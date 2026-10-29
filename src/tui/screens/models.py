"""
Models & Checkpoints Screen for isaac9s
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Static, Label
from rich.text import Text

from src.python.model_profile import (
    list_model_profiles,
    resolve_model_profile,
    generate_download_plan,
    ModelProfileError,
)


class ModelsPane(Vertical):
    """Declarative AI model & weights management screen."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_profiles: list[str] = []
        self.selected_profile_name: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-bar"):
            yield Button("Download [d]", id="btn-download-model", variant="primary")
            yield Button("Dry-Run Plan [v]", id="btn-plan-model", variant="default")
            yield Button("Refresh [r]", id="btn-refresh-models", variant="default")

        with Horizontal(id="models-split-view"):
            with Vertical(id="models-table-container"):
                yield DataTable(id="models-table")
            with VerticalScroll(id="models-detail-pane"):
                yield Static("Select a model profile above to view details.", id="models-detail-content")

    def on_mount(self) -> None:
        table = self.query_one("#models-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Profile", "Description", "Models", "Min Disk", "Engine")
        self.refresh_profiles()

    def refresh_profiles(self) -> None:
        table = self.query_one("#models-table", DataTable)
        table.clear()
        self.current_profiles = list_model_profiles()

        for name in self.current_profiles:
            try:
                resolved = resolve_model_profile(name)
                desc = resolved.get("description", "")
                model_count = str(len(resolved.get("models", [])))
                disk_req = f"{resolved.get('total_min_disk_gb', 0)} GB"
                engine = resolved.get("models", [{}])[0].get("download_engine", "hf_transfer")
                table.add_row(
                    Text(name, style="bold cyan"),
                    desc,
                    model_count,
                    Text(disk_req, style="yellow"),
                    engine,
                )
            except Exception as err:
                table.add_row(name, f"Error: {err}", "0", "0 GB", "unknown")

        if self.current_profiles:
            self.show_profile_details(self.current_profiles[0])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#models-table", DataTable)
        try:
            row_idx = event.cursor_row
            if 0 <= row_idx < len(self.current_profiles):
                profile_name = self.current_profiles[row_idx]
                self.show_profile_details(profile_name)
        except Exception:
            pass

    def show_profile_details(self, profile_name: str) -> None:
        self.selected_profile_name = profile_name
        detail_view = self.query_one("#models-detail-content", Static)
        try:
            resolved = resolve_model_profile(profile_name)
            plan = generate_download_plan(resolved)

            lines = [
                f"[bold cyan]Profile:[/] [white]{resolved['model_profile_name']}[/]",
                f"[bold cyan]Description:[/] {resolved['description']}",
                f"[bold cyan]Recommended Free Disk:[/] [yellow]{resolved['total_min_disk_gb']} GB[/]",
            ]

            if resolved.get("storage"):
                storage = resolved["storage"]
                lines.append(f"[bold cyan]Physical Storage:[/] [green]{storage['physical_dir']}[/]")
                for mount in storage.get("logical_mounts", []):
                    lines.append(f"  [bold]Mount Link:[/] {mount['target']} -> {mount['link_to']}")

            lines.append("\n[bold white underline]Declared Models:[/]")
            for idx, m in enumerate(resolved.get("models", []), start=1):
                lines.append(f"  [bold cyan]{idx}. {m['name']}[/]")
                lines.append(f"     • Repo ID:     [green]{m['repo_id']}[/] (rev: {m['revision']})")
                lines.append(f"     • Destination: {m['destination']}")
                if m.get("symlinks"):
                    lines.append(f"     • Symlinks:    {', '.join(m['symlinks'])}")
                if m.get("allow_patterns"):
                    lines.append(f"     • Include:     {', '.join(m['allow_patterns'])}")
                if m.get("ignore_patterns"):
                    lines.append(f"     • Exclude:     {', '.join(m['ignore_patterns'])}")

            lines.append("\n[bold white underline]Generated Command Preview:[/]")
            for item in plan.get("download_commands", []):
                lines.append(f"  [dim]$ {item['command']}[/]")

            detail_view.update("\n".join(lines))
        except ModelProfileError as err:
            detail_view.update(f"[red]Error loading profile {profile_name}:[/] {err}")

    def get_selected_profile(self) -> str | None:
        return self.selected_profile_name
