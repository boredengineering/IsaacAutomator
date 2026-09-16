#!/usr/bin/env bash
# ==============================================================================
# state.sh - Persistent State Ledger, Drift Detection & Self-Healing Engine
# ==============================================================================

RESUME_SERVICE="/etc/systemd/system/isaac-installer-resume.service"

resolve_state_dir() {
    detect_target_user
    echo "${TARGET_HOME}/.isaac-installer"
}

resolve_state_file() {
    detect_target_user
    echo "${TARGET_HOME}/.isaac-installer/state.json"
}

init_state() {
    detect_target_user
    local state_dir
    state_dir="$(resolve_state_dir)"
    local state_file
    state_file="$(resolve_state_file)"

    mkdir -p "${state_dir}"
    if [[ ! -f "${state_file}" ]]; then
        cat << JSON > "${state_file}"
{
  "current_stage": "init",
  "stages_completed": [],
  "updated_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "status": "in_progress",
  "workspace_layout": "${WORKSPACE_LAYOUT:-auto}",
  "repositories": {}
}
JSON
        chown -R "${TARGET_USER}:${TARGET_USER}" "${state_dir}" 2>/dev/null || true
    fi
}

get_current_stage() {
    local state_file
    state_file="$(resolve_state_file)"
    if [[ -f "${state_file}" ]]; then
        grep -o '"current_stage": *"[^"]*"' "${state_file}" | cut -d'"' -f4
    else
        echo "init"
    fi
}

is_stage_completed() {
    local stage_name="$1"
    local state_file
    state_file="$(resolve_state_file)"
    if [[ -f "${state_file}" ]]; then
        grep -q "\"${stage_name}\"" "${state_file}"
    else
        return 1
    fi
}

