"""Faithful one-way projection of the declared accepted RDF subset."""
import importlib.util
import unittest

from pathlib import Path

import networkx as nx
from rdflib import Dataset, Graph
from rdflib.namespace import RDF, RDFS, XSD

from src.knowledge_graph.model import IA, build_dataset, claims_from_dataset
from src.tests.knowledge_graph.test_claims import raw_claim, snapshot


class ProjectionTests(unittest.TestCase):
    def test_parallel_claims_conditions_types_and_isolated_entities_survive(self):
        self.assertIsNotNone(importlib.util.find_spec("src.knowledge_graph.projection"))
        from src.knowledge_graph.projection import project
        records = []
        for occurrence, predicate, condition in [
            ("a", "urn:ia:consumed_by", {"state": "unconditional", "expression": ""}),
            ("b", "urn:ia:consumed_by", {"state": "expression", "expression": "enabled"}),
            ("c", "urn:ia:requires", {"state": "unresolved", "expression": ""})]:
            raw = raw_claim()
            raw.update(occurrence=occurrence, predicate=predicate, condition=condition)
            records.append(raw)
        for datatype in [str(XSD.integer), str(XSD.string)]:
            raw = raw_claim()
            raw["object"] = {"kind": "literal", "value": "01", "datatype": datatype}
            records.append(raw)
        for assessment in ["disputed", "unreviewed", "rejected"]:
            raw = raw_claim()
            raw["assessment"] = assessment
            records.append(raw)
        entity = {"id": "urn:ia:decl:isolated", "kind": "ResourceDeclaration", "label": "isolated", "path": "src/example.py", "line": 1}
        dataset = build_dataset(records, snapshot(), "urn:ia:activity:first", entities=[entity])
        projected = project(dataset)
        self.assertIsInstance(projected, nx.MultiDiGraph)
        self.assertEqual(projected.number_of_edges(), 5)
        self.assertEqual(len(projected[records[0]["subject"]][records[0]["object"]["value"]]), 3)
        self.assertEqual(projected.nodes[entity["id"]], entity)
        expected = claims_from_dataset(dataset)
        for record in expected:
            if record["assessment"] == "supported":
                edge = next(data for _, _, key, data in projected.edges(keys=True, data=True) if key == record["claim_id"])
                for key, value in record.items():
                    self.assertEqual(edge[key], value)
                self.assertEqual(edge["unconditional"], record["condition"]["state"] == "unconditional")
            else:
                self.assertEqual(projected.nodes[record["claim_id"]]["kind"], "Claim")
                self.assertEqual(projected.nodes[record["claim_id"]]["assessment"], record["assessment"])
        literal_nodes = [data for _, data in projected.nodes(data=True) if data.get("kind") == "Literal"]
        self.assertEqual(len(literal_nodes), 2)
        self.assertEqual({n["term"]["datatype"] for n in literal_nodes}, {str(XSD.integer), str(XSD.string)})
        self.assertEqual(nx.node_link_data(projected, edges="edges"), nx.node_link_data(project(dataset), edges="edges"))
        restored = Dataset().parse(data=dataset.serialize(format="trig"), format="trig")
        self.assertEqual(nx.node_link_data(projected, edges="edges"), nx.node_link_data(project(restored), edges="edges"))

    def test_runtime_entity_and_unadmitted_entity_fail_closed(self):
        for change in [{"kind": "ServiceInstance"}, {"path": "src/unlisted.py"}, {"line": 0}]:
            entity = {"id": "urn:ia:decl:isolated", "kind": "ResourceDeclaration", "label": "isolated", "path": "src/example.py", "line": 1}
            entity.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_dataset([], snapshot(), "urn:ia:activity:first", entities=[entity])

    def test_local_vocabulary_explains_claim_and_provenance_not_truth(self):
        path = Path(__file__).parents[2] / "knowledge_graph/schema/vocabulary.ttl"
        self.assertTrue(path.exists())
        vocabulary = Graph().parse(path, format="turtle")
        self.assertIn((IA.Claim, RDF.type, RDFS.Class), vocabulary)
        self.assertTrue(list(vocabulary.objects(IA.Claim, RDFS.comment)))
        self.assertIn((IA.condition, RDF.type, RDF.Property), vocabulary)

    def test_literal_nodes_cannot_alias_an_iri_with_the_same_internal_spelling(self):
        from src.knowledge_graph.model import _digest
        from src.knowledge_graph.projection import project
        literal = raw_claim()
        literal["object"] = {"kind": "literal", "value": "01", "datatype": str(XSD.integer)}
        iri = raw_claim()
        iri["object"] = {"kind": "iri", "value": "urn:ia:literal:" + _digest(["automator-terms/v1", literal["object"]])}
        graph = project(build_dataset([literal, iri], snapshot(), "urn:ia:activity:first"))
        self.assertEqual(graph.number_of_nodes(), 3)
        self.assertEqual(len(list(graph.successors(literal["subject"]))), 2)
