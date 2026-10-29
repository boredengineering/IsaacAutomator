# Model Profiles (`configs/models/`)

Declarative model profiles specify machine learning foundation models, policies, and checkpoints to download, verify, and link on workstations.

## Directory Structure

```
configs/
├── profiles/      # Layer 1: Infrastructure & Cloud (where it runs)
├── workstations/  # Layer 2: Simulators, OS, & Devtools (what tools run)
└── models/        # Layer 3: Model Weights & Checkpoints (what weights it loads)
```

## Schema Reference

Each model profile is a YAML file:

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

## Available Presets

- `experiment-05-zoo.yaml`: Complete Experiment 05 Master Model Zoo (all 17 models across Roles 1, 2, and 3; ~1,038 GB).
- `exp05-spec-llms.yaml`: Exp 05 Role 1 — Cognitive Specification Synthesizers (Qwen2.5/Qwen3/QwQ/DeepSeek-R1 on Port 8000 `arena-vllm-spec` + GLM-5.3/Flash on Colibrì; ~891 GB).
- `exp05-visual-critics.yaml`: Exp 05 Role 2 — Visual Critics, World Models & Geometric Oracles (`Cosmos-Reason2-2B`, `Qwen2.5-VL-7B-Instruct`, `Qwen3-VL-32B-Thinking`, `DA3METRIC-LARGE`, `moge-2-vitl` on Ports 8001/8002; ~97 GB).
- `gr00t-foundation.yaml`: Exp 05 Role 3 — Closed-Loop Foundation Robotics Policies (`GR00T-N1.7-3B`, `GR00T-N1.6-DROID`, `Cosmos-Reason2-2B` VLM backbone, and OpenPI `pi05_droid_jointpos` on Ports 5556/8008; ~58 GB).
- `colibri-flash.yaml`: GLM-5.3-Flash 321B MoE multimodal weights (~182 GB) for Colibri runtime.
- `colibri-streaming.yaml`: Full multi-shard layout (`GLM-5.3-Flash` + `GLM-5.3`) for dual-NVMe bare-metal hosts or cloud high-throughput storage (~630 GB).
- `example-model.yaml`: Minimal reference template.

## CLI Usage

Inspect model profiles:
```bash
./isaac9s models list
```

Download models onto a running workstation:
```bash
./download-models studio-workstation --profile colibri-flash
./download-models studio-workstation --profile colibri-flash --dry-run
```
