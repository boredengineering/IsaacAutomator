"""Small native GCS runtime bridge; no custom principal attestation.

Public lifecycle API:
  load_backend_record(name, state_root=...) -> BackendRecord | None (legacy local)
  record_runner(record, state_root=..., terraform_root=..., read_only=False)
    yields a fresh, UNINITIALIZED TerraformRunner; caller calls init, plan,
    apply(plan, acknowledge_mutation=True), output/pull_state inside the context.
    read_only=True uses a backend-only root and never loads workload inputs.

Records are persisted in meta.json params: terraform_state (BackendSpec),
project (workload scope), deployment_name, cloud, and backend_runtime (pinned
identity/status/lineage). Missing runtime status means configured, NOT adopted.
Existing protected backend.json and migration/relocation markers retain their
separate supervised protocol. Never dispatch them through this simpler bridge.
"""
from dataclasses import dataclass, replace
from contextlib import contextmanager
import json
import os
import tempfile
from pathlib import Path

from src.python.terraform_sources import workstation_source_files
from src.python.terraform_runner import TerraformRunner

from src.python.terraform_backend import BackendSpec
from src.python.terraform_runner import TerraformRunnerError, _input_snapshot, _no_symlinks
from src.python.deployment_manifest import strict_json


@dataclass(frozen=True)
class BackendRecord:
    backend_spec: BackendSpec
    target_scope: str
    deployment_name: str
    status: str = 'configured'
    lineage: str | None = None

    @property
    def identity(self):
        return self.backend_spec.identity(self.target_scope, self.deployment_name)


def load_backend_record(deployment_name, *, state_root):
    """Resolve explicit GCS params only; never reinterpret stale local state."""
    directory = Path(state_root).absolute() / deployment_name
    _no_symlinks(directory)
    if directory.parent != Path(state_root).absolute() or not deployment_name:
        raise TerraformRunnerError('Invalid deployment name')
    for marker in ('backend.json', 'migration.json', 'relocation.json'):
        try:
            (directory / marker).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise TerraformRunnerError('Cannot verify protected backend/migration records') from None
        raise TerraformRunnerError('Protected backend/claim or migration record requires its supervised protocol')
    path = directory / 'meta.json'
    _no_symlinks(path)
    if not path.exists():
        return None
    try:
        meta = strict_json(_input_snapshot(path, label='Metadata'))
    except ValueError:
        raise TerraformRunnerError('Invalid backend metadata; no local fallback') from None
    params = meta.get('params', {})
    if not isinstance(params, dict):
        raise TerraformRunnerError('Invalid backend metadata; no local fallback')
    try:
        from src.python.utils import _legacy_metadata_is_local
        block = params.get('terraform_state', {})
        if not isinstance(block, dict):
            raise ValueError()
        if params.get('state_backend') != 'gcs' and block.get('backend') != 'gcs':
            if not all(_legacy_metadata_is_local(meta.get(section, {})) for section in ('params', 'input_params')):
                raise ValueError()
            return None
        spec = BackendSpec.from_dict(params['terraform_state'], cloud=params['cloud'])
        name = params['deployment_name']
        scope = params['project']
        identity = spec.identity(scope, name)
        if name != deployment_name or spec.backend != 'gcs' or params.get('state_backend') not in (None, 'gcs'):
            raise ValueError()
        for section in ('params', 'input_params'):
            fields = dict(meta.get(section, {}))
            if fields.pop('state_backend', 'gcs') != 'gcs':
                raise ValueError()
            selected = fields.pop('terraform_state', None)
            if selected is not None and BackendSpec.from_dict(selected, cloud='gcp') != spec:
                raise ValueError()
            if not _legacy_metadata_is_local(fields):
                raise ValueError()
        runtime = params.get('backend_runtime', {})
        if runtime and (runtime.get('identity') != identity or runtime.get('status') not in ('configured', 'active')):
            raise ValueError()
        if runtime.get('status') == 'active' and (not isinstance(runtime.get('lineage'), str) or not runtime['lineage'].strip()):
            raise ValueError()
        if runtime.get('lineage') is not None and (not isinstance(runtime['lineage'], str) or not runtime['lineage'].strip()):
            raise ValueError()
        return BackendRecord(spec, scope, name, runtime.get('status', 'configured'), runtime.get('lineage'))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise TerraformRunnerError('Invalid or mismatched saved GCS backend; no local fallback') from None


def gcs_object_names(record, environment):
    """Metadata-only GCS read using GOOGLE_OAUTH_ACCESS_TOKEN or ordinary ADC.

    ADC token refresh is delegated to the supported gcloud command, including
    GOOGLE_APPLICATION_CREDENTIALS. No login, principal-equality attestation,
    object contents, credential persistence, state writes or redirects here.
    A denied/missing bucket is an error, NEVER evidence of an empty destination.
    """
    import http.client
    import subprocess
    from urllib.parse import quote, urlencode

    connection = None
    try:
        token = environment.get('GOOGLE_OAUTH_ACCESS_TOKEN')
        if not token:
            result = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token', '--quiet'],
                env=dict(environment), shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if result.returncode:
                raise ValueError()
            token = result.stdout.decode('utf-8').strip()
        if not isinstance(token, str) or not token or len(token) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError()
        identity = record.identity
        query = urlencode({'prefix': identity['object_key'], 'maxResults': 100,
                           'fields': 'items(name),nextPageToken'})
        connection = http.client.HTTPSConnection('storage.googleapis.com', timeout=60)
        connection.request('GET', '/storage/v1/b/' + quote(identity['destination']['bucket'], safe='') + '/o?' + query,
                           headers={'Authorization': 'Bearer ' + token})
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 1024 * 1024:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('nextPageToken') or not isinstance(data.get('items', []), list):
            raise ValueError()
        names = set()
        for item in data.get('items', []):
            name = item['name']
            if not isinstance(name, str) or not name.startswith(identity['object_key']):
                raise ValueError()
            names.add(name)
        return names
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, subprocess.SubprocessError):
        raise TerraformRunnerError('Cannot verify GCS destination metadata with ambient authentication; no local fallback') from None
    finally:
        if connection is not None:
            connection.close()


