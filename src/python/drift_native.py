"""Offline cloud-native report-only scheduling manifests; never cloud activation."""
import re
from typing import Any
from .drift_config import bounded, opaque_ref, strict_block

EXECUTORS = {'aws': 'scheduler_codebuild', 'gcp': 'scheduler_cloud_run_job',
             'azure': 'container_apps_job'}
REQUIRED = {'image', 'config_artifact', 'runtime_identity', 'scheduler_identity',
            'admin_identity', 'report_storage_ref', 'schedule'}
REGISTRIES = {'aws': r'[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com',
              'gcp': r'[a-z0-9-]+-docker\.pkg\.dev',
              'azure': r'[a-z0-9]+\.azurecr\.io'}
UUID = r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}'
IDENTITIES = {'aws': r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+',
              'gcp': r'[a-z][a-z0-9-]+@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com',
              'azure': rf'/subscriptions/{UUID}/resourceGroups/[A-Za-z0-9_.()-]+/providers/Microsoft\.ManagedIdentity/userAssignedIdentities/[A-Za-z0-9_-]+'}


def native_manifest(data=None):
    """Return a JSON-serializable, inert scheduling contract."""
    data = strict_block({} if data is None else data, REQUIRED | {
        'provider', 'provision', 'schedule_enabled', 'correction', 'retries',
        'timeout_seconds', 'max_attempts_per_day', 'automator_workdir'})
    for key in ('provision', 'schedule_enabled'):
        if type(data.get(key, False)) is not bool:
            raise ValueError('Native activation flags must be boolean')
    provider = data.get('provider')
    if provider is not None and (not isinstance(provider, str) or provider not in EXECUTORS):
        raise ValueError('Unsupported native provider')
    if data.get('correction', 'report_only') != 'report_only':
        raise ValueError('Native modes support report_only; policies and correction are unsupported')
    if data.get('schedule_enabled') and not data.get('provision'):
        raise ValueError('Scheduling requires explicit provisioning')
    if data.get('provision') and (not REQUIRED <= data.keys() or not data.get('provider')):
        raise ValueError('Provisioning requires explicit image, artifact, identities, reports and schedule')
    if provider == 'aws' and data.get('provision') and not data.get('automator_workdir'):
        raise ValueError('CodeBuild requires explicit automator_workdir inside the pinned image')
    if 'automator_workdir' in data and (provider != 'aws' or not isinstance(data['automator_workdir'], str) or
            not re.fullmatch(r'/[A-Za-z0-9_/-]+', data['automator_workdir'])):
        raise ValueError('CodeBuild requires a safe absolute Automator working directory')
    if 'image' in data and (not isinstance(data['image'], str) or not re.fullmatch(
            r'[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9._/-]+@sha256:[a-f0-9]{64}', data['image'])):
        raise ValueError('Image must be a user registry repository pinned by sha256 digest')
    if 'image' in data and (provider is None or not re.fullmatch(REGISTRIES[provider], data['image'].split('/')[0])):
        raise ValueError('Native image pull supports only matching private ECR, Artifact Registry or ACR')
    if provider == 'azure' and 'scheduler_identity' in data and data['scheduler_identity'] != 'platform:container-apps-jobs':
        raise ValueError('Azure uses the built-in platform:container-apps-jobs scheduler, not a user principal')
    if 'config_artifact' in data and (not isinstance(data['config_artifact'], str) or not re.fullmatch(
            r'/[A-Za-z0-9_/-]+(?:\.[A-Za-z0-9_-]+)*', data['config_artifact']) or
            '..' in data['config_artifact'].split('/')):
        raise ValueError('Config artifact must be a safe absolute path inside the pinned image')
    identities = []
    for key in ('runtime_identity', 'scheduler_identity', 'admin_identity'):
        if key in data:
            value = data[key]
            pattern = IDENTITIES.get(provider or '', r'(?!)')
            if provider == 'azure' and key != 'runtime_identity':
                pattern = UUID if key == 'admin_identity' else r'platform:container-apps-jobs'
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise ValueError('Expected nonsecret provider identity reference')
            identities.append(value)
    if len(set(identities)) != len(identities):
        raise ValueError('Scheduler, runtime and admin identities must be distinct')
    if 'report_storage_ref' in data:
        opaque_ref(data['report_storage_ref'])
    if 'schedule' in data and (not isinstance(data['schedule'], str) or not re.fullmatch(
            r'([0-5]?[0-9]) ([01]?[0-9]|2[0-3]) \* \* \*', data['schedule'])):
        raise ValueError('Native cost-limited slice supports once-daily UTC cron only')
    retries = bounded(data.get('retries', 0), 0, 4)
    bounded(data.get('timeout_seconds', 300), 60, 900)
    if provider == 'aws' and (data.get('timeout_seconds', 300) < 300 or data.get('timeout_seconds', 300) % 60):
        raise ValueError('CodeBuild timeout must be 300..900 seconds in whole minutes')
    if bounded(data.get('max_attempts_per_day', 1), 1, 5) < retries + 1:
        raise ValueError('Daily scheduled-attempt budget must include all retries')
    values: dict[str, Any] = dict(provision=False, schedule_enabled=False, correction='report_only',
                  retries=0, timeout_seconds=300, max_attempts_per_day=1)
    values.update(data)
    provider = values.pop('provider', None)
    return {**values, 'provider': provider,
            'executor': EXECUTORS.get(provider),
            'invocation': ['./drift', 'check', '--config', values['config_artifact']] if values['provision'] else [],
            'report_storage_ownership': 'external_retained', 'terraform_variables': values}
