"""Bounded fixture metadata -> non-executable proposal/review companions.

This library is NOT a sandbox. The caller must separately enforce OS read-only
confinement, target authorization, time/resource ceilings and output permissions.
Ordinary reads can update access times. No installer modules are imported.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import ctypes
import struct
import importlib.util
import json
import os
from pathlib import PurePosixPath
from types import SimpleNamespace
import re
import stat
import time

# Preload the same pure validator used by profile parsing and path selection;
# never import from the observed environment or widen sandbox access later.
_workspace_spec = importlib.util.spec_from_file_location(
    'discovery_workspace_paths', os.path.join(os.path.dirname(__file__), 'workspace_paths.py'))
if _workspace_spec is None or _workspace_spec.loader is None:
    raise ImportError('Trusted workspace validator unavailable')
_workspace_paths = importlib.util.module_from_spec(_workspace_spec)
_workspace_spec.loader.exec_module(_workspace_paths)
_metadata_spec = importlib.util.spec_from_file_location(
    'discovery_metadata_readers', os.path.join(os.path.dirname(__file__), 'metadata_readers.py'))
if _metadata_spec is None or _metadata_spec.loader is None:
    raise ImportError('Trusted metadata readers unavailable')
_metadata = importlib.util.module_from_spec(_metadata_spec)
_metadata_spec.loader.exec_module(_metadata)
_shared_spec = importlib.util.spec_from_file_location(
    'discovery_shared_profile', os.path.join(os.path.dirname(__file__), '../../../src/python/workstation_profile.py'))
if _shared_spec is None or _shared_spec.loader is None:
    raise ImportError('Trusted shared profile validator unavailable')
_shared = importlib.util.module_from_spec(_shared_spec)
_shared_spec.loader.exec_module(_shared)

_host_spec = importlib.util.spec_from_file_location(
    'discovery_host_inventory', os.path.join(os.path.dirname(__file__), 'host_inventory.py'))
if _host_spec is None or _host_spec.loader is None:
    raise ImportError('Trusted host inventory validator unavailable')
_host = importlib.util.module_from_spec(_host_spec)
_host_spec.loader.exec_module(_host)

DEFAULT_LIMITS = {'max_sources': 32, 'max_entries': 64, 'max_bytes': 65536, 'max_seconds': 2}
HARD_LIMITS = {'max_sources': 128, 'max_entries': 1024, 'max_bytes': 262144, 'max_seconds': 30}


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise DiscoveryError('Unsupported discovery document shape')


def _limits(value):
    if value is None:
        return dict(DEFAULT_LIMITS)
    if type(value) is not dict or set(value) - set(DEFAULT_LIMITS):
        raise DiscoveryError('Unsupported discovery limits')
    for key, number in value.items():
        if type(number) not in (int, float) or not 0 < number <= HARD_LIMITS[key]:
            raise DiscoveryError('Invalid discovery limit')
        if key != 'max_seconds' and type(number) is not int:
            raise DiscoveryError('Count and byte limits must be integers')
    return {**DEFAULT_LIMITS, **value}


def _stop_reason(deadline, cancelled):
    if cancelled is not None and cancelled():
        return 'cancelled'
    if time.monotonic() >= deadline:
        return 'time_limit'
    return None


class DiscoveryError(ValueError):
    """Invalid discovery input; diagnostics never embed untrusted values."""


LIMITATIONS = [
    'Metadata presence does not prove functionality, compatibility or necessity.',
    'Only explicitly selected Git metadata read; no index, objects, diffs or config includes.',
    'Git HEAD is not evidence of clean work or reproducibility; dirty status remains unknown.',
    'No live target authorization or OS confinement is provided by this library.',
    'Companions are not executable profiles; legacy and Ansible export unsupported.',
    'Full-machine parity, source provenance and package compatibility are unknown.',
]


def _revision(document):
    payload = {k: v for k, v in document.items() if k not in ('revision', 'collected_at')}
    return 'sha256:' + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _document(kind, **data):
    doc = {'schema_version': 'v1alpha1', 'kind': kind, 'apply_supported': False,
           'limitations': list(LIMITATIONS), **data}
    doc['revision'] = _revision(doc)
    return doc


def _safe_text(value, pattern=r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', maximum=64):
    if type(value) is not str or len(value) > maximum or not re.fullmatch(pattern, value):
        raise DiscoveryError('Invalid nonsecret discovery value')
    if re.search(r'(?i)(?:token|password|secret|credential|bearer)[=_:-]|gh[pousr]_|sk-', value):
        raise DiscoveryError('Sensitive-looking discovery value refused')
    return value


def _workspace_name(value):
    try:
        _workspace_paths.validate_segment(value)
    except ValueError:
        raise DiscoveryError('Invalid workspace name') from None
    return _safe_text(value, r'.+', len(value))


def _path(value):
    _safe_text(value, r'/[A-Za-z0-9_./ -]+', 4096)
    if any(p in ('', '.', '..') for p in value.split('/')[1:]) or len(PurePosixPath(value).parts) < 3:
        raise DiscoveryError('Select a specific absolute path without traversal')
    return value


def _open_directory(path):
    """Walk descriptors, rejecting symlinks in every selected component."""
    fd = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in PurePosixPath(path).parts[1:]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _bounded_entries(fd, maximum):
    """Read Linux dirents without scandir's implicit fcntl FD duplication.

    The caller owns this disposable directory descriptor. getdents64 is already
    admitted by the reader seccomp policy; never widen fcntl/dup permissions.
    """
    if _getdents64 is None:
        raise OSError('bounded directory reader unavailable')
    buffer = ctypes.create_string_buffer(8192)
    emitted = 0
    while emitted < maximum:
        size = _getdents64(fd, buffer, len(buffer))
        if size < 0:
            raise OSError('bounded directory read failed')
        if size == 0:
            break
        data, offset = buffer.raw[:size], 0
        while offset < size and emitted < maximum:
            if size - offset < 20:
                raise OSError('invalid directory metadata')
            length = struct.unpack_from('=H', data, offset + 16)[0]
            if length < 20 or offset + length > size:
                raise OSError('invalid directory metadata')
            name = data[offset + 19:offset + length]
            if b'\0' not in name:
                raise OSError('invalid directory metadata')
            name = name.split(b'\0', 1)[0]
            offset += length
            if name in (b'.', b'..'):
                continue
            emitted += 1
            yield os.fsdecode(name)


# Linux statx mount IDs distinguish bind mounts on the same device. Preload
# libc before confinement; unavailable kernel/libc support fails closed.
_libc = ctypes.CDLL(None, use_errno=True)
_statx = getattr(_libc, 'statx', None)
_getdents64 = getattr(_libc, 'getdents64', None)
if _getdents64 is not None:
    _getdents64.restype = ctypes.c_ssize_t
    _getdents64.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)


def _mount_id(fd):
    if _statx is None:
        raise OSError('mount identity unavailable')
    buffer = ctypes.create_string_buffer(256)
    if _statx(fd, ctypes.c_char_p(b''), 0x1000 | 0x100, 0x1000, ctypes.byref(buffer)) != 0:
        raise OSError('mount identity unavailable')
    mask = struct.unpack_from('=I', buffer.raw, 0)[0]
    mount = struct.unpack_from('=Q', buffer.raw, 144)[0]
    if not mask & 0x1000 or not mount:
        raise OSError('mount identity unavailable')
    return mount


def _read_metadata(directory_fd, filename, maximum, budget=None):
    # Every intermediate component is descriptor-relative and no-follow too.
    parts = filename.split('/')
    if any(part in ('', '.', '..') for part in parts) or len(parts) > 16:
        raise OSError('unsafe metadata path')
    mount = _mount_id(directory_fd)
    parent = os.open('.', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if _mount_id(child) != mount:
                    raise OSError('metadata mount crossing')
            except BaseException:
                os.close(child)
                raise
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        if _mount_id(fd) != mount:
            raise OSError('metadata mount crossing')
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError('unsafe metadata')
        if budget is not None:
            maximum = min(maximum, budget['remaining'])
        if before.st_size > maximum:
            raise _metadata.MetadataError('byte_limit')
        chunks, size = [], 0
        while size < maximum:
            if budget is not None:
                stopped = _stop_reason(budget['deadline'], budget['cancelled'])
                if stopped:
                    raise _metadata.MetadataError(stopped)
            chunk = os.read(fd, min(8192, maximum - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if budget is not None:
                budget['remaining'] -= len(chunk)
        after = os.fstat(fd)
        if size != before.st_size:
            raise DiscoveryError('metadata_changed')
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink):
            raise DiscoveryError('metadata_changed')
        return b''.join(chunks).decode('utf-8')
    finally:
        os.close(fd)


def _unique_json(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise DiscoveryError('Duplicate metadata keys')
        values[key] = value
    return values


def _dist_info(raw):
    values = {}
    for line in raw.splitlines():
        if not line:
            break
        key, separator, value = line.partition(':')
        if separator and key.lower() in ('name', 'version'):
            if key.lower() in values:
                raise DiscoveryError('duplicate_metadata')
            values[key.lower()] = _safe_text(value.strip(), r'[A-Za-z0-9][A-Za-z0-9_.+!-]{0,127}', 128)
    if set(values) != {'name', 'version'}:
        raise DiscoveryError('incomplete_metadata')
    _package(values)
    return values


def admission_paths(*, git_sources=(), metadata_sources=()):
    """Pure validation and exact grant candidates; NEVER stats or opens selections.

    directories: always empty; no Git object/index/checkout-wide grants.
    files: explicitly selected manifest files. optional_files: exact possible Git
    metadata files, pinned only if present (absence remains unknown as needed).
    Caller pins with O_PATH/no-follow before confinement; never grant parents.
    """
    _require(all(type(s) in (list, tuple) for s in (git_sources, metadata_sources)))
    _require(len(git_sources) + len(metadata_sources) <= HARD_LIMITS['max_sources'])
    optional_files, files = set(), set()
    for selections, expected in ((git_sources, {'id', 'root', 'git_dir', 'common_dir', 'ref_paths'}),
                                 (metadata_sources, {'id', 'path', 'format', 'environment', 'placement'})):
        seen = set()
        for selected in selections:
            _keys(selected, expected | ({'component'} if type(selected) is dict and 'component' in selected and 'git_dir' in expected else set())
                  | ({'runtime'} if type(selected) is dict and 'runtime' in selected and 'placement' in expected else set()))
            _safe_text(selected['id'])
            _require(selected['id'] not in seen)
            seen.add(selected['id'])
    for selected in git_sources:
        if 'component' in selected:
            component = selected['component']
            _require(type(component) is str and component in ('lab', 'arena', 'gr00t', 'lerobot'))
        for key in ('root', 'git_dir', 'common_dir'):
            _path(selected[key])
        _bounded_list(selected['ref_paths'], HARD_LIMITS['max_entries'])
        for ref in selected['ref_paths']:
            _safe_text(ref, r'refs/[A-Za-z0-9_./-]+', 256)
            _require(not any(p in ('', '.', '..') for p in ref.split('/')))
            _require(len(ref.split('/')) <= 16)
        _require(len(selected['ref_paths']) == len(set(selected['ref_paths'])))
        root, git, common = (selected[k] for k in ('root', 'git_dir', 'common_dir'))
        if git != os.path.join(root, '.git'):
            optional_files.add(os.path.join(root, '.git'))
        optional_files.add(os.path.join(root, '.gitmodules'))
        optional_files.update(os.path.join(git, name) for name in ('HEAD', 'commondir'))
        optional_files.update(os.path.join(common, name) for name in ('config', 'packed-refs'))
        optional_files.update(os.path.join(common, ref) for ref in selected['ref_paths'])
    formats = {'environment-json': ('environment.json', 'tools.json'),
               'pyproject': ('pyproject.toml',), 'uv-lock-json': ('uv.lock.json',), 'uv-lock': ('uv.lock',)}
    for selected in metadata_sources:
        if 'runtime' in selected:
            runtime = selected['runtime']
            _require(type(runtime) is str and runtime in ('lab', 'gr00t', 'lerobot'))
        _path(selected['path'])
        _safe_text(selected['environment'])
        _require(type(selected['format']) is str and selected['format'] in formats)
        _require(PurePosixPath(selected['path']).name in formats[selected['format']])
        _require(type(selected['placement']) is str and selected['placement'] in
                 ('host', 'container', 'environment', 'project', 'unknown'))
        files.add(selected['path'])
    return {'directories': [], 'files': sorted(files), 'optional_files': sorted(optional_files)}


def observe(*, workspaces=(), package_sources=(), git_sources=(), metadata_sources=(), target='fixture', limits=None, cancelled=None, previous_baseline=None):
    """Observe selected metadata; prior origin adds exclusions, NEVER read grants."""
    prior_roots = original_observed_roots(previous_baseline) if previous_baseline is not None else []
    _safe_text(target)
    limits = _limits(limits)
    deadline = time.monotonic() + limits['max_seconds']
    if any(type(s) not in (list, tuple) for s in (workspaces, package_sources, git_sources, metadata_sources)):
        raise DiscoveryError('Selections must be bounded lists')
    if sum(map(len, (workspaces, package_sources, git_sources, metadata_sources))) > limits['max_sources']:
        raise DiscoveryError('Too many selected metadata sources')
    if cancelled is not None and not callable(cancelled):
        raise DiscoveryError('Cancellation must be a callback')
    for selections, expected in ((workspaces, {'id', 'name', 'root'}),
                                 (package_sources, {'id', 'path', 'format', 'environment'}),
                                 (git_sources, {'id', 'root', 'git_dir', 'common_dir', 'ref_paths'})):
        seen = set()
        for selected in selections:
            _keys(selected, expected | ({'component'} if type(selected) is dict and 'component' in selected and 'git_dir' in expected else set())
                  | ({'runtime'} if type(selected) is dict and 'runtime' in selected and 'placement' in expected else set()))
            identifier = _safe_text(selected['id'])
            if identifier in seen:
                raise DiscoveryError('Duplicate selected source identity')
            seen.add(identifier)
    for selected in workspaces:
        _safe_text(selected['id'])
        _workspace_name(selected['name'])
        _path(selected['root'])
    for selected in package_sources:
        _safe_text(selected['id'])
        _safe_text(selected['environment'])
        _path(selected['path'])
        path = PurePosixPath(selected['path'])
        if not ((selected['format'] == 'dist-info' and path.name == 'METADATA' and path.parent.name.endswith('.dist-info'))
                or (selected['format'] == 'conda' and path.name == 'conda-meta')):
            raise DiscoveryError('Select an admitted metadata location')
    admission_paths(git_sources=git_sources, metadata_sources=metadata_sources)
    observations = []
    for selected in workspaces:
        root = selected['root']
        value = {'root': root, 'name': selected['name'], 'git_marker': 'unknown'}
        item = {'id': 'workspace:' + selected['id'], 'status': 'inaccessible', 'value': value,
                'evidence': {'method': 'selected-directory-entry-metadata', 'path': root}}
        stopped = _stop_reason(deadline, cancelled)
        if stopped:
            item.update(status='unknown', reason=stopped)
            observations.append(item)
            continue
        try:
            fd = _open_directory(root)
            try:
                value['git_marker'] = 'absent'
                try:
                    mode = os.stat('.git', dir_fd=fd, follow_symlinks=False).st_mode
                    value['git_marker'] = ('directory' if stat.S_ISDIR(mode) else
                                           'file' if stat.S_ISREG(mode) else 'unsupported')
                except FileNotFoundError:
                    pass
            finally:
                os.close(fd)
            item['status'] = 'observed'
        except OSError:
            item['reason'] = 'unreadable_or_unsafe_path'
        observations.append(item)
    remaining_entries = limits['max_entries']
    byte_budget = {'remaining': limits['max_bytes'], 'deadline': deadline, 'cancelled': cancelled}

    def consume():
        nonlocal remaining_entries
        stopped = _stop_reason(deadline, cancelled)
        if stopped:
            raise _metadata.MetadataError(stopped)
        if remaining_entries <= 0:
            raise _metadata.MetadataError('entry_limit')
        remaining_entries -= 1

    for selected in package_sources:
        path = PurePosixPath(selected['path'])
        is_conda = selected['format'] == 'conda'
        item = {'id': 'packages:' + selected['id'], 'status': 'unknown',
                'value': {'environment': selected['environment'], 'packages': []},
                'evidence': {'method': 'conda-name-version' if is_conda else 'dist-info-name-version', 'path': str(path)}}
        stopped = _stop_reason(deadline, cancelled) or ('entry_limit' if remaining_entries <= 0 else None)
        if stopped:
            item['reason'] = stopped
            observations.append(item)
            continue
        try:
            fd = _open_directory(str(path if is_conda else path.parent))
            try:
                if is_conda:
                    packages = item['value']['packages']
                    scan_fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        entries = list(_bounded_entries(scan_fd, remaining_entries + 1))
                    finally:
                        os.close(scan_fd)
                    for index, entry_name in enumerate(entries):
                        stopped = _stop_reason(deadline, cancelled)
                        if stopped:
                            item['reason'] = stopped
                            break
                        if remaining_entries <= 0:
                            item['reason'] = 'entry_limit'
                            break
                        remaining_entries -= 1
                        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,191}\.json', entry_name):
                            continue
                        raw = _read_metadata(fd, entry_name, limits['max_bytes'], byte_budget)
                        data = json.loads(raw, object_pairs_hook=_unique_json)
                        package = {key: data[key] for key in ('name', 'version')}
                        _package(package)
                        packages.append(package)
                    packages.sort(key=lambda p: (p['name'], p['version']))
                else:
                    remaining_entries -= 1
                    raw = _read_metadata(fd, path.name, limits['max_bytes'], byte_budget)
                    item['value']['packages'] = [_dist_info(raw)]
                if 'reason' not in item:
                    item['status'] = 'observed'
            finally:
                os.close(fd)
        except OSError:
            item.update(status='inaccessible', reason='unreadable_or_unsafe_path')
        except _metadata.MetadataError as error:
            item['reason'] = str(error)
        except (ValueError, KeyError, TypeError, RecursionError):
            item['reason'] = 'invalid_incomplete_or_oversize_metadata'
        unique, conflicting = {}, set()
        for package in item['value']['packages']:
            normalized = re.sub(r'[-_.]+', '-', package['name']).lower()
            if normalized in unique and unique[normalized]['version'] != package['version']:
                conflicting.add(normalized)
            unique[normalized] = package
        if conflicting:
            item.update(status='conflicting', reason='conflicting_package_metadata')
        item['value']['packages'] = [unique[k] for k in sorted(unique) if k not in conflicting]
        observations.append(item)
    for selected in list(git_sources) + list(metadata_sources):
        is_git = 'git_dir' in selected
        item = {'id': ('repository:' if is_git else 'environment:') + selected['id'], 'status': 'unknown',
                'value': (_metadata.repository_value(selected) if is_git else _metadata.environment_value(selected)),
                'evidence': {'method': 'selected-git-metadata' if is_git else 'selected-environment-metadata',
                             'path': selected['root'] if is_git else selected['path']}}
        stopped = _stop_reason(deadline, cancelled) or ('entry_limit' if remaining_entries <= 0 else None)
        if stopped:
            item['reason'] = stopped
        else:
            def read(directory, name):
                consume()
                fd = _open_directory(directory)
                try:
                    return _read_metadata(fd, name, limits['max_bytes'], byte_budget)
                finally:
                    os.close(fd)
            try:
                reader = _metadata.read_git if is_git else _metadata.read_environment
                item['value'] = reader(selected, read, item['value'], consume)
                stopped = _stop_reason(deadline, cancelled)
                if stopped:
                    raise _metadata.MetadataError(stopped)
                item['status'] = 'observed'
            except OSError:
                item.update(status='inaccessible', reason='unreadable_or_unsafe_path')
            except _metadata.MetadataError as error:
                item['reason'] = str(error)
                if str(error) == 'conflicting_tool_metadata':
                    item['status'] = 'conflicting'
            except (ValueError, KeyError, TypeError, RecursionError):
                item['reason'] = 'invalid_incomplete_or_oversize_metadata'
        observations.append(item)
    roots = sorted(set(prior_roots) | _observation_roots(observations))
    _validate_origin_roots(roots)  # Never truncate cumulative history to fit a budget.
    return _document('workstation-baseline', target=target, limits=limits,
                     original_observed_roots=roots,
                     incomplete=any(o['status'] != 'observed' for o in observations),
                     collected_at=datetime.now(timezone.utc).isoformat(), observations=observations)


def _require(condition):
    if not condition:
        raise DiscoveryError('Invalid or unsupported discovery companion')


def _digest(value):
    _require(type(value) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value) is not None)


def _bounded_list(value, maximum):
    _require(type(value) is list and len(value) <= maximum)


def _reason(value):
    if value is not None:
        _safe_text(value, r'[A-Za-z0-9][A-Za-z0-9 .,_-]{0,159}', 160)
        _require(re.search(r'(?i)\b(password|secret|credential|token|bearer)\b', value) is None)


def _package(value, custom=False):
    _keys(value, {'name', 'version', 'environment', 'location'} if custom else {'name', 'version'})
    _safe_text(value['name'], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', 128)
    _safe_text(value['version'], r'[0-9][A-Za-z0-9_.+!-]{0,63}', 64)
    if custom:
        _safe_text(value['environment'])
        _path(value['location'])


def _field_kind(identifier):
    _safe_text(identifier, r'[A-Za-z0-9][A-Za-z0-9_.:+!-]{0,209}', 210)
    if re.fullmatch(r'coverage:(repository|environment):[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', identifier):
        return 'coverage'
    if re.fullmatch(r'repository:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', identifier):
        return 'repository'
    if re.fullmatch(r'environment:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', identifier):
        return 'environment'
    if re.fullmatch(r'tool:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', identifier):
        return 'tool'
    if re.fullmatch(r'note:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:[0-9]{1,4}', identifier):
        return 'note'
    if re.fullmatch(r'component:(sim|lab|arena|gr00t|lerobot)\.execution', identifier):
        return 'execution'
    if re.fullmatch(r'component:(sim|lab|arena|gr00t|lerobot)\.source', identifier):
        return 'component-source'
    if re.fullmatch(r'runtime:(kit|lab|gr00t|lerobot)', identifier):
        return 'runtime'
    if identifier == 'components.selection':
        return 'components'
    if re.fullmatch(r'workspace:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.(root|name|layout)', identifier):
        return identifier.rsplit('.', 1)[1]
    if re.fullmatch(r'custom:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:(?:__coverage__|[A-Za-z0-9][A-Za-z0-9_.+!-]{0,127})', identifier):
        return 'custom'
    raise DiscoveryError('Unsupported discovery field identity')


def _field_value(identifier, value):
    kind = _field_kind(identifier)
    if value is None:
        return
    if kind == 'coverage':
        _require(value is None)
    elif kind == 'repository':
        try:
            _metadata.validate_repository(value, _path)
        except ValueError:
            raise DiscoveryError('Invalid repository metadata') from None
    elif kind in ('execution', 'component-source') or identifier == 'runtime:kit':
        _declared_value(identifier, value)
    elif kind == 'runtime':
        try:
            _metadata.validate_runtime(value, identifier.split(':', 1)[1])
        except ValueError:
            # Observed metadata may be outside desired grammar; explicit extra
            # intent fields must satisfy the shared schema, never arbitrary keys.
            _declared_value(identifier, value)
    elif kind in ('environment', 'tool', 'note'):
        try:
            if kind == 'environment':
                _metadata.validate_environment(value, _path)
            elif kind == 'tool':
                # Desired null placement uses the consumer's selected environment.
                # Observed paths remain in baseline evidence and original roots;
                # the metadata reader's default path contract stays strict.
                _metadata.validate_tool(value, _path, allow_unbound_location=True)
            else:
                _metadata.note(value)
        except ValueError:
            raise DiscoveryError('Invalid customization metadata') from None
    elif kind == 'root':
        _path(value)
    elif kind == 'name':
        _workspace_name(value)
    elif kind == 'layout':
        _require(value in ('named', 'legacy'))
    elif kind == 'custom':
        _package(value, custom=True)
    else:
        _bounded_list(value, 5)
        _require(all(type(v) is str and v in ('sim', 'lab', 'arena', 'gr00t', 'lerobot') for v in value))
        _require(len(value) == len(set(value)))


def _declared_value(identifier, value):
    """Only bounded shared desired grammar, never observations or commands."""
    kind = _field_kind(identifier)
    _require(value is not None and kind in ('component-source', 'runtime', 'execution'))
    try:
        if kind == 'runtime':
            _require(type(value) is dict and {'manager', 'environment'} <= set(value))
            overlay = {'runtimes': {identifier.split(':', 1)[1]: value}}
        else:
            component, key = identifier.split(':', 1)[1].split('.', 1)
            if kind == 'component-source':
                _require(type(value) is dict)
                required = ({'mode', 'version', 'sha256'} if component == 'sim' and value.get('mode') == 'standalone'
                            else {'mode', 'repository', 'ref', 'revision'})
                _require(required <= set(value))
            overlay = {'components': {component: {key: value}}}
        _shared._validate(overlay, overlay=True)
    except _shared.ProfileError:
        raise DiscoveryError('Invalid declared shared intent') from None


def _observation_roots(observations):
    roots = {item['evidence']['path'] for item in observations}
    for item in observations:
        if item['id'].startswith('repository:'):
            roots.update(item['value'][key] for key in ('root', 'git_dir', 'common_dir'))
    return roots


def _validate_origin_roots(roots):
    _bounded_list(roots, 128)
    for root in roots:
        _path(root)
    _require(roots == sorted(set(roots)))


def original_observed_roots(baseline):
    """Validated immutable baseline origin, not candidate/suggested/desired values.

    Missing legacy origin is unknown, even for an empty current scan. Revisions
    detect inconsistent documents, not malicious replacement of whole bundles.
    """
    _validate_document(baseline, 'workstation-baseline')
    return list(baseline['original_observed_roots'])


def _validate_document(doc, kind):
    """Validate untrusted deserialized companions; digests are not signatures."""
    common = {'schema_version', 'kind', 'apply_supported', 'limitations', 'revision'}
    expected = ({'target', 'limits', 'incomplete', 'collected_at', 'observations', 'original_observed_roots'}
                if kind == 'workstation-baseline' else {'baseline_revision', 'fields'})
    _keys(doc, common | expected)
    _require(doc['kind'] == kind and doc['schema_version'] == 'v1alpha1')
    _require(doc['apply_supported'] is False and doc['limitations'] == LIMITATIONS)
    _digest(doc['revision'])
    if kind == 'workstation-baseline':
        _safe_text(doc['target'])
        limits = _limits(doc['limits'])
        _require(doc['limits'] == limits and type(doc['incomplete']) is bool)
        _safe_text(doc['collected_at'], r'[0-9T:.+Z-]{20,40}', 40)
        _bounded_list(doc['observations'], limits['max_sources'])
        seen = set()
        for item in doc['observations']:
            _require(type(item) is dict)
            _keys(item, {'id', 'status', 'value', 'evidence'} | ({'reason'} if 'reason' in item else set()))
            _require(type(item['id']) is str and item['id'] not in seen)
            seen.add(item['id'])
            _require(item['status'] in ('observed', 'conflicting', 'inaccessible', 'unknown', 'not_selected'))
            if 'reason' in item:
                _require(item['reason'] in ('unreadable_or_unsafe_path', 'invalid_incomplete_or_oversize_metadata',
                                           'entry_limit', 'cancelled', 'time_limit', 'conflicting_package_metadata',
                                           'invalid_metadata', 'indirection_not_selected', 'ref_not_selected', 'config_include_refused', 'toml_unavailable', 'byte_limit', 'unresolved_ref', 'conflicting_tool_metadata',
                                           'worktree_config_unsupported', 'dynamic_metadata_unsupported'))
            _keys(item['evidence'], {'method', 'path'})
            _path(item['evidence']['path'])
            if item['id'].startswith('workspace:'):
                _safe_text(item['id'][10:])
                _keys(item['value'], {'root', 'name', 'git_marker'})
                _path(item['value']['root'])
                _workspace_name(item['value']['name'])
                _require(item['value']['root'] == item['evidence']['path'])
                _require(item['value']['git_marker'] in ('absent', 'directory', 'file', 'unsupported', 'unknown'))
                _require(item['evidence']['method'] == 'selected-directory-entry-metadata')
            elif item['id'].startswith('environment:'):
                _safe_text(item['id'][12:])
                _metadata.validate_environment(item['value'])
                _require(item['evidence']['method'] == 'selected-environment-metadata')
            elif item['id'].startswith('repository:'):
                _safe_text(item['id'][11:])
                _metadata.validate_repository(item['value'], _path)
                _require(item['evidence']['method'] == 'selected-git-metadata')
                _require(item['evidence']['path'] == item['value']['root'])
            elif item['id'] == 'host:inventory':
                _require(item['evidence']['method'] == 'imported-host-inventory')
                _host.validate_report(item['value'])
                _require(item['status'] == ('observed' if item['value']['coverage']['complete'] else 'unknown'))
            else:
                _require(item['id'].startswith('packages:'))
                _safe_text(item['id'][9:])
                _keys(item['value'], {'environment', 'packages'})
                _safe_text(item['value']['environment'])
                _require(item['evidence']['method'] in ('dist-info-name-version', 'conda-name-version'))
                _bounded_list(item['value']['packages'], limits['max_entries'])
                for package in item['value']['packages']:
                    _package(package)
        _require(doc['incomplete'] == any(o['status'] != 'observed' for o in doc['observations']))
        _validate_origin_roots(doc['original_observed_roots'])
        _require(_observation_roots(doc['observations']) <= set(doc['original_observed_roots']))
    else:
        _digest(doc['baseline_revision'])
        _bounded_list(doc['fields'], 4096)
        seen = set()
        for field in doc['fields']:
            _keys(field, {'id', 'value', 'suggested_value', 'evidence', 'required', 'state', 'decision', 'reason',
                          'decision_revision', 'rationale', 'alternatives', 'support', 'evidence_changed', 'not_selected', 'evidence_revision'})
            _digest(field['evidence_revision'])
            if field['rationale'] == 'user_declared_intent':
                _declared_value(field['id'], field['value'])
                _require(field['suggested_value'] is None and field['evidence'] == []
                         and field['alternatives'] == [] and not field['evidence_changed']
                         and not field['not_selected'] and field['evidence_revision'] == _revision({}))
            else:
                _field_value(field['id'], field['value'])
            _field_value(field['id'], field['suggested_value'])
            _require(field['id'] not in seen)
            seen.add(field['id'])
            _bounded_list(field['evidence'], HARD_LIMITS['max_sources'])
            for evidence in field['evidence']:
                _safe_text(evidence, r'(workspace|packages|repository|environment|host):[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', 80)
            _require(len(field['evidence']) == len(set(field['evidence'])))
            for key in ('required', 'evidence_changed', 'not_selected'):
                _require(type(field[key]) is bool)
            _require(field['support'] == 'unsupported')
            _bounded_list(field['alternatives'], HARD_LIMITS['max_sources'])
            if _field_kind(field['id']) not in ('component-source', 'runtime'):
                _require(field['alternatives'] == [])
            for alternative in field['alternatives']:
                _require(alternative is not None)
                _field_value(field['id'], alternative)
            _require(field['rationale'] in ('explicit_user_selection_not_remote_inference', 'component_intent_not_observed',
                                            'package_presence_does_not_establish_required_intent', 'incomplete_package_coverage',
                                            'selected_metadata_does_not_establish_required_intent', 'user_declared_intent'))
            _reason(field['reason'])
            decision = field['decision']
            _require(decision in (None, 'accept', 'edit', 'reject', 'defer', 'declare'))
            if decision == 'declare':
                _require(field['rationale'] == 'user_declared_intent')
            if decision is None:
                _require(field['state'] in ('proposed', 'unresolved') and field['decision_revision'] is None)
            else:
                _digest(field['decision_revision'])
                _require(field['state'] == {'accept': 'accepted', 'edit': 'accepted', 'declare': 'accepted', 'reject': 'rejected', 'defer': 'unresolved'}[decision])
            if field['state'] == 'accepted':
                _require(field['value'] is not None)
        _require('components.selection' in seen)
    _require(doc['revision'] == _revision(doc))


def _field(identifier, value, evidence, required, rationale):
    return {'id': identifier, 'value': deepcopy(value), 'suggested_value': deepcopy(value),
            'evidence': evidence, 'required': required,
            'state': 'proposed' if value is not None else 'unresolved',
            'decision': None, 'reason': None, 'decision_revision': None,
            'rationale': rationale, 'alternatives': [], 'support': 'unsupported',
            'evidence_changed': False, 'not_selected': False, 'evidence_revision': _revision({})}


def _merge_associated_fields(fields):
    """One source field per explicit label, never choose the first clone."""
    groups, result = {}, []
    for field in fields:
        if _field_kind(field['id']) in ('component-source', 'runtime'):
            groups.setdefault(field['id'], []).append(field)
        else:
            result.append(field)
    for identifier, candidates in sorted(groups.items()):
        if len(candidates) == 1:
            result.append(candidates[0])
            continue
        unique = {_revision({'value': field['value']}): field['value']
                  for field in candidates if field['value'] is not None}
        options = [unique[key] for key in sorted(unique)]
        unambiguous = len(options) == 1 and all(f['value'] is not None for f in candidates)
        merged = _field(identifier, options[0] if unambiguous else None,
                        sorted({key for field in candidates for key in field['evidence']}), False,
                        'selected_metadata_does_not_establish_required_intent')
        merged['alternatives'] = [] if unambiguous else options
        result.append(merged)
    return result


def propose(baseline, previous=None):
    """Propose companion fields; root is exactly selected, not root/name joined."""
    _validate_document(baseline, 'workstation-baseline')
    if previous is not None:
        _validate_document(previous, 'workstation-candidate')
    fields = []
    for item in baseline['observations']:
        if item['id'] == 'host:inventory':
            fields.extend(_host.propose_fields(item, discovery=SimpleNamespace(
                _field=_field, _field_value=_field_value)))
        elif item['id'].startswith('workspace:'):
            for key in ('root', 'name', 'layout'):
                value = 'named' if key == 'layout' else item['value'][key]
                fields.append(_field(item['id'] + '.' + key, value, [item['id']], True,
                                     'explicit_user_selection_not_remote_inference'))
        elif item['id'].startswith('environment:'):
            source_id = item['id'].split(':', 1)[1]
            observed = item['value']
            if observed['runtime'] is not None:
                value = _metadata.runtime_value(observed) if item['status'] == 'observed' else None
                fields.append(_field('runtime:' + observed['runtime'], value, [item['id']], False,
                                     'selected_metadata_does_not_establish_required_intent'))
            env = {k: observed[k] for k in ('name', 'manager', 'placement', 'python')}
            env['location'] = item['evidence']['path']
            fields.append(_field(item['id'], env, [item['id']], False,
                                 'selected_metadata_does_not_establish_required_intent'))
            for tool in observed['tools']:
                value = {**tool, 'environment': env['name'], 'placement': env['placement'], 'location': env['location']}
                field = _field('tool:' + source_id + ':' + tool['name'], value, [item['id']], False,
                               'selected_metadata_does_not_establish_required_intent')
                field['state'] = 'unresolved'
                fields.append(field)
            for index, note in enumerate(observed['notes']):
                fields.append(_field('note:' + source_id + ':' + str(index), note, [item['id']], False,
                                     'selected_metadata_does_not_establish_required_intent'))
            if item['status'] != 'observed':
                fields.append(_field('coverage:' + item['id'], None, [item['id']], False,
                                     'selected_metadata_does_not_establish_required_intent'))
        elif item['id'].startswith('repository:'):
            component = item['value']['component']
            if component is not None:
                value = _metadata.component_source(item['value']) if item['status'] == 'observed' else None
                fields.append(_field('component:' + component + '.source', value, [item['id']], False,
                                     'selected_metadata_does_not_establish_required_intent'))
            if item['status'] != 'observed':
                fields.append(_field('coverage:' + item['id'], None, [item['id']], False,
                                     'selected_metadata_does_not_establish_required_intent'))
            fields.append(_field(item['id'], item['value'], [item['id']], False,
                                 'selected_metadata_does_not_establish_required_intent'))
        elif item['id'].startswith('packages:'):
            source_id = item['id'].split(':', 1)[1]
            for package in item['value']['packages']:
                value = {**package, 'environment': item['value']['environment'], 'location': item['evidence']['path']}
                field = _field('custom:' + source_id + ':' + package['name'], value, [item['id']], False,
                               'package_presence_does_not_establish_required_intent')
                field['state'] = 'unresolved'
                fields.append(field)
            if item['status'] != 'observed':
                fields.append(_field('custom:' + source_id + ':__coverage__', None, [item['id']], False,
                                     'incomplete_package_coverage'))
    fields = _merge_associated_fields(fields)
    fields.append(_field('components.selection', None, [], True, 'component_intent_not_observed'))
    evidence_revisions = {item['id']: _revision(item) for item in baseline['observations']}
    for field in fields:
        if field['evidence']:
            field['evidence_revision'] = (evidence_revisions[field['evidence'][0]] if len(field['evidence']) == 1 else
                                          _revision({key: evidence_revisions[key] for key in field['evidence']}))
    if previous is not None:
        prior = {p['id']: p for p in previous['fields']}
        for field in fields:
            old = prior.pop(field['id'], None)
            if old and old['rationale'] == 'user_declared_intent':
                # Independent desired intent never becomes observed evidence.
                field.clear()
                field.update(deepcopy(old))
                continue
            if old and old['decision'] is not None:
                for key in ('value', 'state', 'decision', 'reason', 'decision_revision', 'required'):
                    field[key] = deepcopy(old[key])
                field['evidence_changed'] = (old['suggested_value'] != field['suggested_value']
                                             or old['evidence_revision'] != field['evidence_revision']
                                             or old['evidence_changed'])
        for old in prior.values():
            retained = deepcopy(old)
            if old['rationale'] != 'user_declared_intent':
                retained.update(not_selected=True, evidence_changed=True)
            fields.append(retained)
    return _document('workstation-candidate', baseline_revision=baseline['revision'], fields=fields)


def review(candidate, field_id, decision, *, value=None, reason=None, required=None):
    """Return revised intent; approval is never authorization to execute."""
    _validate_document(candidate, 'workstation-candidate')
    result = deepcopy(candidate)
    if decision not in ('accept', 'edit', 'reject', 'defer', 'declare'):
        raise DiscoveryError('Unsupported review decision')
    field = next((p for p in result['fields'] if p['id'] == field_id), None)
    if decision == 'declare':
        if field is not None:
            raise DiscoveryError('Existing fields require ordinary review')
        _require(len(result['fields']) < 4096)
        _declared_value(field_id, value)
        field = _field(field_id, None, [], False, 'user_declared_intent')
        result['fields'].append(field)
    if field is None:
        raise DiscoveryError('Unknown review field')
    if decision in ('edit', 'declare'):
        if field['rationale'] == 'user_declared_intent':
            _declared_value(field_id, value)
        else:
            _field_value(field_id, value)
        field['value'] = deepcopy(value)
    elif value is not None:
        raise DiscoveryError('Only edit accepts a replacement value')
    if decision in ('accept', 'edit') and field['value'] is None:
        raise DiscoveryError('Unknown intent requires an explicit edit')
    _reason(reason)
    if required is not None:
        if type(required) is not bool:
            raise DiscoveryError('Required must be boolean')
        field['required'] = required
    # A fresh acceptance/edit acknowledges the currently selected evidence,
    # not the suggestion: retain the user's chosen value unless explicitly edited.
    # Missing/unselected evidence cannot be made current by acknowledging it.
    if decision in ('accept', 'edit') and not field['not_selected']:
        field['evidence_changed'] = False
    field.update(state={'accept': 'accepted', 'edit': 'accepted', 'declare': 'accepted', 'reject': 'rejected', 'defer': 'unresolved'}[decision],
                 decision=decision, reason=reason, decision_revision=candidate['revision'])
    result['revision'] = _revision(result)
    return result


def build_review(baseline, candidate):
    """Describe choices and unanswered questions, never drift/repair authority."""
    _validate_document(baseline, 'workstation-baseline')
    _validate_document(candidate, 'workstation-candidate')
    _require(candidate['baseline_revision'] == baseline['revision'])
    required, backlog, comparisons = [], [], []
    for field in candidate['fields']:
        if field['required'] and (field['state'] != 'accepted' or field['support'] == 'unsupported'):
            required.append({'field_id': field['id'], 'reason': 'unsupported_mapping' if field['state'] == 'accepted'
                             else 'required_intent_unresolved'})
        if field['id'].startswith(('custom:', 'tool:', 'note:', 'environment:')):
            purpose = field['value'].get('purpose') if type(field['value']) is dict else None
            backlog.append({'field_id': field['id'], 'value': deepcopy(field['value']), 'purpose': purpose or 'unknown',
                            'decision': field['decision'], 'required': field['required'], 'support': field['support']})
        comparisons.append({'field_id': field['id'], 'state': field['state'],
                            'evidence_changed': field['evidence_changed'], 'not_selected': field['not_selected'],
                            'differs_from_suggestion': field['value'] != field['suggested_value']})
    return _document('workstation-review', baseline_revision=baseline['revision'],
                     candidate_revision=candidate['revision'], required_unresolved=required,
                     customization_backlog=backlog, comparisons=comparisons,
                     conformance='not_evaluated', executable_export_supported=False)


def export_report(document, destination, *, inspected_roots=()):
    """Write a new private combined report. Never overwrite or create parents.

    Caller approves the destination and confines the writer. No mount/bind-mount
    isolation or durability across machine failure is claimed by this helper.
    """
    _keys(document, {'baseline', 'candidate', 'review'})
    expected = build_review(document['baseline'], document['candidate'])
    _require(document['review'] == expected)
    _path(destination)
    _require(type(inspected_roots) in (tuple, list) and len(inspected_roots) <= 128)
    roots = list(inspected_roots) + original_observed_roots(document['baseline'])
    for item in document['baseline']['observations']:
        selected = PurePosixPath(item['evidence']['path'])
        if item['id'].startswith('repository:'):
            roots.extend(item['value'][key] for key in ('git_dir', 'common_dir'))
        roots.append(str(selected.parent if item['evidence']['method'] in
                         ('dist-info-name-version', 'selected-environment-metadata') else selected))
    for root in roots:
        _path(root)
        _require(not PurePosixPath(destination).is_relative_to(root))
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True).encode('utf-8') + b'\n'
    _require(len(payload) <= 8 * 1024 * 1024)
    path = PurePosixPath(destination)
    directory_fd = None
    try:
        directory_fd = _open_directory(str(path.parent))
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError('short write')
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise DiscoveryError('Cannot exclusively write report; destination may contain a partial new file') from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
