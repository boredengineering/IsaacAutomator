# Architectural Plan: Harmonizing Isaac Installer & Ansible with the Host Architecture

**Document ID**: `isaac-installer-host-compat.md`  
**Target Subsystems**: `isaac-installer` (Bare-Metal Bash Provisioner) & `IsaacAutomator` (`src/ansible/` Cloud Engine)  
**Host Target**: Physical Ubuntu 22.04 LTS Workstation, NVIDIA RTX PRO 6000 Blackwell (`sm_120`), Driver 595.84, CUDA 13.2/13.3  
**Active Workspaces**: Isaac Sim 6.0.1, Isaac Lab v3 (v3.0), IsaacLab-Arena (`dev/0.3.0-prerelease`), Isaac-GR00T (`dev`), LeRobot  

---

## 1. Executive Summary & Problem Statement

When provisioning robotics foundation models and physics simulation on the host machine, `isaac-installer` failed and required extensive manual intervention. The installer was architected around assumptions from earlier generation hardware (Ada Lovelace `sm_89`, Hopper `sm_90`), legacy PyTorch wheels (`cu124`/`cu126`), monolithic Python package layouts, and flat repository directory paths.

On the host workstation—an **NVIDIA RTX PRO 6000 Blackwell Workstation Edition (96GB VRAM, `sm_120`)** running the latest **IsaacLab-Arena `dev/0.3.0-prerelease`** and **Isaac-GR00T** stacks—these assumptions caused cascading failures:
1. **CUDA Kernel Failures**: PyTorch wheels compiled for Ada/Hopper threw fatal binary incompatibilities (`no kernel image is available for execution on the device`) on `sm_120`.
2. **Modular Import Failures**: Arena's transition to a multi-package monorepo broke single-entry editable installs (`ModuleNotFoundError: isaaclab_arena_gr00t`).
3. **Missing Locomanipulation Solvers**: Whole-Body Control (WBC) packages (`pin-pink`, `qpsolvers`, `daqp`, `osqp`) required for Unitree G1 humanoid control were omitted.
4. **Environment Breakage**: A bash template expansion bug corrupted `/usr/local/bin/isaaclab-env`, and Omniverse Kit's internal Python stdlib polluted Conda.
5. **Teleoperation Latency**: FTDI-only udev rules ignored ACM and generic USB-serial converters used by dexterous hands and master arms.
6. **Bleeding-Edge Dependency Collisions**: Upstream FlashAttention kernel issues on CUDA 13.x forced foundation model serving into isolated Docker containers (Port 5561) rather than native host processes.

This plan specifies the architecture to update both **`isaac-installer`** and **`IsaacAutomator` Ansible roles** so that both provisioners natively support Blackwell workstations, modern modular robotics repos, and hybrid containerized foundation model workflows without manual fixes.

---

## 2. Host Reality vs. Installer Assumptions: The 9 Core Discrepancies

The table below contrasts what the automated tools currently assume versus what the host workstation actually requires:

