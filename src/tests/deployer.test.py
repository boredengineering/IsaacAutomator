#!/usr/bin/env python3

import json
import os
import shutil
import tempfile
import unittest
import click
from unittest import mock
from pathlib import Path

from src.python.config import c
from src.python.deployer import Deployer


def setUpModule():
    patcher = mock.patch('src.python.deployer.get_my_public_ip', return_value='192.0.2.1')
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)

# Base parameter set used by the helper below.
_BASE_PARAMS = {
    "debug": False,
    "prefix": "isa",
    "from_image": False,
    "deployment_name": "test-1",
    "existing": "ask",
    "in_china": "no",
    "region": "us-east-1",
    "isaac": True,
    "isaac_workstation_instance_type": "g5.2xlarge",
    "isaac_image": "nvcr.io/nvidia/isaac-sim:2022.2.0",
    "vnc_password": "__vnc_password__",
    "ssh_port": 22,
    "upload": True,
    "aws_access_key_id": "__aws_access_key_id__",
    "aws_secret_access_key": "__aws_secret_access_key__",
    "ingress_cidrs": "auto",
}


def _make_deployer(state_dir, extra=None):
    """
    Build a Deployer with a minimal valid param set, optionally overridden.
    Callers MUST pass an isolated state_dir so explicit metadata saves
    at workflow boundaries do not mutate checked-in fixtures.
    """
    config = c.copy()
    config["state_dir"] = state_dir

    params = dict(_BASE_PARAMS)
    if extra:
        params.update(extra)

    return Deployer(params=params, config=config)


class Test_Deployer(unittest.TestCase):
    """
    Reads from the checked-in test-1 fixture but writes outputs into an
    isolated temp dir so the fixture files stay untouched. We copy the
    fixture into the temp dir before running.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fixture_src = Path(c["tests_dir"]) / "res" / "state" / "test-1"
        fixture_dst = Path(self.tmp) / "test-1"
        shutil.copytree(fixture_src, fixture_dst)
        self.deployer = _make_deployer(state_dir=self.tmp)

    def tearDown(self):
        self.deployer = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_output_deployment_info(self):
        self.deployer.output_deployment_info(print_text=False)

        file_generated = Path(self.tmp) / "test-1" / "info.txt"
        file_expected = Path(self.tmp) / "test-1" / "info.expected.txt"

        self.assertEqual(file_generated.read_text(), file_expected.read_text())


class Test_RecreateCommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_includes_string_options(self):
        deployer = _make_deployer(state_dir=self.tmp)
        cmd = deployer.recreate_command_line(separator=" ")
        self.assertIn("--prefix isa", cmd)
        self.assertIn("--deployment-name test-1", cmd)
        self.assertIn("--region us-east-1", cmd)

    def test_outputs_use_the_deployers_own_state_directory(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = Path(self.tmp) / "test-1" / ".tfstate"
        path.parent.mkdir()
        path.write_text(json.dumps({
            "version": 4, "resources": [],
            "outputs": {"isaac_workstation_ip": {"value": "192.0.2.10"}},
        }))
        with mock.patch.dict(c, state_dir=str(Path(self.tmp) / "unrelated-controller")):
            self.assertEqual(deployer.tf_output("isaac_workstation_ip"), "192.0.2.10")

    def test_quotes_strings_with_spaces(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"region": "us east 1"})
        cmd = deployer.recreate_command_line(separator=" ")
        self.assertIn("'us east 1'", cmd)

    def test_key_export_uses_the_deployers_own_state_directory(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = Path(self.tmp) / "test-1" / ".tfstate"
        path.parent.mkdir()
        path.write_text(json.dumps({
            "version": 4, "resources": [],
            "outputs": {"ssh_key": {"value": "synthetic-not-a-private-key"}},
        }))
        with mock.patch.dict(c, state_dir=str(Path(self.tmp) / "unrelated-controller")):
            deployer.export_ssh_key()
        key = path.parent / "key.pem"
        self.assertEqual(key.read_text(), "synthetic-not-a-private-key\n")
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)


    def test_blank_legacy_inventory_connection_values_are_refused(self):
        deployer = _make_deployer(state_dir=self.tmp)
        template = mock.Mock()
        template.format.return_value = 'must-not-be-written'
        for cloud, ip in (('aws', ''), ('aws', 'not-an-ip'), ('', '192.0.2.10')):
            deployer.params.update(cloud=cloud, isaac_workstation_ip=ip)
            with self.subTest(cloud=cloud, ip=ip), \
                 mock.patch('src.python.deployer.Path.read_text', return_value=template):
                with self.assertRaisesRegex(click.ClickException, 'output'):
                    deployer.create_ansible_inventory()
        self.assertFalse((Path(self.tmp) / 'test-1' / '.inventory').exists())

    def test_blank_legacy_ssh_key_is_never_exported(self):
        deployer = _make_deployer(state_dir=self.tmp)
        with mock.patch('src.python.deployer.read_tf_output', return_value='   '):
            with self.assertRaisesRegex(click.ClickException, 'SSH key'):
                deployer.export_ssh_key()
        self.assertFalse((Path(self.tmp) / 'test-1' / 'key.pem').exists())

    def test_boolean_flags(self):
        deployer = _make_deployer(
            state_dir=self.tmp, extra={"upload": True, "from_image": False}
        )
        cmd = deployer.recreate_command_line(separator=" ")
        self.assertIn("--upload", cmd)
        self.assertNotIn("--no-upload", cmd)
        # from-image uses --not- prefix when False
        self.assertIn("--not-from-image", cmd)


class Test_WriteTfvarsFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_strings_lists_and_bools(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = f"{self.tmp}/.tfvars"
        deployer._write_tfvars_file(
            path=path,
            tfvars={
                "prefix": "isa",
                "isaac_enabled": True,
                "from_image": False,
                "ingress_cidrs": ["10.0.0.0/8", "1.2.3.4/32"],
                "ssh_port": 22,
            },
        )
        content = Path(path).read_text()

        self.assertIn('prefix = "isa"', content)
        # booleans are stringified then quoted; terraform parses them into bool vars
        self.assertIn('isaac_enabled = "true"', content)
        self.assertIn('from_image = "false"', content)
        self.assertIn('ingress_cidrs = ["10.0.0.0/8", "1.2.3.4/32"]', content)
        self.assertIn("ssh_port = 22", content)

    def test_escapes_quotes_in_strings(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = f"{self.tmp}/.tfvars"
        deployer._write_tfvars_file(
            path=path,
            tfvars={"password": 'has "quotes"'},
        )
        content = Path(path).read_text()
        self.assertIn(r'password = "has \"quotes\""', content)

    def test_normalizes_hyphen_keys_to_underscores(self):
        deployer = _make_deployer(state_dir=self.tmp)
        path = f"{self.tmp}/.tfvars"
        deployer._write_tfvars_file(
            path=path,
            tfvars={"resource-group": "rg-1"},
        )
        content = Path(path).read_text()
        self.assertIn('resource_group = "rg-1"', content)


class Test_InChinaConversion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_yes_becomes_true(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"in_china": "yes"})
        self.assertTrue(deployer.params["in_china"])

    def test_no_becomes_false(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"in_china": "no"})
        self.assertFalse(deployer.params["in_china"])

    def test_auto_becomes_false(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"in_china": "auto"})
        self.assertFalse(deployer.params["in_china"])


class Test_ResolveDemos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_demos_is_noop(self):
        deployer = _make_deployer(
            state_dir=self.tmp, extra={"demos": "no", "isaacsim": "no", "isaaclab": "no"}
        )
        self.assertEqual(deployer.params["demos"], "no")
        # apps left off must stay off
        self.assertEqual(deployer.params["isaacsim"], "no")
        self.assertEqual(deployer.params["isaaclab"], "no")

    def test_unknown_demo_exits(self):
        with self.assertRaises(SystemExit):
            _make_deployer(state_dir=self.tmp, extra={"demos": "does-not-exist"})

    def test_autoenables_required_apps(self):
        deployer = _make_deployer(
            state_dir=self.tmp,
            extra={
                "demos": "quadruped-locomotion",
                "isaacsim": "no",
                "isaaclab": "no",
            },
        )
        self.assertEqual(
            deployer.params["isaacsim"], c["default_isaacsim_git_checkpoint"]
        )
        self.assertEqual(
            deployer.params["isaaclab"], c["default_isaaclab_git_checkpoint"]
        )
        self.assertEqual(deployer.params["demos"], "quadruped-locomotion")

    def test_keeps_explicit_app_ref(self):
        deployer = _make_deployer(
            state_dir=self.tmp,
            extra={
                "demos": "quadruped-locomotion",
                "isaacsim": "v1.2.3",
                "isaaclab": "no",
            },
        )
        # an explicitly chosen ref is untouched; only the disabled app is enabled
        self.assertEqual(deployer.params["isaacsim"], "v1.2.3")
        self.assertEqual(
            deployer.params["isaaclab"], c["default_isaaclab_git_checkpoint"]
        )


class Test_SecurityProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_profile_is_simple(self):
        deployer = _make_deployer(state_dir=self.tmp)
        self.assertEqual(deployer.params["security_profile"], "simple")
        self.assertEqual(deployer.params["profile"], "simple")

    def test_simple_flag_sets_simple_profile(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"simple": True, "profile": "enterprise"})
        self.assertEqual(deployer.params["security_profile"], "simple")

    def test_team_and_enterprise_profiles(self):
        with mock.patch("click.echo") as echo:
            deployer_team = _make_deployer(state_dir=self.tmp, extra={"profile": "team"})
        self.assertEqual(deployer_team.params["state_bucket"], "")
        self.assertIn("local state", str(echo.call_args_list))
        self.assertIn("explicit", str(echo.call_args_list))
        self.assertEqual(deployer_team.params["security_profile"], "team")

        deployer_ent = _make_deployer(state_dir=self.tmp, extra={"profile": "enterprise"})
        self.assertEqual(deployer_ent.params["state_bucket"], "")
        self.assertEqual(deployer_ent.params["security_profile"], "enterprise")

    def test_unknown_profile_exits(self):
        with self.assertRaises(SystemExit):
            _make_deployer(state_dir=self.tmp, extra={"profile": "invalid-profile"})

    def test_simple_mode_tfvars_contains_security_profile(self):
        deployer = _make_deployer(state_dir=self.tmp, extra={"profile": "simple"})
        tfvars = {}
        deployer.create_tfvars(tfvars=tfvars)
        self.assertEqual(tfvars.get("security_profile"), "simple")
        self.assertFalse(tfvars.get("enable_cmek"))
        self.assertFalse(tfvars.get("enable_iap_only"))

    def test_custom_yaml_profile_loading(self):
        custom_yaml = os.path.join(self.tmp, "my-custom-profile.yaml")
        with open(custom_yaml, "w") as f:
            f.write("""
