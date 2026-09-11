"""Offline service contracts: remote transport/runner are test doubles only."""
import copy
import json
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import Mock

from src.python.terraform_backend import BackendSpec
from src.python.deployment_manifest import DeploymentManifest, LocalManifestStore
from src.python.deployment_manifest import canonical, digest
from src.python.backend_object_store import ProtectedObjectCoordinator, StoredObject, ObjectConflict
try:
    from src.python import deployment_state as ds
except ImportError:
    ds = None

SCOPE = "123456789012"
LINEAGE = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
SECRET = "SYNTHETIC-SECRET"


def spec(remote=False):
    return BackendSpec.from_dict({"backend": "s3", "namespace": "example", "destination": {
        "bucket": "example-state", "region": "us-east-1", "owner_account_id": SCOPE,
        "key_prefix": "isaacautomator/v2"}} if remote else {}, cloud="aws")


def state(serial=3, resources=True):
    return {"version": 4, "lineage": LINEAGE, "serial": serial,
        "outputs": {"settings": {"value": {"enabled": True, "ports": [22, 443], "secret": SECRET},
                                  "sensitive": True, "type": ["object", {}]},
                    "count": {"value": 2, "sensitive": False, "type": "number"}},
        "resources": [{"mode": "managed", "type": "aws_instance", "name": "workstation",
                       "instances": [{"attributes": {"password": SECRET}}]}] if resources else []}


def manifest(remote=False):
    return DeploymentManifest.create(backend_spec=spec(remote), target_scope=SCOPE,
        deployment_name="demo", lineage=LINEAGE, serial=3, addresses=["aws_instance.workstation"])


class FakeRunner:
    def __init__(self, backend, events, current=None):
        self.backend_identity = json.dumps(backend.identity(SCOPE, "demo"), sort_keys=True, separators=(",", ":"))
        self.events = events
        self.current = state() if current is None else current
        self.plan_value = object()

    def __enter__(self):
        self.events.append("enter")
        if hasattr(self, "on_enter"):
            self.on_enter()
        return self

    def __exit__(self, *args):
        self.events.append("exit")
        if hasattr(self, "exit_error"):
            raise self.exit_error

    def init(self):
        self.events.append("init")

    def pull_state(self):
        self.events.append("pull")
        return copy.deepcopy(self.current)

    def output(self):
        self.events.append("output")
        return copy.deepcopy(self.current["outputs"])

    def plan(self, *, destroy=False):
        self.events.append("plan:destroy" if destroy else "plan:apply")
        return self.plan_value

    def apply(self, plan, *, acknowledge_mutation=False):
        if plan is not self.plan_value or acknowledge_mutation is not True:
            raise AssertionError("unapproved plan")
        self.events.append("apply")
        self.current = state(4)
        if hasattr(self, "apply_error"):
            raise self.apply_error


