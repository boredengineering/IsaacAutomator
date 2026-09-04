#!/usr/bin/env bash
# ==============================================================================
# detect.sh - Deep Hardware, NVMe Storage, LVM, PCIe & Architecture Inspection
# ==============================================================================

detect_target_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        TARGET_USER="${SUDO_USER}"
        TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
    else
        TARGET_USER="${USER:-root}"
        TARGET_HOME="${HOME:-/root}"
    fi
}

run_as_user() {
    local cmd="$1"
    detect_target_user

    local conda_env_dir="${TARGET_HOME}/miniconda3/envs/isaaclab"
    if [[ ! -d "$conda_env_dir" ]]; then
        conda_env_dir="${TARGET_HOME}/.conda/envs/isaaclab"
    fi

    local env_sanitize="
        if [[ -n \"\${CONDA_DEFAULT_ENV:-}\" && \"\${CONDA_DEFAULT_ENV}\" == 'base' ]]; then
            unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER
            if [[ -d '${conda_env_dir}' ]]; then
                export CONDA_PREFIX='${conda_env_dir}'
                export CONDA_DEFAULT_ENV='isaaclab'
            fi
        fi
    "

    if command -v sudo &>/dev/null && [[ "$EUID" -eq 0 && "${TARGET_USER}" != "root" && "${TARGET_USER}" != "${USER}" ]]; then
        sudo -H -u "${TARGET_USER}" bash -l -c "${env_sanitize} ${cmd}"
    else
        bash -l -c "${env_sanitize} ${cmd}"
    fi
}

run_as_user_stdin() {
    local target_file="$1"
    detect_target_user
    if command -v sudo &>/dev/null && [[ "$EUID" -eq 0 && "${TARGET_USER}" != "root" && "${TARGET_USER}" != "${USER}" ]]; then
        sudo -H -u "${TARGET_USER}" tee "$target_file" >/dev/null
    else
        tee "$target_file" >/dev/null
    fi
}

run_as_root() {
    local cmd="$1"
    if [[ "$EUID" -eq 0 ]]; then
        bash -c "$cmd"
    elif command -v sudo &>/dev/null; then
        sudo bash -c "$cmd"
    else
        bash -c "$cmd"
    fi
}

detect_system_specs() {
    detect_target_user
    KERNEL_VERSION="$(uname -r)"
    ARCH="$(uname -m)"
    CPU_MODEL="$(lscpu 2>/dev/null | grep -E "Model name:" | sed 's/Model name:[ \t]*//' | head -n 1 || echo "Unknown CPU")"
    CPU_CORES="$(nproc 2>/dev/null || echo "1")"
    TOTAL_RAM_GB="$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")"
    AVAILABLE_RAM_GB="$(free -g 2>/dev/null | awk '/^Mem:/{print $7}' || echo "0")"
}

detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        OS_ID="${ID:-unknown}"
        OS_VERSION="${VERSION_ID:-unknown}"
        OS_NAME="${NAME:-unknown}"
    else
        OS_ID="unknown"
        OS_VERSION="unknown"
        OS_NAME="unknown"
    fi
}

