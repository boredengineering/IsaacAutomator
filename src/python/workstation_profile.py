"""Pure offline workstation software intent; no deployment imports or execution."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re
import stat

import yaml

if __package__:
    from .public_artifact import validate_public_url
else:
    # Legacy confined preview tools load this file by spec, not via sys.path.
    # Preload only the trusted shipped sibling here, before confinement; never
    # search the observed environment or defer filesystem imports to parsing.
    import importlib.util
    _artifact_spec = importlib.util.spec_from_file_location(
        '_workstation_public_artifact', Path(__file__).with_name('public_artifact.py'))
    if _artifact_spec is None or _artifact_spec.loader is None:
        raise ImportError('Trusted public artifact validator unavailable')
    _artifact = importlib.util.module_from_spec(_artifact_spec)
    _artifact_spec.loader.exec_module(_artifact)
    validate_public_url = _artifact.validate_public_url


class ProfileError(ValueError):
    """Invalid or unsupported non-executable workstation profile."""


PRESETS = ('default', 'full', 'minimal')
COMPONENTS = ('sim', 'lab', 'arena', 'gr00t', 'lerobot', 'robolab')
RUNTIMES = ('kit', 'lab', 'gr00t', 'lerobot')
RUNTIME_MANAGERS = {'kit': 'bundled', 'lab': 'conda', 'gr00t': 'uv', 'lerobot': 'conda'}
PROFILE_DIR = Path(__file__).resolve().parents[2] / 'configs' / 'workstations'
COMPONENT_RUNTIME = {'sim': 'kit', 'lab': 'lab', 'arena': 'lab', 'gr00t': 'gr00t', 'lerobot': 'lerobot', 'robolab': 'lab'}
DEPENDENCIES = {'sim': [], 'lab': ['sim'], 'arena': ['lab'], 'gr00t': [], 'lerobot': [], 'robolab': ['lab']}


class _StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag != 'tag:yaml.org,2002:str':
                raise ProfileError('YAML keys must be strings; merge keys unsupported')
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise ProfileError('Duplicate YAML key')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _keys(value, allowed, path):
    if type(value) is not dict or any(type(k) is not str or k not in allowed for k in value):
        raise ProfileError(f'{path}: expected mapping with supported keys only')


def _text(value, pattern, path, nullable=False, maximum=256):
    if nullable and value is None:
        return
    if type(value) is not str or len(value) > maximum or not re.fullmatch(pattern, value):
        raise ProfileError(f'{path}: invalid nonsecret value')


def _ref(value, path):
    _text(value, r'[A-Za-z0-9][A-Za-z0-9._/-]*', path)
    if '..' in value or any(not p or p.startswith('.') or p.endswith(('.', '.lock')) for p in value.split('/')):
        raise ProfileError(f'{path}: invalid Git ref')


def _commit_ref(value):
    """Canonical identity for a full hexadecimal ref, never for a named ref."""
    return value.lower() if isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{40}', value) else None


def _source(value, path, mode):
    if mode == 'standalone':
        _keys(value, {'mode', 'version', 'sha256', 'url'}, path)
        if value.get('url') is not None:
            try:
                validate_public_url(value['url'])
            except ValueError as error:
                raise ProfileError(f'{path}.url: {error}') from None
        if 'version' in value:
            _nonsecret(value['version'], r'[0-9]+\.[0-9]+\.[0-9]+'
                       r'(?:-[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)?'
                       r'(?:\+[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)?',
                       path + '.version', maximum=64)
        if 'sha256' in value:
            _text(value['sha256'], r'[0-9a-f]{64}', path + '.sha256', nullable=True)
    else:
        _keys(value, {'repository', 'ref', 'revision'} | ({'mode'} if mode == 'git' else set()), path)
        if 'repository' in value:
            slug = r'[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*'
            pattern = r'https://github\.com/' + slug + r'\.git' if mode == 'git' else slug
            _text(value['repository'], pattern, path + '.repository')
        if 'ref' in value:
            _ref(value['ref'], path + '.ref')
        if 'revision' in value:
            _text(value['revision'], r'[0-9a-f]{40}', path + '.revision', nullable=True)
        ref, revision = value.get('ref'), value.get('revision')
        if _commit_ref(ref) and revision and revision != _commit_ref(ref):
            raise ProfileError(f'{path}: conflicting immutable selectors')
    if 'mode' in value and value['mode'] != mode:
        raise ProfileError(f'{path}.mode: unsupported source mode')


def _nonsecret(value, pattern, path, nullable=False, maximum=256):
    _text(value, pattern, path, nullable=nullable, maximum=maximum)
    if value is not None and re.search(r'(?i)(?:token|password|secret|credential|bearer)[=_:-]|gh[pousr]_|sk-', value):
        raise ProfileError(f'{path}: sensitive-looking value refused')


def _path_text(value, path):
    _nonsecret(value, r'(?:/|~/)[A-Za-z0-9_./ -]+', path, maximum=4096)
    parts = value.removeprefix('~/').removeprefix('/').split('/')
    if value != value.strip() or any(part in ('', '.', '..') for part in parts):
        raise ProfileError(f'{path}: expected a specific path without traversal')


def _workspace(value):
    _keys(value, {'root', 'layout', 'name', 'default_owner'}, 'workspace')
    if 'root' in value:
        _path_text(value['root'], 'workspace.root')
    for key in ('name', 'default_owner'):
        if key in value:
            _nonsecret(value[key], r'[A-Za-z0-9][A-Za-z0-9 ._-]*', 'workspace.' + key)
            if value[key] != value[key].strip():
                raise ProfileError('workspace: surrounding whitespace forbidden')
    layout = value.get('layout')
    if layout is not None and layout not in ('named', 'flat', 'auto', 'org'):
        raise ProfileError('workspace.layout: unsupported layout')
    if layout not in (None, 'named') and 'name' in value:
        raise ProfileError('workspace.name requires named layout')
    if 'name' in value and 'default_owner' in value and value['name'] != value['default_owner']:
        raise ProfileError('workspace.name conflicts with default_owner')


def _custom_dependencies(items):
    if type(items) is not list or len(items) > 4096:
        raise ProfileError('custom_dependencies: expected bounded list')
    seen = set()
    fields = {'id', 'name', 'version', 'environment', 'location', 'purpose', 'source',
              'placement', 'required', 'support'}
    for item in items:
        _keys(item, fields, 'custom_dependencies.item')
        if set(item) != fields:
            raise ProfileError('custom_dependencies: all declaration fields required')
        _nonsecret(item['id'], r'[A-Za-z0-9][A-Za-z0-9_.:+!-]{0,209}', 'custom_dependencies.id')
        if item['id'] in seen:
            raise ProfileError('custom_dependencies: duplicate identity')
        seen.add(item['id'])
        for key in ('name', 'environment'):
            _nonsecret(item[key], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', 'custom_dependencies.' + key,
                       nullable=key == 'environment')
        _nonsecret(item['version'], r'[0-9][A-Za-z0-9_.+!-]{0,63}', 'custom_dependencies.version', nullable=True)
        if item['purpose'] is not None:
            _note_text(item['purpose'], 'custom_dependencies.purpose')
        _nonsecret(item['source'], r'(?:(?:https|ssh)://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/[A-Za-z0-9_./~+-]+|[A-Za-z0-9][A-Za-z0-9_.+-]*)',
                   'custom_dependencies.source', nullable=True, maximum=2048)
        if item['source'] is not None and '://' in item['source']:
            _url_text(item['source'], 'custom_dependencies.source')
        if item['location'] is not None:
            _path_text(item['location'], 'custom_dependencies.location')
        if item['placement'] not in ('host', 'container', 'environment', 'project', 'unknown'):
            raise ProfileError('custom_dependencies.placement: unsupported placement')
        if type(item['required']) is not bool or item['support'] != 'unsupported':
            raise ProfileError('custom_dependencies: invalid required/support declaration')


def _declarations(items, fields, path):
    if type(items) is not list or len(items) > 4096:
        raise ProfileError(f'{path}: expected bounded declaration list')
    seen = set()
    for item in items:
        _keys(item, fields | {'id', 'required', 'support'}, path)
        if set(item) != fields | {'id', 'required', 'support'}:
            raise ProfileError(f'{path}: missing declaration fields')
        _nonsecret(item['id'], r'[A-Za-z0-9][A-Za-z0-9_.:+!-]{0,209}', path + '.id')
        if item['id'] in seen or type(item['required']) is not bool or item['support'] != 'unsupported':
            raise ProfileError(f'{path}: invalid identity or required/support declaration')
        seen.add(item['id'])
    return items


def _note_text(value, path):
    _nonsecret(value, r'[A-Za-z0-9][A-Za-z0-9 .,_()/-]{0,255}', path)
    if re.search(r'(?i)\b(password|secret|credential|token|bearer)\b', value):
        raise ProfileError(f'{path}: sensitive-looking text refused')


def _url_text(value, path):
    _nonsecret(value, r'(?:https|ssh)://[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?/[A-Za-z0-9_./~-]+', path, maximum=2048)
    authority, url_path = value.split('://', 1)[1].split('/', 1)
    if ':' in authority and not 1 <= int(authority.rsplit(':', 1)[1]) <= 65535:
        raise ProfileError(f'{path}: invalid port')
    if any(p in ('', '.', '..') for p in url_path.split('/')):
        raise ProfileError(f'{path}: invalid URL path')


def _repositories(items):
    fields = {'root', 'git_dir', 'common_dir', 'head', 'remotes', 'submodules', 'dirty', 'pin_provenance'}
    if type(items) is not list or len(items) > 4096:
        raise ProfileError('repositories: expected bounded declaration list')
    repository_ids = set()
    for item in items:
        _declarations([item], fields | ({'component'} if type(item) is dict and 'component' in item else set()), 'repositories')
        if item.get('component') is not None and not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', str(item.get('component'))):
            raise ProfileError('repositories.component: unsupported association')
        if item['id'] in repository_ids:
            raise ProfileError('repositories: duplicate identity')
        repository_ids.add(item['id'])
        for key in ('root', 'git_dir', 'common_dir'):
            _path_text(item[key], 'repositories.' + key)
        _keys(item['head'], {'ref', 'commit'}, 'repositories.head')
        if set(item['head']) != {'ref', 'commit'}:
            raise ProfileError('repositories.head: ref and commit required')
        if item['head']['ref'] is not None:
            _ref(item['head']['ref'], 'repositories.head.ref')
        _text(item['head']['commit'], r'(?:[0-9a-f]{40}|[0-9a-f]{64})', 'repositories.head.commit', nullable=True)
        for key in ('remotes', 'submodules'):
            entries = item[key]
            if type(entries) is not list or len(entries) > 1024:
                raise ProfileError('repositories: expected bounded metadata list')
            seen = set()
            for entry in entries:
                keys = {'name', 'url'} | ({'path'} if key == 'submodules' else set())
                _keys(entry, keys, 'repositories.' + key)
                if set(entry) != keys:
                    raise ProfileError('repositories: incomplete metadata')
                _nonsecret(entry['name'], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', 'repositories.name')
                if entry['name'] in seen:
                    raise ProfileError('repositories: duplicate identity')
                seen.add(entry['name'])
                _url_text(entry['url'], 'repositories.url')
                if key == 'submodules':
                    _nonsecret(entry['path'], r'[A-Za-z0-9_][A-Za-z0-9_./ -]*', 'repositories.submodules.path')
                    if any(p in ('', '.', '..') for p in entry['path'].split('/')):
                        raise ProfileError('repositories.submodules.path: traversal forbidden')
        if item['dirty'] != 'unknown' or item['pin_provenance'] != 'selected-head-only':
            raise ProfileError('repositories: unverified working state cannot claim reproducibility')


def _validate(data, overlay=False):
    allowed = {'schema_version', 'kind', 'name', 'extends', 'target', 'components', 'runtimes', 'serving',
               'defaults', 'draft', 'workspace', 'custom_dependencies', 'environments', 'notes', 'repositories'}
    if overlay:
        allowed -= {'schema_version', 'kind', 'name', 'extends', 'defaults', 'draft'}
    _keys(data, allowed, 'profile')
    if overlay:
        data = {'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'overlay', **data}
    if data.get('kind') != 'workstation-profile':
        raise ProfileError('Expected desired workstation-profile; baselines/legacy profiles unsupported')
    if data.get('schema_version') != 'v1alpha1':
        raise ProfileError('Unsupported schema_version')
    if not isinstance(data.get('name'), str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', data['name']):
        raise ProfileError('Invalid profile name')
    if 'target' in data and data['target'] != 'offline':
        raise ProfileError('Unsupported adapter: only offline resolution is available')
    if 'extends' in data and data['extends'] not in PRESETS:
        raise ProfileError('extends must select one public preset')
    if 'defaults' in data and data['defaults'] is not False:
        raise ProfileError('defaults: only explicit false is supported')
    if 'draft' in data and type(data['draft']) is not bool:
        raise ProfileError('draft must be boolean')
    if (data.get('draft') or data.get('defaults') is False) and 'extends' in data:
        raise ProfileError('Self-contained drafts cannot inherit presets')
    if 'workspace' in data:
        _workspace(data['workspace'])
    if 'custom_dependencies' in data:
        _custom_dependencies(data['custom_dependencies'])
    if 'environments' in data:
        for item in _declarations(data['environments'], {'name', 'manager', 'python', 'placement', 'location'}, 'environments'):
            _nonsecret(item['name'], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', 'environments.name')
            if item['manager'] not in ('uv', 'conda', 'venv', 'system', 'project', 'unknown'):
                raise ProfileError('environments.manager: unsupported manager')
            if item['placement'] not in ('host', 'container', 'environment', 'project', 'unknown'):
                raise ProfileError('environments.placement: unsupported placement')
            _nonsecret(item['python'], r'[0-9][0-9.]{0,31}', 'environments.python', nullable=True)
            _path_text(item['location'], 'environments.location')
    if 'notes' in data:
        for item in _declarations(data['notes'], {'text'}, 'notes'):
            _note_text(item['text'], 'notes.text')
    if 'repositories' in data:
        _repositories(data['repositories'])
    if 'components' in data:
        if type(data['components']) is not dict:
            raise ProfileError('components: expected mapping with supported keys only')
        for name, value in data['components'].items():
            if type(name) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name):
                raise ProfileError(f'components: expected mapping with supported keys only')
            _keys(value, {'enabled', 'runtime', 'source', 'execution', 'install', 'desktop_shortcut', 'dependencies', 'upstream', 'install_dir'}, f'components.{name}')
            if 'execution' in value and value['execution'] != 'native':
                raise ProfileError(f'components.{name}.execution: only native intent supported')
            if 'enabled' in value and type(value['enabled']) is not bool:
                raise ProfileError(f'components.{name}.enabled must be boolean')
            if 'runtime' in value:
                expected_runtime = COMPONENT_RUNTIME.get(name)
                if expected_runtime is not None and value['runtime'] != expected_runtime:
                    raise ProfileError(f'components.{name}.runtime: unsupported runtime binding')
                elif expected_runtime is None and value['runtime'] not in RUNTIMES and value['runtime'] not in data.get('runtimes', {}):
                    raise ProfileError(f'components.{name}.runtime: unsupported runtime binding')
            if 'dependencies' in value:
                if type(value['dependencies']) is not list or any(type(d) is not str for d in value['dependencies']):
                    raise ProfileError(f'components.{name}.dependencies: expected list of string component names')
            if 'install' in value:
                _keys(value['install'], {'method', 'command'}, f'components.{name}.install')
            if 'desktop_shortcut' in value:
                _keys(value['desktop_shortcut'], {'name', 'exec', 'icon'}, f'components.{name}.desktop_shortcut')
            if 'upstream' in value:
                _url_text(value['upstream'], f'components.{name}.upstream')
            if 'install_dir' in value:
                _path_text(value['install_dir'], f'components.{name}.install_dir')
            if 'source' in value:
                source = value['source']
                git_source = type(source) is dict and (source.get('mode') == 'git' or
                    (overlay and 'mode' not in source and bool(set(source) & {'repository', 'ref', 'revision'})))
                mode = 'standalone' if name == 'sim' and not git_source else 'git'
                _source(source, f'components.{name}.source', mode)
    if 'runtimes' in data:
        _keys(data['runtimes'], RUNTIMES, 'runtimes')
        for name, value in data['runtimes'].items():
            _keys(value, {'manager', 'environment', 'python', 'torch', 'torchvision', 'cuda_runtime', 'architecture'}, f'runtimes.{name}')
            for key, item in value.items():
                path = f'runtimes.{name}.{key}'
                if key == 'manager':
                    if item != RUNTIME_MANAGERS[name]:
                        raise ProfileError(f'{path}: unsupported environment manager')
                elif key == 'environment':
                    _text(item, r'[a-z][a-z0-9_-]{0,63}', path)
                    if item == 'base':
                        raise ProfileError(f'{path}: base environment forbidden')
                else:
                    patterns = {
                        'architecture': r'sm_[0-9]{2,3}',
                        'python': r'[0-9]+\.[0-9]+(?:\.[0-9]+)?',
                        'cuda_runtime': r'[0-9]+\.[0-9]+(?:\.[0-9]+)?',
                        'torch': r'[0-9]+\.[0-9]+\.[0-9]+(?:\+cu[0-9]+)?',
                        'torchvision': r'[0-9]+\.[0-9]+\.[0-9]+(?:\+cu[0-9]+)?',
                    }
                    pattern = patterns[key]
                    _text(item, pattern, path, nullable=True)
    if 'serving' in data:
        _keys(data['serving'], {'enabled', 'bind', 'port', 'embodiment', 'model'}, 'serving')
        for key, value in data['serving'].items():
            if key == 'enabled' and type(value) is not bool:
                raise ProfileError('serving.enabled must be boolean')
            if key == 'bind' and value != '127.0.0.1':
                raise ProfileError('serving.bind: only loopback supported')
            if key == 'port' and (type(value) is not int or not 1 <= value <= 65535):
                raise ProfileError('serving.port must be an integer in 1..65535')
            if key == 'embodiment':
                _text(value, r'[A-Z][A-Z0-9_]{0,63}', 'serving.embodiment')
            if key == 'model':
                _source(value, 'serving.model', 'model')


def parse_profile_text(text: str | bytes) -> dict:
    """Parse bounded, already-read YAML without filesystem or preset access."""
    try:
        if type(text) not in (str, bytes):
            raise ProfileError('Expected YAML text or UTF-8 bytes')
        raw = text.encode('utf-8') if isinstance(text, str) else text
        if len(raw) > 131072:
            raise ProfileError('Profile exceeds 128 KiB limit')
        text = raw.decode('utf-8')
        if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for t in yaml.scan(text)):
            raise ProfileError('YAML anchors and aliases unsupported')
        data = yaml.load(text, Loader=_StrictLoader)
        _validate(data)
        return data
    except ProfileError:
        raise
    except (ValueError, yaml.YAMLError, TypeError, RecursionError):
        raise ProfileError('Cannot parse a valid workstation YAML document') from None


def load_profile(name_or_path: str | Path) -> dict:
    """Read a desired document; resolution is a separate operation."""
    try:
        path = PROFILE_DIR / f'{name_or_path}.yaml' if str(name_or_path) in PRESETS else Path(name_or_path)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ProfileError('Profile must be a regular local file')
        with path.open('rb') as stream:
            raw = stream.read(131073)
        return parse_profile_text(raw)
    except ProfileError:
        raise
    except (OSError, ValueError, yaml.YAMLError, TypeError, RecursionError):
        raise ProfileError('Cannot read a valid workstation YAML document') from None


def list_profiles() -> list[str]:
    """Return public preset names only, without scanning private directories."""
    return list(PRESETS)


def _merge(target, overlay, provenance, label, prefix=''):
    # A new selector cannot silently reuse the prior selector's asserted pin.
    if prefix.endswith('.source') or prefix == 'serving.model':
        if ('mode' in overlay and target.get('mode') is not None
                and overlay['mode'] != target['mode']):
            target.clear()
            for key in list(provenance):
                if key.startswith(prefix + '.'):
                    del provenance[key]
        if ('repository' in overlay and overlay['repository'] != target.get('repository')
                and _commit_ref(target.get('ref'))
                and 'ref' not in overlay and not overlay.get('revision')):
            raise ProfileError(f'{prefix}: repository change requires explicit ref or revision for inherited immutable ref')
        pin = 'sha256' if prefix == 'components.sim.source' and overlay.get('mode', target.get('mode')) != 'git' else 'revision'
        changed = any(k in overlay and overlay[k] != target.get(k) for k in ('ref', 'repository', 'version', 'url'))
        if changed and pin not in overlay and pin in target:
            target[pin] = None
            provenance[f'{prefix}.{pin}'] = label
    for key, value in overlay.items():
        if key == 'extends':
            continue
        path = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            _merge(target.setdefault(key, {}), value, provenance, label, path)
        else:
            target[key] = deepcopy(value)
            provenance[path] = label


class ComponentDAGResolver:
    """Sorts components into strict dependency order using Kahn's topological sort."""

    @staticmethod
    def resolve_order(components: list[dict]) -> list[dict]:
        comp_map = {c['id']: c for c in components}
        in_degree = {c['id']: 0 for c in components}
        graph = {c['id']: [] for c in components}

        for c in components:
            deps = c.get('dependencies', [])
            for dep in deps:
                if dep in comp_map:
                    graph[dep].append(c['id'])
                    in_degree[c['id']] += 1

        queue = [cid for cid, deg in in_degree.items() if deg == 0]
        sorted_ids = []

        while queue:
            curr = queue.pop(0)
            sorted_ids.append(curr)
            for neighbor in graph[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_ids) != len(components):
            cycle_nodes = [cid for cid, deg in in_degree.items() if deg > 0]
            raise ProfileError(f'Circular dependency detected between components: {cycle_nodes}')

        return [comp_map[cid] for cid in sorted_ids]


