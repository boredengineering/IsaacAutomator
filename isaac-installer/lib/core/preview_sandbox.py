"""Small fail-closed Linux sandbox for preloaded, pure-data readers.

Not a physical-host approval or runtime qualification. No namespace fallback:
Landlock confines file contents; seccomp denies mutation/network/exec syscalls.
All imports needed by the caller must precede confine_readonly(). Runtime is
already in memory, so no broad /usr or home read allowance is necessary.
"""
import ctypes
import errno
import os
import resource
import signal
import stat


class SandboxError(RuntimeError):
    pass


class _Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]


class _Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_Filter))]


def _pin(path):
    """O_PATH walk: no content read, no symlink components, no special files."""
    if not isinstance(path, str) or not path.startswith("/") or "\0" in path:
        raise SandboxError("Selected inputs must be absolute paths.")
    parts = path.split("/")[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise SandboxError("Selected path is empty, broad or contains traversal.")
    fd = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(parts):
            flags = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
            if index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            newfd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = newfd
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise SandboxError("Hardlinked selected files are unsupported.")
        elif not stat.S_ISDIR(info.st_mode):
            raise SandboxError("Selected input must be a regular file or directory, not a link/device.")
        elif path in ("/home", "/root", "/tmp", "/proc", "/sys", "/dev", "/etc", "/usr", "/var") or path == os.environ.get("HOME"):
            raise SandboxError("Broad host/home directories are not admitted inputs.")
        return fd, stat.S_ISDIR(info.st_mode)
    except BaseException:
        os.close(fd)
        raise


def _seccomp(libc):
    # Linux x86_64 only; arch check also rejects x32 syscall numbers.
    allow = 0x7FFF0000
    deny = 0x00050000 | errno.EPERM
    instructions = [
        (0x20, 0, 0, 4),             # seccomp_data.arch
        (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, 0x80000000),   # KILL_PROCESS on architecture mismatch
        (0x20, 0, 0, 0),             # seccomp_data.nr
        (0x15, 0, 5, 1),             # write: only stdout/stderr
        (0x20, 0, 0, 16),
        (0x15, 2, 0, 1),
        (0x15, 1, 0, 2),
        (0x06, 0, 0, deny),
        (0x06, 0, 0, allow),
    ]
    # open/openat permitted only because Landlock enforces read-only access.
    # Everything else (socket/connect, exec, fork, chmod, mount, ptrace,
    # io_uring, ioctl, sendfile, process_vm_*, signals, privilege changes...) denied.
    for number in (0, 2, 3, 5, 8, 9, 10, 11, 12, 13, 14, 15, 17, 24,
                   28, 39, 60, 89, 96, 102, 104, 107, 108, 158,
                   186, 202, 217, 218, 228, 231, 257, 262, 267, 273, 302, 318, 332):
        instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, allow)))
    instructions.append((0x06, 0, 0, deny))
    filters = (_Filter * len(instructions))(*(_Filter(*item) for item in instructions))
    program = _Program(len(instructions), filters)
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise SandboxError("Seccomp filter unavailable; no metadata was read.")


class _CapabilityHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapabilityData(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32),
                ("inheritable", ctypes.c_uint32)]


