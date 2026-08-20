#!/usr/bin/env bash
# ==============================================================================
# state.sh - Persistent State Ledger, Drift Detection & Self-Healing Engine
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
  "status": "in_progress",
  "workspace_layout": "${WORKSPACE_LAYOUT:-auto}",
  "repositories": {}
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

# Updates the persistent ledger with repository state
update_repo_ledger() {
    local repo_key="$1"
    local repo_path="$2"
    local repo_slug="$3"
    local upstream_slug="$4"
    local target_ref="$5"
    local linked_sim="${6:-}"

    init_state
    python3 -c "
import json, datetime
try:
    with open('${STATE_FILE}', 'r') as f:
        data = json.load(f)
except Exception:
    data = {}

if 'repositories' not in data:
    data['repositories'] = {}

data['repositories']['${repo_key}'] = {
    'path': '${repo_path}',
    'repo_slug': '${repo_slug}',
    'upstream_slug': '${upstream_slug}',
    'target_ref': '${target_ref}',
    'linked_sim': '${linked_sim}',
    'updated_at': datetime.datetime.utcnow().isoformat() + 'Z'
}
data['updated_at'] = datetime.datetime.utcnow().isoformat() + 'Z'

with open('${STATE_FILE}', 'w') as f:
    json.dump(data, f, indent=2)
"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${STATE_DIR}" 2>/dev/null || true
}

# ==============================================================================
# State Drift Detection Engine
# ==============================================================================

DRIFT_ITEMS=()

