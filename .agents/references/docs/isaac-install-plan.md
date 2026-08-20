# Universal Isaac & Physical AI Installer Architecture Plan (`isaac-install-plan.md`)

> **Document Status**: Under Active Architectural Review  
> **Target Platform**: Bare-Metal Workstations & Heterogeneous Physical AI Nodes (Ubuntu 22.04 LTS)  
> **Compute Scope**: NVIDIA Blackwell (GB200 / RTX 5090 / RTX PRO 6000), Ada Lovelace (RTX 4090 / L40S / 6000 Ada), Ampere (RTX 3090 / A100)

---

## 1. Executive Summary & Vision

The **Universal Isaac Installer (`isaac-installer`)** is the zero-infrastructure, bare-metal provisioner for robotics, Physical AI, and simulation engineers. While `IsaacAutomator` handles public cloud instances (AWS, GCP, Azure, Alibaba), `isaac-installer` transforms a fresh or existing physical machine into a high-performance, open-ended robotics workstation.

### The Real-World Developer Reality:
In production robotics and Physical AI research, developers do **not** work in a static, monolithic sandbox. They:
1. Maintain active Git forks of core frameworks (`IsaacLab`, `IsaacLab-Arena`, `lerobot`) and switch branches rapidly.
2. Develop custom robot extensions, gym environments, and PhysX plugins across multiple distinct projects.
3. Manage different Python dependencies across tasks without corrupting Isaac Sim's underlying runtime.
4. Integrate real-time teleoperation hardware (ALOHA leader-follower arms, SpaceMouse, VR headsets, cameras) with sub-millisecond serial latency.
5. Ingest and train on 100s of gigabytes of camera and policy trajectories without thermal or storage I/O bottlenecks.

---

## 2. Realistic System-Space vs. User-Space Decoupled Architecture

A primary flaw of naive installer scripts is executing everything under `sudo`, polluting user directories, creating `root:root` permission locks in `~/.cache` and Python runtimes, and hardcoding global shell variables that break non-simulation workloads.

`isaac-installer` enforces a strict **Two-Phase Privilege Boundary**:

```mermaid
flowchart TD
    subgraph PHASE1 ["Phase 1: System Infrastructure (Privileged - Sudo Once)"]
        D1["NVIDIA Driver (Blackwell 570+ / Ada 535+) & DKMS"]
        D2["Vulkan ICD Runtime & X11 Display Server Configuration"]
        D3["Hardware Udev Rules (1ms FTDI, RealSense, SpaceMouse, Manus)"]
        D4["System Build Stack (GCC 11, CMake, Ninja, Git LFS, Vulkan Dev)"]
        D5["Storage Provisioning (NVMe-CLI, LVM2 Volume Mounting on /data)"]
        D6["User Group Membership (docker, dialout, plugdev, input, video, uinput)"]
    end

    subgraph PHASE2 ["Phase 2: Developer Workspace (Unprivileged - Target User)"]
        U1["Toolchain Provisioning (UV, Miniforge/Micromamba, GitHub CLI)"]
        U2["Smart Git Workspace (~/Documents/GitHub/<Org>/<Repo>) & Fork Remotes"]
        U3["Dynamic Python Isolation & Environment Shims (isaaclab-env)"]
        U4["Topological Extension Installation (omni.isaac.lab -> tasks -> rl)"]
        U5["Downstream Package Linkage (IsaacLab-Arena, LeRobot, Rerun)"]
        U6["IDE & Desktop Integration (VS Code Discovery, GitHub Desktop UI)"]
    end

    PHASE1 -- "System Ready (No Root Required Afterwards)" --> PHASE2
```

---

## 3. Python Environment Architecture: The Environment Shim Pattern

### The Problem with Global `setup_conda_env.sh`
Sourcing Isaac Sim's `setup_conda_env.sh` globally in `~/.bashrc` mutates `PYTHONPATH` and `LD_LIBRARY_PATH` with Omniverse kit libraries. This causes **binary ABI crashes** when running standard Python tools, PyTorch models, or CLI utilities outside of Isaac Sim.

### The Solution: Dynamic Environment Shimming (`isaaclab-env` & Virtualenv Hooks)

