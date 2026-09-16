#!/usr/bin/env python3
"""Offline role consumers: parse/render only; execute disposable shell seams only."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

import yaml
from jinja2 import Environment, StrictUndefined
from src.python.profile_adapters import render_profile
from src.python.workstation_profile import resolve_profile

ROOT = Path(__file__).resolve().parents[2]
ROLES = ROOT / 'src/ansible/roles'
ENV = Environment(undefined=StrictUndefined)
ENV.filters['bool'] = lambda v: str(v).lower() in ('true', 'yes', '1')
ENV.filters['quote'] = shlex.quote


def tasks(role, file='main.yml'):
    return yaml.safe_load((ROLES / role / 'tasks' / file).read_text())


def task_named(items, name):
    for item in items:
        if item.get('name') == name:
            return item
        if 'block' in item:
            try:
                return task_named(item['block'], name)
            except KeyError:
                pass
    raise KeyError(name)


def render(value, variables):
    return ENV.from_string(value).render(**variables)


def applies(task, variables):
    conditions = task.get('when', [])
    if isinstance(conditions, str):
        conditions = [conditions]
    return all(ENV.compile_expression(c)(**variables) for c in conditions)


def full_profile():
    profile = resolve_profile('full')['profile']
    profile['serving']['enabled'] = False
    profile['components']['sim']['source'].update(
        url='https://artifacts.example.org/sim.zip', sha256='a' * 64)
    return profile


class AnsibleRuntimeConsumers(unittest.TestCase):
    def test_gr00t_uv_runtime_routes_sync_outside_lab(self):
        report = render_profile(full_profile(), 'ansible', '/home/tester')
        self.assertNotIn('runtimes.gr00t.manager', [x['field'] for x in report['blockers']])
        variables = dict(report['artifact'], ansible_user='tester',
                         miniconda_install_dir='/home/tester/miniconda3',
                         gr00t_dir='/home/tester/work/Isaac-GR00T',
                         isaaclab_env_bin={'stat': {'exists': True}})
        native = tasks('gr00t', 'native.yml')
        shared = task_named(native, 'Install Isaac-GR00T dependencies into isaaclab environment')
        self.assertFalse(applies(shared, variables))
        isolated = task_named(native, 'Sync isolated profile GR00T environment')
        self.assertTrue(applies(isolated, variables))
        argv = [render(x, variables) for x in isolated['ansible.builtin.command']['argv']]
        self.assertEqual(argv[-1], 'sync')
        self.assertEqual(render(isolated['environment']['UV_PROJECT_ENVIRONMENT'], variables),
                         '/home/tester/work/Isaac-GR00T/.venv')
        self.assertEqual(isolated['environment']['PYTHONPATH'], '')
        self.assertEqual(report['coverage']['runtimes.gr00t.python']['status'], 'unspecified')
        self.assertTrue(applies(shared, {'isaaclab_env_bin': {'stat': {'exists': True}}}))
        self.assertFalse(applies(isolated, {}))
        # Exercise the extracted argv against a disposable recorder, not uv or packages.
        with tempfile.TemporaryDirectory(prefix='isaac-uv-seam-') as directory:
            fixture = Path(directory)
            uv = fixture / 'miniconda/envs/isaaclab/bin/uv'
            uv.parent.mkdir(parents=True)
            uv.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nprintf "ENV=%s\\nPYTHONPATH=%s\\n" "$UV_PROJECT_ENVIRONMENT" "$PYTHONPATH"\n')
            uv.chmod(0o755)
            seam = dict(variables, miniconda_install_dir=str(fixture / 'miniconda'),
                        gr00t_dir=str(fixture / 'GR00T project'))
            environment = {k: render(v, seam) for k, v in isolated['environment'].items()}
            environment.update(PATH='/usr/bin:/bin', HOME=directory)
            result = subprocess.run([render(x, seam) for x in isolated['ansible.builtin.command']['argv']],
                capture_output=True, text=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"sync\nENV={seam['gr00t_dir']}/.venv\nPYTHONPATH=\n")

    def test_lerobot_conda_runtime_has_separate_creation_and_install(self):
        profile = full_profile()
        profile['runtimes']['lerobot'].update(environment='robot-data', python='3.11')
        report = render_profile(profile, 'ansible', '/home/tester')
        self.assertTrue(report['render_supported'], report['blockers'])
        variables = dict(report['artifact'], miniconda_install_dir='/home/tester/miniconda3',
                         isaaclab_env_bin={'stat': {'exists': True}})
        role = tasks('lerobot')
        shared = task_named(role, 'Install LeRobot into isaaclab environment')
        self.assertFalse(applies(shared, variables))
        self.assertTrue(applies(shared, {'isaaclab_env_bin': {'stat': {'exists': True}}}))
        create = task_named(role, 'Create isolated profile LeRobot environment')
        argv = [render(x, variables) for x in create['ansible.builtin.command']['argv']]
        self.assertEqual(argv, ['/home/tester/miniconda3/bin/conda', 'create', '-y', '-n',
                                'robot-data', 'python=3.11', 'pip'])
        install = task_named(role, 'Install LeRobot into isolated profile environment')
        argv = [render(x, variables) for x in install['ansible.builtin.command']['argv']]
        self.assertEqual(argv[:4], ['/home/tester/miniconda3/envs/robot-data/bin/python', '-m', 'pip', 'install'])
        self.assertEqual(argv[4:], ['-e', '.', 'rerun-sdk'])
        self.assertEqual(install['environment']['PYTHONPATH'], '')
        self.assertEqual(install['environment']['PYTHONHOME'], '')
        self.assertFalse(applies(install, {}))

    def test_lerobot_launchers_execute_only_selected_conda_runtime(self):
        with tempfile.TemporaryDirectory(prefix='isaac-lerobot-seam-') as directory:
            root = Path(directory)
            conda = root / 'miniconda with spaces/bin/conda'
            conda.parent.mkdir(parents=True)
            conda.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nprintf "PYTHONPATH=%s PYTHONHOME=%s\\n" "${PYTHONPATH-unset}" "${PYTHONHOME-unset}"\n')
            conda.chmod(0o755)
            repo = root / 'LeRobot project'
            repo.mkdir()
            variables = {'profile_lerobot_isolated': 'true',
                         'profile_lerobot_environment': 'robot-data',
                         'miniconda_install_dir': str(conda.parent.parent), 'lerobot_dir': str(repo)}
            for filename in ('lerobot-teleop.sh.j2', 'lerobot-dataset-viz.j2'):
                with self.subTest(filename=filename):
                    template = (ROLES / 'lerobot/templates' / filename).read_text()
                    script = root / filename.removesuffix('.j2')
                    script.write_text(render(template, variables))
                    result = subprocess.run(['/bin/bash', str(script), '--dataset', 'two words'],
                        capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'HOME': directory,
                        'PYTHONPATH': '/forbidden/lab', 'PYTHONHOME': '/forbidden/lab'})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('run\n--no-capture-output\n-n\nrobot-data\npython\n-m\nlerobot.scripts.visualize_dataset\n--dataset\ntwo words\n', result.stdout)
                    self.assertIn('PYTHONPATH=unset PYTHONHOME=unset', result.stdout)
                    self.assertNotIn('isaaclab-env', script.read_text())
                    self.assertIn('isaaclab-env', render(template, dict(variables, profile_lerobot_isolated='false')))
            conda.unlink()
            failed = subprocess.run(['/bin/bash', str(script)], capture_output=True, text=True,
                                    env={'PATH': '/usr/bin:/bin', 'HOME': directory})
            self.assertNotEqual(failed.returncode, 0)  # no fallback to host/Lab Python

    def test_profile_serving_refuses_unimplemented_loopback_and_model_selectors(self):
        profile = full_profile()
        profile['serving']['enabled'] = True
        report = render_profile(profile, 'ansible', '/home/tester')
        self.assertFalse(report['artifact']['gr00t_service_enabled'])
        for field in ('enabled', 'bind', 'port', 'embodiment', 'model.repository', 'model.ref', 'model.revision'):
            entry = report['coverage']['serving.' + field]
            self.assertEqual(entry['status'], 'unsupported')
            self.assertIn('loopback', entry['reason'])
        template = (ROLES / 'gr00t/templates/gr00t-policy-server.sh.j2').read_text()
        rendered = render(template, report['artifact'])
        self.assertNotIn('isaaclab-env', rendered)
        self.assertNotIn('exec python', rendered)
        with tempfile.TemporaryDirectory(prefix='isaac-serving-seam-') as directory:
            path = Path(directory) / 'launcher.sh'
            path.write_text(rendered)
            result = subprocess.run(['/bin/bash', str(path)], capture_output=True, text=True,
                                    env={'PATH': '/usr/bin:/bin', 'HOME': directory})
            self.assertEqual(result.returncode, 2)
            self.assertIn('unsupported', result.stderr.lower())
        defaults = yaml.safe_load((ROLES / 'gr00t/defaults/main.yml').read_text())
        defaults['gr00t_dir'] = '/legacy/gr00t'
        self.assertIn('isaaclab-env', render(template, defaults))
        service = (ROLES / 'gr00t/templates/isaac-gr00t.service.j2').read_text()
        unit = render(service, dict(defaults, **report['artifact'], ansible_user='tester'))
        self.assertNotIn('isaaclab-env', unit)
        self.assertIn('/gr00t-policy-server.sh', unit)
        self.assertIn('isaaclab-env', render(service, dict(defaults, ansible_user='tester')))

    def test_arena_immutable_revision_fresh_clone_uses_real_local_git(self):
        clone = task_named(tasks('isaaclab-arena-source', 'install.yml'), 'Clone Isaac Lab Arena repository')
        with tempfile.TemporaryDirectory(prefix='isaac-arena-git-seam-') as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target with spaces'
            env = {'PATH': '/usr/bin:/bin', 'HOME': directory, 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
            def git(*args):
                result = subprocess.run(['git', *args], env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()
            git('init', str(source))
            (source / 'marker').write_text('fixture only')
            git('-C', str(source), 'add', 'marker')
            git('-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.org',
                'commit', '-m', 'fixture')
            revision = git('-C', str(source), 'rev-parse', 'HEAD')
            variables = {'isaaclab_arena_dir': str(target), 'isaaclab_arena_git_repo': str(source),
                         'isaaclab_arena_git_checkpoint': revision}
            script = render(clone['shell'], variables)
            result = subprocess.run(['/bin/bash', '-c', script], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git('-C', str(target), 'rev-parse', 'HEAD'), revision)
            self.assertEqual((target / 'marker').read_text(), 'fixture only')
            inspect = task_named(tasks('isaaclab-arena-source', 'install.yml'), 'Get current Isaac Lab Arena git ref')
            checked = subprocess.run(['/bin/bash', '-c', render(inspect['shell'], variables)],
                                     env=env, text=True, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(checked.stdout.strip(), 'match')
            original_origin = git('-C', str(target), 'remote', 'get-url', 'origin')
            wrong_source = dict(variables, isaaclab_arena_git_repo=str(root / 'different-source'))
            for entry in (inspect, clone):
                refused = subprocess.run(['/bin/bash', '-c', render(entry['shell'], wrong_source)],
                                         env=env, text=True, capture_output=True)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn('origin', refused.stderr)
                self.assertEqual(git('-C', str(target), 'remote', 'get-url', 'origin'), original_origin)
                self.assertEqual(git('-C', str(target), 'rev-parse', 'HEAD'), revision)

    def test_gr00t_tool_prerequisite_and_unimplemented_pins_are_explicit(self):
        profile = full_profile()
        report = render_profile(profile, 'ansible', '/home/tester')
        self.assertIs(report['artifact'].get('enable_uv'), True)
        tool = task_named(tasks('conda'), 'Install UV for fast pip resolution')
        self.assertTrue(applies(tool, report['artifact']))
        self.assertIn('pip install uv', render(tool['shell'],
            dict(report['artifact'], miniconda_install_dir='/home/tester/miniconda3')))
        for component in ('gr00t', 'lerobot'):
            profile['runtimes'][component]['torch'] = '2.10.0+cu128'
        profile['runtimes']['gr00t']['environment'] = 'different-uv-name'
        blocked = render_profile(profile, 'ansible', '/home/tester')
        fields = {b['field'] for b in blocked['blockers']}
        self.assertIn('runtimes.gr00t.torch', fields)
        self.assertIn('runtimes.lerobot.torch', fields)
        self.assertIn('runtimes.gr00t.environment', fields)
        self.assertNotIn('profile_gr00t_torch', blocked['artifact'])
        disabled = render_profile(resolve_profile('default'), 'ansible', '/home/tester')
        self.assertNotIn('profile_gr00t_isolated', disabled['artifact'])
        self.assertNotIn('profile_lerobot_isolated', disabled['artifact'])
        self.assertNotIn('enable_uv', disabled['artifact'])

    def test_isolated_values_survive_real_deployer_and_ansible_ini_parser(self):
        import copy
        import sys
        from unittest import mock
        from click.testing import CliRunner
        from src.python.config import c as config
        from src.python.deploy_command import DeployCommand
        from src.python.deployer import Deployer
        profile = full_profile()
        profile['workspace'] = {'root': '~/Documents/GitHub', 'layout': 'named', 'name': 'Robot Team'}
        with tempfile.TemporaryDirectory(prefix='isaac-runtime-inventory-') as directory:
            root = Path(directory)
            conf = copy.deepcopy(config)
            conf.update(state_dir=directory, ansible_dir=str(ROOT / 'src/ansible'), app_dir=str(ROOT))
            captured = []
            def inventory(**params):
                params.update(cloud='gcp', isaac_workstation_ip='192.0.2.10', software_profile=profile)
                captured.append(Deployer(params, conf).create_ansible_inventory(write=False))
            command = DeployCommand('fixture', callback=inventory)
            with mock.patch('subprocess.Popen', side_effect=AssertionError('external process')), \
                 mock.patch('socket.socket', side_effect=AssertionError('network')):
                result = CliRunner().invoke(command, ['--deployment-name', 'fixture',
                    '--ingress-cidrs', '192.0.2.1/32', '--isaacsim', 'no', '--isaaclab', 'no', '--isaaclab-arena', 'no'])
            self.assertEqual(result.exit_code, 0, result.output)
            path = root / 'inventory.ini'
            path.write_text(captured[0])
            cfg = root / 'ansible.cfg'
            cfg.write_text('[defaults]\n')
            script = ('import json; from ansible.parsing.dataloader import DataLoader; '
                      'from ansible.inventory.manager import InventoryManager; '
                      'i=InventoryManager(loader=DataLoader(),sources=[' + repr(str(path)) + ']); '
                      'print(json.dumps(i.groups["isaac_workstation"].vars))')
            parsed = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True,
                env={'PATH': '/usr/bin:/bin', 'HOME': directory, 'ANSIBLE_CONFIG': str(cfg),
                     'ANSIBLE_LOCAL_TEMP': directory + '/ansible-tmp', 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            variables = json.loads(parsed.stdout)
            self.assertEqual(variables['profile_gr00t_isolated'], 'true')
            self.assertEqual(variables['profile_lerobot_environment'], 'lerobot')
            self.assertEqual(variables['gr00t_service_enabled'], 'false')
            self.assertTrue(variables['gr00t_dir'].endswith('/Robot Team/Isaac-GR00T'))
            self.assertTrue(variables['lerobot_dir'].endswith('/Robot Team/lerobot'))
            variables['isaaclab_env_bin'] = {'stat': {'exists': True}}
            self.assertFalse(applies(task_named(tasks('gr00t', 'native.yml'),
                'Install Isaac-GR00T dependencies into isaaclab environment'), variables))
            self.assertFalse(applies(task_named(tasks('lerobot'),
                'Install LeRobot into isaaclab environment'), variables))
            self.assertTrue(applies(task_named(tasks('gr00t', 'native.yml'),
                'Sync isolated profile GR00T environment'), variables))
            self.assertTrue(applies(task_named(tasks('lerobot'),
                'Install LeRobot into isolated profile environment'), variables))
            # INI JSON booleans are strings: legacy false must not be truthy.
            tool = task_named(tasks('conda'), 'Install UV for fast pip resolution')
            self.assertFalse(applies(tool, {'enable_uv': 'false'}))


if __name__ == '__main__':
    unittest.main()
