"""Host reports are portable evidence, never local host read grants."""
import json
import importlib
import importlib.util
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / 'isaac-installer/bin/isaac-installer'
sys.path.insert(0, str(ROOT / 'isaac-installer/lib/core'))
discovery = importlib.import_module('profile_discovery')


def host_report():
    home = '/home/synthetic-operator'
    parent = home + '/Documents/GitHub'
    workspace = parent + '/BoredEngineer'
    return {
        'schema_version': 1, 'kind': 'host-inventory',
        'context': {'home': home, 'system_root': '/', 'identity': 'user-supplied-host',
                    'execution_authorized': False},
        'workspace': {'parent': parent, 'candidates': [workspace], 'selected': workspace},
        'repositories': [{'path': workspace + '/IsaacLab', 'component': 'lab',
                          'repository': 'https://github.com/example/IsaacLab.git',
                          'ref': 'refs/heads/release', 'commit': 'a' * 40, 'dirty': 'unknown'}],
        'isaacsim': [{'path': home + '/IsaacSim', 'version': '6.0.1'}],
        'machine': {'os': {'value': 'Ubuntu 22.04', 'source': '/etc/os-release'}},
        'packages': [{'name': 'cmake', 'version': '3.22.1-1ubuntu1',
                      'architecture': 'amd64', 'manual': True}],
        'environments': [],
        'coverage': {'complete': True, 'issues': [], 'limits': {
            'max_entries': 4096, 'max_bytes': 8388608, 'max_seconds': 10, 'max_depth': 4}},
    }


class HostInventoryIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'host-report.json'
        self.source.write_text(json.dumps(host_report()))
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.base), 'LANG': 'C.UTF-8'}

    def cli(self, *args):
        return subprocess.run(['/bin/bash', str(ENTRY), *map(str, args)],
                              capture_output=True, text=True, env=self.env, timeout=30)

    def editable_fixture(self):
        spec = importlib.util.spec_from_file_location('editable_collector', ROOT/'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home, system = self.base/'home', self.base/'system'
        system.mkdir()
        env = home/'Documents/GitHub/BoredEngineer/.venv'
        site = env/'lib/python3.12/site-packages'
        site.mkdir(parents=True)
        (env/'pyvenv.cfg').write_text('version = 3.12.1\n')
        (site/'local.pth').write_text('/unselected/synthetic-source\n')
        report = module.collect(str(home), str(system), workspace_name='BoredEngineer', include_editable=True, scope='software')
        return module, report, str(env)

    def test_editable_schema_refuses_malformed_sections_and_unbound_sources(self):
        _, report, env = self.editable_fixture()
        discovery._host.validate_report(report)
        with patch('builtins.open', side_effect=AssertionError('host evidence is not a read grant')):
            baseline = discovery._host.baseline(report, str(self.source), discovery)
            discovery.build_review(baseline, discovery.propose(baseline))
        self.assertEqual(baseline['observations'][0]['value']['details']['editable'], report['details']['editable'])
        self.assertEqual(baseline['original_observed_roots'], [str(self.source)])
        mutations = [
            lambda r: r['details'].update(editable=[]),
            lambda r: r['details']['editable'].update(environments=[]),
            lambda r: r['details']['editable']['environments'].update({env:None}),
            lambda r: r['details']['editable'].update(version=True),
            lambda r: r['details']['editable']['environments'][env].update(records=True),
            lambda r: r['details']['editable']['environments'][env]['records'][0].update(source='/unselected/source.pth'),
            lambda r: r['details']['editable']['environments'][env]['records'][0].update(source=env+'/secrets/source.pth'),
            lambda r: r['details']['editable']['environments'][env]['records'][0].update(local_path='import PRIVATE'),
            lambda r: r['details']['editable']['environments'][env]['records'][0].update(line=True),
            lambda r: r['details']['editable']['environments'][env]['records'][0].update(local_path='../escape'),
            lambda r: r['workspace'].update(requested_name='other'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                bad = deepcopy(report); mutate(bad)
                with self.assertRaises(ValueError): discovery._host.validate_report(bad)
        bad = deepcopy(report)
        bad['details']['editable']['environments'][env]['records'] *= 129
        with self.assertRaises(ValueError): discovery._host.validate_report(bad)


    def test_legacy_report_package_punctuation_survives_import_and_review(self):
        for manager in ('conda', 'venv', 'unknown'):
            for name in ('pkg+local', 'pkg:local', '9pkg_.+:-'):
                with self.subTest(manager=manager, name=name):
                    report = host_report()
                    self.assertNotIn('details', report)
                    report['environments'] = [{'path':report['context']['home']+'/legacy-env',
                        'name':'legacy-env', 'manager':manager, 'python':None,
                        'packages':[{'name':name, 'version':'1.0'}]}]
                    with patch('builtins.open', side_effect=AssertionError('report paths are not read grants')):
                        baseline = discovery._host.baseline(report, str(self.source), discovery)
                        discovery.build_review(baseline, discovery.propose(baseline))
                    self.assertEqual(baseline['observations'][0]['value']['environments'], report['environments'])

    def test_underscore_package_names_are_a_narrow_conda_only_report_extension(self):
        report = host_report()
        pair = {'name':'_libgcc_mutex', 'version':'0.1'}
        report['environments'] = [{'path':report['context']['home']+'/legacy-env',
            'name':'legacy-env', 'manager':'conda', 'python':None, 'packages':[pair]}]
        discovery._host.validate_report(report)
        for manager in ('venv', 'unknown'):
            with self.subTest(manager=manager):
                bad = deepcopy(report)
                bad['environments'][0]['manager'] = manager
                with self.assertRaises(discovery._host.InventoryError):
                    discovery._host.validate_report(bad)
        for conda in (False, True):
            with self.assertRaises(discovery._host.InventoryError):
                discovery._host.package({**pair, 'architecture':'all', 'manual':None}, system=True, conda=conda)
        with self.assertRaises(discovery._host.InventoryError):
            discovery._host.package(pair)
        for name in ('_name+extra', '_name:extra', '_name/escape', '_name\n', '_token-private'):
            with self.subTest(name=name):
                bad = deepcopy(report)
                bad['environments'][0]['packages'][0]['name'] = name
                with self.assertRaises(discovery._host.InventoryError):
                    discovery._host.validate_report(bad)

    def test_portable_import_proposes_paths_without_reading_host(self):
        output = self.base / 'imported.json'
        before = self.source.read_bytes()
        baseline = discovery._host.baseline(host_report(), str(self.source), discovery)
        discovery.build_review(baseline, discovery.propose(baseline))
        result = self.cli('import-host-report', '--report', self.source, '--output', output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bundle = json.loads(output.read_text())
        fields = {item['id']: item for item in bundle['candidate']['fields']}
        self.assertEqual(fields['workspace:host.name']['value'], 'BoredEngineer')
        self.assertEqual(fields['workspace:host.root']['value'], '/home/synthetic-operator/Documents/GitHub')
        self.assertEqual(fields['component:lab.source']['value']['revision'], 'a' * 40)
        self.assertTrue(all(f['decision'] is None for f in fields.values()))
        self.assertFalse(bundle['candidate']['apply_supported'])
        self.assertEqual(bundle['baseline']['original_observed_roots'], [str(self.source)])
        self.assertEqual(bundle['baseline']['observations'][0]['evidence']['method'], 'imported-host-inventory')
        self.assertEqual(bundle['baseline']['observations'][0]['value']['packages'][0]['name'], 'cmake')
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_software_followup_import_keeps_ambiguous_sources_unapproved(self):
        spec = importlib.util.spec_from_file_location('followup_collector', ROOT/'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        home, system = self.base/'home', self.base/'system'
        home.mkdir(); system.mkdir()
        for name, commit in (('BoredEngineer', 'a'), ('boredengineering', 'b')):
            git = home/'Documents/GitHub'/name/'IsaacLab/.git'
            git.mkdir(parents=True)
            (git/'HEAD').write_text(commit*40+'\n')
            (git/'config').write_text('[remote "origin"]\nurl=https://github.com/NVIDIA/IsaacLab.git\n')
        meta = home/'miniconda3/envs/robot/conda-meta'
        meta.mkdir(parents=True)
        (meta/'python.json').write_text('{"name":"python","version":"3.12.1"}')
        report = module.collect(str(home), str(system), scope='software')
        self.source.write_text(json.dumps(report))
        before = self.source.read_bytes()
        output = self.base/'software-candidate.json'
        result = self.cli('import-host-report', '--report', self.source, '--output', output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bundle = json.loads(output.read_text())
        fields = {f['id']: f for f in bundle['candidate']['fields']}
        self.assertIsNone(fields['workspace:host.name']['value'])
        self.assertIsNone(fields['component:lab.source']['value'])
        self.assertEqual(len(fields['component:lab.source']['alternatives']), 2)
        self.assertTrue(any(f['id'].startswith('environment:') for f in fields.values()))
        self.assertTrue(all(f['decision'] is None for f in fields.values()))
        self.assertFalse(bundle['candidate']['apply_supported'])
        retained = bundle['baseline']['observations'][0]['value']
        self.assertEqual(retained['machine'], {})
        self.assertEqual(len(retained['repositories']), 2)
        self.assertEqual(self.source.read_bytes(), before)

    def test_environment_proposal_identity_survives_reordering(self):
        report = host_report()
        report['environments'] = [
            {'path': report['context']['home'] + '/miniconda3/envs/' + name,
             'name': name, 'manager': 'conda', 'python': '3.12',
             'packages': [{'name': 'numpy', 'version': '2.1.0'}]}
            for name in ('lab', 'other')]
        before = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(before)
        lab = next(f for f in candidate['fields'] if f['id'].startswith('environment:') and f['value']['name'] == 'lab')
        candidate = discovery.review(candidate, lab['id'], 'accept')
        report['environments'].reverse()
        after = discovery._host.baseline(report, str(self.source), discovery, previous=before)
        refreshed = discovery.propose(after, previous=candidate)
        field = next(f for f in refreshed['fields'] if f['id'] == lab['id'])
        self.assertEqual(field['suggested_value']['name'], 'lab')
        self.assertFalse(field['evidence_changed'])

    def test_review_export_both_renderers_and_dry_run_with_remote_paths(self):
        imported = self.base / 'imported.json'
        result = self.cli('import-host-report', '--report', self.source, '--output', imported)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        decisions = [{'field_id': 'workspace:host.' + key, 'decision': 'accept'} for key in ('root', 'name', 'layout')]
        decisions += [
            {'field_id': 'components.selection', 'decision': 'edit', 'value': ['sim', 'lab']},
            {'field_id': 'component:lab.source', 'decision': 'accept'},
            {'field_id': 'component:lab.execution', 'decision': 'declare', 'value': 'native'},
            {'field_id': 'runtime:lab', 'decision': 'declare',
             'value': {'manager': 'conda', 'environment': 'isaaclab', 'python': '3.12'}},
            {'field_id': 'component:sim.source', 'decision': 'declare', 'value': {
                'mode': 'standalone', 'version': '6.0.1',
                'url': 'https://example.org/synthetic-only.zip', 'sha256': 'b' * 64}},
            {'field_id': 'runtime:kit', 'decision': 'declare', 'value': {'manager': 'bundled', 'environment': 'kit'}},
            {'field_id': 'component:sim.execution', 'decision': 'declare', 'value': 'native'},
        ]
        decision_file = self.base / 'decisions.json'
        decision_file.write_text(json.dumps(decisions))
        reviewed = self.base / 'reviewed.json'
        result = self.cli('review-profile', '--report', imported, '--decisions', decision_file, '--output', reviewed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        refreshed = self.base / 'refreshed.json'
        result = self.cli('import-host-report', '--report', self.source, '--previous-report', reviewed, '--output', refreshed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        profile = self.base / 'desired.yaml'
        result = self.cli('export-profile', '--report', refreshed, '--name', 'synthetic-host', '--format', 'yaml', '--output', profile)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        yaml = importlib.import_module('yaml')
        self.assertTrue(yaml.safe_load(profile.read_text())['components']['lab']['enabled'])
        for adapter in ('local', 'ansible'):
            result = self.cli('render-profile', '--desired-profile', profile,
                              '--target-home', '/home/synthetic-operator', '--adapter', adapter)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rendered = json.loads(result.stdout)
            self.assertTrue(rendered['render_supported'])
            self.assertFalse(rendered['execution_authorized'])
        result = self.cli('install', '--dry-run', '--desired-profile', profile,
                          '--target-home', '/home/synthetic-operator', '--json')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan['execution_authorized'])
        lab = next(a for a in plan['actions'] if a['id'] == 'component.lab')
        self.assertEqual(lab['target'], host_report()['repositories'][0]['path'])
        self.assertEqual(lab['status'], 'unknown')

    def test_malformed_optional_containers_raise_fixed_inventory_errors(self):
        for section in ('workspace', 'details'):
            for value in (None, 17, True, 'not-a-container', [], {}):
                with self.subTest(section=section, value=value):
                    report = host_report()
                    report[section] = value
                    with self.assertRaisesRegex(discovery._host.InventoryError, r'^Invalid host inventory report\.$'):
                        discovery._host.validate_report(report)
        for parent in (None, 17, True, [], {}, '/wrong-parent'):
            with self.subTest(parent=parent):
                report = host_report()
                report['workspace'].update(parent=parent, requested_name='BoredEngineer')
                with self.assertRaisesRegex(discovery._host.InventoryError, r'^Invalid host inventory report\.$'):
                    discovery._host.validate_report(report)

    def test_invalid_reports_refuse_without_output_or_echoing_payload(self):
        mutations = [
            lambda r: r.update(schema_version=True),
            lambda r: r.update(workspace=None),
            lambda r: r.update(details=None),
            lambda r: r['workspace'].update(parent=None, requested_name='BoredEngineer'),
            lambda r: r['context'].update(execution_authorized=True),
            lambda r: r['context'].update(home='/'),
            lambda r: r['repositories'][0].update(repository='https://user:SYNTHETIC_SECRET@github.com/example/IsaacLab.git'),
            lambda r: r['repositories'][0].update(ref='refs/heads/../../escape'),
            lambda r: r['repositories'][0].update(dirty='clean'),
            lambda r: r['repositories'].append(deepcopy(r['repositories'][0])),
            lambda r: r['workspace']['candidates'].append(r['workspace']['parent'] + '/boredengineer'),
            lambda r: r['machine'].update(unapproved={'value': 'raw config', 'source': '/tmp/config'}),
            lambda r: r['packages'][0].update(manual='yes'),
            lambda r: r['packages'][0].update(version='$(touch /tmp/never)'),
            lambda r: r['coverage']['limits'].update(max_seconds=float('nan')),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                report = host_report(); mutate(report)
                self.source.write_text(json.dumps(report))
                output = self.base / ('bad-' + str(index) + '.json')
                result = self.cli('import-host-report', '--report', self.source, '--output', output)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(output.exists())
                self.assertNotIn('SYNTHETIC_SECRET', result.stdout + result.stderr)

    def test_ambiguous_workspace_does_not_choose_a_name(self):
        report = host_report()
        report['workspace']['candidates'].append(report['workspace']['parent'] + '/boredengineer')
        report['workspace']['selected'] = None
        report['coverage']['complete'] = False
        report['coverage']['issues'] = [{'code': 'ambiguous_workspace', 'path': report['workspace']['parent']}]
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        name = next(f for f in candidate['fields'] if f['id'] == 'workspace:host.name')
        self.assertIsNone(name['value'])
        self.assertTrue(name['required'])
        self.assertTrue(baseline['incomplete'])
        self.assertIn('workspace:host.name', [f['field_id'] for f in discovery.build_review(baseline, candidate)['required_unresolved']])

    def test_system_packages_stay_grouped_with_complete_raw_evidence(self):
        report = host_report()
        report['packages'] = [{'name': 'package' + str(i), 'version': '1.0',
                               'architecture': 'amd64', 'manual': None} for i in range(2000)]
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        self.assertLess(len(candidate['fields']), 12)
        self.assertEqual(len(baseline['observations'][0]['value']['packages']), 2000)
        self.assertFalse(any(f['id'].startswith('tool:') for f in candidate['fields']))

    def test_changed_evidence_requires_review_and_keeps_local_origin_history(self):
        report = host_report()
        old = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.review(discovery.propose(old), 'workspace:host.name', 'accept')
        report['packages'][0]['version'] = '4.0'
        new_source = self.base / 'new-host-report.json'
        new_source.write_text(json.dumps(report))
        new = discovery._host.baseline(report, str(new_source), discovery, previous=old)
        candidate = discovery.propose(new, previous=candidate)
        name = next(f for f in candidate['fields'] if f['id'] == 'workspace:host.name')
        self.assertTrue(name['evidence_changed'])
        self.assertEqual(new['original_observed_roots'], sorted([str(self.source), str(new_source)]))
        self.assertEqual(name['value'], 'BoredEngineer')

    def test_output_collision_and_link_input_refuse(self):
        result = self.cli('import-host-report', '--report', self.source, '--output', self.source)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(self.source.read_text()), host_report())
        link = self.base / 'linked-report.json'; link.symlink_to(self.source)
        output = self.base / 'refused.json'
        result = self.cli('import-host-report', '--report', link, '--output', output)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())


    def test_noncanonical_checkout_requires_explicit_path_review(self):
        report = host_report()
        report['repositories'][0]['path'] = report['workspace']['selected'] + '/my-special-lab'
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        required_notes = [f for f in candidate['fields'] if f['id'].startswith('note:') and f['required']]
        self.assertTrue(required_notes, 'An inferred conventional target must not silently replace the actual checkout path')

    def test_extended_sim_version_retained_without_breaking_review_grammar(self):
        report = host_report()
        report['isaacsim'][0]['version'] = '6.0.1+synthetic-build'
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        review = discovery.build_review(baseline, discovery.propose(baseline))
        self.assertFalse(review['apply_supported'])
        self.assertEqual(baseline['observations'][0]['value']['isaacsim'][0]['version'], '6.0.1+synthetic-build')

    def test_unrepresentable_workspace_name_remains_unresolved_not_fatal(self):
        report = host_report()
        selected = report['workspace']['parent'] + '/_historical-workspace'
        report['workspace'].update(candidates=[selected], selected=selected)
        report['repositories'][0]['path'] = selected + '/IsaacLab'
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        discovery.build_review(baseline, candidate)
        name = next(f for f in candidate['fields'] if f['id'] == 'workspace:host.name')
        self.assertIsNone(name['value'])
        self.assertEqual(baseline['observations'][0]['value']['workspace']['selected'], selected)

    def test_unverified_basic_markers_offer_exact_selected_scope_followups(self):
        spec = importlib.util.spec_from_file_location('missing_markers', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        (home / 'IsaacSim').mkdir(parents=True); system.mkdir()
        repo = home / 'Documents/GitHub/BoredEngineer/unknown'
        (repo / '.git').mkdir(parents=True)
        (repo / '.git/HEAD').write_text('unsupported head')
        report = module.collect(str(home), str(system))
        proposals = list(report['details']['followups'].values())
        self.assertTrue(any(p['kind'] == 'isaacsim' and p['path'] == str(home / 'IsaacSim') and p['records'] == ['VERSION'] for p in proposals))
        self.assertTrue(any(p['kind'] == 'repository-metadata' and p['path'] == str(repo) and p['records'] == ['.git/HEAD', '.git/config'] for p in proposals))
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        discovery.build_review(baseline, discovery.propose(baseline))
        bad = deepcopy(report)
        bad['coverage']['issues'].append({'code': 'missing-workspace', 'path': str(home / 'unselected')})
        bad['details']['followups'] = discovery._host.followups(bad)
        self.assertFalse(any(p['path'] == str(home / 'unselected') for p in bad['details']['followups'].values()))

    def test_report_budget_and_orphan_provenance_leave_cli_envelope_headroom(self):
        spec = importlib.util.spec_from_file_location('budget_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        report = module.collect(str(home), str(system))
        report['packages'] = [{'name': 'package' + str(i) + 'a'*110, 'architecture': 'amd64', 'version': '1.' + '0'*120, 'manual': None} for i in range(20001)]
        report['details']['system_packages']['status'] = {p['name'] + ':amd64': 'install ok installed' for p in report['packages']}
        report['coverage']['issues'] += [{'code': 'missing-file', 'path': str(home) + '/' + 'a'*3500 + '/' + str(i)} for i in range(20001)]
        # A watchdog can interrupt a function after source selection but before
        # assignment of its enclosing record. Those sources must not survive.
        report['details']['environments'][str(home / 'not-retained')] = {'python': None, 'packages': {}}
        report['details']['repositories'][str(home / 'not-retained')] = {'head': 'unused'}
        self.assertTrue(hasattr(module, '_finish'), 'No bounded report finalization exists')
        module._finish(report, module._Reader(report))
        self.assertLessEqual(len(json.dumps(report).encode()), 1024*1024)
        self.assertLessEqual(len(report['coverage']['issues']), 20000)
        self.assertLessEqual(len(report['packages']), 20000)
        self.assertTrue({'package-limit', 'issue-limit', 'report-size-limit'} <= {i['code'] for i in report['coverage']['issues']})
        self.assertEqual(report['details']['environments'], {})
        self.assertEqual(report['details']['repositories'], {})
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        discovery.build_review(baseline, candidate)
        self.source.write_text(json.dumps(report))
        result = self.cli('import-host-report', '--report', self.source, '--output', self.base / 'bounded.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLessEqual((self.base / 'bounded.json').stat().st_size, 8*1024*1024)
        # Dropping a repository for the output budget must also drop its .venv
        # scope, not strand a valid-looking environment at an unselected path.
        report = module.collect(str(home), str(system))
        workspace = report['workspace']['parent'] + '/BoredEngineer'
        report['workspace'].update(candidates=[workspace], selected=workspace)
        for i in range(128):
            path = workspace + '/' + 'r'*3500 + str(i)
            report['repositories'].append({'path': path, 'component': None, 'repository': None, 'ref': None, 'commit': None, 'dirty': 'unknown'})
            report['details']['repositories'][path] = {'head': path + '/.git/HEAD', 'config': path + '/.git/config', 'ref': None}
        env_path = report['repositories'][-1]['path'] + '/.venv'
        report['environments'] = [{'path': env_path, 'name': 'venv', 'manager': 'unknown', 'python': None, 'packages': []}]
        report['details']['environments'][env_path] = {'python': None, 'packages': {}}
        module._finish(report, module._Reader(report))
        discovery._host.validate_report(report)

    def test_package_group_membership_is_deterministic_review_evidence_not_install_intent(self):
        spec = importlib.util.spec_from_file_location('groups_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        status = system / 'var/lib/dpkg/status'; status.parent.mkdir(parents=True)
        names = ['bash', 'nvidia-driver-580', 'cmake', 'firefox', 'custom-local']
        status.write_text(''.join('Package: '+name+'\nArchitecture: amd64\nVersion: 1.0\nStatus: install ok installed\n\n' for name in names))
        report = module.collect(str(home), str(system))
        self.assertIn('package_groups', report['details'])
        groups = report['details']['package_groups']
        self.assertEqual(groups, {'basis': 'name-heuristic-review-only', 'groups': {
            'os-baseline': ['bash:amd64'], 'drivers-cuda': ['nvidia-driver-580:amd64'],
            'build-tools': ['cmake:amd64'], 'optional-applications': ['firefox:amd64'], 'uncertain': ['custom-local:amd64']}})
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        review = discovery.build_review(baseline, candidate)
        self.assertFalse(any(f['id'].startswith('tool:') for f in candidate['fields']))
        for group in groups['groups']:
            self.assertIn(group, json.dumps(review['customization_backlog']))
        self.assertTrue(all(f['decision'] is None for f in candidate['fields']))
        report['packages'].reverse()
        self.assertEqual(discovery._host.baseline(report, str(self.source), discovery)['observations'], baseline['observations'])
        report['details']['package_groups']['groups']['build-tools'] = ['not-installed:amd64']
        with self.assertRaises(ValueError): discovery._host.validate_report(report)

    def test_links_and_targeted_followups_are_data_only_and_visible_in_review(self):
        spec = importlib.util.spec_from_file_location('links_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        parent = home / 'Documents/GitHub'; parent.mkdir(parents=True)
        outside = self.base / 'unselected'; outside.mkdir()
        (outside / 'VERSION').write_text('SECRET_NOT_READ')
        (home / 'IsaacSim').symlink_to(outside)
        (parent / 'old@backup').symlink_to('token=PRIVATE')
        env = home / 'miniconda3/envs/robot'
        (env / 'conda-meta').mkdir(parents=True)
        (env / 'conda-meta/python.json').write_text('{"name":"python","version":"3.11.1"}')
        report = module.collect(str(home), str(system))
        self.assertIn('links', report['details'])
        self.assertEqual(report['details']['links'][str(home / 'IsaacSim')], {'target': str(outside), 'status': 'recorded'})
        self.assertEqual(report['details']['links'][str(parent / 'old@backup')], {'target': None, 'status': 'redacted'})
        self.assertNotIn('SECRET_NOT_READ', json.dumps(report)); self.assertNotIn('PRIVATE', json.dumps(report))
        followups = report['details']['followups']
        kinds = {f['kind'] for f in followups.values()}
        self.assertTrue({'workspace', 'isaacsim', 'linked-path', 'environment-descriptors', 'editable-metadata'} <= kinds)
        self.assertTrue(all(f['action'] == 'request-explicit-scope' for f in followups.values()))
        descriptors = next(f for f in followups.values() if f['kind'] == 'environment-descriptors')
        self.assertEqual(descriptors['path'], str(env))
        self.assertEqual(descriptors['records'], ['pyproject.toml', 'uv.lock', 'environment.yml'])
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        review = discovery.build_review(baseline, discovery.propose(baseline))
        backlog = json.dumps(review['customization_backlog'])
        for key in followups:
            self.assertIn(key, backlog)
        self.assertEqual(baseline['original_observed_roots'], [str(self.source)])
        bad = deepcopy(report)
        next(iter(bad['details']['followups'].values()))['action'] = 'scan-now'
        with self.assertRaises(ValueError): discovery._host.validate_report(bad)
        bad = deepcopy(report); bad['details']['links']['/unselected/link'] = {'target': str(outside), 'status': 'recorded'}
        with self.assertRaises(ValueError): discovery._host.validate_report(bad)

    def test_documents_symlink_ancestor_collects_and_imports_without_target_grant(self):
        spec = importlib.util.spec_from_file_location('ancestor_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        outside = self.base / 'unselected'
        git = outside / 'GitHub/BoredEngineer/IsaacLab/.git'
        git.mkdir(parents=True)
        payload = 'd' * 40
        (git / 'HEAD').write_text(payload)
        (git / 'config').write_text('[remote "origin"]\nurl=https://github.com/example/IsaacLab.git\n')
        label = str(home / 'Documents')
        (home / 'Documents').symlink_to(outside)
        # Exercise real descriptor opens while verifying every component remains
        # nofollow; the target contains a valid checkout if traversal regresses.
        real_open = os.open
        def nofollow_open(path, flags, *args, **kwargs):
            self.assertTrue(flags & os.O_NOFOLLOW)
            return real_open(path, flags, *args, **kwargs)
        with patch.object(module.os, 'open', side_effect=nofollow_open) as opens:
            # Preserve the real open capability while wrapping it for assertions.
            with patch.object(module.os, 'supports_dir_fd', os.supports_dir_fd | {opens}):
                report = module.collect(str(home), str(system))
        self.assertGreater(opens.call_count, 0)
        self.assertEqual(report['repositories'], [])
        self.assertEqual(report['workspace']['candidates'], [])
        self.assertNotIn(payload, json.dumps(report))
        self.assertEqual(report['details']['links'][label], {'target': str(outside), 'status': 'recorded'})
        self.assertIn({'code': 'symlink-skipped', 'path': label}, report['coverage']['issues'])
        self.source.write_text(json.dumps(report))
        output = self.base / 'ancestor-import.json'
        result = self.cli('import-host-report', '--report', self.source, '--output', output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bundle = json.loads(output.read_text())
        self.assertEqual(bundle['baseline']['original_observed_roots'], [str(self.source)])
        raw = bundle['baseline']['observations'][0]['value']
        key, proposal = next((k, p) for k, p in raw['details']['followups'].items() if p['kind'] == 'linked-path' and p['path'] == label)
        self.assertEqual(proposal['target'], str(outside))
        self.assertEqual(proposal['action'], 'request-explicit-scope')
        self.assertIn('note:hostscope' + key + ':0', {f['id'] for f in bundle['candidate']['fields']})
        self.assertTrue(all(f['decision'] is None for f in bundle['candidate']['fields']))
        self.assertFalse(bundle['candidate']['apply_supported'])
        self.assertFalse(raw['context']['execution_authorized'])

    def test_shallow_system_ancestor_is_raw_evidence_not_a_local_grant(self):
        # Pure data only: '/' and all embedded paths below are never collected
        # or opened. The synthetic report already declares system_root '/'.
        report = host_report()
        report['coverage'].update(complete=False, issues=[{'code': 'symlink-skipped', 'path': '/var'}])
        report['details'] = {
            'version': 1,
            'repositories': {r['path']: {'head': r['path'] + '/.git/HEAD',
                'config': r['path'] + '/.git/config', 'ref': r['path'] + '/.git/' + r['ref']}
                for r in report['repositories']},
            'isaacsim': {r['path']: {'version': r['path'] + '/VERSION'} for r in report['isaacsim']},
            'environments': {},
            'system_packages': {'status_source': '/var/lib/dpkg/status',
                'manual_source': '/var/lib/apt/extended_states',
                'status': {'cmake:amd64': 'install ok installed'}},
            'links': {'/var': {'target': '/unselected', 'status': 'recorded'}},
            'followups': {}, 'package_groups': {},
        }
        report['details']['followups'] = discovery._host.followups(report)
        report['details']['package_groups'] = discovery._host.package_groups(report['packages'])
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        discovery.build_review(baseline, candidate)
        self.assertEqual(baseline['original_observed_roots'], [str(self.source)])
        self.assertEqual(baseline['observations'][0]['value']['details']['links'], report['details']['links'])
        proposal = next(p for p in report['details']['followups'].values() if p['kind'] == 'linked-path')
        self.assertEqual(proposal, {'kind': 'linked-path', 'path': '/var', 'target': '/unselected',
            'records': ['link-target-scope'], 'action': 'request-explicit-scope'})
        self.assertFalse(candidate['apply_supported'])
        self.assertTrue(all(f['decision'] is None for f in candidate['fields']))
        with self.assertRaises(ValueError): discovery._path('/var')
        with self.assertRaises(ValueError): discovery._field_value('workspace:host.root', '/var')
        with self.assertRaises(ValueError): discovery._host.baseline(report, '/var', discovery)
        # Recompute derived maps so these data-only negatives fail scope binding,
        # not missing issue/followup identities or the old shallow-path grammar.
        for label in ('/home', '/unselected'):
            with self.subTest(outside_scope=label):
                bad = deepcopy(report)
                bad['details']['links'] = {label: {'target': '/unselected', 'status': 'recorded'}}
                bad['coverage']['issues'] = [{'code': 'symlink-skipped', 'path': label}]
                bad['details']['followups'] = discovery._host.followups(bad)
                bad['details']['package_groups'] = discovery._host.package_groups(bad['packages'])
                discovery._host.path(label)
                with self.assertRaises(ValueError): discovery._host.validate_report(bad)
        discovery._host.path('/', root=True)
        for label in ('/', '/var/', '//var', '/var/../etc', '/var\n', '/token=private'):
            with self.subTest(unsafe_label=label):
                with self.assertRaises(ValueError): discovery._host.path(label)

    def test_selected_sources_and_dpkg_status_survive_import_and_bind_to_records(self):
        spec = importlib.util.spec_from_file_location('source_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        def put(path, text):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        repo = home / 'Documents/GitHub/BoredEngineer/IsaacLab'
        put(repo / '.git/HEAD', 'ref: refs/heads/main\n')
        put(repo / '.git/refs/heads/main', 'a'*40)
        put(repo / '.git/config', '[remote "origin"]\nurl=https://github.com/example/IsaacLab.git\n')
        put(home / 'IsaacSim/VERSION', '5.1.0')
        put(system / 'etc/os-release', 'ID=fixture\n')
        put(system / 'var/lib/dpkg/status', 'Package: cmake\nArchitecture: amd64\nVersion: 1.0\nStatus: hold ok installed\n\n')
        put(system / 'var/lib/apt/extended_states', 'Package: cmake\nArchitecture: amd64\nAuto-Installed: 0\n\n')
        conda = home / 'miniconda3/envs/robot'
        put(conda / 'conda-meta/python.json', '{"name":"python","version":"3.11.1"}')
        venv = repo / '.venv'
        put(venv / 'pyvenv.cfg', 'version = 3.11.1\n')
        metadata = venv / 'lib/python3.11/site-packages/sample.dist-info/METADATA'
        put(metadata, 'Name: sample\nVersion: 1.0\n\n')
        report = module.collect(str(home), str(system))
        self.assertIn('details', report, 'Selected per-fact evidence is missing')
        d = report['details']
        self.assertEqual(d['repositories'][str(repo)], {'head': str(repo / '.git/HEAD'), 'config': str(repo / '.git/config'), 'ref': str(repo / '.git/refs/heads/main')})
        self.assertEqual(d['isaacsim'][str(home / 'IsaacSim')], {'version': str(home / 'IsaacSim/VERSION')})
        self.assertEqual(d['environments'][str(conda)]['packages']['python'], str(conda / 'conda-meta/python.json'))
        self.assertEqual(d['environments'][str(conda)]['python'], str(conda / 'conda-meta/python.json'))
        self.assertEqual(d['environments'][str(venv)], {'python': str(venv / 'pyvenv.cfg'), 'packages': {'sample': str(metadata)}})
        self.assertEqual(d['system_packages'], {'status_source': str(system / 'var/lib/dpkg/status'), 'manual_source': str(system / 'var/lib/apt/extended_states'), 'status': {'cmake:amd64': 'hold ok installed'}})
        self.assertTrue({'unsupported-package-managers', 'driver-cuda-level-not-collected'} <= {i['code'] for i in report['coverage']['issues']})
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        discovery.build_review(baseline, candidate)
        self.assertEqual(baseline['original_observed_roots'], [str(self.source)])
        report['environments'].reverse()
        self.assertEqual(discovery._host.baseline(report, str(self.source), discovery)['observations'], baseline['observations'])
        mutations = [
            lambda r: r['details']['repositories'][str(repo)].update(head=str(home / 'arbitrary')),
            lambda r: r['details']['repositories'][str(repo)].update(ref=str(repo / '.git/refs/heads/other')),
            lambda r: r['details']['environments'][str(conda)]['packages'].update(python=str(home / 'other.json')),
            lambda r: r['details']['environments'][str(venv)]['packages'].update(sample=str(venv / 'secrets/METADATA')),
            lambda r: r['details']['system_packages'].update(status_source='/etc/shadow'),
            lambda r: r['details']['system_packages']['status'].update({'cmake:amd64': 'deinstall ok config-files'}),
            lambda r: r['details']['isaacsim'][str(home / 'IsaacSim')].update(version=str(home / 'OTHER')),
            lambda r: r['machine']['os_id'].update(source=str(home / 'etc/os-release')),
        ]
        for mutate in mutations:
            bad = deepcopy(report); mutate(bad)
            with self.assertRaises(ValueError):
                discovery._host.validate_report(bad)

    def test_collector_schema_caps_keep_large_fixture_importable(self):
        spec = importlib.util.spec_from_file_location('bounded_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        for i in range(33):
            meta = home / ('miniconda3/envs/env%02d/conda-meta' % i)
            meta.mkdir(parents=True)
            (meta / 'python.json').write_text('{"name":"python","version":"3.11.1"}')
        for i in range(129):
            git = home / ('Documents/GitHub/BoredEngineer/repo%03d/.git' % i)
            git.mkdir(parents=True)
            (git / 'HEAD').write_text('a'*40)
            (git / 'config').write_text('[remote "origin"]\nurl=https://github.com/example/IsaacLab.git\n')
        report = module.collect(str(home), str(system))
        self.assertEqual(len(report['environments']), 32)
        self.assertEqual(len(report['repositories']), 128)
        self.assertTrue({'environment-limit', 'repository-limit'} <= {i['code'] for i in report['coverage']['issues']})
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        discovery.build_review(baseline, discovery.propose(baseline))

    def test_collector_printable_paths_import_without_becoming_desired_paths(self):
        spec = importlib.util.spec_from_file_location('punctuation_collector', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        home = self.base / 'home+é (fixture)'; system = self.base / 'system'
        home.mkdir(); system.mkdir()
        parent = home / 'Documents/GitHub'
        repo = parent / 'BoredEngineer/IsaacLab+local'
        (repo / '.git').mkdir(parents=True)
        (repo / '.git/HEAD').write_text('a' * 40 + '\n')
        (repo / '.git/config').write_text('[remote "origin"]\nurl=https://github.com/example/IsaacLab.git\n')
        (parent / 'old@backup').symlink_to(self.base / 'never-read')
        report = module.collect(str(home), str(system))
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        discovery.build_review(baseline, candidate)
        self.assertEqual(report['repositories'][0]['path'], str(repo))
        self.assertIn({'code': 'symlink-skipped', 'path': str(parent / 'old@backup')}, report['coverage']['issues'])
        self.assertIsNone(next(f for f in candidate['fields'] if f['id'] == 'workspace:host.root')['value'])
        self.source.write_text(json.dumps(report))
        result = self.cli('import-host-report', '--report', self.source, '--output', self.base / 'punctuation.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_collector_epoch_versions_and_private_env_name_are_importable_evidence(self):
        collector_spec = importlib.util.spec_from_file_location('collected_epoch', ROOT / 'isaac-installer/tools/collect_host_metadata.py')
        assert collector_spec is not None and collector_spec.loader is not None
        collector = importlib.util.module_from_spec(collector_spec)
        collector_spec.loader.exec_module(collector)
        home = self.base / 'fixture-home'; system = self.base / 'fixture-system'
        home.mkdir(); system.mkdir()
        metadata = home / 'miniconda3/envs/_robot/conda-meta'
        metadata.mkdir(parents=True)
        (metadata / 'custom.json').write_text('{"name":"custom","version":"1!2.0"}')
        report = collector.collect(str(home), str(system))
        baseline = discovery._host.baseline(report, str(self.source), discovery)
        candidate = discovery.propose(baseline)
        discovery.build_review(baseline, candidate)
        self.assertEqual(report['environments'][0]['packages'][0]['version'], '1!2.0')
        environment = next(f for f in candidate['fields'] if f['id'].startswith('environment:'))
        self.assertIsNone(environment['value'], 'Unsupported desired env name must remain explicitly unresolved')


if __name__ == '__main__':
    unittest.main()
