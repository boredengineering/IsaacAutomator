"""Linux Landlock + default-deny libseccomp confinement for disposable workers.

Call only after trusted imports and before processing any untrusted data. Failure
is fatal to the worker: restrictions are irreversible and may be partly applied.
No namespace/Docker fallback and no unsafe development bypass.
"""
import ctypes
import errno
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


class SandboxError(RuntimeError):
    """Safe error without paths, environment, or native exception contents."""


class _Ruleset(ctypes.Structure):
    _fields_ = [('handled_access_fs', ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]


def _libraries():
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        raise SandboxError('sandbox_unsupported')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                          ctypes.c_ulong, ctypes.c_ulong]
    seccomp = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    return libc, seccomp


def _open_grant(path):
    """Pinned nofollow walk of a caller-approved static runtime/schema path."""
    if not isinstance(path, str) or not path.startswith('/') or '\x00' in path:
        raise SandboxError('unsafe_read_path')
    parsed = Path(path)
    repo = Path(__file__).absolute().parents[2]
    if (str(parsed) != path or '..' in parsed.parts or parsed in (repo, *repo.parents)
            or path in ('/root', '/home', '/tmp', '/var', '/usr', '/etc', '/opt', '/workspaces')
            or any(parsed == Path(p) or Path(p) in parsed.parents for p in ('/proc', '/sys', '/dev'))
            or path.startswith('/home/') and len(parsed.parts) <= 3):
        raise SandboxError('unsafe_read_path')
    fd = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(parsed.parts[1:]):
            flags = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
            if index < len(parsed.parts) - 2:
                flags |= os.O_DIRECTORY
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        st = os.fstat(fd)
        if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode) and st.st_nlink == 1):
            raise SandboxError('unsafe_read_path')
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def _landlock(libc, read_paths):
    abi = libc.syscall(444, 0, 0, 1)  # landlock_create_ruleset VERSION
    if abi < 3:  # truncate mediation is mandatory
        raise SandboxError('landlock_unavailable')
    handled = (1 << (16 if abi >= 5 else 15)) - 1
    rules = _Ruleset(handled)
    rules_fd = libc.syscall(444, ctypes.byref(rules), ctypes.sizeof(rules), 0)
    if rules_fd < 0:
        raise SandboxError('landlock_unavailable')
    try:
        for path in read_paths:
            fd = _open_grant(path)
            try:
                mode = os.fstat(fd).st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise SandboxError('unsafe_read_path')
                access = (1 << 2) | ((1 << 3) if stat.S_ISDIR(mode) else 0)
                rule = _PathRule(access, fd)  # READ_FILE, optional READ_DIR only
                if libc.syscall(445, rules_fd, 1, ctypes.byref(rule), 0) != 0:
                    raise SandboxError('landlock_rule_failed')
            finally:
                os.close(fd)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            raise SandboxError('no_new_privs_failed')
        if libc.syscall(446, rules_fd, 0) != 0:
            raise SandboxError('landlock_restrict_failed')
    finally:
        os.close(rules_fd)


def _seccomp(seccomp):
    # All other syscalls return EPERM, including network, exec/clone/fork,
    # mount, ptrace, io_uring, bpf, process_vm_*, writes via metadata/ioctl.
    context = seccomp.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise SandboxError('seccomp_init_failed')
    allowed = '''read readv pread64 write writev close lseek fstat newfstatat stat lstat statx
        open openat getdents getdents64 mmap mprotect munmap mremap brk madvise futex
        clock_gettime clock_getres gettimeofday time rt_sigaction rt_sigprocmask
        rt_sigreturn sigaltstack getrandom getpid getppid gettid getuid geteuid
        getgid getegid getcwd uname sched_yield sched_getaffinity getrusage
        restart_syscall exit exit_group'''.split()
    try:
        for name in allowed:
            number = seccomp.seccomp_syscall_resolve_name(name.encode('ascii'))
            if number >= 0 and seccomp.seccomp_rule_add(context, 0x7fff0000, number, 0) != 0:
                raise SandboxError('seccomp_rule_failed')
        if seccomp.seccomp_load(context) != 0:
            raise SandboxError('seccomp_load_failed')
    finally:
        seccomp.seccomp_release(context)


def restrict_process(read_paths: list[str]) -> None:
    """Irreversibly restrict THIS dedicated single-threaded child process."""
    try:
        libc, seccomp = _libraries()
        if not isinstance(read_paths, list) or len(read_paths) > 256:
            raise SandboxError('unsafe_read_paths')
        if len(os.listdir('/proc/self/task')) != 1:
            raise SandboxError('multithreaded_worker')
        for fd in (0, 1, 2):
            st = os.fstat(fd)
            if not (stat.S_ISFIFO(st.st_mode) or
                    stat.S_ISCHR(st.st_mode) and st.st_rdev == os.makedev(1, 3)):
                raise SandboxError('unsafe_stdio')
        # Landlock does not revoke existing descriptors. Close all capabilities
        # other than the parent-owned stdio pipes before installing rules.
        if libc.syscall(436, ctypes.c_uint(3), ctypes.c_uint(0xffffffff), 0) != 0:
            raise SandboxError('descriptor_cleanup_failed')
        _landlock(libc, read_paths)
        _seccomp(seccomp)
    except (OSError, ValueError, TypeError, AttributeError):
        raise SandboxError('sandbox_unavailable') from None


def sandbox_available() -> bool:
    """Probe actual confinement in a fresh child; never restrict this caller."""
    code = '''
import errno, os, runpy, socket, sys
module = runpy.run_path(sys.argv[1])
module['restrict_process']([])
checks = []
for action in (lambda: open(sys.argv[2]).read(),
               lambda: open(sys.argv[2], 'w'),
               lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
               lambda: os.execve('/bin/true', ['/bin/true'], {})):
    try:
        action()
    except OSError as error:
        checks.append(error.errno in (errno.EPERM, errno.EACCES))
    else:
        checks.append(False)
print('sandbox-ok' if all(checks) else 'sandbox-failed')
'''
    try:
        with tempfile.TemporaryDirectory(prefix='ia-sandbox-probe-') as tmp:
            fixture = Path(tmp) / 'synthetic.txt'
            fixture.write_text('synthetic probe', encoding='ascii')
            result = subprocess.run(
                [sys.executable, '-I', '-B', '-c', code, str(Path(__file__).absolute()), str(fixture)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
                env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
            return result.returncode == 0 and result.stdout.strip() == 'sandbox-ok'
    except (OSError, subprocess.SubprocessError):
        return False
