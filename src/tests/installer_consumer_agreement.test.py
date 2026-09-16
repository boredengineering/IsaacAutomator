#!/usr/bin/env python3
"""Actual shell consumer seams on test-owned files; never installer/host probes.

No managed_apply/fixture_builders imports or execution. Repository metadata,
identity, ownership, GUI, Conda and runtime commands are stubbed. The resolver
itself is real and examines only these synthetic temporary directories.
"""
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'isaac-installer/lib'


def function(relative, name):
    text = (LIB / relative).read_text()
    match = re.search(r'^' + re.escape(name) + r'\(\) \{\n.*?^\}(?=\n\n*(?:#|[A-Za-z_]\w*\(\)|\Z))', text, re.M | re.S)
    if not match:
        raise AssertionError(f'Missing actual function {relative}:{name}')
    return match.group() + '\n'


class ConsumerAgreementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-consumer-agreement-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'Home With Spaces'
        self.home.mkdir()
        self.workspace = self.home / 'Work Space'
        self.workspace.mkdir()
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.home),
                    'TARGET_HOME': str(self.home), 'TARGET_USER': 'fixture',
                    'WORKSPACE_DIR': str(self.workspace), 'WORKSPACE_LAYOUT': 'named',
                    'WORKSPACE_NAME': 'Reviewed Team', 'LANG': 'C.UTF-8'}
        self.script = self.base / 'seam.sh'
        (self.base / 'workspace_paths.py').write_text((LIB / 'core/workspace_paths.py').read_text())

    def resolver(self):
        return ''.join(function('core/git_workspace.sh', name) for name in (
            'resolve_default_workspace_dir', 'find_existing_repo',
            'resolve_repo_dest_path', 'resolve_active_repo_dir'))

    def modules(self):
        return ''.join(function('modules/' + module + '.sh', name) for module, name in (
            ('isaaclab', 'resolve_isaaclab_dir'), ('isaaclab_arena', 'resolve_arena_dir'),
            ('gr00t', 'resolve_gr00t_dir'), ('physical_ai', 'resolve_lerobot_dir')))

    def shell(self, body, **values):
        env = dict(self.env, **values)
        self.script.write_text('set -uo pipefail\ndetect_target_user() { :; }\n' + self.resolver() + self.modules() + body)
        return subprocess.run(['/bin/bash', str(self.script)], cwd=self.base,
                              env=env, text=True, capture_output=True, timeout=15)

    def test_configured_active_selection_uses_destination_not_other_checkout(self):
        unrelated = self.home / 'IsaacLab/.git'
        unrelated.mkdir(parents=True)
        for layout, name, owner in [('named', 'Reviewed Team', ''), ('flat', '', ''),
                                    ('auto', '', 'ChosenOwner'), ('org', '', 'ChosenOwner')]:
            with self.subTest(layout=layout):
                result = self.shell('resolve_repo_dest_path IsaacLab isaac-sim/IsaacLab\n'
                                    'resolve_active_repo_dir IsaacLab isaac-sim/IsaacLab\n',
                                    WORKSPACE_LAYOUT=layout, WORKSPACE_NAME=name,
                                    WORKSPACE_DEFAULT_OWNER=owner)
                self.assertEqual(result.returncode, 0, result.stderr)
                selected = result.stdout.splitlines()
                self.assertEqual(len(selected), 2)
                self.assertEqual(selected[0], selected[1])
        explicit = self.home / 'Exact Override'
        result = self.shell('resolve_active_repo_dir IsaacLab isaac-sim/IsaacLab "$ISAACLAB_DIR"\n',
                            WORKSPACE_LAYOUT='auto', WORKSPACE_NAME='', WORKSPACE_DIR='',
                            ISAACLAB_DIR=str(explicit))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(explicit))

    def state_seam(self):
        return '\n'.join(function('core/state.sh', name) for name in (
            'resolve_state_dir', 'resolve_state_file', 'init_state', 'sync_state_ledger'))

    def test_state_snapshot_records_selected_repositories_without_discovery(self):
        script = self.state_seam() + r'''
chown() { :; }
find_existing_repo() { printf 'FORBIDDEN_DISCOVERY\n' >&2; return 72; }
get_repo_info() { python3 -c 'import json,sys; print(json.dumps({"exists": True, "path":sys.argv[1]}))' "$1"; }
resolve_conda_env_path() { printf '%s/Conda Env\n' "$TARGET_HOME"; }
resolve_isaacsim_dir() { printf '%s/Sim Engine\n' "$TARGET_HOME"; }
if sync_state_ledger; then exit 0; else exit $?; fi
'''
        names = {'isaaclab': 'IsaacLab', 'arena': 'IsaacLab-Arena',
                 'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot'}
        for name in names.values():
            (self.workspace / 'Reviewed Team' / name / '.git').mkdir(parents=True)
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        state = json.loads((self.home / '.isaac-installer/state.json').read_text())
        self.assertEqual(set(state['repositories']), set(names))
        for key, name in names.items():
            self.assertEqual(state['repositories'][key]['path'], str(self.workspace / 'Reviewed Team' / name))
        self.assertEqual(state['simulation']['install_dir'], str(self.home / 'Sim Engine'))

    def audit_seam(self):
        text = (LIB / 'core/audit.sh').read_text()
        return ('audit_repository_seam() {\n' +
                text[text.index('    # 14. Isaac Lab Framework'):text.index('    # 17. GitHub Hub Authentication')] +
                '\n printf "%s\\n" "$lab_dir" "$arena_dir" "$gr00t_dir"\n}\n')

    def drift_seam(self):
        text = (LIB / 'core/state.sh').read_text()
        return (text[text.index('audit_workspace_drift() {'):text.index('    # 4. Audit Conda Environment Drift')] +
                '\n printf "%s\\n" "${DRIFT_ITEMS[@]}"\n}\n')

    def test_drift_repository_targets_match_selected_module_paths(self):
        result = self.shell(self.drift_seam() + r'''
find_existing_repo() { printf 'FORBIDDEN_DISCOVERY\n' >&2; return 72; }
if audit_workspace_drift; then exit 0; else exit $?; fi
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        rows = [line.split('|') for line in result.stdout.splitlines()]
        self.assertEqual({row[0] for row in rows}, {'IsaacLab', 'IsaacLab-Arena'})
        for row in rows:
            self.assertEqual(row[3], str(self.workspace / 'Reviewed Team' / row[0]))
        # Canonical source defaults matter for legacy auto/org owner selection.
        result = self.shell(self.drift_seam() + 'audit_workspace_drift\n',
                            WORKSPACE_LAYOUT='auto', WORKSPACE_NAME='')
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in [line.split('|') for line in result.stdout.splitlines()]:
            self.assertEqual(row[3], str(self.workspace / row[0]))

    def test_audit_resolver_failures_propagate_in_all_layouts(self):
        for layout in ('named', 'flat', 'auto', 'org'):
            with self.subTest(layout=layout):
                result = self.shell(self.audit_seam() + r'''
AUDIT_RESULTS=(); INSTALLS_FOUND=0; UPGRADES_FOUND=0; SATISFIED_COUNT=0
resolve_isaaclab_dir() { printf 'SELECTION_REFUSED\n' >&2; return 73; }
if audit_repository_seam; then exit 0; else exit $?; fi
''', WORKSPACE_LAYOUT=layout, WORKSPACE_NAME='Reviewed Team' if layout == 'named' else '')
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('SELECTION_REFUSED', result.stderr)

    def generate_launchers(self, **values):
        return self.shell((LIB / 'modules/demos.sh').read_text() + r'''
log_step() { :; }; log_success() { :; }; chown() { :; }; run_as_user() { :; }
run_as_user_stdin() { cat > "$1"; }
if install_demos_and_shortcuts; then exit 0; else exit $?; fi
''', **values)

    def test_generated_launchers_execute_only_bound_selected_paths(self):
        for repo in ('IsaacLab', 'IsaacLab-Arena', 'Isaac-GR00T'):
            (self.workspace / 'Reviewed Team' / repo).mkdir(parents=True)
            (self.home / repo).mkdir()  # Tempting legacy first-match decoy.
        result = self.generate_launchers()
        self.assertEqual(result.returncode, 0, result.stderr)
        interception = self.base / 'mock-exec.sh'
        interception.write_text('exec() { printf "SELECTED_CWD=%s\\n" "$PWD"; printf "ARG=%s\\n" "$@"; exit 0; }\n')
        launchers = {'humanoid-locomotion.sh': 'IsaacLab', 'quadruped-locomotion.sh': 'IsaacLab',
                     'franka-manipulation.sh': 'IsaacLab', 'arena-benchmark.sh': 'IsaacLab-Arena',
                     'arena-gr00t-closed-loop.sh': 'IsaacLab-Arena', 'gr00t-policy-server.sh': 'Isaac-GR00T'}
        for launcher, repo in launchers.items():
            with self.subTest(launcher=launcher):
                generated = self.home / '.local/share/isaac-demos' / launcher
                run = subprocess.run(['/bin/bash', str(generated)], env=dict(self.env, BASH_ENV=str(interception)),
                                     cwd=self.base, text=True, capture_output=True, timeout=5)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn('SELECTED_CWD=' + str(self.workspace / 'Reviewed Team' / repo), run.stdout)
                self.assertNotIn('find ', generated.read_text())
        for desktop in (self.home / 'Desktop').glob('*.desktop'):
            line = next(line for line in desktop.read_text().splitlines() if line.startswith('Exec='))
            args = shlex.split(line.removeprefix('Exec='))
            self.assertIn(str(self.home / '.local/share/isaac-demos'), ' '.join(args))
            self.assertNotIn('-c', args, 'desktop must pass spaced launcher path as one argument, not nested shell source')

    def test_repair_reports_selected_paths_but_never_mutates(self):
        # Even an empty legacy drift result must not write the ledger or imply
        # that existing resources are healthy/adopted. No legacy audit executes.
        body = (LIB / 'core/state.sh').read_text() + r'''
log_header() { :; }; log_success() { :; }
audit_workspace_drift() { printf 'UNQUALIFIED_AUDIT\n' >&2; DRIFT_ITEMS=(); }
sync_state_ledger() { printf 'FORBIDDEN_LEDGER_WRITE\n' >&2; }
if repair_workspace_drift; then exit 0; else exit $?; fi
'''
        result = self.shell(body)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertNotIn('UNQUALIFIED_AUDIT', result.stderr)
        self.assertNotIn('FORBIDDEN_LEDGER_WRITE', result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan['mutation_supported'])
        self.assertEqual(plan['status'], 'unsupported')
        self.assertEqual(plan['selected_paths'], {key: str(self.workspace / 'Reviewed Team' / name)
                         for key, name in {'isaaclab': 'IsaacLab', 'arena': 'IsaacLab-Arena',
                                           'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot'}.items()})
        self.assertFalse((self.home / '.isaac-installer').exists())

    def test_launcher_generation_propagates_legacy_selection_refusal_before_writes(self):
        for layout in ('auto', 'org', 'flat'):
            with self.subTest(layout=layout):
                # Real module resolver must reject this case-only collision.
                (self.home / 'Exact Override').mkdir(exist_ok=True)
                result = self.generate_launchers(WORKSPACE_LAYOUT=layout, WORKSPACE_NAME='',
                                                 ISAACLAB_DIR=str(self.home / 'exact override'))
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.home / '.local').exists())
                self.assertIn('collision', result.stderr)

    def test_report_entries_preserve_failed_audit_status_for_every_layout(self):
        for name, source in [('print_audit_report', 'core/audit.sh'),
                             ('export_audit_json', 'core/audit.sh'),
                             ('print_drift_report', 'core/state.sh')]:
            for layout in ('named', 'flat', 'auto', 'org'):
                with self.subTest(name=name, layout=layout):
                    result = self.shell(function(source, name) + r'''
log_header() { :; }; log_success() { :; }; DRIFT_ITEMS=(); AUDIT_RESULTS=()
CLR_BOLD=; CLR_RESET=; CLR_GREEN=; CLR_YELLOW=; CLR_RED=; CLR_CYAN=
CONFIG_FILE=fixture; OS_NAME=fixture; OS_VERSION=fixture; GPU_NAME=fixture; DRIVER_VERSION=fixture
FREE_DISK_GB=0; SATISFIED_COUNT=0; INSTALLS_FOUND=0; UPGRADES_FOUND=0; CONFLICTS_FOUND=0
audit_all_components() { printf 'AUDIT_REFUSED\n' >&2; return 73; }
audit_workspace_drift() { printf 'AUDIT_REFUSED\n' >&2; return 73; }
''' + 'if ' + name + '; then exit 0; else exit $?; fi\n', WORKSPACE_LAYOUT=layout)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('AUDIT_REFUSED', result.stderr)

    def test_drift_does_not_swallow_root_resolution_error(self):
        result = self.shell(self.drift_seam() + r'''
resolve_default_workspace_dir() { printf 'ROOT_REFUSED\n' >&2; return 73; }
if audit_workspace_drift; then exit 0; else exit $?; fi
''')
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_drift_metadata_failure_cannot_be_reported_as_no_drift(self):
        (self.workspace / 'Reviewed Team/IsaacLab/.git').mkdir(parents=True)
        result = self.shell(self.drift_seam() + r'''
normalize_git_url() { printf '%s\n' "$1"; }
get_repo_info() { printf 'METADATA_REFUSED\n' >&2; return 73; }
if audit_workspace_drift; then exit 0; else exit $?; fi
''')
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_auxiliary_path_resolution_failures_are_not_fallbacks(self):
        audit = (LIB / 'core/audit.sh').read_text()
        state = (LIB / 'core/state.sh').read_text()
        # Actual assignment blocks, ending BEFORE any package/runtime/host probe.
        blocks = [audit[audit.index('    local conda_bin'):audit.index('    if [[ -x "$conda_bin"')],
                  audit[audit.index('    local sim_dir', audit.index('# 13. Isaac Sim Engine')):
                        audit.index('    local sim_cur=')],
                  state[state.index('    local conda_bin', state.index('# 4. Audit Conda')):
                        state.index('    if [[ -d "/opt/conda')],
                  state[state.index('    local sim_dir\n', state.index('# 5. Audit Standalone')):
                        state.index('    if [[ -n "$sim_dir"')]]
        for index, block in enumerate(blocks):
            with self.subTest(block=index):
                result = self.shell('auxiliary_seam() {\n' + block + '\n printf "CONTINUED\\n"\n}\n' + r'''
resolve_conda_bin() { printf 'AUX_REFUSED\n' >&2; return 73; }
resolve_conda_env_path() { printf 'AUX_REFUSED\n' >&2; return 73; }
resolve_isaacsim_dir() { printf 'AUX_REFUSED\n' >&2; return 73; }
if auxiliary_seam; then exit 0; else exit $?; fi
''')
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('AUX_REFUSED', result.stderr)

    def test_actual_status_missing_paths_match_module_selection(self):
        # The full real status function runs its missing-path arm; metadata and
        # upstream-sync helpers are traps, never the real safe.directory/fetch.
        (self.workspace / 'NVIDIA').mkdir()
        (self.workspace / 'isaac-sim').mkdir()
        for module, cmd, resolver in [('isaaclab', 'cmd_lab', 'resolve_isaaclab_dir'),
                                      ('isaaclab_arena', 'cmd_arena', 'resolve_arena_dir'),
                                      ('gr00t', 'cmd_gr00t', 'resolve_gr00t_dir')]:
            with self.subTest(cmd=cmd):
                result = self.shell(function('modules/' + module + '.sh', cmd) + r'''
log_header() { :; }; log_info() { printf '%s\n' "$*"; }
get_repo_info() { printf 'FORBIDDEN_METADATA\n' >&2; return 91; }
check_fork_sync_status() { printf 'FORBIDDEN_FETCH\n' >&2; return 91; }
''' + resolver + '\n' + cmd + ' status\n', WORKSPACE_LAYOUT='auto', WORKSPACE_NAME='')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                expected, status = result.stdout.split('\n', 1)
                self.assertIn('at ' + expected + '.', status)

    def test_reviewed_config_transport_agrees_across_real_consumers(self):
        config = (LIB / 'core/config.sh').read_text()
        # Execute the real effective-workspace transport block, not a duplicate
        # mapping. CFG values are the reviewed parser output; parsing itself is
        # qualified separately by installer_profile_contract (no package import).
        transport = ('apply_reviewed_workspace() {\n' +
                     config[config.index('    # Workspace CLI contract:'):
                            config.index('    WORKSPACE_AUTO_CREATE_FORK=')] + '\n}\n' +
                     function('core/config.sh', 'expand_tilde_path') + 'apply_reviewed_workspace\n')
        status = '\n'.join(function('modules/' + module + '.sh', cmd) for module, cmd in (
            ('isaaclab', 'cmd_lab'), ('isaaclab_arena', 'cmd_arena'), ('gr00t', 'cmd_gr00t')))
        script = (transport + self.state_seam() + self.audit_seam() + self.drift_seam() +
                  function('core/state.sh', 'plan_workspace_repair') + status +
                  (LIB / 'modules/demos.sh').read_text() + r'''
log_header() { :; }; log_info() { printf '%s\n' "$*"; }
log_step() { :; }; log_success() { :; }; chown() { :; }; run_as_user() { :; }
run_as_user_stdin() { cat > "$1"; }
find_existing_repo() { printf 'FORBIDDEN_DISCOVERY\n' >&2; return 91; }
get_repo_info() { printf 'FORBIDDEN_METADATA\n' >&2; return 91; }
check_fork_sync_status() { printf 'FORBIDDEN_FETCH\n' >&2; return 91; }
resolve_conda_env_path() { printf '%s/Conda Env\n' "$TARGET_HOME"; }
resolve_isaacsim_dir() { printf '%s/Sim Engine\n' "$TARGET_HOME"; }
AUDIT_RESULTS=(); INSTALLS_FOUND=0; UPGRADES_FOUND=0; SATISFIED_COUNT=0
sync_state_ledger || exit $?
audit_repository_seam > "$HOME/audit-paths" || exit $?
audit_workspace_drift > "$HOME/drift-rows" || exit $?
plan_workspace_repair > "$HOME/repair-plan" || exit $?
cmd_lab status > "$HOME/lab-status" || exit $?
cmd_arena status > "$HOME/arena-status" || exit $?
cmd_gr00t status > "$HOME/gr00t-status" || exit $?
install_demos_and_shortcuts || exit $?
''')
        spec = importlib.util.spec_from_file_location('agreement_paths', LIB / 'core/workspace_paths.py')
        assert spec is not None and spec.loader is not None
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        repos = {'isaaclab': 'IsaacLab', 'arena': 'IsaacLab-Arena', 'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot'}
        for layout in ('named', 'flat', 'auto', 'org'):
            with self.subTest(layout=layout):
                name = 'CLI Reviewed Team' if layout == 'named' else ''
                owner = 'ExactOwner' if layout in ('auto', 'org') else ''
                paths = {key: api.resolve_paths(home=str(self.home), root=str(self.workspace), repo=repo,
                                               layout=layout, name=name, configured_owner=owner,
                                               directory_entries={str(self.workspace): []})['destination']
                         for key, repo in repos.items()}
                result = self.shell(script, CFG_WORKSPACE_ROOT='~/Work Space', CFG_WORKSPACE_LAYOUT=layout,
                                    CFG_WORKSPACE_NAME='Profile Team' if layout == 'named' else '',
                                    CFG_WORKSPACE_DEFAULT_OWNER=owner, CLI_WORKSPACE_NAME=name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                ledger = json.loads((self.home / '.isaac-installer/state.json').read_text())
                self.assertEqual({k: v['path'] for k, v in ledger['repositories'].items()}, paths)
                self.assertTrue(all(v['exists'] is False for v in ledger['repositories'].values()))
                self.assertEqual((self.home / 'audit-paths').read_text().splitlines(), list(paths.values())[:3])
                self.assertEqual(json.loads((self.home / 'repair-plan').read_text())['selected_paths'], paths)
                for key, file in [('isaaclab', 'lab-status'), ('arena', 'arena-status'), ('gr00t', 'gr00t-status')]:
                    self.assertIn('at ' + paths[key] + '.', (self.home / file).read_text())
                for row in (self.home / 'drift-rows').read_text().splitlines():
                    repo, _, _, selected, _ = row.split('|')
                    self.assertEqual(selected, paths['isaaclab' if repo == 'IsaacLab' else 'arena'])
                # Read the bound variables by executing only the generated prefix
                # (before its first runtime command). No launch or package import.
                generated = (self.home / '.local/share/isaac-demos/arena-benchmark.sh').read_text()
                prefix = generated.split('if [[', 1)[0]
                observed = subprocess.run(['/bin/bash', '-c', prefix + '\nprintf "%s\\n" "$LAB_DIR" "$ARENA_DIR" "$GR00T_DIR"'],
                                          env=self.env, cwd=self.base, capture_output=True, text=True, timeout=5)
                self.assertEqual(observed.returncode, 0, observed.stderr)
                self.assertEqual(observed.stdout.splitlines(), list(paths.values())[:3])

    def test_legacy_unconfigured_discovery_is_unique_or_refused(self):
        (self.home / 'IsaacLab/.git').mkdir(parents=True)
        values = {'WORKSPACE_DIR': '', 'WORKSPACE_LAYOUT': 'auto', 'WORKSPACE_NAME': ''}
        result = self.shell('resolve_active_repo_dir IsaacLab\n', **values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.home / 'IsaacLab'))
        (self.home / 'projects/IsaacLab/.git').mkdir(parents=True)
        result = self.shell('resolve_active_repo_dir IsaacLab\n', **values)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('ambiguous', result.stderr)

    def test_missing_selected_launcher_refuses_instead_of_using_legacy_checkout(self):
        (self.home / 'IsaacLab').mkdir()
        result = self.generate_launchers()
        self.assertEqual(result.returncode, 0, result.stderr)
        script = self.home / '.local/share/isaac-demos/humanoid-locomotion.sh'
        result = subprocess.run(['/bin/bash', str(script)], env=self.env, cwd=self.base,
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.workspace / 'Reviewed Team/IsaacLab'), result.stdout + result.stderr)

    def test_refused_selection_preserves_fixture_state_and_launchers(self):
        ledger = self.home / '.isaac-installer/state.json'
        ledger.parent.mkdir()
        ledger.write_text('{"foreign": "preserve exactly"}\n')
        before = ledger.read_bytes()
        for body in (self.state_seam() + '\nif sync_state_ledger; then exit 0; else exit $?; fi\n',
                     function('core/state.sh', 'plan_workspace_repair') + '\nplan_workspace_repair\n',
                     self.audit_seam() + '\naudit_repository_seam\n'):
            result = self.shell(body, WORKSPACE_NAME='not/a/name')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertEqual(ledger.read_bytes(), before)
        result = self.generate_launchers(WORKSPACE_NAME='not/a/name')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / '.local').exists())
        self.assertEqual(ledger.read_bytes(), before)

    def test_drift_report_does_not_advertise_automatic_repair(self):
        result = self.shell(function('core/state.sh', 'print_drift_report') + r'''
log_header() { :; }; log_success() { printf '%s\n' "$*"; }
CLR_BOLD=; CLR_RESET=; CLR_GREEN=; CLR_YELLOW=; CLR_DIM=
audit_workspace_drift() { DRIFT_ITEMS=('IsaacLab|REPO_MISSING|None|Selected Path|Synthetic missing checkout'); }
print_drift_report
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unsupported', result.stdout.lower())
        self.assertNotIn('automatically reconcile', result.stdout)


if __name__ == '__main__':
    unittest.main()
