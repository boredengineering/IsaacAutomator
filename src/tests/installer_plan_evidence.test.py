"""Pure evidence boundary tests; inspect only disposable synthetic fixtures."""
import importlib.util
import json
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
CORE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core'


def load(name):
    spec = importlib.util.spec_from_file_location('test_evidence_' + name, CORE / (name + '.py'))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvidenceTests(unittest.TestCase):
    def api(self):
        self.assertTrue((CORE / 'plan_evidence.py').is_file(), 'pure evidence validator missing')
        return load('plan_evidence')

    def test_unknown_sensitive_keys_and_malformed_objects_refuse_without_content(self):
        api = self.api()
        canary = 'SYNTHETIC_PRIVATE_CANARY'
        invalid = [None, [], '', False, 0,
                   {'/fixture/target': [canary]},
                   {'/fixture/target': None},
                   {'/fixture/target': {'state': 'missing', 'password': canary}},
                   {'/fixture/target': {'unknown': {'arbitrary': canary}}},
                   {'/fixture/unused': {'token': canary}},
                   {'/fixture/target': {1: canary}}]
        for evidence in invalid:
            with self.subTest(shape=type(evidence).__name__):
                with self.assertRaisesRegex(ValueError, '^invalid plan evidence$') as caught:
                    api.validate_evidence(evidence)
                self.assertNotIn(canary, str(caught.exception))
        self.assertEqual(api.validate_evidence({}), {})
        self.assertEqual(api.validate_evidence({'/fixture/target': {}}), {'/fixture/target': {}})

    def test_exact_typed_fields_reject_malformed_values(self):
        api = self.api()
        invalid = {
            'state': ['secret', None, [], True, 0],
            'operation': ['shell_exec', 'SYNTHETIC_PRIVATE_CANARY', None, []],
            'managed': [0, 1, 'true', None, {}],
            'conflict': [0, 1, 'collision text', [], None],
            'identity': [[], [1], [1, 2, 3], [True, 1], [-1, 1], [1, 2**64], [1, 1.0], (1, 2), {'inode': 1}],
            'fixture_identity': [None, [1, False], [1, 2**10000]],
            'uid': [-1, True, 1.0, 2**32, 2**10000, None],
            'mode': [-1, False, 1.0, 4096, '0700', {}],
            'sha256': ['changed', 'A' * 64, 'a' * 63, 'a' * 65, None, [], 42],
            'tree_sha256': ['canary', {'sha256': 'a' * 64}],
            'desired_digest': [None, 'private', False],
        }
        for field, values in invalid.items():
            for index, value in enumerate(values):
                with self.subTest(field=field, index=index):
                    with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
                        api.validate_evidence({'/fixture/target': {field: value}})
        for numeric in (float('inf'), -float('inf'), float('nan'), 1e999, -1e999):
            for field in ('uid', 'mode', 'state', 'mtime', 'sha256'):
                with self.subTest(field=field, numeric='nonfinite'):
                    with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
                        api.validate_evidence({'/fixture/target': {field: numeric}})

    def test_supported_typed_field_boundaries_are_copied(self):
        api = self.api()
        record = {'state': 'directory', 'identity': [0, 2**64 - 1],
                  'uid': 2**32 - 1, 'mode': 4095, 'managed': True,
                  'conflict': False, 'sha256': 'a' * 64,
                  'tree_sha256': '0' * 64, 'desired_digest': 'b' * 64,
                  'fixture_identity': [0, 0], 'operation': 'repository_checkout'}
        self.assertEqual(api.validate_evidence({'/fixture/target': record}), {'/fixture/target': record})
        for state in ('missing', 'file', 'directory', 'unsupported', 'unknown'):
            self.assertEqual(api.validate_evidence({'/fixture/target': {'state': state}})['/fixture/target']['state'], state)
        for operation in ('mkdir', 'write_file', 'repository_checkout', 'environment_create',
                          'artifact_install', 'package_install', 'settings_change', 'service_setup', 'unsupported'):
            self.assertEqual(api.validate_evidence({'/fixture/target': {'operation': operation}})['/fixture/target']['operation'], operation)

    def test_paths_and_nested_ancestor_records_are_strictly_bounded(self):
        api = self.api()
        bad_paths = ['', '/', 'relative', '//fixture/target', '/fixture//target',
                     '/fixture/./target', '/fixture/../target', '/fixture/target/',
                     '/fixture/target\\name', '/fixture/\x00target', '/fixture/\nsecret',
                     '/fixture/\x7fsecret', '/fixture/\x85secret', '/fixture/\ud800',
                     '/fixture/' + 'a' * 256, '/fixture/' + 'é' * 128,
                     '/' + '/'.join(['a'] * 129), '/' + '/'.join(['a' * 255] * 17),
                     1, None, False]
        for index, path in enumerate(bad_paths):
            with self.subTest(path_index=index):
                with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
                    api.validate_evidence({path: {'state': 'missing'}})
        bad_ancestors = [None, [], {'/fixture': 'SYNTHETIC_PRIVATE_CANARY'},
                         {'/fixture': [1]}, {'/fixture': [1, True]},
                         {'/other': [1, 2]}, {'/fixture/target': [1, 2]},
                         {'/fixture/target/child': [1, 2]}, {'/fix': [1, 2]},
                         {'/fixture/../fixture': [1, 2]}, {1: [1, 2]},
                         {'/fixture': {'identity': [1, 2], 'password': 'canary'}}]
        for index, ancestors in enumerate(bad_ancestors):
            with self.subTest(ancestors_index=index):
                with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
                    api.validate_evidence({'/fixture/target': {'ancestors': ancestors}})
        with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
            api.validate_evidence({'/fixture/' + str(i): {} for i in range(129)})
        with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
            api.validate_evidence({'/fixture/target': {'ancestors': {'/ancestor' + str(i): [1, 2] for i in range(129)}}})
        for path in ('/fixture/space name', '/fixture/é', '/fixture/' + 'a' * 255,
                     '/' + '/'.join(['a'] * 128), '/' + '/'.join(['a' * 255] * 16)):
            self.assertEqual(api.validate_evidence({path: {}}), {path: {}})
        records = {'/fixture/' + str(i): {} for i in range(128)}
        self.assertEqual(api.validate_evidence(records), records)
        records = {'/fixture/target': {'ancestors': {'/fixture': [0, 2**64 - 1]}}}
        self.assertEqual(api.validate_evidence(records), records)

    def test_total_path_budget_refuses_repeated_deep_metadata(self):
        api = self.api()
        parts = ['a' * 31] * 127
        ancestors = {'/' + '/'.join(parts[:i]): [1, i] for i in range(1, 128)}
        target_parent = '/' + '/'.join(parts)
        records = {target_parent + '/' + str(i): {'ancestors': ancestors} for i in range(8)}
        with self.assertRaisesRegex(ValueError, '^invalid plan evidence$'):
            api.validate_evidence(records)

    def test_validator_performs_no_io_and_returns_strict_json(self):
        api = self.api()
        records = {'/synthetic/nonexistent/target': {
            'state': 'missing', 'ancestors': {'/synthetic': [1, 2]},
            'fixture_identity': [1, 2], 'operation': 'mkdir'}}
        with ExitStack() as stack:
            for function in ('builtins.open', 'os.open', 'os.stat', 'os.lstat',
                             'os.scandir', 'os.listdir', 'socket.socket', 'subprocess.Popen'):
                stack.enter_context(patch(function, side_effect=AssertionError('validator performed I/O')))
            copied = api.validate_evidence(records)
        self.assertEqual(json.loads(json.dumps(copied, allow_nan=False)), records)

    def test_cycles_and_custom_objects_refuse_without_invoking_hooks(self):
        api = self.api()

        class Hostile(dict):
            def __deepcopy__(self, memo):
                raise AssertionError('untrusted deepcopy hook called')

            def items(self):
                raise AssertionError('untrusted items hook called')

        class Text(str):
            def encode(self, *args, **kwargs):
                raise AssertionError('untrusted string hook called')

        cycle = {}
        cycle['ancestors'] = cycle
        cases = [Hostile(), {'/fixture/target': Hostile()},
                 {Text('/fixture/target'): {}},
                 {'/fixture/target': {'sha256': Text('a' * 64)}},
                 {'/fixture/target': {'ancestors': Hostile()}},
                 {'/fixture/target': cycle}]
        for index, records in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaisesRegex(api.EvidenceError, '^invalid plan evidence$'):
                    api.validate_evidence(records)

    def test_actual_fixture_journal_qualified_hash_metadata_is_preserved(self):
        api = self.api()
        managed = load('managed_apply')
        planner = load('action_plan')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = str(root / 'tree')
            Path(target).mkdir(mode=0o700)
            desired = {'manager': 'venv', 'fixture_local': True, 'path': target}
            desired_digest = planner.digest(desired)
            fixture = managed.Root(directory)
            try:
                post = fixture.evidence(target)
            finally:
                fixture.close()
            fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
            try:
                tree_hash = managed._builders.tree_digest(fd)
            finally:
                os.close(fd)
            post.update(tree_sha256=tree_hash, desired_digest=desired_digest)
            # Test-only journal fixture, not an apply receipt or actual install.
            record = {'state': 'verified', 'target': target, 'postcondition': post,
                      'desired_digest': desired_digest, 'run': 'a' * 32,
                      'plan': 'b' * 64, 'action': 'runtime.test'}
            journal = root / managed.JOURNAL
            journal.write_text(json.dumps(record) + '\n')
            journal.chmod(0o600)
            original = managed.inspect_fixture(fixture_root=directory, targets=[target])
            self.assertTrue(original[target]['managed'])
            self.assertEqual(original[target]['tree_sha256'], tree_hash)
            self.assertEqual(original[target]['desired_digest'], desired_digest)
            copied = api.validate_evidence(original)
            self.assertEqual(copied, original)
            plan = planner.build_action_plan({'runtimes': {'test': desired}},
                                            target_home=directory, observed=copied)
            self.assertEqual(plan['actions'][0]['preconditions'], original[target])
            json.dumps(plan, allow_nan=False)

    def test_actual_fixture_metadata_is_preserved_without_aliases(self):
        api = self.api()
        managed = load('managed_apply')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'folder').mkdir(mode=0o700)
            (root / 'file').write_bytes(b'synthetic nonsecret fixture\n')
            targets = [str(root / name) for name in ('folder', 'file', 'missing')]
            original = managed.inspect_fixture(fixture_root=directory, targets=targets)
            copied = api.validate_evidence(original)
            self.assertEqual(copied, original)
            self.assertIsNot(copied, original)
            for target in targets:
                self.assertIsNot(copied[target], original[target])
                self.assertIsNot(copied[target]['ancestors'], original[target]['ancestors'])
                self.assertIsNot(copied[target]['fixture_identity'], original[target]['fixture_identity'])
                self.assertIsNot(copied[target]['ancestors'][directory], original[target]['ancestors'][directory])
            copied[targets[0]]['identity'][0] += 1
            self.assertNotEqual(copied[targets[0]], original[targets[0]])


if __name__ == '__main__':
    unittest.main()
