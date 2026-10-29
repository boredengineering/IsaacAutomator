"""Declarative model profile parser, validator, cloud archive manager, and download plan generator."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import yaml

MODEL_PROFILE_DIR = Path(__file__).resolve().parents[2] / 'configs' / 'models'


class ModelProfileError(ValueError):
    """Raised when a model profile fails validation or cannot be resolved."""


class _StrictYamlLoader(yaml.SafeLoader):
    """YAML loader enforcing string keys and rejecting duplicates."""
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag != 'tag:yaml.org,2002:str':
                raise ModelProfileError('YAML keys must be strings; merge keys unsupported')
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise ModelProfileError(f"Duplicate YAML key '{key}'")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def list_model_profiles(directory: Path | None = None) -> list[str]:
    """Return sorted list of available model profile names."""
    model_dir = directory or MODEL_PROFILE_DIR
    if not model_dir.is_dir():
        return []
    profiles = []
    for path in sorted(model_dir.glob('*.yaml')):
        profiles.append(path.stem)
    return profiles


def find_model_profile_path(name_or_path: str | Path, directory: Path | None = None) -> Path:
    """Resolve a profile name or explicit path to a Path object."""
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate.resolve()

    model_dir = directory or MODEL_PROFILE_DIR
    named_candidate = model_dir / f"{name_or_path}.yaml"
    if named_candidate.is_file():
        return named_candidate.resolve()

    named_exact = model_dir / str(name_or_path)
    if named_exact.is_file():
        return named_exact.resolve()

    raise ModelProfileError(f"Model profile '{name_or_path}' not found in {model_dir}")


def load_model_profile(name_or_path: str | Path, directory: Path | None = None) -> dict:
    """Load and parse a raw model profile YAML document."""
    file_path = find_model_profile_path(name_or_path, directory=directory)
    try:
        content = file_path.read_text(encoding='utf-8')
    except OSError as err:
        raise ModelProfileError(f"Failed to read model profile {file_path}: {err}") from err

    try:
        parsed = yaml.load(content, Loader=_StrictYamlLoader) or {}
    except yaml.YAMLError as err:
        raise ModelProfileError(f"YAML syntax error in {file_path}: {err}") from err

    if not isinstance(parsed, dict):
        raise ModelProfileError(f"Expected top-level mapping in {file_path}")

    return parsed


def _expand_path(path_str: str, target_home: str = "/home/ubuntu") -> str:
    """Expand tilde or environment placeholders portably."""
    if not path_str:
        return path_str
    expanded = path_str.replace("~", target_home)
    expanded = expanded.replace("$HOME", target_home)
    expanded = expanded.replace("${HOME}", target_home)
    expanded = expanded.replace("$HF_HOME", f"{target_home}/.cache/huggingface")
    return os.path.normpath(expanded)


def propose_models_bucket(
    *,
    cloud: str = "gcp",
    namespace: str = "studio",
    owner_scope: str,
    region: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Return deterministic global master archive bucket configuration for models_bucket: 'auto'.

    Uses the exact same v1 identity hash as propose_backend() so the models bucket
    and state bucket share a human-recognizable 20-character hash suffix:
      - State bucket:  isaac-state-<20-char-hash>
      - Models bucket: isaac-models-<20-char-hash>
    """
    if cloud not in ("aws", "gcp", "azure"):
        raise ValueError("Model archive proposals support AWS, GCP and Azure only")
    if not owner_scope or not isinstance(owner_scope, str):
        raise ValueError("owner_scope (project / account ID / subscription ID) is required")
    identity = {
        "proposal_version": 1,
        "cloud": cloud,
        "namespace": namespace,
        "owner_scope": owner_scope,
        "region": region if cloud == "aws" else None,
        "tenant_id": tenant_id if cloud == "azure" else None,
    }
    token = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    hash_prefix = token[:20]

    if cloud == "gcp":
        bucket_name = f"isaac-models-{hash_prefix}"
        uri = f"gs://{bucket_name}"
    elif cloud == "aws":
        bucket_name = f"isaac-models-{hash_prefix}"
        uri = f"s3://{bucket_name}"
    else:
        bucket_name = f"isaacmodels{token[:13]}"
        uri = f"az://{bucket_name}/models"

    return {
        "cloud": cloud,
        "namespace": namespace,
        "owner_scope": owner_scope,
        "hash_prefix": hash_prefix,
        "bucket": bucket_name,
        "uri": uri,
        "labels": build_bucket_labels(
            purpose="ai-models-master-archive",
            namespace=namespace,
            profile="studio-enterprise",
        ),
    }


