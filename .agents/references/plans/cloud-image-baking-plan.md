# Architectural Plan: Cloud Golden Image Baking for Fast Robotics Workstation Deployment

## Container registry boundary (2026-09-09)

See [Artifact Registry plan](artifact-registry-plan.md) and
[guide](../docs/artifact-registry-guide.md). Artifact Registry stores OCI/Docker
images; it does not replace Packer's GCE/AWS/Azure machine-image storage. Registry
creation is a separate, protected Terraform stack, never part of ephemeral Packer
or workstation teardown. The new Ansible registry role is disabled by default.
The workstation CLI profile handoff does not automatically extend to `image-*`
commands: Packer registry identity, variables, digest prefetch and post-boot pulls
need explicit integration/validation. Never bake service-account keys or
short-lived access tokens into a golden image. Read the new ledger before assuming
the historical readiness and parity claims below have been revalidated.

**Document ID**: `cloud-image-baking-plan.md`  
**Target Subsystems**: HashiCorp Packer (`src/packer/gcp/`, `src/packer/aws/`, `src/packer/azure/`), Native Ansible Engine (`src/ansible/`), Google Compute Engine (GCE), AWS EC2, Azure ARM  
**Primary Target Architecture**: Google Cloud Platform (GCP) `us-central1`, `g2-standard-8` (1x NVIDIA L4 24GB, Ada `sm_89`)  
**Multi-Cloud Parity**: AWS EC2 `g6e.2xlarge` (1x NVIDIA L40S 48GB), Azure `Standard_NV36adms_A10_v5` (1x NVIDIA A10 24GB)  
**Host Architecture Parity**: Physical Workstation, NVIDIA RTX PRO 6000 Blackwell (`sm_120`), CUDA 13.x  
**Active Robotics Stack**: Isaac Sim 6.0.1, Isaac Lab v3 (`v3.0.0-beta2`), IsaacLab-Arena (`release/0.3.0-prerelease`), Whole-Body Control (WBC) Solvers, NVIDIA Isaac-GR00T (`dev/arena_v0.3.0-compat`), Neo4j 5.26  
**Status**: **Configured & Dry-Run Validated** (14 Roles Unified)

---

## 1. Executive Summary & Strategic Rationale

In cloud-native robotics simulation, instance provisioning latency is the single largest operational bottleneck:
- **Dynamic Provisioning (`--not-from-image`)**: Every VM boot starts from raw Ubuntu 22.04 LTS and runs 45–60+ minutes of Ansible provisioning. It repeatedly downloads ~15 GB of Omniverse Kit binaries, builds PyTorch environments, compiles CUDA extensions, and clones Git repositories. This creates significant developer downtime, high network failure surface, and substantial accumulated compute costs during iterative testing.
- **Pre-Baked Golden Image (`--from-image`)**: HashiCorp Packer provisions an ephemeral GPU VM, runs the complete 14-role Ansible playbook once to configure the operating system, remote desktop streaming, Python Conda runtime, Isaac Sim 6.0.1, Isaac Lab v3, Arena WBC solvers, and containerized foundation models/graph databases. Packer then creates a compressed machine image and tears down the build VM. Subsequent workstation deployments launch directly from the pre-baked disk in **2 to 3 minutes**.

This document specifies the end-to-end architecture, configuration, cost profile, and verification procedures for building and managing pre-baked Isaac Workstation images on Google Cloud Platform, while maintaining complete architectural harmony with physical Blackwell workstations and other cloud providers.

---

