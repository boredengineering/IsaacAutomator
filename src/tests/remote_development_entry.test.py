"""Top-level offline command registration; no transfer or cloud."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RemoteDevelopmentEntryTests(unittest.TestCase):
    def test_help_runs_without_docker_cloud_or_user_configuration(self):
        with tempfile.TemporaryDirectory(prefix='isaac-remote-entry-') as home:
            result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'remote-development'), '--help'],
                                    cwd=home, env={'PATH': '/nonexistent', 'HOME': home},
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('plan', result.stdout)
        self.assertIn('render', result.stdout)


if __name__ == '__main__':
    unittest.main()