def build_bucket_labels(
    *,
    purpose: str = "ai-models-master-archive",
    namespace: str = "studio",
    profile: str = "studio-enterprise",
) -> dict[str, str]:
    """Build GCP/AWS/Azure-compliant lowercase key/value labels (<=63 chars, [a-z0-9_-])."""
    def _sanitize(val: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_-]", "-", str(val).lower().strip())
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return (cleaned or "default")[:63]

    if purpose == "terraform-remote-state":
        desc = "isaac-automator-terraform-remote-state-and-locks"
    else:
        desc = "isaac-automator-permanent-ai-model-zoo-archive"

    return {
        "managed_by": "isaac-automator",
        "purpose": _sanitize(purpose),
        "namespace": _sanitize(namespace),
        "profile": _sanitize(profile),
        "description": _sanitize(desc),
    }


def generate_bucket_readme(
    *,
    bucket_name: str,
    purpose: str = "ai-models-master-archive",
    project: str = "",
    namespace: str = "studio",
    profile: str = "studio-enterprise",
    model_profile: str = "configs/models/complete-model-zoo.yaml",
) -> str:
    """Generate a human-readable 00-BUCKET-README.md for Cloud Console operators."""
    if purpose == "terraform-remote-state":
        return f"""# Isaac Automator — Terraform Remote State & Lock Bucket (`gs://{bucket_name}`)

## Purpose (Human Operator Summary)
This bucket is **automatically provisioned and managed by Isaac Automator**.
It stores the **Terraform Remote State (`.tfstate`) and state locks** for cloud GPU workstations deployed in project `{project}` (namespace: `{namespace}`).

- **Managed By**: Isaac Automator (`configs/profiles/{profile}.yaml`)
- **Bucket Role**: `terraform-remote-state`
- **Object Versioning**: Enabled (protects state history)
- **Soft Delete Retention**: 7 days (`604800s`)
- **Public Access**: Strictly enforced private (`publicAccessPrevention = enforced`)

> **WARNING**: Do NOT manually delete or edit `.tfstate` objects inside `isaacautomator/v2/` while a workstation is active, or Terraform will lose track of running cloud resources.
"""

    return f"""# Isaac Automator — Permanent AI Model Zoo Master Archive (`gs://{bucket_name}`)

## Purpose (Human Operator Summary)
This bucket is **automatically provisioned and managed by Isaac Automator**.
It serves as the **Permanent Global Cloud Object Storage Archive** for large AI & Robotics Foundation Model weights (`safetensors`, `GR00T`, `OpenPI`, `Cosmos-Reason2`, `SAM-3D`, `Qwen`, `DeepSeek`, `GLM`, `Kimi`).

- **Managed By**: Isaac Automator (`configs/profiles/{profile}.yaml`)
- **Model Catalog**: `{model_profile}`
- **Project / Namespace**: `{project}` / `{namespace}`
- **Bucket Role**: `ai-models-master-archive`
- **Object Versioning**: Disabled (prevents double-billing when updating multi-hundred-GB model weights)
- **Public Access**: Strictly enforced private (`publicAccessPrevention = enforced`)

## Why This Bucket Exists (Global Storage vs. Zonal Disks)
1. **Permanent & Global (`~$0.02/GB/month`)**: Model weights live permanently in this bucket and **survive `./destroy`**.
2. **On-Demand Zonal Block Disks (`/mnt/models_fast`)**: When you launch a GPU workstation in *any* region or zone (`us-central1`, `us-east4`, `europe-west4`, etc.), Isaac Automator attaches a fresh zonal `hyperdisk-balanced` SSD and hydrates the requested models from this bucket at **10–16 Gbps** via `gcloud storage rsync`, then warms them into Host RAM (`vmtouch`) at **28.5 GB/s**.
3. **Zero Idle Disk Waste**: When you destroy your workstation or detach the models disk (`./download-models <name> --detach-disk`), you stop paying for expensive zonal SSD storage while keeping all models safely archived here.

## Directory Layout
- `00-BUCKET-README.md` — This human operator documentation file.
- `models/<model-name>/` — Mirrored model checkpoint directories (e.g., `models/gr00t-n1.7-3b/`, `models/cosmos-reason2-8b/`, `models/glm-5.3-flash/`).
"""