| # | Discrepancy Dimension | `isaac-installer` / Ansible Assumption | Host Machine Reality & Manual Fix | Technical Impact |
| :- | :--- | :--- | :--- | :--- |
| **1** | **GPU Architecture & PyTorch Wheels** | Assumes `sm_89` / `sm_90`. Hardcodes `torch==2.5.1+cu124` or `cu126`. | **Blackwell `sm_120`**. Requires `torch==2.10.0+cu128` (or nightly with `sm_120` fatbin). | Execution crashes immediately on GPU kernel launch. |
| **2** | **UV Lockfile Rollback Trap** | Executes `uv sync` in `Isaac-GR00T` using upstream `uv.lock`. | Upstream `uv.lock` specifies `cu126` wheels. `uv sync` silently downgrades working PyTorch `cu128`. | Running the installer re-breaks a manually fixed environment. |
| **3** | **Arena Packaging & Submodule Topology** | Assumes monolithic repo; runs `pip install -e .` in repo root; assumes vanilla upstream submodules. | **Modular Monorepo + Forked Submodules**: 8 root packages (`isaaclab_arena*`, `_gr00t`, `_g1`, etc.); submodules point to `boredengineering/` forks on branch `dev/arena_v0.3.0-compat`. | `ModuleNotFoundError` or checkout desynchronization. |
| **4** | **Whole-Body Control (WBC) Dependencies** | Only installs standard RL frameworks (`rsl_rl`, `rl_games`, `sb3`). | Unitree G1 locomanipulation requires `pin-pink`, `libpinocchio`, `qpsolvers`, `daqp`, `osqp`. | Policy runners and WBC trajectory solvers fail to import. |
| **5** | **Zero-Activation Shim (`isaaclab-env`)** | Bash heredoc writes `CONDA_PY="${env_path}/bin/python"` without escaping. | Template generation evaluated `${env_path}` to empty, writing `CONDA_PY="/bin/python"`. | Running `isaaclab-env` executes system Python `/bin/python` instead of Conda. |
| **6** | **Kit Python Stdlib Isolation** | Sources `${ISAACSIM_PATH}/setup_python_env.sh` directly into Conda. | Kit Python 3.12 stdlib shadows Conda libraries. Fixed via filtered `PYTHONPATH` & `.pth`. | C-extension symbol mismatches and standard library crashes. |
| **7** | **Teleoperation Serial Latency** | Installs udev rule strictly for `DRIVER=="ftdi_sio"`. | DexHand & Master Arms use `KERNEL=="ttyUSB*"` and `KERNEL=="ttyACM*"`. Set `latency_timer=1`. | 16ms default USB latency causes control instability at >100Hz. |
| **8** | **Foundation Model Serving Stack** | Assumes native host Python process on port 5555. Default `~/.cache` paths. | Containerized `gr00t-server` (`gr00t-dev:latest`) on **Port 5561**; Dedicated `/home/tarfy/models`. | Port collisions, cache exhaustion on root partition, build failures on host. |
| **9** | **Directory Hierarchy & Casing** | Enforces flat `~/IsaacLab` or lowercase `~/.../boredengineering/`. | Host uses `Documents/GitHub/BoredEngineer/` (`dev/0.3.0-prerelease`). | False-positive drift errors (`PATH_MISLOCATED`, `REF_DRIFT`). |
| **10** | **Agent Setup & Fresh Machine Permissions** | Assumes raw script execution. Ignores host directory preparation. | Docker mounts create `models`, `datasets`, `.agents/memory` as `root:root`. Missing `.env` credentials, missing Docker group access. | Permission denial (`PermissionError [Errno 13]`), failed first run on fresh machines. |
| **11** | **GR00T & IsaacLab Branch Fragmentation** | Assumes vanilla upstream repos tracking `main` or detached tags. | Embedded submodules track forked **`dev/arena_v0.3.0-compat`** (`7b8f37e` with geometry conditioning, 6 nested submodules); standalone clones track release tags. | Submodule desynchronization, `reference is not a tree`, missing nested dependencies. |
| **12** | **Graph-RAG Knowledge Memory (Neo4j)** | Ignores agentic environment memory; no Neo4j provisioning. | `neo4j-arena` (Neo4j 5.26) on ports **`7475/7688`** storing RDF-star / LPG experience graphs (650+ episodes). | Evaluation loop cannot retrieve prior failure modes; repeated GPU waste. |

---

## 3. Compatibility Architecture & Target State

To support both bleeding-edge workstations (Blackwell `sm_120` / CUDA 13.x) and mainstream cloud VMs (Ada `sm_89` / Hopper `sm_90` / Ampere `sm_80`), the provisioners will implement an **Adaptive Architecture Pipeline**:

