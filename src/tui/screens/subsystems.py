"""
Subsystems & Health Auditor Screen for isaac9s
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable
from rich.text import Text

from src.tui.backend import WorkstationBackend


class SubsystemsPane(Vertical):
    """Primary cockpit screen rendering the 14 Physical AI subsystems."""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-bar"):
            yield Button("Probe [p]", id="btn-probe", variant="primary")
            yield Button("Heal Drift [h]", id="btn-heal", variant="success")
            yield Button("Audit [a]", id="btn-audit", variant="warning")
            yield Button("Refresh [r]", id="btn-refresh-sub", variant="default")

        yield DataTable(id="subsystems-table")

    def on_mount(self) -> None:
        table = self.query_one("#subsystems-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Subsystem", "Status", "Category", "Operational Details")
        self.refresh_subsystems()

    def refresh_subsystems(self) -> None:
        table = self.query_one("#subsystems-table", DataTable)
        table.clear()
        subsystems = WorkstationBackend.probe_subsystems()

        for s in subsystems:
            status_color = {
                "PASS": "green",
                "WARN": "yellow",
                "FAIL": "red",
                "PENDING": "cyan"
            }.get(s["status"], "white")

            status_badge = f"[{status_color}][bold]{s['status']}[/][/]"
            table.add_row(
                s["name"],
                Text.from_markup(status_badge),
                s["category"],
                s["details"]
            )
