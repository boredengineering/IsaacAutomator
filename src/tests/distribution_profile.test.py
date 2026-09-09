#!/usr/bin/env python3
"""Offline optional distribution profile/state/inventory integration tests."""
import copy
import json
import runpy
import unittest
from pathlib import Path
from unittest import mock

import click

BASE = runpy.run_path(str(Path(__file__).with_name("artifact_registry.test.py")))
Helpers = BASE["TestArtifactRegistry"]
load_profile_spec = BASE["load_profile_spec"]


class TestDistributionProfile(unittest.TestCase):
    root: Path
    profile: dict
    base_set_up = Helpers.setUp
    save_profile = Helpers.save_profile
    deployer = Helpers.deployer
    cloud_deployer_class = Helpers.cloud_deployer_class

    def setUp(self):
        self.base_set_up()
        self.image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/robotics/gr00t@sha256:" + "b" * 64
        self.registry = {
            "enabled": True, "provider": "aws_ecr", "account_id": "123456789012",
            "region": "us-east-1", "repository": "robotics/gr00t",
            "images": {"gr00t": self.image},
        }
        self.profile.pop("artifact_registry")
        self.profile.update(cloud="aws", container_registry=self.registry)

    def test_ecr_profile_to_tfvars_inventory_and_saved_repair(self):
        spec = load_profile_spec(self.save_profile())
        self.assertEqual(spec.get("container_registry"), self.registry)
        cls = self.cloud_deployer_class("aws", "AWSDeployer")
        deployer = self.deployer(deployer_class=cls)
        deployer.tf_outputs["cloud"] = "aws"
        deployer.existing_behavior = "modify"
        deployer.create_tfvars()
        variables = (self.root / "state/registry-test/.tfvars").read_text()
        self.assertIn('enable_ecr = "true"', variables)
        self.assertIn('ecr_account_id = "123456789012"', variables)
        self.assertNotIn("artifact_registry_project", variables)
        inventory = deployer.create_ansible_inventory(write=False)
        value = next(line.split("=", 1)[1] for line in inventory.splitlines()
                     if line.startswith("container_registry_json="))
        self.assertEqual(json.loads(value), self.registry)
        deployer.save_meta()
        saved = json.loads((self.root / "state/registry-test/meta.json").read_text())
        (self.root / "profile.yaml").unlink()
        restored = self.deployer(deployer_class=cls, profile="simple", existing="repair")
        with mock.patch.object(restored, "read_meta", return_value=copy.deepcopy(saved)):
            restored.ask_existing_behavior()
        self.assertEqual(restored.params["container_registry"], self.registry)

    def test_dockerhub_any_cloud_no_cloud_registry_tfvars(self):
        self.profile["container_registry"] = {
            "enabled": True, "provider": "dockerhub", "namespace": "exampleorg",
            "images": {"gr00t": "docker.io/exampleorg/gr00t@sha256:" + "c" * 64},
        }
        for cloud in ("aws", "gcp", "azure", "alicloud"):
            with self.subTest(cloud=cloud):
                self.profile["cloud"] = cloud
                spec = load_profile_spec(self.save_profile())
                self.assertEqual(spec["container_registry"]["auth"], "anonymous")
                deployer = self.deployer(cloud=cloud)
                deployer.existing_behavior = "modify"
                tfvars = {}
                deployer.create_tfvars(tfvars)
                self.assertNotIn("enable_ecr", tfvars)
                self.assertNotIn("enable_artifact_registry", tfvars)
                self.assertIn("docker.io/exampleorg/gr00t@sha256:", deployer.create_ansible_inventory(False))

    def test_new_gcp_selection_uses_existing_legacy_consumers(self):
        image = "us-central1-docker.pkg.dev/example-project/robotics/gr00t@sha256:" + "a" * 64
        self.profile.update(cloud="gcp", container_registry={
            "enabled": True, "provider": "gcp_artifact_registry",
            "project": "example-project", "location": "us-central1",
            "repository": "robotics", "images": {"gr00t": image},
        })
        deployer = self.deployer()
        self.assertTrue(deployer.params["enable_artifact_registry"])
        self.assertEqual(deployer.params["artifact_registry_images"], {"gr00t": image})
        deployer.save_meta()
        self.assertEqual(deployer.params["container_registry"], self.profile["container_registry"])
        deployer.params["artifact_registry_images"] = {}
        with self.assertRaises(click.ClickException):
            deployer.save_meta()

    def test_reject_invalid_provider_fields_clouds_and_digests(self):
        from src.python.registry_profile import RegistryProfileError, normalize_registries

        for change in (
            {"enabled": "true"}, {"provider": "unknown"}, {"provider": []},
            {"account_id": 123456789012}, {"region": "cn-north-1"},
            {"region": "us-gov-west-1"}, {"repository": "../other"},
            {"token": "synthetic-never-accepted"}, {"images": []},
            {"images": {"gr00t": self.image.replace("@sha256:", ":latest@sha256:")}},
            {"images": {"gr00t": self.image.replace("123456789012", "999999999999")}},
            {"images": {"gr00t": self.image.upper()}},
        ):
            with self.subTest(change=change), self.assertRaises(RegistryProfileError):
                normalize_registries(dict(self.profile, container_registry=dict(self.registry, **change)))
        with self.assertRaises(RegistryProfileError):
            normalize_registries(dict(self.profile, cloud="gcp"))
        with self.assertRaises(RegistryProfileError):
            normalize_registries(dict(self.profile, artifact_registry={"enabled": False}))

    def test_disabled_and_omitted_leave_no_registry_tfvars(self):
        for block in (None, {"enabled": False}, dict(self.registry, enabled=False)):
            if block is None:
                self.profile.pop("container_registry", None)
            else:
                self.profile["container_registry"] = block
            deployer = self.deployer(cloud="aws")
            deployer.existing_behavior = "modify"
            tfvars = {}
            deployer.create_tfvars(tfvars)
            self.assertFalse(deployer.params["container_registry"]["enabled"])
            self.assertNotIn("enable_ecr", tfvars)
            self.assertNotIn("enable_artifact_registry", tfvars)

    def test_shipped_examples_are_disabled_and_secret_free(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("example-profile", "example-aws-ecr", "example-dockerhub", "example-huggingface"):
            with self.subTest(name=name):
                spec = load_profile_spec(str(root / "configs/profiles" / (name + ".yaml")))
                self.assertFalse(spec["container_registry"]["enabled"])
                self.assertFalse(spec["enable_artifact_registry"])
                self.assertFalse(spec["huggingface"]["enabled"])
                self.assertNotIn("token", spec["raw"].get("huggingface", {}))

    def test_saved_ecr_cloud_or_image_tampering_cannot_overwrite_state(self):
        deployer = self.deployer(cloud="aws")
        deployer.save_meta()
        path = self.root / "state/registry-test/meta.json"
        before = path.read_bytes()
        saved = json.loads(before)
        for cloud, mutate_image in (("gcp", False), ("aws", True)):
            cls = self.cloud_deployer_class(cloud, {"aws": "AWSDeployer", "gcp": "GCPDeployer"}[cloud])
            restored = self.deployer(deployer_class=cls, profile="simple", existing="repair")
            candidate = copy.deepcopy(saved)
            if mutate_image:
                candidate["params"]["container_registry"]["images"]["gr00t"] = "docker.io/exampleorg/gr00t:latest"
            with mock.patch.object(restored, "read_meta", return_value=candidate):
                with self.assertRaises(click.ClickException):
                    restored.ask_existing_behavior()
            restored.save_meta()
            self.assertEqual(path.read_bytes(), before)

    def test_actual_ansible_inventory_decodes_selected_mapping(self):
        from ansible.parsing.dataloader import DataLoader
        from ansible.inventory.manager import InventoryManager

        deployer = self.deployer(cloud="aws")
        deployer.create_ansible_inventory()
        loader = DataLoader()
        inventory = InventoryManager(loader=loader, sources=[str(self.root / "state/registry-test/.inventory")])
        decoded = inventory.groups["targets"].get_vars()["container_registry_json"]
        self.assertEqual(json.loads(decoded) if isinstance(decoded, str) else decoded, self.registry)

    def test_huggingface_independent_of_registry_and_saved_without_yaml(self):
        self.profile.pop("container_registry")
        self.profile["huggingface"] = {
            "enabled": True, "repositories": [{"name": "policy", "repo_id": "exampleorg/policy",
                "repo_type": "model", "revision": "a" * 40}],
        }
        spec = load_profile_spec(self.save_profile())
        self.assertTrue(spec.get("huggingface", {}).get("enabled", False))
        deployer = self.deployer(cloud="aws")
        inventory = deployer.create_ansible_inventory(False)
        raw = next(line.split("=", 1)[1] for line in inventory.splitlines() if line.startswith("huggingface_json="))
        self.assertEqual(json.loads(raw)["repositories"], self.profile["huggingface"]["repositories"])
        deployer.save_meta()
        saved = json.loads((self.root / "state/registry-test/meta.json").read_text())
        restored = self.deployer(cloud="aws", profile="simple", existing="repair")
        (self.root / "profile.yaml").unlink()
        with mock.patch.object(restored, "read_meta", return_value=saved):
            restored.ask_existing_behavior()
        self.assertEqual(restored.params["huggingface"], deployer.params["huggingface"])
        restored.params["huggingface"]["repositories"][0]["revision"] = "main"
        with self.assertRaises(click.ClickException):
            restored.save_meta()


del Helpers  # Do not rediscover the imported base suite as tests in this module.

if __name__ == "__main__":
    unittest.main()
