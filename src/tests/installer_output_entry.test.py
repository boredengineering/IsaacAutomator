"""Real confined producer/writer integration against newly allocated fixtures."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / 'isaac-installer/bin/isaac-installer'


class OutputEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='isaac-output-entry-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o755)
        self.workspace = self.base / 'selected'
        self.output = self.base / 'reports'
        for path in (self.workspace, self.output):
            path.mkdir(mode=0o700)
            if os.geteuid() == 0:
                os.chown(path, 65534, 65534)

    def run_cli(self, *args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, root=False, direct=False):
        def identity():
            if os.geteuid() == 0:
                os.setgroups([1001, 1002])
                os.setgid(65534)
                os.setuid(65534)
        script = direct if isinstance(direct, str) else 'profile_output.py'
        command = (['/usr/bin/python3', '-I', '-B', str(ENTRY.parent.parent / 'lib/core' / script)]
                   if direct else ['/bin/bash', str(ENTRY)])
        return subprocess.run([*command, *args], cwd=self.base,
                              env={'PATH': '/usr/bin:/bin', 'HOME': str(self.base)},
                              preexec_fn=None if root else identity, stdout=stdout, stderr=stderr,
                              text=True, timeout=20)

    def test_inherited_regular_receipt_streams_refuse_without_writes(self):
        canary = self.workspace / 'canary'
        original = b'SYNTHETIC_ORIGINAL_BYTES_ONLY\n'
        for direct in (False, True):
            for stream in ('stdout', 'stderr'):
                for command in ('observe', 'install'):
                    with self.subTest(direct=direct, stream=stream, command=command):
                        canary.write_bytes(original)
                        destination = self.output / f'{direct}-{stream}-{command}.json'
                        args = ([command, '--workspace-root', str(self.workspace), '--workspace-name', 'Synthetic']
                                if command == 'observe' else [command])
                        fd = os.open(canary, os.O_WRONLY)  # Deliberately no O_TRUNC.
                        try:
                            result = self.run_cli(*args, '--output', str(destination),
                                                  direct=direct,
                                                  stdout=fd if stream == 'stdout' else subprocess.PIPE,
                                                  stderr=fd if stream == 'stderr' else subprocess.PIPE)
                        finally:
                            os.close(fd)
                        self.assertEqual(canary.read_bytes(), original)
                        self.assertEqual(result.returncode, 2)
                        self.assertFalse(destination.exists())

    @unittest.skipUnless(os.geteuid() == 0, 'requires root parent for refusal probe')
    def test_root_entry_diagnostic_preserves_inherited_regular_stderr(self):
        canary = self.workspace / 'root-canary'
        original = b'SYNTHETIC_ROOT_DIAGNOSTIC_CANARY\n'
        for output in (False, True):
            with self.subTest(output=output):
                canary.write_bytes(original)
                destination = self.output / 'root-output.json'
                args = ['observe', '--empty'] + (['--output', str(destination)] if output else [])
                fd = os.open(canary, os.O_WRONLY)
                try:
                    result = self.run_cli(*args, root=True, stderr=fd)
                finally:
                    os.close(fd)
                self.assertEqual(canary.read_bytes(), original)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(destination.exists())

    def test_sibling_entries_admit_receipts_before_root_or_parser_diagnostics(self):
        canary = self.workspace / 'sibling-canary'
        original = b'SYNTHETIC_SIBLING_CANARY\n'
        entries = [('discovery_cli.py', ['observe', '--invalid-option']),
                   ('profile_workflow.py', ['plan-profile', '--invalid-option']),
                   ('safe_preview.py', ['--invalid-option']),
                   (False, ['observe', '--invalid-option']),
                   (False, ['plan-profile', '--desired-profile']),
                   (False, ['--invalid-option'])]
        for direct, args in entries:
            for root in ((False, True) if os.geteuid() == 0 else (False,)):
                for stream in ('stdout', 'stderr'):
                    with self.subTest(direct=direct, args=args, root=root, stream=stream):
                        canary.write_bytes(original)
                        fd = os.open(canary, os.O_WRONLY)
                        try:
                            result = self.run_cli(*args, direct=direct, root=root,
                                                  stdout=fd if stream == 'stdout' else subprocess.PIPE,
                                                  stderr=fd if stream == 'stderr' else subprocess.PIPE)
                        finally:
                            os.close(fd)
                        self.assertEqual(canary.read_bytes(), original)
                        self.assertEqual(result.returncode, 2)
                        self.assertEqual(result.stdout if stream == 'stderr' else result.stderr, '')
            # Valid capture pipes still carry ordinary parser/root diagnostics.
            normal = self.run_cli(*args, direct=direct)
            self.assertNotEqual(normal.returncode, 0)
            self.assertTrue(normal.stderr)

    def test_selected_new_output_is_private_and_collision_does_not_overwrite(self):
        destination = self.output / 'observed.json'
        args = ('observe', '--workspace-root', str(self.workspace), '--workspace-name', 'BoredEngineer',
                '--output', str(destination))
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['status'], 'written')
        before = destination.read_bytes()
        self.assertEqual(json.loads(before)['baseline']['observations'][0]['value']['name'], 'BoredEngineer')
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        again = self.run_cli(*args)
        self.assertEqual(again.returncode, 2)
        self.assertEqual(destination.read_bytes(), before)

    def test_explicit_empty_intent_report_can_be_saved_without_target_reads(self):
        destination = self.output / 'empty.json'
        result = self.run_cli('observe', '--empty', '--output', str(destination))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(destination.read_text())['baseline']['observations'], [])
        self.assertEqual(list(self.workspace.iterdir()), [])
        contradictory = self.output / 'must-not-create.json'
        refused = self.run_cli('observe', '--empty', '--workspace-root', str(self.workspace),
                               '--workspace-name', 'Robotics', '--output', str(contradictory))
        self.assertEqual(refused.returncode, 2)
        self.assertFalse(contradictory.exists())

    def test_malformed_or_mixed_empty_observation_refuses_safely(self):
        cases = [[], ['--empty', '--workspace-root', ''],
                 ['--empty', '--workspace-name', 'Synthetic'],
                 ['--empty', '--git-source'], ['--empty', '--metadata-source']]
        for option in ('--git-source', '--metadata-source'):
            cases.extend(['--empty', option, value] for value in ('null', '[]', '1', '{}', '{', '"root"'))
        cases.append(['--empty', '--dist-info', str(self.workspace)])
        for index, args in enumerate(cases):
            with self.subTest(args=args):
                destination = self.output / f'empty-refused-{index}.json'
                result = self.run_cli('observe', *args, '--output', str(destination))
                self.assertEqual(result.returncode, 2)
                self.assertFalse(destination.exists())
                self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_incomplete_desired_yaml_is_saved_without_claiming_completion(self):
        report = self.output / 'observed.json'
        observed = self.run_cli('observe', '--workspace-root', str(self.workspace), '--workspace-name', 'Robotics',
                                '--output', str(report))
        self.assertEqual(observed.returncode, 0, observed.stderr)
        destination = self.output / 'desired.yaml'
        result = self.run_cli('export-profile', '--report', str(report), '--name', 'draft',
                              '--format', 'yaml', '--output', str(destination))
        self.assertEqual(result.returncode, 2, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['status'], 'written')
        self.assertEqual(receipt['producer_exit_code'], 2)
        self.assertFalse(receipt['execution_authorized'])
        self.assertIn('draft: true', destination.read_text())
        self.assertIn('defaults: false', destination.read_text())

    def test_export_preserves_original_exclusions_after_edit_reject_or_defer(self):
        def owned(path, text=None):
            if text is None:
                path.mkdir(mode=0o700)
            else:
                path.write_text(text)
                path.chmod(0o600)
            if os.geteuid() == 0:
                os.chown(path, 65534, 65534)
            return path

        checkout = owned(self.base / 'checkout')
        gitdir = owned(self.base / 'linked-gitdir')
        common = owned(self.base / 'linked-common')
        owned(checkout / '.git', f'gitdir: {gitdir}\n')
        owned(gitdir / 'commondir', f'{common}\n')
        owned(gitdir / 'HEAD', 'a' * 40 + '\n')
        owned(common / 'config', '[core]\n\trepositoryformatversion = 0\n')
        source = dict(id='synthetic', root=str(checkout), git_dir=str(gitdir),
                      common_dir=str(common), ref_paths=[])
        observed_path = self.output / 'original.json'
        observed = self.run_cli('observe', '--git-source', json.dumps(source),
                                '--workspace-root', str(self.workspace), '--workspace-name', 'Synthetic',
                                '--output', str(observed_path))
        self.assertEqual(observed.returncode, 0, observed.stderr)
        baseline = json.loads(observed_path.read_text())['baseline']
        repository = next(o for o in baseline['observations'] if o['id'] == 'repository:synthetic')
        self.assertEqual(repository['status'], 'observed')
        replacement = dict(repository['value'])
        for key in ('root', 'git_dir', 'common_dir'):
            replacement[key] = str(owned(self.base / ('replacement-' + key)))
        decisions = owned(self.output / 'edit.json', json.dumps([
            dict(field_id=repository['id'], decision='edit', value=replacement)]))
        edited_path = self.output / 'edited.json'
        edited = self.run_cli('review-profile', '--report', str(observed_path), '--decisions', str(decisions),
                             '--output', str(edited_path))
        self.assertEqual(edited.returncode, 0, edited.stderr)
        original_roots = sorted(map(str, (checkout, gitdir, common, self.workspace)))
        for decision in ('edit', 'reject', 'defer'):
            reviewed_path = edited_path
            if decision != 'edit':
                decisions = owned(self.output / f'{decision}.json', json.dumps([
                    dict(field_id=repository['id'], decision=decision)]))
                reviewed_path = self.output / f'{decision}-reviewed.json'
                reviewed = self.run_cli('review-profile', '--report', str(edited_path),
                                        '--decisions', str(decisions), '--output', str(reviewed_path))
                self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            self.assertEqual(json.loads(reviewed_path.read_text())['baseline'], baseline)
            for fmt in ('json', 'yaml'):
                for directory in (checkout, gitdir, common, self.workspace):
                    with self.subTest(decision=decision, format=fmt, root=directory.name):
                        destination = directory / f'{decision}-forbidden.{fmt}'
                        result = self.run_cli('export-profile', '--report', str(reviewed_path),
                                              '--name', 'synthetic', '--format', fmt,
                                              '--output', str(destination))
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertFalse(destination.exists(), result.stdout)
                        self.assertEqual(json.loads(result.stdout)['status'], 'refused')
            with self.subTest(decision=decision, contract='immutable original roots'):
                safe = self.output / f'{decision}-export.json'
                result = self.run_cli('export-profile', '--report', str(reviewed_path), '--name', 'synthetic',
                                      '--output', str(safe))
                self.assertEqual(json.loads(result.stdout)['status'], 'written')
                self.assertEqual(json.loads(safe.read_text())['review'].get('original_observed_roots'),
                                 original_roots)

    def test_target_observation_output_excludes_home_and_external_reported_targets(self):
        profile = self.base / 'target-desired.yaml'
        external = self.base / 'external-targets'
        external.mkdir(mode=0o755)
        external_target = external / 'Synthetic'
        external_target.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(external_target, 65534, 65534)
        for label, root, target in (('home', '~/Documents/GitHub', self.workspace / 'Documents/GitHub/Synthetic'),
                                     ('external', str(external), external_target)):
            profile.write_text('schema_version: v1alpha1\nkind: workstation-profile\nname: synthetic\n'
                               'target: offline\ndefaults: false\ndraft: false\nworkspace:\n'
                               f'  root: {json.dumps(root)}\n  layout: named\n  name: Synthetic\n'
                               'components: {}\nruntimes: {}\n')
            args = ('observe-targets', '--desired-profile', str(profile), '--target-home', str(self.workspace))
            with self.subTest(scope=label, output='outside'):
                destination = self.output / f'{label}-evidence.json'
                result = self.run_cli(*args, '--output', str(destination))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'written')
                self.assertFalse(json.loads(result.stdout)['execution_authorized'])
                evidence = json.loads(destination.read_text())
                self.assertIn(str(target), evidence)
                self.assertTrue(all(path.startswith('/') for path in evidence))
                planned = self.run_cli('plan-profile', '--desired-profile', str(profile),
                                       '--target-home', str(self.workspace), '--evidence', str(destination))
                self.assertIn(planned.returncode, (0, 2), planned.stderr)
                self.assertFalse(json.loads(planned.stdout)['execution_authorized'])
            forbidden = [self.workspace / f'{label}-forbidden.json']
            if label == 'external':
                forbidden.append(external_target / 'external-forbidden.json')
            for destination in forbidden:
                with self.subTest(scope=label, output=str(destination)):
                    result = self.run_cli(*args, '--output', str(destination))
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(destination.exists())
        external_target.rmdir()
        missing = self.output / 'missing-external-evidence.json'
        result = self.run_cli(*args, '--output', str(missing))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(missing.exists())

    def test_mutating_producer_is_not_admitted_by_output_wrapper(self):
        destination = self.output / 'must-not-create.json'
        result = self.run_cli('install', '--output', str(destination), '--config', '/DO_NOT_READ')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(destination.exists())
        self.assertNotIn('/DO_NOT_READ', result.stdout + result.stderr)

    def test_output_inside_selected_observation_root_refuses(self):
        destination = self.workspace / 'must-not-create.json'
        result = self.run_cli('observe', '--workspace-root', str(self.workspace), '--workspace-name', 'Robotics',
                              '--output', str(destination))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(destination.exists())
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
