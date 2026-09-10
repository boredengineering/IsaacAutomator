"""Atomic, integrity-checked local generation storage."""
import tempfile
import unittest

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from src.knowledge_graph import publication
except ImportError:
    publication = None


class PublicationTests(unittest.TestCase):
    def test_publish_and_load_complete_generation(self):
        self.assertIsNotNone(publication, "generation store is not implemented")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            artifacts = {"dataset.trig": "# RDF\n", "manifest.json": "{}\n"}
            generation = publication.publish(cache, artifacts)
            actual_id, actual = publication.load(cache)
            self.assertEqual(actual_id, generation)
            self.assertEqual(actual, artifacts)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o700)

    def test_rejects_artifact_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            with self.assertRaises(ValueError):
                publication.publish(cache, {"../../escape.txt": "forbidden"})
            self.assertFalse((Path(directory) / "escape.txt").exists())

    def test_rejects_symlink_cache_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            with self.assertRaises((ValueError, OSError)):
                publication.publish(alias, {"manifest.json": "{}"})
            self.assertEqual(list(target.iterdir()), [])

    def test_rejects_tampering_and_symlink_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            generation = publication.publish(cache, {"manifest.json": "{}"})
            artifact = cache / generation / "manifest.json"
            artifact.write_text("tampered")
            with self.assertRaises(ValueError):
                publication.load(cache)
            artifact.unlink()
            secret = Path(directory) / "fake-secret"
            secret.write_text("{}")
            artifact.symlink_to(secret)
            with self.assertRaises((ValueError, OSError)):
                publication.load(cache)

    def test_concurrent_publish_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            with ThreadPoolExecutor(max_workers=2) as executor:
                generations = list(executor.map(
                    lambda i: publication.publish(cache, {"manifest.json": str(i)}),
                    range(8),
                ))
            generation, artifacts = publication.load(cache)
            self.assertIn(generation, generations)
            self.assertIn(artifacts["manifest.json"], list(map(str, range(8))))


if __name__ == "__main__":
    unittest.main()
