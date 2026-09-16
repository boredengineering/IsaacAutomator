"""Selected report persistence; all outputs are disposable synthetic fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from typing import Any

CORE = Path(__file__).resolve().parents[2] / "isaac-installer/lib/core"
WRITER = CORE / "report_writer.py"


class ReportWriterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="isaac-report-writer-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.base.chmod(0o755)
        self.observed = self.base / "observed"
        self.observed.mkdir()
        self.canary = self.observed / "private"
        self.canary.write_bytes(b"SYNTHETIC_UNCHANGED")
        self.canary.chmod(0o666)
        self.output_dir = self.base / "reports"
        self.output_dir.mkdir()
        if os.geteuid() == 0:
            os.chown(self.output_dir, 65534, 65534)
        self.output = self.output_dir / "candidate.yaml"

    def options(self):
        options: dict[str, Any] = dict(cwd=self.base, env={"PATH": "/usr/bin:/bin", "HOME": str(self.base)},
                       capture_output=True, timeout=12)
        if os.geteuid() == 0:
            options.update(user=65534, group=65534, extra_groups=(27, 44, 1001))
        return options

    def cli(self, payload=b"kind: synthetic\n", *, output=None, roots=None, expected=None, extra=()):
        args = ["/usr/bin/python3", "-I", "-B", str(WRITER), "--output", str(output or self.output),
                "--expected-bytes", str(len(payload) if expected is None else expected)]
        for root in roots if roots is not None else [self.observed]:
            args.extend(("--exclude-root", str(root)))
        return subprocess.run([*args, *extra], input=payload, **self.options())

    def child(self, source, payload=b"kind: synthetic\n"):
        script = self.base / "child.py"
        script.write_text("import sys, os, json, ctypes, errno, resource, socket, fcntl\n"
                          "sys.path.insert(0, sys.argv[1])\n"
                          "import preview_sandbox as sandbox\n"
                          "import report_writer as writer\n"
                          "output, observed, canary = sys.argv[2:]\n" + textwrap.dedent(source))
        return subprocess.run(["/usr/bin/python3", "-I", "-B", str(script), str(CORE),
                               str(self.output), str(self.observed), str(self.canary)],
                              input=payload, **self.options())

    def test_explicit_new_report_has_exact_bytes_private_mode_and_receipt(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), b"kind: synthetic\n")
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "written")
        self.assertEqual(receipt["bytes_written"], len(b"kind: synthetic\n"))
        self.assertEqual(receipt["owned_artifact"]["inode"], self.output.stat().st_ino)
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_empty_roots_require_explicit_exclusive_writer_flag(self):
        for roots, extra in (([], ()), ([self.observed], ('--no-observed-roots',)),
                             ([], ('--no-observed-roots=true',))):
            with self.subTest(roots=roots, extra=extra):
                result = self.cli(roots=roots, extra=extra)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.output.exists())
        result = self.cli(roots=[], extra=('--no-observed-roots',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'written')
        self.assertEqual(self.output.read_bytes(), b'kind: synthetic\n')
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.canary.read_bytes(), b'SYNTHETIC_UNCHANGED')

    def test_kernel_filesize_limit_enforces_selected_budget(self):
        result = self.child('''
            original = sandbox.confine_writer
            def bounded(fd, max_bytes):
                original(fd, max_bytes)
                assert os.write(fd, b"x" * 100) == max_bytes
                try:
                    os.write(fd, b"extra")
                except OSError as error:
                    assert error.errno == errno.EFBIG
                else:
                    raise AssertionError("kernel byte limit escaped")
                raise OSError(errno.EFBIG, "intentional_negative_control")
            sandbox.confine_writer = bounded
            print(json.dumps(writer.persist_report(output, [observed], 16, max_bytes=16)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "partial")
        self.assertEqual(self.output.read_bytes(), b"x" * 16)

    def test_confinement_failure_leaves_empty_identified_artifact_not_report_bytes(self):
        for syscall in (436, 444):
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
                output += str({syscall})
                print(json.dumps(writer.persist_report(output, [observed], 16)))
            ''')
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "partial")
            output = Path(str(self.output) + str(syscall))
            self.assertEqual(output.read_bytes(), b"")
            self.assertEqual(receipt["owned_artifact"]["inode"], output.stat().st_ino)

    def test_yaml_size_cap_and_permission_refusals_create_no_file(self):
        result = self.cli(b"x" * 131073, extra=("--max-bytes", "131072"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.output.exists())
        self.output_dir.chmod(0o500)
        result = self.cli()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.output.exists())
        self.output_dir.chmod(0o755)

    def test_main_refuses_regular_stdout_without_writing_even_a_receipt(self):
        result = self.child('''
            fd = os.open(canary, os.O_WRONLY)
            os.dup2(fd, 1)
            os.close(fd)
            assert writer.main(["--output", output, "--exclude-root", observed,
                                "--expected-bytes", "16"]) == 2
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_sigterm_at_creation_boundary_retains_owned_identity(self):
        result = self.child('''
            import signal
            original = writer._create_output
            def interrupted(destination, roots):
                fd = original(destination, roots)
                os.kill(os.getpid(), signal.SIGTERM)
                return fd
            writer._create_output = interrupted
            print(json.dumps(writer.persist_report(output, [observed], 16)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["reason"], "interrupted")
        self.assertEqual(receipt["owned_artifact"]["inode"], self.output.stat().st_ino)
        self.assertEqual(self.output.read_bytes(), b"")

    def test_group_or_world_writable_destination_parent_refuses_before_creation(self):
        for mode in (0o775, 0o777):
            self.output_dir.chmod(mode)
            result = self.cli()
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "refused")
            self.assertFalse(self.output.exists())

    def test_failed_final_fd_metadata_or_close_never_claims_written(self):
        for failure in ("metadata", "size", "close"):
            result = self.child(f'''
                if {failure!r} == "metadata":
                    libc = ctypes.CDLL(None)
                    filters = (sandbox._Filter * 4)(
                        sandbox._Filter(0x20, 0, 0, 0),
                        sandbox._Filter(0x15, 0, 1, 5),
                        sandbox._Filter(0x06, 0, 0, 0x50000 | errno.EIO),
                        sandbox._Filter(0x06, 0, 0, 0x7fff0000))
                    program = sandbox._Program(4, filters)
                    assert libc.prctl(38, 1, 0, 0, 0) == 0
                    assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
                elif {failure!r} == "size":
                    real_fsync = os.fsync
                    def inconsistent(fd):
                        os.write(fd, b"extra")
                        real_fsync(fd)
                    os.fsync = inconsistent
                else:
                    real_confine = sandbox.confine_writer
                    def close_failure(fd, max_bytes):
                        real_confine(fd, max_bytes)
                        real_close = os.close
                        def fail_close(number):
                            if number == fd:
                                raise OSError(errno.EIO, "SYNTHETIC_CLOSE_ERROR")
                            real_close(number)
                        os.close = fail_close
                    sandbox.confine_writer = close_failure
                output += {failure!r}
                print(json.dumps(writer.persist_report(output, [observed], 16)))
            ''')
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "partial")
            self.assertIsNotNone(receipt["owned_artifact"])
            self.assertNotIn(b"Traceback", result.stdout + result.stderr)

    def test_collisions_never_overwrite_existing_file_link_fifo_or_directory(self):
        regular = self.output_dir / "regular"
        regular.write_bytes(b"USER_DATA")
        regular.chmod(0o666)
        hard = self.output_dir / "hard"
        os.link(regular, hard)
        symbolic = self.output_dir / "symbolic"
        symbolic.symlink_to(regular)
        dangling = self.output_dir / "dangling"
        dangling.symlink_to(self.output_dir / "missing-target")
        fifo = self.output_dir / "fifo"
        os.mkfifo(fifo)
        directory = self.output_dir / "directory"
        directory.mkdir()
        for output in (regular, hard, symbolic, dangling, fifo, directory):
            before = output.lstat()
            result = self.cli(output=output)
            self.assertEqual(result.returncode, 2, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "refused")
            self.assertIsNone(receipt["owned_artifact"])
            after = output.lstat()
            self.assertEqual((before.st_ino, before.st_mode, before.st_nlink, before.st_size),
                             (after.st_ino, after.st_mode, after.st_nlink, after.st_size))
        self.assertEqual(regular.read_bytes(), b"USER_DATA")
        self.assertFalse((self.output_dir / "missing-target").exists())

    def test_kernel_and_synthetic_mount_refusals_have_no_creation_fallback(self):
        # No mount is performed and no host mount metadata is read. An outer
        # kernel filter supplies EXDEV/ENOSYS as real openat2 syscall failures.
        for error in (18, 38):
            result = self.child(f'''
                libc = ctypes.CDLL(None)
                filters = (sandbox._Filter * 4)(
                    sandbox._Filter(0x20, 0, 0, 0),
                    sandbox._Filter(0x15, 0, 1, 437),
                    sandbox._Filter(0x06, 0, 0, 0x50000 | {error}),
                    sandbox._Filter(0x06, 0, 0, 0x7fff0000))
                program = sandbox._Program(4, filters)
                assert libc.prctl(38, 1, 0, 0, 0) == 0
                assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
                print(json.dumps(writer.persist_report(output, [observed], 16)))
            ''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "refused")
            self.assertFalse(self.output.exists())
        result = self.child('''
            actual_cdll = ctypes.CDLL
            class CheckedLibc:
                def __init__(self):
                    self.actual = actual_cdll(None, use_errno=True)
                def syscall(self, number, *args):
                    if number == 437:
                        how = ctypes.cast(args[2], ctypes.POINTER(writer._OpenHow)).contents
                        assert how.resolve & 1, "same-device bind alias not refused"
                        assert how.resolve & 4, "symlinks not refused"
                        assert how.resolve & 8, "relative escape not refused"
                        ctypes.set_errno(errno.EXDEV)
                        return -1
                    return self.actual.syscall(number, *args)
            writer.ctypes.CDLL = lambda *args, **kwargs: CheckedLibc()
            print(json.dumps(writer.persist_report(output, [observed], 16)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "refused")
        self.assertFalse(self.output.exists())

    def test_disk_full_and_fsync_failure_preserve_only_owned_partial_artifact(self):
        for operation in ("write", "fsync"):
            output = self.output_dir / operation
            result = self.child(f'''
                output = os.path.join(os.path.dirname(output), {operation!r})
                real = getattr(os, {operation!r})
                def failed(fd, *args):
                    if fd > 2:
                        if {operation!r} == "write":
                            real(fd, args[0][:3])
                        raise OSError(errno.ENOSPC, "SYNTHETIC_FAULT_NO_PRIVATE_DETAIL")
                    return real(fd, *args)
                setattr(os, {operation!r}, failed)
                print(json.dumps(writer.persist_report(output, [observed], 16)))
            ''')
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "partial")
            self.assertEqual(receipt["owned_artifact"]["inode"], output.stat().st_ino)
            self.assertEqual(receipt["bytes_written"], output.stat().st_size)
            self.assertEqual(output.read_bytes(), b"kin" if operation == "write" else b"kind: synthetic\n")
            self.assertNotIn(b"SYNTHETIC_FAULT_NO_PRIVATE_DETAIL", result.stdout + result.stderr)
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_maximum_admitted_bytes_succeed_and_exact_file_exclusion_is_supported(self):
        payload = b"x" * (8 * 1024 * 1024)
        result = self.cli(payload, roots=[self.canary])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), payload)
        self.assertEqual(json.loads(result.stdout)["bytes_written"], len(payload))

    def test_explicit_creation_is_mode0600_even_with_restrictive_inherited_umask(self):
        result = self.child('''
            os.umask(0o777)
            print(json.dumps(writer.persist_report(output, [observed], 16)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "written")
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.read_bytes(), b"kind: synthetic\n")

    def test_parent_swap_after_create_never_writes_report_bytes_through_alias(self):
        if os.geteuid() == 0:
            os.chown(self.base, 65534, 65534)
        result = self.child('''
            real_create = writer._create_output
            def swapped(destination, roots):
                fd = real_create(destination, roots)
                parent = os.path.dirname(destination)
                os.rename(parent, parent + ".moved")
                os.symlink(observed, parent)
                return fd
            writer._create_output = swapped
            print(json.dumps(writer.persist_report(output, [observed], 16)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "partial")
        moved = self.base / "reports.moved/candidate.yaml"
        self.assertEqual(moved.read_bytes(), b"")
        self.assertEqual(receipt["owned_artifact"]["inode"], moved.stat().st_ino)
        self.assertFalse((self.observed / "candidate.yaml").exists())
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_actual_sigterm_during_write_reports_owned_partial_without_cleanup(self):
        script = self.base / "interrupted.py"
        script.write_text(textwrap.dedent(f'''
            import os, sys, json
            sys.path.insert(0, {str(CORE)!r})
            import report_writer as writer
            real_write = os.write
            def interrupted(fd, data):
                if fd > 2:
                    real_write(fd, data[:3])
                    real_write(1, b"READY\\n")
                    while True:
                        pass
                return real_write(fd, data)
            os.write = interrupted
            raise SystemExit(writer.main(["--output", {str(self.output)!r}, "--exclude-root",
                                          {str(self.observed)!r}, "--expected-bytes", "16"]))
        '''))
        options = self.options()
        options.pop("capture_output")
        options.pop("timeout")
        process = subprocess.Popen(["/usr/bin/python3", "-I", "-B", str(script)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, **options)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        process.stdin.write(b"kind: synthetic\n")
        process.stdin.close()
        process.stdin = None
        self.assertEqual(process.stdout.readline(), b"READY\n")
        process.terminate()
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 130, stderr)
        receipt = json.loads(stdout)
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["reason"], "interrupted")
        self.assertEqual(receipt["bytes_written"], 3)
        self.assertEqual(receipt["owned_artifact"]["inode"], self.output.stat().st_ino)
        self.assertEqual(self.output.read_bytes(), b"kin")
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_selected_paths_refuse_observed_descendants_aliases_and_unsafe_types(self):
        self.observed.chmod(0o777)
        child = self.observed / "child"
        child.mkdir(mode=0o777)
        child.chmod(0o777)
        alias = self.output_dir / "alias"
        alias.symlink_to(self.observed, target_is_directory=True)
        fifo = self.base / "fifo"
        os.mkfifo(fifo)
        symbolic = self.base / "symbolic"
        symbolic.symlink_to(self.observed)
        missing = self.base / "absent"
        hard = self.base / "hard"
        os.link(self.canary, hard)
        cases = [(self.observed / "report", [self.observed]),
                 (child / "report", [self.observed]),
                 (alias / "report", [self.observed]),
                 (self.output, [symbolic]), (self.output, [fifo]),
                 (self.output, [hard]), (self.output, [missing]),
                 (self.output, []), (self.output, [self.observed] * 129),
                 (self.output_dir / "missing/report", [self.observed]),
                 (str(self.output_dir) + "/../reports/new", [self.observed]),
                 ("relative.yaml", [self.observed])]
        for output, roots in cases:
            with self.subTest(output=output, root_count=len(roots)):
                result = self.cli(output=output, roots=roots)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(Path(output).exists())
                self.assertNotIn(b"Traceback", result.stderr)
        self.assertFalse((self.output_dir / "missing").exists())
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_preflight_refuses_root_or_nonpipe_io_without_creating_output(self):
        result = self.child('''
            regular = os.open(canary, os.O_RDONLY)
            os.dup2(regular, 0)
            os.close(regular)
            print(json.dumps(writer.persist_report(output, [observed], 19)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "refused")
        self.assertFalse(self.output.exists())
        for number in (1, 2):
            result = self.child(f'''
                other = 2 if {number} == 1 else 1
                fd = os.open(canary, os.O_WRONLY)
                os.dup2(fd, {number})
                os.close(fd)
                receipt = writer.persist_report(output, [observed], 16)
                os.write(other, json.dumps(receipt).encode())
            ''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stderr if number == 1 else result.stdout)["status"], "refused")
            self.assertFalse(self.output.exists())
        if os.geteuid() == 0:
            options = self.options()
            for key in ("user", "group", "extra_groups"):
                options.pop(key)
            result = subprocess.run(["/usr/bin/python3", "-I", "-B", str(WRITER),
                                     "--output", str(self.output), "--exclude-root", str(self.observed),
                                     "--expected-bytes", "3"], input=b"abc", **options)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(self.output.exists())
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")

    def test_invalid_or_interrupted_payload_refuses_before_creation(self):
        for payload, expected, extra in [(b"abc", 4, ()), (b"abcd", 3, ()),
                                         (b"", 0, ()), (b"abc", 3, ("--max-bytes", "2")),
                                         (b"abc", 3, ("--max-bytes", str(8 * 1024 * 1024 + 1))),
                                         (b"x" * 1048577, 1048576, ())]:
            with self.subTest(expected=expected, extra=extra):
                result = self.cli(payload, expected=expected, extra=extra)
                self.assertEqual(result.returncode, 2, result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["status"], "refused")
                self.assertIsNone(receipt["owned_artifact"])
                self.assertFalse(self.output.exists())

    def test_writer_confinement_denies_all_paths_network_exec_and_inherited_fds(self):
        result = self.child('''
            real_confine = getattr(sandbox, "confine_writer", None)
            assert real_confine is not None, "dedicated writer confinement missing"
            def checked(fd, max_bytes):
                inherited = os.open(canary, os.O_RDWR)
                os.dup2(inherited, 1000)
                os.close(inherited)
                resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
                real_confine(fd, max_bytes)
                checks = [
                    lambda: open(canary, "wb"),
                    lambda: open(canary, "rb").read(),
                    lambda: open(output + ".outside", "wb"),
                    lambda: os.write(1000, b"ESCAPED"),
                    lambda: os.read(1000, 1),
                    lambda: os.dup2(1000, 1),
                    lambda: fcntl.fcntl(1000, fcntl.F_DUPFD, 1),
                    lambda: socket.socket(),
                    lambda: os.execve("/not-executed", ["fixture-helper"], {}),
                    lambda: os.chmod(output, 0o777),
                    lambda: os.unlink(output),
                    lambda: os.mkdir(output + ".dir"),
                    lambda: os.open(output, os.O_WRONLY),
                ]
                for operation in checks:
                    try:
                        operation()
                    except OSError:
                        pass
                    else:
                        raise AssertionError("confinement escape")
            sandbox.confine_writer = checked
            print(json.dumps(writer.persist_report(output, [observed], 16)))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "written")
        self.assertEqual(self.output.read_bytes(), b"kind: synthetic\n")
        self.assertEqual(self.canary.read_bytes(), b"SYNTHETIC_UNCHANGED")
        self.assertEqual(list(self.output_dir.iterdir()), [self.output])


if __name__ == "__main__":
    unittest.main()
