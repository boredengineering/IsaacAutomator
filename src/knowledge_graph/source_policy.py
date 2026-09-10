"""Explicit, versioned admission policy; no source discovery or target imports."""
import re
from pathlib import Path

import yaml

POLICY_VERSION = 'automator-source-policy/v1'
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 16_777_216
MAX_FILES = 4096


class PolicyError(ValueError):
    """Safe machine-code-only policy failure."""


def validate_relative_path(path) -> str:
    """Validate a canonical source ID, never resolve arbitrary paths."""
    if (not isinstance(path, str) or len(path) > 512
            or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', path)
            or any(part in ('.', '..') for part in path.split('/'))):
        raise PolicyError('invalid_source_id')
    return path


def normalize_policy(policy: dict) -> dict:
    """Validate caller-supplied dicts as strictly as policies loaded from disk."""
    allowed = {'schema_version', 'repo_id', 'files', 'max_file_bytes', 'max_total_bytes'}
    if not isinstance(policy, dict) or set(policy) - allowed:
        raise PolicyError('invalid_policy')
    if policy.get('schema_version') != POLICY_VERSION:
        raise PolicyError('invalid_policy_version')
    repo_id = policy.get('repo_id')
    if not isinstance(repo_id, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', repo_id):
        raise PolicyError('invalid_repo_id')
    files = policy.get('files')
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise PolicyError('invalid_files')
    files = [validate_relative_path(p) for p in files]
    if len(set(files)) != len(files):
        raise PolicyError('duplicate_source_id')
    normalized = {'schema_version': POLICY_VERSION, 'repo_id': repo_id, 'files': sorted(files)}
    for key, ceiling in (('max_file_bytes', MAX_FILE_BYTES), ('max_total_bytes', MAX_TOTAL_BYTES)):
        limit = policy.get(key, ceiling)
        if type(limit) is not int or not 1 <= limit <= ceiling:
            raise PolicyError('invalid_size_limit')
        normalized[key] = limit
    return normalized


class _PolicyLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise PolicyError('invalid_policy_mapping')
        result[key] = loader.construct_object(value_node)
    return result


_PolicyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def exclusion_reason(path: str):
    """Hard pre-open exclusions also apply to explicitly requested IDs.

    Documents are intentionally unsupported: admitting prose requires a future
    reviewed-document policy, not just adding a file to this structural allowlist.
    """
    parts = path.lower().split('/')
    name = parts[-1]
    forbidden = {'private', 'state', 'results', 'uploads', 'logs', 'node_modules',
                 'venv', 'env', 'credentials', 'secrets', 'neo4j', 'home', 'cache'}
    if (any(p.startswith('.') or p in forbidden for p in parts)
            or any(x in name for x in ('credential', 'secret', 'password', 'tfstate', 'tfvars', 'backend'))
            or name.startswith(('id_rsa', 'id_ed25519', 'inventory', 'hosts'))
            and name != 'inventory.template'
            or name.endswith(('.pem', '.key', '.p12', '.log', '.bak'))):
        return 'protected_source'
    if Path(name).suffix not in {'.py', '.tf', '.hcl', '.yml', '.yaml', '.sh', '.template', '.j2'}:
        # Explicitly selected root cloud launchers are structural shell sources.
        if '/' in path or name not in {'deploy-aws', 'deploy-gcp', 'deploy-azure', 'deploy-alicloud'}:
            return 'unsupported_format'
    return None


def unsafe_content(text: str) -> bool:
    """Conservative quarantine, not a claim of perfect secret redaction.

    Sensitive identifier mentions are quarantined even in code/comments. This
    intentionally loses coverage rather than persisting uncertain literals.
    """
    return bool(re.search(
        r'(?i)(password|passwd|secret|token|api[_-]?key|private[_ -]?key|'
        r'authorization|bearer\s|AKIA[A-Z0-9]{16}|ASIA[A-Z0-9]{16}|'
        r'https?://[^\s/]+@|ignore\s+(?:all\s+)?previous\s+instructions|'
        r'FAKE[_-](?:SENTINEL|SECRET))', text))


def load_policy(path) -> dict:
    """Load a bounded nofollow policy using the same checked staging reader.

    The local import avoids a module initialization cycle: snapshot depends on
    the policy validators, and policy file loading reuses its descriptor reader.
    """
    from .snapshot import _checked_read

    try:
        p = Path(path).absolute()
        text = _checked_read(p.parent, p.name, 262144)
        return normalize_policy(yaml.load(text, Loader=_PolicyLoader))
    except (OSError, ValueError, TypeError, yaml.YAMLError, RecursionError):
        raise PolicyError('invalid_policy') from None
