"""Offline source guardrails. Run provider mocks with src/terraform/test_ecr.py."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

TF = Path(__file__).resolve().parents[1] / "terraform"
SPEC = importlib.util.spec_from_file_location("ecr_runner", TF / "test_ecr.py")
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class ECRTerraformTests(unittest.TestCase):
    def test_runner_refuses_missing_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                RUNNER.copy_sources(root / "missing", root / "target")

    def test_runner_copies_only_safe_source_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            target = Path(temporary) / "target"
            source.mkdir()
            for name in ("main.tf", "override.tf", "backend_override.tf", "override.tf.json", "test.auto.tfvars", "main.tf.json"):
                (source / name).write_text("# offline fixture")
            RUNNER.copy_sources(source, target)
            self.assertEqual([p.name for p in target.iterdir()], ["main.tf"])

    def test_runner_refuses_apply_and_unmocked_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            (source / "tests").mkdir(parents=True)
            (source / "main.tf").write_text("# offline fixture")
            path = source / "tests/test.tftest.hcl"
            for text in ('mock_provider "aws" {}\nrun "unsafe" { command = apply }',
                         'run "unsafe" { command = plan }',
                         'mock_provider "aws" {}\nrun "implicit_apply" {}'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(ValueError):
                        RUNNER.copy_sources(source, Path(temporary) / "target")

    def test_runner_refuses_symlinked_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            fixture = Path(temporary) / "fixture.tf"
            fixture.write_text("# offline fixture")
            (source / "main.tf").symlink_to(fixture)
            with self.assertRaises(ValueError):
                RUNNER.copy_sources(source, Path(temporary) / "target")

    def test_shared_registry_is_independent_and_protected(self):
        directory = TF / "registry/aws"
        self.assertTrue((directory / "main.tf").is_file(), "Missing independent ECR registry stack")
        source = "\n".join(p.read_text() for p in directory.glob("*.tf"))
        self.assertIn('backend "s3" {}', source)
        self.assertRegex(source, r'prevent_destroy\s*=\s*true')
        self.assertRegex(source, r'force_delete\s*=\s*false')
        self.assertRegex(source, r'allowed_account_ids\s*=\s*\[var.account_id\]')
        self.assertNotIn('resource "aws_ecr_lifecycle_policy"', source)
        self.assertNotIn('resource "aws_kms_key"', source)
        self.assertNotIn('resource "aws_iam_access_key"', source)
        self.assertNotIn('registry/aws', (TF / "aws/main.tf").read_text())
        readme = (directory / "README.md").read_text()
        for required in ("-backend-config", "separate", "GetAuthorizationToken", "cross-account", "prevent_destroy"):
            self.assertIn(required, readme)

    def test_optional_reader_is_wired_to_actual_instance(self):
        root = (TF / "aws/main.tf").read_text()
        for name in ("enable_ecr", "ecr_account_id", "ecr_region", "ecr_repository"):
            self.assertRegex(root, rf"\b{name}\s*=\s*var\.{name}\b")
        for directory in (TF / "aws", TF / "aws/isaac-workstation"):
            source = "\n".join(p.read_text() for p in directory.glob("*.tf"))
            self.assertRegex(source, r'(?s)variable "enable_ecr"\s*\{[^}]*default\s*=\s*false')
            self.assertNotIn('resource "aws_ecr_repository"', source)
        instance = (TF / "aws/isaac-workstation/main.tf").read_text()
        self.assertRegex(instance, r'iam_instance_profile\s*=\s*var.enable_ecr\s*\?\s*aws_iam_instance_profile.ecr_reader\[0\].name\s*:\s*var.iam_instance_profile')
        self.assertIn('dynamic "metadata_options"', instance)
        self.assertRegex(instance, r'http_tokens\s*=\s*"required"')
        self.assertIn('aws_iam_role_policy.ecr_reader', instance)


if __name__ == "__main__":
    unittest.main()
