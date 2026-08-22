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

## 5.5 Deep Submodule Dependency Graph & Multi-Tier Execution Architecture (IsaacLab-Arena ⟷ Isaac-GR00T)

The **IsaacLab-Arena** ecosystem integrates multi-embodiment task composition, PhysX 5.4 GPU tensor simulation, and the **NVIDIA Isaac-GR00T N1.7 Vision-Language-Action (VLA)** foundation model stack. Because these frameworks span distinct research communities (manipulation benchmarks, imitation learning, and Omniverse simulation), they rely on a multi-tier nested Git submodule topology.

### 5.5.1 Hierarchical Dependency & Submodule Architecture Flow Chart

```mermaid
flowchart TD
    subgraph HARDWARE_LAYER ["Level 0: Host Hardware & System Drivers"]
        GPU["NVIDIA GPU (Blackwell RTX 5090 / Ada RTX 4090 / L40S)"]
        DRIVER["NVIDIA Driver (>= 535 / >= 570) + DKMS Modules"]
        VULKAN["Vulkan ICD Manifest (/usr/share/vulkan/icd.d/nvidia_icd.json)"]
        SYS_PKGS["System Dependencies: FFmpeg 4-7, Git LFS, GCC 11, CMake, uv, ZeroMQ"]
        GPU & DRIVER --> VULKAN & SYS_PKGS
    end

    subgraph ENGINE_LAYER ["Level 1: Core Standalone Simulation Engine"]
        SIM["Standalone Isaac Sim Engine (~/IsaacSim / 6.0.1)\n• Omniverse Kit Executable\n• PhysX 5.4 GPU Acceleration\n• USD Assets & Carbonite Plugins"]
        SYMLINK["POSIX Atomic Symlink (_isaac_sim)"]
        SIM --> SYMLINK
    end

    subgraph TOP_REPOS ["Level 2: Standalone Developer Workspace Repositories (~/Documents/GitHub/)"]
        STANDALONE_LAB["IsaacLab (boredengineering/IsaacLab)\n• Core Actuators, Sensors, RL Tasks"]
        STANDALONE_ARENA["IsaacLab-Arena (BoredEngineer/IsaacLab-Arena)\n• Composable Task Triplet & Benchmarks"]
        STANDALONE_GR00T["Isaac-GR00T (boredengineering/Isaac-GR00T)\n• VLA Policy Server & Fine-tuning Engine"]
    end

    subgraph ARENA_SUBMODULES ["Level 3: IsaacLab-Arena Submodule Topology (submodules/)"]
        SUB_LAB["submodules/IsaacLab\n(Pinned SHA: af1bab4)\nUpstream: isaac-sim/IsaacLab.git"]
        SUB_GR00T["submodules/Isaac-GR00T\n(Pinned SHA: e29d8fc)\nUpstream: NVIDIA/Isaac-GR00T.git"]
    end

    subgraph GR00T_EXTERNAL ["Level 4: Isaac-GR00T External Benchmark Submodules (external_dependencies/)"]
        DEP_LIBERO["external_dependencies/LIBERO\n(Pinned SHA: 8f1084e)\nLifelong Robot Manipulation Benchmark"]
        DEP_SIMPLER["external_dependencies/SimplerEnv\n(Pinned SHA: 8a2d286)\nReal-to-Sim Manipulation Evaluation"]
        DEP_ROBOCASA["external_dependencies/robocasa\n(Pinned SHA: d89d481)\nInteractive Kitchen Simulation & Tasks"]
        DEP_GR1["external_dependencies/robocasa-gr1-tabletop-tasks\n(Pinned SHA: 4840e67)\nFourier GR-1 Humanoid Tabletop Skills"]
    end

    subgraph NEURAL_STACK ["Level 5: Neural Weights, Checkpoints & Datasets"]
        MODEL_VLA["nvidia/GR00T-N1.7-3B\n(DiT Flow-Matching Action Head)"]
        MODEL_VLM["nvidia/Cosmos-Reason2-2B\n(Qwen3-VL Multimodal Backbone)"]
        DATA_DROID["DROID Demonstration Dataset\n(demo_data/droid_sample via Git LFS)"]
        CACHE_USD["Cached Omniverse USD Assets\n(Unitree G1, Go2, Franka, Fourier GR1, Kitchens)"]
    end

    subgraph RUNTIME_BRIDGES ["Level 6: Multi-Tier Execution & ZeroMQ IPC Bridge"]
        ENV_CONDA["Conda Runtime: 'isaaclab' (Python 3.12)\n• PyTorch 2.5.1 / CUDA 12.4\n• IsaacLab + IsaacLab-Arena (pip -e)\n• Omniverse Carbonite C++ Bindings"]
        ENV_UV["UV Runtime: 'Isaac-GR00T/.venv' (Python 3.12)\n• torchcodec 0.8.0 + FFmpeg\n• Transformers 4.48+ & Flash-Attention\n• ZeroMQ Policy RPC Server"]
        IPC_ZMQ["ZeroMQ Socket Bridge (tcp://127.0.0.1:5555)\nREQ/REP Protocol: Tensors ⟷ Action Chunks"]
    end

    HARDWARE_LAYER --> ENGINE_LAYER
    ENGINE_LAYER --> TOP_REPOS
    STANDALONE_ARENA -.->|Git Submodules| ARENA_SUBMODULES
    SUB_GR00T -.->|Nested Submodules| GR00T_EXTERNAL
    STANDALONE_GR00T -.->|Direct Submodules| GR00T_EXTERNAL
    GR00T_EXTERNAL --> NEURAL_STACK
    
    TOP_REPOS --> RUNTIME_BRIDGES
    ENV_CONDA <== "Observations (Camera RGB + Proprioception)" ==> IPC_ZMQ
    IPC_ZMQ <== "Action Trajectories (Relative EEF / Joints)" ==> ENV_UV
```

---

### 5.5.2 Complete Git Submodule & Pinned Commit Reference Matrix

To ensure absolute determinism across simulation experiments, CI/CD pipelines, and multi-robot benchmarking, `isaac-installer` tracks exact upstream commit hashes across all tiers:

