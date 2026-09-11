"""Explicit, single-use, supervised Terraform backend migration.

This service is not invoked by profile selection or normal deployment. Protected
claims and controller leases fence cooperating clients ONLY. The mandatory
operator attestation is not proof of IAM revocation: success always reports
supervised_retirement_required until separately authorized old-writer denial and
provider-specific retirement acceptance have been performed. No auto-unlock,
retry, state push, adoption, restore, backend deletion or recovery cleanup exists.

All durable recovery directories contain SECRET state. The caller must select a
protected, durable admin_root (not a temporary workload staging volume).
recovery-required.json supersedes completed.json after a late failure/expiry;
its authority is source, destination, or indeterminate, backed by confirmed
phase receipts. A false source_authoritative result alone does not establish
destination authority. If journal storage fails, retain all available evidence
and reconcile; no write is retried or rolled back.
"""
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import math
import re
import stat
import subprocess
import time
from typing import Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from src.python.backend_object_store import ObjectConflict, ProtectedObjectCoordinator, StoredObject
from src.python.terraform_backend import BackendSpec, validate_terraform_version
from src.python.terraform_runner import _input_snapshot, _no_symlinks, TerraformRunner
from src.python.deployment_manifest import (DeploymentManifest, LocalManifestStore,
    RelocationRecord, StateSummary, canonical, strict_json, object_location)
from src.python.deployment_state import StateObservation, StateStatus, VerifiedScope


class MigrationError(RuntimeError):
    """Sanitized refusal before mutation; never include provider diagnostics."""


@dataclass(frozen=True)
class SupervisedApproval:
    source_identity: str
    destination_identity: str
    operator: str
    source_write_fence_attestation: str
    acknowledge_unmanaged_writer_risk: bool
    maintenance_deadline: datetime
    acknowledge_loss_of_shared_coordination: bool = False


@dataclass(frozen=True)
class MigrationResult:
    status: str
    recovery_needed: bool
    source_authoritative: bool
    recovery_directory: Path
    destination_manifest: DeploymentManifest | None = field(default=None, repr=False)


@dataclass(frozen=True)
class MigrationEndpoint:
    backend_spec: BackendSpec
    target_scope: str | None
    deployment_name: str
    coordinator: Any
    verify_scope: Callable = field(repr=False)
    state_root: Path | None = None

    @property
    def identity(self):
        return self.backend_spec.identity(self.target_scope, self.deployment_name)

    @property
    def exact_identity(self):
        return {"backend_identity": self.identity,
                "local_state_path": str(self.local_state_path) if self.local_state_path else None}

    @property
    def local_state_path(self):
        if self.backend_spec.backend != "local":
            return None
        if self.state_root is None or not Path(self.state_root).is_absolute():
            raise MigrationError("Local migration requires an explicit absolute state root")
        path = Path(self.state_root) / self.deployment_name / ".tfstate"
        _no_symlinks(path)
        self.backend_spec.backend_config(self.target_scope, self.deployment_name, str(path))
        return path

    @property
    def location(self):
        return ("local", str(self.local_state_path)) if self.local_state_path else object_location(self.identity)

    @classmethod
    def local(cls, backend_spec, target_scope, deployment_name, *, state_root):
        if backend_spec.backend != "local":
            raise MigrationError("Local adapter requires a local backend")
        store = LocalMigrationStore(backend_spec.identity(target_scope, deployment_name), state_root)
        def verify(identity):
            # Local disk protection is checked on every read/write. No cloud
            # authentication is performed or claimed for this offline endpoint.
            return VerifiedScope(canonical(identity), "local-owner")
        return cls(backend_spec, target_scope, deployment_name,
                   ProtectedObjectCoordinator(store, authorize=lambda *_: None), verify, Path(state_root))

    def scope(self):
        if self.coordinator.identity != self.identity:
            raise MigrationError("Protected object store identity mismatch")
        if self.local_state_path and (not isinstance(self.coordinator.store, LocalMigrationStore)
                or self.coordinator.store._files.root != self.state_root):
            raise MigrationError("Local protected store and approved physical path differ")
        verified = self.verify_scope(self.identity)
        if (not isinstance(verified, VerifiedScope) or verified.identity != canonical(self.identity)
                or not verified.principal):
            raise MigrationError("Independent workload/storage/protection verification required")
        return verified

    def observe(self):
        self.scope()
        self.coordinator.require_attachable()
        state = self.coordinator.store.read("state")
        if state is None:
            raise MigrationError("Authoritative source state is unavailable")
        summary = StateSummary.from_state(strict_json(state.data))
        return StateObservation(StateStatus.POPULATED if summary.addresses else StateStatus.REACHABLE_EMPTY,
                                canonical(self.exact_identity), summary)


