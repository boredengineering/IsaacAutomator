"""Persist raw producer bytes to one explicitly selected new local report.

Run only in a dedicated, single-threaded child with all code preloaded. stdin is
an exact-length pipe; stdout/stderr must be pipes or terminals. The supervisor
must validate producer completion/content before supplying those bytes. This
module never observes reports, imports selected code, creates parents, replaces
files, or performs cleanup/resume. A failure after exclusive creation preserves
an identified partial artifact for explicit review.

Admission requires Linux x86_64, unprivileged credentials, existing user-owned
non-group/world-writable output parent, normalized bounded absolute selections,
and openat2 NO_XDEV/NO_SYMLINKS from /. Separate/bind mounts and missing excluded
paths are deliberately unsupported, not silently resolved. Metadata-only pins
and a post-create identity check resist pathname swaps; no claim is made that
this process can stop a hostile same-UID/root process renaming/linking resources
after admission. The writable authority is the exclusively-created inode, not
future bindings of its pathname. SIGKILL/power loss cannot yield a final receipt;
the supervisor must report possible partial output, never infer success.

After admission the dedicated Landlock/seccomp writer denies every pathname,
network/exec and FD-rebinding operation. Only its O_WRONLY output FD and stdout
receipt remain writable; RLIMIT_FSIZE enforces the caller-selected byte budget.
Read-only observer confinement is intentionally unchanged.
"""
import argparse
import ctypes
import json
import os
import signal
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_sandbox as sandbox

MAX_REPORT_BYTES = 8 * 1024 * 1024


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


def _open_beneath(directory_fd, relative, flags, mode=0):
    # RESOLVE_BENEATH | NO_XDEV | NO_SYMLINKS | NO_MAGICLINKS. In particular,
    # NO_XDEV refuses same-device bind mounts, which st_dev cannot detect.
    how = _OpenHow(flags | os.O_CLOEXEC, mode, 0x08 | 0x01 | 0x04 | 0x02)
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.syscall(437, directory_fd, os.fsencode(relative), ctypes.byref(how), ctypes.sizeof(how))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "selected_path_refused")
    return fd


def _path(path):
    if (not isinstance(path, str) or not path.startswith("/") or len(path) > 4096 or
            any(ord(character) < 32 or ord(character) == 127 for character in path)):
        raise ValueError("invalid_selected_path")
    parts = path.split("/")[1:]
    if len(parts) > 64 or any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid_selected_path")
    return parts


