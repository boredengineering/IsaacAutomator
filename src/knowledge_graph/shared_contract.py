"""Portable shared identity, independent of existing checkout-local snapshots.

First review gate only. Callers must independently obtain the issuer/repository
binding and capture authorized checkout fingerprints; strings supplied by an
untrusted checkout are not identity discovery or authorization.
"""
import hashlib
import json
import re
import base64
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass

IDENTITY_FIELDS = frozenset({"schema", "issuer", "organization", "repository_id",
                            "repository_name", "revision", "source_manifest", "policy_digest",
                            "extractor_digest", "dependencies_digest", "dirty"})
MAX_SOURCES = 2048
MAX_ENVELOPE = 1024 * 1024
MAX_ARTIFACT = 16 * 1024 * 1024
MAX_TOTAL = 17 * 1024 * 1024
# First gate deliberately rejects derived sidecars. They require a separately
# reviewed confined RDF/JSON parity bridge, not hash-only "validation".
ARTIFACTS = frozenset({"dataset.trig", "manifest.json"})
PAYLOAD_FIELDS = frozenset({"schema", "identity", "artifact_schema", "artifacts", "generation",
                            "key_id", "catalog_sequence", "revocation_epoch", "issued_at",
                            "expires_at", "revoked_generations", "revoked_keys"})


class VerificationError(ValueError):
    """Fail-closed, non-source-bearing shared verification error."""


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def portable_identity(**fields):
    """Validate/detach supplied portable fingerprints; does not discover Git."""
    result = {"schema": "ia-shared-identity/v1", **fields}
    validate_identity(result)
    return json.loads(canonical_json(result))


