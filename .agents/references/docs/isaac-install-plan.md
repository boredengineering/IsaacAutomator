# Universal Isaac & Physical AI Installer Architecture Plan (`isaac-install-plan.md`)

> **Document Status**: Under Active Architectural Review  
> **Target Platform**: Bare-Metal Workstations & Heterogeneous Physical AI Nodes (Ubuntu 22.04 LTS)  
> **Compute Scope**: NVIDIA Blackwell (GB200 / RTX 5090 / RTX PRO 6000), Ada Lovelace (RTX 4090 / L40S / 6000 Ada), Ampere (RTX 3090 / A100)

---

## 1. Executive Summary & Vision

The **Universal Isaac Installer (`isaac-installer`)** is the zero-infrastructure, bare-metal provisioner for robotics, Physical AI, and simulation engineers. While `IsaacAutomator` handles public cloud instances (AWS, GCP, Azure, Alibaba), `isaac-installer` transforms a fresh or existing physical machine into a high-performance, open-ended robotics workstation.

### The Real-World Developer Reality:
In production robotics and Physical AI research, developers do **not** work in a static, monolithic sandbox. They:
1. Maintain active Git forks of core frameworks (`IsaacLab`, `IsaacLab-Arena`, `lerobot`) and switch branches/tags rapidly.
2. Structure repositories cleanly under user/organization hierarchies (`~/Documents/GitHub/<Owner>/<Repo>`) matching their GitHub Desktop accounts.
3. Manage different Python dependencies across tasks without corrupting Isaac Sim's underlying runtime.
4. Require automated state tracking and self-healing: if repos are misplaced, remotes misconfigured, or symlinks broken, the installer automatically detects the drift, reconciles the state, and heals the workspace based on declarative YAML profiles.
5. Integrate real-time teleoperation hardware (ALOHA leader-follower arms, SpaceMouse, VR headsets, cameras) with sub-millisecond serial latency.

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
        U2["Workspace Hierarchy Engine (~/Documents/GitHub/<Owner>/<Repo>)"]
        U3["Dual-Remote Fork Topology (origin = user fork, upstream = canonical)"]
        U4["Dynamic Python Isolation & Environment Shims (isaaclab-env)"]
        U5["Topological Extension Installation (omni.isaac.lab -> tasks -> rl)"]
        U6["State Tracking, Drift Reconciliation & Self-Healing Engine"]
        U7["IDE & Desktop Integration (VS Code Discovery, GitHub Desktop UI)"]
    end

    PHASE1 -- "System Ready (No Root Required Afterwards)" --> PHASE2
```

---

## 3. Python Environment Architecture: Hybrid Conda + UV Pip Model

### 3.1 The Isaac Sim Pip Package vs. Standalone Engine Rationale

NVIDIA introduced `pip install isaacsim` (and modular wheels `isaacsim-rl`, `isaacsim-kernel`) on PyPI. While appealing for small CI test scripts, in real-world robotics development it presents severe landmines:

| Dimension | `pip install isaacsim` | Standalone Engine (`~/IsaacSim` + `_isaac_sim`) |
| :--- | :--- | :--- |
| **PyTorch & CUDA ABI Compatibility** | Bundles fixed C++ Carbonite symbols that clash with custom PyTorch versions, causing silent `SIGSEGV` or symbol errors. | Completely decoupled; runs with matched system CUDA drivers and runtime libraries. |
| **Vulkan Shaders & Kit Assets** | Lacks full native Omniverse asset packs and precompiled shader caches; causes renderer stutter and warmup failures. | Ships complete native USD assets, MaterialX shaders, and pre-warmed Vulkan pipelines. |
| **Download Reliability & Size** | 10+ separate multi-gigabyte wheels from PyPI; frequently times out or fails checksums on standard connections. | Single verified high-speed CDN archive or local cache with resume support. |
| **Isaac Lab Ecosystem Linkage** | Experimental; unsupported by many research extensions. | **The official gold standard**; expects `_isaac_sim` symlink with native `isaac-sim.sh` and `python.sh`. |

> **Architectural Decision**: `isaac-installer` strictly provisions the **Standalone Isaac Sim Engine** and links it into Isaac Lab via the POSIX `_isaac_sim` atomic symlink standard.

---

### 3.2 Conda vs. UV: Ergonomics vs. Speed Trade-Offs

In robotics workflows, developers move constantly between different project directories, ROS 2 workspaces, dataset stores, and IDEs.

```mermaid
flowchart TD
    subgraph CONDA_MODEL ["Conda / Mamba (Environment-Centric)"]
        C1["Named Envs in central location (~/.conda/envs/isaaclab)"]
        C2["Global activation from ANY folder: conda activate isaaclab"]
        C3["Auto-discovered by VS Code, Cursor, PyCharm, Jupyter"]
        C4["Manages non-Python C/C++ libs (libGL, FFmpeg, CUDA toolkit)"]
        C5["Downside: Standard solver and pip are notoriously slow"]
    end

    subgraph UV_MODEL ["UV (Project / Directory-Centric)"]
        U1["Local directory .venv by default (requires full path or cd)"]
        U2["Blazing fast installer (10x-50x faster than standard pip)"]
        U3["Does NOT manage system C/C++ binaries or CUDA drivers"]
        U4["Perfect for fast lockfiles and isolated CI/CD pipelines"]
        U5["Downside: Extra friction when moving between arbitrary terminal folders"]
    end
```

#### The Friction Points:
1. **The UV Friction Point**: UV defaults to directory-local virtual environments (`.venv`). If a developer is in `~/Documents` or a ROS 2 workspace, they cannot simply type `uv activate isaaclab`. They must either pass `--directory`, supply the full path (`source ~/Documents/GitHub/BoredEngineer/IsaacLab/.venv/bin/activate`), or maintain custom aliases.
2. **The Conda Friction Point**: Standard `conda install` and `pip install` inside Conda are slow, take 10–20 minutes to resolve large wheels like PyTorch and torchvision, and can fail with timeout errors on large extension builds.

---

### 3.3 The Solution: The Hybrid Conda + UV Pip Acceleration Model

We unify the global convenience of Conda with the blazing resolution speed of UV:

```mermaid
flowchart LR
    DEV["Developer / IDE / Terminal"] --> CONDA["Conda Named Environment\n('conda activate isaaclab')"]
    CONDA --> UV["UV Package Engine\n('uv pip install --python $CONDA_PREFIX/bin/python')"]
    UV --> EXT["Topological Editable Extensions\n(omni.isaac.lab, Arena, LeRobot)"]
    EXT --> RUNTIME["High-Performance Isaac Lab Runtime"]
```

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Hybrid Architecture Highlights:                                                        │
│                                                                                        │
│ 1. Central Named Environment:                                                          │
│    • Created via Miniforge/Conda: `conda create -y -n isaaclab python=3.10`            │
│    • Globally accessible from ANY terminal directory: `conda activate isaaclab`        │
│    • Automatically discovered by VS Code, Cursor, and PyCharm interpreters.            │
│                                                                                        │
│ 2. Sub-Second UV Package Acceleration:                                                 │
│    • Packages inside the Conda environment are installed via `uv pip`:                 │
│      `uv pip install --python "$CONDA_PREFIX/bin/python" torch==2.5.1+cu124`           │
│    • Editable extensions are installed in seconds:                                     │
│      `uv pip install --python "$CONDA_PREFIX/bin/python" -e source/extensions/...`     │
│    • Eliminates the 15-minute conda solver wait and pip timeout failures.              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 3.4 Shell Cleanliness & Scoped Activation Hook Guarantee

A major trap in manual Isaac Lab setups is sourcing `setup_conda_env.sh` inside `~/.bashrc`. This permanently pollutes the host shell with Omniverse `PYTHONPATH` and `LD_LIBRARY_PATH`, breaking non-simulation Python packages and system utilities.

`isaac-installer` guarantees **Zero Shell Contamination** using scoped Conda activation hooks:

```text
<User_Conda_Root>/envs/isaaclab/etc/conda/   (e.g. ~/miniconda3/envs/isaaclab/etc/conda/)
├── activate.d/
│   └── 00_isaaclab_env.sh      <-- Scopes Omniverse paths ONLY upon 'conda activate isaaclab'
└── deactivate.d/
    └── 00_isaaclab_env.sh      <-- Completely unsets and restores previous shell state upon 'deactivate'