```mermaid
flowchart TD
    subgraph Probe["1. Hardware & Topology Discovery"]
        P1["Query GPU Compute Capability\n(nvidia-smi --query-gpu=compute_cap)"]
        P2["Detect Repo Casing & Git Branches\n(BoredEngineer vs boredengineering)"]
        P3["Inspect Arena Structure\n(Check for source/isaaclab_arena_*)"]
    end

    subgraph Decision["2. Dynamic Adaptation Matrix"]
        P1 -->|Cap >= 12.0 (Blackwell)| D1["Wheel Target: cu128 / torch 2.10+\nFlag: TORCH_CUDA_ARCH_LIST='12.0+PTX'"]
        P1 -->|Cap 9.0 (Hopper) / 8.9 (Ada)| D2["Wheel Target: cu124 / torch 2.5.1\nFlag: TORCH_CUDA_ARCH_LIST='9.0;8.9'"]
        P2 --> D3["Resolve Canonical Repo Paths\nBind Symlinks to Workspace Directory"]
        P3 -->|Modular Monorepo| D4["Batch Editable Installs:\n_arena, _gr00t, _g1"]
    end

    subgraph Execution["3. Convergent Provisioning"]
        D1 & D2 --> E1["roles/conda & lib/modules/conda.sh\nInstall Matching PyTorch Wheel"]
        D1 --> E2["Lockfile Guard: uv sync --no-install-package torch"]
        D4 --> E3["roles/isaaclab-arena-source\nInstall Modular Subpackages"]
        E1 --> E4["Provision WBC Stack:\npin-pink, libpinocchio, qpsolvers, daqp"]
        E4 --> E5["Deploy Escaped isaaclab-env Shim\n& Filtered isaacsim_standalone.pth"]
        E5 --> E6["Deploy Low-Latency Udev (ttyUSB* / ttyACM*)\n& Dual-Mode GR00T (Host or Docker Port 5561)"]
    end
```

---

## 4. Phased Implementation Plan

### Phase 1: Hardware Compute Capability Probing & Dynamic Wheel Resolution
* **Objectives**: Prevent CUDA architecture mismatch errors on Blackwell (`sm_120`) and future architectures without breaking compatibility with Ada/Hopper.
* **Tasks**:
  1. **Add GPU Architecture Prober**:
     * In `isaac-installer/lib/modules/system.sh` and Ansible `roles/nvidia-driver/tasks/main.yaml`:
       Query `nvidia-smi --query-gpu=compute_cap --format=csv,noheader` (e.g. returns `12.0`).
  2. **Implement PyTorch Matrix Resolver**:
     * If `compute_cap >= 12.0`:
       * Set `torch_wheel_channel="https://download.pytorch.org/whl/cu128"`
       * Set `torch_version_spec="torch==2.10.0+cu128 torchvision==0.25.0+cu128"`
       * Export `TORCH_CUDA_ARCH_LIST="12.0+PTX"`
     * Else (`compute_cap < 12.0`):
       * Fallback to standard stable wheels (`cu124` or `cu126`).
  3. **Mitigate Astral `uv` Rollback Trap**:
     * When running `uv sync` in `Isaac-GR00T` or related repos, inject `--no-install-package torch --no-install-package torchvision` or dynamically patch `pyproject.toml` to declare the cu128 wheel index.

### Phase 2: Modular Packaging & Submodule Topology for IsaacLab-Arena (`0.3.0-prerelease`)
* **Objectives**: Support both legacy single-package Arena checkouts and the host's 8-package monorepo with forked `dev/arena_v0.3.0-compat` submodules.
* **Tasks**:
  1. **Monorepo Root Package Discovery**:
     * Detect root packages configured via `[tool.setuptools.packages.find]`:
       `isaaclab_arena`, `isaaclab_arena_gr00t`, `isaaclab_arena_g1`, `isaaclab_arena_environments`, `isaaclab_arena_examples`, `isaaclab_arena_curobo`, `isaaclab_arena_dreamzero`, `isaaclab_arena_openpi`.
     * Support editable installation in Conda via setuptools/uv: `isaaclab-env pip install -e .` ensuring all `isaaclab_arena*` namespaces are registered.
  2. **Forked Submodule Alignment (`boredengineering`)**:
     * Inspect `.gitmodules` for `submodules/IsaacLab` and `submodules/Isaac-GR00T`.
     * Verify submodules track `origin` (`boredengineering/`) on branch `dev/arena_v0.3.0-compat`.
     * Maintain dual-remote setup (`origin` -> personal fork, `upstream` -> official `isaac-sim/IsaacLab` or `NVIDIA/Isaac-GR00T`).
  3. **Dual-Flavor Sim Stack (`isaaclab-from-source` vs `isaaclab-from-wheel`)**:
     * Recognize Arena's `pyproject.toml` dependency groups:
       * `isaaclab-from-source`: Editable mappings of the 15 Isaac Lab subpackages under `submodules/IsaacLab/source/isaaclab*`.
       * `isaaclab-from-wheel`: Wheel installation of `isaaclab[isaacsim,all]==3.0.0b2`.
  4. **Site-Packages Link Verification**:
     * Ensure `.pth` entries or editable finder shims exist in `${CONDA_PREFIX}/lib/python3.12/site-packages/` and verify via:
       `isaaclab-env python -c "import isaaclab_arena; import isaaclab_arena_gr00t; import isaaclab_arena_g1; print('Arena modular OK')"`

