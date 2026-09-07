# Isaac Automator - Declarative Deployment & Security Profiles

Declarative profiles allow you to configure cloud infrastructure, networking, security tiers, remote Terraform state backends, and workstation applications in a reproducible, version-controlled YAML file.

Instead of passing dozens of command-line flags on every deployment, you can specify a profile with `--profile <name_or_path>`:

```bash
./deploy-gcp \
  --deployment-name studio-rig \
  --project my-gcp-project \
  --zone us-central1-b \
  --profile configs/profiles/custom-developer.yaml \
  --existing replace \
  --dry-run
```

---

## 1. Security Tiers & Cost Overhead

Isaac Automator categorizes infrastructure setups into three standardized security tiers, plus a granular **Custom** mode:

| Tier | Profile Example | Added Infra Cost | Network & Ingress | Terraform State Backend | Cryptography & Secrets | Ideal For |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Simple** | [`simple-workstation.yaml`](simple-workstation.yaml) | **$0.00 / month** | Ephemeral public IP, firewall auto-locked to caller `/32` CIDR | Local (`./state/<name>/.tfstate`) | Cloud default encryption, environment variables | Solo developers, researchers, personal experiments |
| **Team** | [`team-studio.yaml`](team-studio.yaml) | **<$0.10 / month** | Ephemeral public IP, firewall auto-locked to caller or team CIDRs | Remote GCS bucket (`auto`) with distributed object locking | Cloud default encryption, Google Secret Manager | Small teams, shared projects, CI/CD runners |
| **Enterprise** | [`enterprise-zero-trust.yaml`](enterprise-zero-trust.yaml) | **~$35 - $180+ / mo** | Zero Public IP (Cloud IAP TCP Tunnel only), Managed Cloud NAT Gateway | Remote GCS bucket (`auto`) with object locking & soft delete | Regional KMS CMEK auto-rotation, Secret Manager, OS Login 2FA | Enterprise compliance, regulated industries, corporate perimeters |
| **Studio Enterprise** | [`studio-enterprise.yaml`](studio-enterprise.yaml) | **~$35 - $180+ / mo** | Zero Public IP (Cloud IAP / SSM / Bastion), Managed Cloud NAT | Remote GCS/S3 bucket (`auto`) with distributed object locking | Regional KMS CMEK auto-rotation, Secret Manager, OS Login 2FA | Production robotics studios co-located with Omniverse Nucleus & high-speed shared USD storage |
| **Custom** | [`custom-developer.yaml`](custom-developer.yaml) | *Granular / Variable* | Selectable (IAP or Public /32 lock, Cloud NAT toggle) | Selectable (`local` or `gcs`) | Selectable (`google_managed` or `kms_cmek`) | Hybrid setups balancing security, remote state, and cost |

---

## 2. Profile Discovery & Precedence

When you pass the `--profile` (or `--security-profile`) option, Isaac Automator resolves the configuration using the following priority order:

1. **Direct File Path**: If the argument points to an existing file (e.g. `--profile configs/profiles/my-profile.yaml` or `--profile /opt/profiles/custom.yaml`), it is parsed directly.
2. **Repository Profiles Directory**: If an unadorned name is provided (e.g. `--profile custom-developer`), Isaac Automator searches `configs/profiles/<name>.yaml`.
3. **User Home Directory**: If not found in the repo, Isaac Automator checks `~/.isaacautomator/profiles/<name>.yaml`.
4. **Built-In Presets**: Standard keywords (`simple`, `team`, `enterprise`) map directly to the built-in defaults.

> [!TIP]
> **CLI Flags Take Precedence:** Explicit CLI arguments override profile settings. For example, if your profile sets `state_bucket: "auto"`, but you run with `--state-bucket gs://my-override-bucket`, the command-line value will be used.

---

## 3. Profile Schema Reference (`v1alpha1`)

All profiles use YAML with the `schema_version: "v1alpha1"` header:

