# region copyright
# Copyright 2023-2026 NVIDIA Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# endregion


"""
CLI Utils
"""

import json
import os
import re
import subprocess
from glob import glob
from pathlib import Path

import click

from src.python.config import c as config


def colorize_prompt(text):
    return click.style(text, fg="bright_cyan", italic=True)


def colorize_error(text):
    return click.style(text, fg="bright_red", italic=True)


def colorize_info(text):
    return click.style(text, fg="bright_magenta", italic=True)


def colorize_result(text):
    return click.style(text, fg="bright_green", italic=True)


def shell_command(
    command, verbose=False, cwd=None, exit_on_error=True, capture_output=False
):
    """
    Execute shell command, print it if debug is enabled
    """

    if verbose:
        if cwd is not None:
            click.echo(colorize_info(f"* Running `(cd {cwd} && {command})`..."))
        else:
            click.echo(colorize_info(f"* Running `{command}`..."))

    res = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=capture_output,
    )

    if res.returncode == 0:
        if verbose and res.stdout is not None:
            click.echo(res.stdout.decode())

    elif exit_on_error:
        if res.stderr is not None:
            click.echo(
                colorize_error(f"Error: {res.stderr.decode()}"),
                err=True,
            )
        exit(1)

    return res


def deployments():
    """List existing deployments by name"""
    state_dir = config["state_dir"]
    deployments = sorted(
        [
            os.path.basename(os.path.dirname(d))
            for d in glob(os.path.join(state_dir, "*/"))
        ]
    )
    return deployments


def read_meta(deployment_name: str, verbose: bool = False):
    """
    Read metadata from json file
    """

    meta_file = f"{config['state_dir']}/{deployment_name}/meta.json"

    if os.path.isfile(meta_file):
        data = json.loads(Path(meta_file).read_text())
        if verbose:
            click.echo(colorize_info(f"* Meta info loaded from '{meta_file}'"))
        return data

    raise Exception(f"Meta file '{meta_file}' not found")


def _require_no_symlink_path(path):
    """Reject symlinks before canonicalization, including configured ancestors."""
    try:
        path = Path(path).absolute()
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError
    except (OSError, ValueError, RuntimeError):
        raise click.ClickException("Deployment state path is not trusted for legacy operations.") from None


def approved_deployment_path(deployment_name, *, state_dir=None):
    """Return one existing deployment inside a non-symlinked approved root."""
    try:
        if not isinstance(deployment_name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", deployment_name
        ):
            raise ValueError
        root = Path(state_dir if state_dir is not None else config["state_dir"])
        directory = root / deployment_name
        _require_no_symlink_path(directory)
        root = root.resolve(strict=True)
        directory = directory.resolve(strict=True)
        if directory.parent != root or not directory.is_dir():
            raise ValueError
        return directory
    except (OSError, ValueError, RuntimeError):
        raise click.ClickException("Deployment state path is unavailable or outside the approved root.") from None


def read_tf_output(deployment_name, output, verbose=False, *, state_dir=None):
    """
    Read a single output from the deployment's explicitly saved backend.

    Legacy local state is parsed instead of shelling out to Terraform. This is
    both faster and far more robust: it needs no initialized backend/.terraform and
    never executes a provider plugin - which matters on macOS, where Docker Desktop's
    bind mount cannot reliably exec the provider binaries and `terraform output -state=`
    also conflicts with a configured backend. Returns "" for an absent optional
    output, but refuses missing/malformed state. Explicit GCS records use native
    Terraform output in a backend-only context, with no stale local fallback.
    Older protected claim/migration attachments retain their supervised gates.
    """

    directory = approved_deployment_path(deployment_name, state_dir=state_dir)
    from src.python.backend_runtime import load_backend_record, record_runner
    from src.python.terraform_runner import TerraformRunnerError
    try:
        record = load_backend_record(deployment_name, state_root=directory.parent)
        if record is not None:
            with record_runner(record, state_root=directory.parent, read_only=True) as runner:
                runner.init()
                value = runner.output().get(output, {}).get('value')
            return '' if value is None else str(value)
    except TerraformRunnerError as exc:
        raise click.ClickException(str(exc)) from None
    tfstate_file = directory / ".tfstate"
    require_legacy_local_backend(directory)
    state = read_local_tfstate(tfstate_file)
    entry = state["outputs"].get(output, {})
    value = entry.get("value")
    return "" if value is None else str(value)


def _legacy_metadata_is_local(params):
    """Inspect only known controller blocks, never arbitrary workload fields."""
    from src.python.terraform_backend import BackendSpec

    if not isinstance(params, dict):
        return False
    if (params.get("state_bucket") or params.get("backend_config")
            or params.get("state_backend") not in (None, "local")):
        return False
    if "terraform_state" in params:
        try:
            if not isinstance(params["terraform_state"], dict):
                return False
            if BackendSpec.from_dict(params["terraform_state"], cloud="aws").backend != "local":
                return False
        except ValueError:
            return False
    for key in ("profile_spec", "raw"):
        if key in params and not _legacy_metadata_is_local(params[key]):
            return False
    if "security" in params:
        security = params["security"]
        if not isinstance(security, dict):
            return False
        if "storage" in security and not _legacy_metadata_is_local(security["storage"]):
            return False
    return True


