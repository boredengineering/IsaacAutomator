#!/usr/bin/env python3
"""
Headless unit tests for isaac9s TUI application using Textual Pilot
"""
import unittest
from textual.pilot import Pilot
from textual.widgets import DataTable, RichLog

from src.tui.app import Isaac9sApp, TelemetryBanner
from src.tui.screens import (
    DoctorPane,
    HardwarePane,
    LogsPane,
    ProfilesPane,
    RemoteDesktopModal,
    SubsystemsPane,
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

            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, RemoteDesktopModal)

            # 6. Clean Quit
            await pilot.press("q")


if __name__ == "__main__":
    unittest.main()
