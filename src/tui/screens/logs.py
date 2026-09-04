"""
Real-Time Task Execution Log Streamer Screen for isaac9s
"""
from datetime import datetime
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, RichLog


class LogsPane(Vertical):
    """Real-time subprocess execution log streamer and pager."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_history: list[str] = []
        self.active_filter: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-bar"):
            yield Button("Clear Log", id="btn-clear-log", variant="default")
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

    def on_input_changed(self, event: Input.Changed) -> None:
        self.active_filter = event.value.strip()
        self.log_widget.clear()
        for line in self.log_history:
            if not self.active_filter or self.active_filter.lower() in line.lower():
                self.log_widget.write(line)
