"""Offline optional registry tests: temporary homes, fake Docker, no cloud calls."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
import yaml
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'ansible'
ROLE = ROOT / 'roles/container-registry'
HOST = '123456789012.dkr.ecr.us-east-1.amazonaws.com'
IMAGE = HOST + '/workloads/gr00t@sha256:' + 'a' * 64
HUB = 'docker.io/example/gr00t@sha256:' + 'b' * 64


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ecr() -> dict:
    return dict(enabled=True, provider='aws_ecr', account_id='123456789012',
                region='us-east-1', repository='workloads/gr00t', images={'gr00t': IMAGE})


def hub() -> dict:
    return dict(enabled=True, provider='dockerhub', namespace='example', images={'gr00t': HUB})


class ValidationTests(unittest.TestCase):
    def validator(self):
        path = ROLE / 'filter_plugins/container_registry.py'
        self.assertTrue(path.exists(), 'container registry validation is not implemented')
        return load(path, 'registry_validation').validate_settings

    def test_disabled_and_ecr_mapping_or_json(self):
        validate = self.validator()
        self.assertEqual(validate('{}', ''), {'enabled': False})
        self.assertEqual(validate({'enabled': False}, 'gcp'), {'enabled': False})
        for value in (ecr(), json.dumps(ecr())):
            result = validate(value, 'aws')
            self.assertTrue(result['enabled'])
            self.assertEqual(result['registry'], HOST)
            self.assertEqual(result['images'], {'gr00t': IMAGE})
        with self.assertRaises(ValueError):
            validate(ecr(), 'gcp')

    def test_exact_schema_and_pins_fail_closed(self):
        validate = self.validator()
        invalid = [None, [], 'null', '[]', 'garbage', '{"enabled":false,"enabled":true}',
                   {'enabled': 'false'}, {'enabled': False, 'password': 'secret'},
                   dict(ecr(), password='secret'), dict(ecr(), account_id=123456789012),
                   dict(ecr(), account_id='12345678901'), dict(ecr(), region='cn-north-1'),
                   dict(ecr(), region='us-gov-west-1'), dict(ecr(), region='us-east-1\n'),
                   dict(ecr(), repository='../escape'), dict(ecr(), images=[]),
                   dict(ecr(), repository='workloads--gr00t'), dict(hub(), namespace='a'),
                   dict(ecr(), images={'bad name': IMAGE}),
                   dict(ecr(), images={'gr00t': IMAGE.replace('123456789012', '999999999999')}),
                   dict(ecr(), images={'gr00t': IMAGE.replace('/workloads/', '/other/')}),
                   dict(ecr(), images={'gr00t': IMAGE.replace('us-east-1', 'us-west-2')}),
                   dict(ecr(), images={'gr00t': IMAGE + '\n'}),
                   dict(ecr(), images={'gr00t': IMAGE.replace('@sha256:', ':latest@sha256:')}),
                   dict(ecr(), images={'gr00t': IMAGE.replace('a' * 64, 'A' * 64)})]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value, 'aws')

    def test_hub_auth_and_cloud_independence(self):
        validate = self.validator()
        for cloud in ('aws', 'gcp', 'azure', 'alicloud', ''):
            result = validate(hub(), cloud)
            self.assertEqual(result['auth'], 'anonymous')
            self.assertEqual(result['images'], {'gr00t': HUB})
            self.assertEqual(validate(dict(hub(), auth='existing'), cloud)['auth'], 'existing')
        for value in (dict(hub(), auth='password'), dict(hub(), namespace='Bad/namespace'),
                      dict(hub(), images={'gr00t': HUB.replace('docker.io/', '')}),
                      dict(hub(), images={'gr00t': HUB.replace('/example/', '/elsewhere/')}),
                      dict(hub(), images={'gr00t': HUB.replace('/gr00t@', '/nested/gr00t@')})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value, 'aws')

    def test_gcp_validated_but_legacy_role_remains_responsible(self):
        value = dict(enabled=True, provider='gcp_artifact_registry', project='test-project',
                     location='us-central1', repository='workloads', images={})
        result = self.validator()(value, 'gcp')
        self.assertEqual(result['provider'], 'gcp_artifact_registry')
        self.assertTrue(result['enabled'])
        with self.assertRaises(ValueError):
            self.validator()(dict(value, location='us'), 'gcp')


class HelperTests(unittest.TestCase):
    def helper(self):
        path = ROLE / 'files/docker-credential-isaac-ecr.py'
        self.assertTrue(path.exists(), 'ECR wrapper is not implemented')
        return load(path, 'ecr_helper')

    def test_official_helper_get_uses_clean_metadata_only_environment(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, executable, trace = root / 'config.json', root / 'helper', root / 'trace.json'
            config.write_text(json.dumps({'registry': HOST, 'region': 'us-east-1'}))
            executable.write_text('#!/usr/bin/python3\nimport json,os,sys\n'
                + 'from pathlib import Path\n'
                + 'host=sys.stdin.read().strip()\n'
                + 'Path(' + repr(str(trace)) + ').write_text(json.dumps([sys.argv[1:], host, dict(os.environ)]))\n'
                + 'print(json.dumps(dict(ServerURL=host, Username="AWS", Secret="offline-token")))\n')
            executable.chmod(0o700)
            out, err = io.StringIO(), io.StringIO()
            with patch.object(helper, 'CONFIG_PATH', config), patch.object(helper, 'HELPER', str(executable)), \
                 patch.dict(os.environ, {'AWS_ACCESS_KEY_ID': 'bad', 'AWS_SECRET_ACCESS_KEY': 'bad',
                                        'AWS_PROFILE': 'bad', 'AWS_WEB_IDENTITY_TOKEN_FILE': '/must-not-read',
                                        'AWS_CONTAINER_CREDENTIALS_FULL_URI': 'http://evil.invalid',
                                        'AWS_ENDPOINT_URL': 'http://evil.invalid', 'HTTPS_PROXY': 'http://evil.invalid'}), \
                 patch.object(sys, 'stdin', io.StringIO(HOST + '\n')), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(helper.main(['get']), 0)
            args, host, env = json.loads(trace.read_text())
            self.assertEqual(args, ['get'])
            self.assertEqual(host, HOST)
            for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_PROFILE', 'AWS_WEB_IDENTITY_TOKEN_FILE',
                        'AWS_CONTAINER_CREDENTIALS_FULL_URI', 'AWS_ENDPOINT_URL', 'HTTPS_PROXY'):
                self.assertNotIn(key, env)
            self.assertEqual(env['AWS_SHARED_CREDENTIALS_FILE'], '/dev/null')
            self.assertEqual(env['AWS_CONFIG_FILE'], '/dev/null')
            self.assertEqual(env['AWS_ECR_DISABLE_CACHE'], 'true')
            self.assertEqual(env['AWS_ECR_CACHE_DIR'], '/dev/null')
            # Upstream's logger falls back to os.TempDir when cache/log fails.
            self.assertEqual(env.get('TMPDIR'), '/dev/null')
            self.assertEqual(env['AWS_EC2_METADATA_SERVICE_ENDPOINT'], 'http://169.254.169.254')
            self.assertEqual(env['AWS_REGION'], 'us-east-1')
            self.assertEqual(json.loads(out.getvalue())['Secret'], 'offline-token')
            self.assertEqual(err.getvalue(), '')
            self.assertNotIn('offline-token', config.read_text() + trace.read_text())

    def test_untrusted_host_or_configuration_never_invokes_helper(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            for host, region in ((HOST + '.evil', 'us-east-1'), ('https://' + HOST, 'us-east-1'),
                                 (HOST + '\nother.host', 'us-east-1'), (HOST, 'us-west-2'),
                                 (HOST, 'cn-north-1')):
                config.write_text(json.dumps({'registry': HOST, 'region': region}))
                out = io.StringIO()
                with self.subTest(host=host, region=region), patch.object(helper, 'CONFIG_PATH', config), \
                     patch.object(helper.subprocess, 'run') as run, patch.object(sys, 'stdin', io.StringIO(host)), \
                     contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(helper.main(['get']), 1)
                    run.assert_not_called()
                self.assertEqual(out.getvalue(), '')

    def test_non_get_operations_do_not_access_credentials(self):
        helper = self.helper()
        for operation, status, output in [('list', 0, '{}\n'), ('erase', 0, ''), ('store', 1, ''), ('oops', 1, '')]:
            out = io.StringIO()
            with patch.object(helper.subprocess, 'run') as run, contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(helper.main([operation]), status)
                run.assert_not_called()
                self.assertEqual(out.getvalue(), output)

    def test_helper_errors_and_invalid_responses_are_redacted(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'registry': HOST, 'region': 'us-east-1'}))
            for response in ('offline-secret', '{}', json.dumps({'ServerURL': HOST + '.evil', 'Username': 'AWS', 'Secret': 'offline-secret'})):
                out, err = io.StringIO(), io.StringIO()
                with patch.object(helper, 'CONFIG_PATH', config), patch.object(sys, 'stdin', io.StringIO(HOST)), \
                     patch.object(helper.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, response, 'offline-secret')), \
                     contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(helper.main(['get']), 1)
                self.assertEqual(out.getvalue(), '')
                self.assertNotIn('offline-secret', err.getvalue())
            with patch.object(helper, 'CONFIG_PATH', config), patch.object(sys, 'stdin', io.StringIO(HOST)), \
                 patch.object(helper.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'helper', 'offline-secret', 'offline-secret')), \
                 contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(helper.main(['get']), 1)
                self.assertEqual(out.getvalue(), '')
                self.assertNotIn('offline-secret', err.getvalue())


class ConfigurationTests(unittest.TestCase):
    def module(self):
        path = ROLE / 'library/container_registry_docker_config.py'
        self.assertTrue(path.exists(), 'scoped Docker configuration module is missing')
        return load(path, 'docker_config')

    def test_ecr_merge_private_atomic_and_idempotent(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / '.docker').mkdir()
            path = home / '.docker/config.json'
            path.write_text(json.dumps({'credsStore': 'external', 'auths': {HOST: {'auth': 'stale'}, 'other': {'auth': 'keep'}}}))
            self.assertTrue(module.configure(home, os.getuid(), os.getgid(), HOST))
            result = json.loads(path.read_text())
            self.assertEqual(result, {'credsStore': 'external', 'auths': {'other': {'auth': 'keep'}},
                                      'credHelpers': {HOST: 'isaac-ecr'}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            before = path.stat().st_mtime_ns
            self.assertFalse(module.configure(home, os.getuid(), os.getgid(), HOST))
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_anonymous_isolated_empty_and_existing_read_only(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            docker = home / '.docker'
            docker.mkdir()
            original = docker / 'config.json'
            original.write_text('{"auths":{"docker.io":{"auth":"offline-secret"}},"credsStore":"external"}')
            before = (original.read_bytes(), original.stat().st_mode, original.stat().st_mtime_ns)
            self.assertTrue(module.configure(home, os.getuid(), os.getgid(), mode='anonymous'))
            isolated = home / '.docker-isaac-anonymous/config.json'
            self.assertEqual(json.loads(isolated.read_text()), {})
            self.assertFalse(module.configure(home, os.getuid(), os.getgid(), mode='anonymous'))
            self.assertFalse(module.configure(home, os.getuid(), os.getgid(), mode='existing'))
            self.assertEqual((original.read_bytes(), original.stat().st_mode, original.stat().st_mtime_ns), before)
            isolated.write_text('{"credsStore":"must-remove"}')
            self.assertTrue(module.configure(home, os.getuid(), os.getgid(), mode='anonymous'))
            self.assertEqual(json.loads(isolated.read_text()), {})

    def test_check_mode_symlinks_and_malformed_config_fail_closed(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.assertTrue(module.configure(home, os.getuid(), os.getgid(), HOST, check_mode=True))
            self.assertEqual(list(home.iterdir()), [])
            with self.assertRaises(ValueError):
                module.configure(home, os.getuid(), os.getgid(), mode='existing')
            (home / '.docker').mkdir()
            path = home / '.docker/config.json'
            for value in ('bad-json', '[]', '{"credHelpers":[]}'):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    module.configure(home, os.getuid(), os.getgid(), HOST)
                self.assertEqual(path.read_text(), value)
            path.unlink()
            victim = home / 'victim'
            victim.write_text('{}')
            path.symlink_to(victim)
            with self.assertRaises(ValueError):
                module.configure(home, os.getuid(), os.getgid(), HOST)
            self.assertEqual(victim.read_text(), '{}')

    @unittest.skipUnless(os.geteuid() == 0, 'real privilege drop needs root')
    def test_directory_swap_cannot_redirect_root_writes(self):
        import pwd
        account = pwd.getpwnam('nobody')
        script = r'''
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('config', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
home, victim = Path(sys.argv[2]), Path(sys.argv[3])
original = Path.mkdir
swapped = False
def mkdir(path, *args, **kwargs):
    global swapped
    result = original(path, *args, **kwargs)
    if path == home / '.docker':
        path.rename(home / 'parked')
        path.symlink_to(victim, target_is_directory=True)
        swapped = True
    return result
Path.mkdir = mkdir
try:
    module.configure(home, int(sys.argv[4]), int(sys.argv[5]), sys.argv[6])
except (OSError, ValueError):
    pass
try:
    os.setuid(0)
    regained = True
except PermissionError:
    regained = False
print(json.dumps([os.geteuid(), os.getegid(), os.getgroups(), swapped, regained]))
'''
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            sandbox.chmod(0o755)
            home, victim = sandbox / 'home', sandbox / 'root-only'
            home.mkdir()
            os.chown(home, account.pw_uid, account.pw_gid)
            victim.mkdir()
            target = victim / 'config.json'
            target.write_text('{"untouched":true}')
            before = (target.read_bytes(), target.stat().st_mode, victim.stat().st_mode)
            result = subprocess.run([sys.executable, '-c', script, str(ROLE / 'library/container_registry_docker_config.py'),
                str(home), str(victim), str(account.pw_uid), str(account.pw_gid), HOST], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [account.pw_uid, account.pw_gid, [], True, False])
            self.assertEqual((target.read_bytes(), target.stat().st_mode, victim.stat().st_mode), before)


# Reuse only the existing sandbox harness, never its test suite or production
# role mutations. Its fake service/template actions exercise real role flow.
legacy = load(Path(__file__).with_name('artifact_registry_ansible.test.py'), 'legacy_registry_tests')


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
class AnsibleTests(unittest.TestCase):
    play = legacy.AnsibleIntegrationTests.play

    def play_tagged(self, directory, tags, **kwargs):
        run = subprocess.run

        def tagged_run(args, **options):
            return run(args + ['--tags', tags], **options)

        with patch.object(legacy.subprocess, 'run', side_effect=tagged_run):
            return self.play(directory, **kwargs)

    def test_gr00t_tag_requires_registry_prerequisites_before_service_effects(self):
        for settings in (ecr(), hub(), dict(hub(), auth='existing')):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory:
                state = self.sandbox(directory)
                state.write_text(json.dumps({'services': {'isaac-gr00t.service': {
                    'state': 'running', 'status': 'enabled'}}, 'files': {}, 'calls': []}))
                before = state.read_text()
                result = self.play_tagged(directory, '__gr00t', roles=[
                    {'role': 'container-registry', 'tags': ['__container_registry']},
                    {'role': 'gr00t', 'tags': ['__gr00t']}], variables={
                        'mock_state': str(state), 'cloud': 'aws', 'container_registry_json': settings,
                        'ansible_user': 'offline-user'})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(state.read_text(), before, result.stdout + result.stderr)
                self.assertIn('--tags __container_registry,__gr00t', result.stdout)
                self.assertRegex(result.stdout, r'changed=0\s')

    def test_digest_cache_requires_exact_repository_and_digest(self):
        library = HUB.replace('/example/', '/library/')
        familiar = HUB.removeprefix('docker.io/')
        official = library.removeprefix('docker.io/library/')
        fixtures = [
            (HUB, [HUB], False), (HUB, [familiar], False),
            (library, [library], False), (library, [official], False),
            (IMAGE, [IMAGE], False),
            (HUB, [familiar.replace('example/', 'elsewhere/')], True),
            (HUB, [HUB.replace('/example/', '/elsewhere/')], True),
            (HUB, [official], True), (library, [familiar], True),
            (HUB, [familiar.replace('gr00t@', 'other@')], True),
            (HUB, [familiar.replace('b' * 64, 'c' * 64)], True),
            (HUB, ['evil.invalid/' + familiar], True),
            (HUB, [familiar + '\n'], True),
            (IMAGE, [IMAGE.split('/', 1)[1]], True),
            (HUB, [], True), (HUB, None, True),
        ]
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            fake, cached, trace = sandbox / 'docker', sandbox / 'cached.json', sandbox / 'pulls.jsonl'
            fake.write_text('#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\n'
                + 'if sys.argv[1:3]==["image","inspect"]:\n'
                + '    print(Path(' + repr(str(cached)) + ').read_text())\n'
                + 'elif sys.argv[1]=="pull":\n'
                + '    with open(' + repr(str(trace)) + ', "a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                + 'else: sys.exit(99)\n')
            fake.chmod(0o700)
            for image, repo_digests, should_pull in fixtures:
                with self.subTest(image=image, repo_digests=repo_digests):
                    cached.write_text(json.dumps(repo_digests))
                    trace.write_text('')
                    result = self.play(directory, tasks=[{'ansible.builtin.include_tasks': str(ROLE / 'tasks/pull.yml')}],
                        variables={'container_registry_validated': {'images': {'gr00t': image}},
                            'container_registry_docker_binary': str(fake),
                            'container_registry_root_docker_config': str(sandbox / 'unused-config')})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(list(map(json.loads, trace.read_text().splitlines())),
                        [['pull', image]] if should_pull else [])
                    self.assertRegex(result.stdout, r'changed=' + str(int(should_pull)) + r'\s')

    def test_generic_digest_and_provider_transitions_restart_only_container(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.sandbox(directory)
            variables = {'mock_state': str(state), 'ansible_user': 'offline-user',
                         'install_gr00t': False, 'gr00t_service_enabled': False, 'gr00t_serving_mode': 'native'}
            # Changing auth config must restart too, even with an identical image.
            selections = [(ecr(), '/offline/.docker', 1), (ecr(), '/offline/.docker', 1),
                          (hub(), '/offline/.docker-isaac-anonymous', 2),
                          (dict(hub(), auth='existing'), '/offline/.docker', 3)]
            for settings, docker_config, restarts in selections:
                variables.update(container_registry_validated=settings, container_registry_root_docker_config=docker_config)
                result = self.play(directory, roles=['gr00t'], variables=variables)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                actual = json.loads(state.read_text())
                calls = [call for call in actual['calls'] if call['operation'] == 'systemd' and call['arguments'].get('state') == 'restarted']
                self.assertEqual([call['arguments']['name'] for call in calls], ['isaac-gr00t-container'] * restarts)
                unit = actual['files']['/etc/systemd/system/isaac-gr00t-container.service']
                self.assertIn(docker_config, unit)
                self.assertIn(settings['images']['gr00t'], unit)
            variables.update(container_registry_validated={'enabled': False}, install_gr00t=True)
            result = self.play(directory, roles=['gr00t'], variables=variables)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = json.loads(state.read_text())
            self.assertEqual(actual['services']['isaac-gr00t-container.service'], {'state': 'stopped', 'status': 'disabled'})
            self.assertEqual(actual['calls'][-1]['operation'], 'native')

    def test_disabled_or_cache_only_generic_images_leave_services_untouched(self):
        for settings in ({'enabled': False}, dict(hub(), images={'cache': HUB})):
            with tempfile.TemporaryDirectory() as directory:
                state = self.sandbox(directory)
                original = state.read_text()
                result = self.play(directory, roles=['gr00t'], variables={'mock_state': str(state),
                    'container_registry_validated': settings, 'install_gr00t': False})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r'changed=0\s')
                self.assertEqual(state.read_text(), original)

    def test_role_syntax_and_default_disabled_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.play(directory, roles=['container-registry', 'gr00t'])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertRegex(result.stdout, r'changed=0\s')
            env = dict(os.environ, ANSIBLE_ROLES_PATH=str(ROOT / 'roles'),
                       ANSIBLE_CONFIG=str(Path(directory) / 'ansible.cfg'),
                       ANSIBLE_LOCAL_TEMP=str(Path(directory) / 'local'))
            syntax = subprocess.run(['ansible-playbook', '--syntax-check', '-i', 'localhost,', str(Path(directory) / 'play.yml')],
                                    env=env, cwd=directory, text=True, capture_output=True, timeout=30)
            self.assertEqual(syntax.returncode, 0, syntax.stdout + syntax.stderr)

    def sandbox(self, directory):
        state = legacy.AnsibleIntegrationTests.mock_service_roles(self, directory)
        target = Path(directory) / 'roles/container-registry'
        shutil.copytree(ROLE, target)
        for path in (target / 'tasks').glob('*.yml'):
            tasks = yaml.safe_load(path.read_text())
            for task in tasks:
                for action in ('getent', 'file', 'copy', 'apt'):
                    key = 'ansible.builtin.' + action
                    if key in task:
                        task['mock_host'] = {'operation': action, 'arguments': task.pop(key)}
                allowed = {'name', 'when', 'mock_host', 'ansible.builtin.set_fact', 'ansible.builtin.include_tasks',
                           'ansible.builtin.assert', 'ansible.builtin.command', 'container_registry_docker_config',
                           'loop', 'loop_control', 'register', 'environment', 'changed_when', 'failed_when',
                           'check_mode', 'no_log', 'diff', 'tags'}
                self.assertFalse(set(task) - allowed, task)
            path.write_text(yaml.safe_dump(tasks))
        plugin = Path(directory) / 'action_plugins/mock_host.py'
        plugin.write_text(plugin.read_text().replace("elif op != 'systemd':", "elif op not in ('systemd', 'apt'):"))
        return state

    def test_disabled_and_gcp_role_are_noops_invalid_input_fails_before_host(self):
        self.assertTrue((ROLE / 'tasks/main.yml').exists(), 'container-registry role missing')
        gcp = dict(enabled=True, provider='gcp_artifact_registry', project='test-project',
                   location='us-central1', repository='workloads', images={})
        with tempfile.TemporaryDirectory() as directory:
            for value, cloud, legacy_enabled, status in [({}, 'aws', False, 0), ({'enabled': False}, 'gcp', False, 0),
                (gcp, 'gcp', True, 0), (dict(ecr(), password='secret'), 'aws', False, 2),
                (ecr(), 'azure', False, 2), (ecr(), 'aws', True, 2)]:
                with self.subTest(value=value, legacy_enabled=legacy_enabled):
                    result = self.play(directory, roles=['container-registry'], variables={
                        'container_registry_json': json.dumps(value), 'cloud': cloud, 'from_image': True,
                        'enable_artifact_registry': legacy_enabled, 'artifact_registry_project': 'test-project',
                        'artifact_registry_location': 'us-central1', 'artifact_registry_repository': 'workloads'})
                    self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                    self.assertRegex(result.stdout, r'changed=0\s')

    def test_role_order_rejects_conflicts_before_legacy_setup(self):
        dependencies = yaml.safe_load((ROOT / 'roles/isaac-workstation/meta/main.yml').read_text())['dependencies']
        roles = [item['role'] for item in dependencies]
        self.assertIn('container-registry', roles)
        self.assertLess(roles.index('system'), roles.index('container-registry'))
        self.assertLess(roles.index('container-registry'), roles.index('artifact-registry'))

    def test_conflicting_raw_registry_vars_never_reach_either_host_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.sandbox(directory)
            before = state.read_text()
            result = self.play(directory, roles=['container-registry', 'artifact-registry'], variables={
                'mock_state': str(state), 'container_registry_json': hub(), 'cloud': 'gcp',
                'enable_artifact_registry': True, 'artifact_registry_project': 'test-project',
                'artifact_registry_location': 'us-central1', 'artifact_registry_repository': 'workloads',
                'artifact_registry_images_json': '{}'})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('cannot coexist', result.stdout)
            self.assertRegex(result.stdout, r'changed=0\s')
            self.assertEqual(state.read_text(), before)

    def test_gcp_requires_matching_legacy_transport_before_setup(self):
        gcp_image = 'us-central1-docker.pkg.dev/test-project/workloads/gr00t@sha256:' + 'a' * 64
        gcp = dict(enabled=True, provider='gcp_artifact_registry', project='test-project',
                   location='us-central1', repository='workloads', images={'gr00t': gcp_image})
        with tempfile.TemporaryDirectory() as directory:
            base = {'cloud': 'gcp', 'container_registry_json': gcp, 'enable_artifact_registry': True,
                    'artifact_registry_project': 'test-project', 'artifact_registry_location': 'us-central1',
                    'artifact_registry_repository': 'workloads', 'artifact_registry_images_json': json.dumps(gcp['images'])}
            for key, wrong in [('enable_artifact_registry', False), ('artifact_registry_project', 'other-project'),
                               ('artifact_registry_location', 'us-east1'), ('artifact_registry_repository', 'other'),
                               ('artifact_registry_images_json', '{}')]:
                result = self.play(directory, roles=['container-registry'], variables=dict(base, **{key: wrong}))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r'changed=0\s')
            for images in (gcp['images'], json.dumps(gcp['images'])):
                result = self.play(directory, roles=['container-registry'], variables=dict(base, artifact_registry_images_json=images))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_tag_cannot_skip_conflict_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.sandbox(directory)
            before = state.read_text()
            roles = [{'role': 'container-registry', 'tags': ['__container_registry']},
                     {'role': 'artifact-registry', 'tags': ['__artifact_registry']}]
            variables = {'mock_state': str(state), 'cloud': 'gcp', 'container_registry_json': hub(),
                         'enable_artifact_registry': True, 'artifact_registry_project': 'test-project',
                         'artifact_registry_location': 'us-central1', 'artifact_registry_repository': 'workloads'}
            self.play(directory, roles=roles, variables=variables)
            env = dict(os.environ, ANSIBLE_ROLES_PATH=str(Path(directory) / 'roles'),
                       ANSIBLE_ACTION_PLUGINS=str(Path(directory) / 'action_plugins'),
                       ANSIBLE_CONFIG=str(Path(directory) / 'ansible.cfg'),
                       ANSIBLE_LOCAL_TEMP=str(Path(directory) / 'local'), ANSIBLE_REMOTE_TEMP=str(Path(directory) / 'remote'))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local',
                '--tags', '__artifact_registry', str(Path(directory) / 'play.yml')],
                env=env, cwd=directory, text=True, capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('cannot coexist', result.stdout)
            self.assertEqual(state.read_text(), before)

    @unittest.skipUnless(os.geteuid() == 0, 'real privilege drop needs root')
    def test_enabled_from_image_real_modules_and_fake_pulls(self):
        import pwd
        sys.path.insert(0, str(ROOT.parents[1]))
        from src.python.config import c
        from src.python.deployer import Deployer
        account = pwd.getpwnam('nobody')
        self.assertTrue((ROLE / 'tasks/main.yml').exists(), 'container-registry role missing')
        library = dict(hub(), namespace='library', images={'gr00t': HUB.replace('/example/', '/library/')})
        for settings in (ecr(), hub(), dict(hub(), auth='existing'), library, dict(library, auth='existing')):
            with self.subTest(provider=settings['provider'], namespace=settings.get('namespace'), auth=settings.get('auth')), tempfile.TemporaryDirectory() as directory:
                sandbox = Path(directory)
                sandbox.chmod(0o755)
                state = self.sandbox(directory)
                state.write_text(json.dumps({'services': {'isaac-gr00t.service': {'state': 'running', 'status': 'enabled'}}, 'files': {}, 'calls': []}))
                accounts = {}
                for user, uid, gid in (('root', 0, 0), (account.pw_name, account.pw_uid, account.pw_gid)):
                    home = sandbox / (user + '-home')
                    home.mkdir(mode=0o700)
                    os.chown(home, uid, gid)
                    accounts[user] = ['x', str(uid), str(gid), '', str(home), '/bin/sh']
                root_home = Path(accounts['root'][4])
                (root_home / '.docker').mkdir()
                original = root_home / '.docker/config.json'
                original.write_text('{"auths":{"docker.io":{"auth":"offline-secret"}},"credsStore":"existing"}')
                fake, pulled, trace = sandbox / 'docker', sandbox / 'pulled.json', sandbox / 'docker.jsonl'
                fake.write_text('#!/usr/bin/python3\nimport json,sys,os\nfrom pathlib import Path\n'
                    + 'state=Path(' + repr(str(pulled)) + ')\n'
                    + 'with open(' + repr(str(trace)) + ', "a") as f: f.write(json.dumps([sys.argv[1:], os.environ["DOCKER_CONFIG"]])+"\\n")\n'
                    + 'if sys.argv[1:3]==["image","inspect"]:\n'
                    + '    if not state.exists(): sys.exit(1)\n'
                    + '    print(state.read_text())\n'
                    + 'elif sys.argv[1]=="pull":\n'
                    # Docker Engine uses FamiliarString for Docker Hub RepoDigests.
                    + '    image=sys.argv[2]\n'
                    + '    if image.startswith("docker.io/"): image=image.removeprefix("docker.io/").removeprefix("library/")\n'
                    + '    state.write_text(json.dumps([image]))\n'
                    + 'else: sys.exit(99)\n')
                fake.chmod(0o700)
                variables = {'mock_state': str(state), 'mock_accounts': accounts, 'from_image': True,
                    'cloud': 'aws', 'ansible_user': account.pw_name, 'ansible_python_interpreter': sys.executable,
                    'ansible_become': False,
                    'container_registry_json': settings, 'container_registry_docker_binary': str(fake),
                    'install_gr00t': False, 'gr00t_service_enabled': False, 'gr00t_serving_mode': 'native'}
                inventory = sandbox / 'inventory'
                profile = sandbox / 'profile.yaml'
                profile.write_text(yaml.safe_dump({'profile_name': 'offline-registry', 'cloud': 'aws',
                    'security': {'tier': 'custom'}, 'container_registry': settings}))
                params = {'debug': False, 'cloud': 'aws', 'prefix': 'isa', 'deployment_name': 'offline-registry',
                    'existing': 'modify', 'in_china': 'no', 'ssh_port': 22, 'ingress_cidrs': '192.0.2.1/32',
                    'vnc_password': 'test-only', 'system_user_password': 'test-only', 'isaacsim': 'no',
                    'isaaclab': 'no', 'isaaclab_arena': 'no', 'isaaclab_private_git': False, 'demos': 'no',
                    'isaac_workstation_ip': 'localhost', 'profile': str(profile)}
                deployer = Deployer(params, dict(c, state_dir=str(sandbox / 'deployment-state'), default_ssh_user=account.pw_name))
                inventory.write_text(deployer.create_ansible_inventory(write=False))
                del deployer
                # Exercise decoded mapping, actual INI JSON transport, and a fresh
                # combined-tag invocation (set_fact values do not persist).
                roles = [{'role': 'container-registry', 'tags': ['__container_registry']},
                         {'role': 'gr00t', 'tags': ['__gr00t']}]
                for iteration in range(3):
                    if iteration:
                        variables.pop('container_registry_json', None)
                    if iteration == 2:
                        result = self.play_tagged(directory, '__container_registry,__gr00t',
                            roles=roles, variables=variables, inventory=inventory)
                    else:
                        result = self.play(directory, roles=roles, variables=variables, inventory=inventory)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertNotIn('offline-secret', result.stdout)
                    if iteration:
                        self.assertRegex(result.stdout, r'changed=0\s')
                actual = json.loads(state.read_text())
                unit = actual['files']['/etc/systemd/system/isaac-gr00t-container.service']
                image = settings['images']['gr00t']
                config = root_home / ('.docker-isaac-anonymous' if settings['provider'] == 'dockerhub' and settings.get('auth') != 'existing' else '.docker')
                self.assertIn('Environment="DOCKER_CONFIG=' + str(config) + '"', unit)
                self.assertIn(image, unit)
                self.assertNotIn('native', [call['operation'] for call in actual['calls']])
                self.assertEqual(actual['services']['isaac-gr00t.service'], {'state': 'stopped', 'status': 'disabled'})
                calls = list(map(json.loads, trace.read_text().splitlines()))
                self.assertEqual([args for args, _ in calls if args[0] == 'pull'], [['pull', image]])
                self.assertEqual(sum(args[:2] == ['image', 'inspect'] for args, _ in calls), 3)
                self.assertTrue(all(path == str(config) for _, path in calls))
                if settings['provider'] == 'aws_ecr':
                    self.assertTrue(any(call['operation'] == 'apt' and call['arguments']['name'] == 'amazon-ecr-credential-helper' for call in actual['calls']))
                    for entry in accounts.values():
                        path = Path(entry[4]) / '.docker/config.json'
                        self.assertEqual(json.loads(path.read_text())['credHelpers'][HOST], 'isaac-ecr')
                        self.assertEqual(path.stat().st_uid, int(entry[1]))
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                else:
                    self.assertIn('offline-secret', original.read_text())
                    self.assertFalse(any(call['operation'] == 'apt' for call in actual['calls']))
                    if settings.get('auth') != 'existing':
                        self.assertEqual(json.loads((config / 'config.json').read_text()), {})


if __name__ == '__main__':
    unittest.main()