def ensure_bucket_self_documented(
    *,
    bucket_name: str,
    project: str,
    region: str = "us-central1",
    purpose: str = "ai-models-master-archive",
    namespace: str = "studio",
    profile: str = "studio-enterprise",
    workstation_service_account: str | None = None,
    create_if_missing: bool = True,
    dry_run: bool = False,
) -> dict:
    """Ensure a GCS bucket exists (if create_if_missing), has Cloud Console labels, IAM binding, and 00-BUCKET-README.md."""
    labels = build_bucket_labels(purpose=purpose, namespace=namespace, profile=profile)
    readme_text = generate_bucket_readme(
        bucket_name=bucket_name,
        purpose=purpose,
        project=project,
        namespace=namespace,
        profile=profile,
    )
    comment_meta = (
        "Isaac Automator Permanent AI Model Zoo Master Archive (survives ./destroy; hydrates zonal /mnt/models_fast disks)"
        if purpose == "ai-models-master-archive"
        else "Isaac Automator Hardened Terraform Remote State & Lock Bucket"
    )

    if dry_run:
        return {
            "bucket": bucket_name,
            "project": project,
            "labels": labels,
            "readme_object": f"gs://{bucket_name}/00-BUCKET-README.md",
            "comment": comment_meta,
            "status": "dry-run",
        }

    # 1. Check if bucket exists
    desc = subprocess.run(
        ["gcloud", "storage", "buckets", "describe", f"gs://{bucket_name}", f"--project={project}", "--format=json", "--quiet"],
        capture_output=True, text=True, check=False,
    )
    created = False
    if desc.returncode != 0:
        if not create_if_missing:
            raise ModelProfileError(f"Bucket gs://{bucket_name} does not exist in project {project}")
        subprocess.run(
            [
                "gcloud", "storage", "buckets", "create", f"gs://{bucket_name}",
                f"--project={project}",
                f"--location={region}",
                "--uniform-bucket-level-access",
                "--public-access-prevention",
                "--soft-delete-duration=7d",
                "--quiet",
            ],
            check=True,
        )
        created = True

    # 2. Apply Cloud Console labels
    label_pairs = ",".join(f"{k}={v}" for k, v in labels.items())
    subprocess.run(
        [
            "gcloud", "storage", "buckets", "update", f"gs://{bucket_name}",
            f"--project={project}",
            f"--update-labels={label_pairs}",
            "--quiet",
        ],
        check=True,
    )

    # 3. Grant workstation Service Account roles/storage.objectAdmin if provided
    if workstation_service_account:
        sa_email = workstation_service_account.strip()
        if "@" in sa_email:
            subprocess.run(
                [
                    "gcloud", "storage", "buckets", "add-iam-policy-binding", f"gs://{bucket_name}",
                    f"--member=serviceAccount:{sa_email}",
                    "--role=roles/storage.objectAdmin",
                    f"--project={project}",
                    "--quiet",
                ],
                check=False,
            )

    # 4. Upload 00-BUCKET-README.md with custom comment metadata
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix="-00-BUCKET-README.md") as tmp:
        tmp.write(readme_text)
        tmp.flush()
        subprocess.run(
            [
                "gcloud", "storage", "cp", tmp.name, f"gs://{bucket_name}/00-BUCKET-README.md",
                f"--project={project}",
                "--content-type=text/markdown",
                f"--custom-metadata=comment={comment_meta},managed_by=isaac-automator,purpose={purpose}",
                "--quiet",
            ],
            check=True,
        )

    return {
        "bucket": bucket_name,
        "project": project,
        "labels": labels,
        "readme_object": f"gs://{bucket_name}/00-BUCKET-README.md",
        "comment": comment_meta,
        "status": "created" if created else "updated",
    }


