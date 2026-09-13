"""Explicit-input cost estimation shared by the TUI; no deployment imports."""
import asyncio
from functools import partial
from importlib import import_module
import threading

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Select, Static


def estimate_text(*, path=None, saved_plan=None, usage_file=None, cancel_event=None):
    """Lazy adapter: mounting the UI never imports or invokes pricing tooling."""
    core = import_module("src.python.cost_estimate")
    report = core.estimate(path=path, saved_plan=saved_plan, usage_file=usage_file,
                           timeout=60, cancel_event=cancel_event,
                           public_input=True, allow_external_pricing=True)
    return (core.format_report(report, format="table") +
            "\n\nReport details / provenance (JSON):\n" + core.format_report(report, format="json"))


class CostEstimatePanel(Vertical):
    """Price only a deliberately chosen HCL directory or existing saved plan."""

    DEFAULT_CSS = """
    CostEstimatePanel { height: auto; border: round $primary; padding: 1; }
    CostEstimatePanel Static { height: auto; }
    CostEstimatePanel Horizontal { height: 3; }
    CostEstimatePanel Input, CostEstimatePanel Select { margin-bottom: 1; }
    """

    def __init__(self, *, unavailable_reason=None, **kwargs):
        super().__init__(**kwargs)
        self.unavailable_reason = unavailable_reason
        self.cost_worker = None
        self.cancel_event = None
        self.generation = 0
        self.closing = False

    def compose(self) -> ComposeResult:
        yield Static("Cost estimate — explicit input only. Not a price for selected YAML/software, "
                     "security or machine intent. No live plan generation or cloud discovery. "
                     "Estimate/Refresh may contact the configured pricing service. "
                     "Usage assumptions and unsupported inputs are disclosed in the report; not measured billing.",
                     id="cost-scope", markup=False)
        yield Select([("Local Terraform HCL directory", "hcl"),
                      ("Existing saved Terraform plan JSON", "plan")],
                     value="hcl", allow_blank=False, id="sel-cost-source")
        yield Input(placeholder="Explicit HCL directory or saved plan JSON path", id="inp-cost-path")
        yield Input(placeholder="Optional usage YAML path (binding may be unsupported; see report)", id="inp-cost-usage")
        yield Checkbox("I confirm public-only input and allow external pricing requests / telemetry",
                       value=False, id="cb-cost-public")
        with Horizontal():
            yield Button("Estimate / Refresh", id="btn-cost-estimate", variant="primary",
                         disabled=bool(self.unavailable_reason))
            yield Button("Cancel estimate", id="btn-cost-cancel", disabled=True)
        yield Static(self.unavailable_reason or "Not estimated. Select an explicit input, then Estimate / Refresh.",
                     id="cost-status", markup=False)
        yield Static("", id="cost-report", markup=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cost-cancel":
            event.stop()
            self.cancel_estimate()
            self.query_one("#cost-status", Static).update("Cancelled. Not estimated; refresh explicitly.")
            return
        if event.button.id == "btn-cost-estimate":
            event.stop()
            if self.unavailable_reason:
                return
            self.cancel_estimate()
            path = self.query_one("#inp-cost-path", Input).value.strip()
            if not path:
                self.query_one("#cost-status", Static).update("Not estimated: select an explicit input path.")
                return
            if not self.query_one("#cb-cost-public", Checkbox).value:
                self.query_one("#cost-status", Static).update(
                    "Not estimated: acknowledge public-only input and external pricing / telemetry first.")
                return
            usage = self.query_one("#inp-cost-usage", Input).value.strip() or None
            source = self.query_one("#sel-cost-source", Select).value
            self.cancel_event = threading.Event()
            self.query_one("#btn-cost-cancel", Button).disabled = False
            self.cost_worker = self.run_worker(partial(
                self._estimate, path, source, usage, self.cancel_event, self.generation))

    def cancel_estimate(self) -> None:
        self.generation += 1
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.cost_worker is not None:
            self.cost_worker.cancel()
        if self.is_mounted and not self.closing:
            self.query_one("#btn-cost-cancel", Button).disabled = True

    def on_unmount(self) -> None:
        self.closing = True
        self.cancel_estimate()

    def mark_stale(self) -> None:
        """Invalidate without calling the estimator, including pending requests."""
        self.cancel_estimate()
        if self.is_mounted and not self.closing:
            self.query_one("#cost-report", Static).update("")
            self.query_one("#cost-status", Static).update(
                self.unavailable_reason or "Stale / not estimated: selection changed. Refresh explicit input; intent is not priced.")

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.mark_stale()

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self.mark_stale()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self.mark_stale()

    async def _estimate(self, path, source, usage, cancel_event, generation) -> None:
        self.query_one("#cost-status", Static).update("Estimating explicit input only…")
        self.query_one("#cost-report", Static).update("")
        try:
            text = await asyncio.to_thread(estimate_text, path=path if source == "hcl" else None,
                                           saved_plan=path if source == "plan" else None,
                                           usage_file=usage, cancel_event=cancel_event)
        except asyncio.CancelledError:
            cancel_event.set()
            raise
        except Exception:
            # Core failures may contain paths or command diagnostics; don't echo them.
            if generation == self.generation and self.is_mounted and not self.closing:
                self.query_one("#cost-status", Static).update(
                    "Estimate unavailable. Check input and local pricing tooling; no deployment performed.")
                self.query_one("#btn-cost-cancel", Button).disabled = True
            return
        if generation != self.generation or cancel_event.is_set() or not self.is_mounted or self.closing:
            return
        self.query_one("#cost-report", Static).update(text)
        self.query_one("#cost-status", Static).update("Report for explicit input only; not applied intent.")
        self.query_one("#btn-cost-cancel", Button).disabled = True
