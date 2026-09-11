"""Explicit offline bundle integration, using only disposable public fixtures."""
import json
import hashlib
import os
import tempfile
import threading
import time
import traceback
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

from src.tests.knowledge_graph.test_shared_contract import SigningFixture, identity
from src.knowledge_graph import shared_contract as contract, shared_client


def local_bundle(root, signer, payload=None, artifacts=None):
    if payload is None:
        payload, artifacts = signer.payload()
    assert artifacts is not None
    path = Path(root)
    path.mkdir(mode=0o700)
    contents = {**artifacts, "catalog.json": signer.sign(payload)}
    for name, data in contents.items():
        target = path / name
        target.write_bytes(data)
        target.chmod(0o600)
    return path


class SharedClientTests(unittest.TestCase):
    @contextmanager
    def assert_filesystem_error(self):
        try:
            yield
        except contract.VerificationError as error:
            self.assertEqual(str(error), "shared_filesystem_unavailable")
            self.assertIsNone(error.__cause__)
            self.assertTrue(error.__suppress_context__)
            self.assertNotIn("synthetic-private-project-name", "".join(traceback.format_exception(error)))
        else:
            self.fail("filesystem failure must raise, not return a receipt or status")

    def test_import_filesystem_errors_are_source_free_and_preserve_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            client = shared_client.SharedClient(root / "cache", signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            missing = root / "synthetic-private-project-name"
            with self.assert_filesystem_error():
                client.import_local(missing, identity(), now=1001)
            for operation, target, error_type in (
                    ("open", bundle.name, PermissionError),
                    ("stat", "catalog.json", FileNotFoundError),
                    ("open", "catalog.json", OSError)):
                real = getattr(shared_client.os, operation)
                def fail_selected(path, *args, **kwargs):
                    if path == target:
                        raise error_type(5, "synthetic-private-project-name", "synthetic-private-project-name")
                    return real(path, *args, **kwargs)
                with self.subTest(operation=operation, target=target), patch.object(
                        shared_client.os, operation, side_effect=fail_selected), self.assert_filesystem_error():
                    client.import_local(bundle, identity(), now=1001)
                self.assertEqual(client.status(identity(), now=1001), receipt)

    def test_status_filesystem_errors_never_return_cached_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            client = shared_client.SharedClient(root / "cache", signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            missing = shared_client.SharedClient(root / "synthetic-private-project-name", signer.trust(), enabled=True)
            with self.subTest(operation="missing_cache"), self.assert_filesystem_error():
                missing.status(identity(), now=1001)
            for operation, target in (("open", "shared.lock"), ("stat", "shared-state.json"),
                                      ("open", "catalog.json"), ("fsync", None), ("replace", None)):
                real = getattr(shared_client.os, operation)
                def fail_selected(path, *args, **kwargs):
                    if target is None or path == target:
                        raise PermissionError(13, "synthetic-private-project-name", "synthetic-private-project-name")
                    return real(path, *args, **kwargs)
                with self.subTest(operation=operation, target=target), patch.object(
                        shared_client.os, operation, side_effect=fail_selected), self.assert_filesystem_error():
                    client.status(identity(), now=1002 if target is None else 1001)
                self.assertEqual(client.status(identity(), now=1001), receipt)

    def test_observe_filesystem_errors_do_not_report_catalog_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            client = shared_client.SharedClient(root / "cache", signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            payload, _ = signer.payload(catalog_sequence=2)
            envelope = signer.sign(payload)
            missing = shared_client.SharedClient(
                root / "synthetic-private-project-name" / "cache", signer.trust(), enabled=True)
            with self.subTest(operation="missing_parent"), self.assert_filesystem_error():
                missing.observe_catalog(envelope, identity(), now=1001)
            for operation, target in (("open", "shared.lock"), ("stat", "shared-state.json"),
                                      ("fsync", None), ("replace", None)):
                real = getattr(shared_client.os, operation)
                def fail_selected(path, *args, **kwargs):
                    if target is None or path == target:
                        raise OSError(5, "synthetic-private-project-name", "synthetic-private-project-name")
                    return real(path, *args, **kwargs)
                with self.subTest(operation=operation, target=target), patch.object(
                        shared_client.os, operation, side_effect=fail_selected), self.assert_filesystem_error():
                    client.observe_catalog(envelope, identity(), now=1001)
                self.assertEqual(client.status(identity(), now=1001), receipt)
            real_replace = shared_client.os.replace
            def lose_acknowledgement(*args, **kwargs):
                real_replace(*args, **kwargs)
                raise OSError("synthetic-private-project-name")
            with patch.object(shared_client.os, "replace", side_effect=lose_acknowledgement), self.assert_filesystem_error():
                client.observe_catalog(envelope, identity(), now=1001)
            with self.assertRaisesRegex(contract.VerificationError, "^no_verified_bundle$"):
                client.status(identity(), now=1001)
            with self.assertRaisesRegex(contract.VerificationError, "replay"):
                client.import_local(bundle, identity(), now=1001)

    def test_stage_bytes_are_reverified_before_atomic_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            cache = root / "cache"
            client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            payload, artifacts = signer.payload(catalog_sequence=2)
            next_bundle = local_bundle(root / "next", signer, payload, artifacts)
            real_write = shared_client._write
            def corrupt_stage(fd, name, data):
                if name == "dataset.trig":
                    data = b"x" * len(data)
                real_write(fd, name, data)
            with patch.object(shared_client, "_write", side_effect=corrupt_stage), self.assertRaisesRegex(ValueError, "digest"):
                client.import_local(next_bundle, identity(), now=1001)
            self.assertEqual(client.status(identity(), now=1001), receipt)
            self.assertEqual(list(cache.glob(".stage-*")), [])

    def test_identical_import_is_idempotent_and_cache_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            cache = root / "cache"
            client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            for _ in range(3):
                client.import_local(bundle, identity(), now=1001)
            self.assertEqual(len(list(cache.glob("bundle-*"))), 1)
            for sequence in range(2, 9):
                payload, artifacts = signer.payload(catalog_sequence=sequence)
                local = local_bundle(root / str(sequence), signer, payload, artifacts)
                client.import_local(local, identity(), now=1001)
            payload, artifacts = signer.payload(catalog_sequence=9)
            overflow = local_bundle(root / "overflow", signer, payload, artifacts)
            with self.assertRaisesRegex(ValueError, "cache_generation_limit"):
                client.import_local(overflow, identity(), now=1001)
            self.assertEqual(client.status(identity(), now=1001)["catalog_sequence"], 8)

    def test_partial_stage_write_failure_cleans_only_owned_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            cache = root / "cache"
            client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            payload, artifacts = signer.payload(catalog_sequence=2)
            next_bundle = local_bundle(root / "next", signer, payload, artifacts)
            with patch.object(shared_client.os, "fsync", side_effect=OSError("synthetic disk failure")), self.assert_filesystem_error():
                client.import_local(next_bundle, identity(), now=1001)
            self.assertEqual(list(cache.glob(".stage-*")), [])
            self.assertEqual(client.status(identity(), now=1001), receipt)

    def test_concurrent_imports_cannot_roll_back_a_newer_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            first = local_bundle(root / "first", signer)
            payload, artifacts = signer.payload(catalog_sequence=2)
            second = local_bundle(root / "second", signer, payload, artifacts)
            client = shared_client.SharedClient(root / "cache", signer.trust(), enabled=True)
            entered = threading.Event()
            save = shared_client._save_state
            def delayed(fd, checkpoint, active):
                if checkpoint.sequence == 1:
                    entered.set()
                    time.sleep(0.1)
                return save(fd, checkpoint, active)
            with patch.object(shared_client, "_save_state", side_effect=delayed), ThreadPoolExecutor(max_workers=2) as executor:
                old = executor.submit(client.import_local, first, identity(), now=1001)
                self.assertTrue(entered.wait(3))
                new = executor.submit(client.import_local, second, identity(), now=1001)
                old.result(timeout=5)
                new.result(timeout=5)
            self.assertEqual(client.status(identity(), now=1001)["catalog_sequence"], 2)

    def test_unknown_atomic_commit_outcome_retains_a_complete_active_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            first = local_bundle(root / "first", signer)
            client = shared_client.SharedClient(root / "cache", signer.trust(), enabled=True)
            previous = client.import_local(first, identity(), now=1001)
            payload, artifacts = signer.payload(catalog_sequence=2)
            second = local_bundle(root / "second", signer, payload, artifacts)
            real_replace = shared_client.os.replace
            def before(*args, **kwargs):
                raise OSError("synthetic precommit failure")
            with patch.object(shared_client.os, "replace", side_effect=before), self.assert_filesystem_error():
                client.import_local(second, identity(), now=1001)
            self.assertEqual(client.status(identity(), now=1001), previous)
            def after(*args, **kwargs):
                real_replace(*args, **kwargs)
                raise OSError("synthetic lost commit acknowledgement")
            with patch.object(shared_client.os, "replace", side_effect=after), self.assert_filesystem_error():
                client.import_local(second, identity(), now=1001)
            self.assertEqual(client.status(identity(), now=1001)["catalog_sequence"], 2)

    def test_status_clock_and_signed_revocation_survive_client_restart(self):
        self.assertTrue(hasattr(shared_client.SharedClient, "observe_catalog"), "revocation observation missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            cache = root / "cache"
            client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            client.status(identity(), now=1020)
            restarted = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            with self.assertRaisesRegex(ValueError, "clock_rollback"):
                restarted.status(identity(), now=1002)
            revoked, _ = signer.payload(catalog_sequence=2, revocation_epoch=2,
                                        revoked_generations=[receipt["generation"]])
            restarted.observe_catalog(signer.sign(revoked), identity(), now=1021)
            restarted = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            with self.assertRaisesRegex(ValueError, "no_verified_bundle"):
                restarted.status(identity(), now=1022)
            with self.assertRaisesRegex(ValueError, "replay"):
                restarted.import_local(bundle, identity(), now=1022)
            restored, artifacts = signer.payload(catalog_sequence=3, revocation_epoch=3)
            restoration = local_bundle(root / "restored", signer, restored, artifacts)
            with self.assertRaisesRegex(ValueError, "revoked"):
                restarted.import_local(restoration, identity(), now=1022)

    def test_expired_lease_cannot_be_reactivated_by_clock_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            client = shared_client.SharedClient(root / "cache", signer.trust(), enabled=True)
            client.import_local(bundle, identity(), now=1001)
            with self.assertRaisesRegex(ValueError, "lease"):
                client.status(identity(), now=1100)
            with self.assertRaisesRegex(ValueError, "clock_rollback"):
                client.status(identity(), now=1050)

    def test_owner_only_files_and_no_symlink_hardlink_or_fifo_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            for index, mutation in enumerate(("cache_mode", "bundle_mode", "file_mode", "hardlink",
                                               "fifo", "symlink", "ancestor_symlink", "cache_symlink")):
                bundle = local_bundle(root / ("bundle-" + str(index)), signer)
                cache = root / ("cache-" + str(index))
                if mutation == "cache_mode":
                    cache.mkdir(mode=0o755)
                if mutation == "bundle_mode":
                    bundle.chmod(0o755)
                if mutation == "file_mode":
                    (bundle / "dataset.trig").chmod(0o644)
                if mutation in {"hardlink", "fifo", "symlink"}:
                    artifact = bundle / "dataset.trig"
                    target = root / ("outside-" + str(index))
                    artifact.rename(target)
                    if mutation == "hardlink":
                        os.link(target, artifact)
                    elif mutation == "fifo":
                        os.mkfifo(artifact, mode=0o600)
                    else:
                        artifact.symlink_to(target)
                if mutation == "ancestor_symlink":
                    alias = root / "alias"
                    alias.symlink_to(root, target_is_directory=True)
                    bundle = alias / bundle.name
                if mutation == "cache_symlink":
                    target = root / "outside-cache"
                    target.mkdir(mode=0o700)
                    cache.symlink_to(target, target_is_directory=True)
                with self.subTest(mutation=mutation), self.assertRaises(contract.VerificationError):
                    shared_client.SharedClient(cache, signer.trust(), enabled=True).import_local(bundle, identity(), now=1001)
                if mutation == "cache_symlink":
                    self.assertEqual(list(target.iterdir()), [])

    def test_corrupt_cache_pointer_and_missing_replay_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            cache = root / "cache"
            client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            client.import_local(bundle, identity(), now=1001)
            state_path = cache / "shared-state.json"
            state = json.loads(state_path.read_bytes())
            state["active"] = "../bundle"
            state_path.write_bytes(contract.canonical_json(state))
            with self.assertRaisesRegex(ValueError, "cache_state"):
                client.status(identity(), now=1001)
            state_path.unlink()
            with self.assertRaisesRegex(ValueError, "checkpoint_missing"):
                client.import_local(bundle, identity(), now=1001)

    def test_disabled_client_and_unrelated_cache_are_never_touched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            for enabled in (False, 1, "true"):
                cache = root / ("disabled-" + str(enabled))
                client = shared_client.SharedClient(cache, signer.trust(), enabled=enabled)
                with self.subTest(enabled=enabled), self.assertRaisesRegex(ValueError, "disabled"):
                    client.import_local(bundle, identity(), now=1001)
                self.assertFalse(cache.exists())
                with self.assertRaisesRegex(ValueError, "disabled"):
                    client.status(identity(), now=1001)
            cache = root / "existing-local-graph"
            cache.mkdir(mode=0o700)
            (cache / "current").write_text("synthetic unrelated state")
            with self.assertRaisesRegex(ValueError, "dedicated_cache"):
                shared_client.SharedClient(cache, signer.trust(), enabled=True).import_local(bundle, identity(), now=1001)
            self.assertEqual([p.name for p in cache.iterdir()], ["current"])

    def test_tampered_incomplete_or_extended_bundle_never_replaces_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "valid", signer)
            cache = root / "cache"
            client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
            receipt = client.import_local(bundle, identity(), now=1001)
            prior = (cache / "shared-state.json").read_bytes()
            for index, mutation in enumerate(("tamper", "missing", "extra", "wrong_manifest", "binary", "dirty_type")):
                payload, artifacts = signer.payload(catalog_sequence=2)
                if mutation == "wrong_manifest":
                    artifacts["manifest.json"] = contract.canonical_json(identity(repository_id="fork"))
                if mutation == "binary":
                    artifacts["dataset.trig"] = b"\xff\x00"
                if mutation == "dirty_type":
                    malformed = identity()
                    malformed["dirty"] = 0
                    artifacts["manifest.json"] = contract.canonical_json(malformed)
                if mutation in {"wrong_manifest", "binary", "dirty_type"}:
                    payload["artifacts"] = {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                                            for name, data in artifacts.items()}
                    payload["generation"] = hashlib.sha256(contract.canonical_json(payload["artifacts"])).hexdigest()
                bad = local_bundle(root / str(index), signer, payload, artifacts)
                if mutation == "tamper":
                    (bad / "dataset.trig").write_bytes(b"x" * len(artifacts["dataset.trig"]))
                if mutation == "missing":
                    (bad / "dataset.trig").unlink()
                if mutation == "extra":
                    (bad / "claims.json").write_text("[]")
                with self.subTest(mutation=mutation), self.assertRaises(contract.VerificationError):
                    client.import_local(bad, identity(), now=1001)
                self.assertEqual((cache / "shared-state.json").read_bytes(), prior)
                self.assertEqual(client.status(identity(), now=1001), receipt)

    def test_two_explicit_clients_stage_same_verified_generation_without_query_admission(self):
        self.assertIsNotNone(shared_client, "offline shared client missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signer = SigningFixture(root)
            bundle = local_bundle(root / "bundle", signer)
            receipts = []
            for name in ("checkout-one-cache", "checkout-two-cache"):
                cache = root / name
                client = shared_client.SharedClient(cache, signer.trust(), enabled=True)
                receipt = client.import_local(bundle, identity(), now=1001)
                self.assertEqual(client.status(identity(), now=1001), receipt)
                self.assertFalse(receipt["query_ready"])
                self.assertEqual(receipt["verification"], "signature_and_bytes_only")
                self.assertEqual(receipt["transport"], "verified_cache")
                self.assertEqual(receipt["checkout_binding"], "matches_supplied_identity")
                self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
                for item in cache.rglob("*"):
                    self.assertEqual(item.stat().st_mode & 0o777, 0o700 if item.is_dir() else 0o600)
                receipts.append(receipt)
            self.assertEqual(receipts[0], receipts[1])
            self.assertEqual(set(p.name for p in bundle.iterdir()), contract.ARTIFACTS | {"catalog.json"})


if __name__ == "__main__":
    unittest.main()
