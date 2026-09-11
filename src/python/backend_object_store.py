"""Conditional recovery object I/O, never Terraform state writes.

Concrete CLI adapters require authorized ambient credentials; constructors are
pure. Cloud commands execute ONLY on read/write. CLI feature support and IAM
must be accepted separately per provider. No login, IAM changes or retries of
uncertain writes. Callers authorize these operations and provision separately
protected manifest/claim/relocation ACLs outside workload ownership.
"""
from dataclasses import dataclass, field
import hashlib
import os
import re
from pathlib import Path
import subprocess
import tempfile
from src.python.deployment_manifest import (ManifestError, strict_json, _require, _match,
                                            _fields, canonical, digest, StateSummary, DeploymentManifest,
                                            RelocationRecord)


class ObjectStoreError(RuntimeError):
    """Sanitized failure; unknown state must never be interpreted as absent."""


class ObjectAccessDenied(ObjectStoreError):
    """Authentication/authorization failed; never an empty deployment."""


class ObjectConflict(ObjectStoreError):
    """A create or compare-and-swap precondition failed; never retry blindly."""


@dataclass(frozen=True)
class StoredObject:
    data: bytes = field(repr=False)
    generation: str


class CLIObjectStore:
    """Pinned exact BackendSpec identity, bounded private CLI transport.

    read(kind) -> StoredObject or None ONLY on explicit object-not-found.
    write(kind, bytes, expected_generation=None) -> generation. None means
    create-if-absent, never unconditional overwrite. Only metadata is writable.
    run is an optional subprocess.run-compatible test transport.
    """
    def __init__(self, backend_spec, target_scope, deployment_name, *, run=None, environment=None,
                 timeout=60):
        _require(backend_spec.backend in ("s3", "gcs", "azurerm"), "Remote object backend required")
        self._identity = backend_spec.identity(target_scope, deployment_name)
        self._backend = backend_spec.backend
        self._destination = dict(self._identity["destination"])
        self._run = run or subprocess.run
        self._environment = dict(os.environ if environment is None else environment)
        self._environment.update(AWS_PAGER="", CLOUDSDK_CORE_DISABLE_PROMPTS="1")
        self._timeout = timeout

    @property
    def identity(self):
        from copy import deepcopy
        return deepcopy(self._identity)

    def key(self, kind):
        suffix = {"state": "", "manifest": ".isaac-manifest-v1.json",
                  "claim": ".isaac-claim-v1.json", "relocation": ".isaac-relocation-v1.json"}
        _require(kind in suffix, "Unknown protected object kind")
        return self._identity["object_key"] + suffix[kind]

    def _execute(self, argv, *, missing_ok=False):
        try:
            result = self._run(argv, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=self._timeout, env=self._environment)
        except (OSError, subprocess.SubprocessError):
            raise ObjectStoreError("Cloud object operation unavailable; outcome may be unknown") from None
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else result.stderr
            if re.search(r"\b(AccessDenied|ExpiredToken|InvalidAccessKeyId|AuthorizationPermissionMismatch|AuthenticationFailed|AuthorizationFailure)\b|HTTPError 40[13]", error):
                raise ObjectAccessDenied("Cloud object authentication/authorization denied")
            if re.search(r"\b(PreconditionFailed|ConditionalRequestConflict|ConditionNotMet|BlobAlreadyExists)\b|HTTPError 412", error):
                raise ObjectConflict("Protected object changed or destination occupied")
            absent = {"s3": r"\bNoSuchKey\b", "azurerm": r"\bBlobNotFound\b"}
            if missing_ok:
                if self._backend == "gcs":
                    # gcloud 581 GcsNotFoundError identifies the exact object.
                    # Generic HTTP 404 (even with an accessible bucket) is unknown.
                    prefix = ["gcloud", "storage", "objects", "describe"]
                    if (argv[:4] == prefix and len(argv) > 4 and error.strip() ==
                            "ERROR: (gcloud.storage.objects.describe) " + argv[4] + " not found: 404."):
                        return None
                elif re.search(absent[self._backend], error):
                    return None
            raise ObjectStoreError("Cloud object operation failed; diagnostics withheld")
        return result.stdout

    def _s3(self, operation, kind):
        d = self._destination
        return ["aws", "s3api", operation, "--bucket", d["bucket"], "--key", self.key(kind),
                "--region", d["region"], "--expected-bucket-owner", d["owner_account_id"], "--output", "json"]

    def _gcs_url(self, kind):
        return "gs://" + self._destination["bucket"] + "/" + self.key(kind)

    def _azure(self, operation, kind):
        d = self._destination
        return ["az", "storage", "blob", operation, "--account-name", d["storage_account_name"],
                "--container-name", d["container_name"], "--name", self.key(kind), "--auth-mode", "login",
                "--subscription", d["subscription_id"], "--only-show-errors", "--output", "json"]

    def _token(self, value):
        pattern = r"[1-9][0-9]{0,30}" if self._backend == "gcs" else r'"[A-Za-z0-9][A-Za-z0-9_-]{0,255}"|[A-Za-z0-9][A-Za-z0-9_-]{0,255}'
        _match(value, pattern)
        return value

    def read(self, kind):
        self.key(kind)
        try:
            return self._read(kind)
        except (OSError, ManifestError, KeyError, TypeError):
            raise ObjectStoreError("Cloud object read/receipt invalid; diagnostics withheld") from None

    def _read(self, kind):
        self.key(kind)
        with tempfile.TemporaryDirectory(prefix="isaac-object-") as temporary:
            path = Path(temporary) / "object"
            path.touch(mode=0o600)
            if self._backend == "azurerm":
                raw = self._execute(self._azure("show", kind), missing_ok=True)
                if raw is None:
                    return None
                metadata = strict_json(raw)
                generation = self._token(metadata["properties"]["etag"])
                self._execute([*self._azure("download", kind), "--file", str(path),
                               "--overwrite", "true", "--if-match", generation])
                return StoredObject(path.read_bytes(), generation)
            if self._backend == "gcs":
                url = self._gcs_url(kind)
                raw = self._execute(["gcloud", "storage", "objects", "describe", url,
                    "--project", self._destination["project"], "--format=json", "--quiet"], missing_ok=True)
                if raw is None:
                    # Exact object-not-found evidence is necessary, but also
                    # require a reachable, correctly identified bucket.
                    bucket = strict_json(self._execute(["gcloud", "storage", "buckets", "describe",
                        "gs://" + self._destination["bucket"], "--project", self._destination["project"],
                        "--format=json", "--quiet"]))
                    _require(bucket.get("name") == self._destination["bucket"], "Backend bucket identity unknown")
                    return None
                metadata = strict_json(raw)
                generation = self._token(str(metadata["generation"]))
                self._execute(["gcloud", "storage", "cp", "--quiet", url + "#" + generation, str(path)])
                return StoredObject(path.read_bytes(), generation)
            raw = self._execute([*self._s3("get-object", kind), str(path)], missing_ok=True)
            if raw is None:
                return None
            metadata = strict_json(raw)
            return StoredObject(path.read_bytes(), self._token(metadata["ETag"]))

    def write(self, kind, data, *, expected_generation=None):
        _require(kind in ("manifest", "claim", "relocation"), "State writes are forbidden")
        _require(type(data) is bytes and len(data) <= 1024 * 1024, "Bounded metadata bytes required")
        if expected_generation is not None:
            self._token(expected_generation)
        try:
            return self._write(kind, data, expected_generation)
        except (OSError, ManifestError, KeyError, TypeError):
            raise ObjectStoreError("Cloud publication receipt invalid; outcome may be unknown") from None

    def _write(self, kind, data, expected_generation):
        with tempfile.TemporaryDirectory(prefix="isaac-object-") as temporary:
            path = Path(temporary) / "object"
            path.touch(mode=0o600)
            path.write_bytes(data)
            if self._backend == "azurerm":
                condition = (["--if-none-match", "*"] if expected_generation is None
                             else ["--if-match", expected_generation])
                metadata = strict_json(self._execute([*self._azure("upload", kind), "--file", str(path),
                    "--type", "block", "--overwrite", "true", "--content-type", "application/json", *condition]))
                return self._token(metadata["etag"])
            if self._backend == "gcs":
                generation = "0" if expected_generation is None else expected_generation
                self._execute(["gcloud", "storage", "cp", "--quiet", "--if-generation-match=" + generation,
                               str(path), self._gcs_url(kind)])
                # gcloud cp does not return a structured generation receipt.
                # Re-read pinned bytes; a competing different writer is an error,
                # never return a token authorizing overwrite of unrelated data.
                observed = self.read(kind)
                if observed is None or observed.data != data:
                    raise ObjectStoreError("Publication raced; re-read protected metadata before retrying")
                return observed.generation
            args = [*self._s3("put-object", kind), "--body", str(path), "--content-type", "application/json"]
            args += ["--if-none-match", "*"] if expected_generation is None else ["--if-match", expected_generation]
            metadata = strict_json(self._execute(args))
            return self._token(metadata["ETag"])


