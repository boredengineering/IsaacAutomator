"""One-way visualization payload, derived only from the validated RDF dataset."""
import hashlib
import json

from .model import claims_from_dataset
from .projection import project

SCHEMA = 'automator-neo4j/v1'
MAX_PAYLOAD = 4 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def build_payload(dataset, scope, generation, snapshot_id):
    records = claims_from_dataset(dataset)
    graph = project(dataset)
    nodes = {}

    def iri(value):
        key = 'iri:' + value
        if key not in nodes:
            attr = graph.nodes[value] if value in graph else {}
            nodes[key] = {'key': key, 'properties': {
                'iri': value, 'term_json': '', 'kind': attr.get('kind', 'IRI'),
                'label': attr.get('label', value), 'path': attr.get('path', ''),
                'line': attr.get('line', 0)}}
        return key

    for identifier, attributes in graph.nodes(data=True):
        if isinstance(identifier, str) and attributes.get('kind') != 'Claim':
            iri(identifier)
    claims = []
    for record in records:
        if record['snapshot_id'] != snapshot_id:
            raise ValueError('mixed source snapshots')
        subject = iri(record['subject'])
        term = record['object']
        if term['kind'] == 'iri':
            target = iri(term['value'])
        else:
            encoded = canonical(term)
            target = 'literal:' + hashlib.sha256(encoded.encode()).hexdigest()
            nodes[target] = {'key': target, 'properties': {
                'iri': '', 'term_json': encoded, 'kind': 'Literal',
                'label': term['value'], 'path': '', 'line': 0}}
        encoded = canonical(record)
        claims.append({'subject_key': subject, 'object_key': target, 'properties': {
            'claim_id': record['claim_id'], 'predicate': record['predicate'],
            'assessment': record['assessment'], 'evidence_kind': record['evidence_kind'],
            'source_path': record['source']['path'], 'source_line': record['source']['line'],
            'condition_state': record['condition']['state'], 'record_json': encoded,
            'record_sha256': hashlib.sha256(encoded.encode()).hexdigest()}})
    payload = {'schema': SCHEMA, 'scope': scope, 'generation': generation,
               'snapshot_id': snapshot_id, 'nodes': [nodes[key] for key in sorted(nodes)],
               'claims': claims}
    if not claims or len(claims) > 10000 or len(nodes) > 10000 or len(canonical(payload).encode()) > MAX_PAYLOAD:
        raise ValueError('projection outside import budget')
    return payload