## 2. Infrastructure Topology & Execution Flow

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator / Agent
    participant Script as ./image-gcp
    participant Packer as HashiCorp Packer (v1.16+)
    participant GCE as Google Compute Engine API
    participant VM as Ephemeral Build VM (g2-standard-8)
    participant Ansible as Ansible Engine (Local Host)

    Operator->>Script: ./image-gcp (non-interactive options)
    Script->>Script: Verify GCP ADC credentials & export GCP_PROJECT
    Script->>Packer: packer build -var-file / -var arguments
    Packer->>GCE: Request instance creation (g2-standard-8 + 1x nvidia-l4 in us-central1-a)
    GCE->>VM: Boot instance from ubuntu-2204-lts with 255GB pd-ssd
    Packer->>VM: Inject ephemeral SSH keys via metadata & establish SSH tunnel
    Packer->>Ansible: Launch ansible-playbook (src/ansible/isaac-workstation.yaml)
    
    rect rgb(240, 248, 255)
        Note over Ansible,VM: Phase 1: Base System, Hardware & Storage Scaffolding
        Ansible->>VM: roles/system: Apt packages, NVMe tools, Node.js LTS, Docker
        Ansible->>VM: roles/system: Pre-create ~/datasets, ~/models, ~/eval, ~/data/neo4j under ubuntu ownership
        Ansible->>VM: roles/auth: Hardware groups (docker, dialout), Git author, API tokens
        Ansible->>VM: roles/nvidia-driver: Deploy NVIDIA Driver 580/550 + CUDA (probes compute cap)
        Ansible->>VM: roles/hardware-teleop: Configure 1ms serial latency udev (ftdi_sio, ttyUSB*, ttyACM*)
    end

    rect rgb(255, 250, 240)
        Note over Ansible,VM: Phase 2: Desktop & Python Tooling
        Ansible->>VM: roles/remote-desktop: Install XFCE4, NoMachine NX, and noVNC streaming
        Ansible->>VM: roles/conda: Deploy Miniconda3, create 'isaaclab' Conda env (Python 3.12)
        Ansible->>VM: roles/conda: Install PyTorch matching GPU arch (cu124 on L4; cu128 ready)
        Ansible->>VM: roles/conda: Deploy escaped isaaclab-env CLI runner & Vulkan ICD hooks
    end

    rect rgb(240, 255, 240)
        Note over Ansible,VM: Phase 3: Robotics Frameworks & Benchmarks
        Ansible->>VM: roles/isaacsim-source: Download & unpack Isaac Sim 6.0.1 Standalone Kit
        Ansible->>VM: roles/isaacsim-source: Deploy sanitized setup_conda_env.sh & 7-line .pth
        Ansible->>VM: roles/isaaclab-source: Deploy Isaac Lab v3.0.0-beta2 with Dual-Remote topology
        Ansible->>VM: roles/isaaclab-arena-source: Clone Arena 0.3.0-prerelease & editable install 8 subpackages
        Ansible->>VM: roles/isaaclab-arena-source: Install WBC solvers (cmeel, pin-pink, daqp, osqp, mujoco)
    end

    rect rgb(250, 240, 255)
        Note over Ansible,VM: Phase 4: Physical AI, Graph Memory & Demos
        Ansible->>VM: roles/neo4j: Pull neo4j:5.26-community, configure ports 7475/7688, systemd service
        Ansible->>VM: roles/gr00t: Configure GR00T foundation stack on Port 5556/5561 with lockfile guard
        Ansible->>VM: roles/lerobot: Install LeRobot camera teleop and policy visualizer
        Ansible->>VM: roles/demos: Desktop shortcuts (G1 humanoid with WBC single-thread guard, Go2, Franka)
        Ansible->>VM: roles/state-ledger: Record software state ledger (~/.isaac-state.json)
    end

    Ansible-->>Packer: All 14 roles completed successfully
    Packer->>VM: Shell cleanup (vacuum journals, remove /tmp, zero free disk blocks)
    Packer->>GCE: Stop instance & create image: isaac-automator-isaacworkstation-<name>
    Packer->>GCE: Register image into family 'isaac-automator-isaacworkstation'
    Packer->>GCE: Delete ephemeral VM and build disks
    GCE-->>Operator: Golden Image ready for immediate deployment (<3 min)
