"""Bounded profile data boundary; only isolated nonroot fixture children parse."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

CORE = Path(__file__).resolve().parents[2] / "isaac-installer/lib/core"


class ProfileReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="isaac-profile-boundary-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.base.chmod(0o755)
        self.data = self.base / "data"
        self.data.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(self.data, 65534, 65534)

    def child(self, source):
        script = self.base / "child.py"
        script.write_text("import sys, os, errno, json, ctypes\n"
                          "from pathlib import Path\n"
                          "sys.path.insert(0, sys.argv[1])\n"
                          "import profile_parser as parser\n"
                          "import preview_sandbox as sandbox\n"
                          "base = Path(sys.argv[2])\n"
                          "assert os.getuid() != 0 and os.geteuid() != 0\n"
                          + textwrap.dedent(source))
        kwargs = {}
        if os.geteuid() == 0:
            kwargs.update(user=65534, group=65534, extra_groups=())
        return subprocess.run(
            ["/usr/bin/python3", "-I", "-B", str(script), str(CORE), str(self.data)],
            cwd=self.data, env={"PATH": "/usr/bin:/bin", "HOME": str(self.data)},
            capture_output=True, text=True, timeout=12, **kwargs)

    def assert_child(self, source):
        result = self.child(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_text_api_matches_legacy_payload_and_workspace_overrides(self):
        self.assert_child('''
            assert callable(getattr(parser, "parse_profile_text", None)), "text API missing"
            raw = 'profile_name: synthetic\\nenabled: true\\ncount: 42\\nworkspace: {layout: named, name: Chosen}\\n'
            path = base / "profile.yaml"
            path.write_text(raw)
            expected = b"\\0".join([b"CFG_PROFILE_NAME", b"synthetic", b"CFG_ENABLED", b"true", b"CFG_COUNT", b"42", b"CFG_WORKSPACE_LAYOUT", b"named", b"CFG_WORKSPACE_NAME", b"Chosen", b""])
            for overrides in (None, {"LAYOUT": "flat", "NAME": ""}):
                assert parser.parse_profile_text(raw, workspace_overrides=overrides) == expected
                assert parser.parse_profile(path, workspace_overrides=overrides) == expected
            try:
                parser.parse_profile_text(raw, workspace_overrides={"LAYOUT": "flat"})
            except ValueError:
                pass
            else:
                raise AssertionError("workspace validation bypassed")
            print("ok")
        ''')


    def test_profile_path_rejects_links_special_files_without_reading(self):
        self.assert_child('''
            real = base / "real.yaml"
            real.write_text("profile_name: fixture\\n")
            link = base / "symbolic.yaml"
            link.symlink_to(real)
            hard = base / "hard.yaml"
            os.link(real, hard)
            directory = base / "directory"
            directory.mkdir()
            (directory / "inside.yaml").write_text("profile_name: fixture\\n")
            parent_link = base / "linked-parent"
            parent_link.symlink_to(directory, target_is_directory=True)
            fifo = base / "fifo.yaml"
            os.mkfifo(fifo)
            for path in (link, hard, real, parent_link / "inside.yaml", directory, fifo):
                try:
                    parser.parse_profile(path)
                except (ValueError, OSError):
                    pass
                else:
                    raise AssertionError("unsafe file admitted: " + path.name)
            print("ok")
        ''')


    def test_input_byte_budget_applies_before_yaml_or_file_content_read(self):
        self.assert_child('''
            limit = 262144
            raw = "value: " + "x" * (limit - len("value: "))
            path = base / "bounded.yaml"
            path.write_text(raw)
            assert parser.parse_profile_text(raw) == parser.parse_profile(path)
            for oversized in (raw + "x", "value: " + "é" * (limit // 2)):
                for value in (oversized, oversized.encode("utf-8")):
                    try:
                        parser.parse_profile_text(value)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("oversized text admitted")
            path.write_text(raw + "x")
            original = os.read
            def no_read(fd, size):
                raise AssertionError("oversized descriptor content was read")
            os.read = no_read
            try:
                parser.parse_profile(path)
            except ValueError:
                pass
            else:
                raise AssertionError("oversized file admitted")
            finally:
                os.read = original
            assert parser.parse_profile_text(b"value: utf8\\n") == b"CFG_VALUE\\0utf8\\0"
            for value in (b"value: \\xff", "value: \\ud800", object()):
                try:
                    parser.parse_profile_text(value)
                except (ValueError, TypeError):
                    pass
                else:
                    raise AssertionError("invalid text admitted")
            print("ok")
        ''')


    def test_file_mount_boundary_and_unavailable_statx_fail_before_read(self):
        # Creating real mounts would require forbidden privileged setup. Inject
        # only the mount-ID metadata; the file open/descriptor/read path is real.
        self.assert_child('''
            path = base / "mount.yaml"
            path.write_text("profile_name: fixture\\n")
            import stat
            parser._mount_id = lambda fd: 2 if stat.S_ISREG(os.fstat(fd).st_mode) else 1
            original = os.read
            def no_read(fd, size):
                raise AssertionError("mount boundary read")
            os.read = no_read
            try:
                parser.read_profile_text(path)
            except (ValueError, OSError):
                pass
            else:
                raise AssertionError("mount boundary admitted")
            os.read = original
            print("ok")
        ''')
        self.assert_child('''
            path = base / "statx.yaml"
            path.write_text("profile_name: fixture\\n")
            libc = ctypes.CDLL(None)
            filters = (sandbox._Filter * 4)(
                sandbox._Filter(0x20, 0, 0, 0),
                sandbox._Filter(0x15, 0, 1, 332),
                sandbox._Filter(0x06, 0, 0, 0x50000 | errno.ENOSYS),
                sandbox._Filter(0x06, 0, 0, 0x7fff0000))
            program = sandbox._Program(4, filters)
            assert libc.prctl(38, 1, 0, 0, 0) == 0
            assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
            try:
                parser.read_profile_text(path)
            except (ValueError, OSError):
                pass
            else:
                raise AssertionError("uninspectable mount admitted")
            print("ok")
        ''')


    def test_changed_or_replaced_descriptor_is_rejected_with_bounded_reads(self):
        self.assert_child('''
            for mode in ("overwrite", "replace", "link", "truncate", "grow"):
                path = base / (mode + ".yaml")
                raw = "value: " + "a" * 70000
                path.write_text(raw)
                original = os.read
                total = 0
                changed = False
                def racing_read(fd, size):
                    global total, changed
                    result = original(fd, size)
                    total += len(result)
                    if not changed:
                        changed = True
                        if mode == "overwrite":
                            path.write_text("value: " + "b" * 70000)
                        elif mode == "replace":
                            replacement = base / "replacement.yaml"
                            replacement.write_text("value: replacement")
                            replacement.replace(path)
                        elif mode == "link":
                            os.link(path, base / "extra-link.yaml")
                        elif mode == "truncate":
                            path.write_text("value: shortened")
                        else:
                            with path.open("a") as stream:
                                stream.write("z" * 300000)
                    return result
                os.read = racing_read
                try:
                    parser.read_profile_text(path)
                except (ValueError, OSError):
                    pass
                else:
                    raise AssertionError("read race admitted: " + mode)
                finally:
                    os.read = original
                assert total <= 262145, total
            print("ok")
        ''')


    def test_aliases_and_duplicate_keys_are_refused_by_both_validation_passes(self):
        self.assert_child('''
            documents = [
                "first: &shared {value: one}\\nsecond: *shared\\n",
                "first: &shared one\\nsecond: *shared\\n",
                "loop: &loop {again: *loop}\\n",
                "defaults: &d {value: one}\\nother: {<<: *d}\\n",
                "value: one\\nvalue: two\\n",
                "nested: {value: one, value: two}\\n",
            ]
            for raw in documents:
                for parse in (parser.parse_profile_text,
                              lambda text: parser.yaml.load(text, Loader=parser.ProfileLoader)):
                    try:
                        parse(raw)
                    except (ValueError, parser.yaml.YAMLError):
                        pass
                    else:
                        raise AssertionError("ambiguous YAML admitted")
            print("ok")
        ''')


    def test_yaml_depth_nodes_and_flattened_expansion_are_bounded(self):
        self.assert_child('''
            documents = [
                "x: {" * 70 + "value: yes" + "}" * 70,
                "".join("key%d: x\\n" % i for i in range(9000)),
                "? " + "a" * 20000 + "\\n: {" + ", ".join("k%d: x" % i for i in range(200)) + "}",
            ]
            for raw in documents:
                assert len(raw.encode()) < 262144
                try:
                    parser.parse_profile_text(raw)
                except ValueError:
                    pass
                else:
                    raise AssertionError("YAML resource budget absent")
            print("ok")
        ''')


    def test_confined_double_validation_uses_one_descriptor_read_and_no_reopen(self):
        self.assert_child('''
            import builtins
            path = base / "profile.yaml"
            path.write_text("profile_name: synthetic\\nworkspace: {layout: named, name: Chosen}\\n")
            sandbox.confine_readonly([str(path)])
            original = os.open
            content_opens = []
            def count_open(path, flags, *args, **kwargs):
                if not flags & os.O_PATH:
                    content_opens.append(path)
                return original(path, flags, *args, **kwargs)
            os.open = count_open
            raw = parser.read_profile_text(path)
            assert len(content_opens) == 1
            def no_reopen(*args, **kwargs):
                raise AssertionError("validator reopened a pathname")
            os.open = builtins.open = no_reopen
            data = parser.yaml.load(raw, Loader=parser.ProfileLoader)
            payload = parser.parse_profile_text(raw)
            assert data["workspace"]["name"] == "Chosen"
            assert b"CFG_WORKSPACE_NAME\\0Chosen\\0" in payload
            assert parser.parse_profile_text(raw) == payload
            print("ok")
        ''')


if __name__ == "__main__":
    unittest.main()
