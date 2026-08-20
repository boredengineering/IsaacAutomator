#!/usr/bin/env bash
# ==============================================================================
# dev_tools.sh - Declarative Development Workstation Stack & Cloud CLIs
# ==============================================================================

check_dev_tools() {
    local missing=()
    command -v docker &>/dev/null || missing+=("Docker CE")
    command -v nvidia-ctk &>/dev/null || missing+=("nvidia-container-toolkit")
    command -v nvme &>/dev/null || missing+=("nvme-cli")
    command -v lvm &>/dev/null || missing+=("lvm2")
    command -v gh &>/dev/null || missing+=("GitHub CLI (gh)")

    if [[ "${CFG_DEVTOOLS_CLOUD_CLIS_AWS:-false}" == "true" ]]; then
        command -v aws &>/dev/null || missing+=("AWS CLI v2")
    fi
    if [[ "${CFG_DEVTOOLS_CLOUD_CLIS_GCLOUD:-false}" == "true" ]]; then
        command -v gcloud &>/dev/null || missing+=("Google Cloud CLI (gcloud)")
    fi
    if [[ "${CFG_DEVTOOLS_GITHUB_DESKTOP:-true}" == "true" ]]; then
        command -v github-desktop &>/dev/null || missing+=("GitHub Desktop")
    fi
    if [[ "${CFG_DEVTOOLS_VSCODE:-true}" == "true" ]]; then
        command -v code &>/dev/null || missing+=("VS Code")
    fi
    if [[ "${CFG_DEVTOOLS_CHROMIUM:-true}" == "true" ]]; then
        (command -v google-chrome &>/dev/null || command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null) || missing+=("Chrome/Chromium")
    fi
    if [[ "${CFG_DEVTOOLS_DISCORD:-false}" == "true" ]]; then
        command -v discord &>/dev/null || missing+=("Discord")
    fi

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Configured development tools are already installed"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_storage_tools() {
    log_info "Installing NVMe management, LVM2, SMART diagnostics & I/O benchmark tools..."
    pkg_install nvme-cli lvm2 smartmontools fio iotop
    log_success "Storage tools (nvme-cli, lvm2, smartmontools, fio, iotop) installed."
}

install_aws_cli() {
    if ! command -v aws &>/dev/null; then
        log_info "Installing AWS CLI v2..."
        pkg_install unzip curl
        curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
        unzip -q -o /tmp/awscliv2.zip -d /tmp
        sudo /tmp/aws/install --update 2>/dev/null || true
        rm -rf /tmp/aws /tmp/awscliv2.zip
        log_success "AWS CLI v2 installed."
    else
        log_success "AWS CLI v2 is already installed ($(aws --version 2>&1 | awk '{print $1}'))."
    fi
}

install_gcp_cli() {
    if ! command -v gcloud &>/dev/null; then
        log_info "Installing Google Cloud SDK (gcloud CLI)..."
        pkg_install apt-transport-https ca-certificates gnupg curl
        curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg --yes 2>/dev/null || true
        echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null
        pkg_update
        pkg_install google-cloud-cli
        log_success "Google Cloud CLI (gcloud) installed."
    else
        log_success "Google Cloud CLI is already installed ($(gcloud --version 2>&1 | head -n 1))."
    fi
}

install_github_cli() {
    if ! command -v gh &>/dev/null; then
        log_info "Installing GitHub CLI (gh)..."
        pkg_install curl
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null || true
        sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
        pkg_update
        pkg_install gh
        log_success "GitHub CLI (gh) installed."
    else
        log_success "GitHub CLI (gh) is already installed ($(gh --version 2>&1 | head -n 1))."
    fi
}

