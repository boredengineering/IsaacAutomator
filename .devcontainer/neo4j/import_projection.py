"""Fixed, scoped developer projection receiver; Python standard library only."""
import hashlib
import json
import re
import sys

from healthcheck import transaction

SCHEMA = 'automator-neo4j/v1'
MAX_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 10000
NODE_PROPERTIES = {'label', 'kind', 'iri', 'term_json', 'path', 'line'}
CLAIM_PROPERTIES = {'claim_id', 'predicate', 'assessment', 'evidence_kind',
                    'source_path', 'source_line', 'condition_state',
                    'record_json', 'record_sha256'}
RECORD_KEYS = {'subject', 'predicate', 'object', 'source', 'evidence_kind',
               'scope', 'condition', 'assessment', 'extractor', 'claim_id',
               'proposition_key', 'snapshot_id', 'activity_id'}

CONSTRAINT_QUERY = '''CREATE CONSTRAINT automator_projection_scope IF NOT EXISTS
FOR (marker:AutomatorProjection) REQUIRE marker.scope IS UNIQUE'''

# The unique marker serializes load/clear for a scope. The dependent SET takes
# a write lock BEFORE scoped data or the generation guard is read. Keep the
# marker after clear so concurrent transactions share the same lock identity.
LOAD_QUERY = '''
MERGE (marker:AutomatorProjection {scope: $scope})
SET marker._lock = coalesce(marker._lock, 0) + 1
WITH marker
CALL {
  WITH marker
  MATCH (owned:AutomatorOwned {scope: marker.scope})
  DETACH DELETE owned
  RETURN count(*) AS deleted
}
CALL {
  WITH marker
  UNWIND $nodes AS item
  CREATE (node:AutomatorOwned:AutomatorNode)
  SET node = item.properties, node.scope = marker.scope, node.key = item.key
  RETURN count(*) AS nodes
}
CALL {
  WITH marker
  UNWIND $claims AS item
  MATCH (subject:AutomatorOwned:AutomatorNode {scope: marker.scope, key: item.subject_key})
  MATCH (object:AutomatorOwned:AutomatorNode {scope: marker.scope, key: item.object_key})
  CREATE (claim:AutomatorOwned:AutomatorClaim)
  SET claim = item.properties, claim.scope = marker.scope
  CREATE (claim)-[:SUBJECT]->(subject)
  CREATE (claim)-[:OBJECT]->(object)
  FOREACH (supported IN CASE WHEN item.properties.assessment = 'supported' THEN [1] ELSE [] END |
    CREATE (subject)-[edge:EVIDENCE]->(object)
    SET edge = item.properties, edge.scope = marker.scope
  )
  RETURN count(*) AS claims,
         sum(CASE WHEN item.properties.assessment = 'supported' THEN 1 ELSE 0 END) AS evidence_edges
}
SET marker.generation = $generation, marker.snapshot_id = $snapshot_id,
    marker.schema = $schema, marker.imported_at = datetime(),
    marker.freshness = 'snapshot_only'
RETURN nodes, claims, evidence_edges
'''

CLEAR_QUERY = '''
MATCH (marker:AutomatorProjection {scope: $scope})
SET marker._lock = coalesce(marker._lock, 0) + 1
WITH marker
WHERE marker.generation = $generation
CALL {
  WITH marker
  MATCH (owned:AutomatorOwned {scope: marker.scope})
  DETACH DELETE owned
  RETURN count(*) AS deleted
}
SET marker.freshness = 'cleared'
RETURN count(marker) AS cleared, coalesce(sum(deleted), 0) AS deleted
'''


def require(condition):
    if not condition:
        raise ValueError('Invalid projection')


def keys(value, expected):
    require(type(value) is dict and set(value) == expected)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('Invalid projection')


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def properties(value, expected, integer):
    keys(value, expected)
    for key, item in value.items():
        if key == integer:
            require(type(item) is int and 0 <= item < 2 ** 63)
        else:
            require(type(item) is str)
            # Reject lone surrogates before passing strings to Neo4j.
            item.encode('utf-8')


def identity(value, prefix=''):
    require(type(value) is str and re.fullmatch(re.escape(prefix) + '[a-f0-9]{64}', value) is not None)


def term_key(term):
    require(type(term) is dict and type(term.get('value')) is str)
    if term.get('kind') == 'iri':
        keys(term, {'kind', 'value'})
        require(bool(term['value']))
        return 'iri:' + term['value']
    require(term.get('kind') == 'literal')
    require(set(term) in ({'kind', 'value', 'datatype'}, {'kind', 'value', 'language'}))
    qualifier = term.get('datatype', term.get('language'))
    require(type(qualifier) is str and bool(qualifier))
    return 'literal:' + sha(canonical(term))


