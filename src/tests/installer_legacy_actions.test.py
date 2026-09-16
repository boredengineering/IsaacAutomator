"""Legacy intent only: private profiles, pure APIs, intercepted consumer seams.

Never source installer helpers, run stage checks/installers, or inspect a host.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'isaac-installer/lib/core'
MODULES = CORE.parent / 'modules'


def load(name):
    spec = importlib.util.spec_from_file_location(name, CORE / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREVIEW = load('safe_preview')
PARSER = load('profile_parser')
PATHS = load('workspace_paths')


class LegacyActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-legacy-actions-')
        self.base = Path(self.temp.name)
        self.home = str(self.base / 'target-home')

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, text, *extra):
        args = PREVIEW._arguments(['install', '--dry-run', '--config', str(self.base / 'profile.yaml'), *extra])
        parts = PARSER.parse_profile_text(text, args['workspace_overrides']).decode().split('\0')[:-1]
        return PREVIEW._preview(dict(zip(parts[::2], parts[1::2])), args)

    def test_repository_subactions_use_real_config_and_consumer_values(self):
        text = ('workspace:\n  root: ~/work\n  layout: named\n  name: Team\n'
                'repositories:\n  isaaclab:\n    repo: research/LabFork\n    branch: review\n    tag: v9.2\n'
                '  arena:\n    enabled: true\n  lerobot:\n    enabled: true\n  gr00t:\n    enabled: true\n')
        data = self.preview(text)
        self.assertIn('legacy_action_plan', data, 'stage descriptions are not concrete subactions')
        plan = data['legacy_action_plan']
        actions = {a['id']: a for a in plan['actions']}
        self.assertEqual(plan['home_binding'], 'symbolic; not a detected account')
        self.assertFalse(plan['execution_authorized'])
        # Real flattened config mapping assignments, stripped of all profile I/O.
        cfg = (CORE / 'config.sh').read_text()
        assignments = cfg[cfg.index('    # Repositories'):cfg.index('    # Explicit shared-profile Lab pins')]
        flat = PARSER.parse_profile_text(text).decode().split('\0')[:-1]
        env = {'PATH': '/usr/bin:/bin', **dict(zip(flat[::2], flat[1::2]))}
        cases = [('isaaclab', 'isaaclab.sh', 'ISAACLAB', 'IsaacLab', 'false'),
                 ('arena', 'isaaclab_arena.sh', 'ARENA', 'IsaacLab-Arena', 'true'),
                 ('lerobot', 'physical_ai.sh', 'LEROBOT', 'lerobot', 'false'),
                 ('gr00t', 'gr00t.sh', 'GR00T', 'Isaac-GR00T', 'true')]
        for name, filename, prefix, repo_name, submodules in cases:
            source = (MODULES / filename).read_text()
            # Capture the actual native checkout call's argv; never invoke it.
            call = next(line.strip() for line in source.splitlines()
                        if line.strip().startswith('setup_git_repo_with_fork "${') and '"${git_repo}"' in line)
            declarations = '\n'.join(re.search(r'^    local ' + variable + r'=.*$', source, re.M)[0]
                                     for variable in ('git_repo', 'official_upstream', 'git_branch', 'git_tag'))
            var = {'isaaclab': 'lab_dir', 'arena': 'arena_dir', 'lerobot': 'lerobot_dir', 'gr00t': 'gr00t_dir'}[name]
            target = '/target-home/work/Team/' + repo_name
            script = assignments + '\nsetup_git_repo_with_fork() { printf "%s\\0" "$@"; }\nconsumer() {\n' + declarations + '\nlocal ' + var + '="$1"\n' + call + '\n}\nconsumer "$1"\n'
            result = subprocess.run(['/bin/bash', '-c', script, 'seam', target], env=env,
                                    cwd=self.base, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = result.stdout.decode().split('\0')[:-1]
            action = actions['repository.' + name]
            desired = action['desired']
            self.assertEqual([action['target'], desired['repository'], desired['upstream'], desired['branch'], desired['tag'], str(desired['recursive']).lower()], argv)
            self.assertEqual(desired['ref'], desired['tag'] or desired['branch'])
            self.assertEqual(action['target'], PATHS.resolve_paths(home='/target-home', repo=repo_name,
                             root='~/work', layout='named', name='Team', slug=desired['repository'])['destination'])
            self.assertFalse(action['execution_supported'])
            self.assertTrue(action['effects'])
            self.assertTrue(action['approval_required'])
            self.assertTrue(action['blockers'])
        self.assertEqual(actions['repository.isaaclab']['desired']['url'], 'https://github.com/research/LabFork.git')
        self.assertEqual(actions['workspace.group']['target'], '/target-home/work/Team')
        self.assertEqual(actions['repository.lerobot']['desired']['tag'], 'v0.4.3')

    def test_sim_runtime_and_configuration_targets_match_native_value_seams(self):
        text = ('workspace:\n  root: ~/code\n  layout: flat\n'
                'simulation:\n  isaacsim:\n    install_dir: ~/sim-custom\n    version: 5.1.0\n'
                '    url: https://artifacts.example.invalid/sim.zip\n    sha256: ' + 'a' * 64 + '\n'
                'runtimes:\n  lab:\n    environment: isaaclab\n    python: 3.10.14\n'
                '    torch: 2.5.1+cu124\n    torchvision: 0.20.1+cu124\n    cuda_runtime: "12.4"\n')
        actions = {a['id']: a for a in self.preview(text)['legacy_action_plan']['actions']}
        self.assertIn('sim.archive', actions)
        archive = actions['sim.archive']
        self.assertEqual(archive['target'], '/target-home/sim-custom')
        self.assertEqual(archive['desired']['version'], '5.1.0')
        self.assertEqual(archive['desired']['url'], 'https://artifacts.example.invalid/sim.zip')
        self.assertEqual(archive['desired']['sha256'], 'a' * 64)
        self.assertEqual(actions['sim.eula']['target'], archive['target'] + '/.eula_accepted')
        self.assertEqual(actions['lab.sim_link']['desired']['source'], archive['target'])
        self.assertEqual(actions['lab.sim_link']['target'], '/target-home/code/IsaacLab/_isaac_sim')
        self.assertEqual(actions['arena.config']['target'], '/target-home/code/IsaacLab-Arena/.env')
        self.assertEqual(actions['runtime.gr00t']['target'], '/target-home/code/Isaac-GR00T/.venv')
        runtime = actions['runtime.lab']
        self.assertIsNone(runtime['target'], 'Conda discovery must not be replaced with a guessed prefix')
        self.assertEqual(runtime['desired']['python'], '3.10.14')
        self.assertEqual(runtime['desired']['torch'], '2.5.1+cu124')
        self.assertEqual(runtime['desired']['torchvision'], '0.20.1+cu124')
        self.assertEqual(runtime['desired']['wheel_index'], 'https://download.pytorch.org/whl/cu124')
        self.assertEqual(runtime['desired']['environment'], 'isaaclab')
        # Exercise native config.sh's pure assignments, not load_config_profile.
        source = (CORE / 'config.sh').read_text()
        assignments = source[source.index('    # Explicit shared-profile Lab pins'):source.index('\n}\n', source.index('    # Explicit shared-profile Lab pins'))]
        flat = PARSER.parse_profile_text(text).decode().split('\0')[:-1]
        env = {'PATH': '/usr/bin:/bin', 'TARGET_HOME': '/target-home', **dict(zip(flat[::2], flat[1::2]))}
        shell = 'expand_tilde_path() { printf "%s" "${1/#\\~/$TARGET_HOME}"; }\n' + assignments
        shell += '\nprintf "%s\\0" "$ISAACSIM_DIR" "$ISAACSIM_VERSION" "$ISAACSIM_ARCHIVE_URL" "$ISAACSIM_ARCHIVE_SHA256" "$CONDA_ENV_NAME" "$LAB_PYTHON_VERSION" "$LAB_TORCH_VERSION" "$LAB_TORCHVISION_VERSION"\n'
        result = subprocess.run(['/bin/bash', '-c', shell], env=env, cwd=self.base, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().split('\0')[:-1], [archive['target'], archive['desired']['version'], archive['desired']['url'], archive['desired']['sha256'], *[runtime['desired'][k] for k in ('environment', 'python', 'torch', 'torchvision')]])
        conda = (MODULES / 'conda.sh').read_text()
        seam = conda[conda.index('resolve_target_python_version() {'):conda.index('resolve_conda_bin() {')]
        for version, expected in [('5.1.0', '3.10'), ('6.0.1', '3.12')]:
            plan = self.preview('simulation:\n  isaacsim:\n    version: ' + version + '\n')['legacy_action_plan']
            byid = {a['id']: a for a in plan['actions']}
            result = subprocess.run(['/bin/bash', '-c', seam + '\nresolve_target_python_version'], env={'PATH': '/usr/bin:/bin', 'CFG_SIMULATION_ISAACSIM_VERSION': version}, cwd=self.base, capture_output=True, text=True, timeout=5)
            self.assertEqual(byid['runtime.lab']['desired']['python'], result.stdout.strip())
            self.assertEqual(result.stdout.strip(), expected)
            self.assertIsNone(byid['sim.archive']['target'])
            self.assertIn('existing', ' '.join(byid['sim.archive']['blockers']))

    def test_selected_and_excluded_effects_streaming_and_unmapped_fields_are_honest(self):
        text = ('workspace:\n  root: ~/code\n  layout: flat\n'
                'repositories:\n  arena:\n    enabled: false\n    path: ~/NOT_CONSUMED\n'
                'streaming:\n  provider: sunshine\n'
                'devtools:\n  vscode: false\n  cloud_clis:\n    aws: true\n'
                'hardware:\n  enable_nvme_storage_tools: false\n'
                'teleoperation:\n  ftdi_1ms_latency_rule: false\n  realsense_cameras: true\n')
        data = self.preview(text, '--only', 'arena,gr00t,devtools,hardware_teleop,display', '--without', 'gr00t')
        plan = data['legacy_action_plan']
        byid = {a['id']: a for a in plan['actions']}
        self.assertIn('streaming.provider', byid)
        self.assertEqual(byid['streaming.provider']['status'], 'excluded')
        self.assertEqual(byid['streaming.provider']['desired']['requested_provider'], 'sunshine')
        self.assertEqual(byid['streaming.provider']['desired']['effective_provider'], 'none')
        self.assertIn('not consumed', ' '.join(byid['streaming.provider']['blockers']))
        stages = {row['stage']: row for row in data['stages']}
        self.assertEqual(stages['arena']['status'], 'unknown')
        self.assertEqual(stages['gr00t']['status'], 'excluded')
        self.assertEqual(byid['repository.arena']['target'], '/target-home/code/IsaacLab-Arena')
        self.assertIn('CFG_REPOSITORIES_ARENA_PATH', plan['unmapped_fields'])
        self.assertEqual(byid['tool.vscode']['status'], 'excluded')
        self.assertEqual(byid['tool.aws']['status'], 'unknown')
        self.assertEqual(byid['tool.storage']['status'], 'unknown', 'native install ignores descriptive NVMe toggle')
        self.assertEqual(byid['hardware.ftdi']['status'], 'excluded')
        self.assertEqual(byid['hardware.realsense']['status'], 'unknown')
        self.assertEqual(byid['display.xauthority']['target'], '/target-home/.Xauthority')
        self.assertIn('0666', ' '.join(byid['display.xauthority']['effects']))
        self.assertIsNone(byid['driver.packages']['desired']['packages'])
        self.assertIsNone(byid['tool.aws']['desired']['packages'])
        for stage in stages:
            self.assertTrue(any(a['stage'] == stage for a in plan['actions']), stage)
        for action in plan['actions']:
            if action['stage'] in stages and stages[action['stage']]['status'] == 'excluded':
                self.assertFalse(action['selected'], action['id'])
            self.assertFalse(action['execution_authorized'])
            self.assertFalse(action['execution_supported'])
            self.assertTrue(action['blockers'])
        pinned = {a['id']: a for a in self.preview('runtimes:\n  lab:\n    environment: isaaclab\n')['legacy_action_plan']['actions']}
        self.assertEqual(pinned['runtime.lab.activate']['status'], 'unknown', 'pin-aware branch still configures hooks')
        self.assertEqual(pinned['python.miniforge']['status'], 'excluded')
        self.assertEqual(pinned['python.legacy_cleanup']['status'], 'excluded')

    def cli_fixture(self):
        installer = self.base / 'installer'
        core = installer / 'lib/core'
        core.mkdir(parents=True)
        (installer / 'bin').mkdir()
        (installer / 'config').mkdir()
        source = (ROOT / 'isaac-installer/bin/isaac-installer').read_text()
        (installer / 'bin/isaac-installer').write_text(source.split('# Source Core Libraries', 1)[0] + '\nprintf "LEGACY_BODY_REACHED\\n" >&2\nexit 99\n')
        for name in ('safe_preview.py', 'preview_sandbox.py', 'profile_parser.py', 'workspace_paths.py', 'legacy_action_plan.py'):
            shutil.copyfile(CORE / name, core / name)
        for name in ('default-profile.yaml', 'minimal-headless.yaml', 'full-ecosystem.yaml'):
            # Data-only private preset fixtures. The shipped default/full contain
            # build_command and must retain their existing safety refusal.
            preset = (ROOT / 'isaac-installer/config' / name).read_text()
            preset = '\n'.join(line for line in preset.splitlines() if 'build_command:' not in line) + '\n'
            (installer / 'config' / name).write_text(preset)
        profile = self.base / 'profile.yaml'
        profile.write_text('workspace:\n  root: ~/code\n  layout: named\n  name: Private\nrepositories:\n  arena:\n    enabled: true\n')
        # The fixture stays private to the unprivileged preview identity.
        if os.geteuid() == 0:
            os.chown(self.base, 65534, 65534)
        self.base.chmod(0o700)
        return installer, profile

    def cli(self, installer, *args):
        def drop():
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
        return subprocess.run(['/bin/bash', str(installer / 'bin/isaac-installer'), *args],
                              cwd=self.base, env={'PATH': '/usr/bin:/bin', 'HOME': '/NEVER_USE_AMBIENT_HOME'},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, preexec_fn=drop, timeout=15)

    def test_confined_cli_config_and_presets_emit_concrete_text_and_json_without_mutation(self):
        installer, profile = self.cli_fixture()
        before = {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        text = self.cli(installer, 'install', '--dry-run', '--config', str(profile))
        self.assertEqual(text.returncode, 2, text.stderr)
        self.assertIn('repository.arena', text.stdout)
        self.assertIn('/target-home/code/Private/IsaacLab-Arena', text.stdout)
        self.assertIn('approval_required', text.stdout)
        self.assertIn('blockers', text.stdout)
        for source in [('--config', str(profile)), ('--profile', 'default'), ('--profile', 'minimal'), ('--profile', 'full')]:
            result = self.cli(installer, 'install', '--dry-run', *source, '--json')
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn('LEGACY_BODY_REACHED', result.stderr)
            data = json.loads(result.stdout)
            self.assertFalse(data['complete'])
            self.assertEqual(len(data['stages']), 12)
            self.assertIn('legacy_action_plan', data)
            self.assertGreater(len(data['legacy_action_plan']['actions']), len(data['stages']))
            self.assertNotIn('NEVER_USE_AMBIENT_HOME', result.stdout)
            self.assertIn('profile-derived', ' '.join(data['limitations']))
        after = {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_unresolved_targets_and_pin_branch_do_not_invent_consumer_values(self):
        data = self.preview('workspace:\n  root: ~/code\n  layout: auto\nruntimes:\n  lab:\n    environment: isaaclab\n')
        actions = {a['id']: a for a in data['legacy_action_plan']['actions']}
        self.assertIsNone(actions['runtime.lab']['desired']['python'], 'pin-aware create refuses missing Python, not the auto default')
        self.assertIsNone(actions['repository.isaaclab']['target'])
        self.assertEqual(actions['repository.isaaclab']['path_resolution']['candidate_destination'], '/target-home/code/IsaacLab')
        data = self.preview('runtimes:\n  lab:\n    packages: example==1.2\n')
        runtime = next(a for a in data['legacy_action_plan']['actions'] if a['id'] == 'runtime.lab')
        self.assertFalse(runtime['desired']['pin_aware'])
        self.assertIn('packages-only', ' '.join(runtime['blockers']))
        data = self.preview('runtimes:\n  lab:\n    environment: custom\n')
        runtime = next(a for a in data['legacy_action_plan']['actions'] if a['id'] == 'runtime.lab')
        self.assertIn('refuses', ' '.join(runtime['blockers']))
        # The new planner itself has no I/O after imports. No environment lookup,
        # target inspection, subprocess or socket can hide behind the dry-run.
        planner = PREVIEW._trusted_module('legacy_action_plan')
        workspace = data['workspace_intent']
        from contextlib import ExitStack
        with ExitStack() as stack:
            for operation in ('builtins.open', 'os.open', 'os.stat', 'os.lstat', 'os.scandir', 'os.listdir', 'os.getenv', 'subprocess.run', 'socket.socket'):
                stack.enter_context(patch(operation, side_effect=AssertionError('planner attempted ' + operation)))
            plan = planner.build_legacy_action_plan({}, data['stages'], workspace, target_home=self.home)
        self.assertEqual(plan['target_home'], self.home)
        self.assertFalse(plan['execution_authorized'])
        for action in plan['actions']:
            self.assertNotIn('/root/', json.dumps(action))

    def test_workspace_and_repository_side_effect_targets_follow_native_contract(self):
        data = self.preview('workspace:\n  root: ~/work\n  layout: flat\n  auto_create_fork: false\n  auto_register_github_desktop: false\nrepositories:\n  isaaclab:\n    repo: team/lab\n')
        actions = {a['id']: a for a in data['legacy_action_plan']['actions']}
        self.assertIn('repository.isaaclab.desktop', actions)
        self.assertEqual(actions['repository.isaaclab.desktop']['status'], 'excluded')
        self.assertEqual(actions['repository.isaaclab.fork']['status'], 'excluded')
        self.assertIn('fork fallback', ' '.join(actions['repository.isaaclab']['blockers']))
        source = (MODULES / 'system_prereqs.sh').read_text()
        array = source[source.index('    local dirs=('):source.index('\n    for d in', source.index('    local dirs=('))]
        script = 'consumer() { local user_home="$1";\n' + array + '\nprintf "%s\\0" "${dirs[@]}"; }\nconsumer /target-home\n'
        result = subprocess.run(['/bin/bash', '-c', script], cwd=self.base, env={'PATH': '/usr/bin:/bin'}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = result.stdout.decode().split('\0')[:-1]
        actual = [a['target'] for a in actions.values() if a['id'].startswith('prereqs.scaffold.')]
        self.assertEqual(actual, expected)
        self.assertTrue(all('recursively' in ' '.join(a['effects']) for a in actions.values() if a['id'].startswith('prereqs.scaffold.')))
        # Capture native resolve_repo_dest_path -> shared pure resolver argv.
        native = (CORE / 'git_workspace.sh').read_text()
        function = re.search(r'^resolve_repo_dest_path\(\) \{.*?^\}', native, re.M | re.S)[0]
        module = (MODULES / 'isaaclab.sh').read_text()
        module_resolver = re.search(r'^resolve_isaaclab_dir\(\) \{.*?^\}', module, re.M | re.S)[0]
        script = ('detect_target_user() { :; }\nresolve_default_workspace_dir() { printf "%s" "$WORKSPACE_DIR"; }\n'
                  'python3() { if [[ "$3" == settings ]]; then return 0; fi; printf "%s\\0" "${@:4}"; }\n' + function + '\n' + module_resolver + '\nresolve_isaaclab_dir\n')
        result = subprocess.run(['/bin/bash', '-c', script], cwd=self.base,
            env={'PATH': '/usr/bin:/bin', 'TARGET_HOME': '/target-home', 'WORKSPACE_DIR': '/target-home/work', 'WORKSPACE_LAYOUT': 'flat', 'ISAACLAB_REPO': 'team/lab'}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = ('home', 'repo', 'slug', 'path_override', 'root', 'layout', 'name', 'configured_owner')
        args = dict(zip(fields, result.stdout.decode().split('\0')[:-1]))
        self.assertEqual(PATHS.resolve_paths(**args)['destination'], actions['repository.isaaclab']['target'])
        all_excluded = self.preview('workspace:\n  root: ~/code\n  layout: flat\n', '--without', ','.join(dict(PREVIEW.STAGES)))['legacy_action_plan']
        self.assertFalse(any(a['selected'] for a in all_excluded['actions']))

    def test_inactive_preset_build_examples_are_redacted_not_executed(self):
        installer, profile = self.cli_fixture()
        for alias, filename in [('default', 'default-profile.yaml'), ('full', 'full-ecosystem.yaml')]:
            shutil.copyfile(ROOT / 'isaac-installer/config' / filename, installer / 'config' / filename)
            result = self.cli(installer, 'install', '--dry-run', '--profile', alias, '--json')
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stdout, 'Inactive build example must not block the entire public preset preview')
            data = json.loads(result.stdout)
            self.assertIn('legacy_action_plan', data)
            self.assertEqual(data['inactive_executable_fields'], ['CFG_SIMULATION_ISAACSIM_CUSTOM_BUILD_BUILD_COMMAND'])
            self.assertNotIn('./build.sh', result.stderr + result.stdout)
        text_result = self.cli(installer, 'install', '--dry-run', '--profile', 'default')
        self.assertEqual(text_result.returncode, 2)
        self.assertIn('Inactive executable example omitted', text_result.stdout)
        self.assertNotIn('./build.sh', text_result.stdout + text_result.stderr)
        for source_type, enabled in [('custom_build', 'false'), ('standalone', 'true')]:
            profile.write_text('simulation:\n  isaacsim:\n    source_type: ' + source_type +
                '\n    custom_build:\n      enabled: ' + enabled + '\n      build_command: PRIVATE_PAYLOAD\n')
            result = self.cli(installer, 'install', '--dry-run', '--config', str(profile), '--json')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('PRIVATE_PAYLOAD', result.stdout + result.stderr)
        for content in ['hooks:\n  pre: PRIVATE_PAYLOAD\n', 'simulation:\n  isaacsim:\n    install_dir: ~/../outside\n']:
            profile.write_text(content)
            result = self.cli(installer, 'install', '--dry-run', '--config', str(profile), '--json')
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('PRIVATE_PAYLOAD', result.stdout + result.stderr)
        result = self.cli(installer, 'install', '--dry-run', '--config', '/DO_NOT_READ', '--stream', 'sunshine')
        self.assertEqual(result.returncode, 2)
        self.assertIn('no profile was read', result.stderr)
        if os.geteuid() == 0:
            (installer / 'lib/core/legacy_action_plan.py').write_text('raise RuntimeError("PLANNER_IMPORTED_BEFORE_GUARD")\n')
            result = subprocess.run(['/bin/bash', str(installer / 'bin/isaac-installer'), 'install', '--dry-run', '--config', '/DO_NOT_READ'],
                                    cwd=self.base, env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 77)
            self.assertIn('root', result.stderr)
            self.assertNotIn('PLANNER_IMPORTED_BEFORE_GUARD', result.stderr)

    def test_custom_sim_and_fork_flags_describe_actual_native_branching(self):
        def actions(text):
            return {a['id']: a for a in self.preview(text)['legacy_action_plan']['actions']}
        custom = actions('simulation:\n  isaacsim:\n    source_type: custom_build\n    custom_build:\n      source_path: ~/custom-sim\n')
        self.assertEqual(custom['sim.post_install']['status'], 'excluded')
        self.assertEqual(custom['sim.archive']['status'], 'excluded')
        self.assertEqual(custom['sim.custom_source']['target'], '/target-home/custom-sim')
        fallback = actions('simulation:\n  isaacsim:\n    source_type: omniverse_launcher\n')
        self.assertEqual(fallback['sim.archive']['status'], 'unknown', 'native non-custom source falls through to standalone')
        disabled = actions('workspace:\n  auto_create_fork: false\nrepositories:\n  isaaclab:\n    repo: team/lab\n')
        self.assertFalse(disabled['repository.isaaclab.fork']['desired']['auto_create'])


if __name__ == '__main__':
    unittest.main()
