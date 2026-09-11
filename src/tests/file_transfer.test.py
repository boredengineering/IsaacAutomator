"""Offline transfer tests; real rsync runs only against disposable local files."""
import importlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import shlex


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source space's $dir"
        self.destination = self.root / "destination space's $dir"
        self.source.mkdir()
        self.destination.mkdir()
        # Synthetic identities only; transports never access user SSH keys.
        (self.root / "key").write_text("synthetic fixture identity")
        (self.root / "key space.pem").write_text("synthetic fixture identity")

    def module(self):
        spec = importlib.util.find_spec("src.python.file_transfer")
        self.assertIsNotNone(spec, "Reusable transfer module is missing")
        return importlib.import_module("src.python.file_transfer")

    @unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
    def test_push_copies_contents_without_deleting_destination_files(self):
        transfer = self.module()
        (self.source / "new file").write_text("new")
        (self.destination / "keep").write_text("retained")
        result = transfer.transfer_directory(None, "push", self.source, str(self.destination))
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.destination / "new file").read_text(), "new")
        self.assertEqual((self.destination / "keep").read_text(), "retained")
    @unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
    def test_pull_deletion_requires_opt_in_and_preview_does_not_mutate(self):
        transfer = self.module()
        (self.source / "new file").write_text("updated content")
        (self.destination / "keep").write_text("retained")
        (self.destination / "new file").write_text("old")
        preview = transfer.transfer_directory(
            None, "pull", self.destination, str(self.source), delete=True, dry_run=True,
            capture_output=True,
        )
        self.assertIn("*deleting", preview.stdout)
        self.assertEqual((self.destination / "new file").read_text(), "old")
        self.assertTrue((self.destination / "keep").exists())
        transfer.transfer_directory(None, "pull", self.destination, str(self.source))
        self.assertTrue((self.destination / "keep").exists())
        self.assertEqual((self.destination / "new file").read_text(), "updated content")
        transfer.transfer_directory(None, "pull", self.destination, str(self.source), delete=True)
        self.assertFalse((self.destination / "keep").exists())
    @unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
    def test_workspace_exclusions_protect_source_and_destination(self):
        transfer = self.module()
        excluded = ["state/.tfstate", ".terraform/providers/plugin", "credentials/key.json",
                    ".env", "nested/.env.prod", "terraform.tfstate.backup", "key.pem",
                    ".ssh/id_rsa", ".aws/credentials", ".config/gcloud/token", "neo4j/data/store",
                    ".tfvars", "vars.auto.tfvars.json", "saved.tfplan", "credentials.json",
                    "secrets/passwords", ".agents/memory/session.md", "skip pattern.log"]
        for name in excluded:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("must never transfer")
        (self.source / "safe.py").write_text("ok")
        (self.destination / ".env").write_text("do not delete")
        transfer.transfer_directory(None, "push", self.source, str(self.destination),
                                    delete=True, exclude=("*.log",))
        self.assertEqual((self.destination / "safe.py").read_text(), "ok")
        self.assertEqual((self.destination / ".env").read_text(), "do not delete")
        for name in excluded:
            if name != ".env":
                self.assertFalse((self.destination / name).exists(), name)
    def test_direct_ssh_uses_protected_paths_and_verified_host_keys(self):
        transfer = self.module()
        self.assertTrue(hasattr(transfer, "TransferEndpoint"), "SSH endpoint is missing")
        endpoint = transfer.TransferEndpoint(
            host="192.0.2.4", user="ubuntu", identity_file=str(self.root / "key space.pem"),
            known_hosts_file=str(self.root / "known hosts"),
        )
        remote = "/home/ubuntu/work space';$(touch injected)"
        with mock.patch.object(transfer.subprocess, "run") as run:
            transfer.transfer_directory(endpoint, "push", self.source, remote)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "rsync")
        self.assertNotIn("sudo", " ".join(argv))
        self.assertIn("--protect-args", argv)
        self.assertIn("--partial-dir=.rsync-partial", argv)
        self.assertEqual(argv[-1], "ubuntu@192.0.2.4:" + remote)
        ssh = shlex.split(argv[argv.index("-e") + 1])
        self.assertIn("StrictHostKeyChecking=accept-new", ssh)
        self.assertIn('UserKnownHostsFile="' + str(self.root / "known hosts") + '"', ssh)
        self.assertIn(str(self.root / "key space.pem"), ssh)
        setup = argv[argv.index("--rsync-path") + 1]
        self.assertEqual(shlex.split(setup.split(" && ")[0]), ["mkdir", "-p", "--", remote])
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        with mock.patch.object(transfer.subprocess, "run") as run:
            transfer.transfer_directory(endpoint, "push", self.source, remote, dry_run=True)
        self.assertNotIn("--rsync-path", run.call_args.args[0])
        with mock.patch.object(transfer.subprocess, "run") as run:
            transfer.transfer_directory(endpoint, "pull", self.destination, remote)
        self.assertNotIn("--rsync-path", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-2], "ubuntu@192.0.2.4:" + remote + "/")
    def test_iap_endpoint_uses_explicit_cloud_target_without_public_ip(self):
        transfer = self.module()
        endpoint = transfer.TransferEndpoint(
            host="private-vm", user="actual_os_user", identity_file=str(self.root / "key"),
            known_hosts_file=str(self.root / "known_hosts"),
            iap=True, instance="private-vm", project="actual-project", zone="us-central1-a",
        )
        with mock.patch.object(transfer.subprocess, "run") as run:
            transfer.transfer_directory(endpoint, "pull", self.destination, "results")
        ssh = shlex.split(run.call_args.args[0][run.call_args.args[0].index("-e") + 1])
        proxy = next(arg for arg in ssh if arg.startswith("ProxyCommand="))
        self.assertEqual(shlex.split(proxy.split("=", 1)[1]), [
            "gcloud", "compute", "start-iap-tunnel", "private-vm", "22",
            "--listen-on-stdin", "--project=actual-project", "--zone=us-central1-a", "--quiet",
        ])
        self.assertIn("HostKeyAlias=private-vm.actual-project.us-central1-a", ssh)
        self.assertEqual(run.call_args.args[0][-2], "actual_os_user@private-vm:results/")
    def test_saved_gcp_target_discovers_oslogin_identity_not_generic_user(self):
        transfer = self.module()
        self.assertTrue(hasattr(transfer, "endpoint_from_config"), "Saved endpoint resolver missing")
        metadata = {"params": {"cloud": "gcp", "project": "wrong-old", "zone": "old-zone",
                               "enable_iap_only": True, "enable_oslogin": True}}
        outputs = {
            "cloud": {"value": "gcp"}, "isaac_workstation_ip": {"value": ""},
            "isaac_workstation_vm_id": {"value": "projects/actual-project/zones/us-central1-a/instances/private-vm"},
            "iap_enabled": {"value": True}, "oslogin_enabled": {"value": True},
        }
        identity = str(self.root / "google key")
        # These dangerous gcloud defaults must NOT propagate to our SSH transport.
        dry_run = shlex.join(["/usr/bin/ssh", "-i", identity, "-o", "StrictHostKeyChecking=no",
                              "-o", "ProxyCommand=ignored", "real_login@compute.123"])
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, dry_run, ""))
        endpoint = transfer.endpoint_from_config(metadata, outputs, self.root,
                                                 gcloud_runner=runner)
        self.assertEqual(endpoint.user, "real_login")
        self.assertEqual(endpoint.identity_file, identity)
        self.assertEqual(endpoint.host, "private-vm")
        self.assertEqual(endpoint.project, "actual-project")
        self.assertEqual(endpoint.zone, "us-central1-a")
        self.assertEqual(endpoint.known_hosts_file, str(self.root / "known_hosts"))
        self.assertEqual(runner.call_args.args[0], [
            "gcloud", "compute", "ssh", "private-vm", "--project=actual-project",
            "--zone=us-central1-a", "--dry-run", "--quiet", "--tunnel-through-iap",
        ])
        self.assertIn("StrictHostKeyChecking=accept-new", endpoint.ssh_argv())
        self.assertNotIn("StrictHostKeyChecking=no", endpoint.ssh_argv())
        self.assertEqual(runner.call_args.kwargs["timeout"], 60)
        self.assertTrue(runner.call_args.kwargs["capture_output"])
    def test_saved_connection_modes_and_boolean_strings(self):
        transfer = self.module()
        for cloud, iap, oslogin in [("aws", False, False), ("gcp", True, False),
                                    ("gcp", False, True), ("gcp", False, False)]:
            with self.subTest(cloud=cloud, iap=iap, oslogin=oslogin):
                metadata = {"params": {"cloud": cloud, "project": "saved-project", "zone": "saved-zone"}}
                outputs = {"cloud": cloud, "isaac_workstation_ip": "192.0.2.5",
                           "isaac_workstation_vm_id": "actual-vm", "iap_enabled": str(iap).lower(),
                           "oslogin_enabled": str(oslogin)}
                runner = mock.Mock(return_value=subprocess.CompletedProcess(
                    [], 0, "ssh -i /tmp/google_key actual_user@192.0.2.5", ""))
                endpoint = transfer.endpoint_from_config(metadata, outputs, self.root,
                                                         gcloud_runner=runner)
                self.assertEqual(endpoint.iap, iap)
                self.assertEqual(endpoint.host, "actual-vm" if iap else "192.0.2.5")
                self.assertEqual(endpoint.user, "actual_user" if oslogin else "ubuntu")
                self.assertEqual(endpoint.identity_file,
                                 "/tmp/google_key" if oslogin else str(self.root / "key.pem"))
                if oslogin:
                    runner.assert_called_once()
                    self.assertNotIn("--tunnel-through-iap", runner.call_args.args[0])
                else:
                    runner.assert_not_called()
    def test_unsafe_endpoint_fields_are_rejected_before_execution(self):
        transfer = self.module()
        valid = dict(host="192.0.2.4", user="ubuntu", identity_file=str(self.root / "key"),
                     known_hosts_file=str(self.root / "known_hosts"))
        for field, value in [("host", "-oProxyCommand=bad"), ("user", "user;bad"),
                             ("host", ""), ("host", "NA"), ("identity_file", "relative"),
                             ("known_hosts_file", "/dev/null"),
                             ("known_hosts_file", str(self.root / "host%h"))]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                transfer.TransferEndpoint(**{**valid, field: value})
        for fields in [dict(iap=True), dict(iap=True, instance="vm%h", project="p", zone="z")]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                transfer.TransferEndpoint(**valid, **fields)
        linked = self.root / "linked"
        linked.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            transfer.TransferEndpoint(**{**valid, "known_hosts_file": str(linked / "hosts")})
    def test_oslogin_discovery_fails_closed_without_logging_provider_output(self):
        transfer = self.module()
        metadata = {"params": {"cloud": "gcp", "project": "p", "zone": "z",
                               "enable_oslogin": True, "enable_iap_only": True}}
        outputs = {"isaac_workstation_vm_id": "vm", "isaac_workstation_ip": ""}
        for stdout in ["ssh vm", "provider diagnostic TOKEN=secret", "ssh -i /tmp/key vm",
                       "ssh -i /tmp/key user@vm;evil", "ssh -i /tmp/key user@vm extra"]:
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout, "secret"))
            with self.subTest(stdout=stdout), self.assertRaisesRegex(ValueError, "OS Login") as err:
                transfer.endpoint_from_config(metadata, outputs, self.root, gcloud_runner=runner)
            self.assertNotIn("secret", str(err.exception))
        runner = mock.Mock(side_effect=subprocess.CalledProcessError(1, ["gcloud"], stderr="secret"))
        with self.assertRaisesRegex(ValueError, "OS Login") as err:
            transfer.endpoint_from_config(metadata, outputs, self.root, gcloud_runner=runner)
        self.assertNotIn("secret", str(err.exception))
        runner.reset_mock()
        with self.assertRaises(ValueError):
            transfer.endpoint_from_config(metadata, {**outputs, "isaac_workstation_vm_id": "-bad"},
                                          self.root, gcloud_runner=runner)
        runner.assert_not_called()
    def test_public_commands_accept_selected_paths_preview_and_repeated_excludes(self):
        import runpy
        from click.testing import CliRunner
        from src.python.config import c as config
        transfer = self.module()
        endpoint = transfer.TransferEndpoint("192.0.2.1", "ubuntu", str(self.root / "key"),
                                             str(self.root / "hosts"))
        for command, direction in [("upload", "push"), ("download", "pull")]:
            with self.subTest(command=command), mock.patch("src.python.utils.deployments", return_value=["fixture"]), \
                    mock.patch.object(transfer, "load_endpoint", return_value=endpoint, create=True), \
                    mock.patch.object(transfer, "transfer_directory") as perform:
                main = runpy.run_path(str(Path(__file__).resolve().parents[2] / command))["main"]
                result = CliRunner().invoke(main, ["fixture", "--local-dir", str(self.source),
                    "--remote-dir", "/home/ubuntu/work space", "--dry-run", "--exclude", "*.log",
                    "--exclude", "skip folder/", "--instance-role", "isaac_workstation"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(perform.call_args.args,
                                 (endpoint, direction, str(self.source), "/home/ubuntu/work space"))
                self.assertEqual(perform.call_args.kwargs["exclude"], ("*.log", "skip folder/"))
                self.assertTrue(perform.call_args.kwargs["dry_run"])
                self.assertFalse(perform.call_args.kwargs["delete"])
                self.assertIn("overwrite", result.output.lower())
    def test_endpoint_loader_uses_one_authoritative_backend_output_read(self):
        from src.python import utils, backend_runtime
        transfer = self.module()
        self.assertTrue(hasattr(transfer, "load_endpoint"), "Public loader is missing")
        meta = {"params": {"cloud": "gcp", "project": "p", "zone": "z"}}
        outputs = {"cloud": {"value": "gcp"}, "isaac_workstation_ip": {"value": "192.0.2.7"},
                   "isaac_workstation_vm_id": {"value": "vm"}}
        runner = mock.MagicMock()
        runner.output.return_value = outputs
        record = object()
        with mock.patch.object(utils, "approved_deployment_path", return_value=self.root), \
                mock.patch.object(utils, "read_meta", return_value=meta), \
                mock.patch.object(utils, "read_tf_output", side_effect=AssertionError("Stale local read")), \
                mock.patch.object(backend_runtime, "load_backend_record", return_value=record), \
                mock.patch.object(backend_runtime, "record_runner") as context:
            context.return_value.__enter__.return_value = runner
            endpoint = transfer.load_endpoint("fixture", "isaac_workstation")
            self.assertEqual(endpoint.host, "192.0.2.7")
            runner.init.assert_called_once_with()
            runner.output.assert_called_once_with()
            self.assertTrue(context.call_args.kwargs["read_only"])
        with mock.patch.object(utils, "approved_deployment_path", return_value=self.root), \
                mock.patch.object(utils, "read_meta", return_value=meta), \
                mock.patch.object(backend_runtime, "load_backend_record", return_value=None), \
                mock.patch.object(utils, "read_tf_output", side_effect=lambda name, key, **kw: outputs.get(key, {}).get("value", "")):
            endpoint = transfer.load_endpoint("fixture", "isaac_workstation")
            self.assertEqual(endpoint.host, "192.0.2.7")
    def test_absent_optional_outputs_use_saved_security_settings(self):
        transfer = self.module()
        meta = {"params": {"cloud": "gcp", "project": "p", "zone": "z",
                           "enable_iap_only": True, "enable_oslogin": True}}
        outputs = {"cloud": "", "iap_enabled": "", "oslogin_enabled": "",
                   "isaac_workstation_vm_id": "vm"}
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "ssh -i /tmp/key login@vm", ""))
        endpoint = transfer.endpoint_from_config(meta, outputs, self.root, gcloud_runner=runner)
        self.assertTrue(endpoint.iap)
        self.assertEqual(endpoint.user, "login")
        with self.assertRaises(ValueError):
            transfer.endpoint_from_config(meta, {**outputs, "iap_enabled": "unknown"}, self.root,
                                          gcloud_runner=runner)
    def test_cli_folder_defaults_and_oslogin_home_are_usable(self):
        from click.testing import CliRunner
        from src.python.config import c as config
        transfer = self.module()
        uploads = self.root / "uploads"
        results = self.root / "results"
        with mock.patch.dict(config, {"uploads_dir": str(uploads), "results_dir": str(results)}):
            for direction, user in [("push", "ubuntu"), ("pull", "ubuntu"), ("push", "os_user")]:
                with self.subTest(direction=direction, user=user):
                    endpoint = transfer.TransferEndpoint("vm", user, str(self.root / "key"), str(self.root / "hosts"))
                    with mock.patch.object(transfer, "load_endpoint", return_value=endpoint), \
                            mock.patch.object(transfer, "transfer_directory") as perform:
                        result = CliRunner().invoke(transfer.transfer_command(direction), ["fixture"])
                    self.assertEqual(result.exit_code, 0, result.output)
                    expected = uploads if direction == "push" else results / "fixture" / "isaac_workstation"
                    self.assertEqual(Path(perform.call_args.args[2]), expected)
                    self.assertTrue(expected.is_dir())
                    if user == "os_user":
                        self.assertEqual(perform.call_args.args[3], "uploads")
                    else:
                        self.assertEqual(perform.call_args.args[3], config[
                            "default_remote_uploads_dir" if direction == "push" else "default_remote_results_dir"])
    def test_cli_failures_preserve_status_without_success_or_secret_output(self):
        from click.testing import CliRunner
        transfer = self.module()
        endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(self.root / "key"), str(self.root / "hosts"))
        from src.python.terraform_runner import TerraformRunnerError
        for error, status in [(subprocess.CalledProcessError(23, ["rsync"], stderr="SECRET"), 23),
                              (TerraformRunnerError("Saved backend output unavailable; no fallback"), 1),
                              (subprocess.TimeoutExpired(["rsync"], 1), 124),
                              (KeyboardInterrupt(), 130), (ValueError("Invalid transfer target"), 1)]:
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(transfer, "load_endpoint", return_value=endpoint), \
                    mock.patch.object(transfer, "transfer_directory", side_effect=error):
                result = CliRunner().invoke(transfer.transfer_command("push"),
                                            ["fixture", "--local-dir", str(self.source)])
                self.assertEqual(result.exit_code, status, result.output)
                self.assertIn("Error:", result.output)
                self.assertNotIn("Transfer complete", result.output)
                self.assertNotIn("SECRET", result.output)
    @unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
    def test_real_rsync_transport_roundtrip_quotes_remote_shell_paths(self):
        transfer = self.module()
        transport = self.root / "local ssh transport"
        transport.write_text("#!/usr/bin/python3\nimport os, sys\n"
                             "# Emulate SSH's remote command concatenation, without network.\n"
                             + "os.chdir(" + repr(str(self.root)) + ")\n"
                             + "os.execvp('sh', ['sh', '-c', ' '.join(sys.argv[sys.argv.index('fixture-host') + 1:])])\n")
        transport.chmod(0o700)
        endpoint = transfer.TransferEndpoint("fixture-host", "ubuntu", str(self.root / "key"),
                                             str(self.root / "known_hosts"))
        remote = self.root / "remote space' $(touch INJECTED)"
        (self.source / "payload space' $file").write_text("content")
        with mock.patch.object(transfer.TransferEndpoint, "ssh_argv", return_value=[str(transport)]):
            transfer.transfer_directory(endpoint, "push", self.source, str(remote), capture_output=True)
            transfer.transfer_directory(endpoint, "pull", self.destination, str(remote), capture_output=True)
        self.assertEqual((self.destination / "payload space' $file").read_text(), "content")
        self.assertTrue(remote.is_dir())
        self.assertFalse((self.root / "INJECTED").exists())

    def test_root_aliases_are_rejected_before_any_transport(self):
        transfer = self.module()
        linked = self.root / "root-link"
        linked.symlink_to("/", target_is_directory=True)
        endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(self.root / "key"),
                                             str(self.root / "hosts"))
        for delete in (False, True):
            for ep in (None, endpoint):
                for direction in ("push", "pull"):
                    for alias in ("/tmp/..", "/.", "//", str(linked)):
                        with self.subTest(local=alias, direction=direction, delete=delete, ssh=bool(ep)), \
                                mock.patch.object(transfer.subprocess, "run") as run:
                            with self.assertRaises(ValueError):
                                transfer.transfer_directory(ep, direction, alias, "work", delete=delete)
                            run.assert_not_called()
                    aliases = ("/tmp/..", "/.", "//", "/a/../.")
                    if ep is None:
                        aliases += (str(linked),)
                    for alias in aliases:
                        with self.subTest(remote=alias, direction=direction, delete=delete, ssh=bool(ep)), \
                                mock.patch.object(transfer.subprocess, "run") as run:
                            with self.assertRaises(ValueError):
                                transfer.transfer_directory(ep, direction, self.source, alias, delete=delete)
                            run.assert_not_called()

    def test_remote_parent_traversal_is_refused_but_relative_child_is_allowed(self):
        transfer = self.module()
        endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(self.root / "key"),
                                             str(self.root / "hosts"))
        for remote in (".", "./", "..", "../work", "link/../work", "/link/../work"):
            with self.subTest(remote=remote), mock.patch.object(transfer.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    transfer.transfer_directory(endpoint, "push", self.source, remote)
                run.assert_not_called()
        with mock.patch.object(transfer.subprocess, "run") as run:
            transfer.transfer_directory(endpoint, "push", self.source, "./foo")
        self.assertEqual(run.call_args.args[0][-1], "ubuntu@vm:./foo")

    def test_invalid_transfer_requests_fail_before_starting_rsync(self):
        transfer = self.module()
        for direction, local, remote in [("both", self.source, str(self.destination)),
                                          ("push", self.source, ""), ("pull", self.destination, "/"),
                                          ("push", "/", str(self.destination)),
                                          ("push", self.source, "bad\npath")]:
            with self.subTest(direction=direction, remote=remote), \
                    mock.patch.object(transfer.subprocess, "run") as run, self.assertRaises(ValueError):
                transfer.transfer_directory(None, direction, local, remote)
            run.assert_not_called()
    @unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
    def test_missing_pull_source_never_deletes_existing_local_data(self):
        transfer = self.module()
        (self.destination / "keep").write_text("retained")
        with self.assertRaises(subprocess.CalledProcessError):
            transfer.transfer_directory(None, "pull", self.destination,
                                        str(self.root / "missing remote"), delete=True, capture_output=True)
        self.assertEqual((self.destination / "keep").read_text(), "retained")

    @unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
    def test_real_interrupted_transfer_retains_partial_then_completes(self):
        import os
        import signal
        import sys
        import time
        transfer = self.module()
        payload = os.urandom(4 * 1024 * 1024)
        (self.source / "large.bin").write_bytes(payload)
        binary = self.root / "bin"
        binary.mkdir()
        wrapper = binary / "rsync"
        rsync_binary = shutil.which("rsync")
        assert rsync_binary is not None
        wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(rsync_binary) + ' --bwlimit=512 "$@"\n')
        wrapper.chmod(0o700)
        code = ("from src.python.file_transfer import transfer_directory; "
                + f"transfer_directory(None, 'push', {str(self.source)!r}, {str(self.destination)!r})")
        env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
               "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        process = subprocess.Popen([sys.executable, "-c", code], env=env, cwd=self.root,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if list(self.destination.glob(".large.bin.*")):
                    break
                if process.poll() is not None:
                    self.fail("Rsync exited before interruption")
                time.sleep(0.02)
            else:
                self.fail("Rsync did not begin within the fixture deadline")
            os.killpg(process.pid, signal.SIGINT)
            process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            partial = self.destination / ".rsync-partial" / "large.bin"
            self.assertTrue(partial.is_file(), "Interrupted payload was not retained")
            self.assertLess(partial.stat().st_size, len(payload))
            transfer.transfer_directory(None, "push", self.source, str(self.destination), capture_output=True)
            self.assertEqual((self.destination / "large.bin").read_bytes(), payload)
            self.assertFalse(partial.exists())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
    def test_identity_is_revalidated_before_transport_without_reading_contents(self):
        import os
        transfer = self.module()
        link = self.root / "linked-key"
        link.symlink_to(self.root / "key")
        ancestor = self.root / "linked-directory"
        ancestor.symlink_to(self.root, target_is_directory=True)
        fifo = self.root / "fifo-key"
        os.mkfifo(fifo)
        directory = self.root / "directory-key"
        directory.mkdir()
        for identity in (self.root / "missing", directory, link, ancestor / "key", fifo):
            endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(identity), str(self.root / "hosts"))
            with self.subTest(identity=identity), mock.patch.object(transfer.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "identity"):
                    transfer.transfer_directory(endpoint, "push", self.source, "uploads")
                run.assert_not_called()
                self.assertFalse((self.root / "hosts").exists())
        endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(self.root / "key"),
                                             str(self.root / "hosts"))
        (self.root / "key").unlink()
        (self.root / "key").symlink_to(self.root / "key space.pem")
        with mock.patch.object(transfer.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "identity"):
                transfer.transfer_directory(endpoint, "pull", self.destination, "results", dry_run=True)
            run.assert_not_called()

    def test_host_download_routes_output_to_persistent_selected_directory(self):
        import os
        import runpy
        import sys
        transfer = self.module()
        repo = Path(__file__).resolve().parents[2]
        host_directory = self.destination
        original_exists = os.path.exists

        def simulated_run(argv, *, env=None):
            assert env is not None, "Host transfer requires a scoped mount environment"
            self.assertEqual(argv[0], str(repo / "run"))
            command = shlex.split(argv[1])
            self.assertEqual(command, ["./download", "fixture", "--local-dir",
                                       "/run/isaac-transfer-local", "--remote-dir", "results"])
            self.assertEqual(env["ISAAC_TRANSFER_LOCAL_DIR"], str(host_directory))
            self.assertEqual(env["ISAAC_TRANSFER_READ_ONLY"], "false")
            # Emulate the bind mount, not Docker: the target routes to HOST data,
            # never the same-looking /tmp path inside an ephemeral container.
            (Path(env["ISAAC_TRANSFER_LOCAL_DIR"]) / "downloaded.txt").write_text("remote fixture")
            return 0

        with mock.patch.object(sys, "argv", [str(repo / "download"), "fixture", "--local-dir",
                                             str(host_directory), "--remote-dir", "results"]), \
                mock.patch.object(os.path, "exists", side_effect=lambda p: False if p == "/.dockerenv" else original_exists(p)), \
                mock.patch.object(transfer.subprocess, "call", side_effect=simulated_run) as run:
            with self.assertRaises(SystemExit) as exited:
                runpy.run_path(str(repo / "download"), run_name="__main__")
        self.assertEqual(exited.exception.code, 0)
        run.assert_called_once()
        self.assertEqual((host_directory / "downloaded.txt").read_text(), "remote fixture")

    def test_host_parser_scopes_mount_env_and_honors_option_values_and_separator(self):
        transfer = self.module()
        environment = {"PATH": "/synthetic/bin", "ISAAC_TRANSFER_LOCAL_DIR": "/inherited",
                       "ISAAC_TRANSFER_READ_ONLY": "false"}
        before = environment.copy()
        selected = str(self.source)
        cases = [
            ("push", ["fixture", "--local-dir", selected], True, "true"),
            ("pull", ["fixture", "--local-dir=" + selected], True, "false"),
            ("pull", ["--dry-run", "fixture", "--local-dir=" + selected], True, "true"),
            ("pull", ["fixture", "--local-dir", selected, "--exclude", "--dry-run"], True, "false"),
            ("pull", ["fixture", "--local-dir", selected, "--", "--dry-run"], True, "false"),
            ("push", ["fixture"], False, None),
            ("pull", ["fixture", "--", "--local-dir", selected], False, None),
            ("pull", ["fixture", "--", "--local-dir=" + selected], False, None),
            ("pull", ["fixture", "--exclude", "--local-dir", "--remote-dir=results"], False, None),
            ("pull", ["fixture", "--remote-dir", "--local-dir", "--dry-run"], False, None),
        ]
        for direction, arguments, mounted, read_only in cases:
            with self.subTest(direction=direction, arguments=arguments):
                original_arguments = list(arguments)
                argv, env = transfer.host_transfer_invocation(direction, arguments, self.root, environment)
                self.assertEqual(argv[0], str(self.root / "run"))
                command = shlex.split(argv[1])
                expected = list(arguments)
                if mounted:
                    expected = ["/run/isaac-transfer-local" if a == selected else
                                "--local-dir=/run/isaac-transfer-local" if a == "--local-dir=" + selected else a
                                for a in expected]
                    self.assertEqual(env["ISAAC_TRANSFER_LOCAL_DIR"], selected)
                    self.assertEqual(env["ISAAC_TRANSFER_READ_ONLY"], read_only)
                else:
                    self.assertNotIn("ISAAC_TRANSFER_LOCAL_DIR", env)
                    self.assertNotIn("ISAAC_TRANSFER_READ_ONLY", env)
                self.assertEqual(command, ["./upload" if direction == "push" else "./download", *expected])
                self.assertEqual(env["PATH"], "/synthetic/bin")
                self.assertEqual(environment, before)
                self.assertEqual(arguments, original_arguments)

    def test_host_parser_refuses_ambiguous_or_unsafe_mount_selections(self):
        transfer = self.module()
        linked = self.root / "linked-host-directory"
        linked.symlink_to(self.source, target_is_directory=True)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        root_link = self.root / "root-link"
        root_link.symlink_to("/", target_is_directory=True)
        comma = self.root / "comma,directory"
        comma.mkdir()
        quoted = self.root / 'double"quote'
        quoted.mkdir()
        selected = str(self.source)
        bad = [
            ["--local-dir"], ["--local-dir", "--"], ["--local-dir", "--dry-run"],
            ["--local-dir", ""], ["--local-dir="],
            ["--local-dir", selected, "--local-dir", selected],
            ["--local-dir=" + selected, "--local-dir=" + selected],
            ["--local-dir=" + selected, "--local-dir", selected],
        ]
        bad += [["--local-dir", path] for path in (
            "/", "/tmp/..", "/.", "//", str(root_link), str(linked),
            str(linked_parent / self.source.name), str(self.root / "missing"),
            str(self.root / "key"), str(comma), str(quoted), "bad\npath", "bad\rpath", "bad\x00path",
        )]
        for options in bad:
            with self.subTest(options=options), mock.patch.object(transfer.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    transfer.host_transfer_invocation("pull", ["fixture", *options], self.root, {})
                run.assert_not_called()
        self.assertFalse((self.root / "missing").exists(), "Explicit paths are not auto-created")
        with self.assertRaises(ValueError):
            transfer.host_transfer_invocation("both", ["fixture"], self.root, {})

    def test_host_wrappers_preserve_quoted_arguments_readonly_and_exit_status(self):
        import os
        import runpy
        import sys
        transfer = self.module()
        repo = Path(__file__).resolve().parents[2]
        original_exists = os.path.exists
        for name in ("upload", "download"):
            for preview in (False, True):
                arguments = ["fixture", "--local-dir=" + str(self.source), "--remote-dir",
                             "work space';$(touch NEVER)", "--exclude", "*.log"]
                if preview:
                    arguments.append("--dry-run")
                with self.subTest(name=name, preview=preview), \
                        mock.patch.object(sys, "argv", [str(repo / name), *arguments]), \
                        mock.patch.object(os.path, "exists", side_effect=lambda p: False if p == "/.dockerenv" else original_exists(p)), \
                        mock.patch.object(transfer.subprocess, "call", return_value=23) as run:
                    with self.assertRaises(SystemExit) as exited:
                        runpy.run_path(str(repo / name), run_name="__main__")
                self.assertEqual(exited.exception.code, 23)
                self.assertIn("env", run.call_args.kwargs, "Wrapper must supply scoped transport env")
                env = run.call_args.kwargs["env"]
                self.assertEqual(env["ISAAC_TRANSFER_LOCAL_DIR"], str(self.source))
                self.assertEqual(env["ISAAC_TRANSFER_READ_ONLY"], str(name == "upload" or preview).lower())
                arguments[1] = "--local-dir=/run/isaac-transfer-local"
                self.assertEqual(shlex.split(run.call_args.args[0][1]), ["./" + name, *arguments])
                self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_host_wrapper_invalid_selection_fails_cleanly_before_run(self):
        import io
        import os
        import runpy
        import sys
        transfer = self.module()
        repo = Path(__file__).resolve().parents[2]
        original_exists = os.path.exists
        for name in ("upload", "download"):
            with self.subTest(name=name), \
                    mock.patch.object(sys, "argv", [str(repo / name), "fixture", "--local-dir", "/tmp/.."]), \
                    mock.patch.object(os.path, "exists", side_effect=lambda p: False if p == "/.dockerenv" else original_exists(p)), \
                    mock.patch.object(sys, "stderr", new_callable=io.StringIO) as errors, \
                    mock.patch.object(transfer.subprocess, "call") as run:
                try:
                    runpy.run_path(str(repo / name), run_name="__main__")
                except SystemExit as exited:
                    self.assertEqual(exited.code, 2)
                except ValueError:
                    self.fail("Invalid host paths must be reported without a Python traceback")
                else:
                    self.fail("Invalid host paths must fail before starting run")
                run.assert_not_called()
                self.assertIn("Error:", errors.getvalue())

    def test_host_relative_paths_and_default_environment_are_scoped(self):
        import os
        transfer = self.module()
        environment = {"PATH": "/synthetic/bin", "ISAAC_TRANSFER_LOCAL_DIR": "/inherited",
                       "ISAAC_TRANSFER_READ_ONLY": "true"}
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.root)
        with mock.patch.dict(os.environ, environment, clear=True):
            argv, env = transfer.host_transfer_invocation(
                "pull", ["fixture", "--local-dir", "./" + self.source.name], self.root)
            self.assertEqual(env["ISAAC_TRANSFER_LOCAL_DIR"], str(self.source))
            self.assertEqual(env["ISAAC_TRANSFER_READ_ONLY"], "false")
            self.assertEqual(shlex.split(argv[1])[-1], "/run/isaac-transfer-local")
            argv, env = transfer.host_transfer_invocation("pull", ["fixture"], self.root)
            self.assertEqual(env, {"PATH": "/synthetic/bin"})
            self.assertEqual(shlex.split(argv[1]), ["./download", "fixture"])
            self.assertEqual(dict(os.environ), environment)

    def test_trust_file_must_be_writable_and_existing_keys_are_never_replaced(self):
        transfer = self.module()
        hosts = self.root / "known_hosts"
        hosts.write_text("fixture pinned key\n")
        endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(self.root / "key"), str(hosts))
        with mock.patch.object(transfer.subprocess, "run"):
            transfer.transfer_directory(endpoint, "push", self.source, "uploads", dry_run=True)
        self.assertEqual(hosts.read_text(), "fixture pinned key\n")
        endpoint = transfer.TransferEndpoint("vm", "ubuntu", str(self.root / "key"),
                                             str(self.root / "missing trust directory" / "hosts"))
        with mock.patch.object(transfer.subprocess, "run") as run, self.assertRaises(OSError):
            transfer.transfer_directory(endpoint, "push", self.source, "uploads")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
