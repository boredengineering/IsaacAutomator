#!/usr/bin/env bash
# ==============================================================================
# logging.sh - Modern Terminal UI, Box Banners, Tree Formatter & Step Timers
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
}

log_card_start() {
    local title="$1"
    echo -e "${CLR_BOLD}${CLR_WHITE}╭── [ ${CLR_CYAN}${title}${CLR_WHITE} ]${CLR_RESET}"
}

log_card_item() {
    local key="$1"
    local val="$2"
    printf "${CLR_CYAN}│${CLR_RESET}  ${CLR_GRAY}%-22s${CLR_RESET} %b\n" "$key:" "$val"
}

log_card_end() {
    echo -e "${CLR_CYAN}╰────────────────────────────────────────────────────────────────${CLR_RESET}\n"
}

log_step() {
    echo -e "${CLR_BOLD}${CLR_BLUE}${GLYPH_ARROW} [*] $*${CLR_RESET}"
}

log_info() {
    echo -e "  ${CLR_GRAY}${GLYPH_INFO} $*${CLR_RESET}"
}

log_success() {
    echo -e "  ${CLR_GREEN}${GLYPH_CHECK} $*${CLR_RESET}"
}

log_warn() {
    echo -e "  ${CLR_YELLOW}${GLYPH_WARN} WARNING: $*${CLR_RESET}" >&2
}

log_error() {
    echo -e "  ${CLR_RED}${GLYPH_CROSS} ERROR: $*${CLR_RESET}" >&2
}

log_fatal() {
    echo -e "\n${CLR_BOLD}${CLR_RED}${GLYPH_CROSS} FATAL: $*${CLR_RESET}\n" >&2
    exit 1
}

# Run a command with live duration calculation
run_timed() {
    local desc="$1"
    shift
    local start_time
    start_time=$(date +%s%N)
    
    echo -ne "  ${CLR_CYAN}${GLYPH_ARROW}${CLR_RESET} ${desc}..."
    if "$@" >/dev/null 2>&1; then
        local end_time
        end_time=$(date +%s%N)
        local elapsed_ms=$(( (end_time - start_time) / 1000000 ))
        local elapsed_sec
        elapsed_sec=$(awk "BEGIN {printf \"%.2f\", ${elapsed_ms} / 1000}")
        echo -e "\r  ${CLR_GREEN}${GLYPH_CHECK}${CLR_RESET} ${desc} ${CLR_DIM}(${elapsed_sec}s)${CLR_RESET}"
        return 0
    else
        echo -e "\r  ${CLR_RED}${GLYPH_CROSS}${CLR_RESET} ${desc} ${CLR_RED}(Failed)${CLR_RESET}"
        return 1
    fi
}
