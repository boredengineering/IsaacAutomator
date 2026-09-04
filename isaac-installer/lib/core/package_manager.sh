#!/usr/bin/env bash
# ==============================================================================
# package_manager.sh - System Package Manager Abstraction (apt/dnf/pacman)
# ==============================================================================

pkg_update() {
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -y
    elif command -v dnf &>/dev/null; then
        sudo dnf check-update -y || true
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm
    else
        log_warn "Unknown package manager. Skipping update."
    fi
}

pkg_install() {
    local packages=("$@")
    if command -v apt-get &>/dev/null; then
        DEBIAN_FRONTEND=noninteractive sudo apt-get install -y --no-install-recommends "${packages[@]}"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "${packages[@]}"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm "${packages[@]}"
    else
        log_fatal "No supported package manager found (apt/dnf/pacman)."
    fi
}

pkg_is_installed() {
    local package="$1"
    if command -v dpkg-query &>/dev/null; then
        dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed"
    elif command -v rpm &>/dev/null; then
        rpm -q "$package" &>/dev/null
    elif command -v pacman &>/dev/null; then
        pacman -Q "$package" &>/dev/null
    else
        return 1
    fi
}