```

#### Hook Implementation Logic:
* **Upon `conda activate isaaclab`**:
  Exports scoped variables:
  ```bash
  export EXP_PATH="${ISAACSIM_DIR}/apps"
  export ISAAC_PATH="${ISAACSIM_DIR}"
  export CARB_APP_PATH="${ISAACSIM_DIR}/kit"
  export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
  ```
* **Upon `conda deactivate`**:
  Restores original `PYTHONPATH`, `LD_LIBRARY_PATH`, and unsets all Omniverse environment variables.
* **Global `~/.bashrc`**:
  Remains **100% untouched and clean**. Non-Isaac terminals are never affected by simulation library paths.

---

### 3.4.1 Official NVIDIA Docs Note on Conda vs. Bundled Python & `./isaaclab.sh -p`

> **NVIDIA Official Documentation Guidance**:
> *"Combining an Isaac Sim binary installation with an unmanaged conda, uv, or venv virtual environment is not supported. Use Isaac Sim's bundled Python via `./isaaclab.sh -p` instead."*

#### Why NVIDIA States This & Why Our Architecture Solves It:
1. **The Core Hazard (ABI Mismatch & Library Paths)**:
   In raw/unmanaged virtual environments, developers frequently install mismatched PyTorch C++ binaries or execute scripts without setting `CARB_APP_PATH`, `EXP_PATH`, or `VK_ICD_FILENAMES`. When Python tries to load Isaac Sim's Carbonite bindings (`libcarb.so`, `libomni.ext.so`), it crashes with `SIGSEGV` or `undefined symbol: PyExc_...`.
2. **How `./isaaclab.sh` Operates Internally**:
   When inspected directly from Isaac Lab 3.0 source (`isaaclab.sh` lines 23–31):
   ```bash
   if [ -n "$CONDA_PREFIX" ]; then
       python_exe="$CONDA_PREFIX/bin/python"
   elif [ -f "$ISAACLAB_PATH/_isaac_sim/python.sh" ]; then
       python_exe="$ISAACLAB_PATH/_isaac_sim/python.sh"
   ```
   If a Conda environment is active (`$CONDA_PREFIX`), `isaaclab.sh` explicitly routes execution to the active Conda environment!
3. **The `isaac-installer` Harmony**:
   * We ensure the Conda environment matches the exact ABI (Python 3.12 for Sim 6.0; Python 3.10 for Sim 5.1).
   * We deploy scoped `activate.d` hooks so `conda activate isaaclab` injects the exact same Omniverse library paths as `_isaac_sim/python.sh`.
   * We execute the official `./isaaclab.sh --install` inside the healed Conda environment to link all editable extensions properly.
   * Both `python <script>` (under activated conda), `isaaclab-env python <script>`, and `./isaaclab.sh -p <script>` work 100% reliably in full harmony.

---

### 3.4.2 Conda Scripting Architecture: Why Naive Approaches Fail & The Robust Solution

Conda behaves fundamentally differently in non-interactive scripts and multi-user (`sudo`) environments compared to interactive developer shells. Understanding these mechanics explains why naive automated approaches fail and why our architecture succeeds:

#### 1. Why Naive Approaches Fail in Automation:

* **Why Naive Option A (`conda activate` in scripts) Fails**:
  * **Shell Function Dependency**: `conda activate` is not a binary executable on disk; it is an in-memory shell function injected into interactive terminals. Non-interactive subshells, cron, CI/CD runners, and `sudo -H -u` invocations do not load `~/.bashrc`, resulting in `CommandNotFoundError: Your shell has not been properly configured to use 'conda activate'`.
  * **Process Isolation**: In Unix process models, child subshells cannot mutate the environment of the parent process. Environment mutations made inside a subshell evaporate instantly upon subshell exit.
  * **The Root Multi-User Trap**: Running under `sudo` defaults to `root`. If an environment is created under `/opt/conda`, it is placed outside the target developer's default `envs_dirs` (`~/miniconda3/envs`), rendering it an **unnamed path-only environment** in `conda env list` and causing subsequent user `conda activate isaaclab` calls to fail with `EnvironmentNameNotFound`.

* **Why Naive Option B (Raw `uv` / `venv` outside Conda) Fails**:
  * **Omniverse C++ ABI & Missing Dynamic Libraries**: Isaac Sim requires Carbonite C++ bindings (`libcarb.so`, `libomni.ext.so`) and Vulkan configurations. Running inside an unmanaged `venv` without matching ABI and runtime hooks triggers immediate `SIGSEGV` segmentation faults or `ModuleNotFoundError: No module named 'omni'`.
  * **`isaaclab.sh --install` Routing**: Lines 23–31 of NVIDIA's `isaaclab.sh` specifically inspect `$CONDA_PREFIX`. In an unmanaged virtualenv without Conda prefix hooks, `isaaclab.sh` falls back to modifying Isaac Sim's internal bundled directory (`_isaac_sim/python.sh`), breaking multi-project isolation.

---

#### 2. The 4 Engineering Mechanisms of the Robust Solution:

Inheriting the verified patterns from [`setup-isaaclab02.sh`](../scripts/setup-isaaclab02.sh), `isaac-installer` implements four robust mechanisms:

1. **`conda run -n <env>` (Zero-Activation Subshell Execution)**:
   Instead of struggling with stateful `conda activate` in subshells, `conda run -n isaaclab <command>` executes any script or binary within the pre-configured environment without requiring shell hooks or environment mutation:
   ```bash
   conda run -n isaaclab ./isaaclab.sh -i
   conda run -n isaaclab python -c "import torch; print(torch.__version__)"
   ```
2. **Zombie Environment Health Guard**:
   Detects corrupted or interrupted installations (e.g. aborted PyTorch downloads) using an active Python probe:
   ```bash
   if conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME"; then
       if ! conda run -n "$CONDA_ENV_NAME" python --version &>/dev/null; then
           conda env remove -n "$CONDA_ENV_NAME" -y || true
           rm -rf "${env_path}"
       fi
   fi
   ```
3. **Environment Identity Enforcement (`SHELL=/bin/bash`)**:
   Explicitly exports `SHELL=/bin/bash`, `USER`, and `HOME` within `sudo -H -u <user>` subshells before calling `SHELL=/bin/bash ./isaaclab.sh --conda isaaclab` to prevent syntax and path resolution failures across varied developer default shells (`zsh`, `sh`).
4. **Quoted Heredoc Syntax (`<<'EOF'`)**:
   Prevents premature parameter expansion on the caller side, ensuring variables and `awk` scripts evaluate strictly inside the target user's execution context.

---

#### 3. Real-World Industry Instances & Documentation:

* **Anaconda Official Automation Guidelines**: Anaconda explicitly mandates `conda run` over `conda activate` in CI/CD pipelines (GitHub Actions, GitLab CI) and non-interactive scripts to eliminate shell initialization dependencies.
* **NVIDIA Isaac Lab Community & Issues (#284, #419)**: Community bug reports document `setup_conda_env.sh: source not found` and `unknown option` errors when running outside pure bash; explicit `SHELL=/bin/bash` and `conda run` execution is the verified resolution.
* **Cloud Robotics Deployments (AWS RoboMaker / Vertex AI GPU VMs)**: Headless containerized and cloud workstation provisioning requires non-interactive `conda run` to ensure isolation without shell pollution.

---

#### 4. Comprehensive Strategy Matrix:

| Strategy | Execution Mechanism | Non-Interactive Reliability | User Context & Naming | Isaac Sim C++ / Vulkan ABI | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Naive Option A** | `conda activate` in script | ❌ Fails (`CommandNotFoundError`) | ❌ Creates root `/opt/conda` | ⚠️ Pollutes `.bashrc` | Defective |
| **Naive Option B** | Raw `uv` / `venv` | ❌ Fails (`$CONDA_PREFIX` missing) | ⚠️ Unmanaged path | ❌ Crashes (`SIGSEGV` / `omni` missing) | Defective |
| **`setup-isaaclab02.sh` + `isaac-installer` Pipeline** | `conda run -n` + `./isaaclab.sh --conda` + Scoped `activate.d` | **✔ 100% Deterministic** | **✔ Native `~/miniconda3/envs/isaaclab`** | **✔ Zero Pollution & Full Omniverse ABI** | **SELECTED (Active Standard)** |

---

### 3.5 Developer Interaction Modes

The hybrid model supports all four primary robotics development workflows:

| Workflow Mode | Command / Invocation | Use Case |
| :--- | :--- | :--- |
| **1. Global Interactive Terminal** | `conda activate isaaclab`<br>`python scripts/reinforcement_learning/rsl_rl/train.py --task Isaac-Ant-v0` | Day-to-day interactive RL training and development from any directory. |
| **2. Native Isaac Lab Launcher** | `./isaaclab.sh -p scripts/tutorials/00_sim/create_empty.py` | Official standalone Isaac Lab launcher (auto-detects active `$CONDA_PREFIX`). |
| **3. Zero-Activation CLI Shim** | `isaaclab-env python train.py --task Isaac-Cartpole-v0` | Headless execution, bash scripts, tmux workers, or CI/CD pipelines without manual activation. |
| **4. IDE / Debugger** | Select `~/miniconda3/envs/isaaclab/bin/python` in IDE | Visual Studio Code, Cursor, PyCharm interactive breakpoints and linting. |

---

### 3.6 Topological Extension Installation Order

To guarantee stability, extensions and downstream packages must be compiled and linked in strict topological dependency order:

```mermaid
flowchart TD
    T0["0. Base Python 3.10 Runtime (Conda Env 'isaaclab')"]
    T1["1. Accelerated PyTorch CUDA via UV (torch==2.5.1+cu124 matching GPU Arch)"]
    T2["2. Core Extension: source/extensions/omni.isaac.lab"]
    T3["3. Asset Extension: source/extensions/omni.isaac.lab_assets"]
    T4["4. Tasks Extension: source/extensions/omni.isaac.lab_tasks"]
    T5["5. RL Extension: source/extensions/omni.isaac.lab_rl"]
    T6["6. RL Frameworks (rsl_rl, skrl, rl_games, stable-baselines3)"]
    T7["7. Benchmark Suite (IsaacLab-Arena via uv pip -e .)"]
    T8["8. Physical AI / Imitation Learning (LeRobot [all,dataset_viz])"]

    T0 --> T1 --> T2 --> T3 --> T4 --> T5 --> T6 --> T7 --> T8
