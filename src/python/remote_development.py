"""Offline selected synchronization and remote devcontainer candidates.

No function activates a remote transfer or daemon. Source/config are locally
owned; runtime artifacts flow back to a separate local output directory.
"""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
import fnmatch
import re
import shlex

from src.python.file_transfer import DEFAULT_EXCLUDES, TransferEndpoint
# Load shared schema during module setup, not inside pure plan evaluation.
from src.python.workstation_profile import _validate as _validate_profile

ENV_EXCLUDES = ('.venv/', 'venv/', 'env/', 'envs/', '__pycache__/', '*.pyc',
                '.cache/', '.pytest_cache/', '.mypy_cache/', 'node_modules/',
                '*.egg-info/', '.tox/', '.conda/', 'container-layers/',
                'databases/', '*.db', '*.db-*', '*.sqlite*', 'pgdata/', 'neo4j/',
                '.devcontainer/', '.vscode/', 'backups/', 'recovery/', '.rsync-partial/',
                '.git', '.netrc', '.stversions/', '.stfolder/')
ARTIFACT_EXCLUDES = ('datasets/', 'models/', 'checkpoints/', 'outputs/', 'logs/',
                     '*.pt', '*.pth', '*.h5', '*.safetensors', '*.onnx')


def _path(value, *, local=False):
    if (not isinstance(value, str) or not value.startswith('/') or value.startswith('//')
            or len(PurePosixPath(value).parts) < 3
            or any(ord(c) < 32 or c in ',\"\\:$%`*?[]' for c in value)
            or any(p in ('.', '..', '') for p in value[1:].split('/'))):
        raise ValueError('Select an absolute narrow literal path without traversal or delimiters')
    path = Path(value)
    if local:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Selected local path has a symlink component')
        if path.exists() and not path.is_dir():
            raise ValueError('Selected path must be a directory')
    return value


def _overlap(a, b):
    a, b = PurePosixPath(a.casefold()), PurePosixPath(b.casefold())
    return a == b or a in b.parents or b in a.parents


def _excluded_root(value, patterns):
    path = PurePosixPath(value.casefold())
    return any(fnmatch.fnmatchcase(str(prefix), '*/' + pattern.rstrip('/').casefold())
               for prefix in (path, *path.parents) for pattern in patterns)


