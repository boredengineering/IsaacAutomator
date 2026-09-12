#!/usr/bin/env python3
"""Offline profile CLI tests: synthetic inputs only, no deployment commands."""
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]

class WorkstationProfileCommandTests(unittest.TestCase):
    def command(self):
        name = "src.python.workstation_profile_command"
        self.assertIsNotNone(importlib.util.find_spec(name), "offline profile CLI is missing")
        return importlib.import_module(name).main

    def test_help_is_offline_and_explains_non_deployment_scope(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), \
                mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = CliRunner().invoke(self.command(), ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("list", result.output)
        self.assertIn("validate", result.output)
        self.assertIn("resolve", result.output)
        self.assertIn("does not deploy", result.output)

    def test_list_only_shows_public_presets_without_side_effects(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), \
                mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = CliRunner().invoke(self.command(), ["list", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output), ["default", "full", "minimal"])

    def test_top_level_help_does_not_need_docker_or_cloud_tools(self):
        script = ROOT / "workstation-profile"
        self.assertTrue(script.is_file(), "offline entrypoint is missing")
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--help"],
            env={"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
            cwd="/tmp", capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("does not deploy", result.stdout)

    def test_validate_marks_runtime_and_cloud_as_unverified(self):
        result = CliRunner().invoke(self.command(), ["validate", "minimal"])
        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertEqual(report["status"], "valid-profile")
        self.assertEqual(report["cloud_access"], "not_checked")
        self.assertEqual(report["runtime"], "not_verified")
        self.assertEqual(report["deployment"], "not_performed")

    def test_missing_dependencies_have_actionable_error_without_traceback(self):
        result = subprocess.run(
            [sys.executable, "-S", "-B", str(ROOT / "workstation-profile"), "list"],
            env={"PATH": "/nonexistent"}, cwd="/tmp",
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Click and PyYAML", result.stderr)

    def test_resolve_emits_real_manifest_with_no_readiness_claim(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), \
                mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = CliRunner().invoke(self.command(), ["resolve", "minimal"])
        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertEqual(report["kind"], "workstation-resolved")
        self.assertFalse(report["ready_for_apply"])
        self.assertEqual(report["profile"]["components"]["sim"]["source"]["version"], "6.0.1")
        self.assertFalse(report["profile"]["components"]["arena"]["enabled"])
        self.assertTrue(report["unresolved"])

    def test_invalid_file_is_nonzero_without_echoing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "invalid.yaml"
            profile.write_text("kind: workstation-profile\nsecret: [SYNTHETIC-CANARY\n")
            for command in ("validate", "resolve"):
                with self.subTest(command=command):
                    result = CliRunner().invoke(self.command(), [command, str(profile)])
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertIn("Error:", result.output)
                    self.assertNotIn("SYNTHETIC-CANARY", result.output)
                    self.assertNotIn(directory, result.output)

    def test_missing_profile_does_not_fall_back(self):
        result = CliRunner().invoke(self.command(), ["resolve", "not-a-profile"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Error:", result.output)

    def test_explicit_disable_overrides_default_preset(self):
        result = CliRunner().invoke(self.command(), ["resolve", "default", "--disable", "arena"])
        self.assertEqual(result.exit_code, 0, result.output)
        manifest = json.loads(result.output)
        self.assertFalse(manifest["profile"]["components"]["arena"]["enabled"])

    def test_enable_and_conflicting_flags(self):
        result = CliRunner().invoke(self.command(), ["resolve", "minimal", "--enable", "arena"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(json.loads(result.output)["profile"]["components"]["arena"]["enabled"])
        result = CliRunner().invoke(self.command(), ["resolve", "minimal", "--enable", "arena", "--disable", "arena"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("both", result.output)

    def test_invalid_dependency_override_and_unknown_component_are_rejected(self):
        for args in (["resolve", "default", "--disable", "lab"],
                     ["resolve", "default", "--disable", "not-a-component"]):
            with self.subTest(args=args):
                result = CliRunner().invoke(self.command(), args)
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("Error:", result.output)

    def test_explicit_profile_path_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "custom profile.yaml"
            text = "schema_version: v1alpha1\nkind: workstation-profile\nname: custom\nextends: minimal\n"
            profile.write_text(text)
            result = CliRunner().invoke(self.command(), ["resolve", str(profile), "--enable", "arena"])
            self.assertEqual(result.exit_code, 0, result.output)
            manifest = json.loads(result.output)
            self.assertEqual(manifest["profile"]["name"], "custom")
            self.assertTrue(manifest["profile"]["components"]["arena"]["enabled"])
            self.assertNotIn(directory, result.output)
            self.assertEqual(profile.read_text(), text)
            self.assertEqual(list(Path(directory).iterdir()), [profile])


if __name__ == "__main__":
    unittest.main()
