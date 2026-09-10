import unittest
from src.tests.knowledge_graph.test_extractors import snapshot, extract, claims, round_trip


class ProfileTests(unittest.TestCase):
    def test_bracket_keys_preserve_field_identity_through_rdf_projection(self):
        data = snapshot({"configs/public.yaml": "{a: [{b: 1}], 'a[0]': {b: 2}}"})
        result = extract(data)
        fields = [e for e in result["entities"] if e["kind"] == "ProfileField"]
        paths = claims(result, "field_path")
        with self.subTest(stage="extraction"):
            self.assertEqual(len(fields), 4)
            self.assertEqual(len({c["subject"] for c in paths}), 4)
            self.assertEqual(len({c["occurrence"] for c in paths}), 4)
        restored, graph = round_trip(result, data)
        with self.subTest(stage="rdf_projection"):
            self.assertEqual(len(restored), 4)
            self.assertEqual(graph.number_of_edges(), 4)
            self.assertEqual(len({c["claim_id"] for c in restored}), 4)
        self.assertEqual(extract(data), result)

    def test_inventory_placeholder_transport_is_not_execution(self):
        result = extract(snapshot({"src/ansible/inventory.template": "[targets:vars]\nhuggingface_json={huggingface_json}\nansible_user=\"{config[default_ssh_user]}\"\nconstant=do-not-export\n"}))
        transported = claims(result, "transports_field")
        self.assertEqual({c["object"]["value"] for c in transported}, {"huggingface_json", "config[default_ssh_user]"})
        self.assertEqual({c["source"]["line"] for c in transported}, {2, 3})
        self.assertNotIn("do-not-export", str(result))

    def test_generic_profile_fields_are_desired_not_consumed(self):
        result = extract(snapshot({"configs/public.yaml": "security:\n  ssh_enabled: false\ncontainer_registry:\n  provider: gcp\nhuggingface:\n  artifacts:\n    - repo_id: example/model\nworkstation:\n  future_field: intentionally-not-exported\n"}))
        fields = {e["label"]: e for e in result["entities"] if e["kind"] == "ProfileField"}
        self.assertIn("security.ssh_enabled", fields)
        self.assertIn("huggingface.artifacts[0].repo_id", fields)
        self.assertIn("workstation.future_field", fields)
        self.assertEqual(fields["security.ssh_enabled"]["line"], 2)
        self.assertTrue(result["claims"])
        self.assertEqual({c["evidence_kind"] for c in result["claims"]}, {"desired"})
        self.assertNotIn("intentionally-not-exported", str(result))
        self.assertFalse(claims(result, "consumed_by"))


if __name__ == "__main__":
    unittest.main()
