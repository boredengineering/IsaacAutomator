"""Explicit one-way directory transfers, using structured subprocess arguments.

The selected source wins: rsync may overwrite changed destination files even
without deletion. This is NOT a bidirectional conflict merge or a backup tool.
Rsync's normal size/mtime comparison decides what changes; symlinks are preserved,
not dereferenced. Exclusions cover common state/secret stores, not every possible
secret filename: select a narrow working directory and inspect --dry-run first.
Never select a live database directory; use database-consistent exports instead.

Requires rsync 3.x on both ends and OpenSSH supporting accept-new. The one-hour
transfer deadline, 60-second rsync idle timeout, and SSH liveness probes bound
failures. Re-run the same direction/paths to resume .rsync-partial files.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import posixpath
import re
import shlex
import subprocess

import click


DEFAULT_EXCLUDES = (
    "state/", ".terraform/", ".terraform.lock.hcl", ".tfstate*", "*.tfstate*",
    ".tfvars", "*.tfvars", "*.tfvars.json", ".tfplan", "*.tfplan",
    "credentials/", "credentials.json", ".credentials/", "secrets/",
    ".env", ".env.*", "*.pem", "*.key",
    ".ssh/", ".aws/", ".azure/", ".config/gcloud/", "application_default_credentials.json",
    ".git/", ".hermes/", ".agents/memory/", "neo4j/data/", "neo4j/logs/",
)


@dataclass(frozen=True)
class TransferEndpoint:
    """Explicit SSH identity; construct independently of Terraform for fixtures.

    ``known_hosts_file`` belongs to this deployment. First use trusts the key
    with OpenSSH's accept-new policy; a CHANGED key is refused, never removed.
    To pre-pin trust, populate that file through an independently verified path.
    Ambient SSH config is not used. The caller supplies an existing identity.
    """
    host: str
    user: str
    identity_file: str
    known_hosts_file: str
    iap: bool = False
    instance: str = ""
    project: str = ""
    zone: str = ""

    def __post_init__(self):
        for label, value, pattern in (
            ("host", self.host, r"[A-Za-z0-9][A-Za-z0-9.-]*"),
            ("user", self.user, r"[A-Za-z0-9_][A-Za-z0-9_.-]*"),
        ):
            if not isinstance(value, str) or not re.fullmatch(pattern, value) or value == "NA":
                raise ValueError(f"Missing or unsafe SSH {label}")
        if self.iap:
            for value in (self.instance, self.project, self.zone):
                if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", value):
                    raise ValueError("IAP requires an explicit safe instance, project and zone")
        for value in (self.identity_file, self.known_hosts_file):
            if (not isinstance(value, str) or not Path(value).is_absolute()
                    or any(c in value for c in "\x00\n\r%$") or ".." in Path(value).parts):
                raise ValueError("SSH identity and known-host paths must be absolute and literal")
        trust = Path(self.known_hosts_file)
        if (any(part.is_symlink() for part in (trust, *trust.parents))
                or (trust.exists() and not trust.is_file())):
            raise ValueError("Known-hosts must be a regular non-symlinked file")

    def ssh_argv(self):
        """Return SSH argv, preserving identity and trust-file spaces."""
        known_hosts = self.known_hosts_file.replace("\\", "\\\\").replace('"', '\\"')
        argv = ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", f'UserKnownHostsFile="{known_hosts}"',
                "-o", "ConnectTimeout=30", "-o", "ServerAliveInterval=15",
                "-o", "ServerAliveCountMax=3", "-i", self.identity_file]
        if self.iap:
            proxy = ["gcloud", "compute", "start-iap-tunnel", self.instance, "22",
                     "--listen-on-stdin", f"--project={self.project}",
                     f"--zone={self.zone}", "--quiet"]
            argv.extend(["-o", "ProxyCommand=" + shlex.join(proxy),
                         "-o", f"HostKeyAlias={self.instance}.{self.project}.{self.zone}"])
        return argv


def endpoint_from_config(metadata, outputs, deployment_dir, *, role="isaac_workstation",
                         default_user="ubuntu", gcloud_runner=None):
    """Resolve a transfer endpoint from saved params and authoritative outputs.

    No Terraform state is opened here. ``outputs`` accepts plain values or native
    Terraform output envelopes. OS Login uses gcloud's selected username/key,
    never the deployment's generic SSH username. Only identity fields from its
    dry-run are consumed; its unchecked host policy/ProxyCommand are NOT reused.
    gcloud uses the caller's existing authentication; no credentials are logged.
    Authenticate/authorize SSH with gcloud separately if discovery cannot select
    an existing key. No generic-user fallback is attempted for OS Login.

    For an independent private-VM fixture, pass params containing cloud="gcp",
    project, zone, enable_iap_only=True and enable_oslogin=True, plus the actual
    isaac_workstation_vm_id output. deployment_dir is an existing local directory
    for the known_hosts file, not necessarily an Isaac deployment/state folder.
    Alternatively construct TransferEndpoint directly with a preauthorized user
    and identity_file; iap=True uses instance/project/zone and needs no public IP.
    """
    params = metadata.get("params", metadata)

    def output(name, default=""):
        value = outputs.get(name, default)
        value = value.get("value", default) if isinstance(value, dict) else value
        return default if value is None or value == "" else value

    def flag(name, saved_name):
        value = str(output(name, params.get(saved_name, False))).lower()
        if value not in ("true", "false"):
            raise ValueError("Invalid saved SSH security setting")
        return value == "true"

    vm_id = output(f"{role}_vm_id")
    match = re.search(r"(?:^|/)projects/([^/]+)/zones/([^/]+)/instances/([^/]+)$", vm_id)
    project, zone, instance = match.groups() if match else (
        params.get("project", ""), params.get("zone", ""), vm_id)
    cloud = output("cloud", params.get("cloud", ""))
    iap = cloud == "gcp" and flag("iap_enabled", "enable_iap_only")
    os_login = cloud == "gcp" and flag("oslogin_enabled", "enable_oslogin")
    user, identity = default_user, str(Path(deployment_dir) / "key.pem")
    if iap or os_login:
        if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", v)
               or v == "NA" for v in (instance, project, zone)):
            raise ValueError("IAP/OS Login requires an actual instance, project and zone")
    if os_login:
        argv = ["gcloud", "compute", "ssh", instance, f"--project={project}",
                f"--zone={zone}", "--dry-run", "--quiet"]
        if iap:
            argv.append("--tunnel-through-iap")
        try:
            result = (gcloud_runner or subprocess.run)(argv, check=True, text=True,
                                                      capture_output=True, timeout=60)
            ssh = shlex.split(result.stdout)
            if (not ssh or Path(ssh[0]).name != "ssh" or ssh.count("-i") != 1
                    or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*", ssh[-1])):
                raise ValueError()
            identity = ssh[ssh.index("-i") + 1]
            user = ssh[-1].split("@", 1)[0]
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            raise ValueError("OS Login identity discovery failed; verify gcloud SSH access with your existing identity") from None
    return TransferEndpoint(host=instance if iap else output(f"{role}_ip"),
                            user=user, identity_file=identity,
                            known_hosts_file=str(Path(deployment_dir) / "known_hosts"),
                            iap=iap, instance=instance, project=project, zone=zone)


def load_endpoint(deployment_name, role="isaac_workstation", *, debug=False):
    """Use the shared backend bridge once; never fall back to a remote snapshot."""
    from src.python import utils
    from src.python.config import c as config
    from src.python.backend_runtime import load_backend_record, record_runner

    directory = utils.approved_deployment_path(deployment_name)
    record = load_backend_record(deployment_name, state_root=directory.parent)
    metadata = utils.read_meta(deployment_name, verbose=debug)
    if record is not None:
        with record_runner(record, state_root=directory.parent, read_only=True) as runner:
            runner.init()
            outputs = runner.output()
    else:
        names = ("cloud", f"{role}_ip", f"{role}_vm_id", "iap_enabled", "oslogin_enabled")
        outputs = {name: utils.read_tf_output(deployment_name, name, verbose=debug)
                   for name in names}
    return endpoint_from_config(metadata, outputs, directory, role=role,
                                default_user=config["default_ssh_user"])


def host_transfer_invocation(direction, arguments, repo_root, environment=None):
    """Return ``(run_argv, scoped_env)`` for a host upload/download invocation.

    ``arguments`` excludes the executable; relative --local-dir paths are relative
    to the host's current working directory. ``environment=None`` copies os.environ;
    supplied mappings and arguments are never mutated. Inherited transfer transport
    variables are removed, then set only for an explicit --local-dir selection.

    The run wrapper binds ISAAC_TRANSFER_LOCAL_DIR to /run/isaac-transfer-local.
    ISAAC_TRANSFER_READ_ONLY is "true" for push or --dry-run, "false" for live pull.
    Explicit host directories must already exist; they are not auto-created.
    Linked paths, root aliases, parent traversal and Docker CSV delimiters are
    rejected without reading any file contents. Invalid selections raise ValueError.
    Without --local-dir, uploads/results retain the repository convention.
    """
    if direction not in ("push", "pull"):
        raise ValueError("Transfer direction must be push or pull")
    arguments = list(arguments)
    environment = dict(os.environ if environment is None else environment)
    environment.pop("ISAAC_TRANSFER_LOCAL_DIR", None)
    environment.pop("ISAAC_TRANSFER_READ_ONLY", None)
    local_dir = None
    dry_run = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            break
        if argument == "--local-dir" or argument.startswith("--local-dir="):
            if local_dir is not None:
                raise ValueError("Specify --local-dir only once")
            if argument == "--local-dir":
                index += 1
                if index >= len(arguments) or arguments[index].startswith("--"):
                    raise ValueError("--local-dir requires an existing host directory")
                local_dir = arguments[index]
                arguments[index] = "/run/isaac-transfer-local"
            else:
                local_dir = argument.split("=", 1)[1]
                arguments[index] = "--local-dir=/run/isaac-transfer-local"
            if not local_dir:
                raise ValueError("--local-dir requires an existing host directory")
        elif argument in ("--exclude", "--remote-dir", "--instance-role"):
            # Click consumes the next token as a value, even if it resembles an
            # option. Such values must not activate our host transport flags.
            index += 1
        elif argument == "--dry-run":
            dry_run = True
        index += 1
    if local_dir is not None:
        selected = Path(local_dir).absolute()
        # Docker --mount uses CSV syntax. Reject ambiguous delimiters rather than
        # reinterpret a different bind source; do not read directory contents.
        if (any(c in str(selected) for c in '\x00\r\n,"') or ".." in selected.parts
                or any(part.is_symlink() for part in (selected, *selected.parents))
                or not selected.is_dir() or selected.resolve() == Path("/")):
            raise ValueError("--local-dir requires an existing non-root, non-symlinked host directory with a literal safe path; it is not auto-created")
        environment["ISAAC_TRANSFER_LOCAL_DIR"] = str(selected)
        environment["ISAAC_TRANSFER_READ_ONLY"] = str(direction == "push" or dry_run).lower()
    command = "./upload" if direction == "push" else "./download"
    # The run wrapper deliberately takes one shell command string, not an argv.
    return [str(Path(repo_root) / "run"), shlex.join([command, *arguments])], environment


def transfer_command(direction):
    """Shared public upload/download options; every invocation has one direction."""
    from src.python.config import c as config
    from src.python.terraform_runner import TerraformRunnerError

    @click.command()
    @click.argument("deployment_name")
    @click.argument("legacy_instance_role", required=False,
                    type=click.Choice(["all", "isaac_workstation"]))
    @click.option("--instance-role", default="all",
                  type=click.Choice(["all", "isaac_workstation"]))
    @click.option("--debug/--no-debug", default=False)
    @click.option("--local-dir", type=click.Path(file_okay=False),
                  help="Selected local directory (overrides uploads/results). Explicit host directories must already exist; they are not auto-created.")
    @click.option("--remote-dir", help="Selected remote directory; no sudo is used.")
    @click.option("--delete/--no-delete", default=False, show_default=True,
                  help="Opt in to deleting destination files absent at source. Preview first.")
    @click.option("--dry-run", is_flag=True, help="Preview changes/deletions without changing data.")
    @click.option("--exclude", multiple=True, help="Additional rsync exclusion pattern; repeatable.")
    def main(deployment_name, legacy_instance_role, instance_role, debug,
             local_dir, remote_dir, delete, dry_run, exclude):
        """Copy selected directory contents. Source wins, including overwrites.

        No bidirectional conflict merge. State, credentials and common secret
        stores are excluded. SSH trusts first use (accept-new), refusing changed
        host keys; keep the deployment's known_hosts file for subsequent use.
        """
        try:
            role = legacy_instance_role or instance_role
            roles = ["isaac_workstation"] if role == "all" else [role]
            for selected_role in roles:
                endpoint = load_endpoint(deployment_name, selected_role, debug=debug)
                selected_local = local_dir or (
                    config["uploads_dir"] if direction == "push" else
                    str(Path(config["results_dir"]) / deployment_name / selected_role))
                default_remote = config[
                    "default_remote_uploads_dir" if direction == "push" else "default_remote_results_dir"]
                if endpoint.user != config["default_ssh_user"]:
                    # OS Login's home belongs to its real POSIX user, not ubuntu.
                    default_remote = "uploads" if direction == "push" else "results"
                selected_remote = remote_dir or default_remote
                if not dry_run and (direction == "pull" or local_dir is None):
                    Path(selected_local).mkdir(parents=True, exist_ok=True)
                click.echo("Source wins: changed files may overwrite destination files even without --delete.")
                transfer_directory(endpoint, direction, selected_local, selected_remote,
                                   delete=delete, dry_run=dry_run, exclude=exclude)
                click.echo("Preview complete." if dry_run else "Transfer complete.")
        except subprocess.CalledProcessError as exc:
            click.echo(f"Error: Transfer failed (exit {exc.returncode}); no success was recorded.", err=True)
            raise click.exceptions.Exit(exc.returncode if exc.returncode > 0 else 128 - exc.returncode) from None
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            click.echo("Error: Transfer timed out or was interrupted; rerun to resume partial files.", err=True)
            raise click.exceptions.Exit(130 if isinstance(exc, KeyboardInterrupt) else 124) from None
        except (ValueError, OSError, TerraformRunnerError) as exc:
            raise click.ClickException(str(exc)) from None
    return main


def transfer_directory(endpoint, direction, local_dir, remote_dir, *, delete=False,
                       dry_run=False, capture_output=False, exclude=(), timeout=3600):
    """Copy directory contents; deletion is opt-in and dry-run never writes data.

    ``endpoint=None`` selects local rsync, useful for disposable local fixtures.
    ``pull`` makes remote_dir the source; ``push`` makes local_dir the source.
    Use an absolute remote path or a path relative to the SSH user's home. No
    arbitrary shell expressions are expanded. Dry-run does not create working
    directories or modify file contents; it can record first-use SSH trust.
    Excluded destination files remain protected even with delete=True. A missing
    pull source is an rsync error, never an instruction to empty the local copy.
    """
    if direction not in ("push", "pull"):
        raise ValueError("Transfer direction must be push or pull")
    if (not str(local_dir) or not isinstance(remote_dir, str) or not remote_dir
            or any(c in str(local_dir) + remote_dir for c in "\x00\r\n")
            or Path(local_dir).resolve() == Path("/")
            or posixpath.normpath(remote_dir).strip("/") == ""
            or (endpoint is None and Path(remote_dir).resolve() == Path("/"))):
        raise ValueError("Select a non-root directory with a literal, nonempty path")
    if endpoint and (".." in remote_dir.split("/") or posixpath.normpath(remote_dir) == "."):
        # The remote filesystem cannot be resolved locally; parent traversal can
        # escape through a symlink even when lexical normalization looks safe.
        raise ValueError("Select a remote child directory without parent traversal")
    local = str(Path(local_dir).absolute())
    remote = (f"{endpoint.user}@{endpoint.host}:{remote_dir}" if endpoint
              else str(Path(remote_dir).absolute()))
    source, destination = (local, remote) if direction == "push" else (remote, local)
    argv = ["rsync", "-avz", "--itemize-changes", "--protect-args",
            "--partial-dir=.rsync-partial", "--timeout=60"]
    if endpoint:
        # A failed trust-file write must not turn every connection into first use.
        # Dry-run changes no working data, but may record SSH trust metadata.
        endpoint.__post_init__()
        identity = Path(endpoint.identity_file)
        if (any(part.is_symlink() for part in (identity, *identity.parents))
                or not identity.is_file()):
            raise ValueError("SSH identity must be an existing regular non-symlinked file")
        fd = os.open(endpoint.known_hosts_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        argv.extend(["-e", shlex.join(endpoint.ssh_argv())])
        if direction == "push" and not dry_run:
            argv.extend(["--rsync-path", f"mkdir -p -- {shlex.quote(remote_dir)} && exec rsync"])
    for pattern in (*DEFAULT_EXCLUDES, *exclude):
        argv.extend(["--exclude", pattern])
    if delete:
        argv.append("--delete-after")
    if dry_run:
        argv.append("--dry-run")
    return subprocess.run(argv + ["--", source.rstrip("/") + "/", destination],
                          check=True, text=True, capture_output=capture_output, timeout=timeout)