def build_plan(spec) -> dict[str, Any]:
    """Validate explicit strings only; target metadata preflight is separate."""
    keys = {'engine', 'mappings', 'endpoint', 'image', 'delete', 'delete_approved',
            'overwrite_approved', 'initial_seed', 'conflict_policy', 'protected_paths',
            'desired_profile', 'runtime_placements'}
    if not isinstance(spec, dict) or set(spec) - keys:
        raise ValueError('Unknown development specification field')
    engine = spec.get('engine')
    if engine not in ('rsync', 'mutagen', 'syncthing'):
        raise ValueError('Choose an explicit engine: rsync, mutagen or syncthing')
    for key in ('delete', 'delete_approved', 'overwrite_approved'):
        if type(spec.get(key, False)) is not bool:
            raise ValueError('Approval and deletion fields must be boolean')
    delete = spec.get('delete', False)
    if delete and not spec.get('delete_approved', False):
        raise ValueError('Deletion requires separate delete_approved review')
    seed = spec.get('initial_seed', 'empty-target')
    if seed not in ('empty-target', 'reviewed-overwrite'):
        raise ValueError('Select an explicit initial seed policy')
    if seed == 'reviewed-overwrite' and not spec.get('overwrite_approved', False):
        raise ValueError('Overwrite requires separate overwrite_approved review')
    if spec.get('conflict_policy', 'stop') != 'stop':
        raise ValueError('Conflicts require stop and explicit review, not automatic resolution')
    raw = spec.get('mappings')
    if not isinstance(raw, list) or not raw or len(raw) > 100:
        raise ValueError('Select between 1 and 100 explicit mappings')
    protected = spec.get('protected_paths', [])
    if not isinstance(protected, list) or len(protected) > 1000:
        raise ValueError('Select at most 1000 protected paths')
    for entry in protected:
        if (not isinstance(entry, dict) or set(entry) != {'namespace', 'path'} or
                entry['namespace'] not in ('local', 'remote', 'container')):
            raise ValueError('Each protected path needs namespace and path')
        _path(entry['path'])
    mappings = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {'name', 'kind', 'local', 'remote', 'container'}:
            raise ValueError('Each mapping needs name, kind, local, remote and container only')
        if not isinstance(item['name'], str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}', item['name']):
            raise ValueError('Mapping name must be a safe unique identifier')
        if item['kind'] not in ('source', 'config', 'artifacts'):
            raise ValueError('Mapping kind must be source, config or artifacts')
        patterns = (*DEFAULT_EXCLUDES, *ENV_EXCLUDES,
                    *(() if item['kind'] == 'artifacts' else ARTIFACT_EXCLUDES))
        for field in ('local', 'remote', 'container'):
            _path(item[field])
            if _excluded_root(item[field], patterns):
                raise ValueError('Selected root is an excluded secret, state, environment or data store')
        for entry in protected:
            fields = (('local', 'remote') if spec.get('endpoint') is None and
                      entry['namespace'] in ('local', 'remote') else (entry['namespace'],))
            for field in fields:
                selected = PurePosixPath(entry['path'].casefold())
                root = PurePosixPath(item[field].casefold())
                if selected == root or selected in root.parents:
                    raise ValueError('Mapping is inside a selected protected path')
                if root in selected.parents:
                    # Use original case in engine patterns, and fail closed for
                    # ambiguous root casing rather than silently miss protection.
                    if not entry['path'].startswith(item[field] + '/'):
                        raise ValueError('Ambiguous casing in protected path')
                    relative = entry['path'][len(item[field]):]
                    patterns = (*patterns, relative)
        for prior in mappings:
            if item['name'].casefold() == prior['name'].casefold():
                raise ValueError('Duplicate mapping name')
            if any(_overlap(item[field], prior[field]) for field in ('local', 'remote', 'container')):
                raise ValueError('Mapping overlap: outputs and sources need separate folders')
        mappings.append(dict(item, direction='pull' if item['kind'] == 'artifacts' else 'push',
                             owner='remote-runtime' if item['kind'] == 'artifacts' else 'local',
                             excludes=list(dict.fromkeys(patterns))))
    if spec.get('endpoint') is None:
        if any(_overlap(a['local'], b['remote']) for a in mappings for b in mappings):
            raise ValueError('Local endpoint source/destination overlap')
    endpoint = None
    if spec.get('endpoint') is not None:
        try:
            if type(spec['endpoint'].get('iap', False)) is not bool:
                raise ValueError()
            endpoint = TransferEndpoint(**spec['endpoint'], inspect_paths=False)
        except (TypeError, AttributeError, ValueError):
            raise ValueError('Invalid explicit SSH endpoint') from None
    for mapping in mappings:
        # Read-only rendering of the shared transfer contract. Execution below
        # delegates to transfer_directory; parity tests detect contract drift.
        # Calling that helper for preview would write SSH trust metadata.
        local = mapping['local']
        remote = (f'{endpoint.user}@{endpoint.host}:' if endpoint else '') + mapping['remote']
        source, destination = (local, remote) if mapping['direction'] == 'push' else (remote, local)
        argv = ['rsync', '-avz', '--itemize-changes', '--protect-args',
                '--partial-dir=.rsync-partial', '--timeout=60']
        if endpoint:
            argv.extend(['-e', shlex.join(endpoint.ssh_argv())])
        for pattern in mapping['excludes']:
            argv.extend(['--exclude', pattern])
        if delete:
            argv.append('--delete-after')
        mapping['rsync_argv'] = argv + ['--dry-run', '--', source.rstrip('/') + '/', destination]
    plan = dict(engine=engine, mappings=mappings, activation_allowed=False,
                target_observation='none; lexical plan only', preflight_required=True,
                protected_paths=[dict(entry) for entry in protected],
                delete=delete, delete_approved=spec.get('delete_approved', False),
                overwrite_approved=spec.get('overwrite_approved', False),
                initial_seed=seed, conflict_policy='stop')
    manifest = runtime_manifest(spec, plan)
    if manifest is not None:
        plan['runtime_manifest'] = manifest
    elif spec.get('runtime_placements'):
        raise ValueError('Runtime placement requires desired_profile')
    return plan


