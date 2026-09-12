#!/usr/bin/env python3
"""Synthetic image safety contracts; never authenticate or invoke cloud/Packer."""
import contextlib
import importlib.util
import io
import json
import os
import runpy
import shlex
import subprocess
import sys
import tempfile
import unittest
import click
from click.testing import CliRunner
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.python.config import c as config

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = {"gcp": "build_gcp_image", "aws": "build_ami", "azure": "build_azure_image"}
PASSWORD = "synthetic-password-'\"-$()\\\n-not-a-real-secret"


class TestWorkstationImageContract(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "VERSION": "synthetic-version", "HOME": self.tmp,
        }, clear=True))
        self.stack.enter_context(mock.patch.dict(config, state_dir=self.tmp))
        self.process = self.stack.enter_context(mock.patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")))
        self.stack.enter_context(mock.patch(
            "src.python.deploy_command.get_my_public_ip", return_value="192.0.2.1"))
        self.stack.enter_context(mock.patch(
            "src.python.utils.shell_command", return_value=SimpleNamespace(returncode=0, stdout=b"")))
        self.modules = {}
        for provider in PROVIDERS:
            loader = SourceFileLoader(f"image_contract_{provider}", str(ROOT / f"image-{provider}"))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            assert spec is not None
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            self.modules[provider] = module
        self.process.reset_mock()

    def params(self, **changes):
        return {
            "debug": True, "dry_run": False, "project": "fixture-project",
            "zone": "us-central1-a", "region": "fixture-region",
            "isaac_workstation_instance_type": "fixture-instance", "gpu_type": "nvidia-l4",
            "gpu_count": 1, "isaacsim": "v6.0.0", "isaaclab": "no",
            "isaaclab_arena": "no", "demos": "no", "install_gr00t": False,
            "enable_neo4j": True, "system_user_password": PASSWORD,
            "image_name": "Fixture_1.0", "existing": "overwrite",
            "resource_group": "fixture-group", "login": True, **changes,
        }

    @contextlib.contextmanager
    def effects(self, module):
        with contextlib.ExitStack() as stack:
            mocks = {}
            values = {
                "gcp_login": None, "delete_gcp_image": None,
                "aws_image_credentials": {},
                "azure_login": None, "azure_get_subscription_id": "fixture-subscription",
                "azure_ensure_resource_group": None, "delete_managed_image": None,
                "shell_command": SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            }
            for name, value in values.items():
                if hasattr(module, name):
                    mocks[name] = stack.enter_context(mock.patch.object(module, name, return_value=value))
            yield mocks

    def build(self, provider, params):
        return getattr(self.modules[provider], PROVIDERS[provider])(params, {
            "app_dir": self.tmp, "ansible_dir": str(Path(self.tmp) / "ansible"),
        })

    def test_gcp_preview_default_does_not_inspect_cloud_configuration(self):
        module = self.modules["gcp"]
        option = next(param for param in module.main.params if param.name == "project")
        with click.Context(module.main) as ctx, self.effects(module) as effects:
            ctx.params["dry_run"] = True
            self.assertEqual(option.get_default(ctx), "")
            effects["shell_command"].assert_not_called()
            ctx.params["dry_run"] = False
            effects["shell_command"].return_value.stdout = b"fixture-project\n"
            self.assertEqual(option.get_default(ctx), "fixture-project")
            effects["shell_command"].assert_called_once()

    def test_version_required_for_build_before_auth_or_commands(self):
        for version in (None, ""):
            with mock.patch.dict(os.environ):
                if version is None:
                    os.environ.pop("VERSION", None)
                else:
                    os.environ["VERSION"] = version
                for provider, module in self.modules.items():
                    with self.subTest(provider=provider, version=version), self.effects(module) as effects, \
                         contextlib.redirect_stdout(io.StringIO()) as output:
                        with self.assertRaises(SystemExit) as stopped:
                            self.build(provider, self.params(dry_run=False))
                        self.assertEqual(stopped.exception.code, 1)
                        self.assertIn("VERSION", output.getvalue())
                        for effect in effects.values():
                            effect.assert_not_called()
        self.process.assert_not_called()

    def test_non_overwrite_build_preserves_defaults_and_no_login_choice(self):
        for provider, module in self.modules.items():
            with self.subTest(provider=provider), self.effects(module) as effects:
                captured = []
                def execute(argv, **kwargs):
                    if argv[1] == "build":
                        self.assertNotIn("-force", argv)
                        path = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("-var-file=")))
                        captured.append(json.loads(path.read_text()))
                    return subprocess.CompletedProcess(argv, 0, "", "")
                self.process.side_effect = execute
                params = self.params(existing="fail", image_name="", login=False, debug=False)
                for key in ("install_gr00t", "enable_neo4j", "demos"):
                    params.pop(key)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.build(provider, params)
                self.assertEqual(len(captured), 1)
                self.assertNotIn("image_name", captured[0])
                self.assertNotIn("install_gr00t", captured[0])
                self.assertNotIn("enable_neo4j", captured[0])
                self.assertEqual(captured[0]["demos"], "no")
                for name in ("delete_gcp_image", "delete_managed_image", "azure_login"):
                    if name in effects:
                        effects[name].assert_not_called()

    def test_entrypoint_help_never_authenticates_or_runs_commands(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider), self.effects(self.modules[provider]), \
                 mock.patch("src.python.aws.aws_validate_credentials") as auth, \
                 mock.patch("src.python.utils.shell_command") as shell, \
                 mock.patch.object(sys, "argv", [f"image-{provider}", "--help"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(str(ROOT / f"image-{provider}"), run_name="__main__")
                self.assertEqual(stopped.exception.code, 0)
                auth.assert_not_called()
                shell.assert_not_called()

    def test_host_build_transports_argv_privately_and_cleans_up(self):
        real_exists = os.path.exists
        for provider in PROVIDERS:
            for failure in (None, "nonzero", "oserror", "interrupt"):
                args = ["--image-name", "fixture space", "--debug", "--system-user-password=" + PASSWORD]
                files = []
                def execute(argv, **kwargs):
                    self.assertIsInstance(argv, list)
                    self.assertFalse(kwargs.get("shell", False))
                    self.assertNotIn("synthetic-password", repr(argv))
                    inner = shlex.split(argv[1])
                    self.assertEqual(inner[:3], ["python3", "-m", "src.python.image_command_utils"])
                    path = ROOT / Path(inner[-1]).relative_to("/app")
                    files.append(path)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(json.loads(path.read_text()), [f"image-{provider}", *args])
                    # Exercise the container-side reader; only replace its final script dispatch.
                    from src.python.image_command_utils import invoke_image_file
                    def dispatch(script, run_name):
                        self.assertEqual(Path(script).name, f"image-{provider}")
                        self.assertEqual(sys.argv[1:], args)
                    with mock.patch("runpy.run_path", side_effect=dispatch):
                        invoke_image_file(path)
                    if failure == "oserror":
                        raise OSError(PASSWORD)
                    if failure == "interrupt":
                        raise KeyboardInterrupt()
                    return subprocess.CompletedProcess(argv, 19 if failure else 0)
                with self.subTest(provider=provider, failure=failure), \
                     mock.patch("os.path.exists", side_effect=lambda path: False if path == "/.dockerenv" else real_exists(path)), \
                     mock.patch("src.python.utils.shell_command") as shell, \
                     mock.patch.object(sys, "argv", [f"image-{provider}", *args]), \
                     contextlib.redirect_stdout(io.StringIO()) as output, \
                     contextlib.redirect_stderr(output):
                    self.process.reset_mock()
                    self.process.side_effect = execute
                    try:
                        runpy.run_path(str(ROOT / f"image-{provider}"), run_name="__main__")
                    except (SystemExit, click.ClickException, KeyboardInterrupt) as stopped:
                        if isinstance(stopped, SystemExit):
                            self.assertEqual(stopped.code, 19 if failure == "nonzero" else (1 if failure == "oserror" else 0))
                        self.assertNotIn("synthetic-password", str(stopped))
                    shell.assert_not_called()
                    self.process.assert_called_once()
                    self.assertEqual(len(files), 1)
                    self.assertFalse(files[0].parent.exists())
                    self.assertNotIn("synthetic-password", output.getvalue())

    def test_host_preview_and_help_are_local_before_container_forwarding(self):
        real_exists = os.path.exists
        for provider in PROVIDERS:
            for flags in (["--help"], ["--isaacsim", "latest", "--dry-run"]):
                args = [f"image-{provider}", *flags, "--system-user-password", PASSWORD]
                if "--dry-run" in flags:
                    args += ["--image-name", "fixture"]
                    if provider == "gcp":
                        args += ["--project", "fixture-project"]
                with self.subTest(provider=provider, flags=flags), \
                     mock.patch("os.path.exists", side_effect=lambda path: False if path == "/.dockerenv" else real_exists(path)), \
                     mock.patch("src.python.utils.shell_command") as shell, \
                     mock.patch.object(sys, "argv", args), \
                     mock.patch.object(sys, "stdin", io.StringIO("\n" * 20)), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    self.process.reset_mock()
                    try:
                        runpy.run_path(str(ROOT / f"image-{provider}"), run_name="__main__")
                    except SystemExit as stopped:
                        self.assertEqual(stopped.code, 0)
                    shell.assert_not_called()
                    self.process.assert_not_called()
                    self.assertIn("rendering-only", output.getvalue())
                    self.assertNotIn("synthetic-password", output.getvalue())

    def test_preview_skips_remote_defaults_and_explicit_refs_in_any_order(self):
        for provider, module in self.modules.items():
            for refs in ([], ["--isaacsim", "latest", "--isaaclab", "release/fixture",
                              "--isaaclab-arena", "v1.2.3"]):
                for first in (True, False):
                    with self.subTest(provider=provider, refs=refs, first=first), self.effects(module) as effects:
                        args = ["--image-name", "fixture", *refs]
                        if provider == "gcp":
                            args += ["--project", "fixture-project"]
                        args = (["--dry-run"] + args) if first else (args + ["--dry-run"])
                        self.process.reset_mock()
                        self.process.return_value = subprocess.CompletedProcess([], 0, "abc\trefs/tags/v1.2.3\n", "")
                        result = CliRunner().invoke(module.main, args, input="\n" * 20)
                        self.assertEqual(result.exit_code, 0, result.output)
                        self.assertIn("rendering-only", result.output)
                        self.process.assert_not_called()
                        for effect in effects.values():
                            effect.assert_not_called()
                        self.assertIn('"isaacsim": "latest"', result.output)

    def test_click_preview_uses_parsed_flag_and_honest_help(self):
        common = ["Fixture_1.0", "--debug", "--dry-run", "--existing", "overwrite",
                  "--isaacsim", "no", "--isaaclab", "no", "--isaaclab-arena", "no",
                  "--demos", "no"]
        options = {
            "gcp": ["--project", "fixture-project", "--zone", "us-central1-a", "--instance-type", "g2-standard-8"],
            "aws": ["--region", "us-east-1", "--instance-type", "g6e.2xlarge"],
            "azure": ["--region", "westus3", "--instance-type", "Standard_NV36ads_A10_v5"],
        }
        for provider, module in self.modules.items():
            with self.subTest(provider=provider), self.effects(module) as effects:
                result = CliRunner().invoke(module.main, common + options[provider], input="\n" * 10)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("rendering-only", result.output)
                for effect in effects.values():
                    effect.assert_not_called()
                help_text = CliRunner().invoke(module.main, ["--help"]).output
                self.assertIn("rendering-only", help_text)
                self.assertNotIn("Validate Terraform", help_text)

    def test_preview_is_rendering_only_without_auth_or_commands(self):
        for provider, module in self.modules.items():
            with self.subTest(provider=provider), self.effects(module) as effects:
                output = io.StringIO()
                before = dict(os.environ)
                with contextlib.redirect_stdout(output):
                    result = self.build(provider, self.params(dry_run=True))
                for effect in effects.values():
                    effect.assert_not_called()
                self.process.assert_not_called()
                self.assertEqual(dict(os.environ), before)
                self.assertEqual(list(Path(self.tmp).iterdir()), [])
                self.assertEqual(result["status"], "rendering-only")
                self.assertIn("rendering-only", output.getvalue())
                self.assertIn("not validated", output.getvalue())
                self.assertNotIn("fully valid", output.getvalue())
                self.assertNotIn(PASSWORD, output.getvalue())
                self.assertNotIn(PASSWORD, repr(result))

    def test_aws_auth_failure_is_actionable_redacted_and_stops_before_packer(self):
        import src.python.aws as aws
        failures = [OSError(PASSWORD), subprocess.CompletedProcess([], 1, PASSWORD, PASSWORD)]
        failures += [subprocess.CompletedProcess([], 0, body, "") for body in
                     (PASSWORD, "{}", "null", "[]", json.dumps({"AccessKeyId": 123, "SecretAccessKey": PASSWORD}))]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                 mock.patch.object(aws, "shell_command") as shell, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.process.reset_mock()
                self.process.side_effect = failure if isinstance(failure, Exception) else None
                self.process.return_value = failure
                with self.assertRaises(click.ClickException) as stopped:
                    self.build("aws", self.params())
                self.assertIn("AWS CLI", str(stopped.exception))
                self.assertIn("sso login", str(stopped.exception))
                self.assertNotIn("synthetic-password", str(stopped.exception) + output.getvalue())
                self.process.assert_called_once()
                shell.assert_not_called()
                self.assertEqual(list(Path(self.tmp).iterdir()), [])

    def test_aws_template_marks_credentials_sensitive(self):
        import re
        template = (ROOT / "src/packer/aws/isaac-workstation.pkr.hcl").read_text()
        for name in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
            block = re.search(r'variable "' + name + r'"\s*\{(.*?)\n\}', template, re.S).group(1)
            self.assertRegex(block, r"sensitive\s*=\s*true")

    def test_aws_image_resolves_credentials_without_config_writes_or_secret_commands(self):
        import src.python.aws as aws
        exported = {"AccessKeyId": "synthetic-access", "SecretAccessKey": "synthetic-cloud-secret",
                    "SessionToken": "synthetic-session-token"}
        sentinel = Path(self.tmp) / "credentials"
        sentinel.write_text("synthetic-existing-credentials")
        calls = []
        def shell_execute(command, **kwargs):
            calls.append(command)
            if "export-credentials" in command:
                text = json.dumps(exported)
            elif "configure get" in command:
                text = {"aws_access_key_id": exported["AccessKeyId"],
                        "aws_secret_access_key": exported["SecretAccessKey"],
                        "aws_session_token": exported["SessionToken"]}.get(command.split()[3], "us-east-1")
            else:
                text = "{}"
            return subprocess.CompletedProcess(command, 0, text.encode(), b"")
        def execute(argv, **kwargs):
            calls.append(argv)
            if argv[0] == "aws":
                self.assertEqual(argv, ["aws", "configure", "export-credentials", "--format", "process"])
                return subprocess.CompletedProcess(argv, 0, json.dumps(exported), "")
            if argv[1] == "build":
                self.assertEqual(kwargs["env"]["AWS_SECRET_ACCESS_KEY"], exported["SecretAccessKey"])
            return subprocess.CompletedProcess(argv, 0, "", "")
        self.process.side_effect = execute
        before = dict(os.environ)
        with mock.patch.object(aws, "AWS_STATE_DIR", self.tmp), \
             mock.patch.object(aws, "shell_command", side_effect=shell_execute) as shell, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.build("aws", self.params())
            self.assertFalse(any("configure set" in str(call) for call in calls), calls)
            shell.assert_not_called()
            self.assertEqual(sentinel.read_text(), "synthetic-existing-credentials")
            self.assertNotIn("synthetic-cloud-secret", str(calls) + output.getvalue())
        self.assertEqual(dict(os.environ), before)

    def test_template_extra_vars_reach_real_ansible_parser_without_secret_argv(self):
        import re
        from ansible import context
        from ansible.module_utils.common.collections import ImmutableDict
        from ansible.parsing.dataloader import DataLoader
        from ansible.utils.vars import load_extra_vars
        for provider, module in self.modules.items():
            files = []
            template = (ROOT / "src/packer" / provider / "isaac-workstation.pkr.hcl").read_text()
            # These templates use a literal list of strings; decode that actual
            # provisioner boundary and substitute only its var references.
            arguments = json.loads(re.search(r"extra_arguments\s*=\s*(\[.*?\])", template, re.S).group(1))
            def execute(argv, **kwargs):
                if argv[1] == "build":
                    varfile = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("-var-file=")))
                    variables = {"skip_tags": "skip_in_image", "vnc_password": "", **json.loads(varfile.read_text())}
                    rendered = [re.sub(r"\$\{var\.([a-z_0-9]+)\}", lambda m: str(variables[m[1]]).lower()
                                       if isinstance(variables[m[1]], bool) else str(variables[m[1]]), arg)
                                for arg in arguments]
                    extra = tuple(rendered[i + 1] for i, arg in enumerate(rendered) if arg == "--extra-vars")
                    with mock.patch.object(context, "CLIARGS", ImmutableDict(extra_vars=extra)), \
                         mock.patch.object(load_extra_vars, "extra_vars", None, create=True):
                        parsed = load_extra_vars(DataLoader())
                    self.assertEqual(parsed["system_user_password"], PASSWORD)
                    self.assertEqual(parsed["cloud"], provider)
                    self.assertEqual(parsed["isaacsim_git_checkpoint"], "v6.0.0")
                    self.assertNotIn("synthetic-password", repr(rendered))
                    secret_file = Path(next(value[1:] for value in extra if value.startswith("@")))
                    self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(secret_file.parent.stat().st_mode & 0o777, 0o700)
                    files.append(secret_file)
                return subprocess.CompletedProcess(argv, 0, "", "")
            with self.subTest(provider=provider), self.effects(module), contextlib.redirect_stdout(io.StringIO()):
                self.process.side_effect = execute
                self.build(provider, self.params())
                self.assertEqual(len(files), 1)
                self.assertFalse(files[0].exists())
                for name in ("system_user_password", "vnc_password"):
                    block = re.search(r'variable "' + name + r'"\s*\{([^}]+)\}', template).group(1)
                    self.assertRegex(block, r"sensitive\s*=\s*true")

    def test_packer_diagnostics_redact_escaped_values_and_disable_raw_logs(self):
        from src.python.image_command_utils import run_packer_build
        output = io.StringIO()
        diagnostics = "progress " + json.dumps(PASSWORD) + shlex.quote(PASSWORD)
        self.process.return_value = subprocess.CompletedProcess([], 0, diagnostics, diagnostics)
        with mock.patch.dict(os.environ, PACKER_LOG="1", PACKER_LOG_PATH="raw-packer.log"), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            run_packer_build("fixture.pkr.hcl", {"system_user_password": PASSWORD}, debug=True)
        self.assertNotIn("synthetic-password", output.getvalue())
        for call in self.process.call_args_list:
            self.assertEqual(call.kwargs["env"]["PACKER_LOG"], "0")
            self.assertNotIn("PACKER_LOG_PATH", call.kwargs["env"])

    def test_failed_packer_stops_and_cleans_up_without_success_claim(self):
        for provider, module in self.modules.items():
            for stage in ("init", "build"):
                for failure in ("nonzero", "oserror", "interrupt"):
                    with self.subTest(provider=provider, stage=stage, failure=failure), \
                         self.effects(module), mock.patch("tempfile.tempdir", self.tmp):
                        calls = []
                        def execute(argv, **kwargs):
                            calls.append(argv)
                            if argv[1] == stage:
                                if failure == "oserror":
                                    raise OSError(PASSWORD)
                                if failure == "interrupt":
                                    raise KeyboardInterrupt()
                                return subprocess.CompletedProcess(argv, 17, "", PASSWORD)
                            return subprocess.CompletedProcess(argv, 0, "", "")
                        self.process.side_effect = execute
                        output = io.StringIO()
                        expected = KeyboardInterrupt if failure == "interrupt" else click.ClickException
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                            with self.assertRaises(expected) as stopped:
                                self.build(provider, self.params())
                        self.assertNotIn("synthetic-password", str(stopped.exception) + output.getvalue())
                        self.assertNotIn("build complete", output.getvalue())
                        self.assertEqual([argv[1] for argv in calls], ["init"] if stage == "init" else ["init", "build"])
                        self.assertEqual(list(Path(self.tmp).iterdir()), [])

    def test_build_uses_private_variable_file_not_secret_argv_or_debug(self):
        for provider, module in self.modules.items():
            with self.subTest(provider=provider), self.effects(module) as effects:
                files, calls = [], []
                if provider == "aws":
                    effects["aws_image_credentials"].return_value = {
                        "aws_access_key_id": "synthetic-access",
                        "aws_secret_access_key": "synthetic-cloud-secret",
                        "aws_session_token": "synthetic-session-token",
                    }
                def execute(argv, **kwargs):
                    calls.append((argv, kwargs))
                    self.assertIsInstance(argv, list)
                    self.assertFalse(kwargs.get("shell", False))
                    self.assertNotIn("synthetic-password", repr(argv))
                    self.assertNotIn("synthetic-cloud-secret", repr(argv))
                    if argv[1] == "build":
                        path = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("-var-file=")))
                        files.append(path)
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                        variables = json.loads(path.read_text())
                        self.assertEqual(variables["system_user_password"], PASSWORD)
                        for key in ("isaacsim", "isaaclab", "isaaclab_arena", "demos", "install_gr00t", "enable_neo4j"):
                            self.assertEqual(variables[key], self.params()[key])
                        self.assertEqual(variables["version"], "synthetic-version")
                        self.assertIs(variables["in_china"], False)
                        if provider == "gcp":
                            self.assertEqual(variables["image_name"], "isaac-automator-isaacworkstation-fixture-1-0")
                            self.assertEqual(variables["gpu_count"], 1)
                            self.assertEqual(kwargs["env"]["GCP_PROJECT"], "fixture-project")
                        elif provider == "aws":
                            self.assertIn("-force", argv)
                            self.assertEqual(variables["image_name"], "isaacautomator.isaacworkstation.Fixture_1.0")
                            self.assertEqual(kwargs["env"]["AWS_SECRET_ACCESS_KEY"], "synthetic-cloud-secret")
                        else:
                            self.assertEqual(variables["image_name"], "isaac_automator.isaacworkstation.Fixture_1.0")
                            self.assertEqual(kwargs["env"]["AZURE_SUBSCRIPTION_ID"], "fixture-subscription")
                    return subprocess.CompletedProcess(argv, 0, f"progress {PASSWORD}", "")
                self.process.side_effect = execute
                before = dict(os.environ)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    self.build(provider, self.params())
                self.assertNotIn("synthetic-password", output.getvalue())
                self.assertEqual([argv[1] for argv, _ in calls], ["init", "build"])
                self.assertIn("progress", output.getvalue())
                self.assertEqual(dict(os.environ), before)
                self.assertEqual(len(files), 1)
                self.assertFalse(files[0].exists())
                self.assertFalse(files[0].parent.exists())
                if provider == "gcp":
                    effects["gcp_login"].assert_called_once()
                    effects["delete_gcp_image"].assert_called_once_with(
                        "fixture-project", "isaac-automator-isaacworkstation-fixture-1-0", verbose=True)
                elif provider == "aws":
                    effects["aws_image_credentials"].assert_called_once()
                else:
                    effects["azure_login"].assert_called_once()
                    effects["azure_ensure_resource_group"].assert_called_once()
                    effects["delete_managed_image"].assert_called_once()


