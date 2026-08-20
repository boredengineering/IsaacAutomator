#!/usr/bin/env bash
# ==============================================================================
# isaaclab_arena.sh - IsaacLab-Arena Multi-Agent Benchmark Suite Installation
# ==============================================================================

resolve_arena_dir() {
    if [[ -n "${ARENA_DIR:-}" ]]; then
        echo "${ARENA_DIR}"
        return 0
    fi

    # Check for existing clone
    local existing
    if existing="$(find_existing_repo "IsaacLab-Arena")"; then
        echo "$existing"
        return 0
    fi

    # Default to workspace root
    local ws_base
    ws_base="$(resolve_default_workspace_dir)"
    echo "${ws_base}/IsaacLab-Arena"
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
    local git_repo="${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    local official_upstream="https://github.com/isaac-sim/IsaacLab-Arena.git"
    local git_branch="${ARENA_BRANCH:-release/0.1.1}"

    if check_isaaclab_arena; then
        log_success "${STAGE_CHECK_MSG}."
        register_github_desktop_repo "${arena_dir}"
        return 0
    fi

    # 1. Setup repository with Fork + Upstream support & Submodules
    setup_git_repo_with_fork "${arena_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" true

    # 2. Register in GitHub Desktop
    register_github_desktop_repo "${arena_dir}"

    log_success "IsaacLab-Arena successfully installed at ${arena_dir}."
}