def runtime_manifest(spec, plan):
    """Pure selected runtime requirements for the bundled read-only checker.

    Preprepared image/environment paths are prerequisites, never installations or
    proof of contents. Legacy placement-only callers still receive candidates.
    """
    from copy import deepcopy
    profile = deepcopy(spec.get('desired_profile'))
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise ValueError('desired_profile must be shared profile data')
    known = {'schema_version', 'kind', 'name', 'extends', 'target', 'components', 'runtimes',
             'serving', 'defaults', 'draft', 'workspace', 'custom_dependencies', 'environments',
             'notes', 'repositories'}
    unknown = sorted(set(profile) - known)
    profile = {key: value for key, value in profile.items() if key in known}
    _validate_profile(profile)
    if 'extends' in profile:
        raise ValueError('Resolve inherited desired profile before runtime rendering')
    placements = spec.get('runtime_placements', {})
    if not isinstance(placements, dict):
        raise ValueError('runtime_placements must be a mapping')
    result: dict[str, Any] = dict(desired_profile=profile, runtimes={},
                  issues=[dict(field=field, reason='unknown profile field; value omitted') for field in unknown],
                  build_mounts=[], checker_issues=[], image=spec.get('image'), image_verified=False,
                  runtime_parity_verified=False, activation_allowed=False,
                  qualification='bundled-readonly-checker; manual execution only; no editable builds executed',
                  prerequisites=['Caller supplies a trusted preprepared image, executable and stdlib.',
                                 'Image tags and desired intent do not verify image contents.',
                                 'No environment creation, package installation or image build is implemented.'],
                  exclusions={m['name']: list(m['excludes']) for m in plan['mappings']})
    for name, component in profile.get('components', {}).items():
        if component.get('enabled') and component.get('runtime') not in profile.get('runtimes', {}):
            result['issues'].append(dict(field='components.' + name, reason='missing selected runtime intent'))
    for name, runtime in profile.get('runtimes', {}).items():
        selected = {key: deepcopy(value) for key, value in profile.get('components', {}).items()
                    if value.get('enabled') and value.get('runtime') == name}
        if not selected:
            continue
        placement = placements.get(name, {})
        if not isinstance(placement, dict) or set(placement) - {'environment', 'builds', 'check'}:
            raise ValueError('Unknown runtime placement fields')
        environment = placement.get('environment')
        if environment is None:
            result['issues'].append(dict(field='runtime_placements.' + name, reason='missing environment placement'))
        else:
            _path(environment)
        builds = []
        if not isinstance(placement.get('builds', []), list) or len(placement.get('builds', [])) > 128:
            raise ValueError('Select at most 128 build outputs')
        for build in placement.get('builds', []):
            if not isinstance(build, dict) or set(build) != {'component', 'source_mapping', 'remote', 'container'}:
                raise ValueError('Build output requires component, source_mapping, remote, container')
            source = next((m for m in plan['mappings'] if m['name'] == build['source_mapping'] and m['kind'] == 'source'), None)
            if build['component'] not in selected or source is None:
                raise ValueError('Build output needs a selected component and source mapping')
            _path(build['remote'])
            _path(build['container'])
            builds.append(dict(build, source_container=source['container'], source_readonly=True,
                               policy='out-of-tree-only; backend editable-install support unverified'))
            result['build_mounts'].append(dict(remote=build['remote'], container=build['container']))
        result['runtimes'][name] = dict(intent=deepcopy(runtime), components=selected,
            environment_container=environment, build_outputs=builds,
            original_environment_declarations=[deepcopy(e) for e in profile.get('environments', [])
                                                if e['name'] == runtime.get('environment')])
    # Writable runtime locations may never shadow source, artifacts, protection,
    # each other, or active settings. Report conflicts, omit ALL new build mounts.
    occupied = {field: [m[field] for m in plan['mappings']] for field in ('remote', 'container')}
    for name, runtime in result['runtimes'].items():
        for component, intent in runtime['components'].items():
            if not intent.get('source'):
                result['issues'].append(dict(field='components.' + component, reason='missing source intent'))
            # Standalone Kit is an archive runtime, not an editable Git build.
            # See isaacsim-source/tasks/standalone.yml and profile_adapters.py.
            if intent.get('source', {}).get('mode') == 'git' and not any(b['component'] == component for b in runtime['build_outputs']):
                result['issues'].append(dict(field='runtime_placements.' + name,
                    reason='missing explicit editable build-output selection for ' + component))
        locations = [('container', runtime['environment_container'])]
        locations += [(field, b[field]) for b in runtime['build_outputs'] for field in ('remote', 'container')]
        for field, path in locations:
            if path is None:
                continue
            if _excluded_root(path, (*DEFAULT_EXCLUDES, '.devcontainer/', '.vscode/', 'backups/', 'recovery/')):
                result['issues'].append(dict(field='runtime_placements.' + name,
                    reason='writable location is an excluded credential, state or recovery root', namespace=field, path=path))
            conflict = any(_overlap(path, other) for other in occupied[field])
            # Local-mode host endpoints share a namespace; remote mounts must
            # not make a local source writable either.
            if field == 'remote' and spec.get('endpoint') is None:
                conflict |= any(_overlap(path, m['local']) for m in plan['mappings'])
            conflict |= any(_overlap(path, p['path']) for p in plan['protected_paths']
                if p['namespace'] == field or (field == 'remote' and spec.get('endpoint') is None
                                               and p['namespace'] == 'local'))
            conflict |= any(p in ('.devcontainer', '.vscode') for p in PurePosixPath(path).parts)
            if conflict:
                result['issues'].append(dict(field='runtime_placements.' + name,
                    reason='writable location overlap with mapping, protection, settings or runtime', namespace=field, path=path))
            occupied[field].append(path)
    for name in set(placements) - set(result['runtimes']):
        result['issues'].append(dict(field='runtime_placements.' + name, reason='unknown or unselected runtime'))
    for field in ('custom_dependencies', 'notes', 'repositories', 'serving', 'workspace'):
        if profile.get(field):
            result['issues'].append(dict(field=field, reason='preserved intent; no runtime consumer'))
    for declaration in profile.get('environments', []):
        bound = [r for r in result['runtimes'].values() if declaration in r['original_environment_declarations']]
        if not bound:
            result['issues'].append(dict(field=declaration['id'], reason='unbound environment declaration'))
        elif any(declaration.get(field) is not None and r['intent'].get(field) is not None and
                 declaration[field] != r['intent'][field] for r in bound for field in ('manager', 'python')):
            result['issues'].append(dict(field=declaration['id'], reason='selected runtime/environment disagreement'))
    if profile.get('draft'):
        result['issues'].append(dict(field='draft', reason='desired intent still draft'))
    # Optional explicit consumer selections; never infer an interpreter, package
    # identity, image contents, or a config mapping from a placement label.
    from src.python.container_runtime_check import validate_runtime
    for name, runtime in result['runtimes'].items():
        check = deepcopy(placements.get(name, {}).get('check', {}))
        if not isinstance(check, dict) or set(check) - {'interpreter', 'distributions', 'source_bindings', 'bundle'}:
            raise ValueError('Unknown runtime check fields; no readiness flags accepted')
        bindings = check.get('source_bindings', [])
        if not isinstance(bindings, list) or len(bindings) > 128:
            raise ValueError('Select at most 128 explicit source bindings')
        normalized = []
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != {'component', 'distribution', 'source_mapping'}:
                raise ValueError('Source binding requires component, distribution and source_mapping')
            source = next((m for m in plan['mappings'] if m['kind'] == 'source' and m['name'] == binding['source_mapping']), None)
            if source is None or runtime['components'].get(binding['component'], {}).get('source', {}).get('mode') != 'git':
                raise ValueError('Source binding requires selected Git component and source mapping')
            if any(b['source_mapping'] != binding['source_mapping'] for b in runtime['build_outputs'] if b['component'] == binding['component']):
                raise ValueError('Build and runtime source bindings must agree')
            normalized.append(dict(binding, source_container=source['container']))
        check['source_bindings'] = normalized
        runtime['check'] = check
        validate_runtime(runtime, check_paths=False)
        environment = runtime['environment_container']
        custom_paths = [check['interpreter']] if check.get('interpreter') else []
        custom_paths += list(check.get('distributions', {}).values())
        for path in custom_paths:
            _path(path)
            if environment is None or PurePosixPath(environment) not in PurePosixPath(path).parents:
                raise ValueError('Explicit interpreter/metadata paths must be inside selected environment')
            if (any(_overlap(path, m['container']) for m in plan['mappings']) or
                any(_overlap(path, b['container']) for r in result['runtimes'].values() for b in r['build_outputs']) or
                any(_overlap(path, p['path']) for p in plan['protected_paths'] if p['namespace'] == 'container') or
                _excluded_root(path, (*DEFAULT_EXCLUDES, '.devcontainer/', '.vscode/', 'backups/', 'recovery/'))):
                raise ValueError('Explicit runtime check path overlaps protected/source/build/settings mounts')
        missing = []
        if not check.get('interpreter'):
            missing.append('explicit interpreter path')
        for package in ('torch', 'torchvision'):
            if runtime['intent'].get(package) is not None and package not in check.get('distributions', {}):
                missing.append('explicit ' + package + ' dist-info path')
        for component, intent in runtime['components'].items():
            if intent.get('source', {}).get('mode') == 'git' and not any(b['component'] == component for b in normalized):
                missing.append('explicit source distribution binding for ' + component)
        bundle = check.get('bundle')
        if bundle is None:
            missing.append('explicit checker bundle config mapping and relative path')
        else:
            if not isinstance(bundle, dict) or set(bundle) != {'config_mapping', 'relative_path'}:
                raise ValueError('Checker bundle requires config_mapping and relative_path')
            config = next((m for m in plan['mappings'] if m['name'] == bundle['config_mapping'] and m['kind'] == 'config'), None)
            relative = bundle['relative_path']
            if (config is None or not isinstance(relative, str) or len(relative) > 256 or
                not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_./-]*', relative) or
                any(p in ('', '.', '..') for p in relative.split('/'))):
                raise ValueError('Checker bundle needs an explicit config mapping and safe relative directory')
            for field in ('local', 'remote', 'container'):
                path = config[field] + '/' + relative
                _path(path)
                if _excluded_root(path, (*DEFAULT_EXCLUDES, *ENV_EXCLUDES, *ARTIFACT_EXCLUDES)) or any(
                    _overlap(path, p['path']) for p in plan['protected_paths'] if p['namespace'] == field or
                    (spec.get('endpoint') is None and field in ('local', 'remote') and p['namespace'] in ('local', 'remote'))):
                    raise ValueError('Checker bundle overlaps excluded or protected path')
                bundle[field] = path
            bundle['files'] = ['container_runtime_check.py', 'runtime-placement.json']
            bundle['manual_argv'] = ([check['interpreter'], '-I', '-S', '-B',
                bundle['container'] + '/container_runtime_check.py', '--manifest',
                bundle['container'] + '/runtime-placement.json', '--runtime', name] if check.get('interpreter') else None)
        for reason in missing:
            result['checker_issues'].append(dict(field='runtime_placements.' + name + '.check', reason='missing ' + reason))
    result['checker_selection_complete'] = not result['checker_issues'] and not result['issues']
    result['placement_complete'] = not result['issues']
    if result['issues']:
        result['build_mounts'] = []
    return result


