"""
Interactive In-Cockpit Workstation Deployer Modal for isaac9s
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, Select, Static


class DeployWorkstationModal(ModalScreen):
    """Guided modal for non-interactive cloud workstation provisioning."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
    ]

    GPU_OPTIONS = [
        ("AWS: g5.2xlarge (NVIDIA A10G 24GB, ~$1.21/hr)", "g5.2xlarge"),
        ("GCP: g2-standard-8 (NVIDIA L4 24GB, ~$0.85/hr)", "g2-standard-8"),
        ("Azure: Standard_NC4as_T4_v3 (Tesla T4 16GB, ~$0.75/hr)", "Standard_NC4as_T4_v3"),
        ("Alibaba: ecs.gn7i-c8g1.2xlarge (NVIDIA A10 24GB, ~$1.15/hr)", "ecs.gn7i-c8g1.2xlarge"),
    ]

    def __init__(self):
        super().__init__()
        self.selected_cloud = "aws"
        self.selected_profile = "simple"

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New Isaac Workstation Deployer", id="dialog-title")

            with VerticalScroll(id="deploy-body"):
                yield Label("[bold white]1. Workstation Name:[/]")
                yield Input(value="isaac-ws-01", placeholder="Enter unique deployment name", id="inp-deploy-name")

                yield Label("[bold white]2. Cloud Provider:[/]")
                with RadioSet(id="deploy-cloud-select"):
                    yield RadioButton("AWS EC2", value=True, id="rb-cloud-aws")
                    yield RadioButton("Google Cloud (GCP)", id="rb-cloud-gcp")
                    yield RadioButton("Microsoft Azure", id="rb-cloud-azure")
                    yield RadioButton("Alibaba Cloud", id="rb-cloud-alicloud")

                yield Label("[bold white]3. GPU & Instance Type:[/]")
                yield Select(
                    options=self.GPU_OPTIONS,
                    value="g5.2xlarge",
                    id="sel-deploy-gpu",
                    allow_blank=False,
                )

                yield Label("[bold white]4. Multi-Cloud Security Profile:[/]")
                with RadioSet(id="deploy-profile-select"):
                    yield RadioButton("Tier 1: Simple Mode ($0.00/mo, dynamic /32 IP whitelist)", value=True, id="rb-profile-simple")
                    yield RadioButton("Tier 2: Team Mode (<$0.10/mo, shared GCS/S3 remote state)", id="rb-profile-team")
                    yield RadioButton("Tier 3: Enterprise ($35-$180/mo, Cloud NAT, CMEK, Zero-Trust IAP)", id="rb-profile-enterprise")

                yield Label("[bold white]5. Optional Pre-Installed Robotics Demos:[/]")
                with Horizontal(classes="checkbox-row"):
                    yield Checkbox("Franka Manipulation", value=True, id="cb-demo-franka")
                    yield Checkbox("Humanoid Locomotion", value=False, id="cb-demo-humanoid")
                    yield Checkbox("Quadruped Locomotion", value=False, id="cb-demo-quadruped")

                yield Static(
                    "[bold green]Security & Cost Summary:[/] Zero added infrastructure cost ($0.00/mo added).\n"
                    "Firewall ingress is strictly locked to your current caller IP (/32).",
                    id="deploy-summary",
                    classes="box-panel"
                )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Launch Deployment [Enter]", id="btn-deploy-launch", variant="success")
                yield Button("Cancel (Esc)", id="btn-deploy-cancel", variant="error")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "deploy-cloud-select":
            mapping = {
                "rb-cloud-aws": ("aws", "g5.2xlarge"),
                "rb-cloud-gcp": ("gcp", "g2-standard-8"),
                "rb-cloud-azure": ("azure", "Standard_NC4as_T4_v3"),
                "rb-cloud-alicloud": ("alicloud", "ecs.gn7i-c8g1.2xlarge"),
            }
            cloud, default_gpu = mapping.get(event.pressed.id, ("aws", "g5.2xlarge"))
            self.selected_cloud = cloud
            try:
                self.query_one("#sel-deploy-gpu", Select).value = default_gpu
            except Exception:
                pass

        elif event.radio_set.id == "deploy-profile-select":
            p_map = {
                "rb-profile-simple": "simple",
                "rb-profile-team": "team",
                "rb-profile-enterprise": "enterprise",
            }
            self.selected_profile = p_map.get(event.pressed.id, "simple")
            summary = self.query_one("#deploy-summary", Static)
            if self.selected_profile == "simple":
                summary.update(
                    "[bold green]Security & Cost Summary:[/] Simple Mode ($0.00/mo added cost).\n"
                    "Firewall ingress is locked strictly to your caller IP (/32)."
                )
            elif self.selected_profile == "team":
                summary.update(
                    "[bold cyan]Security & Cost Summary:[/] Team Mode (<$0.10/mo storage cost).\n"
                    "Cloud remote state backend with native distributed state locking."
                )
            else:
                summary.update(
                    "[bold red]Security & Cost Summary:[/] Enterprise Mode ($35-$180/mo infrastructure).\n"
                    "Zero public IP, KMS CMEK encryption, Cloud NAT gateway, and Zero-Trust IAP."
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-deploy-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-deploy-launch":
            self.submit_deployment()

    def submit_deployment(self) -> None:
        name_input = self.query_one("#inp-deploy-name", Input)
        name = name_input.value.strip() or "isaac-ws-01"
        gpu = self.query_one("#sel-deploy-gpu", Select).value or "g5.2xlarge"

        demos = []
        if self.query_one("#cb-demo-franka", Checkbox).value:
            demos.append("franka-manipulation")
        if self.query_one("#cb-demo-humanoid", Checkbox).value:
            demos.append("humanoid-locomotion")
        if self.query_one("#cb-demo-quadruped", Checkbox).value:
            demos.append("quadruped-locomotion")

        result = {
            "name": name,
            "cloud": self.selected_cloud,
            "gpu": gpu,
            "profile": self.selected_profile,
            "demos": demos,
        }
        self.dismiss(result)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
