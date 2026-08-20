#!/usr/bin/env bash
# ==============================================================================
# state.sh - JSON State Machine & Reboot Resumption Engine
# ==============================================================================

STATE_DIR="${TARGET_HOME:-$HOME}/.isaac-installer"
STATE_FILE="${STATE_DIR}/state.json"
RESUME_SERVICE="/etc/systemd/system/isaac-installer-resume.service"

init_state() {
    mkdir -p "${STATE_DIR}"
    if [[ ! -f "${STATE_FILE}" ]]; then
        cat << JSON > "${STATE_FILE}"
{
  "current_stage": "init",
  "stages_completed": [],
  "updated_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "status": "in_progress"
}
JSON
        chown -R "${TARGET_USER}:${TARGET_USER}" "${STATE_DIR}" 2>/dev/null || true
    fi
}

get_current_stage() {
    if [[ -f "${STATE_FILE}" ]]; then
        grep -o '"current_stage": *"[^"]*"' "${STATE_FILE}" | cut -d'"' -f4
    else
        echo "init"
    fi
}

is_stage_completed() {
    local stage_name="$1"
    if [[ -f "${STATE_FILE}" ]]; then
        grep -q "\"${stage_name}\"" "${STATE_FILE}"
    else
        return 1
    fi
}

set_stage() {
    local next_stage="$1"
    init_state
    
    # Read completed stages or create new list
    local updated_json
    updated_json=$(python3 -c "
import json, datetime
try:
    with open('${STATE_FILE}', 'r') as f:
        data = json.load(f)
except Exception:
    data = {'stages_completed': []}

curr = data.get('current_stage', 'init')
completed = data.get('stages_completed', [])
if curr not in completed and curr != 'init':
    completed.append(curr)

data['current_stage'] = '${next_stage}'
data['stages_completed'] = completed
data['updated_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
if '${next_stage}' == 'completed':
    data['status'] = 'success'

print(json.dumps(data, indent=2))
")
    echo "$updated_json" > "${STATE_FILE}"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${STATE_DIR}" 2>/dev/null || true
}

register_resume_hook() {
    local script_path
    script_path="$(readlink -f "$0")"

    cat << SERVICE | sudo tee "${RESUME_SERVICE}" >/dev/null
[Unit]
Description=Isaac Installer Post-Reboot Resume
After=network.target graphical.target

[Service]
Type=oneshot
User=root
WorkingDirectory=${TARGET_HOME}
ExecStart=/bin/bash ${script_path} resume
RemainAfterExit=no

[Install]
WantedBy=graphical.target
SERVICE

    sudo systemctl daemon-reload
    sudo systemctl enable isaac-installer-resume.service
}

clear_resume_hook() {
    if [[ -f "${RESUME_SERVICE}" ]]; then
        sudo systemctl disable isaac-installer-resume.service 2>/dev/null || true
        sudo rm -f "${RESUME_SERVICE}"
        sudo systemctl daemon-reload
    fi
}
