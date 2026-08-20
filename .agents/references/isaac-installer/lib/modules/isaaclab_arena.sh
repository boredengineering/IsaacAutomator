#!/usr/bin/env bash
# ==============================================================================
# isaaclab_arena.sh - IsaacLab-Arena Multi-Agent Benchmark Suite Installation
# ==============================================================================

check_isaaclab_arena() {
    local arena_dir="${ARENA_DIR:-${TARGET_HOME}/IsaacLab-Arena}"
    if [[ -d "${arena_dir}/.git" ]]; then
        STAGE_CHECK_MSG="IsaacLab-Arena benchmark suite already cloned at ${arena_dir}"
        return 0
    else
        STAGE_CHECK_MSG="IsaacLab-Arena benchmark suite not cloned"
        return 1
    fi
}

install_isaaclab_arena() {
    log_step "Installing IsaacLab-Arena Benchmark Suite..."

    local arena_dir="${ARENA_DIR:-${TARGET_HOME}/IsaacLab-Arena}"
    local git_repo="${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    local git_branch="${ARENA_BRANCH:-release/0.1.1}"

    if check_isaaclab_arena; then
        log_success "${STAGE_CHECK_MSG}."
        return 0
    fi

    sudo -H -u "${TARGET_USER}" git config --global url."https://github.com/".insteadOf git@github.com: 2>/dev/null || true

    if [[ ! -d "${arena_dir}/.git" ]]; then
        log_info "Cloning IsaacLab-Arena (${git_branch}) with submodules..."
        sudo -H -u "${TARGET_USER}" git clone --depth 1 --recurse-submodules --shallow-submodules \
            -b "${git_branch}" "${git_repo}" "${arena_dir}"
    else
        log_info "IsaacLab-Arena already exists at ${arena_dir}. Updating submodules..."
        sudo -H -u "${TARGET_USER}" bash -c "
            cd '${arena_dir}'
            git submodule update --init --recursive --depth 1
        " 2>/dev/null || true
    fi

    log_success "IsaacLab-Arena successfully installed at ${arena_dir}."
}
