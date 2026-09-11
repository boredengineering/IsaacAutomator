"""Private, local last-applied recipes; not public recovery manifests.

Integration contract (Linux, durable local filesystem):
1. prepare(... source_files=workstation_source_files(cloud), source_revision=an
   explicitly approved hash, verify_source=GitRevisionVerifier(repo, subdir)).
   Pass the approved lock separately; source_files excludes .terraform.lock.hcl.
   Alternatively the verifier must consult a trusted build record binding that
   exact revision to the selected byte map, never merely hash today's checkout.
2. prepared.stage(a_fresh_directory_below_a_private_parent) returns source_root,
   source_files, variables_file; supply those exact fields to TerraformRunner.
3. After successful saved-plan apply, independently verify ownership, lineage,
   expected resources/outputs and that THIS recipe was executed. publish takes
   the actual state/output objects plus verify_applied(recipe, state, outputs).
4. Only on successful publish, persist receipt.baseline_ref in protected active
   deployment metadata / DriftConfig.baseline_ref under the lifecycle lock.
   This store publishes an immutable receipt, NOT the caller's active pointer.
5. reconstruct(ref, fresh_directory) needs no live checkout. Retire the active
   pointer after verified destroy; old receipts are historical, not live state.

None means unknown for legacy deployments, never 'use today's checkout'. No
Terraform execution, credentials, state-file discovery, mutation authorization,
remote lifecycle integration or automatic snapshot garbage collection occurs.

Trust/retention: the owner and selected source/verifier code are trusted. This
is a content-integrity store, not signatures, encryption or a same-UID sandbox.
All store and reconstructed files are private; approved input BYTES (potentially
secrets) must NEVER enter DeploymentManifest.inputs or its public baseline.
That manifest's input_sha256 hashes a public subset; our input_digest hashes the
exact private var-file bytes and is intentionally a different contract. Keep
this CAS on durable protected storage and handle orphan objects/failed staging
cleanup explicitly. Reconstructed sources/providers remain executable code.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, field
import fcntl
import stat
import hashlib
import json
import os
import re
from pathlib import Path
from types import MappingProxyType
import uuid

from src.python.drift_report import Baseline, digest
from src.python.deployment_manifest import StateSummary


class BaselineError(ValueError):
    """Sanitized baseline failure; private contents must not enter diagnostics."""


_MAX_FILE = 16 * 1024 * 1024
_MAX_TOTAL = 64 * 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def _directory(path, *, private=False, create=False):
    """Pin every component, including ancestors; never path-check then follow."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise BaselineError('Absolute non-traversing path required')
    try:
        with ExitStack() as stack:
            fd = os.open(path.anchor, _DIR_FLAGS)
            stack.callback(os.close, fd)
            for index, component in enumerate(path.parts[1:]):
                last = index == len(path.parts) - 2
                if create and last:
                    try:
                        os.mkdir(component, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                if private and (info.st_uid not in (0, os.geteuid())
                        or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)):
                    raise BaselineError('Untrusted directory ownership or permissions')
            info = os.fstat(fd)
            if private and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise BaselineError('Private directory must be owner-only mode 0700')
            yield fd
    except OSError:
        raise BaselineError('Safe directory access failed; diagnostics withheld') from None


