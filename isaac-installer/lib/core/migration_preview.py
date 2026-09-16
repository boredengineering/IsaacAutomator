"""Pure, evidence-only naming comparison; never an adoption/apply operation."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location(
    'migration_workspace_paths', Path(__file__).with_name('workspace_paths.py'))
assert _spec and _spec.loader
_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_paths)


def compare_paths(old, new):
    if old is None or new is None:
        return 'unknown'
    if old == new:
        return 'same_destination'
    return 'case_only_change' if old.casefold() == new.casefold() else 'different_destination'


def build_migration_preview(old_config, new_config, target_home, repositories, observed=None):
    """Compare supplied intent without inspecting or changing a target."""
    if not isinstance(old_config, dict) or not isinstance(new_config, dict):
        raise ValueError('old_config and new_config must be mappings')
    if not isinstance(target_home, str) or not target_home.startswith('/'):
        raise ValueError('target_home must be an explicit absolute home')
    _paths.expand_path(target_home, '')
    if not isinstance(repositories, list):
        raise ValueError('repositories must be a list')
    if observed is not None and not isinstance(observed, dict):
        raise ValueError('observed must be a path-indexed evidence mapping')
    if len(repositories) > 4096 or len(observed or {}) > 16384:
        raise ValueError('migration input evidence limit exceeded')
    for path, evidence in (observed or {}).items():
        if not isinstance(path, str) or not path.startswith('/'):
            raise ValueError('observed path must be absolute')
        _paths.expand_path(path, '')
        if not isinstance(evidence, dict):
            raise ValueError('observed path evidence must be a mapping')
        for key in ('dirty', 'conflict'):
            if key in evidence and evidence[key] is not None and type(evidence[key]) is not bool:
                raise ValueError(key + ' evidence must be boolean or null')
        if evidence.get('state') not in (None, 'unknown', 'missing', 'directory', 'file', 'symlink', 'other'):
            raise ValueError('unsupported evidence state')
    for config in (old_config, new_config):
        workspace = config.get('workspace', {})
        if not isinstance(workspace, dict):
            raise ValueError('workspace must be a mapping')
        _paths.validate_settings(workspace.get('layout', 'auto'), workspace.get('name', ''),
                                 workspace.get('default_owner', ''))
        _paths.normalize_entries(config.get('directory_entries'))
    if repositories and not callable(getattr(_paths, 'resolve_paths', None)):
        raise RuntimeError('shared workspace_paths.resolve_paths integration is required')
    comparisons = []
    for repository in repositories:
        if not isinstance(repository, dict) or not repository.get('name'):
            raise ValueError('repository requires a name')
        if 'active_discovery_complete' in repository and type(repository['active_discovery_complete']) is not bool:
            raise ValueError('active_discovery_complete must be boolean')
        if 'active_path' in repository and repository['active_path'] is not None:
            _paths.expand_path(repository['active_path'], target_home)
        resolved = []
        for side, config in (('old', old_config), ('new', new_config)):
            workspace = config.get('workspace', {})
            args = dict(
                home=target_home, repo=repository['name'], slug=repository.get('slug', ''),
                path_override=repository.get(side + '_path_override', repository.get('path_override', '')),
                root=workspace.get('root', ''), layout=workspace.get('layout', 'auto'),
                name=workspace.get('name', ''), configured_owner=workspace.get('default_owner', ''),
                github_desktop=config.get('github_desktop', False))
            candidate = _paths.resolve_paths(**args)
            try:
                resolved.append(_paths.resolve_paths(**args, directory_entries=config.get('directory_entries')))
            except ValueError as error:
                candidate.update(destination=None, status='blocked', reason=str(error))
                resolved.append(candidate)
        old, new = resolved
        if old_config.get('workspace', {}).get('layout') == 'named':
            active = old['destination']
        elif repository.get('active_path'):
            active = str(_paths.expand_path(repository['active_path'], target_home))
        else:
            active = old['destination'] if repository.get('active_discovery_complete') is True else None
        reasons = [] if active else ['legacy active discovery cannot be resolved offline without supplied evidence']
        for side, value in (('old', old), ('new', new)):
            if value['status'] != 'resolved':
                reasons.append(side + ': ' + value['reason'])
        comparisons.append(dict(name=repository['name'], old_destination=old['destination'],
                                new_destination=new['destination'], active_path=active,
                                old_resolution=old, new_resolution=new,
                                status='unchanged' if active is not None and active == new['destination'] else 'unknown',
                                reasons=reasons,
                                active_path_change=compare_paths(active, new['destination']),
                                path_change=compare_paths(old['destination'], new['destination'])))
    evidence = {} if observed is None else observed
    destinations = {}
    for item in comparisons:
        target, active = item['new_destination'], item['active_path']
        source_obs, target_obs = evidence.get(active, {}), evidence.get(target, {})
        reasons = item['reasons']
        blocked = any(item[side + '_resolution']['status'] == 'blocked' for side in ('old', 'new'))
        if item['path_change'] == 'case_only_change' or item['active_path_change'] == 'case_only_change':
            blocked = True
            reasons.append('case-only rename requires explicit collision review; never rename automatically')
        if source_obs.get('dirty') is True or target_obs.get('dirty') is True:
            blocked = True
            reasons.append('caller evidence reports dirty work; preserve checkout')
        if source_obs.get('conflict') or target_obs.get('conflict'):
            blocked = True
            reasons.append('caller evidence reports collision or unsupported path')
        if source_obs.get('state') in ('file', 'symlink', 'other') or target_obs.get('state') in ('file', 'symlink', 'other'):
            blocked = True
            reasons.append('caller evidence reports unsupported repository path type')
        if target != active and target_obs.get('state') in ('directory', 'file', 'symlink', 'other'):
            blocked = True
            reasons.append('destination exists according to caller evidence; no adoption')
        if blocked:
            item['status'] = 'blocked'
        elif item['status'] != 'unchanged':
            if active and target and source_obs.get('state') == 'directory' and source_obs.get('dirty') is False and target_obs.get('state') == 'missing':
                item['status'] = 'review_required'
                reasons.append('supplied source/target evidence allows comparison only; migration apply unsupported')
            else:
                reasons.append('missing source cleanliness or target absence evidence; no filesystem observations made')
        if target:
            destinations.setdefault(target.casefold(), []).append(item)
    for rows in destinations.values():
        if len(rows) > 1:
            for item in rows:
                item['status'] = 'blocked'
                item['reasons'].append('repository destination collision within requested migration')
    return {
        'kind': 'workspace-migration-preview',
        'schema_version': 1,
        'read_only': True,
        'apply_supported': False,
        'unsupported_reason': 'Repository adoption, updates and migration apply are unsupported; preserve existing checkouts.',
        'repositories': comparisons,
    }
