#!/usr/bin/env python3
"""Offline profile -> Terraform variables -> Ansible inventory contract tests."""

import json
import copy
from contextlib import ExitStack
import gc
import runpy
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml
import click

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.python.config import c, list_available_profiles, load_profile_spec
from src.python.deployer import Deployer


class TestArtifactRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.offline = ExitStack()
        self.addCleanup(self.offline.close)
        self.offline.enter_context(mock.patch("pathlib.Path.home", return_value=self.root))
        self.offline.enter_context(mock.patch.dict("os.environ", HOME=str(self.root)))
        self.offline.enter_context(mock.patch.dict(c, state_dir=str(self.root / "state")))
        # Preload the local parser before blocking its platform-detection subprocess.
        from ansible.inventory.manager import InventoryManager  # noqa: F401

        for target in (
            "socket.socket.connect", "socket.create_connection", "subprocess.Popen",
            "os.system", "src.python.utils.shell_command",
            "src.python.deployer.shell_command", "src.python.deployer.get_my_public_ip",
        ):
            self.offline.enter_context(mock.patch(
                target, side_effect=AssertionError(f"Offline test forbids external calls: {target}")
            ))
        self.image = "us-central1-docker.pkg.dev/example-project/robotics/gr00t@sha256:" + "a" * 64
        self.profile = {
            "profile_name": "registry-test",
            "cloud": "gcp",
            "security": {"tier": "custom"},
            "artifact_registry": {
                "enabled": True,
                "project": "example-project",
                "location": "us-central1",
                "repository": "robotics",
                "images": {"gr00t": self.image},
            },
        }

    def save_profile(self):
        path = self.root / "profile.yaml"
        path.write_text(yaml.safe_dump(self.profile))
        return str(path)

    def deployer(self, deployer_class=Deployer, **overrides):
        params = {
            "debug": False,
            "cloud": "gcp",
            "prefix": "isa",
            "deployment_name": "registry-test",
            "existing": "modify",
            "in_china": "no",
            "ssh_port": 22,
            "ingress_cidrs": "192.0.2.1/32",
            "vnc_password": "test-only",
            "system_user_password": "test-only",
            "isaacsim": "no",
            "isaaclab": "no",
            "isaaclab_arena": "no",
            "isaaclab_private_git": False,
            "demos": "no",
            "isaac_workstation_ip": "192.0.2.2",
            "profile": self.save_profile(),
        }
        if deployer_class is not Deployer:
            params.pop("cloud")  # Real CLI constructors do not receive this option.
        params.update(overrides)
        config = dict(c, state_dir=str(self.root / "state"))
        deployer = deployer_class(params, config)
        return deployer

    def cloud_deployer_class(self, cloud, name):
        # Import the class definition before patching its dependencies so a first
        # import cannot leave a mocked alias cached after this helper exits.
        from src.python import deploy_command

        def import_default(command, *args, **kwargs):
            if command == "gcloud config list --format 'value(core.project)'":
                return mock.Mock(stdout=b"example-project\n", stderr=b"", returncode=0)
            raise AssertionError(f"Offline import forbids shell command: {command}")

        # Click builds defaults/help at import time. Patch both the source and
        # the cached DeployCommand alias before runpy executes the decorators.
        with mock.patch("src.python.utils.get_my_public_ip", return_value="192.0.2.1"), \
                mock.patch.object(deploy_command, "get_my_public_ip", return_value="192.0.2.1"), \
                mock.patch("src.python.utils.shell_command", side_effect=import_default) as shell:
            cls = runpy.run_path(str(ROOT / f"deploy-{cloud}"), run_name="registry_test")[name]
            # The imported script retains this alias: disallow defaults/probes
            # during construction and workflow tests, not just real subprocesses.
            shell.side_effect = AssertionError("Offline test forbids deployment shell commands")
            return cls

    def test_failed_concrete_constructor_preserves_meta(self):
        original = self.deployer()
        original.save_meta()
        path = self.root / "state" / "registry-test" / "meta.json"
        before = path.read_bytes()
        cls = self.cloud_deployer_class("alicloud", "AlicloudDeployer")
        # Real post-super failure: base normalization succeeds, then Alicloud
        # needs the missing region to resolve in_china=auto.
        with self.assertRaisesRegex(KeyError, "region"):
            self.deployer(deployer_class=cls, profile="simple", in_china="auto")
        gc.collect()
        self.assertEqual(path.read_bytes(), before)

    def test_gcp_dry_run_explicitly_saves_resolved_workflow_params(self):
        cls = self.cloud_deployer_class("gcp", "GCPDeployer")
        deployer = self.deployer(
            deployer_class=cls, project="example-project", zone="us-central1-a",
            isaac_workstation_instance_type="g2-standard-4", spot=True,
            backup_bucket="auto", dry_run=True,
        )
        with mock.patch.dict(cls.main.__globals__, gcp_login=mock.Mock()), \
                mock.patch.object(deployer, "initialize_terraform"), \
                mock.patch.object(deployer, "plan_terraform"), \
                mock.patch.object(deployer, "validate_ansible"):
            deployer.main()
        # Hold the object alive: persistence must not depend on finalization.
        path = self.root / "state" / "registry-test" / "meta.json"
        saved = json.loads(path.read_text())["params"]
        self.assertEqual(saved["backup_bucket"], "example-project-registry-test-backups")
        self.assertTrue(saved["auto_restore"])
        self.assertEqual(saved["artifact_registry_images"], {"gr00t": self.image})

    def test_all_concrete_deployers_persist_only_at_explicit_boundaries(self):
        for cloud, name in (("gcp", "GCPDeployer"), ("aws", "AWSDeployer"),
                            ("azure", "AzureDeployer"), ("alicloud", "AlicloudDeployer")):
            with self.subTest(cloud=cloud):
                original = self.deployer()
                original.save_meta()
                path = self.root / "state" / "registry-test" / "meta.json"
                before = path.read_bytes()
                cls = self.cloud_deployer_class(cloud, name)
                deployer = self.deployer(deployer_class=cls, profile="simple",
                                         in_china="auto", region="cn-test")
                self.assertEqual(path.read_bytes(), before)
                # Every concrete main() starts at this explicit persistence boundary.
                deployer.ask_existing_behavior()
                saved = json.loads(path.read_text())["params"]
                self.assertEqual(saved["profile"], "simple")
                self.assertEqual(saved["in_china"], cloud == "alicloud")
                before = path.read_bytes()
                deployer.params["profile"] = "unsaved-edit"
                del deployer
                gc.collect()
                self.assertEqual(path.read_bytes(), before)

    def test_failed_metadata_read_preserves_existing_metadata(self):
        original = self.deployer()
        original.save_meta()
        path = self.root / "state" / "registry-test" / "meta.json"
        before = path.read_bytes()
        restored = self.deployer(profile="simple", existing="repair")
        with mock.patch.object(restored, "read_meta", side_effect=ValueError("invalid JSON")):
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                restored.ask_existing_behavior()
        restored.save_meta()
        del restored
        gc.collect()
        self.assertEqual(path.read_bytes(), before)

    def test_non_gcp_restore_rejects_saved_gcp_registry(self):
        original = self.deployer()
        original.save_meta()
        meta_path = self.root / "state" / "registry-test" / "meta.json"
        before = meta_path.read_bytes()
        for cloud, name in (("aws", "AWSDeployer"), ("azure", "AzureDeployer"),
                            ("alicloud", "AlicloudDeployer")):
            cls = self.cloud_deployer_class(cloud, name)
            for behavior in ("repair", "run_ansible"):
                with self.subTest(cloud=cloud, behavior=behavior):
                    deployer = self.deployer(deployer_class=cls, profile="simple",
                                             existing=behavior, cloud="gcp")
                    with mock.patch.dict(c, state_dir=deployer.config["state_dir"]):
                        with self.assertRaisesRegex(click.ClickException, "GCP"):
                            deployer.ask_existing_behavior()
                    deployer.save_meta()
                    self.assertEqual(meta_path.read_bytes(), before)
                    self.assertFalse(deployer.params["enable_artifact_registry"])

    def test_rejected_profile_preserves_existing_metadata(self):
        original = self.deployer()
        original.save_meta()
        meta_path = self.root / "state" / "registry-test" / "meta.json"
        before = meta_path.read_bytes()
        self.profile["artifact_registry"]["enabled"] = "false"
        with self.assertRaisesRegex(click.ClickException, "artifact_registry.enabled"):
            self.deployer()
        gc.collect()
        self.assertEqual(meta_path.read_bytes(), before)

    def test_invalid_registry_state_cannot_be_output_or_saved(self):
        for operation in ("create_tfvars", "create_ansible_inventory", "save_meta"):
            with self.subTest(operation=operation):
                deployer = self.deployer()
                deployer.save_meta()
                meta_path = self.root / "state" / "registry-test" / "meta.json"
                before = meta_path.read_bytes()
                deployer.params["artifact_registry_images"] = {"gr00t": "gr00t:latest"}
                with self.assertRaisesRegex(click.ClickException, "tag-free sha256"):
                    getattr(deployer, operation)()
                deployer.save_meta()
                del deployer
                gc.collect()
                self.assertEqual(meta_path.read_bytes(), before)

    def test_inventory_rejects_non_gcp_handoff_cloud(self):
        cls = self.cloud_deployer_class("gcp", "GCPDeployer")
        for source in ("params", "terraform"):
            with self.subTest(source=source):
                deployer = self.deployer(deployer_class=cls)
                deployer.save_meta()
                directory = self.root / "state" / "registry-test"
                before = (directory / "meta.json").read_bytes()
                inventory_path = directory / ".inventory"
                inventory_path.write_text("previous inventory")
                if source == "params":
                    deployer.params["cloud"] = "aws"
                else:
                    deployer.tf_outputs["cloud"] = "aws"
                # Fresh Terraform output is now checked against the deployer
                # cloud before the registry-specific handoff validation.
                message = "GCP" if source == "params" else "cloud output.*inconsistent"
                with self.assertRaisesRegex(click.ClickException, message):
                    deployer.create_ansible_inventory()
                deployer.save_meta()
                del deployer
                gc.collect()
                self.assertEqual(inventory_path.read_text(), "previous inventory")
                self.assertEqual((directory / "meta.json").read_bytes(), before)

    def test_invalid_saved_registry_values_are_rejected(self):
        cls = self.cloud_deployer_class("gcp", "GCPDeployer")
        invalid = (
            {"artifact_registry_images": {"gr00t": "gr00t:latest"}},
            {"artifact_registry_images": {"gr00t": self.image.replace("@", ":latest@")}},
            {"enable_artifact_registry": "false"},
            {"artifact_registry_repository": "../other"},
            {"cloud": "aws"},
        )
        for behavior in ("repair", "run_ansible"):
            for changes in invalid:
                with self.subTest(behavior=behavior, changes=changes):
                    original = self.deployer(deployer_class=cls)
                    original.save_meta()
                    path = self.root / "state" / "registry-test" / "meta.json"
                    saved = json.loads(path.read_text())
                    saved["params"].update(changes)
                    path.write_text(json.dumps(saved))
                    before = path.read_bytes()
                    restored = self.deployer(deployer_class=cls, profile="simple", existing=behavior)
                    with mock.patch.dict(c, state_dir=restored.config["state_dir"]):
                        with self.assertRaisesRegex(click.ClickException, "artifact_registry|GCP"):
                            restored.ask_existing_behavior()
                    restored.save_meta()
                    del restored
                    gc.collect()
                    self.assertEqual(path.read_bytes(), before)

    def test_saved_gcp_roundtrip_without_original_profile(self):
        gcp = self.cloud_deployer_class("gcp", "GCPDeployer")
        for cls in (gcp, Deployer):
            for behavior in ("repair", "run_ansible"):
                with self.subTest(cls=cls.__name__, behavior=behavior):
                    original = self.deployer(deployer_class=gcp)
                    self.assertNotIn("cloud", original.input_params)
                    saved_image = self.image.replace("a" * 64, "b" * 64)
                    original.params["artifact_registry_images"] = {"gr00t": saved_image}
                    original.save_meta()
                    restored = self.deployer(deployer_class=cls, profile="simple",
                                             existing=behavior, cloud=None)
                    Path(original.params["profile"]).unlink()
                    restored.tf_outputs["cloud"] = "gcp"
                    with mock.patch.dict(c, state_dir=restored.config["state_dir"]), \
                            mock.patch("src.python.config.load_profile_spec",
                                       side_effect=AssertionError("Must not reopen saved YAML")):
                        restored.ask_existing_behavior()
                        tfvars = {}
                        restored.create_tfvars(tfvars)
                        inventory = restored.create_ansible_inventory(write=False)
                        restored.save_meta()
                    self.assertTrue(tfvars["enable_artifact_registry"])
                    self.assertIn(saved_image, inventory)
                    saved = json.loads((self.root / "state" / "registry-test" / "meta.json").read_text())
                    self.assertEqual(saved["params"]["artifact_registry_images"], {"gr00t": saved_image})

    def test_profile_flows_to_terraform_and_inventory(self):
        spec = load_profile_spec(self.save_profile())
        assert spec is not None
        self.assertTrue(spec.get("enable_artifact_registry"))
        deployer = self.deployer()
        self.assertEqual(deployer.params["artifact_registry_images"], {"gr00t": self.image})
        tfvars = {}
        deployer.create_tfvars(tfvars)
        self.assertIs(tfvars["enable_artifact_registry"], True)
        self.assertEqual(tfvars["artifact_registry_project"], "example-project")
        self.assertEqual(tfvars["artifact_registry_location"], "us-central1")
        self.assertEqual(tfvars["artifact_registry_repository"], "robotics")
        inventory = deployer.create_ansible_inventory(write=False)
        values = dict(line.split("=", 1) for line in inventory.splitlines() if "=" in line)
        self.assertEqual(values["enable_artifact_registry"], "true")
        self.assertEqual(json.loads(values["artifact_registry_images_json"]), {"gr00t": self.image})

    def test_invalid_registry_profiles_fail_closed(self):
        original = copy.deepcopy(self.profile)
        invalid = [
            {"enabled": "false"},
            {"enabled": 1},
            {"project": ""},
            {"project": "https://example-project"},
            {"location": "us-central1\nmalicious=true"},
            {"location": "us"},
            {"repository": "../other"},
            {"images": [self.image]},
            {"images": {"gr00t": "gr00t:latest"}},
            {"images": {"gr00t": self.image.replace("robotics/", "other/")}},
            {"images": {"gr00t": self.image.replace("@sha256:", ":latest@sha256:")}},
            {"images": {"gr00t": self.image[:-1]}},
            {"images": {"bad\nname": self.image}},
            {"image": self.image},
        ]
        for changes in invalid:
            with self.subTest(changes=list(changes)):
                self.profile = copy.deepcopy(original)
                self.profile["artifact_registry"].update(changes)
                with self.assertRaisesRegex(ValueError, "artifact_registry"):
                    load_profile_spec(self.save_profile())

    def test_discovery_uses_same_validation(self):
        directory = self.root / "configs" / "profiles"
        directory.mkdir(parents=True)
        path = directory / "registry-test.yaml"
        path.write_text(yaml.safe_dump(self.profile))
        spec = list_available_profiles(str(self.root))["registry-test"]
        self.assertTrue(spec["enable_artifact_registry"])
        self.profile["artifact_registry"]["enabled"] = "yes"
        path.write_text(yaml.safe_dump(self.profile))
        with self.assertRaisesRegex(ValueError, "artifact_registry"):
            list_available_profiles(str(self.root))

    def test_enabled_registry_rejects_non_gcp_profile_and_deployer(self):
        self.profile["cloud"] = "aws"
        with self.assertRaisesRegex(ValueError, "gcp"):
            load_profile_spec(self.save_profile())
        self.profile["cloud"] = "gcp"
        with self.assertRaisesRegex(click.ClickException, "GCP"):
            self.deployer(cloud="aws")

    def test_disabled_deployment_does_not_inherit_previous_registry_tfvars(self):
        enabled = self.deployer()
        enabled.create_tfvars()
        disabled = self.deployer(profile="simple", cloud="aws", deployment_name="disabled")
        disabled.create_tfvars()
        tfvars = (self.root / "state" / "disabled" / ".tfvars").read_text()
        self.assertNotIn("artifact_registry", tfvars)
        inventory = disabled.create_ansible_inventory(write=False)
        self.assertIn("enable_artifact_registry=false", inventory)
        self.assertIn("artifact_registry_images_json={}", inventory)

    def test_real_gcp_deployer_identity_and_ansible_inventory_parser(self):
        from ansible.inventory.manager import InventoryManager
        from ansible.parsing.dataloader import DataLoader

        cls = self.cloud_deployer_class("gcp", "GCPDeployer")
        self.assertEqual(cls.cloud, "gcp")
        deployer = self.deployer(deployer_class=cls)
        self.assertNotIn("cloud", deployer.input_params)
        deployer.tf_outputs["cloud"] = "gcp"
        deployer.create_ansible_inventory()
        inventory_path = self.root / "state" / "registry-test" / ".inventory"
        loader = DataLoader()
        self.addCleanup(loader.cleanup_all_tmp_files)
        inventory = InventoryManager(loader=loader, sources=[str(inventory_path)])
        values = inventory.groups["targets"].get_vars()
        self.assertEqual(values["artifact_registry_project"], "example-project")
        self.assertEqual(values["artifact_registry_images_json"], {"gr00t": self.image})
        validate = runpy.run_path(str(
            ROOT / "src/ansible/roles/artifact-registry/filter_plugins/artifact_registry.py"
        ))["validate_settings"]
        resolved = validate(
            values["enable_artifact_registry"], values["cloud"],
            values["artifact_registry_project"], values["artifact_registry_location"],
            values["artifact_registry_repository"], values["artifact_registry_images_json"],
        )
        self.assertEqual(resolved["images"], {"gr00t": self.image})

    def test_authentication_only_and_disabled_profiles(self):
        self.profile["artifact_registry"]["images"] = {}
        spec = load_profile_spec(self.save_profile())
        assert spec is not None
        self.assertEqual(spec["artifact_registry_images"], {})
        self.profile["artifact_registry"]["enabled"] = False
        self.profile["artifact_registry"]["project"] = ""
        spec = load_profile_spec(self.save_profile())
        assert spec is not None
        self.assertFalse(spec["enable_artifact_registry"])
        self.assertEqual(spec["artifact_registry_project"], "")

    def test_repository_underscore_matches_terraform_contract(self):
        self.profile["artifact_registry"]["repository"] = "robotics_images"
        self.profile["artifact_registry"]["images"] = {}
        spec = load_profile_spec(self.save_profile())
        assert spec is not None
        self.assertEqual(spec["artifact_registry_repository"], "robotics_images")


if __name__ == "__main__":
    unittest.main()
