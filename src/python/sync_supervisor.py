"""Explicitly activated, cooperative Syncthing folder-session supervision.

No import/constructor performs IO. No CLI activation, subprocess, shell, daemon
launch, installation, discovery or automatic engine choice. The concrete adapter
controls preconfigured paired folders on two explicitly selected loopback APIs;
both filesystem roots must be on this host for independent SHA-256 seed checks.
Native qualification is NOT supplied by the synthetic protocol test suite.
"""
from copy import deepcopy
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlencode

from src.python.remote_development import build_plan, _path, _overlap, _fixture_files, _fixture_manifest
from src.python.dataset_lock import DatasetLock

# Failed-close descriptors remain alive until exact-plan, verified-paused recovery.
# This is in-process cleanup escrow, NOT the dataset exclusion mechanism.
_RETAINED_DATASETS = {}


class SupervisionError(ValueError):
    """Fail closed; messages never contain engine responses or API keys."""


def _activation(value):
    if value is not True:
        raise SupervisionError('Separate explicit API activation=True required')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


class SyncthingREST:
    """Native REST adapter, pinned to v1.27.12 response semantics.

    Uses http.client directly: no proxy/environment, redirects, DNS, subprocess
    or shell. Only numeric 127.0.0.1 HTTP endpoints accepted. TLS/remote APIs and
    Mutagen are unsupported, not silently downgraded. Caller supplies API keys
    in memory; they are never included in receipts or the review digest.
    """
    engine = 'syncthing'
    support = 'paired-preconfigured-loopback-folders-v1.27.12'

    def __init__(self, *, local_url, remote_url, local_device, remote_device,
                 local_api_key, remote_api_key, timeout=3):
        self._endpoints = []
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise SupervisionError('Timeout must be bounded')
        self.timeout = timeout
        for url, device, key in ((local_url, local_device, local_api_key),
                                 (remote_url, remote_device, remote_api_key)):
            parsed = urlsplit(url)
            if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or
                    parsed.path or parsed.query or parsed.fragment or parsed.username or
                    parsed.password or parsed.port is None):
                raise SupervisionError('Select explicit numeric loopback HTTP API and port')
            if not isinstance(device, str) or not re.fullmatch(r'[A-Z0-9-]{1,80}', device):
                raise SupervisionError('Select explicit device identity')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', key):
                raise SupervisionError('Invalid in-memory API key')
            self._endpoints.append((parsed.port, device, key))
        if local_url == remote_url or local_device == remote_device:
            raise SupervisionError('Select distinct paired engines')

    @property
    def selection(self):
        return {'adapter': self.support, 'endpoints': [dict(port=p, device=d) for p, d, _ in self._endpoints]}

    def _request(self, side, method, path, body=None, *, activation=False):
        _activation(activation)
        port, _, key = self._endpoints[side]
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=self.timeout)
        try:
            data = json.dumps(body).encode() if body is not None else None
            connection.request(method, path, body=data,
                headers={'X-API-Key': key, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read(1048577)
            if response.status != 200 or len(raw) > 1048576:
                raise SupervisionError('Engine HTTP result refused')
            return json.loads(raw) if raw else {}
        except (OSError, http.client.HTTPException, ValueError):
            raise SupervisionError('Engine unavailable or invalid protocol response') from None
        finally:
            connection.close()

    def observe(self, plan, *, activation=False):
        _activation(activation)
        observations = []
        for side in range(2):
            def get(path):
                return self._request(side, 'GET', path, activation=True)
            version = get('/rest/system/version')
            system = get('/rest/system/status')
            if version.get('version') != 'v1.27.12' or system.get('myID') != self._endpoints[side][1]:
                raise SupervisionError('Unqualified native version or device identity')
            if not isinstance(system.get('startTime'), str) or not system['startTime']:
                raise SupervisionError('Missing process generation')
            if get('/rest/config/restart-required').get('requiresRestart') is not False:
                raise SupervisionError('Native configuration not applied')
            connections = get('/rest/system/connections').get('connections', {})
            peer = self._endpoints[1-side][1]
            if connections.get(peer, {}).get('connected') is not True:
                raise SupervisionError('Selected peer is not connected')
            folders = []
            for mapping in plan['mappings']:
                folder = mapping['name']
                config = get('/rest/config/folders/' + folder)
                sender = (side == 0) == (mapping['direction'] == 'push')
                expected_type = 'sendonly' if sender else 'receiveonly'
                peers = {d.get('deviceID') for d in config.get('devices', [])}
                if (config.get('id') != folder or config.get('path') != mapping['local' if side == 0 else 'remote']
                        or config.get('type') != expected_type or peer not in peers or
                        peers - {peer, self._endpoints[side][1]} or type(config.get('paused')) is not bool):
                    raise SupervisionError('Native folder identity, ownership or placement mismatch')
                if not sender and config.get('versioning', {}).get('type') != 'staggered':
                    raise SupervisionError('Native receiver versioning not configured')
                query = '?' + urlencode({'folder': folder})
                if get('/rest/db/ignores' + query).get('ignore') != [p.rstrip('/') for p in mapping['excludes']]:
                    raise SupervisionError('Native ignore selection mismatch')
                status = get('/rest/db/status' + query)
                if (not isinstance(status, dict) or not isinstance(status.get('state'), str) or
                        not isinstance(status.get('error'), str) or
                        any(type(status.get(k)) is not int or status[k] < 0
                            for k in ('pullErrors', 'receiveOnlyTotalItems', 'sequence', 'needTotalItems'))):
                    raise SupervisionError('Missing or invalid native runner health')
                # v1.27.12 model.State returns empty state only with no runner.
                # Config paused alone, a PATCH response or CLI exit is NOT proof.
                folders.append({'paused': config['paused'], 'state': status['state'],
                    'conflict': bool(status.get('receiveOnlyTotalItems', 0)),
                    'failure': bool(status.get('error') or status.get('pullErrors') or status['state'] == 'error')})
            observations.append({'generation': system['startTime'], 'folders': folders})
        return observations

    def set_paused(self, plan, paused, *, activation=False):
        _activation(activation)
        if type(paused) is not bool:
            raise SupervisionError('Paused state must be boolean')
        failed = False
        for side in range(2):
            for mapping in plan['mappings']:
                try:
                    system = self._request(side, 'GET', '/rest/system/status', activation=True)
                    config = self._request(side, 'GET', '/rest/config/folders/' + mapping['name'], activation=True)
                    sender = (side == 0) == (mapping['direction'] == 'push')
                    if (system.get('myID') != self._endpoints[side][1] or
                            config.get('id') != mapping['name'] or
                            config.get('path') != mapping['local' if side == 0 else 'remote'] or
                            config.get('type') != ('sendonly' if sender else 'receiveonly')):
                        raise SupervisionError('Selected folder no longer owned; no mutation')
                    self._request(side, 'PATCH', '/rest/config/folders/' + mapping['name'],
                                  {'paused': paused}, activation=True)
                except Exception:
                    if not paused:
                        raise
                    failed = True
        if failed:
            raise SupervisionError('Some selected folders could not be paused')


class Supervisor:
    """Synchronous supervisor; caller must poll while the session is running.

    Directory-inode locks cover identical/nested datasets across control scopes.
    Not a distributed lease and not protection against independent native GUIs
    or same-UID hostile writers. It never owns or terminates an entire daemon;
    cleanup pauses only selected folders, preserving pre-existing configuration.
    """
    def __init__(self, spec, *, backend, lock_directory):
        self._spec = deepcopy(spec)
        self._plan = build_plan(spec)
        if type(backend) is not SyncthingREST or self._plan['engine'] != backend.engine:
            raise SupervisionError('Explicit supported engine and adapter must match')
        if spec.get('endpoint') is not None:
            raise SupervisionError('Remote filesystem seed verifier is not supported')
        self._backend = backend
        self._lock_directory = _path(str(lock_directory))
        lock_path = self._lock_directory + '/.writer.lock'
        if (any(_overlap(lock_path, m[side]) for m in self._plan['mappings'] for side in ('local', 'remote')) or
                any(_overlap(lock_path, p['path']) for p in self._plan['protected_paths']
                    if p['namespace'] in ('local', 'remote')) or
                any(p in ('.devcontainer', '.vscode') for p in Path(self._lock_directory).parts)):
            raise SupervisionError('Writer lock must be outside mappings, settings and protected paths')
        self.plan_digest = _digest({'selection': self._spec, 'plan': self._plan,
                                    'backend': backend.selection, 'lock_directory': self._lock_directory})
        self.state = 'new'
        self._fd = None
        self._seed = None
        self._generations = None
        self._dataset = None
        self._guard_key = None
        self._root_status = 'not-checked'
        self._root_evidence = []
        self._historical_seed = False

    def _ready(self, readiness):
        if (not isinstance(readiness, dict) or set(readiness) != {'plan_digest', 'transport_reviewed',
                'recovery_verified', 'deletion_approved', 'paths_reviewed'} or
                readiness['plan_digest'] != self.plan_digest or
                any(readiness[key] is not True for key in readiness if key != 'plan_digest') or
                self._plan['delete_approved'] is not True):
            raise SupervisionError('Exact plan digest and all readiness reviews required')

    def _receipt(self):
        return dict(state=self.state, writer_owned=self._fd is not None, plan_digest=self.plan_digest,
            executed=True, model_only=False, adapter=self._backend.support,
            native_qualification='not-performed; tests are synthetic',
            seed_verification='sha256-local-pair-bytes' if self._seed is not None else 'not-verified',
            seed_verification_scope='historical seed snapshot, not current continuous bytes',
            historical_seed_verified=self._historical_seed,
            current_root_verification=self._root_status, root_identity_evidence=self._root_evidence,
            dataset_lock_held=self._dataset is not None or self._guard_key in _RETAINED_DATASETS,
            lock_scope='local-cooperative-directory-inodes-and-ancestors',
            distributed_lease=False)

    def _observe(self):
        return self._backend.observe(self._plan, activation=True)

    @staticmethod
    def _paused(observed):
        return all(f['paused'] and f['state'] == '' for e in observed for f in e['folders'])

    def _check_roots(self):
        try:
            if self._dataset is None:
                raise SupervisionError('Dataset ownership required')
            self._root_evidence = self._dataset.check()
            self._root_status = 'pinned-identities-match-at-last-check'
        except (ValueError, OSError):
            self._root_status = 'missing-unreadable-or-identity-changed'
            raise

    def _check_conflict_files(self):
        self._check_roots()
        for mapping in self._plan['mappings']:
            for side in ('local', 'remote'):
                _path(mapping[side], local=True)
                files = _fixture_files(Path(mapping[side]), mapping['excludes'])
                if any('.sync-conflict-' in name for name in files):
                    raise SupervisionError('Conflict filename requires explicit review')

    def _seed_bytes(self):
        self._check_conflict_files()
        manifests = []
        for m in self._plan['mappings']:
            local, remote = Path(m['local']), Path(m['remote'])
            for path in (local, remote):
                _path(str(path), local=True)
                if not path.is_dir():
                    raise SupervisionError('Seed root missing')
            source, destination = (local, remote) if m['direction'] == 'push' else (remote, local)
            a = _fixture_manifest(_fixture_files(source, m['excludes']))
            b = _fixture_manifest(_fixture_files(destination, m['excludes']))
            if a != b:
                raise SupervisionError('Seed byte verification failed')
            manifests.append(a)
        return manifests

    def acquire(self, *, readiness, recover=False, activation=False):
        _activation(activation)
        self._ready(readiness)
        if self.state != 'new':
            raise SupervisionError('Session already used')
        # No-follow each parent. Never unlink a lock inode.
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in Path(self._lock_directory).parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open('.writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise SupervisionError('Another writer owns this synchronization scope') from None
        self._fd = fd
        try:
            import stat
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1024):
                raise SupervisionError('Unsafe writer lock')
            self._guard_key = (info.st_dev, info.st_ino, self.plan_digest)
            previous = os.read(fd, 1025)
            if previous and (recover is not True or previous.decode('ascii', errors='replace') != self.plan_digest):
                raise SupervisionError('Unclean writer guard requires explicit exact-plan recovery')
            retained = _RETAINED_DATASETS.get(self._guard_key) if recover is True else None
            self._dataset = retained or DatasetLock(
                m[side] for m in self._plan['mappings'] for side in ('local', 'remote')).acquire()
            self._check_roots()
            observed = self._observe()
            if not self._paused(observed) or any(f['conflict'] or f['failure'] for e in observed for f in e['folders']):
                raise SupervisionError('Native folders must already be verifiably paused and healthy')
            self._seed = self._seed_bytes()
            self._check_roots()
            self._historical_seed = True
            _RETAINED_DATASETS.pop(self._guard_key, None)
            self._generations = [e['generation'] for e in observed]
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, self.plan_digest.encode('ascii'))
            os.ftruncate(fd, len(self.plan_digest))
            os.fsync(fd)
            self.state = 'paused'
            return self._receipt()
        except BaseException:
            if self._dataset is not None:
                if _RETAINED_DATASETS.get(self._guard_key) is not self._dataset:
                    self._dataset.close()
                self._dataset = None
            os.close(self._fd)
            self._fd = None
            raise

    def resume(self, *, activation=False):
        _activation(activation)
        if self.state != 'paused' or self._fd is None:
            raise SupervisionError('Verified paused owned session required')
        try:
            self._check_roots()
        except (ValueError, OSError):
            self._block()
            raise
        observed = self._observe()
        if (not self._paused(observed) or [e['generation'] for e in observed] != self._generations or
                any(f['conflict'] or f['failure'] for e in observed for f in e['folders'])):
            raise SupervisionError('Native state, health or process generation changed')
        if self._seed_bytes() != self._seed:
            raise SupervisionError('Seed changed; explicit reseed review required')
        try:
            self._check_roots()
            self._backend.set_paused(self._plan, False, activation=True)
            observed = self._observe()
            if not all(not f['paused'] and not f['conflict'] and not f['failure'] and
                       f['state'] in ('idle', 'scanning', 'syncing') for e in observed for f in e['folders']):
                raise SupervisionError('Resume not observed in native state')
            if [e['generation'] for e in observed] != self._generations:
                raise SupervisionError('Process generation changed during resume')
            self._check_roots()
        except BaseException:
            self._block()
            raise
        self.state = 'continuous'
        return self._receipt()

    def pause(self, *, activation=False):
        _activation(activation)
        if self._fd is None:
            raise SupervisionError('No owned session')
        self.state = 'stop-unverified'
        self._backend.set_paused(self._plan, True, activation=True)
        if not self._paused(self._observe()):
            raise SupervisionError('Pause not verified; writer lock retained')
        self.state = 'paused'
        return self._receipt()

    def poll(self, *, activation=False):
        """One real health observation; no hidden background or auto restart."""
        _activation(activation)
        if self.state != 'continuous' or self._fd is None:
            raise SupervisionError('Polling requires a running owned session')
        try:
            self._check_conflict_files()
            observed = self._observe()
            if ([e['generation'] for e in observed] != self._generations or
                    any(f['conflict'] or f['failure'] or f['paused'] or
                        f['state'] not in ('idle', 'scanning', 'syncing')
                        for e in observed for f in e['folders'])):
                raise SupervisionError('Conflict, failure or process generation changed')
            self._check_roots()
        except Exception:
            self._block()
        return self._receipt()

    def _block(self):
        self._seed = None
        self.state = 'blocked'
        try:
            self._backend.set_paused(self._plan, True, activation=True)
            if not self._paused(self._observe()):
                self.state = 'stop-unverified'
        except Exception:
            self.state = 'stop-unverified'

    def reseed(self, *, readiness, fixture=None, activation=False):
        """Review a new seed under retained ownership.

        With fixture=None this only verifies already-transferred selected bytes.
        A local_fixture() capability additionally permits actual checksum rsync
        inside that disposable scope, using the existing verified fixed-command
        adapter. No arbitrary seed callback or existing-root transfer is exposed.
        """
        _activation(activation)
        self._ready(readiness)
        if self._fd is None or self.state not in ('paused', 'blocked', 'stop-unverified'):
            raise SupervisionError('Reseed requires retained writer ownership')
        observed = self._observe()
        if not self._paused(observed) or any(f['conflict'] or f['failure'] for e in observed for f in e['folders']):
            raise SupervisionError('Reseed requires verified stopped healthy folders')
        self._check_roots()
        self._seed = None
        if fixture is not None:
            from src.python.remote_development import _LocalFixture
            if type(fixture) is not _LocalFixture or str(fixture.root) != self._lock_directory:
                raise SupervisionError('Reseed fixture must own this exact locked scope')
            fixture._transfer_locked(dict(self._spec, engine='rsync'), dataset_lock=self._dataset)
        self._seed = self._seed_bytes()
        self._check_roots()
        self._historical_seed = True
        self._generations = [e['generation'] for e in observed]
        self.state = 'paused'
        return self._receipt()

    def run(self, *, readiness, stop_event, poll_interval=1, activation=False):
        """Blocking supervision loop with owned-folder cleanup on every exit.

        The caller owns its thread/event. No process is spawned. Use poll() for
        integration with another scheduler, or run() for automatic health checks.
        """
        import threading
        _activation(activation)
        if not isinstance(stop_event, threading.Event) or not isinstance(poll_interval, (int, float)) or not .01 <= poll_interval <= 60:
            raise SupervisionError('Select a stop Event and bounded poll interval')
        outcome = 'stop-requested'
        try:
            self.acquire(readiness=readiness, activation=True)
            if not stop_event.is_set():
                self.resume(activation=True)
                while not stop_event.wait(poll_interval):
                    self.poll(activation=True)
                    if self.state != 'continuous':
                        outcome = self.state
                        break
        finally:
            cleanup = self.close(activation=True)
        return {'outcome': outcome, 'cleanup': cleanup}

    def close(self, *, activation=False):
        """Owned-session cleanup. Failed stop leaves a persistent recovery guard.

        Closing the control fd does not release dataset descriptors: failed-close
        locks remain escrowed in this process for verified exact-plan recovery.
        Process exit releases kernel locks; the guard only persists in this scope.
        """
        _activation(activation)
        if self._fd is None:
            return self._receipt()
        try:
            return self.stop(activation=True)
        except Exception:
            self.state = 'stop-unverified'
            self._seed = None
            # Keep DATASET descriptors even though the legacy control fd closes.
            # Exact-plan recovery can reclaim them only after stopped verification.
            _RETAINED_DATASETS[self._guard_key] = self._dataset
            self._dataset = None
            os.close(self._fd)
            self._fd = None
            return self._receipt()

    def stop(self, *, activation=False):
        _activation(activation)
        self.pause(activation=True)
        os.ftruncate(self._fd, 0)
        os.fsync(self._fd)
        os.close(self._fd)
        self._fd = None
        if self._dataset is not None:
            self._dataset.close()
        self._dataset = None
        self._seed = None
        self.state = 'stopped'
        return self._receipt()