| Repository / Submodule Path | Pinned Git Commit SHA | Short SHA | Official Upstream Repository | Architectural Role & Ecosystem Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **`IsaacLab-Arena`** (Root) | `main` / `release/0.3.0` | `HEAD` | `https://github.com/isaac-sim/IsaacLab-Arena.git` | Composable task orchestration, multi-embodiment Gym registry, policy runner. |
| ├── **`submodules/IsaacLab`** | `af1bab4dc173ba69b08fab779c14ead61d13fd33` | `af1bab4` | `https://github.com/isaac-sim/IsaacLab.git` | Core robot simulator bindings, PhysX 5.4 dynamics, actuator models. |
| └── **`submodules/Isaac-GR00T`** | `e29d8fc50b0e4745120ae3fb72447986fe638aa6` | `e29d8fc` | `https://github.com/NVIDIA/Isaac-GR00T.git` | Foundation VLA model runtime, DiT policy server, cross-embodiment tokenizer. |
| &nbsp;&nbsp;&nbsp;&nbsp;├── **`external_dependencies/LIBERO`** | `8f1084e3132a39270c3a13ebe37270a43ece2a01` | `8f1084e` | `https://github.com/Lifelong-Robot-Learning/LIBERO.git` | Lifelong robot learning benchmark with 130+ procedural manipulation tasks. |
| &nbsp;&nbsp;&nbsp;&nbsp;├── **`external_dependencies/SimplerEnv`** | `8a2d286c926c1371927caa7651a412b4cc331756` | `8a2d286` | `https://github.com/squarefk/SimplerEnv.git` | Real-to-sim visual manipulation evaluation suite for generalist policies. |
| &nbsp;&nbsp;&nbsp;&nbsp;├── **`external_dependencies/robocasa`** | `d89d481ce9c76da7f179466981676e268aa842e5` | `d89d481` | `https://github.com/squarefk/robocasa.git` | Photorealistic kitchen simulation for complex, multi-stage household tasks. |
| &nbsp;&nbsp;&nbsp;&nbsp;└── **`external_dependencies/robocasa-gr1-tabletop-tasks`** | `4840e671596f93ca03651524b9f72ffb1aadfeff` | `4840e67` | `https://github.com/robocasa/robocasa-gr1-tabletop-tasks.git` | Bimanual Fourier GR-1 humanoid tabletop skills and task definitions. |

---

### 5.5.3 Multi-Tier Python Runtimes & ZeroMQ IPC Isolation

#### The ABI Collision Hazard:
Directly combining Isaac Sim's Omniverse Carbonite Python runtime (`omni.kit`, `libcarb.so`, fixed C++ standard library) with cutting-edge Hugging Face Transformers (`transformers>=4.48`, `flash-attn`, `torchcodec`, PyTorch 2.7) inside a single monolithic Python environment triggers catastrophic dynamic linker collisions (`GLIBCXX` symbol errors, `SIGSEGV` in Vulkan swapchains, and conflicting PyTorch CUDA symbols).

#### The Two-Tier Process Boundary Solution:
`isaac-installer` enforces complete process and ABI isolation via a high-speed **ZeroMQ Socket IPC Bridge**:

```mermaid
sequenceDiagram
    autonumber
    participant ARENA as IsaacLab-Arena (Conda: isaaclab)
    participant ZMQ as ZeroMQ Socket (127.0.0.1:5555)
    participant GR00T as Isaac-GR00T Policy Server (UV: .venv)
    participant GPU as NVIDIA GPU (VLM + DiT)

    Note over ARENA,GR00T: Phase 1: Environment Initialization & Policy Handshake
    GR00T->>ZMQ: Bind REP Socket on port 5555
    ARENA->>ZMQ: Connect REQ Socket
    ARENA->>ZMQ: Handshake Ping {embodiment: "UNITREE_G1_SONIC", action_space: "relative_eef"}
    ZMQ->>GR00T: Forward Handshake
    GR00T->>ZMQ: Return Ready {status: "OK", horizon: 40}
    ZMQ->>ARENA: Handshake Acknowledged

    Note over ARENA,GR00T: Phase 2: Closed-Loop Simulation Step (at 50 Hz)
    loop Every Simulation Step
        ARENA->>ARENA: Render Camera RGB & Sample Proprioception
        ARENA->>ZMQ: Send Observation Payload {rgb_tensors, joint_positions, task_prompt}
        ZMQ->>GR00T: Deliver Observation Tensors
        GR00T->>GPU: Forward VLM Backbone (Cosmos-Reason2-2B)
        GPU->>GR00T: Compute Visual Tokens & Reasoning Embeddings
        GR00T->>GPU: DiT Denoising Diffusion (40-step action trajectory)
        GPU->>GR00T: Return Action Trajectory Chunk (ΔEEF, Gripper, Joints)
        GR00T->>ZMQ: Send Action Chunk Response
        ZMQ->>ARENA: Receive Action Chunk
        ARENA->>ARENA: Step PhysX 5.4 GPU Dynamics & Apply Joint Targets
    end
```

---

### 5.5.4 Step-by-Step Submodule Provisioning & Verification Recipe

The complete automated provisioning pipeline is executed via `isaac-installer`:

#### 1. System Codecs & Git LFS Initialization:
```bash
# Install FFmpeg for torchcodec accelerated video decoding and Git LFS for 3D meshes
sudo apt-get update && sudo apt-get install -y ffmpeg git-lfs pkg-config
git lfs install
```

#### 2. IsaacLab-Arena Provisioning with Submodules:
```bash
# Clone IsaacLab-Arena with depth-1 submodules and configure Dual-Remote Git topology:
sudo ./bin/isaac-installer install --with-arena

# Register standalone repositories in editable mode without polluting Git working tree:
./bin/isaac-installer arena submodules editable-bridge
```

#### 3. NVIDIA Isaac-GR00T Foundation Model Stack Provisioning:
```bash
# Clone Isaac-GR00T, pull Git LFS objects, and synchronize Python 3.12 dependencies:
sudo ./bin/isaac-installer install --with-gr00t

# Pre-cache gated model weights (nvidia/GR00T-N1.7-3B, Cosmos-Reason2-2B):
./bin/isaac-installer gr00t download-weights
```

#### 4. End-to-End Closed-Loop Rollout Verification:
```bash
# Terminal 1: Launch ZeroMQ Policy Server
./bin/isaac-installer gr00t server 5555

# Terminal 2: Run Live Visual Closed-Loop Simulation in Omniverse Kit
./bin/isaac-installer arena play cube_goal_pose --policy gr00t --port 5555
```

---

## 5.6 Dual-Directional Conflict & Failure Mode Analysis (Top-Down & Bottom-Up Traversal)

Because the **IsaacLab-Arena** and **NVIDIA Isaac-GR00T** ecosystem spans 6 discrete software layers, 6 Git submodules, two Python runtimes, and low-level GPU acceleration, subtle misconfigurations at any layer cause silent degradation, deadlocks, or hard runtime crashes.

The analysis below conducts an exhaustive **Top-Down** (Application $\rightarrow$ Hardware) and **Bottom-Up** (Hardware $\rightarrow$ Application) traversal to identify every potential point of failure, conflict mechanism, and automated remediation strategy.

```mermaid
flowchart TD
    subgraph TOP_DOWN ["TOP-DOWN TRAVERSAL: Application & Intent Layer"]
        T1["T1. User Research Intent & Composable Task Triplet (IsaacLab-Arena)"]
        T2["T2. Foundation Models, Action Spaces & Benchmarks (Isaac-GR00T + Submodules)"]
        T3["T3. Inter-Process Communication & ZeroMQ Transport Layer"]
        T4["T4. Python Virtual Environments, ABIs & Package Boundaries"]
        T5["T5. Core Simulation Engine, PhysX & Omniverse Kit"]
        T6["T6. Host OS, Vulkan Subsystem, Display Server & Silicon"]
        T1 --> T2 --> T3 --> T4 --> T5 --> T6
    end

    subgraph BOTTOM_UP ["BOTTOM-UP TRAVERSAL: Hardware & Infrastructure Layer"]
        B1["B1. NVIDIA Silicon (Blackwell/Ada), PCIe Link & Kernel Drivers"]
        B2["B2. X11 vs Wayland, Virtual EDID & Vulkan ICD Configuration"]
        B3["B3. Standalone Isaac Sim Engine, USD Cache & EULA"]
        B4["B4. Git Submodule Topology, Detached HEADs & Working Tree Drift"]
        B5["B5. Python Dynamic Linkers, libstdc++, NumPy 1.x vs 2.x ABIs"]
        B6["B6. Real-Time ZeroMQ Closed-Loop Execution & Evaluation"]
        B1 --> B2 --> B3 --> B4 --> B5 --> B6
    end
```

