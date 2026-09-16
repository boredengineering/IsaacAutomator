"""Pure fixcycle2 checks. No fixture creation, subprocess, or filesystem probes.

Run with python3 -B; Root/hash/copy spies guard malformed recovery input.
The existing managed integration suite is deliberately not imported or run.
"""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True


def _deny_mutating_test_events(event, args):
    # Process-wide tripwire: pure tests must never create a fixture or launch a
    # real child, including if a future test accidentally forgets its mocks.
    if event in {'subprocess.Popen', 'os.system', 'os.fork', 'os.exec', 'os.posix_spawn',
                 'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.link', 'os.symlink',
                 'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'socket.connect'}:
        raise AssertionError('nonmutating test boundary: ' + event)
    if event == 'open':
        _, mode, flags = args
        if (mode and any(letter in mode for letter in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError('nonmutating test boundary: writable open')


sys.addaudithook(_deny_mutating_test_events)
SPEC = importlib.util.spec_from_file_location(
    'managed_pure_subject', Path(__file__).resolve().parents[2] /
    'isaac-installer/lib/core/managed_apply.py')
assert SPEC and SPEC.loader
managed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(managed)
builders = managed._builders


def golden_manifest():
    result = {
        'kind': 'managed-file-backup', 'source': '/original/nested/config.json',
        'source_root': '/original', 'backup': '/backups/backup-' + 'a' * 32 + '.bin',
        'original_name': 'config.json', 'original_mode': 0o600, 'original_uid': 1000,
        'precondition': {'state': 'file', 'identity': [1, 2], 'uid': 1000,
                         'mode': 0o600, 'managed': False, 'sha256': 'b' * 64},
    }
    result['digest'] = managed._plan.digest(result)
    return result


class RecoverySchemaTests(unittest.TestCase):
    def test_malformed_schema_refused_before_copy_hash_or_root(self):
        valid = golden_manifest()
        malformed = [None, [], {}, {'kind': 'managed-file-backup'}, True]
        for key in valid:
            item = copy.deepcopy(valid)
            del item[key]
            malformed.append(item)
        for key, value in (
            ('extra', 1), ('kind', []), ('digest', 'z' * 64),
            ('source', '/other/config.json'), ('source', '/original'),
            ('source_root', '/original/nested/config.json'),
            ('original_name', 'other.json'), ('original_name', '../config.json'),
            ('original_uid', True), ('original_uid', -1), ('original_uid', 2**32),
            ('original_mode', True), ('original_mode', 0o644),
            ('backup', '/original/backup-' + 'a' * 32 + '.bin'),
            ('precondition', None),
        ):
            malformed.append({**valid, key: value})
        for key in ('source', 'source_root', 'backup'):
            for value in (None, [], 'relative', '/', '//absolute/x', '/a/../b',
                          '/a/./b', '/a//b', '/a/b/', '/a\\b', '/a\x00b',
                          '/a\ud800b', '/a/' + 'x' * 256, '/a' * 129):
                malformed.append({**valid, key: value})
        for key, value in (
            ('extra', 1), ('state', 'directory'), ('managed', True), ('managed', 0),
            ('identity', [True, 1]), ('identity', [1, 2**64]),
            ('identity', [-1, 1]), ('identity', (1, 2)), ('uid', 2**32),
            ('uid', 1001), ('mode', 0o644), ('sha256', 'x' * 64),
        ):
            malformed.append({**valid, 'precondition': {**valid['precondition'], key: value}})
        for key in valid['precondition']:
            post = dict(valid['precondition']); del post[key]
            malformed.append({**valid, 'precondition': post})
        class HostileDict(dict):
            def __deepcopy__(self, memo):
                raise AssertionError('custom deepcopy reached')
        class HostileStr(str):
            def __eq__(self, other):
                raise AssertionError('custom comparison reached')
        malformed.extend([HostileDict(valid), {**valid, 'source': HostileStr(valid['source'])}])
        for index, item in enumerate(malformed):
            with self.subTest(item_type=type(item).__name__, index=index):
                with patch.object(managed, 'Root', side_effect=AssertionError('Root reached')), \
                     patch.object(managed, 'deepcopy', side_effect=AssertionError('copy reached')), \
                     patch.object(managed._plan, 'digest', side_effect=AssertionError('hash reached')):
                    with self.assertRaises(managed.ApplyError):
                        managed.restore_backup(item, backup_root='/backups', alternate_root='/alternate', approved=True)


class RecoveryGoldenTests(unittest.TestCase):
    def test_golden_metadata_is_copied_without_filesystem(self):
        original = golden_manifest()
        with patch.object(managed, 'Root', side_effect=AssertionError('Root reached')):
            validated = managed._validate_recovery_manifest(original)
        self.assertEqual(validated, {k: v for k, v in original.items() if k != 'digest'})
        validated['precondition']['identity'][0] = 99
        self.assertEqual(original['precondition']['identity'], [1, 2])

    def test_bad_checksum_and_inconsistent_selection_never_open_root(self):
        original = golden_manifest()
        with patch.object(managed, 'Root', side_effect=AssertionError('Root reached')):
            with self.assertRaises(managed.ApplyError):
                managed.restore_backup({**original, 'digest': '0' * 64},
                                       backup_root='/backups', alternate_root='/alternate', approved=True)
            for backup, alternate in (('/elsewhere', '/alternate'), ('/backups', '/original'),
                                      ('/backups', '/original/sub'), ('/backups', '/backups/sub'),
                                      ('/backups/', '/alternate'), ('/backups', '/')):
                with self.subTest(backup=backup, alternate=alternate), self.assertRaises(managed.ApplyError):
                    managed.restore_backup(original, backup_root=backup, alternate_root=alternate, approved=True)
        # Valid metadata reaches only the Root spy: not a restoration success claim.
        with patch.object(managed, 'Root', side_effect=RuntimeError('pure boundary')) as root:
            with self.assertRaisesRegex(RuntimeError, 'pure boundary'):
                managed.restore_backup(original, backup_root='/backups', alternate_root='/alternate', approved=True)
            root.assert_called_once_with('/backups')


class JournalBoundsTests(unittest.TestCase):
    def test_golden_journal_states_remain_accepted(self):
        common = {'run': 'a' * 32, 'plan': 'b' * 64}
        action = {**common, 'action': 'write-config', 'target': '/original/nested/config.json'}
        post = golden_manifest()['precondition']
        records = [
            {**action, 'state': 'intended'},
            {**action, 'state': 'started', 'staging': '/original/nested/.isaac-stage-' + 'c' * 32,
             'staging_identity': [1, 2], 'created_identity': [1, 3]},
            {**action, 'state': 'verified', 'postcondition': post},
            {**action, 'state': 'verified', 'desired_digest': 'd' * 64,
             'postcondition': {'state': 'directory', 'identity': [1, 3], 'mode': 0o700, 'uid': 1000,
                              'managed': False, 'tree_sha256': 'e' * 64, 'desired_digest': 'd' * 64}},
            {**common, 'state': 'recovery_reviewed', 'journal_digest': 'f' * 64, 'reviewed_state': 'failed'},
        ]
        for record in records:
            with self.subTest(state=record['state']):
                self.assertEqual(managed._validate_record(record), record)

    def test_impossible_identity_and_errno_are_refused(self):
        common = {'run': 'a' * 32, 'plan': 'b' * 64}
        for key in ('created_identity', 'staging_identity'):
            for value in ([0, 2**64], [2**128, 2**128], [-1, 0], [True, 0], (1, 2)):
                record = {**common, 'state': 'started', 'action': 'test', 'target': '/fixture/file', key: value}
                if key == 'staging_identity':
                    record['staging'] = '/fixture/.isaac-stage-' + 'c' * 32
                with self.subTest(key=key, value=value), self.assertRaises(managed.ApplyError):
                    managed._validate_record(record)
        for value in (-1, 0, 4096, 2**128, True, 1.5):
            with self.subTest(errno=value), self.assertRaises(managed.ApplyError):
                managed._validate_record({**common, 'state': 'failed', 'error': 'OSError', 'errno': value})

    def test_journal_accepts_only_exact_bounded_builtins(self):
        class Subdict(dict):
            pass
        class Substr(str):
            pass
        record = {'run': 'a' * 32, 'plan': 'b' * 64, 'state': 'intended',
                  'action': 'test', 'target': '/fixture/file'}
        malformed = [Subdict(record), {**record, 'state': Substr('intended')},
                     {**record, 'run': Substr('a' * 32)}, {**record, 'action': Substr('test')},
                     {**record, 'action': '\ud800'}, {**record, 'state': []},
                     {**record, 'plan': 'a' * 4097}]
        for item in malformed:
            with self.subTest(item_type=type(item).__name__), self.assertRaises(managed.ApplyError):
                managed._validate_record(item)

    def test_boundary_metadata_is_accepted(self):
        common = {'run': 'a' * 32, 'plan': 'b' * 64}
        started = {**common, 'state': 'started', 'action': 'test', 'target': '/fixture/file',
                   'created_identity': [0, 2**64 - 1]}
        self.assertEqual(managed._validate_record(started), started)
        for value in (None, 1, 4095):
            record = {**common, 'state': 'failed', 'error': 'OSError', 'errno': value}
            self.assertEqual(managed._validate_record(record), record)


class VenvContractTests(unittest.TestCase):
    @staticmethod
    def inputs():
        return {
            'profile': '02af55f77ef070f9780276299c3a0e98cb7f527ccb58ff9371426edb9007ecd0',
            'version': [3, 10, 12], 'executable': '/usr/bin/python3',
            'interpreter_sha256': 'd' * 64,
            'templates': {
                'activate': [0o644, 'dir=__VENV_DIR__\nprompt=__VENV_PROMPT__\n'],
                'activate.csh': [0o644, 'python=__VENV_PYTHON__\n'],
                'activate.fish': [0o644, 'name=__VENV_NAME__\nbin=__VENV_BIN_NAME__\n'],
                'Activate.ps1': [0o644, '$dir=__VENV_DIR__\n'],
            },
        }

    def test_prebaseline_changes_cannot_become_the_expected_tree(self):
        self.assertTrue(callable(getattr(builders, '_verify_venv_contract', None)),
                        'desired-tree comparison boundary is missing')
        import hashlib
        import json
        expected = builders._venv_contract_rows(self.inputs(), '/proc/self/fd/9/environment', '/fixture/venv-v1')
        def fingerprint(rows):
            return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
        wanted = fingerprint(expected)
        self.assertEqual(builders._verify_venv_contract(wanted, expected), wanted)
        for index, row in enumerate(expected):
            changed = copy.deepcopy(expected)
            if row[1] == 'file':
                changed[index][-1] = 'e' * 64
            elif row[1] == 'symlink':
                changed[index][-1] = '/outside'
            else:
                changed[index][-1] = 0o777
            with self.subTest(path=row[0]), self.assertRaises(builders.BuilderError):
                builders._verify_venv_contract(fingerprint(changed), expected)
        for changed in (expected[:-1], expected + [['extra', 'directory', 0o700]]):
            with self.assertRaises(builders.BuilderError):
                builders._verify_venv_contract(fingerprint(changed), expected)

    def test_unqualified_generation_profiles_are_refused(self):
        for key, value in (('profile', '0' * 64), ('version', [3, 11, 0]),
                           ('executable', '/fixture/python'), ('templates', {})):
            with self.subTest(key=key), self.assertRaises(builders.BuilderError):
                builders._venv_contract_rows({**self.inputs(), key: value}, '/proc/self/fd/9/environment', '/fixture/venv-v1')

    def test_expected_venv_bytes_and_structure_come_from_generation_inputs(self):
        self.assertTrue(callable(getattr(builders, '_venv_contract_rows', None)),
                        'independent generation-input contract is missing')
        import hashlib
        rows = builders._venv_contract_rows(self.inputs(), '/proc/self/fd/9/environment', '/fixture/venv-v1')
        by_path = {row[0]: row[1:] for row in rows}
        self.assertEqual(set(by_path), {'bin', 'bin/python', 'bin/python3', 'bin/python3.10',
            'bin/activate', 'bin/activate.csh', 'bin/activate.fish', 'bin/Activate.ps1',
            'include', 'lib', 'lib/python3.10', 'lib/python3.10/site-packages', 'lib64', 'pyvenv.cfg'})
        for name in ('python', 'python3', 'python3.10'):
            self.assertEqual(by_path['bin/' + name], ['file', 0o755, 'd' * 64])
        cfg = b"home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.10.12\nprompt = 'venv-v1'\n"
        self.assertEqual(by_path['pyvenv.cfg'], ['file', 0o600, hashlib.sha256(cfg).hexdigest()])
        expected = {
            'activate': b"dir=/fixture/venv-v1\nprompt='(venv-v1) '\n",
            'activate.csh': b'python=/fixture/venv-v1/bin/python3\n',
            'activate.fish': b'name=environment\nbin=bin\n',
            'Activate.ps1': b"$dir='/fixture/venv-v1'\n",
        }
        for name, data in expected.items():
            self.assertEqual(by_path['bin/' + name], ['file', 0o644, hashlib.sha256(data).hexdigest()])
        self.assertEqual(by_path['lib64'], ['symlink', 'lib'])
        self.assertEqual(by_path['lib/python3.10/site-packages'], ['directory', 0o700])


class VenvInputBoundaryTests(unittest.TestCase):
    def test_trusted_reader_checks_in_memory_metadata_before_reading(self):
        import io
        import stat
        from types import SimpleNamespace
        class MemoryFile(io.BytesIO):
            def fileno(self):
                return 123
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        good = dict(st_mode=stat.S_IFREG | 0o755, st_uid=0, st_size=3,
                    st_dev=1, st_ino=2, st_mtime_ns=3, st_ctime_ns=4)
        for overrides in ({}, {'st_uid': 1000}, {'st_mode': stat.S_IFIFO | 0o600},
                          {'st_mode': stat.S_IFREG | 0o777}, {'st_size': 0}):
            info = SimpleNamespace(**{**good, **overrides})
            with self.subTest(overrides=overrides), \
                 patch.object(builders.os.path, 'realpath', return_value='/usr/bin/python3.10'), \
                 patch.object(builders.os, 'stat', return_value=directory), \
                 patch.object(builders.os, 'open', return_value=123) as opened, \
                 patch.object(builders.os, 'fdopen', return_value=MemoryFile(b'abc')), \
                 patch.object(builders.os, 'fstat', return_value=info):
                if overrides:
                    with self.assertRaises(builders.BuilderError):
                        builders._read_trusted_generation_file('/usr/bin/python3')
                else:
                    self.assertEqual(builders._read_trusted_generation_file('/usr/bin/python3'), (b'abc', 0o755))
                self.assertEqual(opened.call_args.args[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)

    def test_trusted_inputs_are_loaded_without_reading_generated_tree(self):
        self.assertTrue(callable(getattr(builders, '_trusted_venv_inputs', None)),
                        'trusted generation input loader is missing')
        import hashlib
        from types import SimpleNamespace
        profile = hashlib.sha256(b'audited stdlib').hexdigest()
        reads = []
        def read_trusted(path):
            reads.append(path)
            if path == '/usr/bin/python3':
                return b'trusted interpreter bytes', 0o755
            if path.endswith('__init__.py'):
                return b'audited stdlib', 0o644
            return b'__VENV_DIR__', 0o644
        with patch.object(builders, '_read_trusted_generation_file', side_effect=read_trusted), \
             patch.object(builders, '_VENV_PROFILE', profile), \
             patch.object(builders.subprocess, 'run', return_value=SimpleNamespace(
                 stdout=b'{"version":[3,10,12],"executable":"/usr/bin/python3","platform":"linux","bits":64}')) as run:
            inputs = builders._trusted_venv_inputs()
        self.assertEqual(inputs['interpreter_sha256'], hashlib.sha256(b'trusted interpreter bytes').hexdigest())
        self.assertEqual(inputs['profile'], profile)
        self.assertEqual(set(inputs['templates']), set(builders._VENV_TEMPLATES))
        self.assertTrue(all(path.startswith('/usr/') for path in reads))
        self.assertEqual(run.call_args.args[0][:4], ['/usr/bin/python3', '-I', '-B', '-c'])
        self.assertNotIn('venv', run.call_args.args[0][4])

    def test_creation_source_wires_independent_contract_before_generation(self):
        # Static wiring only: this does not execute build_environment or qualify IO.
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(builders.build_environment))
        calls = {name: [] for name in ('_trusted_venv_inputs', '_venv_contract_rows', '_verify_venv_contract')}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in calls:
                calls[node.func.id].append(node.lineno)
        self.assertEqual(len(calls['_trusted_venv_inputs']), 1)
        self.assertEqual(len(calls['_venv_contract_rows']), 2)
        self.assertEqual(len(calls['_verify_venv_contract']), 2)
        generating = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and node.func.attr == 'run']
        self.assertEqual(len(generating), 1)
        self.assertLess(max(calls['_venv_contract_rows']), generating[0])
        self.assertLess(calls['_trusted_venv_inputs'][0], min(calls['_venv_contract_rows']))


if __name__ == '__main__':
    unittest.main()