def render_candidate(spec, output_dir, *, reviewed=False):
    """Create review artifacts in a NEW explicit directory, never install them.

    Parent directories must already exist. Descriptor-relative exclusive writes
    refuse symlink traversal and overwrites; interrupted candidates are retained,
    not recursively cleaned up or silently reused.
    """
    import json
    import os
    if reviewed is not True:
        raise ValueError('Explicit reviewed=True is required to render files')
    plan = build_plan(spec)
    image = spec.get('image')
    if not isinstance(image, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/:@-]*', image):
        raise ValueError('Render requires an explicit image reference; runtime parity is unverified')
    out = _path(str(output_dir), local=True)
    if any(_overlap(out, entry['path']) for entry in plan['protected_paths']
           if entry['namespace'] == 'local' or
           (entry['namespace'] == 'remote' and spec.get('endpoint') is None)):
        raise ValueError('Candidate output overlaps a selected protected path')
    if any(p in ('.devcontainer', '.vscode') for p in Path(out).parts):
        raise ValueError('Never render into active devcontainer or editor settings')
    if any(_overlap(out, mapping[field]) for mapping in plan['mappings']
           for field in ('local', 'remote')):
        raise ValueError('Candidate output must not overlap synchronization folders')
    mounts = [f"type=bind,source={m['remote']},target={m['container']}" +
              (',readonly' if m['kind'] != 'artifacts' else '') for m in plan['mappings']]
    manifest = plan.get('runtime_manifest')
    if manifest is not None:
        if any(_overlap(out, b['remote']) for runtime in manifest['runtimes'].values()
               for b in runtime['build_outputs']):
            raise ValueError('Candidate output overlaps selected editable build output')
        mounts.extend(f"type=bind,source={b['remote']},target={b['container']}" for b in manifest['build_mounts'])
    devcontainer = dict(name='Reviewed remote development candidate', image=image,
                        workspaceFolder=plan['mappings'][0]['container'],
                        workspaceMount=mounts[0], mounts=mounts[1:])
    result = dict(plan=plan, devcontainer=devcontainer, runtime_parity_verified=False,
                  activation_allowed=False,
                  warnings=['Image contents, GPU/display, UID/GID, host mounts and runtime dependencies are unverified.',
                            'No hooks, editable installs, services, settings or containers are executed.',
                            'Remote symlinks, destination ownership and concurrent writers require live preflight.',
                            'Filename exclusions are not secret scanning; review selected source contents separately.'])
    files = {'devcontainer.json': json.dumps(devcontainer, indent=2, sort_keys=True) + '\n'}
    if manifest is not None:
        from src.python import container_runtime_check
        result['runtime_manifest'] = manifest
        encoded_manifest = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
        if len(encoded_manifest.encode('utf-8')) > container_runtime_check.MAX_BYTES:
            raise ValueError('Runtime checker manifest exceeds bounded file size')
        files['runtime-placement.json'] = encoded_manifest
        files['container_runtime_check.py'] = Path(container_runtime_check.__file__).read_text(encoding='utf-8')
        instructions = [
            '# Manual read-only runtime checker candidate', '',
            'No image, environment, package, container, service or active settings are created or changed.',
            'The caller must supply an independently prepared and trusted image with the selected',
            'interpreter, stdlib, prefix and packages already present. An image tag is NOT verification.',
            'Environment paths are inside that image, NOT host environment bind mounts.', '',
            'For each runtime, review the manifest check.bundle paths. Separately and manually',
            'place ONLY container_runtime_check.py and runtime-placement.json into a NEW directory',
            'at bundle.local relative to the selected config mapping; refuse existing files or symlinks.',
            'Use a separately reviewed sync/placement operation to reach bundle.remote. The read-only',
            'config mount then exposes bundle.container. Rendering does not perform those operations.',
            'Do not place the devcontainer candidate or active editor settings in this bundle.', '',
            'Inside the independently started container, with a trusted loader environment, run the',
            'exact per-runtime command below manually. There are no lifecycle hooks or autoactivation.',
            'The selected interpreter receives -I -S -B and a fixed stdlib-only protocol; no .pth,',
            'sitecustomize, project, Torch, or robotics code is imported. Only explicitly selected',
            'dist-info METADATA and direct_url.json files are read (128 KiB each, <=128 selections).',
            'Metadata must be directly under a sysconfig package path reported by that interpreter.',
            'Symlinked metadata/ancestors, hardlinks and special files are refused.',
            'On CPython before 3.14, -S venv prefix initialization is unsupported: mismatch fails',
            'closed; no site.py fallback or prefix inference is attempted. Conda/bundled/custom',
            'layouts are only checkable when their isolated interpreter reports the selected prefix.', '',
            'Exit 0 means selected observable checks match, NOT runtime readiness or full parity.',
            'Exit 1 means missing/mismatching evidence; exit 2 means invalid input.',
            'Unsupported results remain visible: .pth/editable import binding, backend out-of-tree',
            'build support, Git repository/ref/revision, standalone Kit/archive identity, metadata',
            'duplicate/import precedence, GPU/CUDA/ABI and full-runtime parity. Build directory',
            'existence is not writability, an implemented build, an install or backend qualification.',
            'No manager/activation script or GPU import is invoked. No automatic fix is attempted.', '',
            'Selection syntax: runtime_placements.<runtime>.check has explicit interpreter,',
            'distributions {distribution-name: absolute-dist-info-directory}, source_bindings',
            '[{component, distribution, source_mapping}], and bundle {config_mapping, relative_path}.',
            'The interpreter and metadata directories must be inside the selected environment.',
            'No distribution name or interpreter path is inferred from a component or label.', '',
        ]
        for name, runtime in manifest['runtimes'].items():
            bundle = runtime['check'].get('bundle')
            instructions += ['## ' + name, '']
            if bundle:
                instructions += ['Local manual placement: `' + bundle['local'] + '`',
                                 'Remote host destination: `' + bundle['remote'] + '`',
                                 'In-container directory: `' + bundle['container'] + '`', '']
            if bundle and bundle.get('manual_argv'):
                instructions += ['```sh', shlex.join(bundle['manual_argv']), '```', '']
            else:
                instructions += ['Invocation unavailable: select explicit interpreter and config bundle paths.', '']
        files['runtime-check.README.md'] = '\n'.join(instructions) + '\n'
    if plan['engine'] != 'rsync':
        result['continuous'] = dict(engine=plan['engine'], activation_allowed=False,
            native_validation='not-performed', supervisor_implemented=plan['engine'] == 'syncthing',
            supervisor_support=('API-only paired preconfigured loopback folders; v1.27.12; synthetic qualification only'
                                if plan['engine'] == 'syncthing' else 'candidate and lifecycle model only; no Mutagen supervisor'),
            deletion_propagates=True, deletion_approved=plan['delete_approved'],
            live_gates=['pairing/transport', 'separate deletion and recovery review',
                        'initial seed verification', 'exclusive writer lock', 'remote path preflight'],
            status='candidate-only; no native engine validation or service activation')
        if plan['engine'] == 'mutagen':
            sessions = {}
            for m in plan['mappings']:
                remote = m['remote']
                if spec.get('endpoint'):
                    endpoint = TransferEndpoint(**spec['endpoint'], inspect_paths=False)
                    remote = f'{endpoint.user}@{endpoint.host}:{remote}'
                alpha, beta = (m['local'], remote) if m['direction'] == 'push' else (remote, m['local'])
                sessions[m['name']] = dict(alpha=alpha, beta=beta, mode='one-way-safe',
                    symlink={'mode': 'ignore'},
                    ignore={'vcs': True, 'paths': [p.rstrip('/') for p in m['excludes']]})
            # JSON is valid YAML; no YAML executable tags or project lifecycle hooks.
            files['mutagen.candidate.yml'] = json.dumps({'sync': sessions}, indent=2, sort_keys=True) + '\n'
            result['continuous']['transport_note'] = (
                'Mutagen does not automatically consume rsync SSH argv. Review/install a dedicated '
                'SSH transport matching the shared SSH/IAP preview before use; ambient SSH is not qualified. '
                'Mutagen has no backup/versioning configured: test separate recovery first.')
        else:
            import xml.etree.ElementTree as ET
            for side in ('local', 'remote'):
                root = ET.Element('configuration', version='37')
                for m in plan['mappings']:
                    sender = (side == 'local') == (m['direction'] == 'push')
                    folder = ET.SubElement(root, 'folder', id=m['name'], label=m['name'],
                        path=m[side], type='sendonly' if sender else 'receiveonly', paused='true')
                    versioning = ET.SubElement(folder, 'versioning', type='staggered')
                    ET.SubElement(versioning, 'param', key='maxAge', val='2592000')
                files[f'syncthing.{side}.candidate.xml'] = ET.tostring(root, encoding='unicode') + '\n'
            for m in plan['mappings']:
                files[f"{m['name']}.stignore.candidate"] = '\n'.join(p.rstrip('/') for p in m['excludes']) + '\n'
            result['continuous']['transport_note'] = (
                'Paused folder-only config candidates; device IDs, addresses, TLS trust and pairing are absent. '
                'Install reviewed ignore files on BOTH endpoints before unpausing. Syncthing uses its own '
                'transport, not SSH/IAP. Staggered versioning is a candidate, not a tested backup.')
    files['review.json'] = json.dumps(result, indent=2, sort_keys=True) + '\n'
    # Walk an existing parent with O_NOFOLLOW at EVERY component; a symlink
    # replacement cannot redirect writes outside the opened directory.
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(out).parent.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        os.mkdir(Path(out).name, mode=0o700, dir_fd=fd)
        child = os.open(Path(out).name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            for name, value in files.items():
                file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=child)
                with os.fdopen(file_fd, 'w') as stream:
                    stream.write(value)
        finally:
            os.close(child)
    finally:
        os.close(fd)
    return result