def _match(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _sha(value):
    return _match(value, r"[0-9a-f]{64}")


def validate_identity(identity):
    if (type(identity) is not dict or set(identity) != IDENTITY_FIELDS
            or identity["schema"] != "ia-shared-identity/v1" or identity["dirty"] is not False):
        raise VerificationError("identity_schema_or_dirty")
    for name in ("issuer", "organization", "repository_id"):
        if not _match(identity[name], r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}"):
            raise VerificationError("invalid_identity_selector")
    if (not _match(identity["repository_name"], r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}")
            or not _match(identity["revision"], r"(?:[0-9a-f]{40}|[0-9a-f]{64})")):
        raise VerificationError("invalid_repository_or_revision")
    for name in ("policy_digest", "extractor_digest", "dependencies_digest"):
        if not _sha(identity[name]):
            raise VerificationError("invalid_fingerprint")
    manifest = identity["source_manifest"]
    if type(manifest) is not dict or not 1 <= len(manifest) <= MAX_SOURCES:
        raise VerificationError("source_manifest_limit")
    for path, digest in manifest.items():
        if (not _match(path, r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
                or len(path) > 240 or any(p in {".", ".."} for p in path.split("/"))
                or not _sha(digest)):
            raise VerificationError("invalid_source_manifest")


def identity_digest(identity):
    validate_identity(identity)
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def require_checkout(approved, checkout):
    """Pure exact-match primitive over independently captured trusted inputs.

    No filesystem is read: callers must not confuse comparison of self-reported
    dictionaries with independently verified actual-checkout freshness.
    """
    validate_identity(approved)
    validate_identity(checkout)
    if approved != checkout:
        raise VerificationError("checkout_mismatch")
    return "current_checkout"


@dataclass(frozen=True)
class TrustPolicy:
    """Explicit out-of-band pins, never populated from a bundle."""
    issuer: str
    organization: str
    repository_id: str
    repository_name: str
    key_id: str
    public_key: bytes
    openssl: str = "/usr/bin/openssl"
    max_lease_seconds: int = 3600
    minimum_sequence: int = 1
    minimum_revocation_epoch: int = 1
    revoked_generations: frozenset = frozenset()
    revoked_keys: frozenset = frozenset()


def _scope(identity):
    # Single catalog stream per pinned repository; revisions never reset replay
    # floors. Future channel/policy catalogs need a new reviewed protocol version.
    return hashlib.sha256(canonical_json({k: identity[k] for k in
        ("issuer", "organization", "repository_id", "repository_name")})).hexdigest()


@dataclass(frozen=True)
class Checkpoint:
    """Owner-protected anti-replay state, not a remotely supplied trust root."""
    scope: str
    catalog_digest: str
    sequence: int
    epoch: int
    issued_at: int
    observed_at: int
    revoked_generations: tuple = ()
    revoked_keys: tuple = ()

    @classmethod
    def from_verified(cls, payload, *, now, previous=None):
        """Call only after verify_envelope; preserve cumulative revocations."""
        generations = set(payload["revoked_generations"])
        keys = set(payload["revoked_keys"])
        if previous is not None:
            generations.update(previous.revoked_generations)
            keys.update(previous.revoked_keys)
        if len(generations) > 4096 or len(keys) > 4096:
            raise VerificationError("revocation_history_limit")
        return cls(_scope(payload["identity"]), hashlib.sha256(canonical_json(payload)).hexdigest(),
                   payload["catalog_sequence"], payload["revocation_epoch"], payload["issued_at"],
                   now, tuple(sorted(generations)), tuple(sorted(keys)))


def _verify_signature(message, signature, trust):
    # RFC 8410 Ed25519 SubjectPublicKeyInfo. Never accept an algorithm supplied
    # by the sender. Only public key material is written by production code.
    if type(trust.public_key) is not bytes or len(trust.public_key) != 32 or len(signature) != 64:
        raise VerificationError("invalid_signature_or_key")
    try:
        with tempfile.TemporaryDirectory(prefix="ia-shared-verify-") as directory:
            root = Path(directory)
            for name, data in (("key.der", bytes.fromhex("302a300506032b6570032100") + trust.public_key),
                               ("message", message), ("signature", signature)):
                path = root / name
                path.touch(mode=0o600)
                path.write_bytes(data)
            result = subprocess.run([trust.openssl, "pkeyutl", "-verify", "-rawin", "-pubin",
                                     "-keyform", "DER", "-inkey", str(root / "key.der"),
                                     "-in", str(root / "message"), "-sigfile", str(root / "signature")],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=5, check=False)
            if result.returncode != 0:
                raise VerificationError("signature_verification_failed")
    except (OSError, subprocess.TimeoutExpired):
        # Include temporary-file creation, writes and cleanup in the boundary.
        raise VerificationError("signature_capability_unavailable") from None


def strict_json(raw, limit=MAX_ENVELOPE):
    """Byte/depth-bounded protocol JSON; duplicate keys/floats are forbidden."""
    if type(raw) is not bytes or len(raw) > limit:
        raise VerificationError("json_size_or_type")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise VerificationError("duplicate_json_key")
            result[key] = value
        return result
    def invalid_constant(_):
        raise VerificationError("invalid_json_number")
    try:
        # Scan structure before parsing; quotes/escapes cannot spoof nesting.
        depth, quoted, escaped = 0, False, False
        for char in raw:
            if quoted:
                if escaped:
                    escaped = False
                elif char == 92:
                    escaped = True
                elif char == 34:
                    quoted = False
            elif char == 34:
                quoted = True
            elif char in (91, 123):
                depth += 1
                if depth > 16:
                    raise VerificationError("json_depth_limit")
            elif char in (93, 125):
                depth -= 1
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=invalid_constant, parse_float=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise VerificationError("invalid_json") from None


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2 ** 53 - 1


def verify_envelope(envelope, trust, expected_identity, *, now, checkpoint=None, allow_revoked=False):
    """Authenticate catalog/lease. Never validates RDF or grants graph use.

    allow_revoked is ONLY for recording authenticated withdrawal messages; the
    caller must not serve their artifacts. No historical anti-replay bypass.
    """
    document = strict_json(envelope)
    if type(document) is not dict or set(document) != {"payload", "signature"}:
        raise VerificationError("envelope_schema")
    payload = document["payload"]
    if type(payload) is not dict or set(payload) != PAYLOAD_FIELDS:
        raise VerificationError("catalog_schema")
    if (payload["schema"] != "ia-shared-catalog/v1"
            or payload["artifact_schema"] != "ia-shared-opaque-canonical/v1"):
        raise VerificationError("unsupported_schema")
    validate_identity(expected_identity)
    require_checkout(payload["identity"], expected_identity)
    for name in ("issuer", "organization", "repository_id", "repository_name"):
        if payload["identity"][name] != getattr(trust, name):
            raise VerificationError("publisher_scope_mismatch")
    if payload["key_id"] != trust.key_id or not _match(trust.key_id, r"[A-Za-z0-9_-]{1,128}"):
        raise VerificationError("publisher_key_mismatch")
    for name in ("catalog_sequence", "revocation_epoch", "issued_at", "expires_at"):
        if not _integer(payload[name], 1):
            raise VerificationError("invalid_catalog_counter")
    if (not _integer(now) or not _integer(trust.max_lease_seconds, 1)
            or trust.max_lease_seconds > 86400
            or not payload["issued_at"] <= now < payload["expires_at"]
            or payload["expires_at"] - payload["issued_at"] > trust.max_lease_seconds):
        raise VerificationError("lease_expired_or_invalid")
    for name in ("revoked_generations", "revoked_keys"):
        items = payload[name]
        if (type(items) is not list or len(items) > 2048
                or any(not (_sha(item) if name == "revoked_generations"
                            else _match(item, r"[A-Za-z0-9_-]{1,128}")) for item in items)
                or len(set(items)) != len(items)):
            raise VerificationError("invalid_revocations")
    descriptors = payload["artifacts"]
    if type(descriptors) is not dict or set(descriptors) != ARTIFACTS:
        raise VerificationError("artifact_allowlist")
    for name, item in descriptors.items():
        if (type(item) is not dict or set(item) != {"sha256", "size"}
                or not _sha(item["sha256"]) or not _integer(item["size"], 1)
                or item["size"] > (MAX_ENVELOPE if name == "manifest.json" else MAX_ARTIFACT)):
            raise VerificationError("artifact_descriptor_or_limit")
    if sum(item["size"] for item in descriptors.values()) > MAX_TOTAL:
        raise VerificationError("artifact_total_limit")
    if payload["generation"] != hashlib.sha256(canonical_json(descriptors)).hexdigest():
        raise VerificationError("generation_digest_mismatch")
    if not isinstance(document["signature"], str) or len(document["signature"]) != 88:
        raise VerificationError("invalid_signature")
    try:
        signature = base64.b64decode(document["signature"], validate=True)
    except ValueError:
        raise VerificationError("invalid_signature") from None
    _verify_signature(canonical_json(payload), signature, trust)
    for floor in (trust.minimum_sequence, trust.minimum_revocation_epoch):
        if not _integer(floor, 1):
            raise VerificationError("invalid_trust_floor")
    if (payload["catalog_sequence"] < trust.minimum_sequence
            or payload["revocation_epoch"] < trust.minimum_revocation_epoch):
        raise VerificationError("catalog_replay")
    if checkpoint is not None:
        if checkpoint.scope != _scope(payload["identity"]):
            raise VerificationError("checkpoint_scope_mismatch")
        if now < checkpoint.observed_at:
            raise VerificationError("clock_rollback")
        if (payload["catalog_sequence"] < checkpoint.sequence
                or payload["revocation_epoch"] < checkpoint.epoch
                or payload["issued_at"] < checkpoint.issued_at
                or (payload["catalog_sequence"] == checkpoint.sequence and
                    hashlib.sha256(canonical_json(payload)).hexdigest() != checkpoint.catalog_digest)):
            raise VerificationError("catalog_replay_or_equivocation")
    if (trust.key_id in trust.revoked_keys
            or checkpoint is not None and trust.key_id in checkpoint.revoked_keys):
        raise VerificationError("publisher_key_revoked")
    revoked_generations = set(trust.revoked_generations) | set(payload["revoked_generations"])
    revoked_keys = set(trust.revoked_keys) | set(payload["revoked_keys"])
    if checkpoint is not None:
        revoked_generations.update(checkpoint.revoked_generations)
        revoked_keys.update(checkpoint.revoked_keys)
    if not allow_revoked and (payload["generation"] in revoked_generations or trust.key_id in revoked_keys):
        raise VerificationError("generation_or_key_revoked")
    return payload
