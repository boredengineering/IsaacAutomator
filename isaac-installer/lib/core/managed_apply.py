"""Bounded local fixture executor, NOT an Isaac/robotics installer.

Caller must select an owned disposable root and approve this exact plan. No
real-target CLI is provided. Existing paths are not adopted. Only new paths are
published; changed existing files require a new versioned destination. Journals
are receipts, not authorization. No automatic resume or recursive cleanup.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import fcntl
import importlib.util
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import sys
import unicodedata
import uuid

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('managed_action_plan', Path(__file__).with_name('action_plan.py'))
assert _spec and _spec.loader
_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_plan)
_spec = importlib.util.spec_from_file_location('managed_fixture_builders', Path(__file__).with_name('fixture_builders.py'))
assert _spec and _spec.loader
_builders = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builders)
JOURNAL = '.isaac-managed-journal.jsonl'
LIMIT = 1048576


class ApplyError(ValueError):
    """Refusal or failed operation; no installer fallback is permitted."""


class Root:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute() or self.path == Path('/') or '..' in self.path.parts:
            raise ApplyError('explicit non-root fixture directory required')
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        self.chain = [(os.fstat(fd).st_dev, os.fstat(fd).st_ino)]
        try:
            for part in self.path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self.chain.append((os.fstat(fd).st_dev, os.fstat(fd).st_ino))
            self.fd = fd
            self.identity = os.fstat(fd)
            if self.identity.st_uid != os.geteuid() or stat.S_IMODE(self.identity.st_mode) != 0o700:
                raise ApplyError('fixture root must be privately owned mode 0700')
        except BaseException:
            os.close(fd)
            raise

    def lock(self):
        # Shared ancestor locks + exclusive root lock serialize even nested roots.
        # Directory inode locks cannot be replaced by unlinking a lock-file name.
        self.lock_fds = []
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, part in enumerate(self.path.parts[1:]):
                if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != self.chain[index]:
                    raise ApplyError('lock ancestor identity changed')
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                self.lock_fds.append(fd)
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            self.lock_fds.append(fd)
            if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != self.chain[-1]:
                raise ApplyError('lock root identity changed')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ApplyError):
            if fd not in self.lock_fds:
                os.close(fd)
            for locked in self.lock_fds:
                os.close(locked)
            self.lock_fds = []
            raise ApplyError('overlapping resource lock unavailable') from None

    def close(self):
        for fd in getattr(self, 'lock_fds', []):
            os.close(fd)
        os.close(self.fd)

    def relative(self, target):
        path = Path(target)
        if not path.is_absolute() or '..' in path.parts:
            raise ApplyError('absolute target without traversal required')
        try:
            relative = path.relative_to(self.path)
        except ValueError:
            raise ApplyError('target outside explicit fixture') from None
        if not relative.parts or any(p.startswith('.isaac-') for p in relative.parts):
            raise ApplyError('root-wide and reserved metadata targets forbidden')
        return relative

    def check_identity(self):
        current = Root(str(self.path))
        try:
            if current.chain != self.chain:
                raise ApplyError('fixture root identity changed')
        finally:
            current.close()

    def parent_identity(self, target):
        with self.parent(target) as (fd, _):
            info = os.fstat(fd)
            return [info.st_dev, info.st_ino]

    def collision(self, fd, name):
        names = os.listdir(fd)
        if len(names) > 4096:
            raise ApplyError('directory inspection count exceeded')
        if any(other != name and other.casefold() == name.casefold() for other in names):
            raise ApplyError('case-only collision; explicit spelling selection required')

    @contextmanager
    def parent(self, target):
        self.check_identity()
        relative = self.relative(target)
        fd = os.dup(self.fd)
        try:
            for part in relative.parts[:-1]:
                self.collision(fd, part)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                if info.st_dev != self.identity.st_dev or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_mode & 0o700 != 0o700:
                    raise ApplyError('mount/ownership/writable-parent boundary')
            self.collision(fd, relative.name)
            yield fd, relative.name
        finally:
            os.close(fd)

    def ancestry(self, target):
        chain = {str(self.path): [self.identity.st_dev, self.identity.st_ino]}
        fd = os.dup(self.fd)
        current = self.path
        try:
            for part in self.relative(target).parts[:-1]:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    break
                os.close(fd); fd = child
                current = current / part
                info = os.fstat(fd)
                chain[str(current)] = [info.st_dev, info.st_ino]
            return chain
        finally:
            os.close(fd)

    def evidence(self, target):
        try:
            with self.parent(target) as (fd, name):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if info.st_dev != self.identity.st_dev or info.st_uid != os.geteuid():
                    raise ApplyError('foreign/mounted target')
                if stat.S_ISDIR(info.st_mode) and (info.st_mode & 0o700 != 0o700 or info.st_mode & 0o022):
                    raise ApplyError('target directory permission boundary')
                result = {'state': 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'unsupported',
                          'identity': [info.st_dev, info.st_ino], 'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode), 'managed': False}
                if result['state'] == 'file':
                    if info.st_nlink != 1 or info.st_uid != os.geteuid():
                        raise ApplyError('hardlinked/foreign file forbidden')
                    readfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(readfd, 'rb') as stream:
                        actual = os.fstat(stream.fileno())
                        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                            raise ApplyError('file identity changed during observation')
                        data = stream.read(LIMIT + 1)
                    if len(data) > LIMIT:
                        raise ApplyError('bounded file size exceeded')
                    result['sha256'] = hashlib.sha256(data).hexdigest()
                return result
        except FileNotFoundError:
            return {'state': 'missing'}


def _journal_metadata(root, fd):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_dev != root.identity.st_dev):
        raise ApplyError('foreign journal metadata')
    identity = (info.st_dev, info.st_ino)
    if hasattr(root, 'journal_identity') and root.journal_identity != identity:
        raise ApplyError('journal identity changed')
    root.journal_identity = identity
    named = os.stat(JOURNAL, dir_fd=root.fd, follow_symlinks=False)
    if (named.st_dev, named.st_ino) != identity:
        raise ApplyError('journal name replaced')
    return info


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ApplyError('duplicate journal key')
        result[key] = value
    return result


def _validate_record(event):
    if type(event) is not dict or not 3 <= len(event) <= 8 or any(type(key) is not str for key in event):
        raise ApplyError('journal record must be an object')
    common = {'run', 'plan', 'state'}
    state = event.get('state')
    fields = {
        'intended': ({'action', 'target'}, set()),
        'started': ({'action', 'target'}, {'staging', 'staging_identity', 'created_identity'}),
        'verified': ({'action', 'target', 'postcondition'}, {'desired_digest'}),
        'failed': ({'error', 'errno'}, set()),
        'recovery_reviewed': ({'journal_digest', 'reviewed_state'}, set()),
    }
    if type(state) is not str or len(state) > 32 or state not in fields:
        raise ApplyError('unknown journal state')
    required, optional = fields[state]
    _exact_fields(event, common | required, optional)
    for key, length in (('run', 32), ('plan', 64), ('desired_digest', 64), ('journal_digest', 64)):
        if key in event and (type(event[key]) is not str or len(event[key]) != length or not re.fullmatch('[0-9a-f]{%d}' % length, event[key])):
            raise ApplyError('invalid journal digest/identity')
    for key in ('action', 'target', 'staging', 'error'):
        if key in event and (type(event[key]) is not str or not 0 < len(event[key]) <= 4096
                             or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in event[key])
                             or len(event[key].encode('utf-8')) > 4096):
            raise ApplyError('invalid journal string')
    for key in ('staging_identity', 'created_identity'):
        if key in event and (type(event[key]) is not list or len(event[key]) != 2 or any(type(n) is not int or not 0 <= n <= 2**64 - 1 for n in event[key])):
            raise ApplyError('invalid journal inode')
    # Linux syscall errno range; None denotes a non-OS exception, not zero.
    if state == 'failed' and event['errno'] is not None and (type(event['errno']) is not int or not 1 <= event['errno'] <= 4095):
        raise ApplyError('invalid journal errno')
    if state == 'recovery_reviewed' and (type(event['reviewed_state']) is not str or event['reviewed_state'] not in ('intended', 'started', 'failed')):
        raise ApplyError('invalid recovery review state')
    if 'target' in event:
        try:
            _plan.validate_evidence({event['target']: {}})
        except ValueError:
            raise ApplyError('invalid journal target') from None
    if ('staging' in event) != ('staging_identity' in event):
        raise ApplyError('incomplete staging identity')
    if 'staging' in event:
        _canonical_path(event['staging'])
    if 'staging' in event and (Path(event['staging']).parent != Path(event['target']).parent or not re.fullmatch(r'\.isaac-stage-[0-9a-f]{32}', Path(event['staging']).name)):
        raise ApplyError('invalid staging target')
    if state == 'verified':
        post = event['postcondition']
        try:
            _plan.validate_evidence({event['target']: post})
        except ValueError:
            raise ApplyError('invalid journal postcondition') from None
        required = {'state', 'identity', 'uid', 'mode', 'managed'}
        if post.get('state') == 'file':
            required.add('sha256')
        elif post.get('state') == 'directory':
            if 'tree_sha256' in post:
                required.update(('tree_sha256', 'desired_digest'))
                if event.get('desired_digest') != post.get('desired_digest'):
                    raise ApplyError('inconsistent desired identity')
        else:
            raise ApplyError('invalid verified resource type')
        if set(post) != required or post.get('managed') is not False:
            raise ApplyError('incomplete verified postcondition')
    return event


def _journal(root):
    try:
        fd = os.open(JOURNAL, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root.fd)
    except FileNotFoundError:
        if getattr(root, 'journal_identity', None) is not None:
            raise ApplyError('journal removed') from None
        root.journal_identity = None
        return []
    with os.fdopen(fd, 'rb') as stream:
        info = _journal_metadata(root, stream.fileno())
        data = stream.read(8 * LIMIT + 1)
        after = _journal_metadata(root, stream.fileno())
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ApplyError('journal changed during read')
    if len(data) > 8 * LIMIT:
        raise ApplyError('journal budget exceeded')
    try:
        lines = data.splitlines()
        if len(lines) > 4096 or (data and not data.endswith(b'\n')):
            raise ApplyError('journal record budget/truncation')
        return [_validate_record(json.loads(line, object_pairs_hook=_unique_object)) for line in lines]
    except (ValueError, TypeError, RecursionError):
        raise ApplyError('incomplete/corrupt journal; manual review required') from None


def read_journal(*, fixture_root):
    root = Root(fixture_root)
    try:
        return _journal(root)
    finally:
        root.close()


def review_recovery(*, fixture_root, run_ids, journal_digest, approved=False):
    """Acknowledge an exact bounded journal after separate human recovery review.

    Does not adopt, remove or restore partial resources. A fresh approved plan is
    still required; retained staging stays untouched. Not an automatic retry.
    """
    if approved is not True or type(run_ids) is not list or not 0 < len(run_ids) <= 128 or any(type(r) is not str for r in run_ids) or len(set(run_ids)) != len(run_ids):
        raise ApplyError('explicit exact recovery review required')
    root = Root(fixture_root)
    try:
        root.lock()
        events = _journal(root)
        if journal_digest != _plan.digest(events):
            raise ApplyError('stale recovery journal review')
        latest = {event['run']: event for event in events}
        if any(run not in latest or latest[run]['state'] not in ('intended', 'started', 'failed') for run in run_ids):
            raise ApplyError('select unresolved runs only')
        for run in run_ids:
            _record(root, {'run': run, 'plan': latest[run]['plan'], 'state': 'recovery_reviewed',
                           'journal_digest': journal_digest, 'reviewed_state': latest[run]['state']})
        return {'status': 'reviewed', 'runs': run_ids, 'resources_modified': False}
    finally:
        root.close()


def _observe(root, targets):
    records = {e['target']: e for e in _journal(root) if e.get('state') == 'verified' and 'postcondition' in e}
    result = {}
    for target in targets:
        evidence = root.evidence(target)
        record = records.get(target, {})
        expected = record.get('postcondition')
        if expected and 'tree_sha256' in expected and evidence.get('state') == 'directory':
            with root.parent(target) as (parent_fd, name):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    evidence['tree_sha256'] = _builders.tree_digest(fd)
                finally:
                    os.close(fd)
            evidence['desired_digest'] = record.get('desired_digest')
        if expected and evidence == {**expected, 'managed': False}:
            evidence['managed'] = True
        evidence['ancestors'] = root.ancestry(target)
        evidence['fixture_identity'] = [root.identity.st_dev, root.identity.st_ino]
        result[target] = evidence
    return result


def inspect_fixture(*, fixture_root, targets):
    """Only caller-selected paths; does not create a root, log or lock."""
    root = Root(fixture_root)
    try:
        return _observe(root, targets)
    finally:
        root.close()


def _record(root, record):
    _validate_record(record)
    data = json.dumps(record, sort_keys=True).encode() + b'\n'
    records = _journal(root)
    new = root.journal_identity is None
    flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(JOURNAL, flags | (os.O_CREAT | os.O_EXCL if new else 0), 0o600, dir_fd=root.fd)
    except FileExistsError:
        raise ApplyError('journal appeared concurrently') from None
    if new:
        root.journal_identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
    with os.fdopen(fd, 'ab') as stream:
        info = _journal_metadata(root, stream.fileno())
        if info.st_size + len(data) > 8 * LIMIT or len(records) >= 4096:
            raise ApplyError('journal budget exceeded')
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        _journal_metadata(root, stream.fileno())
        os.fsync(root.fd)


def _publish(root, target, content, fault=None, action=None):
    """Unnamed O_TMPFILE + linkat: no overwrite and no named staging cleanup.

    Requires Linux/filesystem support. No racy named-temporary fallback exists.
    """
    import ctypes
    with root.parent(target) as (fd, name):
        out = os.open('.', os.O_RDWR | os.O_TMPFILE, 0o600, dir_fd=fd)
        with os.fdopen(out, 'w+b') as stream:
            if fault:
                fault('stage_write', deepcopy(action))
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            if root.parent_identity(target) != [os.fstat(fd).st_dev, os.fstat(fd).st_ino]:
                raise ApplyError('parent moved during staging')
            libc = ctypes.CDLL(None, use_errno=True)
            linkat = libc.linkat
            linkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
            linkat.restype = ctypes.c_int
            # O_TMPFILE supports linking an owned unnamed inode with AT_EMPTY_PATH.
            if linkat(out, b'', fd, os.fsencode(name), 0x1000):
                error = ctypes.get_errno()
                raise OSError(error, 'atomic new-file publication refused')
            os.fsync(fd)


def _read_expected(root, target, expected):
    with root.parent(target) as (fd, name):
        filefd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(filefd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or [info.st_dev, info.st_ino] != expected['identity']:
                raise ApplyError('recovery source identity/ownership changed')
            data = stream.read(LIMIT + 1)
            after = os.fstat(stream.fileno())
            if info.st_mtime_ns != after.st_mtime_ns or len(data) > LIMIT or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ApplyError('recovery source content changed')
    return data


def _separate_roots(first, second):
    if first.path == second.path or first.path in second.path.parents or second.path in first.path.parents:
        raise ApplyError('backup/restore storage must be outside affected tree')


def backup_managed_file(*, fixture_root, target, backup_root, approved=False):
    """Copy only an unchanged journal-qualified file into separate private storage."""
    if approved is not True:
        raise ApplyError('explicit recovery preparation approval required')
    source = Root(fixture_root)
    backup = None
    try:
        backup = Root(backup_root)
        _separate_roots(source, backup)
        source.lock(); backup.lock()
        evidence = _observe(source, [target])[target]
        if evidence.get('state') != 'file' or evidence.get('managed') is not True or evidence.get('mode') != 0o600:
            raise ApplyError('only unchanged owned managed mode0600 declarative files qualified for backup')
        data = _read_expected(source, target, evidence)
        destination = str(backup.path / ('backup-' + uuid.uuid4().hex + '.bin'))
        _publish(backup, destination, data)
        post = backup.evidence(destination)
        if post.get('sha256') != evidence['sha256']:
            raise ApplyError('backup postcondition failed; do not rely on recovery')
        manifest = {'kind': 'managed-file-backup', 'source': target, 'source_root': str(source.path),
                    'backup': destination, 'original_name': Path(target).name, 'original_mode': evidence['mode'],
                    'original_uid': evidence['uid'], 'precondition': post}
        manifest['digest'] = _plan.digest(manifest)
        return manifest
    finally:
        if backup:
            backup.close()
        source.close()


def _exact_fields(value, required, optional=()):
    # Check builtin keys before set membership: no user-defined hash/equality.
    if (type(value) is not dict or not len(required) <= len(value) <= len(required) + len(optional)
            or any(type(key) is not str for key in value)
            or not set(required) <= value.keys() or value.keys() - set(required) - set(optional)):
        raise ApplyError('invalid metadata fields')


def _canonical_path(value):
    if type(value) is not str:
        raise ApplyError('invalid canonical path')
    try:
        _plan.validate_evidence({value: {}})
    except ValueError:
        raise ApplyError('invalid canonical path') from None
    return value


def _validate_recovery_manifest(manifest):
    """Pure bounded schema boundary, BEFORE checksum/copy/Root construction.

    A checksum detects corruption, not provenance or authorization. Coherent
    fields cannot authenticate an original root if a caller rewrites ALL fields.
    Keep the manifest in trusted storage and approve its provenance separately.
    """
    _exact_fields(manifest, {'kind', 'source', 'source_root', 'backup', 'original_name',
                             'original_mode', 'original_uid', 'precondition', 'digest'})
    if type(manifest['kind']) is not str or manifest['kind'] != 'managed-file-backup':
        raise ApplyError('invalid recovery kind')
    for key in ('source', 'source_root', 'backup'):
        _canonical_path(manifest[key])
    source, source_root, backup = (Path(manifest[key]) for key in ('source', 'source_root', 'backup'))
    name = manifest['original_name']
    if (type(name) is not str or len(name) > 255 or name != source.name
            or source_root not in source.parents
            or any(part.startswith('.isaac-') for part in source.relative_to(source_root).parts)
            or backup.parent == source_root or source_root in backup.parent.parents or backup.parent in source_root.parents
            or re.fullmatch(r'backup-[0-9a-f]{32}\.bin', backup.name) is None):
        raise ApplyError('inconsistent recovery paths')
    if (type(manifest['original_mode']) is not int or manifest['original_mode'] != 0o600
            or type(manifest['original_uid']) is not int or not 0 <= manifest['original_uid'] <= 2**32 - 1):
        raise ApplyError('invalid recovery metadata')
    post = manifest['precondition']
    _exact_fields(post, {'state', 'identity', 'uid', 'mode', 'managed', 'sha256'})
    try:
        post = _plan.validate_evidence({manifest['backup']: post})[manifest['backup']]
    except ValueError:
        raise ApplyError('invalid recovery precondition') from None
    if (post['state'] != 'file' or post['managed'] is not False or post['mode'] != 0o600
            or post['uid'] != manifest['original_uid']):
        raise ApplyError('inconsistent recovery precondition')
    checksum = manifest['digest']
    if type(checksum) is not str or len(checksum) != 64 or re.fullmatch('[0-9a-f]{64}', checksum) is None:
        raise ApplyError('invalid recovery digest')
    # Every value is now a bounded builtin. Copy only the validated shape.
    result = {key: value for key, value in manifest.items() if key != 'digest'}
    result['precondition'] = post
    if checksum != _plan.digest(result):
        raise ApplyError('invalid recovery checksum')
    return result


def restore_backup(manifest, *, backup_root, alternate_root, approved=False):
    """Alternate NEW destination only; manifest checksum is NOT provenance."""
    if approved is not True:
        raise ApplyError('explicit alternate restoration approval required')
    manifest = _validate_recovery_manifest(manifest)
    backup_root = _canonical_path(backup_root)
    alternate_root = _canonical_path(alternate_root)
    source_path, backup_path, alternate_path = Path(manifest['source_root']), Path(backup_root), Path(alternate_root)
    if Path(manifest['backup']).parent != backup_path:
        raise ApplyError('backup does not belong to selected storage')
    for other in (source_path, backup_path):
        if alternate_path == other or other in alternate_path.parents or alternate_path in other.parents:
            raise ApplyError('restoration requires a separate alternate tree')
    backup = Root(backup_root)
    alternate = None
    try:
        alternate = Root(alternate_root)
        _separate_roots(backup, alternate)
        source_root = Path(manifest['source_root'])
        if alternate.path == source_root or source_root in alternate.path.parents or alternate.path in source_root.parents:
            raise ApplyError('restoration must be outside original affected tree')
        backup.lock(); alternate.lock()
        if manifest['original_mode'] != 0o600 or manifest['original_uid'] != os.geteuid():
            raise ApplyError('unsupported recovery metadata')
        expected = manifest['precondition']
        if backup.evidence(manifest['backup']) != expected:
            raise ApplyError('backup identity/content changed')
        data = _read_expected(backup, manifest['backup'], expected)
        name = manifest['original_name']
        if Path(name).name != name:
            raise ApplyError('invalid restoration filename')
        target = str(alternate.path / name)
        _publish(alternate, target, data)
        post = alternate.evidence(target)
        if post.get('sha256') != expected['sha256'] or post.get('mode') != manifest['original_mode']:
            raise ApplyError('alternate restoration verification failed')
        return {'status': 'verified', 'target': target, 'sha256': post['sha256'], 'original_not_modified': True}
    finally:
        if alternate:
            alternate.close()
        backup.close()


def _matches(current, expected):
    current, expected = deepcopy(current), deepcopy(expected)
    actual_parents = current.pop('ancestors', {})
    expected_parents = expected.pop('ancestors', {})
    return (bool(expected_parents) and current == expected
            and all(actual_parents.get(path) == identity for path, identity in expected_parents.items()))


def _desired_status(action, current):
    operation, desired = action['operation'], action['desired']
    if current.get('state') == 'missing':
        return 'would_change'
    if operation == 'mkdir' and current.get('state') == 'directory':
        return 'satisfied'
    if current.get('managed') is True:
        if operation == 'write_file' and current.get('state') == 'file' and current.get('sha256') == _plan.hash_content(desired['content']):
            return 'satisfied'
        if operation in ('repository_checkout', 'environment_create') and current.get('state') == 'directory' and current.get('tree_sha256') and current.get('desired_digest') == _plan.digest(desired):
            return 'satisfied'
    return 'blocked'


def _validate_plan(plan, action_ids):
    """Unkeyed digests are not provenance; qualify all execution inputs here."""
    try:
        if type(plan) is not dict or set(plan) != {'kind', 'version', 'target_home', 'profile_digest', 'actions', 'coverage', 'draft', 'digest'}:
            raise ApplyError('invalid plan schema')
        if type(plan['version']) is not int or plan['version'] != 1 or plan['kind'] != 'installer-action-plan' or type(plan['draft']) is not bool:
            raise ApplyError('invalid plan kind/version/draft')
        if type(plan['actions']) is not list or len(plan['actions']) > 128 or type(plan['coverage']) is not dict:
            raise ApplyError('invalid actions/coverage')
        for key in ('digest', 'profile_digest'):
            if type(plan[key]) is not str or not re.fullmatch('[0-9a-f]{64}', plan[key]):
                raise ApplyError('invalid plan checksum')
        _plan.validate_evidence({plan['target_home']: {}})
        if len(json.dumps(plan, allow_nan=False).encode()) > 8 * LIMIT:
            raise ApplyError('plan byte budget exceeded')
        fields = {'id', 'category', 'operation', 'target', 'desired', 'status', 'reason', 'effects', 'preconditions', 'policy', 'execution_supported', 'unsupported_reason'}
        for action in plan['actions']:
            if type(action) is not dict or set(action) != fields:
                raise ApplyError('invalid action schema')
            for key in ('id', 'category', 'operation', 'target', 'reason'):
                if type(action[key]) is not str or not 0 < len(action[key]) <= 4096 or any(ord(c) < 32 for c in action[key]):
                    raise ApplyError('invalid action string')
            if type(action['execution_supported']) is not bool or action['status'] not in ('unknown', 'blocked', 'excluded', 'satisfied', 'would_change'):
                raise ApplyError('invalid action status/support')
            if type(action['effects']) is not list or len(action['effects']) > 32 or any(type(e) is not str or len(e) > 4096 for e in action['effects']):
                raise ApplyError('invalid effects')
            if action['unsupported_reason'] is not None and (type(action['unsupported_reason']) is not str or len(action['unsupported_reason']) > 4096):
                raise ApplyError('invalid unsupported reason')
            policy = action['policy']
            if type(policy) is not dict or set(policy) - {'ownership', 'high_risk', 'adapter', 'required'} or type(policy.get('high_risk')) is not bool or type(policy.get('ownership')) is not str:
                raise ApplyError('invalid action policy')
            if 'required' in policy and type(policy['required']) is not bool:
                raise ApplyError('invalid required policy')
            if type(action['preconditions']) is not dict:
                raise ApplyError('invalid preconditions')
            if action['target'].startswith('/'):
                _plan.validate_evidence({action['target']: action['preconditions']})
            elif action['preconditions']:
                raise ApplyError('symbolic target cannot have filesystem evidence')
            if action['status'] == 'excluded' or not action['execution_supported']:
                continue
            op, desired = action['operation'], action['desired']
            if type(desired) is not dict:
                raise ApplyError('invalid desired operation')
            qualified = False
            if op == 'mkdir':
                qualified = action['id'] in ('workspace.root', 'workspace.group') and desired == {} and action['category'] == 'workspace'
            elif op == 'write_file':
                qualified = (re.fullmatch(r'managed_file\.[0-9]+', action['id']) is not None and action['category'] == 'declarative_file'
                             and set(desired) == {'content'} and type(desired['content']) is str and len(desired['content'].encode()) <= LIMIT)
            elif op == 'environment_create':
                qualified = (re.fullmatch(r'runtime\.[A-Za-z0-9_-]+', action['id']) is not None and action['category'] == 'environment'
                             and not set(desired) - {'manager', 'path', 'fixture_local', 'enabled'} and desired.get('manager') == 'venv'
                             and desired.get('path') == action['target'] and desired.get('fixture_local') is True and desired.get('enabled', True) is True
                             and policy.get('adapter') == 'stdlib-venv')
            elif op == 'repository_checkout':
                qualified = (re.fullmatch(r'component\.[A-Za-z0-9_-]+', action['id']) is not None and action['category'] == 'repository'
                             and not set(desired) - {'repository', 'revision', 'mode', 'fixture_local'} and desired.get('fixture_local') is True
                             and desired.get('mode', 'git') == 'git' and type(desired.get('revision')) is str and re.fullmatch('[0-9a-f]{40}', desired['revision']) is not None
                             and type(desired.get('repository')) is str and desired['repository'].startswith('/') and policy.get('adapter') == 'local-fixture-git')
            if not qualified or policy['ownership'] != 'new-only':
                raise ApplyError('operation not independently qualified')
        all_ids = [a['id'] for a in plan['actions']]
        if len(set(all_ids)) != len(all_ids):
            raise ApplyError('duplicate action IDs')
        if action_ids is not None and (type(action_ids) is not list or not action_ids or any(type(i) is not str for i in action_ids) or len(set(action_ids)) != len(action_ids) or not set(action_ids) <= set(all_ids)):
            raise ApplyError('select exact unique action IDs')
    except (TypeError, KeyError, ValueError, RecursionError, OverflowError):
        raise ApplyError('invalid or unqualified execution plan') from None


def apply_plan(plan, *, fixture_root, approved=False, action_ids=None, fault=None):
    """Execute this exact plan on an explicit fixture; never install robotics."""
    if approved is not True:
        raise ApplyError('explicit execution approval required')
    _validate_plan(plan, action_ids)
    plan = deepcopy(plan)
    checksum = plan.pop('digest', None)
    if checksum != _plan.digest(plan):
        raise ApplyError('plan digest mismatch')
    if plan.get('kind') != 'installer-action-plan' or plan.get('version') != 1:
        raise ApplyError('unsupported action plan kind/version')
    all_ids = [a['id'] for a in plan['actions']]
    if len(all_ids) > 128 or len(set(all_ids)) != len(all_ids):
        raise ApplyError('action count/duplicate IDs invalid')
    if action_ids is not None and (not isinstance(action_ids, list) or not action_ids or len(set(action_ids)) != len(action_ids) or not set(action_ids) <= set(all_ids)):
        raise ApplyError('select nonempty exact unique action IDs')
    if plan.get('draft') and action_ids is None:
        raise ApplyError('draft cannot be applied as a complete profile; explicit qualified action subset required')
    actions = [a for a in plan['actions'] if action_ids is None or a['id'] in action_ids]
    deferred = [a['id'] for a in actions if a['policy'].get('required') is False and not a['execution_supported']
                and a['category'] in ('custom_dependency', 'declaration')]
    actions = [a for a in actions if a['id'] not in deferred]
    if any(a.get('policy', {}).get('high_risk') is not False for a in actions if a['status'] != 'excluded'):
        raise ApplyError('high-risk/unknown policy not authorized by fixture approval')
    if any(a['operation'] not in ('mkdir', 'write_file', 'repository_checkout', 'environment_create') for a in actions if a['status'] != 'excluded'):
        raise ApplyError('operation not in bounded executor allowlist')
    if any(a['status'] not in ('satisfied', 'would_change', 'excluded') or not a['execution_supported'] and a['status'] != 'excluded' for a in actions):
        raise ApplyError('unknown/blocked/unsupported action; choose an explicitly qualified action subset')
    root = Root(fixture_root)
    run = uuid.uuid4().hex
    changed = []
    base = None
    try:
        root.lock()
        latest = {}
        for event in _journal(root):
            latest[event['run']] = event['state']
        if any(state in ('intended', 'started', 'failed') for state in latest.values()):
            raise ApplyError('interrupted operation requires manual recovery review; automatic resume is unsupported')
        for action in actions:
            if action['status'] == 'excluded':
                continue
            target = action['target']
            current = _observe(root, [target])[target]
            if not _matches(current, action['preconditions']):
                raise ApplyError('stale plan precondition')
            actual_status = _desired_status(action, current)
            if actual_status != action['status']:
                raise ApplyError('supplied status does not match verified desired predicate')
            if actual_status == 'satisfied':
                continue
            base = {'run': run, 'plan': checksum, 'action': action['id'], 'target': target}
            _record(root, {**base, 'state': 'intended'})
            _record(root, {**base, 'state': 'started'})
            parent_identity = root.parent_identity(target)
            stage_identity, built_tree = None, None
            if fault:
                fault('before_mutation', deepcopy(action))
            if root.parent_identity(target) != parent_identity or _observe(root, [target])[target] != current:
                raise ApplyError('stale target or parent identity at mutation boundary')
            if action['operation'] == 'mkdir':
                with root.parent(target) as (fd, name):
                    os.mkdir(name, 0o700, dir_fd=fd)
                    os.fsync(fd)
            elif action['operation'] == 'write_file':
                _publish(root, target, action['desired']['content'].encode(), fault, action)
            elif action['operation'] in ('repository_checkout', 'environment_create'):
                with root.parent(target) as (fd, name):
                    stage = '.isaac-stage-' + uuid.uuid4().hex
                    os.mkdir(stage, 0o700, dir_fd=fd)
                    stagefd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        staged = os.fstat(stagefd)
                        stage_identity = [staged.st_dev, staged.st_ino]
                        _record(root, {**base, 'state': 'started', 'staging': str(Path(target).parent / stage), 'staging_identity': stage_identity})
                        builder = _builders.build_repository if action['operation'] == 'repository_checkout' else _builders.build_environment
                        built_tree = builder(root, action, fd, stage, stagefd)
                        if _builders.tree_digest(stagefd) != built_tree:
                            raise ApplyError('builder-verified tree changed at handoff')
                        if fault:
                            fault('before_publish', deepcopy(action))
                        now = os.stat(stage, dir_fd=fd, follow_symlinks=False)
                        if [now.st_dev, now.st_ino] != stage_identity or _builders.tree_digest(stagefd) != built_tree:
                            raise ApplyError('staged resource changed; retained without cleanup')
                        if root.parent_identity(target) != parent_identity:
                            raise ApplyError('parent changed during builder')
                        _builders.rename_new(fd, stage, name)
                    finally:
                        os.close(stagefd)
            else:
                raise ApplyError('operation unsupported by bounded adapter')
            created = root.evidence(target)
            _record(root, {**base, 'state': 'started', 'created_identity': created.get('identity')})
            if fault:
                fault('after_mutation', deepcopy(action))
            post = root.evidence(target)
            if post != created:
                raise ApplyError('new resource changed before verification; retained without cleanup')
            if action['operation'] == 'write_file' and post.get('sha256') != _plan.hash_content(action['desired']['content']):
                raise ApplyError('file content postcondition failed')
            if action['operation'] in ('repository_checkout', 'environment_create'):
                with root.parent(target) as (parent_fd, name):
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    try:
                        published = os.fstat(fd)
                        if [published.st_dev, published.st_ino] != stage_identity:
                            raise ApplyError('published directory identity changed')
                        post['tree_sha256'] = _builders.tree_digest(fd)
                        if post['tree_sha256'] != built_tree:
                            raise ApplyError('published directory differs from builder-verified tree')
                    finally:
                        os.close(fd)
                post['desired_digest'] = _plan.digest(action['desired'])
                base['desired_digest'] = post['desired_digest']
            _record(root, {**base, 'state': 'verified', 'postcondition': post})
            changed.append(action['id'])
        return {'status': 'verified', 'run': run, 'changed': changed, 'deferred': deferred, 'robotics_installed': False}
    except (OSError, KeyboardInterrupt, ApplyError, _builders.BuilderError, subprocess.SubprocessError) as error:
        if base is None and isinstance(error, ApplyError):
            raise
        failure = {'run': run, 'plan': checksum, 'state': 'failed',
                   'error': type(error).__name__, 'errno': getattr(error, 'errno', None)}
        try:
            _record(root, failure)
        except (OSError, ApplyError):
            pass  # Retain incomplete started journal; never invent a success receipt.
        return {'status': 'failed', 'run': run, 'changed': changed, 'error': failure,
                'recovery': 'manual review; staged/partial resources retained; no auto-resume'}
    finally:
        root.close()