def require_legacy_local_backend(deployment_dir):
    """Never interpret a remote deployment's local snapshot as live state."""
    directory = Path(deployment_dir)
    _require_no_symlink_path(directory)
    for marker in ("migration.json", "relocation.json"):
        try:
            (directory / marker).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise click.ClickException("Cannot verify migration status; refusing legacy local operations.") from None
        raise click.ClickException(
            "A migration or retirement marker is present. Legacy local operations are frozen; "
            "review the authoritative migration record. No redirect or retry is automatic."
        )
    if (directory / ".tfstate").is_symlink():
        raise click.ClickException("Symlinked deployment state is not trusted for legacy operations.")
    if (directory / "backend.json").exists() or (directory / "backend.json").is_symlink():
        raise click.ClickException(
            "A saved backend descriptor is present. Legacy local operations are "
            "disabled until backend-aware lifecycle support is available."
        )
    meta_path = directory / "meta.json"
    if meta_path.is_symlink():
        raise click.ClickException("Cannot verify backend metadata; refusing local fallback.")
    if not meta_path.exists():
        return
    if not meta_path.is_file():
        raise click.ClickException("Cannot verify backend metadata; refusing local fallback.")
    try:
        meta = json.loads(meta_path.read_text())
        if not isinstance(meta, dict):
            raise ValueError
        for section in ("params", "input_params"):
            params = meta.get(section, {})
            if not _legacy_metadata_is_local(params):
                raise click.ClickException(
                    "Metadata records remote or ambiguous backend intent. Local "
                    "snapshots cannot be trusted; verify the authoritative backend."
                )
    except (OSError, ValueError):
        raise click.ClickException("Cannot verify backend metadata; refusing local fallback.") from None


def read_local_tfstate(path, *, require_identity=False):
    """Validate legacy v4 state; lifecycle callers also require lineage/serial.

    Output-only fixtures may omit identity. Errors never expose state contents.
    """
    try:
        if Path(path).is_symlink() or not Path(path).is_file():
            raise ValueError
        state = json.loads(Path(path).read_text())
        if (
            not isinstance(state, dict)
            or type(state.get("version")) is not int
            or state.get("version") != 4
            or not isinstance(state.get("resources"), list)
            or not isinstance(state.get("outputs"), dict)
            or any(not isinstance(entry, dict) for entry in state["outputs"].values())
        ):
            raise ValueError
        for resource in state["resources"]:
            if (
                not isinstance(resource, dict)
                or resource.get("mode") not in ("managed", "data")
                or not isinstance(resource.get("instances"), list)
                or any(not isinstance(instance, dict) for instance in resource["instances"])
            ):
                raise ValueError
        if require_identity and (
            not isinstance(state.get("lineage"), str)
            or not state["lineage"].strip()
            or type(state.get("serial")) is not int
            or state["serial"] < 0
        ):
            raise ValueError
        return state
    except (OSError, ValueError):
        raise click.ClickException(
            "Local Terraform state is unavailable or malformed; recovery files "
            "are preserved. Verify the authoritative backend before continuing."
        ) from None


def format_instance_role(instance_role):
    """
    Format instance role name for user output
    """

    formatted = {
        "isaac_workstation": "Isaac Workstation",
    }

    if instance_role in formatted:
        return formatted[instance_role]

    return instance_role


def format_cloud_name(cloud_name):
    """
    Format cloud name for user output
    """

    formatted = {
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "alicloud": "Alibaba Cloud",
    }

    if cloud_name in formatted:
        return formatted[cloud_name]

    return cloud_name


def gcp_login(verbose=False):
    """
    Log into GCP
    """

    import sys
    if os.environ.get('GOOGLE_OAUTH_ACCESS_TOKEN'):
        # Presence selects the supported native auth path. Terraform validates
        # actual access; never print, persist, or probe the token through a shell.
        return
    click.echo(colorize_info("* Checking GCP login status..."), nl=False)
    try:
        res = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token', '--quiet'],
                             shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=60)
        logged_in = res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        logged_in = False

    if logged_in:
        click.echo(colorize_info(" logged in!"))

    if not logged_in:
        click.echo(colorize_info(" not logged in"))
        if not sys.stdin.isatty():
            raise click.ClickException('GCP authentication unavailable: configure ADC or GOOGLE_OAUTH_ACCESS_TOKEN before noninteractive deployment.')
        shell_command(
            "gcloud auth application-default login --no-launch-browser --disable-quota-project --verbosity none",
            verbose=verbose,
        )


def get_my_public_ip(verbose=False):
    """
    Get the current public IP address
    """
    methods = [
        "curl -sS --max-time 2 https://api.ipify.org",
        "curl -sS --max-time 2 https://icanhazip.com",
        "curl -sS --max-time 2 https://checkip.amazonaws.com",
        # DNS-based via UDP port 53 — works even when HTTP is blocked
        "dig +short +time=2 +tries=1 myip.opendns.com @208.67.222.222",
        "dig +short +time=2 +tries=1 myip.opendns.com @208.67.220.220",
    ]
    for cmd in methods:
        res = shell_command(
            cmd, verbose=verbose, capture_output=True, exit_on_error=False
        )
        if res.returncode == 0:
            ip = res.stdout.decode().strip()
            if ip:
                if verbose:
                    click.echo(colorize_info(f"* Public IP: {ip}"))
                return ip
        if verbose:
            click.echo(
                colorize_info(f"* Failed (exit {res.returncode}), trying next...")
            )

    click.echo(
        colorize_error("Warning: Could not determine public IP address, using 0.0.0.0"),
        err=True,
    )
    return "0.0.0.0"


def subnet_from_ip(ip, mask):
    """
    Get CIDR notation from IP and mask
    """
    if "24" == mask:
        return f"{ip.rsplit('.', 1)[0]}.0/24"
    elif "16" == mask:
        return f"{ip.rsplit('.', 2)[0]}.0.0/16"
    elif "8" == mask:
        return f"{ip.rsplit('.', 3)[0]}.0.0.0/8"
    else:
        raise Exception(f"Unsupported mask: {mask}")

    return f"{ip}/{mask}"
