"""Explicit offline shared-bundle quarantine, NOT graph admission or transport.

This gate accepts only a caller-selected local directory and out-of-band trust
pins. It never discovers Git identity, accesses the existing graph cache, parses
RDF, serves claims, publishes, hosts, or makes network requests. The independent
cache contains opaque authenticated bytes; query_ready is always False until a
separately reviewed confined canonical/derived-view validation bridge exists.

Replay protection assumes this owner-only cache and a trustworthy UTC clock are
not rolled back/deleted by its owner. A cold cache needs operator-provided trust
floors. Disconnected readers cannot discover new revocations; the signed lease
bounds that unavoidable stale-access window. Status always re-verifies bytes.
"""
import os
import hashlib
import stat
import re
import uuid
import fcntl
import time
from contextlib import contextmanager
from dataclasses import asdict, fields, replace
from pathlib import Path

from . import shared_contract as contract


@contextmanager
def _filesystem_errors():
    """Sanitize OS failures only after normal cache cleanup has unwound."""
    try:
        yield
    except OSError:
        raise contract.VerificationError("shared_filesystem_unavailable") from None


@contextmanager
def _directory(path, *, create=False):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise contract.VerificationError("absolute_safe_path_required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            if create and index == len(path.parts) - 2:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        _owner_directory(fd)
        yield fd
    finally:
        os.close(fd)


def _owner_directory(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
        raise contract.VerificationError("owner_only_directory_required")


def _file_info(info, limit):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
            or info.st_uid != os.geteuid() or info.st_mode & 0o7177):
        raise contract.VerificationError("unsafe_or_oversized_file")
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _read(fd, name, limit):
    before = _file_info(os.stat(name, dir_fd=fd, follow_symlinks=False), limit)
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, "rb") as stream:
        if _file_info(os.fstat(stream.fileno()), limit) != before:
            raise contract.VerificationError("file_changed")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise contract.VerificationError("file_size_limit")
        if (_file_info(os.fstat(stream.fileno()), limit) != before
                or _file_info(os.stat(name, dir_fd=fd, follow_symlinks=False), limit) != before):
            raise contract.VerificationError("file_changed")
        return data


def _write(fd, name, data):
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        os.unlink(name, dir_fd=fd)
        raise


def _names(fd, limit=32):
    names = set()
    with os.scandir(fd) as entries:
        for entry in entries:
            names.add(entry.name)
            if len(names) > limit:
                raise contract.VerificationError("directory_entry_limit")
    return names


def _state(fd):
    try:
        state = contract.strict_json(_read(fd, "shared-state.json", contract.MAX_ENVELOPE))
    except FileNotFoundError:
        if any(name.startswith("bundle-") for name in _names(fd)):
            raise contract.VerificationError("checkpoint_missing") from None
        return None, None
    if (type(state) is not dict or set(state) != {"schema", "checkpoint", "active"}
            or state["schema"] != "ia-shared-cache/v1"
            or (state["active"] is not None and not contract._match(state["active"], r"bundle-[0-9a-f]{32}"))):
        raise contract.VerificationError("invalid_cache_state")
    value = state["checkpoint"]
    if (type(value) is not dict or set(value) != {f.name for f in fields(contract.Checkpoint)}
            or not all(contract._sha(value[key]) for key in ("scope", "catalog_digest"))
            or not all(contract._integer(value[key], 1) for key in
                       ("sequence", "epoch", "issued_at", "observed_at"))):
        raise contract.VerificationError("invalid_cache_state")
    for key in ("revoked_generations", "revoked_keys"):
        items = value[key]
        if (type(items) is not list or len(items) > 4096
                or any(not (contract._sha(item) if key == "revoked_generations"
                            else contract._match(item, r"[A-Za-z0-9_-]{1,128}")) for item in items)):
            raise contract.VerificationError("invalid_cache_state")
    return contract.Checkpoint(**state["checkpoint"]), state["active"]


def _dedicated(fd):
    for name in _names(fd):
        if (name not in {"shared-state.json", "shared.lock"}
                and not re.fullmatch(r"(?:bundle-|\.stage-|\.state-)[0-9a-f]{32}", name)):
            raise contract.VerificationError("dedicated_cache_required")


