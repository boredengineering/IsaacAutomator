#!/usr/bin/env python3
"""Offline image entry/consumer transport contracts; never run Packer or Git."""
import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner
import yaml

from src.python.profile_adapters import render_profile
from src.python.config import c as config

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = {'gcp': 'build_gcp_image', 'aws': 'build_ami', 'azure': 'build_azure_image'}
SHA = 'a' * 40  # Synthetic selector, never evidence of repository reachability.


def desired():
    return {'schema_version': 'v1alpha1', 'kind': 'workstation-profile',
            'name': 'packer-fixture', 'defaults': False,
            'components': {'sim': {'enabled': True, 'execution': 'native', 'runtime': 'kit',
                'source': {'mode': 'git', 'repository': 'https://github.com/fixture/IsaacSim.git',
                           'ref': 'reviewed', 'revision': SHA}}},
            'runtimes': {'kit': {'manager': 'bundled', 'environment': 'kit', 'python': None}},
            'workspace': {'root': '~/Code', 'layout': 'named', 'name': 'Robot Team'}}


CAPTURES = []


def full_desired(standalone=False):
    from src.python.workstation_profile import resolve_profile
    profile = resolve_profile('default')['profile']
    profile['name'] = 'full-packer-fixture'
    profile['workspace'] = desired()['workspace']
    for name, component in profile['components'].items():
        component['enabled'] = True
        component['source'] = {'mode': 'git', 'repository': 'https://github.com/fixture/' + name + '.git',
                               'ref': 'reviewed', 'revision': SHA}
    if standalone:
        profile['components']['sim']['source'] = {'mode': 'standalone', 'version': '6.0.1',
            'url': 'https://downloads.example.org/isaacsim.zip', 'sha256': 'b' * 64}
    profile['runtimes']['lab']['torchvision'] = '0.25.0+cu128'
    profile['custom_dependencies'] = [{'id': 'extra', 'name': 'fixture-package', 'version': '1.2.3',
        'environment': 'isaaclab', 'location': None, 'purpose': 'offline fixture',
        'source': 'pypi', 'placement': 'environment', 'required': True, 'support': 'unsupported'}]
    profile['notes'] = [{'id': 'review-note', 'text': 'Unmapped review intent is retained',
                         'required': False, 'support': 'unsupported'}]
    return profile


class PackerTransportTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(mock.patch.dict(os.environ, {'VERSION': 'v0.0.0-fixture', 'HOME': str(self.tmp)}, clear=True))
        self.stack.enter_context(mock.patch.dict(config, state_dir=str(self.tmp)))
        self.process = self.stack.enter_context(mock.patch('subprocess.run', side_effect=AssertionError('external process')))
        self.stack.enter_context(mock.patch('subprocess.Popen', side_effect=AssertionError('external process')))
        self.stack.enter_context(mock.patch('socket.socket', side_effect=AssertionError('network')))
        self.proof = self.stack.enter_context(mock.patch(
            'src.python.public_git.prove_public_commit', side_effect=AssertionError('commit network')))
        self.modules = {}
        for provider in PROVIDERS:
            loader = SourceFileLoader('profile_image_' + provider, str(ROOT / ('image-' + provider)))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            assert spec is not None
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            self.modules[provider] = module
        self.profile_file = self.tmp / 'profile.yaml'
        self.profile_file.write_text(yaml.safe_dump(desired()))

    def flags(self, provider):
        flags = ['--image-name', 'fixture', '--system-user-password', 'synthetic-fixture',
                 '--software-profile', str(self.profile_file)]
        if provider == 'gcp':
            flags += ['--project', 'fixture-project', '--zone', 'us-central1-a', '--instance-type', 'g2-standard-8']
        elif provider == 'aws':
            flags += ['--region', 'us-east-1', '--instance-type', 'g6e.2xlarge']
        else:
            flags += ['--region', 'westus3', '--instance-type', 'Standard_NV36ads_A10_v5']
        return flags

    def test_image_dry_cli_translates_source_and_target_paths_without_effects(self):
        for provider, module in self.modules.items():
            with self.subTest(provider=provider):
                result = CliRunner().invoke(module.main, self.flags(provider) + ['--dry-run'])
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                preview, _ = json.JSONDecoder().raw_decode(result.output)
                report = preview['software_profile']
                self.assertEqual(report['adapter'], 'packer')
                self.assertEqual(report['artifact']['isaacsim_git_repo'], 'https://github.com/fixture/IsaacSim.git')
                self.assertEqual(report['artifact']['isaacsim_source_dir'], '/home/ubuntu/Code/Robot Team/IsaacSim')
                self.assertEqual(report['artifact']['isaacsim_git_checkpoint'], SHA)
                self.assertFalse(report['references_verified'])
                self.assertFalse(report['apply_supported'])
        self.process.assert_not_called()

    @contextlib.contextmanager
    def effects(self, module):
        with contextlib.ExitStack() as stack:
            effects = {}
            for name, value in {'gcp_login': None, 'delete_gcp_image': None,
                    'aws_image_credentials': {}, 'azure_login': None,
                    'azure_get_subscription_id': 'fixture-subscription',
                    'azure_ensure_resource_group': None, 'delete_managed_image': None,
                    'shell_command': subprocess.CompletedProcess([], 0, b'', b'')}.items():
                if hasattr(module, name):
                    effects[name] = stack.enter_context(mock.patch.object(module, name, return_value=value))
            yield effects

    def test_real_image_cli_reaches_last_ansible_file_and_public_preflight(self):
        from src.python.deploy_command import DeployCommand
        from jinja2 import Environment, StrictUndefined
        for provider, profile in [(p, profile) for profile in (desired(), full_desired(), full_desired(True))
                                  for p in PROVIDERS]:
            module = self.modules[provider]
            self.profile_file.write_text(yaml.safe_dump(profile))
            captured, files = [], []
            self.proof.reset_mock()
            self.proof.side_effect = lambda repository, revision: revision
            def packer_consumer(argv, **kwargs):
                self.assertEqual(argv[0], 'packer')
                if argv[1] == 'build':
                    path = Path(next(a.split('=', 1)[1] for a in argv if a.startswith('-var-file=')))
                    variables = json.loads(path.read_text())
                    ansible_file = Path(variables['ansible_secret_vars_file'])
                    files.extend([path, ansible_file])
                    self.assertEqual(ansible_file.stat().st_mode & 0o777, 0o600)
                    template = Path(argv[-1]).read_text()
                    # Inspect the actual selected provider's provisioner, not a
                    # fabricated template: this file is the LAST extra-vars input.
                    provisioner = template.split('provisioner "ansible" {', 1)[1].split('provisioner "shell"', 1)[0]
                    self.assertIn('playbook_file = "${path.root}/../../ansible/isaac-workstation.yaml"', provisioner)
                    self.assertEqual(provisioner.rsplit('"--extra-vars", ', 1)[1].splitlines()[0],
                                     '"@${var.ansible_secret_vars_file}"')
                    captured.append(json.loads(ansible_file.read_text()))
                return subprocess.CompletedProcess(argv, 0, '', '')
            self.process.side_effect = packer_consumer
            with self.subTest(provider=provider), self.effects(module), mock.patch.object(
                    DeployCommand, '_anonymous_ls_remote', return_value=subprocess.CompletedProcess(
                        [], 0, 'b' * 40 + '\trefs/heads/reviewed\n', '')) as refs:
                result = CliRunner().invoke(module.main, self.flags(provider))
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                repositories = {c['source']['repository'] for c in profile['components'].values()
                                if c['enabled'] and c['source']['mode'] == 'git'}
                self.assertEqual({call.args[0] for call in self.proof.call_args_list}, repositories)
                self.assertEqual(self.proof.call_count, len(repositories))
                refs.assert_not_called()
                self.assertEqual(len(captured), 1)
                report = render_profile(profile, 'packer', '/home/ubuntu')
                artifact = report['artifact']
                for key, value in artifact.items():
                    self.assertEqual(captured[0].get(key), value, key)
                self.assertEqual(captured[0]['system_user_password'], 'synthetic-fixture')
                self.assertFalse(any(path.exists() for path in files))
                # Dry-render the actual clone module arguments using only values
                # read back from the final Packer/Ansible file. No module executes.
                rendered_clones = {}
                for component, role, task_file, consumer, path_var in (
                    ('sim', 'isaacsim-source', 'install.yml', 'isaacsim', 'isaacsim_source_dir'),
                    ('lab', 'isaaclab-source', 'install.yml', 'isaaclab', 'isaaclab_dir'),
                    ('arena', 'isaaclab-arena-source', 'install.yml', 'isaaclab_arena', 'isaaclab_arena_dir'),
                    ('gr00t', 'gr00t', 'native.yml', 'gr00t', 'gr00t_dir'),
                    ('lerobot', 'lerobot', 'main.yml', 'lerobot', 'lerobot_dir')):
                    selection = profile['components'].get(component, {})
                    if not selection.get('enabled') or selection['source']['mode'] != 'git':
                        continue
                    tasks = yaml.safe_load((ROOT / 'src/ansible/roles' / role / 'tasks' / task_file).read_text())
                    tasks += [child for task in list(tasks) for child in task.get('block', [])]
                    env = Environment(undefined=StrictUndefined)
                    if component == 'arena':
                        import shlex
                        env.filters['quote'] = shlex.quote
                        task = next(t for t in tasks if t.get('name') == 'Clone Isaac Lab Arena repository')
                        shell = env.from_string(task['shell']).render(**captured[0])
                        for variable in (consumer + '_git_repo', consumer + '_git_checkpoint', path_var):
                            self.assertIn(shlex.quote(artifact[variable]), shell)
                        rendered_clones[component] = {'shell': shell, 'executed': False}
                        continue
                    task = next(t for t in tasks if 'git' in t)
                    rendered = {key: env.from_string(task['git'][key]).render(**captured[0])
                                for key in ('repo', 'dest', 'version')}
                    self.assertEqual(rendered['repo'], artifact[consumer + '_git_repo'])
                    self.assertEqual(rendered['version'], artifact[consumer + '_git_checkpoint'])
                    self.assertEqual(rendered['dest'], artifact[path_var])
                    rendered_clones[component] = rendered
                CAPTURES.append({'entrypoint': 'image-' + provider, 'callback': PROVIDERS[provider],
                    'fixture': profile, 'report': report,
                    'ansible_variables': {k: v for k, v in captured[0].items() if 'password' not in k},
                    'rendered_clone_arguments': rendered_clones,
                    'template': 'src/packer/' + provider + '/isaac-workstation.pkr.hcl',
                    'actual_build': False, 'packer_process': 'mock', 'git_preflight': 'mock'})

    def test_conflicts_refuse_before_any_public_or_cloud_effect(self):
        from src.python.deploy_command import DeployCommand
        for provider, module in self.modules.items():
            for override in (['--isaacsim', SHA], ['--isaaclab', 'no'],
                             ['--isaaclab-arena', 'no'], ['--isaaclab-private-git', 'fixture'],
                             ['--demo', 'franka-manipulation'], ['--ssh-user', 'different-user']):
                with self.subTest(provider=provider, override=override), self.effects(module) as effects, \
                        mock.patch.object(DeployCommand, '_anonymous_ls_remote') as refs:
                    result = CliRunner().invoke(module.main, self.flags(provider) + override)
                    self.assertEqual(result.exit_code, 2, result.output + repr(result.exception))
                    self.assertIn('cannot combine', result.output)
                    refs.assert_not_called()
                    for effect in effects.values():
                        effect.assert_not_called()
        self.process.assert_not_called()

    def test_required_gaps_and_optional_unknown_fields_preserve_ansible_classification(self):
        profile = desired()
        profile['notes'] = [{'id': 'review-note', 'text': 'Unknown downstream requirement',
                             'required': False, 'support': 'unsupported'}]
        self.profile_file.write_text(yaml.safe_dump(profile))
        result = CliRunner().invoke(self.modules['gcp'].main, self.flags('gcp') + ['--dry-run'])
        self.assertEqual(result.exit_code, 0, result.output)
        report, _ = json.JSONDecoder().raw_decode(result.output)
        self.assertIn('notes.0.text', [item['field'] for item in report['software_profile']['warnings']])
        profile['notes'][0]['required'] = True
        self.profile_file.write_text(yaml.safe_dump(profile))
        for provider, module in self.modules.items():
            with self.subTest(provider=provider), self.effects(module) as effects:
                result = CliRunner().invoke(module.main, self.flags(provider))
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn('required unmapped', result.output)
                with self.assertRaisesRegex(ValueError, 'required unmapped'):
                    getattr(module, PROVIDERS[provider])({'software_profile': profile}, config)
                for effect in effects.values():
                    effect.assert_not_called()
        self.process.assert_not_called()

    def test_public_failure_refuses_all_image_paths_even_with_sha_selector(self):
        from src.python.deploy_command import DeployCommand
        from src.python.public_git import PublicGitError
        self.proof.side_effect = PublicGitError('synthetic proof refusal')
        for provider, module in self.modules.items():
            for response in (subprocess.CompletedProcess([], 128, '', 'private'),
                             subprocess.CompletedProcess([], 0, '', ''),
                             subprocess.CompletedProcess([], 0, 'not a ref advertisement', '')):
                with self.subTest(provider=provider, response=response.returncode), self.effects(module) as effects, \
                        mock.patch.object(DeployCommand, '_anonymous_ls_remote', return_value=response):
                    result = CliRunner().invoke(module.main, self.flags(provider))
                    self.assertEqual(result.exit_code, 2, result.output)
                    self.assertIn('Anonymous full-SHA commit proof failed', result.output)
                    for effect in effects.values():
                        effect.assert_not_called()
        self.process.assert_not_called()

    def test_latest_and_named_refs_use_public_advertisement_not_default_sources(self):
        from src.python.deploy_command import DeployCommand
        for provider, module in self.modules.items():
            profile = desired()
            profile['components']['sim']['source'].update(ref='latest', revision=None)
            self.profile_file.write_text(yaml.safe_dump(profile))
            captured = []
            with mock.patch.object(module.main, 'callback', side_effect=lambda **params: captured.append(params)), \
                    mock.patch.object(DeployCommand, '_anonymous_ls_remote', return_value=subprocess.CompletedProcess(
                        [], 0, 'c' * 40 + '\trefs/tags/v9.0.0\n', '')) as refs:
                result = CliRunner().invoke(module.main, self.flags(provider))
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                self.assertEqual(captured[0]['isaacsim'], 'v9.0.0')
                source = captured[0]['software_profile']['components']['sim']['source']
                self.assertEqual(source['ref'], 'v9.0.0')
                self.assertIsNone(source['revision'])
                self.assertEqual(refs.call_args.args[0][-1], source['repository'])
            profile['components']['sim']['source']['ref'] = 'missing'
            self.profile_file.write_text(yaml.safe_dump(profile))
            with self.effects(module) as effects, mock.patch.object(DeployCommand, '_anonymous_ls_remote',
                    return_value=subprocess.CompletedProcess([], 0, 'c' * 40 + '\trefs/heads/other\n', '')):
                result = CliRunner().invoke(module.main, self.flags(provider))
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn('Anonymous public repository/ref preflight failed', result.output)
                for effect in effects.values():
                    effect.assert_not_called()
        self.process.assert_not_called()
        self.proof.assert_not_called()

    def test_invalid_sources_reject_without_network_including_dry_run(self):
        for repository in ('git@github.com:fixture/IsaacSim.git', 'https://user:password@github.com/fixture/repo',
                           'file:///tmp/repository', 'http://github.com/fixture/repo'):
            profile = desired()
            profile['components']['sim']['source']['repository'] = repository
            self.profile_file.write_text(yaml.safe_dump(profile))
            for provider, module in self.modules.items():
                with self.subTest(provider=provider, repository=repository):
                    result = CliRunner().invoke(module.main, self.flags(provider) + ['--dry-run'])
                    self.assertEqual(result.exit_code, 2, result.output)
        self.process.assert_not_called()

    def test_host_forwarding_stages_resolved_profile_not_inaccessible_host_path(self):
        import shlex
        import sys
        from src.python.image_command_utils import forward_image_command
        root = self.tmp / 'checkout'
        root.mkdir()
        entry = root / 'image-gcp'
        entry.write_text('# synthetic entry location only\n')
        seen = []
        def container_consumer(argv, **kwargs):
            routed = shlex.split(argv[1])
            argument_file = root / Path(routed[-1]).relative_to('/app')
            arguments = json.loads(argument_file.read_text())
            source = arguments[arguments.index('--software-profile') + 1]
            self.assertTrue(source.startswith('/app/'), source)
            staged = root / Path(source).relative_to('/app')
            self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
            self.assertEqual(staged.parent.stat().st_mode & 0o777, 0o700)
            document = yaml.safe_load(staged.read_text())
            self.assertEqual(document['components']['sim']['source'], desired()['components']['sim']['source'])
            self.assertEqual(document['workspace'], desired()['workspace'])
            self.assertNotIn(str(self.profile_file), repr(arguments))
            seen.append(staged)
            return subprocess.CompletedProcess(argv, 0)
        self.process.side_effect = container_consumer
        for selection in (['--software-profile', str(self.profile_file)],
                          ['--software-profile=' + str(self.profile_file)]):
            with mock.patch.object(sys, 'argv', [str(entry), '--image-name', 'fixture', *selection]):
                self.assertEqual(forward_image_command(entry, self.modules['gcp'].main), 0)
        self.assertEqual(len(seen), 2)
        self.assertFalse(any(path.exists() for path in seen))

    def test_direct_image_callbacks_reject_conflicting_consumers_before_resources(self):
        self.process.side_effect = None
        self.process.return_value = subprocess.CompletedProcess([], 0, '', '')
        base = {'debug': False, 'dry_run': False, 'project': 'fixture-project', 'zone': 'us-central1-a',
                'region': 'fixture-region', 'isaac_workstation_instance_type': 'fixture-instance',
                'gpu_type': 'fixture-gpu', 'gpu_count': 1, 'isaacsim': SHA, 'isaaclab': 'no',
                'isaaclab_arena': 'no', 'demos': 'no', 'system_user_password': 'synthetic-fixture',
                'image_name': 'fixture', 'existing': 'fail', 'resource_group': 'fixture-group', 'login': False}
        for provider, module in self.modules.items():
            for overrides in ({'isaacsim': 'different'}, {'isaaclab': 'main'},
                              {'demos': 'franka-manipulation'}, {'ssh_user': 'other'},
                              {'isaaclab_private_git': 'private'}, {'install_gr00t': True}):
                with self.subTest(provider=provider, overrides=overrides), self.effects(module) as effects:
                    with self.assertRaisesRegex(ValueError, 'cannot combine'):
                        getattr(module, PROVIDERS[provider])({**base, 'software_profile': desired(), **overrides}, config)
                    for effect in effects.values():
                        effect.assert_not_called()
        self.process.assert_not_called()

    def test_profile_render_cli_advertises_same_packer_report(self):
        from src.python.workstation_profile_command import main
        result = CliRunner().invoke(main, ['render', str(self.profile_file), '--adapter', 'packer',
                                         '--target-home', '/home/ubuntu'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output), render_profile(desired(), 'packer', '/home/ubuntu'))
        self.process.assert_not_called()

    def test_packer_reuses_ansible_coverage_including_unverified_pin(self):
        profile = desired()
        expected = render_profile(profile, 'ansible', '/home/ubuntu')
        actual = render_profile(profile, 'packer', '/home/ubuntu')
        self.assertEqual(actual, {**expected, 'adapter': 'packer'})
        self.assertTrue(actual['render_supported'], actual['blockers'])
        self.assertFalse(actual['references_verified'])
        self.assertFalse(actual['runtime_verified'])
        self.assertFalse(actual['apply_supported'])
        self.assertEqual(actual['artifact']['isaacsim_git_checkpoint'], SHA)
        self.assertEqual(actual['coverage']['components.sim.source.ref']['status'], 'superseded')
        self.assertEqual(actual['coverage']['runtimes.kit.python']['status'], 'unspecified')


if __name__ == '__main__':
    unittest.main()
