#!/usr/bin/env bash
# ==============================================================================
# isaacsim.sh - NVIDIA Isaac Sim Standalone Engine Installation
# ==============================================================================

check_isaac_sim() {
    local install_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"
    if [[ -x "${install_dir}/isaac-sim.sh" && -f "${install_dir}/.eula_accepted" ]]; then
        STAGE_CHECK_MSG="Isaac Sim v5.1.0 engine already installed at ${install_dir}"
        return 0
    else
        STAGE_CHECK_MSG="Isaac Sim engine not installed at ${install_dir}"
        return 1
    fi
}

install_isaac_sim() {
    log_step "Installing NVIDIA Isaac Sim Engine..."

    local install_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"
    local source_dir="${TARGET_HOME}/isaacsim-pkg"
    local zip_version="${ISAACSIM_VERSION:-5.1.0}"
    local zip_name="isaac-sim-standalone-${zip_version}-linux-x86_64.zip"
    local download_url="https://download.isaacsim.omniverse.nvidia.com/${zip_name}"

    if check_isaac_sim; then
        log_success "${STAGE_CHECK_MSG}."
        return 0
    fi

    mkdir -p "${source_dir}" "${install_dir}"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${source_dir}" "${install_dir}"

    # 1. Download or locate archive
    if [[ ! -f "${source_dir}/${zip_name}" && ! -f "/tmp/${zip_name}" ]]; then
        log_info "Downloading Isaac Sim ${zip_version} (~15 GB)..."
        sudo -H -u "${TARGET_USER}" wget --show-progress -q -O "${source_dir}/${zip_name}" "${download_url}" || {
            log_warn "Direct download failed. If you have the zip on a USB drive, place it at ${source_dir}/${zip_name}"
            return 1
        }
    elif [[ -f "/tmp/${zip_name}" ]]; then
        mv "/tmp/${zip_name}" "${source_dir}/${zip_name}"
    fi

    # 2. Extract Archive
    log_info "Extracting Isaac Sim archive into ${install_dir}..."
    sudo -H -u "${TARGET_USER}" unzip -q -o "${source_dir}/${zip_name}" -d "${install_dir}"

    # 3. Accept EULA
    log_info "Accepting NVIDIA Omniverse / Isaac Sim EULA..."
    sudo -H -u "${TARGET_USER}" touch "${install_dir}/.eula_accepted"

    # 4. Run post_install.sh
    if [[ -x "${install_dir}/post_install.sh" ]]; then
        log_info "Running Isaac Sim post_install.sh..."
        sudo -H -u "${TARGET_USER}" bash "${install_dir}/post_install.sh"
    fi

    # 5. Patch desktop icon to pin GPU 0
    local icon_path="${TARGET_HOME}/.local/share/applications/IsaacSim.desktop"
    if [[ -f "${icon_path}" ]]; then
        sed -i 's|\(Exec=.*isaac-sim\.sh\)|\1 --/renderer/activeGpu=0|' "${icon_path}" 2>/dev/null || true
        mkdir -p "${TARGET_HOME}/Desktop"
        cp -f "${icon_path}" "${TARGET_HOME}/Desktop/IsaacSim.desktop"
        chown "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/Desktop/IsaacSim.desktop"
        chmod 0755 "${TARGET_HOME}/Desktop/IsaacSim.desktop"
        sudo -H -u "${TARGET_USER}" gio set "${TARGET_HOME}/Desktop/IsaacSim.desktop" metadata::trusted true 2>/dev/null || true
    fi

    log_success "Isaac Sim ${zip_version} successfully installed at ${install_dir}."
}
