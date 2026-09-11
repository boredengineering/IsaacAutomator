"""Backend-aware deployment reads and lifecycle policy.

Runner factories are trusted controller dependencies; never execute source URLs
from recovery metadata. Outputs are secret-bearing native JSON, never logs.
"""
from dataclasses import dataclass, field, replace
from enum import Enum
from copy import deepcopy
import hashlib
import json

from src.python.terraform_backend import BackendSpec
from src.python.deployment_manifest import (StateSummary, canonical, IdentityMismatch,
                                            DeploymentManifest, strict_json, digest)
from src.python.backend_object_store import (ObjectAccessDenied, ObjectStoreError, ObjectConflict,
                                             CreationClaim, CreationStateObservation)
from src.python.terraform_runner import TerraformLockError, TerraformRunnerError


class StateStatus(str, Enum):
    POPULATED = "populated"
    REACHABLE_EMPTY = "reachable-empty"
    PERMISSION_DENIED = "permission-denied"
    UNREACHABLE = "unreachable"
    IDENTITY_MISMATCH = "identity-mismatch"
    LOCKED = "locked"
    UNKNOWN = "unknown"
    DESTROYED = "destroyed"
    PARTIALLY_DESTROYED = "partially-destroyed"
    CONFIGURED_NOT_CREATED = "configured-not-created"
    ATTACHMENT_REQUIRED = "attachment-required"


class DeploymentStateError(RuntimeError):
    """Sanitized service boundary error, never underlying provider diagnostics."""


class CapabilityError(DeploymentStateError):
    """Recovery materials or a trusted integration capability are unavailable."""


@dataclass(frozen=True)
class VerifiedScope:
    """Receipt from REQUIRED independent authenticated scope verifier.

    The hook must verify workload scope AND storage owner/location/IAM. A
    manifest or self-reported profile is not evidence. This is an in-process
    trusted dependency contract, not a serializable authorization credential.
    """
    identity: str
    principal: str = field(repr=False)


@dataclass(frozen=True)
class RemoteSnapshot:
    scope: VerifiedScope
    claim_generation: str
    claim_digest: str
    state_generation: str | None
    summary: StateSummary | None
    manifest_generation: str | None
    _content_digest: bytes | None = field(default=None, repr=False)
    _runner_digest: str | None = field(default=None, repr=False)
    _creation_state: CreationStateObservation | None = field(default=None, repr=False)

    def verify_state(self, raw):
        if self.summary is None or self._runner_digest is None:
            raise IdentityMismatch("Exact state observation is required")
        self.summary.verify(StateSummary.from_state(raw))
        if _state_digest(raw) != self._runner_digest:
            raise IdentityMismatch("Runner state differs from authoritative content")


def _state_digest(raw):
    """Private Terraform v4 semantic binding, not a public state fingerprint.

    Match the raw pull_state schema, not `show -json`. Canonical JSON ignores
    object key order/whitespace only. `state pull` may rewrite the top-level
    Terraform writer version; v4 output entries may omit sensitive=false.
    Normalize ONLY those two envelope conventions. Preserve every resource,
    instance, attribute, private/provider field, array order and unknown field.
    Protected object equality separately binds unnormalized bytes + generation.
    """
    normalized = deepcopy(raw)
    normalized.pop("terraform_version", None)
    normalized["outputs"] = {key: {"sensitive": False, **entry}
                             for key, entry in normalized["outputs"].items()}
    return digest(normalized)


@dataclass(frozen=True)
class CreationReservation:
    claim: CreationClaim
    snapshot: RemoteSnapshot


