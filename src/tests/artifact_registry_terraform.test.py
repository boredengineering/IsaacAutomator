"""Offline source-level guardrails; provider-backed tests live in Terraform tests/.

Run: python3 src/tests/artifact_registry_terraform.test.py
"""
from pathlib import Path

import unittest

TF = Path(__file__).resolve().parents[1] / "terraform"


class ArtifactRegistryTerraformTests(unittest.TestCase):
    def test_registry_has_independent_durable_state_and_protected_docker_repository(self):
        directory = TF / "registry/gcp"
        self.assertTrue((directory / "main.tf").is_file(), "Missing isolated registry root")
        source = "\n".join(p.read_text() for p in directory.glob("*.tf"))
        self.assertIn('backend "gcs" {}', source)
        self.assertRegex(source, r'prevent_destroy\s*=\s*true')
        self.assertNotIn("cleanup_policies", source)
        self.assertNotIn('resource "google_kms_crypto_key"', source)
        self.assertNotIn('resource "google_project_iam_', source)
        self.assertRegex(source, r'format\s*=\s*"DOCKER"')
        self.assertRegex(source, r'disable_on_destroy\s*=\s*false')
        self.assertRegex(source, r'depends_on\s*=\s*\[google_project_service.artifact_registry, google_kms_crypto_key_iam_member.artifact_registry\]')
        self.assertRegex(source, r'member\s*=\s*"serviceAccount:\$\{google_project_service_identity.artifact_registry\[0\].email\}"')
        self.assertNotIn("registry/gcp", (TF / "gcp/main.tf").read_text())

    def test_workstation_contract_and_identity_plumbing(self):
        root = (TF / "gcp/main.tf").read_text()
        for name in ("enable_artifact_registry", "artifact_registry_project",
                     "artifact_registry_location", "artifact_registry_repository", "security_profile"):
            self.assertRegex(root, rf"\b{name}\s*=\s*var\.{name}\b")
        for directory in (TF / "gcp", TF / "gcp/ovkit"):
            source = "\n".join(p.read_text() for p in directory.glob("*.tf"))
            for name, kind, default in (("enable_artifact_registry", "bool", "false"),
                                       ("artifact_registry_project", "string", '""'),
                                       ("artifact_registry_location", "string", '""'),
                                       ("artifact_registry_repository", "string", '""')):
                self.assertRegex(source, rf'(?s)variable "{name}"\s*\{{[^}}]*type\s*=\s*{kind}[^}}]*default\s*=\s*{default}')
            self.assertNotRegex(source, r'resource "google_artifact_registry_repository"')
        module = (TF / "gcp/ovkit/main.tf").read_text()
        self.assertRegex(module, r'var.security_profile == "enterprise"\s*\|\|\s*var.enable_artifact_registry')
        self.assertIn("google_artifact_registry_repository_iam_member.reader", module)
        self.assertRegex(module, r'email\s*=.*google_service_account\.workstation_sa\[0\]\.email')
        reader = (TF / "gcp/ovkit/artifact_registry.tf").read_text()
        self.assertRegex(reader, r'member\s*=\s*"serviceAccount:\$\{google_service_account.workstation_sa\[0\].email\}"')


if __name__ == "__main__":
    unittest.main()