audit_workspace_drift() {
    DRIFT_ITEMS=()
    detect_target_user

    local ws_root
    ws_root="$(resolve_default_workspace_dir)"
    local layout="${WORKSPACE_LAYOUT:-${CFG_WORKSPACE_LAYOUT:-auto}}"

    # 1. Audit Isaac Lab
    local lab_target_path
    lab_target_path="$(resolve_repo_dest_path "IsaacLab" "${ISAACLAB_REPO:-https://github.com/isaac-sim/IsaacLab.git}" "${ISAACLAB_DIR:-}")"
    local lab_existing
    lab_existing="$(find_existing_repo "IsaacLab" || echo "")"

    if [[ -n "$lab_existing" ]]; then
        if [[ "$lab_existing" != "$lab_target_path" ]]; then
            DRIFT_ITEMS+=("IsaacLab|PATH_MISLOCATED|${lab_existing}|${lab_target_path}|Repository located at flat or legacy path instead of desired hierarchy")
        fi

        local lab_info
        lab_info="$(get_repo_info "$lab_existing")"
        local desired_ref="${ISAACLAB_TAG:-${ISAACLAB_BRANCH:-main}}"
        
        # Check remotes & ref drift
        local drift_check
        drift_check=$(python3 -c "
import json
info = json.loads('''${lab_info}''')
desired_origin = '${ISAACLAB_REPO:-https://github.com/isaac-sim/IsaacLab.git}'
desired_upstream = '${ISAACLAB_UPSTREAM:-https://github.com/isaac-sim/IsaacLab.git}'
desired_ref = '${desired_ref}'

drifts = []
if desired_origin and info.get('origin') and info.get('origin') != desired_origin and desired_origin not in info.get('origin'):
    drifts.append(f'ORIGIN_MISMATCH|{info.get(\"origin\")}|{desired_origin}|Origin remote points to unexpected URL')

if not info.get('upstream') and desired_origin != desired_upstream:
    drifts.append(f'UPSTREAM_MISSING|None|{desired_upstream}|Upstream canonical remote not wired')

active_ref = info.get('tag') if info.get('tag') else info.get('branch')
if desired_ref and active_ref and active_ref != desired_ref:
    drifts.append(f'REF_DRIFT|{active_ref}|{desired_ref}|Active ref differs from target YAML ref')

for d in drifts:
    print(d)
" 2>/dev/null || true)

        while IFS= read -r line; do
            if [[ -n "$line" ]]; then
                DRIFT_ITEMS+=("IsaacLab|${line}")
            fi
        done <<< "$drift_check"

        # Check symlink
        local sim_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"
        if [[ ! -L "${lab_existing}/_isaac_sim" ]] || [[ "$(readlink -f "${lab_existing}/_isaac_sim" 2>/dev/null)" != "${sim_dir}" ]]; then
            DRIFT_ITEMS+=("IsaacLab|BROKEN_SYMLINK|${lab_existing}/_isaac_sim|${sim_dir}|_isaac_sim symlink broken or points to stale engine")
        fi
    fi

    # 2. Audit IsaacLab-Arena
    local arena_target_path
    arena_target_path="$(resolve_repo_dest_path "IsaacLab-Arena" "${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}" "${ARENA_DIR:-}")"
    local arena_existing
    arena_existing="$(find_existing_repo "IsaacLab-Arena" || echo "")"

    if [[ -n "$arena_existing" && "$arena_existing" != "$arena_target_path" ]]; then
        DRIFT_ITEMS+=("IsaacLab-Arena|PATH_MISLOCATED|${arena_existing}|${arena_target_path}|Arena located at flat or legacy path instead of desired hierarchy")
    fi

    # 3. Audit LeRobot
    local lerobot_target_path
    lerobot_target_path="$(resolve_repo_dest_path "lerobot" "${LEROBOT_REPO:-https://github.com/huggingface/lerobot.git}" "${LEROBOT_DIR:-}")"
    local lerobot_existing
    lerobot_existing="$(find_existing_repo "lerobot" || echo "")"

    if [[ -n "$lerobot_existing" && "$lerobot_existing" != "$lerobot_target_path" ]]; then
        DRIFT_ITEMS+=("LeRobot|PATH_MISLOCATED|${lerobot_existing}|${lerobot_target_path}|LeRobot located at flat or legacy path instead of desired hierarchy")
    fi

    # 4. Audit Conda Environment Drift
    local conda_bin
    conda_bin="$(resolve_conda_bin 2>/dev/null || echo "")"
    local user_env_path
    user_env_path="$(resolve_conda_env_path "isaaclab" 2>/dev/null || echo "")"

    if [[ -d "/opt/conda/envs/isaaclab" && "$user_env_path" != "/opt/conda/envs/isaaclab" ]]; then
        DRIFT_ITEMS+=("CondaEnv|CONDA_ENV_MISLOCATED|/opt/conda/envs/isaaclab|${user_env_path}|Orphaned /opt/conda/envs/isaaclab found outside user's active Conda")
    fi

    if [[ -n "$user_env_path" && (! -d "$user_env_path" || ! -x "$user_env_path/bin/python") ]]; then
        DRIFT_ITEMS+=("CondaEnv|CONDA_ENV_MISSING|None|${user_env_path}|Named 'isaaclab' Conda environment missing in user's Conda runtime")
    fi
}

print_drift_report() {
    log_header "Workspace State & Drift Audit"
    audit_workspace_drift

    if [[ ${#DRIFT_ITEMS[@]} -eq 0 ]]; then
        log_success "Workspace is 100% in sync with declarative profile (${CONFIG_FILE}). Zero drift detected."
        return 0
    fi

    printf "${CLR_BOLD}%-18s | %-18s | %-32s | %-32s${CLR_RESET}\n" \
        "Repository" "Drift Type" "Current State" "Target Desired State"
    echo "----------------------------------------------------------------------------------------------------------------------"

    for item in "${DRIFT_ITEMS[@]}"; do
        IFS='|' read -r repo dtype cur target desc <<< "$item"
        printf "%-18s | ${CLR_YELLOW}%-18s${CLR_RESET} | %-32s | ${CLR_GREEN}%-32s${CLR_RESET}\n" \
            "$repo" "$dtype" "$(basename "$cur")" "$(basename "$target")"
        echo -e "   ${CLR_DIM}↳ ${desc}${CLR_RESET}"
    done
    echo "----------------------------------------------------------------------------------------------------------------------"
    echo -e "Total Drift Issues Found: ${CLR_YELLOW}${#DRIFT_ITEMS[@]}${CLR_RESET}"
    echo -e "Run ${CLR_BOLD}./bin/isaac-installer repair${CLR_RESET} to automatically reconcile and heal all drift."
    echo ""
}

# ==============================================================================
# Self-Healing Reconciliation Engine (`repair` / `fix`)
# ==============================================================================

repair_workspace_drift() {
    log_header "Initiating Workspace Self-Healing & Drift Reconciliation"
    audit_workspace_drift

    if [[ ${#DRIFT_ITEMS[@]} -eq 0 ]]; then
        log_success "No drift detected. Workspace is healthy and clean."
        return 0
    fi

    detect_target_user

    for item in "${DRIFT_ITEMS[@]}"; do
        IFS='|' read -r repo dtype cur target desc <<< "$item"
        log_step "Reconciling [${repo}]: ${dtype}..."

        case "$dtype" in
            PATH_MISLOCATED)
                log_info "Migrating ${cur} -> ${target}..."
                if [[ -d "$target" ]]; then
                    log_warn "Target path ${target} already exists. Skipping directory move to avoid overwrite."
                else
                    mkdir -p "$(dirname "$target")"
                    mv "$cur" "$target"
                    chown -R "${TARGET_USER}:${TARGET_USER}" "$target"
                    register_github_desktop_repo "$target"
                    log_success "Migrated ${repo} to ${target}."
                fi
                ;;

            ORIGIN_MISMATCH)
                log_info "Re-wiring origin remote on ${repo} -> ${target}..."
                sudo -H -u "${TARGET_USER}" git -C "$(find_existing_repo "$repo")" remote set-url origin "$target" 2>/dev/null || true
                log_success "Origin remote updated to ${target}."
                ;;

            UPSTREAM_MISSING)
                log_info "Adding canonical upstream remote on ${repo} -> ${target}..."
                local repo_dir
                repo_dir="$(find_existing_repo "$repo")"
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" remote add upstream "$target" 2>/dev/null || true
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" config remote.upstream.pushurl "PUSH_DISABLED_CANONICAL_UPSTREAM" 2>/dev/null || true
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" fetch upstream 2>/dev/null || true
                log_success "Upstream remote wired and push-protected."
                ;;

            REF_DRIFT)
                log_info "Aligning active git ref on ${repo} -> ${target}..."
                local repo_dir
                repo_dir="$(find_existing_repo "$repo")"
                local is_tag=false
                if [[ "$target" == v* ]]; then is_tag=true; fi
                fetch_and_checkout_ref "$repo_dir" "$target" "$is_tag"
                log_success "Ref aligned to ${target}."
                ;;

            BROKEN_SYMLINK)
                log_info "Healing _isaac_sim symlink -> ${target}..."
                local repo_dir
                repo_dir="$(find_existing_repo "$repo")"
                ln -sfn "${target}" "${repo_dir}/_isaac_sim.tmp.$$"
                mv -Tf "${repo_dir}/_isaac_sim.tmp.$$" "${repo_dir}/_isaac_sim"
                chown -h "${TARGET_USER}:${TARGET_USER}" "${repo_dir}/_isaac_sim"
                log_success "_isaac_sim symlink healed."
                ;;

            CONDA_ENV_MISLOCATED)
                log_info "Cleaning up orphaned system Conda environment ${cur}..."
                rm -rf "$cur" 2>/dev/null || true
                if [[ -d "/opt/conda" && -z "$(ls -A /opt/conda/envs 2>/dev/null)" ]]; then
                    rm -rf "/opt/conda" 2>/dev/null || true
                fi
                log_info "Provisioning native named Conda environment in user's Conda (${target})..."
                install_python_env
                log_success "Conda environment mislocation healed."
                ;;

            CONDA_ENV_MISSING)
                log_info "Provisioning named Conda environment in user's Conda (${target})..."
                install_python_env
                log_success "Named 'isaaclab' Conda environment created."
                ;;
        esac
    done

    # Re-index Python runtime after healing using official ./isaaclab.sh --install in healed Conda env
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    if [[ -d "${lab_dir}" && -x "${lab_dir}/isaaclab.sh" ]]; then
        log_step "Running official ./isaaclab.sh --install in healed Conda environment..."
        local env_path
        env_path="$(resolve_conda_env_path "isaaclab" 2>/dev/null || echo "")"
        if [[ -x "${env_path}/bin/python" ]]; then
            sudo -H -u "${TARGET_USER}" bash -c "
                export CONDA_PREFIX='${env_path}'
                export PATH='${env_path}/bin:\$PATH'
                cd '${lab_dir}'
                ./isaaclab.sh --install
            " 2>/dev/null || true
        else
            sudo -H -u "${TARGET_USER}" bash -c "cd '${lab_dir}' && ./isaaclab.sh --install" 2>/dev/null || true
        fi
    fi

    log_success "Workspace reconciliation complete. All drift resolved."
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

