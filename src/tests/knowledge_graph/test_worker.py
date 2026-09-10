"""Real worker protocol coverage and confinement integration."""
import tempfile
import unittest
from pathlib import Path

from src.knowledge_graph.ingest import implementation_digest, run_worker
from src.knowledge_graph.snapshot import capture_snapshot


class WorkerTests(unittest.TestCase):
    def test_source_exclusions_remain_visible_without_disclosing_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "example.py"
            source.write_text("def example():\n    return 1\n")
            snapshot = capture_snapshot(root, {
                "schema_version": "automator-source-policy/v1", "repo_id": "fixture",
                "files": ["example.py", "configs/private/person.yaml"],
            })
            result = run_worker({"operation": "build", "snapshot": snapshot,
                                 "implementation_digest": implementation_digest()})
            excluded = [item for item in result["coverage"] if item["status"] == "excluded"]
            self.assertEqual(len(excluded), 1)
            self.assertEqual(excluded[0]["path"], "withheld")


if __name__ == "__main__":
    unittest.main()
