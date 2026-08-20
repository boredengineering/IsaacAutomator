#!/usr/bin/env bash
# ==============================================================================
# conda.sh - Hybrid Conda Named Environment + UV Pip Engine & Activation Hooks
# ==============================================================================

CONDA_ROOT="/opt/conda"
CONDA_ENV_NAME="isaaclab"

resolve_target_python_version() {
    local sim_version="${SIMULATION_VERSION:-${CFG_SIMULATION_ISAACSIM_VERSION:-5.1.0}}"
    if [[ "$sim_version" == 6.* ]]; then
        echo "3.12"
    else
        echo "3.10"
    fi
}

check_python_env() {
    local py_ver
    py_ver="$(resolve_target_python_version)"
    local env_path="${CONDA_ROOT}/envs/${CONDA_ENV_NAME}"

    local missing=()
    command -v uv &>/dev/null || missing+=("uv package manager")
    [[ -x "${CONDA_ROOT}/bin/conda" ]] || missing+=("Miniforge at ${CONDA_ROOT}")
    [[ -d "${env_path}" && -x "${env_path}/bin/python" ]] || missing+=("Conda environment '${CONDA_ENV_NAME}' (Python ${py_ver})")
    [[ -f "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh" ]] || missing+=("Conda activation hooks")
    command -v isaaclab-env &>/dev/null || missing+=("isaaclab-env CLI shim")

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Hybrid Conda '${CONDA_ENV_NAME}' (Python ${py_ver}) + UV and clean activation hooks already configured"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_python_env() {
    log_step "Configuring Hybrid Python Runtime (Conda Named Env + UV Acceleration)..."
    detect_target_user

    local py_ver
    py_ver="$(resolve_target_python_version)"
    local env_path="${CONDA_ROOT}/envs/${CONDA_ENV_NAME}"
    local sim_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"

    # 1. Install UV (Fast Rust-based Python package manager)
    if ! command -v uv &>/dev/null; then
        log_info "Installing UV package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        sudo ln -sf "${TARGET_HOME}/.local/bin/uv" /usr/local/bin/uv 2>/dev/null || true
    fi

    # 2. Install Miniforge into /opt/conda for multi-environment isolation
    if [[ ! -x "${CONDA_ROOT}/bin/conda" ]]; then
        log_info "Installing Miniforge into ${CONDA_ROOT}..."
        local installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
        wget -q -O /tmp/miniforge.sh "${installer_url}"
        sudo bash /tmp/miniforge.sh -b -p "${CONDA_ROOT}"
        rm -f /tmp/miniforge.sh
        sudo chown -R "${TARGET_USER}:${TARGET_USER}" "${CONDA_ROOT}"

        cat << 'CONDA_PROF' | sudo tee /etc/profile.d/conda.sh >/dev/null
if [ -x /opt/conda/bin/conda ]; then
    export PATH="/opt/conda/bin:$PATH"
fi
CONDA_PROF
        sudo chmod 644 /etc/profile.d/conda.sh
    fi

    # Initialize conda for user non-invasively
    sudo -H -u "${TARGET_USER}" bash -c "
        if ! grep -q 'conda initialize' ~/.bashrc 2>/dev/null; then
            ${CONDA_ROOT}/bin/conda init bash 2>/dev/null || true
        fi
    "

    # 3. Create or Verify Named Conda Environment ('isaaclab')
    if [[ ! -d "${env_path}" || ! -x "${env_path}/bin/python" ]]; then
        log_info "Creating central named Conda environment '${CONDA_ENV_NAME}' with Python ${py_ver}..."
        sudo -H -u "${TARGET_USER}" "${CONDA_ROOT}/bin/conda" create -y -n "${CONDA_ENV_NAME}" python="${py_ver}" pip
    else
        log_info "Conda environment '${CONDA_ENV_NAME}' already exists."
    fi

    # 4. Accelerate PyTorch + CUDA Installation using UV inside Conda Env
    log_info "Verifying PyTorch CUDA acceleration in '${CONDA_ENV_NAME}' environment via UV..."
    local uv_bin
    uv_bin="$(command -v uv || echo "${TARGET_HOME}/.local/bin/uv")"

    if [[ -x "${uv_bin}" && -x "${env_path}/bin/python" ]]; then
        local torch_wheel_url="https://download.pytorch.org/whl/cu124"
        sudo -H -u "${TARGET_USER}" "${uv_bin}" pip install \
            --python "${env_path}/bin/python" \
            torch torchvision \
            --index-url "${torch_wheel_url}" 2>/dev/null || true
    fi

    # 5. Configure Scoped Activation Hooks (Guarantees Zero Global Shell Contamination)
    log_info "Configuring scoped Conda activation hooks in ${env_path}/etc/conda/..."
    mkdir -p "${env_path}/etc/conda/activate.d"
    mkdir -p "${env_path}/etc/conda/deactivate.d"

    cat << HOOK_ACT | sudo tee "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh" >/dev/null
#!/usr/bin/env bash
# Scoped Omniverse Environment Variables (Active only while 'isaaclab' is activated)
export _OLD_ISAAC_EXP_PATH="\${EXP_PATH:-}"
export _OLD_ISAAC_PATH="\${ISAAC_PATH:-}"
export _OLD_CARB_APP_PATH="\${CARB_APP_PATH:-}"
export _OLD_VK_ICD_FILENAMES="\${VK_ICD_FILENAMES:-}"

export EXP_PATH="${sim_dir}/apps"
export ISAAC_PATH="${sim_dir}"
export CARB_APP_PATH="${sim_dir}/kit"
export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
HOOK_ACT
    sudo chmod 755 "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh"

    cat << HOOK_DEACT | sudo tee "${env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh" >/dev/null
#!/usr/bin/env bash
# Cleanly restore previous shell environment upon 'conda deactivate'
if [[ -n "\${_OLD_ISAAC_EXP_PATH}" ]]; then export EXP_PATH="\${_OLD_ISAAC_EXP_PATH}"; else unset EXP_PATH; fi
if [[ -n "\${_OLD_ISAAC_PATH}" ]]; then export ISAAC_PATH="\${_OLD_ISAAC_PATH}"; else unset ISAAC_PATH; fi
if [[ -n "\${_OLD_CARB_APP_PATH}" ]]; then export CARB_APP_PATH="\${_OLD_CARB_APP_PATH}"; else unset CARB_APP_PATH; fi
if [[ -n "\${_OLD_VK_ICD_FILENAMES}" ]]; then export VK_ICD_FILENAMES="\${_OLD_VK_ICD_FILENAMES}"; else unset VK_ICD_FILENAMES; fi
unset _OLD_ISAAC_EXP_PATH _OLD_ISAAC_PATH _OLD_CARB_APP_PATH _OLD_VK_ICD_FILENAMES
HOOK_DEACT
    sudo chmod 755 "${env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh"

    sudo chown -R "${TARGET_USER}:${TARGET_USER}" "${env_path}/etc" 2>/dev/null || true

    # 6. Deploy Zero-Activation CLI Shim (/usr/local/bin/isaaclab-env)
    log_info "Deploying zero-activation CLI shim: /usr/local/bin/isaaclab-env..."
    cat << 'SHIM' | sudo tee /usr/local/bin/isaaclab-env >/dev/null
#!/usr/bin/env bash
# ==============================================================================
# isaaclab-env - Scoped Runner for Headless Scripts, CI/CD, and Terminal Executions
# ==============================================================================
set -e

SIM_PATH="${ISAACSIM_DIR:-$HOME/IsaacSim}"
export EXP_PATH="${SIM_PATH}/apps"
export ISAAC_PATH="${SIM_PATH}"
export CARB_APP_PATH="${SIM_PATH}/kit"
export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"

CONDA_PY="/opt/conda/envs/isaaclab/bin/python"

if [[ $# -eq 0 ]]; then
    echo "Usage: isaaclab-env <command> [args...]"
    echo "Example: isaaclab-env python scripts/reinforcement_learning/rsl_rl/train.py --task Isaac-Ant-v0"
    exit 1
fi

if [[ "$1" == "python" || "$1" == "python3" ]]; then
    shift
    if [[ -x "${CONDA_PY}" ]]; then
        export PATH="/opt/conda/envs/isaaclab/bin:$PATH"
        exec "${CONDA_PY}" "$@"
    else
        exec python3 "$@"
    fi
else
    if [[ -x "${CONDA_PY}" ]]; then
        export PATH="/opt/conda/envs/isaaclab/bin:$PATH"
    fi
    exec "$@"
fi
SHIM
    sudo chmod 0755 /usr/local/bin/isaaclab-env

    # 7. Create template binary in bin/ for repository distribution
    mkdir -p "$(dirname "$0")/../bin"
    cp -f /usr/local/bin/isaaclab-env "$(dirname "$0")/../bin/isaaclab-env" 2>/dev/null || true
    chmod 0755 "$(dirname "$0")/../bin/isaaclab-env" 2>/dev/null || true

    log_success "Hybrid Python environment ('${CONDA_ENV_NAME}' + UV + Scoped Hooks) ready."
}

