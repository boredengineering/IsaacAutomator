#!/usr/bin/env bash
# ==============================================================================
# hardware_teleop.sh - Physical AI Teleoperation, XR Headsets, Manus Gloves & Peripherals
# ==============================================================================

check_hardware_teleop() {
    if [[ -f /etc/udev/rules.d/99-ftdi-latency.rules && -f /etc/udev/rules.d/99-manus-gloves.rules ]]; then
        STAGE_CHECK_MSG="Hardware udev rules (Manus, RealSense, 1ms FTDI) already deployed"
        return 0
    else
        STAGE_CHECK_MSG="Missing udev rules for Manus gloves, SpaceMouse, RealSense, or 1ms FTDI"
        return 1
    fi
}

install_hardware_teleop() {
    log_step "Configuring Physical AI Teleoperation, XR & Hardware Devices..."

    local udev_template_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../templates/udev-rules" && pwd)"

    # 1. Install Peripherals Packages & Drivers
    log_info "Installing peripheral daemons, CAN tools, and gamepad utilities..."
    pkg_install \
        spacenavd \
        libspnav-dev \
        spnavcfg \
        can-utils \
        iproute2 \
        joystick \
        jstest-gtk \
        evtest \
        libopenxr-dev \
        libopenxr1

    # Enable and start spacenavd (SpaceMouse daemon)
    sudo systemctl enable --now spacenavd 2>/dev/null || true

    # 2. Deploy Hardware Udev Rules (Manus, FTDI 1ms Latency, SpaceMouse, RealSense)
    log_info "Installing hardware udev rules for Manus gloves, RealSense, and 1ms FTDI serial..."
    if [[ -d "${udev_template_dir}" ]]; then
        sudo cp "${udev_template_dir}"/*.rules /etc/udev/rules.d/
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
    fi

    # 3. Grant User Permissions to Hardware Device Groups
    log_info "Adding ${TARGET_USER} to device groups (dialout, plugdev, input, video)..."
    for grp in dialout plugdev input video; do
        if getent group "$grp" >/dev/null; then
            sudo usermod -aG "$grp" "${TARGET_USER}"
        else
            sudo groupadd "$grp" 2>/dev/null || true
            sudo usermod -aG "$grp" "${TARGET_USER}"
        fi
    done

    # 4. Install Isaac Teleop (XR / Quest / Vision Pro / Manus Retargeters)
    log_info "Installing Isaac Teleop Framework (CloudXR, Apple Vision Pro, Meta Quest 3, Manus Gloves)..."
    local lab_dir="${ISAACLAB_DIR:-${TARGET_HOME}/IsaacLab}"
    if [[ -d "${lab_dir}" ]]; then
        sudo -H -u "${TARGET_USER}" bash -c "
            cd '${lab_dir}'
            ./isaaclab.sh -p -m pip install 'isaacteleop[cloudxr,retargeters]~=1.0.0' rerun-sdk 2>/dev/null || true
        "
    fi

    log_success "Physical AI teleoperation stack and hardware device rules ready."
}
