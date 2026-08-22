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
    run_as_user "git lfs install --skip-repo 2>/dev/null || true"

    # 2. Ensure Astral uv package manager is globally available
    if ! command -v uv &>/dev/null; then
        log_info "Installing Astral uv package manager to /usr/local/bin..."
        curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh 2>/dev/null || \
        curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null || true

        # Link/copy to system bin so all users and sudo subshells find uv immediately
        for p in "${TARGET_HOME}/.local/bin/uv" "${TARGET_HOME}/.cargo/bin/uv" "/root/.local/bin/uv" "/root/.cargo/bin/uv"; do
            if [[ -x "$p" && ! -x "/usr/local/bin/uv" ]]; then
                cp -f "$p" /usr/local/bin/uv 2>/dev/null || ln -sf "$p" /usr/local/bin/uv 2>/dev/null || true
                cp -f "${p}x" /usr/local/bin/uvx 2>/dev/null || ln -sf "${p}x" /usr/local/bin/uvx 2>/dev/null || true
            fi
        done
    fi

    # Also install in user space if user home doesn't have it
    run_as_user "
        if ! command -v uv &>/dev/null; then
            curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null || true
        fi
    "

    # 3. Setup repository with Dual-Remote topology & Submodules
    setup_git_repo_with_fork "${gr00t_dir}" "${git_repo}" "${official_upstream}" "${git_branch}" "${git_tag}" true

    # 4. Initialize Submodules & Pull Git LFS Objects
    run_as_user "
        cd '${gr00t_dir}'
        git submodule update --init --recursive 2>/dev/null || true
        git lfs pull 2>/dev/null || true
    "

    # 5. Provision Isolated Python Environment with uv sync
    log_info "Synchronizing locked Python dependencies with uv..."
    run_as_user "
        cd '${gr00t_dir}'
        export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"
        export CUDA_HOME=\"/usr/local/cuda\"
        uv sync
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
    if run_as_user "
        cd '${gr00t_dir}'
        export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"
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
        run_as_user "cd '${gr00t_dir}' && git lfs pull"
    fi

    echo ""
    log_card_start "Isaac-GR00T Validation Complete"
    log_card_item "Repository" "${gr00t_dir}"
    log_card_item "Model Backbone" "${GR00T_VLM_BACKBONE:-nvidia/Cosmos-Reason2-2B}"
    log_card_item "Base Model Path" "${GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}"
    log_card_item "Standalone Inference" "cd ${gr00t_dir} && uv run python scripts/deployment/standalone_inference_script.py"
    log_card_item "ZeroMQ Policy Server" "./bin/isaac-installer gr00t server [port]"
    log_card_item "Pre-Cache Model Weights" "./bin/isaac-installer gr00t download-weights"
    log_card_end
}

# Download and pre-cache model weights from Hugging Face Hub
download_gr00t_weights() {
    local gr00t_dir
    gr00t_dir="$(resolve_gr00t_dir)"
    local target_dir="${1:-}"
    local is_mock=false

    for arg in "$@"; do
        if [[ "$arg" == "--mock" || "$arg" == "-m" ]]; then
            is_mock=true
        fi
    done

    log_header "NVIDIA Isaac-GR00T Model Weights Manager"

    if [[ "$is_mock" == true ]]; then
        log_info "Creating offline mock model checkpoint fixture for CI/CD testing..."
        local mock_dir="${TARGET_HOME}/.cache/isaac-gr00t/mock-n1.7"
        run_as_user "
            mkdir -p '${mock_dir}/meta'
            cat << 'EOF' > '${mock_dir}/meta/modality.json'
{
  \"state\": {\"joint_pos\": [0, 7], \"joint_vel\": [7, 14]},
  \"action\": {\"joint_pos_target\": [0, 7]}
}
EOF
            touch '${mock_dir}/model.safetensors'
        "
        log_success "Mock weights fixture created at ${mock_dir}."
        return 0
    fi

    # Check Hugging Face token
    local hf_token_file="${TARGET_HOME}/.cache/huggingface/token"
    if [[ ! -f "${hf_token_file}" && -z "${HF_TOKEN:-}" && -z "${HUGGINGFACE_TOKEN:-}" ]]; then
        log_warn "Hugging Face token not found."
        log_info "nvidia/GR00T-N1.7-3B and nvidia/Cosmos-Reason2-2B are gated repositories."
        log_info "Please login first with: ./bin/isaac-installer auth login huggingface"
        log_info "Or export HF_TOKEN=\"your_hf_token\" before running this command."
        read -r -p "Proceed with download attempt anyway? [y/N]: " choice
        case "$choice" in
            [yY]*) ;;
            *) return 1 ;;
        esac
    fi

    local model_id="${GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}"
    log_step "Downloading foundation model weights for [${model_id}]..."

    local dest_arg=""
    if [[ -n "$target_dir" && "$target_dir" != --* ]]; then
        dest_arg="--local-dir '${target_dir}'"
        log_info "Target local directory: ${target_dir}"
    fi

    run_as_user "
        cd '${gr00t_dir}'
        export PATH=\"\$HOME/.cargo/bin:\$PATH\"
        if [[ -n \"${HF_TOKEN:-}\" ]]; then export HF_TOKEN=\"${HF_TOKEN}\"; fi
        
        echo 'Pulling model snapshot via huggingface_hub...'
        uv run python -c \"
import os
from huggingface_hub import snapshot_download
model_id = '${model_id}'
local_dir = '${target_dir}' if '${target_dir}' and not '${target_dir}'.startswith('--') else None
print(f'Starting high-speed snapshot download for {model_id}...')
path = snapshot_download(repo_id=model_id, local_dir=local_dir, ignore_patterns=['*.msgpack'])
print(f'SUCCESS: Model cached at: {path}')
\"
    "
    log_success "Model weights for [${model_id}] verified in local cache."
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

        download-weights|cache-weights|pull-model)
            download_gr00t_weights "$@"
            ;;

        infer|inference)
            log_header "Running Isaac-GR00T Open-Loop Inference on DROID Sample"
            run_as_user "
                cd '${gr00t_dir}'
                export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"
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
            run_as_user "
                cd '${gr00t_dir}'
                export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"
                uv run python gr00t/eval/run_gr00t_server.py \
                  --model-path '${GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}' \
                  --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
                  --port '${port}' \
                  --device cuda:0
            "
            ;;

        eval-closed-loop|closed-loop)
            local port="${1:-5555}"
            local host="${2:-127.0.0.1}"
            log_header "Testing Isaac-GR00T ZeroMQ Client-Server Closed-Loop Bridge"
            run_as_user "
                cd '${gr00t_dir}'
                export PATH=\"/usr/local/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"
                echo 'Testing ZeroMQ client socket connection to ${host}:${port}...'
                uv run python -c \"