@dataclass(frozen=True, repr=False, init=False)
class DeploymentOutputs:
    _json: str = field(repr=False)

    def __init__(self, entries):
        try:
            if type(entries) is not dict or any(type(key) is not str or type(item) is not dict
                    or not {"value", "type", "sensitive"} <= item.keys() or type(item["sensitive"]) is not bool
                    for key, item in entries.items()):
                raise ValueError()
            object.__setattr__(self, "_json", canonical(entries))
        except Exception:
            raise DeploymentStateError("Invalid Terraform outputs; values withheld") from None

    @classmethod
    def from_state(cls, entries):
        """Terraform v4 state omits sensitive when false; output -json does not."""
        try:
            return cls({key: {"sensitive": False, **item} for key, item in entries.items()})
        except Exception:
            raise DeploymentStateError("Invalid Terraform state outputs; values withheld") from None

    @property
    def values(self):
        return {key: item["value"] for key, item in json.loads(self._json).items()}

    @property
    def metadata(self):
        return {key: {"type": deepcopy(item["type"]), "sensitive": item["sensitive"]}
                for key, item in json.loads(self._json).items()}

    def __repr__(self):
        return "DeploymentOutputs(<secret-bearing values withheld>)"


@dataclass(frozen=True)
class StateObservation:
    status: StateStatus
    source: str
    summary: StateSummary | None = None
    outputs: DeploymentOutputs | None = field(default=None, repr=False)

    @property
    def lineage(self):
        return self.summary.lineage if self.summary else None

    @property
    def serial(self):
        return self.summary.serial if self.summary else None


@dataclass(frozen=True)
class DestroyTombstone:
    """Verified zero-managed-resource receipt, never a backend deletion request.

    The empty state binding remains in backend.json and the protected manifest;
    the operation-specific tombstone itself is returned for controller audit.
    """
    source: str
    lineage: str
    serial: int


@dataclass(frozen=True)
class MutationResult:
    infrastructure_status: str
    observation: StateObservation
    descriptor: DeploymentManifest | None = field(repr=False)
    recovery_needed: bool
    tombstone: DestroyTombstone | None = None


class RemoteMutationGuard:
    """One-use capability bound to this live context, plan and state snapshot.

    Runner integration contract: call authorize(runner, plan, operation) while
    holding the controller context lock, immediately before consuming the saved
    plan/launching Terraform apply. The runner MUST still enforce saved-plan
    integrity, native locking and Terraform's lineage/serial check. Never turn
    this into an allow_remote boolean or reuse it for another operation/context.
    Trusted adapter code is mandatory until TerraformRunner supports this hook.
    """
    def __init__(self, service, runner, plan, snapshot, operation, reservation=None):
        self._service = service
        self._runner = runner
        self._plan = plan
        self._snapshot = snapshot
        self._descriptor = service.descriptor
        self._reservation = reservation
        self._operation = operation
        self._used = False
        self._authorized = False

    @property
    def snapshot(self):
        return self._snapshot

    @property
    def consumed(self):
        return self._used

    @property
    def authorized(self):
        return self._authorized

    def authorize(self, runner, plan, operation):
        if self._used:
            raise DeploymentStateError("Mutation guard is already consumed")
        self._used = True  # Failed validation also burns the capability.
        try:
            if runner is not self._runner or plan is not self._plan or operation != self._operation:
                raise IdentityMismatch("Mutation guard context/plan/operation mismatch")
            self._service._check_runner(runner)
            current = (self._service._creation_snapshot(self._reservation.claim,
                           expected_state=self._snapshot._creation_state) if self._reservation
                       else self._service._snapshot(self._descriptor))
            if current != self._snapshot:
                raise IdentityMismatch("Scope, claim or state changed after planning")
            if self._snapshot.summary is not None:
                self._snapshot.verify_state(runner.pull_state())
            self._authorized = True
        except Exception:
            raise DeploymentStateError("Remote mutation guard rejected stale or unverified evidence") from None


