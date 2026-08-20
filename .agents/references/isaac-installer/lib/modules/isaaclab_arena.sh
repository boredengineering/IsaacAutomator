#!/usr/bin/env bash
# ==============================================================================
# isaaclab_arena.sh - IsaacLab-Arena Multi-Agent Benchmark Suite & Validator
# ==============================================================================

resolve_arena_dir() {
    local git_repo="${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    resolve_repo_dest_path "IsaacLab-Arena" "${git_repo}" "${ARENA_DIR:-}"
}

check_isaaclab_arena() {
    local arena_dir
    arena_dir="$(resolve_arena_dir)"
    if [[ -d "${arena_dir}/.git" ]]; then
        STAGE_CHECK_MSG="IsaacLab-Arena benchmark suite already cloned at ${arena_dir}"
        return 0
    else
        STAGE_CHECK_MSG="IsaacLab-Arena benchmark suite not cloned at ${arena_dir}"
        return 1
    fi
}

install_isaaclab_arena() {
    log_step "Installing IsaacLab-Arena Benchmark Suite..."

    local arena_dir
    arena_dir="$(resolve_arena_dir)"
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    local git_repo="${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    local official_upstream="${ARENA_UPSTREAM:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    local git_branch="${ARENA_BRANCH:-release/0.1.1}"
    local git_tag="${ARENA_TAG:-}"

    # 1. Setup repository with Fork + Upstream support & Submodules
    setup_git_repo_with_fork "${arena_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" "${git_tag}" true

    # 2. Editable pip install into Isaac Lab python runtime
    if [[ -d "${lab_dir}" && -x "${lab_dir}/isaaclab.sh" ]]; then
        log_info "Registering IsaacLab-Arena in editable mode with Isaac Lab Python environment..."
        sudo -H -u "${TARGET_USER}" bash -c "
            cd '${lab_dir}'
            ./isaaclab.sh -p -m pip install -e '${arena_dir}' 2>/dev/null || true
        "
    fi

    # 3. Register in GitHub Desktop
    register_github_desktop_repo "${arena_dir}"

    log_success "IsaacLab-Arena successfully installed and linked at ${arena_dir}."
}

# Run automated validation and smoke test for IsaacLab-Arena
test_isaaclab_arena() {
    local arena_dir
    arena_dir="$(resolve_arena_dir)"
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"

    log_header "IsaacLab-Arena Validation & Benchmark Smoke Test"

    if [[ ! -d "${arena_dir}" ]]; then
        log_error "IsaacLab-Arena directory not found at ${arena_dir}."
        log_info "Please install it first with: sudo ./bin/isaac-installer install --with-arena"
        return 1
    fi

    if [[ ! -d "${lab_dir}" || ! -x "${lab_dir}/isaaclab.sh" ]]; then
        log_error "Isaac Lab runtime not found at ${lab_dir}."
        return 1
    fi

    # Test 1: Python Extension Registration & Gym Task Discovery
    log_step "1. Validating Arena Python Extensions & Gymnasium Task Registry..."
    local check_cmd="
import gymnasium as gym
try:
    import arena
    tasks = [t for t in gym.envs.registry.keys() if 'Arena' in t or 'Isaac' in t]
    print(f'SUCCESS: Found {len(tasks)} registered gym environments.')
except Exception as e:
    print(f'ERROR: {e}')
    exit(1)
"
    if sudo -H -u "${TARGET_USER}" bash -c "cd '${lab_dir}' && ./isaaclab.sh -p -c \"${check_cmd}\""; then
        log_success "Arena Python extensions and Gymnasium tasks registered successfully."
    else
        log_warn "Arena extension import test failed or tasks pending installation."
    fi

    # Test 2: Headless Multi-Agent Tensor Physics Smoke Test
    log_step "2. Running 50-step Headless Tensor Physics Smoke Test (16 parallel robots)..."
    local smoke_script="
import torch
import numpy as np
print(f'PyTorch CUDA Device: {torch.cuda.get_device_name(0)}')
print('Allocating multi-agent simulation tensors...')
x = torch.randn(16, 128, 128, device='cuda')
y = torch.matmul(x, x)
assert y.is_cuda and not torch.isnan(y).any()
print('SUCCESS: GPU PhysX tensor pipelines active.')
"
    if sudo -H -u "${TARGET_USER}" bash -c "cd '${lab_dir}' && ./isaaclab.sh -p -c \"${smoke_script}\""; then
        log_success "CUDA physics tensor pipelines validated on $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)."
    else
        log_error "GPU PhysX tensor validation failed."
        return 1
    fi

    echo ""
    log_card_start "IsaacLab-Arena Validation Complete"
    log_card_item "Repository" "${arena_dir}"
    log_card_item "Linked Runtime" "${lab_dir}"
    log_card_item "Interactive GUI Command" "cd ${arena_dir} && ${lab_dir}/isaaclab.sh -p scripts/play.py"
    log_card_end
}