def _dependencies(profile):
    components = profile.get('components', {})
    for name, dependencies in DEPENDENCIES.items():
        if components.get(name, {}).get('enabled'):
            for dependency in dependencies:
                if not components.get(dependency, {}).get('enabled'):
                    raise ProfileError(f'components.{name} requires enabled {dependency}')
    for name, comp in components.items():
        if comp.get('enabled') and 'dependencies' in comp:
            for dep in comp['dependencies']:
                if not components.get(dep, {}).get('enabled'):
                    raise ProfileError(f'components.{name} requires enabled {dep}')
    if profile.get('serving', {}).get('enabled') and not components.get('gr00t', {}).get('enabled'):
        raise ProfileError('serving requires enabled gr00t')
    environments = [runtime['environment'] for runtime in profile.get('runtimes', {}).values() if 'environment' in runtime]
    if len(environments) != len(set(environments)):
        raise ProfileError('Runtime environments must be isolated; only Arena shares Lab')


def _reference_report(profile):
    references, unresolved = {}, []
    sources = [(f'components.{name}', c.get('source', {}), c.get('enabled', False))
               for name, c in profile.get('components', {}).items()]
    serving = profile.get('serving', {})
    if serving:
        sources.append(('serving.model', serving.get('model', {}), serving.get('enabled', False)))
    for path, source, enabled in sources:
        content_id = source.get('revision', source.get('sha256'))
        if not content_id:
            content_id = _commit_ref(source.get('ref'))
        status = ('resolved' if content_id else 'unresolved') if enabled else 'not_selected'
        references[path] = {'status': status, 'requested': source.get('ref', source.get('version')),
                            'content_id': content_id if enabled else None, 'verified': False}
        if status == 'unresolved':
            unresolved.append({'field': path, 'reason': 'immutable_reference_required'})
    selected_runtimes = {c['runtime'] for c in profile.get('components', {}).values()
                         if c.get('enabled') and 'runtime' in c}
    for name in sorted(selected_runtimes):
        path = f'runtimes.{name}'
        unresolved.append({'field': path, 'reason': 'compatibility_unverified'})
        for key, value in profile.get('runtimes', {}).get(name, {}).items():
            if value is None:
                unresolved.append({'field': f'{path}.{key}', 'reason': 'not_pinned'})
    return references, unresolved


