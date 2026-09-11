"""Isolated Terraform execution with exact saved plans and native locking.

Only trusted, explicitly selected source files may be staged. Terraform source
and providers are executable code; this is isolation, not a security sandbox.
Local operations are supported directly. GCS saved-plan apply requires the
trusted live backend_runtime guard (destination, occupancy and protocol fences).
S3/Azure mutation and remote resource import remain disabled. GCS destruction
uses plan(destroy=True) followed by apply, never the direct destroy shortcut.
Even init/plan/output may contact a backend or execute trusted providers; they
are not offline validation APIs. No migration or arbitrary-command API.
"""
from contextlib import ExitStack
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid

from src.python.terraform_backend import validate_terraform_version


class TerraformRunnerError(RuntimeError):
    """Sanitized execution failure; never contains Terraform output or inputs."""


class TerraformLockError(TerraformRunnerError):
    """The controller-local operation lock was not acquired in time."""


class TerraformCancelled(TerraformRunnerError):
    """Operation cancelled; an interrupted mutation may have partially completed."""


class TerraformTimeout(TerraformRunnerError):
    """Command deadline exceeded; mutation outcome may be partial/unknown."""


def _no_symlinks(path):
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise TerraformRunnerError("Symlink or traversal path is forbidden")


def _private_write(path, content):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def _file_bytes(path):
    _no_symlinks(path)
    try:
        if not path.is_file():
            raise TerraformRunnerError("Required private file is missing or not regular")
        return path.read_bytes()
    except OSError:
        raise TerraformRunnerError("Cannot read private operation file; diagnostics withheld") from None


def _json_object(raw):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise TerraformRunnerError("Terraform returned malformed JSON; diagnostics withheld") from None
    if not isinstance(result, dict):
        raise TerraformRunnerError("Terraform JSON must be an object; diagnostics withheld")
    return result


def _input_snapshot(path, *, label="Variable"):
    """Bounded no-follow snapshot of an explicitly selected source or var-file."""
    path = Path(path)
    if not path.is_absolute():
        raise TerraformRunnerError(f"{label} file must use an absolute path")
    if ".." in path.parts:
        raise TerraformRunnerError("Symlink or traversal path is forbidden")
    try:
        with ExitStack() as descriptors:
            # Pin each directory before resolving its child. O_NOFOLLOW on an
            # absolute final open alone does not protect renamed ancestors.
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
            parent_fd = os.open(path.anchor, flags)
            descriptors.callback(os.close, parent_fd)
            for component in path.parts[1:-1]:
                parent_fd = os.open(component, flags, dir_fd=parent_fd)
                descriptors.callback(os.close, parent_fd)
            fd = os.open(path.name or ".", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                         | os.O_CLOEXEC, dir_fd=parent_fd)
            descriptors.callback(os.close, fd)
            # The stack owns fd even if fdopen fails; the stream never closes
            # it independently, avoiding both leaks and double-close errors.
            with os.fdopen(fd, "rb", closefd=False) as stream:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                    raise TerraformRunnerError(f"{label} file must be regular and at most 1 MiB")
                content = stream.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise TerraformRunnerError(f"{label} file exceeds the operation size limit")
            return content
    except (OSError, ValueError):
        raise TerraformRunnerError(f"{label} file is unavailable; diagnostics withheld") from None


@dataclass(frozen=True)
class SavedPlan:
    """Private, context-owned plan receipt; has_changes reflects exit code 2.

    The binary at path can contain secrets. digest is its SHA-256, not a policy
    approval or proof of ownership. A newer plan invalidates the previous one.
    """
    has_changes: bool
    path: Path = field(repr=False)
    digest: str = ""