```

---

## 3. Host Environment & Cloud Quota Verification

The build environment on this machine has been verified and meets all prerequisites:

| Component | Verified Specification | Status |
| :--- | :--- | :---: |
| **Packer Binary** | HashiCorp Packer v1.16.0 installed at `/usr/local/bin/packer` | **Ready** |
| **Packer Plugins** | `hashicorp/googlecompute` (v1.2.7), `hashicorp/amazon` (v1.3.4), `hashicorp/azure` (v2.2.1), and `hashicorp/ansible` (v1.1.6) installed | **Ready** |
| **GCP Identity** | Account `bored2engineer@gmail.com` via Application Default Credentials (ADC) | **Ready** |
| **GCP Project** | `cybernetic-renan` | **Active** |
| **GCP GPU Quota** | Region `us-central1`: **16.0 NVIDIA L4 GPUs** available, **0.0 currently in use** | **Available** |
| **GCP CPU Quota** | Region `us-central1`: Sufficient C2/N1/G2 compute capacity | **Available** |
| **Ansible Engine** | Local `ansible-playbook` 2.16+ using `/workspaces/IsaacAutomator/src/ansible/ansible.cfg` | **Ready** |
| **Pre-Flight Dry Run** | `VERSION=v6.0.1 ./image-gcp --dry-run` passed syntax validation for Packer and Ansible | **Verified** |

---

## 4. Packer & Ansible Configuration Specification

### 4.1 HCL Template Configuration ([`src/packer/gcp/isaac-workstation.pkr.hcl`](file:///workspaces/IsaacAutomator/src/packer/gcp/isaac-workstation.pkr.hcl))
The template uses relative path resolution via `${path.root}` to ensure portability:

```hcl
packer {
  required_plugins {
    googlecompute = {
      source  = "github.com/hashicorp/googlecompute"
      version = "~> 1"
    }
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1"
    }
  }
}

source "googlecompute" "isaac-workstation" {
  project_id          = var.gcp_project
  zone                = var.gcp_zone
  machine_type        = var.instance_type # g2-standard-8
  source_image_family = "ubuntu-2204-lts"
  source_image_project_id = ["ubuntu-os-cloud"]

  image_name        = local.expanded_image_name
  image_family      = "isaac-automator-isaacworkstation"
  image_description = "Isaac Automator workstation image (${var.version})"

  disk_size           = 255
  disk_type           = "pd-ssd"
  ssh_username        = "ubuntu"
  on_host_maintenance = "TERMINATE"

  accelerator_type  = "projects/${var.gcp_project}/zones/${var.gcp_zone}/acceleratorTypes/${var.gpu_type}"
  accelerator_count = var.gpu_count

  labels = {
    deployment = "gcp_image"
  }
}

