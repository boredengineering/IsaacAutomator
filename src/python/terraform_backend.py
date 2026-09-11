"""Pure controller-only Terraform backend descriptors (no lifecycle enablement).

Version policy: stable Terraform >=1.10.0,<2 for ALL remote adapters (one
conservative common baseline); local-only compatibility remains >=1.3.5,<2.
This is a feature gate, not a claim that every future 1.x release was tested.
Terraform 1.10 introduced S3 lockfiles, initially labelled experimental.
No DynamoDB fallback. Provider/bootstrap compatibility is a separate gate.

This descriptor uses a deliberately conservative ASCII naming subset, not
every name accepted by each cloud. Namespace/deployment/prefix components are
lowercase; Azure context UUIDs are canonical lowercase. Remote prefixes are
explicit roots, followed by namespace/cloud/target/deployment/terraform:
S3/Azure append .tfstate, GCS appends /default.tfstate. These are NEW v2
identities only, never a mechanism to guess or relocate an existing v1 object.

Cross-account/project/subscription storage within the SAME cloud is explicit:
destination describes storage, target_scope describes the workload. The S3
allowed_account_ids field restricts the authenticated backend account; it does
not independently prove bucket ownership. Ownership, IAM, existing KMS key
availability/permissions and Azure ancestor isolation need authorized preflight.
GCS project is descriptor metadata, not a Terraform backend configuration field.
OIDC/MSI/ADC/SSO configuration stays ambient (e.g. ARM_USE_OIDC), never serialized.
The future runner must filter inherited credential overrides and TF_WORKSPACE;
this pure module neither reads nor sanitizes the process environment.

Backend fields/naming verified against HashiCorp's versioned 1.10.0 docs:
https://github.com/hashicorp/terraform/releases/tag/v1.10.0
https://github.com/hashicorp/terraform/blob/v1.10.0/website/docs/language/backend/s3.mdx
https://github.com/hashicorp/terraform/blob/v1.10.0/website/docs/language/backend/gcs.mdx
https://github.com/hashicorp/terraform/blob/v1.10.0/website/docs/language/backend/azurerm.mdx
https://github.com/hashicorp/terraform/blob/v1.10.0/website/docs/language/backend/local.mdx
"""
from dataclasses import dataclass
import json
import re

_UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"


def validate_terraform_version(version, backend):
    """Accept a bare stable X.Y.Z version, or raise a nonsecret ValueError."""
    if not isinstance(backend, str) or backend not in ("local", "s3", "gcs", "azurerm"):
        raise ValueError("Unsupported Terraform backend")
    minimum = (1, 3, 5) if backend == "local" else (1, 10, 0)
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Terraform version must be a bare stable X.Y.Z release")
    parsed = tuple(map(int, version.split(".")))
    if parsed[0] != 1 or parsed < minimum:
        floor = ".".join(map(str, minimum))
        raise ValueError(f"{backend} requires stable Terraform >= {floor}, < 2.0.0; select a compatible binary explicitly")


def _block(value, allowed, label):
    if not isinstance(value, dict) or any(key not in allowed for key in value):
        raise ValueError(f"{label} must be an allowlisted mapping; unknown fields/credentials are forbidden")
    return value


