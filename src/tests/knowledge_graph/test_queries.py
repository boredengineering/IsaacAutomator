"""Evidence retrieval must not invent complete implementation paths."""
import unittest
import json

try:
    from src.knowledge_graph import queries
except ImportError:
    queries = None


class QueryTests(unittest.TestCase):
    def test_unknown_field_is_not_reported_as_unused(self):
        self.assertIsNotNone(queries, "bounded queries are not implemented")
        result = queries.query([], [], "explain-field", "workstation.demos")
        self.assertIn("unknown", result["status"])
        self.assertEqual(result["claims"], [])
        self.assertIn("not established", result["message"])

    def test_field_returns_all_parallel_evidence_without_crossing_unknown_conditions(self):
        entities = [
            {"id": "field", "kind": "ProfileField", "label": "container_registry"},
            {"id": "func", "kind": "PythonSymbol", "label": "normalize_registries"},
            {"id": "target", "kind": "TaskDefinition", "label": "pull"},
        ]
        claims = [
            {"claim_id": "one", "subject": "field", "predicate": "consumed_by",
             "object": {"kind": "iri", "value": "func"}, "assessment": "supported",
             "condition": {"state": "unresolved", "expression": ""}},
            {"claim_id": "two", "subject": "field", "predicate": "references",
             "object": {"kind": "iri", "value": "func"}, "assessment": "disputed",
             "condition": {"state": "unconditional", "expression": ""}},
            {"claim_id": "three", "subject": "func", "predicate": "configures",
             "object": {"kind": "iri", "value": "target"}, "assessment": "supported",
             "condition": {"state": "unconditional", "expression": ""}},
        ]
        result = queries.query(claims, entities, "explain-field", "container_registry")
        self.assertEqual({c["claim_id"] for c in result["claims"]}, {"one", "two"})
        self.assertIn("unknown", result["status"])
        self.assertIn("disputed", result["status"])

    def test_result_limits_are_explicit(self):
        entities = [{"id": str(i), "kind": "ProfileField", "label": "field"} for i in range(20)]
        result = queries.query([], entities, "explain-field", "field", limit=3)
        self.assertEqual(len(result["entities"]), 3)
        self.assertTrue(result["truncated"])
        self.assertIn("truncated", result["status"])
        self.assertLessEqual(len(json.dumps(result).encode()), queries.MAX_BYTES)

    def test_unsafe_operations_and_limits_rejected(self):
        for kwargs in [{"operation": "reindex"}, {"depth": 7}, {"limit": 101}]:
            with self.subTest(kwargs=kwargs):
                args = dict(operation="find", value="field", **{})
                args.update(kwargs)
                with self.assertRaises(ValueError):
                    queries.query([], [], **args)


if __name__ == "__main__":
    unittest.main()