def resolve_model_profile(
    name_or_path: str | Path,
    target_user: str = "ubuntu",
    target_home: str = "/home/ubuntu",
    directory: Path | None = None,
    selected_models: list[str] | None = None,
) -> dict:
    """Validate and resolve a model profile into an executable plan, optionally filtered by selected_models."""
    raw = load_model_profile(name_or_path, directory=directory)

    schema_version = raw.get("schema_version", "v1")
    if schema_version != "v1":
        raise ModelProfileError(f"Unsupported schema_version '{schema_version}'; expected 'v1'")

    profile_name = raw.get("model_profile_name")
    if not profile_name or not isinstance(profile_name, str):
        raise ModelProfileError("model_profile_name is required and must be a string")

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModelProfileError("defaults must be a dictionary")

    global_provider = defaults.get("provider", "huggingface")
    global_engine = defaults.get("download_engine", "hf_transfer")
    global_auth_env = defaults.get("auth_env", "HF_TOKEN")

    storage_cfg = raw.get("storage", {})
    resolved_storage = None
    if storage_cfg:
        if not isinstance(storage_cfg, dict):
            raise ModelProfileError("storage must be a dictionary if defined")
        physical_dir = _expand_path(storage_cfg.get("physical_dir", "/models"), target_home)
        logical_mounts = []
        for mount in storage_cfg.get("logical_mounts", []):
            if not isinstance(mount, dict) or "target" not in mount or "link_to" not in mount:
                raise ModelProfileError("logical_mounts items must have 'target' and 'link_to'")
            logical_mounts.append({
                "target": _expand_path(mount["target"], target_home),
                "link_to": _expand_path(mount["link_to"], target_home),
            })
        resolved_storage = {
            "physical_dir": physical_dir,
            "logical_mounts": logical_mounts,
        }

    raw_models = raw.get("models")
    if not raw_models or not isinstance(raw_models, list):
        raise ModelProfileError("models must be a non-empty list of model definitions")

    selected_filter = None
    if selected_models:
        selected_filter = [m.strip() for m in selected_models if m and m.strip()]

    resolved_models = []
    total_min_disk_gb = 0
    available_names = []

    for idx, item in enumerate(raw_models):
        if not isinstance(item, dict):
            raise ModelProfileError(f"models[{idx}] must be a dictionary")

        name = item.get("name")
        if not name or not isinstance(name, str):
            raise ModelProfileError(f"models[{idx}].name is required")
        available_names.append(name)

        repo_id = item.get("repo_id")
        if not repo_id or not isinstance(repo_id, str):
            raise ModelProfileError(f"models[{idx}].repo_id is required")

        if selected_filter is not None and name not in selected_filter and repo_id not in selected_filter:
            continue

        revision = item.get("revision", "main")
        repo_type = item.get("repo_type", "model")
        if repo_type not in ("model", "dataset"):
            raise ModelProfileError(f"models[{idx}].repo_type must be 'model' or 'dataset'")

        # Determine destination
        if "destination" in item:
            dest = _expand_path(item["destination"], target_home)
        elif resolved_storage and "subpath" in item:
            dest = os.path.join(resolved_storage["physical_dir"], item["subpath"])
        else:
            dest = f"{target_home}/.cache/huggingface/hub"

        # Symlinks
        symlinks = [_expand_path(s, target_home) for s in item.get("symlinks", [])]

        # Disk requirements
        min_disk = int(item.get("min_disk_free_gb", 0))
        total_min_disk_gb += min_disk

        allow_patterns = item.get("allow_patterns", [])
        ignore_patterns = item.get("ignore_patterns", [])

        resolved_models.append({
            "name": name,
            "description": item.get("description", ""),
            "repo_id": repo_id,
            "repo_type": repo_type,
            "revision": revision,
            "destination": dest,
            "symlinks": symlinks,
            "allow_patterns": allow_patterns,
            "ignore_patterns": ignore_patterns,
            "min_disk_free_gb": min_disk,
            "provider": item.get("provider", global_provider),
            "download_engine": item.get("download_engine", global_engine),
            "auth_env": item.get("auth_env", global_auth_env),
        })

    if selected_filter is not None:
        matched_names = {m["name"] for m in resolved_models} | {m["repo_id"] for m in resolved_models}
        unknown = [s for s in selected_filter if s not in matched_names]
        if unknown:
            raise ModelProfileError(
                f"Unknown model(s) requested: {', '.join(unknown)}. "
                f"Available in '{profile_name}': {', '.join(available_names)}"
            )

    return {
        "schema_version": schema_version,
        "model_profile_name": profile_name,
        "description": raw.get("description", ""),
        "target_user": target_user,
        "target_home": target_home,
        "storage": resolved_storage,
        "models": resolved_models,
        "total_min_disk_gb": total_min_disk_gb,
    }