### Phase 3: Whole-Body Control (WBC) & Robotics Kinematics Solvers
* **Objectives**: Provide first-class support for Unitree G1 humanoid locomanipulation and inverse kinematics.
* **Tasks**:
  1. **Define WBC Dependency Spec**:
     * Package list:
       * `pin-pink>=3.1.0` (Task-space inverse kinematics for humanoid robots)
       * `libpinocchio>=3.9.0` (Rigid body dynamics library)
       * `qpsolvers>=4.13.0` (Unified QP interface)
       * `daqp>=0.8.5` (Dual Active-Set QP solver for model-predictive control)
       * `osqp>=1.0.5` (Operator Splitting QP solver)
       * `mujoco>=3.8.1`, `mujoco-warp>=3.8.1` (Physics validation & Warp integration)
  2. **Integrate into Ansible & Installer**:
     * In Ansible: Add `wbc_dependencies` list in `roles/isaaclab-arena-source/defaults/main.yaml`.
     * In `isaac-installer`: Add `install_wbc_solvers` step in `lib/modules/isaaclab_arena.sh`.

### Phase 4: Zero-Activation Shim Fix & Omniverse Kit Stdlib Sanitization
* **Objectives**: Fix the fatal variable expansion bug in `isaaclab-env` and protect Conda packages from Kit stdlib shadowing.
* **Tasks**:
  1. **Fix `isaaclab-env` Generator**:
     * In `isaac-installer/lib/modules/conda.sh` and Ansible `roles/conda/templates/isaaclab-env.j2`:
       * Correctly escape Bash variables during heredoc file generation (`\${env_path}` instead of unescaped `${env_path}`).
       * Guarantee generated line reads: `CONDA_PY="/home/{{ ansible_user }}/miniconda3/envs/isaaclab/bin/python"`.
  2. **Deploy Clean `isaacsim_standalone.pth`**:
     * Place `isaacsim_standalone.pth` in `${CONDA_PREFIX}/lib/python3.12/site-packages/` linking the 7 required Omniverse Kit Python directories without exporting Kit's standard library.
  3. **Sanitize Sourced Kit Environments**:
     * In `setup_conda_env.sh`, strip `kit/python/lib/python3.12` from `PYTHONPATH` using `grep -v`.

### Phase 5: Comprehensive Teleoperation Serial Latency Rules
* **Objectives**: Ensure real-time serial responsiveness for master arms, gloves, and dexterous hands (Unitree, DexHand).
* **Tasks**:
  1. **Expand `/etc/udev/rules.d/99-ftdi-latency.rules`**:
     ```udev
     # High-Frequency Low-Latency USB Serial for Robotics Teleop (1ms)
     ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"
     ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyUSB*", ATTR{device/latency_timer}="1"
     ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyACM*", ATTR{device/latency_timer}="1"
     ```
  2. **Ansible Task & Udev Reload**:
     * In `roles/hardware-teleop/tasks/main.yaml`, template the expanded rules file and invoke `udevadm control --reload-rules && udevadm trigger`.

