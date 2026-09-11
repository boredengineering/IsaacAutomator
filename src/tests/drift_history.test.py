"""Offline history/watchdog tests using real reports and temporary paths only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from src.python.drift_report import Baseline, make_report, digest

BASELINE = dict(schema_version=1, source_revision="a" * 40, input_digest="b" * 64,
                lock_digest="c" * 64, source_digest="d" * 64, inputs_ref="protected-inputs",
                source_ref="protected-source", applied_at=10)


def report(at=100, *, actions=("update",), status=None, baseline=None, address="terraform_data.example"):
    resource = {"address": address, "change": {"actions": list(actions),
                "before": {"password": "RAW-SECRET"}, "after": {"password": "OTHER-SECRET"}}}
    plan = {"format_version": "1.2", "resource_drift" if actions != ("no-op",) else "resource_changes": [resource]}
    return make_report(deployment="fixture", scope="workstation_infrastructure",
        baseline=Baseline.from_dict(BASELINE if baseline is None else baseline), backend_digest="e" * 64,
        lineage="lineage", serial=1, observed_at=at, expires_at=at + 60, now=at,
        plan=plan, exit_code=2 if actions != ("no-op",) else 0, status=status)


def module():
    return __import__("src.python.drift_history", fromlist=["*"])


class HistoryTests(unittest.TestCase):
    def test_strict_sanitized_report_boundary_uses_actual_report_shape(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.drift_history"), "history API missing")
        dh = module()
        original = report()
        self.assertEqual(dh.validate_report(original), original)
        self.assertNotIn("SECRET", json.dumps(dh.validate_report(original)))
        bad = [([], "plan", {"values": "SECRET"}), (["baseline"], "values", "SECRET"),
               (["coverage"], "diagnostics", "SECRET"), (["findings", 0], "before", "SECRET"),
               (["findings", 0], "severity", "SECRET"), (["coverage"], "errors", ["SECRET diagnostic"]),
               (["coverage"], "unknown", ["ARBITRARY_DIAGNOSTIC"]),
               ([], "schema_version", True), ([], "observed_at", True),
               ([], "classes", ["SECRET"]), ([], "evidence_sources", ["SECRET"]),
               ([], "deployment", "../outside"), (["findings", 0], "fingerprint", "0" * 64)]
        for path, key, value in bad:
            mutated = copy.deepcopy(original)
            target = mutated
            for part in path:
                target = target[part]
            target[key] = value
            with self.subTest(path=path, key=key):
                with self.assertRaises(dh.HistoryError) as caught:
                    dh.validate_report(mutated)
                self.assertNotIn("SECRET", str(caught.exception))
        checked = dh.validate_report(original)
        checked["findings"].clear()
        self.assertTrue(original["findings"])

    def test_semantic_class_finding_and_coverage_contradictions_are_sanitized(self):
        dh = module()
        cases = []
        for classes in (["clean_within_coverage"], ["desired_change"]):
            value = report(110)
            value['classes'] = classes
            cases.append(value)
        value = report(110)
        value['coverage']['checked'] = []
        cases.append(value)
        for gap, entry in (('unknown', 'output_values'), ('errors', 'errored_plan'),
                           ('ignored', 'reviewed-rule'), ('unsupported', 'plan_format')):
            for actions in (("no-op",), ("update",)):
                value = report(110, actions=actions)
                value['coverage'][gap] = [entry]
                cases.append(value)
        for change in ({'classes': ['clean_within_coverage', 'partial']}, {'baseline': None},
                       {'evidence_sources': ['preflight']}):
            value = report(110, actions=("no-op",))
            value.update(change)
            cases.append(value)
        with tempfile.TemporaryDirectory() as tmp:
            store = dh.HistoryStore(Path(tmp) / 'history', identity=dh.report_identity(report()))
            store.record(report(), received_at=100)
            target = store.root / (digest(store.identity) + '.json')
            saved = target.read_bytes()
            for index, value in enumerate(cases):
                with self.subTest(case=index):
                    for action in (lambda: dh.validate_report(value),
                                   lambda: store.record(value, received_at=110)):
                        with self.assertRaises(dh.HistoryError) as caught:
                            action()
                        self.assertEqual(str(caught.exception), 'Invalid or unsafe drift report; diagnostics withheld')
                    self.assertEqual(target.read_bytes(), saved)
            # Producers may override classes for preflight failures while
            # retaining prior classified findings. These are not clean evidence.
            for status in ('error', 'not_run', 'locked', 'identity_mismatch', 'partial', 'stale'):
                value = report(120, status=status)
                self.assertEqual(dh.validate_report(value), value)
            for plan, exit_code in ((None, 1), ({'format_version': '1.2', 'errored': True}, 0),
                                    ({'format_version': '1.2', 'output_changes': {'label': {'actions': ['update']}}}, 2)):
                value = make_report(deployment='fixture', scope='workstation_infrastructure',
                    baseline=Baseline.from_dict(BASELINE), backend_digest='e' * 64,
                    lineage='lineage', serial=1, observed_at=120, expires_at=180, now=120,
                    plan=plan, exit_code=exit_code)
                self.assertEqual(dh.validate_report(value), value)

    def test_detector_optional_metadata_is_allowlisted_not_a_suppression(self):
        dh = module()
        value = report()
        value["lifecycle_intent"] = "stopped"
        value["findings"][0]["next_action"] = "review_lifecycle_intent"
        value["exceptions"] = [{"resource_ref": "resource-id", "rule_ref": "rule-id", "owner_ref": "owner",
            "justification_ref": "review-ticket", "baseline_ref": "baseline-id", "expires_at": 110,
            "status": "requires_owner_review"}]
        value["coverage"]["ignored"] = ["reviewed-rule"]
        value["classes"].append("partial")
        self.assertEqual(dh.validate_report(value), value)
        for field, replacement in (("status", "approved"), ("justification_ref", "SECRET diagnostic"),
                                   ("expires_at", True), ("values", {})):
            wrong = copy.deepcopy(value)
            wrong["exceptions"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(dh.HistoryError):
                dh.validate_report(wrong)
        for state in ("expired", "baseline_changed"):
            value["exceptions"][0]["status"] = state
            self.assertEqual(dh.validate_report(value)["findings"], value["findings"])

    def test_private_atomic_roundtrip_fsyncs_new_parents(self):
        dh = module()
        self.assertTrue(hasattr(dh, "HistoryStore"), "private history persistence missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fresh" / "history"
            value = report()
            store = dh.HistoryStore(root, identity=dh.report_identity(value))
            self.assertEqual(store.load()["status"], "missing")
            self.assertFalse(root.exists())
            events = []
            original_mkdir, original_fsync = os.mkdir, os.fsync
            def mkdir(path, *args, **kwargs):
                result = original_mkdir(path, *args, **kwargs)
                info = os.fstat(kwargs["dir_fd"])
                events.append(("mkdir", info.st_ino))
                return result
            def fsync(fd):
                info = os.fstat(fd)
                events.append(("fsync", info.st_ino))
                return original_fsync(fd)
            with patch.object(dh.os, "mkdir", side_effect=mkdir), patch.object(dh.os, "fsync", side_effect=fsync):
                result = store.record(value, received_at=101)
            self.assertEqual(result["status"], "recorded")
            loaded = store.load()
            self.assertEqual(loaded["status"], "available")
            self.assertEqual(loaded["history"]["records"][-1], {"received_at": 101, "report": value})
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            for path in root.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.stat().st_uid, os.getuid())
                self.assertNotIn("SECRET", path.read_text())
            self.assertTrue((root / (digest(dh.report_identity(value)) + ".json")).is_file())
            for index, (event, inode) in enumerate(events):
                if event == "mkdir":
                    self.assertEqual(events[index + 1], ("fsync", inode))

    def test_unsafe_paths_mutation_races_and_failed_writes_never_report_success(self):
        dh = module()
        for scenario in ("ancestor_symlink", "writable_ancestor", "public_root", "report_symlink", "hardlink",
                         "fifo", "wrong_owner", "rename_replace", "lock_replace", "report_replace", "write_failure", "identity"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                ancestor = Path(tmp) / "ancestor"
                root = ancestor / "history"
                store = dh.HistoryStore(root, identity=dh.report_identity(report()))
                store.record(report(), received_at=100)
                target = root / (digest(store.identity) + ".json")
                before = target.read_bytes()
                real_replace, real_fsync = os.replace, os.fsync
                if scenario == "ancestor_symlink":
                    ancestor.rename(Path(tmp) / "other")
                    ancestor.symlink_to(Path(tmp) / "other", target_is_directory=True)
                elif scenario == "writable_ancestor":
                    ancestor.chmod(0o777)
                elif scenario == "public_root":
                    root.chmod(0o755)
                elif scenario in ("report_symlink", "hardlink", "fifo"):
                    outside = Path(tmp) / "outside"
                    target.rename(outside)
                    if scenario == "report_symlink":
                        target.symlink_to(outside)
                    elif scenario == "hardlink":
                        os.link(outside, target)
                    else:
                        os.mkfifo(target, 0o600)
                elif scenario == "wrong_owner":
                    if os.getuid() != 0:
                        continue
                    os.chown(target, 65534, -1)
                elif scenario == "identity":
                    store = dh.HistoryStore(root, identity={**store.identity, "deployment": "other"})
                def replace(*args, **kwargs):
                    if scenario == "rename_replace":
                        ancestor.rename(Path(tmp) / "detached")
                    return real_replace(*args, **kwargs)
                changed = False
                def fsync(fd):
                    nonlocal changed
                    if not stat.S_ISDIR(os.fstat(fd).st_mode) and not changed:
                        changed = True
                        if scenario in ("lock_replace", "report_replace"):
                            victim = root / ".history.lock" if scenario == "lock_replace" else target
                            victim.rename(root / "detached-file")
                            victim.write_bytes(b"{}")
                            victim.chmod(0o600)
                        if scenario == "write_failure":
                            raise OSError("SECRET disk failure")
                    return real_fsync(fd)
                with patch.object(dh.os, "replace", side_effect=replace), patch.object(dh.os, "fsync", side_effect=fsync):
                    with self.assertRaises(dh.HistoryError) as caught:
                        store.record(report(110) if scenario != "identity" else {**report(110, actions=("no-op",)), "deployment": "other"}, received_at=110)
                self.assertNotIn("SECRET", str(caught.exception))
                if scenario == "write_failure":
                    self.assertEqual(target.read_bytes(), before)
                    self.assertEqual(sorted(p.name for p in root.iterdir()), sorted([target.name, ".history.lock"]))
        with tempfile.TemporaryDirectory() as tmp:
            unsafe = Path(tmp) / "unsafe"
            unsafe.mkdir()
            unsafe.chmod(0o777)
            with self.assertRaises(dh.HistoryError):
                dh.HistoryStore(unsafe / "new" / "history", identity=dh.report_identity(report())).record(report(), received_at=100)
            self.assertFalse((unsafe / "new").exists())

    def test_incident_dedup_survives_retention_and_only_covered_recheck_resolves(self):
        dh = module()
        with tempfile.TemporaryDirectory() as tmp:
            store = dh.HistoryStore(Path(tmp) / "history", identity=dh.report_identity(report()))
            first = store.record(report(), received_at=100)
            fp = report()["findings"][0]["fingerprint"]
            self.assertEqual(first.get("opened"), [fp], "incident transition missing")
            for value in (report(), report(105)):
                result = store.record(value, received_at=105)
                self.assertEqual(result["opened"], [])
                self.assertEqual(result["resolved"], [])
            for value in (report(110, status="error"), report(115, actions=("no-op",), address="terraform_data.other"),
                          report(120, actions=("no-op",), baseline={**BASELINE, "source_revision": "f" * 40}),
                          report(125, status="not_run")):
                self.assertEqual(store.record(value, received_at=value["observed_at"])["resolved"], [])
                self.assertEqual(len(store.load()["history"]["incidents"]), 1)
            result = store.record(report(130, actions=("no-op",)), received_at=130)
            self.assertEqual(result["resolved"], [fp])
            self.assertEqual(store.load()["history"]["incidents"], [])
            self.assertEqual(store.record(report(135), received_at=135)["opened"], [fp])
            with self.assertRaises(dh.HistoryError):
                store.record(report(129), received_at=140)
            with self.assertRaises(dh.HistoryError):
                store.record(report(140), received_at=139)

    def test_serial_rollback_never_resolves_or_becomes_healthy_after_retention(self):
        dh = module()
        for initial_actions in (("update",), ("no-op",)):
            for max_records in (1, 32):
                with self.subTest(actions=initial_actions, max_records=max_records), tempfile.TemporaryDirectory() as tmp:
                    first = report(100, actions=initial_actions)
                    first['serial'] = 100
                    root = Path(tmp) / 'history'
                    identity = dh.report_identity(first)
                    store = dh.HistoryStore(root, identity=identity, max_records=max_records)
                    store.record(first, received_at=100)
                    fingerprints = [f['fingerprint'] for f in first['findings']]
                    for at, serial in ((110, 1), (120, None), (130, 2)):
                        clean = report(at, actions=("no-op",))
                        clean['serial'] = serial
                        transition = store.record(clean, received_at=at)
                        self.assertEqual(transition['resolved'], [])
                        # Restart and retain at most one observation: rollback
                        # knowledge must not depend on an in-memory predecessor.
                        store = dh.HistoryStore(root, identity=identity, max_records=max_records)
                        assessment = store.assess(now=at + 1, heartbeat_at=at + 1,
                            max_check_age=60, max_heartbeat_age=60)
                        self.assertFalse(assessment['healthy'])
                        self.assertTrue(assessment['monitoring_gap'])
                        self.assertEqual(assessment['active_fingerprints'], fingerprints)
                        if serial is not None:
                            self.assertIn('state_serial_regressed', assessment['reasons'])
                            self.assertEqual(assessment['wrapper_exit_code'], 3)
                    recheck = report(140, actions=("no-op",))
                    recheck['serial'] = 100
                    self.assertEqual(store.record(recheck, received_at=140)['resolved'], fingerprints)
                    self.assertTrue(store.assess(now=141, heartbeat_at=141,
                        max_check_age=60, max_heartbeat_age=60)['healthy'])

    def test_retention_bounds_total_bytes_without_forgetting_unresolved_incidents(self):
        dh = module()
        import inspect
        self.assertIn("max_total_bytes", inspect.signature(dh.HistoryStore).parameters, "history bounds missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            store = dh.HistoryStore(root, identity=dh.report_identity(report()), max_records=2,
                                    retention_seconds=15, max_total_bytes=12000, max_incidents=1)
            store.record(report(), received_at=100)
            sizes = []
            real_fsync = os.fsync
            def fsync(fd):
                sizes.append(sum(p.stat().st_size for p in root.iterdir()))
                return real_fsync(fd)
            with patch.object(dh.os, "fsync", side_effect=fsync):
                for at in (110, 120, 130):
                    store.record(report(at, actions=("no-op",), status="error"), received_at=at)
            history = store.load()["history"]
            self.assertEqual([r["report"]["observed_at"] for r in history["records"]], [120, 130])
            self.assertEqual(len(history["incidents"]), 1)
            self.assertLessEqual(max(sizes), 12000)
            target = root / (digest(store.identity) + ".json")
            before = target.read_bytes()
            with self.assertRaises(dh.HistoryError):
                store.record(report(140, address="terraform_data.second"), received_at=140)
            self.assertEqual(before, target.read_bytes())
            self.assertEqual(store.record(report(140), received_at=140)["opened"], [])
            self.assertEqual(store.record(report(150, actions=("no-op",)), received_at=150)["resolved"],
                             [report()["findings"][0]["fingerprint"]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            store = dh.HistoryStore(root, identity=dh.report_identity(report()), max_total_bytes=1024)
            with self.assertRaises(dh.HistoryError):
                store.record(report(), received_at=100)
            self.assertFalse(root.exists(), "oversized initial report must fail before mkdir")

    def test_missing_unavailable_corrupt_and_read_replacement_are_distinct(self):
        dh = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            store = dh.HistoryStore(root, identity=dh.report_identity(report()))
            self.assertEqual(store.load()["status"], "missing")
            store.record(report(), received_at=100)
            target = root / (digest(store.identity) + ".json")
            original = target.read_bytes()
            for data in (b"{}", b"", b'{"schema_version":1,"schema_version":1}',
                         original.replace(b'"received_at":100', b'"received_at":true'),
                         original.replace(b'"records":[', b'"SECRET":1,"records":[')):
                target.write_bytes(data)
                self.assertEqual(store.load(), {"status": "corrupt", "history": None})
                with self.assertRaises(dh.HistoryError):
                    store.record(report(110), received_at=110)
                self.assertEqual(target.read_bytes(), data)
            target.write_bytes(original)
            target.chmod(0o644)
            self.assertEqual(store.load()["status"], "unavailable")
            target.chmod(0o600)
            real_regular = store._regular
            def replace_on_read(fd):
                info = real_regular(fd)
                if info.st_ino == target.stat().st_ino:
                    target.rename(Path(tmp) / "old")
                    target.write_bytes(original)
                    target.chmod(0o600)
                return info
            with patch.object(store, "_regular", side_effect=replace_on_read):
                self.assertEqual(store.load()["status"], "unavailable", "detached read cannot succeed")
            (root / ".history.lock").unlink()
            self.assertEqual(store.load()["status"], "unavailable")

    def test_watchdog_uses_observed_clock_and_never_equates_heartbeat_with_health(self):
        dh = module()
        self.assertTrue(hasattr(dh.HistoryStore, "assess"), "watchdog assessment missing")
        with tempfile.TemporaryDirectory() as tmp:
            store = dh.HistoryStore(Path(tmp) / "history", identity=dh.report_identity(report()))
            def assess(now, heartbeat):
                return store.assess(now=now, heartbeat_at=heartbeat, max_check_age=30, max_heartbeat_age=20)
            missing = assess(100, 100)
            self.assertEqual(missing["history_status"], "missing")
            self.assertTrue(missing["monitoring_gap"])
            self.assertFalse(missing["healthy"])
            store.record(report(100, actions=("no-op",)), received_at=101)
            good = assess(110, 110)
            self.assertTrue(good["healthy"])
            self.assertEqual(good["drift_status"], "clean_within_coverage")
            self.assertEqual(good["wrapper_exit_code"], 0)
            self.assertEqual(assess(110, None)["heartbeat_status"], "missing")
            for now, heartbeat, reason in ((130, 130, "stale_check"), (121, 100, "stale_heartbeat"),
                                            (99, 99, "clock_invalid"), (110, 111, "clock_invalid")):
                result = assess(now, heartbeat)
                self.assertFalse(result["healthy"])
                self.assertTrue(result["monitoring_gap"])
                self.assertIn(reason, result["reasons"])
            # A late re-delivery must not refresh report observation or receipt.
            store.record(report(100, actions=("no-op",)), received_at=140)
            self.assertEqual(assess(140, 140)["latest_observed_at"], 100)
            self.assertEqual(assess(140, 140)["latest_received_at"], 101)
            store.record(report(145, actions=("no-op",), status="error"), received_at=145)
            failure = assess(146, 100)
            self.assertIn("detector_failed", failure["reasons"])
            self.assertIn("stale_heartbeat", failure["reasons"])
            self.assertEqual(failure["wrapper_exit_code"], 1)
            self.assertEqual(failure["drift_status"], "unknown")
            empty = report(150, actions=("no-op",))
            empty["coverage"]["checked"] = []
            store.record(empty, received_at=150)
            self.assertFalse(assess(151, 151)["healthy"])
            self.assertIn("incomplete_coverage", assess(151, 151)["reasons"])
            exception_report = report(160)
            exception_report["exceptions"] = [{"resource_ref": "resource", "rule_ref": "rule", "owner_ref": "owner",
                "justification_ref": "approval-ticket", "baseline_ref": "baseline", "expires_at": 165,
                "status": "requires_owner_review"}]
            exception_report["classes"].append("partial")
            store.record(exception_report, received_at=160)
            expired = assess(170, 170)
            self.assertEqual(expired["drift_status"], "findings")
            self.assertEqual(expired["active_fingerprints"], [exception_report["findings"][0]["fingerprint"]])
            self.assertEqual(expired["expired_exceptions"], 1)
            self.assertFalse(expired["healthy"])
            json.dumps(expired, allow_nan=False)

    def test_staged_or_published_file_mutation_is_not_success(self):
        dh = module()
        for phase in ("staged", "published"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "history"
                store = dh.HistoryStore(root, identity=dh.report_identity(report()))
                store.record(report(), received_at=100)
                real_fsync, real_replace = os.fsync, os.replace
                def fsync(fd):
                    result = real_fsync(fd)
                    if phase == "staged" and stat.S_ISREG(os.fstat(fd).st_mode):
                        temporary = next(p for p in root.iterdir() if p.name.startswith(".history-"))
                        temporary.unlink()
                        temporary.symlink_to(Path(tmp) / "outside")
                    return result
                def replace(*args, **kwargs):
                    result = real_replace(*args, **kwargs)
                    if phase == "published":
                        target = root / (digest(store.identity) + ".json")
                        target.write_text("{}")
                    return result
                with patch.object(dh.os, "fsync", side_effect=fsync), patch.object(dh.os, "replace", side_effect=replace):
                    with self.assertRaises(dh.HistoryError):
                        store.record(report(110), received_at=110)
                self.assertFalse((Path(tmp) / "outside").exists())
                self.assertFalse(any(p.name.startswith(".history-") for p in root.iterdir()))

    def test_busy_store_does_not_block_the_watchdog(self):
        dh = module()
        import fcntl
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            store = dh.HistoryStore(root, identity=dh.report_identity(report()))
            store.record(report(), received_at=100)
            results = []
            with (root / ".history.lock").open("r+b") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                worker = threading.Thread(target=lambda: results.append(store.assess(
                    now=200, heartbeat_at=100, max_check_age=30, max_heartbeat_age=30)))
                worker.start()
                worker.join(timeout=0.5)
                blocked = worker.is_alive()
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            worker.join(timeout=2)
            self.assertFalse(blocked, "watchdog blocked behind a failing detector/store writer")
            self.assertEqual(results[0]["history_status"], "unavailable")
            self.assertTrue(results[0]["monitoring_gap"])
            self.assertFalse(results[0]["healthy"])

    def test_corrupt_timeline_or_missing_incident_ledger_is_not_empty_success(self):
        dh = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            store = dh.HistoryStore(root, identity=dh.report_identity(report()))
            store.record(report(), received_at=100)
            store.record(report(110, actions=("no-op",), status="error"), received_at=110)
            target = root / (digest(store.identity) + ".json")
            saved = json.loads(target.read_bytes())
            for mutation in ("reverse", "future_observation", "lost_incident", "future_incident"):
                value = copy.deepcopy(saved)
                if mutation == "reverse":
                    value["records"].reverse()
                elif mutation == "future_observation":
                    value["records"][0]["received_at"] = 99
                elif mutation == "lost_incident":
                    value["incidents"] = []
                else:
                    value["incidents"][0].update(last_seen=120, report=report(120))
                target.write_text(json.dumps(value))
                with self.subTest(mutation=mutation):
                    self.assertEqual(store.load()["status"], "corrupt")
                    self.assertFalse(store.assess(now=120, heartbeat_at=120, max_check_age=60, max_heartbeat_age=60)["healthy"])

    def test_root_identity_and_limits_cannot_escape_or_disable_private_bounds(self):
        dh = module()
        for root in ("/", "//", "relative", "/tmp/../outside"):
            with self.subTest(root=root), self.assertRaises(dh.HistoryError):
                dh.HistoryStore(root, identity=dh.report_identity(report()))
        with tempfile.TemporaryDirectory() as tmp:
            identity = dh.report_identity(report())
            for key, wrong in (("deployment", "../other"), ("backend_digest", "other"), ("lineage", "/secret")):
                with self.subTest(key=key), self.assertRaises(dh.HistoryError):
                    dh.HistoryStore(Path(tmp) / "history", identity={**identity, key: wrong})
            for option in ({"max_records": 0}, {"retention_seconds": True}, {"max_total_bytes": -1}, {"max_incidents": 0}):
                with self.subTest(option=option), self.assertRaises(dh.HistoryError):
                    dh.HistoryStore(Path(tmp) / "history", identity=identity, **option)
            store = dh.HistoryStore(Path(tmp) / "history", identity=identity)
            identity["deployment"] = "other"
            store.identity["deployment"] = "other"
            self.assertEqual(store.identity["deployment"], "fixture")

    def test_actual_detector_optional_report_roundtrips_without_suppressing_expired_exception(self):
        # Reuse the repository's existing offline runner, not an invented report format.
        import runpy
        from src.python.drift_config import DriftConfig
        from src.python.drift_detector import DriftDetector, Preflight, runner_identity_digest
        fixtures = runpy.run_path(str(Path(__file__).with_name("drift_detector.test.py")))
        baseline = fixtures["BASELINE"]
        runner = fixtures["FixtureRunner"]({"format_version": "1.2", "resource_drift": [
            {"address": "terraform_data.vm", "change": {"actions": ["update"], "before": {"secret": "SECRET"}}}]}, changes=True)
        backend = runner_identity_digest(runner)
        config = DriftConfig.from_dict({"enabled": True, "scopes": ["workstation_infrastructure"],
            "baseline_ref": "baseline", "exceptions": [{"resource_ref": "vm", "rule_ref": "stopped",
            "owner_ref": "owner", "justification_ref": "approval-ticket", "baseline_ref": "baseline", "expires_at": 110}]}, now=100)
        detector = DriftDetector(config=config, runner_factory=lambda **kw: runner,
            preflight=lambda **kw: Preflight("ready", backend, digest(baseline.to_dict()), "fixture", 1,
                lifecycle_intent="stopped", ignored=("approved-rule",), unsupported=("unmodeled-property",)), clock=lambda: 120)
        value = detector.check(deployment="fixture", scope="workstation_infrastructure", baseline=baseline,
                               backend_digest=backend, expected_lineage="fixture")
        dh = module()
        with tempfile.TemporaryDirectory() as tmp:
            store = dh.HistoryStore(Path(tmp) / "history", identity=dh.report_identity(value))
            self.assertEqual(len(store.record(value, received_at=120)["opened"]), 1)
            self.assertEqual(store.load()["history"]["records"][0]["report"], value)
            assessment = store.assess(now=121, heartbeat_at=121, max_check_age=60, max_heartbeat_age=60)
            self.assertEqual(assessment["expired_exceptions"], 1)
            self.assertEqual(assessment["drift_status"], "findings")
            self.assertNotIn("SECRET", json.dumps(store.load()))


if __name__ == "__main__":
    unittest.main()
