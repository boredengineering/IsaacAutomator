#!/usr/bin/env bash
# ==============================================================================
# isaaclab.sh - Isaac Lab Robotics Framework Installation & PyTorch Linkage
# ==============================================================================

resolve_isaaclab_dir() {
    if [[ -n "${ISAACLAB_DIR:-}" ]]; then
        echo "${ISAACLAB_DIR}"
        return 0
    fi

    # Check for existing clone
    local existing
    if existing="$(find_existing_repo "IsaacLab")"; then
        echo "$existing"
        return 0
    fi

    # Default to workspace root
    local ws_base
    ws_base="$(resolve_default_workspace_dir)"
    echo "${ws_base}/IsaacLab"
}

check_isaac_lab() {
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    if [[ -d "${lab_dir}" && -L "${lab_dir}/_isaac_sim" && -x "${lab_dir}/isaaclab.sh" ]]; then
        STAGE_CHECK_MSG="Isaac Lab framework already cloned and linked at ${lab_dir}"
        return 0
    else
        STAGE_CHECK_MSG="Isaac Lab framework not installed or _isaac_sim symlink missing at ${lab_dir}"
        return 1
    fi
}

install_isaac_lab() {
    log_step "Checking Isaac Lab Framework Status..."

    local sim_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    local git_repo="${ISAACLAB_REPO:-https://github.com/isaac-sim/IsaacLab.git}"
    local official_upstream="https://github.com/isaac-sim/IsaacLab.git"
    local git_branch="${ISAACLAB_BRANCH:-main}"

    if [[ ! -d "${sim_dir}" ]]; then
        log_fatal "Isaac Sim directory ${sim_dir} not found. Isaac Sim must be installed first."
    fi

    if check_isaac_lab; then
        if sudo -H -u "${TARGET_USER}" bash -c "cd '${lab_dir}' && ./isaaclab.sh -p -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null"; then
            log_success "Isaac Lab is already installed, linked, and verified with PyTorch CUDA."
            register_github_desktop_repo "${lab_dir}"
            return 0
        fi
    fi

    # 1. Setup repository with Fork + Upstream support
    setup_git_repo_with_fork "${lab_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" false

    # 2. Create standard _isaac_sim symlink
    log_info "Linking ${sim_dir} -> ${lab_dir}/_isaac_sim..."
    ln -sfn "${sim_dir}" "${lab_dir}/_isaac_sim"
    chown -h "${TARGET_USER}:${TARGET_USER}" "${lab_dir}/_isaac_sim"

    # 3. Execute Isaac Lab Installer
    log_info "Running ./isaaclab.sh --install (this sets up extension packages and dependencies)..."
    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${lab_dir}'
        ./isaaclab.sh --install
    "

    # 4. Verify PyTorch CUDA Tensors
    log_info "Verifying PyTorch CUDA acceleration in Isaac Lab environment..."
    if sudo -H -u "${TARGET_USER}" bash -c "
        cd '${lab_dir}'
        ./isaaclab.sh -p -c 'import torch; assert torch.cuda.is_available(), \"CUDA unavailable\"; print(\"  ✔ PyTorch CUDA Ready:\", torch.cuda.get_device_name(0))'
    "; then
        log_success "Isaac Lab installation verified successfully."
    else
        log_warn "Isaac Lab PyTorch verification encountered an issue. Check GPU driver / Vulkan status."
    fi

    register_github_desktop_repo "${lab_dir}"
}
