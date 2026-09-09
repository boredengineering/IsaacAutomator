"""Validate the public Ansible contract before any remote mutation."""
import json
import re


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Artifact Registry workload key")
        result[key] = value
    return result


def validate_settings(enabled, cloud, project, location, repository, images_json):
    # INI group vars arrive as strings, JSON/YAML extra vars as real booleans.
    if isinstance(enabled, str) and enabled.lower() in ("true", "false"):
        enabled = enabled.lower() == "true"
    if type(enabled) is not bool:
        raise ValueError("enable_artifact_registry must be true or false")
    if not enabled:
        return {"enabled": False}
    if cloud != "gcp":
        raise ValueError("Artifact Registry requires cloud=gcp")
    for name, value, pattern in (
        ("project", project, r"[a-z][a-z0-9-]{4,28}[a-z0-9]"),
        ("location", location, r"[a-z]+-[a-z]+[0-9]+"),
        ("repository", repository, r"[a-z][a-z0-9_-]{0,62}"),
    ):
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError("invalid Artifact Registry " + name)
    try:
        # Ansible can decode an INI value before the role receives it.
        images = json.loads(images_json, object_pairs_hook=unique_object) if isinstance(images_json, str) else images_json
    except (ValueError, TypeError):
        raise ValueError("invalid artifact_registry_images_json") from None
    if not isinstance(images, dict):
        raise ValueError("Artifact Registry images must be a mapping")
    registry = location + "-docker.pkg.dev"
    prefix = registry + "/" + project + "/" + repository + "/"
    component = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
    image_pattern = re.escape(prefix) + component + r"(?:/" + component + r")*@sha256:[0-9a-f]{64}"
    for name, image in images.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError("invalid Artifact Registry workload name")
        if not isinstance(image, str) or not re.fullmatch(image_pattern, image):
            raise ValueError("images must be sha256 digests inside the configured repository")
    return {"enabled": True, "registry": registry, "images": images}


class FilterModule:
    def filters(self):
        return {"artifact_registry_settings": validate_settings}
