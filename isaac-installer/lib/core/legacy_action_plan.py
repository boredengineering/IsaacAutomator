"""Pure legacy CFG_* intent, NOT an executor or a host observation.

Only the caller's flattened profile and selected stage rows are consumed. No
installer shell is sourced and no target paths, environment or metadata are read.
/target-home is a symbolic binding in the legacy CLI (which has no --target-home).
The pure API accepts an explicit home for consumer-conformance tests.
"""
import re
from pathlib import Path

from workspace_paths import expand_path, resolve_paths


REPOSITORIES = (
    ('isaaclab', 'isaaclab', 'IsaacLab', 'https://github.com/isaac-sim/IsaacLab.git', 'main', '', 'ISAAC_LAB_REPO', False),
    ('arena', 'arena', 'IsaacLab-Arena', 'https://github.com/isaac-sim/IsaacLab-Arena.git', 'release/0.3.0-prerelease', '', 'ISAACLAB_ARENA_REPO', True),
    ('lerobot', 'physical_ai', 'lerobot', 'https://github.com/huggingface/lerobot.git', 'main', 'v0.4.3', 'ECOSYSTEM_LEROBOT_REPO', False),
    ('gr00t', 'gr00t', 'Isaac-GR00T', 'https://github.com/NVIDIA/Isaac-GR00T.git', 'main', '', '', True),
)