def _fixture_files(root, patterns):
    """Inspect bounded disposable trees without dereferencing links or devices."""
    import os
    import stat
    files = {}
    if not root.exists():
        return files
    count = 0
    for current, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(current) / name
            count += 1
            mode = path.lstat().st_mode
            if count > 10000:
                raise ValueError('Disposable fixture exceeds entry bound')
            if stat.S_ISLNK(mode):
                raise ValueError('Disposable fixture contains a symlink')
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ValueError('Disposable fixture contains a special file')
            if stat.S_ISREG(mode) and path.stat().st_nlink != 1:
                raise ValueError('Disposable fixture contains a hardlink')
            relative = path.relative_to(root).as_posix()
            prefixes = [relative, *(p.as_posix() for p in PurePosixPath(relative).parents if str(p) != '.')]
            ignored = any(
                (fnmatch.fnmatchcase('/' + prefix, pattern.rstrip('/')) if pattern.startswith('/') else
                 fnmatch.fnmatchcase(prefix, pattern.rstrip('/')) or
                 fnmatch.fnmatchcase(prefix, '*/' + pattern.rstrip('/')))
                for prefix in prefixes for pattern in patterns)
            if stat.S_ISREG(mode) and not ignored:
                files[relative] = path
    return files


def _fixture_manifest(files):
    """Snapshot intended regular-file bytes, independent of rsync and filecmp cache."""
    import hashlib
    import os
    import stat
    manifest = {}
    for relative, path in files.items():
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Fixture verification requires single-link regular files')
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            manifest[relative] = digest.hexdigest()
    return manifest