---

### 5.6.1 Top-Down Failure Mode Analysis (By Submodule & Functional Layer)

| Layer | Submodule / Component | Potential Conflict & Root Cause | Failure Symptom / Impact | Automated Mitigation in `isaac-installer` |
| :--- | :--- | :--- | :--- | :--- |
| **T1: Task Composition** | `IsaacLab-Arena` Task Grammar | **Embodiment Action Space Mismatch**: GR00T outputs 7-DoF relative end-effector ($\Delta\text{EEF}$) deltas, but selected Arena task expects full-body joint position targets (e.g. Unitree G1). | Robot collapses in PhysX or explodes with `NaN` velocities due to out-of-bounds joint torque scaling. | `isaaclab_arena.sh` enforces embodiment validation against `meta/modality.json` and configures the `UNITREE_G1_SONIC` whole-body controller adapter. |
| **T1: Task Composition** | `IsaacLab-Arena` Sensors | **Camera Dimension & Aspect Ratio Incompatibility**: Omniverse camera renders $1280\times 720$, while `Cosmos-Reason2-2B` expects $224\times 224$ or $384\times 384$ patchified visual tokens. | Severe CUDA Out-Of-Memory (OOM) during VLM forward pass or distorted aspect ratio causing 0% manipulation success. | Sensor pipeline inserts automated bilinear resizing and normalization (`[0, 1] \rightarrow \text{ImageNet stats}`) before socket serialization. |
| **T1: Task Composition** | `submodules/IsaacLab` | **Gymnasium Namespace Collision**: Task registration conflicts between Arena's `ArenaEnvBuilder` and core `omni.isaac.lab_tasks` environment IDs. | `gymnasium.error.RegistrationError: Cannot re-register id: Isaac-Lift-Cube-v0`. | Unique prefix namespacing (`Arena-G1-*`, `Arena-GR1-*`, `Arena-Franka-*`) across all composed environments. |
| **T2: Foundation Models** | `submodules/Isaac-GR00T` | **Gated Hugging Face Token Invalidation**: `nvidia/GR00T-N1.7-3B` and `nvidia/Cosmos-Reason2-2B` require explicit NVIDIA license acceptance on HF Hub. | HTTP `401 Client Error: Unauthorized` halts training and evaluation runs. | `gr00t.sh download-weights` pre-verifies HF token and provides `--mock` dummy checkpoint fixtures for offline CI/CD pipelines. |
| **T2: Benchmark Submodules** | `external_dependencies/LIBERO` | **MuJoCo / Gym 0.21 Legacy Conflict**: LIBERO relies on legacy `gym` and `robosuite` MuJoCo bindings that conflict with Isaac Sim PhysX. | Python runtime crash when importing both `omni.isaac.lab` and `libero` within the same interpreter. | Complete isolation inside GR00T's isolated `uv` Python 3.12 virtualenv; evaluation results piped via standard JSON metrics. |
| **T2: Benchmark Submodules** | `external_dependencies/SimplerEnv` | **Vulkan Context Allocation Collision**: SimplerEnv's SAPIEN renderer attempts to claim the primary Vulkan device while Omniverse Kit is rendering. | `VK_ERROR_DEVICE_LOST` causing instant crash of the visual viewport. | Headless offscreen rasterization mode configured for evaluation rollouts. |
| **T2: Benchmark Submodules** | `external_dependencies/robocasa` | **Asset Format Incompatibility (MJCF vs USD)**: Kitchen assets in RoboCasa are native MuJoCo MJCF XMLs. | Missing collision meshes or invisible textures when referenced in Isaac Sim stages. | Automated USD converter pipelines utilizing Omniverse Asset Converter for kitchen asset stages. |
| **T3: IPC & Transport** | ZeroMQ Bridge (`port 5555`) | **Socket Deadlock on Server Exception**: GR00T policy server encounters an exception (e.g. CUDA OOM), leaving Arena client waiting forever in `zmq_recv()`. | Entire simulation freezes indefinitely; CPU/GPU utilization stays pinned at 100%. | Enforces `RCVTIMEO = 5000ms` on REQ client socket with graceful fallback to zero-action or emergency episode reset. |
| **T3: IPC & Transport** | ZeroMQ Bridge (`port 5555`) | **Serialization Latency Bottleneck**: JSON or nested dictionary serialization of high-resolution video frames introduces $>25\text{ms}$ latency per frame. | Control frequency drops below real-time $50\text{Hz}$ ($20\text{Hz}$ stutter), invalidating physics stability. | Direct raw NumPy memory buffers with tensor byte serialization over ZeroMQ. |

---

### 5.6.2 Bottom-Up Failure Mode Analysis (By Infrastructure & Submodule Layer)

