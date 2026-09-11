"""Deterministic nonsecret storage proposals; no existence/adoption claims."""
import hashlib
import json
from src.python.terraform_backend import BackendSpec


def propose_backend(*, cloud, namespace, owner_scope, region=None, tenant_id=None):
    """Return native backend configuration to review before doctor/bootstrap.

    v1 proposal identities deliberately exclude application/source releases.
    Changing scope, namespace, region or tenant proposes DIFFERENT storage; it
    never migrates state. A global name can still be unavailable or pre-owned.
    """
    if cloud not in ("aws", "gcp", "azure"):
        raise ValueError("Backend proposals support AWS, GCP and Azure only")
    if (cloud != "aws" and region is not None) or (cloud != "azure" and tenant_id is not None):
        raise ValueError("Supply only identity fields used by the selected backend")
    identity = {"proposal_version": 1, "cloud": cloud, "namespace": namespace,
                "owner_scope": owner_scope, "region": region, "tenant_id": tenant_id}
    token = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()
    if cloud == "aws":
        destination = {"bucket": "isaac-state-" + token[:20], "region": region,
                       "owner_account_id": owner_scope, "key_prefix": "isaacautomator/v2"}
        backend = "s3"
    elif cloud == "gcp":
        destination = {"bucket": "isaac-state-" + token[:20], "project": owner_scope,
                       "prefix": "isaacautomator/v2"}
        backend = "gcs"
    else:
        destination = {"tenant_id": tenant_id, "subscription_id": owner_scope,
                       "resource_group_name": "isaac-backend-" + token[:20],
                       "storage_account_name": "isaacstate" + token[:14],
                       "container_name": "terraform-state", "key_prefix": "isaacautomator/v2"}
        backend = "azurerm"
    return BackendSpec.from_dict({"backend": backend, "namespace": namespace,
                                  "destination": destination}, cloud=cloud).to_dict()
