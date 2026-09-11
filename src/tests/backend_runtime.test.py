"""GCS runtime tests use synthetic metadata and no cloud operations."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from src.python.terraform_backend import BackendSpec

SPEC = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
    'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'fixture'
        self.directory.mkdir()

    def write_meta(self, **changes):
        params = {'deployment_name': 'fixture', 'cloud': 'gcp', 'project': 'target-project',
                  'state_backend': 'gcs', 'terraform_state': SPEC.to_dict()}
        params.update(changes)
        (self.directory / 'meta.json').write_text(json.dumps({'params': params}))

    def test_protected_records_and_ambiguous_metadata_never_fall_back(self):
        from src.python.backend_runtime import load_backend_record
        from src.python.terraform_runner import TerraformRunnerError
        self.write_meta()
        for marker in ('backend.json', 'migration.json', 'relocation.json'):
            path = self.directory / marker
            path.write_text('{}')
            with self.subTest(marker=marker), self.assertRaises(TerraformRunnerError):
                load_backend_record('fixture', state_root=self.root)
            path.unlink()
        for changes in ({'deployment_name': 'other'}, {'cloud': 'aws'},
                        {'backend_runtime': {'identity': {}, 'status': 'active'}},
                        {'backend_runtime': {'identity': SPEC.identity('target-project', 'fixture'), 'status': 'unknown'}},
                        {'terraform_state': []}):
            self.write_meta(**changes)
            with self.subTest(changes=changes), self.assertRaises(TerraformRunnerError):
                load_backend_record('fixture', state_root=self.root)
        with self.assertRaises(TerraformRunnerError):
            load_backend_record('../escape', state_root=self.root)

    def test_record_runner_binds_sources_inputs_scope_and_read_only_root(self):
        import src.python.backend_runtime as runtime
        self.assertTrue(callable(getattr(runtime, 'record_runner', None)), 'record runner is missing')
        self.write_meta()
        record = runtime.load_backend_record('fixture', state_root=self.root)
        terraform = self.root / 'terraform'
        (terraform / 'gcp').mkdir(parents=True)
        (terraform / 'gcp' / 'main.tf').write_text('terraform {}')
        (self.directory / '.tfvars').write_text('project = "target-project"')
        with patch.object(runtime, 'gcs_object_names', return_value=set()), \
             patch.object(runtime, 'workstation_source_files', return_value=['main.tf']):
            with runtime.record_runner(record, state_root=self.root, terraform_root=terraform,
                                       environment={'PATH': '/usr/bin'}) as runner:
                self.assertTrue(runner.staged_root.is_relative_to(self.root / '.terraform-operations'))
                self.assertTrue(callable(runner._remote_guard), 'record runner must wire the live guard')
                self.assertEqual(json.loads(runner.backend_identity), record.identity)
                self.assertIsNone(runner.local_state_path)
                self.assertEqual((runner.staged_root.parent / 'inputs.tfvars').read_text(),
                                 'project = "target-project"')
            (self.directory / '.tfvars').unlink()
            with runtime.record_runner(record, state_root=self.root, read_only=True,
                                       environment={'PATH': '/usr/bin'}) as runner:
                self.assertEqual(set(p.name for p in runner.staged_root.iterdir()),
                                 {'main.tf', 'runner_override.tf.json'})
                self.assertEqual((runner.staged_root / 'main.tf').read_text(), 'terraform {}\n')
                self.assertEqual(runner._variables_json, b'{}')

    def test_runtime_guard_rejects_occupancy_claims_changes_and_read_only_mutations(self):
        import src.python.backend_runtime as runtime
        from src.python.terraform_runner import TerraformRunnerError
        self.assertTrue(callable(getattr(runtime, 'runtime_guard', None)), 'guard is missing')
        self.write_meta()
        record = runtime.load_backend_record('fixture', state_root=self.root)
        guard = runtime.runtime_guard(record, state_root=self.root, environment={})
        runner = Mock(backend_identity=json.dumps(record.identity, sort_keys=True, separators=(',', ':')))
        with patch.object(runtime, 'gcs_object_names', return_value=set()) as objects:
            guard(runner, 'init')
            guard(runner, 'apply')
            for suffix in ('', '.isaac-claim-v1.json', '.isaac-manifest-v1.json', '.isaac-relocation-v1.json'):
                objects.return_value = {record.identity['object_key'] + suffix}
                with self.subTest(suffix=suffix), self.assertRaises(TerraformRunnerError):
                    guard(runner, 'apply')
            self.write_meta(backend_runtime={'identity': record.identity, 'status': 'active', 'lineage': 'known'})
            active = runtime.load_backend_record('fixture', state_root=self.root)
            guard = runtime.runtime_guard(active, state_root=self.root, environment={})
            objects.return_value = {record.identity['object_key']}
            runner.pull_state.return_value = {'lineage': 'known'}
            guard(runner, 'init')
            runner.pull_state.return_value = {'lineage': 'different'}
            with self.assertRaises(TerraformRunnerError):
                guard(runner, 'apply')
            readonly = runtime.runtime_guard(active, state_root=self.root, environment={}, read_only=True)
            with self.assertRaises(TerraformRunnerError):
                readonly(runner, 'apply')
            self.write_meta(project='changed-project')
            with self.assertRaises(TerraformRunnerError):
                guard(runner, 'init')

    def test_gcs_metadata_reads_use_ambient_token_or_adc_without_state_contents(self):
        import src.python.backend_runtime as runtime
        from src.python.terraform_runner import TerraformRunnerError
        self.write_meta()
        record = runtime.load_backend_record('fixture', state_root=self.root)
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps({'items': [{'name': record.identity['object_key']}]}).encode()
        with patch('http.client.HTTPSConnection', return_value=connection) as connect, \
             patch('subprocess.run') as run:
            run.return_value = Mock(returncode=0, stdout=b'synthetic-adc-token\n')
            for env in ({'GOOGLE_OAUTH_ACCESS_TOKEN': 'synthetic-env-token'}, {'PATH': '/usr/bin'}):
                self.assertEqual(runtime.gcs_object_names(record, env), {record.identity['object_key']})
                method, url = connection.request.call_args.args
                self.assertEqual(method, 'GET')
                self.assertIn('prefix=state%2Ftests%2Fgcp%2Ftarget-project%2Ffixture', url)
                self.assertIn('fields=items%28name%29%2CnextPageToken', url)
                self.assertNotIn('alt=media', url)
                self.assertNotIn('synthetic', url)
                connect.assert_called_with('storage.googleapis.com', timeout=60)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ['gcloud', 'auth', 'application-default', 'print-access-token', '--quiet'])
            self.assertFalse(run.call_args.kwargs['shell'])
            for status, payload in ((403, b'SECRET'), (404, b''), (200, b'bad'),
                                    (200, b'{"nextPageToken":"more"}'), (200, b'{"items":[{}]}')):
                response.status, response.read.return_value = status, payload
                with self.subTest(status=status, payload=payload), self.assertRaises(TerraformRunnerError) as error:
                    runtime.gcs_object_names(record, {'GOOGLE_OAUTH_ACCESS_TOKEN': 'synthetic-env-token'})
                self.assertNotIn('SECRET', str(error.exception))

    def test_operation_created_empty_state_is_pinned_for_later_plan_apply(self):
        import src.python.backend_runtime as runtime
        self.write_meta()
        record = runtime.load_backend_record('fixture', state_root=self.root)
        guard = runtime.runtime_guard(record, state_root=self.root, environment={})
        runner = Mock(backend_identity=json.dumps(record.identity))
        runner.pull_state.return_value = {'lineage': 'init-lineage', 'serial': 1, 'resources': [], 'outputs': {}}
        with patch.object(runtime, 'gcs_object_names', return_value=set()) as names:
            guard(runner, 'pre-init')
            names.return_value = {record.identity['object_key']}
            guard(runner, 'init')
            saved = runtime.load_backend_record('fixture', state_root=self.root)
            self.assertEqual(saved.status, 'configured')
            self.assertEqual(saved.lineage, 'init-lineage')
            # A fresh controller can plan/apply the exact initialized empty state.
            fresh = runtime.runtime_guard(saved, state_root=self.root, environment={})
            fresh(runner, 'pre-init')
            fresh(runner, 'init')
            fresh(runner, 'apply')
            from src.python.terraform_runner import TerraformRunnerError
            names.return_value = set()
            with self.assertRaises(TerraformRunnerError):
                fresh(runner, 'pre-init')
            self.assertEqual((self.directory / 'meta.json').stat().st_mode & 0o777, 0o600)

    def test_record_loader_rejects_hidden_or_malformed_backend_intent(self):
        from src.python.backend_runtime import load_backend_record
        from src.python.terraform_runner import TerraformRunnerError
        for changes in ({'terraform_state': [], 'state_backend': None},
                        {'state_bucket': 'legacy-state'}, {'backend_config': '/untrusted/path'},
                        {'profile_spec': {'state_backend': 's3'}},
                        {'backend_runtime': {'identity': SPEC.identity('target-project', 'fixture'),
                                             'status': 'configured', 'lineage': []}}):
            self.write_meta(**changes)
            with self.subTest(changes=changes), self.assertRaises(TerraformRunnerError):
                load_backend_record('fixture', state_root=self.root)
        self.write_meta()
        meta_path = self.directory / 'meta.json'
        meta = json.loads(meta_path.read_text())
        meta['input_params'] = {'state_backend': 'local'}
        meta_path.write_text(json.dumps(meta))
        with self.assertRaises(TerraformRunnerError):
            load_backend_record('fixture', state_root=self.root)

    def test_saved_metadata_resolves_exact_backend_scope_and_name(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.backend_runtime'), 'runtime is missing')
        from src.python.backend_runtime import load_backend_record
        self.write_meta()
        record = load_backend_record('fixture', state_root=self.root)
        self.assertEqual(record.backend_spec, SPEC)
        self.assertEqual(record.target_scope, 'target-project')
        self.assertEqual(record.deployment_name, 'fixture')
        self.assertEqual(record.identity, SPEC.identity('target-project', 'fixture'))


if __name__ == '__main__':
    unittest.main()