def validate_record(claim, snapshot_id):
    props = claim['properties']
    record = decode(props['record_json'])
    require(type(record) is dict)
    keys(record, RECORD_KEYS | ({'occurrence'} if 'occurrence' in record else set()))
    require(canonical(record) == props['record_json'])
    require(record['snapshot_id'] == snapshot_id)
    require(type(record['subject']) is str and claim['subject_key'] == 'iri:' + record['subject'])
    require(claim['object_key'] == term_key(record['object']))
    keys(record['source'], {'path', 'line', 'end_line', 'sha256'})
    keys(record['scope'], {'cloud', 'execution_path'})
    keys(record['condition'], {'state', 'expression'})
    for field in ('claim_id', 'predicate', 'assessment', 'evidence_kind'):
        require(props[field] == record[field])
    require(props['source_path'] == record['source']['path'])
    require(type(record['source']['line']) is int and props['source_line'] == record['source']['line'])
    require(props['condition_state'] == record['condition']['state'])


def validate_payload(value, mode):
    require(mode in {'load', 'clear'})
    expected = {'schema', 'scope', 'generation'}
    keys(value, expected | ({'snapshot_id', 'nodes', 'claims'} if mode == 'load' else set()))
    require(value['schema'] == SCHEMA)
    identity(value['scope'])
    identity(value['generation'])
    if mode == 'clear':
        return value
    identity(value['snapshot_id'], 'urn:ia:snapshot:')
    for collection in ('nodes', 'claims'):
        require(type(value[collection]) is list and 1 <= len(value[collection]) <= MAX_ITEMS)
    node_keys = set()
    for node in value['nodes']:
        keys(node, {'key', 'properties'})
        props = node['properties']
        properties(props, NODE_PROPERTIES, 'line')
        require(type(node['key']) is str and node['key'] not in node_keys)
        if props['iri']:
            require(node['key'] == 'iri:' + props['iri'] and props['term_json'] == '')
        else:
            require(node['key'] == 'literal:' + sha(props['term_json']))
            term = decode(props['term_json'])
            require(canonical(term) == props['term_json'])
            require(term_key(term) == node['key'])
        node_keys.add(node['key'])
    claim_ids = set()
    for claim in value['claims']:
        keys(claim, {'subject_key', 'object_key', 'properties'})
        for endpoint in ('subject_key', 'object_key'):
            require(type(claim[endpoint]) is str and claim[endpoint] in node_keys)
        props = claim['properties']
        properties(props, CLAIM_PROPERTIES, 'source_line')
        identity(props['claim_id'], 'urn:ia:claim:')
        require(props['claim_id'] not in claim_ids)
        claim_ids.add(props['claim_id'])
        identity(props['record_sha256'])
        require(sha(props['record_json']) == props['record_sha256'])
        validate_record(claim, value['snapshot_id'])
    return value


def read_payload(stream, mode):
    raw = stream.read(MAX_BYTES + 1)
    require(type(raw) is bytes and len(raw) <= MAX_BYTES)
    return validate_payload(decode(raw.decode('utf-8')), mode)


def result_row(result, columns):
    try:
        require(result['errors'] == [] and len(result['results']) == 1)
        item = result['results'][0]
        require(item['columns'] == columns and len(item['data']) == 1)
        row = item['data'][0]['row']
        require(type(row) is list and len(row) == len(columns))
        require(all(type(count) is int and 0 <= count <= 2 * MAX_ITEMS for count in row))
        return row
    except (KeyError, IndexError, TypeError):
        raise ValueError('Invalid projection receipt') from None


def apply_payload(value, mode):
    validate_payload(value, mode)
    receipt = {'status': 'loaded' if mode == 'load' else 'cleared',
               'scope': value['scope'], 'generation': value['generation']}
    if mode == 'load':
        transaction(CONSTRAINT_QUERY, timeout=30)
        result = transaction(LOAD_QUERY, value, timeout=30)
        columns = ['nodes', 'claims', 'evidence_edges']
        row = result_row(result, columns)
        require(row == [len(value['nodes']), len(value['claims']),
                        sum(item['properties']['assessment'] == 'supported' for item in value['claims'])])
        receipt.update(zip(columns, row))
    else:
        result = transaction(CLEAR_QUERY, value, timeout=30)
        row = result_row(result, ['cleared', 'deleted'])
        require(row[0] in (0, 1) and (row[0] == 1 or row[1] == 0))
        receipt.update(matched=bool(row[0]), deleted=row[1])
    return receipt


def main(argv=None, stream=None):
    try:
        args = sys.argv[1:] if argv is None else argv
        require(len(args) == 1 and args[0] in {'load', 'clear'})
        value = read_payload(sys.stdin.buffer if stream is None else stream, args[0])
        receipt = apply_payload(value, args[0])
        print(canonical(receipt))
        return 0
    except Exception:
        # No exception, request, response or credential contents reach either
        # output stream. The host deadline bounds input transfer as well.
        print(canonical({'status': 'error', 'error': 'Neo4j projection failed'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
