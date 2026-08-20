#!/usr/bin/env bash
# ==============================================================================
# conda.sh - Python Environment Isolation (Miniforge & UV)
# ==============================================================================

check_python_env() {
    if command -v uv &>/dev/null && [[ -x /opt/conda/bin/conda ]]; then
        STAGE_CHECK_MSG="UV and Miniforge already configured at /opt/conda"
        return 0
    else
        STAGE_CHECK_MSG="Missing UV package manager or Miniforge installation"
        return 1
    fi
}

install_python_env() {
    log_step "Configuring Python Runtime & Environment Isolation..."

    # 1. Install UV (Fast Rust-based Python package manager)
    if ! command -v uv &>/dev/null; then
        log_info "Installing UV package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        sudo ln -sf "${TARGET_HOME}/.local/bin/uv" /usr/local/bin/uv 2>/dev/null || true
    fi

    # 2. Install Miniforge into /opt/conda for multi-environment isolation
    local conda_dir="/opt/conda"
    if [[ ! -x "${conda_dir}/bin/conda" ]]; then
        log_info "Installing Miniforge into ${conda_dir}..."
        local installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
        wget -q -O /tmp/miniforge.sh "${installer_url}"
        sudo bash /tmp/miniforge.sh -b -p "${conda_dir}"
        rm -f /tmp/miniforge.sh
        sudo chown -R "${TARGET_USER}:${TARGET_USER}" "${conda_dir}"

        cat << 'CONDA_PROF' | sudo tee /etc/profile.d/conda.sh >/dev/null
if [ -x /opt/conda/bin/conda ]; then
    export PATH="/opt/conda/bin:$PATH"
fi
CONDA_PROF
        sudo chmod 644 /etc/profile.d/conda.sh
    fi

    sudo -H -u "${TARGET_USER}" bash -c "
        if ! grep -q 'conda initialize' ~/.bashrc 2>/dev/null; then
            /opt/conda/bin/conda init bash 2>/dev/null || true
        fi
    "

    log_success "Python runtime (UV & Miniforge) ready."
}
