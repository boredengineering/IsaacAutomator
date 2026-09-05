# isaac9s - The Terminal Cockpit for Physical AI & Multi-Cloud Fleet Management
**User Guide, Architecture, Keyboard Shortcuts & Operator Runbook**

---

## 1. Introduction

`isaac9s` is a high-performance terminal graphical user interface (TUI/GUI) built in **Python 3 (Textual 8.2 & Rich 15)**. Inspired by `k9s` (the Kubernetes cluster management console), `isaac9s` delivers an interactive, single-pane-of-glass operations cockpit for:

1. **Physical Bare-Metal Workstations**: Local robotics rigs provisioned via `isaac-installer` with NVIDIA RTX GPUs, DKMS drivers, real-time Vulkan ICD bridges, and FTDI 1ms low-latency USB serial devices.
2. **Multi-Cloud GPU Fleets**: Virtual workstations running NVIDIA Isaac Sim, Isaac Lab, IsaacLab-Arena, and Isaac-GR00T across **AWS, GCP, Azure, and Alibaba Cloud**.
3. **Dynamic Security & Declarative Profiles**: In-cockpit customization of Zero-Trust perimeters, Cloud IAP tunnels, GCS remote state locking, and real-time cloud infrastructure cost estimation.

---

## 2. Launching isaac9s

Run `isaac9s` directly from the repository root:

```bash
# Launch via top-level executable
./isaac9s

# Or invoke directly with Python
PYTHONPATH=. python3 src/tui/app.py
```

`isaac9s` runs directly inside the DevContainer or host environment without external graphical window servers (X11 forwarding is not required).

---

## 3. Global Navigation & Hotkey Reference

### Top Navigation Tabs
Press number keys `[1]` through `[7]` or click tabs at the top:

| Key | Tab / Screen | Purpose |
| :---: | :--- | :--- |
| `1` | **Subsystems** | Physical AI health auditor & automated state drift reconciler |
| `2` | **Workstations** | Multi-cloud fleet manager, lifecycle controls (start/stop/destroy/inspect) |
| `3` | **Remote** | Remote desktop streaming launcher (noVNC, KasmVNC, NoMachine, DCV) |
| `4` | **Logs** | Real-time asynchronous log streamer for background deployer/healer tasks |
| `5` | **Doctor / Pre-Flight** | Pre-flight environment diagnostics & Cloud Auth Bridge modal |
| `6` | **Profiles** | Declarative profile configurator, Custom Mode builder & live cost calculator |
| `7` | **HW Telemetry** | High-speed GPU (VRAM, power, temp) & NVMe storage diagnostics |

### Command Palette & Global Keys

| Key / Command | Action |
| :---: | :--- |
| `:` | **Vim Command Palette**: Type `:deploy`, `:auth`, `:doctor`, `:inspect`, `:remote`, `:profile`, `:logs`, or `:quit` |
| `/` | **Universal Search Filter**: Filter rows in Subsystems and Workstations tables |
| `n` or `:deploy` | Open the **In-Cockpit Workstation Deployer Wizard Modal** |
| `a` or `:auth` | Open the **Cloud Authentication & SSO Bridge Modal** |
| `i` or `:inspect` | Open the **Workstation Deep Inspector & Raw .tfstate Drawer** |
| `p` or `:profile` | Switch to **Declarative Profile & Security Configurator** |
| `r` or `:remote` | Open **Remote Desktop Streaming Selector** for the active workstation |
| `?` | Toggle the Help & Keyboard Reference overlay |
| `q` or `Ctrl+C` | Gracefully quit `isaac9s` |

---

## 4. Screen-by-Screen Operator Manual

### Screen 1: Subsystems & Physical AI Auditor (`[1]`)
* **What it monitors**: Probes the 14 core Physical AI layers:
  * Hardware & Drivers: NVIDIA Driver, DKMS, CUDA Runtime, Vulkan ICD Bridge.
  * Python & Environment: Named Conda runtime (`isaaclab`), UV Package Engine.
  * Robotics Stack: Isaac Sim Engine (Kit), Isaac Lab editable source, IsaacLab-Arena.
  * Physical AI & Controls: Isaac-GR00T (VLA), Pinocchio/Pink WBC, ZeroMQ Policy IPC.
  * Workstation Peripherals: Remote Desktop X11 display, Dual-Remote Git forks.