### Phase 6: Dual-Mode Foundation Model Serving (Native vs. Containerized Port 5561)
* **Objectives**: Support both native Python GR00T serving and containerized serving on modern architectures.
* **Tasks**:
  1. **Add Serving Mode Toggle**:
     * Introduce `gr00t_serving_mode: "container"` (default on Blackwell `sm_120`) vs `"native"`.
     * Configure service port: Default to **Port 5561** (matching host `g1_sim_wbc_data_gr00t_n_1_7_config.py` and preventing port 5555 conflicts).
  2. **Containerized Systemd Service Unit**:
     * Deploy `isaac-gr00t-container.service` running Docker with `--gpus all`, `--ipc=host`, `--network host`, binding model weights from `/home/{{ ansible_user }}/models/isaaclab_arena`.
  3. **Neo4j 3D Scene Graph LPG Container**:
     * Provision `neo4j-arena` (Neo4j 5.26) systemd service for scene graph queries.
  4. **Dedicated Model and Dataset Storage Hierarchy**:
     * Standardize storage roots:
       * `/home/{{ ansible_user }}/models/isaaclab_arena`
       * `/home/{{ ansible_user }}/datasets/isaaclab_arena`

### Phase 7: Case-Insensitive Git Workspace Discovery & Drift Auditing
* **Objectives**: Eliminate false-positive drift warnings and support existing GitHub directory conventions.
* **Tasks**:
  1. **Case-Insensitive Directory Matcher**:
     * Update `lib/core/git_workspace.sh` and Ansible workspace resolution to search for `BoredEngineer` or `boredengineering` using find/globbing.
  2. **Reflect Working Branch in State Ledger**:
     * Update `.isaac-state.json` schema to capture `active_branch: "dev/0.3.0-prerelease"`.
     * When evaluating drift, compare against active branch rather than forcing `main`.


### Phase 8: Fresh-Machine Bootstrap & First-Run Reliability
* **Objectives**: Eliminate the 7 recurring failure modes that prevent smooth initialization and execution of agent workflows and simulation on a clean/fresh host machine.
* **Tasks**:
  1. **Automated Submodule SSH-to-HTTPS Fallback Rewriter**:
     * `.gitmodules` uses SSH URLs (`git@github.com:boredengineering/...`). On fresh machines lacking configured GitHub SSH keys, `git submodule update --init --recursive` crashes with `Permission denied (publickey)`.
     * Task: Implement a pre-flight git configuration check in `lib/core/git_workspace.sh` and Ansible `roles/isaaclab-arena-source/tasks/submodules.yml`:
       ```bash
       if ! ssh -o BatchMode=yes -o ConnectTimeout=3 -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
           echo "⚠️ GitHub SSH authentication unavailable. Configuring HTTPS URL rewrites for submodules..."
           git config --global url."https://github.com/".insteadOf "git@github.com:"
       fi
       ```
  2. **Pre-emptive Host Directory Scaffolding & Ownership Guard**:
     * DevContainer and `docker run` bind-mount `${HOME}/datasets`, `${HOME}/models`, `${HOME}/eval`, and `${HOME}/.cache/huggingface`. If Docker launches before these directories exist, Docker daemon creates them as `root:root` with 0755 permissions, leading to fatal `PermissionError: [Errno 13]` when non-root users/agents attempt writes.
     * Task: Port the full logic of `.devcontainer/ensure_host_directories.sh` into Ansible `roles/common/tasks/directories.yml` and `isaac-installer/lib/modules/system.sh`. Ensure directories are created under `ansible_user` / host user ownership before any container engine executes:
       * `${HOME}/datasets/isaaclab_arena/{locomanipulation_tutorial,sequential_static_manipulation_tutorial,static_apple_tutorial}`
       * `${HOME}/models/isaaclab_arena/{locomanipulation_tutorial,sequential_static_manipulation_tutorial,dexsuite_lift,reinforcement_learning,static_apple_tutorial}`
       * `${HOME}/eval/isaaclab_arena/{locomanipulation_tutorial,camera_sensitivity}`
       * `${HOME}/.cache/huggingface`, `${HOME}/.aws`, `${HOME}/.config/gcloud`, `${HOME}/.azure`, `${HOME}/.config/gh`, `${HOME}/.config/osmo`
  3. **Docker Group Membership & Socket Accessibility**:
     * DevContainer utilizes Docker-outside-of-Docker (`/var/run/docker.sock`). If the user is not in the `docker` group, container commands fail.
     * Task: In Ansible `roles/docker/tasks/main.yml` and installer `lib/modules/system.sh`, ensure `usermod -aG docker $USER`, set permissions on `/var/run/docker.sock`, and invoke `newgrp docker` or reload systemd user session.
  4. **Declarative `.env` Configuration Scaffolder**:
     * Fresh machines lack `.env` in `IsaacLab-Arena`, crashing VLM-guided scene generation and Hugging Face model downloads.
     * Task: Generate `.env` from template with sanity validation:
       * `OPENROUTER_API_KEY`: Required for active inference, task grounding, and RDF-Star scene generation.
       * `OPENROUTER_BASE_URL`: Defaults to `https://openrouter.ai/api/v1`.
       * `HF_TOKEN`: Required for downloading fine-tuned checkpoints and gated model weights.
       * `NEO4J_URI`: Defaults to `bolt://localhost:7688`.
       * `NEO4J_USER`: `neo4j` / `NEO4J_PASSWORD`.
  5. **Node.js LTS & NVIDIA Agent Skills Caching**:
     * `init_agent_workspace.sh` invokes `npx -y skills add nvidia/skills --skill '*' --copy -y`. On a clean machine, missing Node.js or network latency during bulk download of 340+ skills causes bootstrap timeouts.
     * Task: Install Node.js LTS in system provisioners, and provide on-demand / cached installation of essential robotics skills (`accelerated-computing-cudf`, `cudaq-guide`, `omniverse-*`) rather than blocking whole-repo clones.
  6. **ZeroMQ Port Guard & Allocation**:
     * Upstream default port `5555` collides with VS Code Server internal tunnels.
     * Task: Enforce policy daemon port configuration to **`5556`** for host native processes and **`5561`** for containerized daemons. Validate port availability via `lsof -i :<port>` or `ss -tulpn` before launching.
  7. **Single-Thread Pinocchio Concurrency Guard**:
     * First-time users frequently launch evaluation scripts with `--num_envs > 1`, causing immediate deadlocks in `g1_wbc_pink`'s Pinocchio QP solver.
     * Task: Enforce `--num_envs 1` in all generated shell scripts, launch configurations, and agent CLI wrappers when `wbc_pink` controller is selected.

