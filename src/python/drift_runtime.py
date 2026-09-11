"""Explicit approved local drift runtime; no remote lifecycle enablement.

The config is trusted controller metadata, not an authorization proof. It binds
an exact local path/current lineage+serial to an immutable last-applied receipt.
No latest-checkout fallback, credentials, arbitrary executable or ready flag.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from src.python.backend_selection import load_profile_yaml
from src.python.deployment_baseline import BaselineStore, BaselineError, _directory, _read_at, _tree_write
from src.python.deployment_manifest import strict_json, StateSummary
from src.python.drift_config import DriftConfig, SCOPES, strict_block
from src.python.drift_detector import DriftDetector, Preflight
from src.python.drift_report import make_report, digest
from src.python.terraform_backend import BackendSpec
from src.python.terraform_runner import TerraformRunner, TerraformRunnerError


def check(config):
    """Validate approved artifact storage before any Terraform process starts."""
    if config.report_root is not None and any(
            config.report_root.is_relative_to(private) or private.is_relative_to(config.report_root)
            for private in (config.state_root, config.baseline_store)):
        raise RuntimeConfigError('Report root must be separate from state and baseline storage')
    reports = ReportStore(config.report_root) if config.report_root is not None else None
    report = _check(config)
    if reports is not None:
        from src.python.drift_history import HistoryStore, report_identity
        # HistoryStore owns a dedicated root: artifacts cannot be mixed into
        # its strictly bounded directory. It is local evidence, not transport
        # or an independently observed scheduler heartbeat.
        history = HistoryStore(config.report_root / 'history', identity=report_identity(report),
                               retention_seconds=config.drift.retention_days * 86400)
        history.record(report, received_at=int(time.time()))
        reports.save(report)
    return report


class ReportStore:
    """Immutable sanitized artifacts alongside a separate bounded history.

    An explicit dedicated absolute approved root is mandatory. The history
    lives in root/history, with no heartbeat fabrication, automatic artifact
    deletion, cloud transport, or notifications.
    """
    def __init__(self, root):
        self.root = _path(str(root))
        with _directory(self.root, private=True, create=True):
            pass

    def save(self, report):
        from src.python.drift_history import validate_report
        sanitized = validate_report(report)
        raw = json.dumps(sanitized, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        name = 'report-' + hashlib.sha256(raw).hexdigest() + '.json'
        with _directory(self.root, private=True) as directory:
            pending = 'pending-' + uuid.uuid4().hex
            try:
                _tree_write(directory, pending, raw)
                try:
                    os.link(pending, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError:
                    if _read_at(directory, name, private=True) != raw:
                        raise ValueError('Report artifact collision; diagnostics withheld') from None
            finally:
                try:
                    os.unlink(pending, dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.fsync(directory)
        return self.root / name


def _check(config):
    """Check an explicitly approved config, deriving readiness from local evidence.

    BaselineStore currently has no public state-summary reader. Its verified
    _record(ref) is used narrowly for the applied lineage/serial binding; never
    read an unverified receipt or infer identity from the current checkout.
    """
    now = int(time.time())
    identity = config.backend_spec.identity(config.target_scope, config.deployment)
    if config.backend_spec.backend == 'local':
        identity['local_state_path'] = str(config.local_state_path)
    backend_digest = digest(identity)
    baseline = None
    def incomplete(status='partial', reason=None):
        report = make_report(deployment=config.deployment, scope=config.scope, baseline=baseline,
                           backend_digest=backend_digest, lineage=config.expected_lineage, serial=None,
                           observed_at=now, expires_at=now + 300, now=int(time.time()), status=status)
        if reason:
            report['coverage']['unsupported'].append(reason)
        return report
    if not config.drift.enabled:
        return incomplete('not_run')
    if config.backend_spec.backend != 'local':
        return incomplete(reason='remote_backend_controller_review_and_service_release_gate_required')
    if config.scope != 'workstation_infrastructure':
        return incomplete(reason='scope_adapter_required')
    if config.baseline_ref is None or not config.baseline_store.exists():
        return incomplete(reason='applied_baseline_unavailable')
    try:
        store = BaselineStore(config.baseline_store)
        receipt = store.load(config.baseline_ref)
        baseline = receipt.baseline
        binding = store._record(config.baseline_ref)['state']
        if (binding['lineage'] != config.expected_lineage or binding['serial'] > config.expected_serial):
            return incomplete('identity_mismatch')
        with tempfile.TemporaryDirectory(prefix='isaac-drift-') as temporary:
            reconstructed = store.reconstruct(config.baseline_ref, Path(temporary) / 'recipe')
            if reconstructed.baseline != baseline:
                return incomplete()
            # Conservative lexical dependency gate, not an HCL resolver. False
            # positives (including comments) are blocked, never silently healthy.
            for name in reconstructed.source_files:
                if name == '.terraform.lock.hcl':
                    continue
                text = (reconstructed.source_root / name).read_text()
                if name.endswith('.json'):
                    text = json.dumps(json.loads(text), ensure_ascii=False)
                if re.search(r'\bmodule\b', text):
                    return incomplete(reason='module_resolver_required')
                if ('.terraform.lock.hcl' not in reconstructed.source_files
                        and re.search(r'\b(?:resource|data|provider|required_providers)\b', text)):
                    return incomplete(reason='pinned_dependencies_required')
            snapshot = _local_snapshot(config)
            def preflight(**kwargs):
                current = _local_snapshot(config)
                if current != snapshot:
                    raise TerraformRunnerError('Local evidence changed')
                return Preflight('ready', backend_digest, digest(baseline.to_dict()),
                                 config.expected_lineage, config.expected_serial)
            @contextmanager
            def factory(**limits):
                with TerraformRunner(source_root=reconstructed.source_root,
                        source_files=reconstructed.source_files, variables_file=reconstructed.variables_file,
                        backend_spec=config.backend_spec, target_scope=config.target_scope,
                        deployment_name=config.deployment, state_root=config.state_root, **limits) as runner:
                    # Recheck after acquiring the same controller lock used by
                    # local lifecycle operations, before even Terraform version.
                    if _local_snapshot(config) != snapshot:
                        raise TerraformRunnerError('Local evidence changed')
                    yield _CheckedRunner(runner, config, snapshot)
            return DriftDetector(config=config.drift, runner_factory=factory, preflight=preflight).check(
                deployment=config.deployment, scope=config.scope, baseline=baseline,
                backend_digest=backend_digest, expected_lineage=config.expected_lineage)
    except LocalIdentityError:
        return incomplete('identity_mismatch')
    except BaselineError:
        return incomplete(reason='applied_baseline_unavailable')
    except (OSError, ValueError, TypeError, KeyError, TerraformRunnerError):
        return incomplete('error')


class LocalIdentityError(ValueError):
    pass


def _local_snapshot(config):
    # Directory fds pin every component, reject symlinks/untrusted ownership;
    # retirement markers fail closed even when unreadable, empty or symlinked.
    with _directory(config.local_state_path.parent, private=True) as directory:
        for marker in ('migration.json', 'relocation.json', '.tfstate.retired',
                       'backend.json', '.isaac-claim-v1.json', 'errored.tfstate'):
            try:
                os.stat(marker, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise LocalIdentityError('Local lifecycle metadata requires explicit reconciliation')
        raw = _read_at(directory, '.tfstate', private=True)
    state = strict_json(raw)
    summary = StateSummary.from_state(state)
    if (summary.lineage != config.expected_lineage or summary.serial != config.expected_serial):
        raise LocalIdentityError('Local state binding differs from approved configuration')
    return hashlib.sha256(raw).hexdigest()


class _CheckedRunner:
    """Read-only runner surface, with current serial and lifecycle revalidation."""
    def __init__(self, runner, config, snapshot):
        self.runner, self.config, self.snapshot = runner, config, snapshot
        self.backend_identity = runner.backend_identity
        self.local_state_path = runner.local_state_path

    def _verify(self):
        if _local_snapshot(self.config) != self.snapshot:
            raise TerraformRunnerError('Local evidence changed during check')

    def init(self):
        self._verify()
        self.runner.init()

    def pull_state(self):
        self._verify()
        state = self.runner.pull_state()
        if (state['lineage'] != self.config.expected_lineage or state['serial'] != self.config.expected_serial):
            raise TerraformRunnerError('Pulled state identity changed')
        return state

    def plan(self):
        self._verify()
        return self.runner.plan()

    def plan_json(self, plan):
        document = self.runner.plan_json(plan)
        self._verify()
        return document


class RuntimeConfigError(ValueError):
    """Public diagnostics deliberately exclude configuration values."""


def _path(value):
    if (not isinstance(value, str) or not value.startswith('/') or len(value) > 4096
            or not re.fullmatch(r'/[A-Za-z0-9_./ -]+', value)
            or any(part in ('.', '..') for part in value.split('/'))
            or str(Path(value)) != value):
        raise ValueError()
    return Path(value)


@dataclass(frozen=True)
class RuntimeConfig:
    deployment: str
    cloud: str
    backend_spec: BackendSpec
    target_scope: str | None
    state_root: Path
    local_state_path: Path
    baseline_store: Path
    baseline_ref: str | None
    expected_lineage: str
    expected_serial: int
    scope: str
    drift: DriftConfig
    report_root: Path | None = None

    @classmethod
    def from_dict(cls, data):
        try:
            required = {'schema_version', 'deployment', 'cloud', 'backend_config', 'target_scope',
                        'state_root', 'local_state_path', 'baseline_store', 'baseline_ref',
                        'expected_lineage', 'expected_serial', 'scope', 'drift'}
            strict_block(data, required | {'report_root'})
            if not required <= data.keys() or type(data['schema_version']) is not int or data['schema_version'] != 1:
                raise ValueError()
            if not isinstance(data['backend_config'], dict) or not isinstance(data['drift'], dict):
                raise ValueError()
            backend = BackendSpec.from_dict(data['backend_config'], cloud=data['cloud'])
            backend.identity(data['target_scope'], data['deployment'])
            root, path, store = (_path(data[name]) for name in ('state_root', 'local_state_path', 'baseline_store'))
            if path != root / data['deployment'] / '.tfstate':
                raise ValueError()
            if (not isinstance(data['expected_lineage'], str) or not re.fullmatch(
                    r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', data['expected_lineage'])
                    or type(data['expected_serial']) is not int or data['expected_serial'] < 0):
                raise ValueError()
            ref = data['baseline_ref']
            if ref is not None and (not isinstance(ref, str) or not re.fullmatch(r'baseline-[0-9a-f]{64}', ref)):
                raise ValueError()
            policy = DriftConfig.from_dict(data['drift'])
            if policy.baseline_ref not in (None, ref) or data['scope'] not in SCOPES:
                raise ValueError()
            if policy.enabled and data['scope'] not in policy.scopes:
                raise ValueError()
            policy = DriftConfig.from_dict({**data['drift'], 'baseline_ref': ref})
            report_root = _path(data['report_root']) if 'report_root' in data else None
            return cls(data['deployment'], data['cloud'], backend, data['target_scope'], root, path,
                       store, ref, data['expected_lineage'], data['expected_serial'], data['scope'], policy, report_root)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise RuntimeConfigError('Invalid runtime configuration; values withheld') from None

    @classmethod
    def load(cls, path):
        try:
            return cls.from_dict(load_profile_yaml(path))
        except (ValueError, OSError):
            raise RuntimeConfigError('Invalid runtime configuration; values withheld') from None
