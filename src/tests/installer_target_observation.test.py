"""Metadata bridge tests: observation only in confined synthetic children."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
CORE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core'


class TargetObservationTests(unittest.TestCase):
    def api(self):
        self.assertTrue((CORE / 'target_observation.py').is_file(), 'bounded target observer missing')
        spec = importlib.util.spec_from_file_location('test_target_observation', CORE / 'target_observation.py')
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def confined(self, root, body):
        self.api()
        source = root / 'desired-profile.json'
        source.write_text('{}')
        source.chmod(0o644)
        root.chmod(0o755)
        script = f'''import sys, os, json, builtins
sys.dont_write_bytecode = True
sys.path.insert(0, {str(CORE)!r})
import target_observation as observer
import action_plan as planner
import plan_evidence
import preview_sandbox as sandbox
root = {str(root)!r}
home = root + '/home'
if os.geteuid() == 0:
    os.setgroups([])
    os.setresgid(65534, 65534, 65534)
    os.setresuid(65534, 65534, 65534)
sandbox.confine_readonly([{str(source)!r}])
{body}
'''
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', result.stdout)
        return json.loads(result.stdout)

    def test_missing_and_present_targets_supply_strict_unmanaged_metadata(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir(mode=0o755)
            folder = home / 'workspace'
            folder.mkdir(mode=0o755)
            existing = home / 'existing'
            existing.write_text('SYNTHETIC_PRIVATE_CANARY')
            existing.chmod(0o640)
            (home / 'unselected').write_text('SYNTHETIC_PRIVATE_CANARY')
            expected = existing.stat()
            result = self.confined(root, '''profile = {
 'workspace': {'root': home + '/workspace', 'layout': 'flat'},
 'managed_files': [{'path': home + '/existing', 'content': 'new'},
                   {'path': home + '/missing/descendant', 'content': 'new'}]}
plan = planner.build_action_plan(profile, target_home=home)
evidence = observer.collect_evidence(plan, target_home=home)
assert evidence == plan_evidence.validate_evidence(evidence)
updated = planner.build_action_plan(profile, target_home=home, observed=evidence)
print(json.dumps({'evidence': evidence, 'statuses': [a['status'] for a in updated['actions']]}))''')
            evidence = result['evidence']
            self.assertEqual(set(evidence), {str(folder), str(existing), str(home / 'missing/descendant')})
            self.assertEqual(evidence[str(existing)], {'state': 'file', 'identity': [expected.st_dev, expected.st_ino], 'mode': 0o640, 'managed': False})
            self.assertEqual(evidence[str(folder)]['state'], 'directory')
            self.assertEqual(evidence[str(home / 'missing/descendant')], {'state': 'missing', 'managed': False})
            self.assertEqual(result['statuses'], ['satisfied', 'blocked', 'would_change'])

    def test_linked_special_and_non_directory_ancestors_are_blocked_without_identity(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir(mode=0o755)
            canary = root / 'unselected'
            canary.write_text('SYNTHETIC_PRIVATE_CANARY')
            (home / 'symlink').symlink_to(canary)
            (home / 'linked-parent').symlink_to(root, target_is_directory=True)
            os.link(canary, home / 'hardlink')
            os.mkfifo(home / 'fifo')
            (home / 'file-parent').write_text('SYNTHETIC_PRIVATE_CANARY')
            targets = ['symlink', 'linked-parent/missing/child', 'hardlink', 'fifo', 'file-parent/child']
            result = self.confined(root, f'''targets = {targets!r}
plan = planner.build_action_plan({{'managed_files': [{{'path': home + '/' + name, 'content': ''}} for name in targets]}}, target_home=home)
print(json.dumps(observer.collect_evidence(plan, target_home=home)))''')
            self.assertEqual(set(result), {str(home / target) for target in targets})
            for record in result.values():
                self.assertEqual(record, {'state': 'unsupported', 'managed': False, 'conflict': True})

    def test_mount_transition_blocks_before_descendant_even_same_device(self):
        api = self.api()
        self.assertTrue(callable(getattr(api, '_mount_id', None)), 'descriptor mount-ID validation missing')
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir(mode=0o755)
            boundary = home / 'boundary'
            boundary.mkdir(mode=0o755)
            (boundary / 'unselected').write_text('SYNTHETIC_PRIVATE_CANARY')
            inode = boundary.stat().st_ino
            result = self.confined(root, f'''original_mount_id = observer._mount_id
# Simulate a same-device bind mount without requiring host mount privileges.
# All descriptors and real statx calls still concern this synthetic fixture.
def mount_id(fd):
    value = original_mount_id(fd)
    return value + 1 if os.fstat(fd).st_ino == {inode} else value
observer._mount_id = mount_id
original_open = os.open
def guarded_open(path, flags, **kwargs):
    assert path != 'unselected', 'crossed the simulated mount boundary'
    return original_open(path, flags, **kwargs)
os.open = guarded_open
plan = planner.build_action_plan({{'managed_files': [{{'path': home + '/boundary/unselected', 'content': ''}}]}}, target_home=home)
print(json.dumps(observer.collect_evidence(plan, target_home=home)))''')
            self.assertEqual(result[str(boundary / 'unselected')], {'state': 'unsupported', 'managed': False, 'conflict': True})

    def test_invalid_selection_and_budgets_refuse_before_any_target_io(self):
        from copy import deepcopy
        from unittest.mock import patch
        api = self.api()
        good = {'kind': 'installer-action-plan', 'version': 1, 'target_home': '/synthetic/home',
                'actions': [{'target': '/synthetic/home/one'}, {'target': '/synthetic/home/two'}]}
        variants = [(good, '/synthetic/home', value) for value in (0, -1, True, 129, '2', 1)]
        variants += [(good, '/synthetic/other', 128), (None, '/synthetic/home', 128)]
        for target in ('/', '/synthetic/../secret', '/synthetic//secret', '/synthetic/x/', '/synthetic/\x00x', 42):
            altered = deepcopy(good)
            altered['actions'].append({'target': target})
            variants.append((altered, '/synthetic/home', 128))
        altered = deepcopy(good)
        altered['actions'] *= 257
        variants.append((altered, '/synthetic/home', 128))
        with patch('os.open', side_effect=AssertionError('invalid selection performed I/O')):
            for index, (plan, home, limit) in enumerate(variants):
                with self.subTest(case=index):
                    with self.assertRaisesRegex(ValueError, '^invalid target observation request$'):
                        api.collect_evidence(plan, target_home=home, max_targets=limit)

    def test_inaccessible_ancestor_and_unavailable_mount_metadata_stay_unknown(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir(mode=0o755)
            locked = home / 'locked'
            locked.mkdir(mode=0)
            try:
                result = self.confined(root, '''plan = planner.build_action_plan({'managed_files': [{'path': home + '/locked/absent', 'content': ''}]}, target_home=home)
first = observer.collect_evidence(plan, target_home=home)
def unavailable(fd):
    raise OSError(95, 'SYNTHETIC_PRIVATE_CANARY')
observer._mount_id = unavailable
second = observer.collect_evidence(plan, target_home=home)
print(json.dumps([first, second]))''')
                for evidence in result:
                    self.assertEqual(evidence[str(locked / 'absent')], {'state': 'unknown', 'managed': False, 'conflict': True})
            finally:
                locked.chmod(0o700)

    def test_expired_deadline_does_not_open_any_target(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'time'), 'bounded monotonic deadline missing')
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            (root / 'home').mkdir(mode=0o755)
            result = self.confined(root, '''plan = planner.build_action_plan({'managed_files': [{'path': home + '/one', 'content': ''}, {'path': home + '/two', 'content': ''}]}, target_home=home)
ticks = iter([0.0, 2.0, 2.0, 2.0, 2.0])
observer.time.monotonic = lambda: next(ticks)
def forbidden(*args, **kwargs):
    raise AssertionError('expired observer attempted target I/O')
os.open = forbidden
print(json.dumps(observer.collect_evidence(plan, target_home=home)))''')
            self.assertEqual(len(result), 2)
            for record in result.values():
                self.assertEqual(record, {'state': 'unknown', 'managed': False, 'conflict': True})

    def test_deadline_expiring_during_final_metadata_discards_result_and_closes_fds(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            (root / 'home').mkdir(mode=0o755)
            (root / 'home/final').write_text('SYNTHETIC_PRIVATE_CANARY')
            result = self.confined(root, '''plan = planner.build_action_plan({'managed_files': [{'path': home + '/final', 'content': ''}]}, target_home=home)
clock = [0.0]
observer.time.monotonic = lambda: clock[0]
original_open = os.open
opened = []
def track_open(path, flags, **kwargs):
    fd = original_open(path, flags, **kwargs)
    opened.append(fd)
    if path == 'final':
        clock[0] = 2.0
    return fd
os.open = track_open
evidence = observer.collect_evidence(plan, target_home=home)
for fd in set(opened):
    try:
        os.fstat(fd)
    except OSError as error:
        assert error.errno == 9
    else:
        raise AssertionError('observer leaked a target descriptor')
print(json.dumps(evidence))''')
            self.assertEqual(result[str(root / 'home/final')], {'state': 'unknown', 'managed': False, 'conflict': True})

    def test_only_selected_names_opened_and_profile_only_content_grants_remain(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir(mode=0o755)
            (home / 'selected').write_text('SYNTHETIC_PRIVATE_CANARY')
            (home / 'disabled').write_text('SYNTHETIC_PRIVATE_CANARY')
            (home / 'unselected').write_text('SYNTHETIC_PRIVATE_CANARY')
            result = self.confined(root, '''profile = {'managed_files': [
 {'path': home + '/selected', 'content': ''},
 {'path': home + '/selected', 'content': ''},
 {'path': home + '/disabled', 'enabled': False, 'content': ''}],
 'tools': {'logical-only': {'enabled': True}}}
plan = planner.build_action_plan(profile, target_home=home)
with open(root + '/desired-profile.json') as source:
    assert source.read() == '{}'
for forbidden in (home + '/selected', home + '/unselected'):
    try:
        open(forbidden).close()
    except PermissionError:
        pass
    else:
        raise AssertionError('target content read grant was widened')
try:
    os.listdir(home)
except PermissionError:
    pass
else:
    raise AssertionError('target listing grant was widened')
opened = []
def audit(event, args):
    if event == 'open':
        assert args[2] & os.O_PATH, 'content-capable open attempted'
        if args[0] != '/':
            assert args[2] & os.O_NOFOLLOW
            assert '/' not in args[0], 'non-component open attempted'
        opened.append(args[0])
    assert event not in ('os.listdir', 'os.scandir', 'subprocess.Popen', 'os.system'), event
sys.addaudithook(audit)
evidence = observer.collect_evidence(plan, target_home=home, max_targets=1)
assert opened == ['/'] + (home + '/selected')[1:].split('/')
print(json.dumps(evidence))''')
            self.assertEqual(set(result), {str(home / 'selected')})
            self.assertEqual(result[str(home / 'selected')]['managed'], False)

    def test_existing_checkout_and_environment_never_infer_managed_or_clean(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir(mode=0o755)
            for name in ('checkout', 'environment'):
                target = home / name
                target.mkdir(mode=0o755)
                (target / '.git').write_text('SYNTHETIC_PRIVATE_CANARY')
                if os.geteuid() == 0:
                    os.chown(target, 65534, 65534)
            result = self.confined(root, '''profile = {
 'components': {'lab': {'enabled': True, 'path': home + '/checkout',
  'source': {'fixture_local': True, 'repository': root + '/not-selected-source', 'revision': 'a' * 40}}},
 'runtimes': {'lab': {'enabled': True, 'manager': 'venv', 'fixture_local': True, 'path': home + '/environment'}}}
plan = planner.build_action_plan(profile, target_home=home)
evidence = observer.collect_evidence(plan, target_home=home)
updated = planner.build_action_plan(profile, target_home=home, observed=evidence)
print(json.dumps({'evidence': evidence, 'statuses': [a['status'] for a in updated['actions']]}))''')
            self.assertEqual(result['statuses'], ['blocked', 'blocked'])
            for record in result['evidence'].values():
                self.assertEqual(set(record), {'state', 'identity', 'mode', 'managed'})
                self.assertFalse(record['managed'])
                self.assertEqual(record['state'], 'directory')

    def test_statx_failure_and_missing_mount_id_mask_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='isaac-observation-') as directory:
            root = Path(directory)
            (root / 'home').mkdir(mode=0o755)
            result = self.confined(root, '''plan = planner.build_action_plan({'managed_files': [{'path': home + '/missing', 'content': ''}]}, target_home=home)
results = []
for return_value in (-1, 0):
    # statx unavailable, or success without requested mount-ID capability.
    observer._libc.syscall = lambda *args: return_value
    results.append(observer.collect_evidence(plan, target_home=home))
print(json.dumps(results))''')
            for evidence in result:
                self.assertEqual(evidence[str(root / 'home/missing')], {'state': 'unknown', 'managed': False, 'conflict': True})

    def test_no_filesystem_targets_means_no_home_probe_or_implicit_discovery(self):
        from unittest.mock import patch
        api = self.api()
        plan = {'kind': 'installer-action-plan', 'version': 1, 'target_home': '/synthetic/home',
                'actions': [{'target': 'unresolved-runtime-prefix:conda:lab'},
                            {'target': '/synthetic/home/disabled', 'status': 'excluded'}]}
        with patch('os.open', side_effect=AssertionError('unselected path observation')):
            self.assertEqual(api.collect_evidence(plan, target_home='/synthetic/home'), {})
            plan['actions'] = []
            self.assertEqual(api.collect_evidence(plan, target_home='/synthetic/home'), {})


if __name__ == '__main__':
    unittest.main()