---

### 3.7 Physical AI C++ Runtime, Dynamic Linker & ABI Compatibility Guide

Physical AI pipelines (Isaac Sim, Isaac Lab, LeRobot, TensorRT, RSL-RL) merge modern Python wrappers with complex C++ shared libraries (`.so`), CUDA kernels, and Vulkan GPU surfaces. Understanding the dynamic linker (`ld.so`) and C++ runtime interactions is essential for debugging and long-term pipeline planning:

#### 1. The `libstdc++.so.6` & `GLIBCXX` Symbol Conflict:
* **The Root Cause**:
  Linux distributions (such as Ubuntu 22.04 LTS) ship with a base GNU C++ standard library (`/lib/x86_64-linux-gnu/libstdc++.so.6`) providing symbols up to `GLIBCXX_3.4.30` (GCC 11/12). Modern pre-compiled binaries (e.g. `conda-libmamba-solver`, PyTorch CUDA 12.4 C++ extensions, Hugging Face Rust/C++ bindings) are compiled against GCC 13/14, requiring `GLIBCXX_3.4.31` or higher.
* **The Dynamic Linker Collision**:
  When Python loads a C++ module, Linux searches system library paths first. If the system's older `libstdc++.so.6` is loaded before Conda's newer `miniconda3/lib/libstdc++.so.6`, the dynamic linker throws:
  ```text
  Error while loading conda entry point: conda-libmamba-solver: version GLIBCXX_3.4.31 not found
  ```
* **Architectural Safeguards**:
  1. **Disable Broken Entry Points in Automation**: Set `export CONDA_NO_PLUGINS=true` and `export CONDA_SOLVER=classic` to bypass libmamba C++ entry point crashes during headless scripting.
  2. **Conda-Forge Library Precedence**: Use `conda install -c conda-forge libstdcxx-ng` or prioritize `${conda_root}/lib` in runtime environments when C++ extensions require modern symbols.

---

#### 2. NVIDIA Carbonite & Vulkan Loader Path Architecture:
* **Carbonite Framework (`libcarb.so`, `libomni.ext.so`)**:
  Isaac Sim's core engine relies on Carbonite plugins located in `_isaac_sim/kit`. Standard Python runs fail with `SIGSEGV` or unresolved symbols unless `CARB_APP_PATH` and `EXP_PATH` point to Isaac Sim's kit and app directories.
* **Vulkan GPU Surface Driver (`VK_ICD_FILENAMES`)**:
  Omniverse Kit renders via Vulkan hardware layers. Setting `VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"` inside scoped activation hooks (`activate.d/00_isaaclab_env.sh`) ensures simulation viewports link directly to the NVIDIA hardware driver rather than CPU software fallbacks (`llvmpipe`).

---

---

#### 4. Dual-Mode Isaac Sim Engine Architecture (Pip Package vs Standalone Symlink):

Physical AI practitioners require the flexibility to run Isaac Sim and Isaac Lab across two primary engine paradigms:

1. **Native Pip / Wheel Package Mode** (`pip install "isaacsim[all,extscache]==6.0.1" --extra-index-url https://pypi.nvidia.com`):
   * Isaac Sim modules are compiled as standalone wheels hosted directly inside the Conda environment’s `site-packages`.
   * Requires no directory symlinks (`_isaac_sim`), no shell bridges, and no `PYTHONPATH` exports.
2. **Standalone Binary / Symlink Mode** (`_isaac_sim -> ~/IsaacSim`):
   * Uses the pre-extracted Isaac Sim standalone distribution containing the full Omniverse Kit executable, PhysX, and extensions.
   * Essential for customized simulator builds, offline cloud VM deployments, and shared storage environments.

---

#### 5. The 3-Pillar Solution for Standalone Symlink Mode in Isaac Lab 3.0:

In Isaac Sim 6.0, NVIDIA removed `setup_conda_env.sh` and replaced it with `setup_python_env.sh`. When Isaac Lab 3.0 runs in standalone symlink mode, it requires the following three pillars to operate deterministically:

```mermaid
flowchart LR
    P1["Pillar 1:\nFiltering setup_conda_env.sh in _isaac_sim"]
    P2["Pillar 2:\nScoped activate.d hooks in Conda"]
    P3["Pillar 3:\nConda .pth site-packages registration"]

    P1 & P2 & P3 --> SUCCESS["✔ Symlink Mode works via ./isaaclab.sh AND direct 'python train.py'"]
```

* **Pillar 1: The Pure Filtering Bridge (`_isaac_sim/setup_conda_env.sh`)**:
  `setup_conda_env.sh` sources `setup_python_env.sh` to extract Omniverse extensions and Carbonite paths, but **filters out** `$SCRIPT_DIR/kit/python/lib/python3.12` from `PYTHONPATH` to prevent shadowing Conda's Python 3.12 standard library:
  ```bash
  #!/usr/bin/env bash
  SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
  MY_DIR="$(realpath -s "$SCRIPT_DIR")"

  export CARB_APP_PATH="${SCRIPT_DIR}/kit"
  export EXP_PATH="${MY_DIR}/apps"
  export ISAAC_PATH="${MY_DIR}"

  CURRENT_DIR="$(pwd)"
  cd "${SCRIPT_DIR}"
  . ./setup_python_env.sh
  cd "${CURRENT_DIR}"

  # Strip Kit Python standard libraries to preserve Conda Python 3.12 runtime purity
  export PYTHONPATH=$(echo "$PYTHONPATH" | tr ':' '\n' | grep -v "${SCRIPT_DIR}/kit/python/lib/python3.12" | grep -v "${SCRIPT_DIR}/kit/python/lib/python3.11" | tr '\n' ':' | sed 's/:$//')
  ```

* **Pillar 2: Scoped Conda Activation Hooks (`activate.d/00_isaaclab_env.sh`)**:
  When `conda activate isaaclab` is called, it automatically injects `CARB_APP_PATH`, `EXP_PATH`, `ISAAC_PATH`, `VK_ICD_FILENAMES`, and `LD_LIBRARY_PATH`, restoring them upon `conda deactivate`.

* **Pillar 3: Conda `.pth` Path Registration (`isaacsim_standalone.pth`)**:
  Registers Isaac Sim's standalone extensions directly into `<conda_env>/lib/python3.12/site-packages/isaacsim_standalone.pth`, enabling direct Python execution (`python scripts/reinforcement_learning/train.py`) without requiring the `isaaclab.sh` wrapper script:
  ```text
  /home/tarfy/IsaacSim/python_packages
  /home/tarfy/IsaacSim/exts/isaacsim.simulation_app
  /home/tarfy/IsaacSim/kit/kernel/py
  /home/tarfy/IsaacSim/kit/plugins/bindings-python
  /home/tarfy/IsaacSim/exts/omni.isaac.core_archive/pip_prebundle
  /home/tarfy/IsaacSim/exts/omni.pip.compute/pip_prebundle
  /home/tarfy/IsaacSim/exts/omni.pip.cloud/pip_prebundle
  ```

---

#### 7. Vulkan Hardware Surface Resolution & Dynamic Loader Discovery:

When rendering Omniverse Kit viewports in Isaac Lab 3.0 (via `--viz kit`), the Vulkan loader (`libvulkan.so`) queries the system for an Installable Client Driver (ICD) JSON manifest.

