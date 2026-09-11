"""State identity and attachment contracts using synthetic Terraform v4 data."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
from src.python.terraform_backend import BackendSpec
from src.python import deployment_manifest as dm

LINEAGE = "11111111-1111-4111-8111-111111111111"


def state(serial=3):
    return {"version": 4, "lineage": LINEAGE, "serial": serial, "outputs": {
        "private_key": {"value": "SYNTHETIC-SECRET", "sensitive": True, "type": "string"}},
        "resources": [{"mode": "managed", "type": "aws_instance", "name": "workstation",
                       "instances": [{"attributes": {"id": "i-example", "password": "SYNTHETIC-SECRET"}}]}]}


class StateTests(unittest.TestCase):
    def test_attach_fresh_controller_is_read_only_and_missing_inputs_limit_capabilities(self):
        self.assertTrue(hasattr(dm, "attach_verified"), "attachment API missing")
        spec = BackendSpec.from_dict({"backend": "s3", "namespace": "example", "destination": {
            "bucket": "example-state", "region": "us-east-1", "owner_account_id": "123456789012",
            "key_prefix": "isaacautomator/v2"}}, cloud="aws")
        value = dm.DeploymentManifest.create(backend_spec=spec, target_scope="123456789012",
            deployment_name="demo", lineage=LINEAGE, serial=3, addresses=["aws_instance.workstation"])
        identity = value.identity
        reader = Mock(return_value=state())
        claim_check = Mock(return_value={"status": "active", "identity": identity, "lineage": LINEAGE})
        scope_check = Mock(return_value={"cloud": "aws", "target_scope": "123456789012"})
        with tempfile.TemporaryDirectory() as temporary:
            local = dm.LocalManifestStore(Path(temporary) / "state")
            attached = dm.attach_verified(value, backend_spec=spec, target_scope="123456789012",
                deployment_name="demo", state_reader=reader, verify_cloud_scope=scope_check,
                check_attachment=claim_check, local_store=local)
            self.assertEqual(local.load("demo"), value)
            self.assertTrue(attached.capabilities.state_inspection)
            self.assertFalse(attached.capabilities.vm_start_stop)
            self.assertFalse(attached.capabilities.repair_destroy)
            self.assertNotIn("SYNTHETIC-SECRET", repr(attached))
            self.assertFalse((Path(temporary) / "state/demo/.tfstate").exists())
            reader.assert_called_once_with(identity)
            claim_check.assert_called_once_with(identity)
        for result in ({"cloud": "gcp", "target_scope": "123456789012"},
                       {"cloud": "aws", "target_scope": "999999999999"}):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "state"
                with self.assertRaises(dm.IdentityMismatch):
                    dm.attach_verified(value, backend_spec=spec, target_scope="123456789012",
                        deployment_name="demo", state_reader=Mock(return_value=state()),
                        verify_cloud_scope=Mock(return_value=result), check_attachment=claim_check,
                        local_store=dm.LocalManifestStore(root))
                self.assertFalse(root.exists())

    def test_state_summary_validates_lineage_serial_addresses_without_secret_values(self):
        self.assertTrue(hasattr(dm, "StateSummary"), "state binding implementation missing")
        summary = dm.StateSummary.from_state(state())
        self.assertEqual(summary.to_dict(), {"lineage": LINEAGE, "serial": 3,
                                           "addresses": ["aws_instance.workstation"]})
        self.assertNotIn("SYNTHETIC-SECRET", repr(summary))
        summary.verify(dm.StateSummary.from_state(state()))
        with self.assertRaises(dm.IdentityMismatch):
            summary.verify(dm.StateSummary.from_state(state(4)))
        summary.verify(dm.StateSummary.from_state(state(4)), allow_serial_advance=True)
        for change in ({"lineage": "bad"}, {"serial": True}, {"resources": None}, {"version": 3}):
            with self.subTest(change=change), self.assertRaises(dm.ManifestError):
                dm.StateSummary.from_state(dict(state(), **change))
        other = state()
        other["resources"][0]["name"] = "other"
        with self.assertRaises(dm.IdentityMismatch):
            summary.verify(dm.StateSummary.from_state(other))


if __name__ == "__main__":
    unittest.main()
