"""Ambient cloud identity and context auto-discovery.

Discovers project/account/subscription IDs, regions, and active caller principals
from the environment or cloud CLI configuration without prompting the user.
Never stores or serializes credentials.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess


@dataclass(frozen=True)
class CloudContext:
    cloud: str
    owner_scope: str
    region: str
    controller_principal: str


def _run_cli(argv, timeout=10):
    """Run a bounded CLI read command capturing JSON or text output safely."""
    try:
        res = subprocess.run(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def resolve_ambient_owner_scope(cloud: str, explicit: str | None = None) -> str | None:
    """Resolve workload or backend owner scope (project, account, or subscription)."""
    uuid_pat = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    if explicit:
        e = explicit.strip()
        if cloud == "gcp" and re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", e):
            return e
        elif cloud == "aws" and re.fullmatch(r"[0-9]{12}", e):
            return e
        elif cloud == "azure" and re.fullmatch(uuid_pat, e, re.IGNORECASE):
            return e.lower()
        return None

    if cloud == "gcp":
        for var in ("CLOUDSDK_CORE_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"):
            val = os.environ.get(var)
            if val and re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", val.strip()):
                return val.strip()
        val = _run_cli(["gcloud", "config", "get-value", "project"])
        if val and re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", val):
            return val

    elif cloud == "aws":
        val = os.environ.get("AWS_ACCOUNT_ID")
        if val and re.fullmatch(r"[0-9]{12}", val.strip()):
            return val.strip()
        val = _run_cli(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"])
        if val and re.fullmatch(r"[0-9]{12}", val):
            return val

    elif cloud == "azure":
        val = os.environ.get("AZURE_SUBSCRIPTION_ID")
        uuid_pat = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
        if val and re.fullmatch(uuid_pat, val.strip(), re.IGNORECASE):
            return val.strip().lower()
        out = _run_cli(["az", "account", "show", "--output", "json"])
        if out:
            try:
                data = json.loads(out)
                sub_id = data.get("id")
                if sub_id and re.fullmatch(uuid_pat, sub_id, re.IGNORECASE):
                    return sub_id.lower()
            except Exception:
                pass

    return None


def resolve_ambient_region(cloud: str, explicit: str | None = None, zone: str | None = None) -> str:
    """Resolve target region for the cloud provider."""
    if explicit and re.fullmatch(r"[a-z][a-z0-9-]{1,62}", explicit.strip()):
        return explicit.strip()

    if zone and re.fullmatch(r"[a-z][a-z0-9-]{1,62}", zone.strip()):
        # Truncate zone suffix (e.g., us-central1-a -> us-central1)
        z = zone.strip()
        last_dash = z.rfind("-")
        if last_dash > 0 and len(z) - last_dash == 2 and z[-1].isalpha():
            return z[:last_dash]
        return z

    if cloud == "gcp":
        for var in ("CLOUDSDK_COMPUTE_REGION", "GOOGLE_REGION", "GCP_REGION"):
            val = os.environ.get(var)
            if val and re.fullmatch(r"[a-z][a-z0-9-]{1,62}", val.strip()):
                return val.strip()
        val = _run_cli(["gcloud", "config", "get-value", "compute/region"])
        if val and val != "(unset)" and re.fullmatch(r"[a-z][a-z0-9-]{1,62}", val):
            return val
        return "us-central1"

    elif cloud == "aws":
        for var in ("AWS_DEFAULT_REGION", "AWS_REGION"):
            val = os.environ.get(var)
            if val and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*", val.strip()):
                return val.strip()
        val = _run_cli(["aws", "configure", "get", "region"])
        if val and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*", val):
            return val
        return "us-east-1"

    elif cloud == "azure":
        for var in ("AZURE_LOCATION", "AZURE_DEFAULT_REGION"):
            val = os.environ.get(var)
            if val and re.fullmatch(r"[a-z0-9]+", val.strip()):
                return val.strip()
        return "eastus"

    return "us-central1"


def resolve_ambient_principal(cloud: str, explicit: str | None = None, owner_scope: str | None = None) -> str:
    """Resolve controller principal for IAM membership on bootstrap state storage."""
    if explicit:
        return explicit.strip()

    if cloud == "gcp":
        val = os.environ.get("ISAAC_CONTROLLER_PRINCIPAL")
        if val:
            return val.strip()
        acct = _run_cli(["gcloud", "config", "get-value", "account"])
        if acct and "@" in acct:
            prefix = "serviceAccount" if acct.endswith(".gserviceaccount.com") else "user"
            return f"{prefix}:{acct}"
        if owner_scope:
            return f"serviceAccount:deployer@{owner_scope}.iam.gserviceaccount.com"
        return "user:operator@local"

    elif cloud == "aws":
        val = os.environ.get("ISAAC_CONTROLLER_PRINCIPAL")
        if val:
            return val.strip()
        arn = _run_cli(["aws", "sts", "get-caller-identity", "--query", "Arn", "--output", "text"])
        if arn and arn.startswith("arn:aws:"):
            return arn
        if owner_scope:
            return f"arn:aws:iam::{owner_scope}:root"
        return "arn:aws:iam::123456789012:role/IsaacOperator"

    elif cloud == "azure":
        val = os.environ.get("ISAAC_CONTROLLER_PRINCIPAL")
        uuid_pat = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
        if val and re.fullmatch(uuid_pat, val.strip()):
            return val.strip()
        # Query current user / service principal objectId
        out = _run_cli(["az", "ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"])
        if out and re.fullmatch(uuid_pat, out):
            return out
        return "00000000-0000-0000-0000-000000000000"

    return "user:operator@local"


def resolve_cloud_context(
    cloud: str,
    explicit_scope: str | None = None,
    explicit_region: str | None = None,
    zone: str | None = None,
    explicit_principal: str | None = None,
) -> CloudContext:
    """Resolve full ambient cloud context required for backend proposals and bootstrap."""
    scope = resolve_ambient_owner_scope(cloud, explicit_scope)
    region = resolve_ambient_region(cloud, explicit_region, zone)
    principal = resolve_ambient_principal(cloud, explicit_principal, scope)
    return CloudContext(
        cloud=cloud,
        owner_scope=scope or "default-scope",
        region=region,
        controller_principal=principal,
    )
