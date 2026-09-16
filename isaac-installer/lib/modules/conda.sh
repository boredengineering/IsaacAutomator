#!/usr/bin/env bash
# ==============================================================================
# conda.sh - Hybrid Conda Named Environment + UV Pip Engine & Activation Hooks
# ==============================================================================

CONDA_ENV_NAME="isaaclab"

# Selected commands use argv directly, including across the sudo boundary. The
# legacy run_as_user login-shell sanitizer interpolates HOME as shell source;
# pin-aware installs must not pass profile paths through that old boundary.
run_profile_argv() {
    detect_target_user
    if command -v sudo &>/dev/null && [[ "$EUID" -eq 0 && "${TARGET_USER}" != root && "${TARGET_USER}" != "${USER:-}" ]]; then
        sudo -H -u "$TARGET_USER" -- "$@"
    else
        "$@"
    fi
}

# Shared-profile runtime consumer. Called by install_python_env instead of the
# legacy auto-detection/upgrade path. Deliberately no automatic pin substitution.
install_profile_lab_runtime() {
    # Other legacy modules still bind to isaaclab. Refuse an identity that they
    # cannot consistently consume, rather than installing into the wrong env.
    if [[ "${CONDA_ENV_NAME}" != isaaclab ]]; then
        log_error 'Local Lab environment must be isaaclab; arbitrary identities are not integrated.'
        return 1
    fi
    local pin
    for pin in "${LAB_TORCH_VERSION:-}" "${LAB_TORCHVISION_VERSION:-}"; do
        if [[ -n "$pin" && ! "$pin" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\+cu[0-9]+)?$ ]]; then
            log_error 'Invalid explicit PyTorch wheel version.'; return 1
        fi
        if [[ -n "${LAB_CUDA_RUNTIME:-}" && "$pin" == *+cu* && "${pin##*+cu}" != "${LAB_CUDA_RUNTIME//./}" ]]; then
            log_error 'CUDA wheel channel conflicts with explicit wheel pin.'; return 1
        fi
    done
    if [[ -n "${LAB_CUDA_RUNTIME:-}" && ! "$LAB_CUDA_RUNTIME" =~ ^[0-9]+\.[0-9]+$ ]]; then
        log_error 'CUDA wheel channel requires major.minor.'; return 1
    fi
    if [[ -n "${LAB_ARCHITECTURE:-}" && ( ! "${GPU_COMPUTE_CAP:-}" =~ ^[0-9]+\.[0-9]+$ || "sm_${GPU_COMPUTE_CAP//./}" != "$LAB_ARCHITECTURE" ) ]]; then
        log_error 'Requested GPU architecture is missing or mismatches the observed target.'; return 1
    fi
    if [[ -n "${LAB_PYTHON_VERSION:-}" && ! "$LAB_PYTHON_VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
        log_error 'Invalid explicit Python version.'; return 1
    fi
    local package package_name
    local -a packages=()
    while IFS= read -r package; do
        [[ -n "$package" ]] || continue
        if [[ ! "$package" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*==[0-9]+\.[0-9]+[A-Za-z0-9.+-]*$ ]]; then
            log_error 'Custom dependencies require exact PyPI name==version pins.'; return 1
        fi
        package_name="${package%%==*}"
        case "${package_name,,}" in
            torch|torchvision|python|pip|uv) log_error 'Custom dependency cannot override runtime pins.'; return 1 ;;
        esac
        packages+=("$package")
    done <<< "${LAB_CUSTOM_PACKAGES:-}"
    local conda_bin env_path actual_python
    conda_bin="$(resolve_conda_bin)" || return $?
    env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")" || return $?
    if [[ ! -x "${env_path}/bin/python" ]]; then
        if [[ ! -x "$conda_bin" || -z "${LAB_PYTHON_VERSION:-}" ]]; then
            log_error 'Explicit Lab runtime creation requires Conda and a Python pin.'; return 1
        fi
        # isaaclab.sh --conda chooses its own Python from Sim; it has no Python
        # pin argument. Direct prefix creation is intentional, not a fallback.
        run_profile_argv env -u LD_LIBRARY_PATH CONDA_NO_PLUGINS=true \
            CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes CONDA_SOLVER=classic \
            "$conda_bin" create -y --prefix "$env_path" "python=${LAB_PYTHON_VERSION}" pip -c conda-forge || return $?
    fi
    actual_python="$(run_profile_argv "${env_path}/bin/python" -c 'import platform; print(platform.python_version())')" || return $?
    if [[ -n "${LAB_PYTHON_VERSION:-}" && "$actual_python" != "$LAB_PYTHON_VERSION" && "$actual_python" != "$LAB_PYTHON_VERSION".* ]]; then
        log_error 'Existing Python does not match requested pin; refusing implicit replacement.'; return 1
    fi
    local -a wheels=()
    [[ -z "${LAB_TORCH_VERSION:-}" ]] || wheels+=("torch==${LAB_TORCH_VERSION}")
    [[ -z "${LAB_TORCHVISION_VERSION:-}" ]] || wheels+=("torchvision==${LAB_TORCHVISION_VERSION}")
    if [[ ${#wheels[@]} -gt 0 ]]; then
        local -a channel=()
        [[ -z "${LAB_CUDA_RUNTIME:-}" ]] || channel=(--index-url "https://download.pytorch.org/whl/cu${LAB_CUDA_RUNTIME//./}")
        run_profile_argv "${env_path}/bin/python" -m pip install "${channel[@]}" -- "${wheels[@]}" || return $?
    fi
    if [[ ${#packages[@]} -gt 0 ]]; then
        # Reviewed direct packages only: dependency resolution must not silently
        # replace the pinned runtime. Missing transitive packages remain explicit.
        run_profile_argv "${env_path}/bin/python" -m pip install --no-deps -- "${packages[@]}" || return $?
    fi
}

# Pin-aware source installs never inherit a login shell's unrelated Python.
profile_lab_pins_selected() {
    [[ -v CFG_RUNTIMES_LAB_ENVIRONMENT || -n "${LAB_PYTHON_VERSION:-}${LAB_TORCH_VERSION:-}${LAB_TORCHVISION_VERSION:-}${LAB_CUDA_RUNTIME:-}${LAB_ARCHITECTURE:-}${LAB_CUSTOM_PACKAGES:-}" ]]
}

# Metadata only: do not import torch (or initialize a GPU) to prove wheel pins.
# Unspecified wheel versions are frozen at their observed pre-pipeline versions,
# not replaced with guessed compatibility defaults. Each run owns a fresh 0700
# temporary directory and exclusive 0600 files; user paths are never overwritten.
profile_lab_metadata() {
    local mode="$1" env_path="$2" constraints="${3:-}"
    run_profile_argv env -u PYTHONPATH -u PYTHONHOME "${env_path}/bin/python" -I -c '
import importlib.metadata as metadata
import json, os, pathlib, platform, re, sys, tempfile
mode, prefix, python_pin, torch_pin, vision_pin, constraints = sys.argv[1:]
if os.path.realpath(sys.prefix) != os.path.realpath(prefix):
    raise SystemExit("Selected Lab environment prefix mismatch")
actual_python = platform.python_version()
if python_pin and not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", python_pin):
    raise SystemExit("Invalid Python pin")
if python_pin and actual_python != python_pin and not actual_python.startswith(python_pin + "."):
    raise SystemExit("Selected Lab Python does not match pin")
versions = {name: metadata.version(name) for name in ("torch", "torchvision")}
for name, requested in (("torch", torch_pin), ("torchvision", vision_pin)):
    if requested and versions[name] != requested:
        raise SystemExit(name + " metadata does not match selected pin")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\+[A-Za-z0-9.]+)?", versions[name]):
        raise SystemExit("Unsupported wheel version for constraint: " + name)
state = dict(python=actual_python, versions=versions)
if mode == "prepare":
    directory = pathlib.Path(tempfile.mkdtemp(prefix="isaac-lab-pins-", dir="/tmp"))
    path = directory / "constraints.txt"
    for target, content in ((path, "".join(k + "==" + v + "\n" for k, v in versions.items())), (directory / "runtime.json", json.dumps(state))):
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
    print(path)
elif mode == "verify":
    expected = json.loads(pathlib.Path(constraints).with_name("runtime.json").read_text())
    if state != expected:
        raise SystemExit("Lab runtime changed during dependency installation")
elif mode != "validate":
    raise SystemExit("Unknown conformance operation")
' "$mode" "$env_path" "${LAB_PYTHON_VERSION:-}" "${LAB_TORCH_VERSION:-}" "${LAB_TORCHVISION_VERSION:-}" "$constraints"
}

profile_lab_source_preflight() {
    if [[ "${CONDA_ENV_NAME}" != isaaclab ]]; then
        log_error 'Local Lab environment must be isaaclab; refusing a different selected environment.'
        return 1
    fi
    local conda_bin env_path
    conda_bin="$(resolve_conda_bin)" || return $?
    env_path="$(resolve_conda_env_path "$CONDA_ENV_NAME")" || return $?
    if [[ ! -x "$conda_bin" || ! -x "$env_path/bin/python" ]]; then
        log_error 'Pinned Lab source installation requires an existing selected Conda runtime.'
        return 1
    fi
    profile_lab_metadata validate "$env_path"
}

resolve_target_python_version() {
    if [[ -n "${LAB_PYTHON_VERSION:-}" ]]; then
        printf '%s\n' "$LAB_PYTHON_VERSION"
        return 0
    fi
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
    if profile_lab_pins_selected; then
        user_conda="$(run_profile_argv /bin/bash -c 'command -v conda' 2>/dev/null)" || user_conda=""
    else
        user_conda="$(run_as_user "command -v conda 2>/dev/null" || true)"
    fi
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
    if [[ -v CFG_RUNTIMES_LAB_ENVIRONMENT || -n "${LAB_PYTHON_VERSION:-}${LAB_TORCH_VERSION:-}${LAB_TORCHVISION_VERSION:-}${LAB_CUDA_RUNTIME:-}${LAB_ARCHITECTURE:-}${LAB_CUSTOM_PACKAGES:-}" ]]; then
        STAGE_CHECK_MSG='Explicit Lab pins require runtime revalidation; existence is not conformance.'
        return 1
    fi
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
    # Resolver refusal is fatal in every layout, before cleanup or installation.
    lab_dir="$(resolve_active_repo_dir "IsaacLab" "${ISAACLAB_REPO:-}" "${ISAACLAB_DIR:-}")" || return $?

    # Pinned profiles bypass legacy cleanup, native-helper defaults and automatic
    # hardware wheel upgrades. Named repository rejection above still runs first.
    if [[ -v CFG_RUNTIMES_LAB_ENVIRONMENT || -n "${LAB_PYTHON_VERSION:-}${LAB_TORCH_VERSION:-}${LAB_TORCHVISION_VERSION:-}${LAB_CUDA_RUNTIME:-}${LAB_ARCHITECTURE:-}" ]]; then
        install_profile_lab_runtime || return $?
        configure_python_env_hooks "$(resolve_conda_env_path "${CONDA_ENV_NAME}")" || return $?
        return 0
    fi

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
        run_as_user "bash /tmp/miniforge.sh -b -p '${conda_root}'"
        rm -f /tmp/miniforge.sh
        run_as_user "'${conda_bin}' init bash 2>/dev/null || true"
    else
        log_info "Using detected target user Conda runtime: ${conda_bin}"
    fi

    # 3. Create Named Conda Environment using Option A (Official ./isaaclab.sh --conda)
    local env_path
    env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"

    # Zombie Environment Health Guard
    if [[ -d "${env_path}" ]]; then
        log_info "Checking health of existing Conda environment '${CONDA_ENV_NAME}'..."
        if ! run_as_user "'${conda_bin}' run -n '${CONDA_ENV_NAME}' python --version &>/dev/null"; then
            log_warn "Detected broken or corrupted Conda environment '${CONDA_ENV_NAME}'. Purging for clean recreation..."
            run_as_user "'${conda_bin}' env remove -n '${CONDA_ENV_NAME}' -y 2>/dev/null || true"
            rm -rf "${env_path}" 2>/dev/null || true
        fi
    fi

    # Pre-configure Conda ToS auto-acceptance, classic solver & conda-forge priority
    run_as_user "
        unset LD_LIBRARY_PATH
        export CONDA_NO_PLUGINS=true
        export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
        export CONDA_SOLVER=classic
        '${conda_bin}' config --set auto_accept_tos true 2>/dev/null || true
        '${conda_bin}' config --set solver classic 2>/dev/null || true
        '${conda_bin}' config --add channels conda-forge 2>/dev/null || true
        '${conda_bin}' tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main 2>/dev/null || true
        '${conda_bin}' tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r 2>/dev/null || true
        # Repair / reinstall pydantic and pydantic-core in base to restore compiled Rust C-extensions
        if [[ -x '${conda_root}/bin/pip' ]]; then
            '${conda_root}/bin/pip' install --force-reinstall pydantic pydantic-core 2>/dev/null || true
        fi
    " || true

    if [[ ! -d "${env_path}" || ! -x "${env_path}/bin/python" ]]; then
        if [[ -n "$lab_dir" && -f "${lab_dir}/isaaclab.sh" ]]; then
            log_info "Delegating environment creation to official ./isaaclab.sh --conda '${CONDA_ENV_NAME}'..."
            run_as_user "
                export SHELL=/bin/bash
                export USER='${TARGET_USER}'
                export HOME='${TARGET_HOME}'
                export CONDA_NO_PLUGINS=true
                export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
                export CONDA_SOLVER=classic
                unset LD_LIBRARY_PATH
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || eval \"\$('${conda_bin}' shell.bash hook 2>/dev/null)\" || true
                cd '${lab_dir}'
                SHELL=/bin/bash ./isaaclab.sh --conda '${CONDA_ENV_NAME}'
            " || true
        fi
        
        # Fallback if ./isaaclab.sh was unavailable or creation needed direct conda create
        env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"
        if [[ ! -d "${env_path}" || ! -x "${env_path}/bin/python" ]]; then
            log_info "Creating native named Conda environment '${CONDA_ENV_NAME}' (Python ${py_ver}) via conda binary..."
            run_as_user "
                export CONDA_NO_PLUGINS=true
                export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
                export CONDA_SOLVER=classic
                unset LD_LIBRARY_PATH
                '${conda_bin}' create -y -n '${CONDA_ENV_NAME}' python='${py_ver}' pip -c conda-forge
            "
        fi
        
        run_as_user "'${conda_bin}' config --append envs_dirs '${conda_root}/envs' 2>/dev/null || true"
        env_path="$(resolve_conda_env_path "${CONDA_ENV_NAME}")"
    else
        log_info "Named Conda environment '${CONDA_ENV_NAME}' is healthy at ${env_path}."
        run_as_user "'${conda_bin}' config --append envs_dirs '${conda_root}/envs' 2>/dev/null || true"
    fi

    # 4b. Ensure PyTorch matching hardware architecture is installed (Blackwell cu128 vs Ada/Hopper)
    local torch_channel="${TORCH_WHEEL_CHANNEL:-https://download.pytorch.org/whl/cu124}"
    local torch_spec="${TORCH_VERSION_SPEC:-torch==2.5.1+cu124 torchvision==0.20.1+cu124}"
    if [[ "${HAS_BLACKWELL:-false}" == true || "${GPU_COMPUTE_CAP%%.*}" -ge 12 ]]; then
        torch_channel="https://download.pytorch.org/whl/cu128"
        torch_spec="torch==2.10.0+cu128 torchvision==0.25.0+cu128"
    fi
    log_info "Ensuring PyTorch matching GPU architecture is installed (${torch_spec})..."
    run_as_user "
        '${env_path}/bin/python' -m pip install --upgrade pip uv 2>/dev/null || true
        '${env_path}/bin/python' -m pip install ${torch_spec} --index-url '${torch_channel}' 2>/dev/null || true
    " || true

    configure_python_env_hooks "$env_path"
}

configure_python_env_hooks() {
    local env_path="$1"
    # 5. Configure Scoped Activation Hooks (Guarantees Zero Global Shell Contamination)
    log_info "Configuring scoped Conda activation hooks in ${env_path}/etc/conda/..."
    run_profile_argv mkdir -p "${env_path}/etc/conda/activate.d" "${env_path}/etc/conda/deactivate.d" || return $?

    local vk_icd=""
    for icd_candidate in /usr/share/vulkan/icd.d/nvidia_icd.json \
                         /etc/vulkan/icd.d/nvidia_icd.json \
                         /usr/share/vulkan/icd.d/nvidia.json \
                         /etc/vulkan/icd.d/nvidia.json; do
        if [[ -f "$icd_candidate" ]]; then
            vk_icd="$icd_candidate"
            break
        fi
    done

    local vk_line=""
    if [[ -n "$vk_icd" ]]; then
        vk_line="export VK_ICD_FILENAMES=\"${vk_icd}\""
    else
        vk_line="# VK_ICD_FILENAMES unset (using Vulkan loader auto-discovery)"
    fi

    cat << 'HOOK_ACT' | run_as_user_stdin "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh"
#!/usr/bin/env bash
# Scoped Omniverse Environment Variables (Active only while Conda environment is activated)
export _OLD_ISAAC_EXP_PATH="${EXP_PATH:-}"
export _OLD_ISAAC_PATH="${ISAAC_PATH:-}"
export _OLD_CARB_APP_PATH="${CARB_APP_PATH:-}"
export _OLD_VK_ICD_FILENAMES="${VK_ICD_FILENAMES:-}"

export EXP_PATH="${ISAAC_PATH:-$HOME/IsaacSim}/apps"
export ISAAC_PATH="${ISAAC_PATH:-$HOME/IsaacSim}"
export CARB_APP_PATH="${ISAAC_PATH}/kit"

# Dynamic Vulkan ICD Manifest Resolution (Avoids hardcoded path failures across driver updates)
if [ -f /usr/share/vulkan/icd.d/nvidia_icd.json ]; then
    export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia_icd.json"
elif [ -f /etc/vulkan/icd.d/nvidia_icd.json ]; then
    export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
elif [ -f /usr/share/vulkan/icd.d/nvidia.json ]; then
    export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia.json"
elif [ -f /etc/vulkan/icd.d/nvidia.json ]; then
    export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia.json"
else
    unset VK_ICD_FILENAMES
fi
HOOK_ACT
    chmod 755 "${env_path}/etc/conda/activate.d/00_isaaclab_env.sh" 2>/dev/null || true

    cat << 'HOOK_DEACT' | run_as_user_stdin "${env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh"
#!/usr/bin/env bash
# Cleanly restore previous shell environment upon 'conda deactivate'
if [[ -n "${_OLD_ISAAC_EXP_PATH}" ]]; then export EXP_PATH="${_OLD_ISAAC_EXP_PATH}"; else unset EXP_PATH; fi
if [[ -n "${_OLD_ISAAC_PATH}" ]]; then export ISAAC_PATH="${_OLD_ISAAC_PATH}"; else unset ISAAC_PATH; fi
if [[ -n "${_OLD_CARB_APP_PATH}" ]]; then export CARB_APP_PATH="${_OLD_CARB_APP_PATH}"; else unset CARB_APP_PATH; fi
if [[ -n "${_OLD_VK_ICD_FILENAMES}" ]]; then export VK_ICD_FILENAMES="${_OLD_VK_ICD_FILENAMES}"; else unset VK_ICD_FILENAMES; fi
unset _OLD_ISAAC_EXP_PATH _OLD_ISAAC_PATH _OLD_CARB_APP_PATH _OLD_VK_ICD_FILENAMES
unset PYTHONPATH
HOOK_DEACT
    chmod 755 "${env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh" 2>/dev/null || true

    # 6. Deploy Zero-Activation CLI Shim (/usr/local/bin/isaaclab-env)
    log_info "Deploying zero-activation CLI shim: /usr/local/bin/isaaclab-env..."
    cat << SHIM | run_as_root "tee /usr/local/bin/isaaclab-env >/dev/null"
#!/usr/bin/env bash
# ==============================================================================
# isaaclab-env - Scoped Runner for Headless Scripts, CI/CD, and Terminal Executions
# ==============================================================================
set -e

SIM_PATH="\${ISAACSIM_DIR:-\$HOME/IsaacSim}"
export EXP_PATH="\${SIM_PATH}/apps"
export ISAAC_PATH="\${SIM_PATH}"
export CARB_APP_PATH="\${SIM_PATH}/kit"

if [ -f /usr/share/vulkan/icd.d/nvidia_icd.json ]; then
    export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia_icd.json"
elif [ -f /etc/vulkan/icd.d/nvidia_icd.json ]; then
    export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
elif [ -f /usr/share/vulkan/icd.d/nvidia.json ]; then
    export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia.json"
elif [ -f /etc/vulkan/icd.d/nvidia.json ]; then
    export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia.json"
else
    unset VK_ICD_FILENAMES
fi

# Dynamic Conda Python Resolution (Bakes installed path with candidate search fallback)
CONDA_PY="${env_path}/bin/python"
if [[ ! -x "\${CONDA_PY}" ]]; then
    for cand in "\$HOME/miniconda3/envs/isaaclab" "\$HOME/.conda/envs/isaaclab" "\$HOME/miniforge3/envs/isaaclab" "/opt/conda/envs/isaaclab"; do
        if [[ -x "\${cand}/bin/python" ]]; then
            CONDA_PY="\${cand}/bin/python"
            break
        fi
    done
fi

ENV_BIN="\$(dirname "\${CONDA_PY}")"

if [[ \$# -eq 0 ]]; then
    echo "Usage: isaaclab-env <command> [args...]"
    echo "Example: isaaclab-env python scripts/reinforcement_learning/rsl_rl/train.py --task Isaac-Ant-v0"
    exit 1
fi

if [[ "\$1" == "python" || "\$1" == "python3" ]]; then
    shift
    if [[ -x "\${CONDA_PY}" ]]; then
        export PATH="\${ENV_BIN}:\$PATH"
        exec "\${CONDA_PY}" "\$@"
    else
        exec python3 "\$@"
    fi
else
    if [[ -x "\${CONDA_PY}" ]]; then
        export PATH="\${ENV_BIN}:\$PATH"
    fi
    exec "\$@"
fi
SHIM
    run_as_root "chmod 0755 /usr/local/bin/isaaclab-env"

    # 7. Create template binary in bin/ for repository distribution
    mkdir -p "$(dirname "$0")/../bin"
    cp -f /usr/local/bin/isaaclab-env "$(dirname "$0")/../bin/isaaclab-env" 2>/dev/null || true
    chmod 0755 "$(dirname "$0")/../bin/isaaclab-env" 2>/dev/null || true

    log_success "Hybrid Python environment ('${CONDA_ENV_NAME}' at ${env_path} + UV + Scoped Hooks) ready."
}