build {
  sources = ["source.googlecompute.isaac-workstation"]

  provisioner "ansible" {
    use_proxy     = false
    groups        = ["isaac_workstation"]
    playbook_file = "${path.root}/../../ansible/isaac-workstation.yaml"
    ansible_env_vars = [
      "ANSIBLE_CONFIG=${path.root}/../../ansible/ansible.cfg"
    ]
    extra_arguments = [
      "--skip-tags", "${var.skip_tags}",
      "--extra-vars", "cloud='gcp' deployment_name='gcp_image' isaacsim_git_checkpoint='${var.isaacsim}' isaaclab_git_checkpoint='${var.isaaclab}' isaaclab_arena_git_checkpoint='${var.isaaclab_arena}' demos='${var.demos}' install_gr00t=${var.install_gr00t} enable_neo4j=${var.enable_neo4j} vnc_password='${var.vnc_password}' system_user_password='${var.system_user_password}' in_china=${var.in_china} uploads_dir='/home/ubuntu/uploads' results_dir='/home/ubuntu/results' workspace_dir='/home/ubuntu/workspace'"
    ]
  }

  provisioner "shell" {
    inline = [
      "sudo rm -rf /tmp/* /var/tmp/*",
      "sudo journalctl --vacuum-size=10M",
      "sudo dd if=/dev/zero of=/EMPTY bs=1M || true",
      "sudo rm -f /EMPTY",
      "sync"
    ]
  }
}
```

### 4.2 Stack & Role Alignment in the Golden Image

The image captures the full 14-role state:

| Role | Target Package / Ref | Key Adjustments in Image |
| :--- | :--- | :--- |
| [**`system`**](file:///workspaces/IsaacAutomator/src/ansible/roles/system) | Ubuntu 22.04 LTS + Utilities | Installs `nvme-cli`, `smartmontools`, `fio`, `iotop`, Node.js LTS, GitHub CLI (`gh`), Docker. Scaffolds `${HOME}/datasets`, `${HOME}/models`, `${HOME}/eval`, `data/neo4j` under `ubuntu:ubuntu` ownership *before* containers execute. |
| [**`auth`**](file:///workspaces/IsaacAutomator/src/ansible/roles/auth) | Hardware Groups & Git Identity | Adds `ubuntu` user to `docker`, `dialout`, `plugdev`, `input`, `video`. Pre-configures Git author. |
| [**`nvidia-driver`**](file:///workspaces/IsaacAutomator/src/ansible/roles/nvidia-driver) | Driver 580/550 + CUDA | Installed on build VM; kernel modules validated. Probes compute capability (`sm_89` on L4; sets `cuda_wheel_flavor: cu124`). |
| [**`remote-desktop`**](file:///workspaces/IsaacAutomator/src/ansible/roles/remote-desktop) | NoMachine + noVNC | Installed & pre-configured; passwords and ephemeral tokens skipped via `skip_in_image`. |
| [**`conda`**](file:///workspaces/IsaacAutomator/src/ansible/roles/conda) | Miniconda3 / Python 3.12 | Pre-creates named `isaaclab` environment; deploys `uv`, dynamically selected PyTorch wheels, escaped `/usr/local/bin/isaaclab-env` CLI shim, and Vulkan ICD hooks. |
| [**`hardware-teleop`**](file:///workspaces/IsaacAutomator/src/ansible/roles/hardware-teleop)| Low-latency serial rules | Deploys `/etc/udev/rules.d/99-ftdi-latency.rules` with `ftdi_sio`, `ttyUSB*`, and `ttyACM*` `latency_timer=1`. Installs `spacenavd` and Intel RealSense SDK. |
| [**`isaacsim-source`**](file:///workspaces/IsaacAutomator/src/ansible/roles/isaacsim-source)| Isaac Sim 6.0.1 Standalone | Downloaded & unpacked to `/opt/nvidia/isaac-sim/releases/6.0.1`; atomic symlink `/home/ubuntu/IsaacSim`; deploys filtered 7-line `.pth` and sanitized `setup_conda_env.sh`. |
| [**`isaaclab-source`**](file:///workspaces/IsaacAutomator/src/ansible/roles/isaaclab-source)| Isaac Lab v3.0.0-beta2 | Cloned and installed via `./isaaclab.sh --conda isaaclab`; configures Dual-Remote Git topology (`origin`/`upstream`). |
| [**`isaaclab-arena-source`**](file:///workspaces/IsaacAutomator/src/ansible/roles/isaaclab-arena-source)| Arena 0.3.0-prerelease | Cloned with submodules; editable pip install across 8 root packages; installs WBC solvers (`pin-pink`, `daqp`, `osqp`, `mujoco`). |
| [**`neo4j`**](file:///workspaces/IsaacAutomator/src/ansible/roles/neo4j)| Neo4j 5.26 Community | Pre-pulls Docker image `neo4j:5.26-community`; configures HTTP port 7475 and Bolt port 7688; deploys `neo4j-arena.service` systemd unit with APOC plugins. |
| [**`gr00t`**](file:///workspaces/IsaacAutomator/src/ansible/roles/gr00t)| GR00T Foundation Model | Pinned to Port **5556** (native) or Port **5561** (container `gr00t-dev:latest`) with `uv sync` lockfile downgrade guard. |
| [**`lerobot`**](file:///workspaces/IsaacAutomator/src/ansible/roles/lerobot)| Hugging Face LeRobot | Cloned and editable installed with `[feetech,realsense]`; adds desktop launcher. |
| [**`demos`**](file:///workspaces/IsaacAutomator/src/ansible/roles/demos)| Physical AI Shortcuts | Deploys desktop shortcuts; enforces single-thread Pinocchio WBC concurrency guard (`--num_envs 1`) in `arena-gr00t.sh.j2`. |
| [**`state-ledger`**](file:///workspaces/IsaacAutomator/src/ansible/roles/state-ledger)| State Ledger & Self-Healing | Generates `/home/ubuntu/.isaac-state.json` recording all component git refs and package versions; hooks boot-time self-healing repair. |

---

## 5. Execution Procedures

### Step 1: Pre-Flight Dry-Run Validation (Zero Cost)
Validate the Packer HCL syntax, GCP project authentication, and Ansible playbook structure without launching cloud infrastructure:

```bash
VERSION=v6.0.1 ./image-gcp --dry-run \
  --image-name test-image \
  --project cybernetic-renan \
  --zone us-central1-a \
  --instance-type g2-standard-8 \
  --gpu-type nvidia-l4 \
  --gpu-count 1 \
  --isaacsim v6.0.1 \
  --isaaclab v3.0.0-beta2 \
  --isaaclab-arena release/0.3.0-prerelease \
  --system-user-password "TemporaryValidationPass123!" \
  --existing overwrite
