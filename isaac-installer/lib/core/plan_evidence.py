"""Bounded caller-supplied evidence for pure plans; never authorization.

Only JSON-shaped builtins and the explicitly supported metadata fields survive.
No target is resolved, inspected, or opened. Accepted path and hash strings are
metadata supplied by the caller, not an assertion of truth or absence of secrets.
"""
import re
import unicodedata

MAX_TARGETS = 128
MAX_ANCESTORS = 128
MAX_PATH_BYTES = 4096
MAX_PATH_PARTS = 128
FIELDS = frozenset(('state', 'identity', 'uid', 'mode', 'managed', 'sha256',
                    'tree_sha256', 'desired_digest', 'ancestors',
                    'fixture_identity', 'conflict', 'operation'))
STATES = frozenset(('missing', 'file', 'directory', 'unsupported', 'unknown'))
OPERATIONS = frozenset(('mkdir', 'write_file', 'repository_checkout',
                        'environment_create', 'artifact_install', 'package_install',
                        'settings_change', 'service_setup', 'unsupported'))


class EvidenceError(ValueError):
    """Invalid supplied evidence; diagnostics never include its contents."""


def _integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise EvidenceError('invalid plan evidence')
    return value


def _identity(value):
    if type(value) is not list or len(value) != 2:
        raise EvidenceError('invalid plan evidence')
    return [_integer(part, 2**64 - 1) for part in value]


def _path(value):
    # Reject, rather than normalize, alternate spellings and traversal.
    if (type(value) is not str or not 1 < len(value) <= MAX_PATH_BYTES
            or not value.startswith('/') or '\\' in value
            or any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs') for char in value)):
        raise EvidenceError('invalid plan evidence')
    parts = value[1:].split('/')
    if (len(value.encode('utf-8')) > MAX_PATH_BYTES or len(parts) > MAX_PATH_PARTS
            or any(part in ('', '.', '..') or len(part.encode('utf-8')) > 255 for part in parts)):
        raise EvidenceError('invalid plan evidence')
    return value


def _ancestors(value, target):
    if type(value) is not dict or len(value) > MAX_ANCESTORS:
        raise EvidenceError('invalid plan evidence')
    result = {}
    for path, identity in value.items():
        path = _path(path)
        if not target.startswith(path + '/'):
            raise EvidenceError('invalid plan evidence')
        result[path] = _identity(identity)
    return result


def _field(key, value, target):
    if key == 'ancestors':
        return _ancestors(value, target)
    if key in ('identity', 'fixture_identity'):
        return _identity(value)
    if key in ('uid', 'mode'):
        return _integer(value, 2**32 - 1 if key == 'uid' else 4095)
    if key in ('managed', 'conflict'):
        if type(value) is not bool:
            raise EvidenceError('invalid plan evidence')
    elif key in ('sha256', 'tree_sha256', 'desired_digest'):
        if type(value) is not str or len(value) != 64 or re.fullmatch('[0-9a-f]{64}', value) is None:
            raise EvidenceError('invalid plan evidence')
    elif key in ('state', 'operation'):
        if type(value) is not str or value not in (STATES if key == 'state' else OPERATIONS):
            raise EvidenceError('invalid plan evidence')
    return value  # Validated exact builtin immutable scalar, not an input object.


def validate_evidence(mapping):
    """Return a new dict of typed metadata, or fixed-message EvidenceError.

    All entries are checked, including targets absent from the desired plan.
    Fields are optional: absent/empty evidence remains unknown to the planner.
    Floats (including finite ones) have no supported field in this schema.
    """
    if type(mapping) is not dict or len(mapping) > MAX_TARGETS:
        raise EvidenceError('invalid plan evidence')
    result = {}
    path_bytes = 0
    for target, evidence in mapping.items():
        target = _path(target)
        if (type(evidence) is not dict or len(evidence) > len(FIELDS)
                or any(type(key) is not str or key not in FIELDS for key in evidence)):
            raise EvidenceError('invalid plan evidence')
        copied = {key: _field(key, value, target) for key, value in evidence.items()}
        path_bytes += len(target.encode('utf-8'))
        # The original nested dict is now fully validated; only copied values
        # below are returned. Count repeats because they also repeat in JSON.
        if 'ancestors' in evidence:
            path_bytes += sum(len(path.encode('utf-8')) for path in evidence['ancestors'])
        if path_bytes > 1048576:
            raise EvidenceError('invalid plan evidence')
        result[target] = copied
    return result
