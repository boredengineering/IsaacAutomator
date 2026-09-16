"""New-resource offline builders. Never execute repository code or fetch URLs.

Only synthetic owned sources within the executor's explicit root are admitted.
The caller owns locking, journal, approval, new-name publication and containment.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


class BuilderError(ValueError):
    pass


def tree_digest(fd, *, reject_symlinks=False):
    """Bounded no-follow content/metadata fingerprint; includes untracked files."""
    rows = []
    budget = [0, 0]

    def visit(directory, prefix, depth):
        if depth > 32:
            raise BuilderError('tree depth limit exceeded')
        directory_before = os.fstat(directory)
        for name in sorted(os.listdir(directory)):
            budget[0] += 1
            if budget[0] > 4096:
                raise BuilderError('tree count limit exceeded')
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if info.st_uid != os.geteuid() or info.st_dev != os.fstat(fd).st_dev:
                raise BuilderError('foreign tree entry')
            path = prefix + name
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                if mode & 0o022:
                    raise BuilderError('writable tree entry')
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (info.st_dev, info.st_ino):
                        raise BuilderError('tree directory identity changed')
                    rows.append([path, 'directory', mode])
                    visit(child, path + '/', depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise BuilderError('hardlinked tree entry')
                filefd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(filefd, 'rb') as stream:
                    actual = os.fstat(stream.fileno())
                    if (actual.st_dev, actual.st_ino, actual.st_mode, actual.st_nlink, actual.st_uid) != (info.st_dev, info.st_ino, info.st_mode, 1, info.st_uid):
                        raise BuilderError('tree identity changed before read')
                    data = stream.read(16 * 1048576 + 1)
                    after = os.fstat(stream.fileno())
                    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns):
                        raise BuilderError('tree bytes changed during read')
                budget[1] += len(data)
                if len(data) > 16 * 1048576 or budget[1] > 64 * 1048576:
                    raise BuilderError('tree byte limit exceeded')
                rows.append([path, 'file', mode, hashlib.sha256(data).hexdigest()])
            elif stat.S_ISLNK(info.st_mode) and not reject_symlinks:
                rows.append([path, 'symlink', os.readlink(name, dir_fd=directory)])
            else:
                raise BuilderError('unsupported tree entry')
        directory_after = os.fstat(directory)
        if (directory_after.st_mtime_ns, directory_after.st_ctime_ns) != (directory_before.st_mtime_ns, directory_before.st_ctime_ns):
            raise BuilderError('tree directory changed during inspection')
    visit(fd, '', 0)
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def rename_new(parent_fd, stage, name):
    """Linux atomic directory publication: RENAME_NOREPLACE, no fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise BuilderError('atomic nonoverwrite directory publication unavailable')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(stage), parent_fd, os.fsencode(name), 1):
        error = ctypes.get_errno()
        raise OSError(error, 'atomic new-directory publication refused')
    os.fsync(parent_fd)


class _Ruleset(ctypes.Structure):
    _fields_ = [('handled_access_fs', ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]


class _Filter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]


class _Program(ctypes.Structure):
    _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(_Filter))]


