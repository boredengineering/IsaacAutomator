"""Nonsecret recovery manifests. No Terraform execution or implicit cloud I/O.

These immutable values are metadata, NOT signatures or cloud ownership proof.
Protected cloud object ACLs plus independently authenticated scope verification
are the trust anchor for attachment; local exports require explicit review.
A manifest is not a state transaction, controller backup or mutation approval.
"""
from dataclasses import dataclass
import hashlib
import json
import re
import os
import stat
import fcntl
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit
from src.python.terraform_backend import BackendSpec

MAX_METADATA_BYTES = 1024 * 1024


class ManifestError(ValueError):
    """Invalid nonsecret metadata; input values never appear in diagnostics."""


class IdentityMismatch(ManifestError):
    """Authoritative identity or state binding differs; reconcile explicitly."""


def _require(condition, message="Invalid or unsupported recovery metadata"):
    if not condition:
        raise ManifestError(message)


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields))


def _match(value, pattern):
    _require(isinstance(value, str) and re.fullmatch(pattern, value) is not None)


def _path(value):
    _match(value, r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
    _require(len(value) <= 1024 and all(p not in (".", "..") for p in value.split("/")))


def _reference(value):
    _require(type(value) is dict)
    _fields(value, {"store", "key", "sha256"} if "sha256" in value else {"store", "key"})
    _require(value["store"] in ("protected-inputs", "secret-manager", "vault", "environment"))
    _path(value["key"])
    if "sha256" in value:
        _require(value["store"] == "protected-inputs")
        _match(value["sha256"], r"[0-9a-f]{64}")


def _timestamp(value):
    _match(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ManifestError("Invalid recovery timestamp") from None


def _state_binding(value):
    _fields(value, {"lineage", "serial", "addresses"})
    _match(value["lineage"], r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
    _require(type(value["serial"]) is int and value["serial"] >= 0)
    addresses = value["addresses"]
    _require(type(addresses) is list and all(isinstance(a, str) for a in addresses))
    _require(len(set(addresses)) == len(addresses))
    for address in addresses:
        # Conservative Terraform module/resource address grammar; no values.
        ident = r"[A-Za-z_][A-Za-z0-9_-]*"
        index = r'(?:\[(?:[0-9]+|"[A-Za-z0-9_.:/-]+")\])?'
        _match(address, rf"(?:module\.{ident}{index}\.)*(?:data\.)?{ident}\.{ident}{index}")


def _validate_manifest(data):
    _fields(data, {"schema_version", "identity", "backend_config", "state", "source", "lockfile",
                   "inputs", "input_reference", "secret_references", "baseline"})
    _require(type(data["schema_version"]) is int and data["schema_version"] == 1)
    identity = data["identity"]
    _require(type(identity) is dict)
    try:
        spec = BackendSpec.from_dict(data["backend_config"], cloud=identity.get("cloud"))
        expected = spec.identity(identity.get("target_scope"), identity.get("deployment_name"))
    except (ValueError, TypeError):
        raise ManifestError("Invalid backend identity/configuration") from None
    _require(identity == expected, "Exact backend identity does not match configuration")
    _state_binding(data["state"])
    source, lockfile = data["source"], data["lockfile"]
    if source is not None:
        _fields(source, {"repository", "revision", "root"})
        _match(source["repository"], r"https://[A-Za-z0-9.-]+/[A-Za-z0-9_./-]+")
        parsed = urlsplit(source["repository"])
        _require(parsed.hostname is not None and not parsed.username and not parsed.query and not parsed.fragment)
        _path(parsed.path.lstrip("/"))
        _match(source["revision"], r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
        _path(source["root"])
    if lockfile is not None:
        _fields(lockfile, {"path", "sha256"})
        _path(lockfile["path"])
        _require(lockfile["path"].split("/")[-1] == ".terraform.lock.hcl")
        _match(lockfile["sha256"], r"[0-9a-f]{64}")
    inputs = data["inputs"]
    _require(type(inputs) is dict and set(inputs) <= {
        "region", "zone", "instance_type", "machine_type", "resource_group_name",
        "image_id", "disk_size_gb", "os_login", "security_tier"})
    for key, value in inputs.items():
        if key == "disk_size_gb":
            _require(type(value) is int and 1 <= value <= 65536)
        elif key == "os_login":
            _require(type(value) is bool)
        elif key == "security_tier":
            _require(value in ("public", "team", "enterprise"))
        else:
            _match(value, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    if data["input_reference"] is not None:
        _reference(data["input_reference"])
        _require(data["input_reference"]["store"] == "protected-inputs")
    _require(type(data["secret_references"]) is dict and set(data["secret_references"]) <= {
        "ssh_private_key", "desktop_password", "sudo_password", "registry_credentials", "huggingface_token"})
    for reference in data["secret_references"].values():
        _reference(reference)
    baseline = data["baseline"]
    _fields(baseline, {"source_revision", "lockfile_sha256", "input_sha256", "applied_at"})
    _require(baseline["source_revision"] == (source["revision"] if source else None))
    _require(baseline["lockfile_sha256"] == (lockfile["sha256"] if lockfile else None))
    _require(baseline["input_sha256"] == digest(inputs))
    if baseline["applied_at"] is not None:
        _timestamp(baseline["applied_at"])


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate recovery metadata field")
            result[key] = value
        return result
    try:
        _require(isinstance(raw, (str, bytes)))
        _require(len(raw.encode("utf-8") if isinstance(raw, str) else raw) <= MAX_METADATA_BYTES)
        return json.loads(raw, object_pairs_hook=unique)
    except (TypeError, ValueError, UnicodeError):
        raise ManifestError("Invalid recovery JSON; diagnostics withheld") from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True, init=False)
class DeploymentManifest:
    _json: str

    def __init__(self, *args, **kwargs):
        raise TypeError("Use DeploymentManifest.create/from_dict/from_json")

    @classmethod
    def create(cls, *, backend_spec, target_scope, deployment_name, lineage, serial,
               addresses, source=None, lockfile=None, inputs=None, input_reference=None,
               secret_references=None, applied_at=None):
        inputs = {} if inputs is None else inputs
        return cls.from_dict({"schema_version": 1,
            "identity": backend_spec.identity(target_scope, deployment_name),
            "backend_config": backend_spec.to_dict(),
            "state": {"lineage": lineage, "serial": serial, "addresses": sorted(addresses)},
            "source": source, "lockfile": lockfile, "inputs": inputs,
            "input_reference": input_reference,
            "secret_references": {} if secret_references is None else secret_references,
            "baseline": {"source_revision": source["revision"] if source else None,
                         "lockfile_sha256": lockfile["sha256"] if lockfile else None,
                         "input_sha256": digest(inputs), "applied_at": applied_at}})

    @classmethod
    def from_dict(cls, data):
        _validate_manifest(data)
        encoded = canonical(data)
        _require(len(encoded.encode()) <= MAX_METADATA_BYTES, "Recovery metadata exceeds size limit")
        value = object.__new__(cls)
        object.__setattr__(value, "_json", encoded)
        return value

    @classmethod
    def from_json(cls, raw):
        return cls.from_dict(strict_json(raw))

    def canonical_json(self):
        return self._json

    def to_dict(self):
        return json.loads(self._json)

    @property
    def identity(self):
        return self.to_dict()["identity"]


@dataclass(frozen=True)
class StateSummary:
    """Allowlisted managed-resource identity, never state/output values."""
    lineage: str
    serial: int
    addresses: tuple

    def __post_init__(self):
        _require(type(self.addresses) is tuple)
        _state_binding(self.to_dict())

    def to_dict(self):
        return {"lineage": self.lineage, "serial": self.serial, "addresses": list(self.addresses)}

    @classmethod
    def from_state(cls, data):
        _require(type(data) is dict and type(data.get("version")) is int and data["version"] == 4)
        _require(type(data.get("resources")) is list)
        addresses = []
        for resource in data["resources"]:
            _require(type(resource) is dict and resource.get("mode") in ("managed", "data"))
            _require(type(resource.get("instances")) is list)
            if resource["mode"] == "data":
                continue
            for instance in resource["instances"]:
                _require(type(instance) is dict and "deposed" not in instance,
                         "Deposed/partial resource instances require reconciliation")
                _match(resource.get("type"), r"[A-Za-z_][A-Za-z0-9_-]*")
                _match(resource.get("name"), r"[A-Za-z_][A-Za-z0-9_-]*")
                module = resource.get("module", "")
                _require(isinstance(module, str))
                address = (module + "." if module else "") + resource["type"] + "." + resource["name"]
                if "index_key" in instance:
                    key = instance["index_key"]
                    _require(type(key) in (str, int))
                    address += "[" + canonical(key) + "]"
                addresses.append(address)
        return cls(data.get("lineage"), data.get("serial"), tuple(sorted(addresses)))

    def verify(self, observed, *, allow_serial_advance=False):
        serial_ok = observed.serial >= self.serial if allow_serial_advance else observed.serial == self.serial
        if self.lineage != observed.lineage or self.addresses != observed.addresses or not serial_ok:
            raise IdentityMismatch("State lineage/serial/resource identity mismatch; reconcile before continuing")


def object_location(identity):
    """Physical object locator, excluding config/context that cannot move data."""
    destination = identity["destination"]
    if identity["backend"] in ("s3", "gcs"):
        storage = (destination["bucket"],)
    elif identity["backend"] == "azurerm":
        storage = (destination["storage_account_name"], destination["container_name"])
    else:
        storage = ()
    return (identity["backend"], *storage, identity["object_key"])


@dataclass(frozen=True, init=False)
class RelocationRecord:
    """Protected retirement marker, NEVER a redirect or a provider IAM fence.

    Publication fences cooperating managed callers only. Retirement still
    requires separately approved provider write fencing/identity rotation and
    an old-controller write-denial test; metadata cannot prove those facts.
    """
    _json: str

    def __init__(self, *args, **kwargs):
        raise TypeError("Use RelocationRecord.create/from_json")

    @classmethod
    def create(cls, source, destination, *, relocated_at):
        a, b = source.to_dict(), destination.to_dict()
        return cls.from_json(canonical({"schema_version": 1, "source_identity": a["identity"],
            "destination_identity": b["identity"], "source_state": a["state"],
            "destination_state": b["state"], "relocated_at": relocated_at,
            "retirement": "supervised_retirement_required"}))

    @classmethod
    def from_json(cls, raw):
        data = strict_json(raw)
        _fields(data, {"schema_version", "source_identity", "destination_identity", "source_state",
                       "destination_state", "relocated_at", "retirement"})
        _require(type(data["schema_version"]) is int and data["schema_version"] == 1)
        _require(data["retirement"] == "supervised_retirement_required")
        for identity in (data["source_identity"], data["destination_identity"]):
            _require(type(identity) is dict)
            config = {"backend": identity.get("backend"), "namespace": identity.get("namespace")}
            if identity.get("backend") != "local":
                config["destination"] = identity.get("destination")
            try:
                spec = BackendSpec.from_dict(config, cloud=identity.get("cloud"))
                _require(spec.identity(identity.get("target_scope"), identity.get("deployment_name")) == identity)
            except (ValueError, TypeError):
                raise ManifestError("Invalid relocation backend identity") from None
        a, b = data["source_identity"], data["destination_identity"]
        _require(object_location(a) != object_location(b) and all(a[key] == b[key] for key in ("cloud", "target_scope", "deployment_name")),
                 "Relocation must preserve workload identity and change the backend location")
        for state in (data["source_state"], data["destination_state"]):
            _state_binding(state)
        a, b = data["source_state"], data["destination_state"]
        StateSummary(a["lineage"], a["serial"], tuple(a["addresses"])).verify(
            StateSummary(b["lineage"], b["serial"], tuple(b["addresses"])), allow_serial_advance=True)
        _timestamp(data["relocated_at"])
        value = object.__new__(cls)
        object.__setattr__(value, "_json", canonical(data))
        return value

    def canonical_json(self):
        return self._json

    def to_dict(self):
        return strict_json(self._json)


@dataclass(frozen=True)
class RecoveryCapabilities:
    """Informational prerequisites, never an authorization/mutation token."""
    state_inspection: bool = True
    vm_start_stop: bool = False
    repair_destroy: bool = False
    missing: tuple = ("verified_vm_identity", "approved_source", "protected_inputs", "secrets")


@dataclass(frozen=True)
class Attachment:
    manifest: DeploymentManifest
    state: StateSummary
    capabilities: RecoveryCapabilities
    trust: str = "local-receipt-not-cloud-identity"


def evaluate_capabilities(manifest, *, verified_vm_identity=False, source_revision=None,
                          lockfile_sha256=None, protected_inputs_sha256=None,
                          required_secrets=None, available_secrets=()):
    """Compare independently verified LOCAL availability to a recovered baseline.

    Evidence arguments are caller-owned verification results, not fields to
    deserialize from a manifest. This does not fetch/execute source or resolve
    secrets. Call ONLY after verified attachment. A digest of allowlisted public
    inputs is not the full protected input file checksum: both are distinct.
    required_secrets must come from the trusted stack's input contract (empty
    tuple is valid for no-key/OS Login), never from missing manifest entries.
    Full repair/destroy still requires operation-specific auth/plan approval.
    """
    _require(isinstance(manifest, DeploymentManifest))
    data = manifest.to_dict()
    missing = []
    if verified_vm_identity is not True:
        missing.append("verified_vm_identity")
    if not data["source"] or data["source"]["revision"] != source_revision:
        missing.append("approved_source")
    if not data["lockfile"] or data["lockfile"]["sha256"] != lockfile_sha256:
        missing.append("provider_lockfile")
    reference = data["input_reference"]
    if (not reference or not reference.get("sha256") or
            reference["sha256"] != protected_inputs_sha256):
        missing.append("protected_inputs")
    if data["baseline"]["applied_at"] is None:
        missing.append("applied_baseline")
    if (required_secrets is None or not set(required_secrets) <= set(data["secret_references"])
            or not set(required_secrets) <= set(available_secrets)):
        missing.append("secrets")
    return RecoveryCapabilities(True, verified_vm_identity is True, not missing, tuple(missing))


def attach_verified(manifest, *, backend_spec, target_scope, deployment_name, state_reader,
                    verify_cloud_scope, check_attachment, local_store):
    """Read authoritative state once, verify it, then save ONLY local metadata.

    All three callables are trusted controller dependencies, not manifest data:
      state_reader(exact_identity) -> private Terraform v4 dict (or raises).
      check_attachment(exact_identity) -> ACTIVE protected claim, or raises.
      verify_cloud_scope(exact_identity, private_state) -> {cloud,target_scope}
        independently verified through authenticated provider checks; never
        merely echo fields from state/manifest. Must raise if unverified.

    check_attachment should bind ProtectedObjectCoordinator.require_attachable
    to the exact identity (including relocation checks). Attachment does NOT
    execute referenced code, fetch inputs/secrets, apply, import or grant full
    lifecycle capability. Export/import is operator-reviewed metadata, not an
    unsigned assertion of cloud ownership. Callback errors propagate; trusted
    adapters must sanitize their errors and never log private state.
    """
    _require(isinstance(manifest, DeploymentManifest))
    identity = backend_spec.identity(target_scope, deployment_name)
    if identity != manifest.identity:
        raise IdentityMismatch("Explicit backend scope does not match manifest")
    _require(all(callable(f) for f in (state_reader, verify_cloud_scope, check_attachment)))
    claim = check_attachment(identity)
    if (not isinstance(claim, dict) or claim.get("status") != "active" or claim.get("identity") != identity
            or claim.get("lineage") != manifest.to_dict()["state"]["lineage"]):
        raise IdentityMismatch("Protected claim is missing, pending or mismatched; reconcile attachment")
    raw = state_reader(identity)
    summary = StateSummary.from_state(raw)
    expected = manifest.to_dict()["state"]
    StateSummary(expected["lineage"], expected["serial"], tuple(expected["addresses"])).verify(summary)
    scope = verify_cloud_scope(identity, raw)
    if scope != {"cloud": identity["cloud"], "target_scope": identity["target_scope"]}:
        raise IdentityMismatch("Authenticated workload cloud scope does not match manifest")
    local_store.save(manifest)
    return Attachment(manifest, summary, RecoveryCapabilities())


class LocalManifestStore:
    """Private backend.json descriptors under an explicit absolute state root.

    None expected_digest means create-only. Updates require the current SHA256
    of canonical metadata, preserve identity/lineage and never rewind serial.
    Linux dirfd + NOFOLLOW traversal, flock, fsync and atomic replace avoid
    partial writes and cooperating-controller races. All ancestors must be
    root/current-user owned and non-writable by others (sticky ancestors such
    as /tmp are permitted). Root and the current UID are trusted: hostile code
    running as either cannot be fenced by local file permissions. Canonical
    ancestry is rechecked under the lock and before/after publication; a rename
    race is an unknown outcome requiring reconciliation, never save success.
    This is a local receipt, not cloud evidence. Do not persist raw state here.
    """
    def __init__(self, root):
        self.root = Path(root)
        _require(self.root.is_absolute() and ".." not in self.root.parts)

    @contextmanager
    def _directory(self, name, create=False):
        _match(name, r"[a-z0-9][a-z0-9_-]{0,62}")
        fd = None
        lock = None
        try:
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            self._safe_directory(fd)
            parts = (*self.root.parts[1:], name)
            for index, part in enumerate(parts):
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)  # Persist the new child's directory entry.
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self._safe_directory(fd, private=index >= len(parts) - 2)
            lock = os.open(".manifest.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=fd)
            self._regular(lock)
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._canonical_directory(name, fd)
            yield fd
            self._canonical_directory(name, fd)
        except OSError:
            raise ManifestError("Cannot access private descriptor; diagnostics withheld") from None
        finally:
            if lock is not None:
                os.close(lock)
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _safe_directory(fd, *, private=False):
        info = os.fstat(fd)
        trusted_owner = info.st_uid == os.getuid() if private else info.st_uid in (0, os.getuid())
        # Root/current-user-owned sticky ancestors (e.g. /tmp) protect the
        # next owned path component against other users' rename/unlink.
        writable_ok = not info.st_mode & 0o022 or (not private and info.st_mode & stat.S_ISVTX)
        _require(trusted_owner and writable_ok,
                 "Descriptor ancestry must be trusted and protected from replacement")

    def _canonical_directory(self, name, directory):
        """Detect trusted-owner rename races; never report detached success."""
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            self._safe_directory(fd)
            parts = (*self.root.parts[1:], name)
            for index, part in enumerate(parts):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self._safe_directory(fd, private=index >= len(parts) - 2)
            a, b = os.fstat(fd), os.fstat(directory)
            _require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino),
                     "Canonical descriptor directory changed; reconcile before retrying")
        finally:
            os.close(fd)

    @staticmethod
    def _regular(fd):
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                 info.st_uid == os.getuid() and not info.st_mode & 0o077,
                 "Descriptor must be a private owned regular file")

    def _read(self, directory):
        try:
            fd = os.open("backend.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            self._regular(stream.fileno())
            return DeploymentManifest.from_json(stream.read(MAX_METADATA_BYTES + 1))

    def load(self, deployment_name):
        with self._directory(deployment_name) as directory:
            value = self._read(directory)
            _require(value is not None, "Descriptor not found")
            _require(value.identity["deployment_name"] == deployment_name, "Descriptor name mismatch")
            return value

    def save(self, manifest, *, expected_digest=None):
        _require(isinstance(manifest, DeploymentManifest))
        # Validate/bound before mkdir, lock creation or replacing any receipt.
        encoded = manifest.canonical_json().encode()
        DeploymentManifest.from_json(encoded)
        name = manifest.identity["deployment_name"]
        with self._directory(name, create=True) as directory:
            current = self._read(directory)
            _require((current is None and expected_digest is None) or
                     (current is not None and digest(current.to_dict()) == expected_digest),
                     "Descriptor conflict; re-read before updating")
            if current is not None:
                old, new = current.to_dict(), manifest.to_dict()
                _require(old["identity"] == new["identity"] and
                         old["state"]["lineage"] == new["state"]["lineage"] and
                         old["state"]["serial"] <= new["state"]["serial"],
                         "Descriptor identity changed; explicit reconciliation required")
            temporary = ".manifest-" + uuid.uuid4().hex
            try:
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._canonical_directory(name, directory)
                os.replace(temporary, "backend.json", src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