class _LocalFixture:
    """Only created by local_fixture(); never accepts an existing sandbox root."""
    def __init__(self, root):
        self.root = root

    @contextmanager
    def writer(self, engine):
        """Cooperative cross-process lock; conservatively covers the whole fixture.

        Keep the lock inode for this fixture's lifetime. Removing a lock file
        would allow another process to lock a different inode for the same scope.
        This cannot lock an independently launched external daemon.
        """
        import fcntl
        import os
        if engine not in ('rsync', 'mutagen', 'syncthing'):
            raise ValueError('Choose an explicit writer engine')
        fd = os.open(self.root / '.writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another writer owns this synchronization scope') from None
            if os.fstat(fd).st_size:
                raise ValueError('Unclean continuous writer guard requires explicit recovery')
            from src.python.dataset_lock import DatasetLock
            with DatasetLock([str(self.root)]) as dataset_lock:
                yield dataset_lock
        finally:
            os.close(fd)

    def transfer(self, spec):
        """Qualify the existing rsync transport on owned temporary data only."""
        with self.writer('rsync') as dataset_lock:
            return self._transfer_locked(spec, dataset_lock=dataset_lock)

    def _transfer_locked(self, spec, *, dataset_lock):
        from src.python.file_transfer import transfer_directory
        if spec.get('endpoint') is not None or spec.get('engine') != 'rsync':
            raise ValueError('Local fixture only: no remote endpoint or continuous service')
        plan = build_plan(spec)
        for m in plan['mappings']:
            for field in ('local', 'remote'):
                if self.root not in Path(m[field]).parents:
                    raise ValueError('All endpoints must be inside this disposable fixture')
                _path(m[field], local=True)
        dataset_lock.check()
        # The enclosing fixture lock covers creation of absent destinations.
        # Never create sources; pin each existing sender before any seed write.
        sources = [m['local' if m['direction'] == 'push' else 'remote'] for m in plan['mappings']]
        dataset_lock.pin(sources)
        pairs = []
        # Validate ALL mappings before transferring the first one.
        for m in plan['mappings']:
            local, remote = Path(m['local']), Path(m['remote'])
            source, destination = (local, remote) if m['direction'] == 'push' else (remote, local)
            if not source.is_dir():
                raise ValueError('Disposable fixture source is missing')
            incoming = _fixture_files(source, m['excludes'])
            existing = _fixture_files(destination, m['excludes'])
            if plan['initial_seed'] == 'empty-target' and existing.keys() - incoming.keys():
                raise ValueError('Initial seed conflict: requires an empty or identical target; adoption needs separate review')
            for relative in incoming:
                other = destination / relative
                if other.exists() and not other.is_file():
                    raise ValueError('Destination type conflict: file/directory replacement is unsupported')
            for relative in existing:
                if (source / relative).is_dir():
                    raise ValueError('Destination type conflict: file/directory replacement is unsupported')
            intended = _fixture_manifest(incoming)
            prior = _fixture_manifest(existing)
            for relative in incoming.keys() & existing.keys():
                if (intended[relative] != prior[relative]
                        and plan['initial_seed'] != 'reviewed-overwrite'):
                    raise ValueError('Destination conflict: stop and review before overwriting')
            all_prior = _fixture_manifest(_fixture_files(destination, ()))
            protected_prior = {key: value for key, value in all_prior.items() if key not in prior}
            expected = {**protected_prior, **intended} if plan['delete'] else {**all_prior, **intended}
            pairs.append((m, source, destination, intended, expected))
        for m, source, destination, intended, expected in pairs:
            dataset_lock.check()
            destination.mkdir(parents=True, exist_ok=True)
        dataset_lock.pin(m[side] for m in plan['mappings'] for side in ('local', 'remote'))
        returncodes = []
        for m, source, destination, intended, expected in pairs:
            dataset_lock.check()
            result = transfer_directory(None, m['direction'], m['local'], m['remote'],
                delete=plan['delete'], capture_output=True, isolated_local=True, checksum=True,
                exclude=tuple(p for p in m['excludes'] if p not in DEFAULT_EXCLUDES))
            returncodes.append(result.returncode)
        dataset_lock.check()
        # Verify every mapping after every transfer, against pre-launch intent.
        # A zero exit or equal *changed* endpoints is not proof of the seed.
        for m, source, destination, intended, expected in pairs:
            if (_fixture_manifest(_fixture_files(source, m['excludes'])) != intended or
                    _fixture_manifest(_fixture_files(destination, ())) != expected):
                raise ValueError('Seed byte verification failed; stop and review, no verified receipt')
        dataset_lock.check()
        return {'returncodes': returncodes, 'scope': 'disposable-local-only',
                'status': 'verified', 'verification': 'sha256-preflight-regular-file-bytes'}


