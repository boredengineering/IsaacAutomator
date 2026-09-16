#!/usr/bin/env python3
"""Offline migration preview acceptance; inputs are synthetic evidence, not reads."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
CORE = Path(__file__).resolve().parents[2] / 'isaac-installer/lib/core'


def load(name):
    spec = importlib.util.spec_from_file_location(name, CORE / (name + '.py'))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationPreviewTests(unittest.TestCase):
    def test_empty_preview_is_explicitly_read_only_not_migration_apply(self):
        self.assertTrue((CORE / 'migration_preview.py').exists(), 'migration preview missing')
        preview = load('migration_preview').build_migration_preview(
            {'workspace': {'root': '~/work', 'layout': 'flat'}},
            {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Chosen'}},
            '/fixture/home', [])
        self.assertEqual(preview['kind'], 'workspace-migration-preview')
        self.assertEqual(preview['schema_version'], 1)
        self.assertIs(preview['read_only'], True)
        self.assertIs(preview['apply_supported'], False)
        self.assertEqual(preview['repositories'], [])
        self.assertIn('adoption', preview['unsupported_reason'])
        json.dumps(preview)


    def test_malformed_inputs_refuse_instead_of_claiming_empty_success(self):
        api = load('migration_preview')
        args = [
            {'workspace': {'root': '~/work', 'layout': 'flat'}},
            {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Chosen'}},
            '/fixture/home', [], None,
        ]
        for index, invalid in ((0, None), (1, []), (2, ''), (2, 'relative'),
                               (2, '/'), (2, '~/user'), (3, {}), (3, 'IsaacLab'), (4, [])):
            with self.subTest(index=index, invalid=invalid):
                changed = list(args)
                changed[index] = invalid
                with self.assertRaises(ValueError):
                    api.build_migration_preview(*changed)


    def test_nonempty_flat_to_named_compares_actual_destinations_without_reads(self):
        from unittest.mock import patch
        import os
        api = load('migration_preview')
        with patch.object(os, 'scandir', side_effect=AssertionError('unexpected target read')), \
                patch.object(Path, 'lstat', side_effect=AssertionError('unexpected target read')):
            preview = api.build_migration_preview(
                {'workspace': {'root': '~/work', 'layout': 'flat'}},
                {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Chosen Team'}},
                '/fixture/home', [{'name': 'IsaacLab', 'slug': 'fork/IsaacLab'}])
        self.assertEqual(len(preview['repositories']), 1)
        item = preview['repositories'][0]
        self.assertEqual(item['old_destination'], '/fixture/home/work/IsaacLab')
        self.assertEqual(item['new_destination'], '/fixture/home/work/Chosen Team/IsaacLab')
        self.assertIsNone(item['active_path'])
        self.assertEqual(item['status'], 'unknown')
        self.assertIn('legacy active discovery', ' '.join(item['reasons']))
        self.assertEqual(item['path_change'], 'different_destination')
        self.assertIs(preview['apply_supported'], False)

    def test_per_repository_overrides_are_independent_of_roots_and_report_same_path(self):
        api = load('migration_preview')
        old = {'workspace': {'root': 'invalid unrelated root', 'layout': 'flat'}}
        new = {'workspace': {'root': '/other/root', 'layout': 'named', 'name': 'CASE'}}
        repo = {'name': 'IsaacLab', 'path_override': '~/My Checkout',
                'active_discovery_complete': True}
        item = api.build_migration_preview(old, new, '/fixture/home', [repo])['repositories'][0]
        self.assertEqual(item['old_destination'], '/fixture/home/My Checkout')
        self.assertEqual(item['new_destination'], item['old_destination'])
        self.assertEqual(item['path_change'], 'same_destination')
        self.assertEqual(item['active_path'], item['old_destination'])
        self.assertEqual(item['status'], 'unchanged')
        repo.update(old_path_override='~/Before', new_path_override='~/After')
        item = api.build_migration_preview(old, new, '/fixture/home', [repo])['repositories'][0]
        self.assertEqual(item['old_destination'], '/fixture/home/Before')
        self.assertEqual(item['new_destination'], '/fixture/home/After')

    def test_auto_and_org_use_shared_case_evidence_not_invented_owner_paths(self):
        api = load('migration_preview')
        for layout in ('auto', 'org'):
            old = {'workspace': {'root': '~/work', 'layout': layout, 'default_owner': 'existingowner'},
                   'directory_entries': {'/fixture/home/work': ['ExistingOwner']}}
            new = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'ExistingOwner'}}
            repo = {'name': 'IsaacLab', 'slug': 'fork/IsaacLab', 'active_path': '/elsewhere/IsaacLab'}
            item = api.build_migration_preview(old, new, '/fixture/home', [repo])['repositories'][0]
            self.assertEqual(item['old_destination'], '/fixture/home/work/ExistingOwner/IsaacLab')
            self.assertEqual(item['new_destination'], item['old_destination'])
            self.assertEqual(item['active_path'], '/elsewhere/IsaacLab')
            self.assertEqual(item['active_path_change'], 'different_destination')
            del old['directory_entries']
            item = api.build_migration_preview(old, new, '/fixture/home', [repo])['repositories'][0]
            self.assertIsNone(item['old_destination'])
            self.assertEqual(item['path_change'], 'unknown')

    def test_case_only_rename_and_supplied_collisions_remain_visible(self):
        api = load('migration_preview')
        old = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Chosen'}}
        new = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'chosen'}}
        repo = {'name': 'IsaacLab'}
        item = api.build_migration_preview(old, new, '/fixture/home', [repo])['repositories'][0]
        self.assertEqual(item['path_change'], 'case_only_change')
        self.assertEqual(item['status'], 'blocked')
        new['directory_entries'] = {'/fixture/home/work': ['Chosen']}
        item = api.build_migration_preview(old, new, '/fixture/home', [repo])['repositories'][0]
        self.assertEqual(item['status'], 'blocked')
        self.assertIn('collision', ' '.join(item['reasons']))
        self.assertEqual(item['new_resolution']['candidate_destination'], '/fixture/home/work/chosen/IsaacLab')

    def test_only_caller_evidence_can_report_dirty_existing_or_review_required(self):
        api = load('migration_preview')
        old = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Before'}}
        new = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'After'}}
        source, target = '/fixture/home/work/Before/IsaacLab', '/fixture/home/work/After/IsaacLab'
        cases = [({}, 'unknown', 'evidence'),
                 ({source: {'dirty': True}}, 'blocked', 'dirty'),
                 ({target: {'state': 'directory'}}, 'blocked', 'exists'),
                 ({target: {'conflict': True}}, 'blocked', 'collision'),
                 ({source: {'state': 'directory', 'dirty': False}, target: {'state': 'missing'}},
                  'review_required', 'apply')]
        for evidence, expected, reason in cases:
            with self.subTest(evidence=evidence):
                preview = api.build_migration_preview(old, new, '/fixture/home', [{'name': 'IsaacLab'}], evidence)
                item = preview['repositories'][0]
                self.assertEqual(item['status'], expected)
                self.assertIn(reason, ' '.join(item['reasons']))
                self.assertIs(preview['apply_supported'], False)
                self.assertNotIn('commands', item)

    def test_two_repositories_cannot_share_exact_or_casefold_destination(self):
        api = load('migration_preview')
        config = {'workspace': {'root': '~/work', 'layout': 'flat'}}
        for target in ('~/same', '~/SAME'):
            rows = api.build_migration_preview(config, config, '/fixture/home', [
                {'name': 'IsaacLab', 'path_override': '~/same', 'active_discovery_complete': True},
                {'name': 'lerobot', 'path_override': target, 'active_discovery_complete': True}])['repositories']
            self.assertTrue(all(row['status'] == 'blocked' for row in rows))
            self.assertTrue(all('collision' in ' '.join(row['reasons']) for row in rows))

    def test_malformed_nested_evidence_and_repository_records_refuse(self):
        api = load('migration_preview')
        config = {'workspace': {'root': '~/work', 'layout': 'flat'}}
        for evidence in ({'/fixture/target': {'dirty': 'false'}}, {'relative': {}},
                         {'/fixture/target': {'state': 'clean'}}, {'/fixture/target': []},
                         {'/fixture/target': {'conflict': 'no'}}):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                api.build_migration_preview(config, config, '/fixture/home', [], evidence)
        for repo in ({}, {'name': 'IsaacLab', 'active_discovery_complete': 'yes'},
                     {'name': 'IsaacLab', 'active_path': 'relative'}, {'name': 'IsaacLab', 'path_override': []}):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                api.build_migration_preview(config, config, '/fixture/home', [repo])
        with self.assertRaises(ValueError):
            api.build_migration_preview({'workspace': {'layout': 'flat', 'name': 'Illegal'}}, config,
                                        '/fixture/home', [])

    def test_workspace_name_does_not_rewrite_independent_roots_or_input_profiles(self):
        from copy import deepcopy
        api = load('migration_preview')
        old = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Before'},
               'runtimes': {'lab': {'path': '~/envs/lab'}},
               'state_root': '~/.isaac-installer', 'sim_prefix': '~/IsaacSim'}
        new = deepcopy(old)
        new['workspace']['name'] = 'After'
        before = deepcopy((old, new))
        rows = api.build_migration_preview(old, new, '/fixture/home', [
            {'name': 'IsaacLab', 'slug': 'fork/IsaacLab'},
            {'name': 'lerobot', 'slug': 'huggingface/lerobot'}])['repositories']
        self.assertEqual([row['new_destination'] for row in rows],
                         ['/fixture/home/work/After/IsaacLab', '/fixture/home/work/After/lerobot'])
        self.assertEqual((old, new), before)
        self.assertTrue(all('commands' not in row for row in rows))

    def test_same_destination_does_not_hide_supplied_file_or_symlink_conflicts(self):
        api = load('migration_preview')
        config = {'workspace': {'root': '~/work', 'layout': 'named', 'name': 'Chosen'}}
        target = '/fixture/home/work/Chosen/IsaacLab'
        for kind in ('file', 'symlink', 'other'):
            row = api.build_migration_preview(config, config, '/fixture/home', [{'name': 'IsaacLab'}],
                                               {target: {'state': kind}})['repositories'][0]
            self.assertEqual(row['path_change'], 'same_destination')
            self.assertEqual(row['status'], 'blocked')
            self.assertIn('unsupported', ' '.join(row['reasons']))

    def test_missing_shared_resolver_never_silently_drops_repositories(self):
        api = load('migration_preview')
        # A missing dependency must be explicit, not an apparently valid empty plan.
        if hasattr(api._paths, 'resolve_paths'):
            del api._paths.resolve_paths
        with self.assertRaisesRegex(RuntimeError, 'shared.*resolve_paths'):
            api.build_migration_preview({}, {}, '/fixture/home', [{}])


if __name__ == '__main__':
    unittest.main()
