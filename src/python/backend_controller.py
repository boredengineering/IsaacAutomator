"""Authenticated, read-only remote attachment controller.

This module supplies trusted in-process adapters, not request-JSON verification
flags. A read receipt is deliberately NOT cloud-ready or mutation authority.
Cloud CLI diagnostics and credentials are never included in public exceptions.

Integration: make_read_service(...) returns ReadService. attach_remote() reads
and validates the exact protected manifest and saves only a local receipt;
load_attachment() independently validates an existing local receipt; read()
returns DeploymentState's native Terraform output observation. No caller source
checkout, providers or recovered workload secrets are required. Factories are
lazy: authenticated reads begin on those operations or verify_scope().

Explicit credential modes (environment is a TRUSTED embedding dependency,
never a request-JSON credential/verification field):
* aws-environment: already-present AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY and
  optional SESSION_TOKEN. CLI and Terraform share the frozen environment;
  shared credential/config files and metadata fallback are disabled. Backend
  and workload accounts must both match independent STS reads. Profiles,
  credential_process, SSO, role/web-identity and cross-account source selection
  are unsupported rather than assumed equivalent.
* gcp-gcloud-token: explicit active gcloud_account; obtain one short-lived token
  from that account, then feed identical token bytes to Terraform via
  GOOGLE_OAUTH_ACCESS_TOKEN and gcloud via per-command private token files.
  Files are removed after each CLI call; token refresh requires a new service.
  ADC equivalence, impersonation, hidden credential overrides, custom universes
  and storage/header overrides are refused. No login or key material inputs.
* azure-cli: public AzureCloud, CLI user auth only; default backend subscription
  must match, and workload subscription is explicitly inspected through ARM.
  Default/backend/workload selections must use the same CLI user in the
  descriptor tenant; mixed principals are refused. ARM auth alternatives
  are disabled; OIDC/MSI/SP and sovereign/custom clouds are unsupported.

Ambient cloud overrides outside the mode allowlist, plus nonempty proxies,
are refused. Unrelated environment entries are dropped; basic process/home/
locale variables are retained. CLI read-feature help is checked in a separate
credential-free temporary HOME. AWS requires working groff/mandoc help output;
missing help support fails closed. The receipt describes observed read-scope
and protective checks, not guaranteed future object access, independent
metadata-writer administration, or effective write/lease/restore permissions.

References: Terraform v1.10.0 internal/backend/remote-state/gcs/backend.go
(GOOGLE_OAUTH_ACCESS_TOKEN), gcloud auth print-access-token/config get-value,
and az storage blob download --help (--if-match). Native generation-pinned
object reads remain delegated to CLIObjectStore; no metadata write adapter is
exposed and no receipt, acknowledge flag or serialized value grants mutation.
"""
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

from src.python.terraform_runner import TerraformRunner
from src.python.backend_bootstrap import doctor, InspectionError
from src.python.backend_object_store import CLIObjectStore, ProtectedObjectCoordinator
from src.python.deployment_manifest import LocalManifestStore, DeploymentManifest, canonical
from src.python.deployment_state import DeploymentState, VerifiedScope, CapabilityError


class ControllerError(CapabilityError):
    """Unsupported, denied or unverified controller authentication/read scope."""


@dataclass(frozen=True)
class ReadVerification:
    status: str
    health_status: str
    unknown_checks: tuple
    mutation_allowed: bool = False


