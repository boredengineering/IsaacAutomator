"""Trusted-adapter remediation tests; no cloud or deployment state."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.python.drift_config import DriftConfig
from src.python.drift_report import Baseline, digest

BASELINE = Baseline.from_dict(dict(schema_version=1, source_revision="a" * 40,
    input_digest="b" * 64, lock_digest="c" * 64, source_digest="d" * 64,
    source_ref="fixture", inputs_ref="fixture", applied_at=1))


class RemediationTests(unittest.TestCase):
    def test_report_only_prohibits_proposals_and_mutations(self):
        from src.python.drift_remediation import RemediationEngine, RemediationError
        def forbidden(*args, **kwargs):
            self.fail("report_only called an execution adapter")
        engine = RemediationEngine(config=DriftConfig.from_dict(None), issuer=None,
            actor="detector", executor="workload-executor", observe=forbidden,
            assess_risk=forbidden, postcheck=forbidden, clock=lambda: 100)
        with self.assertRaises(RemediationError):
            engine.propose(deployment="fixture", scope="workstation_infrastructure",
                           baseline=BASELINE, runner=None, saved_plan=None)
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id="proposal", approval_ref="approval")
        with self.assertRaises(TypeError):
            engine.remediate(proposal_id="proposal", approval_ref="approval", approved=True)

    def fixture(self):
        from src.python.drift_remediation import RemediationEngine, Observation, Postcheck
        from src.python.drift_detector import runner_identity_digest
        root = tempfile.TemporaryDirectory(prefix="drift-remediation-", dir="/tmp")
        self.addCleanup(root.cleanup)
        path = Path(root.name) / "reviewed.tfplan"
        path.write_bytes(b"private synthetic plan")
        path.chmod(0o600)
        saved = SimpleNamespace(path=path, digest=hashlib.sha256(path.read_bytes()).hexdigest(), has_changes=True)
        resource = {"address": "terraform_data.vm", "change": {"actions": ["update"],
                    "before": {"private": "old"}, "after": {"private": "new"}}}
        class Runner:
            backend_identity = '{"fixture":"synthetic"}'
            local_state_path = None
            state = {"lineage": "fixture", "serial": 1}
            calls = []
            document = {"format_version": "1.2", "resource_changes": [resource]}
            post_document = {"format_version": "1.2", "resource_changes": [
                {"address": "terraform_data.vm", "change": {"actions": ["no-op"]}}]}
            def plan_json(self, plan):
                return self.document
            def pull_state(self):
                return self.state
            def plan(self):
                self.document = self.post_document
                return SimpleNamespace(has_changes=self.post_document["resource_changes"][0]["change"]["actions"] != ["no-op"])
            def apply(self, plan, *, acknowledge_mutation):
                self.calls.append((plan, acknowledge_mutation))
        class Issuer:
            # Test-only authenticated registry. Not a production issuer or signer.
            records = {}
            used = set()
            def verify(self, ref):
                return self.records[ref]
            def consume(self, ref, binding_digest):
                if ref in self.used or self.records[ref].binding_digest != binding_digest:
                    return False
                self.used.add(ref)
                return True
        runner, issuer = Runner(), Issuer()
        observed = [Observation(backend_digest=runner_identity_digest(runner),
            baseline_digest=digest(BASELINE.to_dict()), lineage="fixture", serial=1,
            properties_digest=digest({"private": "old"}), coverage_digest=digest(["terraform_data.vm"]),
            observed_at=100, complete=True)]
        now = [100]
        post = [Postcheck(properties_verified=True, plan_clean=True, complete=True)]
        risk = [()]
        engine = RemediationEngine(config=DriftConfig.from_dict({"enabled": True,
            "scopes": ["workstation_infrastructure"], "correction": "approval_required"}),
            issuer=issuer, actor="detector", executor="workload-executor",
            observe=lambda **kwargs: observed[0], assess_risk=lambda **kwargs: risk[0],
            postcheck=lambda **kwargs: post[0], clock=lambda: now[0])
        return engine, runner, saved, issuer, observed, now, post, risk

    def proposal(self, engine, runner, saved):
        return engine.propose(deployment="fixture", scope="workstation_infrastructure",
                              baseline=BASELINE, runner=runner, saved_plan=saved)

    def authorize(self, issuer, proposal, **changes):
        from src.python.drift_remediation import VerifiedApproval
        fields = dict(binding_digest=proposal["binding_digest"], reviewer="independent-reviewer",
                      executor="workload-executor", issued_at=100, expires_at=200, role="reviewer")
        issuer.records["approved-review"] = VerifiedApproval(**{**fields, **changes})
        return "approved-review"

    def test_exact_reviewed_plan_applies_only_with_trusted_issuer_and_postchecks(self):
        engine, runner, saved, issuer, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        receipt = engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(runner.calls, [(saved, True)])
        self.assertEqual(proposal["plan_digest"], saved.digest)
        self.assertNotIn("private", str(proposal))
        self.assertEqual(receipt["attempts"], 1)

    def test_consistently_failed_policy_assertions_reject_proposal_without_apply(self):
        from src.python.drift_remediation import RemediationError
        from src.python.drift_report import classify_plan
        engine, runner, saved, issuer, *_ = self.fixture()
        runner.document["checks"] = [{
            "address": {"kind": "check", "name": "private_access",
                        "to_display": "check.private_access"},
            "status": "fail",
            "instances": [{"address": {"to_display": "check.private_access"},
                           "status": "fail",
                           "failure_messages": ["synthetic-private-policy-detail"]}],
        }]
        # Consistent real Terraform aggregate/instance shape: rejection must be
        # for failed policy, not an accidentally partial or malformed fixture.
        summary = classify_plan(runner.document, exit_code=2)
        self.assertEqual(set(summary["classes"]), {"desired_change", "policy_noncompliance"})
        with self.assertRaises(RemediationError):
            proposal = self.proposal(engine, runner, saved)
            # If proposal rejection regresses, ordinary independent approval
            # would otherwise take this exact saved plan through apply.
            ref = self.authorize(issuer, proposal)
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(runner.calls, [])
        self.assertEqual(engine._proposals, {})
        self.assertEqual(issuer.records, {})

    def test_proposal_adapter_failures_are_sanitized_and_release_operation_lock(self):
        import traceback
        from src.python.drift_remediation import RemediationError
        secret = "synthetic-private-attester-detail"
        for phase in ("plan_json", "assess_risk", "observe", "pull_state"):
            for error_type in (OSError, RemediationError):
                with self.subTest(phase=phase, error_type=error_type):
                    engine, runner, saved, issuer, *_ = self.fixture()
                    target = engine if phase in ("assess_risk", "observe") else runner
                    original = getattr(target, phase)
                    def failure(*args, **kwargs):
                        raise error_type(secret)
                    setattr(target, phase, failure)
                    try:
                        self.proposal(engine, runner, saved)
                    except Exception as exc:
                        self.assertIsInstance(exc, RemediationError)
                        self.assertNotIn(secret, str(exc))
                        self.assertNotIn(secret, "".join(traceback.format_exception(exc)))
                        self.assertIsNone(exc.__cause__)
                        self.assertTrue(exc.__suppress_context__)
                    else:
                        self.fail("proposal accepted unavailable adapter evidence")
                    self.assertEqual(engine._proposals, {})
                    self.assertEqual(runner.calls, [])
                    setattr(target, phase, original)
                    self.assertIn("proposal_id", self.proposal(engine, runner, saved))

    def test_rejects_forged_self_wrong_actor_expired_and_replayed_approvals(self):
        from src.python.drift_remediation import RemediationError
        for change in ({"reviewer": "detector"}, {"reviewer": "workload-executor"},
                       {"executor": "other"}, {"binding_digest": "f" * 64},
                       {"issued_at": 101}, {"expires_at": 100}, {"expires_at": 9999},
                       {"role": "repository-writer"}):
            with self.subTest(change=change):
                engine, runner, saved, issuer, *_ = self.fixture()
                proposal = self.proposal(engine, runner, saved)
                ref = self.authorize(issuer, proposal, **change)
                with self.assertRaises(RemediationError):
                    engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
                self.assertEqual(runner.calls, [])
        engine, runner, saved, issuer, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        for ref in ("forged", "https://evil/approval", {"approved": True}):
            with self.assertRaises(RemediationError):
                engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        issuer.records["forged"] = {"approved": True, "binding_digest": proposal["binding_digest"]}
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref="forged")
        ref = self.authorize(issuer, proposal)
        engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(len(runner.calls), 1)

    def test_stale_live_values_even_unchanged_serial_or_changed_plan_reject(self):
        from dataclasses import replace
        from src.python.drift_remediation import RemediationError
        for change in ({"properties_digest": "f" * 64}, {"lineage": "other"},
                       {"serial": 2}, {"baseline_digest": "f" * 64},
                       {"backend_digest": "f" * 64}, {"coverage_digest": "f" * 64},
                       {"complete": False}, {"observed_at": 1}, {"observed_at": 101}):
            with self.subTest(change=change):
                engine, runner, saved, issuer, observed, *_ = self.fixture()
                proposal = self.proposal(engine, runner, saved)
                ref = self.authorize(issuer, proposal)
                observed[0] = replace(observed[0], **change)
                with self.assertRaises(RemediationError):
                    engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
                self.assertEqual(runner.calls, [])
        for change in ("binary", "actions", "same-actions-new-values", "public-proposal", "old-proposal"):
            with self.subTest(change=change):
                engine, runner, saved, issuer, observed, now, *_ = self.fixture()
                proposal = self.proposal(engine, runner, saved)
                ref = self.authorize(issuer, proposal)
                if change == "binary":
                    saved.path.write_bytes(b"different plan with same actions")
                elif change == "actions":
                    runner.document["resource_changes"][0]["change"]["actions"] = ["delete"]
                elif change == "same-actions-new-values":
                    runner.document["resource_changes"][0]["change"]["after"] = {"private": "evil"}
                elif change == "public-proposal":
                    proposal["actions"][0]["actions"] = ["delete"]
                    # Detached public summaries cannot edit the protected operation.
                    receipt = engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
                    self.assertEqual(receipt["status"], "verified")
                    continue
                else:
                    now[0] = 401
                    observed[0] = replace(observed[0], observed_at=401)
                    self.authorize(issuer, proposal, issued_at=401, expires_at=450)
                with self.assertRaises(RemediationError):
                    engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
                self.assertEqual(runner.calls, [])

    def test_consumption_precedes_final_validation_and_burns_stale_grant(self):
        from dataclasses import replace
        from src.python.drift_remediation import RemediationError
        for mutation in ("properties", "state", "plan_json", "binary"):
            with self.subTest(mutation=mutation):
                engine, runner, saved, issuer, observed, now, *_ = self.fixture()
                proposal = self.proposal(engine, runner, saved)
                ref = self.authorize(issuer, proposal)
                consume = issuer.consume
                def slow_consume(ref, binding_digest):
                    consumed = consume(ref, binding_digest)
                    now[0] = 159
                    if mutation == "properties":
                        observed[0] = replace(observed[0], properties_digest="f" * 64,
                                              observed_at=159)
                    elif mutation == "state":
                        runner.state = {"lineage": "fixture", "serial": 2}
                    elif mutation == "plan_json":
                        runner.document["resource_changes"][0]["change"]["after"] = {"private": "changed"}
                    else:
                        saved.path.write_bytes(b"changed during consumption")
                    return consumed
                issuer.consume = slow_consume
                with self.assertRaises(RemediationError):
                    engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
                self.assertEqual(runner.calls, [])
                self.assertIn(ref, issuer.used)
                with self.assertRaises(RemediationError):
                    engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
                with self.assertRaises(RemediationError):
                    self.proposal(engine, runner, saved)

    def test_risk_review_scope_ownership_and_unsupported_rules(self):
        from src.python.drift_remediation import RemediationError
        for action in (["delete"], ["delete", "create"], ["create", "delete"]):
            engine, runner, saved, issuer, *_ = self.fixture()
            runner.document["resource_changes"][0]["change"]["actions"] = action
            proposal = self.proposal(engine, runner, saved)
            ref = self.authorize(issuer, proposal)
            with self.assertRaises(RemediationError):
                engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
            self.assertEqual(runner.calls, [])
            self.authorize(issuer, proposal, role="elevated_reviewer")
            self.assertEqual(engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)["status"], "verified")
        engine, runner, saved, issuer, observed, now, post, risk = self.fixture()
        risk[0] = ("iam_broadening",)
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        for scope in ("cloud_native", "runtime", "backend_infrastructure"):
            with self.assertRaises(RemediationError):
                engine.propose(deployment="fixture", scope=scope, baseline=BASELINE,
                               runner=runner, saved_plan=saved)
        engine.assess_risk = None
        with self.assertRaises(RemediationError):
            self.proposal(engine, runner, saved)
        engine, runner, saved, issuer, *_ = self.fixture()
        runner.document["resource_changes"] *= 21
        with self.assertRaises(RemediationError):
            self.proposal(engine, runner, saved)

    def test_partial_postchecks_failure_pause_and_oscillation_are_unresolved(self):
        from dataclasses import replace
        from src.python.drift_remediation import RemediationError
        for field in ("properties_verified", "plan_clean", "complete"):
            engine, runner, saved, issuer, observed, now, post, *_ = self.fixture()
            post[0] = replace(post[0], **{field: False})
            proposal = self.proposal(engine, runner, saved)
            ref = self.authorize(issuer, proposal)
            self.assertEqual(engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)["status"], "unverified")
            with self.assertRaises(RemediationError):
                self.proposal(engine, runner, saved)
        engine, runner, saved, issuer, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        engine.pause()
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(runner.calls, [])
        for phase in ("apply", "postcheck"):
            engine, runner, saved, issuer, *_ = self.fixture()
            proposal = self.proposal(engine, runner, saved)
            ref = self.authorize(issuer, proposal)
            def failure(*args, **kwargs):
                raise RuntimeError("SECRET")
            if phase == "apply":
                runner.apply = failure
            else:
                engine.postcheck = failure
            receipt = engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
            self.assertEqual(receipt["status"], "error")
            self.assertNotIn("SECRET", str(receipt))
            with self.assertRaises(RemediationError):
                engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)

    def test_rechecks_expiry_after_slow_live_checks_and_prevents_queued_duplicate(self):
        from src.python.drift_remediation import RemediationError
        engine, runner, saved, issuer, observed, now, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        def slow_observe(**kwargs):
            now[0] = 200
            from dataclasses import replace
            return replace(observed[0], observed_at=200)
        engine.observe = slow_observe
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(runner.calls, [])
        engine, runner, saved, issuer, *_ = self.fixture()
        first = self.proposal(engine, runner, saved)
        second = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, first)
        engine.remediate(proposal_id=first["proposal_id"], approval_ref=ref)
        issuer.used.clear()  # Different valid issuer grant, not a token replay.
        self.authorize(issuer, second)
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=second["proposal_id"], approval_ref=ref)
        self.assertEqual(len(runner.calls), 1)

    def test_concurrent_correction_is_bounded_to_one(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from src.python.drift_remediation import RemediationError
        engine, runner, saved, issuer, observed, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        entered, release = threading.Event(), threading.Event()
        def wait_observe(**kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return observed[0]
        engine.observe = wait_observe
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(engine.remediate, proposal_id=proposal["proposal_id"], approval_ref=ref)
            self.assertTrue(entered.wait(2))
            try:
                with self.assertRaises(RemediationError):
                    engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
            finally:
                release.set()
            self.assertEqual(future.result()["status"], "verified")
        self.assertEqual(len(runner.calls), 1)


    def test_real_runner_postplan_is_required_despite_positive_adapter_flags(self):
        engine, runner, saved, issuer, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        runner.post_document["resource_changes"][0]["change"]["actions"] = ["update"]
        result = engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(result["status"], "unverified")


    def test_authoritative_runner_state_is_rechecked_not_only_observer_claim(self):
        from src.python.drift_remediation import RemediationError
        engine, runner, saved, issuer, *_ = self.fixture()
        proposal = self.proposal(engine, runner, saved)
        ref = self.authorize(issuer, proposal)
        runner.state["serial"] = 2
        with self.assertRaises(RemediationError):
            engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=ref)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
