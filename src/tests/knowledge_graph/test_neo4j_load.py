"""Explicit database publication with before/after freshness gates."""
import json
import tempfile
import unittest
from unittest.mock import patch

from src.tests.knowledge_graph import test_cli


def receipt(payload, project, operation='load'):
    return {'status': 'loaded' if operation == 'load' else 'cleared',
            'scope': payload['scope'], 'generation': payload['generation']}


class LoadTests(unittest.TestCase):
    def test_sender_uses_fixed_receiver_and_rejects_wrong_receipt(self):
        from src.knowledge_graph.neo4j_client import transfer
        from subprocess import CompletedProcess
        payload = {'schema': 'automator-neo4j/v1', 'scope': 'a' * 64, 'generation': 'b' * 64}
        good = receipt(payload, 'fixture')
        with patch('src.knowledge_graph.neo4j_client.subprocess.run',
                   return_value=CompletedProcess([], 0, json.dumps(good).encode())) as run:
            self.assertEqual(transfer(payload, 'fixture'), good)
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ['/opt/automator-neo4j/import_projection.py', 'load'])
            self.assertEqual(json.loads(run.call_args.kwargs['input']), payload)
            self.assertNotIn('shell', run.call_args.kwargs)
            for project in ('--other', 'project;whoami', '../project'):
                with self.assertRaises(ValueError):
                    transfer(payload, project)
            self.assertEqual(run.call_count, 1)
        good['scope'] = 'c' * 64
        with patch('src.knowledge_graph.neo4j_client.subprocess.run',
                   return_value=CompletedProcess([], 0, json.dumps(good).encode())):
            with self.assertRaises(ValueError):
                transfer(payload, 'fixture')

    def test_revocation_during_export_never_contacts_database(self):
        from src.knowledge_graph import neo4j_client
        from src.knowledge_graph.ingest import run_worker
        helper = test_cli.CliTests()
        with tempfile.TemporaryDirectory() as directory:
            policy, cache, options = helper.fixture(directory)
            self.assertEqual(helper.invoke('index', *options)[0], 0)
            def revoke(request):
                result = run_worker(request)
                policy.unlink()
                return result
            with patch('src.knowledge_graph.ingest.run_worker', side_effect=revoke), \
                    patch.object(neo4j_client, 'transfer') as send:
                code, result = helper.invoke('neo4j-load', *options)
            self.assertEqual(code, 3, result)
            send.assert_not_called()

    def test_load_exports_from_real_worker_and_sends_no_raw_source(self):
        from src.knowledge_graph import neo4j_client
        helper = test_cli.CliTests()
        with tempfile.TemporaryDirectory() as directory:
            policy, cache, options = helper.fixture(directory)
            self.assertEqual(helper.invoke('index', *options)[0], 0)
            with patch.object(neo4j_client, 'transfer', side_effect=receipt) as send:
                code, result = helper.invoke('neo4j-load', *options)
            self.assertEqual(code, 0, result)
            payload = send.call_args.args[0]
            self.assertTrue(payload['claims'])
            self.assertNotIn('def normalize', json.dumps(payload))
            self.assertEqual(result['status'], 'loaded')
            self.assertEqual(result['freshness'], 'checked_at_import_only')

    def test_policy_deleted_during_transfer_clears_only_imported_generation(self):
        from src.knowledge_graph import neo4j_client
        helper = test_cli.CliTests()
        with tempfile.TemporaryDirectory() as directory:
            policy, cache, options = helper.fixture(directory)
            self.assertEqual(helper.invoke('index', *options)[0], 0)
            operations = []
            def send(payload, project, operation='load'):
                operations.append((operation, payload['generation']))
                if operation == 'load':
                    policy.unlink()
                return receipt(payload, project, operation)
            with patch.object(neo4j_client, 'transfer', side_effect=send):
                code, result = helper.invoke('neo4j-load', *options)
            self.assertEqual(code, 3, result)
            self.assertEqual([op for op, _ in operations], ['load', 'clear'])
            self.assertEqual(operations[0][1], operations[1][1])
            self.assertEqual(result['cleanup'], 'cleared')

    def test_revoked_policy_blocks_transfer_but_not_explicit_clear(self):
        from src.knowledge_graph import neo4j_client
        helper = test_cli.CliTests()
        with tempfile.TemporaryDirectory() as directory:
            policy, cache, options = helper.fixture(directory)
            self.assertEqual(helper.invoke('index', *options)[0], 0)
            policy.write_text('{}')
            with patch.object(neo4j_client, 'transfer', side_effect=receipt) as send:
                self.assertNotEqual(helper.invoke('neo4j-load', *options)[0], 0)
                send.assert_not_called()
                code, result = helper.invoke('neo4j-clear', '--generation', 'b' * 64, *options)
                self.assertEqual(code, 0, result)
                self.assertEqual(send.call_args.args[2], 'clear')
