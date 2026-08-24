# Comprehensive Debugging Plan & Architectural Deep Dive: Native Bare-Metal IsaacLab-Arena & Isaac-GR00T

**Document Version:** 3.0.0 (Native Bare-Metal Architecture)  
**Target Platform:** NVIDIA RTX PRO 6000 Blackwell Workstation (96GB VRAM, CUDA 12.8, Driver 595.84)  
**Target Runtimes:** Isaac Sim 6.0.1 / 4.5.0, Isaac Lab 2.3.0 / 3.0, IsaacLab-Arena (0.3.0-prerelease), Isaac-GR00T (N1.6-DROID / N1.7-3B)

---

## 1. Executive Summary & Native Bare-Metal Topology

The robotics physical AI stack runs **100% natively on bare-metal Linux** without container virtualization overhead, providing direct PCIe/GPU DMA throughput, instant editable code iteration, and unified hardware acceleration:

```mermaid
flowchart TD
    subgraph SIM_LAYER ["Native Simulation Runtime (Conda: isaaclab | Python 3.12)"]
        SIM["NVIDIA Isaac Sim (PhysX 5.4 GPU Fabric & Vulkan Offscreen)"]
        LAB["Isaac Lab 3.0 / 2.3.0 (Robot Core & RL Harness)"]
        ARENA["IsaacLab-Arena 0.3.0 (Composable Benchmarks)"]
        ARENA_EXT["isaaclab_arena_gr00t & isaaclab_arena_g1 (Editable Extension Packages)"]
        WBC["Native C++ Whole-Body Controller (Pinocchio / Pink / QP Solvers)"]
        SIM --> LAB --> ARENA --> ARENA_EXT & WBC
    end

    subgraph POLICY_LAYER ["Native Policy Serving Runtime (UV: submodules/Isaac-GR00T | Python 3.10)"]
        GR00T_WEIGHTS["nvidia/GR00T-N1.6-DROID / nvidia/GR00T-N1.7-3B"]
        COSMOS_BACKBONE["nvidia/Cosmos-Reason2-2B (Vision-Language Perception Backbone)"]
        GR00T_SRV["Policy Server Daemon (run_gr00t_server.py on port 5555)"]
        GR00T_WEIGHTS & COSMOS_BACKBONE --> GR00T_SRV
    end

    subgraph IPC_BRIDGE ["High-Throughput ZeroMQ Loopback (tcp://127.0.0.1:5555)"]
        OBS["Sim Observations: Camera RGB (224x224) + Robot Joint States"]
        ACTIONS["Action Predictions: Receding Horizon Delta Joint Chunks [H x 7]"]
    end

    ARENA_EXT <== "ZeroMQ REQ/REP Socket" ==> IPC_BRIDGE <== "Port 5555" ==> GR00T_SRV
```

### Verified Hardware & Runtime Groundwork:
1. **Blackwell GPU Acceleration**: 96GB VRAM, CUDA 12.8, Driver 595.84, Vulkan 1.3.
2. **Open-Loop Inference Validated**: 3.1B parameter forward pass over DROID trajectories runs in **7.14s** load time, **89.9ms/step** latency with valid MSE predictions ($0.00328$).
3. **PhysX Simulation Verified**: Multi-environment tensor physics running at 50 FPS.

---

## 2. The Canonical Bottom-Up Ground Truth: NVIDIA's Minimal Reference

