#!/usr/bin/env python3
"""Discovery CLI contracts; only disposable synthetic inputs, never the host inventory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'isaac-installer/lib/core/discovery_cli.py'


class DiscoveryCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-discovery-cli-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o755)

    def run_cli(self, *args, entry=False):
        kwargs = {}
        if os.geteuid() == 0:
            kwargs.update(user=65534, group=65534, extra_groups=())
        command = (['/bin/bash', str(ROOT / 'isaac-installer/bin/isaac-installer')]
                   if entry else ['/usr/bin/python3', '-I', '-B', str(CLI)])
        return subprocess.run(
            [*command, *args],
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.directory)},
            cwd=self.directory, capture_output=True, text=True, timeout=15, **kwargs,
        )

    def test_observe_emits_non_executable_proposals_from_selected_metadata(self):
        workspace = self.directory / 'GitHub'
        (workspace / 'BoredEngineer' / 'IsaacLab' / '.git').mkdir(parents=True)
        metadata = self.directory / 'custom_tool-1.2.dist-info' / 'METADATA'
        metadata.parent.mkdir()
        metadata.write_text('Name: custom-tool\nVersion: 1.2\n')
        before = {str(p): p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}
        result = self.run_cli('observe', '--workspace-root', str(workspace),
                              '--workspace-name', 'BoredEngineer',
                              '--dist-info', str(metadata), '--environment', 'devcontainer')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['baseline']['kind'], 'workstation-baseline')
        self.assertFalse(output['candidate']['apply_supported'])
        self.assertIn('custom-tool', result.stdout)
        self.assertIn('BoredEngineer', result.stdout)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.directory.rglob('*') if p.is_file()})

    def test_review_and_rescan_preserve_explicit_decision(self):
        workspace = self.directory / 'workspace'
        workspace.mkdir()
        observed = self.run_cli('observe', '--workspace-root', str(workspace),
                                '--workspace-name', 'Original')
        self.assertEqual(observed.returncode, 0, observed.stderr)
        report = self.directory / 'report.json'
        report.write_text(observed.stdout)
        decisions = self.directory / 'decisions.json'
        decisions.write_text(json.dumps([{'field_id': 'workspace:workspace.name',
                                         'decision': 'edit', 'value': 'Chosen'}]))
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        candidate = json.loads(reviewed.stdout)['candidate']
        field = next(f for f in candidate['fields'] if f['id'] == 'workspace:workspace.name')
        self.assertEqual(field['value'], 'Chosen')
        self.assertEqual(field['state'], 'accepted')
        report.write_text(reviewed.stdout)
        rescanned = self.run_cli('observe', '--workspace-root', str(workspace),
                                 '--workspace-name', 'Original', '--previous-report', str(report))
        self.assertEqual(rescanned.returncode, 0, rescanned.stderr)
        field = next(f for f in json.loads(rescanned.stdout)['candidate']['fields']
                     if f['id'] == 'workspace:workspace.name')
        self.assertEqual(field['value'], 'Chosen')
        self.assertFalse((workspace / 'Chosen').exists())

    def test_custom_decisions_survive_package_argument_reordering(self):
        files = []
        for name in ('alpha', 'beta'):
            metadata = self.directory / (name + '-1.dist-info') / 'METADATA'
            metadata.parent.mkdir()
            metadata.write_text('Name: ' + name + '\nVersion: 1\n')
            files.append(str(metadata))
        observed = self.run_cli('observe', '--dist-info', files[0], '--dist-info', files[1])
        self.assertEqual(observed.returncode, 0, observed.stderr)
        bundle = json.loads(observed.stdout)
        field_id = next(f['id'] for f in bundle['candidate']['fields']
                        if f['id'].endswith(':alpha'))
        report = self.directory / 'packages.json'
        report.write_text(observed.stdout)
        decisions = self.directory / 'decisions.json'
        decisions.write_text(json.dumps([{'field_id': field_id, 'decision': 'reject'}]))
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        report.write_text(reviewed.stdout)
        rescanned = self.run_cli('observe', '--dist-info', files[1], '--dist-info', files[0],
                                 '--previous-report', str(report))
        self.assertEqual(rescanned.returncode, 0, rescanned.stderr)
        active_alpha = [f for f in json.loads(rescanned.stdout)['candidate']['fields']
                        if f['id'].endswith(':alpha') and not f['not_selected']]
        self.assertEqual(len(active_alpha), 1)
        self.assertEqual(active_alpha[0]['state'], 'rejected')

    def test_real_entrypoint_uses_confined_observer_not_legacy_modules(self):
        workspace = self.directory / 'workspace'
        workspace.mkdir()
        result = self.run_cli('observe', '--workspace-root', str(workspace),
                              '--workspace-name', 'Robotics', entry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['baseline']['kind'], 'workstation-baseline')
        self.assertFalse((self.directory / '.isaac-installer').exists())

    def test_invalid_report_inputs_are_bounded_and_sanitized(self):
        report = self.directory / 'report.json'
        decisions = self.directory / 'decisions.json'
        decisions.write_text('[]')
        for payload in ('{"baseline":{},"baseline":{"secret":"CANARY_PRIVATE"}}',
                        '{"kind":"workstation-profile","secret":"CANARY_PRIVATE"}',
                        'x' * 1048577, '[NaN]', '{'):
            report.write_text(payload)
            result = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions))
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('CANARY_PRIVATE', result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stderr)
        report.unlink()
        report.symlink_to(decisions)
        result = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions))
        self.assertEqual(result.returncode, 2)

    def test_root_refuses_before_reading_inputs(self):
        if os.geteuid() != 0:
            self.skipTest('root-specific refusal')
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(CLI), 'observe',
             '--workspace-root', '/does-not-exist', '--workspace-name', 'Example'],
            env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('root', result.stderr)
        self.assertNotIn('/does-not-exist', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_explicit_tool_metadata_flows_into_reviewable_proposals(self):
        metadata = self.directory / 'tools.json'
        metadata.write_text(json.dumps({'name': 'robot-project', 'manager': 'uv', 'python': '3.12',
                                       'tools': [{'name': 'custom-tool', 'version': '1.2',
                                                  'source': None, 'purpose': 'robot workflow'}],
                                       'notes': []}))
        source = {'id': 'robot-tools', 'path': str(metadata), 'format': 'environment-json',
                  'environment': 'robot-project', 'placement': 'container'}
        result = self.run_cli('observe', '--metadata-source', json.dumps(source), entry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = json.loads(result.stdout)
        self.assertIn('custom-tool', result.stdout)
        fields = bundle['candidate']['fields']
        self.assertTrue(any(f['id'].startswith('tool:') for f in fields))
        self.assertTrue(all(f['state'] != 'accepted' for f in fields))
        self.assertFalse(bundle['candidate']['apply_supported'])

    def test_explicit_git_metadata_uses_exact_file_admission(self):
        repo = self.directory / 'checkout'
        git = repo / '.git'
        (git / 'refs/heads').mkdir(parents=True)
        (git / 'HEAD').write_text('ref: refs/heads/main\n')
        (git / 'refs/heads/main').write_text('a' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/IsaacLab.git\n')
        (repo / 'private-not-read.txt').write_text('SYNTHETIC_PRIVATE_CHECKOUT')
        selected = {'id': 'selected-lab', 'root': str(repo), 'git_dir': str(git),
                    'common_dir': str(git), 'ref_paths': ['refs/heads/main']}
        result = self.run_cli('observe', '--git-source', json.dumps(selected), entry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('SYNTHETIC_PRIVATE_CHECKOUT', result.stdout + result.stderr)
        self.assertIn('a' * 40, result.stdout)
        self.assertTrue(any(f['id'].startswith('repository:')
                            for f in json.loads(result.stdout)['candidate']['fields']))

    def test_selected_entry_budget_truncates_explicitly_and_report_is_reviewable(self):
        workspace = self.directory / 'conda-meta'
        workspace.mkdir()
        for name in ('One', 'Two', 'Three'):
            (workspace / (name + '.json')).write_text(json.dumps({'name': name, 'version': '1.0'}))
        result = self.run_cli('observe', '--conda-meta', str(workspace),
                              '--max-entries', '1', entry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = json.loads(result.stdout)
        self.assertTrue(bundle['baseline']['incomplete'])
        self.assertEqual(bundle['baseline']['limits']['max_entries'], 1)
        report = self.directory / 'bounded-report.json'
        decisions = self.directory / 'bounded-decisions.json'
        report.write_text(result.stdout)
        decisions.write_text('[]')
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions), entry=True)
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)

    def test_report_reader_and_encoder_share_eight_mebibyte_budget(self):
        import runpy
        module = runpy.run_path(str(ROOT / 'isaac-installer/lib/core/discovery_cli.py'))
        document = {'padding': 'x' * 1100000}
        selected = self.directory / 'large-input.json'
        selected.write_text(json.dumps(document))
        self.assertEqual(module['_read_json'](str(selected)), document)
        with self.assertRaises(ValueError):
            module['_dump_json']({'padding': 'x' * 8388608})

    def test_large_bounded_report_roundtrips_without_silent_loss(self):
        metadata = self.directory / 'conda-meta'
        metadata.mkdir()
        for index in range(768):
            name = 'package-' + 'x' * 70 + str(index)
            (metadata / (name + '.json')).write_text(json.dumps({'name': name, 'version': '1.0'}))
        observed = self.run_cli('observe', '--conda-meta', str(metadata), '--max-entries', '1024',
                                '--max-bytes', '262144', '--max-seconds', '10', entry=True)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertGreater(len(observed.stdout.encode()), 1048576, observed.stdout[:3000])
        report = self.directory / 'large-report.json'
        decisions = self.directory / 'large-decisions.json'
        report.write_text(observed.stdout)
        decisions.write_text('[]')
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions), entry=True)
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        self.assertEqual(len(json.loads(reviewed.stdout)['candidate']['fields']),
                         len(json.loads(observed.stdout)['candidate']['fields']))

    def test_explicit_runtime_metadata_remains_reviewable_not_enabled(self):
        metadata = self.directory / 'environment.json'
        metadata.write_text(json.dumps({'name': 'lab-env', 'manager': 'conda', 'python': '3.12',
                                       'tools': [], 'notes': []}))
        source = {'id': 'lab-runtime', 'path': str(metadata), 'format': 'environment-json',
                  'environment': 'lab-env', 'placement': 'environment', 'runtime': 'lab'}
        result = self.run_cli('observe', '--metadata-source', json.dumps(source), entry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = {f['id']: f for f in json.loads(result.stdout)['candidate']['fields']}
        self.assertEqual(fields['runtime:lab']['value']['environment'], 'lab-env')
        self.assertEqual(fields['runtime:lab']['state'], 'proposed')
        self.assertEqual(fields['components.selection']['state'], 'unresolved')

    def test_reviewed_desired_yaml_reaches_both_consumers_and_concrete_plan(self):
        workspace = self.directory / 'pipeline-workspace'
        workspace.mkdir()
        observed = self.run_cli('observe', '--workspace-root', str(workspace), '--workspace-name', 'BoredEngineer', entry=True)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        bundle = json.loads(observed.stdout)
        report = self.directory / 'pipeline-observed.json'
        report.write_text(observed.stdout)
        choices = []
        for field in bundle['candidate']['fields']:
            if field['id'].startswith('workspace:'):
                choices.append({'field_id': field['id'], 'decision': 'accept'})
            elif field['id'] == 'components.selection':
                choices.append({'field_id': field['id'], 'decision': 'edit', 'value': []})
        decisions = self.directory / 'pipeline-decisions.json'
        decisions.write_text(json.dumps(choices))
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions), entry=True)
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        report.write_text(reviewed.stdout)
        exported = self.run_cli('export-profile', '--report', str(report), '--name', 'pipeline', '--format', 'yaml', entry=True)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        desired = self.directory / 'pipeline-desired.yaml'
        desired.write_text(exported.stdout)
        for adapter in ('local', 'ansible'):
            rendered = self.run_cli('render-profile', '--desired-profile', str(desired),
                                    '--target-home', '/fixture/robot', '--adapter', adapter, entry=True)
            self.assertIn(rendered.returncode, (0, 2), rendered.stderr)
            self.assertIn('BoredEngineer', rendered.stdout)
            self.assertIn('artifact', json.loads(rendered.stdout))
        planned = self.run_cli('install', '--dry-run', '--desired-profile', str(desired),
                              '--target-home', '/fixture/robot', '--json', entry=True)
        self.assertEqual(planned.returncode, 2, planned.stderr)
        self.assertFalse(json.loads(planned.stdout)['execution_authorized'])
        self.assertIn(str(workspace / 'BoredEngineer'), planned.stdout)
        self.assertEqual(list(workspace.iterdir()), [])

    def test_nonempty_reviewed_robotics_selection_reaches_local_consumer(self):
        repo = self.directory / 'LeRobot'
        git = repo / '.git'
        git.mkdir(parents=True)
        (git / 'HEAD').write_text('a' * 40 + '\n')
        (git / 'config').write_text('[remote "origin"]\nurl = https://github.com/example/lerobot.git\n')
        metadata = self.directory / 'environment.json'
        metadata.write_text(json.dumps({'name': 'lerobot', 'manager': 'conda', 'python': None,
                                       'tools': [], 'notes': []}))
        source = {'id': 'robot-repo', 'root': str(repo), 'git_dir': str(git), 'common_dir': str(git),
                  'ref_paths': [], 'component': 'lerobot'}
        environment = {'id': 'robot-env', 'path': str(metadata), 'format': 'environment-json',
                       'environment': 'lerobot', 'placement': 'environment', 'runtime': 'lerobot'}
        observed = self.run_cli('observe', '--git-source', json.dumps(source),
                                '--metadata-source', json.dumps(environment), entry=True)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        report = self.directory / 'robot-report.json'
        decisions = self.directory / 'robot-decisions.json'
        report.write_text(observed.stdout)
        decisions.write_text(json.dumps([
            {'field_id': 'components.selection', 'decision': 'edit', 'value': ['lerobot']},
            {'field_id': 'component:lerobot.source', 'decision': 'accept'},
            {'field_id': 'runtime:lerobot', 'decision': 'accept'},
            {'field_id': 'environment:robot-env', 'decision': 'accept'}]))
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions), entry=True)
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        report.write_text(reviewed.stdout)
        exported = self.run_cli('export-profile', '--report', str(report), '--name', 'robot-fixture',
                                '--format', 'yaml', entry=True)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        desired = self.directory / 'robot-desired.yaml'
        desired.write_text(exported.stdout)
        rendered = self.run_cli('render-profile', '--desired-profile', str(desired),
                                '--target-home', '/fixture/robot', '--adapter', 'local', entry=True)
        self.assertEqual(rendered.returncode, 0, rendered.stderr + rendered.stdout)
        artifact = json.loads(rendered.stdout)['artifact']
        self.assertTrue(artifact['repositories']['lerobot']['enabled'])
        self.assertEqual(artifact['repositories']['lerobot']['repo'], 'https://github.com/example/lerobot.git')
        self.assertEqual(artifact['repositories']['lerobot']['tag'], 'a' * 40)
        self.assertFalse(artifact['simulation']['isaacsim']['enabled'])
        planned = self.run_cli('plan-profile', '--desired-profile', str(desired),
                               '--target-home', '/fixture/robot', entry=True)
        self.assertEqual(planned.returncode, 2, planned.stderr)
        self.assertIn('component.lerobot', planned.stdout)
        self.assertEqual((git / 'HEAD').read_text(), 'a' * 40 + '\n')

    def test_explicit_declarations_complete_missing_sim_and_lab_intent(self):
        observed = self.run_cli('observe', '--empty', entry=True)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        report = self.directory / 'declared.json'
        report.write_text(observed.stdout)
        decisions = self.directory / 'declarations.json'
        decisions.write_text(json.dumps([
            {'field_id': 'components.selection', 'decision': 'edit', 'value': ['sim', 'lab']},
            {'field_id': 'component:sim.source', 'decision': 'declare',
             'value': {'mode': 'standalone', 'version': '6.0.1', 'sha256': None}},
            {'field_id': 'runtime:kit', 'decision': 'declare', 'value': {'manager': 'bundled', 'environment': 'kit'}},
            {'field_id': 'component:lab.source', 'decision': 'declare',
             'value': {'mode': 'git', 'repository': 'https://github.com/example/IsaacLab.git',
                       'ref': 'fixture', 'revision': 'a' * 40}},
            {'field_id': 'runtime:lab', 'decision': 'declare', 'value': {'manager': 'conda', 'environment': 'isaaclab'}},
            {'field_id': 'component:lab.execution', 'decision': 'declare', 'value': 'native'}]))
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions), entry=True)
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        report.write_text(reviewed.stdout)
        declared = self.run_cli('review-profile', '--report', str(report),
                                '--field-id', 'component:sim.execution', '--decision', 'declare',
                                '--value-json', '"native"', entry=True)
        self.assertEqual(declared.returncode, 0, declared.stderr)
        report.write_text(declared.stdout)
        exported = self.run_cli('export-profile', '--report', str(report), '--name', 'explicit-intent', entry=True)
        self.assertEqual(exported.returncode, 0, exported.stderr + exported.stdout)
        bundle = json.loads(exported.stdout)
        self.assertTrue(bundle['complete'])
        self.assertTrue(bundle['profile']['components']['sim']['enabled'])
        self.assertTrue(bundle['profile']['components']['lab']['enabled'])
        self.assertEqual(bundle['review']['observation_coverage'], [])
        source = next(f for f in bundle['review']['fields'] if f['id'] == 'component:sim.source')
        self.assertEqual(source['rationale'], 'user_declared_intent')
        self.assertEqual(source['evidence'], [])

    def test_reviewed_workspace_exports_desired_yaml_through_real_entry(self):
        workspace = self.directory / 'export-workspace'
        workspace.mkdir()
        observed = self.run_cli('observe', '--workspace-root', str(workspace),
                                '--workspace-name', 'Robotics Team')
        self.assertEqual(observed.returncode, 0, observed.stderr)
        bundle = json.loads(observed.stdout)
        report = self.directory / 'export-report.json'
        report.write_text(observed.stdout)
        decisions = self.directory / 'export-decisions.json'
        decisions.write_text(json.dumps([
            {'field_id': field['id'], 'decision': 'accept'}
            for field in bundle['candidate']['fields'] if field['id'].startswith('workspace:')
        ]))
        reviewed = self.run_cli('review-profile', '--report', str(report), '--decisions', str(decisions))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        report.write_text(reviewed.stdout)
        exported = self.run_cli('export-profile', '--report', str(report), '--name', 'reviewed-fixture',
                                '--format', 'yaml', entry=True)
        self.assertIn(exported.returncode, (0, 2), exported.stderr)
        import yaml
        profile = yaml.safe_load(exported.stdout)
        self.assertIsInstance(profile, dict, exported.stderr)
        self.assertEqual(profile['kind'], 'workstation-profile')
        self.assertEqual(profile['workspace']['name'], 'Robotics Team')
        self.assertFalse((workspace / 'Robotics Team').exists())
        self.assertFalse((self.directory / '.isaac-installer').exists())


if __name__ == '__main__':
    unittest.main()
