#!/usr/bin/env bash
# ==============================================================================
# isaacsim.sh - NVIDIA Isaac Sim Engine Detection & Standalone Management
# ==============================================================================

resolve_isaacsim_dir() {
    detect_target_user

    # 1. Explicit override or custom build path
    if [[ "${ISAACSIM_SOURCE_TYPE:-standalone}" == "custom_build" && -n "${ISAACSIM_CUSTOM_BUILD_SOURCE_PATH:-}" ]]; then
        if [[ -d "${ISAACSIM_CUSTOM_BUILD_SOURCE_PATH}" ]]; then
            echo "${ISAACSIM_CUSTOM_BUILD_SOURCE_PATH}"
            return 0
        fi
    fi

    if [[ -n "${ISAACSIM_DIR:-}" && -d "${ISAACSIM_DIR}" ]]; then
        echo "${ISAACSIM_DIR}"
        return 0
    fi

    local req_ver="${ISAACSIM_VERSION:-${CFG_SIMULATION_ISAACSIM_VERSION:-6.0.1}}"

    # 2. Version-specific path (e.g. ~/IsaacSim-6.0.1 or ~/IsaacSim-5.1.0)
    if [[ -x "${TARGET_HOME}/IsaacSim-${req_ver}/isaac-sim.sh" ]]; then
        echo "${TARGET_HOME}/IsaacSim-${req_ver}"
        return 0
    fi

    # 3. Standard ~/IsaacSim location
    if [[ -x "${TARGET_HOME}/IsaacSim/isaac-sim.sh" ]]; then
        echo "${TARGET_HOME}/IsaacSim"
        return 0
    fi

    # 4. Omniverse Launcher standard path (~/.local/share/ov/pkg/isaac*sim*)
    local ov_pkg
    ov_pkg=$(find "${TARGET_HOME}/.local/share/ov/pkg" -maxdepth 1 -type d -name "isaac*sim*${req_ver}*" 2>/dev/null | sort -V | tail -n 1 || true)
    if [[ -n "$ov_pkg" && -x "${ov_pkg}/isaac-sim.sh" ]]; then
        echo "$ov_pkg"
        return 0
    fi

    # 5. System-wide /opt/nvidia/isaac-sim
    if [[ -x "/opt/nvidia/isaac-sim/isaac-sim.sh" ]]; then
        echo "/opt/nvidia/isaac-sim"
        return 0
    fi

    # Default fallback
    if [[ "$req_ver" == "5.1.0" ]]; then
        echo "${TARGET_HOME}/IsaacSim-5.1.0"
    else
        echo "${TARGET_HOME}/IsaacSim"
    fi
}

check_isaac_sim() {
    local install_dir
    install_dir="$(resolve_isaacsim_dir)"

    if [[ -x "${install_dir}/isaac-sim.sh" || -x "${install_dir}/kit/kit" ]]; then
        # Ensure EULA is accepted
        if [[ ! -f "${install_dir}/.eula_accepted" ]]; then
            sudo -H -u "${TARGET_USER}" touch "${install_dir}/.eula_accepted" 2>/dev/null || true
        fi
        # Isaac Sim 6.0 setup_conda_env.sh compatibility shim (renamed by NVIDIA to setup_python_env.sh)
        if [[ -f "${install_dir}/setup_python_env.sh" && ! -f "${install_dir}/setup_conda_env.sh" ]]; then
            sudo -H -u "${TARGET_USER}" ln -sf "${install_dir}/setup_python_env.sh" "${install_dir}/setup_conda_env.sh" 2>/dev/null || true
        fi
        STAGE_CHECK_MSG="Isaac Sim engine already installed and verified at ${install_dir}"
        return 0
    else
        STAGE_CHECK_MSG="Isaac Sim engine not installed at ${install_dir}"
        return 1
    fi
}

