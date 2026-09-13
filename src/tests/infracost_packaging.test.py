"""Optional Infracost installer contract; synthetic archives, no network."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/install_infracost.py"


class PackagingTests(unittest.TestCase):
    def load_installer(self):
        self.assertTrue(SCRIPT.is_file(), "Optional pinned installer is missing")
        spec = importlib.util.spec_from_file_location("infracost_installer", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_runtime_manifest_pins_minimal_gcp_bundle(self):
        path = ROOT / "configs/cost/runtime.json"
        self.assertTrue(path.is_file(), "Pinned plugin manifest is missing")
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["cli_version"], "2.16.3")
        self.assertEqual(manifest["plugin_directory"], "/opt/isaac-infracost/plugins")
        self.assertEqual({p["name"]: p["version"] for p in manifest["plugins"]}, {
            "infracost-parser-terraform": "0.0.71",
            "infracost-parser-terraform-plan": "0.0.20",
            "infracost-provider-google": "0.0.12",
        })
        for plugin in manifest["plugins"]:
            self.assertEqual(set(plugin["platforms"]), {"linux-amd64", "linux-arm64"})
            for platform, pin in plugin["platforms"].items():
                arch = platform.removeprefix("linux-")
                self.assertEqual(pin["url"],
                    f"https://releases.infracost.io/{plugin['name']}/linux/{arch}/v{plugin['version']}/data.tar.gz")
                self.assertEqual(pin["checksum_url"], pin["url"] + ".sha256")
                for key in ("archive_sha256", "binary_sha256"):
                    self.assertRegex(pin[key], r"^[0-9a-f]{64}$")

    def test_plugin_disabled_and_unsupported_settings_are_side_effect_free(self):
        installer = self.load_installer()
        self.assertTrue(hasattr(installer, "install_plugins"), "Plugin installer is missing")
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "absent" / "plugins"
            with mock.patch.object(installer, "urlopen", side_effect=AssertionError("network")):
                installer.install_plugins("0", "unsupported", dest)
                for enabled, arch in [("true", "amd64"), ("1", "mips")]:
                    with self.assertRaises(ValueError):
                        installer.install_plugins(enabled, arch, dest)
            self.assertFalse(dest.parent.exists())

    def plugin_fixture(self):
        manifest = json.loads((ROOT / "configs/cost/runtime.json").read_text())
        archives = {}
        for plugin in manifest["plugins"]:
            data = self.archive(plugin["name"])
            for pin in plugin["platforms"].values():
                pin["archive_sha256"] = hashlib.sha256(data).hexdigest()
                pin["binary_sha256"] = hashlib.sha256(b"synthetic-test-executable").hexdigest()
                archives[pin["url"]] = data
        return manifest, archives

    def test_plugins_install_pinned_flat_bundle_for_both_architectures(self):
        installer = self.load_installer()
        manifest, archives = self.plugin_fixture()
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as root:
                manifest_path = Path(root) / "runtime.json"
                manifest_path.write_text(json.dumps(manifest))
                dest = Path(root) / "plugins"
                with mock.patch.object(installer, "urlopen", side_effect=lambda url, **kw: io.BytesIO(archives[url])) as request:
                    installer.install_plugins("1", arch, dest, manifest_path=manifest_path)
                self.assertEqual({p.name for p in dest.iterdir()}, {p["name"] for p in manifest["plugins"]})
                self.assertEqual(request.call_count, 3)
                for plugin in manifest["plugins"]:
                    path = dest / plugin["name"]
                    self.assertEqual(path.read_bytes(), b"synthetic-test-executable")
                    self.assertEqual(path.stat().st_mode & 0o777, 0o755)
                    request.assert_any_call(plugin["platforms"][f"linux-{arch}"]["url"], timeout=60)

    def test_plugin_checksum_failure_does_not_publish_partial_bundle(self):
        installer = self.load_installer()
        for field in ("archive_sha256", "binary_sha256"):
            manifest, archives = self.plugin_fixture()
            manifest["plugins"][-1]["platforms"]["linux-amd64"][field] = "0" * 64
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                mp = Path(root) / "runtime.json"
                mp.write_text(json.dumps(manifest))
                dest = Path(root) / "plugins"
                with mock.patch.object(installer, "urlopen", side_effect=lambda url, **kw: io.BytesIO(archives[url])):
                    with self.assertRaisesRegex(ValueError, "checksum"):
                        installer.install_plugins("1", "amd64", dest, manifest_path=mp)
                self.assertFalse(dest.exists())
                self.assertEqual({p.name for p in Path(root).iterdir()}, {"runtime.json"})

    def test_plugin_install_refuses_existing_or_symlink_destination_before_network(self):
        installer = self.load_installer()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            existing = root / "existing"
            existing.mkdir()
            (existing / "original").write_bytes(b"original")
            alias = root / "alias"
            alias.symlink_to(existing, target_is_directory=True)
            with mock.patch.object(installer, "urlopen", side_effect=AssertionError("network")):
                for dest in (existing, alias, alias / "plugins"):
                    with self.subTest(dest=dest), self.assertRaises(ValueError):
                        installer.install_plugins("1", "amd64", dest)
            self.assertEqual((existing / "original").read_bytes(), b"original")
            self.assertEqual({p.name for p in existing.iterdir()}, {"original"})

    def test_invalid_manifest_is_rejected_before_network(self):
        installer = self.load_installer()
        for mutation in ("cli", "schema", "name", "url", "hash", "missing"):
            manifest, _ = self.plugin_fixture()
            if mutation == "cli":
                manifest["cli_version"] = "0.10.45"
            elif mutation == "schema":
                manifest["schema_version"] = 999
            elif mutation == "name":
                manifest["plugins"][0]["name"] = "../escape"
            elif mutation == "url":
                manifest["plugins"][0]["platforms"]["linux-amd64"]["url"] = "https://example.com/unpinned"
            elif mutation == "hash":
                manifest["plugins"][0]["platforms"]["linux-amd64"]["binary_sha256"] = "bad"
            else:
                manifest["plugins"].pop()
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                mp = Path(root) / "runtime.json"
                mp.write_text(json.dumps(manifest))
                with mock.patch.object(installer, "urlopen", side_effect=AssertionError("network")):
                    with self.assertRaisesRegex(ValueError, "manifest"):
                        installer.install_plugins("1", "amd64", Path(root) / "plugins", manifest_path=mp)

    def test_plugin_archive_path_and_link_rejected(self):
        installer = self.load_installer()
        for name, symlink in [("../escape", False), ("infracost-parser-terraform", True)]:
            manifest, archives = self.plugin_fixture()
            bad = self.archive(name, symlink)
            pin = manifest["plugins"][0]["platforms"]["linux-amd64"]
            archives[pin["url"]] = bad
            pin["archive_sha256"] = hashlib.sha256(bad).hexdigest()
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                mp = Path(root) / "runtime.json"
                mp.write_text(json.dumps(manifest))
                with mock.patch.object(installer, "urlopen", side_effect=lambda url, **kw: io.BytesIO(archives[url])):
                    with self.assertRaisesRegex(ValueError, "archive"):
                        installer.install_plugins("1", "amd64", Path(root) / "plugins", manifest_path=mp)
                self.assertFalse((Path(root) / "plugins").exists())

    def test_disabled_install_has_no_network_or_filesystem_effects(self):
        installer = self.load_installer()
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "absent" / "infracost"
            with mock.patch.object(installer, "urlopen", side_effect=AssertionError("network")):
                installer.install("0", "amd64", destination)
            self.assertFalse(destination.parent.exists())

    def archive(self, name="infracost", symlink=False):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            member = tarfile.TarInfo(name)
            content = b"synthetic-test-executable"
            member.size = len(content)
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "/outside"
                member.size = 0
            archive.addfile(member, None if symlink else io.BytesIO(content))
        return stream.getvalue()

    def test_enabled_install_verifies_pin_and_writes_executable(self):
        installer = self.load_installer()
        data = self.archive()
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "bin" / "infracost"
            with mock.patch.dict(installer.SHA256, amd64=hashlib.sha256(data).hexdigest()):
                with mock.patch.object(installer, "urlopen", return_value=io.BytesIO(data)) as request:
                    installer.install("1", "amd64", dest)
            self.assertEqual(dest.read_bytes(), b"synthetic-test-executable")
            self.assertEqual(dest.stat().st_mode & 0o777, 0o755)
            self.assertIn("/v2.16.3/infracost-linux-amd64.tar.gz", request.call_args.args[0])

    def test_checksum_failure_preserves_existing_binary(self):
        installer = self.load_installer()
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "infracost"
            dest.write_bytes(b"original")
            with mock.patch.object(installer, "urlopen", return_value=io.BytesIO(self.archive())):
                with self.assertRaisesRegex(ValueError, "checksum"):
                    installer.install("1", "amd64", dest)
            self.assertEqual(dest.read_bytes(), b"original")

    def test_unsafe_archive_rejected_even_when_checksum_matches(self):
        installer = self.load_installer()
        for name, symlink in [("../infracost", False), ("infracost", True)]:
            data = self.archive(name, symlink)
            with self.subTest(name=name, symlink=symlink), tempfile.TemporaryDirectory() as root:
                with mock.patch.dict(installer.SHA256, amd64=hashlib.sha256(data).hexdigest()):
                    with mock.patch.object(installer, "urlopen", return_value=io.BytesIO(data)):
                        with self.assertRaisesRegex(ValueError, "archive"):
                            installer.install("1", "amd64", Path(root) / "infracost")
                self.assertEqual(list(Path(root).iterdir()), [])

    def test_invalid_build_settings_fail_before_network(self):
        installer = self.load_installer()
        with mock.patch.object(installer, "urlopen", side_effect=AssertionError("network")):
            for enabled, architecture in [("true", "amd64"), ("1", "mips")]:
                with self.assertRaises(ValueError):
                    installer.install(enabled, architecture, Path("/unused"))

    def test_command_installs_plugins_only_when_explicitly_requested(self):
        installer = self.load_installer()
        for plugins in ("0", "1"):
            with self.subTest(plugins=plugins):
                argv = [str(SCRIPT), "--enabled", "1", "--architecture", "amd64",
                        "--destination", "/isolated/bin/infracost", "--with-plugins", plugins,
                        "--plugin-destination", "/isolated/plugins"]
                with mock.patch("sys.argv", argv), mock.patch.object(installer, "install") as core, mock.patch.object(installer, "install_plugins") as bundle:
                    installer.main()
                core.assert_called_once_with("1", "amd64", "/isolated/bin/infracost")
                bundle.assert_called_once_with(plugins, "amd64", "/isolated/plugins")

    def test_disabled_command_cannot_install_requested_plugins(self):
        installer = self.load_installer()
        argv = [str(SCRIPT), "--enabled", "0", "--architecture", "amd64",
                "--with-plugins", "1"]
        with mock.patch("sys.argv", argv), mock.patch.object(installer, "urlopen", side_effect=AssertionError("network")):
            with mock.patch.object(installer, "write_binary", side_effect=AssertionError("filesystem")):
                installer.main()

    def test_command_plugin_failure_is_nonzero_and_sanitized(self):
        installer = self.load_installer()
        argv = [str(SCRIPT), "--enabled", "1", "--architecture", "amd64",
                "--with-plugins", "1"]
        stderr = io.StringIO()
        with mock.patch("sys.argv", argv), mock.patch("sys.stderr", stderr):
            with mock.patch.object(installer, "install"), mock.patch.object(installer, "install_plugins", side_effect=ValueError("SYNTHETIC_PRIVATE_DIAGNOSTIC")):
                with self.assertRaises(SystemExit) as caught:
                    installer.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", stderr.getvalue())
        self.assertIn("Pinned Infracost installation failed", stderr.getvalue())

    def test_docker_opt_in_and_no_credential_build_arguments(self):
        text = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WITH_INFRACOST=0", text)
        self.assertIn("--with-plugins \"$WITH_INFRACOST\"", text)
        self.assertIn("COPY configs/cost/runtime.json /tmp/isaac-build/configs/cost/runtime.json", text)
        self.assertIn("ENV INFRACOST_CLI_PLUGIN_DIR=/opt/isaac-infracost/plugins", text)
        self.assertIn("ENV INFRACOST_CLI_PLUGIN_AUTO_UPDATE=false", text)
        self.assertIn("scripts/install_infracost.py", text)
        self.assertNotIn("ARG INFRACOST_API_KEY", text)
        self.assertNotIn("ARG INFRACOST_CLI_AUTHENTICATION_TOKEN", text)


if __name__ == "__main__":
    unittest.main()
