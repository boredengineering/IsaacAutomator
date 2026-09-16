"""Validate portable host evidence and propose intent without reading its paths.

Only the explicitly selected local JSON report is an observed root. Embedded
host paths are remote evidence/data, not local filesystem grants or health proof.
No installer, package manager, observed environment, or collector is imported.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import PurePosixPath
import re

# Exact destination contract used by src/python/profile_adapters.py:REPO_DIRS.
# A discovered nonconventional path is retained, never silently renamed to it.
REPO_DIRS = {'lab': 'IsaacLab', 'arena': 'IsaacLab-Arena', 'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot'}


class InventoryError(ValueError):
    """Fixed, nonsecret input diagnostics."""


def require(condition):
    if not condition:
        raise InventoryError('Invalid host inventory report.')


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def text(value, pattern=r'[A-Za-z0-9][A-Za-z0-9_.+~:-]*', maximum=256):
    require(type(value) is str and len(value) <= maximum and re.fullmatch(pattern, value) is not None)
    require(re.search(r'(?i)(?:token|password|secret|credential|bearer)[=_:-]|gh[pousr]_|sk-', value) is None)


def path(value, root=False):
    if root and value == '/':
        return
    # Host labels are data, not the deliberately narrower local-read grammar.
    text(value, r'/.*', 4096)
    require(value.isprintable())
    require(all(p not in ('', '.', '..') for p in value.split('/')[1:]))
    # Selected system ancestors such as /var are valid raw labels; '/' remains
    # an explicit root=True exception, never a general evidence/local-read path.
    require(len(PurePosixPath(value).parts) >= 2)


def inside(value, parent):
    return value == parent or value.startswith(parent.rstrip('/') + '/')


def array(value, limit=20000):
    require(type(value) is list and len(value) <= limit)


def unique(items, key):
    require(len({key(item) for item in items}) == len(items))


def package(value, system=False):
    shape(value, {'name', 'version', 'architecture', 'manual'} if system else {'name', 'version'})
    text(value['name'], r'[A-Za-z0-9][A-Za-z0-9_.+:-]*', 128)
    text(value['version'], r'[A-Za-z0-9][A-Za-z0-9_.!+~:-]*')
    if system:
        text(value['architecture'], r'[A-Za-z0-9][A-Za-z0-9_-]*', 64)
        require(value['manual'] is None or type(value['manual']) is bool)


def validate_report(report):
    require(type(report) is dict)
    shape(report, {'schema_version', 'kind', 'context', 'workspace', 'repositories',
                   'isaacsim', 'machine', 'packages', 'environments', 'coverage'} |
          ({'details'} if 'details' in report else set()))
    require(type(report['schema_version']) is int and report['schema_version'] == 1)
    require(report['kind'] == 'host-inventory')
    shape(report['context'], {'home', 'system_root', 'identity', 'execution_authorized'})
    context = report['context']
    path(context['home']); path(context['system_root'], root=True)
    require(context['identity'] in ('fixture', 'user-supplied-host'))
    require(context['execution_authorized'] is False)
    require((context['identity'] == 'fixture') == (context['system_root'] != '/'))
    ws = report['workspace']
    shape(ws, {'parent', 'candidates', 'selected'})
    path(ws['parent'])
    require(ws['parent'] == context['home'] + '/Documents/GitHub')
    array(ws['candidates'], 128)
    for candidate in ws['candidates']:
        path(candidate)
        require(str(PurePosixPath(candidate).parent) == ws['parent'])
    unique(ws['candidates'], lambda p: p)
    require(ws['selected'] is None or len(ws['candidates']) == 1 and ws['selected'] == ws['candidates'][0])
    array(report['repositories'], 128)
    for repo in report['repositories']:
        shape(repo, {'path', 'component', 'repository', 'ref', 'commit', 'dirty'})
        path(repo['path'])
        require(any(inside(repo['path'], c) for c in ws['candidates']))
        require(repo['component'] in (None, 'lab', 'arena', 'gr00t', 'lerobot'))
        require(repo['dirty'] == 'unknown')
        if repo['repository'] is not None:
            text(repo['repository'], r'https://github\.com/[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.git', 512)
        if repo['ref'] is not None:
            text(repo['ref'], r'refs/[A-Za-z0-9_./-]+', 256)
            require(all(p not in ('', '.', '..') for p in repo['ref'].split('/')))
        if repo['commit'] is not None:
            text(repo['commit'], r'(?:[a-f0-9]{40}|[a-f0-9]{64})', 64)
    unique(report['repositories'], lambda r: r['path'])
    array(report['isaacsim'], 16)
    for sim in report['isaacsim']:
        shape(sim, {'path', 'version'})
        path(sim['path']); require(inside(sim['path'], context['home']))
        if sim['version'] is not None:
            text(sim['version'], r'[A-Za-z0-9][A-Za-z0-9_.+-]*', 64)
    unique(report['isaacsim'], lambda s: s['path'])
    require(type(report['machine']) is dict and set(report['machine']) <= {
        'os', 'os_id', 'os_version', 'kernel', 'cpu', 'memory', 'driver', 'cuda_toolkit', 'gpu', 'container'})
    for fact in report['machine'].values():
        shape(fact, {'value', 'source'}); path(fact['source'])
        values = fact['value'] if type(fact['value']) is list else [fact['value']]
        array(values, 32)
        for value in values:
            if type(value) is str:
                text(value, r'[A-Za-z0-9][A-Za-z0-9 _.,:/()+~-]*', 512)
            else:
                require(value is None or type(value) in (int, bool))
                if type(value) is int:
                    require(0 <= value < 2**64)
    array(report['packages'])
    for item in report['packages']:
        package(item, system=True)
    unique(report['packages'], lambda p: (p['name'], p['architecture']))
    array(report['environments'], 32)
    for env in report['environments']:
        shape(env, {'path', 'name', 'manager', 'python', 'packages'})
        path(env['path']); require(inside(env['path'], context['home']))
        text(env['name'], r'[A-Za-z0-9_][A-Za-z0-9_.-]*', 128)
        require(env['manager'] in ('conda', 'venv', 'unknown'))
        if env['python'] is not None:
            text(env['python'], r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', 32)
        array(env['packages'])
        for item in env['packages']:
            package(item)
        unique(env['packages'], lambda p: p['name'])
    unique(report['environments'], lambda e: e['path'])
    coverage = report['coverage']
    shape(coverage, {'complete', 'issues', 'limits'})
    require(type(coverage['complete']) is bool)
    array(coverage['issues'], 20000)
    for issue in coverage['issues']:
        shape(issue, {'code', 'path'})
        text(issue['code'], r'[a-z][a-z0-9_-]*', 80); path(issue['path'], root=True)
    require(not coverage['complete'] or not coverage['issues'])
    shape(coverage['limits'], {'max_entries', 'max_bytes', 'max_seconds', 'max_depth'})
    for key, bound in {'max_entries': 100000, 'max_bytes': 67108864, 'max_seconds': 120, 'max_depth': 16}.items():
        value = coverage['limits'][key]
        require(type(value) in ((int, float) if key == 'max_seconds' else (int,)))
        require(math.isfinite(value) and 0 < value <= bound)
    if 'details' in report:
        validate_details(report)
    require(len(json.dumps(report, allow_nan=False).encode('utf-8')) <= 8 * 1024 * 1024)
    return report


def package_groups(packages):
    """Deterministic heuristic review hints, not native consumer/install intent.

    Members are name:architecture identities into packages and system_packages
    source/status evidence. No array position or manual flag implies necessity.
    """
    groups = {k: [] for k in ('os-baseline', 'drivers-cuda', 'build-tools', 'optional-applications', 'uncertain')}
    for p in packages:
        name = p['name']
        if name.startswith(('nvidia-', 'libnvidia-', 'cuda-', 'libcuda', 'libcudnn', 'cudnn-')):
            group = 'drivers-cuda'
        elif name in ('build-essential', 'cmake', 'make', 'ninja-build', 'git', 'pkg-config', 'gcc', 'g++') or name.startswith(('gcc-', 'g++-')):
            group = 'build-tools'
        elif name in ('bash', 'coreutils', 'libc6', 'systemd', 'apt', 'dpkg') or name.startswith('linux-image-'):
            group = 'os-baseline'
        elif name in ('firefox', 'chromium', 'blender', 'vlc', 'code'):
            group = 'optional-applications'
        else:
            group = 'uncertain'
        groups[group].append(name + ':' + p['architecture'])
    return {'basis': 'name-heuristic-review-only', 'groups': {k: sorted(v) for k, v in groups.items()}}


def followups(report):
    """Named next-batch proposals only. Do not inspect these descriptors/targets."""
    result = {}
    def add(kind, path, records, target=None):
        key = hashlib.sha256((kind + '\0' + path).encode()).hexdigest()[:24]
        result[key] = {'kind': kind, 'path': path, 'target': target,
            'records': records, 'action': 'request-explicit-scope'}
    if report['workspace']['selected'] is None:
        add('workspace', report['workspace']['parent'], ['BoredEngineer', 'boredengineering'])
    if not report['isaacsim'] or any(s['version'] is None for s in report['isaacsim']):
        add('isaacsim', report['context']['home'] + '/IsaacSim', ['VERSION'])
    unresolved_refs = set()
    for repo in report['repositories']:
        if repo['repository'] is None or repo['commit'] is None:
            add('repository-metadata', repo['path'], ['.git/HEAD', '.git/config'])
        if repo['ref'] and repo['commit'] is None:
            unresolved_refs.add(repo['path'] + '/.git/' + repo['ref'])
    for issue in report['coverage']['issues']:
        code, path = issue['code'], issue['path']
        if (code == 'unsupported-worktree' and path.endswith('/.git') and
                any(path.startswith(c + '/') for c in report['workspace']['candidates'])):
            add('git-worktree', path, ['HEAD', 'config'])
        elif code == 'unresolved-ref' and path in unresolved_refs:
            add('repository-ref', path, ['loose-ref', 'packed-refs'])
    for path, link in report['details']['links'].items():
        add('linked-path', path, ['link-target-scope'], link['target'])
    for path in sorted({e['path'] for e in report['environments']} | {r['path'] for r in report['repositories']}):
        add('environment-descriptors', path, ['pyproject.toml', 'uv.lock', 'environment.yml'])
    for env in report['environments']:
        add('editable-metadata', env['path'], ['direct_url.json', '*.pth'])
    return dict(sorted(result.items())[:128])


def validate_details(report):
    """Pure lexical binding of claimed selected sources, not source attestation.

    No embedded path is opened. Map keys are record identities, never array indexes.
    Field selectors are fixed: HEAD/ref commit, origin.url, VERSION, package
    name/version, pyvenv version/version_info, dpkg Package/Architecture/Version/
    Status and APT Package/Architecture/Auto-Installed. Null facts remain unknown.
    """
    d = report['details']
    shape(d, {'version', 'repositories', 'isaacsim', 'environments', 'system_packages', 'links', 'followups', 'package_groups'})
    require(type(d['version']) is int and d['version'] == 1)
    for section in ('repositories', 'isaacsim', 'environments'):
        shape(d[section], {r['path'] for r in report[section]})
    for r in report['repositories']:
        base = r['path'] + '/.git/'
        require(d['repositories'][r['path']] == {
            'head': base + 'HEAD', 'config': base + 'config',
            'ref': base + r['ref'] if r['ref'] else None})
        if r['ref']:
            require(re.fullmatch(r'refs/(heads|tags)/[A-Za-z0-9_./-]{1,200}', r['ref']) is not None)
    for r in report['isaacsim']:
        require(r['path'] == report['context']['home'] + '/IsaacSim')
        require(d['isaacsim'][r['path']] == {'version': r['path'] + '/VERSION'})
    home = report['context']['home']
    selected_envs = {r + '/.venv' for r in report['workspace']['candidates']}
    selected_envs.update(r['path'] + '/.venv' for r in report['repositories'])
    seeds = [home + '/' + s for s in ('miniconda3', 'anaconda3', 'miniforge3', 'mambaforge')]
    for env in report['environments']:
        base = env['path']
        require(base in selected_envs or base in seeds or
                str(PurePosixPath(base).parent) in [s + '/envs' for s in seeds] + [home + '/.conda/envs'])
        evidence = d['environments'][base]
        shape(evidence, {'python', 'packages'})
        shape(evidence['packages'], {p['name'] for p in env['packages']})
        for source in evidence['packages'].values():
            path(source)
            if env['manager'] == 'conda':
                require(str(PurePosixPath(source).parent) == base + '/conda-meta')
                require(PurePosixPath(source).name.endswith('.json') and not PurePosixPath(source).name.startswith('.'))
            else:
                require(env['manager'] == 'venv' and source.startswith(base + '/'))
                require(re.fullmatch(r'lib/python[0-9]+\.[0-9]+/site-packages/[^/.][^/]*\.dist-info/METADATA', source[len(base)+1:]) is not None)
        if env['manager'] == 'conda':
            require(evidence['python'] == (evidence['packages'].get('python') if env['python'] is not None else None))
            if env['python'] is not None:
                require(any(p['name'] == 'python' and p['version'] == env['python'] for p in env['packages']))
        elif env['manager'] == 'venv':
            require(evidence['python'] == base + '/pyvenv.cfg')
        else:
            require(evidence == {'python': None, 'packages': {}} and env['python'] is None)
    root = report['context']['system_root'].rstrip('/')
    s = d['system_packages']
    shape(s, {'status_source', 'manual_source', 'status'})
    require(s['status_source'] == root + '/var/lib/dpkg/status')
    require(s['manual_source'] == root + '/var/lib/apt/extended_states')
    shape(s['status'], {p['name'] + ':' + p['architecture'] for p in report['packages']})
    require(all(v in ('install ok installed', 'hold ok installed') for v in s['status'].values()))
    sources = {'os': ('etc/os-release', 'usr/lib/os-release'),
        'os_id': ('etc/os-release', 'usr/lib/os-release'), 'os_version': ('etc/os-release', 'usr/lib/os-release'),
        'kernel': ('proc/sys/kernel/osrelease',), 'cpu': ('proc/cpuinfo',), 'memory': ('proc/meminfo',),
        'driver': ('proc/driver/nvidia/version',), 'gpu': ('proc/driver/nvidia/version',),
        'cuda_toolkit': ('usr/local/cuda/version.json',), 'container': ('run/systemd/container',)}
    for key, fact in report['machine'].items():
        require(fact['source'] in [root + '/' + p for p in sources[key]])
    require(type(d['links']) is dict and len(d['links']) <= 128)
    selected_home = [home + '/Documents/GitHub', home + '/IsaacSim', home + '/.conda'] + seeds
    selected_system = [root + '/' + p for ps in sources.values() for p in ps]
    selected_system += [s['status_source'], s['manual_source']]
    for label, link in d['links'].items():
        path(label)
        # Ancestors are evidence only, and must remain inside declared scope.
        require((inside(label, home) and any(inside(label, p) or inside(p, label) for p in selected_home)) or
                any(inside(p, label) and inside(label, root or '/') for p in selected_system))
        require({'code': 'symlink-skipped', 'path': label} in report['coverage']['issues'])
        shape(link, {'target', 'status'})
        if link['target'] is None:
            require(link['status'] == 'redacted')
        else:
            text(link['target'], r'.*', 4096)
            require(link['target'].isprintable() and not link['target'].startswith('//'))
            require(all(p not in ('', '.', '..') for p in link['target'].lstrip('/').split('/')))
            require(link['status'] == 'recorded')
    require(d['followups'] == followups(report))
    require(d['package_groups'] == package_groups(report['packages']))


def baseline(report, report_path, discovery, previous=None):
    """Create an import observation, never relabel it a live directory scan."""
    validate_report(report); discovery._path(report_path)
    roots = discovery.original_observed_roots(previous) if previous is not None else []
    report = deepcopy(report)
    # Enumeration order is not changed evidence or an environment's identity.
    for key, order in (('repositories', lambda r: r['path']), ('isaacsim', lambda s: s['path']),
                       ('environments', lambda e: e['path']),
                       ('packages', lambda p: (p['name'], p['architecture']))):
        report[key].sort(key=order)
    report['workspace']['candidates'].sort()
    report['coverage']['issues'].sort(key=lambda i: (i['path'], i['code']))
    for env in report['environments']:
        env['packages'].sort(key=lambda p: p['name'])
    complete = report['coverage']['complete']
    observation = {'id': 'host:inventory', 'status': 'observed' if complete else 'unknown',
                   'value': deepcopy(report),
                   'evidence': {'method': 'imported-host-inventory', 'path': report_path}}
    return discovery._document('workstation-baseline', target='imported-host',
        limits=dict(discovery.DEFAULT_LIMITS), original_observed_roots=sorted(set(roots + [report_path])),
        incomplete=not complete, collected_at=datetime.now(timezone.utc).isoformat(),
        observations=[observation])


def propose_fields(item, discovery):
    """Useful proposals and grouped backlog. No field is automatically accepted."""
    report = validate_report(item['value'])
    fields = []
    def add(identifier, value, required=False):
        try:
            discovery._field_value(identifier, value)
        except ValueError:
            value = None
        fields.append(discovery._field(identifier, value, [item['id']], required,
            'selected_metadata_does_not_establish_required_intent'))
    ws = report['workspace']
    add('workspace:host.root', ws['parent'], True)
    selected_name = PurePosixPath(ws['selected']).name if ws['selected'] else None
    if selected_name is not None:
        try:
            discovery._field_value('workspace:host.name', selected_name)
        except ValueError:
            # Observation paths have a broader grammar than desired workspace
            # names. Retain their exact evidence and ask for supported intent.
            selected_name = None
    add('workspace:host.name', selected_name, True)
    add('workspace:host.layout', 'named', True)
    for repo in report['repositories']:
        if repo['component'] is None:
            continue
        if ws['selected'] is None or repo['path'] != ws['selected'] + '/' + REPO_DIRS[repo['component']]:
            key = 'hostpath' + hashlib.sha256(repo['path'].encode()).hexdigest()[:16]
            add('note:' + key + ':0', 'Existing repository path differs from conventional consumer destination. '
                'Review the preserved host path before choosing any installation target.', required=True)
        value = None
        if repo['repository'] is not None and repo['commit'] is not None and len(repo['commit']) == 40:
            value = {'mode': 'git', 'repository': repo['repository'],
                     'ref': repo['commit'], 'revision': repo['commit']}
        add('component:' + repo['component'] + '.source', value)
    if 'details' in report:
        for key, proposal in sorted(report['details']['followups'].items()):
            add('note:hostscope' + key + ':0', 'Request explicit scope review for ' + proposal['kind'] +
                '. See baseline host inventory details followups ' + key +
                ' for the exact path and selected records. No additional read is approved.')
    if 'details' not in report:
        add('note:host:3', 'Older limited evidence lacks selected source details. No per-fact source proof is available.')
    # Existing merge logic handles multiple component sources; sources stay optional.
    add('note:host:0', 'Machine configuration retained in host inventory. Compatibility is unverified.')
    add('note:host:1', 'System package inventory retained - ' + str(len(report['packages'])) +
        ' packages. Presence and manual marking do not approve installation.')
    for group, members in package_groups(report['packages'])['groups'].items():
        if members:
            add('note:hostgroup' + group + ':0', 'Package review hint ' + group + ' - ' + str(len(members)) +
                ' members. See baseline host inventory details package_groups for identities and packages for evidence. '
                'Name heuristics are uncertain and never installation intent.')
    for sim in report['isaacsim']:
        key = 'hostsim' + hashlib.sha256(sim['path'].encode()).hexdigest()[:16]
        add('note:' + key + ':0', 'IsaacSim installation found. Version and path retained in inventory. '
            'Source archive and runtime health remain unknown.')
    for env in report['environments']:
        key = 'hostenv' + hashlib.sha256(env['path'].encode()).hexdigest()[:16]
        identity = 'environment:' + key
        environment_value = {'name': env['name'], 'manager': env['manager'],
            'placement': 'environment', 'python': env['python'], 'location': env['path']}
        try:
            discovery._field_value(identity, environment_value)
        except ValueError:
            environment_value = None
        add(identity, environment_value)
        # Tools use the existing optional review/export path; cap proposals, retain
        # the full bounded package inventory in the original host observation.
        for package_info in env['packages'][:32]:
            try:
                value = {**package_info, 'source': None, 'purpose': None,
                         'environment': env['name'], 'placement': 'environment', 'location': env['path']}
                identifier = 'tool:' + key + ':' + package_info['name']
                discovery._field_value(identifier, value)
            except ValueError:
                continue
            add(identifier, value)
        if len(env['packages']) > 32:
            add('note:' + key + ':0', 'Only the first 32 package proposals are shown. Full inventory retained for further review.')
    if not report['coverage']['complete']:
        add('note:host:2', 'Host collection is incomplete. Inspect coverage issues before accepting intent.')
    return fields