def require_unprivileged():
    """Reject privilege before selected paths are pinned or their contents read.

    Contract: real/effective/saved UIDs must be one nonzero UID; the analogous
    GIDs must be one nonzero GID; fsuid/fsgid must match. Nonzero supplementary
    groups are preserved, not looked up or changed. All effective, permitted,
    inheritable and ambient capability sets must be empty.

    This is a credential precondition, NOT confinement on its own. Group DAC
    permissions cannot override Landlock's scoped inode read-only rules. The
    seccomp allowlist denies socket/connect, exec, ioctl and identity changes;
    full inherited FD closure removes preopened file/device/socket authority.
    Thus even service/device groups add no outside-content or mutation channel
    AFTER confine_readonly succeeds. No untrusted reader may run before that.
    The caller must be a single-threaded reader and must exit on any failure.
    """
    if os.uname().sysname != "Linux" or os.uname().machine != "x86_64":
        raise SandboxError("Confinement requires Linux x86_64 with Landlock and seccomp.")
    uids = os.getresuid()
    if 0 in uids or len(set(uids)) != 1:
        raise SandboxError("Root or transitional user identities are refused.")
    gids = os.getresgid()
    if 0 in gids or len(set(gids)) != 1 or 0 in os.getgroups():
        raise SandboxError("Root or transitional group identities are refused.")
    # capget v3 returns both 32-bit words, without /proc or environment probing.
    libc = ctypes.CDLL(None, use_errno=True)
    # Query with the invalid uid_t/gid_t sentinel: no identity is changed.
    for syscall, expected in ((122, uids[0]), (123, gids[0])):
        actual = libc.syscall(syscall, ctypes.c_uint(0xFFFFFFFF))
        if actual == -1 or ctypes.c_uint(actual).value != expected:
            raise SandboxError("Filesystem identity differs or cannot be inspected.")
    header = _CapabilityHeader(0x20080522, 0)
    capabilities = (_CapabilityData * 2)()
    if libc.syscall(125, ctypes.byref(header), ctypes.byref(capabilities)) != 0:
        raise SandboxError("Capability inspection unavailable; no metadata was read.")
    if any(item.effective or item.permitted or item.inheritable for item in capabilities):
        raise SandboxError("Processes with retained capabilities are refused.")
    # Linux guarantees ambient is a subset of permitted AND inheritable. Requiring
    # both sets empty also proves ambient empty (including all 64 capability bits).



def confine_readonly(paths, optional_files=(), *, allow_empty=False):
    """Irreversibly confine this single-threaded reader to selected input paths.

    Raises SandboxError; callers MUST exit on error, never continue reading.
    Read/list is recursive for explicitly selected directories. File path rules
    bind inodes, not names. Traversal/content policy remains the caller's job.
    optional_files grants only exact regular single-link files, ignoring ENOENT
    alone. Directories (including .git), symlinks and all other errors refuse.
    Omit checkout/.git from optional_files for standard directory checkouts.
    At most 32 required paths and 128 combined paths; an optional-only selection
    is supported, even when every optional file is absent (zero content grants).
    Explicit allow_empty supports intent-only review with zero filesystem grants;
    accidental empty selections continue to refuse by default.
    """
    require_unprivileged()
    if (type(allow_empty) is not bool or (not paths and not optional_files and not allow_empty)
            or len(paths) > 32 or len(paths) + len(optional_files) > 128):
        raise SandboxError("Select at most 32 required and 128 combined bounded read-only inputs.")
    libc = ctypes.CDLL(None, use_errno=True)
    # No metadata content or user imports have been read at this point.
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 5:
        raise SandboxError("Landlock ABI >= 5 unavailable; no metadata was read.")
    for fd in (1, 2):
        mode = os.fstat(fd).st_mode
        if not stat.S_ISFIFO(mode) and not (stat.S_ISCHR(mode) and os.isatty(fd)):
            raise SandboxError("Output must be a pipe or terminal; files and sockets are refused.")
    # RLIMIT_NOFILE can be lowered below existing descriptors. Close the entire
    # unsigned FD range, not the current limit; never fall back to a bounded loop.
    # __NR_close_range = 436 on the x86_64 ABI checked above.
    if libc.syscall(436, ctypes.c_uint(3), ctypes.c_uint(0xFFFFFFFF), 0) != 0:
        raise SandboxError("Full inherited descriptor closure unavailable; no metadata was read.")
    try:
        os.close(0)
    except OSError as error:
        if error.errno != errno.EBADF:
            raise SandboxError("Cannot close inherited standard input; no metadata was read.") from None
    pins = []
    ruleset = -1
    try:
        for path in paths:
            pins.append(_pin(path))
        for path in optional_files:
            try:
                pin = _pin(path)
            except OSError as error:
                if error.errno != errno.ENOENT:
                    raise
                continue
            pins.append(pin)
            if pin[1]:
                raise SandboxError("Optional file grants cannot admit directories.")
        # All ABI5 filesystem rights, including REFER, TRUNCATE and IOCTL_DEV.
        attr = _Ruleset((1 << 16) - 1)
        ruleset = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
        if ruleset < 0:
            raise SandboxError("Landlock ruleset unavailable; no metadata was read.")
        for fd, directory in pins:
            rule = _PathRule((1 << 2) | ((1 << 3) if directory else 0), fd)
            if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
                raise SandboxError("Landlock path rule failed; no metadata was read.")
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, ruleset, 0) != 0:
            raise SandboxError("Landlock restriction failed; no metadata was read.")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        signal.alarm(8)
        _seccomp(libc)
    except OSError:
        raise SandboxError("Cannot confine selected inputs; no metadata was read.") from None
    finally:
        for fd, _ in pins:
            os.close(fd)
        if ruleset >= 0:
            os.close(ruleset)


