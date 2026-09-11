"""Synthetic, value-free reporting tests."""
import unittest
import json

BASELINE = dict(schema_version=1, source_revision="a" * 40, input_digest="b" * 64,
                lock_digest="c" * 64, source_digest="d" * 64, inputs_ref="protected-inputs",
                source_ref="protected-source", applied_at=10)


class ReportTests(unittest.TestCase):
    def test_baseline_is_versioned_reconstructible_and_pinned(self):
        from src.python.drift_report import Baseline
        baseline = Baseline.from_dict(BASELINE)
        self.assertEqual(baseline.to_dict(), BASELINE)
        for change in ({"source_revision": "HEAD"}, {"inputs_ref": None},
                       {"schema_version": 2}, {"input_digest": "bad"},
                       {"token": "SECRET"}, {"applied_at": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Baseline.from_dict({**BASELINE, **change})
        self.assertEqual(Baseline.from_dict(None), None)

    def test_classifies_external_and_desired_changes_without_leaking_values(self):
        from src.python.drift_report import classify_plan
        resource = {"address": "terraform_data.example", "change": {
            "actions": ["update"], "before": {"password": "SECRET"},
            "after": {"password": "NEW-SECRET"}, "after_unknown": {}}}
        result = classify_plan({"format_version": "1.2", "resource_drift": [resource],
                                "resource_changes": [resource], "output_changes": {}}, exit_code=2)
        self.assertEqual(set(result["classes"]), {"external_drift", "desired_change"})
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(result["coverage"]["checked"], ["terraform_data.example"])
        self.assertEqual(result["findings"][0]["actions"], ["update"])
        self.assertEqual(classify_plan({"format_version": "1.2"}, exit_code=0)["classes"],
                         ["clean_within_coverage"])
        self.assertEqual(classify_plan({}, exit_code=1)["classes"], ["error"])

    def test_unknown_deferred_and_unsupported_never_claim_clean(self):
        from src.python.drift_report import classify_plan
        variants = [{"format_version": "9.0"}, {"format_version": "1.2", "future_SECRET": 1},
                    {"format_version": "1.2", "deferred_changes": [{}]},
                    {"format_version": "1.2", "resource_changes": "SECRET"},
                    {"format_version": "1.2", "complete": False},
                    {"format_version": "1.2", "resource_changes": [{"address": 'x["SECRET"]',
                      "change": {"actions": ["no-op"], "after_unknown": {"SECRET": True}}}]}]
        for plan in variants:
            with self.subTest(plan=plan):
                result = classify_plan(plan, exit_code=0)
                self.assertIn("partial", result["classes"])
                self.assertNotIn("clean_within_coverage", result["classes"])
                self.assertNotIn("SECRET", json.dumps(result))
        result = classify_plan({"format_version": "1.2"}, exit_code=2)
        self.assertIn("partial", result["classes"])
        output = classify_plan({"format_version": "1.2", "output_changes": {
            "SECRET": {"actions": ["update"], "after": "SECRET"}}}, exit_code=2)
        self.assertEqual(output["classes"], ["desired_change"])
        self.assertNotIn("SECRET", json.dumps(output))

    def test_completion_flags_require_booleans_and_deferred_changes_require_list(self):
        from src.python.drift_report import classify_plan, wrapper_exit_code
        for field in ("complete", "errored", "applyable"):
            for value in (0, 1, None, "SECRET", [], {}):
                with self.subTest(field=field, value=value):
                    result = classify_plan({"format_version": "1.2", field: value}, exit_code=0)
                    self.assertIn("partial", result["classes"])
                    self.assertEqual(wrapper_exit_code(result), 3)
                    self.assertTrue(result["coverage"]["errors"])
                    self.assertNotIn("SECRET", json.dumps(result))
        for value in (None, False, 0, {}, ""):
            with self.subTest(deferred_changes=value):
                result = classify_plan({"format_version": "1.2", "deferred_changes": value}, exit_code=0)
                self.assertIn("partial", result["classes"])
        for version in ("1.0", "1.1", "1.2"):
            result = classify_plan({"format_version": version, "complete": True,
                "errored": False, "applyable": False, "deferred_changes": []}, exit_code=0)
            self.assertEqual(result["classes"], ["clean_within_coverage"])

    def test_output_changes_reject_unknown_fields_and_malformed_actions(self):
        from src.python.drift_report import classify_plan, wrapper_exit_code
        for change in ({"actions": ["no-op"], "future_SECRET": True},
                       {"actions": ("no-op",)}, {"actions": "no-op"},
                       {"actions": None}, {"actions": [["no-op"]]}, [], None):
            with self.subTest(change=change):
                result = classify_plan({"format_version": "1.2",
                    "output_changes": {"SECRET": change}}, exit_code=0)
                self.assertIn("partial", result["classes"])
                self.assertEqual(wrapper_exit_code(result), 3)
                self.assertNotIn("SECRET", json.dumps(result))
        for version in ("1.0", "1.1", "1.2"):
            result = classify_plan({"format_version": version, "output_changes": {"SECRET": {
                "actions": ["no-op"], "before": "SECRET", "after": "SECRET",
                "after_unknown": False, "before_sensitive": True, "after_sensitive": True}}}, exit_code=0)
            self.assertEqual(result["classes"], ["clean_within_coverage"])
            self.assertNotIn("SECRET", json.dumps(result))

    def test_checks_validate_nested_structures_without_disclosing_values(self):
        from copy import deepcopy
        from src.python.drift_report import classify_plan, wrapper_exit_code
        base = {"address": {"kind": "check", "name": "SECRET", "to_display": "check.SECRET"},
                "status": "pass", "instances": [{"address": {"to_display": "check.SECRET"}, "status": "pass"}]}
        mutations = [([], "future_SECRET", True), (["address"], "future_SECRET", True),
                     (["instances", 0], "future_SECRET", True),
                     (["instances", 0, "address"], "future_SECRET", True),
                     ([], "instances", {}), ([], "instances", [None]),
                     ([], "instances", [{"status": "pass"}]),
                     ([], "instances", [{"address": {"to_display": "SECRET"}}]),
                     ([], "address", None), (["address"], "kind", "future_SECRET"),
                     (["address"], "name", []), (["instances", 0], "address", []),
                     (["instances", 0, "address"], "to_display", 1),
                     (["instances", 0, "address"], "instance_key", {}),
                     (["instances", 0], "failure_messages", "SECRET"),
                     (["instances", 0], "failure_messages", [0])]
        for path, key, value in mutations:
            with self.subTest(path=path, key=key, value=value):
                check = deepcopy(base)
                target = check
                for part in path:
                    target = target[part]
                target[key] = value
                result = classify_plan({"format_version": "1.2", "checks": [check]}, exit_code=0)
                self.assertIn("partial", result["classes"])
                self.assertEqual(wrapper_exit_code(result), 3)
                self.assertNotIn("SECRET", json.dumps(result))
        for version in ("1.0", "1.1", "1.2"):
            result = classify_plan({"format_version": version, "checks": [base]}, exit_code=0)
            self.assertEqual(result["classes"], ["clean_within_coverage"])
            self.assertNotIn("SECRET", json.dumps(result))

    def test_check_instance_status_cannot_be_hidden_by_aggregate_pass(self):
        from src.python.drift_report import classify_plan
        for aggregate, status in (("pass", "fail"), ("pass", "error"), ("pass", "unknown"),
                                  ("fail", "pass"), ("unknown", "fail"), ("error", "fail")):
            with self.subTest(aggregate=aggregate, instance=status):
                check = {"address": {"kind": "check", "name": "SECRET", "to_display": "check.SECRET"},
                    "status": aggregate, "instances": [{"address": {"to_display": "check.SECRET"},
                    "status": status}]}
                result = classify_plan({"format_version": "1.2", "checks": [check]}, exit_code=0)
                self.assertIn("partial", result["classes"])
                self.assertNotIn("clean_within_coverage", result["classes"])
                if "fail" in (aggregate, status):
                    self.assertIn("policy_noncompliance", result["classes"])
                self.assertNotIn("SECRET", json.dumps(result))
        check = {"address": {"kind": "check", "name": "SECRET", "to_display": "check.SECRET"},
                 "status": "pass", "instances": [{"address": {"to_display": "check.SECRET"},
                 "status": "pass", "failure_messages": ["SECRET"]}]}
        result = classify_plan({"format_version": "1.2", "checks": [check]}, exit_code=0)
        with self.subTest(contradiction="pass_with_failure_messages"):
            self.assertIn("partial", result["classes"])
            self.assertNotIn("SECRET", json.dumps(result))
        del check["instances"]
        with self.subTest(contradiction="pass_without_instances"):
            self.assertIn("partial", classify_plan({"format_version": "1.2", "checks": [check]}, exit_code=0)["classes"])
        check["status"] = "fail"
        check["instances"] = [{"address": {"to_display": "check.SECRET"}, "status": "fail",
                               "failure_messages": ["SECRET"]}]
        self.assertEqual(classify_plan({"format_version": "1.2", "checks": [check]}, exit_code=0)["classes"],
                         ["policy_noncompliance"])

    def test_report_freshness_dedup_and_resolution_require_successful_coverage(self):
        from src.python.drift_report import Baseline, make_report, resolved_findings
        baseline = Baseline.from_dict(BASELINE)
        args = dict(deployment="fixture", scope="workstation_infrastructure", baseline=baseline,
                    backend_digest="e" * 64, lineage="lineage", serial=1, observed_at=100,
                    expires_at=160, now=110)
        resource = {"address": "terraform_data.example", "change": {"actions": ["update"]}}
        plan = {"format_version": "1.2", "resource_drift": [resource]}
        first = make_report(plan=plan, exit_code=2, **args)
        later = make_report(plan=plan, exit_code=2, **{**args, "observed_at": 105})
        self.assertEqual(first["findings"][0]["fingerprint"], later["findings"][0]["fingerprint"])
        self.assertEqual(first["schema_version"], 1)
        stale = make_report(plan=plan, exit_code=2, **{**args, "now": 160})
        self.assertIn("stale", stale["classes"])
        clean = make_report(plan={"format_version": "1.2", "resource_changes": [
            {"address": "terraform_data.example", "change": {"actions": ["no-op"]}}]}, exit_code=0,
            **{**args, "observed_at": 105})
        self.assertEqual(resolved_findings(first, clean, now=110), [first["findings"][0]["fingerprint"]])
        for replacement in (stale, make_report(plan={}, exit_code=1, **args),
                            make_report(plan={"format_version": "1.2"}, exit_code=0, **args)):
            self.assertEqual(resolved_findings(first, replacement, now=110), [])
        missing = make_report(plan={}, exit_code=0, **{**args, "baseline": None})
        self.assertIn("partial", missing["classes"])

    def test_policy_checks_and_unknown_nested_plan_fields_are_not_ignored(self):
        from src.python.drift_report import classify_plan, wrapper_exit_code
        base = {"format_version": "1.2", "checks": [{"address": {"to_display": "SECRET"}, "status": "fail"}]}
        report = classify_plan(base, exit_code=0)
        self.assertIn("policy_noncompliance", report["classes"])
        self.assertNotIn("SECRET", json.dumps(report))
        resource = {"address": "terraform_data.x", "future_SECRET": {}, "change": {"actions": ["no-op"]}}
        self.assertIn("partial", classify_plan({"format_version": "1.2", "resource_changes": [resource]}, exit_code=0)["classes"])
        resource.pop("future_SECRET")
        resource["change"]["future_SECRET"] = True
        self.assertIn("partial", classify_plan({"format_version": "1.2", "resource_changes": [resource]}, exit_code=0)["classes"])
        for classes, code in ((["clean_within_coverage"], 0), (["desired_change"], 2),
                              (["external_drift", "partial"], 3), (["locked"], 3),
                              (["not_run"], 3), (["error"], 1)):
            self.assertEqual(wrapper_exit_code({"classes": classes}), code)


if __name__ == "__main__":
    unittest.main()