Instead of contaminating the host shell, `isaac-installer` configures a **Scoped Environment Shim**:

```mermaid
flowchart LR
    DEV["Developer / VS Code"] --> SHIM["isaaclab-env [command]"]
    SHIM --> RUN["Subshell with Exported Omniverse Paths\n(EXP_PATH, RESOURCE_NAME, Vulkan ICD)"]
    RUN --> EXEC["Executes Script / PyTorch / Gym Task"]
    EXEC --> EXIT["Exits: Host Shell Remains 100% Clean"]
```

```text
Host Shell (.bashrc)
└── Clean Python / Conda / UV Environment (No Global Isaac Sim PYTHONPATH)
    ├── Standard Python Projects (run independently without library collisions)
    └── Scoped Invocation:
        ├── Direct CLI:       isaaclab-env python train.py --task Isaac-Cartpole-v0
        ├── Conda Activate:   conda activate isaaclab (sources env-vars on activation only)
        └── Project Virtual:  source ~/workspaces/robot_project/.venv/bin/activate_isaac
```

### Topological Extension Installation Order

To guarantee stability, extensions and downstream packages must be compiled and linked in strict topological dependency order:

```mermaid
flowchart TD
    T0["0. Base Python 3.10 Runtime (UV / Conda) + Pip / Wheel"]
    T1["1. Pinned PyTorch CUDA (torch==2.5.1+cu124 matching GPU Arch)"]
    T2["2. Core Extension: source/extensions/omni.isaac.lab"]
    T3["3. Asset Extension: source/extensions/omni.isaac.lab_assets"]
    T4["4. Tasks Extension: source/extensions/omni.isaac.lab_tasks"]
    T5["5. RL Extension: source/extensions/omni.isaac.lab_rl"]
    T6["6. RL Frameworks (rsl_rl, skrl, rl_games, stable-baselines3)"]
    T7["7. Benchmark Suite (IsaacLab-Arena via editable pip -e .)"]
    T8["8. Physical AI / Imitation Learning (LeRobot [all,dataset_viz])"]

    T0 --> T1 --> T2 --> T3 --> T4 --> T5 --> T6 --> T7 --> T8
```

---

## 4. Open-Ended Developer Fork & Multi-Repo Workflows

In active robotics development, researchers frequently work across custom branches and organizational forks.

### Dual-Remote Git Topology
For every cloned repository (`IsaacLab`, `IsaacLab-Arena`, `lerobot`, `rsl_rl`):
- `origin`: Developer's personal or lab fork (Read/Write for branches, commits, PRs).
- `upstream`: Official NVIDIA or Hugging Face repository (Read-only for tracking and syncing).

```text
~/Documents/GitHub/
├── BoredEngineer/
│   ├── IsaacLab/               [origin: BoredEngineer/IsaacLab | upstream: isaac-sim/IsaacLab]
│   ├── IsaacLab-Arena/         [origin: BoredEngineer/IsaacLab-Arena | upstream: isaac-sim/IsaacLab-Arena]
│   └── lerobot/                [origin: BoredEngineer/lerobot | upstream: huggingface/lerobot]
└── custom_extensions/
    └── omni.isaac.custom_task/ [User's proprietary robot manipulation tasks]
```

### Submodule Optimization:
- Large upstream submodules (`rsl_rl`, `Arena-Assets`) are initialized with `--depth 1 --recurse-submodules --shallow-submodules` to avoid pulling gigabytes of unused commit history while preserving branch switching capabilities.
- Automated URL rewrites ensure SSH authentication gracefully falls back to HTTPS for automated/CI runs.

---

## 5. Teleoperation, Real-Time Serial & Peripherals Subsystem

Robotics teleoperation requires deterministic, low-latency communication with physical actuators, microcontrollers, and sensory devices.

