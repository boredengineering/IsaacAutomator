"""Safe-entry tests: never execute the legacy installer body."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "isaac-installer/bin/isaac-installer"
CORE = ROOT / "isaac-installer/lib/core"


class SafePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="isaac-safe-")
        self.base = Path(self.temp.name)
        self.base.chmod(0o755)
        self.installer = self.base / "installer"
        (self.installer / "bin").mkdir(parents=True)
        (self.installer / "lib/core").mkdir(parents=True)
        # If the early barrier is missing, stop BEFORE any original legacy code.
        text = BIN.read_text()
        prefix = text.split("# Source Core Libraries", 1)[0]
        (self.installer / "bin/isaac-installer").write_text(
            prefix + '\nprintf "LEGACY_BODY_REACHED\\n" >&2\nexit 99\n')
        for name in ("safe_preview.py", "preview_sandbox.py", "profile_parser.py", "workspace_paths.py"):
            if (CORE / name).exists():
                shutil.copyfile(CORE / name, self.installer / "lib/core" / name)
        self.profile = self.base / "profile.yaml"
        self.profile.write_text("profile_name: fixture\nrepositories:\n  arena:\n    enabled: true\n")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, nonroot=False):
        def drop():
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
        return subprocess.run(
            ["/bin/bash", str(self.installer / "bin/isaac-installer"), *args],
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.base)}, cwd=self.base,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            preexec_fn=drop if nonroot else None, timeout=10)

    @unittest.skipUnless(os.geteuid() == 0, "root refusal requires root test runner")
    def test_root_dry_run_stops_before_legacy_body(self):
        result = self.run_cli("install", "--config", "/DO_NOT_READ", "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("LEGACY_BODY_REACHED", result.stderr)
        self.assertIn("root", result.stderr.lower())

    def test_offline_preview_selects_stages_without_claiming_host_health(self):
        result = self.run_cli("--dry-run", "install", "--config", str(self.profile),
                              "--only", "arena,isaacsim", "--without", "isaacsim", "--json", nonroot=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        import json
        self.assertTrue(result.stdout.startswith("{"), "profile-only JSON preview is missing")
        data = json.loads(result.stdout)
        selected = [row["stage"] for row in data["stages"] if row["status"] == "unknown"]
        self.assertEqual(selected, ["arena"])
        self.assertEqual(data["scope"], "offline-profile-only")
        self.assertFalse(data["execution_authorized"])
        self.assertEqual(self.profile.read_text(), "profile_name: fixture\nrepositories:\n  arena:\n    enabled: true\n")

    def test_stage_selection_matches_extracted_legacy_pure_function(self):
        text = BIN.read_text()
        start = text.index('is_stage_selected() {')
        end = text.index('evaluate_and_run_stage() {', start)
        import re
        stages = re.findall(r'evaluate_and_run_stage "([a-z_0-9]+)"', text)
        shell = self.base / "selection.sh"
        shell.write_text(text[start:end] + '\nfor stage in "$@"; do\n if is_stage_selected "$stage"; then printf "%s\\n" "$stage"; fi\ndone\n')
        import json
        for only, without, flags in [("", "", []), ("", "", ["--with-arena", "--with-lerobot", "--with-gr00t"]),
                                      ("arena,isaacsim", "arena", []), ("demos,gr00t", "", []),
                                      ("", "driver,demos,arena", [])]:
            self.profile.write_text("profile_name: fixture\ndemos:\n  desktop_shortcuts: false\nrepositories:\n  arena:\n    enabled: true\n")
            env = {"PATH": "/usr/bin:/bin", "ONLY_STAGES": only, "WITHOUT_STAGES": without,
                   "CONFIG_FILE": "fixture", "CFG_REPOSITORIES_ARENA_ENABLED": "true", "CFG_DEMOS_DESKTOP_SHORTCUTS": "false"}
            for flag, key in [("--with-lerobot", "CFG_REPOSITORIES_LEROBOT_ENABLED"),
                              ("--with-gr00t", "CFG_REPOSITORIES_GR00T_ENABLED")]:
                if flag in flags:
                    env[key] = "true"
            actual = subprocess.run(["/bin/bash", str(shell), *stages], env=env, cwd=self.base,
                                    capture_output=True, text=True, timeout=5)
            args = ["install", "--dry-run", "--config", str(self.profile), "--json", *flags]
            if only:
                args.extend(("--only", only))
            if without:
                args.extend(("--without", without))
            result = self.run_cli(*args, nonroot=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            rows = json.loads(result.stdout)["stages"]
            self.assertEqual([row["stage"] for row in rows], stages)
            self.assertEqual([row["stage"] for row in rows if row["status"] == "unknown"], actual.stdout.splitlines())

    def test_help_is_static_and_never_initializes_installer(self):
        for args in [(), ("help",), ("--help",), ("-h",)]:
            result = self.run_cli(*args, nonroot=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("offline", result.stdout.lower())
            for command in ('export-profile', 'plan-profile', 'render-profile', 'migration-profile', 'observe-targets', '--output'):
                self.assertIn(command, result.stdout)
            self.assertNotIn("LEGACY_BODY_REACHED", result.stderr)

    def test_explicit_disabled_sim_lab_are_consumed_by_legacy_selection_and_preview(self):
        text = BIN.read_text()
        seam = text[text.index('is_stage_selected() {'):text.index('evaluate_and_run_stage() {')]
        script = self.base / 'selection-disabled.sh'
        script.write_text(seam + '\nfor stage in isaacsim isaaclab; do if is_stage_selected "$stage"; then printf "%s\\n" "$stage"; fi; done\n')
        result = subprocess.run(['/bin/bash', str(script)], cwd=self.base,
                                env={'PATH': '/usr/bin:/bin', 'ONLY_STAGES': '', 'WITHOUT_STAGES': '',
                                     'CFG_SIMULATION_ISAACSIM_ENABLED': 'false',
                                     'CFG_REPOSITORIES_ISAACLAB_ENABLED': 'false', 'CONFIG_FILE': 'fixture'},
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.profile.write_text('simulation:\n  isaacsim:\n    enabled: false\nrepositories:\n  isaaclab:\n    enabled: false\n')
        preview = self.run_cli('install', '--dry-run', '--config', str(self.profile), '--json', nonroot=True)
        import json
        self.assertEqual(preview.returncode, 2, preview.stderr)
        rows = {row['stage']: row for row in json.loads(preview.stdout)['stages']}
        for name in ('isaacsim', 'isaaclab'):
            self.assertEqual(rows[name]['status'], 'excluded')

    def test_workspace_preview_cli_overrides_profile_as_pure_intent(self):
        self.profile.write_text("profile_name: fixture\nworkspace:\n  root: ~/Documents/GitHub\n  layout: named\n  name: ProfileName\n  default_owner: owner\n")
        result = self.run_cli("install", "--dry-run", "--config", str(self.profile), "--json",
                              "--workspace-name", "BoredEngineer", "--workspace-root", "/fixture/workspace",
                              "--workspace-default-owner", "", nonroot=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(result.stdout.startswith("{"), result.stderr)
        import json
        workspace = json.loads(result.stdout)["workspace_intent"]
        self.assertEqual(workspace["name"], {"value": "BoredEngineer", "source": "cli"})
        self.assertEqual(workspace["root"], {"value": "/fixture/workspace", "source": "cli"})
        self.assertEqual(workspace["layout"], {"value": "named", "source": "profile"})
        self.assertEqual(workspace["default_owner"], {"value": "", "source": "cli"})
        self.assertEqual(workspace["target_home"], "unknown")
        self.assertEqual(workspace["filesystem_status"], "unknown")
        text_result = self.run_cli("install", "--dry-run", "--config", str(self.profile),
                                   "--workspace-name", "BoredEngineer", "--workspace-default-owner", "", nonroot=True)
        self.assertIn("BoredEngineer", text_result.stdout)
        self.assertIn('"source": "cli"', text_result.stdout)

    def test_unsafe_options_refuse_before_opening_profile(self):
        for extra in [("--stream", "sunshine"), ("--auto-reboot",), ("--step",),
                      ("--isaaclab-repo", "attacker/repo"), ("--workspace-root", "/"),
                      ("--only", "sim"), ("--config", "/duplicate"), ("--dry-run=false",),
                      ("--unknown",), ("--without",)]:
            with self.subTest(extra=extra):
                result = self.run_cli("install", "--dry-run", "--config", "/DO_NOT_READ", *extra, nonroot=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Cannot confine", result.stderr)
                self.assertNotIn("LEGACY_BODY_REACHED", result.stderr)

    def test_malicious_profile_data_is_not_executed_or_echoed(self):
        cases = ["x: !!python/object/apply:os.system ['touch /MUST_NOT_EXIST']\n",
                 "hooks:\n  pre: SUPER_PRIVATE_PAYLOAD\n", "kind: workstation-baseline\n",
                 "x: &loop\n  x: *loop\n", "x: 1\nx: 2\n", "x: [1, 2]\n"]
        for content in cases:
            with self.subTest(content=content[:20]):
                self.profile.write_text(content)
                result = self.run_cli("install", "--dry-run", "--config", str(self.profile), nonroot=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("profile", result.stderr)
                self.assertNotIn("SUPER_PRIVATE_PAYLOAD", result.stderr + result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.profile.read_text(), content)

    def test_symlink_and_hardlink_profile_inputs_are_refused(self):
        for kind in ("symlink", "hardlink"):
            link = self.base / kind
            if kind == "symlink":
                link.symlink_to(self.profile)
            else:
                os.link(self.profile, link)
            result = self.run_cli("install", "--dry-run", "--config", str(link), nonroot=True)
            self.assertEqual(result.returncode, 77, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            link.unlink()

    def test_named_application_is_blocked_before_stage_dispatch(self):
        text = BIN.read_text()
        start = text.index('# 2. Apply Explicit CLI Overrides')
        end = text.index('case "${COMMAND}" in', start)
        seam = self.base / "apply-seam.sh"
        seam.write_text('set -eu\nCLI_WITH_ARENA=false\nCLI_WITH_LEROBOT=false\nCLI_WITH_GR00T=false\n' +
                        text[start:end] + '\nprintf "STAGE_DISPATCH_REACHED"\n')
        for command in ("install", "resume"):
            result = subprocess.run(["/bin/bash", str(seam)], cwd=self.base,
                                    env={"PATH": "/usr/bin:/bin", "COMMAND": command, "WORKSPACE_LAYOUT": "named"},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 77, result.stderr)
            self.assertNotIn("STAGE_DISPATCH_REACHED", result.stdout)
            self.assertIn("not qualified", result.stderr)
        result = subprocess.run(["/bin/bash", str(seam)], cwd=self.base,
                                env={"PATH": "/usr/bin:/bin", "COMMAND": "install", "WORKSPACE_LAYOUT": "flat"},
                                capture_output=True, text=True)
        self.assertEqual(result.stdout, "STAGE_DISPATCH_REACHED")

    def test_shared_profile_cannot_fall_into_unqualified_flat_application(self):
        text = BIN.read_text()
        start = text.index('# 2. Apply Explicit CLI Overrides')
        end = text.index('case "${COMMAND}" in', start)
        seam = self.base / 'shared-gate.sh'
        seam.write_text('set -eu\nCLI_WITH_ARENA=false\nCLI_WITH_LEROBOT=false\nCLI_WITH_GR00T=false\n' +
                        text[start:end] + '\nprintf "STAGE_DISPATCH_REACHED"\n')
        for layout in ('flat', 'auto', 'org', 'named'):
            for command in ('install', 'resume', 'repair', 'gr00t', 'gui'):
                result = subprocess.run(['/bin/bash', str(seam)], cwd=self.base,
                    env={'PATH': '/usr/bin:/bin', 'COMMAND': command, 'WORKSPACE_LAYOUT': layout,
                         'CFG_PUBLIC_GIT_PROFILE': 'true'}, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 77, 'Shared rendered intent must not authorize native stages')
                self.assertNotIn('STAGE_DISPATCH_REACHED', result.stdout)
                self.assertIn('not qualified', result.stderr)

    def test_parser_type_failure_is_sanitized(self):
        parser = self.installer / "lib/core/profile_parser.py"
        parser.write_text('import yaml\ndef parse_profile(path, **kwargs):\n    raise TypeError("SECRET_PAYLOAD")\n')
        result = self.run_cli("install", "--dry-run", "--config", str(self.profile), nonroot=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("SECRET_PAYLOAD", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_discovery_dispatch_is_separate_before_legacy_initialization(self):
        (self.installer / "lib/core/discovery_cli.py").write_text(
            'import sys\nprint("DISCOVERY_ENTRY:" + sys.argv[1])\n')
        for command in ("observe", "review-profile"):
            result = self.run_cli(command, "--fixture", nonroot=True)
            self.assertEqual(result.stdout.strip(), "DISCOVERY_ENTRY:" + command)
            self.assertNotIn("LEGACY_BODY_REACHED", result.stderr)
        result = self.run_cli("observe", "--dry-run", nonroot=True)
        self.assertNotIn("DISCOVERY_ENTRY", result.stdout)
        self.assertEqual(result.returncode, 2)

    def test_workspace_overrides_are_explicit_only_without_legacy_execution(self):
        text = BIN.read_text()
        globals_start = text.index("# Global State & Filter Lists")
        parsing_start = text.index("# --- CLI Argument Parsing ---")
        parsing_end = text.index("# 1. Load Active YAML Profile")
        # Only execute declarations and argument parsing; never sources/handlers.
        declarations = text[globals_start:text.index("# Check if a stage", globals_start)]
        script = self.base / "parse.sh"
        script.write_text('set -eu\n' + declarations + text[parsing_start:parsing_end] +
                          '\nprintf "%s|%s|%s|%s" "${CLI_WORKSPACE_DIR-unset}" "${CLI_WORKSPACE_NAME-unset}" "${CLI_WORKSPACE_LAYOUT-unset}" "${CLI_WORKSPACE_DEFAULT_OWNER-unset}"\n')
        env = {"PATH": "/usr/bin:/bin", "CLI_WORKSPACE_DIR": "POISON", "CLI_WORKSPACE_NAME": "POISON",
               "CLI_WORKSPACE_LAYOUT": "POISON", "CLI_WORKSPACE_DEFAULT_OWNER": "POISON"}
        result = subprocess.run(["/bin/bash", str(script), "install"], env=env, capture_output=True, text=True)
        self.assertEqual(result.stdout, "unset|unset|unset|unset")
        result = subprocess.run(["/bin/bash", str(script), "install", "--workspace-root", "/fixture",
                                 "--workspace-name", "BoredEngineer", "--workspace-layout", "named",
                                 "--workspace-default-owner", "boredengineering"], env=env, capture_output=True, text=True)
        self.assertEqual(result.stdout, "/fixture|BoredEngineer|named|boredengineering")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_kernel_confinement_denies_negative_controls(self):
        helper = CORE / "preview_sandbox.py"
        self.assertTrue(helper.exists(), "reusable confinement is missing")
        secret = self.base / "secret"
        secret.write_text("fake secret")
        secret.chmod(0o666)
        runner = self.base / "controls.py"
        runner.write_text('''import sys, os, socket, subprocess, json, fcntl
sys.path.insert(0, sys.argv[1])
from preview_sandbox import enter_confinement
allowed, forbidden = sys.argv[2:4]
oldfd = os.open(forbidden, os.O_RDONLY)
enter_confinement([allowed])
assert open(allowed).read().startswith("profile_name")
checks = {
 "write": lambda: open(forbidden, "w"),
 "allowed_write": lambda: open(allowed, "w"),
 "read_outside": lambda: open(forbidden).read(),
 "network": lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
 "unix_socket": lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM),
 "helper": lambda: subprocess.run(["/usr/bin/true"]),
 "chmod": lambda: os.chmod(forbidden, 0o777),
 "inherited_fd": lambda: os.read(oldfd, 1),
 "advisory_lock": lambda: fcntl.lockf(os.open(allowed, os.O_RDONLY), fcntl.LOCK_SH | fcntl.LOCK_NB),
}
result = {}
for name, action in checks.items():
 try:
  action()
  result[name] = "ESCAPED"
 except OSError:
  result[name] = "denied"
print(json.dumps(result))
''')
        def drop():
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
        result = subprocess.run(["/usr/bin/python3", "-I", "-B", str(runner),
                                 str(self.installer / "lib/core"), str(self.profile), str(secret)],
                                env={"PATH": "/usr/bin:/bin"}, cwd=self.base,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                preexec_fn=drop, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        self.assertEqual(set(json.loads(result.stdout).values()), {"denied"})
        self.assertEqual(secret.read_text(), "fake secret")
        self.assertEqual(secret.stat().st_mode & 0o777, 0o666)

    def run_sandbox_script(self, source, *args, stdout=None):
        runner = self.base / "sandbox-case.py"
        runner.write_text('import sys, os, json, ctypes\nsys.path.insert(0, sys.argv[1])\n' + source)
        def drop():
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
        return subprocess.run(["/usr/bin/python3", "-I", "-B", str(runner),
                               str(self.installer / "lib/core"), *map(str, args)],
                              env={"PATH": "/usr/bin:/bin"}, cwd=self.base,
                              stdin=subprocess.DEVNULL, stdout=stdout or subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, preexec_fn=drop, timeout=10)

    def test_unavailable_landlock_has_no_unconfined_fallback(self):
        source = '''from preview_sandbox import _Filter, _Program, confine_readonly, SandboxError
# Actual outer kernel filter simulates a platform denying Landlock discovery.
libc = ctypes.CDLL(None)
filters = (_Filter * 4)(_Filter(0x20,0,0,0), _Filter(0x15,0,1,444),
                        _Filter(0x06,0,0,0x50000 | 38), _Filter(0x06,0,0,0x7fff0000))
program = _Program(4, filters)
assert libc.prctl(38,1,0,0,0) == 0
assert libc.prctl(22,2,ctypes.byref(program),0,0) == 0
try:
 confine_readonly([sys.argv[2]])
except SandboxError as error:
 print(str(error))
 sys.exit(77)
print("UNCONFINED_FALLBACK")
'''
        result = self.run_sandbox_script(source, self.profile)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertIn("Landlock ABI", result.stdout)
        self.assertNotIn("UNCONFINED_FALLBACK", result.stdout)

    def test_directory_scope_blocks_symlink_escape_and_writes(self):
        root = self.base / "workspace"
        root.mkdir()
        (root / "normal").write_text("normal")
        (root / "escape").symlink_to(self.profile)
        source = '''from preview_sandbox import confine_readonly
root = sys.argv[2]
confine_readonly([root])
assert sorted(os.listdir(root)) == ["escape", "normal"]
assert open(root + "/normal").read() == "normal"
for path, mode in [(root + "/escape", "r"), (root + "/normal", "w"), (root + "/new", "w")]:
 try:
  open(path, mode)
  raise AssertionError("escape succeeded")
 except PermissionError:
  pass
print("denied")
'''
        result = self.run_sandbox_script(source, root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "denied")
        self.assertEqual((root / "normal").read_text(), "normal")
        self.assertFalse((root / "new").exists())

    def test_redirected_output_files_are_not_admitted(self):
        target = self.base / "output"
        source = '''from preview_sandbox import confine_readonly, SandboxError
try:
 confine_readonly([sys.argv[2]])
except SandboxError as error:
 print(str(error), file=sys.stderr)
 sys.exit(77)
'''
        with target.open("wb") as out:
            result = self.run_sandbox_script(source, self.profile, stdout=out)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertIn("Output must", result.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_observation_commands_never_reach_legacy_body(self):
        for args in [("doctor",), ("plan",), ("check",), ("audit",), ("drift",),
                     ("config",), ("test",), ("validate",), ("bench",), ("logs",),
                     ("backups",), ("auth",), ("auth", "status"),
                     ("lab", "list-tags"), ("arena", "status"), ("gr00t", "status"),
                     ("sim", "list"), ("net", "status"), ("ports",), ("zmq",)]:
            with self.subTest(args=args):
                result = self.run_cli(*args, nonroot=True)
                self.assertNotIn("LEGACY_BODY_REACHED", result.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unknown", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
