#!/usr/bin/env bash
# ==============================================================================
# logging.sh - ANSI colored terminal logging & output formatting
# ==============================================================================

# ANSI Color Codes
CLR_RESET="\033[0m"
CLR_BOLD="\033[1m"
CLR_RED="\033[38;5;196m"
CLR_GREEN="\033[38;5;46m"
CLR_YELLOW="\033[38;5;226m"
CLR_BLUE="\033[38;5;39m"
CLR_MAGENTA="\033[38;5;201m"
CLR_CYAN="\033[38;5;51m"
CLR_GRAY="\033[38;5;245m"

log_header() {
    echo -e "\n${CLR_BOLD}${CLR_CYAN}================================================================${CLR_RESET}"
    echo -e "${CLR_BOLD}${CLR_CYAN}  $*${CLR_RESET}"
    echo -e "${CLR_BOLD}${CLR_CYAN}================================================================${CLR_RESET}\n"
}

log_step() {
    echo -e "${CLR_BOLD}${CLR_BLUE}▶ [*] $*${CLR_RESET}"
}

log_info() {
    echo -e "  ${CLR_GRAY}ℹ $*${CLR_RESET}"
}

log_success() {
    echo -e "  ${CLR_GREEN}✔ $*${CLR_RESET}"
}

log_warn() {
    echo -e "  ${CLR_YELLOW}⚠ WARNING: $*${CLR_RESET}" >&2
}

log_error() {
    echo -e "  ${CLR_RED}✖ ERROR: $*${CLR_RESET}" >&2
}

log_fatal() {
    echo -e "\n${CLR_BOLD}${CLR_RED}✖ FATAL: $*${CLR_RESET}\n" >&2
    exit 1
}
