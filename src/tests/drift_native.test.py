"""Native generation is offline: no provider client, process, or activation."""
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch


class NativeTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('src.python.drift_native')
        except ModuleNotFoundError:
            self.fail('Native report-only adapter has not been implemented')

    def valid(self, provider='aws'):
        repositories = {'aws': '123456789012.dkr.ecr.us-east-1.amazonaws.com/automator',
                        'gcp': 'us-central1-docker.pkg.dev/example-monitoring/tools/automator',
                        'azure': 'example.azurecr.io/automator'}
        identities = {
            'aws': ['arn:aws:iam::123456789012:role/drift-reader', 'arn:aws:iam::123456789012:role/drift-scheduler', 'arn:aws:iam::123456789012:role/monitoring-admin'],
            'gcp': ['drift-reader@example-monitoring.iam.gserviceaccount.com', 'drift-scheduler@example-monitoring.iam.gserviceaccount.com', 'monitoring-admin@example-monitoring.iam.gserviceaccount.com'],
            'azure': ['/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/monitoring/providers/Microsoft.ManagedIdentity/userAssignedIdentities/drift-reader', 'platform:container-apps-jobs', '00000000-0000-0000-0000-000000000002']}
        return dict(provider=provider, provision=True, image=repositories[provider] + '@sha256:' + 'a' * 64,
                    config_artifact='/opt/automator/check.json', runtime_identity=identities[provider][0],
                    scheduler_identity=identities[provider][1], admin_identity=identities[provider][2],
                    report_storage_ref='retained-private-reports', schedule='17 3 * * *',
                    **({'automator_workdir': '/opt/automator'} if provider == 'aws' else {}))

    def test_provider_manifests_use_same_explicit_command_without_activation(self):
        native = self.module()
        for provider, executor in [('aws', 'scheduler_codebuild'), ('gcp', 'scheduler_cloud_run_job'),
                                   ('azure', 'container_apps_job')]:
            with self.subTest(provider=provider), patch('subprocess.run', side_effect=AssertionError('cloud invocation')):
                result = native.native_manifest(self.valid(provider))
            self.assertEqual(result['executor'], executor)
            self.assertEqual(result['invocation'], ['./drift', 'check', '--config', '/opt/automator/check.json'])
            self.assertFalse(result['schedule_enabled'])
            self.assertEqual(result['terraform_variables']['image'], self.valid(provider)['image'])
            self.assertEqual(result['terraform_variables']['correction'], 'report_only')
            self.assertEqual(result['report_storage_ownership'], 'external_retained')

    def test_rejects_unsupported_modes_unpinned_inputs_and_unsafe_budgets(self):
        native = self.module()
        changes = [dict(provider='alicloud'), dict(correction='approval_required'),
                   dict(mode='policy_remediation'), dict(signal='config'), dict(token='SECRET'),
                   dict(image='registry.example/automator:latest'), dict(image='https://secret@host/x@sha256:' + 'a'*64),
                   dict(config_artifact='../private.json'), dict(config_artifact='/x;curl'),
                   dict(runtime_identity='monitoring-admin'), dict(scheduler_identity='runtime-reader'),
                   dict(retries=5), dict(retries=True), dict(retries=1), dict(timeout_seconds=901),
                   dict(schedule='* * * * *'), dict(schedule='99 3 * * *'),
                   dict(provision=False, schedule_enabled=True), dict(provision='false')]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ValueError) as raised:
                    native.native_manifest({**self.valid(), **change})
                self.assertNotIn('SECRET', str(raised.exception))
        for field in ['provider', 'image', 'config_artifact', 'runtime_identity', 'scheduler_identity',
                      'admin_identity', 'report_storage_ref', 'schedule']:
            data = self.valid(); del data[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                native.native_manifest(data)

    def test_provider_specific_runtime_constraints(self):
        native = self.module()
        for provider in ['aws', 'gcp', 'azure']:
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                native.native_manifest({**self.valid(provider), 'image': 'registry.example/automator@sha256:' + 'a'*64})
        for timeout in [60, 301]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                native.native_manifest({**self.valid(), 'timeout_seconds': timeout})
        with self.assertRaises(ValueError):
            native.native_manifest({**self.valid('azure'), 'scheduler_identity': 'pretend-user-scheduler'})
        for data in [[], False, {'provider': []}, {'provider': None, 'image': 'x'}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                native.native_manifest(data)

    def test_codebuild_requires_explicit_working_directory(self):
        native = self.module()
        data = self.valid()
        data['automator_workdir'] = '/opt/automator'
        self.assertEqual(native.native_manifest(data)['terraform_variables']['automator_workdir'], '/opt/automator')
        missing = dict(data); del missing['automator_workdir']
        with self.assertRaises(ValueError):
            native.native_manifest(missing)
        for directory in ['', '../repo', '/opt/repo;curl']:
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                native.native_manifest({**data, 'automator_workdir': directory})

    def test_examples_are_inert_yaml_json_subset_without_invented_images(self):
        native = self.module()
        root = Path(__file__).resolve().parents[2]
        for provider in ['aws', 'gcp', 'azure']:
            path = root / 'configs/drift' / f'example-{provider}-native.yaml'
            self.assertTrue(path.is_file(), 'Missing disabled native example')
            data = json.loads(path.read_text())
            manifest = native.native_manifest(data)
            self.assertFalse(manifest['provision'])
            self.assertFalse(manifest['schedule_enabled'])
            self.assertEqual(manifest['provider'], provider)
            self.assertNotIn('image', data)

    def test_identity_references_are_provider_ids_not_secret_urls(self):
        native = self.module()
        for provider in ['aws', 'gcp', 'azure']:
            for key in ['runtime_identity', 'scheduler_identity', 'admin_identity']:
                with self.subTest(provider=provider, key=key), self.assertRaises(ValueError):
                    native.native_manifest({**self.valid(provider), key: 'https://user:SECRET@host'})
            data = self.valid(provider)
            data['runtime_identity'] = data['admin_identity']
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                native.native_manifest(data)

    def test_defaults_generate_no_invocation_or_resources(self):
        native = self.module()
        with patch('subprocess.run', side_effect=AssertionError('must remain offline')):
            manifest = native.native_manifest({})
        self.assertFalse(manifest['provision'])
        self.assertFalse(manifest['schedule_enabled'])
        self.assertEqual(manifest['invocation'], [])
        self.assertEqual(manifest['correction'], 'report_only')


if __name__ == '__main__':
    unittest.main()
