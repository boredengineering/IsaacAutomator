#!/usr/bin/env python3
"""Portable, metadata-only inventory. Presence never authorizes execution.

All target I/O is descriptor-relative and no-follow. On platforms without the
required POSIX primitives collection fails closed, rather than weakening safety.
"""
import configparser
import hashlib
import json
import math
import os
import re
from urllib.parse import unquote, urlsplit
import signal
import stat
import threading
import time
from contextlib import contextmanager


def _safe_label(value, maximum=4096):
    return (isinstance(value, str) and 0 < len(value) <= maximum and value.isprintable()
            and re.search(r'(?i)(?:token|password|secret|credential|bearer)[=_:-]|gh[pousr]_|sk-', value) is None)


def _absolute(path):
    if not _safe_label(path) or not os.path.isabs(path):
        raise ValueError('absolute path required')
    if os.path.normpath(path) != path or path.startswith('//'):
        raise ValueError('canonical lexical path required')
    return path


@contextmanager
def _directory(path, readable=False):
    """Pin each ancestor; never resolve a symlink, even in supplied roots."""
    if not hasattr(os, 'O_NOFOLLOW') or os.open not in os.supports_dir_fd:
        raise OSError('secure descriptor operations unavailable')
    walk = getattr(os, 'O_PATH', os.O_RDONLY)
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    fd = os.open('/', flags | walk)
    try:
        parts = path.strip('/').split('/') if path != '/' else []
        for index, part in enumerate(parts):
            mode = os.O_RDONLY if readable and index == len(parts)-1 else walk
            child = os.open(part, flags | mode, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


class _DeadlineExpired(Exception):
    pass


class _Reader:
    def __init__(self, report):
        self.home = report['context']['home']
        self.system_root = report['context']['system_root']
        self.details = report['details']
        self.coverage = report['coverage']
        self.limits = self.coverage['limits']
        self.issue_keys = {(i['code'], i['path']) for i in self.coverage['issues']}
        self.repositories = 0
        self.entries = 0
        self.bytes = 0
        self.deadline = time.monotonic() + self.limits['max_seconds']

    @contextmanager
    def watchdog(self, path):
        self.current_path = path
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.issue('time-limit', path)
            yield False
            return
        if (not hasattr(signal, 'setitimer') or threading.current_thread() is not threading.main_thread()
                or any(signal.getitimer(signal.ITIMER_REAL))):
            self.issue('timeout-unavailable', path)
            yield False
            return
        def expired(signum, frame):
            raise _DeadlineExpired()
        previous = signal.signal(signal.SIGALRM, expired)
        try:
            signal.setitimer(signal.ITIMER_REAL, remaining)
            try:
                yield True
            except _DeadlineExpired:
                self.issue('time-limit', self.current_path)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    def issue(self, code, path):
        if not _safe_label(path):
            code, path = 'unsupported-path-label', self.home
        item = {'code':code, 'path':path}
        if (code, path) not in self.issue_keys:
            if len(self.coverage['issues']) < 19999:
                self.coverage['issues'].append(item)
                self.issue_keys.add((code, path))
            elif len(self.coverage['issues']) == 19999:
                self.coverage['issues'].append({'code': 'issue-limit', 'path': self.home})
                self.issue_keys.add(('issue-limit', self.home))
        self.coverage['complete'] = False

    def ready(self, path):
        if time.monotonic() >= self.deadline:
            self.issue('time-limit', path)
            return False
        return True

    def entry(self, path):
        self.current_path = path
        if not _safe_label(path):
            self.issue('unsupported-path-label', self.home)
            return False
        if not self.ready(path):
            return False
        if self.entries >= self.limits['max_entries']:
            self.issue('entry-limit', path)
            return False
        self.entries += 1
        return True

    def record_link(self, path):
        """Read only the first link inode on a pinned lexical path, never its target."""
        if not self.entry(path):
            return
        if len(self.details['links']) >= 128:
            self.issue('link-limit', self.home)
            return
        parts = path.strip('/').split('/')
        for i in range(len(parts)):
            selected = '/' + '/'.join(parts[:i+1])
            try:
                with _directory(os.path.dirname(selected)) as fd:
                    name = parts[i]
                    before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISLNK(before.st_mode):
                        continue
                    target = None
                    remaining = self.limits['max_bytes'] - self.bytes
                    if 0 < before.st_size <= min(4096, remaining) and self.ready(selected):
                        raw = os.readlink(name, dir_fd=fd)
                        self.bytes += len(os.fsencode(raw))
                        after = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if (before.st_ino, before.st_dev, before.st_mtime_ns, before.st_ctime_ns) == (after.st_ino, after.st_dev, after.st_mtime_ns, after.st_ctime_ns):
                            if _safe_label(raw) and all(p not in ('', '.', '..') for p in raw.lstrip('/').split('/')) and not raw.startswith('//'):
                                target = raw
                    # Ancestors outside the requested home/system scopes are not
                    # new evidence roots; only retain labels at selected scopes.
                    if (selected == path or selected.startswith(self.home.rstrip('/') + '/')
                            or selected.startswith(self.system_root.rstrip('/') + '/')):
                        self.details['links'][selected] = {'target': target, 'status': 'recorded' if target is not None else 'redacted'}
                        self.issue('symlink-skipped', selected)
                    return
            except OSError:
                return

    def directory_exists(self, path):
        if not self.entry(path):
            return False
        try:
            with _directory(path):
                return True
        except FileNotFoundError:
            return False
        except OSError:
            self.record_link(path)
            self.issue('unsafe-or-unreadable-directory', path)
            return False

    def read(self, path, cap=65536, optional=False, metadata_header=False):
        # Only RFC-style METADATA headers admit a prefix. JSON always requires
        # the entire stable file; never parse an arbitrary truncated JSON prefix.
        if metadata_header:
            if os.path.basename(path) != 'METADATA':
                raise ValueError('header reads require METADATA')
            cap = 65536
        if not self.entry(path):
            return None
        remaining = self.limits['max_bytes'] - self.bytes
        if remaining <= 0:
            self.issue('byte-limit', path)
            return None
        try:
            with _directory(os.path.dirname(path)) as parent:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0)
                fd = os.open(os.path.basename(path), flags, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        self.issue('unsafe-file', path)
                        return None
                    budget = min(cap, remaining)
                    if not metadata_header and before.st_size > budget:
                        self.issue('byte-limit' if before.st_size > remaining else 'file-size-limit', path)
                        return None
                    chunks = []
                    count = 0
                    header_done = False
                    line = bytearray()
                    while count < budget:
                        if not self.ready(path):
                            return None
                        # Bytewise headers stop exactly at the delimiter, even
                        # for CRLF, without reading private description bodies.
                        chunk = os.read(fd, 1 if metadata_header else min(8192, budget-count))
                        count += len(chunk)
                        self.bytes += len(chunk)
                        if not chunk:
                            # Actual EOF below the cap is a complete header-only
                            # record; hitting a budget is never equivalent to EOF.
                            if metadata_header:
                                header_done = True
                            break
                        chunks.append(chunk)
                        if metadata_header:
                            line.extend(chunk)
                            if chunk == b'\n':
                                if line in (b'\n', b'\r\n'):
                                    header_done = True
                                    break
                                line.clear()
                    after = os.fstat(fd)
                    current = os.stat(os.path.basename(path), dir_fd=parent, follow_symlinks=False)
                    signature = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                    if signature(before) != signature(after) or signature(after) != signature(current):
                        self.issue('unstable-file', path)
                        return None
                    # After unchanged signatures, a positive ordinary-file size
                    # proves the whole record fits without an extra budget byte.
                    # Virtual proc st_size=0 cannot prove this; header reads still
                    # require their delimiter or an actual EOF below the budget.
                    full_file = not metadata_header and 0 < before.st_size == count
                    if count == budget and not header_done and not full_file:
                        self.issue('byte-limit' if budget == remaining else 'file-size-limit', path)
                        return None
                    if not self.ready(path):
                        return None
                    if metadata_header and not header_done:
                        self.issue('malformed-metadata', path)
                        return None
                    return b''.join(chunks).decode('utf-8', errors='strict')
                finally:
                    os.close(fd)
        except FileNotFoundError:
            if not optional:
                self.issue('missing-file', path)
        except UnicodeError:
            self.issue('malformed-metadata', path)
        except OSError:
            self.record_link(path)
            self.issue('unsafe-or-unreadable-file', path)
        return None

    def directories(self, path, files=False):
        result = []
        if not self.entry(path):
            return result
        try:
            with _directory(path, readable=True) as fd, os.scandir(fd) as entries:
                for item in entries:
                    if not self.entry(path):
                        break
                    if not _safe_label(os.path.join(path, item.name)):
                        self.issue('unsupported-path-label', path)
                        continue
                    if item.is_symlink():
                        self.record_link(os.path.join(path, item.name))
                        self.issue('symlink-skipped', os.path.join(path, item.name))
                    elif (item.is_file(follow_symlinks=False) if files else item.is_dir(follow_symlinks=False)):
                        result.append(item.name)
        except FileNotFoundError:
            self.issue('missing-directory', path)
        except OSError:
            self.record_link(path)
            self.issue('unsafe-or-unreadable-directory', path)
        return sorted(result)


_EXCLUDED = {'assets', 'data', 'datasets', 'logs', 'cache', 'caches', 'node_modules',
             'build', 'dist', 'checkpoints', 'models', 'secrets', 'credentials', '__pycache__'}
_COMMIT = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')
_REF = re.compile(r'refs/(?:heads|tags)/[A-Za-z0-9_./-]{1,200}\Z')


def _repository_url(raw):
    if raw.startswith('git@github.com:'):
        raw = 'ssh://git@github.com/' + raw[len('git@github.com:'):]
    try:
        url = urlsplit(raw)
        if url.scheme not in ('https', 'http', 'ssh', 'git') or url.hostname != 'github.com':
            return None
        if url.port not in (None, 22, 80, 443):
            return None
        parts = url.path.strip('/').split('/')
        if len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}', part) for part in parts):
            return None
        owner, repo = parts
        repo = repo[:-4] if repo.endswith('.git') else repo
        if not repo or repo.endswith('.') or '..' in repo:
            return None
        normalized = 'https://github.com/' + owner + '/' + repo + '.git'
        return normalized if _safe_label(normalized, 512) else None
    except ValueError:
        return None