def resolve_profile(name_or_path: str | Path, overrides: dict | None = None) -> dict:
    """Resolve public defaults/preset/file/explicit overrides without execution."""
    selected = load_profile(name_or_path)
    presets = {}
    if selected.get('defaults') is not False and not selected.get('draft'):
        presets['default'] = load_profile('default')
    if 'extends' in selected:
        presets[selected['extends']] = load_profile(selected['extends'])
    label = f'preset:{name_or_path}' if str(name_or_path) in PRESETS else 'profile'
    return resolve_document(selected, presets=presets, overrides=overrides, label=label)


def resolve_document(selected: dict, *, presets: dict | None = None,
                     overrides: dict | None = None, label: str = 'profile') -> dict:
    """Pure resolution with explicitly preloaded trusted public presets.

    Confined callers load public presets before sandbox entry and pass them here.
    No missing preset is ever fetched, opened or substituted by this function.
    """
    _validate(selected)
    overrides = {} if overrides is None else overrides
    _validate(overrides, overlay=True)
    presets = {} if presets is None else presets

    def preset(name):
        if type(presets) is not dict or name not in presets:
            raise ProfileError('Required public preset was not preloaded')
        parent = presets[name]
        _validate(parent)
        if 'extends' in parent:
            raise ProfileError('Recursive preset inheritance unsupported')
        return parent

    result, provenance = {}, {}
    if selected.get('defaults') is not False and not selected.get('draft'):
        _merge(result, preset('default'), provenance, 'defaults')
    if 'extends' in selected:
        name = selected['extends']
        _merge(result, preset(name), provenance, f'preset:{name}')
    _merge(result, selected, provenance, label)
    _merge(result, overrides, provenance, 'overrides')
    return resolve_profile_data(result, provenance=provenance)