* **The Ubuntu / Debian Path Divergence**:
  On Ubuntu and Debian systems using standard NVIDIA proprietary drivers (550+ / 560+ / 570+), the driver manifest is located at `/usr/share/vulkan/icd.d/nvidia_icd.json`. Setting a static path to `/etc/vulkan/icd.d/nvidia_icd.json` forces the loader to look exclusively at a non-existent file, causing `vkCreateInstance failed with ERROR_INCOMPATIBLE_DRIVER`.
* **The Dynamic Runtime Discovery Pattern**:
  Activation hooks and runner shims must probe standard candidate paths dynamically at shell initialization:
  ```bash
  if [ -f /usr/share/vulkan/icd.d/nvidia_icd.json ]; then
      export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia_icd.json"
  elif [ -f /etc/vulkan/icd.d/nvidia_icd.json ]; then
      export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
  elif [ -f /usr/share/vulkan/icd.d/nvidia.json ]; then
      export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia.json"
  elif [ -f /etc/vulkan/icd.d/nvidia.json ]; then
      export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia.json"
  else
      unset VK_ICD_FILENAMES
  fi
  ```
  Unsetting `VK_ICD_FILENAMES` when no explicit match is found permits the Vulkan loader to execute its native fallback multi-directory search without crashing.

---

#### 8. Conda Base Plugin Registry & Rust C-Extension (`pydantic-core`) Resilience:

Modern Anaconda/Conda releases bundle commercial cloud and telemetry plugins into the `base` environment (e.g. `anaconda-cloud-auth`, `conda-anaconda-tos`, `anaconda-channel-guide`). Every time `conda` executes (`conda activate`, `conda deactivate`), its entry point scanner initializes these plugins.

* **The `_pydantic_core` Failure Mode**:
  These plugins rely on Pydantic v2, which requires a compiled Rust C-extension (`_pydantic_core.cpython-*.so`). If the base environment's Rust binary was compiled against a different Python version or corrupted during base updates, Conda outputs:
  ```text
  Error while loading conda entry point: anaconda-auth (No module named 'pydantic_core._pydantic_core')
  Error while loading conda entry point: conda-anaconda-tos (No module named 'pydantic_core._pydantic_core')
  ```
* **The Two Architectural Remedies**:
  1. **Rust Binary Reinstallation (`base` repair)**:
     Reinstalling native wheels for `pydantic` and `pydantic-core` restores the compiled Rust `.so` module in base:
     ```bash
     ~/miniconda3/bin/pip install --force-reinstall pydantic pydantic-core
     ```
  2. **Headless & CI/CD Plugin Suppression**:
     Exporting `CONDA_NO_PLUGINS=true` suppresses the external entry point scanner entirely. This provides faster CLI execution (~300ms reduction per command) and complete immunity against broken third-party plugins.

---

#### 9. Cross-Python Version Isolation & `PYTHONPATH` Sanitization Protocol:

When operating in heterogeneous Python environments (e.g. Miniconda Base running Python 3.14 and Isaac Lab running Python 3.12), environment variable leakage represents a primary failure mode:

* **The Cross-Version Binary Collision**:
  Omniverse Kit bundles CPython 3.12 wheels (`extscache/omni.kit.pip_archive...cp312/pip_prebundle`). If `PYTHONPATH` is exported globally into the interactive shell, any process using a different Python version (including the base Conda executable `/home/tarfy/miniconda3/bin/python`) will attempt to load the `cp312` compiled C-extensions (`_pydantic_core.so`, `_rust.so`). This causes immediate `ModuleNotFoundError` crashes during `conda deactivate` and `conda env list`.
* **The Two-Tier Isolation Protocol**:
  1. **Tier 1 (Targeted `.pth` Registration)**: Extension paths are declared exclusively inside `<conda_env>/lib/python3.12/site-packages/isaacsim_standalone.pth`, ensuring they are loaded strictly by the Python 3.12 interpreter and never leak into the parent shell environment.
  2. **Tier 2 (Mandatory Deactivation Sanitization)**: The deactivation hook (`deactivate.d/00_isaaclab_env.sh`) executes an unconditional `unset PYTHONPATH`, guaranteeing that the base shell returns to an uncontaminated state upon exit:
     ```bash
     #!/usr/bin/env bash
     if [[ -n "${_OLD_ISAAC_EXP_PATH}" ]]; then export EXP_PATH="${_OLD_ISAAC_EXP_PATH}"; else unset EXP_PATH; fi
     if [[ -n "${_OLD_ISAAC_PATH}" ]]; then export ISAAC_PATH="${_OLD_ISAAC_PATH}"; else unset ISAAC_PATH; fi
     if [[ -n "${_OLD_CARB_APP_PATH}" ]]; then export CARB_APP_PATH="${_OLD_CARB_APP_PATH}"; else unset CARB_APP_PATH; fi
     if [[ -n "${_OLD_VK_ICD_FILENAMES}" ]]; then export VK_ICD_FILENAMES="${_OLD_VK_ICD_FILENAMES}"; else unset VK_ICD_FILENAMES; fi
     unset _OLD_ISAAC_EXP_PATH _OLD_ISAAC_PATH _OLD_CARB_APP_PATH _OLD_VK_ICD_FILENAMES
     unset PYTHONPATH
     ```

---

#### 10. Production Automated Integration Plan in `isaac-installer`:

To eliminate manual workarounds and make the installer 100% resilient across both modes:

1. **Automated Dual-Mode Engine Provisioning**:
   - `lib/modules/isaacsim.sh` will dynamically provision both Pillar 1 (`setup_conda_env.sh`) and Pillar 3 (`isaacsim_standalone.pth`) during the `isaacsim` and `conda` stages.
2. **Automated Self-Healing Drift Detection (`lib/core/state.sh`)**:
   - **`SIM_BRIDGE_MISSING`**: Emitted if `~/IsaacSim` exists but `setup_conda_env.sh` is missing. Healed by auto-generating the filtering bridge script.
   - **`SIM_PTH_MISSING`**: Emitted if `~/IsaacSim` exists but `isaacsim_standalone.pth` is missing from Conda site-packages. Healed by auto-generating the `.pth` file.
   - **`BROKEN_SYMLINK`**: Reconnects `_isaac_sim` to `~/IsaacSim` and automatically ensures both bridge and `.pth` files are synchronized.
3. **Execution Mode Agnostic**:
   - Works flawlessly whether invoked via `./isaaclab.sh train ...`, `python -m isaaclab.train`, or `isaaclab-env python ...`.

---

### 3.8 Verification & Audit Plan for Hybrid Model

Before writing the implementation code for this subsystem, the following verification gates are established:

1. **Discovery Gate**: Check if Conda (`~/miniconda3/bin/conda` or `~/.local/share/mamba/bin/mamba`) and UV (`~/.cargo/bin/uv` or `/usr/local/bin/uv`) are installed.
2. **Environment Creation Gate**: Verify `conda env list` contains `isaaclab` with matching Python version (`3.10` for Sim 5.1, `3.12` for Sim 6.0).
3. **PyTorch Tensor Gate**: Run `uv pip` to verify `torch.cuda.is_available()` returns `True` and recognizes active GPU (RTX 4090 / Blackwell).
4. **Shell Isolation Gate**: Open a clean non-Conda subshell and assert that `PYTHONPATH` and `LD_LIBRARY_PATH` contain zero references to Omniverse Kit directories.
5. **Activation Hook Gate**: Assert that `conda activate isaaclab` exports `EXP_PATH` and `CARB_APP_PATH`, and `conda deactivate` restores the previous environment.

---

## 4. Workspace Organization & GitHub Desktop Hierarchy

In professional robotics setups, developers maintain repositories under user or organization folders matching their GitHub account (e.g. `~/Documents/GitHub/BoredEngineer/IsaacAutomator`). Naive flat cloning (`~/Documents/GitHub/IsaacLab`) creates folder fragmentation and breaks GitHub Desktop repository tracking.

```mermaid
flowchart TD
    subgraph LAYOUT ["Clean Organization Hierarchy (~/Documents/GitHub/<Owner>/<Repo>)"]
        ROOT["~/Documents/GitHub/"]
        OWNER["BoredEngineer/ (User / Org Namespace)"]
        R1["IsaacAutomator/"]
        R2["IsaacLab/"]
        R3["IsaacLab-Arena/"]
        R4["lerobot/"]
    end

    ROOT --> OWNER
    OWNER --> R1
    OWNER --> R2
    OWNER --> R3
    OWNER --> R4
```

