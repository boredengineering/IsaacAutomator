"""
Interactive In-Cockpit Workstation Deployer Modal for isaac9s
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, Select, Static


class DeployWorkstationModal(ModalScreen):
    """Guided modal for multi-cloud, multi-GPU and Spot workstation provisioning."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
        Binding("q", "dismiss_modal", "Close", show=True),
    ]

    CLOUD_GPUS = {
        "gcp": [
            ("g2-standard-4 (1x NVIDIA L4 24GB, 4 vCPU, 16G RAM) ~$0.56/hr [Spot ~$0.20/hr]", "g2-standard-4"),
            ("g2-standard-8 (1x NVIDIA L4 24GB, 8 vCPU, 32G RAM) ~$0.85/hr [Spot ~$0.29/hr] (Recommended)", "g2-standard-8"),
            ("g2-standard-16 (1x NVIDIA L4 24GB, 16 vCPU, 64G RAM) ~$1.42/hr [Spot ~$0.48/hr]", "g2-standard-16"),
            ("g2-standard-24 (2x NVIDIA L4 48GB, 24 vCPU, 96G RAM) ~$2.14/hr [Spot ~$0.73/hr]", "g2-standard-24"),
            ("g2-standard-48 (4x NVIDIA L4 96GB, 48 vCPU, 192G RAM) ~$4.28/hr [Spot ~$1.46/hr]", "g2-standard-48"),
            ("g2-standard-96 (8x NVIDIA L4 192GB, 96 vCPU, 384G RAM) ~$8.56/hr [Spot ~$2.92/hr]", "g2-standard-96"),
            ("n1-standard-4 (1x Tesla T4 16GB, 4 vCPU, 15G RAM) ~$0.45/hr [Spot ~$0.15/hr]", "n1-standard-4"),
            ("n1-standard-8 (1x Tesla T4 16GB, 8 vCPU, 30G RAM) ~$0.65/hr [Spot ~$0.22/hr]", "n1-standard-8"),
            ("n1-standard-16 (2x Tesla T4 32GB, 16 vCPU, 60G RAM) ~$1.30/hr [Spot ~$0.44/hr]", "n1-standard-16"),
            ("a2-highgpu-1g (1x A100 40GB SXM4, 12 vCPU, 85G RAM) ~$3.67/hr [Spot ~$1.10/hr]", "a2-highgpu-1g"),
            ("a2-highgpu-2g (2x A100 80GB SXM4, 24 vCPU, 170G RAM) ~$7.34/hr [Spot ~$2.20/hr]", "a2-highgpu-2g"),
            ("a2-highgpu-4g (4x A100 160GB SXM4, 48 vCPU, 340G RAM) ~$14.68/hr [Spot ~$4.40/hr]", "a2-highgpu-4g"),
            ("a2-highgpu-8g (8x A100 320GB SXM4, 96 vCPU, 680G RAM) ~$29.36/hr [Spot ~$8.80/hr]", "a2-highgpu-8g"),
            ("g4-standard-48 (1x RTX Pro 6000 48GB, 48 vCPU) ~$3.95/hr", "g4-standard-48"),
        ],
        "aws": [
            ("g5.xlarge (1x NVIDIA A10G 24GB, 4 vCPU, 16G RAM) ~$1.01/hr [Spot ~$0.40/hr]", "g5.xlarge"),
            ("g5.2xlarge (1x NVIDIA A10G 24GB, 8 vCPU, 32G RAM) ~$1.21/hr [Spot ~$0.48/hr] (Recommended)", "g5.2xlarge"),
            ("g5.4xlarge (1x NVIDIA A10G 24GB, 16 vCPU, 64G RAM) ~$1.62/hr [Spot ~$0.65/hr]", "g5.4xlarge"),
            ("g5.12xlarge (4x NVIDIA A10G 96GB, 48 vCPU, 192G RAM) ~$5.67/hr [Spot ~$2.27/hr]", "g5.12xlarge"),
            ("g4dn.xlarge (1x NVIDIA T4 16GB, 4 vCPU, 16G RAM) ~$0.53/hr [Spot ~$0.21/hr]", "g4dn.xlarge"),
            ("g4dn.2xlarge (1x NVIDIA T4 16GB, 8 vCPU, 32G RAM) ~$0.75/hr [Spot ~$0.30/hr]", "g4dn.2xlarge"),
            ("p4d.24xlarge (8x NVIDIA A100 320GB, 96 vCPU, 1.1T RAM) ~$32.77/hr [Spot ~$13.11/hr]", "p4d.24xlarge"),
        ],
        "azure": [
            ("Standard_NC4as_T4_v3 (1x Tesla T4 16GB, 4 vCPU, 28G RAM) ~$0.53/hr [Spot ~$0.16/hr]", "Standard_NC4as_T4_v3"),
            ("Standard_NC8as_T4_v3 (1x Tesla T4 16GB, 8 vCPU, 56G RAM) ~$0.96/hr [Spot ~$0.29/hr]", "Standard_NC8as_T4_v3"),
            ("Standard_NC16as_T4_v3 (2x Tesla T4 32GB, 16 vCPU, 110G RAM) ~$1.92/hr [Spot ~$0.58/hr]", "Standard_NC16as_T4_v3"),
            ("Standard_NC64as_T4_v3 (4x Tesla T4 64GB, 64 vCPU, 440G RAM) ~$3.84/hr [Spot ~$1.15/hr]", "Standard_NC64as_T4_v3"),
            ("Standard_ND96amsr_A100_v4 (8x A100 320GB, 96 vCPU) ~$27.20/hr [Spot ~$8.16/hr]", "Standard_ND96amsr_A100_v4"),
        ],
        "alicloud": [
            ("ecs.gn7i-c8g1.2xlarge (1x NVIDIA A10 24GB, 8 vCPU, 31G RAM) ~$1.15/hr", "ecs.gn7i-c8g1.2xlarge"),
            ("ecs.gn6v-c8g1.2xlarge (1x NVIDIA V100 16GB, 8 vCPU, 32G RAM) ~$2.20/hr", "ecs.gn6v-c8g1.2xlarge"),
        ],
    }

    def __init__(self):
        super().__init__()
        self.selected_cloud = "gcp"
        self.selected_profile = "simple"
        self.selected_gpu = "g2-standard-8"
        self.selected_zone = "us-central1-a"
        self.scheduling_model = "standard"
        self.use_spot = False
        self.use_flex_start = False

    @staticmethod
    def get_zones_for_selection(cloud: str, gpu: str) -> list[tuple[str, str]]:
        if cloud == "gcp":
            if gpu.startswith("g2-"):
                return [
                    ("us-central1-a (Iowa - L4 Quota Verified) [Recommended]", "us-central1-a"),
                    ("us-central1-b (Iowa - L4 Secondary)", "us-central1-b"),
                    ("us-central1-c (Iowa - L4 Tertiary)", "us-central1-c"),
                    ("us-east4-a (N. Virginia - L4)", "us-east4-a"),
                    ("us-west1-a (Oregon - L4)", "us-west1-a"),
                    ("europe-west4-a (Netherlands - L4)", "europe-west4-a"),
                    ("asia-southeast1-c (Singapore - L4)", "asia-southeast1-c"),
                ]
            elif gpu.startswith("n1-"):
                return [
                    ("us-central1-a (Iowa - T4 Quota Verified) [Recommended]", "us-central1-a"),
                    ("us-central1-b (Iowa - T4)", "us-central1-b"),
                    ("us-central1-f (Iowa - T4)", "us-central1-f"),
                    ("us-east1-c (S. Carolina - T4)", "us-east1-c"),
                    ("us-west1-b (Oregon - T4)", "us-west1-b"),
                ]
            elif gpu.startswith("a2-"):
                return [
                    ("us-central1-a (Iowa - A100 SXM4) [Recommended]", "us-central1-a"),
                    ("us-central1-b (Iowa - A100 SXM4)", "us-central1-b"),
                    ("us-central1-c (Iowa - A100 SXM4)", "us-central1-c"),
                    ("us-east4-b (N. Virginia - A100)", "us-east4-b"),
                ]
            elif gpu.startswith("g4-"):
                return [
                    ("us-central1-b (Iowa - RTX Pro 6000 - Flex-start Verified) [Recommended]", "us-central1-b"),
                    ("us-central1-a (Iowa - RTX Pro 6000)", "us-central1-a"),
                    ("us-east4-a (N. Virginia - RTX Pro 6000)", "us-east4-a"),
                ]
            return [("us-central1-a (Iowa - Default)", "us-central1-a")]
        elif cloud == "aws":
            return [
                ("us-east-1 (N. Virginia) [Recommended]", "us-east-1"),
                ("us-east-2 (Ohio)", "us-east-2"),
                ("us-west-2 (Oregon)", "us-west-2"),
                ("eu-west-1 (Ireland)", "eu-west-1"),
            ]
        elif cloud == "azure":
            return [
                ("eastus (US East) [Recommended]", "eastus"),
                ("westus2 (US West 2)", "westus2"),
                ("westeurope (West Europe)", "westeurope"),
            ]
        elif cloud == "alicloud":
            return [
                ("cn-hangzhou (Hangzhou) [Recommended]", "cn-hangzhou"),
                ("us-west-1 (Silicon Valley)", "us-west-1"),
            ]
        return [("default", "default")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New Isaac Workstation Deployer", id="dialog-title")

            with VerticalScroll(id="deploy-body"):
                yield Label("[bold white]1. Workstation Name:[/]")
                yield Input(value="isaac-ws-01", placeholder="Enter unique deployment name", id="inp-deploy-name")

                yield Label("[bold white]2. Cloud Provider:[/]")
                with RadioSet(id="deploy-cloud-select"):
                    yield RadioButton("Google Cloud (GCP)", value=True, id="rb-cloud-gcp")
                    yield RadioButton("AWS EC2", id="rb-cloud-aws")
                    yield RadioButton("Microsoft Azure", id="rb-cloud-azure")
                    yield RadioButton("Alibaba Cloud", id="rb-cloud-alicloud")

                yield Label("[bold white]3. GPU & Multi-GPU Instance Type:[/]")
                yield Select(
                    options=self.CLOUD_GPUS["gcp"],
                    value=self.selected_gpu,
                    id="sel-deploy-gpu",
                    allow_blank=False,
                )

                yield Label("[bold white]4. Target Zone / Region (GPU-Optimized):[/]")
                yield Select(
                    options=self.get_zones_for_selection("gcp", self.selected_gpu),
                    value=self.selected_zone,
                    id="sel-deploy-zone",
                    allow_blank=False,
                )

                yield Label("[bold white]5. Provisioning & Cost Optimization Model:[/]")
                with RadioSet(id="deploy-scheduling-model"):
                    yield RadioButton("Standard On-Demand (Immediate launch, standard billing)", value=True, id="rb-sched-standard")
                    yield RadioButton("GCP Flex-start (Dynamic Workload Scheduler, 7-day queued run, ./cycle-vm)", id="rb-sched-flex")
                    yield RadioButton("Spot / Preemptible VM (60-91% discount, auto-backup & 30s watchdog)", id="rb-sched-spot")

                yield Label("[bold white]6. Multi-Cloud Security Profile:[/]")
                with RadioSet(id="deploy-profile-select"):
                    yield RadioButton("Tier 1: Simple Mode ($0.00/mo, dynamic /32 IP whitelist)", value=True, id="rb-profile-simple")
                    yield RadioButton("Tier 2: Team Mode (<$0.10/mo, shared GCS/S3 remote state)", id="rb-profile-team")
                    yield RadioButton("Tier 3: Enterprise ($35-$180/mo, Cloud NAT, CMEK, Zero-Trust IAP)", id="rb-profile-enterprise")
                    from src.python.config import list_available_profiles
                    for custom_name, custom_meta in list_available_profiles().items():
                        if custom_name not in ("simple", "team", "enterprise"):
                            yield RadioButton(f"Custom: {custom_name} ({custom_meta.get('tier', 'custom')})", id=f"rb-profile-custom-{custom_name}")

                yield Label("[bold white]7. Optional Pre-Installed Robotics Demos:[/]")
                with Horizontal(classes="checkbox-row"):
                    yield Checkbox("Franka Manipulation", value=True, id="cb-demo-franka")
                    yield Checkbox("Humanoid Locomotion", value=False, id="cb-demo-humanoid")
                    yield Checkbox("Quadruped Locomotion", value=False, id="cb-demo-quadruped")

                yield Static(
                    self.build_summary_text(),
                    id="deploy-summary",
                    classes="box-panel"
                )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Dry Run / Validate", id="btn-deploy-dryrun", variant="warning")
                yield Button("Launch Deployment [Enter]", id="btn-deploy-launch", variant="success")
                yield Button("Cancel [Esc / q]", id="btn-deploy-cancel", variant="error")

    def build_summary_text(self) -> str:
        if self.scheduling_model == "flex":
            sched_badge = "[bold yellow]GCP Flex-start Active (Dynamic Workload Scheduler)[/]"
            resilience_str = (
                "\n[bold yellow]DWS Scheduling:[/] Queued allocation (up to 60m timeout) & 7-day max duration (managed via `./cycle-vm`)."
            )
        elif self.scheduling_model == "spot":
            sched_badge = "[bold green]Spot Discount Active (~60-75% off compute)[/]"
            resilience_str = (
                "\n[bold green]Spot Resilience Pipeline:[/] Active 30s metadata watchdog (`preempt-listener`) & 10-min GCS backups enabled."
                if self.selected_cloud == "gcp" else ""
            )
        else:
            sched_badge = "[dim]Standard On-Demand Compute[/]"
            resilience_str = ""

        prof_desc = "Simple Mode ($0.00/mo added infrastructure). Dynamic /32 IP lock."
        if self.selected_profile == "team":
            prof_desc = "Team Mode (<$0.10/mo storage). Distributed state locking via GCS/S3."
        elif self.selected_profile == "enterprise":
            prof_desc = "Enterprise Mode ($35-$180/mo). Zero public IP, Cloud NAT, CMEK, IAP Zero-Trust."
        elif self.selected_profile not in ("simple", "team", "enterprise"):
            from src.python.config import list_available_profiles
            meta = list_available_profiles().get(self.selected_profile, {})
            prof_desc = f"Custom Profile '{self.selected_profile}' (Tier: {meta.get('tier', 'custom')})."

        return (
            f"[bold cyan]Deployment Preview ({self.selected_cloud.upper()}):[/]\n"
            f"• Instance & GPU: [bold white]{self.selected_gpu}[/] | Zone: [cyan]{self.selected_zone}[/]\n"
            f"• Provisioning Model: {sched_badge}{resilience_str}\n"
            f"• Security & Storage: [white]{prof_desc}[/]"
        )

    def update_summary(self) -> None:
        try:
            summary = self.query_one("#deploy-summary", Static)
            summary.update(self.build_summary_text())
        except Exception:
            pass

    def update_scheduling_visibility(self) -> None:
        try:
            rb_flex = self.query_one("#rb-sched-flex", RadioButton)
            is_gcp = (self.selected_cloud == "gcp")
            rb_flex.display = is_gcp
            if not is_gcp and self.scheduling_model == "flex":
                self.scheduling_model = "standard"
                self.use_flex_start = False
                rb_flex.value = False
                self.query_one("#rb-sched-standard", RadioButton).value = True
        except Exception:
            pass

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "deploy-cloud-select":
            cloud_map = {
                "rb-cloud-gcp": "gcp",
                "rb-cloud-aws": "aws",
                "rb-cloud-azure": "azure",
                "rb-cloud-alicloud": "alicloud",
            }
            self.selected_cloud = cloud_map.get(event.pressed.id, "gcp")
            try:
                gpu_select = self.query_one("#sel-deploy-gpu", Select)
                gpus = self.CLOUD_GPUS.get(self.selected_cloud, self.CLOUD_GPUS["gcp"])
                gpu_select.set_options(gpus)
                self.selected_gpu = gpus[1][1] if len(gpus) > 1 else gpus[0][1]
                gpu_select.value = self.selected_gpu

                zone_select = self.query_one("#sel-deploy-zone", Select)
                zones = self.get_zones_for_selection(self.selected_cloud, self.selected_gpu)
                zone_select.set_options(zones)
                self.selected_zone = zones[0][1]
                zone_select.value = self.selected_zone
            except Exception:
                pass
            self.update_scheduling_visibility()
            self.update_summary()

        elif event.radio_set.id == "deploy-scheduling-model":
            sched_map = {
                "rb-sched-standard": "standard",
                "rb-sched-flex": "flex",
                "rb-sched-spot": "spot",
            }
            self.scheduling_model = sched_map.get(event.pressed.id, "standard")
            self.use_spot = (self.scheduling_model == "spot")
            self.use_flex_start = (self.scheduling_model == "flex")
            self.update_summary()

        elif event.radio_set.id == "deploy-profile-select":
            p_map = {
                "rb-profile-simple": "simple",
                "rb-profile-team": "team",
                "rb-profile-enterprise": "enterprise",
            }
            if event.pressed.id in p_map:
                self.selected_profile = p_map[event.pressed.id]
            elif event.pressed.id.startswith("rb-profile-custom-"):
                self.selected_profile = event.pressed.id.replace("rb-profile-custom-", "")
            else:
                self.selected_profile = "simple"

            self.update_summary()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sel-deploy-gpu":
            self.selected_gpu = str(event.value)
            try:
                zone_select = self.query_one("#sel-deploy-zone", Select)
                zones = self.get_zones_for_selection(self.selected_cloud, self.selected_gpu)
                zone_select.set_options(zones)
                self.selected_zone = zones[0][1]
                zone_select.value = self.selected_zone
            except Exception:
                pass
            self.update_summary()
        elif event.select.id == "sel-deploy-zone":
            self.selected_zone = str(event.value)
            self.update_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-deploy-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-deploy-dryrun":
            self.submit_deployment(dry_run=True)
        elif event.button.id == "btn-deploy-launch":
            self.submit_deployment(dry_run=False)

    def submit_deployment(self, dry_run: bool = False) -> None:
        name_input = self.query_one("#inp-deploy-name", Input)
        name = name_input.value.strip() or "isaac-ws-01"

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
            "gpu": self.selected_gpu,
            "zone": self.selected_zone,
            "spot": (self.scheduling_model == "spot"),
            "flex_start": (self.scheduling_model == "flex"),
            "profile": self.selected_profile,
            "demos": demos,
            "dry_run": dry_run,
        }
        self.dismiss(result)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