class MemoryObjects:
    """Only an offline test transport; never used by production."""
    def __init__(self, events, attached=True):
        self.identity = spec(True).identity(SCOPE, "demo")
        self.events = events
        self.objects = {}
        self.writes = []
        if attached:
            self.objects = {
                "state": StoredObject(canonical(state()).encode(), "state-3"),
                "manifest": StoredObject(manifest(True).canonical_json().encode(), "manifest-1"),
                "claim": StoredObject(canonical({"schema_version": 1, "identity": self.identity,
                    "owner_id": OWNER, "status": "active", "lineage": LINEAGE}).encode(), "claim-1")}

    def read(self, kind):
        self.events.append("read:" + kind)
        return self.objects.get(kind)

    def write(self, kind, data, *, expected_generation=None):
        old = self.objects.get(kind)
        if (old.generation if old else None) != expected_generation:
            raise ObjectConflict("occupied")
        generation = str(len(self.writes) + 1)
        self.objects[kind] = StoredObject(data, generation)
        self.writes.append(kind)
        self.events.append("write:" + kind)
        return generation


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ds, "deployment state service is missing")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local = LocalManifestStore(Path(self.temporary.name) / "state")
        self.events = []

    def remote(self, attached=True, **kwargs):
        self.objects = MemoryObjects(self.events, attached)
        coordinator = ProtectedObjectCoordinator(self.objects, authorize=lambda identity, operation: None)
        self.runner = FakeRunner(spec(True), self.events)
        self.scope = Mock(side_effect=lambda identity: ds.VerifiedScope(canonical(identity), "test-principal"))
        return ds.DeploymentState(backend_spec=spec(True), target_scope=SCOPE, deployment_name="demo",
            local_store=self.local, runner_factory=lambda **kw: self.runner,
            coordinator=coordinator, verify_scope=self.scope, **kwargs)

    def test_saved_descriptor_dispatches_local_runner_and_preserves_native_outputs(self):
        saved = manifest()
        self.local.save(saved)
        runner = FakeRunner(spec(), self.events)
        factory = Mock(return_value=runner)
        service = ds.DeploymentState.from_saved("demo", local_store=self.local, runner_factory=factory)
        observed = service.read()
        self.assertEqual(observed.status, ds.StateStatus.POPULATED)
        self.assertEqual(observed.lineage, LINEAGE)
        self.assertEqual(observed.serial, 3)
        self.assertEqual(json.loads(observed.source)["backend"], "local")
        self.assertEqual(observed.outputs.values["count"], 2)
        self.assertIs(observed.outputs.values["settings"]["enabled"], True)
        self.assertEqual(observed.outputs.values["settings"]["ports"], [22, 443])
        self.assertTrue(observed.outputs.metadata["settings"]["sensitive"])
        self.assertNotIn(SECRET, repr(observed))
        self.assertNotIn(SECRET, repr(observed.outputs))
        self.assertEqual(factory.call_args.kwargs["backend_spec"], spec())
        self.assertEqual(self.events, ["enter", "init", "pull", "output", "exit"])


    def test_reads_fail_closed_without_conflating_failure_and_empty(self):
        from src.python.backend_object_store import ObjectAccessDenied
        from src.python.terraform_runner import TerraformLockError
        runner = FakeRunner(spec(), self.events)
        service = ds.DeploymentState(backend_spec=spec(), target_scope=SCOPE, deployment_name="demo",
            local_store=self.local, runner_factory=lambda **kw: runner, descriptor=manifest())
        for error, status_name in [(ObjectAccessDenied(SECRET), "PERMISSION_DENIED"),
                                   (TerraformLockError(SECRET), "LOCKED"),
                                   (OSError(SECRET), "UNREACHABLE"),
                                   (RuntimeError(SECRET), "UNKNOWN")]:
            with self.subTest(status=status_name):
                runner.pull_state = Mock(side_effect=error)
                observed = service.read()
                self.assertEqual(observed.status.value, status_name.lower().replace("_", "-"))
                self.assertIsNone(observed.lineage)
                self.assertIsNone(observed.serial)
                self.assertIsNone(observed.outputs)
                self.assertNotIn(SECRET, repr(observed))
        runner.pull_state = lambda: state(resources=False)
        observed = service.read()
        self.assertEqual(observed.status.value, "identity-mismatch")
        service.descriptor = None  # Legacy local read, without invented attachment.
        self.assertEqual(service.read().status.value, "reachable-empty")
        runner.backend_identity = "{}"
        self.events.clear()
        self.assertEqual(service.read().status.value, "identity-mismatch")
        self.assertNotIn("init", self.events)


    def test_remote_attach_verifies_protected_evidence_before_init_and_writes_only_local_metadata(self):
        self.assertTrue(hasattr(ds.DeploymentState, "attach"), "read-only attach is missing")
        service = self.remote()
        attached = service.attach(manifest(True))
        self.assertEqual(attached, manifest(True))
        self.assertEqual(self.local.load("demo"), attached)
        self.assertEqual(self.objects.writes, [])
        self.assertLess(self.events.index("read:relocation"), self.events.index("init"))
        self.assertLess(self.events.index("read:state"), self.events.index("init"))
        self.assertEqual(self.scope.call_args.args[0], spec(True).identity(SCOPE, "demo"))
        self.assertEqual(service.read().outputs.values["count"], 2)
        self.assertFalse((Path(self.temporary.name) / "state" / "demo" / ".tfstate").exists())
        self.assertEqual(service.capabilities(), frozenset({"outputs"}))
        with self.assertRaises(ds.CapabilityError):
            service.require_capability("apply")


    def test_attach_rechecks_relocation_after_context_lock_before_init(self):
        service = self.remote()
        self.runner.on_enter = lambda: self.objects.objects.update(
            relocation=StoredObject(b"retired", "relocated"))
        with self.assertRaises(ds.DeploymentStateError) as caught:
            service.attach(manifest(True))
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn("init", self.events)
        self.assertEqual(self.objects.writes, [])
        self.assertFalse((Path(self.temporary.name) / "state").exists())

    def test_attach_rejects_scope_claim_lineage_serial_and_manifest_mismatch(self):
        for defect in ("scope", "pending", "lineage", "serial", "manifest", "readfail", "absent"):
            with self.subTest(defect=defect):
                self.events.clear()
                service = self.remote()
                if defect == "scope":
                    self.scope.side_effect = lambda identity: True
                elif defect == "readfail":
                    self.objects.read = Mock(side_effect=OSError(SECRET))
                elif defect == "absent":
                    del self.objects.objects["state"]
                elif defect in ("pending", "lineage"):
                    claim = json.loads(self.objects.objects["claim"].data)
                    claim.update({"status": "pending"} if defect == "pending" else {"lineage": OWNER})
                    self.objects.objects["claim"] = StoredObject(canonical(claim).encode(), "changed")
                elif defect == "serial":
                    self.objects.objects["state"] = StoredObject(canonical(state(4)).encode(), "state-4")
                else:
                    different = manifest(True).to_dict()
                    different["inputs"] = {"region": "us-west-2"}
                    different["baseline"]["input_sha256"] = digest(different["inputs"])
                    self.objects.objects["manifest"] = StoredObject(canonical(different).encode(), "other")
                with self.assertRaises(ds.DeploymentStateError) as caught:
                    service.attach(manifest(True))
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn("init", self.events)
                self.assertEqual(self.objects.writes, [])


    def test_runner_normalization_keeps_resource_fields_and_private_digests(self):
        service = self.remote()
        protected = state()
        protected["terraform_version"] = "1.8.0"
        del protected["outputs"]["count"]["sensitive"]
        self.objects.objects["state"] = StoredObject(json.dumps(protected, indent=2).encode(), "state-3")
        self.runner.current["terraform_version"] = "1.9.0"
        original = copy.deepcopy(self.runner.current)
        service.attach(manifest(True))
        self.assertEqual(service.read().status, ds.StateStatus.POPULATED)
        self.assertEqual(self.runner.current, original)
        snapshot = service._snapshot(service.descriptor)
        self.assertNotIn(snapshot._content_digest.hex(), repr(snapshot))
        self.assertNotIn(repr(snapshot._content_digest), repr(snapshot))
        self.assertNotIn(snapshot._runner_digest, repr(snapshot))
        self.assertNotIn(SECRET, repr(snapshot))
        # Even normalization-equivalent protected rewrites with a reused fake
        # generation must change the private exact-object binding.
        self.objects.objects["state"] = StoredObject(canonical(protected).encode(), "state-3")
        self.assertNotEqual(snapshot, service._snapshot(service.descriptor))
        for field in ("terraform_version", "sensitive"):
            changed = copy.deepcopy(original)
            changed["resources"][0]["instances"][0]["attributes"][field] = "real-resource-value"
            with self.assertRaises(ds.IdentityMismatch):
                snapshot.verify_state(changed)

    def test_exact_state_content_is_bound_at_attach_read_guard_and_outcome(self):
        for boundary in ("attach", "read", "pre-plan", "guard-runner", "guard-protected", "post"):
            for field in ("outputs", "attributes", "data", "private", "checks"):
                with self.subTest(boundary=boundary, field=field), tempfile.TemporaryDirectory() as temporary:
                    self.local = LocalManifestStore(Path(temporary) / "state")
                    def change(raw):
                        if field == "outputs":
                            raw["outputs"]["count"]["value"] = 99
                        elif field == "attributes":
                            raw["resources"][0]["instances"][0]["attributes"]["password"] = "changed"
                        elif field == "data":
                            raw["resources"].append({"mode": "data", "type": "aws_caller_identity",
                                "name": "current", "instances": [{"attributes": {"id": "changed"}}]})
                        elif field == "private":
                            raw["resources"][0]["instances"][0]["private"] = "changed"
                        else:
                            raw["check_results"] = [{"status": "fail"}]
                    def adapter(runner, plan, *, guard, operation):
                        if boundary.startswith("guard"):
                            change(runner.current)
                            if boundary == "guard-protected":
                                self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-3")
                        guard.authorize(runner, plan, operation)
                        runner.apply(plan, acknowledge_mutation=True)
                        self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
                        if boundary == "post":
                            change(runner.current)
                    service = self.remote(mutation_adapter=adapter, verify_materials=lambda d, op: None)
                    if boundary == "attach":
                        change(self.runner.current)
                        with self.assertRaises(ds.DeploymentStateError):
                            service.attach(manifest(True))
                        self.assertIsNone(service.descriptor)
                        continue
                    service.attach(manifest(True))
                    if boundary == "read":
                        change(self.runner.current)
                        observed = service.read()
                        self.assertEqual(observed.status, ds.StateStatus.IDENTITY_MISMATCH)
                        self.assertIsNone(observed.outputs)
                    elif boundary == "post":
                        result = service.apply(acknowledge_mutation=True)
                        self.assertEqual(result.infrastructure_status, "succeeded")
                        self.assertTrue(result.recovery_needed)
                        self.assertIsNone(result.observation.outputs)
                        self.assertEqual(self.local.load("demo"), manifest(True))
                    else:
                        if boundary == "pre-plan":
                            self.runner.init = lambda: change(self.runner.current)
                        with self.assertRaises(ds.DeploymentStateError):
                            service.apply(acknowledge_mutation=True)
                        self.assertNotIn("apply", self.events)
                        if boundary == "pre-plan":
                            self.assertNotIn("plan:apply", self.events)
                    self.assertEqual(self.objects.writes, [])
                    self.events.clear()

    def test_new_creator_reserves_with_cas_and_refuses_occupied_or_retired_destinations(self):
        self.assertTrue(hasattr(ds.DeploymentState, "reserve_new"), "creator reservation missing")
        service = self.remote(attached=False)
        reservation = service.reserve_new(OWNER)
        self.assertEqual(reservation.claim.owner_id, OWNER)
        self.assertIsNone(reservation.snapshot.summary)
        self.assertEqual(self.objects.writes, ["claim"])
        with self.assertRaises(ds.DeploymentStateError):
            service.reserve_new(LINEAGE)
        self.assertEqual(self.objects.writes, ["claim"])
        self.assertNotIn("init", self.events)
        for occupied in ("state", "manifest", "relocation"):
            service = self.remote(attached=False)
            self.objects.objects[occupied] = StoredObject(b"occupied", "old")
            with self.assertRaises(ds.DeploymentStateError):
                service.reserve_new(OWNER)
            self.assertEqual(self.objects.writes, [])
        service = self.remote(attached=False)
        self.objects.read = Mock(side_effect=OSError(SECRET))
        with self.assertRaises(ds.DeploymentStateError) as caught:
            service.reserve_new(OWNER)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(self.objects.writes, [])


    def test_local_partial_apply_retains_updated_descriptor_and_original_infrastructure_outcome(self):
        self.assertTrue(hasattr(ds.DeploymentState, "apply"), "lifecycle orchestration missing")
        saved = manifest()
        self.local.save(saved)
        runner = FakeRunner(spec(), self.events)
        runner.apply_error = RuntimeError(SECRET)
        materials = Mock(return_value=None)
        service = ds.DeploymentState.from_saved("demo", local_store=self.local,
            runner_factory=lambda **kw: runner, verify_materials=materials)
        result = service.apply(acknowledge_mutation=True)
        self.assertEqual(result.infrastructure_status, "failed")
        self.assertTrue(result.recovery_needed)
        self.assertEqual(result.observation.serial, 4)
        self.assertEqual(self.local.load("demo").to_dict()["state"]["serial"], 4)
        self.assertEqual(self.local.load("demo").identity, saved.identity)
        self.assertNotIn(SECRET, repr(result))
        self.assertEqual(materials.call_args.args, (saved, "apply"))
        self.assertEqual(self.events.count("apply"), 1)


    def test_remote_apply_passes_snapshot_bound_single_use_guard_and_publishes_after_state_verification(self):
        self.assertTrue(hasattr(ds, "RemoteMutationGuard"), "remote runner guard missing")
        guards = []
        def adapter(runner, plan, *, guard, operation):
            guards.append(guard)
            guard.authorize(runner, plan, operation)
            runner.apply(plan, acknowledge_mutation=True)
            self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
        service = self.remote(mutation_adapter=adapter, verify_materials=lambda descriptor, operation: None)
        service.attach(manifest(True))
        result = service.apply(acknowledge_mutation=True)
        self.assertEqual(result.infrastructure_status, "succeeded")
        self.assertFalse(result.recovery_needed)
        self.assertEqual(result.observation.serial, 4)
        self.assertEqual(self.objects.writes, ["manifest"])
        self.assertEqual(guards[0].snapshot.summary.serial, 3)
        self.assertEqual(guards[0].snapshot.scope.identity, canonical(service.identity))
        self.assertEqual(guards[0].snapshot.claim_generation, "claim-1")
        with self.assertRaises(ds.DeploymentStateError):
            guards[0].authorize(self.runner, self.runner.plan_value, "apply")


    def test_remote_guard_races_refuse_without_adopting_changed_state_or_publishing(self):
        for change in ("serial", "lineage", "claim", "relocation", "scope", "runner", "plan", "operation", "ignored"):
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as temporary:
                    self.local = LocalManifestStore(Path(temporary) / "state")
                    def adapter(runner, plan, *, guard, operation):
                        if change == "serial":
                            runner.current = state(4)
                            self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "new")
                        elif change == "lineage":
                            runner.current["lineage"] = OWNER
                            self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "new")
                        elif change == "claim":
                            old = self.objects.objects["claim"]
                            self.objects.objects["claim"] = StoredObject(old.data, "new")
                        elif change == "relocation":
                            self.objects.objects["relocation"] = StoredObject(b"retired", "new")
                        elif change == "scope":
                            self.scope.side_effect = lambda identity: ds.VerifiedScope(canonical(identity), "other-principal")
                        elif change == "ignored":
                            return
                        try:
                            guard.authorize(object() if change == "runner" else runner,
                                object() if change == "plan" else plan, "destroy" if change == "operation" else operation)
                        except ds.DeploymentStateError:
                            return  # A buggy adapter must not turn guard rejection into success.
                        runner.apply(plan, acknowledge_mutation=True)
                    service = self.remote(mutation_adapter=adapter, verify_materials=lambda d, op: None)
                    service.attach(manifest(True))
                    self.events.clear()
                    with self.assertRaises(ds.DeploymentStateError):
                        service.apply(acknowledge_mutation=True)
                    self.assertNotIn("apply", self.events)
                    self.assertEqual(self.objects.writes, [])
                    self.assertEqual(self.local.load("demo"), manifest(True))


    def test_initialized_empty_creation_captures_one_exact_receipt_through_guard(self):
        checks = []
        guards = []
        def adapter(runner, plan, *, guard, operation):
            guards.append(guard)
            guard.authorize(runner, plan, operation)
            runner.apply(plan, acknowledge_mutation=True)
            self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
        service = self.remote(attached=False, mutation_adapter=adapter, verify_materials=lambda d, op: None)
        verify = service.coordinator.verify_creation_state
        def checked(claim, **kwargs):
            receipt = verify(claim, **kwargs)
            checks.append((kwargs, receipt))
            return receipt
        service.coordinator.verify_creation_state = checked
        reservation = service.reserve_new(OWNER)
        def initialized():
            self.events.append("init")
            self.runner.current = state(0, resources=False)
            self.runner.current["outputs"] = {}
            self.objects.objects["state"] = StoredObject(canonical(self.runner.current).encode(), "init-0")
        self.runner.init = initialized
        result = service.apply(acknowledge_mutation=True, reservation=reservation,
            manifest_factory=lambda summary: DeploymentManifest.create(backend_spec=spec(True),
                target_scope=SCOPE, deployment_name="demo", **summary.to_dict()))
        self.assertEqual(result.infrastructure_status, "succeeded")
        self.assertFalse(result.recovery_needed)
        captures = [(index, receipt) for index, (kwargs, receipt) in enumerate(checks)
                    if kwargs.get("allow_initialized_empty") is True]
        self.assertEqual(len(captures), 1)
        index, receipt = captures[0]
        self.assertEqual(receipt.generation, "init-0")
        self.assertGreaterEqual(index, 2)  # reservation and protected pre-init absence
        self.assertTrue(all(observed is None for _, observed in checks[:index]))
        self.assertGreaterEqual(len(checks[index + 1:]), 2)  # pre-plan + guard
        for kwargs, observed in checks[index + 1:]:
            self.assertIs(kwargs["expected_state"], receipt)
            self.assertEqual(observed, receipt)
        self.assertIs(guards[0].snapshot._creation_state, receipt)
        self.assertEqual(guards[0].snapshot.state_generation, "init-0")
        self.assertNotIn(repr(receipt._content_digest), repr(guards[0].snapshot))
        self.assertEqual(self.events.count("apply"), 1)

    def test_creation_never_rebaselines_after_protected_preinit_absence(self):
        for timing in ("pre-init", "plan", "guard"):
            for change in ("generation", "bytes", "outputs", "resources", "disappeared", "late-empty", "runner"):
                with self.subTest(timing=timing, change=change), tempfile.TemporaryDirectory() as temporary:
                    self.local = LocalManifestStore(Path(temporary) / "state")
                    self.events.clear()
                    empty = state(0, resources=False)
                    empty["outputs"] = {}
                    def race():
                        if change == "disappeared":
                            self.objects.objects.pop("state", None)
                            return
                        raw = copy.deepcopy(empty)
                        if change == "outputs":
                            raw["outputs"] = state()["outputs"]
                        elif change == "resources":
                            raw["resources"] = state()["resources"]
                        elif change == "runner":
                            self.runner.current["check_results"] = [{"status": "fail"}]
                            return
                        encoded = json.dumps(raw, indent=2) if change == "bytes" else canonical(raw)
                        generation = "raced" if change in ("generation", "late-empty") else "init-0"
                        self.objects.objects["state"] = StoredObject(encoded.encode(), generation)
                    def adapter(runner, plan, *, guard, operation):
                        if timing == "guard":
                            race()
                        guard.authorize(runner, plan, operation)
                        self.events.append("apply")
                    service = self.remote(attached=False, mutation_adapter=adapter, verify_materials=lambda d, op: None)
                    reservation = service.reserve_new(OWNER)
                    def initialized():
                        self.events.append("init")
                        self.runner.current = copy.deepcopy(empty)
                        if change != "late-empty":
                            self.objects.objects["state"] = StoredObject(canonical(empty).encode(), "init-0")
                    self.runner.init = initialized
                    original_plan = self.runner.plan
                    def planned(**kwargs):
                        plan = original_plan(**kwargs)
                        if timing == "plan":
                            race()
                        return plan
                    self.runner.plan = planned
                    if timing == "pre-init":
                        # Even empty state cannot be adopted before this init.
                        self.runner.on_enter = lambda: self.objects.objects.update(
                            state=StoredObject(canonical(empty).encode(), "pre-existing"))
                    with self.assertRaises(ds.DeploymentStateError):
                        service.apply(acknowledge_mutation=True, reservation=reservation, manifest_factory=Mock())
                    self.assertNotIn("apply", self.events)
                    self.assertEqual(self.objects.writes, ["claim"])
                    self.assertIsNone(service.descriptor)
                    if timing == "pre-init":
                        self.assertNotIn("init", self.events)

    def test_reserved_creation_is_guarded_and_partial_apply_keeps_pending_claim_and_local_descriptor(self):
        for partial in (False, True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as temporary:
                self.local = LocalManifestStore(Path(temporary) / "state")
                def adapter(runner, plan, *, guard, operation):
                    guard.authorize(runner, plan, operation)
                    runner.apply(plan, acknowledge_mutation=True)
                    self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
                    if partial:
                        raise RuntimeError(SECRET)
                def build(summary):
                    return DeploymentManifest.create(backend_spec=spec(True), target_scope=SCOPE,
                        deployment_name="demo", **summary.to_dict())
                service = self.remote(attached=False, mutation_adapter=adapter, verify_materials=lambda d, op: None)
                reservation = service.reserve_new(OWNER)
                result = service.apply(acknowledge_mutation=True, reservation=reservation, manifest_factory=build)
                self.assertEqual(result.infrastructure_status, "failed" if partial else "succeeded")
                self.assertEqual(result.recovery_needed, partial)
                self.assertEqual(self.local.load("demo").to_dict()["state"]["serial"], 4)
                claim = json.loads(self.objects.objects["claim"].data)
                self.assertEqual(claim["status"], "pending" if partial else "active")
                self.assertLess(self.events.index("write:claim"), self.events.index("init"))
                self.assertEqual(self.events.count("apply"), 1)
                self.events.clear()


    def test_destroy_requires_same_backend_authoritative_managed_empty_state_for_tombstone(self):
        self.assertTrue(hasattr(ds.DeploymentState, "destroy"), "verified destruction missing")
        for outcome in ("empty", "managed", "wrong-backend", "readfail", "remote-mismatch"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                self.local = LocalManifestStore(Path(temporary) / "state")
                def adapter(runner, plan, *, guard, operation):
                    self.assertEqual(operation, "destroy")
                    guard.authorize(runner, plan, operation)
                    self.events.append("apply")
                    runner.current = state(4, resources=outcome == "managed")
                    runner.current["outputs"] = {}  # Empty outputs do NOT imply destroyed.
                    if outcome == "empty":
                        runner.current["resources"] = [{"mode": "data", "type": "aws_caller_identity",
                            "name": "current", "instances": [{"attributes": {}}]}]
                    self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
                    if outcome == "wrong-backend":
                        runner.backend_identity = "{}"
                    elif outcome == "readfail":
                        runner.pull_state = Mock(side_effect=OSError(SECRET))
                    elif outcome == "remote-mismatch":
                        self.objects.objects["state"] = StoredObject(canonical(state(4)).encode(), "other")
                service = self.remote(mutation_adapter=adapter, verify_materials=lambda d, op: None)
                service.attach(manifest(True))
                result = service.destroy(acknowledge_mutation=True)
                self.assertIn("plan:destroy", self.events)
                self.assertEqual(result.infrastructure_status, "succeeded")
                if outcome == "empty":
                    self.assertFalse(result.recovery_needed)
                    self.assertEqual(result.observation.status.value, "destroyed")
                    self.assertEqual(result.tombstone.source, canonical(service.identity))
                    self.assertEqual(result.tombstone.lineage, LINEAGE)
                    self.assertEqual(result.tombstone.serial, 4)
                    self.assertEqual(self.local.load("demo").to_dict()["state"]["addresses"], [])
                else:
                    self.assertTrue(result.recovery_needed)
                    self.assertIsNone(result.tombstone)
                    if outcome == "managed":
                        self.assertEqual(result.observation.status.value, "partially-destroyed")
                    else:
                        self.assertEqual(self.local.load("demo"), manifest(True))
                self.assertNotIn(SECRET, repr(result))


    def test_destroy_invalidates_cleanup_receipt_on_publication_or_recovery_uncertainty(self):
        from src.python.terraform_runner import TerraformRunnerError
        for failure in ("managed", "same-summary", "generation", "bytes", "publication", "local-save", "context-exit"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                self.local = LocalManifestStore(Path(temporary) / "state")
                self.events.clear()
                def adapter(runner, plan, *, guard, operation):
                    guard.authorize(runner, plan, operation)
                    runner.current = state(4, resources=False)
                    runner.current["outputs"] = {}
                    self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
                    if failure == "context-exit":
                        runner.exit_error = TerraformRunnerError("Retained recovery state " + SECRET)
                    elif failure == "local-save":
                        self.local.save = Mock(side_effect=OSError(SECRET))
                service = self.remote(mutation_adapter=adapter, verify_materials=lambda d, op: None)
                service.attach(manifest(True))
                write = self.objects.write
                def publishing(kind, data, **kwargs):
                    if failure == "publication":
                        raise OSError(SECRET)
                    generation = write(kind, data, **kwargs)
                    if kind == "manifest" and failure in ("managed", "same-summary", "generation", "bytes"):
                        raw = copy.deepcopy(self.runner.current)
                        if failure == "managed":
                            raw["resources"] = state()["resources"]
                        elif failure == "same-summary":
                            raw["outputs"] = state()["outputs"]
                        encoded = json.dumps(raw, indent=2) if failure == "bytes" else canonical(raw)
                        self.objects.objects["state"] = StoredObject(encoded.encode(),
                            "raced" if failure == "generation" else "state-4")
                    return generation
                self.objects.write = publishing
                result = service.destroy(acknowledge_mutation=True)
                self.assertEqual(result.infrastructure_status, "succeeded")
                self.assertTrue(result.recovery_needed)
                self.assertIsNone(result.tombstone)
                self.assertNotEqual(result.observation.status, ds.StateStatus.DESTROYED)
                self.assertIsNone(result.observation.outputs)
                self.assertIsNotNone(result.descriptor)
                self.assertNotIn(SECRET, repr(result))

    def test_outputs_are_detached_validated_and_never_mix_different_state_snapshots(self):
        entries = state()["outputs"]
        outputs = ds.DeploymentOutputs(entries)
        entries["count"]["value"] = 99
        self.assertEqual(outputs.values["count"], 2)
        values = outputs.values
        values["count"] = 88
        self.assertEqual(outputs.values["count"], 2)
        for malformed in ({"bad": {"value": SECRET}}, {"bad": {"value": 1, "type": "number", "sensitive": 1}},
                          {"bad": {"value": float("nan"), "type": "number", "sensitive": False}}):
            with self.assertRaises(ds.DeploymentStateError) as caught:
                ds.DeploymentOutputs(malformed)
            self.assertNotIn(SECRET, str(caught.exception))
        runner = FakeRunner(spec(), self.events)
        runner.output = lambda: entries
        service = ds.DeploymentState(backend_spec=spec(), target_scope=SCOPE, deployment_name="demo",
            local_store=self.local, runner_factory=lambda **kw: runner, descriptor=manifest())
        observed = service.read()
        self.assertEqual(observed.status.value, "identity-mismatch")
        self.assertIsNone(observed.outputs)


    def test_unattached_remote_absence_is_distinct_from_occupied_and_read_failure(self):
        service = self.remote(attached=False)
        self.assertEqual(service.read().status.value, "configured-not-created")
        self.objects.objects["state"] = StoredObject(canonical(state()).encode(), "existing")
        self.assertEqual(service.read().status.value, "attachment-required")
        self.objects.read = Mock(side_effect=OSError(SECRET))
        observed = service.read()
        self.assertEqual(observed.status.value, "unreachable")
        self.assertIsNone(observed.summary)
        self.assertNotIn("init", self.events)


    def test_remote_read_and_creation_recheck_fences_before_init_and_plan(self):
        service = self.remote()
        service.attach(manifest(True))
        self.events.clear()
        self.runner.on_enter = lambda: self.objects.objects.update(relocation=StoredObject(b"retired", "new"))
        self.assertEqual(service.read().status.value, "identity-mismatch")
        self.assertNotIn("init", self.events)
        self.events.clear()
        service = self.remote(attached=False, mutation_adapter=Mock(), verify_materials=lambda d, op: None)
        reservation = service.reserve_new(OWNER)
        def raced_init():
            self.events.append("init")
            self.objects.objects["state"] = StoredObject(canonical(state()).encode(), "appeared")
        self.runner.init = raced_init
        with self.assertRaises(ds.DeploymentStateError):
            service.apply(acknowledge_mutation=True, reservation=reservation, manifest_factory=Mock())
        self.assertNotIn("plan:apply", self.events)
        self.assertEqual(self.objects.writes, ["claim"])


    def test_metadata_or_context_cleanup_failure_never_relabels_successful_apply_as_refused(self):
        for failure in ("publication", "local-save", "context-exit"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                self.local = LocalManifestStore(Path(temporary) / "state")
                def adapter(runner, plan, *, guard, operation):
                    guard.authorize(runner, plan, operation)
                    runner.apply(plan, acknowledge_mutation=True)
                    self.objects.objects["state"] = StoredObject(canonical(runner.current).encode(), "state-4")
                    if failure == "context-exit":
                        runner.exit_error = OSError(SECRET)
                    elif failure == "local-save":
                        self.local.save = Mock(side_effect=OSError(SECRET))
                    else:
                        self.objects.write = Mock(side_effect=OSError(SECRET))
                service = self.remote(mutation_adapter=adapter, verify_materials=lambda d, op: None)
                service.attach(manifest(True))
                result = service.apply(acknowledge_mutation=True)
                self.assertEqual(result.infrastructure_status, "succeeded")
                self.assertTrue(result.recovery_needed)
                self.assertNotIn(SECRET, repr(result))
                expected_serial = 3 if failure == "local-save" else 4
                self.assertEqual(self.local.load("demo").to_dict()["state"]["serial"], expected_serial)


    def test_mutation_requires_material_verification_and_matching_descriptor_before_init(self):
        for defect in ("materials", "descriptor", "adapter", "acknowledgement"):
            with self.subTest(defect=defect):
                self.events.clear()
                runner = FakeRunner(spec(), self.events)
                service = ds.DeploymentState(backend_spec=spec(), target_scope=SCOPE, deployment_name="demo",
                    local_store=self.local, runner_factory=lambda **kw: runner,
                    descriptor=manifest(True) if defect == "descriptor" else manifest(),
                    verify_materials=(lambda d, op: False) if defect == "materials" else (lambda d, op: None))
                if defect == "adapter":
                    service = self.remote(descriptor=manifest(True), verify_materials=lambda d, op: None)
                with self.assertRaises(ds.DeploymentStateError):
                    service.apply(acknowledge_mutation=defect != "acknowledgement")
                self.assertNotIn("init", self.events)
        service = self.remote(verify_materials=lambda d, op: (_ for _ in ()).throw(RuntimeError(SECRET)))
        with self.assertRaises(ds.CapabilityError) as caught:
            service.require_capability("connect")
        self.assertNotIn(SECRET, str(caught.exception))


    @unittest.skipUnless(shutil.which("terraform"), "provider-free integration requires Terraform")
    def test_real_provider_free_local_runner_read_apply_and_destroy(self):
        from src.python.terraform_runner import TerraformRunner
        from src.python.deployment_manifest import StateSummary
        root = Path(self.temporary.name)
        source = root / "source"
        source.mkdir()
        (source / "main.tf").write_text('resource "terraform_data" "sample" { input = { enabled = true, count = 2 } }\n'
            'output "settings" { value = terraform_data.sample.output }\n')
        def factory(**kwargs):
            return TerraformRunner(source_root=source, source_files=["main.tf"], state_root=root / "state",
                lock_root=root / "locks", environment={}, terraform_binary=shutil.which("terraform"), **kwargs)
        # Seed only the built-in terraform_data resource in an isolated /tmp root.
        with factory(backend_spec=spec(), target_scope=SCOPE, deployment_name="demo") as runner:
            runner.init()
            runner.apply(runner.plan(), acknowledge_mutation=True)
            summary = StateSummary.from_state(runner.pull_state())
        self.local.save(DeploymentManifest.create(backend_spec=spec(), target_scope=SCOPE,
            deployment_name="demo", **summary.to_dict()))
        service = ds.DeploymentState.from_saved("demo", local_store=self.local,
            runner_factory=factory, verify_materials=lambda descriptor, operation: None)
        observed = service.read()
        self.assertEqual(observed.status.value, "populated")
        self.assertEqual(observed.outputs.values["settings"], {"enabled": True, "count": 2})
        applied = service.apply(acknowledge_mutation=True)
        self.assertEqual(applied.infrastructure_status, "succeeded")
        self.assertFalse(applied.recovery_needed)
        destroyed = service.destroy(acknowledge_mutation=True)
        self.assertEqual(destroyed.observation.status.value, "destroyed")
        self.assertFalse(destroyed.recovery_needed)
        self.assertEqual(destroyed.tombstone.lineage, observed.lineage)
        self.assertEqual(self.local.load("demo").to_dict()["state"]["addresses"], [])


    def test_saved_gcs_and_azure_descriptors_dispatch_exact_backend_without_cloud_transport(self):
        destinations = [
            ("gcp", "gcs", "example-project", {"bucket": "example-state", "project": "example-project", "prefix": "state/v2"}),
            ("azure", "azurerm", LINEAGE, {"tenant_id": OWNER, "subscription_id": LINEAGE,
                "resource_group_name": "example-rg", "storage_account_name": "examplestate",
                "container_name": "tfstate", "key_prefix": "state/v2"})]
        for cloud, backend, target, destination in destinations:
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as temporary:
                local = LocalManifestStore(Path(temporary) / "state")
                selected = BackendSpec.from_dict({"backend": backend, "namespace": "example",
                    "destination": destination}, cloud=cloud)
                value = DeploymentManifest.create(backend_spec=selected, target_scope=target,
                    deployment_name="demo", lineage=LINEAGE, serial=3, addresses=["aws_instance.workstation"])
                local.save(value)
                objects = MemoryObjects(self.events)
                objects.identity = value.identity
                objects.objects["manifest"] = StoredObject(value.canonical_json().encode(), "manifest-1")
                claim = json.loads(objects.objects["claim"].data)
                claim["identity"] = value.identity
                objects.objects["claim"] = StoredObject(canonical(claim).encode(), "claim-1")
                runner = FakeRunner(spec(), self.events)
                runner.backend_identity = canonical(value.identity)
                factory = Mock(return_value=runner)
                service = ds.DeploymentState.from_saved("demo", local_store=local, runner_factory=factory,
                    coordinator=ProtectedObjectCoordinator(objects, authorize=lambda identity, op: None),
                    verify_scope=lambda identity: ds.VerifiedScope(canonical(identity), "test-principal"))
                result = service.read()
                self.assertEqual(result.status.value, "populated")
                self.assertEqual(factory.call_args.kwargs["backend_spec"], selected)
                self.assertEqual(factory.call_args.kwargs["target_scope"], target)
                self.assertEqual(json.loads(result.source), value.identity)
                self.assertEqual(objects.writes, [])


if __name__ == "__main__":
    unittest.main()
