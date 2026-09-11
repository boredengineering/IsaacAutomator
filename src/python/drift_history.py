"""Private, value-free local drift evidence; never an authenticated health claim.

Only sanitized drift_report / drift_detector reports are accepted. References
remain opaque metadata: this module never dereferences them or reads Terraform
state. No network, notifications, issue writes, or remediation side effects.
"""
import json
import os
import stat
import fcntl
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.python.drift_config import SCOPES, opaque_ref
from src.python.drift_report import Baseline, CLASSES, digest, public_address, require_digest, resolved_findings, wrapper_exit_code


class HistoryError(ValueError):
    """Fail-closed, nonsecret validation or persistence error."""


def _require(condition):
    if not condition:
        raise HistoryError("Invalid or unsafe drift history; diagnostics withheld")


def _exact(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _integer(value):
    _require(type(value) is int and 0 <= value <= 2**63 - 1)


def _list(value, limit=4096):
    _require(type(value) is list and len(value) <= limit)


def _address(value):
    _require(type(value) is str and len(value) <= 512 and public_address(value) == value)


_REQUIRED = frozenset({"schema_version", "deployment", "scope", "backend_digest", "baseline",
    "lineage", "serial", "observed_at", "expires_at", "evidence_sources", "classes", "findings", "coverage"})
_ERRORS = frozenset({"terraform_execution_failed", "malformed_completion_flag", "malformed_deferred_changes",
    "errored_plan", "contradictory_check_messages", "contradictory_check_status", "malformed_plan_changes"})
_UNKNOWN = frozenset({"deferred_or_incomplete_plan", "unverified_policy_check", "missing_check_instances",
    "unverified_policy_check_instance", "output_values"})
_ACTIONS = {("read",), ("create",), ("update",), ("delete",), ("delete", "create"), ("create", "delete"), ("forget",)}


def validate_report(value, *, max_bytes=262144):
    """Deep-copy a strict report, rejecting unknown fields rather than stripping.

    This is a schema boundary, not a general-purpose secret scanner: opaque IDs
    and static resource names must already be nonsecret at the trusted producer.
    """
    try:
        _require(type(max_bytes) is int and 1 <= max_bytes <= 1048576)
        _require(type(value) is dict and _REQUIRED <= set(value) <= _REQUIRED | {"lifecycle_intent", "exceptions"})
        intent = value.get("lifecycle_intent", "unspecified")
        _require(intent in ("unspecified", "stopped", "scheduled_scaling"))
        exceptions = value.get("exceptions", [])
        _list(exceptions, 100)
        for rule in exceptions:
            _exact(rule, {"resource_ref", "rule_ref", "owner_ref", "justification_ref", "baseline_ref", "expires_at", "status"})
            for key in ("resource_ref", "rule_ref", "owner_ref", "justification_ref", "baseline_ref"):
                opaque_ref(rule[key])
            _integer(rule["expires_at"])
            _require(rule["status"] in ("expired", "baseline_changed", "requires_owner_review"))
        _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        opaque_ref(value["deployment"])
        _require(value["scope"] in SCOPES)
        require_digest(value["backend_digest"])
        Baseline.from_dict(value["baseline"])
        if value["lineage"] is not None:
            opaque_ref(value["lineage"])
        if value["serial"] is not None:
            _integer(value["serial"])
        _integer(value["observed_at"])
        _integer(value["expires_at"])
        _require(value["expires_at"] > value["observed_at"])
        _list(value["classes"], len(CLASSES))
        _require(value["classes"] and all(type(c) is str and c in CLASSES for c in value["classes"]))
        _require(len(set(value["classes"])) == len(value["classes"]))
        _require(value["evidence_sources"] in (["terraform_plan"], ["preflight"]))
        coverage = value["coverage"]
        _exact(coverage, {"checked", "unsupported", "ignored", "unknown", "errors"})
        for key, entries in coverage.items():
            _list(entries)
            for entry in entries:
                if key == "checked":
                    _address(entry)
                elif key == "errors":
                    _require(type(entry) is str and entry in _ERRORS)
                elif key == "unknown":
                    if type(entry) is not str or entry not in _UNKNOWN:
                        _address(entry)
                        _require(entry in coverage["checked"])
                else:
                    opaque_ref(entry)
        _list(value["findings"])
        fingerprints = set()
        for finding in value["findings"]:
            _exact(finding, {"class", "address", "actions", "severity", "next_action", "fingerprint"})
            _require(finding["class"] in ("external_drift", "desired_change"))
            _address(finding["address"])
            _list(finding["actions"], 2)
            _require(tuple(finding["actions"]) in _ACTIONS)
            _require(finding["severity"] == "review" and finding["next_action"] ==
                     ("review_with_owner" if intent == "unspecified" else "review_lifecycle_intent"))
            require_digest(finding["fingerprint"])
            identity = {key: value[key] for key in ("deployment", "scope", "backend_digest", "baseline")}
            unsigned = {key: item for key, item in finding.items() if key != "fingerprint"}
            # Detector changes next_action AFTER make_report computes identity.
            unsigned["next_action"] = "review_with_owner"
            _require(finding["fingerprint"] == digest({**identity, "finding": unsigned}))
            _require(finding["fingerprint"] not in fingerprints)
            fingerprints.add(finding["fingerprint"])
        classes = set(value['classes'])
        plan_evidence = value['evidence_sources'] == ['terraform_plan']
        gaps = any(coverage[key] for key in ('unsupported', 'ignored', 'unknown', 'errors'))
        if 'clean_within_coverage' in classes:
            _require(classes == {'clean_within_coverage'} and not value['findings']
                     and not gaps and not exceptions and plan_evidence and value['baseline'] is not None)
        for finding in value['findings']:
            _require(finding['address'] in coverage['checked'])
            # make_report(status=...) explicitly overrides plan classes for
            # preflight/error evidence, but still retains classified findings.
            if plan_evidence:
                _require(finding['class'] in classes)
        if plan_evidence and (gaps or exceptions):
            _require(bool(classes & {'partial', 'error'}))
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        _require(len(encoded) <= max_bytes)
        return json.loads(encoded)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise HistoryError("Invalid or unsafe drift report; diagnostics withheld") from None


def report_identity(report):
    """Immutable stream identity; baseline stays in evidence for recheck matching."""
    value = validate_report(report)
    return {key: value[key] for key in ("deployment", "scope", "backend_digest", "lineage")}


def _identity(value):
    try:
        _exact(value, {"deployment", "scope", "backend_digest", "lineage"})
        opaque_ref(value["deployment"])
        _require(value["scope"] in SCOPES)
        require_digest(value["backend_digest"])
        if value["lineage"] is not None:
            opaque_ref(value["lineage"])
        return json.loads(json.dumps(value))
    except (ValueError, TypeError, KeyError):
        raise HistoryError("Invalid drift identity") from None


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _serial_high_water(high_water, value):
    if value['lineage'] is not None and value['serial'] is not None:
        return value['serial'] if high_water is None else max(high_water, value['serial'])
    return high_water


def _serial_regressed(value, high_water):
    return (value['lineage'] is not None and value['serial'] is not None
            and high_water is not None and value['serial'] < high_water)


def _covered_clean(value, *, now, serial_high_water=None):
    return (value["classes"] == ["clean_within_coverage"] and not value["findings"]
            and not _serial_regressed(value, serial_high_water)
            and value["baseline"] is not None and value["baseline"]["applied_at"] <= value["observed_at"]
            and value["lineage"] is not None and value["serial"] is not None
            and value["evidence_sources"] == ["terraform_plan"]
            and value["observed_at"] <= now < value["expires_at"]
            and bool(value["coverage"]["checked"]) and not value.get("exceptions")
            and not any(value["coverage"][key] for key in ("ignored", "unsupported", "unknown", "errors")))


class _Corrupt(HistoryError):
    pass


class HistoryStore:
    """One immutable identity per dedicated absolute root; no implicit default.

    Root must be current-user-owned mode 0700. Ancestors must be owned by
    root/current user and protected against other users' replacement (sticky
    /tmp permitted). One digest-named snapshot and a 0600 flock file are used.
    Linux dirfd/NOFOLLOW, atomic replace and fsync are required. Nonblocking
    flock contention is unavailable/HistoryError, so a stuck writer cannot hang
    this watchdog. Retry policy belongs to the caller, not this store.

    Retention trims observations on successful new writes, not on reads. Live
    incidents survive age/count pruning; overflow refuses a write rather than
    implying resolution. max_total_bytes bounds snapshot + atomic staging file
    (each receives half the budget); this dedicated root accepts one identity,
    one zero-byte lock, and no unrelated files. Abandoned staging files require
    explicit reconciliation. Defaults: 32 observations, 7 days, 256 incidents,
    2 MiB total, with a separate 256 KiB sanitized-report ceiling.

    Same-UID/root adversaries or rollback of the entire directory cannot be
    authenticated by a local receipt. An error after replace/fsync may leave
    the new snapshot committed: re-read and reconcile, never assume rollback.
    """
    def __init__(self, root, *, identity, max_records=32, retention_seconds=604800,
                 max_total_bytes=2097152, max_incidents=256):
        for number, low, high in ((max_records, 1, 512), (retention_seconds, 1, 7776000),
                                  (max_total_bytes, 1024, 16777216), (max_incidents, 1, 4096)):
            _require(type(number) is int and low <= number <= high)
        self.max_records = max_records
        self.retention_seconds = retention_seconds
        self.max_snapshot_bytes = max_total_bytes // 2
        self.max_incidents = max_incidents
        self.root = Path(root)
        _require(self.root.is_absolute() and ".." not in self.root.parts and len(self.root.parts) > 1)
        self._identity_json = _encoded(_identity(identity))
        self._name = digest(identity) + ".json"

    @property
    def identity(self):
        return json.loads(self._identity_json)

    @staticmethod
    def _safe_dir(fd, private=False):
        info = os.fstat(fd)
        _require(stat.S_ISDIR(info.st_mode))
        if private:
            _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        else:
            _require(info.st_uid in (0, os.getuid()) and
                     (not info.st_mode & 0o022 or bool(info.st_mode & stat.S_ISVTX)))

    @staticmethod
    def _regular(fd):
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                 stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)
        return info

    def _walk(self, create=False):
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._safe_dir(fd)
            for index, part in enumerate(self.root.parts[1:]):
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self._safe_dir(fd, private=index == len(self.root.parts) - 2)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _stamp(directory, name):
        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        except FileNotFoundError:
            return None

    def _guard(self, directory, lock, temporary=None):
        canonical = self._walk()
        try:
            a, b = os.fstat(canonical), os.fstat(directory)
            _require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino))
        finally:
            os.close(canonical)
        info = self._regular(lock)
        stamp = self._stamp(directory, ".history.lock")
        _require(stamp is not None and stamp[:2] == (info.st_dev, info.st_ino) and info.st_size == 0)
        allowed = {self._name, ".history.lock"}
        if temporary is not None:
            allowed.add(temporary)
        # A dedicated root bounds identities as well as bytes. Unknown or
        # abandoned files require explicit reconciliation, never silent deletion.
        _require(set(os.listdir(directory)) <= allowed)

    @contextmanager
    def _directory(self, create=False):
        directory = self._walk(create)
        lock = None
        try:
            if not create and not os.listdir(directory):
                yield None
                return
            lock = os.open(".history.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK |
                           (os.O_CREAT if create else 0), 0o600, dir_fd=directory)
            self._regular(lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._guard(directory, lock)
            yield directory, lock
            self._guard(directory, lock)
        except (OSError, TypeError):
            raise HistoryError("Private drift history changed or is unavailable") from None
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)

    def _read(self, directory):
        try:
            fd = os.open(self._name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            before = self._regular(stream.fileno())
            expected = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            _require(self._stamp(directory, self._name) == expected)
            data = stream.read(self.max_snapshot_bytes + 1)
            after = self._regular(stream.fileno())
            _require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == expected)
            _require(self._stamp(directory, self._name) == expected)
        try:
            _require(len(data) <= self.max_snapshot_bytes)
            value = json.loads(data, object_pairs_hook=_unique)
            required = {"schema_version", "identity", "records", "incidents"}
            _require(type(value) is dict and required <= set(value) <= required | {'serial_high_water'})
            _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
            _require(_identity(value["identity"]) == self.identity)
            _list(value["records"], self.max_records)
            _require(bool(value["records"]))
            last_observed, last_received = -1, -1
            high_water = None
            retained_active = {}
            for record in value["records"]:
                _exact(record, {"received_at", "report"})
                _integer(record["received_at"])
                validate_report(record["report"])
                _require(report_identity(record["report"]) == self.identity)
                current = record["report"]
                _require(last_observed < current["observed_at"] <= record["received_at"] and last_received <= record["received_at"])
                last_observed, last_received = current["observed_at"], record["received_at"]
                if _covered_clean(current, now=record["received_at"], serial_high_water=high_water):
                    retained_active = {fp: prior for fp, prior in retained_active.items()
                        if fp not in resolved_findings(prior, current, now=record["received_at"])}
                high_water = _serial_high_water(high_water, current)
                retained_active.update({f["fingerprint"]: current for f in current["findings"]})
            _list(value["incidents"], self.max_incidents)
            seen = set()
            for incident in value["incidents"]:
                _exact(incident, {"fingerprint", "first_seen", "last_seen", "report"})
                require_digest(incident["fingerprint"])
                _integer(incident["first_seen"])
                _integer(incident["last_seen"])
                previous = validate_report(incident["report"])
                _require(report_identity(previous) == self.identity)
                high_water = _serial_high_water(high_water, previous)
                _require(incident["first_seen"] <= incident["last_seen"] == previous["observed_at"] <= last_observed)
                _require(incident["fingerprint"] in {f["fingerprint"] for f in previous["findings"]})
                _require(incident["fingerprint"] not in seen)
                seen.add(incident["fingerprint"])
            _require(set(retained_active) <= seen)
            # Older snapshots derive the floor from retained evidence. New
            # snapshots persist it independently of observation/incident pruning.
            stored_high_water = value.get('serial_high_water', high_water)
            if stored_high_water is not None:
                _integer(stored_high_water)
                _require(self.identity['lineage'] is not None)
            _require(high_water is None or (stored_high_water is not None and stored_high_water >= high_water))
            value['serial_high_water'] = stored_high_water
            return value
        except (ValueError, TypeError, KeyError, RecursionError):
            raise _Corrupt("Corrupt drift history; diagnostics withheld") from None

    def load(self):
        """Read without creating directories; absence is not an empty history."""
        try:
            with self._directory() as opened:
                value = self._read(opened[0]) if opened is not None else None
            return {"status": "available" if value is not None else "missing", "history": value}
        except FileNotFoundError:
            return {"status": "missing", "history": None}
        except _Corrupt:
            return {"status": "corrupt", "history": None}
        except (OSError, HistoryError):
            return {"status": "unavailable", "history": None}

    def assess(self, *, now, heartbeat_at, max_check_age, max_heartbeat_age):
        """Read-only JSON-ready watchdog, using a caller-supplied independent clock.

        heartbeat_at is an observation from the trusted scheduler/watchdog,
        never inferred from file mtime, receipt time, or detector success. None
        means heartbeat missing. `healthy` is strictly local, within reported
        coverage, NOT cloud readiness. wrapper_exit_code preserves the original
        report contract except a known serial rollback is vetoed as incomplete;
        consumers must also inspect monitoring_gap/reasons.
        """
        _integer(now)
        for age in (max_check_age, max_heartbeat_age):
            _integer(age)
            _require(age > 0)
        reasons = set()
        if heartbeat_at is None:
            heartbeat_status = "missing"
            reasons.add("missing_heartbeat")
        else:
            _integer(heartbeat_at)
            if heartbeat_at > now:
                heartbeat_status = "invalid"
                reasons.add("clock_invalid")
            elif now - heartbeat_at >= max_heartbeat_age:
                heartbeat_status = "stale"
                reasons.add("stale_heartbeat")
            else:
                heartbeat_status = "fresh"
        loaded = self.load()
        result = {"schema_version": 1, "identity_digest": self._name[:-5], "assessed_at": now,
            "history_status": loaded["status"], "heartbeat_status": heartbeat_status,
            "latest_observed_at": None, "latest_received_at": None, "wrapper_exit_code": None,
            "active_fingerprints": [], "expired_exceptions": 0, "drift_status": "unknown",
            "healthy": False, "monitoring_gap": True, "reasons": []}
        if loaded["status"] != "available":
            reasons.add({"missing": "missing_check", "corrupt": "corrupt_history", "unavailable": "history_unavailable"}[loaded["status"]])
        else:
            history = loaded["history"]
            latest = history["records"][-1]
            value = latest["report"]
            observed = value["observed_at"]
            result.update(latest_observed_at=observed, latest_received_at=latest["received_at"],
                          wrapper_exit_code=wrapper_exit_code(value),
                          active_fingerprints=sorted(i["fingerprint"] for i in history["incidents"]),
                          expired_exceptions=sum(r["expires_at"] <= now for r in value.get("exceptions", [])))
            if now < observed or now < latest["received_at"]:
                reasons.add("clock_invalid")
            if _serial_regressed(value, history['serial_high_water']):
                reasons.add('state_serial_regressed')
                result['wrapper_exit_code'] = 3
            if now >= value["expires_at"] or now - observed >= max_check_age or "stale" in value["classes"]:
                reasons.add("stale_check")
            if "error" in value["classes"]:
                reasons.add("detector_failed")
            if set(value["classes"]) & {"not_run", "locked", "identity_mismatch"}:
                reasons.add("check_blocked")
            if (not value["coverage"]["checked"] or value["baseline"] is None
                    or value["lineage"] is None or value["serial"] is None
                    or value["evidence_sources"] != ["terraform_plan"]
                    or "partial" in value["classes"] or value.get("exceptions")
                    or any(value["coverage"][key] for key in ("ignored", "unsupported", "unknown", "errors"))):
                reasons.add("incomplete_coverage")
            result["monitoring_gap"] = bool(reasons)
            if result["active_fingerprints"] or set(value["classes"]) & {"external_drift", "desired_change", "policy_noncompliance"}:
                result["drift_status"] = "findings"
            elif not reasons and _covered_clean(value, now=now):
                result["drift_status"] = "clean_within_coverage"
                result["healthy"] = True
        result["reasons"] = sorted(reasons)
        return result

    def record(self, report, *, received_at):
        """Persist sanitized evidence atomically; errors never include OS details."""
        value = validate_report(report)
        _integer(received_at)
        _require(value["observed_at"] <= received_at)
        _require(report_identity(value) == self.identity)
        _require(len(_encoded(value)) <= self.max_snapshot_bytes)
        try:
            with self._directory(create=True) as opened:
                directory, lock = opened
                previous_stamp = self._stamp(directory, self._name)
                history = self._read(directory) or {"schema_version": 1, "identity": self.identity,
                    "records": [], "incidents": [], "serial_high_water": None}
                if history["records"]:
                    latest = history["records"][-1]
                    _require(received_at >= latest["received_at"] and value["observed_at"] >= latest["report"]["observed_at"])
                    if value["observed_at"] == latest["report"]["observed_at"]:
                        _require(value == latest["report"])
                        return {"status": "duplicate", "opened": [], "resolved": []}
                active = {i["fingerprint"]: i for i in history["incidents"]}
                resolved = set()
                if _covered_clean(value, now=received_at, serial_high_water=history['serial_high_water']):
                    for fingerprint, incident in active.items():
                        if fingerprint in resolved_findings(incident["report"], value, now=received_at):
                            resolved.add(fingerprint)
                for fingerprint in resolved:
                    del active[fingerprint]
                opened = []
                for finding in value["findings"]:
                    fingerprint = finding["fingerprint"]
                    if fingerprint not in active:
                        opened.append(fingerprint)
                    active[fingerprint] = {"fingerprint": fingerprint,
                        "first_seen": active.get(fingerprint, {}).get("first_seen", value["observed_at"]),
                        "last_seen": value["observed_at"], "report": value}
                _require(len(active) <= self.max_incidents)
                history["incidents"] = [active[key] for key in sorted(active)]
                history['serial_high_water'] = _serial_high_water(history['serial_high_water'], value)
                history["records"].append({"received_at": received_at, "report": value})
                history["records"] = [r for r in history["records"]
                    if r["received_at"] >= received_at - self.retention_seconds][-self.max_records:]
                while len(_encoded(history)) > self.max_snapshot_bytes and len(history["records"]) > 1:
                    history["records"].pop(0)
                encoded = _encoded(history)
                _require(len(encoded) <= self.max_snapshot_bytes)
                temporary = ".history-" + uuid.uuid4().hex
                try:
                    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(encoded)
                        stream.flush()
                        info = self._regular(stream.fileno())
                        staged = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                        os.fsync(stream.fileno())
                        self._regular(stream.fileno())
                        _require(self._stamp(directory, temporary) == staged)
                    self._guard(directory, lock, temporary)
                    _require(self._stamp(directory, self._name) == previous_stamp)
                    os.replace(temporary, self._name, src_dir_fd=directory, dst_dir_fd=directory)
                    os.fsync(directory)
                    self._guard(directory, lock)
                    published = self._stamp(directory, self._name)
                    _require(published is not None and published[:2] == staged[:2])
                    _require(self._read(directory) == history)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass
            return {"status": "recorded", "opened": sorted(opened), "resolved": sorted(resolved)}
        except (OSError, HistoryError):
            raise HistoryError("Cannot persist private drift history; diagnostics withheld") from None