def _child_scope(stagefd, executable, readonly=()):
    """Child-only ABI5 Landlock: writes to pinned stage; exec trusted binary only.

    Trusted OS runtime libraries/loader remain readable; the loader is executable,
    and /dev/null is an allowed discard sink. No network or helper processes,
    mount/namespace/ptrace or alternate execution syscall. This is not a mount
    namespace or a general hostile-process sandbox (metadata syscalls differ).
    """
    import resource
    import signal
    parent_pid = os.getpid()
    def enter():
        if os.uname().machine != 'x86_64':
            raise BuilderError('builder confinement requires Linux x86_64')
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) or os.getppid() != parent_pid:
            os._exit(125)
        if libc.syscall(444, 0, 0, 1) < 5:
            raise BuilderError('builder confinement requires Landlock ABI5')
        attr = _Ruleset((1 << 16) - 1)
        ruleset = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
        if ruleset < 0:
            raise BuilderError('builder Landlock ruleset failed')
        pins = []
        def allow(fd, rights):
            rule = _PathRule(rights, fd)
            if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0):
                raise BuilderError('builder Landlock rule failed')
        try:
            # No device/socket/FIFO creation or execution in the staging tree.
            writable = sum(1 << bit for bit in (1, 2, 3, 4, 5, 7, 8, 12, 13, 14))
            allow(stagefd, writable)
            for fd in readonly:
                allow(fd, (1 << 2) | (1 << 3))
            for path in ('/usr/lib', '/lib', '/lib64', '/usr/share/git-core', '/etc/ld.so.cache'):
                try:
                    fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
                except FileNotFoundError:
                    continue
                pins.append(fd)
                allow(fd, (1 << 2) | ((1 << 3) if stat.S_ISDIR(os.fstat(fd).st_mode) else 0))
            fd = os.open('/dev/null', os.O_PATH | os.O_CLOEXEC)
            pins.append(fd); allow(fd, (1 << 1) | (1 << 2))
            for path in (executable, '/lib64/ld-linux-x86-64.so.2'):
                fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
                pins.append(fd); allow(fd, (1 << 0) | (1 << 2))
            if libc.prctl(38, 1, 0, 0, 0) or libc.syscall(446, ruleset, 0):
                raise BuilderError('builder Landlock restriction failed')
        finally:
            for fd in pins:
                os.close(fd)
            os.close(ruleset)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1048576, 64 * 1048576))
        deny = 0x00050000 | 1
        instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xC000003E), (0x06, 0, 0, 0x80000000),
                        (0x20, 0, 0, 0), (0x35, 0, 1, 0x40000000), (0x06, 0, 0, deny)]
        for number in (*range(41, 59), 62, 101, 165, 166, 169, 200, 234, 246, 248, 249, 250,
                       272, 288, 299, 303, 304, 307, 308, 310, 311, 321, 322, 323, 425, 426, 427, 435):
            instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, deny)))
        instructions.append((0x06, 0, 0, 0x7FFF0000))
        filters = (_Filter * len(instructions))(*(_Filter(*row) for row in instructions))
        program = _Program(len(instructions), filters)
        if libc.prctl(22, 2, ctypes.byref(program), 0, 0):
            raise BuilderError('builder seccomp unavailable')
        os.fchdir(stagefd)
    return enter


# Audited Linux CPython 3.10 stdlib generation profile. A changed implementation
# requires a new audited profile, never an observed-output baseline fallback.
# This pins generation rules, not the interpreter bytes (read from trusted /usr).
_VENV_PROFILE = '02af55f77ef070f9780276299c3a0e98cb7f527ccb58ff9371426edb9007ecd0'
_VENV_TEMPLATES = ('activate', 'activate.csh', 'activate.fish', 'Activate.ps1')


