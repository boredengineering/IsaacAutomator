"""Exact saved-plan correction contract; no CLI, native rules or approval issuer."""
import time
import uuid
import copy
import hashlib
import os
import stat
import threading
from dataclasses import dataclass, asdict
from typing import Protocol
from functools import wraps
from src.python.drift_report import digest, classify_plan, require_digest
from src.python.drift_config import opaque_ref
from src.python.drift_detector import runner_identity_digest


@dataclass(frozen=True)
class Observation:
    backend_digest: str
    baseline_digest: str
    lineage: str
    serial: int
    properties_digest: str
    coverage_digest: str
    observed_at: int
    complete: bool


@dataclass(frozen=True)
class Postcheck:
    properties_verified: bool
    plan_clean: bool
    complete: bool


@dataclass(frozen=True)
class VerifiedApproval:
    binding_digest: str
    reviewer: str
    executor: str
    issued_at: int
    expires_at: int
    role: str


class TrustedApprovalIssuer(Protocol):
    """Explicit trust anchor, injected by authenticated application composition.

    verify resolves an opaque reference via an authenticated protected review
    service or separately managed asymmetric signature verifier. It MUST verify
    reviewer authorization for the exact binding/scope, audience and revocation.
    Never implement by parsing caller JSON or trusting an 'approved' flag.
    consume MUST atomically/durably reject replay across processes/controllers,
    recheck revocation, and bind consumption to the same verified grant. Detector
    and report writers must have NO issuer signing or record-writing authority.
    No insecure default implementation is shipped; stdlib has no signing API.
    """
    def verify(self, approval_ref: str) -> VerifiedApproval: ...
    def consume(self, approval_ref: str, binding_digest: str) -> bool: ...


class RemediationError(ValueError):
    """Sanitized fail-closed policy or execution rejection."""


