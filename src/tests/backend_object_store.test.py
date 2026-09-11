"""Concrete cloud command adapters exercised ONLY with injected subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from src.python.terraform_backend import BackendSpec
from src.python import deployment_manifest as dm
from src.python import backend_object_store as bos


def backend(cloud="aws"):
    variants = {
        "aws": {"backend": "s3", "destination": {"bucket": "example-state", "region": "us-east-1",
            "owner_account_id": "123456789012", "key_prefix": "isaacautomator/v2"}},
        "gcp": {"backend": "gcs", "destination": {"bucket": "example-state", "project": "example-project",
            "prefix": "isaacautomator/v2"}},
        "azure": {"backend": "azurerm", "destination": {"tenant_id": "11111111-1111-4111-8111-111111111111",
            "subscription_id": "22222222-2222-4222-8222-222222222222", "resource_group_name": "state-rg",
            "storage_account_name": "examplestate", "container_name": "state", "key_prefix": "isaacautomator/v2"}}}
    return BackendSpec.from_dict(dict(variants[cloud], namespace="example"), cloud=cloud)


def store(cloud="aws", run=None):
    scope = {"aws": "123456789012", "gcp": "example-project",
             "azure": "22222222-2222-4222-8222-222222222222"}[cloud]
    return bos.CLIObjectStore(backend(cloud), scope, "demo", run=run, environment={})


class MemoryStore:
    """Deterministic test service implementing atomic conditional object writes."""
    def __init__(self):
        self.identity = backend().identity("123456789012", "demo")
        self.objects = {}
        self.events = []
        self.serial = 0
        self.lock = threading.Lock()

    def read(self, kind):
        self.events.append(("read", kind))
        return self.objects.get(kind)

    def write(self, kind, data, *, expected_generation=None):
        with self.lock:
            return self._write(kind, data, expected_generation)

    def _write(self, kind, data, expected_generation):
        self.events.append(("write", kind))
        old = self.objects.get(kind)
        if (None if old is None else old.generation) != expected_generation:
            raise bos.ObjectConflict("conditional write conflict")
        self.serial += 1
        generation = str(self.serial)
        self.objects[kind] = bos.StoredObject(data, generation)
        return generation


class OwnershipTests(unittest.TestCase):
    def test_simultaneous_first_creators_cannot_both_win_the_reservation(self):
        remote = MemoryStore()
        rendezvous = threading.Barrier(2)
        original_read = remote.read
        def read(kind):
            value = original_read(kind)
            if kind == "manifest":
                rendezvous.wait(timeout=5)
            return value
        remote.read = read
        def reserve(owner):
            try:
                return bos.ProtectedObjectCoordinator(remote, authorize=lambda *args: None).claim_new(owner)
            except bos.ObjectConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, ("11111111-1111-4111-8111-111111111111",
                                                "22222222-2222-4222-8222-222222222222")))
        self.assertEqual(sum(result is not None for result in outcomes), 1)
        self.assertEqual(json.loads(remote.objects["claim"].data)["status"], "pending")

    def test_claimant_revalidates_initial_state_and_refuses_competing_first_apply(self):
        self.assertTrue(hasattr(bos.ProtectedObjectCoordinator, "verify_creation_state"), "creation state gate missing")
        remote = MemoryStore()
        coordinator = bos.ProtectedObjectCoordinator(remote, authorize=lambda *args: None)
        owner = "11111111-1111-4111-8111-111111111111"
        claim = coordinator.claim_new(owner)
        self.assertIsNone(coordinator.verify_creation_state(claim))
        initial = {"version": 4, "lineage": owner, "serial": 0, "resources": [], "outputs": {}}
        generation = remote.write("state", json.dumps(initial).encode())
        with self.assertRaises(bos.ObjectConflict):
            coordinator.verify_creation_state(claim)
        summary = coordinator.verify_creation_state(claim, allow_initialized_empty=True)
        coordinator.verify_creation_state(claim, expected_state=summary)
        initial["serial"] = 1
        remote.write("state", json.dumps(initial).encode(), expected_generation=generation)
        with self.assertRaises(dm.IdentityMismatch):
            coordinator.verify_creation_state(claim, expected_state=summary)

    def test_creation_observation_binds_exact_private_bytes_generation_and_claim(self):
        from dataclasses import FrozenInstanceError, replace
        remote = MemoryStore()
        coordinator = bos.ProtectedObjectCoordinator(remote, authorize=lambda *args: None)
        owner = "11111111-1111-4111-8111-111111111111"
        claim = coordinator.claim_new(owner)
        raw = {"version": 4, "lineage": owner, "serial": 0, "resources": [], "outputs": {}}
        original = bos.StoredObject(json.dumps(raw).encode(), "2")
        remote.objects["state"] = original
        receipt = coordinator.verify_creation_state(claim, allow_initialized_empty=True)
        assert receipt is not None
        # Both a generation-only rewrite and byte-only rewrite must fail even
        # though lineage/serial/managed addresses have not changed.
        for changed in (
            bos.StoredObject(original.data, "3"),
            bos.StoredObject(json.dumps(raw, indent=2).encode(), "2"),
            bos.StoredObject(json.dumps(dict(raw, outputs={"key": {"value": "SYNTHETIC-SECRET"}})).encode(), "3"),
            bos.StoredObject(json.dumps(dict(raw, resources=[{"mode": "data", "instances": []}])).encode(), "2"),
        ):
            remote.objects["state"] = changed
            with self.subTest(changed=changed), self.assertRaises((bos.ObjectConflict, dm.IdentityMismatch)):
                coordinator.verify_creation_state(claim, expected_state=receipt, allow_initialized_empty=True)
        remote.objects["state"] = original
        self.assertEqual(receipt.generation, "2")
        self.assertEqual(receipt.identity, remote.identity)
        self.assertEqual(receipt.summary, dm.StateSummary.from_state(raw))
        self.assertEqual(coordinator.verify_creation_state(claim, expected_state=receipt), receipt)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            receipt.generation = "3"
        self.assertNotIn(receipt._content_digest.hex(), repr(receipt))
        self.assertNotIn("SYNTHETIC-SECRET", repr(receipt))
        with self.assertRaises(dm.ManifestError):
            coordinator.verify_creation_state(claim, expected_state=receipt.summary)
        changed_identity = receipt.identity
        changed_identity["deployment_name"] = "other"
        self.assertEqual(receipt.identity, remote.identity)
        for wrong in (replace(receipt, _identity_json=dm.canonical(changed_identity)),
                      replace(receipt, claim=replace(claim, owner_id="22222222-2222-4222-8222-222222222222"))):
            with self.assertRaises(bos.ObjectConflict):
                coordinator.verify_creation_state(claim, expected_state=wrong)
        del remote.objects["state"]
        with self.assertRaises(bos.ObjectConflict):
            coordinator.verify_creation_state(claim, expected_state=receipt)

    def test_initialized_empty_baseline_rejects_output_or_data_resources(self):
        for extra in ({"outputs": {"value": {"value": "SYNTHETIC-SECRET"}}},
                      {"resources": [{"mode": "data", "instances": []}]}):
            remote = MemoryStore()
            coordinator = bos.ProtectedObjectCoordinator(remote, authorize=lambda *args: None)
            owner = "11111111-1111-4111-8111-111111111111"
            claim = coordinator.claim_new(owner)
            raw = dict(version=4, lineage=owner, serial=0, resources=[], outputs={})
            raw.update(extra)
            remote.objects["state"] = bos.StoredObject(json.dumps(raw).encode(), "2")
            with self.subTest(extra=extra), self.assertRaises(bos.ObjectConflict):
                coordinator.verify_creation_state(claim, allow_initialized_empty=True)

    def test_negative_or_ambiguous_protection_verification_never_grants_ownership(self):
        for result in (False, True, {"trusted": True}):
            remote = MemoryStore()
            with self.subTest(result=result), self.assertRaises(bos.ObjectAccessDenied):
                bos.ProtectedObjectCoordinator(remote, authorize=lambda *args: result).claim_new(
                    "11111111-1111-4111-8111-111111111111")
            self.assertEqual(remote.events, [])

    def test_protected_relocation_fences_stale_clients_without_following_redirects(self):
        self.assertTrue(hasattr(bos.ProtectedObjectCoordinator, "publish_relocation"), "relocation storage missing")
        remote = MemoryStore()
        coordinator = bos.ProtectedObjectCoordinator(remote, authorize=Mock(return_value=None))
        owner = "11111111-1111-4111-8111-111111111111"
        claim = coordinator.claim_new(owner)
        source = dm.DeploymentManifest.create(backend_spec=backend(), target_scope="123456789012",
            deployment_name="demo", lineage=owner, serial=3, addresses=[])
        remote.write("state", json.dumps({"version": 4, "lineage": owner, "serial": 3,
                                          "resources": []}).encode())
        coordinator.complete_creation(claim, source)
        config = backend().to_dict()
        config["destination"]["key_prefix"] = "relocated/v2"
        destination = dm.DeploymentManifest.create(backend_spec=BackendSpec.from_dict(config, cloud="aws"),
            target_scope="123456789012", deployment_name="demo", lineage=owner, serial=3, addresses=[])
        record = dm.RelocationRecord.create(source, destination, relocated_at="2026-09-10T01:00:00Z")
        verifier = Mock(return_value={"identity": destination.identity, "state": destination.to_dict()["state"]})
        coordinator.publish_relocation(record, verify_destination=verifier)
        self.assertEqual(coordinator.read_relocation(), record)
        self.assertEqual(remote.objects["state"].data, json.dumps({"version": 4, "lineage": owner,
                         "serial": 3, "resources": []}).encode())
        for action in (coordinator.require_attachable, lambda: coordinator.claim_new(owner),
                       lambda: coordinator.assert_claim(claim)):
            with self.assertRaises(bos.ObjectConflict):
                action()
        self.assertEqual(json.loads(remote.objects["relocation"].data)["retirement"],
                         "supervised_retirement_required")

    def test_completion_publishes_verified_manifest_and_failed_publication_keeps_pending(self):
        self.assertTrue(hasattr(bos.ProtectedObjectCoordinator, "complete_creation"), "claim completion missing")
        remote = MemoryStore()
        coordinator = bos.ProtectedObjectCoordinator(remote, authorize=Mock(return_value=None))
        owner = "11111111-1111-4111-8111-111111111111"
        claim = coordinator.claim_new(owner)
        value = dm.DeploymentManifest.create(backend_spec=backend(), target_scope="123456789012",
            deployment_name="demo", lineage=owner, serial=3, addresses=[])
        state = {"version": 4, "lineage": owner, "serial": 3, "resources": [],
                 "outputs": {"key": {"value": "SYNTHETIC-SECRET"}}}
        remote.write("state", json.dumps(state).encode())
        original_write = remote.write
        def failed(kind, *args, **kwargs):
            if kind == "manifest":
                raise bos.ObjectStoreError("publication interrupted")
            return original_write(kind, *args, **kwargs)
        remote.write = failed
        receipt = coordinator.complete_creation(claim, value)
        self.assertTrue(receipt.recovery_needed)
        self.assertEqual(receipt.status, "recovery_needed")
        with self.assertRaises(bos.ObjectConflict):
            coordinator.require_attachable()
        remote.write = original_write
        receipt = coordinator.complete_creation(claim, value)
        self.assertFalse(receipt.recovery_needed)
        self.assertEqual(coordinator.require_attachable()["lineage"], owner)
        self.assertEqual(dm.DeploymentManifest.from_json(remote.objects["manifest"].data), value)
        self.assertNotIn("SYNTHETIC-SECRET", repr(receipt))
        # A state/manifest serial mismatch cannot be published as successful.
        bad = value.to_dict()
        bad["state"]["serial"] = 4
        receipt = coordinator.publish_manifest(dm.DeploymentManifest.from_dict(bad),
            expected_generation=remote.objects["manifest"].generation)
        self.assertTrue(receipt.recovery_needed)
        self.assertEqual(dm.DeploymentManifest.from_json(remote.objects["manifest"].data), value)

    def test_remote_publication_validates_previous_generation_and_monotonic_binding(self):
        for change in ("rollback", "identity", "lineage", "stale", "missing", "malformed", "advance"):
            with self.subTest(change=change):
                remote = MemoryStore()
                coordinator = bos.ProtectedObjectCoordinator(remote, authorize=lambda *args: None)
                owner = "11111111-1111-4111-8111-111111111111"
                claim = coordinator.claim_new(owner)
                value = dm.DeploymentManifest.create(backend_spec=backend(), target_scope="123456789012",
                    deployment_name="demo", lineage=owner, serial=5, addresses=[])
                raw = {"version": 4, "lineage": owner, "serial": 5, "resources": []}
                remote.write("state", json.dumps(raw).encode())
                self.assertFalse(coordinator.complete_creation(claim, value).recovery_needed)
                expected = remote.objects["manifest"].generation
                proposal = value.to_dict()
                if change in ("rollback", "advance"):
                    proposal["state"]["serial"] = 0 if change == "rollback" else 6
                    raw["serial"] = proposal["state"]["serial"]
                elif change in ("identity", "lineage"):
                    old = value.to_dict()
                    if change == "identity":
                        old["identity"] = backend().identity("123456789012", "other")
                    else:
                        old["state"]["lineage"] = "22222222-2222-4222-8222-222222222222"
                    remote.objects["manifest"] = bos.StoredObject(
                        dm.DeploymentManifest.from_dict(old).canonical_json().encode(), expected)
                elif change == "stale":
                    expected = "stale-receipt"
                elif change == "missing":
                    del remote.objects["manifest"]
                elif change == "malformed":
                    remote.objects["manifest"] = bos.StoredObject(b"{}", expected)
                remote.objects["state"] = bos.StoredObject(json.dumps(raw).encode(), "new-state")
                previous = remote.objects.get("manifest")
                remote.events.clear()
                result = coordinator.publish_manifest(dm.DeploymentManifest.from_dict(proposal),
                                                       expected_generation=expected)
                if change == "advance":
                    self.assertEqual(result.status, "published")
                    self.assertEqual(dm.DeploymentManifest.from_json(remote.objects["manifest"].data).to_dict(), proposal)
                else:
                    self.assertTrue(result.recovery_needed)
                    self.assertEqual(remote.objects.get("manifest"), previous)
                    self.assertNotIn(("write", "manifest"), remote.events)

    def test_first_creator_claim_is_atomic_before_init_and_blocks_other_controllers(self):
        self.assertTrue(hasattr(bos, "ProtectedObjectCoordinator"), "ownership coordinator missing")
        remote = MemoryStore()
        auth = Mock(return_value=None)
        coordinator = bos.ProtectedObjectCoordinator(remote, authorize=auth)
        owner = "11111111-1111-4111-8111-111111111111"
        claim = coordinator.claim_new(owner)
        self.assertEqual(claim.owner_id, owner)
        self.assertEqual(json.loads(remote.objects["claim"].data)["status"], "pending")
        auth.assert_called()
        coordinator.assert_claim(claim)
        self.assertNotIn(("write", "state"), remote.events)
        with self.assertRaises(bos.ObjectConflict):
            bos.ProtectedObjectCoordinator(remote, authorize=auth).claim_new(
                "22222222-2222-4222-8222-222222222222")
        with self.assertRaises(bos.ObjectConflict):
            coordinator.require_attachable()
        # No auto-adoption, even an empty object left by Terraform init.
        for content in (b"{}", b'{"version":4,"resources":[]}'):
            occupied = MemoryStore()
            occupied.write("state", content)
            with self.assertRaises(bos.ObjectConflict):
                bos.ProtectedObjectCoordinator(occupied, authorize=auth).claim_new(owner)
            self.assertNotIn("claim", occupied.objects)
        denied = MemoryStore()
        with self.assertRaises(bos.ObjectAccessDenied):
            bos.ProtectedObjectCoordinator(denied, authorize=Mock(
                side_effect=bos.ObjectAccessDenied("denied"))).claim_new(owner)
        self.assertEqual(denied.events, [])


class AdapterTests(unittest.TestCase):
    def test_gcs_absence_requires_exact_installed_cli_object_diagnostic(self):
        target = store("gcp")
        url = target._gcs_url("state")
        for diagnostic, absent in (
            (f"ERROR: (gcloud.storage.objects.describe) {url} not found: 404.", True),
            ("HTTPError 404: upstream endpoint not found", False),
            ("HTTPError 404", False),
            ("ERROR: (gcloud.storage.objects.describe) gs://example-state/other not found: 404.", False),
            ("ERROR: (gcloud.storage.objects.describe) gs://example-state not found: 404.", False),
            (f"ERROR: (gcloud.storage.objects.describe) {url} not found: 404. extra", False),
        ):
            with self.subTest(diagnostic=diagnostic):
                fake = Mock(side_effect=[subprocess.CompletedProcess([], 1, b"", diagnostic.encode()),
                    subprocess.CompletedProcess([], 0, b'{"name":"example-state"}', b"")])
                target = store("gcp", run=fake)
                if absent:
                    self.assertIsNone(target.read("state"))
                else:
                    with self.assertRaises(bos.ObjectStoreError):
                        target.read("state")
                    self.assertEqual(fake.call_count, 1)

    def test_gcs_missing_bucket_is_not_an_empty_state_object(self):
        target = store("gcp", run=Mock(return_value=subprocess.CompletedProcess([], 1, b"", b"HTTPError 404")))
        with self.assertRaises(bos.ObjectStoreError):
            target.read("state")

    def test_wildcard_etags_and_malformed_read_receipts_fail_before_unconditional_write(self):
        for cloud in ("aws", "gcp", "azure"):
            for token in ("*", "", "--dangerous", "bad\nvalue"):
                fake = Mock(return_value=None)
                with self.subTest(cloud=cloud, token=token), self.assertRaises(dm.ManifestError):
                    store(cloud, run=fake).write("claim", b"{}", expected_generation=token)
                fake.assert_not_called()
        for raw in (b"{}", b'{"ETag":"*"}', b'{"ETag":null}', b"not-json"):
            with self.subTest(raw=raw), self.assertRaises(bos.ObjectStoreError):
                store(run=Mock(return_value=subprocess.CompletedProcess([], 0, raw, b""))).read("state")

    def test_only_explicit_notfound_is_absent_and_denial_conflict_unknown_are_errors(self):
        cases = {"aws": [("NoSuchKey", None), ("AccessDenied", "denied"), ("ExpiredToken", "denied"),
                          ("NoSuchBucket", "error"), ("PreconditionFailed", "conflict"), ("404", "error")],
                 "gcp": [("HTTPError 404", "error"), ("HTTPError 403", "denied"),
                         ("HTTPError 412", "conflict"), ("network unavailable", "error")],
                 "azure": [("BlobNotFound", None), ("ContainerNotFound", "error"),
                           ("AuthorizationPermissionMismatch", "denied"), ("ConditionNotMet", "conflict")]}
        self.assertTrue(hasattr(bos, "ObjectAccessDenied"), "typed object failures missing")
        for cloud, errors in cases.items():
            for code, outcome in errors:
                with self.subTest(cloud=cloud, code=code):
                    fake = Mock(return_value=subprocess.CompletedProcess([], 1, b"", (code + " SYNTHETIC-SECRET").encode()))
                    target = store(cloud, run=fake)
                    if outcome is None:
                        self.assertIsNone(target.read("state"))
                    else:
                        cls = {"denied": bos.ObjectAccessDenied, "conflict": bos.ObjectConflict,
                               "error": bos.ObjectStoreError}[outcome]
                        with self.assertRaises(cls) as caught:
                            target.read("state")
                        self.assertNotIn("SYNTHETIC-SECRET", str(caught.exception))
        with self.assertRaises(bos.ObjectStoreError):
            store(run=Mock(side_effect=subprocess.TimeoutExpired("secret", 1))).read("state")

    def test_azure_uses_entra_auth_and_etag_conditions(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            if "show" in argv:
                raw = {"properties": {"etag": '"one"'}}
            elif "download" in argv:
                Path(argv[argv.index("--file") + 1]).write_bytes(b"{}")
                raw = {}
            else:
                raw = {"etag": '"two"'}
            return subprocess.CompletedProcess(argv, 0, json.dumps(raw).encode(), b"")
        target = store("azure", run=run)
        self.assertEqual(target.read("manifest").generation, '"one"')
        self.assertEqual(target.write("claim", b"{}"), '"two"')
        target.write("claim", b"{}", expected_generation='"one"')
        for argv in calls:
            self.assertIn("--auth-mode", argv)
            self.assertIn("login", argv)
            self.assertNotIn("--account-key", argv)
            self.assertIn("--subscription", argv)
        self.assertIn("--if-match", calls[1])
        self.assertIn("--if-none-match", calls[2])
        self.assertIn("--if-match", calls[3])

    def test_gcs_reads_pinned_generation_and_writes_with_generation_cas(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            if "describe" in argv:
                return subprocess.CompletedProcess(argv, 0, b'{"generation":"17"}', b"")
            if argv[-1].endswith("/object"):
                self.assertIn("#17", argv[-2])
                Path(argv[-1]).write_bytes(b"{}")
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        target = store("gcp", run=run)
        self.assertEqual(target.read("state").generation, "17")
        self.assertEqual(target.write("claim", b"{}"), "17")
        self.assertTrue(any("--if-generation-match=0" in call for call in calls))
        target.write("claim", b"{}", expected_generation="17")
        self.assertTrue(any("--if-generation-match=17" in call for call in calls))
        self.assertTrue(all("gcloud" == call[0] for call in calls))

    def test_s3_read_and_conditional_write_use_exact_key_owner_and_private_file(self):
        self.assertIsNotNone(bos, "object store implementation missing")
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            if "get-object" in argv:
                Path(argv[-1]).write_bytes(b'{"example":"bytes"}')
                return subprocess.CompletedProcess(argv, 0, b'{"ETag":"\\"read-etag\\""}', b"")
            path = Path(argv[argv.index("--body") + 1])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_bytes(), b"{}")
            return subprocess.CompletedProcess(argv, 0, b'{"ETag":"\\"write-etag\\""}', b"")
        target = store(run=run)
        result = target.read("manifest")
        self.assertEqual(result.data, b'{"example":"bytes"}')
        self.assertEqual(result.generation, '"read-etag"')
        self.assertNotIn("bytes", repr(result))
        target.write("manifest", b"{}")
        target.write("manifest", b"{}", expected_generation=result.generation)
        self.assertIn("--if-none-match", calls[1])
        self.assertIn("--if-match", calls[2])
        self.assertIn("--expected-bucket-owner", calls[0])
        self.assertEqual(calls[0][calls[0].index("--key") + 1],
                         target.identity["object_key"] + ".isaac-manifest-v1.json")
        self.assertNotEqual(target.key("claim"), target.key("state"))
        with self.assertRaises(ValueError):
            target.write("state", b"{}")


if __name__ == "__main__":
    unittest.main()
