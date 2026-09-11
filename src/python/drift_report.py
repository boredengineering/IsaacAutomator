"""Versioned drift evidence. Public summaries never serialize Terraform values."""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from src.python.drift_config import opaque_ref, strict_block


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def require_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected SHA-256 digest")
    return value


@dataclass(frozen=True)
class Baseline:
    schema_version: int
    source_revision: str
    input_digest: str
    lock_digest: str
    source_digest: str
    inputs_ref: str
    source_ref: str
    applied_at: int

    @classmethod
    def from_dict(cls, data):
        if data is None:
            return None
        strict_block(data, cls.__dataclass_fields__)
        if set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Missing reconstructible last-applied baseline")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported baseline version")
        if not isinstance(data["source_revision"], str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", data["source_revision"]):
            raise ValueError("Baseline source must be an immutable revision")
        for key in ("input_digest", "lock_digest", "source_digest"):
            require_digest(data[key])
        for key in ("inputs_ref", "source_ref"):
            opaque_ref(data[key])
        if type(data["applied_at"]) is not int or data["applied_at"] < 0:
            raise ValueError("Invalid successful-apply timestamp")
        return cls(**data)

    def to_dict(self):
        return asdict(self)


def public_address(value):
    # for_each keys can contain private values. Retain safe static/numeric addresses only.
    if not isinstance(value, str):
        raise ValueError("Invalid resource address")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*(?:\[[0-9]+\](?:\.[A-Za-z_][A-Za-z0-9_.-]*)?)*", value):
        return value
    return "resource-" + digest(value)


def _unknown(value):
    if isinstance(value, dict):
        return any(_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(_unknown(v) for v in value)
    return value is not False and value is not None


_ACTIONS = {("no-op",), ("read",), ("create",), ("update",), ("delete",),
            ("delete", "create"), ("create", "delete"), ("forget",)}
_PLAN_FIELDS = {"format_version", "terraform_version", "variables", "planned_values", "resource_drift",
                "resource_changes", "output_changes", "prior_state", "configuration", "relevant_attributes",
                "checks", "timestamp", "applyable", "complete", "errored", "deferred_changes"}


def _check_fields(value, allowed, coverage):
    if not isinstance(value, dict):
        raise ValueError()
    if set(value) - allowed:
        coverage["unsupported"].append("unknown_check_fields")


def _check_address(address, *, instance, coverage):
    # Terraform JSON 1.x check addresses differ for aggregates and instances.
    allowed = {"to_display", "instance_key"} if instance else {"kind", "mode", "type", "name", "to_display"}
    _check_fields(address, allowed, coverage)
    required = {"to_display"} if instance else {"kind", "name", "to_display"}
    if not required <= set(address):
        raise ValueError()
    if any(not isinstance(address[key], str) or not address[key]
           for key in (set(address) & allowed) - {"instance_key"}):
        raise ValueError()
    if instance:
        if "instance_key" in address and (type(address["instance_key"]) not in (str, int)
                or (type(address["instance_key"]) is int and address["instance_key"] < 0)):
            raise ValueError()
    elif address["kind"] not in ("resource", "output_value", "check", "var"):
        coverage["unsupported"].append("unknown_check_kind")
    elif address["kind"] == "resource" and (address.get("mode") not in ("managed", "data")
                                           or not address.get("type")):
        raise ValueError()


def classify_plan(plan, *, exit_code):
    """Allowlisted Terraform JSON 1.0/1.1/1.2; unknown formats fail partial.

    Exit 2 alone is never evidence of unauthorized drift. Missing coverage is
    explicit, not a claim about properties Terraform/providers do not model.
    """
    result = {"classes": [], "findings": [], "coverage": {
        "checked": [], "unsupported": [], "ignored": [], "unknown": [], "errors": []}}
    coverage = result["coverage"]
    if type(exit_code) is not int or exit_code not in (0, 2):
        result["classes"] = ["error"]
        coverage["errors"].append("terraform_execution_failed")
        return result
    if not isinstance(plan, dict) or plan.get("format_version") not in ("1.0", "1.1", "1.2"):
        result["classes"] = ["partial"]
        coverage["unsupported"].append("plan_format")
        return result
    if set(plan) - _PLAN_FIELDS:
        coverage["unsupported"].append("unknown_plan_fields")
    for field in ("complete", "errored", "applyable"):
        if field in plan and type(plan[field]) is not bool:
            coverage["errors"].append("malformed_completion_flag")
    if "deferred_changes" in plan and not isinstance(plan["deferred_changes"], list):
        coverage["errors"].append("malformed_deferred_changes")
    if plan.get("deferred_changes") or plan.get("complete") is False:
        coverage["unknown"].append("deferred_or_incomplete_plan")
    if plan.get("errored") is True:
        coverage["errors"].append("errored_plan")
    try:
        for field, kind in (("resource_drift", "external_drift"), ("resource_changes", "desired_change")):
            resources = plan.get(field, [])
            if not isinstance(resources, list):
                raise ValueError()
            for resource in resources:
                if set(resource) - {"address", "module_address", "mode", "type", "name", "index", "provider_name",
                                    "deposed", "change", "action_reason", "previous_address"}:
                    coverage["unsupported"].append("unknown_resource_fields")
                address = public_address(resource["address"])
                if address not in coverage["checked"]:
                    coverage["checked"].append(address)
                change = resource["change"]
                if set(change) - {"actions", "before", "after", "after_unknown", "before_sensitive", "after_sensitive",
                                  "replace_paths", "importing", "generated_config"}:
                    coverage["unsupported"].append("unknown_change_fields")
                actions = change["actions"]
                if not isinstance(actions, list) or tuple(actions) not in _ACTIONS:
                    raise ValueError()
                if _unknown(change.get("after_unknown")):
                    coverage["unknown"].append(address)
                if actions != ["no-op"]:
                    if kind not in result["classes"]:
                        result["classes"].append(kind)
                    result["findings"].append({"class": kind, "address": address, "actions": list(actions),
                                               "severity": "review", "next_action": "review_with_owner"})
        checks = plan.get("checks", [])
        if not isinstance(checks, list):
            raise ValueError()
        for check in checks:
            _check_fields(check, {"address", "status", "instances"}, coverage)
            status = check.get("status")
            if status == "fail":
                if "policy_noncompliance" not in result["classes"]:
                    result["classes"].append("policy_noncompliance")
            elif status != "pass":
                coverage["unknown"].append("unverified_policy_check")
            _check_address(check["address"], instance=False, coverage=coverage)
            if "instances" not in check:
                coverage["unknown"].append("missing_check_instances")
            instances = check.get("instances", [])
            if not isinstance(instances, list):
                raise ValueError()
            statuses = []
            for instance in instances:
                _check_fields(instance, {"address", "status", "failure_messages"}, coverage)
                instance_status = instance.get("status")
                if instance_status not in ("pass", "fail", "error", "unknown"):
                    raise ValueError()
                statuses.append(instance_status)
                if instance_status == "fail":
                    if "policy_noncompliance" not in result["classes"]:
                        result["classes"].append("policy_noncompliance")
                elif instance_status != "pass":
                    coverage["unknown"].append("unverified_policy_check_instance")
                _check_address(instance["address"], instance=True, coverage=coverage)
                messages = instance.get("failure_messages", [])
                if not isinstance(messages, list) or any(not isinstance(message, str) for message in messages):
                    raise ValueError()
                if messages and instance_status == "pass":
                    coverage["errors"].append("contradictory_check_messages")
            if ((status == "pass" and any(item != "pass" for item in statuses))
                    or (status != "pass" and statuses and status not in statuses)):
                coverage["errors"].append("contradictory_check_status")
        outputs = plan.get("output_changes", {})
        if not isinstance(outputs, dict):
            raise ValueError()
        for change in outputs.values():
            if not isinstance(change, dict):
                raise ValueError()
            if set(change) - {"actions", "before", "after", "after_unknown", "before_sensitive", "after_sensitive"}:
                coverage["unsupported"].append("unknown_output_change_fields")
            if not isinstance(change["actions"], list) or tuple(change["actions"]) not in _ACTIONS:
                raise ValueError()
            if _unknown(change.get("after_unknown")):
                coverage["unknown"].append("output_values")
            if change["actions"] != ["no-op"] and "desired_change" not in result["classes"]:
                result["classes"].append("desired_change")
    except (KeyError, TypeError, ValueError, AttributeError):
        coverage["errors"].append("malformed_plan_changes")
    if coverage["unsupported"] or coverage["unknown"] or coverage["errors"] or (exit_code == 2 and not result["classes"]):
        result["classes"].append("partial")
    if not result["classes"]:
        result["classes"] = ["clean_within_coverage"]
    coverage["checked"].sort()
    return result


CLASSES = frozenset({"clean_within_coverage", "external_drift", "desired_change", "policy_noncompliance",
                     "identity_mismatch", "locked", "error", "partial", "stale", "not_run"})


def make_report(*, deployment, scope, baseline, backend_digest, lineage, serial,
                observed_at, expires_at, now, plan=None, exit_code=0, status=None):
    from src.python.drift_config import SCOPES
    opaque_ref(deployment)
    if scope not in SCOPES:
        raise ValueError("Unsupported drift scope")
    require_digest(backend_digest)
    if lineage is not None:
        opaque_ref(lineage)
    if serial is not None and (type(serial) is not int or serial < 0):
        raise ValueError("Invalid state serial")
    if any(type(v) is not int or v < 0 for v in (observed_at, expires_at, now)) or expires_at <= observed_at:
        raise ValueError("Invalid report freshness interval")
    if status is not None and status not in CLASSES - {"clean_within_coverage"}:
        raise ValueError("Invalid explicit report status")
    result = classify_plan(plan, exit_code=exit_code)
    if status is not None:
        result["classes"] = [status]
    if baseline is None and "partial" not in result["classes"]:
        result["classes"] = [c for c in result["classes"] if c != "clean_within_coverage"] + ["partial"]
    if now >= expires_at or now < observed_at:
        result["classes"] = [c for c in result["classes"] if c != "clean_within_coverage"] + ["stale"]
    baseline_data = baseline.to_dict() if baseline is not None else None
    identity = {"deployment": deployment, "scope": scope, "backend_digest": backend_digest,
                "baseline": baseline_data}
    for finding in result["findings"]:
        finding["fingerprint"] = digest({**identity, "finding": finding})
    return {"schema_version": 1, **identity, "lineage": lineage, "serial": serial,
            "observed_at": observed_at, "expires_at": expires_at,
            "evidence_sources": ["terraform_plan"] if status is None else ["preflight"], **result}


def resolved_findings(previous, current, *, now):
    """Only successful fresh same-baseline rechecks resolve covered incidents."""
    if (current["classes"] != ["clean_within_coverage"] or not current["observed_at"] <= now < current["expires_at"]
            or current["observed_at"] <= previous["observed_at"]
            or any(previous[key] != current[key] for key in ("deployment", "scope", "backend_digest", "baseline", "lineage"))):
        return []
    covered = set(current["coverage"]["checked"])
    return sorted(f["fingerprint"] for f in previous["findings"] if f["address"] in covered)


def wrapper_exit_code(report):
    """Wrapper contract: 0 covered clean, 1 execution error, 2 findings, 3 incomplete/blocked.

    These are NOT Terraform's exit codes; partial findings retain exit 3.
    """
    classes = set(report["classes"])
    if "error" in classes:
        return 1
    if not classes or classes - CLASSES or classes & {"partial", "stale", "not_run", "locked", "identity_mismatch"}:
        return 3
    return 0 if classes == {"clean_within_coverage"} else 2