```yaml
# Top-level Metadata
schema_version: "v1alpha1"          # Required: schema specification version
profile_name: "custom-developer"    # Unique identifier for this profile
description: "Custom workstation"   # Human-readable summary
cloud: "gcp"                        # Target cloud provider (gcp, aws, azure, alicloud)

security:
  tier: "custom"                    # Tier label: simple | team | enterprise | custom

  network:
    iap_only: false                 # true = zero public IP (Cloud IAP tunnel only); false = direct public IP
    cloud_nat: false                # true = deploy Cloud NAT gateway (~$32.40/mo); required if iap_only is true
    ingress_cidrs: ["auto"]         # ["auto"] auto-detects caller public IP (/32 lock); or list specific CIDRs: ["1.2.3.4/32"]

  storage:
    state_backend: "gcs"            # "local" (./state/<name>/) or "gcs" (remote object store)
    state_bucket: "auto"            # "auto" (auto-provisions isaacautomator-state-<project>-<region>) or bucket name
    state_locking: true             # true = enable distributed state locking to prevent concurrent overwrite
    soft_delete_days: 7             # GCS retention policy window for disaster recovery

  cryptography:
    encryption_type: "google_managed" # "google_managed" ($0/mo) or "kms_cmek" (Customer-Managed Encryption Keys)
    kms_keyring_name: ""            # "auto" or explicit Cloud KMS key ring name if kms_cmek is enabled

  compute:
    shielded_vm: true               # true = Secure Boot, vTPM, and Integrity Monitoring ($0.00/mo)
    os_login: false                 # true = Google Cloud OS Login IAM with mandatory 2FA; false = SSH keypair
    service_account_type: "dedicated" # "default" (Compute Engine default SA) or "dedicated" (least-privilege SA)

  secrets:
    engine: "secret_manager"        # "env_vars" (local environment variables) or "secret_manager" (Google Secret Manager)

workstation:
  gpu_model: "g4-standard-48"       # Recommended machine type (e.g. g4-standard-48, g2-standard-8)
  demos:
    - "franka-manipulation"         # Pre-configured robotics shortcuts to install on desktop
    - "quadruped-locomotion"
  remote_desktop: "standard"        # Remote display stack: standard | nomachine | dcv | kasmvnc
```

---

## 4. Complex Studio Architecture Profile (`studio-enterprise.yaml`)

For production robotics teams, Isaac Workstations rarely operate as isolated standalone machines. Instead, they operate inside a **multi-node studio architecture** co-located with **NVIDIA Omniverse Nucleus Enterprise**, high-throughput shared USD storage, and centralized IAM/secrets management (as diagrammed in [`.agents/references/plans/network-plans.md`](../../.agents/references/plans/network-plans.md)).

The [`studio-enterprise.yaml`](studio-enterprise.yaml) profile is specifically engineered for this complex topology.

### 4.1 Why Use the Studio Enterprise Profile?

1. **Zero-Egress High-Throughput USD Asset Pipeline**:
   * Robotics USD environments, textures, and asset libraries frequently reach hundreds of gigabytes.
   * By deploying the workstation into the same VPC/VNet as the Omniverse Nucleus cluster and shared NFS volume (**Google Cloud Filestore Enterprise**, **Amazon EFS Elastic Throughput**, or **Azure NetApp Files**), USD assets stream over the sub-millisecond cloud internal fabric.
   * Eliminates 100% of inter-cloud and public internet data egress fees (**$0.00 egress cost**).
2. **Enterprise Zero-Trust Perimeter**:
   * **Zero Public IP**: The workstation has no external IP address, eliminating public port scans and unauthorized access vectors.
   * **Private Tunneling**: Access is restricted strictly to identity-aware TCP tunneling (**Cloud IAP** on GCP, **AWS SSM Session Manager**, or **Azure Bastion**).
   * **Cloud NAT Gateway**: Outbound APT package installs, Docker pulls, and pip updates route cleanly through an isolated Cloud NAT without exposing listening ports.
   * **Customer-Managed Encryption Keys (KMS CMEK)**: All workstation boot disks, persistent volumes, and remote state buckets are sealed under customer-controlled encryption keys with automated 90-day cryptographic rotation.
   * **Centralized Identity with 2FA**: Replaces loose SSH keypairs with corporate IAM (**Google Cloud OS Login**, **Microsoft Entra ID**, or **AWS IAM Identity Center**) requiring mandatory two-factor authentication.
3. **Hardware-Accelerated 3D Viewport Streaming**:
   * Isaac Sim and Omniverse Kit render via native Vulkan surface rendering that standard 2D VNC/noVNC cannot capture (resulting in a black or frozen viewport).
   * The profile configures dual hardware-accelerated remote desktop providers: **NICE DCV** and **NoMachine** (`remote_desktop: "dcv,nomachine"`), delivering low-latency 60fps 3D simulation streaming across private networks.
4. **Distributed Team State Locking**:
   * State is stored in a hardened cloud storage bucket (`gs://` or `s3://`) with distributed object locking.
   * Multiple engineers, CI/CD runners, and automation pipelines can operate concurrently without risking Terraform state corruption or conflicting deployments.
5. **Spot Resilience & Automated Checkpoint Synchronization**:
   * Operates cost-effectively on Spot / Preemptible GPU instances.
   * Includes a 30-second instance termination listener and continuous 10-minute snapshot timer that syncs local workspaces to cloud object storage.

---

### 4.2 Infrastructure Verification: What Isaac Automator Deploys vs. Shared Studio Services

When planning a full studio deployment, understand the clean division of responsibilities:

