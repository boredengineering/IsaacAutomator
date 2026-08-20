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
        echo "$target"
        return 0
    fi

    # Check aliases inside config directory
    case "$target" in
        minimal|headless|ci)
            if [[ -f "${SCRIPT_DIR}/config/minimal-headless.yaml" ]]; then
                echo "${SCRIPT_DIR}/config/minimal-headless.yaml"
                return 0
            fi
            ;;
        full|ecosystem|all)
            if [[ -f "${SCRIPT_DIR}/config/full-ecosystem.yaml" ]]; then
                echo "${SCRIPT_DIR}/config/full-ecosystem.yaml"
                return 0
            fi
            ;;
        default|standard|workstation)
            if [[ -f "${SCRIPT_DIR}/config/default-profile.yaml" ]]; then
                echo "${SCRIPT_DIR}/config/default-profile.yaml"
                return 0
            fi
            ;;
    esac

    # Search config/*.yaml matching target
    local match
    match=$(find "${SCRIPT_DIR}/config" -maxdepth 1 -type f -name "*${target}*.yaml" 2>/dev/null | head -n 1 || true)
    if [[ -n "$match" && -f "$match" ]]; then
        echo "$match"
        return 0
    fi

    echo "${DEFAULT_CONFIG_PATH}"
}

# Load and parse YAML configuration profile into environment variables
load_config_profile() {
    local requested="${1:-${DEFAULT_CONFIG_PATH}}"
    CONFIG_FILE="$(resolve_profile_path "$requested")"
    detect_target_user

    # Robust Python-based YAML parser (Handles PyYAML or recursive standard token fallback)
    local env_exports
    env_exports=$(python3 -c "
import sys, re

def parse_yaml_file(filepath):
    try:
        import yaml
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass

    tokens = []
    with open(filepath, 'r') as f:
        for line in f:
            raw = line.split('#')[0].rstrip()
            if not raw or raw.isspace():
                continue
            indent = len(raw) - len(raw.lstrip())
            trimmed = raw.strip()
            if ':' not in trimmed:
                continue
            k, v = trimmed.split(':', 1)
            tokens.append((indent, k.strip(), v.strip().strip('\"\'')))

    def build_tree(idx, min_indent):
        node = {}
        while idx < len(tokens):
            indent, k, v = tokens[idx]
            if indent < min_indent:
                break
            if v == '':
                sub_node, next_idx = build_tree(idx + 1, indent + 1)
                node[k] = sub_node
                idx = next_idx
            else:
                if v.lower() == 'true': node[k] = True
                elif v.lower() == 'false': node[k] = False
                elif v.isdigit(): node[k] = int(v)
                else: node[k] = v
                idx += 1
        return node, idx

    root, _ = build_tree(0, 0)
    return root

def flatten_dict(d, prefix='CFG_'):
    items = []
    if not isinstance(d, dict):
        return items
    for k, v in d.items():
        clean_k = re.sub(r'[^A-Za-z0-9_]', '_', str(k)).upper()
        new_key = f'{prefix}{clean_k}'
        if isinstance(v, dict):
            items.extend(flatten_dict(v, f'{new_key}_'))
        else:
            val_str = 'true' if v is True else ('false' if v is False else str(v))
            items.append((new_key, val_str))
    return items

cfg = parse_yaml_file('${CONFIG_FILE}')
for k, v in flatten_dict(cfg):
    print(f'export {k}=\"{v}\"')
" 2>/dev/null || true)

    if [[ -n "$env_exports" ]]; then
        eval "$env_exports"
    fi

    # Map CFG variables to operational parameters if not overridden by CLI
    PROFILE_NAME="${CFG_PROFILE_NAME:-default}"
    export PROFILE_NAME

    # Workspace
    if [[ -z "${WORKSPACE_DIR:-}" && -n "${CFG_WORKSPACE_ROOT:-}" ]]; then
        WORKSPACE_DIR="$(expand_tilde_path "${CFG_WORKSPACE_ROOT}")"
    fi

    # Repositories
    if [[ -z "${ISAACLAB_REPO:-}" && -n "${CFG_REPOSITORIES_ISAACLAB_REPO:-${CFG_ISAAC_LAB_REPO:-}}" ]]; then
        ISAACLAB_REPO="${CFG_REPOSITORIES_ISAACLAB_REPO:-${CFG_ISAAC_LAB_REPO:-}}"
    fi
    if [[ -z "${ARENA_REPO:-}" && -n "${CFG_REPOSITORIES_ARENA_REPO:-${CFG_ISAACLAB_ARENA_REPO:-}}" ]]; then
        ARENA_REPO="${CFG_REPOSITORIES_ARENA_REPO:-${CFG_ISAACLAB_ARENA_REPO:-}}"
    fi
    if [[ -z "${LEROBOT_REPO:-}" && -n "${CFG_REPOSITORIES_LEROBOT_REPO:-${CFG_ECOSYSTEM_LEROBOT_REPO:-}}" ]]; then
        LEROBOT_REPO="${CFG_REPOSITORIES_LEROBOT_REPO:-${CFG_ECOSYSTEM_LEROBOT_REPO:-}}"
    fi

    # Isaac Sim
    if [[ -z "${ISAACSIM_DIR:-}" && -n "${CFG_SIMULATION_ISAACSIM_INSTALL_DIR:-${CFG_ISAAC_SIM_INSTALL_PATH:-}}" ]]; then
        ISAACSIM_DIR="$(expand_tilde_path "${CFG_SIMULATION_ISAACSIM_INSTALL_DIR:-${CFG_ISAAC_SIM_INSTALL_PATH:-}}")"
    fi
}

print_active_config() {
    log_header "Active YAML Configuration Profile: ${CONFIG_FILE}"
    cat "${CONFIG_FILE}"
    echo ""
}