schema_version: "v1alpha1"
profile_name: "my-custom-profile"
security:
  tier: "custom"
  network:
    iap_only: true
    cloud_nat: true
  storage:
    state_backend: "gcs"
    state_bucket: "gs://custom-state-bucket"
  cryptography:
    encryption_type: "kms_cmek"
  compute:
    os_login: true
""")
        from src.python.config import load_profile_spec
        spec = load_profile_spec(custom_yaml)
        self.assertEqual(spec["tier"], "custom")
        self.assertTrue(spec["enable_iap_only"])
        self.assertTrue(spec["enable_cmek"])
        self.assertTrue(spec["enable_oslogin"])
        self.assertEqual(spec["state_bucket"], "gs://custom-state-bucket")
        with self.assertRaisesRegex(click.ClickException, "not implemented"):
            _make_deployer(state_dir=self.tmp, extra={"profile": custom_yaml})

    def test_discovered_profile_name_resolution(self):
        from src.python.config import load_profile_spec
        spec = load_profile_spec("team-studio")
        self.assertEqual(spec["tier"], "team")
        self.assertEqual(spec["state_bucket"], "auto")
        with self.assertRaisesRegex(click.ClickException, "not implemented"):
            _make_deployer(state_dir=self.tmp, extra={"profile": "team-studio"})

    @mock.patch("src.python.deployer.shell_command")
    def test_dry_run_plan_and_validate(self, mock_shell):
        deployer = _make_deployer(state_dir=self.tmp, extra={"dry_run": True, 'cloud': 'gcp'})
        with mock.patch('src.python.deployer.TerraformRunner') as factory:
            factory.return_value.recovery_directory = None
            runner = factory.return_value.__enter__.return_value
            runner.plan.return_value.has_changes = True
            self.assertTrue(deployer.plan_terraform(cwd=f"{c['terraform_dir']}/gcp"))
            # Terraform plan validates configuration; there is no independent
            # shared-source validate or apply, and no raw plan output is logged.
            self.assertEqual(runner.method_calls, [mock.call.init(), mock.call.plan()])
            factory.return_value.__exit__.assert_called_once()
            mock_shell.assert_not_called()

        deployer.validate_ansible()
        self.assertEqual(mock_shell.call_count, 1)
        self.assertIn("ansible-playbook --syntax-check", mock_shell.call_args_list[0][0][0])


class TestLocalTerraformIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deployer = _make_deployer(str(self.root / 'custom state'), {'cloud': 'aws'})
        self.deployer.config['terraform_dir'] = str(self.root / 'terraform')
        self.source = self.root / 'terraform' / 'aws'
        self.source.mkdir(parents=True)
        from src.python.terraform_sources import workstation_source_files
        for relative in workstation_source_files('aws'):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')
        self.inputs = self.root / 'custom state' / 'test-1' / '.tfvars'
        self.inputs.parent.mkdir()
        self.inputs.write_text('prefix = "original-repair-input"\n')

    def _provider_free_fixture(self):
        (self.source / 'main.tf').write_text('''
terraform {
  backend "local" {}
}
variable "prefix" { type = string }
module "fixture" {
  source = "./common"
  value = var.prefix
}
output "fixture" { value = module.fixture.value }
output "cloud" { value = "aws" }
output "isaac_workstation_ip" { value = "192.0.2.10" }
output "ssh_key" {
  value = "synthetic-not-a-private-key"
  sensitive = true
}
''')
        (self.source / 'common/main.tf').write_text('''
variable "value" { type = string }
output "value" { value = var.value }
''')
        # Nonallowlisted operational artifacts must neither load nor be changed.
        (self.source / 'backend_override.tf.json').write_text('untrusted stale backend')
        (self.source / 'secret.auto.tfvars').write_text('prefix = "must-not-load"')
        (self.source / 'unreviewed.tf').write_text('invalid unreviewed executable source')
        (self.source / '.terraform').mkdir()
        (self.source / '.terraform' / 'terraform.tfstate').write_text('stale backend data')

    def _source_snapshot(self):
        return {str(p.relative_to(self.source)): (p.read_bytes(), p.stat().st_mode)
                for p in self.source.rglob('*') if p.is_file()}

    def test_actual_provider_free_public_api_preserves_legacy_inputs_and_source(self):
        self._provider_free_fixture()
        # Native Terraform HCL syntax, deliberately not a JSON-compatible line parser.
        self.inputs.write_text('/* legacy repair input */\nprefix = <<-VALUE\nold-input\nVALUE\n')
        before = self._source_snapshot()
        from src.python.terraform_runner import TerraformRunner
        contexts = []
        def factory(**kwargs):
            runner = TerraformRunner(**kwargs)
            contexts.append(runner)
            return runner
        with mock.patch('src.python.deployer.TerraformRunner', side_effect=factory), \
             mock.patch('src.python.deployer.shell_command') as shell:
            self.deployer.initialize_terraform(str(self.source))
            self.assertIsNone(contexts[-1]._temp)
            self.assertTrue(self.deployer.plan_terraform(str(self.source)))
            self.assertFalse((self.inputs.parent / '.tfstate').exists())
            self.deployer.run_terraform(str(self.source))
            self.assertEqual(self.deployer.tf_output('fixture'), 'old-input\n')
            self.assertFalse(self.deployer.plan_terraform(str(self.source)))
            shell.assert_not_called()
        for runner in contexts:
            self.assertIsNone(runner._temp)
            self.assertIsNone(runner._lock_fd)
        self.assertEqual(before, self._source_snapshot())
        self.assertIn('/* legacy repair input */', self.inputs.read_text())

    def test_actual_concurrent_public_applies_isolate_data_inputs_and_states(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from src.python.terraform_runner import TerraformRunner
        self._provider_free_fixture()
        before = self._source_snapshot()
        other = _make_deployer(str(self.inputs.parent.parent), {'cloud': 'aws', 'deployment_name': 'test-2'})
        other.config['terraform_dir'] = self.deployer.config['terraform_dir']
        second_input = self.inputs.parent.parent / 'test-2' / '.tfvars'
        second_input.parent.mkdir()
        second_input.write_text('prefix = "other-deployment"\n')
        barrier = threading.Barrier(2, timeout=20)
        contexts = []
        class ConcurrentRunner(TerraformRunner):
            def __enter__(runner):
                active = super().__enter__()
                contexts.append(runner)
                try:
                    barrier.wait()
                except BaseException:
                    runner.__exit__(None, None, None)
                    raise
                return active
        with mock.patch('src.python.deployer.TerraformRunner', ConcurrentRunner), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(d.run_terraform, str(self.source)) for d in (self.deployer, other)]
            for future in futures:
                future.result(timeout=60)
        self.assertEqual(self.deployer.tf_output('fixture'), 'original-repair-input')
        self.assertEqual(other.tf_output('fixture'), 'other-deployment')
        self.assertEqual(len({r.staged_root for r in contexts}), 2)
        self.assertEqual(len({r.data_dir for r in contexts}), 2)
        self.assertEqual(len({r.local_state_path for r in contexts}), 2)
        self.assertTrue(all(not r.staged_root.exists() for r in contexts))
        self.assertEqual(before, self._source_snapshot())

    def test_actual_dry_run_rejects_invalid_configuration_without_state_or_logs(self):
        self._provider_free_fixture()
        self.deployer.params.update(dry_run=True, debug=True)
        (self.source / 'outputs.tf').write_text('output "secret-sentinel" { value = var.not_declared }\n')
        from src.python.terraform_runner import TerraformRunner
        contexts = []
        def factory(**kwargs):
            runner = TerraformRunner(**kwargs)
            contexts.append(runner)
            return runner
        with mock.patch('src.python.deployer.TerraformRunner', side_effect=factory), mock.patch('click.echo') as echo:
            self.deployer.initialize_terraform(str(self.source))
            with self.assertRaisesRegex(click.ClickException, 'diagnostics withheld') as caught:
                self.deployer.plan_terraform(str(self.source))
        self.assertNotIn('secret-sentinel', str(caught.exception))
        self.assertNotIn('secret-sentinel', str(echo.call_args_list))
        self.assertFalse((self.inputs.parent / '.tfstate').exists())
        self.assertTrue(all(r._temp is None and r._lock_fd is None for r in contexts))

    def test_incomplete_postapply_snapshot_blocks_key_and_inventory_writes(self):
        good = {'cloud': 'aws', 'isaac_workstation_ip': '192.0.2.10', 'ssh_key': 'synthetic-key'}
        for field, bad in (('cloud', ''), ('cloud', 'azure'), ('isaac_workstation_ip', ''),
                           ('isaac_workstation_ip', 'not-an-ip'), ('ssh_key', ''), ('ssh_key', None)):
            with self.subTest(field=field, bad=bad), mock.patch('src.python.deployer.TerraformRunner') as factory:
                factory.return_value.recovery_directory = None
                values = dict(good, **{field: bad})
                factory.return_value.__enter__.return_value.output.return_value = {
                    k: {'value': v, 'type': 'string', 'sensitive': k == 'ssh_key'} for k, v in values.items()}
                self.deployer.tf_outputs = {'ssh_key': 'stale-key'}
                with self.assertRaisesRegex(click.ClickException, 'output'):
                    self.deployer.run_terraform(str(self.source))
                with mock.patch('src.python.deployer.read_tf_output') as legacy, \
                     mock.patch('src.python.deployer.Path.write_text') as write:
                    for action in (self.deployer.export_ssh_key, self.deployer.create_ansible_inventory):
                        with self.assertRaisesRegex(click.ClickException, 'output'):
                            action()
                    write.assert_not_called()
                    legacy.assert_not_called()
                self.assertFalse((self.inputs.parent / 'key.pem').exists())
                self.assertFalse((self.inputs.parent / '.inventory').exists())

    def test_mutating_public_apis_refuse_dry_run_before_runner_creation(self):
        self.deployer.params['dry_run'] = True
        with mock.patch('src.python.deployer.TerraformRunner') as factory:
            for action in (lambda: self.deployer.run_terraform(str(self.source)),
                           lambda: self.deployer.import_terraform_resource(str(self.source), 'terraform_data.item', 'fixture')):
                with self.subTest(action=action), self.assertRaisesRegex(click.ClickException, 'dry-run'):
                    action()
            factory.assert_not_called()

    def test_initialization_errors_are_sanitized_without_entering_context(self):
        from src.python.terraform_runner import TerraformRunnerError
        with mock.patch('src.python.deployer.TerraformRunner', side_effect=TerraformRunnerError('Missing private input')):
            with self.assertRaisesRegex(click.ClickException, 'Missing private input'):
                self.deployer.initialize_terraform(str(self.source))

    def test_retained_recovery_paths_remain_accessible_after_failure(self):
        from src.python.terraform_runner import TerraformRunnerError
        with mock.patch('src.python.deployer.TerraformRunner') as factory, mock.patch('click.echo') as echo:
            runner = factory.return_value
            runner.recovery_directory = self.root / 'private-recovery'
            runner.recovery_state = runner.recovery_directory / 'source' / 'errored.tfstate'
            runner.__enter__.return_value.apply.side_effect = TerraformRunnerError('Recovery required')
            with self.assertRaises(click.ClickException):
                self.deployer.run_terraform(str(self.source))
            self.assertEqual(self.deployer.terraform_recovery_directory, runner.recovery_directory)
            self.assertEqual(self.deployer.terraform_recovery_state, runner.recovery_state)
            self.assertIn(str(runner.recovery_directory), str(echo.call_args_list))

    def test_failures_close_context_and_surface_sanitized_click_errors(self):
        from src.python.terraform_runner import TerraformRunnerError
        for step in ('init', 'plan', 'apply'):
            with self.subTest(step=step), mock.patch('src.python.deployer.TerraformRunner') as factory:
                runner = factory.return_value
                active = runner.__enter__.return_value
                runner.recovery_directory = runner.recovery_state = None
                getattr(active, step).side_effect = TerraformRunnerError('Terraform command failed; diagnostics withheld')
                with self.assertRaisesRegex(click.ClickException, 'diagnostics withheld'):
                    self.deployer.run_terraform(str(self.source))
                runner.__exit__.assert_called_once()

    def test_preflight_rejects_missing_or_symlinked_allowlisted_source_without_staging(self):
        required = self.source / 'common' / 'main.tf'
        required.unlink()
        with mock.patch('src.python.deployer.TerraformRunner') as factory:
            with self.assertRaisesRegex(click.ClickException, 'source'):
                self.deployer.initialize_terraform(str(self.source))
            required.symlink_to(self.inputs)
            with self.assertRaisesRegex(click.ClickException, 'source'):
                self.deployer.initialize_terraform(str(self.source))
            factory.assert_not_called()

    def test_cwd_must_be_the_configured_cloud_source_root(self):
        unapproved = self.root / 'unreviewed' / 'aws'
        unapproved.mkdir(parents=True)
        with mock.patch('src.python.deployer.TerraformRunner') as factory:
            with self.assertRaisesRegex(click.ClickException, 'source root'):
                self.deployer.initialize_terraform(str(unapproved))
            factory.assert_not_called()

    def test_public_import_uses_its_own_initialized_context(self):
        self.deployer.params['cloud'] = 'aws'
        with mock.patch('src.python.deployer.TerraformRunner') as factory, \
             mock.patch('src.python.deployer.shell_command') as shell:
            factory.return_value.recovery_directory = None
            active = factory.return_value.__enter__.return_value
            self.deployer.import_terraform_resource(str(self.source), 'terraform_data.item', 'fixture-id')
            self.assertEqual(active.method_calls, [mock.call.init(),
                mock.call.import_resource('terraform_data.item', 'fixture-id', acknowledge_mutation=True)])
            factory.return_value.__exit__.assert_called_once()
            shell.assert_not_called()

    def test_public_apply_uses_one_private_context_with_saved_plan(self):
        with mock.patch('src.python.deployer.TerraformRunner', create=True) as factory, \
             mock.patch('src.python.deployer.shell_command') as shell:
            runner = factory.return_value
            runner.recovery_directory = None
            active = runner.__enter__.return_value
            snapshot = {
                'cloud': {'value': 'aws', 'type': 'string', 'sensitive': False},
                'isaac_workstation_ip': {'value': '192.0.2.10', 'type': 'string', 'sensitive': False},
                'ssh_key': {'value': 'synthetic-key', 'type': 'string', 'sensitive': True},
                'native': {'value': {'enabled': True, 'items': [1, 2]}, 'type': ['object', {}], 'sensitive': False},
            }
            active.output.return_value = snapshot
            self.deployer.initialize_terraform(str(self.source))
            runner.__enter__.assert_not_called()
            shell.assert_not_called()
            self.deployer.run_terraform(str(self.source))
            self.assertEqual(active.method_calls, [mock.call.init(), mock.call.plan(),
                             mock.call.apply(active.plan.return_value, acknowledge_mutation=True), mock.call.output()])
            with mock.patch('src.python.deployer.read_tf_output') as legacy:
                self.assertEqual(self.deployer.tf_output('native'), {'enabled': True, 'items': [1, 2]})
                self.assertEqual(self.deployer.tf_output('optional_absent', 'fallback'), 'fallback')
                self.deployer.export_ssh_key()
                self.assertEqual((self.inputs.parent / 'key.pem').read_text(), 'synthetic-key\n')
                legacy.assert_not_called()
            self.deployer.params['isaac_workstation_ip'] = 'stale-before-apply'
            template = mock.Mock()
            template.format.return_value = 'public inventory'
            with mock.patch('src.python.deployer.Path.read_text', return_value=template):
                self.deployer.create_ansible_inventory(write=False)
            self.assertEqual(template.format.call_args.kwargs['isaac_workstation_ip'], '192.0.2.10')
            runner.__enter__.assert_called_once()
            runner.__exit__.assert_called_once()
            shell.assert_not_called()
            kwargs = factory.call_args.kwargs
            self.assertEqual(kwargs['source_root'], self.source)
            self.assertIn('isaac-workstation/main.tf', kwargs['source_files'])
            self.assertNotIn('backend_override.tf.json', kwargs['source_files'])
            self.assertEqual(kwargs['variables_file'], self.inputs)
            self.assertEqual(kwargs['state_root'], self.inputs.parent.parent)
            self.assertIsNone(kwargs['target_scope'])
            self.assertEqual(kwargs['backend_spec'].backend, 'local')


class TestBackendSafety(unittest.TestCase):
    def test_explicit_inventory_hostname_is_supported_without_relaxing_output_ip_checks(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'aws', 'isaac_workstation_ip': 'localhost'})
            with mock.patch('pathlib.Path.read_text', return_value='{isaac_workstation_ip}'):
                self.assertEqual(deployer.create_ansible_inventory(write=False), 'localhost')
                deployer.params['isaac_workstation_ip'] = 'localhost\n[unsafe:vars]'
                with self.assertRaises(click.ClickException):
                    deployer.create_ansible_inventory(write=False)
                deployer.params['isaac_workstation_ip'] = 'localhost'
                deployer._terraform_outputs_ready = True
                deployer.tf_outputs['isaac_workstation_ip'] = 'localhost'
                with self.assertRaises(click.ClickException):
                    deployer.create_ansible_inventory(write=False)

    def test_gcs_requires_explicit_project_before_constructor_writes(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        with tempfile.TemporaryDirectory() as root:
            for project in (None, '', 'invalid-project!'):
                with self.subTest(project=project), mock.patch('src.python.deployer.os.makedirs') as mkdir:
                    with self.assertRaisesRegex(click.ClickException, 'explicit --project'):
                        _make_deployer(root, {'cloud': 'gcp', 'project': project, 'terraform_state': spec.to_dict()})
                    mkdir.assert_not_called()

    def test_active_gcs_replace_uses_saved_destroy_plan_but_dry_run_does_not_mutate(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project', 'existing': 'replace',
                                           'terraform_state': spec.to_dict()})
            deployer.params['backend_runtime'].update(status='active', lineage='known')
            deployer.save_meta()
            (Path(root) / 'test-1' / '.tfvars').write_text('project = "target-project"')
            with mock.patch('src.python.deployer.TerraformRunner') as factory, \
                 mock.patch('src.python.deployer.shell_command') as shell:
                factory.return_value.recovery_directory = None
                runner = factory.return_value.__enter__.return_value
                runner.pull_state.return_value = {'lineage': 'known', 'resources': [], 'outputs': {}}
                runner.assert_no_recovery = mock.Mock()
                deployer.ask_existing_behavior()
                shell.assert_not_called()
                runner.plan.assert_called_once_with(destroy=True)
                runner.apply.assert_called_once_with(runner.plan.return_value, acknowledge_mutation=True)
                runner.pull_state.assert_called_once()
                runner.assert_no_recovery.assert_called_once()
                self.assertEqual(factory.call_args.kwargs['state_root'], Path(root))
            deployer.params['dry_run'] = True
            with mock.patch('src.python.deployer.TerraformRunner') as factory, \
                 mock.patch('src.python.deployer.shell_command') as shell:
                deployer.ask_existing_behavior()
                factory.assert_not_called()
                shell.assert_not_called()

    def test_active_gcs_replace_regenerates_inputs_only_after_verified_destroy(self):
        from src.python.terraform_backend import BackendSpec
        from src.python.terraform_runner import TerraformRunnerError
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        for failure in (None, 'apply', 'lineage', 'resources', 'recovery', 'publish', 'dry_run'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                deployer = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project',
                    'existing': 'replace', 'prefix': 'old-prefix', 'terraform_state': spec.to_dict()})
                deployer.params['backend_runtime'].update(status='active', lineage='known')
                deployer.save_meta()
                directory = Path(root) / 'test-1'
                inputs = directory / '.tfvars'
                inputs.write_text('prefix = "old-prefix"\n')
                before_meta = (directory / 'meta.json').read_bytes()
                before_inputs = inputs.read_bytes()
                (directory / '.tfstate').write_text('SYNTHETIC RECOVERY SNAPSHOT')
                deployer.params.update(prefix='new-prefix', dry_run=failure == 'dry_run')
                with mock.patch('src.python.deployer.TerraformRunner') as factory, \
                        mock.patch('src.python.deployer.shell_command') as shell:
                    factory.return_value.recovery_directory = None
                    runner = factory.return_value.__enter__.return_value
                    runner.pull_state.return_value = {'lineage': 'other' if failure == 'lineage' else 'known',
                        'resources': [{'mode': 'managed', 'instances': [{}]}] if failure == 'resources' else []}
                    def apply(*args, **kwargs):
                        self.assertEqual(inputs.read_bytes(), before_inputs)
                        self.assertEqual((directory / 'meta.json').read_bytes(), before_meta)
                        if failure == 'apply':
                            raise TerraformRunnerError('Synthetic apply failure')
                    runner.apply.side_effect = apply
                    def clean():
                        self.assertEqual(inputs.read_bytes(), before_inputs)
                        if failure == 'recovery':
                            raise TerraformRunnerError('Synthetic recovery remains')
                    runner.attach_mock(mock.Mock(side_effect=clean), 'assert_no_recovery')
                    # Fail only publication, not fixture setup or the destroy operation.
                    with mock.patch.object(deployer, 'save_meta', wraps=deployer.save_meta,
                            side_effect=click.ClickException('Synthetic publication failure') if failure == 'publish' else None):
                        if failure not in (None, 'dry_run'):
                            with self.assertRaises(click.ClickException):
                                deployer.ask_existing_behavior()
                        else:
                            deployer.ask_existing_behavior()
                    deployer.create_tfvars()
                    shell.assert_not_called()
                    if failure is None:
                        self.assertIn('prefix = "new-prefix"', inputs.read_text())
                        self.assertEqual(runner.method_calls, [mock.call.init(), mock.call.plan(destroy=True),
                            mock.call.apply(runner.plan.return_value, acknowledge_mutation=True),
                            mock.call.pull_state(), mock.call.assert_no_recovery()])
                        saved = json.loads((directory / 'meta.json').read_text())['params']
                        self.assertEqual(saved['prefix'], 'new-prefix')
                        self.assertEqual(saved['backend_runtime'], deployer.params['backend_runtime'])
                        self.assertEqual(saved['terraform_state'], spec.to_dict())
                    else:
                        self.assertEqual(inputs.read_bytes(), before_inputs)
                        self.assertEqual((directory / 'meta.json').read_bytes(), before_meta)
                    if failure == 'publish':
                        runner.retain_recovery.assert_called_once()
                    if failure == 'dry_run':
                        factory.assert_not_called()
                    self.assertEqual((directory / '.tfstate').read_text(), 'SYNTHETIC RECOVERY SNAPSHOT')

    def test_new_gcs_replace_does_not_destroy_the_just_saved_configuration(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project', 'existing': 'replace',
                                           'terraform_state': spec.to_dict()})
            with mock.patch('src.python.deployer.shell_command') as shell:
                deployer.ask_existing_behavior()
                shell.assert_not_called()
            self.assertEqual(deployer.existing_behavior, 'replace')

    def test_metadata_publication_is_private_atomic_and_preserves_old_receipt_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'aws'})
            deployer.save_meta()
            path = Path(root) / 'test-1' / 'meta.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            before = path.read_bytes()
            deployer.params['prefix'] = 'changed'
            with mock.patch('src.python.backend_runtime.os.replace', side_effect=OSError('synthetic rename failure')):
                with self.assertRaises(click.ClickException):
                    deployer.save_meta()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual([p.name for p in path.parent.iterdir()], ['meta.json'])

    def test_key_export_checks_authoritative_oslogin_with_stale_saved_settings(self):
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        for saved in (False, None):
            for authoritative in (True, 'true'):
                with self.subTest(saved=saved, authoritative=authoritative), tempfile.TemporaryDirectory() as root:
                    deployer = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project',
                        'zone': 'us-central1-a', 'enable_oslogin': False, 'terraform_state': spec.to_dict()})
                    if saved is None:
                        deployer.params.pop('enable_oslogin')
                    deployer.params['backend_runtime'].update(status='active', lineage='known')
                    deployer.save_meta()
                    key = Path(root) / 'test-1/key.pem'
                    key.write_text('SYNTHETIC EXISTING KEY\n')
                    key.chmod(0o600)
                    outputs = {'cloud': 'gcp', 'iap_enabled': False, 'oslogin_enabled': authoritative,
                        'isaac_workstation_ip': '192.0.2.10', 'isaac_workstation_private_ip': '10.0.0.2',
                        'isaac_workstation_vm_id': 'projects/target-project/zones/us-central1-a/instances/fixture',
                        'ssh_key': 'OS_LOGIN_ACTIVE'}
                    with mock.patch('src.python.deployer.read_tf_output',
                            side_effect=lambda deployment, name, **kw: outputs[name]), \
                            mock.patch('src.python.file_transfer.subprocess.run') as discover:
                        with self.assertRaisesRegex(click.ClickException, 'security output'):
                            deployer.export_ssh_key()
                        discover.assert_not_called()
                    self.assertEqual(key.read_text(), 'SYNTHETIC EXISTING KEY\n')
                    self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_key_export_refuses_oslogin_sentinel_even_with_false_output(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'gcp', 'enable_oslogin': False})
            directory = Path(root) / 'test-1'
            directory.mkdir()
            key = directory / 'key.pem'
            key.write_text('SYNTHETIC EXISTING KEY\n')
            deployer._terraform_outputs_ready = True
            deployer.tf_outputs = {'cloud': 'gcp', 'iap_enabled': False, 'oslogin_enabled': False,
                                   'ssh_key': '  OS_LOGIN_ACTIVE\n'}
            with self.assertRaisesRegex(click.ClickException, 'SSH key'):
                deployer.export_ssh_key()
            self.assertEqual(key.read_text(), 'SYNTHETIC EXISTING KEY\n')

    def test_iap_inventory_uses_private_ip_and_verified_endpoint_options(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project', 'zone': 'us-central1-a',
                                           'enable_iap_only': True, 'enable_oslogin': False})
            directory = Path(root) / 'test-1'
            directory.mkdir()
            (directory / '.tfvars').write_text('project = "target-project"')
            values = {'cloud': 'gcp', 'ssh_key': 'synthetic-key', 'iap_enabled': True,
                      'oslogin_enabled': False, 'isaac_workstation_ip': 'NONE (IAP ONLY)',
                      'isaac_workstation_private_ip': '10.0.0.2',
                      'isaac_workstation_vm_id': 'projects/target-project/zones/us-central1-a/instances/fixture'}
            with mock.patch('src.python.deployer.TerraformRunner') as factory:
                factory.return_value.recovery_directory = None
                runner = factory.return_value.__enter__.return_value
                runner.output.return_value = {k: {'value': v, 'type': 'bool' if type(v) is bool else 'string',
                                                   'sensitive': k == 'ssh_key'} for k, v in values.items()}
                deployer.run_terraform(f"{c['terraform_dir']}/gcp")
            with mock.patch('src.python.deployer.Path.read_text', return_value='[isaac_workstation]\n{isaac_workstation_ip}\n'):
                inventory = deployer.create_ansible_inventory(write=False)
            self.assertIn('10.0.0.2', inventory)
            self.assertIn('start-iap-tunnel fixture 22 --listen-on-stdin', inventory)
            self.assertIn('--project=target-project', inventory)
            self.assertIn('--zone=us-central1-a', inventory)
            self.assertIn('StrictHostKeyChecking=accept-new', inventory)
            self.assertIn('ansible_ssh_host_key_checking=True', inventory)
            self.assertNotIn('NONE (IAP ONLY)', inventory)
            deployer.export_ssh_key()
            self.assertEqual((directory / 'key.pem').read_text(), 'synthetic-key\n')
            deployer.params['enable_oslogin'] = True
            deployer.tf_outputs.update(oslogin_enabled=True, ssh_key='OS_LOGIN_ACTIVE')
            identity = directory / 'oslogin key'
            identity.write_text('synthetic-oslogin-identity')
            with mock.patch('src.python.file_transfer.subprocess.run', return_value=mock.Mock(
                    stdout=f"ssh -i {__import__('shlex').quote(str(identity))} actual_user@fixture")) as discover:
                deployer.export_ssh_key()
                with mock.patch('src.python.deployer.Path.read_text', return_value='[isaac_workstation]\n{isaac_workstation_ip}\n'):
                    inventory = deployer.create_ansible_inventory(write=False)
                self.assertIn('ansible_user=actual_user', inventory)
                self.assertIn(f'ansible_ssh_private_key_file={identity}', inventory)
                self.assertTrue(discover.called)
            self.assertEqual((directory / 'key.pem').read_text(), 'synthetic-key\n', 'OS Login sentinel must never replace a PEM')

    def test_gcs_deploy_persists_exact_destination_and_applied_lineage(self):
        from src.python.terraform_backend import BackendSpec
        from src.python.backend_runtime import load_backend_record
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project',
                                           'terraform_state': spec.to_dict()})
            deployer.save_meta()
            self.assertEqual(load_backend_record('test-1', state_root=root).status, 'configured')
            directory = Path(root) / 'test-1'
            (directory / '.tfvars').write_text('project = "target-project"')
            objects = set()
            output = {key: {'value': value, 'type': 'string', 'sensitive': key == 'ssh_key'} for key, value in {
                'ssh_key': 'synthetic-key', 'isaac_workstation_ip': '192.0.2.10', 'cloud': 'gcp'}.items()}
            state = {'version': 4, 'serial': 1, 'lineage': 'synthetic-lineage', 'resources': [], 'outputs': output}
            commands = []
            def execute(argv, **kwargs):
                commands.append(argv[1])
                if argv[1] == 'version':
                    raw, code = b'{"terraform_version":"1.10.0"}', 0
                elif argv[1] == 'init':
                    data_dir = Path(kwargs['env']['TF_DATA_DIR'])
                    (data_dir / 'terraform.tfstate').write_text(json.dumps({'backend': {
                        'type': 'gcs', 'config': spec.backend_config('target-project', 'test-1')}}))
                    objects.add(spec.identity('target-project', 'test-1')['object_key'])
                    raw, code = b'{}', 0
                elif argv[1] == 'plan':
                    Path(next(a[5:] for a in argv if a.startswith('-out='))).write_bytes(b'exact-gcs-plan')
                    raw, code = b'', 2
                elif argv[1] == 'apply':
                    self.assertEqual(Path(argv[-1]).read_bytes(), b'exact-gcs-plan')
                    self.assertIn('-lock-timeout=120s', argv)
                    objects.add(spec.identity('target-project', 'test-1')['object_key'])
                    raw, code = b'', 0
                else:
                    observed = state if 'apply' in commands else dict(state, serial=0, resources=[], outputs={})
                    raw, code = json.dumps(observed if argv[1] == 'state' else output).encode(), 0
                proc = mock.Mock(returncode=code)
                proc.communicate.return_value = raw, b''
                return proc
            with mock.patch('src.python.backend_runtime.gcs_object_names', side_effect=lambda *args: set(objects)), \
                 mock.patch('src.python.terraform_runner.subprocess.Popen', side_effect=execute):
                deployer.plan_terraform(f"{c['terraform_dir']}/gcp")
                deployer.save_meta()
                self.assertEqual(load_backend_record('test-1', state_root=root).lineage, 'synthetic-lineage')
                deployer.run_terraform(f"{c['terraform_dir']}/gcp")
            record = load_backend_record('test-1', state_root=root)
            self.assertEqual(record.status, 'active')
            self.assertEqual(record.lineage, 'synthetic-lineage')
            self.assertEqual(record.identity, spec.identity('target-project', 'test-1'))
            self.assertEqual(deployer.tf_outputs['isaac_workstation_ip'], '192.0.2.10')
            self.assertEqual(commands.count('apply'), 1)
            self.assertFalse((directory / '.tfstate').exists())
            with mock.patch('src.python.deployer.TerraformRunner') as factory, \
                 mock.patch.object(deployer, 'save_meta', side_effect=OSError('synthetic publication failure')):
                factory.return_value.recovery_directory = None
                runner = factory.return_value.__enter__.return_value
                runner.backend_identity = json.dumps(record.identity)
                runner.pull_state.return_value = state
                with self.assertRaises(click.ClickException):
                    deployer.run_terraform(f"{c['terraform_dir']}/gcp")
                runner.retain_recovery.assert_called_once()
                self.assertEqual(factory.call_args.kwargs['staging_root'], Path(root) / '.terraform-operations')
            # Fresh constructor uses saved destination, never a new local default.
            fresh = _make_deployer(root, {'cloud': 'gcp', 'project': 'target-project'})
            self.assertEqual(fresh.params['terraform_state'], spec.to_dict())
            with self.assertRaises(click.ClickException):
                _make_deployer(root, {'cloud': 'gcp', 'state_backend': 'local', 'project': 'target-project'})

    def test_saved_profile_intent_is_not_bypassed_by_stale_flat_params(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'test-1'
            directory.mkdir()
            for profile in ({'terraform_state': {'backend': 'gcs'}},
                            {'state_bucket': 'auto'},
                            {'raw': {'terraform_state': {'backend': 'gcs'}}},
                            {'raw': {'security': {'storage': {'state_backend': 'gcs'}}}}):
                path = directory / 'meta.json'
                path.write_text(json.dumps({'params': {'state_backend': 'local', 'profile_spec': profile}}))
                with self.subTest(profile=profile), self.assertRaises(click.ClickException):
                    _make_deployer(root, {'cloud': 'aws', 'state_backend': 'local'})

    def test_new_explicit_local_discards_profile_destination_and_survives_save(self):
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root) / 'profile.yaml'
            profile.write_text('terraform_state:\n  backend: gcs\n  namespace: studio\n  destination:\n    bucket: example-state\n    project: example-project\n    prefix: isaacautomator/v2\n')
            deployer = _make_deployer(root, {'cloud': 'aws', 'profile': str(profile), 'state_backend': 'local'})
            deployer.save_meta()
            text = (Path(root) / 'test-1' / 'meta.json').read_text()
            self.assertNotIn('example-state', text)
            deployer.require_local_backend()

    def test_restore_uses_own_state_directory(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'aws', 'existing': 'repair'})
            deployer.save_meta()
            deployer.params['prefix'] = 'changed'
            with mock.patch.dict(c, state_dir=str(Path(root) / 'unrelated-controller')):
                deployer.ask_existing_behavior()
            self.assertEqual(deployer.params['prefix'], 'isa')

    def test_backend_inputs_are_controller_only_and_local_config_remains_usable(self):
        with tempfile.TemporaryDirectory() as root:
            config_file = Path(root) / 'private-sentinel.yaml'
            config_file.write_text('backend: local')
            deployer = _make_deployer(root, {'cloud': 'aws', 'backend_config': str(config_file)})
            self.assertNotIn('private-sentinel', deployer.recreate_command_line())
            deployer.save_meta()
            deployer.require_local_backend()
            meta = json.loads((Path(root) / 'test-1' / 'meta.json').read_text())
            self.assertEqual(meta['params']['terraform_state']['backend'], 'local')
            self.assertNotIn('private-sentinel', json.dumps(meta))
            fields = {'terraform_state', 'state_backend', 'state_bucket', 'backend_config', 'profile_spec'}
            target = Path(root) / 'variables'
            deployer._write_tfvars_file(str(target), dict(deployer.params, prefix='public'))
            for key in fields:
                self.assertNotIn(key, target.read_text())
            template = mock.Mock()
            template.format.return_value = 'public inventory'
            deployer.params['isaac_workstation_ip'] = '192.0.2.1'
            # Only template read is substituted; backend checks remain real.
            original = Path.read_text
            def read(path, *args, **kwargs):
                if str(path).endswith('inventory.template'):
                    return template
                return original(path, *args, **kwargs)
            with mock.patch.object(Path, 'read_text', read):
                deployer.create_ansible_inventory(write=False)
            self.assertFalse(fields.intersection(template.format.call_args.kwargs))

    def test_saved_descriptor_refuses_even_explicit_local_without_rewriting(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'test-1'
            directory.mkdir()
            descriptor = directory / 'backend.json'
            descriptor.write_text('{"backend":"gcs","private":"private-sentinel"}')
            before = descriptor.read_bytes()
            with mock.patch('src.python.deployer.os.makedirs') as mkdir:
                with self.assertRaisesRegex(click.ClickException, 'migration') as caught:
                    _make_deployer(root, {'state_backend': 'local', 'cloud': 'aws'})
            self.assertNotIn('private-sentinel', str(caught.exception))
            mkdir.assert_not_called()
            self.assertEqual(descriptor.read_bytes(), before)
            self.assertFalse((directory / 'meta.json').exists())

    def test_saved_remote_metadata_cannot_be_masked_by_current_local(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'test-1'
            directory.mkdir()
            meta = directory / 'meta.json'
            for section in ('params', 'input_params'):
                for intent in ({'state_bucket': 'auto'}, {'terraform_state': {'backend': 'gcs'}},
                               {'state_backend': 's3'}, {'backend_config': 'unknown-location'}):
                    meta.write_text(json.dumps({section: dict(intent, cloud='gcp')}))
                    before = meta.read_bytes()
                    with self.subTest(section=section, intent=intent), mock.patch('src.python.deployer.os.makedirs') as mkdir:
                        with self.assertRaises(click.ClickException):
                            _make_deployer(root, {'state_backend': 'local', 'cloud': 'aws'})
                        mkdir.assert_not_called()
                        self.assertEqual(meta.read_bytes(), before)

    def test_restore_and_late_mutation_recheck_before_save_vars_or_shell(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'aws', 'existing': 'repair'})
            hostile = dict(deployer.params, cloud='gcp', terraform_state={'backend': 'gcs'})
            with mock.patch.object(deployer, 'read_meta', return_value={'params': hostile}), \
                 mock.patch.object(deployer, 'save_meta') as save:
                with self.assertRaises(click.ClickException):
                    deployer.ask_existing_behavior()
                save.assert_not_called()
                self.assertEqual(deployer.cloud, 'aws')
                self.assertEqual(deployer.params['cloud'], 'aws')
            deployer._persistence_ready = True
            deployer.params['terraform_state'] = {'backend': 'gcs'}
            with mock.patch('src.python.deployer.get_my_public_ip') as ip, \
                 mock.patch('src.python.deployer.shell_command') as shell, \
                 mock.patch('src.python.deployer.read_tf_output', return_value='public') as output, \
                 mock.patch('src.python.deployer.Path.write_text') as write:
                for action in (deployer.save_meta, deployer.create_tfvars,
                               deployer.create_ansible_inventory,
                               lambda: deployer.initialize_terraform(root),
                               lambda: deployer.run_terraform(root), lambda: deployer.plan_terraform(root),
                               lambda: deployer.import_terraform_resource(root, 'terraform_data.item', 'fixture'),
                               lambda: deployer.tf_output('cloud'),
                               deployer.validate_ansible, deployer.export_ssh_key, deployer.upload_user_data,
                               lambda: deployer.run_ansible('public', root),
                               lambda: deployer._write_tfvars_file(str(Path(root) / 'vars'), {})):
                    with self.subTest(action=action), self.assertRaises(click.ClickException):
                        action()
                ip.assert_not_called()
                shell.assert_not_called()
                output.assert_not_called()
                write.assert_not_called()

    def test_remote_intent_refused_before_constructor_writes(self):
        with tempfile.TemporaryDirectory() as root:
            for cloud, backend in (('aws', 's3'), ('gcp', 'gcs'), ('azure', 'azurerm'), ('alicloud', 'gcs')):
                for intent in ({'state_backend': backend}, {'state_bucket': 'auto'},
                               {'terraform_state': {'backend': backend}}):
                    with self.subTest(cloud=cloud, intent=intent), \
                         mock.patch('src.python.deployer.os.makedirs') as mkdir, \
                         mock.patch('src.python.deployer.shell_command') as shell:
                        with self.assertRaisesRegex(click.ClickException, 'not implemented'):
                            _make_deployer(root, dict(intent, cloud=cloud, dry_run=True))
                        mkdir.assert_not_called()
                        shell.assert_not_called()

    def test_late_remote_dryrun_never_rewrites_backend_as_local(self):
        with tempfile.TemporaryDirectory() as root:
            deployer = _make_deployer(root, {'cloud': 'aws', 'dry_run': True})
            deployer.params['state_bucket'] = 'example-state'
            tf = Path(root) / 'terraform'
            tf.mkdir()
            override = tf / 'backend_override.tf.json'
            override.write_text('preserve')
            with mock.patch('src.python.deployer.shell_command') as shell:
                with self.assertRaisesRegex(click.ClickException, 'not implemented'):
                    deployer.initialize_terraform(str(tf))
            shell.assert_not_called()
            self.assertEqual(override.read_text(), 'preserve')


if __name__ == "__main__":
    unittest.main()

