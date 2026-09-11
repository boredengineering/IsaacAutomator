"""Independent bootstrap ownership and authorized read-only backend inspection.

No login, automatic adoption, migration, or write/lease probes. Cloud command
output is private and never included in reports or exceptions.
"""
from dataclasses import dataclass
import json
import re
import subprocess
import hashlib
from pathlib import Path

from src.python.terraform_backend import BackendSpec
from src.python.terraform_runner import TerraformRunner


class InspectionError(RuntimeError):
    """Internal sanitized transport classification."""
    def __init__(self, status):
        self.status = status
        super().__init__('Backend inspection failed; cloud diagnostics withheld')


def _resource_absent(argv, diagnostic):
    """Recognize absence only at the resource lookup, never account context.

    HTTP status alone (including proxy 404s) is not evidence of absence. Keep
    this allowlist deliberately narrow: unrecognized CLI formats fail closed.
    """
    patterns = {
        ('aws', 's3api', 'get-bucket-location'):
            r'^An error occurred \(NoSuchBucket\) when calling the GetBucketLocation operation:',
        ('gcloud', 'storage', 'buckets', 'describe'):
            r'^ERROR: \(gcloud\.storage\.buckets\.describe\) HTTPError 404: The specified bucket does not exist\.',
        ('az', 'storage', 'account', 'show'):
            r'^ERROR: \((?:ResourceNotFound|ResourceGroupNotFound)\) ',
        ('az', 'group', 'show'):
            r'^ERROR: \(ResourceGroupNotFound\) ',
    }
    return any(tuple(argv[:len(operation)]) == operation and re.search(pattern, diagnostic, re.MULTILINE)
               for operation, pattern in patterns.items())


def _cli_read(argv):
    """Concrete bounded JSON cloud-CLI transport; never performs login."""
    try:
        result = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=60)
    except FileNotFoundError:
        raise InspectionError('unsupported-feature') from None
    except (OSError, subprocess.TimeoutExpired):
        raise InspectionError('unreachable') from None
    if result.returncode:
        status = 'unknown'
        # Authentication/authorization failures take precedence over absence.
        for pattern, classification in (
            (r'\b(AccessDenied|AccessDeniedException|AuthorizationPermissionMismatch|AuthorizationFailure|Forbidden|PERMISSION_DENIED|403)\b', 'permission-denied'),
            (r'\b(ExpiredToken|InvalidClientTokenId|AuthenticationFailed|UNAUTHENTICATED|401)\b', 'authentication-required'),
        ):
            if re.search(pattern, result.stderr):
                status = classification
                break
        if status == 'unknown' and _resource_absent(argv, result.stderr):
            status = 'not-found'
        raise InspectionError(status)
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, (dict, list)):
            raise ValueError()
        return payload
    except (ValueError, UnicodeError):
        raise InspectionError('unknown') from None


@dataclass(frozen=True)
class HealthReport:
    """Sanitized evidence, not proof of effective write/lease authorization."""
    status: str
    checks: dict
    message: str


def _check(condition):
    return 'passed' if condition else 'gap'


