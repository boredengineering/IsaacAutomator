![Isaac Automator](src/banner.png)

# Isaac Automator (v4.2)

Isaac Automator deploys **NVIDIA Isaac Sim**, **Isaac Lab**, and **Isaac Lab Arena** to public clouds (AWS, GCP, Azure, and Alibaba Cloud) as ready-to-use GPU **Isaac Workstations** in minutes.

The result is a fully configured remote desktop cloud VM with NVIDIA drivers, Isaac software, high-performance GUI and 3D streaming (noVNC, KasmVNC, NoMachine, NICE DCV, xrdp, Sunshine+Moonlight, Parsec), automated lifecycle management (start/stop/destroy/cycle), and automated state resilience for Spot and Flex-start cost savings.

---

## Table of Contents

- [TLDR ;)](#tldr-)
- [Development Environments](#development-environments)
  - [Option A: VS Code DevContainer (Recommended)](#option-a-vs-code-devcontainer-recommended)
  - [Option B: Local Docker CLI](#option-b-local-docker-cli)
- [Using with AI Agents](#using-with-ai-agents)
- [Deploying an Isaac Workstation](#deploying-an-isaac-workstation)
  - [AWS](#aws)
  - [GCP (Google Cloud Platform)](#gcp-google-cloud-platform)
  - [Azure](#azure)
  - [Alibaba Cloud](#alibaba-cloud)
  - [Common Deploy Options](#common-deploy-options)
- [Remote Desktop & Interactive 3D Streaming](#remote-desktop--interactive-3d-streaming)
  - [Supported Providers](#supported-providers)
  - [1. noVNC (Standard HTML5 Web Desktop)](#1-novnc-standard-html5-web-desktop)
  - [2. KasmVNC (WebRTC Browser Desktop with Native Clipboard)](#2-kasmvnc-webrtc-browser-desktop-with-native-clipboard)
  - [3. NoMachine (Hardware-Accelerated 3D Viewport)](#3-nomachine-hardware-accelerated-3d-viewport)
  - [4. NICE DCV (Enterprise GPU Streaming)](#4-nice-dcv-enterprise-gpu-streaming)
  - [5. xrdp (Native Windows / Mac Remote Desktop)](#5-xrdp-native-windows--mac-remote-desktop)
  - [6. Sunshine + Moonlight (Ultra-Low Latency 60/120 FPS Streaming)](#6-sunshine--moonlight-ultra-low-latency-60120-fps-streaming)
  - [7. Parsec (Interactive Streaming Daemon)](#7-parsec-interactive-streaming-daemon)
  - [8. SSH Shell](#8-ssh-shell)
- [Reusing Existing Machines & In-Place Updates](#reusing-existing-machines--in-place-updates)
- [Spot Preemption Resilience & State Backups (GCP)](#spot-preemption-resilience--state-backups-gcp)
  - [30-Second Preemption Watchdog](#30-second-preemption-watchdog)
  - [10-Minute Continuous Backup Timer](#10-minute-continuous-backup-timer)
  - [Restoring State with `./restore-gcp`](#restoring-state-with-restore-gcp)
- [Pausing, Resuming & VM Cycling](#pausing-resuming--vm-cycling)
  - [Stop and Start](#stop-and-start)
  - [GCP Flex-start 7-Day VM Cycling (`./cycle-vm`)](#gcp-flex-start-7-day-vm-cycling-cycle-vm)
- [Data Transfer & Standard Folders](#data-transfer--standard-folders)
- [Maintenance, Repair & Teardown](#maintenance-repair--teardown)
  - [Repairing Deployments](#repairing-deployments)
  - [Tearing Down Deployments](#tearing-down-deployments)
  - [Pre-Built Golden Images](#pre-built-golden-images)
- [License](#license)

---

## TLDR ;)

```sh
# Option 1: Using VS Code DevContainer
# Simply open the repo in VS Code -> "Reopen in Container" -> Run commands directly:
./deploy-gcp my-workstation --flex-start --backup-bucket gs://my-isaac-backups/
./novnc my-workstation         # stream desktop in browser
./destroy my-workstation --yes # clean up when done

# Option 2: Using Local Docker CLI
./build                        # build Isaac Automator tool container (one-time)
./run                          # enter container environment
./deploy-aws my-workstation    # follow prompts to deploy
./novnc my-workstation
./destroy my-workstation --yes
```

---

## Development Environments

### Option A: VS Code DevContainer (Recommended)

Isaac Automator provides a fully containerized, zero-setup developer environment using the official OCI DevContainer specification.

1. Install [VS Code](https://code.visualstudio.com/) and the [Dev Containers Extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
2. Open this repository in VS Code and select **"Reopen in Container"** when prompted.
3. The DevContainer automatically configures:
   * **Pre-bundled Cloud Tools:** Terraform 1.8, AWS CLI v2, Google Cloud SDK (`gcloud`), Azure CLI, and AliCloud CLI.
   * **Host Credential Passthrough:** Automatically passes through `~/.aws`, `~/.config/gcloud`, and `~/.azure` from your host system.
   * **Performance Volume Caching:** `/opt/tf-data` persistent volume cache for smooth Terraform execution without macOS VirtioFS filesystem locks.
   * **Direct Terminal Execution:** Run all deployment, management, and repair commands directly in the integrated terminal without needing the `./run` wrapper.

### Option B: Local Docker CLI

You can also run Isaac Automator directly via Docker from Linux, macOS, or Windows:

```sh
# 1. Build the automator container image
./build

# 2. Launch commands via the ./run wrapper:
./run ./deploy-gcp
# Or enter an interactive container shell:
./run
```

---

## Using with AI Agents

Isaac Automator provides first-class, non-interactive instructions and native skills for AI agents:

* **Operator Guide:** Agents operating workstations should follow [`ai/automator.agent.md`](ai/automator.agent.md) and [`AGENTS.md`](AGENTS.md).
* **Native Agent Skills:** Modular, executable procedures located in [`.agents/skills/isaac-automator/`](.agents/skills/isaac-automator/):
  * `deploy-workstation` — Non-interactive cloud provisioning.
  * `manage-lifecycle` — Start, stop, cycle, repair, and destroy workflows.
  * `connect-workstation` — Web desktop, 3D viewport, and SSH tunnels.
  * `run-demos` — Out-of-the-box Isaac Sim / Lab RL robotics demos.
  * `transfer-data` — Bi-directional file synchronization and autorun setup.
  * `troubleshoot` — Common failure diagnostics and auto-repair.
* **Persistent Session Memory:** Agents track multi-session progress in [`.agents/memory/INDEX.md`](.agents/memory/INDEX.md).

---

## Deploying an Isaac Workstation

### AWS

```sh
./deploy-aws <deployment-name> \
  --instance-type g6e.2xlarge \
  --isaacsim latest \
  --isaaclab latest \
  --remote-desktop standard,dcv \
  --demos quadruped-locomotion
```

* Supported instances: `g4dn.*` (T4), `g5.*` (A10G), `g6.*` (L4), `g6e.*` (L40S).
* AWS SSO credentials are authenticated interactively or via environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).

### GCP (Google Cloud Platform)

```sh
./deploy-gcp <deployment-name> \
  --project my-gcp-project \
  --zone us-central1-a \
  --instance-type g2-standard-8 \
  --isaac-workstation-gpu-count 1 \
  --flex-start \
  --backup-bucket gs://my-bucket/backups \
  --remote-desktop standard,kasmvnc \
  --auto-restore
```

* Supported GPUs: NVIDIA L4 (`g2-*`), NVIDIA T4 (`n1-*`), NVIDIA RTX PRO 6000 (`g4-*`).
* **Flex-start:** Enable Dynamic Workload Scheduling with `--flex-start` for substantial cloud cost savings.
* **State Backups:** Pass `--backup-bucket <gcs-uri>` to enable automated state persistence and preemption protection.

### Azure

```sh
./deploy-azure <deployment-name> \
  --region westus3 \
  --instance-type Standard_NV36ads_A10_v5 \
  --remote-desktop standard,xrdp
```

### Alibaba Cloud

```sh
./deploy-alicloud <deployment-name> \
  --region us-east-1 \
  --instance-type ecs.gn7i-c16g1.4xlarge
```

### Common Deploy Options

| Option | Description | Default |
| :--- | :--- | :--- |
| `--remote-desktop` | Remote desktop & streaming providers (`standard`, `kasmvnc`, `dcv`, `xrdp`, `sunshine`, `parsec`, `all`, `no`) | `standard` |
| `--isaacsim` | Git ref for Isaac Sim, or `latest` / `no` | `latest` |
| `--isaaclab` | Git ref for Isaac Lab, or `latest` / `no` | `latest` |
| `--isaaclab-arena` | Git ref for Isaac Lab Arena, or `latest` / `no` | `latest` |
| `--demos` | Out-of-the-box demo shortcuts (`quadruped-locomotion`, `humanoid-locomotion`, `franka-manipulation`) | `no` |
| `--flex-start` | *(GCP only)* Deploy using GCP Dynamic Workload Scheduler | `no-flex-start` |
| `--backup-bucket` | *(GCP only)* GCS bucket URI for automated preemption & 10m backups | `""` |
| `--auto-restore` | *(GCP only)* Restore workspace automatically from backup bucket on deployment | `no` |
| `--ingress-cidrs` | Allowed IP CIDR blocks (use `myip` for current IP) | `0.0.0.0/0` |
| `--existing` | Action if name exists: `ask`, `repair`, `modify`, `replace`, `run_ansible` | `ask` |

---

## Remote Desktop & Interactive 3D Streaming

Isaac Automator provides multi-provider remote desktop support. All options attach directly to the primary hardware-accelerated NVIDIA GPU display buffer (`DISPLAY=:0`), ensuring full compatibility with Omniverse Kit and Vulkan hardware rendering.

### Supported Providers

| Provider | Access Mode | Port(s) | Primary Use Case |
| :--- | :--- | :--- | :--- |
| **noVNC** | Browser (HTML5) | `6080` (TCP) | Default lightweight web desktop. |
| **KasmVNC** | Browser (WebRTC HTTPS) | `8444` (TCP) | Modern browser streaming with **native copy-paste (`Ctrl+V`)**. |
| **NoMachine** | Native Client | `4000` (TCP/UDP) | Default high-performance 3D viewport rendering over NX protocol. |
| **NICE DCV** | Browser & Client | `8443` (TCP/UDP) | Enterprise GPU streaming (100% free on AWS EC2 instances). |
| **xrdp** | Native Windows/Mac RDP | `3389` (TCP) | Zero-client-install Microsoft Remote Desktop console mirror. |
| **Sunshine** | Moonlight Client | `47984-48010`, `47990` | Sub-10ms, 60/120 FPS NVENC streaming for robotics teleoperation. |
| **Parsec** | Native Client | `8000-8040` (UDP) | Low-latency interactive cloud streaming daemon. |

---

### Credentials & Password Management

Isaac Automator configures two levels of access credentials:

* **VNC / WebRTC Password (`--vnc-password`)**: Used for **noVNC** (port 6080) and **KasmVNC** (port 8444).
* **System User Password (`--system-user-password`)**: Used for the `ubuntu` Linux account, **Microsoft Remote Desktop (xrdp)** (port 3389), and SSH sudo operations.

```sh
# Deploy with custom passwords
./deploy-gcp my-workstation \
  --vnc-password "MySecretVNC123" \
  --system-user-password "MySecretSys456" \
  --remote-desktop standard,kasmvnc,xrdp
```

> [!TIP]
> If you omit these flags, secure random 10-character passwords are automatically generated. You can view the active passwords for any deployment at any time in `state/<deployment-name>/info.txt` or `state/<deployment-name>/meta.json`.

---

### 1. noVNC (Standard HTML5 Web Desktop)

Zero client installation required. Opens directly in your browser:

* **One-Click Command:**
  ```sh
  ./novnc <deployment-name>
  ```
* **Direct URL:**
  ```text
  http://<instance-ip>:6080/vnc.html?host=<instance-ip>&port=6080&password=<vnc-password>&autoconnect=true&resize=scale
  ```
* **Best For:** Quick checks, starting scripts, or running when no client software can be installed.

---

### 2. KasmVNC (WebRTC Browser Desktop with Native Clipboard)

Modern WebRTC streaming in the browser with **full native clipboard support** (`Ctrl+C` and `Ctrl+V` work directly between host and cloud VM without sidebars):

* **Direct URL:**
  ```text
  https://<instance-ip>:8444/
  ```
* **Authentication:**
  * **Username:** `ubuntu`
  * **Password:** `<vnc-password>` (from `state/<deployment-name>/meta.json`)
* **Browser Certificate Notice:** Because KasmVNC uses TLS to enable the browser's `navigator.clipboard` API, modern browsers will display a standard self-signed certificate warning on first access. Click **Advanced $\to$ Proceed to `<instance-ip>` (unsafe)** to continue to the login prompt.

---

### 3. Microsoft Remote Desktop (xrdp)

Native OS remote desktop client integration on Windows, macOS, and Linux:

* **Client Software:**
  * **Windows:** Built-in **Remote Desktop Connection** (`mstsc.exe`).
  * **macOS / iOS:** [Microsoft Remote Desktop](https://apps.apple.com/us/app/microsoft-remote-desktop/id1295203466) (App Store).
  * **Linux:** `xfreerdp` or `Remmina`.
* **Host Address:** `<instance-ip>:3389`
* **Authentication:**
  * **Username:** `ubuntu`
  * **Password:** `<system-user-password>` (from `state/<deployment-name>/meta.json`)
* **Console Mirroring:** Automatically mirrors the primary GPU hardware console session (`DISPLAY=:0`), ensuring full NVIDIA Vulkan acceleration.

---

### 4. Sunshine + Moonlight (Ultra-Low Latency 60/120 FPS Streaming)

High-performance gaming-grade streaming powered by NVIDIA NVENC hardware video encoding. Ideal for live robotics teleoperation and interactive 3D camera navigation:

1. **Install Client:** Download and launch [Moonlight](https://moonlight-stream.org/) on your computer.
2. **Add Workstation Host:** Click **Add Host** in Moonlight and enter `<instance-ip>`. Moonlight will display a 4-digit pairing PIN on your screen.
3. **Pair Host:** Open `https://<instance-ip>:47990` in your web browser, click the **PIN** tab, and enter the 4-digit PIN.
4. **Launch Stream:** Moonlight will immediately show the Isaac Workstation desktop ready to launch at 60 or 120 FPS with sub-10ms latency.

---

### 5. NoMachine (Hardware-Accelerated 3D Viewport)

* **Client Software:** Download and install from [NoMachine](https://downloads.nomachine.com/).
* **Host Address:** `<instance-ip>:4000` (Protocol: `NX`)
* **Authentication:** In Connection Settings $\to$ Configuration $\to$ select *"Use key-based authentication with a key you provide"*, point to file `state/<deployment-name>/key.pem`, and enter username `ubuntu`.
* **Best For:** Direct Vulkan frame-buffer capture over high-latency WAN links.

---

### 6. NICE DCV (Enterprise GPU Streaming)

* **Browser Access:** `https://<instance-ip>:8443`
* **Native Client:** Connect to `<instance-ip>:8443` using the NICE DCV client.
* **Authentication:** Username `ubuntu`, password `<system-user-password>`.
* **Licensing:** 100% free when running on AWS EC2 instances.

---

### 7. Parsec (Interactive Streaming Daemon)

* Deploy with `--remote-desktop standard,parsec`.
* Open the Parsec app on your local machine and select your deployed cloud workstation from the list.

---

### 8. SSH Shell

Open an interactive shell into your workstation:

```sh
# Convenience wrapper
./ssh <deployment-name>

# Or direct standard OpenSSH command
ssh -i state/<deployment-name>/key.pem -o StrictHostKeyChecking=no ubuntu@<instance-ip>
```

---

## Reusing Existing Machines & In-Place Updates

You do **not** need to destroy or recreate your cloud workstations to enable new remote desktop options. Use `--existing modify`:

```sh
# Add KasmVNC to an existing GCP deployment
./deploy-gcp <deployment-name> --existing modify --remote-desktop standard,kasmvnc

# Add xrdp and Sunshine to an existing AWS deployment
./deploy-aws <deployment-name> --existing modify --remote-desktop standard,xrdp,sunshine
```

* **Terraform** updates cloud firewall rules in-place (~5 seconds, zero VM restart).
* **Ansible** detects that Isaac Sim, Isaac Lab, and NVIDIA drivers are already installed, skipping them completely and provisioning only the new remote desktop packages (~1 minute).
* All datasets, files in `~/workspace`, and training checkpoints are completely preserved.

---

## Spot Preemption Resilience & State Backups (GCP)

When running on GCP Spot or Flex-start instances, Isaac Automator provides an automated state resilience pipeline to prevent data loss.

```
┌────────────────────────────────────────────────────────────────────────────┐
│ GCP Workstation Instance                                                   │
│                                                                            │
│  [10-min Timer] ────> Trigger GCS Sync ─────────────────────┐              │
│                                                             │              │
│  [Metadata Watchdog] ──> Preemption Alert! (30s window)     │              │
│                               │                             │              │
│                               ├──> Send SIGINT to Isaac     │              │
│                               │    (Graceful Checkpoint)    ▼              │
│                               └──> Flush Workspace ───> [ GCS Bucket ]     │
└────────────────────────────────────────────────────────────────────────────┘
```

### 30-Second Preemption Watchdog
The `isaac-preempt-listener.service` daemon continuously polls the GCP instance metadata endpoint:
1. When Google signals preemption, the listener intercepts the notice with 30 seconds remaining.
2. It sends `SIGINT` to running Python / Isaac Sim processes so simulation training scripts save final model checkpoints.
3. It immediately syncs `/home/ubuntu/workspace` and experiment artifacts to your configured GCS bucket via `gcloud storage rsync`.

### 10-Minute Continuous Backup Timer
The `isaac-backup.timer` systemd unit performs periodic background synchronizations every 10 minutes to minimize recovery point objectives (RPO).

### Restoring State with `./restore-gcp`

If an instance is preempted or replaced, restore your workspace seamlessly using `./restore-gcp`:

```sh
# 1. Restore remote workstation workspace directly from the backup bucket
./restore-gcp <deployment-name>

# 2. Download the backup directly to your local workstation results directory
./restore-gcp <deployment-name> --to-local ./local-results/

# 3. Restore from a custom specific GCS snapshot URI
./restore-gcp <deployment-name> --source-bucket gs://my-archive-bucket/checkpoints/
```

---

## Pausing, Resuming & VM Cycling

### Stop and Start

Cloud instances can be stopped when idle to eliminate GPU compute billing while retaining disk state:

```sh
# Stop instance (preserves static IP and storage)
./stop <deployment-name>

# Start instance and re-verify drivers/services
./start <deployment-name>

# Fast start (skip Ansible verification, run autorun script only)
./start <deployment-name> --quick
```

### GCP Flex-start 7-Day VM Cycling (`./cycle-vm`)

GCP Flex-start instances have a hard 7-day maximum run duration limit. To prevent hard termination during long training runs, `./cycle-vm` monitors uptime and resets the 7-day window:

```sh
# Check current uptime and termination deadline without stopping
./cycle-vm <deployment-name> --check-only

# Automatically cycle VM if uptime >= 6.5 days (156 hours)
./cycle-vm <deployment-name>

# Force an immediate stop/start cycle with quick reboot
./cycle-vm <deployment-name> --force --quick
```

---

## Data Transfer & Standard Folders

| Local Folder | Remote Location | Purpose |
| :--- | :--- | :--- |
| `uploads/` | `/home/ubuntu/uploads` | Synchronize local datasets, models, or scripts to the cloud VM (`./upload <name>`). |
| `results/` | `/home/ubuntu/results` | Download training checkpoints, logs, and rendered outputs to local disk (`./download <name>`). |
| Workspace | `/home/ubuntu/workspace` | Primary development folder backed up automatically on Spot/GCS pipelines. |

---

## Maintenance, Repair & Teardown

### Repairing Deployments

If network security groups or software configurations drift, repair them without recreating infrastructure:

```sh
# Full repair (Terraform infrastructure + Ansible configuration)
./repair <deployment-name>

# Restrict ingress firewall rules to your current public IP
./repair <deployment-name> --ingress-cidrs myip
```

### Tearing Down Deployments

```sh
# Terminate VM and permanently delete cloud resources
./destroy <deployment-name> --yes
```

### Pre-Built Golden Images

To reduce provisioning time from ~15 minutes down to <2 minutes, bake a custom image containing NVIDIA drivers and pre-cached Isaac binaries:

```sh
./image-gcp --image-name isaac-workstation-base
./deploy-gcp my-workstation --from-image
```

---

## License

Copyright 2023-2026 NVIDIA Corporation. Licensed under the Apache License, Version 2.0.