def _repository(reader, path):
    git = os.path.join(path, '.git')
    head = reader.read(os.path.join(git, 'HEAD'))
    config = reader.read(os.path.join(git, 'config'))
    repository = None
    if config is not None:
        parser = configparser.ConfigParser(interpolation=None, strict=True, default_section='\x00')
        try:
            parser.read_string(config)
            repository = _repository_url(parser.get('remote "origin"', 'url', fallback=''))
        except configparser.Error:
            reader.issue('malformed-metadata', os.path.join(git, 'config'))
    if repository is None:
        reader.issue('unrecognized-repository', path)
    ref = commit = None
    if head:
        head = head.strip()
        if _COMMIT.fullmatch(head):
            commit = head.lower()
        elif (head.startswith('ref: ') and _REF.fullmatch(head[5:]) and _safe_label(head[5:], 256)
              and all(p not in ('', '.', '..') for p in head[5:].split('/'))):
            ref = head[5:]
            text = reader.read(os.path.join(git, ref))
            if text and _COMMIT.fullmatch(text.strip()):
                commit = text.strip().lower()
            else:
                reader.issue('unresolved-ref', os.path.join(git, ref))
        else:
            reader.issue('malformed-metadata', os.path.join(git, 'HEAD'))
    slug = repository.rsplit('/', 1)[-1][:-4].casefold() if repository else ''
    component = {'isaaclab':'lab', 'isaaclab-arena':'arena', 'isaac-gr00t':'gr00t', 'lerobot':'lerobot'}.get(slug)
    reader.details['repositories'][path] = {'head': os.path.join(git, 'HEAD'),
        'config': os.path.join(git, 'config'), 'ref': os.path.join(git, ref) if ref else None}
    return {'path':path, 'component':component, 'repository':repository,
            'ref':ref, 'commit':commit, 'dirty':'unknown'}


