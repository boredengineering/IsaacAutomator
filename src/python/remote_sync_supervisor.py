"""Selected SSH/IAP + preconfigured Syncthing protocol supervision.

Only cooperative POSIX inode locks; no distributed/hostile-writer guarantee.
Fixed Python is sent as an SSH command, never installed as a remote helper.
No service, pairing, authentication, forwarding or provisioning is performed.
Protocol fixtures do not qualify real SSH/IAP, tunnels, or a native engine.
"""
from copy import deepcopy
import inspect
import json
import os
import select
import shlex
import subprocess
import time
import tempfile

from src.python.dataset_lock import DatasetLock, DatasetLockError
from src.python.selected_transfer import SelectedTransfer, _PROBE_CODE, _validate_snapshot, _payload
from src.python.remote_development import build_plan
from src.python.sync_supervisor import SyncthingREST, SupervisionError, _activation, _digest


# Both remote and local roots use the exact published DatasetLock algorithm.
# Source is taken from these fixed imported classes, never from a caller hook.
_LEASE_LOOP = r'''
import contextlib
import io
import json
import select
import sys

BOUND = 8 * 1024 * 1024
lock = None
selections = None
try:
    while True:
        raw = sys.stdin.buffer.readline(1048577)
        if not raw:
            break
        if len(raw) > 1048576 or not raw.endswith(b'\n'):
            raise ValueError('request bound')
        request = json.loads(raw)
        if (not isinstance(request, dict) or type(request.get('id')) is not int or
                request.get('version') != 1 or type(request.get('version')) is not int):
            raise ValueError('request schema')
        operation = request.get('op')
        if operation == 'acquire':
            if lock is not None or set(request) != {'version', 'id', 'op', 'selections'}:
                raise ValueError('acquire schema')
            selections = request['selections']
            if not isinstance(selections, list) or not 1 <= len(selections) <= 64:
                raise ValueError('selection bound')
            for item in selections:
                if (not isinstance(item, dict) or set(item) != {'root', 'excludes'} or
                        not isinstance(item['root'], str) or item['root'] == '/' or
                        not isinstance(item['excludes'], list) or len(item['excludes']) > 512 or
                        any(not isinstance(p, str) or not p or len(p) > 4096 for p in item['excludes'])):
                    raise ValueError('selection schema')
            lock = DatasetLock(item['root'] for item in selections).acquire()
            result = lock.check()
        elif operation == 'check':
            if lock is None or set(request) != {'version', 'id', 'op'}:
                raise ValueError('check schema')
            result = lock.check()
        elif operation == 'observe':
            if (lock is None or set(request) != {'version', 'id', 'op', 'index'} or
                    type(request['index']) is not int or not 0 <= request['index'] < len(selections)):
                raise ValueError('observe schema')
            lock.check()
            output = io.StringIO()
            old_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(json.dumps(selections[request['index']]))
                with contextlib.redirect_stdout(output):
                    exec(PROBE, {})
            finally:
                sys.stdin = old_stdin
            lock.check()
            result = json.loads(output.getvalue())
        else:
            raise ValueError('unknown operation')
        encoded = json.dumps(dict(version=1, id=request['id'], ok=True, result=result),
                             separators=(',', ':'), allow_nan=False).encode() + b'\n'
        if len(encoded) > BOUND:
            raise ValueError('response bound')
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
finally:
    if lock is not None:
        lock.close()
'''