def build_legacy_action_plan(config, stages, workspace, *, target_home='/target-home'):
    """Return potential native effects; selected never means would-change/safe."""
    home = str(expand_path(target_home, ''))
    actions = []
    consumed = set()
    selection = {row['stage']: row for row in stages}

    def value(key, default=''):
        key = 'CFG_' + key
        if key in config:
            consumed.add(key)
        return config.get(key) or default  # shell ${value:-default}, not dict.get

    def add(identifier, stage, operation, target, desired, effects, blockers=(), enabled=True):
        row = selection.get(stage)
        selected = enabled and (row is None or row['status'] != 'excluded')
        action: dict = dict(id=identifier, stage=stage, selected=selected,
                      status='unknown' if selected else 'excluded', operation=operation,
                      target=target, desired=desired, effects=effects,
                      overwrite_effects='potential native effects only; existing content/ownership unknown',
                      approval_required=['independent safety review', 'explicit physical-run approval'],
                      blockers=['native operation unqualified; execution denied', 'target state not inspected', *blockers],
                      execution_supported=False, execution_authorized=False,
                      evidence='flattened-profile+native-consumer-contract',
                      reason=(row['reason'] if row and not selected else 'profile intent only; host checks not run'))
        if not enabled:
            action['reason'] = 'Disabled by native subaction selection.'
        actions.append(action)
        return action

    workspace_selected = any(row['status'] != 'excluded' for row in stages
                             if row['stage'] in ('isaaclab', 'arena', 'physical_ai', 'gr00t', 'python', 'demos'))
    settings = {key: workspace[key]['value'] for key in ('root', 'layout', 'name', 'default_owner')}
    if settings['root']:
        root = str(expand_path(settings['root'], home))
        add('workspace.root', 'workspace', 'workspace_prepare', root, settings,
            ['native checkout may create workspace parents; ownership behavior requires review'], enabled=workspace_selected)
        if settings['layout'] == 'named':
            add('workspace.group', 'workspace', 'workspace_prepare', str(Path(root) / settings['name']), settings,
                ['native checkout may create named group directory; named application remains denied'], enabled=workspace_selected)
    destinations = {}
    for name, stage, directory, upstream, branch, tag, alias, recursive in REPOSITORIES:
        prefix = 'REPOSITORIES_' + name.upper() + '_'
        repository = value(prefix + 'REPO', value(alias, upstream) if alias else upstream)
        branch, tag = value(prefix + 'BRANCH', branch), value(prefix + 'TAG', tag)
        url = 'https://github.com/' + repository + '.git' if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) else repository
        desired = dict(repository=repository, url=url, upstream=value(prefix + 'UPSTREAM', upstream),
                       branch=branch, tag=tag, ref=tag or branch, ref_kind='tag' if tag else 'branch',
                       recursive=recursive, immutable_revision=None)
        resolution = resolve_paths(home=home, repo=directory, slug=repository, root=settings['root'],
                                   layout=settings['layout'], name=settings['name'], configured_owner=settings['default_owner'])
        destinations[name] = resolution['destination']
        action = add('repository.' + name, stage, 'repository_checkout', resolution['destination'], desired,
                     ['clone/fetch repository; configure origin/upstream; checkout requested ref',
                      'existing checkout may be changed; optional remote fork and Desktop registration require separate review'],
                     ['branch/tag is not a verified immutable revision', resolution['reason']] if not resolution['destination'] else ['branch/tag is not a verified immutable revision'])
        action['path_resolution'] = resolution
        action['blockers'].append('remote/auth checks and fork fallback may change effective clone URL; requested URL is not observed origin')
        add('repository.' + name + '.fork', stage, 'remote_fork', url,
            dict(upstream=desired['upstream'], auto_create=value('WORKSPACE_AUTO_CREATE_FORK', 'true') == 'true'),
            ['conditionally create remote GitHub fork; fallback may clone upstream'],
            ['network/authentication/external-account mutation unqualified'],
            enabled=value('WORKSPACE_AUTO_CREATE_FORK', 'true') == 'true' and url != desired['upstream'])
        add('repository.' + name + '.desktop', stage, 'desktop_register', resolution['destination'], {},
            ['invoke GitHub Desktop --add with selected repository path'],
            ['desktop process/session and repository existence not inspected'],
            enabled=value('WORKSPACE_AUTO_REGISTER_GITHUB_DESKTOP', 'true') == 'true')
    def child(parent, suffix):
        return str(Path(parent) / suffix) if parent else None

    sim_version = value('SIMULATION_ISAACSIM_VERSION', '6.0.1')
    sim_source = value('SIMULATION_ISAACSIM_SOURCE_TYPE', 'standalone')
    sim_path = value('SIMULATION_ISAACSIM_INSTALL_DIR', value('ISAAC_SIM_INSTALL_PATH'))
    sim_target = str(expand_path(sim_path, home)) if sim_path else None
    custom_path = value('SIMULATION_ISAACSIM_CUSTOM_BUILD_SOURCE_PATH')
    custom_target = str(expand_path(custom_path, home)) if custom_path else None
    if sim_source == 'custom_build':
        # resolve_isaacsim_dir prefers this only if it exists; do not assert it.
        sim_target = None
    sim_blockers = [] if sim_target else ['existing Sim discovery/custom-source existence not observed; install prefix unresolved']
    zip_name = 'isaac-sim-standalone-' + sim_version + '-linux-x86_64.zip'
    archive_url = value('SIMULATION_ISAACSIM_URL')
    archive_sha = value('SIMULATION_ISAACSIM_SHA256')
    explicit_archive = bool(archive_url or archive_sha)
    archive = add('sim.archive', 'isaacsim', 'artifact_install', sim_target,
        dict(version=sim_version, source_type=sim_source,
             url=archive_url if explicit_archive else 'https://download.isaacsim.omniverse.nvidia.com/' + zip_name,
             sha256=archive_sha or None, archive_name=zip_name,
             cache_path=None if explicit_archive else home + '/isaacsim-pkg/' + zip_name,
             fallback_install_path=home + ('/IsaacSim-5.1.0' if sim_version == '5.1.0' else '/IsaacSim')),
        ['download and extract archive; legacy unzip may overwrite existing files',
         'legacy default path may recursively chown install/cache directories; explicit archive requires new target'],
        [*sim_blockers, 'archive safety, integrity and platform compatibility unqualified'], enabled=sim_source != 'custom_build')
    if sim_source != 'standalone' and explicit_archive:
        archive['blockers'].append('native explicit archive overrides require standalone source type')
    if explicit_archive and (not archive_url or not re.fullmatch('[a-f0-9]{64}', archive_sha)):
        archive['blockers'].append('native explicit archive requires URL and lowercase SHA256')
    add('sim.custom_source', 'isaacsim', 'custom_source_review', custom_target,
        dict(source_type=sim_source), ['native custom source validation/build is unqualified; executable profile fields are refused'],
        ['custom-source existence and launcher identity unknown'], enabled=sim_source == 'custom_build')
    add('sim.eula', 'isaacsim', 'accept_eula', child(sim_target, '.eula_accepted'), {},
        ['create NVIDIA EULA acceptance marker'], [*sim_blockers, 'separate EULA approval required'])
    add('sim.post_install', 'isaacsim', 'source_script', child(sim_target, 'post_install.sh'), {},
        ['execute vendor post_install.sh if executable; downstream effects unknown'],
        [*sim_blockers, 'source-script execution is not qualified'], enabled=sim_source != 'custom_build')

    pin_fields = ('python', 'torch', 'torchvision', 'cuda_runtime', 'architecture', 'packages')
    pins = {key: value('RUNTIMES_LAB_' + key.upper()) for key in pin_fields}
    source_pinned = 'CFG_RUNTIMES_LAB_ENVIRONMENT' in config or any(pins.values())
    # install_python_env omits packages from its branch predicate, whereas
    # profile_lab_pins_selected (Lab/Arena) includes it. Expose that mismatch.
    pinned = 'CFG_RUNTIMES_LAB_ENVIRONMENT' in config or any(pins[k] for k in pin_fields if k != 'packages')
    environment = value('RUNTIMES_LAB_ENVIRONMENT', 'isaaclab')
    runtime: dict = dict(manager='conda', environment=environment, **pins)
    runtime['python'] = pins['python'] or (None if pinned else '3.12' if sim_version.startswith('6.') else '3.10')
    runtime['python_basis'] = 'explicit or required-but-unspecified pin' if pinned else 'native Sim-major default (creation may delegate to Lab)'
    runtime['pin_aware'] = pinned
    runtime['wheel_index'] = 'https://download.pytorch.org/whl/cu' + pins['cuda_runtime'].replace('.', '') if pins['cuda_runtime'] else None
    runtime['prefix_expression'] = '<resolved-conda-root>/envs/' + environment
    runtime['fresh_install_candidate'] = home + '/miniforge3/envs/' + environment
    conda_blockers = ['Conda PATH/installation discovery not run; prefix unresolved']
    if source_pinned and not pinned:
        conda_blockers.append('packages-only native branch mismatch: Python provisioning ignores packages while Lab/Arena select pin-aware dependencies')
    if pinned and not pins['python']:
        conda_blockers.append('native new environment creation requires an explicit Python pin')
    if pinned and environment != 'isaaclab':
        conda_blockers.append('native pin-aware consumer refuses environments other than isaaclab')
    if not pinned:
        conda_blockers.append('torch/torchvision/CUDA versions depend on unknown GPU; no guessed wheel set')
    add('runtime.lab', 'python', 'environment_create', None, runtime,
        ['create or reuse selected Conda environment; install selected Python/wheels',
         'unpinned legacy branch may remove broken environments and upgrade packages'], conda_blockers)
    for name, relative in [('activate', 'etc/conda/activate.d/00_isaaclab_env.sh'),
                           ('deactivate', 'etc/conda/deactivate.d/00_isaaclab_env.sh')]:
        add('runtime.lab.' + name, 'python', 'write_config', None,
            dict(environment=environment, relative_target=relative),
            ['write/overwrite scoped environment hook; Vulkan settings depend on host'], conda_blockers)
    add('runtime.lerobot', 'physical_ai', 'environment_create', None,
        dict(manager='conda', environment='lerobot', python='3.10', prefix_expression='<conda-named-environment:lerobot>'),
        ['create/reuse named lerobot environment; upgrade/install visualization dependencies; editable source install'],
        ['named Conda environment discovery not run; native consumer fixes Python 3.10 and does not consume runtimes.lerobot overrides'])
    add('runtime.gr00t', 'gr00t', 'environment_sync', child(destinations['gr00t'], '.venv'),
        dict(manager='uv', source=destinations['gr00t'], python=None, version_source='repository lockfile and GPU branch; not read'),
        ['uv sync repository lockfile; hardware branch may replace torch/torchvision'],
        ['lockfile, existing venv and GPU not inspected'])
    add('lab.sim_link', 'isaaclab', 'replace_symlink', child(destinations['isaaclab'], '_isaac_sim'),
        dict(source=str(expand_path(sim_path, home)) if sim_path else home + '/IsaacSim'),
        ['stage and replace _isaac_sim symlink; change link ownership'],
        ['native Lab uses ISAACSIM_DIR or ~/IsaacSim, not Sim discovery; source existence unknown'])
    add('lab.extensions', 'isaaclab', 'editable_install', destinations['isaaclab'],
        dict(environment=environment, pin_aware=source_pinned, entrypoint='isaaclab.sh -i'),
        ['install editable Lab extensions and execute repository installer; dependency and GPU verification effects unqualified'], conda_blockers)
    add('arena.dependencies', 'arena', 'editable_install', destinations['arena'],
        dict(environment=environment if source_pinned else 'Lab/Sim discovered runtime(s)', pin_aware=source_pinned),
        ['install Arena editable source and WBC dependencies'], conda_blockers)
    add('arena.config', 'arena', 'write_config', child(destinations['arena'], '.env'),
        dict(condition='only when native -f test reports absent'), ['write Arena declarative .env template'],
        ['existing .env state unknown; template is not read by preview'])
    # Native system operations are listed as intent, never guessed package sets.
    system_blockers = ['machine-wide settings need separate maintenance approval',
                       'OS/package manager/GPU/service state unknown; package resolution not performed']
    def system(identifier, stage, operation, target, effect, enabled=True, **desired):
        desired.setdefault('packages', None)
        action = add(identifier, stage, operation, target, desired, [effect], system_blockers, enabled)
        action['approval_required'].append('machine-wide maintenance/settings permission')
        return action

    system('driver.blacklist', 'driver', 'write_config', '/etc/modprobe.d/blacklist-nouveau.conf',
           'overwrite nouveau blacklist and rebuild initramfs')
    system('driver.packages', 'driver', 'package_install', None,
           'select driver/kernel packages from GPU, kernel and package availability; enable persistence; schedule resume/reboot')
    system('display.gdm', 'display', 'edit_config', '/etc/gdm3/custom.conf',
           'conditionally disable Wayland in existing GDM configuration')
    system('display.edid', 'display', 'write_config', '/etc/X11/vdisplay.edid',
           'conditionally copy virtual EDID and generate Xorg configuration without physical monitor')
    add('display.xauthority', 'display', 'change_permissions', home + '/.Xauthority', {},
        ['touch .Xauthority, chmod 0666 and change ownership'], system_blockers)
    system('prereqs.packages', 'prereqs', 'package_install', None,
           'update package indexes and install build/graphics prerequisites; conditional Node.js setup script')
    scaffold = (
        'datasets/isaaclab_arena/locomanipulation_tutorial',
        'datasets/isaaclab_arena/sequential_static_manipulation_tutorial',
        'datasets/isaaclab_arena/static_apple_tutorial',
        'models/isaaclab_arena/locomanipulation_tutorial',
        'models/isaaclab_arena/sequential_static_manipulation_tutorial',
        'models/isaaclab_arena/dexsuite_lift', 'models/isaaclab_arena/reinforcement_learning',
        'models/isaaclab_arena/static_apple_tutorial',
        'eval/isaaclab_arena/locomanipulation_tutorial', 'eval/isaaclab_arena/camera_sensitivity',
        'data/neo4j', '.cache/huggingface', '.aws', '.config/gcloud', '.azure', '.config/gh', '.config/osmo')
    for index, relative in enumerate(scaffold):
        add('prereqs.scaffold.' + str(index), 'prereqs', 'mkdir_and_chown', home + '/' + relative, {},
            ['create directory if missing; native consumer recursively changes ownership even when existing'])
    system('prereqs.compilers', 'prereqs', 'update_alternatives', '/usr/bin/gcc',
           'change gcc and g++ system alternatives to GCC 11', companion_target='/usr/bin/g++')
    add('prereqs.git_lfs', 'prereqs', 'git_global_config', home + '/.gitconfig', {},
        ['git lfs install changes user Git configuration'], ['Git configuration redirection not inspected'])
    system('python.legacy_cleanup', 'python', 'remove_tree', '/opt/conda',
           'legacy branch may recursively delete /opt/conda and edit user/root environments.txt', enabled=not pinned)
    add('python.miniforge', 'python', 'runtime_install', None,
        dict(url='https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh',
             version=None, fallback_prefix=home + '/miniforge3'),
        ['download/execute Miniforge installer if Conda missing; conda init bash edits shell configuration'],
        conda_blockers, enabled=not pinned)
    system('python.shim', 'python', 'write_config', '/usr/local/bin/isaaclab-env',
           'overwrite runtime CLI shim and copy into installer distribution', environment=environment)
    for name, key, default in [('docker', '', 'true'), ('nvidia_container', '', 'true'),
                               ('storage', '', 'true'), ('github_cli', '', 'true'),
                               ('github_desktop', 'DEVTOOLS_GITHUB_DESKTOP', 'true'),
                               ('vscode', 'DEVTOOLS_VSCODE', 'true'), ('chromium', 'DEVTOOLS_CHROMIUM', 'true'),
                               ('aws', 'DEVTOOLS_CLOUD_CLIS_AWS', 'false'),
                               ('gcloud', 'DEVTOOLS_CLOUD_CLIS_GCLOUD', 'false'), ('discord', 'DEVTOOLS_DISCORD', 'false')]:
        system('tool.' + name, 'devtools', 'tool_install', None,
               'install/configure ' + name + '; repositories, keys, services/groups or extensions may change',
               enabled=value(key, default) == 'true' if key else True, tool=name)
    for name, key, default, filename in [
            ('ftdi', 'FTDI_1MS_LATENCY_RULE', 'true', '99-ftdi-latency.rules'),
            ('spacemouse', 'SPACEMOUSE_DAEMON', 'false', '99-spacenav.rules'),
            ('manus', 'MANUS_VR_GLOVES', 'false', '99-manus-gloves.rules'),
            ('realsense', 'REALSENSE_CAMERAS', 'false', '99-realsense.rules')]:
        system('hardware.' + name, 'hardware_teleop', 'write_config', '/etc/udev/rules.d/' + filename,
               'copy/overwrite device rules; SpaceMouse additionally installs/enables its daemon',
               enabled=value('TELEOPERATION_' + key, default) == 'true')
    system('hardware.groups', 'hardware_teleop', 'settings_change', None,
           'reload and trigger udev; create/join dialout, plugdev, input and video groups regardless of device toggles')
    system('hardware.cloudxr', 'hardware_teleop', 'tool_install', destinations['isaaclab'],
           'install OpenXR system libraries and isaacteleop[cloudxr,retargeters]~=1.0.0 via Lab runtime',
           enabled=value('TELEOPERATION_XR_CLOUDXR', 'false') == 'true')
    system('physical_ai.codecs', 'physical_ai', 'package_install', None,
           'install video codec development dependencies and optional global Hugging Face Python CLI')
    for name in ('lerobot-dataset-viz', 'huggingface-cli', 'hf'):
        system('physical_ai.wrapper.' + name, 'physical_ai', 'write_config', '/usr/local/bin/' + name,
               'overwrite CLI wrapper or symlink for named lerobot environment')
    system('gr00t.tools', 'gr00t', 'tool_install', '/usr/local/bin/uv',
           'install dependencies and uv; may copy/link uv/uvx into system bin and modify global Git LFS configuration')
    add('gr00t.submodules', 'gr00t', 'repository_submodules_lfs', destinations['gr00t'], {},
        ['initialize recursive Git submodules and fetch LFS objects'], ['network/repository execution unqualified'])
    add('demos.launchers', 'demos', 'write_config', home + '/.local/share/isaac-demos',
        dict(repository_targets=destinations if settings['layout'] == 'named' else None),
        ['create/overwrite demo scripts; recursively change directory ownership'],
        ['non-named launcher repository discovery and desktop availability not evaluated'])
    add('demos.desktop', 'demos', 'write_config', home + '/Desktop', {},
        ['create/overwrite six desktop shortcuts; chmod/chown and mark desktop entries trusted'],
        ['desktop existence/stage check not performed; existing unrelated desktop entries may be affected'])
    add('streaming.provider', 'streaming', 'streaming_install', None,
        dict(requested_provider=value('STREAMING_PROVIDER', 'none'), effective_provider='none'),
        ['no streaming installation selected by admitted legacy preview options'],
        ['profile streaming.provider is not consumed by native install dispatch; --stream remains unsupported in safe preview'], enabled=False)
    return dict(kind='legacy-installer-action-plan', version=1, target_home=home,
                home_binding='symbolic; not a detected account' if target_home == '/target-home' else 'caller-supplied; not observed',
                complete=False, execution_authorized=False, actions=actions,
                consumed_fields=sorted(consumed), unmapped_fields=sorted(set(config) - consumed),
                unqualified_native_operations=[a['id'] for a in actions])
