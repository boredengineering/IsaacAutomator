# Model Profiles (`configs/models/`)

Declarative model profiles specify machine learning foundation models, vision-language-action (VLA) robotics policies, world models, and MoE checkpoints to download, verify, and link on Isaac Workstations.

## Table of Contents

- [Directory Structure](#directory-structure)
- [Available Model Profiles](#available-model-profiles)
- [Master Model Catalog (`complete-model-zoo.yaml`)](#master-model-catalog-complete-model-zooyaml)
  - [1. Cognitive Specification Synthesizers (Port 8000 / GPU 0)](#1-cognitive-specification-synthesizers-port-8000--gpu-0)
  - [2. Visual Critics, World Models & Geometric Oracles (Port 8001 / 8002 / CPU)](#2-visual-critics-world-models--geometric-oracles-port-8001--8002--cpu)
  - [3. Closed-Loop Foundation Robotics Policies (Port 5556 / 8008 / GPU 1)](#3-closed-loop-foundation-robotics-policies-port-5556--8008--gpu-1)
- [Schema Reference](#schema-reference)
- [CLI & TUI Usage](#cli--tui-usage)

---

## Directory Structure

```text
configs/
├── profiles/      # Layer 1: Infrastructure & Cloud (where it runs)
├── workstations/  # Layer 2: Simulators, OS, & Devtools (what tools run)
└── models/        # Layer 3: Model Weights & Checkpoints (what weights it loads)
```

---

## Available Model Profiles

| Profile File | Profile Name | Models | Total Disk Quota | Description & Use Case |
| :--- | :--- | :--- | :--- | :--- |
| [`complete-model-zoo.yaml`](./complete-model-zoo.yaml) | `complete-model-zoo` | 17 | **1,038 GB** | Complete Master Model Zoo across all 3 functional roles (Spec LLMs, Visual/3D Critics, and Closed-Loop Robotics Policies). |
| [`example-model.yaml`](./example-model.yaml) | `example-model` | 1 | **5 GB** | Minimal reference template demonstrating all supported schema fields. |

---

## Master Model Catalog (`complete-model-zoo.yaml`)

### 1. Cognitive Specification Synthesizers (Port 8000 / GPU 0)
Generates finite relational scene graphs, SHACL constraints, and spatial factor coordinates:

| Model Key (`name`) | Upstream Repo (`repo_id`) | Architecture | Serving Engine & Port | Canonical Destination & Symlink | Min Disk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `qwen2.5-72b-instruct-awq` | `Qwen/Qwen2.5-72B-Instruct-AWQ` | 72B Dense Transformer (AWQ) | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/qwen/Qwen2.5-72B-Instruct-AWQ`<br>$\rightarrow$ `/models/Qwen2.5-72B-Instruct-AWQ` | 42 GB |
| `qwen2.5-coder-32b-instruct-awq` | `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` | 32B Code-Specialized (AWQ, 32k/131k YaRN) | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/qwen/Qwen2.5-Coder-32B-Instruct-AWQ`<br>$\rightarrow$ `/models/Qwen2.5-Coder-32B-Instruct-AWQ` | 20 GB |
| `qwq-32b-awq` | `Qwen/QwQ-32B-AWQ` | 32B Reasoning CoT (AWQ) | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/qwen/QwQ-32B-AWQ`<br>$\rightarrow$ `/models/QwQ-32B-AWQ` | 20 GB |
| `deepseek-r1-distill-qwen-32b` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | 32B Distilled RL CoT | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/deepseek/DeepSeek-R1-Distill-Qwen-32B`<br>$\rightarrow$ `/models/DeepSeek-R1-Distill-Qwen-32B` | 66 GB |
| `qwen3-32b-fp8` | `Qwen/Qwen3-32B-FP8` | 32B Dual-Mode Transformer (FP8) | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/qwen/Qwen3-32B-FP8`<br>$\rightarrow$ `/models/Qwen3-32B-FP8` | 35 GB |
| `qwen3-30b-a3b-fp8` | `Qwen/Qwen3-30B-A3B-FP8` | 30B MoE (3B active FP8) | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/qwen/Qwen3-30B-A3B-FP8`<br>$\rightarrow$ `/models/Qwen3-30B-A3B-FP8` | 32 GB |
| `qwen2.5-vl-72b-instruct-awq` | `Qwen/Qwen2.5-VL-72B-Instruct-AWQ` | 72B Omnimodal VLM (AWQ) | vLLM (`arena-vllm-spec`, Port 8000) | `/mnt/models_fast/models/qwen/Qwen2.5-VL-72B-Instruct-AWQ`<br>$\rightarrow$ `/models/Qwen2.5-VL-72B-Instruct-AWQ` | 46 GB |
| `glm-5.3-flash` | `zai-org/GLM-5.3-Flash` | 321B Multimodal MoE (62 shards) | Colibrì Engine (Vulkan DMA) | `/mnt/models_fast/models/glm-5.3-flash`<br>$\rightarrow$ `/models/glm-5.3-flash` | 190 GB |
| `glm-5.3` | `zai-org/GLM-5.3` | 744B MoE (42B active, INT4 gs64, 141 shards) | Colibrì Engine (Vulkan DMA) | `/mnt/models_fast/models/glm-5.3`<br>$\rightarrow$ `/models/glm-5.3` | 440 GB |

### 2. Visual Critics, World Models & Geometric Oracles (Port 8001 / 8002 / CPU)
Evaluates step-0 rendered camera viewports, dynamic physics, and motion manifolds:

| Model Key (`name`) | Upstream Repo (`repo_id`) | Architecture | Serving Engine & Port | Canonical Destination & Symlink | Min Disk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `cosmos-reason2-2b` | `nvidia/Cosmos-Reason2-2B` | 2B Physical AI World Model (V2 Critic & GR00T VLM backbone) | vLLM (`arena-vllm-visual`, Port 8001) | `/mnt/models_fast/models/cosmos/Cosmos-Reason2-2B`<br>$\rightarrow$ `/models/cosmos/Cosmos-Reason2-2B` | 8 GB |
| `qwen2.5-vl-7b-instruct` | `Qwen/Qwen2.5-VL-7B-Instruct` | 7B Multimodal VLM (V1 Scene Critic) | vLLM (`arena-vllm-visual`, Port 8001) | `/mnt/models_fast/models/qwen/Qwen2.5-VL-7B-Instruct`<br>$\rightarrow$ `/models/Qwen2.5-VL-7B-Instruct` | 17 GB |
| `qwen3-vl-32b-thinking` | `Qwen/Qwen3-VL-32B-Thinking` | 32B Visual CoT Critic | vLLM (`arena-vllm-visual`, Port 8001) | `/mnt/models_fast/models/qwen/Qwen3-VL-32B-Thinking`<br>$\rightarrow$ `/models/Qwen3-VL-32B-Thinking` | 66 GB |
| `da3metric-large` | `depth-anything/DA3METRIC-LARGE` | Metric 3D Depth Estimation (V3 Oracle) | In-Tree Daemon (Port 8002, GPU 0) | `/mnt/models_fast/models/geometry/DA3METRIC-LARGE`<br>$\rightarrow$ `/models/DA3METRIC-LARGE` | 3 GB |
| `moge-2-vitl` | `Ruicheng/moge-2-vitl` | Dense Surface Normal & Geometry Oracle (V3) | In-Tree Daemon (Port 8002, GPU 0) | `/mnt/models_fast/models/geometry/moge-2-vitl`<br>$\rightarrow$ `/models/moge-2-vitl` | 3 GB |
| *(Deterministic V0 Oracle)* | *(In-Tree Python + Pixar USD `BBoxCache`)* | Analytical Geometry Collision Check | `verify_articulated_spec.py` (CPU) | *(No external weights required)* | 0 GB |

### 3. Closed-Loop Foundation Robotics Policies (Port 5556 / 8008 / GPU 1)
Downstream policies evaluated across certified scene graphs on Franka DROID and humanoid embodiments:

| Model Key (`name`) | Upstream Repo (`repo_id`) | Architecture | Serving Engine & Port | Canonical Destination & Symlink | Min Disk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `gr00t-n1.7-3b` | `nvidia/GR00T-N1.7-3B` | Flow-Matched Diffusion Transformer (DiT — Policy $\alpha$, 50 Hz Cartesian velocity) | `gr00t-server` (Port 5556, ZeroMQ) | `/mnt/models_fast/models/gr00t/GR00T-N1.7-3B`<br>$\rightarrow$ `/models/gr00t/GR00T-N1.7-3B` | 15 GB |
| `openpi-pi05-droid-jointpos` | `physical-intelligence/pi05_droid_jointpos` | Autoregressive / Flow Hybrid Diffusion (Policy $\beta$ $\pi_{0.5}$, 50 Hz relative jointpos) | `openpi-server` (Port 8008, WebSocket) | `/mnt/models_fast/models/openpi/pi05_droid_jointpos`<br>$\rightarrow$ `/models/openpi/pi05_droid_jointpos` | 20 GB |
| `gr00t-n1.6-droid` | `nvidia/GR00T-N1.6-DROID` | Flow-Matched DiT (Historical baseline control) | `gr00t-server` (Port 5556, ZeroMQ) | `/mnt/models_fast/models/gr00t/GR00T-N1.6-DROID`<br>$\rightarrow$ `/models/gr00t/GR00T-N1.6-DROID` | 15 GB |

---

## Schema Reference

Each model profile is a YAML file adhering to `schema_version: v1`:

```yaml
schema_version: v1
model_profile_name: <string>
description: <string>

defaults:
  provider: huggingface           # huggingface, modelscope, url, s3
  download_engine: hf_transfer    # hf_transfer (Rust fast transfer) or hf_cli
  auth_env: HF_TOKEN             # Target/host env var for authentication token

storage:                         # Optional storage topology & symlinks
  physical_dir: /mnt/models_fast/models
  logical_mounts:
    - target: /models
      link_to: /mnt/models_fast/models
    - target: ~/models
      link_to: /mnt/models_fast/models
    - target: ~/.cache/huggingface
      link_to: /mnt/models_fast/hf_cache

models:
  - name: <string>               # Model identifier
    description: <string>        # Human description
    repo_id: <org/repo>          # Hugging Face or provider repository ID
    repo_type: model             # 'model' or 'dataset'
    revision: main               # Branch, git commit hash, or tag
    destination: <path>          # Target path (supports ~, $HF_HOME, or /models/...)
    symlinks:                    # List of symlinks to establish
      - /models/glm-5.3
    allow_patterns:              # File patterns to include
      - "*.safetensors"
      - "*.json"
    ignore_patterns:             # File patterns to exclude
      - "*.bin"
    min_disk_free_gb: 120        # Pre-flight disk space quota check
```

---

## CLI & TUI Usage

Download or dry-run a model profile onto a running workstation via CLI:

```bash
# Dry-run the complete model zoo plan against a workstation:
./download-models studio-workstation --profile complete-model-zoo --dry-run

# Execute the download plan onto a workstation:
./download-models studio-workstation --profile complete-model-zoo
```

Or manage models interactively in the **`isaac9s`** Terminal Cockpit by pressing **`7`** (or `:models`) to open the **Models & Weights [7]** view.
