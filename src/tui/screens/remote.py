"""
Remote Desktop Protocol Selector Modal for isaac9s
"""
import webbrowser
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static


class RemoteDesktopModal(ModalScreen):
    """Modal dialog allowing the operator to select and launch remote desktop protocols."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
        Binding("1", "select_novnc", "noVNC", show=False),
        Binding("2", "select_nomachine", "NoMachine", show=False),
        Binding("3", "select_sunshine", "Sunshine", show=False),
        Binding("4", "select_ssh", "SSH", show=False),
    ]

    def __init__(self, workstation: dict = None):
        super().__init__()
        self.workstation = workstation or {
            "name": "workstation-01",
            "ip": "127.0.0.1",
            "cloud": "LOCAL",
        }
        self.selected_proto = "novnc"

    def compose(self) -> ComposeResult:
        ip = self.workstation.get("ip", "127.0.0.1")
        name = self.workstation.get("name", "workstation")

        with Vertical(id="dialog"):
            yield Label(f"Connect to Workstation: [bold cyan]{name}[/]", id="dialog-title")
            yield Static(
                "Select desired remote access protocol to launch or stream:",
                id="dialog-info",
            )

            with RadioSet(id="proto-select"):
                yield RadioButton("1. noVNC Browser Desktop (Port 6080) - HTML5 2D Web Desktop", value=True, id="rb-novnc")
                yield RadioButton("2. NoMachine High-Performance 3D (Port 4000) - 60 FPS Isaac Sim 3D Viewport", id="rb-nomachine")
                yield RadioButton("3. Sunshine + Moonlight GameStream (Port 47989) - Low Latency NVENC Teleop", id="rb-sunshine")
                yield RadioButton("4. Secure SSH Shell Tunnel (Port 22 / IAP / SSM) - Terminal Access", id="rb-ssh")

            yield Static(
                f"[bold white]Target Endpoint:[/] [cyan]http://{ip}:6080/vnc.html?autoconnect=true&resize=remote[/]\n"
                f"[bold white]Security Lock:[/]   [green]Strict /32 Caller IP Filter[/] (Simple Mode Active)",
                id="target-endpoint",
                classes="box-panel",
            )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Launch in Browser", id="btn-launch", variant="primary")
                yield Button("Copy Endpoint", id="btn-copy", variant="default")
                yield Button("Close (Esc)", id="btn-close", variant="error")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        ip = self.workstation.get("ip", "127.0.0.1")
        btn_id = event.pressed.id
        endpoint_widget = self.query_one("#target-endpoint", Static)

        if btn_id == "rb-novnc":
            self.selected_proto = "novnc"
            url = f"http://{ip}:6080/vnc.html?autoconnect=true&resize=remote"
            desc = "Zero-install HTML5 browser client. Ideal for 2D UI, terminal, and downloads."
        elif btn_id == "rb-nomachine":
            self.selected_proto = "nomachine"
            url = f"nx://{ip}:4000"
            desc = "Hardware-accelerated H.264 stream. Recommended for live 60 FPS Isaac Sim 3D Viewport."
        elif btn_id == "rb-sunshine":
            self.selected_proto = "sunshine"
            url = f"https://{ip}:47990"
            desc = "Ultra-low latency NVENC streaming (sub-15ms) for direct robot teleoperation."
        else:
            self.selected_proto = "ssh"
            url = f"ssh://ubuntu@{ip}:22"
            desc = "Interactive direct shell without opening public SSH ports."

        endpoint_widget.update(
            f"[bold white]Target Endpoint:[/] [cyan]{url}[/]\n"
            f"[bold white]Protocol Note:[/]   {desc}\n"
            f"[bold white]Security Lock:[/]   [green]Strict /32 Caller IP Filter[/]"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)
        elif event.button.id == "btn-launch":
            ip = self.workstation.get("ip", "127.0.0.1")
            if self.selected_proto == "novnc":
                webbrowser.open(f"http://{ip}:6080/vnc.html?autoconnect=true&resize=remote")
            elif self.selected_proto == "sunshine":
                webbrowser.open(f"https://{ip}:47990")
            self.dismiss(self.selected_proto)
        elif event.button.id == "btn-copy":
            self.dismiss(self.selected_proto)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_select_novnc(self) -> None:
        self.query_one("#rb-novnc", RadioButton).value = True

    def action_select_nomachine(self) -> None:
        self.query_one("#rb-nomachine", RadioButton).value = True

    def action_select_sunshine(self) -> None:
        self.query_one("#rb-sunshine", RadioButton).value = True

    def action_select_ssh(self) -> None:
        self.query_one("#rb-ssh", RadioButton).value = True
