#!/usr/bin/env python3
"""Offline execution of real installer functions and rendered role commands.

Only disposable executables handle package/native calls. Metadata checks execute
real checker code with stdlib metadata/platform doubles, never robotics imports.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'isaac-installer/lib/modules'
ROLES = ROOT / 'src/ansible/roles'
JINJA = Environment(undefined=StrictUndefined)
JINJA.filters['quote'] = shlex.quote
JINJA.filters['bool'] = lambda x: str(x).lower() in ('true', '1', 'yes')

RECORDER = r'''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
constraint = os.environ.get('PIP_CONSTRAINT')
row = dict(name=name, argv=args, prefix=os.environ.get('CONDA_PREFIX'),
           pip=constraint, uv=os.environ.get('UV_CONSTRAINT'))
if constraint:
    row['constraints'] = Path(constraint).read_text()
    row['mode'] = Path(constraint).stat().st_mode & 0o777
with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(row)+'\n')
if name == 'python' and '-c' in args:
    import platform, importlib.metadata
    from unittest.mock import patch
    code = args[args.index('-c')+1]
    sys.argv = ['-c'] + args[args.index('-c')+2:]
    versions = {'torch': '2.10.0+cu128', 'torchvision': '0.25.0+cu128'}
    if Path(os.environ['DRIFT_FILE']).exists():
        versions[os.environ.get('DRIFT_PACKAGE','torch')] = '9.9.9'
    actual_python = os.environ.get('PY_VERSION','3.11.9')
    if Path(os.environ['DRIFT_FILE']).exists() and os.environ.get('DRIFT_PACKAGE') == 'python':
        actual_python = '3.11.10'
    with patch('platform.python_version', return_value=actual_python), patch('importlib.metadata.version', side_effect=lambda n: versions[n]), patch.object(sys, 'prefix', os.environ.get('ACTUAL_PREFIX', os.environ['ENV_PATH'])):
        exec(compile(code, '<actual-runtime-check>', 'exec'))
    sys.exit(0)
if name == 'conda':
    assert args[:2] == ['run', '--prefix'], args
    os.environ['CONDA_PREFIX'] = args[2]
    os.execvpe(args[3], args[3:], os.environ)
if os.environ.get('FAIL_STAGE') == name: sys.exit(43)
if name == os.environ.get('DRIFT_STAGE'): Path(os.environ['DRIFT_FILE']).touch()
'''


class PinConformance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='isaac-pin-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'Home Case Spaces'
        self.bin = self.root / 'fakebin'
        self.env_path = self.home / 'miniconda3/envs/isaaclab'
        self.lab = self.home / 'Lab Case Spaces'
        self.arena = self.home / 'Arena Case Spaces'
        self.sim = self.home / 'Sim Case Spaces'
        for p in (self.bin, self.env_path / 'bin', self.lab / 'source/isaaclab', self.arena, self.sim):
            p.mkdir(parents=True)
        self.log = self.root / 'calls.jsonl'
        for p in (self.env_path / 'bin/python', self.home / 'miniconda3/bin/conda', self.lab / 'isaaclab.sh', self.bin / 'uv', self.bin / 'chown'):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(RECORDER)
            p.chmod(0o755)
        # Preserve real run_as_user while blocking login startup and privilege changes.
        for name, code in {'bash': '#!/bin/bash\n[[ "$1" == -l ]] && shift\nexec /bin/bash "$@"\n', 'sudo': '#!/bin/bash\n[[ "$1" == -H && "$2" == -u ]] || exit 98\nshift 3\n[[ "$1" == -- ]] && shift\nif [[ "$1" == tee && "$2" != "$HOME/"* ]]; then exit 97; fi\nexec "$@"\n'}.items():
            (self.bin / name).write_text(code)
            (self.bin / name).chmod(0o755)
        self.environment = dict(PATH=f'{self.bin}:/usr/bin:/bin', HOME=str(self.home), USER='fixture',
            CALL_LOG=str(self.log), ENV_PATH=str(self.env_path), DRIFT_FILE=str(self.root / 'drift'),
            LAB_PYTHON_VERSION='3.11', LAB_TORCH_VERSION='2.10.0+cu128',
            LAB_TORCHVISION_VERSION='0.25.0+cu128', LAB_CUDA_RUNTIME='12.8')

    def shell(self, body='install_isaac_lab'):
        q = shlex.quote
        script = f'''
source {q(str(MODULES.parent / 'core/detect.sh'))}
source {q(str(MODULES / 'conda.sh'))}
source {q(str(MODULES / 'isaaclab.sh'))}
source {q(str(MODULES / 'isaaclab_arena.sh'))}
TARGET_HOME=$HOME; TARGET_USER=fixture
ISAACLAB_DIR={q(str(self.lab))}; ISAACSIM_DIR={q(str(self.sim))}; ARENA_DIR={q(str(self.arena))}
log_step() {{ :; }}; log_info() {{ :; }}; log_success() {{ :; }}; log_warn() {{ :; }}
log_error() {{ printf '%s\\n' "$*" >&2; }}; log_fatal() {{ log_error "$@"; return 1; }}
resolve_repo_dest_path() {{ printf '%s\\n' "$3"; }}
setup_git_repo_with_fork() {{ printf 'setup\\n' >> "$HOME/events"; return "${{FAIL_SETUP:-0}}"; }}
deploy_isaacsim_conda_bridge() {{ printf 'bridge\\n' >> "$HOME/events"; }}
register_github_desktop_repo() {{ printf 'registered\\n' >> "$HOME/events"; }}
{body}
'''
        return subprocess.run(['/bin/bash', '-c', script], cwd=self.root, text=True, capture_output=True, env=self.environment)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_local_native_and_extensions_keep_pins_through_final_check(self):
        result = self.shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        native = next(x for x in calls if x['name'] == 'isaaclab.sh')
        self.assertIsNotNone(native['pip'], 'native Lab install lost selected constraints')
        self.assertEqual(native['pip'], native['uv'])
        self.assertEqual(native['prefix'], str(self.env_path))
        self.assertIn('torch==2.10.0+cu128', native['constraints'])
        self.assertIn('torchvision==0.25.0+cu128', native['constraints'])
        self.assertEqual(native['mode'], 0o600)
        self.assertEqual(native['argv'], ['-i'])
        self.assertEqual(calls[-1]['name'], 'python')
        self.assertIn('-c', calls[-1]['argv'])
        self.assertFalse(Path(native['pip']).exists(), 'private constraints must be cleaned')
    def test_local_arena_finishes_with_metadata_check(self):
        (self.arena / '.env').write_text('USER_DATA=keep\n')
        result = self.shell('install_isaaclab_arena')
        self.assertEqual(result.returncode, 0, result.stderr)
        installs = [x for x in self.calls() if x['name'] == 'python' and x['argv'][:3] == ['-m', 'pip', 'install']]
        self.assertEqual(len(installs), 2, self.calls())
        for row in installs:
            self.assertIsNotNone(row['pip'])
            self.assertEqual(row['pip'], row['uv'])
        self.assertIn(str(self.arena), installs[0]['argv'])
        self.assertIn('pinocchio', installs[1]['argv'])
        self.assertIn('-c', self.calls()[-1]['argv'])
        self.assertEqual((self.arena / '.env').read_text(), 'USER_DATA=keep\n')
    def test_existing_checkout_cannot_skip_pin_conformance(self):
        (self.lab / '_isaac_sim').symlink_to(self.sim)
        (self.arena / '.git').mkdir()
        for check in ('check_isaac_lab', 'check_isaaclab_arena'):
            result = self.shell(f'if {check}; then exit 99; fi')
            self.assertEqual(result.returncode, 0, check)
    def test_native_argv_seam_preserves_home_and_repo_quotes(self):
        old_home = self.home
        self.home = self.root / "Home ' Literal $(touch DO_NOT_CREATE)"
        old_home.rename(self.home)
        for attr in ('env_path', 'lab', 'arena', 'sim'):
            setattr(self, attr, self.home / getattr(self, attr).relative_to(old_home))
        self.environment.update(HOME=str(self.home), ENV_PATH=str(self.env_path))
        result = self.shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        native = next(x for x in self.calls() if x['name'] == 'isaaclab.sh')
        self.assertEqual(native['prefix'], str(self.env_path))
        self.assertFalse((ROOT / 'DO_NOT_CREATE').exists())
    def cloud(self, kind='lab'):
        template = ROLES / 'isaaclab-source/templates/profile-lab-install.sh.j2'
        self.assertTrue(template.exists(), 'cloud source role has no constrained native pipeline')
        directory = self.root / 'Private Cloud Helper'
        directory.mkdir(exist_ok=True)
        for name in ('conda.sh', 'isaaclab.sh'):
            (directory / name).write_text((MODULES / name).read_text())
        variables = dict(profile_lab_helper_dir={'path': str(directory)}, ansible_user='fixture',
            miniconda_install_dir=str(self.home / 'miniconda3'), conda_env_name='isaaclab',
            conda_python_version=self.environment['LAB_PYTHON_VERSION'],
            profile_lab_torch=self.environment.get('LAB_TORCH_VERSION', ''),
            profile_lab_torchvision=self.environment.get('LAB_TORCHVISION_VERSION', ''),
            isaaclab_dir=str(self.lab), isaaclab_arena_dir=str(self.arena),
            profile_lab_install_kind=kind)
        script = directory / 'install.sh'
        script.write_text(JINJA.from_string(template.read_text()).render(**variables))
        tasks = yaml.safe_load((ROLES / 'isaaclab-source/tasks/pinned.yml').read_text())
        block = next(t['block'] for t in tasks if 'block' in t)
        command = next(t for t in block if t.get('name') == 'Run constrained Lab dependency pipeline')
        argv = [JINJA.from_string(a).render(**variables) for a in command['ansible.builtin.command']['argv']]
        return subprocess.run(argv, cwd=self.root, text=True, capture_output=True, env=self.environment)

    def test_cloud_runs_actual_constrained_native_command(self):
        result = self.cloud()
        self.assertEqual(result.returncode, 0, result.stderr)
        native = next(x for x in self.calls() if x['name'] == 'isaaclab.sh')
        self.assertEqual(native['prefix'], str(self.env_path))
        self.assertEqual(native['pip'], native['uv'])
        self.assertIn('torch==2.10.0+cu128', native['constraints'])
        self.assertIn('-c', self.calls()[-1]['argv'])
    def test_cloud_roles_dispatch_pins_without_legacy_fallthrough(self):
        for role, legacy_names in (
            ('isaaclab-source', ['Install Isaac Lab into conda environment', 'Install Isaac Lab standalone (fallback)']),
            ('isaaclab-arena-source', ['Install IsaacLab-Arena in editable mode', 'Install Pinocchio, Pink WBC, and QP Solvers for Locomanipulation'])):
            items = yaml.safe_load((ROLES / role / 'tasks/install.yml').read_text())
            selected = next((t for t in items if t.get('name') == 'Install source dependencies with selected Lab pins'), None)
            self.assertIsNotNone(selected, role)
            context = dict(profile_lab_torch='2.10.0+cu128', profile_lab_pins_selected=True,
                isaaclab_install_needed=True, isaaclab_env_check={'stat': {'exists': True}}, isaaclab_arena_needs_install=True)
            def applies(task, variables):
                conditions = task.get('when', [])
                if isinstance(conditions, str): conditions = [conditions]
                return all(JINJA.compile_expression(c)(**variables) for c in conditions)
            self.assertTrue(applies(selected, context))
            for name in legacy_names:
                task = next(t for t in items if t.get('name') == name)
                self.assertFalse(applies(task, context), name)
            context.update(profile_lab_pins_selected=False)
            self.assertFalse(applies(selected, context))
    def test_failed_native_or_extension_install_cannot_report_success(self):
        for stage in ('isaaclab.sh', 'python'):
            with self.subTest(stage=stage):
                self.environment['FAIL_STAGE'] = stage
                self.log.unlink(missing_ok=True)
                result = self.shell()
                self.assertEqual(result.returncode, 43, result.stderr)
                self.assertNotIn('registered', (self.home / 'events').read_text())
                for row in self.calls():
                    if row['pip']:
                        self.assertFalse(Path(row['pip']).exists())

    def test_final_metadata_rejects_drift_locally_and_in_cloud(self):
        for cloud in (False, True):
            for package in ('torch', 'torchvision'):
                with self.subTest(cloud=cloud, package=package):
                    Path(self.environment['DRIFT_FILE']).unlink(missing_ok=True)
                    self.environment.update(DRIFT_STAGE='isaaclab.sh', DRIFT_PACKAGE=package)
                    result = self.cloud() if cloud else self.shell()
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertIn('metadata does not match', result.stderr)

    def test_arena_failure_and_drift_are_not_swallowed(self):
        (self.arena / '.env').write_text('keep')
        for cloud in (False, True):
            for setting in ('FAIL_STAGE', 'DRIFT_STAGE'):
                with self.subTest(cloud=cloud, setting=setting):
                    Path(self.environment['DRIFT_FILE']).unlink(missing_ok=True)
                    self.environment.pop('FAIL_STAGE', None)
                    self.environment.pop('DRIFT_STAGE', None)
                    self.environment[setting] = 'python'
                    result = self.cloud('arena') if cloud else self.shell('install_isaaclab_arena')
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((self.arena / '.env').read_text(), 'keep')

    def test_clone_failure_stops_before_links_and_dependencies(self):
        self.environment['FAIL_SETUP'] = '41'
        for body in ('install_isaac_lab', 'install_isaaclab_arena'):
            result = self.shell(body)
            self.assertEqual(result.returncode, 41, result.stderr)
        self.assertFalse((self.lab / '_isaac_sim').exists())
        self.assertFalse((self.arena / '.env').exists())
        self.assertFalse(any(x['name'] in ('isaaclab.sh', 'chown') or '-m' in x['argv'] for x in self.calls()))

    def test_selected_environment_and_python_mismatch_stop_before_setup(self):
        for variable, value in (('ACTUAL_PREFIX', '/unrelated/environment'), ('PY_VERSION', '3.12.1')):
            with self.subTest(variable=variable):
                self.environment[variable] = value
                self.assertNotEqual(self.shell().returncode, 0)
                self.assertFalse((self.home / 'events').exists())
                self.environment.pop(variable)
        result = self.shell('CONDA_ENV_NAME=OtherCase; install_isaac_lab')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / 'events').exists())

    def test_missing_conda_is_explicit_prerequisite_not_bootstrap(self):
        (self.home / 'miniconda3/bin/conda').unlink()
        result = self.shell()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires an existing', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_unspecified_vision_is_frozen_not_guessed_and_drift_rejected(self):
        self.environment.pop('LAB_TORCHVISION_VERSION')
        self.environment.update(DRIFT_STAGE='isaaclab.sh', DRIFT_PACKAGE='torchvision')
        result = self.shell()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('runtime changed', result.stderr)

    def test_actual_public_profile_runtime_is_read_not_invented(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from src.python.workstation_profile import resolve_profile
        runtime = resolve_profile('default')['profile']['runtimes']['lab']
        for key, var in (('python', 'LAB_PYTHON_VERSION'), ('torch', 'LAB_TORCH_VERSION'), ('torchvision', 'LAB_TORCHVISION_VERSION')):
            self.environment[var] = runtime.get(key) or ''
        self.environment['PY_VERSION'] = runtime['python'] + ('.9' if runtime['python'].count('.') == 1 else '')
        result = self.shell()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_pins_retains_legacy_install_branch(self):
        for key in list(self.environment):
            if key.startswith('LAB_'): self.environment.pop(key)
        result = self.shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('bridge', (self.home / 'events').read_text())
        self.assertTrue(any(x['name'] == 'uv' and not x['pip'] for x in self.calls()))
    def test_cloud_arena_clone_uses_literal_profile_paths(self):
        target = self.home / "Arena ' $(touch MUST_NOT_EXECUTE)"
        items = yaml.safe_load((ROLES / 'isaaclab-arena-source/tasks/install.yml').read_text())
        clone = next(t for t in items if t.get('name') == 'Clone Isaac Lab Arena repository')
        (self.bin / 'git').write_text(RECORDER)
        (self.bin / 'git').chmod(0o755)
        variables = dict(isaaclab_arena_dir=str(target), isaaclab_arena_git_repo='https://github.com/isaac-sim/IsaacLab-Arena.git', isaaclab_arena_git_checkpoint='release/0.3.0-prerelease')
        result = subprocess.run(['/bin/bash', '-c', JINJA.from_string(clone['shell']).render(**variables)],
            cwd=self.root, env=self.environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'MUST_NOT_EXECUTE').exists())
        self.assertEqual(self.calls()[-1]['argv'][-1], str(target))
    def test_cloud_lab_tag_probe_keeps_profile_path_literal(self):
        target = self.home / 'Lab $(touch MUST_NOT_EXECUTE)'
        items = yaml.safe_load((ROLES / 'isaaclab-source/tasks/install.yml').read_text())
        task = next(t for t in items if t.get('name') == 'Check existing install tag')
        variables = {'isaaclab_dir': str(target)}
        if 'shell' in task:
            (self.bin / 'cat').write_text(RECORDER)
            (self.bin / 'cat').chmod(0o755)
            argv = ['/bin/bash', '-c', JINJA.from_string(task['shell']).render(**variables)]
        else:
            argv = [JINJA.from_string(a).render(**variables) for a in task['ansible.builtin.command']['argv']]
            argv[0] = str(self.bin / 'cat')
            (self.bin / 'cat').write_text(RECORDER)
            (self.bin / 'cat').chmod(0o755)
        subprocess.run(argv, cwd=self.root, env=self.environment, text=True, capture_output=True)
        self.assertFalse((self.root / 'MUST_NOT_EXECUTE').exists())
        self.assertEqual(self.calls()[-1]['argv'][-1], str(target / '.install-tag'))
    def test_arena_rejected_path_does_not_reach_setup(self):
        result = self.shell('resolve_repo_dest_path() { return 42; }; install_isaaclab_arena')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertFalse((self.home / 'events').exists())
        self.assertEqual(self.calls(), [])
    def test_python_patch_drift_is_rechecked_after_native(self):
        self.environment.update(DRIFT_STAGE='isaaclab.sh', DRIFT_PACKAGE='python')
        for cloud in (False, True):
            Path(self.environment['DRIFT_FILE']).unlink(missing_ok=True)
            result = self.cloud() if cloud else self.shell()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('runtime changed', result.stderr)

    def test_user_constraints_are_not_overwritten_or_adopted(self):
        original = self.home / 'My Constraints.txt'
        original.write_text('user-controlled original\n')
        self.environment.update(PIP_CONSTRAINT=str(original), UV_CONSTRAINT=str(original))
        result = self.shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        native = next(x for x in self.calls() if x['name'] == 'isaaclab.sh')
        self.assertNotEqual(native['pip'], str(original))
        self.assertEqual(original.read_text(), 'user-controlled original\n')
        self.assertFalse(Path(native['pip']).parent.exists())

    def test_cloud_arena_success_and_cloud_literal_path(self):
        self.lab = self.home / "Cloud Lab ' $(touch MUST_NOT_EXECUTE)"
        (self.lab / 'source/isaaclab').mkdir(parents=True)
        (self.lab / 'isaaclab.sh').write_text(RECORDER)
        (self.lab / 'isaaclab.sh').chmod(0o755)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertFalse((self.root / 'MUST_NOT_EXECUTE').exists())
        self.log.unlink()
        result = self.cloud('arena')
        self.assertEqual(result.returncode, 0, result.stderr)
        pip = [x for x in self.calls() if x['argv'][:3] == ['-m', 'pip', 'install']]
        self.assertEqual(len(pip), 2)
        self.assertIn('pinocchio', pip[-1]['argv'])
        self.assertIsNotNone(pip[-1]['pip'])
        self.assertIn('-c', self.calls()[-1]['argv'])


if __name__ == '__main__':
    unittest.main()