---

### Phase 9: Isaac-GR00T & IsaacLab Branch Invariants & Nested Submodule Topology
* **Objectives**: Maintain strict synchronization across the 3-tier repository layout (Arena Monorepo $\to$ Submodules $\to$ Nested Submodules) and prevent detached HEAD drift.
* **Tasks**:
  1. **Document & Enforce Repository Topology**:
     * **Monorepo Root**:
       * Canonical Workspace: `/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena` (PascalCase `BoredEngineer`)
       * Active Branch: `dev/0.3.0-prerelease`
       * Remote `origin`: `git@github.com:boredengineering/IsaacLab-Arena.git`
       * Remote `upstream`: `git@github.com:isaac-sim/IsaacLab-Arena.git`
     * **Submodule 1: `Isaac-GR00T` (`submodules/Isaac-GR00T`)**:
       * Active Branch: **`dev/arena_v0.3.0-compat`** (Commit `7b8f37e`)
       * Remote `origin`: `git@github.com:boredengineering/Isaac-GR00T.git`
       * Remote `upstream`: `https://github.com/NVIDIA/Isaac-GR00T.git`
       * Critical Features in Branch:
         * `feat(gr00t_n1d7): geometry-conditioned embedding alignment (Spatial Forcing)` (Commit `792c547`)
         * Pinned dependencies: `depth-anything-3` and `GR00T-WholeBodyControl` (Commit `e58bf16`)
         * Strict DA3 backbone loading with tolerated discarded head (Commit `d78207d`)
         * Inference OOM protection: teacher model kept out of GPU memory during eval (Commit `e500114`)
         * Lean runnable align arm (Commit `7b8f37e`)
       * **6 Nested Submodules under `external_dependencies/`**:
         * `GR00T-WholeBodyControl`: Branch `remotes/origin/ry/fix_lang-4-g3966393` (Commit `3966393e`)
         * `LIBERO`: Branch `master` (Commit `8f1084e3`)
         * `SimplerEnv`: Branch `main` (Commit `8a2d286c`), containing child `ManiSkill2_real2sim` (`c2a9e87c`)
         * `depth-anything-3`: Branch `main` (Commit `3d835ec1`), containing child `salad` (`6aede13a`)
         * `robocasa`: Branch `main` (Commit `d89d481c`)
         * `robocasa-gr1-tabletop-tasks`: Branch `main` (Commit `4840e671`)
     * **Submodule 2: `IsaacLab` (`submodules/IsaacLab`)**:
       * Active Branch: **`dev/arena_v0.3.0-compat`** (Commit `ffff603ea` "Updates pyarrow version (#6310)")
       * Remote `origin`: `git@github.com:boredengineering/IsaacLab.git`
       * Remote `upstream`: `https://github.com/isaac-sim/IsaacLab.git`
     * **Standalone Reference Clones (`~/Documents/GitHub/boredengineering/`)**:
       * `Isaac-GR00T`: Tracks `main` (Commit `626af89`, N1.7 release metrics & RoboCasa benchmarks).
       * `IsaacLab`: Tracks `release/v3.0.0-beta2` (Commit `28a37cecd`).
       * `IsaacLab-Arena`: Tracks `release/0.3.0-prerelease` (Commit `62a5339cc`).
  2. **Automate Submodule Sync & Disaster Recovery (`submodule_shenanigans.md`)**:
     * In Ansible `roles/isaaclab-arena-source` and installer `lib/modules/isaaclab_arena.sh`:
       Implement automated submodule validation:
       * Check if submodules are on detached HEADs; if detached, checkout canonical branches (`dev/arena_v0.3.0-compat`).
       * Run `git submodule update --init --recursive` with depth verification.
       * Incorporate the disaster recovery scenarios from `submodule_shenanigans.md` (Scenario A: lost branch recovery via reflog; Scenario B: main repo dirt recovery; Scenario C: remote URL restoration; Scenario D: clean deinit & re-clone).

