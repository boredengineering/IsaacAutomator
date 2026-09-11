#!/usr/bin/env python3
"""The workstation source manifest is explicit, not discovery of local files."""
from pathlib import Path
import re
import unittest

from src.python import terraform_sources


class TestTerraformSources(unittest.TestCase):
    def test_allowlist_covers_reviewed_roots_and_relative_modules_only(self):
        root = Path(__file__).resolve().parents[1] / 'terraform'
        for cloud in ('aws', 'gcp', 'azure', 'alicloud'):
            with self.subTest(cloud=cloud):
                files = terraform_sources.workstation_source_files(cloud)
                self.assertIsInstance(files, tuple)
                self.assertEqual(len(files), len(set(files)))
                self.assertIn('main.tf', files)
                actual = {str(p.relative_to(root / cloud)) for p in (root / cloud).rglob('*.tf')}
                self.assertEqual(set(files), actual)
                for name in files:
                    text = (root / cloud / name).read_text()
                    for module in re.findall(r'source\s*=\s*"(\./[^"]+)"', text):
                        directory = (Path(name).parent / module).as_posix()
                        self.assertTrue(any(p.startswith(directory + '/') for p in files), module)

    def test_unknown_root_is_refused(self):
        with self.assertRaises(ValueError):
            terraform_sources.workstation_source_files('registry')


if __name__ == '__main__':
    unittest.main()
