"""Offline shared workstation contract tests; no deployment/credential fixtures."""
import copy

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.python import workstation_profile as wp


class WorkstationProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profile.yaml'

    def write(self, text):
        self.path.write_text(text, encoding='utf-8')
        return self.path

    def test_execution_mode_is_explicit_and_container_intent_is_rejected(self):
        components = wp.resolve_profile('full')['profile']['components']
        for name, component in components.items():
            with self.subTest(name=name):
                self.assertIn('execution', component)
                self.assertEqual(component['execution'], 'native')
                with self.assertRaises(wp.ProfileError):
                    wp.resolve_profile('full', {'components': {name: {'execution': 'container'}}})

    def test_bounded_regular_file_input_and_precise_runtime_versions(self):
        self.write('schema_version: v1alpha1\nkind: workstation-profile\nname: custom\n#' + 'x' * 131073)
        with self.assertRaises(wp.ProfileError):
            wp.load_profile(self.path)
        for value in ('DO_NOT_ECHO\x00.yaml', Path(self.temp.name), None):
            with self.subTest(value=value), self.assertRaises(wp.ProfileError) as ctx:
                wp.load_profile(value)
            self.assertNotIn('DO_NOT_ECHO', str(ctx.exception))
        for field, value in [('python', '3.12+cu128'), ('cuda_runtime', '12.8+cu128'), ('torch', '2.10')]:
            with self.subTest(field=field), self.assertRaises(wp.ProfileError):
                wp.resolve_profile('full', {'runtimes': {'gr00t': {field: value}}})

    def test_gr00t_preserves_repo_local_uv_runtime_intent(self):
        runtimes = wp.resolve_profile('full')['profile']['runtimes']
        self.assertEqual(runtimes['gr00t']['manager'], 'uv')
        self.assertEqual(runtimes['gr00t']['environment'], 'gr00t')
        self.assertEqual(runtimes['lab']['manager'], 'conda')
        self.assertEqual(runtimes['lerobot']['manager'], 'conda')
        with self.assertRaises(wp.ProfileError):
            wp.resolve_profile('full', {'runtimes': {'gr00t': {'manager': 'conda'}}})

    def test_ref_changes_invalidate_inherited_pins(self):
        import yaml
        profile = wp.resolve_profile('full', {'components': {
            'lab': {'source': {'revision': 'a' * 40}},
            'sim': {'source': {'sha256': 'b' * 64}}},
            'serving': {'model': {'revision': 'c' * 40}}})['profile']
        self.write(yaml.safe_dump(profile))
        changes = [
            ({'components': {'lab': {'source': {'ref': 'main'}}}}, 'components.lab', 'components.lab.source.revision'),
            ({'components': {'lab': {'source': {'repository': 'https://github.com/example/IsaacLab.git'}}}}, 'components.lab', 'components.lab.source.revision'),
            ({'components': {'sim': {'source': {'version': '5.1.0'}}}}, 'components.sim', 'components.sim.source.sha256'),
            ({'serving': {'model': {'ref': 'dev'}}}, 'serving.model', 'serving.model.revision'),
            ({'serving': {'model': {'repository': 'example/model'}}}, 'serving.model', 'serving.model.revision'),
        ]
        for overlay, key, field in changes:
            with self.subTest(overlay=overlay):
                result = wp.resolve_profile(self.path, overlay)
                self.assertEqual(result['references'][key]['status'], 'unresolved')
                self.assertIsNone(result['references'][key]['content_id'])
                self.assertEqual(result['provenance'][field], 'overrides')
        same = wp.resolve_profile(self.path, {'components': {'lab': {'source': {'ref': 'v3.0.0-beta2'}}}})
        self.assertEqual(same['references']['components.lab']['content_id'], 'a' * 40)
        replaced = wp.resolve_profile(self.path, {'components': {'lab': {'source': {'ref': 'main', 'revision': 'd' * 40}}}})
        self.assertEqual(replaced['references']['components.lab']['content_id'], 'd' * 40)
        direct = wp.resolve_profile('default', {'components': {'lab': {'source': {'ref': 'e' * 40}}}})
        self.assertEqual(direct['references']['components.lab']['content_id'], 'e' * 40)
        self.assertEqual(direct['references']['components.lab']['status'], 'resolved')
        with self.assertRaises(wp.ProfileError):
            wp.resolve_profile('default', {'components': {'lab': {'source': {'ref': 'e' * 40, 'revision': 'f' * 40}}}})

    def test_repository_changes_cannot_reuse_inherited_immutable_refs(self):
        import yaml
        from unittest.mock import patch

        default = wp.load_profile('default')
        original = wp.resolve_profile('full', {
            'components': {'lab': {'source': {'ref': 'a' * 40}}},
            'serving': {'model': {'ref': 'a' * 40}},
        })['profile']
        original_copy = copy.deepcopy(original)
        directory = Path(self.temp.name)
        for path, repository, reference in (
            (('components', 'lab', 'source'), 'https://github.com/example/IsaacLab.git', 'components.lab'),
            (('serving', 'model'), 'example/model', 'serving.model'),
        ):
            for layer in ('preset', 'profile', 'overrides'):
                for replacement, expected in (
                    ({}, 'reject'),
                    ({'revision': None}, 'reject'),
                    ({'ref': 'main'}, None),
                    ({'ref': 'b' * 40}, 'b' * 40),
                    ({'revision': 'a' * 40}, 'a' * 40),
                ):
                    with self.subTest(path=path, layer=layer, replacement=replacement):
                        overlay = {'repository': repository, **replacement}
                        for key in reversed(path):
                            overlay = {key: overlay}
                        overlay_copy = copy.deepcopy(overlay)
                        selected = overlay if layer == 'preset' else original
                        (directory / 'default.yaml').write_text(yaml.safe_dump(
                            original if layer == 'preset' else default), encoding='utf-8')
                        (directory / 'full.yaml').write_text(yaml.safe_dump({
                            'schema_version': 'v1alpha1', 'kind': 'workstation-profile',
                            'name': 'full', **selected}), encoding='utf-8')
                        self.write(yaml.safe_dump({
                            'schema_version': 'v1alpha1', 'kind': 'workstation-profile',
                            'name': 'custom', 'extends': 'full', **overlay}))
                        documents = {p: p.read_bytes() for p in directory.glob('*.yaml')}
                        with patch.object(wp, 'PROFILE_DIR', directory):
                            name = self.path if layer == 'profile' else 'full'
                            overrides = overlay if layer == 'overrides' else None
                            if expected == 'reject':
                                with self.assertRaisesRegex(wp.ProfileError, 'repository.*explicit.*ref or revision'):
                                    wp.resolve_profile(name, overrides)
                            else:
                                result = wp.resolve_profile(name, overrides)
                                self.assertEqual(result['references'][reference]['content_id'], expected)
                                self.assertEqual(result['references'][reference]['status'],
                                                 'resolved' if expected else 'unresolved')
                                self.assertFalse(result['references'][reference]['verified'])
                        self.assertEqual(overlay, overlay_copy)
                        self.assertEqual(original, original_copy)
                        self.assertEqual({p: p.read_bytes() for p in documents}, documents)

    def test_manifest_reports_honest_refs_and_path_independent_digest(self):
        result = wp.resolve_profile('full')
        self.assertIn('ready_for_apply', result, 'manifest acceptance status missing')
        self.assertFalse(result['ready_for_apply'])
        self.assertEqual(result['adapter'], {'name': 'offline', 'apply_supported': False})
        refs = result['references']
        for name in ('sim', 'lab', 'arena', 'gr00t', 'lerobot'):
            self.assertEqual(refs['components.' + name]['status'], 'unresolved')
            self.assertFalse(refs['components.' + name]['verified'])
        self.assertEqual(refs['components.gr00t']['requested'], 'dev')
        self.assertEqual(refs['serving.model']['status'], 'unresolved')
        self.assertIn({'field': 'runtimes.gr00t.python', 'reason': 'not_pinned'}, result['unresolved'])
        self.assertIn({'field': 'runtimes.lab', 'reason': 'compatibility_unverified'}, result['unresolved'])
        pins = {'components': {'lab': {'source': {'revision': 'a' * 40}}, 'sim': {'source': {'sha256': 'b' * 64}}}, 'serving': {'model': {'revision': 'c' * 40}}}
        pinned = wp.resolve_profile('full', pins)
        self.assertEqual(pinned['references']['components.lab']['status'], 'resolved')
        self.assertEqual(pinned['references']['components.lab']['content_id'], 'a' * 40)
        self.assertFalse(pinned['references']['components.lab']['verified'])
        self.assertEqual(pinned['references']['components.sim']['status'], 'resolved')
        self.assertEqual(pinned['references']['serving.model']['status'], 'resolved')
        self.assertFalse(pinned['ready_for_apply'])
        minimal = wp.resolve_profile('minimal')
        self.assertEqual(minimal['references']['components.gr00t']['status'], 'not_selected')
        self.assertEqual(minimal['references']['serving.model']['status'], 'not_selected')
        self.assertFalse(any(item['field'].startswith('runtimes.gr00t') for item in minimal['unresolved']))
        canonical = json.dumps(result['profile'], sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        self.assertEqual(result['digest'], 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest())
        self.assertNotEqual(pinned['digest'], result['digest'])
        import yaml
        self.write(yaml.safe_dump(result['profile']))
        from_path = wp.resolve_profile(self.path)
        self.assertEqual(result['digest'], from_path['digest'])
        display = json.dumps(from_path)
        self.assertNotIn(self.temp.name, display)
        self.assertNotIn(str(ROOT), display)
        self.assertEqual(set(from_path['provenance'].values()), {'profile'})
        saved = self.write(yaml.safe_dump(result))
        with self.assertRaises(wp.ProfileError):
            wp.load_profile(saved)

    def test_disabled_dependencies_and_runtime_contamination_fail_closed(self):
        invalid = [
            {'components': {'sim': {'enabled': False}}},
            {'components': {'lab': {'enabled': False}}},
            {'components': {'gr00t': {'enabled': False}}},
            {'runtimes': {'gr00t': {'environment': 'isaaclab'}}},
            {'runtimes': {'lerobot': {'environment': 'gr00t'}}},
            {'runtimes': {'kit': {'environment': 'isaaclab'}}},
        ]
        for overlay in invalid:
            with self.subTest(overlay=overlay), self.assertRaises(wp.ProfileError):
                wp.resolve_profile('full', overlay)
        all_off = {'components': {name: {'enabled': False} for name in ('sim', 'lab', 'arena', 'gr00t', 'lerobot')}, 'serving': {'enabled': False}}
        result = wp.resolve_profile('full', all_off)
        self.assertEqual(result['dependencies']['components']['arena'], ['lab'])
        self.assertEqual(result['dependencies']['components']['lab'], ['sim'])
        self.assertEqual(result['dependencies']['runtimes']['arena'], 'lab')
        self.assertEqual(result['dependencies']['serving'], ['gr00t'])
        self.assertIsNone(result['endpoint'])
        self.assertEqual(wp.resolve_profile('full')['endpoint'], 'tcp://127.0.0.1:5561')
        self.assertEqual(wp.resolve_profile('full', {'serving': {'port': 5562}})['endpoint'], 'tcp://127.0.0.1:5562')

    def test_software_values_are_typed_nonsecret_and_nonexecutable(self):
        invalid = [
            {'components': {'sim': {'source': {'mode': 'custom_build'}}}},
            {'components': {'sim': {'source': {'version': 6.0}}}},
            {'components': {'sim': {'source': {'sha256': 'latest'}}}},
            {'components': {'lab': {'source': {'mode': 'container'}}}},
            {'components': {'lab': {'source': {'repository': 'https://user:DO_NOT_ECHO@github.com/a/b.git'}}}},
            {'components': {'lab': {'source': {'repository': 'https://github.com/a/b.git?token=DO_NOT_ECHO'}}}},
            {'components': {'lab': {'source': {'repository': 'https://github.com/a/b.git#DO_NOT_ECHO'}}}},
            {'components': {'lab': {'source': {'repository': '$(touch DO_NOT_ECHO)'}}}},
            {'components': {'lab': {'source': {'ref': '../main'}}}},
            {'components': {'lab': {'source': {'ref': 'bad.lock'}}}},
            {'components': {'lab': {'source': {'ref': 'bad//branch'}}}},
            {'components': {'lab': {'source': {'ref': '$(DO_NOT_ECHO)'}}}},
            {'components': {'lab': {'source': {'revision': 'v3.0.0'}}}},
            {'components': {'lab': {'source': {'revision': 'deadbeef'}}}},
            {'components': {'lab': {'source': {'ref': None}}}},
            {'components': {'lab': {'runtime': 'base'}}},
            {'runtimes': {'lab': {'manager': 'uv'}}},
            {'runtimes': {'kit': {'manager': 'conda'}}},
            {'runtimes': {'lab': {'environment': 'base'}}},
            {'runtimes': {'gr00t': {'python': 3.12}}},
            {'runtimes': {'gr00t': {'torch': '$(DO_NOT_ECHO)'}}},
            {'runtimes': {'gr00t': {'architecture': 'arbitrary'}}},
            {'serving': {'enabled': 'false'}},
            {'serving': {'bind': '0.0.0.0'}},
            {'serving': {'port': True}},
            {'serving': {'port': 0}},
            {'serving': {'port': 65536}},
            {'serving': {'embodiment': 'bad\nDO_NOT_ECHO'}},
            {'serving': {'model': {'repository': '/home/DO_NOT_ECHO'}}},
            {'serving': {'model': {'ref': 'main;DO_NOT_ECHO'}}},
            {'serving': {'model': {'revision': 'main'}}},
        ]
        for overlay in invalid:
            with self.subTest(overlay=overlay):
                with self.assertRaises(wp.ProfileError) as ctx:
                    wp.resolve_profile('default', overlay)
                self.assertNotIn('DO_NOT_ECHO', str(ctx.exception))

    def test_named_presets_resolve_with_explicit_false_precedence(self):
        self.assertTrue(callable(getattr(wp, 'resolve_profile', None)), 'resolver API is missing')
        self.assertEqual(wp.list_profiles(), ['default', 'full', 'minimal'])
        default = wp.resolve_profile('default')
        self.assertEqual(default['profile']['components']['sim']['source']['version'], '6.0.1')
        self.assertEqual(default['profile']['components']['lab']['source']['ref'], 'v3.0.0-beta2')
        self.assertEqual(default['profile']['components']['arena']['source']['ref'], 'release/0.3.0-prerelease')
        self.assertFalse(default['profile']['components']['gr00t']['enabled'])
        full = wp.resolve_profile('full')['profile']
        self.assertTrue(all(c['enabled'] for c in full['components'].values()))
        self.assertEqual(full['components']['gr00t']['source']['ref'], 'dev')
        self.assertEqual(full['serving']['port'], 5561)
        self.assertEqual(full['serving']['embodiment'], 'NEW_EMBODIMENT')
        self.assertEqual(full['runtimes']['lab']['python'], '3.12')
        self.assertIsNone(full['runtimes']['gr00t']['python'])
        self.assertIsNone(full['runtimes']['lerobot']['python'])
        self.assertEqual(full['runtimes']['lab']['torch'], '2.10.0+cu128')
        self.assertEqual(full['runtimes']['lab']['architecture'], 'sm_120')
        minimal = wp.resolve_profile('minimal')['profile']
        self.assertFalse(minimal['components']['arena']['enabled'])
        path = self.write('schema_version: v1alpha1\nkind: workstation-profile\nname: custom\nextends: full\ncomponents:\n  gr00t: {enabled: false}\nserving: {enabled: false}\n')
        overrides = {'components': {'lerobot': {'enabled': False}}}
        original = copy.deepcopy(overrides)
        custom = wp.resolve_profile(path, overrides)
        self.assertFalse(custom['profile']['components']['gr00t']['enabled'])
        self.assertFalse(custom['profile']['components']['lerobot']['enabled'])
        self.assertEqual(custom['provenance']['components.lerobot.enabled'], 'overrides')
        self.assertEqual(custom['provenance']['components.gr00t.enabled'], 'profile')
        self.assertEqual(custom['provenance']['components.arena.enabled'], 'preset:full')
        self.assertEqual(overrides, original)
        self.assertEqual(wp.validate_profile('default'), default)
        json.dumps(custom, allow_nan=False)
        for invalid in ({'extends': 'full'}, {'name': 'oops'}, {'kind': 'workstation-baseline'}, {'target': 'ansible'}, {'bad': 3}):
            with self.subTest(override=invalid), self.assertRaises(wp.ProfileError):
                wp.resolve_profile('default', invalid)
        with self.assertRaises(wp.ProfileError):
            wp.load_profile('defualt')

    def test_strict_loader_rejects_ambiguous_or_observed_input(self):
        header = 'schema_version: v1alpha1\nkind: workstation-profile\nname: custom\n'
        invalid = [
            header + 'name: duplicate\n',
            header + 'unknown_secret: DO_NOT_ECHO\n',
            header + 'components: {lab: {enabled: true, enabled: false}}\n',
            header + 'components: {lab: {typo: true}}\n',
            header + 'components: {lab: {enabled: "false"}}\n',
            header + 'target: ansible\n',
            header + 'extends: /private/DO_NOT_ECHO.yaml\n',
            header + 'runtimes: {lab: &x {python: "3.12"}, gr00t: *x}\n',
            header + 'components: {lab: {<<: {enabled: true}}}\n',
            'kind: workstation-baseline\nsecret: DO_NOT_ECHO\n',
            'version: "1.0"\nprofile_name: old\n',
            'schema_version: v1alpha1\nprofile_name: cloud\nsecurity: {}\n',
            header.replace('v1alpha1', 'v99'),
            header.replace('name: custom', 'name: 5'),
            '[]', 'null', '!!python/object:DO_NOT_ECHO {}',
            header + '---\nname: other\n',
        ]
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(wp.ProfileError) as ctx:
                    wp.load_profile(self.write(text))
                self.assertNotIn('DO_NOT_ECHO', str(ctx.exception))
        with self.assertRaises(wp.ProfileError):
            wp.load_profile(Path(self.temp.name) / 'missing.yaml')

    def test_load_desired_document_without_side_effects(self):
        self.assertIsNotNone(wp, 'workstation profile module must exist')
        path = self.write('schema_version: v1alpha1\nkind: workstation-profile\nname: custom\n')
        self.assertEqual(wp.load_profile(path), {
            'schema_version': 'v1alpha1', 'kind': 'workstation-profile', 'name': 'custom'})
        self.assertTrue(issubclass(wp.ProfileError, ValueError))


if __name__ == '__main__':
    unittest.main()