class TestImageEntrypointProcesses(unittest.TestCase):
    def test_help_and_default_preview_work_without_external_tools(self):
        with tempfile.TemporaryDirectory(prefix="image-entrypoint-regression-") as directory:
            env = {"HOME": directory, "PATH": directory, "PYTHONPATH": str(ROOT)}
            # Exercise the real __main__ host branch in a fresh interpreter.
            # Forbid child processes and network before importing application code.
            host_entrypoint = """
import os
import runpy
import sys

def forbid_external_effects(event, args):
    if event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn")) or event in (
        "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.posix_spawnp",
    ):
        raise AssertionError("External effect forbidden: " + event)

sys.addaudithook(forbid_external_effects)
real_exists = os.path.exists
os.path.exists = lambda path: False if path == "/.dockerenv" else real_exists(path)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
            for provider in PROVIDERS:
                for preview in (False, True):
                    with self.subTest(provider=provider, preview=preview):
                        args = [sys.executable, "-c", host_entrypoint, str(ROOT / f"image-{provider}")]
                        args += (["--image-name", "offline-preview", "--system-user-password", "synthetic",
                                  "--dry-run"] if preview else ["--help"])
                        if preview and provider == "gcp":
                            args += ["--project", "offline-project"]
                        result = subprocess.run(args, cwd=ROOT, env=env, input="\n" * 20,
                                                capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("rendering-only", result.stdout)
                        self.assertNotIn("git-ref", result.stdout + result.stderr)
                        self.assertNotIn("synthetic", result.stdout + result.stderr)
                        if preview:
                            self.assertIn('"version": null', result.stdout)
                            self.assertIn("not validated", result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
