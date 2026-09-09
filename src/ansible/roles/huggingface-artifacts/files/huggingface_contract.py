"""Dependency-free contract shared by profile, Ansible, and target runner.

Kept with the role so a copied role remains self-contained. Errors intentionally
omit input values: accidentally supplied credentials must not enter diagnostics.
"""
import json
import re



def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("huggingface contains duplicate JSON keys")
        result[key] = value
    return result


def decode_settings(value):
    if isinstance(value, str):
        try:
            value = json.loads(value, object_pairs_hook=unique_object)
        except (ValueError, TypeError):
            raise ValueError("huggingface_json must contain an unambiguous JSON mapping") from None
    return validate_settings(value)


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError("huggingface must be a mapping")
    if set(value) - {"enabled", "repositories", "token_file"}:
        raise ValueError("huggingface contains unsupported fields")
    enabled = value.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("huggingface.enabled must be a boolean")
    if "token_file" in value:
        path = value["token_file"]
        if (not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
                or any(part in ("", ".", "..") for part in path.split("/")[1:])):
            raise ValueError("huggingface.token_file must be a safe absolute file reference")
    entries = value.get("repositories", [])
    if not isinstance(entries, list) or (enabled and not entries):
        raise ValueError("huggingface.repositories must be a nonempty list when enabled")
    repositories, names = [], set()
    component = r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?"
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"name", "repo_id", "repo_type", "revision"}:
            raise ValueError("huggingface repository contains unsupported fields or is not a mapping")
        name, repo_id, revision = (entry.get(k) for k in ("name", "repo_id", "revision"))
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or name in names:
            raise ValueError("huggingface repository name must be safe and unique")
        if (not isinstance(repo_id, str) or not re.fullmatch(component + "/" + component, repo_id)
                or ".." in repo_id or "--" in repo_id or repo_id.endswith(".git")
                or any(len(part) > 96 for part in repo_id.split("/"))):
            raise ValueError("huggingface.repo_id must be namespace/repository")
        repo_type = entry.get("repo_type", "model")
        if repo_type not in ("model", "dataset"):
            raise ValueError("huggingface.repo_type must be model or dataset")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("huggingface.revision must be a full lowercase commit SHA")
        names.add(name)
        repositories.append(dict(name=name, repo_id=repo_id, repo_type=repo_type, revision=revision))
    if not enabled:
        return {"enabled": False}
    result = {"enabled": True, "repositories": repositories}
    if "token_file" in value:
        result["token_file"] = value["token_file"]
    return result
