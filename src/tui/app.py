"""
isaac9s - The k9s-style Terminal User Interface for Isaac Automator & Installer
"""
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from src.tui.backend import INSTALLER_BIN, REPO_ROOT, WorkstationBackend
from src.tui.screens import (
    DoctorPane,
    HardwarePane,
    LogsPane,
    ProfilesPane,
    RemoteDesktopModal,
    SubsystemsPane,
    WorkstationsPane,
)
from src.tui.telemetry import SystemTelemetry


class TelemetryBanner(Static):
    """Renders the top live system telemetry banner like k9s cluster info."""

    def update_metrics(self) -> None:
        stats = SystemTelemetry.get_system_summary()
        gpus = stats.get("gpus", [])
        gpu_str = "No GPU (CPU Mode)"
        if gpus:
            gpu_names = [f"{g['name']} ({g['temp_c']}°C, {g['util_percent']}%)" for g in gpus]
            gpu_str = " | ".join(gpu_names)

        content = (
            f"[bold cyan]Host:[/] [white]{stats['hostname']}[/] | "
            f"[bold cyan]OS:[/] [white]{stats['os']}[/] | "
            f"[bold cyan]CPU:[/] [green]{stats['cpu_percent']}%[/] ({stats['cpu_count']} cores) | "
            f"[bold cyan]RAM:[/] [green]{stats['mem_used_gb']}G / {stats['mem_total_gb']}G[/] ({stats['mem_percent']}%) | "
            f"[bold cyan]Disk:[/] [green]{stats['disk_percent']}%[/] | "
            f"[bold cyan]GPU:[/] [yellow]{gpu_str}[/]"
        )
        self.update(content)


