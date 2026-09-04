"""
Real-Time Task Execution Log Streamer Screen for isaac9s
"""
from datetime import datetime
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, RichLog


class LogsPane(Vertical):
    """Real-time subprocess execution log streamer and pager."""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-bar"):
            yield Button("Clear Log", id="btn-clear-log", variant="default")
            yield Input(placeholder="Filter logs...", id="input-log-filter")

        yield RichLog(id="execution-log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#execution-log", RichLog)

    def write_line(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_widget.write(f"[{ts}] {msg}")

    def clear_log(self) -> None:
        self.log_widget.clear()

    def on_input_changed(self, event: Input.Changed) -> None:
        pass
