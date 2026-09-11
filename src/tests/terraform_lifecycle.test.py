#!/usr/bin/env python3
"""Destroy regressions using synthetic state and no cloud/process execution."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import click
from click.testing import CliRunner

from src.python.config import c


class TestDestroySafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.deployment = self.root / "demo"
        self.deployment.mkdir()
        self.marker = self.deployment / "recovery.txt"
        self.marker.write_text("synthetic recovery receipt")
        self.config_patch = mock.patch.dict(
            c, state_dir=str(self.root), app_dir=str(self.root),
            terraform_dir=str(self.root / "terraform"),
        )
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        loader = importlib.machinery.SourceFileLoader(
            "destroy_under_test", str(Path(__file__).resolve().parents[2] / "destroy")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        self.command = importlib.util.module_from_spec(spec)
        with mock.patch("src.python.utils.deployments", return_value=["demo"]):
            loader.exec_module(self.command)
        self.shell = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
        self.command.__dict__.update(
            aws_validate_credentials=mock.Mock(),
            azure_login=mock.Mock(), gcp_login=mock.Mock(),
            read_meta=mock.Mock(return_value={"input_params": {}}),
        )
        self.runner = mock.Mock()
        self.runner.assert_no_recovery = mock.Mock(return_value=None)
        self.operation = mock.MagicMock()
        self.operation.__enter__.return_value = self.runner
        self.operation.recovery_directory = None
        self.factory = mock.Mock(return_value=self.operation)
        self.command.TerraformRunner = self.factory

        # Reuse the synthetic Terraform state-transition fixtures below, without
        # executing a shell, Terraform, or providers. The CLI must call the runner.
        def operation_result(name):
            result = self.shell(command="terraform " + name)
            if result.returncode:
                from src.python.terraform_runner import TerraformRunnerError
                raise TerraformRunnerError("Synthetic operation failed")
        self.runner.init.side_effect = lambda: operation_result("init")
        self.runner.apply.side_effect = lambda *args, **kwargs: operation_result("destroy")
        def plan_result(**kwargs):
            operation_result("plan -destroy")
            return self.runner.plan.return_value
        self.runner.plan.side_effect = plan_result

    def test_host_entrypoint_quotes_arguments_and_propagates_status(self):
        import os
        import runpy
        import shlex
        import sys

        script = Path(__file__).resolve().parents[2] / "destroy"
        arguments = ["demo with spaces", "--yes", "literal'quote", "$(touch NEVER)"]
        real_exists = os.path.exists
        for code in (0, 23):
            with self.subTest(code=code), \
                    mock.patch("src.python.utils.deployments", return_value=["demo"]), \
                    mock.patch.object(os.path, "exists", side_effect=lambda path:
                                      False if path == "/.dockerenv" else real_exists(path)), \
                    mock.patch.object(sys, "argv", [str(script), *arguments]), \
                    mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], code)) as execute, \
                    mock.patch("subprocess.Popen", side_effect=AssertionError("No Docker or real processes")):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(str(script), run_name="__main__")
                self.assertEqual(raised.exception.code, code)
                execute.assert_called_once()
                argv = execute.call_args.args[0]
                self.assertEqual(argv[0], str(script.with_name("run")))
                self.assertEqual(len(argv), 2)
                self.assertEqual(shlex.split(argv[1]), ["./destroy", *arguments])
                self.assertIs(execute.call_args.kwargs["shell"], False)
                self.assertIs(execute.call_args.kwargs["check"], False)

    def test_destroy_uses_one_isolated_saved_plan(self):
        self.write_state()
        self.shell.side_effect = self.finish_destroy
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.factory.assert_called_once()
        options = self.factory.call_args.kwargs
        self.assertEqual(options["source_root"], self.root / "terraform/aws")
        self.assertEqual(options["source_files"], self.command.workstation_source_files("aws"))
        self.assertEqual(options["variables_file"], self.deployment / ".tfvars")
        self.assertEqual(options["state_root"], self.root)
        self.assertEqual(options["deployment_name"], "demo")
        self.assertEqual(options["backend_spec"].backend, "local")
        self.assertIsNone(options["target_scope"])
        self.runner.init.assert_called_once_with()
        self.runner.plan.assert_called_once_with(destroy=True)
        self.runner.apply.assert_called_once_with(self.runner.plan.return_value, acknowledge_mutation=True)
        self.runner.assert_no_recovery.assert_called_once_with()
        self.operation.__exit__.assert_called_once()

    def test_successful_apply_with_possible_recovery_preserves_deployment(self):
        import os
        import shutil
        from src.python.terraform_runner import TerraformRunner

        source = self.root / "terraform/aws"
        source.mkdir(parents=True)
        (source / "main.tf").write_text('# Synthetic source; Terraform is never executed.\n')
        (self.deployment / ".tfvars").write_text('# Synthetic inputs\n')
        for kind in ("present", "unknown"):
            with self.subTest(kind=kind):
                self.deployment.mkdir(exist_ok=True)
                self.marker.write_text("synthetic recovery receipt")
                (self.deployment / ".tfvars").write_text('# Synthetic inputs\n')
                self.write_state()
                created = []

                def construct(**options):
                    run = TerraformRunner(**options, lock_root=self.root / "locks", environment={})
                    created.append(run)
                    run.init = mock.Mock()
                    run.plan = mock.Mock()

                    def apply(*args, **kwargs):
                        self.addCleanup(shutil.rmtree, run.staged_root.parent, ignore_errors=True)
                        self.finish_destroy(command="terraform destroy")
                        if kind == "present":
                            (run.staged_root / "errored.tfstate").write_bytes(b"SYNTHETIC-RECOVERY")

                    run.apply = mock.Mock(side_effect=apply)
                    return run

                real_stat = os.stat
                def inspect(path, *args, **kwargs):
                    if kind == "unknown" and path == "errored.tfstate":
                        raise PermissionError("SYNTHETIC-PRIVATE")
                    return real_stat(path, *args, **kwargs)

                self.factory.side_effect = construct
                with mock.patch.object(self.command, "workstation_source_files", return_value=["main.tf"]), \
                        mock.patch("src.python.terraform_runner.os.stat", side_effect=inspect), \
                        mock.patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                    result = self.invoke()
                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertTrue(self.marker.exists(), "deployment was deleted before recovery check")
                self.assertNotIn('Deployment "demo" destroyed', result.output)
                self.assertNotIn("SYNTHETIC-PRIVATE", result.output)
                run = created[0]
                self.assertTrue(run.recovery_directory.is_dir())
                if kind == "present":
                    self.assertEqual(run.recovery_state.read_bytes(), b"SYNTHETIC-RECOVERY")
                spawn.assert_not_called()

    def test_cleanup_finishes_before_controller_lock_is_released(self):
        self.write_state()
        self.shell.side_effect = self.finish_destroy
        def after_unlock(*args):
            self.runner.assert_no_recovery.assert_called_once_with()
            self.assertFalse(self.deployment.exists(), "cleanup must remain inside the locked context")
            self.deployment.mkdir()
            (self.deployment / "new-owner.txt").write_text("next deployment after lock release")
            return False
        self.operation.__exit__.side_effect = after_unlock
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.deployment / "new-owner.txt").exists())

    def invoke(self, *args):
        return CliRunner().invoke(self.command.main, ["demo", "--yes", *args])

    def write_state(self):
        state = {
            "version": 4, "serial": 1, "lineage": "synthetic-lineage",
            "outputs": {}, "resources": [{
                "mode": "managed", "type": "aws_instance", "name": "fixture",
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [{"attributes": {"id": "synthetic-instance"}}],
            }],
        }
        (self.deployment / ".tfstate").write_text(json.dumps(state))

    def test_remote_only_state_is_not_destroyed_or_forgotten(self):
        (self.deployment / "backend.json").write_text(
            json.dumps({"schema_version": 1, "backend": "gcs"})
        )
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())
        self.assertNotIn('Deployment "demo" destroyed', result.output)
        self.shell.assert_not_called()

    def test_malformed_or_ambiguous_state_is_preserved(self):
        for text in ["", "{}", "[]", "null", "not-json", '{"version":4,"resources":[]}']:
            with self.subTest(text=text):
                self.deployment.mkdir(exist_ok=True)
                self.marker.write_text("synthetic recovery receipt")
                (self.deployment / ".tfstate").write_text(text)
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.assertNotIn('Deployment "demo" destroyed', result.output)
                self.shell.assert_not_called()

    def test_remote_descriptor_cannot_use_a_stale_local_snapshot(self):
        self.write_state()
        (self.deployment / "backend.json").write_text('{"backend":"s3"}')
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())
        self.shell.assert_not_called()

    def test_failed_or_incomplete_destroy_preserves_recovery(self):
        for code in [1, 0]:
            with self.subTest(code=code):
                self.deployment.mkdir(exist_ok=True)
                self.marker.write_text("synthetic recovery receipt")
                self.write_state()
                self.shell.return_value = subprocess.CompletedProcess([], code)
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.assertNotIn('Deployment "demo" destroyed', result.output)


    def finish_destroy(self, *args, **kwargs):
        if str(kwargs.get("command", "")).startswith("terraform destroy"):
            path = self.deployment / ".tfstate"
            state = json.loads(path.read_text())
            state["resources"] = []
            state["serial"] += 1
            path.write_text(json.dumps(state))
        return subprocess.CompletedProcess([], 0)

    def test_verified_destroy_removes_only_the_synthetic_deployment(self):
        self.write_state()
        other = self.root / "other-recovery.txt"
        other.write_text("preserve")
        self.shell.side_effect = self.finish_destroy
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.deployment.exists())
        self.assertTrue(other.exists())
        self.assertIn('Deployment "demo" destroyed', result.output)

    def test_changed_lineage_is_not_a_verified_destroy(self):
        self.write_state()

        def changed_state(*args, **kwargs):
            result = self.finish_destroy(*args, **kwargs)
            if str(kwargs.get("command", "")).startswith("terraform destroy"):
                path = self.deployment / ".tfstate"
                state = json.loads(path.read_text())
                state["lineage"] = "different-owner"
                path.write_text(json.dumps(state))
            return result

        self.shell.side_effect = changed_state
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())

    def test_malformed_post_destroy_resources_preserve_recovery(self):
        for resource in (
            {}, {"mode": "unknown", "instances": []}, {"mode": "managed"},
            {"mode": "managed", "instances": None},
            {"mode": "managed", "instances": {}},
            {"mode": "data", "instances": [None]},
        ):
            with self.subTest(resource=resource):
                self.deployment.mkdir(exist_ok=True)
                self.marker.write_text("synthetic recovery receipt")
                self.write_state()

                def malformed_state(*args, **kwargs):
                    result = self.finish_destroy(*args, **kwargs)
                    if str(kwargs.get("command", "")).startswith("terraform destroy"):
                        path = self.deployment / ".tfstate"
                        state = json.loads(path.read_text())
                        state["resources"] = [resource]
                        path.write_text(json.dumps(state))
                    return result

                self.shell.side_effect = malformed_state
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.assertIn("malformed", result.output)
                self.assertNotIn('Deployment "demo" destroyed', result.output)

    def test_valid_data_resources_do_not_prevent_verified_destroy(self):
        self.write_state()

        def data_only_state(*args, **kwargs):
            result = self.finish_destroy(*args, **kwargs)
            if str(kwargs.get("command", "")).startswith("terraform destroy"):
                path = self.deployment / ".tfstate"
                state = json.loads(path.read_text())
                state["resources"] = [{"mode": "data", "instances": [{"attributes": {}}]}]
                path.write_text(json.dumps(state))
            return result

        self.shell.side_effect = data_only_state
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.deployment.exists())

    def test_unreadable_state_preserves_files_without_authentication(self):
        self.write_state()
        with mock.patch("src.python.utils.Path.read_text", side_effect=PermissionError("synthetic")):
            result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())
        self.shell.assert_not_called()

    def test_state_identity_is_required_before_any_authentication_or_mutation(self):
        for field, value in (
            ("lineage", None), ("lineage", ""), ("lineage", "   "),
            ("lineage", 123), ("lineage", {"synthetic-private-value": True}),
            ("serial", None), ("serial", -1), ("serial", True),
            ("serial", "1"), ("serial", 1.0),
        ):
            for dryrun in (False, True):
                with self.subTest(field=field, value=value, dryrun=dryrun):
                    self.write_state()
                    path = self.deployment / ".tfstate"
                    state = json.loads(path.read_text())
                    if value is None:
                        del state[field]
                    else:
                        state[field] = value
                    path.write_text(json.dumps(state))
                    result = self.invoke(*(["--dryrun"] if dryrun else []))
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertTrue(self.marker.exists())
                    self.assertNotIn("synthetic-private-value", result.output)
                    self.shell.assert_not_called()
                    self.command.aws_validate_credentials.assert_not_called()

    def test_invalid_or_regressed_post_destroy_identity_preserves_recovery(self):
        for field, value in (
            ("lineage", None), ("lineage", ""), ("lineage", 123),
            ("serial", None), ("serial", -1), ("serial", True),
            ("serial", "2"), ("serial", 2.0), ("serial", 0),
        ):
            with self.subTest(field=field, value=value):
                self.write_state()

                def invalid_identity(*args, **kwargs):
                    result = self.finish_destroy(*args, **kwargs)
                    if str(kwargs.get("command", "")).startswith("terraform destroy"):
                        path = self.deployment / ".tfstate"
                        state = json.loads(path.read_text())
                        if value is None:
                            del state[field]
                        else:
                            state[field] = value
                        path.write_text(json.dumps(state))
                    return result

                self.shell.side_effect = invalid_identity
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.assertNotIn('Deployment "demo" destroyed', result.output)

    def test_symlinked_state_is_refused(self):
        self.write_state()
        original = self.deployment / ".tfstate"
        outside = self.root / "other-state.json"
        original.rename(outside)
        original.symlink_to(outside)
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())
        self.shell.assert_not_called()

    def test_symlinked_configured_root_is_refused_before_authentication(self):
        self.write_state()
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for state_dir in (alias, alias / ".." / self.root.name):
            with self.subTest(state_dir=state_dir), mock.patch.dict(c, state_dir=str(state_dir)):
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.shell.assert_not_called()
                self.command.aws_validate_credentials.assert_not_called()

    def test_destroy_callback_refuses_name_traversal(self):
        self.write_state()
        approved = self.root / "approved"
        approved.mkdir()
        with mock.patch.dict(c, state_dir=str(approved)):
            with self.assertRaises(click.ClickException):
                self.command.main.callback(
                    yes=True, debug=False, dryrun=False, deployment_name="../demo",
                )
        self.assertTrue(self.marker.exists())
        self.shell.assert_not_called()
        self.command.aws_validate_credentials.assert_not_called()

    def test_failed_destroy_command_preserves_files(self):
        for codes in ([0, 1], [0, 0, 1]):
            with self.subTest(codes=codes):
                self.write_state()
                self.shell.reset_mock()
                self.runner.apply.reset_mock()
                self.shell.side_effect = [subprocess.CompletedProcess([], code) for code in codes]
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.assertEqual(self.shell.call_count, len(codes))
                if len(codes) == 3:
                    self.runner.apply.assert_called_once_with(
                        self.runner.plan.return_value, acknowledge_mutation=True)
                else:
                    self.runner.apply.assert_not_called()
                self.runner.assert_no_recovery.assert_not_called()
                self.assertNotIn('Deployment "demo" destroyed', result.output)

    def test_lock_entry_rechecks_state_and_backend_intent_before_init(self):
        for change in ("state", "backend"):
            with self.subTest(change=change):
                self.write_state()

                def changed_after_lock():
                    if change == "state":
                        path = self.deployment / ".tfstate"
                        state = json.loads(path.read_text())
                        state["serial"] += 1
                        path.write_text(json.dumps(state))
                    else:
                        (self.deployment / "backend.json").write_text('{"backend":"s3"}')
                    return self.runner

                self.operation.__enter__.side_effect = changed_after_lock
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertTrue(self.marker.exists())
                self.shell.assert_not_called()

    def test_successful_dryrun_preserves_files_without_apply_or_cleanup(self):
        self.write_state()
        original = (self.deployment / ".tfstate").read_bytes()
        result = self.invoke("--dryrun")
        self.assertEqual(result.exit_code, 0, result.output)
        self.runner.init.assert_called_once_with()
        self.runner.plan.assert_called_once_with(destroy=True)
        self.runner.apply.assert_not_called()
        self.runner.assert_no_recovery.assert_not_called()
        self.assertTrue(self.marker.exists())
        self.assertEqual((self.deployment / ".tfstate").read_bytes(), original)
        self.assertNotIn('Deployment "demo" destroyed', result.output)

    def test_dangling_metadata_symlink_prevents_destroy(self):
        self.write_state()
        (self.deployment / "meta.json").symlink_to(self.root / "missing-metadata")
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())
        self.shell.assert_not_called()
        self.command.aws_validate_credentials.assert_not_called()

    def test_dryrun_plan_error_is_not_success(self):
        self.write_state()
        self.shell.side_effect = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)]
        result = self.invoke("--dryrun")
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
