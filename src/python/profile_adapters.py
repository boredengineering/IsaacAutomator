"""Pure software intent adapters. Rendering never grants permission to apply.

Every input leaf is accounted for. An unsupported non-null selected field blocks
complete consumer export; disabled and optional declarations remain visible.
"""
from copy import deepcopy
import json
from pathlib import PurePosixPath
import re

from src.python.workstation_profile import ProfileError, _validate, _dependencies


# TODO: Replace static component name/directory mappings with dynamic manifest-driven resolution.
LEGACY_NAMES = {'lab': 'isaaclab', 'arena': 'arena', 'gr00t': 'gr00t', 'lerobot': 'lerobot', 'robolab': 'robolab'}
REPO_DIRS = {'lab': 'IsaacLab', 'arena': 'IsaacLab-Arena', 'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot', 'robolab': 'RoboLab'}


def _leaves(value, prefix=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f'{prefix}.{key}' if prefix else key)
    elif isinstance(value, list) and value:
        for i, item in enumerate(value):
            yield from _leaves(item, f'{prefix}.{i}')
    else:
        yield prefix, value


def _target_path(value, home):
    if not isinstance(home, str) or not re.fullmatch(r'/[A-Za-z0-9_./ -]+', home):
        raise ProfileError('target_home: explicit safe absolute target home required')
    if home == '/' or any(p in ('.', '..') for p in home.split('/')):
        raise ProfileError('target_home: unsafe target home')
    if value.startswith('~/'):
        value = home.rstrip('/') + value[1:]
    if not re.fullmatch(r'/[A-Za-z0-9_./ -]+', value) or any(p in ('.', '..') for p in value.split('/')):
        raise ProfileError('workspace.root: safe absolute or target-home-relative path required')
    return str(PurePosixPath(value))


