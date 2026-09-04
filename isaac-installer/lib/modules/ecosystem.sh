#!/usr/bin/env bash
# ==============================================================================
# ecosystem.sh - Foundation Models (GR00T, LeRobot) and ROS 2 Bridge
# ==============================================================================

install_ecosystem_extensions() {
    local install_gr00t="${1:-false}"
    local install_ros="${2:-false}"

    if [[ "$install_gr00t" == "true" ]]; then
        log_step "Installing Isaac-GR00T & Hugging Face LeRobot..."
        local gr00t_dir="${TARGET_HOME}/Isaac-GR00T"
        local lerobot_dir="${TARGET_HOME}/lerobot"

        pkg_install ffmpeg libavcodec-dev libavformat-dev libswscale-dev libavdevice-dev

        # Create isolated conda env
        local conda_bin="$(resolve_conda_bin 2>/dev/null || echo "")"
        local conda_root="$(dirname "$(dirname "$conda_bin")" 2>/dev/null || echo "${TARGET_HOME}/miniconda3")"
        sudo -H -u "${TARGET_USER}" bash -c "
            source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
            if ! conda info --envs | grep -q 'gr00t'; then
                conda create -y -n gr00t python=3.10
                conda install -y -n gr00t ffmpeg -c conda-forge
            fi
        "

        # Clone & install LeRobot
        if [[ ! -d "${lerobot_dir}" ]]; then
            sudo -H -u "${TARGET_USER}" git clone https://github.com/huggingface/lerobot.git "${lerobot_dir}"
            sudo -H -u "${TARGET_USER}" bash -c "
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
                conda run -n gr00t --cwd '${lerobot_dir}' pip install -e .
            "
        fi

        # Clone & install Isaac-GR00T
        if [[ ! -d "${gr00t_dir}" ]]; then
            sudo -H -u "${TARGET_USER}" git clone https://github.com/NVIDIA/Isaac-GR00T "${gr00t_dir}"
            sudo -H -u "${TARGET_USER}" bash -c "
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
                conda run -n gr00t --cwd '${gr00t_dir}' pip install -e . --no-build-isolation
            "
        fi
        log_success "Isaac-GR00T and LeRobot installed in 'gr00t' conda environment."
    fi

    if [[ "$install_ros" == "true" ]]; then
        log_step "Configuring ROS 2 Humble Base Packages..."
        if [[ "$OS_ID" == "ubuntu" && "$OS_VERSION" == "22.04" ]]; then
            sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") main" | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null
            pkg_update
            pkg_install ros-humble-ros-base ros-humble-cyclonedds
            log_success "ROS 2 Humble installed. CycloneDDS configured."
        fi
    fi
}
