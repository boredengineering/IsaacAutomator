"""Migration tests: synthetic state only; cloud subprocesses are never run."""
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import shutil
import unittest
from unittest.mock import patch

from src.python.backend_object_store import ProtectedObjectCoordinator, StoredObject, ObjectConflict
from src.python.deployment_manifest import DeploymentManifest, StateSummary, canonical
from src.python.deployment_state import StateObservation, StateStatus, VerifiedScope
from src.python.terraform_backend import BackendSpec

OWNER = "11111111-1111-4111-8111-111111111111"
STATE = {"version": 4, "terraform_version": "1.8.5", "lineage": OWNER, "serial": 3,
         "outputs": {"answer": {"value": "private-fixture-value", "type": "string"}},
         "resources": [{"mode": "managed", "type": "terraform_data", "name": "example",
                        "provider": "provider[\"terraform.io/builtin/terraform\"]",
                        "instances": [{"schema_version": 0, "attributes": {"id": "fixture-id"}}]}]}


class MemoryStore:
    def __init__(self, identity, events, label):
        self.identity, self.events, self.label = identity, events, label
        self.objects = {}
        self.number = 0
        self.fail_kind = None

    def read(self, kind):
        return self.objects.get(kind)

    def write(self, kind, data, *, expected_generation=None):
        self.events.append((self.label, kind))
        if kind == self.fail_kind:
            raise RuntimeError("private provider diagnostics")
        old = self.objects.get(kind)
        if (old.generation if old else None) != expected_generation:
            raise ObjectConflict("CAS conflict")
        self.number += 1
        self.objects[kind] = StoredObject(data, str(self.number))
        return str(self.number)


def spec(prefix):
    return BackendSpec.from_dict({"backend": "s3", "namespace": "example", "destination": {
        "bucket": "example-state", "region": "us-east-1", "owner_account_id": "123456789012",
        "key_prefix": prefix}}, cloud="aws")


class MigrationTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.backend_migration"),
                             "explicit migration service is missing")
        return importlib.import_module("src.python.backend_migration")

    def fixture(self, root):
        bm = self.module()
        events = []
        ends = []
        for label in ("source", "destination"):
            backend = spec(label)
            store = MemoryStore(backend.identity("123456789012", "demo"), events, label)
            coordinator = ProtectedObjectCoordinator(store, authorize=lambda *args: None)
            ends.append(bm.MigrationEndpoint(backend, "123456789012", "demo", coordinator=coordinator,
                verify_scope=lambda identity: VerifiedScope(canonical(identity), "test-principal")))
        source, destination = ends
        summary = StateSummary.from_state(STATE)
        manifest = DeploymentManifest.create(backend_spec=source.backend_spec,
            target_scope=source.target_scope, deployment_name=source.deployment_name,
            lineage=summary.lineage, serial=summary.serial, addresses=summary.addresses)
        claim = source.coordinator.claim_new(OWNER)
        source.coordinator.store.write("state", canonical(STATE).encode())
        self.assertFalse(source.coordinator.complete_creation(claim, manifest).recovery_needed)
        events.clear()
        approval = bm.SupervisedApproval(canonical(source.exact_identity), canonical(destination.exact_identity),
            operator="test-operator", source_write_fence_attestation="All writers paused until manual retirement",
            acknowledge_unmanaged_writer_risk=True,
            maintenance_deadline=datetime.now(timezone.utc) + timedelta(minutes=5))
        @contextmanager
        def lease(endpoint, deadline):
            events.append(("lease", canonical(endpoint.exact_identity)))
            yield
        class Adapter:
            calls = 0
            def migrate(self, source, destination, *, guard, recovery_directory):
                self.calls += 1
                guard.authorize(self)
                events.append(("native", "copy"))
                destination.coordinator.store.write("state", source.coordinator.store.read("state").data)
        adapter = Adapter()
        service = bm.BackendMigration(source, destination, admin_root=root, adapter=adapter, lease_factory=lease)
        return bm, service, source, destination, manifest, approval, events, adapter

    def test_approval_requires_exact_identities_nonempty_fence_and_live_deadline(self):
        cases = [dict(source_identity="{}"), dict(destination_identity="{}"), dict(operator=" "),
                 dict(source_write_fence_attestation=""), dict(acknowledge_unmanaged_writer_risk=False),
                 dict(acknowledge_unmanaged_writer_risk=1), dict(maintenance_deadline=None),
                 dict(maintenance_deadline=datetime.now()),
                 dict(maintenance_deadline=datetime.now(timezone.utc) - timedelta(seconds=1))]
        for changes in cases:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                observation = source.observe()
                with self.assertRaises(bm.MigrationError):
                    service.migrate(source_manifest=manifest, source_observation=observation,
                                    approval=replace(approval, **changes))
                self.assertEqual(adapter.calls, 0)
                self.assertFalse(destination.coordinator.store.objects)
                self.assertIsNone(source.coordinator.store.read("relocation"))
                self.assertEqual(source.coordinator.require_attachable()["status"], "active")

    def test_deadline_expiry_during_final_publication_requires_recovery(self):
        for phase in ("relocation-write", "relocation-read", "activation-check",
                      "activation-write", "activation-read", "completion-write"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                now = [datetime.now(timezone.utc)]
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return now[0]
                approval = replace(approval, maintenance_deadline=Clock.fromtimestamp(
                    approval.maintenance_deadline.timestamp(), timezone.utc))
                def expire():
                    now[0] = approval.maintenance_deadline
                source_write, source_read = source.coordinator.store.write, source.coordinator.store.read
                target_write, target_read = destination.coordinator.store.write, destination.coordinator.store.read
                check_claim = destination.coordinator.assert_claim
                persist = bm._persist
                def write_source(kind, data, **kwargs):
                    result = source_write(kind, data, **kwargs)
                    if kind == "relocation" and phase == "relocation-write":
                        expire()
                    return result
                def read_source(kind):
                    result = source_read(kind)
                    if kind == "relocation" and result is not None and phase == "relocation-read":
                        expire()
                    return result
                def assert_claim(*args):
                    result = check_claim(*args)
                    if source_read("relocation") is not None and phase == "activation-check":
                        expire()
                    return result
                def write_target(kind, data, **kwargs):
                    result = target_write(kind, data, **kwargs)
                    if kind == "claim" and json.loads(data)["status"] == "active" and phase == "activation-write":
                        expire()
                    return result
                def read_target(kind):
                    result = target_read(kind)
                    if (kind == "claim" and result is not None and json.loads(result.data)["status"] == "active"
                            and phase == "activation-read"):
                        expire()
                    return result
                def write_receipt(directory, name, data):
                    persist(directory, name, data)
                    if name == "completed.json" and phase == "completion-write":
                        expire()
                with patch.object(bm, "datetime", Clock), patch.object(bm, "_persist", write_receipt), \
                        patch.object(source.coordinator.store, "write", write_source), \
                        patch.object(source.coordinator.store, "read", read_source), \
                        patch.object(destination.coordinator.store, "write", write_target), \
                        patch.object(destination.coordinator.store, "read", read_target), \
                        patch.object(destination.coordinator, "assert_claim", assert_claim):
                    result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertEqual(result.status, "recovery_required")
                self.assertTrue(result.recovery_needed)
                self.assertIsNotNone(source_read("relocation"))
                if phase in ("relocation-write", "relocation-read", "activation-check"):
                    self.assertEqual(json.loads(target_read("claim").data)["status"], "pending")
                if phase != "completion-write":
                    self.assertFalse((result.recovery_directory / "completed.json").exists())
                self.assertTrue((result.recovery_directory / "destination-state.json").is_file())

    def test_changed_content_after_copy_never_publishes_or_retires(self):
        for field in ("outputs", "resources", "extra"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                original = adapter.migrate
                def corrupt(*args, **kwargs):
                    original(*args, **kwargs)
                    state = copy.deepcopy(STATE)
                    if field == "outputs":
                        state["outputs"]["answer"]["value"] = "changed-secret"
                    elif field == "resources":
                        state["resources"][0]["instances"][0]["attributes"]["id"] = "changed-id"
                    else:
                        state["unexpected"] = True
                    store = destination.coordinator.store
                    store.write("state", canonical(state).encode(), expected_generation=store.read("state").generation)
                adapter.migrate = corrupt
                result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertTrue(result.recovery_needed)
                self.assertTrue(result.source_authoritative)
                self.assertIsNone(destination.coordinator.store.read("manifest"))
                self.assertIsNone(source.coordinator.store.read("relocation"))
                self.assertEqual(source.coordinator.store.read("state").data, canonical(STATE).encode())

    def test_unchanged_physical_location_and_workload_changes_are_refused_before_leases(self):
        for change in ("same", "scope", "name", "cloud", "alias"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                if change == "same":
                    destination = source
                elif change == "scope":
                    destination = replace(destination, target_scope="999999999999")
                elif change == "name":
                    destination = replace(destination, deployment_name="other")
                elif change == "cloud":
                    destination = replace(destination, backend_spec=BackendSpec.from_dict({}, cloud="gcp"),
                                          target_scope="example-project", state_root=Path(root) / "cross-cloud")
                else:
                    config = source.backend_spec.to_dict()
                    config["destination"]["region"] = "us-west-2"
                    destination = replace(destination, backend_spec=BackendSpec.from_dict(config, cloud="aws"))
                service.destination = destination
                approval = replace(approval, destination_identity=canonical(destination.exact_identity))
                with self.assertRaises(bm.MigrationError):
                    service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertEqual(events, [])
                self.assertEqual(adapter.calls, 0)

    def test_source_race_after_native_copy_retains_frozen_source_without_publication(self):
        with tempfile.TemporaryDirectory() as root:
            bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
            original = adapter.migrate
            def race(*args, **kwargs):
                original(*args, **kwargs)
                current = source.coordinator.store.read("state")
                state = copy.deepcopy(STATE)
                state["serial"] += 1
                source.coordinator.store.write("state", canonical(state).encode(), expected_generation=current.generation)
            adapter.migrate = race
            result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
            self.assertTrue(result.recovery_needed)
            self.assertIsNone(source.coordinator.store.read("relocation"))
            self.assertIsNone(destination.coordinator.store.read("manifest"))
            self.assertEqual(json.loads(source.coordinator.store.read("claim").data)["status"], "unknown")

    def test_native_local_move_uses_real_terraform_and_retires_old_path(self):
        self.native_local_move()

    def test_native_local_completion_failure_persists_destination_recovery_authority(self):
        self.native_local_move(completion_failure=True)

    def test_committed_but_failed_publication_never_claims_source_authority(self):
        for phase in ("retirement", "activation"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                store = source.coordinator.store if phase == "retirement" else destination.coordinator.store
                write = store.write
                def committed_failure(kind, data, **kwargs):
                    generation = write(kind, data, **kwargs)
                    if ((phase == "retirement" and kind == "relocation") or
                            (phase == "activation" and kind == "claim" and json.loads(data)["status"] == "active")):
                        raise OSError("synthetic lost write response")
                    return generation
                store.write = committed_failure
                result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertTrue(result.recovery_needed)
                self.assertFalse(result.source_authoritative)
                self.assertIsNotNone(source.coordinator.store.read("relocation"))
                recovery = json.loads((result.recovery_directory / "recovery-required.json").read_bytes())
                self.assertEqual(recovery["authority"], "indeterminate")
                self.assertEqual(recovery["attempted_phase"], "source_retirement" if phase == "retirement" else "destination_activation")
                self.assertNotIn("destination_activation", recovery["confirmed_receipts"])
                if phase == "activation":
                    self.assertEqual(destination.coordinator.require_attachable()["status"], "active")
                    receipt = json.loads((result.recovery_directory / "source-retirement.json").read_bytes())
                    self.assertEqual(receipt["generation"], source.coordinator.store.read("relocation").generation)
                self.assertFalse((result.recovery_directory / "completed.json").exists())

    def test_native_local_deadline_expiry_stops_retirement_or_completion(self):
        for phase in ("activation-read", "local-retire", "completion-write"):
            with self.subTest(phase=phase):
                self.native_local_move(expire_after=phase)

    def native_local_move(self, *, completion_failure=False, expire_after=None):
        bm = self.module()
        self.assertTrue(hasattr(bm, "NativeMigrationRunner"), "production native migration bridge missing")
        binary = shutil.which("terraform")
        self.assertIsNotNone(binary, "real Terraform acceptance fixture requires an installed binary")
        from src.python.terraform_runner import TerraformRunner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = root / "approved-source"
            code.mkdir(mode=0o700)
            (code / "main.tf").write_text('resource "terraform_data" "example" { input = "synthetic fixture" }\n'
                                          'output "answer" { value = terraform_data.example.output }\n')
            local = BackendSpec.from_dict({}, cloud="aws")
            environment = {"PATH": os.environ["PATH"], "HOME": str(root / "empty-home"),
                           "CHECKPOINT_DISABLE": "1"}
            with TerraformRunner(source_root=code, source_files=["main.tf"], backend_spec=local,
                    target_scope=None, deployment_name="demo", state_root=root / "source",
                    environment=environment, terraform_binary=binary, lock_root=root / "locks") as runner:
                runner.init()
                runner.apply(runner.plan(), acknowledge_mutation=True)
            raw = json.loads((root / "source/demo/.tfstate").read_bytes())
            summary = StateSummary.from_state(raw)
            manifest = DeploymentManifest.create(backend_spec=local, target_scope=None, deployment_name="demo",
                lineage=summary.lineage, serial=summary.serial, addresses=summary.addresses)
            endpoints = [bm.MigrationEndpoint.local(local, None, "demo", state_root=root / name)
                         for name in ("source", "destination")]
            source, destination = endpoints
            # Fixture enrollment is explicit. Production migration never adopts
            # preexisting unclaimed state or guesses a local receipt.
            source.coordinator.store.write("manifest", manifest.canonical_json().encode())
            source.coordinator.store.write("claim", canonical({"schema_version": 1,
                "identity": source.identity, "owner_id": OWNER, "status": "active",
                "lineage": summary.lineage}).encode())
            approval = bm.SupervisedApproval(canonical(source.exact_identity), canonical(destination.exact_identity),
                "fixture-operator", "Only synthetic fixture writer is paused", True,
                datetime.now(timezone.utc) + timedelta(minutes=5))
            adapter = bm.NativeMigrationRunner(source_root=code, source_files=["main.tf"],
                environment={**environment, "TF_CLI_ARGS_init": "-reconfigure", "TF_DATA_DIR": "/do-not-use"},
                terraform_binary=binary)
            service = bm.BackendMigration(source, destination, admin_root=root / "admin", adapter=adapter,
                                           lock_root=root / "locks")
            persist = bm._persist
            now = [datetime.now(timezone.utc)]
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now[0]
            approval = replace(approval, maintenance_deadline=Clock.fromtimestamp(
                approval.maintenance_deadline.timestamp(), timezone.utc))
            target_read = destination.coordinator.store.read
            retire = source.coordinator.store.retire_state
            def read_target(kind):
                stored = target_read(kind)
                if (expire_after == "activation-read" and kind == "claim" and stored is not None
                        and json.loads(stored.data)["status"] == "active"):
                    now[0] = approval.maintenance_deadline
                return stored
            def retire_source(expected):
                self.assertLess(now[0], approval.maintenance_deadline, "local retirement started after expiry")
                retire(expected)
                if expire_after == "local-retire":
                    now[0] = approval.maintenance_deadline
            def write_receipt(directory, name, data):
                if completion_failure and name == "completed.json":
                    raise OSError("synthetic private completion failure")
                persist(directory, name, data)
                if expire_after == "completion-write" and name == "completed.json":
                    now[0] = approval.maintenance_deadline
            with patch.object(bm, "_persist", write_receipt), patch.object(bm, "datetime", Clock), \
                    patch.object(destination.coordinator.store, "read", read_target), \
                    patch.object(source.coordinator.store, "retire_state", retire_source):
                result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
            self.assertEqual(result.status, "recovery_required" if completion_failure or expire_after else "supervised_retirement_required")
            if expire_after:
                self.assertTrue(result.recovery_needed)
                self.assertFalse(result.source_authoritative)
                recovery = json.loads((result.recovery_directory / "recovery-required.json").read_bytes())
                self.assertEqual(recovery["authority"], "destination")
                self.assertFalse(recovery["source_authoritative"])
                self.assertEqual((result.recovery_directory / "completed.json").exists(), expire_after == "completion-write")
            if completion_failure:
                self.assertTrue(result.recovery_needed)
                self.assertFalse(result.source_authoritative, "retired local source is not authoritative")
                recovery = json.loads((result.recovery_directory / "recovery-required.json").read_bytes())
                self.assertEqual(recovery["authority"], "destination")
                self.assertFalse(recovery["source_authoritative"])
                self.assertEqual(recovery["last_confirmed_phase"], "local_source_retired")
                self.assertEqual(recovery["attempted_phase"], "completion")
                self.assertEqual(recovery["source"], source.exact_identity)
                self.assertEqual(recovery["destination"], destination.exact_identity)
                self.assertFalse((result.recovery_directory / "completed.json").exists())
                for name in ("source-retirement.json", "destination-activation.json", "local-source-retired.json"):
                    self.assertTrue((result.recovery_directory / name).is_file())
                self.assertEqual((result.recovery_directory / "recovery-required.json").stat().st_mode & 0o777, 0o600)
                self.assertNotIn("synthetic private", repr(recovery))
            copied = json.loads((root / "destination/demo/.tfstate").read_bytes())
            self.assertEqual(copied["lineage"], raw["lineage"])
            self.assertEqual(copied["resources"], raw["resources"])
            self.assertEqual(copied["outputs"], raw["outputs"])
            self.assertEqual((root / "source/demo/.tfstate").exists(), expire_after == "activation-read")
            self.assertEqual((root / "source/demo/.tfstate.retired").is_file(), expire_after != "activation-read")
            self.assertTrue((root / "source/demo/migration.json").is_file())
            self.assertTrue((root / "source/demo/relocation.json").is_file())
            with self.assertRaises(ObjectConflict):
                source.coordinator.require_attachable()
            self.assertEqual(destination.coordinator.require_attachable()["lineage"], raw["lineage"])
            self.assertTrue((result.recovery_directory / "native/source/migration-plan.json").is_file())
            self.assertEqual(json.loads((result.recovery_directory / "source-state.json").read_bytes()), raw)
            self.assertEqual((result.recovery_directory / "source-state.json").stat().st_mode & 0o777, 0o600)
            journal = json.loads((result.recovery_directory / "native-commands.json").read_bytes())
            migration = [args for args in journal if "-migrate-state" in args]
            self.assertEqual(len(migration), 1)
            self.assertIn("-force-copy", migration[0])
            self.assertFalse(any("-reconfigure" in args for args in journal))
            self.assertFalse((code / ".terraform").exists())

    def test_source_claim_lineage_must_match_authoritative_state_before_copy(self):
        with tempfile.TemporaryDirectory() as root:
            bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
            store = source.coordinator.store
            stored = store.read("claim")
            claim = json.loads(stored.data)
            claim["lineage"] = "22222222-2222-4222-8222-222222222222"
            store.write("claim", canonical(claim).encode(), expected_generation=stored.generation)
            observation = StateObservation(StateStatus.POPULATED, canonical(source.exact_identity),
                                           StateSummary.from_state(STATE))
            with self.assertRaises(bm.MigrationError):
                service.migrate(source_manifest=manifest, source_observation=observation, approval=approval)
            self.assertEqual(adapter.calls, 0)
            self.assertFalse(destination.coordinator.store.objects)

    def test_unknown_destination_or_existing_claim_never_triggers_copy(self):
        for occupied in ("state", "manifest", "claim", "relocation", "denied"):
            with self.subTest(occupied=occupied), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                store = destination.coordinator.store
                if occupied == "denied":
                    def denied(kind):
                        raise PermissionError("private-provider-message")
                    store.read = denied
                else:
                    store.write(occupied, b"occupied")
                result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertTrue(result.recovery_needed)
                self.assertTrue(result.source_authoritative)
                self.assertEqual(adapter.calls, 0)
                self.assertEqual(source.coordinator.require_attachable()["status"], "active")

    def test_partial_native_or_publication_failures_keep_both_receipts_without_retry(self):
        for phase in ("native", "manifest", "relocation", "activation"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                original = adapter.migrate
                def fail(*args, **kwargs):
                    original(*args, **kwargs)
                    if phase == "native":
                        raise RuntimeError("secret native diagnostics")
                    if phase == "manifest":
                        destination.coordinator.store.fail_kind = "manifest"
                    if phase == "relocation":
                        source.coordinator.store.fail_kind = "relocation"
                    if phase == "activation":
                        destination.coordinator.store.fail_kind = "claim"
                adapter.migrate = fail
                observation = source.observe()
                result = service.migrate(source_manifest=manifest, source_observation=observation, approval=approval)
                self.assertEqual(result.status, "recovery_required")
                self.assertEqual(result.source_authoritative, phase in ("native", "manifest"))
                recovery = json.loads((result.recovery_directory / "recovery-required.json").read_bytes())
                self.assertEqual(recovery["authority"], "source" if phase in ("native", "manifest") else "indeterminate")
                self.assertEqual(recovery["attempted_phase"], {
                    "native": "native_copy", "manifest": "destination_manifest",
                    "relocation": "source_retirement", "activation": "destination_activation"}[phase])
                self.assertEqual(recovery["last_confirmed_phase"], {
                    "native": "source_frozen", "manifest": "destination_verified",
                    "relocation": "destination_manifest_published", "activation": "source_retired"}[phase])
                self.assertEqual(adapter.calls, 1)
                self.assertEqual(source.coordinator.store.read("state").data, canonical(STATE).encode())
                self.assertIsNotNone(destination.coordinator.store.read("state"))
                self.assertTrue((result.recovery_directory / "source-state.json").is_file())
                self.assertTrue((result.recovery_directory / "destination-manifest.json").is_file())
                self.assertEqual(json.loads(source.coordinator.store.read("claim").data)["status"], "unknown")
                self.assertEqual(json.loads(destination.coordinator.store.read("claim").data)["status"], "pending")
                with self.assertRaises(bm.MigrationError):
                    service.migrate(source_manifest=manifest, source_observation=observation, approval=approval)
                self.assertEqual(adapter.calls, 1)
                self.assertNotIn("secret", repr(result))

    def test_guard_rejects_pre_copy_races_and_reused_capabilities(self):
        for change in ("source", "destination", "scope", "guard-context", "guard-reuse", "unguarded"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                accepted = []
                def race(source, destination, *, guard, recovery_directory):
                    if change == "source":
                        store = source.coordinator.store
                        store.write("state", b"changed", expected_generation=store.read("state").generation)
                    if change == "destination":
                        destination.coordinator.store.write("state", canonical(STATE).encode())
                    if change == "scope":
                        source.coordinator._authorize = lambda *_: False
                    if change == "unguarded":
                        return
                    guard.authorize(object() if change == "guard-context" else adapter)
                    if change == "guard-reuse":
                        guard.authorize(adapter)
                    accepted.append(True)
                adapter.migrate = race
                result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertEqual(accepted, [])
                self.assertTrue(result.recovery_needed)
                self.assertIsNone(destination.coordinator.store.read("manifest"))
                self.assertIsNone(source.coordinator.store.read("relocation"))

    def test_destination_manifest_must_be_read_back_before_retirement(self):
        with tempfile.TemporaryDirectory() as root:
            bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
            write = destination.coordinator.store.write
            def substitute(kind, data, **kwargs):
                if kind == "manifest":
                    data = manifest.canonical_json().encode()  # wrong backend, same state summary
                return write(kind, data, **kwargs)
            destination.coordinator.store.write = substitute
            result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
            self.assertTrue(result.recovery_needed)
            self.assertIsNone(source.coordinator.store.read("relocation"))
            self.assertEqual(json.loads(destination.coordinator.store.read("claim").data)["status"], "pending")

    def test_local_endpoint_cannot_observe_a_different_store_root(self):
        bm = self.module()
        with tempfile.TemporaryDirectory() as root:
            local = BackendSpec.from_dict({}, cloud="aws")
            endpoint = bm.MigrationEndpoint.local(local, None, "demo", state_root=Path(root) / "one")
            redirected = replace(endpoint, state_root=Path(root) / "two")
            with self.assertRaises(bm.MigrationError):
                redirected.scope()

    def test_remote_to_local_requires_acknowledging_loss_of_shared_coordination(self):
        with tempfile.TemporaryDirectory() as root:
            bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
            local = BackendSpec.from_dict({}, cloud="aws")
            destination = bm.MigrationEndpoint.local(local, source.target_scope, "demo", state_root=Path(root) / "local")
            service.destination = destination
            approval = replace(approval, destination_identity=canonical(destination.exact_identity))
            with self.assertRaises(bm.MigrationError):
                service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(events, [])

    def test_retirement_and_activation_require_confirmed_publication_receipts(self):
        for phase in ("retirement", "activation"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
                store = source.coordinator.store if phase == "retirement" else destination.coordinator.store
                write = store.write
                def drop(kind, data, **kwargs):
                    if (phase == "retirement" and kind == "relocation") or (phase == "activation" and kind == "claim"
                            and json.loads(data)["status"] == "active"):
                        return "unconfirmed-receipt"
                    return write(kind, data, **kwargs)
                store.write = drop
                result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
                self.assertTrue(result.recovery_needed)
                self.assertFalse((result.recovery_directory / "completed.json").exists())

    def test_native_serial_version_changes_retain_exact_verified_destination_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
            original = adapter.migrate
            def advance(*args, **kwargs):
                original(*args, **kwargs)
                store = destination.coordinator.store
                after = copy.deepcopy(STATE)
                after.update(serial=4, terraform_version="1.10.0")
                store.write("state", canonical(after).encode(), expected_generation=store.read("state").generation)
                store.fail_kind = "manifest"
            adapter.migrate = advance
            result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
            self.assertTrue(result.recovery_needed)
            receipt = result.recovery_directory / "verified-destination-manifest.json"
            self.assertTrue(receipt.is_file(), "verified destination receipt missing after publication failure")
            self.assertEqual(json.loads(receipt.read_bytes())["state"]["serial"], 4)
            self.assertEqual(json.loads((result.recovery_directory / "destination-state.json").read_bytes())["serial"], 4)
            self.assertIsNone(source.coordinator.store.read("relocation"))

    def test_supervised_move_preserves_state_and_publishes_manifest_before_source_retirement(self):
        with tempfile.TemporaryDirectory() as root:
            bm, service, source, destination, manifest, approval, events, adapter = self.fixture(root)
            result = service.migrate(source_manifest=manifest, source_observation=source.observe(), approval=approval)
            self.assertEqual(result.status, "supervised_retirement_required")
            self.assertFalse(result.recovery_needed)
            self.assertFalse(result.source_authoritative)
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(destination.coordinator.store.read("state").data, canonical(STATE).encode())
            self.assertEqual(events[:2], [("lease", identity) for identity in sorted([
                canonical(source.exact_identity), canonical(destination.exact_identity)])])
            self.assertLess(events.index(("destination", "manifest")), events.index(("source", "relocation")))
            with self.assertRaises(ObjectConflict):
                source.coordinator.require_attachable()
            self.assertEqual(destination.coordinator.require_attachable()["lineage"], OWNER)
            self.assertEqual(json.loads((result.recovery_directory / "source-state.json").read_bytes()), STATE)
            self.assertTrue((result.recovery_directory / "source-manifest.json").is_file())
            self.assertTrue((result.recovery_directory / "destination-manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