### Declarative YAML Configuration (`config/*.yaml`):
```yaml
workspace:
  root: "~/Documents/GitHub"
  # Layout Strategy:
  #   - "auto": Auto-detects if owner directory exists (e.g. ~/Documents/GitHub/BoredEngineer)
  #   - "org":  Always nest under owner folder (~/Documents/GitHub/<Owner>/<Repo>)
  #   - "flat": Always place directly under root (~/Documents/GitHub/<Repo>)
  layout: "auto"
  default_owner: "BoredEngineer"      # Fallback if unauthenticated
  auto_register_github_desktop: true
  auto_create_fork: true             # Automatically checks/creates fork via gh CLI

repositories:
  isaaclab:
    enabled: true
    repo: "BoredEngineer/IsaacLab"    # Personal fork (origin)
    upstream: "https://github.com/isaac-sim/IsaacLab.git" # Canonical (upstream)
    branch: "main"
    tag: ""                          # e.g. "v3.0.0-beta2" (empty = use branch)

  arena:
    enabled: true
    repo: "BoredEngineer/IsaacLab-Arena"
    upstream: "https://github.com/isaac-sim/IsaacLab-Arena.git"
    branch: "release/0.3.0-prerelease" # Arena 0.3.0 Pre-release (Newton physics & OpenPI)
    tag: ""

  lerobot:
    enabled: true
    repo: "BoredEngineer/lerobot"
    upstream: "https://github.com/huggingface/lerobot.git"
    branch: "main"
    tag: "v0.4.3"                    # Pinned stable release
    isolated_env: true               # Dedicated 'lerobot' conda env to prevent GR00T/numpy conflicts

simulation:
  isaacsim:
    enabled: true
    version: "6.0.1"                 # "6.0.1" | "5.1.0" | "custom"
    install_dir: "~/IsaacSim"        # Standard standalone directory or custom build root
    source_type: "standalone"        # "standalone" | "custom_build" | "omniverse_launcher"
    custom_build:
      enabled: false
      source_path: "~/IsaacSim-Source"
      build_command: "./build.sh -r"
    accept_eula: true
```

---

## 5. Dual-Remote Fork Topology & GitHub Remote Checking

```mermaid
flowchart TD
    DEV["Robotics Engineer"]

    subgraph PROBE ["0. Remote Fork Validation & Auto-Creation"]
        CHECK["Check if fork exists on GitHub\n(gh api repos/<owner>/<repo>)"]
        CREATE["If missing: Auto-create fork\n(gh repo fork <upstream> --clone=false)"]
        FALLBACK["If unauthenticated: Fallback to upstream clone"]
    end

    subgraph REMOTES ["Dual-Remote Git Configuration (.git/config)"]
        ORIGIN["origin (Push / Personal Fork)\ngit@github.com:BoredEngineer/IsaacLab.git"]
        UPSTREAM["upstream (Pull / Sync / Official Releases)\nhttps://github.com/isaac-sim/IsaacLab.git"]
    end

    subgraph WORKFLOW ["Day-to-Day Development Loop"]
        SYNC_CHECK["Check Sync Delta\n(ahead / behind commits)"]
        SYNC["Sync / Rebase\ngit fetch upstream\ngit rebase upstream/main"]
        BRANCH["New Feature Branch\n(e.g., feature/g1-locomotion)"]
        PUSH["Push to Personal Fork\ngit push -u origin feature/g1-locomotion"]
        PR["Open Upstream PR\nvia GitHub Desktop / gh pr create"]
    end

    DEV --> CHECK --> CREATE --> ORIGIN
    CHECK --> FALLBACK --> ORIGIN
    UPSTREAM -- "git fetch --tags upstream" --> SYNC_CHECK --> SYNC
    SYNC --> BRANCH
    BRANCH -- "git push" --> ORIGIN
    ORIGIN --> PR
```

### Core Capabilities:
1. **Automated Remote Fork Discovery & Creation**:
   - `isaac-installer` checks if the fork exists on GitHub using `gh api repos/<owner>/<repo>` or `git ls-remote`.
   - If missing and `gh` is authenticated, it calls `gh repo fork <upstream> --clone=false --default-branch-only` to instantiate the fork under your account instantly.
   - If unauthenticated, it clones upstream directly with a clear warning so development is never blocked.
2. **Upstream Push Guard**: `git config remote.upstream.pushurl "PUSH_DISABLED_CANONICAL_UPSTREAM"` to eliminate accidental pushes to official repositories.
3. **Fork Sync Delta Telemetry (`lab status` & `lab sync`)**:
   - Compares local branches against upstream (`upstream/main`), reporting exact `ahead`/`behind` commit deltas.
   - One-click `isaac-installer lab sync [--rebase]` to keep personal forks aligned with upstream release tags.
4. **GitHub Desktop UI Integration**: Executing `github-desktop --add <path>` enables native "Fetch upstream", "Sync with upstream", and visual PR creation.

---

### Dual-Remote Day-to-Day Developer Workflows:

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

---

## 5.1 Custom Source-Built Isaac Sim & Multi-Version Coexistence (6.0.1 & 5.1.0)

For advanced physical AI teams compiling Isaac Sim from source (or maintaining custom USD/PhysX builds), or teams needing both 6.0.1 and 5.1.0 on the same machine:

```mermaid
flowchart TD
    subgraph ENGINES ["Sim Engines on Host Disk"]
        SIM6["Isaac Sim 6.0.1 (~/IsaacSim-6.0.1)\n• Python 3.12\n• Isaac Lab 3.0 / Arena 0.3.0"]
        SIM5["Isaac Sim 5.1.0 (~/IsaacSim-5.1.0)\n• Python 3.10\n• Isaac Lab 2.3.2 / Arena 0.1.1"]
        CUSTOM["Custom Source Build (~/IsaacSim-Custom)\n• Custom Kit SDK / USD"]
    end

    subgraph SWITCHER ["Atomic Symlink Switcher (isaac-installer sim switch)"]
        LINK["_isaac_sim symlink\n(POSIX atomic staging via tmp.$$ rename)"]
    end

    subgraph ENVS ["Matched Python Conda Environments"]
        ENV6["conda activate isaaclab (Python 3.12)"]
        ENV5["conda activate isaaclab-5.1 (Python 3.10)"]
    end

    SIM6 --> LINK
    SIM5 --> LINK
    CUSTOM --> LINK
    LINK --> ENVS
```

* **Custom Build Compilation**: If `source_type: "custom_build"`, the installer validates `kit/kit` or `isaac-sim.sh` binaries, and optionally runs `custom_build.build_command` under unprivileged user permissions.
* **Instant Switching**: Run `./bin/isaac-installer sim switch 6.0.1` or `./bin/isaac-installer sim switch 5.1.0` to switch the active engine in < 100ms without re-installing or corrupting packages.

---

## 5.2 IsaacLab-Arena Composable Task & Multi-Embodiment Benchmark Architecture

**IsaacLab-Arena** (`isaac-sim/IsaacLab-Arena`) is an open-source extension to NVIDIA Isaac Lab for simplified task curation and generalist robot policy evaluation at scale. Instead of monolithic environment classes where robots, objects, and tasks are hardcoded, Arena provides a **Composable Triplet Architecture**:

```mermaid
flowchart TD
    subgraph COMPOSABLES ["Composable Primitives"]
        EMBODIMENT["1. Embodiments\n(Unitree G1, Fourier GR1, Franka Panda, ANYmal-D, Spot)"]
        SCENE["2. Semantic Scene Graph\n(Kitchen, Tabletop, Warehouse, Rough Terrain)"]
        TASK["3. Task Grammar\n(Sequential Skills: Walk -> Pick -> Walk -> Place -> Close)"]
    end

    subgraph BUILDER ["Arena Dynamic Builder (ArenaEnvBuilder)"]
        CFG["ArenaEnvBuilderCfg (CLI & Python API)"]
        ENV["ManagerBasedRLEnv / DirectRLEnv Assembly"]
        COMPOSABLES --> CFG --> ENV
    end

    subgraph WORKFLOWS ["Evaluation & Training Pipelines"]
        RUNNER["isaaclab_arena/evaluation/policy_runner.py"]
        RL_PIPES["Parallel PhysX GPU Rollouts (4,096 Actors)"]
        GR00T_PIPES["GR00T VLA Zero-Shot & Finetuned Inference"]
        ENV --> RUNNER --> RL_PIPES & GR00T_PIPES
    end
```

