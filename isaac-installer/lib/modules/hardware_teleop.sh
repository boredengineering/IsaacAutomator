#!/usr/bin/env bash
# ==============================================================================
# hardware_teleop.sh - Declarative Teleoperation, XR & Peripheral Controller
# ==============================================================================

get_teleop_description() {
    local parts=()
    [[ "${CFG_TELEOPERATION_FTDI_1MS_LATENCY_RULE:-true}" == "true" ]] && parts+=("1ms FTDI low-latency serial rule for robotic arms")
    [[ "${CFG_TELEOPERATION_SPACEMOUSE_DAEMON:-false}" == "true" ]] && parts+=("SpaceMouse daemon (spacenavd)")
    [[ "${CFG_TELEOPERATION_MANUS_VR_GLOVES:-false}" == "true" ]] && parts+=("Manus VR haptic gloves")
    [[ "${CFG_TELEOPERATION_REALSENSE_CAMERAS:-false}" == "true" ]] && parts+=("Intel RealSense depth cameras")
    [[ "${CFG_TELEOPERATION_XR_CLOUDXR:-false}" == "true" ]] && parts+=("XR CloudXR retargeters")

    if [[ ${#parts[@]} -gt 0 ]]; then
        local IFS=", "
        echo "${parts[*]}"
    else
        echo "Hardware teleoperation (Disabled in profile)"
    fi
}

check_hardware_teleop() {
    local missing=()
    local udev_dir="/etc/udev/rules.d"
    local total_enabled=0

    if [[ "${CFG_TELEOPERATION_FTDI_1MS_LATENCY_RULE:-true}" == "true" ]]; then
        total_enabled=$((total_enabled + 1))
        [[ -f "${udev_dir}/99-ftdi-latency.rules" ]] || missing+=("1ms FTDI rule")
    fi

    if [[ "${CFG_TELEOPERATION_SPACEMOUSE_DAEMON:-false}" == "true" ]]; then
        total_enabled=$((total_enabled + 1))
        command -v spacenavd &>/dev/null || missing+=("spacenavd")
    fi

    if [[ "${CFG_TELEOPERATION_MANUS_VR_GLOVES:-false}" == "true" ]]; then
        total_enabled=$((total_enabled + 1))
        [[ -f "${udev_dir}/99-manus-gloves.rules" ]] || missing+=("Manus gloves rule")
    fi

    if [[ "${CFG_TELEOPERATION_REALSENSE_CAMERAS:-false}" == "true" ]]; then
        total_enabled=$((total_enabled + 1))
        [[ -f "${udev_dir}/99-realsense.rules" ]] || missing+=("RealSense rule")
    fi

    if [[ "$total_enabled" -eq 0 ]]; then
        STAGE_CHECK_MSG="Hardware teleoperation is disabled in active profile"
        return 0
    fi

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Configured hardware teleop components are active"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_hardware_teleop() {
    log_step "Configuring Hardware Teleoperation & Peripherals from Profile..."

    local udev_template_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../templates/udev-rules" && pwd)"
    local udev_dest="/etc/udev/rules.d"

    # 1. FTDI 1ms Latency Timer (For ALOHA & SO-100 arms)
    if [[ "${CFG_TELEOPERATION_FTDI_1MS_LATENCY_RULE:-true}" == "true" ]]; then
        log_info "Deploying 1ms FTDI low-latency serial udev rule..."
        if [[ -f "${udev_template_dir}/99-ftdi-latency.rules" ]]; then
            sudo cp "${udev_template_dir}/99-ftdi-latency.rules" "${udev_dest}/"
        fi
    fi

    # 2. 3D SpaceMouse Daemon (Only if enabled in YAML)
    if [[ "${CFG_TELEOPERATION_SPACEMOUSE_DAEMON:-false}" == "true" ]]; then
        log_info "Installing SpaceMouse daemon (spacenavd)..."
        pkg_install spacenavd libspnav-dev spnavcfg
        sudo systemctl enable --now spacenavd 2>/dev/null || true
        if [[ -f "${udev_template_dir}/99-spacenav.rules" ]]; then
            sudo cp "${udev_template_dir}/99-spacenav.rules" "${udev_dest}/"
        fi
    fi

    # 3. Manus VR Haptic Gloves (Only if enabled in YAML)
    if [[ "${CFG_TELEOPERATION_MANUS_VR_GLOVES:-false}" == "true" ]]; then
        log_info "Deploying Manus VR haptic gloves udev rule..."
        if [[ -f "${udev_template_dir}/99-manus-gloves.rules" ]]; then
            sudo cp "${udev_template_dir}/99-manus-gloves.rules" "${udev_dest}/"
        fi
    fi

    # 4. Intel RealSense Depth Cameras (Only if enabled in YAML)
    if [[ "${CFG_TELEOPERATION_REALSENSE_CAMERAS:-false}" == "true" ]]; then
        log_info "Deploying Intel RealSense depth camera udev rule..."
        if [[ -f "${udev_template_dir}/99-realsense.rules" ]]; then
            sudo cp "${udev_template_dir}/99-realsense.rules" "${udev_dest}/"
        fi
    fi

    # 5. Reload Udev
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true

    # 6. Device User Groups
    log_info "Ensuring user group memberships for serial and USB devices..."
    for grp in dialout plugdev input video; do
        if getent group "$grp" >/dev/null; then
            sudo usermod -aG "$grp" "${TARGET_USER}"
        else
            sudo groupadd "$grp" 2>/dev/null || true
            sudo usermod -aG "$grp" "${TARGET_USER}"
        fi
    done

    # 7. XR / CloudXR Retargeters (Only if enabled in YAML)
    if [[ "${CFG_TELEOPERATION_XR_CLOUDXR:-false}" == "true" ]]; then
        log_info "Installing OpenXR development libraries and Isaac Teleop..."
        pkg_install libopenxr-dev libopenxr1
        local lab_dir
        lab_dir="$(resolve_isaaclab_dir)"
        if [[ -d "${lab_dir}" ]]; then
            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${lab_dir}'
                ./isaaclab.sh -p -m pip install 'isaacteleop[cloudxr,retargeters]~=1.0.0' 2>/dev/null || true
            "
        fi
    fi

    log_success "Hardware teleoperation configured according to active profile."
}
