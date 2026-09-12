"""Offline GCP generation tests: never authenticate or run Terraform/Ansible."""
import importlib.util
import json
import shlex
import tempfile
from contextlib import ExitStack
from itertools import product
from importlib.machinery import SourceFileLoader
from pathlib import Path
import unittest
from unittest import mock

import click
from click.testing import CliRunner


ROOT = Path(__file__).resolve().parents[2]


class FlexStartGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = SourceFileLoader("task31_deploy_gcp", str(ROOT / "deploy-gcp"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        cls.mod = importlib.util.module_from_spec(spec)
        with mock.patch("src.python.deploy_command.get_my_public_ip", return_value="192.0.2.1"), \
                mock.patch("src.python.utils.shell_command"):
            loader.exec_module(cls.mod)

    def deployer(self, **overrides):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # Keep the real metadata decision, validation, save and tfvars boundaries.
        obj = self.boundary_deployer(Path(temp.name), **overrides)
        for name in ("save_meta", "create_tfvars"):
            setattr(obj, name, mock.Mock(wraps=getattr(obj, name)))
        for name in ("initialize_terraform", "plan_terraform", "validate_ansible"):
            setattr(obj, name, mock.Mock())
        return obj

    def test_spot_and_flex_rejected_before_generation_or_login(self):
        obj = self.deployer(spot=True, flex_start=True)
        with mock.patch.object(self.mod, "gcp_login") as login, \
                mock.patch.object(self.mod, "shell_command") as shell:
            with self.assertRaisesRegex(click.ClickException, "Spot.*Flex-start|spot.*flex"):
                obj.main()
        obj.create_tfvars.assert_not_called()
        obj.save_meta.assert_not_called()
        login.assert_not_called()
        shell.assert_not_called()

    def invoke_controls(self, args, **overrides):
        obj = self.deployer(**overrides)
        def callback(**params):
            obj.params.update(params)
            obj.main()
        with mock.patch("src.python.deploy_command.get_my_public_ip", return_value="192.0.2.1"):
            cmd = self.mod.DeployGCPCommand("offline", callback=callback)
        cmd.params = [p for p in cmd.params if p.name in (
            "flex_start", "spot", "flex_max_run_seconds", "flex_create_timeout_seconds")]
        with mock.patch.object(self.mod, "gcp_login"), \
                mock.patch.object(self.mod, "shell_command", side_effect=AssertionError("No shell calls")):
            return CliRunner().invoke(cmd, args), obj

    def test_explicit_runtime_and_create_timeout_reach_generation(self):
        result, obj = self.invoke_controls([
            "--flex-start", "--flex-max-run-seconds", "600",
            "--flex-create-timeout-seconds", "7500"])
        self.assertEqual(result.exit_code, 0, result.output)
        values = obj.create_tfvars.call_args.args[0]
        self.assertEqual(values["flex_max_run_seconds"], 600)
        self.assertEqual(values["flex_create_timeout_seconds"], 7500)

    def test_profile_flex_does_not_silently_discard_spot(self):
        obj = self.deployer(spot=True, profile_spec={"enable_flex_start": True})
        with mock.patch.object(self.mod, "gcp_login"):
            with self.assertRaisesRegex(click.ClickException, "Spot.*Flex-start"):
                obj.main()

    def test_controls_are_bounded_and_require_flex(self):
        for flag, invalid in (("--flex-max-run-seconds", ("0", "604801", "1.5")),
                              ("--flex-create-timeout-seconds", ("0", "86401", "1.5"))):
            for value in invalid:
                with self.subTest(flag=flag, value=value):
                    result, obj = self.invoke_controls(["--flex-start", flag, value])
                    self.assertNotEqual(result.exit_code, 0)
                    obj.create_tfvars.assert_not_called()
            result, obj = self.invoke_controls([flag, "600"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("requires Flex-start", result.output)
            obj.create_tfvars.assert_not_called()

    def test_restored_values_cannot_bypass_bounds(self):
        for key in ("flex_max_run_seconds", "flex_create_timeout_seconds"):
            for value in (0, -1, True, 1.5, "600", 999999):
                with self.subTest(key=key, value=value):
                    obj = self.deployer(flex_start=True, **{key: value})
                    with self.assertRaises(click.ClickException):
                        obj.resolve_scheduling()

    def test_provider_version_is_pinned_to_verified_schema(self):
        self.assertRegex((ROOT / "src/terraform/gcp/main.tf").read_text(),
                         r'version\s*=\s*"= 8\.2\.0"')

    def test_flex_g4_rejects_incompatible_gpu_count(self):
        for machine, count in (("g4-standard-48", "8"), ("g4-standard-384", "2")):
            result, obj = self.invoke_controls(["--flex-start"],
                isaac_workstation_instance_type=machine, isaac_workstation_gpu_count=count)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("GPU count", result.output)
            obj.create_tfvars.assert_not_called()

    def test_g4_shapes_generate_exact_gpu_disk_and_flex_defaults(self):
        for machine, count in (("g4-standard-48", 1), ("g4-standard-384", 8)):
            result, obj = self.invoke_controls(["--flex-start"], isaac_workstation_instance_type=machine)
            self.assertEqual(result.exit_code, 0, result.output)
            values = obj.create_tfvars.call_args.args[0]
            self.assertEqual(values["isaac_workstation_gpu_count"], count)
            self.assertEqual(values["isaac_workstation_gpu_type"], "nvidia-rtx-pro-6000")
            self.assertEqual(values["boot_disk_type"], "hyperdisk-balanced")
            self.assertTrue(values["use_flex_start"])
            self.assertFalse(values["use_spot"])
            self.assertEqual(values["flex_max_run_seconds"], 604800)
            self.assertEqual(values["flex_create_timeout_seconds"], 3600)

    def test_standard_spot_and_explicit_no_flex_keep_defaults(self):
        for flags, profile in (([], {}), (["--spot"], {}),
                               (["--no-flex-start"], {"enable_flex_start": True})):
            result, obj = self.invoke_controls(flags, profile_spec=profile,
                                              isaac_workstation_instance_type="g2-standard-8")
            self.assertEqual(result.exit_code, 0, result.output)
            values = obj.create_tfvars.call_args.args[0]
            self.assertFalse(values["use_flex_start"])
            self.assertEqual(values["boot_disk_type"], "pd-ssd")
            self.assertEqual(values["use_spot"], flags == ["--spot"])
            self.assertNotIn("flex_max_run_seconds", values)
            self.assertNotIn("flex_create_timeout_seconds", values)

    def test_allocation_wait_is_not_misrepresented_as_supported(self):
        result, obj = self.invoke_controls(["--flex-start", "--flex-allocation-wait-seconds", "90"])
        self.assertNotEqual(result.exit_code, 0)
        obj.create_tfvars.assert_not_called()
        result, _ = self.invoke_controls(["--help"])
        self.assertIn("unsupported by the pinned Google provider", " ".join(result.output.split()))

    def test_conflict_is_rejected_before_project_discovery(self):
        obj = self.deployer(project=None, spot=True, flex_start=True)
        with mock.patch.object(self.mod, "shell_command") as shell, \
                mock.patch.object(click, "prompt", return_value="offline-project"):
            with self.assertRaisesRegex(click.ClickException, "Spot.*Flex-start"):
                obj.main()
        shell.assert_not_called()


    def boundary_deployer(self, root, **overrides):
        """Real construction, restoration, validation and local persistence."""
        params = dict(project="offline-project", zone="us-central1-a",
                      deployment_name="offline-flex", existing="modify",
                      isaac_workstation_instance_type="g4-standard-48",
                      isaac_workstation_gpu_count="auto", debug=False, dry_run=True,
                      flex_start=False, spot=False, in_china="no", profile="simple",
                      remote_desktop="no", demos="no", ingress_cidrs="192.0.2.1/32",
                      prefix="isa", ssh_port=22, isaacsim="no", isaaclab="no",
                      isaaclab_arena="no", isaaclab_private_git=False,
                      vnc_password="synthetic", system_user_password="synthetic")
        profile_spec = overrides.pop("profile_spec", None)
        params.update(overrides)
        obj = self.mod.GCPDeployer(params, dict(self.mod.config,
            state_dir=str(root / "state"), app_dir=str(ROOT),
            terraform_dir=str(root / "terraform")))
        if profile_spec is not None:
            obj.params["profile_spec"] = profile_spec
        return obj

    def test_standard_spot_and_default_flex_replay_omit_unset_durations(self):
        for flags in ([], ["--spot"], ["--flex-start"]):
            with self.subTest(flags=flags):
                result, original = self.invoke_controls(flags)
                self.assertEqual(result.exit_code, 0, result.output)
                # Parsed optional values are part of the original CLI inputs.
                original.input_params = {name: original.params.get(name) for name in (
                    "spot", "flex_start", "flex_max_run_seconds", "flex_create_timeout_seconds")}
                command = original.recreate_command_line(separator=" ")
                result, replayed = self.invoke_controls(shlex.split(command)[1:])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertNotIn("--flex-max-run-seconds", command)
                self.assertNotIn("--flex-create-timeout-seconds", command)
                self.assertEqual(replayed.create_tfvars.call_args, original.create_tfvars.call_args)

    def test_replay_omits_only_none_not_other_falsey_values(self):
        obj = self.deployer()
        obj.input_params = {"optional_count": None, "count": 0, "text": "", "flag": False}
        captured = {}
        command = click.Command("offline", callback=lambda **params: captured.update(params), params=[
            click.Option(["--optional-count"], type=int), click.Option(["--count"], type=int),
            click.Option(["--text"]), click.Option(["--flag/--no-flag"]),
        ])
        replay = obj.recreate_command_line(separator=" ")
        result = CliRunner().invoke(command, shlex.split(replay)[1:])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("--optional-count", replay)
        self.assertEqual(captured, obj.input_params)

    def test_repair_does_not_reinfer_saved_single_gpu_to_hide_incompatibility(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            original = self.boundary_deployer(root, flex_start=True,
                isaac_workstation_instance_type="g4-standard-384", isaac_workstation_gpu_count="1")
            original.save_meta()  # Synthetic incompatible saved configuration.
            path = root / "state/offline-flex/meta.json"
            before = path.read_bytes()
            repaired = self.boundary_deployer(root, existing="repair")
            stack.enter_context(mock.patch.object(self.mod, "gcp_login"))
            for name in ("initialize_terraform", "plan_terraform", "validate_ansible"):
                stack.enter_context(mock.patch.object(repaired, name))
            with self.assertRaisesRegex(click.ClickException, "GPU count"):
                repaired.main()
            self.assertEqual(path.read_bytes(), before)

    def test_repair_keeps_saved_explicit_no_flex_over_profile_default(self):
        for spot in (False, True):
            with self.subTest(spot=spot):
                result, original = self.invoke_controls(
                    ["--no-flex-start"] + (["--spot"] if spot else []),
                    profile_spec={"enable_flex_start": True})
                self.assertEqual(result.exit_code, 0, result.output)
                root = Path(original.config["state_dir"]).parent
                path = root / "state/offline-flex/meta.json"
                self.assertFalse(json.loads(path.read_text())["params"]["flex_start"])
                before_tfvars = (path.parent / ".tfvars").read_bytes()
                repaired = self.boundary_deployer(root, existing="repair", flex_start=True)
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(self.mod, "gcp_login"))
                    for name in ("initialize_terraform", "plan_terraform", "validate_ansible"):
                        stack.enter_context(mock.patch.object(repaired, name))
                    repaired.main()
                saved = json.loads(path.read_text())["params"]
                self.assertFalse(saved["flex_start"])
                self.assertEqual(saved["spot"], spot)
                self.assertEqual((path.parent / ".tfvars").read_bytes(), before_tfvars)

    def test_invalid_resolved_replacement_preserves_metadata_before_any_effect(self):
        cases = (
            ({"spot": True, "flex_start": True}, "Spot.*Flex-start"),
            ({"flex_start": True, "flex_max_run_seconds": 604801}, "integer"),
            ({"flex_start": True, "flex_create_timeout_seconds": True}, "integer"),
            ({"flex_max_run_seconds": 600}, "requires Flex-start"),
            ({"flex_start": True, "isaac_workstation_gpu_count": "8"}, "GPU count"),
        )
        for behavior, backend in product(("replace", "modify", "repair", "ask"),
                                         ("local", "configured", "active")):
            for invalid, message in cases:
                with self.subTest(behavior=behavior, backend=backend, invalid=invalid), \
                        tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                    root = Path(tmp)
                    stack.enter_context(mock.patch.dict("os.environ", {}, clear=True))
                    stack.enter_context(mock.patch("subprocess.Popen", side_effect=AssertionError("No process")))
                    backend_params = {}
                    if backend != "local":
                        from src.python.terraform_backend import BackendSpec
                        spec = BackendSpec.from_dict({"backend": "gcs", "namespace": "tests",
                            "destination": {"bucket": "synthetic-state", "project": "backend-project",
                                            "prefix": "state"}}, cloud="gcp")
                        backend_params = dict(cloud="gcp", terraform_state=spec.to_dict(),
                            backend_runtime={"identity": spec.identity("offline-project", "offline-flex"),
                                "status": backend, "lineage": "synthetic-lineage" if backend == "active" else None})
                    original = self.boundary_deployer(root, **backend_params)
                    original.save_meta()
                    directory = root / "state/offline-flex"
                    (directory / ".tfvars").write_text("# original inputs\n")
                    (directory / ".tfstate").write_text("synthetic original state")
                    obj = self.boundary_deployer(root, existing=behavior, dry_run=False,
                        **backend_params, **({} if behavior == "repair" else invalid))
                    if behavior == "repair":
                        metadata = json.loads((directory / "meta.json").read_text())
                        metadata["params"].update(invalid)
                        (directory / "meta.json").write_text(json.dumps(metadata))
                    before = {p.name: p.read_bytes() for p in directory.iterdir()}
                    stack.enter_context(mock.patch.object(click, "prompt", return_value="replace"))
                    shell = stack.enter_context(mock.patch("src.python.deployer.shell_command"))
                    discovery = stack.enter_context(mock.patch.object(self.mod, "shell_command"))
                    login = stack.enter_context(mock.patch.object(self.mod, "gcp_login"))
                    runner = stack.enter_context(mock.patch.object(obj, "_terraform_operation"))
                    save = stack.enter_context(mock.patch.object(obj, "save_meta", wraps=obj.save_meta))
                    with self.assertRaisesRegex(click.ClickException, message):
                        obj.main()
                    save.assert_not_called()
                    obj.save_meta()  # Failure also fences a later attempted save.
                    self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
                    shell.assert_not_called()
                    discovery.assert_not_called()
                    login.assert_not_called()
                    runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
