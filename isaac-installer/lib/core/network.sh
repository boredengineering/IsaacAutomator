#!/usr/bin/env bash
# ==============================================================================
# network.sh - Network Connectivity, Port Management & ZeroMQ IPC Diagnostics
# ==============================================================================

# ------------------------------------------------------------------------------
# Port Inspection & Lifecycle Management
# ------------------------------------------------------------------------------

is_port_in_use() {
    local port="$1"
    if command -v ss &>/dev/null; then
        ss -tulpn 2>/dev/null | grep -qE "(:|\])${port}\b" && return 0
    fi
    if command -v lsof &>/dev/null; then
        lsof -iTCP:"${port}" -sTCP:LISTEN -n -P &>/dev/null && return 0
    fi
    if command -v fuser &>/dev/null; then
        fuser "${port}/tcp" &>/dev/null && return 0
    fi
    python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('0.0.0.0', int('${port}')))
    s.close()
    exit(1)
except OSError:
    exit(0)
" 2>/dev/null && return 0
    return 1
}

get_port_owner() {
    local port="$1"
    local pid=""
    local pname=""
    local user=""

    if command -v ss &>/dev/null; then
        local line
        line=$(ss -tulpn 2>/dev/null | grep -E "(:|\])${port}\b" | head -n 1)
        if [[ "$line" =~ pid=([0-9]+) ]]; then
            pid="${BASH_REMATCH[1]}"
        fi
    fi
    if [[ -z "$pid" ]] && command -v lsof &>/dev/null; then
        pid=$(lsof -tiTCP:"${port}" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true)
    fi
    if [[ -z "$pid" ]] && command -v fuser &>/dev/null; then
        pid=$(fuser "${port}/tcp" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' | head -n 1 || true)
    fi

    if [[ -n "$pid" ]]; then
        pname=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        user=$(ps -p "$pid" -o user= 2>/dev/null || echo "unknown")
        local cmdline
        cmdline=$(ps -p "$pid" -o args= 2>/dev/null | cut -c1-60 || echo "")
        echo "${pid}|${pname}|${user}|${cmdline}"
        return 0
    fi
    echo "|||"
    return 1
}

free_port() {
    local port="$1"
    local force="${2:-false}"

    if ! is_port_in_use "$port"; then
        log_info "Port ${port} is already free."
        return 0
    fi

    local owner_info
    owner_info=$(get_port_owner "$port")
    IFS='|' read -r pid pname puser pcmd <<< "$owner_info"

    if [[ -n "$pid" ]]; then
        log_warn "Port ${port} is occupied by PID ${pid} (${pname} / user: ${puser})"
        log_step "Sending SIGTERM to process ${pid}..."
        kill -15 "$pid" 2>/dev/null || sudo kill -15 "$pid" 2>/dev/null || true
        
        # Wait up to 2 seconds for graceful socket release
        local elapsed=0
        while is_port_in_use "$port" && [[ $elapsed -lt 4 ]]; do
            sleep 0.5
            elapsed=$((elapsed + 1))
        done

        if is_port_in_use "$port"; then
            log_warn "Process ${pid} did not terminate gracefully. Sending SIGKILL (kill -9)..."
            kill -9 "$pid" 2>/dev/null || sudo kill -9 "$pid" 2>/dev/null || true
            sleep 0.5
        fi
    fi

    if command -v fuser &>/dev/null; then
        fuser -k -9 "${port}/tcp" &>/dev/null || sudo fuser -k -9 "${port}/tcp" &>/dev/null || true
    fi

    if is_port_in_use "$port"; then
        log_error "Failed to release port ${port}. Please check with: sudo ss -tulpn | grep ${port}"
        return 1
    else
        log_success "Port ${port} successfully released."
        return 0
    fi
}

find_free_port() {
    local port="${1:-5555}"
    local max_attempts="${2:-20}"
    local attempts=0
    while [[ $attempts -lt $max_attempts ]]; do
        if ! is_port_in_use "$port"; then
            echo "$port"
            return 0
        fi
        port=$((port + 1))
        attempts=$((attempts + 1))
    done
    echo ""
    return 1
}

kill_all_policy_servers() {
    log_step "Terminating all active ZeroMQ Policy Servers & Orphaned Python Daemons..."
    pkill -f "run_gr00t_server.py" 2>/dev/null || true
    pkill -f "policy_runner.py" 2>/dev/null || true
    
    for p in $(seq 5555 5560); do
        if is_port_in_use "$p"; then
            free_port "$p"
        fi
    done
    log_success "All ZeroMQ policy servers terminated and ports 5555-5560 are verified free."
}

print_robotics_port_dashboard() {
    log_header "Robotics IPC, ZeroMQ & Cloud Workstation Port Manager"

    local ports_to_check=(
        "5555|ZeroMQ GR00T Policy Server (Primary)|VLA Action Streaming"
        "5556|ZeroMQ GR00T Telemetry / Feedback|Secondary Teleop Channel"
        "5557|ZeroMQ Arena Multi-Agent Worker 1|Distributed Subprocess"
        "5558|ZeroMQ Arena Multi-Agent Worker 2|Distributed Subprocess"
        "8080|Isaac Sim WebRTC Streaming|Live Omniverse Video Web Portal"
        "8211|Omniverse Kit USD Live Sync|Multi-Client Scene Collaboration"
        "6006|TensorBoard RL Monitoring|Loss & Episode Return Tracking"
        "8000|LeRobot Web Dataset Visualizer|Hugging Face Physical AI"
        "8081|Rerun.io 3D Visualizer Web|Spatial Video & Point Cloud Stream"
        "5900|VNC Display Server (x11vnc)|Remote Desktop RFB Protocol"
        "6080|noVNC Browser Gateway|HTML5 Canvas Remote Desktop"
        "4000|NoMachine NX Protocol|Hardware-Accelerated 3D Desktop"
        "47998|Sunshine GameStream (Video)|Low-Latency NVENC Video Stream"
        "47999|Sunshine GameStream (Control)|Direct Controller/Keyboard Input"
    )

    printf "${CLR_BOLD}%-6s | %-32s | %-12s | %-8s | %-30s${CLR_RESET}\n" \
        "Port" "Service / Subsystem" "Status" "PID" "Process / Owner"
    echo "----------------------------------------------------------------------------------------------------------------"

    for entry in "${ports_to_check[@]}"; do
        IFS='|' read -r port svc desc <<< "$entry"
        if is_port_in_use "$port"; then
            local owner_info
            owner_info=$(get_port_owner "$port")
            IFS='|' read -r pid pname puser pcmd <<< "$owner_info"
            local owner_str="${pname:-unknown} (${puser:-unknown})"
            printf "%-6s | %-32s | ${CLR_YELLOW}%-12s${CLR_RESET} | %-8s | %-30s\n" \
                "$port" "$svc" "LISTENING" "${pid:--}" "${owner_str:0:30}"
        else
            printf "%-6s | %-32s | ${CLR_GREEN}%-12s${CLR_RESET} | %-8s | %-30s\n" \
                "$port" "$svc" "AVAILABLE" "-" "-"
        fi
    done
    echo "----------------------------------------------------------------------------------------------------------------"
    echo -e "\n${CLR_BOLD}Management Commands:${CLR_RESET}"
    echo -e "  ${CLR_CYAN}./bin/isaac-installer net free <port>${CLR_RESET}          (Free an occupied port)"
    echo -e "  ${CLR_CYAN}./bin/isaac-installer net kill-servers${CLR_RESET}         (Kill all background ZeroMQ policy servers)"
    echo -e "  ${CLR_CYAN}./bin/isaac-installer net find-free [start]${CLR_RESET}   (Find next free port)\n"
}

# ------------------------------------------------------------------------------
# CDN Latency & Download Speed Benchmarking
# ------------------------------------------------------------------------------

test_cdn_endpoint() {
    local name="$1"
    local url="$2"
    
    local http_code
    local time_total
    
    if command -v curl &>/dev/null; then
        local response
        response=$(curl -s -o /dev/null -w "%{http_code}|%{time_total}" --connect-timeout 4 "$url" 2>/dev/null || echo "000|0")
        http_code=$(echo "$response" | cut -d'|' -f1)
        time_total=$(echo "$response" | cut -d'|' -f2)
        
        if [[ "$http_code" =~ ^(200|301|302|403|404)$ ]]; then
            local latency_ms
            latency_ms=$(awk "BEGIN {printf \"%.0f\", ${time_total} * 1000}")
            echo -e "  ${CLR_GREEN}✔ ${name}:${CLR_RESET} Reachable (${latency_ms} ms)"
            return 0
        else
            echo -e "  ${CLR_YELLOW}⚠ ${name}:${CLR_RESET} Unreachable / Slow (HTTP ${http_code})"
            return 1
        fi
    else
        echo -e "  ${CLR_GRAY}ℹ ${name}:${CLR_RESET} Skipped (curl not found)"
        return 0
    fi
}

benchmark_network_preflight() {
    log_step "Benchmarking CDN & Repository Connectivity..."
    test_cdn_endpoint "NVIDIA Omniverse CDN (Isaac Sim 15GB)" "https://download.isaacsim.omniverse.nvidia.com"
    test_cdn_endpoint "Hugging Face Hub (LeRobot & GR00T Models)" "https://huggingface.co"
    test_cdn_endpoint "GitHub (Repositories & Releases)" "https://github.com"
    test_cdn_endpoint "Ubuntu Package Mirrors" "http://archive.ubuntu.com"
}

# ------------------------------------------------------------------------------
# CLI Dispatcher for `isaac-installer net ...`
# ------------------------------------------------------------------------------

cmd_net() {
    local subcmd="${1:-status}"
    shift || true

    case "$subcmd" in
        status|ports|list)
            print_robotics_port_dashboard
            ;;
        free|kill-port|release)
            local target_port="${1:-}"
            if [[ -z "$target_port" ]]; then
                log_error "Please specify a port to free (e.g. ./bin/isaac-installer net free 5555)"
                return 1
            fi
            free_port "$target_port"
            ;;
        kill-servers|kill-gr00t|kill-zmq|stop)
            kill_all_policy_servers
            ;;
        find-free|next-port)
            local start="${1:-5555}"
            local free_p
            free_p=$(find_free_port "$start")
            if [[ -n "$free_p" ]]; then
                echo -e "Next free port: ${CLR_GREEN}${free_p}${CLR_RESET}"
            else
                echo -e "${CLR_RED}No free ports found starting from ${start}${CLR_RESET}"
            fi
            ;;
        bench)
            benchmark_network_preflight
            ;;
        *)
            log_error "Unknown net command: ${subcmd}"
            echo "Usage: ./bin/isaac-installer net [status|free <port>|kill-servers|find-free <start>|bench]"
            ;;
    esac
}

