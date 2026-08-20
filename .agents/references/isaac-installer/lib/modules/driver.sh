#!/usr/bin/env bash
# ==============================================================================
# driver.sh - NVIDIA GPU Driver, Blackwell Support, DKMS, and Nouveau Blacklisting
# ==============================================================================

check_driver() {
    detect_gpu
    local min_driver="${RECOMMENDED_DRIVER:-535}"
    if [[ "$DRIVER_INSTALLED" == true ]]; then
        local major_ver
        major_ver="$(echo "$DRIVER_VERSION" | cut -d'.' -f1)"
        if [[ "$major_ver" -ge "$min_driver" ]]; then
            STAGE_CHECK_MSG="Driver v${DRIVER_VERSION} active and satisfies requirement (>= ${min_driver})"
            return 0
        else
            STAGE_CHECK_MSG="Driver v${DRIVER_VERSION} is outdated for ${GPU_NAME} (Requires >= ${min_driver})"
            return 1
        fi
    else
        STAGE_CHECK_MSG="No active NVIDIA driver found for ${GPU_NAME}"
        return 1
    fi
}

install_nvidia_driver() {
    log_step "Checking NVIDIA GPU Driver Status & Hardware Requirements..."
    if check_driver; then
        log_success "${STAGE_CHECK_MSG}."
        return 0
    fi

    log_warn "${STAGE_CHECK_MSG}. Proceeding with installation..."

    # 1. Blacklist open-source nouveau module
    log_info "Blacklisting nouveau driver module..."
    cat << NOUVEAU | sudo tee /etc/modprobe.d/blacklist-nouveau.conf >/dev/null
blacklist nouveau
options nouveau modeset=0
NOUVEAU
    sudo update-initramfs -u

    # 2. Add CUDA keyring for official NVIDIA packages
    if [[ "$OS_ID" == "ubuntu" || "$OS_ID" == "debian" ]]; then
        log_info "Adding official NVIDIA CUDA repository keyring..."
        wget -q -O /tmp/cuda-keyring.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
        sudo dpkg -i /tmp/cuda-keyring.deb 2>/dev/null || true
        rm -f /tmp/cuda-keyring.deb
        pkg_update

        local min_driver="${RECOMMENDED_DRIVER:-535}"
        local driver_pkg="cuda-drivers-${min_driver}"
        if ! apt-cache show "$driver_pkg" &>/dev/null; then
            driver_pkg="nvidia-driver-${min_driver}"
        fi

        log_info "Installing kernel headers, build-essential, DKMS, and ${driver_pkg}..."
        pkg_install "linux-headers-$(uname -r)" build-essential dkms "${driver_pkg}"
    fi

    # 3. Enable GPU Persistence Mode
    if command -v nvidia-smi &>/dev/null; then
        sudo nvidia-smi -pm ENABLED 2>/dev/null || true
    fi

    log_success "NVIDIA driver package installed."
    set_stage "reboot_pending"
    register_resume_hook

    log_warn "================================================================="
    log_warn "A SYSTEM REBOOT IS REQUIRED to load the NVIDIA kernel modules."
    log_warn "After rebooting, the installer will automatically resume."
    log_warn "================================================================="
    
    if [[ "${AUTO_REBOOT:-false}" == "true" ]]; then
        log_info "Rebooting machine in 5 seconds..."
        sleep 5
        sudo reboot
    else
        echo -e "\nPlease run: ${CLR_BOLD}sudo reboot${CLR_RESET} to complete driver setup.\n"
        exit 0
    fi
}