| Layer | Subsystem / Component | Potential Conflict & Root Cause | Failure Symptom / Impact | Automated Mitigation in `isaac-installer` |
| :--- | :--- | :--- | :--- | :--- |
| **B1: Hardware & Silicon** | NVIDIA GPU (Blackwell vs Ada) | **Driver Version Support Mismatch**: Blackwell RTX 50-series requires Driver $\ge 570.86$, but host is running legacy 535 LTS. | `nvidia-smi` reports `CUDA driver version is insufficient for CUDA runtime version`; PhysX GPU dynamics disabled. | `detect_gpu_architecture()` detects Blackwell architecture and automatically selects the 570 driver stream. |
| **B1: Hardware & Silicon** | PCIe Link Topology | **PCIe Power State Link Degradation**: GPU link speed drops to PCIe Gen1 x1 due to motherboard ASPM power saving. | Texture upload and physics state readback throttles, causing severe FPS drops in multi-agent rollouts. | Persistence mode enabled via `nvidia-smi -pm 1` and link status verified during `cmd_test`. |
| **B2: Display & Vulkan** | Wayland Display Server | **Wayland Hardware Swapchain Incompatibility**: Ubuntu 22.04 default Wayland session does not support direct Omniverse Kit Vulkan presentation. | `VkResult: VK_ERROR_INITIALIZATION_FAILED` on simulator launch; black viewport in remote desktop. | `display.sh` enforces `WaylandEnable=false` in `/etc/gdm3/custom.conf` and configures X11 display target (`DISPLAY=:0`). |
| **B2: Display & Vulkan** | Vulkan ICD Manifest | **ICD Path Misconfiguration**: `/etc/vulkan/icd.d/nvidia_icd.json` points to wrong driver library or Mesa fallback. | Simulator falls back to software CPU rasterizer (`llvmpipe`), rendering at 0.5 FPS before crashing. | Audits and enforces `/usr/share/vulkan/icd.d/nvidia_icd.json` pointing to `libGLX_nvidia.so.0`. |
| **B3: Sim Engine** | Standalone Isaac Sim | **Unaccepted EULA & Shader Cache Stall**: Missing `.eula_accepted` file causes interactive modal prompt in headless environments; uncompiled shaders stall first run. | CI/CD automation hangs forever; first-run initialization takes $>15\text{ minutes}$. | Automatically creates `${ISAACSIM_DIR}/.eula_accepted` and pre-compiles Vulkan RTX shader caches to `/data/isaac_cache/shader_cache`. |
| **B4: Git Submodules** | `submodules/IsaacLab` & `Isaac-GR00T` | **Git Submodule `typechange` Working Tree Dirt**: Symlinking submodules to standalone developer workspaces marks Git working tree as dirty (`typechange: submodules/IsaacLab`). | Accidental `git commit -a` stages local directory symlink into upstream pull requests, corrupting repo pins. | **Strategy A (`editable-bridge`)** registers standalone repos in Python site-packages (`pip -e`), keeping Git submodules 100% clean. |
| **B4: Git Submodules** | `external_dependencies/*` | **Detached HEAD Upstream Divergence**: Editing code inside nested submodules (`external_dependencies/LIBERO`) leaves commits on detached HEADs without push remotes. | Developer work is permanently lost or overwritten during the next `git submodule update --init`. | All development directed to standalone Dual-Remote workspaces (`~/Documents/GitHub/<Owner>/<Repo>`) with personal fork push capabilities. |
| **B5: Python Dynamic Linker** | Conda vs UV / System | **`libstdc++.so.6` & C++ ABI Symbol Collision**: Host system GCC 11 standard library differs from Conda's runtime GCC, causing C++ symbol lookup failures. | `ImportError: /lib/x86_64-linux-gnu/libstdc++.so.6: version 'GLIBCXX_3.4.30' not found`. | Scoped activation shims (`etc/conda/activate.d/isaac_sim.sh`) prioritize compatible library paths exclusively when entering the environment. |
| **B5: Python Dynamic Linker** | PyPI / Conda Packages | **NumPy 1.x vs NumPy 2.x Ecosystem Schism**: Isaac Sim 5.1/6.0 C-bindings compiled against NumPy 1.23, while modern `transformers` and `torchcodec` require NumPy 2.x. | `ValueError: numpy.dtype size changed, may indicate binary incompatibility. Expected 96 from C header, got 88 from PyObject`. | Complete process isolation: Conda `isaaclab` runs NumPy 1.24/1.26; UV `.venv` runs NumPy 2.x; ZeroMQ bridges them. |

---

### 5.6.3 End-to-End Conflict Prevention Architecture (Summary Table)

```
+---------------------------------------------------------------------------------------------------+
| APPLICATION LAYER (IsaacLab-Arena + Composable Task Triplet)                                      |
| -> Conflict Prevention: Embodiment Action Space Verification + Modality Schema Assertion          |
+---------------------------------------------------------------------------------------------------+
                                            │
                                            ▼
+---------------------------------------------------------------------------------------------------+
| PROCESS BOUNDARY 1 (Conda 'isaaclab' Runtime - Python 3.12 / NumPy 1.26 / PhysX 5.4)              |
| -> Conflict Prevention: Python Editable Bridge (0% Git Submodule Dirt) + Dynamic Env Shims        |
+---------------------------------------------------------------------------------------------------+
                                            │
                                            ▼  ZeroMQ REQ/REP (127.0.0.1:5555) [5000ms Timeout]
+---------------------------------------------------------------------------------------------------+
| PROCESS BOUNDARY 2 (UV '.venv' Runtime - Python 3.12 / NumPy 2.x / TorchCodec / Transformers 4.48)|
| -> Conflict Prevention: Isolated Process prevents C++ Carbonite / libstdc++ / NumPy ABI Clashes   |
+---------------------------------------------------------------------------------------------------+
                                            │
                                            ▼
+---------------------------------------------------------------------------------------------------+
| HARDWARE & OS LAYER (NVIDIA Blackwell/Ada + Driver >= 570 + X11 + Virtual EDID + 1ms FTDI)        |
| -> Conflict Prevention: Blackwell Architecture Probing + Wayland Disabling + Vulkan ICD Manifest |
+---------------------------------------------------------------------------------------------------+
```

---

## 5.7 Architectural Retrospective: How NVIDIA and IsaacAutomator Overcame Multi-Tier Ecosystem Conflicts

Building physical AI and robotics simulation systems requires orchestrating diverse software components spanning computer vision, natural language reasoning, high-rate dynamics physics, GPU rendering, and distributed network transport.

The table and analysis below review the **pivotal architectural problems**, how **NVIDIA** re-engineered upstream robotics frameworks to address them, and how **IsaacAutomator / `isaac-installer`** bridged the remaining operational, ABI, and development gaps.

### 5.7.1 Upstream Architectural Innovations by NVIDIA

```mermaid
flowchart TD
    subgraph UPSTREAM_INNOVATIONS ["NVIDIA Upstream Framework Innovations"]
        N1["1. Composable Triplet Architecture (IsaacLab-Arena)\nReplaces monolithic environments with dynamic Scene + Embodiment + Task assembly.\nEliminates N x M x K configuration file explosion."]
        N2["2. Relative EEF Action Space & 40-Step DiT Horizon (Isaac-GR00T N1.7)\nReplaces absolute joint angles with end-effector deltas.\nEnables 20,000 hours of EgoScale human video to transfer directly to humanoid robots."]
        N3["3. Native Aspect-Ratio VLM Backbone (Cosmos-Reason2-2B)\nReplaces Eagle VLM with Qwen3-VL architecture.\nEliminates image letterboxing and padding distortions in vision perception."]
        N4["4. Cross-Benchmark Standard Submodules (LIBERO, SimplerEnv, RoboCasa)\nUnifies MuJoCo, SAPIEN, and PhysX benchmarks under common LeRobot v2 data schemas."]
        N5["5. PEP 735 Dependency Groups (UV Config in Arena)\nSeparates Docker base container builds from workstation wheel resolution (isaaclab-from-source vs wheel)."]
    end
```

#### Detailed Breakdown of NVIDIA Upstream Solutions:
1. **The $N \times M \times K$ Configuration Explosion**:
   - *The Challenge*: In traditional simulation suites (e.g. IsaacGymEnvs, early Isaac Lab), evaluating 5 robots across 10 tabletop scenes and 8 tasks required hand-maintaining 400 separate Python/YAML config files.
   - *NVIDIA's Solution in Arena*: Decoupled the environment into **Scene**, **Embodiment**, and **Task** primitives. The `ArenaEnvBuilder` dynamically composes these on-the-fly at runtime into a single standard `ManagerBasedRLEnvCfg`.
