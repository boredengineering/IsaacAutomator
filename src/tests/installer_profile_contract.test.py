#!/usr/bin/env python3
"""Offline contracts: source only detect/config; never run the installer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "isaac-installer"
DUMP_ENV = (
    'import json, os; print(json.dumps({k: v for k, v in os.environ.items() '
    'if k.startswith(("CFG_", "WORKSPACE_", "ISAAC", "ARENA_", "LEROBOT_", "GR00T_")) '
    'or k in ("PROFILE_NAME", "CONFIG_FILE")}))'
)


class InstallerProfileContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def profile(self, text, name="profile.yaml"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_loader(self, *profiles, script_dir=INSTALLER, before="", after=""):
        # Paths and profile contents are argv/data, never embedded shell source.
        script = (
            'set -euo pipefail; SCRIPT_DIR="$1"; '
            'source "$2/lib/core/detect.sh"; source "$2/lib/core/config.sh"; '
            'python_executable="$3"; shift 3; '
            + before
            + '; for profile in "$@"; do load_config_profile "$profile"; done; '
            + after
            + '; "$python_executable" -c ' + "'" + DUMP_ENV + "'"
        )
        # Empty fragments must not produce adjacent shell semicolons.
        script = script.replace('; ;', ';')
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
        env.update(HOME=str(self.root), USER="profile-test", SUDO_USER="")
        return subprocess.run(
            ["bash", "-c", script, "profile-contract", str(script_dir),
             str(INSTALLER), sys.executable, *(str(p) for p in profiles)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=10,
        )

    def loaded(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_existing_relative_option_like_path_loads_literally(self):
        self.profile('profile_name: option-path\n', "-n")
        env = self.loaded(self.run_loader("-n"))
        self.assertEqual(env["PROFILE_NAME"], "option-path")

    def test_profile_paths_are_data_not_python_or_shell_source(self):
        names = (
            "spaces and 'quotes' $(touch path-canary).yaml",
            "x' + str(__import__('os').system('touch python-path-canary')) + '.yaml",
            "line\nbreak.yaml",
        )
        for name in names:
            with self.subTest(name=name):
                path = self.profile('profile_name: safe-path\n', name)
                env = self.loaded(self.run_loader(path))
                self.assertEqual(env["PROFILE_NAME"], "safe-path")
                self.assertFalse((self.root / "path-canary").exists())
                self.assertFalse((self.root / "python-path-canary").exists())

    def test_trailing_newline_path_never_loads_alternate_file(self):
        self.profile('profile_name: wrong-file\n', "same.yaml")
        for suffix in ("\n", "\n\n"):
            with self.subTest(suffix=suffix):
                path = self.profile('profile_name: exact-file\n', "same.yaml" + suffix)
                env = self.loaded(self.run_loader(path, after='export CONFIG_FILE'))
                self.assertEqual(env["PROFILE_NAME"], "exact-file")
                self.assertEqual(env["CONFIG_FILE"], str(path))

    def test_strings_booleans_numbers_and_cli_overrides_are_preserved(self):
        path = self.profile(
            'profile_name: typed\nworkspace: {root: "~/space here", auto_create_fork: false}\n'
            'enabled: true\ndisabled: false\nliteral: "false"\nempty: ""\n'
            'integer: 5556\nratio: 1.25\nquoted: "00123"\n'
        )
        env = self.loaded(self.run_loader(path, before='export ISAACLAB_REPO="cli/repo"'))
        for key, value in dict(ENABLED="true", DISABLED="false", LITERAL="false", EMPTY="",
                               INTEGER="5556", RATIO="1.25", QUOTED="00123").items():
            self.assertEqual(env["CFG_" + key], value)
        self.assertEqual(env["WORKSPACE_DIR"], str(self.root / "space here"))
        self.assertEqual(env["WORKSPACE_AUTO_CREATE_FORK"], "false")
        self.assertEqual(env["ISAACLAB_REPO"], "cli/repo")

    def test_public_presets_and_aliases_preserve_all_flattened_values(self):
        presets = {
            "default-profile": ("default", "standard", "workstation"),
            "minimal-headless": ("minimal", "headless", "ci"),
            "full-ecosystem": ("full", "ecosystem", "all"),
            "example-profile": ("example",),
        }

        def expected_variables(data, prefix="CFG_"):
            expected = {}
            for key, value in data.items():
                name = prefix + key.upper()
                if isinstance(value, dict):
                    expected.update(expected_variables(value, name + "_"))
                else:
                    expected[name] = str(value).lower() if isinstance(value, bool) else str(value)
            return expected

        for name, aliases in presets.items():
            path = INSTALLER / "config" / (name + ".yaml")
            data = yaml.safe_load(path.read_text())
            expected = expected_variables(data)
            for request in (path, name, *aliases):
                with self.subTest(request=request):
                    env = self.loaded(self.run_loader(request))
                    self.assertEqual({k: v for k, v in env.items() if k.startswith("CFG_")}, expected)
                    self.assertEqual(env["PROFILE_NAME"], data["profile_name"])
                    self.assertEqual(env["ISAACLAB_REPO"], data["repositories"]["isaaclab"]["repo"])
                    self.assertEqual(env["WORKSPACE_DIR"], data["workspace"]["root"].replace("~", str(self.root), 1))
        implicit = self.loaded(self.run_loader(before='load_config_profile'))
        self.assertEqual(implicit["PROFILE_NAME"], "default-workstation")

    def test_missing_pyyaml_has_actionable_error_not_fallback(self):
        path = self.profile('profile_name: dependency-test\n')
        # Real Python with site packages disabled, not a fake parser response.
        result = self.run_loader(path, before='python3() { command python3 -S "$@"; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PyYAML is required", result.stderr)
        self.assertIn("python3 -m pip install PyYAML", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_successful_reload_replaces_cfg_namespace(self):
        first = self.profile('profile_name: first\ndevtools: {discord: true}\n', "first.yaml")
        second = self.profile('profile_name: second\nworkspace: {layout: flat}\n', "second.yaml")
        env = self.loaded(self.run_loader(first, second, before='export CFG_STALE=old'))
        self.assertEqual(env["PROFILE_NAME"], "second")
        self.assertEqual(env["CFG_WORKSPACE_LAYOUT"], "flat")
        self.assertNotIn("CFG_DEVTOOLS_DISCORD", env)
        self.assertNotIn("CFG_STALE", env)

    def test_rejected_load_keeps_previous_configuration(self):
        first = self.profile('profile_name: first\ndevtools: {discord: false}\n', "first.yaml")
        self.profile('profile_name: poisoned\ndescription: "bad\\0value"\n', "bad.yaml")
        for rejected in ("bad.yaml", "unknown-profile"):
            with self.subTest(rejected=rejected):
                # Both names are fixed test literals, not profile-controlled source.
                after = f'if load_config_profile {rejected}; then exit 99; fi; export CONFIG_FILE'
                env = self.loaded(self.run_loader(first, after=after))
                self.assertEqual(env["CFG_PROFILE_NAME"], "first")
                self.assertEqual(env["PROFILE_NAME"], "first")
                self.assertEqual(env["CFG_DEVTOOLS_DISCORD"], "false")
                self.assertEqual(env["CONFIG_FILE"], str(first))
                self.assertNotIn("CFG_DESCRIPTION", env)

    def test_malformed_or_unrepresentable_documents_fail_closed(self):
        documents = (
            'profile_name: broken\nworkspace: [unterminated\n',
            'kind: workstation-baseline\nworkspace: [unterminated\n',
            'profile_name: first\n---\nprofile_name: second\n',
            '', '{}', 'null', 'just a string', '- profile_name: list\n',
            'description: [one, two]\n', 'description: null\n',
            'description: "before\\0after"\n', 'loop: &loop {again: *loop}\n',
            'description: !!python/object/apply:os.system ["touch yaml-canary"]\n',
        )
        for document in documents:
            with self.subTest(document=document):
                result = self.run_loader(self.profile(document))
                self.assertNotEqual(result.returncode, 0, "invalid YAML must not become defaults")
                self.assertIn("invalid installer profile", result.stderr.lower())
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((self.root / "yaml-canary").exists())

    def test_yaml_diagnostics_do_not_expose_source_or_path(self):
        canary = "SYNTHETIC_PRIVATE_PROFILE_CANARY"
        for document in (f'description: "{canary}\n',
                         f'description: !{canary} value\n'):
            with self.subTest(document=document):
                result = self.run_loader(self.profile(document, canary + ".yaml"))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn(canary, result.stderr)
                self.assertNotIn(str(self.root), result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("invalid installer profile", result.stderr.lower())
                self.assertIn("yaml", result.stderr.lower())

    def test_file_error_diagnostics_do_not_expose_private_path(self):
        canary = "SYNTHETIC_PRIVATE_PATH_CANARY"
        directory = self.root / (canary + "-directory")
        directory.mkdir()
        for path in (self.root / (canary + "-missing.yaml"), directory):
            with self.subTest(path=path):
                # Exercise the parser's real OSError handling without resolver rejection.
                result = subprocess.run(
                    [sys.executable, str(INSTALLER / "lib/core/profile_parser.py"), str(path)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn(canary, result.stderr)
                self.assertNotIn(str(self.root), result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("invalid installer profile", result.stderr.lower())
                self.assertIn("read", result.stderr.lower())

    def test_nonlegacy_kinds_are_rejected(self):
        for key in ("kind", "Kind", "KIND"):
            for kind in ("workstation-baseline", "workstation-profile", "unrecognized"):
                with self.subTest(key=key, kind=kind):
                    result = self.run_loader(self.profile(f"{key}: {kind}\nprofile_name: unsupported\n"))
                    self.assertNotEqual(result.returncode, 0)
                    diagnostic = "inventory" if kind == "workstation-baseline" else "unsupported"
                    self.assertIn(diagnostic, result.stderr.lower())

    def test_invalid_or_colliding_keys_are_rejected(self):
        documents = (
            'profile_name: one\nprofile_name: two\n',
            'workspace:\n  root: one\n  root: two\n',
            'profile_name: one\nPROFILE_NAME: two\n',
            'workspace_root: one\nworkspace:\n  root: two\n',
            'bad-key: one\n', '"bad key": one\n', '42: one\n',
            '"x[$(touch key-canary)]": one\n',
            'defaults: &defaults {root: first}\nworkspace:\n  <<: *defaults\n  root: second\n',
        )
        for document in documents:
            with self.subTest(document=document):
                result = self.run_loader(self.profile(document))
                self.assertNotEqual(result.returncode, 0, "keys must not be silently rewritten/overwritten")
                self.assertIn("key", result.stderr.lower())
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((self.root / "key-canary").exists())

    def test_missing_known_alias_preset_never_selects_unrelated_profile(self):
        config = self.root / "config"
        config.mkdir()
        for alias in ("minimal", "headless", "ci", "full", "ecosystem", "all",
                      "default", "standard", "workstation"):
            with self.subTest(alias=alias):
                unrelated = config / ("user-" + alias + "-custom.yaml")
                unrelated.write_text('profile_name: wrong-file\n', encoding="utf-8")
                result = self.run_loader(alias, script_dir=self.root)
                unrelated.unlink()
                self.assertNotEqual(result.returncode, 0, "known aliases must not fall through")
                self.assertIn("preset", result.stderr.lower())
                self.assertIn("missing", result.stderr.lower())
                self.assertEqual(result.stdout, "")

    def test_unknown_or_ambiguous_profile_never_defaults(self):
        config = self.root / "config"
        config.mkdir()
        for name in ("default-profile", "shared-a", "shared-b"):
            (config / (name + ".yaml")).write_text("profile_name: fixture\n")
        for requested, diagnostic in (("missing", "unknown"), ("shared", "ambiguous"),
                                      ("", "unknown"), ("*", "unknown")):
            with self.subTest(requested=requested):
                result = self.run_loader(requested, script_dir=self.root)
                self.assertNotEqual(result.returncode, 0, "must not select a fallback")
                self.assertIn(diagnostic, result.stderr.lower())

    def test_shell_syntax_in_values_is_literal_data(self):
        value = '$(touch value-canary) `touch backtick-canary` ${HOME} "quoted" \\\n # = ; Unicode: café\tend\n\n'
        path = self.profile(yaml.safe_dump({"profile_name": "literal", "description": value}))
        result = self.run_loader(path)
        self.assertFalse((self.root / "value-canary").exists(), "value executed shell code")
        self.assertFalse((self.root / "backtick-canary").exists(), "backticks executed")
        self.assertEqual(self.loaded(result)["CFG_DESCRIPTION"], value)


if __name__ == "__main__":
    unittest.main()
