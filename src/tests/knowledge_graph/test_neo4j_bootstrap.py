"""Offline security tests for the isolated Neo4j image (stdlib only)."""
import importlib.util
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import io
from contextlib import redirect_stderr
import unittest
from unittest.mock import patch

IMAGE = Path(__file__).resolve().parents[3] / '.devcontainer' / 'neo4j'


def load_module(name):
    path = IMAGE / (name + '.py')
    if not path.is_file():
        raise AssertionError(f'Missing image implementation: {name}')
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AuthTests(unittest.TestCase):
    def test_incomplete_seed_with_factory_skeleton_never_skips_auth_validation(self):
        bootstrap = load_module('bootstrap')
        auth = bootstrap.ensure_auth(self.auth, self.data)
        for name in ('databases', 'transactions', 'dbms'):
            (self.data / name).mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, '^Neo4j bootstrap refused$'):
            bootstrap.initialize_password(auth, self.data)

    def test_factory_empty_directories_are_fresh_and_still_initialize_password(self):
        bootstrap = load_module('bootstrap')
        for name in ('databases', 'transactions'):
            (self.data / name).mkdir()
        auth = bootstrap.ensure_auth(self.auth, self.data)
        with patch.object(bootstrap.subprocess, 'run') as run:
            bootstrap.initialize_password(auth, self.data)
        run.assert_called_once()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / 'secrets'
        self.private.mkdir(mode=0o700)
        self.auth = self.private / 'auth'
        self.data = self.root / 'data'
        self.data.mkdir()

    def test_secret_created_private_random_and_persisted_unchanged(self):
        bootstrap = load_module('bootstrap')
        first = bootstrap.ensure_auth(self.auth, self.data)
        self.assertRegex(first, r'^neo4j/[A-Za-z0-9_-]{43}$')
        self.assertEqual(self.auth.stat().st_mode & 0o777, 0o600)
        before = self.auth.stat()
        self.assertEqual(bootstrap.ensure_auth(self.auth, self.data), first)
        self.assertEqual(self.auth.stat().st_ino, before.st_ino)
        self.assertEqual(self.auth.stat().st_mtime_ns, before.st_mtime_ns)
        other = self.private / 'other'
        self.assertNotEqual(bootstrap.ensure_auth(other, self.data), first)

    def test_missing_auth_with_database_or_other_state_fails_closed(self):
        bootstrap = load_module('bootstrap')
        for name in ('databases', 'database', 'transactions', 'dbms'):
            with self.subTest(name=name):
                state = self.data / name
                state.mkdir()
                (state / 'existing-state').write_text('not a fresh database')
                with self.assertRaisesRegex(RuntimeError, '^Neo4j bootstrap refused$'):
                    bootstrap.ensure_auth(self.auth, self.data)
                self.assertFalse(self.auth.exists())
                (state / 'existing-state').unlink()
                state.rmdir()

    def test_unsafe_auth_is_rejected_without_replacement(self):
        bootstrap = load_module('bootstrap')
        token = 'neo4j/' + 'a' * 43
        def regular():
            self.auth.write_text(token)
            self.auth.chmod(0o600)
        for kind in ('symlink', 'dangling', 'hardlink', 'directory', 'mode',
                     'special-mode', 'format', 'large', 'directory-mode', 'directory-link', 'owner'):
            with self.subTest(kind=kind):
                self.setUp()
                regular()
                target = self.root / 'target'
                if kind in ('symlink', 'dangling'):
                    self.auth.rename(target)
                    self.auth.symlink_to(target if kind == 'symlink' else self.root / 'absent')
                elif kind == 'hardlink':
                    os.link(self.auth, target)
                elif kind == 'directory':
                    self.auth.unlink()
                    self.auth.mkdir()
                elif kind == 'mode':
                    self.auth.chmod(0o644)
                elif kind == 'special-mode':
                    self.auth.chmod(0o4600)
                elif kind == 'format':
                    self.auth.write_text('neo4j/secret-from-error\n')
                elif kind == 'large':
                    self.auth.write_text(token * 1000)
                elif kind == 'directory-mode':
                    self.private.chmod(0o755)
                elif kind == 'directory-link':
                    self.private.rename(target)
                    self.private.symlink_to(target)
                elif kind == 'owner':
                    if os.geteuid() != 0:
                        self.auth.unlink()
                        continue
                    os.chown(self.auth, 7474, -1)
                with self.assertRaisesRegex(RuntimeError, '^Neo4j bootstrap refused$'):
                    bootstrap.ensure_auth(self.auth, self.data)
                if kind == 'directory-link':
                    self.private.unlink()
                    target.rename(self.private)
                self.private.chmod(0o700)
                if self.auth.is_dir():
                    self.auth.rmdir()
                else:
                    self.auth.unlink()
                if target.exists():
                    target.unlink()

    def test_bootstrap_rejects_auth_and_execution_overrides(self):
        bootstrap = load_module('bootstrap')
        self.assertTrue(hasattr(bootstrap, 'validate_environment'))
        for key, value in {
            'NEO4J_AUTH': 'none', 'NEO4J_AUTH_PATH': '/evil',
            'NEO4J_AUTH_FILE': '/evil', 'NEO4J_dbms_security_auth__enabled': 'false',
            'NEO4J_dbms_security_auth__enabled_FILE': '/evil',
            'EXTENSION_SCRIPT': '/evil', 'EXTENDED_CONF': 'yes',
            'NEO4J_PLUGINS': '[]', 'NEO4JLABS_PLUGINS': '[]',
            'JAVA_TOOL_OPTIONS': '-javaagent:/evil', 'JDK_JAVA_OPTIONS': '-javaagent:/evil',
            '_JAVA_OPTIONS': '-javaagent:/evil', 'NEO4J_CONF': '/evil',
            'NEO4J_HOME': '/evil', 'NEO4J_server_directories_data': '/evil',
        }.items():
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, '^Neo4j bootstrap refused$'):
                    bootstrap.validate_environment({key: value})
        bootstrap.validate_environment({'NEO4J_dbms_security_auth__enabled': 'true',
                                        'NEO4J_HOME': '/var/lib/neo4j'})

    def test_initial_password_uses_fixed_stdin_helper_never_secret_argv(self):
        bootstrap = load_module('bootstrap')
        self.assertTrue(hasattr(bootstrap, 'initialize_password'))
        auth = bootstrap.ensure_auth(self.auth, self.data)
        with patch.object(bootstrap.subprocess, 'run') as run:
            bootstrap.initialize_password(auth, self.data)
        args, kwargs = run.call_args
        self.assertNotIn(auth.split('/')[1], repr(args))
        self.assertNotIn(auth.split('/')[1], repr(kwargs.get('env')))
        self.assertEqual(kwargs['input'], auth.split('/')[1].encode('ascii'))
        self.assertIn('AutomatorInitialPassword', args[0])
        self.assertTrue(kwargs['check'])
        self.assertLessEqual(kwargs['timeout'], 60)
        self.assertEqual(kwargs['stdout'], bootstrap.subprocess.DEVNULL)
        self.assertEqual(kwargs['stderr'], bootstrap.subprocess.DEVNULL)
        (self.data / 'databases').mkdir()
        (self.data / 'databases' / 'system').mkdir()
        with patch.object(bootstrap.subprocess, 'run') as run:
            bootstrap.initialize_password(auth, self.data)
        run.assert_not_called()

    def test_entrypoint_is_fixed_nonroot_and_enables_auth(self):
        bootstrap = load_module('bootstrap')
        self.assertTrue(hasattr(bootstrap, 'main'))
        with patch.object(bootstrap.os, 'geteuid', return_value=0), redirect_stderr(io.StringIO()):
            self.assertEqual(bootstrap.main([]), 1)
        with patch.object(bootstrap.os, 'geteuid', return_value=7474), redirect_stderr(io.StringIO()):
            self.assertEqual(bootstrap.main(['-c', 'untrusted-source']), 1)
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(bootstrap, 'ensure_auth', return_value='neo4j/' + 'a' * 43), \
                 patch.object(bootstrap, 'initialize_password'), \
                 patch.object(bootstrap.os, 'umask'), \
                 patch.object(bootstrap.os, 'execve') as execute:
                bootstrap.main([])
        command, args, env = execute.call_args.args
        self.assertEqual(command, '/startup/docker-entrypoint.sh')
        self.assertEqual(args, [command, 'neo4j'])
        self.assertEqual(env['NEO4J_dbms_security_auth__enabled'], 'true')
        self.assertFalse(any(key.startswith('NEO4J_AUTH') for key in env))

    def test_build_helper_writes_only_fixed_source_and_compiles(self):
        bootstrap = load_module('bootstrap')
        self.assertTrue(hasattr(bootstrap, 'build_helper'))
        with patch.object(bootstrap.subprocess, 'run') as run:
            bootstrap.build_helper(self.root)
            command = run.call_args.args[0]
            self.assertEqual(command[0], 'javac')
        self.assertIn('System.in.readNBytes(44)', bootstrap.JAVA_HELPER)
        self.assertIn('new SetInitialPasswordCommand', bootstrap.JAVA_HELPER)
        self.assertNotIn('ProcessBuilder', bootstrap.JAVA_HELPER)
        self.assertIn('.execute("--", password)', bootstrap.JAVA_HELPER)

    def test_partial_initialization_cannot_start_with_default_password(self):
        bootstrap = load_module('bootstrap')
        auth = bootstrap.ensure_auth(self.auth, self.data)
        (self.data / 'dbms').mkdir(mode=0o700)
        with patch.object(bootstrap.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, '^Neo4j bootstrap refused$'):
                bootstrap.initialize_password(auth, self.data)
        run.assert_not_called()
        initial = self.data / 'dbms' / 'auth.ini'
        initial.write_text('fixture for existing upstream initial-password output')
        initial.chmod(0o600)
        with patch.object(bootstrap.subprocess, 'run') as run:
            bootstrap.initialize_password(auth, self.data)
        run.assert_not_called()
        initial.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, '^Neo4j bootstrap refused$'):
            bootstrap.initialize_password(auth, self.data)


