"""Offline contract tests: no Docker, live database, or credential access."""
import copy
import hashlib
import io
import inspect
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from test_neo4j_bootstrap import IMAGE, load_module


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def payload():
    snapshot = 'urn:ia:snapshot:' + 'c' * 64
    record = {
        'subject': 'urn:test:s', 'predicate': 'urn:test:p',
        'object': {'kind': 'literal', 'value': 'hello', 'datatype': 'http://www.w3.org/2001/XMLSchema#string'},
        'source': {'path': 'src/test.py', 'line': 1, 'end_line': 1, 'sha256': 'd' * 64},
        'scope': {'cloud': 'shared', 'execution_path': 'source'},
        'condition': {'state': 'unconditional', 'expression': ''},
        'assessment': 'supported', 'evidence_kind': 'static_implementation',
        'extractor': 'test/v1', 'snapshot_id': snapshot, 'activity_id': 'urn:test:activity',
        'proposition_key': 'urn:ia:proposition:' + 'e' * 64,
        'claim_id': 'urn:ia:claim:' + 'f' * 64,
    }
    term = canonical(record['object'])
    literal_key = 'literal:' + digest(term)
    return {
        'schema': 'automator-neo4j/v1', 'scope': 'a' * 64, 'generation': 'b' * 64,
        'snapshot_id': snapshot,
        'nodes': [
            {'key': 'iri:urn:test:s', 'properties': {'label': 'subject', 'kind': 'entity', 'iri': 'urn:test:s', 'term_json': '', 'path': '', 'line': 0}},
            {'key': literal_key, 'properties': {'label': 'hello', 'kind': 'literal', 'iri': '', 'term_json': term, 'path': '', 'line': 0}},
        ],
        'claims': [{'subject_key': 'iri:urn:test:s', 'object_key': literal_key, 'properties': {
            'claim_id': record['claim_id'], 'predicate': record['predicate'], 'assessment': record['assessment'],
            'evidence_kind': record['evidence_kind'], 'source_path': record['source']['path'],
            'source_line': 1, 'condition_state': 'unconditional',
            'record_json': canonical(record), 'record_sha256': digest(canonical(record)),
        }}],
    }


