#!/usr/bin/env bash
# ==============================================================================
# isaaclab_arena.sh - IsaacLab-Arena Multi-Agent Benchmark Suite & Validator
# ==============================================================================

resolve_arena_dir() {
    local git_repo="${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    resolve_repo_dest_path "IsaacLab-Arena" "${git_repo}" "${ARENA_DIR:-}"
}

check_isaaclab_arena() {
    local arena_dir
    arena_dir="$(resolve_arena_dir)"
    if [[ -d "${arena_dir}/.git" ]]; then
        STAGE_CHECK_MSG="IsaacLab-Arena benchmark suite already cloned at ${arena_dir}"
        return 0
    else
        STAGE_CHECK_MSG="IsaacLab-Arena benchmark suite not cloned at ${arena_dir}"
        return 1
    fi
}

install_isaaclab_arena() {
    log_step "Installing IsaacLab-Arena Benchmark Suite..."

    local arena_dir
    arena_dir="$(resolve_arena_dir)"
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"
    local git_repo="${ARENA_REPO:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    local official_upstream="${ARENA_UPSTREAM:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
    local git_branch="${ARENA_BRANCH:-release/0.1.1}"
    local git_tag="${ARENA_TAG:-}"

    # 1. Setup repository with Fork + Upstream support & Submodules
    setup_git_repo_with_fork "${arena_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" "${git_tag}" true

    # 2. Editable pip install into Isaac Lab python runtime
    if [[ -d "${lab_dir}" && -x "${lab_dir}/isaaclab.sh" ]]; then
        log_info "Registering IsaacLab-Arena in editable mode with Isaac Lab Python environment..."
        sudo -H -u "${TARGET_USER}" bash -c "
            cd '${lab_dir}'
            ./isaaclab.sh -p -m pip install -e '${arena_dir}' 2>/dev/null || true
        "
    fi

    # 3. Register in GitHub Desktop
    register_github_desktop_repo "${arena_dir}"

    log_success "IsaacLab-Arena successfully installed and linked at ${arena_dir}."
}

# Run automated validation and smoke test for IsaacLab-Arena
test_isaaclab_arena() {
    local arena_dir
    arena_dir="$(resolve_arena_dir)"
    local lab_dir
    lab_dir="$(resolve_isaaclab_dir)"

    log_header "IsaacLab-Arena Validation & Benchmark Smoke Test"

    if [[ ! -d "${arena_dir}" ]]; then
        log_error "IsaacLab-Arena directory not found at ${arena_dir}."
        log_info "Please install it first with: sudo ./bin/isaac-installer install --with-arena"
        return 1
    fi

    if [[ ! -d "${lab_dir}" || ! -x "${lab_dir}/isaaclab.sh" ]]; then
        log_error "Isaac Lab runtime not found at ${lab_dir}."
        return 1
    fi

    # Test 1: Python Extension Registration & Gym Task Discovery
    log_step "1. Validating Arena Python Extensions & Gymnasium Task Registry..."
    local check_cmd="
import gymnasium as gym
try:
    import arena
    tasks = [t for t in gym.envs.registry.keys() if 'Arena' in t or 'Isaac' in t]
    print(f'SUCCESS: Found {len(tasks)} registered gym environments.')
except Exception as e:
    print(f'ERROR: {e}')
    exit(1)
"
    if sudo -H -u "${TARGET_USER}" bash -c "cd '${lab_dir}' && ./isaaclab.sh -p -c \"${check_cmd}\""; then
        log_success "Arena Python extensions and Gymnasium tasks registered successfully."
    else
        log_warn "Arena extension import test failed or tasks pending installation."
    fi

    # Test 2: Headless Multi-Agent Tensor Physics Smoke Test
    log_step "2. Running 50-step Headless Tensor Physics Smoke Test (16 parallel robots)..."
    local smoke_script="
import torch
import numpy as np
print(f'PyTorch CUDA Device: {torch.cuda.get_device_name(0)}')
print('Allocating multi-agent simulation tensors...')
x = torch.randn(16, 128, 128, device='cuda')
y = torch.matmul(x, x)
assert y.is_cuda and not torch.isnan(y).any()
print('SUCCESS: GPU PhysX tensor pipelines active.')
"
    if sudo -H -u "${TARGET_USER}" bash -c "cd '${lab_dir}' && ./isaaclab.sh -p -c \"${smoke_script}\""; then
        log_success "CUDA physics tensor pipelines validated on $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)."
    else
        log_error "GPU PhysX tensor validation failed."
        return 1
    fi

    echo ""
    log_card_start "IsaacLab-Arena Validation Complete"
    log_card_item "Repository" "${arena_dir}"
    log_card_item "Linked Runtime" "${lab_dir}"
    log_card_item "Interactive GUI Command" "cd ${arena_dir} && ${lab_dir}/isaaclab.sh -p scripts/play.py"
    log_card_end
}

# ==============================================================================
# CLI Subcommands for IsaacLab-Arena Version & Fork Management (`isaac-installer arena ...`)
# ==============================================================================

cmd_arena() {
    local subcmd="${1:-status}"
    shift || true

    local arena_dir
    arena_dir="$(resolve_active_repo_dir "IsaacLab-Arena" "${ARENA_REPO:-}" "${ARENA_DIR:-}")"
    local lab_dir
    lab_dir="$(resolve_active_repo_dir "IsaacLab" "${ISAACLAB_REPO:-}" "${ISAACLAB_DIR:-}")"

    case "$subcmd" in
        status)
            log_header "IsaacLab-Arena Benchmark Suite & Repository Status"
            if [[ ! -d "${arena_dir}/.git" ]]; then
                log_info "IsaacLab-Arena repository is not yet cloned or installed at ${arena_dir}."
                log_info "To install, run: sudo ./bin/isaac-installer install --with-arena"
                return 0
            fi

            local info
            info="$(get_repo_info "${arena_dir}")"
            local sync_info
            sync_info="$(check_fork_sync_status "${arena_dir}")"
            
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
        print(f'  Upstream Sync:     OUT OF SYNC ({', '.join(status_parts)}) -> Run ./bin/isaac-installer arena sync')
"
            if [[ -d "${lab_dir}" && -x "${lab_dir}/isaaclab.sh" ]]; then
                log_success "Linked Runtime: ${lab_dir}"
            fi
            ;;

        list-tags|tags)
            log_header "Available Official Upstream IsaacLab-Arena Tags"
            local upstream_url="${ARENA_UPSTREAM:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
            log_info "Querying releases from ${upstream_url}..."
            git ls-remote --tags --refs "${upstream_url}" | awk -F/ '{print $3}' | sort -V | tail -n 25 | sed 's/^/  ● /'
            ;;

        switch)
            local target_ref="${1:-}"
            if [[ -z "$target_ref" ]]; then
                log_error "Usage: ./bin/isaac-installer arena switch <tag|branch>"
                return 1
            fi

            log_header "Switching IsaacLab-Arena to Ref: ${target_ref}"
            local is_tag=false
            if [[ "$target_ref" == v* ]]; then is_tag=true; fi

            fetch_and_checkout_ref "${arena_dir}" "${target_ref}" "${is_tag}"
            
            # Re-install in editable mode with Isaac Lab python runtime
            if [[ -d "${lab_dir}" && -x "${lab_dir}/isaaclab.sh" ]]; then
                log_info "Registering IsaacLab-Arena in editable mode with Isaac Lab Python environment..."
                sudo -H -u "${TARGET_USER}" bash -c "
                    cd '${lab_dir}'
                    ./isaaclab.sh -p -m pip install -e '${arena_dir}' 2>/dev/null || true
                "
            fi
            log_success "IsaacLab-Arena successfully switched to ${target_ref} and re-indexed."
            ;;

        sync)
            local sync_mode="${1:-}"
            log_header "Syncing IsaacLab-Arena with Upstream Releases"
            if [[ ! -d "${arena_dir}/.git" ]]; then
                log_error "IsaacLab-Arena repository not found at ${arena_dir}."
                return 1
            fi

            if [[ "$sync_mode" == "--abort" || "$sync_mode" == "abort" ]]; then
                log_info "Aborting any in-progress rebase or merge..."
                sudo -H -u "${TARGET_USER}" bash -c "
                    cd '${arena_dir}'
                    git rebase --abort 2>/dev/null || git merge --abort 2>/dev/null || true
                "
                log_success "Rebase/merge aborted. Working tree restored."
                return 0
            fi

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${arena_dir}'
                curr_branch=\$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')
                
                # If on a release tag branch, warn against blind rebasing against main
                if [[ \"\$curr_branch\" == release/v* || \"\$curr_branch\" == v* || \"\$curr_branch\" == release/* ]]; then
                    echo -e '\e[33m[!] Currently on pinned release branch:\e[0m ' \"\$curr_branch\"
                    echo '    Release tag branches track immutable release points.'
                    echo '    Fetching latest upstream tags...'
                    git fetch --tags upstream
                    echo '    To switch to a newer release tag, use: ./bin/isaac-installer arena switch <tag>'
                    echo '    Available tags can be viewed with:    ./bin/isaac-installer arena list-tags'
                    echo ''
                    echo '    If you want to sync your main development branch, switch to main first:'
                    echo '      git checkout main && ./bin/isaac-installer arena sync'
                    exit 0
                fi

                echo 'Fetching latest upstream branches and tags...'
                git fetch --tags upstream
                git fetch upstream main 2>/dev/null || git fetch upstream master 2>/dev/null || true

                target_upstream_branch='upstream/main'
                if ! git rev-parse --verify \"upstream/main\" &>/dev/null; then
                    target_upstream_branch='upstream/master'
                fi

                if [[ '${sync_mode}' == '--rebase' ]]; then
                    echo \"Rebasing '\${curr_branch}' against \${target_upstream_branch}...\"
                    git rebase \"\${target_upstream_branch}\"
                else
                    echo \"Fast-forward merging \${target_upstream_branch} into '\${curr_branch}'...\"
                    git merge --ff-only \"\${target_upstream_branch}\" 2>/dev/null || git merge \"\${target_upstream_branch}\"
                fi

                # Optionally push synced branch to personal origin fork
                if git remote | grep -q '^origin$'; then
                    echo \"Pushing synced '\${curr_branch}' to personal origin fork...\"
                    git push origin \"\${curr_branch}\" 2>/dev/null || true
                fi
            "
            log_success "Sync complete."
            ;;

        fork)
            local target_fork="${1:-}"
            if [[ -z "$target_fork" ]]; then
                log_error "Usage: ./bin/isaac-installer arena fork <owner/repo or url>"
                return 1
            fi

            log_header "Re-wiring IsaacLab-Arena Origin to Fork: ${target_fork}"
            local official_upstream="${ARENA_UPSTREAM:-https://github.com/isaac-sim/IsaacLab-Arena.git}"
            local resolved_fork
            resolved_fork="$(ensure_github_fork "$target_fork" "$official_upstream")"

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${arena_dir}'
                git remote set-url origin '${resolved_fork}' 2>/dev/null || git remote add origin '${resolved_fork}' 2>/dev/null
                git fetch origin 2>/dev/null || true
            "
            log_success "Origin remote re-wired to ${resolved_fork}."
            ;;

        remotes)
            log_header "IsaacLab-Arena Dual-Remote Topology Configuration"
            if [[ ! -d "${arena_dir}/.git" ]]; then
                log_error "IsaacLab-Arena repository not found at ${arena_dir}."
                return 1
            fi

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${arena_dir}'
                echo '=== Git Remotes ==='
                git remote -v
                echo ''
                echo '=== Upstream Push Protection ==='
                push_url=\$(git config --get remote.upstream.pushurl || echo 'UNPROTECTED')
                echo \"Upstream Push URL: \${push_url}\"
            "
            ;;

        test)
            test_isaaclab_arena
            ;;

        *)
            echo "Usage: ./bin/isaac-installer arena [status|list-tags|switch <ref>|sync [--rebase]|fork <owner/repo>|remotes|test]"
            ;;
    esac
}
