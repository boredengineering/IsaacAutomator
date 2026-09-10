"""Validation must inspect the explicit RDF union, not hidden JSON."""
import importlib.util
import unittest
from rdflib import Dataset, URIRef, Literal
from rdflib.namespace import RDF, XSD
from src.knowledge_graph.model import IA, PROV, build_dataset, claims_from_dataset
from src.tests.knowledge_graph.test_claims import raw_claim, snapshot


def fixture():
    dataset = build_dataset([raw_claim()], snapshot(), "urn:ia:activity:first")
    default = dataset.default_graph
    claims = dataset.graph(next(default.objects(None, IA.claimsGraph)))
    prov = dataset.graph(next(default.objects(None, IA.provenanceGraph)))
    node = next(claims.subjects(RDF.type, IA.Claim))
    return dataset, claims, prov, node


class ValidationTests(unittest.TestCase):
    def test_real_shacl_validates_declared_union_and_reports_safe_manifest(self):
        self.assertIsNotNone(importlib.util.find_spec("src.knowledge_graph.validation"))
        from src.knowledge_graph.validation import validate_dataset, require_valid
        dataset, _, _, _ = fixture()
        result = validate_dataset(dataset)
        self.assertTrue(result["conforms"], result)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["selected_graphs"]), 4)
        self.assertEqual(len(result["union_digest"]), 64)
        self.assertEqual(len(result["shapes_digest"]), 64)
        self.assertEqual(result["options"], {"inference": "none", "advanced": False, "js": False, "do_owl_imports": False})
        require_valid(dataset)

    def test_invalid_named_claims_and_provenance_fail_closed_on_read(self):
        self.assertIsNotNone(importlib.util.find_spec("src.knowledge_graph.validation"))
        from src.knowledge_graph.validation import validate_dataset, require_valid
        def remove_condition(ds, cg, pg, node):
            cg.remove((node, IA.condition, None))
        def wrong_subject(ds, cg, pg, node):
            cg.set((node, RDF.subject, Literal("urn:ia:decl:field")))
        def missing_activity(ds, cg, pg, node):
            pg.remove((URIRef("urn:ia:activity:first"), RDF.type, PROV.Activity))
        def wrong_usage_direction(ds, cg, pg, node):
            activity = URIRef("urn:ia:activity:first")
            snap = URIRef(snapshot()["snapshot_id"])
            pg.remove((activity, PROV.used, snap))
            pg.add((snap, PROV.used, activity))
        def injected_claim(ds, cg, pg, node):
            pg.add((URIRef("urn:ia:claim:invalid"), RDF.type, IA.Claim))
        def hidden_claim(ds, cg, pg, node):
            ds.graph(URIRef("urn:unexpected")).add((URIRef("urn:invalid"), RDF.type, IA.Claim))
        def missing_context(ds, cg, pg, node):
            ds.remove_graph(pg)
        def empty_selection(ds, cg, pg, node):
            ds.default_graph.remove((None, IA.declaredGraph, None))
        def broken_source(ds, cg, pg, node):
            source = next(cg.objects(node, PROV.wasDerivedFrom))
            pg.set((source, PROV.specializationOf, URIRef("urn:unadmitted")))
        def runtime_claim(ds, cg, pg, node):
            cg.set((node, IA.evidenceKind, Literal("observation", datatype=XSD.string)))
        def base_fact(ds, cg, pg, node):
            cg.add((URIRef(raw_claim()["subject"]), URIRef(raw_claim()["predicate"]), URIRef(raw_claim()["object"]["value"])))
        def duplicate_object(ds, cg, pg, node):
            cg.add((node, RDF.object, URIRef("urn:other")))
        def unsafe_value(ds, cg, pg, node):
            cg.set((node, IA.evidenceKind, Literal("SYNTHETIC_SECRET_DO_NOT_ECHO", datatype=XSD.string)))
        for mutate in [remove_condition, wrong_subject, missing_activity, wrong_usage_direction,
                       injected_claim, hidden_claim, missing_context, empty_selection,
                       broken_source, runtime_claim, base_fact, duplicate_object, unsafe_value]:
            dataset, claims, prov, node = fixture()
            mutate(dataset, claims, prov, node)
            with self.subTest(mutation=mutate.__name__):
                result = validate_dataset(dataset)
                self.assertFalse(result["conforms"], result)
                self.assertNotIn("SYNTHETIC_SECRET", str(result))
                with self.assertRaises(ValueError):
                    require_valid(dataset)
                with self.assertRaises(ValueError):
                    claims_from_dataset(dataset)
        self.assertFalse(validate_dataset(Dataset())["conforms"])

    def test_declared_entity_tampering_and_source_supplied_shapes_are_rejected(self):
        from src.knowledge_graph.validation import validate_dataset
        from src.knowledge_graph.projection import project
        from rdflib.namespace import SH
        entity = {"id": "urn:ia:decl:isolated", "kind": "ResourceDeclaration", "label": "isolated", "path": "src/example.py", "line": 1}
        for predicate, value in [(IA.kind, Literal("ServiceInstance", datatype=XSD.string)),
                                 (IA.line, Literal(0, datatype=XSD.integer)),
                                 (PROV.wasDerivedFrom, URIRef("urn:unadmitted"))]:
            dataset = build_dataset([], snapshot(), "urn:ia:activity:first", [entity])
            graph = dataset.graph(next(dataset.default_graph.objects(None, IA.entitiesGraph)))
            graph.set((URIRef(entity["id"]), predicate, value))
            with self.subTest(predicate=predicate):
                self.assertFalse(validate_dataset(dataset)["conforms"])
                with self.assertRaises(ValueError):
                    project(dataset)
        dataset, claims, _, _ = fixture()
        claims.add((URIRef("urn:source-shape"), RDF.type, SH.NodeShape))
        self.assertFalse(validate_dataset(dataset)["conforms"])

    def test_bad_shape_failure_contains_no_untrusted_graph_identifiers(self):
        from src.knowledge_graph.validation import validate_dataset
        dataset, claims, _, node = fixture()
        old = claims.identifier
        new = URIRef("urn:SYNTHETIC_SECRET_DO_NOT_ECHO")
        graph = dataset.graph(new)
        for triple in claims:
            graph.add(triple)
        dataset.remove_graph(claims)
        root = next(dataset.default_graph.subjects(RDF.type, IA.Dataset))
        dataset.default_graph.remove((root, IA.declaredGraph, old))
        dataset.default_graph.add((root, IA.declaredGraph, new))
        dataset.default_graph.set((root, IA.claimsGraph, new))
        graph.remove((node, IA.condition, None))
        result = validate_dataset(dataset)
        self.assertFalse(result["conforms"])
        self.assertNotIn("SYNTHETIC_SECRET", str(result))
