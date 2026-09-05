#!/usr/bin/env python3

import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from src.python.config import c
from src.python.deployer import Deployer

# Base parameter set used by the helper below.
_BASE_PARAMS = {
    "debug": False,
    "prefix": "isa",
    "from_image": False,
    "deployment_name": "test-1",
    "existing": "ask",
    "in_china": "no",
    "region": "us-east-1",
    "isaac": True,
    "isaac_workstation_instance_type": "g5.2xlarge",
    "isaac_image": "nvcr.io/nvidia/isaac-sim:2022.2.0",
    "vnc_password": "__vnc_password__",
    "ssh_port": 22,
    "upload": True,
    "aws_access_key_id": "__aws_access_key_id__",
    "aws_secret_access_key": "__aws_secret_access_key__",
    "ingress_cidrs": "auto",
}


def _make_deployer(state_dir, extra=None):
    """
    Build a Deployer with a minimal valid param set, optionally overridden.
    Callers MUST pass an isolated state_dir so the Deployer's __del__
    hook (save_meta) does not mutate checked-in fixtures.
    """
    config = c.copy()
    config["state_dir"] = state_dir

    params = dict(_BASE_PARAMS)
    if extra:
        params.update(extra)

    return Deployer(params=params, config=config)


class Test_Deployer(unittest.TestCase):
    """
    Reads from the checked-in test-1 fixture but writes outputs into an
    isolated temp dir so the fixture files stay untouched. We copy the
    fixture into the temp dir before running.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fixture_src = Path(c["tests_dir"]) / "res" / "state" / "test-1"
        fixture_dst = Path(self.tmp) / "test-1"
        shutil.copytree(fixture_src, fixture_dst)
        self.deployer = _make_deployer(state_dir=self.tmp)

    def tearDown(self):
        self.deployer = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_output_deployment_info(self):
        self.deployer.output_deployment_info(print_text=False)

        file_generated = Path(self.tmp) / "test-1" / "info.txt"
        file_expected = Path(self.tmp) / "test-1" / "info.expected.txt"

        self.assertEqual(file_generated.read_text(), file_expected.read_text())


class Test_RecreateCommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_includes_string_options(self):
        deployer = _make_deployer(state_dir=self.tmp)
        cmd = deployer.recreate_command_line(separator=" ")
        self.assertIn("--prefix isa", cmd)
        self.assertIn("--deployment-name test-1", cmd)
        self.assertIn("--region us-east-1", cmd)

    def test_quotes_strings_with_spaces(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"region": "us east 1"})
        cmd = deployer.recreate_command_line(separator=" ")
        self.assertIn("'us east 1'", cmd)

    def test_boolean_flags(self):
        deployer = _make_deployer(
            state_dir=self.tmp, extra={"upload": True, "from_image": False}
        )
        cmd = deployer.recreate_command_line(separator=" ")
        self.assertIn("--upload", cmd)
        self.assertNotIn("--no-upload", cmd)
        # from-image uses --not- prefix when False
        self.assertIn("--not-from-image", cmd)


class Test_WriteTfvarsFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_strings_lists_and_bools(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = f"{self.tmp}/.tfvars"
        deployer._write_tfvars_file(
            path=path,
            tfvars={
                "prefix": "isa",
                "isaac_enabled": True,
                "from_image": False,
                "ingress_cidrs": ["10.0.0.0/8", "1.2.3.4/32"],
                "ssh_port": 22,
            },
        )
        content = Path(path).read_text()

        self.assertIn('prefix = "isa"', content)
        # booleans are stringified then quoted; terraform parses them into bool vars
        self.assertIn('isaac_enabled = "true"', content)
        self.assertIn('from_image = "false"', content)
        self.assertIn('ingress_cidrs = ["10.0.0.0/8", "1.2.3.4/32"]', content)
        self.assertIn("ssh_port = 22", content)

    def test_escapes_quotes_in_strings(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = f"{self.tmp}/.tfvars"
        deployer._write_tfvars_file(
            path=path,
            tfvars={"password": 'has "quotes"'},
        )
        content = Path(path).read_text()
        self.assertIn(r'password = "has \"quotes\""', content)

    def test_normalizes_hyphen_keys_to_underscores(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = f"{self.tmp}/.tfvars"
        deployer._write_tfvars_file(
            path=path,
            tfvars={"resource-group": "rg-1"},
        )
        content = Path(path).read_text()
        self.assertIn('resource_group = "rg-1"', content)


class Test_InChinaConversion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_yes_becomes_true(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"in_china": "yes"})
        self.assertTrue(deployer.params["in_china"])

    def test_no_becomes_false(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"in_china": "no"})
        self.assertFalse(deployer.params["in_china"])

    def test_auto_becomes_false(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"in_china": "auto"})
        self.assertFalse(deployer.params["in_china"])


class Test_ResolveDemos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_demos_is_noop(self):
        deployer = _make_deployer(
            state_dir=self.tmp, extra={"demos": "no", "isaacsim": "no", "isaaclab": "no"}
        )
        self.assertEqual(deployer.params["demos"], "no")
        # apps left off must stay off
        self.assertEqual(deployer.params["isaacsim"], "no")
        self.assertEqual(deployer.params["isaaclab"], "no")

    def test_unknown_demo_exits(self):
        with self.assertRaises(SystemExit):
            _make_deployer(state_dir=self.tmp, extra={"demos": "does-not-exist"})

    def test_autoenables_required_apps(self):
        deployer = _make_deployer(
            state_dir=self.tmp,
            extra={
                "demos": "quadruped-locomotion",
                "isaacsim": "no",
                "isaaclab": "no",
            },
        )
        self.assertEqual(
            deployer.params["isaacsim"], c["default_isaacsim_git_checkpoint"]
        )
        self.assertEqual(
            deployer.params["isaaclab"], c["default_isaaclab_git_checkpoint"]
        )
        self.assertEqual(deployer.params["demos"], "quadruped-locomotion")

    def test_keeps_explicit_app_ref(self):
        deployer = _make_deployer(
            state_dir=self.tmp,
            extra={
                "demos": "quadruped-locomotion",
                "isaacsim": "v1.2.3",
                "isaaclab": "no",
            },
        )
        # an explicitly chosen ref is untouched; only the disabled app is enabled
        self.assertEqual(deployer.params["isaacsim"], "v1.2.3")
        self.assertEqual(
            deployer.params["isaaclab"], c["default_isaaclab_git_checkpoint"]
        )


class Test_SecurityProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_profile_is_simple(self):
        deployer = _make_deployer(state_dir=self.tmp)
        self.assertEqual(deployer.params["security_profile"], "simple")
        self.assertEqual(deployer.params["profile"], "simple")

    def test_simple_flag_sets_simple_profile(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"simple": True, "profile": "enterprise"})
        self.assertEqual(deployer.params["security_profile"], "simple")

    def test_team_and_enterprise_profiles(self):
        deployer_team = _make_deployer(state_dir=self.tmp, extra={"profile": "team"})
        self.assertEqual(deployer_team.params["security_profile"], "team")

        deployer_ent = _make_deployer(state_dir=self.tmp, extra={"profile": "enterprise"})
        self.assertEqual(deployer_ent.params["security_profile"], "enterprise")

    def test_unknown_profile_exits(self):
        with self.assertRaises(SystemExit):
            _make_deployer(state_dir=self.tmp, extra={"profile": "invalid-profile"})

    def test_simple_mode_tfvars_contains_security_profile(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"profile": "simple"})
        tfvars = {}
        deployer.create_tfvars(tfvars=tfvars)
        self.assertEqual(tfvars.get("security_profile"), "simple")
        self.assertFalse(tfvars.get("enable_cmek"))
        self.assertFalse(tfvars.get("enable_iap_only"))

    def test_custom_yaml_profile_loading(self):
        custom_yaml = os.path.join(self.tmp, "my-custom-profile.yaml")
        with open(custom_yaml, "w") as f:
            f.write("""
