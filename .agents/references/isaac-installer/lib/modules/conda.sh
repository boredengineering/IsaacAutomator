#!/usr/bin/env bash
# ==============================================================================
# conda.sh - Hybrid Conda Named Environment + UV Pip Engine & Activation Hooks
# ==============================================================================

CONDA_ENV_NAME="isaaclab"

resolve_target_python_version() {
    local sim_version="${SIMULATION_VERSION:-${CFG_SIMULATION_ISAACSIM_VERSION:-6.0.1}}"
    if [[ "$sim_version" == 6.* ]]; then
        echo "3.12"
    else
        echo "3.10"
    fi
}

resolve_conda_bin() {
    detect_target_user

    # 1. Check user PATH
    local user_conda
    user_conda="$(sudo -H -u "${TARGET_USER}" bash -l -c "command -v conda 2>/dev/null" || true)"
    if [[ -n "$user_conda" && -x "$user_conda" ]]; then
        echo "$user_conda"
        return 0
    fi

    # 2. Check standard user and system paths
    for dir in "${TARGET_HOME}/miniconda3" "${TARGET_HOME}/miniforge3" "${TARGET_HOME}/anaconda3" "${TARGET_HOME}/.conda" "/opt/conda"; do
        if [[ -x "${dir}/bin/conda" ]]; then
            echo "${dir}/bin/conda"
            return 0
        fi
    done

    # Default fallback when installing fresh Miniforge
    echo "${TARGET_HOME}/miniforge3/bin/conda"
}

resolve_conda_env_path() {
    local env_name="${1:-isaaclab}"
    detect_target_user
    local conda_bin
    conda_bin="$(resolve_conda_bin)"
    local conda_root
    conda_root="$(dirname "$(dirname "$conda_bin")")"
    echo "${conda_root}/envs/${env_name}"
}