def _venv_contract_rows(inputs, stage_path, target, *, relocated=True):
    """Pure independent expectation for the pinned --copies/--without-pip profile.

    Inputs come from trusted system files BEFORE the creating child runs, never
    from its generated tree. Modes are deterministic via the child's 0077 umask.
    Templates follow the audited stdlib quoting rules, then our prefix relocation.
    """
    import shlex
    if (type(inputs) is not dict or set(inputs) != {'profile', 'version', 'executable', 'interpreter_sha256', 'templates'}
            or inputs['profile'] != _VENV_PROFILE or inputs['executable'] != '/usr/bin/python3'
            or type(inputs['version']) is not list or len(inputs['version']) != 3
            or any(type(n) is not int or not 0 <= n <= 999 for n in inputs['version'])
            or inputs['version'][:2] != [3, 10]
            or type(inputs['interpreter_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', inputs['interpreter_sha256']) is None
            or type(inputs['templates']) is not dict or set(inputs['templates']) != set(_VENV_TEMPLATES)):
        raise BuilderError('unqualified trusted venv generation profile')
    for path in (stage_path, target):
        if (type(path) is not str or not 1 < len(path) <= 4096
                or re.fullmatch(r'/[A-Za-z0-9_./-]+', path) is None
                or any(part in ('', '.', '..') or len(part) > 255 for part in path[1:].split('/'))):
            raise BuilderError('invalid venv contract prefix')
    prompt = Path(target).name
    replacements = {'__VENV_DIR__': stage_path, '__VENV_NAME__': 'environment',
                    '__VENV_PROMPT__': '(' + prompt + ') ', '__VENV_BIN_NAME__': 'bin',
                    '__VENV_PYTHON__': stage_path + '/bin/python3'}
    rows = [[name, 'directory', 0o700] for name in
            ('bin', 'include', 'lib', 'lib/python3.10', 'lib/python3.10/site-packages')]
    rows.append(['lib64', 'symlink', 'lib'])
    rows.extend(['bin/' + name, 'file', 0o755, inputs['interpreter_sha256']]
                for name in ('python', 'python3', 'python3.10'))
    config = ('home = /usr/bin\ninclude-system-site-packages = false\nversion = %d.%d.%d\n'
              % tuple(inputs['version']) + 'prompt = %r\n' % prompt).encode()
    rows.append(['pyvenv.cfg', 'file', 0o600, hashlib.sha256(config).hexdigest()])
    for name in _VENV_TEMPLATES:
        template = inputs['templates'][name]
        if (type(template) is not list or len(template) != 2 or type(template[0]) is not int
                or template[0] not in (0o644, 0o755) or type(template[1]) is not str
                or not 0 < len(template[1]) <= 1048576):
            raise BuilderError('invalid trusted activation template')
        text = template[1]
        for key, value in replacements.items():
            quoted = "'" + value.replace("'", "''") + "'" if name.endswith('.ps1') else shlex.quote(value)
            text = text.replace(key, quoted)
        data = text.encode('utf-8')
        if relocated:
            data = data.replace(stage_path.encode(), target.encode())
        rows.append(['bin/' + name, 'file', template[0], hashlib.sha256(data).hexdigest()])
    return sorted(rows)


def _verify_venv_contract(actual_digest, expected_rows):
    """Compare to generation-input expectation, never bless an observed baseline."""
    expected = hashlib.sha256(json.dumps(expected_rows, separators=(',', ':')).encode()).hexdigest()
    if actual_digest != expected:
        raise BuilderError('venv bytes/structure differ from trusted generation contract')
    return expected


def _read_trusted_generation_file(path):
    """Read system generation inputs only; never follow a fixture-provided path.

    Trusted OS/runtime is part of the execution model. Require root-owned,
    non-writable ancestry as well as a stable regular no-follow opened inode.
    """
    resolved = Path(os.path.realpath(path))
    if not str(resolved).startswith('/usr/'):
        raise BuilderError('generation input outside trusted system tree')
    for ancestor in (resolved.parent, *resolved.parent.parents):
        info = os.stat(ancestor, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise BuilderError('untrusted generation input ancestry')
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o022
                or not 0 < before.st_size <= 16 * 1048576):
            raise BuilderError('untrusted generation input file')
        data = stream.read(16 * 1048576 + 1)
        after = os.fstat(stream.fileno())
        if (len(data) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise BuilderError('generation input changed during read')
        return data, stat.S_IMODE(before.st_mode)


def _trusted_venv_inputs():
    """Acquire expected data before creation; no generated-tree reads or writes."""
    source, _ = _read_trusted_generation_file('/usr/lib/python3.10/venv/__init__.py')
    profile = hashlib.sha256(source).hexdigest()
    if profile != _VENV_PROFILE:
        raise BuilderError('stdlib venv implementation needs a qualified generation profile')
    interpreter, mode = _read_trusted_generation_file('/usr/bin/python3')
    if mode != 0o755:
        raise BuilderError('unsupported system Python mode')
    query = ('import json,sys; print(json.dumps({"version":list(sys.version_info[:3]),'
             '"executable":sys._base_executable,"platform":sys.platform,'
             '"bits":64 if sys.maxsize > 2**32 else 32}))')
    result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c', query],
                            env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C'},
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            check=True, timeout=10)
    if len(result.stdout) > 4096:
        raise BuilderError('trusted Python metadata budget exceeded')
    try:
        metadata = json.loads(result.stdout)
        if (type(metadata) is not dict or set(metadata) != {'version', 'executable', 'platform', 'bits'}
                or metadata['platform'] != 'linux' or metadata['bits'] != 64):
            raise ValueError
    except (ValueError, TypeError):
        raise BuilderError('unsupported trusted Python metadata') from None
    templates = {}
    for name in _VENV_TEMPLATES:
        section = 'common' if name in ('activate', 'Activate.ps1') else 'posix'
        data, mode = _read_trusted_generation_file('/usr/lib/python3.10/venv/scripts/' + section + '/' + name)
        if len(data) > 1048576:
            raise BuilderError('activation template budget exceeded')
        try:
            templates[name] = [mode, data.decode('utf-8')]
        except UnicodeError:
            raise BuilderError('unsupported activation template encoding') from None
    return {'profile': profile, 'version': metadata['version'], 'executable': metadata['executable'],
            'interpreter_sha256': hashlib.sha256(interpreter).hexdigest(), 'templates': templates}


def build_environment(root, action, parent_fd, stage, stagefd):
    desired = action['desired']
    allowed = {'manager', 'path', 'fixture_local', 'enabled'}
    if desired.get('manager') != 'venv' or desired.get('fixture_local') is not True or set(desired) - allowed:
        raise BuilderError('stdlib venv only; requested pins/packages/managers require dedicated adapters')
    # The child traverses the pinned staging descriptor, never target ancestors.
    stage_path = f'/proc/self/fd/{stagefd}/environment'
    parent_identity = root.parent_identity(action['target'])
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', action['target']):
        raise BuilderError('venv generated activation relocation requires a simple absolute prefix')
    inputs = _trusted_venv_inputs()
    initial_rows = _venv_contract_rows(inputs, stage_path, action['target'], relocated=False)
    final_rows = _venv_contract_rows(inputs, stage_path, action['target'])
    subprocess.run(['/usr/bin/python3', '-I', '-B', '-m', 'venv', '--without-pip', '--copies', '--prompt', Path(action['target']).name, stage_path],
                   env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C'},
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True, timeout=30, umask=0o077, pass_fds=(stagefd, *root.lock_fds),
                   preexec_fn=_child_scope(stagefd, '/usr/bin/python3'))
    if root.parent_identity(action['target']) != parent_identity:
        raise BuilderError('environment parent moved during build')
    if os.listdir(stagefd) != ['environment']:
        raise BuilderError('unexpected environment staging entries')
    payload = os.open('environment', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stagefd)
    try:
        # Check every initial byte and entry against independent trusted inputs;
        # edits between child exit and this FIRST observation cannot be blessed.
        _verify_venv_contract(tree_digest(payload), initial_rows)
        for name in os.listdir(payload):
            os.rename(name, name, src_dir_fd=payload, dst_dir_fd=stagefd)
        os.rmdir('environment', dir_fd=stagefd)
    finally:
        os.close(payload)
    # Only known files generated by trusted stdlib in this newly created staging
    # directory are relocated. Never patch user settings or environment contents.
    stagefd = os.dup(stagefd)
    try:
        for relative in ('pyvenv.cfg', 'bin/activate', 'bin/activate.csh', 'bin/activate.fish', 'bin/Activate.ps1'):
            parts = relative.split('/')
            directory = os.dup(stagefd)
            try:
                if len(parts) > 1:
                    child = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory)
                    directory = child
                fd = os.open(parts[-1], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'r+b') as stream:
                    info = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_uid != os.geteuid() or info.st_dev != os.fstat(stagefd).st_dev):
                        raise BuilderError('invalid generated activation inode')
                    data = stream.read(1048577)
                    if len(data) > 1048576 or os.fstat(stream.fileno()).st_nlink != 1:
                        raise BuilderError('invalid generated activation file')
                    data = data.replace(stage_path.encode(), action['target'].encode())
                    stream.seek(0)
                    stream.write(data)
                    stream.truncate()
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(directory)
        return _verify_venv_contract(tree_digest(stagefd), final_rows)
    finally:
        os.close(stagefd)