def _persist_initialized_record(record, lineage, state_root):
    """Pin state created by this init, without claiming apply succeeded."""
    path = Path(state_root).absolute() / record.deployment_name / 'meta.json'
    if load_backend_record(record.deployment_name, state_root=state_root) != record:
        raise TerraformRunnerError('Backend metadata changed during initialization')
    meta = strict_json(_input_snapshot(path, label='Metadata'))
    updated = replace(record, lineage=lineage)
    meta['params']['backend_runtime'] = {'identity': updated.identity, 'status': updated.status,
                                       'lineage': updated.lineage}
    write_private_metadata(path, meta)
    return updated


def write_private_metadata(path, meta):
    """Atomic owner-only metadata publication with file and directory fsync."""
    path = Path(path)
    _no_symlinks(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(meta, stream, indent=4)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise TerraformRunnerError('Cannot persist deployment metadata; recovery review required') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def runtime_guard(record, *, state_root, environment=None, read_only=False):
    """Bind saved destination, occupancy and existing protocol fences.

    This is not a distributed reservation. New creates require absent state;
    Terraform native locking and stale-saved-plan checks close state write races.
    Preexisting protected claims/manifests require the original guarded service.
    """
    environment = dict(os.environ if environment is None else environment)

    initialized_lineage = record.lineage
    new_destination = False
    def guard(runner, operation):
        nonlocal record, initialized_lineage, new_destination
        if read_only and operation not in ('pre-init', 'init'):
            raise TerraformRunnerError('Read-only backend context cannot mutate state')
        saved = load_backend_record(record.deployment_name, state_root=state_root)
        if saved != record or json.loads(runner.backend_identity) != record.identity:
            raise TerraformRunnerError('Saved backend selection changed; discard this operation')
        names = gcs_object_names(record, environment)
        key = record.identity['object_key']
        if any(key + suffix in names for suffix in ('.isaac-claim-v1.json',
                '.isaac-manifest-v1.json', '.isaac-relocation-v1.json')):
            raise TerraformRunnerError('Protected remote claim/migration record requires its supervised protocol')
        if record.status == 'configured':
            if initialized_lineage and key not in names:
                raise TerraformRunnerError('Previously initialized GCS state is missing; recovery review required')
            if operation == 'pre-init':
                if key in names and not initialized_lineage:
                    raise TerraformRunnerError('GCS destination is occupied; explicit attachment/migration is required')
                if read_only and key not in names:
                    raise TerraformRunnerError('GCS deployment has no initialized state to read')
                new_destination = key not in names
            elif key in names:
                state = runner.pull_state()
                if (not (new_destination or initialized_lineage) or state.get('resources') != []
                        or state.get('outputs') != {} or type(state.get('serial')) is not int
                        or state['serial'] not in (0, 1)
                        or (initialized_lineage and state.get('lineage') != initialized_lineage)):
                    raise TerraformRunnerError('GCS destination is occupied; explicit attachment/migration is required')
                initialized_lineage = state['lineage']
                if record.lineage is None:
                    record = _persist_initialized_record(record, initialized_lineage, state_root)
        elif record.status == 'active':
            if key not in names or (operation != 'pre-init' and runner.pull_state().get('lineage') != record.lineage):
                raise TerraformRunnerError('Saved GCS state is missing or its lineage changed; recovery review required')
        else:
            raise TerraformRunnerError('Unknown backend runtime status; recovery review required')
    return guard


@contextmanager
def record_runner(record, *, state_root, terraform_root=None, read_only=False,
                  environment=None, terraform_binary='terraform'):
    """Yield an uninitialized context for an exact saved metadata selection.

    Workload operations snapshot state_root/name/.tfvars and the reviewed cloud
    source allowlist. Output reads need neither workload sources nor tfvars.
    This never loads an executable source location from saved metadata.
    """
    environment = dict(os.environ if environment is None else environment)
    with tempfile.TemporaryDirectory(prefix='isaac-backend-read-') as root:
        if read_only:
            source = Path(root)
            (source / 'main.tf').write_text('terraform {}\n')
            sources = ['main.tf']
            variables_file = None
        else:
            if terraform_root is None:
                raise TerraformRunnerError('Explicit reviewed Terraform root is required')
            source = Path(terraform_root).absolute() / record.backend_spec.cloud
            sources = workstation_source_files(record.backend_spec.cloud)
            variables_file = Path(state_root).absolute() / record.deployment_name / '.tfvars'
        with TerraformRunner(source_root=source, source_files=sources,
                backend_spec=record.backend_spec, target_scope=record.target_scope,
                deployment_name=record.deployment_name, state_root=Path(state_root).absolute(),
                variables_file=variables_file, environment=environment,
                terraform_binary=terraform_binary,
                staging_root=Path(state_root).absolute() / '.terraform-operations',
                remote_guard=runtime_guard(record, state_root=state_root, environment=environment,
                                           read_only=read_only)) as runner:
            yield runner

