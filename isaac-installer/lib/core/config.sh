#!/usr/bin/env bash
# ==============================================================================
# config.sh - Declarative YAML Configuration Profile Parser & Dispatcher
# ==============================================================================

DEFAULT_CONFIG_PATH="${SCRIPT_DIR}/config/default-profile.yaml"
CONFIG_FILE="${DEFAULT_CONFIG_PATH}"
PROFILE_NAME="default-workstation"

expand_tilde_path() {
    local path="$1"
    detect_target_user
    echo "${path/#\~/$TARGET_HOME}"
}

# Resolves a profile alias or path to an exact YAML file
resolve_profile_path() {
    local target="$1"

    # Direct existing path
    if [[ -f "$target" ]]; then
        printf '%s\n' "$target"
        return 0
    fi

    # Check aliases inside config directory
    case "$target" in
        minimal|headless|ci)
            if [[ -f "${SCRIPT_DIR}/config/minimal-headless.yaml" ]]; then
                printf '%s\n' "${SCRIPT_DIR}/config/minimal-headless.yaml"
                return 0
            fi
            printf 'Installer preset minimal-headless.yaml is missing; restore it or use an exact YAML path.\n' >&2
            return 1
            ;;
        full|ecosystem|all)
            if [[ -f "${SCRIPT_DIR}/config/full-ecosystem.yaml" ]]; then
                printf '%s\n' "${SCRIPT_DIR}/config/full-ecosystem.yaml"
                return 0
            fi
            printf 'Installer preset full-ecosystem.yaml is missing; restore it or use an exact YAML path.\n' >&2
            return 1
            ;;
        default|standard|workstation)
            if [[ -f "${SCRIPT_DIR}/config/default-profile.yaml" ]]; then
                printf '%s\n' "${SCRIPT_DIR}/config/default-profile.yaml"
                return 0
            fi
            printf 'Installer preset default-profile.yaml is missing; restore it or use an exact YAML path.\n' >&2
            return 1
            ;;
    esac

    # Retain unique substring lookup, but treat the request literally, not as a glob.
    local candidate filename
    local -a matches=()
    if [[ -n "$target" ]]; then
        for candidate in "${SCRIPT_DIR}/config/"*.yaml; do
            [[ -f "$candidate" ]] || continue
            filename="${candidate##*/}"
            [[ "$filename" == *"$target"* ]] && matches+=("$candidate")
        done
    fi
    if [[ ${#matches[@]} -eq 1 ]]; then
        printf '%s\n' "${matches[0]}"
        return 0
    fi
    if [[ ${#matches[@]} -gt 1 ]]; then
        printf 'Ambiguous installer profile: %s; use an exact file path.\n' "$target" >&2
    else
        printf 'Unknown installer profile: %s; use a preset alias or existing YAML path.\n' "$target" >&2
    fi
    return 1
}

# Load and parse YAML configuration profile into environment variables
load_config_profile() {
    local requested="${1-${DEFAULT_CONFIG_PATH}}"
    local resolved
    # Protect filename newlines from command substitution, then remove only the
    # sentinel and the single record terminator printed by the resolver.
    resolved="$(resolve_profile_path "$requested" && printf '.')" || return 1
    resolved="${resolved%.}"
    resolved="${resolved%$'\n'}"

    # Stage data before applying it: process substitution alone hides parser failures.
    # NUL-delimited records preserve whitespace, quotes and shell metacharacters.
    local profile_data key value
    profile_data=$(mktemp) || return 1
    if ! python3 "${BASH_SOURCE[0]%/*}/profile_parser.py" "$resolved" > "$profile_data"; then
        rm -f -- "$profile_data"
        return 1
    fi
    # CFG_* is reserved for the active profile, including flags added by the caller.
    # Failed resolution/parsing leaves the previous profile intact. Operational
    # variables retain their existing CLI-override semantics below.
    for key in "${!CFG_@}"; do
        unset "$key"
    done
    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        export "$key=$value"
    done < "$profile_data"
    rm -f -- "$profile_data"
    CONFIG_FILE="$resolved"
    detect_target_user

    # Map CFG variables to operational parameters if not overridden by CLI
    PROFILE_NAME="${CFG_PROFILE_NAME:-default}"
    export PROFILE_NAME

    # Workspace
    if [[ -z "${WORKSPACE_DIR:-}" && -n "${CFG_WORKSPACE_ROOT:-}" ]]; then
        WORKSPACE_DIR="$(expand_tilde_path "${CFG_WORKSPACE_ROOT}")"
    fi
    WORKSPACE_LAYOUT="${CFG_WORKSPACE_LAYOUT:-auto}"
    WORKSPACE_DEFAULT_OWNER="${CFG_WORKSPACE_DEFAULT_OWNER:-}"
    WORKSPACE_AUTO_CREATE_FORK="${CFG_WORKSPACE_AUTO_CREATE_FORK:-true}"
    export WORKSPACE_DIR WORKSPACE_LAYOUT WORKSPACE_DEFAULT_OWNER WORKSPACE_AUTO_CREATE_FORK

    # Repositories
    if [[ -z "${ISAACLAB_REPO:-}" && -n "${CFG_REPOSITORIES_ISAACLAB_REPO:-${CFG_ISAAC_LAB_REPO:-}}" ]]; then
        ISAACLAB_REPO="${CFG_REPOSITORIES_ISAACLAB_REPO:-${CFG_ISAAC_LAB_REPO:-}}"
    fi
    ISAACLAB_UPSTREAM="${ISAACLAB_UPSTREAM:-${CFG_REPOSITORIES_ISAACLAB_UPSTREAM:-https://github.com/isaac-sim/IsaacLab.git}}"
    ISAACLAB_BRANCH="${ISAACLAB_BRANCH:-${CFG_REPOSITORIES_ISAACLAB_BRANCH:-main}}"
    ISAACLAB_TAG="${ISAACLAB_TAG:-${CFG_REPOSITORIES_ISAACLAB_TAG:-}}"
    export ISAACLAB_REPO ISAACLAB_UPSTREAM ISAACLAB_BRANCH ISAACLAB_TAG

    if [[ -z "${ARENA_REPO:-}" && -n "${CFG_REPOSITORIES_ARENA_REPO:-${CFG_ISAACLAB_ARENA_REPO:-}}" ]]; then
        ARENA_REPO="${CFG_REPOSITORIES_ARENA_REPO:-${CFG_ISAACLAB_ARENA_REPO:-}}"
    fi
    ARENA_UPSTREAM="${ARENA_UPSTREAM:-${CFG_REPOSITORIES_ARENA_UPSTREAM:-https://github.com/isaac-sim/IsaacLab-Arena.git}}"
    ARENA_BRANCH="${ARENA_BRANCH:-${CFG_REPOSITORIES_ARENA_BRANCH:-release/0.3.0-prerelease}}"
    ARENA_TAG="${ARENA_TAG:-${CFG_REPOSITORIES_ARENA_TAG:-}}"
    export ARENA_REPO ARENA_UPSTREAM ARENA_BRANCH ARENA_TAG

    if [[ -z "${LEROBOT_REPO:-}" && -n "${CFG_REPOSITORIES_LEROBOT_REPO:-${CFG_ECOSYSTEM_LEROBOT_REPO:-}}" ]]; then
        LEROBOT_REPO="${CFG_REPOSITORIES_LEROBOT_REPO:-${CFG_ECOSYSTEM_LEROBOT_REPO:-}}"
    fi
    LEROBOT_UPSTREAM="${LEROBOT_UPSTREAM:-${CFG_REPOSITORIES_LEROBOT_UPSTREAM:-https://github.com/huggingface/lerobot.git}}"
    LEROBOT_BRANCH="${LEROBOT_BRANCH:-${CFG_REPOSITORIES_LEROBOT_BRANCH:-main}}"
    LEROBOT_TAG="${LEROBOT_TAG:-${CFG_REPOSITORIES_LEROBOT_TAG:-v0.4.3}}"
    LEROBOT_ISOLATED_ENV="${CFG_REPOSITORIES_LEROBOT_ISOLATED_ENV:-true}"
    export LEROBOT_REPO LEROBOT_UPSTREAM LEROBOT_BRANCH LEROBOT_TAG LEROBOT_ISOLATED_ENV

    if [[ -z "${GR00T_REPO:-}" && -n "${CFG_REPOSITORIES_GR00T_REPO:-}" ]]; then
        GR00T_REPO="${CFG_REPOSITORIES_GR00T_REPO:-}"
    fi
    GR00T_UPSTREAM="${GR00T_UPSTREAM:-${CFG_REPOSITORIES_GR00T_UPSTREAM:-https://github.com/NVIDIA/Isaac-GR00T.git}}"
    GR00T_BRANCH="${GR00T_BRANCH:-${CFG_REPOSITORIES_GR00T_BRANCH:-main}}"
    GR00T_TAG="${GR00T_TAG:-${CFG_REPOSITORIES_GR00T_TAG:-}}"
    GR00T_MODEL_PATH="${GR00T_MODEL_PATH:-${CFG_REPOSITORIES_GR00T_MODEL_PATH:-nvidia/GR00T-N1.7-3B}}"
    GR00T_VLM_BACKBONE="${GR00T_VLM_BACKBONE:-${CFG_REPOSITORIES_GR00T_VLM_BACKBONE:-nvidia/Cosmos-Reason2-2B}}"
    GR00T_SERVER_PORT="${GR00T_SERVER_PORT:-${CFG_REPOSITORIES_GR00T_SERVER_PORT:-5556}}"
    GR00T_ISOLATED_ENV="${CFG_REPOSITORIES_GR00T_ISOLATED_ENV:-true}"
    export GR00T_REPO GR00T_UPSTREAM GR00T_BRANCH GR00T_TAG GR00T_MODEL_PATH GR00T_VLM_BACKBONE GR00T_SERVER_PORT GR00T_ISOLATED_ENV

    # Isaac Sim
    if [[ -z "${ISAACSIM_DIR:-}" && -n "${CFG_SIMULATION_ISAACSIM_INSTALL_DIR:-${CFG_ISAAC_SIM_INSTALL_PATH:-}}" ]]; then
        ISAACSIM_DIR="$(expand_tilde_path "${CFG_SIMULATION_ISAACSIM_INSTALL_DIR:-${CFG_ISAAC_SIM_INSTALL_PATH:-}}")"
    fi
    ISAACSIM_VERSION="${CFG_SIMULATION_ISAACSIM_VERSION:-6.0.1}"
    ISAACSIM_SOURCE_TYPE="${CFG_SIMULATION_ISAACSIM_SOURCE_TYPE:-standalone}"
    ISAACSIM_CUSTOM_BUILD_SOURCE_PATH="$(expand_tilde_path "${CFG_SIMULATION_ISAACSIM_CUSTOM_BUILD_SOURCE_PATH:-}")"
    ISAACSIM_CUSTOM_BUILD_COMMAND="${CFG_SIMULATION_ISAACSIM_CUSTOM_BUILD_COMMAND:-}"
    export ISAACSIM_DIR ISAACSIM_VERSION ISAACSIM_SOURCE_TYPE ISAACSIM_CUSTOM_BUILD_SOURCE_PATH ISAACSIM_CUSTOM_BUILD_COMMAND
}

print_active_config() {
    log_header "Active YAML Configuration Profile: ${CONFIG_FILE}"
    cat "${CONFIG_FILE}"
    echo ""
}