def resolve_profile_data(profile: dict, *, provenance: dict | None = None) -> dict:
    """Resolve only supplied intent, never inherit or read presets."""
    _validate(profile)
    if 'extends' in profile:
        raise ProfileError('Pure resolution requires expanded inheritance')
    result, labels = {}, {}
    _merge(result, profile, labels, 'profile')
    provenance = deepcopy(provenance) if provenance is not None else labels
    dependency_gaps = []
    try:
        _dependencies(result)
    except ProfileError:
        if not result.get('draft'):
            raise
        dependency_gaps.append({'field': 'dependencies', 'reason': 'dependency_intent_unresolved'})
    serving = result.get('serving', {})
    endpoint = (f"tcp://{serving['bind']}:{serving['port']}"
                if serving.get('enabled') and 'bind' in serving and 'port' in serving else None)
    references, unresolved = _reference_report(result)
    unresolved.extend(dependency_gaps)
    if result.get('draft'):
        unresolved.append({'field': 'profile', 'reason': 'draft_intent_unresolved'})
    canonical = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return {'schema_version': 'v1alpha1', 'kind': 'workstation-resolved',
            'profile': result, 'provenance': provenance, 'endpoint': endpoint,
            'digest': 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
            'references': references, 'unresolved': unresolved,
            'adapter': {'name': 'offline', 'apply_supported': False}, 'ready_for_apply': False,
            'dependencies': {'components': deepcopy(DEPENDENCIES),
                             'runtimes': deepcopy(COMPONENT_RUNTIME), 'serving': ['gr00t']}}


def validate_profile(name_or_path: str | Path) -> dict:
    """Validation is offline resolution, never installation or acceptance."""
    return resolve_profile(name_or_path)