* **Actions**:
  * Press `p` to force an immediate re-probe across all subsystems.
  * Press `h` to invoke the automated **Self-Healing Drift Reconciler**.
  * Press `a` to run pre-flight audit tests.

---

### Screen 2: Multi-Cloud Fleet & Lifecycle Manager (`[2]`)
* **What it monitors**: Lists all deployed instances across AWS, GCP, Azure, and local nodes. Displays instance name, cloud, region, GPU type, public/private IP, uptime, state, and hourly burn rate.
* **Actions on Selected Workstation**:
  * `s` : **Start Workstation** (resume paused VM).
  * `x` : **Stop Workstation** (pauses compute charges while preserving NVMe disk).
  * `d` : **Destroy Workstation** (prompts confirmation and deletes all cloud resources).
  * `i` : **Inspect Details** (opens Deep Inspector drawer displaying full metadata and raw `.tfstate` resources).
  * `c` : **Connect** (launches default SSH or remote desktop session).
  * `n` : **New Deploy** (opens the in-cockpit deploy modal).

---

### Screen 3: Remote Desktop & 3D Streaming Selector (`[3]`)
* Supports hardware-accelerated remote streaming protocols:
  1. **noVNC (Port 6080)**: Direct HTML5 browser desktop (zero client install required).
  2. **KasmVNC (Port 8444)**: Modern HTTPS WebRTC desktop with native clipboard support.
  3. **NoMachine (Port 4000)**: Native client recommended for interactive 3D Vulkan Kit viewports.
  4. **NICE DCV (Port 8443)**: Enterprise GPU streaming with UDP QUIC acceleration.
  5. **SSH (Port 22 / Custom)**: Interactive shell terminal (supports standard SSH or Google IAP tunnel).

---

### Screen 4: Asynchronous Log Streamer (`[4]`)
* Captures and displays real-time output from Terraform provisioning, Ansible playbooks, and background container builds.
* Press `c` to clear the log pane.
* Auto-scrolls to the newest output during active deployments.

---

### Screen 5: Doctor & Cloud Authentication Bridge (`[5]`)
* **Environment Diagnostics**: Checks host prerequisites (Docker daemon, Cloud CLIs: `aws`, `gcloud`, `az`, `aliyun`, Git, SSH keys).
* **Cloud Auth Bridge Modal (`a`)**:
  * Interactive wizard guiding operators through AWS IAM Identity Center (SSO) device-code flows and GCP Application Default Credentials (`gcloud auth login`).
  * Provides one-click browser opening and instant credential verification.

---

### Screen 6: Declarative Profiles & Dynamic Cost Estimator (`[6]`)
* Allows operators to switch between pre-configured presets or tailor custom infrastructure:
  1. **Tier 1: Simple Mode** ($0.00/mo added cost, /32 IP firewall lock).
  2. **Tier 2: Team Mode** (<$0.10/mo, remote GCS state with distributed concurrency locking).
  3. **Tier 3: Enterprise Mode** (~$35 - $180/mo, Zero Public IP, Cloud IAP, Cloud NAT, KMS CMEK, Shielded VM, OS Login).
  4. **Special Custom Mode**: Granular interactive checkboxes for each individual feature with real-time recalculation of added cloud overhead.
* Press `s` to save your custom configuration as a reusable declarative YAML profile in `configs/profiles/<profile_name>.yaml`.

---

### Screen 7: Deep Hardware & NVMe Telemetry (`[7]`)
* **Live GPU Metrics**: Samples GPU core clocks, memory clocks, temperature, fan speed, power draw (Watts), and VRAM allocation breakdown (Kit engine vs PyTorch CUDA context vs Compositor).
* **NVMe Storage & Health**: Mountpoint usage, filesystem capacity, S.M.A.R.T. health status, and NVMe controller temperature.
* Press `r` to manually refresh metrics or `Space` to toggle 1-second auto-sampling.
