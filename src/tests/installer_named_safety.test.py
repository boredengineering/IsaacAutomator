#!/usr/bin/env python3
"""Named safety regressions using extracted shell seams, never the installer.

No legacy libraries are sourced. Dispatch targets are action stubs; consumer
seams end before their first filesystem action or host probe.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "isaac-installer"
BIN = INSTALLER / "bin/isaac-installer"


class NamedSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="isaac-named-safety-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.actions = self.base / "actions"

    def run_shell(self, script, *args, **values):
        self.actions.unlink(missing_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base),
               "TARGET_HOME": str(self.base), "TARGET_USER": "fixture",
               "ACTION_LOG": str(self.actions), "LANG": "C.UTF-8"}
        env.update(values)
        shell = self.base / "bin/seam.sh"
        shell.parent.mkdir(exist_ok=True)
        (self.base / "lib/core").mkdir(parents=True, exist_ok=True)
        shell.write_text(script)
        return subprocess.run(["/bin/bash", str(shell), *args],
                              cwd=self.base, env=env, capture_output=True,
                              text=True, timeout=5)

    def dispatch(self, command, *args, layout="named"):
        text = BIN.read_text()
        seam = text[text.index("# --- CLI Argument Parsing ---"):]
        # Simulate a future dispatch arm: the policy must not depend on knowing it.
        seam = seam.replace('case "${COMMAND}" in',
                            'case "${COMMAND}" in\n    future-mutate) mutation ;;', 1)
        stubs = '''set -euo pipefail
DEFAULT_CONFIG_PATH=fixture
SCRIPT_DIR="$HOME/no-installer"
load_config_profile() { WORKSPACE_LAYOUT="${CLI_WORKSPACE_LAYOUT-${FIXTURE_LAYOUT}}"; }
mutation() { printf '%s\\n' "$*" >> "$ACTION_LOG"; return 0; }
log_error() { printf '%s\\n' "$*" >&2; }
usage() { :; }
for action in cmd_auth cmd_doctor cmd_plan print_drift_report repair_workspace_drift \
  cmd_lab cmd_arena cmd_gr00t cmd_sim cmd_net cmd_bench print_active_config \
  cmd_install cmd_resume test_isaaclab_arena test_gr00t test_isaac_lab cmd_test \
  cmd_logs install_streaming_provider list_backups exec; do
  eval "$action() { mutation '$action' \\"\\$@\\"; }"
done
'''
        return self.run_shell(stubs + seam, command, *args, FIXTURE_LAYOUT=layout)

    def test_all_remaining_named_dispatch_is_refused_before_action(self):
        commands = [(name,) for name in
                    ("install", "resume", "repair", "fix", "stream", "gui", "tui",
                     "k9s", "isaac9s", "future-mutate", "unrecognized")]
        commands += [(name, sub) for name in ("lab", "arena", "gr00t")
                     for sub in ("switch", "sync", "fork", "future-mutate")]
        commands += [("auth", "login"), ("sim", "switch"), ("net", "free"),
                     ("ports", "free"), ("zmq", "kill-servers")]
        # Even observations that somehow bypass offline predispatch must not
        # gain access to legacy probes just because they seem read-only.
        commands += [(name,) for name in ("doctor", "plan", "audit", "test", "config")]
        for args in commands:
            with self.subTest(args=args):
                result = self.dispatch(*args)
                self.assertFalse(self.actions.exists(), result.stderr)
                self.assertEqual(result.returncode, 77, result.stderr)
                self.assertIn("not qualified", result.stderr)

    def predispatch(self, *args):
        prefix = BIN.read_text().split("# Source Core Libraries", 1)[0]
        # Never execute preview helpers or source even one legacy library.
        return self.run_shell('exec() { printf "OFFLINE_STUB\\n"; exit 77; }\n' +
                              prefix + '\nprintf "LEGACY_SOURCE_REACHED\\n" >> "$ACTION_LOG"\n',
                              *args)

    def test_unknown_and_cross_command_mutations_cannot_reach_legacy_sources(self):
        for args in (("future-command",), ("lab", "login"), ("auth", "switch"),
                     ("sim", "fork"), ("gr00t", "fix-perms"), ("arena", "free"),
                     ("net", "infer"), ("ports", "fork"), ("zmq", "server")):
            with self.subTest(args=args):
                result = self.predispatch(*args)
                self.assertFalse(self.actions.exists(), result.stderr)
                self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_explicit_legacy_mutation_routes_remain_admitted(self):
        routes = [(name,) for name in ("install", "resume", "repair", "fix", "stream",
                                      "gui", "tui", "k9s", "isaac9s")]
        routes += [(name, sub) for name in ("lab", "arena")
                   for sub in ("switch", "sync", "fork")]
        routes += [("gr00t", sub) for sub in ("sync", "fork", "infer", "server")]
        routes += [("auth", sub) for sub in
                   ("login", "gen-ssh", "ssh", "git", "identity", "check-perms", "fix-perms")]
        routes += [("sim", "switch"), ("arena", "infer")]
        routes += [(name, sub) for name in ("net", "ports", "zmq")
                   for sub in ("free", "kill-servers")]
        for args in routes:
            with self.subTest(args=args):
                result = self.predispatch(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.actions.exists())

    def consumer(self, module, fail_repo, *, layout="named", overrides=False, conditional=True):
        text = (INSTALLER / "lib" / module).read_text()
        if module == "modules/demos.sh":
            name = "install_demos_and_shortcuts"
            seam = text[text.index(name + "() {"):text.index('    mkdir -p "${demos_dir}"')]
            seam += '    mutation "$lab_dir" "$arena_dir" "$gr00t_dir"\n}\n'
        elif module == "modules/conda.sh":
            name = "install_python_env"
            seam = text[text.index(name + "() {"):text.index("    # 1. Clean up")]
            seam += '    mutation "$lab_dir"\n}\n'
        elif module == "core/audit.sh":
            name = "audit_repo_seam"
            # Only repository resolution/report rows, never host-wide audit probes.
            seam = name + '() {\n' + text[text.index("    # 14. Isaac Lab Framework"):
                                        text.index("    # 17. GitHub Hub Authentication")]
            seam += '    mutation "$lab_dir" "$arena_dir" "$gr00t_dir"\n}\n'
        else:
            raise AssertionError("Unsupported consumer seam")
        stubs = '''set -euo pipefail
CONDA_ENV_NAME=fixture
mutation() { printf '%s\\n' "$@" >> "$ACTION_LOG"; }
detect_target_user() { :; }
log_step() { :; }
resolve_target_python_version() { printf '3.12\\n'; }
resolve_conda_bin() { printf '%s/conda/bin/conda\\n' "$HOME"; }
resolve_active_repo_dir() {
    if [[ "$1" == "$FAIL_REPO" ]]; then
        printf '%s\\n' 'named selection rejected: collision/symlink/permission' >&2
        return 73
    fi
    printf '%s/selected/%s\\n' "$HOME" "$1"
}
resolve_repo_dest_path() { mutation FALLBACK; return 73; }
resolve_isaaclab_dir() { resolve_active_repo_dir IsaacLab; }
resolve_arena_dir() { resolve_active_repo_dir IsaacLab-Arena; }
resolve_gr00t_dir() { resolve_active_repo_dir Isaac-GR00T; }
AUDIT_RESULTS=()
INSTALLS_FOUND=0
UPGRADES_FOUND=0
SATISFIED_COUNT=0
'''
        # Conditional invocation disables errexit inside the function. A proper
        # consumer must propagate failure explicitly, not rely on set -e.
        call = ('if ' + name + '; then exit 0; else exit $?; fi\n') if conditional else name + '\n'
        values = {"WORKSPACE_LAYOUT": layout, "FAIL_REPO": fail_repo}
        if overrides:
            values.update({key: str(self.base / "explicit") for key in
                           ("ISAACLAB_DIR", "ARENA_DIR", "GR00T_DIR")})
        return self.run_shell(stubs + seam + call, **values)

    def test_status_prefixes_return_before_probes_on_resolver_failure(self):
        # Extract only the real assignment prefix. Status arms and their host/Git
        # probes are absent, not executed behind denial stubs.
        modules = (('isaaclab.sh', 'cmd_lab', ('IsaacLab',)),
                   ('isaaclab_arena.sh', 'cmd_arena', ('IsaacLab-Arena', 'IsaacLab')),
                   ('gr00t.sh', 'cmd_gr00t', ('Isaac-GR00T',)))
        for module, name, repos in modules:
            text = (INSTALLER / 'lib/modules' / module).read_text()
            start = text.index(name + '() {')
            prefix = text[start:text.index('    case "$subcmd" in', start)]
            script = '''set -euo pipefail
resolve_active_repo_dir() {
    printf 'RESOLVE:%s\\n' "$1" >&2
    [[ "$1" != "$FAIL_REPO" ]] || return 73
    printf '%s/selected/%s\\n' "$HOME" "$1"
}
''' + prefix + '    printf "PREFIX_COMPLETE\\n"\n}\nif ' + name + ' status; then exit 0; else exit $?; fi\n'
            for layout in ('auto', 'org', 'flat', 'named'):
                for fail in (*repos, 'none'):
                    with self.subTest(module=module, layout=layout, fail=fail):
                        result = self.run_shell(script, WORKSPACE_LAYOUT=layout, FAIL_REPO=fail)
                        self.assertEqual(result.returncode, 0 if fail == 'none' else 73, result.stderr)
                        self.assertEqual(result.stdout, 'PREFIX_COMPLETE\n' if fail == 'none' else '')
                        expected = repos if fail == 'none' else repos[:repos.index(fail) + 1]
                        self.assertEqual(result.stderr.splitlines(), ['RESOLVE:' + repo for repo in expected])
                        self.assertFalse(self.actions.exists())

    def test_demos_named_resolution_failure_stops_before_launcher_writes(self):
        for repo in ("IsaacLab", "IsaacLab-Arena", "Isaac-GR00T"):
            for overrides in (False, True):
                for conditional in (False, True):
                    with self.subTest(repo=repo, overrides=overrides, conditional=conditional):
                        result = self.consumer("modules/demos.sh", repo,
                                               overrides=overrides, conditional=conditional)
                        self.assertFalse(self.actions.exists(), result.stderr)
                        self.assertEqual(result.returncode, 73, result.stderr)
                        self.assertIn("named selection rejected", result.stderr)

    def test_conda_named_resolution_failure_stops_before_cleanup_or_install(self):
        for conditional in (False, True):
            with self.subTest(conditional=conditional):
                result = self.consumer("modules/conda.sh", "IsaacLab", conditional=conditional)
                self.assertFalse(self.actions.exists(), result.stderr)
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertIn("named selection rejected", result.stderr)

    def test_audit_named_resolution_failure_cannot_become_legacy_report(self):
        for repo in ("IsaacLab", "IsaacLab-Arena", "Isaac-GR00T"):
            for conditional in (False, True):
                with self.subTest(repo=repo, conditional=conditional):
                    result = self.consumer("core/audit.sh", repo, conditional=conditional)
                    self.assertFalse(self.actions.exists(), result.stderr)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    self.assertIn("named selection rejected", result.stderr)

    def test_named_audit_report_entrypoints_propagate_failure(self):
        text = (INSTALLER / "lib/core/audit.sh").read_text()
        for name, end in (("print_audit_report", '    printf "${CLR_BOLD}'),
                          ("export_audit_json", '    python3 -c')):
            with self.subTest(name=name):
                start = text.index(name + "() {")
                seam = text[start:text.index(end, start)]
                script = '''set -euo pipefail
log_header() { :; }
audit_all_components() { printf 'named resolver refused\\n' >&2; return 73; }
mutation() { printf 'REPORT_ATTEMPT\\n' >> "$ACTION_LOG"; }
''' + seam + '    mutation\n}\nif ' + name + '; then exit 0; else exit $?; fi\n'
                result = self.run_shell(script, WORKSPACE_LAYOUT="named")
                self.assertFalse(self.actions.exists(), result.stderr)
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_legacy_consumers_propagate_resolution_failure_without_fallback(self):
        for layout in ("auto", "org", "flat"):
            for module in ("modules/demos.sh", "modules/conda.sh", "core/audit.sh"):
                for conditional in (False, True):
                    with self.subTest(layout=layout, module=module, conditional=conditional):
                        result = self.consumer(module, "IsaacLab", layout=layout, conditional=conditional)
                        self.assertEqual(result.returncode, 73, result.stderr)
                        self.assertIn("selection rejected", result.stderr)
                        self.assertFalse(self.actions.exists(), result.stderr)

    def test_valid_consumer_selection_reaches_only_stubbed_action_in_all_layouts(self):
        for layout in ("auto", "org", "flat", "named"):
            for module in ("modules/demos.sh", "modules/conda.sh", "core/audit.sh"):
                with self.subTest(layout=layout, module=module):
                    result = self.consumer(module, "none", layout=layout)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    outputs = self.actions.read_text().splitlines()
                    repos = ["IsaacLab"] if module == "modules/conda.sh" else [
                        "IsaacLab", "IsaacLab-Arena", "Isaac-GR00T"]
                    self.assertEqual(outputs, [str(self.base / "selected" / repo) for repo in repos])

    def test_effective_layout_gates_dispatch_without_changing_legacy_actions(self):
        for layout in ("auto", "org", "flat"):
            for command in ("repair", "fix", "install", "resume"):
                with self.subTest(layout=layout, command=command):
                    result = self.dispatch(command, layout=layout)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(self.actions.exists())
                    result = self.dispatch(command, "--workspace-layout", "named", layout=layout)
                    self.assertEqual(result.returncode, 77, result.stderr)
                    self.assertFalse(self.actions.exists())
        result = self.dispatch("repair", "--workspace-layout", "flat", layout="named")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.actions.exists())

    def test_offline_predispatch_still_wins_for_dry_run_and_observations(self):
        for args in (("repair", "--dry-run"), ("lab", "switch", "--dry-run"),
                     ("gr00t", "fork", "--dry-run=false"), ("help",),
                     ("lab", "status"), ("plan",), ("observe",), ("review-profile",),
                     ("--workspace-layout", "named", "repair")):
            with self.subTest(args=args):
                result = self.predispatch(*args)
                self.assertFalse(self.actions.exists(), result.stderr)
                self.assertEqual(result.returncode, 77, result.stderr)


if __name__ == "__main__":
    unittest.main()
