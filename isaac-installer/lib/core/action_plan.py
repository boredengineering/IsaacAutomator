"""Pure concrete installer plans. This module does not inspect or mutate targets.

Evidence is caller-supplied, never proof of permission. Apply revalidates it.
The plan is an operation record, not an executable shell script or authorization.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import sys
from typing import Any

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('action_workspace_paths', Path(__file__).with_name('workspace_paths.py'))
assert _spec and _spec.loader
_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_paths)
_spec = importlib.util.spec_from_file_location('action_plan_evidence', Path(__file__).with_name('plan_evidence.py'))
assert _spec and _spec.loader
_evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_evidence)
validate_evidence = _evidence.validate_evidence


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def hash_content(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def inspect_adoption(desired, evidence, policy=None):
    """Eligibility for reviewed inspection ONLY, never automatic Git mutation."""
    reasons = []
    if not policy or policy.get('reviewed') is not True or policy.get('permitted_actions') != ['inspect']:
        reasons.append('explicit reviewed inspection-only policy required')
    for key in ('repository', 'revision'):
        if not desired.get(key) or evidence.get(key) != desired[key]:
            reasons.append(key + ' identity unverified or mismatched')
    for key in ('dirty', 'untracked', 'ignored', 'worktrees', 'nested', 'local_commits'):
        if evidence.get(key) is not False:
            reasons.append(key + ' present or unknown')
    return {'eligible': not reasons, 'reasons': reasons, 'mutation_supported': False,
            'permitted_actions': ['inspect'] if not reasons else []}


def build_action_plan(profile, *, target_home, observed=None):
    """Resolve explicit desired data and optional bounded evidence, without I/O."""
    profile = deepcopy(profile.get('profile', profile))
    home = str(_paths.expand_path(target_home, target_home))
    evidence = validate_evidence({} if observed is None else observed)
    actions: list[dict[str, Any]] = []

    def add(identifier, category, operation, target, desired) -> dict[str, Any]:
        obs = deepcopy(evidence.get(target, {}))
        status = 'would_change' if obs.get('state') == 'missing' else 'unknown'
        action = dict(id=identifier, category=category, operation=operation, target=target,
                      desired=deepcopy(desired), status=status, reason='target missing' if status == 'would_change' else 'bounded evidence required',
                      effects=['create new directory; never chown existing parents'],
                      preconditions=obs, policy={'ownership': 'new-only', 'high_risk': False},
                      execution_supported=True, unsupported_reason=None)
        if obs.get('state') == 'directory' and operation == 'mkdir':
            action.update(status='satisfied', reason='exact existing directory; no ownership adoption or changes')
        elif obs.get('state') not in (None, 'missing'):
            action.update(status='blocked', reason='existing resource is not authorized for mutation')
        if obs.get('conflict'):
            action.update(status='blocked', reason='observed collision or unsupported path')
        actions.append(action)
        return action

    # Effective local-consumer defaults, not evidence about any installed tree.
    # Sparse explicit workspace declarations remain unresolved, never filled in.
    workspace = profile.get('workspace', {})
    if not workspace and profile.get('kind') == 'workstation-profile':
        workspace = {'root': '~/Documents/GitHub', 'layout': 'flat'}
    root = None
    if workspace and workspace.get('root') and (workspace.get('layout') or not workspace.get('name')):
        layout = workspace.get('layout', 'flat')
        _paths.validate_settings(layout, workspace.get('name', ''), workspace.get('default_owner', ''))
        root = str(_paths.expand_path(workspace['root'], home))
        workspace_action = add('workspace.root', 'workspace', 'mkdir', root, {})
        if layout in ('auto', 'org'):
            workspace_action.update(status='unknown', execution_supported=False, unsupported_reason='legacy owner/layout mapping requires explicit migration review', reason='legacy owner/layout mapping requires explicit migration review')
            root = None
        if layout == 'named':
            root = str(Path(root) / workspace['name'])
            add('workspace.group', 'workspace', 'mkdir', root, {})
    elif workspace:
        action = add('workspace.root', 'workspace', 'mkdir', 'unresolved-workspace', {})
        action.update(status='unknown', execution_supported=False, unsupported_reason='reviewed workspace root/layout required', reason='reviewed workspace root/layout required')
    names = {'sim': 'IsaacSim', 'lab': 'IsaacLab', 'isaaclab': 'IsaacLab', 'arena': 'IsaacLab-Arena', 'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot'}

    def unsupported(identifier, category, operation, target, desired, reason, enabled=True, high_risk=False) -> dict[str, Any]:
        action = add(identifier, category, operation, target, desired)
        action.update(execution_supported=False, unsupported_reason=reason,
                      status='blocked' if high_risk else action['status'], reason=reason,
                      effects=[reason], policy={'ownership': 'no-adoption', 'high_risk': high_risk})
        if not enabled:
            action.update(status='excluded', reason='explicitly disabled')
        return action

    components = profile.get('components', profile.get('repositories', {}))
    if isinstance(components, list):
        components = {}  # Shared repositories are declarations, not components.
    for name, component in components.items():
        source = component.get('source', component)
        resolution = None
        if source.get('mode') == 'standalone':
            target = str(_paths.expand_path(component['path'], home)) if component.get('path') else str(Path(home) / 'IsaacSim') if name == 'sim' else 'unresolved-install-prefix:' + name
        elif workspace.get('name') and not workspace.get('layout'):
            target = 'unresolved-workspace:' + name
        else:
            resolution = _paths.resolve_paths(home=home, repo=names.get(name, name),
                slug=source.get('repository', source.get('repo', '')), path_override=component.get('path', ''),
                root=workspace.get('root', ''), layout=workspace.get('layout', 'auto'),
                name=workspace.get('name', ''), configured_owner=workspace.get('default_owner', ''))
            target = resolution['destination'] or 'unresolved-workspace:' + name
        action = unsupported('component.' + name, 'repository', 'repository_checkout', target,
                    source, 'repository checkout requires pinned revision, explicit new destination and isolated source adapter; network/build/submodules/LFS gated', component.get('enabled', False))
        if component.get('enabled') and resolution and resolution['status'] == 'unknown':
            action.update(status='blocked' if workspace.get('root') else 'unknown', reason=resolution['reason'])
        if source.get('mode') == 'standalone':
            action.update(category='artifact', operation='artifact_install', unsupported_reason='artifact integrity/extraction, EULA and runtime verification require a dedicated qualified adapter', reason='artifact integrity/extraction, EULA and runtime verification require a dedicated qualified adapter', effects=['download/verify artifact, extract into selected new prefix, separately review EULA and runtime setup'])
            if not component.get('path') and name != 'sim':
                action['target'] = 'unresolved-install-prefix:' + name
        if source.get('fixture_local') is True and re.fullmatch('[0-9a-f]{40}', source.get('revision', '')) and source.get('repository', '').startswith('/') and component.get('path'):
            action.update(execution_supported=True, unsupported_reason=None,
                          effects=['copy bounded local fixture Git objects without config/hooks/hardlinks; detached pinned checkout; publish only a new directory; no builds/submodules/LFS'],
                          policy={'ownership': 'new-only', 'high_risk': False, 'adapter': 'local-fixture-git'})
            if action['status'] != 'excluded':
                obs = action['preconditions']
                if obs.get('managed') and obs.get('desired_digest') == digest(source):
                    action.update(status='satisfied', reason='managed checkout tree and requested identity unchanged')
                elif obs.get('state') == 'missing':
                    action.update(status='would_change', reason='new pinned local-fixture checkout')
    for name, runtime in profile.get('runtimes', {}).items():
        manager = runtime.get('manager', 'unknown')
        target = str(_paths.expand_path(runtime['path'], home)) if runtime.get('path') else 'unresolved-runtime-prefix:' + manager + ':' + runtime.get('environment', name)
        if manager == 'uv' and name == 'gr00t' and not runtime.get('path'):
            component_target = next((a['target'] for a in actions if a['id'] == 'component.gr00t'), None)
            if component_target and component_target.startswith('/'):
                target = str(Path(component_target) / '.venv')
        selected = {c.get('runtime', 'lab' if key == 'arena' else key) for key, c in profile.get('components', {}).items() if c.get('enabled') is True}
        enabled = runtime.get('enabled', name in selected if 'components' in profile else True)
        action = unsupported('runtime.' + name, 'environment', 'environment_create', target, runtime,
                    manager + ' environment provisioning requires a qualified new-prefix adapter; existing environment mutation prohibited', enabled)
        if target.startswith('unresolved-runtime-prefix:') and enabled:
            action.update(status='unknown', reason='consumer runtime prefix depends on separately supplied installation evidence; no environment-name guess is a filesystem path')
        if manager == 'venv' and runtime.get('fixture_local') is True and runtime.get('path'):
            action.update(execution_supported=True, unsupported_reason=None,
                          policy={'ownership': 'new-only', 'high_risk': False, 'adapter': 'stdlib-venv'},
                          effects=['create new isolated stdlib venv without pip/packages; relocate generated activation paths before atomic publication'])
            obs = action['preconditions']
            if enabled and obs.get('managed') and obs.get('desired_digest') == digest(runtime):
                action.update(status='satisfied', reason='managed environment bytes and desired intent unchanged')
            elif enabled and obs.get('state') == 'missing':
                action.update(status='would_change', reason='explicit new fixture venv prefix')
    for name, tool in profile.get('tools', profile.get('devtools', {})).items():
        tool = tool if isinstance(tool, dict) else {'enabled': tool}
        placement = tool.get('placement', 'host')
        target = placement + ':' + (tool.get('environment', '') + ':' if tool.get('environment') else '') + name
        unsupported('tool.' + name, 'tool', 'package_install', target, tool,
                    tool.get('manager', 'system') + ' package execution unavailable: pinned source, isolated placement and package-specific recovery required', tool.get('enabled', True), placement == 'host')
    for category in ('settings', 'hardware', 'teleoperation', 'streaming'):
        for name, setting in profile.get(category, {}).items():
            enabled = setting.get('enabled', True) if isinstance(setting, dict) else setting not in (False, None, 'none')
            identifier = ('setting' if category == 'settings' else category) + '.' + name
            unsupported(identifier, category, 'settings_change', category + ':' + name, setting,
                        'separate maintenance/settings permission and operation-specific recovery required; not executed by fixture adapter', enabled, True)
    if 'serving' in profile:
        service = profile['serving']
        unsupported('serving', 'service', 'service_setup', 'tcp://' + str(service.get('bind', 'unresolved')) + ':' + str(service.get('port', 'unresolved')), service,
                    'model downloads and service/startup configuration require separate scoped execution', service.get('enabled', False), True)
    for index, item in enumerate(profile.get('custom_dependencies', [])):
        placement = item.get('placement', 'unknown')
        target = item.get('location') or placement + ':' + str(item.get('environment') or 'unresolved') + ':' + item.get('name', 'unknown')
        action = unsupported(item.get('id', 'custom.' + str(index)), 'custom_dependency', 'package_install', target, item,
                             'custom dependency has no qualified package/source/placement adapter', True)
        action['policy']['required'] = item.get('required', False)
        action['status'] = 'blocked' if item.get('required') else 'unknown'
    for category in ('repositories', 'environments', 'notes'):
        declarations = profile.get(category, [])
        if not isinstance(declarations, list):
            continue
        for index, item in enumerate(declarations):
            target = item.get('root') or item.get('path') or category + ':' + str(index)
            action = unsupported(item.get('id', category + '.' + str(index)), 'declaration', 'unsupported', target, item,
                                 'declaration remains unsupported; no implicit source execution or environment mutation')
            action['policy']['required'] = item.get('required', False)
            action['status'] = 'blocked' if item.get('required') else 'unknown'
    handled = {'workspace', 'components', 'repositories', 'runtimes', 'tools', 'devtools', 'settings', 'hardware', 'teleoperation', 'streaming', 'serving', 'custom_dependencies', 'managed_files', 'environments', 'notes'}
    metadata = {'kind', 'schema_version', 'defaults', 'draft', 'name', 'profile_name', 'description', 'version', 'target'}
    coverage = {key: 'planned' if key in handled else 'metadata' if key in metadata else 'unsupported' for key in profile}
    for key in sorted(set(profile) - handled - metadata):
        unsupported('unsupported.' + key, 'unsupported', 'unsupported', key, {}, 'unmapped profile field; never silently ignored', True, True)
    for index, item in enumerate(profile.get('managed_files', [])):
        target = str(_paths.expand_path(item['path'], home))
        content = item['content']
        if not isinstance(content, str) or len(content.encode('utf-8')) > 1048576:
            raise ValueError('managed declarative content must be text <= 1 MiB')
        action = add('managed_file.' + str(index), 'declarative_file', 'write_file', target, {'content': content})
        action['effects'] = ['atomic new file publication; never overwrite an existing name']
        obs = action['preconditions']
        if obs.get('state') == 'file' and obs.get('managed') is True and obs.get('sha256') == hash_content(content):
            action.update(status='satisfied', reason='managed identity and desired content match')
        elif obs.get('state') == 'file':
            action.update(status='blocked', reason='foreign/changed file: use explicitly selected new versioned path; in-place CAS unsupported')
        if item.get('enabled') is False:
            action.update(status='excluded', reason='explicitly disabled')
    plan = dict(kind='installer-action-plan', version=1, target_home=home,
                profile_digest=digest(profile), actions=actions, coverage=coverage, draft=bool(profile.get('draft', False)))
    plan['digest'] = digest(plan)
    return plan
