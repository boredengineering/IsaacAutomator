# Issues with the SM120 GPUs

Trying to document here the issues with SM120 GPUS (RTX PRO 6000, RTX 5090, ...), since there are several issues that impact running several torch modules.

### 1. The Hardware Architecture Distinction: sm_100 vs. sm_120

NVIDIA Blackwell GPUs are split into two distinct compute capabilities:

| Architecture Category           | GPU Models                               | Compute Cap…       | Key Characteristics                                                     |
| ------------------------------- | ---------------------------------------- | ------------------ | ----------------------------------------------------------------------- |
| Data Center Blackwell           | NVIDIA B100, B200, GB200                 | sm_100             | Tensor Memory (TMEM), TCGEN05 tensor cores.                             |
| Workstation & Desktop Blackwell | NVIDIA RTX PRO 6000 Blackwell, RTX 5090, | sm_120             | SM 12.0 architecture; lacks data center TMEM but requires native sm_120 |
| RTX 5080                        |                                          | SASS machine code. |
──────

### 2. How the Issue Was Overcome Across the Community



#### Strategy A: Official PyTorch cu128 Index Routing (The Standard Fix)

* **The Root Cause:** PyTorch packages compiled for CUDA ≤12.6 (like ```2.7.1+cu126```) stop their machine code generation at ```sm_90``` (Hopper).
* **The Fix:** PyTorch introduced native ```sm_120 / sm_100``` SASS binary compilation in builds targeting **CUDA 12.8+** (```cu128```).
* **The uv Mechanism:** In projects managed by Astral uv (like Isaac-GR00T), running uv pip install manually does not persist because uv run detects lockfile drift and automatically rolls back to uv.lock.

To resolve this in uv, developers configure the explicit PyTorch CUDA 12.8 index in ```pyproject.toml```:

```toml
[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu128" }]
torchvision = [{ index = "pytorch-cu128" }]
```

Or run without sync: ```uv run --no-sync python ....```

──────

#### Strategy B: Handling flash_attn on sm_120

* **The Issue:** Pre-built wheels for ```flash_attn``` (e.g. ```2.7.4.post1```) on PyPI only contain binaries for Ampere (```sm_80```), Ada (```sm_89```), and Hopper (```sm_90```).
* **Community Workarounds:**
    1. Source Build targeting ```SM120```:
    Developers with CUDA Toolkit 12.8+ compile flash_attn directly from source with the explicit architecture flag:
    
    ```bash
    export TORCH_CUDA_ARCH_LIST="12.0"
    pip install --no-build-isolation -e .
    ```

    2. SDPA Fallback: For inference and deployment, routing transformer layers through PyTorch's native Scaled Dot-Product Attention (sdpa) avoids flash_attn binary dependencies completely.

──────

#### Strategy C: Hermetic Docker Containerization (NVIDIA's Preferred Production Path)

* Because compiling bleeding-edge C-extensions on fresh hardware architectures can lead to host toolchain conflicts, NVIDIA's primary recommendation for robotics is containerizing the entire runtime with CUDA 12.8 base images.
* This is why IsaacLab-Arena's Docker container (isaaclab_arena:latest with torch==2.10.0+cu128) passed 100% of all 869 tests on your RTX PRO 6000 without a single kernel error.

──────

### Summary Checklist for NVIDIA Consultation

1. PyTorch Wheel Target: Ensure the environment pulls from https://download.pytorch.org/whl/cu128 where sm_120 is explicitly listed in torch.cuda.get_arch_list().
2. uv Lockfile Alignment: Update [tool.uv.sources] to point to pytorch-cu128 so uv run does not roll back to cu126.
3. flash_attn Status: Clarify whether NVIDIA GR00T foundation models require custom sm_120 compiled flash_attn wheels or can default to native PyTorch SDPA.
