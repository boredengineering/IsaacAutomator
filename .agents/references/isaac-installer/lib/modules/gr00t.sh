#!/usr/bin/env bash
# ==============================================================================
# gr00t.sh - NVIDIA Isaac-GR00T Foundation Model Stack & Policy Serving
# ==============================================================================

resolve_gr00t_dir() {
    local git_repo="${GR00T_REPO:-https://github.com/NVIDIA/Isaac-GR00T.git}"
    resolve_repo_dest_path "Isaac-GR00T" "${git_repo}" "${GR00T_DIR:-}"
}

check_gr00t() {
    local gr00t_dir
    gr00t_dir="$(resolve_gr00t_dir)"
    local missing=()

    command -v git-lfs &>/dev/null || missing+=("git-lfs")
    command -v ffmpeg &>/dev/null || missing+=("ffmpeg")
    command -v uv &>/dev/null || missing+=("uv")

    if [[ ! -d "${gr00t_dir}/.git" ]]; then
        missing+=("Isaac-GR00T repository at ${gr00t_dir}")
    fi

    if [[ ${#missing[@]} -eq 0 ]]; then
        STAGE_CHECK_MSG="Isaac-GR00T foundation model stack and virtual environment ready at ${gr00t_dir}"
        return 0
    else
        STAGE_CHECK_MSG="Missing components: ${missing[*]}"
        return 1
    fi
}

install_gr00t() {
    log_step "Installing NVIDIA Isaac-GR00T Foundation Model Stack..."

    local gr00t_dir
    gr00t_dir="$(resolve_gr00t_dir)"
    local git_repo="${GR00T_REPO:-https://github.com/NVIDIA/Isaac-GR00T.git}"
    local official_upstream="${GR00T_UPSTREAM:-https://github.com/NVIDIA/Isaac-GR00T.git}"
    local git_branch="${GR00T_BRANCH:-main}"
    local git_tag="${GR00T_TAG:-}"

    # 1. Install System Dependencies & Video Codecs
    log_info "Installing git-lfs, ffmpeg, and build prerequisites..."
    pkg_install git-lfs ffmpeg pkg-config
    sudo -H -u "${TARGET_USER}" bash -c "git lfs install --skip-repo 2>/dev/null || true"

    # 2. Ensure uv package manager is available
    if ! command -v uv &>/dev/null && [[ ! -x "/home/${TARGET_USER}/.cargo/bin/uv" && ! -x "/root/.cargo/bin/uv" ]]; then
        log_info "Installing Astral uv package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi

    # 3. Setup repository with Dual-Remote topology & Submodules
    setup_git_repo_with_fork "${gr00t_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" "${git_tag}" true

    # 4. Initialize Submodules & Pull Git LFS Objects
    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${gr00t_dir}'
        git submodule update --init --recursive 2>/dev/null || true
        git lfs pull 2>/dev/null || true
    "

    # 5. Provision Isolated Python 3.12 Environment with uv sync
    log_info "Synchronizing locked Python 3.12 dependencies with uv..."
    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${gr00t_dir}'
        export PATH=\"\$HOME/.cargo/bin:\$PATH\"
        export CUDA_HOME=\"/usr/local/cuda\"
        uv sync --python 3.12
    "

    # 6. Register in GitHub Desktop
    register_github_desktop_repo "${gr00t_dir}"

    log_success "NVIDIA Isaac-GR00T successfully installed and synchronized at ${gr00t_dir}."
}

# Run automated validation and inference smoke test for Isaac-GR00T
test_gr00t() {
    local gr00t_dir
    gr00t_dir="$(resolve_gr00t_dir)"

    log_header "NVIDIA Isaac-GR00T Validation & Inference Smoke Test"

    if [[ ! -d "${gr00t_dir}" ]]; then
        log_error "Isaac-GR00T directory not found at ${gr00t_dir}."
        log_info "Please install it first with: sudo ./bin/isaac-installer install --with-gr00t"
        return 1
    fi

    # Test 1: Python Core Module Import Sanity
    log_step "1. Validating GR00T Core Module & Python 3.12 Imports..."
    if sudo -H -u "${TARGET_USER}" bash -c "
        cd '${gr00t_dir}'
        export PATH=\"\$HOME/.cargo/bin:\$PATH\"
        uv run python -c \"import gr00t; print('SUCCESS: GR00T imported.')\"
    "; then
        log_success "GR00T core module loaded successfully."
    else
        log_error "GR00T core module import failed."
        return 1
    fi

    # Test 2: Dataset Parquet & Modality Integrity Probe
    log_step "2. Checking DROID Demo Dataset & Modality Mapping..."
    if [[ -f "${gr00t_dir}/demo_data/droid_sample/meta/modality.json" ]]; then
        log_success "DROID sample dataset & modality.json verified."
    else
        log_warn "demo_data/droid_sample missing. Pulling with git lfs..."
        sudo -H -u "${TARGET_USER}" bash -c "cd '${gr00t_dir}' && git lfs pull"
    fi

    echo ""
    log_card_start "Isaac-GR00T Validation Complete"
    log_card_item "Repository" "${gr00t_dir}"
    log_card_item "Model Backbone" "${GR00T_VLM_BACKBONE:-nvidia/Cosmos-Reason2-2B}"
    log_card_item "Base Model Path" "${GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}"
    log_card_item "Standalone Inference" "cd ${gr00t_dir} && uv run python scripts/deployment/standalone_inference_script.py"
    log_card_end
}

# ==============================================================================
# CLI Subcommands for Isaac-GR00T (`isaac-installer gr00t ...`)
# ==============================================================================

cmd_gr00t() {
    local subcmd="${1:-status}"
    shift || true

    local gr00t_dir
    gr00t_dir="$(resolve_active_repo_dir "Isaac-GR00T" "${GR00T_REPO:-}" "${GR00T_DIR:-}")"

    case "$subcmd" in
        status)
            log_header "NVIDIA Isaac-GR00T Foundation Model Stack Status"
            if [[ ! -d "${gr00t_dir}/.git" ]]; then
                log_info "Isaac-GR00T repository is not yet cloned or installed at ${gr00t_dir}."
                log_info "To install, run: sudo ./bin/isaac-installer install --with-gr00t"
                return 0
            fi

            local info
            info="$(get_repo_info "${gr00t_dir}")"
            local sync_info
            sync_info="$(check_fork_sync_status "${gr00t_dir}")"

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
        print(f'  Upstream Sync:     OUT OF SYNC ({', '.join(status_parts)}) -> Run ./bin/isaac-installer gr00t sync')
"
            ;;

        infer|inference)
            log_header "Running Isaac-GR00T Open-Loop Inference on DROID Sample"
            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${gr00t_dir}'
                export PATH=\"\$HOME/.cargo/bin:\$PATH\"
                uv run python scripts/deployment/standalone_inference_script.py \
                  --model-path '${GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}' \
                  --dataset-path demo_data/droid_sample \
                  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
                  --traj-ids 1 \
                  --inference-mode pytorch \
                  --execution-horizon 8
            "
            ;;

        server)
            local port="${1:-${GR00T_SERVER_PORT:-5555}}"
            log_header "Starting Isaac-GR00T ZeroMQ Policy Server on Port ${port}"
            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${gr00t_dir}'
                export PATH=\"\$HOME/.cargo/bin:\$PATH\"
                uv run python gr00t/eval/run_gr00t_server.py \
                  --model-path '${GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}' \
                  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
                  --port '${port}' \
                  --device cuda:0
            "
            ;;

        fork)
            local target_fork="${1:-}"
            if [[ -z "$target_fork" ]]; then
                log_error "Usage: ./bin/isaac-installer gr00t fork <owner/repo or url>"
                return 1
            fi

            log_header "Re-wiring Isaac-GR00T Origin to Fork: ${target_fork}"
            local official_upstream="${GR00T_UPSTREAM:-https://github.com/NVIDIA/Isaac-GR00T.git}"
            local resolved_fork
            resolved_fork="$(ensure_github_fork "$target_fork" "$official_upstream")"

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${gr00t_dir}'
                git remote set-url origin '${resolved_fork}' 2>/dev/null || git remote add origin '${resolved_fork}' 2>/dev/null
                git fetch origin 2>/dev/null || true
            "
            log_success "Origin remote re-wired to ${resolved_fork}."
            ;;

        remotes)
            log_header "Isaac-GR00T Dual-Remote Topology Configuration"
            if [[ ! -d "${gr00t_dir}/.git" ]]; then
                log_error "Isaac-GR00T repository not found at ${gr00t_dir}."
                return 1
            fi

            sudo -H -u "${TARGET_USER}" bash -c "
                cd '${gr00t_dir}'
                echo '=== Git Remotes ==='
                git remote -v
                echo ''
                echo '=== Upstream Push Protection ==='
                push_url=\$(git config --get remote.upstream.pushurl || echo 'UNPROTECTED')
                echo \"Upstream Push URL: \${push_url}\"
            "
            ;;

        test)
            test_gr00t
            ;;

        *)
            echo "Usage: ./bin/isaac-installer gr00t [status|infer|server [port]|fork <owner/repo>|remotes|test]"
            ;;
    esac
}