```
*Expected Result*: Outputs `✓ Dry-run complete: Packer template and Ansible playbooks are fully valid!` with zero compute cost.

### Step 2: Live-Fire Image Baking Command
Execute the full image build. Run strictly non-interactively to prevent agent hangs:

```bash
VERSION=v6.0.1 ./image-gcp \
  --image-name isaac-workstation-601-l4 \
  --project cybernetic-renan \
  --zone us-central1-a \
  --instance-type g2-standard-8 \
  --gpu-type nvidia-l4 \
  --gpu-count 1 \
  --isaacsim v6.0.1 \
  --isaaclab v3.0.0-beta2 \
  --isaaclab-arena release/0.3.0-prerelease \
  --system-user-password "YourDeploymentUserPasswordHere" \
  --existing overwrite
```

### Step 3: Verify Image in GCP Catalog
Once Packer outputs `* Image build complete!`, verify the image exists in GCE:

```bash
gcloud compute images describe isaac-automator-isaacworkstation-isaac-workstation-601-l4 \
  --project=cybernetic-renan \
  --format="table(name,family,status,diskSizeGb)"
```

### Step 4: Rapid Workstation Deployment from Golden Image
Deploy a new workstation from the baked image in under 3 minutes:

```bash
./deploy-gcp isaac-prod-01 \
  --from-image \
  --project cybernetic-renan \
  --zone us-central1-a \
  --instance-type g2-standard-8 \
  --gpu-type nvidia-l4 \
  --ingress-cidrs myip \
  --existing replace
```

---

## 6. Financial Profile & Resource Safety

- **Hourly Rate**: GCE `g2-standard-8` with 1x NVIDIA L4 GPU costs approximately **$0.85/hour** in `us-central1`.
- **Total Build Cost**: A standard 50-minute image build consumes ~0.83 compute hours, costing **~$0.71 USD**.
- **Storage Cost**: Storing the custom compressed GCE image costs **~$0.05/GB/month** (for a ~30GB compressed image, approx. **$1.50/month**).
- **Cleanup Guarantee**: If the Packer build fails or succeeds, Packer automatically sends an API call to delete the ephemeral build VM and attached disks. No orphan compute instances remain running.

---

## 7. Troubleshooting & Failure Recovery

| Symptom | Probable Cause | Remediation |
| :--- | :--- | :--- |
| **`Permission denied (publickey)` during Ansible run** | GCE metadata propagation delay for Packer SSH key | Packer retries SSH automatically for up to 10 minutes. Check VPC firewall allows port 22. |
| **`Quota exceeded for NVIDIA_L4_GPUS`** | Project GPU quota reached in selected zone | Verified: `cybernetic-renan` has 16 L4 quota in `us-central1`. If zone capacity is constrained, switch `--zone us-central1-b` or `us-central1-c`. |
| **`Address already in use: 5555`** | Service port collision | GR00T role is reconfigured to port **5556** (native) or **5561** (container). |
| **`Address already in use: 7474 / 7687`** | Neo4j default port collision | Neo4j role maps external host ports to **7475** (HTTP) and **7688** (Bolt). |
| **`PermissionError: [Errno 13]` in datasets/models** | Container daemon created directories as `root:root` | Handled by `roles/system/tasks/directories.yml` which creates the entire storage hierarchy under `ubuntu:ubuntu` before Docker runs. |
| **`Disk full during Isaac Sim extraction`** | Insufficient root disk | Template allocates `disk_size = 255` GB `pd-ssd`. Isaac Sim extraction requires ~35 GB free. |
| **`image-gcp prompts for input and hangs`** | Omitted required CLI argument | Always pass `--existing overwrite`, `--system-user-password`, `--project`, `--zone`, and version flags. |
| **`Pinocchio WBC deadlock on multi-env`** | Non-threadsafe QP trajectory solver | Handled by `roles/demos/templates/arena-gr00t.sh.j2` which enforces `--num_envs 1`. |
