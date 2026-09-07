#!/usr/bin/env bash
# ==============================================================================
# system_prereqs.sh - Graphics, Vulkan, Compiler Toolchain & Git LFS
# ==============================================================================

check_system_prereqs() {
    if command -v gcc-11 &>/dev/null && command -v git-lfs &>/dev/null && command -v cmake &>/dev/null; then
        if pkg_is_installed "libvulkan-dev" 2>/dev/null; then
            STAGE_CHECK_MSG="GCC 11, CMake, Git LFS and Vulkan dev headers already installed"
            return 0
        fi
    fi
    STAGE_CHECK_MSG="Missing GCC 11, Git LFS, or Vulkan graphics development libraries"
    return 1
}

install_system_prereqs() {
    log_step "Checking System Prereqs, Vulkan Libraries, and Compilers..."

    if check_system_prereqs; then
        log_success "${STAGE_CHECK_MSG}."
        return 0
    fi

    pkg_update

    log_info "Installing core build tools and graphics libraries..."
    pkg_install \
        build-essential \
        cmake \
        git \
        git-lfs \
        curl \
        wget \
        unzip \
        tar \
        gcc-11 \
        g++-11 \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        libvulkan1 \
        libvulkan-dev \
        vulkan-tools \
        libgl1-mesa-dev \
        libglu1-mesa-dev \
        libx11-dev \
        libxcursor-dev \
        libxrandr-dev \
        libxinerama-dev \
        libxi-dev \
        libxkbcommon-dev \
        xserver-xorg

    # Set GCC 11 and G++ 11 as default compiler alternatives (Required for Omniverse C++)
    log_info "Configuring GCC 11 and G++ 11 as default system compilers..."
    sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 200 2>/dev/null || true
    sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-11 200 2>/dev/null || true

    # Initialize Git LFS for the target user
    log_info "Initializing Git Large File Storage (Git LFS)..."
    sudo -H -u "${TARGET_USER}" git lfs install 2>/dev/null || true

    # Install Node.js LTS for agent tooling and skills if missing
    if ! command -v node &>/dev/null; then
        log_info "Installing Node.js LTS for agent tooling and skills..."
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - 2>/dev/null || true
        pkg_install nodejs || true
    fi

    # Pre-emptively scaffold host workspace and dataset directories
    scaffold_host_workspaces

    if command -v vulkaninfo &>/dev/null; then
        log_success "Vulkan diagnostic tool (vulkaninfo) is available."
    fi

    log_success "System prerequisites, graphics toolchains, and host directories configured."
}

scaffold_host_workspaces() {
    log_info "Pre-emptively scaffolding host storage directories to prevent Docker root permission traps..."
    local user_home="${TARGET_HOME}"
    local user="${TARGET_USER}"

    local dirs=(
        "${user_home}/datasets/isaaclab_arena/locomanipulation_tutorial"
        "${user_home}/datasets/isaaclab_arena/sequential_static_manipulation_tutorial"
        "${user_home}/datasets/isaaclab_arena/static_apple_tutorial"
        "${user_home}/models/isaaclab_arena/locomanipulation_tutorial"
        "${user_home}/models/isaaclab_arena/sequential_static_manipulation_tutorial"
        "${user_home}/models/isaaclab_arena/dexsuite_lift"
        "${user_home}/models/isaaclab_arena/reinforcement_learning"
        "${user_home}/models/isaaclab_arena/static_apple_tutorial"
        "${user_home}/eval/isaaclab_arena/locomanipulation_tutorial"
        "${user_home}/eval/isaaclab_arena/camera_sensitivity"
        "${user_home}/data/neo4j"
        "${user_home}/.cache/huggingface"
        "${user_home}/.aws"
        "${user_home}/.config/gcloud"
        "${user_home}/.azure"
        "${user_home}/.config/gh"
        "${user_home}/.config/osmo"
    )

    for d in "${dirs[@]}"; do
        if [[ ! -d "$d" ]]; then
            sudo -H -u "${user}" mkdir -p "$d" 2>/dev/null || sudo mkdir -p "$d"
        fi
        sudo chown -R "${user}:${user}" "$d" 2>/dev/null || true
    done

    # Ensure user is in docker group if it exists
    if getent group docker >/dev/null; then
        sudo usermod -aG docker "${user}" 2>/dev/null || true
    fi
}
