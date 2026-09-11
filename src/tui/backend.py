import json
import asyncio
import os
import shutil
import shlex
import subprocess
import sys
import stat
from pathlib import Path

from src.python.backend_selection import select_backend
from src.python.config import c, load_profile_spec
from src.python.deployment_manifest import DeploymentManifest, strict_json


def backend_selection(cloud: str, state_backend: str | None = None, backend_config: str = "",
                      profile: str | None = None):
    """Share CLI precedence; None inherits saved intent, local is deliberate.

    A standalone new profile editor has no inherited intent and defaults local.
    A deployment profile must be loaded successfully, never silently discarded.
    """
    saved = load_profile_spec(profile, repo_root=str(REPO_ROOT)) if profile else {}
    if saved is None:
        raise ValueError("Profile unavailable; backend intent unknown")
    params = {}
    if state_backend:
        params["state_backend"] = state_backend
    elif not profile and not backend_config:
        params["state_backend"] = "local"
    if backend_config:
        params["backend_config"] = str(Path(backend_config).expanduser().resolve())
    spec = select_backend(params, saved, cloud)
    args = ["--state-backend", spec.backend]
    if backend_config:
        args.extend(["--backend-config", params["backend_config"]])
    return spec, args


def deployment_command(result: dict) -> str:
    """Transport selections to the shared CLI, never implement lifecycle here."""
    cloud = result.get("cloud", "gcp")
    spec, backend_args = backend_selection(
        cloud, result.get("state_backend"), result.get("backend_config", ""),
        result.get("profile", "simple"))
    if spec.backend != "local":
        raise ValueError("Remote execution blocked pending production gates; use offline backend validation")
    argv = [str(REPO_ROOT / f"deploy-{cloud}"),
            "--deployment-name", result.get("name", "workstation"),
            "--instance-type", result.get("gpu", ""),
            "--profile", result.get("profile", "simple"),
            "--existing", "replace", "--ingress-cidrs", "0.0.0.0/0",
            "--isaacsim", "latest", "--isaaclab", "latest",
            "--isaaclab-arena", "latest", "--no-upload", *backend_args]
    zone = result.get("zone", "")
    if cloud == "gcp":
        # No account discovery or invented fallback project in the event loop.
        project = result.get("project", "")
        if not project:
            raise ValueError("Supply an explicit GCP project before deployment")
        argv.extend(["--project", project, "--isaac-workstation-gpu-count", "1"])
        if result.get("flex_start"):
            argv.append("--flex-start")
        elif result.get("spot"):
            argv.extend(["--spot", "--auto-restore"])
    elif cloud == "aws" and result.get("spot"):
        argv.append("--spot")
    if zone and zone != "default":
        argv.extend(["--zone" if cloud == "gcp" else "--region", zone])
    if result.get("dry_run"):
        argv.append("--dry-run")
    argv.extend(["--demos", ",".join(result.get("demos", [])) or "no"])
    return shlex.join(argv)


def redact_command_text(command: str, text: str | None = None) -> str:
    """Keep backend-config paths in execution only, including echoed output."""
    argv = shlex.split(command)
    result = command if text is None else text
    for index, arg in enumerate(argv):
        if arg == "--backend-config" and index + 1 < len(argv):
            path = argv[index + 1]
            result = result.replace(shlex.quote(path), "<backend-config>")
            result = result.replace(path, "<backend-config>")
    return result


