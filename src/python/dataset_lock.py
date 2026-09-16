"""Cooperative local directory-inode exclusion; no files are created in datasets.

EX selected roots + SH ancestors exclude identical/nested selections while
allowing siblings, regardless of caller control directory. A single sorted,
deduplicated identity set prevents self-conflicts for overlapping selections.
This is advisory POSIX flock, not a distributed/crash-surviving lease or a
filesystem race sandbox. Unrelated mount aliases and hostile writers are not
confined. Call check() at use boundaries; descriptors pin observed identities,
not the names a native engine will subsequently resolve.
"""
import fcntl
import os
from pathlib import PurePosixPath


class DatasetLockError(ValueError):
    pass


class DatasetLock:
    def __init__(self, roots):
        self.roots = tuple(sorted(set(str(p) for p in roots)))
        if not self.roots or any(not p.startswith('/') or str(PurePosixPath(p)) != p or
                                 '..' in PurePosixPath(p).parts for p in self.roots):
            raise DatasetLockError('Select normalized absolute dataset directories')
        self._fds = {}
        self._chains = None

    @staticmethod
    def _walk(path):
        opened = []
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            opened.append(fd)
            for part in PurePosixPath(path).parts[1:]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=fd)
                opened.append(fd)
            # Directory opening and enumeration must both be permitted.
            with os.scandir(fd) as entries:
                next(entries, None)
            return opened
        except BaseException:
            for fd in opened:
                os.close(fd)
            raise

    @staticmethod
    def _identity(fd):
        info = os.fstat(fd)
        return info.st_dev, info.st_ino

    @property
    def evidence(self):
        if self._chains is None:
            return []
        return [dict(path=p, device=chain[-1][0], inode=chain[-1][1])
                for p, chain in self._chains.items()]

    def acquire(self):
        if self._chains is not None:
            raise DatasetLockError('Dataset lock already acquired')
        chains, modes = {}, {}
        try:
            for path in self.roots:
                opened = self._walk(path)
                chains[path] = tuple(self._identity(fd) for fd in opened)
                for index, fd in enumerate(opened):
                    identity = chains[path][index]
                    mode = fcntl.LOCK_EX if index == len(opened) - 1 else fcntl.LOCK_SH
                    if identity in self._fds:
                        os.close(fd)
                    else:
                        self._fds[identity] = fd
                    if mode == fcntl.LOCK_EX or identity not in modes:
                        modes[identity] = mode
            for identity in sorted(self._fds):
                fcntl.flock(self._fds[identity], modes[identity] | fcntl.LOCK_NB)
            self._chains = chains
            self.check()
            return self
        except BaseException as exc:
            self.close()
            if isinstance(exc, OSError):
                raise DatasetLockError('Dataset unavailable, symlink, or another writer owns overlapping roots') from None
            raise

    def pin(self, roots):
        """Pin descendants covered by an already-held EX selected-root lock.

        Used by disposable seed writers whose fixture-root lock also covers
        not-yet-created destinations. Never adopts a changed existing pin.
        """
        self.check()
        assert self._chains is not None
        additions = {}
        for path in map(str, roots):
            if not path.startswith('/') or str(PurePosixPath(path)) != path or '..' in PurePosixPath(path).parts:
                raise DatasetLockError('Select normalized absolute dataset directories')
            if path in self._chains:
                continue
            if not any(path.startswith(root.rstrip('/') + '/') for root in self.roots):
                raise DatasetLockError('Cannot pin a path outside held dataset ownership')
            opened = []
            try:
                opened = self._walk(path)
                additions[path] = tuple(self._identity(fd) for fd in opened)
                # Retain directory descriptors as inode pins; the ancestor EX
                # lock already excludes cooperating descendant writers.
                for fd, identity in zip(opened, additions[path]):
                    if identity in self._fds:
                        os.close(fd)
                    else:
                        self._fds[identity] = fd
                opened = []
            except OSError:
                raise DatasetLockError('Dataset source missing, symlink, or unreadable') from None
            finally:
                for fd in opened:
                    os.close(fd)
        self._chains.update(additions)
        return self.check()

    def check(self):
        if self._chains is None:
            raise DatasetLockError('Dataset ownership not acquired')
        for path, expected in self._chains.items():
            opened = []
            try:
                opened = self._walk(path)
                if tuple(self._identity(fd) for fd in opened) != expected:
                    raise DatasetLockError('Dataset root or ancestor identity changed; new path review required')
            except OSError:
                raise DatasetLockError('Dataset root missing, symlink, or unreadable; new path review required') from None
            finally:
                for fd in opened:
                    os.close(fd)
        return self.evidence

    def close(self):
        for fd in self._fds.values():
            os.close(fd)
        self._fds = {}
        self._chains = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.close()
