#!/usr/bin/env bash
# ==============================================================================
# detect.sh - Deep Hardware, GPU Architecture, Blackwell, Multi-GPU & Display Probe
# ==============================================================================

detect_target_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        TARGET_USER="${SUDO_USER}"
    elif [[ -n "${USER:-}" ]]; then
        TARGET_USER="${USER}"
    else
        TARGET_USER="$(whoami)"
    fi
    TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -z "$TARGET_HOME" || ! -d "$TARGET_HOME" ]]; then
        TARGET_HOME="/home/${TARGET_USER}"
    fi
}

detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        OS_NAME="${NAME:-Unknown}"
        OS_ID="${ID:-unknown}"
        OS_VERSION="${VERSION_ID:-unknown}"
    else
        OS_NAME="Linux"
        OS_ID="linux"
        OS_VERSION="unknown"
    fi
}

detect_gpu_architecture() {
    local gpu_name="${1:-}"
    local pci_id="${2:-}"

    if [[ "$gpu_name" =~ (RTX\ 50|GB100|GB200|GB202|GB203|Blackwell) ]]; then
        echo "Blackwell"
    elif [[ "$gpu_name" =~ (H100|H200|GH200|Hopper) ]]; then
        echo "Hopper"
    elif [[ "$gpu_name" =~ (RTX\ 40|RTX\ 6000\ Ada|L40|L4|Ada) ]]; then
        echo "Ada Lovelace"
    elif [[ "$gpu_name" =~ (RTX\ 30|A100|A10|A30|A40|Ampere) ]]; then
        echo "Ampere"
    elif [[ "$gpu_name" =~ (RTX\ 20|TITAN\ RTX|Turing) ]]; then
        echo "Turing"
    else
        echo "Generic NVIDIA"
    fi
}

get_minimum_driver_version() {
    local arch="$1"
    case "$arch" in
        "Blackwell")    echo "570" ;; # Blackwell requires >= 570/580
        "Hopper")       echo "535" ;;
        "Ada Lovelace") echo "535" ;;
        "Ampere")       echo "525" ;;
        *)              echo "535" ;;
    esac
}

detect_gpu() {
    GPU_FOUND=false
    GPU_COUNT=0
    GPUS=()
    GPU_NAME="None"
    DRIVER_INSTALLED=false
    DRIVER_VERSION="None"
    PRIMARY_GPU_INDEX=0
    RECOMMENDED_DRIVER="535"
    HAS_BLACKWELL=false
    IS_HETEROGENEOUS=false
    HAS_INTEGRATED_GPU=false

    # Check for Integrated CPU GPU (Intel / AMD)
    if command -v lspci &>/dev/null; then
        local igpu_check
        igpu_check="$(lspci 2>/dev/null | grep -i "VGA.*Intel\|VGA.*AMD\|Display.*Intel\|Display.*AMD" | grep -qv "NVIDIA" || true)"
        if [[ -n "$igpu_check" ]]; then
            HAS_INTEGRATED_GPU=true
        fi
    fi

    # Query active driver via nvidia-smi if available
    if command -v nvidia-smi &>/dev/null; then
        if nvidia-smi &>/dev/null; then
            DRIVER_INSTALLED=true
            DRIVER_VERSION="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | tr -d ' ' || echo "Unknown")"
            local raw_names
            raw_names="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || true)"
            if [[ -n "$raw_names" ]]; then
                GPU_COUNT=$(echo "$raw_names" | wc -l)
            fi
            
            local idx=0
            local prev_arch=""
            local smi_lines
            smi_lines="$(nvidia-smi --query-gpu=name,memory.total,pci.bus_id --format=csv,noheader 2>/dev/null || true)"
            if [[ -n "$smi_lines" ]]; then
                while IFS=, read -r name vram pci_bus; do
                    [[ -z "$name" ]] && continue
                    name="$(echo "$name" | xargs)"
                    vram="$(echo "$vram" | xargs)"
                    pci_bus="$(echo "$pci_bus" | xargs)"
                    local arch
                    arch="$(detect_gpu_architecture "$name" "$pci_bus")"
                    if [[ "$arch" == "Blackwell" ]]; then
                        HAS_BLACKWELL=true
                    fi
                    if [[ -n "$prev_arch" && "$prev_arch" != "$arch" ]]; then
                        IS_HETEROGENEOUS=true
                    fi
                    prev_arch="$arch"

                    GPUS+=("GPU ${idx}: ${name} (${vram} VRAM, Arch: ${arch}, Bus: ${pci_bus})")
                    idx=$((idx + 1))
                done <<< "$smi_lines"
            fi

            GPU_FOUND=true
            GPU_NAME="$(echo "$raw_names" | head -n 1)"
        fi
    fi

    # Fallback to PCIe inspection if driver not yet loaded
    if [[ "$GPU_FOUND" == false ]] && command -v lspci &>/dev/null; then
        local pci_nvidia
        pci_nvidia="$(lspci -nn 2>/dev/null | grep -i "VGA compatible controller.*NVIDIA\|3D controller.*NVIDIA" || true)"
        if [[ -n "$pci_nvidia" ]]; then
            GPU_FOUND=true
            GPU_COUNT=$(echo "$pci_nvidia" | wc -l)
            local idx=0
            while read -r line; do
                [[ -z "$line" ]] && continue
                local name
                name="$(echo "$line" | sed 's/.*: //')"
                local pci_bus
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
        fi
    fi

    # Determine recommended driver for installed hardware
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

probe_system() {
    detect_target_user
    detect_os
    detect_gpu
    detect_display
    detect_disk_space
}