---

### Phase 10: Neo4j Graph-RAG Experience Memory Orchestration
* **Objectives**: Provision and integrate Neo4j 5.26-community for 3D scene graphs, causal episode autopsies, and active inference memory.
* **Tasks**:
  1. **Deploy Containerized `neo4j-arena` Service**:
     * Container image: `neo4j:5.26-community`
     * Port Mapping: **`7475:7474`** (HTTP Browser) and **`7688:7687`** (Bolt Protocol) to avoid collisions with default host Neo4j services.
     * Persistent Data Volume: `${HOME}/data/neo4j:/data`.
     * Environment: `NEO4J_AUTH=neo4j/isaaclab_arena_2026`, `NEO4J_PLUGINS=["apoc"]`.
  2. **Experience Memory Integration**:
     * Wire environment variables in `.env` and bash profile:
       `NEO4J_URI=bolt://localhost:7688`, `NEO4J_USER=neo4j`.
     * Pre-load episode failure graph schema (650+ episodes: contact termination bugs, PhysX interpenetration catapults, vertical OOD surface shifts).
     * Verify connection via Python driver in Conda environment:
       `python -c "from neo4j import GraphDatabase; driver = GraphDatabase.driver('bolt://localhost:7688', auth=('neo4j', 'isaaclab_arena_2026')); driver.verify_connectivity(); print('Neo4j Connected')"`

---

### Phase 11: Decoupled Dual-Runtime & ZeroMQ Service IPC Safety
* **Objectives**: Enforce the dual-runtime architecture, preventing corrupt monolithic python installations and ensuring stable ZeroMQ policy serving.
* **Tasks**:
  1. **Enforce Dual-Runtime Separation**:
     * **Simulation Runtime**: Isaac Sim 6.0.1 / Isaac Lab v3 / Python 3.12 / CUDA 12.8 in Docker container (`isaaclab_arena:latest` via `./docker/run_docker.sh`).
     * **Foundation Policy Daemon**: Python 3.10 / PyTorch `cu128` on host via `uv` or isolated container (`gr00t-server` via `gr00t-dev:latest`).
     * Explicit guard: Never attempt to install Isaac Sim Kit inside the host Python 3.10 GR00T training environment.
  2. **Automate ZeroMQ Daemon Management**:
     * Provide unified management script `run_gr00t_daemon.sh` supporting:
       * Port 5556 (native host daemon)
       * Port 5561 (Docker container daemon)
     * Enforce modality configuration: `NEW_EMBODIMENT` + `ego_view` for Unitree G1 humanoid; `OXE_DROID` + stereo for Franka Droid.
     * Health check endpoint: ZeroMQ `ping` returning `{"status": "ok", "message": "Server is running"}` and `get_modality_config`.

