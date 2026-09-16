#!/usr/bin/env python3
"""Offline public-preflight regressions; Git/cloud/process seams never execute."""
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


class PublicPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='isaac-preflight-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.conf = copy.deepcopy(config)
        self.conf.update(state_dir=str(self.root / 'state'), app_dir=str(ROOT))
        self.profile = resolve_profile('default')['profile']
        self.profile['components']['sim']['source'].update(
            url='https://artifacts.example.org/sim.zip', sha256='a' * 64)
        for component in ('lab', 'arena'):
            self.profile['components'][component]['source'].update(
                repository=f'https://github.com/example/{component}.git',
                ref='review-ref', revision=None)
        self.reached = []
        self.deployer = None
        self.git_result = SimpleNamespace(returncode=0, stderr='',
            stdout='b' * 40 + '\trefs/heads/review-ref\n')
        for target in ('socket.socket', 'subprocess.Popen'):
            patcher = mock.patch(target, side_effect=AssertionError('real operation forbidden'))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch('src.python.deploy_command.subprocess.run', return_value=self.git_result)
        self.git = patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, extra=(), construct=False):
        path = self.root / 'software.yaml'
        path.write_text(yaml.safe_dump(self.profile))
        def callback(**params):
            self.reached.append(params)
            if construct:
                params.update(cloud='gcp', isaac_workstation_ip='192.0.2.10')
                self.deployer = Deployer(params, self.conf)
        return CliRunner().invoke(DeployCommand('fixture', callback=callback), [
            '--software-profile', str(path), '--deployment-name', 'fixture',
            '--ingress-cidrs', '192.0.2.1/32', '--in-china', 'no', '--no-debug',
        ] + list(extra), env={'DEBUG': '0'})

    def test_git_preflight_isolates_config_auth_proxy_and_worktree(self):
        poison = {key: 'fixture-poison' for key in (
            'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_GLOBAL',
            'GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0',
            'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_EXEC_PATH',
            'GIT_ASKPASS', 'SSH_ASKPASS', 'SSH_AUTH_SOCK', 'GIT_SSH_COMMAND',
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
            'GIT_SSL_NO_VERIFY', 'GIT_SSL_CERT', 'GIT_SSL_KEY',
            'CURL_HOME', 'CURL_CA_BUNDLE', 'NETRC', 'LD_PRELOAD', 'PATH')}
        poison.update(HOME=str(self.root), XDG_CONFIG_HOME=str(self.root))
        directories = []
        def inspect_git(argv, **kwargs):
            self.assertEqual(argv[:2], ['git', 'ls-remote'])
            env = kwargs.get('env', {})
            self.assertEqual(env.get('GIT_CONFIG_NOSYSTEM'), '1')
            self.assertEqual(env.get('GIT_CONFIG_SYSTEM'), os.devnull)
            self.assertEqual(env.get('GIT_CONFIG_GLOBAL'), os.devnull)
            self.assertEqual(env.get('GIT_TERMINAL_PROMPT'), '0')
            self.assertEqual(env.get('GIT_ASKPASS'), '/bin/false')
            self.assertEqual(env.get('SSH_ASKPASS'), '/bin/false')
            self.assertEqual(env.get('GIT_ALLOW_PROTOCOL'), 'https')
            self.assertEqual(env.get('PATH'), os.defpath)
            self.assertTrue(all(value != 'fixture-poison' for value in env.values()))
            self.assertFalse(set(poison).intersection(env) - {
                'HOME', 'XDG_CONFIG_HOME', 'PATH', 'GIT_CONFIG_SYSTEM',
                'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0',
                'GIT_CONFIG_VALUE_0', 'GIT_ASKPASS', 'SSH_ASKPASS', 'GIT_SSH_COMMAND'})
            cwd = Path(kwargs['cwd'])
            directories.append(cwd)
            self.assertEqual(env['HOME'], str(cwd))
            self.assertEqual(env['XDG_CONFIG_HOME'], str(cwd))
            self.assertNotEqual(cwd, self.root)
            self.assertNotEqual(cwd, ROOT)
            self.assertEqual(cwd.stat().st_mode & 0o777, 0o700)
            self.assertEqual(list(cwd.iterdir()), [])
            self.assertEqual(env['GIT_CEILING_DIRECTORIES'], str(cwd.parent))
            settings = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}']
                        for i in range(int(env['GIT_CONFIG_COUNT']))}
            for key, value in {'credential.helper': '', 'credential.interactive': 'false',
                               'core.askPass': '/bin/false', 'http.proxy': '',
                               'http.extraHeader': '', 'http.followRedirects': 'false',
                               'http.sslVerify': 'true'}.items():
                self.assertEqual(settings.get(key), value)
            self.assertEqual(kwargs.get('stdin'), subprocess.DEVNULL)
            self.assertEqual(kwargs.get('timeout'), 30)
            self.assertFalse(kwargs.get('shell', False))
            return self.git_result
        self.git.side_effect = inspect_git
        for selector in ('review-ref', 'latest'):
            self.git_result.stdout = 'b' * 40 + '\trefs/heads/review-ref\n' + 'c' * 40 + '\trefs/tags/v1.2.3\n'
            self.profile['components']['lab']['source']['ref'] = selector
            with self.subTest(selector=selector), mock.patch.dict(os.environ, poison):
                result = self.invoke()
            self.assertEqual(result.exit_code, 0, str(result.exception) + result.output)
        self.assertTrue(directories)
        self.assertTrue(all(not directory.exists() for directory in directories))

    def test_profile_nonzero_or_malformed_git_output_refuses(self):
        outputs = [
            (128, self.git_result.stdout), (1, 'c' * 40 + '\trefs/tags/v1.2.3\n'),
            (0, ''), (0, 'not a Git advertisement'),
            (0, 'wrong-hash\trefs/tags/v1.2.3\n'),
            (0, 'b' * 40 + '\trefs/heads/review-ref\nmalformed'),
            (0, 'b' * 40 + '\trefs/heads/wrong-ref\n'),
        ]
        for selector in ('review-ref', 'latest'):
            self.profile['components']['lab']['source']['ref'] = selector
            for code, stdout in outputs:
                with self.subTest(selector=selector, code=code, stdout=stdout):
                    self.git.return_value = SimpleNamespace(returncode=code, stdout=stdout,
                                                           stderr='untrusted-remote-message')
                    result = self.invoke(construct=True)
                    self.assertEqual(result.exit_code, 2, result.output)
                    self.assertEqual(self.reached, [])
                    self.assertFalse((self.root / 'state').exists())
                    self.assertNotIn('untrusted-remote-message', result.output)

    def test_profile_sha_requires_mocked_commit_object_proof(self):
        for component in ('lab', 'arena'):
            self.profile['components'][component]['source']['revision'] = 'd' * 40
        def proof(argv, **kwargs):
            output = 'commit\n' if 'cat-file' in argv else 'd' * 40 + '\n' if 'rev-parse' in argv else ''
            kwargs['stdout'].write(output.encode('utf-8'))
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        self.git.side_effect = proof
        result = self.invoke(construct=True)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.git.call_count, 8)
        assert self.deployer is not None
        inventory = self.deployer.create_ansible_inventory(write=False)
        for component in ('isaaclab', 'isaaclab_arena'):
            self.assertIn(component + '_git_checkpoint="' + 'd' * 40 + '"', inventory)
        report = self.deployer.software_profile_report()
        for field in ('apply_supported', 'runtime_verified', 'references_verified'):
            self.assertFalse(report[field])
        self.assertFalse((self.root / 'state/fixture/.inventory').exists())
        for call in self.git.call_args_list:
            argv = call.args[0]
            if 'fetch' in argv:
                self.assertEqual(argv[-1], 'd' * 40)
            self.assertNotIn('ls-remote', argv)
            self.assertNotIn('review-ref', argv)
        self.assertNotIn('commit reachability unverified', result.output.lower())
        self.assertEqual(self.reached[0]['isaaclab'], 'd' * 40)

    def test_profile_sha_public_failures_refuse_before_deployer(self):
        for component in ('lab', 'arena'):
            self.profile['components'][component]['source']['revision'] = 'd' * 40
        for failure in (OSError('fixture'), subprocess.TimeoutExpired('git', 30),
                        SimpleNamespace(returncode=128, stdout=self.git_result.stdout, stderr=''),
                        SimpleNamespace(returncode=0, stdout='', stderr=''),
                        SimpleNamespace(returncode=0, stdout='malformed', stderr='')):
            with self.subTest(failure=type(failure).__name__):
                self.git.side_effect = failure if isinstance(failure, Exception) else None
                self.git.return_value = failure
                result = self.invoke(construct=True)
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertEqual(len(self.reached), 0)
                self.assertFalse((self.root / 'state').exists())

    def test_legacy_sha_is_still_syntax_only_without_lookup(self):
        for sha in ('abc1234', 'd' * 40):
            self.assertEqual(DeployCommand.git_ref_callback(None, click.Option(['--isaaclab']), sha), sha)
        self.git.assert_not_called()

    def test_normalized_registry_conflict_refuses_before_state_creation(self):
        spec = {'name': 'fixture', 'tier': 'simple', 'raw': {
            'container_registry': {'enabled': True, 'provider': 'dockerhub',
                'namespace': 'exampleorg', 'images': {
                    'gr00t': 'docker.io/exampleorg/gr00t@sha256:' + 'c' * 64}}}}
        # Only file lookup is replaced; resolve_security_profile, both registry
        # normalizers and compatibility checks run on the real Click params.
        with mock.patch('src.python.config.load_profile_spec', return_value=spec), \
                mock.patch('src.python.deployer.os.makedirs', side_effect=AssertionError('state mkdir forbidden')) as mkdir:
            result = self.invoke(['--security-profile', 'fixture'], construct=True)
        self.assertEqual(result.exit_code, 1, str(result.exception) + result.output)
        self.assertIn('native intent cannot combine with registry', result.output)
        self.assertEqual(len(self.reached), 1)
        self.assertTrue(self.reached[0]['container_registry']['enabled'])
        mkdir.assert_not_called()
        self.assertFalse((self.root / 'state').exists())

    def test_additional_enabled_git_components_require_public_ref_preflight(self):
        for component in ('gr00t', 'lerobot'):
            self.profile['components'][component]['enabled'] = True
            self.profile['components'][component]['source'].update(ref='review-ref', revision=None)
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        queried = {next(arg for arg in call.args[0] if arg.startswith('https://'))
                   for call in self.git.call_args_list}
        self.assertEqual(queried, {component['source']['repository']
            for component in self.profile['components'].values()
            if component['enabled'] and component['source']['mode'] == 'git'})
        self.reached.clear()
        for component in ('gr00t', 'lerobot'):
            repository = self.profile['components'][component]['source']['repository']
            def denied(argv, **kwargs):
                if repository in argv:
                    return SimpleNamespace(returncode=128, stdout='', stderr='fixture denied')
                return self.git_result
            self.git.side_effect = denied
            with self.subTest(component=component):
                result = self.invoke(construct=True)
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertEqual(len(self.reached), 0)
                self.assertFalse((self.root / 'state').exists())

    def test_profile_private_source_override_refuses_before_git(self):
        result = self.invoke(['--isaaclab-private-git', 'https://github.com/example/private.git'], construct=True)
        self.assertEqual(result.exit_code, 2, result.output)
        self.git.assert_not_called()
        self.assertEqual(len(self.reached), 0)
        self.assertFalse((self.root / 'state').exists())

    def test_malformed_profile_sources_fail_before_any_git_or_deployer(self):
        source = self.profile['components']['lab']['source']
        for key, value in (
            ('repository', 'https://user:fixture@github.com/example/lab.git'),
            ('repository', 'https://github.com/example/lab.git?token=fixture'),
            ('repository', 'git@github.com:example/lab.git'),
            ('repository', 'https://github.com/example/../lab.git'),
            ('ref', '--upload-pack=fixture'), ('ref', 'bad..ref'),
            ('ref', 'bad\nref'), ('revision', 'd' * 39),
        ):
            old = source.get(key)
            with self.subTest(key=key, value=value):
                source[key] = value
                result = self.invoke(construct=True)
                self.assertEqual(result.exit_code, 2, result.output)
                self.git.assert_not_called()
                self.assertEqual(len(self.reached), 0)
                self.assertFalse((self.root / 'state').exists())
            source[key] = old

    def test_latest_profile_errors_are_fail_closed_and_sanitized(self):
        self.profile['components']['lab']['source']['ref'] = 'latest'
        for error in (OSError('untrusted-remote-message'), subprocess.TimeoutExpired('git', 30),
                      subprocess.SubprocessError('untrusted-remote-message')):
            self.git.side_effect = error
            with self.subTest(error=type(error).__name__):
                result = self.invoke(['--debug'], construct=True)
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn('anonymous', result.output.lower())
                self.assertNotIn('untrusted-remote-message', result.output)
                self.assertEqual(len(self.reached), 0)
                self.assertFalse((self.root / 'state').exists())

    def test_profile_git_exceptions_refuse_before_deployer(self):
        for error in (subprocess.TimeoutExpired('git', 30), OSError('fixture'),
                      subprocess.SubprocessError('fixture')):
            with self.subTest(error=type(error).__name__):
                self.git.side_effect = error
                result = self.invoke(construct=True)
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn('anonymous', result.output.lower())
                self.assertEqual(self.reached, [])
                self.assertFalse((self.root / 'state').exists())


if __name__ == '__main__':
    unittest.main()
