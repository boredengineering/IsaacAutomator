"""Lifecycle integration against disposable metadata; no cloud or real state."""
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from click.testing import CliRunner
from src.python.config import c


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'fixture'
        self.directory.mkdir()
        (self.directory / 'info.txt').write_text('Synthetic workstation')
        self.patch = mock.patch.dict(c, state_dir=str(self.root), app_dir=str(self.root),
                                     terraform_dir=str(self.root / 'terraform'))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.spawn = mock.patch('subprocess.Popen', side_effect=AssertionError('No real processes'))
        self.spawn.start()
        self.addCleanup(self.spawn.stop)
        self.meta: dict[str, Any] = {'params': {'project': 'target-project', 'zone': 'us-central1-a'}}
        self.outputs = {'cloud': 'gcp', 'isaac_workstation_vm_id':
                        'projects/target-project/zones/us-central1-a/instances/fixture-vm',
                        'isaac_workstation_ip': '192.0.2.10'}

    def load(self, name) -> Any:
        loader = importlib.machinery.SourceFileLoader('lifecycle_' + name,
                    str(Path(__file__).resolve().parents[2] / name))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        command: Any = importlib.util.module_from_spec(spec)
        with mock.patch('src.python.utils.deployments', return_value=['fixture']):
            loader.exec_module(command)
        command.read_meta = mock.Mock(side_effect=lambda *a, **k: self.meta)
        command.read_tf_output = mock.Mock(side_effect=lambda name, key, **k: self.outputs[key])
        command.gcp_login = mock.Mock()
        command.shell_command = mock.Mock()
        return command

    def remote_fixture(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        self.meta = {'params': {'project': 'target-project', 'zone': 'us-central1-a',
            'cloud': 'gcp', 'deployment_name': 'fixture', 'state_backend': 'gcs',
            'terraform_state': spec.to_dict(), 'backend_runtime': {
                'identity': spec.identity('target-project', 'fixture'),
                'status': 'active', 'lineage': 'synthetic-lineage'}}}
        (self.directory / 'meta.json').write_text(json.dumps(self.meta))
        (self.directory / '.tfvars').write_text('# Synthetic inputs\n')
        state = {'version': 4, 'serial': 4, 'lineage': 'synthetic-lineage', 'outputs': {},
                 'resources': [{'mode': 'managed', 'instances': [{'attributes': {'id': 'fixture-vm'}}]}]}
        return state

    def test_gcs_destroy_pulls_plans_applies_verifies_then_cleans_under_lock(self):
        before = self.remote_fixture()
        after = dict(before, serial=5, resources=[])
        command = self.load('destroy')
        runner = mock.Mock()
        runner.pull_state.side_effect = [before, after]
        runner.recovery_directory = None
        runner.assert_no_recovery = mock.Mock()
        context = mock.MagicMock()
        context.__enter__.return_value = runner
        events = []
        runner.attach_mock(mock.Mock(side_effect=lambda: events.append('clean')), 'assert_no_recovery')
        def unlock(*args):
            self.assertFalse(self.directory.exists(), 'cleanup must precede unlock')
            self.assertEqual(events, ['clean'])
        context.__exit__.side_effect = unlock
        from src.python import backend_runtime
        with mock.patch.object(backend_runtime, 'record_runner', return_value=context) as factory:
            result = CliRunner().invoke(command.main, ['fixture', '--yes'])
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        self.assertFalse((self.directory / '.tfstate').exists())
        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[0].target_scope, 'target-project')
        self.assertEqual(runner.method_calls, [mock.call.init(), mock.call.pull_state(),
            mock.call.plan(destroy=True), mock.call.apply(runner.plan.return_value, acknowledge_mutation=True),
            mock.call.pull_state(), mock.call.assert_no_recovery()])
        command.gcp_login.assert_not_called()  # native backend ADC, no account switching

    def test_gcs_destroy_refuses_unconfirmed_or_different_saved_lineage(self):
        from src.python import backend_runtime
        for status, lineage in [('configured', 'synthetic-lineage'), ('active', 'other-owner')]:
            with self.subTest(status=status, lineage=lineage):
                before = self.remote_fixture()
                self.meta['params']['backend_runtime']['status'] = status
                (self.directory / 'meta.json').write_text(json.dumps(self.meta))
                command = self.load('destroy')
                runner = mock.Mock(recovery_directory=None)
                runner.pull_state.return_value = dict(before, lineage=lineage, resources=[])
                context = mock.MagicMock()
                context.__enter__.return_value = runner
                with mock.patch.object(backend_runtime, 'record_runner', return_value=context):
                    result = CliRunner().invoke(command.main, ['fixture', '--yes'])
                self.assertNotEqual(result.exit_code, 0)
                runner.plan.assert_not_called()
                runner.apply.assert_not_called()
                self.assertTrue(self.directory.exists())

    def test_gcs_repair_uses_saved_plan_not_local_backend_shell(self):
        from src.python import backend_runtime
        before = self.remote_fixture()
        command = self.load('repair')
        runner = mock.Mock()
        runner.recovery_directory = None
        runner.assert_no_recovery = mock.Mock()
        runner.pull_state.side_effect = [before, dict(before, serial=5)]
        context = mock.MagicMock()
        context.__enter__.return_value = runner
        with mock.patch.object(backend_runtime, 'record_runner', return_value=context):
            result = CliRunner().invoke(command.main, ['fixture', '--no-ansible'])
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        runner.init.assert_called_once_with()
        runner.plan.assert_called_once_with()
        runner.apply.assert_called_once_with(runner.plan.return_value, acknowledge_mutation=True)
        self.assertEqual(runner.pull_state.call_count, 2)
        runner.assert_no_recovery.assert_called_once_with()
        command.shell_command.assert_not_called()
        self.assertTrue(self.directory.exists())

    def test_ssh_iap_uses_shared_endpoint_without_a_public_ip(self):
        self.remote_fixture()
        self.meta['params']['enable_iap_only'] = True
        self.meta['params']['enable_oslogin'] = False
        self.outputs['isaac_workstation_ip'] = ''
        command = self.load('ssh')
        with mock.patch('src.python.utils.deployments', return_value=['fixture']), \
                mock.patch('subprocess.run', return_value=mock.Mock(returncode=0)) as execute:
            result = CliRunner().invoke(command.main, ['fixture'])
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        execute.assert_called_once()
        argv = execute.call_args.args[0]
        self.assertEqual(argv[-1], c['default_ssh_user'] + '@fixture-vm')
        proxy = next(arg for arg in argv if arg.startswith('ProxyCommand='))
        self.assertIn('--project=target-project', proxy)
        self.assertIn('--zone=us-central1-a', proxy)
        self.assertIn('--listen-on-stdin', proxy)
        self.assertIn('StrictHostKeyChecking=accept-new', argv)
        command.shell_command.assert_not_called()

    def test_destroy_preserves_new_reconciliation_marker_after_apply(self):
        from src.python import backend_runtime
        before = self.remote_fixture()
        command = self.load('destroy')
        runner = mock.Mock()
        runner.recovery_directory = None
        runner.assert_no_recovery = mock.Mock()
        runner.pull_state.side_effect = [before, dict(before, resources=[], serial=5)]
        runner.apply.side_effect = lambda *a, **k: (self.directory / 'migration.json').write_text('{}')
        context = mock.MagicMock()
        context.__enter__.return_value = runner
        with mock.patch.object(backend_runtime, 'record_runner', return_value=context):
            result = CliRunner().invoke(command.main, ['fixture', '--yes'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue((self.directory / 'migration.json').exists())

    def test_native_runner_destroy_boundaries_with_synthetic_transport(self):
        """Exercise actual staging, guards, saved plans and state validation."""
        from src.python import backend_runtime
        from src.python.terraform_runner import TerraformRunner, TerraformRunnerError
        for failure in (None, 'auth', 'apply', 'lineage', 'serial', 'resources', 'malformed', 'recovery', 'dryrun'):
            with self.subTest(failure=failure):
                self.directory.mkdir(exist_ok=True)
                before = self.remote_fixture()
                (self.directory / '.tfstate').write_text('STALE LOCAL SNAPSHOT MUST NOT BE READ')
                source = self.root / 'terraform/gcp'
                source.mkdir(parents=True, exist_ok=True)
                (source / 'main.tf').write_text('terraform {}\n')
                record = backend_runtime.load_backend_record('fixture', state_root=self.root)
                commands = []
                applied = False
                created = []
                def transport(run, argv, **kwargs):
                    nonlocal applied
                    commands.append(argv)
                    if argv[0] == 'version':
                        return 0, b'{"terraform_version":"1.10.5"}'
                    if argv[0] == 'init':
                        (run.data_dir / 'terraform.tfstate').write_text(json.dumps({
                            'backend': {'type': 'gcs', 'config': run._config}}))
                    elif argv[0] == 'plan':
                        Path(next(a[5:] for a in argv if a.startswith('-out='))).write_bytes(b'SYNTHETIC SAVED PLAN')
                        self.assertIn('-destroy', argv)
                        return 2, b''
                    elif argv[0] == 'apply':
                        self.assertTrue(argv[-1].startswith('/proc/self/fd/'))
                        self.assertEqual(Path(argv[-1]).read_bytes(), b'SYNTHETIC SAVED PLAN')
                        if failure == 'apply':
                            raise TerraformRunnerError('Synthetic failed apply')
                        applied = True
                        if failure == 'recovery':
                            (run.staged_root / 'errored.tfstate').write_text('SYNTHETIC RECOVERY')
                    elif argv == ['state', 'pull']:
                        state = dict(before)
                        if applied:
                            state.update(serial=5, resources=[])
                            if failure == 'lineage': state['lineage'] = 'different-owner'
                            if failure == 'serial': state['serial'] = 1
                            if failure == 'resources': state['resources'] = before['resources']
                            if failure == 'malformed': state['resources'] = [{}]
                        return 0, json.dumps(state).encode()
                    else:
                        self.assertIn(argv[0], ('version', 'init', 'plan', 'apply', 'state'))
                    return 0, b''
                def construct(**kwargs):
                    run = TerraformRunner(**kwargs, lock_root=self.root / 'locks')
                    created.append(run)
                    return run
                command = self.load('destroy')
                with mock.patch.object(backend_runtime, 'TerraformRunner', side_effect=construct), \
                        mock.patch.object(backend_runtime, 'workstation_source_files', return_value=['main.tf']), \
                        mock.patch.object(backend_runtime, 'gcs_object_names', return_value={record.identity['object_key']},
                            side_effect=TerraformRunnerError('Synthetic auth denied') if failure == 'auth' else None), \
                        mock.patch.object(TerraformRunner, '_execute', transport):
                    result = CliRunner().invoke(command.main, ['fixture', '--yes'] + (['--dryrun'] if failure == 'dryrun' else []))
                if failure in (None, 'dryrun'):
                    self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                else:
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertNotIn('destroyed;', result.output)
                self.assertEqual(self.directory.exists(), failure is not None)
                if failure in ('auth', 'dryrun'):
                    self.assertFalse(applied)
                if failure == 'recovery':
                    import shutil
                    self.assertIsNotNone(created[0].recovery_directory)
                    self.addCleanup(shutil.rmtree, created[0].recovery_directory, ignore_errors=True)
                for argv in commands:
                    self.assertNotIn('destroy', argv)
                    self.assertNotIn('-lock=false', argv)

    def test_output_consumers_use_gcs_and_never_fallback_on_auth_failure(self):
        from src.python import backend_runtime, utils
        from src.python.terraform_runner import TerraformRunnerError
        import os
        for script in ('start', 'stop', 'ssh', 'novnc', 'repair'):
            for failure in (False, True):
                with self.subTest(script=script, failure=failure):
                    self.remote_fixture()
                    self.meta['input_params'] = {'vnc_password': 'synthetic'}
                    (self.directory / 'key.pem').write_text('SYNTHETIC KEY FIXTURE')
                    (self.directory / '.tfstate').write_text('STALE LOCAL SNAPSHOT')
                    command = self.load(script)
                    command.read_tf_output = utils.read_tf_output
                    command.gcp_start_instance = mock.Mock()
                    command.gcp_stop_instance = mock.Mock()
                    command.gcp_get_instance_status = mock.Mock(return_value='RUNNING' if script == 'start' else 'TERMINATED')
                    runner = mock.Mock()
                    runner.output.return_value = {key: {'value': value} for key, value in self.outputs.items()}
                    runner.init.side_effect = TerraformRunnerError('Synthetic auth denied') if failure else None
                    context = mock.MagicMock()
                    context.__enter__.return_value = runner
                    original_exists = os.path.exists
                    with mock.patch.object(backend_runtime, 'record_runner', return_value=context) as factory, \
                            mock.patch.object(utils, 'read_local_tfstate', side_effect=AssertionError('No local fallback')), \
                            mock.patch.object(utils, 'deployments', return_value=['fixture']), \
                            mock.patch('subprocess.run', return_value=mock.Mock(returncode=0)) as execute, \
                            mock.patch.object(os.path, 'exists', side_effect=lambda p: False if p == '/.dockerenv' else original_exists(p)):
                        args = ['fixture'] + (['--no-terraform', '--no-ansible'] if script == 'repair' else [])
                        result = CliRunner().invoke(command.main, args)
                    if failure:
                        self.assertNotEqual(result.exit_code, 0)
                        command.shell_command.assert_not_called()
                        command.gcp_start_instance.assert_not_called()
                        command.gcp_stop_instance.assert_not_called()
                        execute.assert_not_called()
                    else:
                        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                        self.assertTrue(factory.called)
                        self.assertTrue(all(call.kwargs['read_only'] for call in factory.call_args_list))
                        if script in ('start', 'stop'):
                            getattr(command, 'gcp_' + script + '_instance').assert_called_once_with(
                                'fixture-vm', zone='us-central1-a', project='target-project', verbose=False)

    def test_all_consumers_preserve_protected_reconciliation_records(self):
        from src.python import backend_runtime, utils
        for script in ('destroy', 'start', 'stop', 'ssh', 'novnc', 'repair'):
            for marker in ('migration.json', 'relocation.json', 'backend.json'):
                with self.subTest(script=script, marker=marker):
                    self.remote_fixture()
                    path = self.directory / marker
                    path.write_text('{}')
                    command = self.load(script)
                    command.read_tf_output = utils.read_tf_output
                    with mock.patch.object(backend_runtime, 'record_runner') as factory, \
                            mock.patch.object(utils, 'deployments', return_value=['fixture']):
                        result = CliRunner().invoke(command.main, ['fixture'] + (['--yes'] if script == 'destroy' else []))
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertTrue(path.exists())
                    factory.assert_not_called()
                    command.shell_command.assert_not_called()
                    command.gcp_login.assert_not_called()
                    path.unlink()

    def test_ssh_oslogin_uses_discovered_identity_and_propagates_exit(self):
        self.remote_fixture()
        self.meta['params'].update(enable_iap_only=True, enable_oslogin=True)
        self.outputs['isaac_workstation_ip'] = ''
        command = self.load('ssh')
        key = self.root / 'oslogin-key'
        with mock.patch('src.python.utils.deployments', return_value=['fixture']), \
                mock.patch('subprocess.run', side_effect=[
                    mock.Mock(returncode=0, stdout=f'ssh -i {key} principal@fixture-vm'),
                    mock.Mock(returncode=23)]) as execute:
            result = CliRunner().invoke(command.main, ['fixture'])
        self.assertEqual(result.exit_code, 23)
        discovery, connect = [call.args[0] for call in execute.call_args_list]
        self.assertIn('--dry-run', discovery)
        self.assertIn('--tunnel-through-iap', discovery)
        self.assertIn('--project=target-project', discovery)
        self.assertIn('--zone=us-central1-a', discovery)
        self.assertEqual(connect[-1], 'principal@fixture-vm')
        self.assertEqual(connect[connect.index('-i') + 1], str(key))
        self.assertIn('StrictHostKeyChecking=accept-new', connect)

    def test_start_stop_require_authoritative_id_matching_saved_scope(self):
        valid = 'projects/target-project/zones/us-central1-a/instances/fixture-vm'
        cases = [('', False), (None, False), ('NA', False), ('not/a/vm', False),
                 (valid.replace('target-project', 'other-project'), False),
                 (valid.replace('us-central1-a', 'us-east1-b'), False),
                 ('https://untrusted.example/compute/v1/' + valid, False),
                 (valid + '/', False), ('fixture-vm;touch unsafe', False),
                 ('fixture-', False), ('a' * 64, False), ('fixture-vm', True),
                 (valid, True), ('https://www.googleapis.com/compute/v1/' + valid, True)]
        for script in ('start', 'stop'):
            for vm_id, accepted in cases:
                with self.subTest(script=script, vm_id=vm_id):
                    self.remote_fixture()
                    self.outputs['isaac_workstation_vm_id'] = vm_id
                    before = (self.directory / 'meta.json').read_bytes()
                    command = self.load(script)
                    action = mock.Mock()
                    setattr(command, 'gcp_' + script + '_instance', action)
                    command.gcp_get_instance_status = mock.Mock(
                        return_value='RUNNING' if script == 'start' else 'TERMINATED')
                    result = CliRunner().invoke(command.main, ['fixture'])
                    if accepted:
                        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                        action.assert_called_once_with('fixture-vm', project='target-project',
                                                       zone='us-central1-a', verbose=False)
                    else:
                        self.assertNotEqual(result.exit_code, 0)
                        self.assertIn('VM ID', result.output)
                        action.assert_not_called()
                        command.gcp_get_instance_status.assert_not_called()
                        command.gcp_login.assert_not_called()
                        command.shell_command.assert_not_called()
                    self.assertEqual((self.directory / 'meta.json').read_bytes(), before)

    def test_start_stop_refuse_missing_explicit_gcp_scope(self):
        for script in ('start', 'stop'):
            for field in ('project', 'zone'):
                with self.subTest(script=script, field=field):
                    self.meta = {'params': {'project': 'target-project', 'zone': 'us-central1-a'}}
                    del self.meta['params'][field]
                    command = self.load(script)
                    action = mock.Mock()
                    setattr(command, 'gcp_' + script + '_instance', action)
                    command.gcp_get_instance_status = mock.Mock(return_value='RUNNING' if script == 'start' else 'TERMINATED')
                    result = CliRunner().invoke(command.main, ['fixture'])
                    self.assertNotEqual(result.exit_code, 0)
                    action.assert_not_called()
                    self.assertIn('project and zone', result.output)


if __name__ == '__main__':
    unittest.main()
