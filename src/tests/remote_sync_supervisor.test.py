"""Offline protocol fixtures only: fake SSH subprocesses, NOT native proof."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from typing import Any

from src.python.dataset_lock import DatasetLock, DatasetLockError
from src.python.file_transfer import TransferEndpoint


class LeaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-remote-protocol-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote'
        self.remote.mkdir()
        self.endpoint = TransferEndpoint(host='host.invalid', user='fixture',
            identity_file=str(self.root / 'identity'), known_hosts_file=str(self.root / 'trust'),
            inspect_paths=False)
        self.calls = []
        self.contexts = []

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.remote_sync_supervisor'),
                             'persistent remote lease implementation missing')
        return importlib.import_module('src.python.remote_sync_supervisor')

    def factory(self, argv, **kwargs):
        self.calls.append(argv)
        self.contexts.append(dict(kwargs['env']))
        self.assertEqual(argv[0], '/usr/bin/ssh')
        self.assertIn('fixture@host.invalid', argv)
        fixed = shlex.split(argv[-1])
        self.assertEqual(fixed[:5], ['/usr/bin/python3', '-I', '-S', '-B', '-c'])
        return subprocess.Popen(fixed, **kwargs)

    def lease(self, root=None, **kwargs):
        lease = self.module().RemoteLease(self.endpoint,
            [{'root': str(root or self.remote), 'excludes': ['.env']}],
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, cwd=str(self.root),
            _process_factory=self.factory, **kwargs)
        self.addCleanup(lease.close)
        return lease


class RemoteLeaseTests(LeaseFixture):
    def test_malformed_manifest_permanently_poisons_remote_session(self):
        module = self.module()
        script = """import json, sys
