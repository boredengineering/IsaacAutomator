#!/usr/bin/env python3
"""Real-entry runtime conflict regression; empty inventory and synthetic files only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.python import workstation_profile as shared


class ExportConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-export-conflict-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o755)

    def run_cli(self, *args):
        identity = 65534 if os.geteuid() == 0 else None
        return subprocess.run(
            ['/bin/bash', str(ROOT / 'isaac-installer/bin/isaac-installer'), *args],
            cwd=self.root, env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LANG': 'C.UTF-8'},
            capture_output=True, text=True, timeout=20, user=identity, group=identity,
            extra_groups=(27, 44, 1001) if identity is not None else None)

    def invoke(self, *args, code=0):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_empty_declare_export_resolve_render_collision_and_distinct_control(self):
        for duplicate in (True, False):
            with self.subTest(duplicate=duplicate):
                bundle = self.invoke('observe', '--empty')
                self.assertEqual(bundle['baseline']['observations'], [])
                decisions = [{'field_id': 'components.selection', 'decision': 'edit',
                              'value': ['gr00t', 'lerobot']}]
                runtimes = {}
                for component, manager in [('gr00t', 'uv'), ('lerobot', 'conda')]:
                    runtimes[component] = {'manager': manager, 'environment': 'same' if duplicate else component}
                    for field_id, value in [
                        ('component:' + component + '.source', {'mode': 'git',
                         'repository': 'https://github.com/example/' + component + '.git',
                         'ref': 'a' * 40, 'revision': 'a' * 40}),
                        ('component:' + component + '.execution', 'native'),
                        ('runtime:' + component, runtimes[component]),
                    ]:
                        decisions.append({'field_id': field_id, 'decision': 'declare', 'value': value})
                report = self.root / 'report.json'
                decision_file = self.root / 'decisions.json'
                report.write_text(json.dumps(bundle))
                decision_file.write_text(json.dumps(decisions))
                reviewed = self.invoke('review-profile', '--report', str(report),
                                       '--decisions', str(decision_file))
                report.write_text(json.dumps(reviewed))
                before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
                exported = self.invoke('export-profile', '--report', str(report), '--name', 'independent',
                                       code=2 if duplicate else 0)
                self.assertEqual(exported['complete'], not duplicate)
                self.assertEqual(exported['profile']['draft'], duplicate)
                self.assertEqual(exported['review']['intent_complete'], not duplicate)
                self.assertEqual(exported['review']['fields'], reviewed['candidate']['fields'])
                self.assertEqual(exported['profile']['runtimes'], runtimes)
                self.assertEqual(exported['review']['required_unresolved'], [
                    {'field_id': 'dependencies', 'reason': 'dependency_intent_unresolved', 'required': True}
                ] if duplicate else [])
                self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
                resolved = shared.resolve_document(exported['profile'])
                self.assertFalse(resolved['ready_for_apply'])
                self.assertEqual({'field': 'dependencies', 'reason': 'dependency_intent_unresolved'}
                                 in resolved['unresolved'], duplicate)
                desired = self.root / 'desired.yaml'
                desired.write_text(yaml.safe_dump(exported['profile']))
                render_args = ('render-profile', '--desired-profile', str(desired),
                               '--target-home', str(self.root / 'target'), '--adapter', 'local')
                if duplicate:
                    # The renderer independently refuses conflicting intent,
                    # including drafts; export must not conceal that conflict.
                    rendered = self.run_cli(*render_args)
                    self.assertEqual(rendered.returncode, 2)
                    self.assertEqual(rendered.stdout, '')
                    self.assertEqual(rendered.stderr, 'Profile workflow refused: invalid or unsupported input, '
                                     'or confinement unavailable. No application performed.\n')
                else:
                    rendered = self.invoke(*render_args)
                    self.assertTrue(rendered['render_supported'])
                    self.assertFalse(rendered['execution_authorized'])
                self.assertFalse((self.root / 'target').exists())
                self.assertFalse((self.root / '.isaac-installer').exists())


if __name__ == '__main__':
    unittest.main()
