"""Synthetic fixtures only; run with python3 -I -B this-file -v."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core/profile_discovery.py'


def backend():
    if not MODULE.exists():
        return None
    spec = importlib.util.spec_from_file_location('profile_discovery', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / 'BoredEngineer'
        self.workspace.mkdir()
        self.d = backend()

    def observe(self, **kwargs):
        return self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace),
                                          'name': 'BoredEngineer'}], **kwargs)

    def test_reviewed_pypi_tool_source_is_explicit_and_never_autoapproved(self):
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'isaaclab', 'manager': 'conda', 'python': '3.11',
            'tools': [{'name': 'custom-tool', 'version': '1.2.3', 'source': None, 'purpose': None}], 'notes': []}))
        baseline = self.d.observe(metadata_sources=[{'id': 'lab', 'path': str(path),
            'format': 'environment-json', 'environment': 'isaaclab', 'placement': 'environment'}])
        candidate = self.d.propose(baseline)
        field = next(f for f in candidate['fields'] if f['id'] == 'tool:lab:custom-tool')
        self.assertEqual(field['state'], 'unresolved')
        edited = {**field['value'], 'source': 'pypi', 'purpose': 'Robot tools'}
        reviewed = self.d.review(candidate, field['id'], 'edit', value=edited, required=True)
        self.d.build_review(baseline, reviewed)
        self.assertEqual(next(f for f in reviewed['fields'] if f['id'] == field['id'])['value'], edited)
        for invalid in ('pip install x', 'pypi;run', 'https://user:secret@host/a', 'Pypi'):
            with self.subTest(source=invalid), self.assertRaises(self.d.DiscoveryError):
                self.d.review(candidate, field['id'], 'edit', value={**edited, 'source': invalid})
        data = json.loads(path.read_text())
        data['tools'][0]['source'] = 'pypi'
        path.write_text(json.dumps(data))
        observed = self.d.observe(metadata_sources=[{'id': 'lab', 'path': str(path),
            'format': 'environment-json', 'environment': 'isaaclab', 'placement': 'environment'}])
        proposal = self.d.propose(observed)
        field = next(f for f in proposal['fields'] if f['id'] == 'tool:lab:custom-tool')
        self.assertEqual(field['state'], 'unresolved')
        self.assertIsNone(field['decision'])
        self.assertFalse(field['required'])

    def test_manual_declared_intent_survives_rescan_without_observed_health_claim(self):
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        values = {'component:sim.source': {'mode': 'standalone', 'version': '5.0.0', 'sha256': 'a' * 64},
                  'runtime:kit': {'manager': 'bundled', 'environment': 'kit'},
                  'component:sim.execution': 'native'}
        for field_id, value in values.items():
            candidate = self.d.review(candidate, field_id, 'declare', value=value)
        candidate = self.d.review(candidate, 'component:sim.source', 'edit',
            value={**values['component:sim.source'], 'sha256': 'b' * 64})
        changed = self.d.observe()
        rescanned = self.d.propose(changed, previous=candidate)
        self.d.build_review(changed, rescanned)
        fields = {f['id']: f for f in rescanned['fields']}
        for field_id in values:
            field = fields[field_id]
            self.assertEqual(field['rationale'], 'user_declared_intent')
            self.assertFalse(field['not_selected'])
            self.assertFalse(field['evidence_changed'])
            self.assertEqual(field['evidence'], [])
            self.assertIsNone(field['suggested_value'])
        self.assertEqual(fields['component:sim.source']['value']['sha256'], 'b' * 64)
        for decision, state in [('defer', 'unresolved'), ('reject', 'rejected'), ('accept', 'accepted')]:
            rescanned = self.d.review(rescanned, 'runtime:kit', decision)
            self.d.build_review(changed, rescanned)
            self.assertEqual(next(f for f in rescanned['fields'] if f['id'] == 'runtime:kit')['state'], state)

    def test_later_observation_does_not_relabel_independent_manual_runtime(self):
        baseline = self.d.observe()
        candidate = self.d.review(self.d.propose(baseline), 'runtime:lab', 'declare',
            value={'manager': 'conda', 'environment': 'chosen', 'python': '3.11', 'torch': '2.7.0',
                   'torchvision': '0.22.0', 'cuda_runtime': '12.8', 'architecture': 'sm_89'})
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'observed', 'manager': 'conda', 'python': '3.12', 'tools': [], 'notes': []}))
        baseline = self.d.observe(metadata_sources=[{'id': 'lab', 'path': str(path),
            'format': 'environment-json', 'environment': 'observed', 'placement': 'container', 'runtime': 'lab'}])
        current = self.d.propose(baseline, previous=candidate)
        self.d.build_review(baseline, current)
        field = next(f for f in current['fields'] if f['id'] == 'runtime:lab')
        self.assertEqual(field, candidate['fields'][-1])
        self.assertEqual(baseline['observations'][0]['value']['name'], 'observed')
        self.assertEqual(field['value']['environment'], 'chosen')

    def test_review_edits_can_fill_all_shared_source_runtime_pins(self):
        path = self.root / 'environment.json'
        path.write_text(json.dumps({'name': 'isaaclab', 'manager': 'conda', 'python': '3.11', 'tools': [], 'notes': []}))
        git = self.root / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('a' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/IsaacLab.git\n')
        baseline = self.d.observe(git_sources=[{'id': 'lab', 'root': str(self.root), 'git_dir': str(git),
            'common_dir': str(git), 'ref_paths': [], 'component': 'lab'}], metadata_sources=[{'id': 'lab',
            'path': str(path), 'format': 'environment-json', 'environment': 'isaaclab', 'placement': 'host', 'runtime': 'lab'}])
        candidate = self.d.propose(baseline)
        values = {'runtime:lab': {'manager': 'conda', 'environment': 'isaaclab', 'python': '3.11',
                  'torch': '2.7.0', 'torchvision': '0.22.0', 'cuda_runtime': '12.8', 'architecture': 'sm_89'},
                  'component:lab.source': {'mode': 'git', 'repository': 'https://github.com/example/IsaacLab.git',
                                           'ref': 'reviewed-branch', 'revision': 'b' * 40}}
        for field_id, value in values.items():
            candidate = self.d.review(candidate, field_id, 'edit', value=value)
        self.d.build_review(baseline, candidate)
        current = self.d.propose(baseline, previous=candidate)
        self.d.build_review(baseline, current)
        for field_id, value in values.items():
            self.assertEqual(next(f for f in current['fields'] if f['id'] == field_id)['value'], value)

    def test_manual_declarations_are_bounded_typed_and_cannot_launder_evidence(self):
        import copy
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        source = {'mode': 'git', 'repository': 'https://github.com/example/IsaacSim.git',
                  'ref': 'reviewed', 'revision': 'a' * 40}
        invalid = [('component:sim.source', None), ('component:sim.source', {}),
                   ('component:sim.source', {**source, 'hook': 'DO_NOT_ECHO'}),
                   ('component:sim.source', {**source, 'ref': '../DO_NOT_ECHO'}),
                   ('component:sim.source', {'mode': 'standalone', 'version': '6.0.1', 'sha256': False}),
                   ('component:sim.source', {'mode': 'standalone', 'version': '6.0.1'}),
                   ('component:lab.source', {'mode': 'standalone', 'version': '6.0.1', 'sha256': None}),
                   ('runtime:kit', {'manager': 'conda', 'environment': 'kit'}),
                   ('runtime:lab', {'manager': 'conda', 'environment': 'base'}),
                   ('runtime:lab', {'manager': 'conda', 'environment': 'User-Env'}),
                   ('runtime:lab', {'manager': 'conda', 'environment': 'lab', 'python': 3.11}),
                   ('runtime:lab', {'manager': 'conda', 'environment': 'lab', 'command': 'DO_NOT_ECHO'}),
                   ('runtime:kit', {}), ('runtime:unknown', {'manager': 'bundled', 'environment': 'kit'}),
                   ('component:sim.execution', 'container'), ('component:sim.execution', True),
                   ('component:sim.command', 'DO_NOT_ECHO'), ('apply_supported', True),
                   ('workspace:other.root', '/tmp/elsewhere'), ('tool:new:tool', {}),
                   ('components.selection', ['sim'])]
        original = copy.deepcopy(candidate)
        for field_id, value in invalid:
            with self.subTest(field=field_id, value=value), self.assertRaises(self.d.DiscoveryError) as error:
                self.d.review(candidate, field_id, 'declare', value=value)
            self.assertNotIn('DO_NOT_ECHO', str(error.exception))
            self.assertEqual(candidate, original)
        declared = self.d.review(candidate, 'component:sim.source', 'declare', value=source)
        self.d.build_review(baseline, declared)
        with self.assertRaises(self.d.DiscoveryError):
            self.d.review(declared, 'component:sim.source', 'declare', value=source)
        for key, value in [('evidence', ['workspace:main']), ('support', 'supported'),
                           ('not_selected', True), ('suggested_value', source), ('observed_health', 'working')]:
            forged = copy.deepcopy(declared)
            forged['fields'][-1][key] = value
            forged['revision'] = self.d._revision(forged)
            with self.subTest(key=key), self.assertRaises(self.d.DiscoveryError):
                self.d.build_review(baseline, forged)

    def test_selected_workspace_metadata_is_nonexecutable(self):
        self.assertIsNotNone(self.d, 'discovery backend is missing')
        (self.workspace / '.git').mkdir()
        (self.workspace / '.git/config').write_text('FAKE_SECRET_REMOTE=https://token@private.invalid')
        (self.workspace / 'dirty.py').write_text('never read this private diff')
        before = {str(p): p.read_bytes() for p in self.workspace.rglob('*') if p.is_file()}
        baseline = self.observe()
        self.assertEqual(baseline['kind'], 'workstation-baseline')
        self.assertFalse(baseline['apply_supported'])
        item = baseline['observations'][0]
        self.assertEqual(item['id'], 'workspace:main')
        self.assertEqual(item['status'], 'observed')
        self.assertEqual(item['value']['git_marker'], 'directory')
        self.assertEqual(item['value']['name'], 'BoredEngineer')
        self.assertEqual(item['evidence']['method'], 'selected-directory-entry-metadata')
        self.assertIn('collected_at', baseline)
        self.assertNotIn('FAKE_SECRET', json.dumps(baseline))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.workspace.rglob('*') if p.is_file()})

    def test_workspace_names_preserve_spaces_case_through_review_and_rescan(self):
        def roundtrip(document):
            return json.loads(json.dumps(document, ensure_ascii=True))

        for name, edited_name in (('Robotics Team', 'Robot Research'),
                                  ('BoredEngineer', 'BoredEngineer Lab')):
            with self.subTest(name=name):
                selection = {'id': 'main', 'root': str(self.workspace), 'name': name}
                baseline = roundtrip(self.d.observe(workspaces=[selection]))
                self.assertEqual(baseline['observations'][0]['value']['name'], name)
                candidate = roundtrip(self.d.propose(baseline))
                field = next(p for p in candidate['fields'] if p['id'] == 'workspace:main.name')
                self.assertEqual(field['value'], name)
                self.assertEqual(field['suggested_value'], name)
                candidate = roundtrip(self.d.review(candidate, 'workspace:main.name', 'accept'))
                candidate = roundtrip(self.d.review(candidate, 'workspace:main.name', 'edit', value=edited_name))
                changed = roundtrip(self.d.observe(workspaces=[{**selection, 'name': name + ' II'}]))
                candidate = roundtrip(self.d.propose(changed, previous=candidate))
                field = next(p for p in candidate['fields'] if p['id'] == 'workspace:main.name')
                self.assertEqual(field['value'], edited_name)
                self.assertEqual(field['suggested_value'], name + ' II')
                self.assertEqual(field['decision'], 'edit')
                self.assertTrue(field['evidence_changed'])
                self.assertEqual(candidate['fields'][0]['value'], str(self.workspace))
                report = {'baseline': changed, 'candidate': candidate,
                          'review': self.d.build_review(changed, candidate)}
                destination = self.root / (name + '.json')
                self.d.export_report(roundtrip(report), str(destination))
                self.assertEqual(json.loads(destination.read_text()), report)

    def test_invalid_workspace_names_are_rejected_at_every_companion_boundary(self):
        from unittest.mock import patch

        baseline = self.observe()
        candidate = self.d.review(self.d.propose(baseline), 'workspace:main.name', 'accept')
        invalid = [None, False, 0, [], {}, '', ' ', '.', '..', ' leading', 'trailing ',
                   'a/b', 'a\\b', 'password=FAKE_SECRET', 'Équipe ロボット',
                   '.hidden', 'team:one', 'team@host']
        invalid += ['a' + chr(code) + 'b' for code in (*range(32), *range(127, 160))]
        invalid += ['a' + char + 'b' for char in ('\u200b', '\u202e', '\ufeff', '\ud800', '\ue000')]
        for name in invalid:
            with self.subTest(name=repr(name)):
                with patch.object(self.d, '_open_directory', side_effect=AssertionError('unexpected read')):
                    with self.assertRaises(self.d.DiscoveryError):
                        self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace), 'name': name}])
                with self.assertRaises(self.d.DiscoveryError):
                    self.d.review(candidate, 'workspace:main.name', 'edit', value=name)
                bad_baseline = json.loads(json.dumps(baseline))
                bad_baseline['observations'][0]['value']['name'] = name
                bad_baseline['revision'] = self.d._revision(bad_baseline)
                for call in (lambda: self.d.propose(bad_baseline),
                             lambda: self.d.build_review(bad_baseline, candidate)):
                    with self.assertRaises(self.d.DiscoveryError):
                        call()
                for key in ('value', 'suggested_value'):
                    if name is None and key == 'suggested_value':
                        continue  # None is the companion's explicit unknown suggestion.
                    bad_candidate = json.loads(json.dumps(candidate))
                    field = next(p for p in bad_candidate['fields'] if p['id'] == 'workspace:main.name')
                    field[key] = name
                    bad_candidate['revision'] = self.d._revision(bad_candidate)
                    for call in (lambda: self.d.propose(baseline, previous=bad_candidate),
                                 lambda: self.d.review(bad_candidate, 'workspace:main.name', 'accept'),
                                 lambda: self.d.build_review(baseline, bad_candidate)):
                        with self.assertRaises(self.d.DiscoveryError):
                            call()

    def test_workspace_display_names_do_not_relax_ids_or_package_names(self):
        info = self.root / 'tool.dist-info'
        info.mkdir()
        source = {'id': 'tools', 'path': str(info / 'METADATA'), 'format': 'dist-info', 'environment': 'uv'}
        for name in ('Robotics Team', 'Équipe ロボット'):
            with self.subTest(name=name):
                with self.assertRaises(self.d.DiscoveryError):
                    self.d.observe(workspaces=[{'id': name, 'root': str(self.workspace), 'name': 'Local'}])
                with self.assertRaises(self.d.DiscoveryError):
                    self.observe(package_sources=[{**source, 'id': name}])
                (info / 'METADATA').write_text(f'Name: {name}\nVersion: 1\n')
                item = self.observe(package_sources=[source])['observations'][1]
                self.assertEqual(item['status'], 'unknown')
                self.assertEqual(item['value']['packages'], [])

    def test_workspace_symlink_ancestors_missing_and_git_indirection_are_not_followed(self):
        real = self.root / 'real'
        real.mkdir()
        (real / 'checkout').mkdir()
        (self.root / 'link').symlink_to(real, target_is_directory=True)
        for root in (self.root / 'link/checkout', self.root / 'missing'):
            result = self.d.observe(workspaces=[{'id': 'x', 'root': str(root), 'name': 'Local'}])
            self.assertEqual(result['observations'][0]['status'], 'inaccessible')
        (self.workspace / '.git').write_text('gitdir: /private/FAKE_SECRET\n')
        result = self.observe()
        self.assertEqual(result['observations'][0]['value']['git_marker'], 'file')
        self.assertNotIn('FAKE_SECRET', json.dumps(result))

    def test_unsafe_selection_is_rejected_without_leaking_input(self):
        for value in ('../FAKE_SECRET', '/', '/tmp/../FAKE_SECRET', '/tmp/\x1b[31mFAKE_SECRET',
                      '/tmp/token=FAKE_SECRET', '/tmp/' + 'x' * 4096):
            with self.subTest(value=repr(value[:30])):
                with self.assertRaises(ValueError) as caught:
                    self.d.observe(workspaces=[{'id': 'a', 'root': value, 'name': 'Local'}])
                self.assertNotIn('FAKE_SECRET', str(caught.exception))
        with self.assertRaises(ValueError):
            self.observe(target='https://secret@host')
        with self.assertRaises(ValueError):
            self.d.observe(workspaces=[{'id': 'a', 'root': str(self.workspace), 'name': '../escape'}])

    def test_explicit_dist_info_extracts_only_name_version_without_imports(self):
        info = self.root / 'custom-1.dist-info'
        info.mkdir()
        metadata = info / 'METADATA'
        metadata.write_text('Metadata-Version: 2.1\nName: custom-tool\nVersion: 1.2.3\n'
                            'Home-page: https://FAKE_SECRET@private.invalid\n\nPRIVATE_DESCRIPTION')
        (info / 'direct_url.json').write_text('{"url":"FAKE_SECRET"}')
        source = {'id': 'tooling', 'path': str(metadata), 'format': 'dist-info', 'environment': 'project-uv'}
        result = self.observe(package_sources=[source])
        self.assertEqual(len(result['observations']), 2)
        item = result['observations'][1]
        self.assertEqual(item['status'], 'observed')
        self.assertEqual(item['value']['packages'], [{'name': 'custom-tool', 'version': '1.2.3'}])
        self.assertEqual(item['value']['environment'], 'project-uv')
        self.assertNotIn('FAKE_SECRET', json.dumps(result))
        self.assertNotIn('PRIVATE_DESCRIPTION', json.dumps(result))

    def test_metadata_refuses_unsafe_incomplete_or_oversize_records(self):
        info = self.root / 'custom.dist-info'
        info.mkdir()
        path = info / 'METADATA'
        source = {'id': 'custom', 'path': str(path), 'format': 'dist-info', 'environment': 'uv'}
        cases = [b'Name: ok\nVersion: 1\nName: duplicate\n', b'Name: ok\n',
                 b'Name: ok\nVersion: \x1b[31mSECRET\n', b'Name: password=FAKE_SECRET\nVersion: 1\n',
                 b'Name: ok\nVersion: 1\n' + b'x' * 70000, b'\xff']
        for raw in cases:
            path.write_bytes(raw)
            result = self.observe(package_sources=[source])['observations'][1]
            self.assertNotEqual(result['status'], 'observed')
            self.assertEqual(result['value']['packages'], [])
            self.assertNotIn('FAKE_SECRET', json.dumps(result))
        path.unlink()
        private = self.root / 'private'
        private.write_text('Name: forbidden\nVersion: 1\n')
        for link_kind in ('symlink', 'hardlink', 'fifo'):
            if link_kind == 'symlink':
                path.symlink_to(private)
            elif link_kind == 'hardlink':
                os.link(private, path)
            else:
                os.mkfifo(path)
            result = self.observe(package_sources=[source])['observations'][1]
            self.assertEqual(result['status'], 'inaccessible')
            self.assertEqual(result['value']['packages'], [])
            path.unlink()
        source['path'] = str(private)
        with self.assertRaises(ValueError):
            self.observe(package_sources=[source])

    def test_conda_directory_is_bounded_and_never_reads_extra_fields(self):
        meta = self.root / 'conda-meta'
        meta.mkdir()
        for index in range(3):
            (meta / f'tool-{index}.json').write_text(json.dumps({'name': f'tool-{index}', 'version': '1.0',
                                                              'channel': 'https://FAKE_SECRET@private.invalid'}))
        (meta / 'history').write_text('PRIVATE_COMMANDS')
        source = {'id': 'conda', 'path': str(meta), 'format': 'conda', 'environment': 'lab'}
        result = self.observe(package_sources=[source], limits={'max_entries': 1})
        item = result['observations'][1]
        self.assertEqual(item['status'], 'unknown')
        self.assertEqual(item['reason'], 'entry_limit')
        self.assertLessEqual(len(item['value']['packages']), 1)
        self.assertTrue(result['incomplete'])
        complete = self.observe(package_sources=[source])
        self.assertEqual(len(complete['observations'][1]['value']['packages']), 3)
        self.assertNotIn('FAKE_SECRET', json.dumps(complete))
        self.assertNotIn('PRIVATE_COMMANDS', json.dumps(complete))
        self.assertEqual(complete['observations'][1]['status'], 'observed')

    def test_candidate_uses_selected_root_name_and_keeps_unknowns_explicit(self):
        self.assertTrue(hasattr(self.d, 'propose'), 'proposal API missing')
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        self.assertEqual(candidate['kind'], 'workstation-candidate')
        self.assertEqual(candidate['baseline_revision'], baseline['revision'])
        fields = {p['id']: p for p in candidate['fields']}
        self.assertEqual(fields['workspace:main.root']['value'], str(self.workspace))
        self.assertEqual(fields['workspace:main.name']['value'], 'BoredEngineer')
        self.assertEqual(fields['workspace:main.root']['state'], 'proposed')
        self.assertEqual(fields['workspace:main.root']['evidence'], ['workspace:main'])
        self.assertEqual(fields['components.selection']['state'], 'unresolved')
        self.assertTrue(fields['components.selection']['required'])
        self.assertIsNone(fields['components.selection']['value'])
        self.assertFalse(candidate['apply_supported'])

    def test_review_preserves_decisions_and_exposes_rescan_discrepancies(self):
        self.assertTrue(hasattr(self.d, 'review'), 'review API missing')
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        original = json.dumps(candidate, sort_keys=True)
        candidate = self.d.review(candidate, 'workspace:main.name', 'edit', value='MyWorkspace', reason='preserve local name')
        candidate = self.d.review(candidate, 'workspace:main.root', 'accept')
        candidate = self.d.review(candidate, 'components.selection', 'defer')
        fields = {p['id']: p for p in candidate['fields']}
        self.assertEqual(fields['workspace:main.name']['state'], 'accepted')
        self.assertEqual(fields['workspace:main.name']['value'], 'MyWorkspace')
        self.assertEqual(fields['components.selection']['state'], 'unresolved')
        self.assertEqual(fields['components.selection']['decision'], 'defer')
        self.assertEqual(original, json.dumps(self.d.propose(baseline), sort_keys=True))
        changed = self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace), 'name': 'Changed'}])
        rescanned = self.d.propose(changed, previous=json.loads(json.dumps(candidate)))
        fields = {p['id']: p for p in rescanned['fields']}
        self.assertEqual(fields['workspace:main.name']['value'], 'MyWorkspace')
        self.assertEqual(fields['workspace:main.name']['suggested_value'], 'Changed')
        self.assertTrue(fields['workspace:main.name']['evidence_changed'])
        self.assertEqual(fields['workspace:main.name']['reason'], 'preserve local name')
        self.assertEqual(fields['workspace:main.root']['decision'], 'accept')
        rejected = self.d.review(rescanned, 'workspace:main.name', 'reject')
        again = self.d.propose(changed, previous=rejected)
        self.assertEqual(again['fields'][1]['state'], 'rejected')
        absent = self.d.propose(self.d.observe(), previous=again)
        self.assertTrue(next(p for p in absent['fields'] if p['id'] == 'workspace:main.name')['not_selected'])

    def test_ancestor_descriptors_do_not_require_directory_listing(self):
        from unittest.mock import patch
        opened = []
        original = os.open
        def recording(path, flags, *args, **kwargs):
            opened.append((path, flags))
            return original(path, flags, *args, **kwargs)
        with patch.object(self.d.os, 'open', side_effect=recording):
            self.observe()
        self.assertTrue(opened[0][1] & os.O_PATH)
        self.assertTrue(all(flags & os.O_PATH for _, flags in opened[:-1]))

    def test_budget_validation_and_cancelled_observations_are_explicit(self):
        for limits in ({'max_sources': 0}, {'max_sources': 129}, {'max_bytes': True},
                       {'max_seconds': float('nan')}, {'unknown': 2}, {'max_entries': 1025}):
            with self.assertRaises(ValueError):
                self.observe(limits=limits)
        result = self.observe(cancelled=lambda: True)
        self.assertEqual(result['observations'][0]['status'], 'unknown')
        self.assertEqual(result['observations'][0]['reason'], 'cancelled')
        self.assertTrue(result['incomplete'])
        with self.assertRaises(ValueError):
            self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace), 'name': 'Local'}] * 2,
                           limits={'max_sources': 1})
        with self.assertRaises(ValueError):
            self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace), 'name': 'Local'}] * 2)
        with self.assertRaises(ValueError):
            self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace)}])
        info = self.root / 'x.dist-info'
        info.mkdir()
        (info / 'METADATA').write_text('Name: x\nVersion: 1\n')
        result = self.observe(package_sources=[{'id': 'x', 'path': str(info / 'METADATA'),
                                               'format': 'dist-info', 'environment': 'uv'}], limits={'max_bytes': 1})
        self.assertEqual(result['observations'][1]['status'], 'unknown')
        self.assertTrue(result['incomplete'])

    def test_custom_backlog_required_unsupported_stays_blocked_after_acceptance(self):
        self.assertTrue(hasattr(self.d, 'build_review'), 'comparison report API missing')
        info = self.root / 'tool.dist-info'
        info.mkdir()
        (info / 'METADATA').write_text('Name: custom-tool\nVersion: 1.0\n')
        baseline = self.observe(package_sources=[{'id': 'tools', 'path': str(info / 'METADATA'),
                                                'format': 'dist-info', 'environment': 'project-uv'}])
        candidate = self.d.propose(baseline)
        custom = next(p for p in candidate['fields'] if p['id'].startswith('custom:'))
        self.assertEqual(custom['state'], 'unresolved')
        self.assertEqual(custom['value']['name'], 'custom-tool')
        self.assertEqual(custom['support'], 'unsupported')
        candidate = self.d.review(candidate, custom['id'], 'accept', required=True)
        report = self.d.build_review(baseline, candidate)
        self.assertEqual(report['kind'], 'workstation-review')
        self.assertFalse(report['apply_supported'])
        self.assertFalse(report['executable_export_supported'])
        self.assertIn(custom['id'], [item['field_id'] for item in report['required_unresolved']])
        self.assertEqual(report['customization_backlog'][0]['decision'], 'accept')
        self.assertEqual(report['customization_backlog'][0]['purpose'], 'unknown')
        self.assertEqual(report['conformance'], 'not_evaluated')
        empty = self.d.build_review(self.d.observe(), self.d.propose(self.d.observe()))
        self.assertEqual(empty['customization_backlog'], [])

    def test_serialized_companions_are_strictly_validated_before_use(self):
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        mutations = [lambda d: d.update(kind='legacy'), lambda d: d.update(schema_version='v999'),
                     lambda d: d.update(extra='FAKE_SECRET'),
                     lambda d: d['observations'][0]['value'].update(name='\x1bFAKE_SECRET'),
                     lambda d: d['observations'][0]['evidence'].update(method='FAKE_SECRET'),
                     lambda d: d['observations'][0].update(extra='FAKE_SECRET'),
                     lambda d: d.update(observations=d['observations'] * 129)]
        for mutate in mutations:
            bad = json.loads(json.dumps(baseline))
            mutate(bad)
            with self.assertRaises(ValueError) as caught:
                self.d.propose(bad)
            self.assertNotIn('FAKE_SECRET', str(caught.exception))
        mutations = [lambda d: d.update(extra='FAKE_SECRET'),
                     lambda d: d['fields'][0].update(value='/tmp/../FAKE_SECRET'),
                     lambda d: d['fields'][0].update(rationale='FAKE_SECRET'),
                     lambda d: d['fields'][0].update(alternatives=['FAKE_SECRET']),
                     lambda d: d['fields'][0].update(support='supported'),
                     lambda d: d['fields'][0].update(id='install_command'),
                     lambda d: d.update(revision='sha256:' + '0' * 64),
                     lambda d: d['fields'][0].update(reason='password FAKE_SECRET')]
        for mutate in mutations:
            bad = json.loads(json.dumps(candidate))
            mutate(bad)
            for call in (lambda: self.d.review(bad, 'workspace:main.name', 'accept'),
                         lambda: self.d.propose(baseline, previous=bad),
                         lambda: self.d.build_review(baseline, bad)):
                with self.assertRaises(ValueError) as caught:
                    call()
                self.assertNotIn('FAKE_SECRET', str(caught.exception))
        with self.assertRaises(ValueError):
            self.d.review(candidate, 'components.selection', 'edit', value='execute-shell')
        with self.assertRaises(ValueError):
            self.d.review(candidate, 'workspace:main.name', 'accept', reason='password FAKE_SECRET')
        changed = self.d.observe(workspaces=[])
        with self.assertRaises(ValueError):
            self.d.build_review(changed, candidate)

    def test_report_export_is_exclusive_private_and_outside_inspected_roots(self):
        self.assertTrue(hasattr(self.d, 'export_report'), 'exclusive export API missing')
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        document = {'baseline': baseline, 'candidate': candidate, 'review': self.d.build_review(baseline, candidate)}
        output = self.root / 'reports'
        output.mkdir()
        destination = output / 'review.json'
        self.d.export_report(document, str(destination), inspected_roots=[str(self.workspace)])
        self.assertEqual(json.loads(destination.read_text()), document)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.d.export_report(document, str(destination))
        self.assertEqual(json.loads(destination.read_text()), document)
        with self.assertRaises(ValueError):
            self.d.export_report(document, str(self.workspace / 'forbidden.json'))
        linked = self.root / 'linked-output'
        linked.symlink_to(output, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.d.export_report(document, str(linked / 'escape.json'))
        destination.unlink()
        destination.symlink_to(self.workspace / 'private')
        with self.assertRaises(ValueError):
            self.d.export_report(document, str(destination))
        forged = json.loads(json.dumps(document))
        forged['review']['customization_backlog'].append({'secret': 'FAKE_SECRET'})
        with self.assertRaises(ValueError):
            self.d.export_report(forged, str(output / 'forged.json'))
        self.assertFalse((output / 'forged.json').exists())

    def test_conda_positive_reader_works_inside_real_readonly_confinement(self):
        import subprocess
        import sys
        self.root.chmod(0o755)
        metadata = self.root / 'conda-meta'
        metadata.mkdir()
        (metadata / 'motion.json').write_text('{"name":"motion","version":"1"}')
        script = f'''import importlib.util,json,os
from pathlib import Path
core=Path({str(MODULE.parent)!r})
def load(name):
    spec=importlib.util.spec_from_file_location(name,core/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
d=load('profile_discovery');sandbox=load('preview_sandbox')
if os.geteuid()==0:
    os.setgroups([]);os.setgid(65534);os.setuid(65534)
sandbox.confine_readonly([{str(metadata)!r}])
result=d.observe(package_sources=[{{'id':'positive','path':{str(metadata)!r},'format':'conda','environment':'robot'}}])
print(json.dumps(result))
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script], capture_output=True,
                                text=True, timeout=20, env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)['observations'][0]
        self.assertEqual(item['status'], 'observed', item)
        self.assertEqual(item['value']['packages'], [{'name': 'motion', 'version': '1'}])

    def test_byte_budget_is_shared_across_package_and_git_readers(self):
        info = self.root / 'tool.dist-info'
        info.mkdir()
        raw = 'Name: tool\nVersion: 1\n'
        (info / 'METADATA').write_text(raw)
        git = self.workspace / '.git'
        git.mkdir()
        (git / 'HEAD').write_text('a' * 40 + '\n')
        package = {'id': 'tools', 'path': str(info / 'METADATA'), 'format': 'dist-info', 'environment': 'uv'}
        repository = {'id': 'git', 'root': str(self.workspace), 'git_dir': str(git),
                      'common_dir': str(git), 'ref_paths': []}
        baseline = self.observe(package_sources=[package], git_sources=[repository],
                                limits={'max_bytes': len(raw.encode()) + 40})
        self.assertEqual(baseline['observations'][1]['status'], 'observed')
        self.assertEqual(baseline['observations'][2]['status'], 'unknown')
        self.assertIsNone(baseline['observations'][2]['value']['head']['commit'])
        self.assertEqual(baseline['observations'][2]['reason'], 'byte_limit')
        # Invalid input still consumes bytes; repeated malformed sources cannot
        # multiply the physical read budget.
        (info / 'METADATA').write_bytes(b'\xff' * len(raw))
        baseline = self.observe(package_sources=[package], git_sources=[repository],
                                limits={'max_bytes': len(raw.encode()) + 40})
        self.assertEqual(baseline['observations'][2]['reason'], 'byte_limit')
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_entry_budget_is_shared_across_all_selected_package_sources(self):
        sources = []
        for index in range(2):
            info = self.root / f'pkg-{index}.dist-info'
            info.mkdir()
            (info / 'METADATA').write_text(f'Name: pkg-{index}\nVersion: 1\n')
            sources.append({'id': f'p{index}', 'path': str(info / 'METADATA'), 'format': 'dist-info', 'environment': 'uv'})
        result = self.observe(package_sources=sources, limits={'max_entries': 1})
        self.assertEqual(result['observations'][1]['status'], 'observed')
        self.assertEqual(result['observations'][2]['status'], 'unknown')
        self.assertEqual(result['observations'][2]['reason'], 'entry_limit')
        self.assertEqual(result['observations'][2]['value']['packages'], [])

    def test_conflicting_conda_versions_do_not_create_duplicate_candidate_fields(self):
        meta = self.root / 'conda-meta'
        meta.mkdir()
        (meta / 'tool1.json').write_text('{"name":"tool","version":"1"}')
        (meta / 'tool2.json').write_text('{"name":"tool","version":"2"}')
        sources = [{'id': 'tools', 'path': str(meta), 'format': 'conda', 'environment': 'lab'}]
        baseline = self.observe(package_sources=sources)
        self.assertEqual(baseline['observations'][1]['status'], 'conflicting')
        candidate = self.d.propose(baseline)
        self.assertEqual(len({p['id'] for p in candidate['fields']}), len(candidate['fields']))
        self.assertFalse(self.d.build_review(baseline, candidate)['executable_export_supported'])
        (meta / 'tool2.json').write_text('{"name":"tool","version":"1"}')
        baseline = self.observe(package_sources=sources)
        self.assertEqual(baseline['observations'][1]['status'], 'observed')
        self.assertEqual(len(baseline['observations'][1]['value']['packages']), 1)
        (meta / 'tool2.json').write_text('{"name":"tool","name":"other","version":"1"}')
        baseline = self.observe(package_sources=sources)
        self.assertNotEqual(baseline['observations'][1]['status'], 'observed')

    def test_named_workspace_layout_is_proposed_without_path_concatenation(self):
        candidate = self.d.propose(self.observe())
        fields = {p['id']: p for p in candidate['fields']}
        self.assertIn('workspace:main.layout', fields)
        self.assertEqual(fields['workspace:main.layout']['value'], 'named')
        self.assertEqual(fields['workspace:main.root']['value'], str(self.workspace))
        edited = self.d.review(candidate, 'workspace:main.layout', 'edit', value='legacy')
        self.assertEqual(next(p for p in edited['fields'] if p['id'].endswith('.layout'))['value'], 'legacy')
        with self.assertRaises(ValueError):
            self.d.review(candidate, 'workspace:main.layout', 'edit', value='shell-hook')

    def test_fresh_review_acknowledges_selected_evidence_without_losing_intent(self):
        desired_path = MODULE.parent / 'desired_profile.py'
        spec = importlib.util.spec_from_file_location('discovery_rereview_export', desired_path)
        desired = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(desired)
        baseline = self.observe()
        candidate = self.d.propose(baseline)
        for field in candidate['fields']:
            if field['id'].startswith('workspace:'):
                candidate = self.d.review(candidate, field['id'], 'accept')
        candidate = self.d.review(candidate, 'components.selection', 'edit', value=[])
        self.assertTrue(desired.export_candidate(baseline, candidate)['complete'])
        changed = self.d.observe(workspaces=[{'id': 'main', 'root': str(self.workspace), 'name': 'Changed'}])
        candidate = self.d.propose(changed, previous=candidate)
        self.assertFalse(desired.export_candidate(changed, candidate)['complete'])
        prior_name = next(f for f in candidate['fields'] if f['id'] == 'workspace:main.name')['value']
        for field in candidate['fields']:
            if field['id'].startswith('workspace:'):
                action = 'edit' if field['id'].endswith('.layout') else 'accept'
                kwargs = {'value': field['value']} if action == 'edit' else {}
                candidate = self.d.review(candidate, field['id'], action, **kwargs)
        selected = [f for f in candidate['fields'] if f['id'].startswith('workspace:')]
        self.assertTrue(all(not f['evidence_changed'] for f in selected))
        self.assertEqual(next(f for f in selected if f['id'].endswith('.name'))['value'], prior_name)
        self.assertTrue(desired.export_candidate(changed, candidate)['complete'])
        again = self.d.propose(changed, previous=candidate)
        self.assertTrue(all(not f['evidence_changed'] for f in again['fields']))
        empty = self.d.observe()
        removed = self.d.propose(empty, previous=again)
        removed = self.d.review(removed, 'workspace:main.name', 'accept')
        field = next(f for f in removed['fields'] if f['id'] == 'workspace:main.name')
        self.assertTrue(field['not_selected'])
        self.assertTrue(field['evidence_changed'])
        self.assertFalse(desired.export_candidate(empty, removed)['complete'])

    def test_rescan_marks_changed_evidence_even_when_selected_value_is_unchanged(self):
        baseline = self.observe()
        candidate = self.d.review(self.d.propose(baseline), 'workspace:main.root', 'accept')
        (self.workspace / '.git').mkdir()
        rescanned = self.d.propose(self.observe(), previous=candidate)
        field = next(p for p in rescanned['fields'] if p['id'] == 'workspace:main.root')
        self.assertTrue(field['evidence_changed'])
        self.assertEqual(field['value'], str(self.workspace))
        self.assertEqual(field['decision'], 'accept')
        self.assertEqual(field['decision_revision'], candidate['fields'][0]['decision_revision'])

    def test_partial_package_coverage_cannot_collide_with_tool_named_coverage(self):
        meta = self.root / 'conda-meta'
        meta.mkdir()
        (meta / 'first.json').write_text('{"name":"coverage","version":"1"}')
        (meta / 'second.json').write_text('{"name":"coverage","version":"1"}')
        sources = [{'id': 'tools', 'path': str(meta), 'format': 'conda', 'environment': 'lab'}]
        baseline = self.observe(package_sources=sources, limits={'max_entries': 1})
        candidate = self.d.propose(baseline)
        self.assertEqual(len({p['id'] for p in candidate['fields']}), len(candidate['fields']))
        self.assertFalse(self.d.build_review(baseline, candidate)['executable_export_supported'])

    def test_recomputed_forged_ids_and_opaque_versions_are_not_echoed(self):
        import hashlib
        candidate = self.d.propose(self.observe())
        candidate['fields'][0]['id'] = 'workspace:password-FAKE_SECRET.root'
        candidate['fields'][0]['evidence'] = []
        payload = {k: v for k, v in candidate.items() if k not in ('revision', 'collected_at')}
        candidate['revision'] = 'sha256:' + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        with self.assertRaises(ValueError) as caught:
            self.d.review(candidate, candidate['fields'][0]['id'], 'accept')
        self.assertNotIn('FAKE_SECRET', str(caught.exception))
        info = self.root / 'x.dist-info'
        info.mkdir()
        (info / 'METADATA').write_text('Name: x\nVersion: FAKE_SECRET\n')
        baseline = self.observe(package_sources=[{'id': 'x', 'path': str(info / 'METADATA'),
                                                'format': 'dist-info', 'environment': 'uv'}])
        self.assertEqual(baseline['observations'][1]['status'], 'unknown')
        self.assertNotIn('FAKE_SECRET', json.dumps(baseline))


if __name__ == '__main__':
    unittest.main()