request = json.loads(sys.stdin.readline())
root = request['selections'][0]['root']
print(json.dumps(dict(version=1,id=1,ok=True,result=[dict(path=root,device=1,inode=2)])),flush=True)
request = json.loads(sys.stdin.readline())
print(json.dumps(dict(version=1,id=2,ok=True,result=True)),flush=True)
sys.stdin.read()
"""
        def fake(argv, **kwargs):
            return subprocess.Popen(['/usr/bin/python3', '-I', '-S', '-B', '-c', script], **kwargs)
        lease = module.RemoteLease(self.endpoint, [{'root': str(self.remote), 'excludes': []}],
            env={'PATH': '/usr/bin:/bin'}, cwd=str(self.root), _process_factory=fake, timeout=.2)
        self.addCleanup(lease.close)
        lease.acquire(activation=True)
        with self.assertRaises(ValueError):
            lease.observe(0)
        self.assertTrue(lease._failed, 'Malformed metadata must poison the persistent lease')

    def test_remote_root_ancestor_replacement_is_not_silently_reacquired(self):
        lease = self.lease().acquire(activation=True)
        self.remote.rename(self.root / 'old-remote')
        self.remote.mkdir()
        with self.assertRaisesRegex(ValueError, 'lost|identity'):
            lease.check()
        self.assertTrue(lease._failed)

    def test_nested_remote_lock_overlap_and_sibling_independence(self):
        child = self.remote / 'child'
        child.mkdir()
        sibling = self.root / 'sibling'
        sibling.mkdir()
        lease = self.lease().acquire(activation=True)
        with self.assertRaises(ValueError):
            self.lease(root=child).acquire(activation=True)
        self.lease(root=sibling).acquire(activation=True).check()
        lease.close()

    def test_protocol_timeout_and_eof_have_no_receipt(self):
        for script in ('import time; time.sleep(2)', 'pass'):
            def fake(argv, **kwargs):
                return subprocess.Popen(['/usr/bin/python3', '-I', '-S', '-c', script], **kwargs)
            lease = self.module().RemoteLease(self.endpoint,
                [{'root': str(self.remote), 'excludes': []}], env={'PATH': '/usr/bin:/bin'},
                cwd=str(self.root), _process_factory=fake, timeout=.03)
            with self.assertRaisesRegex(ValueError, 'lost'):
                lease.acquire(activation=True)
            self.assertTrue(lease._failed)

    def test_unknown_operation_and_oversized_response_poison_protocol(self):
        lease = self.lease().acquire(activation=True)
        with self.assertRaises(ValueError):
            lease._request('exec', command='never-executed')
        self.assertTrue(lease._failed)
        def oversized(argv, **kwargs):
            return subprocess.Popen(['/usr/bin/python3', '-I', '-S', '-c',
                "import sys; sys.stdin.readline(); sys.stdout.write('x' * (8*1024*1024+1)); sys.stdout.flush()"], **kwargs)
        lease = self.module().RemoteLease(self.endpoint, [{'root': str(self.remote), 'excludes': []}],
            env={'PATH': '/usr/bin:/bin'}, cwd=str(self.root), _process_factory=oversized, timeout=1)
        with self.assertRaises(ValueError):
            lease.acquire(activation=True)
        self.assertTrue(lease._failed)

    def test_persistent_remote_descriptor_excludes_other_process_until_close(self):
        (self.remote / 'included').write_bytes(b'fixture bytes')
        os.mkfifo(self.remote / '.env')
        lease = self.lease().acquire(activation=True)
        first = lease.observe(0)
        self.assertEqual(first['entries']['included']['kind'], 'file')
        self.assertIn('.env', first['excluded'])
        self.assertEqual(first['root_identity'], lease.observe(0)['root_identity'])
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(DatasetLockError):
            DatasetLock([str(self.remote)]).acquire()
        lease.check()
        lease.close()
        with DatasetLock([str(self.remote)]):
            pass


class SelectedFixture(LeaseFixture):
    def adapter(self, *, kind='source', runner=None, iap=False):
        from src.python.selected_transfer import SelectedTransfer
        self.local = self.root / ('local-' + kind)
        self.local.mkdir(exist_ok=True)
        for name in ('identity', 'trust'):
            (self.root / name).touch()
        self.spec: dict[str, Any] = dict(engine='rsync', endpoint=dict(host='host.invalid', user='fixture',
            identity_file=str(self.root / 'identity'), known_hosts_file=str(self.root / 'trust')),
            mappings=[dict(name='code', kind=kind, local=str(self.local), remote=str(self.remote),
                           container='/workspace/code')])
        if iap:
            self.spec['endpoint'].update(iap=True, instance='fixture-vm', project='fixture-project', zone='fixture-zone')
        return SelectedTransfer(self.spec, _process_runner=runner or self.runner,
                                _lease_process_factory=self.factory)

    def runner(self, argv, **kwargs):
        actual = list(argv)
        if actual[0] == '/usr/bin/rsync':
            # Fake transport seam: keep the generated rsync policy but replace
            # only the fixture remote endpoint with its temporary local path.
            index = actual.index('-e')
            del actual[index:index+2]
            actual.remove('--rsync-path=/usr/bin/rsync')
            actual = [a.removeprefix('fixture@host.invalid:') for a in actual]
        self.assertNotEqual(actual[0], '/usr/bin/ssh', 'no real SSH in tests')
        return subprocess.run(actual, **kwargs)

    def ready(self, adapter):
        return dict(plan_digest=adapter.plan_digest, transport_reviewed=True,
                    paths_reviewed=True, exclusive_writer_reviewed=True)


class SelectedLeaseTests(SelectedFixture):
    def test_native_marker_requires_verified_paused_supervisor_not_attestation(self):
        adapter = self.adapter()
        (self.remote / '.stfolder').mkdir()
        with self.assertRaisesRegex(ValueError, 'paused.supervisor'):
            adapter.seed(readiness=self.ready(adapter), activation=True)

    def test_official_push_and_pull_hold_both_physical_dataset_locks(self):
        for kind in ('source', 'artifacts'):
            with self.subTest(kind=kind):
                def checked(argv, **kwargs):
                    if argv[0] == '/usr/bin/rsync':
                        for root in (self.local, self.remote):
                            with self.assertRaises(DatasetLockError):
                                DatasetLock([str(root)]).acquire()
                    return self.runner(argv, **kwargs)
                adapter = self.adapter(kind=kind, runner=checked)
                source = self.local if kind == 'source' else self.remote
                (source / 'included').write_bytes(b'selected bytes')
                receipt = adapter.seed(readiness=self.ready(adapter), activation=True)
                self.assertEqual(receipt['status'], 'verified')
                self.assertEqual(receipt['remote_writer_exclusion'], 'cooperative-remote-directory-inodes')
                self.assertEqual((self.local / 'included').read_bytes(), (self.remote / 'included').read_bytes())


class RemoteSupervisorTests(SelectedFixture):
    def supervisor(self, *, iap=False, kind='source'):
        self.adapter(iap=iap, kind=kind)
        spec = dict(self.spec, engine='syncthing', delete_approved=True)
        from src.python.remote_development import build_plan
        from src.python.sync_supervisor import SyncthingREST
        fixture_spec = importlib.util.spec_from_file_location('remote_rest_protocol_fixture',
            Path(__file__).with_name('sync_supervisor.test.py'))
        assert fixture_spec is not None and fixture_spec.loader is not None
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        plan = build_plan(spec)
        self.engines = [fixture.FakeEngine(plan, 'local', 'DEVICE-A', 'DEVICE-B'),
                        fixture.FakeEngine(plan, 'remote', 'DEVICE-B', 'DEVICE-A')]
        for engine in self.engines:
            self.addCleanup(engine.close)
        backend = SyncthingREST(local_url=self.engines[0].url, remote_url=self.engines[1].url,
            local_device='DEVICE-A', remote_device='DEVICE-B', local_api_key='synthetic-key',
            remote_api_key='synthetic-key', timeout=1)
        supervisor = self.module().RemoteSupervisor(spec, backend=backend,
            rest_contexts={'local': 'local-loopback', 'remote': 'forwarded-loopback'},
            _process_runner=self.runner, _lease_process_factory=self.factory)
        self.addCleanup(supervisor.close, activation=True)
        return supervisor

    def supervisor_ready(self, supervisor):
        return dict(plan_digest=supervisor.plan_digest, transport_reviewed=True,
            paths_reviewed=True, rest_contexts_reviewed=True, recovery_verified=True,
            deletion_approved=True)

    def test_iap_pull_preserves_only_selected_context_without_starting_tunnel(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {'CLOUDSDK_CONFIG': str(self.root / 'synthetic-gcloud-context'),
                'CLOUDSDK_ACTIVE_CONFIG_NAME': 'fixture', 'LD_PRELOAD': 'forbidden', 'RSYNC_RSH': 'forbidden'}):
            supervisor = self.supervisor(iap=True, kind='artifacts')
            (self.remote / 'returned').write_bytes(b'fixture pull')
            supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
            supervisor.seed(readiness=self.supervisor_ready(supervisor), activation=True)
            self.assertEqual((self.local / 'returned').read_bytes(), b'fixture pull')
            supervisor.resume(activation=True)
            self.assertEqual(supervisor.poll(activation=True)['state'], 'continuous')
        self.assertTrue(any('ProxyCommand=gcloud compute start-iap-tunnel' in a for a in self.calls[0]))
        self.assertEqual(self.contexts[0]['CLOUDSDK_ACTIVE_CONFIG_NAME'], 'fixture')
        self.assertNotIn('LD_PRELOAD', self.contexts[0])
        self.assertNotIn('RSYNC_RSH', self.contexts[0])
        self.assertFalse((self.root / 'synthetic-gcloud-context').exists())

    def running(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
        supervisor.verify_seed(readiness=self.supervisor_ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        return supervisor

    def test_remote_session_loss_blocks_and_verifies_best_effort_pause(self):
        supervisor = self.running()
        supervisor._lease._process.kill()
        supervisor._lease._process.wait(timeout=2)
        receipt = supervisor.poll(activation=True)
        self.assertEqual(receipt['state'], 'blocked')
        self.assertTrue(receipt['manual_recovery_required'])
        self.assertTrue(receipt['verified_paused'])
        self.assertFalse(receipt['remote_lease_held'])
        self.assertNotEqual(receipt['current_root_verification'], 'pinned-identities-match-at-last-check')
        with self.assertRaises(ValueError):
            supervisor.resume(activation=True)

    def test_close_detects_lost_lease_even_without_an_intervening_poll(self):
        supervisor = self.running()
        supervisor._lease._process.kill()
        supervisor._lease._process.wait(timeout=2)
        result = supervisor.close(activation=True)
        self.assertTrue(result['manual_recovery_required'])
        self.assertEqual(result['current_root_verification'], 'lost-session-or-root-identity')
        self.assertTrue(result['verified_paused'])

    def test_failed_pause_retains_dataset_and_surviving_lease_until_manual_close(self):
        supervisor = self.running()
        self.engines[1].noop_pause = True
        self.engines[0].conflict = True
        receipt = supervisor.poll(activation=True)
        self.assertEqual(receipt['state'], 'stop-unverified')
        receipt = supervisor.close(activation=True)
        self.assertFalse(receipt['verified_paused'])
        self.assertTrue(receipt['manual_recovery_required'])
        for root in (self.local, self.remote):
            with self.assertRaises(DatasetLockError):
                DatasetLock([str(root)]).acquire()
        self.engines[1].noop_pause = False
        self.engines[0].conflict = False
        self.assertEqual(supervisor.close(activation=True)['state'], 'stopped')

    def test_remote_replacement_cannot_be_adopted_during_poll(self):
        supervisor = self.running()
        self.remote.rename(self.root / 'old')
        self.remote.mkdir()
        result = supervisor.poll(activation=True)
        self.assertEqual(result['state'], 'blocked')
        self.assertTrue(result['manual_recovery_required'])
        self.assertTrue(result['verified_paused'])

    def test_new_peer_config_or_generation_is_never_healthy(self):
        supervisor = self.running()
        self.engines[1].folders['code']['devices'].append({'deviceID': 'UNREVIEWED'})
        result = supervisor.poll(activation=True)
        self.assertEqual(result['state'], 'stop-unverified')
        self.engines[1].folders['code']['devices'].pop()
        supervisor.close(activation=True)

    def test_no_local_foreign_path_open_during_preflight_seed_and_poll(self):
        from unittest import mock
        supervisor = self.supervisor()
        original_walk = DatasetLock._walk
        def local_walk(path):
            self.assertNotEqual(path, str(self.remote), 'remote filesystem must travel only over SSH')
            return original_walk(path)
        with mock.patch.object(DatasetLock, '_walk', side_effect=local_walk):
            supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
            supervisor.seed(readiness=self.supervisor_ready(supervisor), activation=True)
            supervisor.resume(activation=True)
            self.assertEqual(supervisor.poll(activation=True)['state'], 'continuous')
            supervisor.close(activation=True)

    def test_every_lifecycle_action_requires_explicit_activation(self):
        supervisor = self.supervisor()
        ready = self.supervisor_ready(supervisor)
        for name in ('acquire', 'seed', 'verify_seed', 'resume', 'poll', 'pause', 'close'):
            kwargs = {'readiness': ready} if name in ('acquire', 'seed', 'verify_seed') else {}
            with self.subTest(name=name), self.assertRaises(ValueError):
                getattr(supervisor, name)(**kwargs)
        self.assertEqual(self.calls, [])
        self.assertFalse(any(e.calls for e in self.engines))
        with self.assertRaises(ValueError):
            supervisor.acquire(readiness=dict(ready, rest_contexts_reviewed=False), activation=True)
        self.assertEqual(self.calls, [])

    def test_resume_refuses_seed_changed_on_both_hosts(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
        supervisor.verify_seed(readiness=self.supervisor_ready(supervisor), activation=True)
        for root in (self.local, self.remote):
            (root / 'changed').write_bytes(b'new matching but unreviewed bytes')
        with self.assertRaisesRegex(ValueError, 'seed changed'):
            supervisor.resume(activation=True)
        self.assertTrue(supervisor._manual)
        self.assertFalse(any(e.resumed.is_set() for e in self.engines))

    def test_another_official_seed_cannot_bypass_remote_lease_with_different_local_root(self):
        supervisor = self.running()
        from src.python.selected_transfer import SelectedTransfer
        other_local = self.root / 'other-local'
        other_local.mkdir()
        for kind in ('source', 'artifacts'):
            spec = dict(self.spec, mappings=[dict(self.spec['mappings'][0], local=str(other_local), kind=kind)])
            transfer = SelectedTransfer(spec, _process_runner=self.runner, _lease_process_factory=self.factory)
            with self.assertRaisesRegex(ValueError, 'lease'):
                transfer.seed(readiness=self.ready(transfer), activation=True)
        self.assertEqual(supervisor.poll(activation=True)['state'], 'continuous')

    def test_direct_borrowed_seed_receipt_does_not_claim_seed_only_locks(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
        receipt = supervisor._transfer.seed(readiness=self.ready(supervisor._transfer),
                                            activation=True, supervisor=supervisor)
        self.assertEqual(receipt['local_dataset_lock_scope'], 'cooperative-directory-inodes-borrowed-supervisor-session')
        self.assertEqual(receipt['remote_root_identity_evidence'][0]['path'], str(self.remote))

    def test_direct_selected_borrowed_seed_failure_blocks_supervisor(self):
        supervisor = self.supervisor()
        (self.local / 'code').write_bytes(b'bytes not copied by a zero-exit process')
        supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
        original = supervisor._transfer._runner
        def noop(argv, **kwargs):
            if argv[0] == '/usr/bin/rsync':
                return subprocess.CompletedProcess(argv, 0, '', '')
            return original(argv, **kwargs)
        supervisor._transfer._runner = noop
        with self.assertRaises(ValueError):
            supervisor._transfer.seed(readiness=self.ready(supervisor._transfer), activation=True,
                                      supervisor=supervisor)
        self.assertTrue(supervisor._manual, 'Borrowed seed failure must poison the owning session')
        self.assertEqual(supervisor.state, 'blocked')

    def test_generation_change_during_pause_is_not_a_healthy_paused_receipt(self):
        supervisor = self.running()
        self.engines[0].start = 'a-new-native-process'
        with self.assertRaises(ValueError):
            supervisor.pause(activation=True)
        self.assertTrue(supervisor._manual)

    def test_native_already_running_cannot_be_adopted(self):
        supervisor = self.supervisor()
        self.engines[0].folders['code']['paused'] = False
        with self.assertRaisesRegex(ValueError, 'paused'):
            supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
        self.assertTrue(supervisor._manual)

    def test_paused_preflight_seed_resume_poll_pause_uses_one_shared_remote_lease(self):
        supervisor = self.supervisor()
        (self.local / 'code').write_bytes(b'initial seed')
        for root in (self.local, self.remote):
            (root / '.stfolder').mkdir()
        receipt = supervisor.acquire(readiness=self.supervisor_ready(supervisor), activation=True)
        self.assertEqual(receipt['state'], 'paused-unseeded')
        receipt = supervisor.seed(readiness=self.supervisor_ready(supervisor), activation=True)
        self.assertTrue(receipt['historical_seed_verified'])
        self.assertEqual((self.remote / 'code').read_bytes(), b'initial seed')
        self.assertEqual(supervisor.resume(activation=True)['state'], 'continuous')
        self.assertEqual(supervisor.poll(activation=True)['state'], 'continuous')
        self.assertEqual(len(self.calls), 1, 'seed must borrow rather than reacquire the remote lease')
        for root in (self.local, self.remote):
            with self.assertRaises(DatasetLockError):
                DatasetLock([str(root)]).acquire()
        self.assertEqual(supervisor.pause(activation=True)['state'], 'paused')
        self.assertEqual(supervisor.close(activation=True)['state'], 'stopped')
        for root in (self.local, self.remote):
            with DatasetLock([str(root)]):
                pass


if __name__ == '__main__':
    unittest.main()
