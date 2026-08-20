#!/usr/bin/env bash
# ==============================================================================
# display.sh - Display Server, X11 Enforcement & Virtual EDID Configuration
# ==============================================================================

check_display_server() {
    detect_display
    if [[ "$IS_WAYLAND" == false && "$GDM_WAYLAND_DISABLED" == true ]]; then
        STAGE_CHECK_MSG="X11 session active and Wayland already disabled in GDM"
        return 0
    elif [[ "$IS_WAYLAND" == false ]]; then
        STAGE_CHECK_MSG="X11 active (GDM Wayland toggle recommended for persistence)"
        return 1
    else
        STAGE_CHECK_MSG="Active session is Wayland (X11 enforcement required for Omniverse)"
        return 1
    fi
}

configure_display_server() {
    log_step "Configuring Display Server for Omniverse Vulkan Compatibility..."
    detect_display

    # 1. Enforce X11 in GDM3 (Disable Wayland)
    if [[ -f /etc/gdm3/custom.conf ]]; then
        if ! grep -q "^WaylandEnable=false" /etc/gdm3/custom.conf; then
            log_info "Disabling Wayland in /etc/gdm3/custom.conf (Enforcing X11)..."
            if grep -q "^#WaylandEnable=false" /etc/gdm3/custom.conf; then
                sudo sed -i 's/^#WaylandEnable=false/WaylandEnable=false/' /etc/gdm3/custom.conf
            elif grep -q "\[daemon\]" /etc/gdm3/custom.conf; then
                sudo sed -i '/\[daemon\]/a WaylandEnable=false' /etc/gdm3/custom.conf
            else
                echo -e "\n[daemon]\nWaylandEnable=false" | sudo tee -a /etc/gdm3/custom.conf >/dev/null
            fi
            log_success "GDM configured for X11."
        else
            log_info "Wayland is already disabled in GDM."
        fi
    fi

    # 2. Handle Headless vs Physical Monitor
    if [[ "$HAS_PHYSICAL_MONITOR" == true ]]; then
        log_success "Physical monitor detected on active display. Preserving native Xorg configuration."
    else
        log_info "No physical monitor detected (Headless mode). Setting up virtual EDID..."
        local template_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../templates" && pwd)"
        
        if [[ -f "${template_dir}/vdisplay.edid" ]]; then
            sudo cp "${template_dir}/vdisplay.edid" /etc/X11/vdisplay.edid
            sudo chmod 644 /etc/X11/vdisplay.edid
        fi

        detect_gpu
        local bus_id="${GPU_BUS_ID:-0:0:0}"
        if command -v nvidia-xconfig &>/dev/null; then
            sudo nvidia-xconfig -a \
                --allow-empty-initial-configuration \
                --virtual=1920x1080 \
                --busid="${bus_id}" 2>/dev/null || true
            log_success "Generated headless virtual Xorg configuration."
        fi
    fi

    touch "${TARGET_HOME}/.Xauthority"
    chmod 0666 "${TARGET_HOME}/.Xauthority"
    chown "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/.Xauthority" 2>/dev/null || true
}
