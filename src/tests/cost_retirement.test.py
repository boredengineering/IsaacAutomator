"""Offline regression contracts for retirement of the optional costing runtime."""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import gc
import json
import runpy
import tempfile
import unittest
import warnings
from unittest import mock

from textual.app import App
from textual.widgets import Button, Checkbox, Input, RadioButton, Select, Static


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def no_external_operations():
    """Allow real offline backend workers, never cloud/pricing or deploy calls."""
    with ExitStack() as stack:
        guards = [stack.enter_context(mock.patch(target, side_effect=AssertionError(
            "Unexpected external operation"))) for target in
            ("subprocess.run", "webbrowser.open", "socket.socket.connect")]
        yield
        for guard in guards:
            guard.assert_not_called()


def assert_no_cost_controls(test, owner):
    for widget in owner.query("*"):
        test.assertNotIn("cost", widget.id or "")
        test.assertNotEqual(type(widget).__name__, "CostEstimatePanel")
    for binding in owner.BINDINGS:
        test.assertNotIn("cost", binding.action)
    for widget in owner.query("Static, RadioButton, Checkbox"):
        text = str(widget.render()).lower()
        test.assertNotIn("input required below", text)
        test.assertNotIn("hcl/plan input below", text)
        test.assertNotRegex(text, r"\$\d")


@contextmanager
def offline_app_boundaries():
    """Keep the existing production-app smoke offline, with isolated exports."""
    def unauthenticated(modal):
        modal.aws_detail = "Not checked (offline test)"
        modal.aws_arn = modal.gcp_account = modal.gcp_project = ""
        modal.has_adc = False
        return {"aws": False, "gcp": False}

    stats = {"hostname": "offline-test", "os": "test", "cpu_percent": 0,
             "cpu_count": 1, "mem_used_gb": 0, "mem_total_gb": 1,
             "mem_percent": 0, "disk_percent": 0, "gpus": []}
    with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
        stack.enter_context(no_external_operations())
        stack.enter_context(mock.patch("src.tui.app.load_deployment_inventory", return_value=[]))
        stack.enter_context(mock.patch("src.tui.backend.WorkstationBackend.probe_subsystems", return_value=[
            {"name": "Offline fixture", "status": "PENDING", "category": "Test", "details": "Not probed"}]))
        stack.enter_context(mock.patch("src.tui.telemetry.SystemTelemetry.get_system_summary", return_value=stats))
        stack.enter_context(mock.patch("src.tui.screens.doctor.DoctorPane.refresh_doctor"))
        stack.enter_context(mock.patch("src.tui.screens.auth_modal.CloudAuthBridgeModal.check_auth_sync", unauthenticated))
        stack.enter_context(mock.patch("src.python.config.list_available_profiles", return_value={}))
        for module in ("profiles", "doctor"):
            stack.enter_context(mock.patch(f"src.tui.screens.{module}.REPO_ROOT", Path(root)))
        guards = [stack.enter_context(mock.patch(target, side_effect=AssertionError(
            "Unexpected deployment dispatch"))) for target in
            ("src.tui.app.Isaac9sApp.run_async_command", "src.tui.app.prepare_deployment_command")]
        yield
        for guard in guards:
            guard.assert_not_called()


class CostRuntimeRetirementTests(unittest.TestCase):
    def test_retired_widget_and_runtime_references_are_absent_from_active_code(self):
        self.assertFalse((ROOT / "src/tui/widgets/cost_estimate.py").exists())
        for directory in ("src/python", "src/tui", "scripts"):
            for path in (ROOT / directory).rglob("*.py"):
                with self.subTest(path=str(path.relative_to(ROOT))):
                    source = path.read_text().lower()
                    for retired in ("infracost", "cost_estimate", "cost_command", "costestimatepanel"):
                        self.assertNotIn(retired, source)

    def test_optional_runtime_entrypoints_and_packaging_are_removed(self):
        for relative in ("cost", "src/python/cost_command.py", "src/python/cost_estimate.py",
                         "scripts/install_infracost.py"):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists(), f"Retired runtime still present: {relative}")
        for relative in ("Dockerfile", "requirements-tui.txt", "build", "run"):
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text().lower()
                self.assertNotIn("infracost", source)
                self.assertNotIn("configs/cost/runtime.json", source)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WITH_PACKER=1", dockerfile)
        self.assertIn("apt-get install -qy terraform", dockerfile)
        self.assertIn("ENV TF_DATA_DIR=/opt/tf-data", dockerfile)


class CostUIRetirementTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_production_app_smoke_without_cost_runtime(self):
        # Reuse the unchanged existing navigation/lifecycle/modal smoke rather
        # than duplicate it or allow its discovery and exports on the real host.
        suite = runpy.run_path(str(ROOT / "src/tests/isaac9s.test.py"))
        with offline_app_boundaries():
            await suite["Test_Isaac9sApp"].test_app_headless_mount_and_telemetry(self)

    async def test_backend_worker_cancellation_still_does_not_leak_coroutines(self):
        from src.tui.screens.deploy_modal import DeployWorkstationModal
        from src.tui.screens.profiles import ProfilesPane

        class ProfileApp(App):
            def compose(self):
                yield ProfilesPane()

        with warnings.catch_warnings(record=True) as caught, no_external_operations(), mock.patch(
                "src.python.config.list_available_profiles", return_value={}):
            warnings.simplefilter("always", RuntimeWarning)
            app = App()
            async with app.run_test(size=(110, 60)) as pilot:
                modal = DeployWorkstationModal()
                app.push_screen(modal)
                await pilot.pause()
                for _ in range(4):
                    modal.start_backend_validation()
                await modal.backend_worker.wait()
                self.assertEqual(modal.effective_state_backend, "local")
                modal.start_backend_validation()
                modal.dismiss(None)
                await pilot.pause()
                gc.collect()
            app = ProfileApp()
            async with app.run_test(size=(110, 60)) as pilot:
                pane = app.query_one(ProfilesPane)
                button = pane.query_one("#btn-profile-backend-validate", Button)
                for _ in range(4):
                    pane.on_button_pressed(Button.Pressed(button))
                await pane.backend_worker.wait()
                self.assertIsNotNone(pane.validated_backend)
                pane.on_button_pressed(Button.Pressed(button))
                pane.invalidate_backend()
                await pilot.pause()
                gc.collect()
            gc.collect()
        self.assertEqual([str(w.message) for w in caught if "never awaited" in str(w.message)], [])

    async def test_inspector_preserves_safe_state_and_connect_without_cost_controls(self):
        from src.tui.screens.inspector import WorkstationInspectorModal

        class ScreenApp(App):
            CSS_PATH = str(ROOT / "src/tui/styles/isaac9s.tcss")

        with no_external_operations():
            app = ScreenApp()
            async with app.run_test(size=(110, 60)) as pilot:
                for cloud in ("GCP", "BARE-METAL"):
                    with self.subTest(cloud=cloud):
                        results = []
                        modal = WorkstationInspectorModal({"name": "offline-fixture", "cloud": cloud,
                            "status": "VM UNKNOWN", "gpu": "unknown", "ip": "N/A", "profile": "simple",
                            "backend": "local", "namespace": "team", "attachment": "present-unverified",
                            "backend_access": "unknown", "params": {"secret": "PRIVATE_SENTINEL"},
                            "terraform_outputs": {"password": "PRIVATE_SENTINEL"}})
                        app.push_screen(modal, results.append)
                        await pilot.pause()
                        assert_no_cost_controls(self, modal)
                        self.assertIn("Connect", modal.query_one("#btn-inspect-connect", Button).label.plain)
                        state = json.loads(modal.get_state_content())
                        self.assertEqual(state["backend"], "local")
                        self.assertIn("blocked", state["remote_execution"])
                        self.assertIn("unknown", state["vm_status"])
                        for _ in range(2):
                            shown = str(modal.query_one("#inspector-details", Static).render())
                            self.assertIn("offline-fixture", shown)
                            self.assertNotIn("Estimated Rate", shown)
                            self.assertNotIn("Billing Category", shown)
                            self.assertNotIn("PRIVATE_SENTINEL", shown)
                            await pilot.press("t")
                            self.assertTrue(modal.show_raw_state)
                            shown = str(modal.query_one("#inspector-details", Static).render())
                            self.assertIn("Safe backend summary", shown)
                            self.assertNotIn("PRIVATE_SENTINEL", shown)
                            await pilot.press("t")
                            self.assertFalse(modal.show_raw_state)
                        await pilot.press("c")
                        self.assertEqual(results, ["connect"])
                        self.assertNotIsInstance(app.screen, WorkstationInspectorModal)

    async def test_deployer_preserves_backend_gate_and_dryrun_payload_without_cost_controls(self):
        from src.tui.screens.deploy_modal import DeployWorkstationModal

        class ScreenApp(App):
            CSS_PATH = str(ROOT / "src/tui/styles/isaac9s.tcss")

        with tempfile.TemporaryDirectory() as root, no_external_operations(), mock.patch(
                "src.python.config.list_available_profiles", return_value={}):
            app = ScreenApp()
            results = []
            async with app.run_test(size=(110, 60)) as pilot:
                modal = DeployWorkstationModal()
                app.push_screen(modal, results.append)
                await pilot.pause()
                await modal.backend_worker.wait()
                assert_no_cost_controls(self, modal)
                self.assertEqual(modal.effective_state_backend, "local")
                self.assertFalse(modal.query_one("#btn-deploy-launch", Button).disabled)
                for selector, value in (("#sel-deploy-gpu", "g4-standard-48"),
                                        ("#rb-sched-flex", True), ("#rb-profile-team", True),
                                        ("#cb-demo-franka", False), ("#cb-demo-humanoid", True),
                                        ("#inp-deploy-name", "offline-workstation"),
                                        ("#inp-deploy-project", "example-project")):
                    modal.query_one(selector).value = value
                    await pilot.pause()
                await modal.backend_worker.wait()
                self.assertEqual(modal.scheduling_model, "flex")
                self.assertTrue(modal.use_flex_start)
                self.assertIn("./cycle-vm", modal.build_summary_text())
                self.assertEqual(modal.selected_zone, "us-central1-b")

                config = Path(root) / "backend.json"
                config.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                    "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
                modal.query_one("#sel-state-backend", Select).value = "gcs"
                modal.query_one("#inp-backend-config", Input).value = str(config)
                await pilot.pause()
                await modal.backend_worker.wait()
                self.assertEqual(modal.effective_state_backend, "gcs")
                self.assertTrue(modal.query_one("#btn-deploy-launch", Button).disabled)
                self.assertIn("BLOCKED", str(modal.query_one("#backend-status", Static).render()))
                modal.submit_deployment(dry_run=True)
                await pilot.pause()
                await modal.backend_worker.wait()
                self.assertEqual(results, [], "Remote intent must not dispatch even a dry run")

                modal.query_one("#sel-state-backend", Select).value = "local"
                modal.query_one("#inp-backend-config", Input).value = ""
                await pilot.pause()
                await modal.backend_worker.wait()
                self.assertFalse(modal.query_one("#btn-deploy-launch", Button).disabled)
                modal.submit_deployment(dry_run=True)
                await pilot.pause()
                self.assertEqual(results, [{"name": "offline-workstation", "cloud": "gcp",
                    "gpu": "g4-standard-48", "zone": "us-central1-b", "spot": False,
                    "flex_start": True, "profile": "team", "demos": ["humanoid-locomotion"],
                    "dry_run": True, "state_backend": "local", "backend_config": "",
                    "project": "example-project"}])

                # Provider changes still hide/reset GCP-only scheduling.
                modal = DeployWorkstationModal()
                app.push_screen(modal)
                await pilot.pause()
                modal.query_one("#rb-sched-flex", RadioButton).value = True
                await pilot.pause()
                modal.query_one("#rb-cloud-aws", RadioButton).value = True
                await pilot.pause()
                await modal.backend_worker.wait()
                self.assertEqual(modal.selected_cloud, "aws")
                self.assertEqual(modal.scheduling_model, "standard")
                self.assertFalse(modal.query_one("#rb-sched-flex").display)
                modal.query_one("#rb-sched-spot", RadioButton).value = True
                await pilot.pause()
                self.assertTrue(modal.use_spot)
                assert_no_cost_controls(self, modal)
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, DeployWorkstationModal)

    async def test_profiles_edit_and_export_intent_without_cost_controls(self):
        import yaml
        from src.python.config import load_profile_spec
        from src.python.workstation_profile import list_profiles, resolve_profile
        from src.tui.screens.profiles import ProfilesPane

        class ProfileApp(App):
            def compose(self):
                yield ProfilesPane()

        with tempfile.TemporaryDirectory() as root, no_external_operations(), mock.patch(
                "src.tui.screens.profiles.REPO_ROOT", Path(root)):
            app = ProfileApp()
            async with app.run_test(size=(110, 70)) as pilot:
                pane = app.query_one(ProfilesPane)
                assert_no_cost_controls(self, pane)
                ids = {button.id for button in pane.query_one("#rs-workstation-profile").query(RadioButton)}
                self.assertEqual(ids, {"p-" + name for name in list_profiles()})
                for name in list_profiles():
                    pane.query_one("#p-" + name, RadioButton).value = True
                    await pilot.pause()
                    self.assertEqual(pane.selected_profile, name)
                    self.assertFalse(resolve_profile(name)["ready_for_apply"])
                    summary = str(pane.query_one("#workstation-intent", Static).render()).lower()
                    self.assertIn(name, summary)
                    self.assertIn("not applied", summary)
                    self.assertIn("unsupported", summary)

                # Exercise all former cost-invalidation handlers, not just mount.
                pane.query_one("#tier-custom", RadioButton).value = True
                pane.query_one("#cb-custom-nat", Checkbox).value = False
                pane.query_one("#sel-profile-cloud", Select).value = "aws"
                await pilot.pause()
                self.assertEqual(pane.selected_tier, "custom")
                self.assertEqual(pane.selected_cloud, "aws")
                self.assertTrue(pane.query_one("#custom-config-container").display)
                assert_no_cost_controls(self, pane)

                config = Path(root) / "backend.json"
                config.write_text(json.dumps({"backend": "local"}))
                pane.query_one("#inp-profile-backend-config", Input).value = str(config)
                await pilot.pause()
                self.assertIsNone(pane.validated_backend)
                pane.query_one("#btn-profile-backend-validate", Button).press()
                await pilot.pause()
                await pane.backend_worker.wait()
                self.assertEqual(pane.validated_backend.backend, "local")
                for path in (pane.export_yaml(), pane.save_custom_profile_yaml()):
                    raw = yaml.safe_load(path.read_text())
                    self.assertEqual(raw["cloud"], "aws")
                    self.assertEqual(raw["workstation"]["base_profile"], pane.selected_profile)
                    self.assertFalse(raw["workstation"]["ready_for_apply"])
                    self.assertFalse(raw["workstation"]["apply_supported"])
                    self.assertNotIn("kind", raw)
                    self.assertEqual(load_profile_spec(str(path), repo_root=root)["terraform_state"]["backend"], "local")
                with mock.patch.object(pane, "notify") as notify:
                    pane.query_one("#btn-apply-profile", Button).press()
                    await pilot.pause()
                    self.assertIn("not applied", str(notify.call_args).lower())


if __name__ == "__main__":
    unittest.main()
