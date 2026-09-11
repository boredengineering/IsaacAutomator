#!/usr/bin/env python3
"""Public offline drift-automation CLI contracts; no cloud or GitHub writes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import runpy
import shlex
import subprocess
import sys
from unittest import mock
from click.testing import CliRunner


class DriftCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "workflow.json"
        self.config.write_text(json.dumps({
            "schema_version": 1, "repository": "example/infrastructure", "protected_branch": "main",
            "source_revision": "a" * 40, "provider": "aws",
            "identity": {"role_arn": "arn:aws:iam::123456789012:role/drift-detect", "region": "us-east-1"},
            "config_path": "configs/drift/production.yaml", "deployments": ["gpu-a"],
            "backend_identity": "studio/production/workstations", "namespace": "studio",
            "scopes": ["workstation_infrastructure"],
            "runtime_image": "ghcr.io/example/automator@sha256:" + "b" * 64,
            "terraform_version": "1.10.5",
        }))

    def test_public_entrypoint_routes_container_and_host_without_activation(self):
        wrapper = Path(__file__).resolve().parents[2] / "drift"
        self.assertTrue(wrapper.is_file(), "executable drift entrypoint missing")
        with mock.patch("os.path.exists", return_value=True), mock.patch("src.python.drift_command.main") as main:
            runpy.run_path(str(wrapper), run_name="__main__")
        main.assert_called_once_with()
        args = ["workflow", "preview", "--config", "configs/with spaces/workflow.yaml"]
        with mock.patch("os.path.exists", return_value=False), \
                mock.patch.object(sys, "argv", [str(wrapper), *args]), \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 3)) as docker:
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(wrapper), run_name="__main__")
        self.assertEqual(result.exception.code, 3)
        self.assertEqual(shlex.split(docker.call_args.args[0][1]), ["./drift", *args])
        self.assertFalse(docker.call_args.kwargs.get("shell", False))

    def test_preview_does_not_write_workflows(self):
        from src.python.drift_command import main
        result = CliRunner().invoke(main, ["workflow", "preview", "--config", str(self.config)])
        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertIn("drift-check.yml", report["files"])
        self.assertEqual(list(self.root.iterdir()), [self.config])

    def test_generate_creates_only_requested_inert_output(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.drift_command"), "public drift CLI missing")
        from src.python.drift_command import main
        output = self.root / "generated"
        result = CliRunner().invoke(main, ["workflow", "generate", "--config", str(self.config),
                                          "--output-dir", str(output)])
        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertEqual(report["status"], "generated-inactive")
        self.assertTrue((output / "drift-check.yml").is_file())
        self.assertFalse((self.root / ".github").exists())
        self.assertFalse(report["remote_activation"])
        self.assertEqual(report["files"], sorted(str(path) for path in output.iterdir()))

    def runtime_config(self):
        return dict(schema_version=1, deployment='fixture', cloud='aws',
            backend_config={'backend': 'local'}, target_scope=None,
            state_root=str(self.root / 'state'), local_state_path=str(self.root / 'state/fixture/.tfstate'),
            baseline_store=str(self.root / 'baselines'), baseline_ref=None,
            expected_lineage='00000000-0000-0000-0000-000000000001', expected_serial=1,
            scope='workstation_infrastructure', drift={'enabled': True, 'scopes': ['workstation_infrastructure']})

    def test_check_missing_baseline_outputs_public_json_and_wrapper_exit_three(self):
        from src.python.drift_command import main
        self.config.write_text(json.dumps(self.runtime_config()))
        result = CliRunner().invoke(main, ['check', '--config', str(self.config)])
        self.assertEqual(result.exit_code, 3, result.output)
        self.assertEqual(json.loads(result.output)['classes'], ['partial'])
        self.assertEqual(list(self.root.iterdir()), [self.config])

    def test_generated_workflow_selectors_are_assertions_not_config_overrides(self):
        from src.python.drift_command import main
        self.config.write_text(json.dumps(self.runtime_config()))
        approved = self.root / 'approved-reports'
        args = ['check', 'fixture', '--config', str(self.config), '--scope', 'workstation_infrastructure',
                '--format', 'json', '--report-dir', str(approved)]
        result = CliRunner().invoke(main, args)
        self.assertEqual(result.exit_code, 3, result.output)
        self.assertEqual(json.loads(result.output)['classes'], ['partial'])
        self.assertEqual(len(list(approved.glob('report-*.json'))), 1)
        args[1] = 'unapproved'
        denied = CliRunner().invoke(main, args)
        self.assertEqual(denied.exit_code, 1, denied.output)
        self.assertEqual(json.loads(denied.output)['classes'], ['error'])

    def test_malformed_configuration_is_sanitized_before_any_terraform_call(self):
        from src.python.drift_command import main
        malformed = ['password: PRIVATE_CANARY', 'schema_version: 1\nschema_version: 1',
                     'x: &a {secret: PRIVATE_CANARY}\ny: *a', '{broken PRIVATE_CANARY',
                     json.dumps({**self.runtime_config(), 'ready': True})]
        with mock.patch('src.python.terraform_runner.TerraformRunner.init') as init:
            for text in malformed:
                self.config.write_text(text)
                result = CliRunner().invoke(main, ['check', '--config', str(self.config)])
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertEqual(json.loads(result.output)['classes'], ['error'])
                self.assertNotIn('PRIVATE_CANARY', result.output)
                self.assertNotIn(str(self.config), result.output)
        init.assert_not_called()

    def test_denied_history_write_is_public_error_not_a_clean_or_partial_success(self):
        from src.python.drift_command import main
        approved = self.root / 'approved-reports'
        approved.mkdir(mode=0o700)
        (approved / 'history').mkdir(mode=0o755)
        self.config.write_text(json.dumps({**self.runtime_config(), 'report_root': str(approved)}))
        result = CliRunner().invoke(main, ['check', '--config', str(self.config)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(json.loads(result.output)['classes'], ['error'])
        self.assertNotIn(str(approved), result.output)
        self.assertEqual(list(approved.glob('report-*.json')), [])


if __name__ == "__main__":
    unittest.main()
