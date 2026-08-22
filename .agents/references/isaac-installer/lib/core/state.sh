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
    init_state
    local state_file
    state_file="$(resolve_state_file)"
    local state_dir
    state_dir="$(resolve_state_dir)"

    local lab_existing
    lab_existing="$(find_existing_repo "IsaacLab" || echo "")"
    local lab_info="{\"exists\": false}"
    if [[ -n "$lab_existing" ]]; then
        lab_info="$(get_repo_info "$lab_existing")"
    fi

    local arena_existing
    arena_existing="$(find_existing_repo "IsaacLab-Arena" || echo "")"
    local arena_info="{\"exists\": false}"
    if [[ -n "$arena_existing" ]]; then
        arena_info="$(get_repo_info "$arena_existing")"
    fi

    local conda_env
    conda_env="$(resolve_conda_env_path "isaaclab" 2>/dev/null || echo "")"
    local sim_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"

    python3 -c "
import json, datetime
try:
    with open('${state_file}', 'r') as f:
        data = json.load(f)
except Exception:
    data = {}

data['updated_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
data['target_user'] = '${TARGET_USER}'
data['workspace_root'] = '$(resolve_default_workspace_dir)'
data['simulation'] = {
    'version': '${ISAACSIM_VERSION:-6.0.1}',
    'install_dir': '${sim_dir}',
    'exists': $([[ -d "$sim_dir" ]] && echo "True" || echo "False")
}
data['conda'] = {
    'env_name': 'isaaclab',
    'env_path': '${conda_env}',
    'exists': $([[ -d "$conda_env" && -x "$conda_env/bin/python" ]] && echo "True" || echo "False")
}
data['repositories'] = {
    'isaaclab': json.loads('''${lab_info}'''),
    'arena': json.loads('''${arena_info}''')
}

with open('${state_file}', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
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
    ws_root="$(resolve_default_workspace_dir)"
    local layout="${WORKSPACE_LAYOUT:-${CFG_WORKSPACE_LAYOUT:-auto}}"

    # 1. Audit Isaac Lab
    local lab_enabled="${CFG_REPOSITORIES_ISAACLAB_ENABLED:-true}"
    local lab_target_path
    lab_target_path="$(resolve_repo_dest_path "IsaacLab" "${ISAACLAB_REPO:-https://github.com/boredengineering/IsaacLab.git}" "${ISAACLAB_DIR:-}")"
    local lab_existing
    lab_existing="$(find_existing_repo "IsaacLab" || echo "")"

    if [[ "$lab_enabled" == "true" ]]; then
        if [[ -z "$lab_existing" || ! -d "${lab_existing}/.git" ]]; then
            DRIFT_ITEMS+=("IsaacLab|REPO_MISSING|None|${lab_target_path}|Isaac Lab repository is not cloned or installed on disk")
        else
            if [[ "$lab_existing" != "$lab_target_path" ]]; then
                DRIFT_ITEMS+=("IsaacLab|PATH_MISLOCATED|${lab_existing}|${lab_target_path}|Repository located at flat or legacy path instead of desired hierarchy")
            fi

            local lab_info
            lab_info="$(get_repo_info "$lab_existing")"
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
    arena_target_path="$(resolve_repo_dest_path "IsaacLab-Arena" "${ARENA_REPO:-https://github.com/boredengineering/IsaacLab-Arena.git}" "${ARENA_DIR:-}")"
    local arena_existing
    arena_existing="$(find_existing_repo "IsaacLab-Arena" || echo "")"

    if [[ "$arena_enabled" == "true" ]]; then
        if [[ -z "$arena_existing" || ! -d "${arena_existing}/.git" ]]; then
            DRIFT_ITEMS+=("IsaacLab-Arena|REPO_MISSING|None|${arena_target_path}|IsaacLab-Arena repository is not cloned on disk")
        else
            if [[ "$arena_existing" != "$arena_target_path" ]]; then
                DRIFT_ITEMS+=("IsaacLab-Arena|PATH_MISLOCATED|${arena_existing}|${arena_target_path}|Arena located at flat or legacy path instead of desired hierarchy")
            fi

            local arena_info
            arena_info="$(get_repo_info "$arena_existing")"
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
    lerobot_target_path="$(resolve_repo_dest_path "lerobot" "${LEROBOT_REPO:-https://github.com/huggingface/lerobot.git}" "${LEROBOT_DIR:-}")"
    local lerobot_existing
    lerobot_existing="$(find_existing_repo "lerobot" || echo "")"

    if [[ "$lerobot_enabled" == "true" ]]; then
        if [[ -z "$lerobot_existing" || ! -d "${lerobot_existing}/.git" ]]; then
            DRIFT_ITEMS+=("LeRobot|REPO_MISSING|None|${lerobot_target_path}|LeRobot repository is not cloned on disk")
        else
            if [[ "$lerobot_existing" != "$lerobot_target_path" ]]; then
                DRIFT_ITEMS+=("LeRobot|PATH_MISLOCATED|${lerobot_existing}|${lerobot_target_path}|LeRobot located at flat or legacy path instead of desired hierarchy")
            fi

            local lerobot_info
            lerobot_info="$(get_repo_info "$lerobot_existing")"
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
    conda_bin="$(resolve_conda_bin 2>/dev/null || echo "")"
    local user_env_path
    user_env_path="$(resolve_conda_env_path "isaaclab" 2>/dev/null || echo "")"

    if [[ -d "/opt/conda/envs/isaaclab" || -d "/opt/conda" ]]; then
        DRIFT_ITEMS+=("CondaEnv|CONDA_ENV_MISLOCATED|/opt/conda/envs/isaaclab|${user_env_path}|Orphaned /opt/conda system environment found outside user's active Conda")
    fi

    if [[ -n "$user_env_path" && (! -d "$user_env_path" || ! -x "$user_env_path/bin/python") ]]; then
        DRIFT_ITEMS+=("CondaEnv|CONDA_ENV_MISSING|None|${user_env_path}|Named 'isaaclab' Conda environment missing in user's Conda runtime")
    fi

    # 5. Audit Standalone Isaac Sim Bridge, .pth link & Vulkan Hook Drift
    local sim_dir
    sim_dir="$(resolve_isaacsim_dir 2>/dev/null || echo "")"
    if [[ -n "$sim_dir" && -d "$sim_dir" ]]; then
        if [[ -f "${sim_dir}/setup_python_env.sh" && ! -f "${sim_dir}/setup_conda_env.sh" ]]; then
            DRIFT_ITEMS+=("IsaacSim|SIM_BRIDGE_MISSING|None|${sim_dir}/setup_conda_env.sh|Isaac Sim 6.0 setup_conda_env.sh bridge script missing")
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
        sync_state_ledger
        return 0
    fi

    detect_target_user

    for item in "${DRIFT_ITEMS[@]}"; do
        IFS='|' read -r repo dtype cur target desc <<< "$item"
        log_step "Reconciling [${repo}]: ${dtype}..."

        case "$dtype" in
            REPO_MISSING)
                log_info "Provisioning missing repository [${repo}] -> ${target}..."
                case "$repo" in
                    IsaacLab)
                        install_isaac_lab
                        ;;
                    IsaacLab-Arena)
                        install_isaaclab_arena
                        ;;
                    LeRobot)
                        install_physical_ai_stack
                        ;;
                esac
                log_success "${repo} provisioned."
                ;;

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
                local repo_dir
                repo_dir="$(find_existing_repo "$repo")"
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" config --global --add safe.directory "$repo_dir" 2>/dev/null || true
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" remote set-url origin "$target" 2>/dev/null || \
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" remote add origin "$target" 2>/dev/null || true
                log_success "Origin remote updated to ${target}."
                ;;

            UPSTREAM_MISSING|UPSTREAM_MISMATCH)
                log_info "Adding canonical upstream remote on ${repo} -> ${target}..."
                local repo_dir
                repo_dir="$(find_existing_repo "$repo")"
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" config --global --add safe.directory "$repo_dir" 2>/dev/null || true
                sudo -H -u "${TARGET_USER}" git -C "$repo_dir" remote set-url upstream "$target" 2>/dev/null || \
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
                deploy_isaacsim_conda_bridge "${target}"
                log_success "_isaac_sim symlink healed."
                ;;

            CONDA_ENV_MISLOCATED)
                log_info "Cleaning up orphaned system Conda environment and /opt/conda..."
                rm -rf "/opt/conda" 2>/dev/null || true
                for env_txt in "${TARGET_HOME}/.conda/environments.txt" "/root/.conda/environments.txt"; do
                    if [[ -f "$env_txt" ]]; then
                        sed -i '\|/opt/conda|d' "$env_txt" 2>/dev/null || true
                    fi
                done
                log_info "Provisioning native named Conda environment in user's Conda (${target})..."
                install_python_env
                log_success "Conda environment mislocation healed."
                ;;

            CONDA_ENV_MISSING)
                log_info "Provisioning named Conda environment in user's Conda (${target})..."
                install_python_env
                log_success "Conda environment provisioned."
                ;;

            SIM_BRIDGE_MISSING|SIM_PTH_MISSING)
                log_info "Reconciling Isaac Sim bridge and site-packages .pth link..."
                local sim_dir
                sim_dir="$(resolve_isaacsim_dir)"
                deploy_isaacsim_conda_bridge "$sim_dir"
                log_success "Isaac Sim bridge and .pth link reconciled."
                ;;

            VULKAN_HOOK_DRIFT|DEACT_HOOK_DRIFT)
                log_info "Healing Conda environment activation & deactivation hooks..."
                install_python_env
                log_success "Conda activation and deactivation hooks healed."
                ;;

            EMPTY_CASE_DUPLICATE)
                log_info "Cleaning empty duplicate folder ${cur}..."
                rmdir "$cur" 2>/dev/null || rm -rf "$cur" 2>/dev/null || true
                log_success "Cleaned duplicate folder ${cur}."
                ;;
        esac
    done

    # Run extension installation and sync ledger
    local lab_dir
    lab_dir="$(resolve_active_repo_dir "IsaacLab")"
    if [[ -d "$lab_dir" && -x "$lab_dir/isaaclab.sh" ]]; then
        log_step "Running official ./isaaclab.sh --install in healed Conda environment..."
        local env_path
        env_path="$(resolve_conda_env_path "isaaclab")"
        local conda_bin
        conda_bin="$(resolve_conda_bin)"
        local conda_root
        conda_root="$(dirname "$(dirname "$conda_bin")")"
        if [[ -d "$env_path" ]]; then
            sudo -H -u "${TARGET_USER}" bash -l -c "
                export SHELL=/bin/bash
                export USER='${TARGET_USER}'
                export HOME='${TARGET_HOME}'
                export CONDA_NO_PLUGINS=true
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
                cd '${lab_dir}'
                '${conda_bin}' run -n isaaclab ./isaaclab.sh -i
            " || true
        fi
    fi

    sync_state_ledger
    log_success "Workspace reconciliation complete. All drift resolved."
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