### Key Capabilities & Workflows:
1. **LEGO-like On-the-Fly Composition**: Mix and match robot bodies, scene assets, and reward grammars at runtime without maintaining thousands of duplicate YAML/Python configs.
2. **Sequential Task Chaining**: Chain atomic skills (e.g. `Pick` + `Walk` + `Place` + `Close Door`) for long-horizon evaluation.
3. **Core Validation Workflows**:
   - **Zero-Action Tensor Rollout**:
     ```bash
     python isaaclab_arena/evaluation/policy_runner.py \
       --policy_type zero_action \
       --num_steps 50 \
       --num_envs 16 \
       cube_goal_pose
     ```
   - **Live Omniverse Kit GUI Rollout**:
     ```bash
     python isaaclab_arena/evaluation/policy_runner.py \
       --viz kit \
       --policy_type zero_action \
       --num_steps 200 \
       cube_goal_pose
     ```
   - **Target Embodiments**:
     - **Unitree G1 Humanoid Loco-Manipulation** (`isaaclab_arena_g1`)
     - **Fourier GR1 Microwave Door Opening** (`isaaclab_arena_environments`)
     - **Franka Emika Panda Object Lift** (`isaaclab_arena_examples`)

---

## 5.3 NVIDIA Isaac-GR00T Foundation Model Stack (N1.7 General Availability)

**NVIDIA Isaac-GR00T** (`NVIDIA/Isaac-GR00T`) is an open Vision-Language-Action (VLA) foundation model designed for generalist humanoid robot skills and cross-embodiment manipulation.

```mermaid
flowchart TD
    subgraph INPUTS ["Multimodal Inputs"]
        LANG["Task Language Instruction\n('Pick up the red mug and place it in the tray')"]
        VIDEO["Multi-Camera Video Streams (RGB)\n(Decoded via torchcodec + FFmpeg)"]
        STATE["Proprioceptive Robot State (Joints / Relative EEF)"]
    end

    subgraph BACKBONE ["GR00T N1.7 Neural Architecture"]
        VLM["Cosmos-Reason2-2B (Qwen3-VL Multimodal Backbone)\nPre-trained on 20K hrs EgoScale Human Videos"]
        DIT["Diffusion Transformer Action Head (DiT)\nFlow-Matching Action Denoising (40-step horizon)"]
        INPUTS --> VLM --> DIT
    end

    subgraph OUTPUTS ["Cross-Embodiment Actuation"]
        EEF["Relative End-Effector Trajectories"]
        SONIC["GEAR-SONIC Whole-Body Controller (UNITREE_G1_SONIC)\nDecodes Latent Tokens -> Full-Body Joint Commands"]
        DIT --> EEF & SONIC
    end
```

### Technical Specifications & Architecture:
* **Model Checkpoint**: `nvidia/GR00T-N1.7-3B` (Hugging Face gated checkpoint).
* **VLM Backbone**: `nvidia/Cosmos-Reason2-2B` (Qwen3-VL native aspect ratio, flexible token resolution).
* **Action Space**: Relative End-Effector (EEF) action space shared across human video priors and robot embodiments.
* **Humanoid Whole-Body Control (SONIC)**: Uses the `UNITREE_G1_SONIC` embodiment tag with the GEAR-SONIC whole-body controller to produce synchronized bimanual manipulation and footstep placement.

### Operational Deployment Modes:
1. **Server-Client Architecture (ZeroMQ Transport)**:
   - *GPU Policy Server (Port 5555)*:
     ```bash
     uv run python gr00t/eval/run_gr00t_server.py \
       --model-path nvidia/GR00T-N1.7-3B \
       --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
       --device cuda:0
     ```
   - *Client Open-Loop Evaluation*:
     ```bash
     uv run python gr00t/eval/open_loop_eval.py \
       --dataset-path demo_data/droid_sample \
       --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
       --host 127.0.0.1 \
       --port 5555 \
       --traj-ids 1 2 \
       --execution-horizon 8
     ```
2. **Fine-Tuning Engine (`launch_finetune.py`)**:
   - Supports multi-dataset mixtures with alpha weighting (`--ds_weights_alpha`), state dropout (`--state_dropout_prob`), and Weights & Biases telemetry.
   - Dataset Schema: LeRobot v2 format + `meta/modality.json` for state/action splitting.
3. **Video Backend**: Accelerated H.264 video decoding via `torchcodec==0.8.0` with FFmpeg 4–7 compatibility layer.

---

### Step-by-Step Isaac-GR00T Installation & Verification Plan:

```mermaid
flowchart TD
    subgraph STAGE1 ["1. Host Prerequisites & System Libraries"]
        P1["git-lfs (git lfs install for parquet files)"]
        P2["FFmpeg 4-7 runtime (required by torchcodec)"]
        P3["Astral uv Package Manager (curl -LsSf https://astral.sh/uv/install.sh | sh)"]
        P4["Hugging Face Token Auth (huggingface-cli login / gated Cosmos-Reason2-2B access)"]
        P1 & P2 & P3 & P4 --> CLONE
    end

    subgraph STAGE2 ["2. Repository Provisioning & Dual-Remote Topology"]
        CLONE["git clone --recurse-submodules https://github.com/NVIDIA/Isaac-GR00T.git\n~/Documents/GitHub/boredengineering/Isaac-GR00T"]
        R1["origin: https://github.com/boredengineering/Isaac-GR00T.git (Push Allowed)"]
        R2["upstream: https://github.com/NVIDIA/Isaac-GR00T.git (Push Locked)"]
        GHD["github-desktop --add <repo_path>"]
        CLONE --> R1 & R2 --> GHD --> SYNC
    end

    subgraph STAGE3 ["3. Python 3.12 Virtual Environment & Lockfile Sync"]
        SYNC["uv sync --python 3.12\n(Installs PyTorch 2.7, flash-attn, torchcodec, Transformers 4.57.3)"]
        CUDA_FIX["export CUDA_HOME=/usr/local/cuda"]
        SYNC --> CUDA_FIX --> TEST1
    end

    subgraph STAGE4 ["4. 4-Stage Verification & Benchmark Suite"]
        TEST1["Gate 1: uv run python -c 'import gr00t; print(SUCCESS)'"]
        TEST2["Gate 2: Hugging Face Gated Model Access Validation"]
        TEST3["Gate 3: Standalone Open-Loop Inference on DROID Sample (demo_data/droid_sample)"]
        TEST4["Gate 4: ZeroMQ Policy Server Round-Trip Latency Benchmark"]
        TEST1 --> TEST2 --> TEST3 --> TEST4
    end
```

#### Detailed Installation Commands:

```bash
# 1. System Dependencies & Git LFS
sudo apt-get update && sudo apt-get install -y git-lfs ffmpeg
git lfs install

# 2. Clone Isaac-GR00T with Submodules & Wire Dual-Remote Topology
git clone --recurse-submodules https://github.com/NVIDIA/Isaac-GR00T.git ~/Documents/GitHub/boredengineering/Isaac-GR00T
cd ~/Documents/GitHub/boredengineering/Isaac-GR00T

git remote rename origin upstream
git remote add origin https://github.com/boredengineering/Isaac-GR00T.git
git config remote.upstream.pushurl PUSH_DISABLED_CANONICAL_UPSTREAM
github-desktop --add ~/Documents/GitHub/boredengineering/Isaac-GR00T

# 3. Provision Isolated Python 3.12 Environment with uv
uv sync --python 3.12

# 4. Hugging Face Access & Token Login (Gated Cosmos-Reason2-2B VLM)
uv run huggingface-cli login

# 5. Execute 4-Stage Verification Suite
# Gate 1: Core Import
uv run python -c "import gr00t; print('✔ GR00T Core Module Imported Successfully')"

# Gate 2 & 3: Standalone Zero-Shot Inference on DROID Sample
uv run python scripts/deployment/standalone_inference_script.py \
  --model-path nvidia/GR00T-N1.7-3B \
  --dataset-path demo_data/droid_sample \
  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
  --traj-ids 1 2 \
  --inference-mode pytorch \
  --execution-horizon 8

# Gate 4: Server-Client ZeroMQ Serving Test (Optional)
uv run python gr00t/eval/run_gr00t_server.py \
  --model-path nvidia/GR00T-N1.7-3B \
  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
  --device cuda:0 &
SERVER_PID=$!
sleep 5
uv run python gr00t/eval/open_loop_eval.py \
  --dataset-path demo_data/droid_sample \
  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
  --host 127.0.0.1 \
  --port 5555 \
  --traj-ids 1 \
  --execution-horizon 8
kill $SERVER_PID
```

---

### 5.3.1 Closed-Loop Simulation Bridge (IsaacLab-Arena ⟷ Isaac-GR00T ZeroMQ Policy Bridge)

In physical robotics research, evaluating foundation models requires closed-loop interaction between the simulation environment and the policy server:

