"""Offline BackendSpec contract tests; no credentials, state or cloud access."""
import importlib.util
import unittest
import copy
import json
from dataclasses import FrozenInstanceError


def s3_data():
    return {"backend": "s3", "namespace": "studio-dev", "destination": {
        "bucket": "example-state-bucket", "region": "us-east-1",
        "owner_account_id": "123456789012", "key_prefix": "isaacautomator/v2"}}


def gcs_data():
    return {"backend": "gcs", "namespace": "studio-dev", "destination": {
        "bucket": "example-state-bucket", "project": "backend-project", "prefix": "isaacautomator/v2"}}


TENANT = "11111111-1111-1111-1111-111111111111"
SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"
TARGET_SUBSCRIPTION = "33333333-3333-3333-3333-333333333333"


def azure_data():
    return {"backend": "azurerm", "namespace": "studio-dev", "destination": {
        "tenant_id": TENANT, "subscription_id": SUBSCRIPTION,
        "resource_group_name": "Backend-RG", "storage_account_name": "examplestate123",
        "container_name": "tf-state", "key_prefix": "isaacautomator/v2"}}


class BackendSpecTests(unittest.TestCase):
    def test_empty_input_is_local_for_each_supported_cloud(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.terraform_backend"),
                             "BackendSpec module must exist")
        from src.python.terraform_backend import BackendSpec
        for cloud in ("aws", "gcp", "azure", "alicloud"):
            for data in (None, {}):
                with self.subTest(cloud=cloud, data=data):
                    spec = BackendSpec.from_dict(data, cloud=cloud)
                    self.assertEqual((spec.backend, spec.cloud, spec.namespace,
                                      spec.timeout_seconds),
                                     ("local", cloud, "default", 120))
                    self.assertEqual(spec.to_dict(), {
                        "schema_version": 1, "backend": "local", "namespace": "default",
                        "workspace": "default", "locking": {"mode": "native", "timeout_seconds": 120},
                        "authentication": {"mode": "ambient"}})


    def test_only_local_identity_can_omit_unqueried_cloud_scope(self):
        from src.python.terraform_backend import BackendSpec
        for cloud in ("aws", "gcp", "azure", "alicloud"):
            local = BackendSpec.from_dict(None, cloud=cloud)
            identity = local.identity(None, "demo")
            self.assertIsNone(identity["target_scope"])
            self.assertNotIn("None", identity["logical_path"])
            self.assertEqual(local.backend_config(None, "demo", "/tmp/state/demo/.tfstate"),
                             {"path": "/tmp/state/demo/.tfstate"})
        for cloud, data in (("aws", s3_data()), ("gcp", gcs_data()), ("azure", azure_data())):
            with self.subTest(cloud=cloud), self.assertRaises(ValueError):
                BackendSpec.from_dict(data, cloud=cloud).identity(None, "demo")

    def test_schema_rejects_ambiguous_or_unsafe_local_configuration(self):
        from src.python.terraform_backend import BackendSpec
        invalid = [[], "", False, 0, {"backend": "auto"}, {"schema_version": True},
                   {"schema_version": 2}, {"workspace": "team"}, {"destination": {}},
                   {"s3": {}, "gcs": {}}, {"terraform_state": {}},
                   {"namespace": "../oops"}, {"namespace": "bad\nname"},
                   {"namespace": ""}, {"namespace": "auto"},
                   {"locking": []}, {"locking": {"mode": "none"}},
                   {"locking": {"timeout_seconds": True}},
                   {"locking": {"timeout_seconds": 0}},
                   {"locking": {"timeout_seconds": 3601}},
                   {"locking": {"timeout_seconds": "120"}},
                   {"authentication": {"mode": "oidc"}},
                   {"authentication": {"token": "TEST-SECRET"}},
                   {"access_key": "TEST-SECRET"}, {"backend": ["local", "s3"]}]
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(ValueError) as raised:
                    BackendSpec.from_dict(data, cloud="aws")
                self.assertNotIn("TEST-SECRET", str(raised.exception))
        for cloud in (None, "", "AWS", "other", []):
            with self.assertRaises(ValueError):
                BackendSpec.from_dict({}, cloud=cloud)
        spec = BackendSpec.from_dict({"namespace": "team-1", "locking": {"timeout_seconds": 30}}, cloud="gcp")
        self.assertEqual((spec.namespace, spec.timeout_seconds), ("team-1", 30))


    def test_s3_descriptor_maps_to_exact_native_locked_state(self):
        from src.python.terraform_backend import BackendSpec
        data = s3_data()
        spec = BackendSpec.from_dict(data, cloud="aws")
        self.assertEqual(spec.to_dict()["destination"], data["destination"])
        key = "isaacautomator/v2/studio-dev/aws/999999999999/workstation/terraform.tfstate"
        self.assertEqual(spec.backend_config("999999999999", "workstation"), {
            "bucket": "example-state-bucket", "region": "us-east-1", "key": key,
            "allowed_account_ids": ["123456789012"], "encrypt": True, "use_lockfile": True})
        self.assertEqual(spec.identity("999999999999", "workstation"), {
            "schema_version": 1, "backend": "s3", "cloud": "aws", "namespace": "studio-dev",
            "workspace": "default", "target_scope": "999999999999", "deployment_name": "workstation",
            "logical_path": key.removesuffix(".tfstate"), "object_key": key,
            "destination": data["destination"]})


    def test_s3_requires_explicit_safe_native_cloud_destination(self):
        from src.python.terraform_backend import BackendSpec
        for cloud in ("gcp", "azure", "alicloud"):
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(s3_data(), cloud=cloud)
        for field in ("namespace", "destination"):
            data = s3_data()
            del data[field]
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(data, cloud="aws")
        invalid = {
            "bucket": (None, "auto", "ab", "UPPER", "a..b", "192.168.0.1", "a/b", "x\n", "a" * 64),
            "region": ("", "auto", "us east 1", "us-east-1;cmd", "US-EAST-1"),
            "owner_account_id": (123456789012, "123", "a" * 12),
            "key_prefix": ("", "auto", "/root", "a/../b", "a//b", "a/", "a\\b", "a/%2e", "a/${x}", "a\x00b")}
        for field, values in invalid.items():
            for value in ("__MISSING__", *values):
                data = s3_data()
                if value == "__MISSING__":
                    del data["destination"][field]
                else:
                    data["destination"][field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        BackendSpec.from_dict(data, cloud="aws")
        for field in ("project", "access_key", "secret_key", "token", "endpoint", "encrypt",
                      "use_lockfile", "dynamodb_table", "sse_customer_key"):
            data = s3_data()
            data["destination"][field] = "TEST-SECRET"
            with self.assertRaises(ValueError) as raised:
                BackendSpec.from_dict(data, cloud="aws")
            self.assertNotIn("TEST-SECRET", str(raised.exception))
        for destination in ([], [{"bucket": "one"}, {"bucket": "two"}], None):
            data = s3_data()
            data["destination"] = destination
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(data, cloud="aws")


    def test_gcs_keeps_project_in_descriptor_not_init_config(self):
        from src.python.terraform_backend import BackendSpec
        data = gcs_data()
        try:
            spec = BackendSpec.from_dict(data, cloud="gcp")
        except ValueError as error:
            self.fail(f"Valid GCS descriptor rejected: {error}")
        prefix = "isaacautomator/v2/studio-dev/gcp/workload-project/workstation/terraform"
        self.assertEqual(spec.backend_config("workload-project", "workstation"),
                         {"bucket": "example-state-bucket", "prefix": prefix})
        identity = spec.identity("workload-project", "workstation")
        self.assertEqual(identity["object_key"], prefix + "/default.tfstate")
        self.assertEqual(identity["destination"], data["destination"])
        self.assertEqual(spec.to_dict()["destination"]["project"], "backend-project")
        for field in ("bucket", "project", "prefix"):
            bad = gcs_data()
            del bad["destination"][field]
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(bad, cloud="gcp")
        for project in ("123456789", "bad/project", "tiny", "UPPER", "project-", "auto"):
            bad = gcs_data()
            bad["destination"]["project"] = project
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(bad, cloud="gcp")
        for field in ("region", "credentials", "access_token", "encryption_key"):
            bad = gcs_data()
            bad["destination"][field] = "TEST-SECRET"
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(bad, cloud="gcp")
        for cloud in ("aws", "azure", "alicloud"):
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(data, cloud=cloud)


    def test_azure_uses_entra_with_explicit_management_context(self):
        from src.python.terraform_backend import BackendSpec
        data = azure_data()
        try:
            spec = BackendSpec.from_dict(data, cloud="azure")
        except ValueError as error:
            self.fail(f"Valid Azure descriptor rejected: {error}")
        key = f"isaacautomator/v2/studio-dev/azure/{TARGET_SUBSCRIPTION}/workstation/terraform.tfstate"
        expected = dict(data["destination"])
        del expected["key_prefix"]
        expected.update(key=key, use_azuread_auth=True)
        self.assertEqual(spec.backend_config(TARGET_SUBSCRIPTION, "workstation"), expected)
        self.assertEqual(spec.identity(TARGET_SUBSCRIPTION, "workstation")["object_key"], key)
        for field in data["destination"]:
            bad = azure_data()
            del bad["destination"][field]
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(bad, cloud="azure")
        for field, values in {
            "tenant_id": ("auto", "not-uuid", TENANT + "\n"),
            "subscription_id": ("not-uuid",), "resource_group_name": ("../rg", "rg;run", "rg."),
            "storage_account_name": ("ab", "UpperCase", "with-hyphen", "a" * 25),
            "container_name": ("ab", "Upper", "two--hyphens", "trailing-"),
            "key_prefix": ("a/../b",)}.items():
            for value in values:
                bad = azure_data()
                bad["destination"][field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        BackendSpec.from_dict(bad, cloud="azure")
        for field in ("sas_token", "access_key", "client_secret", "client_id", "use_oidc", "bucket"):
            bad = azure_data()
            bad["destination"][field] = "TEST-SECRET"
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(bad, cloud="azure")
        for cloud in ("aws", "gcp", "alicloud"):
            with self.assertRaises(ValueError):
                BackendSpec.from_dict(data, cloud=cloud)


    def test_canonical_serialization_is_detached_and_spec_is_immutable(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict(s3_data(), cloud="aws")
        self.assertTrue(callable(getattr(spec, "canonical_json", None)))
        data = s3_data()
        original = copy.deepcopy(data)
        spec = BackendSpec.from_dict(data, cloud="aws")
        canonical = spec.canonical_json()
        self.assertEqual(canonical, json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        reordered = dict(reversed(list(original.items())))
        self.assertEqual(BackendSpec.from_dict(reordered, cloud="aws").canonical_json(), canonical)
        self.assertEqual(BackendSpec.from_dict(spec.to_dict(), cloud="aws"), spec)
        data["destination"]["bucket"] = "changed-bucket"
        exported = spec.to_dict()
        exported["destination"]["bucket"] = "another-bucket"
        exported["locking"]["mode"] = "none"
        identity = spec.identity("999999999999", "workstation")
        identity["destination"]["bucket"] = "third-bucket"
        self.assertEqual(spec.canonical_json(), canonical)
        with self.assertRaises(FrozenInstanceError):
            spec.namespace = "changed"
        with self.assertRaises(TypeError):
            BackendSpec(cloud="aws", backend="s3", _destination=(("secret_key", "TEST-SECRET"),))


    def test_identity_validates_target_scope_and_deployment_before_rendering(self):
        from src.python.terraform_backend import BackendSpec
        cases = ((s3_data(), "aws", "999999999999"),
                 (gcs_data(), "gcp", "workload-project"),
                 (azure_data(), "azure", TARGET_SUBSCRIPTION))
        identities = []
        for data, cloud, scope in cases:
            spec = BackendSpec.from_dict(data, cloud=cloud)
            for invalid in (None, "", "auto", "../escape", "x/y", "x\\y", "x\n", "x\x7f", "x\u202e", "${x}", "x;cmd", "x" * 64):
                for method in (spec.identity, spec.backend_config):
                    with self.subTest(cloud=cloud, value=invalid, method=method.__name__):
                        with self.assertRaises(ValueError):
                            method(scope, invalid)
                        with self.assertRaises(ValueError):
                            method(invalid, "workstation")
            for wrong_scope in ("123", "UPPER", "not-a-real-scope-"):
                with self.assertRaises(ValueError):
                    spec.identity(wrong_scope, "workstation")
            identities.append(json.dumps(spec.identity(scope, "workstation"), sort_keys=True))
            changed = copy.deepcopy(data)
            changed["namespace"] = "other-team"
            self.assertNotEqual(spec.identity(scope, "workstation")["object_key"],
                                BackendSpec.from_dict(changed, cloud=cloud).identity(scope, "workstation")["object_key"])
        self.assertEqual(len(set(identities)), 3)
        spec = BackendSpec.from_dict(s3_data(), cloud="aws")
        self.assertNotEqual(spec.identity("999999999999", "workstation")["object_key"],
                            spec.identity("888888888888", "workstation")["object_key"])


    def test_local_requires_caller_pinned_absolute_state_path(self):
        from src.python.terraform_backend import BackendSpec
        for cloud, scope in (("aws", "999999999999"), ("gcp", "workload-project"),
                             ("azure", TARGET_SUBSCRIPTION), ("alicloud", "1234567890123456")):
            spec = BackendSpec.from_dict(None, cloud=cloud)
            try:
                identity = spec.identity(scope, "workstation")
            except KeyError as error:
                self.fail(f"Local identity not implemented: {error}")
            self.assertEqual(identity["logical_path"], f"isaacautomator/v2/default/{cloud}/{scope}/workstation/terraform")
            self.assertEqual(identity["object_key"], "state/workstation/.tfstate")
            self.assertEqual(spec.backend_config(scope, "workstation", "/approved-root/workstation/.tfstate"),
                             {"path": "/approved-root/workstation/.tfstate"})
            for path in (None, "state/workstation/.tfstate", "/root/../workstation/.tfstate",
                         "/root//workstation/.tfstate", "/root/./workstation/.tfstate",
                         "/root/other/.tfstate", "/root/workstation/other.tfstate",
                         "/root/workstation/.tfstate\n", "//root/workstation/.tfstate", "/root/${x}/workstation/.tfstate"):
                with self.subTest(cloud=cloud, path=path):
                    with self.assertRaises(ValueError):
                        spec.backend_config(scope, "workstation", path)
        remote = BackendSpec.from_dict(s3_data(), cloud="aws")
        with self.assertRaises(ValueError):
            remote.backend_config("999999999999", "workstation", "/root/workstation/.tfstate")

    def test_local_state_root_allows_spaces_and_unicode_without_shell_interpolation(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict(None, cloud="aws")
        path = "/home/developer/Robotics Projects/équipe/workstation/.tfstate"
        self.assertEqual(spec.backend_config("123456789012", "workstation", path), {"path": path})


    def test_existing_kms_identifiers_are_allowlisted_not_key_material(self):
        from src.python.terraform_backend import BackendSpec
        cases = ((s3_data, "aws", "999999999999", "kms_key_id",
                  "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789abc"),
                 (gcs_data, "gcp", "workload-project", "kms_encryption_key",
                  "projects/kms-project/locations/us-east1/keyRings/StateKeys/cryptoKeys/state-key"))
        for factory, cloud, scope, field, identifier in cases:
            data = factory()
            data["destination"][field] = identifier
            try:
                spec = BackendSpec.from_dict(data, cloud=cloud)
            except ValueError as error:
                self.fail(f"Documented existing KMS identifier rejected: {error}")
            self.assertEqual(spec.backend_config(scope, "workstation")[field], identifier)
            self.assertEqual(spec.to_dict()["destination"][field], identifier)
            for value in ("TEST-SECRET", "", "auto", identifier + "\n", identifier + "/../other", {"secret": "TEST-SECRET"}):
                data["destination"][field] = value
                with self.assertRaises(ValueError) as raised:
                    BackendSpec.from_dict(data, cloud=cloud)
                self.assertNotIn("TEST-SECRET", str(raised.exception))


    def test_json_loader_rejects_duplicate_blocks_before_mapping_loss(self):
        from src.python.terraform_backend import BackendSpec
        self.assertTrue(callable(getattr(BackendSpec, "from_json", None)))
        spec = BackendSpec.from_dict(s3_data(), cloud="aws")
        self.assertEqual(BackendSpec.from_json(spec.canonical_json(), cloud="aws"), spec)
        for text in ('{"backend":"local","backend":"s3"}',
                     '{"locking":{"mode":"native"},"locking":{"mode":"none"}}',
                     '{"locking":{"mode":"native","mode":"native"}}',
                     '{"authentication":{"mode":"ambient","mode":"ambient"}}',
                     '{"TEST-SECRET":', '[]', '', 1):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as raised:
                    BackendSpec.from_json(text, cloud="aws")
                self.assertNotIn("TEST-SECRET", str(raised.exception))


class VersionTests(unittest.TestCase):
    def test_backend_feature_version_contract(self):
        from src.python import terraform_backend as module
        self.assertTrue(callable(getattr(module, "validate_terraform_version", None)))
        validate = module.validate_terraform_version
        for backend, minimum in (("local", "1.3.5"), ("gcs", "1.10.0"),
                                 ("azurerm", "1.10.0"), ("s3", "1.10.0")):
            for version in (minimum, "1.10.0", "1.20.5"):
                with self.subTest(backend=backend, version=version):
                    self.assertIsNone(validate(version, backend))
            for version in ("1.3.4", "0.15.0", "2.0.0", "1.10.0-rc1", "1.10.0+dev",
                            "01.10.0", "1.10", "Terraform v1.10.0", None, 1, "1.10.0\n"):
                with self.subTest(backend=backend, version=version):
                    with self.assertRaises(ValueError):
                        validate(version, backend)
        self.assertIsNone(validate("1.8.5", "local"))
        for backend in ("s3", "gcs", "azurerm"):
            with self.assertRaisesRegex(ValueError, "1.10.0"):
                validate("1.8.5", backend)
        with self.assertRaises(ValueError):
            validate("1.10.0", "oss")


if __name__ == "__main__":
    unittest.main()