install_isaac_sim() {
    log_step "Checking NVIDIA Isaac Sim Engine..."

    local install_dir
    install_dir="$(resolve_isaacsim_dir)"
    local source_type="${ISAACSIM_SOURCE_TYPE:-standalone}"

    # Handle Custom Source Build
    if [[ "$source_type" == "custom_build" ]]; then
        log_header "Configuring Custom Source Built Isaac Sim"
        local custom_path="${ISAACSIM_CUSTOM_BUILD_SOURCE_PATH:-$install_dir}"
        local build_cmd="${ISAACSIM_CUSTOM_BUILD_COMMAND:-}"

        if [[ -n "$build_cmd" && -d "$custom_path" ]]; then
            log_info "Executing custom build command: ${build_cmd} in ${custom_path}..."
            sudo -H -u "${TARGET_USER}" bash -c "cd '${custom_path}' && ${build_cmd}"
        fi

        if [[ -x "${custom_path}/isaac-sim.sh" || -x "${custom_path}/kit/kit" ]]; then
            sudo -H -u "${TARGET_USER}" touch "${custom_path}/.eula_accepted" 2>/dev/null || true
            log_success "Custom Isaac Sim build verified at ${custom_path}."
            return 0
        else
            log_error "Custom build at ${custom_path} is missing isaac-sim.sh or kit/kit binary."
            return 1
        fi
    fi

    local source_dir="${TARGET_HOME}/isaacsim-pkg"
    local zip_version="${ISAACSIM_VERSION:-6.0.1}"
    local zip_name="isaac-sim-standalone-${zip_version}-linux-x86_64.zip"
    local download_url="https://download.isaacsim.omniverse.nvidia.com/${zip_name}"

    if check_isaac_sim; then
        log_success "${STAGE_CHECK_MSG} (Skipping 15 GB download)."
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

# ==============================================================================
# CLI Subcommands for Isaac Sim Multi-Version Management (`isaac-installer sim ...`)
# ==============================================================================

cmd_sim() {
    local subcmd="${1:-list}"
    shift || true

    detect_target_user

    case "$subcmd" in
        list)
            log_header "Discovered Isaac Sim Engine Installations"
            local found=0

            # 1. Standard ~/IsaacSim versions
            for dir in "${TARGET_HOME}"/IsaacSim* "${TARGET_HOME}"/isaacsim*; do
                if [[ -x "${dir}/isaac-sim.sh" || -x "${dir}/kit/kit" ]]; then
                    echo -e "  ● ${CLR_BOLD}${dir}${CLR_RESET} (Standalone / Custom)"
                    found=$((found + 1))
                fi
            done

            # 2. Omniverse packages
            if [[ -d "${TARGET_HOME}/.local/share/ov/pkg" ]]; then
                while IFS= read -r pkg; do
                    if [[ -n "$pkg" && -x "${pkg}/isaac-sim.sh" ]]; then
                        echo -e "  ● ${CLR_BOLD}${pkg}${CLR_RESET} (Omniverse Launcher)"
                        found=$((found + 1))
                    fi
                done < <(find "${TARGET_HOME}/.local/share/ov/pkg" -maxdepth 1 -type d -name "isaac*sim*" 2>/dev/null)
            fi

            # 3. System-wide
            if [[ -x "/opt/nvidia/isaac-sim/isaac-sim.sh" ]]; then
                echo -e "  ● ${CLR_BOLD}/opt/nvidia/isaac-sim${CLR_RESET} (System-Wide)"
                found=$((found + 1))
            fi

            if [[ "$found" -eq 0 ]]; then
                log_info "No Isaac Sim installations detected on host."
                log_info "Run 'sudo ./bin/isaac-installer install' to download and install."
            else
                echo ""
                log_info "Active Engine Linked to Isaac Lab:"
                local lab_dir
                lab_dir="$(resolve_isaaclab_dir)"
                if [[ -L "${lab_dir}/_isaac_sim" ]]; then
                    echo -e "  ↳ ${CLR_GREEN}$(readlink -f "${lab_dir}/_isaac_sim")${CLR_RESET}"
                else
                    echo -e "  ↳ ${CLR_YELLOW}None (Run ./bin/isaac-installer sim switch <path|version>)${CLR_RESET}"
                fi
            fi
            ;;

        switch)
            local target_sim="${1:-}"
            if [[ -z "$target_sim" ]]; then
                log_error "Usage: ./bin/isaac-installer sim switch <version|path-to-isaac-sim>"
                return 1
            fi

            # Check if version alias passed (e.g. 6.0.1 or 5.1.0)
            if [[ "$target_sim" == "6.0.1" || "$target_sim" == "6.0" ]]; then
                if [[ -d "${TARGET_HOME}/IsaacSim-6.0.1" ]]; then
                    target_sim="${TARGET_HOME}/IsaacSim-6.0.1"
                else
                    target_sim="${TARGET_HOME}/IsaacSim"
                fi
            elif [[ "$target_sim" == "5.1.0" || "$target_sim" == "5.1" ]]; then
                if [[ -d "${TARGET_HOME}/IsaacSim-5.1.0" ]]; then
                    target_sim="${TARGET_HOME}/IsaacSim-5.1.0"
                else
                    target_sim="${TARGET_HOME}/IsaacSim"
                fi
            else
                target_sim="$(expand_tilde_path "$target_sim")"
            fi

            if [[ ! -x "${target_sim}/isaac-sim.sh" && ! -x "${target_sim}/kit/kit" ]]; then
                log_error "Path ${target_sim} is not a valid Isaac Sim installation (missing isaac-sim.sh or kit/kit)."
                return 1
            fi

            local lab_dir
            lab_dir="$(resolve_isaaclab_dir)"
            if [[ ! -d "${lab_dir}" ]]; then
                log_error "Isaac Lab directory not found at ${lab_dir}."
                return 1
            fi

            log_info "Atomically switching Isaac Lab engine -> ${target_sim}..."
            ln -sfn "${target_sim}" "${lab_dir}/_isaac_sim.tmp.$$"
            mv -Tf "${lab_dir}/_isaac_sim.tmp.$$" "${lab_dir}/_isaac_sim"
            chown -h "${TARGET_USER}:${TARGET_USER}" "${lab_dir}/_isaac_sim"

            log_success "Active engine switched to ${target_sim}."
            ;;

        *)
            echo "Usage: ./bin/isaac-installer sim [list|switch <version|path>]"
            ;;
    esac
}