install_dev_tools() {
    log_step "Installing Developer Workstation Stack from Profile..."

    # 1. Docker CE Engine
    if ! command -v docker &>/dev/null; then
        log_info "Installing Docker CE..."
        pkg_install ca-certificates curl gnupg lsb-release
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        pkg_update
        pkg_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        sudo usermod -aG docker "${TARGET_USER}"
        log_success "Docker CE installed and user '${TARGET_USER}' added to docker group."
    else
        log_success "Docker CE is already installed ($(docker --version 2>&1 | awk '{print $3}' | sed 's/,//'))."
    fi

    # 2. NVIDIA Container Toolkit
    if ! command -v nvidia-ctk &>/dev/null; then
        log_info "Installing NVIDIA Container Toolkit (nvidia-ctk)..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg --yes
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
        pkg_update
        pkg_install nvidia-container-toolkit
        sudo nvidia-ctk runtime configure --runtime=docker
        sudo systemctl restart docker
        log_success "NVIDIA Container Toolkit configured with Docker runtime."
    else
        log_success "NVIDIA Container Toolkit is already configured."
    fi

    # 3. Storage & NVMe Tools
    install_storage_tools

    # 4. GitHub CLI
    install_github_cli

    # 5. Cloud CLIs (Only if enabled in YAML)
    if [[ "${CFG_DEVTOOLS_CLOUD_CLIS_AWS:-false}" == "true" ]]; then
        install_aws_cli
    fi
    if [[ "${CFG_DEVTOOLS_CLOUD_CLIS_GCLOUD:-false}" == "true" ]]; then
        install_gcp_cli
    fi

    # 6. GitHub Desktop for Linux (Only if enabled in YAML)
    if [[ "${CFG_DEVTOOLS_GITHUB_DESKTOP:-true}" == "true" ]]; then
        if ! command -v github-desktop &>/dev/null; then
            log_info "Installing GitHub Desktop..."
            wget -qO - https://mirror.mwt.me/shiftkey-desktop/gpgkey | gpg --dearmor | sudo tee /etc/apt/keyrings/mwt-desktop.gpg > /dev/null
            sudo chmod 644 /etc/apt/keyrings/mwt-desktop.gpg
            echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/mwt-desktop.gpg] https://mirror.mwt.me/shiftkey-desktop/deb/ any main" | sudo tee /etc/apt/sources.list.d/mwt-desktop.list > /dev/null
            pkg_update
            pkg_install github-desktop || log_warn "GitHub Desktop installation skipped or unsupported architecture."
            log_success "GitHub Desktop installed."
        else
            log_success "GitHub Desktop is already installed."
        fi
    fi

    # 7. Visual Studio Code & Robotics Extensions (Only if enabled in YAML)
    if [[ "${CFG_DEVTOOLS_VSCODE:-true}" == "true" ]]; then
        if ! command -v code &>/dev/null; then
            log_info "Installing Visual Studio Code..."
            wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | sudo tee /etc/apt/keyrings/packages.microsoft.gpg > /dev/null
            echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" | sudo tee /etc/apt/sources.list.d/vscode.list > /dev/null
            pkg_update
            pkg_install code
        fi

        if command -v code &>/dev/null; then
            log_info "Installing VS Code extensions for Physical AI, Robotics, USD & Python..."
            local extensions=(
                "ms-python.python"
                "ms-python.vscode-pylance"
                "ms-vscode.cpptools"
                "ms-vscode-remote.remote-containers"
                "ms-vscode-remote.remote-ssh"
                "ms-iot.vscode-ros"
                "ms-toolsai.jupyter"
                "eamodio.gitlens"
                "nv-usd.usd-language-support"
                "foxglove.foxglove-studio"
            )
            for ext in "${extensions[@]}"; do
                sudo -H -u "${TARGET_USER}" code --install-extension "$ext" --force 2>/dev/null || true
            done
            log_success "Visual Studio Code and extensions configured."
        fi
    fi

    # 8. Hardware-Accelerated Browser (Only if enabled in YAML)
    if [[ "${CFG_DEVTOOLS_CHROMIUM:-true}" == "true" ]]; then
        if ! command -v google-chrome &>/dev/null && ! command -v chromium-browser &>/dev/null && ! command -v chromium &>/dev/null; then
            log_info "Installing Google Chrome (Hardware-accelerated WebXR / WebRTC / Foxglove browser)..."
            wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
            pkg_install /tmp/google-chrome.deb || sudo apt-get install -f -y
            rm -f /tmp/google-chrome.deb
            log_success "Google Chrome installed."
        else
            log_success "Browser is already installed."
        fi
    fi

    # 9. Discord (Only if enabled in YAML)
    if [[ "${CFG_DEVTOOLS_DISCORD:-false}" == "true" ]]; then
        if ! command -v discord &>/dev/null; then
            log_info "Installing Discord..."
            wget -q -O /tmp/discord.deb "https://discord.com/api/download?platform=linux&format=deb"
            pkg_install /tmp/discord.deb || sudo apt-get install -f -y
            rm -f /tmp/discord.deb
            log_success "Discord installed."
        else
            log_success "Discord is already installed."
        fi
    fi
}
