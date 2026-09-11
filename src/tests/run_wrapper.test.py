#!/usr/bin/env python3
"""Exercise the host wrapper with a fake Docker binary; never start a container."""
import json

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestRunWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(Path(__file__).resolve().parents[2] / "run", self.root / "run")
        binary_dir = self.root / "bin"
        binary_dir.mkdir()
        docker = binary_dir / "docker"
        docker.write_text('''#!/usr/bin/python3
import json, os, sys
if sys.argv[1] == "images":
    print("synthetic-image")
    sys.exit(0)
if sys.argv[1:3] == ["context", "inspect"]:
    with open(os.environ["DOCKER_CONTEXT_LOG"], "w") as stream:
        json.dump(sys.argv[1:], stream)
    print(os.environ["DOCKER_TEST_ENDPOINT"])
    sys.exit(int(os.environ.get("DOCKER_TEST_CONTEXT_EXIT", "0")))
if sys.argv[1] != "run":
    sys.exit(90)
with open(os.environ["DOCKER_ARGUMENT_LOG"], "w") as stream:
    json.dump(sys.argv[1:], stream)
sys.exit(int(os.environ["DOCKER_TEST_EXIT"]))
''')
        docker.chmod(0o700)
        self.log = self.root / "docker.json"
        self.context_log = self.root / "context.json"
        self.env = {
            "PATH": f"{binary_dir}:/usr/bin:/bin", "HOME": str(self.root),
            "DOCKER_ARGUMENT_LOG": str(self.log), "DOCKER_TEST_EXIT": "7",
            "DOCKER_CONTEXT_LOG": str(self.context_log),
            "DOCKER_TEST_ENDPOINT": "unix:///var/run/docker.sock",
        }

    def invoke(self):
        return subprocess.run(
            ["bash", str(self.root / "run"), "synthetic-command"],
            cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10,
        )

    def test_command_failure_survives_watcher_cleanup(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertFalse((self.root / ".open-url").exists())

    def test_headless_invocation_does_not_request_a_tty(self):
        self.env["DOCKER_TEST_EXIT"] = "0"
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(self.log.read_text())
        self.assertNotIn("-it", arguments)
        self.assertNotIn("-t", arguments)
        self.assertIn("synthetic-command", arguments)

    def test_selected_identity_environment_is_forwarded_without_secret_argv(self):
        self.env.update(AWS_ACCESS_KEY_ID="synthetic-access", AWS_SECRET_ACCESS_KEY="synthetic-secret",
                        AWS_ROLE_ARN="arn:aws:iam::123456789012:role/backend",
                        ARM_CLIENT_ID="fixture-client", ARM_TENANT_ID="fixture-tenant",
                        ARM_SUBSCRIPTION_ID="fixture-subscription", ARM_USE_OIDC="true",
                        UNRELATED_PRIVATE="must-not-forward")
        result = self.invoke()
        self.assertEqual(result.returncode, 7, result.stderr)
        arguments = json.loads(self.log.read_text())
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ROLE_ARN", "ARM_CLIENT_ID",
                    "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID", "ARM_USE_OIDC"):
            self.assertIn(key, arguments)
        self.assertNotIn("synthetic-secret", " ".join(arguments))
        self.assertNotIn("UNRELATED_PRIVATE", " ".join(arguments))

    def test_gcs_access_token_is_forwarded_by_name_only(self):
        self.env['GOOGLE_OAUTH_ACCESS_TOKEN'] = 'synthetic-gcs-token-not-for-argv'
        result = self.invoke()
        self.assertEqual(result.returncode, 7, result.stderr)
        arguments = json.loads(self.log.read_text())
        self.assertIn('GOOGLE_OAUTH_ACCESS_TOKEN', arguments)
        self.assertNotIn(self.env['GOOGLE_OAUTH_ACCESS_TOKEN'], ' '.join(arguments))
        self.assertNotIn(self.env['GOOGLE_OAUTH_ACCESS_TOKEN'], result.stdout + result.stderr)

    def test_explicit_transfer_directory_is_mounted_with_selected_write_scope(self):
        local = self.root / 'selected local directory'
        local.mkdir()
        self.env['ISAAC_TRANSFER_LOCAL_DIR'] = str(local)
        for read_only in ('true', 'false'):
            with self.subTest(read_only=read_only):
                self.env['ISAAC_TRANSFER_READ_ONLY'] = read_only
                result = self.invoke()
                self.assertEqual(result.returncode, 7, result.stderr)
                args = json.loads(self.log.read_text())
                expected = f'type=bind,source={local},target=/run/isaac-transfer-local'
                if read_only == 'true':
                    expected += ',readonly'
                self.assertIn(expected, args)
                self.assertNotIn('ISAAC_TRANSFER_LOCAL_DIR', args)

    def test_transfer_mount_rejects_unsafe_paths_modes_and_remote_daemon(self):
        local = self.root / 'selected'
        local.mkdir()
        link = self.root / 'linked'
        link.symlink_to(local, target_is_directory=True)
        cases = [('/', 'true', ''), (str(link), 'true', ''),
                 (str(local / '..'), 'true', ''), (str(local), 'maybe', ''),
                 (str(local), 'true', 'tcp://remote.example:2376')]
        for path, mode, daemon in cases:
            with self.subTest(path=path, mode=mode, daemon=daemon):
                self.log.unlink(missing_ok=True)
                self.env.update(ISAAC_TRANSFER_LOCAL_DIR=path,
                                ISAAC_TRANSFER_READ_ONLY=mode, DOCKER_HOST=daemon)
                result = self.invoke()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.log.exists())

    def test_explicit_bootstrap_state_directory_is_durable_writable_mount(self):
        admin = self.root / "admin state"
        admin.mkdir(mode=0o700)
        self.env["ISAAC_BOOTSTRAP_STATE_ROOT"] = str(admin)
        result = self.invoke()
        self.assertEqual(result.returncode, 7, result.stderr)
        args = json.loads(self.log.read_text())
        self.assertIn(f"type=bind,source={admin},target=/run/isaac-bootstrap-state", args)
        self.assertNotIn("ISAAC_BOOTSTRAP_STATE_ROOT", args)
        self.env["DOCKER_HOST"] = "ssh://remote"
        self.log.unlink()
        self.assertEqual(self.invoke().returncode, 2)
        self.assertFalse(self.log.exists())

    def test_bootstrap_admin_directory_rejects_unsafe_permissions_and_links(self):
        admin = self.root / "admin"
        admin.mkdir(mode=0o777)
        admin.chmod(0o777)
        link = self.root / "linked-admin"
        link.symlink_to(admin)
        for path in (admin, link, self.root / "missing", Path("relative")):
            with self.subTest(path=path):
                self.env["ISAAC_BOOTSTRAP_STATE_ROOT"] = str(path)
                result = self.invoke()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.log.exists())

    def test_bootstrap_admin_symlinks_with_separators_never_reach_docker(self):
        admin = self.root / "private-admin"
        admin.mkdir(mode=0o700)
        (admin / "child").mkdir(mode=0o700)
        link = self.root / "linked-admin"
        link.symlink_to(admin, target_is_directory=True)
        for path in (f"{link}/", f"{link}///", f"{self.root}//linked-admin//",
                     f"{link}//child///", f"{link}/.//", f"{self.root}//linked-admin/./child/"):
            with self.subTest(path=path):
                self.log.unlink(missing_ok=True)
                self.env["ISAAC_BOOTSTRAP_STATE_ROOT"] = path
                result = self.invoke()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Linked bootstrap state directories", result.stderr)
                self.assertFalse(self.log.exists(), "linked writable mount reached Docker")

    def test_credential_symlink_components_with_separators_are_rejected(self):
        directory = self.root / "private-directory"
        directory.mkdir(mode=0o700)
        (directory / "token").write_text("synthetic fixture")
        link = self.root / "linked-directory"
        link.symlink_to(directory, target_is_directory=True)
        file_link = self.root / "linked-token"
        file_link.symlink_to(directory / "token")
        for path in (f"{link}//token", f"{self.root}//linked-directory///token",
                     f"{link}/.//token", f"{self.root}//linked-token", f"{file_link}/"):
            with self.subTest(path=path):
                self.log.unlink(missing_ok=True)
                self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = path
                result = self.invoke()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.log.exists(), "linked credential mount reached Docker")

    def test_external_credential_references_are_mapped_read_only(self):
        credential = self.root / "outside credential.json"
        credential.write_text("synthetic fixture, not credentials")
        self.env["GOOGLE_APPLICATION_CREDENTIALS"] = str(credential)
        result = self.invoke()
        self.assertEqual(result.returncode, 7, result.stderr)
        arguments = json.loads(self.log.read_text())
        destination = "/run/isaac-credentials/GOOGLE_APPLICATION_CREDENTIALS"
        self.assertIn(f"type=bind,source={credential},target={destination},readonly", arguments)
        self.assertIn(f"GOOGLE_APPLICATION_CREDENTIALS={destination}", arguments)

    def test_double_quote_credential_path_is_rejected_before_mount_csv(self):
        credential = self.root / 'quoted"credential'
        credential.write_text("synthetic fixture")
        self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = str(credential)
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Invalid external credential file reference", result.stderr)
        self.assertFalse(self.log.exists(), "quote-containing source reached Docker CSV parser")

    def test_external_mount_requires_local_selected_docker_endpoint(self):
        credential = self.root / "synthetic-token"
        credential.write_text("synthetic fixture")
        self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = str(credential)
        base_env = self.env.copy()
        cases = [
            ("default-local-context", {}, True, []),
            ("unix-host", {"DOCKER_HOST": "unix:///tmp/local.sock"}, True, None),
            ("local-pipe", {"DOCKER_HOST": "npipe:////./pipe/docker_engine"}, True, None),
            ("ssh-host", {"DOCKER_HOST": "ssh://remote"}, False, None),
            ("tcp-host", {"DOCKER_HOST": "tcp://remote:2376"}, False, None),
            ("loopback-tcp", {"DOCKER_HOST": "tcp://127.0.0.1:2375"}, False, None),
            ("remote-pipe", {"DOCKER_HOST": "npipe:////remote/pipe/docker_engine"}, False, None),
            ("relative-socket", {"DOCKER_HOST": "unix://relative.sock"}, False, None),
            ("empty-socket", {"DOCKER_HOST": "unix:///"}, False, None),
            ("unknown-host", {"DOCKER_HOST": "https://remote"}, False, None),
            ("current-remote-context", {"DOCKER_TEST_ENDPOINT": "ssh://remote"}, False, []),
            ("named-remote-over-local-host", {
                "DOCKER_CONTEXT": "remote-fixture", "DOCKER_HOST": "unix:///tmp/local.sock",
                "DOCKER_TEST_ENDPOINT": "tcp://remote:2376",
            }, False, ["remote-fixture"]),
            ("named-local-over-remote-host", {
                "DOCKER_CONTEXT": "local-fixture", "DOCKER_HOST": "ssh://remote",
            }, True, ["local-fixture"]),
            ("host-over-current-context", {
                "DOCKER_HOST": "unix:///tmp/local.sock", "DOCKER_TEST_ENDPOINT": "ssh://remote",
            }, True, None),
            ("inspect-failure", {"DOCKER_TEST_CONTEXT_EXIT": "1"}, False, []),
            ("empty-context-endpoint", {"DOCKER_TEST_ENDPOINT": ""}, False, []),
        ]
        for name, overrides, allowed, context_names in cases:
            with self.subTest(name=name):
                self.log.unlink(missing_ok=True)
                self.context_log.unlink(missing_ok=True)
                self.env = {**base_env, **overrides}
                result = self.invoke()
                self.assertEqual(result.returncode, 7 if allowed else 2, result.stderr)
                self.assertEqual(self.log.exists(), allowed)
                if not allowed:
                    self.assertIn("local Docker endpoint", result.stderr)
                if context_names is None:
                    self.assertFalse(self.context_log.exists())
                else:
                    self.assertTrue(self.context_log.exists(), "selected Docker context was not inspected")
                    self.assertEqual(json.loads(self.context_log.read_text()), [
                        "context", "inspect", *context_names,
                        "--format", "{{.Endpoints.docker.Host}}",
                    ])

    def test_symlink_to_regular_credential_file_is_rejected(self):
        target = self.root / "regular-token"
        target.write_text("synthetic fixture")
        link = self.root / "linked-token"
        link.symlink_to(target)
        self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = str(link)
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Symlinked external credential file reference", result.stderr)
        self.assertFalse(self.log.exists())

    def test_symlinked_credential_ancestor_is_rejected(self):
        directory = self.root / "regular-directory"
        directory.mkdir()
        (directory / "token").write_text("synthetic fixture")
        link = self.root / "linked-directory"
        link.symlink_to(directory, target_is_directory=True)
        self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = str(link / "token")
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Symlinked external credential file reference", result.stderr)
        self.assertFalse(self.log.exists())

    def test_control_relative_and_traversal_credential_paths_are_rejected(self):
        regular = self.root / "regular-token"
        regular.write_text("synthetic fixture")
        directory = self.root / "directory"
        directory.mkdir()
        paths = ["regular-token", f"{directory}/../regular-token"]
        for name in ("line\nbreak", "carriage\rreturn"):
            path = self.root / name
            path.write_text("synthetic fixture")
            paths.append(str(path))
        for path in paths:
            with self.subTest(path=repr(path)):
                self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = path
                result = self.invoke()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Invalid external credential file reference", result.stderr)
                self.assertFalse(self.log.exists())
                self.assertNotIn(path, result.stderr)

    def test_remote_endpoint_without_external_mounts_is_unchanged(self):
        self.env["DOCKER_HOST"] = "ssh://remote-fixture"
        self.env["AWS_ACCESS_KEY_ID"] = "synthetic-access"
        result = self.invoke()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertFalse(self.context_log.exists())
        arguments = json.loads(self.log.read_text())
        self.assertNotIn("--mount", arguments)
        self.assertIn("AWS_ACCESS_KEY_ID", arguments)
        self.assertNotIn("synthetic-access", " ".join(arguments))

    def test_invalid_credential_reference_fails_without_container_start(self):
        for kind in ("missing", "directory", "symlink", "fifo", "comma"):
            with self.subTest(kind=kind):
                path = self.root / kind
                if kind == "directory":
                    path.mkdir()
                elif kind == "symlink":
                    path.symlink_to(self.root)
                elif kind == "fifo":
                    import os
                    os.mkfifo(path)
                elif kind == "comma":
                    path = self.root / "ambiguous,path"
                    path.write_text("fixture")
                self.env["AWS_WEB_IDENTITY_TOKEN_FILE"] = str(path)
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.log.exists(), "invalid credential path reached docker run")


if __name__ == "__main__":
    unittest.main()
