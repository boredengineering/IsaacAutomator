"""Bounded nonmutating drift service; no CLI, cloud health or lifecycle bypass."""
import time
import json
import threading
from dataclasses import dataclass, asdict
from src.python.drift_config import opaque_ref
from src.python.drift_report import make_report, digest


@dataclass(frozen=True)
class Preflight:
    """Trusted health/attachment/baseline adapter result, NOT request JSON.

    ready attests applicable lifecycle gates, nonretired state location, health,
    and that runner_factory reconstructs exactly the pinned source/inputs/lock.
    The integrating health service owns these checks; this module cannot infer
    them from a backend descriptor or repository HEAD.
    """
    status: str
    backend_digest: str
    baseline_digest: str
    lineage: str
    serial: int
    lifecycle_intent: str = "unspecified"
    owner: str = "unspecified"
    ignored: tuple = ()
    unsupported: tuple = ()


def runner_identity_digest(runner):
    """Include actual durable local path; a logical local name is insufficient."""
    identity = json.loads(runner.backend_identity)
    if runner.local_state_path is not None:
        identity["local_state_path"] = str(runner.local_state_path)
    return digest(identity)


class DriftDetector:
    def __init__(self, *, config, runner_factory, preflight, clock=time.time):
        self.config = config
        self.runner_factory = runner_factory
        self.preflight = preflight
        self.clock = clock

    def check(self, *, deployment, scope, baseline, backend_digest, expected_lineage, cancel_event=None):
        """runner_factory is a trusted pinned-source resolver, not user-supplied code.

        Shared preflight must enforce provider release gates before any backend
        read. No Terraform apply, refresh-only apply, SSH or policy mutation.
        """
        from src.python.terraform_runner import TerraformRunnerError, TerraformLockError, TerraformCancelled
        now = int(self.clock())
        args = dict(deployment=deployment, scope=scope, baseline=baseline,
                    backend_digest=backend_digest, lineage=expected_lineage, serial=None,
                    observed_at=now, expires_at=now + 300, now=now)
        cancel = cancel_event if cancel_event is not None else threading.Event()
        if not self.config.enabled or scope not in self.config.scopes or cancel.is_set():
            return make_report(**args, status="not_run")
        if baseline is None or baseline.applied_at > now:
            return make_report(**args, status="partial")
        try:
            health = self.preflight(deployment=deployment, scope=scope, baseline=baseline)
            if not isinstance(health, Preflight):
                return make_report(**args, status="partial")
            coverage = {}
            for field in ("ignored", "unsupported"):
                items = getattr(health, field)
                if type(items) is not tuple:
                    raise ValueError("Malformed preflight coverage")
                # Validate and snapshot adapter evidence inside the sanitized
                # boundary, before any runner/backend access.
                coverage[field] = [opaque_ref(item) for item in items]
            if (not isinstance(health.lifecycle_intent, str) or health.lifecycle_intent not in
                    ("unspecified", "stopped", "scheduled_scaling")):
                report = make_report(**args, status="partial")
                report["coverage"]["unsupported"].append("unsupported_lifecycle_intent")
                return report
            if scope in ("runtime", "controller_identity") or (scope == "backend_infrastructure" and health.owner != "bootstrap_terraform"):
                report = make_report(**args, status="partial")
                report["coverage"]["unsupported"].append("scope_adapter_required")
                return report
            if health.status != "ready":
                status = {"locked": "locked", "retired": "identity_mismatch", "identity_mismatch": "identity_mismatch",
                          "error": "error", "policy_noncompliance": "policy_noncompliance"}.get(health.status, "partial")
                return make_report(**args, status=status)
            if health.backend_digest != backend_digest or health.lineage != expected_lineage:
                return make_report(**args, status="identity_mismatch")
            if health.baseline_digest != digest(baseline.to_dict()):
                return make_report(**args, status="partial")
            with self.runner_factory(command_timeout=self.config.command_timeout,
                                     controller_lock_timeout=self.config.lock_timeout,
                                     cancel_event=cancel) as runner:
                if runner_identity_digest(runner) != backend_digest:
                    return make_report(**args, status="identity_mismatch")
                runner.init()
                state = runner.pull_state()
                if state["lineage"] != expected_lineage:
                    return make_report(**args, status="identity_mismatch")
                args.update(lineage=state["lineage"], serial=state["serial"])
                saved = runner.plan()
                document = runner.plan_json(saved)
                args["now"] = int(self.clock())
                report = make_report(**args, plan=document, exit_code=2 if saved.has_changes else 0)
        except TerraformLockError:
            return make_report(**args, status="locked")
        except TerraformCancelled:
            return make_report(**args, status="not_run")
        except (TerraformRunnerError, ValueError, OSError, KeyError, TypeError):
            return make_report(**args, status="error")
        report["lifecycle_intent"] = health.lifecycle_intent
        if report["lifecycle_intent"] != "unspecified":
            for finding in report["findings"]:
                finding["next_action"] = "review_lifecycle_intent"
        for field in ("ignored", "unsupported"):
            report["coverage"][field].extend(coverage[field])
        report["exceptions"] = []
        for rule in self.config.exceptions:
            status = ("expired" if int(self.clock()) >= rule.expires_at else
                      "baseline_changed" if rule.baseline_ref != self.config.baseline_ref else "requires_owner_review")
            report["exceptions"].append({**asdict(rule), "status": status})
        if coverage["ignored"] or coverage["unsupported"] or report["exceptions"]:
            report["classes"] = sorted(set(report["classes"]) - {"clean_within_coverage"} | {"partial"})
        # Parsing, context cleanup and report assembly must not extend evidence's
        # validity window. Recheck immediately before handing it to the caller.
        if not report["observed_at"] <= int(self.clock()) < report["expires_at"]:
            report["classes"] = sorted(set(report["classes"]) - {"clean_within_coverage"} | {"stale"})
        return report
