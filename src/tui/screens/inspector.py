"""
Workstation Deep Inspector Modal for isaac9s
"""
import json
from pathlib import Path
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from src.tui.backend import REPO_ROOT


class WorkstationInspectorModal(ModalScreen):
    """Deep inspection modal displaying cloud metadata, networking, burn rate, and state."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
        Binding("c", "connect_workstation", "Connect", show=True),
        Binding("s", "start_workstation", "Start", show=False),
        Binding("x", "stop_workstation", "Stop", show=False),
        Binding("t", "toggle_raw_state", "Toggle State", show=False),
    ]

    def __init__(self, workstation: dict = None):
        super().__init__()
        self.workstation = workstation or {
            "name": "local-workstation",
            "cloud": "BARE-METAL",
            "status": "READY",
            "gpu": "Physical Host",
            "ip": "127.0.0.1",
            "profile": "Simple ($0/mo)",
            "path": "",
        }
        self.show_raw_state = False

    def get_cost_estimate(self) -> tuple[str, str]:
        gpu = self.workstation.get("gpu", "").lower()
        cloud = self.workstation.get("cloud", "").upper()

        if cloud == "BARE-METAL" or cloud == "LOCAL":
            return "$0.00 / hr", "On-Premise Physical Node"
        elif "g5." in gpu or "a10g" in gpu:
            return "~$1.21 / hr", "AWS EC2 GPU Instance"
        elif "g2-" in gpu or "l4" in gpu:
            return "~$0.85 / hr", "GCP Compute Engine GPU Instance"
        elif "nc" in gpu or "t4" in gpu:
            return "~$0.75 / hr", "Azure NC-series GPU Instance"
        elif "gn7i" in gpu:
            return "~$1.15 / hr", "Alibaba Cloud GPU Instance"
        return "~$0.95 / hr", "Cloud GPU Instance"

    def get_state_content(self) -> str:
        path_str = self.workstation.get("path")
        if not path_str:
            return "No persistent cloud state file found (Local bare-metal node)."

        ws_dir = Path(path_str)
        tfstate = ws_dir / ".tfstate"
        meta = ws_dir / "meta.json"

        summary = {}
        if meta.exists():
            try:
                with open(meta) as f:
                    summary["meta_params"] = json.load(f).get("params", {})
            except Exception as e:
                summary["meta_error"] = str(e)

        if tfstate.exists():
            try:
                with open(tfstate) as f:
                    raw_tf = json.load(f)
                    summary["outputs"] = raw_tf.get("outputs", {})
                    summary["resources_count"] = len(raw_tf.get("resources", []))
            except Exception as e:
                summary["tfstate_error"] = str(e)

        if not summary:
            return f"State directory: {ws_dir} (empty or unreadable state)"

        return json.dumps(summary, indent=2)

    def compose(self) -> ComposeResult:
        name = self.workstation.get("name", "workstation")
        cloud = self.workstation.get("cloud", "UNKNOWN")
        status = self.workstation.get("status", "UNKNOWN")
        gpu = self.workstation.get("gpu", "N/A")
        ip = self.workstation.get("ip", "N/A")
        profile = self.workstation.get("profile", "Simple ($0/mo)")
        rate, billing_desc = self.get_cost_estimate()

        status_color = "green" if status in ('READY', 'PROVISIONED', 'RUNNING') else "yellow"
        with Vertical(id="dialog"):
            yield Label(f"Workstation Deep Inspector: [bold cyan]{name}[/]", id="dialog-title")

            with VerticalScroll(id="inspector-body"):
                yield Static(
                    f"[bold white]GENERAL METADATA[/]\n"
                    f"  Name:             [cyan]{name}[/]\n"
                    f"  Provider / Cloud: [yellow]{cloud}[/]\n"
                    f"  Status:           [{status_color}][bold]{status}[/][/]\n"
                    f"  GPU / Instance:   [white]{gpu}[/]\n\n"
                    f"[bold white]CLOUD NETWORKING & TOPOLOGY[/]\n"
                    f"  Public Endpoint:  [cyan]{ip}[/]\n"
                    f"  Security Tier:    [green]{profile}[/]\n"
                    f"  Ingress Filter:   Strict /32 Caller IP Filter (Zero Public Exposure)\n\n"
                    f"[bold white]BILLING & RUNTIME TELEMETRY[/]\n"
                    f"  Estimated Rate:   [yellow]{rate}[/]\n"
                    f"  Billing Category: {billing_desc}\n"
                    f"  Lifecycle State:  {'Active Cost Accumulation' if status in ('PROVISIONED', 'RUNNING') else 'Cost Paused (Storage Only)'}\n\n"
                    f"[bold white]PHYSICAL AI COMPATIBILITY[/]\n"
                    f"  Isaac Sim:        6.0.1 Standalone Kit\n"
                    f"  Isaac Lab:        v3.0.0-beta2 (Omniverse Kit Compatible)\n"
                    f"  Remote Streaming: noVNC (Port 6080), NoMachine (Port 4000), Sunshine (Port 47990), SSH (Port 22)",
                    id="inspector-details",
                    classes="box-panel",
                )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Connect [c]", id="btn-inspect-connect", variant="primary")
                yield Button("Toggle Raw State [t]", id="btn-inspect-raw", variant="default")
                yield Button("Close (Esc)", id="btn-inspect-close", variant="error")

    def toggle_state_view(self) -> None:
        self.show_raw_state = not self.show_raw_state
        details = self.query_one("#inspector-details", Static)
        if self.show_raw_state:
            state_json = self.get_state_content()
            details.update(f"[bold cyan]Raw Terraform & Meta State:[/]\n\n{state_json}")
        else:
            name = self.workstation.get("name", "workstation")
            cloud = self.workstation.get("cloud", "UNKNOWN")
            status = self.workstation.get("status", "UNKNOWN")
            gpu = self.workstation.get("gpu", "N/A")
            ip = self.workstation.get("ip", "N/A")
            profile = self.workstation.get("profile", "Simple ($0/mo)")
            rate, billing_desc = self.get_cost_estimate()
            details.update(
                f"[bold white]GENERAL METADATA[/]\n"
                f"  Name:             [cyan]{name}[/]\n"
                f"  Provider / Cloud: [yellow]{cloud}[/]\n"
                f"  Status:           [bold]{status}[/]\n"
                f"  GPU / Instance:   [white]{gpu}[/]\n\n"
                f"[bold white]CLOUD NETWORKING & TOPOLOGY[/]\n"
                f"  Public Endpoint:  [cyan]{ip}[/]\n"
                f"  Security Tier:    [green]{profile}[/]\n"
                f"  Ingress Filter:   Strict /32 Caller IP Filter\n\n"
                f"[bold white]BILLING & RUNTIME TELEMETRY[/]\n"
                f"  Estimated Rate:   [yellow]{rate}[/]\n"
                f"  Billing Category: {billing_desc}"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-inspect-close":
            self.dismiss(None)
        elif event.button.id == "btn-inspect-connect":
            self.dismiss("connect")
        elif event.button.id == "btn-inspect-raw":
            self.toggle_state_view()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_connect_workstation(self) -> None:
        self.dismiss("connect")

    def action_toggle_raw_state(self) -> None:
        self.toggle_state_view()