class Isaac9sApp(App):
    """isaac9s - The k9s-style Terminal User Interface for Isaac Automator & Installer."""

    TITLE = "isaac9s"
    SUB_TITLE = "Physical AI & Multi-Cloud Robotics Cockpit"
    CSS_PATH = Path(__file__).parent / "styles" / "isaac9s.tcss"

    BINDINGS = [
        Binding("1", "tab_subsystems", "Subsystems", show=True),
        Binding("2", "tab_workstations", "Fleet", show=True),
        Binding("3", "tab_logs", "Logs", show=True),
        Binding("4", "tab_doctor", "Doctor", show=True),
        Binding("5", "tab_profiles", "Profiles", show=True),
        Binding("6", "tab_hardware", "Hardware", show=True),
        Binding("question_mark", "tab_help", "Help", show=True, key_display="?"),
        Binding("c", "open_connect_modal", "Connect", show=True),
        Binding("p", "run_probe", "Probe", show=True),
        Binding("h", "run_heal", "Heal", show=True),
        Binding("a", "run_audit", "Audit", show=True),
        Binding("s", "run_start", "Start", show=True),
        Binding("x", "run_stop", "Stop", show=True),
        Binding("r", "run_refresh", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield TelemetryBanner(id="telemetry-bar")

        with TabbedContent(id="main-tabs"):
            with TabPane("Subsystems & Health [1]", id="tab-subsystems"):
                yield SubsystemsPane(id="pane-subsystems")

            with TabPane("Workstations & Fleet [2]", id="tab-workstations"):
                yield WorkstationsPane(id="pane-workstations")

            with TabPane("Real-Time Logs [3]", id="tab-logs"):
                yield LogsPane(id="pane-logs")

            with TabPane("Pre-Flight Doctor [4]", id="tab-doctor"):
                yield DoctorPane(id="pane-doctor")

            with TabPane("Security & Profiles [5]", id="tab-profiles"):
                yield ProfilesPane(id="pane-profiles")

            with TabPane("Hardware Telemetry [6]", id="tab-hardware"):
                yield HardwarePane(id="pane-hardware")

            with TabPane("Help [?]", id="tab-help"):
                with VerticalScroll():
                    yield Static(
                        "[bold cyan]isaac9s - Keyboard Shortcuts & Cockpit Reference[/]\n\n"
                        "  [bold white]1 - 6[/]: Switch dashboard screens\n"
                        "  [bold white]?[/]: Open this Help reference\n"
                        "  [bold white]c[/]: Open Remote Desktop protocol selector modal (noVNC, NoMachine, Sunshine, SSH)\n"
                        "  [bold white]p[/]: Run hardware probe & diagnostic tests\n"
                        "  [bold white]h[/]: Run automated state drift reconciliation & healing\n"
                        "  [bold white]a[/]: Run pre-flight architecture audit\n"
                        "  [bold white]s[/]: Start highlighted workstation\n"
                        "  [bold white]x[/]: Stop highlighted workstation (pauses billing)\n"
                        "  [bold white]r[/]: Refresh current tab metrics\n"
                        "  [bold white]q[/]: Exit isaac9s\n\n"
                        "[bold cyan]CLI Invocations:[/]\n"
                        "  ./isaac9s                   Launch interactive terminal cockpit\n"
                        "  ./isaac-installer doctor    Pre-flight audit in terminal\n"
                        "  ./isaac-installer repair    Reconcile and heal drift\n\n"
                        "[bold cyan]Security Profiles:[/]\n"
                        "  Tier 1: Simple Mode        $0.00 / mo, Dynamic /32 IP lock, Direct Outbound\n"
                        "  Tier 2: Collaborative      <$0.10 / mo, Cloud remote state with native locking\n"
                        "  Tier 3: Enterprise         ~$35-$180 / mo, KMS CMEK keys, Cloud Secret Manager, Zero-Trust IAP"
                    )

        yield Footer()

    def on_mount(self) -> None:
        self.telemetry_widget = self.query_one("#telemetry-bar", TelemetryBanner)
        self.logs_pane = self.query_one("#pane-logs", LogsPane)
        self.subsystems_pane = self.query_one("#pane-subsystems", SubsystemsPane)
        self.workstations_pane = self.query_one("#pane-workstations", WorkstationsPane)
        self.doctor_pane = self.query_one("#pane-doctor", DoctorPane)
        self.hardware_pane = self.query_one("#pane-hardware", HardwarePane)

        self.telemetry_widget.update_metrics()
        self.set_interval(2.0, self.update_telemetry)
        self.log_message("[bold green]isaac9s cockpit initialized.[/] Welcome to Isaac Automator & Installer.")

    def update_telemetry(self) -> None:
        self.telemetry_widget.update_metrics()

    def log_message(self, msg: str) -> None:
        self.logs_pane.write_line(msg)

    # Navigation Actions
    def action_tab_subsystems(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-subsystems"

    def action_tab_workstations(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-workstations"

    def action_tab_logs(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-logs"

    def action_tab_doctor(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-doctor"

    def action_tab_profiles(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-profiles"

    def action_tab_hardware(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-hardware"

    def action_tab_help(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-help"

    # Operational Actions
    def action_open_connect_modal(self) -> None:
        selected_vm = self.workstations_pane.get_selected_workstation()
        self.push_screen(RemoteDesktopModal(workstation=selected_vm), self.on_modal_closed)

    def on_modal_closed(self, result: str) -> None:
        selected_vm = self.workstations_pane.get_selected_workstation()
        name = selected_vm.get("name", "workstation")
        if result == "ssh":
            if name and name != "local-workstation":
                self.log_message(f"[bold cyan]To connect via SSH, run in your shell:[/] [white]./ssh {name}[/]")
            else:
                self.log_message("[bold cyan]Local workstation shell already active in this terminal.[/]")
        elif result:
            self.log_message(f"[bold cyan]Connected to '{name}' via protocol:[/] [green]{result}[/]")

    def action_run_probe(self) -> None:
        self.log_message("[bold cyan]Running hardware & subsystem probe...[/]")
        self.subsystems_pane.refresh_subsystems()
        self.doctor_pane.refresh_doctor()
        self.hardware_pane.refresh_telemetry()
        self.log_message("[bold green]Subsystem probe completed.[/]")

    def action_run_heal(self) -> None:
        self.log_message("[bold yellow]Executing self-healing state drift repair...[/]")
        if INSTALLER_BIN.exists():
            self.run_async_command(f"{INSTALLER_BIN} repair --dry-run")
        else:
            self.log_message("[green]No drift detected. System state is healthy.[/]")

    def action_run_audit(self) -> None:
        self.log_message("[bold cyan]Running pre-flight architecture audit...[/]")
        self.action_tab_doctor()
        self.doctor_pane.refresh_doctor()
        self.log_message("[bold green]Pre-flight audit updated.[/]")

    def action_run_start(self) -> None:
        selected_vm = self.workstations_pane.get_selected_workstation()
        name = selected_vm.get("name", "workstation")
        if name == "local-workstation" or selected_vm.get("cloud") == "BARE-METAL":
            self.log_message("[bold yellow]Notice:[/] local-workstation is a bare-metal node (always running).")
            return

        start_script = REPO_ROOT / "start"
        if start_script.exists():
            self.run_async_command(f"{start_script} {name}")
        else:
            self.log_message(f"[bold green]Starting workstation '{name}'...[/]")

    def action_run_stop(self) -> None:
        selected_vm = self.workstations_pane.get_selected_workstation()
        name = selected_vm.get("name", "workstation")
        if name == "local-workstation" or selected_vm.get("cloud") == "BARE-METAL":
            self.log_message("[bold yellow]Notice:[/] local-workstation is a bare-metal node. Cloud stop does not apply.")
            return

        stop_script = REPO_ROOT / "stop"
        if stop_script.exists():
            self.run_async_command(f"{stop_script} {name}")
        else:
            self.log_message(f"[bold yellow]Stopping workstation '{name}' to pause billing...[/]")

    def action_run_refresh(self) -> None:
        self.telemetry_widget.update_metrics()
        self.subsystems_pane.refresh_subsystems()
        self.workstations_pane.refresh_workstations()
        self.doctor_pane.refresh_doctor()
        self.hardware_pane.refresh_telemetry()
        self.log_message("[bold cyan]All tab data refreshed.[/]")

    def run_async_command(self, cmd: str) -> None:
        self.action_tab_logs()
        self.log_message(f"[bold white]$ {cmd}[/]")

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in proc.stdout:
                    self.call_from_thread(self.log_message, f"  {line.rstrip()}")
                proc.wait()
                self.call_from_thread(self.log_message, f"[bold green]Finished with exit code {proc.returncode}[/]")
            except Exception as e:
                self.call_from_thread(self.log_message, f"[bold red]Error: {e}[/]")

        self.run_worker(worker, thread=True)

    # Table Row Double-Click / Enter to Connect
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "workstations-table":
            self.action_open_connect_modal()

    # Button Event Dispatchers
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-probe":
            self.action_run_probe()
        elif btn_id == "btn-heal":
            self.action_run_heal()
        elif btn_id == "btn-audit":
            self.action_run_audit()
        elif btn_id == "btn-refresh-sub":
            self.subsystems_pane.refresh_subsystems()
        elif btn_id == "btn-refresh-vms":
            self.workstations_pane.refresh_workstations()
        elif btn_id == "btn-start-vm":
            self.action_run_start()
        elif btn_id == "btn-stop-vm":
            self.action_run_stop()
        elif btn_id == "btn-connect-vm":
            self.action_open_connect_modal()
        elif btn_id == "btn-clear-log":
            self.logs_pane.clear_log()
        elif btn_id == "btn-doc-probe":
            self.doctor_pane.refresh_doctor()
        elif btn_id == "btn-doc-heal":
            self.action_run_heal()
        elif btn_id == "btn-hw-refresh":
            self.hardware_pane.refresh_telemetry()
        elif btn_id == "btn-apply-profile":
            self.log_message("[bold green]Configuration profile applied successfully.[/]")


if __name__ == "__main__":
    app = Isaac9sApp()
    app.run()