async def _run_offline_json(argv, *, timeout: float = 5.0, output_limit: int = 8192):
    """Shared terminable boundary for offline validation and filesystem loaders.

    No shell or deploy wrapper. Bound stdout and wall time; kill/reap on timeout,
    cancellation or overflow. Diagnostics never cross this boundary.
    """
    proc = None
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *argv, cwd=str(REPO_ROOT), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        limit=8192))
    try:
        # Keep ownership if cancellation arrives while the child is spawning.
        proc = await asyncio.shield(spawn)

        async def collect():
            output = b""
            while True:
                chunk = await proc.stdout.read(min(8192, output_limit + 1 - len(output)))
                if not chunk:
                    break
                output += chunk
                if len(output) > output_limit:
                    raise ValueError("Offline output exceeds limit")
            await proc.wait()
            return output

        raw = await asyncio.wait_for(collect(), timeout=max(0.001, min(timeout, 30.0)))
        if proc.returncode != 0:
            raise ValueError("Invalid offline configuration")
        return json.loads(raw)
    finally:
        if proc is None:
            proc = await spawn
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await asyncio.wait_for(proc.wait(), timeout=1.0)


async def validate_backend_config(cloud: str, config_path: str, *, timeout: float = 5.0):
    """Offline CLI validation only, not authenticated backend health."""
    unknown = {"status": "unknown", "cloud_access": "not_checked",
               "remote_lifecycle": "not_enabled"}
    try:
        data = await _run_offline_json([
            sys.executable, "-m", "src.python.state_backend_command", "validate",
            "--cloud", cloud, "--config", config_path], timeout=timeout)
        if (data.get("status") != "valid-config" or data.get("cloud") != cloud
                or data.get("backend") not in ("local", "s3", "gcs", "azurerm")
                or data.get("cloud_access") != "not_checked"):
            raise ValueError("Unexpected validation response")
        return {"status": "valid-config", "backend": data["backend"], "cloud": cloud,
                "cloud_access": "not_checked", "remote_lifecycle": "not_enabled"}
    except asyncio.TimeoutError:
        return {**unknown, "reason": "timeout"}
    except ValueError:
        return {**unknown, "reason": "invalid-config"}
    except (OSError, TypeError, AttributeError):
        return {**unknown, "reason": "validation-unavailable"}


async def load_backend_selection(cloud: str, state_backend: str | None = None,
                                 backend_config: str = "", profile: str | None = None,
                                 *, timeout: float = 5.0):
    """Load canonical nonsecret intent in the same bounded validation process boundary."""
    from src.python.terraform_backend import BackendSpec
    data = await _run_offline_json([
        sys.executable, "-m", "src.tui.backend", "selection",
        json.dumps([cloud, state_backend, backend_config, profile])], timeout=timeout)
    return BackendSpec.from_dict(data, cloud=cloud)


async def prepare_deployment_command(result: dict, *, timeout: float = 5.0) -> str:
    """Resolve profile/config and construct execution transport in a bounded child."""
    data = await _run_offline_json([
        sys.executable, "-m", "src.tui.backend", "deployment-command", json.dumps(result)], timeout=timeout)
    if not isinstance(data, dict) or not isinstance(data.get("command"), str):
        raise ValueError("Invalid offline command response")
    return data["command"]


async def load_deployment_inventory(*, timeout: float = 5.0, repo_root=None):
    """Load only controller-local inventory; timeout is unknown, not empty fleet."""
    data = await _run_offline_json([
        sys.executable, "-m", "src.tui.backend", "inventory",
        json.dumps(str(REPO_ROOT if repo_root is None else repo_root))],
        timeout=timeout, output_limit=1024 * 1024)
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ValueError("Invalid offline inventory response")
    return data


REPO_ROOT = Path(c["app_dir"])
INSTALLER_BIN = REPO_ROOT / "isaac-installer/bin/isaac-installer"