set_stage() {
    local next_stage="$1"
    init_state
    local state_file
    state_file="$(resolve_state_file)"
    local state_dir
    state_dir="$(resolve_state_dir)"
    
    local updated_json
    updated_json=$(python3 -c "
import json, datetime
try:
    with open('${state_file}', 'r') as f:
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
    echo "$updated_json" > "${state_file}"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${state_dir}" 2>/dev/null || true
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
    local state_file
    state_file="$(resolve_state_file)"
    local state_dir
    state_dir="$(resolve_state_dir)"

    python3 -c "
import json, datetime
try:
    with open('${state_file}', 'r') as f:
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

with open('${state_file}', 'w') as f:
    json.dump(data, f, indent=2)
"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${state_dir}" 2>/dev/null || true
}

# Takes a full snapshot of active workspace state and writes it to state.json
sync_state_ledger() {
    detect_target_user
    local ws_root sim_dir conda_env state_file state_dir
    local lab_dir arena_dir gr00t_dir lerobot_dir
    # Resolve everything before initialization/writes. Refusal is not absence.
    ws_root="$(resolve_default_workspace_dir)" || return $?
    lab_dir="$(resolve_isaaclab_dir)" || return $?
    arena_dir="$(resolve_arena_dir)" || return $?
    gr00t_dir="$(resolve_gr00t_dir)" || return $?
    lerobot_dir="$(resolve_lerobot_dir)" || return $?
    conda_env="$(resolve_conda_env_path "isaaclab")" || return $?
    sim_dir="$(resolve_isaacsim_dir)" || return $?
    state_file="$(resolve_state_file)" || return $?
    state_dir="$(resolve_state_dir)" || return $?

    local path info
    local repo_info=()
    for path in "$lab_dir" "$arena_dir" "$gr00t_dir" "$lerobot_dir"; do
        info='{"exists": false}'
        if [[ -d "$path/.git" ]]; then
            info="$(get_repo_info "$path")" || return $?
        fi
        repo_info+=("$info")
    done
    init_state || return $?
    # Paths/metadata are data, never interpolated Python source.
    python3 - "$state_file" "$TARGET_USER" "$ws_root" "$sim_dir" \
        "${ISAACSIM_VERSION:-6.0.1}" "$conda_env" \
        "$lab_dir" "$arena_dir" "$gr00t_dir" "$lerobot_dir" "${repo_info[@]}" <<'PY'
import datetime
import json
import os
import sys
state_file, user, root, sim, version, conda = sys.argv[1:7]
with open(state_file) as stream:
    data = json.load(stream)
repositories = {}
for key, path, raw in zip(('isaaclab', 'arena', 'gr00t', 'lerobot'), sys.argv[7:11], sys.argv[11:15]):
    info = json.loads(raw)
    info['path'] = path
    repositories[key] = info
# Path selection is not identity/adoption/healthy-runtime evidence.
data.update(updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            target_user=user, workspace_root=root, repositories=repositories,
            simulation=dict(version=version, install_dir=sim, exists=os.path.isdir(sim)),
            conda=dict(env_name='isaaclab', env_path=conda,
                       exists=os.path.isdir(conda) and os.access(os.path.join(conda, 'bin/python'), os.X_OK)))
with open(state_file, 'w') as stream:
    json.dump(data, stream, indent=2)
PY
    local result=$?
    [[ "$result" -eq 0 ]] || return "$result"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${state_dir}" 2>/dev/null || true
}

# ==============================================================================
# State Drift Detection Engine
# ==============================================================================

DRIFT_ITEMS=()

audit_workspace_drift() {
    DRIFT_ITEMS=()
    detect_target_user

    local ws_root
    ws_root="$(resolve_default_workspace_dir)" || return $?
    local layout="${WORKSPACE_LAYOUT:-${CFG_WORKSPACE_LAYOUT:-auto}}"

    # 1. Audit Isaac Lab
    local lab_enabled="${CFG_REPOSITORIES_ISAACLAB_ENABLED:-true}"
    local lab_target_path
    lab_target_path="$(resolve_isaaclab_dir)" || return $?
    local lab_existing
    lab_existing="${lab_target_path}"

    if [[ "$lab_enabled" == "true" ]]; then
        if [[ -z "$lab_existing" || ! -d "${lab_existing}/.git" ]]; then
            DRIFT_ITEMS+=("IsaacLab|REPO_MISSING|None|${lab_target_path}|Isaac Lab repository is not cloned or installed on disk")
        else
            if [[ "$lab_existing" != "$lab_target_path" ]]; then
                DRIFT_ITEMS+=("IsaacLab|PATH_MISLOCATED|${lab_existing}|${lab_target_path}|Repository located at flat or legacy path instead of desired hierarchy")
            fi

            local lab_info
            lab_info="$(get_repo_info "$lab_existing")" || return $?
            local desired_ref="${ISAACLAB_TAG:-${ISAACLAB_BRANCH:-main}}"
            
            # Check remotes & ref drift
            local desired_origin_norm
            desired_origin_norm="$(normalize_git_url "${ISAACLAB_REPO:-https://github.com/boredengineering/IsaacLab.git}")"
            local desired_upstream_norm
            desired_upstream_norm="$(normalize_git_url "${ISAACLAB_UPSTREAM:-https://github.com/isaac-sim/IsaacLab.git}")"

            local drift_check
            drift_check=$(python3 -c "
import json
info = json.loads('''${lab_info}''')
desired_origin = '${desired_origin_norm}'
desired_upstream = '${desired_upstream_norm}'
desired_ref = '${desired_ref}'

def clean_url(u):
    if not u: return ''
    return u.rstrip('/').removesuffix('.git').lower()

cur_origin = info.get('origin', '')
cur_upstream = info.get('upstream', '')

drifts = []
if desired_origin and cur_origin and clean_url(cur_origin) != clean_url(desired_origin):
    drifts.append(f'ORIGIN_MISMATCH|{cur_origin}|{desired_origin}|Origin remote points to unexpected URL')

if clean_url(desired_origin) != clean_url(desired_upstream):
    if not cur_upstream:
        drifts.append(f'UPSTREAM_MISSING|None|{desired_upstream}|Upstream canonical remote not wired')
    elif clean_url(cur_upstream) != clean_url(desired_upstream):
        drifts.append(f'UPSTREAM_MISMATCH|{cur_upstream}|{desired_upstream}|Upstream remote points to unexpected URL')

active_tags = info.get('tags', [])
cur_branch = info.get('branch', '')
cur_tag = info.get('tag', '')

if desired_ref:
    is_matching = False
    if desired_ref in active_tags:
        is_matching = True
    elif cur_branch == desired_ref or cur_branch == f'release/{desired_ref}':
        is_matching = True
    elif cur_tag == desired_ref:
        is_matching = True
    
    if not is_matching:
        active_ref = cur_tag if cur_tag else cur_branch
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
    fi

    # 2. Audit IsaacLab-Arena
    local arena_enabled="${CFG_REPOSITORIES_ARENA_ENABLED:-true}"
    local arena_target_path
    arena_target_path="$(resolve_arena_dir)" || return $?
    local arena_existing
    arena_existing="${arena_target_path}"

    if [[ "$arena_enabled" == "true" ]]; then
        if [[ -z "$arena_existing" || ! -d "${arena_existing}/.git" ]]; then
            DRIFT_ITEMS+=("IsaacLab-Arena|REPO_MISSING|None|${arena_target_path}|IsaacLab-Arena repository is not cloned on disk")
        else
            if [[ "$arena_existing" != "$arena_target_path" ]]; then
                DRIFT_ITEMS+=("IsaacLab-Arena|PATH_MISLOCATED|${arena_existing}|${arena_target_path}|Arena located at flat or legacy path instead of desired hierarchy")
            fi

            local arena_info
            arena_info="$(get_repo_info "$arena_existing")" || return $?
            local arena_desired_ref="${ARENA_TAG:-${ARENA_BRANCH:-release/0.1.1}}"
            local arena_origin_norm="$(normalize_git_url "${ARENA_REPO:-https://github.com/boredengineering/IsaacLab-Arena.git}")"
            local arena_upstream_norm="$(normalize_git_url "${ARENA_UPSTREAM:-https://github.com/isaac-sim/IsaacLab-Arena.git}")"

            local arena_drift
            arena_drift=$(python3 -c "
import json
info = json.loads('''${arena_info}''')
desired_origin = '${arena_origin_norm}'
desired_upstream = '${arena_upstream_norm}'
desired_ref = '${arena_desired_ref}'

def clean_url(u):
    if not u: return ''
    return u.rstrip('/').removesuffix('.git').lower()

cur_origin = info.get('origin', '')
cur_upstream = info.get('upstream', '')

drifts = []
if desired_origin and cur_origin and clean_url(cur_origin) != clean_url(desired_origin):
    drifts.append(f'ORIGIN_MISMATCH|{cur_origin}|{desired_origin}|Origin remote points to unexpected URL')

if clean_url(desired_origin) != clean_url(desired_upstream):
    if not cur_upstream:
        drifts.append(f'UPSTREAM_MISSING|None|{desired_upstream}|Upstream canonical remote not wired')
    elif clean_url(cur_upstream) != clean_url(desired_upstream):
        drifts.append(f'UPSTREAM_MISMATCH|{cur_upstream}|{desired_upstream}|Upstream remote points to unexpected URL')

active_tags = info.get('tags', [])
cur_branch = info.get('branch', '')
cur_tag = info.get('tag', '')

if desired_ref:
    is_matching = False
    if desired_ref in active_tags:
        is_matching = True
    elif cur_branch == desired_ref or cur_branch == f'release/{desired_ref}':
        is_matching = True
    elif cur_tag == desired_ref:
        is_matching = True
    
    if not is_matching:
        active_ref = cur_tag if cur_tag else cur_branch
        drifts.append(f'REF_DRIFT|{active_ref}|{desired_ref}|Active ref differs from target YAML ref')

for d in drifts:
    print(d)
" 2>/dev/null || true)

            while IFS= read -r line; do
                if [[ -n "$line" ]]; then
                    DRIFT_ITEMS+=("IsaacLab-Arena|${line}")
                fi
            done <<< "$arena_drift"
        fi
    fi

    # 3. Audit LeRobot
    local lerobot_enabled="${CFG_REPOSITORIES_LEROBOT_ENABLED:-false}"
    local lerobot_target_path
    lerobot_target_path="$(resolve_lerobot_dir)" || return $?
    local lerobot_existing
    lerobot_existing="${lerobot_target_path}"

    if [[ "$lerobot_enabled" == "true" ]]; then
        if [[ -z "$lerobot_existing" || ! -d "${lerobot_existing}/.git" ]]; then
            DRIFT_ITEMS+=("LeRobot|REPO_MISSING|None|${lerobot_target_path}|LeRobot repository is not cloned on disk")
        else
            if [[ "$lerobot_existing" != "$lerobot_target_path" ]]; then
                DRIFT_ITEMS+=("LeRobot|PATH_MISLOCATED|${lerobot_existing}|${lerobot_target_path}|LeRobot located at flat or legacy path instead of desired hierarchy")
            fi

            local lerobot_info
            lerobot_info="$(get_repo_info "$lerobot_existing")" || return $?
            local lerobot_desired_ref="${LEROBOT_TAG:-${LEROBOT_BRANCH:-main}}"
            local lerobot_origin_norm="$(normalize_git_url "${LEROBOT_REPO:-https://github.com/huggingface/lerobot.git}")"
            local lerobot_upstream_norm="$(normalize_git_url "${LEROBOT_UPSTREAM:-https://github.com/huggingface/lerobot.git}")"

            local lerobot_drift
            lerobot_drift=$(python3 -c "
import json
info = json.loads('''${lerobot_info}''')
desired_origin = '${lerobot_origin_norm}'
desired_upstream = '${lerobot_upstream_norm}'
desired_ref = '${lerobot_desired_ref}'

def clean_url(u):
    if not u: return ''
    return u.rstrip('/').removesuffix('.git').lower()

cur_origin = info.get('origin', '')
cur_upstream = info.get('upstream', '')

drifts = []
if desired_origin and cur_origin and clean_url(cur_origin) != clean_url(desired_origin):
    drifts.append(f'ORIGIN_MISMATCH|{cur_origin}|{desired_origin}|Origin remote points to unexpected URL')

if clean_url(desired_origin) != clean_url(desired_upstream):
    if not cur_upstream:
        drifts.append(f'UPSTREAM_MISSING|None|{desired_upstream}|Upstream canonical remote not wired')
    elif clean_url(cur_upstream) != clean_url(desired_upstream):
        drifts.append(f'UPSTREAM_MISMATCH|{cur_upstream}|{desired_upstream}|Upstream remote points to unexpected URL')

active_tags = info.get('tags', [])
cur_branch = info.get('branch', '')
cur_tag = info.get('tag', '')

if desired_ref:
    is_matching = False
    if desired_ref in active_tags:
        is_matching = True
    elif cur_branch == desired_ref or cur_branch == f'release/{desired_ref}':
        is_matching = True
    elif cur_tag == desired_ref:
        is_matching = True
    
    if not is_matching:
        active_ref = cur_tag if cur_tag else cur_branch
        drifts.append(f'REF_DRIFT|{active_ref}|{desired_ref}|Active ref differs from target YAML ref')

for d in drifts:
    print(d)
" 2>/dev/null || true)

            while IFS= read -r line; do
                if [[ -n "$line" ]]; then
                    DRIFT_ITEMS+=("LeRobot|${line}")
                fi
            done <<< "$lerobot_drift"
        fi
    fi

    # 4. Audit Conda Environment Drift
    local conda_bin
    conda_bin="$(resolve_conda_bin)" || return $?
    local user_env_path
    user_env_path="$(resolve_conda_env_path "isaaclab")" || return $?

    if [[ -d "/opt/conda/envs/isaaclab" || -d "/opt/conda" ]]; then
        DRIFT_ITEMS+=("CondaEnv|CONDA_ENV_MISLOCATED|/opt/conda/envs/isaaclab|${user_env_path}|Orphaned /opt/conda system environment found outside user's active Conda")
    fi

    if [[ -n "$user_env_path" && (! -d "$user_env_path" || ! -x "$user_env_path/bin/python") ]]; then
        DRIFT_ITEMS+=("CondaEnv|CONDA_ENV_MISSING|None|${user_env_path}|Named 'isaaclab' Conda environment missing in user's Conda runtime")
    fi

    # 5. Audit Standalone Isaac Sim Bridge, .pth link & Vulkan Hook Drift
    local sim_dir
    sim_dir="$(resolve_isaacsim_dir)" || return $?
    if [[ -n "$sim_dir" && -d "$sim_dir" ]]; then
        if [[ -f "${sim_dir}/setup_python_env.sh" && ! -f "${sim_dir}/setup_conda_env.sh" ]]; then
            DRIFT_ITEMS+=("IsaacSim|SIM_BRIDGE_MISSING|None|${sim_dir}/setup_conda_env.sh|Isaac Sim 6.0.1 setup_conda_env.sh bridge script missing")
        fi

        if [[ -n "$user_env_path" && -d "$user_env_path" ]]; then
            local sp_dir
            sp_dir=$(find "${user_env_path}/lib" -maxdepth 2 -type d -name "site-packages" 2>/dev/null | head -n 1)
            if [[ -d "$sp_dir" && ! -f "${sp_dir}/isaacsim_standalone.pth" ]]; then
                DRIFT_ITEMS+=("IsaacSim|SIM_PTH_MISSING|None|${sp_dir}/isaacsim_standalone.pth|isaacsim_standalone.pth missing from Conda site-packages")
            fi

            local act_hook="${user_env_path}/etc/conda/activate.d/00_isaaclab_env.sh"
            if [[ ! -f "$act_hook" || $(grep -c "VK_ICD_FILENAMES=/etc/vulkan" "$act_hook" 2>/dev/null || true) -gt 0 ]]; then
                DRIFT_ITEMS+=("CondaEnv|VULKAN_HOOK_DRIFT|Static / Missing Hook|${act_hook}|Conda activation hook missing or contains hardcoded invalid Vulkan ICD path")
            fi

            local deact_hook="${user_env_path}/etc/conda/deactivate.d/00_isaaclab_env.sh"
            if [[ ! -f "$deact_hook" || $(grep -c "unset PYTHONPATH" "$deact_hook" 2>/dev/null || true) -eq 0 ]]; then
                DRIFT_ITEMS+=("CondaEnv|DEACT_HOOK_DRIFT|Missing Sanitization|${deact_hook}|Conda deactivation hook missing 'unset PYTHONPATH' isolation")
            fi
        fi
    fi

    # 6. Audit Case-Drift Duplicate Directories in Workspace Root
    if [[ -d "${ws_root}" ]]; then
        for dir in "${ws_root}"/*; do
            if [[ -d "$dir" ]]; then
                local bname="$(basename "$dir")"
                local lower_bname="${bname,,}"
                for other in "${ws_root}"/*; do
                    if [[ -d "$other" && "$dir" != "$other" ]]; then
                        local other_bname="$(basename "$other")"
                        if [[ "${other_bname,,}" == "$lower_bname" ]]; then
                            if [[ -z "$(ls -A "$other" 2>/dev/null)" ]]; then
                                DRIFT_ITEMS+=("Workspace|EMPTY_CASE_DUPLICATE|${other}|${dir}|Empty case-duplicate directory found in workspace root")
                            fi
                        fi
                    fi
                done
            fi
        done
    fi
}

print_drift_report() {
    log_header "Workspace State & Drift Audit"
    audit_workspace_drift || return $?

    if [[ ${#DRIFT_ITEMS[@]} -eq 0 ]]; then
        log_success "Workspace is 100% in sync with declarative profile (${CONFIG_FILE}). Zero drift detected."
        return 0
    fi

    printf "${CLR_BOLD}%-18s | %-18s | %-32s | %-32s${CLR_RESET}\n" \
        "Repository" "Drift Type" "Current State" "Target Desired State"
    echo "----------------------------------------------------------------------------------------------------------------------"

    for item in "${DRIFT_ITEMS[@]}"; do
        IFS='|' read -r repo dtype cur target desc <<< "$item"
        local display_cur="$cur"
        local display_target="$target"
        if [[ ${#display_cur} -gt 32 ]]; then display_cur="...${display_cur: -29}"; fi
        if [[ ${#display_target} -gt 32 ]]; then display_target="...${display_target: -29}"; fi
        printf "%-18s | ${CLR_YELLOW}%-18s${CLR_RESET} | %-32s | ${CLR_GREEN}%-32s${CLR_RESET}\n" \
            "$repo" "$dtype" "$display_cur" "$display_target"
        echo -e "   ${CLR_DIM}↳ ${desc}${CLR_RESET}"
    done
    echo "----------------------------------------------------------------------------------------------------------------------"
    echo -e "Total Drift Issues Found: ${CLR_YELLOW}${#DRIFT_ITEMS[@]}${CLR_RESET}"
    echo "Automatic repair/adoption is unsupported. The repair command reports selected paths only; no reconciliation is attempted."
    echo ""
}

# ==============================================================================
# Self-Healing Reconciliation Engine (`repair` / `fix`)
# ==============================================================================

# Selection-only planning: no drift probes, metadata imports, Git or writes.
# Unsupported mutation remains explicit; this is not an adoption/action receipt.
plan_workspace_repair() {
    local lab_dir arena_dir gr00t_dir lerobot_dir
    lab_dir="$(resolve_isaaclab_dir)" || return $?
    arena_dir="$(resolve_arena_dir)" || return $?
    gr00t_dir="$(resolve_gr00t_dir)" || return $?
    lerobot_dir="$(resolve_lerobot_dir)" || return $?
    python3 - "$lab_dir" "$arena_dir" "$gr00t_dir" "$lerobot_dir" <<'PY'
import json
import sys
print(json.dumps(dict(
    status='unsupported', mutation_supported=False,
    reason='Existing-resource repair/adoption requires a separately implemented and reviewed preservation policy; no actions were attempted.',
    selected_paths=dict(zip(('isaaclab', 'arena', 'gr00t', 'lerobot'), sys.argv[1:])),
    actions=[]), indent=2))
PY
}

repair_workspace_drift() {
    plan_workspace_repair || return $?
    return 77
}

register_resume_hook() {
    local script_path
    script_path="$(readlink -f "$0")"

    cat << SERVICE | run_as_root "tee '${RESUME_SERVICE}' >/dev/null"
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

    if command -v systemctl &>/dev/null && [[ -d /run/systemd/system ]]; then
        run_as_root "systemctl daemon-reload && systemctl enable isaac-installer-resume.service 2>/dev/null || true"
    fi
}

clear_resume_hook() {
    if [[ -n "${RESUME_SERVICE:-}" && -f "${RESUME_SERVICE}" ]]; then
        if command -v systemctl &>/dev/null && [[ -d /run/systemd/system ]]; then
            run_as_root "systemctl disable isaac-installer-resume.service 2>/dev/null || true"
        fi
        run_as_root "rm -f '${RESUME_SERVICE}'"
        if command -v systemctl &>/dev/null && [[ -d /run/systemd/system ]]; then
            run_as_root "systemctl daemon-reload 2>/dev/null || true"
        fi
    fi
}