@contextmanager
def _cache(path, *, create=False):
    with _directory(path, create=create) as fd:
        _dedicated(fd)
        try:
            lock = os.open("shared.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                           0o600, dir_fd=fd)
        except FileExistsError:
            before = _file_info(os.stat("shared.lock", dir_fd=fd, follow_symlinks=False), 0)
            lock = os.open("shared.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                if _file_info(os.fstat(lock), 0) != before:
                    raise contract.VerificationError("lock_changed")
            except BaseException:
                os.close(lock)
                raise
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise contract.VerificationError("cache_busy") from None
                    time.sleep(0.01)
            yield fd
        finally:
            os.close(lock)


def _save_state(fd, checkpoint, active):
    name = ".state-" + uuid.uuid4().hex
    try:
        _write(fd, name, contract.canonical_json({"schema": "ia-shared-cache/v1",
                                                "checkpoint": asdict(checkpoint), "active": active}))
        os.replace(name, "shared-state.json", src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass


def _clock(fd, checkpoint, active, now):
    if not contract._integer(now, 1):
        raise contract.VerificationError("invalid_clock")
    if checkpoint is not None:
        if now < checkpoint.observed_at:
            raise contract.VerificationError("clock_rollback")
        if now > checkpoint.observed_at:
            checkpoint = replace(checkpoint, observed_at=now)
            _save_state(fd, checkpoint, active)
    return checkpoint


def _bundle(fd, trust, expected_identity, now, checkpoint):
    _owner_directory(fd)
    if _names(fd, 3) != contract.ARTIFACTS | {"catalog.json"}:
        raise contract.VerificationError("bundle_file_allowlist")
    envelope = _read(fd, "catalog.json", contract.MAX_ENVELOPE)
    payload = contract.verify_envelope(envelope, trust, expected_identity, now=now, checkpoint=checkpoint)
    artifacts = {name: _read(fd, name, item["size"]) for name, item in payload["artifacts"].items()}
    for name, data in artifacts.items():
        item = payload["artifacts"][name]
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise contract.VerificationError("artifact_digest_or_size_mismatch")
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            raise contract.VerificationError("invalid_artifact_text") from None
        if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise contract.VerificationError("invalid_artifact_text")
    manifest = contract.strict_json(artifacts["manifest.json"])
    contract.validate_identity(manifest)
    if manifest != payload["identity"]:
        raise contract.VerificationError("artifact_identity_mismatch")
    return payload, {**artifacts, "catalog.json": envelope}


def _receipt(payload):
    return {"schema": "ia-shared-verification-receipt/v1", "generation": payload["generation"],
            "identity_digest": contract.identity_digest(payload["identity"]),
            "repository_id": payload["identity"]["repository_id"], "revision": payload["identity"]["revision"],
            "policy_digest": payload["identity"]["policy_digest"], "catalog_sequence": payload["catalog_sequence"],
            "revocation_epoch": payload["revocation_epoch"], "lease_expires_at": payload["expires_at"],
            "lease_status": "unexpired", "transport": "verified_cache", "backend": None,
            "checkout_binding": "matches_supplied_identity", "verification": "signature_and_bytes_only",
            "query_ready": False}


class SharedClient:
    def __init__(self, cache, trust, *, enabled=False):
        self.cache = Path(cache)
        self.trust = trust
        self.enabled = enabled

    def observe_catalog(self, envelope, expected_identity, *, now):
        """Record a separately supplied signed catalog, including revocations.

        Invalidates the active quarantine pointer, even when its generation did
        not change. Explicit import is required to select newly authorized bytes.
        """
        if self.enabled is not True:
            raise contract.VerificationError("shared_client_disabled")
        with _filesystem_errors(), _cache(self.cache, create=True) as fd:
            checkpoint, active = _state(fd)
            checkpoint = _clock(fd, checkpoint, active, now)
            payload = contract.verify_envelope(envelope, self.trust, expected_identity, now=now,
                                               checkpoint=checkpoint, allow_revoked=True)
            checkpoint = contract.Checkpoint.from_verified(payload, now=now, previous=checkpoint)
            _save_state(fd, checkpoint, None)
            return {"catalog_sequence": checkpoint.sequence, "revocation_epoch": checkpoint.epoch,
                    "query_ready": False, "status": "catalog_observed_reimport_required"}

    def import_local(self, bundle, expected_identity, *, now):
        """Stage an explicitly provided directory; no semantic graph admission."""
        if self.enabled is not True:
            raise contract.VerificationError("shared_client_disabled")
        with _filesystem_errors(), _cache(self.cache, create=True) as fd:
            checkpoint, active = _state(fd)
            checkpoint = _clock(fd, checkpoint, active, now)
            with _directory(bundle) as source:
                payload, artifacts = _bundle(source, self.trust, expected_identity, now, checkpoint)
            next_checkpoint = contract.Checkpoint.from_verified(payload, now=now, previous=checkpoint)
            if active and checkpoint is not None and checkpoint.catalog_digest == next_checkpoint.catalog_digest:
                existing_fd = os.open(active, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    _bundle(existing_fd, self.trust, expected_identity, now, checkpoint)
                finally:
                    os.close(existing_fd)
                return _receipt(payload)
            if sum(name.startswith(("bundle-", ".stage-")) for name in _names(fd)) >= 8:
                raise contract.VerificationError("cache_generation_limit")
            stage = ".stage-" + uuid.uuid4().hex
            active = "bundle-" + uuid.uuid4().hex
            os.mkdir(stage, mode=0o700, dir_fd=fd)
            stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            written = []
            renamed = False
            try:
                for name, data in artifacts.items():
                    _write(stage_fd, name, data)
                    written.append(name)
                _bundle(stage_fd, self.trust, expected_identity, now, checkpoint)
                os.fsync(stage_fd)
                os.rename(stage, active, src_dir_fd=fd, dst_dir_fd=fd)
                renamed = True
                os.fsync(fd)
                _save_state(fd, next_checkpoint, active)
            except BaseException:
                # A state replacement can commit despite a lost acknowledgement.
                # Retain complete renamed bytes for readback, never delete a
                # directory that a committed pointer could reference.
                if not renamed:
                    for name in written:
                        os.unlink(name, dir_fd=stage_fd)
                    os.rmdir(stage, dir_fd=fd)
                raise
            finally:
                os.close(stage_fd)
            return _receipt(payload)

    def status(self, expected_identity, *, now):
        """Re-verify the quarantined bytes; never returns graph claims."""
        if self.enabled is not True:
            raise contract.VerificationError("shared_client_disabled")
        with _filesystem_errors(), _cache(self.cache) as fd:
            checkpoint, active = _state(fd)
            checkpoint = _clock(fd, checkpoint, active, now)
            if not active:
                raise contract.VerificationError("no_verified_bundle")
            bundle_fd = os.open(active, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                payload, _ = _bundle(bundle_fd, self.trust, expected_identity, now, checkpoint)
            finally:
                os.close(bundle_fd)
            return _receipt(payload)