@dataclass(frozen=True)
class CreationClaim:
    """CAS receipt, NOT a signature or proof outside its protected object store."""
    identity_digest: str
    owner_id: str
    generation: str


@dataclass(frozen=True)
class CreationStateObservation:
    """In-process exact empty-state receipt; never export its private digest.

    Not authentication evidence or a state backup. Keep the entire receipt with
    the saved plan until the immediate pre-apply check; summary alone is unsafe.
    """
    _identity_json: str = field(repr=False)
    claim: CreationClaim
    generation: str
    summary: StateSummary
    _content_digest: bytes = field(repr=False)

    @property
    def identity(self):
        return strict_json(self._identity_json)


@dataclass(frozen=True)
class PublicationResult:
    """Metadata outcome only; NEVER changes the caller's infrastructure outcome."""
    status: str
    generation: str | None = None

    @property
    def recovery_needed(self):
        return self.status == "recovery_needed"


class ProtectedObjectCoordinator:
    """Ownership protocol for cooperating controllers, preceding Terraform init.

    authorize(identity, operation) is a REQUIRED trusted controller policy hook:
    it must verify separately administered object IAM/protection/owner and
    authorization, returning None on success and raising on denied/unknown
    checks. Boolean/dict "trusted" receipts are refused. It is never loaded from
    manifests. The concrete transport authenticates bytes; storage admin owns
    ACLs and granting this capability. No local JSON flag or self-signature is
    an alternative trust anchor. This protocol does not fence raw Terraform.

    Pending/unknown claims are deliberately durable after interruption. There
    is no timeout takeover/delete API: explicit state reconciliation is required.
    Hold the runner lock and revalidate immediately before plan/apply; Terraform
    still owns state locking and saved-plan lineage/serial checks.
    """
    def __init__(self, store, *, authorize):
        _require(callable(authorize), "A trusted protected-object authorization hook is required")
        self.store = store
        self._identity_json = canonical(store.identity)
        self._authorize = authorize

    @property
    def identity(self):
        return strict_json(self._identity_json)

    def _gate(self, operation):
        if canonical(self.store.identity) != self._identity_json:
            raise ObjectConflict("Pinned object identity changed")
        self._authorized(operation)
        if self.store.read("relocation") is not None:
            raise ObjectConflict("Source is retired or fenced; explicit migration reconciliation required")

    def _authorized(self, operation):
        if self._authorize(self.identity, operation) is not None:
            raise ObjectAccessDenied("Protected-object policy did not explicitly complete verification")

    def _claim(self):
        stored = self.store.read("claim")
        if stored is None:
            raise ObjectConflict("Ownership claim missing; explicit adoption required")
        data = strict_json(stored.data)
        _fields(data, {"schema_version", "identity", "owner_id", "status", "lineage"})
        _require(type(data["schema_version"]) is int and data["schema_version"] == 1)
        _match(data["owner_id"], r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
        if data["identity"] != self.identity or data["status"] not in ("pending", "active", "unknown"):
            raise ObjectConflict("Ownership claim identity/status is invalid")
        return stored, data

    def claim_new(self, owner_id):
        """CAS exclusive reservation BEFORE any Terraform init/plan. No takeover."""
        _match(owner_id, r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
        self._gate("claim_new")
        if self.store.read("state") is not None or self.store.read("manifest") is not None:
            raise ObjectConflict("Destination occupied; verified attachment required")
        data = {"schema_version": 1, "identity": self.identity, "owner_id": owner_id,
                "status": "pending", "lineage": None}
        generation = self.store.write("claim", canonical(data).encode(), expected_generation=None)
        # A noncooperating writer may race preflight; retain the pending fence.
        if self.store.read("state") is not None:
            raise ObjectConflict("State appeared during reservation; claim retained for reconciliation")
        return CreationClaim(digest(self.identity), owner_id, generation)

    def assert_claim(self, claim):
        self._gate("assert_claim")
        stored, data = self._claim()
        if (not isinstance(claim, CreationClaim) or claim.identity_digest != digest(self.identity)
                or stored.generation != claim.generation or data["owner_id"] != claim.owner_id
                or data["status"] != "pending"):
            raise ObjectConflict("Creation ownership changed; refuse operation")
        return data

    def require_attachable(self):
        self._gate("attach")
        _, data = self._claim()
        if data["status"] != "active":
            raise ObjectConflict("Pending/unknown creation claim; reconcile before attachment")
        _match(data["lineage"], r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
        return data

    def verify_creation_state(self, claim, *, expected_state=None, allow_initialized_empty=False):
        """Recheck before init/plan/apply; bind the returned receipt to the plan.

        Default requires absence. Only the controller that just initialized its
        reserved identity may opt into an empty init-created state. Once that
        CreationStateObservation is captured, pass it as expected_state on
        every subsequent check (including immediately before applying);
        never reacquire a newer empty baseline to hide a competing writer.
        Terraform locking and saved-plan state checks remain mandatory.
        """
        self.assert_claim(claim)
        if expected_state is not None:
            _require(isinstance(expected_state, CreationStateObservation),
                     "Exact creation observation required; summary alone is insufficient")
        stored = self.store.read("state")
        if stored is None:
            if expected_state is not None:
                raise ObjectConflict("Previously observed creation state disappeared")
            return None
        raw = strict_json(stored.data)
        summary = StateSummary.from_state(raw)
        if expected_state is not None:
            expected_state.summary.verify(summary)
        if ((expected_state is None and allow_initialized_empty is not True)
                or raw["resources"] != [] or raw.get("outputs", {}) != {}):
            raise ObjectConflict("Creation destination is occupied; refuse automatic adoption")
        _require(type(stored.data) is bytes and type(stored.generation) is str and bool(stored.generation),
                 "Exact state bytes and generation required")
        observation = CreationStateObservation(self._identity_json, claim, stored.generation, summary,
                                               hashlib.sha256(stored.data).digest())
        if expected_state is not None and observation != expected_state:
            raise ObjectConflict("Creation state observation changed; refuse stale saved plan")
        return observation

    def _verify_manifest_state(self, manifest):
        _require(isinstance(manifest, DeploymentManifest) and manifest.identity == self.identity,
                 "Manifest/backend identity mismatch")
        observed = self.store.read("state")
        if observed is None:
            raise ObjectConflict("Authoritative state is missing; cannot publish/attach")
        summary = StateSummary.from_state(strict_json(observed.data))
        expected = manifest.to_dict()["state"]
        StateSummary(expected["lineage"], expected["serial"], tuple(expected["addresses"])).verify(summary)
        return summary

    def read_relocation(self):
        """Read/validate a protected marker for display, NEVER follow its target."""
        self._authorized("read_relocation")
        stored = self.store.read("relocation")
        if stored is None:
            return None
        record = RelocationRecord.from_json(stored.data)
        _require(record.to_dict()["source_identity"] == self.identity, "Relocation source mismatch")
        return record

    def publish_relocation(self, record, *, verify_destination):
        """Create a protected retirement marker; does NOT claim IAM fencing.

        verify_destination(record_dict) is a trusted authenticated read callback
        returning {identity,state} for the verified destination. It MUST perform
        the independent destination check, never echo the input. Terraform
        migration, state backup, exclusive maintenance and provider write-fence
        acceptance remain caller-owned, separately approved operations.
        """
        _require(isinstance(record, RelocationRecord) and callable(verify_destination))
        active = self.require_attachable()
        self._authorized("publish_relocation")
        data = record.to_dict()
        _require(data["source_identity"] == self.identity and data["source_state"]["lineage"] == active["lineage"],
                 "Relocation source/claim mismatch")
        verified = verify_destination(data)
        _require(verified == {"identity": data["destination_identity"], "state": data["destination_state"]},
                 "Relocation destination has not been independently verified")
        return self.store.write("relocation", record.canonical_json().encode(), expected_generation=None)

    def _publish_manifest(self, manifest, expected_generation):
        self._gate("publish_manifest")
        self._verify_manifest_state(manifest)
        current = self.store.read("manifest")
        _require((current is None and expected_generation is None) or
                 (current is not None and expected_generation is not None and
                  current.generation == expected_generation),
                 "Manifest generation conflict; re-read before publishing")
        if current is not None:
            old = DeploymentManifest.from_json(current.data).to_dict()
            new = manifest.to_dict()
            _require(old["identity"] == new["identity"] and
                     old["state"]["lineage"] == new["state"]["lineage"] and
                     old["state"]["serial"] <= new["state"]["serial"],
                     "Manifest baseline changed; explicit reconciliation required")
        generation = self.store.write("manifest", manifest.canonical_json().encode(),
                                      expected_generation=expected_generation)
        # State/metadata are not atomic. Detect change while publishing, retain
        # recovery_needed and never turn a successful apply into failed infra.
        self._verify_manifest_state(manifest)
        return generation

    def publish_manifest(self, manifest, *, expected_generation=None):
        """Refresh an ACTIVE deployment's manifest after a verified operation.

        Returns recovery_needed on mismatched/denied/unknown publication. The
        caller must retain local recovery metadata and original apply status.
        """
        try:
            active = self.require_attachable()
            _require(manifest.to_dict()["state"]["lineage"] == active["lineage"], "Claim lineage mismatch")
            generation = self._publish_manifest(manifest, expected_generation)
            return PublicationResult("published", generation)
        except (ObjectStoreError, ManifestError):
            return PublicationResult("recovery_needed")

    def complete_creation(self, claim, manifest, *, expected_manifest_generation=None):
        """After successful apply/state verification: manifest first, ACTIVE last.

        Any failure leaves a pending/unknown claim and recovery_needed. Caller
        must NOT announce a complete recovery path or retry apply automatically.
        """
        try:
            data = self.assert_claim(claim)
            generation = self._publish_manifest(manifest, expected_manifest_generation)
            self.assert_claim(claim)
            data.update(status="active", lineage=manifest.to_dict()["state"]["lineage"])
            self.store.write("claim", canonical(data).encode(), expected_generation=claim.generation)
            return PublicationResult("published", generation)
        except (ObjectStoreError, ManifestError):
            return PublicationResult("recovery_needed")
