#!/usr/bin/env bash
# ==============================================================================
# physical_ai.sh - Hugging Face LeRobot, Dataset Visualizer & Policy Tools
# ==============================================================================

check_physical_ai() {
    if command -v lerobot-dataset-viz &>/dev/null && pkg_is_installed "libavformat-dev" 2>/dev/null; then
        STAGE_CHECK_MSG="LeRobot dataset visualizer and FFmpeg dev libraries already installed"
        return 0
    else
        STAGE_CHECK_MSG="Missing LeRobot dataset visualizer or FFmpeg video development libraries"
        return 1
    fi
}

install_physical_ai_stack() {
    log_step "Installing Hugging Face Physical AI Stack (LeRobot & Dataset Visualizer)..."

    local lerobot_dir="${TARGET_HOME}/lerobot"

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

    # 3. Create global symlink or wrapper for 'lerobot-dataset-viz'
    cat << 'VIZ' | sudo tee /usr/local/bin/lerobot-dataset-viz >/dev/null
#!/usr/bin/env bash
source /opt/conda/etc/profile.d/conda.sh
exec conda run -n lerobot lerobot-dataset-viz "$@"
VIZ
    sudo chmod 0755 /usr/local/bin/lerobot-dataset-viz

    # 4. Clone LeRobot Git repository for local development & policies
    if [[ ! -d "${lerobot_dir}/.git" ]]; then
        log_info "Cloning LeRobot repository into ${lerobot_dir}..."
        sudo -H -u "${TARGET_USER}" git clone https://github.com/huggingface/lerobot.git "${lerobot_dir}"
        sudo -H -u "${TARGET_USER}" bash -c "
            source /opt/conda/etc/profile.d/conda.sh
            conda run -n lerobot --cwd '${lerobot_dir}' pip install -e '.[all,dataset_viz]'
        "
    fi

    log_success "Hugging Face LeRobot & lerobot-dataset-viz are fully configured and in PATH."
}
