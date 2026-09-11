"""Local runtime bridge: temporary fixtures only; no cloud credentials."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


def configuration(root):
    return dict(schema_version=1, deployment='fixture', cloud='aws',
                backend_config={'backend': 'local'}, target_scope=None,
                state_root=str(root / 'state'), local_state_path=str(root / 'state/fixture/.tfstate'),
                baseline_store=str(root / 'baselines'), baseline_ref=None,
                expected_lineage='00000000-0000-0000-0000-000000000001', expected_serial=1,
                scope='workstation_infrastructure',
                drift={'enabled': True, 'scopes': ['workstation_infrastructure']})


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.drift_runtime'),
                             'actual drift runtime bridge is missing')
        from src.python import drift_runtime
        return drift_runtime

    def test_strict_config_is_nonsecret_and_does_not_accept_ready_attestations(self):
        api = self.api()
        raw = configuration(self.root)
        config = api.RuntimeConfig.from_dict(raw)
        self.assertEqual(config.local_state_path, self.root / 'state/fixture/.tfstate')
        for changes in ({'ready': True}, {'credentials': 'PRIVATE_CANARY'},
                        {'schema_version': True}, {'state_root': '../state'},
                        {'expected_serial': True}, {'baseline_ref': 'latest'},
                        {'local_state_path': str(self.root / 'other/fixture/.tfstate')},
                        {'drift': {'enabled': True, 'scopes': ['runtime']}}):
            with self.subTest(changes=changes), self.assertRaises(api.RuntimeConfigError) as error:
                api.RuntimeConfig.from_dict({**raw, **changes})
            self.assertNotIn('PRIVATE_CANARY', str(error.exception))

    def test_missing_baseline_is_partial_without_terraform_or_store_creation(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'check'), 'runtime check is missing')
        with mock.patch('src.python.terraform_runner.TerraformRunner.init') as init:
            report = api.check(api.RuntimeConfig.from_dict(configuration(self.root)))
        init.assert_not_called()
        self.assertEqual(report['classes'], ['partial'])
        self.assertFalse((self.root / 'baselines').exists())
        self.assertFalse((self.root / 'state').exists())

    def applied_fixture(self, dependency_declaration=False, module=False):
        import hashlib
        import time
        from src.python.deployment_baseline import prepare, BaselineStore
        from src.python.terraform_backend import BackendSpec
        from src.python.terraform_runner import TerraformRunner
        source = self.root / 'checkout'
        source.mkdir()
        observed = self.root / 'observed'
        observed.write_text('ORIGINAL_PRIVATE_VALUE')
        code = b'variable "observed" { type = string }\noutput "observed" { value = filesha256(var.observed) }\n'
        if dependency_declaration:
            code += b'terraform {\n required_providers {}\n}\n'
        lock = None
        sources = {}
        if module:
            code += b'module "child" { source = "./child" }\n'
            (source / 'child').mkdir()
            sources['child/main.tf'] = b'output "value" { value = "local" }\n'
            (source / 'child/main.tf').write_bytes(sources['child/main.tf'])
            lock = self.root / 'approved.lock'
            lock.write_text('# Empty provider-free lock\n')
        sources['main.tf'] = code
        (source / 'main.tf').write_bytes(code)
        inputs = self.root / 'input.tfvars.json'
        inputs.write_text(json.dumps({'observed': str(observed)}))
        revision = hashlib.sha256(code).hexdigest()
        prepared = prepare(source_root=source, source_files=tuple(sources), variables_file=inputs,
                           provider_lockfile=lock, source_revision=revision,
                           verify_source=lambda rev, files: rev == revision and dict(files) == sources)
        paths = prepared.stage(self.root / 'applied-recipe')
        with TerraformRunner(source_root=paths.source_root, source_files=paths.source_files,
                             variables_file=paths.variables_file,
                             backend_spec=BackendSpec.from_dict({'backend': 'local'}, cloud='aws'),
                             target_scope=None, deployment_name='fixture', state_root=self.root / 'state') as runner:
            runner.init()
            runner.apply(runner.plan(), acknowledge_mutation=True)
            state, outputs = runner.pull_state(), runner.output()
        store = BaselineStore(self.root / 'baselines')
        receipt = store.publish(prepared, apply_exit_code=0, state=state, outputs=outputs,
            applied_at=int(time.time()), verify_applied=lambda recipe, actual, result:
                recipe is prepared and actual == state and result == outputs
                and result['observed']['value'] == hashlib.sha256(observed.read_bytes()).hexdigest())
        raw = configuration(self.root)
        raw.update(baseline_ref=receipt.baseline_ref, expected_lineage=state['lineage'], expected_serial=state['serial'])
        (source / 'main.tf').write_text('INVALID DIRTY CHECKOUT MUST NEVER EXECUTE')
        inputs.write_text('PRIVATE_DIRTY_INPUT')
        return raw, observed

    def test_real_cached_apply_reconstructs_clean_then_detects_external_file_change_without_apply(self):
        api = self.api()
        from src.python.terraform_runner import TerraformRunner
        from src.python.drift_report import wrapper_exit_code
        raw, observed = self.applied_fixture()
        config = api.RuntimeConfig.from_dict(raw)
        before = config.local_state_path.read_bytes()
        commands = []
        real_execute = TerraformRunner._execute
        def audit(runner, arguments, *args, **kwargs):
            commands.append(arguments[0])
            return real_execute(runner, arguments, *args, **kwargs)
        with mock.patch.object(TerraformRunner, '_execute', audit):
            clean = api.check(config)
            self.assertEqual(clean['classes'], ['clean_within_coverage'], clean)
            observed.write_text('EXTERNALLY_CHANGED_PRIVATE_VALUE')
            changed = api.check(config)
        self.assertEqual(wrapper_exit_code(clean), 0)
        self.assertEqual(changed['classes'], ['desired_change'], changed)
        self.assertEqual(wrapper_exit_code(changed), 2)
        self.assertEqual(changed['evidence_sources'], ['terraform_plan'])
        self.assertIn('plan', commands)
        self.assertIn('show', commands)
        self.assertNotIn('apply', commands)
        self.assertEqual(before, config.local_state_path.read_bytes())
        self.assertNotIn('PRIVATE', json.dumps(changed))
        self.assertNotIn(str(self.root), json.dumps(changed))

    def test_report_artifact_requires_explicit_private_root_and_is_sanitized(self):
        api = self.api()
        raw, _ = self.applied_fixture()
        report_root = self.root / 'approved-reports'
        raw['report_root'] = str(report_root)
        result = api.check(api.RuntimeConfig.from_dict(raw))
        artifacts = list(report_root.glob('report-*.json'))
        self.assertEqual(len(artifacts), 1, 'approved ReportStore artifact missing')
        self.assertEqual(json.loads(artifacts[0].read_text()), result)
        self.assertEqual(artifacts[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(report_root.stat().st_mode & 0o777, 0o700)
        self.assertNotIn('PRIVATE', artifacts[0].read_text())
        self.assertNotIn(str(self.root), artifacts[0].read_text())
        with self.assertRaises(ValueError):
            api.ReportStore(report_root).save({**result, 'plan': {'password': 'PRIVATE'}})
        report_root.chmod(0o755)
        with mock.patch('src.python.terraform_runner.TerraformRunner.init') as init:
            with self.assertRaises(ValueError):
                api.check(api.RuntimeConfig.from_dict(raw))
        init.assert_not_called()

    def test_unlocked_dependency_declarations_are_partial_before_terraform(self):
        api = self.api()
        raw, _ = self.applied_fixture(dependency_declaration=True)
        with mock.patch('src.python.terraform_runner.TerraformRunner.init') as init:
            report = api.check(api.RuntimeConfig.from_dict(raw))
        init.assert_not_called()
        self.assertEqual(report['classes'], ['partial'])
        self.assertIn('pinned_dependencies_required', report['coverage']['unsupported'])

    def test_modules_need_a_reviewed_resolver_even_with_a_provider_lock(self):
        api = self.api()
        raw, _ = self.applied_fixture(module=True)
        with mock.patch('src.python.terraform_runner.TerraformRunner.init') as init:
            report = api.check(api.RuntimeConfig.from_dict(raw))
        init.assert_not_called()
        self.assertEqual(report['classes'], ['partial'])
        self.assertIn('module_resolver_required', report['coverage']['unsupported'])

    def test_report_root_cannot_overlap_state_or_private_baseline_storage(self):
        api = self.api()
        raw = configuration(self.root)
        for location in (self.root, self.root / 'state', self.root / 'state/reports',
                         self.root / 'baselines', self.root / 'baselines/reports'):
            with self.subTest(location=location), self.assertRaises(ValueError):
                api.check(api.RuntimeConfig.from_dict({**raw, 'report_root': str(location)}))

    def test_remote_backends_block_before_baseline_or_terraform_access(self):
        api = self.api()
        cases = [('aws', '123456789012', {'backend': 's3', 'namespace': 'studio', 'destination': {
                    'bucket': 'approved-bucket', 'region': 'us-east-1', 'owner_account_id': '123456789012', 'key_prefix': 'state'}}),
                 ('gcp', 'sample-project', {'backend': 'gcs', 'namespace': 'studio', 'destination': {
                    'bucket': 'approved-bucket', 'project': 'sample-project', 'prefix': 'state'}}),
                 ('azure', '00000000-0000-0000-0000-000000000001', {'backend': 'azurerm', 'namespace': 'studio', 'destination': {
                    'tenant_id': '00000000-0000-0000-0000-000000000001', 'subscription_id': '00000000-0000-0000-0000-000000000001',
                    'resource_group_name': 'example', 'storage_account_name': 'examplestore', 'container_name': 'state', 'key_prefix': 'state'}})]
        with mock.patch.object(api, 'BaselineStore') as store, mock.patch.object(api, 'TerraformRunner') as runner:
            for cloud, scope, backend in cases:
                raw = {**configuration(self.root), 'cloud': cloud, 'target_scope': scope, 'backend_config': backend}
                report = api.check(api.RuntimeConfig.from_dict(raw))
                self.assertEqual(report['classes'], ['partial'])
                self.assertIn('remote_backend_controller_review_and_service_release_gate_required', report['coverage']['unsupported'])
        store.assert_not_called()
        runner.assert_not_called()

    def test_current_markers_lineage_serial_and_corrupt_recipe_block_before_terraform(self):
        api = self.api()
        raw, _ = self.applied_fixture()
        config = api.RuntimeConfig.from_dict(raw)
        with mock.patch('src.python.terraform_runner.TerraformRunner.init') as init:
            for marker in ('migration.json', 'relocation.json', '.tfstate.retired', 'backend.json', '.isaac-claim-v1.json', 'errored.tfstate'):
                path = config.local_state_path.parent / marker
                path.symlink_to(self.root / 'missing')
                self.assertIn('identity_mismatch', api.check(config)['classes'], marker)
                path.unlink()
            for changes in ({'expected_lineage': configuration(self.root)['expected_lineage']},
                            {'expected_serial': raw['expected_serial'] + 1}):
                result = api.check(api.RuntimeConfig.from_dict({**raw, **changes}))
                self.assertIn('identity_mismatch', result['classes'])
            for path in config.baseline_store.glob('object-*'):
                original = path.read_bytes()
                path.write_bytes(b'CORRUPT_PRIVATE_INPUT')
                self.assertEqual(api.check(config)['classes'], ['partial'])
                path.write_bytes(original)
        init.assert_not_called()

    def test_retirement_rechecked_under_controller_lock_before_native_init(self):
        api = self.api()
        from src.python.terraform_runner import TerraformRunner
        raw, _ = self.applied_fixture()
        config = api.RuntimeConfig.from_dict(raw)
        stage = TerraformRunner._stage
        def retire_after_lock(runner):
            result = stage(runner)
            (config.local_state_path.parent / 'relocation.json').write_text('{}')
            return result
        with mock.patch.object(TerraformRunner, '_stage', retire_after_lock), mock.patch.object(TerraformRunner, 'init') as init:
            report = api.check(config)
        init.assert_not_called()
        self.assertNotIn('clean_within_coverage', report['classes'])

    def test_explicit_report_root_records_actual_history_api(self):
        api = self.api()
        from src.python.drift_history import HistoryStore, report_identity
        raw, _ = self.applied_fixture()
        raw['report_root'] = str(self.root / 'approved-reports')
        report = api.check(api.RuntimeConfig.from_dict(raw))
        history = HistoryStore(self.root / 'approved-reports/history', identity=report_identity(report)).load()
        self.assertEqual(history['status'], 'available')
        self.assertEqual(history['history']['records'][-1]['report'], report)
        self.assertNotIn('PRIVATE', json.dumps(history))

    def test_executable_check_uses_real_terraform_and_propagates_clean_and_findings_exits(self):
        import subprocess
        api = self.api()
        raw, observed = self.applied_fixture()
        path = self.root / 'runtime.json'
        path.write_text(json.dumps(raw))
        wrapper = Path(__file__).resolve().parents[2] / 'drift'
        before = api.RuntimeConfig.from_dict(raw).local_state_path.read_bytes()
        clean = subprocess.run([str(wrapper), 'check', '--config', str(path)],
                               text=True, capture_output=True, timeout=30)
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertEqual(json.loads(clean.stdout)['classes'], ['clean_within_coverage'])
        observed.write_text('PRIVATE_EXTERNAL_CHANGE')
        changed = subprocess.run([str(wrapper), 'check', '--config', str(path)],
                                 text=True, capture_output=True, timeout=30)
        self.assertEqual(changed.returncode, 2, changed.stdout + changed.stderr)
        self.assertEqual(json.loads(changed.stdout)['classes'], ['desired_change'])
        self.assertEqual(changed.stderr, '')
        self.assertNotIn('PRIVATE', changed.stdout)
        self.assertEqual(api.RuntimeConfig.from_dict(raw).local_state_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
