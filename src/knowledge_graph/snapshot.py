"""Detached, content-addressed admitted source generations."""
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .source_policy import PolicyError, exclusion_reason, normalize_policy, unsafe_content


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode('utf-8')).hexdigest()


def _snapshot(repo_id, policy_digest, sources, coverage):
    manifest = {p: hashlib.sha256(t.encode('utf-8')).hexdigest() for p, t in sources.items()}
    result = {'schema_version': 'automator-snapshot/v1', 'repo_id': repo_id,
              'policy_digest': policy_digest, 'manifest': manifest,
              'coverage': coverage}
    result['snapshot_id'] = 'urn:ia:snapshot:' + _digest(result)
    result['sources'] = sources
    return result


def _stamp(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _checked_read(repo: Path, path: str, limit: int):
    """Walk pinned nofollow descriptors, check before open and after read.

    No resolve(), directory enumeration, symlink following or blocking FIFO opens.
    Revalidate every ancestor binding after reading to detect directory renames.
    """
    absolute = Path(repo).absolute() / path
    if '..' in absolute.parts:
        raise PolicyError('unsafe_root')
    fds, bindings = [], []
    try:
        parent = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        fds.append(parent)
        for part in absolute.parts[1:-1]:
            fd = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
            fds.append(fd)
            bindings.append((parent, part, os.fstat(fd)))
            parent = fd
        name = absolute.name
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise PolicyError('unsafe_file')
        if before.st_size > limit:
            raise PolicyError('file_size_limit')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        fds.append(fd)
        opened = os.fstat(fd)
        if _stamp(before) != _stamp(opened):
            raise PolicyError('source_changed')
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > limit:
            raise PolicyError('file_size_limit')
        if (_stamp(os.fstat(fd)) != _stamp(opened)
                or _stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _stamp(opened)):
            raise PolicyError('source_changed')
        for ancestor, component, before_dir in bindings:
            after_dir = os.stat(component, dir_fd=ancestor, follow_symlinks=False)
            if (after_dir.st_dev, after_dir.st_ino, after_dir.st_mode) != (
                    before_dir.st_dev, before_dir.st_ino, before_dir.st_mode):
                raise PolicyError('source_changed')
        text = b''.join(chunks).decode('utf-8')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            raise PolicyError('invalid_text')
        return text
    except UnicodeError:
        raise PolicyError('invalid_text') from None
    except OSError:
        raise PolicyError('unsafe_or_unavailable') from None
    finally:
        for fd in reversed(fds):
            os.close(fd)


def capture_snapshot(repo: Path, policy: dict) -> dict:
    """Capture only explicitly enumerated sources; never discover files."""
    normalized = normalize_policy(policy)
    sources, coverage = {}, []
    used = 0
    for path in normalized['files']:
        reason = exclusion_reason(path)
        if reason:
            coverage.append({'path': 'withheld', 'status': 'excluded', 'reason': reason})
            continue
        remaining = normalized['max_total_bytes'] - used
        if remaining <= 0:
            coverage.append({'path': 'withheld', 'status': 'excluded', 'reason': 'total_size_limit'})
            continue
        try:
            text = _checked_read(repo, path, min(normalized['max_file_bytes'], remaining))
        except PolicyError as exc:
            reason = str(exc)
            if reason == 'file_size_limit' and remaining < normalized['max_file_bytes']:
                reason = 'total_size_limit'
            coverage.append({'path': 'withheld', 'status': 'failed', 'reason': reason})
            continue
        used += len(text.encode('utf-8'))
        if unsafe_content(text):
            coverage.append({'path': 'withheld', 'status': 'excluded', 'reason': 'quarantined_content'})
            continue
        sources[path] = text
        coverage.append({'path': path, 'status': 'scanned', 'reason': 'admitted'})
    # Second checked pass catches changes while other files were being staged.
    # The result is detached immutable *content*, not an atomic filesystem freeze.
    for entry in coverage:
        path = entry['path']
        if entry['status'] != 'scanned':
            continue
        try:
            unchanged = _checked_read(repo, path, normalized['max_file_bytes']) == sources[path]
        except PolicyError:
            unchanged = False
        if not unchanged:
            del sources[path]
            entry.update(path='withheld', status='failed', reason='source_changed')
    return _snapshot(normalized['repo_id'], _digest(normalized), sources, coverage)


def check_freshness(repo: Path, policy: dict, snapshot: dict) -> dict:
    """Compare authorized source IDs only; failure never means current.

    Full snapshots carry sources; persisted metadata omits that field entirely.
    Both use the canonical metadata (including manifest and coverage) as identity.
    Reject forged/mutated snapshot envelopes before opening anything. Policy
    revocation returns stale without reading or naming revoked source IDs.
    """
    unknown = {'current': False, 'status': 'unknown', 'changed': []}
    try:
        normalized = normalize_policy(policy)
        metadata_keys = {
                'schema_version', 'repo_id', 'snapshot_id', 'policy_digest',
                'manifest', 'coverage'}
        if not isinstance(snapshot, dict) or set(snapshot) not in (
                metadata_keys, metadata_keys | {'sources'}):
            return unknown
        if (snapshot['policy_digest'] != _digest(normalized)
                or snapshot['repo_id'] != normalized['repo_id']):
            return {'current': False, 'status': 'stale', 'changed': []}
        if snapshot['schema_version'] != 'automator-snapshot/v1':
            return unknown
        manifest = snapshot['manifest']
        if not isinstance(manifest, dict) or not set(manifest) <= set(normalized['files']):
            return unknown
        for path, digest in manifest.items():
            if exclusion_reason(path) or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
                return unknown
        coverage = snapshot['coverage']
        if not isinstance(coverage, list) or len(coverage) != len(normalized['files']):
            return unknown
        reasons = {
            'scanned': {'admitted'},
            'excluded': {'protected_source', 'unsupported_format', 'total_size_limit', 'quarantined_content'},
            'failed': {'unsafe_root', 'unsafe_file', 'file_size_limit', 'total_size_limit',
                       'source_changed', 'invalid_text', 'unsafe_or_unavailable'},
        }
        scanned = set()
        for path, entry in zip(normalized['files'], coverage):
            if (not isinstance(entry, dict) or set(entry) != {'path', 'status', 'reason'}
                    or not all(isinstance(v, str) for v in entry.values())
                    or entry['reason'] not in reasons.get(entry['status'], set())):
                return unknown
            if entry['status'] == 'scanned':
                if entry['path'] != path or path not in manifest:
                    return unknown
                scanned.add(path)
            elif entry['path'] != 'withheld':
                return unknown
            excluded = exclusion_reason(path)
            if excluded and (entry['status'] != 'excluded' or entry['reason'] != excluded):
                return unknown
        if scanned != set(manifest):
            return unknown
        if 'sources' in snapshot:
            sources = snapshot['sources']
            if not isinstance(sources, dict) or set(sources) != set(manifest):
                return unknown
            for path, text in sources.items():
                if (exclusion_reason(path) or not isinstance(text, str) or unsafe_content(text)
                        or len(text.encode('utf-8')) > normalized['max_file_bytes']):
                    return unknown
            if sum(len(t.encode('utf-8')) for t in sources.values()) > normalized['max_total_bytes']:
                return unknown
            if snapshot != _snapshot(snapshot['repo_id'], snapshot['policy_digest'],
                                     sources, snapshot['coverage']):
                return unknown
        identity = {k: snapshot[k] for k in metadata_keys - {'snapshot_id'}}
        if snapshot['snapshot_id'] != 'urn:ia:snapshot:' + _digest(identity):
            return unknown
        current = capture_snapshot(repo, normalized)
        # A denied/missing/quarantined previously admitted source is unknown and
        # its name is withheld, rather than announcing potentially private data.
        if not set(manifest) <= set(current['sources']):
            return unknown
        if any(c['status'] == 'failed' for c in current['coverage']):
            return unknown
        changed = sorted(p for p in current['manifest']
                         if current['manifest'][p] != manifest.get(p))
        same = current['snapshot_id'] == snapshot['snapshot_id']
        return {'current': same, 'status': 'current' if same else 'stale', 'changed': changed}
    except (PolicyError, TypeError, KeyError, UnicodeError, RecursionError):
        return unknown