class ReadController:
    """One explicit identity and frozen credential-source selection."""
    def __init__(self, spec, scope, name, environment, *, gcloud_account=None, workload_resource_groups=()):
        self.spec = spec
        self.identity = spec.identity(scope, name)
        self._environment = dict(environment)
        self.receipt = None
        self._gcloud_account = gcloud_account
        self._workload_resource_groups = tuple(workload_resource_groups)
        self._read_features_checked = False

    def _raw(self, argv):
        try:
            result = self.object_run(argv, shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, env=dict(self._environment))
            if result.returncode:
                raise InspectionError("unknown")
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            raise InspectionError("unknown") from None

    def _read(self, argv):
        try:
            payload = json.loads(self._raw(argv))
            if not isinstance(payload, (dict, list)):
                raise ValueError()
            return payload
        except (OSError, subprocess.SubprocessError, ValueError):
            raise InspectionError("unknown") from None

    def verify_scope(self, identity):
        self.receipt = None
        if identity != self.identity:
            raise ControllerError("Selected controller identity changed")
        self._verify_read_transport()
        d = self.identity["destination"]
        if self.spec.cloud == "gcp":
            self._prepare_gcp()
        azure_principal = self._prepare_azure() if self.spec.cloud == "azure" else None
        health = doctor(self.spec, acknowledge_reads=True, transport=self._read,
                        workload_resource_groups=self._workload_resource_groups)
        required = {
            "aws": ("identity", "versioning", "public_access", "ownership", "encryption", "tls_only", "public_policy", "scoped_list_access"),
            "gcp": ("identity", "versioning", "uniform_access", "public_access", "soft_delete", "public_iam", "encryption"),
            "azure": ("identity", "encryption", "tls_only", "public_access", "entra_only", "private_container",
                      "versioning", "deletion_protection", "deleteRetentionPolicy", "containerDeleteRetentionPolicy"),
        }[self.spec.cloud]
        if (health.status != "partial" or any(health.checks.get(k) != "passed" for k in required)
                or any(v not in ("passed", "unknown", "not-applicable") for v in health.checks.values())):
            raise ControllerError("Backend owner/location/protection read verification failed")
        if self.spec.cloud == "gcp":
            for project_id in (d["project"], identity["target_scope"]):
                project = self._read(["gcloud", "projects", "describe", project_id, "--format=json", "--quiet"])
                if (not isinstance(project, dict) or project.get("projectId") != project_id
                        or not re.fullmatch(r"[1-9][0-9]*", str(project.get("projectNumber", "")))
                        or project.get("lifecycleState") != "ACTIVE"):
                    raise ControllerError("Backend/workload project ID/number is unverified")
            principal = "gcp:gcloud-account:" + self._gcloud_account
        elif self.spec.cloud == "azure":
            selected = self._azure_account(identity["target_scope"])
            if selected["user"]["name"] != azure_principal:
                raise ControllerError("Azure backend/workload CLI principals differ")
            workload = self._read(["az", "rest", "--method", "get", "--url",
                "https://management.azure.com/subscriptions/" + identity["target_scope"] + "?api-version=2022-12-01",
                "--subscription", identity["target_scope"], "--output", "json", "--only-show-errors"])
            if (not isinstance(workload, dict) or workload.get("subscriptionId") != identity["target_scope"]
                    or workload.get("tenantId") != d["tenant_id"] or workload.get("state") != "Enabled"):
                raise ControllerError("Independent ARM workload tenant/subscription is unverified")
            principal = "azure:cli-user:" + selected["user"]["name"]
        else:
            account = self._read(["aws", "sts", "get-caller-identity", "--region", d["region"],
                                  "--output", "json", "--no-cli-pager"])
            if not isinstance(account, dict) or account.get("Account") != identity["target_scope"] or not account.get("Arn"):
                raise ControllerError("Independent workload account does not match")
            principal = account["Arn"]
        self.receipt = ReadVerification("read-verified", health.status,
            tuple(sorted(k for k, v in health.checks.items() if v == "unknown")))
        return VerifiedScope(canonical(identity), principal)

    def _verify_read_transport(self):
        # Executable CLI precondition, not a request-JSON verified=True flag.
        # Help is offline, in a credential-free temporary HOME. No cloud probe
        # writes or test leases, and no promotion to write/CAS capability.
        if self._read_features_checked:
            return
        command, required = {
            "aws": (["aws", "s3api", "get-object", "help"], ("--expected-bucket-owner", "--if-match")),
            "gcp": (["gcloud", "storage", "cp", "--help"], ("--if-generation-match",)),
            "azure": (["az", "storage", "blob", "download", "--help"], ("--if-match",)),
        }[self.spec.cloud]
        try:
            with tempfile.TemporaryDirectory(prefix="isaac-cli-help-") as root:
                env = {"PATH": self._environment.get("PATH", os.defpath), "HOME": root,
                    "CLOUDSDK_CONFIG": root + "/gcloud", "AZURE_CONFIG_DIR": root + "/azure",
                    "AWS_CONFIG_FILE": "/dev/null", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
                    "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": "", "PAGER": ""}
                result = subprocess.run(command, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=60, env=env)
                text = result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout
                text = re.sub(r".\x08", "", text)  # manpage overstrike formatting
                if result.returncode or not all(flag in text for flag in required):
                    raise ValueError()
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            raise ControllerError("CLI read-condition support is unverified; install compatible CLI/help tools") from None
        self._read_features_checked = True

    def _azure_account(self, subscription=None):
        argv = ["az", "account", "show", "--output", "json", "--only-show-errors"]
        if subscription is not None:
            argv += ["--subscription", subscription]
        account = self._read(argv)
        d = self.identity["destination"]
        if (not isinstance(account, dict) or account.get("id") != (subscription or d["subscription_id"])
                or account.get("tenantId") != d["tenant_id"] or account.get("environmentName") != "AzureCloud"
                or account.get("state") != "Enabled" or account.get("user", {}).get("type") != "user"
                or not account.get("user", {}).get("name")):
            raise ControllerError("Azure CLI must select an enabled public-cloud user in the expected tenant/subscription")
        return account

    def _prepare_azure(self):
        cloud = self._read(["az", "cloud", "show", "--output", "json", "--only-show-errors"])
        if (not isinstance(cloud, dict) or cloud.get("name") != "AzureCloud"
                or cloud.get("endpoints", {}).get("resourceManager") != "https://management.azure.com/"
                or cloud.get("endpoints", {}).get("activeDirectory") != "https://login.microsoftonline.com/"
                or cloud.get("suffixes", {}).get("storageEndpoint") != "core.windows.net"):
            raise ControllerError("Only verified AzureCloud ARM/login/storage endpoints are supported")
        # Terraform's CLI authorizer can consult the CLI default subscription.
        # Refuse disagreement rather than executing az account set behind users.
        default = self._azure_account()
        backend = self._azure_account(self.identity["destination"]["subscription_id"])
        if default["user"]["name"] != backend["user"]["name"]:
            raise ControllerError("Azure default/backend CLI principals differ")
        return backend["user"]["name"]

    def _prepare_gcp(self):
        # gcloud and ADC are independent credential stores. Explicitly mint
        # from the selected gcloud account and pin that SAME short-lived token
        # in gcloud + Terraform environments. Never infer ADC from auth list.
        config = self._read(["gcloud", "config", "list", "--format=json", "--quiet"])
        if (not isinstance(config, dict) or config.get("api_endpoint_overrides")
                or config.get("auth") or config.get("proxy")
                or config.get("storage")
                or config.get("core", {}).get("universe_domain", "googleapis.com") != "googleapis.com"
                or config.get("core", {}).get("custom_ca_certs_file")):
            raise ControllerError("gcloud credential/endpoint configuration is unsupported")
        # Hidden Cloud SDK property is omitted even from config list --all.
        hidden = self._raw(["gcloud", "config", "get-value", "auth/credential_file_override", "--quiet"])
        if hidden.strip():
            raise ControllerError("Hidden gcloud credential override cannot prove the selected account")
        active = self._read(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=json", "--quiet"])
        if not isinstance(active, list) or len(active) != 1 or active[0].get("account") != self._gcloud_account:
            raise ControllerError("Select the explicit active gcloud account; ADC is not equivalent")
        if "GOOGLE_OAUTH_ACCESS_TOKEN" not in self._environment:
            raw = self._raw(["gcloud", "auth", "print-access-token", "--account=" + self._gcloud_account, "--quiet"])
            try:
                token = raw.decode("utf-8").strip() if isinstance(raw, bytes) else raw.strip()
                if not re.fullmatch(r"[A-Za-z0-9._~+/-]{16,16384}=*", token):
                    raise ValueError()
            except (UnicodeError, ValueError, AttributeError):
                raise ControllerError("gcloud token selection failed; diagnostics withheld") from None
            self._environment.update(GOOGLE_OAUTH_ACCESS_TOKEN=token)

    def object_run(self, argv, **kwargs):
        env = dict(self._environment)
        kwargs["env"] = env
        token = env.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        # CLI auth/config commands inspect the selected local source. Actual
        # resource reads use Cloud SDK's supported access_token_file setting;
        # there is NO CLOUDSDK_AUTH_ACCESS_TOKEN property. Token values never
        # appear in argv, receipts, logs or retained local manifests.
        if self.spec.cloud == "gcp" and token and argv[1] not in ("auth", "config"):
            with tempfile.TemporaryDirectory(prefix="isaac-gcloud-token-") as root:
                path = Path(root) / "token"
                path.touch(mode=0o600)
                path.write_text(token)
                env["CLOUDSDK_AUTH_ACCESS_TOKEN_FILE"] = str(path)
                return subprocess.run(argv, **kwargs)
        return subprocess.run(argv, **kwargs)

    def runner_factory(self, *, backend_spec, target_scope, deployment_name):
        if backend_spec.identity(target_scope, deployment_name) != self.identity:
            raise ControllerError("Runner identity differs from authenticated controller")
        self.verify_scope(self.identity)
        # TerraformRunner snapshots allowlisted sources during construction.
        # No repository, manifest URL, providers, variables or secret recovery.
        with tempfile.TemporaryDirectory(prefix="isaac-read-source-") as root:
            source = Path(root) / "read.tf.json"
            source.touch(mode=0o600)
            source.write_text(json.dumps({"terraform": {"required_version": ">= 1.10.0, < 2.0.0"}}))
            return TerraformRunner(source_root=root, source_files=[source.name],
                backend_spec=backend_spec, target_scope=target_scope, deployment_name=deployment_name,
                environment=dict(self._environment))

    def authorize(self, identity, operation):
        if operation not in ("attach", "read_relocation"):
            raise ControllerError("Read-only controller: mutation authorization is unavailable")
        self.verify_scope(identity)


class ReadOnlyObjectStore(CLIObjectStore):
    def __init__(self, *args, controller, **kwargs):
        super().__init__(*args, **kwargs)
        self._controller = controller

    def read(self, kind):
        self._controller.verify_scope(self.identity)
        return super().read(kind)

    def write(self, *args, **kwargs):
        raise ControllerError("Read-only transport cannot publish objects or claims")


class ReadService(DeploymentState):
    controller: ReadController

    def attach_remote(self):
        """Explicitly attach the exact protected manifest; only local writes."""
        self.controller.authorize(self.identity, "attach")
        stored = self.coordinator.store.read("manifest")
        if stored is None:
            raise ControllerError("Protected recovery descriptor is missing")
        return self.attach(DeploymentManifest.from_json(stored.data))

    def load_attachment(self):
        """Load a local receipt, verifying it against the explicit remote scope."""
        descriptor = self.local_store.load(self.deployment_name)
        self._snapshot(descriptor)
        self.descriptor = descriptor
        return descriptor


def make_read_service(*, backend_spec, target_scope, deployment_name,
                      local_manifest_root, credential_mode, acknowledge_reads=False,
                      environment=None, gcloud_account=None, workload_resource_groups=()):
    """Build explicit remote read dependencies; no login or implicit discovery."""
    if acknowledge_reads is not True:
        raise ControllerError("Authenticated reads require explicit acknowledgement")
    if {"s3": "aws-environment", "gcs": "gcp-gcloud-token", "azurerm": "azure-cli"}.get(backend_spec.backend) != credential_mode:
        raise ControllerError("Unsupported credential source; effective CLI/Terraform identity is unverified")
    ambient = dict(os.environ if environment is None else environment)
    allowed_auth = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                    "AWS_REGION", "AWS_DEFAULT_REGION"} if backend_spec.backend == "s3" else ({"CLOUDSDK_CONFIG"} if backend_spec.backend == "gcs" else {"AZURE_CONFIG_DIR", "ARM_SUBSCRIPTION_ID", "ARM_TENANT_ID", "ARM_ENVIRONMENT"})
    for key, value in ambient.items():
        if (key.startswith(("AWS_", "CLOUDSDK_", "GOOGLE_", "ARM_", "AZURE_"))
                and key not in allowed_auth) or (value and key.upper().endswith("_PROXY")):
            raise ControllerError("Ambient credential/endpoint override is unsupported")
    base = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    env = {key: value for key, value in ambient.items() if key in base | allowed_auth}
    if backend_spec.backend == "s3":
        if not env.get("AWS_ACCESS_KEY_ID") or not env.get("AWS_SECRET_ACCESS_KEY"):
            raise ControllerError("aws-environment requires existing ambient environment credentials")
        region = backend_spec.to_dict()["destination"]["region"]
        for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
            if key in env and env[key] != region:
                raise ControllerError("Ambient AWS region differs from the explicit backend region")
            env[key] = region
        env.update(AWS_CONFIG_FILE="/dev/null", AWS_SHARED_CREDENTIALS_FILE="/dev/null",
                   AWS_EC2_METADATA_DISABLED="true")
    elif backend_spec.backend == "azurerm":
        d = backend_spec.to_dict()["destination"]
        if not workload_resource_groups or d["resource_group_name"].casefold() in {g.casefold() for g in workload_resource_groups}:
            raise ControllerError("Explicit nonoverlapping workload resource groups are required")
        for key, expected in (("ARM_SUBSCRIPTION_ID", d["subscription_id"]), ("ARM_TENANT_ID", d["tenant_id"]), ("ARM_ENVIRONMENT", "public")):
            if key in env and env[key] != expected:
                raise ControllerError("Ambient ARM scope/cloud differs from the selected backend")
            env[key] = expected
        env.update(ARM_USE_CLI="true", ARM_USE_OIDC="false", ARM_USE_MSI="false", ARM_USE_AZUREAD="true")
    elif not isinstance(gcloud_account, str) or not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", gcloud_account):
        raise ControllerError("Select one explicit gcloud account; implicit ADC equivalence is unsupported")
    env.update(AWS_PAGER="", CLOUDSDK_CORE_DISABLE_PROMPTS="1")
    controller = ReadController(backend_spec, target_scope, deployment_name, env, gcloud_account=gcloud_account,
                                workload_resource_groups=workload_resource_groups)
    store = ReadOnlyObjectStore(backend_spec, target_scope, deployment_name, environment=env, run=controller.object_run, controller=controller)
    service = ReadService(backend_spec=backend_spec, target_scope=target_scope,
        deployment_name=deployment_name, local_store=LocalManifestStore(local_manifest_root),
        runner_factory=controller.runner_factory, coordinator=ProtectedObjectCoordinator(store, authorize=controller.authorize),
        verify_scope=controller.verify_scope)
    service.controller = controller
    return service
