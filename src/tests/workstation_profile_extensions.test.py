"""Additive shared YAML contracts; synthetic text only."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.python import workstation_profile as wp

HEADER = 'schema_version: v1alpha1\nkind: workstation-profile\nname: reviewed\n'


class ExtensionsTests(unittest.TestCase):
    def test_uppercase_commit_reference_has_canonical_content_identity(self):
        result = wp.resolve_profile('default', {'components': {'lab': {'source': {
            'ref': 'D' * 40, 'revision': None}}}})
        self.assertEqual(result['references']['components.lab']['content_id'], 'd' * 40)

    def test_repository_change_cannot_reuse_uppercase_immutable_ref(self):
        profile = wp.resolve_profile('default', {'components': {'lab': {'source': {
            'ref': 'D' * 40, 'revision': None}}}})['profile']
        profile['defaults'] = False
        with self.assertRaisesRegex(wp.ProfileError, 'repository change requires'):
            wp.resolve_document(profile, overrides={'components': {'lab': {'source': {
                'repository': 'https://github.com/example/other.git'}}}})

    def test_uppercase_immutable_ref_cannot_hide_conflicting_revision(self):
        with self.assertRaises(wp.ProfileError):
            wp.resolve_profile('default', {'components': {'lab': {'source': {
                'ref': 'D' * 40, 'revision': 'a' * 40}}}})
        matching = wp.resolve_profile('default', {'components': {'lab': {'source': {
            'ref': 'D' * 40, 'revision': 'd' * 40}}}})
        self.assertEqual(matching['profile']['components']['lab']['source']['revision'], 'd' * 40)

    def test_explicit_sim_git_is_lossless_without_converting_standalone_defaults(self):
        import yaml
        source = {'mode': 'git', 'repository': 'https://github.com/example/IsaacSim.git',
                  'ref': 'reviewed-branch', 'revision': 'a' * 40}
        data = {**wp.parse_profile_text(HEADER), 'defaults': False,
                'components': {'sim': {'enabled': True, 'source': source}}}
        result = wp.resolve_document(wp.parse_profile_text(yaml.safe_dump(data)))
        self.assertEqual(result['profile']['components']['sim']['source'], source)
        self.assertEqual(result['references']['components.sim']['content_id'], 'a' * 40)
        self.assertEqual(wp.load_profile('default')['components']['sim']['source']['mode'], 'standalone')
        for changes in ({'version': '5.0.0'}, {'sha256': 'b' * 64},
                        {'repository': 'https://user:secret@example.org/x'}, {'command': 'run'}):
            with self.subTest(changes=changes), self.assertRaises(wp.ProfileError):
                wp.resolve_profile_data({**data, 'components': {'sim': {'source': {**source, **changes}}}})

    def test_explicit_sim_source_mode_switch_replaces_union_without_stale_pins(self):
        source = {'mode': 'git', 'repository': 'https://github.com/example/IsaacSim.git',
                  'ref': 'branch', 'revision': 'a' * 40}
        selected = {**wp.parse_profile_text(HEADER), 'components': {'sim': {'source': source}}}
        result = wp.resolve_document(selected, presets={'default': wp.load_profile('default')})
        self.assertEqual(result['profile']['components']['sim']['source'], source)
        self.assertNotIn('components.sim.source.version', result['provenance'])
        self.assertNotIn('components.sim.source.sha256', result['provenance'])
        sparse = {**selected, 'defaults': False}
        changed = wp.resolve_document(sparse, overrides={'components': {'sim': {'source': {'ref': 'new'}}}})
        self.assertIsNone(changed['profile']['components']['sim']['source']['revision'])
        archive = {'mode': 'standalone', 'version': '5.0.0', 'sha256': 'b' * 64}
        changed = wp.resolve_document(sparse, overrides={'components': {'sim': {'source': archive}}})
        self.assertEqual(changed['profile']['components']['sim']['source'], archive)

    def test_explicit_standalone_archive_url_roundtrips_exactly_and_never_is_invented(self):
        source = {'mode': 'standalone', 'version': '6.0.1', 'sha256': 'a' * 64,
                  'url': 'https://artifacts.example.org/sim-6.0.1.zip'}
        data = {**wp.parse_profile_text(HEADER), 'defaults': False,
                'components': {'sim': {'enabled': True, 'source': source}}}
        self.assertEqual(wp.resolve_document(data)['profile']['components']['sim']['source'], source)
        for url in (None, 'https://cdn.example.org/releases/sim.zip'):
            result = wp.resolve_document({**data, 'components': {'sim': {'source': {**source, 'url': url}}}})
            self.assertEqual(result['profile']['components']['sim']['source']['url'], url)
        for url in ('http://example.org/x.zip', 'https://u:p@example.org/x.zip',
                    'https://example.org:443/x.zip', 'https://example.org/x.zip?q=1',
                    'https://example.org/x.zip#frag', 'https://example.org/../x.zip',
                    'https://example.org/a//b.zip', 'https://example.org/%2ex.zip',
                    'https://example.org/$(run).zip', 'https://example.org/token=secret',
                    'https://example.org/.hidden.zip', 'https://-bad.example/x.zip',
                    'https://example.org/x.zip\n'):
            with self.subTest(url=url), self.assertRaises(wp.ProfileError):
                wp.resolve_profile_data({**data, 'components': {'sim': {'source': {**source, 'url': url}}}})
        defaults = wp.load_profile('default')['components']['sim']['source']
        self.assertNotIn('url', defaults)

    def test_archive_url_override_invalidates_inherited_checksum(self):
        source = {'mode': 'standalone', 'version': '6.0.1', 'sha256': 'a' * 64,
                  'url': 'https://artifacts.example.org/one.zip'}
        data = {**wp.parse_profile_text(HEADER), 'defaults': False, 'components': {'sim': {'source': source}}}
        result = wp.resolve_document(data, overrides={'components': {'sim': {'source': {
            'url': 'https://artifacts.example.org/two.zip'}}}})
        self.assertIsNone(result['profile']['components']['sim']['source']['sha256'])
        self.assertEqual(result['provenance']['components.sim.source.sha256'], 'overrides')

    def test_pure_text_parser_never_opens_presets(self):
        self.assertTrue(callable(getattr(wp, 'parse_profile_text', None)), 'pure parser missing')
        with patch.object(Path, 'open', side_effect=AssertionError('disk access')):
            self.assertEqual(wp.parse_profile_text(HEADER), {
                'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'reviewed'})
            self.assertEqual(wp.parse_profile_text(HEADER.encode()), wp.parse_profile_text(HEADER))
            for invalid in (HEADER + 'name: duplicate', HEADER + '# ' + 'x' * 131072,
                            HEADER + 'target: &a offline', b'\xff', None,
                            'kind: workstation-baseline\n'):
                with self.subTest(invalid=str(invalid)[:80]), self.assertRaises(wp.ProfileError):
                    wp.parse_profile_text(invalid)

    def test_workspace_and_draft_controls_are_strict_nonsecret_data(self):
        for extra in ('defaults: true', 'defaults: 0', 'draft: yesplease',
                      'defaults: false\nextends: full', 'draft: true\nextends: full',
                      'workspace: {root: /}', 'workspace: {root: /tmp/../private}',
                      'workspace: {root: "~/"}', 'workspace: {layout: bad}',
                      'workspace: {name: ../bad}', 'workspace: {name: " Name"}',
                      'workspace: {layout: flat, name: Team}',
                      'workspace: {layout: named, name: Team, default_owner: Other}',
                      'workspace: {command: DO_NOT_ECHO}',
                      'workspace: {root: "/tmp/token=DO_NOT_ECHO"}'):
            with self.subTest(extra=extra):
                with self.assertRaises(wp.ProfileError) as ctx:
                    wp.parse_profile_text(HEADER + extra)
                self.assertNotIn('DO_NOT_ECHO', str(ctx.exception))
        for extra in ('defaults: false\ndraft: true\nworkspace: {name: Team}',
                      'workspace: {root: "~/Documents/Robotics", layout: named, name: "Team A"}',
                      'workspace: {layout: flat}'):
            self.assertTrue(wp.parse_profile_text(HEADER + extra))

    def test_sparse_drafts_resolve_without_preset_or_robotics_defaults(self):
        import tempfile
        self.assertTrue(callable(getattr(wp, 'resolve_profile_data', None)), 'pure resolver missing')
        data = wp.parse_profile_text(HEADER + 'defaults: false\ndraft: true\n')
        with patch.object(Path, 'open', side_effect=AssertionError('disk access')):
            result = wp.resolve_profile_data(data)
        self.assertEqual(result['profile'], data)
        self.assertFalse(result['ready_for_apply'])
        self.assertIn({'field': 'profile', 'reason': 'draft_intent_unresolved'}, result['unresolved'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.yaml'
            path.write_text(HEADER + 'defaults: false\ndraft: true\n')
            with patch.object(wp, 'PROFILE_DIR', Path('/unavailable/presets')):
                self.assertEqual(wp.resolve_profile(path), result)

    def test_custom_declarations_reject_hooks_secrets_and_forged_support(self):
        import yaml
        item = {'id': 'tool:sample:tool', 'name': 'tool', 'version': '1.0', 'environment': 'my-env',
                'location': '/tmp/selected/tools.json', 'purpose': 'Robot workflow',
                'source': 'https://example.org/team/tool', 'placement': 'environment',
                'required': True, 'support': 'unsupported'}
        base = wp.parse_profile_text(HEADER)
        for key, value in [('command', 'DO_NOT_ECHO'), ('name', '$(DO_NOT_ECHO)'),
                           ('source', 'https://user:DO_NOT_ECHO@example.org/a'),
                           ('source', 'https://example.org/a?token=DO_NOT_ECHO'),
                           ('purpose', 'token=DO_NOT_ECHO'), ('purpose', 'password DO_NOT_ECHO'), ('required', 'true'),
                           ('support', 'supported'), ('placement', 'conda'),
                           ('location', '/tmp/../DO_NOT_ECHO'), ('version', 1.0),
                           ('environment', '$(DO_NOT_ECHO)')]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(wp.ProfileError) as ctx:
                    wp.parse_profile_text(yaml.safe_dump({**base, 'custom_dependencies': [{**item, key: value}]}))
                self.assertNotIn('DO_NOT_ECHO', str(ctx.exception))
        with self.assertRaises(wp.ProfileError):
            wp.parse_profile_text(yaml.safe_dump({**base, 'custom_dependencies': [item, item]}))
        with self.assertRaises(wp.ProfileError):
            wp.parse_profile_text(yaml.safe_dump({**base, 'custom_dependencies': [{}]}))
        self.assertEqual(wp.parse_profile_text(yaml.safe_dump({**base, 'custom_dependencies': [item]}))[
            'custom_dependencies'], [item])

    def test_environment_and_note_declarations_are_typed_nonexecutable(self):
        import yaml
        base = wp.parse_profile_text(HEADER)
        env = {'id': 'environment:tools', 'name': 'project-uv', 'manager': 'uv', 'python': '3.12',
               'placement': 'container', 'location': '/tmp/project/environment.json',
               'required': False, 'support': 'unsupported'}
        note = {'id': 'note:tools:0', 'text': 'Preserve tooling', 'required': False, 'support': 'unsupported'}
        for key, item, changes in [('environments', env, {'manager': 'shell'}),
                                   ('environments', env, {'python': 3.12}),
                                   ('environments', env, {'location': '/tmp/../secret'}),
                                   ('environments', env, {'placement': 'conda'}),
                                   ('notes', note, {'text': 'password DO_NOT_ECHO'}),
                                   ('notes', note, {'text': '$(DO_NOT_ECHO)'}),
                                   ('notes', note, {'required': 'false'}),
                                   ('notes', note, {'support': 'supported'})]:
            with self.subTest(key=key, changes=changes), self.assertRaises(wp.ProfileError):
                wp.parse_profile_text(yaml.safe_dump({**base, key: [{**item, **changes}]}))
        for key, item in [('environments', env), ('notes', note)]:
            for items in ([item, item], [{}], {'bad': item}):
                with self.subTest(key=key, items=items), self.assertRaises(wp.ProfileError):
                    wp.parse_profile_text(yaml.safe_dump({**base, key: items}))

    def test_repository_declarations_cannot_claim_clean_or_leak_credentials(self):
        import yaml
        base = wp.parse_profile_text(HEADER)
        repo = {'id': 'repository:robot', 'root': '/tmp/robot', 'git_dir': '/tmp/robot/.git',
                'common_dir': '/tmp/robot/.git', 'head': {'ref': 'refs/heads/main', 'commit': 'a' * 40},
                'remotes': [{'name': 'origin', 'url': 'https://example.org/team/robot.git'}],
                'submodules': [], 'dirty': 'unknown', 'pin_provenance': 'selected-head-only',
                'required': False, 'support': 'unsupported'}
        for changes in ({'dirty': 'clean'}, {'pin_provenance': 'verified'}, {'head': {'ref': None, 'commit': 'main'}},
                        {'head': {'ref': 'refs/../private', 'commit': None}},
                        {'remotes': [{'name': 'origin', 'url': 'ssh://user:DO_NOT_ECHO@example.org/x'}]},
                        {'remotes': [{'name': 'origin', 'url': 'https://example.org:99999/x'}]},
                        {'remotes': [{'name': 'origin', 'url': 'https://example.org/../x'}]},
                        {'submodules': [{'name': 'sub', 'path': '../x', 'url': 'https://example.org/x'}]},
                        {'git_dir': '/tmp/../private'}, {'command': 'DO_NOT_ECHO'}):
            with self.subTest(changes=changes), self.assertRaises(wp.ProfileError):
                wp.parse_profile_text(yaml.safe_dump({**base, 'repositories': [{**repo, **changes}]}))
        self.assertEqual(wp.parse_profile_text(yaml.safe_dump({**base, 'repositories': [repo]}))['repositories'], [repo])
        from copy import deepcopy
        with self.assertRaises(wp.ProfileError):
            wp.parse_profile_text(yaml.safe_dump({**base, 'repositories': [deepcopy(repo), deepcopy(repo)]}))

    def test_pure_resolution_matches_file_resolution_with_preloaded_presets(self):
        self.assertTrue(callable(getattr(wp, 'resolve_document', None)), 'pure preset resolver missing')
        presets = {name: wp.load_profile(name) for name in wp.PRESETS}
        overrides = {'components': {'lerobot': {'enabled': False}}}
        expected = wp.resolve_profile('full', overrides)
        with patch.object(Path, 'open', side_effect=AssertionError('disk access')):
            self.assertEqual(wp.resolve_document(presets['full'], presets=presets, overrides=overrides,
                                                  label='preset:full'), expected)
            selected = wp.parse_profile_text(HEADER + 'extends: minimal\n')
            result = wp.resolve_document(selected, presets=presets)
            self.assertFalse(result['profile']['components']['arena']['enabled'])
            self.assertEqual(result['profile']['components']['lab']['source']['ref'], 'v3.0.0-beta2')
            self.assertEqual(wp.resolve_document(wp.parse_profile_text(HEADER + 'defaults: false\n'), presets={})[
                'profile'], wp.parse_profile_text(HEADER + 'defaults: false\n'))
            with self.assertRaises(wp.ProfileError):
                wp.resolve_document(selected, presets={})

    def test_admitted_long_paths_urls_and_purpose_remain_lossless(self):
        import yaml
        item = {'id': 'tool:sample:tool', 'name': 'tool', 'version': None, 'environment': 'base',
                'location': '/tmp/' + '/'.join(['selected-directory'] * 40),
                'purpose': 'Robot workflow (control/vision)',
                'source': 'https://example.org/' + '/'.join(['repository'] * 40),
                'placement': 'environment', 'required': False, 'support': 'unsupported'}
        profile = {**wp.parse_profile_text(HEADER), 'custom_dependencies': [item]}
        self.assertEqual(wp.parse_profile_text(yaml.safe_dump(profile)), profile)
        for source in ('https://example.org:99999/x', 'https://example.org/../x'):
            with self.subTest(source=source), self.assertRaises(wp.ProfileError):
                wp.parse_profile_text(yaml.safe_dump({**profile, 'custom_dependencies': [{**item, 'source': source}]}))

    def test_incomplete_draft_dependency_errors_are_reported_not_hidden_by_defaults(self):
        data = wp.parse_profile_text(HEADER + 'defaults: false\ndraft: true\ncomponents: {lab: {enabled: true}}\n')
        result = wp.resolve_document(data)
        self.assertEqual(result['profile']['components'], {'lab': {'enabled': True}})
        self.assertIn({'field': 'dependencies', 'reason': 'dependency_intent_unresolved'}, result['unresolved'])
        self.assertFalse(result['ready_for_apply'])
        with self.assertRaises(wp.ProfileError):
            wp.resolve_document({**data, 'draft': False})

    def test_overrides_cannot_remove_draft_or_relabel_inherited_defaults(self):
        data = wp.parse_profile_text(HEADER + 'defaults: false\ndraft: true\n')
        for overrides in ({'draft': False}, {'defaults': False}):
            with self.subTest(overrides=overrides), self.assertRaises(wp.ProfileError):
                wp.resolve_document(data, overrides=overrides)


if __name__ == '__main__':
    unittest.main()
