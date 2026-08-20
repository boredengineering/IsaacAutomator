#!/usr/bin/env bash
# ==============================================================================
# logging.sh - Dual-Stream Logging Engine, Error Trapping & Remediation Assistant
# ==============================================================================

# ANSI Color & Style Codes
CLR_RESET="\033[0m"
CLR_BOLD="\033[1m"
CLR_DIM="\033[2m"
CLR_ITALIC="\033[3m"
CLR_UNDERLINE="\033[4m"

CLR_RED="\033[38;5;196m"
CLR_GREEN="\033[38;5;46m"
CLR_YELLOW="\033[38;5;226m"
CLR_BLUE="\033[38;5;39m"
CLR_MAGENTA="\033[38;5;201m"
CLR_CYAN="\033[38;5;51m"
CLR_GRAY="\033[38;5;245m"
CLR_WHITE="\033[38;5;255m"

# Unicode Glyphs
GLYPH_CHECK="✔"
GLYPH_CROSS="✖"
GLYPH_WARN="⚠"
GLYPH_INFO="ℹ"
GLYPH_ARROW="▶"
GLYPH_BULLET="●"
GLYPH_TREE_MID="├─"
GLYPH_TREE_END="└─"
GLYPH_TREE_PIPE="│ "

# Log Paths
LOG_DIR=""
CURRENT_LOG_FILE=""
LATEST_LOG_SYMLINK=""
CURRENT_STAGE_RUNNING="init"

# Strip ANSI codes for plain-text file logging
strip_ansi() {
    sed -r "s/\x1B\[([0-9]{1,2}(;[0-9]{1,2})?)?[mGK]//g"
}

# Initialize dual-stream logging (Terminal + Timestamped File)
init_logging() {
    local base_home="${TARGET_HOME:-$HOME}"
    LOG_DIR="${base_home}/.isaac-installer/logs"
    mkdir -p "${LOG_DIR}"
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    CURRENT_LOG_FILE="${LOG_DIR}/install_${timestamp}.log"
    LATEST_LOG_SYMLINK="${LOG_DIR}/latest.log"

    # Create empty log file and update latest symlink
    touch "${CURRENT_LOG_FILE}"
    ln -sf "${CURRENT_LOG_FILE}" "${LATEST_LOG_SYMLINK}"
    
    if [[ -n "${TARGET_USER:-}" ]]; then
        chown -R "${TARGET_USER}:${TARGET_USER}" "${base_home}/.isaac-installer" 2>/dev/null || true
    fi

    # Write Session Header to Log File
    cat << LOG_HEADER >> "${CURRENT_LOG_FILE}"
================================================================================
Isaac Installer Session Log
Started At: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
User: ${TARGET_USER:-$USER}
Home: ${base_home}
Command: $0 $*
================================================================================

LOG_HEADER
}

# Write raw entry directly to persistent log file
log_to_file() {
    local level="$1"
    shift
    local msg="$*"
    if [[ -n "${CURRENT_LOG_FILE:-}" && -f "${CURRENT_LOG_FILE}" ]]; then
        local ts
        ts=$(date +"%Y-%m-%d %H:%M:%S")
        echo "[${ts}] [${level}] [${CURRENT_STAGE_RUNNING}] ${msg}" | strip_ansi >> "${CURRENT_LOG_FILE}"
    fi
}