---

## 5. Technical Verification & Acceptance Criteria

| Subsystem | Verification Command | Expected Successful Output |
| :--- | :--- | :--- |
| **GPU Architecture** | `python -c "import torch; print(torch.cuda.get_device_name(0), torch.cuda.get_arch_list())"` | Contains `RTX PRO 6000` and `'sm_120'` in arch list. |
| **Zero-Activation Shim** | `isaaclab-env python -c "import sys; print(sys.executable)"` | Outputs `/home/.../miniconda3/envs/isaaclab/bin/python` (NOT `/bin/python`). |
| **Modular Arena Imports** | `isaaclab-env python -c "import isaaclab_arena_gr00t; import isaaclab_arena_g1; print('OK')"` | Outputs `OK` without `ModuleNotFoundError`. |
| **WBC Solvers** | `isaaclab-env python -c "import pink; import qpsolvers; import daqp; print('WBC OK')"` | Outputs `WBC OK`. |
| **Omniverse Kit Isolation** | `isaaclab-env python -c "import sys; assert not any('kit/python/lib' in p for p in sys.path); print('Clean')"` | Outputs `Clean` (no Kit stdlib shadowing). |
| **Udev Latency Rules** | `cat /etc/udev/rules.d/99-ftdi-latency.rules` | Contains `ttyUSB*` and `ttyACM*` rules. |
| **GR00T Submodule Branch** | `cd submodules/Isaac-GR00T && git branch --show-current && git log -1 --oneline` | Outputs `dev/arena_v0.3.0-compat` and commit `7b8f37e`. |
| **Nested Submodules** | `cd submodules/Isaac-GR00T && git submodule status` | Shows 6 submodules checked out cleanly without leading minus (`-`). |
| **Host Directory Perms** | `ls -ld ~/models ~/datasets ~/eval ~/.cache/huggingface` | Owned by `$USER:$USER` (NOT `root:root`). |
| **ZeroMQ Service** | `python -c "import zmq; ctx=zmq.Context(); s=ctx.socket(zmq.REQ); s.connect('tcp://127.0.0.1:5561'); s.send_json({'command': 'ping'}); print(s.recv_json())"` | Outputs `{'status': 'ok', 'message': 'Server is running'}`. |
| **Neo4j Bolt Connectivity**| `nc -zv 127.0.0.1 7688` | Outputs `Connection to 127.0.0.1 7688 port [tcp/*] succeeded!`. |
| **WBC Concurrency** | `python -c "assert '--num_envs 1' in open('tools/run_g1_eval.sh').read()"` | Passes assertion without exception. |

---

## 6. Next Steps & Review Checkpoints

1. **Review and Tailor**:
   * Review this completed plan at [`.agents/references/plans/isaac-installer-host-compat.md`](file:///workspaces/IsaacAutomator/.agents/references/plans/isaac-installer-host-compat.md).
   * Specify any modifications to port numbers (e.g. 5561 vs 5556), custom embodiment paths, or repo casing rules.
2. **Execution Readiness**:
   * Once aligned, we will proceed to implement the updates in small, testable chunks:
     1. Ansible roles (`roles/common`, `roles/conda`, `roles/isaaclab-arena-source`, `roles/hardware-teleop`, `roles/neo4j`).
     2. `isaac-installer` modules (`lib/core/git_workspace.sh`, `lib/modules/system.sh`, `lib/modules/conda.sh`, `lib/modules/isaaclab_arena.sh`).
   * All changes will be verified with dry-runs and non-destructive syntax checks.