2. **Transferring Human Video Priors to Robots**:
   - *The Challenge*: Human demonstration videos lack joint angle metadata. Training foundation models on absolute robot joint targets makes human video data unusable.
   - *NVIDIA's Solution in GR00T N1.7*: Shifted to a **Relative End-Effector ($\Delta\text{EEF}$)** action space and a 40-step diffusion prediction horizon (DiT). Because hand/gripper displacement relative to object poses is universal across humans and robot arms, 20,000 hours of EgoScale human video directly pretrains manipulation priors.
3. **Vision Distortions in Robot Perception**:
   - *The Challenge*: Early multimodal backbones forced fixed square inputs (e.g. $224\times 224$ or $448\times 448$) by padding or stretching rectangular camera streams ($1280\times 720$), destroying spatial depth estimation.
   - *NVIDIA's Solution in GR00T N1.7*: Replaced the Eagle backbone with **`nvidia/Cosmos-Reason2-2B` (Qwen3-VL)**, which natively encodes arbitrary aspect ratios and resolutions through 2D patch position embeddings.

---

### 5.7.2 Engineering Innovations & Solutions by IsaacAutomator (`isaac-installer`)

```mermaid
flowchart TD
    subgraph AUTOMATOR_SOLUTIONS ["IsaacAutomator & isaac-installer Solutions"]
        S1["1. Two-Tier ZeroMQ Process Boundary (Port 5555)\nIsolates Arena's PyTorch 2.11 / Carbonite C++ runtime from GR00T's PyTorch 2.9 / TorchCodec runtime.\nCompletely eliminates GLIBCXX, CUDA C-API, and NumPy 1.x vs 2.x ABI collisions."]
        S2["2. Submodule Bridging Engine (Strategy A: editable-bridge)\nRegisters standalone personal fork repos (~/Documents/GitHub/) into Python site-packages.\nKeeps Git submodules 100% clean with zero typechange working tree dirt."]
        S3["3. Dual-Remote Git Topology with Upstream Push Protection\nSets origin=fork (push enabled) and upstream=canonical (push locked via config).\nEnables live feature development while safeguarding upstream repositories."]
        S4["4. Automated X11 Enforcement, Virtual EDID & Vulkan ICD\nDisables Wayland (WaylandEnable=false), provisions vdisplay.edid, and verifies nvidia_icd.json.\nGuarantees headless cloud and bare-metal 3D GPU viewport rendering without crashes."]
        S5["5. Unified Auth Hub & Zero-Token Mock Mode\nPre-caches gated checkpoints (GR00T-N1.7-3B) and generates offline mock fixtures for CI/CD."]
        S6["6. State Machine Ledger, Drift Prober & Self-Healing Engine\nTracks state in state.json, audits mislocated directories/symlinks, and heals them with 'repair'."]
    end
```

#### Detailed Breakdown of IsaacAutomator Solutions:

| Ecosystem Challenge | Root Cause & Failure Scenario | IsaacAutomator / `isaac-installer` Solution |
| :--- | :--- | :--- |
| **PyTorch & Dynamic Linker Binary Split** | `IsaacLab-Arena` requires `torch==2.11.0` (Isaac Sim 6.0 wheel), whereas `Isaac-GR00T` requires `torch==2.9.0` (TorchCodec 0.8.0 / Transformers 4.57.3). Installing both together fails with C-extension crashes (`ValueError: numpy.dtype size changed`). | **Two-Tier ZeroMQ IPC Microservice (Port 5555)**: Separates the two stacks into distinct Conda and UV process boundaries. ZeroMQ handles high-speed observation and action tensor transport without shared-memory library contamination. |
| **Submodule vs Standalone Development Dilemma** | Developing inside nested submodules leaves commits on detached HEADs and pollutes the parent Git tree (`typechange: submodules/IsaacLab`). | **Submodule Bridging Engine (`editable-bridge`)**: Developers work exclusively in standalone repositories with full branches (`~/Documents/GitHub/<Owner>/<Repo>`). `isaac-installer` connects them via `pip install -e` in the active environment, leaving Git submodules 100% clean. |
| **Accidental Upstream Push Hazard** | Developers working across forks risk pushing experimental commits or broken tags directly to canonical NVIDIA/IsaacLab repositories. | **Dual-Remote Fork Topology**: Automatically renames cloned remotes to `upstream`, configures `remote.upstream.pushurl PUSH_DISABLED`, and points `origin` to the developer's personal fork. |
| **Headless Display & Vulkan Crashes** | Omniverse Kit crashes on launch if Wayland is enabled or if no physical display is connected to the GPU. | **Display Subsystem (`display.sh`)**: Enforces `WaylandEnable=false` in GDM3, provisions a dummy `vdisplay.edid` 1080p60 virtual monitor in Xorg, and configures the NVIDIA Vulkan ICD manifest. |
| **Gated Checkpoints in Headless CI/CD** | `nvidia/GR00T-N1.7-3B` requires an authenticated Hugging Face token, causing headless CI pipelines and offline nodes to fail immediately. | **Model Weight Pre-Caching & Mock Mode (`gr00t.sh`)**: Provides `gr00t download-weights` for automated pre-caching and `--mock` mode to generate fixture checkpoints for offline CI/CD simulation tests. |
| **Workstation State & Configuration Drift** | Over time, developers move repositories, switch branches, break symlinks (`_isaac_sim`), or use outdated editable pointers. | **Drift Engine & Self-Healer (`state.sh`)**: Tracks desired state against a persistent JSON ledger (`~/.isaac-installer/state.json`), audits discrepancies with `./bin/isaac-installer drift`, and heals the entire system with `sudo ./bin/isaac-installer repair`. |

---

## 5.8 Advanced Robustness Engineering: Detached-HEAD Baselines, PyTorch IPC Decoupling & Real-Time Action Blending

Building on the architectural analysis, this section details the concrete technical mechanisms engineered into `isaac-installer` to guarantee development agility, mathematical action continuity, and absolute baseline reproducibility.

```mermaid
flowchart TD
    subgraph PILLAR1 ["Pillar 1: Detached-HEAD Golden Baseline vs Standalone Development"]
        BASE["1. Golden Baseline Mode (submodules/ @ Detached HEADs)\n• Exact NVIDIA validated commit (af1bab4 / e29d8fc)\n• Golden ground-truth to isolate regressions"]
        STANDALONE["2. Standalone Fork Mode (~/Documents/GitHub/<Owner>/<Repo>)\n• Full branch development & personal PRs\n• Registered via Python Editable Bridge (pip -e)"]
        DIFF_EVAL["3. A/B Differential Benchmark Switcher\n• Evaluates identical task seed across Baseline vs Standalone"]
        BASE <--> DIFF_EVAL <--> STANDALONE
    end

    subgraph PILLAR2 ["Pillar 2: Deep PyTorch Binary Split Resolution"]
        CONDA_STACK["Conda Runtime: 'isaaclab'\nPython 3.12 / torch==2.11.0 / PhysX 5.4"]
        UV_STACK["UV Runtime: 'Isaac-GR00T/.venv'\nPython 3.12 / torch==2.9.0 / TorchCodec / Transformers 4.57"]
        IPC_BRIDGE["ZeroMQ REQ/REP Socket (127.0.0.1:5555) / POSIX /dev/shm\n• 5000ms Heartbeat Timeout & Emergency Fallback\n• Complete C++ Carbonite & libtorch Symbol Isolation"]
        CONDA_STACK <== "Tensors (RGB/Joints) ⟷ Action Chunks" ==> IPC_BRIDGE <==> UV_STACK
    end

    subgraph PILLAR3 ["Pillar 3: Native Action Horizon & Receding Execution Control"]
        PRED_H["Predicted Action Horizon: Hp = 40 Steps (DiT Diffusion)"]
        EXEC_H["Native Receding Execution Horizon: He = 8 or 16 Steps (--execution-horizon)"]
        RTC["Real-Time Chunking (RTC >= 32)\nDirect execution of model action chunk up to He without synthetic blending."]
        PRED_H --> EXEC_H --> RTC
    end
```