detect_nvme_storage() {
    NVME_DRIVES=()
    NVME_COUNT=0
    LVM_VOLUME_GROUPS=()

    # Detect NVMe drives using lsblk (robust across nvme-cli versions)
    local lsblk_nvme
    lsblk_nvme=$(lsblk -d -n -o KNAME,MODEL,SIZE,TRAN 2>/dev/null | grep -E "nvme" || true)
    if [[ -n "$lsblk_nvme" ]]; then
        while read -r name model size tran; do
            if [[ -n "$name" ]]; then
                NVME_DRIVES+=("/dev/${name}: ${model:-Generic NVMe} (${size})")
                NVME_COUNT=$((NVME_COUNT + 1))
            fi
        done <<< "$lsblk_nvme"
    fi

    # Fallback to nvme list if lsblk found nothing
    if [[ ${#NVME_DRIVES[@]} -eq 0 ]] && command -v nvme &>/dev/null; then
        local nvme_out
        nvme_out=$(nvme list 2>/dev/null | awk 'NR>2 {print $1 "|" $2}' || true)
        if [[ -n "$nvme_out" ]]; then
            while IFS='|' read -r dev sn; do
                if [[ -n "$dev" ]]; then
                    NVME_DRIVES+=("${dev}: NVMe Drive [SN: ${sn}]")
                    NVME_COUNT=$((NVME_COUNT + 1))
                fi
            done <<< "$nvme_out"
        fi
    fi

    # Detect LVM Volume Groups
    if command -v vgs &>/dev/null; then
        local vgs_out
        vgs_out=$(vgs --noheadings -o vg_name,vg_size,vg_free 2>/dev/null || true)
        if [[ -n "$vgs_out" ]]; then
            while read -r vg_name vg_size vg_free; do
                if [[ -n "$vg_name" ]]; then
                    LVM_VOLUME_GROUPS+=("${vg_name} (Size: ${vg_size}, Free: ${vg_free})")
                fi
            done <<< "$vgs_out"
        fi
    fi
}

detect_gpu_architecture() {
    local gpu_name="$1"
    local pci_bus="$2"

    if [[ "$gpu_name" =~ (RTX[[:space:]]+50[0-9]{2}|RTX[[:space:]]+PRO[[:space:]]+6000[[:space:]]+Blackwell|GB[0-9]{3}|B100|B200|Blackwell) ]]; then
        echo "Blackwell"
    elif [[ "$gpu_name" =~ (RTX[[:space:]]+40[0-9]{2}|RTX[[:space:]]+6000[[:space:]]+Ada|L40|L4|Ada) ]]; then
        echo "Ada Lovelace"
    elif [[ "$gpu_name" =~ (RTX[[:space:]]+30[0-9]{2}|A100|A10|A30|A40|Ampere) ]]; then
        echo "Ampere"
    elif [[ "$gpu_name" =~ (RTX[[:space:]]+20[0-9]{2}|Titan[[:space:]]+RTX|T4|Turing) ]]; then
        echo "Turing"
    elif [[ "$gpu_name" =~ (GTX[[:space:]]+10[0-9]{2}|P100|Pascal) ]]; then
        echo "Pascal"
    else
        echo "Generic NVIDIA"
    fi
}

detect_gpu() {
    GPU_FOUND=false
    GPU_COUNT=0
    GPU_NAME="None"
    GPU_VRAM_MB="0"
    GPU_BUS_ID=""
    GPU_ARCH="None"
    GPUS=()
    PCIE_LINK_INFO="Unknown"
    DRIVER_INSTALLED=false
    DRIVER_VERSION="None"
    HAS_BLACKWELL=false
    IS_HETEROGENEOUS=false
    HAS_INTEGRATED_GPU=false

    if lspci 2>/dev/null | grep -E "VGA|3D|Display" | grep -Ei "Intel|AMD|ATI" | grep -vEi "NVIDIA" >/dev/null; then
        HAS_INTEGRATED_GPU=true
    fi

    if command -v nvidia-smi &>/dev/null; then
        local smi_out
        smi_out="$(nvidia-smi --query-gpu=name,memory.total,driver_version,pci.bus_id --format=csv,noheader,nounits 2>/dev/null || true)"
        if [[ -n "$smi_out" ]]; then
            GPU_FOUND=true
            DRIVER_INSTALLED=true
            DRIVER_VERSION="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | xargs)"
            
            local architectures=()
            local idx=0
            while IFS=',' read -r name vram driver bus; do
                name="$(echo "$name" | xargs)"
                vram="$(echo "$vram" | xargs)"
                bus="$(echo "$bus" | xargs)"
                local arch
                arch="$(detect_gpu_architecture "$name" "$bus")"
                architectures+=("$arch")
                if [[ "$arch" == "Blackwell" ]]; then
                    HAS_BLACKWELL=true
                fi
                GPUS+=("GPU ${idx}: ${name} (${vram} MiB VRAM, Arch: ${arch}, Bus: ${bus})")
                if [[ $idx -eq 0 ]]; then
                    GPU_NAME="$name"
                    GPU_VRAM_MB="$vram"
                    GPU_BUS_ID="$bus"
                    GPU_ARCH="$arch"
                fi
                idx=$((idx + 1))
            done <<< "$smi_out"
            GPU_COUNT=$idx

            local first_arch="${architectures[0]:-}"
            for a in "${architectures[@]}"; do
                if [[ "$a" != "$first_arch" ]]; then
                    IS_HETEROGENEOUS=true
                    break
                fi
            done

            if [[ -n "$GPU_BUS_ID" ]]; then
                local pci_clean
                pci_clean="$(echo "$GPU_BUS_ID" | sed 's/^00000000://' | sed 's/^0000://')"
                local lspci_speed
                lspci_speed="$(lspci -s "$pci_clean" -vv 2>/dev/null | grep -E "LnkSta:" | head -n 1 | sed 's/^[ \t]*LnkSta:[ \t]*//' || true)"
                if [[ -n "$lspci_speed" ]]; then
                    PCIE_LINK_INFO="$lspci_speed"
                fi
            fi
        fi
    fi

    if [[ "$GPU_FOUND" == false ]]; then
        local pci_nvidia
        pci_nvidia="$(lspci 2>/dev/null | grep -E "VGA|3D|Display" | grep -i "NVIDIA" || true)"
        if [[ -n "$pci_nvidia" ]]; then
            GPU_FOUND=true
            local idx=0
            while read -r line; do
                local name
                local pci_bus
                name="$(echo "$line" | sed 's/.*: //')"
                pci_bus="$(echo "$line" | awk '{print $1}')"
                local arch
                arch="$(detect_gpu_architecture "$name" "$pci_bus")"
                if [[ "$arch" == "Blackwell" ]]; then
                    HAS_BLACKWELL=true
                fi
                GPUS+=("GPU ${idx}: ${name} (Arch: ${arch}, Bus: ${pci_bus})")
                idx=$((idx + 1))
            done <<< "$pci_nvidia"
            GPU_NAME="$(echo "$pci_nvidia" | head -n 1 | sed 's/.*: //')"
            GPU_COUNT=$idx
        fi
    fi

    if [[ "$HAS_BLACKWELL" == true ]]; then
        RECOMMENDED_DRIVER="570"
    else
        RECOMMENDED_DRIVER="535"
    fi
}

detect_display() {
    DISPLAY_MODE="unknown"
    HAS_PHYSICAL_MONITOR=false
    IS_WAYLAND=false
    GDM_WAYLAND_DISABLED=false

    if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
        IS_WAYLAND=true
    fi

    if [[ -f /etc/gdm3/custom.conf ]]; then
        if grep -q "^WaylandEnable=false" /etc/gdm3/custom.conf 2>/dev/null; then
            GDM_WAYLAND_DISABLED=true
        fi
    fi

    local x_sockets=()
    if [[ -d /tmp/.X11-unix ]]; then
        mapfile -t x_sockets < <(find /tmp/.X11-unix -type s -name "X*" 2>/dev/null || true)
    fi

    if [[ -n "${DISPLAY:-}" || ${#x_sockets[@]} -gt 0 ]]; then
        DISPLAY_MODE="x11_active"
        HAS_PHYSICAL_MONITOR=true
    else
        DISPLAY_MODE="headless"
        HAS_PHYSICAL_MONITOR=false
    fi
}

detect_disk_space() {
    detect_target_user
    FREE_DISK_GB=$(df -BG "$TARGET_HOME" 2>/dev/null | awk 'NR==2 {gsub("G","",$4); print $4}' || echo "0")
}

detect_apt_lock() {
    APT_LOCKED=false
    APT_LOCK_HOLDER="None"
    local lock_pids
    lock_pids=$(fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock 2>/dev/null || true)
    if [[ -n "$lock_pids" ]]; then
        APT_LOCKED=true
        local pnames=()
        for pid in $lock_pids; do
            local pname
            pname="$(ps -p "$pid" -o comm= 2>/dev/null || echo "PID $pid")"
            pnames+=("${pname} (PID ${pid})")
        done
        APT_LOCK_HOLDER="${pnames[*]}"
    elif [[ -f /var/lib/dpkg/lock-frontend || -f /var/lib/apt/lists/lock ]]; then
        if fuser /var/lib/dpkg/lock-frontend &>/dev/null || fuser /var/lib/apt/lists/lock &>/dev/null; then
            APT_LOCKED=true
            APT_LOCK_HOLDER="Active dpkg process"
        fi
    fi
}

probe_system() {
    detect_target_user
    detect_system_specs
    detect_os
    detect_nvme_storage
    detect_gpu
    detect_display
    detect_disk_space
    detect_apt_lock
}
