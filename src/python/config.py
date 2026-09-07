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

import os
from typing import Any

c: dict[str, Any] = {}

# paths
_repo_root = os.environ.get(
    "APP_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
)
c["app_dir"] = _repo_root
c["state_dir"] = f"{_repo_root}/state"
c["results_dir"] = f"{_repo_root}/results"
c["uploads_dir"] = f"{_repo_root}/uploads"
c["tests_dir"] = f"{_repo_root}/src/tests"
c["ansible_dir"] = f"{_repo_root}/src/ansible"
c["terraform_dir"] = f"{_repo_root}/src/terraform"

# ensure Ansible picks up the repository ansible.cfg
os.environ["ANSIBLE_CONFIG"] = f"{_repo_root}/src/ansible/ansible.cfg"

# app image name
c["app_image_name"] = "isaac_automator"


# aws/alicloud driver
c["generic_driver_apt_package"] = "nvidia-driver-580-server"

# default ssh user
c["default_ssh_user"] = "ubuntu"

# default remote dirs
c["default_remote_uploads_dir"] = f"/home/{c['default_ssh_user']}/uploads"
c["default_remote_results_dir"] = f"/home/{c['default_ssh_user']}/results"
c["default_remote_workspace_dir"] = f"/home/{c['default_ssh_user']}/workspace"

# defaults

# --ssh-port
c["default_ssh_port"] = 22

# --from-image
c["azure_default_from_image"] = False
c["aws_default_from_image"] = False

# --isaac-workstation-instance-type
c["aws_default_isaac_workstation_instance_type"] = "g6e.2xlarge"
# str, 1-index in DeployAzureCommand.AZURE_OVKIT_INSTANCE_TYPES
c["azure_default_isaac_workstation_instance_type"] = "Standard_NV36ads_A10_v5"
c["gcp_default_isaac_workstation_instance_type"] = "g2-standard-8"
c["alicloud_default_isaac_workstation_instance_type"] = "ecs.gn7i-c16g1.4xlarge"

# --isaac-workstation-gpu-count
c["gcp_default_isaac_workstation_gpu_count"] = "auto"

# --region
c["alicloud_default_region"] = "us-east-1"

# --prefix for the created cloud resources
c["default_prefix"] = "isaacautomator"

# --isaacsim / --isaaclab / --isaaclab-arena
# "latest" -> auto-detect the latest release at deploy time (see git_ref_callback):
# highest version across the repo's tags + release/* branches, prereleases included
# (so it tracks e.g. a 3.0.0-beta line, not an older stable), branch wins on a tie.
# Can be overridden with an explicit git ref or "no" to skip.
c["default_isaaclab_git_checkpoint"] = "latest"
c["default_isaaclab_arena_git_checkpoint"] = "latest"
c["default_isaacsim_git_checkpoint"] = "latest"

# git repos used to validate / auto-detect the --isaacsim/--isaaclab/--isaaclab-arena
# refs before deploy (mirror of the ansible role defaults; keep both in sync if a repo moves)
c["isaacsim_git_repo"] = "https://github.com/isaac-sim/IsaacSim.git"
c["isaaclab_git_repo"] = "https://github.com/isaac-sim/IsaacLab.git"
c["isaaclab_arena_git_repo"] = "https://github.com/isaac-sim/IsaacLab-Arena.git"

# --profile / --security-profile
# Security tier: "simple" ($0 added cost, auto-locked /32 IP firewall),
# "team" (<$0.10/mo, remote state with locking), or
# "enterprise" (KMS CMEK, secret manager, zero-trust private access).
c["default_security_profile"] = "simple"

# --ingress-cidrs
# empty or auto value will be replaced with the current public IP
c["default_ingress_cidrs"] = "0.0.0.0/0"

# --demos
# Out-of-the-box demos to install on the workstation, exposed as double-click
# desktop shortcuts. Comma-separated list of names from c["demos"], or "no".
c["default_demos"] = "no"

# Demo registry. Each demo lists the apps it depends on (by the deploy option
# name); selecting a demo auto-enables those apps if they were left off, using
# their default git ref. Names here must match the demos role tasks.
c["demos"] = {
    "quadruped-locomotion": {
        "description": "Train an ANYmal-D quadruped to walk using RSL-RL in Isaac Lab.",
        "requires": ["isaacsim", "isaaclab"],
    },
    "humanoid-locomotion": {
        "description": "Train a Unitree G1 humanoid to walk using RSL-RL in Isaac Lab.",
        "requires": ["isaacsim", "isaaclab"],
    },
    "franka-manipulation": {
        "description": "Train a Franka arm to reach targets using RSL-RL in Isaac Lab.",
        "requires": ["isaacsim", "isaaclab"],
    },
}

# --remote-desktop
# Comma-separated list of remote desktop providers to install on the workstation,
# or "standard" (installs nomachine + novnc).
c["default_remote_desktop"] = "standard"

# Remote desktop provider registry.
c["remote_desktop_providers"] = {
    "nomachine": {
        "description": "NoMachine NX server for hardware-accelerated 3D viewport (Port 4000).",
        "standard": True,
    },
    "novnc": {
        "description": "HTML5 browser desktop via websockify + x11vnc (Port 6080).",
        "standard": True,
    },
    "kasmvnc": {
        "description": "WebRTC browser desktop with native clipboard support over HTTPS (Port 8444).",
        "standard": False,
    },
    "dcv": {
        "description": "NICE DCV enterprise GPU streaming server (Port 8443).",
        "standard": False,
    },
    "xrdp": {
        "description": "Microsoft Remote Desktop (RDP) console mirror server (Port 3389).",
        "standard": False,
    },
    "sunshine": {
        "description": "Sunshine NVENC game/3D streaming server for Moonlight clients (Port 47984-48010, 47990).",
        "standard": False,
    },
    "parsec": {
        "description": "Parsec ultra-low latency interactive streaming daemon (Port 8000-8040).",
        "standard": False,
    },
}

