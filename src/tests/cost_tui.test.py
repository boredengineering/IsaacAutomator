"""Offline cost UX contracts exercised with real headless Textual widgets."""
import asyncio
import gc
import importlib
import os
from pathlib import Path
import sys
import threading
import types
import tempfile
import unittest
import warnings
from contextlib import contextmanager, ExitStack
from unittest import mock

from textual.app import App
from textual.widgets import Button, Checkbox, Input, Select, Static


def panel_type():
    try:
        return importlib.import_module("src.tui.widgets.cost_estimate").CostEstimatePanel
    except ModuleNotFoundError:
        raise AssertionError("Reusable cost estimate panel is missing") from None


def fake_core(estimate):
    module = types.ModuleType("src.python.cost_estimate")
    module.estimate = estimate
    module.format_report = lambda report, format="table": report["text"]
    return mock.patch.dict(sys.modules, {"src.python.cost_estimate": module})


@contextmanager
def offline_app_boundaries(inventory=()):
    """Keep the production app mounted, but never discover/authenticate/dispatch.

    Backend validation still runs the real bounded offline selection worker.
    Also reusable when running the existing isaac9s.test.py smoke unchanged.
    """
    def unauthenticated(modal):
        modal.aws_detail = "Not checked (offline test)"
        modal.aws_arn = modal.gcp_account = modal.gcp_project = ""
        modal.has_adc = False
        return {"aws": False, "gcp": False}
    stats = {"hostname": "offline-test", "os": "test", "cpu_percent": 0,
             "cpu_count": 1, "mem_used_gb": 0, "mem_total_gb": 1,
             "mem_percent": 0, "disk_percent": 0, "gpus": []}
    with ExitStack() as stack:
        stack.enter_context(mock.patch("src.tui.app.load_deployment_inventory", return_value=list(inventory)))
        stack.enter_context(mock.patch("src.tui.backend.WorkstationBackend.probe_subsystems", return_value=[
            {"name": "Offline fixture", "status": "PENDING", "category": "Test", "details": "Not probed"}]))
        stack.enter_context(mock.patch("src.tui.telemetry.SystemTelemetry.get_system_summary", return_value=stats))
        stack.enter_context(mock.patch("src.tui.screens.doctor.DoctorPane.refresh_doctor"))
        stack.enter_context(mock.patch("src.tui.screens.auth_modal.CloudAuthBridgeModal.check_auth_sync", unauthenticated))
        stack.enter_context(mock.patch("src.python.config.list_available_profiles", return_value={}))
        guards = [stack.enter_context(mock.patch(target, side_effect=AssertionError("Unexpected external operation")))
                  for target in ("src.tui.app.Isaac9sApp.run_async_command", "src.tui.app.prepare_deployment_command",
                                 "subprocess.run", "webbrowser.open", "socket.socket.connect")]
        yield guards
        for guard in guards:
            guard.assert_not_called()


class CostPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_and_unmount_stop_real_offline_child_through_core_runner(self):
        core = importlib.import_module("src.python.cost_estimate")
        panel_cls = panel_type()
        class CostApp(App):
            def compose(self):
                yield panel_cls()
        for action in ("cancel", "unmount"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as root:
                processes, started, ended = [], threading.Event(), threading.Event()
                spawn = core.subprocess.Popen
                def observe(*args, **kwargs):
                    process = spawn(*args, **kwargs)
                    processes.append(process)
                    started.set()
                    return process
                def offline_estimate(**kwargs):
                    try:
                        core.run_process([sys.executable, "-c", "import time; time.sleep(60)"],
                                         cwd=root, environment={}, timeout=60,
                                         cancel_event=kwargs["cancel_event"])
                    finally:
                        ended.set()
                with mock.patch.object(core, "estimate", side_effect=offline_estimate), mock.patch.object(
                        core.subprocess, "Popen", side_effect=observe):
                    app = CostApp()
                    async with app.run_test(size=(110, 50)) as pilot:
                        panel = app.query_one(panel_cls)
                        panel.query_one("#inp-cost-path", Input).value = root
                        panel.query_one("#cb-cost-public", Checkbox).value = True
                        await pilot.pause()
                        await pilot.click("#btn-cost-estimate")
                        self.assertTrue(await asyncio.to_thread(started.wait, 3), "offline child never started")
                        if action == "cancel":
                            await pilot.click("#btn-cost-cancel")
                        else:
                            await panel.remove()
                        self.assertTrue(await asyncio.to_thread(ended.wait, 3), "UI cancellation did not stop child")
                        self.assertLess(processes[0].returncode, 0)
                        with self.assertRaises(ChildProcessError):
                            os.waitpid(processes[0].pid, os.WNOHANG)

    async def test_real_core_missing_input_is_reported_without_any_pricing_child(self):
        core = importlib.import_module("src.python.cost_estimate")
        adapter = importlib.import_module("src.tui.widgets.cost_estimate").estimate_text
        with tempfile.TemporaryDirectory() as root, mock.patch.object(
                core, "run_process", side_effect=AssertionError("unexpected pricing child")):
            text = await asyncio.to_thread(adapter, path=str(Path(root) / "absent"), cancel_event=threading.Event())
        self.assertIn("error", text.lower())
        self.assertIn("invalid_input", text)

    async def test_shared_formatter_details_preserve_provenance_and_unsupported_reason(self):
        import json
        panel_cls = panel_type()
        module = types.ModuleType("src.python.cost_estimate")
        module.estimate = lambda **kwargs: {"reason": "usage_binding_not_verified", "input_digest": "a" * 64}
        module.format_report = lambda report, format="table": (
            "Status: unsupported" if format == "table" else json.dumps(report))
        class CostApp(App):
            def compose(self):
                yield panel_cls()
        with mock.patch.dict(sys.modules, {"src.python.cost_estimate": module}):
            app = CostApp()
            async with app.run_test(size=(110, 50)) as pilot:
                panel = app.query_one(panel_cls)
                panel.query_one("#inp-cost-path", Input).value = "/tmp/hcl"
                panel.query_one("#cb-cost-public", Checkbox).value = True
                await pilot.pause()
                await pilot.click("#btn-cost-estimate")
                await panel.cost_worker.wait()
                text = str(panel.query_one("#cost-report", Static).render())
                self.assertIn("Status: unsupported", text)
                self.assertIn("usage_binding_not_verified", text)
                self.assertIn("a" * 64, text)

    async def test_public_input_and_external_pricing_require_acknowledgment(self):
        panel_cls = panel_type()
        estimate = mock.Mock(return_value={"text": "Public estimate"})
        class CostApp(App):
            def compose(self):
                yield panel_cls()
        with fake_core(estimate):
            app = CostApp()
            async with app.run_test(size=(110, 50)) as pilot:
                panel = app.query_one(panel_cls)
                panel.query_one("#inp-cost-path", Input).value = "/tmp/public-hcl"
                await pilot.pause()
                await pilot.click("#btn-cost-estimate")
                await pilot.pause()
                estimate.assert_not_called()
                consent = panel.query_one("#cb-cost-public", Checkbox)
                self.assertFalse(consent.value)
                consent.value = True
                await pilot.pause(0.5)
                await pilot.click("#btn-cost-estimate")
                await panel.cost_worker.wait()
                self.assertTrue(estimate.call_args.kwargs["public_input"])
                self.assertTrue(estimate.call_args.kwargs["allow_external_pricing"])

    async def test_input_changes_mark_stale_without_pricing_and_errors_are_safe(self):
        panel_cls = panel_type()
        estimate = mock.Mock(return_value={"text": "Partial estimate; unknown resources"})
        class CostApp(App):
            def compose(self):
                yield panel_cls()
        with fake_core(estimate):
            app = CostApp()
            async with app.run_test(size=(110, 50)) as pilot:
                panel = app.query_one(panel_cls)
                panel.query_one("#inp-cost-path", Input).value = "/tmp/hcl"
                panel.query_one("#cb-cost-public", Checkbox).value = True
                await pilot.pause()
                await pilot.click("#btn-cost-estimate")
                await panel.cost_worker.wait()
                for selector, value in (("#inp-cost-path", "/tmp/other"), ("#inp-cost-usage", "/tmp/usage")):
                    panel.query_one(selector, Input).value = value
                    await pilot.pause()
                    self.assertIn("stale", str(panel.query_one("#cost-status", Static).render()).lower())
                    self.assertNotIn("Partial estimate", str(panel.query_one("#cost-report", Static).render()))
                    self.assertEqual(estimate.call_count, 1)
                estimate.side_effect = RuntimeError("private-sentinel [red] raw error")
                await pilot.pause(0.5)
                await pilot.click("#btn-cost-estimate")
                await panel.cost_worker.wait()
                shown = str(panel.query_one("#cost-status", Static).render())
                self.assertIn("unavailable", shown.lower())
                self.assertNotIn("private-sentinel", shown)
                self.assertTrue(panel.query_one("#btn-cost-cancel", Button).disabled)

    async def test_cancel_refresh_and_unmount_discard_late_results(self):
        panel_cls = panel_type()
        calls, released = [], threading.Event()
        def estimate(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                released.wait(5)
                return {"text": "OLD RESULT MUST NOT RETURN"}
            return {"text": "NEW RESULT"}
        class CostApp(App):
            def compose(self):
                yield panel_cls()
        with fake_core(estimate):
            app = CostApp()
            try:
                async with app.run_test(size=(110, 50)) as pilot:
                    panel = app.query_one(panel_cls)
                    panel.query_one("#inp-cost-path", Input).value = "/tmp/plan.json"
                    panel.query_one("#sel-cost-source", Select).value = "plan"
                    panel.query_one("#cb-cost-public", Checkbox).value = True
                    await pilot.pause()
                    await pilot.click("#btn-cost-estimate")
                    await pilot.pause()
                    self.assertEqual(len(calls), 1)
                    self.assertFalse(panel.query_one("#btn-cost-cancel", Button).disabled)
                    await pilot.click("#btn-cost-cancel")
                    self.assertTrue(calls[0]["cancel_event"].is_set())
                    self.assertIn("cancel", str(panel.query_one("#cost-status", Static).render()).lower())
                    await pilot.pause(0.5)
                    await pilot.click("#btn-cost-estimate")
                    await panel.cost_worker.wait()
                    self.assertIsNone(calls[1]["path"])
                    self.assertEqual(calls[1]["saved_plan"], "/tmp/plan.json")
                    released.set()
                    await pilot.pause(0.1)
                    self.assertIn("NEW RESULT", str(panel.query_one("#cost-report", Static).render()))
                    self.assertNotIn("OLD RESULT", str(panel.query_one("#cost-report", Static).render()))
                    await panel.remove()
                    self.assertTrue(calls[1]["cancel_event"].is_set())
            finally:
                released.set()

    async def test_explicit_input_only_lazy_pricing_and_literal_report(self):
        panel_cls = panel_type()
        calls = []
        def estimate(**kwargs):
            calls.append(kwargs)
            return {"text": "[bold]literal resource[/bold]\nPartial: storage unknown"}
        class CostApp(App):
            def compose(self):
                yield panel_cls()
        with fake_core(estimate):
            app = CostApp()
            async with app.run_test(size=(110, 50)) as pilot:
                panel = app.query_one(panel_cls)
                self.assertEqual(calls, [])
                await pilot.click("#btn-cost-estimate")
                await pilot.pause()
                self.assertEqual(calls, [], "empty input must not invoke pricing")
                panel.query_one("#inp-cost-path", Input).value = "/tmp/explicit hcl"
                panel.query_one("#inp-cost-usage", Input).value = "/tmp/usage.yml"
                panel.query_one("#cb-cost-public", Checkbox).value = True
                await pilot.pause()
                self.assertEqual(calls, [], "input changes must not invoke pricing")
                await pilot.pause(0.5)
                await pilot.click("#btn-cost-estimate")
                await panel.cost_worker.wait()
                await pilot.pause()
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["path"], "/tmp/explicit hcl")
                self.assertIsNone(calls[0]["saved_plan"])
                self.assertEqual(calls[0]["usage_file"], "/tmp/usage.yml")
                self.assertIsInstance(calls[0]["cancel_event"], threading.Event)
                self.assertEqual(calls[0]["timeout"], 60)
                report = panel.query_one("#cost-report", Static)
                self.assertIn("[bold]literal resource[/bold]", str(report.render()))
                self.assertIn("explicit input only", str(panel.query_one("#cost-scope", Static).render()).lower())
                self.assertIn("not", str(panel.query_one("#cost-scope", Static).render()).lower())
                self.assertIn("usage assumptions", str(panel.query_one("#cost-scope", Static).render()).lower())
                self.assertNotIn("no assumed usage", panel.query_one("#inp-cost-usage", Input).placeholder)


class CostScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_app_profiles_and_modals_keep_pricing_explicit(self):
        import json
        from src.tui.app import Isaac9sApp
        from src.tui.screens import ProfilesPane, DeployWorkstationModal, WorkstationInspectorModal
        from textual.widgets import TabbedContent
        started, ended = threading.Event(), threading.Event()
        calls = []
        def estimate(**kwargs):
            calls.append(kwargs)
            started.set()
            kwargs["cancel_event"].wait(10)
            ended.set()
            return {"text": "Cancelled result must not appear"}
        async def click_reachable(pilot, widget):
            await pilot.wait_for_scheduled_animations()
            widget.scroll_visible(immediate=True)
            await pilot.pause()
            await pilot.wait_for_scheduled_animations()
            hit, _ = widget.app.get_widget_at(widget.region.x + 2, widget.region.y + 1)
            self.assertTrue(hit is widget or widget in hit.ancestors, f"Unreachable: {widget.id} (hit {hit})")
            await pilot.click(widget, offset=(2, 1))
        async def exercise_cost_panel(pilot, owner):
            panel = owner.query_one(panel_type())
            before = len(calls)
            consent = panel.query_one("#cb-cost-public", Checkbox)
            self.assertFalse(consent.value)
            path = panel.query_one("#inp-cost-path", Input)
            await click_reachable(pilot, path)
            path.value = "/tmp/explicit-public-hcl"
            await pilot.pause()
            button = panel.query_one("#btn-cost-estimate", Button)
            await click_reachable(pilot, button)
            self.assertEqual(len(calls), before, "Unchecked consent must block pricing")
            self.assertIn("acknowledge", str(panel.query_one("#cost-status", Static).render()).lower())
            await click_reachable(pilot, consent)
            self.assertTrue(consent.value)
            self.assertEqual(len(calls), before, "Consent alone must not start pricing")
            started.clear()
            ended.clear()
            await pilot.pause(0.5)
            await click_reachable(pilot, button)
            self.assertTrue(await asyncio.to_thread(started.wait, 3))
            self.assertEqual(len(calls), before + 1)
            self.assertTrue(calls[-1]["public_input"])
            self.assertTrue(calls[-1]["allow_external_pricing"])
            self.assertEqual(calls[-1]["path"], path.value)
            await click_reachable(pilot, panel.query_one("#btn-cost-cancel", Button))
            self.assertTrue(calls[-1]["cancel_event"].is_set())
            self.assertTrue(await asyncio.to_thread(ended.wait, 3))
            await pilot.pause()
            self.assertIn("cancel", str(panel.query_one("#cost-status", Static).render()).lower())
            self.assertNotIn("Cancelled result", str(panel.query_one("#cost-report", Static).render()))
            self.assertTrue(panel.query_one("#btn-cost-cancel", Button).disabled)
        inventory = [{"name": "offline-cloud-fixture", "cloud": "GCP", "status": "VM UNKNOWN",
                      "gpu": "unknown", "ip": "N/A", "attachment": "present-unverified"}]
        with tempfile.TemporaryDirectory() as root, offline_app_boundaries(inventory), fake_core(estimate):
            config = Path(root) / "backend.json"
            config.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            app = Isaac9sApp()
            async with app.run_test(size=(110, 50)) as pilot:
                await pilot.press("5")
                await pilot.pause()
                self.assertEqual(app.query_one("#main-tabs", TabbedContent).active, "tab-profiles")
                pane = app.query_one(ProfilesPane)
                selector = pane.query_one("#sel-profile-backend", Select)
                self.assertEqual(selector.value, "local")
                await click_reachable(pilot, selector)
                await pilot.press("home", "down", "enter")
                await pilot.pause()
                self.assertEqual(pane.selected_state_backend, "gcs")
                pane.query_one("#inp-profile-backend-config", Input).value = str(config)
                await pilot.pause()
                await click_reachable(pilot, pane.query_one("#btn-profile-backend-validate", Button))
                await pane.backend_worker.wait()
                self.assertEqual(pane.validated_backend.backend, "gcs")
                self.assertIn("BLOCKED", str(pane.query_one("#profile-backend-status", Static).render()))
                self.assertEqual(calls, [], "Mounting, navigation and backend changes must not price")
                await exercise_cost_panel(pilot, pane)

                app.action_open_deploy_modal()
                await pilot.pause()
                modal = app.screen
                self.assertIsInstance(modal, DeployWorkstationModal)
                await modal.backend_worker.wait()
                self.assertIsNone(modal.selected_state_backend)
                selector = modal.query_one("#sel-state-backend", Select)
                await click_reachable(pilot, selector)
                await pilot.press("home", "down", "down", "enter")
                await pilot.pause()
                self.assertEqual(modal.selected_state_backend, "gcs")
                modal.query_one("#inp-backend-config", Input).value = str(config)
                await pilot.pause()
                await modal.backend_worker.wait()
                self.assertEqual(modal.effective_state_backend, "gcs")
                self.assertTrue(modal.query_one("#btn-deploy-launch", Button).disabled)
                self.assertIn("BLOCKED", str(modal.query_one("#backend-status", Static).render()))
                self.assertEqual(len(calls), 1, "Opening deploy and changing backend must not price")
                await exercise_cost_panel(pilot, modal)
                await click_reachable(pilot, modal.query_one("#btn-deploy-cancel", Button))
                await pilot.pause()
                self.assertNotIsInstance(app.screen, DeployWorkstationModal)
                self.assertIsNone(app.backend_dispatch_worker)

                app.action_tab_workstations()
                await pilot.pause()
                app.action_open_inspector_modal()
                await pilot.pause()
                modal = app.screen
                self.assertIsInstance(modal, WorkstationInspectorModal)
                self.assertEqual(modal.workstation["name"], "offline-cloud-fixture")
                self.assertEqual(len(calls), 2, "Opening inspector must not price inventory")
                await exercise_cost_panel(pilot, modal)
                await click_reachable(pilot, modal.query_one("#btn-inspect-close", Button))
                await pilot.pause()
                self.assertNotIsInstance(app.screen, WorkstationInspectorModal)
                self.assertEqual(len(calls), 3)
                self.assertIsNone(app.active_proc)

    def test_sibling_cost_labels_do_not_claim_unestimated_prices(self):
        for filename in ("app.py", "backend.py", "screens/workstations.py"):
            with self.subTest(filename=filename):
                source = (Path("src/tui") / filename).read_text()
                self.assertNotRegex(source, r"\$\d")
                self.assertIn("cost not estimated", source.lower())

    async def test_cancel_before_worker_start_does_not_leak_coroutines(self):
        from src.tui.screens.deploy_modal import DeployWorkstationModal
        estimate = mock.Mock(return_value={"text": "Explicit estimate"})
        with warnings.catch_warnings(record=True) as caught, fake_core(estimate), mock.patch(
                "src.python.config.list_available_profiles", return_value={}):
            warnings.simplefilter("always", RuntimeWarning)
            app = App()
            async with app.run_test(size=(110, 60)) as pilot:
                modal = DeployWorkstationModal()
                app.push_screen(modal)
                await pilot.pause()
                panel = modal.query_one(panel_type())
                panel.query_one("#inp-cost-path", Input).value = "/tmp/hcl"
                panel.query_one("#cb-cost-public", Checkbox).value = True
                await pilot.pause()
                for _ in range(4):
                    modal.start_backend_validation()
                    panel.on_button_pressed(Button.Pressed(panel.query_one("#btn-cost-estimate", Button)))
                await modal.backend_worker.wait()
                await panel.cost_worker.wait()
                await pilot.pause()
                gc.collect()
            from src.tui.screens.profiles import ProfilesPane
            class ProfileApp(App):
                def compose(self):
                    yield ProfilesPane()
            app = ProfileApp()
            async with app.run_test(size=(110, 60)) as pilot:
                pane = app.query_one(ProfilesPane)
                button = pane.query_one("#btn-profile-backend-validate", Button)
                for _ in range(4):
                    pane.on_button_pressed(Button.Pressed(button))
                await pane.backend_worker.wait()
                self.assertIsNotNone(pane.validated_backend)
                pane.on_button_pressed(Button.Pressed(button))
                pane.invalidate_backend()  # Cancel before the coroutine can start.
                await pilot.pause()
                gc.collect()
            gc.collect()
        self.assertEqual([str(w.message) for w in caught if "never awaited" in str(w.message)], [])

    async def test_deploy_panel_context_is_stale_and_machine_labels_have_no_prices(self):
        from src.tui.screens.deploy_modal import DeployWorkstationModal
        panel_cls = panel_type()
        class ScreenApp(App):
            CSS_PATH = str(Path("src/tui/styles/isaac9s.tcss").resolve())
        estimate = mock.Mock(return_value={"text": "Standalone estimate"})
        with fake_core(estimate), mock.patch("src.python.config.list_available_profiles", return_value={}):
            app = ScreenApp()
            async with app.run_test(size=(110, 50)) as pilot:
                modal = DeployWorkstationModal()
                app.push_screen(modal)
                await pilot.pause()
                await modal.backend_worker.wait()
                self.assertEqual(len(modal.query(panel_cls)), 1, "Deployer has no cost panel")
                panel = modal.query_one(panel_cls)
                for selector, value in (("#sel-deploy-gpu", "g2-standard-4"),
                                        ("#rb-cloud-aws", True), ("#rb-profile-team", True),
                                        ("#rb-sched-spot", True), ("#cb-demo-franka", False),
                                        ("#inp-deploy-project", "explicit-public-project")):
                    panel.query_one("#cost-status", Static).update("Fresh sentinel")
                    modal.query_one(selector).value = value
                    await pilot.pause()
                    self.assertIn("stale", str(panel.query_one("#cost-status", Static).render()).lower())
                button = panel.query_one("#btn-cost-estimate", Button)
                button.scroll_visible(immediate=True)
                await pilot.pause()
                self.assertTrue(await pilot.click(button), "Cost button not reachable inside deployed stylesheet")
                estimate.assert_not_called()
                for options in modal.CLOUD_GPUS.values():
                    for label, value in options:
                        self.assertNotRegex(label, r"\$\d")
                self.assertNotRegex(modal.build_summary_text(), r"\$\d|\d+[-–]\d+%")
                for filename in ("profiles", "inspector", "deploy_modal"):
                    self.assertNotRegex(Path(f"src/tui/screens/{filename}.py").read_text(), r"\$\d|\b0\.95\b")
                modal.dismiss(None)

    async def test_inspector_cost_is_explicit_and_bare_metal_not_estimated(self):
        from src.tui.screens.inspector import WorkstationInspectorModal
        panel_cls = panel_type()
        estimate = mock.Mock(return_value={"text": "Explicit estimate"})
        class ScreenApp(App):
            CSS_PATH = str(Path("src/tui/styles/isaac9s.tcss").resolve())
        with fake_core(estimate):
            app = ScreenApp()
            async with app.run_test(size=(110, 50)) as pilot:
                for workstation in ({"cloud": "GCP", "gpu": "unknown"}, {"cloud": "BARE-METAL"}):
                    modal = WorkstationInspectorModal(workstation)
                    app.push_screen(modal)
                    await pilot.pause()
                    self.assertEqual(len(modal.query(panel_cls)), 1, "Inspector has no reachable panel")
                    self.assertNotRegex(str(modal.query_one("#inspector-details", Static).render()), r"\$\d")
                    panel = modal.query_one(panel_cls)
                    button = panel.query_one("#btn-cost-estimate", Button)
                    await pilot.wait_for_scheduled_animations()
                    button.scroll_visible(immediate=True)
                    await pilot.pause()
                    await pilot.wait_for_scheduled_animations()
                    self.assertGreater(button.region.height, 0)
                    if workstation["cloud"] == "BARE-METAL":
                        self.assertTrue(button.disabled)
                        self.assertIn("not estimated", str(panel.query_one("#cost-status", Static).render()).lower())
                    else:
                        self.assertFalse(button.disabled)
                        await pilot.click(button)
                    modal.dismiss(None)
                    await pilot.pause()
                estimate.assert_not_called()

    async def test_real_software_presets_are_intent_only_and_export_roundtrips(self):
        import yaml
        from src.python.workstation_profile import list_profiles, resolve_profile
        from src.python.config import load_profile_spec
        from src.tui.screens.profiles import ProfilesPane
        from textual.widgets import RadioButton
        class ProfileApp(App):
            def compose(self):
                yield ProfilesPane()
        with tempfile.TemporaryDirectory() as root, mock.patch("src.tui.screens.profiles.REPO_ROOT", Path(root)):
            app = ProfileApp()
            async with app.run_test(size=(110, 70)) as pilot:
                pane = app.query_one(ProfilesPane)
                self.assertIn(pane.selected_profile, list_profiles(), "UI uses nonexistent YAML presets")
                ids = {button.id for button in pane.query_one("#rs-workstation-profile").query(RadioButton)}
                self.assertEqual(ids, {"p-" + name for name in list_profiles()})
                for name in list_profiles():
                    pane.query_one("#p-" + name, RadioButton).value = True
                    await pilot.pause()
                    self.assertEqual(pane.selected_profile, name)
                    report = resolve_profile(name)
                    self.assertFalse(report["ready_for_apply"])
                    summary = str(pane.query_one("#workstation-intent", Static).render()).lower()
                    self.assertIn(name, summary)
                    self.assertIn("not applied", summary)
                    self.assertIn("unsupported", summary)
                for path in (pane.export_yaml(), pane.save_custom_profile_yaml()):
                    raw = yaml.safe_load(path.read_text())
                    self.assertEqual(raw["cloud"], "gcp")
                    self.assertEqual(raw["workstation"]["base_profile"], "minimal")
                    self.assertFalse(raw["workstation"]["ready_for_apply"])
                    self.assertFalse(raw["workstation"]["apply_supported"])
                    self.assertNotIn("kind", raw, "legacy config must not become a deployable workstation-profile")
                    loaded = load_profile_spec(str(path), repo_root=root)
                    self.assertEqual(loaded["terraform_state"]["backend"], "local")
                with mock.patch.object(pane, "notify") as notify:
                    pane.query_one("#btn-apply-profile", Button).press()
                    await pilot.pause()
                    self.assertIn("not applied", str(notify.call_args).lower())

    async def test_profile_backend_config_change_cancels_pending_and_stales_report(self):
        from src.tui.screens.profiles import ProfilesPane
        class ProfileApp(App):
            def compose(self):
                yield ProfilesPane()
        started, released, ended = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def estimate(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                started.set()
                released.wait(5)
                ended.set()
            return {"text": "Old backend context"}
        with fake_core(estimate):
            app = ProfileApp()
            try:
                async with app.run_test(size=(110, 70)) as pilot:
                    pane = app.query_one(ProfilesPane)
                    panel = pane.query_one(panel_type())
                    panel.query_one("#inp-cost-path", Input).value = "/tmp/public-hcl"
                    panel.query_one("#cb-cost-public", Checkbox).value = True
                    await pilot.pause()
                    button = panel.query_one("#btn-cost-estimate", Button)
                    button.scroll_visible(immediate=True)
                    await pilot.pause()
                    await pilot.click(button)
                    self.assertTrue(await asyncio.to_thread(started.wait, 3))
                    pane.query_one("#inp-profile-backend-config", Input).value = "/tmp/new-backend.yaml"
                    await pilot.pause()
                    self.assertTrue(calls[0]["cancel_event"].is_set())
                    self.assertIn("stale", str(panel.query_one("#cost-status", Static).render()).lower())
                    self.assertTrue(panel.query_one("#btn-cost-cancel", Button).disabled)
                    released.set()
                    self.assertTrue(await asyncio.to_thread(ended.wait, 3))
                    await pilot.pause()
                    self.assertNotIn("Old backend context", str(panel.query_one("#cost-report", Static).render()))
                    self.assertEqual(len(calls), 1)
                    await pilot.pause(0.5)  # Textual button activation cooldown.
                    await pilot.click(button)
                    await panel.cost_worker.wait()
                    self.assertIn("Old backend context", str(panel.query_one("#cost-report", Static).render()))
                    pane.query_one("#inp-profile-backend-config", Input).value = "/tmp/another-backend.yaml"
                    await pilot.pause()
                    self.assertIn("stale", str(panel.query_one("#cost-status", Static).render()).lower())
                    self.assertNotIn("Old backend context", str(panel.query_one("#cost-report", Static).render()))
                    self.assertEqual(len(calls), 2)
            finally:
                released.set()

    async def test_profiles_panel_marks_context_changes_stale_without_pricing(self):
        from src.tui.screens.profiles import ProfilesPane
        from textual.widgets import Checkbox, RadioButton
        panel_cls = panel_type()
        class ProfileApp(App):
            def compose(self):
                yield ProfilesPane()
        estimate = mock.Mock(return_value={"text": "Current explicit estimate"})
        with fake_core(estimate):
            app = ProfileApp()
            async with app.run_test(size=(110, 70)) as pilot:
                pane = app.query_one(ProfilesPane)
                self.assertEqual(len(pane.query(panel_cls)), 1, "Profiles has no reachable cost panel")
                panel = pane.query_one(panel_cls)
                for selector, value in (("#sel-profile-cloud", "aws"), ("#tier-custom", True),
                                        ("#cb-custom-nat", False), ("#p-full", True)):
                    panel.query_one("#cost-status", Static).update("Fresh sentinel")
                    pane.query_one(selector).value = value
                    await pilot.pause()
                    self.assertIn("stale", str(panel.query_one("#cost-status", Static).render()).lower())
                estimate.assert_not_called()
                for widget in pane.query("Static, RadioButton, Checkbox"):
                    self.assertNotRegex(str(widget.render()), r"\$\d", "hardcoded profile price remains")


if __name__ == "__main__":
    unittest.main()