According to the official [IsaacLab-Arena 0.3.0-prerelease Documentation](https://isaac-sim.github.io/IsaacLab-Arena/release/0.3.0-prerelease/pages/quickstart/first_experiments/running_a_real_policy/gr00t.html), the simplest, canonical path to run a real closed-loop policy is the **DROID Tabletop Pick & Place Task on Maple Table**.

### 2.1 The Minimal Canonical Invocation Pattern

```mermaid
sequenceDiagram
    autonumber
    participant Server as GR00T Server (run_gr00t_server.py)
    participant Socket as ZeroMQ Socket (tcp://127.0.0.1:5555)
    participant Client as Arena Evaluation (policy_runner.py)

    Note over Server: Step 1: Launch Model Server Daemon
    Server->>Socket: Bind tcp://127.0.0.1:5555 (DROID Embodiment)
    
    Note over Client: Step 2: Launch Arena Evaluation Runner
    Client->>Socket: Handshake & Send Camera RGB + Joint State
    Socket->>Server: Observation Dict
    Server->>Server: DROID DiT Forward Pass (40-step Denoising)
    Server-->>Socket: 7-DoF Delta Joint Action Chunks
    Socket-->>Client: Receive Action Chunks
    Client->>Client: Step Simulation (Pick rubiks_cube -> Place in bowl)
```

#### Step 1: Policy Server Daemon (GR00T)
```bash
cd ~/Documents/GitHub/boredengineering/Isaac-GR00T
uv run python gr00t/eval/run_gr00t_server.py \
  --model-path nvidia/GR00T-N1.6-DROID \
  --embodiment-tag OXE_DROID \
  --device cuda --host 127.0.0.1 --port 5555
```

#### Step 2: Policy Client (Arena Evaluation Harness)
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
python isaaclab_arena/evaluation/policy_runner.py \
  --viz kit \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5555 \
  --language_instruction "Pick up the Rubik's cube and place it in the bowl." \
  --enable_cameras \
  --num_episodes 3 \
  pick_and_place_maple_table \
  --embodiment droid_abs_joint_pos \
  --pick_up_object rubiks_cube_hot3d_robolab \
  --destination_location bowl_ycb_robolab \
  --hdr home_office_robolab
```

### 2.2 Critical Anatomy of the NVIDIA Reference Command

| Flag / Parameter | Exact Canonical Value | Purpose & Mechanism |
| :--- | :--- | :--- |
| **`--policy_type`** | `isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy` | Official remote client wrapper communicating over ZeroMQ with `run_gr00t_server.py`. |
| **`--policy_config_yaml_path`** | `isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml` | Specifies action chunk size ($H=8$ or $16$), observation key mappings, and action normalization scales. |
| **`--remote_host` & `--remote_port`** | `127.0.0.1:5555` | ZeroMQ client socket destination. |
| **`--language_instruction`** | `"Pick up the Rubik's cube and place it in the bowl."` | Condition prompt for the Cosmos VLM language embedder. |
| **`--enable_cameras`** | Flag | Activates Vulkan offscreen rendering for visual perception observations. |
| **Positional Task** | `pick_and_place_maple_table` | Native Arena task registered in `policy_runner.py`. |
| **`--embodiment`** | `droid_abs_joint_pos` | Robot configuration matching the DROID model weights. |
| **`--pick_up_object`** | `rubiks_cube_hot3d_robolab` | USD asset spawned on the tabletop. |
| **`--destination_location`** | `bowl_ycb_robolab` | Goal receptacle asset. |
| **`--hdr`** | `home_office_robolab` | Photorealistic environment map lighting. |

---

## 3. Deep Structural Reasoning on the Core Underlying Issues

Rather than treating symptoms on the surface, we analyze the 5 foundational underlying issues that govern the failure modes:

```mermaid
flowchart TD
    subgraph ISSUES ["5 Foundational Underlying Issues"]
        I1["1. Extension Package Registration\n(isaaclab_arena_gr00t not linked in Conda)"]
        I2["2. Native Bare-Metal WBC Stack\n(Pinocchio / Pink / QP Solvers for Unitree G1)"]
        I3["3. ZeroMQ IPC Observation Contract\n(Camera RGB dict format & Modality Schema alignment)"]
        I4["4. Episode Horizon & Termination Mechanics\n(100 steps vs 1,000 step episode_length_s)"]
        I5["5. Classical MuJoCo 1-DoF Joint Assertion\n(robosuite 1.4.1 vs 1.5+ get_joint_qpos_addr)"]
    end
```

---

### 3.1 Underlying Issue 1: Extension Package Registration (`isaaclab_arena_gr00t`)

* **The Problem**:
  `policy_runner.py` failed with `ModuleNotFoundError: No module named 'isaaclab_arena_gr00t'`.
* **Underlying Architecture**:
  In Isaac Lab and Arena, modular extensions (such as `isaaclab_arena_gr00t`, `isaaclab_arena_g1`, `isaaclab_tasks`) must be registered into the Python runtime.
* **Bare-Metal Resolution**:
  Instead of virtualization, the extension is installed in editable mode directly into the named `isaaclab` Conda environment:
  ```bash
  conda activate isaaclab
  cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
  pip install -e source/isaaclab_arena_gr00t
  ```
  This creates a live `.egg-link` / `.pth` entry in `~/miniconda3/envs/isaaclab/lib/python3.12/site-packages`, making `Gr00tRemoteClosedloopPolicy` and its configuration YAMLs natively importable.

---

### 3.2 Underlying Issue 2: Native Bare-Metal Whole-Body Control (WBC) for Unitree G1

* **The Problem**:
  NVIDIA documentation for complex humanoid locomanipulation (`GalileoG1LocomanipPickAndPlaceEnvironment`) suggests `./docker/run_docker.sh` because humanoid whole-body control requires specialized kinematics and quadratic programming (QP) solvers.
* **Underlying Architecture**:
  Previous iterations proved this can run **100% natively on bare-metal**. The Unitree G1 humanoid locomanipulation pipeline consists of:
  1. **Kinematics & Dynamics Engine**: `pinocchio` and `pink` (Python inverse kinematics based on Pinocchio).
  2. **QP Optimization Solvers**: `qpsolvers` with `quadprog` or `proxsuite`.
  3. **Locomotion Policy Execution**: `rsl_rl` for low-level walking policy combined with upper-body manipulation.
* **Bare-Metal Resolution**:
  Install the WBC dependencies directly into the `isaaclab` Conda environment:
  ```bash
  conda activate isaaclab
  pip install pin-pink pinocchio qpsolvers quadprog
  cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
  pip install -e source/isaaclab_arena_g1
  ```
  This enables G1 locomanipulation natively with zero Docker overhead and direct Blackwell GPU acceleration.

---

### 3.3 Underlying Issue 3: ZeroMQ IPC Observation Contract & Modality Alignment

* **The Problem**:
  In-process C-extension sharing between Isaac Lab (Python 3.12 / PyTorch 2.10) and GR00T (Python 3.10 / PyTorch 2.9) is impossible due to Python ABI differences.
* **Underlying Architecture**:
  The ZeroMQ IPC bridge acts as a decoupled serialization layer:
  - **Handshake**: Client queries server for `modality.json` (e.g. `OXE_DROID` or `G1_LOCOMANIP`).
  - **Observation Payload**: Client packages camera views (`rgb: [B, C, H, W]`) and joint positions (`state: [B, D]`) into JSON/MsgPack.
  - **Inference**: Server runs 40-step DiT denoising on GPU and returns action chunks (`action: [B, H, action_dim]`).
  - **Receding Horizon**: Simulation executes action step-by-step at 50 Hz.
* **Bare-Metal Resolution**:
  Ensure both the client (`Gr00tRemoteClosedloopPolicy`) and server (`run_gr00t_server.py`) share the identical port (`5555`) and matching embodiment tag (`OXE_DROID` or `g1_wbc_joint`).

---

### 3.4 Underlying Issue 4: Simulation Horizon & Termination Mechanics in Arena

* **The Problem**:
  Running `./bin/isaac-installer arena run cube_goal_pose --steps 100` reported:
  `num_episodes: 0`, `RuntimeWarning: Mean of empty slice`, and `[WARNING] No episode results found`.
* **Underlying Architecture**:
  - `cube_goal_pose` defines `episode_length_s = 20.0s`. At `dt = 0.02s` (50 Hz control loop), one full episode requires **1,000 steps**.
  - Simulating 100 steps represents only **2.0 seconds** (10% of an episode).
  - Under `zero_action`, the robot stays stationary, never reaching the goal (early success termination) and never hitting the 1,000-step timeout.
  - Arena's `EpisodeRecorderManager` computes statistics exclusively on completed episodes (`dones == True`). With 0 completed episodes, NumPy computes the mean of an empty slice, producing `NaN`.
* **Bare-Metal Resolution**:
  - For benchmark evaluation: Run with `--num_steps 1200` to allow episodes to complete and log statistics.
  - For active evaluation: Run with `Gr00tRemoteClosedloopPolicy` or `replay_action` where goal conditions trigger dynamic episode termination.

---

### 3.5 Underlying Issue 5: Classical MuJoCo 1-DoF Joint Assertion in LIBERO

* **The Problem**:
  `assert joint_type in (mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE)` throws `AssertionError` in `robosuite/utils/binding_utils.py:521`.
* **Underlying Architecture**:
  - LIBERO's BDDL kitchen domain XMLs contain floating-base or gripper reference joints (`mjJNT_FREE` or ball joints).
  - `robosuite >= 1.5.0` introduced a strict assertion in `get_joint_qpos_addr` that crashes when traversing non-1DoF joints.
* **Bare-Metal Resolution**:
  Pin `robosuite==1.4.1` and `mujoco==2.3.7` inside `gr00t/eval/sim/LIBERO/libero_uv/.venv`, and execute `robosuite.scripts.setup_macros`.

---

## 4. Targeted Diagnostic & Native Repair Plan

| Layer | Diagnostic Probe | Native Resolution Command | Verification Target |
| :--- | :--- | :--- | :--- |
| **1. Extension Packaging** | `python -c "import isaaclab_arena_gr00t"` in `isaaclab` env | `conda activate isaaclab && pip install -e ~/Documents/GitHub/boredengineering/IsaacLab-Arena/source/isaaclab_arena_gr00t` | `isaaclab_arena_gr00t` imports cleanly with all config YAMLs. |
| **2. Native WBC Stack** | `python -c "import pink, pinocchio, qpsolvers"` in `isaaclab` env | `conda activate isaaclab && pip install pin-pink pinocchio qpsolvers quadprog && pip install -e ~/Documents/GitHub/boredengineering/IsaacLab-Arena/source/isaaclab_arena_g1` | G1 whole-body controller imports natively without Docker. |
| **3. Policy Server Daemon** | Check port 5555 status via `lsof -i :5555` | `cd ~/Documents/GitHub/boredengineering/Isaac-GR00T && uv run python gr00t/eval/run_gr00t_server.py --model-path nvidia/GR00T-N1.6-DROID --embodiment-tag OXE_DROID --device cuda --host 127.0.0.1 --port 5555` | Server binds on `0.0.0.0:5555` and loads DROID weights on GPU. |
| **4. DROID Closed-Loop Rollout** | Launch canonical NVIDIA Arena evaluation | `cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena && python isaaclab_arena/evaluation/policy_runner.py --viz kit --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml --remote_host 127.0.0.1 --remote_port 5555 --language_instruction "Pick up the Rubik's cube and place it in the bowl." --enable_cameras --num_episodes 3 pick_and_place_maple_table --embodiment droid_abs_joint_pos --pick_up_object rubiks_cube_hot3d_robolab --destination_location bowl_ycb_robolab --hdr home_office_robolab` | Robot captures camera views, receives action chunks, and manipulates Rubik's cube. |
| **5. LIBERO MuJoCo Pinning** | Check `pip list` in `libero_uv` | `gr00t/eval/sim/LIBERO/libero_uv/.venv/bin/pip install robosuite==1.4.1 mujoco==2.3.7 && gr00t/eval/sim/LIBERO/libero_uv/.venv/bin/python -m robosuite.scripts.setup_macros` | `gr00t rollout --port 5555 --n-episodes 1` completes episode without assertion crash. |

---

## 5. Architectural Review & Case Study: `boredengineering/IsaacLab-Arena` (Branch `0.2.1-dev`)

A deep inspection of the user's `0.2.1-dev` branch and the `g1_brainco_extension` reveals exactly how complex closed-loop robotics inference was solved in previous implementations.

### 5.1 Analysis of Execution Paradigms: Docker vs ZeroMQ vs In-Process Inference

```mermaid
flowchart TD
    subgraph PARADIGM_A ["Paradigm A: 0.2.1-dev Solution (In-Process Monolithic Inference)"]
        A_ENV["Isaac Lab Simulation Process"]
        A_MODEL["Direct PyTorch / Hugging Face Model (Gr00tClosedloopPolicy)"]
        A_ACTION["G1BraincoWBCAction (Direct Memory Tensor Transfer)"]
        A_ENV <--> A_MODEL <--> A_ACTION
    end

    subgraph PARADIGM_B ["Paradigm B: Upstream 0.3.0-prerelease (Decoupled ZeroMQ IPC)"]
        B_ENV["Arena Process (Python 3.12 / Sim 6.0)"]
        B_SOCK["ZeroMQ REQ/REP Bridge (tcp://127.0.0.1:5555)"]
        B_SRV["GR00T Server Process (Python 3.10 / Cosmos-Reason2)"]
        B_ENV <== "MsgPack / JSON" ==> B_SOCK <== "Tensor Actions" ==> B_SRV
    end

    subgraph PARADIGM_C ["Paradigm C: NVIDIA Default (Heavy Docker Virtualization)"]
        C_DOCKER["Docker Container (run_docker.sh)"]
        C_OVERHEAD["Layer Isolation, GPU Binding Issues, Slow Iteration"]
    end
```

#### 1. Did `0.2.1-dev` Use Docker?
* **No for Simulation Runtime, Yes for Development Tooling**: The simulation and inference ran directly inside the workspace Python environment without spawning nested virtualized Docker containers during execution. A lightweight devcontainer was configured solely to standardize Antigravity MCP tooling and environment variables. The code rejected hardcoded Docker shims (such as synthetic `/isaac-sim/python.sh` paths).

#### 2. Did `0.2.1-dev` Use ZeroMQ?
* **No — It Used Direct In-Process Model Loading (`Gr00tClosedloopPolicy`)**:
  * Upstream Arena 0.3.0 introduced `Gr00tRemoteClosedloopPolicy` which relies on a ZeroMQ socket (`tcp://127.0.0.1:5555`) to communicate with `run_gr00t_server.py`.
  * In contrast, `0.2.1-dev` executed **in-process inference** via `Gr00tClosedloopPolicy`. The Hugging Face `AutoModelForVision2Seq` checkpoint (`checkpoint-20000`) was loaded directly into GPU VRAM in the same process space, calling `self.get_action_chunk(observation)` synchronously.

---

### 5.2 Deep-Dive into `g1_brainco_extension` Documents & Source Files

All documentation and structural artifacts inside `g1_brainco_extension` were reviewed:

#### 1. `g1_brainco_extension/README.md`
* **Custom Embodiment (`G1BraincoCustomEmbodiment`)**:
  * Loads `assets/g1_with_brainco_hands.usd` containing 5-finger Brainco hands.
  * Overrides the `hands` actuator regex to encompass all finger joints: `index`, `middle`, `pinky`, `ring`, and `thumb`.
* **Custom Action Controller (`G1BraincoWBCAction`)**:
  * Solves the dimensional mismatch between the 43-DoF Whole-Body Controller (WBC) and the 50+ DoF physics simulation asset.
  * Slices simulation states to feed only the 43 joints required by the WBC, and maps output targets back to simulation indices.
* **Environment (`G1BraincoPickDrinkEnvironment`)**:
  * Configures high-friction finger contact physics (`static_friction: 6.0`, `dynamic_friction: 5.0`) to secure grasps.
  * Loads `"Oficina CBA Grande"` environment lighting and pre-sets `G1_STATIC_OPEN_ARM_JOINT_POS`.
* **Global Asset Registry (`assets.py`)**:
  * Uses `@register_asset` to register interactive objects (e.g. `CokeCan`, `RedSortingBin`) so they are discoverable globally by the Arena CLI.

#### 2. `g1_brainco_extension/notes.md`
* **Dynamic Tabletop Spawning via `ObjectReference`**:
  * Documents how `isaaclab_arena.assets.object_reference.ObjectReference` acts as an anchor for relational placement:
    ```python
    tabletop_reference = ObjectReference(
        name="table",
        prim_path="{ENV_REGEX_NS}/office_table/Geometry/sm_tabletop_a01_01/sm_tabletop_a01_top_01",
        parent_asset=table_background,
    )
    tabletop_reference.add_relation(IsAnchor())
    ```
* **Robot Constants Architecture**:
  * Segregates physical parameters (`G1_STATIC_FINGER_STATIC_FRICTION`, `G1_STATIC_OPEN_ARM_JOINT_POS`) into `robot_configs.py`.
  * Notes that the WBC dynamically elevates the robot pelvis to $\sim z=0.74\text{m}$ during runtime initialization.

#### 3. `g1_brainco_extension/plan.md`
* **Configuration Path Decoupling**:
  * `modality_config_path` (`g1_sim_wbc_data_config.py`): Multi-modal data layout (camera resolutions, ego view keys).
  * `policy_joints_config_path` (`gr00t_43dof_joint_space.yaml`): Internal neural network 43-DoF sorting order.
  * `state_joints_config_path` & `action_joints_config_path` (`43dof_joint_space.yaml`): Mapping between flat simulation joint arrays and named policy joints.
* **Mimic Coupling Strategy for 5-Finger Hands**:
  * Because the foundation model was trained on a 43-DoF 3-finger configuration, the un-modeled `ring` and `pinky` fingers are dynamically coupled in `G1BraincoWBCAction` to mirror the `middle` finger targets:
    $$\theta_{\text{ring\_0}} = \theta_{\text{middle\_0}}, \quad \theta_{\text{ring\_1}} = \theta_{\text{middle\_1}}$$
    $$\theta_{\text{pinky\_0}} = \theta_{\text{middle\_0}}, \quad \theta_{\text{pinky\_1}} = \theta_{\text{middle\_1}}$$

#### 4. `g1_brainco_extension/my_usdtree_with_arcs.txt`
* Captures the full USD hierarchy generated by `make_tree.py` for `g1_29dof_mode_15_brainco_hand`, detailing prim linkages (`pelvis`, `left_hip_pitch_link`, etc.) and `PhysicsRevoluteJoint` scopes across legs, waist, and Brainco hands.

#### 5. `traceback_output.txt` & Diagnostic Logs
* Documents the 4 fundamental runtime bugs encountered and resolved:
  1. **Projector Weight Index (Index 8 vs Index 10)**: In multi-embodiment checkpoints, `unitree_g1` maps to Index 8 (un-finetuned pre-trained weights) while `new_embodiment` maps to Index 10 (fine-tuned weights). Configuring `embodiment_tag: NEW_EMBODIMENT` is mandatory for fine-tuned checkpoints.
  2. **Action Representation (Relative vs Absolute)**: The WBC requires absolute joint position targets. When the model outputs relative deltas ($\Delta q \approx 0.05\text{ rad}$), `StateActionProcessor.unapply_action` must add the `reference_state` ($q_{\text{current}} + \Delta q$) before passing targets to the controller; otherwise, the WBC receives near-zero angles and the robot violently thrashes.
  3. **Action Chunk Dimension Broadcast**: Resolving `(1, 50, 7)` vs `(30, 7)` buffer broadcasting in `ActionChunkingState`.
  4. **Dedicated Diagnostic Tooling (`tools/`)**: Validating model weights, action timings, and joint ordering using standalone scripts (`check_shape.py`, `debug_arms.py`, `extract_npz.py`, `WBC_RECORD_NPZ=1`).

---

### 5.3 Architectural Synthesis: Comparison of Inference Strategies

| Feature / Dimension | `0.2.1-dev` (User Fork) | Upstream `0.3.0-prerelease` (NVIDIA Standard) | Current Native Bare-Metal Target |
| :--- | :--- | :--- | :--- |
| **Inference Transport** | In-Process Direct PyTorch (`Gr00tClosedloopPolicy`) | Decoupled ZeroMQ Socket (`Gr00tRemoteClosedloopPolicy`) | Dual-Mode: Native ZeroMQ Daemon (Port 5555) + In-Process Option |
| **Embodiment Tagging** | `NEW_EMBODIMENT` (Projector Index 10) | `OXE_DROID` / `UNITREE_G1` | Exact Matching to Checkpoint Architecture |
| **Hand Control** | 5-Finger Mimic Coupling (`middle` $\to$ `ring`/`pinky`) | Standard 3-Finger / 1-DoF Parallel Gripper | Native Coupling in `ActionTerm` |
| **Action Conversion** | Delta $\to$ Absolute via `reference_state` | Configurable per YAML representation | Explicit `StateActionProcessor` Handling |
| **Diagnostics** | Dedicated `tools/` suite + `WBC_RECORD_NPZ=1` | Basic Kit Viewport Logging | Integrated Telemetry + Benchmark Verification |

---

## 6. Pragmatic Dual-Track Roadmap: Docker Baseline to Native Parity

To ensure rapid, guaranteed progress while systematically resolving complex robotics foundation model dependencies, we adopt a **Pragmatic Two-Track Strategy**:

```mermaid
flowchart LR
    subgraph TRACK_1 ["Track 1: Docker-First Baseline (Guaranteed Working Path)"]
        D1["1. Build/Run Container\n(run_docker.sh -g)"]
        D2["2. Run In-Container Sim & GR00T\n(DROID Pick & Place / G1 Brainco)"]
        D3["3. Capture Working Baseline Data\n(Metrics, States, Telemetry)"]
        D1 --> D2 --> D3
    end

    subgraph REVERSE_ENG ["Intermediate: Container Reverse-Engineering & Manifest Extraction"]
        M1["Extract Python Freeze (pip list)"]
        M2["Inspect LD_LIBRARY_PATH & C++ Solvers"]
        M3["Map Vulkan & Offscreen Render Shims"]
        D3 --> M1 & M2 & M3
    end

    subgraph TRACK_2 ["Track 2: Methodical Native Bare-Metal Conversion"]
        N1["Configure Host Conda/UV Runtimes\n(Matching Container Manifests)"]
        N2["Link Native Editable Extensions\n(isaaclab_arena_gr00t & g1)"]
        N3["Validate 100% Parity\n(Zero-Loss Metric Match vs Docker)"]
        M1 & M2 & M3 --> N1 --> N2 --> N3
    end
```

---

### 6.1 Track 1: The Docker-First Baseline (Architecture & Execution)

#### 1. NVIDIA's Built-In Automation Architecture
A critical inspection of NVIDIA's scripts (`docker/run_docker.sh` and `docker/run_gr00t_server.sh`) reveals that they **already automate all container lifecycle management**:
* **Zero Manual Docker Builds**: Automatically detects whether `isaaclab_arena:latest` (or `cuda_gr00t_gn16` with `-g`) exists; if missing, automatically executes `docker build --pull ...`.
* **Zero Manual Docker Exec / Attach**: Checks if a container is already running and auto-attaches; otherwise prunes exited containers and starts a new one.
* **Seamless Command Forwarding (`"$@"` / `"${SERVER_ARGS[@]}"`)**: Options (`-g`, `-d`, `-m`, `-e`) are consumed by `getopts`, and any trailing commands are forwarded directly into the container's entrypoint.
* **Automated User & Graphics Passthrough**:
  - Automatically executes `xhost +local:docker > /dev/null` for X11 rendering.
  - Injects `DOCKER_RUN_USER_ID=$(id -u)` and `DOCKER_RUN_USER_NAME=$(id -un)` so all generated artifacts and logs on the host retain native user ownership (no root lockouts).
  - Mounts host datasets, models, `.cache`, `/tmp/.X11-unix`, and SSL CA certificates.

---

#### 2. Native Command Forwarding Runbook (No Manual Docker Commands)

##### Step 1: Run In-Process Policy Evaluation via `run_docker.sh`
You pass the Python evaluation command directly to `./docker/run_docker.sh` without any `docker exec`:
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_docker.sh -g \
  python isaaclab_arena/evaluation/policy_runner.py \
    --viz headless \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_closedloop_policy.Gr00tClosedloopPolicy \
    --policy_config_yaml_path g1_brainco_extension/policy/config/g1_brainco_static_gr00t_closedloop_config.yaml \
    --language_instruction "Pick up the bottle from the table and place it into the red bin." \
    --enable_cameras \
    --num_episodes 1 \
    g1_static_pick_and_place_drink \
    --embodiment g1_brainco_custom
```

##### Step 2: Run Decoupled ZeroMQ Server + Client via Automated Scripts
*Terminal 1 (Policy Server Daemon):*
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_gr00t_server.sh -m ~/models -- --host 0.0.0.0 --port 5555
```

*Terminal 2 (Simulation Client):*
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_docker.sh -g \
  python isaaclab_arena/evaluation/policy_runner.py \
    --viz kit \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
    --remote_host 127.0.0.1 --remote_port 5555 \
    --language_instruction "Pick up the Rubik's cube and place it in the bowl." \
    --enable_cameras --num_episodes 1 pick_and_place_maple_table \
    --embodiment droid_abs_joint_pos
```

---

### 6.2 Automation in `isaac-installer` CLI

We integrate these automated wrappers directly into `./bin/isaac-installer` so that users and agents interact with a unified interface:

```bash
# 1. Direct pass-through to run_docker.sh via installer
./bin/isaac-installer arena docker -g python isaaclab_arena/evaluation/policy_runner.py --help

# 2. Run benchmark in Docker mode with 1 flag
./bin/isaac-installer arena run cube_goal_pose --docker --steps 300

# 3. Play live 3D visual rollout in Docker mode
./bin/isaac-installer arena play pick_and_place_maple_table --docker --policy gr00t --port 5555

# 4. Launch containerized GR00T policy server
./bin/isaac-installer gr00t server 5555 --docker
```

---

### 6.3 Reverse-Engineering the Working Container to Native Bare-Metal

Once the Docker baseline executes and telemetry is captured, we systematically extract the working environment profile to replicate it natively on bare-metal:

#### 1. Automated Manifest Extraction Procedure
```bash
# 1. Extract complete Python package freeze from container runtime
./docker/run_docker.sh -g python -m pip list --format=freeze > /workspaces/IsaacAutomator/.agents/references/docs/container_pip_freeze.txt

# 2. Extract active environment variables and library paths
./docker/run_docker.sh -g env > /workspaces/IsaacAutomator/.agents/references/docs/container_env.txt

# 3. Extract exact dynamic linker shared object dependencies for WBC solvers
./docker/run_docker.sh -g python -c "
import pinocchio, pink, qpsolvers
print('Pinocchio path:', pinocchio.__file__)
print('Pink path:', pink.__file__)
print('QPSolvers path:', qpsolvers.__file__)
" > /workspaces/IsaacAutomator/.agents/references/docs/container_wbc_manifest.txt
```

#### 2. Native Bare-Metal Replication Blueprint
1. **Synchronize Conda (`isaaclab`) Packages**: Match Python 3.12 wheel versions in Conda to the frozen container requirements.
2. **Inject Scoped Environment Hooks**: Replicate `LD_LIBRARY_PATH`, `PYTHONPATH`, and `VK_ICD_FILENAMES` in `~/miniconda3/envs/isaaclab/etc/conda/activate.d/`.
3. **Link Native Editable Extensions**: Register `source/isaaclab_arena_gr00t`, `source/isaaclab_arena_g1`, and `g1_brainco_extension` natively via `pip install -e`.
4. **Parity Validation**: Execute the same task natively and verify that step times, joint targets, and completion rates match the Docker baseline.

---

## 7. Retrospective Reflection: Lessons Learned from Engineering Attempts 1 & 2

To ensure technical rigor and avoid repeating past antipatterns, we document the root causes and architectural lessons from both previous implementation attempts:

### 7.1 Attempt 1: The Ad-Hoc Execution Antipattern (Black-Box Trial & Error)
* **What We Did**: Attempted to run simulation and policy commands directly (`./bin/isaac-installer gr00t rollout ...`, `arena play ...`) without first establishing and auditing the underlying environment variables, library ABIs, or schema contracts.
* **Why It Failed**:
  1. *MuJoCo / Robosuite Dependency Mismatch*: LIBERO benchmark scripts failed with assertion errors in `robosuite/utils/binding_utils.py` (`assert joint_type in (mjJNT_HINGE, mjJNT_SLIDE)`) because unpinned `robosuite 1.5+` was installed against MuJoCo 3.x, which broke non-1DoF BDDL joint parsing.
  2. *Arena Policy Registry & Dotted Path Contracts*: Invoking Arena scripts with `--policy_type gr00t` failed with `AssertionError: policy_type must be a dotted Python import path` and missing `PolicyCfg` registrations.
  3. *Gated Hugging Face Dependencies*: Downloading `nvidia/GR00T-N1.7-3B` succeeded, but runtime initialization threw `403 Forbidden` because `Cosmos-Reason2-2B` is a separate gated repository requiring independent token acceptance.
* **Core Takeaway**: Attempting to execute complex robotics tasks without explicit, declarative dependency pinning and schema verification creates an endless cycle of trial-and-error debugging.

### 7.2 Attempt 2: CLI Scope Creep & Submodule Collision Antipattern
* **What We Did**: Over-engineered `isaac-installer` by turning it into a heavyweight simulation runner (`arena run`, `arena play`, `gr00t server`, `--docker` flags) and attempting automated in-place git submodule checkout/reset operations on the host.
* **Why It Failed**:
  1. *Violation of Tool Boundary*: `isaac-installer` was designed as an **Environment, Dependency, and Workspace State Provisioner**, NOT a runtime execution wrapper for every simulation script. Adding execution layers added unnecessary indirection and obscured runtime errors.
  2. *Repository Topology Mismatch (Standalone Sibling Repos vs. Nested Submodules)*: The user develops across separate standalone sibling repositories (`~/Documents/GitHub/BoredEngineer/{IsaacAutomator, IsaacSim, IsaacLab, IsaacLab-Arena, Isaac-GR00T}`). NVIDIA's `Dockerfile.isaaclab_arena` assumes physical nested clones (`COPY ./submodules/IsaacLab`). Docker build context cannot follow symlinks pointing outside the repository tree, triggering:
     ```
     ERROR: failed to calculate checksum: "/submodules/IsaacLab": not found
     ```
  3. *Host Git Workspace Intrusion*: Writing scripts that automatically run `git checkout -- submodules/` or delete symlinks risked corrupting active developer branches and duplicating gigabytes of repository data.
* **Core Takeaway**: Keep `isaac-installer` strictly focused on **dependency provisioning, state tracking, and environment configuration**, while runtime execution belongs directly to native development tools (`isaaclab.sh`, `python`, `uv`, `run_docker.sh`).

---

## 8. The Re-Architected Master Plan: Environment Provisioning & State Engine Foundation

This plan re-establishes clear architectural boundaries: `isaac-installer` provisions the system, manages state, and organizes paths, enabling seamless execution both natively and in containers.

```mermaid
flowchart TD
    subgraph INSTALLER_CORE ["1. isaac-installer Architectural Scope (State & Provisioning)"]
        SYS["System Prereqs\n(NVIDIA Drivers, CUDA 12.x, Vulkan ICD, Docker CE, nvidia-ctk)"]
        RUNTIMES["Runtimes & Virtual Envs\n(Conda isaaclab Py3.12, Astral uv, Isaac-GR00T Py3.10)"]
        WEIGHTS["Model Cache Engine\n(nvidia/GR00T-N1.7-3B, Cosmos-Reason2-2B, Local Snapshots)"]
        STATE["Declarative State & Paths (.state.json)\n(Repo Paths, Python Binaries, WBC Shared Objects, Env Hooks)"]
        SYS & RUNTIMES & WEIGHTS --> STATE
    end

    subgraph DUAL_EXECUTION ["2. Dual-Mode Direct Execution (No Installer Wrapper Overkill)"]
        direction TB
        subgraph TRACK_NATIVE ["Native Bare-Metal Direct Execution (Primary Target)"]
            N_POL["Terminal 1: Direct GR00T Policy Server / In-Process\n(uv run python gr00t/eval/run_gr00t_server.py)"]
            N_SIM["Terminal 2: Direct Arena Simulation\n(~/miniconda3/envs/isaaclab/bin/python policy_runner.py)"]
        end
        subgraph TRACK_CONTAINER ["Docker Baseline Execution (Reference Target)"]
            D_POL["Terminal 1: ./docker/run_gr00t_server.sh"]
            D_SIM["Terminal 2: ./docker/run_docker.sh -g python policy_runner.py"]
        end
    end

    STATE ==> TRACK_NATIVE & TRACK_CONTAINER
```

---

### 8.1 Responsibilities of `isaac-installer` (The Provisioning & State Engine)

`isaac-installer` manages the foundational layers so developers never have to manually install drivers, set environment variables, or track missing libraries:

1. **System & Hardware Prerequisites**:
   - Manages NVIDIA GPU drivers, CUDA Toolkit 12.x, Vulkan ICD manifests, Docker CE, and `nvidia-ctk`.
   - Command: `sudo ./bin/isaac-installer dev-tools` / `./bin/isaac-installer audit`
2. **Runtime & Python Environment Provisioning**:
   - Creates and maintains the Conda `isaaclab` environment (Python 3.12) with all Isaac Lab requirements.
   - Sets up Astral `uv` and synchronizes the locked Python 3.10 virtual environment for `Isaac-GR00T`.
   - Command: `./bin/isaac-installer conda` / `./bin/isaac-installer gr00t sync-env`
3. **Whole-Body Controller (WBC) & C++ Kinematic Solvers**:
   - Builds and installs C++ quadratic programming and kinematic solver wheels (`pin-pink`, `pinocchio`, `proxsuite`, `qpsolvers`, `quadprog`) into the native Conda environment.
4. **Declarative State Tracking (`.state.json`)**:
   - Records resolved repository paths (`IsaacAutomator`, `IsaacSim`, `IsaacLab`, `IsaacLab-Arena`, `Isaac-GR00T`), active Python interpreter paths, and submodule commits.
5. **Scoped Environment Activation Hooks**:
   - Generates clean, isolated `etc/conda/activate.d/00_isaaclab_env.sh` hooks that inject:
     - `LD_LIBRARY_PATH`: Dynamic linking for Warp, PhysX, and Pinocchio.
     - `PYTHONPATH`: Seamless discovery of `isaaclab_arena`, `isaaclab_arena_gr00t`, `isaaclab_arena_g1`, and `g1_brainco_extension`.
     - `VK_ICD_FILENAMES`: Proper offscreen Vulkan rendering driver configuration.
6. **Model Weight Caching**:
   - Authenticates Hugging Face credentials and downloads dual model snapshots (`GR00T-N1.7-3B` + `Cosmos-Reason2-2B`).
   - Command: `./bin/isaac-installer gr00t download-weights`

---

### 8.2 Clean Sibling-Repo Solution for Docker Baseline (Option B)

To run NVIDIA's Docker baseline without corrupting standalone sibling repositories:

1. **Keep Standalone Repos Untouched**:
   - Your standalone `~/Documents/GitHub/BoredEngineer/IsaacLab` remains pure and untouched for native development.
2. **Populate In-Tree Submodules Exclusively for Docker Build Context**:
   - Run `git submodule update --init --recursive submodules/IsaacLab` inside `IsaacLab-Arena`. This creates the physical directory required by `Dockerfile.isaaclab_arena:32` (`COPY ./submodules/IsaacLab ...`) without touching your sibling `../IsaacLab` directory.
3. **Execute NVIDIA Container Scripts Directly**:
   ```bash
   cd ~/Documents/GitHub/BoredEngineer/IsaacLab-Arena

   # Launch Policy Server container:
   ./docker/run_gr00t_server.sh -m ~/models -- --host 0.0.0.0 --port 5555

   # Launch Simulation container with live Kit GUI:
   ./docker/run_docker.sh -g \
     python isaaclab_arena/evaluation/policy_runner.py \
       --viz kit \
       --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
       --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
       --remote_host 127.0.0.1 --remote_port 5555 \
       --language_instruction "Pick up the Rubik's cube and place it in the bowl." \
       --enable_cameras --num_episodes 1 pick_and_place_maple_table \
       --embodiment droid_abs_joint_pos
   ```

---

### 8.3 Step-by-Step Native Bare-Metal Direct Execution (Option C)

With dependencies, environment hooks, and state configured by `isaac-installer`, running natively requires no wrappers:

```bash
# ------------------------------------------------------------------------------
# 1. Activate Native Isaac Lab Conda Environment
# ------------------------------------------------------------------------------
conda activate isaaclab

# ------------------------------------------------------------------------------
# 2. Terminal 1: Launch ZeroMQ Policy Server (Native UV Environment)
# ------------------------------------------------------------------------------
cd ~/Documents/GitHub/BoredEngineer/Isaac-GR00T
uv run python gr00t/eval/run_gr00t_server.py \
  --model-path nvidia/GR00T-N1.7-3B \
  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
  --host 127.0.0.1 \
  --port 5555 \
  --device cuda:0

# ------------------------------------------------------------------------------
# 3. Terminal 2: Launch Arena Simulation with Live Kit Viewport (Native Conda)
# ------------------------------------------------------------------------------
cd ~/Documents/GitHub/BoredEngineer/IsaacLab-Arena
python isaaclab_arena/evaluation/policy_runner.py \
  --viz kit \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5555 \
  --language_instruction "Pick up the Rubik's cube and place it in the bowl." \
  --enable_cameras \
  --num_episodes 1 \
  pick_and_place_maple_table \
  --embodiment droid_abs_joint_pos
```

---

## 9. Docker Installation Baseline Path & Submodule Resolution Guide

We are currently pursuing the **Docker-First Baseline Installation Path** to establish confirmed working inference inside NVIDIA's hermetic container environment before converting to native bare-metal.

### 9.1 The Submodule Obstacle & Complete Resolution Procedure

When building the Docker image with `run_docker.sh -g`, `Dockerfile.isaaclab_arena` executes:
```dockerfile
COPY ./submodules/IsaacLab ${WORKDIR}/submodules/IsaacLab
```

#### Symptoms Encountered:
1. `ERROR: failed to calculate checksum ... "/submodules/IsaacLab": not found`
2. `fatal: transport 'file' not allowed`
3. `fatal: 'upstream' does not appear to be a git repository`
4. `fatal: Fetched in submodule path 'submodules/Isaac-GR00T', but it did not contain e29d8fc5... Direct fetching of that commit failed.`

#### Root Causes Diagnosed:
* **Stale/Corrupted Submodule Cache**: Internal configuration files in `.git/modules/submodules/` were referencing invalid remote names (`upstream` as a literal string).
* **Git Protocol Security (CVE-2022-39253)**: Git 2.38+ blocks local relative and file transports by default during submodule commands.
* **Remote Endpoint Alignment**: Submodules must point strictly to official NVIDIA HTTPS endpoints (`https://github.com/isaac-sim/IsaacLab.git` and `https://github.com/NVIDIA/Isaac-GR00T.git`) which contain the exact detached commit SHAs (`ffff603...` and `e29d8fc...`).

#### Step-by-Step Clean Resolution Procedure:
To restore and cleanly synchronize submodules at any time:

```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena

# Step 1: Remove corrupted internal submodule cache and directories
rm -rf .git/modules/submodules
rm -rf submodules/IsaacLab submodules/Isaac-GR00T
git submodule deinit -f --all 2>/dev/null || true

# Step 2: Ensure .gitmodules specifies the official NVIDIA HTTPS endpoints
cat << 'EOF' > .gitmodules
[submodule "submodules/IsaacLab"]
	path = submodules/IsaacLab
	url = https://github.com/isaac-sim/IsaacLab.git
[submodule "submodules/Isaac-GR00T"]
	path = submodules/Isaac-GR00T
	url = https://github.com/NVIDIA/Isaac-GR00T.git
EOF

# Step 3: Enable submodule protocol transport
git config --global protocol.file.allow always

# Step 4: Synchronize remote URLs and checkout exact detached HEADs
git submodule sync
git submodule update --init --recursive

# Step 5: Verify clean detached HEAD status (leading space, no '+' or error)
git submodule status
# Expected output:
#  e29d8fc50b0e4745120ae3fb72447986fe638aa6 submodules/Isaac-GR00T (n1.5-release-11-ge29d8fc)
#  ffff603eafc6b74264a5261cc0183d6a65390d78 submodules/IsaacLab (perf-2026-06-24-10-gffff603ea)
```

---

### 9.2 Code Inventory: All Lines in `isaac-installer` Handling `arena docker`

The following files and line numbers in `isaac-installer` implement the Docker automation and submodule health checks:

| File Path | Line Range | Purpose & Functionality |
| :--- | :--- | :--- |
| [`.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh#L23-L38) | Lines 23–38 | `ensure_docker_submodules()` helper function ensuring `submodules/IsaacLab` is populated with real repository files before Docker builds. |
| [`.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh#L482-L525) | Lines 482–525 | `play)` command `--docker` flag handling: auto-runs `run_docker.sh -g python scripts/play.py --viz kit`. |
| [`.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh#L526-L570) | Lines 526–570 | `run)` command `--docker` flag handling: auto-runs `run_docker.sh -g python scripts/play.py --headless`. |
| [`.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh#L571-L715) | Lines 571–715 | `eval-gr00t)` command `--docker` flag handling: auto-runs `run_docker.sh -g python policy_runner.py`. |
| [`.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh#L725-L740) | Lines 725–740 | `docker)` subcommand: Direct CLI passthrough executing `./docker/run_docker.sh` with `printf '%q '` escaping. |
| [`.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/isaaclab_arena.sh#L742-L770) | Lines 742–770 | `extract-container-manifest)` command: Automated dump of `container_pip_freeze.txt`, `container_env.txt`, and `container_wbc_manifest.txt`. |
| [`.agents/references/isaac-installer/lib/modules/gr00t.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/gr00t.sh#L354-L415) | Lines 354–415 | `server)` command `--docker` flag handling: Launches containerized policy server via `./docker/run_gr00t_server.sh`. |
| [`.agents/references/isaac-installer/lib/modules/dev_tools.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/modules/dev_tools.sh#L104-L135) | Lines 104–135 | Host Docker CE installation, user group addition (`usermod -aG docker`), and NVIDIA Container Toolkit configuration (`nvidia-ctk runtime configure`). |
| [`.agents/references/isaac-installer/lib/core/audit.sh`](file:///workspaces/IsaacAutomator/.agents/references/isaac-installer/lib/core/audit.sh#L153-L170) | Lines 153–170 | Hardware audit inspecting Docker daemon status and GPU passthrough capability (`nvidia-ctk`). |

---

### 9.3 Docker Baseline Verification & Test Suite Execution

The Docker container environment built from `docker/Dockerfile.isaaclab_arena` was verified with 100% test pass on the host environment:

#### 1. Three-Tier Test Suite Commands:
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena

# Tier 1: Fast Physics & Logic (No Cameras, No Subprocesses) - VERIFIED PASSED (18/18)
./docker/run_docker.sh pytest -sv -m "not with_cameras and not with_subprocess" isaaclab_arena/tests/

# Tier 2: Camera & Vision Rendering (Requires Vulkan/RTX GPU Offscreen Pipeline) - VERIFIED PASSED (808/808)
./docker/run_docker.sh pytest -sv -m "with_cameras and not with_subprocess" isaaclab_arena/tests/

# Tier 3: Multi-Process Subsystems & Policy IPC - VERIFIED PASSED (43/43)
./docker/run_docker.sh pytest -sv -m with_subprocess isaaclab_arena/tests/
```

#### 2. Verified Test Results (100% Pass Across All 869 Tests):
* **Tier 1 (Physics & Logic)**:
  ```text
  ================ 18 passed, 854 deselected, 7594 warnings in 403.61s (0:06:43) ================
  Closing persistent simulation app. Tests failed: False
  ```
* **Tier 2 (Vision & Camera Rendering)**:
  ```text
  ================ 808 passed, 3 skipped, 61 deselected, 2245 warnings in 890.97s (0:14:50) ================
  Closing persistent simulation app. Tests failed: False
  ```
* **Tier 3 (Multi-Process Subsystems & Policy IPC)**:
  ```text
  ================ 43 passed, 829 deselected, 95 warnings in 954.69s (0:15:54) ================
  [IsaacLab Arena] ~tarfy /workspaces/isaaclab_arena $
  ```
* **Overall Test Suite Total**: **869 Passed, 3 Skipped, 0 Failed (100% Success Rate)**.

#### 3. Host Volume Mount Contract:
* **Live Code Sync**: `.:/workspaces/isaaclab_arena` (Live host code changes reflected immediately in container).
* **Cache Persistence**: `$HOME/.cache` -> `/home/<user>/.cache` (Hugging Face weights and pip wheels preserved).
* **Optional Data Mounts**: `$HOME/datasets` -> `/datasets`, `$HOME/models` -> `/models`, `$HOME/eval` -> `/eval` (safely skipped if directories do not exist).

---

### 9.4 Container Manifest Extraction & Ground Truth Analysis (Verified)

The container manifest extraction protocol was executed on the working reference container (`isaaclab_arena:latest`), capturing ground-truth configuration in [`.agents/references/docs/`](file:///workspaces/IsaacAutomator/.agents/references/docs/):

#### 1. Extracted Manifest Files Summary:
* [`container_wbc_manifest.txt`](file:///workspaces/IsaacAutomator/.agents/references/docs/container_wbc_manifest.txt): C++ Kinematic and QP solver module paths.
* [`container_env.txt`](file:///workspaces/IsaacAutomator/.agents/references/docs/container_env.txt): Active environment variables, Vulkan driver paths, and Omniverse hub parameters.
* [`container_pip_freeze.txt`](file:///workspaces/IsaacAutomator/.agents/references/docs/container_pip_freeze.txt): Full freeze of all 363 Python 3.12 wheel packages.

#### 2. Ground-Truth Findings & Analysis:
* **C++ Whole-Body Controller (WBC) Solver Stack**:
  - **Pinocchio**: Packaged via `cmeel` binary wheels (`libpinocchio==4.1.0`, `eigenpy==3.13.0`, `coal==3.0.3`, `cmeel-boost==1.90.0`, `cmeel-urdfdom==6.0.0`, `cmeel-assimp==6.0.5`, `cmeel-tinyxml2==11.0.0`, `cmeel-zlib==1.3.2`).
  - **Pink IK Solver**: Installed as `pin-pink==3.1.0`.
  - **QP Solvers**: `qpsolvers==4.13.0` backed by `daqp==0.8.5`.
* **Robotics & Kinematics**:
  - `cumotion==1.1.0a2`, `dex_retargeting==0.5.0`, `mujoco==3.8.1`, `mujoco-warp==3.8.1`, `warp-lang==1.13.0`.
* **Simulation & Policy Runtimes**:
  - `isaaclab==6.1.14` (Assets `0.3.4`, Mimic `1.3.3`, Newton `0.13.6`, OVPhysX `3.0.2`, PhysX `1.1.3`, RL `0.5.5`, Tasks `1.10.9`, Teleop `0.5.2`, Visualizers `0.1.0`).
  - `isaaclab_arena==0.3.0`.
  - `gr00t==0.1.0`, `torch==2.10.0+cu128`, `torchvision==0.25.0+cu128`, `huggingface_hub==0.36.2`, `einops==0.8.2`.
* **Runtime & Graphics Environment**:
  - `VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json`
  - `NVIDIA_CTK_LIBCUDA_DIR=/usr/lib/x86_64-linux-gnu`
  - `ISAACLAB_PATH=/workspaces/isaaclab_arena/submodules/IsaacLab`

#### 3. Preserved Native Bare-Metal Replication Recipe (For Later Execution):
When transitioning to native bare-metal, apply this exact dependency command in Conda `isaaclab`:
```bash
conda activate isaaclab

# Install CMEEL Pinocchio, Pink, and QP Solvers (exact container parity)
pip install \
  cmeel==0.60.1 \
  cmeel-boost==1.90.0 \
  cmeel-urdfdom==6.0.0 \
  cmeel-assimp==6.0.5 \
  cmeel-console-bridge==1.0.2.3 \
  cmeel-octomap==1.10.0 \
  cmeel-qhull==8.0.2.1 \
  cmeel-tinyxml2==11.0.0 \
  cmeel-zlib==1.3.2 \
  eigenpy==3.13.0 \
  coal==3.0.3 \
  libpinocchio==4.1.0 \
  pin-pink==3.1.0 \
  qpsolvers==4.13.0 \
  daqp==0.8.5 \
  dex_retargeting==0.5.0 \
  cumotion==1.1.0a2
```

---

## 10. Container Operations Runbook for Isaac Lab & IsaacLab-Arena (Active Priority)

This runbook details all operational procedures to run, test, and troubleshoot the containerized Isaac Lab / Arena environment.

### 10.1 Host Environment Prerequisites
Before launching container workloads, ensure:
1. **Host Repository Path**: `cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena`
2. **Submodules Clean**: `git submodule status` shows clean commits for `submodules/IsaacLab` (`ffff603ea`) and `submodules/Isaac-GR00T` (`e29d8fc`).
3. **X11 Display Authorizations**:
   ```bash
   xhost +local:root > /dev/null 2>&1 || true
   xhost +local:docker > /dev/null 2>&1 || true
   ```
4. **GPU Passthrough Validation**:
   ```bash
   ./docker/run_docker.sh nvidia-smi
   ```

---

### 10.2 Interactive Container Shells

#### Option A: Headless Interactive Bash Shell
Use for package inspection, CLI tests, or headless script debugging:
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_docker.sh bash
```

#### Option B: GUI / Vulkan-Enabled Interactive Bash Shell
Use for running scripts with live Omniverse Kit 3D viewports or GUI debugging:
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_docker.sh -g bash
```

Inside the interactive container:
```bash
# Isaac Lab directory inside container:
cd /workspaces/isaaclab_arena/submodules/IsaacLab

# IsaacLab-Arena root:
cd /workspaces/isaaclab_arena
```

---

### 10.3 Running Isaac Lab Standalone Scripts & Demos inside Container

You can forward commands directly to Isaac Lab's standalone scripts through `./docker/run_docker.sh -g`:

```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena

# 1. Bipedal Locomotion Demo:
./docker/run_docker.sh -g python submodules/IsaacLab/source/standalone/demos/bipedal_locomotion.py

# 2. Robotic Arms Demo:
./docker/run_docker.sh -g python submodules/IsaacLab/source/standalone/demos/arms.py

# 3. Markers & Visualization Demo:
./docker/run_docker.sh -g python submodules/IsaacLab/source/standalone/demos/markers.py

# 4. Quadruped / Anymal RL Environment Demo:
./docker/run_docker.sh -g python submodules/IsaacLab/source/standalone/environments/teleoperation/teleop_se3_agent.py --task Isaac-Velocity-Rough-Anymal-C-v0
```

---

### 10.4 Running IsaacLab-Arena & GR00T Policy Inference inside Container

#### Track A: In-Process Closed-Loop Evaluation
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena

./docker/run_docker.sh -g \
  python isaaclab_arena/evaluation/policy_runner.py \
    --viz kit \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_closedloop_policy.Gr00tClosedloopPolicy \
    --policy_config_yaml_path g1_brainco_extension/policy/config/g1_brainco_static_gr00t_closedloop_config.yaml \
    --language_instruction "Pick up the bottle from the table and place it into the red bin." \
    --enable_cameras \
    --num_episodes 1 \
    g1_static_pick_and_place_drink \
    --embodiment g1_brainco_custom
```

#### Track B: Decoupled ZeroMQ Policy Server + Arena Client

**Terminal 1: Containerized Policy Server Daemon**
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_gr00t_server.sh -m ~/models -- --host 0.0.0.0 --port 5555
```

**Terminal 2: Containerized Arena Simulation Client**
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena
./docker/run_docker.sh -g \
  python isaaclab_arena/evaluation/policy_runner.py \
    --viz kit \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
    --remote_host 127.0.0.1 --remote_port 5555 \
    --language_instruction "Pick up the Rubik's cube and place it in the bowl." \
    --enable_cameras --num_episodes 1 pick_and_place_maple_table \
    --embodiment droid_abs_joint_pos
```

---

### 10.5 Container Troubleshooting Guide

| Symptom | Probable Cause | Immediate Resolution |
| :--- | :--- | :--- |
| **`cannot connect to X server :0` or `:1`** | X11 permissions not granted on host | Run on host: `xhost +local:root && xhost +local:docker` |
| **`Vulkan physical device not found`** | Missing NVIDIA Container Toolkit GPU hook | Run with `-g` flag or verify `./docker/run_docker.sh nvidia-smi` |
| **`Permission denied` creating files in workspace** | UID mismatch | `run_docker.sh` auto-injects host UID/GID; ensure files on host are owned by user |
| **`403 Forbidden` on Cosmos/GR00T weights** | Gated model repository on Hugging Face | Accept terms on HF web page and pass token via `HF_TOKEN` |
| **Submodule checksum failure during build** | Stale `.git/modules` cache | Run clean sync: `git submodule sync && git submodule update --init --recursive` |

---

### 10.6 Host Volume Mount Persistence & G1 Loco-Manipulation Setup

NVIDIA's `docker/run_docker.sh` checks for the presence of host directories before mounting:
* `$HOME/datasets` $\rightarrow$ `/datasets`
* `$HOME/models` $\rightarrow$ `/models`
* `$HOME/eval` $\rightarrow$ `/eval`

> [!IMPORTANT]
> If these directories do not exist on the host **prior** to running `run_docker.sh`, Docker skips mounting them. Creating them on the host first guarantees persistent storage across container rebuilds and ensures correct user ownership.

#### Step 1: Create Persistent Host Directories (Run on Host)
```bash
# Create base volume mount roots with tutorial subdirectories on host:
mkdir -p ~/datasets/isaaclab_arena/locomanipulation_tutorial
mkdir -p ~/models/isaaclab_arena/locomanipulation_tutorial
mkdir -p ~/eval/isaaclab_arena/locomanipulation_tutorial
```

#### Step 2: Verify Volume Mount Binding Inside Container
Execute this verification command to confirm bidirectional persistence and write permissions:
```bash
cd ~/Documents/GitHub/boredengineering/IsaacLab-Arena

./docker/run_docker.sh bash -c "
  echo '>>> Verifying volume mount bindings...'
  touch /datasets/isaaclab_arena/locomanipulation_tutorial/.mount_verified
  touch /models/isaaclab_arena/locomanipulation_tutorial/.mount_verified
  touch /eval/isaaclab_arena/locomanipulation_tutorial/.mount_verified
  ls -ld /datasets /models /eval
  echo '>>> Volume mounts successfully verified!'
"
```

#### Step 3: Configure Tutorial Environment Variables (Inside Container)
When running the G1 loco-manipulation tutorial workflows inside the container:
```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial
export MODELS_DIR=/models/isaaclab_arena/locomanipulation_tutorial
export EVAL_DIR=/eval/isaaclab_arena/locomanipulation_tutorial
```

---

## 11. Deep Architectural Analysis: NVIDIA Blackwell (`sm_120`) Kernel Incompatibility in `Isaac-GR00T`

During Step 5 of the G1 Loco-Manipulation Box Pick & Place evaluation (`policy_runner.py` connecting to `run_gr00t_server.py`), a critical low-level hardware/CUDA runtime incompatibility was diagnosed on the **NVIDIA RTX PRO 6000 Blackwell Workstation Edition**.

### 11.1 Incident Telemetry & Diagnostic Probe Output

During closed-loop policy rollout (`galileo_g1_locomanip_pick_and_place`), the simulation client connected over ZeroMQ to port `5556`, but the policy server failed on its first inference step:

```text
Traceback (most recent call last):
  File "/workspaces/isaaclab_arena/submodules/Isaac-GR00T/gr00t/policy/server_client.py", line 210, in call_endpoint
    raise RuntimeError(f"Server error: {response['error']}")
RuntimeError: Server error: CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
For debugging consider passing CUDA_LAUNCH_BLOCKING=1
Compile with `TORCH_USE_CUDA_DSA` to enable device-side assertions.
```

#### Diagnostic Audit Results (from `submodules/Isaac-GR00T` via `uv run python`):
```text
================================================================
            ISAAC-GR00T PYTORCH & HARDWARE AUDIT                
================================================================
1. PyTorch Version:         2.7.1+cu126
2. Bundled CUDA Version:    12.6
3. Active GPU Device:       NVIDIA RTX PRO 6000 Blackwell Workstation Edition
4. Hardware Capability:     SM (12, 0)
5. Compiled Architectures:  ['sm_50', 'sm_60', 'sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_90']

--- Sensitive C-Extension Inventory ---
  ✓ flash_attn     : 2.7.4.post1
  - xformers       : Not installed / Not imported
  ✓ triton         : 3.3.1
  ✓ deepspeed      : 0.17.6
  ✓ transformers   : 4.51.3
  ✓ accelerate     : 1.14.0
================================================================
UserWarning: 
NVIDIA RTX PRO 6000 Blackwell Workstation Edition with CUDA capability sm_120 is not compatible with the current PyTorch installation.
The current PyTorch install supports CUDA capabilities sm_50 sm_60 sm_70 sm_75 sm_80 sm_86 sm_90.
```

---

### 11.2 Empirical Runtime Tests & Findings

1. **Test A: Runtime Flag Bypass (`TORCH_SDPA_USE_FLASH=0 CUDA_FORCE_PTX_JIT=1`)**:
   - **Hypothesis**: Bypassing fused `flash_attn` kernels might allow standard PyTorch Scaled Dot-Product Attention (math/mem-efficient) to JIT-compile via driver PTX.
   - **Result**: **FAILED**. Threw `CUDA error: no kernel image is available for execution on the device`.
   - **Finding**: PyTorch's core CUDA kernels in `cu126` (e.g. `torch.embedding`, linear layers, GEMM) lack intermediate PTX targeting `sm_120`.

2. **Test B: Basic Tensor Compute Probe (`torch.randn(1, 1024, device='cuda')`)**:
   - **Test Code**:
     ```python
     import torch
     x = torch.randn(1, 1024, device='cuda')
     w = torch.randn(1024, 1024, device='cuda')
     y = torch.matmul(x, w)
     ```
   - **Result**: **FAILED** immediately on line `x = torch.randn(...)`:
     ```text
     RuntimeError: CUDA error: no kernel image is available for execution on the device
     ```
   - **Finding**: The incompatibility is not restricted to transformer/attention layers. **Zero CUDA operations** (even basic random tensor memory allocations) can execute under `torch==2.7.1+cu126` on an NVIDIA RTX PRO 6000 Blackwell (`sm_120`).

3. **Test C: Astral `uv run` Declarative Lockfile Enforcement**:
   - When attempting manual pip installations inside `.venv`, running `uv run python ...` triggers:
     ```text
     Uninstalled 20 packages in 74ms
     Installed 20 packages in 55ms
     PyTorch Version: 2.7.1+cu126
     ```
   - **Finding**: `uv run` strictly enforces `uv.lock`. Any manual environment modifications outside `uv lock / uv sync` are automatically rolled back to preserve the repository's locked dependency tree.

4. **Test D: Environment Decoupling Verification**:
   - **Finding**: `IsaacLab-Arena` (in Docker) runs on `torch==2.10.0+cu128` (CUDA 12.8) and has **zero issues on Blackwell** (100% test pass across 869 tests).
   - The failure is isolated strictly to the **`Isaac-GR00T` policy server Python 3.10 virtual environment**.

---

### 11.3 4-Layer Bottleneck Breakdown

```mermaid
flowchart TD
    L1["1. Hardware Layer: NVIDIA RTX PRO 6000 Blackwell\n• Requires SM 12.0 (sm_120) SASS instruction set"]
    L2["2. Driver Layer: NVIDIA Driver 595.84 (CUDA 13.2 capable)\n• NOT the bottleneck — recognizes card & supports CUDA 13.x"]
    L3["3. PyTorch Binary fatbin Layer: PyTorch 2.7.1+cu126\n• BOTTLENECK 1: Only contains machine code for sm_50..sm_90\n• Lacks sm_120 native SASS (introduced in CUDA 12.8+)"]
    L4["4. C-Extension Ecosystem Layer: flash_attn, triton, deepspeed\n• BOTTLENECK 2: Compiled against specific PyTorch C++ ABI\n• Unpinned / nightly updates risk breaking downstream symbols"]

    L1 <==> L2 <==> L3 <==> L4
```

| Layer | Component | Status & Technical Detail |
| :--- | :--- | :--- |
| **Hardware** | NVIDIA RTX PRO 6000 Blackwell | Requires Compute Capability `sm_120` (SM 12.0). |
| **Host Driver** | Driver 595.84 | Fully supports CUDA 13.2 and Blackwell architecture (Passes `nvidia-smi`). |
| **PyTorch Wheel** | `torch==2.7.1+cu126` | Compiled with CUDA 12.6. `fatbin` stops at `sm_90` (Hopper). Missing `sm_120`. |
| **C-Extensions** | `flash_attn 2.7.4`, `triton 3.3.1` | Pinned to Python 3.10 and PyTorch 2.7 C++ ABI; sensitive to arbitrary wheel replacements. |

---

### 11.4 NVIDIA Forum & Community Consultation Agenda

To ensure a production-grade, non-breaking resolution aligned with official NVIDIA engineering standards, the following technical items are slated for consultation with NVIDIA forums and community engineers:

1. **Official Blackwell Wheel Matrix for Python 3.10**:
   - What is NVIDIA's recommended PyTorch build targeting `cu128` that maintains 100% C++ ABI compatibility with `transformers 4.51.x`, `flash_attn 2.7.x`, and `triton 3.3.x` on Python 3.10?
2. **FlashAttention Source Compilation on `sm_120`**:
   - If rebuilding `flash_attn` from source on Blackwell workstations, what exact `TORCH_CUDA_ARCH_LIST` flags (e.g. `TORCH_CUDA_ARCH_LIST="12.0;12.0+PTX"`) and NVCC compiler flags are supported by the `Dao-AILab/flash-attention` release?
3. **Dedicated NGC GR00T Container Availability**:
   - Does NVIDIA ship an official container image (e.g., `nvcr.io/nvidian/gr00t1_6_arena_ci` or `cuda_gr00t_gn16`) that pre-packages the CUDA 12.8 / Blackwell-compatible policy server stack with all foundation model dependencies pre-compiled?

### 11.5 Verified Solution: Explicit `pytorch-cu128` Index Routing in `pyproject.toml`

The incompatibility was **100% resolved** without breaking any pinned dependencies by adding an explicit `pytorch-cu128` source index to `submodules/Isaac-GR00T/pyproject.toml`:

```toml
[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu128" }]
torchvision = [{ index = "pytorch-cu128" }]
```

#### Verification Probe Output (100% Success):
```text
1. PyTorch Version:         2.7.1+cu128
2. Bundled CUDA Version:    12.8
3. Compiled Architectures:  ['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120', 'compute_120']
4. Testing Blackwell compute...
✓ Blackwell GPU Compute Test: SUCCESS! Shape: torch.Size([1, 1024])
```

* **Outcome**: PyTorch retains exact pinned version `2.7.1` on Python 3.10, but the underlying CUDA binary now natively includes **`sm_120` and `sm_100`**, enabling GPU tensor computation and policy inference on the NVIDIA RTX PRO 6000 Blackwell workstation with zero runtime warnings.

---

### ⚓ Master Baseline & Active Goal Anchor

* **Active Working Mode**: **Track 1: Docker Container Baseline Execution**
* **Primary Target**: Getting Isaac Lab / IsaacLab-Arena container running smoothly on host.
* **Secondary Target (Deferred)**: Replicating container manifests to native Conda `isaaclab` environment.
* **Active Benchmark**: Unitree G1 Loco-Manipulation Box Pick & Place Workflow.
* **Active Status**: GR00T Policy Server running natively on Blackwell GPU (`sm_120` via `cu128`).