# ------------------------------------------------------------------------------
# Declarative Profile & Dynamic Security Discovery Engine
# ------------------------------------------------------------------------------
from pathlib import Path
import yaml

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "simple": {
        "name": "simple",
        "tier": "simple",
        "description": "Zero-cost personal developer workstation with auto /32 IP firewall lock and local state",
        "enable_cmek": False,
        "enable_iap_only": False,
        "enable_oslogin": False,
        "enable_secrets": False,
        "state_bucket": "",
        "ingress_cidrs": ["auto"],
    },
    "team": {
        "name": "team",
        "tier": "team",
        "description": "Collaborative studio profile with remote GCS state locking and shared asset access",
        "enable_cmek": False,
        "enable_iap_only": False,
        "enable_oslogin": False,
        "enable_secrets": True,
        "state_bucket": "auto",
        "ingress_cidrs": ["auto"],
    },
    "enterprise": {
        "name": "enterprise",
        "tier": "enterprise",
        "description": "Enterprise Zero-Trust workstation with private IP, IAP TCP forwarding, Cloud NAT, and KMS CMEK",
        "enable_cmek": True,
        "enable_iap_only": True,
        "enable_oslogin": True,
        "enable_secrets": True,
        "state_bucket": "auto",
        "ingress_cidrs": [],
    },
}


def get_profile_search_dirs(repo_root: str | None = None) -> list[Path]:
    """Returns candidate directories for declarative profiles."""
    root = Path(repo_root or _repo_root)
    dirs = [
        root / "configs" / "profiles",
        Path.home() / ".isaacautomator" / "profiles",
    ]
    return [d for d in dirs if d.exists()]


def list_available_profiles(repo_root: str | None = None) -> dict[str, dict[str, Any]]:
    """
    Returns a unified mapping of all available profiles:
    built-in presets ('simple', 'team', 'enterprise') plus any custom YAML files
    discovered in configs/profiles/ and ~/.isaacautomator/profiles/.
    """
    profiles: dict[str, dict[str, Any]] = dict(BUILTIN_PROFILES)

    for pdir in get_profile_search_dirs(repo_root):
        for path in sorted(pdir.glob("*.y*ml")):
            stem = path.stem
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                prof_name = data.get("profile_name", stem)
                sec = data.get("security", {})
                profiles[prof_name] = {
                    "name": prof_name,
                    "tier": sec.get("tier", "custom"),
                    "description": data.get("description", f"Custom profile ({path.name})"),
                    "path": str(path),
                    "enable_cmek": sec.get("cryptography", {}).get("encryption_type") == "kms_cmek",
                    "enable_iap_only": sec.get("network", {}).get("iap_only", False),
                    "enable_oslogin": sec.get("compute", {}).get("os_login", False),
                    "enable_secrets": sec.get("secrets", {}).get("engine") == "secret_manager",
                    "enable_flex_start": sec.get("compute", {}).get("scheduling") == "flex_start",
                    "state_bucket": sec.get("storage", {}).get("state_bucket", ""),
                    "ingress_cidrs": sec.get("network", {}).get("ingress_cidrs", ["auto"]),
                    "raw": data,
                }
            except Exception:
                pass

    return profiles


def load_profile_spec(identifier: str, repo_root: str | None = None) -> dict[str, Any] | None:
    """
    Resolves a profile identifier (name, stem, or direct file path) into normalized parameters.
    """
    if not identifier:
        return BUILTIN_PROFILES["simple"]

    clean_id = identifier.strip().lower()
    if clean_id in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[clean_id]

    # Check direct file path
    direct_path = Path(identifier)
    if direct_path.exists() and direct_path.is_file():
        try:
            with open(direct_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            sec = data.get("security", {})
            return {
                "name": data.get("profile_name", direct_path.stem),
                "tier": sec.get("tier", "custom"),
                "description": data.get("description", ""),
                "path": str(direct_path),
                "enable_cmek": sec.get("cryptography", {}).get("encryption_type") == "kms_cmek",
                "enable_iap_only": sec.get("network", {}).get("iap_only", False),
                "enable_oslogin": sec.get("compute", {}).get("os_login", False),
                "enable_secrets": sec.get("secrets", {}).get("engine") == "secret_manager",
                "enable_flex_start": sec.get("compute", {}).get("scheduling") == "flex_start",
                "state_bucket": sec.get("storage", {}).get("state_bucket", ""),
                "ingress_cidrs": sec.get("network", {}).get("ingress_cidrs", ["auto"]),
                "raw": data,
            }
        except Exception:
            return None

    # Check in search directories
    available = list_available_profiles(repo_root)
    if identifier in available:
        return available[identifier]
    if clean_id in available:
        return available[clean_id]

    return None


def save_profile_spec(name: str, spec: dict[str, Any], repo_root: str | None = None) -> Path:
    """
    Serializes a custom profile specification to configs/profiles/<name>.yaml.
    """
    root = Path(repo_root or _repo_root)
    out_dir = root / "configs" / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_name = name.strip().lower().replace(" ", "-")
    if not clean_name.endswith(".yaml"):
        clean_name += ".yaml"
    out_path = out_dir / clean_name

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(spec, f, sort_keys=False)

    return out_path
