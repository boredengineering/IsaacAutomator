"""Pure offline workstation software intent; no deployment imports or execution."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re
import stat

import yaml


class ProfileError(ValueError):
    """Invalid or unsupported non-executable workstation profile."""


PRESETS = ('default', 'full', 'minimal')
COMPONENTS = ('sim', 'lab', 'arena', 'gr00t', 'lerobot')
RUNTIMES = ('kit', 'lab', 'gr00t', 'lerobot')
RUNTIME_MANAGERS = {'kit': 'bundled', 'lab': 'conda', 'gr00t': 'uv', 'lerobot': 'conda'}
PROFILE_DIR = Path(__file__).resolve().parents[2] / 'configs' / 'workstations'
COMPONENT_RUNTIME = {'sim': 'kit', 'lab': 'lab', 'arena': 'lab', 'gr00t': 'gr00t', 'lerobot': 'lerobot'}
DEPENDENCIES = {'sim': [], 'lab': ['sim'], 'arena': ['lab'], 'gr00t': [], 'lerobot': []}


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


def _text(value, pattern, path, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not str or len(value) > 256 or not re.fullmatch(pattern, value):
        raise ProfileError(f'{path}: invalid nonsecret value')


def _ref(value, path):
    _text(value, r'[A-Za-z0-9][A-Za-z0-9._/-]*', path)
    if '..' in value or any(not p or p.startswith('.') or p.endswith(('.', '.lock')) for p in value.split('/')):
        raise ProfileError(f'{path}: invalid Git ref')


def _source(value, path, mode):
    if mode == 'standalone':
        _keys(value, {'mode', 'version', 'sha256'}, path)
        if 'version' in value:
            _text(value['version'], r'[0-9]+\.[0-9]+\.[0-9]+', path + '.version')
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
        if isinstance(ref, str) and re.fullmatch(r'[0-9a-f]{40}', ref) and revision and revision != ref:
            raise ProfileError(f'{path}: conflicting immutable selectors')
    if 'mode' in value and value['mode'] != mode:
        raise ProfileError(f'{path}.mode: unsupported source mode')


def _validate(data, overlay=False):
    allowed = {'schema_version', 'kind', 'name', 'extends', 'target', 'components', 'runtimes', 'serving'}
    if overlay:
        allowed -= {'schema_version', 'kind', 'name', 'extends'}
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
    if 'components' in data:
        _keys(data['components'], COMPONENTS, 'components')
        for name, value in data['components'].items():
            _keys(value, {'enabled', 'runtime', 'source', 'execution'}, f'components.{name}')
            if 'execution' in value and value['execution'] != 'native':
                raise ProfileError(f'components.{name}.execution: only native intent supported')
            if 'enabled' in value and type(value['enabled']) is not bool:
                raise ProfileError(f'components.{name}.enabled must be boolean')
            if 'runtime' in value and value['runtime'] != COMPONENT_RUNTIME[name]:
                raise ProfileError(f'components.{name}.runtime: unsupported runtime binding')
            if 'source' in value:
                _source(value['source'], f'components.{name}.source', 'standalone' if name == 'sim' else 'git')
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


def load_profile(name_or_path: str | Path) -> dict:
    """Read a desired document; resolution is a separate operation."""
    try:
        path = PROFILE_DIR / f'{name_or_path}.yaml' if str(name_or_path) in PRESETS else Path(name_or_path)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ProfileError('Profile must be a regular local file')
        with path.open('rb') as stream:
            raw = stream.read(131073)
        if len(raw) > 131072:
            raise ProfileError('Profile exceeds 128 KiB limit')
        text = raw.decode('utf-8')
        if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for t in yaml.scan(text)):
            raise ProfileError('YAML anchors and aliases unsupported')
        data = yaml.load(text, Loader=_StrictLoader)
    except ProfileError:
        raise
    except (OSError, ValueError, yaml.YAMLError, TypeError, RecursionError):
        raise ProfileError('Cannot read a valid workstation YAML document') from None
    _validate(data)
    return data


def list_profiles() -> list[str]:
    """Return public preset names only, without scanning private directories."""
    return list(PRESETS)


def _merge(target, overlay, provenance, label, prefix=''):
    # A new selector cannot silently reuse the prior selector's asserted pin.
    if prefix.endswith('.source') or prefix == 'serving.model':
        if ('repository' in overlay and overlay['repository'] != target.get('repository')
                and re.fullmatch(r'[0-9a-f]{40}', target.get('ref', ''))
                and 'ref' not in overlay and not overlay.get('revision')):
            raise ProfileError(f'{prefix}: repository change requires explicit ref or revision for inherited immutable ref')
        pin = 'sha256' if prefix == 'components.sim.source' else 'revision'
        changed = any(k in overlay and overlay[k] != target.get(k) for k in ('ref', 'repository', 'version'))
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


def _dependencies(profile):
    components = profile['components']
    for name, dependencies in DEPENDENCIES.items():
        if components[name]['enabled']:
            for dependency in dependencies:
                if not components[dependency]['enabled']:
                    raise ProfileError(f'components.{name} requires enabled {dependency}')
    if profile['serving']['enabled'] and not components['gr00t']['enabled']:
        raise ProfileError('serving requires enabled gr00t')
    environments = [runtime['environment'] for runtime in profile['runtimes'].values()]
    if len(environments) != len(set(environments)):
        raise ProfileError('Runtime environments must be isolated; only Arena shares Lab')


def _reference_report(profile):
    references, unresolved = {}, []
    sources = [(f'components.{name}', c['source'], c['enabled']) for name, c in profile['components'].items()]
    sources.append(('serving.model', profile['serving']['model'], profile['serving']['enabled']))
    for path, source, enabled in sources:
        content_id = source.get('revision', source.get('sha256'))
        if not content_id and re.fullmatch(r'[0-9a-f]{40}', source.get('ref', '')):
            content_id = source['ref']
        status = ('resolved' if content_id else 'unresolved') if enabled else 'not_selected'
        references[path] = {'status': status, 'requested': source.get('ref', source.get('version')),
                            'content_id': content_id if enabled else None, 'verified': False}
        if status == 'unresolved':
            unresolved.append({'field': path, 'reason': 'immutable_reference_required'})
    selected_runtimes = {c['runtime'] for c in profile['components'].values() if c['enabled']}
    for name in sorted(selected_runtimes):
        path = f'runtimes.{name}'
        unresolved.append({'field': path, 'reason': 'compatibility_unverified'})
        for key, value in profile['runtimes'][name].items():
            if value is None:
                unresolved.append({'field': f'{path}.{key}', 'reason': 'not_pinned'})
    return references, unresolved


def resolve_profile(name_or_path: str | Path, overrides: dict | None = None) -> dict:
    """Resolve public defaults/preset/file/explicit overrides without execution."""
    selected = load_profile(name_or_path)
    if overrides is None:
        overrides = {}
    _validate(overrides, overlay=True)
    result, provenance = {}, {}
    _merge(result, load_profile('default'), provenance, 'defaults')
    if 'extends' in selected:
        preset = selected['extends']
        parent = load_profile(preset)
        if 'extends' in parent:
            raise ProfileError('Recursive preset inheritance unsupported')
        _merge(result, parent, provenance, f'preset:{preset}')
    label = f'preset:{name_or_path}' if str(name_or_path) in PRESETS else 'profile'
    _merge(result, selected, provenance, label)
    _merge(result, overrides, provenance, 'overrides')
    _validate(result)
    _dependencies(result)
    serving = result['serving']
    endpoint = f"tcp://{serving['bind']}:{serving['port']}" if serving['enabled'] else None
    references, unresolved = _reference_report(result)
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
