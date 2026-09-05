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
        Binding("q", "dismiss_modal", "Close", show=True),
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

    def get_endpoint_info(self, proto: str) -> tuple[str, str]:
        ip = self.workstation.get("ip", "127.0.0.1")
        valid_ip = ip and ip not in ("N/A", "None", "")
        host = ip if valid_ip else "127.0.0.1"

        if proto == "novnc":
            url = f"http://{host}:6080/vnc.html?autoconnect=true&resize=remote"
            desc = "Zero-install HTML5 browser client. Ideal for 2D UI, terminal, and file downloads."
        elif proto == "nomachine":
            url = f"nx://{host}:4000"
            desc = "Hardware-accelerated H.264 stream. Recommended for live 60 FPS Isaac Sim 3D Viewport."
        elif proto == "sunshine":
            url = f"https://{host}:47990"
            desc = "Ultra-low latency NVENC streaming (sub-15ms) for direct robot teleoperation."
        else:
            url = f"ssh://ubuntu@{host}:22"
            desc = "Interactive direct shell without opening public SSH ports."

        if not valid_ip:
            url += " (Pending IP assignment)"

        return url, desc

    def compose(self) -> ComposeResult:
        name = self.workstation.get("name", "workstation")
        url, desc = self.get_endpoint_info("novnc")

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
                f"[bold white]Target Endpoint:[/] [cyan]{url}[/]\n"
                f"[bold white]Protocol Note:[/]   {desc}\n"
                f"[bold white]Security Lock:[/]   [green]Strict /32 Caller IP Filter[/] (Simple Mode Active)",
                id="target-endpoint",
                classes="box-panel",
            )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Launch in Browser", id="btn-launch", variant="primary")
                yield Button("Copy Endpoint", id="btn-copy", variant="default")
                yield Button("Close [Esc / q]", id="btn-close", variant="error")

    def update_proto(self, proto: str) -> None:
        self.selected_proto = proto
        url, desc = self.get_endpoint_info(proto)
        endpoint_widget = self.query_one("#target-endpoint", Static)
        endpoint_widget.update(
            f"[bold white]Target Endpoint:[/] [cyan]{url}[/]\n"
            f"[bold white]Protocol Note:[/]   {desc}\n"
            f"[bold white]Security Lock:[/]   [green]Strict /32 Caller IP Filter[/]"
        )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        mapping = {
            "rb-novnc": "novnc",
            "rb-nomachine": "nomachine",
            "rb-sunshine": "sunshine",
            "rb-ssh": "ssh",
        }
        proto = mapping.get(event.pressed.id, "novnc")
        self.update_proto(proto)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)
        elif event.button.id == "btn-launch":
            ip = self.workstation.get("ip", "127.0.0.1")
            url, _ = self.get_endpoint_info(self.selected_proto)
            if self.selected_proto in ("novnc", "sunshine"):
                webbrowser.open(url)
            self.dismiss(self.selected_proto)
        elif event.button.id == "btn-copy":
            url, _ = self.get_endpoint_info(self.selected_proto)
            try:
                self.app.copy_to_clipboard(url)
                self.notify(f"Copied endpoint: {url}")
            except Exception:
                self.notify(f"Endpoint: {url}")
            self.dismiss(self.selected_proto)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_select_novnc(self) -> None:
        self.query_one("#rb-novnc", RadioButton).value = True
        self.update_proto("novnc")

    def action_select_nomachine(self) -> None:
        self.query_one("#rb-nomachine", RadioButton).value = True
        self.update_proto("nomachine")

    def action_select_sunshine(self) -> None:
        self.query_one("#rb-sunshine", RadioButton).value = True
        self.update_proto("sunshine")

    def action_select_ssh(self) -> None:
        self.query_one("#rb-ssh", RadioButton).value = True
        self.update_proto("ssh")
