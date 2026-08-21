#!/usr/bin/env bash
# ==============================================================================
# isaaclab.sh - Isaac Lab Robotics Framework Installation, Versioning & PyTorch Linkage
# ==============================================================================

resolve_isaaclab_dir() {
    local git_repo="${ISAACLAB_REPO:-https://github.com/isaac-sim/IsaacLab.git}"
    resolve_repo_dest_path "IsaacLab" "${git_repo}" "${ISAACLAB_DIR:-}"
}

check_isaac_lab() {
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    if [[ -d "${lab_dir}" && -L "${lab_dir}/_isaac_sim" && -x "${lab_dir}/isaaclab.sh" ]]; then
        STAGE_CHECK_MSG="Isaac Lab framework already cloned and linked at ${lab_dir}"
        return 0
    else
        STAGE_CHECK_MSG="Isaac Lab framework not installed or _isaac_sim symlink missing at ${lab_dir}"
        return 1
    fi
}

install_isaac_lab() {
    log_step "Checking Isaac Lab Framework Status..."

    local sim_dir="${ISAACSIM_DIR:-${TARGET_HOME}/IsaacSim}"
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    local git_repo="${ISAACLAB_REPO:-https://github.com/isaac-sim/IsaacLab.git}"
    local official_upstream="${ISAACLAB_UPSTREAM:-https://github.com/isaac-sim/IsaacLab.git}"
    local git_branch="${ISAACLAB_BRANCH:-main}"
    local git_tag="${ISAACLAB_TAG:-}"

    if [[ ! -d "${sim_dir}" ]]; then
        log_fatal "Isaac Sim directory ${sim_dir} not found. Isaac Sim must be installed first."
    fi

    # 1. Setup repository with Hierarchy, Fork + Upstream support, and Tag/Branch resolution
    setup_git_repo_with_fork "${lab_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" "${git_tag}" false

    # 2. Create standard _isaac_sim symlink (Atomic staging)
    log_info "Linking ${sim_dir} -> ${lab_dir}/_isaac_sim..."
    ln -sfn "${sim_dir}" "${lab_dir}/_isaac_sim.tmp.$$"
    mv -Tf "${lab_dir}/_isaac_sim.tmp.$$" "${lab_dir}/_isaac_sim"
    chown -h "${TARGET_USER}:${TARGET_USER}" "${lab_dir}/_isaac_sim"

    # Deploy Isaac Sim 6.0 Conda Runtime Bridge
    deploy_isaacsim_conda_bridge "${sim_dir}"

    # 3. Execute Isaac Lab Installer & Topological Extension Setup
    log_info "Installing Isaac Lab extensions in topological order..."
    local env_path
    env_path="$(resolve_conda_env_path "isaaclab")"
    local conda_py="${env_path}/bin/python"
    local uv_bin
    uv_bin="$(command -v uv || echo "${TARGET_HOME}/.local/bin/uv")"

    if [[ -x "${conda_py}" && -x "${uv_bin}" ]]; then
        log_info "Accelerating extension installation into 'isaaclab' Conda environment (${conda_py}) via UV..."
        sudo -H -u "${TARGET_USER}" bash -c "
            cd '${lab_dir}'
            # Topological installation order: Base -> Assets -> Tasks -> RL
            for ext in source/extensions/omni.isaac.lab \
                       source/extensions/omni.isaac.lab_assets \
                       source/extensions/omni.isaac.lab_tasks \
                       source/extensions/omni.isaac.lab_rl \
                       source/isaaclab \
                       source/isaaclab_assets \
                       source/isaaclab_tasks \
                       source/isaaclab_rl; do
                if [[ -d \"\$ext\" ]]; then
                    echo \"  ↳ Linking \$ext...\"
                    '${uv_bin}' pip install --python '${conda_py}' -e \"\$ext\" 2>/dev/null || true
                fi
            done
        "
    fi

    log_info "Running native ./isaaclab.sh --install inside Conda environment via conda run..."
    local conda_bin
    conda_bin="$(resolve_conda_bin)"
    local conda_root
    conda_root="$(dirname "$(dirname "$conda_bin")")"
    sudo -H -u "${TARGET_USER}" bash -l -c "
        export SHELL=/bin/bash
        export USER='${TARGET_USER}'
        export HOME='${TARGET_HOME}'
        export CONDA_NO_PLUGINS=true
        source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
        cd '${lab_dir}'
        '${conda_bin}' run -n '${CONDA_ENV_NAME:-isaaclab}' ./isaaclab.sh -i
    " || true

    # 4. Verify PyTorch CUDA Tensors
    log_info "Verifying PyTorch CUDA acceleration in Isaac Lab environments..."
    local sim_ok=false
    local conda_ok=false

    if sudo -H -u "${TARGET_USER}" bash -c "
        cd '${lab_dir}'
        ./isaaclab.sh -p -c 'import torch; assert torch.cuda.is_available(), \"CUDA unavailable\"; print(\"  ✔ Isaac Sim Bundled PyTorch:\", torch.cuda.get_device_name(0))'
    " 2>/dev/null; then
        sim_ok=true
    fi

    if [[ -x "${conda_py}" ]]; then
        if sudo -H -u "${TARGET_USER}" bash -c "
            '${conda_py}' -c 'import torch; assert torch.cuda.is_available(), \"CUDA unavailable\"; print(\"  ✔ Named Conda Env PyTorch:\", torch.cuda.get_device_name(0))'
        " 2>/dev/null; then
            conda_ok=true
        fi
    fi

    if [[ "$sim_ok" == true || "$conda_ok" == true ]]; then
        log_success "Isaac Lab installation verified successfully."
    else
        log_warn "Isaac Lab PyTorch verification encountered an issue. Check GPU driver / Vulkan status."
    fi

    register_github_desktop_repo "${lab_dir}"
}

# ==============================================================================
# CLI Subcommands for Isaac Lab Version & Fork Management (`isaac-installer lab ...`)
# ==============================================================================

cmd_lab() {
    local subcmd="${1:-status}"
    shift || true

    local lab_dir
    lab_dir="$(resolve_active_repo_dir "IsaacLab" "${ISAACLAB_REPO:-}" "${ISAACLAB_DIR:-}")"

    case "$subcmd" in
        status)
            log_header "Isaac Lab Framework & Repository Status"
            if [[ ! -d "${lab_dir}/.git" ]]; then
                log_info "Isaac Lab repository is not yet cloned or installed at ${lab_dir}."
                log_info "To install, run: sudo ./bin/isaac-installer install"
                return 0
            fi

            local info
            info="$(get_repo_info "${lab_dir}")"
            local sync_info
            sync_info="$(check_fork_sync_status "${lab_dir}")"
            
            python3 -c "
import json
data = json.loads('''${info}''')
sync = json.loads('''${sync_info}''')
print('  Directory:        ', data.get('path'))
print('  Active Branch:    ', data.get('branch'))
print('  Active Tag:       ', data.get('tag') or '(none / on branch)')
print('  Current Commit:   ', data.get('commit')[:10] if data.get('commit') else 'unknown')
print('  Origin Remote:    ', data.get('origin'))
print('  Upstream Remote:  ', data.get('upstream') or '(none)')
print('  Working Tree:     ', 'DIRTY (uncommitted edits)' if data.get('dirty') else 'CLEAN')

if sync.get('has_upstream'):
    behind = sync.get('behind', 0)
    ahead = sync.get('ahead', 0)
    if behind == 0 and ahead == 0:
        print('  Upstream Sync:     IN SYNC with ' + sync.get('upstream_ref', 'upstream/main'))
    else:
        status_parts = []
        if behind > 0: status_parts.append(f'{behind} commits behind')
        if ahead > 0: status_parts.append(f'{ahead} commits ahead')
        print(f'  Upstream Sync:     OUT OF SYNC ({', '.join(status_parts)}) -> Run ./bin/isaac-installer lab sync')
"
            local sim_link=""
            if [[ -L "${lab_dir}/_isaac_sim" ]]; then
                sim_link="$(readlink -f "${lab_dir}/_isaac_sim")"
                log_success "Linked Isaac Sim Engine: ${sim_link}"
            else
                log_warn "_isaac_sim symlink is missing or broken."
            fi
            ;;

        list-tags|tags)
            log_header "Available Official Upstream Isaac Lab Tags"
            local upstream_url="${ISAACLAB_UPSTREAM:-https://github.com/isaac-sim/IsaacLab.git}"
            log_info "Querying releases from ${upstream_url}..."
            git ls-remote --tags --refs "${upstream_url}" | awk -F/ '{print $3}' | sort -V | tail -n 25 | sed 's/^/  ● /'
            ;;

        switch)
            local target_ref="${1:-}"
            if [[ -z "$target_ref" ]]; then
                log_error "Usage: ./bin/isaac-installer lab switch <tag|branch>"
                return 1
            fi

            log_header "Switching Isaac Lab to Ref: ${target_ref}"
            local is_tag=false
            if [[ "$target_ref" == v* ]]; then is_tag=true; fi

            fetch_and_checkout_ref "${lab_dir}" "${target_ref}" "${is_tag}"
            
            # Re-index extensions in editable mode
            log_info "Re-indexing Isaac Lab extensions with active runtime..."
            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${lab_dir}'
                ./isaaclab.sh --install
            "
            log_success "Isaac Lab successfully switched to ${target_ref} and re-indexed."
            ;;

        sync)
            local rebase_flag="${1:-}"
            log_header "Syncing Isaac Lab with Upstream Releases"
            if [[ ! -d "${lab_dir}/.git" ]]; then
                log_error "Isaac Lab repository not found at ${lab_dir}."
                return 1
            fi

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${lab_dir}'
                git fetch --tags upstream
                git fetch upstream main
                if [[ '${rebase_flag}' == '--rebase' ]]; then
                    echo 'Rebasing current branch against upstream/main...'
                    git rebase upstream/main
                else
                    echo 'Merging upstream/main into current branch...'
                    git merge upstream/main
                fi
            "
            log_success "Sync complete."
            ;;

        fork)
            local target_fork="${1:-}"
            if [[ -z "$target_fork" ]]; then
                log_error "Usage: ./bin/isaac-installer lab fork <owner/repo or url>"
                return 1
            fi

            log_header "Re-wiring Isaac Lab Origin to Fork: ${target_fork}"
            local official_upstream="${ISAACLAB_UPSTREAM:-https://github.com/isaac-sim/IsaacLab.git}"
            local resolved_fork
            resolved_fork="$(ensure_github_fork "$target_fork" "$official_upstream")"

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${lab_dir}'
                git remote set-url origin '${resolved_fork}' 2>/dev/null || git remote add origin '${resolved_fork}' 2>/dev/null
                git fetch origin 2>/dev/null || true
            "
            log_success "Origin remote re-wired to ${resolved_fork}."
            ;;

        remotes)
            log_header "Isaac Lab Dual-Remote Topology Configuration"
            if [[ ! -d "${lab_dir}/.git" ]]; then
                log_error "Isaac Lab repository not found at ${lab_dir}."
                return 1
            fi

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${lab_dir}'
                echo '=== Git Remotes ==='
                git remote -v
                echo ''
                echo '=== Upstream Push Protection ==='
                push_url=\$(git config --get remote.upstream.pushurl || echo 'UNPROTECTED')
                echo \"Upstream Push URL: \${push_url}\"
            "
            ;;

        *)
            echo "Usage: ./bin/isaac-installer lab [status|list-tags|switch <ref>|sync [--rebase]|fork <owner/repo>|remotes]"
            ;;
    esac
}