class RemoteLease:
    """Persistent fixed-code SSH process, bounded typed JSON-line protocol.

    Constructor is inert. _process_factory is a trusted test-only Popen seam;
    production always uses /usr/bin/ssh and the selected SSH/IAP argv builder.
    Timeout/EOF/identity drift poisons the lease: it cannot be re-adopted.
    """
    def __init__(self, endpoint, selections, *, env, cwd, timeout=120, _process_factory=None):
        if type(timeout) not in (int, float) or not .01 <= timeout <= 120:
            raise SupervisionError('Select a bounded lease timeout')
        self.endpoint = endpoint
        self.selections = deepcopy(selections)
        self.env, self.cwd = dict(env), cwd
        self.timeout = timeout
        self._factory = _process_factory or subprocess.Popen
        self._process = None
        self._serial = 0
        self._evidence = None
        self._failed = False

    def acquire(self, *, activation=False):
        _activation(activation)
        if self._process is not None or self._failed:
            raise SupervisionError('Remote lease already used')
        fixed = ('import fcntl, os\nfrom pathlib import PurePosixPath\n' +
                 inspect.getsource(DatasetLockError) + '\n' + inspect.getsource(DatasetLock) +
                 '\nPROBE = ' + repr(_PROBE_CODE) + '\n' + _LEASE_LOOP)
        command = ['/usr/bin/python3', '-I', '-S', '-B', '-c', fixed]
        argv = ['/usr/bin/ssh', *self.endpoint.ssh_argv()[1:],
                f'{self.endpoint.user}@{self.endpoint.host}', shlex.join(command)]
        self._process = self._factory(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=self.env, cwd=self.cwd, bufsize=0)
        assert self._process.stdin is not None and self._process.stdout is not None
        os.set_blocking(self._process.stdin.fileno(), False)
        os.set_blocking(self._process.stdout.fileno(), False)
        try:
            self._evidence = self._identities(self._request('acquire', selections=self.selections))
            return self
        except BaseException:
            self.close()
            raise

    def _request(self, operation, **fields):
        if self._process is None or self._failed or self._process.poll() is not None:
            self._failed = True
            raise SupervisionError('Remote lease lost; manual recovery required')
        assert self._process.stdin is not None and self._process.stdout is not None
        self._serial += 1
        request = json.dumps(dict(version=1, id=self._serial, op=operation, **fields),
                             allow_nan=False, separators=(',', ':')).encode() + b'\n'
        deadline = time.monotonic() + self.timeout
        try:
            if len(request) > 1048576:
                raise ValueError('request bound')
            pending = memoryview(request)
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self._process.stdin], [], remaining)[1]:
                    raise ValueError('write timeout')
                pending = pending[os.write(self._process.stdin.fileno(), pending):]
            response = bytearray()
            while not response.endswith(b'\n'):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([self._process.stdout], [], [], remaining)[0]:
                    raise ValueError('read timeout')
                chunk = os.read(self._process.stdout.fileno(), 65536)
                if not chunk or len(response) + len(chunk) > 8 * 1024 * 1024:
                    raise ValueError('response bound or EOF')
                response.extend(chunk)
            value = json.loads(response)
            if (not isinstance(value, dict) or set(value) != {'version', 'id', 'ok', 'result'} or
                    type(value['version']) is not int or value['version'] != 1 or
                    type(value['id']) is not int or value['id'] != self._serial or value['ok'] is not True):
                raise ValueError('response schema')
            return value['result']
        except (OSError, ValueError, TypeError):
            self._failed = True
            raise SupervisionError('Remote lease protocol/session lost; manual recovery required') from None

    def _identities(self, evidence):
        if (not isinstance(evidence, list) or len(evidence) != len({s['root'] for s in self.selections}) or
                any(not isinstance(e, dict) or set(e) != {'path', 'device', 'inode'} or
                    not isinstance(e['path'], str) or type(e['device']) is not int or type(e['inode']) is not int
                    for e in evidence) or
                {e['path'] for e in evidence} != {s['root'] for s in self.selections}):
            self._failed = True
            raise SupervisionError('Invalid remote root identity evidence')
        return evidence

    def check(self):
        evidence = self._identities(self._request('check'))
        if evidence != self._evidence:
            self._failed = True
            raise SupervisionError('Remote root identity changed; manual recovery required')
        return evidence

    def observe(self, index):
        if type(index) is not int or not 0 <= index < len(self.selections):
            raise SupervisionError('Select a pinned mapping index')
        try:
            snapshot = _validate_snapshot(self._request('observe', index=index))
        except (ValueError, TypeError):
            self._failed = True
            raise SupervisionError('Invalid remote manifest; lease lost; manual recovery required') from None
        assert self._evidence is not None
        evidence = next(e for e in self._evidence if e['path'] == self.selections[index]['root'])
        if snapshot['root_identity'][:2] != [evidence['device'], evidence['inode']]:
            self._failed = True
            raise SupervisionError('Remote probe root identity changed')
        return snapshot

    def close(self):
        process, self._process = self._process, None
        self._failed = True
        if process is not None:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.close()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            process.stdout.close()