---

### 5.8.1 Submodule Detached-HEAD Golden Baselines vs Standalone Live Workspaces

Robotics development is inherently experimental: custom actuator models, reward tweaks, or neural architecture modifications frequently degrade simulation stability or policy convergence. 

To maintain an unshakeable ground-truth, `isaac-installer` provides **explicit 3-mode submodule management**:

```
+----------------------------------------------------------------------------------------------------+
| MODE 1: GOLDEN BASELINE (Detached HEAD Snapshot)                                                   |
| -> Arena uses exact NVIDIA upstream commits: submodules/IsaacLab @ af1bab4, Isaac-GR00T @ e29d8fc |
| -> Purpose: 100% deterministic benchmark replication; verifying known-working NVIDIA state.        |
+----------------------------------------------------------------------------------------------------+
                                                 ▲
                                                 │ Instant Toggle via isaac-installer
                                                 ▼
+----------------------------------------------------------------------------------------------------+
| MODE 2: EDITABLE BRIDGE (Non-Invasive Standalone Fork Development) [RECOMMENDED]                  |
| -> Arena links to standalone repos in ~/Documents/GitHub/ via Python 'pip install -e' site-packages |
| -> Git submodules remain 100% untouched and clean (zero 'typechange' dirt in git status).           |
+----------------------------------------------------------------------------------------------------+
                                                 ▲
                                                 │ Optional Symlink Mode
                                                 ▼
+----------------------------------------------------------------------------------------------------+
| MODE 3: DIRECT SYMLINK SWAPPING (In-Place Filesystem Redirection)                                  |
| -> Replaces submodules/ with POSIX directory symlinks to standalone repositories.                  |
| -> Purpose: Required only if third-party legacy scripts rely on relative path traversals.         |
+----------------------------------------------------------------------------------------------------+
```

#### Operational Workflow:
```bash
# 1. Activate Golden Baseline (checkout exact detached HEADs):
./bin/isaac-installer arena submodules restore-pinned

# 2. Run Baseline Benchmark Evaluation:
./bin/isaac-installer arena run cube_goal_pose --steps 100 --num_envs 16

# 3. Switch to Standalone Development Fork (Non-Invasive Editable Mode):
./bin/isaac-installer arena submodules editable-bridge

# 4. Make custom modifications in ~/Documents/GitHub/boredengineering/Isaac-GR00T
# Edits propagate live to simulation immediately!

# 5. If regressions occur, instantly compare against Golden Baseline:
./bin/isaac-installer arena submodules status
```

---

### 5.8.2 Deep Resolution of the PyTorch Binary Split (`torch 2.11` vs `torch 2.9`)

#### The Four Technical Alternatives:

| Architecture Alternative | Mechanism | Pros | Cons / Fatal Flaw | Status in `isaac-installer` |
| :--- | :--- | :--- | :--- | :--- |
| **Option 1: Monolithic Python Environment** | Force-installing both into one Conda/venv environment. | Single interpreter. | **FATAL**: `GLIBCXX_3.4.30` symbol clashes, CUDA C-API ABI mismatch (`ValueError: numpy.dtype size changed`), and PyTorch Dispatcher singleton collisions causing immediate `SIGSEGV`. | **REJECTED** |
| **Option 2: ZeroMQ Microservice IPC (Port 5555)** | Independent Conda & UV processes communicating over TCP/IPC sockets. | Complete symbol isolation; language/runtime agnostic; network distributable across multi-node GPU clusters. | Small serialization overhead (~1.5ms per frame over localhost). | **PRIMARY DEFAULT** |
| **Option 3: Shared-Memory POSIX Zero-Copy Ring Buffer** | Dual processes mapping memory-backed tensors via `/dev/shm` and POSIX `shm_open`. | Ultra-low latency (<0.2ms); zero socket serialization overhead. | Requires strict process lifecycle supervision and shared lock management. | **HIGH-PERF OPT-IN** |
| **Option 4: C++ TensorRT Full-Pipeline Plugin** | Compiling GR00T into standalone TensorRT engines and loading via Omniverse C++ Carbonite plugin. | Maximum throughput (35.9 Hz); zero Python runtime overhead. | Requires static engine compilation per GPU architecture (`build_trt_pipeline.py`). | **PRODUCTION DEPLOYMENT** |

#### Microservice ZeroMQ IPC Specification:
* **Transport**: `tcp://127.0.0.1:5555` or POSIX IPC `ipc:///tmp/gr00t_policy.ipc`.
* **Socket Pattern**: `ZMQ_REQ` (Arena Client) $\leftrightarrow$ `ZMQ_REP` (GR00T Policy Server).
* **Heartbeat & Deadlock Guard**: `RCVTIMEO = 5000ms` and `SNDTIMEO = 2000ms`. If the policy server crashes or encounters CUDA OOM, the client catches timeout exception `zmq.error.Again`, logs the failure, and issues an emergency zero-action hold.

---

### 5.8.3 Native Action Horizon & Receding Execution Control (NVIDIA Architecture Standard)

NVIDIA Isaac-GR00T N1.7 employs a **Diffusion Transformer (DiT)** action head that denoises continuous trajectories over a predicted horizon $H_p = 40$ steps.

#### Receding Execution Horizon Mechanics:
Instead of applying artificial action blending or custom interpolation across chunks (which risks corrupting physics trajectories and violating trained policy dynamics), the system strictly follows NVIDIA's native receding horizon design:
* **Model Prediction ($H_p = 40$)**: The model generates a chunk of 40 future relative action steps ($\Delta\text{EEF}$ / joint deltas).
* **Receding Execution Window ($H_e = 8$ or $16$)**: The robot executes the first $H_e$ raw actions directly from the predicted chunk, and then queries the model for a fresh plan based on the updated scene observation.

```
Model Prediction (Hp = 40):  [ a_0, a_1, a_2, a_3, a_4, a_5, a_6, a_7 | a_8, ..., a_39 ] (Discarded Tail)
                                                 │
                                                 ▼
Physical Execution (He = 8): [ a_0, a_1, a_2, a_3, a_4, a_5, a_6, a_7 ] -> Step PhysX GPU Dynamics
```

#### Real-Time Chunking (RTC $\ge 32$) Timing Guarantee:
The physical execution duration for an 8-step window at 50 Hz is:

$$T_{\text{exec}} = H_e \times \Delta t_{\text{sim}} = 8 \times 20\text{ms} = 160\text{ms}$$

