#!/usr/bin/env python3
"""
Remote Non-Invasive Observation & Diagnostics for Isaac Workstations.
Executes read-only probes over secure SSH transport without mutating target state.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.python.config import c as config
from src.python.file_transfer import endpoint_from_config
from src.python.utils import (
    approved_deployment_path,
    read_meta,
    read_tf_output,
)

REMOTE_PROBE_SCRIPT = r"""
import json
import os
import subprocess

def sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return p.stdout.strip()
    except Exception:
        return ""

# Read state ledger if present
state_ledger = None
ledger_path = os.path.expanduser("~/.isaac-state.json")
if os.path.exists(ledger_path):
    try:
        with open(ledger_path) as f:
            state_ledger = json.load(f)
    except Exception:
        pass

# Check GPU
gpu_info = sh("nvidia-smi --query-gpu=name,driver_version,memory.total,temperature.gpu --format=csv,noheader")

# Check Services
kasmvnc_status = sh("systemctl is-active kasmvnc.service 2>/dev/null || echo inactive")
docker_status = sh("systemctl is-active docker.service 2>/dev/null || echo inactive")
xorg_status = sh("systemctl is-active display-manager.service 2>/dev/null || echo inactive")

# Check Ports
ports = sh("ss -tlpn 2>/dev/null | awk 'NR>1 {print $4}' | sort -u").splitlines()

# Check Isaac Sim
sim_path = os.path.expanduser("~/IsaacSim")
has_sim = os.path.exists(sim_path)
sim_real = os.path.realpath(sim_path) if has_sim else ""

# Check Isaac Lab
has_lab_env = os.path.exists(os.path.expanduser("~/miniconda3/envs/isaaclab"))
has_lab_shim = bool(sh("which isaaclab-env"))

# Check Repositories & Branches
repos = {}
gh_dir = os.path.expanduser("~/Documents/GitHub/BoredEngineer")
if os.path.exists(gh_dir):
    for entry in os.listdir(gh_dir):
        repo_dir = os.path.join(gh_dir, entry)
        if os.path.isdir(os.path.join(repo_dir, ".git")):
            branch = sh(f"git -C '{repo_dir}' branch --show-current 2>/dev/null")
            commit = sh(f"git -C '{repo_dir}' rev-parse --short HEAD 2>/dev/null")
            repos[entry] = {
                "branch": branch or "detached",
                "commit": commit
            }

report = {
    "hostname": sh("hostname"),
    "uptime": sh("uptime -p"),
    "os": sh("grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"'"),
    "kernel": sh("uname -r"),
    "gpu": gpu_info,
    "services": {
        "kasmvnc": kasmvnc_status,
        "docker": docker_status,
        "display_manager": xorg_status
    },
    "listening_ports": [p for p in ports if any(port in p for port in ("22", "6080", "8444", "4000", "5555", "5561"))],
    "isaac_sim": {
        "installed": has_sim,
        "path": sim_real,
        "version": state_ledger.get("components", {}).get("isaacsim", {}).get("version", "6.0.1") if state_ledger else "6.0.1"
    },
    "isaac_lab": {
        "conda_environment": has_lab_env,
        "shim_present": has_lab_shim,
        "framework_version": "v3"
    },
    "repositories": repos,
    "state_ledger": state_ledger
}

print(json.dumps(report, indent=2))
"""


def probe_cloud_workstation(deployment_name: str, instance_role: str = "isaac_workstation", timeout: int = 30) -> dict[str, Any]:
    """Execute read-only remote diagnostics on target cloud workstation."""
    outputs = {key: read_tf_output(deployment_name, key, verbose=False)
               for key in ("cloud", f"{instance_role}_vm_id", f"{instance_role}_ip")}
    
    endpoint = endpoint_from_config(
        read_meta(deployment_name, verbose=False), outputs,
        approved_deployment_path(deployment_name), role=instance_role,
        default_user=config["default_ssh_user"],
    )
    if endpoint.host in ("NA", "", None):
        raise RuntimeError(f"No active VM endpoint found for deployment '{deployment_name}'")

    cmd = [*endpoint.ssh_argv(), f"{endpoint.user}@{endpoint.host}", "python3", "-"]
    proc = subprocess.run(
        cmd,
        input=REMOTE_PROBE_SCRIPT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Remote diagnostic probe failed (exit {proc.returncode}): {proc.stderr.strip()}")

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Malformed diagnostic JSON from remote workstation: {proc.stdout[:200]}") from exc


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.python.remote_diagnostics <DEPLOYMENT_NAME>", file=sys.stderr)
        sys.exit(1)
    
    deployment_name = sys.argv[1]
    try:
        data = probe_cloud_workstation(deployment_name)
        print(json.dumps(data, indent=2))
    except Exception as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