class DeploymentState:
    """One explicit deployment identity; use serially, not across threads.

    Required dependencies:
      local_store: LocalManifestStore-compatible load/save (CAS local receipts).
      runner_factory(*, backend_spec, target_scope, deployment_name): returns a
        fresh TerraformRunner context with controller-approved source_files,
        variables, environment, state_root and lock_root already bound. It must
        NOT derive executable source from an untrusted manifest URL. Output-only
        attachment can use a trusted backend-only root without workload secrets.

    Remote dependencies (no implicit concrete provider construction):
      coordinator: ProtectedObjectCoordinator over a pinned CLIObjectStore.
      verify_scope(identity_dict) -> VerifiedScope: independently authenticate
        workload scope AND storage owner/location/protection. Unknown is denied.
      mutation_adapter(runner, plan, *, guard, operation): trusted runner bridge;
        call guard.authorize(runner, plan, operation) immediately before applying
        the exact saved plan under native locking. No default bridge is supplied:
        the current TerraformRunner intentionally disables remote mutations.

    verify_materials(descriptor_or_None, operation) -> None is required beyond
    outputs. It must verify approved source revision/lockfile/input material and
    operation-specific recovered secrets; raise on denied/unavailable/unknown.
    None descriptor means a new creator whose materials are independently bound
    by the caller. capabilities() lists the unconditional material capability;
    require_capability() checks additional operations, NOT remote ownership.

    from_saved() reconstructs BackendSpec from a local manifest. read() returns
    StateObservation: no output object or invented lineage/serial on failure.
    attach(manifest) validates protected evidence and saves only local metadata.
    reserve_new(owner_uuid) returns a durable CAS CreationReservation before init.
    apply(..., reservation=receipt, manifest_factory=fn) creates new remote state;
    fn(StateSummary) must return an exact validated DeploymentManifest. Existing
    deployments omit both arguments. Local first-creation orchestration remains
    the local deployer's responsibility; legacy local read needs no descriptor.

    MutationResult separates command success from recovery publication failure.
    Descriptors/claims are retained; never retry a failed/unknown apply blindly.
    Destroy uses a saved destroy plan and returns a tombstone only after verified
    same-backend empty managed state, not merely empty outputs. No backend/state
    object deletion, detach, migration, resource import or source checkout here.
    """
    def __init__(self, *, backend_spec, target_scope, deployment_name, local_store,
                 runner_factory, descriptor=None, coordinator=None, verify_scope=None,
                 verify_materials=None, mutation_adapter=None):
        self.backend_spec = backend_spec
        self.target_scope = target_scope
        self.deployment_name = deployment_name
        self.local_store = local_store
        self.runner_factory = runner_factory
        self.descriptor = descriptor
        self.identity = backend_spec.identity(target_scope, deployment_name)
        self.coordinator = coordinator
        self.verify_scope = verify_scope
        self.verify_materials = verify_materials
        self.mutation_adapter = mutation_adapter

    def capabilities(self):
        """Outputs need no source checkout or recovered SSH/desktop secrets."""
        return frozenset({"outputs"})

    def require_capability(self, operation):
        if operation == "outputs":
            return
        if operation not in {"apply", "destroy", "plan", "connect"} or not callable(self.verify_materials):
            raise CapabilityError("Operation requires independently verified recovery materials")
        try:
            # Trusted controller hook must verify pinned source/lockfile, input
            # recovery and operation-specific secrets; raise on missing/unknown.
            if self.verify_materials(self.descriptor, operation) is not None:
                raise CapabilityError("Verifier must return None only on verified success")
        except Exception:
            raise CapabilityError("Required source, inputs or secrets are not verified") from None

    def apply(self, *, acknowledge_mutation=False, reservation=None, manifest_factory=None):
        """Plan once/apply once; retain local recovery metadata on partial failure."""
        return self._mutate("apply", acknowledge_mutation=acknowledge_mutation,
                            reservation=reservation, manifest_factory=manifest_factory)

    def destroy(self, *, acknowledge_mutation=False):
        """Apply a saved destroy plan; never infer destruction from empty outputs."""
        return self._mutate("destroy", acknowledge_mutation=acknowledge_mutation)

    def _mutate(self, operation, *, acknowledge_mutation, reservation=None, manifest_factory=None):
        result = None
        try:
            if acknowledge_mutation is not True:
                raise CapabilityError("Mutation requires explicit acknowledgement")
            if self.descriptor is not None and self.descriptor.identity != self.identity:
                raise IdentityMismatch("Descriptor differs from selected backend")
            self.require_capability(operation)
            remote = self.backend_spec.backend != "local"
            if remote and not callable(self.mutation_adapter):
                raise CapabilityError("Remote mutation runner adapter is not integrated")
            if reservation is not None:
                if (not remote or self.descriptor is not None or not isinstance(reservation, CreationReservation)
                        or not callable(manifest_factory)):
                    raise CapabilityError("Creation requires its reservation and a recovery manifest factory")
                snapshot = reservation.snapshot
                if self._creation_snapshot(reservation.claim) != snapshot:
                    raise IdentityMismatch("Creation reservation changed")
            else:
                snapshot = self._snapshot(self.descriptor) if remote else None
            with self._runner() as runner:
                self._check_runner(runner)
                current = (self._creation_snapshot(reservation.claim) if reservation else
                           self._snapshot(self.descriptor) if remote else None)
                if remote and current != snapshot:
                    raise IdentityMismatch("Remote evidence changed before initialization")
                runner.init()
                before = None
                if reservation is not None:
                    # Only this just-initialized context, with protected absence
                    # checked under its lock immediately before init, may capture
                    # an empty initialization object. Never reacquire after this.
                    initialized = self._creation_snapshot(reservation.claim, allow_initialized_empty=True)
                    if replace(initialized, state_generation=None, summary=None,
                               _content_digest=None, _runner_digest=None, _creation_state=None) != snapshot:
                        raise IdentityMismatch("Creation ownership changed during initialization")
                    snapshot = initialized
                    if snapshot.summary is not None:
                        snapshot.verify_state(runner.pull_state())
                        before = snapshot.summary
                if reservation is None:
                    raw_before = runner.pull_state()
                    before = StateSummary.from_state(raw_before)
                    self._verify_summary(self.descriptor, before)
                    if remote:
                        snapshot.verify_state(raw_before)
                current = (self._creation_snapshot(reservation.claim,
                               expected_state=snapshot._creation_state) if reservation else
                           self._snapshot(self.descriptor) if remote else None)
                if remote and current != snapshot:
                    raise IdentityMismatch("Remote evidence changed before planning")
                plan = runner.plan(destroy=operation == "destroy")
                self._check_runner(runner)
                if before is not None:
                    raw_planned = runner.pull_state()
                    before.verify(StateSummary.from_state(raw_planned))
                    if remote:
                        snapshot.verify_state(raw_planned)
                succeeded = True
                try:
                    if remote:
                        guard = RemoteMutationGuard(self, runner, plan, snapshot, operation, reservation)
                        self.mutation_adapter(runner, plan, guard=guard, operation=operation)
                        if not guard.consumed:
                            raise CapabilityError("Runner adapter did not consume its mutation guard")
                    else:
                        runner.apply(plan, acknowledge_mutation=True)
                except Exception:
                    succeeded = False
                if remote and not guard.authorized:
                    raise CapabilityError("Remote adapter failed to validate its guard; descriptor retained")
                result = self._record_outcome(runner, succeeded, snapshot=snapshot,
                                            reservation=reservation, manifest_factory=manifest_factory,
                                            operation=operation)
            return result
        except Exception:
            if result is not None:
                # Context exit can report retained Terraform recovery state.
                # Command success survives, but no cleanup authority survives.
                return replace(result, recovery_needed=True, tombstone=None,
                    observation=StateObservation(StateStatus.UNKNOWN, canonical(self.identity)))
            raise DeploymentStateError("Mutation preflight failed; operation refused") from None

    def _record_outcome(self, runner, succeeded, *, snapshot=None, reservation=None, manifest_factory=None,
                        operation="apply"):
        """Infrastructure status and metadata publication status stay separate."""
        observation = StateObservation(StateStatus.UNKNOWN, canonical(self.identity))
        recovery_needed = not succeeded
        tombstone = None
        try:
            self._check_runner(runner)
            raw = runner.pull_state()
            summary = StateSummary.from_state(raw)
            if snapshot is not None:
                state_binding = self._verify_post_remote(raw, snapshot, reservation)
            old = self.descriptor
            if old is None:
                updated = manifest_factory(summary)
                if not isinstance(updated, DeploymentManifest) or updated.identity != self.identity:
                    raise IdentityMismatch("Recovery factory returned a different identity")
                self._verify_summary(updated, summary)
            else:
                data = old.to_dict()
                if summary.lineage != data["state"]["lineage"] or summary.serial < data["state"]["serial"]:
                    raise IdentityMismatch("Post-operation state binding changed")
                data["state"] = summary.to_dict()
                updated = DeploymentManifest.from_dict(data)
            observation = StateObservation(StateStatus.POPULATED if summary.addresses else StateStatus.REACHABLE_EMPTY,
                                           canonical(self.identity), summary, DeploymentOutputs.from_state(raw["outputs"]))
            if operation == "destroy":
                status = StateStatus.DESTROYED if succeeded and not summary.addresses else StateStatus.PARTIALLY_DESTROYED
                observation = StateObservation(status, canonical(self.identity), summary, observation.outputs)
                recovery_needed = recovery_needed or status != StateStatus.DESTROYED
            self.local_store.save(updated, expected_digest=digest(old.to_dict()) if old else None)
            self.descriptor = updated
            if snapshot is not None and succeeded:
                if reservation is not None:
                    published = self.coordinator.complete_creation(reservation.claim, updated)
                else:
                    published = self.coordinator.publish_manifest(updated,
                        expected_generation=snapshot.manifest_generation)
                recovery_needed = recovery_needed or published.recovery_needed
                if not published.recovery_needed:
                    # Publication is not atomic with state. Bind its final read
                    # to the exact object verified before saving any metadata.
                    final = self._snapshot(updated)
                    final.verify_state(raw)
                    if (final.scope != snapshot.scope
                            or (final.state_generation, final._content_digest) != state_binding
                            or (reservation is None and
                                (final.claim_generation, final.claim_digest) !=
                                (snapshot.claim_generation, snapshot.claim_digest))):
                        raise IdentityMismatch("Protected evidence changed during publication")
            if operation == "destroy" and succeeded and not summary.addresses and not recovery_needed:
                tombstone = DestroyTombstone(canonical(self.identity), summary.lineage, summary.serial)
        except Exception as error:
            recovery_needed = True
            if observation.summary is None:
                observation = StateObservation(self._error_status(error), canonical(self.identity))
        if recovery_needed and observation.status == StateStatus.DESTROYED:
            observation = StateObservation(StateStatus.UNKNOWN, canonical(self.identity))
            tombstone = None
        return MutationResult("succeeded" if succeeded else "failed", observation,
                              self.descriptor, recovery_needed, tombstone)

    def _verify_post_remote(self, raw, snapshot, reservation):
        if self._scope() != snapshot.scope:
            raise IdentityMismatch("Authenticated scope changed during operation")
        if reservation is not None:
            claim = self.coordinator.assert_claim(reservation.claim)
        else:
            claim = self.coordinator.require_attachable()
        stored_claim = self.coordinator.store.read("claim")
        if (stored_claim is None or stored_claim.generation != snapshot.claim_generation
                or digest(claim) != snapshot.claim_digest or strict_json(stored_claim.data) != claim):
            raise IdentityMismatch("Protected ownership changed during operation")
        stored = self.coordinator.store.read("state")
        if stored is None:
            raise IdentityMismatch("Authoritative state is unavailable after mutation")
        authoritative = strict_json(stored.data)
        StateSummary.from_state(raw).verify(StateSummary.from_state(authoritative))
        if _state_digest(raw) != _state_digest(authoritative):
            raise IdentityMismatch("Post-operation state content differs")
        return stored.generation, hashlib.sha256(stored.data).digest()

    def _scope(self):
        if self.coordinator is None or not callable(self.verify_scope):
            raise CapabilityError("Remote access requires protected objects and independent scope verification")
        if self.coordinator.identity != self.identity:
            raise IdentityMismatch("Protected store differs from selected backend")
        result = self.verify_scope(deepcopy(self.identity))
        if not isinstance(result, VerifiedScope) or result.identity != canonical(self.identity) or not result.principal:
            raise IdentityMismatch("Authenticated scope does not match selected backend")
        return result

    def _snapshot(self, descriptor):
        scope = self._scope()
        if not isinstance(descriptor, DeploymentManifest) or descriptor.identity != self.identity:
            raise IdentityMismatch("Exact recovery descriptor required")
        active = self.coordinator.require_attachable()
        store = self.coordinator.store
        claim = store.read("claim")
        remote = store.read("manifest")
        state = store.read("state")
        if claim is None or remote is None or state is None:
            raise IdentityMismatch("Authoritative attachment evidence is missing")
        if strict_json(claim.data) != active:
            raise IdentityMismatch("Ownership changed while checking attachment")
        protected = DeploymentManifest.from_json(remote.data)
        if protected != descriptor:
            raise IdentityMismatch("Protected recovery descriptor differs; reconcile explicitly")
        raw = strict_json(state.data)
        summary = StateSummary.from_state(raw)
        self._verify_summary(descriptor, summary)
        if active["lineage"] != summary.lineage:
            raise IdentityMismatch("Ownership claim lineage mismatch")
        return RemoteSnapshot(scope, claim.generation, digest(active), state.generation,
                              summary, remote.generation, hashlib.sha256(state.data).digest(), _state_digest(raw))

    def _creation_snapshot(self, claim, *, expected_state=None, allow_initialized_empty=False):
        scope = self._scope()
        pending = self.coordinator.assert_claim(claim)
        observed = self.coordinator.verify_creation_state(claim, expected_state=expected_state,
            allow_initialized_empty=allow_initialized_empty)
        if self.coordinator.store.read("manifest") is not None:
            raise IdentityMismatch("Reserved destination became occupied; reconcile ownership")
        if observed is None:
            return RemoteSnapshot(scope, claim.generation, digest(pending), None, None, None)
        # Retain the original coordinator receipt, never a refreshed baseline.
        receipt = expected_state if expected_state is not None else observed
        stored = self.coordinator.store.read("state")
        if (stored is None or stored.generation != receipt.generation
                or hashlib.sha256(stored.data).digest() != receipt._content_digest):
            raise IdentityMismatch("Creation state changed while capturing content")
        return RemoteSnapshot(scope, claim.generation, digest(pending), receipt.generation,
            receipt.summary, None, receipt._content_digest, _state_digest(strict_json(stored.data)), receipt)

    def reserve_new(self, owner_id):
        """Durable protected create-if-absent claim; never initializes Terraform.

        Failure/interruptions leave any successful pending reservation in place.
        No automatic timeout, deletion or takeover of another creator's claim.
        """
        try:
            if self.backend_spec.backend == "local" or self.descriptor is not None:
                raise CapabilityError("Reservation requires a new remote deployment")
            self._scope()
            claim = self.coordinator.claim_new(owner_id)
            return CreationReservation(claim, self._creation_snapshot(claim))
        except Exception:
            raise DeploymentStateError("Destination reservation refused; reconcile protected ownership") from None

    @staticmethod
    def _verify_summary(descriptor, summary):
        binding = descriptor.to_dict()["state"]
        StateSummary(binding["lineage"], binding["serial"], tuple(binding["addresses"])).verify(summary)

    def attach(self, descriptor):
        """Verify supplied + protected metadata, then save ONLY a local receipt.

        No import/apply/plan, repository checkout, remote write or raw state
        persistence. Fresh isolated init uses controller-approved sources only.
        Missing source/secret recovery never prevents output-only attachment.
        """
        try:
            before = self._snapshot(descriptor)
            with self._runner() as runner:
                self._check_runner(runner)
                if self._snapshot(descriptor) != before:
                    raise IdentityMismatch("Attachment evidence changed before initialization")
                runner.init()
                before.verify_state(runner.pull_state())
                if self._snapshot(descriptor) != before:
                    raise IdentityMismatch("Attachment evidence changed during initialization")
                self.local_store.save(descriptor)
                self.descriptor = descriptor
            return descriptor
        except Exception:
            raise DeploymentStateError("Attachment refused; evidence unavailable or inconsistent") from None

    @classmethod
    def from_saved(cls, deployment_name, *, local_store, runner_factory, **kwargs):
        descriptor = local_store.load(deployment_name)
        data = descriptor.to_dict()
        return cls(backend_spec=BackendSpec.from_dict(data["backend_config"], cloud=data["identity"]["cloud"]),
                   target_scope=data["identity"]["target_scope"], deployment_name=deployment_name,
                   local_store=local_store, runner_factory=runner_factory, descriptor=descriptor, **kwargs)

    def _runner(self):
        return self.runner_factory(backend_spec=self.backend_spec, target_scope=self.target_scope,
                                   deployment_name=self.deployment_name)

    def read(self):
        try:
            if self.backend_spec.backend != "local" and self.descriptor is None:
                self._scope()
                objects = [self.coordinator.store.read(kind) for kind in ("relocation", "state", "manifest", "claim")]
                status = StateStatus.ATTACHMENT_REQUIRED if any(obj is not None for obj in objects) else StateStatus.CONFIGURED_NOT_CREATED
                return StateObservation(status, canonical(self.identity))
            before = self._snapshot(self.descriptor) if self.backend_spec.backend != "local" else None
            with self._runner() as runner:
                self._check_runner(runner)
                if before is not None and self._snapshot(self.descriptor) != before:
                    raise IdentityMismatch("Remote evidence changed before initialization")
                runner.init()
                state = runner.pull_state()
                summary = StateSummary.from_state(state)
                if before is not None:
                    before.verify_state(state)
                if self.descriptor is not None:
                    if self.descriptor.identity != self.identity:
                        raise IdentityMismatch("Descriptor identity mismatch")
                    self._verify_summary(self.descriptor, summary)
                entries = runner.output()
                if DeploymentOutputs(entries) != DeploymentOutputs.from_state(state["outputs"]):
                    raise IdentityMismatch("Outputs changed relative to the observed state snapshot")
                if before is not None and self._snapshot(self.descriptor) != before:
                    raise IdentityMismatch("Remote state changed during read")
                return StateObservation(StateStatus.POPULATED if summary.addresses else StateStatus.REACHABLE_EMPTY,
                                        canonical(self.identity), summary, DeploymentOutputs(entries))
        except Exception as error:
            return StateObservation(self._error_status(error), canonical(self.identity))

    def _check_runner(self, runner):
        if runner.backend_identity != canonical(self.identity):
            raise IdentityMismatch("Runner backend differs from selected identity")

    @staticmethod
    def _error_status(error):
        if isinstance(error, ObjectAccessDenied):
            return StateStatus.PERMISSION_DENIED
        if isinstance(error, TerraformLockError):
            return StateStatus.LOCKED
        if isinstance(error, (IdentityMismatch, ObjectConflict)):
            return StateStatus.IDENTITY_MISMATCH
        if isinstance(error, (OSError, ObjectStoreError, TerraformRunnerError)):
            return StateStatus.UNREACHABLE
        return StateStatus.UNKNOWN
