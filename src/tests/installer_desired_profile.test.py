"""Observation/review -> actual shared YAML; disposable metadata only."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.python import workstation_profile as wp
CORE = ROOT / 'isaac-installer/lib/core'


def module(name):
    spec = importlib.util.spec_from_file_location(name, CORE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


discovery = module('profile_discovery')


class DesiredTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((CORE / 'desired_profile.py').exists(), 'desired bridge missing')
        self.bridge = module('desired_profile')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        baseline = discovery.observe(workspaces=[{'id': 'main', 'name': 'Robotics Team', 'root': str(self.root)}])
        return baseline, discovery.propose(baseline)

    def roundtrip(self, result):
        text = yaml.safe_dump(result['profile'])
        with patch.object(Path, 'open', side_effect=AssertionError('preset/file read')):
            self.assertEqual(wp.parse_profile_text(text), result['profile'])
        path = self.root / 'desired.yaml'
        path.write_text(text)
        self.assertEqual(wp.load_profile(path), result['profile'])
        return path

    def alternative_fixture(self, same_name=False):
        import json
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('a' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/GR00T.git\n')
        sources = []
        for identifier, placement in [('host', 'host'), ('container', 'container')]:
            directory = self.root / identifier
            directory.mkdir()
            path = directory / 'environment.json'
            name = 'robot' if same_name else identifier
            path.write_text(json.dumps({'name': name, 'manager': 'uv', 'python': '3.11', 'tools': [], 'notes': []}))
            sources.append({'id': identifier, 'path': str(path), 'format': 'environment-json',
                            'environment': name, 'placement': placement, 'runtime': 'gr00t'})
        baseline = discovery.observe(git_sources=[{'id': 'robot', 'root': str(self.root),
            'git_dir': str(git), 'common_dir': str(git), 'ref_paths': [], 'component': 'gr00t'}], metadata_sources=sources)
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=['gr00t'])
        candidate = discovery.review(candidate, 'component:gr00t.source', 'accept')
        candidate = discovery.review(candidate, 'runtime:gr00t', 'edit',
            value={'manager': 'uv', 'environment': 'robot' if same_name else 'host', 'python': '3.11'})
        candidate = discovery.review(candidate, 'environment:host', 'accept')
        return baseline, candidate, sources

    def test_chosen_reviewed_host_runtime_is_not_vetoed_by_container_alternative(self):
        baseline, candidate, _ = self.alternative_fixture()
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(result['complete'], result['review']['required_unresolved'])
        self.assertEqual(result['profile']['components']['gr00t']['execution'], 'native')
        self.assertEqual(result['profile']['runtimes']['gr00t']['environment'], 'host')
        self.assertEqual(result['review']['fields'], candidate['fields'])
        self.roundtrip(result)

    def test_observe_review_manual_sim_intents_exports_nonempty_sim_lab(self):
        import json
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('d' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/IsaacLab.git\n')
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'isaaclab', 'manager': 'conda', 'python': '3.11',
                                    'tools': [], 'notes': []}))
        baseline = discovery.observe(workspaces=[{'id': 'main', 'name': 'Team', 'root': str(self.root)}],
            git_sources=[{'id': 'lab', 'root': str(self.root), 'git_dir': str(git), 'common_dir': str(git),
                          'ref_paths': [], 'component': 'lab'}], metadata_sources=[{'id': 'lab', 'path': str(path),
                          'format': 'environment-json', 'environment': 'isaaclab', 'placement': 'host', 'runtime': 'lab'}])
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=['sim', 'lab'])
        for field_id in ('workspace:main.root', 'workspace:main.name', 'workspace:main.layout',
                         'component:lab.source', 'runtime:lab', 'environment:lab'):
            candidate = discovery.review(candidate, field_id, 'accept')
        self.assertFalse(self.bridge.export_candidate(baseline, candidate)['complete'])
        source = {'mode': 'standalone', 'version': '5.0.0', 'sha256': 'c' * 64}
        kit = {'manager': 'bundled', 'environment': 'kit', 'python': '3.11'}
        for field_id, value in [('component:sim.source', source), ('runtime:kit', kit),
                                ('component:sim.execution', 'native')]:
            candidate = discovery.review(candidate, field_id, 'declare', value=value, reason='Explicit desired intent')
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(result['complete'], result['review']['required_unresolved'])
        self.assertEqual(result['profile']['components']['sim'], {
            'enabled': True, 'source': source, 'runtime': 'kit', 'execution': 'native'})
        self.assertEqual(result['profile']['components']['lab']['source']['revision'], 'd' * 40)
        self.assertEqual(result['profile']['runtimes']['kit'], kit)
        declared = [f for f in result['review']['fields'] if f['rationale'] == 'user_declared_intent']
        self.assertEqual(len(declared), 3)
        self.assertTrue(all(f['evidence'] == [] and f['suggested_value'] is None for f in declared))
        self.assertEqual(result['review']['conformance'], 'not_evaluated')
        self.assertFalse(wp.resolve_document(result['profile'])['ready_for_apply'])
        self.roundtrip(result)

    def test_runtime_collision_is_required_draft_gap_and_review_can_correct_it(self):
        baseline = discovery.observe()
        candidate = discovery.review(discovery.propose(baseline), 'components.selection',
                                     'edit', value=['gr00t', 'lerobot'])
        for component, manager in [('gr00t', 'uv'), ('lerobot', 'conda')]:
            for field_id, value in [
                ('component:' + component + '.source', {
                    'mode': 'git', 'repository': 'https://github.com/example/' + component + '.git',
                    'ref': 'a' * 40, 'revision': 'a' * 40}),
                ('component:' + component + '.execution', 'native'),
                ('runtime:' + component, {'manager': manager, 'environment': 'same'}),
            ]:
                candidate = discovery.review(candidate, field_id, 'declare', value=value)
        original = copy.deepcopy((baseline, candidate))
        with patch('builtins.open', side_effect=AssertionError('unexpected file read')), \
                patch.object(Path, 'open', side_effect=AssertionError('unexpected preset read')):
            result = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(result['complete'])
        self.assertTrue(result['profile']['draft'])
        self.assertFalse(result['review']['intent_complete'])
        self.assertEqual(result['review']['required_unresolved'], [
            {'field_id': 'dependencies', 'reason': 'dependency_intent_unresolved', 'required': True}])
        self.assertEqual(result['review']['fields'], candidate['fields'])
        self.assertEqual((baseline, candidate), original)
        self.assertEqual(result['profile']['runtimes'], {
            'gr00t': {'manager': 'uv', 'environment': 'same'},
            'lerobot': {'manager': 'conda', 'environment': 'same'}})
        self.roundtrip(result)
        resolved = wp.resolve_document(result['profile'])
        self.assertIn({'field': 'dependencies', 'reason': 'dependency_intent_unresolved'},
                      resolved['unresolved'])
        self.assertFalse(resolved['ready_for_apply'])
        with self.assertRaisesRegex(wp.ProfileError, 'Runtime environments must be isolated'):
            wp.resolve_document({**result['profile'], 'draft': False})
        corrected = discovery.review(candidate, 'runtime:lerobot', 'edit',
                                     value={'manager': 'conda', 'environment': 'lerobot'})
        positive = self.bridge.export_candidate(baseline, corrected)
        self.assertTrue(positive['complete'], positive['review']['required_unresolved'])
        self.assertFalse(positive['profile']['draft'])
        self.assertTrue(positive['review']['intent_complete'])
        self.assertEqual(positive['review']['fields'], corrected['fields'])
        self.assertNotIn({'field': 'dependencies', 'reason': 'dependency_intent_unresolved'},
                         wp.resolve_document(positive['profile'])['unresolved'])
        self.roundtrip(positive)

    def test_explicit_execution_rejection_cannot_be_overridden_by_observed_host(self):
        baseline, candidate, _ = self.alternative_fixture()
        candidate = discovery.review(candidate, 'component:gr00t.execution', 'declare', value='native')
        for decision in ('reject', 'defer'):
            blocked = discovery.review(candidate, 'component:gr00t.execution', decision)
            result = self.bridge.export_candidate(baseline, blocked)
            self.assertFalse(result['complete'], decision)
            self.assertNotIn('execution', result['profile']['components']['gr00t'])

    def test_all_known_manual_source_runtime_execution_fields_roundtrip(self):
        baseline, candidate = self.fixture()
        for field in candidate['fields']:
            candidate = discovery.review(candidate, field['id'], 'edit', value=list(wp.COMPONENTS) if
                                         field['id'] == 'components.selection' else field['value'])
        declarations = {}
        for component in wp.COMPONENTS:
            declarations['component:' + component + '.source'] = {
                'mode': 'git', 'repository': 'https://github.com/example/' + component + '.git',
                'ref': 'reviewed-branch', 'revision': 'd' * 40}
            declarations['component:' + component + '.execution'] = 'native'
        for runtime in wp.RUNTIMES:
            declarations['runtime:' + runtime] = {'manager': wp.RUNTIME_MANAGERS[runtime], 'environment': runtime,
                'python': '3.11', 'torch': '2.7.0', 'torchvision': '0.22.0', 'cuda_runtime': '12.8', 'architecture': 'sm_89'}
        for field_id, value in declarations.items():
            candidate = discovery.review(candidate, field_id, 'declare', value=value)
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(result['complete'], result['review']['required_unresolved'])
        self.assertEqual(set(result['profile']['runtimes']), set(wp.RUNTIMES))
        self.assertTrue(all(c['enabled'] and c['execution'] == 'native' for c in result['profile']['components'].values()))
        for field_id, value in declarations.items():
            self.assertEqual(next(f for f in result['review']['fields'] if f['id'] == field_id)['value'], value)
        self.roundtrip(result)
        self.assertFalse(wp.resolve_document(result['profile'])['ready_for_apply'])

    def test_matching_placement_choice_and_selected_unknown_evidence_remain_visible(self):
        baseline, candidate, sources = self.alternative_fixture(same_name=True)
        self.assertTrue(self.bridge.export_candidate(baseline, candidate)['complete'])
        # Re-observe only synthetic sources; a malformed selected host manifest
        # keeps explicit edited intent separate from incomplete evidence.
        Path(sources[0]['path']).write_text('{')
        changed = discovery.observe(metadata_sources=sources)
        current = discovery.propose(changed, previous=candidate)
        current = discovery.review(current, 'runtime:gr00t', 'edit',
            value={'manager': 'uv', 'environment': 'robot', 'python': '3.11'})
        host = next(f for f in candidate['fields'] if f['id'] == 'environment:host')['value']
        current = discovery.review(current, 'environment:host', 'edit', value=host)
        result = self.bridge.export_candidate(changed, current)
        self.assertFalse(result['complete'], 'unselected repository evidence still gates')
        self.assertTrue(result['review']['observation_incomplete'])
        coverage = next(x for x in result['review']['observation_coverage'] if x['id'] == 'environment:host')
        self.assertEqual(coverage['status'], 'unknown')
        self.assertEqual(coverage['reason'], 'invalid_incomplete_or_oversize_metadata')
        self.assertEqual(result['profile']['runtimes']['gr00t']['environment'], 'robot')
        self.assertEqual(result['review']['conformance'], 'not_evaluated')

    def test_reviewed_pypi_intent_reaches_real_ansible_mapper_after_export(self):
        import json
        from src.python.profile_adapters import render_profile
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'isaaclab', 'manager': 'conda', 'python': '3.11',
            'tools': [{'name': 'custom-tool', 'version': '1.2.3', 'source': None, 'purpose': None}], 'notes': []}))
        baseline = discovery.observe(metadata_sources=[{'id': 'lab', 'path': str(path), 'format': 'environment-json',
            'environment': 'isaaclab', 'placement': 'environment', 'runtime': 'lab'}])
        candidate = discovery.review(discovery.propose(baseline), 'components.selection', 'edit', value=['sim', 'lab'])
        candidate = discovery.review(candidate, 'runtime:lab', 'accept')
        candidate = discovery.review(candidate, 'environment:lab', 'accept')
        fields = {f['id']: f for f in candidate['fields']}
        candidate = discovery.review(candidate, 'tool:lab:custom-tool', 'edit', required=True,
            value={**fields['tool:lab:custom-tool']['value'], 'source': 'pypi', 'purpose': 'Robot tooling',
                   'location': '/home/tester/miniconda3/envs/isaaclab'})
        declarations = {'component:sim.source': {'mode': 'standalone', 'version': '6.0.1',
            'sha256': 'a' * 64, 'url': 'https://artifacts.example.org/sim-6.0.1.zip'},
            'component:lab.source': {'mode': 'git', 'repository': 'https://github.com/example/IsaacLab.git',
                                     'ref': 'reviewed-branch', 'revision': 'b' * 40},
            'runtime:kit': {'manager': 'bundled', 'environment': 'kit'}, 'component:sim.execution': 'native'}
        for field_id, value in declarations.items():
            candidate = discovery.review(candidate, field_id, 'declare', value=value)
        exported = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(exported['complete'], 'generic required custom support remains consumer-specific')
        self.assertTrue(exported['review']['intent_complete'])
        self.assertFalse(exported['profile']['draft'])
        rendered = render_profile(wp.resolve_document(exported['profile']), 'ansible', '/home/tester')
        self.assertTrue(rendered['render_supported'], rendered['blockers'])
        self.assertEqual(rendered['artifact']['profile_lab_packages'], ['custom-tool==1.2.3'])
        self.assertEqual(rendered['artifact']['isaacsim_archive_url'], declarations['component:sim.source']['url'])
        self.assertEqual(rendered['artifact']['isaacsim_archive_sha256'], 'a' * 64)
        self.assertEqual(exported['profile']['components']['sim']['source'], declarations['component:sim.source'])
        self.roundtrip(exported)

    def test_reviewed_tool_can_use_consumer_environment_without_losing_origin(self):
        import json
        from src.python.profile_adapters import render_profile
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'isaaclab', 'manager': 'conda', 'python': '3.12',
            'tools': [{'name': 'custom-tool', 'version': '1.2.3', 'source': None, 'purpose': None}],
            'notes': []}))
        selections = [{'id': 'lab', 'path': str(path), 'format': 'environment-json',
                       'environment': 'isaaclab', 'placement': 'environment', 'runtime': 'lab'}]
        baseline = discovery.observe(metadata_sources=selections)
        original = copy.deepcopy(baseline)
        candidate = discovery.propose(baseline)
        field = next(f for f in candidate['fields'] if f['id'] == 'tool:lab:custom-tool')
        self.assertEqual(field['value']['location'], str(path))
        desired_tool = {**field['value'], 'source': 'pypi', 'purpose': 'Robot tooling', 'location': None}
        # Null means use the consumer's selected runtime, not erase the origin.
        candidate = discovery.review(candidate, field['id'], 'edit', value=desired_tool)
        for value in ('', 'relative/path', '/tmp/../unsafe', [], {}):
            with self.subTest(location=value), self.assertRaises(ValueError):
                discovery.review(candidate, field['id'], 'edit', value={**desired_tool, 'location': value})
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=['sim', 'lab'])
        for identifier in ('runtime:lab', 'environment:lab'):
            candidate = discovery.review(candidate, identifier, 'accept')
        for identifier, value in {
            'component:sim.source': {'mode': 'standalone', 'version': '6.0.1',
                'sha256': 'a' * 64, 'url': 'https://artifacts.example.org/synthetic.zip'},
            'component:lab.source': {'mode': 'git', 'repository': 'https://github.com/example/IsaacLab.git',
                'ref': 'b' * 40, 'revision': 'b' * 40},
            'runtime:kit': {'manager': 'bundled', 'environment': 'kit'},
            'component:sim.execution': 'native', 'component:lab.execution': 'native',
        }.items():
            candidate = discovery.review(candidate, identifier, 'declare', value=value)
        rescanned = discovery.observe(metadata_sources=selections, previous_baseline=baseline)
        candidate = discovery.propose(rescanned, previous=candidate)
        exported = self.bridge.export_candidate(rescanned, candidate)
        self.assertTrue(exported['complete'])
        self.assertEqual(exported['profile']['custom_dependencies'][0]['location'], None)
        for adapter in ('local', 'ansible'):
            rendered = render_profile(wp.resolve_document(exported['profile']), adapter, '/fixture/home')
            self.assertTrue(rendered['render_supported'], rendered['blockers'])
            expected = rendered['artifact']['runtimes']['lab']['packages'] if adapter == 'local' else rendered['artifact']['profile_lab_packages'][0]
            self.assertEqual(expected, 'custom-tool==1.2.3')
        self.assertEqual(baseline, original)
        self.assertIn(str(path), discovery.original_observed_roots(rescanned))
        field = next(f for f in candidate['fields'] if f['id'] == 'tool:lab:custom-tool')
        self.assertEqual(field['suggested_value']['location'], str(path))
        self.assertEqual(field['state'], 'accepted')
        self.assertFalse(field['evidence_changed'])
        # The observed metadata validator still requires an actual selected path.
        with self.assertRaises(ValueError):
            discovery._metadata.validate_tool(desired_tool, discovery._path)

    def test_unreviewed_draft_is_loadable_without_inferred_approvals(self):
        baseline, candidate = self.fixture()
        original = copy.deepcopy((baseline, candidate))
        result = self.bridge.export_candidate(baseline, candidate, name='robotics')
        self.assertFalse(result['complete'])
        self.assertTrue(result['profile']['draft'])
        self.assertIs(result['profile']['defaults'], False)
        self.assertNotIn('extends', result['profile'])
        self.assertFalse(result['profile'].get('components'))
        self.assertNotIn('workspace', result['profile'])
        self.assertEqual(result['review']['fields'], candidate['fields'])
        self.assertTrue(result['review']['required_unresolved'])
        self.roundtrip(result)
        self.assertEqual((baseline, candidate), original)

    def test_reviewed_workspace_and_explicit_empty_selection_are_complete(self):
        baseline, candidate = self.fixture()
        for field in candidate['fields']:
            candidate = discovery.review(candidate, field['id'], 'edit', value=[] if
                                         field['id'] == 'components.selection' else field['value'])
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(result['complete'])
        self.assertFalse(result['profile']['draft'])
        self.assertEqual(result['profile']['workspace'], {
            'root': str(self.root), 'name': 'Robotics Team', 'layout': 'named'})
        self.assertEqual(result['profile']['components'], {name: {'enabled': False} for name in wp.COMPONENTS})
        self.assertFalse(result['review']['required_unresolved'])
        self.assertEqual({c['status'] for c in result['review']['coverage']}, {'mapped'})
        self.roundtrip(result)

    def test_enabled_components_do_not_invent_source_or_runtime(self):
        baseline, candidate = self.fixture()
        for field in candidate['fields']:
            candidate = discovery.review(candidate, field['id'], 'edit', value=['sim'] if
                                         field['id'] == 'components.selection' else field['value'])
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(result['complete'])
        self.assertEqual(result['profile']['components']['sim'], {'enabled': True})
        self.assertIn({'field_id': 'components.sim', 'reason': 'source_runtime_intent_unresolved',
                       'required': True}, result['review']['gaps'])
        self.roundtrip(result)

    def test_reviewed_custom_package_is_preserved_and_required_support_blocks(self):
        metadata = self.root / 'custom.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_text('Name: custom-tool\nVersion: 1.2.3\n')
        baseline = discovery.observe(package_sources=[{'id': 'tools', 'path': str(metadata / 'METADATA'),
                                                       'format': 'dist-info', 'environment': 'project-uv'}])
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=[])
        candidate = discovery.review(candidate, 'custom:tools:custom-tool', 'accept')
        optional = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(optional['complete'])
        item = optional['profile']['custom_dependencies'][0]
        self.assertEqual(item, {'id': 'custom:tools:custom-tool', 'name': 'custom-tool', 'version': '1.2.3',
                               'environment': 'project-uv', 'location': str(metadata / 'METADATA'),
                               'purpose': None, 'source': None, 'placement': 'unknown',
                               'required': False, 'support': 'unsupported'})
        self.roundtrip(optional)
        required = discovery.review(candidate, 'custom:tools:custom-tool', 'accept', required=True)
        blocked = self.bridge.export_candidate(baseline, required)
        self.assertFalse(blocked['complete'])
        self.assertFalse(blocked['profile']['draft'], 'reviewed support gaps belong to individual consumers')
        self.assertTrue(blocked['review']['intent_complete'])
        self.assertTrue(blocked['profile']['custom_dependencies'][0]['required'])
        self.assertIn({'field_id': item['id'], 'reason': 'unsupported_mapping', 'required': True},
                      blocked['review']['required_unresolved'])
        self.roundtrip(blocked)

    def test_changed_evidence_preserves_accepted_intent_but_blocks_stale_claims(self):
        baseline, candidate = self.fixture()
        for field in candidate['fields']:
            candidate = discovery.review(candidate, field['id'], 'edit', value=[] if
                                         field['id'] == 'components.selection' else field['value'])
        changed = discovery.observe(workspaces=[{'id': 'main', 'name': 'Other Team', 'root': str(self.root)}])
        updated = discovery.propose(changed, previous=candidate)
        result = self.bridge.export_candidate(changed, updated)
        self.assertEqual(result['profile']['workspace']['name'], 'Robotics Team')
        self.assertFalse(result['complete'])
        self.assertTrue(any(g['reason'] == 'evidence_changed_review_required' for g in result['review']['gaps']))
        self.assertEqual(result['review']['fields'], updated['fields'])
        self.roundtrip(result)

    def test_multiple_workspace_scopes_never_silently_overwrite(self):
        baseline = discovery.observe(workspaces=[
            {'id': 'one', 'name': 'First', 'root': str(self.root)},
            {'id': 'two', 'name': 'Second', 'root': str(self.root)}])
        candidate = discovery.propose(baseline)
        for field in candidate['fields']:
            candidate = discovery.review(candidate, field['id'], 'edit', value=[] if
                                         field['id'] == 'components.selection' else field['value'])
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(result['complete'])
        self.assertNotIn('workspace', result['profile'])
        self.assertTrue(any(g['reason'] == 'multiple_workspace_scopes' for g in result['review']['gaps']))
        self.assertEqual(result['review']['fields'], candidate['fields'])
        self.roundtrip(result)

    def test_legacy_workspace_review_does_not_prevent_draft_generation(self):
        baseline, candidate = self.fixture()
        for field in candidate['fields']:
            value = [] if field['id'] == 'components.selection' else field['value']
            if field['id'].endswith('.layout'):
                value = 'legacy'
            candidate = discovery.review(candidate, field['id'], 'edit', value=value)
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(result['complete'])
        self.assertNotIn('layout', result['profile'].get('workspace', {}))
        self.assertTrue(any(g['reason'] == 'legacy_layout_requires_reviewed_migration' for g in result['review']['gaps']))
        self.roundtrip(result)

    def test_reviewed_environment_tools_and_notes_survive_shared_yaml(self):
        import json
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'project-uv', 'manager': 'uv', 'python': '3.12',
            'tools': [{'name': 'custom-tool', 'version': '1.2.3',
                       'source': 'ssh://example.org:2222/team/tool',
                       'purpose': 'Robot workflow (control/vision)'}],
            'notes': ['Preserve project tooling']}))
        baseline = discovery.observe(metadata_sources=[{'id': 'tools', 'path': str(path),
            'format': 'environment-json', 'environment': 'project-uv', 'placement': 'container'}])
        self.assertEqual(baseline['observations'][0]['status'], 'observed')
        candidate = discovery.propose(baseline)
        for field in candidate['fields']:
            candidate = discovery.review(candidate, field['id'], 'edit', value=[] if
                                         field['id'] == 'components.selection' else field['value'])
        result = self.bridge.export_candidate(baseline, candidate)
        item = result['profile']['custom_dependencies'][0]
        self.assertEqual(item['source'], 'ssh://example.org:2222/team/tool')
        self.assertEqual(item['purpose'], 'Robot workflow (control/vision)')
        self.assertEqual(item['placement'], 'container')
        self.assertEqual(item['environment'], 'project-uv')
        env = result['profile']['environments'][0]
        self.assertEqual(env, {'id': 'environment:tools', 'name': 'project-uv', 'manager': 'uv',
                              'python': '3.12', 'placement': 'container', 'location': str(path),
                              'required': False, 'support': 'unsupported'})
        self.assertEqual(result['profile']['notes'], [{'id': 'note:tools:0', 'text': 'Preserve project tooling',
                                                       'required': False, 'support': 'unsupported'}])
        self.assertTrue(result['complete'])
        self.assertEqual(result['review']['fields'], candidate['fields'])
        self.roundtrip(result)

    def test_reviewed_repository_identity_and_submodule_limits_are_preserved(self):
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('a' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://example.org/team/robot.git\n')
        (self.root / '.gitmodules').write_text('[submodule "arena"]\npath = dependencies/arena\nurl = https://example.org/team/arena.git\n')
        baseline = discovery.observe(git_sources=[{'id': 'robot', 'root': str(self.root),
            'git_dir': str(git), 'common_dir': str(git), 'ref_paths': []}])
        self.assertEqual(baseline['observations'][0]['status'], 'observed')
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=[])
        candidate = discovery.review(candidate, 'repository:robot', 'accept')
        result = self.bridge.export_candidate(baseline, candidate)
        repo = result['profile']['repositories'][0]
        self.assertEqual(repo, {'id': 'repository:robot', **baseline['observations'][0]['value'],
                               'required': False, 'support': 'unsupported'})
        self.assertEqual(repo['dirty'], 'unknown')
        self.assertEqual(repo['pin_provenance'], 'selected-head-only')
        self.assertTrue(result['complete'])
        self.roundtrip(result)

    def test_explicit_component_source_association_requires_independent_review(self):
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('a' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/lerobot.git\n')
        baseline = discovery.observe(git_sources=[{'id': 'robot', 'root': str(self.root),
            'git_dir': str(git), 'common_dir': str(git), 'ref_paths': [], 'component': 'lerobot'}])
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=['lerobot'])
        before = self.bridge.export_candidate(baseline, candidate)
        self.assertNotIn('source', before['profile']['components']['lerobot'])
        candidate = discovery.review(candidate, 'component:lerobot.source', 'accept')
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertEqual(result['profile']['components']['lerobot']['source'], {
            'mode': 'git', 'repository': 'https://github.com/example/lerobot.git',
            'ref': 'a' * 40, 'revision': 'a' * 40})
        self.assertNotIn('runtime', result['profile']['components']['lerobot'])
        self.assertFalse(result['complete'])
        self.roundtrip(result)

    def test_reviewed_runtime_binding_completes_selected_source_without_defaults(self):
        import json
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('b' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/lerobot.git\n')
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'lerobot', 'manager': 'conda', 'python': '3.12',
                                    'tools': [], 'notes': []}))
        baseline = discovery.observe(git_sources=[{'id': 'robot', 'root': str(self.root),
            'git_dir': str(git), 'common_dir': str(git), 'ref_paths': [], 'component': 'lerobot'}],
            metadata_sources=[{'id': 'runtime', 'path': str(path), 'format': 'environment-json',
                               'environment': 'lerobot', 'placement': 'host', 'runtime': 'lerobot'}])
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=['lerobot'])
        candidate = discovery.review(candidate, 'component:lerobot.source', 'accept')
        candidate = discovery.review(candidate, 'runtime:lerobot', 'accept')
        unplaced = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(unplaced['complete'], 'runtime acceptance alone does not approve native placement')
        candidate = discovery.review(candidate, 'environment:runtime', 'accept')
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(result['complete'])
        self.assertEqual(result['profile']['runtimes'], {'lerobot': {
            'manager': 'conda', 'environment': 'lerobot', 'python': '3.12'}})
        self.assertEqual(result['profile']['components']['lerobot']['runtime'], 'lerobot')
        self.assertEqual(result['profile']['components']['lerobot']['execution'], 'native')
        self.assertNotIn('serving', result['profile'])
        self.roundtrip(result)
        resolved = wp.resolve_document(result['profile'])
        self.assertFalse(resolved['ready_for_apply'])
        self.assertEqual(resolved['references']['components.lerobot']['content_id'], 'b' * 40)
        # Explicitly review the runtime without a Python pin for the local
        # consumer, which does not implement a selectable interpreter pin.
        local_candidate = discovery.review(candidate, 'runtime:lerobot', 'edit',
            value={'manager': 'conda', 'environment': 'lerobot'})
        local_export = self.bridge.export_candidate(baseline, local_candidate)
        from src.python.profile_adapters import render_profile
        local = render_profile(wp.resolve_document(local_export['profile']), 'local', '/home/tester')
        self.assertTrue(local['render_supported'], local['blockers'])
        self.assertEqual(local['artifact']['repositories']['lerobot']['repo'], 'https://github.com/example/lerobot.git')
        self.assertEqual(local['artifact']['repositories']['lerobot']['tag'], 'b' * 40)
        legacy = self.root / 'legacy.yaml'
        legacy.write_text(yaml.safe_dump(local['artifact']))
        parsed = module('profile_parser').parse_profile(legacy).decode().rstrip('\0').split('\0')
        values = dict(zip(parsed[::2], parsed[1::2]))
        self.assertEqual(values['CFG_REPOSITORIES_LEROBOT_ENABLED'], 'true')
        self.assertEqual(values['CFG_REPOSITORIES_LEROBOT_TAG'], 'b' * 40)
        ansible = render_profile(local_export['profile'], 'ansible', '/home/tester')
        self.assertTrue(ansible['render_supported'], ansible['blockers'])
        self.assertEqual(ansible['coverage']['runtimes.lerobot.manager']['status'], 'mapped')
        self.assertEqual(ansible['coverage']['runtimes.lerobot.environment']['status'], 'mapped')
        self.assertEqual(ansible['artifact']['lerobot_git_checkpoint'], 'b' * 40)
        unsupported = discovery.review(candidate, 'runtime:lerobot', 'edit',
            value={'manager': 'conda', 'environment': 'User-Env', 'python': '3.12'})
        partial = self.bridge.export_candidate(baseline, unsupported)
        self.assertFalse(partial['complete'])
        self.assertNotIn('lerobot', partial['profile'].get('runtimes', {}))
        self.assertTrue(any(g['reason'] == 'unsupported_runtime_intent' for g in partial['review']['gaps']))
        self.roundtrip(partial)
        container_baseline = discovery.observe(git_sources=[{'id': 'robot', 'root': str(self.root),
            'git_dir': str(git), 'common_dir': str(git), 'ref_paths': [], 'component': 'lerobot'}],
            metadata_sources=[{'id': 'runtime', 'path': str(path), 'format': 'environment-json',
                               'environment': 'lerobot', 'placement': 'container', 'runtime': 'lerobot'}])
        container_candidate = discovery.propose(container_baseline)
        container_candidate = discovery.review(container_candidate, 'components.selection', 'edit', value=['lerobot'])
        container_candidate = discovery.review(container_candidate, 'component:lerobot.source', 'accept')
        container_candidate = discovery.review(container_candidate, 'runtime:lerobot', 'accept')
        container = self.bridge.export_candidate(container_baseline, container_candidate)
        self.assertFalse(container['complete'], 'container runtime must not silently map to native intent')
        self.assertTrue(any(g['reason'] == 'unsupported_runtime_placement' for g in container['review']['gaps']))
        self.roundtrip(container)
        (git / 'HEAD').write_text('c' * 40 + '\n')
        changed = discovery.observe(git_sources=[{'id': 'robot', 'root': str(self.root),
            'git_dir': str(git), 'common_dir': str(git), 'ref_paths': [], 'component': 'lerobot'}],
            metadata_sources=[{'id': 'runtime', 'path': str(path), 'format': 'environment-json',
                               'environment': 'lerobot', 'placement': 'host', 'runtime': 'lerobot'}])
        stale = self.bridge.export_candidate(changed, discovery.propose(changed, previous=candidate))
        self.assertFalse(stale['complete'], 'selected source evidence change must block even optional proposal')
        self.assertEqual(stale['profile']['components']['lerobot']['source']['revision'], 'b' * 40)
        self.roundtrip(stale)

    def test_selected_component_missing_dependency_is_incomplete_draft(self):
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('d' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/IsaacLab.git\n')
        import json
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'isaaclab', 'manager': 'conda', 'python': '3.12', 'tools': [], 'notes': []}))
        baseline = discovery.observe(git_sources=[{'id': 'lab', 'root': str(self.root), 'git_dir': str(git),
            'common_dir': str(git), 'ref_paths': [], 'component': 'lab'}], metadata_sources=[{
                'id': 'lab', 'path': str(path), 'format': 'environment-json',
                'environment': 'isaaclab', 'placement': 'host', 'runtime': 'lab'}])
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=['lab'])
        candidate = discovery.review(candidate, 'component:lab.source', 'accept')
        candidate = discovery.review(candidate, 'runtime:lab', 'accept')
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertFalse(result['complete'])
        self.assertIn({'field_id': 'components.lab', 'reason': 'requires_enabled_sim', 'required': True},
                      result['review']['gaps'])
        self.assertFalse(result['profile']['components']['sim']['enabled'])
        self.roundtrip(result)

    def test_optional_inaccessible_coverage_remains_visible_without_blocking_draft(self):
        baseline = discovery.observe(package_sources=[{'id': 'missing', 'path': str(self.root / 'conda-meta'),
            'format': 'conda', 'environment': 'tools'}])
        candidate = discovery.propose(baseline)
        candidate = discovery.review(candidate, 'components.selection', 'edit', value=[])
        result = self.bridge.export_candidate(baseline, candidate)
        self.assertTrue(result['complete'])
        self.assertTrue(result['review']['observation_incomplete'])
        self.assertEqual(result['review']['observation_coverage'], [{
            'id': 'packages:missing', 'status': 'inaccessible', 'reason': 'unreadable_or_unsafe_path',
            'evidence': baseline['observations'][0]['evidence']}])
        self.assertEqual(result['review']['limitations'], baseline['limitations'])
        self.assertEqual(result['review']['conformance'], 'not_evaluated')
        self.roundtrip(result)

    def test_rejected_and_deferred_decisions_remain_distinct_in_coverage(self):
        baseline, candidate = self.fixture()
        candidate = discovery.review(candidate, 'workspace:main.root', 'reject', reason='Not desired', required=False)
        candidate = discovery.review(candidate, 'workspace:main.name', 'defer', reason='Decide later')
        result = self.bridge.export_candidate(baseline, candidate)
        coverage = {item['field_id']: item['status'] for item in result['review']['coverage']}
        self.assertEqual(coverage['workspace:main.root'], 'excluded')
        self.assertEqual(coverage['workspace:main.name'], 'unresolved')
        self.assertFalse(any(g['field_id'] == 'workspace:main.root' for g in result['review']['gaps']))
        self.assertEqual(result['review']['fields'], candidate['fields'])
        self.roundtrip(result)


if __name__ == '__main__':
    unittest.main()
