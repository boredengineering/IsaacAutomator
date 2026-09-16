#!/usr/bin/env python3
"""Exercise the actual nonmutating consumer seams, never provision a target."""
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml
from jinja2 import Environment, StrictUndefined
from click.testing import CliRunner
from src.python.workstation_profile import resolve_profile
from src.python.profile_adapters import render_profile

ROOT = Path(__file__).resolve().parents[2]


class TransportTests(unittest.TestCase):
    def test_runtime_pins_reach_real_conda_role_expression(self):
        profile = resolve_profile('default')
        report = render_profile(profile, 'ansible', '/home/tester')
        variables = report['artifact']
        self.assertEqual(variables.get('profile_lab_torch'), '2.10.0+cu128')
        self.assertEqual(variables.get('profile_lab_cuda_runtime'), '12.8')
        self.assertEqual(variables.get('profile_lab_architecture'), 'sm_120')
        tasks = yaml.safe_load((ROOT / 'src/ansible/roles/conda/tasks/main.yml').read_text())
        task = next(t for t in tasks if t['name'] == 'Determine PyTorch wheel channel and spec')
        env = Environment(undefined=StrictUndefined)
        facts = {k: env.from_string(v).render(**variables) for k, v in task['set_fact'].items()}
        self.assertIn('torch==2.10.0+cu128', facts['torch_version_spec'])
        self.assertEqual(facts['torch_wheel_channel'], 'https://download.pytorch.org/whl/cu128')
        self.assertNotIn('runtimes.lab.torch', [x['field'] for x in report['blockers']])
        # Unselected legacy deployments retain hardware-derived defaults.
        defaults = {k: env.from_string(v).render() for k, v in task['set_fact'].items()}
        self.assertIn('torch==2.5.1+cu124', defaults['torch_version_spec'])

    def test_render_cli_emits_legacy_yaml_accepted_by_real_parser(self):
        from src.python.workstation_profile_command import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'desired.yaml'
            source.write_text(yaml.safe_dump(resolve_profile('minimal', {
                'components': {'lab': {'enabled': False}}})['profile']))
            with mock.patch('socket.socket', side_effect=AssertionError('network')), \
                    mock.patch('subprocess.Popen', side_effect=AssertionError('process')):
                result = CliRunner().invoke(main, ['render', str(source), '--adapter', 'local',
                    '--target-home', '/home/tester', '--format', 'yaml'])
            self.assertEqual(result.exit_code, 0, result.output)
            output = root / 'legacy.yaml'
            output.write_text(result.output)
            spec = importlib.util.spec_from_file_location('legacy_parser_test', ROOT / 'isaac-installer/lib/core/profile_parser.py')
            parser = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(parser)
            items = parser.parse_profile(output).decode().rstrip('\0').split('\0')
            parsed = dict(zip(items[::2], items[1::2]))
            self.assertEqual(parsed['CFG_SIMULATION_ISAACSIM_VERSION'], '6.0.1')
            self.assertEqual(parsed['CFG_SIMULATION_ISAACSIM_INSTALL_DIR'], '/home/tester/IsaacSim')
            self.assertEqual(parsed['CFG_REPOSITORIES_ISAACLAB_ENABLED'], 'false')
            self.assertNotIn('kind', yaml.safe_load(result.output))

    def test_profile_transport_reaches_real_deployer_inventory_without_writing(self):
        import copy
        from src.python.config import c as config
        from src.python.deploy_command import DeployCommand
        from src.python.deployer import Deployer
        desired = {'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'paths',
                   'defaults': False, 'workspace': {'root': '~/Documents/GitHub', 'layout': 'named', 'name': 'Robotics Team'}}
        with tempfile.TemporaryDirectory() as directory:
            conf = copy.deepcopy(config)
            conf.update(state_dir=directory, ansible_dir=str(ROOT / 'src/ansible'), app_dir=str(ROOT))
            captured, recreated = [], []
            def render(**params):
                params.update(cloud='gcp', isaac_workstation_ip='192.0.2.10', software_profile=desired)
                deployer = Deployer(params, conf)
                captured.append(deployer.create_ansible_inventory(write=False))
                recreated.append(deployer.recreate_command_line(' '))
            command = DeployCommand('transport', callback=render)
            with mock.patch('subprocess.Popen', side_effect=AssertionError('process')), \
                    mock.patch('socket.socket', side_effect=AssertionError('network')):
                result = CliRunner().invoke(command, ['--deployment-name', 'fixture',
                    '--ingress-cidrs', '192.0.2.1/32', '--isaacsim', 'no', '--isaaclab', 'no', '--isaaclab-arena', 'no'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn('profile_isaacsim_archive_enabled=false', captured[0])
            self.assertIn('workspace_dir="/home/' + conf['default_ssh_user'] + '/Documents/GitHub/Robotics Team"', captured[0])
            self.assertIn('install_gr00t=false', captured[0])
            self.assertFalse((Path(directory) / 'fixture/.inventory').exists())
            # Direct API intent lacks an explicit source path: never recreate a
            # command that silently drops it and enables deployment defaults.
            self.assertTrue(recreated[0].startswith('# Cannot recreate'))
            # Parse with the actual Ansible INI plugin, using only disposable
            # configuration/home directories; this never connects to the host.
            import subprocess
            import sys
            inventory = Path(directory) / 'rendered.ini'
            inventory.write_text(captured[0])
            ansible_config = Path(directory) / 'ansible.cfg'
            ansible_config.write_text('[defaults]\n')
            script = ('import json; from ansible.parsing.dataloader import DataLoader; '
                      'from ansible.inventory.manager import InventoryManager; '
                      'i=InventoryManager(loader=DataLoader(),sources=[' + repr(str(inventory)) + ']); '
                      'print(json.dumps(i.groups["isaac_workstation"].vars))')
            parsed = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True,
                env={'PATH': '/usr/bin:/bin', 'HOME': directory, 'ANSIBLE_CONFIG': str(ansible_config),
                     'ANSIBLE_LOCAL_TEMP': directory + '/ansible-tmp', 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            self.assertEqual(json.loads(parsed.stdout)['workspace_dir'],
                             '/home/' + conf['default_ssh_user'] + '/Documents/GitHub/Robotics Team')

    def test_custom_pypi_dependency_maps_only_selected_lab_environment(self):
        desired = resolve_profile('default')['profile']
        desired['components']['sim']['source']['sha256'] = 'a' * 64  # fixture-only reviewed pin
        desired['components']['sim']['source']['url'] = 'https://artifacts.example.org/sim-6.0.1.zip'
        desired['draft'] = False  # exporter separates reviewed intent from generic support status
        desired['custom_dependencies'] = [{'id': 'extra', 'name': 'pytest', 'version': '8.3.1',
            'environment': 'isaaclab', 'location': None, 'purpose': 'offline testing',
            'source': 'pypi', 'placement': 'environment', 'required': True, 'support': 'unsupported'}]
        report = render_profile(desired, 'ansible', '/home/tester')
        self.assertEqual(report['artifact'].get('profile_lab_packages'), ['pytest==8.3.1'])
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertEqual(report['coverage']['custom_dependencies.0.name']['status'], 'mapped')
        tasks = yaml.safe_load((ROOT / 'src/ansible/roles/conda/tasks/main.yml').read_text())
        task = next(t for t in tasks if t['name'] == 'Install reviewed profile Lab dependencies')
        env = Environment(undefined=StrictUndefined)
        argv = [env.from_string(v).render(miniconda_install_dir='/home/tester/miniconda3',
                conda_env_name='isaaclab', item='pytest==8.3.1') for v in task['ansible.builtin.command']['argv']]
        self.assertEqual(argv, ['/home/tester/miniconda3/envs/isaaclab/bin/python', '-m', 'pip', 'install', '--', 'pytest==8.3.1'])
        desired['custom_dependencies'][0]['placement'] = 'container'
        blocked = render_profile(desired, 'ansible', '/home/tester')
        self.assertNotIn('profile_lab_packages', blocked['artifact'])
        self.assertIn('custom_dependencies.0.name', [x['field'] for x in blocked['blockers']])

    def test_deploy_profile_option_is_parsed_before_refs_and_help_is_offline(self):
        from src.python.deploy_command import DeployCommand
        captured = []
        command = DeployCommand('transport', callback=lambda **params: captured.append(params))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'software.yaml'
            path.write_text(yaml.safe_dump({'schema_version': 'v1alpha1', 'kind': 'workstation-profile',
                'name': 'empty', 'defaults': False, 'draft': False}))
            flags = ['--software-profile', str(path), '--deployment-name', 'fixture',
                     '--ingress-cidrs', '192.0.2.1/32']
            with mock.patch('subprocess.Popen', side_effect=AssertionError('network')), \
                    mock.patch('socket.socket', side_effect=AssertionError('network')):
                result = CliRunner().invoke(command, flags)
                help_result = CliRunner().invoke(command, ['--software-profile', '/nonexistent', '--help'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(captured[0]['isaaclab'], 'no')
            self.assertEqual(captured[0]['software_profile']['name'], 'empty')
            self.assertEqual(help_result.exit_code, 0, help_result.output)
            self.assertIn('--software-profile', help_result.output)

    def test_custom_lab_identity_is_used_by_sim_bridge_and_state_ledger(self):
        env = Environment(undefined=StrictUndefined)
        sim_tasks = yaml.safe_load((ROOT / 'src/ansible/roles/isaacsim-source/tasks/install.yml').read_text())
        bridge = next(t for t in sim_tasks if 'conda_sp_dir' == t.get('register'))
        command = env.from_string(bridge['shell']).render(ansible_user='tester', conda_env_name='robot-lab',
                                                        miniconda_install_dir='/home/tester/miniconda3')
        self.assertIn('/envs/robot-lab/lib', command)
        ledger = (ROOT / 'src/ansible/roles/state-ledger/tasks/main.yml').read_text()
        self.assertIn('{{ isaaclab_dir', ledger)
        verify = (ROOT / 'src/ansible/roles/state-ledger/templates/isaac-verify-state.j2').read_text()
        self.assertIn('{{ isaaclab_dir', verify)

    def test_profile_option_is_available_on_images_and_recreation_preserves_source(self):
        import copy
        import runpy
        from src.python.config import c as config
        from src.python.deploy_command import DeployCommand
        from src.python.deployer import Deployer
        command = runpy.run_path(str(ROOT / 'image-gcp'), run_name='profile_test')['main']
        result = CliRunner().invoke(command, ['--help'])
        self.assertIn('--software-profile', result.output)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'desired.yaml'
            profile.write_text(yaml.safe_dump({'schema_version': 'v1alpha1', 'kind': 'workstation-profile',
                'name': 'empty', 'defaults': False}))
            conf = copy.deepcopy(config)
            conf.update(state_dir=str(root / 'state'), app_dir=str(ROOT))
            commands = []
            def record(**params):
                params['cloud'] = 'gcp'
                commands.append(Deployer(params, conf).recreate_command_line(' '))
            cmd = DeployCommand('fixture', callback=record)
            result = CliRunner().invoke(cmd, ['--software-profile', str(profile), '--deployment-name', 'fixture',
                                             '--ingress-cidrs', '192.0.2.1/32'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn('--software-profile ' + str(profile), commands[0])
            self.assertNotIn('--isaaclab ', commands[0])
            self.assertNotIn('--isaaclab-repo ', commands[0])

    def test_enabled_profile_forks_validate_and_reach_actual_inventory(self):
        import copy
        from types import SimpleNamespace
        from src.python.config import c as config
        from src.python.deploy_command import DeployCommand
        from src.python.deployer import Deployer
        desired = resolve_profile('default')['profile']
        desired['components']['sim']['source']['sha256'] = 'c' * 64  # reviewed synthetic checksum, not a published pin
        desired['components']['sim']['source']['url'] = 'https://artifacts.example.org/sim-6.0.1.zip'
        for component, repository in (('lab', 'IsaacLab'), ('arena', 'IsaacLab-Arena')):
            desired['components'][component]['source'] = {'mode': 'git',
                'repository': 'https://github.com/example/' + repository + '.git',
                'ref': 'latest' if component == 'lab' else 'fork-only', 'revision': None}
        desired['workspace'] = {'root': '~/Documents/GitHub', 'layout': 'named', 'name': 'Robotics Team'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'desired.yaml'
            profile.write_text(yaml.safe_dump(desired))
            conf = copy.deepcopy(config)
            conf.update(state_dir=str(root / 'state'), ansible_dir=str(ROOT / 'src/ansible'), app_dir=str(ROOT))
            lookups, inventories = [], []
            def git(argv, **kwargs):
                self.assertEqual(argv[:2], ['git', 'ls-remote'])
                repo = next(x for x in argv if x.startswith('https://'))
                lookups.append(repo)
                return SimpleNamespace(stdout='a' * 40 + '\trefs/heads/fork-only\n' + 'b' * 40 + '\trefs/tags/v1.2.3\n', stderr='', returncode=0)
            def render(**params):
                params.update(cloud='gcp', isaac_workstation_ip='192.0.2.10')
                inventories.append(Deployer(params, conf).create_ansible_inventory(write=False))
            command = DeployCommand('fixture', callback=render)
            with mock.patch('src.python.deploy_command.subprocess.run', side_effect=git):
                result = CliRunner().invoke(command, ['--software-profile', str(profile), '--deployment-name', 'fixture',
                                                     '--ingress-cidrs', '192.0.2.1/32'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(set(lookups), {c['source']['repository'] for c in desired['components'].values()
                                           if c['enabled'] and c['source']['mode'] == 'git'})
            self.assertIn('isaaclab_git_checkpoint="v1.2.3"', inventories[0])
            self.assertNotIn('isaaclab_git_checkpoint="latest"', inventories[0])
            self.assertIn('isaacsim_git_checkpoint="no"', inventories[0])
            self.assertIn('profile_isaacsim_archive_enabled=true', inventories[0])
            self.assertIn('isaacsim_archive_sha256="' + 'c' * 64 + '"', inventories[0])
            self.assertIn('isaaclab_dir="/home/ubuntu/Documents/GitHub/Robotics Team/IsaacLab"', inventories[0])
            self.assertIn('profile_lab_torch="2.10.0+cu128"', inventories[0])
            with mock.patch('src.python.deploy_command.subprocess.run', return_value=SimpleNamespace(stdout='', stderr='', returncode=0)):
                missing = CliRunner().invoke(command, ['--software-profile', str(profile), '--deployment-name', 'fixture',
                                                        '--ingress-cidrs', '192.0.2.1/32'])
            self.assertEqual(missing.exit_code, 2, missing.output)
            self.assertEqual(len(inventories), 1)  # no deployer reached for missing fork ref
            with mock.patch('src.python.deploy_command.subprocess.run', side_effect=AssertionError('conflict must precede lookup')):
                conflicting = CliRunner().invoke(command, ['--software-profile', str(profile), '--isaaclab', 'main'])
            self.assertEqual(conflicting.exit_code, 2, conflicting.output)
            self.assertEqual(len(inventories), 1)
            for name in ('lab', 'arena'):
                desired['components'][name]['source']['revision'] = 'd' * 40
            profile.write_text(yaml.safe_dump(desired))
            lookups.clear()
            def proof(argv, **kwargs):
                self.assertEqual(argv[3], '/usr/bin/git')
                if 'fetch' in argv:
                    lookups.append(argv[-2])
                    self.assertEqual(argv[-1], 'd' * 40)
                output = 'commit\n' if 'cat-file' in argv else 'd' * 40 + '\n' if 'rev-parse' in argv else ''
                kwargs['stdout'].write(output.encode('utf-8'))
                return SimpleNamespace(returncode=0, stdout=output, stderr='')
            with mock.patch('src.python.deploy_command.subprocess.run', side_effect=proof) as pinned_lookup:
                pinned = CliRunner().invoke(command, ['--software-profile', str(profile), '--deployment-name', 'fixture',
                                                       '--ingress-cidrs', '192.0.2.1/32'])
            self.assertEqual(pinned.exit_code, 0, pinned.output)
            self.assertEqual(set(lookups), {desired['components'][name]['source']['repository'] for name in ('lab', 'arena')})
            self.assertEqual(pinned_lookup.call_count, 8)
            self.assertTrue(any('cat-file' in call.args[0] for call in pinned_lookup.call_args_list))
            self.assertFalse(any('ls-remote' in call.args[0] for call in pinned_lookup.call_args_list))
            self.assertIn('isaaclab_git_checkpoint="' + 'd' * 40 + '"', inventories[1])
            self.assertIn('isaaclab_arena_git_checkpoint="' + 'd' * 40 + '"', inventories[1])

    def test_standalone_archive_requires_explicit_pin_and_real_role(self):
        import jinja2
        from src.python.profile_adapters import render_profile
        desired = resolve_profile('default')['profile']
        unpinned = render_profile(desired, 'ansible', '/home/tester')
        self.assertIn('components.sim.source.sha256', [x['field'] for x in unpinned['blockers']])
        desired['components']['sim']['source'].pop('sha256')
        absent = render_profile(desired, 'ansible', '/home/tester')
        self.assertIn('components.sim.source.sha256', [x['field'] for x in absent['blockers']])
        desired['components']['sim']['source']['sha256'] = 'a' * 64
        desired['components']['sim']['source']['url'] = 'https://artifacts.example.org/sim-6.0.1.zip'
        report = render_profile(desired, 'ansible', '/home/tester')
        self.assertTrue(report['render_supported'], report['blockers'])
        artifact = report['artifact']
        self.assertEqual(artifact['isaacsim_archive_url'],
            'https://artifacts.example.org/sim-6.0.1.zip')
        self.assertEqual(artifact['isaacsim_version'], '6.0.1')
        self.assertEqual(artifact['isaacsim_install_dir'], '/home/tester/IsaacSim')
        tasks = yaml.safe_load((ROOT / 'src/ansible/roles/isaacsim-source/tasks/standalone.yml').read_text())
        def all_tasks(items):
            for task in items:
                yield task
                for section in ('block', 'rescue', 'always'):
                    yield from all_tasks(task.get(section, []))
        flattened = list(all_tasks(tasks))
        self.assertFalse(any('ansible.builtin.get_url' in task for task in flattened))
        download = next(t['ansible.builtin.command']['argv'] for t in flattened
                        if '--sha256' in t.get('ansible.builtin.command', {}).get('argv', []))
        values = dict(artifact, ansible_user='tester', isaacsim_artifact_helper={'path': '/fixture/helper'})
        argv = [jinja2.Template(value).render(**values) for value in download]
        self.assertEqual(argv[:3], ['/usr/bin/python3', '-I', '/fixture/helper/public_artifact.py'])
        self.assertEqual(argv[argv.index('--url') + 1], artifact['isaacsim_archive_url'])
        self.assertEqual(argv[argv.index('--sha256') + 1], 'a' * 64)
        entry = yaml.safe_load((ROOT / 'src/ansible/roles/isaacsim-source/tasks/main.yml').read_text())
        standalone = next(t for t in entry if t.get('import_tasks') == 'standalone.yml')
        self.assertIn('profile_isaacsim_archive_enabled', standalone['when'])
        self.assertFalse(report['apply_supported'])


if __name__ == '__main__':
    unittest.main()
