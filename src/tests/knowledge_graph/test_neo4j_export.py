"""A Neo4j visual copy conserves canonical claims, terms and provenance."""
import copy
import hashlib
import importlib.util
import json
import unittest

from src.knowledge_graph.model import build_dataset, claims_from_dataset
from src.tests.knowledge_graph.test_claims import raw_claim, snapshot


class ExportTests(unittest.TestCase):
    def test_real_confined_worker_exports_validated_dataset(self):
        from src.knowledge_graph.ingest import run_worker
        data = build_dataset([raw_claim()], snapshot(), 'urn:ia:activity:first')
        result = run_worker({'operation': 'neo4j-export', 'dataset': data.serialize(format='trig'),
                             'scope': 'a' * 64, 'generation': 'b' * 64,
                             'snapshot_id': snapshot()['snapshot_id']})
        self.assertEqual(result['payload']['claims'][0]['properties']['claim_id'],
                         claims_from_dataset(data)[0]['claim_id'])

    def test_typed_terms_parallel_claims_and_unreviewed_records_survive(self):
        self.assertIsNotNone(importlib.util.find_spec('src.knowledge_graph.neo4j_projection'))
        from src.knowledge_graph.neo4j_projection import build_payload
        claims = []
        for index, datatype in enumerate(['string', 'integer', 'string']):
            record = copy.deepcopy(raw_claim())
            record['object'] = {'kind': 'literal', 'value': '01',
                                'datatype': 'http://www.w3.org/2001/XMLSchema#' + datatype}
            record['occurrence'] = str(index)
            claims.append(record)
        other = copy.deepcopy(claims[0])
        other.update(assessment='unreviewed', occurrence='unreviewed')
        claims.append(other)
        entity = {'id': 'urn:ia:decl:isolated', 'kind': 'ProfileField', 'label': 'isolated',
                  'path': 'src/example.py', 'line': 1}
        data = build_dataset(claims, snapshot(), 'urn:ia:activity:first', entities=[entity])
        expected = claims_from_dataset(data)
        payload = build_payload(data, 'a' * 64, 'b' * 64, snapshot()['snapshot_id'])
        self.assertEqual(len(payload['claims']), len(expected))
        self.assertEqual({r['properties']['claim_id'] for r in payload['claims']},
                         {r['claim_id'] for r in expected})
        self.assertEqual([json.loads(r['properties']['record_json']) for r in payload['claims']], expected)
        for row in payload['claims']:
            self.assertEqual(hashlib.sha256(row['properties']['record_json'].encode()).hexdigest(),
                             row['properties']['record_sha256'])
        literals = [n for n in payload['nodes'] if n['properties']['kind'] == 'Literal']
        self.assertEqual(len(literals), 2)
        self.assertIn('iri:urn:ia:decl:isolated', {n['key'] for n in payload['nodes']})
        self.assertEqual(payload, build_payload(data, 'a' * 64, 'b' * 64, snapshot()['snapshot_id']))

    def test_invalid_canonical_dataset_does_not_export(self):
        from src.knowledge_graph.neo4j_projection import build_payload
        from rdflib import Dataset
        with self.assertRaises(ValueError):
            build_payload(Dataset(), 'a' * 64, 'b' * 64, 'urn:ia:snapshot:' + 'c' * 64)