class TerraformRunner:
    """One single-use context spanning init, plan, apply/output or destroy.

    Local state lives at state_root/deployment_name/.tfstate, never in staging.
    environment is a caller-approved credential/proxy environment; if omitted,
    inherit the controller environment. Returned output JSON is SECRET-BEARING:
    callers must not log it. Mutation acknowledgements are intent, not verified
    ownership or a remote lifecycle authorization policy.

    source_files is a nonempty explicit list of relative .tf/.tf.json sources
    and optionally .terraform.lock.hcl; there is no recursive copy or asset
    discovery. Relative module topology inside source_root is preserved.
    Sources and variables_file are immutable construction-time snapshots, each
    selected file regular and at most 1 MiB, read through no-follow descriptors.
    Original sources are never reopened during lock waiting or staging.
    variables is copied as JSON into a private, explicitly supplied var-file.
    All inherited TF_* settings are removed (nondefault TF_WORKSPACE rejects),
    including logging, CLI injection, implicit variables and shared caches.

    Linux/Python >=3.10 is required (flock, process groups, /proc/self/fd).
    A context must be used serially by one thread; distinct contexts may run
    concurrently. Set cancel_event (threading.Event) to cancel a command or
    lock wait. command_timeout bounds each command; controller_lock_timeout
    defaults to BackendSpec.timeout_seconds, also used for Terraform locking.
    All callers must share lock_root (default /tmp/isaac-tf-locks-<uid>).
    Locks span the whole context, coordinate only this controller/user, and do
    not serialize other controllers or raw Terraform/cloud/SSH operations.

    init/apply/destroy return None, plan returns SavedPlan, output returns a
    secret-bearing Terraform output object (native value/type/sensitive).
    An empty output object is NOT proof of an empty or destroyed deployment.
    backend_identity is canonical JSON of BackendSpec.identity(); local locking
    instead uses the exact absolute local_state_path. Read-only staged_root,
    data_dir and local_state_path properties are Paths (last is None remotely).
    After assert_no_recovery() or context exit, recovery_directory/recovery_state
    are read-only Paths when errored.tfstate exists or cannot be safely ruled
    out, otherwise None. Once observed, recovery retention is never cleared.
    Recovery retains the entire private staging directory (including secrets),
    without automatic deletion, copying, state restoration or pushing. Default
    /tmp staging is NOT reboot-durable. Controllers can select an absolute,
    private staging_root on durable storage (record_runner and Deployer do).
    remote_guard(runner, operation) is a trusted callback invoked before/after
    init and immediately before GCS apply. It is never serialized as authority.
    Callers must arrange secure retention and manual recovery review, then
    explicitly remove the directory once it is no longer needed.
    """

    def __init__(self, *, source_root, source_files, backend_spec, target_scope,
                 deployment_name, state_root=None, environment=None, variables=None,
                 terraform_binary="terraform", command_timeout=300,
                 lock_root=None, controller_lock_timeout=None, cancel_event=None,
                 variables_file=None, remote_guard=None, staging_root=None):
        # Trusted controller callback, not a serialized approval or auth flag.
        self._remote_guard = remote_guard
        self._staging_root = Path(staging_root) if staging_root is not None else None
        if self._staging_root is not None:
            if not self._staging_root.is_absolute():
                raise TerraformRunnerError('Staging root must be absolute')
            _no_symlinks(self._staging_root)
        self._source_root = Path(source_root).absolute()
        self._source_files = tuple(source_files)
        if not self._source_files or len(set(self._source_files)) != len(self._source_files):
            raise TerraformRunnerError("Provide a nonempty, unique source-file allowlist")
        self._backend = backend_spec.backend
        self._lock_timeout = backend_spec.timeout_seconds
        identity = backend_spec.identity(target_scope, deployment_name)
        self._backend_identity = (identity if isinstance(identity, str) else
                                  json.dumps(identity, sort_keys=True, separators=(",", ":")))
        self._environment = dict(os.environ if environment is None else environment)
        if any(not isinstance(key, str) or not isinstance(value, str) or "\0" in key + value
               or "=" in key for key, value in self._environment.items()):
            raise TerraformRunnerError("Approved process environment contains invalid entries")
        if self._environment.get("TF_WORKSPACE", "default") != "default":
            raise TerraformRunnerError("Only the default Terraform workspace is permitted")
        self._environment = {key: value for key, value in self._environment.items()
                             if not key.startswith("TF_")}
        if variables_file is not None and variables is not None:
            raise TerraformRunnerError("Choose native variables or one existing variable file, not both")
        if variables is None:
            variables = {}
        if not isinstance(variables, dict) or any(not isinstance(key, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", key) for key in variables):
            raise TerraformRunnerError("Approved variables must be a mapping of valid variable names")
        try:
            self._variables_json = json.dumps(variables, allow_nan=False).encode()
        except (TypeError, ValueError):
            raise TerraformRunnerError("Approved variables must contain JSON values") from None
        self._variables_name = "inputs.tfvars.json"
        if variables_file is not None:
            self._variables_json = _input_snapshot(variables_file)
            self._variables_name = "inputs.tfvars.json" if str(variables_file).endswith(".json") else "inputs.tfvars"
        self._binary = terraform_binary
        if not isinstance(terraform_binary, str) or not terraform_binary or "\0" in terraform_binary:
            raise TerraformRunnerError("Select a valid Terraform executable")
        self._timeout = command_timeout
        self._local_state_path = None
        if self._backend == "local":
            if state_root is None or not Path(state_root).is_absolute():
                raise TerraformRunnerError("Local state requires an absolute durable state root")
            root = Path(state_root)
            self._local_state_path = root / deployment_name / ".tfstate"
            _no_symlinks(self._local_state_path)
            if self._local_state_path.parent.parent != root:
                raise TerraformRunnerError("Local state must remain inside the approved state root")
        self._config = backend_spec.backend_config(target_scope, deployment_name,
                          local_state_path=str(self.local_state_path) if self.local_state_path else None)
        self._temp = None
        self._initialized = False
        self._recovery_directory = None
        self._recovery_state = None
        self._plan = None
        self._cancel = cancel_event if cancel_event is not None else threading.Event()
        self._controller_lock_timeout = (self._lock_timeout if controller_lock_timeout is None
                                         else controller_lock_timeout)
        for duration in (command_timeout, self._controller_lock_timeout):
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                raise TerraformRunnerError("Timeouts must be finite positive seconds")
        self._lock_root = Path(lock_root) if lock_root is not None else Path(f"/tmp/isaac-tf-locks-{os.getuid()}")
        if not self._lock_root.is_absolute():
            raise TerraformRunnerError("Controller lock root must be absolute")
        self._lock_fd = None
        self._entered = False
        self._pinned_files = {}
        self._source_snapshots = self._snapshot_sources()

    @property
    def staged_root(self):
        return self._staged_root

    @property
    def data_dir(self):
        return self._data_dir

    @property
    def local_state_path(self):
        return self._local_state_path

    @property
    def backend_identity(self):
        return self._backend_identity

    @property
    def recovery_directory(self):
        return self._recovery_directory

    @property
    def recovery_state(self):
        """Candidate recovery path, not a guarantee of readable/valid state."""
        return self._recovery_state

    def _snapshot_sources(self):
        snapshots = []
        _no_symlinks(self._source_root)
        for relative in self._source_files:
            path = Path(relative)
            name = path.name.lower()
            if (path.is_absolute() or not path.parts or ".." in path.parts
                    or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts)
                    or any(part.lower() in {".terraform", "state", "credentials", ".ssh", "inventory"}
                           for part in path.parts)
                    or any(word in name for word in ("credential", "inventory", "tfstate", "auto.tfvars"))
                    or name in {"override.tf", "override.tf.json"}
                    or name.endswith(("_override.tf", "_override.tf.json"))
                    or not (name.endswith((".tf", ".tf.json")) or name == ".terraform.lock.hcl")):
                raise TerraformRunnerError("Only explicit safe Terraform source paths may be staged")
            snapshots.append((relative, _input_snapshot(self._source_root / path, label="Source")))
        return tuple(snapshots)

    def __enter__(self):
        if self._entered:
            raise TerraformRunnerError("Terraform contexts are single-use")
        self._entered = True
        try:
            self._acquire_lock()
            return self._stage()
        except BaseException as error:
            self.__exit__(None, None, None)
            if isinstance(error, OSError):
                raise TerraformRunnerError("Cannot prepare private Terraform context; diagnostics withheld") from None
            raise

    def _acquire_lock(self):
        _no_symlinks(self._lock_root)
        self._lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self._lock_root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TerraformLockError("Controller lock directory must be private and owned by this user")
        identity = ("local:" + str(self.local_state_path) if self.local_state_path is not None
                    else self.backend_identity)
        key = hashlib.sha256(identity.encode()).hexdigest()
        # Never unlink lock files: waiters must keep locking the same inode.
        self._lock_fd = os.open(self._lock_root / (key + ".lock"),
                                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        deadline = time.monotonic() + self._controller_lock_timeout
        while True:
            if self._cancel.is_set():
                raise TerraformCancelled("Terraform operation cancelled")
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TerraformLockError("Controller operation lock timed out") from None
                self._cancel.wait(min(0.05, remaining))

    def _stage(self):
        # Explicit ownership: no finalizer may delete retained recovery state.
        if self._staging_root is not None:
            _no_symlinks(self._staging_root)
            self._staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self._staging_root.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise TerraformRunnerError('Staging root must be private and owned by this user')
        self._temp = Path(tempfile.mkdtemp(prefix="isaac-tf-", dir=self._staging_root or '/tmp'))
        base = self._temp
        self._staged_root = base / "source"
        self._data_dir = base / "data"
        self.staged_root.mkdir(mode=0o700)
        self.data_dir.mkdir(mode=0o700)
        for relative, content in self._source_snapshots:
            destination = self.staged_root / relative
            for parent in reversed(destination.parents):
                if parent.is_relative_to(self.staged_root):
                    parent.mkdir(mode=0o700, exist_ok=True)
            _private_write(destination, content)
        if self.local_state_path is not None:
            _no_symlinks(self.local_state_path)
            self.local_state_path.parent.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.local_state_path.parent.mkdir(mode=0o700, exist_ok=True)
            os.chmod(self.local_state_path.parent, 0o700)
        _private_write(self.staged_root / "runner_override.tf.json", json.dumps(
            {"terraform": {"backend": {self._backend: {}}}}).encode())
        self._config_path = base / "backend.hcl"
        _private_write(self._config_path, "\n".join(
            f"{key} = {json.dumps(value)}" for key, value in sorted(self._config.items())).encode())
        self._variables_path = base / self._variables_name
        _private_write(self._variables_path, self._variables_json)
        cli_config = base / "terraform.rc"
        _private_write(cli_config, b"disable_checkpoint = true\n")
        self._environment.update(TF_DATA_DIR=str(self.data_dir), TF_INPUT="0", TF_IN_AUTOMATION="1",
                                 TF_WORKSPACE="default", TF_CLI_CONFIG_FILE=str(cli_config))
        self._pin_files([self.staged_root / relative for relative in self._source_files] +
                        [self.staged_root / "runner_override.tf.json", self._config_path,
                         self._variables_path, cli_config])
        return self

    def _pin_files(self, paths):
        for path in paths:
            self._pinned_files[path] = hashlib.sha256(_file_bytes(path)).hexdigest()

    def _require_context(self, initialized=True):
        if self._temp is None or self._lock_fd is None:
            raise TerraformRunnerError("An active locked Terraform context is required")
        if initialized and not self._initialized:
            raise TerraformRunnerError("Explicit successful init is required")
        _no_symlinks(self.staged_root)
        _no_symlinks(self.data_dir)
        workspace = self.data_dir / "environment"
        if workspace.exists() or workspace.is_symlink():
            if _file_bytes(workspace).strip() != b"default":
                raise TerraformRunnerError("Initialized Terraform workspace does not match the pinned identity")
        for path, digest in self._pinned_files.items():
            if hashlib.sha256(_file_bytes(path)).hexdigest() != digest:
                raise TerraformRunnerError("Pinned operation files changed; discard this context")
        if self.local_state_path is not None:
            for path in (self.local_state_path, Path(str(self.local_state_path) + ".backup"),
                         self.local_state_path.parent / ("." + self.local_state_path.name + ".lock.info")):
                _no_symlinks(path)

    def assert_no_recovery(self):
        """Refuse cleanup unless recovery is absent in this active locked context.

        Returns None on confirmed absence, otherwise records recovery paths and
        raises TerraformRunnerError without releasing the controller lock. This
        does not prove that authoritative state is empty or authorize deletion.
        """
        self._require_context(initialized=False)
        if self._retain_recovery():
            raise TerraformRunnerError("Possible Terraform recovery state retained; inspect "
                                       "recovery_directory and recovery_state before cleanup")

    def retain_recovery(self):
        """Retain private operation evidence after uncertain publication, even
        without errored.tfstate. Select a durable staging_root for reboot safety.
        Callers must review/remove the directory explicitly, never auto-retry.
        """
        self._require_context(initialized=False)
        self._recovery_directory = self._temp
        self._recovery_state = self.staged_root / 'errored.tfstate'

    def _retain_recovery(self):
        """Only a confirmed absent marker permits deleting private staging."""
        # An earlier active-context check may already have observed recovery or
        # uncertainty. Never erase that evidence on a subsequent cleanup probe.
        if self._recovery_directory is not None:
            return True
        with ExitStack() as descriptors:
            try:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
                base_fd = os.open(self._temp, flags)
                descriptors.callback(os.close, base_fd)
                os.fchmod(base_fd, 0o700)
                source_fd = os.open("source", flags, dir_fd=base_fd)
                descriptors.callback(os.close, source_fd)
                os.fchmod(source_fd, 0o700)
                try:
                    info = os.stat("errored.tfstate", dir_fd=source_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return False
                if stat.S_ISREG(info.st_mode):
                    fd = os.open("errored.tfstate", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=source_fd)
                    descriptors.callback(os.close, fd)
                    current = os.fstat(fd)
                    if (stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                            and current.st_uid == os.getuid()
                            and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)):
                        os.fchmod(fd, 0o600)
            except OSError:
                # Unknown/unreadable/nonregular markers or failed permission
                # hardening must never cause loss of the only recovery copy.
                pass
        self._recovery_directory = self._temp
        self._recovery_state = self.staged_root / "errored.tfstate"
        return True

    def __exit__(self, exc_type, exc_value, traceback):
        self._initialized = False
        self._plan = None
        retained = False
        try:
            if self._temp is not None:
                retained = self._retain_recovery()
                if not retained:
                    shutil.rmtree(self._temp)
                self._temp = None
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
        if retained:
            message = ("Possible Terraform recovery state retained; inspect recovery_directory "
                       "and recovery_state for secure retention and manual recovery review "
                       "before retrying. Staging contains secrets; durability depends on staging_root.")
            if isinstance(exc_value, TerraformRunnerError):
                exc_value.args = (str(exc_value) + "; " + message,)
            elif exc_value is None:
                raise TerraformRunnerError(message)

    def _execute(self, arguments, accepted=(0,), pass_fds=()):
        self._require_context(initialized=arguments[0] not in ("version", "init"))
        if self._cancel.is_set():
            raise TerraformCancelled("Terraform operation cancelled")
        try:
            process = subprocess.Popen([self._binary, *arguments], cwd=self.staged_root,
                                       env=self._environment, shell=False, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True, umask=0o077, pass_fds=pass_fds)
        except OSError:
            raise TerraformRunnerError("Terraform could not start; check the selected executable") from None
        try:
            deadline = time.monotonic() + self._timeout
            while True:
                if self._cancel.is_set():
                    raise TerraformCancelled("Terraform operation cancelled; mutation outcome may be partial")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TerraformTimeout("Terraform command timed out; mutation outcome may be partial")
                try:
                    stdout, _ = process.communicate(timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException as error:
            self._stop_process_group(process)
            self._plan = None
            self._initialized = False
            if isinstance(error, KeyboardInterrupt):
                raise TerraformCancelled("Terraform operation interrupted; mutation outcome may be partial") from None
            if isinstance(error, OSError):
                raise TerraformRunnerError("Terraform process communication failed; diagnostics withheld") from None
            raise
        if process.returncode not in accepted:
            raise TerraformRunnerError("Terraform command failed; diagnostics withheld")
        return process.returncode, stdout

    @staticmethod
    def _stop_process_group(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # Kill descendants even when the leader exited during the grace period.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()

    def init(self):
        """Version-gated fresh initialization; no upgrades or migration flags."""
        self._require_context(initialized=False)
        if self._initialized:
            raise TerraformRunnerError("This context has already initialized its pinned backend")
        _, raw = self._execute(["version", "-json"])
        version = _json_object(raw).get("terraform_version")
        try:
            validate_terraform_version(version, self._backend)
        except ValueError:
            raise TerraformRunnerError("Unsupported Terraform version for selected backend; local requires "
                                       "stable >=1.3.5,<2 and remote requires stable >=1.10.0,<2") from None
        arguments = ["init", "-input=false", "-no-color", f"-backend-config={self._config_path}",
                     f"-lock-timeout={self._lock_timeout}s"]
        if ".terraform.lock.hcl" in self._source_files:
            arguments.append("-lockfile=readonly")
        if self._remote_guard is not None:
            self._remote_guard(self, 'pre-init')
        self._execute(arguments)
        metadata = self.data_dir / "terraform.tfstate"
        backend = _json_object(_file_bytes(metadata)).get("backend")
        if (not isinstance(backend, dict) or backend.get("type") != self._backend
                or not isinstance(backend.get("config"), dict)
                or any(backend["config"].get(key) != value for key, value in self._config.items())):
            raise TerraformRunnerError("Initialized Terraform backend does not match the pinned identity")
        self._require_context(initialized=False)
        self._pin_files([metadata])
        self._initialized = True
        if self._remote_guard is not None:
            try:
                self._remote_guard(self, 'init')
            except BaseException:
                self._initialized = False
                raise

    def plan(self, *, destroy=False, refresh_only=False):
        """Save a private refresh-enabled plan; distinguish Terraform exits 0/2."""
        self._require_context()
        if type(destroy) is not bool or type(refresh_only) is not bool or (destroy and refresh_only):
            raise TerraformRunnerError("Select one valid Terraform planning mode")
        self._plan = None
        path = self.staged_root.parent / (uuid.uuid4().hex + ".tfplan")
        mode = ["-destroy"] if destroy else (["-refresh-only"] if refresh_only else [])
        code, _ = self._execute(["plan", "-input=false", "-no-color", "-detailed-exitcode",
                                f"-out={path}", f"-var-file={self._variables_path}",
                                f"-lock-timeout={self._lock_timeout}s", *mode], accepted=(0, 2))
        _no_symlinks(path)
        self._plan = SavedPlan(code == 2, path, hashlib.sha256(_file_bytes(path)).hexdigest())
        return self._plan

    def _verified_plan_bytes(self, plan):
        self._require_context()
        if plan is not self._plan or plan is None:
            raise TerraformRunnerError("Operation requires this context's unconsumed saved plan")
        _no_symlinks(plan.path)
        contents = _file_bytes(plan.path)
        if hashlib.sha256(contents).hexdigest() != plan.digest:
            raise TerraformRunnerError("Saved plan changed; create and approve a new plan")
        return contents

    def plan_json(self, plan):
        """Inspect the exact private saved plan. Returned JSON may contain secrets."""
        contents = self._verified_plan_bytes(plan)
        with tempfile.TemporaryFile(dir=self.staged_root.parent) as snapshot:
            snapshot.write(contents)
            snapshot.flush()
            snapshot.seek(0)
            fd = snapshot.fileno()
            _, raw = self._execute(["show", "-json", f"/proc/self/fd/{fd}"], pass_fds=(fd,))
        return _json_object(raw)

    def pull_state(self):
        """Read authoritative v4 state; unavailable is never interpreted as empty.

        This is secret-bearing state, not a public receipt or proof of cloud
        ownership. Terraform/backend errors are preserved as sanitized failures.
        """
        _, raw = self._execute(["state", "pull"])
        state = _json_object(raw)
        if (type(state.get("version")) is not int or state["version"] != 4
                or not isinstance(state.get("lineage"), str) or not state["lineage"].strip()
                or type(state.get("serial")) is not int or state["serial"] < 0
                or not isinstance(state.get("resources"), list)
                or not isinstance(state.get("outputs"), dict)
                or any(not isinstance(value, dict) for value in state["outputs"].values())):
            raise TerraformRunnerError("Terraform state identity or envelope is invalid; diagnostics withheld")
        for resource in state["resources"]:
            if (not isinstance(resource, dict) or resource.get("mode") not in ("managed", "data")
                    or not isinstance(resource.get("instances"), list)
                    or any(not isinstance(instance, dict) for instance in resource["instances"])):
                raise TerraformRunnerError("Terraform state resource envelope is invalid; diagnostics withheld")
        return state

    def apply(self, plan, *, acknowledge_mutation=False):
        """Consume an exact saved plan once; GCS requires a live controller guard."""
        self._require_context()
        if self._backend != "local" and (self._backend != "gcs" or not callable(self._remote_guard)):
            raise TerraformRunnerError("Remote mutation requires the supported GCS runtime guard")
        if acknowledge_mutation is not True:
            raise TerraformRunnerError("Mutation requires explicit acknowledgement")
        contents = self._verified_plan_bytes(plan)
        self._plan = None  # Never replay after any attempted apply, including partial failure.
        if self._backend == 'gcs':
            self._remote_guard(self, 'apply')
        # Pass an anonymous verified snapshot, not the caller-visible path.
        # The Linux container is the supported runner platform.
        with tempfile.TemporaryFile(dir=self.staged_root.parent) as snapshot:
            snapshot.write(contents)
            snapshot.flush()
            snapshot.seek(0)
            fd = snapshot.fileno()
            try:
                self._execute(["apply", "-input=false", "-no-color",
                               f"-lock-timeout={self._lock_timeout}s", f"/proc/self/fd/{fd}"], pass_fds=(fd,))
            except BaseException:
                if self._backend == 'gcs':
                    self.retain_recovery()
                raise

    def import_resource(self, address, resource_id, *, acknowledge_mutation=False):
        """Explicit local ownership adoption in this isolated context.

        Only unindexed static resource addresses are supported. The caller must
        establish that adoption is authorized; this method is never a plan step.
        """
        self._require_context()
        if self._backend != "local":
            raise TerraformRunnerError("Remote import requires verified attachment and ownership")
        if acknowledge_mutation is not True:
            raise TerraformRunnerError("Import requires explicit mutation acknowledgement")
        if (not isinstance(address, str) or len(address) > 512 or not re.fullmatch(
                r"(?:module\.[A-Za-z_][A-Za-z0-9_-]*\.)*[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_-]*", address)
                or not isinstance(resource_id, str) or not resource_id or len(resource_id) > 4096
                or resource_id.startswith("-") or any(ord(char) < 32 or ord(char) == 127 for char in resource_id)):
            raise TerraformRunnerError("Invalid static import address or resource identifier")
        self._plan = None
        self._execute(["import", "-input=false", "-no-color",
                       f"-lock-timeout={self._lock_timeout}s", f"-var-file={self._variables_path}",
                       address, resource_id])

    def output(self):
        """Return validated but SECRET-BEARING output JSON; never log this value."""
        _, raw = self._execute(["output", "-json", "-no-color"])
        outputs = _json_object(raw)
        if any(not isinstance(item, dict) or not {"value", "type", "sensitive"} <= item.keys()
               or type(item["sensitive"]) is not bool for item in outputs.values()):
            raise TerraformRunnerError("Terraform output JSON has an invalid schema; diagnostics withheld")
        return outputs

    def destroy(self, *, acknowledge_mutation=False):
        """Local only: acknowledged direct destroy; caller must verify destruction."""
        self._require_context()
        if self._backend != "local":
            raise TerraformRunnerError("Remote mutation is disabled until occupancy/attachment/lineage gates are integrated")
        if acknowledge_mutation is not True:
            raise TerraformRunnerError("Mutation requires explicit acknowledgement")
        self._plan = None
        self._execute(["destroy", "-input=false", "-no-color", "-auto-approve",
                       f"-var-file={self._variables_path}", f"-lock-timeout={self._lock_timeout}s"])
