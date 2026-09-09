"""Offline tests: no real metadata, Docker daemon, or host configuration access."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import shutil
import yaml
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1] / "ansible"
ROLE = ROOT / "roles" / "artifact-registry"
HOST = "us-central1-docker.pkg.dev"
IMAGE = HOST + "/test-project/workloads/gr00t@sha256:" + "a" * 64


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CredentialHelperTests(unittest.TestCase):
    def test_get_protocol_uses_metadata_and_never_persists_token(self):
        path = ROLE / "files" / "docker-credential-isaac-artifact-registry.py"
        self.assertTrue(path.exists(), "metadata credential helper is not implemented")
        helper = load_module(path, "credential_helper")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Metadata-Flavor": "Google"}
        response.read.return_value = json.dumps({
            "access_token": "offline-test-token", "token_type": "Bearer", "expires_in": 3599
        }).encode()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "registry.json"
            config.write_text(json.dumps({"registry": HOST}))
            out, err = io.StringIO(), io.StringIO()
            opener = Mock()
            opener.open.return_value = response
            with patch.object(helper, "CONFIG_PATH", config), patch.object(
                helper.urllib.request, "build_opener", return_value=opener
            ), patch.object(sys, "stdin", io.StringIO(HOST + "\n")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(helper.main(["get"]), 0)
            self.assertEqual(json.loads(out.getvalue()), {
                "ServerURL": HOST, "Username": "oauth2accesstoken", "Secret": "offline-test-token"
            })
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token")
            self.assertEqual(request.get_header("Metadata-flavor"), "Google")
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 5)
            self.assertEqual(err.getvalue(), "")
            self.assertEqual(list(Path(directory).iterdir()), [config])
            self.assertNotIn("offline-test-token", config.read_text())


    def test_protocol_rejects_untrusted_hosts_and_bad_responses(self):
        helper = load_module(ROLE / "files" / "docker-credential-isaac-artifact-registry.py", "helper_errors")
        cases = [
            (HOST + ".evil.example", None),
            ("https://" + HOST, None),
            (HOST, b'{"access_token":"secret", "expires_in":0,"token_type":"Bearer"}'),
            (HOST, b'{"access_token":"secret", "expires_in":90,"token_type":"Basic"}'),
            (HOST, b'{"access_token":123,"expires_in":90,"token_type":"Bearer"}'),
            (HOST, b"secret-not-json"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "registry.json"
            config.write_text(json.dumps({"registry": HOST}))
            for host, body in cases:
                with self.subTest(host=host, body=body):
                    response = Mock()
                    response.__enter__ = Mock(return_value=response)
                    response.__exit__ = Mock(return_value=False)
                    response.headers = {"Metadata-Flavor": "Google"}
                    response.read.return_value = body
                    opener = Mock()
                    opener.open.return_value = response
                    out, err = io.StringIO(), io.StringIO()
                    with patch.object(helper, "CONFIG_PATH", config), patch.object(helper.urllib.request, "build_opener", return_value=opener), patch.object(sys, "stdin", io.StringIO(host)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        self.assertEqual(helper.main(["get"]), 1)
                    self.assertEqual(out.getvalue(), "")
                    self.assertNotIn("secret", err.getvalue())
                    if body is None:
                        opener.open.assert_not_called()

    def test_protocol_list_erase_and_store_never_contact_metadata(self):
        helper = load_module(ROLE / "files" / "docker-credential-isaac-artifact-registry.py", "helper_operations")
        for operation, status, output in [("list", 0, "{}\n"), ("erase", 0, ""), ("store", 1, ""), ("unknown", 1, "")]:
            with self.subTest(operation=operation):
                out = io.StringIO()
                with patch.object(helper.urllib.request, "build_opener") as network, patch.object(sys, "stdin", io.StringIO("not-a-real-secret")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(helper.main([operation]), status)
                self.assertEqual(out.getvalue(), output)
                network.assert_not_called()

    def test_metadata_redirects_are_refused(self):
        helper = load_module(ROLE / "files" / "docker-credential-isaac-artifact-registry.py", "helper_redirects")
        self.assertTrue(hasattr(helper, "NoRedirect"), "metadata redirects must be denied")
        with self.assertRaises(Exception):
            helper.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://evil.example/")

    def test_metadata_network_failure_is_redacted_and_proxies_are_disabled(self):
        helper = load_module(ROLE / "files" / "docker-credential-isaac-artifact-registry.py", "helper_network_error")
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "registry.json"
            config.write_text(json.dumps({"registry": HOST}))
            opener = Mock()
            opener.open.side_effect = TimeoutError("sensitive-error-body")
            out, err = io.StringIO(), io.StringIO()
            with patch.object(helper, "CONFIG_PATH", config), patch.object(helper.urllib.request, "build_opener", return_value=opener) as build, patch.object(sys, "stdin", io.StringIO(HOST)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(helper.main(["get"]), 1)
            self.assertEqual(out.getvalue(), "")
            self.assertNotIn("sensitive-error-body", err.getvalue())
            self.assertEqual(build.call_args.args[0].proxies, {})
            self.assertIsInstance(build.call_args.args[1], helper.NoRedirect)

    def test_http_transport_ignores_proxy_and_refuses_redirect(self):
        import http.server
        import socket
        import threading
        helper = load_module(ROLE / "files/docker-credential-isaac-artifact-registry.py", "helper_transport")
        requests = []
        response_status = 200
        class Metadata(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Metadata-Flavor")))
                self.send_response(response_status)
                self.send_header("Metadata-Flavor", "Google")
                self.send_header("Location", "http://evil.example/stolen")
                self.end_headers()
                self.wfile.write(b'{"access_token":"offline-token","expires_in":90,"token_type":"Bearer"}')
            def log_message(self, format, *args):
                pass
        # Keep the real urllib opener/HTTP transport. Only route the fixed
        # metadata socket to our loopback server; all other destinations fail.
        connect = socket.create_connection
        with tempfile.TemporaryDirectory() as directory, http.server.ThreadingHTTPServer(("127.0.0.1", 0), Metadata) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                config = Path(directory) / "registry.json"
                config.write_text(json.dumps({"registry": HOST}))
                for status in (200, 302):
                    with self.subTest(status=status):
                        response_status = status
                        destinations = []
                        def offline_connect(address, *args, **kwargs):
                            destinations.append(address)
                            if address != ("169.254.169.254", 80):
                                raise AssertionError("unexpected network destination: " + repr(address))
                            return connect(("127.0.0.1", server.server_port), *args, **kwargs)
                        out, err = io.StringIO(), io.StringIO()
                        with patch.object(helper, "CONFIG_PATH", config), patch.object(socket, "create_connection", side_effect=offline_connect), patch.dict(os.environ, {
                            "http_proxy": "http://proxy.invalid:8181", "HTTP_PROXY": "http://proxy.invalid:8181",
                            "https_proxy": "http://proxy.invalid:8181", "HTTPS_PROXY": "http://proxy.invalid:8181",
                            "all_proxy": "http://proxy.invalid:8181", "ALL_PROXY": "http://proxy.invalid:8181",
                            "no_proxy": "", "NO_PROXY": "",
                        }), patch.object(sys, "stdin", io.StringIO(HOST)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                            self.assertEqual(helper.main(["get"]), 0 if status == 200 else 1)
                        self.assertEqual(destinations, [("169.254.169.254", 80)])
                        self.assertEqual(requests[-1], ("/computeMetadata/v1/instance/service-accounts/default/token", "Google"))
                        if status == 200:
                            self.assertEqual(json.loads(out.getvalue())["Secret"], "offline-token")
                            self.assertEqual(err.getvalue(), "")
                        else:
                            self.assertEqual(out.getvalue(), "")
                            self.assertNotIn("offline-token", err.getvalue())
                self.assertEqual(len(requests), 2)
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_standalone_process_supports_docker_list_protocol(self):
        result = subprocess.run([sys.executable, str(ROLE / "files" / "docker-credential-isaac-artifact-registry.py"), "list"], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})


class ConfigurationTests(unittest.TestCase):
    def test_merge_is_private_atomic_and_idempotent(self):
        path = ROLE / "library" / "artifact_registry_docker_config.py"
        self.assertTrue(path.exists(), "Docker configuration module is missing")
        module = load_module(path, "docker_config")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            docker = home / ".docker"
            docker.mkdir(mode=0o755)
            config = docker / "config.json"
            original = {"auths": {"other.example": {"auth": "offline-placeholder"}, HOST: {"auth": "stale"}}, "credsStore": "existing", "credHelpers": {"other.example": "other-helper"}, "detachKeys": "ctrl-e,e"}
            config.write_text(json.dumps(original))
            self.assertTrue(module.configure(home, os.getuid(), os.getgid(), HOST))
            result = json.loads(config.read_text())
            self.assertEqual(result["credHelpers"], {"other.example": "other-helper", HOST: "isaac-artifact-registry"})
            self.assertEqual(result["auths"], {"other.example": {"auth": "offline-placeholder"}})
            self.assertEqual(result["credsStore"], "existing")
            self.assertEqual(result["detachKeys"], "ctrl-e,e")
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(docker.stat().st_mode & 0o777, 0o700)
            self.assertEqual(config.stat().st_uid, os.getuid())
            before = config.stat().st_mtime_ns
            self.assertFalse(module.configure(home, os.getuid(), os.getgid(), HOST))
            self.assertEqual(config.stat().st_mtime_ns, before)

    def test_config_rejects_malformed_content_and_symlinks_without_overwrite(self):
        path = ROLE / "library" / "artifact_registry_docker_config.py"
        self.assertTrue(path.exists(), "Docker configuration module is missing")
        module = load_module(path, "docker_config_invalid")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".docker").mkdir()
            config = home / ".docker" / "config.json"
            for text in ["bad json", "[]", '{"credHelpers":[]}', '{"auths":null}']:
                config.write_text(text)
                with self.assertRaises(ValueError):
                    module.configure(home, os.getuid(), os.getgid(), HOST)
                self.assertEqual(config.read_text(), text)
            config.unlink()
            target = home / "unrelated.json"
            target.write_text("{}")
            config.symlink_to(target)
            with self.assertRaises(ValueError):
                module.configure(home, os.getuid(), os.getgid(), HOST)
            self.assertEqual(target.read_text(), "{}")

    @unittest.skipUnless(os.geteuid() == 0, "requires root to verify real privilege dropping")
    def test_user_directory_swap_cannot_redirect_privileged_writes(self):
        # A child drops privilege without altering the test runner. All targets,
        # including the root-only victim, are inside this temporary sandbox.
        import pwd
        account = pwd.getpwnam("nobody")
        script = r'''
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("config", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
home, victim = Path(sys.argv[2]), Path(sys.argv[3])
phase = sys.argv[6]
original_mkdir, original_read = Path.mkdir, Path.read_text
swapped = False
def swap():
    global swapped
    if not swapped:
        swapped = True
        (home / '.docker').rename(home / 'parked')
        (home / '.docker').symlink_to(victim, target_is_directory=True)
def mkdir(path, *args, **kwargs):
    result = original_mkdir(path, *args, **kwargs)
    if path == home / '.docker': swap()
    return result
def read(path, *args, **kwargs):
    result = original_read(path, *args, **kwargs)
    if path == home / '.docker/config.json': swap()
    return result
if phase == 'mkdir': Path.mkdir = mkdir
if phase == 'read': Path.read_text = read
try:
    module.configure(home, int(sys.argv[4]), int(sys.argv[5]), sys.argv[7])
except (OSError, ValueError):
    pass  # Failing closed after the attacker swaps the path is acceptable.
try:
    os.setuid(0)
    regained_root = True
except PermissionError:
    regained_root = False
print(json.dumps({'uid': os.geteuid(), 'gid': os.getegid(), 'groups': os.getgroups(), 'swapped': swapped, 'regained_root': regained_root}))
'''
        for phase in ("mkdir", "read", "normal"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                sandbox = Path(directory)
                sandbox.chmod(0o755)
                home, victim = sandbox / "home", sandbox / "root-only"
                home.mkdir()
                os.chown(home, account.pw_uid, account.pw_gid)
                docker = home / ".docker"
                docker.mkdir()
                os.chown(docker, account.pw_uid, account.pw_gid)
                config = docker / "config.json"
                config.write_text("{}")
                os.chown(config, account.pw_uid, account.pw_gid)
                victim.mkdir(mode=0o755)
                target = victim / "config.json"
                target.write_text('{"untouched": true}')
                before = (target.read_bytes(), target.stat().st_mode, victim.stat().st_mode)
                result = subprocess.run([
                    sys.executable, "-c", script,
                    str(ROLE / "library/artifact_registry_docker_config.py"),
                    str(home), str(victim), str(account.pw_uid), str(account.pw_gid), phase, HOST,
                ], text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                identity = json.loads(result.stdout)
                if phase != "normal":
                    self.assertTrue(identity["swapped"], "the adversarial race must actually fire")
                self.assertEqual((target.read_bytes(), target.stat().st_mode, victim.stat().st_mode), before,
                                 "user path swap redirected a privileged write/chmod into the victim")
                self.assertEqual(identity, {"uid": account.pw_uid, "gid": account.pw_gid,
                                            "groups": [], "swapped": phase != "normal", "regained_root": False})
                if phase == "normal":
                    self.assertEqual(json.loads(config.read_text())["credHelpers"][HOST], "isaac-artifact-registry")
                    self.assertEqual(config.stat().st_uid, account.pw_uid)

    def test_config_check_mode_does_not_create_files(self):
        path = ROLE / "library" / "artifact_registry_docker_config.py"
        self.assertTrue(path.exists(), "Docker configuration module is missing")
        module = load_module(path, "docker_config_check")
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(module.configure(Path(directory), os.getuid(), os.getgid(), HOST, check_mode=True))
            self.assertEqual(list(Path(directory).iterdir()), [])


class InputValidationTests(unittest.TestCase):
    def validator(self):
        path = ROLE / "filter_plugins" / "artifact_registry.py"
        self.assertTrue(path.exists(), "direct Ansible input validation is missing")
        return load_module(path, "registry_filters").validate_settings

    def test_valid_settings_and_disabled_defaults(self):
        validate = self.validator()
        self.assertEqual(validate(False, "", "", "", "", "{}"), {"enabled": False})
        self.assertEqual(validate("False", "aws", "", "", "", "{}"), {"enabled": False})
        result = validate("True", "gcp", "test-project", "us-central1", "workloads", json.dumps({"gr00t": IMAGE}))
        self.assertEqual(result, {"enabled": True, "registry": HOST, "images": {"gr00t": IMAGE}})
        self.assertEqual(validate(True, "gcp", "test-project", "us-central1", "workloads", {"gr00t": IMAGE}), result)

    def test_rejects_malformed_direct_ansible_variables(self):
        validate = self.validator()
        valid = [True, "gcp", "test-project", "us-central1", "workloads", json.dumps({"gr00t": IMAGE})]
        invalid = {0: ["yes", 1, None], 1: ["aws", ""], 2: ["../project", "a", "BAD-PROJECT"], 3: ["us/x", "US"], 4: ["../repo", "repo;cmd"], 5: ["[]", "null", "not-json", {"gr00t": "bad"}, '{"gr00t":"x", "gr00t":"y"}', json.dumps({"gr00t": IMAGE.replace("@sha256:", ":latest#")}), json.dumps({"gr00t": IMAGE.replace("workloads/", "elsewhere/")}), json.dumps({"bad key": IMAGE}), json.dumps({"gr00t": IMAGE + "\n"})]}
        for index, values in invalid.items():
            for value in values:
                with self.subTest(index=index, value=value):
                    settings = list(valid)
                    settings[index] = value
                    with self.assertRaises(ValueError):
                        validate(*settings)

    def test_location_must_be_regional_and_long_workload_names_are_allowed(self):
        validate = self.validator()
        for location in ["us", "eu", "us-central", "us-central1-extra"]:
            with self.subTest(location=location), self.assertRaises(ValueError):
                validate(True, "gcp", "test-project", location, "workloads", "{}")
        name = "workload_" + "x" * 80
        self.assertIn(name, validate(True, "gcp", "test-project", "us-central1", "workloads", {name: IMAGE})["images"])


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook required for isolated role tests")
class AnsibleIntegrationTests(unittest.TestCase):
    def mock_service_roles(self, directory):
        """Run real role control flow/handlers; sandbox every host side effect."""
        sandbox = Path(directory)
        roles = sandbox / "roles"
        role = roles / "gr00t"
        shutil.copytree(ROOT / "roles/gr00t", role)
        # Native installation is a sentinel: never apt/git/pip on the host.
        (role / "tasks/native.yml").write_text(yaml.safe_dump([{
            "name": "Mock native provisioning boundary",
            "mock_host": {"operation": "native", "arguments": {}},
        }]))
        def sandbox_tasks(tasks):
            for task in tasks:
                if "block" in task:
                    sandbox_tasks(task["block"])
                for key in list(task):
                    operation = key.removeprefix("ansible.builtin.")
                    if operation in {"systemd", "service_facts", "template", "getent", "copy", "file"}:
                        task["mock_host"] = {"operation": operation, "arguments": task.pop(key)}
                # Fail closed if production introduces an unsandboxed action.
                allowed = {"name", "when", "notify", "listen", "block", "mock_host",
                           "ansible.builtin.set_fact", "ansible.builtin.include_tasks",
                           "ansible.builtin.assert", "artifact_registry_docker_config",
                           "loop", "register", "no_log", "diff"}
                self.assertFalse(set(task) - allowed, task)
            return tasks
        for name, relatives in {
            "gr00t": ("tasks/main.yml", "handlers/main.yml"),
            "artifact-registry": ("tasks/main.yml", "tasks/configure.yml"),
        }.items():
            if name == "artifact-registry":
                shutil.copytree(ROLE, roles / name)
            for relative in relatives:
                path = roles / name / relative
                path.write_text(yaml.safe_dump(sandbox_tasks(yaml.safe_load(path.read_text()))))
        plugins = sandbox / "action_plugins"
        plugins.mkdir()
        (plugins / "mock_host.py").write_text(r'''
import json
from pathlib import Path
from ansible.plugins.action import ActionBase
class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        path = Path(task_vars['mock_state'])
        state = json.loads(path.read_text())
        op = self._task.args['operation']
        args = self._task.args['arguments'] or {}
        state['calls'].append({'operation': op, 'arguments': args})
        result = {'changed': False}
        if op == 'service_facts':
            result['ansible_facts'] = {'services': state['services']}
        elif op == 'systemd' and 'name' in args:
            name = args['name'] + '.service'
            before = dict(state['services'].get(name, {}))
            service = state['services'].setdefault(name, {})
            if 'enabled' in args:
                service['status'] = 'enabled' if args['enabled'] else 'disabled'
            if 'state' in args:
                service['state'] = 'stopped' if args['state'] == 'stopped' else 'running'
            result['changed'] = before != service or args.get('state') == 'restarted'
        elif op == 'template':
            content = self._templar.template(Path(self._find_needle('templates', args['src'])).read_text())
            result['changed'] = state['files'].get(args['dest']) != content
            state['files'][args['dest']] = content
        elif op == 'getent':
            result['ansible_facts'] = {'getent_passwd': {args['key']: task_vars['mock_accounts'][args['key']]}}
        elif op in ('file', 'copy'):
            destination = args.get('dest', args.get('path'))
            if 'src' in args:
                content = Path(self._find_needle('files', args['src'])).read_text()
            else:
                content = args
            result['changed'] = state['files'].get(destination) != content
            state['files'][destination] = content
        elif op == 'native':
            container = state['services'].get('isaac-gr00t-container.service', {})
            if container.get('state') == 'running' or container.get('status') == 'enabled':
                result.update(failed=True, msg='old container is still active at native provisioning')
        elif op != 'systemd':
            result.update(failed=True, msg='unexpected mocked host operation')
        path.write_text(json.dumps(state))
        return result
''')
        state = sandbox / "host-state.json"
        state.write_text(json.dumps({"services": {
            "isaac-gr00t-container.service": {"state": "running", "status": "enabled"},
        }, "calls": [], "files": {}}))
        return state

    def play(self, directory, tasks=None, roles=None, variables=None, inventory=None):
        playbook = Path(directory) / "play.yml"
        content = [{"hosts": "localhost", "gather_facts": False, "become": False,
                    "vars": variables or {}, "tasks": tasks or [], "roles": roles or []}]
        playbook.write_text(yaml.safe_dump(content))
        config = Path(directory) / "ansible.cfg"
        config.write_text("[defaults]\n")
        env = dict(os.environ, ANSIBLE_ROLES_PATH=str(Path(directory) / "roles") + os.pathsep + str(ROOT / "roles"),
                   ANSIBLE_ACTION_PLUGINS=str(Path(directory) / "action_plugins"),
                   ANSIBLE_LIBRARY=str(ROLE / "library"),
                   ANSIBLE_FILTER_PLUGINS=str(ROLE / "filter_plugins"),
                   ANSIBLE_LOCAL_TEMP=str(Path(directory) / "local"),
                   ANSIBLE_REMOTE_TEMP=str(Path(directory) / "remote"),
                   ANSIBLE_STDOUT_CALLBACK="default", ANSIBLE_DISPLAY_ARGS_TO_STDOUT="False",
                   ANSIBLE_NOCOLOR="1", ANSIBLE_CONFIG=str(config))
        return subprocess.run(["ansible-playbook", "-i", str(inventory or "localhost,"), "-c", "local", str(playbook)],
                              cwd=directory, env=env, text=True, capture_output=True, timeout=90)

    def test_native_transition_stops_container_before_provisioning(self):
        for service_enabled in (True, False):
            with self.subTest(service_enabled=service_enabled), tempfile.TemporaryDirectory() as directory:
                state = self.mock_service_roles(directory)
                variables = {"mock_state": str(state), "ansible_user": "offline-user",
                             "install_gr00t": True, "gr00t_serving_mode": "native",
                             "gr00t_service_enabled": service_enabled}
                result = self.play(directory, roles=["gr00t"], variables=variables)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                actual = json.loads(state.read_text())
                self.assertEqual(actual["services"]["isaac-gr00t-container.service"],
                                 {"state": "stopped", "status": "disabled"})
                calls = actual["calls"]
                stopped = next(i for i, call in enumerate(calls) if call["operation"] == "systemd"
                               and call["arguments"].get("name") == "isaac-gr00t-container")
                native = next(i for i, call in enumerate(calls) if call["operation"] == "native")
                self.assertLess(stopped, native)
                # Re-running native mode must not produce repeated changes.
                repeat = self.play(directory, roles=["gr00t"], variables=variables)
                self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
                self.assertRegex(repeat.stdout, r"changed=0\s")

    def test_disabled_and_no_gr00t_selection_leave_existing_services_untouched(self):
        for validated in ({"enabled": False}, {"enabled": True, "images": {"cache": IMAGE}}):
            with self.subTest(validated=validated), tempfile.TemporaryDirectory() as directory:
                state = self.mock_service_roles(directory)
                original = json.loads(state.read_text())
                result = self.play(directory, roles=["gr00t"], variables={
                    "mock_state": str(state), "install_gr00t": False,
                    "artifact_registry_validated": validated, "gr00t_serving_mode": "native",
                })
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r"changed=0\s")
                self.assertEqual(json.loads(state.read_text()), original)

    def test_native_selection_without_old_container_does_not_stop_missing_service(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.mock_service_roles(directory)
            state.write_text(json.dumps({"services": {}, "files": {}, "calls": []}))
            result = self.play(directory, roles=["gr00t"], variables={
                "mock_state": str(state), "install_gr00t": True,
                "gr00t_serving_mode": "native", "gr00t_service_enabled": False,
            })
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = json.loads(state.read_text())
            self.assertEqual([call["operation"] for call in actual["calls"]], ["service_facts", "native"])
            self.assertEqual(actual["services"], {})

    def test_registry_transition_and_digest_change_restart_only_container(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.mock_service_roles(directory)
            state.write_text(json.dumps({"services": {
                "isaac-gr00t.service": {"state": "running", "status": "enabled"},
            }, "files": {}, "calls": []}))
            variables = {"mock_state": str(state), "ansible_user": "offline-user",
                         "install_gr00t": False, "gr00t_service_enabled": False,
                         "gr00t_serving_mode": "native", "artifact_registry_root_docker_config": "/offline-root/.docker"}
            unit = "/etc/systemd/system/isaac-gr00t-container.service"
            for digest, expected_restarts in ((IMAGE, 1), (IMAGE, 1), (IMAGE.replace("a" * 64, "b" * 64), 2)):
                with self.subTest(digest=digest, expected_restarts=expected_restarts):
                    variables["artifact_registry_validated"] = {"enabled": True, "images": {"gr00t": digest}}
                    result = self.play(directory, roles=["gr00t"], variables=variables)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(state.read_text())
                    self.assertEqual(actual["services"]["isaac-gr00t.service"], {"state": "stopped", "status": "disabled"})
                    self.assertEqual(actual["services"]["isaac-gr00t-container.service"], {"state": "running", "status": "enabled"})
                    restarts = [call["arguments"]["name"] for call in actual["calls"]
                                if call["operation"] == "systemd" and call["arguments"].get("state") == "restarted"]
                    self.assertEqual(restarts, ["isaac-gr00t-container"] * expected_restarts)
                    self.assertNotIn("native", [call["operation"] for call in actual["calls"]])
                    self.assertIn(digest, actual["files"][unit])
            operations = actual["calls"]
            stop = next(i for i, call in enumerate(operations) if call["operation"] == "systemd"
                        and call["arguments"].get("name") == "isaac-gr00t")
            start = next(i for i, call in enumerate(operations) if call["operation"] == "systemd"
                         and call["arguments"].get("name") == "isaac-gr00t-container")
            self.assertLess(stop, start)

    @unittest.skipUnless(os.geteuid() == 0, "requires root for real root/SSH account merges")
    def test_enabled_gcp_from_image_inventory_configures_and_starts_container(self):
        import pwd
        sys.path.insert(0, str(ROOT.parents[1]))
        from src.python.config import c
        from src.python.deployer import Deployer
        account = pwd.getpwnam("nobody")
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            sandbox.chmod(0o755)
            state = self.mock_service_roles(directory)
            fake = sandbox / "docker"
            pulled, docker_log = sandbox / "pulled.json", sandbox / "docker-calls.jsonl"
            fake.write_text("#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\n"
                            + "state=Path(" + repr(str(pulled)) + ")\n"
                            + "with open(" + repr(str(docker_log)) + ", 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                            + "if sys.argv[1:3]==['image','inspect']:\n"
                            + "    if not state.exists(): sys.exit(1)\n"
                            + "    print(state.read_text())\n"
                            + "elif sys.argv[1]=='pull': state.write_text(json.dumps([sys.argv[2]]))\n"
                            + "else: sys.exit(99)\n")
            fake.chmod(0o700)
            accounts = {}
            for user, uid, gid in (("root", 0, 0), (account.pw_name, account.pw_uid, account.pw_gid)):
                home = sandbox / (user + "-home")
                home.mkdir(mode=0o700)
                os.chown(home, uid, gid)
                accounts[user] = ["x", str(uid), str(gid), "", str(home), "/bin/sh"]
            profile = sandbox / "profile.yaml"
            profile.write_text(yaml.safe_dump({
                "profile_name": "offline-registry", "cloud": "gcp", "security": {"tier": "custom"},
                "artifact_registry": {"enabled": True, "project": "test-project", "location": "us-central1",
                                      "repository": "workloads", "images": {"gr00t": IMAGE}},
            }))
            params = {"debug": False, "cloud": "gcp", "prefix": "isa", "deployment_name": "offline-registry",
                      "existing": "modify", "in_china": "no", "ssh_port": 22, "ingress_cidrs": "192.0.2.1/32",
                      "vnc_password": "test-only", "system_user_password": "test-only", "isaacsim": "no",
                      "isaaclab": "no", "isaaclab_arena": "no", "isaaclab_private_git": False, "demos": "no",
                      "isaac_workstation_ip": "localhost", "profile": str(profile)}
            deployer = Deployer(params, dict(c, state_dir=str(sandbox / "state"), default_ssh_user=account.pw_name))
            inventory = sandbox / "inventory"
            inventory.write_text(deployer.create_ansible_inventory(write=False))
            del deployer  # Any metadata destructor writes stay inside the sandbox.
            variables = {"mock_state": str(state), "mock_accounts": accounts, "from_image": True,
                         "ansible_python_interpreter": sys.executable,
                         "ansible_become": False, "artifact_registry_docker_binary": str(fake)}
            for iteration in range(2):
                result = self.play(directory, roles=["artifact-registry", "gr00t"], variables=variables, inventory=inventory)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stderr, "", "module privilege drop must not cause wrapper/cleanup warnings")
                if iteration:
                    self.assertRegex(result.stdout, r"changed=0\s")
            actual = json.loads(state.read_text())
            self.assertEqual(actual["services"]["isaac-gr00t-container.service"], {"state": "running", "status": "enabled"})
            self.assertNotIn("native", [call["operation"] for call in actual["calls"]])
            self.assertIn(IMAGE, actual["files"]["/etc/systemd/system/isaac-gr00t-container.service"])
            self.assertIn("/usr/local/bin/docker-credential-isaac-artifact-registry", actual["files"])
            self.assertEqual([call for call in map(json.loads, docker_log.read_text().splitlines()) if call[0] == "pull"], [["pull", IMAGE]])
            for user, entry in accounts.items():
                config = Path(entry[4]) / ".docker/config.json"
                self.assertEqual(config.stat().st_uid, int(entry[1]))
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(config.read_text())["credHelpers"][HOST], "isaac-artifact-registry")

    def test_disabled_role_default_and_from_image_have_zero_changes(self):
        self.assertTrue((ROLE / "tasks" / "main.yml").exists(), "Artifact Registry role tasks missing")
        with tempfile.TemporaryDirectory() as directory:
            for variables in [{}, {"from_image": True, "cloud": "aws", "enable_artifact_registry": "false"}]:
                result = self.play(directory, roles=["artifact-registry", "gr00t"], variables=variables)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r"changed=0\s")

    def test_invalid_role_vars_fail_before_remote_mutations(self):
        self.assertTrue((ROLE / "tasks" / "main.yml").exists(), "Artifact Registry role tasks missing")
        with tempfile.TemporaryDirectory() as directory:
            result = self.play(directory, roles=["artifact-registry"], variables={"enable_artifact_registry": True, "cloud": "gcp", "artifact_registry_project": "bad;project"})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid Artifact Registry project", result.stdout)
            self.assertRegex(result.stdout, r"changed=0\s")

    def test_digest_pull_tasks_are_idempotent_with_fake_docker_only(self):
        pull = ROLE / "tasks" / "pull.yml"
        self.assertTrue(pull.exists(), "digest pre-pull tasks missing")
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "docker"
            state = Path(directory) / "pulled.json"
            log = Path(directory) / "calls.jsonl"
            fake.write_text("#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\n"
                            + "state=Path(" + repr(str(state)) + ")\n"
                            + "with open(" + repr(str(log)) + ", 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                            + "if sys.argv[1:3]==['image','inspect']:\n"
                            + "    if not state.exists(): sys.exit(1)\n"
                            + "    print(state.read_text())\n"
                            + "elif sys.argv[1]=='pull': state.write_text(json.dumps([sys.argv[2]]))\n"
                            + "else: sys.exit(99)\n")
            fake.chmod(0o700)
            variables = {"artifact_registry_validated": {"images": {"gr00t": IMAGE}}, "artifact_registry_docker_binary": str(fake), "artifact_registry_root_docker_config": str(Path(directory) / ".docker")}
            task = {"ansible.builtin.include_tasks": str(pull)}
            first = self.play(directory, tasks=[task], variables=variables)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            second = self.play(directory, tasks=[task], variables=variables)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertRegex(second.stdout, r"changed=0\s")
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual([call for call in calls if call[0] == "pull"], [["pull", IMAGE]])
            self.assertTrue(all(call[:2] == ["image", "inspect"] or call == ["pull", IMAGE] for call in calls))

    def test_real_ansible_config_module_and_gr00t_selection_in_temporary_homes(self):
        # Exercise the actual configure tasks using synthetic passwd results.
        # Deliberately exclude helper installation and any service/Docker actions.
        configure = yaml.safe_load((ROLE / "tasks/configure.yml").read_text())
        selected = [task for task in configure if task["name"] in {
            "Merge private Docker configuration for root and the SSH user",
            "Resolve root Docker configuration path for image pulls",
            "Select the registry GR00T container service",
        }]
        self.assertEqual(len(selected), 3)
        selection = yaml.safe_load((ROOT / "roles/gr00t/tasks/main.yml").read_text())[:2]
        with tempfile.TemporaryDirectory() as directory:
            homes = [Path(directory) / "root-home", Path(directory) / "ssh-home"]
            results = []
            for user, home in zip(["root", "resolved-ssh-user"], homes):
                home.mkdir()
                (home / ".docker").mkdir()
                (home / ".docker/config.json").write_text(json.dumps({"auths": {"unrelated.example": {"auth": "offline-config-secret"}}}))
                results.append({"item": user, "ansible_facts": {"getent_passwd": {user: ["x", str(os.getuid()), str(os.getgid()), "", str(home), "/bin/sh"]}}})
            variables = {"artifact_registry_accounts": {"results": results},
                         "artifact_registry_validated": {"enabled": True, "registry": HOST, "images": {"gr00t": IMAGE}},
                         "install_gr00t": False, "gr00t_serving_mode": "native", "gr00t_service_enabled": False}
            assertions = {"ansible.builtin.assert": {"that": [
                "should_install_gr00t", "gr00t_registry_selected", "gr00t_service_enabled",
                "gr00t_effective_serving_mode == 'container'", "gr00t_container_image == artifact_registry_validated.images.gr00t",
                "artifact_registry_root_docker_config == artifact_registry_accounts.results[0].ansible_facts.getent_passwd.root[4] + '/.docker'",
            ]}}
            for iteration in range(2):
                result = self.play(directory, tasks=selected + selection + [assertions], variables=variables)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("offline-config-secret", result.stdout + result.stderr)
                if iteration:
                    self.assertRegex(result.stdout, r"changed=0\s")
            for home in homes:
                config = home / ".docker/config.json"
                self.assertEqual(json.loads(config.read_text())["credHelpers"][HOST], "isaac-artifact-registry")
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_generic_images_do_not_select_gr00t(self):
        configure = yaml.safe_load((ROLE / "tasks/configure.yml").read_text())
        task = next(task for task in configure if task["name"] == "Select the registry GR00T container service")
        selection = yaml.safe_load((ROOT / "roles/gr00t/tasks/main.yml").read_text())[:2]
        with tempfile.TemporaryDirectory() as directory:
            result = self.play(directory, tasks=[task] + selection + [{"ansible.builtin.assert": {"that": ["not should_install_gr00t", "not gr00t_registry_selected", "gr00t_effective_serving_mode == 'native'"]}}], variables={
                "artifact_registry_validated": {"enabled": True, "registry": HOST, "images": {"cache": IMAGE}},
                "install_gr00t": False, "gr00t_serving_mode": "native",
            })
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class Gr00tIntegrationTests(unittest.TestCase):
    def test_role_order_and_digest_select_existing_container_service(self):
        dependencies = yaml.safe_load((ROOT / "roles/isaac-workstation/meta/main.yml").read_text())["dependencies"]
        roles = [item["role"] for item in dependencies]
        self.assertIn("artifact-registry", roles, "registry auth must precede consumers")
        self.assertLess(roles.index("system"), roles.index("artifact-registry"))
        self.assertLess(roles.index("artifact-registry"), roles.index("gr00t"))
        tasks = yaml.safe_load((ROOT / "roles/gr00t/tasks/main.yml").read_text())
        native = [task for task in tasks if task.get("ansible.builtin.include_tasks") == "native.yml"]
        self.assertEqual(len(native), 1, "native provisioning must be separate from container mode")
        self.assertIn("native", str(native[0]["when"]))
        handlers = yaml.safe_load((ROOT / "roles/gr00t/handlers/main.yml").read_text())
        restart = next((task for task in handlers if task.get("listen") == "restart_gr00t_container"), None)
        self.assertIsNotNone(restart, "digest changes must restart container unit")
        assert restart is not None
        self.assertEqual(restart["ansible.builtin.systemd"]["name"], "isaac-gr00t-container")
        self.assertEqual(restart["ansible.builtin.systemd"]["state"], "restarted")

    def test_container_unit_renders_exact_digest(self):
        defaults = yaml.safe_load((ROOT / "roles/gr00t/defaults/main.yml").read_text())
        defaults.update(ansible_user="offline-user", gr00t_container_image=IMAGE)
        template = (ROOT / "roles/gr00t/templates/isaac-gr00t-container.service.j2").read_text()
        rendered = Environment().from_string(template).render(defaults)
        self.assertIn(IMAGE + " \\\n", rendered)
        self.assertNotIn("gr00t-dev:latest", rendered)

    def test_registry_service_uses_resolved_root_docker_configuration(self):
        defaults = yaml.safe_load((ROOT / "roles/gr00t/defaults/main.yml").read_text())
        defaults.update(ansible_user="offline-user", gr00t_registry_selected=True,
                        artifact_registry_validated={"images": {"gr00t": IMAGE}},
                        artifact_registry_root_docker_config="/root-home/.docker")
        template = (ROOT / "roles/gr00t/templates/isaac-gr00t-container.service.j2").read_text()
        rendered = Environment().from_string(template).render(defaults)
        self.assertIn('Environment="DOCKER_CONFIG=/root-home/.docker"', rendered)
        self.assertIn(IMAGE, rendered)
        self.assertNotIn("gr00t-dev:latest", rendered)


if __name__ == "__main__":
    unittest.main()
