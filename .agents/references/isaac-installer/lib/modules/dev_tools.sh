#!/usr/bin/env bash
# ==============================================================================
# dev_tools.sh - Development Workstation Stack (Docker, GitHub Desktop, VS Code, Chrome, Discord)
# ==============================================================================

check_dev_tools() {
    local missing=()
    command -v docker &>/dev/null || missing+=("Docker CE")
    command -v nvidia-ctk &>/dev/null || missing+=("nvidia-container-toolkit")
    command -v github-desktop &>/dev/null || missing+=("GitHub Desktop")
    command -v code &>/dev/null || missing+=("VS Code")
    (command -v google-chrome &>/dev/null || command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null) || missing+=("Chrome/Chromium")
    command -v discord &>/dev/null || missing+=("Discord")

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Docker, nvidia-ctk, GitHub Desktop, VS Code, Chrome, and Discord already installed"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_dev_tools() {
    log_step "Configuring Development Workstation Tools & Applications..."

    # 1. Docker CE & NVIDIA Container Toolkit
    if ! command -v docker &>/dev/null; then
        log_info "Installing Docker CE engine..."
        pkg_install ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
        pkg_update
        pkg_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        
        # Add user to docker group (passwordless docker execution)
        sudo usermod -aG docker "${TARGET_USER}"
        sudo systemctl enable --now docker
        log_success "Docker CE installed. Added ${TARGET_USER} to 'docker' group."
    else
        log_success "Docker CE is already installed."
    fi

    # 2. NVIDIA Container Toolkit (GPU Passthrough into Docker)
    if ! command -v nvidia-ctk &>/dev/null; then
        log_info "Installing NVIDIA Container Toolkit..."
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

    # 3. GitHub Desktop for Linux
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

    # 4. Visual Studio Code & Robotics / AI Extensions
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

    # 5. Hardware-Accelerated Browser
    if ! command -v google-chrome &>/dev/null && ! command -v chromium-browser &>/dev/null && ! command -v chromium &>/dev/null; then
        log_info "Installing Google Chrome (Hardware-accelerated WebXR / WebRTC / Foxglove browser)..."
        wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
        pkg_install /tmp/google-chrome.deb || sudo apt-get install -f -y
        rm -f /tmp/google-chrome.deb
        log_success "Google Chrome installed."
    else
        log_success "Browser is already installed."
    fi

    # 6. Discord for Robotics & AI Communities
    if ! command -v discord &>/dev/null; then
        log_info "Installing Discord..."
        wget -q -O /tmp/discord.deb "https://discord.com/api/download?platform=linux&format=deb"
        pkg_install /tmp/discord.deb || sudo apt-get install -f -y
        rm -f /tmp/discord.deb
        log_success "Discord installed."
    else
        log_success "Discord is already installed."
    fi
}