```mermaid
flowchart TD
    subgraph TELEOP_DEVICES ["Physical Devices & Interfaces"]
        ARM["ALOHA / SO-100 Robot Arms (FTDI Serial)"]
        SPACEMOUSE["3Dconnexion SpaceMouse (USB HID)"]
        CAMERA["Intel RealSense / OAK-D Depth Cameras"]
        VR["Apple Vision Pro / Meta Quest 3 / Manus Gloves"]
    end

    subgraph UDEV_RULES ["System Udev Rules (/etc/udev/rules.d/)"]
        R1["99-ftdi-latency.rules: latency_timer = 1ms (reduces 16ms jitter)"]
        R2["99-spacenav.rules: User group permissions for spacenavd"]
        R3["99-realsense.rules: Hardware video stream decoders"]
        R4["99-manus-gloves.rules: OpenXR / Bluetooth HID permissions"]
    end

    subgraph PERMISSIONS ["User Permissions"]
        G["Groups: dialout, plugdev, input, video, uinput"]
    end

    TELEOP_DEVICES --> UDEV_RULES --> PERMISSIONS
```

### 1ms FTDI Serial Latency Rule:
Standard Linux kernel drivers default USB-to-serial devices (`/dev/ttyUSB*`) to a **16ms buffer latency timer**. In closed-loop robot control, this causes severe latency and packet drops. The installer enforces:
```udev
ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"
```

---

## 6. High-Throughput NVMe Storage, Datasets & USD Asset Cache

Physical AI training and multi-camera simulation create massive I/O traffic.

```text
/data (Mounted on High-Speed PCIe Gen4/Gen5 NVMe SSD)
├── isaac_cache/
│   ├── ov_data/           # Cached Omniverse USD assets (G1, Go2, Franka, Warehouses)
│   └── shader_cache/      # Pre-compiled Vulkan / RTX shader cache (sub-2s startup)
├── datasets/
│   ├── lerobot/           # Multi-camera HDF5/Zarr teleoperation trajectories
│   └── rsl_rl_logs/       # Reinforcement learning checkpoints and tensorboard runs
└── models/
    └── pretrained_checkpoints/ # Hugging Face LeRobot & Foundation policy weights
```

---

## 7. Concrete Project Structure

```text
isaac-installer/
├── bin/
│   ├── isaac-installer            # CLI dispatcher (doctor, plan, install, sim, auth, test)
│   └── isaaclab-env               # Dynamic runtime environment shim
├── config/
│   ├── default-profile.yaml       # Standard interactive robotics workstation preset
│   ├── minimal-headless.yaml      # Headless RL training / CI cluster node preset
│   └── full-ecosystem.yaml        # Full stack (+ LeRobot, Arena, SpaceMouse, Manus VR)
├── lib/
│   ├── core/
│   │   ├── logging.sh             # Unicode UI cards, color palette, failure log tailing
│   │   ├── detect.sh              # Blackwell/Ada GPU, NVMe SSDs, LVM, Wayland/X11
│   │   ├── audit.sh               # 20-component pre-flight audit diff matrix
│   │   ├── state.sh               # JSON state machine & reboot resumption
│   │   ├── network.sh             # CDN latency pre-flight benchmark
│   │   ├── backup.sh              # Safety configuration snapshots & rollback
│   │   ├── git_workspace.sh       # Dual-remote fork topology & GitHub Desktop integration
│   │   └── package_manager.sh     # Abstract package manager wrapper
│   ├── modules/
│   │   ├── driver.sh              # NVIDIA drivers (570+ / 535+), DKMS, nouveau blacklist
│   │   ├── display.sh             # X11 enforcement, virtual EDID (headless display)
│   │   ├── system_prereqs.sh      # Vulkan runtime, GCC 11, CMake, Ninja, Git LFS
│   │   ├── conda.sh               # UV toolchain & Miniforge/Micromamba isolation
│   │   ├── dev_tools.sh           # Docker CE, nvidia-ctk, nvme-cli, lvm2, VS Code, Chrome
│   │   ├── physical_ai.sh         # Hugging Face CLI, LeRobot, Rerun.io dataset viz
│   │   ├── hardware_teleop.sh     # 1ms FTDI rules, SpaceMouse, RealSense, Manus VR
│   │   ├── isaacsim.sh            # Standalone ZIP engine extraction, multi-version registry
│   │   ├── isaaclab.sh            # Topological extension installer & PyTorch verification
│   │   ├── isaaclab_arena.sh      # Arena multi-agent benchmark suite with depth-1 submodules
│   │   ├── auth.sh                # Unified OAuth, Cloud Hubs (GH, HF, NGC, WandB)
│   │   ├── streaming.sh           # Hardware streaming (NoMachine, Sunshine NVENC)
│   │   ├── demos.sh               # Desktop shortcuts (.desktop) and RL launchers
│   │   └── ecosystem.sh           # Isaac-GR00T, ROS 2 Humble/Jazzy bridge
│   └── templates/
│       ├── xorg.conf.template     # Dummy display template for headless servers
│       ├── vdisplay.edid          # 1080p60 EDID binary for headless GPU rendering
│       ├── udev-rules/            # Hardware device udev rules (FTDI, SpaceMouse, RealSense)
│       └── desktop-shortcuts/     # Desktop launcher templates (.desktop.template)
└── README.md                      # Operator manual and quickstart
```

