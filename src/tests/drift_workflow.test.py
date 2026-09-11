"""Offline workflow generator contracts; no GitHub/cloud credentials required."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


def example(provider="aws"):
    identities = {
        "aws": {"role_arn": "arn:aws:iam::123456789012:role/drift-detect", "region": "us-east-1"},
        "gcp": {"workload_identity_provider": "projects/123456789/locations/global/workloadIdentityPools/drift/providers/github", "service_account": "drift@sample-project.iam.gserviceaccount.com"},
        "azure": {"client_id": "11111111-1111-1111-1111-111111111111", "tenant_id": "22222222-2222-2222-2222-222222222222", "subscription_id": "33333333-3333-3333-3333-333333333333"},
    }
    return {"schema_version": 1, "repository": "example/infrastructure", "protected_branch": "main", "source_revision": "a" * 40,
            "provider": provider, "identity": identities[provider], "config_path": "configs/drift/production.yaml",
            "deployments": ["gpu-a"], "backend_identity": "studio/production/workstations", "namespace": "studio",
            "scopes": ["workstation_infrastructure"], "runtime_image": "ghcr.io/example/automator@sha256:" + "b" * 64,
            "terraform_version": "1.10.5"}


class WorkflowTests(unittest.TestCase):
    def test_azure_login_uses_verified_peeled_commit_not_annotated_tag(self):
        from src.python.drift_workflow import WorkflowConfig, render, validate_rendered
        # Offline regression fixture, verified against public Azure/login via:
        # git ls-remote https://github.com/Azure/login.git 'refs/tags/v2.3.0*'
        # action.yml also retrieved successfully at the peeled commit.
        tag_object = "eec3c95657c1536435858eda1f3ff5437fee8474"
        commit = "a457da9ea143d694b1b9c7c869ebb04ebe844ef5"
        files = render(WorkflowConfig.from_dict(example("azure")))
        job = yaml.safe_load(files["drift-check.yml"])["jobs"]["detect"]
        login = next(step["uses"] for step in job["steps"]
                     if step.get("uses", "").startswith("azure/login@"))
        self.assertEqual(login, "azure/login@" + commit)
        self.assertEqual(validate_rendered(files)["yaml"], "valid")
        with self.assertRaisesRegex(ValueError, "action revision is not approved"):
            validate_rendered({"drift-check.yml": files["drift-check.yml"].replace(commit, tag_object)})

    def test_remote_terraform_version_policy_for_every_cloud(self):
        from src.python.drift_workflow import WorkflowConfig, render
        from src.python.terraform_backend import validate_terraform_version
        for provider, backend in (("aws", "s3"), ("gcp", "gcs"), ("azure", "azurerm")):
            for version, accepted in (("1.9.8", False), ("1.10.0", True), ("1.10.5", True),
                                      ("2.0.0", False), ("1.10.0-rc1", False), ("1.010.0", False)):
                with self.subTest(provider=provider, version=version):
                    data = {**example(provider), "terraform_version": version}
                    if not accepted:
                        with self.assertRaises(ValueError) as shared_error:
                            validate_terraform_version(version, backend)
                        with self.assertRaises(ValueError) as rejected:
                            WorkflowConfig.from_dict(data)
                        self.assertEqual(str(rejected.exception), str(shared_error.exception))
                    else:
                        validate_terraform_version(version, backend)
                        job = yaml.safe_load(render(WorkflowConfig.from_dict(data))["drift-check.yml"])["jobs"]["detect"]
                        setup = next(step for step in job["steps"] if step["name"] == "Pinned Terraform")
                        self.assertEqual(setup["with"]["terraform_version"], version)

    def test_namespace_uses_backend_spec_component_contract(self):
        from src.python.drift_workflow import WorkflowConfig
        from src.python.terraform_backend import BackendSpec
        for provider in ("aws", "gcp", "azure"):
            for namespace, accepted in (("auto", False), ("AUTO", False), ("Studio", False),
                                        ("a" * 64, False), ("studio", True), ("a" * 63, True),
                                        ("studio_01-prod", True), ("", False), (None, False)):
                with self.subTest(provider=provider, namespace=namespace):
                    data = {**example(provider), "namespace": namespace}
                    if accepted:
                        backend = BackendSpec.from_dict({"namespace": namespace}, cloud=provider)
                        self.assertEqual(WorkflowConfig.from_dict(data).to_dict()["namespace"], backend.namespace)
                    else:
                        with self.assertRaises(ValueError) as backend_error:
                            BackendSpec.from_dict({"namespace": namespace}, cloud=provider)
                        with self.assertRaises(ValueError) as workflow_error:
                            WorkflowConfig.from_dict(data)
                        self.assertEqual(str(workflow_error.exception), str(backend_error.exception))

    def test_success_exit_with_unclassified_report_fails_closed(self):
        from src.python.drift_workflow import WorkflowConfig, render
        job = yaml.safe_load(render(WorkflowConfig.from_dict(example()))["drift-check.yml"])["jobs"]["detect"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "drift").write_text('#!/bin/bash\nprintf "not-json-secret"\nexit 0\n')
            (root / "drift").chmod(0o700)
            env = {**os.environ, **job["env"], "DRIFT_DEPLOYMENT": "gpu-a", "RUNNER_TEMP": directory, "GITHUB_STEP_SUMMARY": str(root / "summary")}
            result = subprocess.run(["bash", "-c", job["steps"][-1]["run"]], cwd=root, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(result.returncode, 1)
            self.assertIn("wrapper exit 0", (root / "summary").read_text())
            self.assertNotIn("secret", result.stdout + result.stderr + (root / "summary").read_text())

    def test_azure_terraform_receives_federated_identity_not_keys(self):
        from src.python.drift_workflow import WorkflowConfig, render
        data = example("azure")
        job = yaml.safe_load(render(WorkflowConfig.from_dict(data))["drift-check.yml"])["jobs"]["detect"]
        self.assertEqual(job["env"].get("ARM_USE_OIDC"), "true")
        self.assertEqual(job["env"].get("ARM_USE_AZUREAD"), "true")
        for key in ("client_id", "tenant_id", "subscription_id"):
            self.assertEqual(job["env"]["ARM_" + key.upper()], data["identity"][key])
        self.assertNotIn("ARM_CLIENT_SECRET", job["env"])

    def test_examples_require_real_pins_and_remediation_template_is_nonexecutable(self):
        from src.python.drift_workflow import WorkflowConfig, render
        root = Path(__file__).resolve().parents[2]
        for provider in ("aws", "gcp", "azure"):
            path = root / "configs" / "drift" / f"example-{provider}-github.yaml"
            self.assertTrue(path.exists(), "provider customization example required")
            data = yaml.safe_load(path.read_text())
            with self.assertRaises(ValueError):
                WorkflowConfig.from_dict(data)
            data["source_revision"] = "a" * 40
            data["runtime_image"] = example()["runtime_image"]
            self.assertIn("drift-check.yml", render(WorkflowConfig.from_dict(data)))
        path = root / "templates" / "github-actions" / "drift-remediate.yml.tmpl"
        self.assertTrue(path.exists())
        self.assertIsNone(yaml.safe_load(path.read_text()))
        self.assertIn("UNAVAILABLE", path.read_text())
        forged = {**example(), "correction_mode": "approval_required", "environment_verified": True, "approval_receipt": {"approved": True}}
        with self.assertRaises(ValueError):
            WorkflowConfig.from_dict(forged)

    def test_preview_and_setup_are_offline_and_validation_gates_writes(self):
        from src.python import drift_workflow as workflow
        self.assertTrue(hasattr(workflow, "preview"), "offline preview API required")
        config = workflow.WorkflowConfig.from_dict(example())
        result = workflow.preview(config)
        self.assertEqual(result["files"], workflow.render(config))
        setup = workflow.verify_setup(config)
        self.assertFalse(setup["verified"])
        self.assertFalse(setup["remediation_available"])
        self.assertEqual(setup["status"], "UNVERIFIED")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            with patch.object(workflow, "validate_rendered", side_effect=ValueError("invalid workflow")):
                with self.assertRaises(ValueError):
                    workflow.generate(config, output)
            self.assertFalse(output.exists())

    def test_validation_reports_missing_actionlint_and_rejects_bad_workflows(self):
        from src.python import drift_workflow as workflow
        self.assertTrue(hasattr(workflow, "validate_rendered"), "workflow validators required")
        files = workflow.render(workflow.WorkflowConfig.from_dict(example()))
        with patch.object(shutil, "which", return_value=None):
            result = workflow.validate_rendered(files)
        self.assertEqual(result, {"yaml": "valid", "actionlint": "unavailable (not installed)"})
        for text in ("on: [workflow_dispatch]\njobs: {}", "'on': {pull_request_target: {}}", files["drift-check.yml"].replace("11bd71901bbe5b1630ceea73d27597364c9af683", "main")):
            with self.assertRaises(ValueError):
                workflow.validate_rendered({"drift-check.yml": text})

    @unittest.skipUnless(shutil.which("actionlint"), "actionlint unavailable; not installed silently")
    def test_actionlint_when_already_installed(self):
        from src.python.drift_workflow import WorkflowConfig, render, validate_rendered
        for provider in ("aws", "gcp", "azure"):
            self.assertEqual(validate_rendered(render(WorkflowConfig.from_dict(example(provider))))["actionlint"], "valid")

    def test_install_requires_destination_bound_preview_confirmation(self):
        from src.python import drift_workflow as workflow
        self.assertTrue(hasattr(workflow, "install_preview"), "explicit installation preview required")
        config = workflow.WorkflowConfig.from_dict(example())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            preview = workflow.install_preview(config, root)
            self.assertEqual(preview["destination"], str(root / ".github" / "workflows"))
            self.assertIn("+name: IsaacAutomator", preview["diff"])
            self.assertFalse((root / ".github").exists())
            for confirmation in (None, True, "yes", "0" * 64):
                with self.assertRaises(ValueError):
                    workflow.install(config, root, confirmation=confirmation)
                self.assertFalse((root / ".github").exists())
            paths = workflow.install(config, root, confirmation=preview["confirmation"])
            self.assertEqual(paths, [root / ".github" / "workflows" / "drift-check.yml"])
            (root / ".github" / "workflows" / "unrelated.yml").write_text("untouched")
            (paths[0]).write_text("unmanaged")
            with self.assertRaisesRegex(ValueError, "conflict"):
                workflow.install(config, root, confirmation=preview["confirmation"])
            self.assertEqual((paths[0]).read_text(), "unmanaged")
        with self.assertRaises(ValueError):
            workflow.install_preview(config, Path(__file__).resolve().parents[2])

    def test_generation_is_inert_idempotent_and_refuses_conflicts_or_links(self):
        from src.python import drift_workflow as workflow
        self.assertTrue(hasattr(workflow, "generate"), "inert filesystem generator required")
        config = workflow.WorkflowConfig.from_dict(example())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "generated"
            paths = workflow.generate(config, output)
            self.assertEqual(set(paths), {output / "drift-check.yml", output / "SETUP.md"})
            first = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
            self.assertEqual(workflow.generate(config, output), paths)
            self.assertEqual(first, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths})
            self.assertFalse((root / ".github").exists())
            (output / "drift-check.yml").write_text("unmanaged")
            with self.assertRaisesRegex(ValueError, "conflict"):
                workflow.generate(config, output)
            self.assertEqual((output / "drift-check.yml").read_text(), "unmanaged")
            with self.assertRaises(ValueError):
                workflow.generate(config, root / ".github" / "workflows")
            (root / "linked").symlink_to(output, target_is_directory=True)
            with self.assertRaises(ValueError):
                workflow.generate(config, root / "linked" / "nested")
            target = root / "symlink-output"
            target.mkdir()
            (target / "drift-check.yml").symlink_to(output / "drift-check.yml")
            with self.assertRaises(ValueError):
                workflow.generate(config, target)

    def test_private_headless_execution_preserves_errors_and_cleans_files(self):
        from src.python.drift_workflow import WorkflowConfig, render
        job = yaml.safe_load(render(WorkflowConfig.from_dict(example()))["drift-check.yml"])["jobs"]["detect"]
        script = job["steps"][-1]["run"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "drift"
            command.write_text('#!/bin/bash\nprintf \'{"classes":["clean_within_coverage"],"private":"secret-plan-value"}\'\nprintf secret-error >&2\nprintf "%s\\n" "$@" > "$ARG_LOG"\nexit "$TEST_CODE"\n')
            command.chmod(0o700)
            for code, expected, label in ((0, 0, "clean"), (2, 2, "drift"), (1, 1, "error"), (3, 3, "incomplete"), (127, 1, "error")):
                summary = root / "summary"
                summary.write_text("")
                env = {**os.environ, **job["env"], "DRIFT_DEPLOYMENT": "gpu-a", "RUNNER_TEMP": directory, "GITHUB_STEP_SUMMARY": str(summary), "ARG_LOG": str(root / "args"), "TEST_CODE": str(code)}
                result = subprocess.run(["bash", "-c", script], cwd=root, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
                self.assertEqual(result.returncode, expected)
                self.assertIn(label, summary.read_text())
                self.assertNotIn("secret", result.stdout + result.stderr + summary.read_text())
                self.assertEqual(list(root.glob("isaac-drift.*")), [])
                self.assertIn("--report-dir", (root / "args").read_text())
                self.assertIn("configs/drift/production.yaml", (root / "args").read_text())

    def test_concurrency_is_stable_across_source_image_and_schedule_changes(self):
        from src.python.drift_workflow import WorkflowConfig, render

        def group(data):
            job = yaml.safe_load(render(WorkflowConfig.from_dict(data))["drift-check.yml"])["jobs"]["detect"]
            self.assertFalse(job["concurrency"]["cancel-in-progress"])
            self.assertTrue(job["concurrency"]["group"].endswith("-${{ matrix.deployment }}"))
            return job["concurrency"]["group"]

        groups = []
        for provider in ("aws", "gcp", "azure"):
            data = example(provider)
            original = group(data)
            groups.append(original)
            for key, value in (("source_revision", "c" * 40),
                               ("runtime_image", "ghcr.io/example/automator@sha256:" + "d" * 64),
                               ("schedule", {"enabled": True, "cron_utc": "23 */8 * * *"})):
                with self.subTest(provider=provider, field=key):
                    changed = copy.deepcopy(data)
                    changed[key] = value
                    self.assertEqual(group(changed), original)
            for key, value in (("backend_identity", "studio/staging/workstations"), ("namespace", "another")):
                with self.subTest(provider=provider, field=key):
                    self.assertNotEqual(group({**data, key: value}), original)
        self.assertEqual(len(set(groups)), 3)

    def test_mixed_scopes_aggregate_exit_precedence_without_leaking_reports(self):
        from itertools import product
        from src.python.drift_workflow import WorkflowConfig, render
        scopes = ["workstation_infrastructure", "controller_identity", "backend_infrastructure", "runtime"]
        labels = {0: "clean", 2: "drift", 3: "incomplete", 1: "error", 127: "error"}
        cases = list(product(labels, repeat=2)) + [(0, 2, 3, 1), (1, 3, 2, 0), (0, 2, 3, 0), (3, 2, 0, 0)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "drift"
            command.write_text(
                '#!/bin/bash\n'
                'printf \'{"classes":["clean_within_coverage"],"private":"secret-plan-value"}\'\n'
                'printf secret-error >&2\n'
                'printf "%s\\n" "$6" >> "$CALL_LOG"\n'
                'case "$6" in\n' +
                ''.join(f'  {scope}) exit "$CODE_{index}" ;;\n' for index, scope in enumerate(scopes)) +
                '  *) exit 99 ;;\nesac\n')
            command.chmod(0o700)
            for codes in cases:
                with self.subTest(codes=codes):
                    data = {**example(), "scopes": scopes[:len(codes)]}
                    job = yaml.safe_load(render(WorkflowConfig.from_dict(data))["drift-check.yml"])["jobs"]["detect"]
                    summary, calls = root / "summary", root / "calls"
                    summary.write_text("")
                    calls.write_text("")
                    env = {**os.environ, **job["env"], "DRIFT_DEPLOYMENT": "gpu-a", "RUNNER_TEMP": directory,
                           "GITHUB_STEP_SUMMARY": str(summary), "CALL_LOG": str(calls),
                           **{f"CODE_{index}": str(code) for index, code in enumerate(codes)}}
                    result = subprocess.run(["bash", "-c", job["steps"][-1]["run"]], cwd=root, env=env,
                                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
                    expected = next((status for status in (1, 3, 2) if status in [1 if c == 127 else c for c in codes]), 0)
                    self.assertEqual(result.returncode, expected)
                    self.assertEqual(calls.read_text().splitlines(), data["scopes"])
                    self.assertEqual(summary.read_text().splitlines(),
                                     [f"Drift check: {labels[code]} (wrapper exit {code})" for code in codes])
                    self.assertEqual(result.stdout + result.stderr, "")
                    self.assertNotIn("secret", summary.read_text())
                    self.assertEqual(list(root.glob("isaac-drift.*")), [])

    def test_explicit_schedule_and_customization_changes_provenance(self):
        from src.python.drift_workflow import WorkflowConfig, render
        data = example()
        before = render(WorkflowConfig.from_dict(data))["drift-check.yml"]
        data.update(schedule={"enabled": True, "cron_utc": "23 */8 * * *"}, protected_branch="release/stable", runner_labels=["ubuntu-22.04"], deployments=["gpu-a", "gpu-b"], timeout_minutes=55, max_parallel=2)
        text = render(WorkflowConfig.from_dict(data))["drift-check.yml"]
        doc = yaml.safe_load(text)
        self.assertEqual(doc["on"]["schedule"], [{"cron": "23 */8 * * *"}])
        self.assertNotEqual(before.splitlines()[0], text.splitlines()[0])
        job = doc["jobs"]["detect"]
        self.assertEqual(job["strategy"]["max-parallel"], 2)
        self.assertEqual(job["timeout-minutes"], 55)
        self.assertEqual(job["runs-on"], ["ubuntu-22.04"])
        self.assertIn("refs/heads/release/stable", job["if"])

    def test_render_is_inert_deterministic_and_provider_scoped(self):
        from src.python import drift_workflow as workflow
        self.assertTrue(hasattr(workflow, "render"), "offline renderer required")
        for provider, action in (("aws", "aws-actions/configure-aws-credentials"), ("gcp", "google-github-actions/auth"), ("azure", "azure/login")):
            config = workflow.WorkflowConfig.from_dict(example(provider))
            files = workflow.render(config)
            self.assertEqual(files, workflow.render(config))
            self.assertEqual(set(files), {"drift-check.yml", "SETUP.md"})
            text = files["drift-check.yml"]
            doc = yaml.safe_load(text)
            self.assertEqual(doc["on"], {"workflow_dispatch": {}})
            self.assertEqual(doc["permissions"], {"contents": "read"})
            job = doc["jobs"]["detect"]
            self.assertEqual(job["permissions"], {"contents": "read", "id-token": "write"})
            self.assertFalse(job["concurrency"]["cancel-in-progress"])
            self.assertEqual(job["strategy"]["matrix"]["deployment"], ["gpu-a"])
            self.assertIn("github.ref == 'refs/heads/main'", job["if"])
            self.assertIn("github.repository == 'example/infrastructure'", job["if"])
            actions = [s["uses"] for s in job["steps"] if "uses" in s]
            self.assertTrue(any(a.startswith(action + "@") for a in actions))
            for ref in actions:
                self.assertRegex(ref, r"^[A-Za-z0-9_/-]+@[0-9a-f]{40}$")
            self.assertIn("./drift", text)
            for forbidden in ("pull_request", "workflow_run", "upload-artifact", "remediate", "continue-on-error", "secrets."):
                self.assertNotIn(forbidden, text)
            self.assertIn("UNVERIFIED", files["SETUP.md"])
            self.assertIn("trust anchor", files["SETUP.md"])
            self.assertIn("independent", files["SETUP.md"])

    def test_rejects_untrusted_or_incomplete_configuration(self):
        from src.python.drift_workflow import WorkflowConfig
        invalid = [None, [], {}, {**example(), "unknown": 1}]
        replacements = {
            "schema_version": [True, 2], "repository": ["owner/repo/extra", "evil${{ github.token }}", "owner/repo.git"],
            "protected_branch": ["refs/heads/main", "main;id", "a..b", "-main"],
            "source_revision": ["main", "a" * 39], "config_path": ["../x", "/tmp/x", "a/../x", "a//x", "a\\x", "a\nx", "${{ github.token }}"],
            "deployments": [[], ["x", "x"], ["--help"], ["a;id"]], "scopes": [[], ["all"], ["workstation", "workstation"]],
            "identity": [{}, {"role_arn": "$(id)", "region": "us-east-1"}, {**example()["identity"], "secret_access_key": "value"}],
            "provider": ["alicloud"], "runtime_image": ["ubuntu:latest", "image@sha256:" + "0" * 64 + ";id"],
            "terraform_version": ["latest", "1.9.8;id"], "namespace": ["a/b", "${{ x }}"], "backend_identity": ["../bad", "a:b"],
            "schedule": [{"enabled": "false"}, {"enabled": True, "cron_utc": "* * * * *"}, {"enabled": True, "cron_utc": "99 * * * *"}, {"enabled": False, "evil": True}],
            "runner_labels": [["self-hosted"], ["ubuntu-latest", "$(id)"], []],
            "notifications": ["issues", "external"], "correction_mode": ["manual_approval", "preauthorized_allowlist"],
            "timeout_minutes": [True, 0, 361], "max_parallel": [False, 0, 33],
        }
        for key, values in replacements.items():
            invalid.extend({**example(), key: value} for value in values)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                WorkflowConfig.from_dict(data)

    def test_valid_config_is_canonical_and_disabled_by_default(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.drift_workflow"), "workflow module must exist")
        from src.python.drift_workflow import WorkflowConfig
        data = example()
        config = WorkflowConfig.from_dict(data)
        data["deployments"].append("not-approved")
        self.assertEqual(config.to_dict()["deployments"], ["gpu-a"])
        self.assertFalse(config.to_dict()["schedule"]["enabled"])
        self.assertEqual(config.to_dict()["correction_mode"], "report_only")
        self.assertEqual(config.to_dict()["notifications"], "job_summary")
        self.assertEqual(config, WorkflowConfig.from_dict(config.to_dict()))


if __name__ == "__main__":
    unittest.main()
