"""
Remote Desktop Protocol Selector Modal for isaac9s
"""
import shlex
import webbrowser
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static

from src.python.workstation_connection import (
    ProtocolEndpoint,
    WorkstationConnectionInfo,
    resolve_workstation_connection,
)


class RemoteDesktopModal(ModalScreen):
    """Modal dialog allowing the operator to select and launch remote desktop protocols."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
        Binding("q", "dismiss_modal", "Close", show=True),
        Binding("1", "select_novnc", "noVNC", show=False),
        Binding("2", "select_kasmvnc", "KasmVNC", show=False),
        Binding("3", "select_nomachine", "NoMachine", show=False),
        Binding("4", "select_sunshine", "Sunshine", show=False),
        Binding("5", "select_ssh", "SSH", show=False),
        Binding("6", "select_vscode", "VS Code", show=False),
    ]

    def __init__(self, workstation: dict = None):
        super().__init__()
        self.workstation = workstation or {
            "name": "workstation-01",
            "ip": "127.0.0.1",
            "cloud": "LOCAL",
        }
        self.selected_proto = "novnc"
        self.conn_info = self._resolve_conn_info()

    def _resolve_conn_info(self) -> WorkstationConnectionInfo:
        name = self.workstation.get("name", "workstation")
        if name and name != "local-workstation" and self.workstation.get("cloud") != "BARE-METAL":
            try:
                return resolve_workstation_connection(name)
            except Exception:
                pass

        cloud = str(self.workstation.get("cloud", "LOCAL")).lower()
        iap = bool(self.workstation.get("iap_enabled", False))
        return WorkstationConnectionInfo(
            name=name,
            cloud=cloud,
            instance_name=self.workstation.get("instance_name", ""),
            public_ip=self.workstation.get("public_ip", self.workstation.get("ip", "")),
            private_ip=self.workstation.get("private_ip", ""),
            iap_enabled=iap,
            oslogin_enabled=bool(self.workstation.get("oslogin_enabled", False)),
            project=self.workstation.get("project", ""),
            zone=self.workstation.get("zone", ""),
            security_profile=self.workstation.get("profile", "simple").lower(),
            security_posture_label=self.workstation.get("security_posture", ""),
        )

    def get_endpoint_info(self, proto: str) -> tuple[str, str]:
        ep = self.conn_info.get_protocol_endpoint(proto)
        return ep.target_endpoint, ep.desc

    def get_protocol_endpoint(self, proto: str) -> ProtocolEndpoint:
        return self.conn_info.get_protocol_endpoint(proto)

    def format_endpoint_markup(self, ep: ProtocolEndpoint) -> str:
        text = (
            f"[bold white]Target Endpoint:[/] [cyan]{ep.target_endpoint}[/]\n"
            f"[bold white]Protocol Note:[/]   {ep.desc}\n"
            f"[bold white]Security Lock:[/]   [green]{ep.security_lock}[/]"
        )
        if ep.warning:
            text += f"\n[bold red]Protocol Warning:[/] [yellow]{ep.warning}[/]"
        elif ep.requires_tunnel:
            text += f"\n[bold cyan]Tunnel Mode:[/]      [white]Cloud IAP TCP Forwarding required (Remote Port {ep.remote_port})[/]"
        return text

    def compose(self) -> ComposeResult:
        name = self.workstation.get("name", "workstation")
        ep = self.get_protocol_endpoint("novnc")

        with Vertical(id="dialog"):
            yield Label(f"Connect to Workstation: [bold cyan]{name}[/]", id="dialog-title")
            yield Static(
                "Select desired remote access protocol to launch or stream:",
                id="dialog-info",
            )

            with RadioSet(id="proto-select"):
                yield RadioButton("1. noVNC Browser Desktop (Port 6080) - HTML5 2D Web Desktop", value=True, id="rb-novnc")
                yield RadioButton("2. KasmVNC WebRTC Browser (Port 8444) - Fast Streaming & Native Clipboard [Recommended]", id="rb-kasmvnc")
                yield RadioButton("3. NoMachine High-Performance 3D (Port 4000) - 60 FPS Isaac Sim Viewport", id="rb-nomachine")
                yield RadioButton("4. Sunshine + Moonlight GameStream (Port 47989) - Low Latency NVENC Teleop", id="rb-sunshine")
                yield RadioButton("5. Secure SSH Shell Tunnel (Port 22 / IAP / SSM) - Terminal Access", id="rb-ssh")
                yield RadioButton("6. VS Code Remote-SSH Workspace (Port 22 / IAP) - Dev Container Ready", id="rb-vscode")

            yield Static(
                self.format_endpoint_markup(ep),
                id="target-endpoint",
                classes="box-panel",
            )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Launch / Connect", id="btn-launch", variant="primary")
                yield Button("Copy Endpoint", id="btn-copy", variant="default")
                yield Button("Close [Esc / q]", id="btn-close", variant="error")

    def update_proto(self, proto: str) -> None:
        self.selected_proto = proto
        ep = self.get_protocol_endpoint(proto)
        endpoint_widget = self.query_one("#target-endpoint", Static)
        endpoint_widget.update(self.format_endpoint_markup(ep))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        mapping = {
            "rb-novnc": "novnc",
            "rb-kasmvnc": "kasmvnc",
            "rb-nomachine": "nomachine",
            "rb-sunshine": "sunshine",
            "rb-ssh": "ssh",
            "rb-vscode": "vscode",
        }
        proto = mapping.get(event.pressed.id, "novnc")
        self.update_proto(proto)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)
        elif event.button.id == "btn-launch":
            ep = self.get_protocol_endpoint(self.selected_proto)
            if not ep.supported and ep.warning:
                self.notify(ep.warning, title="Protocol Incompatible", severity="error")
                return
            if self.selected_proto in ("novnc", "sunshine", "kasmvnc", "vscode") and not ep.requires_tunnel:
                webbrowser.open(ep.target_endpoint)
            self.dismiss(self.selected_proto)
        elif event.button.id == "btn-copy":
            ep = self.get_protocol_endpoint(self.selected_proto)
            if ep.requires_tunnel and ep.tunnel_command:
                copy_val = shlex.join(ep.tunnel_command)
            else:
                copy_val = ep.target_endpoint
            try:
                self.app.copy_to_clipboard(copy_val)
                self.notify(f"Copied: {copy_val}")
            except Exception:
                self.notify(f"Endpoint: {copy_val}")
            self.dismiss(self.selected_proto)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_select_novnc(self) -> None:
        self.query_one("#rb-novnc", RadioButton).value = True
        self.update_proto("novnc")

    def action_select_kasmvnc(self) -> None:
        self.query_one("#rb-kasmvnc", RadioButton).value = True
        self.update_proto("kasmvnc")

    def action_select_nomachine(self) -> None:
        self.query_one("#rb-nomachine", RadioButton).value = True
        self.update_proto("nomachine")

    def action_select_sunshine(self) -> None:
        self.query_one("#rb-sunshine", RadioButton).value = True
        self.update_proto("sunshine")

    def action_select_ssh(self) -> None:
        self.query_one("#rb-ssh", RadioButton).value = True
        self.update_proto("ssh")

    def action_select_vscode(self) -> None:
        self.query_one("#rb-vscode", RadioButton).value = True
        self.update_proto("vscode")
