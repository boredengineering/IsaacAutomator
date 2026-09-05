#!/usr/bin/env python3
"""
Headless unit tests for isaac9s TUI application using Textual Pilot
"""
import unittest
from textual.pilot import Pilot
from textual.widgets import Button, DataTable, Input, RichLog, TabbedContent

from src.tui.app import Isaac9sApp, TelemetryBanner
from src.tui.screens import (
    CloudAuthBridgeModal,
    DeployWorkstationModal,
    DoctorPane,
    HardwarePane,
    LogsPane,
    ProfilesPane,
    RemoteDesktopModal,
    SubsystemsPane,
    WorkstationInspectorModal,
    WorkstationsPane,
)


class Test_Isaac9sApp(unittest.IsolatedAsyncioTestCase):
    async def test_app_headless_mount_and_telemetry(self):
        app = Isaac9sApp()
        async with app.run_test() as pilot:
            # 1. Verify telemetry banner and main layout mounted
            self.assertEqual(len(app.query(TelemetryBanner)), 1)
            self.assertEqual(len(app.query(SubsystemsPane)), 1)
            self.assertEqual(len(app.query(WorkstationsPane)), 1)
            self.assertEqual(len(app.query(LogsPane)), 1)
            self.assertEqual(len(app.query(DoctorPane)), 1)
            self.assertEqual(len(app.query(ProfilesPane)), 1)
            self.assertEqual(len(app.query(HardwarePane)), 1)

            # 2. Verify sub-tables populated
            sub_table = app.query_one("#subsystems-table", DataTable)
            self.assertGreater(len(sub_table.rows), 0)

            # 3. Test Tab Switching
            await pilot.press("2")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-workstations")

            await pilot.press("3")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-logs")

            await pilot.press("4")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-doctor")

            await pilot.press("5")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-profiles")

            await pilot.press("6")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-hardware")

            await pilot.press("question_mark")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-help")

            await pilot.press("1")
            await pilot.pause()
            self.assertEqual(app.query_one("#main-tabs").active, "tab-subsystems")

            # 4. Test Hotkeys (Probe, Audit, Start, Stop, Refresh)
            await pilot.press("p")
            await pilot.pause()

            await pilot.press("r")
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()

            await pilot.press("x")
            await pilot.pause()

            # 5. Test Remote Desktop Modal Trigger & Dismiss
            await pilot.press("c")
            await pilot.pause()
            self.assertIsInstance(app.screen, RemoteDesktopModal)

            # Test modal protocol switching
            await pilot.press("2")
            await pilot.pause()
            self.assertEqual(app.screen.selected_proto, "nomachine")

            await pilot.press("4")
            await pilot.pause()
            self.assertEqual(app.screen.selected_proto, "ssh")

            # Dismiss modal
            await pilot.press("escape")
            await pilot.pause()
            # 6. Test Deploy Modal Trigger, Flex-start selection & Dismiss with 'q'
            await pilot.press("n")
            await pilot.pause()
            self.assertIsInstance(app.screen, DeployWorkstationModal)
            deploy_modal = app.screen
            self.assertEqual(deploy_modal.scheduling_model, "standard")

            # Select Flex-start option
            rb_flex = deploy_modal.query_one("#rb-sched-flex")
            rb_flex.value = True
            await pilot.pause()
            self.assertEqual(deploy_modal.scheduling_model, "flex")
            self.assertTrue(deploy_modal.use_flex_start)
            self.assertIn("Flex-start Active", deploy_modal.build_summary_text())

            await pilot.press("q")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, DeployWorkstationModal)

            # 7. Test Workstation Deep Inspector Trigger & Dismiss (with raw state / inline code and 'q')
            await pilot.press("i")
            await pilot.pause()
            self.assertIsInstance(app.screen, WorkstationInspectorModal)
            app.screen.toggle_state_view()
            self.assertTrue(app.screen.show_raw_state)
            # Verify 'q' closes inspector even when raw inline code is active
            await pilot.press("q")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, WorkstationInspectorModal)

            # 8. Test Cloud Auth Bridge Modal Trigger & Dismiss with 'q'
            await pilot.press("a")
            await pilot.pause()
            self.assertIsInstance(app.screen, CloudAuthBridgeModal)
            await pilot.press("q")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, CloudAuthBridgeModal)

            # 9. Test Command Palette Execution
            app.execute_command("ws")
            self.assertEqual(app.query_one("#main-tabs").active, "tab-workstations")
            app.execute_command("doc")
            self.assertEqual(app.query_one("#main-tabs").active, "tab-doctor")
            app.execute_command("sub")
            self.assertEqual(app.query_one("#main-tabs").active, "tab-subsystems")

            # 10. Test LogsPane Live Search, Filtering & Process Lifecycle Controls
            logs_pane = app.query_one("#pane-logs", LogsPane)
            logs_pane.write_line("Alpha Test Message")
            logs_pane.write_line("Beta Debug Message")
            log_input = app.query_one("#input-log-filter", Input)
            log_input.value = "Alpha"
            await pilot.pause()
            self.assertEqual(logs_pane.active_filter, "Alpha")

            # Process badge and cancel button state transitions
            logs_pane.set_proc_running(99999, "test-proc")
            self.assertFalse(logs_pane.query_one("#btn-cancel-proc", Button).disabled)
            badge_text = str(logs_pane.query_one("#proc-status-badge").render())
            self.assertIn("RUNNING", badge_text)

            logs_pane.set_proc_idle("IDLE")
            self.assertTrue(logs_pane.query_one("#btn-cancel-proc", Button).disabled)
            badge_text_idle = str(logs_pane.query_one("#proc-status-badge").render())
            self.assertIn("IDLE", badge_text_idle)

            # Test hotkey 'k' and command palette stop/kill
            await pilot.press("k")
            await pilot.pause()
            app.execute_command("kill")
            app.execute_command("stop")

            # 11. Test Doctor JSON Export
            doc_pane = app.query_one("#pane-doctor", DoctorPane)
            report_path = doc_pane.export_json()
            self.assertTrue(report_path.exists())

            # 12. Test Profiles YAML Export
            prof_pane = app.query_one("#pane-profiles", ProfilesPane)
            yaml_path = prof_pane.export_yaml()
            self.assertTrue(yaml_path.exists())

            # 13. Clean Quit
            await pilot.press("q")


if __name__ == "__main__":
    unittest.main()