log_header() {
    local title="$*"
    local len=${#title}
    local box_width=$((len + 6))
    if [[ $box_width -lt 64 ]]; then box_width=64; fi
    local border
    border=$(printf '─%.0s' $(seq 1 $((box_width - 2))))

    echo -e "\n${CLR_CYAN}╭${border}╮${CLR_RESET}"
    printf "${CLR_CYAN}│${CLR_RESET}  ${CLR_BOLD}${CLR_WHITE}%-$((box_width - 6))s${CLR_RESET}  ${CLR_CYAN}│${CLR_RESET}\n" "$title"
    echo -e "${CLR_CYAN}╰${border}╯${CLR_RESET}\n"

    log_to_file "HEADER" "=== ${title} ==="
}

log_card_start() {
    local title="$1"
    echo -e "${CLR_BOLD}${CLR_WHITE}╭── [ ${CLR_CYAN}${title}${CLR_WHITE} ]${CLR_RESET}"
    log_to_file "CARD" "--- [ ${title} ] ---"
}

log_card_item() {
    local key="$1"
    local val="$2"
    printf "${CLR_CYAN}│${CLR_RESET}  ${CLR_GRAY}%-22s${CLR_RESET} %b\n" "$key:" "$val"
    log_to_file "CARD_ITEM" "${key}: ${val}"
}

log_card_end() {
    echo -e "${CLR_CYAN}╰────────────────────────────────────────────────────────────────${CLR_RESET}\n"
}

log_step() {
    echo -e "${CLR_BOLD}${CLR_BLUE}${GLYPH_ARROW} [*] $*${CLR_RESET}"
    log_to_file "STEP" "$*"
}

log_info() {
    echo -e "  ${CLR_GRAY}${GLYPH_INFO} $*${CLR_RESET}"
    log_to_file "INFO" "$*"
}

log_success() {
    echo -e "  ${CLR_GREEN}${GLYPH_CHECK} $*${CLR_RESET}"
    log_to_file "SUCCESS" "$*"
}

log_warn() {
    echo -e "  ${CLR_YELLOW}${GLYPH_WARN} WARNING: $*${CLR_RESET}" >&2
    log_to_file "WARN" "$*"
}

log_error() {
    echo -e "  ${CLR_RED}${GLYPH_CROSS} ERROR: $*${CLR_RESET}" >&2
    log_to_file "ERROR" "$*"
}

log_fatal() {
    echo -e "\n${CLR_BOLD}${CLR_RED}${GLYPH_CROSS} FATAL: $*${CLR_RESET}\n" >&2
    log_to_file "FATAL" "$*"
    exit 1
}

# Executes a sub-command and streams stdout/stderr to both terminal (if verbose) and persistent log
run_logged() {
    local desc="$1"
    shift
    
    log_to_file "EXEC" "Running: $*"
    if [[ -n "${CURRENT_LOG_FILE:-}" ]]; then
        "$@" >> "${CURRENT_LOG_FILE}" 2>&1
        return $?
    else
        "$@"
        return $?
    fi
}

# Global Failure Trap Handler
on_error_trap() {
    local exit_code="$1"
    local line_no="$2"
    local command="$3"
    
    # Ignore intentional SIGINT (Ctrl+C)
    if [[ "$exit_code" -eq 130 ]]; then
        echo -e "\n${CLR_YELLOW}Execution paused by operator (Ctrl+C).${CLR_RESET}"
        echo -e "To resume later, run: ${CLR_BOLD}sudo ./bin/isaac-installer resume${CLR_RESET}\n"
        exit 130
    fi

    # Record error in log
    log_to_file "CRASH" "Command '${command}' exited with code ${exit_code} on line ${line_no} during stage [${CURRENT_STAGE_RUNNING}]"

    echo ""
    log_card_start "Installation Halted - Diagnostics & Remediation"
    log_card_item "Failed Stage" "${CLR_RED}${CURRENT_STAGE_RUNNING}${CLR_RESET}"
    log_card_item "Failed Command" "${CLR_YELLOW}${command}${CLR_RESET}"
    log_card_item "Source Code Line" "Line ${line_no}"
    log_card_item "Exit Code" "${exit_code}"
    log_card_item "Log File Location" "${LATEST_LOG_SYMLINK:-$CURRENT_LOG_FILE}"
    
    # Specific Root-Cause Analysis
    echo -e "${CLR_CYAN}│${CLR_RESET}"
    echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_BOLD}${CLR_WHITE}Suggested Remediation:${CLR_RESET}"
    
    if grep -q "Could not get lock /var/lib/dpkg/lock" "${CURRENT_LOG_FILE:-/dev/null}" 2>/dev/null; then
        echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_YELLOW}● APT package manager is locked by another process.${CLR_RESET}"
        echo -e "${CLR_CYAN}│${CLR_RESET}    Run: ${CLR_BOLD}sudo fuser -vki /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock${CLR_RESET}"
    elif grep -q "No space left on device" "${CURRENT_LOG_FILE:-/dev/null}" 2>/dev/null; then
        echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_YELLOW}● Out of disk space. Free up storage on your primary drive.${CLR_RESET}"
    elif grep -q "Permission denied" "${CURRENT_LOG_FILE:-/dev/null}" 2>/dev/null; then
        echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_YELLOW}● Permission issue. Ensure you run the installer with 'sudo'.${CLR_RESET}"
    elif grep -q "Could not resolve host" "${CURRENT_LOG_FILE:-/dev/null}" 2>/dev/null; then
        echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_YELLOW}● Network DNS resolution failed. Check your internet connection.${CLR_RESET}"
    else
        echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_YELLOW}● Inspect detailed error logs: ${CLR_BOLD}./bin/isaac-installer logs${CLR_RESET}"
        echo -e "${CLR_CYAN}│${CLR_RESET}  ● After resolving the issue, resume instantly with: ${CLR_BOLD}sudo ./bin/isaac-installer resume${CLR_RESET}"
    fi

    # Print Last 10 lines of error log
    if [[ -n "${CURRENT_LOG_FILE:-}" && -f "${CURRENT_LOG_FILE}" ]]; then
        echo -e "${CLR_CYAN}│${CLR_RESET}"
        echo -e "${CLR_CYAN}│${CLR_RESET}  ${CLR_BOLD}${CLR_WHITE}Tail of Failure Log:${CLR_RESET}"
        while IFS= read -r l; do
            echo -e "${CLR_CYAN}│${CLR_RESET}    ${CLR_DIM}${l}${CLR_RESET}"
        done < <(tail -n 8 "${CURRENT_LOG_FILE}")
    fi
    
    log_card_end
}

# CLI command to view and tail logs
cmd_logs() {
    local base_home="${TARGET_HOME:-$HOME}"
    local log_dir="${base_home}/.isaac-installer/logs"
    local latest="${log_dir}/latest.log"
    local flag="${1:-latest}"

    case "$flag" in
        --list|-l|list)
            log_header "Available Isaac Installer Log Files"
            if [[ -d "$log_dir" ]]; then
                ls -lht "${log_dir}"/*.log 2>/dev/null | awk '{print "  " $9 " (" $5 ", " $6 " " $7 " " $8 ")"}'
            else
                log_info "No log directory found at ${log_dir}"
            fi
            ;;
        --tail|-t|tail)
            local lines="${2:-50}"
            if [[ -f "$latest" ]]; then
                tail -n "$lines" "$latest"
            else
                log_error "No recent log file found at ${latest}"
            fi
            ;;
        --follow|-f|follow)
            if [[ -f "$latest" ]]; then
                tail -f "$latest"
            else
                log_error "No recent log file found at ${latest}"
            fi
            ;;
        latest|*)
            if [[ -f "$latest" ]]; then
                log_header "Latest Log Output: ${latest}"
                cat "$latest"
            else
                log_error "No log file found at ${latest}"
            fi
            ;;
    esac
}
