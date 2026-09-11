"""Detector tests never contact clouds or existing state."""
import json
import unittest
from types import SimpleNamespace

from src.python.drift_config import DriftConfig
from src.python.drift_report import Baseline, digest

BASELINE = Baseline.from_dict(dict(schema_version=1, source_revision="a" * 40,
    input_digest="b" * 64, lock_digest="c" * 64, source_digest="d" * 64,
    source_ref="fixture", inputs_ref="fixture", applied_at=1))


class FixtureRunner:
    backend_identity = '{"fixture":"synthetic"}'
    local_state_path = None

    def __init__(self, plan, changes=False):
        self.document = plan
        self.changes = changes
        self.calls = []

    def __enter__(self):
        self.calls.append("enter")
        return self

    def __exit__(self, *args):
        self.calls.append("exit")

    def init(self):
        self.calls.append("init")

    def pull_state(self):
        self.calls.append("pull_state")
        return {"lineage": "fixture", "serial": 2}

    def plan(self):
        self.calls.append("plan")
        return SimpleNamespace(has_changes=self.changes)

    def plan_json(self, plan):
        self.calls.append("plan_json")
        return self.document

    def apply(self, *args, **kwargs):
        raise AssertionError("Detection must not mutate")


class DetectorTests(unittest.TestCase):
    def test_opted_out_check_never_constructs_runner(self):
        from src.python.drift_detector import DriftDetector
        def forbidden(*args, **kwargs):
            self.fail("Opted-out detection touched execution adapters")
        detector = DriftDetector(config=DriftConfig.from_dict(None), runner_factory=forbidden,
                                 preflight=forbidden, clock=lambda: 100)
        report = detector.check(deployment="fixture", scope="workstation_infrastructure",
                                baseline=BASELINE, backend_digest="e" * 64, expected_lineage="fixture")
        self.assertEqual(report["classes"], ["not_run"])

    def test_refresh_plan_uses_runner_and_current_authorized_serial(self):
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        resource = {"address": "terraform_data.vm", "change": {"actions": ["update"]}}
        runner = FixtureRunner({"format_version": "1.2", "resource_drift": [resource],
                                "resource_changes": [resource]}, changes=True)
        options = []
        def factory(**kwargs):
            options.append(kwargs)
            return runner
        backend = runner_identity_digest(runner)
        preflight = lambda **kwargs: Preflight(status="ready", backend_digest=backend,
            baseline_digest=digest(BASELINE.to_dict()), lineage="fixture", serial=1,
            lifecycle_intent="stopped")
        detector = DriftDetector(config=DriftConfig.from_dict({"enabled": True,
            "scopes": ["workstation_infrastructure"]}), runner_factory=factory,
            preflight=preflight, clock=lambda: 100)
        report = detector.check(deployment="fixture", scope="workstation_infrastructure",
            baseline=BASELINE, backend_digest=backend, expected_lineage="fixture")
        self.assertEqual(set(report["classes"]), {"external_drift", "desired_change"})
        self.assertEqual(report["serial"], 2)
        self.assertEqual(report["lifecycle_intent"], "stopped")
        self.assertEqual(runner.calls, ["enter", "init", "pull_state", "plan", "plan_json", "exit"])
        self.assertEqual(options[0]["controller_lock_timeout"], 30)
        self.assertEqual(options[0]["command_timeout"], 300)
        self.assertEqual(report["findings"][0]["next_action"], "review_lifecycle_intent")

    def test_blocked_identity_missing_baseline_failures_and_cancellation(self):
        from dataclasses import replace
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        from src.python.terraform_runner import TerraformRunnerError, TerraformLockError, TerraformCancelled
        runner = FixtureRunner({"format_version": "1.2"})
        backend = runner_identity_digest(runner)
        healthy = Preflight("ready", backend, digest(BASELINE.to_dict()), "fixture", 1)
        args = dict(deployment="fixture", scope="workstation_infrastructure", baseline=BASELINE,
                    backend_digest=backend, expected_lineage="fixture")
        config = DriftConfig.from_dict({"enabled": True, "scopes": ["workstation_infrastructure"]})
        for health, expected in ((replace(healthy, status="locked"), "locked"),
             (replace(healthy, status="retired"), "identity_mismatch"),
             (replace(healthy, backend_digest="f" * 64), "identity_mismatch"),
             (replace(healthy, baseline_digest="f" * 64), "partial"),
             (replace(healthy, lineage="other"), "identity_mismatch")):
            with self.subTest(health=health):
                detector = DriftDetector(config=config, runner_factory=lambda **kw: self.fail("blocked runner"),
                    preflight=lambda **kw: health, clock=lambda: 100)
                self.assertIn(expected, detector.check(**args)["classes"])
        detector = DriftDetector(config=config, runner_factory=lambda **kw: self.fail("missing baseline runner"),
            preflight=lambda **kw: self.fail("missing baseline preflight"), clock=lambda: 100)
        self.assertIn("partial", detector.check(**{**args, "baseline": None})["classes"])
        for error, expected in ((TerraformRunnerError("SECRET"), "error"),
             (TerraformLockError("SECRET"), "locked"), (TerraformCancelled("SECRET"), "not_run")):
            def broken(**kwargs):
                raise error
            detector = DriftDetector(config=config, runner_factory=broken,
                                     preflight=lambda **kw: healthy, clock=lambda: 100)
            report = detector.check(**args)
            self.assertIn(expected, report["classes"])
            self.assertNotIn("SECRET", json.dumps(report))
        import threading
        cancel = threading.Event()
        cancel.set()
        detector = DriftDetector(config=config, runner_factory=lambda **kw: self.fail("cancelled runner"),
            preflight=lambda **kw: self.fail("cancelled health"), clock=lambda: 100)
        self.assertIn("not_run", detector.check(**args, cancel_event=cancel)["classes"])

    def test_unimplemented_scopes_and_external_ownership_are_explicit_partial(self):
        from src.python.drift_detector import DriftDetector, Preflight
        config = DriftConfig.from_dict({"enabled": True, "scopes": ["runtime", "controller_identity", "backend_infrastructure"]})
        for scope in config.scopes:
            detector = DriftDetector(config=config, runner_factory=lambda **kw: self.fail("unsupported scope executed Terraform"),
                preflight=lambda **kw: Preflight("ready", "e" * 64, digest(BASELINE.to_dict()), "fixture", 1), clock=lambda: 100)
            report = detector.check(deployment="fixture", scope=scope, baseline=BASELINE,
                backend_digest="e" * 64, expected_lineage="fixture")
            self.assertIn("partial", report["classes"])
            self.assertIn("scope_adapter_required", report["coverage"]["unsupported"])

    def test_exceptions_are_visible_not_silent_suppression(self):
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        runner = FixtureRunner({"format_version": "1.2"})
        backend = runner_identity_digest(runner)
        config = DriftConfig.from_dict({"enabled": True, "scopes": ["workstation_infrastructure"],
            "baseline_ref": "last-applied", "exceptions": [{"resource_ref": "vm", "rule_ref": "stopped",
            "owner_ref": "team", "justification_ref": "review", "baseline_ref": "last-applied", "expires_at": 120}]}, now=100)
        detector = DriftDetector(config=config, runner_factory=lambda **kw: runner,
            preflight=lambda **kw: Preflight("ready", backend, digest(BASELINE.to_dict()), "fixture", 1,
                ignored=("approved-tag",), unsupported=("unmodeled-property",)), clock=lambda: 130)
        report = detector.check(deployment="fixture", scope="workstation_infrastructure", baseline=BASELINE,
            backend_digest=backend, expected_lineage="fixture")
        self.assertEqual(report["exceptions"][0]["status"], "expired")
        self.assertIn("partial", report["classes"])
        self.assertIn("approved-tag", report["coverage"]["ignored"])
        self.assertIn("unmodeled-property", report["coverage"]["unsupported"])

    def test_expiry_during_plan_json_or_cleanup_never_returns_clean(self):
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        from src.python.drift_report import wrapper_exit_code
        for phase in ("plan_json", "cleanup"):
            for finished_at in (400, 500, 99):
                with self.subTest(phase=phase, finished_at=finished_at):
                    now = [100]
                    class SlowRunner(FixtureRunner):
                        def plan_json(self, plan):
                            if phase == "plan_json":
                                now[0] = finished_at
                            return super().plan_json(plan)
                        def __exit__(self, *args):
                            if phase == "cleanup":
                                now[0] = finished_at
                            return super().__exit__(*args)
                    runner = SlowRunner({"format_version": "1.2"})
                    backend = runner_identity_digest(runner)
                    detector = DriftDetector(config=DriftConfig.from_dict({"enabled": True,
                        "scopes": ["workstation_infrastructure"]}), runner_factory=lambda **kw: runner,
                        preflight=lambda **kw: Preflight("ready", backend,
                            digest(BASELINE.to_dict()), "fixture", 1), clock=lambda: now[0])
                    report = detector.check(deployment="fixture", scope="workstation_infrastructure",
                        baseline=BASELINE, backend_digest=backend, expected_lineage="fixture")
                    self.assertEqual(report["classes"], ["stale"])
                    self.assertEqual(wrapper_exit_code(report), 3)
                    self.assertEqual(report["observed_at"], 100)
                    self.assertEqual(report["expires_at"], 400)

    def test_unsupported_lifecycle_blocks_before_runner_with_explicit_incomplete_evidence(self):
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        from src.python.drift_report import wrapper_exit_code
        for intent in ("synthetic-private-unsupported-intent", None, [], {"intent": "unknown"}, 1):
            with self.subTest(intent=intent):
                runner = FixtureRunner({"format_version": "1.2"})
                backend = runner_identity_digest(runner)
                detector = DriftDetector(config=DriftConfig.from_dict({"enabled": True,
                    "scopes": ["workstation_infrastructure"]}), runner_factory=lambda **kw: runner,
                    preflight=lambda **kw: Preflight("ready", backend,
                        digest(BASELINE.to_dict()), "fixture", 1, lifecycle_intent=intent), clock=lambda: 100)
                report = detector.check(deployment="fixture", scope="workstation_infrastructure",
                    baseline=BASELINE, backend_digest=backend, expected_lineage="fixture")
                self.assertEqual(report["classes"], ["partial"])
                self.assertIn("unsupported_lifecycle_intent", report["coverage"]["unsupported"])
                self.assertEqual(wrapper_exit_code(report), 3)
                self.assertNotIn("synthetic-private", json.dumps(report))
                self.assertEqual(runner.calls, [])

    def test_malformed_preflight_coverage_is_sanitized_error_before_runner(self):
        from dataclasses import replace
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        from src.python.drift_report import wrapper_exit_code
        for field in ("ignored", "unsupported"):
            for value in (None, [], "private-detail", {"private-detail": True}, 1,
                          (None,), ([],), ("private detail with spaces",)):
                with self.subTest(field=field, value=value):
                    runner = FixtureRunner({"format_version": "1.2"})
                    backend = runner_identity_digest(runner)
                    health = replace(Preflight("ready", backend,
                        digest(BASELINE.to_dict()), "fixture", 1), **{field: value})
                    detector = DriftDetector(config=DriftConfig.from_dict({"enabled": True,
                        "scopes": ["workstation_infrastructure"]}), runner_factory=lambda **kw: runner,
                        preflight=lambda **kw: health, clock=lambda: 100)
                    report = detector.check(deployment="fixture", scope="workstation_infrastructure",
                        baseline=BASELINE, backend_digest=backend, expected_lineage="fixture")
                    self.assertEqual(report["classes"], ["error"])
                    self.assertEqual(wrapper_exit_code(report), 1)
                    self.assertNotIn("private", json.dumps(report))
                    self.assertEqual(runner.calls, [])

    def test_real_provider_free_plan_and_check_do_not_modify_state(self):
        import hashlib
        import os
        import shutil
        import tempfile
        from pathlib import Path
        from src.python.terraform_backend import BackendSpec
        from src.python.terraform_runner import TerraformRunner
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        from src.python.drift_report import classify_plan
        if not shutil.which("terraform"):
            self.skipTest("Terraform binary unavailable; no installation attempted")
        with tempfile.TemporaryDirectory(prefix="drift-real-", dir="/tmp") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "main.tf").write_text('variable "message" { type = string }\nresource "terraform_data" "example" { input = var.message }\n')
            options = dict(source_root=source, source_files=["main.tf"],
                backend_spec=BackendSpec.from_dict({}, cloud="aws"), target_scope="123456789012",
                deployment_name="fixture", state_root=root / "durable", lock_root=root / "locks",
                variables={"message": "original"}, environment={"PATH": os.environ["PATH"], "CHECKPOINT_DISABLE": "1"})
            # Explicit setup mutation is limited to this disposable built-in resource.
            with TerraformRunner(**options) as runner:
                runner.init()
                runner.apply(runner.plan(), acknowledge_mutation=True)
                state = runner.pull_state()
                backend = runner_identity_digest(runner)
            path = root / "durable/fixture/.tfstate"
            before = path.read_bytes()
            baseline = Baseline.from_dict({**BASELINE.to_dict(),
                "source_digest": hashlib.sha256((source / "main.tf").read_bytes()).hexdigest(),
                "input_digest": digest(options["variables"])})
            detector = DriftDetector(config=DriftConfig.from_dict({"enabled": True,
                "scopes": ["workstation_infrastructure"]}),
                runner_factory=lambda **bounds: TerraformRunner(**options, **bounds),
                preflight=lambda **kw: Preflight("ready", backend, digest(baseline.to_dict()), state["lineage"], state["serial"]),
                clock=lambda: 100)
            report = detector.check(deployment="fixture", scope="workstation_infrastructure", baseline=baseline,
                backend_digest=backend, expected_lineage=state["lineage"])
            self.assertEqual(report["classes"], ["clean_within_coverage"])
            self.assertIn("terraform_data.example", report["coverage"]["checked"])
            self.assertEqual(path.read_bytes(), before)
            # Separate intentional desired-input comparison, NOT a last-applied drift baseline.
            with TerraformRunner(**{**options, "variables": {"message": "intentionally-new"}}) as runner:
                runner.init()
                plan = runner.plan()
                classified = classify_plan(runner.plan_json(plan), exit_code=2 if plan.has_changes else 0)
                self.assertIn("desired_change", classified["classes"])
                self.assertNotIn("external_drift", classified["classes"])
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