class ImportTests(unittest.TestCase):
    def receiver(self):
        load_module('bootstrap')
        load_module('healthcheck')
        return load_module('import_projection')

    def test_invalid_contract_is_rejected_before_transfer(self):
        receiver = self.receiver()
        cases = []
        def change(path, value):
            item = payload()
            target = item
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            cases.append(item)
        for path, value in [
            (['extra'], 'query'), (['schema'], 'v2'), (['scope'], 'A' * 64),
            (['generation'], 'bad'), (['snapshot_id'], 'urn:bad'),
            (['nodes'], []), (['claims'], []), (['nodes'], {}),
            (['nodes', 0, 'extra'], 1), (['nodes', 0, 'properties', 'scope'], 'evil'),
            (['nodes', 0, 'properties', 'line'], True),
            (['nodes', 0, 'properties', 'line'], -1),
            (['nodes', 0, 'properties', 'line'], 2 ** 63),
            (['nodes', 0, 'properties', 'label'], {}),
            (['nodes', 0, 'key'], 'iri:wrong'),
            (['nodes', 1, 'key'], 'literal:' + '0' * 64),
            (['nodes', 1, 'properties', 'iri'], 'urn:bad'),
            (['claims', 0, 'subject_key'], 'missing'),
            (['claims', 0, 'object_key'], 'missing'),
            (['claims', 0, 'properties', 'extra'], 'bad'),
            (['claims', 0, 'properties', 'record_sha256'], '0' * 64),
            (['claims', 0, 'properties', 'record_json'], '{}'),
            (['claims', 0, 'properties', 'claim_id'], 'bad'),
            (['claims', 0, 'properties', 'source_line'], True),
        ]:
            change(path, value)
        for collection in ('nodes', 'claims'):
            value = payload()
            value[collection].append(copy.deepcopy(value[collection][0]))
            cases.append(value)
            value = payload()
            value[collection] = value[collection] * 10001
            cases.append(value)
        for item in cases:
            with self.subTest(case=cases.index(item)):
                with self.assertRaises(ValueError):
                    receiver.validate_payload(item, 'load')

    def test_bounded_strict_json_input(self):
        receiver = self.receiver()
        class Bounded(io.BytesIO):
            def read(self, size=-1):
                self_test.assertEqual(size, 4 * 1024 * 1024 + 1)
                return super().read(size)
        self_test = self
        for raw in [b' ' * (4 * 1024 * 1024 + 1), b'{"schema":1,"schema":2}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'\xff', b'[]']:
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(ValueError):
                    receiver.read_payload(Bounded(raw), 'load')

    def test_canonical_typed_terms_and_complete_records_are_required(self):
        receiver = self.receiver()
        for field, content in [('record_json', '{}'), ('record_json', '[]'),
                               ('record_json', '{"x":NaN}'), ('term_json', '{}'),
                               ('term_json', '{"kind":"literal","value":5}'),
                               ('term_json', '{"kind":"iri","value":"urn:x"}')]:
            value = payload()
            if field == 'record_json':
                props = value['claims'][0]['properties']
                props[field], props['record_sha256'] = content, digest(content)
            else:
                props = value['nodes'][1]['properties']
                props[field] = content
                key = 'literal:' + digest(content)
                value['nodes'][1]['key'] = value['claims'][0]['object_key'] = key
            with self.subTest(field=field, content=content), self.assertRaises(ValueError):
                receiver.validate_payload(value, 'load')
        for field in ('claim_id', 'predicate', 'assessment', 'evidence_kind', 'source_path',
                      'condition_state', 'source_line'):
            value = payload()
            value['claims'][0]['properties'][field] = 2 if field == 'source_line' else 'urn:ia:claim:' + '1' * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                receiver.validate_payload(value, 'load')
        for modify in ('whitespace', 'missing', 'snapshot', 'subject', 'object', 'extra'):
            value = payload()
            props = value['claims'][0]['properties']
            record = json.loads(props['record_json'])
            if modify == 'missing':
                del record['scope']
            elif modify == 'snapshot':
                record['snapshot_id'] = 'urn:ia:snapshot:' + '1' * 64
            elif modify == 'subject':
                record['subject'] = 'urn:other'
            elif modify == 'object':
                record['object']['value'] = 'other'
            elif modify == 'extra':
                record['body'] = 'raw source forbidden'
            content = json.dumps(record) if modify == 'whitespace' else canonical(record)
            props['record_json'], props['record_sha256'] = content, digest(content)
            with self.subTest(modify=modify), self.assertRaises(ValueError):
                receiver.validate_payload(value, 'load')

    def test_clear_has_exact_generation_guard_envelope(self):
        receiver = self.receiver()
        value = {k: payload()[k] for k in ('schema', 'scope', 'generation')}
        self.assertEqual(receiver.validate_payload(value, 'clear'), value)
        for bad in [dict(value, nodes=[]), dict(value, generation=''), {}, value]:
            with self.assertRaises(ValueError):
                receiver.validate_payload(bad, 'other' if bad == value else 'clear')

    def test_load_uses_static_constraint_then_one_atomic_scoped_query(self):
        receiver = self.receiver()
        self.assertTrue(hasattr(receiver, 'apply_payload'))
        value = payload()
        injection = "'); MATCH (n) DETACH DELETE n //"
        value['nodes'][0]['properties']['label'] = injection
        result = {'results': [{'columns': ['nodes', 'claims', 'evidence_edges'],
                               'data': [{'row': [2, 1, 1]}]}], 'errors': []}
        with patch.object(receiver, 'transaction', return_value=result) as tx:
            receipt = receiver.apply_payload(value, 'load')
        self.assertEqual(receipt, {'status': 'loaded', 'scope': value['scope'],
                                  'generation': value['generation'], 'nodes': 2,
                                  'claims': 1, 'evidence_edges': 1})
        self.assertEqual(tx.call_count, 2)
        constraint, write = tx.call_args_list
        self.assertEqual(constraint.args, (receiver.CONSTRAINT_QUERY,))
        self.assertIn('IF NOT EXISTS', constraint.args[0])
        self.assertIn('REQUIRE marker.scope IS UNIQUE', constraint.args[0])
        self.assertEqual(write.args, (receiver.LOAD_QUERY, value))
        self.assertEqual(write.kwargs, {'timeout': 30})
        query = write.args[0]
        self.assertNotIn(injection, query)
        self.assertIn('MERGE (marker:AutomatorProjection {scope: $scope})', query)
        self.assertIn('SET marker._lock = coalesce(marker._lock, 0) + 1', query)
        self.assertIn('MATCH (owned:AutomatorOwned {scope: marker.scope})', query)
        self.assertIn('DETACH DELETE owned', query)
        self.assertLess(query.index('SET marker._lock'), query.index('DETACH DELETE owned'))
        for fragment in ['CREATE (node:AutomatorOwned:AutomatorNode)',
                         'CREATE (claim:AutomatorOwned:AutomatorClaim)',
                         'CREATE (claim)-[:SUBJECT]->(subject)',
                         'CREATE (claim)-[:OBJECT]->(object)',
                         "item.properties.assessment = 'supported'",
                         'CREATE (subject)-[edge:EVIDENCE]->(object)',
                         "marker.freshness = 'snapshot_only'", 'marker.imported_at = datetime()']:
            self.assertIn(fragment, query)
        self.assertNotIn('MERGE (subject)-', query)

    def test_clear_locks_marker_before_generation_check_and_scoped_deletion(self):
        receiver = self.receiver()
        self.assertTrue(hasattr(receiver, 'apply_payload'))
        value = {k: payload()[k] for k in ('schema', 'scope', 'generation')}
        for row in ([1, 3], [0, 0]):
            result = {'results': [{'columns': ['cleared', 'deleted'], 'data': [{'row': row}]}], 'errors': []}
            with patch.object(receiver, 'transaction', return_value=result) as tx:
                receipt = receiver.apply_payload(value, 'clear')
            tx.assert_called_once_with(receiver.CLEAR_QUERY, value, timeout=30)
            self.assertEqual(receipt, {'status': 'cleared', 'scope': value['scope'],
                                      'generation': value['generation'], 'matched': bool(row[0]), 'deleted': row[1]})
        query = receiver.CLEAR_QUERY
        self.assertLess(query.index('SET marker._lock'), query.index('WHERE marker.generation = $generation'))
        self.assertLess(query.index('WHERE marker.generation = $generation'), query.index('DETACH DELETE owned'))
        self.assertIn('MATCH (owned:AutomatorOwned {scope: marker.scope})', query)
        self.assertNotIn('DELETE marker', query)

    def test_invalid_payload_does_not_call_database(self):
        receiver = self.receiver()
        self.assertTrue(hasattr(receiver, 'apply_payload'))
        with patch.object(receiver, 'transaction') as tx, self.assertRaises(ValueError):
            receiver.apply_payload({}, 'load')
        tx.assert_not_called()

    def test_receipt_requires_exact_database_counts_and_shape(self):
        receiver = self.receiver()
        for result in [
            {'results': [], 'errors': []},
            {'results': [{'columns': ['nodes', 'claims', 'evidence_edges'], 'data': [{'row': [True, 1, 1]}]}], 'errors': []},
            {'results': [{'columns': ['nodes', 'claims', 'evidence_edges'], 'data': [{'row': [2, 0, 1]}]}], 'errors': []},
            {'results': [{'columns': ['nodes', 'claims', 'evidence_edges'], 'data': [{'row': [2, 1, 1, 'secret']}]}], 'errors': []},
            {'results': [{'columns': ['bad'], 'data': [{'row': [2, 1, 1]}]}], 'errors': []},
        ]:
            with self.subTest(result=result), patch.object(receiver, 'transaction', return_value=result):
                with self.assertRaises(ValueError):
                    receiver.apply_payload(payload(), 'load')

    def test_cli_only_fixed_modes_generic_failure_and_bounded_receipt(self):
        receiver = self.receiver()
        self.assertTrue(hasattr(receiver, 'main'))
        for argv in ([], ['query'], ['load', 'extra'], ['clear', '--url=evil']):
            with patch.object(receiver, 'transaction') as tx, redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                self.assertEqual(receiver.main(argv, io.BytesIO(b'{}')), 1)
            tx.assert_not_called()
            self.assertEqual(json.loads(out.getvalue()), {'status': 'error', 'error': 'Neo4j projection failed'})
            self.assertEqual(err.getvalue(), '')
        result = {'results': [{'columns': ['nodes', 'claims', 'evidence_edges'], 'data': [{'row': [2, 1, 1]}]}], 'errors': []}
        with patch.object(receiver, 'transaction', return_value=result), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(receiver.main(['load'], io.BytesIO(canonical(payload()).encode())), 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'loaded')
        self.assertLess(len(out.getvalue()), 1024)
        with patch.object(receiver, 'transaction', side_effect=RuntimeError('secret payload')), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(receiver.main(['load'], io.BytesIO(canonical(payload()).encode())), 1)
        self.assertNotIn('secret', out.getvalue() + err.getvalue())

    def test_transaction_timeout_is_keyword_only_and_bounded(self):
        self.receiver()
        health = load_module('healthcheck')
        parameters = inspect.signature(health.transaction).parameters
        self.assertIn('timeout', parameters)
        self.assertEqual(parameters['timeout'].kind, inspect.Parameter.KEYWORD_ONLY)
        for value in (0, -1, 31, True, '30', float('inf'), float('nan')):
            with patch.object(health, 'read_auth') as auth:
                with self.assertRaisesRegex(RuntimeError, '^Neo4j transaction failed$'):
                    health.transaction('RETURN 1', timeout=value)
                auth.assert_not_called()
        with patch.object(health, 'read_auth', return_value='neo4j/test-only'), \
             patch.object(health.http.client, 'HTTPConnection') as connection, \
             patch.object(health.threading, 'Timer') as timer:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b'{"results":[],"errors":[]}'
            health.transaction('RETURN 1', timeout=30)
            connection.assert_called_once_with('127.0.0.1', health.PORT, timeout=30)
            self.assertEqual(timer.call_args.args[0], 30)

    def test_image_copies_fixed_receiver(self):
        self.assertIn('COPY --chown=root:root bootstrap.py healthcheck.py import_projection.py /opt/automator-neo4j/',
                      (IMAGE / 'Dockerfile').read_text())

    def test_valid_load_preserves_complete_canonical_records(self):
        receiver = self.receiver()
        value = payload()
        self.assertEqual(receiver.validate_payload(value, 'load'), value)
        self.assertEqual(receiver.read_payload(io.BytesIO(canonical(value).encode()), 'load'), value)


if __name__ == '__main__':
    unittest.main()
