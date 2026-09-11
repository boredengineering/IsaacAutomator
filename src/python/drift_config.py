"""Nonsecret opt-in drift configuration. No scheduling or cloud side effects."""
from dataclasses import dataclass
import re
import json
import time

SCOPES = frozenset({"backend_infrastructure", "workstation_infrastructure",
                    "controller_identity", "runtime"})


def opaque_ref(value):
    """References resolve through trusted stores, never arbitrary URLs/paths."""
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value):
        raise ValueError("Expected an opaque nonsecret reference")
    return value


def strict_block(data, fields):
    if not isinstance(data, dict) or set(data) - set(fields):
        raise ValueError("Unknown fields or secret-bearing configuration are forbidden")
    return data


@dataclass(frozen=True)
class ExceptionRule:
    resource_ref: str
    rule_ref: str
    owner_ref: str
    justification_ref: str
    baseline_ref: str
    expires_at: int


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Integer setting outside supported bounds")
    return value


def validate_schedule(schedule):
    if not isinstance(schedule, str) or len(schedule.split()) != 5:
        raise ValueError("Expected five-field UTC cron schedule")
    for field, (low, high) in zip(schedule.split(), ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))):
        for item in field.split(","):
            if item == "*":
                continue
            if re.fullmatch(r"\*/[0-9]+", item):
                bounded(int(item[2:]), 1, high + 1)
            elif re.fullmatch(r"[0-9]+", item):
                bounded(int(item), low, high)
            else:
                raise ValueError("Unsupported cron field; use integers, lists, wildcard or wildcard step")


@dataclass(frozen=True)
class DriftConfig:
    schema_version: int = 1
    enabled: bool = False
    scopes: tuple = ()
    schedule: str | None = None
    executor: str = "on_demand"
    correction: str = "report_only"

    identity_ref: str | None = None
    baseline_ref: str | None = None
    reporting_ref: str | None = None
    retention_days: int = 7
    command_timeout: int = 300
    lock_timeout: int = 30
    exceptions: tuple = ()

    @classmethod
    def from_dict(cls, data, *, now=None):
        data = strict_block({} if data is None else data,
                            {"schema_version", "enabled", "scopes", "schedule", "executor",
                             "correction", "identity_ref", "baseline_ref", "reporting_ref",
                             "retention_days", "command_timeout", "lock_timeout", "exceptions"})
        if type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) != 1:
            raise ValueError("Only schema version 1 is supported")
        enabled = data.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        scopes = data.get("scopes", [])
        if (not isinstance(scopes, list) or any(not isinstance(s, str) or s not in SCOPES for s in scopes)
                or len(set(scopes)) != len(scopes) or (bool(scopes) != enabled)):
            raise ValueError("Enabled detection requires unique explicit supported scopes")
        executor = data.get("executor", "on_demand")
        if executor not in ("on_demand", "github_actions"):
            raise ValueError("Cloud-native execution/rule engines are unsupported")
        schedule = data.get("schedule")
        if schedule is not None:
            if executor != "github_actions" or not enabled:
                raise ValueError("Schedules require explicit enabled GitHub Actions execution")
            validate_schedule(schedule)
        correction = data.get("correction", "report_only")
        if correction not in ("report_only", "approval_required"):
            raise ValueError("Automatic/preauthorized correction is unsupported")
        identity = data.get("identity_ref")
        if identity is not None:
            opaque_ref(identity)
        refs = {key: data.get(key) for key in ("baseline_ref", "reporting_ref")}
        for value in refs.values():
            if value is not None:
                opaque_ref(value)
        settings = {key: bounded(data.get(key, default), 1, maximum)
                    for key, default, maximum in (("retention_days", 7, 90),
                        ("command_timeout", 300, 900), ("lock_timeout", 30, 120))}
        exceptions = data.get("exceptions", [])
        if not isinstance(exceptions, list) or len(exceptions) > 100:
            raise ValueError("Expected bounded exception list")
        rules = []
        now = time.time() if now is None else now
        for item in exceptions:
            strict_block(item, ExceptionRule.__dataclass_fields__)
            if set(item) != set(ExceptionRule.__dataclass_fields__):
                raise ValueError("Exception requires exact ownership, justification and baseline")
            for key, value in item.items():
                if key != "expires_at":
                    opaque_ref(value)
            if type(item["expires_at"]) is not int or not now < item["expires_at"] <= now + 2592000:
                raise ValueError("Exception expired or exceeds 30-day limit")
            rules.append(ExceptionRule(**item))
        return cls(enabled=enabled, scopes=tuple(scopes), executor=executor,
                   correction=correction, identity_ref=identity, schedule=schedule,
                   exceptions=tuple(rules), **refs, **settings)

    @classmethod
    def from_json(cls, text, **kwargs):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate configuration field")
                result[key] = value
            return result
        try:
            data = json.loads(text, object_pairs_hook=unique)
        except (TypeError, json.JSONDecodeError):
            raise ValueError("Invalid configuration JSON") from None
        return cls.from_dict(data, **kwargs)
