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
Utils for GCP
"""

from datetime import datetime, timezone
import re
import click

from src.python.utils import colorize_error, colorize_info, shell_command


def gcp_instance_name(vm_id, *, project, zone):
    """Validate an authoritative VM ID against explicit saved workload scope."""
    project_pattern = r'[a-z][a-z0-9-]{4,28}[a-z0-9]'
    zone_pattern = r'[a-z][a-z0-9-]*[0-9]-[a-z]'
    name_pattern = r'[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if (not isinstance(project, str) or not re.fullmatch(project_pattern, project)
            or not isinstance(zone, str) or not re.fullmatch(zone_pattern, zone)):
        raise click.ClickException('Saved GCP project and zone are required and must be valid; ambient defaults are not used.')
    if isinstance(vm_id, str):
        match = re.fullmatch(
            rf'(?:https://(?:www|compute)\.googleapis\.com/compute/v1/)?'
            rf'projects/({project_pattern})/zones/({zone_pattern})/instances/({name_pattern})', vm_id)
        if match:
            if match.group(1) != project or match.group(2) != zone:
                raise click.ClickException('Authoritative GCP VM ID disagrees with saved project and zone.')
            return match.group(3)
        if re.fullmatch(name_pattern, vm_id):
            return vm_id
    raise click.ClickException('Authoritative GCP VM ID is missing or invalid; instance names are never guessed.')


def _build_gcloud_args(zone: str = None, project: str = None) -> str:
    args = []
    if zone:
        args.append(f"--zone={zone}")
    if project:
        args.append(f"--project={project}")
    return " ".join(args)


def gcp_stop_instance(instance_name: str, zone: str = None, project: str = None, verbose: bool = False):
    """
    Stop GCP Compute Engine instance
    """
    extra_args = _build_gcloud_args(zone, project)
    cmd = f"gcloud compute instances stop {instance_name} {extra_args} --quiet"
    shell_command(
        cmd,
        verbose=verbose,
        exit_on_error=True,
        capture_output=False,
    )


def gcp_start_instance(instance_name: str, zone: str = None, project: str = None, verbose: bool = False):
    """
    Start GCP Compute Engine instance
    """
    extra_args = _build_gcloud_args(zone, project)
    cmd = f"gcloud compute instances start {instance_name} {extra_args} --quiet"
    shell_command(
        cmd,
        verbose=verbose,
        exit_on_error=True,
        capture_output=False,
    )


def gcp_get_instance_status(instance_name: str, zone: str = None, project: str = None, verbose: bool = False) -> str:
    """
    Get GCP Compute Engine instance status (e.g. RUNNING, TERMINATED, PROVISIONING, STAGING)
    """
    extra_args = _build_gcloud_args(zone, project)
    cmd = f"gcloud compute instances describe {instance_name} {extra_args} --format='value(status)'"
    res = shell_command(
        cmd,
        verbose=verbose,
        exit_on_error=False,
        capture_output=True,
    )
    if res.returncode == 0 and res.stdout:
        return res.stdout.decode().strip()
    return ""


def gcp_get_instance_last_start(instance_name: str, zone: str = None, project: str = None, verbose: bool = False) -> str:
    """
    Get GCP Compute Engine instance lastStartTimestamp in ISO 8601 format
    """
    extra_args = _build_gcloud_args(zone, project)
    cmd = f"gcloud compute instances describe {instance_name} {extra_args} --format='value(lastStartTimestamp)'"
    res = shell_command(
        cmd,
        verbose=verbose,
        exit_on_error=False,
        capture_output=True,
    )
    if res.returncode == 0 and res.stdout:
        return res.stdout.decode().strip()
    return ""


def parse_iso_timestamp(timestamp_iso: str) -> datetime:
    """
    Safely parse ISO 8601 timestamps (including trailing 'Z') into datetime with timezone.
    """
    normalized = timestamp_iso.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def gcp_get_instance_uptime_seconds(instance_name: str, zone: str = None, project: str = None, verbose: bool = False) -> int:
    """
    Compute uptime in seconds from lastStartTimestamp. Returns -1 if unable to retrieve.
    """
    ts_str = gcp_get_instance_last_start(instance_name, zone=zone, project=project, verbose=verbose)
    if not ts_str:
        return -1

    try:
        start_dt = parse_iso_timestamp(ts_str)
        now_dt = datetime.now(timezone.utc)
        diff = now_dt - start_dt
        return max(0, int(diff.total_seconds()))
    except Exception as e:
        if verbose:
            click.echo(colorize_error(f"Failed to parse timestamp '{ts_str}': {e}"))
        return -1


def gcp_ssh_iap(instance_name: str, zone: str = None, project: str = None, os_login: bool = True, extra_ssh_args: str = ""):
    """
    Establish an SSH connection to a private Compute Engine instance through Cloud IAP.
    """
    extra_args = _build_gcloud_args(zone, project)
    cmd = f"gcloud compute ssh {instance_name} --tunnel-through-iap {extra_args}"
    if extra_ssh_args:
        cmd += f" -- {extra_ssh_args}"
    return shell_command(cmd, verbose=True, exit_on_error=True, capture_output=False)


def gcp_start_iap_tunnel(instance_name: str, remote_port: int, local_port: int, zone: str = None, project: str = None):
    """
    Start an Identity-Aware Proxy (IAP) TCP forwarding tunnel in the background.
    """
    extra_args = _build_gcloud_args(zone, project)
    cmd = f"gcloud compute start-iap-tunnel {instance_name} {remote_port} --local-host-port=localhost:{local_port} {extra_args}"
    return shell_command(cmd, verbose=True, exit_on_error=False, capture_output=False)
