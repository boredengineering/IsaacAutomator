"""End-to-end desired-profile CLI tests using disposable inputs only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'isaac-installer/bin/isaac-installer'


class ProfileWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='isaac-profile-workflow-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o755)
        self.profile = self.base / 'desired.yaml'
        self.profile.write_text('''schema_version: v1alpha1
kind: workstation-profile
name: selected-workspace
target: offline
defaults: false
draft: false
workspace:
  root: ~/Documents/GitHub
  layout: named
  name: Robotics Team
components: {}
runtimes: {}
''')

    def run_cli(self, *args):
        identity = dict(user=65534, group=65534, extra_groups=()) if os.geteuid() == 0 else {}
        return subprocess.run(['/bin/bash', str(BIN), *args],
                              cwd=self.base, env={'PATH': '/usr/bin:/bin', 'HOME': str(self.base)},
                              capture_output=True, text=True, timeout=20, **identity)

    def test_desired_profile_reaches_concrete_plan_without_target_reads_or_writes(self):
        result = self.run_cli('install', '--dry-run', '--desired-profile', str(self.profile),
                              '--target-home', '/home/fixture-robot', '--json')
        self.assertIn(result.returncode, (0, 2), result.stderr)
        self.assertTrue(result.stdout.startswith('{'), result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['kind'], 'installer-action-plan')
        self.assertFalse(plan['execution_authorized'])
        self.assertTrue(any(row['target'] == '/home/fixture-robot/Documents/GitHub/Robotics Team'
                            for row in plan['actions']))
        self.assertFalse((self.base / '.isaac-installer').exists())

    def test_explicit_readonly_diagnostics_use_same_plan(self):
        for command in ('status', 'audit'):
            result = self.run_cli(command, '--desired-profile', str(self.profile),
                                  '--target-home', '/home/fixture-robot', '--json')
            self.assertIn(result.returncode, (0, 2), result.stderr)
            self.assertTrue(result.stdout.startswith('{'), result.stderr)
            self.assertEqual(json.loads(result.stdout)['kind'], 'installer-action-plan')
            self.assertNotIn('successfully installed', result.stdout)

    def test_unknown_or_mutating_options_refuse_without_profile_content(self):
        for extra in (['--apply'], ['--auto-reboot'], ['--target-home', '/'], ['--execute']):
            result = self.run_cli('plan-profile', '--desired-profile', '/DO_NOT_READ',
                                  '--target-home', '/home/fixture-robot', *extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('/DO_NOT_READ', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_malformed_or_sensitive_evidence_refuses_without_disclosure(self):
        evidence = self.base / 'evidence.json'
        target = str(self.base / 'robotics/BoredEngineer')
        for value in ('{"state":"missing","password":"SYNTHETIC_PRIVATE_CANARY"}',
                      '["SYNTHETIC_PRIVATE_CANARY"]',
                      '{"state":"missing","mtime":1e999}',
                      '{"state":"missing","mtime":-1e999}'):
            evidence.write_text('{' + json.dumps(target) + ':' + value + '}')
            result = self.run_cli('plan-profile', '--desired-profile', str(self.profile),
                              '--target-home', '/fixture/robot', '--evidence', str(evidence))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_public_preset_inheritance_is_resolved_before_planning(self):
        self.profile.write_text('schema_version: v1alpha1\nkind: workstation-profile\nname: inherited\n'
                                'target: offline\nextends: minimal\n')
        result = self.run_cli('plan-profile', '--desired-profile', str(self.profile),
                              '--target-home', '/home/fixture-robot')
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        actions = {row['id']: row for row in report['actions']}
        self.assertIn('component.sim', actions)
        self.assertIn('component.lab', actions)
        self.assertNotEqual(actions['component.sim']['status'], 'excluded')
        self.assertNotEqual(actions['component.lab']['status'], 'excluded')

    def test_migration_preview_compares_profiles_without_moving_checkout(self):
        old_profile = self.base / 'old.yaml'
        old_profile.write_text(self.profile.read_text().replace('Robotics Team', 'OldWorkspace'))
        repositories = self.base / 'repositories.json'
        repositories.write_text(json.dumps([{'name': 'IsaacLab', 'slug': 'isaac-sim/IsaacLab'}]))
        result = self.run_cli('migration-profile', '--old-profile', str(old_profile),
                              '--desired-profile', str(self.profile), '--repositories', str(repositories),
                              '--target-home', '/fixture/home')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['apply_supported'])
        row = report['repositories'][0]
        self.assertEqual(row['old_destination'], '/fixture/home/Documents/GitHub/OldWorkspace/IsaacLab')
        self.assertEqual(row['new_destination'], '/fixture/home/Documents/GitHub/Robotics Team/IsaacLab')
        self.assertEqual(row['path_change'], 'different_destination')
        self.assertTrue(report['read_only'])
        reports = self.base / 'reports'
        reports.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(reports, 65534, 65534)
        destination = reports / 'migration.json'
        saved = self.run_cli('migration-profile', '--old-profile', str(old_profile),
                             '--desired-profile', str(self.profile), '--repositories', str(repositories),
                             '--target-home', '/fixture/home', '--output', str(destination))
        self.assertEqual(saved.returncode, 0, saved.stderr + saved.stdout)
        self.assertEqual(json.loads(destination.read_text()), report)

    def test_explicit_target_metadata_bridges_into_conflict_plan(self):
        private = self.base / 'unselected-canary'
        private.write_text('SYNTHETIC_PRIVATE_CONTENT')
        observed = self.run_cli('observe-targets', '--desired-profile', str(self.profile),
                                '--target-home', str(self.base))
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertNotIn('SYNTHETIC_PRIVATE_CONTENT', observed.stdout)
        self.assertNotIn('unselected-canary', observed.stdout)
        evidence = json.loads(observed.stdout)
        target = str(self.base / 'Documents/GitHub/Robotics Team')
        self.assertEqual(evidence[target]['state'], 'missing')
        self.assertFalse(evidence[target]['managed'])
        observed_file = self.base / 'target-evidence.json'
        observed_file.write_text(observed.stdout)
        planned = self.run_cli('plan-profile', '--desired-profile', str(self.profile),
                               '--target-home', str(self.base), '--evidence', str(observed_file))
        self.assertIn(planned.returncode, (0, 2), planned.stderr)
        actions = json.loads(planned.stdout)['actions']
        self.assertEqual(next(action for action in actions if action['target'] == target)['status'], 'would_change')
        self.assertFalse(Path(target).exists())
        self.assertEqual(private.read_text(), 'SYNTHETIC_PRIVATE_CONTENT')

    def test_packer_adapter_is_available_through_confined_renderer(self):
        result = self.run_cli('render-profile', '--desired-profile', str(self.profile),
                              '--target-home', '/home/image-user', '--adapter', 'packer')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['adapter'], 'packer')
        self.assertFalse(report['execution_authorized'])
        self.assertFalse(report['apply_supported'])
        self.assertIn('/home/image-user/Documents/GitHub', result.stdout)

    def test_shared_yaml_renders_actual_legacy_workspace_fields(self):
        result = self.run_cli('render-profile', '--desired-profile', str(self.profile),
                              '--target-home', '/home/fixture-robot', '--adapter', 'local')
        self.assertIn(result.returncode, (0, 2), result.stderr)
        self.assertTrue(result.stdout.startswith('{'), result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['artifact']['workspace']['name'], 'Robotics Team')
        self.assertFalse(report['execution_authorized'])
        self.assertIn('coverage', report)


if __name__ == '__main__':
    unittest.main()
