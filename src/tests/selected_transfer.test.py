"""Offline selected seed qualification: fresh data and controlled processes only."""
import copy
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
from unittest import mock


class SelectedTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-selected-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self._lease_factory = None
        self.source = self.root / 'source'
        self.target = self.root / 'target'
        self.source.mkdir()
        self.target.mkdir()
        self.spec: dict[str, Any] = dict(engine='rsync', mappings=[dict(name='code', kind='source',
            local=str(self.source), remote=str(self.target), container='/workspace/code')])

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.selected_transfer'),
                             'selected transfer implementation is missing')
        return importlib.import_module('src.python.selected_transfer')

    def readiness(self, adapter):
        return dict(plan_digest=adapter.plan_digest, transport_reviewed=True,
                    paths_reviewed=True, exclusive_writer_reviewed=True)

    def remote_fixture(self, *, iap=False):
        """A fake SSH executable runs real local rsync --server, never a socket."""
        endpoint: dict[str, Any] = dict(host='host.invalid', user='fixture',
                        identity_file=str(self.root / 'never-read-identity'),
                        known_hosts_file=str(self.root / 'never-read-known-hosts'))
        if iap:
            endpoint.update(iap=True, instance='vm-fixture', project='fixture-project', zone='fixture-zone')
        # Synthetic empty metadata fixtures; no actual credentials are inspected.
        Path(endpoint['identity_file']).touch()
        Path(endpoint['known_hosts_file']).touch()
        log = self.root / 'protocol.jsonl'
        script = self.root / 'fake_transport.py'
        script.write_text('import json, os, shlex, sys\n'
            + 'args = sys.argv[1:]\n'
            + 'host = "fixture@host.invalid" if "fixture@host.invalid" in args else "host.invalid"\n'
            + 'command = shlex.split(" ".join(args[args.index(host) + 1:]))\n'
            + 'with open(' + repr(str(log)) + ', "a") as out: out.write(json.dumps(command) + "\\n")\n'
            + 'if command[0] == "rsync": command[0] = "/usr/bin/rsync"\n'
            + 'assert command[0] in ("/usr/bin/python3", "/usr/bin/rsync")\n'
            + 'os.execv(command[0], command)\n')
        executable = self.root / 'fake-ssh'
        executable.write_text('#!/bin/sh\nexec /usr/bin/python3 -I -S ' + shlex.quote(str(script)) + ' "$@"\n')
        executable.chmod(0o700)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            actual = list(argv)
            if actual[0] == '/usr/bin/ssh':
                actual[0] = str(executable)
            elif actual[0] == '/usr/bin/rsync' and '-e' in actual:
                index = actual.index('-e') + 1
                ssh = shlex.split(actual[index])
                self.assertEqual(ssh[0], '/usr/bin/ssh')
                actual[index] = shlex.join([str(executable), *ssh[1:]])
            else:
                self.assertEqual(actual[0], '/usr/bin/python3')
            return subprocess.run(actual, **kwargs)
        def lease_factory(argv, **kwargs):
            calls.append(list(argv))
            self.assertEqual(argv[0], '/usr/bin/ssh')
            return subprocess.Popen([str(executable), *argv[1:]], **kwargs)
        self._lease_factory = lease_factory
        return endpoint, runner, calls, log

    def test_ssh_push_and_iap_pull_use_actual_controlled_server_transport(self):
        for iap, direction in ((False, 'source'), (True, 'artifacts')):
            with self.subTest(iap=iap):
                endpoint, runner, calls, log = self.remote_fixture(iap=iap)
                (self.source / 'sample').write_bytes(b'controlled cross-endpoint bytes')
                if direction == 'artifacts':
                    (self.source / 'sample').unlink()
                    (self.target / 'sample').write_bytes(b'artifact return bytes')
                spec = copy.deepcopy(self.spec)
                spec['endpoint'] = endpoint
                spec['mappings'][0]['kind'] = direction
                adapter = self.module().SelectedTransfer(spec, _process_runner=runner, _lease_process_factory=self._lease_factory)
                result = adapter.seed(readiness=self.readiness(adapter), activation=True)
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['scope'], 'selected-ssh-iap' if iap else 'selected-ssh')
                self.assertEqual((self.source / 'sample').read_bytes(), (self.target / 'sample').read_bytes())
                transports = [c for c in calls if c[0] == '/usr/bin/ssh']
                self.assertTrue(transports)
                self.assertTrue(any(c[0] == '/usr/bin/rsync' and '-e' in c for c in calls))
                protocols = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertTrue(any(c[0] == '/usr/bin/rsync' and '--server' in c for c in protocols))
                probes = [c for c in protocols if c[0] == '/usr/bin/python3']
                self.assertTrue(probes)
                self.assertTrue(all(c[1:4] == ['-I', '-S', '-B'] for c in probes))
                self.assertEqual(any('ProxyCommand=gcloud compute start-iap-tunnel' in a
                                    for c in transports for a in c), iap)
                self.assertEqual(Path(endpoint['identity_file']).read_bytes(), b'')
                self.assertEqual(Path(endpoint['known_hosts_file']).read_bytes(), b'')

    def test_iap_preserves_explicit_existing_auth_context_not_ambient_hooks(self):
        endpoint, runner, calls, log = self.remote_fixture(iap=True)
        contexts = []
        def inspect(argv, **kwargs):
            contexts.append(dict(kwargs['env']))
            return runner(argv, **kwargs)
        spec = dict(self.spec, endpoint=endpoint)
        config = str(self.root / 'synthetic-gcloud-context')
        with mock.patch.dict(os.environ, {'CLOUDSDK_CONFIG': config,
                'CLOUDSDK_ACTIVE_CONFIG_NAME': 'selected', 'LD_PRELOAD': 'forbidden',
                'RSYNC_RSH': 'forbidden', 'PYTHONPATH': 'forbidden'}):
            adapter = self.module().SelectedTransfer(spec, _process_runner=inspect, _lease_process_factory=self._lease_factory)
            adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertTrue(contexts)
        for env in contexts:
            self.assertEqual(env.get('CLOUDSDK_CONFIG'), config)
            self.assertEqual(env.get('CLOUDSDK_ACTIVE_CONFIG_NAME'), 'selected')
            self.assertNotIn('LD_PRELOAD', env)
            self.assertNotIn('RSYNC_RSH', env)
            self.assertNotIn('PYTHONPATH', env)
        self.assertFalse(Path(config).exists())

    def test_auth_paths_cannot_be_inside_selected_local_data_even_arbitrary_names(self):
        endpoint, runner, calls, log = self.remote_fixture()
        for field in ('identity_file', 'known_hosts_file'):
            bad = dict(endpoint, **{field: str(self.source / 'ordinary-name')})
            with self.assertRaisesRegex(ValueError, 'identity|trust'):
                self.module().SelectedTransfer(dict(self.spec, endpoint=bad), _process_runner=runner, _lease_process_factory=self._lease_factory)
        self.assertEqual(calls, [])

    def test_reserved_partial_directory_symlink_is_rejected_before_rsync(self):
        endpoint, runner, calls, log = self.remote_fixture()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.target / '.rsync-partial').symlink_to(outside, target_is_directory=True)
        adapter = self.module().SelectedTransfer(dict(self.spec, endpoint=endpoint), _process_runner=runner, _lease_process_factory=self._lease_factory)
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))
        self.assertEqual(list(outside.iterdir()), [])

    def test_cross_side_case_collision_is_rejected_before_rsync(self):
        (self.source / 'Code').write_bytes(b'incoming')
        (self.target / 'code').write_bytes(b'existing')
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.run(argv, **kwargs)
        adapter = self.module().SelectedTransfer(dict(self.spec, initial_seed='reviewed-overwrite',
            overwrite_approved=True), _process_runner=runner, _lease_process_factory=self._lease_factory)
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))

    def test_remote_probe_boolean_or_malformed_manifest_cannot_verify_a_seed(self):
        endpoint, runner, calls, log = self.remote_fixture()
        for bad in ({'entries': {}, 'excluded': {}, 'root_identity': True},
                    {'entries': {'../escape': {'kind': 'file', 'sha256': 'a' * 64, 'stamp': [1] * 9}},
                     'excluded': {}, 'root_identity': [1, 2, 3]}):
            with self.subTest(bad=bad):
                # Fault injection belongs to the persistent protocol seam now,
                # not the old one-shot subprocess.run probe seam.
                script = "import json, os, sys\nBAD=" + repr(bad) + "\n" + """
for line in sys.stdin:
    request = json.loads(line)
    if request['op'] == 'acquire':
        roots = [s['root'] for s in request['selections']]
        evidence = [dict(path=p, device=os.stat(p).st_dev, inode=os.stat(p).st_ino) for p in roots]
    result = BAD if request['op'] == 'observe' else evidence
    print(json.dumps(dict(version=1,id=request['id'],ok=True,result=result)),flush=True)
"""
                def malformed_factory(argv, **kwargs):
                    return subprocess.Popen(['/usr/bin/python3', '-I', '-S', '-c', script], **kwargs)
                adapter = self.module().SelectedTransfer(dict(self.spec, endpoint=endpoint),
                    _process_runner=runner, _lease_process_factory=malformed_factory)
                with self.assertRaisesRegex(ValueError, 'manifest'):
                    adapter.seed(readiness=self.readiness(adapter), activation=True)
                self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))

    def test_all_mappings_preflight_before_any_transfer(self):
        endpoint, runner, calls, log = self.remote_fixture()
        (self.source / 'good').write_bytes(b'first mapping must not transfer')
        spec = copy.deepcopy(self.spec)
        spec['endpoint'] = endpoint
        spec['mappings'].append(dict(name='missing', kind='artifacts', local=str(self.root / 'missing-local'),
                                     remote=str(self.root / 'missing-remote'), container='/output/missing'))
        adapter = self.module().SelectedTransfer(spec, _process_runner=runner, _lease_process_factory=self._lease_factory)
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))

    def test_exclusions_skip_protected_bytes_and_preserve_all_shared_filters(self):
        endpoint, runner, calls, log = self.remote_fixture()
        (self.source / 'normal').write_bytes(b'included')
        # FIFOs prove excluded contents are never opened; scanner rejects them
        # if unexcluded. No real secret/config/cache data is involved.
        for root in (self.source, self.target):
            for folder in ('.venv', '.cache', 'databases', '.devcontainer', 'rescue'):
                (root / folder).mkdir()
                os.mkfifo(root / folder / 'never-open')
            os.mkfifo(root / '.env')
        spec = dict(self.spec, endpoint=endpoint, protected_paths=[
            dict(namespace='remote', path=str(self.target / 'rescue'))])
        adapter = self.module().SelectedTransfer(spec, _process_runner=runner, _lease_process_factory=self._lease_factory)
        result = adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertEqual(result['manifests'], {'code': {'normal': __import__('hashlib').sha256(b'included').hexdigest()}})
        argv = next(c for c in calls if c[0] == '/usr/bin/rsync')
        from src.python.remote_development import build_plan
        excludes = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == '--exclude']
        self.assertEqual(excludes, [p.rstrip('/') for p in build_plan(spec)['mappings'][0]['excludes']])
        self.assertFalse(any(a.startswith('--delete') for a in argv))
        self.assertTrue((self.target / '.env').is_fifo())
        self.assertTrue((self.target / 'rescue/never-open').is_fifo())

    def test_reviewed_overwrite_uses_checksum_and_retains_unselected_destination_files(self):
        (self.source / 'sample').write_bytes(b'NEW')
        (self.target / 'sample').write_bytes(b'OLD')
        (self.target / 'retained').write_bytes(b'retain')
        for path in (self.source / 'sample', self.target / 'sample'):
            os.utime(path, ns=(1700000000000000000, 1700000000000000000))
        adapter = self.module().SelectedTransfer(dict(self.spec, initial_seed='reviewed-overwrite', overwrite_approved=True))
        adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertEqual((self.target / 'sample').read_bytes(), b'NEW')
        self.assertEqual((self.target / 'retained').read_bytes(), b'retain')

    def test_zero_exit_noop_and_equal_changed_endpoints_do_not_verify(self):
        endpoint, runner, calls, log = self.remote_fixture()
        for mode in ('noop', 'both', 'target', 'protected'):
            with self.subTest(mode=mode):
                (self.source / 'sample').write_bytes(b'pinned')
                (self.target / 'sample').unlink(missing_ok=True)
                (self.target / '.env').write_bytes(b'synthetic excluded bytes')
                def corrupt(argv, **kwargs):
                    if argv[0] == '/usr/bin/rsync' and mode == 'noop':
                        return subprocess.CompletedProcess(argv, 0, '', '')
                    result = runner(argv, **kwargs)
                    if argv[0] == '/usr/bin/rsync':
                        if mode == 'both':
                            (self.source / 'sample').write_bytes(b'changed')
                        if mode in ('both', 'target'):
                            (self.target / 'sample').write_bytes(b'changed')
                        if mode == 'protected':
                            (self.target / '.env').write_bytes(b'mutated excluded bytes')
                    return result
                adapter = self.module().SelectedTransfer(dict(self.spec, endpoint=endpoint), _process_runner=corrupt, _lease_process_factory=self._lease_factory)
                with self.assertRaisesRegex(ValueError, 'verification|drift'):
                    adapter.seed(readiness=self.readiness(adapter), activation=True)

    def test_pretransfer_drift_prevents_launch(self):
        (self.source / 'sample').write_bytes(b'pinned')
        calls = []
        def mutate(argv, **kwargs):
            calls.append(argv)
            result = subprocess.run(argv, **kwargs)
            # After both initial probes, invalidate the pinned source.
            if len(calls) == 2:
                (self.source / 'sample').write_bytes(b'changed')
            return result
        adapter = self.module().SelectedTransfer(self.spec, _process_runner=mutate, _lease_process_factory=self._lease_factory)
        with self.assertRaisesRegex(ValueError, 'drift'):
            adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))

    def test_unsupported_modes_and_false_readiness_do_not_launch(self):
        module = self.module()
        never = mock.Mock(side_effect=AssertionError('must not launch'))
        for changed in (dict(engine='syncthing'), dict(engine='mutagen'), dict(delete=True, delete_approved=True)):
            adapter = module.SelectedTransfer(dict(self.spec, **changed), _process_runner=never, _lease_process_factory=self._lease_factory)
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                adapter.seed(readiness=self.readiness(adapter), activation=True)
        adapter = module.SelectedTransfer(self.spec, _process_runner=never, _lease_process_factory=self._lease_factory)
        for changed in (dict(plan_digest='not-this-selection'), dict(paths_reviewed=False),
                        dict(exclusive_writer_reviewed=1), dict(recovery_verified=True)):
            with self.assertRaisesRegex(ValueError, 'readiness'):
                adapter.seed(readiness=dict(self.readiness(adapter), **changed), activation=True)
        never.assert_not_called()

    def test_symlinks_hardlinks_special_files_and_type_conflicts_stop_before_rsync(self):
        for mode in ('symlink', 'hardlink', 'fifo', 'type-conflict'):
            with self.subTest(mode=mode):
                for root in (self.source, self.target):
                    for path in root.iterdir():
                        if path.is_dir() and not path.is_symlink():
                            path.rmdir()
                        else:
                            path.unlink()
                if mode == 'symlink':
                    (self.source / 'item').symlink_to(self.root / 'not-selected')
                elif mode == 'hardlink':
                    (self.source / 'item').write_bytes(b'fixture')
                    os.link(self.source / 'item', self.source / 'alias')
                elif mode == 'fifo':
                    os.mkfifo(self.source / 'item')
                else:
                    (self.source / 'item').mkdir()
                    (self.target / 'item').write_bytes(b'conflict')
                calls = []
                def runner(argv, **kwargs):
                    calls.append(argv)
                    return subprocess.run(argv, **kwargs)
                adapter = self.module().SelectedTransfer(self.spec, _process_runner=runner, _lease_process_factory=self._lease_factory)
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    adapter.seed(readiness=self.readiness(adapter), activation=True)
                self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))

    def test_known_hosts_cannot_write_to_explicit_protection_or_active_settings(self):
        endpoint, runner, calls, log = self.remote_fixture()
        spec = dict(self.spec, endpoint=endpoint, protected_paths=[
            dict(namespace='local', path=endpoint['known_hosts_file'])])
        with self.assertRaisesRegex(ValueError, 'trust'):
            self.module().SelectedTransfer(spec, _process_runner=runner, _lease_process_factory=self._lease_factory)
        for directory in ('.devcontainer', '.vscode'):
            bad = dict(endpoint, known_hosts_file=str(self.root / directory / 'ordinary-file'))
            with self.assertRaisesRegex(ValueError, 'trust'):
                self.module().SelectedTransfer(dict(self.spec, endpoint=bad), _process_runner=runner, _lease_process_factory=self._lease_factory)
        self.assertEqual(calls, [])

    def test_local_seed_executes_rsync_and_verifies_selected_bytes(self):
        (self.source / 'hello.txt').write_bytes(b'hello selected seed')
        adapter = self.module().SelectedTransfer(self.spec)
        receipt = adapter.seed(readiness=self.readiness(adapter), activation=True)
        self.assertEqual(receipt['status'], 'verified')
        self.assertEqual(receipt['scope'], 'selected-local')
        self.assertEqual((self.target / 'hello.txt').read_bytes(), b'hello selected seed')
        self.assertEqual(receipt['returncodes'], [0])
        self.assertEqual(receipt['plan_digest'], adapter.plan_digest)
        self.assertEqual(receipt['manifests']['code']['hello.txt'],
                         __import__('hashlib').sha256(b'hello selected seed').hexdigest())

    def test_selected_probe_bounds_and_linked_root_fail_without_rsync(self):
        for mode in ('oversize', 'linked-root'):
            with self.subTest(mode=mode):
                spec = copy.deepcopy(self.spec)
                if mode == 'oversize':
                    with (self.source / 'large').open('wb') as stream:
                        stream.truncate(268435457)
                else:
                    (self.source / 'large').unlink()
                    link = self.root / 'linked'
                    link.symlink_to(self.source, target_is_directory=True)
                    spec['mappings'][0]['local'] = str(link)
                calls = []
                def runner(argv, **kwargs):
                    calls.append(argv)
                    return subprocess.run(argv, **kwargs)
                adapter = self.module().SelectedTransfer(spec, _process_runner=runner, _lease_process_factory=self._lease_factory)
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    adapter.seed(readiness=self.readiness(adapter), activation=True)
                self.assertFalse(any(c[0] == '/usr/bin/rsync' for c in calls))

    def test_transport_error_and_timeout_never_return_receipt(self):
        endpoint, runner, calls, log = self.remote_fixture()
        for error in (subprocess.CalledProcessError(23, ['fixture-rsync']),
                      subprocess.TimeoutExpired(['fixture-ssh'], 120)):
            def fail(argv, **kwargs):
                raise error
            adapter = self.module().SelectedTransfer(dict(self.spec, endpoint=endpoint), _process_runner=fail, _lease_process_factory=self._lease_factory)
            with self.assertRaises(type(error)):
                adapter.seed(readiness=self.readiness(adapter), activation=True)

    def test_constructor_is_pure_and_seed_requires_explicit_activation(self):
        module = self.module()
        with mock.patch('os.open', side_effect=AssertionError('filesystem open')), \
             mock.patch.object(Path, 'stat', side_effect=AssertionError('filesystem stat')), \
             mock.patch('subprocess.run', side_effect=AssertionError('process')):
            adapter = module.SelectedTransfer(self.spec)
            digest = adapter.plan_digest
            remote = module.SelectedTransfer(dict(self.spec, endpoint=dict(
                host='example.invalid', user='fixture', identity_file='/synthetic/not-read',
                known_hosts_file='/synthetic/not-inspected')))
            self.assertNotEqual(remote.plan_digest, digest)
            with self.assertRaisesRegex(ValueError, 'activation'):
                remote.seed(readiness=self.readiness(remote), activation=1)
            self.spec['mappings'][0]['local'] = '/different/selection'
            self.assertEqual(adapter.plan_digest, digest)
            with self.assertRaisesRegex(ValueError, 'activation'):
                adapter.seed(readiness=self.readiness(adapter))
            with self.assertRaisesRegex(ValueError, 'readiness'):
                adapter.seed(readiness={}, activation=True)


if __name__ == '__main__':
    unittest.main()
