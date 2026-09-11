"""Offline synthetic recovery metadata tests; no profiles/state/cloud reads."""
import json
import unittest
from dataclasses import FrozenInstanceError
from src.python.terraform_backend import BackendSpec
from src.python import deployment_manifest as dm


def spec():
    return BackendSpec.from_dict({"backend": "s3", "namespace": "example", "destination": {
        "bucket": "example-state", "region": "us-east-1", "owner_account_id": "123456789012",
        "key_prefix": "isaacautomator/v2"}}, cloud="aws")


def manifest():
    return dm.DeploymentManifest.create(
        backend_spec=spec(), target_scope="123456789012", deployment_name="demo",
        lineage="11111111-1111-4111-8111-111111111111", serial=3,
        addresses=["aws_instance.workstation"],
        source={"repository": "https://github.com/example/automator", "revision": "a" * 40,
                "root": "src/terraform/aws"},
        lockfile={"path": "src/terraform/aws/.terraform.lock.hcl", "sha256": "b" * 64},
        inputs={"region": "us-east-1", "instance_type": "g5.xlarge"},
        input_reference={"store": "protected-inputs", "key": "demo/revision-1"},
        secret_references={"ssh_private_key": {"store": "secret-manager", "key": "demo/ssh/1"}},
        applied_at="2026-09-10T00:00:00Z")


def _cas_worker(root, value, expected, barrier, results):
    barrier.wait(timeout=5)
    try:
        dm.LocalManifestStore(root).save(value, expected_digest=expected)
        results.put("saved")
    except dm.ManifestError:
        results.put("conflict")


