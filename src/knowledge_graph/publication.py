"""Immutable, atomically published local graph generations (no pickle)."""
import hashlib
import json
import os
import re
import fcntl
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

ARTIFACTS = frozenset({"dataset.trig", "manifest.json", "entities.json", "claims.json", "coverage.json", "projection.json"})
MAX_ARTIFACT = 32 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(value).hexdigest()


@contextmanager
def _cache(cache, create=False):
    """Walk directory descriptors without following even ancestor symlinks."""
    parts = Path(os.path.abspath(cache)).parts
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("cache must be owner-only")
        yield fd
    finally:
        os.close(fd)


def _read(fd, name, limit=MAX_ARTIFACT):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("unsafe or oversized artifact")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("oversized artifact")
        return data


def _write(fd, name, data):
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    with os.fdopen(handle, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _generation(fd, generation):
    if not re.fullmatch(r"[0-9a-f]{64}", generation):
        raise ValueError("invalid generation pointer")
    directory = os.open(generation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        integrity = _read(directory, "integrity.json", 8192)
        if _digest(integrity) != generation:
            raise ValueError("invalid generation manifest")
        hashes = json.loads(integrity)
        if not isinstance(hashes, dict) or not hashes or not set(hashes) <= ARTIFACTS:
            raise ValueError("invalid artifact names")
        artifacts = {}
        for name, expected in hashes.items():
            data = _read(directory, name)
            if _digest(data) != expected:
                raise ValueError("artifact integrity mismatch")
            artifacts[name] = data.decode("utf-8")
        return artifacts
    finally:
        os.close(directory)


def publish(cache, artifacts):
    """Publish complete text artifacts, serialized across competing writers."""
    if not isinstance(artifacts, dict) or not artifacts or not set(artifacts) <= ARTIFACTS:
        raise ValueError("invalid artifact names")
    if any(not isinstance(value, str) or len(value.encode()) > MAX_ARTIFACT
           for value in artifacts.values()):
        raise ValueError("invalid or oversized artifact")
    hashes = {name: _digest(value.encode("utf-8")) for name, value in artifacts.items()}
    integrity = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    generation = _digest(integrity)
    with _cache(cache, create=True) as fd:
        lock = os.open("writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=fd)
        try:
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe writer lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            stage = ".build-" + uuid.uuid4().hex
            os.mkdir(stage, mode=0o700, dir_fd=fd)
            stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            written = []
            renamed = False
            try:
                for name, value in artifacts.items():
                    _write(stage_fd, name, value.encode("utf-8"))
                    written.append(name)
                _write(stage_fd, "integrity.json", integrity)
                written.append("integrity.json")
                os.fsync(stage_fd)
                try:
                    existing = _generation(fd, generation)
                except FileNotFoundError:
                    os.rename(stage, generation, src_dir_fd=fd, dst_dir_fd=fd)
                    renamed = True
                else:
                    if existing != artifacts:
                        raise ValueError("existing generation differs")
                pointer = ".current-" + uuid.uuid4().hex
                _write(fd, pointer, (generation + "\n").encode("ascii"))
                os.replace(pointer, "current", src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                if not renamed:
                    for name in written:
                        os.unlink(name, dir_fd=stage_fd)
                os.close(stage_fd)
                if not renamed:
                    os.rmdir(stage, dir_fd=fd)
        finally:
            os.close(lock)
    return generation


def load(cache):
    """Load one pinned generation and reject corrupted evidence."""
    with _cache(cache) as fd:
        generation = _read(fd, "current", 65).decode("ascii").strip()
        return generation, _generation(fd, generation)
