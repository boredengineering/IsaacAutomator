#!/usr/bin/env bash
# ==============================================================================
# audit.sh - Deep Component Audit, Version Comparison & Conflict Detection Engine
# ==============================================================================

# Audit a single component
# Output format: Component | Current Version | Target Version | Status | Conflict/Risk
audit_all_components() {
    AUDIT_RESULTS=()
    CONFLICTS_FOUND=0
    UPGRADES_FOUND=0
    INSTALLS_FOUND=0
    SATISFIED_COUNT=0

    # 1. Package Manager / DPKG Health
    local dpkg_status="Healthy"
    local dpkg_risk="None"
    if [[ -f /var/lib/dpkg/lock-frontend || -f /var/lib/apt/lists/lock ]]; then
        dpkg_status="Apt Locked"
        dpkg_risk="Apt is currently locked by another process"
        CONFLICTS_FOUND=$((CONFLICTS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("System Package Lock|${dpkg_status}|Unlocked|${dpkg_status}|${dpkg_risk}")

    # 2. Disk Space
    detect_disk_space
    local disk_status="Sufficient (${FREE_DISK_GB} GB)"
    local disk_risk="None"
    if [[ "$FREE_DISK_GB" -lt 60 ]]; then
        disk_status="Low Space (${FREE_DISK_GB} GB)"
        disk_risk="Requires at least 60 GB free for Isaac Sim extraction"
        CONFLICTS_FOUND=$((CONFLICTS_FOUND + 1))
    else
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    fi
    AUDIT_RESULTS+=("Free Disk Space|${FREE_DISK_GB} GB|>= 60 GB|${disk_status}|${disk_risk}")

    # 3. GPU Driver & Blackwell Compatibility
    detect_gpu
    local driver_cur="${DRIVER_VERSION}"
    local driver_target=">= ${RECOMMENDED_DRIVER}"
    local driver_status="Missing"
    local driver_risk="None"

    if [[ "$DRIVER_INSTALLED" == true ]]; then
        local major_ver
        major_ver="$(echo "$DRIVER_VERSION" | cut -d'.' -f1)"
        if [[ "$major_ver" -ge "$RECOMMENDED_DRIVER" ]]; then
            driver_status="UP_TO_DATE"
            SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
        else
            driver_status="UPGRADE_REQUIRED"
            driver_risk="Driver v${DRIVER_VERSION} is below ${RECOMMENDED_DRIVER} for ${GPU_NAME}"
            UPGRADES_FOUND=$((UPGRADES_FOUND + 1))
        fi
    else
        driver_status="MISSING"
        driver_risk="GPU hardware present but driver not loaded"
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("NVIDIA GPU Driver|${driver_cur}|${driver_target}|${driver_status}|${driver_risk}")

    # 4. Display Server & Wayland
    detect_display
    local display_cur="X11"
    local display_risk="None"
    local display_status="UP_TO_DATE"
    if [[ "$IS_WAYLAND" == true ]]; then
        display_cur="Wayland Active"
        display_status="CONFLICT"
        display_risk="Wayland causes Vulkan swapchain jitter in Omniverse"
        CONFLICTS_FOUND=$((CONFLICTS_FOUND + 1))
    else
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    fi
    AUDIT_RESULTS+=("Display Server Session|${display_cur}|X11|${display_status}|${display_risk}")

    # 5. Compilers (GCC / G++)
    local gcc_cur="None"
    local gcc_status="MISSING"
    local gcc_risk="None"
    if command -v gcc &>/dev/null; then
        gcc_cur="$(gcc -dumpversion 2>/dev/null || echo "Unknown")"
        if [[ "$gcc_cur" == 11* ]]; then
            gcc_status="UP_TO_DATE"
            SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
        else
            gcc_status="ALTERNATIVE_NEEDED"
            gcc_risk="GCC ${gcc_cur} active (Omniverse C++ requires GCC 11)"
            UPGRADES_FOUND=$((UPGRADES_FOUND + 1))
        fi
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Default Compiler (GCC)|${gcc_cur}|GCC 11.x|${gcc_status}|${gcc_risk}")

    # 6. Vulkan Runtime & Headers
    local vulkan_cur="Missing"
    local vulkan_status="MISSING"
    local vulkan_risk="None"
    if pkg_is_installed "libvulkan-dev" 2>/dev/null; then
        vulkan_cur="Installed"
        vulkan_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Vulkan Dev Headers|${vulkan_cur}|Installed|${vulkan_status}|${vulkan_risk}")

    # 7. Git LFS
    local lfs_cur="Missing"
    local lfs_status="MISSING"
    local lfs_risk="None"
    if command -v git-lfs &>/dev/null; then
        lfs_cur="$(git lfs version 2>/dev/null | awk '{print $1}' | cut -d/ -f2 || echo "Installed")"
        lfs_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        lfs_risk="Without Git LFS, 3D meshes will clone as empty text pointers"
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Git Large File Storage|${lfs_cur}|Installed|${lfs_status}|${lfs_risk}")

    # 8. Hybrid Conda & UV Toolchain
    local py_cur="Missing"
    local py_status="MISSING"
    local py_risk="None"
    local py_target="Miniforge + UV"
    local conda_bin="$(resolve_conda_bin 2>/dev/null || echo "")"
    local env_path="$(resolve_conda_env_path "isaaclab" 2>/dev/null || echo "")"
    if [[ -x "$conda_bin" && -d "$env_path" ]]; then
        if command -v uv &>/dev/null; then
            py_cur="Conda ('isaaclab') + UV"
            py_status="UP_TO_DATE"
            SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
        else
            py_cur="Conda ('isaaclab') (UV missing)"
            py_status="UPGRADES_NEEDED"
            py_risk="UV missing; package installation will be slow"
            UPGRADES_FOUND=$((UPGRADES_FOUND + 1))
        fi
    elif command -v uv &>/dev/null; then
        py_cur="UV only (Conda missing)"
        py_status="UPGRADES_NEEDED"
        py_risk="Named 'isaaclab' Conda environment not yet created"
        UPGRADES_FOUND=$((UPGRADES_FOUND + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Hybrid Python Environment|${py_cur}|${py_target}|${py_status}|${py_risk}")

    # 8. Docker Engine & NVIDIA Container Toolkit
    local docker_cur="Missing"
    local docker_status="MISSING"
    local docker_risk="None"
    if command -v docker &>/dev/null; then
        docker_cur="$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' || echo "Installed")"
        if command -v nvidia-ctk &>/dev/null; then
            docker_status="UP_TO_DATE"
            SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
        else
            docker_status="GPU_HOOK_MISSING"
            docker_risk="Docker installed but nvidia-ctk GPU passthrough missing"
            UPGRADES_FOUND=$((UPGRADES_FOUND + 1))
        fi
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Docker CE & NVIDIA Toolkit|${docker_cur}|Docker + nvidia-ctk|${docker_status}|${docker_risk}")

    # 9. Visual Studio Code
    local code_cur="Missing"
    local code_status="MISSING"
    local code_risk="None"
    if command -v code &>/dev/null; then
        code_cur="$(code --version 2>/dev/null | head -n 1 || echo "Installed")"
        code_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Visual Studio Code|${code_cur}|Latest Stable|${code_status}|${code_risk}")

    # 10. Hardware-Accelerated Browser
    local browser_cur="Missing"
    local browser_status="MISSING"
    local browser_risk="None"
    if command -v google-chrome &>/dev/null; then
        browser_cur="Google Chrome"
        browser_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    elif command -v chromium-browser &>/dev/null || command -v chromium &>/dev/null; then
        browser_cur="Chromium"
        browser_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("WebXR/Foxglove Browser|${browser_cur}|Chrome / Chromium|${browser_status}|${browser_risk}")

    # Cloud CLIs (AWS & GCP)
    local aws_cur="Missing"
    local aws_status="OPTIONAL"
    if command -v aws &>/dev/null; then
        aws_cur="$(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2 || echo "Installed")"
        aws_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    fi
    AUDIT_RESULTS+=("AWS CLI v2|${aws_cur}|Installed|${aws_status}|None")

    local gcp_cur="Missing"
    local gcp_status="OPTIONAL"
    if command -v gcloud &>/dev/null; then
        gcp_cur="Installed"
        gcp_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    fi
    AUDIT_RESULTS+=("Google Cloud SDK (gcloud)|${gcp_cur}|Installed|${gcp_status}|None")

    # NVMe CLI & LVM Storage Subsystem
    local storage_cur="Missing"
    local storage_status="MISSING"
    if command -v nvme &>/dev/null && command -v lvm &>/dev/null; then
        storage_cur="nvme + lvm2 active"
        storage_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    elif command -v nvme &>/dev/null; then
        storage_cur="nvme-cli installed"
        storage_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("NVMe & LVM Storage Tools|${storage_cur}|nvme-cli + lvm2|${storage_status}|None")

    # 11. Hugging Face CLI & LeRobot Visualizer
    local hfcli_cur="Missing"
    local hfcli_status="MISSING"
    if command -v huggingface-cli &>/dev/null || command -v hf &>/dev/null; then
        hfcli_cur="Installed in PATH"
        hfcli_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Hugging Face CLI (hf)|${hfcli_cur}|Installed in PATH|${hfcli_status}|None")

    local lerobot_cur="Missing"
    local lerobot_status="MISSING"
    local lerobot_risk="None"
    if command -v lerobot-dataset-viz &>/dev/null; then
        lerobot_cur="Installed in PATH"
        lerobot_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("LeRobot Dataset Visualizer|${lerobot_cur}|lerobot[all,dataset_viz]|${lerobot_status}|${lerobot_risk}")

    # 12. FTDI 1ms Low-Latency Serial Rule (ALOHA / SO-100)
    local ftdi_cur="Missing"
    local ftdi_status="MISSING"
    local ftdi_risk="None"
    if [[ -f /etc/udev/rules.d/99-ftdi-latency.rules ]]; then
        ftdi_cur="Configured (1ms)"
        ftdi_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        ftdi_risk="Default Linux serial latency is 16ms (causes 10x lag in teleop arms)"
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("ALOHA/SO-100 1ms Latency|${ftdi_cur}|1ms Timer Rule|${ftdi_status}|${ftdi_risk}")

    # 13. Isaac Sim Engine
    local sim_dir
    sim_dir="$(resolve_isaacsim_dir 2>/dev/null || echo "${TARGET_HOME}/IsaacSim")"
    local sim_cur="Missing"
    local sim_status="MISSING"
    local sim_risk="None"
    if [[ -x "${sim_dir}/isaac-sim.sh" ]]; then
        sim_cur="Installed (${sim_dir})"
        sim_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("NVIDIA Isaac Sim Engine|${sim_cur}|v5.1.0 Standalone|${sim_status}|${sim_risk}")

    # 14. Isaac Lab Framework
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir 2>/dev/null || echo "${TARGET_HOME}/IsaacLab")"
    local lab_cur="Missing"
    local lab_status="MISSING"
    local lab_risk="None"
    if [[ -d "${lab_dir}" && -L "${lab_dir}/_isaac_sim" ]]; then
        lab_cur="Installed (${lab_dir})"
        lab_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("Isaac Lab Framework|${lab_cur}|Linked & Installed|${lab_status}|${lab_risk}")

    # 15. IsaacLab-Arena Benchmark Suite
    local arena_dir
    arena_dir="$(resolve_arena_dir 2>/dev/null || echo "${TARGET_HOME}/Documents/GitHub/BoredEngineer/IsaacLab-Arena")"
    local arena_cur="Missing"
    local arena_status="MISSING"
    local arena_risk="None"
    if [[ -d "${arena_dir}/.git" ]]; then
        arena_cur="Installed (${arena_dir})"
        arena_status="UP_TO_DATE"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("IsaacLab-Arena Suite|${arena_cur}|Linked & Installed|${arena_status}|${arena_risk}")

    # 16. NVIDIA Isaac-GR00T Foundation Model Stack
    local gr00t_dir
    gr00t_dir="$(resolve_gr00t_dir 2>/dev/null || echo "${TARGET_HOME}/Documents/GitHub/boredengineering/Isaac-GR00T")"
    local gr00t_cur="Missing"
    local gr00t_status="MISSING"
    local gr00t_risk="None"
    if [[ -d "${gr00t_dir}/.git" ]]; then
        if [[ -d "${gr00t_dir}/.venv" || -x "${gr00t_dir}/.venv/bin/python" ]]; then
            gr00t_cur="Installed (Python 3.12 .venv)"
            gr00t_status="UP_TO_DATE"
            SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
        else
            gr00t_cur="Cloned (uv sync pending)"
            gr00t_status="UPGRADES_NEEDED"
            gr00t_risk="uv virtual environment not yet synchronized"
            UPGRADES_FOUND=$((UPGRADES_FOUND + 1))
        fi
    else
        INSTALLS_FOUND=$((INSTALLS_FOUND + 1))
    fi
    AUDIT_RESULTS+=("NVIDIA Isaac-GR00T VLA|${gr00t_cur}|Python 3.12 + uv|${gr00t_status}|${gr00t_risk}")

    # 17. GitHub Hub Authentication
    local gh_auth_cur="Not Logged In"
    local gh_auth_status="OPTIONAL"
    local gh_auth_risk="Private robot URDFs/submodules may require auth"
    if command -v gh &>/dev/null; then
        if sudo -H -u "${TARGET_USER}" gh auth status &>/dev/null; then
            gh_auth_cur="Authenticated"
            gh_auth_status="UP_TO_DATE"
            gh_auth_risk="None"
            SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
        fi
    elif [[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]]; then
        gh_auth_cur="Authenticated (Env)"
        gh_auth_status="UP_TO_DATE"
        gh_auth_risk="None"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    fi
    AUDIT_RESULTS+=("GitHub Hub Login (gh)|${gh_auth_cur}|Authenticated|${gh_auth_status}|${gh_auth_risk}")

    # 18. Hugging Face Hub Authentication
    local hf_auth_cur="Not Logged In"
    local hf_auth_status="OPTIONAL"
    local hf_auth_risk="Uploading LeRobot teleop datasets requires auth"
    if [[ -f "${TARGET_HOME}/.cache/huggingface/token" || -n "${HF_TOKEN:-}" ]]; then
        hf_auth_cur="Authenticated"
        hf_auth_status="UP_TO_DATE"
        hf_auth_risk="None"
        SATISFIED_COUNT=$((SATISFIED_COUNT + 1))
    fi
    AUDIT_RESULTS+=("Hugging Face Hub (HF)|${hf_auth_cur}|Authenticated|${hf_auth_status}|${hf_auth_risk}")
}

# Pretty-print the audit diff matrix
print_audit_report() {
    log_header "Workstation Pre-Flight Audit & Conflict Analysis"
    audit_all_components

    printf "${CLR_BOLD}%-28s | %-18s | %-18s | %-16s | %-30s${CLR_RESET}\n" \
        "Component" "Host State" "Target State" "Action / Status" "Risk / Conflicts"
    echo "----------------------------------------------------------------------------------------------------------------------------------"

    for row in "${AUDIT_RESULTS[@]}"; do
        IFS='|' read -r comp host target status risk <<< "$row"
        
        local status_color="${CLR_RESET}"
        case "$status" in
            "UP_TO_DATE")           status_color="${CLR_GREEN}" ;;
            "MISSING")              status_color="${CLR_YELLOW}" ;;
            "UPGRADE_REQUIRED"|"ALTERNATIVE_NEEDED"|"GPU_HOOK_MISSING") status_color="${CLR_CYAN}" ;;
            "CONFLICT"|*"Locked"|*"Low Space"*) status_color="${CLR_RED}" ;;
        esac

        printf "%-28s | %-18s | %-18s | ${status_color}%-16s${CLR_RESET} | %-30s\n" \
            "$comp" "$host" "$target" "$status" "$risk"
    done

    echo "----------------------------------------------------------------------------------------------------------------------------------"
    echo -e "\n${CLR_BOLD}Audit Summary:${CLR_RESET}"
    echo -e "  ${CLR_GREEN}✔ Already Up-To-Date:${CLR_RESET} ${SATISFIED_COUNT}"
    echo -e "  ${CLR_YELLOW}ℹ Components to Install:${CLR_RESET} ${INSTALLS_FOUND}"
    echo -e "  ${CLR_CYAN}⬆ Components to Upgrade/Reconfigure:${CLR_RESET} ${UPGRADES_FOUND}"
    if [[ "$CONFLICTS_FOUND" -gt 0 ]]; then
        echo -e "  ${CLR_RED}✖ Conflicts / Critical Risks:${CLR_RESET} ${CONFLICTS_FOUND}"
    else
        echo -e "  ${CLR_GREEN}✔ Conflicts / Critical Risks:${CLR_RESET} 0 (All clear)"
    fi
    echo ""
}

# Export audit in JSON format
export_audit_json() {
    audit_all_components
    python3 -c "
import json
rows = []
raw = '''$(for r in "${AUDIT_RESULTS[@]}"; do echo "$r"; done)'''.strip().split('\n')
for line in raw:
    if not line: continue
    parts = line.split('|')
    rows.append({
        'component': parts[0],
        'host_state': parts[1],
        'target_state': parts[2],
        'status': parts[3],
        'risk': parts[4] if len(parts) > 4 else 'None'
    })

data = {
    'target_user': '${TARGET_USER}',
    'os': '${OS_NAME} ${OS_VERSION}',
    'gpu': '${GPU_NAME}',
    'driver': '${DRIVER_VERSION}',
    'free_disk_gb': int('${FREE_DISK_GB}' or 0),
    'summary': {
        'up_to_date': int('${SATISFIED_COUNT}'),
        'missing': int('${INSTALLS_FOUND}'),
        'upgrades_needed': int('${UPGRADES_FOUND}'),
        'conflicts': int('${CONFLICTS_FOUND}')
    },
    'components': rows
}
print(json.dumps(data, indent=2))
"
}
