"""Only real disposable targets; no installer, network, settings or cloud."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
CORE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core'

def load(name):
    spec = importlib.util.spec_from_file_location(name, CORE / (name + '.py'))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='isaac-managed-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.planner = load('action_plan')

    def api(self):
        self.assertTrue((CORE / 'managed_apply.py').exists(), 'bounded executor missing')
        return load('managed_apply')

    def make_plan(self, api, content='{}\n', filename='config-v1.json'):
        profile = {'workspace': {'root': str(self.root / 'work')}, 'managed_files': [{'path': str(self.root / 'work' / filename), 'content': content}]}
        initial = self.planner.build_action_plan(profile, target_home=str(self.root))
        evidence = api.inspect_fixture(fixture_root=str(self.root), targets=[a['target'] for a in initial['actions']])
        return self.planner.build_action_plan(profile, target_home=str(self.root), observed=evidence)

    def test_same_plan_execution_then_unchanged_rerun_and_single_new_version(self):
        api = self.api()
        plan = self.make_plan(api)
        with self.assertRaises(api.ApplyError):
            api.apply_plan(plan, fixture_root=str(self.root))
        self.assertEqual(list(self.root.iterdir()), [])
        result = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['changed'], ['workspace.root', 'managed_file.0'])
        target = self.root / 'work/config-v1.json'
        self.assertEqual(target.read_text(), '{}\n')
        before = target.stat()
        rerun = self.make_plan(api)
        self.assertEqual([a['status'] for a in rerun['actions']], ['satisfied', 'satisfied'])
        self.assertEqual(api.apply_plan(rerun, fixture_root=str(self.root), approved=True)['changed'], [])
        self.assertEqual(target.stat().st_ino, before.st_ino)
        change = self.make_plan(api, '{"version":2}\n', 'config-v2.json')
        self.assertEqual(api.apply_plan(change, fixture_root=str(self.root), approved=True)['changed'], ['managed_file.0'])
        self.assertEqual(target.read_text(), '{}\n')
        journal = api.read_journal(fixture_root=str(self.root))
        self.assertTrue({'intended', 'started', 'verified'} <= {e['state'] for e in journal})

    def test_failure_journal_partial_files_and_no_automatic_resume(self):
        api = self.api()
        for error in (OSError(errno.ENOSPC, 'disk full'), PermissionError(errno.EACCES, 'denied'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory(prefix='isaac-fault-') as root:
                old = self.root; self.root = Path(root)
                plan = self.make_plan(api)
                def fail(stage, action):
                    if action['operation'] == 'write_file' and stage == 'stage_write':
                        raise error
                result = api.apply_plan(plan, fixture_root=root, approved=True, fault=fail)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['changed'], ['workspace.root'])
                self.assertFalse((self.root / 'work/config-v1.json').exists())
                events = api.read_journal(fixture_root=root)
                self.assertEqual(events[-1]['state'], 'failed')
                self.assertFalse(any(e['state'] == 'verified' and e['action'] == 'managed_file.0' for e in events))
                fresh = self.make_plan(api)
                with self.assertRaises(api.ApplyError):
                    api.apply_plan(fresh, fixture_root=root, approved=True)
                self.assertTrue(hasattr(api, 'review_recovery'), 'explicit bounded recovery review API missing')
                with self.assertRaises(api.ApplyError):
                    api.review_recovery(fixture_root=root, run_ids=[result['run']], journal_digest='0' * 64, approved=True)
                reviewed = api.review_recovery(fixture_root=root, run_ids=[result['run']], journal_digest=self.planner.digest(events), approved=True)
                self.assertEqual(reviewed['status'], 'reviewed')
                self.assertEqual(api.apply_plan(self.make_plan(api), fixture_root=root, approved=True)['status'], 'verified')
                self.root = old

    def test_overlapping_runs_are_locked_including_nested_fixture_roots(self):
        api = self.api()
        nested = self.root / 'nested'; nested.mkdir(mode=0o700)
        plan = self.make_plan(api)
        attempts = []
        def concurrent(stage, action):
            if stage == 'before_mutation' and not attempts:
                for root in (self.root, nested):
                    other = self.planner.build_action_plan({'workspace': {'root': str(root / 'other')}}, target_home=str(root), observed={str(root / 'other'): {'state': 'missing'}})
                    try:
                        api.apply_plan(other, fixture_root=str(root), approved=True)
                    except api.ApplyError as error:
                        attempts.append(str(error))
        result = api.apply_plan(plan, fixture_root=str(self.root), approved=True, fault=concurrent)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all('lock' in message for message in attempts))
        self.assertFalse((nested / 'other').exists())

    def test_changed_root_and_parent_identity_refuse_race_without_escape(self):
        api = self.api()
        plan = self.make_plan(api)
        moved = self.root / 'moved'
        def race(stage, action):
            if stage == 'before_mutation' and action['operation'] == 'write_file':
                (self.root / 'work').rename(moved)
                (self.root / 'work').mkdir(mode=0o700)
        result = api.apply_plan(plan, fixture_root=str(self.root), approved=True, fault=race)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse((self.root / 'work/config-v1.json').exists())
        self.assertFalse((moved / 'config-v1.json').exists())
        self.assertEqual(api.read_journal(fixture_root=str(self.root))[-1]['state'], 'failed')

    def test_new_local_pinned_repository_real_checkout_and_idempotence(self):
        api = self.api()
        import subprocess
        source = self.root / 'source'; source.mkdir(mode=0o700)
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}
        def git(*args):
            return subprocess.check_output(['/usr/bin/git', '-C', str(source), *args], env=env, stderr=subprocess.DEVNULL).decode().strip()
        git('init'); (source / 'README').write_text('fixture repo\n'); git('add', 'README'); git('commit', '-m', 'fixture')
        revision = git('rev-parse', 'HEAD')
        target = self.root / 'checkout-v1'
        profile = {'components': {'lab': {'enabled': True, 'path': str(target), 'source': {'repository': str(source), 'revision': revision, 'mode': 'git', 'fixture_local': True}}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        self.assertTrue(plan['actions'][0]['execution_supported'], 'local new-checkout adapter missing')
        result = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(result['status'], 'verified', result)
        self.assertEqual((target / 'README').read_text(), 'fixture repo\n')
        self.assertNotEqual((target / '.git/objects' / revision[:2] / revision[2:]).stat().st_ino, (source / '.git/objects' / revision[:2] / revision[2:]).stat().st_ino)
        rerun = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        self.assertEqual(rerun['actions'][0]['status'], 'satisfied')
        self.assertEqual(api.apply_plan(rerun, fixture_root=str(self.root), approved=True)['changed'], [])
        (target / 'untracked').write_text('preserve')
        drift = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        self.assertEqual(drift['actions'][0]['status'], 'blocked')
        self.assertEqual((target / 'untracked').read_text(), 'preserve')
        target2 = self.root / 'checkout-v2'
        profile['components']['lab']['path'] = str(target2)
        plan2 = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target2)]))
        def dirty_published(stage, action):
            if stage == 'after_mutation':
                (target2 / 'README').write_text('unexpected published edit')
        failed = api.apply_plan(plan2, fixture_root=str(self.root), approved=True, fault=dirty_published)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual((target2 / 'README').read_text(), 'unexpected published edit')

    def test_new_venv_real_python_and_activation_use_final_versioned_prefix(self):
        api = self.api()
        import subprocess
        target = self.root / 'env-v1'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        self.assertTrue(plan['actions'][0]['execution_supported'], 'new venv builder missing')
        receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(receipt['status'], 'verified', receipt)
        output = subprocess.check_output([str(target / 'bin/python'), '-I', '-c', 'import sys; print(sys.prefix)'], env={'PATH': '/usr/bin:/bin'}).decode().strip()
        self.assertEqual(output, str(target))
        self.assertIn(str(target), (target / 'bin/activate').read_text())
        self.assertNotIn('.isaac-stage-', (target / 'bin/activate').read_text())
        rerun = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        self.assertEqual(rerun['actions'][0]['status'], 'satisfied')
        self.assertEqual(api.apply_plan(rerun, fixture_root=str(self.root), approved=True)['changed'], [])

    def test_exact_action_selection_draft_and_high_risk_preflight(self):
        api = self.api()
        plan = self.make_plan(api)
        for ids in (['unknown'], ['workspace.root', 'workspace.root'], []):
            with self.subTest(ids=ids), self.assertRaises(api.ApplyError):
                api.apply_plan(plan, fixture_root=str(self.root), approved=True, action_ids=ids)
        plan['draft'] = True
        plan['digest'] = self.planner.digest({k: v for k, v in plan.items() if k != 'digest'})
        with self.assertRaises(api.ApplyError):
            api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        result = api.apply_plan(plan, fixture_root=str(self.root), approved=True, action_ids=['workspace.root'])
        self.assertEqual(result['changed'], ['workspace.root'])
        high = self.make_plan(api)
        high['actions'][1]['policy']['high_risk'] = True
        high['digest'] = self.planner.digest({k: v for k, v in high.items() if k != 'digest'})
        with self.assertRaises(api.ApplyError):
            api.apply_plan(high, fixture_root=str(self.root), approved=True)
        self.assertFalse((self.root / 'work/config-v1.json').exists())

    def test_managed_backup_alternate_restore_checks_bytes_and_preserves_edits(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'backup_managed_file'), 'managed recovery missing')
        api.apply_plan(self.make_plan(api), fixture_root=str(self.root), approved=True)
        target = self.root / 'work/config-v1.json'
        with tempfile.TemporaryDirectory(prefix='isaac-backup-') as backup, tempfile.TemporaryDirectory(prefix='isaac-restore-') as alternate:
            manifest = api.backup_managed_file(fixture_root=str(self.root), target=str(target), backup_root=backup, approved=True)
            receipt = api.restore_backup(manifest, backup_root=backup, alternate_root=alternate, approved=True)
            self.assertEqual(receipt['status'], 'verified')
            restored = Path(receipt['target'])
            self.assertEqual(restored.read_bytes(), target.read_bytes())
            self.assertEqual(restored.stat().st_mode & 0o777, target.stat().st_mode & 0o777)
            target.write_text('user edit')
            with self.assertRaises(api.ApplyError):
                api.backup_managed_file(fixture_root=str(self.root), target=str(target), backup_root=backup, approved=True)
            restored.write_text('alternate user edit')
            with self.assertRaises((api.ApplyError, FileExistsError)):
                api.restore_backup(manifest, backup_root=backup, alternate_root=alternate, approved=True)
            self.assertEqual(restored.read_text(), 'alternate user edit')
            self.assertEqual(target.read_text(), 'user edit')

    def test_changed_new_file_is_not_verified_or_cleaned_up(self):
        api = self.api()
        target = self.root / 'work/config-v1.json'
        def edit(stage, action):
            if stage == 'after_mutation' and action['operation'] == 'write_file':
                target.write_text('subsequent user content')
        receipt = api.apply_plan(self.make_plan(api), fixture_root=str(self.root), approved=True, fault=edit)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(target.read_text(), 'subsequent user content')
        events = api.read_journal(fixture_root=str(self.root))
        self.assertFalse(any(e.get('action') == 'managed_file.0' and e['state'] == 'verified' for e in events))
        self.assertFalse(api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)])[str(target)]['managed'])

    def test_atomic_file_staging_cannot_unlink_or_publish_foreign_names(self):
        api = self.api()
        injected = []
        def replace_stage(stage, action):
            if stage == 'stage_write':
                for path in (self.root / 'work').glob('.isaac-stage-*'):
                    path.unlink(); path.write_text('foreign staging replacement'); injected.append(path)
        receipt = api.apply_plan(self.make_plan(api), fixture_root=str(self.root), approved=True, fault=replace_stage)
        self.assertEqual(receipt['status'], 'verified', receipt)
        self.assertEqual((self.root / 'work/config-v1.json').read_text(), '{}\n')
        self.assertTrue(all(p.read_text() == 'foreign staging replacement' for p in injected))

    def test_real_sigterm_leaves_started_journal_and_refuses_automatic_resume(self):
        api = self.api()
        import signal
        plan = self.make_plan(api)
        pid = os.fork()
        if pid == 0:
            def terminate(stage, action):
                if stage == 'stage_write':
                    os.kill(os.getpid(), signal.SIGTERM)
            api.apply_plan(plan, fixture_root=str(self.root), approved=True, fault=terminate)
            os._exit(90)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGTERM)
        journal = api.read_journal(fixture_root=str(self.root))
        self.assertEqual(journal[-1]['state'], 'started')
        fresh = self.make_plan(api)
        with self.assertRaises(api.ApplyError):
            api.apply_plan(fresh, fixture_root=str(self.root), approved=True)
        self.assertFalse((self.root / 'work/config-v1.json').exists())

    def test_real_path_guards_case_permissions_symlinks_hardlinks_and_foreign_owner(self):
        api = self.api()
        case = self.root / 'Work'; case.mkdir(mode=0o700)
        with self.assertRaises(api.ApplyError):
            self.make_plan(api)
        case.rmdir()
        restricted = self.root / 'work'; restricted.mkdir(mode=0o500)
        with self.assertRaises(api.ApplyError):
            self.make_plan(api)
        restricted.chmod(0o700); restricted.rmdir()
        with tempfile.TemporaryDirectory(prefix='isaac-outside-') as outside:
            (self.root / 'work').symlink_to(outside, target_is_directory=True)
            with self.assertRaises((api.ApplyError, OSError)):
                self.make_plan(api)
            self.assertEqual(list(Path(outside).iterdir()), [])
            (self.root / 'work').unlink()
        restricted.mkdir(mode=0o700)
        target = restricted / 'config-v1.json'; target.write_text('user')
        alias = restricted / 'alias'; os.link(target, alias)
        with self.assertRaises(api.ApplyError):
            self.make_plan(api)
        alias.unlink()
        if os.geteuid() == 0:
            os.chown(target, 65534, 65534)
            with self.assertRaises(api.ApplyError):
                self.make_plan(api)
            os.chown(target, 0, 0)
        self.assertEqual(target.read_text(), 'user')

    def test_preview_is_bound_to_root_and_existing_parent_inodes(self):
        api = self.api()
        plan = self.make_plan(api)
        parked = self.root.with_name(self.root.name + '-parked')
        self.root.rename(parked)
        self.root.mkdir(mode=0o700)
        try:
            with self.assertRaises(api.ApplyError):
                api.apply_plan(plan, fixture_root=str(self.root), approved=True)
            self.assertEqual(list(self.root.iterdir()), [])
        finally:
            self.root.rmdir(); parked.rename(self.root)
        (self.root / 'work').mkdir(mode=0o700)
        plan = self.make_plan(api)
        moved = self.root / 'old-parent'
        (self.root / 'work').rename(moved); (self.root / 'work').mkdir(mode=0o700)
        with self.assertRaises(api.ApplyError):
            api.apply_plan(plan, fixture_root=str(self.root), approved=True, action_ids=['managed_file.0'])
        self.assertFalse((self.root / 'work/config-v1.json').exists())

    def test_repository_source_config_helpers_refused_before_publication(self):
        api = self.api()
        import subprocess
        source = self.root / 'source'; source.mkdir(mode=0o700)
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
        subprocess.run(['/usr/bin/git', 'init', str(source)], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        config = source / '.git/config'
        config.write_text(config.read_text() + '\n[include]\n path = /outside-unapproved-config\n')
        target = self.root / 'checkout'
        profile = {'components': {'lab': {'enabled': True, 'path': str(target), 'source': {'repository': str(source), 'revision': 'a' * 40, 'fixture_local': True}}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['error']['error'], 'BuilderError', 'unsafe config must be rejected before invoking Git, not merely fail checkout')
        self.assertFalse(target.exists())

    def test_owned_unprivileged_fixture_positive_path(self):
        api = self.api()
        uid = 65534 if os.geteuid() == 0 else os.geteuid()
        if os.geteuid() == 0:
            os.chown(self.root, uid, uid)
        pid = os.fork()
        if pid == 0:
            try:
                if os.geteuid() == 0:
                    os.setgroups([]); os.setgid(uid); os.setuid(uid)
                receipt = api.apply_plan(self.make_plan(api), fixture_root=str(self.root), approved=True)
                assert receipt['status'] == 'verified', receipt
                assert (self.root / 'work/config-v1.json').read_text() == '{}\n'
                target = self.root / 'env-unprivileged'
                profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
                plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
                assert api.apply_plan(plan, fixture_root=str(self.root), approved=True)['status'] == 'verified'
                assert str(target) in (target / 'bin/activate').read_text()
                os._exit(0)
            except BaseException:
                os._exit(91)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFEXITED(status))
        self.assertEqual(os.WEXITSTATUS(status), 0, 'ordinary-user positive path failed')

    def test_new_name_collision_never_overwrites_racing_user_file(self):
        api = self.api()
        target = self.root / 'work/config-v1.json'
        def occupy(stage, action):
            if stage == 'stage_write':
                target.write_text('foreign arrival')
        receipt = api.apply_plan(self.make_plan(api), fixture_root=str(self.root), approved=True, fault=occupy)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(target.read_text(), 'foreign arrival')
        self.assertFalse(api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)])[str(target)]['managed'])

    def test_directory_builder_preserves_racing_new_target_and_failed_stage(self):
        api = self.api()
        target = self.root / 'env-race'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        def race(stage, action):
            if stage == 'before_publish':
                target.mkdir(mode=0o700); (target / 'user').write_text('preserve')
        receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True, fault=race)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual((target / 'user').read_text(), 'preserve')
        self.assertTrue(list(self.root.glob('.isaac-stage-*')))
        self.assertTrue(any(e.get('staging_identity') for e in api.read_journal(fixture_root=str(self.root))))

    def test_git_expanded_content_budget_refuses_before_checkout_writes(self):
        api = self.api()
        import subprocess
        source = self.root / 'source'; source.mkdir(mode=0o700)
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}
        def git(*args):
            return subprocess.check_output(['/usr/bin/git', '-C', str(source), *args], env=env, stderr=subprocess.DEVNULL).decode().strip()
        git('init'); (source / 'big').write_bytes(b'x' * (16 * 1048576 + 1))
        git('add', 'big'); git('commit', '-m', 'fixture'); revision = git('rev-parse', 'HEAD')
        (source / 'big').unlink()  # Compressed object is small; expansion is not.
        target = self.root / 'checkout'
        profile = {'components': {'lab': {'enabled': True, 'path': str(target), 'source': {'repository': str(source), 'revision': revision, 'mode': 'git', 'fixture_local': True}}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(receipt['status'], 'failed')
        self.assertFalse(any((stage / 'big').exists() for stage in self.root.glob('.isaac-stage-*')), 'content budget was enforced only after writing expanded content')

    def test_subprocess_scope_refuses_source_hook_execution(self):
        api = self.api()
        import subprocess
        source = self.root / 'source'; source.mkdir(mode=0o700)
        stage = self.root / 'stage'; stage.mkdir(mode=0o700)
        marker = stage / 'hook-executed'
        hook = source / 'hook'
        hook.write_text('#!/bin/sh\nprintf forbidden > ' + str(marker) + '\n'); hook.chmod(0o700)
        fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises((PermissionError, subprocess.SubprocessError)):
                subprocess.run([str(hook)], check=True, timeout=5, pass_fds=(fd,),
                    env={'PATH': '/usr/bin:/bin'}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    preexec_fn=api._builders._child_scope(fd, '/usr/bin/git'))
            self.assertFalse(marker.exists())
        finally:
            os.close(fd)

    def test_builder_child_dies_with_parent_and_keeps_recovery_gate(self):
        api = self.api()
        import signal
        import select
        import subprocess
        from unittest.mock import patch
        target = self.root / 'env'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        readfd, writefd = os.pipe()
        parent = os.fork()
        if parent == 0:
            os.close(readfd)
            original = subprocess.run
            def pause_child(args, **kwargs):
                confine = kwargs['preexec_fn']
                def pause():
                    confine()
                    os.write(writefd, str(os.getpid()).encode())
                    signal.pause()
                kwargs['preexec_fn'] = pause
                kwargs['pass_fds'] = (*kwargs['pass_fds'], writefd)
                return original(args, **kwargs)
            with patch.object(api._builders.subprocess, 'run', side_effect=pause_child):
                api.apply_plan(plan, fixture_root=str(self.root), approved=True)
            os._exit(93)
        os.close(writefd)
        childfd = None
        try:
            ready = select.poll(); ready.register(readfd, select.POLLIN)
            self.assertTrue(ready.poll(3000), 'builder never entered its child scope')
            child = int(os.read(readfd, 32))
            childfd = os.pidfd_open(child)
            os.kill(parent, signal.SIGTERM); _, status = os.waitpid(parent, 0); parent = None
            self.assertTrue(os.WIFSIGNALED(status))
            exited = select.poll(); exited.register(childfd, select.POLLIN)
            if not exited.poll(3000):
                os.kill(child, signal.SIGKILL)
                self.fail('builder child outlived terminated parent')
            root = api.Root(str(self.root))
            try:
                root.lock()  # Child inherited the same directory locks until death.
            finally:
                root.close()
            with self.assertRaises(api.ApplyError):
                api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        finally:
            os.close(readfd)
            if childfd is not None:
                os.close(childfd)
            if parent is not None:
                os.kill(parent, signal.SIGKILL); os.waitpid(parent, 0)

    def test_generated_activation_fifo_is_refused_without_blocking(self):
        api = self.api()
        import signal
        import subprocess
        import time
        from unittest.mock import patch
        target = self.root / 'env'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        pid = os.fork()
        if pid == 0:
            original = subprocess.run
            def fifo(args, **kwargs):
                result = original(args, **kwargs)
                activate = Path(args[-1]) / 'bin/activate'
                activate.unlink(); os.mkfifo(activate, 0o600)
                return result
            with patch.object(api._builders.subprocess, 'run', side_effect=fifo):
                receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
            os._exit(0 if receipt['status'] == 'failed' else 92)
        status = None
        for _ in range(100):
            done, value = os.waitpid(pid, os.WNOHANG)
            if done:
                status = value; break
            time.sleep(0.01)
        if status is None:
            os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
        self.assertIsNotNone(status, 'generated activation FIFO blocked bounded builder')
        self.assertEqual(os.WEXITSTATUS(status), 0)

    def test_builder_expected_tree_is_checked_at_executor_handoff(self):
        api = self.api()
        from unittest.mock import patch
        target = self.root / 'env'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        original = api._builders.build_environment
        def dirty(*args):
            result = original(*args)
            (Path('/proc/self/fd') / str(args[-1]) / 'bin/activate').write_text('changed after builder verification')
            return result
        with patch.object(api._builders, 'build_environment', side_effect=dirty):
            receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(receipt['status'], 'failed')
        self.assertFalse(target.exists())

    def test_tree_fingerprint_refuses_in_place_changes_during_read(self):
        api = self.api()
        from unittest.mock import patch
        target = self.root / 'file'; target.write_text('before')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        original = os.fdopen
        class ChangingRead:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, size):
                data = self.stream.read(size)
                target.write_text('after!')
                return data
        try:
            with patch.object(api._builders.os, 'fdopen', side_effect=lambda *args, **kw: ChangingRead(original(*args, **kw))):
                with self.assertRaises(api._builders.BuilderError):
                    api._builders.tree_digest(fd)
        finally:
            os.close(fd)

    def test_git_builder_rejects_dirty_tree_before_initial_fingerprint(self):
        api = self.api()
        import subprocess
        from unittest.mock import patch
        source = self.root / 'source'; source.mkdir(mode=0o700)
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}
        def git(*args):
            return subprocess.check_output(['/usr/bin/git', '-C', str(source), *args], env=env, stderr=subprocess.DEVNULL).decode().strip()
        git('init'); (source / 'README').write_text('wanted\n'); git('add', 'README'); git('commit', '-m', 'fixture')
        revision = git('rev-parse', 'HEAD')
        target = self.root / 'checkout'
        profile = {'components': {'lab': {'enabled': True, 'path': str(target), 'source': {'repository': str(source), 'revision': revision, 'mode': 'git', 'fixture_local': True}}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        original = subprocess.run
        def edit(args, **kwargs):
            result = original(args, **kwargs)
            if 'checkout' in args:
                destination = Path(args[args.index('-C') + 1]) / 'README'
                before = destination.stat()
                destination.write_text('edited\n')  # same size; restore stat quick-check timestamps
                os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
            return result
        with patch.object(api._builders.subprocess, 'run', side_effect=edit):
            receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(receipt['status'], 'failed', 'dirty bytes became a managed initial baseline')
        self.assertFalse(target.exists())

    def test_optional_declarations_remain_visible_without_blocking_file_apply(self):
        api = self.api()
        target = str(self.root / 'new.json')
        profile = {'managed_files': [{'path': target, 'content': 'ok'}],
                   'custom_dependencies': [{'id': 'custom.optional', 'name': 'optional', 'required': False}],
                   'environments': [{'id': 'env.optional', 'path': '/synthetic/other/env', 'required': False}],
                   'notes': [{'id': 'note.optional', 'text': 'Synthetic fixture note', 'required': False}],
                   'repositories': [{'id': 'repo.optional', 'root': '/synthetic/other/repo', 'required': False}]}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[target]))
        self.assertTrue({'env.optional', 'note.optional', 'repo.optional'} <= {a['id'] for a in plan['actions']})
        receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(receipt['status'], 'verified')
        self.assertEqual(set(receipt['deferred']), {'custom.optional', 'env.optional', 'note.optional', 'repo.optional'})
        self.assertEqual(Path(target).read_text(), 'ok')

    def test_executor_rejects_rehashed_malformed_schema_and_adapter_claims_before_writes(self):
        api = self.api()
        from copy import deepcopy
        original = self.make_plan(api)
        cases = []
        for key, value in (('draft', 'false'), ('version', True), ('actions', {}), ('extra', 'unknown')):
            p = deepcopy(original); p[key] = value; cases.append(p)
        for key, value in (('id', 'unknown.action'), ('execution_supported', 1), ('preconditions', []), ('desired', {'content': 'x' * (api.LIMIT + 1)}), ('desired', {'content': []}), ('desired', {'content': 'x', 'script': 'no'})):
            p = deepcopy(original); p['actions'][1][key] = value; cases.append(p)
        for p in cases:
            p['digest'] = self.planner.digest({k: v for k, v in p.items() if k != 'digest'})
            with self.subTest(case=len(str(p))), self.assertRaises(api.ApplyError):
                api.apply_plan(p, fixture_root=str(self.root), approved=True)
            self.assertEqual(list(self.root.iterdir()), [], 'schema must be rejected before any writes')
        for value in (None, [], False, {'actions': []}):
            with self.subTest(value=value), self.assertRaises(api.ApplyError):
                api.apply_plan(value, fixture_root=str(self.root), approved=True)
        for ids in ([{}], [True], 'workspace.root'):
            with self.subTest(ids=ids), self.assertRaises(api.ApplyError):
                api.apply_plan(original, fixture_root=str(self.root), action_ids=ids, approved=True)

    def test_published_environment_edit_never_becomes_verified_baseline(self):
        api = self.api()
        target = self.root / 'env'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        def edit(stage, action):
            if stage == 'after_mutation':
                (target / 'bin/activate').write_text('unexpected user edit')
        receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True, fault=edit)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual((target / 'bin/activate').read_text(), 'unexpected user edit')
        self.assertFalse(any(e['state'] == 'verified' for e in api.read_journal(fixture_root=str(self.root))))

    def test_rehashed_satisfied_label_never_proves_missing_desired_content(self):
        api = self.api()
        plan = self.make_plan(api)
        plan['actions'][0]['status'] = 'satisfied'
        plan['actions'][1]['status'] = 'satisfied'
        plan['digest'] = self.planner.digest({k: v for k, v in plan.items() if k != 'digest'})
        with self.assertRaises(api.ApplyError):
            api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(api.apply_plan(self.make_plan(api), fixture_root=str(self.root), approved=True)['status'], 'verified')
        plan = self.make_plan(api)
        plan['actions'][1]['desired']['content'] = 'different approved content'
        plan['digest'] = self.planner.digest({k: v for k, v in plan.items() if k != 'digest'})
        with self.assertRaises(api.ApplyError):
            api.apply_plan(plan, fixture_root=str(self.root), approved=True)
        self.assertEqual((self.root / 'work/config-v1.json').read_text(), '{}\n')

    def test_builder_subprocess_cannot_follow_staged_file_link_outside(self):
        api = self.api()
        from unittest.mock import patch
        import subprocess
        target = self.root / 'env'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        original = subprocess.run
        with tempfile.TemporaryDirectory(prefix='isaac-child-outside-') as outside:
            marker = Path(outside) / 'untouched'; marker.write_text('preserve')
            def inject(args, **kwargs):
                payload = Path(args[-1]); payload.mkdir(mode=0o700)
                (payload / 'pyvenv.cfg').symlink_to(marker)
                return original(args, **kwargs)
            with patch.object(api._builders.subprocess, 'run', side_effect=inject):
                receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
            self.assertEqual(marker.read_text(), 'preserve', 'child wrote through an outside symlink')
            self.assertEqual(receipt['status'], 'failed')

    def test_venv_builder_ancestor_swap_cannot_write_outside(self):
        api = self.api()
        from unittest.mock import patch
        import subprocess
        parent = self.root / 'work'; parent.mkdir(mode=0o700)
        target = parent / 'env'
        profile = {'runtimes': {'evaluation': {'manager': 'venv', 'path': str(target), 'fixture_local': True}}}
        plan = self.planner.build_action_plan(profile, target_home=str(self.root), observed=api.inspect_fixture(fixture_root=str(self.root), targets=[str(target)]))
        original = subprocess.run
        with tempfile.TemporaryDirectory(prefix='isaac-venv-outside-') as outside:
            def swap(*args, **kwargs):
                parent.rename(self.root / 'parked')
                parent.symlink_to(outside, target_is_directory=True)
                return original(*args, **kwargs)
            with patch.object(api._builders.subprocess, 'run', side_effect=swap):
                receipt = api.apply_plan(plan, fixture_root=str(self.root), approved=True)
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(list(Path(outside).iterdir()), [], 'venv escaped through swapped ancestor')
            parent.unlink()

    def test_root_lock_rejects_replacement_inode_and_ancestor_chain(self):
        api = self.api()
        pinned = api.Root(str(self.root))
        self.addCleanup(pinned.close)
        parked = self.root.with_name(self.root.name + '-parked')
        self.root.rename(parked); self.root.mkdir(mode=0o700)
        try:
            with self.assertRaises(api.ApplyError):
                pinned.lock()
        finally:
            self.root.rmdir(); parked.rename(self.root)

    def test_journal_strict_schema_metadata_budget_and_replacement(self):
        api = self.api()
        journal = self.root / api.JOURNAL
        invalid = [b'null\n', b'[]\n', b'{}\n', b'{"state":"verified","run":"x"}\n',
                   b'{"run":"x","run":"y","state":"failed"}\n',
                   (json.dumps({'run': 'a' * 32, 'plan': 'b' * 64, 'action': 'managed_file.0', 'target': str(self.root / 'file'), 'state': 'verified', 'postcondition': {}}) + '\n').encode()]
        for data in invalid:
            journal.write_bytes(data); journal.chmod(0o600)
            with self.subTest(data=data), self.assertRaises(api.ApplyError):
                api.read_journal(fixture_root=str(self.root))
        journal.write_bytes(b''); journal.chmod(0o644)
        with self.assertRaises(api.ApplyError):
            api.read_journal(fixture_root=str(self.root))
        journal.unlink()
        root = api.Root(str(self.root))
        try:
            api._journal(root)
            journal.write_bytes(b''); journal.chmod(0o600)
            with self.assertRaises(api.ApplyError):
                api._record(root, {'run': 'a' * 32, 'plan': 'b' * 64, 'state': 'failed', 'error': 'OSError', 'errno': 5})
        finally:
            root.close()

    def test_fifo_journal_is_refused_without_blocking(self):
        api = self.api()
        import signal
        import time
        os.mkfifo(self.root / '.isaac-managed-journal.jsonl', 0o600)
        pid = os.fork()
        if pid == 0:
            try:
                api.read_journal(fixture_root=str(self.root))
                os._exit(92)
            except (api.ApplyError, OSError):
                os._exit(0)
        status = None
        for _ in range(50):
            done, value = os.waitpid(pid, os.WNOHANG)
            if done:
                status = value; break
            time.sleep(0.01)
        if status is None:
            os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
        self.assertIsNotNone(status, 'FIFO metadata blocked bounded executor')
        self.assertEqual(os.WEXITSTATUS(status), 0)

if __name__ == '__main__':
    unittest.main()