def calculate_models_disk_spec(
    resolved_profile: dict,
    *,
    safety_factor: float = 1.25,
    min_size_gb: int = 100,
) -> dict:
    """Calculate dynamic zonal block disk size (rounded up to 100 GB increments) for the resolved model set."""
    raw_total_gb = int(resolved_profile.get("total_min_disk_gb", 0))
    padded = math.ceil(raw_total_gb * safety_factor)
    rounded_100 = int(math.ceil(max(padded, min_size_gb) / 100.0) * 100)
    return {
        "selected_model_count": len(resolved_profile.get("models", [])),
        "raw_total_gb": raw_total_gb,
        "safety_factor": safety_factor,
        "recommended_disk_gb": rounded_100,
    }


def generate_models_env_content(resolved_profile: dict, models_bucket: str | None = None) -> str:
    """Generate deterministic /etc/isaac-models.env and /etc/profile.d/isaac-models.sh exports."""
    target_home = resolved_profile.get("target_home", "/home/ubuntu")
    lines = [
        "# ==============================================================================",
        "# Isaac Automator - Programmatic Model Storage & Path Projection Contract",
        f"# Active Model Profile: {resolved_profile.get('model_profile_name', 'complete-model-zoo')}",
        "# ==============================================================================",
        'export ISAAC_MODELS_ROOT="/models"',
        'export ISAAC_MODELS_MOUNT="/mnt/models_fast"',
        f'export ISAAC_MODELS_BUCKET="{models_bucket or ""}"',
        f'export HF_HOME="{target_home}/.cache/huggingface"',
        'export HF_HUB_CACHE="/mnt/models_fast/hf_cache/hub"',
        'export HF_HUB_ENABLE_HF_TRANSFER="1"',
        f'export GR00T_CACHE_DIR="{target_home}/.cache/isaac-gr00t"',
        f'export OPENPI_DATA_HOME="{target_home}/.cache/openpi"',
    ]
    for model in resolved_profile.get("models", []):
        env_Suffix = re.sub(r"[^A-Z0-9]+", "_", model["name"].upper()).strip("_")
        # Prefer canonical /models/<name> symlink if present, else destination
        canonical_path = f"/models/{model['name']}"
        if canonical_path not in model.get("symlinks", []) and not model["destination"].startswith("/mnt/models_fast/models/"):
            canonical_path = model["destination"]
        lines.append(f'export ISAAC_MODEL_{env_Suffix}_PATH="{canonical_path}"')
    return "\n".join(lines) + "\n"