| Subsystem | Managed by Isaac Automator (`studio-enterprise`) | Managed by Shared Studio Infrastructure (e.g. `nucleus-terraform`) | Integration Point |
| :--- | :--- | :--- | :--- |
| **Robotics Workstation** | ✅ Provisions GPU instance (`g4-standard-48` / `g5.4xlarge`), NVIDIA drivers, Isaac Sim, Isaac Lab, IsaacLab-Arena, and desktop shortcuts | ❌ Out of scope | Operates in Private Workstation Subnet (`10.x.4.0/24`) |
| **Display Streaming** | ✅ Pre-installs NICE DCV, NoMachine, and WebRTC streaming daemons | ❌ Out of scope | Accessed via IAP / Bastion / SSM tunneling |
| **Perimeter Ingress & TLS** | ❌ Out of scope (workstation is fully private) | ✅ Deploys Cloud Application Load Balancer / App Gateway with Port 443 SSL termination | ALB routes public HTTPS/WSS to internal Nucleus Core / Navigator |
| **Omniverse Nucleus Stack** | ❌ Out of scope | ✅ Deploys Nucleus Core, LFT (Large File Transfer), Auth, Discovery, Navigator microservices | Workstation connects via internal DNS: `http://nucleus.studio.internal:3100` |
| **Shared USD Asset Storage** | ❌ Out of scope | ✅ Deploys Google Cloud Filestore Enterprise, AWS EFS, or Azure NetApp Files | Workstation mounts shared NFS share at `/mnt/nucleus` |
| **AI Farm & DeepSearch** | ❌ Out of scope | ✅ Deploys Farm queue workers and CLIP AI vector indexers | Dispatches background render / indexing tasks |
| **Network & Security** | ✅ Provisions Private Subnet, Cloud Router, Cloud NAT, IAP ingress firewall, CMEK Key Ring, Secret Manager | ✅ Provisions Ingress Subnet, Application Subnet, and Storage Subnet | Co-located within the same VPC (`10.x.0.0/16`) or peered network |

### 4.3 Deploying with the Studio Enterprise Profile

To deploy a workstation configured for the studio environment:

```bash
# GCP Studio Workstation
./deploy-gcp \
  --deployment-name studio-workstation-01 \
  --project my-studio-project \
  --zone us-central1-b \
  --instance-type g4-standard-48 \
  --isaac-workstation-gpu-count 1 \
  --ingress-cidrs myip \
  --profile studio-enterprise \
  --existing replace
```

To connect the deployed workstation to the studio's shared Filestore / EFS asset volume after launch:
```bash
# Inside the workstation via SSH or IAP:
sudo mkdir -p /mnt/nucleus
sudo mount -t nfs 10.10.5.2:/nucleus_assets /mnt/nucleus
```

---

## 5. How to Create a Custom Profile (Step-by-Step)

### Step 1: Copy a Template
Start from an existing profile in this directory:
```bash
cp configs/profiles/simple-workstation.yaml configs/profiles/my-robotics-profile.yaml
```

### Step 2: Edit Your Settings
Open `configs/profiles/my-robotics-profile.yaml` in your editor. For example, to create a hybrid developer setup with remote state locking and Google Secret Manager:

```yaml
schema_version: "v1alpha1"
profile_name: "my-robotics-profile"
description: "My custom workstation with remote GCS state and auto IP lock"
cloud: "gcp"

security:
  tier: "custom"
  network:
    iap_only: false
    cloud_nat: false
    ingress_cidrs: ["auto"]
  storage:
    state_backend: "gcs"
    state_bucket: "auto"
    state_locking: true
    soft_delete_days: 7
  cryptography:
    encryption_type: "google_managed"
    kms_keyring_name: ""
  compute:
    shielded_vm: true
    os_login: false
    service_account_type: "dedicated"
  secrets:
    engine: "secret_manager"

workstation:
  gpu_model: "g4-standard-48"
  demos: ["franka-manipulation"]
  remote_desktop: "standard"
```

### Step 3: Validate with a Dry-Run
Run `./deploy-gcp` with `--dry-run` to validate your profile against Terraform and Ansible syntax checks without incurring cloud costs:

```bash
./deploy-gcp \
  --deployment-name test-rig \
  --project my-project-id \
  --zone us-central1-b \
  --profile my-robotics-profile \
  --existing replace \
  --no-upload \
  --dry-run
```

### Step 4: Deploy for Real
When you are ready to provision, remove `--dry-run`:

```bash
./deploy-gcp \
  --deployment-name test-rig \
  --project my-project-id \
  --zone us-central1-b \
  --profile my-robotics-profile \
  --existing replace
```

---

## 6. Visual Profile Configurator (`isaac9s`)

You can also design, cost-estimate, and export custom profiles interactively using the built-in terminal cockpit:

1. Launch `isaac9s`:
   ```bash
   ./run isaac9s
   # Or directly inside the container:
   isaac9s
   ```
2. Navigate to the **Profiles** screen (tab 2).
3. Select **Special Custom Mode** to interactively toggle individual subsystems (Cloud NAT, GCS State, KMS CMEK, Shielded VM, OS Login, Secret Manager).
4. Review the dynamic monthly cost calculator.
5. Enter a profile name and click **Save Custom Profile** to automatically serialize it into `configs/profiles/<profile_name>.yaml`.
