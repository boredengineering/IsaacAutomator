#!/usr/bin/env python3
"""Offline backend selection contract; all inputs are public synthetic data."""
import tempfile
import unittest
from pathlib import Path
import click
import os
from unittest import mock
from click.core import ParameterSource

from src.python import backend_selection as selection


class TestBackendConfigLoader(unittest.TestCase):
    def test_nonregular_config_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.yaml"
            os.mkfifo(path)
            with mock.patch("builtins.open", side_effect=AssertionError("blocking read attempted")) as read:
                with self.assertRaises(selection.BackendSelectionError):
                    selection.load_backend_config(path)
                read.assert_not_called()

    def test_strict_standalone_config_parser(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.yaml"
            for text in ('backend: local', 'terraform_state:\n  backend: local',
                         '{"terraform_state": {"backend": "local"}}'):
                path.write_text(text)
                self.assertEqual(selection.load_backend_config(path), {"backend": "local"})
            for text in (
                'backend: local\nbackend: gcs',
                '{"backend":"local","backend":"s3"}',
                'terraform_state: {backend: local}\nother: private-sentinel',
                'backend: local\nauthentication: {token: private-sentinel}',
                'backend: local\nunknown: private-sentinel',
                'backend: local\n---\nbackend: gcs',
                'backend: &value local\nnamespace: *value',
                '<<: {backend: local}',
                'backend: [private-sentinel',
                'null', '[]', '', 'x' * (65536 + 1),
            ):
                with self.subTest(kind=text[:20]):
                    path.write_text(text)
                    with self.assertRaises(ValueError) as caught:
                        selection.load_backend_config(path)
                    self.assertNotIn('private-sentinel', str(caught.exception))


class TestSelection(unittest.TestCase):
    def test_legacy_environment_is_opt_in_for_programmatic_callers(self):
        with mock.patch.dict(os.environ, ISAAC_STATE_BUCKET='example-state'):
            with self.assertRaisesRegex(ValueError, 'not implemented'):
                selection.select_backend({}, {}, 'aws')
            self.assertEqual(selection.select_backend({'state_backend': 'local'}, {}, 'aws').backend, 'local')

    def test_profile_normalizes_state_and_rejects_ambiguous_yaml(self):
        from src.python.config import load_profile_spec, list_available_profiles
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'configs' / 'profiles'
            directory.mkdir(parents=True)
            path = directory / 'example.yaml'
            path.write_text('profile_name: example\ncloud: gcp\nterraform_state: {backend: local}')
            spec = load_profile_spec(str(path), repo_root=root)
            self.assertEqual(spec['terraform_state']['workspace'], 'default')
            self.assertEqual(list_available_profiles(root)['example']['terraform_state'], spec['terraform_state'])
            for text in (
                'terraform_state: {backend: local}\nterraform_state: {backend: gcs}',
                'terraform_state: {backend: local, token: private-sentinel}',
                'terraform_state: null',
            ):
                path.write_text(text)
                with self.assertRaises(ValueError) as caught:
                    load_profile_spec(str(path), repo_root=root)
                self.assertNotIn('private-sentinel', str(caught.exception))

    def test_exact_precedence_uses_click_sources(self):
        remote = {"backend": "gcs", "namespace": "studio", "destination": {
            "bucket": "example-state", "project": "example-project", "prefix": "isaacautomator/v2"}}
        profile = {"terraform_state": remote}
        ctx = click.Context(click.Command('selection'))
        ctx.set_parameter_source('state_backend', ParameterSource.DEFAULT)
        self.assertEqual(selection.select_backend({'state_backend': 'local'}, profile, 'gcp', ctx).backend, 'gcs')
        ctx.set_parameter_source('state_backend', ParameterSource.COMMANDLINE)
        local = selection.select_backend({'state_backend': 'local'}, profile, 'gcp', ctx)
        self.assertEqual(local.backend, 'local')
        self.assertNotIn('destination', local.to_dict())
        self.assertEqual(selection.select_backend({}, {}, 'aws').backend, 'local')
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'backend.yaml'
            import json
            path.write_text(json.dumps(remote))
            ctx.set_parameter_source('backend_config', ParameterSource.COMMANDLINE)
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                selection.select_backend({'state_backend': 'local', 'backend_config': str(path)}, {}, 'gcp', ctx)
            ctx.set_parameter_source('state_backend', ParameterSource.DEFAULT)
            self.assertEqual(selection.select_backend({'state_backend': 'local', 'backend_config': str(path)}, {}, 'gcp', ctx).backend, 'gcs')
            with self.assertRaises(ValueError):
                selection.select_backend({'backend_config': str(path)}, {}, 'aws')
        for cloud in ('aws', 'gcp', 'azure', 'alicloud'):
            with self.subTest(cloud=cloud), self.assertRaisesRegex(ValueError, 'not implemented'):
                selection.select_backend({'state_bucket': 'auto'}, {}, cloud)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            selection.select_backend({'state_backend': 'local', 'state_bucket': 'example-state'}, {}, 'gcp')
        self.assertEqual(selection.select_backend({'state_backend': 'local'}, {'state_bucket': 'auto'}, 'gcp').backend, 'local')


if __name__ == '__main__':
    unittest.main()