check_python_env() {
    local py_ver
    py_ver="$(resolve_target_python_version)"
    local conda_bin
    conda_bin="$(resolve_conda_bin)"
    local env_path
    env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"

    local missing=()
    command -v uv &>/dev/null || missing+=("uv package manager")
    [[ -x "${conda_bin}" ]] || missing+=("Conda binary (${conda_bin})")
    [[ -d "${env_path}" && -x "${env_path}/bin/python" ]] || missing+=("Conda environment '${CONDA_ENV_NAME}' (Python ${py_ver})")
    [[ -f "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh" ]] || missing+=("Conda activation hooks")
    command -v isaaclab-env &>/dev/null || missing+=("isaaclab-env CLI shim")

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Hybrid Conda '${CONDA_ENV_NAME}' (Python ${py_ver}) + UV and clean activation hooks already configured at ${env_path}"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_python_env() {
    log_step "Configuring Named Conda Environment ('${CONDA_ENV_NAME}') via Official Option A Pipeline..."
    detect_target_user

    local py_ver
    py_ver="$(resolve_target_python_version)"
    local conda_bin
    conda_bin="$(resolve_conda_bin)"
    local conda_root
    conda_root="$(dirname "$(dirname "$conda_bin")")"
    local sim_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"
    local lab_dir
    lab_dir="$(resolve_active_repo_dir "IsaacLab" 2>/dev/null || resolve_repo_dest_path "IsaacLab" 2>/dev/null || echo "")"

    # 1. Clean up any legacy or orphaned /opt/conda system directory and environments.txt entries
    if [[ -d "/opt/conda" ]]; then
        log_info "Purging orphaned system /opt/conda to maintain pure user miniconda3 runtime..."
        rm -rf /opt/conda 2>/dev/null || true
    fi
    for env_txt in "${TARGET_HOME}/.conda/environments.txt" "/root/.conda/environments.txt"; do
        if [[ -f "$env_txt" ]]; then
            sed -i '\|/opt/conda|d' "$env_txt" 2>/dev/null || true
        fi
    done

    # 2. Install Miniforge if no user Conda exists
    if [[ ! -x "${conda_bin}" ]]; then
        log_info "No Conda installation detected. Installing Miniforge into ${conda_root}..."
        local installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
        wget -q -O /tmp/miniforge.sh "${installer_url}"
        sudo -H -u "${TARGET_USER}" bash /tmp/miniforge.sh -b -p "${conda_root}"
        rm -f /tmp/miniforge.sh
        sudo -H -u "${TARGET_USER}" "${conda_bin}" init bash 2>/dev/null || true
    else
        log_info "Using detected target user Conda runtime: ${conda_bin}"
    fi

    # 3. Create Named Conda Environment using Option A (Official ./isaaclab.sh --conda)
    local env_path
    env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"

    # Zombie Environment Health Guard
    if [[ -d "${env_path}" ]]; then
        log_info "Checking health of existing Conda environment '${CONDA_ENV_NAME}'..."
        if ! sudo -H -u "${TARGET_USER}" "${conda_bin}" run -n "${CONDA_ENV_NAME}" python --version &>/dev/null; then
            log_warn "Detected broken or corrupted Conda environment '${CONDA_ENV_NAME}'. Purging for clean recreation..."
            sudo -H -u "${TARGET_USER}" "${conda_bin}" env remove -n "${CONDA_ENV_NAME}" -y 2>/dev/null || true
            rm -rf "${env_path}" 2>/dev/null || true
        fi
    fi

    if [[ ! -d "${env_path}" || ! -x "${env_path}/bin/python" ]]; then
        if [[ -n "$lab_dir" && -f "${lab_dir}/isaaclab.sh" ]]; then
            log_info "Delegating environment creation to official ./isaaclab.sh --conda '${CONDA_ENV_NAME}'..."
            sudo -H -u "${TARGET_USER}" bash -l -c "
                export SHELL=/bin/bash
                export USER='${TARGET_USER}'
                export HOME='${TARGET_HOME}'
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || eval \"\$('${conda_bin}' shell.bash hook 2>/dev/null)\" || true
                cd '${lab_dir}'
                SHELL=/bin/bash ./isaaclab.sh --conda '${CONDA_ENV_NAME}'
            " || true
        fi
        
        # Fallback if ./isaaclab.sh was unavailable or creation needed direct conda create
        env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"
        if [[ ! -d "${env_path}" || ! -x "${env_path}/bin/python" ]]; then
            log_info "Creating native named Conda environment '${CONDA_ENV_NAME}' (Python ${py_ver}) via conda binary..."
            sudo -H -u "${TARGET_USER}" "${conda_bin}" create -y -n "${CONDA_ENV_NAME}" python="${py_ver}" pip
        fi
        
        sudo -H -u "${TARGET_USER}" "${conda_bin}" config --append envs_dirs "${conda_root}/envs" 2>/dev/null || true
        env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"
    else
        log_info "Named Conda environment '${CONDA_ENV_NAME}' is healthy at ${env_path}."
        sudo -H -u "${TARGET_USER}" "${conda_bin}" config --append envs_dirs "${conda_root}/envs" 2>/dev/null || true
    fi

    # 5. Configure Scoped Activation Hooks (Guarantees Zero Global Shell Contamination)
    log_info "Configuring scoped Conda activation hooks in ${env_path}/etc/conda/..."
    sudo -H -u "${TARGET_USER}" mkdir -p "${env_path}/etc/conda/activate.d" "${env_path}/etc/conda/deactivate.d"

    cat << HOOK_ACT | sudo -H -u "${TARGET_USER}" tee "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh" >/dev/null
#!/usr/bin/env bash
# Scoped Omniverse Environment Variables (Active only while '${CONDA_ENV_NAME}' is activated)
export _OLD_ISAAC_EXP_PATH="\${EXP_PATH:-}"
export _OLD_ISAAC_PATH="\${ISAAC_PATH:-}"
export _OLD_CARB_APP_PATH="\${CARB_APP_PATH:-}"
export _OLD_VK_ICD_FILENAMES="\${VK_ICD_FILENAMES:-}"

export EXP_PATH="${sim_dir}/apps"
export ISAAC_PATH="${sim_dir}"
export CARB_APP_PATH="${sim_dir}/kit"
export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
HOOK_ACT
    chmod 755 "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh"

    cat << HOOK_DEACT | sudo -H -u "${TARGET_USER}" tee "${env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh" >/dev/null
#!/usr/bin/env bash
# Cleanly restore previous shell environment upon 'conda deactivate'
if [[ -n "\${_OLD_ISAAC_EXP_PATH}" ]]; then export EXP_PATH="\${_OLD_ISAAC_EXP_PATH}"; else unset EXP_PATH; fi
if [[ -n "\${_OLD_ISAAC_PATH}" ]]; then export ISAAC_PATH="\${_OLD_ISAAC_PATH}"; else unset ISAAC_PATH; fi
if [[ -n "\${_OLD_CARB_APP_PATH}" ]]; then export CARB_APP_PATH="\${_OLD_CARB_APP_PATH}"; else unset CARB_APP_PATH; fi
if [[ -n "\${_OLD_VK_ICD_FILENAMES}" ]]; then export VK_ICD_FILENAMES="\${_OLD_VK_ICD_FILENAMES}"; else unset VK_ICD_FILENAMES; fi
unset _OLD_ISAAC_EXP_PATH _OLD_ISAAC_PATH _OLD_CARB_APP_PATH _OLD_VK_ICD_FILENAMES
HOOK_DEACT
    chmod 755 "${env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh"

    # 6. Deploy Zero-Activation CLI Shim (/usr/local/bin/isaaclab-env)
    log_info "Deploying zero-activation CLI shim: /usr/local/bin/isaaclab-env..."
    cat << SHIM | sudo tee /usr/local/bin/isaaclab-env >/dev/null
#!/usr/bin/env bash
# ==============================================================================
# isaaclab-env - Scoped Runner for Headless Scripts, CI/CD, and Terminal Executions
# ==============================================================================
set -e

SIM_PATH="\${ISAACSIM_DIR:-\$HOME/IsaacSim}"
export EXP_PATH="\${SIM_PATH}/apps"
export ISAAC_PATH="\${SIM_PATH}"
export CARB_APP_PATH="\${SIM_PATH}/kit"
export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"

CONDA_PY="${env_path}/bin/python"

if [[ \$# -eq 0 ]]; then
    echo "Usage: isaaclab-env <command> [args...]"
    echo "Example: isaaclab-env python scripts/reinforcement_learning/rsl_rl/train.py --task Isaac-Ant-v0"
    exit 1
fi

if [[ "\$1" == "python" || "\$1" == "python3" ]]; then
    shift
    if [[ -x "\${CONDA_PY}" ]]; then
        export PATH="${env_path}/bin:\$PATH"
        exec "\${CONDA_PY}" "\$@"
    else
        exec python3 "\$@"
    fi
else
    if [[ -x "\${CONDA_PY}" ]]; then
        export PATH="${env_path}/bin:\$PATH"
    fi
    exec "\$@"
fi
SHIM
    sudo chmod 0755 /usr/local/bin/isaaclab-env

    # 7. Create template binary in bin/ for repository distribution
    mkdir -p "$(dirname "$0")/../bin"
    cp -f /usr/local/bin/isaaclab-env "$(dirname "$0")/../bin/isaaclab-env" 2>/dev/null || true
    chmod 0755 "$(dirname "$0")/../bin/isaaclab-env" 2>/dev/null || true

    log_success "Hybrid Python environment ('${CONDA_ENV_NAME}' at ${env_path} + UV + Scoped Hooks) ready."
}