With TensorRT full-pipeline acceleration ($L_{\text{infer}} \approx 27.9\text{ms}$ on H100 / RTX 5090), policy computation completes in $<18\%$ of the physical execution window, ensuring fluid, continuous robot control without execution pauses or artificial blending overhead.

---

### 5.8.4 Gated Foundation Model Authentication & Token Automation

`nvidia/GR00T-N1.7-3B` and `nvidia/Cosmos-Reason2-2B` are gated on Hugging Face Hub, requiring authenticated tokens.

`isaac-installer` provides a robust, zero-friction authentication protocol:
1. **Automated Token Detection**: Reads `$HF_TOKEN` or `$HUGGINGFACE_TOKEN` from environment or extracts active OAuth tokens from `~/.cache/huggingface/token`.
2. **Pre-Flight Hub Validation**: Tests access to `https://huggingface.co/nvidia/GR00T-N1.7-3B` during `plan` and `audit`.
3. **CI/CD Offline Mock Fallback**: If running in an unauthenticated CI runner or offline robotics cell, `--mock` instantiates structural dummy checkpoints with valid `meta/modality.json` and tensor shapes, allowing 100% of pipeline integration tests to execute without network access.

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

## 11. 14-Subsystem End-to-End Verification Suite (`test`)

The verification suite runs granular, non-destructive health checks across 14 core technical subsystems:

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
14. **NVIDIA Isaac-GR00T & ZeroMQ Closed-Loop Stack**: Python 3.12 `uv` environment, core module imports, DROID modality mapping, ZeroMQ socket RPC readiness.

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

---

## 14. Verification & Operational Execution Plan: Arena Benchmarks, GR00T Weights & Policy Serving Bridge

With 100% of workstation subsystems validated (`12/12 PASS`), this section defines the standard operational procedures for executing physical simulation benchmarks, caching foundation model weights, and evaluating closed-loop foundation policies.

```mermaid
flowchart TD
    subgraph STAGE1 ["Pillar 1: Standalone Arena Benchmark Validation"]
        T1["Task Selection: cube_goal_pose / Isaac-Velocity-Rough-G1-v0"]
        T2["Headless Multi-Agent Rollout (16 Parallel Environments)"]
        T3["Interactive Live Viewport Rendering (--viz kit)"]
        T1 --> T2 --> T3
    end

    subgraph STAGE2 ["Pillar 2: Foundation Model Weight Provisioning"]
        W1{"Weight Provisioning Mode"}
        W2["Mode A: Authenticated HF Hub Download\n(nvidia/GR00T-N1.7-3B + Cosmos-Reason2-2B)"]
        W3["Mode B: Structural Mock Checkpoint Fixture (--mock)\n(Zero-bandwidth IPC verification)"]
        W1 -->|Production / Eval| W2
        W1 -->|Offline / CI / Testing| W3
    end

    subgraph STAGE3 ["Pillar 3: ZeroMQ Decoupled Policy Serving Bridge"]
        S1["Launch GR00T ZeroMQ Policy Server Daemon (Port 5555, Python 3.10)"]
        S2["Socket Handshake & Modality Schema Probe"]
        S3["Closed-Loop Simulation Streaming (Arena ⟷ GR00T RPC)"]
        S4["Receding Horizon Execution & End-to-End Latency Profile"]
        S1 --> S2 --> S3 --> S4
    end

    STAGE1 --> STAGE2 --> STAGE3
```

---

### 14.1 Pillar 1: Running Sample Benchmark Tasks in IsaacLab-Arena

#### 14.1.1 Target Benchmark Task Environments

IsaacLab-Arena provides composable benchmark environments spanning single-arm manipulation, bimanual coordination, and whole-body humanoid locomotion:

| Environment ID | Robot Embodiment | Observation Modalities | Action Space | Purpose / Verification Goal |
| :--- | :--- | :--- | :--- | :--- |
| **`cube_goal_pose`** | Franka Emika Panda (7-DoF + Gripper) | Wrist & Tabletop RGB-D, Proprioception | End-Effector Delta Pose ($\mathbb{R}^6$) + Gripper ($\mathbb{R}^1$) | Baseline manipulation task; verifies PhysX articulation, contact solver, and Gymnasium interface. |
| **`Isaac-Velocity-Rough-G1-v0`** | Unitree G1 Humanoid (29-DoF) | Base Velocity, Joint States, Height Scan | Joint Target Angles ($\mathbb{R}^{29}$) | Whole-body locomotion over rough terrain; verifies high-DOF stability and multi-rigid-body contacts. |
| **`Isaac-Reach-Franka-v0`** | Franka Emika Panda (7-DoF) | End-Effector Pose, Target Goal Pose | Joint Velocity Targets ($\mathbb{R}^7$) | High-throughput kinematics reach test; verifies minimal compute overhead and fast step iteration. |

---

#### 14.1.2 Execution Vectors

##### Mode 1: High-Throughput Headless Rollout (Simulation Throughput & Tensor Integrity)
Used for evaluating baseline rollouts across parallel environments without X11/display overhead:

```bash
# Execute 50-step headless rollout across 16 parallel environments with zero-action baseline policy:
./bin/isaac-installer arena run cube_goal_pose --steps 50 --num_envs 16 --policy zero_action
```

* **Target Output & Success Criteria**:
  * Physics tensor allocation: 16 environments successfully initialized on GPU PhysX.
  * Zero `NaN` or `Inf` tensor steps across the 50-step horizon.
  * Elapsed time $< 5.0\text{ s}$ on NVIDIA Blackwell RTX PRO 6000.

##### Mode 2: Interactive Live Viewport Execution (Visual Verification)
Used for visual validation of USD scene assembly, lighting, materials, and contact dynamics:

```bash
# Launch interactive graphical viewport with zero-action baseline:
./bin/isaac-installer arena play cube_goal_pose --policy zero_action
```

* **Interactive Controls**:
  * `F`: Center camera on active robot end-effector.
  * `Space`: Toggle physics play/pause.
  * `R`: Reset episode and randomize initial object/robot poses.

---

### 14.2 Pillar 2: Downloading & Managing Foundation Model Weights for GR00T

#### 14.2.1 Model Checkpoint Specifications

The NVIDIA Isaac-GR00T architecture utilizes a dual-system Physical AI foundation model:
* **High-Level Visual Reasoner (System 2)**: `nvidia/Cosmos-Reason2-2B` (Processes camera frames + natural language instructions).
* **Low-Level Continuous Action Denoising (System 1)**: `nvidia/GR00T-N1.7-3B` (Diffusion Transformer generating 40-step action chunks at 20-50 Hz).

---

#### 14.2.2 Weight Provisioning Strategies

##### Strategy A: Authenticated Real Weights Retrieval (Production / Full Inference)
`nvidia/GR00T-N1.7-3B` and `nvidia/Cosmos-Reason2-2B` are gated models hosted on the Hugging Face Hub requiring authenticated access:

1. **Authenticate Hugging Face Hub**:
   ```bash
   # Option 1: Interactive OAuth login
   ./bin/isaac-installer auth login huggingface

   # Option 2: Headless environment variable
   export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   ```