class ImageTests(unittest.TestCase):
    def test_pinned_nonroot_image_and_narrow_build_context(self):
        self.assertTrue((IMAGE / 'Dockerfile').is_file())
        dockerfile = (IMAGE / 'Dockerfile').read_text()
        self.assertIn('neo4j:5.26.30-community@sha256:22ec5cd05a8cbb372fc4bed5e384c30bc75fd92504c72be4462039761b105f61', dockerfile)
        self.assertIn('apt-get install -y --no-install-recommends python3', dockerfile)
        self.assertIn('USER neo4j', dockerfile)
        self.assertIn('tini', dockerfile)
        self.assertIn('/opt/automator-neo4j/bootstrap.py', dockerfile)
        self.assertIn('install -d -o 7474 -g 7474 -m 0700 /automator-secrets', dockerfile)
        self.assertEqual((IMAGE / '.dockerignore').read_text().splitlines(),
                         ['*', '!Dockerfile', '!.dockerignore', '!bootstrap.py', '!healthcheck.py',
                          '!Dockerfile.gateway', '!haproxy.cfg'])


class HealthTests(unittest.TestCase):
    def setUp(self):
        bootstrap = load_module('bootstrap')
        self.health = load_module('healthcheck')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        private = Path(self.tmp.name)
        private.chmod(0o700)
        self.auth = private / 'auth'
        data = private / 'data'
        data.mkdir()
        self.token = bootstrap.ensure_auth(self.auth, data)
        self.requests = []
        self.status = 200
        self.payload = {'results': [{'columns': ['1'], 'data': [{'row': [1]}]}], 'errors': []}
        self.headers = {}
        self.delay = 0
        self.drip = 0
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                owner.requests.append((self.path, dict(self.headers), json.loads(body)))
                time.sleep(owner.delay)
                self.send_response(owner.status)
                for key, value in owner.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    payload = owner.payload if isinstance(owner.payload, bytes) else json.dumps(owner.payload).encode()
                    if owner.drip:
                        for char in payload:
                            self.wfile.write(bytes([char]))
                            self.wfile.flush()
                            time.sleep(owner.drip)
                    else:
                        self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                owner.requests.append(('redirected', {}, {}))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        setattr(self.health, 'AUTH_PATH', self.auth)
        setattr(self.health, 'PORT', server.server_port)

    def test_authenticated_transaction_and_return_one_health(self):
        result = self.health.transaction('RETURN $value', {'value': 1})
        self.assertEqual(result, self.payload)
        path, headers, body = self.requests[0]
        self.assertEqual(path, '/db/neo4j/tx/commit')
        expected = 'Basic ' + base64.b64encode(self.token.replace('/', ':', 1).encode()).decode()
        self.assertEqual(headers['Authorization'], expected)
        self.assertEqual(body['statements'], [{'statement': 'RETURN $value', 'parameters': {'value': 1}}])
        self.assertTrue(self.health.check_health())
        self.assertEqual(self.requests[-1][2]['statements'][0]['statement'], 'RETURN 1')

    def test_http_failures_and_redirects_are_rejected_without_secret_errors(self):
        self.headers['Location'] = f'http://127.0.0.1:{self.health.PORT}/redirect'
        for status in (301, 302, 303, 307, 308, 401, 403, 500):
            with self.subTest(status=status):
                self.status = status
                with self.assertRaisesRegex(RuntimeError, '^Neo4j transaction failed$'):
                    self.health.transaction('RETURN 1')
        self.assertEqual(len(self.requests), 8)
        self.assertFalse(any(request[0] == 'redirected' for request in self.requests))

    def test_bad_json_error_results_and_oversized_reads_are_rejected(self):
        for payload in (b'not-json-secret', b'x' * 65537, {}, [],
                        {'results': [], 'errors': [{'message': self.token}]},
                        {'results': 'wrong', 'errors': []}):
            with self.subTest(kind=type(payload).__name__):
                self.payload = payload
                with self.assertRaisesRegex(RuntimeError, '^Neo4j transaction failed$'):
                    self.health.transaction('RETURN 1')

    def test_health_requires_exact_integer_one_row(self):
        for data in ([], [{'row': [2]}], [{'row': [True]}], [{'row': ['1']}],
                     [{'row': [1]}, {'row': [1]}], [{'row': [1, 2]}]):
            with self.subTest(data=data):
                self.payload = {'results': [{'columns': ['1'], 'data': data}], 'errors': []}
                with self.assertRaisesRegex(RuntimeError, '^Neo4j health check failed$'):
                    self.health.check_health()

    def test_proxy_environment_is_ignored(self):
        with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1',
                                     'HTTP_PROXY': 'http://127.0.0.1:1',
                                     'ALL_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': '', 'no_proxy': ''}):
            self.assertTrue(self.health.check_health())
        self.assertEqual(len(self.requests), 1)

    def test_timeout_is_bounded(self):
        self.assertTrue(hasattr(self.health, 'TIMEOUT'))
        self.delay = 0.3
        with patch.object(self.health, 'TIMEOUT', 0.05):
            start = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, '^Neo4j transaction failed$'):
                self.health.transaction('RETURN 1')
            self.assertLess(time.monotonic() - start, 0.5)

    def test_unsafe_auth_never_reaches_network(self):
        self.auth.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, '^Neo4j transaction failed$'):
            self.health.transaction('RETURN 1')
        self.assertEqual(self.requests, [])

    def test_slow_drip_cannot_extend_total_io_deadline(self):
        self.drip = 0.01
        with patch.object(self.health, 'TIMEOUT', 0.05):
            start = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, '^Neo4j transaction failed$'):
                self.health.transaction('RETURN 1')
            self.assertLess(time.monotonic() - start, 0.5)

    def test_health_cli_has_no_user_statement_or_source_execution(self):
        self.assertTrue(hasattr(self.health, 'main'))
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.health.main(['-c', 'anything']), 1)
        self.assertEqual(errors.getvalue(), 'Neo4j health check failed\n')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.health.main([]), 0)


if __name__ == '__main__':
    unittest.main()
