"""
Declarative Profile & 3-Tier Security Configurator Screen for isaac9s
"""
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, RadioButton, RadioSet, Static

from src.tui.backend import REPO_ROOT


class ProfilesPane(VerticalScroll):
    """Declarative profile and 3-tier security configurator."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_profile: str = "default-workstation.yaml"
        self.selected_tier: str = "simple"

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold cyan]isaac9s » Declarative Profile & Multi-Cloud Security Configurator[/]",
            classes="box-panel",
        )

        with Vertical(classes="box-panel"):
            yield Label("[bold yellow]1. SELECT WORKSTATION PROFILE:[/]")
            with RadioSet(id="rs-workstation-profile"):
                yield RadioButton("default-workstation.yaml - Clean robotics workstation (Sim + Lab + Dev Apps)", value=True, id="p-default")
                yield RadioButton("full-ecosystem.yaml    - Full ecosystem (+ LeRobot, Arena, GR00T, Manus VR)", id="p-full")
                yield RadioButton("minimal-headless.yaml  - Minimal headless compute node (Sim server, CI/CD, training)", id="p-minimal")

        with Vertical(classes="box-panel"):
            yield Label("[bold yellow]2. SELECT SECURITY & HARDENING TIER:[/]")
            with RadioSet(id="rs-security-tier"):
                yield RadioButton("Tier 1: Simple Mode ($0.00 / mo added cost) [RECOMMENDED FOR BEGINNERS]", value=True, id="tier-simple")
                yield RadioButton("Tier 2: Team Mode (<$0.10 / mo added cost) [FOR COLLABORATION & CI]", id="tier-team")
                yield RadioButton("Tier 3: Enterprise Mode (~$35 - $180 / mo) [FOR REGULATED / COMPLIANCE]", id="tier-enterprise")

        yield Static(id="profile-details-panel", classes="box-panel")

        with Horizontal(classes="action-bar"):
            yield Button("Apply Configuration", id="btn-apply-profile", variant="primary")
            yield Button("Export YAML Spec", id="btn-export-profile", variant="default")

    def on_mount(self) -> None:
        self.update_details("tier-simple")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "rs-security-tier":
            tier_map = {
                "tier-simple": "simple",
                "tier-team": "team",
                "tier-enterprise": "enterprise",
            }
            self.selected_tier = tier_map.get(event.pressed.id, "simple")
            self.update_details(event.pressed.id)
        elif event.radio_set.id == "rs-workstation-profile":
            prof_map = {
                "p-default": "default-workstation.yaml",
                "p-full": "full-ecosystem.yaml",
                "p-minimal": "minimal-headless.yaml",
            }
            self.selected_profile = prof_map.get(event.pressed.id, "default-workstation.yaml")

    def update_details(self, tier_id: str) -> None:
        panel = self.query_one("#profile-details-panel", Static)
        if tier_id == "tier-simple":
            panel.update(
                "[bold green]Active Selection: Tier 1 - Simple Mode (Frictionless / Beginner)[/]\n\n"
                "• [bold white]Added Monthly Cost:[/] [green]$0.00 / month[/]\n"
                "• [bold white]Firewall Ingress:[/]   [cyan]Dynamic /32 IP Whitelist[/] (auto-locked to caller IP via curl ifconfig.me)\n"
                "• [bold white]Outbound Internet:[/]  Direct ephemeral public IP (Eliminates $32/mo Cloud NAT fee)\n"
                "• [bold white]Data Encryption:[/]    Free cloud-default encryption (Google-managed, AWS SSE-S3, Azure PMK)\n"
                "• [bold white]State Storage:[/]      Local state in ./state/<name>/.tfstate with POSIX 0600 permissions\n"
                "• [bold white]IAM Requirements:[/]   Standard personal developer credentials (zero Org Admin / KMS blockers)"
            )
        elif tier_id == "tier-team":
            panel.update(
                "[bold yellow]Active Selection: Tier 2 - Collaborative (Team & Multi-Agent)[/]\n\n"
                "• [bold white]Added Monthly Cost:[/] [yellow]<$0.10 / month[/]\n"
                "• [bold white]Firewall Ingress:[/]   Dynamic /32 IP Whitelist or shared team subnet CIDR\n"
                "• [bold white]Outbound Internet:[/]  Direct ephemeral public IP\n"
                "• [bold white]Data Encryption:[/]    Free cloud-default encryption with bucket versioning\n"
                "• [bold white]State Storage:[/]      Cloud remote state (S3, GCS, Azure Blob, AliCloud OSS) with native locking\n"
                "• [bold white]IAM Requirements:[/]   Object Admin on dedicated team state bucket"
            )
        else:
            panel.update(
                "[bold red]Active Selection: Tier 3 - Enterprise Hardened (Defense / Compliance)[/]\n\n"
                "• [bold white]Added Monthly Cost:[/] [red]~$35.00 - $180.00+ / month[/] (Cloud NAT, KMS keys, Bastion)\n"
                "• [bold white]Firewall Ingress:[/]   Zero Public IP (Cloud IAP, AWS SSM Session Manager, Azure Bastion)\n"
                "• [bold white]Outbound Internet:[/]  Managed Cloud NAT Gateway with Cloud Router\n"
                "• [bold white]Data Encryption:[/]    Customer-Managed Encryption Keys (KMS CMEK / CMK) with 90-day auto-rotation\n"
                "• [bold white]Secrets Handling:[/]   Cloud Secret Manager (GCP, AWS, Azure Key Vault, AliCloud KMS)\n"
                "• [bold white]Hardware Security:[/]  Shielded VM (Secure Boot & vTPM) / AWS Nitro Enclaves / Trusted Launch"
            )

    def export_yaml(self) -> Path:
        out_dir = REPO_ROOT / "state"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "active-profile.yaml"
        content = (
            f"# Generated by isaac9s\n"
            f"profile: {self.selected_profile}\n"
            f"security_tier: {self.selected_tier}\n"
            f"auto_ip_lockdown: true\n"
        )
        out_file.write_text(content)
        return out_file

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-export-profile":
            path = self.export_yaml()
            self.notify(f"Exported spec to {path.name}")
        elif event.button.id == "btn-apply-profile":
            self.export_yaml()
            self.notify(f"Profile '{self.selected_profile}' applied with {self.selected_tier.capitalize()} security.")
