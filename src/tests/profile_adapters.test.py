#!/usr/bin/env python3
"""Offline adapter contracts against actual consumer configuration."""
import importlib
import importlib.util
import unittest
from unittest import mock

from src.python.workstation_profile import resolve_profile


def adapter():
    assert importlib.util.find_spec('src.python.profile_adapters'), 'profile adapters missing'
    return importlib.import_module('src.python.profile_adapters')


def sim_only():
    return resolve_profile('minimal', {'components': {'lab': {'enabled': False}}})


class AdapterTests(unittest.TestCase):
    def test_local_standalone_maps_real_legacy_fields_offline(self):
        with mock.patch('socket.socket', side_effect=AssertionError('network')), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('process')):
            report = adapter().render_profile(sim_only(), 'local', '/home/reviewer')
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertFalse(report['apply_supported'])
        self.assertEqual(report['artifact']['simulation']['isaacsim'], {
            'enabled': True, 'version': '6.0.1', 'source_type': 'standalone',
            'install_dir': '/home/reviewer/IsaacSim'})
        self.assertNotIn('accept_eula', report['artifact']['simulation']['isaacsim'])
        self.assertFalse(report['artifact']['repositories']['isaaclab']['enabled'])
        self.assertEqual(report['coverage']['components.sim.source.version']['status'], 'mapped')

    def test_local_fork_ref_and_all_fields_have_honest_coverage(self):
        profile = resolve_profile('default', {'components': {'lab': {'source': {
            'repository': 'https://github.com/example/IsaacLab.git', 'ref': 'fork-only',
            'revision': 'a' * 40}}}})
        report = adapter().render_profile(profile, 'local', '/home/reviewer')
        source = report['artifact']['repositories']['isaaclab']
        self.assertEqual(source['repo'], 'https://github.com/example/IsaacLab.git')
        self.assertEqual(source['tag'], 'a' * 40)
        self.assertEqual(source['branch'], '')
        self.assertEqual(report['coverage']['components.lab.source.ref']['status'], 'superseded')
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertEqual(report['coverage']['runtimes.lab.torch']['status'], 'mapped')
        self.assertEqual(report['coverage']['runtimes.gr00t.manager']['status'], 'not_selected')
        def leaves(data, prefix=''):
            for key, value in data.items():
                path = f'{prefix}.{key}' if prefix else key
                if isinstance(value, dict):
                    yield from leaves(value, path)
                else:
                    yield path
        self.assertEqual(set(leaves(profile['profile'])), set(report['coverage']))
        self.assertEqual(report['artifact']['streaming']['provider'], 'none')
        self.assertFalse(report['artifact']['workspace']['auto_create_fork'])

    def test_ansible_maps_repos_without_substituting_git_for_unpinned_standalone(self):
        profile = resolve_profile('default', {'components': {'lab': {'source': {
            'repository': 'https://github.com/example/IsaacLab.git', 'ref': 'fork-only'}}}})
        report = adapter().render_profile(profile, 'ansible', '/home/remote')
        self.assertEqual(report['deploy_params']['isaacsim'], 'no')
        self.assertEqual(report['deploy_params']['isaaclab'], 'fork-only')
        self.assertEqual(report['deploy_params']['isaaclab_repo'], 'https://github.com/example/IsaacLab.git')
        self.assertEqual(report['artifact']['isaaclab_git_checkpoint'], 'fork-only')
        self.assertEqual(report['artifact']['conda_env_name'], 'isaaclab')
        self.assertEqual(report['artifact']['conda_python_version'], '3.12')
        self.assertIn('components.sim.source.sha256', [x['field'] for x in report['blockers']])
        self.assertEqual(report['artifact']['isaacsim_git_checkpoint'], 'no')
        self.assertTrue(report['artifact']['profile_isaacsim_archive_enabled'])
        self.assertFalse(report['render_supported'])
        self.assertIn('standalone', report['coverage']['components.sim.source.mode']['consumer'])

    def test_named_workspace_translates_target_home_not_controller(self):
        profile = sim_only()
        profile['profile']['workspace'] = {'root': '~/Documents/GitHub', 'layout': 'named', 'name': 'Bored Engineer'}
        profile['profile']['components']['gr00t']['enabled'] = True
        local = adapter().render_profile(profile, 'local', '/home/alice')
        self.assertEqual(local['artifact']['workspace']['root'], '/home/alice/Documents/GitHub')
        self.assertEqual(local['artifact']['workspace']['name'], 'Bored Engineer')
        self.assertTrue(local['render_supported'], local['blockers'])
        ansible = adapter().render_profile(profile, 'ansible', '/home/bob')
        self.assertEqual(ansible['artifact']['gr00t_dir'], '/home/bob/Documents/GitHub/Bored Engineer/Isaac-GR00T')
        self.assertEqual(ansible['coverage']['workspace.name']['status'], 'mapped')
        self.assertFalse(ansible['apply_supported'])
        for home in ('/', '~', '/home/../other', '/home/x\nansible_connection=local'):
            with self.subTest(home=home), self.assertRaises(ValueError):
                adapter().render_profile(profile, 'local', home)

    def test_sparse_draft_and_optional_unknown_items_do_not_silently_disappear(self):
        profile = {'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'sparse',
                   'defaults': False, 'draft': False,
                   'custom_dependencies': [{'id': 'extra', 'name': 'unmapped-tool', 'version': '1.2',
                       'environment': None, 'location': None, 'purpose': 'custom workflow',
                       'source': None, 'placement': 'unknown', 'required': False, 'support': 'unsupported'}]}
        report = adapter().render_profile(profile, 'local', '/home/tester')
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertTrue(report['warnings'])
        self.assertFalse(report['artifact']['simulation']['isaacsim']['enabled'])
        self.assertTrue(all(not x['enabled'] for x in report['artifact']['repositories'].values()))
        profile['custom_dependencies'][0]['required'] = True
        self.assertFalse(adapter().render_profile(profile, 'local', '/home/tester')['render_supported'])
        profile['custom_dependencies'] = []
        profile['draft'] = True
        report = adapter().render_profile(profile, 'ansible', '/home/tester')
        self.assertIn('draft', [x['field'] for x in report['blockers']])
        self.assertFalse(report['render_supported'])

    def test_missing_selected_intent_and_conflicting_wheel_pins_block(self):
        sparse = {'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'sparse',
                  'defaults': False, 'components': {'sim': {'enabled': True}}}
        report = adapter().render_profile(sparse, 'local', '/home/tester')
        self.assertFalse(report['render_supported'])
        self.assertIn('components.sim.source', [x['field'] for x in report['blockers']])
        desired = resolve_profile('default')['profile']
        desired['runtimes']['lab']['cuda_runtime'] = '12.4'
        report = adapter().render_profile(desired, 'ansible', '/home/tester')
        self.assertEqual(report['coverage']['runtimes.lab.cuda_runtime']['status'], 'unsupported')
        desired['components']['sim']['enabled'] = False
        with self.assertRaises(ValueError):
            adapter().render_profile(desired, 'local', '/home/tester')

    def test_unresolved_inheritance_is_never_treated_as_metadata_only(self):
        raw = {'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'inherited', 'extends': 'full'}
        with self.assertRaisesRegex(ValueError, 'resolve'):
            adapter().render_profile(raw, 'local', '/home/tester')

    def test_environment_declaration_matches_real_lab_consumer_or_stays_explicit(self):
        desired = resolve_profile('default')['profile']
        desired['environments'] = [{'id': 'lab-env', 'name': 'isaaclab', 'manager': 'conda',
            'python': '3.12', 'placement': 'environment', 'location': '~/miniconda3/envs/isaaclab',
            'required': True, 'support': 'unsupported'}]
        desired['notes'] = [{'id': 'note', 'text': 'Keep custom workflow', 'required': False, 'support': 'unsupported'}]
        report = adapter().render_profile(desired, 'ansible', '/home/tester')
        self.assertEqual(report['coverage']['environments.0.name']['status'], 'mapped')
        self.assertNotIn('notes.0.text', [x['field'] for x in report['blockers']])
        self.assertIn('notes.0.text', [x['field'] for x in report['warnings']])
        desired['environments'][0]['placement'] = 'container'
        report = adapter().render_profile(desired, 'ansible', '/home/tester')
        self.assertIn('environments.0.name', [x['field'] for x in report['blockers']])

    def test_ansible_reserved_disabled_selector_cannot_disable_enabled_lab(self):
        desired = resolve_profile('default')['profile']
        desired['components']['lab']['source']['ref'] = 'no'
        report = adapter().render_profile(desired, 'ansible', '/home/tester')
        self.assertEqual(report['coverage']['components.lab.source.ref']['status'], 'unsupported')
        self.assertIn('disabled sentinel', report['coverage']['components.lab.source.ref']['reason'])

    def test_explicit_git_sim_has_real_source_directory_not_archive_substitution(self):
        desired = resolve_profile('default')['profile']
        desired['components']['sim']['source'] = {'mode': 'git',
            'repository': 'https://github.com/example/IsaacSim.git', 'ref': 'fork-only', 'revision': None}
        desired['workspace'] = {'root': '~/Documents/GitHub', 'layout': 'named', 'name': 'Robotics Team'}
        report = adapter().render_profile(desired, 'ansible', '/home/tester')
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertFalse(report['artifact']['profile_isaacsim_archive_enabled'])
        self.assertEqual(report['artifact']['isaacsim_source_dir'], '/home/tester/Documents/GitHub/Robotics Team/IsaacSim')
        self.assertEqual(report['deploy_params']['isaacsim_repo'], 'https://github.com/example/IsaacSim.git')
        local = adapter().render_profile(desired, 'local', '/home/tester')
        self.assertIn('components.sim.source.mode', [x['field'] for x in local['blockers']])

    def test_local_optional_archive_url_is_not_an_unconsumed_override(self):
        desired = sim_only()['profile']
        desired['components']['sim']['source']['url'] = None
        report = adapter().render_profile(desired, 'local', '/home/tester')
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertEqual(report['coverage']['components.sim.source.url']['status'], 'unspecified')
        desired['components']['sim']['source']['url'] = 'https://artifacts.example.org/sim-6.0.1.zip'
        report = adapter().render_profile(desired, 'local', '/home/tester')
        self.assertIn('components.sim.source.sha256', [x['field'] for x in report['blockers']])
        desired['components']['sim']['source']['sha256'] = 'a' * 64
        report = adapter().render_profile(desired, 'local', '/home/tester')
        self.assertTrue(report['render_supported'], report['blockers'])
        self.assertEqual(report['artifact']['simulation']['isaacsim']['url'], desired['components']['sim']['source']['url'])


if __name__ == '__main__':
    unittest.main()