def render_profile(profile_or_resolved, adapter, target_home):
    """Return concrete consumer data plus a field-by-field coverage report.

    Input must be shared desired intent or its resolved manifest. No file, Git,
    cloud, target filesystem, subprocess or environment inspection is performed.
    """
    if adapter == 'packer':
        # Images use the same Ansible playbook and last extra-vars JSON file.
        # Keep one field classification: transport is not build/runtime proof.
        return {**render_profile(profile_or_resolved, 'ansible', target_home), 'adapter': 'packer'}
    profile = deepcopy(profile_or_resolved.get('profile', profile_or_resolved))
    _validate(profile)
    if 'extends' in profile:
        raise ProfileError('Use resolve_profile before rendering inherited intent')
    _dependencies(profile)
    if adapter not in ('local', 'ansible'):
        raise ProfileError('Unsupported adapter')
    home = _target_path(target_home, target_home)
    components = profile.get('components', {})
    selected = {name for name, value in components.items() if value.get('enabled')}
    runtimes = profile.get('runtimes', {})
    selected_runtimes = {components[n].get('runtime') for n in selected}
    coverage = {path: {'status': 'unsupported', 'reason': 'No matching consumer', 'required': True}
                for path, value in _leaves(profile)}
    values = dict(_leaves(profile))

    def mark(path, status='mapped', consumer=None, reason=None, required=True):
        if path in coverage:
            coverage[path] = {'status': status, 'required': required}
            if consumer:
                coverage[path]['consumer'] = consumer
            if reason:
                coverage[path]['reason'] = reason

    def subtree(path, status, reason=None, required=True, consumer=None):
        for field in coverage:
            if field == path or field.startswith(path + '.'):
                mark(field, status, consumer=consumer, reason=reason, required=required)

    for field in ('schema_version', 'kind', 'name', 'target', 'extends', 'defaults', 'draft'):
        mark(field, 'metadata', reason='Rendering metadata, not deployment authorization')
    artifact: dict = {'version': '1.0', 'profile_name': profile['name'], 'public_git_profile': True, 'repositories': {},
                'simulation': {}, 'workspace': {'root': home + '/Documents/GitHub',
                    'layout': 'flat', 'auto_create_fork': False,
                    'auto_register_github_desktop': False},
                'streaming': {'provider': 'none'},
                'devtools': {'docker': False, 'nvidia_container_toolkit': False,
                    'vscode': False, 'github_desktop': False, 'chromium': False,
                    'discord': False, 'cloud_clis': {'aws': False, 'gcloud': False, 'gh': False}},
                'teleoperation': {'ftdi_1ms_latency_rule': False, 'spacemouse_daemon': False,
                    'manus_vr_gloves': False, 'realsense_cameras': False, 'xr_cloudxr': False},
                'demos': {'desktop_shortcuts': False}}
    deploy_params = {}
    for name, component in components.items():
        path = f'components.{name}'
        enabled = name in selected
        source = component.get('source', {})
        if name == 'sim':
            destination = 'simulation.isaacsim'
            out = {'enabled': enabled}
            artifact['simulation']['isaacsim'] = out
        else:
            destination = 'repositories.' + LEGACY_NAMES.get(name, name)
            out = {'enabled': enabled}
            artifact['repositories'][LEGACY_NAMES.get(name, name)] = out
        mark(path + '.enabled', consumer=destination + '.enabled')
        if not enabled:
            subtree(path, 'not_selected', 'Component disabled')
            mark(path + '.enabled', consumer=destination + '.enabled')
            continue
        mark(path + '.execution', consumer='native installer modules')
        mark(path + '.runtime', consumer='component-specific environment binding')
        if 'install' in component:
            subtree(path + '.install', 'mapped', consumer='workspace-component')
        if 'desktop_shortcut' in component:
            subtree(path + '.desktop_shortcut', 'mapped', consumer='workspace-component')
        if 'dependencies' in component:
            subtree(path + '.dependencies', 'mapped', consumer='workspace-component')
        if 'upstream' in component:
            mark(path + '.upstream', 'mapped', consumer='workspace-component')
        if 'install_dir' in component:
            mark(path + '.install_dir', 'mapped', consumer='workspace-component')
        if name == 'sim':
            if source.get('mode') == 'standalone':
                out.update(version=source.get('version'), source_type='standalone', install_dir=home + '/IsaacSim')
                mark(path + '.source.mode', consumer=destination + '.source_type')
                mark(path + '.source.version', consumer=destination + '.version')
            else:
                subtree(path + '.source', 'unsupported', 'Local installer does not consume a Git Sim source pair')
            if source.get('url') is None:
                mark(path + '.source.url', 'unspecified', reason='No explicit archive URL override requested')
            if source.get('sha256') is None:
                mark(path + '.source.sha256', 'unspecified', reason='No immutable archive checksum requested')
            if adapter == 'local' and source.get('mode') == 'standalone' and (source.get('url') or source.get('sha256')):
                for key in ('url', 'sha256'):
                    if source.get(key):
                        out[key] = source[key]
                    mark(path + '.source.' + key, 'mapped' if source.get(key) else 'unsupported',
                         consumer=destination + '.' + key,
                         reason='Public artifact helper verifies exact URL/checksum pair before extraction')
        else:
            out.update(repo=source.get('repository'), branch='', tag=source.get('revision') or source.get('ref', ''))
            mark(path + '.source.mode', consumer='Git checkout')
            mark(path + '.source.repository', consumer=destination + '.repo')
            mark(path + '.source.ref', 'superseded' if source.get('revision') else 'mapped',
                 consumer=destination + '.tag', reason='Explicit revision takes precedence; reachability unverified')
            mark(path + '.source.revision', 'mapped' if source.get('revision') else 'unspecified',
                 consumer=destination + '.tag')
            if name in ('gr00t', 'lerobot'):
                out['isolated_env'] = True
    for name, runtime in runtimes.items():
        path = f'runtimes.{name}'
        if name not in selected_runtimes:
            subtree(path, 'not_selected', 'Runtime not selected')
            continue
        mark(path + '.manager', consumer='fixed native environment manager')
        expected_environment = {'kit': 'kit', 'lab': 'isaaclab', 'gr00t': 'gr00t', 'lerobot': 'lerobot'}.get(name)
        if expected_environment and runtime.get('environment') == expected_environment:
            mark(path + '.environment', consumer='fixed native environment identity',
                 reason='GR00T label identifies repository-local .venv' if name == 'gr00t' else None)
        elif not expected_environment:
            mark(path + '.environment', consumer='custom environment identity')
        if adapter == 'local' and name == 'lab':
            # Actual config.sh -> install_python_env -> install_profile_lab_runtime
            # consumes these scalars; no helper defaults replace explicit pins.
            artifact.setdefault('runtimes', {})['lab'] = {
                key: value for key, value in runtime.items()
                if key != 'manager' and value is not None}
            mark(path + '.manager', consumer='conda.sh install_profile_lab_runtime')
            for key in ('python', 'torch', 'torchvision', 'cuda_runtime', 'architecture'):
                if runtime.get(key) is not None:
                    mark(path + '.' + key, consumer='runtimes.lab.' + key,
                         reason='Architecture asserted against observed GPU before mutation' if key == 'architecture' else None)
            cuda = runtime.get('cuda_runtime')
            if cuda is not None and (not re.fullmatch(r'[0-9]+\.[0-9]+', cuda) or any(
                    '+cu' in (runtime.get(key) or '') and runtime[key].split('+cu')[-1] != cuda.replace('.', '')
                    for key in ('torch', 'torchvision'))):
                mark(path + '.cuda_runtime', 'unsupported', reason='CUDA wheel channel conflicts with requested wheel pins')
        for key, value in runtime.items():
            if value is None:
                mark(path + '.' + key, 'unspecified', reason='No pin requested')
    if not profile.get('serving', {}).get('enabled'):
        subtree('serving', 'not_selected', 'Serving disabled')
        mark('serving.enabled', consumer='No serving activation by adapter')
    if adapter == 'ansible':
        artifact = {'public_git_profile': True, 'install_gr00t': False, 'install_lerobot': False, 'install_robolab': False,
                    'gr00t_service_enabled': False, 'profile_isaacsim_archive_enabled': False}
        # TODO: Refactor hardcoded component-to-consumer mappings for future extensibility.
        # Currently, the supported components ('sim', 'lab', 'arena', 'gr00t', 'lerobot') and their
        # corresponding Ansible consumer variables and directory structures are explicitly enumerated.
        # In a future iteration, this adapter should dynamically discover and iterate over arbitrary
        # components declared in the workstation profile YAML (e.g., 'robolab', custom benchmark suites,
        # or user-defined robotics packages), resolving git sources, runtimes, and paths generically.
        for name, consumer in (('sim', 'isaacsim'), ('lab', 'isaaclab'), ('arena', 'isaaclab_arena'),
                               ('gr00t', 'gr00t'), ('lerobot', 'lerobot')):
            component = components.get(name, {})
            source = component.get('source', {})
            path = f'components.{name}'
            checkpoint = 'no'
            if name in selected:
                if source.get('mode') == 'git':
                    checkpoint = source.get('revision') or source.get('ref', '')
                    artifact[consumer + '_git_repo'] = source.get('repository')
                    for field in ('mode', 'repository', 'ref', 'revision'):
                        mark(path + '.source.' + field,
                             'superseded' if field == 'ref' and source.get('revision') else
                             'unspecified' if field == 'revision' and not source.get('revision') else 'mapped',
                             consumer=consumer + ('_git_repo' if field == 'repository' else '_git_checkpoint'))
                    if str(checkpoint).lower() == 'no':
                        mark(path + '.source.ref', 'unsupported',
                             reason='Ansible disabled sentinel cannot select an enabled component Git ref')
                    if name in ('sim', 'lab', 'arena'):
                        deploy_params[consumer + '_repo'] = source.get('repository')
                elif name == 'sim' and source.get('mode') == 'standalone':
                    artifact['profile_isaacsim_archive_enabled'] = True
                    artifact['isaacsim_version'] = source.get('version')
                    artifact['isaacsim_install_dir'] = home + '/IsaacSim'
                    artifact['isaacsim_archive_sha256'] = source.get('sha256')
                    mark(path + '.source.mode', consumer='isaacsim-source standalone.yml (no Git build)')
                    artifact['isaacsim_archive_url'] = source.get('url')
                    mark(path + '.source.url', 'mapped' if source.get('url') else 'unsupported',
                         consumer='isaacsim_archive_url', reason='Explicit reviewed URL only; no URL constructed or fetched')
                    mark(path + '.source.version', 'mapped' if source.get('version') == '6.0.1' else 'unsupported',
                         consumer='isaacsim_version', reason='Standalone role currently supports 6.0.1; archive contents and runtime remain unverified')
                    mark(path + '.source.sha256', 'mapped' if source.get('sha256') else 'unsupported',
                         consumer='isaacsim_archive_sha256',
                         reason='Explicit archive checksum required; no checksum is fabricated or fetched')
                else:
                    subtree(path + '.source', 'unsupported', 'No matching Ansible source consumer')
                if name in ('gr00t', 'lerobot'):
                    artifact['install_' + consumer] = True
                    if name == 'gr00t':
                        artifact['profile_gr00t_isolated'] = True
                        artifact['enable_uv'] = True  # earlier conda role provides the uv CLI
                        mark('components.gr00t.runtime', consumer='profile_gr00t_isolated')
                        mark('runtimes.gr00t.manager', consumer='gr00t role uv sync into repository .venv')
                        # The public label identifies the project-local uv environment.
                        # Other identities and non-null wheel pins remain unsupported.
                    elif name == 'lerobot':
                        artifact['profile_lerobot_isolated'] = True
                        mark('components.lerobot.runtime', consumer='profile_lerobot_isolated')
                        mark('runtimes.lerobot.manager', consumer='lerobot role isolated conda environment')
                        for key in ('environment', 'python'):
                            value = runtimes.get('lerobot', {}).get(key)
                            if value is not None:
                                runtime_consumer = 'profile_lerobot_' + key
                                artifact[runtime_consumer] = value
                                mark('runtimes.lerobot.' + key, consumer=runtime_consumer)
            artifact[consumer + '_git_checkpoint'] = checkpoint
            mark(path + '.enabled', consumer=('profile_isaacsim_archive_enabled' if name == 'sim' and source.get('mode') == 'standalone'
                 else 'install_' + consumer if name in ('gr00t', 'lerobot') else consumer + '_git_checkpoint'))
            if name in ('sim', 'lab', 'arena'):
                deploy_params[consumer] = checkpoint

        # Dynamic open-world components mapping for Ansible:
        for name, component in components.items():
            if name in ('sim', 'lab', 'arena', 'gr00t', 'lerobot'):
                continue
            path = f'components.{name}'
            if name in selected:
                source = component.get('source', {})
                if source.get('mode') == 'git':
                    checkpoint = source.get('revision') or source.get('ref', '')
                    for field in ('mode', 'repository', 'ref', 'revision'):
                        mark(path + '.source.' + field,
                             'superseded' if field == 'ref' and source.get('revision') else
                             'unspecified' if field == 'revision' and not source.get('revision') else 'mapped',
                             consumer='workspace-component')
                    if str(checkpoint).lower() == 'no':
                        mark(path + '.source.ref', 'unsupported',
                             reason='Ansible disabled sentinel cannot select an enabled component Git ref')
                else:
                    subtree(path + '.source', 'unsupported', 'No matching Ansible source consumer')
                mark(path + '.enabled', consumer='workspace-component')
                mark(path + '.runtime', consumer='workspace-component')
                mark(path + '.execution', consumer='workspace-component')
            else:
                subtree(path, 'not_selected', 'Component disabled')
                mark(path + '.enabled', consumer='workspace-component')
        if 'lab' in selected_runtimes:
            for key, consumer in (('environment', 'conda_env_name'), ('python', 'conda_python_version')):
                value = runtimes.get('lab', {}).get(key)
                if value is not None:
                    artifact[consumer] = value
                    mark('runtimes.lab.' + key, consumer=consumer)
            mark('runtimes.lab.manager', consumer='conda role')
            for key in ('torch', 'torchvision', 'cuda_runtime', 'architecture'):
                value = runtimes.get('lab', {}).get(key)
                if value is not None:
                    consumer = 'profile_lab_' + key
                    artifact[consumer] = value
                    mark('runtimes.lab.' + key, consumer=consumer,
                         reason='GPU architecture asserted at apply, never verified by rendering' if key == 'architecture' else None)
    workspace = profile.get('workspace', {})
    if workspace:
        root = _target_path(workspace.get('root', '~/Documents/GitHub'), home)
        layout = workspace.get('layout')
        name = workspace.get('name')
        owner = workspace.get('default_owner')
        if layout in ('flat', 'named') and (layout != 'named' or name):
            if adapter == 'local':
                artifact['workspace'].update(workspace, root=root)
            else:
                base = root + ('/' + name if layout == 'named' else '')
                for component in selected:
                    if component == 'sim' and components[component].get('source', {}).get('mode') == 'git':
                        artifact['isaacsim_source_dir'] = base + '/IsaacSim'
                    if component in REPO_DIRS:
                        consumer = {'lab': 'isaaclab', 'arena': 'isaaclab_arena'}.get(component, component)
                        artifact[consumer + '_dir'] = base + '/' + REPO_DIRS[component]
                artifact['workspace_dir'] = base
            for key in workspace:
                mark('workspace.' + key, consumer='workspace.' + key if adapter == 'local' else 'component directory variables',
                     reason='Pure target path translation; existing paths and collisions not inspected')
        elif adapter == 'local' and layout in ('auto', 'org'):
            artifact['workspace'].update(workspace, root=root)
            for key in workspace:
                mark('workspace.' + key, consumer='workspace.' + key,
                     reason='Legacy owner-dependent resolution retained, not named-layout equivalence')
        else:
            subtree('workspace', 'unsupported', 'Explicit complete named/flat workspace required for Ansible translation')
    # Build open-world profile components manifest for Ansible
    if adapter == 'ansible':
        ws = profile.get('workspace', {})
        ws_root = _target_path(ws.get('root', '~/Documents/GitHub'), home) if ws else home + '/Documents/GitHub'
        ws_layout = ws.get('layout') if ws else 'flat'
        ws_name = ws.get('name') if ws else ''
        ws_base = ws_root + ('/' + ws_name if ws_layout == 'named' and ws_name else '')

        dynamic_components = []
        for cname, cval in components.items():
            if cname in ('sim', 'lab', 'arena', 'gr00t', 'lerobot'):
                continue
            if cname not in selected:
                continue
            c_source = cval.get('source', {})
            c_dest = (
                _target_path(cval['install_dir'], home)
                if cval.get('install_dir')
                else f"{ws_base}/{REPO_DIRS.get(cname, cname.capitalize() if not cname[0].isupper() else cname)}"
            )
            comp_entry = {
                'id': cname,
                'type': c_source.get('mode', 'git'),
                'runtime': cval.get('runtime', 'lab'),
                'dest': c_dest,
                'repository': c_source.get('repository'),
                'ref': c_source.get('revision') or c_source.get('ref', ''),
                'upstream': cval.get('upstream', ''),
                'install_method': cval.get('install', {}).get('method', 'editable'),
                'install_command': cval.get('install', {}).get('command', ''),
                'desktop_shortcut': cval.get('desktop_shortcut'),
                'dependencies': cval.get('dependencies', []),
            }
            dynamic_components.append(comp_entry)

        from src.python.workstation_profile import ComponentDAGResolver
        ordered_components = ComponentDAGResolver.resolve_order(dynamic_components)
        artifact['profile_components'] = ordered_components
        artifact['profile_components_json'] = json.dumps(ordered_components, sort_keys=True)
    # SERVING: optional consumer of one explicitly selected immutable API only.
    # No source/ref or preset is substituted, and mapping does not activate it.
    if profile.get('serving', {}).get('enabled'):
        from src.python.gr00t_serving import validate_config
        serving_config = {'source': deepcopy(components.get('gr00t', {}).get('source', {})),
                          'serving': deepcopy(profile['serving']),
                          'cache_dir': home + '/.cache/isaac-gr00t/hub'}
        try:
            validate_config(serving_config)
            if 'gr00t' not in selected:
                raise ValueError('Serving requires the selected GR00T component')
        except ValueError as exc:
            subtree('serving', 'unsupported', 'Shared loopback/model serving contract unavailable: ' + str(exc))
        else:
            destination = 'gr00t_serving' if adapter == 'local' else 'profile_gr00t_serving'
            artifact[destination] = serving_config
            for field in coverage:
                if field.startswith('serving.'):
                    mark(field, consumer=destination + '.' + field,
                         reason='gr00t_serving.py explicit reviewed-source and activation gates; cache-only startup')
            model = profile['serving']['model']
            if model.get('revision'):
                mark('serving.model.ref', 'superseded', consumer=destination + '.serving.model.revision')
            else:
                mark('serving.model.revision', 'unspecified', reason='Explicit model ref consumed without an immutable model claim')
    if profile.get('draft'):
        mark('draft', 'unsupported', reason='Draft intent contains unresolved review decisions')
    if not profile.get('custom_dependencies'):
        mark('custom_dependencies', 'not_selected', reason='No custom dependencies selected')
    for index, item in enumerate(profile.get('custom_dependencies', [])):
        prefix = f'custom_dependencies.{index}'
        subtree(prefix, 'unsupported',
                'Custom dependency has no matching installation consumer', required=item['required'])
        environment = runtimes.get('lab', {}).get('environment')
        expected_location = home + '/miniconda3/envs/' + (environment or '')
        if (adapter == 'local' and 'lab' in selected_runtimes and environment == 'isaaclab'
                and item['placement'] == 'environment' and item['source'] == 'pypi'
                and item['environment'] == environment and item['location'] is None
                and item['version'] is not None
                and re.fullmatch(r'[0-9]+(?:\.[0-9]+)+(?:[A-Za-z0-9.+-]*)', item['version'])
                and item['name'].lower().replace('_', '-') not in ('torch', 'torchvision', 'pip', 'uv', 'python')):
            runtime_out = artifact['runtimes']['lab']
            runtime_out['packages'] = '\n'.join(filter(None, (
                runtime_out.get('packages'), item['name'] + '==' + item['version'])))
            for key in item:
                mark(prefix + '.' + key, 'mapped', consumer='runtimes.lab.packages',
                     reason='Exact direct package in resolved Lab environment; --no-deps prevents runtime upgrades',
                     required=item['required'])
            for key in ('id', 'purpose', 'required', 'support'):
                mark(prefix + '.' + key, 'metadata', reason='Review declaration retained in coverage', required=item['required'])
        if (adapter == 'ansible' and 'lab' in selected_runtimes
                and item['placement'] == 'environment' and item['source'] == 'pypi'
                and item['environment'] == environment
                and (item['location'] is None or _target_path(item['location'], home) == expected_location)
                and item['version'] is not None
                and re.fullmatch(r'[0-9]+(?:\.[0-9]+)+(?:[A-Za-z0-9.+-]*)', item['version'])
                and item['name'].lower().replace('_', '-') not in ('torch', 'torchvision', 'pip', 'uv', 'python')):
            artifact.setdefault('profile_lab_packages', []).append(item['name'] + '==' + item['version'])
            for key in item:
                mark(prefix + '.' + key, 'mapped', consumer='profile_lab_packages', required=item['required'])
            for key in ('id', 'purpose', 'required', 'support'):
                mark(prefix + '.' + key, 'metadata', reason='Review declaration retained in coverage', required=item['required'])
    for section in ('environments', 'notes', 'repositories'):
        if not profile.get(section):
            mark(section, 'not_selected', reason='No declarations selected')
        for index, item in enumerate(profile.get(section, [])):
            prefix = f'{section}.{index}'
            subtree(prefix, 'unsupported',
                    'Declaration retained for review; no matching consumer', required=item['required'])
            environment = runtimes.get('lab', {})
            if (section == 'environments' and adapter == 'ansible' and 'lab' in selected_runtimes
                    and item['manager'] == 'conda' and item['placement'] == 'environment'
                    and item['name'] == environment.get('environment')
                    and item['python'] == environment.get('python')
                    and _target_path(item['location'], home) == home + '/miniconda3/envs/' + item['name']):
                for key in item:
                    mark(prefix + '.' + key, 'mapped', consumer='conda role environment', required=item['required'])
                for key in ('id', 'required', 'support'):
                    mark(prefix + '.' + key, 'metadata', reason='Reviewed declaration', required=item['required'])
    if adapter == 'local':
        artifact['simulation'].setdefault('isaacsim', {'enabled': False})
        for name in LEGACY_NAMES.values():
            artifact['repositories'].setdefault(name, {'enabled': False})
    lab_runtime = runtimes.get('lab', {})
    if adapter == 'ansible' and 'lab' in selected_runtimes:
        cuda = lab_runtime.get('cuda_runtime')
        if cuda is not None:
            mismatch = not re.fullmatch(r'[0-9]+\.[0-9]+', cuda)
            for key in ('torch', 'torchvision'):
                pin = lab_runtime.get(key) or ''
                if '+cu' in pin and pin.split('+cu')[-1] != cuda.replace('.', ''):
                    mismatch = True
            if mismatch:
                mark('runtimes.lab.cuda_runtime', 'unsupported', reason='CUDA wheel channel conflicts with requested wheel pins')
    missing = []
    for name in sorted(selected):
        component = components[name]
        path = 'components.' + name
        source = component.get('source', {})
        if not source:
            missing.append({'field': path + '.source', 'reason': 'Enabled component requires explicit source intent'})
        else:
            required_keys = ('mode', 'version') if source.get('mode') == 'standalone' else ('mode', 'repository')
            for key in required_keys:
                if not source.get(key):
                    missing.append({'field': path + '.source.' + key, 'reason': 'Required source field absent'})
            if adapter == 'local' and name == 'sim' and source.get('mode') == 'standalone' and (source.get('url') or source.get('sha256')):
                for field in ('url', 'sha256'):
                    if field not in source:
                        missing.append({'field': path + '.source.' + field,
                                        'reason': 'Explicit local archive overrides require a URL/checksum pair'})
            if adapter == 'ansible' and name == 'sim' and source.get('mode') == 'standalone':
                for field in ('sha256', 'url'):
                    if field not in source:
                        missing.append({'field': path + '.source.' + field, 'reason': 'Explicit archive ' + field + ' required for Ansible standalone transport'})
            if source.get('mode') == 'git' and not (source.get('ref') or source.get('revision')):
                missing.append({'field': path + '.source.ref', 'reason': 'Required Git selector absent'})
        for key in ('runtime', 'execution'):
            if not component.get(key):
                missing.append({'field': path + '.' + key, 'reason': 'Required execution/runtime binding absent'})
        runtime = runtimes.get(component.get('runtime'), {})
        for key in ('manager', 'environment'):
            if not runtime.get(key):
                missing.append({'field': 'runtimes.' + str(component.get('runtime', name)) + '.' + key,
                                'reason': 'Selected runtime requires explicit manager and environment'})
    blockers = missing + [{'field': path, 'reason': item.get('reason', 'No matching consumer')}
                for path, item in coverage.items() if item['status'] == 'unsupported' and item['required']]
    warnings = [{'field': path, 'reason': item.get('reason', 'No matching consumer')}
                for path, item in coverage.items() if item['status'] == 'unsupported' and not item['required']]
    return {'adapter': adapter, 'artifact': artifact, 'deploy_params': deploy_params,
            'coverage': coverage, 'blockers': blockers, 'warnings': warnings,
            'render_supported': not blockers, 'apply_supported': False,
            'runtime_verified': False, 'references_verified': False}
