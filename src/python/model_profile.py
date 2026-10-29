"""Declarative model profile parser, validator, and download plan generator."""
from pathlib import Path
from copy import deepcopy
import os
import re
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


def resolve_model_profile(
    name_or_path: str | Path,
    target_user: str = "ubuntu",
    target_home: str = "/home/ubuntu",
    directory: Path | None = None,
) -> dict:
    """Validate and resolve a model profile into an executable plan."""
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
        
    resolved_models = []
    total_min_disk_gb = 0
    
    for idx, item in enumerate(raw_models):
        if not isinstance(item, dict):
            raise ModelProfileError(f"models[{idx}] must be a dictionary")
            
        name = item.get("name")
        if not name or not isinstance(name, str):
            raise ModelProfileError(f"models[{idx}].name is required")
            
        repo_id = item.get("repo_id")
        if not repo_id or not isinstance(repo_id, str):
            raise ModelProfileError(f"models[{idx}].repo_id is required")
            
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


def generate_download_plan(
    resolved_profile: dict,
) -> dict:
    """Generate the explicit bash commands and filesystem actions for deployment."""
    target_user = resolved_profile["target_user"]
    directories_to_create = set()
    symlinks_to_create = []
    download_commands = []
    
    # Storage topology mounts
    if resolved_profile.get("storage"):
        storage = resolved_profile["storage"]
        directories_to_create.add(storage["physical_dir"])
        for mount in storage.get("logical_mounts", []):
            symlinks_to_create.append((mount["link_to"], mount["target"]))
            directories_to_create.add(str(Path(mount["target"]).parent))
            
    for model in resolved_profile["models"]:
        dest = model["destination"]
        directories_to_create.add(dest)
        
        for sym in model.get("symlinks", []):
            symlinks_to_create.append((dest, sym))
            directories_to_create.add(str(Path(sym).parent))
            
        # Build the hf download command line
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
            
        for pat in model.get("allow_patterns", []):
            cmd_parts.append(f"--include '{pat}'")
            
        for pat in model.get("ignore_patterns", []):
            cmd_parts.append(f"--exclude '{pat}'")
            
        download_commands.append({
            "model_name": model["name"],
            "destination": dest,
            "command": " ".join(cmd_parts),
            "min_disk_free_gb": model["min_disk_free_gb"],
        })
        
    return {
        "profile_name": resolved_profile["model_profile_name"],
        "target_user": target_user,
        "directories_to_create": sorted(list(directories_to_create)),
        "symlinks_to_create": symlinks_to_create,
        "download_commands": download_commands,
        "total_min_disk_gb": resolved_profile["total_min_disk_gb"],
    }
