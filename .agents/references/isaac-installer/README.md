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

# Audit workspace state and remote drift:
./bin/isaac-installer drift

# Automatically reconcile and heal workspace drift:
sudo ./bin/isaac-installer repair
```

---

## Dual-Remote Fork Topology & Development Workflows

When developing physical AI and robotics models, developers need access to their personal GitHub fork for pushing custom experiments and branches, while simultaneously pulling official releases, tags, and PR changes from NVIDIA upstream.

`isaac-installer` automatically configures this **Dual-Remote Git Topology**:

```text
=== Git Remotes (.git/config) ===
origin    https://github.com/boredengineering/IsaacLab.git (fetch & push allowed)
upstream  https://github.com/isaac-sim/IsaacLab.git (fetch only)
          🔒 pushurl: PUSH_DISABLED_CANONICAL_UPSTREAM
```

### Day-to-Day Developer Workflows:

#### Workflow A: Developing Features & Opening Upstream PRs
```bash
# 1. Switch to your main branch
git checkout main

# 2. Sync your local main with NVIDIA upstream/main and push to your fork:
./bin/isaac-installer lab sync

# 3. Create your new feature branch:
git checkout -b feature/my-new-robot

# 4. Make edits, train models, commit changes:
git add .
git commit -m "feat: implement custom humanoid task"

# 5. Push your feature branch to your personal fork (Push is allowed):
git push -u origin feature/my-new-robot

# 6. Open a Pull Request from boredengineering/IsaacLab -> isaac-sim/IsaacLab
# (Via GitHub Desktop or 'gh pr create')
```

#### Workflow B: Pinned Release Tags (e.g. Isaac Sim 6.0 Compatibility)
```bash
# To switch to a different official release tag:
./bin/isaac-installer lab list-tags
./bin/isaac-installer lab switch v3.0.0-beta2
```

### Dual-Remote CLI Commands:

#### Isaac Lab (`lab`):
```bash
# View active branch, tag, commit, and upstream sync telemetry:
./bin/isaac-installer lab status

# Inspect full remote URLs and push guards:
./bin/isaac-installer lab remotes

# Synchronize branch with upstream:
./bin/isaac-installer lab sync

# Abort an in-progress rebase or merge:
./bin/isaac-installer lab sync --abort

# Re-wire origin remote to another fork or organization:
./bin/isaac-installer lab fork boredengineering/IsaacLab
```

#### IsaacLab-Arena (`arena`):
```bash
# View active Arena branch, tag, commit, and sync status:
./bin/isaac-installer arena status

# Inspect Arena remote URLs and push guards:
./bin/isaac-installer arena remotes

# Synchronize Arena branch with upstream:
./bin/isaac-installer arena sync

# Switch Arena release tags/branches:
./bin/isaac-installer arena switch release/0.3.0

# Re-wire Arena origin remote to your personal fork:
./bin/isaac-installer arena fork boredengineering/IsaacLab-Arena

# Run Arena validation and benchmark smoke test:
./bin/isaac-installer arena test
```

#### NVIDIA Isaac-GR00T (`gr00t`):
```bash
# View active Isaac-GR00T repository and model status:
./bin/isaac-installer gr00t status

# Run open-loop standalone inference on DROID demo dataset:
./bin/isaac-installer gr00t infer

# Launch ZeroMQ policy server (Port 5555):
./bin/isaac-installer gr00t server 5555

# Inspect GR00T remote URLs and push guards:
./bin/isaac-installer gr00t remotes

# Re-wire GR00T origin remote to your personal fork:
./bin/isaac-installer gr00t fork boredengineering/Isaac-GR00T

# Run core validation and test suite:
./bin/isaac-installer gr00t test
```