class Lifecycle:
    """Non-executing lifecycle orchestration, not a running daemon controller.

    Callers can review ordered transitions and gates without starting anything.
    Every new instance requires a new verified seed; no on-login/auto-resume path.
    Actual process supervision and cross-host locking remain unqualified.
    """
    def __init__(self, spec):
        self.plan = build_plan(spec)
        self.state = 'unseeded'

    def transition(self, event, *, verified=False, deletion_approved=False, recovery_verified=False):
        if event == 'stop':
            state = 'stopped'
        elif event in ('conflict', 'failure'):
            state = 'blocked'
        elif event == 'seed-start':
            if self.state not in ('unseeded', 'paused'):
                raise ValueError('An active or blocked writer prevents reseeding')
            state = 'seeding'
        elif event == 'seed-complete':
            if self.state != 'seeding' or verified is not True:
                raise ValueError('Seed postconditions must be independently verified')
            state = 'paused'
        elif event == 'resume':
            if self.state != 'paused':
                raise ValueError('A verified seed and paused writer are required; blocked/stopped sessions need new review')
            if self.plan['engine'] == 'rsync':
                raise ValueError('Rsync has no continuous service to resume')
            if verified is not True:
                raise ValueError('Transport, ownership, pairing and writer preflight must be verified')
            if deletion_approved is not True:
                raise ValueError('Continuous engines propagate deletion; separate approval required')
            if recovery_verified is not True:
                raise ValueError('Continuous activation requires verified recovery outside sync roots')
            state = 'continuous'
        elif event == 'pause' and self.state == 'continuous':
            if verified is not True:
                raise ValueError('Writer stop must be verified before releasing its lock')
            state = 'paused'
        else:
            raise ValueError('Unsupported lifecycle transition')
        self.state = state
        return dict(state=state, event=event, executed=False, model_only=True,
                    process_status='not-observed', supervisor_implemented=False,
                    modeled_writer='continuous-engine' if state == 'continuous' else
                           ('rsync-seed' if state == 'seeding' else None),
                    activation_allowed=False)


@contextmanager
def local_fixture():
    """Allocate and clean up NEW disposable local qualification endpoints.

    No CLI exposes this helper. It does not accept pre-existing user directories
    and never invokes SSH. It is not a production filesystem security sandbox.
    """
    import tempfile
    with tempfile.TemporaryDirectory(prefix='isaac-remote-qualification-') as directory:
        yield _LocalFixture(Path(directory))