def _aws(destination, read):
    d = destination
    base = ['aws']
    suffix = ['--region', d['region'], '--output', 'json', '--no-cli-pager']
    identity = read(base + ['sts', 'get-caller-identity'] + suffix)
    if identity.get('Account') != d['owner_account_id'] or not identity.get('Arn'):
        return HealthReport('identity-mismatch', {'identity':'gap'}, 'Select the expected backend account identity')
    def bucket(operation, *extra):
        return read(base + ['s3api', operation, '--bucket', d['bucket'], '--expected-bucket-owner', d['owner_account_id'], *extra] + suffix)
    location = bucket('get-bucket-location').get('LocationConstraint') or 'us-east-1'
    if location == 'EU':
        location = 'eu-west-1'
    if location != d['region']:
        return HealthReport('identity-mismatch', {'region':'gap'}, 'Bucket region differs from the descriptor')
    checks = {'identity':'passed', 'versioning':_check(bucket('get-bucket-versioning').get('Status') == 'Enabled')}
    public = bucket('get-public-access-block').get('PublicAccessBlockConfiguration', {})
    checks['public_access'] = _check(all(public.get(k) is True for k in ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')))
    ownership = bucket('get-bucket-ownership-controls').get('OwnershipControls', {}).get('Rules', [])
    checks['ownership'] = _check(any(r.get('ObjectOwnership') == 'BucketOwnerEnforced' for r in ownership))
    rules = bucket('get-bucket-encryption').get('ServerSideEncryptionConfiguration', {}).get('Rules', [])
    checks['encryption'] = _check(any(r.get('ApplyServerSideEncryptionByDefault', {}).get('SSEAlgorithm') in ('AES256', 'aws:kms', 'aws:kms:dsse') and (not d.get('kms_key_id') or r.get('ApplyServerSideEncryptionByDefault', {}).get('KMSMasterKeyID') == d['kms_key_id']) for r in rules))
    policy = json.loads(bucket('get-bucket-policy').get('Policy', '{}'))
    arn = 'arn:aws:s3:::' + d['bucket']
    statements = policy.get('Statement', [])
    if isinstance(statements, dict):
        statements = [statements]
    checks['tls_only'] = _check(any(s.get('Effect') == 'Deny' and s.get('Principal') == '*' and s.get('Action') == 's3:*' and set(s.get('Resource', [])) >= {arn, arn+'/*'} and s.get('Condition') == {'Bool':{'aws:SecureTransport':'false'}} for s in statements))
    checks['public_policy'] = _check(bucket('get-bucket-policy-status').get('PolicyStatus', {}).get('IsPublic') is False)
    bucket('list-objects-v2', '--prefix', d['key_prefix']+'/', '--max-keys', '1')
    checks['scoped_list_access'] = 'passed'
    checks.update(state_lock_write_permissions='unknown', deletion_protection='unknown', kms_permissions='unknown' if d.get('kms_key_id') else 'not-applicable')
    return _report(checks)


def _report(checks):
    return HealthReport('noncompliant' if 'gap' in checks.values() else 'partial', checks,
                        'Read-only evidence only; effective write/lock, restore and key permissions require separately approved verification')


def _gcp(d, read):
    def command(*args):
        return read(['gcloud', *args, '--format=json', '--quiet'])
    identity = command('auth', 'list', '--filter=status:ACTIVE')
    if not isinstance(identity, list) or len(identity) != 1 or not identity[0].get('account'):
        return HealthReport('identity-mismatch', {'identity':'gap'}, 'Select one authenticated backend controller identity')
    project = command('projects', 'describe', d['project'])
    bucket = command('storage', 'buckets', 'describe', 'gs://'+d['bucket'], '--raw', '--project='+d['project'])
    if project.get('projectId') != d['project'] or not project.get('projectNumber') or str(bucket.get('projectNumber')) != str(project['projectNumber']) or bucket.get('name') != d['bucket']:
        return HealthReport('identity-mismatch', {'identity':'gap'}, 'Bucket project differs from the descriptor')
    iam = command('storage', 'buckets', 'get-iam-policy', 'gs://'+d['bucket'], '--project='+d['project'])
    configuration = bucket.get('iamConfiguration', {})
    checks = dict(identity='passed',
                  versioning=_check(bucket.get('versioning', {}).get('enabled') is True),
                  uniform_access=_check(configuration.get('uniformBucketLevelAccess', {}).get('enabled') is True),
                  public_access=_check(configuration.get('publicAccessPrevention') == 'enforced'),
                  soft_delete=_check(int(bucket.get('softDeletePolicy', {}).get('retentionDurationSeconds', 0)) >= 604800),
                  public_iam=_check('bindings' in iam and not any(m in ('allUsers', 'allAuthenticatedUsers') for binding in iam['bindings'] for m in binding.get('members', []))),
                  encryption=_check(not d.get('kms_encryption_key') or bucket.get('encryption', {}).get('defaultKmsKeyName') == d['kms_encryption_key']),
                  state_lock_write_permissions='unknown', deletion_protection='unknown',
                  kms_service_agent_permissions='unknown' if d.get('kms_encryption_key') else 'not-applicable')
    return _report(checks)


def _azure(d, read):
    def command(*args):
        return read(['az', *args, '--subscription', d['subscription_id'], '--output', 'json', '--only-show-errors'])
    identity = command('account', 'show')
    if identity.get('id') != d['subscription_id'] or identity.get('tenantId') != d['tenant_id'] or not identity.get('user', {}).get('name'):
        return HealthReport('identity-mismatch', {'identity':'gap'}, 'Select the expected backend tenant/subscription identity')
    account = command('storage', 'account', 'show', '--resource-group', d['resource_group_name'], '--name', d['storage_account_name'])
    account_id = '/subscriptions/'+d['subscription_id']+'/resourceGroups/'+d['resource_group_name']+'/providers/Microsoft.Storage/storageAccounts/'+d['storage_account_name']
    if account.get('id', '').casefold() != account_id.casefold():
        return HealthReport('identity-mismatch', {'identity':'gap'}, 'Storage account ancestry differs from the descriptor')
    if account.get('kind') != 'StorageV2' or account.get('isHnsEnabled') is True:
        return HealthReport('unsupported-feature', {'storage_kind':'gap'}, 'Versioned backend requires non-HNS StorageV2')
    service = command('storage', 'blob', 'service-properties', 'show', '--account-name', d['storage_account_name'], '--auth-mode', 'login')
    container = command('storage', 'container', 'show', '--account-name', d['storage_account_name'], '--name', d['container_name'], '--auth-mode', 'login')
    locks = command('lock', 'list', '--resource-group', d['resource_group_name'],
                    '--resource-name', d['storage_account_name'], '--resource-type', 'Microsoft.Storage/storageAccounts')
    checks = dict(identity='passed',
                  encryption=_check(account.get('encryption', {}).get('services', {}).get('blob', {}).get('enabled') is True),
                  tls_only=_check(account.get('enableHttpsTrafficOnly') is True and account.get('minimumTlsVersion') in ('TLS1_2','TLS1_3')),
                  public_access=_check(account.get('allowBlobPublicAccess') is False),
                  entra_only=_check(account.get('allowSharedKeyAccess') is False),
                  private_container=_check(container.get('name') == d['container_name'] and 'publicAccess' in container.get('properties', {}) and container['properties']['publicAccess'] in (None, 'off')),
                  versioning=_check(service.get('isVersioningEnabled') is True),
                  deletion_protection=_check(any(lock.get('level') == 'CanNotDelete' and lock.get('id', '').casefold().startswith(account_id.casefold()+'/providers/microsoft.authorization/locks/') for lock in locks)),
                  state_lock_write_permissions='unknown', effective_iam='unknown')
    for key in ('deleteRetentionPolicy', 'containerDeleteRetentionPolicy'):
        policy = service.get(key, {})
        checks[key] = _check(policy.get('enabled') is True and policy.get('days', 0) >= 7)
    return _report(checks)


def _isolate(spec, workload_resource_groups):
    if spec.backend == 'local':
        raise ValueError('Bootstrap requires a remote backend')
    if spec.cloud == 'azure':
        if not workload_resource_groups:
            raise ValueError('Supply all workload resource group names for ancestor isolation')
        destination = spec.to_dict()['destination']
        if destination['resource_group_name'].casefold() in {name.casefold() for name in workload_resource_groups}:
            raise ValueError('Backend resource group overlaps workload resource group ownership')


def doctor(spec, *, acknowledge_reads=False, workload_resource_groups=(), transport=None):
    _isolate(spec, workload_resource_groups)
    if acknowledge_reads is not True:
        raise ValueError('Authenticated inspection requires explicit read acknowledgement')
    try:
        return {'aws':_aws, 'gcp':_gcp, 'azure':_azure}[spec.cloud](spec.to_dict()['destination'], transport or _cli_read)
    except InspectionError as error:
        return HealthReport(error.status, {'inspection':'unknown'},
                            'Inspection incomplete; verify CLI availability, backend identity, read permissions and network access. No changes made.')
    except (ValueError, TypeError, KeyError, AttributeError):
        return HealthReport('unknown', {'inspection':'unknown'}, 'Unexpected cloud response; no changes made; diagnostics withheld')


class BootstrapSession:
    """Create-new admin stack; use doctor() for existing/external ownership.

    Keep this context open across plan review and apply: SavedPlan is private,
    single-use and bound to the runner. No destroy/import/migrate API is exposed.
    bootstrap_state_root must be an explicitly retained controller admin root;
    the runner keeps its private state under bootstrap/backend-<storage digest>.
    Back it up securely independently of workstation attachments before moving
    controllers. An interrupted apply can require manual recovery; inspect the
    runner recovery_directory/recovery_state properties after context exit.
    """
    def __init__(self, spec, *, bootstrap_state_root, region, controller_principal,
                 workload_resource_groups=(), acknowledge_reads=False,
                 runner_factory=None, transport=None):
        _isolate(spec, workload_resource_groups)
        if acknowledge_reads is not True:
            raise ValueError('Bootstrap planning requires explicit read acknowledgement')
        d = spec.to_dict()['destination']
        principal_patterns = {
            'aws': r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+',
            'gcp': r'(?:serviceAccount|user):[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+',
            'azure': r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',
        }
        if not isinstance(controller_principal, str) or not re.fullmatch(principal_patterns[spec.cloud], controller_principal):
            raise ValueError('Supply one explicit nonsecret controller principal in the provider format')
        if not isinstance(region, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,62}', region):
            raise ValueError('Supply an explicit safe backend storage region')
        if spec.cloud == 'aws' and region != d['region']:
            raise ValueError('Bootstrap region must match the S3 backend descriptor')
        scope = d.get('owner_account_id') or d.get('project') or d.get('subscription_id')
        storage_identity = {k:v for k,v in d.items() if k not in ('key_prefix', 'prefix', 'kms_key_id', 'kms_encryption_key', 'container_name')}
        name = 'backend-'+hashlib.sha256(json.dumps(storage_identity, sort_keys=True).encode()).hexdigest()[:24]
        self._read = transport or _cli_read
        self._state_path = Path(bootstrap_state_root)/'bootstrap'/name/'.tfstate'
        if spec.cloud == 'aws':
            self._absence_commands = [['aws', 's3api', 'get-bucket-location', '--bucket', d['bucket'], '--expected-bucket-owner', d['owner_account_id'], '--region', d['region'], '--output', 'json', '--no-cli-pager']]
        elif spec.cloud == 'gcp':
            self._absence_commands = [['gcloud', 'storage', 'buckets', 'describe', 'gs://'+d['bucket'], '--raw', '--project='+d['project'], '--format=json', '--quiet']]
        else:
            suffix = ['--subscription', d['subscription_id'], '--output', 'json', '--only-show-errors']
            self._absence_commands = [
                ['az', 'storage', 'account', 'show', '--resource-group', d['resource_group_name'], '--name', d['storage_account_name'], *suffix],
                ['az', 'group', 'show', '--name', d['resource_group_name'], *suffix],
            ]
        variables: dict = dict(region=region, controller_principal=controller_principal)
        if spec.cloud == 'aws':
            variables.update(bucket_name=d['bucket'], owner_account_id=d['owner_account_id'], key_prefix=d['key_prefix'], kms_key_id=d.get('kms_key_id', ''))
        elif spec.cloud == 'gcp':
            variables.update(project=d['project'], state_bucket_name=d['bucket'], kms_key_name=d.get('kms_encryption_key', ''))
        else:
            variables.update({k:v for k,v in d.items() if k != 'key_prefix'})
            variables['workload_resource_groups'] = list(workload_resource_groups)
        self.runner = (runner_factory or TerraformRunner)(
            source_root=Path(__file__).resolve().parents[1]/'terraform'/'bootstrap'/spec.cloud,
            source_files=['main.tf', 'variables.tf', 'outputs.tf'],
            backend_spec=BackendSpec.from_dict(None, cloud=spec.cloud),
            target_scope=scope, deployment_name=name,
            state_root=Path(bootstrap_state_root)/'bootstrap', variables=variables)

    def __enter__(self):
        self.runner.__enter__()
        try:
            self._assert_absent()
            self.runner.init()
        except BaseException as error:
            self.runner.__exit__(type(error), error, error.__traceback__)
            raise
        return self

    def __exit__(self, *args):
        return self.runner.__exit__(*args)

    def plan(self):
        return self.runner.plan()

    def _assert_absent(self):
        if self._state_path.exists():
            raise ValueError('An existing bootstrap state requires its original admin maintenance/recovery workflow')
        for command in self._absence_commands:
            try:
                self._read(command)
            except InspectionError as error:
                if error.status == 'not-found':
                    continue
                raise ValueError('Cannot establish storage absence; use doctor and resolve access before creating') from None
            raise ValueError('Refusing to adopt existing storage or resource group; use doctor for use-existing')

    def apply(self, plan, *, acknowledge_creation=False):
        if acknowledge_creation is not True:
            raise ValueError('Backend creation requires separate explicit acknowledgement')
        self._assert_absent()
        return self.runner.apply(plan, acknowledge_mutation=True)
