"""Offline deterministic backend-name proposals are not provisioning."""
import importlib.util
import unittest
from unittest import mock


class BackendProposalTests(unittest.TestCase):
    def test_unused_scope_inputs_are_rejected_not_hidden_in_name_hash(self):
        from src.python.backend_proposal import propose_backend
        for case in (dict(cloud="gcp", owner_scope="backend-project", region="us-east1"),
                     dict(cloud="aws", owner_scope="123456789012", region="us-east-1", tenant_id="unused"),
                     dict(cloud="gcp", owner_scope="backend-project", tenant_id="unused")):
            with self.subTest(case=case), self.assertRaises(ValueError):
                propose_backend(namespace="studio", **case)

    def test_proposals_are_valid_deterministic_distinct_and_offline(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.backend_proposal"), "proposal API missing")
        from src.python.backend_proposal import propose_backend
        from src.python.terraform_backend import BackendSpec
        cases = [dict(cloud="aws", owner_scope="123456789012", region="us-east-1"),
                 dict(cloud="gcp", owner_scope="backend-project"),
                 dict(cloud="azure", owner_scope="22222222-2222-2222-2222-222222222222",
                      tenant_id="11111111-1111-1111-1111-111111111111")]
        with mock.patch("subprocess.run", side_effect=AssertionError("proposal must be offline")):
            for case in cases:
                with self.subTest(cloud=case["cloud"]):
                    first = propose_backend(namespace="studio-prod", **case)
                    self.assertEqual(first, propose_backend(namespace="studio-prod", **case))
                    other = propose_backend(namespace="studio-dev", **case)
                    self.assertNotEqual(first["destination"], other["destination"])
                    self.assertEqual(BackendSpec.from_dict(first, cloud=case["cloud"]).to_dict(), first)


if __name__ == "__main__":
    unittest.main()
