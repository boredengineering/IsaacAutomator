#!/usr/bin/env python3
"""Offline CLI contract: validation must not authenticate or execute Terraform."""
import importlib.util
import json
import runpy
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner


class TestStateBackendCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "backend.yaml"

    def test_validate_local_configuration_without_cloud_or_terraform(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.state_backend_command"))
        from src.python.state_backend_command import main
        self.path.write_text("terraform_state:\n  schema_version: 1\n  backend: local\n")
        with mock.patch("subprocess.run", side_effect=AssertionError("No subprocess during validation")):
            result = CliRunner().invoke(main, ["validate", "--config", str(self.path), "--cloud", "aws"])
        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertEqual(report["status"], "valid-config")
        self.assertEqual(report["backend"], "local")
        self.assertEqual(report["cloud_access"], "not_checked")
        self.assertEqual(report["remote_lifecycle"], "not_checked")
        self.assertEqual(report["terraform_version"], "not_checked")
        self.assertEqual(len(report["configuration_sha256"]), 64)


    def test_native_s3_locking_checks_the_supplied_version_offline(self):
        from src.python.state_backend_command import main
        self.path.write_text(json.dumps({
            "backend": "s3", "namespace": "studio-dev", "destination": {
                "bucket": "example-state-bucket", "region": "us-east-1",
                "owner_account_id": "123456789012", "key_prefix": "isaacautomator/v2",
            },
        }))
        args = ["validate", "--config", str(self.path), "--cloud", "aws", "--terraform-version"]
        with mock.patch("subprocess.run", side_effect=AssertionError("Offline validation")):
            rejected = CliRunner().invoke(main, [*args, "1.8.5"])
            accepted = CliRunner().invoke(main, [*args, "1.10.0"])
        self.assertNotEqual(rejected.exit_code, 0)
        self.assertIn("1.10.0", rejected.output)
        self.assertEqual(accepted.exit_code, 0, accepted.output)
        self.assertEqual(json.loads(accepted.output)["terraform_version"], "1.10.0")

    def test_propose_outputs_loadable_config_without_cloud_lookup(self):
        from src.python.state_backend_command import main
        with mock.patch("subprocess.run", side_effect=AssertionError("proposal must be offline")):
            proposed = CliRunner().invoke(main, ["propose", "--cloud", "aws", "--namespace", "studio",
                                               "--owner-scope", "123456789012", "--region", "us-east-1"])
            self.assertEqual(proposed.exit_code, 0, proposed.output)
            self.path.write_text(proposed.output)
            validated = CliRunner().invoke(main, ["validate", "--cloud", "aws", "--config", str(self.path)])
        self.assertEqual(validated.exit_code, 0, validated.output)
        self.assertEqual(json.loads(validated.output)["cloud_access"], "not_checked")

    def test_doctor_requires_explicit_reads_and_reports_partial_honestly(self):
        from src.python.state_backend_command import main
        from src.python.backend_bootstrap import HealthReport
        self.path.write_text(json.dumps({"backend": "s3", "namespace": "studio-dev", "destination": {
            "bucket": "example-state-bucket", "region": "us-east-1",
            "owner_account_id": "123456789012", "key_prefix": "isaacautomator/v2"}}))
        args = ["doctor", "--config", str(self.path), "--cloud", "aws"]
        with mock.patch("src.python.backend_bootstrap.doctor", return_value=HealthReport(
                "partial", {"state_lock_write_permissions": "unknown"}, "Read-only evidence only")) as doctor:
            denied = CliRunner().invoke(main, args)
            self.assertNotEqual(denied.exit_code, 0)
            doctor.assert_not_called()
            partial = CliRunner().invoke(main, [*args, "--acknowledge-reads"])
        self.assertEqual(partial.exit_code, 2, partial.output)
        self.assertEqual(json.loads(partial.output)["status"], "partial")
        doctor.assert_called_once()
        self.assertTrue(doctor.call_args.kwargs["acknowledge_reads"])

    def test_bootstrap_plan_and_apply_are_separate_explicit_intents(self):
        from src.python.state_backend_command import main
        self.path.write_text(json.dumps({"backend": "s3", "namespace": "studio-dev", "destination": {
            "bucket": "example-state-bucket", "region": "us-east-1",
            "owner_account_id": "123456789012", "key_prefix": "isaacautomator/v2"}}))
        args = ["bootstrap", "--config", str(self.path), "--cloud", "aws", "--region", "us-east-1",
                "--bootstrap-state-root", str(Path(self.tmp.name) / "admin"),
                "--controller-principal", "arn:aws:iam::123456789012:role/controller", "--acknowledge-reads"]
        with mock.patch("src.python.backend_bootstrap.BootstrapSession") as factory:
            factory.return_value.runner.recovery_directory = None
            session = factory.return_value.__enter__.return_value
            plan = session.plan.return_value
            plan.digest = "a" * 64
            plan.has_changes = True
            preview = CliRunner().invoke(main, args)
            self.assertEqual(preview.exit_code, 0, preview.output)
            self.assertEqual(json.loads(preview.output)["status"], "bootstrap-planned")
            session.apply.assert_not_called()
            factory.reset_mock()
            denied = CliRunner().invoke(main, [*args, "--apply"])
            self.assertNotEqual(denied.exit_code, 0)
            factory.assert_not_called()
            applied = CliRunner().invoke(main, [*args, "--apply", "--approve-creation"])
            self.assertEqual(applied.exit_code, 0, applied.output)
            session.apply.assert_called_once_with(plan, acknowledge_creation=True)
            self.assertEqual(json.loads(applied.output.splitlines()[-1])["status"], "bootstrap-applied")

    def test_secrets_and_duplicate_fields_fail_without_echoing_input(self):
        from src.python.state_backend_command import main
        for text in [
            "backend: local\naccess_key: SYNTHETIC-NOT-A-SECRET\n",
            "backend: local\nbackend: s3\n",
            "terraform_state:\n  backend: local\nextra: {}\n",
        ]:
            with self.subTest(text=text):
                self.path.write_text(text)
                result = CliRunner().invoke(main, ["validate", "--config", str(self.path), "--cloud", "aws"])
                self.assertNotEqual(result.exit_code, 0)
                self.assertNotIn("SYNTHETIC-NOT-A-SECRET", result.output)

    def test_missing_inputs_fail_noninteractively(self):
        from src.python.state_backend_command import main
        result = CliRunner().invoke(main, ["validate"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Missing option", result.output)

    def test_entrypoint_dispatches_inside_container_without_docker(self):
        wrapper = Path(__file__).resolve().parents[2] / "state-backend"
        self.assertTrue(wrapper.is_file())
        with mock.patch("os.path.exists", return_value=True), \
                mock.patch("src.python.state_backend_command.main") as command, \
                mock.patch("subprocess.run") as docker:
            runpy.run_path(str(wrapper), run_name="__main__")
        command.assert_called_once_with()
        docker.assert_not_called()

    def test_host_entrypoint_preserves_failure_and_quotes_arguments(self):
        wrapper = Path(__file__).resolve().parents[2] / "state-backend"
        self.assertTrue(wrapper.is_file())
        args = ["validate", "--config", "directory with spaces/backend.yaml", "--cloud", "aws"]
        with mock.patch("os.path.exists", return_value=False), \
                mock.patch.object(sys, "argv", [str(wrapper), *args]), \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 7)) as docker:
            with self.assertRaises(SystemExit) as exit_result:
                runpy.run_path(str(wrapper), run_name="__main__")
        self.assertEqual(exit_result.exception.code, 7)
        command = docker.call_args.args[0]
        self.assertEqual(command[0], str(wrapper.parent / "run"))
        self.assertEqual(shlex.split(command[1]), ["./state-backend", *args])
        self.assertFalse(docker.call_args.kwargs.get("shell", False))

    def test_host_bootstrap_maps_admin_root_to_explicit_durable_bind(self):
        wrapper = Path(__file__).resolve().parents[2] / "state-backend"
        admin = Path(self.tmp.name) / "external admin"
        admin.mkdir(mode=0o700)
        for option in (["--bootstrap-state-root", str(admin)], ["--bootstrap-state-root=" + str(admin)]):
            args = ["bootstrap", *option, "--cloud", "aws"]
            with mock.patch("os.path.exists", return_value=False), \
                    mock.patch.object(sys, "argv", [str(wrapper), *args]), \
                    mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as docker:
                with self.assertRaises(SystemExit):
                    runpy.run_path(str(wrapper), run_name="__main__")
            command = shlex.split(docker.call_args.args[0][1])
            self.assertIn("/run/isaac-bootstrap-state", command)
            self.assertNotIn(str(admin), command)
            self.assertEqual(docker.call_args.kwargs["env"]["ISAAC_BOOTSTRAP_STATE_ROOT"], str(admin))

    def test_bash_completion_offers_validation_and_cloud_choices(self):
        completion = Path(__file__).resolve().parents[2] / ".completions"
        for words, index, expected in [
            ("./state-backend v", 1, {"validate"}),
            ("./state-backend validate --cloud a", 3, {"aws", "azure", "alicloud"}),
            ("./state-backend b", 1, {"bootstrap"}),
            ("./state-backend bootstrap --cloud a", 3, {"aws", "azure"}),
            ("./state-backend doctor --ack", 2, {"--acknowledge-reads"}),
            ("./state-backend propose --owner", 2, {"--owner-scope"}),
        ]:
            script = (
                'source "$1"; COMP_WORDS=(' + words + '); COMP_CWORD=' + str(index) + '; '
                '_isaac_state_backend_complete; printf "%s\\n" "${COMPREPLY[@]}"'
            )
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", script, "completion-test", str(completion)],
                cwd=self.tmp.name, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(set(result.stdout.split()), expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
