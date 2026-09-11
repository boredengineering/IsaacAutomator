#!/usr/bin/env python3

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import click

from src.python.config import c

from src.python.utils import (
    format_cloud_name,
    format_instance_role,
    read_local_tfstate,
    read_tf_output,
    require_legacy_local_backend,
    subnet_from_ip,
)


class Test_LocalOutputSafety(unittest.TestCase):
    def test_gcp_auth_accepts_supplied_token_and_never_prompts_headless(self):
        from src.python.utils import gcp_login
        with mock.patch.dict(os.environ, {'GOOGLE_OAUTH_ACCESS_TOKEN': 'synthetic-token'}, clear=True), \
             mock.patch('src.python.utils.shell_command') as shell, \
             mock.patch('src.python.utils.subprocess.run') as run, mock.patch('click.echo') as output:
            gcp_login(verbose=True)
            shell.assert_not_called()
            run.assert_not_called()
            self.assertNotIn('synthetic-token', str(output.call_args_list))
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch('src.python.utils.shell_command') as shell, \
             mock.patch('src.python.utils.subprocess.run', return_value=mock.Mock(returncode=1)) as run, \
             mock.patch('sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(click.ClickException, 'ADC|authentication'):
                gcp_login()
            shell.assert_not_called()
            self.assertFalse(run.call_args.kwargs['shell'])
            self.assertEqual(run.call_args.kwargs['stdout'], __import__('subprocess').DEVNULL)

    def test_saved_gcs_output_dispatches_backend_only_without_local_state(self):
        from src.python.terraform_backend import BackendSpec
        from src.python.terraform_runner import TerraformRunnerError
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'demo'
            directory.mkdir()
            (directory / 'meta.json').write_text(json.dumps({'params': {
                'terraform_state': spec.to_dict(), 'state_backend': 'gcs', 'cloud': 'gcp',
                'project': 'target-project', 'deployment_name': 'demo',
                'backend_runtime': {'identity': spec.identity('target-project', 'demo'),
                                    'status': 'active', 'lineage': 'fixture-lineage'}}}))
            with mock.patch('src.python.backend_runtime.record_runner') as factory, \
                 mock.patch('src.python.utils.read_local_tfstate', side_effect=AssertionError('no local state')):
                runner = factory.return_value.__enter__.return_value
                runner.output.return_value = {'ip': {'value': '192.0.2.10', 'type': 'string', 'sensitive': False}}
                self.assertEqual(read_tf_output('demo', 'ip', state_dir=root), '192.0.2.10')
                self.assertTrue(factory.call_args.kwargs['read_only'])
                runner.init.assert_called_once()
                self.assertEqual(read_tf_output('demo', 'optional', state_dir=root), '')
                runner.output.side_effect = TerraformRunnerError('GCS read failed')
                with self.assertRaises(click.ClickException):
                    read_tf_output('demo', 'ip', state_dir=root)

    def test_migration_or_retirement_marker_blocks_legacy_without_reading_it(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ("migration.json", "relocation.json"):
                for kind in ("regular", "dangling-link", "fifo", "directory"):
                    marker = directory / name
                    if kind == "regular":
                        marker.write_text("untrusted private migration details")
                    elif kind == "dangling-link":
                        marker.symlink_to(directory / "absent")
                    elif kind == "fifo":
                        os.mkfifo(marker)
                    else:
                        marker.mkdir()
                    with self.subTest(name=name, kind=kind), \
                            mock.patch("pathlib.Path.read_text", side_effect=AssertionError("must not read marker")), \
                            self.assertRaises(click.ClickException):
                        require_legacy_local_backend(directory)
                    marker.rmdir() if kind == "directory" else marker.unlink()

    def test_output_deployment_name_cannot_escape_custom_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approved = root / "approved"
            approved.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / ".tfstate").write_text(json.dumps({
                "version": 4, "resources": [],
                "outputs": {"ip": {"value": "synthetic-private-output"}},
            }))
            for name in ("../outside", "../outside/.", str(outside)):
                with self.subTest(name=name):
                    with self.assertRaises(click.ClickException) as error:
                        read_tf_output(name, "ip", state_dir=approved)
                    self.assertNotIn("synthetic-private-output", str(error.exception))
                    self.assertNotIn(tmp, str(error.exception))

    def test_output_rejects_symlinked_root_or_any_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual = root / "actual"
            deployment = actual / "nested" / "demo"
            deployment.mkdir(parents=True)
            (deployment / ".tfstate").write_text(json.dumps({
                "version": 4, "resources": [], "outputs": {"ip": {"value": "synthetic"}},
            }))
            alias = root / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            direct = root / "direct"
            direct.symlink_to(actual / "nested", target_is_directory=True)
            for state_dir in (alias / "nested", direct):
                with self.subTest(state_dir=state_dir):
                    with self.assertRaises(click.ClickException):
                        read_tf_output("demo", "ip", state_dir=state_dir)

    def test_legacy_guard_rejects_symlinked_ancestors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "actual" / "nested" / "demo").mkdir(parents=True)
            (root / "alias").symlink_to(root / "actual", target_is_directory=True)
            with self.assertRaises(click.ClickException):
                require_legacy_local_backend(root / "alias" / "nested" / "demo")

    def test_unavailable_state_is_not_an_empty_output(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(c, state_dir=tmp):
            path = Path(tmp) / "demo" / ".tfstate"
            path.parent.mkdir()
            for text in [None, "{invalid-json", "null", '{"outputs": []}']:
                with self.subTest(text=text):
                    if text is not None:
                        path.write_text(text)
                    with self.assertRaises(click.ClickException):
                        read_tf_output("demo", "ip")

    def test_remote_attachment_never_returns_a_stale_local_output(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(c, state_dir=tmp):
            deployment = Path(tmp) / "demo"
            deployment.mkdir()
            (deployment / ".tfstate").write_text(json.dumps({
                "version": 4, "resources": [],
                "outputs": {"ip": {"value": "192.0.2.1"}},
            }))
            for filename, data in [
                ("backend.json", {"backend": "gcs"}),
                ("meta.json", {"params": {"state_bucket": "auto"}}),
                ("meta.json", {"input_params": {"state_bucket": "example-bucket"}}),
            ]:
                with self.subTest(filename=filename, data=data):
                    marker = deployment / filename
                    marker.write_text(json.dumps(data))
                    with self.assertRaises(click.ClickException):
                        read_tf_output("demo", "ip")
                    marker.unlink()

    def test_state_readers_refuse_unsupported_or_incomplete_envelopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            deployment = Path(tmp) / "demo"
            deployment.mkdir()
            path = deployment / ".tfstate"
            valid = {"version": 4, "resources": [], "outputs": {"ip": {"value": "synthetic-private-output"}}}
            invalid = [
                {**valid, "version": 999},
                {**valid, "version": 4.0},
                {"outputs": {}},
                {key: value for key, value in valid.items() if key != "resources"},
                {key: value for key, value in valid.items() if key != "outputs"},
                {**valid, "resources": {}},
                {**valid, "outputs": []},
                {**valid, "outputs": {"ip": {"value": "synthetic-private-output"}, "other": None}},
            ]
            readers = (
                lambda: read_tf_output("demo", "ip", state_dir=tmp),
                lambda: read_local_tfstate(path),
            )
            for index, state in enumerate(invalid):
                path.write_text(json.dumps(state))
                for reader_index, reader in enumerate(readers):
                    with self.subTest(case=index, reader=reader_index):
                        with self.assertRaises(click.ClickException) as error:
                            reader()
                        self.assertNotIn("synthetic-private-output", str(error.exception))
                        self.assertNotIn(tmp, str(error.exception))

    def test_optional_output_fields_do_not_require_state_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            deployment = Path(tmp) / "demo"
            deployment.mkdir()
            for outputs, expected in (
                ({}, ""), ({"ip": {}}, ""), ({"ip": {"value": None}}, ""),
                ({"ip": {"value": "192.0.2.1"}}, "192.0.2.1"),
                ({"ip": {"value": 0}}, "0"),
            ):
                with self.subTest(outputs=outputs):
                    (deployment / ".tfstate").write_text(json.dumps({
                        "version": 4, "resources": [], "outputs": outputs,
                    }))
                    self.assertEqual(read_tf_output("demo", "ip", state_dir=tmp), expected)

    def test_state_readers_reject_malformed_resource_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            deployment = Path(tmp) / "demo"
            deployment.mkdir()
            path = deployment / ".tfstate"
            for resource in (
                {}, {"instances": []}, {"mode": "unknown", "instances": []},
                {"mode": "managed"}, {"mode": "managed", "instances": None},
                {"mode": "managed", "instances": {}},
                {"mode": "data", "instances": "synthetic-private-value"},
                {"mode": "data", "instances": [None]},
                {"mode": "managed", "instances": ["synthetic-private-value"]},
            ):
                path.write_text(json.dumps({"version": 4, "resources": [resource], "outputs": {}}))
                for reader in (lambda: read_local_tfstate(path), lambda: read_tf_output("demo", "ip", state_dir=tmp)):
                    with self.subTest(resource=resource, reader=reader):
                        with self.assertRaises(click.ClickException) as error:
                            reader()
                        self.assertNotIn("synthetic-private-value", str(error.exception))

    def test_metadata_symlinks_never_allow_local_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            deployment = Path(tmp) / "demo"
            deployment.mkdir()
            (deployment / ".tfstate").write_text(json.dumps({
                "version": 4, "resources": [], "outputs": {"ip": {"value": "synthetic"}},
            }))
            target = Path(tmp) / "synthetic-private-metadata"
            marker = deployment / "meta.json"
            marker.symlink_to(target)
            for exists in (False, True):
                with self.subTest(exists=exists):
                    if exists:
                        target.write_text("{}")
                    with self.assertRaises(click.ClickException) as error:
                        read_tf_output("demo", "ip", state_dir=tmp)
                    self.assertNotIn(str(target), str(error.exception))


    def test_nested_backend_metadata_never_allows_local_fallback(self):
        blocks = [
            {"terraform_state": {"backend": "s3"}},
            {"terraform_state": {"backend": "local", "unexpected": "field"}},
            {"profile_spec": {"raw": {"security": {"storage": {"state_bucket": "legacy-bucket"}}}}},
            {"backend_config": "unverified-external.yaml"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "demo"
            directory.mkdir()
            for block in blocks:
                with self.subTest(block=block):
                    (directory / "meta.json").write_text(json.dumps({"params": block}))
                    with self.assertRaises(click.ClickException):
                        require_legacy_local_backend(directory)
            (directory / "meta.json").write_text(json.dumps({
                "params": {"terraform_state": {"schema_version": 1, "backend": "local"}},
            }))
            require_legacy_local_backend(directory)


    def test_nonregular_metadata_is_rejected_before_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            os.mkfifo(directory / "meta.json")
            with mock.patch.object(Path, "read_text", return_value="{}") as read:
                with self.assertRaises(click.ClickException):
                    require_legacy_local_backend(directory)
                read.assert_not_called()


class Test_SubnetFromIp(unittest.TestCase):
    def test_slash_24(self):
        self.assertEqual(subnet_from_ip("10.0.1.42", "24"), "10.0.1.0/24")

    def test_slash_16(self):
        self.assertEqual(subnet_from_ip("10.0.1.42", "16"), "10.0.0.0/16")

    def test_slash_8(self):
        self.assertEqual(subnet_from_ip("10.0.1.42", "8"), "10.0.0.0/8")

    def test_unsupported_mask_raises(self):
        with self.assertRaises(Exception):
            subnet_from_ip("10.0.1.42", "12")


class Test_FormatCloudName(unittest.TestCase):
    def test_known_clouds(self):
        self.assertEqual(format_cloud_name("aws"), "AWS")
        self.assertEqual(format_cloud_name("azure"), "Azure")
        self.assertEqual(format_cloud_name("gcp"), "GCP")
        self.assertEqual(format_cloud_name("alicloud"), "Alibaba Cloud")

    def test_unknown_cloud_passthrough(self):
        self.assertEqual(format_cloud_name("oracle"), "oracle")


class Test_FormatInstanceRole(unittest.TestCase):
    def test_known_role(self):
        self.assertEqual(format_instance_role("isaac_workstation"), "Isaac Workstation")

    def test_unknown_role_passthrough(self):
        self.assertEqual(format_instance_role("other"), "other")


if __name__ == "__main__":
    unittest.main()
