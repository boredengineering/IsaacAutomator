"""Explicit action-target metadata bridge, never installer ownership evidence.

Preload before, invoke ONLY AFTER normal preview_sandbox.confine_readonly.
Landlock does not restrict stat metadata or O_PATH traversal. This module uses
that documented limitation for explicit planned names, NOT new directory read
grants. No content, directory listing, configuration, Git or process inspection.
The pure planner never imports/calls this opt-in bridge.
"""
import ctypes
import errno
import importlib.util
import os
from pathlib import Path
import stat
import sys
import time

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('target_plan_evidence', Path(__file__).with_name('plan_evidence.py'))
assert _spec and _spec.loader
_evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_evidence)
_libc = ctypes.CDLL(None, use_errno=True)  # Load before confinement; no target I/O.


def _mount_id(fd):
    """Linux x86_64 statx on a pinned descriptor, no pathname or /proc read.

    Normal sandbox admits statx(332), but NOT openat2(437). The stable Linux
    statx ABI is 256 bytes, with stx_mask at 0 and stx_mnt_id at offset 144.
    Mount ID (unlike st_dev) detects same-device bind mounts. Fail closed on
    older kernels/filesystems without STATX_MNT_ID. AT_NO_AUTOMOUNT avoids
    requesting automount traversal; AT_EMPTY_PATH addresses this fd alone.
    """
    data = (ctypes.c_ubyte * 256)()
    if _libc.syscall(332, fd, b'', 0x1000 | 0x800, 0x1000, ctypes.byref(data)) != 0:
        raise OSError(ctypes.get_errno(), 'target mount metadata unavailable')
    if not ctypes.c_uint32.from_buffer(data, 0).value & 0x1000:
        raise OSError(errno.ENOTSUP, 'target mount metadata unavailable')
    return ctypes.c_uint64.from_buffer(data, 144).value


def _check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('target observation deadline exhausted')


def _observe(target, deadline):
    _check_deadline(deadline)
    fd = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = target[1:].split('/')
        info = os.fstat(fd)
        mount_id = _mount_id(fd)
        for index, part in enumerate(parts):
            _check_deadline(deadline)
            try:
                child = os.open(part, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            except FileNotFoundError:
                return {'state': 'missing', 'managed': False}
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if (_mount_id(fd) != mount_id
                    or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
                    or (index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode))):
                return {'state': 'unsupported', 'managed': False, 'conflict': True}
        return {'state': 'directory' if stat.S_ISDIR(info.st_mode) else 'file',
                'identity': [info.st_dev, info.st_ino],
                'mode': stat.S_IMODE(info.st_mode), 'managed': False}
    finally:
        os.close(fd)


class ObservationError(ValueError):
    """Malformed or oversized explicit request; no target has been inspected."""


def _targets(action_plan, target_home, max_targets):
    try:
        if (type(max_targets) is not int or not 1 <= max_targets <= _evidence.MAX_TARGETS
                or type(action_plan) is not dict
                or type(action_plan.get('kind')) is not str
                or action_plan.get('kind') != 'installer-action-plan'
                or type(action_plan.get('version')) is not int or action_plan['version'] != 1
                or type(action_plan.get('target_home')) is not str
                or type(target_home) is not str or action_plan['target_home'] != target_home
                or type(action_plan.get('actions')) is not list or len(action_plan['actions']) > 512):
            raise ObservationError('invalid target observation request')
        _evidence.validate_evidence({target_home: {}})
        targets = {}
        for action in action_plan['actions']:
            if (type(action) is not dict or type(action.get('target')) is not str
                    or not 0 < len(action['target']) <= _evidence.MAX_PATH_BYTES
                    or type(action.get('status', 'unknown')) is not str):
                raise ObservationError('invalid target observation request')
            target = action['target']
            if target.startswith('/'):
                _evidence.validate_evidence({target: {}})
                if action.get('status') != 'excluded':
                    targets[target] = {}
            if len(targets) > max_targets:
                raise ObservationError('invalid target observation request')
        return _evidence.validate_evidence(targets)
    except _evidence.EvidenceError:
        raise ObservationError('invalid target observation request') from None


def collect_evidence(action_plan, *, target_home, max_targets=128):
    """Return validate_evidence-compatible metadata, never apply permission.

    Call only in the already-confined, unprivileged, single-threaded reader.
    Normal source-profile file grants are sufficient: do NOT grant target/home
    directory reads. target_home must exactly match the explicit plan anchor;
    it is validated as data, not independently inspected. Absolute normalized
    non-excluded action targets alone are selected; logical labels stay unknown
    in the planner. Up to 512 actions, 128 unique targets and schema path bounds
    are accepted, with request validation completed before any target opens.

    Safe existing names return file/directory, identity=[device,inode], mode,
    managed=False. Missing ancestors imply missing only after safe descriptor
    traversal of every existing prefix. Symlink/hardlink/special-file/mount
    boundaries return unsupported+conflict; unavailable/DAC/deadline errors
    return unknown+conflict, without path-bearing OS messages. The strict
    evidence schema has no reason or ownership-unknown field: these fixed state
    categories and managed=False are intentional, not an ownership assertion.
    Ancestor metadata is not exported. No cleanliness/content claims are made.

    The one-second cooperative deadline bounds traversal between syscalls; the
    normal sandbox's existing eight-second alarm is the hard wall-time backstop
    for a stalled filesystem syscall. No alarm, limits or grants are widened.
    Descriptor pinning prevents link traversal, NOT concurrent pathname changes:
    this is a point-in-time conflict preview; apply must revalidate independently.
    Mount boundaries are conservatively refused even along the home prefix.
    """
    deadline = time.monotonic() + 1.0
    targets = _targets(action_plan, target_home, max_targets)
    result = {}
    for target in targets:
        try:
            record = _observe(target, deadline)
            _check_deadline(deadline)
            result[target] = record
        except OSError:
            # Never echo errno paths/details (which could reveal other names).
            result[target] = {'state': 'unknown', 'managed': False, 'conflict': True}
    return _evidence.validate_evidence(result)