def generate_download_plan(
    resolved_profile: dict,
    *,
    models_bucket: str | None = None,
) -> dict:
    """Generate the explicit bash commands and filesystem actions for deployment.

    When `models_bucket` is supplied (e.g. 'isaac-models-c3527cbb69c601fa1dd9'),
    generates a 3-Tier Waterfall command per model:
      Tier 1: Check local marker `<dest>/.provisioned_complete`
      Tier 2: Try fast internal pull from `gs://<models_bucket>/models/<name>/`
      Tier 3: Fallback to `hf download` + push back to `gs://<models_bucket>/models/<name>/`
    """
    target_user = resolved_profile["target_user"]
    directories_to_create = set()
    symlinks_to_create = []
    download_commands = []

    clean_bucket = None
    if models_bucket:
        clean_bucket = str(models_bucket).replace("gs://", "").replace("s3://", "").strip("/")

    # Storage topology mounts
    mount_map = {}
    if resolved_profile.get("storage"):
        storage = resolved_profile["storage"]
        directories_to_create.add(storage["physical_dir"])
        for mount in storage.get("logical_mounts", []):
            symlinks_to_create.append((mount["link_to"], mount["target"]))
            directories_to_create.add(str(Path(mount["target"]).parent))
            directories_to_create.add(mount["link_to"])
            mount_map[mount["target"].rstrip("/")] = mount["link_to"].rstrip("/")

    for model in resolved_profile["models"]:
        dest = model["destination"]
        directories_to_create.add(dest)

        for sym in model.get("symlinks", []):
            # Skip self-referencing symlinks when a parent directory is already a logical_mount to physical_dir
            resolved_sym = sym
            for m_target, m_link in mount_map.items():
                if sym == m_target or sym.startswith(m_target + "/"):
                    resolved_sym = m_link + sym[len(m_target):]
                    break
            if os.path.normpath(resolved_sym) == os.path.normpath(dest):
                continue
            symlinks_to_create.append((dest, sym))

        # Build the download command line (Hugging Face Hub or GCS bucket URI)
        if model.get("provider") == "gcs" or str(model["repo_id"]).startswith("gs://"):
            gcs_src = model["repo_id"] if str(model["repo_id"]).startswith("gs://") else f"gs://{model['repo_id']}"
            hf_cmd = f"mkdir -p '{dest}' && gcloud storage rsync -r '{gcs_src}' '{dest}'"
        else:
            cmd_parts = []
            if model["download_engine"] == "hf_transfer":
                cmd_parts.append("HF_HUB_ENABLE_HF_TRANSFER=1")

            cmd_parts.append("hf")
            cmd_parts.append("download")
            cmd_parts.append(model["repo_id"])

            if model["repo_type"] == "dataset":
                cmd_parts.append("--repo-type dataset")

            if model["revision"] and model["revision"] != "main":
                cmd_parts.append(f"--revision {model['revision']}")

            if not dest.endswith("/.cache/huggingface/hub"):
                cmd_parts.append(f"--local-dir {dest}")

            if model.get("allow_patterns"):
                inc_args = " ".join(f"'{pat}'" for pat in model["allow_patterns"])
                cmd_parts.append(f"--include {inc_args}")

            if model.get("ignore_patterns"):
                exc_args = " ".join(f"'{pat}'" for pat in model["ignore_patterns"])
                cmd_parts.append(f"--exclude {exc_args}")

            hf_cmd = " ".join(cmd_parts)
        gcs_uri = f"gs://{clean_bucket}/models/{model['name']}" if clean_bucket else None

        if gcs_uri:
            waterfall_cmd = (
                f"if [ -f '{dest}/.provisioned_complete' ]; then "
                f"echo '[Tier-1 Local] {model['name']} already provisioned at {dest}'; "
                f"elif gcloud storage ls '{gcs_uri}/.provisioned_complete' >/dev/null 2>&1; then "
                f"echo '[Tier-2 GCS Hydration] Pulling {model['name']} from {gcs_uri} -> {dest}...'; "
                f"mkdir -p '{dest}' && gcloud storage rsync -r '{gcs_uri}' '{dest}'; "
                f"else "
                f"echo '[Tier-3 HF Hub Download + GCS Archive] Downloading {model['name']} ({model['repo_id']})...'; "
                f"{hf_cmd} && "
                f"echo '[Tier-3 Archive Push] Caching {model['name']} to permanent bucket {gcs_uri}...' && "
                f"touch '{dest}/.provisioned_complete' && "
                f"(gcloud storage rsync -r '{dest}' '{gcs_uri}' || (rm -f '{dest}/.provisioned_complete' && exit 1)); "
                f"fi"
            )
        else:
            waterfall_cmd = f"{hf_cmd} && touch '{dest}/.provisioned_complete'"

        download_commands.append({
            "model_name": model["name"],
            "repo_id": model["repo_id"],
            "destination": dest,
            "hf_command": hf_cmd,
            "gcs_uri": gcs_uri,
            "command": waterfall_cmd,
            "min_disk_free_gb": model["min_disk_free_gb"],
        })

    disk_spec = calculate_models_disk_spec(resolved_profile)

    return {
        "profile_name": resolved_profile["model_profile_name"],
        "target_user": target_user,
        "models_bucket": clean_bucket,
        "directories_to_create": sorted(list(directories_to_create)),
        "symlinks_to_create": symlinks_to_create,
        "download_commands": download_commands,
        "total_min_disk_gb": resolved_profile["total_min_disk_gb"],
        "disk_spec": disk_spec,
        "env_file_content": generate_models_env_content(resolved_profile, models_bucket=clean_bucket),
    }