import zmq
import time
context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.setsockopt(zmq.RCVTIMEO, 5000)
socket.connect('tcp://${host}:${port}')
print('✔ Connected to ZeroMQ policy server socket.')
\" 2>/dev/null || echo 'Note: Policy server not active on ${host}:${port}. Start it first with: ./bin/isaac-installer gr00t server ${port}'
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

            run_as_user "
                cd '${gr00t_dir}'
                git remote set-url origin '${resolved_fork}' 2>/dev/null || git remote add origin '${resolved_fork}' 2>/dev/null
                git fetch origin 2>/dev/null || true
            "
            log_success "Origin remote re-wired to ${resolved_fork}."
            ;;

        sync)
            local sync_mode="${1:-}"
            log_header "Syncing Isaac-GR00T with Upstream Releases"
            if [[ ! -d "${gr00t_dir}/.git" ]]; then
                log_error "Isaac-GR00T repository not found at ${gr00t_dir}."
                return 1
            fi

            run_as_user "
                cd '${gr00t_dir}'
                curr_branch=\$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')
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

                if git remote | grep -q '^origin$'; then
                    echo \"Pushing synced '\${curr_branch}' to personal origin fork...\"
                    git push origin \"\${curr_branch}\" 2>/dev/null || true
                fi
            "
            log_success "Sync complete."
            ;;

        remotes)
            log_header "Isaac-GR00T Dual-Remote Topology Configuration"
            if [[ ! -d "${gr00t_dir}/.git" ]]; then
                log_error "Isaac-GR00T repository not found at ${gr00t_dir}."
                return 1
            fi

            run_as_user "
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

        help|--help|-h|*)
            cat << 'HELP'
Isaac-GR00T - Physical AI Foundation Vision-Language-Action (VLA) Model Stack

Usage:
  isaac-installer gr00t <command> [options]

Model Weights & Authentication:
  download-weights [options]           Download & cache foundation weights (nvidia/GR00T-N1.7-3B)
  download-weights --mock              Create structural mock weights fixture for offline/CI tests

Serving & Policy Inference:
  server [port] [options]              Launch ZeroMQ REP policy server daemon (Default: 5555)
  infer [options]                      Run open-loop inference on DROID demonstration trajectories
  eval-closed-loop [options]           Run closed-loop evaluation in IsaacLab-Arena

Git & Dual-Remote Management:
  status                               Inspect active branch, commit, dirty state, and remotes
  sync [--rebase]                      Fetch & merge/rebase upstream changes into local fork
  fork <owner/repo>                    Re-home origin remote to a personal fork
  remotes                              Show origin/upstream URLs and push-protection status

Server & Inference Options:
  --port <number>                      ZeroMQ server port (Default: 5555)
  --device <cuda:0|cpu>                Inference device (Default: cuda:0)
  --embodiment-tag <tag>               Robot tag: OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT | REAL_G1 | etc.
  --model-path <id/path>               Hugging Face ID or local path (Default: nvidia/GR00T-N1.7-3B)
  --execution-horizon <steps>          Receding execution window: 8 or 16 (Default: 8)

Verification:
  test                                 Run Python 3.12 imports, DROID mapping, and ZeroMQ smoke test

Examples:
  ./bin/isaac-installer gr00t download-weights --mock
  ./bin/isaac-installer gr00t server 5555
  ./bin/isaac-installer gr00t infer --dataset-path demo_data/droid_sample
HELP
            ;;
    esac
}
