"""Concrete controller contracts; cloud subprocesses are always synthetic."""
import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.python.terraform_backend import BackendSpec
from src.python.deployment_manifest import canonical, DeploymentManifest
from src.python.terraform_runner import TerraformRunner
from src.python.deployment_state import StateStatus
from src.python.deployment_state import CapabilityError, VerifiedScope

ACCOUNT = "123456789012"


def aws_spec():
    return BackendSpec.from_dict({"backend": "s3", "namespace": "test", "destination": {
        "bucket": "test-state", "region": "us-east-1", "owner_account_id": ACCOUNT,
        "key_prefix": "state"}}, cloud="aws")


def aws_environment():
    # Synthetic values, never inspect the real controller credentials in tests.
    return {"PATH": "/usr/bin", "AWS_ACCESS_KEY_ID": "SYNTHETIC",
            "AWS_SECRET_ACCESS_KEY": "SYNTHETIC-SECRET"}


class AWSCLI:
    def __init__(self):
        self.calls = []
        self.account = ACCOUNT
        self.versioning = "Enabled"
        self.objects = {}

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        operation = argv[2]
        if argv[-1] == "help":
            return subprocess.CompletedProcess(argv, 0, b"--expected-bucket-owner --if-match", b"")
        if operation == "get-object":
            key = argv[argv.index("--key") + 1]
            if key not in self.objects:
                return subprocess.CompletedProcess(argv, 1, b"", b"NoSuchKey")
            Path(argv[-1]).write_bytes(self.objects[key])
            return subprocess.CompletedProcess(argv, 0, b'{"ETag":"stable"}', b"")
        responses = {
            "get-caller-identity": {"Account": self.account, "Arn": "arn:aws:iam::" + self.account + ":user/controller"},
            "get-bucket-location": {"LocationConstraint": None},
            "get-bucket-versioning": {"Status": self.versioning},
            "get-public-access-block": {"PublicAccessBlockConfiguration": {k: True for k in
                ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")}},
            "get-bucket-ownership-controls": {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}},
            "get-bucket-encryption": {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}},
            "get-bucket-policy": {"Policy": json.dumps({"Statement": [{"Effect": "Deny", "Principal": "*", "Action": "s3:*", "Resource": ["arn:aws:s3:::test-state", "arn:aws:s3:::test-state/*"], "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]})},
            "get-bucket-policy-status": {"PolicyStatus": {"IsPublic": False}},
            "list-objects-v2": {},
        }
        if operation not in responses:
            raise AssertionError("Unexpected cloud command: " + repr(argv))
        return subprocess.CompletedProcess(argv, 0, json.dumps(responses[operation]).encode(), b"")


class ControllerTests(unittest.TestCase):
    def module(self):
        self.assertTrue(Path("src/python/backend_controller.py").is_file(), "concrete controller is missing")
        return importlib.import_module("src.python.backend_controller")

    def test_aws_verified_read_receipt_never_promotes_partial_doctor_to_mutation(self):
        bc = self.module()
        cli = AWSCLI()
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", cli):
            service = bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                deployment_name="demo", local_manifest_root=Path(root) / "manifests",
                credential_mode="aws-environment", environment=aws_environment(), acknowledge_reads=True)
            scope = service.verify_scope(service.identity)
            self.assertIsInstance(scope, VerifiedScope)
            self.assertEqual(scope.identity, canonical(service.identity))
            self.assertEqual(service.controller.receipt.status, "read-verified")
            self.assertEqual(service.controller.receipt.health_status, "partial")
            self.assertIn("state_lock_write_permissions", service.controller.receipt.unknown_checks)
            self.assertFalse(service.controller.receipt.mutation_allowed)
            service.controller.authorize(service.identity, "attach")
            with self.assertRaises(CapabilityError):
                service.require_capability("apply")
            with self.assertRaises(bc.ControllerError):
                service.controller.authorize(service.identity, "claim_new")
            sts = [argv for argv, _ in cli.calls if argv[1:3] == ["sts", "get-caller-identity"]]
            self.assertGreaterEqual(len(sts), 2, "workload identity needs an independent STS read")
            for argv, kwargs in cli.calls:
                if argv[-1] == "help":
                    continue
                self.assertFalse(kwargs["shell"])
                self.assertEqual(kwargs["env"]["AWS_CONFIG_FILE"], "/dev/null")
                self.assertEqual(kwargs["env"]["AWS_SHARED_CREDENTIALS_FILE"], "/dev/null")
                self.assertEqual(argv[argv.index("--region") + 1], "us-east-1")

    def test_ambient_overrides_are_refused_before_any_process(self):
        bc = self.module()
        overrides = ("AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL_STS",
            "CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE", "GOOGLE_STORAGE_CUSTOM_ENDPOINT",
            "ARM_ENDPOINT", "ARM_METADATA_HOST", "AZURE_STORAGE_CONNECTION_STRING",
            "AWS_PROFILE", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CA_BUNDLE",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI", "HTTPS_PROXY")
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run") as run:
            for key in overrides:
                with self.subTest(key=key), self.assertRaises(bc.ControllerError):
                    bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                        deployment_name="demo", local_manifest_root=Path(root),
                        credential_mode="aws-environment", acknowledge_reads=True,
                        environment={**aws_environment(), key: "UNTRUSTED-SECRET-VALUE"})
            run.assert_not_called()

    def test_native_backend_only_attach_reload_outputs_and_no_remote_writes(self):
        bc = self.module()
        cli = AWSCLI()
        lineage = "11111111-1111-4111-8111-111111111111"
        manifest = DeploymentManifest.create(backend_spec=aws_spec(), target_scope=ACCOUNT,
            deployment_name="demo", lineage=lineage, serial=3, addresses=[])
        state = {"version": 4, "lineage": lineage, "serial": 3, "resources": [],
            "outputs": {"ip": {"type": "string", "value": "192.0.2.1", "sensitive": False}}}
        key = manifest.identity["object_key"]
        cli.objects = {key: json.dumps(state).encode(),
            key + ".isaac-manifest-v1.json": manifest.canonical_json().encode(),
            key + ".isaac-claim-v1.json": json.dumps({"schema_version": 1, "identity": manifest.identity,
                "owner_id": lineage, "lineage": lineage, "status": "active"}).encode()}
        commands = []
        environments = []
        def native_command(runner, argv, **kwargs):
            commands.append(argv)
            environments.append(dict(runner._environment))
            runner._require_context(initialized=argv[0] not in ("version", "init"))
            sources = [p for p in runner.staged_root.iterdir() if p.name.endswith(".tf.json")]
            self.assertEqual({p.name for p in sources}, {"read.tf.json", "runner_override.tf.json"})
            self.assertEqual(json.loads((runner.staged_root / "read.tf.json").read_text()), {"terraform": {"required_version": ">= 1.10.0, < 2.0.0"}})
            if argv[0] == "version":
                return 0, b'{"terraform_version":"1.10.5"}'
            if argv[0] == "init":
                (runner.data_dir / "terraform.tfstate").write_text(json.dumps({"backend": {"type": "s3", "config": runner._config}}))
                return 0, b""
            if argv == ["state", "pull"]:
                return 0, json.dumps(state).encode()
            if argv == ["output", "-json", "-no-color"]:
                return 0, json.dumps(state["outputs"]).encode()
            self.fail("Mutation/provider command in output-only context")
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", cli), patch.object(TerraformRunner, "_execute", native_command):
            def make():
                return bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                    deployment_name="demo", local_manifest_root=Path(root) / "manifests",
                    credential_mode="aws-environment", environment=aws_environment(), acknowledge_reads=True)
            service = make()
            self.assertTrue(callable(service.runner_factory), "native read runner is missing")
            self.assertEqual(service.attach_remote(), manifest)
            other = make()
            self.assertEqual(other.load_attachment(), manifest)
            observed = other.read()
            self.assertEqual(observed.status, StateStatus.REACHABLE_EMPTY)
            self.assertEqual(observed.outputs.values, {"ip": "192.0.2.1"})
            self.assertIn(["output", "-json", "-no-color"], commands)
            self.assertFalse((Path(root) / "manifests/demo/.tfstate").exists())
            for env in environments:
                self.assertEqual(env["AWS_CONFIG_FILE"], "/dev/null")
                self.assertEqual(env["AWS_ACCESS_KEY_ID"], "SYNTHETIC")
            with self.assertRaises(bc.ControllerError):
                service.coordinator.store.write("manifest", b"{}")

    def test_gcp_explicit_cli_token_is_shared_with_terraform_not_ambient_adc(self):
        bc = self.module()
        spec = BackendSpec.from_dict({"backend": "gcs", "namespace": "test", "destination": {
            "bucket": "test-state", "project": "backend-project", "prefix": "state"}}, cloud="gcp")
        calls = []
        def gcloud(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[1] in ("projects", "storage") and argv[-1] != "--help":
                self.assertIn("CLOUDSDK_AUTH_ACCESS_TOKEN_FILE", kwargs["env"], "gcloud requires a supported token-file selector")
                path = Path(kwargs["env"]["CLOUDSDK_AUTH_ACCESS_TOKEN_FILE"])
                self.assertEqual(path.read_text(), kwargs["env"]["GOOGLE_OAUTH_ACCESS_TOKEN"])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            op = argv[1:4]
            if argv[-1] == "--help":
                return subprocess.CompletedProcess(argv, 0, b"--if-generation-match", b"")
            if op[:2] == ["config", "get-value"]:
                return subprocess.CompletedProcess(argv, 0, b"", b"(unset)")
            if op[:2] == ["config", "list"]:
                result = {"core": {"account": "controller@example.com"}}
            elif op[:2] == ["auth", "print-access-token"]:
                self.assertIn("--account=controller@example.com", argv)
                return subprocess.CompletedProcess(argv, 0, b"SYNTHETIC-OAUTH-TOKEN\n", b"")
            elif op[:2] == ["auth", "list"]:
                result = [{"account": "controller@example.com", "status": "ACTIVE"}]
            elif op[:2] == ["projects", "describe"]:
                result = {"projectId": op[2], "projectNumber": "111" if op[2] == "backend-project" else "222", "lifecycleState": "ACTIVE"}
            elif op == ["storage", "buckets", "describe"]:
                result = {"name": "test-state", "projectNumber": "111", "versioning": {"enabled": True},
                    "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}, "publicAccessPrevention": "enforced"},
                    "softDeletePolicy": {"retentionDurationSeconds": "604800"}}
            elif op == ["storage", "buckets", "get-iam-policy"]:
                result = {"bindings": []}
            elif op == ["storage", "objects", "describe"]:
                result = {"generation": "42"}
            elif op[:2] == ["storage", "cp"]:
                self.assertTrue(argv[-2].endswith("#42"))
                Path(argv[-1]).write_bytes(b"synthetic-state-bytes")
                result = {}
            else:
                self.fail("Unexpected gcloud command: " + repr(argv))
            return subprocess.CompletedProcess(argv, 0, json.dumps(result).encode(), b"")
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", gcloud):
            service = bc.make_read_service(backend_spec=spec, target_scope="workload-project", deployment_name="demo",
                local_manifest_root=Path(root), credential_mode="gcp-gcloud-token", gcloud_account="controller@example.com",
                environment={"PATH": "/usr/bin"}, acknowledge_reads=True)
            scope = service.verify_scope(service.identity)
            self.assertIn("controller@example.com", scope.principal)
            self.assertEqual(service.controller.receipt.status, "read-verified")
            self.assertEqual(service.coordinator.store.read("state").data, b"synthetic-state-bytes")
            runner = service.runner_factory(backend_spec=spec, target_scope="workload-project", deployment_name="demo")
            self.assertEqual(runner._environment["GOOGLE_OAUTH_ACCESS_TOKEN"], "SYNTHETIC-OAUTH-TOKEN")
            for argv, kwargs in calls:
                if argv[1] in ("projects", "storage") and argv[-1] != "--help":
                    self.assertFalse(Path(kwargs["env"]["CLOUDSDK_AUTH_ACCESS_TOKEN_FILE"]).exists())
            self.assertTrue(any(argv[1:4] == ["projects", "describe", "workload-project"] for argv, _ in calls))
            self.assertNotIn("SYNTHETIC-OAUTH-TOKEN", repr(service.controller.receipt))
            with self.assertRaises(bc.ControllerError):
                bc.make_read_service(backend_spec=spec, target_scope="workload-project", deployment_name="demo",
                    local_manifest_root=Path(root), credential_mode="gcp-adc", acknowledge_reads=True, environment={})
            def invalid_backend_number(argv, **kwargs):
                response = gcloud(argv, **kwargs)
                if argv[1:4] in (["projects", "describe", "backend-project"], ["storage", "buckets", "describe"]):
                    payload = json.loads(response.stdout)
                    payload["projectNumber"] = "not-a-number"
                    response.stdout = json.dumps(payload).encode()
                return response
            with patch.object(bc.subprocess, "run", invalid_backend_number), self.assertRaises(bc.ControllerError):
                service.verify_scope(service.identity)

    def test_azure_cli_scope_uses_public_arm_and_explicit_subscriptions(self):
        bc = self.module()
        subscription = "11111111-1111-4111-8111-111111111111"
        target = "22222222-2222-4222-8222-222222222222"
        tenant = "33333333-3333-4333-8333-333333333333"
        spec = BackendSpec.from_dict({"backend": "azurerm", "namespace": "test", "destination": {
            "subscription_id": subscription, "tenant_id": tenant, "resource_group_name": "backend-rg",
            "storage_account_name": "teststate", "container_name": "state", "key_prefix": "state"}}, cloud="azure")
        account_id = "/subscriptions/" + subscription + "/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/teststate"
        calls = []
        def az(argv, **kwargs):
            calls.append((argv, kwargs))
            op = argv[1:4]
            if argv[-1] == "--help":
                return subprocess.CompletedProcess(argv, 0, b"--if-match", b"")
            if op[:2] == ["cloud", "show"]:
                result = {"name": "AzureCloud", "endpoints": {"resourceManager": "https://management.azure.com/", "activeDirectory": "https://login.microsoftonline.com/"}, "suffixes": {"storageEndpoint": "core.windows.net"}}
            elif op[:2] == ["account", "show"]:
                selected = argv[argv.index("--subscription") + 1] if "--subscription" in argv else subscription
                result = {"id": selected, "tenantId": tenant, "environmentName": "AzureCloud", "state": "Enabled", "user": {"name": "controller@example.com", "type": "user"}}
            elif op == ["storage", "account", "show"]:
                result = {"id": account_id, "kind": "StorageV2", "encryption": {"services": {"blob": {"enabled": True}}}, "enableHttpsTrafficOnly": True,
                    "minimumTlsVersion": "TLS1_2", "allowBlobPublicAccess": False, "allowSharedKeyAccess": False}
            elif op == ["storage", "blob", "service-properties"]:
                result = {"isVersioningEnabled": True, "deleteRetentionPolicy": {"enabled": True, "days": 7}, "containerDeleteRetentionPolicy": {"enabled": True, "days": 7}}
            elif op == ["storage", "container", "show"]:
                result = {"name": "state", "properties": {"publicAccess": None}}
            elif op == ["storage", "blob", "show"]:
                result = {"properties": {"etag": "stable"}}
            elif op == ["storage", "blob", "download"]:
                self.assertEqual(argv[argv.index("--if-match") + 1], "stable")
                self.assertEqual(argv[argv.index("--auth-mode") + 1], "login")
                Path(argv[argv.index("--file") + 1]).write_bytes(b"synthetic-state-bytes")
                result = {}
            elif op[:2] == ["lock", "list"]:
                result = [{"level": "CanNotDelete", "id": account_id + "/providers/Microsoft.Authorization/locks/protect"}]
            elif argv[1] == "rest":
                self.assertEqual(argv[argv.index("--url") + 1], "https://management.azure.com/subscriptions/" + target + "?api-version=2022-12-01")
                self.assertEqual(argv[argv.index("--subscription") + 1], target)
                result = {"subscriptionId": target, "tenantId": tenant, "state": "Enabled"}
            else:
                self.fail("Unexpected Azure command: " + repr(argv))
            return subprocess.CompletedProcess(argv, 0, json.dumps(result).encode(), b"")
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", az):
            service = bc.make_read_service(backend_spec=spec, target_scope=target, deployment_name="demo",
                local_manifest_root=Path(root), credential_mode="azure-cli", workload_resource_groups=("workload-rg",),
                environment={"PATH": "/usr/bin"}, acknowledge_reads=True)
            service.verify_scope(service.identity)
            self.assertEqual(service.coordinator.store.read("state").data, b"synthetic-state-bytes")
            self.assertTrue(any(argv[1] == "rest" for argv, _ in calls))
            runner = service.runner_factory(backend_spec=spec, target_scope=target, deployment_name="demo")
            self.assertEqual(runner._environment["ARM_SUBSCRIPTION_ID"], subscription)
            self.assertEqual(runner._environment["ARM_TENANT_ID"], tenant)
            self.assertEqual(runner._environment["ARM_USE_OIDC"], "false")
            self.assertEqual(runner._environment["ARM_USE_MSI"], "false")
            self.assertEqual(runner._environment["ARM_ENVIRONMENT"], "public")
            for selection in ("default", subscription, target):
                def mismatched_principal(argv, **kwargs):
                    response = az(argv, **kwargs)
                    if argv[1:3] == ["account", "show"]:
                        selected = argv[argv.index("--subscription") + 1] if "--subscription" in argv else "default"
                        if selected == selection:
                            payload = json.loads(response.stdout)
                            payload["user"]["name"] = "different-user@example.com"
                            response.stdout = json.dumps(payload).encode()
                    return response
                with self.subTest(selection=selection), patch.object(bc.subprocess, "run", mismatched_principal):
                    with self.assertRaises(bc.ControllerError):
                        service.verify_scope(service.identity)
                    self.assertIsNone(service.controller.receipt, "mixed principals cannot receive read verification")
                    with self.assertRaises(bc.ControllerError):
                        service.coordinator.store.read("state")
                    with self.assertRaises(bc.ControllerError):
                        service.runner_factory(backend_spec=spec, target_scope=target, deployment_name="demo")
            self.assertEqual(service.verify_scope(service.identity).principal, "azure:cli-user:controller@example.com")
            self.assertFalse(service.controller.receipt.mutation_allowed)

    def test_unverified_read_cli_condition_refuses_before_authenticated_reads(self):
        bc = self.module()
        cli = AWSCLI()
        def no_features(argv, **kwargs):
            if argv[-1] == "help":
                self.assertNotIn("AWS_ACCESS_KEY_ID", kwargs["env"])
                return subprocess.CompletedProcess(argv, 0, b"unknown CLI", b"")
            return cli(argv, **kwargs)
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", no_features):
            service = bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                deployment_name="demo", local_manifest_root=Path(root),
                credential_mode="aws-environment", environment=aws_environment(), acknowledge_reads=True)
            with self.assertRaises(bc.ControllerError):
                service.verify_scope(service.identity)
            self.assertIsNone(service.controller.receipt)
            self.assertEqual(cli.calls, [])

    def test_raw_store_and_native_runner_cannot_bypass_scope_verification(self):
        bc = self.module()
        cli = AWSCLI()
        cli.versioning = "Suspended"
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", cli):
            service = bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                deployment_name="demo", local_manifest_root=Path(root),
                credential_mode="aws-environment", environment=aws_environment(), acknowledge_reads=True)
            for action in (lambda: service.coordinator.store.read("state"),
                           lambda: service.runner_factory(backend_spec=aws_spec(), target_scope=ACCOUNT, deployment_name="demo")):
                with self.subTest(action=action), self.assertRaises(bc.ControllerError):
                    action()
            self.assertFalse(any(argv[2] == "get-object" and argv[-1] != "help" for argv, _ in cli.calls))

    def test_aws_region_override_cannot_conflict_with_explicit_backend_region(self):
        bc = self.module()
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run") as run:
            for region_key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
                with self.subTest(key=region_key), self.assertRaises(bc.ControllerError):
                    bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                        deployment_name="demo", local_manifest_root=Path(root), credential_mode="aws-environment",
                        environment={**aws_environment(), region_key: "eu-west-1"}, acknowledge_reads=True)
            run.assert_not_called()

    def test_unknown_required_read_protection_is_not_a_read_verified_receipt(self):
        bc = self.module()
        from src.python.backend_bootstrap import HealthReport
        cli = AWSCLI()
        with tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", cli):
            service = bc.make_read_service(backend_spec=aws_spec(), target_scope=ACCOUNT,
                deployment_name="demo", local_manifest_root=Path(root), credential_mode="aws-environment",
                environment=aws_environment(), acknowledge_reads=True)
            for checks in ({"identity": "passed", "versioning": "unknown"}, {"identity": "passed"}):
                with self.subTest(checks=checks), patch.object(bc, "doctor", return_value=HealthReport("partial", checks, "unknown read protection")):
                    with self.assertRaises(bc.ControllerError):
                        service.verify_scope(service.identity)
                    self.assertIsNone(service.controller.receipt)

    def test_gcp_hidden_credential_and_nonstandard_universe_headers_are_refused(self):
        bc = self.module()
        spec = BackendSpec.from_dict({"backend": "gcs", "namespace": "test", "destination": {
            "bucket": "test-state", "project": "backend-project", "prefix": "state"}}, cloud="gcp")
        for config, hidden in (({}, "/unverified/credential.json"),
                ({"core": {"universe_domain": "unverified.example"}}, ""),
                ({"storage": {"additional_headers": "Authorization=unverified"}}, ""),
                ({"auth": {"impersonate_service_account": "other@example.com"}}, "")):
            def cli(argv, **kwargs):
                if argv[1:3] == ["config", "get-value"]:
                    result = hidden.encode()
                elif argv[1:3] == ["config", "list"]:
                    result = json.dumps(config).encode()
                elif argv[1:3] == ["auth", "list"]:
                    result = b'[{"account":"controller@example.com"}]'
                elif argv[1:3] == ["auth", "print-access-token"]:
                    result = b"SYNTHETIC-OAUTH-TOKEN"
                else:
                    self.fail("Unexpected command")
                return subprocess.CompletedProcess(argv, 0, result, b"")
            with self.subTest(config=config, hidden=hidden), tempfile.TemporaryDirectory() as root, patch.object(bc.subprocess, "run", cli):
                service = bc.make_read_service(backend_spec=spec, target_scope="workload-project", deployment_name="demo",
                    local_manifest_root=Path(root), credential_mode="gcp-gcloud-token", gcloud_account="controller@example.com",
                    environment={}, acknowledge_reads=True)
                with self.assertRaises(bc.ControllerError):
                    service.controller._prepare_gcp()


if __name__ == "__main__":
    unittest.main()
