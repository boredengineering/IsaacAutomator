"""Normalize optional image providers and the legacy GCP registry contract."""

import re


class RegistryProfileError(ValueError):
    """An explicit registry configuration must not silently become defaults."""


def normalize_saved_artifact_registry(params: dict, cloud: str | None) -> dict:
    """Validate normalized metadata without reopening its original profile file."""
    enabled = params.get("enable_artifact_registry", False)
    if enabled is True and cloud != "gcp":
        raise RegistryProfileError("Artifact Registry is supported only by GCP deployments")
    return normalize_artifact_registry({
        "cloud": cloud,
        "artifact_registry": {
            "enabled": enabled,
            "project": params.get("artifact_registry_project", ""),
            "location": params.get("artifact_registry_location", ""),
            "repository": params.get("artifact_registry_repository", ""),
            "images": params.get("artifact_registry_images", {}),
        },
    })


def normalize_artifact_registry(profile: dict) -> dict:
    registry = profile.get("artifact_registry", {})
    if not isinstance(registry, dict):
        raise RegistryProfileError("artifact_registry must be a mapping")
    allowed = {"enabled", "project", "location", "repository", "images"}
    if set(registry) - allowed:
        raise RegistryProfileError("artifact_registry contains unsupported fields")
    enabled = registry.get("enabled", False)
    if not isinstance(enabled, bool):
        raise RegistryProfileError("artifact_registry.enabled must be a boolean")
    if enabled:
        if profile.get("cloud") != "gcp":
            raise RegistryProfileError("artifact_registry requires cloud: gcp")
        patterns = {
            "project": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
            "location": r"[a-z]+-[a-z]+[0-9]+",
            "repository": r"[a-z][a-z0-9_-]{0,62}",
        }
        for key, pattern in patterns.items():
            value = registry.get(key)
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise RegistryProfileError(f"artifact_registry.{key} is missing or invalid")
        images = registry.get("images", {})
        if not isinstance(images, dict):
            raise RegistryProfileError("artifact_registry.images must be a mapping")
        prefix = (
            f"{registry['location']}-docker.pkg.dev/"
            f"{registry['project']}/{registry['repository']}/"
        )
        component = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
        image_pattern = re.escape(prefix) + component + rf"(?:/{component})*@sha256:[0-9a-f]{{64}}"
        for name, image in images.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                raise RegistryProfileError("artifact_registry.images contains an invalid workload name")
            if not isinstance(image, str) or not re.fullmatch(image_pattern, image):
                raise RegistryProfileError(
                    "artifact_registry.images must use tag-free sha256 digests in the configured repository"
                )
    return {
        "enable_artifact_registry": enabled,
        "artifact_registry_project": registry.get("project", "") if enabled else "",
        "artifact_registry_location": registry.get("location", "") if enabled else "",
        "artifact_registry_repository": registry.get("repository", "") if enabled else "",
        "artifact_registry_images": dict(registry.get("images", {})) if enabled else {},
    }


def normalize_container_registry(registry: dict, cloud: str | None) -> dict:
    """Validate optional provider selection; credentials never belong in profiles."""
    if not isinstance(registry, dict):
        raise RegistryProfileError("container_registry must be a mapping")
    provider = registry.get("provider")
    if provider is not None and not isinstance(provider, str):
        raise RegistryProfileError("container_registry.provider must be a string")
    allowed = {"enabled", "provider", "images"} | {
        "aws_ecr": {"account_id", "region", "repository"},
        "dockerhub": {"namespace", "auth"},
        "gcp_artifact_registry": {"project", "location", "repository"},
    }.get(provider or "", set())
    if set(registry) - allowed:
        raise RegistryProfileError("container_registry contains unsupported fields")
    enabled = registry.get("enabled", False)
    if type(enabled) is not bool:
        raise RegistryProfileError("container_registry.enabled must be a boolean")
    if not enabled:
        return {"enabled": False}
    if provider == "gcp_artifact_registry":
        legacy = {key: value for key, value in registry.items() if key != "provider"}
        normalized = normalize_artifact_registry({"cloud": cloud, "artifact_registry": legacy})
        return dict(registry, images=normalized["artifact_registry_images"])
    if provider not in ("aws_ecr", "dockerhub"):
        raise RegistryProfileError("unsupported container_registry.provider")
    if provider == "aws_ecr":
        if cloud != "aws":
            raise RegistryProfileError("aws_ecr requires cloud: aws")
        for key, pattern in (
            ("account_id", r"[0-9]{12}"),
            ("region", r"(?!cn-)[a-z]{2}-[a-z]+-[0-9]+"),
            ("repository", r"[a-z0-9]+(?:[._/-][a-z0-9]+)*"),
        ):
            value = registry.get(key)
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise RegistryProfileError("invalid container_registry." + key)
        if not 2 <= len(registry["repository"]) <= 256:
            raise RegistryProfileError("invalid container_registry.repository length")
        host = f"{registry['account_id']}.dkr.ecr.{registry['region']}.amazonaws.com"
        pattern = re.escape(host + "/" + registry["repository"])
    else:
        namespace = registry.get("namespace")
        if not isinstance(namespace, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,254}", namespace):
            raise RegistryProfileError("invalid container_registry.namespace")
        if registry.get("auth", "anonymous") not in ("anonymous", "existing"):
            raise RegistryProfileError("dockerhub auth must be anonymous or existing")
        component = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
        pattern = re.escape("docker.io/" + namespace + "/") + component
    pattern += r"@sha256:[0-9a-f]{64}"
    images = registry.get("images", {})
    if not isinstance(images, dict):
        raise RegistryProfileError("container_registry.images must be a mapping")
    for name, image in images.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise RegistryProfileError("invalid container_registry workload name")
        if not isinstance(image, str) or not re.fullmatch(pattern, image):
            raise RegistryProfileError("images must be tag-free sha256 digests in the selected registry")
    result = dict(registry, enabled=True, images=dict(images))
    if provider == "dockerhub":
        result["auth"] = registry.get("auth", "anonymous")
    return result


def normalize_registries(profile: dict) -> dict:
    """Keep the legacy schema while making new distribution opt-in."""
    if "container_registry" in profile and "artifact_registry" in profile:
        raise RegistryProfileError("choose container_registry or artifact_registry, not both")
    registry = normalize_container_registry(profile.get("container_registry", {}), profile.get("cloud"))
    if registry.get("provider") == "gcp_artifact_registry":
        profile = dict(profile, artifact_registry={key: value for key, value in registry.items() if key != "provider"})
    return {**normalize_artifact_registry(profile), "container_registry": registry}


def normalize_saved_registries(params: dict, cloud: str | None) -> dict:
    registry = normalize_container_registry(params.get("container_registry", {}), cloud)
    legacy = normalize_saved_artifact_registry(params, cloud)
    if registry.get("provider") == "gcp_artifact_registry":
        expected = normalize_registries({"cloud": cloud, "container_registry": registry})
        if any(legacy[key] != expected[key] for key in legacy):
            raise RegistryProfileError("inconsistent saved GCP registry settings")
        return expected
    if registry["enabled"] and legacy["enable_artifact_registry"]:
        raise RegistryProfileError("conflicting saved registry selections")
    return {**legacy, "container_registry": registry}