def _plan_digest(saved):
    # Runner independently verifies ownership and uses an anonymous exact binary
    # snapshot for apply; this check never substitutes for that guarantee.
    try:
        with os.fdopen(os.open(saved.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise ValueError()
            result = hashlib.sha256(stream.read()).hexdigest()
        if result != saved.digest:
            raise ValueError()
        return result
    except (OSError, ValueError):
        raise RemediationError("Saved plan is changed, missing or not private") from None


def _validate_observation(observation, runner, baseline, now):
    if (not isinstance(observation, Observation) or observation.complete is not True
            or type(observation.observed_at) is not int or not 0 <= now - observation.observed_at <= 60
            or type(observation.serial) is not int or observation.serial < 0
            or observation.backend_digest != runner_identity_digest(runner)
            or observation.baseline_digest != digest(baseline.to_dict())):
        raise RemediationError("Incomplete, stale or mismatched live observation")
    for value in (observation.backend_digest, observation.baseline_digest,
                  observation.properties_digest, observation.coverage_digest):
        require_digest(value)
    opaque_ref(observation.lineage)
    state = runner.pull_state()
    if state["lineage"] != observation.lineage or state["serial"] != observation.serial:
        raise RemediationError("Authoritative state changed; discard observation and proposal")


def _serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if not self._operation_lock.acquire(blocking=False):
            raise RemediationError("Another correction operation is active")
        try:
            return method(self, *args, **kwargs)
        finally:
            self._operation_lock.release()
    return guarded


class RemediationEngine:
    """Short-lived, same-active-runner-context proposals only.

    The composition root authenticates actor/executor and supplies trusted
    observe/risk/postcheck adapters. None may be request-selected functions.
    observe must freshly read authoritative identity, baseline and ALL protected
    live target properties (including private values) with complete coverage;
    postcheck must re-plan AND independently check affected properties. Locks do
    not exclude cloud-console edits: a residual observe/apply race remains.
    No cross-context plan import/export or approval persistence is implemented.
    """
    def __init__(self, *, config, issuer, actor, executor, observe, assess_risk, postcheck,
                 clock=time.time, identity_role="workload"):
        self.config = config
        self.issuer = issuer
        self.actor = actor
        self.executor = executor
        self.observe = observe
        self.assess_risk = assess_risk
        self.postcheck = postcheck
        self.clock = clock
        self.identity_role = identity_role
        self._proposals = {}
        self._attempted = set()
        self._paused = threading.Event()
        self._operation_lock = threading.Lock()

    def pause(self):
        """Kill switch: this engine cannot be resumed or retry an attempted plan."""
        self._paused.set()

    def _enabled(self):
        if (not self.config.enabled or self.config.correction != "approval_required" or self._paused.is_set()
                or self.issuer is None or not callable(self.assess_risk) or not callable(self.observe)
                or not callable(self.postcheck)):
            raise RemediationError("Correction is paused or not authorized/configured")

    @_serialized
    def propose(self, *, deployment, scope, baseline, runner, saved_plan):
        try:
            return self._propose(deployment=deployment, scope=scope, baseline=baseline,
                                 runner=runner, saved_plan=saved_plan)
        except Exception:
            # Even an adapter's RemediationError may contain private diagnostics.
            # Keep execution, validation and binding creation inside this boundary.
            raise RemediationError("Correction proposal rejected or evidence unavailable") from None

    def _propose(self, *, deployment, scope, baseline, runner, saved_plan):
        self._enabled()
        if (scope not in self.config.scopes or scope not in ("workstation_infrastructure", "backend_infrastructure")
                or (scope == "backend_infrastructure" and self.identity_role != "backend_owner")
                or (scope == "workstation_infrastructure" and self.identity_role != "workload") or baseline is None):
            raise RemediationError("Unsupported correction scope or wrong resource-owner identity")
        opaque_ref(deployment)
        document = runner.plan_json(saved_plan)
        summary = classify_plan(document, exit_code=2 if saved_plan.has_changes else 0)
        actions = [f for f in summary["findings"] if f["class"] == "desired_change"]
        if "policy_noncompliance" in summary["classes"]:
            raise RemediationError("Failed policy assertions prohibit correction")
        if "partial" in summary["classes"] or "error" in summary["classes"] or not 1 <= len(actions) <= 20:
            raise RemediationError("Incomplete, empty or excessive corrective action set")
        risks = self.assess_risk(plan=document, scope=scope)
        known_risks = {"iam_broadening", "public_exposure", "protection_disabled", "key_change", "cost_increase",
                       "destructive", "import", "ownership_change"}
        if not isinstance(risks, tuple) or any(risk not in known_risks for risk in risks):
            raise RemediationError("Risk assessment incomplete or unsupported")
        elevated = bool(risks) or any(a in ("delete", "forget") for f in actions for a in f["actions"])
        elevated = elevated or any("importing" in r.get("change", {}) for r in document.get("resource_changes", []))
        incident = digest({"deployment": deployment, "scope": scope, "baseline": baseline.to_dict(), "actions": actions})
        if incident in self._attempted:
            raise RemediationError("Repeated correction/oscillation requires independent review and a new session")
        observation = self.observe(runner=runner, baseline=baseline, scope=scope)
        _validate_observation(observation, runner, baseline, int(self.clock()))
        proposal_id = uuid.uuid4().hex
        binding = dict(schema_version=1, proposal_id=proposal_id, deployment=deployment,
                       scope=scope, baseline=baseline.to_dict(), plan_digest=_plan_digest(saved_plan),
                       plan_json_digest=digest(document),
                       observation=asdict(observation), actions=summary["findings"],
                       actor=self.actor, executor=self.executor, identity_role=self.identity_role,
                       elevated=elevated, risks=list(risks), incident=incident, created_at=int(self.clock()))
        fingerprint = digest(binding)
        self._proposals[proposal_id] = (binding, fingerprint, runner, saved_plan, baseline)
        return {"schema_version": 1, "proposal_id": proposal_id, "binding_digest": fingerprint,
                "plan_digest": saved_plan.digest, "actions": copy.deepcopy(summary["findings"])}

    @_serialized
    def remediate(self, *, proposal_id, approval_ref):
        self._enabled()
        try:
            opaque_ref(proposal_id)
            opaque_ref(approval_ref)
            binding, fingerprint, runner, saved, baseline = self._proposals[proposal_id]
            approval = self.issuer.verify(approval_ref)
        except Exception:
            raise RemediationError("Unknown proposal or unverified approval reference") from None
        now = int(self.clock())
        if binding["incident"] in self._attempted:
            raise RemediationError("Duplicate/oscillating correction already attempted")
        if (not isinstance(approval, VerifiedApproval) or approval.binding_digest != fingerprint
                or approval.reviewer in (self.actor, self.executor)
                or approval.executor != self.executor or approval.role not in ("reviewer", "elevated_reviewer")
                or (binding["elevated"] and approval.role != "elevated_reviewer")
                or type(approval.issued_at) is not int or type(approval.expires_at) is not int
                or not binding["created_at"] <= approval.issued_at <= now < approval.expires_at
                or approval.expires_at - approval.issued_at > 300
                or not 0 <= now - binding["created_at"] < 300):
            raise RemediationError("Approval is invalid, expired, self-approved or outside actor scope")
        try:
            consumed = self.issuer.consume(approval_ref, fingerprint)
        except Exception:
            raise RemediationError("Approval consumption unavailable; mutation refused") from None
        if consumed is not True:
            raise RemediationError("Approval already consumed or revoked")
        # Consume before the final potentially expensive checks. A stale proposal
        # burns its grant too; no issuer round trip may follow live validation.
        del self._proposals[proposal_id]
        self._attempted.add(binding["incident"])
        self._enabled()
        try:
            document = runner.plan_json(saved)
            if _plan_digest(saved) != binding["plan_digest"] or digest(document) != binding["plan_json_digest"]:
                raise RemediationError("Exact reviewed plan changed")
            observed = self.observe(runner=runner, baseline=baseline, scope=binding["scope"])
            _validate_observation(observed, runner, baseline, int(self.clock()))
            current = asdict(observed)
            if any(current[key] != value for key, value in binding["observation"].items() if key != "observed_at"):
                raise RemediationError("Live conditions changed; replan and reapprove")
        except Exception:
            raise RemediationError("Plan or live preconditions changed or cannot be verified") from None
        self._enabled()
        if not approval.issued_at <= int(self.clock()) < min(approval.expires_at, binding["created_at"] + 300, observed.observed_at + 60):
            raise RemediationError("Approval or observation expired before execution")
        status = "error"
        try:
            runner.apply(saved, acknowledge_mutation=True)
            recheck = runner.plan()  # New refresh-enabled plan, never an automatic second apply.
            rechecked = classify_plan(runner.plan_json(recheck), exit_code=2 if recheck.has_changes else 0)
            result = self.postcheck(runner=runner, baseline=baseline, scope=binding["scope"])
            status = ("verified" if isinstance(result, Postcheck) and result.properties_verified is True
                      and result.plan_clean is True and result.complete is True
                      and rechecked["classes"] == ["clean_within_coverage"] else "unverified")
        except Exception:
            pass  # Attempt consumed even on partial mutation; diagnostics never leave this boundary.
        return {"schema_version": 1, "proposal_id": proposal_id, "attempts": 1,
                "status": status}
