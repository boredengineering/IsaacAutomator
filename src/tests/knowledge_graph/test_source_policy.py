"""Admission contracts; all sensitive-looking values are synthetic fixtures."""
import json
import tempfile
import unittest
from pathlib import Path


class SourcePolicyTests(unittest.TestCase):
    def test_load_explicit_versioned_policy(self):
        from src.knowledge_graph.source_policy import load_policy
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'policy.json'
            p.write_text(json.dumps({'schema_version': 'automator-source-policy/v1',
                                     'repo_id': 'isaacautomator', 'files': ['src/example.py']}))
            loaded = load_policy(p)
            self.assertEqual(loaded['files'], ['src/example.py'])
            self.assertEqual(loaded['repo_id'], 'isaacautomator')

    def test_policy_is_closed_bounded_and_source_ids_are_canonical(self):
        from src.knowledge_graph.source_policy import load_policy, PolicyError, validate_relative_path
        base = {'schema_version': 'automator-source-policy/v1', 'repo_id': 'isaacautomator',
                'files': ['src/example.py']}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'policy.json'
            for change in ({'files': ['src/**']}, {'repo_id': 'https://user:fake@host/repo'},
                           {'files': ['src/a.py', 'src/a.py']}, {'schema_version': 'future'},
                           {'roots': ['.']}, {'max_file_bytes': -1}, {'max_total_bytes': True},
                           {'files': 'src/a.py'}):
                with self.subTest(change=change):
                    p.write_text(json.dumps(base | change))
                    with self.assertRaises(PolicyError) as caught:
                        load_policy(p)
                    self.assertRegex(str(caught.exception), r'^[a-z_]+$')
            for bad in ('../bad', '/etc/passwd', 'a/../b', 'a//b', './x', 'a\\\\b',
                        'a\x00b', 'x\ny', '', 'a/%2e%2e/b', 'https://x', 'a/*'):
                with self.subTest(path=bad), self.assertRaises(PolicyError):
                    validate_relative_path(bad)
            self.assertEqual(validate_relative_path('src/a-b_2.py'), 'src/a-b_2.py')

    def test_yaml_policy_and_safe_load_failures(self):
        from src.knowledge_graph.source_policy import load_policy, PolicyError
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'policy.yaml'
            p.write_text('schema_version: automator-source-policy/v1\nrepo_id: isaacautomator\nfiles: [src/a.py]\n')
            self.assertEqual(load_policy(p)['files'], ['src/a.py'])
            for text in ('!!python/object/apply:os.system [never-run]', 'files: [\n', 'files: []\nfiles: []\n'):
                p.write_text(text)
                with self.assertRaises(PolicyError):
                    load_policy(p)
            p.unlink()
            p.symlink_to('absent')
            with self.assertRaises(PolicyError):
                load_policy(p)

    def test_policy_parent_symlink_and_hardlink_are_refused(self):
        import os
        from src.knowledge_graph.source_policy import load_policy, PolicyError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'real').mkdir()
            p = root / 'real' / 'p.yaml'
            p.write_text('schema_version: automator-source-policy/v1\nrepo_id: isaacautomator\nfiles: []\n')
            (root / 'alias').symlink_to('real', target_is_directory=True)
            with self.assertRaises(PolicyError):
                load_policy(root / 'alias' / 'p.yaml')
            os.link(p, root / 'hard.yaml')
            with self.assertRaises(PolicyError):
                load_policy(root / 'hard.yaml')


if __name__ == '__main__':
    unittest.main()
