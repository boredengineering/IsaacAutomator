"""API-only selected rsync seed; never installed or exposed through a CLI.

Construction is lexical and pure. Literal activation and exact caller review are
required on EVERY seed. Review fields are future caller attestations, NOT crypto
identity, backup verification or evidence that another writer actually stopped.

This one-shot adapter consumes the shared plan's rsync argv and SSH/IAP builder.
It does not discover credentials or modify settings. The fixed read-only Python
probe runs in isolated mode, over SSH for remote roots, with JSON selection on
stdin: no helper file or arbitrary command is installed on the target. Existing
roots, Linux/POSIX no-follow support, /usr/bin/python3 and rsync 3.x are required.
Deletion and continuous engines are deliberately unsupported. Independent writers
must be stopped by the caller; observations are not a distributed lock or atomic
transaction. Every selected SSH/IAP seed additionally holds a persistent remote
cooperative DatasetLock lease; a test runner must supply an explicit fake Popen
lease factory or execution is refused. Native .stfolder roots are refused unless
borrowing an exact, observed paused RemoteSupervisor session. Exceptions may
follow a partial transfer; there is no auto rollback.

Verification covers included regular-file SHA-256 bytes and directory shape,
source drift, retained destination bytes, and excluded entry metadata only.
Excluded directories are NOT descended and protected bytes are NEVER hashed.
This is filename policy, not secret scanning or adversarial filesystem confinement.
"""
from contextlib import ExitStack
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import tempfile

from src.python.file_transfer import TransferEndpoint
from src.python.remote_development import _overlap, build_plan
from src.python.dataset_lock import DatasetLock


# Fixed code, not a caller hook. Same scanner on both endpoints. Parent directory
# traversal opens metadata only; all file content reads are selected-root-relative.
_PROBE_CODE = r'''
import fnmatch
import hashlib
import json
import os
import stat
import sys

request = json.loads(sys.stdin.read(1048577))
if set(request) != {'root', 'excludes'}:
    raise ValueError('Invalid manifest request')
root, patterns = request['root'], request['excludes']
if not root.startswith('/') or any(p in ('', '.', '..') for p in root[1:].split('/')):
    raise ValueError('Unsafe manifest root')
MAX_ENTRIES = 10000
MAX_BYTES = 268435456
entries = {}
excluded = {}
count = 0
consumed = 0

def stamp(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

def ignored(relative):
    parts = relative.split('/')
    prefixes = ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    return any((fnmatch.fnmatchcase('/' + prefix, pattern) if pattern.startswith('/') else
                fnmatch.fnmatchcase(prefix, pattern) or fnmatch.fnmatchcase(prefix, '*/' + pattern))
               for prefix in prefixes for pattern in patterns)

def walk(fd, prefix=''):
    global count, consumed
    before = os.fstat(fd)
    names = sorted(os.listdir(fd))
    if len(names) > MAX_ENTRIES:
        raise ValueError('Selected entry bound exceeded')
    folded = set()
    for name in names:
        count += 1
        if count > MAX_ENTRIES or name.casefold() in folded or any(ord(c) < 32 for c in name):
            raise ValueError('Ambiguous filename or selected entry bound exceeded')
        folded.add(name.casefold())
        relative = prefix + name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if name == '.rsync-partial':
            raise ValueError('Reserved partial directory requires separate recovery review')
        if ignored(relative):
            excluded[relative] = stamp(info)
            continue
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                if stamp(os.fstat(child)) != stamp(info):
                    raise ValueError('Directory drift during manifest')
                entries[relative] = {'kind': 'directory', 'stamp': stamp(info)}
                walk(child, relative + '/')
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            if info.st_size + consumed > MAX_BYTES:
                raise ValueError('Selected byte bound exceeded')
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                start = os.fstat(child)
                if stamp(start) != stamp(info) or not stat.S_ISREG(start.st_mode) or start.st_nlink != 1:
                    raise ValueError('File drift during manifest')
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(child, 1048576)
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if consumed > MAX_BYTES:
                        raise ValueError('Selected byte bound exceeded')
                    digest.update(chunk)
                if stamp(os.fstat(child)) != stamp(start):
                    raise ValueError('File drift during manifest')
                entries[relative] = {'kind': 'file', 'sha256': digest.hexdigest(), 'stamp': stamp(info)}
            finally:
                os.close(child)
        else:
            raise ValueError('Selected symlink, hardlink or special file is unsupported')
        if stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != stamp(info):
            raise ValueError('Entry drift during manifest')
    if stamp(os.fstat(fd)) != stamp(before):
        raise ValueError('Directory drift during manifest')

fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
try:
    for part in root[1:].split('/'):
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = child
    root_info = os.fstat(fd)
    if root_info.st_uid != os.geteuid():
        raise ValueError('Selected root must be owned by the executing user')
    walk(fd)
    print(json.dumps({'entries': entries, 'excluded': excluded,
                      'root_identity': [root_info.st_dev, root_info.st_ino, root_info.st_uid]}))
finally:
    os.close(fd)
'''