def _workspace_repositories(reader, path, depth=0):
    if depth > reader.limits['max_depth']:
        reader.issue('depth-limit', path)
        return []
    # Probe the fixed metadata directory before enumerating repository payloads.
    # Large asset/source trees must not spend the budget needed to read HEAD.
    git = os.path.join(path, '.git')
    if reader.directory_exists(git):
        if reader.repositories >= 128:
            reader.issue('repository-limit', path)
            return []
        reader.repositories += 1
        return [_repository(reader, path)]
    if reader.read(git, optional=True) is not None:
        reader.issue('unsupported-worktree', git)
        return []
    result = []
    names = reader.directories(path)
    for name in names:
        if name.startswith('.') or name.casefold() in _EXCLUDED:
            continue
        if not reader.ready(path):
            break
        result.extend(_workspace_repositories(reader, os.path.join(path, name), depth+1))
    return result


def _safe_text(value):
    return value if _safe_label(value, 256) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._()+,/:~-]{0,255}', value) else None


def _machine(reader, root):
    result = {}
    def source(relative):
        return os.path.join(root, relative)
    def fact(key, value, relative):
        if isinstance(value, str) and not _safe_label(value, 512):
            value = None
        if value is None:
            reader.issue('unavailable-fact', source(relative))
        result[key] = {'value':value, 'source':source(relative)}
    relative = 'etc/os-release'
    text = reader.read(source(relative))
    if text is None:
        # Independently admitted fixed record, never the symlink's target.
        relative = 'usr/lib/os-release'
        text = reader.read(source(relative))
    fields = {}
    for line in (text or '').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in ('PRETTY_NAME', 'ID', 'VERSION_ID'):
                if key in fields:
                    fields[key] = None
                    reader.issue('malformed-metadata', source(relative))
                else:
                    fields[key] = _safe_text(value.strip().strip('\"\''))
    for key, field in (('os','PRETTY_NAME'), ('os_id','ID'), ('os_version','VERSION_ID')):
        fact(key, fields.get(field), relative)
    relative = 'proc/sys/kernel/osrelease'
    fact('kernel', _safe_text((reader.read(source(relative)) or '').strip()), relative)
    relative = 'proc/cpuinfo'
    text = reader.read(source(relative), cap=1048576)
    models = []
    for line in (text or '').splitlines():
        if ':' in line and line.split(':', 1)[0].strip() in ('model name', 'Hardware'):
            model = _safe_text(line.split(':', 1)[1].strip())
            if model and model not in models:
                if len(models) >= 32:
                    reader.issue('fact-limit', source(relative))
                    break
                models.append(model)
    fact('cpu', (models[0] if len(models) == 1 else models) if models else None, relative)
    relative = 'proc/meminfo'
    text = reader.read(source(relative))
    match = re.search(r'^MemTotal:\s*([0-9]{1,15}) kB\s*$', text or '', re.M)
    fact('memory', int(match[1])*1024 if match else None, relative)
    relative = 'proc/driver/nvidia/version'
    text = reader.read(source(relative))
    match = re.search(r'Kernel Module\s+([0-9]+(?:\.[0-9]+){1,3})\b', text or '')
    fact('driver', match[1] if match else None, relative)
    fact('gpu', None, relative)
    reader.issue('gpu-probe-not-enabled', source(relative))
    reader.issue('driver-cuda-level-not-collected', source(relative))
    relative = 'usr/local/cuda/version.json'
    text = reader.read(source(relative))
    version = None
    if text:
        try:
            value = json.loads(text)
            version = value.get('cuda', {}).get('version')
            if not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', version):
                version = None
        except (ValueError, AttributeError, RecursionError):
            reader.issue('malformed-metadata', source(relative))
    fact('cuda_toolkit', version, relative)
    relative = 'run/systemd/container'
    text = (reader.read(source(relative), optional=True) or '').strip()
    fact('container', text if text in ('docker','podman','lxc','lxc-libvirt','systemd-nspawn','rkt','wsl','proot') else None, relative)
    return result


def _records(reader, path):
    text = reader.read(path, cap=8388608)
    if text is None:
        return
    if text and not text.endswith('\n\n'):
        reader.issue('truncated-database', path)
        text = text[:text.rfind('\n\n')+2] if '\n\n' in text else ''
    selected = {'Package', 'Architecture', 'Version', 'Status', 'Auto-Installed'}
    for block in text.split('\n\n'):
        if not block.strip():
            continue
        if not reader.entry(path):
            break
        fields = {}
        valid = True
        for line in block.splitlines():
            if line.startswith((' ', '\t')):
                continue
            if ':' not in line:
                valid = False
                continue
            key, value = line.split(':', 1)
            if key in selected:
                if key in fields:
                    valid = False
                fields[key] = value.strip()
        if valid:
            yield fields
        else:
            reader.issue('malformed-metadata', path)


def _packages(reader, root):
    apt_path = os.path.join(root, 'var/lib/apt/extended_states')
    manual = {}
    for record in _records(reader, apt_path):
        key = (record.get('Package'), record.get('Architecture'))
        flag = record.get('Auto-Installed')
        if flag not in ('0', '1') or not all(key) or key in manual:
            reader.issue('ambiguous-manual-state', apt_path)
            manual[key] = None
        else:
            manual[key] = flag == '0'
    result = {}
    statuses = {}
    path = os.path.join(root, 'var/lib/dpkg/status')
    reader.issue('unsupported-package-managers', root)
    for record in _records(reader, path):
        if record.get('Status') not in ('install ok installed', 'hold ok installed'):
            continue
        name, arch, version = record.get('Package', ''), record.get('Architecture', ''), record.get('Version', '')
        if not (all(_safe_label(v, 128) for v in (name, arch, version)) and
                re.fullmatch(r'[a-z0-9][a-z0-9+.-]{0,127}', name) and
                re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', arch) and
                re.fullmatch(r'[0-9][A-Za-z0-9.+:~_-]{0,127}', version)):
            reader.issue('malformed-metadata', path)
            continue
        key = (name, arch)
        if len(result) >= 20000 and key not in result:
            reader.issue('package-limit', path)
            break
        if key in result:
            result[key] = None
            reader.issue('conflicting-package', path)
            continue
        flag = manual.get(key)
        if flag is None:
            reader.issue('unknown-manual-state', apt_path)
        result[key] = {'name':name, 'version':version, 'architecture':arch, 'manual':flag}
        statuses[name + ':' + arch] = record['Status']
    packages = [result[key] for key in sorted(result) if result[key] is not None]
    reader.details['system_packages']['status'] = {p['name'] + ':' + p['architecture']: statuses[p['name'] + ':' + p['architecture']] for p in packages}
    return packages


