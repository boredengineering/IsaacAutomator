"""Unified workstation connection resolver and IAP tunnel management.

Provides a single authoritative backend contract for resolving remote endpoints,
IAP TCP tunnels, security posture, and protocol capabilities across CLI and TUI.
"""
from dataclasses import dataclass, field
import ipaddress
import re
import socket
from pathlib import Path
from typing import Any

from src.python.config import c as config
from src.python.gcp import gcp_instance_name


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a local TCP port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.bind((host, port))
            return False
        except (OSError, socket.error):
            return True


def find_available_local_port(start_port: int, max_attempts: int = 50) -> int:
    """Find the next available loopback port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(port):
            return port
    return start_port


def build_iap_tunnel_command(instance: str, remote_port: int, local_port: int,
                             project: str, zone: str) -> list[str]:
    """Construct safe argv for starting a gcloud compute IAP TCP tunnel."""
    return [
        "gcloud", "compute", "start-iap-tunnel", instance, str(remote_port),
        f"--local-host-port=127.0.0.1:{local_port}",
        f"--project={project}", f"--zone={zone}", "--quiet"
    ]


@dataclass(frozen=True)
class ProtocolEndpoint:
    """Authoritative endpoint specification for a single remote access protocol."""
    protocol: str
    supported: bool
    target_endpoint: str
    desc: str
    security_lock: str
    requires_tunnel: bool
    remote_port: int
    local_port: int
    tunnel_command: list[str] = field(default_factory=list)
    warning: str | None = None


@dataclass(frozen=True)
class WorkstationConnectionInfo:
    """Resolved connection and security metadata for an existing workstation."""
    name: str
    cloud: str
    instance_role: str = "isaac_workstation"
    instance_name: str = ""
    public_ip: str = ""
    private_ip: str = ""
    iap_enabled: bool = False
    oslogin_enabled: bool = False
    project: str = ""
    zone: str = ""
    security_profile: str = "simple"
    security_posture_label: str = ""

    def get_display_ip(self) -> str:
        """Return human-readable IP address or IAP status badge for tables."""
        if self.iap_enabled:
            if self.private_ip and self.private_ip not in ("NA", "None", ""):
                return f"IAP ({self.private_ip})"
            return "IAP (Private)"
        if self.public_ip and self.public_ip not in ("NA", "None", "", "IAP_ONLY"):
            return self.public_ip
        if self.private_ip and self.private_ip not in ("NA", "None", ""):
            return self.private_ip
        return "N/A"

    def get_protocol_endpoint(self, proto: str, local_port: int | None = None) -> ProtocolEndpoint:
        """Generate structured endpoint information for a given protocol."""
        proto = proto.lower()
        sec_lock = self.security_posture_label or (
            "Cloud IAP (Identity-Aware Proxy, Zero Public Ingress)"
            if self.iap_enabled
            else "Strict /32 Caller IP Filter"
        )

        host = self.public_ip or self.private_ip or "127.0.0.1"

        if proto == "novnc":
            remote_port = 6080
            lp = local_port or remote_port
            if self.iap_enabled:
                tunnel_cmd = build_iap_tunnel_command(
                    self.instance_name, remote_port, lp, self.project, self.zone
                ) if self.instance_name and self.project and self.zone else []
                return ProtocolEndpoint(
                    protocol="novnc",
                    supported=True,
                    target_endpoint=f"http://127.0.0.1:{lp}/vnc.html?resize=scale",
                    desc="Zero-install HTML5 browser client via Cloud IAP TCP forwarding tunnel.",
                    security_lock=sec_lock,
                    requires_tunnel=True,
                    remote_port=remote_port,
                    local_port=lp,
                    tunnel_command=tunnel_cmd,
                )
            else:
                return ProtocolEndpoint(
                    protocol="novnc",
                    supported=bool(self.public_ip and self.public_ip not in ("NA", "None", "", "IAP_ONLY")),
                    target_endpoint=f"http://{host}:6080/vnc.html?autoconnect=true&resize=remote",
                    desc="Zero-install HTML5 browser client. Ideal for 2D UI, terminal, and file downloads.",
                    security_lock=sec_lock,
                    requires_tunnel=False,
                    remote_port=remote_port,
                    local_port=remote_port,
                )

        elif proto == "nomachine":
            remote_port = 4000
            lp = local_port or remote_port
            if self.iap_enabled:
                tunnel_cmd = build_iap_tunnel_command(
                    self.instance_name, remote_port, lp, self.project, self.zone
                ) if self.instance_name and self.project and self.zone else []
                return ProtocolEndpoint(
                    protocol="nomachine",
                    supported=True,
                    target_endpoint=f"nx://127.0.0.1:{lp}",
                    desc="Hardware-accelerated H.264 stream via Cloud IAP TCP forwarding tunnel.",
                    security_lock=sec_lock,
                    requires_tunnel=True,
                    remote_port=remote_port,
                    local_port=lp,
                    tunnel_command=tunnel_cmd,
                )
            else:
                return ProtocolEndpoint(
                    protocol="nomachine",
                    supported=bool(self.public_ip and self.public_ip not in ("NA", "None", "", "IAP_ONLY")),
                    target_endpoint=f"nx://{host}:4000",
                    desc="Hardware-accelerated H.264 stream. Recommended for live 60 FPS Isaac Sim 3D Viewport.",
                    security_lock=sec_lock,
                    requires_tunnel=False,
                    remote_port=remote_port,
                    local_port=remote_port,
                )

        elif proto == "ssh":
            remote_port = 22
            lp = local_port or remote_port
            if self.iap_enabled:
                tunnel_cmd = build_iap_tunnel_command(
                    self.instance_name, remote_port, lp, self.project, self.zone
                ) if self.instance_name and self.project and self.zone else []
                return ProtocolEndpoint(
                    protocol="ssh",
                    supported=True,
                    target_endpoint=f"./ssh {self.name}",
                    desc="Encrypted shell tunnel through Cloud IAM and IAP.",
                    security_lock=sec_lock,
                    requires_tunnel=True,
                    remote_port=remote_port,
                    local_port=lp,
                    tunnel_command=tunnel_cmd,
                )
            else:
                return ProtocolEndpoint(
                    protocol="ssh",
                    supported=bool(self.public_ip and self.public_ip not in ("NA", "None", "", "IAP_ONLY")),
                    target_endpoint=f"ssh://ubuntu@{host}:22",
                    desc="Interactive direct shell without opening public SSH ports.",
                    security_lock=sec_lock,
                    requires_tunnel=False,
                    remote_port=remote_port,
                    local_port=remote_port,
                )

        elif proto == "sunshine":
            remote_port = 47990
            lp = local_port or remote_port
            if self.iap_enabled:
                return ProtocolEndpoint(
                    protocol="sunshine",
                    supported=False,
                    target_endpoint="UNAVAILABLE VIA IAP",
                    desc="Ultra-low latency NVENC streaming (Moonlight client).",
                    security_lock=sec_lock,
                    requires_tunnel=False,
                    remote_port=remote_port,
                    local_port=lp,
                    warning="Sunshine/Moonlight streaming requires UDP which is not supported by Cloud IAP TCP forwarding. Use noVNC (2D) or NoMachine (3D) for private IAP workstations.",
                )
            else:
                return ProtocolEndpoint(
                    protocol="sunshine",
                    supported=bool(self.public_ip and self.public_ip not in ("NA", "None", "", "IAP_ONLY")),
                    target_endpoint=f"https://{host}:47990",
                    desc="Ultra-low latency NVENC streaming (sub-15ms) for direct robot teleoperation.",
                    security_lock=sec_lock,
                    requires_tunnel=False,
                    remote_port=remote_port,
                    local_port=remote_port,
                )

        raise ValueError(f"Unknown remote protocol: {proto}")


def resolve_workstation_connection(deployment_name: str, *,
                                   state_dir: Path | str | None = None,
                                   role: str = "isaac_workstation",
                                   verbose: bool = False) -> WorkstationConnectionInfo:
    """Resolve complete, verified connection parameters for an existing deployment."""
    from src.python import utils
    from src.python.backend_runtime import load_backend_record, record_runner

    directory = utils.approved_deployment_path(deployment_name, state_dir=state_dir)
    metadata = utils.read_meta(deployment_name, verbose=verbose)
    params = metadata.get("params", {})
    command_str = metadata.get("command", "")

    record = load_backend_record(deployment_name, state_root=directory.parent)
    outputs: dict[str, Any] = {}
    if record is not None:
        with record_runner(record, state_root=directory.parent, read_only=True) as runner:
            runner.init()
            raw_outputs = runner.output()
            outputs = {k: v.get("value") if isinstance(v, dict) else v for k, v in raw_outputs.items()}
    else:
        for key in ("cloud", f"{role}_ip", f"{role}_private_ip", f"{role}_vm_id",
                    "iap_enabled", "oslogin_enabled"):
            val = utils.read_tf_output(deployment_name, key, verbose=verbose, state_dir=directory.parent)
            if val != "":
                outputs[key] = val

    # Resolve Cloud
    cloud = outputs.get("cloud", params.get("cloud", "")).lower()
    if not cloud:
        if "project" in params or "deploy-gcp" in command_str:
            cloud = "gcp"
        elif "aws_access_key_id" in params or "deploy-aws" in command_str:
            cloud = "aws"
        elif "azure_subscription_id" in params or "deploy-azure" in command_str:
            cloud = "azure"
        elif "deploy-alicloud" in command_str:
            cloud = "alicloud"
        else:
            cloud = "unknown"

    # Resolve IAP & OS Login
    raw_iap = outputs.get("iap_enabled", params.get("enable_iap_only", params.get("iap", False)))
    iap_enabled = str(raw_iap).lower() == "true" and cloud == "gcp"

    raw_oslogin = outputs.get("oslogin_enabled", params.get("enable_oslogin", params.get("oslogin", False)))
    oslogin_enabled = str(raw_oslogin).lower() == "true" and cloud == "gcp"

    # Resolve IP addresses
    public_ip = str(outputs.get(f"{role}_ip", "")).strip()
    if public_ip in ("NA", "None"):
        public_ip = ""
    private_ip = str(outputs.get(f"{role}_private_ip", "")).strip()
    if private_ip in ("NA", "None"):
        private_ip = ""

    # Resolve GCP Instance, Project, Zone
    vm_id = str(outputs.get(f"{role}_vm_id", "")).strip()
    project = str(params.get("project", "")).strip()
    zone = str(params.get("zone", "")).strip()

    instance_name = ""
    if cloud == "gcp":
        if vm_id and vm_id != "NA":
            match = re.search(r"(?:^|/)projects/([^/]+)/zones/([^/]+)/instances/([^/]+)$", vm_id)
            if match:
                parsed_proj, parsed_zone, parsed_inst = match.groups()
                project = project or parsed_proj
                zone = zone or parsed_zone
                instance_name = parsed_inst
            else:
                try:
                    instance_name = gcp_instance_name(vm_id, project=project, zone=zone)
                except Exception:
                    instance_name = vm_id

    # Security Profile & Posture
    profile = str(params.get("security_profile", params.get("profile", "simple"))).lower()
    if iap_enabled:
        posture = "Cloud IAP (Identity-Aware Proxy, Zero Public Ingress)"
    elif profile == "enterprise":
        posture = "Enterprise Zero-Trust (KMS CMEK, Shielded VM)"
    elif profile == "team":
        posture = "Team Workstation (Shared Ingress, Multi-User)"
    else:
        posture = "Strict /32 Caller IP Filter (Simple Mode)"

    return WorkstationConnectionInfo(
        name=deployment_name,
        cloud=cloud,
        instance_role=role,
        instance_name=instance_name,
        public_ip=public_ip,
        private_ip=private_ip,
        iap_enabled=iap_enabled,
        oslogin_enabled=oslogin_enabled,
        project=project,
        zone=zone,
        security_profile=profile,
        security_posture_label=posture,
    )
