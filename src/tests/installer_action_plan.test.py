"""Offline concrete action contract; never execute installer modules."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
CORE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core'

def load():
    spec = importlib.util.spec_from_file_location('action_plan', CORE / 'action_plan.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class PlannerTests(unittest.TestCase):
    def test_pure_named_workspace_concrete_plan_uses_explicit_home(self):
        self.assertTrue((CORE / 'action_plan.py').exists(), 'concrete planner missing')
        api = load()
        profile = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'BoredEngineer'}}
        with patch('os.stat', side_effect=AssertionError('planner probed filesystem')), patch('os.lstat', side_effect=AssertionError('planner probed filesystem')):
            plan = api.build_action_plan(profile, target_home='/synthetic/home', observed={'/synthetic/home/work': {'state': 'missing'}, '/synthetic/home/work/BoredEngineer': {'state': 'missing'}})
        self.assertEqual([a['target'] for a in plan['actions']], ['/synthetic/home/work', '/synthetic/home/work/BoredEngineer'])
        self.assertEqual([a['status'] for a in plan['actions']], ['would_change', 'would_change'])
        self.assertTrue(all(a['operation'] == 'mkdir' for a in plan['actions']))
        self.assertTrue(all(a['preconditions'] == {'state': 'missing'} for a in plan['actions']))
        self.assertEqual(plan, api.build_action_plan(profile, target_home='/synthetic/home', observed={'/synthetic/home/work': {'state': 'missing'}, '/synthetic/home/work/BoredEngineer': {'state': 'missing'}}))
        json.dumps(plan)

    def test_components_runtimes_tools_settings_have_targets_and_gates(self):
        api = load()
        profile = {'workspace': {'root': '~/work', 'layout': 'flat'},
                   'components': {'lab': {'enabled': True, 'source': {'repository': 'https://github.com/isaac-sim/IsaacLab.git', 'ref': 'main'}}, 'gr00t': {'enabled': False}},
                   'runtimes': {'lab': {'manager': 'conda', 'environment': 'lab-v2', 'python': '3.11'}},
                   'tools': {'pytest': {'enabled': True, 'manager': 'pip', 'version': '8.0', 'placement': 'environment', 'environment': 'lab-v2'}},
                   'settings': {'vscode': {'enabled': True}}, 'hardware': {'enforce_x11': True}}
        actions = {a['id']: a for a in api.build_action_plan(profile, target_home='/fixture/home')['actions']}
        self.assertEqual(actions['component.lab']['target'], '/fixture/home/work/IsaacLab')
        self.assertEqual(actions['component.gr00t']['status'], 'excluded')
        self.assertEqual(actions['runtime.lab']['target'], 'unresolved-runtime-prefix:conda:lab-v2')
        self.assertIn('conda', actions['runtime.lab']['unsupported_reason'])
        self.assertEqual(actions['tool.pytest']['target'], 'environment:lab-v2:pytest')
        self.assertEqual(actions['setting.vscode']['status'], 'blocked')
        self.assertTrue(actions['hardware.enforce_x11']['policy']['high_risk'])
        for action in actions.values():
            for field in ('reason', 'effects', 'preconditions', 'policy', 'execution_supported', 'unsupported_reason'):
                self.assertIn(field, action)

    def test_managed_evidence_never_adopts_foreign_resources_and_files(self):
        api = load()
        self.assertTrue(hasattr(api, 'inspect_adoption'), 'adoption policy missing')
        profile = {'workspace': {'root': '/fixture/work'}, 'managed_files': [{'path': '/fixture/work/config-v1.json', 'content': '{}\n'}]}
        observations = {'/fixture/work': {'state': 'directory', 'managed': False}, '/fixture/work/config-v1.json': {'state': 'file', 'managed': False, 'sha256': api.hash_content('{}\n')}}
        plan = api.build_action_plan(profile, target_home='/fixture', observed=observations)
        self.assertEqual([a['status'] for a in plan['actions']], ['satisfied', 'blocked'])
        observations['/fixture/work/config-v1.json']['managed'] = True
        self.assertEqual(api.build_action_plan(profile, target_home='/fixture', observed=observations)['actions'][1]['status'], 'satisfied')
        observations['/fixture/work/config-v1.json']['sha256'] = '0' * 64
        self.assertEqual(api.build_action_plan(profile, target_home='/fixture', observed=observations)['actions'][1]['status'], 'blocked')
        desired = {'repository': 'https://github.com/example/repo.git', 'revision': 'a' * 40}
        clean = {**desired, 'dirty': False, 'untracked': False, 'ignored': False, 'worktrees': False, 'nested': False, 'local_commits': False}
        self.assertFalse(api.inspect_adoption(desired, clean)['eligible'])
        policy = {'reviewed': True, 'permitted_actions': ['inspect']}
        self.assertTrue(api.inspect_adoption(desired, clean, policy)['eligible'])
        for risk in ('dirty', 'untracked', 'ignored', 'worktrees', 'nested', 'local_commits'):
            self.assertFalse(api.inspect_adoption(desired, {**clean, risk: True}, policy)['eligible'])
            uncertain = dict(clean); uncertain.pop(risk)
            self.assertFalse(api.inspect_adoption(desired, uncertain, policy)['eligible'])
        self.assertFalse(api.inspect_adoption(desired, {**clean, 'repository': 'other'}, policy)['eligible'])

    def test_sparse_shared_profile_covers_custom_service_and_unused_runtime(self):
        api = load()
        profile = {'kind': 'workstation-profile', 'schema_version': 'v1alpha1', 'defaults': False, 'draft': True,
                   'workspace': {'name': 'ReviewedOnly'},
                   'components': {'lab': {'enabled': False}},
                   'runtimes': {'lab': {'manager': 'conda', 'environment': 'lab'}},
                   'custom_dependencies': [{'id': 'custom.foo', 'name': 'foo', 'placement': 'unknown', 'required': True, 'support': 'unsupported'}],
                   'serving': {'enabled': False, 'port': 5556, 'model': {'repository': 'org/model'}}}
        plan = api.build_action_plan(profile, target_home='/fixture/home')
        actions = {a['id']: a for a in plan['actions']}
        self.assertEqual(actions['workspace.root']['status'], 'unknown')
        self.assertEqual(actions['runtime.lab']['status'], 'excluded')
        self.assertEqual(actions['serving']['status'], 'excluded')
        self.assertNotIn('serving.port', actions)
        self.assertEqual(actions['custom.foo']['status'], 'blocked')
        self.assertTrue(actions['custom.foo']['policy']['required'])
        self.assertEqual(set(plan['coverage']), set(profile))
        unknown = api.build_action_plan({'future_extension': {'x': 1}}, target_home='/fixture/home')
        self.assertEqual(unknown['actions'][0]['status'], 'blocked')

    def test_repo_targets_use_shared_shell_resolver_and_public_defaults(self):
        sys.path.insert(0, str(CORE.parents[2]))
        from src.python import workstation_profile, profile_adapters
        api = load()
        profile = workstation_profile.resolve_profile('default')['profile']
        consumer = profile_adapters.render_profile(profile, 'local', '/fixture/home')['artifact']
        with patch.object(api._paths, 'resolve_paths', wraps=api._paths.resolve_paths) as resolver:
            plan = api.build_action_plan(profile, target_home='/fixture/home')
        self.assertTrue(resolver.called, 'planner must call the same resolver as the shell')
        actions = {a['id']: a for a in plan['actions']}
        expected = api._paths.resolve_paths(home='/fixture/home', repo='IsaacLab', slug=consumer['repositories']['isaaclab']['repo'], root=consumer['workspace']['root'], layout=consumer['workspace']['layout'])
        self.assertEqual(actions['component.lab']['target'], expected['destination'])
        profile['workspace'] = {'root': '~/work', 'layout': 'org', 'default_owner': 'FixtureOwner'}
        unknown = {a['id']: a for a in api.build_action_plan(profile, target_home='/fixture/home')['actions']}
        self.assertEqual(unknown['component.lab']['status'], 'blocked')
        self.assertEqual(unknown['component.lab']['target'], 'unresolved-workspace:lab')

    def test_shared_public_yaml_plan_targets_match_actual_local_consumer(self):
        sys.path.insert(0, str(CORE.parents[2]))
        from src.python import workstation_profile, profile_adapters
        api = load()
        for preset in workstation_profile.PRESETS:
            profile = workstation_profile.resolve_profile(preset)['profile']
            profile['workspace'] = {'root': '~/work', 'layout': 'named', 'name': 'FixtureTeam'}
            actions = {a['id']: a for a in api.build_action_plan(profile, target_home='/fixture/home')['actions']}
            consumer = profile_adapters.render_profile(profile, 'local', '/fixture/home')['artifact']
            self.assertEqual(actions['component.sim']['target'], consumer['simulation']['isaacsim']['install_dir'])
            self.assertEqual(actions['component.sim']['operation'], 'artifact_install')
            self.assertEqual(actions['runtime.gr00t']['target'], '/fixture/home/work/FixtureTeam/Isaac-GR00T/.venv')
            self.assertTrue(actions['runtime.lab']['target'].startswith('unresolved-runtime-prefix:'))
            self.assertIn(actions['runtime.lab']['status'], ('unknown', 'excluded'))

    def test_all_supplied_evidence_is_validated_before_planning(self):
        api = load()
        for evidence in ([], False, '', {'/unselected': {'secret': 'never-echo'}}, {'/unselected': {'managed': 'yes'}}):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                api.build_action_plan({}, target_home='/fixture/home', observed=evidence)

    def test_standalone_artifact_and_legacy_layout_are_not_fake_repo_plans(self):
        api = load()
        profile = {'workspace': {'root': '~/work', 'layout': 'auto'}, 'components': {'sim': {'enabled': True, 'path': '~/Sim-v2', 'source': {'mode': 'standalone', 'version': '6.0.1'}}, 'lab': {'enabled': True, 'source': {'repository': 'https://github.com/isaac-sim/IsaacLab.git', 'ref': 'main'}}}}
        actions = {a['id']: a for a in api.build_action_plan(profile, target_home='/fixture/home')['actions']}
        self.assertEqual(actions['component.sim']['operation'], 'artifact_install')
        self.assertEqual(actions['component.sim']['target'], '/fixture/home/Sim-v2')
        self.assertIn('EULA', actions['component.sim']['unsupported_reason'])
        self.assertEqual(actions['workspace.root']['status'], 'unknown')
        self.assertEqual(actions['component.lab']['target'], 'unresolved-workspace:lab')
        self.assertEqual(actions['component.lab']['status'], 'blocked', 'legacy owner spelling cannot silently choose a flat target')

if __name__ == '__main__':
    unittest.main()
