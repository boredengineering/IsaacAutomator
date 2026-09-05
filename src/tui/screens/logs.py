from datetime import datetime
from pathlib import Path
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, RichLog


class LogsPane(Vertical):
    """Real-time subprocess execution log streamer and pager with AI export."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_history: list[str] = []
        self.active_filter: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-bar"):
            yield Button("Copy All (AI Paste)", id="btn-copy-logs", variant="primary")
            yield Button("Clear Log", id="btn-clear-log", variant="default")
            yield Button("Stop Process", id="btn-cancel-proc", variant="error", disabled=True)
            yield Label("[bold green]● IDLE[/]", id="proc-status-badge")
            yield Input(placeholder="Filter logs (live search)...", id="input-log-filter")

        yield RichLog(id="execution-log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#execution-log", RichLog)

    def write_line(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{ts}] {msg}"
        self.log_history.append(formatted)
        if not self.active_filter or self.active_filter.lower() in formatted.lower():
            self.log_widget.write(formatted)

    def clear_log(self) -> None:
        self.log_history.clear()
        self.log_widget.clear()

    def copy_logs(self) -> None:
        if not self.log_history:
            self.notify("No logs to copy.", title="Log Export", severity="warning")
            return

        clean_lines = []
        for line in self.log_history:
            try:
                clean_lines.append(Text.from_markup(line).plain)
            except Exception:
                clean_lines.append(line)

        full_log_text = "\n".join(clean_lines)

        # 1. Native clipboard (OSC 52 across terminal/SSH/Docker)
        try:
            self.app.copy_to_clipboard(full_log_text)
        except Exception:
            pass

        # 2. Persist to standard file for immediate attachment / AI tool consumption
        export_path = Path("/tmp/isaac9s.log")
        try:
            export_path.write_text(full_log_text)
        except Exception:
            pass

        self.notify(
            f"Copied {len(clean_lines)} lines to clipboard & saved to /tmp/isaac9s.log",
            title="Copied for AI Tools",
            severity="information",
            timeout=5.0,
        )

    def set_proc_running(self, pid: int, cmd: str = "") -> None:
        try:
            badge = self.query_one("#proc-status-badge", Label)
            btn = self.query_one("#btn-cancel-proc", Button)
            badge.update(f"[bold yellow]● RUNNING (PID {pid})[/]")
            btn.disabled = False
        except Exception:
            pass

    def set_proc_idle(self, status: str = "IDLE") -> None:
        try:
            badge = self.query_one("#proc-status-badge", Label)
            btn = self.query_one("#btn-cancel-proc", Button)
            color = "green" if status in ("IDLE", "SUCCESS") else "red"
            badge.update(f"[bold {color}]● {status}[/]")
            btn.disabled = True
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-clear-log":
            self.clear_log()
        elif event.button.id == "btn-copy-logs":
            self.copy_logs()
        elif event.button.id == "btn-cancel-proc":
            if hasattr(self.app, "action_cancel_running_process"):
                self.app.action_cancel_running_process()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.active_filter = event.value.strip()
        self.log_widget.clear()
        for line in self.log_history:
            if not self.active_filter or self.active_filter.lower() in line.lower():
                self.log_widget.write(line)

