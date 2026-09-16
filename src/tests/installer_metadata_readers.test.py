"""Synthetic selected metadata only; no Git processes or real checkout reads."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core/profile_discovery.py'


def backend():
    spec = importlib.util.spec_from_file_location('metadata_discovery_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.d = backend()

    def repo(self, name='repo', commit='a' * 40):
        root = self.root / name
        git = root / '.git'
        git.mkdir(parents=True)
        (git / 'HEAD').write_text(commit + '\n')
        return {'id': name, 'root': str(root), 'git_dir': str(git),
                'common_dir': str(git), 'ref_paths': []}

    def fields(self, candidate):
        return {field['id']: field for field in candidate['fields']}

    def manifest(self, data, format='environment-json', placement='host', name='environment.json'):
        path = self.root / name
        path.write_text(json.dumps(data))
        return {'id': 'tools', 'path': str(path), 'format': format,
                'environment': 'robot', 'placement': placement}

    def test_multi_evidence_and_alternatives_reject_malformed_values(self):
        selected = self.repo()
        selected['component'] = 'lab'
        candidate = self.d.propose(self.d.observe(git_sources=[selected]))
        for key, value in (('evidence', [{}]), ('alternatives', [None]), ('alternatives', [{}])):
            forged = json.loads(json.dumps(candidate))
            field = self.fields(forged)['component:lab.source']
            field[key] = value
            forged['revision'] = self.d._revision(forged)
            try:
                self.d.review(forged, field['id'], 'defer')
            except Exception as error:
                self.assertIsInstance(error, ValueError, 'malformed evidence needs a sanitized validation error')
            else:
                self.fail('malformed evidence was accepted')

    def test_multiple_runtime_environments_offer_explicit_review_choices(self):
        source = self.manifest({'name': 'robot', 'manager': 'uv', 'python': '3.10', 'tools': [], 'notes': []})
        source['runtime'] = 'gr00t'
        other_dir = self.root / 'other'
        other_dir.mkdir()
        other_path = other_dir / 'environment.json'
        other_path.write_text(json.dumps({'name': 'robot-next', 'manager': 'uv', 'python': '3.12',
                                         'tools': [], 'notes': []}))
        other = {**source, 'id': 'other', 'path': str(other_path), 'environment': 'robot-next'}
        try:
            baseline = self.d.observe(metadata_sources=[source, other])
        except ValueError:
            self.fail('multiple runtime environments must remain reviewable')
        candidate = self.d.propose(baseline)
        field = self.fields(candidate)['runtime:gr00t']
        self.assertIsNone(field['value'])
        self.assertEqual({v['environment'] for v in field['alternatives']}, {'robot', 'robot-next'})
        choice = next(v for v in field['alternatives'] if v['environment'] == 'robot')
        candidate = self.d.review(candidate, field['id'], 'edit', value=choice)
        again = self.d.propose(baseline, previous=candidate)
        self.assertEqual(self.fields(again)[field['id']]['value'], choice)
        self.assertFalse(self.fields(again)[field['id']]['evidence_changed'])
        self.d.build_review(baseline, again)

    def test_multiple_associated_repositories_offer_alternatives_and_preserve_choice(self):
        selections = [self.repo('clone-one', 'a' * 40), self.repo('clone-two', 'b' * 40)]
        for selected in selections:
            selected['component'] = 'lab'
            (Path(selected['git_dir']) / 'config').write_text('[remote "origin"]\nurl=https://github.com/example/robot.git\n')
        try:
            baseline = self.d.observe(git_sources=selections)
        except ValueError:
            self.fail('multiple selected candidates must become reviewable alternatives')
        candidate = self.d.propose(baseline)
        field = self.fields(candidate)['component:lab.source']
        self.assertIsNone(field['value'])
        self.assertEqual(len(field['alternatives']), 2)
        self.assertEqual(set(field['evidence']), {'repository:clone-one', 'repository:clone-two'})
        with self.assertRaises(ValueError):
            self.d.review(candidate, field['id'], 'accept')
        choice = field['alternatives'][1]
        candidate = self.d.review(candidate, field['id'], 'edit', value=choice)
        changed = self.d.observe(git_sources=list(reversed(selections)))
        candidate = self.d.propose(changed, previous=candidate)
        field = self.fields(candidate)['component:lab.source']
        self.assertEqual(field['value'], choice)
        self.assertEqual(field['decision'], 'edit')
        self.assertFalse(field['evidence_changed'])
        self.d.build_review(changed, candidate)

    def test_deadline_expiry_during_parse_cannot_be_reported_observed(self):
        from unittest.mock import patch
        source = self.manifest({'name': 'robot', 'manager': 'uv', 'python': None, 'tools': [], 'notes': []})
        now = [0.0]
        original = json.loads
        def parse(*args, **kwargs):
            value = original(*args, **kwargs)
            now[0] = 3.0
            return value
        with patch.object(self.d.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(self.d._metadata.json, 'loads', side_effect=parse):
            baseline = self.d.observe(metadata_sources=[source], limits={'max_seconds': 2})
        self.assertEqual(baseline['observations'][0]['status'], 'unknown')
        self.assertEqual(baseline['observations'][0]['reason'], 'time_limit')
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_hostile_manifest_content_never_reaches_reports_or_review_values(self):
        tool = {'name': 'motion', 'version': '1', 'source': None, 'purpose': None}
        valid = {'name': 'robot', 'manager': 'uv', 'python': None, 'tools': [tool], 'notes': []}
        source = self.manifest(valid)
        cases = [b'{"name":"robot","name":"duplicate"}', b'[]', b'\\xff',
                 b'{' + b' ' * 70000 + b'}']
        for value in ('bad\x1bFAKE_SECRET', 'token=FAKE_SECRET', '\u202eFAKE_SECRET'):
            changed = json.loads(json.dumps(valid))
            changed['tools'][0]['purpose'] = value
            cases.append(json.dumps(changed).encode())
        for url in ('file:///private/FAKE_SECRET', 'ext::FAKE_SECRET',
                    'https://example.org/org/%46AKE_SECRET', 'https://example.org/../FAKE_SECRET',
                    'https://example.org:wrong/org/FAKE_SECRET', 'https://example.org/org/\x1bFAKE_SECRET'):
            changed = json.loads(json.dumps(valid))
            changed['tools'][0]['source'] = url
            cases.append(json.dumps(changed).encode())
        for raw in cases:
            with self.subTest(raw=raw[:30]):
                Path(source['path']).write_bytes(raw)
                baseline = self.d.observe(metadata_sources=[source])
                self.assertNotEqual(baseline['observations'][0]['status'], 'observed')
                self.assertNotIn('FAKE_SECRET', json.dumps(baseline))
                self.d.build_review(baseline, self.d.propose(baseline))
        Path(source['path']).write_text(json.dumps(valid))
        candidate = self.d.propose(self.d.observe(metadata_sources=[source]))
        for key, bad in (('source', 'https://user:FAKE_SECRET@example.org/org/repo'),
                         ('purpose', 'password FAKE_SECRET'), ('placement', 'execute')):
            value = {**self.fields(candidate)['tool:tools:motion']['value'], key: bad}
            with self.assertRaises(ValueError) as caught:
                self.d.review(candidate, 'tool:tools:motion', 'edit', value=value)
            self.assertNotIn('FAKE_SECRET', str(caught.exception))

    def test_new_metadata_files_reject_links_special_files_and_missing_parser(self):
        from unittest.mock import patch
        valid = {'name': 'robot', 'manager': 'uv', 'python': None, 'tools': [], 'notes': []}
        source = self.manifest(valid)
        metadata = Path(source['path'])
        private = self.root / 'private.json'
        private.write_text(json.dumps(valid))
        metadata.unlink()
        for kind in ('symlink', 'hardlink', 'fifo'):
            if kind == 'symlink':
                metadata.symlink_to(private)
            elif kind == 'hardlink':
                os.link(private, metadata)
            else:
                os.mkfifo(metadata)
            baseline = self.d.observe(metadata_sources=[source])
            self.assertEqual(baseline['observations'][0]['status'], 'inaccessible')
            self.assertEqual(baseline['observations'][0]['value']['tools'], [])
            metadata.unlink()
        source = self.manifest({}, format='pyproject', name='pyproject.toml')
        Path(source['path']).write_text('[project]\nname="motion"\n')
        with patch.object(self.d._metadata, '_toml', None):
            baseline = self.d.observe(metadata_sources=[source])
        self.assertEqual(baseline['observations'][0]['reason'], 'toml_unavailable')
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_dynamic_project_and_worktree_config_stay_unknown(self):
        source = self.manifest({}, format='pyproject', name='pyproject.toml')
        Path(source['path']).write_text('[project]\nname="motion"\ndynamic=["dependencies"]\n')
        baseline = self.d.observe(metadata_sources=[source])
        self.assertEqual(baseline['observations'][0]['status'], 'unknown')
        self.assertEqual(baseline['observations'][0]['reason'], 'dynamic_metadata_unsupported')
        selected = self.repo()
        (Path(selected['git_dir']) / 'config').write_text('[extensions]\nworktreeConfig=true\n')
        (Path(selected['git_dir']) / 'config.worktree').write_text('[include]\npath=/private/FAKE_SECRET\n')
        baseline = self.d.observe(git_sources=[selected])
        self.assertEqual(baseline['observations'][0]['status'], 'unknown')
        self.assertEqual(baseline['observations'][0]['reason'], 'worktree_config_unsupported')
        self.assertNotIn('FAKE_SECRET', json.dumps(baseline))
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_forged_new_baseline_collisions_are_rejected_before_proposal(self):
        tool = {'name': 'motion', 'version': '1', 'source': None, 'purpose': None}
        source = self.manifest({'name': 'robot', 'manager': 'uv', 'python': None, 'tools': [tool], 'notes': []})
        baseline = self.d.observe(metadata_sources=[source])
        baseline['observations'][0]['value']['tools'].append(tool)
        baseline['revision'] = self.d._revision(baseline)
        with self.assertRaises(ValueError):
            self.d.propose(baseline)
        selected = self.repo()
        selected['component'] = 'lab'
        baseline = self.d.observe(git_sources=[selected])
        duplicate = json.loads(json.dumps(baseline['observations'][0]))
        duplicate['id'] = 'repository:repo'
        baseline['observations'].append(duplicate)
        baseline['revision'] = self.d._revision(baseline)
        with self.assertRaises(ValueError):
            self.d.propose(baseline)

    def test_report_export_refuses_external_selected_git_metadata_directory(self):
        selected = self.repo()
        git = Path(selected['git_dir'])
        external = self.root / 'external-metadata'
        git.rename(external)
        (Path(selected['root']) / '.git').write_text('gitdir: ../external-metadata\n')
        selected.update(git_dir=str(external), common_dir=str(external))
        baseline = self.d.observe(git_sources=[selected])
        candidate = self.d.propose(baseline)
        report = {'baseline': baseline, 'candidate': candidate, 'review': self.d.build_review(baseline, candidate)}
        destination = external / 'forbidden-report.json'
        with self.assertRaises(ValueError):
            self.d.export_report(report, str(destination))
        self.assertFalse(destination.exists())

    def test_cancellation_stops_between_file_chunks_without_finishing_parse(self):
        from unittest.mock import patch
        source = self.manifest({'name': 'robot', 'manager': 'uv', 'python': None, 'tools': [],
                                'notes': [], 'ignored': 'x' * 20000})
        chunks = []
        original = os.read
        def read(fd, size):
            chunk = original(fd, size)
            chunks.append(len(chunk))
            return chunk
        with patch.object(self.d.os, 'read', side_effect=read):
            baseline = self.d.observe(metadata_sources=[source], cancelled=lambda: bool(chunks))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(baseline['observations'][0]['reason'], 'cancelled')
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_tool_duplicates_are_deduped_and_conflicts_remain_unresolved(self):
        tool = {'name': 'motion-tool', 'version': '1.0', 'source': None, 'purpose': None}
        data = {'name': 'robot', 'manager': 'uv', 'python': None, 'tools': [tool, tool], 'notes': []}
        source = self.manifest(data)
        baseline = self.d.observe(metadata_sources=[source])
        self.assertEqual(len(baseline['observations'][0]['value']['tools']), 1)
        self.d.build_review(baseline, self.d.propose(baseline))
        data['tools'] = [tool, {**tool, 'name': 'motion_tool', 'version': '2.0'}]
        Path(source['path']).write_text(json.dumps(data))
        baseline = self.d.observe(metadata_sources=[source])
        item = baseline['observations'][0]
        self.assertEqual(item['status'], 'conflicting')
        self.assertEqual(item['value']['tools'], [])
        candidate = self.d.propose(baseline)
        self.assertIn('coverage:environment:tools', self.fields(candidate))
        self.d.build_review(baseline, candidate)

    def test_explicit_ref_falls_back_to_bounded_packed_refs(self):
        selected = self.repo()
        git = Path(selected['git_dir'])
        (git / 'HEAD').write_text('ref: refs/heads/main\n')
        selected['ref_paths'] = ['refs/heads/main']
        (git / 'packed-refs').write_text('# pack-refs with: peeled fully-peeled sorted\n'
                                          + 'f' * 40 + ' refs/heads/main\n'
                                          + 'a' * 40 + ' refs/heads/other\n')
        baseline = self.d.observe(git_sources=[selected])
        item = baseline['observations'][0]
        self.assertEqual(item['status'], 'observed')
        self.assertEqual(item['value']['head']['commit'], 'f' * 40)
        self.assertNotIn('refs/heads/other', json.dumps(baseline))
        self.d.build_review(baseline, self.d.propose(baseline))
        (git / 'packed-refs').write_text('f' * 40 + ' refs/heads/main\n' + 'e' * 40 + ' refs/heads/main\n')
        item = self.d.observe(git_sources=[selected])['observations'][0]
        self.assertEqual(item['status'], 'unknown')
        self.assertIsNone(item['value']['head']['commit'])

    def test_parsed_records_and_notes_share_global_entry_budget(self):
        source = self.manifest({'name': 'robot', 'manager': 'uv', 'python': None,
                                'tools': [], 'notes': ['One', 'Two', 'Three']})
        second = {**source, 'id': 'second'}
        baseline = self.d.observe(metadata_sources=[source, second], limits={'max_entries': 2})
        first, second_item = baseline['observations']
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(first['reason'], 'entry_limit')
        self.assertLessEqual(len(first['value']['notes']), 1)
        self.assertEqual(second_item['reason'], 'entry_limit')
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_metadata_mount_identity_guard_fails_closed_before_content_read(self):
        self.assertTrue(hasattr(self.d, '_mount_id'), 'descriptor mount identity check missing')
        from unittest.mock import patch
        selected = self.repo()
        git = Path(selected['git_dir'])
        fd = self.d._open_directory(str(git))
        try:
            actual = self.d._mount_id(fd)
            self.assertIsInstance(actual, int)
            self.assertGreater(actual, 0)
            # Simulate a same-device bind mount: device checks alone cannot detect it.
            with patch.object(self.d, '_mount_id', side_effect=[actual, actual + 1]), \
                    patch.object(self.d.os, 'read', side_effect=AssertionError('content read before mount check')):
                with self.assertRaises(OSError):
                    self.d._read_metadata(fd, 'HEAD', 100)
        finally:
            os.close(fd)

    def test_selected_ref_rejects_symlink_ancestor_without_reading_target(self):
        selected = self.repo()
        git = Path(selected['git_dir'])
        private = self.root / 'outside'
        private.mkdir()
        (private / 'main').write_text('e' * 40 + '\n')
        (git / 'refs').mkdir()
        (git / 'refs/heads').symlink_to(private, target_is_directory=True)
        (git / 'HEAD').write_text('ref: refs/heads/main\n')
        selected['ref_paths'] = ['refs/heads/main']
        item = self.d.observe(git_sources=[selected])['observations'][0]
        self.assertEqual(item['status'], 'inaccessible')
        self.assertIsNone(item['value']['head']['commit'])

    def test_uv_lock_json_and_toml_are_declared_pins_not_installed_proof(self):
        source = self.manifest({'version': 1, 'package': [
            {'name': 'motion', 'version': '2.0', 'source': {'registry': 'https://user:FAKE_SECRET@example.org/simple'},
             'sdist': {'url': 'PRIVATE_DOWNLOAD'}}]}, format='uv-lock-json', name='uv.lock.json', placement='environment')
        for format, name, raw in [('uv-lock-json', 'uv.lock.json', Path(source['path']).read_text()),
                                 ('uv-lock', 'uv.lock', 'version = 1\n[[package]]\nname = "motion"\nversion = "2.0"\n'
                                  'source = {registry = "https://user:FAKE_SECRET@example.org/simple"}\n')]:
            with self.subTest(format=format):
                source.update(format=format, path=str(self.root / name))
                Path(source['path']).write_text(raw)
                baseline = self.d.observe(metadata_sources=[source])
                item = baseline['observations'][0]
                self.assertEqual(item['status'], 'observed')
                self.assertEqual(item['value']['manager'], 'uv')
                self.assertEqual(item['value']['tools'], [{'name': 'motion', 'version': '2.0',
                                 'source': 'https://example.org/simple', 'purpose': None}])
                self.assertNotIn('FAKE_SECRET', json.dumps(baseline))
                self.assertNotIn('PRIVATE_DOWNLOAD', json.dumps(baseline))
                self.d.build_review(baseline, self.d.propose(baseline))

    def test_explicit_runtime_association_uses_known_manifest_not_guesses(self):
        source = self.manifest({'name': 'robot', 'manager': 'uv', 'python': '3.10', 'tools': [], 'notes': []})
        source['runtime'] = 'gr00t'
        try:
            baseline = self.d.observe(metadata_sources=[source])
        except ValueError:
            self.fail('explicit runtime association is not admitted')
        candidate = self.d.propose(baseline)
        self.assertEqual(self.fields(candidate)['runtime:gr00t']['value'],
                         {'manager': 'uv', 'environment': 'robot', 'python': '3.10'})
        reviewed = self.d.review(candidate, 'runtime:gr00t', 'accept')
        self.d.build_review(baseline, reviewed)
        self.assertNotIn('torch', self.fields(reviewed)['runtime:gr00t']['value'])
        source['runtime'] = 'lab'
        baseline = self.d.observe(metadata_sources=[source])
        self.assertIsNone(self.fields(self.d.propose(baseline))['runtime:lab']['value'])
        with self.assertRaises(ValueError):
            self.d.observe(metadata_sources=[{**source, 'runtime': 'kit'}])
        with self.assertRaises(ValueError):
            self.d.observe(metadata_sources=[source, source])

    def test_explicit_component_association_proposes_source_not_enablement(self):
        selected = self.repo('not-a-component-name')
        selected['component'] = 'lab'
        (Path(selected['git_dir']) / 'config').write_text('[remote "origin"]\nurl = https://user:FAKE_SECRET@github.com/example/robot.git\n')
        try:
            baseline = self.d.observe(git_sources=[selected])
        except ValueError:
            self.fail('explicit component association is not admitted')
        candidate = self.d.propose(baseline)
        field = self.fields(candidate)['component:lab.source']
        self.assertEqual(field['value'], {'mode': 'git', 'repository': 'https://github.com/example/robot.git',
                                         'ref': 'a' * 40, 'revision': 'a' * 40})
        self.assertIsNone(self.fields(candidate)['components.selection']['value'])
        self.assertEqual(field['evidence'], ['repository:not-a-component-name'])
        candidate = self.d.review(candidate, field['id'], 'accept')
        self.d.build_review(baseline, candidate)
        self.assertEqual(baseline['observations'][0]['value']['dirty'], 'unknown')
        for component in ('sim', 'arbitrary'):
            with self.assertRaises(ValueError):
                self.d.observe(git_sources=[{**selected, 'component': component}])
        with self.assertRaises(ValueError):
            self.d.observe(git_sources=[selected, selected])
        (Path(selected['git_dir']) / 'config').write_text('[remote "origin"]\nurl = ssh://example.org/org/robot.git\n')
        baseline = self.d.observe(git_sources=[selected])
        self.assertIsNone(self.fields(self.d.propose(baseline))['component:lab.source']['value'])

    def test_pyproject_toml_extracts_declared_tools_without_importing_project(self):
        source = self.manifest({}, format='pyproject', name='pyproject.toml', placement='project')
        Path(source['path']).write_text('[build-system]\nrequires = ["FAKE_BUILD_BACKEND"]\nbuild-backend = "evil_backend"\n'
                                       '[project]\nname = "robot-motion"\nversion = "0.2"\n'
                                       'dependencies = ["geometry-kit==1.3", "solver>=2.0"]\n'
                                       '[project.scripts]\nrun = "evil_backend:main"\n')
        (self.root / 'evil_backend.py').write_text('raise RuntimeError("MUST_NOT_IMPORT")\n')
        baseline = self.d.observe(metadata_sources=[source])
        item = baseline['observations'][0]
        self.assertEqual(item['status'], 'observed')
        self.assertEqual(item['value']['manager'], 'project')
        tools = {v['name']: v for v in item['value']['tools']}
        self.assertEqual(tools['robot-motion']['version'], '0.2')
        self.assertEqual(tools['geometry-kit']['version'], '1.3')
        self.assertIsNone(tools['solver']['version'])
        self.assertNotIn('FAKE_BUILD_BACKEND', json.dumps(baseline))
        self.d.build_review(baseline, self.d.propose(baseline))

    def test_environment_tool_and_user_notes_share_review_decision_path(self):
        self.assertIn('metadata_sources', __import__('inspect').signature(self.d.observe).parameters)
        data = {'name': 'robot', 'manager': 'uv', 'python': '3.10',
                'tools': [{'name': 'motion-tool', 'version': '1.2',
                           'source': 'https://user:FAKE_SECRET@example.org/org/motion?token=FAKE_SECRET',
                           'purpose': 'Robot motion workflow'}],
                'notes': ['Keep project tooling separate']}
        source = self.manifest(data, placement='container')
        baseline = self.d.observe(metadata_sources=[source])
        self.assertFalse(baseline['incomplete'])
        self.assertNotIn('FAKE_SECRET', json.dumps(baseline))
        candidate = self.d.propose(baseline)
        fields = self.fields(candidate)
        self.assertEqual(fields['environment:tools']['value'], {'name': 'robot', 'manager': 'uv',
                         'placement': 'container', 'location': source['path'], 'python': '3.10'})
        tool = fields['tool:tools:motion-tool']
        self.assertEqual(tool['value']['source'], 'https://example.org/org/motion')
        self.assertEqual(tool['value']['purpose'], 'Robot motion workflow')
        self.assertEqual(tool['state'], 'unresolved')
        self.assertEqual(tool['value']['placement'], 'container')
        self.assertEqual(fields['note:tools:0']['value'], 'Keep project tooling separate')
        candidate = self.d.review(candidate, tool['id'], 'accept', required=True)
        candidate = self.d.review(candidate, 'note:tools:0', 'reject')
        data['tools'][0]['version'] = '2.0'
        Path(source['path']).write_text(json.dumps(data))
        changed = self.d.observe(metadata_sources=[source])
        candidate = self.d.propose(changed, previous=candidate)
        fields = self.fields(candidate)
        self.assertEqual(fields[tool['id']]['value']['version'], '1.2')
        self.assertEqual(fields[tool['id']]['suggested_value']['version'], '2.0')
        self.assertTrue(fields[tool['id']]['evidence_changed'])
        self.assertEqual(fields['note:tools:0']['decision'], 'reject')
        report = self.d.build_review(changed, candidate)
        backlog = {v['field_id']: v for v in report['customization_backlog']}
        self.assertEqual(backlog[tool['id']]['purpose'], 'Robot motion workflow')
        self.assertIn(tool['id'], [v['field_id'] for v in report['required_unresolved']])
        gone = self.d.propose(self.d.observe(), previous=candidate)
        self.assertTrue(self.fields(gone)[tool['id']]['not_selected'])

    def test_admission_paths_is_pure_exact_and_rejects_unsafe_selections(self):
        self.assertTrue(hasattr(self.d, 'admission_paths'), 'pure admission API missing')
        from unittest.mock import patch
        selected = self.repo()
        source = {'id': 'tools', 'path': str(self.root / 'environment.json'),
                  'format': 'environment-json', 'environment': 'robot', 'placement': 'container'}
        with patch.object(self.d, '_open_directory', side_effect=AssertionError('unexpected read')):
            paths = self.d.admission_paths(git_sources=[selected], metadata_sources=[source])
            self.assertEqual(paths['directories'], [])
            self.assertEqual(paths['files'], [source['path']])
            self.assertEqual(set(paths['optional_files']), {str(Path(selected['root']) / '.gitmodules'),
                             str(Path(selected['git_dir']) / 'HEAD'), str(Path(selected['git_dir']) / 'commondir'),
                             str(Path(selected['common_dir']) / 'config'), str(Path(selected['common_dir']) / 'packed-refs')})
            invalid = [{**selected, 'ref_paths': ['refs/heads/../private']},
                       {**selected, 'git_dir': '/tmp/../escape'},
                       {**selected, 'ref_paths': ['refs/heads/' + 'x/' * 20 + 'branch']},
                       {**selected, 'ref_paths': ['refs/heads/main', 'refs/heads/main']}]
            for value in invalid:
                with self.assertRaises(ValueError):
                    self.d.admission_paths(git_sources=[value])
            for value in ({**source, 'path': str(self.root / '.env')},
                          {**source, 'placement': 'docker-command'}, {**source, 'unknown': 'field'}):
                with self.assertRaises(ValueError):
                    self.d.admission_paths(metadata_sources=[value])

    def test_config_includes_refused_and_partial_coverage_visible(self):
        selected = self.repo()
        for header in ('[include]', '[includeIf "gitdir:/private/"]'):
            with self.subTest(header=header):
                (Path(selected['git_dir']) / 'config').write_text(header + '\n path = /private/FAKE_SECRET\n')
                baseline = self.d.observe(git_sources=[selected])
                item = baseline['observations'][0]
                self.assertEqual(item['status'], 'unknown')
                self.assertEqual(item['reason'], 'config_include_refused')
                self.assertNotIn('FAKE_SECRET', json.dumps(baseline))
                candidate = self.d.propose(baseline)
                field = self.fields(candidate)['coverage:repository:repo']
                self.assertIsNone(field['value'])
                self.assertEqual(field['state'], 'unresolved')
                self.d.build_review(baseline, candidate)

    def test_submodule_metadata_and_remote_urls_are_nonexecuting_redacted_evidence(self):
        selected = self.repo('arena')
        root, git = Path(selected['root']), Path(selected['git_dir'])
        (git / 'config').write_text('[remote "origin"]\n url = https://user:FAKE_SECRET@example.org/org/arena.git?token=FAKE_SECRET#private\n'
                                  '[core]\n fsmonitor = /FAKE_HELPER\n[extensions]\n partialClone = origin\n')
        (root / '.gitmodules').write_text('[submodule "robot"]\n path = modules/robot\n url = git@example.org:org/robot.git\n')
        subgit = git / 'modules/robot'
        subgit.mkdir(parents=True)
        (subgit / 'HEAD').write_text('d' * 40 + '\n')
        checkout = root / 'modules/robot'
        checkout.mkdir(parents=True)
        (checkout / '.git').write_text('gitdir: ../../.git/modules/robot\n')
        sub = {'id': 'robot', 'root': str(checkout), 'git_dir': str(subgit),
               'common_dir': str(subgit), 'ref_paths': []}
        (root / 'dirty.py').write_text('PRIVATE_DIFF')
        (git / 'index').write_bytes(b'PRIVATE_INDEX')
        before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        baseline = self.d.observe(git_sources=[selected, sub])
        first, second = baseline['observations']
        self.assertEqual(first['status'], 'observed')
        self.assertEqual(first['value']['remotes'], [{'name': 'origin', 'url': 'https://example.org/org/arena.git'}])
        self.assertEqual(first['value']['submodules'], [{'name': 'robot', 'path': 'modules/robot',
                                                       'url': 'ssh://example.org/org/robot.git'}])
        self.assertEqual(second['value']['head']['commit'], 'd' * 40)
        self.assertEqual(second['value']['pin_provenance'], 'selected-head-only')
        self.d.build_review(baseline, self.d.propose(baseline))
        self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})
        for private in ('FAKE_SECRET', 'FAKE_HELPER', 'PRIVATE_DIFF', 'PRIVATE_INDEX'):
            self.assertNotIn(private, json.dumps(baseline))

    def test_explicit_worktree_indirection_resolves_only_selected_ref(self):
        primary = self.repo('primary')
        common = Path(primary['git_dir'])
        git = common / 'worktrees/feature'
        git.mkdir(parents=True)
        checkout = self.root / 'feature'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: ../primary/.git/worktrees/feature\n')
        (git / 'commondir').write_text('../..\n')
        (git / 'HEAD').write_text('ref: refs/heads/feature\n')
        (common / 'refs/heads').mkdir(parents=True)
        (common / 'refs/heads/feature').write_text('c' * 40 + '\n')
        selected = {'id': 'feature', 'root': str(checkout), 'git_dir': str(git),
                    'common_dir': str(common), 'ref_paths': ['refs/heads/feature']}
        item = self.d.observe(git_sources=[selected])['observations'][0]
        self.assertEqual(item['status'], 'observed')
        self.assertEqual(item['value']['head'], {'ref': 'refs/heads/feature', 'commit': 'c' * 40})
        # The same ref without explicit selection cannot be opened implicitly.
        item = self.d.observe(git_sources=[{**selected, 'ref_paths': []}])['observations'][0]
        self.assertEqual(item['status'], 'unknown')
        self.assertIsNone(item['value']['head']['commit'])
        self.assertEqual(item['reason'], 'ref_not_selected')
        # A forged gitdir must not authorize a different selected metadata directory.
        (checkout / '.git').write_text('gitdir: /outside/private\n')
        item = self.d.observe(git_sources=[selected])['observations'][0]
        self.assertEqual(item['status'], 'unknown')
        self.assertEqual(item['reason'], 'indirection_not_selected')

    def test_selected_detached_head_enters_review_without_dirty_claim(self):
        self.assertIn('git_sources', __import__('inspect').signature(self.d.observe).parameters,
                      'explicit Git selection API is missing')
        selected = self.repo()
        baseline = self.d.observe(git_sources=[selected])
        item = baseline['observations'][0]
        self.assertEqual(item['id'], 'repository:repo')
        self.assertEqual(item['status'], 'observed')
        self.assertEqual(item['value']['head'], {'ref': None, 'commit': 'a' * 40})
        self.assertEqual(item['value']['dirty'], 'unknown')
        self.assertEqual(item['value']['pin_provenance'], 'selected-head-only')
        candidate = self.d.propose(json.loads(json.dumps(baseline)))
        field = self.fields(candidate)['repository:repo']
        self.assertFalse(field['required'])
        self.assertEqual(field['decision'], None)
        candidate = self.d.review(candidate, field['id'], 'accept')
        (Path(selected['git_dir']) / 'HEAD').write_text('b' * 40 + '\n')
        changed = self.d.observe(git_sources=[selected])
        candidate = self.d.propose(changed, previous=candidate)
        field = self.fields(candidate)['repository:repo']
        self.assertEqual(field['value']['head']['commit'], 'a' * 40)
        self.assertEqual(field['suggested_value']['head']['commit'], 'b' * 40)
        self.assertTrue(field['evidence_changed'])
        self.d.build_review(changed, candidate)


if __name__ == '__main__':
    unittest.main()