def _component(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", value) or value == "auto":
        raise ValueError(f"{label} must be an explicit safe lowercase component (1-63 characters)")
    return value


def _match(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value) or value == "auto":
        raise ValueError(f"Invalid or missing {label}; supply an explicit nonsecret identifier")
    return value


def _prefix(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError("Invalid destination prefix")
    for part in value.split("/"):
        _component(part, "prefix component")


def _bucket(value):
    _match(value, r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", "bucket")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) for part in value.split(".")) or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", value):
        raise ValueError("Invalid bucket name")


@dataclass(frozen=True, init=False)
class BackendSpec:
    """Validated immutable value; construct only with from_dict()."""
    cloud: str
    backend: str = "local"
    namespace: str = "default"
    timeout_seconds: int = 120
    _destination: tuple = ()

    def __init__(self, *args, **kwargs):
        raise TypeError("Construct BackendSpec with BackendSpec.from_dict(data, cloud=...)")

    @classmethod
    def from_dict(cls, data, *, cloud):
        """Normalize an already-parsed terraform_state block, not a profile.

        None/{} mean local. Remote destinations and namespace are mandatory;
        no resource discovery, legacy-prefix adoption, auth or filesystem I/O.
        Mapping parsers MUST reject duplicate keys before calling this method:
        duplicates discarded by a YAML/JSON loader cannot be recovered here.
        from_json() supplies a strict JSON loader for backend config files.
        """
        if not isinstance(cloud, str) or cloud not in ("aws", "gcp", "azure", "alicloud"):
            raise ValueError("Unsupported deployment cloud")
        data = _block({} if data is None else data,
                      {"schema_version", "backend", "namespace", "workspace", "destination", "locking", "authentication"},
                      "BackendSpec")
        version = data.get("schema_version", 1)
        if type(version) is not int or version != 1:
            raise ValueError("BackendSpec requires schema_version 1")
        backend = data.get("backend", "local")
        if not isinstance(backend, str) or backend not in ("local", "s3", "gcs", "azurerm"):
            raise ValueError("Unsupported backend")
        if backend != "local" and {"s3": "aws", "gcs": "gcp", "azurerm": "azure"}[backend] != cloud:
            raise ValueError("Backend must match deployment cloud; cross-cloud remote state is unsupported")
        if backend == "local" and "destination" in data:
            raise ValueError("Local backend must omit destination")
        if data.get("workspace", "default") != "default":
            raise ValueError("Only the default workspace is supported")
        namespace = _component(data.get("namespace", "default" if backend == "local" else None), "namespace")
        locking = _block(data.get("locking", {}), {"mode", "timeout_seconds"}, "locking")
        if locking.get("mode", "native") != "native":
            raise ValueError("Only native locking is supported")
        timeout = locking.get("timeout_seconds", 120)
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError("locking.timeout_seconds must be an integer from 1 to 3600")
        auth = _block(data.get("authentication", {}), {"mode"}, "authentication")
        if auth.get("mode", "ambient") != "ambient":
            raise ValueError("Only ambient authentication is supported; supply OIDC through the environment")
        destination = data.get("destination", {})
        if backend == "s3":
            destination = _block(destination, {"bucket", "region", "owner_account_id", "key_prefix", "kms_key_id"}, "S3 destination")
            _bucket(destination.get("bucket"))
            _match(destination.get("region"), r"[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*", "S3 region")
            _match(destination.get("owner_account_id"), r"[0-9]{12}", "S3 owner_account_id")
            _prefix(destination.get("key_prefix"))
            if "kms_key_id" in destination:
                _match(destination["kms_key_id"],
                       r"arn:aws(?:-us-gov|-cn)?:kms:[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*:[0-9]{12}:key/(?:" + _UUID + r"|mrk-[0-9a-f]{32})",
                       "S3 KMS key ARN")
        elif backend == "gcs":
            destination = _block(destination, {"bucket", "project", "prefix", "kms_encryption_key"}, "GCS destination")
            _bucket(destination.get("bucket"))
            _match(destination.get("project"), r"[a-z][a-z0-9-]{4,28}[a-z0-9]", "GCS project ID")
            _prefix(destination.get("prefix"))
            if "kms_encryption_key" in destination:
                _match(destination["kms_encryption_key"],
                       r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z][a-z0-9-]{0,62}/keyRings/[A-Za-z0-9_-]{1,63}/cryptoKeys/[A-Za-z0-9_-]{1,63}",
                       "GCS KMS CryptoKey resource name")
        elif backend == "azurerm":
            destination = _block(destination, {"tenant_id", "subscription_id", "resource_group_name",
                                                "storage_account_name", "container_name", "key_prefix"}, "Azure destination")
            _match(destination.get("tenant_id"), _UUID, "Azure tenant_id")
            _match(destination.get("subscription_id"), _UUID, "Azure subscription_id")
            _match(destination.get("resource_group_name"), r"[A-Za-z0-9_-]{1,90}", "Azure resource_group_name")
            _match(destination.get("storage_account_name"), r"[a-z0-9]{3,24}", "Azure storage_account_name")
            container = _match(destination.get("container_name"), r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", "Azure container_name")
            if "--" in container:
                raise ValueError("Azure container_name cannot contain consecutive hyphens")
            _prefix(destination.get("key_prefix"))
        spec = object.__new__(cls)
        for name, value in (("cloud", cloud), ("backend", backend), ("namespace", namespace),
                            ("timeout_seconds", timeout), ("_destination", tuple(sorted(destination.items())))):
            object.__setattr__(spec, name, value)
        return spec

    @classmethod
    def from_json(cls, text, *, cloud):
        """Parse JSON without accepting last-key-wins duplicate blocks."""
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate BackendSpec field or block")
                result[key] = value
            return result

        if not isinstance(text, str):
            raise ValueError("BackendSpec JSON must be text")
        try:
            data = json.loads(text, object_pairs_hook=unique_object)
        except json.JSONDecodeError:
            raise ValueError("Invalid BackendSpec JSON") from None
        return cls.from_dict(data, cloud=cloud)

    def to_dict(self):
        result = {"schema_version": 1, "backend": self.backend,
                "namespace": self.namespace, "workspace": "default",
                "locking": {"mode": "native", "timeout_seconds": self.timeout_seconds},
                "authentication": {"mode": "ambient"}}
        if self.backend != "local":
            result["destination"] = dict(self._destination)
        return result

    def canonical_json(self):
        """Canonical nonsecret configuration JSON (cloud is in identity())."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def identity(self, target_scope, deployment_name):
        """Return a detached nonsecret identity mapping, including exact object.

        Serialize identities with json.dumps(..., sort_keys=True,
        separators=(",", ":"), ensure_ascii=True) for stable digest input.
        Local object_key preserves the legacy logical relative path; the actual
        approved absolute root is caller-owned, not discovered by this module.
        """
        _component(deployment_name, "deployment_name")
        patterns = {"aws": r"[0-9]{12}", "gcp": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
                    "azure": _UUID, "alicloud": r"[0-9]{1,32}"}
        # Local state is identified and locked by its approved absolute path.
        # Do not authenticate merely to invent a scope for an offline/local
        # operation. Remote identities always require an explicit real scope.
        if self.backend != "local" or target_scope is not None:
            _match(target_scope, patterns[self.cloud], "target_scope")
        scope_component = "local" if target_scope is None else target_scope
        suffix = f"{self.namespace}/{self.cloud}/{scope_component}/{deployment_name}/terraform"
        destination = dict(self._destination)
        if self.backend == "local":
            object_key = f"state/{deployment_name}/.tfstate"
        else:
            root = destination["prefix" if self.backend == "gcs" else "key_prefix"]
            object_key = f"{root}/{suffix}" + ("/default.tfstate" if self.backend == "gcs" else ".tfstate")
        return {"schema_version": 1, "backend": self.backend, "cloud": self.cloud,
                "namespace": self.namespace, "workspace": "default",
                "target_scope": target_scope, "deployment_name": deployment_name,
                "logical_path": f"isaacautomator/v2/{suffix}",
                "object_key": object_key,
                "destination": destination}

    def backend_config(self, target_scope, deployment_name, local_state_path=None):
        """Return ONLY init fields; timeout is a runner CLI option, not a field.

        Local requires the caller's pinned absolute canonical path. This pure
        lexical check cannot prove containment or detect symlinks: the runner
        MUST enforce the approved state root and symlink safety before use.
        Never default local state into a disposable Terraform staging directory.
        """
        identity = self.identity(target_scope, deployment_name)
        if self.backend == "local":
            path = _match(local_state_path, r"/(?:[\w. -]+/)*[\w. -]+", "absolute local_state_path")
            parts = path.split("/")[1:]
            if any(part in (".", "..") for part in parts) or parts[-2:] != [deployment_name, ".tfstate"]:
                raise ValueError("local_state_path must end in deployment_name/.tfstate without traversal")
            return {"path": path}
        if local_state_path is not None:
            raise ValueError("local_state_path is incompatible with a remote backend")
        destination = dict(self._destination)
        if self.backend == "gcs":
            result = {"bucket": destination["bucket"], "prefix": identity["object_key"][:-len("/default.tfstate")]}
            if "kms_encryption_key" in destination:
                result["kms_encryption_key"] = destination["kms_encryption_key"]
            return result
        if self.backend == "azurerm":
            return {**{key: value for key, value in destination.items() if key != "key_prefix"},
                    "key": identity["object_key"], "use_azuread_auth": True}
        result = {"bucket": destination["bucket"], "region": destination["region"],
                "key": identity["object_key"], "allowed_account_ids": [destination["owner_account_id"]],
                "encrypt": True, "use_lockfile": True}
        if "kms_key_id" in destination:
            result["kms_key_id"] = destination["kms_key_id"]
        return result
