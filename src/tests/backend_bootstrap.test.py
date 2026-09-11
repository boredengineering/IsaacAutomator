"""Offline bootstrap tests. All authenticated transports are mocked."""
import importlib.util
import unittest
import subprocess
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from src.python.terraform_backend import BackendSpec

UUID = '11111111-1111-1111-1111-111111111111'
DEST = {
    'aws': dict(bucket='example-state', region='us-east-1', owner_account_id='123456789012', key_prefix='state'),
    'gcp': dict(bucket='example-state', project='example-project', prefix='state'),
    'azure': dict(tenant_id=UUID, subscription_id=UUID, resource_group_name='backend-rg', storage_account_name='examplestate', container_name='tfstate', key_prefix='state'),
}
def spec(cloud):
    return BackendSpec.from_dict(dict(backend={'aws':'s3','gcp':'gcs','azure':'azurerm'}[cloud], namespace='test', destination=DEST[cloud]), cloud=cloud)

def module():
    found = importlib.util.find_spec('src.python.backend_bootstrap')
    if found is None:
        return None
    from src.python import backend_bootstrap
    return backend_bootstrap

class BootstrapTests(unittest.TestCase):
    def test_bootstrap_rejects_unvalidated_principal_and_wrong_aws_region_offline(self):
        for principal, region in [('allUsers','us-east-1'), ('private-secret','us-east-1'), ('arn:aws:iam::123456789012:role/controller','us-west-2')]:
            with self.subTest(principal=principal), patch('subprocess.run') as run:
                with self.assertRaises(ValueError):
                    module().BootstrapSession(spec('aws'), bootstrap_state_root=Path('/not-used'), region=region, controller_principal=principal, acknowledge_reads=True)
                run.assert_not_called()

    def test_generic_http_404_never_authorizes_creation(self):
        api = module()
        for cloud in DEST:
            with self.subTest(cloud=cloud), tempfile.TemporaryDirectory() as root:
                runner = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
                failure = subprocess.CompletedProcess([], 1, '', 'Proxy endpoint returned HTTP 404: route unavailable')
                with patch('subprocess.run', return_value=failure):
                    session = api.BootstrapSession(
                        spec(cloud), bootstrap_state_root=Path(root),
                        region='us-east-1' if cloud == 'aws' else 'eastus',
                        controller_principal='arn:aws:iam::123456789012:role/controller' if cloud == 'aws' else ('user:controller@example.test' if cloud == 'gcp' else UUID),
                        workload_resource_groups=['workload-rg'], acknowledge_reads=True,
                        runner_factory=Mock(return_value=runner))
                    with self.assertRaisesRegex(ValueError, 'absence'):
                        with session:
                            session.apply(session.plan(), acknowledge_creation=True)
                    runner.init.assert_not_called()
                    runner.apply.assert_not_called()

    def test_generic_http_404_at_apply_recheck_blocks_mutation(self):
        api = module()
        with tempfile.TemporaryDirectory() as root:
            runner = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
            absent = subprocess.CompletedProcess([], 1, '', 'An error occurred (NoSuchBucket) when calling the GetBucketLocation operation: The specified bucket does not exist')
            ambiguous = subprocess.CompletedProcess([], 1, '', 'Proxy endpoint returned HTTP 404: route unavailable')
            with patch('subprocess.run', side_effect=[absent, ambiguous]):
                session = api.BootstrapSession(
                    spec('aws'), bootstrap_state_root=Path(root), region='us-east-1',
                    controller_principal='arn:aws:iam::123456789012:role/controller',
                    acknowledge_reads=True, runner_factory=Mock(return_value=runner))
                with session:
                    runner.init.assert_called_once()
                    with self.assertRaisesRegex(ValueError, 'absence'):
                        session.apply(session.plan(), acknowledge_creation=True)
                runner.apply.assert_not_called()

    def test_create_new_never_adopts_existing_or_denied_storage(self):
        api = module()
        for cloud in ('aws', 'gcp', 'azure'):
            for outcome in ({}, api.InspectionError('permission-denied')):
                with self.subTest(cloud=cloud, outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as root:
                    runner = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
                    read = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
                    session = api.BootstrapSession(spec(cloud), bootstrap_state_root=Path(root), region='us-east-1' if cloud == 'aws' else 'eastus', controller_principal='arn:aws:iam::123456789012:role/controller' if cloud == 'aws' else ('user:controller@example.test' if cloud == 'gcp' else UUID), workload_resource_groups=['workload-rg'], acknowledge_reads=True, runner_factory=Mock(return_value=runner), transport=read)
                    with self.assertRaisesRegex(ValueError, 'existing|absence'):
                        with session:
                            self.fail('must refuse')
                    runner.init.assert_not_called()
                    runner.__exit__.assert_called_once()

    def test_bootstrap_plan_apply_uses_independent_local_state_and_exact_plan(self):
        api = module()
        self.assertTrue(hasattr(api, 'BootstrapSession'), 'bootstrap session missing')
        runner_factory = Mock()
        runner = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        runner.__enter__.return_value = runner
        runner_factory.return_value = runner
        with tempfile.TemporaryDirectory() as root:
            session = api.BootstrapSession(spec('aws'), bootstrap_state_root=Path(root), region='us-east-1', controller_principal='arn:aws:iam::123456789012:role/controller', acknowledge_reads=True, runner_factory=runner_factory, transport=Mock(side_effect=api.InspectionError('not-found')))
            with session as bootstrap:
                plan = bootstrap.plan()
                with self.assertRaisesRegex(ValueError, 'acknowledgement'):
                    bootstrap.apply(plan)
                runner.apply.assert_not_called()
                bootstrap.apply(plan, acknowledge_creation=True)
                runner.apply.assert_called_once_with(plan, acknowledge_mutation=True)
            args = runner_factory.call_args.kwargs
            self.assertEqual(args['backend_spec'].backend, 'local')
            self.assertEqual(args['state_root'], Path(root)/'bootstrap')
            self.assertIn('bootstrap/aws', str(args['source_root']))
            self.assertEqual(args['variables']['controller_principal'], 'arn:aws:iam::123456789012:role/controller')
            self.assertTrue(args['deployment_name'].startswith('backend-'))
            self.assertNotIn('workstation', str(args))

    def test_bootstrap_creation_refuses_azure_overlap_and_implicit_reads(self):
        api = module()
        self.assertTrue(hasattr(api, 'BootstrapSession'), 'bootstrap session missing')
        with self.assertRaisesRegex(ValueError, 'resource group'):
            api.BootstrapSession(spec('azure'), bootstrap_state_root=Path('/not-used'), region='eastus', controller_principal=UUID, workload_resource_groups=['BACKEND-RG'], acknowledge_reads=True)
        with self.assertRaisesRegex(ValueError, 'acknowledgement'):
            api.BootstrapSession(spec('aws'), bootstrap_state_root=Path('/not-used'), region='us-east-1', controller_principal='arn:aws:iam::123456789012:role/controller')

    def test_not_found_requires_matching_provider_and_resource_operation(self):
        api = module()
        aws_error = 'An error occurred (NoSuchBucket) when calling the GetBucketLocation operation: The specified bucket does not exist'
        gcp_error = 'ERROR: (gcloud.storage.buckets.describe) HTTPError 404: The specified bucket does not exist.'
        azure_error = "ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/examplestate' under resource group 'backend-rg' was not found."
        group_error = "ERROR: (ResourceGroupNotFound) Resource group 'backend-rg' could not be found."
        allowed = [
            (['aws', 's3api', 'get-bucket-location', '--bucket', 'example-state'], aws_error),
            (['gcloud', 'storage', 'buckets', 'describe', 'gs://example-state'], gcp_error),
            (['az', 'storage', 'account', 'show', '--name', 'examplestate'], azure_error),
            (['az', 'storage', 'account', 'show', '--name', 'examplestate'], group_error),
            (['az', 'group', 'show', '--name', 'backend-rg'], group_error),
        ]
        denied = [
            (['aws', 'sts', 'get-caller-identity'], aws_error),
            (['gcloud', 'auth', 'list'], gcp_error),
            (['gcloud', 'projects', 'describe', 'example-project'], 'ERROR: (gcloud.projects.describe) NOT_FOUND: Project not found'),
            (['az', 'account', 'show'], azure_error),
            (['az', 'group', 'show', '--name', 'backend-rg'], azure_error),
        ]
        for argv, diagnostic in allowed:
            for unrelated in (aws_error, gcp_error, azure_error, group_error, '404', 'NOT_FOUND', 'ResourceNotFound', 'NoSuchBucket'):
                if (argv, unrelated) not in allowed:
                    denied.append((argv, unrelated))
        for expected, cases in [('not-found', allowed), ('unknown', denied)]:
            for argv, diagnostic in cases:
                with self.subTest(argv=argv, diagnostic=diagnostic), patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', diagnostic)):
                    with self.assertRaises(api.InspectionError) as caught:
                        api._cli_read(argv)
                    self.assertEqual(caught.exception.status, expected)

    def test_default_transport_is_concrete_read_only_and_sanitizes_failures(self):
        api = module()
        for code, status in [('AccessDenied','permission-denied'), ('NoSuchBucket','unknown'), ('ExpiredToken','authentication-required'), ('unclassified','unknown')]:
            with self.subTest(code=code), patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', code+' private-secret')) as run:
                result = api.doctor(spec('aws'), acknowledge_reads=True)
                self.assertEqual(result.status, status)
                self.assertNotIn('private-secret', repr(result))
                self.assertFalse(run.call_args.kwargs['shell'])
                self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired([], 5, output='private-secret')):
            self.assertEqual(api.doctor(spec('aws'), acknowledge_reads=True).status, 'unreachable')
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '{bad private-secret', '')):
            self.assertEqual(api.doctor(spec('aws'), acknowledge_reads=True).status, 'unknown')
        with patch('subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'acknowledgement'):
                api.doctor(spec('aws'))
            run.assert_not_called()

    def test_azure_health_uses_entra_data_plane_and_checks_delete_lock(self):
        account_id = '/subscriptions/'+UUID+'/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate'
        transport = Mock(side_effect=[
            {'id':UUID,'tenantId':UUID,'user':{'name':'controller'}},
            {'id':account_id,'name':'examplestate','kind':'StorageV2','isHnsEnabled':False,'enableHttpsTrafficOnly':True,'minimumTlsVersion':'TLS1_2','allowBlobPublicAccess':False,'allowSharedKeyAccess':False,'encryption':{'services':{'blob':{'enabled':True}}}},
            {'isVersioningEnabled':True,'deleteRetentionPolicy':{'enabled':True,'days':7},'containerDeleteRetentionPolicy':{'enabled':True,'days':7}},
            {'name':'tfstate','properties':{'publicAccess':None}},
            [{'level':'CanNotDelete','id':account_id+'/providers/Microsoft.Authorization/locks/backend'}],
        ])
        result = module().doctor(spec('azure'), acknowledge_reads=True, workload_resource_groups=['workload-rg'], transport=transport)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checks['deletion_protection'], 'passed')
        self.assertEqual(result.checks['encryption'], 'passed')
        self.assertEqual(transport.call_args_list[4].args[0], [
            'az', 'lock', 'list', '--resource-group', 'backend-rg',
            '--resource-name', 'examplestate', '--resource-type', 'Microsoft.Storage/storageAccounts',
            '--subscription', UUID, '--output', 'json', '--only-show-errors',
        ])
        for call in transport.call_args_list[2:4]:
            self.assertIn('--auth-mode', call.args[0])
            self.assertIn('login', call.args[0])

    def test_gcp_health_validates_project_and_public_iam(self):
        transport = Mock(side_effect=[
            [{'account':'controller@example.test','status':'ACTIVE'}],
            {'projectId':'example-project','projectNumber':'12345'},
            {'name':'example-state','projectNumber':'12345','versioning':{'enabled':True},'iamConfiguration':{'uniformBucketLevelAccess':{'enabled':True},'publicAccessPrevention':'enforced'},'softDeletePolicy':{'retentionDurationSeconds':'604800'}},
            {'bindings':[{'role':'roles/storage.objectViewer','members':['allUsers']}]},
        ])
        result = module().doctor(spec('gcp'), acknowledge_reads=True, transport=transport)
        self.assertEqual(result.status, 'noncompliant')
        self.assertEqual(result.checks['public_iam'], 'gap')
        self.assertEqual(result.checks['soft_delete'], 'passed')
        self.assertTrue(all(c.args[0][0] == 'gcloud' for c in transport.call_args_list))

    def test_aws_health_checks_protection_without_mutation(self):
        api = module()
        replies = [
            {'Account':'123456789012','Arn':'arn:aws:iam::123456789012:role/controller'},
            {'LocationConstraint':None},
            {'Status':'Enabled'},
            {'PublicAccessBlockConfiguration':dict(BlockPublicAcls=True, IgnorePublicAcls=True, BlockPublicPolicy=True, RestrictPublicBuckets=True)},
            {'OwnershipControls':{'Rules':[{'ObjectOwnership':'BucketOwnerEnforced'}]}},
            {'ServerSideEncryptionConfiguration':{'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]}},
            {'Policy':'{"Statement":[{"Effect":"Deny","Principal":"*","Action":"s3:*","Resource":["arn:aws:s3:::example-state","arn:aws:s3:::example-state/*"],"Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}'},
            {'PolicyStatus':{'IsPublic':False}},
            {'Contents':[]},
        ]
        transport = Mock(side_effect=replies)
        result = api.doctor(spec('aws'), acknowledge_reads=True, transport=transport)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checks['versioning'], 'passed')
        self.assertEqual(result.checks['encryption'], 'passed')
        self.assertEqual(result.checks['tls_only'], 'passed')
        self.assertEqual(result.checks['state_lock_write_permissions'], 'unknown')
        self.assertEqual(transport.call_count, 9)
        commands = [c.args[0] for c in transport.call_args_list]
        self.assertTrue(all(c[0] == 'aws' for c in commands))
        self.assertTrue(all('--expected-bucket-owner' in c for c in commands[1:]))

    def test_azure_ancestor_overlap_refuses_before_reads(self):
        api = module()
        self.assertIsNotNone(api, 'bootstrap service is missing')
        transport = Mock()
        with self.assertRaisesRegex(ValueError, 'resource group'):
            api.doctor(spec('azure'), acknowledge_reads=True, workload_resource_groups=['BACKEND-RG'], transport=transport)
        transport.assert_not_called()

if __name__ == '__main__':
    unittest.main()