def _copy_objects(source, destination):
    """Copy Git object bytes only; no source config, refs, hooks or path reuse."""
    budget = [0, 0]
    device = os.fstat(source).st_dev
    def copy(src, dst, depth):
        for name in os.listdir(src):
            budget[0] += 1
            if budget[0] > 4096 or depth > 2:
                raise BuilderError('object copy count/depth exceeded')
            before = os.stat(name, dir_fd=src, follow_symlinks=False)
            if before.st_uid != os.geteuid() or before.st_dev != device:
                raise BuilderError('foreign object store')
            if stat.S_ISDIR(before.st_mode):
                if depth != 0 or (name not in ('info', 'pack') and not re.fullmatch('[0-9a-f]{2}', name)):
                    raise BuilderError('unsupported object directory')
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=src)
                try:
                    if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (before.st_dev, before.st_ino):
                        raise BuilderError('object directory changed')
                    try:
                        os.mkdir(name, 0o700, dir_fd=dst)
                    except FileExistsError:
                        if name not in ('info', 'pack'):
                            raise
                    out = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dst)
                    try:
                        copy(child, out, depth + 1)
                    finally:
                        os.close(out)
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
                if not re.fullmatch(r'(?:[0-9a-f]{38}|pack-[0-9a-f]{40}\.(?:pack|idx|rev))', name):
                    raise BuilderError('unsupported object file')
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src)
                with os.fdopen(fd, 'rb') as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink) != (before.st_dev, before.st_ino, before.st_mode, 1):
                        raise BuilderError('object identity changed')
                    data = stream.read(16 * 1048576 + 1)
                    after = os.fstat(stream.fileno())
                    if (after.st_mtime_ns, after.st_ctime_ns, after.st_size) != (opened.st_mtime_ns, opened.st_ctime_ns, opened.st_size):
                        raise BuilderError('object bytes changed')
                budget[1] += len(data)
                if len(data) > 16 * 1048576 or budget[1] > 64 * 1048576:
                    raise BuilderError('object copy byte budget exceeded')
                out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dst)
                with os.fdopen(out, 'wb') as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
            else:
                raise BuilderError('unsupported object inode')
    copy(source, destination, 0)