class ManifestTests(unittest.TestCase):
    def test_unsafe_writable_ancestor_is_refused_before_any_write(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            unsafe = Path(temporary) / "unsafe"
            unsafe.mkdir(mode=0o777)
            unsafe.chmod(0o777)
            root = unsafe / "ancestor" / "state"
            with patch.object(dm.os, "replace", wraps=dm.os.replace) as replace:
                with self.assertRaises(dm.ManifestError):
                    dm.LocalManifestStore(root).save(manifest())
                replace.assert_not_called()
            self.assertFalse((unsafe / "ancestor").exists())

    def test_ancestor_renamed_during_replace_cannot_report_canonical_success(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary) / "ancestor"
            root = ancestor / "state"
            original = dm.os.replace
            def rename_then_replace(*args, **kwargs):
                ancestor.rename(Path(temporary) / "detached")
                return original(*args, **kwargs)
            with patch.object(dm.os, "replace", side_effect=rename_then_replace):
                with self.assertRaises(dm.ManifestError):
                    dm.LocalManifestStore(root).save(manifest())
            self.assertFalse((root / "demo" / "backend.json").exists())

    def test_local_cas_between_processes_has_exactly_one_winner(self):
        import multiprocessing
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            value = manifest()
            dm.LocalManifestStore(root).save(value)
            data = value.to_dict()
            data["state"]["serial"] += 1
            updated = dm.DeploymentManifest.from_dict(data)
            ctx = multiprocessing.get_context("fork")
            barrier, results = ctx.Barrier(2), ctx.Queue()
            workers = [ctx.Process(target=_cas_worker, args=(root, updated,
                       dm.digest(value.to_dict()), barrier, results)) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted(results.get(timeout=2) for _ in workers), ["conflict", "saved"])
            self.assertEqual(dm.LocalManifestStore(root).load("demo"), updated)

    def test_first_save_fsyncs_every_new_directory_parent(self):
        import tempfile
        import os
        import stat
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fresh" / "state"
            events = []
            original_mkdir, original_fsync = dm.os.mkdir, dm.os.fsync
            def mkdir(path, *args, **kwargs):
                result = original_mkdir(path, *args, **kwargs)
                info = os.fstat(kwargs["dir_fd"])
                events.append(("mkdir", (info.st_dev, info.st_ino)))
                return result
            def fsync(fd):
                info = os.fstat(fd)
                if stat.S_ISDIR(info.st_mode):
                    events.append(("fsync", (info.st_dev, info.st_ino)))
                return original_fsync(fd)
            with patch.object(dm.os, "mkdir", side_effect=mkdir), patch.object(dm.os, "fsync", side_effect=fsync):
                dm.LocalManifestStore(root).save(manifest())
            self.assertEqual(sum(event[0] == "mkdir" for event in events), 3)
            for index, (event, parent) in enumerate(events):
                if event == "mkdir":
                    self.assertEqual(events[index + 1], ("fsync", parent))
            self.assertEqual(dm.LocalManifestStore(root).load("demo"), manifest())

    def test_manifest_encoded_size_is_bounded_at_construction_and_before_save(self):
        import tempfile
        from pathlib import Path
        limit = 1024 * 1024
        data = manifest().to_dict()
        data["state"]["addresses"] = ["aws_instance.x"]
        data["state"]["addresses"][0] += "x" * (limit - len(dm.canonical(data).encode()))
        bounded = dm.DeploymentManifest.from_dict(data)
        self.assertEqual(len(bounded.canonical_json().encode()), limit)
        self.assertEqual(dm.DeploymentManifest.from_json(bounded.canonical_json()), bounded)
        data["state"]["addresses"][0] += "x"
        for construct in (
            lambda: dm.DeploymentManifest.from_dict(data),
            lambda: dm.DeploymentManifest.from_json(dm.canonical(data)),
            lambda: dm.DeploymentManifest.create(backend_spec=spec(), target_scope="123456789012",
                deployment_name="demo", lineage=data["state"]["lineage"], serial=3,
                addresses=["aws_instance." + "x" * limit]),
        ):
            with self.subTest(construct=construct), self.assertRaises(dm.ManifestError):
                construct()
        # Defensive save validation covers legacy instances/deserialization bypass.
        invalid = manifest()
        object.__setattr__(invalid, "_json", dm.canonical(data))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            store = dm.LocalManifestStore(root)
            with self.assertRaises(dm.ManifestError):
                store.save(invalid)
            self.assertFalse(root.exists())
            original = manifest()
            store.save(original)
            before = (root / "demo" / "backend.json").read_bytes()
            with self.assertRaises(dm.ManifestError):
                store.save(invalid, expected_digest=dm.digest(original.to_dict()))
            self.assertEqual((root / "demo" / "backend.json").read_bytes(), before)
            self.assertEqual(store.load("demo"), original)

    def test_strict_json_limit_counts_encoded_bytes_not_characters(self):
        raw = json.dumps("é" * (1024 * 1024 // 2), ensure_ascii=False)
        with self.assertRaises(dm.ManifestError):
            dm.strict_json(raw)

    def test_export_never_normalizes_invalid_secret_reference_containers_to_empty(self):
        for references in ([], "", False):
            with self.subTest(references=references), self.assertRaises(dm.ManifestError):
                dm.DeploymentManifest.create(backend_spec=spec(), target_scope="123456789012",
                    deployment_name="demo", lineage="11111111-1111-4111-8111-111111111111", serial=0,
                    addresses=[], secret_references=references)

    def test_relocation_rejects_configuration_only_change_at_same_physical_object(self):
        source = manifest()
        target = source.to_dict()
        target["backend_config"]["destination"]["region"] = "us-west-2"
        target["identity"] = BackendSpec.from_dict(target["backend_config"], cloud="aws").identity("123456789012", "demo")
        with self.assertRaises(dm.ManifestError):
            dm.RelocationRecord.create(source, dm.DeploymentManifest.from_dict(target),
                                       relocated_at="2026-09-10T01:00:00Z")

    def test_relocation_records_preserve_identity_without_claiming_a_provider_write_fence(self):
        self.assertTrue(hasattr(dm, "RelocationRecord"), "relocation contract missing")
        source = manifest()
        target_spec = spec().to_dict()
        target_spec["destination"]["key_prefix"] = "relocated/v2"
        target = source.to_dict()
        target["backend_config"] = target_spec
        target["identity"] = BackendSpec.from_dict(target_spec, cloud="aws").identity("123456789012", "demo")
        target["state"]["serial"] = 4
        destination = dm.DeploymentManifest.from_dict(target)
        record = dm.RelocationRecord.create(source, destination, relocated_at="2026-09-10T01:00:00Z")
        self.assertEqual(dm.RelocationRecord.from_json(record.canonical_json()), record)
        self.assertEqual(record.to_dict()["retirement"], "supervised_retirement_required")
        self.assertEqual(record.to_dict()["source_identity"], source.identity)
        self.assertEqual(record.to_dict()["destination_identity"], destination.identity)
        with self.assertRaises(dm.ManifestError):
            dm.RelocationRecord.create(source, source, relocated_at="2026-09-10T01:00:00Z")
        tampered = record.to_dict()
        tampered["retirement"] = "fenced"
        with self.assertRaises(dm.ManifestError):
            dm.RelocationRecord.from_json(json.dumps(tampered))

    def test_capabilities_require_verified_source_lockfile_protected_inputs_and_secrets(self):
        self.assertTrue(hasattr(dm, "evaluate_capabilities"), "capability assessment missing")
        data = manifest().to_dict()
        data["input_reference"]["sha256"] = "c" * 64
        value = dm.DeploymentManifest.from_dict(data)
        self.assertFalse(dm.evaluate_capabilities(value).repair_destroy)
        evidence = dict(verified_vm_identity=True, source_revision="a" * 40,
                        lockfile_sha256="b" * 64, protected_inputs_sha256="c" * 64,
                        required_secrets=("ssh_private_key",), available_secrets=("ssh_private_key",))
        complete = dm.evaluate_capabilities(value, **evidence)
        self.assertTrue(complete.state_inspection)
        self.assertTrue(complete.vm_start_stop)
        self.assertTrue(complete.repair_destroy)
        for key, wrong in (("source_revision", "d" * 40), ("lockfile_sha256", "d" * 64),
                           ("protected_inputs_sha256", "d" * 64), ("available_secrets", ()),
                           ("required_secrets", None)):
            with self.subTest(key=key):
                limited = dm.evaluate_capabilities(value, **dict(evidence, **{key: wrong}))
                self.assertTrue(limited.vm_start_stop)
                self.assertFalse(limited.repair_destroy)

    def test_allowlisted_export_is_immutable_and_round_trips(self):
        self.assertIsNotNone(dm, "recovery manifest implementation missing")
        value = manifest()
        data = value.to_dict()
        self.assertEqual(data["identity"], spec().identity("123456789012", "demo"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(dm.DeploymentManifest.from_json(value.canonical_json()), value)
        data["identity"]["destination"]["bucket"] = "other"
        self.assertEqual(value.to_dict()["identity"]["destination"]["bucket"], "example-state")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            value.identity = {}
        self.assertEqual(value.to_dict()["baseline"]["source_revision"], "a" * 40)
        self.assertEqual(len(value.to_dict()["baseline"]["input_sha256"]), 64)

    def test_local_descriptor_is_atomic_private_and_compare_and_swap(self):
        import tempfile
        import os
        from pathlib import Path
        from unittest.mock import patch
        self.assertTrue(hasattr(dm, "LocalManifestStore"), "local persistence missing")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fresh" / "state"
            store = dm.LocalManifestStore(root)
            value = manifest()
            store.save(value)
            path = root / "demo" / "backend.json"
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(store.load("demo"), value)
            with self.assertRaises(dm.ManifestError):
                store.save(value)
            data = value.to_dict()
            data["state"]["serial"] = 4
            updated = dm.DeploymentManifest.from_dict(data)
            expected = dm.digest(value.to_dict())
            with patch.object(dm.os, "replace", side_effect=OSError("SYNTHETIC-SECRET")):
                with self.assertRaises(dm.ManifestError) as caught:
                    store.save(updated, expected_digest=expected)
            self.assertNotIn("SYNTHETIC-SECRET", str(caught.exception))
            self.assertEqual(store.load("demo"), value)
            store.save(updated, expected_digest=expected)
            self.assertEqual(store.load("demo"), updated)
            with self.assertRaises(dm.ManifestError):
                store.save(value, expected_digest=expected)
            with self.assertRaises(dm.ManifestError):
                store.load("../demo")
            path.unlink()
            path.symlink_to(Path(temporary) / "outside")
            with self.assertRaises(dm.ManifestError):
                store.save(value)
            link = Path(temporary) / "link"
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(dm.ManifestError):
                dm.LocalManifestStore(link).load("demo")

    def test_import_rejects_unknown_nested_credentials_and_forged_identity(self):
        mutations = [
            lambda d: d.update(legacy_params={"password": "SYNTHETIC-SECRET"}),
            lambda d: d["inputs"].update(region={"token": "SYNTHETIC-SECRET"}),
            lambda d: d["inputs"].update(password="SYNTHETIC-SECRET"),
            lambda d: d["source"].update(token="SYNTHETIC-SECRET"),
            lambda d: d["source"].update(repository="https://user:SYNTHETIC-SECRET@example.com/repo"),
            lambda d: d["source"].update(revision="main"),
            lambda d: d["source"].update(root="../private"),
            lambda d: d["secret_references"]["ssh_private_key"].update(value="SYNTHETIC-SECRET"),
            lambda d: d["identity"].update(object_key="other.tfstate"),
            lambda d: d["baseline"].update(input_sha256="0" * 64),
            lambda d: d.update(schema_version=True),
            lambda d: d["state"].update(serial=True),
            lambda d: d["state"].update(lineage="bad"),
            lambda d: d["state"].update(addresses=["aws_instance.workstation", "aws_instance.workstation"]),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                data = manifest().to_dict()
                mutate(data)
                with self.assertRaises(ValueError) as caught:
                    dm.DeploymentManifest.from_dict(data)
                self.assertNotIn("SYNTHETIC-SECRET", str(caught.exception))
        with self.assertRaises(ValueError):
            dm.DeploymentManifest.from_json('{"schema_version":1,"schema_version":1}')


if __name__ == "__main__":
    unittest.main()
