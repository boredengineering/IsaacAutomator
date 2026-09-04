#!/usr/bin/env bash
# ==============================================================================
# backup.sh - Configuration File Snapshots, Safe Rollback & Restore
# ==============================================================================

BACKUP_DIR="${TARGET_HOME:-$HOME}/.isaac-installer/backups"

backup_file() {
    local target_file="$1"
    if [[ -f "$target_file" ]]; then
        mkdir -p "${BACKUP_DIR}"
        local timestamp
        timestamp="$(date +%Y%m%d_%H%M%S)"
        local backup_path="${BACKUP_DIR}/$(basename "${target_file}").${timestamp}.bak"
        cp -p "$target_file" "$backup_path"
        log_info "Created safety backup: ${backup_path}"
    fi
}

list_backups() {
    log_header "Workstation Configuration Backups"
    if [[ -d "${BACKUP_DIR}" ]]; then
        find "${BACKUP_DIR}" -type f -name "*.bak" | while read -r file; do
            echo "  • $(basename "$file") ($(stat -c '%y' "$file" | cut -d'.' -f1))"
        done
    else
        log_info "No previous backups found."
    fi
}
