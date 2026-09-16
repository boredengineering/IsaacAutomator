#!/usr/bin/env python3
"""OFFLINE ONLY: mocked Git output tests, not commit/reachability/live proof."""
import copy
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import click
from click.testing import CliRunner
import yaml

from src.python.config import c as config
from src.python.deploy_command import DeployCommand
from src.python.deployer import Deployer
from src.python.workstation_profile import resolve_profile

ROOT = Path(__file__).resolve().parents[2]
SHA = 'd' * 40


def mocked_output(output, kwargs):
    # Emulate the real stdout file/pipe contract; never run Git.
    if hasattr(kwargs.get('stdout'), 'write'):
        kwargs['stdout'].write(output.encode('utf-8'))
    return SimpleNamespace(returncode=0, stdout=output, stderr='')


class ProfileShaProofTests(unittest.TestCase):
    def test_named_annotated_tag_is_peeled_to_commit_without_git_execution(self):
        from src.python import public_git
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            if 'cat-file' in args:
                return 'tag' if args[-1] == 'FETCH_HEAD' else 'commit'
            if 'rev-parse' in args:
                return 'b' * 40 if args[-1] == 'FETCH_HEAD' else SHA
            if 'ls-tree' in args:
                return '100644 blob ' + 'a' * 40 + '\tREADME.md'
            return ''
        with mock.patch.object(public_git.os.path, 'lexists', return_value=False), \
             mock.patch.object(public_git.os, 'mkdir'), \
             mock.patch.object(public_git.tempfile, 'TemporaryDirectory') as directory, \
             mock.patch.object(public_git, '_runner', return_value=run):
            directory.return_value.__enter__.return_value = '/fixture/control'
            self.assertEqual(public_git.checkout_public_source(
                'https://github.com/example/source.git', 'v3.0.0-beta2', '/fixture/new-source'), SHA)
        self.assertTrue(any('checkout' in call and call[-1] == SHA for call in calls))

    def test_gitmodules_blob_is_refused_before_checkout_without_git_execution(self):
        from src.python import public_git
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            if 'cat-file' in args:
                return 'commit'
            if 'rev-parse' in args:
                return SHA
            if 'ls-tree' in args:
                return '100644 blob ' + 'a' * 40 + '\t.gitmodules'
            return ''
        with mock.patch.object(public_git.os.path, 'lexists', return_value=False), \
             mock.patch.object(public_git.os, 'mkdir'), \
             mock.patch.object(public_git.tempfile, 'TemporaryDirectory') as directory, \
             mock.patch.object(public_git, '_runner', return_value=run):
            directory.return_value.__enter__.return_value = '/fixture/control'
            with self.assertRaisesRegex(public_git.PublicGitError, 'submodules'):
                public_git.checkout_public_source('https://github.com/example/source.git', SHA, '/fixture/new-source')
        self.assertFalse(any('checkout' in call for call in calls))

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='isaac-sha-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = resolve_profile('default')['profile']
        self.profile['components']['sim']['source'].update(
            url='https://artifacts.example.org/sim.zip', sha256='a' * 64)
        for name in ('lab', 'arena'):
            self.profile['components'][name]['source'].update(
                repository=f'https://github.com/example/{name}.git', ref='review-ref', revision=SHA)
        self.reached = []
        self.deployer = None
        for target in ('socket.socket', 'subprocess.Popen'):
            patcher = mock.patch(target, side_effect=AssertionError('real operation forbidden'))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch('subprocess.run', side_effect=self.mock_git)
        self.git = patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def mock_git(argv, **kwargs):
        output = ''
        if 'cat-file' in argv:
            output = 'commit\n'
        elif 'rev-parse' in argv:
            output = SHA + '\n'
        elif 'ls-remote' in argv:
            output = 'b' * 40 + '\trefs/heads/review-ref\n'
        return mocked_output(output, kwargs)

    def invoke(self):
        path = self.root / 'profile.yaml'
        path.write_text(yaml.safe_dump(self.profile))
        conf = copy.deepcopy(config)
        conf.update(state_dir=str(self.root / 'state'), app_dir=str(ROOT))
        def callback(**params):
            self.reached.append(params)
            params.update(cloud='gcp', isaac_workstation_ip='192.0.2.10')
            self.deployer = Deployer(params, conf)
        return CliRunner().invoke(DeployCommand('fixture', callback=callback), [
            '--software-profile', str(path), '--deployment-name', 'fixture',
            '--ingress-cidrs', '192.0.2.1/32', '--in-china', 'no', '--no-debug',
        ], env={'DEBUG': '0'})

    def test_isolated_fixed_git_commands_and_cleanup(self):
        poison = {key: 'poison' for key in (
            'HOME', 'PATH', 'XDG_CONFIG_HOME', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT',
            'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0', 'GIT_DIR', 'GIT_WORK_TREE',
            'GIT_EXEC_PATH', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
            'GIT_TEMPLATE_DIR', 'GIT_ASKPASS', 'SSH_AUTH_SOCK', 'HTTP_PROXY', 'HTTPS_PROXY',
            'ALL_PROXY', 'http_proxy', 'https_proxy', 'LD_PRELOAD', 'CURL_HOME', 'NETRC')}
        with mock.patch.dict(os.environ, poison):
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)
        for call in self.git.call_args_list:
            argv, kw = call.args[0], call.kwargs
            self.assertEqual(argv[:2], ['/usr/bin/timeout', '--signal=KILL'])
            self.assertEqual(argv[3], '/usr/bin/git')
            self.assertTrue(kw['start_new_session'])
            self.assertNotIn('checkout', argv)
            self.assertNotIn('clone', argv)
            self.assertFalse(kw.get('shell', False))
            self.assertEqual(kw['stdin'], subprocess.DEVNULL)
            self.assertEqual(kw['stderr'], subprocess.DEVNULL)
            self.assertGreater(kw['timeout'], 0)
            self.assertLessEqual(kw['timeout'], 10)
            self.assertEqual(kw['preexec_fn'].__name__, '_limit_files')
            env = kw['env']
            self.assertNotIn('poison', env.values())
            for key in ('GIT_DIR', 'GIT_EXEC_PATH', 'GIT_CONFIG_PARAMETERS', 'HTTPS_PROXY', 'LD_PRELOAD'):
                self.assertNotIn(key, env)
            self.assertEqual(env['HOME'], kw['cwd'])
            self.assertEqual(env['GIT_CONFIG_GLOBAL'], '/dev/null')
            self.assertEqual(env['GIT_CONFIG_SYSTEM'], '/dev/null')
            self.assertEqual(env['GIT_ALLOW_PROTOCOL'], 'https')
            settings = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}']
                        for i in range(int(env['GIT_CONFIG_COUNT']))}
            for key, value in {'credential.helper': '', 'http.proxy': '', 'http.extraHeader': '',
                'core.hooksPath': '/dev/null', 'init.templateDir': '', 'gc.auto': '0',
                'maintenance.auto': 'false', 'protocol.allow': 'never',
                'protocol.https.allow': 'always', 'http.followRedirects': 'false'}.items():
                self.assertEqual(settings[key], value)
            self.assertFalse(Path(kw['cwd']).exists())
            if 'fetch' in argv:
                for arg in ('--depth=1', '--filter=blob:none', '--no-tags',
                            '--no-recurse-submodules', '--no-auto-maintenance'):
                    self.assertIn(arg, argv)
            if 'init' in argv:
                self.assertIn('--bare', argv)
                self.assertIn('--template=', argv)

    def test_every_proof_failure_blocks_callback_and_state(self):
        failures = [OSError('UNTRUSTED'), subprocess.TimeoutExpired('UNTRUSTED', 10),
                    subprocess.SubprocessError('UNTRUSTED')]
        for stage in ('init', 'fetch', 'cat-file', 'rev-parse'):
            for failure in failures + [SimpleNamespace(returncode=128, stdout='', stderr='UNTRUSTED')]:
                def fail(argv, **kwargs):
                    if stage in argv:
                        if isinstance(failure, Exception):
                            raise failure
                        return failure
                    return self.mock_git(argv, **kwargs)
                with self.subTest(stage=stage, failure=repr(failure)):
                    self.git.reset_mock()
                    self.git.side_effect = fail
                    result = self.invoke()
                    self.assertEqual(result.exit_code, 2, str(result.exception) + result.output)
                    self.assertIn('full-SHA commit proof failed', result.output)
                    self.assertNotIn('UNTRUSTED', result.output)
                    self.assertEqual(self.reached, [])
                    self.assertFalse((self.root / 'state').exists())
                    self.assertLessEqual(self.git.call_count, 4)
                    self.assertTrue(all(not Path(c.kwargs['cwd']).exists() for c in self.git.call_args_list))

    def test_wrong_type_hash_empty_and_malformed_proofs_block(self):
        for stage, output in (('cat-file', 'tag\n'), ('cat-file', 'blob\n'),
                ('cat-file', ''), ('cat-file', 'commit\nUNTRUSTED'),
                ('rev-parse', 'e' * 40 + '\n'), ('rev-parse', 'd' * 39),
                ('rev-parse', SHA + '\n' + SHA), ('rev-parse', ''),
                ('init', 'x' * 4097)):
            def fail(argv, **kwargs):
                if stage in argv:
                    return mocked_output(output, kwargs)
                return self.mock_git(argv, **kwargs)
            with self.subTest(stage=stage, output=output[:80]):
                self.git.side_effect = fail
                result = self.invoke()
                self.assertEqual(result.exit_code, 2, str(result.exception) + result.output)
                self.assertEqual(self.reached, [])
                self.assertFalse((self.root / 'state').exists())

    def test_total_budget_exhaustion_is_fail_closed(self):
        from src.python import public_git
        # Deadline at 30; init starts at 0, completes at 9; fetch starts at 25.
        with mock.patch.object(public_git.time, 'monotonic', side_effect=[0, 0, 9, 25, 31]):
            result = self.invoke()
        self.assertEqual(result.exit_code, 2, str(result.exception) + result.output)
        self.assertEqual(self.git.call_count, 2)
        self.assertEqual(self.git.call_args_list[0].kwargs['timeout'], 10)
        self.assertEqual(self.git.call_args_list[1].kwargs['timeout'], 5)
        self.assertEqual(self.reached, [])
        self.assertFalse((self.root / 'state').exists())

    def test_all_enabled_git_components_use_exact_consumer_sources(self):
        self.profile['components']['sim']['source'] = {
            'mode': 'git', 'repository': 'https://github.com/example/sim.git', 'ref': SHA, 'revision': None}
        for name in ('gr00t', 'lerobot'):
            self.profile['components'][name]['enabled'] = True
            self.profile['components'][name]['source'].update(ref=SHA, revision=None)
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)
        sources = {v['source']['repository'] for v in self.profile['components'].values() if v['enabled']}
        fetches = [c.args[0] for c in self.git.call_args_list if 'fetch' in c.args[0]]
        self.assertEqual({a[-2] for a in fetches}, sources)
        self.assertEqual(len(fetches), 5)
        self.assertTrue(all(a[-1] == SHA for a in fetches))
        assert self.deployer is not None
        inventory = self.deployer.create_ansible_inventory(write=False)
        for name in ('isaacsim', 'isaaclab', 'isaaclab_arena', 'gr00t', 'lerobot'):
            self.assertIn(name + '_git_checkpoint="' + SHA + '"', inventory)

    def test_partial_profile_and_legacy_sha_compatibility_is_explicit(self):
        for name in ('lab', 'arena'):
            self.profile['components'][name]['source'].update(ref='abc1234', revision=None)
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)
        self.assertIn('commit reachability unverified', result.output)
        self.assertTrue(all('ls-remote' in c.args[0] for c in self.git.call_args_list))
        self.git.reset_mock()
        for sha in ('abc1234', SHA):
            self.assertEqual(DeployCommand.git_ref_callback(None, click.Option(['--isaaclab']), sha), sha)
        self.git.assert_not_called()

    def test_fresh_target_uses_exact_source_and_never_recurses(self):
        from src.python import public_git
        self.assertTrue(hasattr(public_git, 'checkout_public_source'),
                        'target source consumers need isolated fresh-checkout helper')
        destination = self.root / 'target'
        def git(argv, **kwargs):
            if 'ls-tree' in argv:
                return mocked_output('100644 blob ' + SHA + '\tREADME.md\n', kwargs)
            return self.mock_git(argv, **kwargs)
        self.git.side_effect = git
        public_git.checkout_public_source('https://github.com/example/lab.git', SHA, str(destination))
        fetches = [c.args[0] for c in self.git.call_args_list if 'fetch' in c.args[0]]
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0][-2:], ['https://github.com/example/lab.git', SHA])
        self.assertTrue(any('checkout' in c.args[0] for c in self.git.call_args_list))
        for call in self.git.call_args_list:
            self.assertEqual(call.args[0][3], '/usr/bin/git')
            self.assertNotIn('--recursive', call.args[0])
            self.assertNotIn('--force', call.args[0])
            self.assertNotIn('submodule', call.args[0])
            self.assertLessEqual(call.kwargs['timeout'], 10)

    def test_existing_target_refuses_without_subprocess_or_mutation(self):
        from src.python import public_git
        self.assertTrue(hasattr(public_git, 'checkout_public_source'))
        destination = self.root / 'existing'
        destination.mkdir()
        (destination / '.git').mkdir()
        config_file = destination / '.git/config'
        before = '[remote "origin"]\nurl = https://github.com/other/repo.git\n'
        config_file.write_text(before)
        with self.assertRaisesRegex(public_git.PublicGitError, 'existing'):
            public_git.checkout_public_source('https://github.com/example/lab.git', SHA, str(destination))
        self.git.assert_not_called()
        self.assertEqual(config_file.read_text(), before)

    def test_target_submodule_tree_refuses_before_checkout(self):
        from src.python import public_git
        self.assertTrue(hasattr(public_git, 'checkout_public_source'))
        for tree in ('160000 commit ' + SHA + '\tmodules/dep\n',
                     '100644 blob ' + SHA + '\t.gitmodules\n'):
            def git(argv, **kwargs):
                if 'ls-tree' in argv:
                    return mocked_output(tree, kwargs)
                return self.mock_git(argv, **kwargs)
            self.git.reset_mock()
            self.git.side_effect = git
            with self.assertRaisesRegex(public_git.PublicGitError, 'submodule'):
                public_git.checkout_public_source('https://github.com/example/lab.git', SHA, str(self.root / ('target-' + str(len(tree)))))
            self.assertFalse(any('checkout' in c.args[0] for c in self.git.call_args_list))

    def test_native_source_roles_dispatch_profile_git_without_legacy_mutation(self):
        paths = {
            'isaacsim-source/tasks/install.yml': ('isaacsim_git_repo', 'isaacsim_git_checkpoint'),
            'isaaclab-source/tasks/install.yml': ('isaaclab_git_repo', 'isaaclab_git_checkpoint'),
            'isaaclab-arena-source/tasks/install.yml': ('isaaclab_arena_git_repo', 'isaaclab_arena_git_checkpoint'),
            'gr00t/tasks/native.yml': ('gr00t_git_repo', 'gr00t_git_checkpoint'),
            'lerobot/tasks/main.yml': ('lerobot_git_repo', 'lerobot_git_checkpoint'),
        }
        for path, pair in paths.items():
            text = (ROOT / 'src/ansible/roles' / path).read_text()
            with self.subTest(path=path):
                self.assertIn('public-git/tasks/source.yml', text)
                tasks = yaml.safe_load(text)
                def walk(items):
                    for task in items:
                        yield task
                        yield from walk(task.get('block', []))
                tasks = list(walk(tasks))
                include = next(t for t in tasks if 'public-git/tasks/source.yml' in t.get('ansible.builtin.include_tasks', ''))
                self.assertEqual(include['vars']['public_git_repository'], '{{ ' + pair[0] + ' }}')
                self.assertEqual(include['vars']['public_git_ref'], '{{ ' + pair[1] + ' }}')
                for task in tasks:
                    if 'git' in task or 'git_config' in task or ('shell' in task and any(
                            op in task['shell'] for op in ('git fetch', 'git clone', 'git config', 'git lfs', 'git submodule'))):
                        self.assertIn('not (public_git_profile', str(task.get('when', '')), task['name'])
        local = (ROOT / 'isaac-installer/lib/core/git_workspace.sh').read_text()
        setup = local.split('setup_git_repo_with_fork() {', 1)[1]
        self.assertIn('CFG_PUBLIC_GIT_PROFILE', setup)
        self.assertLess(setup.index('CFG_PUBLIC_GIT_PROFILE'), setup.index('ensure_github_fork'))
        self.assertIn('public_git.py', setup)
        fetch = local.split('fetch_and_checkout_ref() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('CFG_PUBLIC_GIT_PROFILE', fetch)

    def test_git_stdout_is_file_bounded_not_unbounded_pipe(self):
        def git(argv, **kwargs):
            self.assertNotEqual(kwargs['stdout'], subprocess.PIPE,
                                'Git tree/remote output must not accumulate in memory without a cap')
            self.assertTrue(hasattr(kwargs['stdout'], 'read'))
            return self.mock_git(argv, **kwargs)
        self.git.side_effect = git
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)

    def test_profile_mode_flag_reaches_inventory_and_native_local_parser(self):
        import importlib.util
        from src.python.profile_adapters import render_profile
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)
        assert self.deployer is not None
        inventory = self.deployer.create_ansible_inventory(write=False)
        self.assertIn('public_git_profile=true', inventory,
                      'profile routing must actually reach target isolation, not just an unused helper')
        artifact = render_profile(self.profile, 'local', '/home/tester')['artifact']
        self.assertIs(artifact.get('public_git_profile'), True)
        path = ROOT / 'isaac-installer/lib/core/profile_parser.py'
        spec = importlib.util.spec_from_file_location('sha_profile_parser', path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = module.parse_profile_text(yaml.safe_dump(artifact))
        self.assertIn(b'CFG_PUBLIC_GIT_PROFILE\0true\0', payload)

    def test_file_budget_hook_only_changes_child_limit(self):
        from src.python import public_git
        with mock.patch.object(public_git.resource, 'getrlimit', return_value=(999, 1024)), \
                mock.patch.object(public_git.resource, 'setrlimit') as limit:
            public_git._limit_files()
        limit.assert_called_once_with(public_git.resource.RLIMIT_FSIZE, (1024, 1024))
        with mock.patch.object(public_git.resource, 'getrlimit', return_value=(999, public_git.resource.RLIM_INFINITY)), \
                mock.patch.object(public_git.resource, 'setrlimit') as limit:
            public_git._limit_files()
        limit.assert_called_once_with(public_git.resource.RLIMIT_FSIZE,
                                     (public_git.MAX_FILE_BYTES, public_git.MAX_FILE_BYTES))

    def test_target_cli_existing_destination_fails_without_git(self):
        from contextlib import redirect_stderr
        import io
        from src.python import public_git
        destination = self.root / 'existing-cli'
        destination.mkdir()
        output = io.StringIO()
        with redirect_stderr(output):
            code = public_git.main(['checkout', 'https://github.com/example/lab.git', SHA, str(destination)])
        self.assertEqual(code, 2)
        self.assertIn('existing destination/origin', output.getvalue())
        self.git.assert_not_called()
        self.assertEqual(list(destination.iterdir()), [])

    def test_full_sha_fetch_type_exact_hash_precedes_inventory(self):
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)
        calls = self.git.call_args_list
        fetches = [c for c in calls if 'fetch' in c.args[0]]
        self.assertEqual(len(fetches), 2, 'advertisement alone is not full-SHA commit proof')
        for name, prefix in (('lab', 'isaaclab'), ('arena', 'isaaclab_arena')):
            source = self.profile['components'][name]['source']
            self.assertTrue(any(c.args[0][-2:] == [source['repository'], SHA] for c in fetches))
            inventory = self.deployer.create_ansible_inventory(write=False)
            self.assertIn(prefix + '_git_checkpoint="' + SHA + '"', inventory)
            self.assertIn(prefix + '_git_repo="' + source['repository'] + '"', inventory)
        self.assertEqual(sum('cat-file' in c.args[0] for c in calls), 2)
        self.assertEqual(sum('rev-parse' in c.args[0] for c in calls), 2)
        self.assertFalse(any('ls-remote' in c.args[0] for c in calls))
        self.assertFalse((self.root / 'state/fixture/.inventory').exists())
        for field in ('apply_supported', 'runtime_verified', 'references_verified'):
            self.assertFalse(self.deployer.software_profile_report()[field])
        self.assertNotIn('commit reachability unverified', result.output)


if __name__ == '__main__':
    unittest.main()