```mermaid
flowchart LR
    subgraph SIMULATION ["IsaacLab-Arena Runtime (Isaac Sim / PhysX)"]
        RENDER["Camera Sensors (RGB Video) + Proprioception (Joints)"]
        STEP["PhysX 5.4 GPU Dynamics Step"]
        RENDER --> ZMQ_CLIENT["Arena Policy Client (ZeroMQ REQ)"]
        ZMQ_CLIENT --> STEP
    end

    subgraph SERVER ["Isaac-GR00T Policy Server (Python 3.12 / uv)"]
        ZMQ_SERVER["Policy Daemon (ZeroMQ REP: Port 5555)"]
        VLM["Cosmos-Reason2-2B VLM Backbone"]
        DIT["DiT Action Chunk Denoising (40-step horizon)"]
        ZMQ_SERVER --> VLM --> DIT --> ZMQ_SERVER
    end

    ZMQ_CLIENT <== "Observations (Tensors)" ==> ZMQ_SERVER
    ZMQ_SERVER <== "Action Trajectory (Relative EEF / Joints)" ==> ZMQ_CLIENT
```

#### Execution Workflows:
1. **Interactive Live Viewport Closed-Loop Demo**:
   ```bash
   ./bin/isaac-installer arena play cube_goal_pose --policy gr00t --port 5555
   ```
2. **Headless Parallel Benchmark Rollout**:
   ```bash
   ./bin/isaac-installer arena eval-gr00t cube_goal_pose 5555
   ```

---

### 5.3.2 Foundation Model Weight Pre-Caching & Gated Access Protocol

NVIDIA foundation models (`nvidia/GR00T-N1.7-3B` and `nvidia/Cosmos-Reason2-2B`) require authenticated access via Hugging Face. The installer provides automated pre-caching and mock fallback mechanisms:

1. **Pre-Caching Gated Weights**:
   ```bash
   ./bin/isaac-installer gr00t download-weights [--local-dir /data/models/pretrained_checkpoints/gr00t-n1.7-3b]
   ```
2. **Offline / CI Mock Fixture Mode**:
   ```bash
   ./bin/isaac-installer gr00t download-weights --mock
   ```

---

## 5.4 Decoupled Standalone Workspace with Atomic Submodule Bridging & Pinned Commit Management

### The Architecture Problem: Nested Submodules vs Standalone Development

Upstream `isaac-sim/IsaacLab-Arena` relies on Git submodules (`submodules/IsaacLab` and `submodules/Isaac-GR00T`) pinned to exact upstream commit SHAs.

However, robotics developers need to build, modify, test, and commit to **`Isaac-GR00T`** (e.g. creating custom VLA heads, modifying modality configs, fine-tuning new embodiments) and **`IsaacLab`** (custom robot actuators, sensor plugins) **as first-class standalone repositories** with full branches and push access, outside the awkward detached-HEAD confines of nested submodules.

```mermaid
flowchart TD
    subgraph STANDALONE ["Standalone Developer Workspaces (~/Documents/GitHub/boredengineering/)"]
        LAB["IsaacLab (Standalone Git Repo & Fork)\n• Develop custom actuators & sensors\n• Branch: feature/my-actuator\n• Origin: boredengineering/IsaacLab"]
        GR00T["Isaac-GR00T (Standalone Git Repo & Fork)\n• Develop custom VLA heads & finetune\n• Branch: feature/g1-custom-head\n• Origin: boredengineering/Isaac-GR00T"]
        ARENA["IsaacLab-Arena (Standalone Git Repo & Fork)\n• Compose tasks, benchmark suites, policy runner\n• Branch: main / release/0.3.0"]
    end

    subgraph BRIDGING ["Submodule Linking & Alignment Engine (isaac-installer arena submodules)"]
        MODE_DEV["Development Mode (Symlink / Editable Bridge):\nArena links submodules/Isaac-GR00T -> Standalone Isaac-GR00T\nArena links submodules/IsaacLab -> Standalone IsaacLab\n✅ Live edits propagate instantaneously!"]
        MODE_PIN["Reproducibility Mode (Pinned Snapshot):\nArena uses internal git submodules at exact upstream commit SHAs\n✅ 100% deterministic benchmark replication!"]
        AUDIT["Submodule Drift Telemetry:\nReports commit delta between Standalone HEAD vs Pinned Submodule SHA"]
    end

    subgraph RUNTIMES ["Unified Python Execution Environments"]
        ENV_LAB["conda activate isaaclab (Isaac Lab 3.0 / Arena Runtime)"]
        ENV_GR00T["uv / conda run (Isaac-GR00T Python 3.12 Runtime)"]
        ZMQ["ZeroMQ Socket Bridge (127.0.0.1:5555)"]
        ENV_GR00T <-->|Action Tokens & Observations| ZMQ <-->|Policy Inference| ENV_LAB
    end

    STANDALONE --> BRIDGING --> RUNTIMES
```

### Submodule & Standalone Bridging Operations:

```bash
cd /workspaces/IsaacAutomator/.agents/references/isaac-installer

# 1. Audit Submodule vs Standalone Alignment:
./bin/isaac-installer arena submodules status

# 2. Strategy A [RECOMMENDED]: Non-Invasive Python Editable Bridge (Zero Symlinks, Zero Git Dirt):
# Registers standalone IsaacLab, Isaac-GR00T, and IsaacLab-Arena into Python site-packages.
# Git submodules remain 100% clean and untouched!
./bin/isaac-installer arena submodules editable-bridge

# 3. Strategy B: In-Place Directory Symlinks (For legacy path-relative code):
./bin/isaac-installer arena submodules link-standalone

# 4. Reversible Reset: Unlink Symlinks & Restore Exact Upstream Pinned Commits:
./bin/isaac-installer arena submodules unlink

# 5. Update the Submodule Pin in Arena to Match Current Standalone HEAD:
./bin/isaac-installer arena submodules update-pin Isaac-GR00T
```

### Architectural Critique: Symlinks vs Python Editable Bridge Mode

| Dimension | **Strategy A: Python Editable Bridge (`editable-bridge`)** | **Strategy B: In-Place Directory Symlinks (`link-standalone`)** |
| :--- | :--- | :--- |
| **Git Repository Cleanliness** | **100% Clean**: `git status` in Arena is never polluted. | **Dirty**: Shows `typechange: submodules/IsaacLab` in git status. |
| **Live Development** | **Instant**: Changes in standalone `Isaac-GR00T` reflect live. | **Instant**: Changes reflect live via filesystem pointer. |
| **Accidental Commit Risk** | **0% Risk**: Submodules are not modified. | **Risk**: Accidental `git commit -a` could stage symlink. |
| **Reversibility** | **Instant**: Standard `pip install` state. | **Instant**: Reversible with `./bin/isaac-installer arena submodules unlink`. |
| **Recommendation** | **PRIMARY DEFAULT**: Cleanest, industry-standard approach. | **OPT-IN**: Used only if code requires hardcoded relative paths. |

---

## 6. State Tracking, Drift Detection & Self-Healing Engine

When workstations evolve over time, repositories get misplaced (e.g. flat `GitHub/IsaacLab` vs `GitHub/BoredEngineer/IsaacLab`), remotes point to wrong URLs, branches drift, or symlinks break.

`isaac-installer` introduces an **Automated Drift Detection & Self-Healing Engine**:

```mermaid
flowchart TD
    subgraph DESIRED ["1. Desired State (Declarative YAML)"]
        Y1["Profile: layout='org', default_owner='BoredEngineer'"]
        Y2["IsaacLab: tag='v2.3.0', origin='BoredEngineer/IsaacLab'"]
    end

    subgraph PROBER ["2. Host State Prober & Drift Auditor"]
        P1["Discovers all repos across ~/Documents/GitHub/**, ~/workspace/**"]
        P2["Inspects origin/upstream URLs, active ref/tag, dirty state"]
        P3["Validates symlinks (_isaac_sim) and pip -e packages"]
        P4["Computes Drift Delta Matrix (Plan / Doctor)"]
    end

    subgraph HEALER ["3. Self-Healing & Reconciliation Engine (repair / fix)"]
        H1["Safe Re-Homing: Move GitHub/IsaacLab -> GitHub/BoredEngineer/IsaacLab"]
        H2["Remote Wiring: Set origin=fork, upstream=canonical"]
        H3["Ref Alignment: Fetch & checkout target tag/branch"]
        H4["Symlink Healing: Atomically re-link _isaac_sim -> active Isaac Sim"]
        H5["Python Re-Index: Update uv pip -e editable package pointers"]
        H6["GHD Sync: Re-register resolved paths in GitHub Desktop"]
    end

    DESIRED --> PROBER --> HEALER
```

### Drift Classification Matrix:

