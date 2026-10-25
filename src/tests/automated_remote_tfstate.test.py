"""Unit and contract tests for Automated Remote Terraform State Provisioning."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import click
from click.core import ParameterSource

from src.python.backend_bootstrap import check_storage_exists, ensure_backend_storage, InspectionError
from src.python.backend_context import (
    resolve_ambient_owner_scope,
    resolve_ambient_principal,
    resolve_ambient_region,
    resolve_cloud_context,
)
from src.python.backend_selection import select_backend, normalize_profile_backend, BackendSelectionError
from src.python.terraform_backend import BackendSpec


class TestAutomatedRemoteState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # --------------------------------------------------------------------------
    # 1. Bucket Option Gate Tests (Strict Opt-In Rule)
    # --------------------------------------------------------------------------
    def test_empty_bucket_defaults_to_local_state(self):
        """When bucket is empty, null, or omitted, backend must be strictly local."""
        cases = [
            {"storage": {"backend": "gcs", "bucket": ""}},
            {"storage": {"backend": "gcs", "bucket": None}},
            {"storage": {"backend": "local", "bucket": ""}},
            {"storage": {}},
            {"security": {"storage": {"state_backend": "local", "state_bucket": ""}}},
        ]
        for c in cases:
            with self.subTest(case=c):
                spec = select_backend({}, {"raw": c}, "gcp")
                self.assertEqual(spec.backend, "local")
                self.assertEqual(spec.cloud, "gcp")
                self.assertNotIn("destination", spec.to_dict())

    def test_normalize_profile_backend_with_storage_block(self):
        """Top-level storage block normalization produces standard BackendSpec dict."""
        empty = normalize_profile_backend({"storage": {"backend": "gcs", "bucket": ""}})
        self.assertEqual(empty["terraform_state"]["backend"], "local")

        auto = normalize_profile_backend({"cloud": "gcp", "storage": {"backend": "gcs", "bucket": "auto"}})
        self.assertEqual(auto["terraform_state"]["destination"]["bucket"], "auto")

        custom = normalize_profile_backend({"cloud": "gcp", "project": "my-prj", "storage": {"backend": "gcs", "bucket": "my-bucket"}})
        self.assertEqual(custom["terraform_state"]["destination"]["bucket"], "my-bucket")
        self.assertEqual(custom["terraform_state"]["destination"]["project"], "my-prj")

    # --------------------------------------------------------------------------
    # 2. Auto Bucket Resolution (bucket: "auto")
    # --------------------------------------------------------------------------
    def test_auto_bucket_generates_deterministic_proposal(self):
        """bucket: 'auto' synthesizes deterministic isaac-state-<hash>."""
        profile = {"raw": {"project": "test-project", "storage": {"backend": "gcs", "bucket": "auto"}}}
        spec = select_backend({}, profile, "gcp")
        self.assertEqual(spec.backend, "gcs")
        d = spec.to_dict()["destination"]
        self.assertTrue(d["bucket"].startswith("isaac-state-"))
        self.assertEqual(d["project"], "test-project")
        self.assertEqual(d["prefix"], "isaacautomator/v2")

        # Must be strictly deterministic across calls
        spec2 = select_backend({}, profile, "gcp")
        self.assertEqual(spec.to_dict(), spec2.to_dict())

    def test_custom_bucket_sets_remote_backend(self):
        """Explicit custom bucket is preserved with target project."""
        profile = {"raw": {"project": "test-project", "storage": {"backend": "gcs", "bucket": "my-custom-state-bucket"}}}
        spec = select_backend({}, profile, "gcp")
        self.assertEqual(spec.backend, "gcs")
        d = spec.to_dict()["destination"]
        self.assertEqual(d["bucket"], "my-custom-state-bucket")
        self.assertEqual(d["project"], "test-project")

    # --------------------------------------------------------------------------
    # 3. Ambient Context Auto-Discovery
    # --------------------------------------------------------------------------
    def test_ambient_context_resolver_with_env(self):
        """Context resolver reads environment variables when available."""
        with mock.patch.dict(os.environ, {
            "CLOUDSDK_CORE_PROJECT": "env-project-123",
            "CLOUDSDK_COMPUTE_REGION": "europe-west1",
            "ISAAC_CONTROLLER_PRINCIPAL": "user:test@example.com",
        }):
            ctx = resolve_cloud_context("gcp")
            self.assertEqual(ctx.owner_scope, "env-project-123")
            self.assertEqual(ctx.region, "europe-west1")
            self.assertEqual(ctx.controller_principal, "user:test@example.com")

    def test_ambient_region_truncates_zone(self):
        """Zone suffix (e.g. us-central1-a) is cleanly converted to region."""
        self.assertEqual(resolve_ambient_region("gcp", zone="us-central1-a"), "us-central1")
        self.assertEqual(resolve_ambient_region("gcp", zone="europe-west4-b"), "europe-west4")

    # --------------------------------------------------------------------------
    # 4. Preflight & Just-In-Time Bootstrap
    # --------------------------------------------------------------------------
    def test_check_storage_exists_detects_existing_bucket(self):
        """check_storage_exists returns True when CLI describe succeeds."""
        spec = BackendSpec.from_dict({
            "backend": "gcs",
            "namespace": "studio",
            "destination": {"bucket": "existing-bucket", "project": "test-project", "prefix": "state"},
        }, cloud="gcp")

        # Mock CLI returning success
        with mock.patch("src.python.backend_bootstrap._cli_read", return_value={"name": "existing-bucket"}):
            self.assertTrue(check_storage_exists(spec))

    def test_check_storage_exists_detects_missing_bucket(self):
        """check_storage_exists returns False when CLI describe returns not-found."""
        spec = BackendSpec.from_dict({
            "backend": "gcs",
            "namespace": "studio",
            "destination": {"bucket": "missing-bucket", "project": "test-project", "prefix": "state"},
        }, cloud="gcp")

        with mock.patch("src.python.backend_bootstrap._cli_read", side_effect=InspectionError("not-found")):
            self.assertFalse(check_storage_exists(spec))

    def test_ensure_backend_storage_skips_when_existing(self):
        """ensure_backend_storage does not call bootstrap session if bucket exists."""
        spec = BackendSpec.from_dict({
            "backend": "gcs",
            "namespace": "studio",
            "destination": {"bucket": "existing-bucket", "project": "test-project", "prefix": "state"},
        }, cloud="gcp")

        messages = []
        with mock.patch("src.python.backend_bootstrap.check_storage_exists", return_value=True), \
             mock.patch("src.python.backend_bootstrap.BootstrapSession") as mock_session:
            result = ensure_backend_storage(spec, echo=messages.append)
            self.assertEqual(result, spec)
            self.assertFalse(mock_session.called)
            self.assertTrue(any("Verified" in m for m in messages))

    def test_ensure_backend_storage_provisions_when_missing(self):
        """ensure_backend_storage bootstraps bucket via BootstrapSession when missing."""
        spec = BackendSpec.from_dict({
            "backend": "gcs",
            "namespace": "studio",
            "destination": {"bucket": "new-bucket", "project": "test-project", "prefix": "state"},
        }, cloud="gcp")

        mock_session_inst = mock.MagicMock()
        mock_session_inst.__enter__.return_value = mock_session_inst
        mock_session_inst.plan.return_value = "SYNTHETIC_PLAN"

        messages = []
        with mock.patch("src.python.backend_bootstrap.check_storage_exists", return_value=False), \
             mock.patch("src.python.backend_bootstrap.BootstrapSession", return_value=mock_session_inst), \
             mock.patch("src.python.backend_context.resolve_cloud_context") as mock_ctx:
            mock_ctx.return_value = mock.Mock(region="us-central1", controller_principal="user:test@example.com")
            result = ensure_backend_storage(spec, bootstrap_state_root=self.root, echo=messages.append)
            self.assertEqual(result, spec)
            mock_session_inst.plan.assert_called_once()
            mock_session_inst.apply.assert_called_once_with("SYNTHETIC_PLAN", acknowledge_creation=True)
            self.assertTrue(any("Auto-bootstrapping" in m for m in messages))

    # --------------------------------------------------------------------------
    # 5. CLI Precedence & Overrides
    # --------------------------------------------------------------------------
    def test_cli_state_backend_local_overrides_profile_auto(self):
        """Command-line --state-backend local overrides profile's bucket: auto."""
        profile = {"raw": {"project": "prj", "storage": {"backend": "gcs", "bucket": "auto"}}}
        ctx = click.Context(click.Command("deploy"))
        ctx.set_parameter_source("state_backend", ParameterSource.COMMANDLINE)
        spec = select_backend({"state_backend": "local"}, profile, "gcp", ctx)
        self.assertEqual(spec.backend, "local")
        self.assertNotIn("destination", spec.to_dict())

    # --------------------------------------------------------------------------
    # 6. Dry-Run Safety & Zero Network Calls
    # --------------------------------------------------------------------------
    def test_dry_run_safety_never_mutates_storage(self):
        """Dry-run must never apply Terraform mutations to provision remote storage."""
        spec = BackendSpec.from_dict({
            "backend": "gcs",
            "namespace": "studio",
            "destination": {"bucket": "missing-bucket", "project": "test-project", "prefix": "state"},
        }, cloud="gcp")

        mock_session_inst = mock.MagicMock()
        mock_session_inst.__enter__.return_value = mock_session_inst
        messages = []
        with mock.patch("src.python.backend_bootstrap.check_storage_exists", return_value=False), \
             mock.patch("src.python.backend_bootstrap.BootstrapSession", return_value=mock_session_inst):
            result = ensure_backend_storage(spec, dry_run=True, echo=messages.append)
            self.assertEqual(result, spec)
            mock_session_inst.apply.assert_not_called()
            self.assertTrue(any("[DRY-RUN]" in m for m in messages))

    def test_empty_bucket_zero_network_calls(self):
        """Empty bucket strictly resolves to local backend with zero CLI/network calls."""
        profile = {"raw": {"storage": {"backend": "gcs", "bucket": ""}}}
        spec = select_backend({}, profile, "gcp")
        self.assertEqual(spec.backend, "local")

        transport = mock.Mock()
        self.assertTrue(check_storage_exists(spec, transport=transport))
        transport.assert_not_called()

        result = ensure_backend_storage(spec, transport=transport)
        self.assertEqual(result, spec)
        transport.assert_not_called()

    def test_malformed_project_and_bucket_names_fail_closed(self):
        """Malformed projects and buckets are rejected without leaking values or crashing."""
        malformed_buckets = [
            "-bad-start",
            "bad-end-",
            "BAD_UPPERCASE",
            "a" * 65,
            "contains..double-dots",
            "contains/slashes",
        ]
        for b in malformed_buckets:
            with self.subTest(bucket=b):
                profile = {"raw": {"project": "valid-project", "storage": {"backend": "gcs", "bucket": b}}}
                with self.assertRaises(BackendSelectionError):
                    select_backend({}, profile, "gcp")

        malformed_projects = [
            "123-bad-start",
            "bad-end-",
            "PROJECT_UPPERCASE",
            "bad@characters!",
        ]
        for p in malformed_projects:
            with self.subTest(project=p):
                profile = {"raw": {"project": p, "storage": {"backend": "gcs", "bucket": "auto"}}}
                # Context auto-discovery should reject malformed project
                self.assertIsNone(resolve_ambient_owner_scope("gcp", explicit=p))

    def test_deploy_command_does_not_artificially_override_profile(self):
        """DeployCommand.parse_args must not inject --state-backend as a CLI argument."""
        from src.python.deploy_command import DeployCommand
        from click.testing import CliRunner
        cmd = DeployCommand("test-deploy", params=[])
        ctx = click.Context(cmd)
        # Verify parse_args doesn't mutate sys.argv or inject --state-backend
        opts, args, _ = cmd.make_parser(ctx).parse_args(args=["--software-profile", "sample"])
        self.assertNotIn("state_backend", opts)


if __name__ == "__main__":
    unittest.main()
