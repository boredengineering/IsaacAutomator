"""Synthetic Syncthing REST protocol fixtures; NOT native qualification."""
import importlib
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit, parse_qs

from src.python.remote_development import build_plan


class FakeEngine:
    """Only binds ephemeral numeric loopback; owns and joins its server thread."""
    def __init__(self, plan, side, device, peer):
        self.device, self.peer = device, peer
        self.start = '2026-01-01T00:00:00Z'
        self.calls = []
        self.resumed = threading.Event()
        self.failure = False
        self.noop_pause = False
        self.noop_resume = False
        self.conflict = False
        self.omit_status = None
        self.runner_override = None
        self.folders = {m['name']: dict(id=m['name'], path=m[side], paused=True,
            type='sendonly' if (side == 'local') == (m['direction'] == 'push') else 'receiveonly',
            devices=[{'deviceID': peer}], versioning={'type': 'staggered'}) for m in plan['mappings']}
        self.ignores = {m['name']: [p.rstrip('/') for p in m['excludes']] for m in plan['mappings']}
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def respond(self, body, code=200):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_GET(self):
                owner.calls.append(('GET', self.path))
                if self.headers.get('X-API-Key') != 'synthetic-key':
                    return self.respond({}, 403)
                if owner.failure:
                    return self.respond({}, 503)
                url = urlsplit(self.path)
                folder = parse_qs(url.query).get('folder', [''])[0]
                if url.path == '/rest/system/version':
                    return self.respond({'version': 'v1.27.12'})
                if url.path == '/rest/system/status':
                    return self.respond({'myID': owner.device, 'startTime': owner.start})
                if url.path == '/rest/system/connections':
                    return self.respond({'connections': {owner.peer: {'connected': True}}})
                if url.path == '/rest/config/restart-required':
                    return self.respond({'requiresRestart': False})
                if url.path.startswith('/rest/config/folders/'):
                    value = owner.folders.get(url.path.rsplit('/', 1)[-1])
                    return self.respond(value, 200 if value else 404)
                if url.path == '/rest/db/ignores':
                    return self.respond({'ignore': owner.ignores[folder], 'expanded': []})
                if url.path == '/rest/db/status':
                    status = {'state': '' if owner.folders[folder]['paused'] else 'idle',
                        'error': '', 'pullErrors': 0, 'needTotalItems': 0,
                        'receiveOnlyTotalItems': int(owner.conflict), 'sequence': 1}
                    if owner.omit_status:
                        status.pop(owner.omit_status)
                    if owner.runner_override is not None:
                        status['state'] = owner.runner_override
                    return self.respond(status)
                return self.respond({}, 404)
            def do_PATCH(self):
                owner.calls.append(('PATCH', self.path))
                if self.headers.get('X-API-Key') != 'synthetic-key' or owner.failure:
                    return self.respond({}, 503)
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert set(value) == {'paused'} and type(value['paused']) is bool
                folder = self.path.rsplit('/', 1)[-1]
                if not ((owner.noop_pause and value['paused']) or (owner.noop_resume and not value['paused'])):
                    owner.folders[folder]['paused'] = value['paused']
                    if not value['paused']:
                        owner.resumed.set()
                return self.respond({})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        assert not self.thread.is_alive()


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-supervisor-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for side in ('local', 'remote'):
            (self.root / side).mkdir()
            (self.root / side / 'code').write_bytes(b'expected seed bytes')
        self.spec = dict(engine='syncthing', delete_approved=True, mappings=[dict(name='repo', kind='source',
            local=str(self.root / 'local'), remote=str(self.root / 'remote'), container='/workspaces/repo')])
        self.plan = build_plan(self.spec)
        self.engines = [FakeEngine(self.plan, 'local', 'DEVICE-A', 'DEVICE-B'),
                        FakeEngine(self.plan, 'remote', 'DEVICE-B', 'DEVICE-A')]
        for engine in self.engines:
            self.addCleanup(engine.close)
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.sync_supervisor'),
                             'concrete supervisor missing')
        return importlib.import_module('src.python.sync_supervisor')
    def supervisor(self, *, lock_directory=None):
        mod = self.module()
        backend = mod.SyncthingREST(local_url=self.engines[0].url, remote_url=self.engines[1].url,
            local_device='DEVICE-A', remote_device='DEVICE-B', local_api_key='synthetic-key',
            remote_api_key='synthetic-key', timeout=.5)
        supervisor = mod.Supervisor(self.spec, backend=backend,
            lock_directory=self.root if lock_directory is None else lock_directory)
        self.addCleanup(supervisor.close, activation=True)
        return supervisor
    def ready(self, supervisor):
        return dict(plan_digest=supervisor.plan_digest, transport_reviewed=True,
                    recovery_verified=True, deletion_approved=True, paths_reviewed=True)
    def test_writer_lock_cannot_be_placed_in_mappings_settings_or_protection(self):
        self.spec['protected_paths'] = [dict(namespace='local', path=str(self.root / 'saved'))]
        for directory in (self.root / 'local', self.root / '.devcontainer', self.root / 'saved'):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.supervisor(lock_directory=directory)
        self.assertFalse((self.root / 'local/.writer.lock').exists())
        self.assertEqual(sum(len(e.calls) for e in self.engines), 0)

    def test_new_native_conflict_refuses_resume_before_any_unpause(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        self.engines[0].conflict = True
        with self.assertRaises(ValueError):
            supervisor.resume(activation=True)
        self.assertFalse(any(c[0] == 'PATCH' for e in self.engines for c in e.calls))
        supervisor.stop(activation=True)

    def test_native_unknown_health_and_config_only_pause_are_not_verification(self):
        for field in ('receiveOnlyTotalItems', 'pullErrors', 'sequence', 'needTotalItems', 'error'):
            with self.subTest(field=field):
                self.engines[0].omit_status = field
                supervisor = self.supervisor()
                try:
                    with self.assertRaises(ValueError):
                        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
                finally:
                    supervisor.close(activation=True)
        self.engines[0].omit_status = None
        self.engines[0].runner_override = 'syncing'
        supervisor = self.supervisor()
        with self.assertRaises(ValueError):
            supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        self.assertFalse(any(c[0] == 'PATCH' for e in self.engines for c in e.calls))
        self.engines[0].runner_override = None

    def test_native_adapter_is_explicit_and_has_no_remote_proxy_or_shell_transport(self):
        mod = self.module()
        for engine in ('mutagen', 'rsync'):
            self.spec['engine'] = engine
            with self.assertRaises(ValueError):
                self.supervisor()
        for url in ('http://localhost:1234', 'https://127.0.0.1:1234',
                    'http://192.0.2.1:1234', 'http://127.0.0.1:1234/redirect'):
            with self.assertRaises(ValueError):
                mod.SyncthingREST(local_url=url, remote_url=self.engines[1].url, local_device='DEVICE-A',
                    remote_device='DEVICE-B', local_api_key='synthetic-key', remote_api_key='synthetic-key')
        self.assertEqual(sum(len(e.calls) for e in self.engines), 0)

    def test_digest_binds_entire_selection_and_scope_and_conflicts_prevent_acquisition(self):
        original = self.supervisor()
        self.spec['image'] = 'example.invalid/changed:version'
        changed = self.supervisor()
        self.assertNotEqual(original.plan_digest, changed.plan_digest)
        elsewhere = self.supervisor(lock_directory=self.root / 'other-scope')
        self.assertNotEqual(changed.plan_digest, elsewhere.plan_digest)
        self.engines[0].conflict = True
        with self.assertRaises(ValueError):
            changed.acquire(readiness=self.ready(changed), activation=True)
        self.assertFalse(any(c[0] == 'PATCH' for e in self.engines for c in e.calls))

    def test_reseed_can_execute_checksum_verified_rsync_in_owned_disposable_scope(self):
        from src.python.remote_development import local_fixture
        if not Path('/usr/bin/rsync').is_file():
            self.skipTest('fixed system rsync unavailable')
        with local_fixture() as fixture:
            for side in ('local', 'remote'):
                (fixture.root / side).mkdir()
                (fixture.root / side / 'code').write_bytes(b'original')
            spec = dict(self.spec, initial_seed='reviewed-overwrite', overwrite_approved=True,
                mappings=[dict(self.spec['mappings'][0], local=str(fixture.root / 'local'),
                               remote=str(fixture.root / 'remote'))])
            engines = [FakeEngine(build_plan(spec), 'local', 'DEVICE-A', 'DEVICE-B'),
                       FakeEngine(build_plan(spec), 'remote', 'DEVICE-B', 'DEVICE-A')]
            try:
                mod = self.module()
                backend = mod.SyncthingREST(local_url=engines[0].url, remote_url=engines[1].url,
                    local_device='DEVICE-A', remote_device='DEVICE-B', local_api_key='synthetic-key',
                    remote_api_key='synthetic-key', timeout=.5)
                supervisor = mod.Supervisor(spec, backend=backend, lock_directory=fixture.root)
                supervisor.acquire(readiness=self.ready(supervisor), activation=True)
                (fixture.root / 'local/code').write_bytes(b'reviewed replacement')
                receipt = supervisor.reseed(readiness=self.ready(supervisor), fixture=fixture, activation=True)
                self.assertEqual((fixture.root / 'remote/code').read_bytes(), b'reviewed replacement')
                self.assertEqual(receipt['seed_verification'], 'sha256-local-pair-bytes')
                supervisor.resume(activation=True)
                supervisor.stop(activation=True)
            finally:
                for engine in engines:
                    engine.close()

    def test_supervisor_and_existing_seed_fixture_share_the_writer_lock(self):
        from src.python.remote_development import local_fixture
        with local_fixture() as fixture:
            supervisor = self.supervisor(lock_directory=fixture.root)
            supervisor.acquire(readiness=self.ready(supervisor), activation=True)
            with self.assertRaises(ValueError):
                with fixture.writer('rsync'):
                    pass
            supervisor.resume(activation=True)
            self.engines[0].failure = True
            supervisor.close(activation=True)
            with self.assertRaisesRegex(ValueError, 'recovery'):
                with fixture.writer('rsync'):
                    pass
            self.engines[0].failure = False
            self.engines[0].folders['repo']['paused'] = True
            recovered = self.supervisor(lock_directory=fixture.root)
            recovered.acquire(readiness=self.ready(recovered), recover=True, activation=True)
            recovered.stop(activation=True)
            with fixture.writer('rsync'):
                pass

    def test_running_supervision_loop_stops_and_cleans_owned_session(self):
        from concurrent.futures import ThreadPoolExecutor
        supervisor = self.supervisor()
        self.assertTrue(callable(getattr(supervisor, 'run', None)), 'real supervision loop missing')
        stop = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(supervisor.run, readiness=self.ready(supervisor), stop_event=stop,
                                 poll_interval=.01, activation=True)
            try:
                self.assertTrue(self.engines[1].resumed.wait(timeout=3))
            finally:
                stop.set()
            receipt = future.result(timeout=3)
        self.assertEqual(receipt['outcome'], 'stop-requested')
        self.assertEqual(receipt['cleanup']['state'], 'stopped')
        self.assertTrue(all(e.folders['repo']['paused'] for e in self.engines))
        self.assertFalse(receipt['cleanup']['writer_owned'])

    def test_activation_readiness_and_seed_drift_fail_before_resume_writes(self):
        supervisor = self.supervisor()
        for args in ({'readiness': self.ready(supervisor)},
                     {'readiness': dict(self.ready(supervisor), plan_digest='0' * 64), 'activation': True},
                     {'readiness': dict(self.ready(supervisor), deletion_approved=False), 'activation': True}):
            with self.assertRaises(ValueError):
                supervisor.acquire(**args)
        self.assertEqual(sum(len(e.calls) for e in self.engines), 0)
        self.assertFalse((self.root / '.writer.lock').exists())
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        for method in (supervisor.resume, supervisor.pause, supervisor.poll, supervisor.stop,
                       supervisor.close):
            before = sum(len(e.calls) for e in self.engines)
            with self.assertRaises(ValueError):
                method()
            self.assertEqual(sum(len(e.calls) for e in self.engines), before)
        (self.root / 'remote/code').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            supervisor.resume(activation=True)
        self.assertFalse(any(c[0] == 'PATCH' for e in self.engines for c in e.calls))
        supervisor.stop(activation=True)

    def test_conflict_file_is_detected_even_when_native_counters_are_clean(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        (self.root / 'remote/code.sync-conflict-20260101-001-FIXTURE').write_bytes(b'conflict')
        self.assertEqual(supervisor.poll(activation=True)['state'], 'blocked')
        with self.assertRaises(ValueError):
            supervisor.reseed(readiness=self.ready(supervisor), activation=True)
        supervisor.stop(activation=True)

    def test_failed_cleanup_leaves_durable_guard_and_requires_explicit_recovery(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        self.engines[0].failure = True
        receipt = supervisor.close(activation=True)
        self.assertEqual(receipt['state'], 'stop-unverified')
        self.assertFalse(receipt['writer_owned'])
        self.assertTrue((self.root / '.writer.lock').read_text())
        self.engines[0].failure = False
        other = self.supervisor()
        with self.assertRaisesRegex(ValueError, 'recovery'):
            other.acquire(readiness=self.ready(other), activation=True)
        # Recovery never forcibly adopts a running folder.
        with self.assertRaises(ValueError):
            other.acquire(readiness=self.ready(other), recover=True, activation=True)
        self.engines[0].folders['repo']['paused'] = True
        other.acquire(readiness=self.ready(other), recover=True, activation=True)
        other.stop(activation=True)
        self.assertEqual((self.root / '.writer.lock').read_bytes(), b'')

    def test_partial_resume_failure_rolls_back_only_owned_folders(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        self.engines[1].noop_resume = True
        with self.assertRaises(ValueError):
            supervisor.resume(activation=True)
        self.assertEqual(supervisor.state, 'blocked')
        self.assertTrue(all(e.folders['repo']['paused'] for e in self.engines))
        supervisor.stop(activation=True)

    def test_cleanup_refuses_reassigned_folder_instead_of_mutating_it(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        self.engines[0].folders['repo']['path'] = str(self.root / 'unowned')
        before = len([c for c in self.engines[0].calls if c[0] == 'PATCH'])
        with self.assertRaises(ValueError):
            supervisor.stop(activation=True)
        self.assertEqual(len([c for c in self.engines[0].calls if c[0] == 'PATCH']), before)
        self.assertTrue(self.engines[1].folders['repo']['paused'])
        self.engines[0].folders['repo']['path'] = str(self.root / 'local')
        supervisor.stop(activation=True)

    def test_transport_failure_pauses_reachable_peer_and_keeps_dirty_ownership(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        self.engines[0].failure = True
        receipt = supervisor.poll(activation=True)
        self.assertEqual(receipt['state'], 'stop-unverified')
        self.assertTrue(self.engines[1].folders['repo']['paused'])
        self.assertTrue(receipt['writer_owned'])
        with self.assertRaises(ValueError):
            supervisor.stop(activation=True)
        # A dead/unresponsive process is not verified stopped; cannot unlock.
        self.assertEqual(supervisor.state, 'stop-unverified')
        other = self.supervisor()
        with self.assertRaises(ValueError):
            other.acquire(readiness=self.ready(other), activation=True)
        self.engines[0].failure = False
        supervisor.stop(activation=True)

    def test_pause_http_success_without_stopped_runner_does_not_release_lock(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        self.engines[0].noop_pause = True
        with self.assertRaises(ValueError):
            supervisor.stop(activation=True)
        self.assertEqual(supervisor.state, 'stop-unverified')
        self.assertIsNotNone(supervisor._fd)
        self.engines[0].noop_pause = False
        supervisor.stop(activation=True)

    def test_conflict_blocks_until_reviewed_reseed_and_process_restart_is_detected(self):
        supervisor = self.supervisor()
        supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        supervisor.resume(activation=True)
        self.engines[1].conflict = True
        receipt = supervisor.poll(activation=True)
        self.assertEqual(receipt['state'], 'blocked')
        self.assertTrue(receipt['writer_owned'])
        self.assertTrue(all(e.folders['repo']['paused'] for e in self.engines))
        with self.assertRaises(ValueError):
            supervisor.resume(activation=True)
        self.engines[1].conflict = False
        for side in ('local', 'remote'):
            (self.root / side / 'code').write_bytes(b'reviewed reseed bytes')
        self.assertEqual(supervisor.reseed(readiness=self.ready(supervisor), activation=True)['state'], 'paused')
        supervisor.resume(activation=True)
        self.engines[0].start = '2026-01-02T00:00:00Z'
        self.assertEqual(supervisor.poll(activation=True)['state'], 'blocked')
        supervisor.stop(activation=True)

    def test_actual_rest_resume_pause_stop_verifies_seed_and_native_state(self):
        supervisor = self.supervisor()
        self.assertEqual(sum(len(e.calls) for e in self.engines), 0)
        receipt = supervisor.acquire(readiness=self.ready(supervisor), activation=True)
        self.assertEqual(receipt['state'], 'paused')
        self.assertTrue(receipt['writer_owned'])
        receipt = supervisor.resume(activation=True)
        self.assertEqual(receipt['state'], 'continuous')
        self.assertEqual(receipt['seed_verification'], 'sha256-local-pair-bytes')
        self.assertTrue(all(not e.folders['repo']['paused'] for e in self.engines))
        self.assertEqual(supervisor.pause(activation=True)['state'], 'paused')
        self.assertTrue(all(e.folders['repo']['paused'] for e in self.engines))
        self.assertFalse(supervisor.stop(activation=True)['writer_owned'])
        self.assertEqual(supervisor.state, 'stopped')
        self.assertTrue(all('repo' in e.folders for e in self.engines))
        other = self.supervisor()
        other.acquire(readiness=self.ready(other), activation=True)
        other.stop(activation=True)


if __name__ == '__main__':
    unittest.main()
