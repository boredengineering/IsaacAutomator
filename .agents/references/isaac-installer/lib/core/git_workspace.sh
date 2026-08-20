#!/usr/bin/env bash
# ==============================================================================
# git_workspace.sh - Smart Repo Discovery, Fork/Upstream Remote Topology & GitHub Desktop Integration
# ==============================================================================

# Resolves the default workspace root directory
resolve_default_workspace_dir() {
    detect_target_user
    if [[ -n "${WORKSPACE_DIR:-}" ]]; then
        mkdir -p "${WORKSPACE_DIR}"
        echo "${WORKSPACE_DIR}"
        return 0
    fi

    # Check for ~/Documents/GitHub
    local gh_docs="${TARGET_HOME}/Documents/GitHub"
    if [[ -d "${gh_docs}" || -x "$(command -v github-desktop 2>/dev/null)" ]]; then
        mkdir -p "${gh_docs}"
        chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/Documents" 2>/dev/null || true
        echo "${gh_docs}"
        return 0
    fi

    # Fallback to ~/workspace or ~/
    if [[ -d "${TARGET_HOME}/workspace" ]]; then
        echo "${TARGET_HOME}/workspace"
    else
        echo "${TARGET_HOME}"
    fi
}

# Normalize a GitHub repo string (e.g. 'BoredEngineer/IsaacLab' -> 'https://github.com/BoredEngineer/IsaacLab.git')
normalize_git_url() {
    local input="$1"
    if [[ "$input" =~ ^https?:// || "$input" =~ ^git@ ]]; then
        echo "$input"
    elif [[ "$input" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
        echo "https://github.com/${input}.git"
    else
        echo "$input"
    fi
}

# Search for existing repo clones across developer directory tree
find_existing_repo() {
    local repo_name="$1"
    detect_target_user

    local search_paths=(
        "${WORKSPACE_DIR:-}"
        "${TARGET_HOME}/Documents/GitHub"
        "${TARGET_HOME}/Documents/GitHub/*"
        "${TARGET_HOME}/workspace"
        "${TARGET_HOME}/projects"
        "${TARGET_HOME}/dev"
        "${TARGET_HOME}"
    )

    for base_pattern in "${search_paths[@]}"; do
        if [[ -z "$base_pattern" ]]; then continue; fi
        for base in $base_pattern; do
            if [[ -d "${base}/${repo_name}/.git" ]]; then
                echo "${base}/${repo_name}"
                return 0
            fi
        done
    done

    return 1
}

# Register a cloned or discovered repository with GitHub Desktop
register_github_desktop_repo() {
    local repo_path="$1"
    detect_target_user

    if command -v github-desktop &>/dev/null && [[ -d "${repo_path}/.git" ]]; then
        log_info "Registering ${repo_path} with GitHub Desktop..."
        sudo -H -u "${TARGET_USER}" github-desktop --add "${repo_path}" 2>/dev/null || true
    fi
}

# Clones or updates a repository with dual-remote (origin = fork, upstream = official)
setup_git_repo_with_fork() {
    local dest_dir="$1"
    local fork_or_main_url="$2"
    local official_upstream_url="$3"
    local branch="${4:-main}"
    local recurse_submodules="${5:-false}"

    detect_target_user
    mkdir -p "$(dirname "$dest_dir")"
    chown "${TARGET_USER}:${TARGET_USER}" "$(dirname "$dest_dir")"

    fork_or_main_url="$(normalize_git_url "$fork_or_main_url")"
    official_upstream_url="$(normalize_git_url "$official_upstream_url")"

    # Fix SSH vs HTTPS rewrite for submodules if needed
    sudo -H -u "${TARGET_USER}" git config --global url."https://github.com/".insteadOf git@github.com: 2>/dev/null || true

    if [[ ! -d "${dest_dir}/.git" ]]; then
        log_info "Cloning ${fork_or_main_url} (${branch}) -> ${dest_dir}..."
        
        local clone_cmd=(git clone --depth 1 -b "${branch}")
        if [[ "$recurse_submodules" == true ]]; then
            clone_cmd+=(--recurse-submodules --shallow-submodules)
        fi
        clone_cmd+=("${fork_or_main_url}" "${dest_dir}")

        sudo -H -u "${TARGET_USER}" "${clone_cmd[@]}"
        chown -R "${TARGET_USER}:${TARGET_USER}" "${dest_dir}"
    else
        log_info "Existing repository found at ${dest_dir}."
    fi

    # Configure Remotes (origin = user fork, upstream = official)
    local current_origin
    current_origin="$(sudo -H -u "${TARGET_USER}" git -C "${dest_dir}" remote get-url origin 2>/dev/null || echo "")"

    if [[ -n "$official_upstream_url" && "$current_origin" != "$official_upstream_url" ]]; then
        if ! sudo -H -u "${TARGET_USER}" git -C "${dest_dir}" remote | grep -q "^upstream$"; then
            log_info "Adding official upstream remote: ${official_upstream_url}..."
            sudo -H -u "${TARGET_USER}" git -C "${dest_dir}" remote add upstream "${official_upstream_url}" 2>/dev/null || true
            sudo -H -u "${TARGET_USER}" git -C "${dest_dir}" fetch upstream 2>/dev/null || true
            log_success "Configured dual-remote topology (origin: $(basename "$fork_or_main_url") | upstream: $(basename "$official_upstream_url"))."
        fi
    fi

    # Register in GitHub Desktop
    register_github_desktop_repo "${dest_dir}"
}