---

## 8. Authentication & Permissions Matrix

| Category | Component / Service | Required Credentials | Interactive Flow | Automated / Headless Flow |
| :--- | :--- | :--- | :--- | :--- |
| **Code & Repos** | **GitHub** | OAuth Token / PAT / SSH Key | `gh auth login -w` | `$GITHUB_TOKEN` / `$GH_TOKEN` + `gh auth setup-git` |
| **Foundation Hub** | **Hugging Face Hub** | User Access Token (Read/Write) | `huggingface-cli login` | `$HF_TOKEN` -> `~/.cache/huggingface/token` |
| **Container Cloud**| **NVIDIA NGC (`nvcr.io`)** | NGC API Key (`$oauthtoken`) | `ngc config set` | `echo "$NGC_API_KEY" \| docker login nvcr.io -u '$oauthtoken' --password-stdin` |
| **RL Tracking** | **Weights & Biases** | WandB API Key | `wandb login` | Reads `$WANDB_API_KEY` -> `~/.netrc` |
| **Host Security** | **Docker Group** | User group membership | Automatic | `usermod -aG docker $TARGET_USER` |
| **Host Security** | **Robotics Serial (USB)**| Group `dialout`, `tty` | Automatic | Grants access to Dynamixel, ALOHA, SO-100 arms |
| **Host Security** | **Peripherals (`plugdev`)**| Group `plugdev`, `input`, `video`, `uinput` | Automatic | Grants access to SpaceMouse, RealSense, Manus VR |
| **Licensing** | **Omniverse EULA** | EULA Acceptance | Automatic | Touches `${ISAACSIM_DIR}/.eula_accepted` |

---

## 9. 13-Subsystem End-to-End Verification Suite (`test`)

The verification suite runs granular, non-destructive health checks across 13 core subsystems:

1. **NVIDIA Driver & GPU Topology**: Driver version ($\ge 535$ or $\ge 570$), PCIe Link speed (Gen4/Gen5 x16), persistence mode.
2. **Display Server**: X11 server active or virtual EDID configured (`DISPLAY=:0`), Wayland disabled for Omniverse compatibility.
3. **Build Prerequisites**: GCC 11, G++ 11, CMake $\ge 3.22$, Ninja, Git LFS.
4. **Vulkan Runtime**: `vulkaninfo` device enumeration, ICD configuration (`/etc/vulkan/icd.d/nvidia_icd.json`).
5. **Docker & GPU Passthrough**: Docker daemon status, `nvidia-ctk` runtime test (`nvidia-smi` inside container).
6. **Developer Tools**: VS Code, GitHub Desktop, Google Chrome / Chromium, `gh`, `aws`, `gcloud`, `hf`.
7. **Storage & I/O Stack**: NVMe SMART health telemetry, LVM2 volume groups, mount permissions on `/data`.
8. **Python Runtime & UV**: Python 3.10 runtime, `uv` package manager binary and cache health.
9. **Physical AI & LeRobot**: Hugging Face token validity, `lerobot` import, Rerun.io visualizer binary.
10. **Hardware Teleop**: 1ms FTDI latency timer verification, user membership in `dialout`, `plugdev`, `input`.
11. **Isaac Sim Standalone Engine**: Executable verification, `.eula_accepted` presence, Kit Carbonite core load.
12. **Isaac Lab PyTorch CUDA Linkage**: GPU tensor allocation, CUDA device name match, extension import sanity.
13. **IsaacLab-Arena & Demos**: Gymnasium multi-agent environment registration, 50-step headless PhysX tensor rollout.