_CONDA_SEEDS = ('miniconda3', 'anaconda3', 'miniforge3', 'mambaforge')


def _package_pair(name, version, conda=False):
    pattern = r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}' if conda else r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}'
    if (_safe_label(name, 128) and re.fullmatch(pattern, name)
            and _safe_label(version, 128) and re.fullmatch(r'[0-9][A-Za-z0-9.!+_~-]{0,127}', version)):
        return {'name':name, 'version':version}
    return None


def _unique_packages(reader, path, packages):
    by_name = {}
    for package in packages:
        name = package['name']
        if len(by_name) >= 20000 and name not in by_name:
            reader.issue('package-limit', path)
            break
        if name in by_name and by_name[name] != package:
            by_name[name] = None
            reader.issue('conflicting-environment-package', path)
        elif name not in by_name:
            by_name[name] = package
    return [by_name[name] for name in sorted(by_name) if by_name[name] is not None]


def _environment(reader, path):
    name = 'venv' if os.path.basename(path) == '.venv' else os.path.basename(path)
    if not _safe_label(name, 128) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', name):
        reader.issue('unsafe-environment-name', path)
        return None
    meta = os.path.join(path, 'conda-meta')
    if not reader.directory_exists(meta):
        return _venv(reader, path, name)
    packages = []
    sources = {}
    if reader.limits['max_depth'] < 1:
        reader.issue('depth-limit', meta)
    else:
        # Exact Python metadata first, then version/build filenames, not every
        # python-prefixed package (for example python-dateutil or python-2fa).
        filenames = reader.directories(meta, files=True)
        filenames.sort(key=lambda n: (n != 'python.json',
            re.fullmatch(r'python-[0-9]+(?:\.[0-9]+)+(?:-[A-Za-z0-9_.-]+)?\.json', n) is None, n))
        for filename in filenames:
            if not filename.endswith('.json') or filename.startswith('.'):
                continue
            source = os.path.join(meta, filename)
            text = reader.read(source, cap=1048576)
            if text is None:
                continue
            try:
                value = json.loads(text)
                pair = _package_pair(value.get('name'), value.get('version'), conda=True)
                if pair:
                    packages.append(pair)
                    sources.setdefault(pair['name'], source)
                else:
                    reader.issue('malformed-metadata', source)
            except (ValueError, AttributeError, RecursionError):
                reader.issue('malformed-metadata', source)
    packages = _unique_packages(reader, path, packages)
    versions = {p['version'] for p in packages if p['name'] == 'python'}
    python = next(iter(versions)) if len(versions) == 1 else None
    if python is not None and (len(python) > 32 or not re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', python)):
        reader.issue('unsupported-python-version', meta)
        python = None
    reader.details['environments'][path] = {'python': sources.get('python') if python else None,
        'packages': {p['name']: sources[p['name']] for p in packages}}
    return {'path':path, 'name':name, 'manager':'conda', 'python':python, 'packages':packages}


def _venv(reader, path, name):
    source = os.path.join(path, 'pyvenv.cfg')
    text = reader.read(source, optional=True)
    if text is None:
        if os.path.basename(path) == '.venv':
            reader.issue('unknown-environment', path)
            reader.details['environments'][path] = {'python': None, 'packages': {}}
            return {'path':path, 'name':name, 'manager':'unknown', 'python':None, 'packages':[]}
        return None
    versions = []
    for line in text.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key.strip() in ('version', 'version_info'):
                value = value.strip()
                if len(value) <= 32 and re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', value):
                    versions.append(value)
    python = versions[0] if len(set(versions)) == 1 else None
    if python is None:
        reader.issue('malformed-metadata', source)
    python_source = source
    packages = []
    sources = {}
    lib = os.path.join(path, 'lib')
    if reader.limits['max_depth'] < 4:
        reader.issue('depth-limit', lib)
    elif reader.directory_exists(lib):
        for version in reader.directories(lib):
            if not re.fullmatch(r'python[0-9]+\.[0-9]+', version):
                continue
            site = os.path.join(lib, version, 'site-packages')
            if not reader.directory_exists(site):
                continue
            for filename in reader.directories(site):
                if not filename.endswith('.dist-info') or filename.startswith('.'):
                    continue
                source = os.path.join(site, filename, 'METADATA')
                text = reader.read(source, metadata_header=True)
                if text is None:
                    continue
                fields = {}
                previous = None
                valid = True
                for line in text.splitlines():
                    if not line:
                        break
                    if line.startswith((' ', '\t')):
                        if previous in ('name', 'version'):
                            valid = False
                        continue
                    if ':' not in line:
                        valid = False
                        continue
                    key, value = line.split(':', 1)
                    previous = key.lower()
                    if previous in ('name', 'version'):
                        if previous in fields:
                            valid = False
                        fields[previous] = value.strip()
                pair = _package_pair(fields.get('name'), fields.get('version')) if valid else None
                if pair:
                    packages.append(pair)
                    sources.setdefault(pair['name'], source)
                else:
                    reader.issue('malformed-metadata', source)
    if 'editable' not in reader.details:
        reader.issue('unsupported-editable-metadata', path)
    packages = _unique_packages(reader, path, packages)
    reader.details['environments'][path] = {'python': python_source,
        'packages': {p['name']: sources[p['name']] for p in packages}}
    return {'path':path, 'name':name, 'manager':'venv', 'python':python, 'packages':packages}


def _environments(reader, home, report):
    candidates = []
    workspaces = report['workspace']['candidates']
    for base in workspaces + [repo['path'] for repo in report['repositories']]:
        env = os.path.join(base, '.venv')
        if reader.directory_exists(env):
            candidates.append(env)
    for seed in _CONDA_SEEDS:
        base = os.path.join(home, seed)
        if reader.directory_exists(base):
            candidates.append(base)
            envs = os.path.join(base, 'envs')
            if reader.directory_exists(envs):
                candidates.extend(os.path.join(envs, name) for name in reader.directories(envs))
    envs = os.path.join(home, '.conda', 'envs')
    if reader.directory_exists(envs):
        candidates.extend(os.path.join(envs, name) for name in reader.directories(envs))
    result = []
    for path in sorted(set(candidates)):
        if not reader.ready(path):
            break
        if len(result) >= 32:
            reader.issue('environment-limit', path)
            break
        env = _environment(reader, path)
        if env:
            result.append(env)
    return result


def _local_evidence_path(value, absolute=True):
    """Sanitize lexical labels only. Never resolve, stat or follow this value."""
    if not _safe_label(value, 4096) or re.fullmatch(r'[A-Za-z0-9_./ -]+', value) is None:
        return None
    if value.startswith('//') or (absolute and not value.startswith('/')):
        return None
    if any(p in ('', '.', '..') for p in value.lstrip('/').split('/')):
        return None
    return value


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _direct_url_record(source, text):
    record = {'source': source, 'kind': 'direct-url', 'line': None,
              'editable': None, 'local_path': None, 'status': 'unknown'}
    if text is None:
        return record
    try:
        value = json.loads(text, object_pairs_hook=_unique_json_pairs)
        flag = value.get('dir_info', {}).get('editable')
        raw = value.get('url')
        if type(flag) is not bool or not isinstance(raw, str):
            return record
        record['editable'] = flag
        # Parse only after rejecting control characters; urlsplit strips some.
        if not raw.isprintable():
            record['status'] = 'redacted'
            return record
        url = urlsplit(raw)
        if url.scheme != 'file' or url.netloc not in ('', 'localhost'):
            record['status'] = 'nonlocal'
        elif url.query or url.fragment:
            record['status'] = 'redacted'
        else:
            record['local_path'] = _local_evidence_path(unquote(url.path, errors='strict'))
            record['status'] = 'local' if record['local_path'] is not None else 'redacted'
    except (ValueError, AttributeError, RecursionError, UnicodeError):
        pass
    return record


def _pth_record(source, line, value):
    record = {'source': source, 'kind': 'pth', 'line': line,
              'editable': None, 'local_path': None, 'status': 'unknown'}
    if value is None:
        return record
    if value.startswith(('import ', 'import\t')):
        record['status'] = 'executable'
    elif '://' in value:
        record['status'] = 'nonlocal'
    else:
        record['local_path'] = _local_evidence_path(value, absolute=False)
        record['status'] = 'local' if record['local_path'] is not None else 'redacted'
    return record


def _editable(reader, env):
    """Read selected source records in either manager, not source targets."""
    base = env['path']
    evidence = {'status': 'unknown', 'records': []}
    reader.details['editable']['environments'][base] = evidence
    initial = set(reader.issue_keys)
    def append(record):
        records = reader.details['editable']['environments'].values()
        if sum(len(e['records']) for e in records) >= 128:
            reader.issue('editable-limit', base)
            return False
        evidence['records'].append(record)
        if record['status'] != 'local':
            reader.issue('unresolved-editable-metadata', record['source'])
        return True
    lib = os.path.join(base, 'lib')
    if env['manager'] == 'unknown' or reader.limits['max_depth'] < 4:
        reader.issue('editable-metadata-unavailable', base)
        return
    if not reader.directory_exists(lib):
        reader.issue('editable-metadata-unavailable', base)
        return
    sites = 0
    for version in reader.directories(lib):
        if not re.fullmatch(r'python[0-9]+\.[0-9]+', version):
            continue
        site = os.path.join(lib, version, 'site-packages')
        if not reader.directory_exists(site):
            continue
        sites += 1
        for filename in reader.directories(site):
            if not filename.endswith('.dist-info') or filename.startswith('.'):
                continue
            source = os.path.join(site, filename, 'direct_url.json')
            before = set(reader.issue_keys)
            text = reader.read(source, optional=True)
            # Missing optional direct_url is not evidence of an editable install.
            if text is None and before == reader.issue_keys:
                continue
            if not append(_direct_url_record(source, text)):
                return
        for filename in reader.directories(site, files=True):
            if not filename.endswith('.pth') or filename.startswith('.'):
                continue
            source = os.path.join(site, filename)
            text = reader.read(source)
            if text is None:
                if not append(_pth_record(source, None, None)):
                    return
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if not reader.entry(source):
                    return
                value = line.strip()
                if not value or value.startswith('#'):
                    continue
                if not append(_pth_record(source, number, value)):
                    return
    if not sites:
        reader.issue('editable-metadata-unavailable', base)
    # Earlier venv/package discovery may already have reported the same unsafe
    # site ancestor. Deduplicated issues still invalidate this scan's coverage.
    blocked = any(p == lib or p.startswith(lib + '/') or
                  (lib.startswith(p.rstrip('/') + '/') and code in
                   ('symlink-skipped', 'unsafe-or-unreadable-directory', 'unsupported-path-label',
                    'entry-limit', 'byte-limit', 'time-limit', 'depth-limit'))
                  for code, p in reader.issue_keys)
    if sites and not blocked and initial == reader.issue_keys and reader.ready(base):
        evidence['status'] = 'observed'


def _package_groups(packages):
    """Deterministic heuristic review hints, not native consumer/install intent.

    Members are name:architecture identities into packages and system_packages
    source/status evidence. No array position or manual flag implies necessity.
    """
    groups = {k: [] for k in ('os-baseline', 'drivers-cuda', 'build-tools', 'optional-applications', 'uncertain')}
    for p in packages:
        name = p['name']
        if name.startswith(('nvidia-', 'libnvidia-', 'cuda-', 'libcuda', 'libcudnn', 'cudnn-')):
            group = 'drivers-cuda'
        elif name in ('build-essential', 'cmake', 'make', 'ninja-build', 'git', 'pkg-config', 'gcc', 'g++') or name.startswith(('gcc-', 'g++-')):
            group = 'build-tools'
        elif name in ('bash', 'coreutils', 'libc6', 'systemd', 'apt', 'dpkg') or name.startswith('linux-image-'):
            group = 'os-baseline'
        elif name in ('firefox', 'chromium', 'blender', 'vlc', 'code'):
            group = 'optional-applications'
        else:
            group = 'uncertain'
        groups[group].append(name + ':' + p['architecture'])
    return {'basis': 'name-heuristic-review-only', 'groups': {k: sorted(v) for k, v in groups.items()}}


def _followups(report):
    """Named next-batch proposals only. Do not inspect these descriptors/targets."""
    result = {}
    def add(kind, path, records, target=None):
        key = hashlib.sha256((kind + '\0' + path).encode()).hexdigest()[:24]
        result[key] = {'kind': kind, 'path': path, 'target': target,
            'records': records, 'action': 'request-explicit-scope'}
    if report['workspace']['selected'] is None:
        add('workspace', report['workspace']['parent'],
            [report['workspace']['requested_name']] if 'requested_name' in report['workspace']
            else ['BoredEngineer', 'boredengineering'])
    if not report['isaacsim'] or any(s['version'] is None for s in report['isaacsim']):
        add('isaacsim', report['context']['home'] + '/IsaacSim', ['VERSION'])
    unresolved_refs = set()
    for repo in report['repositories']:
        if repo['repository'] is None or repo['commit'] is None:
            add('repository-metadata', repo['path'], ['.git/HEAD', '.git/config'])
        if repo['ref'] and repo['commit'] is None:
            unresolved_refs.add(repo['path'] + '/.git/' + repo['ref'])
    for issue in report['coverage']['issues']:
        code, path = issue['code'], issue['path']
        if (code == 'unsupported-worktree' and path.endswith('/.git') and
                any(path.startswith(c + '/') for c in report['workspace']['candidates'])):
            add('git-worktree', path, ['HEAD', 'config'])
        elif code == 'unresolved-ref' and path in unresolved_refs:
            add('repository-ref', path, ['loose-ref', 'packed-refs'])
    for path, link in report['details']['links'].items():
        add('linked-path', path, ['link-target-scope'], link['target'])
    for path in sorted({e['path'] for e in report['environments']} | {r['path'] for r in report['repositories']}):
        add('environment-descriptors', path, ['pyproject.toml', 'uv.lock', 'environment.yml'])
    for env in report['environments']:
        evidence = report['details'].get('editable', {}).get('environments', {}).get(env['path'])
        if evidence is None or evidence['status'] == 'unknown':
            add('editable-metadata', env['path'], ['direct_url.json', '*.pth'])
    return dict(sorted(result.items()))


def _finish(report, reader):
    """Bound portable data and repair only truncation seams, without more I/O.

    A 1 MiB raw budget reserves room for the existing CLI baseline/candidate/
    review envelope. Recompute identity maps after every truncation; selected
    metadata from an interrupted enclosing record must never become proof.
    """
    d = report['details']
    issues = report['coverage']['issues']
    def gap(code):
        item = {'code': code, 'path': reader.home}
        if item not in issues:
            issues.insert(0, item)
        report['coverage']['complete'] = False
    for section, limit, code in (('repositories', 128, 'repository-limit'), ('environments', 32, 'environment-limit'),
                                  ('isaacsim', 16, 'isaacsim-limit'), ('packages', 20000, 'package-limit')):
        if len(report[section]) > limit:
            del report[section][limit:]
            gap(code)
    for env in report['environments']:
        if len(env['packages']) > 20000:
            del env['packages'][20000:]
            gap('package-limit')
    if len(issues) > 19999:
        del issues[19998:]
        gap('issue-limit')
    def normalize():
        for section in ('repositories', 'environments', 'isaacsim'):
            retained = [r for r in report[section] if r['path'] in d[section]]
            if len(retained) != len(report[section]):
                gap('interrupted-record')
            report[section] = retained
            d[section] = {r['path']: d[section][r['path']] for r in retained}
        selected_venvs = {p + '/.venv' for p in report['workspace']['candidates']}
        selected_venvs.update(r['path'] + '/.venv' for r in report['repositories'])
        retained_envs = [e for e in report['environments'] if not e['path'].endswith('/.venv') or e['path'] in selected_venvs]
        if len(retained_envs) != len(report['environments']):
            gap('environment-scope-truncated')
        report['environments'] = retained_envs
        d['environments'] = {e['path']: d['environments'][e['path']] for e in retained_envs}
        if 'editable' in d:
            editable = d['editable']['environments']
            d['editable']['environments'] = {e['path']: editable.get(e['path'],
                {'status': 'unknown', 'records': []}) for e in retained_envs}
        statuses = d['system_packages']['status']
        report['packages'] = [p for p in report['packages'] if p['name'] + ':' + p['architecture'] in statuses]
        d['system_packages']['status'] = {p['name'] + ':' + p['architecture']: statuses[p['name'] + ':' + p['architecture']] for p in report['packages']}
        for env in report['environments']:
            evidence = d['environments'][env['path']]
            env['packages'] = [p for p in env['packages'] if p['name'] in evidence['packages']]
            evidence['packages'] = {p['name']: evidence['packages'][p['name']] for p in env['packages']}
            if env['manager'] == 'conda' and 'python' not in evidence['packages']:
                env['python'] = evidence['python'] = None
        kept_links = {i['path'] for i in issues if i['code'] == 'symlink-skipped'}
        d['links'] = {p: v for p, v in d['links'].items() if p in kept_links}
        proposals = _followups(report)
        if len(proposals) > 128:
            gap('followup-limit')
        d['followups'] = dict(list(proposals.items())[:128])
        d['package_groups'] = _package_groups(report['packages'])
    normalize()
    size = len(json.dumps(report, allow_nan=False).encode('utf-8'))
    while size > 1024 * 1024:
        gap('report-size-limit')
        # Halve the largest variable section. Fixed context/scalars are bounded;
        # limit markers are retained even when ordinary issues must be removed.
        ordinary = [i for i in issues if not i['code'].endswith('-limit')]
        choices = [(len(json.dumps(report[k])), k) for k in ('packages', 'environments', 'repositories')]
        choices.append((len(json.dumps(ordinary)), 'issues'))
        if 'editable' in d and any(e['records'] for e in d['editable']['environments'].values()):
            choices.append((len(json.dumps(d['editable'])), 'editable'))
        _, section = max(choices)
        if section == 'editable':
            for evidence in d['editable']['environments'].values():
                del evidence['records'][len(evidence['records'])//2:]
                evidence['status'] = 'unknown'
        elif section == 'issues' and ordinary:
            keep = ordinary[:len(ordinary)//2]
            issues[:] = [i for i in issues if i['code'].endswith('-limit')] + keep
        elif report.get(section):
            del report[section][len(report[section])//2:]
        normalize()
        reduced_size = len(json.dumps(report, allow_nan=False).encode('utf-8'))
        if reduced_size >= size:
            # Long limit labels or regenerated details can defeat truncation.
            # Require progress even though finalization runs after the watchdog.
            issues[:] = [{'code': 'report-size-limit', 'path': reader.home}]
            d['links'] = {}
            normalize()
            reduced_size = len(json.dumps(report, allow_nan=False).encode('utf-8'))
            if reduced_size >= size:
                raise ValueError('Unable to bound host inventory report.')
        size = reduced_size


def _validate_workspace_name(name):
    if name is not None and (not _safe_label(name, 128) or
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name) is None):
        raise ValueError('safe exact workspace child required')


def _validate_limits(limits):
    for key, cap in (('max_entries', 100000), ('max_bytes', 67108864), ('max_depth', 16)):
        if type(limits[key]) is not int or not 0 < limits[key] <= cap:
            raise ValueError('positive capped integer limit required')
    max_seconds = limits['max_seconds']
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 120:
        raise ValueError('finite positive time limit up to 120 seconds required')


def collect(home: str, system_root: str, *, max_entries=4096, max_bytes=8388608,
            max_seconds=10.0, max_depth=4, scope='all', workspace_name=None, include_editable=False):
    home, system_root = _absolute(home), _absolute(system_root)
    if scope not in ('all', 'software'):
        raise ValueError('unsupported collection scope')
    _validate_workspace_name(workspace_name)
    if type(include_editable) is not bool:
        raise ValueError('boolean editable opt-in required')
    limits = dict(max_entries=max_entries, max_bytes=max_bytes,
                  max_seconds=max_seconds, max_depth=max_depth)
    _validate_limits(limits)
    parent = os.path.join(home, 'Documents', 'GitHub')
    report = {
        'schema_version': 1, 'kind': 'host-inventory',
        'context': {'home':home, 'system_root':system_root,
                    'identity':'fixture' if system_root != '/' else 'user-supplied-host',
                    'execution_authorized':False},
        'workspace': {'parent':parent, 'candidates':[], 'selected':None},
        'repositories':[], 'isaacsim':[], 'machine':{}, 'packages':[], 'environments':[],
        'coverage': {'complete':True, 'issues':[], 'limits':limits},
        'details': {'version': 1, 'repositories': {}, 'isaacsim': {}, 'environments': {},
            'links': {}, 'followups': {},
            'system_packages': {'status_source': os.path.join(system_root, 'var/lib/dpkg/status'),
                'manual_source': os.path.join(system_root, 'var/lib/apt/extended_states'), 'status': {}}},
    }
    if workspace_name is not None:
        report['workspace']['requested_name'] = workspace_name
    if include_editable:
        report['details']['editable'] = {'version': 1, 'environments': {}}
    reader = _Reader(report)
    if scope == 'software':
        reader.issue('system-scope-not-collected', system_root)
    with reader.watchdog(home) as active:
        if active:
            if workspace_name is not None:
                candidate = os.path.join(parent, workspace_name)
                candidates = [candidate] if reader.directory_exists(candidate) else []
            else:
                candidates = [os.path.join(parent, name) for name in reader.directories(parent)
                              if name.casefold() in ('boredengineer', 'boredengineering')]
            if len(candidates) > 128:
                reader.issue('workspace-limit', parent)
                candidates = candidates[:128]
            report['workspace']['candidates'] = candidates
            enumeration_incomplete = any(item['path'] == parent and item['code'] in
                                         ('entry-limit', 'time-limit', 'unsafe-or-unreadable-directory', 'missing-directory')
                                         for item in report['coverage']['issues'])
            if len(candidates) == 1 and not enumeration_incomplete:
                report['workspace']['selected'] = candidates[0]
            else:
                reader.issue('ambiguous-workspace' if candidates else 'missing-workspace', parent)
            # Observing candidates does not choose the desired workspace. Keep
            # ambiguous roots separate, with one shared collection budget.
            for candidate in candidates:
                report['repositories'].extend(_workspace_repositories(reader, candidate))
            sim = os.path.join(home, 'IsaacSim')
            if reader.directory_exists(sim):
                source = os.path.join(sim, 'VERSION')
                text = reader.read(source)
                version = text.strip() if text and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)?(?:\+[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)?', text.strip()) else None
                if version is not None and (len(version) > 64 or not _safe_label(version)):
                    version = None
                if text is not None and version is None:
                    reader.issue('malformed-metadata', source)
                report['isaacsim'].append({'path':sim, 'version':version})
                reader.details['isaacsim'][sim] = {'version': source}
            else:
                reader.issue('missing-isaacsim', sim)
            if scope == 'all':
                report['machine'] = _machine(reader, system_root)
                report['packages'] = _packages(reader, system_root)
            report['environments'] = _environments(reader, home, report)
            if include_editable:
                for env in report['environments']:
                    _editable(reader, env)
            reader.issue('unsupported-software-inventory', home)
    _finish(report, reader)
    return report


def _streams_safe():
    try:
        return all(stat.S_ISFIFO(os.fstat(fd).st_mode) or os.isatty(fd) for fd in (1, 2))
    except OSError:
        return False


def main(argv=None):
    # Before argparse/help/errors: never write diagnostics to redirected files.
    if not _streams_safe():
        return 2
    import argparse
    import sys
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        print('Refusing root or unsupported execution identity.', file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--collect', action='store_true')
    parser.add_argument('--home', default=os.path.expanduser('~'))
    parser.add_argument('--system-root', default='/')
    parser.add_argument('--scope', choices=('all', 'software'), default='all',
                        help='software skips machine and system-package reads')
    parser.add_argument('--workspace-name', help='scan only this exact workspace child; siblings are unobserved')
    parser.add_argument('--include-editable', action='store_true', help='read local editable source evidence; never follow targets')
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-entries', type=int, default=4096)
    parser.add_argument('--max-bytes', type=int, default=8388608)
    parser.add_argument('--max-seconds', type=float, default=10.0)
    parser.add_argument('--max-depth', type=int, default=4)
    args = parser.parse_args(argv)
    try:
        home, root, output = _absolute(args.home), _absolute(args.system_root), _absolute(args.output)
        limits = {'max_entries':args.max_entries, 'max_bytes':args.max_bytes,
                  'max_seconds':args.max_seconds, 'max_depth':args.max_depth}
        _validate_limits(limits)
        _validate_workspace_name(args.workspace_name)
        if not args.collect:
            plan = {'schema_version':1, 'kind':'host-inventory-plan',
                    'execution_authorized':False, 'home':home, 'system_root':root,
                    'identity':'fixture' if root != '/' else 'user-supplied-host',
                    'output':output, 'seeds':[os.path.join(home,'Documents','GitHub','BoredEngineer'),
                        os.path.join(home,'IsaacSim')] + [os.path.join(home,s) for s in _CONDA_SEEDS] + [os.path.join(home,'.conda','envs')],
                    'limits':limits, 'scope':args.scope,
                    'fields':['repository HEAD/config/ref', 'IsaacSim VERSION', 'fixed machine records',
                              'dpkg/APT records', 'conda-meta', 'pyvenv.cfg/dist-info'],
                    'system_records':[os.path.join(root, relative) for relative in (
                        'etc/os-release', 'usr/lib/os-release', 'proc/sys/kernel/osrelease',
                        'proc/cpuinfo', 'proc/meminfo', 'proc/driver/nvidia/version',
                        'usr/local/cuda/version.json', 'run/systemd/container',
                        'var/lib/dpkg/status', 'var/lib/apt/extended_states')],
                    'workspace_names':['BoredEngineer', 'boredengineering'],
                    'home_metadata':['.git/HEAD', '.git/config', '.git/refs/heads/*', '.git/refs/tags/*',
                        '.git (worktree marker only; target never followed)', 'IsaacSim/VERSION',
                        'conda-meta/*.json', '.venv/pyvenv.cfg', 'lib/python*/site-packages/*.dist-info/METADATA'],
                    'excluded':['credentials','shell history','.env','assets','caches','runtime imports','probes',
                        'Git commands', 'package-manager commands', 'network', 'worktree targets',
                        'direct_url.json', '*.pth', 'Conda history', 'launchers', 'settings changes'],
                    'effects':'Plan reads no target roots; explicit collection reads metadata and creates one private report; access times may change.'}
            if args.workspace_name is not None:
                plan['workspace_names'] = [args.workspace_name]
                plan['seeds'][0] = os.path.join(home, 'Documents', 'GitHub', args.workspace_name)
                plan['workspace_scope'] = 'exact-child; siblings unobserved'
            plan['include_editable'] = args.include_editable
            if args.include_editable:
                plan['excluded'] = [p for p in plan['excluded'] if p not in ('direct_url.json', '*.pth')]
                plan['excluded'].extend(['editable targets', 'executable .pth code'])
                plan['home_metadata'].extend(['lib/python*/site-packages/*.dist-info/direct_url.json',
                    'lib/python*/site-packages/*.pth (text evidence only)'])
                plan['editable_limits'] = {'max_records': 128, 'max_file_bytes': 65536,
                    'shared_entry_byte_time_budget': True}
            if args.scope == 'software':
                plan['system_records'] = []
                plan['fields'] = ['repository HEAD/config/ref', 'IsaacSim VERSION',
                                  'conda-meta', 'pyvenv.cfg/dist-info']
            print(json.dumps(plan, sort_keys=True, allow_nan=False))
            return 0
        excluded = [os.path.join(home, item) for item in ('Documents/GitHub', 'IsaacSim', '.conda', *_CONDA_SEEDS)]
        excluded += [root] if root != '/' else ['/etc', '/proc', '/var/lib/dpkg', '/var/lib/apt', '/usr/local/cuda', '/run/systemd']
        if any(os.path.commonpath([output, tree]) == tree for tree in excluded):
            raise ValueError('output overlaps observed tree')
        with _directory(os.path.dirname(output)) as parent:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
            fd = os.open(os.path.basename(output), flags, 0o600, dir_fd=parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                os.fchmod(stream.fileno(), 0o600)
                report = collect(home, root, scope=args.scope, workspace_name=args.workspace_name,
                                 include_editable=args.include_editable, **limits)
                json.dump(report, stream, sort_keys=True, allow_nan=False)
                stream.write('\n')
        print('Private host inventory written; coverage gaps remain evidence, not authority.')
        return 0
    except (ValueError, OSError):
        print('Collection refused: invalid input or unsafe/unavailable destination.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
