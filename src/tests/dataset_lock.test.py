"""Fresh private fixtures; directory descriptor locking, not native qualification."""
import importlib.util
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.python.dataset_lock import DatasetLock
from src.python.remote_development import build_plan, local_fixture

spec = importlib.util.spec_from_file_location('supervisor_fixture', Path(__file__).with_name('sync_supervisor.test.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class DatasetTests(unittest.TestCase):
    def test_cross_process_identical_nested_and_disjoint_in_both_orders(self):
        with tempfile.TemporaryDirectory(prefix='isaac-dataset-lock-') as td:
            root = Path(td)
            a, nested, b = root/'a', root/'a/nested', root/'b'
            nested.mkdir(parents=True); b.mkdir()
            script = ('from src.python.dataset_lock import DatasetLock; import sys\n'
                      'try:\n with DatasetLock(sys.argv[1:]): pass\n'
                      'except ValueError: sys.exit(17)\n')
            for held, attempted, blocked in [(a,a,True),(a,nested,True),(nested,a,True),(a,b,False)]:
                with self.subTest(held=held, attempted=attempted), DatasetLock([str(held)]):
                    run = subprocess.run([sys.executable,'-B','-c',script,str(attempted)],
                                         cwd=Path(__file__).resolve().parents[2], capture_output=True)
                    self.assertEqual(run.returncode,17 if blocked else 0,run.stderr.decode())

    def test_combined_roots_deduplicate_and_upgrade_ancestor(self):
        with tempfile.TemporaryDirectory(prefix='isaac-dataset-lock-') as td:
            a=Path(td)/'a'; child=a/'child'; child.mkdir(parents=True)
            with DatasetLock([str(child),str(a),str(a)]) as lock:
                self.assertEqual(len(lock.evidence),2)
                with self.assertRaises(ValueError): DatasetLock([str(child)]).acquire()
            with DatasetLock([str(child)]): pass

    def test_pin_refuses_parent_traversal_outside_owned_root(self):
        with tempfile.TemporaryDirectory(prefix='isaac-dataset-lock-') as td:
            root=Path(td); a=root/'a'; b=root/'b'; a.mkdir(); b.mkdir()
            with DatasetLock([str(a)]) as lock:
                with self.assertRaises(ValueError): lock.pin([str(a)+'/../b'])

    def test_source_pin_retains_inode_descriptor_and_rejects_replacement(self):
        with tempfile.TemporaryDirectory(prefix='isaac-dataset-lock-') as td:
            root=Path(td); source=root/'source'; source.mkdir()
            with DatasetLock([str(root)]) as lock:
                lock.pin([str(source)])
                identity=(source.stat().st_dev,source.stat().st_ino)
                descriptors = [int(p.name) for p in Path('/proc/self/fd').iterdir()]
                pinned=[]
                for fd in descriptors:
                    try: st=os.fstat(fd)
                    except OSError: continue
                    if (st.st_dev,st.st_ino)==identity: pinned.append(fd)
                self.assertTrue(pinned,'source inode must stay descriptor-pinned, not just stat-saved')
                source.rename(root/'parked'); source.mkdir()
                with self.assertRaises(ValueError): lock.check()


class SupervisorDatasetTests(unittest.TestCase):
    setUp=fixture.SupervisorTests.setUp
    module=fixture.SupervisorTests.module
    supervisor=fixture.SupervisorTests.supervisor
    ready=fixture.SupervisorTests.ready

    def make_other(self, selected, directory):
        directory.mkdir()
        pair=[fixture.FakeEngine(build_plan(selected),'local','DEVICE-A','DEVICE-B'),
              fixture.FakeEngine(build_plan(selected),'remote','DEVICE-B','DEVICE-A')]
        for engine in pair: self.addCleanup(engine.close)
        mod=self.module()
        backend=mod.SyncthingREST(local_url=pair[0].url,remote_url=pair[1].url,
            local_device='DEVICE-A',remote_device='DEVICE-B',local_api_key='synthetic-key',
            remote_api_key='synthetic-key',timeout=.5)
        other=mod.Supervisor(selected,backend=backend,lock_directory=directory)
        self.addCleanup(other.close,activation=True)
        return other

    def test_disjoint_official_supervisors_both_continuous(self):
        selected=dict(self.spec,mappings=[dict(self.spec['mappings'][0],
            local=str(self.root/'local-other'),remote=str(self.root/'remote-other'))])
        for side in ('local','remote'):
            root=Path(selected['mappings'][0][side]); root.mkdir(); (root/'code').write_text('equal')
        first=self.supervisor(); other=self.make_other(selected,self.root/'other-control')
        for s in (first,other):
            s.acquire(readiness=self.ready(s),activation=True); s.resume(activation=True)
        for s in (first,other): self.assertEqual(s.poll(activation=True)['state'],'continuous')

    def test_missing_and_same_bytes_replacement_on_both_directional_senders(self):
        for kind,source_side in (('source','local'),('artifacts','remote')):
            for mutation in ('missing','replacement'):
                for phase in ('resume','poll'):
                    with self.subTest(kind=kind,mutation=mutation,phase=phase):
                        selected=dict(self.spec,mappings=[dict(self.spec['mappings'][0],kind=kind)])
                        s=self.make_other(selected,self.root/(kind+mutation+phase))
                        s.acquire(readiness=self.ready(s),activation=True)
                        if phase=='poll': s.resume(activation=True)
                        source=self.root/source_side; parked=self.root/'parked'
                        source.rename(parked)
                        if mutation=='replacement':
                            source.mkdir(); (source/'code').write_bytes((parked/'code').read_bytes())
                        try:
                            if phase=='resume':
                                with self.assertRaises(ValueError): s.resume(activation=True)
                                receipt=s._receipt()
                            else: receipt=s.poll(activation=True)
                            self.assertNotEqual(receipt['state'],'continuous')
                            self.assertTrue(receipt['dataset_lock_held'])
                            self.assertTrue(receipt['historical_seed_verified'])
                            self.assertEqual(receipt['current_root_verification'],'missing-unreadable-or-identity-changed')
                            self.assertEqual((parked/'code').read_bytes(),b'expected seed bytes')
                        finally:
                            if source.exists(): (source/'code').unlink(); source.rmdir()
                            parked.rename(source); s.stop(activation=True)

    def test_unreadable_selected_root_blocks_poll(self):
        if os.getuid() == 0:
            self.skipTest('permission denial requires unprivileged runner')
        s=self.supervisor(); s.acquire(readiness=self.ready(s),activation=True); s.resume(activation=True)
        root=self.root/'remote'
        root.chmod(0)
        try:
            receipt=s.poll(activation=True)
            self.assertEqual(receipt['state'],'blocked')
            self.assertTrue(receipt['dataset_lock_held'])
            self.assertEqual(receipt['current_root_verification'],'missing-unreadable-or-identity-changed')
        finally:
            root.chmod(0o700)

    def test_ordinary_in_tree_edits_allowed_after_seed_during_poll(self):
        s=self.supervisor(); s.acquire(readiness=self.ready(s),activation=True); s.resume(activation=True)
        (self.root/'local/code').write_bytes(b'ordinary editor change')
        receipt=s.poll(activation=True)
        self.assertEqual(receipt['state'],'continuous')
        self.assertIn('historical',receipt['seed_verification_scope'])
        self.assertEqual(receipt['current_root_verification'],'pinned-identities-match-at-last-check')
        self.assertEqual((self.root/'local/code').read_bytes(),b'ordinary editor change')
        self.assertEqual((self.root/'remote/code').read_bytes(),b'expected seed bytes')

    def test_failed_pause_retains_dataset_after_close_and_exact_recovery(self):
        s=self.supervisor(); s.acquire(readiness=self.ready(s),activation=True); s.resume(activation=True)
        self.engines[0].noop_pause=True
        (self.root/'local').rename(self.root/'parked')
        receipt=s.poll(activation=True)
        self.assertEqual(receipt['state'],'stop-unverified'); self.assertTrue(receipt['dataset_lock_held'])
        (self.root/'parked').rename(self.root/'local')
        receipt=s.close(activation=True)
        self.assertFalse(receipt['writer_owned']) # Preserve original control-fd contract.
        self.assertTrue(receipt['dataset_lock_held'])
        other=self.make_other(self.spec,self.root/'alternate-control')
        with self.assertRaises(ValueError): other.acquire(readiness=self.ready(other),activation=True)
        self.engines[0].noop_pause=False
        self.engines[0].folders['repo']['paused']=True
        recovered=self.supervisor()
        recovered.acquire(readiness=self.ready(recovered),recover=True,activation=True)
        recovered.stop(activation=True)
        other.acquire(readiness=self.ready(other),activation=True); other.stop(activation=True)

    @staticmethod
    def selected_ready(adapter):
        return dict(plan_digest=adapter.plan_digest,transport_reviewed=True,
                    paths_reviewed=True,exclusive_writer_reviewed=True)

    def test_selected_seed_refuses_identical_and_nested_supervisor_dataset(self):
        from src.python.selected_transfer import SelectedTransfer
        for nested in (False,True):
            with self.subTest(nested=nested):
                mapping=dict(self.spec['mappings'][0])
                if nested:
                    for side in ('local','remote'):
                        p=self.root/side/'nested'; p.mkdir(); (p/'code').write_bytes(b'nested seed')
                        mapping[side]=str(p)
                s=self.supervisor(); s.acquire(readiness=self.ready(s),activation=True)
                selected=SelectedTransfer(dict(engine='rsync',mappings=[mapping]))
                try:
                    with self.assertRaisesRegex(ValueError,'writer|overlap'):
                        selected.seed(readiness=self.selected_ready(selected),activation=True)
                finally: s.stop(activation=True)

    def test_selected_ssh_local_roots_conflict_without_inspecting_foreign_roots(self):
        from src.python.selected_transfer import SelectedTransfer
        identity=self.root/'synthetic-identity'; identity.touch()
        trust=self.root/'synthetic-trust'; trust.touch()
        endpoint=dict(host='fixture.invalid',user='fixture',identity_file=str(identity),known_hosts_file=str(trust))
        s=self.supervisor(); s.acquire(readiness=self.ready(s),activation=True)
        for kind in ('source','artifacts'):
            for nested in (False,True):
                local=self.root/'local'
                if nested:
                    local=local/'nested'
                    local.mkdir(exist_ok=True)
                selected=dict(engine='rsync',endpoint=endpoint,mappings=[dict(name='selected',kind=kind,
                    local=str(local),remote=str(self.root/'foreign-absent'),container='/workspaces/selected')])
                with patch('subprocess.run',side_effect=AssertionError('must refuse before transport')) as process:
                    adapter=SelectedTransfer(selected)
                    with self.assertRaisesRegex(ValueError,'writer|overlap'):
                        adapter.seed(readiness=self.selected_ready(adapter),activation=True)
                    process.assert_not_called()
        s.stop(activation=True)

    def test_selected_seed_holds_lock_against_supervisor_before_first_probe(self):
        from src.python.selected_transfer import SelectedTransfer
        s=self.supervisor(); calls=[]
        def runner(argv,**kwargs):
            if not calls:
                with self.assertRaises(ValueError): s.acquire(readiness=self.ready(s),activation=True)
            calls.append(argv)
            return subprocess.run(argv,**kwargs)
        selected=SelectedTransfer(dict(self.spec,engine='rsync'),_process_runner=runner)
        receipt=selected.seed(readiness=self.selected_ready(selected),activation=True)
        self.assertTrue(receipt['local_dataset_exclusion'])
        self.assertFalse(receipt['distributed_lock'])
        s.acquire(readiness=self.ready(s),activation=True); s.stop(activation=True)

    def test_fixture_seed_excludes_supervisor_with_different_control_directory(self):
        with local_fixture() as scope:
            selected=dict(self.spec,mappings=[dict(self.spec['mappings'][0],
                local=str(scope.root/'source'),remote=str(scope.root/'target'))])
            for side in ('local','remote'):
                p=Path(selected['mappings'][0][side]); p.mkdir(); (p/'code').write_text('seed')
            s=self.make_other(selected,self.root/'external-control')
            with scope.writer('rsync'):
                with self.assertRaises(ValueError): s.acquire(readiness=self.ready(s),activation=True)
            s.acquire(readiness=self.ready(s),activation=True)
            with patch('subprocess.run') as process:
                with self.assertRaises(ValueError): scope.transfer(dict(selected,engine='rsync'))
                process.assert_not_called()
            s.stop(activation=True)
            receipt=scope.transfer(dict(selected,engine='rsync'))
            self.assertEqual(receipt['status'],'verified')


class SelectedPhysicalRootTests(unittest.TestCase):
    def test_ssh_names_are_not_opened_locally_and_only_local_root_is_locked(self):
        from src.python.selected_transfer import SelectedTransfer
        module_spec=importlib.util.spec_from_file_location('selected_fixture',Path(__file__).with_name('selected_transfer.test.py'))
        module=importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
        for kind in ('source','artifacts'):
            with self.subTest(kind=kind):
                remote=module.SelectedTransferTests(); remote.setUp()
                try:
                    endpoint,runner,calls,log=remote.remote_fixture()
                    foreign=str(remote.root/'foreign-absent')
                    actual=str(remote.target)
                    (remote.source if kind=='source' else remote.target).joinpath('code').write_bytes(b'physical fixture')
                    selected=dict(remote.spec,endpoint=endpoint,mappings=[dict(remote.spec['mappings'][0],kind=kind,remote=foreign)])
                    def physical_protocol(argv,**kwargs):
                        # Explicit test-only remote namespace translation. Real
                        # fixed probe and fake-SSH rsync server still execute.
                        if kwargs.get('input'):
                            request=json.loads(kwargs['input'])
                            if request['root']==foreign:
                                request['root']=actual; kwargs['input']=json.dumps(request)
                        argv=[a.replace(foreign,actual) for a in argv]
                        return runner(argv,**kwargs)
                    def physical_lease(argv, **kwargs):
                        # Only the fake remote process maps its foreign namespace.
                        # Parent still cannot open foreign-absent locally.
                        command = shlex.split(argv[-1])
                        command[-1] = ("import os\n_original_open = os.open\n" +
                            "def _fixture_open(path, *a, **kw):\n" +
                            "    return _original_open('target' if path == 'foreign-absent' else path, *a, **kw)\n" +
                            "os.open = _fixture_open\n" + command[-1])
                        return remote._lease_factory([*argv[:-1], shlex.join(command)], **kwargs)
                    adapter=SelectedTransfer(selected,_process_runner=physical_protocol,
                                             _lease_process_factory=physical_lease)
                    receipt=adapter.seed(readiness=SupervisorDatasetTests.selected_ready(adapter),activation=True)
                    self.assertEqual(receipt['status'],'verified')
                    self.assertEqual([e['path'] for e in receipt['local_root_identity_evidence']],[str(remote.source)])
                    self.assertEqual(receipt['remote_writer_exclusion'],'cooperative-remote-directory-inodes')
                    self.assertFalse(Path(foreign).exists())
                    self.assertEqual((remote.source/'code').read_bytes(),(remote.target/'code').read_bytes())
                finally:
                    remote.doCleanups()


class LocalSeedDatasetTests(unittest.TestCase):
    def test_same_byte_source_replacement_during_seed_is_not_verified(self):
        for kind, source_side in (('source','local'),('artifacts','remote')):
            with self.subTest(kind=kind), local_fixture() as scope:
                for side in ('local','remote'):
                    p=scope.root/side; p.mkdir(); (p/'code').write_bytes(b'expected')
                selected=dict(engine='rsync',mappings=[dict(name='data',kind=kind,
                    local=str(scope.root/'local'),remote=str(scope.root/'remote'),container='/workspaces/data')])
                source=scope.root/source_side
                def replace_source(*args,**kwargs):
                    source.rename(scope.root/'parked')
                    source.mkdir(); (source/'code').write_bytes(b'expected')
                    return subprocess.CompletedProcess(args[0],0)
                with patch('subprocess.run',side_effect=replace_source):
                    with self.assertRaisesRegex(ValueError,'identity changed'):
                        scope.transfer(selected)
                self.assertEqual((scope.root/'parked/code').read_bytes(),b'expected')
                self.assertEqual((source/'code').read_bytes(),b'expected')


if __name__=='__main__': unittest.main()
