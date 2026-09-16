"""Sandbox regressions: isolated children and disposable synthetic files only."""
import json
import os
import socket
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

CORE = Path(__file__).resolve().parents[2] / "isaac-installer/lib/core"


class SandboxRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="isaac-sandbox-regression-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.base.chmod(0o755)
        self.allowed = self.base / "selected"
        self.allowed.write_text("profile_name: synthetic\n")
        self.forbidden = self.base / "not-selected"
        self.forbidden.write_text("FAKE_PRIVATE")
        self.forbidden.chmod(0o666)

    def child(self, source, *, root=False, groups=()):
        script = self.base / "child.py"
        script.write_text("import sys, os, ctypes, errno, json, resource, fcntl\n"
                          "sys.path.insert(0, sys.argv[1])\n"
                          "import preview_sandbox as sandbox\n"
                          "allowed, forbidden = sys.argv[2:4]\n" + textwrap.dedent(source))
        kwargs = {}
        if not root and os.geteuid() == 0:
            kwargs.update(user=65534, group=65534, extra_groups=groups)
        return subprocess.run(
            ["/usr/bin/python3", "-I", "-B", str(script), str(CORE),
             str(self.allowed), str(self.forbidden)],
            cwd=self.base, env={"PATH": "/usr/bin:/bin", "HOME": str(self.base)},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12, **kwargs)

    def test_explicit_empty_intent_sandbox_grants_no_file_content(self):
        result = self.child('''
            import socket
            try:
                sandbox.confine_readonly([])
                raise AssertionError("accidental empty input accepted")
            except sandbox.SandboxError:
                pass
            sandbox.confine_readonly([], allow_empty=True)
            for operation in (
                lambda: open(allowed).read(), lambda: open(forbidden).read(),
                lambda: open(sandbox.__file__).read(), lambda: open(forbidden, "w"),
                lambda: socket.socket(),
            ):
                try:
                    operation()
                    raise AssertionError("empty sandbox escaped")
                except OSError:
                    pass
            print("zero_content_grants")
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'zero_content_grants')
        self.assertEqual(self.forbidden.read_text(), 'FAKE_PRIVATE')

    @unittest.skipUnless(os.geteuid() == 0, "supplementary group fixture requires root setup")
    def test_normal_supplementary_groups_preserve_scoped_kernel_restrictions(self):
        # Synthetic group-only files/socket prove DAC access actually exists.
        # No account database or host membership is changed.
        for path in (self.allowed, self.forbidden):
            os.chown(path, 0, 1001)
            path.chmod(0o660)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        endpoint = str(self.base / "group-service.sock")
        listener.bind(endpoint)
        os.chown(endpoint, 0, 1001)
        os.chmod(endpoint, 0o660)
        listener.listen(2)
        result = self.child('''
            import socket
            before = os.getgroups()
            assert before == [27, 44, 1001]
            sandbox.require_unprivileged()
            assert os.getgroups() == before
            assert open(allowed).read() == "profile_name: synthetic\\n"
            assert open(forbidden).read() == "FAKE_PRIVATE"
            with open(forbidden, "r+") as stream:
                assert stream.read() == "FAKE_PRIVATE"
            inherited = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            inherited.connect(os.path.join(os.path.dirname(allowed), "group-service.sock"))
            os.dup2(inherited.fileno(), 1000)
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
            libc = ctypes.CDLL(None, use_errno=True)
            sandbox.confine_readonly([allowed])
            assert open(allowed).read() == "profile_name: synthetic\\n"
            checks = {}
            def connect_existing():
                assert libc.syscall(42, 1000, 0, 0) == -1
                assert ctypes.get_errno() == errno.EPERM
                raise PermissionError()
            for name, operation in [
                ("outside_read", lambda: open(forbidden).read()),
                ("outside_write", lambda: open(forbidden, "w")),
                ("selected_write", lambda: open(allowed, "w")),
                ("unix_socket", lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)),
                ("inet_socket", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)),
                ("connect", connect_existing),
                ("inherited_socket", lambda: os.read(1000, 1)),
                ("socket_rebind", lambda: fcntl.fcntl(1000, fcntl.F_DUPFD, 1)),
                ("setgroups", lambda: os.setgroups([])),
            ]:
                try:
                    operation()
                    checks[name] = "ESCAPED"
                except OSError:
                    checks[name] = "denied"
            print(json.dumps(checks))
        ''', groups=(27, 44, 1001))
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = json.loads(result.stdout)
        self.assertEqual(len(checks), 9)
        self.assertEqual(set(checks.values()), {"denied"})
        self.assertEqual(self.forbidden.read_text(), "FAKE_PRIVATE")
        self.assertEqual(self.allowed.read_text(), "profile_name: synthetic\n")

    def test_optional_file_grants_are_exact_and_missing_files_do_not_broaden(self):
        result = self.child('''
            sandbox.confine_readonly([], optional_files=[allowed, allowed + ".absent"])
            assert open(allowed).read() == "profile_name: synthetic\\n"
            for path, mode in ((forbidden, "r"), (forbidden, "w"), (allowed, "w")):
                try:
                    open(path, mode)
                except OSError:
                    pass
                else:
                    raise AssertionError("optional grants escaped")
            print("exact")
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "exact")
        self.assertEqual(self.forbidden.read_text(), "FAKE_PRIVATE")

    def test_optional_grants_refuse_unsafe_existing_entries_not_just_ignore_them(self):
        directory = self.base / "directory"
        directory.mkdir()
        (directory / "private").write_text("FAKE_PRIVATE")
        symbolic = self.base / "symbolic"
        symbolic.symlink_to(self.allowed)
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "absent")
        hard = self.base / "hard"
        os.link(self.forbidden, hard)
        fifo = self.base / "fifo"
        os.mkfifo(fifo)
        inaccessible = self.base / "inaccessible"
        inaccessible.mkdir(mode=0o700)
        (inaccessible / "file").write_text("FAKE_PRIVATE")
        for path in (directory, symbolic, dangling, hard, fifo,
                     inaccessible / "file", self.base / "missing/../escape"):
            with self.subTest(path=path.name):
                result = self.child(f'''
                    try:
                        sandbox.confine_readonly([allowed], optional_files=[{str(path)!r}])
                    except sandbox.SandboxError:
                        print("refused")
                    else:
                        raise AssertionError("unsafe optional grant admitted")
                ''')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "refused")

    def test_optional_grant_count_is_bounded_before_pinning(self):
        result = self.child('''
            def no_pin(path):
                raise AssertionError("unbounded optional grants reached admission")
            sandbox._pin = no_pin
            try:
                sandbox.confine_readonly([], optional_files=[allowed] * 129)
            except sandbox.SandboxError:
                print("refused")
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "refused")

    def test_high_fd_above_lowered_hard_limit_is_closed(self):
        result = self.child('''
            fd = os.open(forbidden, os.O_RDWR)
            os.dup2(fd, 1000)
            os.close(fd)
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
            sandbox.confine_readonly([allowed])
            assert open(allowed).read() == "profile_name: synthetic\\n"
            try:
                data = os.read(1000, 64)
            except OSError as error:
                assert error.errno == errno.EBADF, error
                print("closed")
            else:
                print("ESCAPED_READ:" + data.decode())
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "closed")
        self.assertEqual(self.forbidden.read_text(), "FAKE_PRIVATE")


    @unittest.skipUnless(os.geteuid() == 0, "identity fixtures require root child setup")
    def test_saved_root_uid_is_refused_before_path_admission(self):
        result = self.child('''
            os.setgroups([])
            os.setresgid(65534, 65534, 65534)
            os.setresuid(65534, 65534, 0)
            identity = os.getresuid()
            pinned = []
            original = sandbox._pin
            def record_pin(path):
                pinned.append(path)
                return original(path)
            sandbox._pin = record_pin
            try:
                sandbox.confine_readonly([allowed])
            except sandbox.SandboxError:
                print(json.dumps({"status": "refused", "uid": identity, "pinned": pinned}))
            else:
                print(json.dumps({"status": "ADMITTED", "uid": identity, "pinned": pinned}))
        ''', root=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"status": "refused", "uid": [65534, 65534, 0], "pinned": []})


    @unittest.skipUnless(os.geteuid() == 0, "identity fixtures require root child setup")
    def test_privileged_or_transitional_groups_are_refused_before_admission(self):
        for gids, groups in [((0, 0, 0), []), ((65534, 0, 0), []),
                             ((65534, 65534, 0), []), ((65534, 65534, 65533), []),
                             ((65534, 65534, 65534), [0])]:
            with self.subTest(gids=gids, groups=groups):
                result = self.child(f'''
                    os.setgroups({groups!r})
                    os.setresgid(*{gids!r})
                    os.setresuid(65534, 65534, 65534)
                    def no_pin(path):
                        raise AssertionError("PATH_ADMITTED")
                    sandbox._pin = no_pin
                    try:
                        sandbox.confine_readonly([allowed])
                    except sandbox.SandboxError:
                        print("refused")
                ''', root=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "refused")


    @unittest.skipUnless(os.geteuid() == 0, "capability fixtures require root child setup")
    def test_retained_capability_sets_are_refused_before_admission(self):
        for mode, bits in [("permitted", (0, 1, 0)), ("effective", (1, 1, 0)),
                           ("inheritable", (0, 0, 1)), ("ambient", (0, 1, 1))]:
            with self.subTest(mode=mode):
                result = self.child(f'''
                    libc = ctypes.CDLL(None, use_errno=True)
                    class Header(ctypes.Structure):
                        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
                    class Data(ctypes.Structure):
                        _fields_ = [("effective", ctypes.c_uint32),
                                    ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]
                    header = Header(0x20080522, 0)
                    assert libc.prctl(8, 1, 0, 0, 0) == 0  # PR_SET_KEEPCAPS
                    os.setgroups([])
                    os.setresgid(65534, 65534, 65534)
                    os.setresuid(65534, 65534, 65534)
                    data = (Data * 2)(Data(*{bits!r}), Data())
                    assert libc.syscall(126, ctypes.byref(header), ctypes.byref(data)) == 0
                    if {mode!r} == "ambient":
                        assert libc.prctl(47, 2, 0, 0, 0) == 0  # raise ambient CAP_CHOWN
                        assert libc.prctl(47, 1, 0, 0, 0) == 1
                    actual = (Data * 2)()
                    assert libc.syscall(125, ctypes.byref(header), ctypes.byref(actual)) == 0
                    assert (actual[0].effective, actual[0].permitted, actual[0].inheritable) == {bits!r}
                    def no_pin(path):
                        raise AssertionError("CAPABILITY_PROCESS_ADMITTED")
                    sandbox._pin = no_pin
                    try:
                        sandbox.confine_readonly([allowed])
                    except sandbox.SandboxError:
                        print("refused")
                ''', root=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "refused")


    @unittest.skipUnless(os.geteuid() == 0, "filesystem identity fixture requires root setup")
    def test_distinct_filesystem_ids_with_empty_caps_are_refused(self):
        for syscall in (122, 123):  # setfsuid, setfsgid
            with self.subTest(syscall=syscall):
                result = self.child(f'''
                    libc = ctypes.CDLL(None, use_errno=True)
                    class Header(ctypes.Structure):
                        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
                    class Data(ctypes.Structure):
                        _fields_ = [("effective", ctypes.c_uint32),
                                    ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]
                    header = Header(0x20080522, 0)
                    assert libc.prctl(8, 1, 0, 0, 0) == 0
                    os.setgroups([])
                    os.setresgid(65534, 65534, 65534)
                    os.setresuid(65534, 65534, 65534)
                    data = (Data * 2)(Data(192, 192, 0), Data())  # SETUID/SETGID only
                    assert libc.syscall(126, ctypes.byref(header), ctypes.byref(data)) == 0
                    assert libc.syscall({syscall}, 0) == 65534
                    data = (Data * 2)()
                    assert libc.syscall(126, ctypes.byref(header), ctypes.byref(data)) == 0
                    assert libc.syscall({syscall}, ctypes.c_uint(0xFFFFFFFF)) == 0
                    assert os.getresuid() == (65534, 65534, 65534)
                    assert os.getresgid() == (65534, 65534, 65534)
                    def no_pin(path):
                        raise AssertionError("FILESYSTEM_PRIVILEGE_ADMITTED")
                    sandbox._pin = no_pin
                    try:
                        sandbox.confine_readonly([allowed])
                    except sandbox.SandboxError:
                        print("refused")
                ''', root=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "refused")


    @unittest.skipUnless(os.geteuid() == 0, "identity fixtures require root child setup")
    def test_preview_checks_saved_identity_before_argument_admission(self):
        result = self.child('''
            import safe_preview
            os.setgroups([])
            os.setresgid(65534, 65534, 65534)
            os.setresuid(65534, 65534, 0)
            def no_arguments(argv):
                raise AssertionError("ARGUMENTS_ADMITTED")
            safe_preview._arguments = no_arguments
            print(safe_preview.main(["install", "--dry-run", "--config", allowed]))
        ''', root=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "77")
        self.assertNotIn("Traceback", result.stderr)


    def test_high_fd_cannot_be_rebound_to_writable_stdout(self):
        result = self.child('''
            fd = os.open(forbidden, os.O_RDWR)
            os.dup2(fd, 1000)
            os.close(fd)
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
            sandbox.confine_readonly([allowed])
            os.close(1)
            checks = {}
            for name, operation in [
                ("fcntl_rebind", lambda: fcntl.fcntl(1000, fcntl.F_DUPFD, 1)),
                ("dup2_rebind", lambda: os.dup2(1000, 1)),
                ("high_fd_write", lambda: os.write(1000, b"MUTATED_DATA")),
                ("outside_read", lambda: open(forbidden).read()),
                ("outside_write", lambda: open(forbidden, "w")),
            ]:
                try:
                    operation()
                    checks[name] = "ESCAPED"
                except OSError:
                    checks[name] = "denied"
            try:
                os.write(1, b"MUTATED_DATA")
                checks["stdout_write"] = "ESCAPED"
            except OSError:
                checks["stdout_write"] = "denied"
            os.write(2, json.dumps(checks).encode())
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stderr).values()), {"denied"})
        self.assertEqual(self.forbidden.read_text(), "FAKE_PRIVATE")

    def test_required_syscall_failure_refuses_before_path_admission(self):
        # Real outer seccomp filters simulate unsupported/blocked kernel calls.
        for syscall in (436, 125, 122, 123):
            with self.subTest(syscall=syscall):
                result = self.child(f'''
                    libc = ctypes.CDLL(None)
                    filters = (sandbox._Filter * 4)(
                        sandbox._Filter(0x20, 0, 0, 0),
                        sandbox._Filter(0x15, 0, 1, {syscall}),
                        sandbox._Filter(0x06, 0, 0, 0x50000 | errno.ENOSYS),
                        sandbox._Filter(0x06, 0, 0, 0x7fff0000))
                    program = sandbox._Program(4, filters)
                    assert libc.prctl(38, 1, 0, 0, 0) == 0
                    assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
                    def no_pin(path):
                        raise AssertionError("PATH_ADMITTED_AFTER_SYSCALL_FAILURE")
                    sandbox._pin = no_pin
                    try:
                        sandbox.confine_readonly([allowed])
                    except sandbox.SandboxError:
                        print("refused")
                ''')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "refused")

    @unittest.skipUnless(os.geteuid() == 0, "identity fixtures require root child setup")
    def test_healthy_unprivileged_process_reads_selected_input(self):
        for groups in ([], [65534]):
            with self.subTest(groups=groups):
                result = self.child(f'''
                    os.setgroups({groups!r})
                    os.setresgid(65534, 65534, 65534)
                    os.setresuid(65534, 65534, 65534)
                    sandbox.confine_readonly([allowed])
                    print(open(allowed).read(), end="")
                ''', root=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, self.allowed.read_text())


    def test_stdin_cannot_survive_a_denied_close_syscall(self):
        result = self.child('''
            fd = os.open(forbidden, os.O_RDONLY)
            os.dup2(fd, 0)
            os.close(fd)
            libc = ctypes.CDLL(None)
            filters = (sandbox._Filter * 6)(
                sandbox._Filter(0x20, 0, 0, 0),
                sandbox._Filter(0x15, 0, 3, 3),  # close syscall
                sandbox._Filter(0x20, 0, 0, 16),
                sandbox._Filter(0x15, 0, 1, 0),  # fd == 0
                sandbox._Filter(0x06, 0, 0, 0x50000 | errno.EPERM),
                sandbox._Filter(0x06, 0, 0, 0x7fff0000))
            program = sandbox._Program(6, filters)
            assert libc.prctl(38, 1, 0, 0, 0) == 0
            assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
            try:
                sandbox.confine_readonly([allowed])
            except (sandbox.SandboxError, OSError):
                print("refused")
            else:
                try:
                    data = os.read(0, 64)
                except OSError:
                    print("closed")
                else:
                    print("ESCAPED_READ:" + data.decode())
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(result.stdout.strip(), {"refused", "closed"})


if __name__ == "__main__":
    unittest.main()
