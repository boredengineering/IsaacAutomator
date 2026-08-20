#!/usr/bin/env bash
# ==============================================================================
# streaming.sh - Hardware-Accelerated 3D Streaming (NoMachine & Sunshine NVENC)
# ==============================================================================

install_streaming_provider() {
    local provider="${1:-nomachine}"
    log_step "Configuring 3D Viewport Streaming Provider: ${provider}..."

    case "$provider" in
        nomachine)
            if ! command -v nxserver &>/dev/null; then
                log_info "Downloading and installing NoMachine (Port 4000)..."
                wget -q -O /tmp/nomachine.deb https://download.nomachine.com/download/8.11/Linux/nomachine_8.11.3_4_amd64.deb
                sudo dpkg -i /tmp/nomachine.deb 2>/dev/null || pkg_install -f
                rm -f /tmp/nomachine.deb
                log_success "NoMachine installed. Connect on port 4000."
            else
                log_success "NoMachine is already installed."
            fi
            ;;
        sunshine)
            if ! command -v sunshine &>/dev/null; then
                log_info "Downloading and installing Sunshine NVENC Streaming Server..."
                wget -q -O /tmp/sunshine.deb https://github.com/LizardByte/Sunshine/releases/download/v0.21.0/sunshine-ubuntu-22.04-amd64.deb
                pkg_install /tmp/sunshine.deb
                rm -f /tmp/sunshine.deb
                log_success "Sunshine installed. Configure Web UI at https://<IP>:47990."
            else
                log_success "Sunshine is already installed."
            fi
            ;;
        *)
            log_warn "Unknown streaming provider: ${provider}. Skipping."
            ;;
    esac
}
