"""Claim identity and portable RDF behavior; synthetic sources only."""
import importlib.util
import unittest
from copy import deepcopy


def raw_claim():
    return {"subject": "urn:ia:decl:field", "predicate": "urn:ia:consumed_by",
            "object": {"kind": "iri", "value": "urn:ia:decl:consumer"},
            "source": {"path": "src/example.py", "line": 1, "end_line": 1, "sha256": "a" * 64},
            "evidence_kind": "static_implementation",
            "scope": {"cloud": "gcp", "execution_path": "source"},
            "condition": {"state": "unconditional", "expression": ""},
            "assessment": "supported", "extractor": "automator-ast/v1"}


def snapshot():
    return {"schema_version": "automator-snapshot/v1", "repo_id": "isaacautomator",
            "snapshot_id": "urn:ia:snapshot:" + "b" * 64, "policy_digest": "c" * 64,
            "manifest": {"src/example.py": "a" * 64},
            "sources": {"src/example.py": "synthetic source\n"}, "coverage": []}


class ClaimTests(unittest.TestCase):
    def test_occurrence_identity_is_idempotent_not_proposition_deduplication(self):
        self.assertIsNotNone(importlib.util.find_spec("src.knowledge_graph.model"))
        from src.knowledge_graph.model import normalize_claim
        raw = raw_claim()
        first = normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first")
        self.assertEqual(first, normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first"))
        second = normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:second")
        self.assertNotEqual(first["claim_id"], second["claim_id"])
        self.assertEqual(first["proposition_key"], second["proposition_key"])
        another = deepcopy(raw)
        another["occurrence"] = "second-mention"
        self.assertNotEqual(first["claim_id"], normalize_claim(another, snapshot()["snapshot_id"], "urn:ia:activity:first")["claim_id"])
        self.assertNotIn("claim_id", raw)

    def test_normalization_rejects_malformed_or_unattributable_evidence(self):
        from src.knowledge_graph.model import normalize_claim
        mutations = [
            lambda r: r.pop("condition"),
            lambda r: r.update(evidence_kind="runtime_true"),
            lambda r: r.update(evidence_kind="test_execution"),
            lambda r: r.update(evidence_kind="observation"),
            lambda r: r.update(assessment="certain"),
            lambda r: r.update(confidence=1),
            lambda r: r.update(subject="not an iri"),
            lambda r: r["source"].update(path="../private/secret.py"),
            lambda r: r["source"].update(line=True),
            lambda r: r["source"].update(end_line=0),
            lambda r: r["source"].update(sha256="invalid"),
            lambda r: r["scope"].update(cloud="all-clouds"),
            lambda r: r["condition"].update(state="true"),
            lambda r: r["condition"].update(state="expression", expression=""),
            lambda r: r["condition"].update(expression="enabled"),
            lambda r: r.update(object={"kind": "literal", "value": 2}),
            lambda r: r.update(object={"kind": "literal", "value": "x", "language": "en", "datatype": "urn:type"}),
            lambda r: r.update(object={"kind": "literal", "value": "x", "language": "bad tag"}),
            lambda r: r.update(object={"kind": "literal", "value": "not-integer", "datatype": "http://www.w3.org/2001/XMLSchema#integer"}),
        ]
        for mutate in mutations:
            raw = raw_claim()
            mutate(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first")

    def test_literal_canonicalization_preserves_lexical_types(self):
        from src.knowledge_graph.model import normalize_claim
        raw = raw_claim()
        raw["object"] = {"kind": "literal", "value": "01", "datatype": "http://www.w3.org/2001/XMLSchema#integer"}
        first = normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first")
        self.assertEqual(first["object"]["value"], "01")
        raw["object"]["value"] = "1"
        self.assertNotEqual(first["proposition_key"], normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first")["proposition_key"])
        raw["object"] = {"kind": "literal", "value": "plain"}
        self.assertEqual(normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first")["object"]["datatype"], "http://www.w3.org/2001/XMLSchema#string")

    def test_named_rdf_roundtrip_keeps_real_terms_and_provenance_without_base_facts(self):
        from rdflib import Dataset, URIRef, Literal
        from rdflib.namespace import RDF, XSD
        from src.knowledge_graph import model
        self.assertTrue(hasattr(model, "build_dataset"))
        records = []
        for obj in [{"kind": "iri", "value": "urn:ia:decl:consumer"},
                    {"kind": "literal", "value": "01", "datatype": str(XSD.integer)},
                    {"kind": "literal", "value": "雪\n\"quote\"", "language": "EN"}]:
            raw = raw_claim()
            raw["object"] = obj
            records.append(raw)
        activity = "urn:ia:activity:first"
        expected = sorted([model.normalize_claim(r, snapshot()["snapshot_id"], activity) for r in records], key=lambda r: r["claim_id"])
        dataset = model.build_dataset(records, snapshot(), activity)
        claims = dataset.graph(next(dataset.default_graph.objects(None, model.IA.claimsGraph)))
        self.assertEqual(len(list(claims.subjects(RDF.type, model.IA.Claim))), 3)
        for record in expected:
            self.assertIn((URIRef(record["claim_id"]), RDF.subject, URIRef(record["subject"])), claims)
            self.assertIn((URIRef(record["claim_id"]), model.PROV.wasGeneratedBy, URIRef(activity)), claims)
        self.assertTrue(any(isinstance(obj, Literal) and obj.datatype == XSD.integer and str(obj) == "01" for obj in claims.objects(None, RDF.object)))
        self.assertFalse(any(tuple(q[:3]) == (URIRef(records[0]["subject"]), URIRef(records[0]["predicate"]), URIRef(records[0]["object"]["value"])) for q in dataset.quads((None, None, None, None))))
        restored = Dataset()
        restored.parse(data=dataset.serialize(format="trig"), format="trig")
        self.assertEqual(model.claims_from_dataset(restored), expected)
        self.assertEqual(model.claims_from_dataset(model.build_dataset(records + records, snapshot(), activity)), expected)

    def test_build_rejects_source_locators_outside_admitted_manifest(self):
        from src.knowledge_graph import model
        self.assertTrue(hasattr(model, "build_dataset"))
        for change in [{"path": "src/unlisted.py"}, {"sha256": "d" * 64}]:
            raw = raw_claim()
            raw["source"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.build_dataset([raw], snapshot(), "urn:ia:activity:first")

    def test_normalization_rejects_container_type_confusion_with_safe_value_errors(self):
        from src.knowledge_graph.model import normalize_claim
        for field, value in [("evidence_kind", []), ("assessment", {}), ("scope", []),
                             ("source", None), ("condition", "unconditional")]:
            raw = raw_claim()
            raw[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_claim(raw, snapshot()["snapshot_id"], "urn:ia:activity:first")