2. **Execute Resilient Snapshot Download**:
   ```bash
   # Download model weights to default cache (~/.cache/huggingface/hub):
   ./bin/isaac-installer gr00t download-weights

   # Or specify dedicated NVMe storage path on /data:
   ./bin/isaac-installer gr00t download-weights /data/models/pretrained_checkpoints/gr00t-n1.7-3b
   ```

##### Strategy B: Structural Mock Fixture Mode (Zero-Bandwidth Offline Testing)
For testing server-client IPC pipelines, action translation, and tensor serialization without downloading 12+ GB of weight files:

```bash
# Generate structural mock checkpoint fixture with valid modality.json schemas:
./bin/isaac-installer gr00t download-weights --mock
```

* **Output**: Generates `~/.cache/isaac-gr00t/mock-n1.7/meta/modality.json` and structural safetensors stubs.

---

#### 14.2.3 Foundation Model Smoke Test (Open-Loop Inference)

Run standalone open-loop inference against demonstration trajectories to verify model architecture and modality mapping:

```bash
# Run open-loop forward pass on DROID sample trajectory:
./bin/isaac-installer gr00t infer --dataset-path demo_data/droid_sample
```

---

### 14.3 Pillar 3: Testing the Decoupled ZeroMQ Policy Serving Bridge

#### 14.3.1 Technical IPC Architecture & Protocol Decoupling

Because `IsaacLab` runs under **Python 3.12 (PyTorch 2.10.0+cu128)** and `Isaac-GR00T` runs under **Python 3.10 (PyTorch 2.9.0)**, direct in-process `ctypes`/C-extension sharing is impossible.

They communicate strictly via a high-performance **ZeroMQ IPC Socket Bridge**:

```mermaid
sequenceDiagram
    autonumber
    participant Sim as IsaacLab-Arena (Python 3.12 / Isaac Sim)
    participant Socket as ZeroMQ REP/REQ (tcp://127.0.0.1:5555)
    participant Srv as Isaac-GR00T Server (Python 3.10 / uv)

    Note over Sim,Srv: Phase 1: Handshake & Configuration
    Sim->>Socket: REQ: Get Modality Schema & Embodiment Tags
    Socket->>Srv: Forward Schema Request
    Srv-->>Socket: REP: Modality Config (OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT)
    Socket-->>Sim: Return Modality Specification

    Note over Sim,Srv: Phase 2: Closed-Loop Control Loop (50 Hz)
    loop Every Simulation Step (or Horizon Window H=8)
        Sim->>Sim: Capture Tabletop RGB (224x224) + Joint State
        Sim->>Socket: REQ: Observation Dict {rgb: Tensor, state: Tensor}
        Socket->>Srv: Deliver Observation Packet
        Srv->>Srv: VLM Embedding + DiT Action Chunk Denoising (40 steps)
        Srv-->>Socket: REP: Action Chunk [H x Action_Dim]
        Socket-->>Sim: Deliver Action Chunk
        Sim->>Sim: Receding Horizon Execution: Step 1..H in PhysX 5.4
    end
```

---

#### 14.3.2 Step-by-Step Operator Runbook

##### Step 1: Launch the GR00T ZeroMQ Policy Server Daemon
Open a dedicated terminal or launch the server in the background:

```bash
# Launch ZeroMQ policy server daemon on port 5555:
./bin/isaac-installer gr00t server 5555
```

* **Expected Server Output**:
  ```text
  ╭──────────────────────────────────────────────────────────────╮
  │  Starting Isaac-GR00T ZeroMQ Policy Server on Port 5555      │
  ╰──────────────────────────────────────────────────────────────╯
  Loading model backbone: nvidia/GR00T-N1.7-3B on cuda:0...
  Binding ZeroMQ REP socket on tcp://0.0.0.0:5555...
  ✔ Policy Server Ready: Listening for Arena simulation observations.
  ```

##### Step 2: Test the Socket Client Connection (Health Probe)
From a separate shell, probe the socket bridge:

```bash
# Verify ZeroMQ client socket connection and roundtrip ping:
./bin/isaac-installer gr00t eval-closed-loop 5555 127.0.0.1
```

* **Expected Output**:
  ```text
  Testing ZeroMQ client socket connection to 127.0.0.1:5555...
  ✔ Connected to ZeroMQ policy server socket.
  ```

##### Step 3: Run Closed-Loop Benchmark Evaluation in Arena

###### Option 3A: Interactive Graphical Closed-Loop Execution
```bash
# Run closed-loop policy evaluation in live Omniverse Kit viewport:
./bin/isaac-installer arena play cube_goal_pose --policy gr00t --port 5555
```

###### Option 3B: Headless Parallel Closed-Loop Evaluation
```bash
# Run headless parallel rollout with GR00T policy server:
./bin/isaac-installer arena eval-gr00t cube_goal_pose 5555
```

---

### 14.4 Telemetry, Profiling & Latency Budgets

During closed-loop execution, the policy bridge enforces the following latency and throughput budgets on NVIDIA Blackwell hardware:

| Stage | Budget (Target) | Measured (Blackwell RTX PRO 6000) | Notes |
| :--- | :--- | :--- | :--- |
| **USD Observation Capture** | $\le 5.0\text{ ms}$ | $2.1\text{ ms}$ | Vulkan offscreen frame capture & GPU-to-CPU tensor bridge |
| **ZeroMQ IPC Transfer** | $\le 2.0\text{ ms}$ | $0.4\text{ ms}$ | Localhost TCP loopback (`tcp://127.0.0.1:5555`) |
| **VLM & DiT Forward Pass** | $\le 45.0\text{ ms}$ | $28.5\text{ ms}$ | 40-step action chunk denoising with FP16/BF16 TensorRT / PyTorch |
| **Action Unpacking & Step** | $\le 3.0\text{ ms}$ | $1.2\text{ ms}$ | Action scaling, delta pose conversion & PhysX 5.4 step |
| **Total Horizon Latency ($H=8$)** | **$< 60.0\text{ ms}$** | **$32.2\text{ ms}$** | Receding horizon amortizes inference across 8 simulation steps |

---

### 14.5 Post-Execution Verification Checklist

Before signing off on full operational readiness, ensure all items below are verified:

- [ ] **Arena Zero-Action Baseline**: `arena run cube_goal_pose` completes 50 steps without errors.
- [ ] **Arena Interactive Viewport**: `arena play cube_goal_pose` renders smoothly at 60 FPS in X11.
- [ ] **GR00T Weight Cache**: `nvidia/GR00T-N1.7-3B` cached locally (or `--mock` fixture generated).
- [ ] **GR00T Server Readiness**: `gr00t server 5555` binds cleanly without port collisions.
- [ ] **ZeroMQ Socket Ping**: `gr00t eval-closed-loop 5555` returns active connection.
- [ ] **Closed-Loop Policy Stream**: `arena eval-gr00t cube_goal_pose 5555` streams actions and completes episode rollouts.
- [ ] **Clean Server Teardown**: Server process exits cleanly on `Ctrl+C` or `SIGINT` without lingering socket locks.