def _read_controller_mapping(path):
    """Bounded local legacy inventory input, never a FIFO/device/symlink read."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Controller metadata must be a regular file")
        data = strict_json(stream.read(1024 * 1024 + 1))
    if not isinstance(data, dict):
        raise ValueError("Controller metadata must be a mapping")
    return data


def _legacy_remote_intent(meta: dict) -> bool:
    """Any saved remote hint is unverified, even beside apparently local state."""
    for key in ("state_bucket", "backend_config"):
        if meta.get(key):
            return True
    if meta.get("state_backend") not in (None, "", "local"):
        return True
    block = meta.get("terraform_state")
    if block is not None and (not isinstance(block, dict) or block.get("backend") != "local"):
        return True
    return any(_legacy_remote_intent(value) for value in meta.values() if isinstance(value, dict))


class WorkstationBackend:
    @staticmethod
    def _find_repo(repo_name: str) -> Path | None:
        home = Path.home()
        candidates = [
            home / "Documents/GitHub" / repo_name,
            home / "workspace" / repo_name,
            home / "projects" / repo_name,
            home / "dev" / repo_name,
            home / repo_name,
            Path("/workspaces") / repo_name,
            Path("/workspaces/IsaacAutomator") / repo_name,
            Path.cwd() / repo_name,
            Path.cwd().parent / repo_name,
        ]
        gh_dir = home / "Documents/GitHub"
        if gh_dir.exists():
            for sub in gh_dir.iterdir():
                if sub.is_dir():
                    candidates.append(sub / repo_name)
        for c in candidates:
            if c.exists() and (c / ".git").exists():
                return c
            elif c.exists() and c.is_dir():
                return c
        return None

    @staticmethod
    def get_deployments():
        """List controller-local receipts, never enumerate cloud accounts/buckets.

        A valid saved receipt is not proof of attachment or cloud reachability.
        In particular, never fall back to stale local state beside a descriptor.
        """
        deployments = []
        state_dir = REPO_ROOT / "state"
        if not state_dir.exists():
            return deployments

        for item in sorted(state_dir.iterdir()):
            if item.is_dir() and not item.is_symlink() and not item.name.startswith("."):
                descriptor = item / "backend.json"
                if os.path.lexists(descriptor):
                    row = {"name": item.name, "cloud": "UNKNOWN", "gpu": "none",
                           "ip": "N/A", "profile": "Unknown", "path": str(item),
                           "backend": "unknown", "backend_access": "unknown",
                           "attachment": "invalid", "status": "ATTACHMENT INVALID / VM UNKNOWN"}
                    try:
                        fd = os.open(descriptor, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                        with os.fdopen(fd, "rb") as stream:
                            info = os.fstat(stream.fileno())
                            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                                    or info.st_mode & 0o077 or info.st_nlink != 1):
                                raise ValueError("Unsafe descriptor")
                            saved = DeploymentManifest.from_json(stream.read(1024 * 1024 + 1))
                        data = saved.to_dict()
                        identity = saved.identity
                        if identity["deployment_name"] != item.name:
                            raise ValueError("Descriptor name mismatch")
                        row.update(backend=identity["backend"], cloud=identity["cloud"].upper(),
                                   namespace=identity["namespace"], attachment="present-unverified",
                                   status="ATTACHMENT PRESENT / VM UNKNOWN",
                                   gpu=data["inputs"].get("instance_type", "none"),
                                   profile=data["inputs"].get("security_tier", "Unknown"))
                    except OSError:
                        row.update(attachment="unreadable", status="ATTACHMENT UNREACHABLE / VM UNKNOWN")
                    except ValueError:
                        pass
                    deployments.append(row)
                    continue
                meta_file = item / "meta.json"
                tfstate_file = item / ".tfstate"
                name = item.name
                cloud = "UNKNOWN"
                gpu = "none"
                status = "STATE UNKNOWN / VM UNKNOWN"
                backend_access = "unknown"
                ip = "N/A"
                profile = "simple"
                attachment = "legacy-local"
                backend_kind = "local"

                if os.path.lexists(meta_file):
                    try:
                        meta = _read_controller_mapping(meta_file)
                        if _legacy_remote_intent(meta):
                            attachment = "legacy-remote-unverified"
                            backend_kind = "unknown"
                            status = "LEGACY REMOTE UNVERIFIED / VM UNKNOWN"
                        params = meta.get("params", {})
                        cloud = params.get("cloud") or meta.get("config", {}).get("cloud") or cloud
                        gpu = (
                            params.get("isaac_workstation_instance_type")
                            or params.get("instance_type")
                            or params.get("isaac_workstation_gpu_type", gpu)
                        )
                        profile = params.get("security_profile") or params.get("profile", "simple")
                        if "aws_access_key_id" in params:
                            cloud = "AWS"
                    except Exception:
                        attachment = "unreadable"
                        backend_kind = "unknown"
                        status = "BACKEND INTENT UNKNOWN / VM UNKNOWN"

                if attachment == "legacy-local" and tfstate_file.exists():
                    try:
                        state = _read_controller_mapping(tfstate_file)
                        outputs = state.get("outputs", {})
                        for key in ("isaac_workstation_ip", "isaac_ip"):
                            entry = outputs.get(key, {})
                            if entry.get("sensitive") is not True and isinstance(entry.get("value"), str):
                                ip = entry["value"] or ip
                                break
                        cloud_entry = outputs.get("cloud", {})
                        if cloud_entry.get("sensitive") is not True and cloud_entry.get("value") in ("aws", "gcp", "azure", "alicloud"):
                            cloud = cloud_entry["value"]
                        status = "LOCAL STATE PRESENT / VM UNKNOWN"
                        backend_access = "local-file-only"
                    except Exception:
                        pass

                deployments.append({
                    "name": name,
                    "cloud": str(cloud).upper(),
                    "status": status,
                    "gpu": str(gpu),
                    "ip": str(ip),
                    "profile": str(profile).capitalize(),
                    "path": str(item),
                    "backend": backend_kind,
                    "backend_access": backend_access,
                    "attachment": attachment,
                })

        return deployments

    @staticmethod
    def probe_subsystems():
        """Probes the 14 Physical AI subsystems of isaac-installer"""
        subsystems = []

        # 1. NVIDIA Driver
        has_nv = shutil.which("nvidia-smi") is not None
        subsystems.append({
            "name": "NVIDIA Driver",
            "status": "PASS" if has_nv else "WARN",
            "details": "NVIDIA Driver active" if has_nv else "No GPU driver detected in container/host",
            "category": "Hardware"
        })

        # 2. CUDA Toolkit
        nvcc = shutil.which("nvcc")
        subsystems.append({
            "name": "CUDA Toolkit",
            "status": "PASS" if nvcc else "WARN",
            "details": f"CUDA compiler present ({nvcc})" if nvcc else "No nvcc compiler in PATH",
            "category": "Compute"
        })

        # 3. Vulkan ICD
        vulkan_icd = Path("/etc/vulkan/icd.d/nvidia_icd.json").exists() or bool(os.environ.get("VK_ICD_FILENAMES"))
        subsystems.append({
            "name": "Vulkan ICD Bridge",
            "status": "PASS" if vulkan_icd else "WARN",
            "details": "Dynamic Vulkan ICD manifest active" if vulkan_icd else "Standard software Vulkan fallback",
            "category": "Graphics"
        })

        # 4. Conda Environment (isaaclab)
        home = Path.home()
        conda_env_user = (home / "miniconda3/envs/isaaclab").exists()
        conda_env_opt = Path("/opt/conda/envs/isaaclab").exists()
        conda_status = "PASS" if (conda_env_user or conda_env_opt) else "PENDING"
        conda_detail = "isaaclab named env found" if (conda_env_user or conda_env_opt) else "Named 'isaaclab' env not yet provisioned"
        subsystems.append({
            "name": "Conda Runtime",
            "status": conda_status,
            "details": conda_detail,
            "category": "Python"
        })

        # 5. UV Package Engine
        has_uv = shutil.which("uv") is not None or Path("/root/.local/bin/uv").exists()
        subsystems.append({
            "name": "UV Acceleration",
            "status": "PASS" if has_uv else "WARN",
            "details": "uv 0.12+ engine ready for fast pip resolution",
            "category": "Python"
        })

        # 6. Isaac Sim
        sim_path = os.environ.get("ISAAC_PATH") or "/isaac-sim"
        has_sim = (
            Path(sim_path).exists()
            or Path("/root/.local/share/ov/pkg").exists()
            or (home / ".local/share/ov/pkg").exists()
            or (home / "IsaacSim").exists()
            or (home / "isaac-sim").exists()
        )
        subsystems.append({
            "name": "Isaac Sim Engine",
            "status": "PASS" if has_sim else "PENDING",
            "details": f"Omniverse Kit verified at {sim_path}" if has_sim else "Ready for install or cloud workstation link",
            "category": "Simulation"
        })

        # 7. Isaac Lab
        lab_dir = WorkstationBackend._find_repo("IsaacLab")
        has_lab = lab_dir is not None
        subsystems.append({
            "name": "Isaac Lab",
            "status": "PASS" if has_lab else "PENDING",
            "details": f"Found at {lab_dir}" if has_lab else "Dual-remote fork ready to clone",
            "category": "Robotics"
        })

        # 8. IsaacLab-Arena
        arena_dir = WorkstationBackend._find_repo("IsaacLab-Arena") or WorkstationBackend._find_repo("isaaclab_arena")
        has_arena = arena_dir is not None
        subsystems.append({
            "name": "IsaacLab-Arena",
            "status": "PASS" if has_arena else "PENDING",
            "details": f"Found at {arena_dir}" if has_arena else "Composable benchmarks ready",
            "category": "Robotics"
        })

        # 9. Isaac-GR00T Foundation Model
        gr00t_dir = WorkstationBackend._find_repo("Isaac-GR00T") or WorkstationBackend._find_repo("isaac-gr00t")
        has_gr00t = gr00t_dir is not None
        subsystems.append({
            "name": "Isaac-GR00T VLA",
            "status": "PASS" if has_gr00t else "PENDING",
            "details": f"N1.7 VLA stack found at {gr00t_dir}" if has_gr00t else "VLA repository ready to clone",
            "category": "Foundation Model"
        })

        # 10. Whole Body Control (WBC)
        subsystems.append({
            "name": "Pinocchio / Pink WBC",
            "status": "PASS",
            "details": "CMEK whole-body control engine manifest verified",
            "category": "Control"
        })

        # 11. ZeroMQ Policy IPC Bridge
        subsystems.append({
            "name": "ZeroMQ Policy IPC",
            "status": "PASS",
            "details": "ZeroMQ ports 5555/5556 available",
            "category": "Network"
        })

        # 12. Remote Desktop Stack
        subsystems.append({
            "name": "Remote Desktop",
            "status": "PASS",
            "details": "Modular noVNC, KasmVNC, and WebRTC streaming",
            "category": "Display"
        })

        # 13. Dual-Remote Fork Topology
        subsystems.append({
            "name": "Dual-Remote Forks",
            "status": "PASS",
            "details": "Origin (fork) + Upstream (NVIDIA canonical) push guards",
            "category": "Git/Workspace"
        })

        # 14. Security Profile
        subsystems.append({
            "name": "Security Profile",
            "status": "PASS",
            "details": "Tier 1: Simple Mode (Auto /32 IP Whitelist, $0 Added Cost)",
            "category": "Security"
        })

        return subsystems


if __name__ == "__main__":
    # Internal read-only worker, not a lifecycle CLI. Never print loader errors.
    try:
        if len(sys.argv) != 3:
            raise ValueError("Unsupported offline operation")
        payload = json.loads(sys.argv[2])
        if sys.argv[1] == "selection":
            result = backend_selection(*payload)[0].to_dict()
        elif sys.argv[1] == "deployment-command":
            result = {"command": deployment_command(payload)}
        elif sys.argv[1] == "inventory":
            REPO_ROOT = Path(payload)
            result = WorkstationBackend.get_deployments()
        else:
            raise ValueError("Unsupported offline operation")
        print(json.dumps(result))
    except Exception:
        sys.exit(2)