def _validate_snapshot(snapshot):
    """Reject boolean/malformed endpoint claims; accept only bounded probe data."""
    def integers(value, length):
        return isinstance(value, list) and len(value) == length and all(type(v) is int for v in value)

    if (not isinstance(snapshot, dict) or set(snapshot) != {'entries', 'excluded', 'root_identity'} or
            not integers(snapshot['root_identity'], 3) or
            not isinstance(snapshot['entries'], dict) or not isinstance(snapshot['excluded'], dict)):
        raise ValueError('Invalid selected manifest schema')
    entries, excluded = snapshot['entries'], snapshot['excluded']
    if len(entries) + len(excluded) > 10000 or entries.keys() & excluded.keys():
        raise ValueError('Invalid selected manifest entries')
    for path in (*entries, *excluded):
        if (not isinstance(path, str) or any(p in ('', '.', '..') for p in path.split('/')) or
                any(ord(c) < 32 for c in path)):
            raise ValueError('Unsafe selected manifest path')
        parts = path.split('/')
        for index in range(1, len(parts)):
            if entries.get('/'.join(parts[:index]), {}).get('kind') != 'directory':
                raise ValueError('Invalid selected manifest directory structure')
    for entry in entries.values():
        if not isinstance(entry, dict) or entry.get('kind') not in ('file', 'directory'):
            raise ValueError('Invalid selected manifest entry type')
        keys = {'kind', 'stamp', 'sha256'} if entry['kind'] == 'file' else {'kind', 'stamp'}
        if set(entry) != keys or not integers(entry['stamp'], 9):
            raise ValueError('Invalid selected manifest metadata')
        if entry['kind'] == 'file' and (not isinstance(entry['sha256'], str) or
                not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
            raise ValueError('Invalid selected manifest checksum')
    if any(not integers(value, 9) for value in excluded.values()):
        raise ValueError('Invalid excluded manifest metadata')
    return snapshot


def _payload(snapshot):
    return {path: {key: value for key, value in entry.items() if key != 'stamp'}
            for path, entry in snapshot['entries'].items()}


class SelectedTransfer:
    """Pin a selection without I/O; call seed with separate explicit activation.

    ``_process_runner`` is a trusted test-only subprocess.run seam, not an
    authorization boundary or user-supplied remote hook. Production callers omit
    it. Tests consume the exact generated commands but substitute local processes;
    they cannot establish real SSH authentication or IAP reachability.
    """

    def __init__(self, spec, *, _process_runner=None, _lease_process_factory=None):
        self._selection = json.dumps(spec, sort_keys=True, separators=(',', ':'))
        plan = build_plan(json.loads(self._selection))
        if spec.get('endpoint') is not None:
            if any(_overlap(mapping['local'], spec['endpoint'][field])
                   for mapping in plan['mappings'] for field in ('identity_file', 'known_hosts_file')):
                raise ValueError('SSH identity/trust must be outside selected local data roots')
            trust = spec['endpoint']['known_hosts_file']
            if (any(part.casefold() in ('.devcontainer', '.vscode') for part in Path(trust).parts) or
                    any(_overlap(trust, p['path']) for p in plan['protected_paths'] if p['namespace'] == 'local')):
                raise ValueError('SSH trust storage overlaps explicit protection or active settings')
        self._canonical_plan = json.dumps(plan, sort_keys=True, separators=(',', ':'))
        self._digest = hashlib.sha256((self._selection + self._canonical_plan).encode()).hexdigest()
        self._runner = _process_runner
        self._lease_factory = _lease_process_factory

    @property
    def plan_digest(self):
        return self._digest

    def endpoint(self):
        """Validate selected LOCAL authentication metadata; never read key bytes."""
        spec = json.loads(self._selection)
        if spec.get('endpoint') is None:
            return None
        endpoint = TransferEndpoint(**spec['endpoint'], inspect_paths=False)
        endpoint.__post_init__()
        for selected in (endpoint.identity_file, endpoint.known_hosts_file):
            path = Path(selected)
            if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
                raise ValueError('SSH identity/trust must be existing non-symlink regular files')
        return endpoint

    def probe_local(self, index, *, dataset_lock, env, cwd, activation=False):
        """Fixed selected local probe under an existing DatasetLock; no remote IO."""
        if activation is not True:
            raise ValueError('Explicit activation=True is required')
        mappings = json.loads(self._canonical_plan)['mappings']
        if type(index) is not int or not 0 <= index < len(mappings):
            raise ValueError('Select a pinned mapping index')
        mapping = mappings[index]
        evidence = dataset_lock.check()
        pinned = next((e for e in evidence if e['path'] == mapping['local']), None)
        if pinned is None:
            raise ValueError('Exact local dataset ownership required')
        result = (self._runner or subprocess.run)(
            ['/usr/bin/python3', '-I', '-S', '-B', '-c', _PROBE_CODE],
            input=json.dumps(dict(root=mapping['local'], excludes=[p.rstrip('/') for p in mapping['excludes']])),
            check=True, text=True, capture_output=True, timeout=120, env=env, cwd=cwd)
        if result.returncode != 0 or len(result.stdout) > 8 * 1024 * 1024:
            raise ValueError('Selected local probe failed or exceeded bound')
        snapshot = _validate_snapshot(json.loads(result.stdout))
        dataset_lock.check()
        if snapshot['root_identity'][:2] != [pinned['device'], pinned['inode']]:
            raise ValueError('Local probe identity changed')
        return snapshot

    def seed(self, *, readiness, activation=False, supervisor=None):
        """Run the selected seed; optionally borrow an exact paused supervisor.

        Borrowing is an observed concrete RemoteSupervisor session, NOT a caller
        attestation. It retains both locks and checks native pause at every
        process boundary. Any transfer failure poisons that owning session.
        """
        if activation is not True:
            raise ValueError('Explicit activation=True is required')
        fields = {'plan_digest', 'transport_reviewed', 'paths_reviewed', 'exclusive_writer_reviewed'}
        if (not isinstance(readiness, dict) or set(readiness) != fields or
                readiness['plan_digest'] != self.plan_digest or
                any(readiness[key] is not True for key in fields - {'plan_digest'})):
            raise ValueError('Exact selected readiness and caller reviews are required')
        if supervisor is not None:
            from src.python.remote_sync_supervisor import RemoteSupervisor
            if type(supervisor) is not RemoteSupervisor:
                raise ValueError('An explicit verified paused-supervisor is required')
            supervisor._seed_context(self)
        try:
            return self._seed(readiness=readiness, activation=True, supervisor=supervisor)
        except BaseException:
            if supervisor is not None:
                supervisor._block()
            raise

    def _seed(self, *, readiness, activation=False, supervisor=None):
        """Execute one reviewed seed and return independently observed manifests.

        ``readiness`` has exactly ``plan_digest`` equal to this instance's digest
        and literal True ``transport_reviewed``, ``paths_reviewed``, and
        ``exclusive_writer_reviewed``. These approve this call, not prove state.
        Both roots of each mapping must already exist, be owned by the executing
        user, and contain at most 10,000 observed entries / 256 MiB included bytes.
        All paths and exclusions come from the pinned spec, never caller argv.
        Directory-shaped exclusions are strengthened to cover same-named files.
        Existing .rsync-partial entries require separate recovery and are refused.

        SSH uses an existing identity and known-hosts file; metadata is validated
        without reading identity bytes. accept-new remains the shared trust policy.
        IAP uses existing CLOUDSDK_CONFIG (or HOME/.config/gcloud) and optional
        CLOUDSDK_ACTIVE_CONFIG_NAME; gcloud must be available on /usr/bin:/bin.
        This code neither provisions auth nor verifies backups, independent
        writers, native-engine compatibility, or real-host acceptance.
        """
        if activation is not True:
            raise ValueError('Explicit activation=True is required')
        fields = {'plan_digest', 'transport_reviewed', 'paths_reviewed', 'exclusive_writer_reviewed'}
        if (not isinstance(readiness, dict) or set(readiness) != fields or
                readiness['plan_digest'] != self.plan_digest or
                any(readiness[key] is not True for key in fields - {'plan_digest'})):
            raise ValueError('Exact selected readiness and caller reviews are required')
        plan = json.loads(self._canonical_plan)
        spec = json.loads(self._selection)
        if plan['engine'] != 'rsync' or plan['delete']:
            raise ValueError('Unsupported engine or deletion; no reviewed recovery implementation')
        endpoint = self.endpoint()
        borrowed = None
        if supervisor is not None:
            from src.python.remote_sync_supervisor import RemoteSupervisor
            if type(supervisor) is not RemoteSupervisor:
                raise ValueError('An explicit verified paused-supervisor is required')
            borrowed = supervisor._seed_context(self)
        # Lock physical directories on THIS host only. With an SSH endpoint,
        # mapping['remote'] is a foreign namespace, never a local filesystem path.
        local_sides = ('local', 'remote') if endpoint is None else ('local',)
        local_roots = [m[side] for m in plan['mappings'] for side in local_sides]
        with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='isaac-selected-process-') as home:
            dataset_lock = borrowed[0] if borrowed else stack.enter_context(DatasetLock(local_roots))
            env = dict(PATH='/usr/bin:/bin', HOME=home, LC_ALL='C', TMPDIR=home, XDG_CONFIG_HOME=home)
            if endpoint and endpoint.iap:
                # Preserve gcloud's existing caller-selected authentication
                # context; an empty HOME alone would make IAP unusable. These
                # are references only, read by gcloud on future API activation.
                # No credential/config bytes are read by this adapter.
                config = os.environ.get('CLOUDSDK_CONFIG')
                if not config:
                    caller_home = os.environ.get('HOME')
                    if not caller_home or not caller_home.startswith('/'):
                        raise ValueError('IAP requires an existing explicit gcloud context')
                    config = caller_home.rstrip('/') + '/.config/gcloud'
                if not config.startswith('/'):
                    raise ValueError('IAP CLOUDSDK_CONFIG must be absolute')
                env['CLOUDSDK_CONFIG'] = config
                if os.environ.get('CLOUDSDK_ACTIVE_CONFIG_NAME'):
                    env['CLOUDSDK_ACTIVE_CONFIG_NAME'] = os.environ['CLOUDSDK_ACTIVE_CONFIG_NAME']
            remote_lease = borrowed[1] if borrowed else None
            if endpoint and borrowed is None:
                from src.python.remote_sync_supervisor import RemoteLease
                if self._runner is not None and self._lease_factory is None:
                    raise ValueError('Test process runner requires an explicit remote lease process factory')
                remote_lease = RemoteLease(endpoint, [dict(root=m['remote'],
                    excludes=[p.rstrip('/') for p in m['excludes']]) for m in plan['mappings']],
                    env=env, cwd=home, _process_factory=self._lease_factory)
                stack.callback(remote_lease.close)
                remote_lease.acquire(activation=True)
            runner = self._runner or subprocess.run

            def check_ownership():
                dataset_lock.check()
                if remote_lease is not None:
                    remote_lease.check()
                if supervisor is not None:
                    supervisor._seed_context(self)

            def run(argv, *, data=None):
                check_ownership()
                result = runner(argv, input=data, check=True, text=True, capture_output=True,
                                timeout=120 if data is not None else 3600, env=env, cwd=home)
                if result.returncode != 0:
                    raise ValueError('Selected process failed; no verified receipt')
                check_ownership()
                return result

            def observe(mapping, side):
                check_ownership()
                if side == 'remote' and remote_lease is not None:
                    return remote_lease.observe(plan['mappings'].index(mapping))
                request = dict(root=mapping[side], excludes=[p.rstrip('/') for p in mapping['excludes']])
                command = ['/usr/bin/python3', '-I', '-S', '-B', '-c', _PROBE_CODE]
                if side == 'remote' and endpoint:
                    command = ['/usr/bin/ssh', *endpoint.ssh_argv()[1:],
                               f'{endpoint.user}@{endpoint.host}', shlex.join(command)]
                result = run(command,
                             data=json.dumps(request, separators=(',', ':')))
                if len(result.stdout) > 8 * 1024 * 1024:
                    raise ValueError('Manifest response bound exceeded')
                return _validate_snapshot(json.loads(result.stdout))

            pairs = []
            # Observe and validate EVERY direction before issuing ANY rsync.
            for mapping in plan['mappings']:
                src, dst = ('local', 'remote') if mapping['direction'] == 'push' else ('remote', 'local')
                before_source, before_target = observe(mapping, src), observe(mapping, dst)
                if supervisor is None and any(path.split('/')[-1] == '.stfolder' for snapshot in (before_source, before_target)
                       for path in snapshot['excluded']):
                    raise ValueError('Native-owned root requires a verified paused-supervisor seed path')
                source, target = _payload(before_source), _payload(before_target)
                paths = set(source) | set(target) | set(before_source['excluded']) | set(before_target['excluded'])
                if len({p.casefold() for p in paths}) != len(paths):
                    raise ValueError('Cross-endpoint case collision')
                if any(source[p]['kind'] != target[p]['kind'] for p in source.keys() & target.keys()):
                    raise ValueError('Destination type conflict')
                if plan['initial_seed'] == 'empty-target':
                    if target.keys() - source.keys() or any(source[p] != target[p] for p in source.keys() & target.keys()):
                        raise ValueError('Initial seed destination conflict; stop and review')
                pairs.append((mapping, src, dst, before_source, before_target, {**target, **source}))
            returncodes = []
            for mapping, src, dst, before_source, before_target, expected in pairs:
                if observe(mapping, src) != before_source or observe(mapping, dst) != before_target:
                    raise ValueError('Pre-transfer source/destination drift')
                argv = list(mapping['rsync_argv'])
                argv[0] = '/usr/bin/rsync'
                argv.remove('--dry-run')
                if endpoint:
                    # Consume the shared transport preview, not ambient SSH.
                    index = argv.index('-e') + 1
                    ssh = shlex.split(argv[index])
                    argv[index] = shlex.join(['/usr/bin/ssh', *ssh[1:]])
                    argv[argv.index('--'):argv.index('--')] = ['--rsync-path=/usr/bin/rsync']
                # Directory exclusions also exclude same-named non-directories:
                # scanner and rsync must agree conservatively on protection.
                for index in range(1, len(argv)):
                    if argv[index - 1] == '--exclude':
                        argv[index] = argv[index].rstrip('/')
                argv[argv.index('--'):argv.index('--')] = ['--checksum', '--no-links', '--no-devices', '--no-specials']
                returncodes.append(run(argv).returncode)
            manifests = {}
            for mapping, src, dst, before_source, before_target, expected in pairs:
                after_source, after_target = observe(mapping, src), observe(mapping, dst)
                if (after_source != before_source or _payload(after_target) != expected or
                        after_target['excluded'] != before_target['excluded'] or
                        after_target['root_identity'] != before_target['root_identity']):
                    raise ValueError('Seed verification failed: source/destination drift; no verified receipt')
                manifests[mapping['name']] = {path: entry['sha256'] for path, entry in expected.items()
                                             if entry['kind'] == 'file'}
            scope = 'selected-local' if endpoint is None else ('selected-ssh-iap' if endpoint.iap else 'selected-ssh')
            check_ownership()
            local_evidence = dataset_lock.check()
            return dict(status='verified', executed=True, scope=scope,
                        plan_digest=self.plan_digest, returncodes=returncodes, manifests=manifests,
                        verification='sha256-included-files; directory-shape; excluded-entry-metadata-only',
                        live_transport_qualified=False, distributed_lock=False,
                        local_dataset_exclusion=True,
                        local_dataset_lock_scope=('cooperative-directory-inodes-borrowed-supervisor-session'
                            if borrowed else 'cooperative-directory-inodes-held-during-seed-only'),
                        local_root_identity_evidence=local_evidence,
                        remote_root_identity_evidence=remote_lease.check() if remote_lease else [],
                        remote_writer_exclusion='cooperative-remote-directory-inodes' if endpoint else 'local-dataset-lock',
                        exclusive_writer_review='caller-attestation-not-global-writer-proof')
