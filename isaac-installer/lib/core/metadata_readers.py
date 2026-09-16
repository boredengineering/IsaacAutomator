"""Small non-executing readers for explicitly selected, bounded metadata.

Caller supplies descriptor-safe reads and a shared budget; this is not a sandbox.
No observed code is imported and no subprocess, object, index or diff is read.
"""
import os
import json
import re
from urllib.parse import urlsplit

# Load only trusted interpreter dependencies before callers install confinement.
try:
    import tomllib as _toml
except ImportError:
    try:
        import tomli as _toml
    except ImportError:
        _toml = None


class MetadataError(ValueError):
    """A fixed, nonsecret reason code; never include untrusted input."""


def text(value, pattern=r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', maximum=64):
    if (type(value) is not str or len(value) > maximum or not re.fullmatch(pattern, value)
            or re.search(r'(?i)(?:token|password|secret|credential|bearer)[=_:-]|gh[pousr]_|sk-', value)):
        raise MetadataError('invalid_metadata')
    return value


def shape(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise MetadataError('invalid_metadata')


def validate_repository(value, path):
    shape(value, {'root', 'git_dir', 'common_dir', 'head', 'remotes', 'submodules', 'dirty', 'pin_provenance', 'component'})
    if value['component'] is not None and value['component'] not in ('lab', 'arena', 'gr00t', 'lerobot'):
        raise MetadataError('invalid_metadata')
    for key in ('root', 'git_dir', 'common_dir'):
        path(value[key])
    shape(value['head'], {'ref', 'commit'})
    if value['head']['ref'] is not None:
        text(value['head']['ref'], r'refs/[A-Za-z0-9_./-]+', 256)
    if value['head']['commit'] is not None:
        text(value['head']['commit'], r'(?:[0-9a-f]{40}|[0-9a-f]{64})', 64)
    for key in ('remotes', 'submodules'):
        if type(value[key]) is not list or len(value[key]) > 1024:
            raise MetadataError('invalid_metadata')
        seen = set()
        for entry in value[key]:
            shape(entry, {'name', 'url', 'path'} if key == 'submodules' else {'name', 'url'})
            text(entry['name'])
            if entry['name'] in seen or sanitize_url(entry['url']) != entry['url']:
                raise MetadataError('invalid_metadata')
            seen.add(entry['name'])
            if key == 'submodules':
                relative_path(entry['path'])
    if value['dirty'] != 'unknown' or value['pin_provenance'] != 'selected-head-only':
        raise MetadataError('invalid_metadata')


def repository_value(selected):
    return {key: selected[key] for key in ('root', 'git_dir', 'common_dir')} | {
        'head': {'ref': None, 'commit': None}, 'remotes': [], 'submodules': [],
        'dirty': 'unknown', 'pin_provenance': 'selected-head-only', 'component': selected.get('component')}


def validate_component_source(value):
    shape(value, {'mode', 'repository', 'ref', 'revision'})
    if value['mode'] != 'git':
        raise MetadataError('invalid_metadata')
    text(value['repository'], r'https://github\.com/[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.git', 256)
    text(value['ref'], r'[0-9a-f]{40}', 40)
    if value['revision'] != value['ref']:
        raise MetadataError('invalid_metadata')


def component_source(value):
    origins = [r for r in value['remotes'] if r['name'] == 'origin']
    if len(origins) != 1 or value['head']['commit'] is None:
        return None
    source = {'mode': 'git', 'repository': origins[0]['url'],
              'ref': value['head']['commit'], 'revision': value['head']['commit']}
    try:
        validate_component_source(source)
    except ValueError:
        return None
    return source


def relative_path(value):
    text(value, r'[A-Za-z0-9_][A-Za-z0-9_./ -]*', 256)
    if any(p in ('', '.', '..') for p in value.split('/')) or len(value.split('/')) > 16:
        raise MetadataError('invalid_metadata')
    return value


def sanitize_url(value):
    if type(value) is not str or len(value) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise MetadataError('invalid_metadata')
    if '://' not in value:
        match = re.fullmatch(r'(?:[^/@:]+@)?([A-Za-z0-9.-]+):([A-Za-z0-9_./-]+)', value)
        if not match:
            raise MetadataError('invalid_metadata')
        value = 'ssh://' + match[1] + '/' + match[2]
    parsed = urlsplit(value)
    if parsed.scheme not in ('https', 'ssh') or not parsed.hostname:
        raise MetadataError('invalid_metadata')
    host = text(parsed.hostname, r'[A-Za-z0-9][A-Za-z0-9.-]*', 253)
    path = text(parsed.path, r'/[A-Za-z0-9_./~-]+', 1024)
    if any(part in ('', '.', '..') for part in path.split('/')[1:]):
        raise MetadataError('invalid_metadata')
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise MetadataError('invalid_metadata')
    return parsed.scheme + '://' + host + (':' + str(port) if port else '') + path


def _config_records(raw, wanted, consume):
    # Deliberately NOT Git/configparser: no interpolation, includes, helpers or
    # general configuration evaluation. Only literal sections/keys are admitted.
    if any(ord(c) < 32 and c not in '\n\t' or ord(c) > 126 for c in raw):
        raise MetadataError('invalid_metadata')
    records, section, name = {}, None, None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('['):
            match = re.fullmatch(r'\[([A-Za-z][A-Za-z0-9-]*)(?: "([^"\\]+)")?\]', line)
            if not match:
                raise MetadataError('invalid_metadata')
            section, name = match[1].lower(), match[2]
            if section in ('include', 'includeif'):
                raise MetadataError('config_include_refused')
            if section == wanted:
                text(name)
                if name in records:
                    raise MetadataError('invalid_metadata')
                records[name] = {}
            continue
        if section == 'extensions' and re.match(r'(?i)worktreeconfig(?:\s|=|$)', line):
            raise MetadataError('worktree_config_unsupported')
        if section == wanted:
            key, sep, value = line.partition('=')
            key = key.strip().lower()
            if not sep:
                raise MetadataError('invalid_metadata')
            if key not in ('url', 'path'):
                continue
            if key in records[name]:
                raise MetadataError('invalid_metadata')
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            records[name][key] = sanitize_url(value) if key == 'url' else relative_path(value)
    output = []
    for name, values in sorted(records.items()):
        consume()
        shape(values, {'url', 'path'} if wanted == 'submodule' else {'url'})
        output.append({'name': name, **values})
    return output


def note(value):
    text(value, r'[A-Za-z0-9][A-Za-z0-9 .,_()/-]{0,255}', 256)
    if re.search(r'(?i)\b(password|secret|credential|token|bearer)\b', value):
        raise MetadataError('invalid_metadata')
    return value


def validate_tool(value, path=None, *, allow_unbound_location=False):
    keys = {'name', 'version', 'source', 'purpose'}
    shape(value, keys | ({'environment', 'placement', 'location'} if path else set()))
    text(value['name'], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', 128)
    if value['version'] is not None:
        text(value['version'], r'[0-9][A-Za-z0-9_.+!-]{0,63}', 64)
    if value['source'] not in (None, 'pypi') and sanitize_url(value['source']) != value['source']:
        raise MetadataError('invalid_metadata')
    if value['purpose'] is not None:
        note(value['purpose'])
    if path:
        text(value['environment'])
        placement(value['placement'])
        if value['location'] is not None or not allow_unbound_location:
            path(value['location'])


def placement(value):
    if type(value) is not str or value not in ('host', 'container', 'environment', 'project', 'unknown'):
        raise MetadataError('invalid_metadata')


def validate_environment(value, path=None):
    shape(value, {'name', 'manager', 'placement', 'python'} | ({'location'} if path else {'tools', 'notes', 'runtime'}))
    text(value['name'])
    placement(value['placement'])
    if value['manager'] not in ('uv', 'conda', 'venv', 'system', 'project', 'unknown'):
        raise MetadataError('invalid_metadata')
    if value['python'] is not None:
        text(value['python'], r'[0-9][0-9.]{0,31}', 32)
    if path:
        path(value['location'])
    else:
        if value['runtime'] is not None and value['runtime'] not in ('lab', 'gr00t', 'lerobot'):
            raise MetadataError('invalid_metadata')
        if any(type(value[k]) is not list or len(value[k]) > 1024 for k in ('tools', 'notes')):
            raise MetadataError('invalid_metadata')
        seen = set()
        for tool in value['tools']:
            validate_tool(tool)
            key = re.sub(r'[-_.]+', '-', tool['name']).lower()
            if key in seen:
                raise MetadataError('invalid_metadata')
            seen.add(key)
        for line in value['notes']:
            note(line)


def validate_runtime(value, runtime):
    shape(value, {'manager', 'environment'} | ({'python'} if type(value) is dict and 'python' in value else set()))
    if value['manager'] != {'lab': 'conda', 'gr00t': 'uv', 'lerobot': 'conda'}[runtime]:
        raise MetadataError('invalid_metadata')
    text(value['environment'])
    if 'python' in value:
        text(value['python'], r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', 32)


def runtime_value(value):
    result = {'manager': value['manager'], 'environment': value['name']}
    if value['python'] is not None:
        result['python'] = value['python']
    try:
        validate_runtime(result, value['runtime'])
    except ValueError:
        return None
    return result


def environment_value(selected):
    return {'name': selected['environment'], 'manager': 'unknown', 'placement': selected['placement'],
            'python': None, 'tools': [], 'notes': [], 'runtime': selected.get('runtime')}


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MetadataError('invalid_metadata')
        result[key] = value
    return result


def _pyproject(data, selected):
    if type(data) is not dict or type(data.get('project')) is not dict:
        raise MetadataError('invalid_metadata')
    project = data['project']
    if project.get('dynamic'):
        raise MetadataError('dynamic_metadata_unsupported')
    tool = {'name': project.get('name'), 'version': project.get('version'), 'source': None, 'purpose': None}
    validate_tool(tool)
    tools = [tool]
    dependencies = project.get('dependencies', [])
    if type(dependencies) is not list:
        raise MetadataError('invalid_metadata')
    for dependency in dependencies:
        text(dependency, r'[A-Za-z0-9][A-Za-z0-9_.+!<>=~, -]*', 256)
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)(.*)', dependency)
        suffix = match[2].strip()
        exact = re.fullmatch(r'==([0-9][A-Za-z0-9_.+!-]*)', suffix)
        if suffix and not exact and not re.fullmatch(r'[<>=!~]+[0-9][A-Za-z0-9_.+!<>=~, -]*', suffix):
            raise MetadataError('invalid_metadata')
        tools.append({'name': match[1], 'version': exact[1] if exact else None, 'source': None, 'purpose': None})
    return {'name': selected['environment'], 'manager': 'project', 'placement': selected['placement'],
            'python': None, 'tools': tools, 'notes': []}


def _uv_lock(data, selected):
    if type(data) is not dict or type(data.get('package')) is not list or type(data.get('version')) is not int or data['version'] != 1:
        raise MetadataError('invalid_metadata')
    tools = []
    for package in data['package']:
        if type(package) is not dict:
            raise MetadataError('invalid_metadata')
        source = package.get('source', {})
        if type(source) is not dict or len(source) > 1:
            raise MetadataError('invalid_metadata')
        url = None
        if source:
            kind, raw = next(iter(source.items()))
            if kind in ('registry', 'git', 'url'):
                url = sanitize_url(raw)
            elif kind not in ('editable', 'virtual', 'directory'):
                raise MetadataError('invalid_metadata')
            # Local source paths are neither traversed nor copied into output.
        tools.append({'name': package.get('name'), 'version': package.get('version'),
                      'source': url, 'purpose': None})
    return {'name': selected['environment'], 'manager': 'uv', 'placement': selected['placement'],
            'python': None, 'tools': tools, 'notes': []}


def read_environment(selected, read, value, consume):
    directory, name = os.path.split(selected['path'])
    raw = read(directory, name)
    if selected['format'] in ('pyproject', 'uv-lock'):
        if _toml is None:
            raise MetadataError('toml_unavailable')
        data = _toml.loads(raw)
    else:
        data = json.loads(raw, object_pairs_hook=_unique_json)
    if selected['format'] == 'pyproject':
        result = _pyproject(data, selected)
    elif selected['format'] in ('uv-lock', 'uv-lock-json'):
        result = _uv_lock(data, selected)
    else:
        shape(data, {'name', 'manager', 'python', 'tools', 'notes'})
        result = {**data, 'placement': selected['placement']}
    if result['name'] != selected['environment']:
        raise MetadataError('invalid_metadata')
    if type(result['tools']) is not list:
        raise MetadataError('invalid_metadata')
    for tool in result['tools']:
        consume()
        shape(tool, {'name', 'version', 'source', 'purpose'})
        if tool['source'] not in (None, 'pypi'):
            tool['source'] = sanitize_url(tool['source'])
        validate_tool(tool)
    if type(result['notes']) is not list:
        raise MetadataError('invalid_metadata')
    for line in result['notes']:
        consume()
        note(line)
    result['runtime'] = selected.get('runtime')
    unique, conflicting = {}, set()
    for tool in result['tools']:
        key = re.sub(r'[-_.]+', '-', tool['name']).lower()
        comparable = {**tool, 'name': key}
        if key in unique and {**unique[key], 'name': key} != comparable:
            conflicting.add(key)
        unique.setdefault(key, tool)
    result['tools'] = [unique[k] for k in sorted(unique) if k not in conflicting]
    validate_environment(result)
    value.update(result)
    if conflicting:
        raise MetadataError('conflicting_tool_metadata')
    return value


def _optional(read, directory, name):
    try:
        return read(directory, name)
    except FileNotFoundError:
        return None


def _indirection(raw, base, expected):
    text(raw, r'[A-Za-z0-9_./ -]+', 4096)
    # Normalize only for comparison, never open the path from file contents.
    if os.path.normpath(os.path.join(base, raw)) != expected:
        raise MetadataError('indirection_not_selected')


def _packed_ref(raw, ref, consume):
    commit = None
    for line in raw.splitlines():
        if not line or line.startswith('#'):
            continue
        consume()
        if line.startswith('^'):
            text(line[1:], r'(?:[0-9a-f]{40}|[0-9a-f]{64})', 64)
            continue
        sha, separator, name = line.partition(' ')
        if not separator:
            raise MetadataError('invalid_metadata')
        text(sha, r'(?:[0-9a-f]{40}|[0-9a-f]{64})', 64)
        text(name, r'refs/[A-Za-z0-9_./-]+', 256)
        if name == ref:
            if commit is not None:
                raise MetadataError('invalid_metadata')
            commit = sha
    if commit is None:
        raise MetadataError('unresolved_ref')
    return commit


def read_git(selected, read, value, consume):
    root, git, common = (selected[k] for k in ('root', 'git_dir', 'common_dir'))
    if git != os.path.join(root, '.git'):
        marker = read(root, '.git')
        if not marker.startswith('gitdir: ') or len(marker.splitlines()) != 1:
            raise MetadataError('invalid_metadata')
        _indirection(marker[8:].rstrip('\n'), root, git)
    else:
        # Open the explicitly selected .git directory, never infer another root.
        pass
    common_marker = _optional(read, git, 'commondir')
    if common_marker is not None:
        if len(common_marker.splitlines()) != 1:
            raise MetadataError('invalid_metadata')
        _indirection(common_marker.rstrip('\n'), git, common)
    elif git != common:
        raise MetadataError('indirection_not_selected')
    raw = read(git, 'HEAD').rstrip('\n')
    if raw.startswith('ref: '):
        ref = text(raw[5:], r'refs/[A-Za-z0-9_./-]+', 256)
        if any(p in ('', '.', '..') for p in ref.split('/')):
            raise MetadataError('invalid_metadata')
        value['head']['ref'] = ref
        if ref not in selected['ref_paths']:
            raise MetadataError('ref_not_selected')
        loose = _optional(read, common, ref)
        raw = (loose.rstrip('\n') if loose is not None else
               _packed_ref(read(common, 'packed-refs'), ref, consume))
    value['head']['commit'] = text(raw, r'(?:[0-9a-f]{40}|[0-9a-f]{64})', 64)
    config = _optional(read, common, 'config')
    if config is not None:
        value['remotes'] = _config_records(config, 'remote', consume)
    modules = _optional(read, root, '.gitmodules')
    if modules is not None:
        value['submodules'] = _config_records(modules, 'submodule', consume)
    return value