def _verify_checkout(stagefd, entries):
    """Compare every worktree byte with the pinned commit, not Git's stat cache."""
    expected = {}
    directories = set()
    for entry in entries.split(b'\0'):
        if not entry:
            continue
        try:
            metadata, path = entry.split(b'\t', 1)
            mode, kind, checksum = metadata.split(b' ')
            name = path.decode('utf-8')
        except (ValueError, UnicodeError):
            raise BuilderError('unsupported Git tree encoding') from None
        parts = name.split('/')
        if (mode not in (b'100644', b'100755') or kind != b'blob' or not re.fullmatch(b'[0-9a-f]{40}', checksum)
                or any(part in ('', '.', '..', '.git') for part in parts) or name in expected):
            raise BuilderError('unsupported Git tree entry')
        expected[name] = (mode == b'100755', checksum.decode())
        directories.update('/'.join(parts[:i]) for i in range(1, len(parts)))
    actual, seen_dirs = set(), set()
    budget = [0, 0]
    def visit(fd, prefix):
        for name in os.listdir(fd):
            if not prefix and name == '.git':
                continue
            budget[0] += 1
            if budget[0] > 4096:
                raise BuilderError('checkout entry budget exceeded')
            path = prefix + name
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if before.st_dev != os.fstat(stagefd).st_dev or before.st_uid != os.geteuid():
                raise BuilderError('checkout inode boundary')
            if stat.S_ISDIR(before.st_mode) and path in directories:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (before.st_dev, before.st_ino):
                        raise BuilderError('checkout directory changed')
                    seen_dirs.add(path); visit(child, path + '/')
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and path in expected:
                filefd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(filefd, 'rb') as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink) != (before.st_dev, before.st_ino, before.st_mode, 1):
                        raise BuilderError('checkout file changed')
                    content = stream.read(16 * 1048576 + 1)
                    after = os.fstat(stream.fileno())
                    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
                        raise BuilderError('checkout bytes changed during verification')
                budget[1] += len(content)
                if len(content) > 16 * 1048576 or budget[1] > 64 * 1048576:
                    raise BuilderError('checkout byte budget exceeded')
                actual.add(path)
                blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
                if expected[path] != (bool(before.st_mode & 0o111), blob):
                    raise BuilderError('checkout bytes differ from requested commit')
            else:
                raise BuilderError('untracked or unsupported checkout entry')
    visit(stagefd, '')
    if actual != set(expected) or seen_dirs != directories:
        raise BuilderError('incomplete checkout')