| Drift Category | Detected Scenario | Automated Self-Healing Action |
| :--- | :--- | :--- |
| **Mislocated Directory** | `IsaacLab` is in flat `GitHub/` or `~/workspace/`, but YAML specifies `org` layout. | Safely moves directory to `~/Documents/GitHub/BoredEngineer/IsaacLab`, checks dirty state, and updates all symlinks. |
| **Origin Remote Mismatch** | `origin` is set to `isaac-sim/IsaacLab` instead of `BoredEngineer/IsaacLab`. | Updates `origin` to personal fork and configures `upstream` to canonical NVIDIA repo. |
| **Branch / Tag Drift** | Local repo is on `main`, but YAML requests `tag: v2.3.0`. | Fetches upstream tags, stashes any uncommitted work, and checks out `release/v2.3.0`. |
| **Broken Engine Symlink** | `_isaac_sim` symlink is broken or points to a non-existent Isaac Sim path. | Atomically recreates `_isaac_sim` pointing to active `${ISAACSIM_DIR}`. |
| **Stale Python Editable Link** | Pip editable metadata points to old directory path before re-homing. | Re-runs `uv pip install -e <new_path>` inside the conda/venv environment. |
| **Dirty Work Protection** | Local repo contains uncommitted edits or untracked research files. | Never deletes or overwrites; creates safety git branch/stash backup before migration. |

### Persistent State Ledger (`~/.isaac-installer/state.json`):
```json
{
  "version": "1.0",
  "last_reconciled": "2026-08-20T21:30:00Z",
  "workspace_layout": "org",
  "default_owner": "BoredEngineer",
  "repositories": {
    "isaaclab": {
      "path": "/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab",
      "repo_slug": "BoredEngineer/IsaacLab",
      "upstream_slug": "isaac-sim/IsaacLab",
      "active_ref": "v2.3.0",
      "ref_type": "tag",
      "linked_sim": "/home/tarfy/IsaacSim",
      "git_status": "clean"
    },
    "arena": {
      "path": "/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena",
      "repo_slug": "BoredEngineer/IsaacLab-Arena",
      "upstream_slug": "isaac-sim/IsaacLab-Arena",
      "active_ref": "release/0.1.1",
      "ref_type": "branch",
      "linked_sim": "/home/tarfy/IsaacSim",
      "git_status": "clean"
    }
  },
  "simulation": {
    "active_version": "5.1.0",
    "path": "/home/tarfy/IsaacSim"
  },
  "python_env": {
    "type": "conda",
    "name": "isaaclab",
    "path": "/opt/conda/envs/isaaclab",
    "torch_cuda": "2.5.1+cu124"
  }
}
```

---

## 7. Teleoperation, Real-Time Serial & Peripherals Subsystem

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

## 8. High-Throughput NVMe Storage, Datasets & USD Asset Cache

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

## 9. Concrete Project Structure

```text
isaac-installer/
├── bin/
│   ├── isaac-installer            # CLI dispatcher (doctor, plan, install, sim, lab, auth, test, repair)
│   └── isaaclab-env               # Dynamic runtime environment shim
├── config/
│   ├── default-profile.yaml       # Standard interactive robotics workstation preset
│   ├── minimal-headless.yaml      # Headless RL training / CI cluster node preset
│   └── full-ecosystem.yaml        # Full stack (+ LeRobot, Arena, SpaceMouse, Manus VR)
├── lib/
│   ├── core/
│   │   ├── logging.sh             # Unicode UI cards, color palette, failure log tailing
│   │   ├── detect.sh              # Blackwell/Ada GPU, NVMe SSDs, LVM, Wayland/X11
│   │   ├── config.sh              # Declarative YAML profile parser & layout mapper
│   │   ├── audit.sh               # 20-component pre-flight audit diff matrix
│   │   ├── state.sh               # JSON state machine, ledger & drift tracker
│   │   ├── network.sh             # CDN latency pre-flight benchmark
│   │   ├── backup.sh              # Safety configuration snapshots & rollback
│   │   ├── git_workspace.sh       # Hierarchy resolver, dual-remote fork engine, GHD registration
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
│   │   ├── isaaclab.sh            # Topological extension installer, tag/branch switcher, PyTorch check
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

## 10. Authentication & Permissions Matrix

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

## 11. 15-Subsystem End-to-End Verification Suite (`test`)

The verification suite runs granular, non-destructive health checks across 15 core subsystems:

1. **NVIDIA Driver & GPU Topology**: Driver version ($\ge 535$ or $\ge 570$), PCIe Link speed (Gen4/Gen5 x16), persistence mode.
2. **Display Server**: X11 server active or virtual EDID configured (`DISPLAY=:0`), Wayland disabled for Omniverse compatibility.
3. **Build Prerequisites**: GCC 11, G++ 11, CMake $\ge 3.22$, Ninja, Git LFS.
4. **Vulkan Runtime**: `vulkaninfo` device enumeration, ICD configuration (`/usr/share/vulkan/icd.d/nvidia_icd.json`).
5. **Docker & GPU Passthrough**: Docker daemon status, `nvidia-ctk` runtime test (`nvidia-smi` inside container).
6. **Developer Tools**: VS Code, GitHub Desktop, Google Chrome / Chromium, `gh`, `aws`, `gcloud`, `hf`.
7. **Storage & I/O Stack**: NVMe SMART health telemetry, LVM2 volume groups, mount permissions on `/data`.
8. **Python Runtime & UV**: Python 3.10 / 3.12 runtime, `uv` package manager binary and cache health.
9. **Physical AI & LeRobot**: Hugging Face token validity, `lerobot` import, Rerun.io visualizer binary.
10. **Hardware Teleop**: 1ms FTDI latency timer verification, user membership in `dialout`, `plugdev`, `input`.
11. **Isaac Sim Standalone Engine**: Executable verification, `.eula_accepted` presence, Kit Carbonite core load.
12. **Isaac Lab PyTorch CUDA Linkage**: GPU tensor allocation, CUDA device name match, extension import sanity.
13. **IsaacLab-Arena Benchmark Suite**: Gymnasium multi-agent environment registration, composable task runner, headless tensor rollouts.
14. **NVIDIA Isaac-GR00T Foundation Model Stack**: Python 3.12 `uv` environment, core module imports, DROID modality mapping, ZeroMQ socket readiness.
15. **Desktop Shortcuts & Demos**: Desktop `.desktop` launchers for Unitree G1, Go2, Franka, Arena Benchmark Kit GUI, GR00T Policy Server, and Arena + GR00T Closed-Loop Demo.

---

## 12. Critical Architectural Review & Open Questions

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

## 13. Implementation Roadmap

- [x] **Core CLI & Unicode UI Engine** (`bin/isaac-installer`, `lib/core/logging.sh`)
- [x] **Deep Hardware, NVMe & Multi-GPU Discovery** (`lib/core/detect.sh`)
- [x] **20-Component Pre-Flight Audit Matrix** (`lib/core/audit.sh`)
- [x] **Network CDN Latency Pre-Flight Benchmarking** (`lib/core/network.sh`)
- [x] **Configuration Safety Snapshots & Rollback** (`lib/core/backup.sh`)
- [x] **Unified Authentication & Cloud Hub Manager** (`lib/modules/auth.sh`)
- [x] **High-Speed Storage Stack (`nvme-cli`, `lvm2`, `fio`)** (`lib/modules/dev_tools.sh`)
- [x] **Hugging Face LeRobot & `lerobot-dataset-viz`** (`lib/modules/physical_ai.sh`)
- [x] **Hardware Teleop Peripherals & 1ms Low-Latency Serial** (`lib/modules/hardware_teleop.sh`)
- [x] **Multi-Version Isaac Sim Detection & Atomic Symlink Switcher** (`lib/modules/isaacsim.sh`)
- [x] **15-Subsystem End-to-End Verification Suite** (`cmd_test`)
- [x] **Workspace Hierarchy Engine (`~/Documents/GitHub/<Owner>/<Repo>`)** (`lib/core/git_workspace.sh`)
- [x] **Dual-Remote Fork & Tag/Branch Management (`lab switch`, `lab sync`)** (`lib/modules/isaaclab.sh`)
- [x] **IsaacLab-Arena Composable Task & Benchmark Suite (`arena status`, `arena test`, `arena play --policy gr00t`)** (`lib/modules/isaaclab_arena.sh`)
- [x] **NVIDIA Isaac-GR00T Foundation Model Stack & ZeroMQ Serving (`gr00t server`, `gr00t download-weights`)** (`lib/modules/gr00t.sh`)
- [x] **State Tracking, Drift Reconciliation & Self-Healing Engine (`repair` / `fix`)** (`lib/core/state.sh`)
- [x] **Hybrid Conda Named Environment + UV Pip Engine & Scoped Hooks** (`lib/modules/conda.sh`)
- [ ] **Two-Phase Privilege Boundary Refactor (`sys-provision` vs `dev-setup`)**
- [x] **Multi-Agent Skills Registration** (`.agents/skills/isaac-baremetal-installer/SKILL.md`)
