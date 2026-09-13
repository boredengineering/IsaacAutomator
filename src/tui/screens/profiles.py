"""
Declarative Profile & Dynamic Security Configurator Screen for isaac9s
Supports Simple, Team, Enterprise, and Custom modes with persistent YAML profiles.
"""
from pathlib import Path
import asyncio
import re
import yaml

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, Select, Static

from src.python.config import save_profile_spec
from src.python.workstation_profile import list_profiles, resolve_profile, ProfileError
from src.tui.backend import REPO_ROOT, backend_selection, load_backend_selection


class ProfilesPane(VerticalScroll):
    """Declarative profile and dynamic multi-cloud security configurator."""

    DEFAULT_CSS = """
    ProfilesPane > Vertical.box-panel { height: auto; }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_profile: str = "default"
        self.selected_tier: str = "simple"
        self.selected_cloud = "gcp"
        self.selected_state_backend = "local"
        self.backend_config = ""
        self.backend_worker = None
        self.validated_backend = None
        self.validated_selection = None

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold cyan]isaac9s » Declarative Profile & Dynamic Security Configurator[/]",
            classes="box-panel",
        )

        with Vertical(classes="box-panel"):
            yield Label("[bold yellow]1. WORKSTATION SOFTWARE INTENT (NOT APPLIED):[/]")
            with RadioSet(id="rs-workstation-profile"):
                for name in list_profiles():
                    yield RadioButton(f"{name} — offline software intent", value=name == self.selected_profile, id=f"p-{name}")
            yield Static(id="workstation-intent", markup=False)

        with Vertical(classes="box-panel"):
            yield Label("[bold yellow]2. SELECT SECURITY & INFRASTRUCTURE MODE:[/]")
            with RadioSet(id="rs-security-tier"):
                yield RadioButton("Tier 1: Simple Mode (cost not estimated)", value=True, id="tier-simple")
                yield RadioButton("Tier 2: Team Mode (cost not estimated)", id="tier-team")
                yield RadioButton("Tier 3: Enterprise Mode (cost not estimated)", id="tier-enterprise")
                yield RadioButton("Special Custom Mode (Interactive Granular Configurator)", id="tier-custom")

        with Vertical(id="custom-config-container", classes="box-panel"):
            yield Label("[bold cyan]3. CUSTOM SUBSYSTEM INTENT (NOT APPLIED):[/]")
            yield Checkbox("Zero Public IP (Cloud IAP TCP Forwarding Tunnel)", value=True, id="cb-custom-iap")
            yield Checkbox("Cloud NAT Gateway (Required for Private Outbound Packages)", value=True, id="cb-custom-nat")

            yield Checkbox("Customer-Managed Encryption Keys (Cloud KMS CMEK)", value=False, id="cb-custom-kmscmek")
            yield Checkbox("Shielded VM (Secure Boot, vTPM, Integrity Monitoring)", value=True, id="cb-custom-shielded")
            yield Checkbox("Centralized OS Login with Mandatory 2FA", value=True, id="cb-custom-oslogin")
            yield Checkbox("Google Secret Manager (Zero-Bake Credentials)", value=True, id="cb-custom-secrets")

            with Horizontal(classes="action-bar"):
                yield Label("[bold white]Profile Name:[/] ", classes="action-label")
                yield Input(value="cybernetic-custom", id="inp-custom-profile-name", placeholder="profile-name")

        with Vertical(classes="box-panel"):
            yield Label("Terraform state (independent of security tier; local default):")
            yield Select([("GCP", "gcp"), ("AWS", "aws"), ("Azure", "azure"), ("Alibaba", "alicloud")],
                         value="gcp", allow_blank=False, id="sel-profile-cloud")
            yield Select([("Local", "local"), ("GCS (GCP only)", "gcs"),
                          ("S3 (AWS only)", "s3"), ("Azure Blob (Azure only)", "azurerm")],
                         value="local", allow_blank=False, id="sel-profile-backend")
            yield Input(placeholder="Nonsecret backend YAML/JSON file path", id="inp-profile-backend-config")
            yield Button("Validate backend intent (offline)", id="btn-profile-backend-validate")
            yield Static("Local default. Remote execution blocked pending production gates.",
                         id="profile-backend-status", markup=False)

        yield Static(id="profile-details-panel", classes="box-panel")

        with Horizontal(classes="action-bar"):
            yield Button("Save Intent (not apply)", id="btn-apply-profile", variant="primary")
            yield Button("Save Profile to YAML", id="btn-save-custom-profile", variant="success")
            yield Button("Export Active Spec", id="btn-export-profile", variant="default")

    def on_mount(self) -> None:
        self.update_custom_visibility(False)
        self.update_details("tier-simple")
        self.update_workstation_intent()

    def update_workstation_intent(self) -> None:
        try:
            report = resolve_profile(self.selected_profile)
            components = ", ".join(name for name, spec in report["profile"]["components"].items() if spec["enabled"])
            text = (f"{self.selected_profile}: {components or 'no software selected'}. "
                    "Offline intent, not applied. Software apply unsupported; ready_for_apply=False. "
                    "No installation, verification or pricing implied by this selection.")
        except (ProfileError, OSError):
            text = "Software intent unavailable; not applied. Apply unsupported; ready_for_apply=False."
        self.query_one("#workstation-intent", Static).update(text)

    def update_custom_visibility(self, visible: bool) -> None:
        try:
            container = self.query_one("#custom-config-container", Vertical)
            container.display = visible
        except Exception:
            pass

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "rs-security-tier":
            tier_map = {
                "tier-simple": "simple",
                "tier-team": "team",
                "tier-enterprise": "enterprise",
                "tier-custom": "custom",
            }
            self.selected_tier = tier_map.get(event.pressed.id, "simple")
            self.update_custom_visibility(self.selected_tier == "custom")
            self.update_details(event.pressed.id)
        elif event.radio_set.id == "rs-workstation-profile":
            self.selected_profile = event.pressed.id.removeprefix("p-")
            self.update_workstation_intent()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self.selected_tier == "custom":
            self.update_details("tier-custom")

    def update_details(self, tier_id: str) -> None:
        panel = self.query_one("#profile-details-panel", Static)
        if tier_id == "tier-simple":
            panel.update(
                "[bold green]Active Selection: Tier 1 - Simple Mode (Frictionless / Beginner)[/]\n\n"
                "• [bold white]Firewall Ingress:[/]   [cyan]Dynamic /32 IP Whitelist[/] (auto-locked to caller IP via curl ifconfig.me)\n"
                "• [bold white]Outbound Internet:[/]  Direct ephemeral public IP\n"
                "• [bold white]Data Encryption:[/]    Cloud-default encryption (Google-managed, AWS SSE-S3, Azure PMK)\n"
                "• [bold white]State Storage:[/]      Local by default; explicit backend intent below\n"
                "• [bold white]IAM Requirements:[/]   Standard personal developer credentials (zero Org Admin / KMS blockers)"
            )
        elif tier_id == "tier-team":
            panel.update(
                "[bold yellow]Active Selection: Tier 2 - Collaborative (Team & Multi-Agent)[/]\n\n"
                "• [bold white]Firewall Ingress:[/]   Dynamic /32 IP Whitelist or shared team subnet CIDR\n"
                "• [bold white]Outbound Internet:[/]  Direct ephemeral public IP\n"
                "• [bold white]Data Encryption:[/]    Cloud-default encryption with bucket versioning\n"
                "• [bold white]State Storage:[/]      Local by default; Team does not enable remote state\n"
                "• [bold white]Remote State:[/]       Explicit GCS/S3/Azure selection only; execution currently blocked"
            )
        elif tier_id == "tier-enterprise":
            panel.update(
                "[bold red]Active Selection: Tier 3 - Enterprise Hardened (Defense / Compliance)[/]\n\n"
                "• [bold white]Firewall Ingress:[/]   Zero Public IP (Cloud IAP, AWS SSM Session Manager, Azure Bastion)\n"
                "• [bold white]Outbound Internet:[/]  Managed Cloud NAT Gateway with Cloud Router\n"
                "• [bold white]Data Encryption:[/]    Customer-Managed Encryption Keys (KMS CMEK / CMK) with 90-day auto-rotation\n"
                "• [bold white]Secrets Handling:[/]   Cloud Secret Manager (GCP, AWS, Azure Key Vault, AliCloud KMS)\n"
                "• [bold white]Hardware Security:[/]  Shielded VM (Secure Boot & vTPM) / AWS Nitro Enclaves / Trusted Launch"
            )
        else:
            panel.update(
                f"[bold cyan]Active Selection: Special Custom Mode (Interactive Granular Spec)[/]\n\n"
                f"• [bold white]Network Perimeter:[/]  {'Zero Public IP (Cloud IAP Tunnel)' if self.query_one('#cb-custom-iap', Checkbox).value else 'Public IP (/32 Lock)'}\n"
                f"• [bold white]Outbound Routing:[/]   {'Managed Cloud NAT Gateway' if self.query_one('#cb-custom-nat', Checkbox).value else 'Direct Ephemeral Public'}\n"
                f"• [bold white]Storage Backend:[/]    Explicit selection below; no automatic bucket creation\n"
                f"• [bold white]Cryptographic Key:[/]  {'Customer-Managed KMS CMEK (90d rotation)' if self.query_one('#cb-custom-kmscmek', Checkbox).value else 'Google-Managed Default'}\n"
                f"• [bold white]Hardware Security:[/]  {'Shielded VM (Secure Boot + vTPM)' if self.query_one('#cb-custom-shielded', Checkbox).value else 'Standard VM'}\n"
                f"• [bold white]Identity & Access:[/]  {'OS Login with Mandatory 2FA' if self.query_one('#cb-custom-oslogin', Checkbox).value else 'Static Metadata RSA Key'}"
            )

    def export_yaml(self) -> Path:
        spec = {"profile_name": self.selected_profile, "cloud": self.selected_cloud,
                "security": {"tier": self.selected_tier},
                "workstation": {"base_profile": self.selected_profile,
                                "apply_supported": False, "ready_for_apply": False},
                "terraform_state": self.backend_intent()}
        out_dir = REPO_ROOT / "state"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "active-profile.yaml"
        content = yaml.safe_dump(spec, sort_keys=False)
        out_file.write_text(content)
        return out_file

    def save_custom_profile_yaml(self) -> Path:
        prof_name = self.query_one("#inp-custom-profile-name", Input).value.strip() or "custom-profile"
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}", prof_name):
            raise ValueError("Profile name must be a simple name, not a path")
        spec = {
            "schema_version": "v1alpha1",
            "profile_name": prof_name,
            "description": f"Custom profile saved from isaac9s ({prof_name})",
            "cloud": self.selected_cloud,
            "terraform_state": self.backend_intent(),
            "security": {
                "tier": "custom",
                "network": {
                    "iap_only": self.query_one("#cb-custom-iap", Checkbox).value,
                    "cloud_nat": self.query_one("#cb-custom-nat", Checkbox).value,
                    "ingress_cidrs": [] if self.query_one("#cb-custom-iap", Checkbox).value else ["auto"],
                },

                "cryptography": {
                    "encryption_type": "kms_cmek" if self.query_one("#cb-custom-kmscmek", Checkbox).value else "google_managed",
                    "kms_keyring_name": "auto" if self.query_one("#cb-custom-kmscmek", Checkbox).value else "",
                },
                "compute": {
                    "shielded_vm": self.query_one("#cb-custom-shielded", Checkbox).value,
                    "os_login": self.query_one("#cb-custom-oslogin", Checkbox).value,
                    "service_account_type": "dedicated" if self.query_one("#cb-custom-iap", Checkbox).value else "default",
                },
                "secrets": {
                    "engine": "secret_manager" if self.query_one("#cb-custom-secrets", Checkbox).value else "env_vars",
                },
            },
            "workstation": {
                "base_profile": self.selected_profile,
                "apply_supported": False,
                "ready_for_apply": False,
            },
        }
        return save_profile_spec(prof_name, spec, repo_root=str(REPO_ROOT))

    def backend_intent(self) -> dict:
        selection = (self.selected_cloud, self.selected_state_backend, self.backend_config)
        if self.selected_state_backend == "local" and not self.backend_config:
            return backend_selection(self.selected_cloud)[0].to_dict()
        if selection != self.validated_selection or self.validated_backend is None:
            raise ValueError("Validate the selected backend configuration before saving")
        return self.validated_backend.to_dict()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sel-profile-cloud":
            self.selected_cloud = str(event.value)
        elif event.select.id == "sel-profile-backend":
            self.selected_state_backend = str(event.value)
        else:
            return
        self.invalidate_backend()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "inp-profile-backend-config":
            self.backend_config = event.value.strip()
            self.invalidate_backend()

    def invalidate_backend(self) -> None:
        self.validated_backend = None
        self.validated_selection = None
        if self.backend_worker is not None:
            self.backend_worker.cancel()
        if self.is_mounted:
            self.query_one("#profile-backend-status", Static).update(
                "Selection changed. Validate before saving. Cloud access UNKNOWN; remote execution BLOCKED.")

    async def validate_backend(self) -> None:
        selection = (self.selected_cloud, self.selected_state_backend, self.backend_config)
        panel = self.query_one("#profile-backend-status", Static)
        panel.update("Validating offline intent…")
        try:
            spec = await load_backend_selection(*selection, timeout=5.0)
        except (ValueError, OSError, asyncio.TimeoutError):
            panel.update("Invalid configuration or validation timeout. No backend setup performed.")
            return
        if selection != (self.selected_cloud, self.selected_state_backend, self.backend_config):
            return
        self.validated_backend = spec
        self.validated_selection = selection
        panel.update("Intent validated (not cloud access). Saving preserves nonsecret intent only. "
                     "Remote execution BLOCKED pending production gates.")

    def on_unmount(self) -> None:
        if self.backend_worker is not None:
            self.backend_worker.cancel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-profile-backend-validate":
            self.backend_worker = self.run_worker(self.validate_backend, group="backend-validation", exclusive=True)
            return
        try:
            self.handle_profile_button(event)
        except (ValueError, OSError):
            event.stop()
            self.notify("Profile not saved: validate backend configuration and check the profile name/path.", severity="error")

    def handle_profile_button(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-export-profile":
            path = self.export_yaml()
            self.notify(f"Exported spec to {path.name}")
        elif event.button.id == "btn-save-custom-profile":
            saved_path = self.save_custom_profile_yaml()
            self.notify(f"Saved custom profile to {saved_path.relative_to(REPO_ROOT)}")
        elif event.button.id == "btn-apply-profile":
            if self.selected_tier == "custom":
                saved_path = self.save_custom_profile_yaml()
                self.notify(f"Custom profile '{saved_path.stem}' saved as intent, not applied.")
            else:
                self.export_yaml()
                self.notify(f"Profile '{self.selected_profile}' saved as intent, not applied.")