schema_version: "v1alpha1"
profile_name: "my-custom-profile"
security:
  tier: "custom"
  network:
    iap_only: true
    cloud_nat: true
  storage:
    state_backend: "gcs"
    state_bucket: "gs://custom-state-bucket"
  cryptography:
    encryption_type: "kms_cmek"
  compute:
    os_login: true
""")
        deployer = _make_deployer(state_dir=self.tmp, extra={"profile": custom_yaml})
        self.assertEqual(deployer.params["security_profile"], "custom")
        self.assertTrue(deployer.params["enable_iap_only"])
        self.assertTrue(deployer.params["enable_cmek"])
        self.assertTrue(deployer.params["enable_oslogin"])
        self.assertEqual(deployer.params["state_bucket"], "gs://custom-state-bucket")

        tfvars = {}
        deployer.create_tfvars(tfvars=tfvars)
        self.assertTrue(tfvars["enable_iap_only"])
        self.assertTrue(tfvars["enable_cmek"])
        self.assertTrue(tfvars["enable_oslogin"])
        self.assertEqual(tfvars["state_bucket"], "gs://custom-state-bucket")

    def test_discovered_profile_name_resolution(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"profile": "team-studio"})
        self.assertEqual(deployer.params["security_profile"], "team")
        self.assertEqual(deployer.params["state_bucket"], "auto")

    @mock.patch("src.python.deployer.shell_command")
    def test_dry_run_plan_and_validate(self, mock_shell):
        deployer = _make_deployer(state_dir=self.tmp, extra={"dry_run": True})
        deployer.plan_terraform(cwd="/fake/tf/gcp")
        self.assertEqual(mock_shell.call_count, 2)
        val_call, plan_call = mock_shell.call_args_list
        self.assertIn("terraform validate", val_call[0][0])
        self.assertIn("terraform plan", plan_call[0][0])

        mock_shell.reset_mock()
        deployer.validate_ansible()
        self.assertEqual(mock_shell.call_count, 1)
        self.assertIn("ansible-playbook --syntax-check", mock_shell.call_args_list[0][0][0])


if __name__ == "__main__":
    unittest.main()

