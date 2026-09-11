"""Offline drift configuration contracts."""
import unittest


class ConfigTests(unittest.TestCase):
    def test_defaults_do_not_enable_monitoring_or_correction(self):
        from src.python.drift_config import DriftConfig
        config = DriftConfig.from_dict(None)
        self.assertFalse(config.enabled)
        self.assertEqual(config.scopes, ())
        self.assertIsNone(config.schedule)
        self.assertEqual(config.correction, "report_only")
        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.executor, "on_demand")

    def test_strict_opt_in_and_unsupported_automation(self):
        from src.python.drift_config import DriftConfig
        valid = {"enabled": True, "scopes": ["workstation_infrastructure"],
                 "correction": "approval_required", "identity_ref": "workload-reader"}
        self.assertTrue(DriftConfig.from_dict(valid).enabled)
        for change in ({"enabled": "false"}, {"schema_version": True},
                       {"token": "SECRET"}, {"scopes": ["everything"]},
                       {"scopes": ["runtime", "runtime"]},
                       {"correction": "preauthorized_allowlist"},
                       {"executor": "cloud_native"}, {"identity_ref": "https://user:secret@host"},
                       {"schedule": "* * * * *"}, {"reporting": {"token": "SECRET"}}):
            with self.subTest(change=change), self.assertRaises(ValueError) as raised:
                DriftConfig.from_dict({**valid, **change})
            self.assertNotIn("SECRET", str(raised.exception))
        with self.assertRaises(ValueError):
            DriftConfig.from_dict({"scopes": ["runtime"]})

    def test_bounded_settings_expiring_exceptions_and_schedules(self):
        from src.python.drift_config import DriftConfig
        data = {"enabled": True, "scopes": ["workstation_infrastructure"],
                "executor": "github_actions", "schedule": "15 */6 * * *",
                "baseline_ref": "last-applied", "reporting_ref": "private-reports",
                "retention_days": 7, "command_timeout": 120, "lock_timeout": 15,
                "exceptions": [{"resource_ref": "vm", "rule_ref": "stopped",
                                "owner_ref": "team", "justification_ref": "review-1",
                                "baseline_ref": "last-applied", "expires_at": 200}]}
        config = DriftConfig.from_dict(data, now=100)
        self.assertEqual(config.command_timeout, 120)
        self.assertEqual(config.exceptions[0].expires_at, 200)
        for change in ({"schedule": "bad"}, {"schedule": "99 * * * *"},
                       {"schedule": "* * * * *;curl x"}, {"command_timeout": True},
                       {"retention_days": 0}, {"lock_timeout": 10000}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                DriftConfig.from_dict({**data, **change}, now=100)
        with self.assertRaises(ValueError):
            DriftConfig.from_dict(data, now=200)
        with self.assertRaises(ValueError):
            DriftConfig.from_json('{"enabled":false,"enabled":true}')


if __name__ == "__main__":
    unittest.main()
