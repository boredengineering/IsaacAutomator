#!/usr/bin/env bash
# ==============================================================================
# physical_ai.sh - Hugging Face LeRobot, Dataset Visualizer & Policy Tools
# ==============================================================================

resolve_lerobot_dir() {
    if [[ -n "${LEROBOT_DIR:-}" ]]; then
        echo "${LEROBOT_DIR}"
        return 0
    fi

    local existing
    if existing="$(find_existing_repo "lerobot")"; then
        echo "$existing"
        return 0
    fi

    local ws_base
    ws_base="$(resolve_default_workspace_dir)"
    echo "${ws_base}/lerobot"
}

check_physical_ai() {
    local missing=()
    (command -v huggingface-cli &>/dev/null || command -v hf &>/dev/null) || missing+=("huggingface-cli")
    command -v lerobot-dataset-viz &>/dev/null || missing+=("lerobot-dataset-viz")
    pkg_is_installed "libavformat-dev" 2>/dev/null || missing+=("FFmpeg video headers")

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Hugging Face CLI (hf), LeRobot dataset visualizer, and FFmpeg video dev libraries already installed"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_physical_ai_stack() {
    log_step "Installing Hugging Face Physical AI Stack (LeRobot & Dataset Visualizer)..."

    local lerobot_dir
    lerobot_dir="$(resolve_lerobot_dir)"
    local git_repo="${LEROBOT_REPO:-https://github.com/huggingface/lerobot.git}"
    local official_upstream="https://github.com/huggingface/lerobot.git"
    local git_branch="${LEROBOT_BRANCH:-main}"

    # 1. Install System Video Codec Libraries (Required for LeRobot & PyAV)
    log_info "Installing FFmpeg development libraries for high-throughput video encoding..."
    pkg_install \
        pkg-config \
        libavformat-dev \
        libavcodec-dev \
        libavdevice-dev \
        libavutil-dev \
        libswscale-dev \
        libswresample-dev \
        libavfilter-dev \
        ffmpeg

    # 2. Create/Configure 'lerobot' Conda Environment with visualization extras
    log_info "Configuring 'lerobot' Python environment with dataset visualization & Rerun.io..."
    sudo -H -u "${TARGET_USER}" bash -c "
        source /opt/conda/etc/profile.d/conda.sh 2>/dev/null || true
        if ! conda info --envs 2>/dev/null | grep -q 'lerobot'; then
            conda create -y -n lerobot python=3.10
        fi
        
        # Install LeRobot with dataset_viz, dynamixel, and rerun support
        conda run -n lerobot pip install --upgrade pip
        conda run -n lerobot pip install 'lerobot[all,dataset_viz]' rerun-sdk huggingface_hub[cli] opencv-python
    "

    # 3. Create global symlink or wrapper for 'lerobot-dataset-viz' and 'huggingface-cli'
    cat << 'VIZ' | sudo tee /usr/local/bin/lerobot-dataset-viz >/dev/null
#!/usr/bin/env bash
source /opt/conda/etc/profile.d/conda.sh 2>/dev/null || true
if conda info --envs 2>/dev/null | grep -q 'lerobot'; then
    exec conda run -n lerobot lerobot-dataset-viz "$@"
else
    exec python3 -m lerobot.scripts.visualize_dataset "$@"
fi
VIZ
    sudo chmod 0755 /usr/local/bin/lerobot-dataset-viz

    cat << 'HFCLI' | sudo tee /usr/local/bin/huggingface-cli >/dev/null
#!/usr/bin/env bash
source /opt/conda/etc/profile.d/conda.sh 2>/dev/null || true
if conda info --envs 2>/dev/null | grep -q 'lerobot'; then
    exec conda run -n lerobot huggingface-cli "$@"
elif command -v pip3 &>/dev/null; then
    exec python3 -m huggingface_hub.cli.core "$@"
else
    echo "huggingface-cli requires Python/Conda environment." >&2
    exit 1
fi
HFCLI
    sudo chmod 0755 /usr/local/bin/huggingface-cli

    sudo ln -sf /usr/local/bin/huggingface-cli /usr/local/bin/hf 2>/dev/null || true

    if command -v pip3 &>/dev/null; then
        sudo pip3 install --upgrade "huggingface_hub[cli]" 2>/dev/null || true
    fi

    # 4. Setup LeRobot Git repository with Fork + Upstream support
    setup_git_repo_with_fork "${lerobot_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" false

    # 5. Install editable package
    sudo -H -u "${TARGET_USER}" bash -c "
        source /opt/conda/etc/profile.d/conda.sh 2>/dev/null || true
        if conda info --envs 2>/dev/null | grep -q 'lerobot'; then
            conda run -n lerobot --cwd '${lerobot_dir}' pip install -e '.[all,dataset_viz]' 2>/dev/null || true
        fi
    "

    # 6. Register in GitHub Desktop
    register_github_desktop_repo "${lerobot_dir}"

    log_success "Hugging Face LeRobot, huggingface-cli (hf) & lerobot-dataset-viz ready in PATH."
}