def _seccomp_writer(libc, output_fd):
    """Deny every pathname operation; only two write descriptors survive."""
    allow, deny = 0x7FFF0000, 0x00050000 | errno.EPERM
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xC000003E),
                    (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0)]
    for syscall, fds in ((1, (1, output_fd)), (74, (output_fd,))):
        # A failed syscall match skips the entire argument-check block.
        block = [(0x20, 0, 0, 16)]
        for fd in fds:
            block.extend(((0x15, 0, 1, fd), (0x06, 0, 0, allow)))
        block.append((0x06, 0, 0, deny))
        instructions.append((0x15, 0, len(block), syscall))
        instructions.extend(block)
    # mmap is anonymous-only: no inherited file/device-backed mappings.
    block = [(0x20, 0, 0, 48), (0x15, 0, 1, 0xFFFFFFFF),
             (0x06, 0, 0, allow), (0x06, 0, 0, deny)]
    instructions.append((0x15, 0, len(block), 9))
    instructions.extend(block)
    for number in (3, 5, 10, 11, 12, 13, 14, 15, 24, 28, 39, 60,
                   96, 186, 202, 218, 228, 231, 273):
        instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, allow)))
    instructions.append((0x06, 0, 0, deny))
    filters = (_Filter * len(instructions))(*(_Filter(*item) for item in instructions))
    program = _Program(len(instructions), filters)
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise SandboxError("Writer seccomp unavailable; selected artifact may be empty.")


def confine_writer(output_fd, max_bytes):
    """Irreversible child-only writer: already approved O_WRONLY FD, no paths.

    This does not authorize/open a destination. report_writer owns exclusive
    creation and validation. Caller MUST exit on any failure. No read-only
    confinement behavior or grants are shared/widened by this API.
    """
    require_unprivileged()
    if type(output_fd) is not int or output_fd < 3 or not 0 < max_bytes <= 8 * 1024 * 1024:
        raise SandboxError("Invalid bounded writer descriptor.")
    info = os.fstat(output_fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            info.st_uid != os.geteuid() or info.st_size != 0 or
            stat.S_IMODE(info.st_mode) != 0o600):
        raise SandboxError("Writer requires a new private single-link regular file.")
    for fd in (1, 2):
        mode = os.fstat(fd).st_mode
        if not stat.S_ISFIFO(mode) and not (stat.S_ISCHR(mode) and os.isatty(fd)):
            raise SandboxError("Writer receipt must use pipes or terminals.")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syscall(444, 0, 0, 1) < 5:
        raise SandboxError("Writer requires Landlock ABI >= 5.")
    for first, last in ((3, output_fd - 1), (output_fd + 1, 0xFFFFFFFF)):
        if first <= last and libc.syscall(436, ctypes.c_uint(first), ctypes.c_uint(last), 0) != 0:
            raise SandboxError("Full inherited writer descriptor closure failed.")
    os.close(0)
    attr = _Ruleset((1 << 16) - 1)
    ruleset = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset < 0:
        raise SandboxError("Writer Landlock ruleset unavailable.")
    try:
        # Empty ruleset: no pathname is admitted, including the output path.
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, ruleset, 0) != 0:
            raise SandboxError("Writer Landlock confinement failed.")
    finally:
        os.close(ruleset)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))
    _seccomp_writer(libc, output_fd)


# Initial name retained for the fixture negative-control API.
enter_confinement = confine_readonly
