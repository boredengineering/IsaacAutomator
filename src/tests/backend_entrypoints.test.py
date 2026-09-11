#!/usr/bin/env python3
"""Wrapper boundary tests: synthetic state, no cloud/auth/process execution.

The shared DeployCommand public-IP help lookup is stubbed: moving that lookup
and generic git-ref callbacks is outside these provider wrappers' scope.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner

from src.python.config import c
from src.python.deployer import Deployer


ROOT = Path(__file__).resolve().parents[2]
CLOUDS = ("aws", "azure", "gcp", "alicloud")


class TestBackendEntrypoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.patch(mock.patch.dict(os.environ, {}, clear=True))
        self.patch(mock.patch.dict(c, state_dir=str(self.state),
                                  app_dir=str(self.root),
                                  terraform_dir=str(self.root / "terraform"),
                                  uploads_dir=str(self.root / "uploads")))
        self.patch(mock.patch("src.python.deploy_command.get_my_public_ip",
                              return_value="192.0.2.1"))
        self.process = self.patch(mock.patch("subprocess.Popen", side_effect=AssertionError("live process forbidden")))
        self.shell = self.patch(mock.patch("src.python.utils.shell_command",
                                         return_value=subprocess.CompletedProcess([], 0, stdout=b"fixture-project\n")))
        self.auth = {
            "aws": self.patch(mock.patch("src.python.aws.aws_validate_credentials")),
            "azure": self.patch(mock.patch("src.python.azure.azure_login")),
            "gcp": self.patch(mock.patch("src.python.utils.gcp_login")),
        }
        self.regions = self.patch(mock.patch("src.python.alicloud.alicloud_list_regions",
                                            return_value=["us-east-1"]))
        self.aws_config = self.patch(mock.patch("src.python.aws.aws_cli_set"))
        # Select the in-container CLI branch without inspecting or starting Docker.
        exists = os.path.exists
        self.patch(mock.patch("os.path.exists", side_effect=lambda path:
                              True if path == "/.dockerenv" else exists(path)))

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def args(self, cloud):
        args = ["--deployment-name", "fixture", "--profile", "simple",
                "--isaacsim", "no", "--isaaclab", "no", "--isaaclab-arena", "no",
                "--demos", "no", "--remote-desktop", "no", "--ingress-cidrs", "192.0.2.1/32",
                "--vnc-password", "synthetic", "--system-user-password", "synthetic",
                "--no-upload", "--existing", "modify", "--dry-run", "--no-debug",
                "--instance-type", c[f"{cloud}_default_isaac_workstation_instance_type"]]
        if cloud == "gcp":
            args += ["--zone", "us-central1-a", "--project", "fixture-project",
                     "--isaac-workstation-gpu-count", "auto"]
        else:
            args += ["--region", "us-east-1"]
        if cloud == "aws":
            args += ["--availability-zone", "us-east-1a"]
        if cloud == "alicloud":
            # Keys precede region so the old network callback is exercised.
            args = ["--aliyun-access-key", "synthetic", "--aliyun-secret-key", "synthetic"] + args
        return args

    def script(self, cloud, args):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [f"deploy-{cloud}", *args]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                runpy.run_path(str(ROOT / f"deploy-{cloud}"), run_name="__main__")
            except SystemExit as exc:
                return exc.code, output.getvalue()
        return 0, output.getvalue()

    def load(self, cloud):
        with contextlib.redirect_stdout(io.StringIO()):
            return runpy.run_path(str(ROOT / f"deploy-{cloud}"), run_name=f"test_deploy_{cloud}")

    def assert_no_cloud_calls(self):
        for auth in self.auth.values():
            auth.assert_not_called()
        self.regions.assert_not_called()
        self.shell.assert_not_called()
        self.aws_config.assert_not_called()
        self.process.assert_not_called()

    def test_gcp_project_discovery_waits_for_local_validation(self):
        module = self.load("gcp")
        self.assert_no_cloud_calls()
        args = self.args("gcp")
        index = args.index("--project")
        del args[index:index + 2]
        events = []
        original_init = Deployer.__init__

        def initialize(deployer, params, config):
            original_init(deployer, params, config)
            events.append("validated")

        def discover(*args, **kwargs):
            events.append("discovery")
            return subprocess.CompletedProcess([], 0, stdout=b"fixture-project\n")

        self.shell.side_effect = discover
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(Deployer, "__init__", initialize))
            stack.enter_context(mock.patch.object(Deployer, "ask_existing_behavior",
                                                  side_effect=lambda: events.append("restored")))
            for method in ("create_tfvars", "save_meta", "initialize_terraform", "plan_terraform", "validate_ansible"):
                stack.enter_context(mock.patch.object(Deployer, method))
            result = CliRunner().invoke(module["main"], args, input="\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(events, ["validated", "restored", "discovery"])

    def test_gcp_inspection_without_project_stays_offline(self):
        module = self.load("gcp")
        args = self.args("gcp")
        index = args.index("--project")
        del args[index:index + 2]
        with mock.patch.object(module["GCPDeployer"], "main"):
            result = CliRunner().invoke(module["main"], args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assert_no_cloud_calls()

    def test_import_and_help_do_not_authenticate_or_discover_cloud(self):
        for cloud in CLOUDS:
            with self.subTest(cloud=cloud):
                self.load(cloud)
                code, output = self.script(cloud, ["--help"])
                self.assertEqual(code, 0, output)
                self.assertIn("--state-backend", output)
                self.assertIn("--backend-config", output)
                self.assert_no_cloud_calls()
                self.assertFalse(self.state.exists())

    def test_help_describes_gcs_execution_without_claiming_other_backends(self):
        code, output = self.script('gcp', ['--help'])
        self.assertEqual(code, 0, output)
        self.assertIn('GCS execution', output)
        self.assertNotIn('remote execution is not yet implemented', output)
        self.assert_no_cloud_calls()

    def test_help_never_resolves_public_ip(self):
        with mock.patch('src.python.deploy_command.get_my_public_ip',
                        side_effect=AssertionError('Public IP discovery during help')):
            code, output = self.script('gcp', ['--help'])
        self.assertEqual(code, 0, output)
        self.assert_no_cloud_calls()

    def test_legacy_environment_refused_before_cloud_calls(self):
        for cloud in CLOUDS:
            with self.subTest(cloud=cloud), mock.patch.dict(os.environ, ISAAC_STATE_BUCKET="synthetic-bucket"):
                code, output = self.script(cloud, self.args(cloud))
                self.assertNotEqual(code, 0)
                self.assertIn("not implemented safely", output)
                self.assert_no_cloud_calls()
                self.assertFalse(self.state.exists())

    def test_backend_config_refused_without_gcp_project_discovery(self):
        path = self.root / "backend.json"
        path.write_text(json.dumps({"backend": "gcs", "namespace": "fixture", "destination": {
            "bucket": "fixture-state", "project": "fixture-project", "prefix": "isaacautomator/v2"}}))
        args = self.args("gcp")
        index = args.index("--project")
        del args[index:index + 2]
        code, output = self.script("gcp", args + ["--state-backend", "gcs", "--backend-config", str(path)])
        self.assertNotEqual(code, 0)
        self.assertIn("explicit --project", output)
        self.assert_no_cloud_calls()
        self.assertFalse(self.state.exists())

    def test_saved_remote_descriptor_preserved_before_cloud_calls(self):
        deployment = self.state / "fixture"
        deployment.mkdir(parents=True)
        descriptor = deployment / "backend.json"
        descriptor.write_text('{"schema_version":1,"backend":"gcs"}')
        marker = deployment / "recovery.txt"
        marker.write_text("synthetic recovery material")
        before = {p.name: p.read_bytes() for p in deployment.iterdir()}
        for cloud in CLOUDS:
            with self.subTest(cloud=cloud):
                code, output = self.script(cloud, self.args(cloud) + ["--state-backend", "local"])
                self.assertNotEqual(code, 0)
                self.assertIn("Protected backend/claim or migration record", output)
                self.assert_no_cloud_calls()
                self.assertEqual({p.name: p.read_bytes() for p in deployment.iterdir()}, before)

    def test_local_auth_or_region_lookup_follows_validation_and_precedes_run(self):
        original_init = Deployer.__init__
        for cloud in CLOUDS:
            with self.subTest(cloud=cloud), contextlib.ExitStack() as stack:
                events = []

                def initialize(deployer, params, config):
                    original_init(deployer, params, config)
                    events.append("validated")

                stack.enter_context(mock.patch.object(Deployer, "__init__", initialize))
                for method in ("ask_existing_behavior", "create_tfvars", "save_meta",
                               "plan_terraform", "validate_ansible"):
                    stack.enter_context(mock.patch.object(Deployer, method))
                stack.enter_context(mock.patch.object(Deployer, "initialize_terraform",
                                                      side_effect=lambda **kw: events.append("run")))
                if cloud == "alicloud":
                    self.regions.side_effect = lambda **kw: events.append("cloud") or ["us-east-1"]
                else:
                    self.auth[cloud].side_effect = lambda **kw: events.append("cloud")
                code, output = self.script(cloud, self.args(cloud))
                self.assertEqual(code, 0, output)
                self.assertNotIn("no costs were incurred", output)
                self.assertIn("not offline validation", output)
                self.assertEqual(events, ["validated", "cloud", "run"])
                self.shell.assert_not_called()  # Explicit GCP project skips discovery.
                self.process.assert_not_called()

    def test_azure_no_login_is_preserved(self):
        module = self.load("azure")
        with contextlib.ExitStack() as stack:
            for method in ("ask_existing_behavior", "create_tfvars", "initialize_terraform",
                           "plan_terraform", "validate_ansible"):
                stack.enter_context(mock.patch.object(Deployer, method))
            result = CliRunner().invoke(module["main"], self.args("azure") + ["--no-login"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assert_no_cloud_calls()

    def test_azure_dry_run_never_imports_resource_group(self):
        module = self.load("azure")
        with contextlib.ExitStack() as stack:
            for method in ("ask_existing_behavior", "create_tfvars", "initialize_terraform",
                           "plan_terraform", "validate_ansible"):
                stack.enter_context(mock.patch.object(Deployer, method))
            imported = stack.enter_context(mock.patch.object(module["AzureDeployer"], "import_resource_group"))
            result = CliRunner().invoke(module["main"], self.args("azure") + [
                "--no-login", "--resource-group",
                "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/fixture"])
        self.assertEqual(result.exit_code, 0, result.output)
        imported.assert_not_called()
        self.assertIn("not imported", result.output)
        self.assertNotIn("no costs were incurred", result.output)

    def test_azure_explicit_import_uses_isolated_deployer_operation(self):
        module = self.load("azure")
        deployer = module["AzureDeployer"].__new__(module["AzureDeployer"])
        resource_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/fixture"
        deployer.params = {"resource_group": resource_id, "debug": False, "deployment_name": "fixture"}
        deployer.config = {"state_dir": str(self.state)}
        with mock.patch.object(Deployer, "import_terraform_resource", create=True) as imported:
            deployer.import_resource_group("/approved/azure")
        imported.assert_called_once_with(
            cwd="/approved/azure", address="module.common.azurerm_resource_group.isa_rg", resource_id=resource_id)
        self.shell.assert_not_called()

    def test_invalid_local_alicloud_region_still_refused(self):
        args = self.args("alicloud")
        args[args.index("--region") + 1] = "not-a-region"
        code, output = self.script("alicloud", args)
        self.assertNotEqual(code, 0)
        self.assertIn("Invalid region", output)
        self.assertIn("--region", output)
        self.regions.assert_called_once_with(aliyun_access_key="synthetic", aliyun_secret_key="synthetic")
        self.process.assert_not_called()
        self.shell.assert_not_called()
        self.assertFalse((self.state / "fixture").exists())

    def test_remote_intent_refused_before_auth_or_discovery(self):
        for cloud in CLOUDS:
            backend = {"aws": "s3", "gcp": "gcs", "azure": "azurerm", "alicloud": "s3"}[cloud]
            for intent in (["--state-backend", backend], ["--state-bucket", "synthetic-bucket"]):
                with self.subTest(cloud=cloud, intent=intent):
                    code, output = self.script(cloud, self.args(cloud) + intent)
                    self.assertNotEqual(code, 0)
                    self.assertIn("not implemented safely", output)
                    self.assert_no_cloud_calls()
                    self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
