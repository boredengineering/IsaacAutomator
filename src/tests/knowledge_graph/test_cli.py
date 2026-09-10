"""CLI exercises the real optional entry point, never deployment wrappers."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "src.knowledge_graph.cli", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )


class CliTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory) / 'repo'
        root.mkdir()
        (root / 'example.py').write_text('def normalize(profile):\n    return profile.get("container_registry")\n')
        policy = root / 'policy.json'
        policy.write_text(json.dumps({'schema_version': 'automator-source-policy/v1',
                                     'repo_id': 'fixture', 'files': ['example.py']}))
        cache = Path(directory) / 'cache'
        return policy, cache, ['--repo', str(root), '--policy', str(policy), '--cache', str(cache)]

    def invoke(self, *args):
        from src.knowledge_graph.cli import main
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, json.loads(output.getvalue())

    def test_policy_revocation_during_real_worker_withholds_publication(self):
        from src.knowledge_graph.ingest import run_worker
        from src.knowledge_graph.publication import load
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                policy, cache, options = self.fixture(directory)
                previous = None
                if existing:
                    code, output = self.invoke('index', *options)
                    self.assertEqual(code, 0, output)
                    previous = load(cache)

                def revoke_after_worker(request):
                    result = run_worker(request)
                    self.assertTrue(result['claims'])
                    revoked = json.loads(policy.read_text())
                    revoked['files'] = []
                    policy.write_text(json.dumps(revoked))
                    return result

                with patch('src.knowledge_graph.ingest.run_worker', side_effect=revoke_after_worker):
                    code, output = self.invoke('index', *options)
                self.assertEqual(code, 2, output)
                self.assertEqual(output['status'], 'unavailable')
                self.assertNotIn('claims', output)
                if existing:
                    self.assertEqual(load(cache), previous)
                else:
                    self.assertFalse(cache.exists())

    def test_policy_change_during_real_query_withholds_results(self):
        from src.knowledge_graph.queries import query
        for change in ('revoke', 'invalid', 'symlink', 'missing'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                policy, cache, options = self.fixture(directory)
                code, output = self.invoke('index', *options)
                self.assertEqual(code, 0, output)

                def change_after_query(*args, **kwargs):
                    result = query(*args, **kwargs)
                    self.assertTrue(result['entities'])
                    if change == 'revoke':
                        revoked = json.loads(policy.read_text())
                        revoked['files'] = []
                        policy.write_text(json.dumps(revoked))
                    elif change == 'invalid':
                        policy.write_text('{}')
                    elif change == 'symlink':
                        target = policy.with_name('replacement.json')
                        target.write_text(policy.read_text())
                        policy.unlink()
                        policy.symlink_to(target.name)
                    else:
                        policy.unlink()
                    return result

                with patch('src.knowledge_graph.queries.query', side_effect=change_after_query):
                    code, output = self.invoke('explain-field', 'container_registry', *options)
                self.assertEqual(code, 3 if change == 'revoke' else 2, output)
                self.assertEqual(output['status'], 'stale' if change == 'revoke' else 'unavailable')
                self.assertNotIn('claims', output)
                self.assertNotIn('entities', output)
                self.assertNotIn('freshness', output)

    def test_policy_revocation_during_real_validation_withholds_conformance(self):
        from src.knowledge_graph.ingest import run_worker
        with tempfile.TemporaryDirectory() as directory:
            policy, cache, options = self.fixture(directory)
            code, output = self.invoke('index', *options)
            self.assertEqual(code, 0, output)

            def revoke_after_validation(request):
                self.assertEqual(request['operation'], 'validate')
                result = run_worker(request)
                self.assertTrue(result['validation']['conforms'])
                revoked = json.loads(policy.read_text())
                revoked['files'] = []
                policy.write_text(json.dumps(revoked))
                return result

            with patch('src.knowledge_graph.ingest.run_worker', side_effect=revoke_after_validation):
                code, output = self.invoke('validate', *options)
            self.assertEqual(code, 3, output)
            self.assertEqual(output['status'], 'stale')
            self.assertNotIn('validation', output)

    def test_initial_freshness_boundary_reloads_policy_before_source_read(self):
        from src.knowledge_graph.ingest import implementation_digest
        from src.knowledge_graph.snapshot import _checked_read
        with tempfile.TemporaryDirectory() as directory:
            policy, cache, options = self.fixture(directory)
            code, output = self.invoke('index', *options)
            self.assertEqual(code, 0, output)

            def revoke_after_digest():
                result = implementation_digest()
                revoked = json.loads(policy.read_text())
                revoked['files'] = []
                policy.write_text(json.dumps(revoked))
                return result

            def forbid_revoked_source(repo, path, limit):
                self.assertNotEqual(path, 'example.py', 'revoked source reread')
                return _checked_read(repo, path, limit)

            with patch('src.knowledge_graph.ingest.implementation_digest', side_effect=revoke_after_digest), \
                    patch('src.knowledge_graph.snapshot._checked_read', side_effect=forbid_revoked_source):
                code, output = self.invoke('status', *options)
            self.assertEqual(code, 3, output)
            self.assertEqual(output['status'], 'stale')
            self.assertNotIn('claims', output)

    def test_wrapper_runs_optional_cli_without_deployment_runtime(self):
        script = ROOT / "knowledge-graph"
        self.assertTrue(script.is_file(), "optional entry point is missing")
        result = subprocess.run(["sh", str(script), "--help"], cwd="/tmp", capture_output=True, text=True,
                                env={"PATH": "/usr/bin:/bin", "ISAAC_GRAPH_PYTHON": sys.executable}, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("explain-field", result.stdout)

    def test_missing_index_is_explicit_and_does_not_create_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "absent"
            result = run_cli("status", "--cache", str(cache))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "unavailable")
            self.assertFalse(cache.exists())

    def test_sandboxed_index_query_and_stale_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            source = root / "src/python/example.py"
            source.parent.mkdir(parents=True)
            source.write_text('def normalize(profile):\n    return profile.get("container_registry")\n')
            profile = root / "configs/profiles/example.yaml"
            profile.parent.mkdir(parents=True)
            profile.write_text("container_registry:\n  enabled: false\nworkstation:\n  demos: []\n")
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": "automator-source-policy/v1", "repo_id": "fixture",
                "files": ["src/python/example.py", "configs/profiles/example.yaml"],
            }))
            cache = Path(directory) / "cache"
            options = ["--repo", str(root), "--policy", str(policy), "--cache", str(cache)]
            indexed = run_cli("index", *options)
            self.assertEqual(indexed.returncode, 0, indexed.stdout + indexed.stderr)
            self.assertGreater(json.loads(indexed.stdout)["claims"], 0)
            queried = run_cli("explain-field", "container_registry", *options)
            self.assertEqual(queried.returncode, 0, queried.stdout + queried.stderr)
            data = json.loads(queried.stdout)
            self.assertTrue(data["entities"])
            self.assertEqual(data["freshness"], "current")
            verified = run_cli("validate", *options)
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            source.write_text("# changed source\n")
            stale = run_cli("explain-field", "container_registry", *options)
            self.assertEqual(stale.returncode, 3, stale.stdout + stale.stderr)
            self.assertEqual(json.loads(stale.stdout)["status"], "stale")
            self.assertNotIn("claims", json.loads(stale.stdout))


if __name__ == "__main__":
    unittest.main()