# Failed-stop sessions retain local and surviving remote descriptors in process.
# No automatic reclaim: exact object + explicit verified-paused close is required.
_RETAINED_SESSIONS = {}


class RemoteSupervisor:
    """API-only synchronous selected cross-host folder session.

    ``acquire`` verifies preconfigured paused folders; ``seed`` runs selected
    rsync under the same locks; ``verify_seed`` adopts matching existing bytes.
    ``resume``, ``poll``, ``pause`` and ``close`` all require activation=True.
    The caller MUST poll for the entire running session. There is no watchdog
    across caller/process failure, no tunnel creation and no crash-safe lease.
    A blocked session can only close after verified pause, then requires a NEW
    explicitly reviewed session. No auto-resume/re-pin/recovery is provided.
    """
    def __init__(self, spec, *, backend, rest_contexts,
                 _process_runner=None, _lease_process_factory=None, lease_timeout=120):
        self._plan = build_plan(spec)
        if type(backend) is not SyncthingREST or self._plan['engine'] != 'syncthing' or not spec.get('endpoint'):
            raise SupervisionError('Select SyncthingREST and an explicit SSH/IAP endpoint')
        if rest_contexts != {'local': 'local-loopback', 'remote': 'forwarded-loopback'}:
            raise SupervisionError('Explicit local and already-forwarded loopback REST contexts required')
        if _process_runner is not None and _lease_process_factory is None:
            raise SupervisionError('Test runner requires an explicit fake lease process factory')
        self._backend = backend
        self._spec = deepcopy(spec)
        self._transfer = SelectedTransfer(dict(spec, engine='rsync', delete=False),
            _process_runner=_process_runner, _lease_process_factory=_lease_process_factory)
        self._factory, self._timeout = _lease_process_factory, lease_timeout
        self.plan_digest = _digest(dict(spec=spec, backend=backend.selection, rest_contexts=rest_contexts,
                                        seed_plan=self._transfer.plan_digest))
        self.state = 'new'
        self._dataset = self._lease = self._home = None
        self._env = None
        self._seed = self._generations = None
        self._historical = False
        self._manual = False
        self._roots = 'not-checked'
        self._evidence = {}
        self._pause_verified = False

    def _ready(self, readiness):
        fields = {'plan_digest', 'transport_reviewed', 'paths_reviewed', 'rest_contexts_reviewed',
                  'recovery_verified', 'deletion_approved'}
        if (not isinstance(readiness, dict) or set(readiness) != fields or
                readiness['plan_digest'] != self.plan_digest or self._plan['delete_approved'] is not True or
                any(readiness[key] is not True for key in fields - {'plan_digest'})):
            raise SupervisionError('Exact selected readiness, deletion and reviewed REST contexts required')

    def _receipt(self):
        return dict(state=self.state, plan_digest=self.plan_digest,
            historical_seed_verified=self._historical,
            seed_verification_scope='historical SHA256 included-files and directory-shape; not current continuous bytes',
            current_root_verification=self._roots, root_identity_evidence=deepcopy(self._evidence),
            local_dataset_lock_held=self._dataset is not None,
            remote_lease_held=self._lease is not None and not self._lease._failed,
            verified_paused=self._pause_verified, manual_recovery_required=self._manual,
            lock_scope='cooperative-POSIX-directory-inodes-on-each-host; not external writers',
            distributed_hostile_writer_exclusion=False, live_transport_qualified=False,
            native_qualification='not-performed; protocol fixtures only',
            tunnel_acceptance='pending; caller-supplied existing forwarding only')

    @staticmethod
    def _paused(observed):
        return all(f['paused'] and f['state'] == '' for e in observed for f in e['folders'])

    def _observe(self, *, paused):
        observed = self._backend.observe(self._plan, activation=True)
        if self._generations is not None and [e['generation'] for e in observed] != self._generations:
            raise SupervisionError('Native process generation changed')
        if any(f['conflict'] or f['failure'] for e in observed for f in e['folders']):
            raise SupervisionError('Native health requires manual recovery')
        if paused:
            if not self._paused(observed):
                raise SupervisionError('Native folders must be verified paused with no runner')
        elif any(f['paused'] or f['state'] not in ('idle', 'scanning', 'syncing')
                 for e in observed for f in e['folders']):
            raise SupervisionError('Native running state not verified')
        return observed

    def _check_roots(self):
        try:
            if self._dataset is None or self._lease is None:
                raise SupervisionError('Local and remote ownership required')
            self._evidence = dict(local=self._dataset.check(), remote=self._lease.check())
            self._roots = 'pinned-identities-match-at-last-check'
        except Exception:
            self._roots = 'lost-session-or-root-identity'
            raise

    def _snapshots(self):
        self._check_roots()
        assert self._dataset is not None and self._lease is not None and self._home is not None
        pairs = []
        for index, mapping in enumerate(self._plan['mappings']):
            local = self._transfer.probe_local(index, dataset_lock=self._dataset,
                env=self._env, cwd=self._home.name, activation=True)
            remote = self._lease.observe(index)
            if any('.sync-conflict-' in p for snap in (local, remote) for p in snap['entries']):
                raise SupervisionError('Conflict filename requires manual recovery')
            pairs.append((local, remote))
        self._check_roots()
        return pairs

    def acquire(self, *, readiness, activation=False):
        _activation(activation)
        self._ready(readiness)
        if self.state != 'new':
            raise SupervisionError('Session already used; manual recovery requires a new review')
        endpoint = self._transfer.endpoint()
        assert endpoint is not None
        self._dataset = DatasetLock(m['local'] for m in self._plan['mappings']).acquire()
        try:
            self._home = tempfile.TemporaryDirectory(prefix='isaac-remote-supervision-')
            home = self._home.name
            self._env = dict(PATH='/usr/bin:/bin', HOME=home, LC_ALL='C', TMPDIR=home, XDG_CONFIG_HOME=home)
            if endpoint.iap:
                config = os.environ.get('CLOUDSDK_CONFIG')
                if not config:
                    caller_home = os.environ.get('HOME', '')
                    if not caller_home.startswith('/'):
                        raise SupervisionError('IAP requires an existing explicit gcloud context')
                    config = caller_home.rstrip('/') + '/.config/gcloud'
                if not config.startswith('/'):
                    raise SupervisionError('IAP CLOUDSDK_CONFIG must be absolute')
                self._env['CLOUDSDK_CONFIG'] = config
                if os.environ.get('CLOUDSDK_ACTIVE_CONFIG_NAME'):
                    self._env['CLOUDSDK_ACTIVE_CONFIG_NAME'] = os.environ['CLOUDSDK_ACTIVE_CONFIG_NAME']
            self._lease = RemoteLease(endpoint, [dict(root=m['remote'],
                excludes=[p.rstrip('/') for p in m['excludes']]) for m in self._plan['mappings']],
                env=self._env, cwd=home, timeout=self._timeout, _process_factory=self._factory)
            self._lease.acquire(activation=True)
            self._check_roots()
            observed = self._observe(paused=True)
            self._snapshots()
            self._generations = [e['generation'] for e in observed]
            self._observe(paused=True)
            self._check_roots()
            self._pause_verified = True
            self.state = 'paused-unseeded'
            return self._receipt()
        except BaseException:
            self._block()
            raise

    def _seed_context(self, transfer):
        if (type(transfer) is not SelectedTransfer or transfer.plan_digest != self._transfer.plan_digest or
                self.state not in ('paused', 'paused-unseeded') or self._manual):
            raise SupervisionError('Exact verified paused-supervisor seed session required')
        try:
            self._check_roots()
            self._observe(paused=True)
        except BaseException:
            self._block()
            raise
        return self._dataset, self._lease

    def seed(self, *, readiness, activation=False):
        _activation(activation)
        self._ready(readiness)
        self._seed_context(self._transfer)
        self._seed = None
        try:
            self._transfer.seed(readiness=dict(plan_digest=self._transfer.plan_digest,
                transport_reviewed=True, paths_reviewed=True, exclusive_writer_reviewed=True),
                activation=True, supervisor=self)
            return self.verify_seed(readiness=readiness, activation=True)
        except BaseException:
            self._block()
            raise

    def verify_seed(self, *, readiness, activation=False):
        _activation(activation)
        self._ready(readiness)
        self._seed_context(self._transfer)
        try:
            pairs = self._snapshots()
            if any(_payload(a) != _payload(b) for a, b in pairs):
                raise SupervisionError('Seed bytes or directory shape differ')
            self._observe(paused=True)
            self._check_roots()
            self._seed = [_payload(a) for a, b in pairs]
            self._historical = True
            self.state = 'paused'
            return self._receipt()
        except BaseException:
            self._block()
            raise

    def resume(self, *, activation=False):
        _activation(activation)
        if self.state != 'paused' or self._seed is None or self._manual:
            raise SupervisionError('Historical verified seed and owned paused session required')
        try:
            self._seed_context(self._transfer)
            if any(_payload(a) != seed or _payload(b) != seed
                   for (a, b), seed in zip(self._snapshots(), self._seed)):
                raise SupervisionError('Historical seed changed; new review required')
            self._observe(paused=True)
            self._check_roots()
            self._pause_verified = False
            self._backend.set_paused(self._plan, False, activation=True)
            self._observe(paused=False)
            self._check_roots()
            self.state = 'continuous'
            return self._receipt()
        except BaseException:
            self._block()
            raise

    def poll(self, *, activation=False):
        _activation(activation)
        if self.state != 'continuous' or self._manual:
            raise SupervisionError('Poll requires a running owned session')
        try:
            self._snapshots()
            self._observe(paused=False)
            self._check_roots()
        except Exception:
            self._block()
        return self._receipt()

    def _verified_pause(self):
        # Independent of a failed SSH lease: REST may still safely stop folders.
        self._pause_verified = False
        self._backend.set_paused(self._plan, True, activation=True)
        if not self._paused(self._backend.observe(self._plan, activation=True)):
            raise SupervisionError('Native pause unverified; retain surviving locks')
        self._pause_verified = True

    def _block(self):
        self._manual = True
        self._seed = None
        self.state = 'blocked'
        _RETAINED_SESSIONS[id(self)] = self
        try:
            self._verified_pause()
        except Exception:
            self.state = 'stop-unverified'

    def pause(self, *, activation=False):
        _activation(activation)
        if self._dataset is None or self._manual:
            raise SupervisionError('Pause requires owned session; blocked sessions must close manually')
        try:
            self._check_roots()
            self._verified_pause()
            self._observe(paused=True)
            self._check_roots()
            self.state = 'paused' if self._seed is not None else 'paused-unseeded'
            return self._receipt()
        except BaseException:
            self._block()
            raise

    def close(self, *, activation=False):
        """Verified-pause cleanup; failed stop retains locks, never claims success."""
        _activation(activation)
        if self._dataset is None:
            return self._receipt()
        try:
            self._check_roots()
        except Exception:
            self._manual = True
            self._seed = None
        try:
            self._verified_pause()
        except Exception:
            self._manual = True
            self._seed = None
            self.state = 'stop-unverified'
            _RETAINED_SESSIONS[id(self)] = self
            return self._receipt()
        if self._lease is not None:
            self._lease.close()
            self._lease = None
        self._dataset.close()
        self._dataset = None
        if self._home is not None:
            self._home.cleanup()
            self._home = None
        self._seed = None
        self.state = 'stopped'
        _RETAINED_SESSIONS.pop(id(self), None)
        return self._receipt()