def _read_at(parent, name, *, private=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (private and info.st_uid != os.geteuid())
                or info.st_size > _MAX_FILE
                or (private and stat.S_IMODE(info.st_mode) != 0o600)):
            raise BaselineError('Snapshot file must be bounded, regular, owned and unlinked')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(_MAX_FILE + 1)
        after = os.fstat(fd)
        if (len(raw) > _MAX_FILE or after.st_nlink != 1
                or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) !=
                   (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise BaselineError('Snapshot changed while being read')
        return raw
    finally:
        os.close(fd)


def _read_path(path, *, private=False):
    path = Path(path)
    with _directory(path.parent) as fd:
        return _read_at(fd, path.name, private=private)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@dataclass(frozen=True, init=False)
class PreparedBaseline:
    source_revision: str
    _sources: tuple = field(repr=False)
    _inputs: bytes = field(repr=False)
    _lock: bytes = field(repr=False)
    inputs_name: str
    lock_present: bool

    def __init__(self, *args, **kwargs):
        raise BaselineError('Use prepare with independent source verification')

    def stage(self, destination):
        """Materialize a fresh private runner recipe BEFORE planning/apply.

        Parent must already exist, be owner-only, and have trusted ancestors.
        Caller owns cleanup; failed materialization may leave a private partial
        directory, never a published baseline. Never reuse an existing directory.
        """
        return _materialize(self, destination)


@dataclass(frozen=True)
class RecipePaths:
    source_root: Path
    source_files: tuple
    variables_file: Path = field(repr=False)


def _prepared(revision, sources, inputs, lock, inputs_name, lock_present):
    result = object.__new__(PreparedBaseline)
    for name, value in zip(PreparedBaseline.__dataclass_fields__,
                           (revision, sources, inputs, lock, inputs_name, lock_present)):
        object.__setattr__(result, name, value)
    return result


def _tree_write(root, name, raw):
    with ExitStack() as stack:
        parent = root
        for part in name.split('/')[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
            child = os.open(part, _DIR_FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            info = os.fstat(child)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise BaselineError('Unsafe reconstruction directory')
            parent = child
        fd = os.open(name.split('/')[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)


def _materialize(prepared, destination):
    destination = Path(destination)
    if not destination.is_absolute() or '..' in destination.parts:
        raise BaselineError('Absolute fresh reconstruction path required')
    with _directory(destination.parent, private=True) as parent:
        os.mkdir(destination.name, 0o700, dir_fd=parent)
        root = os.open(destination.name, _DIR_FLAGS, dir_fd=parent)
        try:
            for name, raw in prepared._sources:
                _tree_write(root, 'source/' + name, raw)
            _tree_write(root, prepared.inputs_name, prepared._inputs)
            if prepared.lock_present:
                _tree_write(root, 'source/.terraform.lock.hcl', prepared._lock)
            os.fsync(root)
            os.fsync(parent)
        finally:
            os.close(root)
    files = tuple(name for name, _ in prepared._sources)
    if prepared.lock_present:
        files += ('.terraform.lock.hcl',)
    return RecipePaths(destination / 'source', files, destination / prepared.inputs_name)


@dataclass(frozen=True)
class BaselineReceipt:
    baseline_ref: str
    baseline: Baseline


@dataclass(frozen=True)
class ReconstructedBaseline:
    baseline: Baseline
    source_root: Path
    source_files: tuple
    variables_file: Path = field(repr=False)


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise BaselineError('Explicit immutable source revision required')


def _source_names(values):
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 1024:
        raise BaselineError('Explicit nonempty source allowlist required')
    for name in values:
        if (not isinstance(name, str) or len(name) > 1024
                or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)
                or any(part in ('.', '..', '.terraform', '.git') for part in name.split('/'))
                or not name.endswith(('.tf', '.tf.json'))
                or Path(name).name in ('override.tf', 'override.tf.json')
                or name.endswith(('_override.tf', '_override.tf.json'))):
            raise BaselineError('Only reviewed relative Terraform sources are permitted')
    if len(set(values)) != len(values):
        raise BaselineError('Duplicate source selection')
    return tuple(sorted(values))


def prepare(*, source_root, source_files, variables_file, provider_lockfile,
            source_revision, verify_source):
    """Capture explicitly reviewed files and independently verify their revision.

    verify_source(revision, read_only_mapping_of_relative_paths_to_bytes) must
    return literal True after consulting a trusted revision/build record. Never
    implement it as a comparison against a dirty working tree or HEAD's name.
    provider_lockfile=None explicitly records no lock (provider-free recipes).
    """
    _revision(source_revision)
    names = _source_names(source_files)
    if not callable(verify_source):
        raise BaselineError('An independent source verifier is required')
    sources = []
    total = 0
    for name in names:
        raw = _read_path(Path(source_root) / name)
        total += len(raw)
        if total > _MAX_TOTAL:
            raise BaselineError('Source snapshot exceeds aggregate size limit')
        sources.append((name, raw))
    sources = tuple(sources)
    inputs = _read_path(variables_file)
    if len(inputs) > 1024 * 1024:
        raise BaselineError('Approved variables exceed runner size limit')
    try:
        verified = verify_source(source_revision, MappingProxyType(dict(sources)))
    except Exception:
        raise BaselineError('Source revision verification failed; diagnostics withheld') from None
    if verified is not True:
        raise BaselineError('Source revision verification failed')
    return _prepared(source_revision, sources, inputs,
                            _read_path(provider_lockfile) if provider_lockfile is not None else b'',
                            'inputs.tfvars.json' if str(variables_file).endswith('.json') else 'inputs.tfvars',
                            provider_lockfile is not None)


class GitRevisionVerifier:
    """Verify selected blobs against an explicit trusted local Git commit.

    No checkout, whole-tree walk, credentials, hooks or current-HEAD inference.
    The caller supplies/reviews the allowlist (e.g. workstation_source_files).
    Git object availability/authenticity and executable provenance are trust
    prerequisites; this checks equality, not a signature or repository origin.
    """
    def __init__(self, repository_root, source_subdir):
        self.repository_root = Path(repository_root)
        if (not isinstance(source_subdir, str)
                or not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*', source_subdir)
                or any(part in ('.', '..', '.git') for part in source_subdir.split('/'))):
            raise BaselineError('Explicit repository-relative source root required')
        self.source_subdir = source_subdir

    def __call__(self, revision, sources):
        import subprocess
        _revision(revision)
        names = _source_names(tuple(sources))
        environment = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        environment.update(GIT_NO_REPLACE_OBJECTS='1', GIT_CONFIG_NOSYSTEM='1',
                           GIT_CONFIG_GLOBAL='/dev/null', GIT_OPTIONAL_LOCKS='0')
        with _directory(self.repository_root) as fd:
            def git(*args):
                try:
                    result = subprocess.run(['git', '-c', f'safe.directory={self.repository_root}', *args], cwd=f'/proc/self/fd/{fd}',
                        pass_fds=(fd,), env=environment, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, timeout=30, check=True)
                    return result.stdout
                except (OSError, subprocess.SubprocessError):
                    raise BaselineError('Pinned Git source is unavailable') from None
            if git('cat-file', '-t', revision).strip() != b'commit':
                raise BaselineError('Pinned Git revision must be a commit')
            for name in names:
                path = self.source_subdir + '/' + name
                entry = git('ls-tree', '-z', revision, '--', path)
                if not entry.startswith((b'100644 blob ', b'100755 blob ')) or entry.count(b'\0') != 1:
                    raise BaselineError('Selected Git source must be a regular blob')
                obj = revision + ':' + path
                if int(git('cat-file', '-s', obj)) > _MAX_FILE:
                    raise BaselineError('Selected Git blob exceeds snapshot limit')
                if git('show', '--no-ext-diff', '--no-textconv', obj) != sources[name]:
                    return False
        return True


class BaselineStore:
    def __init__(self, root):
        self.root = Path(root)
        with _directory(self.root, private=True, create=True):
            pass

    def _guard(self, parent):
        with _directory(self.root, private=True) as canonical:
            expected, actual = os.fstat(parent), os.fstat(canonical)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise BaselineError('Private baseline directory changed; reconcile publication')

    @contextmanager
    def _publication(self):
        with _directory(self.root, private=True) as parent:
            # One pinned identity and lock for ALL objects plus the receipt.
            fcntl.flock(parent, fcntl.LOCK_EX)
            self._guard(parent)
            yield parent
            self._guard(parent)

    def _write(self, name, raw, *, parent=None):
        if parent is None:
            with self._publication() as directory:
                return self._write(name, raw, parent=directory)
        self._guard(parent)
        try:
            existing = _read_at(parent, name, private=True)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing != raw:
                raise BaselineError('Content address collision or corruption')
            self._guard(parent)
            return
        temporary = 'pending-' + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._guard(parent)
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
            self._guard(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass

    def publish(self, prepared, *, apply_exit_code, state, outputs, verify_applied, applied_at):
        """Caller must verify the exact recipe actually applied, not merely exit 0.

        verify_applied(prepared, state, outputs) must verify expected identity,
        lineage, resources and deployment-specific outputs. The state/outputs
        are private and are not retained; this callback is an explicit trust
        boundary, not an authenticity guarantee from an exit code.
        """
        try:
            if (type(apply_exit_code) is not int or apply_exit_code != 0
                    or type(applied_at) is not int or applied_at < 0
                    or not callable(verify_applied)):
                raise BaselineError('Successful verified apply is required')
            # Freeze observed evidence so a callback cannot repair mismatched outputs.
            state, outputs = json.loads(_json(state)), json.loads(_json(outputs))
            summary = StateSummary.from_state(state)
            normalized_state_outputs = {name: {'sensitive': False, **value}
                                        for name, value in state['outputs'].items()}
            if type(outputs) is not dict or _json(outputs) != _json(normalized_state_outputs):
                raise BaselineError('State/output mismatch')
            for value in outputs.values():
                if (type(value) is not dict or set(value) != {'sensitive', 'type', 'value'}
                        or type(value['sensitive']) is not bool):
                    raise BaselineError('Invalid Terraform output envelope')
            if verify_applied(prepared, state, outputs) is not True:
                raise BaselineError('Verification failed')
        except Exception:
            raise BaselineError('Apply/state/output verification failed; diagnostics withheld') from None
        sources = {name: _sha(raw) for name, raw in prepared._sources}
        baseline = Baseline.from_dict(dict(schema_version=1, source_revision=prepared.source_revision,
            input_digest=_sha(prepared._inputs), lock_digest=_sha(prepared._lock),
            source_digest=digest(sources), inputs_ref='object-' + _sha(prepared._inputs),
            source_ref='object-' + _sha(_json(sources)), applied_at=applied_at))
        assert baseline is not None
        record = dict(schema_version=1, baseline=baseline.to_dict(), sources=sources,
                      inputs_name=prepared.inputs_name, lock_present=prepared.lock_present,
                      state=summary.to_dict())
        raw = _json(record)
        ref = 'baseline-' + _sha(raw)
        with self._publication() as parent:
            for content in (prepared._inputs, prepared._lock, _json(sources),
                            *(value for _, value in prepared._sources)):
                self._write('object-' + _sha(content), content, parent=parent)
            self._write(ref, raw, parent=parent)
        return BaselineReceipt(ref, baseline)

    def _record(self, baseline_ref):
        if not isinstance(baseline_ref, str) or not re.fullmatch(r'baseline-[0-9a-f]{64}', baseline_ref):
            raise BaselineError('Expected opaque applied baseline reference')
        try:
            return self._verified_record(baseline_ref)
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            raise BaselineError('Invalid or unavailable applied baseline; diagnostics withheld') from None

    def _verified_record(self, baseline_ref):
        with _directory(self.root, private=True) as fd:
            raw = _read_at(fd, baseline_ref, private=True)
        if baseline_ref != 'baseline-' + _sha(raw):
            raise BaselineError('Receipt digest mismatch')
        record = json.loads(raw)
        if (type(record) is not dict or set(record) != {'schema_version', 'baseline', 'sources',
                'inputs_name', 'lock_present', 'state'} or _json(record) != raw
                or type(record['schema_version']) is not int or record['schema_version'] != 1
                or type(record['lock_present']) is not bool
                or record['inputs_name'] not in ('inputs.tfvars', 'inputs.tfvars.json')):
            raise BaselineError('Invalid baseline recipe schema')
        summary = record['state']
        if type(summary) is not dict or set(summary) != {'lineage', 'serial', 'addresses'}:
            raise BaselineError('Invalid state binding')
        StateSummary(summary['lineage'], summary['serial'], tuple(summary['addresses']))
        baseline = Baseline.from_dict(record['baseline'])
        if baseline is None:
            raise BaselineError('Missing baseline binding')
        sources = record['sources']
        if type(sources) is not dict:
            raise BaselineError('Invalid source map')
        _source_names(tuple(sources))
        if not record['lock_present'] and baseline.lock_digest != _sha(b''):
            raise BaselineError('Absent lock digest mismatch')
        if (baseline.source_digest != digest(sources)
                or baseline.source_ref != 'object-' + _sha(_json(sources))
                or baseline.inputs_ref != 'object-' + baseline.input_digest):
            raise BaselineError('Recipe binding mismatch')
        self._input_bytes(baseline.input_digest)
        for sha in (baseline.lock_digest, _sha(_json(sources))):
            self._object(sha)
        for _ in self._source_bytes(sources):
            pass
        return record

    def _source_bytes(self, sources):
        total = 0
        for name, sha in sources.items():
            raw = self._object(sha)
            total += len(raw)
            if total > _MAX_TOTAL:
                raise BaselineError('Source snapshot exceeds aggregate size limit')
            yield name, raw

    def _input_bytes(self, sha):
        raw = self._object(sha)
        if len(raw) > 1024 * 1024:
            raise BaselineError('Approved variables exceed runner size limit')
        return raw

    def _object(self, sha):
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise BaselineError('Invalid snapshot content address')
        with _directory(self.root, private=True) as fd:
            raw = _read_at(fd, 'object-' + sha, private=True)
        if _sha(raw) != sha:
            raise BaselineError('Snapshot digest mismatch')
        return raw

    def load(self, baseline_ref):
        if baseline_ref is None:
            return None
        record = self._record(baseline_ref)
        baseline = Baseline.from_dict(record['baseline'])
        assert baseline is not None
        return BaselineReceipt(baseline_ref, baseline)

    def lifecycle_status(self, baseline_ref):
        """Historical snapshot status, NOT a claim that infrastructure still exists."""
        return 'unknown' if self.load(baseline_ref) is None else 'applied'

    def reconstruct(self, baseline_ref, destination):
        """Verify the receipt and all referenced bytes; never consult current HEAD.

        The protected receipt binds the verified revision to its source digest.
        Store ownership is the trust anchor, not a signature. No missing-snapshot
        fallback and no automatic local-state migration or destruction.
        """
        record = self._record(baseline_ref)
        baseline = Baseline.from_dict(record['baseline'])
        assert baseline is not None
        # Re-read with digest checks into immutable memory, not check-then-copy.
        prepared = _prepared(baseline.source_revision,
            tuple(self._source_bytes(record['sources'])),
            self._input_bytes(baseline.input_digest), self._object(baseline.lock_digest),
            record['inputs_name'], record['lock_present'])
        paths = _materialize(prepared, destination)
        return ReconstructedBaseline(baseline, paths.source_root, paths.source_files, paths.variables_file)