def _persist(directory, name, data):
    """Create-only, durable private recovery evidence; never overwrite a receipt."""
    fd = os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalMigrationStore:
    """Protected local metadata CAS; Terraform alone writes active state.

    Migration-only enrollment/retirement is explicit. This adapter does not
    magically retrofit legacy local runners with relocation checks: all such
    clients must remain quiescent under the supervised operator attestation.
    """
    _names = {"state": ".tfstate", "manifest": "backend.json",
              "claim": ".isaac-claim-v1.json", "relocation": "relocation.json"}

    def __init__(self, identity, root):
        self._identity = canonical(identity)
        self._files = LocalManifestStore(root)

    @property
    def identity(self):
        return strict_json(self._identity)

    def _read(self, directory, kind):
        name = self._names[kind]
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            self._files._regular(stream.fileno())
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise MigrationError("Local migration receipt/state exceeds bounded size")
        return StoredObject(data, hashlib.sha256(data).hexdigest())

    def read(self, kind):
        with self._files._directory(self.identity["deployment_name"], create=True) as directory:
            return self._read(directory, kind)

    def write(self, kind, data, *, expected_generation=None):
        if kind not in ("manifest", "claim", "relocation") or not isinstance(data, bytes):
            raise MigrationError("Only protected metadata writes are supported")
        if kind == "relocation" and expected_generation is not None:
            raise MigrationError("Retirement markers are immutable")
        if len(data) > 1024 * 1024:
            raise MigrationError("Metadata exceeds bounded size")
        with self._files._directory(self.identity["deployment_name"], create=True) as directory:
            previous = self._read(directory, kind)
            if (previous.generation if previous else None) != expected_generation:
                raise ObjectConflict("Local protected metadata CAS conflict")
            if kind == "claim" and strict_json(data).get("status") in ("pending", "unknown"):
                # Fixed legacy fence name agreed with the lifecycle integration.
                # Create-only and retained on ALL outcomes, never a redirect.
                marker = canonical({"schema_version": 1, "status": "supervised_migration_pending",
                    "identity": self.identity, "local_state_path": str(self._files.root / self.identity["deployment_name"] / ".tfstate"),
                    "unmanaged_writer_fence": "operator_attestation_only"}).encode()
                marker_fd = os.open("migration.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                    0o600, dir_fd=directory)
                with os.fdopen(marker_fd, "wb") as stream:
                    stream.write(marker)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory)
            temporary = ".migration-" + str(uuid.uuid4())
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._names[kind], src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            return hashlib.sha256(data).hexdigest()

    def retire_state(self, expected):
        with self._files._directory(self.identity["deployment_name"]) as directory:
            if self._read(directory, "relocation") is None or self._read(directory, "state") != expected:
                raise MigrationError("Local source changed before retirement")
            # link is create-only; never overwrite an older recovery copy.
            os.link(".tfstate", ".tfstate.retired", src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
            os.fsync(directory)
            os.unlink(".tfstate", dir_fd=directory)
            os.fsync(directory)


class _MigrationGuard:
    def __init__(self, adapter, check, deadline):
        self._adapter, self.check = adapter, check
        self.deadline = deadline
        self.consumed = False
        self.authorized = False

    def authorize(self, adapter):
        if self.consumed:
            raise MigrationError("Migration capability already consumed")
        self.consumed = True
        if adapter is not self._adapter:
            raise MigrationError("Migration adapter identity mismatch")
        self.check()
        self.authorized = True


class BackendMigration:
    """Trusted policy/transport dependencies; never deserialize callable hooks.

    verify_scope(identity) must independently authenticate workload scope AND
    storage ownership/protection, returning VerifiedScope. The coordinator's
    authorize hook independently gates protected metadata writes. lease_factory
    is an optional controller-lock context factory; production uses ordered
    local controller leases, NOT a claim of distributed Terraform locks.
    """
    def __init__(self, source, destination, *, admin_root, adapter, lease_factory=None, lock_root=None):
        self.source, self.destination = source, destination
        self.admin_root = Path(admin_root)
        self.adapter = adapter
        self.lock_root = Path(lock_root) if lock_root is not None else Path(f"/tmp/isaac-tf-locks-{os.getuid()}")
        self.lease_factory = lease_factory or self._lease
        self._used = False

    @contextmanager
    def _lease(self, endpoint, deadline):
        """Same lock identity/root as TerraformRunner; bounded, no stale unlink."""
        root = self.lock_root
        if not root.is_absolute():
            raise MigrationError("Controller lock root must be absolute")
        _no_symlinks(root)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise MigrationError("Controller lock root must be private and owned")
        identity = ("local:" + str(endpoint.local_state_path) if endpoint.local_state_path
                    else canonical(endpoint.identity))
        fd = os.open(root / (hashlib.sha256(identity.encode()).hexdigest() + ".lock"),
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise MigrationError("Unsafe controller lease file")
            while True:
                remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    raise MigrationError("Migration controller lease deadline expired")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(0.05, remaining))
            yield
        finally:
            os.close(fd)

    def _approval(self, approval):
        if (not isinstance(approval, SupervisedApproval)
                or approval.source_identity != canonical(self.source.exact_identity)
                or approval.destination_identity != canonical(self.destination.exact_identity)
                or not isinstance(approval.operator, str) or not approval.operator.strip()
                or len(approval.operator) > 256
                or not isinstance(approval.source_write_fence_attestation, str)
                or not approval.source_write_fence_attestation.strip()
                or len(approval.source_write_fence_attestation) > 4096
                or approval.acknowledge_unmanaged_writer_risk is not True):
            raise MigrationError("Explicit exact-identity approval and supervised write-fence attestation required")
        if (self.source.backend_spec.backend != "local" and self.destination.backend_spec.backend == "local"
                and approval.acknowledge_loss_of_shared_coordination is not True):
            raise MigrationError("Remote-to-local migration loses shared-controller coordination; explicit acknowledgement required")
        self._deadline(approval)

    def _deadline(self, approval):
        if (not isinstance(approval.maintenance_deadline, datetime)
                or approval.maintenance_deadline.tzinfo is None
                or datetime.now(timezone.utc) >= approval.maintenance_deadline):
            raise MigrationError("Supervised maintenance deadline expired; retain both receipts")

    def migrate(self, *, source_manifest, source_observation, approval):
        if self._used:
            raise MigrationError("Migration service is single-use; reconcile before any new attempt")
        self._used = True
        source, destination = self.source, self.destination
        recovery = None
        authority = "source"
        attempted_phase = "preflight"
        last_confirmed_phase = "preflight"
        confirmed_receipts = {}
        try:
            self._approval(approval)
            if (any(source.identity[key] != destination.identity[key]
                    for key in ("cloud", "target_scope", "deployment_name"))
                    or source.location == destination.location):
                raise MigrationError("Migration must preserve workload identity and change physical location")
            with ExitStack() as locks:
                for endpoint in sorted((source, destination), key=lambda e: canonical(e.exact_identity)):
                    locks.enter_context(self.lease_factory(endpoint, approval.maintenance_deadline))
                scopes = (source.scope(), destination.scope())
                active = source.coordinator.require_attachable()
                source_state = source.coordinator.store.read("state")
                source_claim = source.coordinator.store.read("claim")
                protected_manifest = source.coordinator.store.read("manifest")
                if (source_state is None or protected_manifest is None or source_claim is None
                        or DeploymentManifest.from_json(protected_manifest.data) != source_manifest
                        or source_manifest.identity != source.identity):
                    raise MigrationError("Authoritative source manifest/state is missing or mismatched")
                summary = StateSummary.from_state(strict_json(source_state.data))
                if active["lineage"] != summary.lineage or strict_json(source_claim.data) != active:
                    raise MigrationError("Source ownership claim/state lineage changed")
                binding = source_manifest.to_dict()["state"]
                StateSummary(binding["lineage"], binding["serial"], tuple(binding["addresses"])).verify(summary)
                if source.observe() != source_observation or source_observation.summary != summary:
                    raise MigrationError("Authoritative source observation changed")
                last_confirmed_phase = "source_verified"
                data = source_manifest.to_dict()
                data.update(identity=destination.identity, backend_config=destination.backend_spec.to_dict())
                intended = DeploymentManifest.from_dict(data)
                # Pin recovery before the first protected metadata mutation.
                with LocalManifestStore(self.admin_root)._directory("migrations", create=True) as parent:
                    operation = str(uuid.uuid4())
                    os.mkdir(operation, 0o700, dir_fd=parent)
                    os.fsync(parent)
                recovery = self.admin_root / "migrations" / operation
                for name, raw in (("source-state.json", source_state.data),
                                  ("source-manifest.json", source_manifest.canonical_json().encode()),
                                  ("destination-manifest.json", intended.canonical_json().encode()),
                                  ("source-claim.json", source_claim.data)):
                    _persist(recovery, name, raw)
                _persist(recovery, "approval.json", canonical({
                    "source": source.exact_identity, "destination": destination.exact_identity,
                    "operator": approval.operator, "source_write_fence_attestation": approval.source_write_fence_attestation,
                    "acknowledge_unmanaged_writer_risk": approval.acknowledge_unmanaged_writer_risk,
                    "maintenance_deadline": approval.maintenance_deadline.isoformat(),
                    "acknowledge_loss_of_shared_coordination": approval.acknowledge_loss_of_shared_coordination}).encode())
                attempted_phase = "destination_reservation"
                reservation = destination.coordinator.claim_new(operation)
                last_confirmed_phase = "destination_reserved"
                _persist(recovery, "destination-claim.json", canonical(reservation.__dict__).encode())
                attempted_phase = "source_freeze"
                source.coordinator._authorized("freeze_source")
                frozen = dict(active, status="unknown")
                frozen_generation = source.coordinator.store.write("claim", canonical(frozen).encode(),
                    expected_generation=source_claim.generation)
                _persist(recovery, "source-freeze.json", canonical({"generation": frozen_generation,
                    "status": "supervised-source-freeze", "identity": source.exact_identity}).encode())

                def revalidate(*, copied=None):
                    self._deadline(approval)
                    if (source.scope(), destination.scope()) != scopes:
                        raise MigrationError("Authenticated scope changed")
                    source.coordinator._authorized("migration_source")
                    if source.coordinator.store.read("relocation") is not None:
                        raise MigrationError("Source retirement changed")
                    claim = source.coordinator.store.read("claim")
                    if (claim is None or claim.generation != frozen_generation or strict_json(claim.data) != frozen
                            or source.coordinator.store.read("state") != source_state
                            or source.coordinator.store.read("manifest") != protected_manifest):
                        raise MigrationError("Frozen source evidence changed")
                    if copied is None:
                        destination.coordinator.verify_creation_state(reservation)
                    else:
                        destination.coordinator.assert_claim(reservation)
                        if destination.coordinator.store.read("state") != copied:
                            raise MigrationError("Copied destination changed during verification")

                last_confirmed_phase = "source_frozen"
                attempted_phase = "native_copy"
                guard = _MigrationGuard(self.adapter, revalidate, approval.maintenance_deadline)
                self.adapter.migrate(source, destination, guard=guard, recovery_directory=recovery)
                if not guard.authorized:
                    raise MigrationError("Migration adapter did not authorize the copy")
                self._deadline(approval)
                copied = destination.coordinator.store.read("state")
                if copied is None:
                    raise MigrationError("Destination state is unavailable after copy")
                after = StateSummary.from_state(strict_json(copied.data))
                summary.verify(after, allow_serial_advance=True)
                # Native Terraform can advance serial/change its writer version.
                # Every other field (including outputs/data/private provider
                # attributes and unknown extension fields) must be unchanged.
                before_payload, after_payload = strict_json(source_state.data), strict_json(copied.data)
                for payload in (before_payload, after_payload):
                    payload.pop("serial", None)
                    payload.pop("terraform_version", None)
                if canonical(before_payload) != canonical(after_payload):
                    raise MigrationError("Migration changed state content; retain both receipts")
                data["state"] = after.to_dict()
                published = DeploymentManifest.from_dict(data)
                revalidate(copied=copied)
                _persist(recovery, "destination-state.json", copied.data)
                _persist(recovery, "verified-destination-manifest.json", published.canonical_json().encode())
                last_confirmed_phase = "destination_verified"
                attempted_phase = "destination_manifest"
                generation = destination.coordinator._publish_manifest(published, None)
                revalidate(copied=copied)
                confirmed = destination.coordinator.store.read("manifest")
                if (confirmed is None or confirmed.generation != generation
                        or DeploymentManifest.from_json(confirmed.data) != published):
                    raise MigrationError("Destination manifest publication is unconfirmed")
                last_confirmed_phase = "destination_manifest_published"
                confirmed_receipts["destination_manifest"] = generation
                relocated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if source.local_state_path and destination.local_state_path:
                    # BackendSpec's logical local object key omits the absolute
                    # root. Do not pretend its RelocationRecord can distinguish
                    # two local directories: retain BOTH exact physical paths.
                    record_bytes = canonical({"schema_version": 1, "kind": "local-migration-retirement",
                        "source_identity": source.exact_identity, "destination_identity": destination.exact_identity,
                        "source_state": summary.to_dict(), "destination_state": after.to_dict(),
                        "relocated_at": relocated_at, "retirement": "supervised_retirement_required"}).encode()
                else:
                    record_bytes = RelocationRecord.create(source_manifest, published,
                        relocated_at=relocated_at).canonical_json().encode()
                source.coordinator._authorized("publish_relocation")
                # A transport may commit and then fail. Once retirement is
                # attempted, never infer source authority from an exception.
                attempted_phase = "source_retirement"
                authority = "indeterminate"
                retirement_generation = source.coordinator.store.write("relocation", record_bytes, expected_generation=None)
                self._deadline(approval)
                retirement = source.coordinator.store.read("relocation")
                if retirement != StoredObject(record_bytes, retirement_generation):
                    raise MigrationError("Source retirement publication is unconfirmed")
                last_confirmed_phase = "source_retired"
                confirmed_receipts["source_retirement"] = retirement_generation
                _persist(recovery, "source-retirement.json", canonical({"generation": retirement_generation,
                    "record": strict_json(record_bytes)}).encode())
                self._deadline(approval)
                claim = destination.coordinator.assert_claim(reservation)
                claim.update(status="active", lineage=after.lineage)
                self._deadline(approval)
                attempted_phase = "destination_activation"
                activation = destination.coordinator.store.write("claim", canonical(claim).encode(),
                                                                 expected_generation=reservation.generation)
                self._deadline(approval)
                if destination.coordinator.store.read("claim") != StoredObject(canonical(claim).encode(), activation):
                    raise MigrationError("Destination activation publication is unconfirmed")
                authority = "destination"
                last_confirmed_phase = "destination_active"
                confirmed_receipts["destination_activation"] = activation
                _persist(recovery, "destination-activation.json", canonical({"generation": activation,
                    "claim": claim}).encode())
                self._deadline(approval)
                if source.local_state_path:
                    self._deadline(approval)
                    attempted_phase = "local_source_retirement"
                    source.coordinator.store.retire_state(source_state)
                    last_confirmed_phase = "local_source_retired"
                    confirmed_receipts["local_source_retirement"] = source_state.generation
                    _persist(recovery, "local-source-retired.json", canonical({"generation": source_state.generation,
                        "source": source.exact_identity, "retired_state_path": str(source.local_state_path) + ".retired"}).encode())
                self._deadline(approval)
                attempted_phase = "completion"
                _persist(recovery, "completed.json", canonical({"manifest_generation": generation,
                    "status": "supervised_retirement_required"}).encode())
                self._deadline(approval)
                return MigrationResult("supervised_retirement_required", False, False, recovery, published)
        except Exception:
            if recovery is not None:
                # A late receipt/deadline failure does not undo a publication.
                # This create-only record supersedes completed.json, if present.
                # If the recovery disk itself fails, keep all existing evidence
                # and return the conservative in-memory authority; never retry
                # remote writes or pretend the journal was persisted.
                try:
                    _persist(recovery, "recovery-required.json", canonical({
                        "status": "recovery_required", "authority": authority,
                        "source_authoritative": authority == "source",
                        "attempted_phase": attempted_phase, "last_confirmed_phase": last_confirmed_phase,
                        "confirmed_receipts": confirmed_receipts,
                        "source": source.exact_identity, "destination": destination.exact_identity}).encode())
                except Exception:
                    pass
                return MigrationResult("recovery_required", True, authority == "source", recovery)
            raise MigrationError("Migration preflight refused; no copy attempted") from None


class NativeMigrationRunner:
    """Concrete subprocess bridge, fixed argv, no arbitrary Terraform flags.

    The caller approves executable source_files and the ambient credential
    environment. Sources/optional inputs are snapshotted at construction, never
    fetched from manifest URLs. Both backend types/configs are generated from
    validated endpoints. Source initialization and default-workspace inspection
    precede a one-use guard immediately before init -migrate-state -force-copy.
    Destination plan uses refresh=false and is NEVER applied. All staging,
    errored.tfstate, private plan and state pulls remain in durable admin_root.
    """
    def __init__(self, *, source_root, source_files, environment=None,
                 terraform_binary="terraform", command_timeout=300, variables_file=None):
        root = Path(source_root)
        if not root.is_absolute():
            raise MigrationError("Approved Terraform source root must be absolute")
        files = tuple(source_files)
        if not files or len(files) != len(set(files)):
            raise MigrationError("Explicit nonempty source allowlist required")
        self._snapshots = []
        for relative in files:
            path = Path(relative)
            name = path.name.lower()
            if (path.is_absolute() or not path.parts or ".." in path.parts
                    or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts)
                    or any(part.lower() in {".terraform", "state", "credentials", ".ssh", "inventory"} for part in path.parts)
                    or any(word in name for word in ("credential", "inventory", "tfstate", "auto.tfvars"))
                    or name in {"override.tf", "override.tf.json"}
                    or name.endswith(("_override.tf", "_override.tf.json"))
                    or not (name.endswith((".tf", ".tf.json")) or name == ".terraform.lock.hcl")):
                raise MigrationError("Unsafe Terraform source allowlist")
            self._snapshots.append((path, _input_snapshot(root / path, label="Migration source")))
        self._variables = _input_snapshot(variables_file) if variables_file is not None else None
        self._variables_name = "inputs.tfvars.json" if str(variables_file).endswith(".json") else "inputs.tfvars"
        supplied = dict(os.environ if environment is None else environment)
        if supplied.get("TF_WORKSPACE", "default") != "default":
            raise MigrationError("Only default workspace migration is supported")
        self._environment = {key: value for key, value in supplied.items() if not key.startswith("TF_")}
        if (not isinstance(terraform_binary, str) or not terraform_binary or "\0" in terraform_binary
                or type(command_timeout) not in (int, float) or not math.isfinite(command_timeout)
                or command_timeout <= 0):
            raise MigrationError("Explicit valid executable and bounded timeout required")
        self._binary, self._timeout = terraform_binary, command_timeout
        self._used = False

    def migrate(self, source, destination, *, guard, recovery_directory):
        if self._used or not isinstance(guard, _MigrationGuard):
            raise MigrationError("Native migration requires a fresh controlled operation guard")
        self._used = True
        guard.check()
        base = Path(recovery_directory) / "native"
        _no_symlinks(base)
        base.mkdir(mode=0o700)
        work, data = base / "source", base / "data"
        work.mkdir(mode=0o700)
        data.mkdir(mode=0o700)
        pinned = {}
        commands = []

        def write(path, content):
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _persist(path.parent, path.name, content)
            pinned[path] = hashlib.sha256(content).hexdigest()

        for relative, content in self._snapshots:
            write(work / relative, content)
        if self._variables is not None:
            write(base / self._variables_name, self._variables)
        write(base / "terraform.rc", b"disable_checkpoint = true\n")
        environment = {**self._environment, "TF_DATA_DIR": str(data), "TF_INPUT": "0",
                       "TF_IN_AUTOMATION": "1", "TF_WORKSPACE": "default",
                       "TF_CLI_CONFIG_FILE": str(base / "terraform.rc"), "CHECKPOINT_DISABLE": "1"}
        override = work / "migration_override.tf.json"

        def configure(endpoint, label):
            if override in pinned:
                # Controlled backend-type replacement; no original source edits.
                override.unlink()
                del pinned[override]
            write(override, canonical({"terraform": {"backend": {endpoint.backend_spec.backend: {}}}}).encode())
            config = endpoint.backend_spec.backend_config(endpoint.target_scope, endpoint.deployment_name,
                str(endpoint.local_state_path) if endpoint.local_state_path else None)
            config_path = base / (label + "-backend.hcl")
            write(config_path, "\n".join(f"{key} = {json.dumps(value)}" for key, value in sorted(config.items())).encode())
            return "-backend-config=" + str(config_path)

        def execute(arguments, accepted=(0,)):
            for path, expected in pinned.items():
                if hashlib.sha256(_input_snapshot(path)).hexdigest() != expected:
                    raise MigrationError("Pinned migration inputs changed")
            for endpoint in (source, destination):
                if endpoint.local_state_path:
                    for path in (endpoint.local_state_path, Path(str(endpoint.local_state_path) + ".backup"),
                                 endpoint.local_state_path.parent / "..tfstate.lock.info"):
                        _no_symlinks(path)
            _no_symlinks(data)
            workspace_file = data / "environment"
            if workspace_file.exists() and _input_snapshot(workspace_file).strip() != b"default":
                raise MigrationError("Initialized workspace changed")
            remaining = min(self._timeout, (guard.deadline - datetime.now(timezone.utc)).total_seconds())
            if remaining <= 0:
                raise MigrationError("Supervised maintenance deadline expired")
            commands.append(arguments)
            try:
                command_environment = dict(environment)
                if arguments[:2] == ["workspace", "list"]:
                    # Terraform adds a prose override warning when this env var
                    # is set. Fresh/pinned TF_DATA_DIR still enforces default;
                    # enumerate actual workspaces without suppressing evidence.
                    command_environment.pop("TF_WORKSPACE", None)
                process = subprocess.Popen([self._binary, *arguments], cwd=work, env=command_environment,
                    shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True, umask=0o077)
                try:
                    stdout, _ = process.communicate(timeout=remaining)
                except BaseException:
                    TerraformRunner._stop_process_group(process)
                    raise
            except (OSError, subprocess.SubprocessError):
                raise MigrationError("Native Terraform operation failed or timed out; recovery retained") from None
            if process.returncode not in accepted:
                raise MigrationError("Native Terraform rejected migration operation; recovery retained")
            return stdout

        try:
            version = strict_json(execute(["version", "-json"]))["terraform_version"]
            for endpoint in (source, destination):
                validate_terraform_version(version, endpoint.backend_spec.backend)
            source_config = configure(source, "source")
            guard.check()
            lock = "-lock-timeout=" + str(min(source.backend_spec.timeout_seconds,
                                             destination.backend_spec.timeout_seconds)) + "s"
            execute(["init", "-input=false", "-no-color", lock, source_config])
            workspaces = execute(["workspace", "list", "-no-color"]).decode().splitlines()
            if [line.strip().lstrip("* ") for line in workspaces if line.strip()] != ["default"]:
                raise MigrationError("Multi-workspace migration is forbidden")
            before = execute(["state", "pull"])
            _persist(base, "source-pull.json", before)
            if strict_json(before) != strict_json((Path(recovery_directory) / "source-state.json").read_bytes()):
                raise MigrationError("Native source pull differs from the approved observation")
            destination_config = configure(destination, "destination")
            guard.authorize(self)
            execute(["init", "-migrate-state", "-force-copy", "-input=false", "-no-color", lock, destination_config])
            _persist(base, "destination-pull.json", execute(["state", "pull"]))
            plan = ["plan", "-refresh=false", "-input=false", "-no-color", "-detailed-exitcode", lock,
                    "-out=migration.plan"]
            if self._variables is not None:
                plan.append("-var-file=" + str(base / self._variables_name))
            execute(plan, accepted=(0, 2))
            raw_plan = execute(["show", "-json", "migration.plan"])
            _persist(work, "migration-plan.json", raw_plan)
            parsed = strict_json(raw_plan)
            if any(change.get("change", {}).get("actions") not in (["no-op"], ["read"])
                   for change in parsed.get("resource_changes", [])):
                raise MigrationError("Migration validation plan has unexpected resource changes")
        finally:
            # No cleanup, even on success: retain process recovery state,
            # original snapshots and both receipts for manual retirement review.
            _persist(Path(recovery_directory), "native-commands.json", canonical(commands).encode())