def build_repository(root, action, parent_fd, stage, stagefd):
    desired = action['desired']
    source = desired.get('repository', '')
    revision = desired.get('revision', '')
    if desired.get('fixture_local') is not True or not re.fullmatch('[0-9a-f]{40}', revision):
        raise BuilderError('only explicit pinned local fixture Git sources supported')
    root.relative(source)
    with root.parent(source) as (source_parent, source_name):
        source_fd = os.open(source_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_parent)
    try:
        before = tree_digest(source_fd, reject_symlinks=True)
        gitfd = os.open('.git', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
        try:
            import configparser
            configfd = os.open('config', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=gitfd)
            with os.fdopen(configfd, 'r', encoding='utf-8') as stream:
                config = stream.read(65537)
            if len(config) > 65536:
                raise BuilderError('source config budget exceeded')
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read_string(config)
            except configparser.Error:
                raise BuilderError('unsupported source config syntax') from None
            allowed = {'core': {'repositoryformatversion', 'filemode', 'bare', 'logallrefupdates'}, 'user': {'name', 'email'}}
            if parser.defaults() or any(section not in allowed or set(parser[section]) - allowed[section] for section in parser.sections()):
                raise BuilderError('source config helpers/includes/remotes require separate inspection; no Git invoked')
            for forbidden in ('commondir', 'worktrees', 'shallow'):
                try:
                    os.stat(forbidden, dir_fd=gitfd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise BuilderError('worktree/shared/shallow source unsupported')
            objects = os.open('objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=gitfd)
            try:
                info = os.open('info', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=objects)
                try:
                    if os.listdir(info):
                        raise BuilderError('alternate/shared object stores unsupported')
                finally:
                    os.close(info)
            finally:
                os.close(objects)
        finally:
            os.close(gitfd)
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_SYSTEM': '/dev/null',
               'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': '', 'GIT_OPTIONAL_LOCKS': '0',
               'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
               'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}
        git = ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'protocol.allow=never']
        destination = f'/proc/self/fd/{stagefd}'
        def run(args, capture=False):
            fd = os.open('.', os.O_RDWR | os.O_TMPFILE, 0o600, dir_fd=stagefd) if capture else None
            try:
                subprocess.run(git + args, env=env, stdin=subprocess.DEVNULL, stdout=fd if capture else subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=True, timeout=30,
                               pass_fds=(stagefd, *root.lock_fds),
                               preexec_fn=_child_scope(stagefd, '/usr/bin/git'))
                if fd is not None:
                    if os.fstat(fd).st_size > 1048576:
                        raise BuilderError('Git metadata output budget exceeded')
                    return os.pread(fd, 1048577, 0)
                return b''
            finally:
                if fd is not None:
                    os.close(fd)
        run(['init', '--template=', destination])
        source_git = os.open('.git', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
        dest_git = os.open('.git', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stagefd)
        try:
            source_objects = os.open('objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_git)
            try:
                dest_objects = os.open('objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dest_git)
                try:
                    _copy_objects(source_objects, dest_objects)
                finally:
                    os.close(dest_objects)
            finally:
                os.close(source_objects)
        finally:
            os.close(source_git); os.close(dest_git)
        # Check expanded bytes/count BEFORE checkout, not just after writes.
        listing = run(['-C', destination, 'ls-tree', '-rz', '--long', '--full-tree', revision], capture=True)
        entries = [entry for entry in listing.split(b'\0') if entry]
        expanded = 0
        if len(entries) > 4096:
            raise BuilderError('checkout expansion count exceeded')
        for entry in entries:
            try:
                metadata, _ = entry.split(b'\t', 1)
                mode, kind, checksum, size = metadata.split()
                size = int(size)
            except ValueError:
                raise BuilderError('unsupported Git expansion metadata') from None
            if mode not in (b'100644', b'100755') or kind != b'blob' or not 0 <= size <= 16 * 1048576:
                raise BuilderError('unsupported or oversized Git expansion')
            expanded += size
            if expanded > 64 * 1048576:
                raise BuilderError('checkout expansion byte budget exceeded')
        run(['-C', destination, '-c', 'submodule.recurse=false', 'checkout', '--detach', revision, '--'])
        run(['-C', destination, 'config', 'remote.origin.url', source])
        if run(['-C', destination, 'rev-parse', '--verify', 'HEAD'], capture=True).strip() != revision.encode():
            raise BuilderError('checkout HEAD differs from requested commit')
        expected_tree = tree_digest(stagefd)
        _verify_checkout(stagefd, run(['-C', destination, 'ls-tree', '-rz', '--full-tree', revision], capture=True))
        if tree_digest(source_fd, reject_symlinks=True) != before:
            raise BuilderError('source changed during checkout; staged result not published')
        if tree_digest(stagefd) != expected_tree:
            raise BuilderError('checkout changed across content verification')
        return expected_tree
    finally:
        os.close(source_fd)
