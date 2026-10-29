import json
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from src.python.remote_diagnostics import probe_cloud_workstation


class WorkstationInspectorModal(ModalScreen):
    """Read-only workstation metadata and safe backend state inspection."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
        Binding("q", "dismiss_modal", "Close", show=True),
        Binding("c", "connect_workstation", "Connect", show=True),
        Binding("p", "run_live_probe", "Live Probe", show=True),
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
            "profile": "Simple (cost not estimated)",
            "path": "",
        }
        self.show_raw_state = False

    def get_state_content(self) -> str:
        # Controller inventory is already projected from the shared descriptor
        # schema. Never render raw Terraform outputs/params or secret references.
        summary = {key: self.workstation.get(key, "unknown") for key in
                   ("backend", "namespace", "attachment", "backend_access", "status")}
        summary["remote_execution"] = "blocked pending production gates"
        summary["vm_status"] = "unknown (state metadata is not a live VM probe)"
        return json.dumps(summary, indent=2)

    def compose(self) -> ComposeResult:
        name = self.workstation.get("name", "workstation")
        cloud = self.workstation.get("cloud", "UNKNOWN")
        status = self.workstation.get("status", "UNKNOWN")
        gpu = self.workstation.get("gpu", "N/A")
        ip = self.workstation.get("ip", "N/A")
        profile = self.workstation.get("profile", "Unknown")

        status_color = "green" if status in ('READY', 'PROVISIONED', 'RUNNING') else "yellow"
        with Vertical(id="dialog"):
            yield Label(f"Workstation Deep Inspector: [bold cyan]{name}[/]", id="dialog-title")

            with VerticalScroll(id="inspector-body"):
                yield Static(Text("STATE BACKEND (read-only)\n" + self.get_state_content()),
                             id="inspector-backend", classes="box-panel")
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
                    f"[bold white]LIFECYCLE[/]\n"
                    f"  Lifecycle State:  Unknown (not a live VM status check)\n\n"
                    f"[bold white]PHYSICAL AI COMPATIBILITY[/]\n"
                    f"  Isaac Sim:        6.0.1 Standalone Kit\n"
                    f"  Isaac Lab:        v3.0.0-beta2 (Omniverse Kit Compatible)\n"
                    f"  Remote Streaming: KasmVNC (Port 8444), noVNC (Port 6080), NoMachine (Port 4000), Sunshine (Port 47990), SSH (Port 22)",
                    id="inspector-details",
                    classes="box-panel",
                )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Connect [c]", id="btn-inspect-connect", variant="primary")
                yield Button("Live Probe [p]", id="btn-inspect-probe", variant="warning")
                yield Button("Safe State Summary [t]", id="btn-inspect-raw", variant="default")
                yield Button("Close [Esc / q]", id="btn-inspect-close", variant="error")

    def toggle_state_view(self) -> None:
        self.show_raw_state = not self.show_raw_state
        details = self.query_one("#inspector-details", Static)
        if self.show_raw_state:
            state_json = self.get_state_content()
            details.update(Text("Safe backend summary (no raw state):\n\n" + state_json))
        else:
            name = self.workstation.get("name", "workstation")
            cloud = self.workstation.get("cloud", "UNKNOWN")
            status = self.workstation.get("status", "UNKNOWN")
            gpu = self.workstation.get("gpu", "N/A")
            ip = self.workstation.get("ip", "N/A")
            profile = self.workstation.get("profile", "Unknown")
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
                f"[bold white]LIFECYCLE[/]\n"
                f"  Lifecycle State:  Unknown (not a live VM status check)"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-inspect-close":
            self.dismiss(None)
        elif event.button.id == "btn-inspect-connect":
            self.dismiss("connect")
        elif event.button.id == "btn-inspect-probe":
            self.action_run_live_probe()
        elif event.button.id == "btn-inspect-raw":
            self.toggle_state_view()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_connect_workstation(self) -> None:
        self.dismiss("connect")

    def action_toggle_raw_state(self) -> None:
        self.toggle_state_view()

    def action_run_live_probe(self) -> None:
        name = self.workstation.get("name", "")
        if not name or name == "local-workstation" or self.workstation.get("cloud") == "BARE-METAL":
            self.notify("Live cloud probe requires a deployed cloud workstation.", severity="warning")
            return
        
        details = self.query_one("#inspector-details", Static)
        details.update(f"[bold yellow]Running non-invasive live probe on {name}...[/]")
        self.run_worker(self._async_live_probe(name), exclusive=True)

    async def _async_live_probe(self, name: str) -> None:
        import asyncio
        loop = asyncio.get_running_loop()
        try:
            report = await loop.run_in_executor(None, probe_cloud_workstation, name)
            details = self.query_one("#inspector-details", Static)
            
            repo_lines = []
            for rname, rinfo in report.get("repositories", {}).items():
                repo_lines.append(f"    • [cyan]{rname}[/]: branch=[bold green]{rinfo.get('branch')}[/] ({rinfo.get('commit')})")
            repo_text = "\n".join(repo_lines) if repo_lines else "    None detected"

            services = report.get("services", {})
            serv_text = f"KasmVNC: [green]{services.get('kasmvnc')}[/] | Docker: [green]{services.get('docker')}[/] | Display: [green]{services.get('display_manager')}[/]"
            ports_text = ", ".join(report.get("listening_ports", []))

            markup = (
                f"[bold green]LIVE WORKSTATION DIAGNOSTICS & TELEMETRY ({report.get('hostname')})[/]\n"
                f"  OS / Kernel:      [white]{report.get('os')}[/] ([dim]{report.get('kernel')}[/])\n"
                f"  Uptime:           [cyan]{report.get('uptime')}[/]\n"
                f"  GPU Hardware:     [bold yellow]{report.get('gpu')}[/]\n"
                f"  System Services:  {serv_text}\n"
                f"  Listening Ports:  [white]{ports_text}[/]\n\n"
                f"[bold white]PHYSICAL AI STACK[/]\n"
                f"  Isaac Sim:        [green]Installed[/] at [cyan]{report.get('isaac_sim', {}).get('path')}[/] (v{report.get('isaac_sim', {}).get('version')})\n"
                f"  Isaac Lab:        Conda env=[green]{report.get('isaac_lab', {}).get('conda_environment')}[/], Shim=[green]{report.get('isaac_lab', {}).get('shim_present')}[/]\n\n"
                f"[bold white]WORKSPACE REPOSITORIES & ACTIVE BRANCHES[/]\n"
                f"{repo_text}"
            )
            details.update(markup)
            self.notify(f"Live probe completed for {name}", title="Probe Success", severity="information")
        except Exception as err:
            details = self.query_one("#inspector-details", Static)
            details.update(f"[bold red]Probe failed:[/] {err}")
            self.notify(f"Probe failed: {err}", title="Probe Error", severity="error")
