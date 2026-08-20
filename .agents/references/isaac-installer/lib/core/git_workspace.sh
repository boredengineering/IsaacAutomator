#!/usr/bin/env bash
# ==============================================================================
# git_workspace.sh - Workspace Hierarchy, Dual-Remote Fork Topology & GitHub Desktop Integration
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

# Extract owner from URL or slug (e.g. 'BoredEngineer/IsaacLab' -> 'BoredEngineer')
extract_repo_owner() {
    local input="$1"
    if [[ "$input" =~ ^https?://github\.com/([^/]+)/ ]]; then
        echo "${BASH_REMATCH[1]}"
    elif [[ "$input" =~ ^git@github\.com:([^/]+)/ ]]; then
        echo "${BASH_REMATCH[1]}"
    elif [[ "$input" =~ ^([A-Za-z0-9_.-]+)/[A-Za-z0-9_.-]+$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo ""
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

# Resolves the exact destination folder for a repository taking layout into account
resolve_repo_dest_path() {
    local repo_name="$1"        # e.g. "IsaacLab"
    local repo_slug="${2:-}"    # e.g. "BoredEngineer/IsaacLab" or "https://..."
    local explicit_path="${3:-}" # Optional explicit path override

    detect_target_user

    # 1. If explicit path is provided, expand and return
    if [[ -n "$explicit_path" ]]; then
        expand_tilde_path "$explicit_path"
        return 0
    fi

    # 2. Check if an existing clone already exists anywhere on disk
    local existing
    if existing="$(find_existing_repo "$repo_name")"; then
        echo "$existing"
        return 0
    fi

    # 3. Base workspace root (e.g. /home/tarfy/Documents/GitHub)
    local ws_root
    ws_root="$(resolve_default_workspace_dir)"

    # 4. Determine layout strategy ("auto" | "org" | "flat")
    local layout="${WORKSPACE_LAYOUT:-${CFG_WORKSPACE_LAYOUT:-auto}}"
    local owner
    owner="$(extract_repo_owner "$repo_slug")"

    if [[ -z "$owner" ]]; then
        owner="${WORKSPACE_DEFAULT_OWNER:-${CFG_WORKSPACE_DEFAULT_OWNER:-}}"
    fi
    if [[ -z "$owner" ]]; then
        owner="$(sudo -H -u "${TARGET_USER}" gh api user -q .login 2>/dev/null || sudo -H -u "${TARGET_USER}" git config --get user.name 2>/dev/null || echo "")"
    fi

    case "$layout" in
        org)
            if [[ -n "$owner" ]]; then
                echo "${ws_root}/${owner}/${repo_name}"
                return 0
            fi
            ;;
        flat)
            echo "${ws_root}/${repo_name}"
            return 0
            ;;
        auto|*)
            # If ~/Documents/GitHub/<Owner> already exists on disk, adopt that folder structure!
            if [[ -n "$owner" && -d "${ws_root}/${owner}" ]]; then
                echo "${ws_root}/${owner}/${repo_name}"
                return 0
            fi
            # If owner is known, default to organized structure
            if [[ -n "$owner" ]]; then
                echo "${ws_root}/${owner}/${repo_name}"
                return 0
            fi
            ;;
    esac

    # Fallback to flat
    echo "${ws_root}/${repo_name}"
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

# Get detailed metadata for a git repository
get_repo_info() {
    local repo_path="$1"
    detect_target_user

    if [[ ! -d "${repo_path}/.git" ]]; then
        echo "{\"exists\": false}"
        return 1
    fi

    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${repo_path}'
        branch=\$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'HEAD')
        tag=\$(git describe --tags --exact-match 2>/dev/null || echo '')
        commit=\$(git rev-parse HEAD 2>/dev/null || echo '')
        origin=\$(git remote get-url origin 2>/dev/null || echo '')
        upstream=\$(git remote get-url upstream 2>/dev/null || echo '')
        dirty=false
        if [[ -n \$(git status --porcelain 2>/dev/null) ]]; then dirty=true; fi

        python3 -c \"
import json
print(json.dumps({
    'exists': True,
    'path': '${repo_path}',
    'branch': '\${branch}',
    'tag': '\${tag}',
    'commit': '\${commit}',
    'origin': '\${origin}',
    'upstream': '\${upstream}',
    'dirty': \${dirty}
}))
\"
    " 2>/dev/null || echo "{\"exists\": false}"
}

# Safely switches or checks out a desired git ref (tag, branch, commit)
fetch_and_checkout_ref() {
    local repo_path="$1"
    local desired_ref="$2"
    local is_tag="${3:-false}"
    detect_target_user

    if [[ ! -d "${repo_path}/.git" || -z "$desired_ref" ]]; then
        return 0
    fi

    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${repo_path}'
        # Fetch tags and refs from both origin and upstream
        git fetch --tags origin 2>/dev/null || true
        git fetch --tags upstream 2>/dev/null || true

        curr_head=\$(git rev-parse HEAD 2>/dev/null || echo '')
        target_head=\$(git rev-parse '${desired_ref}^{commit}' 2>/dev/null || git rev-parse '${desired_ref}' 2>/dev/null || echo '')

        if [[ -n \"\$target_head\" && \"\$curr_head\" == \"\$target_head\" ]]; then
            exit 0
        fi

        # If ref not found locally, fetch refspec from upstream or unshallow
        if [[ -z \"\$target_head\" ]]; then
            git fetch upstream '${desired_ref}' 2>/dev/null || git fetch --unshallow upstream 2>/dev/null || true
        fi

        # Check for dirty work
        if [[ -n \$(git status --porcelain 2>/dev/null) ]]; then
            echo 'DIRTY_WORK_SAVED'
            git stash save 'isaac-installer-auto-stash-\$(date +%s)' 2>/dev/null || true
        fi

        if [[ '${is_tag}' == 'true' || '${desired_ref}' == v* ]]; then
            git checkout 'tags/${desired_ref}' -B 'release/${desired_ref}' 2>/dev/null || git checkout '${desired_ref}' 2>/dev/null
        else
            git checkout '${desired_ref}' 2>/dev/null || git checkout -b '${desired_ref}' 'origin/${desired_ref}' 2>/dev/null || git checkout -b '${desired_ref}' 'upstream/${desired_ref}' 2>/dev/null
        fi
    "
}

# Check if a remote fork repository exists on GitHub
check_remote_fork_exists() {
    local repo_url="$1"
    detect_target_user

    # 1. Try with git ls-remote first
    if sudo -H -u "${TARGET_USER}" git ls-remote --heads "$repo_url" &>/dev/null; then
        return 0
    fi

    # 2. Try with gh CLI if authenticated
    local slug
    slug="$(extract_repo_owner "$repo_url")/$(basename "$repo_url" .git)"
    if sudo -H -u "${TARGET_USER}" gh api "repos/${slug}" &>/dev/null; then
        return 0
    fi

    return 1
}

# Ensures a user fork exists on GitHub, automatically creating it via gh if missing
ensure_github_fork() {
    local requested_fork_url="$1"
    local official_upstream_url="$2"

    requested_fork_url="$(normalize_git_url "$requested_fork_url")"
    official_upstream_url="$(normalize_git_url "$official_upstream_url")"

    if [[ "$requested_fork_url" == "$official_upstream_url" ]]; then
        echo "$requested_fork_url"
        return 0
    fi

    detect_target_user

    # Check if the fork already exists on GitHub
    if check_remote_fork_exists "$requested_fork_url"; then
        echo "$requested_fork_url"
        return 0
    fi

    # Fork does not exist; check if auto_create_fork is enabled and gh is authenticated
    local auto_create="${WORKSPACE_AUTO_CREATE_FORK:-${CFG_WORKSPACE_AUTO_CREATE_FORK:-true}}"
    if [[ "$auto_create" == "true" ]] && command -v gh &>/dev/null && sudo -H -u "${TARGET_USER}" gh auth status &>/dev/null; then
        log_info "GitHub fork ${requested_fork_url} not found. Automatically creating fork of ${official_upstream_url} via GitHub CLI..."
        if sudo -H -u "${TARGET_USER}" gh repo fork "${official_upstream_url}" --clone=false --default-branch-only 2>/dev/null; then
            log_success "Fork successfully created on GitHub under your account."
            echo "$requested_fork_url"
            return 0
        fi
    fi

    log_warn "Fork ${requested_fork_url} does not exist on GitHub and auto-fork was unavailable."
    log_info "Falling back to cloning official upstream repository directly: ${official_upstream_url}"
    echo "$official_upstream_url"
}

# Checks if local repository fork is behind or ahead of official upstream
check_fork_sync_status() {
    local repo_path="$1"
    detect_target_user

    if [[ ! -d "${repo_path}/.git" ]]; then
        echo "{\"sync\": \"unknown\"}"
        return 1
    fi

    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${repo_path}'
        if ! git remote | grep -q '^upstream$'; then
            echo '{\"has_upstream\": false}'
            exit 0
        fi

        git fetch upstream --quiet 2>/dev/null || true
        curr_branch=\$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')
        
        # Check against matching upstream branch or upstream/main
        upstream_ref='upstream/main'
        if git rev-parse --verify \"upstream/\${curr_branch}\" &>/dev/null; then
            upstream_ref=\"upstream/\${curr_branch}\"
        fi

        behind=\$(git rev-list --count HEAD..\${upstream_ref} 2>/dev/null || echo 0)
        ahead=\$(git rev-list --count \${upstream_ref}..HEAD 2>/dev/null || echo 0)

        python3 -c \"
import json
print(json.dumps({
    'has_upstream': True,
    'branch': '\${curr_branch}',
    'upstream_ref': '\${upstream_ref}',
    'behind': int('\${behind}'),
    'ahead': int('\${ahead}'),
    'in_sync': int('\${behind}') == 0 and int('\${ahead}') == 0
}))
\"
    " 2>/dev/null || echo "{\"sync\": \"unknown\"}"
}

# Clones or updates a repository with dual-remote (origin = fork, upstream = official) and ref resolution
setup_git_repo_with_fork() {
    local dest_dir="$1"
    local fork_or_main_url="$2"
    local official_upstream_url="$3"
    local branch="${4:-main}"
    local tag="${5:-}"
    local recurse_submodules="${6:-false}"

    detect_target_user
    mkdir -p "$(dirname "$dest_dir")"
    chown "${TARGET_USER}:${TARGET_USER}" "$(dirname "$dest_dir")"

    fork_or_main_url="$(ensure_github_fork "$fork_or_main_url" "$official_upstream_url")"
    official_upstream_url="$(normalize_git_url "$official_upstream_url")"

    local target_ref="${tag:-$branch}"
    local is_tag=false
    if [[ -n "$tag" ]]; then is_tag=true; fi

    if [[ ! -d "${dest_dir}/.git" ]]; then
        log_info "Cloning ${fork_or_main_url} (${target_ref}) -> ${dest_dir}..."
        
        local clone_cmd=(git clone)
        if [[ -n "$target_ref" ]]; then
            clone_cmd+=(-b "${target_ref}")
        fi
        if [[ "$recurse_submodules" == true ]]; then
            clone_cmd+=(--recurse-submodules --shallow-submodules)
        fi
        clone_cmd+=("${fork_or_main_url}" "${dest_dir}")

        if ! sudo -H -u "${TARGET_USER}" "${clone_cmd[@]}"; then
            log_warn "Direct clone with ref '${target_ref}' failed. Falling back to default clone and checkout..."
            sudo -H -u "${TARGET_USER}" git clone "${fork_or_main_url}" "${dest_dir}"
        fi
        chown -R "${TARGET_USER}:${TARGET_USER}" "${dest_dir}"
    else
        log_info "Existing repository found at ${dest_dir}."
    fi

    # Configure Dual Remotes
    sudo -H -u "${TARGET_USER}" bash -c "
        cd '${dest_dir}'
        current_origin=\$(git remote get-url origin 2>/dev/null || echo '')
        
        # Ensure origin points to user's fork
        if [[ -n '${fork_or_main_url}' && \"\$current_origin\" != '${fork_or_main_url}' ]]; then
            git remote set-url origin '${fork_or_main_url}' 2>/dev/null || git remote add origin '${fork_or_main_url}' 2>/dev/null
        fi

        # Ensure upstream remote is wired to canonical repo with disabled push
        if [[ -n '${official_upstream_url}' && '${fork_or_main_url}' != '${official_upstream_url}' ]]; then
            if ! git remote | grep -q '^upstream$'; then
                git remote add upstream '${official_upstream_url}' 2>/dev/null || true
            else
                git remote set-url upstream '${official_upstream_url}' 2>/dev/null || true
            fi
            git config remote.upstream.pushurl 'PUSH_DISABLED_CANONICAL_UPSTREAM' 2>/dev/null || true
            git fetch upstream 2>/dev/null || true
        fi
    "

    # Reconcile / Checkout desired tag or branch
    if [[ -n "$target_ref" ]]; then
        fetch_and_checkout_ref "${dest_dir}" "${target_ref}" "${is_tag}"
    fi

    # Handle Submodule Update if requested
    if [[ "$recurse_submodules" == true ]]; then
        sudo -H -u "${TARGET_USER}" bash -c "
            cd '${dest_dir}'
            git config --local submodule.recurse true 2>/dev/null || true
            git submodule update --init --recursive --depth 1 2>/dev/null || true
        "
    fi

    # Register in GitHub Desktop
    register_github_desktop_repo "${dest_dir}"
}