def _identity(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _create_output(destination, excluded_roots, *, no_observed_roots=False):
    """Metadata-only admission followed by one exclusive create; no mkdir."""
    parts = _path(destination)
    if (type(no_observed_roots) is not bool or len(parts) < 2 or
            not isinstance(excluded_roots, (list, tuple)) or
            not (0 if no_observed_roots else 1) <= len(excluded_roots) <= 128 or
            no_observed_roots and excluded_roots):
        raise ValueError("invalid_output_selection")
    for path in excluded_roots:
        _path(path)
        if destination == path or destination.startswith(path + "/"):
            raise ValueError("output_inside_observed_root")
    pins = []
    root = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        excluded = set()
        for path in excluded_roots:
            fd = _open_beneath(root, path[1:], os.O_PATH)
            pins.append(fd)
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode):
                excluded.add(_identity(fd))
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe_excluded_root")
        parent = _open_beneath(root, "/".join(parts[:-1]), os.O_PATH | os.O_DIRECTORY)
        pins.append(parent)
        parent_info = os.fstat(parent)
        if parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o022:
            raise ValueError("output_parent_requires_private_ownership")
        # Check inode ancestry too, not only path spelling. All mount crossings
        # are already refused by openat2; no mount table or host content read.
        current = os.dup(parent)
        try:
            for _ in range(65):
                identity = _identity(current)
                if identity in excluded:
                    raise ValueError("output_inside_observed_root")
                ancestor = os.open("..", os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                   dir_fd=current)
                same = _identity(ancestor) == identity
                os.close(current)
                current = ancestor
                if same:
                    break
            else:
                raise ValueError("unbounded_output_ancestry")
        finally:
            os.close(current)
        old_mask = os.umask(0o077)
        try:
            return _open_beneath(parent, parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        finally:
            os.umask(old_mask)
    finally:
        for fd in pins:
            os.close(fd)
        os.close(root)


def _verify_destination(destination, fd):
    root = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        selected = _open_beneath(root, destination[1:], os.O_PATH)
        try:
            if _identity(selected) != _identity(fd):
                raise ValueError("selected_output_identity_changed")
        finally:
            os.close(selected)
    finally:
        os.close(root)


def _receipt_streams():
    for fd in (1, 2):
        mode = os.fstat(fd).st_mode
        if not stat.S_ISFIFO(mode) and not (stat.S_ISCHR(mode) and os.isatty(fd)):
            raise ValueError("receipt_requires_pipe_or_terminal")


class _FileStat(ctypes.Structure):
    # Linux x86_64 struct stat, used with the fd-only syscall (not glibc's
    # fstat -> newfstatat pathname wrapper, which the writer intentionally denies).
    _fields_ = [("device", ctypes.c_ulong), ("inode", ctypes.c_ulong),
                ("links", ctypes.c_ulong), ("mode", ctypes.c_uint),
                ("uid", ctypes.c_uint), ("gid", ctypes.c_uint), ("pad", ctypes.c_uint),
                ("rdev", ctypes.c_ulong), ("size", ctypes.c_long),
                ("rest", ctypes.c_byte * 88)]


def _fd_stat(fd):
    result = _FileStat()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syscall(5, fd, ctypes.byref(result)) != 0:
        raise OSError(ctypes.get_errno(), "output_metadata_unavailable")
    return result


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def persist_report(destination, excluded_roots, expected_bytes, *, max_bytes=MAX_REPORT_BYTES, no_observed_roots=False):
    """Read exact report bytes from stdin, create a new selected report, return receipt."""
    receipt = {"status": "refused", "destination": destination, "bytes_written": 0,
               "owned_artifact": None}
    fd = None
    try:
        sandbox.require_unprivileged()
        _receipt_streams()
        if not stat.S_ISFIFO(os.fstat(0).st_mode):
            raise ValueError("input_requires_pipe")
        if (type(no_observed_roots) is not bool or type(expected_bytes) is not int or type(max_bytes) is not int or
                not 0 < expected_bytes <= max_bytes <= MAX_REPORT_BYTES):
            raise ValueError("invalid_byte_budget")
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            signal.signal(number, _interrupt)
        signal.alarm(8)
        payload = bytearray()
        while len(payload) <= expected_bytes:
            chunk = os.read(0, min(65536, expected_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != expected_bytes:
            raise ValueError("payload_length_mismatch")
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGALRM})
        try:
            fd = (_create_output(destination, excluded_roots, no_observed_roots=True)
                  if no_observed_roots is True else _create_output(destination, excluded_roots))
            receipt["status"] = "partial"
            receipt["owned_artifact"] = {"identity_unknown": True}
            info = os.fstat(fd)
            receipt["owned_artifact"] = {"device": info.st_dev, "inode": info.st_ino}
        finally:
            # Delivery resumes only once a newly created FD is tracked. An
            # interruption between open and return must not hide the artifact.
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        _verify_destination(destination, fd)
        sandbox.confine_writer(fd, max_bytes)
        while receipt["bytes_written"] < len(payload):
            receipt["bytes_written"] += os.write(fd, payload[receipt["bytes_written"]:])
        os.fsync(fd)
        receipt["status"] = "written"
    except KeyboardInterrupt:
        receipt["reason"] = "interrupted"
    except ValueError as error:
        receipt["reason"] = str(error)
    except (OSError, sandbox.SandboxError):
        receipt["reason"] = "writer_refused_or_failed"
    finally:
        if fd is not None:
            try:
                final = _fd_stat(fd)
                receipt["bytes_written"] = final.size
                owned = receipt["owned_artifact"]
                if (final.size != expected_bytes or final.links != 1 or
                        final.mode & 0o777 != 0o600 or
                        owned != {"device": final.device, "inode": final.inode}):
                    receipt["status"] = "partial"
                    receipt.setdefault("reason", "output_postcondition_failed")
            except OSError:
                receipt["status"] = "partial"
                receipt.setdefault("reason", "output_metadata_unavailable")
                receipt["bytes_written_verified"] = False
            try:
                os.close(fd)
            except OSError:
                receipt["status"] = "partial"
                receipt.setdefault("reason", "output_close_failed")
    return receipt


def main(argv=None):
    # Even argument errors/help must not write into redirected regular files.
    try:
        _receipt_streams()
    except (OSError, ValueError):
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    exclusions = parser.add_mutually_exclusive_group(required=True)
    exclusions.add_argument("--exclude-root", action="append")
    exclusions.add_argument("--no-observed-roots", action="store_true",
                            help="Explicit intent-only producer with no observed input roots.")
    parser.add_argument("--expected-bytes", type=int, required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_REPORT_BYTES)
    args = parser.parse_args(argv)
    receipt = persist_report(args.output, args.exclude_root or [], args.expected_bytes,
                             max_bytes=args.max_bytes, no_observed_roots=args.no_observed_roots)
    print(json.dumps(receipt, ensure_ascii=True))
    if receipt.get("reason") == "interrupted":
        return 130
    return 0 if receipt["status"] == "written" else 2


if __name__ == "__main__":
    raise SystemExit(main())
