"""Read-only CLI selection and new-directory candidate rendering acceptance."""
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from click.testing import CliRunner


class RemoteDevelopmentCommandTests(unittest.TestCase):
    def test_cli_consumes_explicit_shared_yaml_profile_without_activation(self):
        import yaml
        command = importlib.import_module('src.python.remote_development_command').remote_development
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = dict(engine='syncthing', image='example.invalid/robotics:review', mappings=[
                dict(name='repo', kind='source', local=str(root / 'source'),
                     remote=str(root / 'remote'), container='/workspaces/repo')])
            profile = dict(schema_version='v1alpha1', kind='workstation-profile', name='selected',
                defaults=False, runtimes={'gr00t': dict(manager='uv', environment='training', python='3.11')},
                components={'gr00t': dict(enabled=True, runtime='gr00t', source=dict(mode='git',
                    repository='https://github.com/NVIDIA/Isaac-GR00T.git', ref='selected'))})
            selection, desired = root / 'selection.json', root / 'desired.yaml'
            selection.write_text(json.dumps(spec))
            desired.write_text(yaml.safe_dump(profile))
            args = ['plan', '--spec', str(selection), '--desired-profile', str(desired)]
            result = CliRunner().invoke(command, args)
            self.assertEqual(result.exit_code, 0, result.output)
            manifest = json.loads(result.output)['runtime_manifest']
            self.assertEqual(manifest['desired_profile'], profile)
            self.assertFalse(manifest['placement_complete'])
            self.assertEqual(set(root.iterdir()), {selection, desired})
            self.assertNotEqual(CliRunner().invoke(command, args + ['--activate']).exit_code, 0)
            out = root / 'candidate'
            result = CliRunner().invoke(command, ['render', *args[1:], '--reviewed', '--output-dir', str(out)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((out / 'runtime-placement.json').is_file())
            self.assertTrue(json.loads(result.output)['continuous']['supervisor_implemented'])
            link = root / 'linked-profile.yaml'
            link.symlink_to(desired)
            self.assertNotEqual(CliRunner().invoke(command, ['plan', '--spec', str(selection),
                '--desired-profile', str(link)]).exit_code, 0)

    def test_cli_plan_observes_only_selection_not_mapping_or_trust_paths(self):
        from unittest import mock
        command = importlib.import_module('src.python.remote_development_command').remote_development
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            targets = [root / name for name in ('source', 'remote', 'key', 'trust', 'private-profile')]
            spec = dict(engine='rsync', endpoint=dict(host='fixture.invalid', user='fixture',
                identity_file=str(targets[2]), known_hosts_file=str(targets[3])),
                protected_paths=[dict(namespace='local', path=str(targets[4]))],
                mappings=[dict(name='repo', kind='source', local=str(targets[0]),
                               remote=str(targets[1]), container='/workspaces/repo')])
            selected = root / 'selection.json'
            selected.write_text(json.dumps(spec))
            original_stat, original_lstat = Path.stat, Path.lstat
            def guarded(original):
                def inspect(path, *args, **kwargs):
                    if path in targets:
                        raise AssertionError('selected target metadata observed')
                    return original(path, *args, **kwargs)
                return inspect
            with mock.patch.object(Path, 'stat', guarded(original_stat)), \
                 mock.patch.object(Path, 'lstat', guarded(original_lstat)), \
                 mock.patch('subprocess.run', side_effect=AssertionError('process invoked')):
                result = CliRunner().invoke(command, ['plan', '--spec', str(selected)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.output)['target_observation'], 'none; lexical plan only')
            self.assertEqual(list(root.iterdir()), [selected])

    def test_plan_entry_is_offline_and_render_requires_new_reviewed_output(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.remote_development_command'),
                             'read-only CLI group is missing')
        command = importlib.import_module('src.python.remote_development_command').remote_development
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = dict(engine='rsync', image='example.invalid/robotics:review', mappings=[
                dict(name='repo', kind='source', local=str(root / 'source'),
                     remote='/home/fixture/workspace/repo', container='/workspaces/repo')])
            path = root / 'selection.json'
            path.write_text(json.dumps(spec))
            before = path.read_bytes()
            result = runner.invoke(command, ['plan', '--spec', str(path)])
            self.assertEqual(result.exit_code, 0, result.output)
            plan = json.loads(result.output)
            self.assertFalse(plan['activation_allowed'])
            self.assertEqual(plan['mappings'][0]['direction'], 'push')
            self.assertEqual(list(root.iterdir()), [path])
            out = root / 'candidate'
            result = runner.invoke(command, ['render', '--spec', str(path), '--output-dir', str(out)])
            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse(out.exists())
            args = ['render', '--spec', str(path), '--output-dir', str(out), '--reviewed']
            result = runner.invoke(command, args)
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse(json.loads(result.output)['activation_allowed'])
            self.assertTrue((out / 'devcontainer.json').is_file())
            self.assertNotEqual(runner.invoke(command, args).exit_code, 0)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotEqual(runner.invoke(command, ['activate', '--spec', str(path)]).exit_code, 0)


    def test_spec_reader_refuses_symlinks_duplicates_nonfiles_and_secret_echo(self):
        import os
        command = importlib.import_module('src.python.remote_development_command').remote_development
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / 'good.json'
            good.write_text(json.dumps(dict(engine='rsync', mappings=[dict(name='repo', kind='source',
                local=str(root / 'source'), remote=str(root / 'remote'), container='/workspaces/repo')])))
            link = root / 'link.json'
            link.symlink_to(good)
            duplicate = root / 'duplicate.json'
            duplicate.write_text(good.read_text().replace('"engine": "rsync"', '"engine": "auto", "engine": "rsync"'))
            invalid = root / 'invalid.json'
            invalid.write_text('SECRET-INVALID-INPUT')
            huge = root / 'huge.json'
            huge.write_text(' ' * 1048577 + good.read_text())
            fifo = root / 'pipe'
            os.mkfifo(fifo)
            # FIFO is tested via the bounded reader directly; it must not block.
            reader = importlib.import_module('src.python.remote_development_command')._load_spec
            for path in (link, duplicate, invalid, huge):
                with self.subTest(path=path):
                    result = runner.invoke(command, ['plan', '--spec', str(path)])
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertNotIn('SECRET-INVALID-INPUT', result.output)
            import signal
            previous = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('reader blocked')))
            signal.alarm(2)
            try:
                with self.assertRaises(ValueError):
                    reader(fifo)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)


if __name__ == '__main__':
    unittest.main()