---

## 10. Critical Architectural Review & Open Questions

The following architectural points require specific team and stakeholder review during the next development iterations:

### Review Point 1: Two-Phase CLI Separation (`sys-provision` vs `dev-setup`)
- **Question**: Should the installer CLI be explicitly split into two top-level subcommands:
  - `sudo isaac-installer sys-provision` (runs strictly as root: drivers, udev, packages, storage).
  - `isaac-installer dev-setup` (runs strictly as target user: git clones, uv envs, extensions, shortcuts)?
- **Tradeoff**: Clean privilege boundary and 0% risk of root cache pollution vs. single-command convenience.

### Review Point 2: Python Environment Isolation Strategy
- **Question**: Should `isaac-installer` default to:
  - **Strategy A**: Isolated Conda environment (`conda create -n isaaclab python=3.10`) with `uv pip` acceleration inside.
  - **Strategy B**: Pure `uv venv` virtualenv (`~/.venvs/isaaclab`) with lightweight shell shims.
  - **Strategy C**: DevContainer / OCI container on bare-metal with bind-mounted GPU and X11 sockets.
- **Tradeoff**: Conda provides system-level CUDA/C++ dependency isolation; UV provides 10x faster package resolution; DevContainers provide 100% reproducibility across machines.

### Review Point 3: Sourced Environment Shims vs Monolithic Shell Pollution
- **Question**: How should Omniverse runtime paths be exposed to IDEs (VS Code / Cursor / PyCharm)?
  - Via a `.env` file in the workspace root.
  - Via dynamic wrapper script (`bin/isaaclab-env`).
  - Via Conda `etc/conda/activate.d/isaac_sim.sh` hooks that activate only when entering the conda environment.

### Review Point 4: Downstream Dependency Management (Submodules vs Wheels)
- **Question**: Should downstream RL dependencies (like `rsl_rl`, `skrl`, `rl_games`) be managed as editable git submodules or pinned PyPI wheels?
  - Submodules allow modifying the RL algorithm source code directly during research.
  - Wheels provide faster and more predictable installs.

---

## 11. Implementation Roadmap

- [x] **Core CLI & Unicode UI Engine** (`bin/isaac-installer`, `lib/core/logging.sh`)
- [x] **Deep Hardware, NVMe & Multi-GPU Discovery** (`lib/core/detect.sh`)
- [x] **20-Component Pre-Flight Audit Matrix** (`lib/core/audit.sh`)
- [x] **Network CDN Latency Pre-Flight Benchmarking** (`lib/core/network.sh`)
- [x] **Configuration Safety Snapshots & Rollback** (`lib/core/backup.sh`)
- [x] **Unified Authentication & Cloud Hub Manager** (`lib/modules/auth.sh`)
- [x] **High-Speed Storage Stack (`nvme-cli`, `lvm2`, `fio`)** (`lib/modules/dev_tools.sh`)
- [x] **Smart Repo Discovery, Fork Wiring & GitHub Desktop** (`lib/core/git_workspace.sh`)
- [x] **Hugging Face LeRobot & `lerobot-dataset-viz`** (`lib/modules/physical_ai.sh`)
- [x] **Hardware Teleop Peripherals & 1ms Low-Latency Serial** (`lib/modules/hardware_teleop.sh`)
- [x] **Multi-Version Isaac Sim Detection & Atomic Symlink Switcher** (`lib/modules/isaacsim.sh`)
- [x] **Topological Isaac Lab & Arena Linking** (`lib/modules/isaaclab.sh`, `lib/modules/isaaclab_arena.sh`)
- [x] **13-Subsystem End-to-End Verification Suite** (`cmd_test`)
- [ ] **Two-Phase Privilege Boundary Refactor (`sys-provision` vs `dev-setup`)**
- [ ] **Dynamic Environment Shim Implementation (`isaaclab-env` & activation hooks)**
- [ ] **Multi-Agent Skills Registration** (`.agents/skills/isaac-baremetal-installer/SKILL.md`)
