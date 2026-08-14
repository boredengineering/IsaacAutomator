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
import click

from src.python.utils import colorize_error, colorize_info, shell_command


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
