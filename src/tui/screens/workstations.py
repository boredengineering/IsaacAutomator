"""
Workstations & Multi-Cloud Fleet Screen for isaac9s
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable
from rich.text import Text

from src.tui.backend import WorkstationBackend


class WorkstationsPane(Vertical):
    """Multi-cloud workstation fleet and lifecycle management screen."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_vms: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-bar"):
            yield Button("Start VM [s]", id="btn-start-vm", variant="success")
            yield Button("Stop VM [x]", id="btn-stop-vm", variant="warning")
            yield Button("Connect [c]", id="btn-connect-vm", variant="primary")
            yield Button("Refresh [r]", id="btn-refresh-vms", variant="default")

        yield DataTable(id="workstations-table")

    def on_mount(self) -> None:
        table = self.query_one("#workstations-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Workstation", "Cloud", "Status", "GPU Model", "IP Address", "Security Profile")
        self.refresh_workstations()

    def refresh_workstations(self) -> None:
        table = self.query_one("#workstations-table", DataTable)
        table.clear()
        vms = WorkstationBackend.get_deployments()
        self.current_vms = vms

        if not vms:
            table.add_row(
                "local-workstation",
                "BARE-METAL",
                Text.from_markup("[green]READY[/]"),
                "Physical Host",
                "127.0.0.1",
                "Simple ($0/mo)"
            )
        else:
            for vm in vms:
                status_color = "green" if vm["status"] == "PROVISIONED" else "yellow"
                status_badge = f"[{status_color}][bold]{vm['status']}[/][/]"
                table.add_row(
                    vm["name"],
                    vm["cloud"],
                    Text.from_markup(status_badge),
                    vm["gpu"],
                    vm["ip"],
                    vm.get("profile", "Simple ($0/mo)")
                )

    def get_selected_workstation(self) -> dict:
        table = self.query_one("#workstations-table", DataTable)
        if not self.current_vms:
            return {"name": "local-workstation", "ip": "127.0.0.1", "cloud": "BARE-METAL"}

        try:
            row_idx = table.cursor_row
            if row_idx is not None and 0 <= row_idx < len(self.current_vms):
                return self.current_vms[row_idx]
        except Exception:
            pass
        return self.current_vms[0]
