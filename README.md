![Isaac Automator](src/banner.png)

# Isaac Automator (v4.2)

Isaac Automator deploys **NVIDIA Isaac Sim**, **Isaac Lab**, and **Isaac Lab Arena** to public clouds (AWS, GCP, Azure, and Alibaba Cloud) as ready-to-use GPU **Isaac Workstations** in minutes.

The result is a fully configured remote desktop cloud VM with NVIDIA drivers, Isaac software, GUI streaming (noVNC browser & NoMachine 3D), automated lifecycle management (start/stop/destroy/cycle), and automated state resilience for Spot and Flex-start cost savings.

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
  - [Complete Options Reference](#complete-options-reference)
- [Spot Preemption Resilience & State Backups (GCP)](#spot-preemption-resilience--state-backups-gcp)
  - [30-Second Preemption Watchdog](#30-second-preemption-watchdog)
  - [10-Minute Continuous Backup Timer](#10-minute-continuous-backup-timer)
  - [Restoring State with `./restore-gcp`](#restoring-state-with-restore-gcp)
- [Pausing, Resuming & VM Cycling](#pausing-resuming--vm-cycling)
  - [Stop and Start](#stop-and-start)
  - [GCP Flex-start 7-Day VM Cycling (`./cycle-vm`)](#gcp-flex-start-7-day-vm-cycling-cycle-vm)
- [Connecting to Your Workstation](#connecting-to-your-workstation)
  - [Browser Remote Desktop (noVNC)](#browser-remote-desktop-novnc)
  - [Live 3D Viewport (NoMachine)](#live-3d-viewport-nomachine)
  - [SSH Shell](#ssh-shell)
- [Running Applications & Demos](#running-applications--demos)
  - [Isaac Sim](#isaac-sim)
  - [Isaac Lab](#isaac-lab)
  - [Isaac Lab Arena](#isaac-lab-arena)
  - [Built-In Robotics Demos](#built-in-robotics-demos)
- [Autorun Script](#autorun-script)
- [Data Transfer & Standard Folders](#data-transfer--standard-folders)
- [Maintenance, Repair & Teardown](#maintenance-repair--teardown)
  - [Repairing Deployments](#repairing-deployments)
  - [Tearing Down Deployments](#tearing-down-deployments)
  - [Importing Existing Deployments](#importing-existing-deployments)
  - [Pre-Built Golden Images](#pre-built-golden-images)
- [Tips](#tips)

---

## TLDR ;)

```sh
# Option 1: Using VS Code DevContainer
# Simply open the repo in VS Code -> "Reopen in Container" -> Run commands directly:
./deploy-gcp my-workstation --flex-start --backup-bucket gs://my-isaac-backups/
./novnc my-workstation        # stream desktop in browser
./destroy my-workstation --yes # clean up when done

# Option 2: Using Local Docker CLI
./build                       # build Isaac Automator tool container (one-time)
./run                         # enter container environment
./deploy-aws my-workstation   # follow prompts to deploy
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

<details>
  <summary>Enabling Access Permissions & Credentials</summary>

  You need *AmazonEC2FullAccess* permissions for your AWS user.
  On first run, you will be prompted to sign in with AWS IAM Identity Center (`aws configure sso` / `aws sso login`). Credentials are stored in `state/.aws/` and persist across restarts.
</details>

```sh
./deploy-aws <deployment-name> \
  --instance-type g6e.2xlarge \
  --isaacsim latest \
  --isaaclab latest \
  --demos quadruped-locomotion
```

* Supported instance families: `g4dn.*` (NVIDIA T4), `g5.*` (NVIDIA A10G), `g6.*` (NVIDIA L4), `g6e.*` (NVIDIA L40S).

### GCP (Google Cloud Platform)

<details>
  <summary>Setting Up GCP Access</summary>

  You will be prompted to log in with your Google account (`gcloud auth login`) during the first deployment. Credentials are stored in `state/.gcp/` and persist across container restarts. Ensure the Compute Engine API is enabled in your target project.
</details>

```sh
./deploy-gcp <deployment-name> \
  --project my-gcp-project \
  --zone us-central1-a \
  --instance-type g2-standard-8 \
  --isaac-workstation-gpu-count 1 \
  --flex-start \
  --backup-bucket gs://my-bucket/backups \
  --auto-restore
```

* Supported GPUs: NVIDIA L4 (`g2-*`), NVIDIA T4 (`n1-*`), NVIDIA RTX PRO 6000 (`g4-*`).
* **Flex-start:** Enable Dynamic Workload Scheduling with `--flex-start` for substantial cloud cost savings.
* **State Backups:** Pass `--backup-bucket <gcs-uri>` to enable automated state persistence and preemption protection.

### Azure

<details>
  <summary>Setting Up Azure Access</summary>

  You will be prompted to log in with your Azure account (`az login`). Credentials persist in `state/.azure/`.
</details>

```sh
./deploy-azure <deployment-name> \
  --region westus3 \
  --instance-type Standard_NV36ads_A10_v5
```

### Alibaba Cloud

<details>
  <summary>Getting Access Credentials</summary>

  Provide an Access Key and Secret Key from the Alibaba Cloud console.
</details>

```sh
./deploy-alicloud <deployment-name> \
  --region us-east-1 \
  --instance-type ecs.gn7i-c16g1.4xlarge
```

---

### Common Deploy Options

| Option | Description | Default |
| :--- | :--- | :--- |
| `--isaacsim` | Git ref for Isaac Sim, or `latest` / `no` | `latest` |
| `--isaaclab` | Git ref for Isaac Lab, or `latest` / `no` | `latest` |
| `--isaaclab-arena` | Git ref for Isaac Lab Arena, or `latest` / `no` | `latest` |
| `--demos` | Out-of-the-box demo shortcuts (`quadruped-locomotion`, `humanoid-locomotion`, `franka-manipulation`) | `no` |
| `--flex-start` | *(GCP only)* Deploy using GCP Dynamic Workload Scheduler | `no-flex-start` |
| `--backup-bucket` | *(GCP only)* GCS bucket URI for automated preemption & 10m backups | `""` |
| `--auto-restore` | *(GCP only)* Restore workspace automatically from backup bucket on deployment | `no` |
| `--ingress-cidrs` | Allowed IP CIDR blocks (use `myip` for current IP, or `myip/16`, `myip/24`) | `0.0.0.0/0` |
| `--existing` | Action if name exists: `ask`, `repair`, `modify`, `replace`, `run_ansible` | `ask` |
| `--from-image` | Deploy from a pre-built golden VM image to accelerate provisioning | `not-from-image` |

---

### Complete Options Reference

<details>
<summary><code>deploy-aws</code> options</summary>

```
Options:
  --debug / --no-debug          Enable debug output.  [default: no-debug]
  --prefix TEXT                 Prefix for all cloud resources.  [default: isaacautomator]
  --from-image / --not-from-image
                                Deploy from pre-built image, from bare OS
                                otherwise.  [default: not-from-image]
  --in-china [auto|yes|no]      Is deployment in China? (Local mirrors will be
                                used.)  [default: auto]
  --deployment-name TEXT        Name of the deployment.  [default: <random>]
  --ingress-cidrs TEXT          CIDR blocks for ingress traffic, comma
                                separated. "myip" for your public IP.
                                [default: 0.0.0.0/0]
  --existing [ask|repair|modify|replace|run_ansible]
                                What to do if deployment already exists.
                                [default: ask]
  --isaacsim TEXT               Git ref at github.com/isaac-sim/IsaacSim, or
                                "no".  [default: latest]
  --isaaclab TEXT               Git ref at github.com/isaac-sim/IsaacLab, or
                                "no".  [default: latest]
  --isaaclab-arena TEXT         Git ref at
                                github.com/isaac-sim/IsaacLab-Arena, or
                                "no".  [default: latest]
  --vnc-password TEXT           Password for VNC access.  [default: <random>]
  --system-user-password TEXT   System user password.  [default: <random>]
  --ssh-port TEXT               SSH port.  [default: 22]
  --ssh-user TEXT               OS username on the deployed instances.
                                [default: ubuntu]
  --upload / --no-upload        Upload user data from "uploads/" to cloud
                                instances.  [default: upload]
  --instance-type TEXT          Instance type (G4dn, G5, G6, G6e supported).
                                [default: g6e.2xlarge]
  --region TEXT                 AWS Region.  [default: us-east-1]
```

</details>

<details>
<summary><code>deploy-gcp</code> options</summary>

```
Options:
  --debug / --no-debug          Enable debug output.  [default: no-debug]
  --prefix TEXT                 Prefix for all cloud resources.  [default: isaacautomator]
  --in-china [auto|yes|no]      Is deployment in China? (Local mirrors will be
                                used.)  [default: auto]
  --deployment-name TEXT        Name of the deployment.  [default: <random>]
  --zone TEXT                   GCP zone.  [default: us-central1-a]
  --project TEXT                GCP Project ID.  [default: from gcloud config]
  --ingress-cidrs TEXT          CIDR blocks for ingress traffic, comma
                                separated. "myip" for your public IP.
                                [default: 0.0.0.0/0]
  --existing [ask|repair|modify|replace|run_ansible]
                                What to do if deployment already exists.
                                [default: ask]
  --isaacsim TEXT               Git ref at github.com/isaac-sim/IsaacSim, or
                                "no".  [default: latest]
  --isaaclab TEXT               Git ref at github.com/isaac-sim/IsaacLab, or
                                "no".  [default: latest]
  --isaaclab-arena TEXT         Git ref at
                                github.com/isaac-sim/IsaacLab-Arena, or
                                "no".  [default: latest]
  --vnc-password TEXT           Password for VNC access.  [default: <random>]
  --system-user-password TEXT   System user password.  [default: <random>]
  --ssh-port TEXT               SSH port.  [default: 22]
  --ssh-user TEXT               OS username on the deployed instances.
                                [default: ubuntu]
  --upload / --no-upload        Upload user data from "uploads/" to cloud
                                instances.  [default: upload]
  --instance-type [g2-standard-4|g2-standard-8|...|n1-standard-4|...|g4-standard-48|...]
                                Instance type.  [default: g2-standard-8]
  --isaac-workstation-gpu-count [1|2|4|8]
                                Number of GPUs.  [default: 1]
  --flex-start / --no-flex-start
                                Deploy using GCP Flex-start (Dynamic Workload
                                Scheduler) for improved capacity availability.
                                [default: no-flex-start]
  --backup-bucket TEXT          GCS bucket URI for automated preemption and periodic backups.
  --auto-restore / --no-auto-restore
                                Restore workspace from backup bucket on deployment. [default: no]
```

</details>

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

The public IP address is preserved across stop/start cycles on all supported clouds (AWS uses an Elastic IP, GCP reserves a static external address, and Azure retains the public IP).

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

## Connecting to Your Workstation

### Browser Remote Desktop (noVNC)

Connect to the workstation's XFCE desktop directly in any web browser without local client software:

```sh
./novnc <deployment-name>
```

### Live 3D Viewport (NoMachine)

Isaac Sim and Omniverse Kit render via hardware-accelerated Vulkan surfaces. For real-time 3D viewport interaction:
1. Install [NoMachine client](https://www.nomachine.com/) on your host machine.
2. Connect to `<instance-ip>:4000` using the username `ubuntu` and the system password displayed during deployment (or stored in `state/<deployment-name>/info.txt`).

### SSH Shell

```sh
./ssh <deployment-name>
```

---

## Running Applications & Demos

### Isaac Sim

```sh
# Run Isaac Sim with GUI:
isaac-sim

# Run Isaac Sim headlessly:
isaac-sim.headless
```

### Isaac Lab

```sh
cd ~/workspace/IsaacLab
./isaaclab.sh -p source/standalone/tutorials/00_sim/create_empty.py
```

### Isaac Lab Arena

```sh
cd ~/workspace/IsaacLab-Arena
./isaaclab.sh -p source/extensions/omni.isaac.lab_arena/...
```

### Built-In Robotics Demos

When selected during deploy (`--demos <name>`), out-of-the-box reinforcement learning demos appear as double-clickable desktop shortcuts:

| Demo Name | Description | Required Apps |
| :--- | :--- | :--- |
| `quadruped-locomotion` | Train an ANYmal-D quadruped to walk using RSL-RL in Isaac Lab | Isaac Sim, Isaac Lab |
| `humanoid-locomotion` | Train a Unitree G1 humanoid to walk using RSL-RL in Isaac Lab | Isaac Sim, Isaac Lab |
| `franka-manipulation` | Train a Franka arm to reach targets using RSL-RL in Isaac Lab | Isaac Sim, Isaac Lab |

---

## Autorun Script

For scripts that need to execute automatically on initial deploy and after every `./start`, edit [`uploads/autorun.sh`](uploads/autorun.sh):

```sh
#!/bin/sh
# Executed on initial deploy and after every start
cd /home/ubuntu/workspace/IsaacLab
# Example: launch unattended background training job
python3 train.py &
```

---

## Data Transfer & Standard Folders

| Local Folder | Remote Location | Purpose |
| :--- | :--- | :--- |
| `uploads/` | `/home/ubuntu/uploads` | Synchronize local datasets, models, or scripts to the cloud VM (`./upload <name>`). |
| `results/` | `/home/ubuntu/results` | Download training checkpoints, logs, and rendered outputs to local disk (`./download <name>`). |
| Workspace | `/home/ubuntu/workspace` | Primary development folder backed up automatically on Spot/GCS pipelines. |

```sh
# Upload local data:
./upload <deployment-name>

# Download remote results:
./download <deployment-name>
```

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

### Importing Existing Deployments

If you lose the local `state/` directory but still have cloud resources running, import them back:

```sh
./import --cloud gcp --project my-project --prefix isaacautomator --zone us-central1-a
```

### Pre-Built Golden Images

To reduce provisioning time from ~15 minutes down to <2 minutes, bake a custom image containing NVIDIA drivers and pre-cached Isaac binaries:

```sh
./image-gcp --image-name isaac-workstation-base
./deploy-gcp my-workstation --from-image
```

---

## Tips

### Persisting Custom Configurations
To persist customizations (custom conda environments, dependencies, system tweaks) across stop/start cycles:
1. Store files in `/home/ubuntu/workspace/` (retained across stops and backed up to GCS).
2. Add automated re-initialization commands to [`uploads/autorun.sh`](uploads/autorun.sh).

---

## License

Copyright 2023-2026 NVIDIA Corporation. Licensed under the Apache License, Version 2.0.
