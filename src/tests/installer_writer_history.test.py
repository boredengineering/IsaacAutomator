"""Historical exclusions: real unprivileged CLI, disposable synthetic roots only."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('writer_entry_controls', Path(__file__).with_name('installer_output_entry.test.py'))
assert spec is not None and spec.loader is not None
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class WriterHistoryTests(unittest.TestCase):
    workspace: Path
    output: Path
    base: Path
    setUp = entry.OutputEntryTests.setUp
    run_cli = entry.OutputEntryTests.run_cli

    def owned(self, path, content=None):
        if content is None:
            path.mkdir(mode=0o700)
        else:
            path.write_text(content)
            path.chmod(0o600)
        if os.geteuid() == 0:
            os.chown(path, 65534, 65534)
        return path

    def written(self, args, destination, code=0):
        result = self.run_cli(*map(str, args), '--output', str(destination))
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['status'], 'written', receipt)
        self.assertFalse(receipt['execution_authorized'])
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        return destination

    def refused(self, args, destination):
        result = self.run_cli(*map(str, args), '--output', str(destination))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(destination.exists(), result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'], 'refused')

    def seed(self):
        roots = [self.workspace] + [self.owned(self.base / name) for name in ('checkout', 'gitdir', 'common')]
        workspace, checkout, gitdir, common = roots
        self.owned(checkout / '.git', f'gitdir: {gitdir}\n')
        self.owned(gitdir / 'commondir', f'{common}\n')
        self.owned(gitdir / 'HEAD', 'c' * 40 + '\n')
        self.owned(common / 'config', '[core]\n\trepositoryformatversion = 0\n')
        for root in roots:
            self.owned(root / 'canary', 'SYNTHETIC_UNCHANGED\n')
        source = dict(id='history', root=str(checkout), git_dir=str(gitdir), common_dir=str(common), ref_paths=[])
        report = self.written(['observe', '--git-source', json.dumps(source), '--workspace-root', workspace,
                               '--workspace-name', 'Synthetic'], self.output / 'seed.json')
        return roots, report

    def test_history_union_across_empty_omission_decisions_and_repeated_continuation(self):
        roots, seed = self.seed()
        seed_baseline = json.loads(seed.read_text())['baseline']
        replacement = dict(next(o for o in seed_baseline['observations'] if o['id'] == 'repository:history')['value'])
        for key in ('root', 'git_dir', 'common_dir'):
            replacement[key] = str(self.owned(self.base / ('edited-' + key)))
        edited = self.written(['review-profile', '--report', seed, '--field-id', 'repository:history',
                               '--decision', 'edit', '--value-json', json.dumps(replacement)], self.output / 'edited.json')
        for state in ('edit', 'reject', 'defer'):
            prior = edited
            if state != 'edit':
                prior = self.written(['review-profile', '--report', edited, '--field-id', 'repository:history',
                                      '--decision', state], self.output / (state + '.json'))
            self.assertEqual(json.loads(prior.read_text())['baseline'], seed_baseline)
            for mode in ('empty', 'omission'):
                added = self.owned(self.base / (state + '-' + mode + '-new'))
                refresh = ['observe', '--previous-report', prior]
                refresh += ['--empty'] if mode == 'empty' else ['--workspace-root', added, '--workspace-name', 'New']
                current = self.written(refresh, self.output / (state + '-' + mode + '.json'))
                # A second source-free refresh must keep the entire cumulative union.
                continued = self.written(['observe', '--empty', '--previous-report', current],
                                         self.output / (state + '-' + mode + '-again.json'))
                expected = sorted(map(str, roots + ([added] if mode == 'omission' else [])))
                self.written(['export-profile', '--report', continued, '--name', 'synthetic'],
                             Path(replacement['root']) / (state + '-' + mode + '-intent-is-not-origin.json'), 2)
                for fmt in ('json', 'yaml'):
                    good = self.written(['export-profile', '--report', continued, '--name', 'synthetic', '--format', fmt],
                                        self.output / (state + '-' + mode + '-export.' + fmt), 2)
                    if fmt == 'json':
                        self.assertEqual(json.loads(good.read_text())['review']['original_observed_roots'], expected)
                    for index, root in enumerate(roots + ([added] if mode == 'omission' else [])):
                        with self.subTest(state=state, mode=mode, fmt=fmt, root=root):
                            self.refused(['export-profile', '--report', continued, '--name', 'synthetic', '--format', fmt],
                                         root / (state + '-' + mode + '-forbidden.' + fmt))
                            self.refused(refresh, root / (state + '-' + mode + '-' + fmt + '-observe.json'))
                # Reviewing after continuation must not move/remove origin either.
                after = self.written(['review-profile', '--report', continued, '--field-id', 'repository:history',
                                      '--decision', 'reject'], self.output / (state + '-' + mode + '-after.json'))
                self.refused(['export-profile', '--report', after, '--name', 'synthetic'],
                             roots[-1] / (state + '-' + mode + '-after-forbidden.json'))
        for root in roots:
            self.assertEqual((root / 'canary').read_text(), 'SYNTHETIC_UNCHANGED\n')

    def test_source_free_history_is_known_and_legacy_missing_origin_is_refused(self):
        first = self.written(['observe', '--empty'], self.output / 'empty.json')
        again = self.written(['observe', '--empty', '--previous-report', first], self.output / 'again.json')
        self.assertEqual(json.loads(again.read_text())['baseline'].get('original_observed_roots'), [])
        # A legacy revision can be internally consistent without proving history.
        import hashlib
        bundle = json.loads(first.read_text())
        bundle['baseline'].pop('original_observed_roots', None)
        def resign(doc):
            body = {k: v for k, v in doc.items() if k not in ('revision', 'collected_at')}
            doc['revision'] = 'sha256:' + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        resign(bundle['baseline'])
        bundle['candidate']['baseline_revision'] = bundle['baseline']['revision']
        resign(bundle['candidate'])
        legacy = self.owned(self.output / 'legacy.json', json.dumps(bundle))
        for name, args in [('observe', ['observe', '--empty', '--previous-report', legacy]),
                           ('export', ['export-profile', '--report', legacy, '--name', 'legacy'])]:
            self.refused(args, self.output / ('legacy-forbidden-' + name + '.json'))

    def test_origin_contract_malformed_bounds_and_missing_roots_fail_without_artifacts(self):
        import copy
        import hashlib
        roots, seed = self.seed()
        original = json.loads(seed.read_text())
        def resign(doc):
            body = {k: v for k, v in doc.items() if k not in ('revision', 'collected_at')}
            doc['revision'] = 'sha256:' + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        root = str(roots[0])
        values = [None, False, {}, [], [root, root], ['relative'], ['/tmp/../escape'],
                  ['/tmp/control\npath'], ['/tmp/' + 'x' * 4096], [root] * 129,
                  list(reversed(sorted(map(str, roots))))]
        for index, value in enumerate(values):
            bundle = copy.deepcopy(original)
            bundle['baseline']['original_observed_roots'] = value
            resign(bundle['baseline'])
            bundle['candidate']['baseline_revision'] = bundle['baseline']['revision']
            resign(bundle['candidate'])
            prior = self.owned(self.output / f'invalid-origin-{index}.json', json.dumps(bundle))
            for mode, args in [('continue', ['observe', '--empty', '--previous-report', prior]),
                               ('export', ['export-profile', '--report', prior, '--name', 'invalid'])]:
                self.refused(args, self.output / f'no-artifact-{index}-{mode}.json')
        # Valid individually bounded prior history plus one new source cannot be
        # silently truncated to the writer's 128-root ceiling.
        empty = self.written(['observe', '--empty'], self.output / 'bounded-empty.json')
        bundle = json.loads(empty.read_text())
        bundle['baseline']['original_observed_roots'] = sorted(
            str(self.owned(self.base / f'historical-{i}')) for i in range(128))
        resign(bundle['baseline'])
        bundle['candidate']['baseline_revision'] = bundle['baseline']['revision']
        resign(bundle['candidate'])
        prior = self.owned(self.output / 'at-bound.json', json.dumps(bundle))
        self.refused(['observe', '--workspace-root', self.workspace, '--workspace-name', 'New',
                      '--previous-report', prior], self.output / 'union-overflow.json')

    def test_history_origin_never_grants_content_reads(self):
        roots, seed = self.seed()
        script = self.base / 'history-read-probe.py'
        script.write_text('import sys,json,os\n'
            f'sys.path.insert(0, {str(ROOT / "isaac-installer/lib/core")!r})\n'
            'import profile_discovery as d\n'
            'from discovery_cli import _load_bundle\n'
            'from preview_sandbox import confine_readonly\n'
            f'confine_readonly([{str(seed)!r}])\n'
            f'prior = _load_bundle({str(seed)!r}, d)\n'
            'baseline = d.observe(previous_baseline=prior["baseline"])\n'
            'assert baseline["original_observed_roots"] == prior["baseline"]["original_observed_roots"]\n'
            'denied=0\n'
            'for root in baseline["original_observed_roots"]:\n'
            ' for operation in (lambda: open(root+"/canary").read(), lambda: os.listdir(root)):\n'
            '  try: operation()\n'
            '  except PermissionError: denied+=1\n'
            '  else: raise AssertionError("historical root became read grant")\n'
            'print(json.dumps({"denied":denied,"uid":os.getuid(),"gid":os.getgid()}))\n')
        script.chmod(0o644)
        result = self.run_cli(direct=str(script))
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence['denied'], len(roots) * 2)
        self.assertNotEqual(evidence['uid'], 0)
        self.assertNotEqual(evidence['gid'], 0)

    def test_legacy_supervisor_fault_controls_refuse_before_writer_and_valid_faults_remain_partial(self):
        import subprocess
        seed = self.written(['observe', '--empty'], self.output / 'fault-seed.json')
        payload = seed.read_bytes()
        legacy_payload = b'{"baseline":{"observations":[]},"candidate":{},"review":{}}'
        for valid in (False, True):
            for malformed in (False, True):
                destination = self.output / f'fault-{valid}-{malformed}.json'
                script = self.base / f'fault-{valid}-{malformed}.py'
                script.write_text('import sys,subprocess,json\n'
                    f'sys.path.insert(0, {str(ROOT / "isaac-installer/lib/core")!r})\n'
                    'import profile_output as p\n'
                    'calls=[]\n'
                    'def fake(script,args,data=None):\n'
                    ' calls.append(script)\n'
                    f' if script=="discovery_cli.py": return subprocess.CompletedProcess([],0,{payload if valid else legacy_payload!r},b"")\n'
                    + (' return subprocess.CompletedProcess([],2,b"bad",b"")\n' if malformed else
                       ' raise subprocess.TimeoutExpired("synthetic",1)\n') +
                    'p._run=fake\n'
                    f'assert p.main(["observe","--empty","--output",{str(destination)!r}])==2\n'
                    f'assert ("report_writer.py" in calls) is {valid!r}\n')
                script.chmod(0o644)
                result = self.run_cli(direct=str(script))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'possibly_partial' if valid else 'refused')
                self.assertFalse(destination.exists())
                self.assertFalse(json.loads(result.stdout)['execution_authorized'])

    def test_singleton_path_duplicates_and_equals_do_not_choose_first_authority(self):
        home = self.owned(self.base / 'target-home')
        decoy = self.owned(self.base / 'decoy-home')
        external = self.owned(self.base / 'external')
        self.owned(external / 'Synthetic')
        profile = self.owned(self.output / 'desired.yaml',
            'schema_version: v1alpha1\nkind: workstation-profile\nname: synthetic\n'
            'target: offline\ndefaults: false\ndraft: false\nworkspace:\n'
            f'  root: {external}\n  name: Synthetic\n  layout: named\ncomponents: {{}}\nruntimes: {{}}\n')
        base = ['observe-targets', '--desired-profile', profile]
        for index, options in enumerate((['--target-home', decoy, '--target-home', home],
                                         ['--target-home', decoy, '--target-home=' + str(home)],
                                         ['--target-home=' + str(home), '--target-home', decoy])):
            self.refused(base + options, (decoy if index == 2 else home) / ('duplicate-' + str(index) + '.json'))
        self.refused(base + ['--target-home=' + str(home)], home / 'equals-forbidden.json')
        self.written(base + ['--target-home=' + str(home)], self.output / 'equals-good.json')
        report = self.written(['observe', '--empty'], self.output / 'report.json')
        # Reject every singleton path option, both same spelling and mixed equals.
        commands = {
            '--workspace-root': ['observe', '--workspace-name', 'Synthetic'],
            '--previous-report': ['observe', '--empty'],
            '--report': ['export-profile', '--name', 'synthetic'],
            '--decisions': ['review-profile', '--report', report],
            '--desired-profile': ['plan-profile', '--target-home', home],
            '--evidence': ['plan-profile', '--desired-profile', profile, '--target-home', home],
            '--old-profile': ['migration-profile', '--desired-profile', profile, '--target-home', home, '--repositories', report],
            '--repositories': ['migration-profile', '--desired-profile', profile, '--target-home', home, '--old-profile', profile],
        }
        for index, (option, command) in enumerate(commands.items()):
            value = self.workspace if option == '--workspace-root' else profile if 'profile' in option and option != '--previous-report' else report
            for equals in (False, True):
                opts = [option, value] + ([option + '=' + str(value)] if equals else [option, value])
                self.refused(command + opts, self.output / f'duplicate-path-{index}-{equals}.json')
        self.refused(['observe', '--empty', '--output=' + str(self.output / 'other.json')], self.output / 'duplicate-output.json')
        self.assertFalse((self.output / 'other.json').exists())


if __name__ == '__main__':
    unittest.main()
