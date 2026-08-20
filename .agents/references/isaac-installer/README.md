# Isaac Installer (`isaac-installer`)

A modular, zero-infrastructure, bare-metal robotics and Physical AI workstation provisioner for **Ubuntu 22.04 LTS**.

`isaac-installer` transforms a freshly booted or pre-existing physical desktop or server into a complete robotics development, teleoperation, and simulation workstation using **declarative YAML profiles**.

---

## Key Features

- **Declarative YAML Configuration Profiles (`config/*.yaml`)**:
  - `default-profile.yaml`: Clean, standard interactive robotics workstation (Sim + Lab + VS Code + GitHub Desktop + Chromium + NVMe tools + 1ms FTDI serial rule). Bloat-free: VR gloves, SpaceMouse daemons, LeRobot, and Discord are disabled by default.
  - `minimal-headless.yaml`: Headless RL training or CI/CD server (Driver + Docker + Vulkan + Isaac Sim + Isaac Lab only).
  - `full-ecosystem.yaml`: Full Physical AI ecosystem (+ LeRobot, Arena, SpaceMouse, Manus VR, RealSense, Cloud CLIs).
- **Smart Repository Discovery & Fork Workflows**:
  - Automatically searches for existing project clones in `~/Documents/GitHub/`, `~/workspace/`, `~`.
  - Supports personal fork repositories (`--isaaclab-repo <slug>`, `--arena-repo <slug>`, `--lerobot-repo <slug>`).
  - Automatically wires **Dual-Remote Git Topology** (`origin` = your fork for pushing, `upstream` = official NVIDIA/HF for syncing).
  - **GitHub Desktop Integration**: Automatically registers all cloned repositories directly into GitHub Desktop's UI sidebar (`github-desktop --add`).
- **High-Speed Multi-NVMe Storage & LVM2 Subsystem**:
  - Probes all PCIe Gen4/Gen5 NVMe SSDs (Model, Capacity, SMART health, S.M.A.R.T. thermal logs) and LVM volume groups across `doctor`, `plan`, and `test`.
- **POSIX Atomic Multi-Version & Custom Source Engine Switcher (`sim`)**:
  - Seamlessly switch between Isaac Sim versions (4.2.0, 4.5.0, 5.1.0) and custom source builds with 0.1s atomic symlink swapping and automated rollback.
- **Unified OAuth & Cloud Hub Manager (`auth`)**:
  - Single pane of glass to audit, login, and configure GitHub, Hugging Face Hub, NVIDIA NGC (`nvcr.io`), Weights & Biases, GCP ADC, AWS, and local hardware groups (`docker`, `dialout`, `plugdev`, `input`, `video`).
  - Git Author Identity (`user.name` / `user.email`) & SSH public key generator (`auth gen-ssh`).
- **Deep Pre-Flight Audit (`plan` / `check`)**:
  - 20-component diff matrix comparing host versions vs target versions with APT lock holder detection and conflict warnings.
- **13-Subsystem Verification Suite (`test`)**:
  - Tests Driver, Display, Vulkan, Git LFS, Docker GPU passthrough, VS Code/Apps, Cloud CLIs, NVMe/LVM, Hugging Face CLI, LeRobot Viz, 1ms FTDI rule, Isaac Sim, and Isaac Lab with overall Health Scorecard.

---

## Usage & Profiles

### 1. Inspect Active YAML Configuration
```bash
./bin/isaac-installer config
```

### 2. Run with a Preset YAML Profile
```bash
# Standard clean workstation (default):
sudo ./bin/isaac-installer install

# Minimal headless server (no GUI apps, no teleop daemons):
sudo ./bin/isaac-installer install --profile minimal

# Full ecosystem (LeRobot, Arena benchmarks, all hardware teleop):
sudo ./bin/isaac-installer install --profile full

# Custom YAML configuration file:
sudo ./bin/isaac-installer install --config my-custom-config.yaml
```

### 3. Dynamic CLI Overrides on Top of Profiles
```bash
# Standard workstation + selectively enable LeRobot:
sudo ./bin/isaac-installer install --with-lerobot

# Minimal headless server + selectively enable IsaacLab-Arena:
sudo ./bin/isaac-installer install --profile minimal --with-arena

# Clone personal fork with custom workspace directory:
sudo ./bin/isaac-installer install \
  --workspace-dir ~/Documents/GitHub/BoredEngineer \
  --isaaclab-repo BoredEngineer/IsaacLab \
  --arena-repo BoredEngineer/IsaacLab-Arena
```

### 4. Non-Destructive Pre-Flight Simulations
```bash
# Simulate default profile:
./bin/isaac-installer install --dry-run

# Simulate minimal profile:
./bin/isaac-installer install --dry-run --profile minimal

# 20-component audit diff report:
./bin/isaac-installer plan
```

### 5. Diagnostics & Health Verification
```bash
# Probe CPU, RAM, NVMe SSDs, LVM, GPU PCIe link, and Display:
./bin/isaac-installer doctor

# Run end-to-end 13-subsystem test suite:
./bin/isaac-installer test

# Check Cloud Hubs, OAuth & user permissions:
./bin/isaac-installer auth status
```
