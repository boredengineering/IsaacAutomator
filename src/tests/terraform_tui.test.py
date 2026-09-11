"""Offline TUI/backend seam tests; no clouds, real state or user profiles."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.tui import backend


def source_method(path, class_name, method_name, namespace):
    """Exercise a UI method's real AST without pretending Textual is installed.

    These are method-level seam tests, not headless Textual integration tests.
    """
    import ast
    tree = ast.parse(Path(path).read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == method_name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, "exec"), namespace)
    return namespace[method_name]


class BackendSelectionTests(unittest.TestCase):
    def test_repository_root_uses_shared_cli_configuration(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as root:
            env = dict(os.environ, APP_DIR=root)
            process = subprocess.run([sys.executable, "-c",
                "from src.tui.backend import REPO_ROOT; print(REPO_ROOT)"],
                env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.strip(), root)

    def test_local_default_is_explicit_even_with_legacy_environment(self):
        with mock.patch.dict(os.environ, ISAAC_STATE_BUCKET="do-not-use"):
            spec, args = backend.backend_selection("gcp")
        self.assertEqual(spec.backend, "local")
        self.assertEqual(args, ["--state-backend", "local"])

    def test_shared_loader_preserves_only_validated_remote_intent(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend config.yaml"
            config = {"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}
            path.write_text(json.dumps(config))
            spec, args = backend.backend_selection("gcp", "gcs", str(path))
            self.assertEqual(args, ["--state-backend", "gcs", "--backend-config", str(path)])
            self.assertEqual(spec.to_dict()["destination"], config["destination"])
            with self.assertRaises(ValueError):
                backend.backend_selection("aws", "gcs", str(path))
            path.write_text('backend: gcs\nbackend: local')
            with self.assertRaises(ValueError):
                backend.backend_selection("gcp", "gcs", str(path))

    def test_deployment_transport_quotes_values_and_always_selects_local(self):
        import shlex
        result = {"name": "name with spaces; false", "cloud": "aws", "gpu": "g5.xlarge",
                  "profile": "team", "zone": "us-east-1", "dry_run": True}
        command = backend.deployment_command(result)
        argv = shlex.split(command)
        self.assertEqual(argv[argv.index("--deployment-name") + 1], result["name"])
        self.assertEqual(argv[argv.index("--state-backend") + 1], "local")
        self.assertNotIn("--backend-config", argv)
        self.assertIn("--dry-run", argv)

    def test_untouched_saved_remote_profile_is_not_overridden_by_local(self):
        from src.python.config import load_profile_spec
        from src.python.backend_selection import select_backend
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "profile.json"
            path.write_text(json.dumps({"cloud": "gcp", "terraform_state": {
                "backend": "gcs", "namespace": "team", "destination": {
                    "bucket": "example-state", "project": "example-project", "prefix": "state"}}}))
            profile = load_profile_spec(str(path), repo_root=root)
            self.assertEqual(select_backend({}, profile, "gcp").backend, "gcs")
            result = {"cloud": "gcp", "profile": str(path), "project": "example-project"}
            with self.assertRaisesRegex(ValueError, "blocked"):
                backend.deployment_command(result)
            # A deliberate local override remains supported.
            self.assertIn("--state-backend local", backend.deployment_command(
                {**result, "state_backend": "local"}))

    def test_remote_deployment_is_blocked_before_any_wrapper_or_setup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            path.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            with mock.patch.object(backend.subprocess, "run", side_effect=AssertionError("hidden command")):
                with self.assertRaisesRegex(ValueError, "blocked"):
                    backend.deployment_command({"cloud": "gcp", "state_backend": "gcs",
                                                "backend_config": str(path), "dry_run": True})


class ValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_loader_returns_canonical_intent_from_bounded_child(self):
        self.assertTrue(hasattr(backend, "load_backend_selection"), "profile loader still has no terminable boundary")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            processes = []
            spawn = asyncio.create_subprocess_exec
            async def observe(*args, **kwargs):
                proc = await spawn(*args, **kwargs)
                processes.append(proc)
                return proc
            with mock.patch.object(asyncio, "create_subprocess_exec", side_effect=observe):
                spec = await backend.load_backend_selection("gcp", "gcs", str(path))
            self.assertEqual(spec.to_dict(), backend.backend_selection("gcp", "gcs", str(path))[0].to_dict())
            self.assertEqual(len(processes), 1)
            self.assertEqual(processes[0].returncode, 0)

    async def test_profile_editor_validation_uses_process_not_loader_thread(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text('{"backend":"local"}')
            panel = SimpleNamespace(update=mock.Mock())
            pane = SimpleNamespace(selected_cloud="aws", selected_state_backend="local", backend_config=str(path),
                                   validated_backend=None, validated_selection=None, query_one=lambda *a: panel)
            method = source_method("src/tui/screens/profiles.py", "ProfilesPane", "validate_backend",
                                   {**vars(backend), "Static": object})
            with mock.patch.object(asyncio, "create_subprocess_exec", wraps=asyncio.create_subprocess_exec) as spawn:
                await method(pane)
            self.assertEqual(pane.validated_backend.backend, "local")
            self.assertEqual(spawn.call_count, 1, "editor still uses an uncancellable loader thread")

    async def test_inherited_remote_is_displayed_and_blocked_in_modal_and_dispatch(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "profile.json"
            path.write_text(json.dumps({"cloud": "gcp", "terraform_state": {
                "backend": "gcs", "namespace": "team", "destination": {
                    "bucket": "example-state", "project": "example-project", "prefix": "state"}}}))
            panel, launch = mock.Mock(), SimpleNamespace(disabled=False)
            modal = SimpleNamespace(selected_cloud="gcp", selected_state_backend=None, backend_config="",
                                    selected_profile=str(path), validated_selection=None, effective_state_backend=None,
                                    query_one=lambda selector, *a: panel if selector == "#backend-status" else launch,
                                    update_summary=mock.Mock())
            validate = source_method("src/tui/screens/deploy_modal.py", "DeployWorkstationModal", "validate_backend",
                                     {**vars(backend), "Static": object, "Button": object})
            await validate(modal)
            self.assertEqual(modal.effective_state_backend, "gcs")
            self.assertTrue(launch.disabled)
            self.assertIn("Inherited", panel.update.call_args.args[0])
            self.assertNotIn(str(path), str(panel.update.call_args_list))
            dispatch = source_method("src/tui/app.py", "Isaac9sApp", "dispatch_deployment", vars(backend).copy())
            app = SimpleNamespace(notify=mock.Mock(), run_async_command=mock.Mock())
            with mock.patch.object(asyncio, "create_subprocess_exec", wraps=asyncio.create_subprocess_exec) as spawn:
                await dispatch(app, {"cloud": "gcp", "profile": str(path), "project": "example-project"})
            app.run_async_command.assert_not_called()
            self.assertEqual(spawn.call_count, 1, "dispatch still uses a nonterminable loader thread")

    async def test_inventory_load_uses_bounded_process(self):
        self.assertTrue(hasattr(backend, "load_deployment_inventory"), "inventory still retains filesystem threads")
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            (directory / "meta.json").write_text('{"params":{"state_bucket":"legacy"}}')
            with mock.patch.object(asyncio, "create_subprocess_exec", wraps=asyncio.create_subprocess_exec) as spawn:
                rows = await backend.load_deployment_inventory(repo_root=root)
            self.assertEqual(rows[0]["attachment"], "legacy-remote-unverified")
            self.assertEqual(spawn.call_count, 1)

    async def test_fleet_status_timeout_does_not_become_undeployed(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            async def inventory(**kwargs):
                return await backend.load_deployment_inventory(repo_root=root, **kwargs)
            ns = {"asyncio": asyncio, "load_deployment_inventory": inventory}
            method = source_method("src/tui/app.py", "BackendAwareWorkstationsPane", "load_workstations", ns)
            pane = SimpleNamespace(current_vms=[], render_workstations=mock.Mock())
            await method(pane, timeout=0.001)
        self.assertEqual(pane.current_vms[0]["status"], "STATE UNKNOWN / VM UNKNOWN")
        pane.render_workstations.assert_called_once()

    async def test_cancellation_kills_and_reaps_real_offline_child(self):
        import sys
        started = asyncio.Event()
        processes = []
        spawn = asyncio.create_subprocess_exec
        async def observe(*args, **kwargs):
            proc = await spawn(*args, **kwargs)
            processes.append(proc)
            started.set()
            return proc
        # Real synthetic child on the same runner used by validation/profile loads.
        # No extracted UI method or fake Process is evidence for cancellation.
        with mock.patch.object(asyncio, "create_subprocess_exec", side_effect=observe):
            task = asyncio.create_task(backend._run_offline_json(
                [sys.executable, "-c", "import time; time.sleep(60)"]))
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        self.assertLess(processes[0].returncode, 0)
        with self.assertRaises(ChildProcessError):
            os.waitpid(processes[0].pid, os.WNOHANG)

    async def test_invalid_config_diagnostics_are_not_rendered(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text('{"backend":"local","token":"private-sentinel"}')
            result = await backend.validate_backend_config("gcp", str(path))
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "invalid-config")
        self.assertNotIn("private-sentinel", json.dumps(result))

    async def test_offline_cli_validation_never_claims_reachability(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            result = await backend.validate_backend_config("gcp", str(path))
        self.assertEqual(result["status"], "valid-config")
        self.assertEqual(result["cloud_access"], "not_checked")
        self.assertEqual(result["remote_lifecycle"], "not_enabled")

    async def test_timeout_and_overflow_reap_real_offline_children(self):
        import sys
        for program, expected, timeout in (
            ("import time; time.sleep(60)", asyncio.TimeoutError, 0.02),
            ("import sys,time; sys.stdout.write('x'*9000); sys.stdout.flush(); time.sleep(60)", ValueError, 5),
        ):
            with self.subTest(expected=expected):
                processes = []
                spawn = asyncio.create_subprocess_exec
                async def observe(*args, **kwargs):
                    proc = await spawn(*args, **kwargs)
                    processes.append(proc)
                    return proc
                with mock.patch.object(asyncio, "create_subprocess_exec", side_effect=observe):
                    with self.assertRaises(expected):
                        await backend._run_offline_json([sys.executable, "-c", program], timeout=timeout)
                self.assertLess(processes[0].returncode, 0)
                with self.assertRaises(ChildProcessError):
                    os.waitpid(processes[0].pid, os.WNOHANG)


class StatusTests(unittest.TestCase):
    def test_legacy_remote_intent_never_falls_back_to_local_state_or_dispatch(self):
        from types import SimpleNamespace
        fixtures = [
            {"params": {"state_bucket": "legacy-bucket"}},
            {"config": {"state_bucket": "legacy-bucket"}},
            {"params": {"state_backend": "gcs"}},
            {"params": {"terraform_state": {"backend": "s3"}}},
            {"config": {"security": {"storage": {"state_backend": "gcs"}}}},
        ]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            (directory / ".tfstate").write_text('{"outputs":{"isaac_ip":{"value":"stale-ip"}}}')
            for fixture in fixtures:
                with self.subTest(fixture=fixture):
                    (directory / "meta.json").write_text(json.dumps(fixture))
                    with mock.patch.object(backend, "REPO_ROOT", Path(root)):
                        row = backend.WorkstationBackend.get_deployments()[0]
                    self.assertEqual(row["attachment"], "legacy-remote-unverified")
                    self.assertNotEqual(row["backend"], "local")
                    self.assertEqual(row["backend_access"], "unknown")
                    self.assertNotIn("stale-ip", json.dumps(row))
                    for action in ("start", "stop"):
                        (Path(root) / action).touch()
                        method = source_method("src/tui/app.py", "Isaac9sApp", "action_run_" + action,
                                               {"REPO_ROOT": Path(root)})
                        app = SimpleNamespace(workstations_pane=SimpleNamespace(get_selected_workstation=lambda: row),
                                              notify=mock.Mock(), run_async_command=mock.Mock())
                        method(app)
                        app.run_async_command.assert_not_called()

    def test_unreadable_legacy_intent_does_not_become_local(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            (directory / "meta.json").write_text('{"params":{"state_bucket":')
            (directory / ".tfstate").write_text('{"outputs":{}}')
            with mock.patch.object(backend, "REPO_ROOT", Path(root)):
                row = backend.WorkstationBackend.get_deployments()[0]
            self.assertEqual(row["attachment"], "unreadable")
            self.assertEqual(row["backend"], "unknown")
            self.assertEqual(row["backend_access"], "unknown")

    def test_local_fifo_is_not_opened_with_a_blocking_reader(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            os.mkfifo(directory / ".tfstate")
            with mock.patch.object(backend, "REPO_ROOT", Path(root)), mock.patch(
                    "builtins.open", side_effect=AssertionError("blocking open")) as reader:
                row = backend.WorkstationBackend.get_deployments()[0]
            reader.assert_not_called()
            self.assertEqual(row["backend_access"], "unknown")

    def test_unreadable_local_state_is_unknown_not_undeployed(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            (directory / ".tfstate").write_text("not valid state")
            with mock.patch.object(backend, "REPO_ROOT", Path(root)):
                row = backend.WorkstationBackend.get_deployments()[0]
            self.assertEqual(row["status"], "STATE UNKNOWN / VM UNKNOWN")
            self.assertEqual(row["backend_access"], "unknown")

    def test_sensitive_ip_output_is_not_rendered(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            (directory / ".tfstate").write_text(json.dumps({"outputs": {
                "isaac_workstation_ip": {"sensitive": True, "value": "private-sentinel"}}}))
            with mock.patch.object(backend, "REPO_ROOT", Path(root)):
                row = backend.WorkstationBackend.get_deployments()[0]
            self.assertNotIn("private-sentinel", json.dumps(row))

    def test_descriptor_attachment_is_not_reachable_or_undeployed(self):
        from src.python.deployment_manifest import DeploymentManifest
        from src.python.terraform_backend import BackendSpec
        spec = BackendSpec.from_dict({"backend": "gcs", "namespace": "team", "destination": {
            "bucket": "example-state", "project": "example-project", "prefix": "state"}}, cloud="gcp")
        manifest = DeploymentManifest.create(
            backend_spec=spec, target_scope="example-project", deployment_name="demo",
            lineage="11111111-1111-4111-8111-111111111111", serial=3,
            addresses=["google_compute_instance.workstation"], source=None, lockfile=None,
            inputs={}, input_reference=None, secret_references={}, applied_at=None)
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            descriptor = directory / "backend.json"
            descriptor.write_text(manifest.canonical_json())
            descriptor.chmod(0o600)
            (directory / ".tfstate").write_text('{"outputs":{"secret":{"value":"private-sentinel"}}}')
            before = sorted(str(p) for p in Path(root).rglob("*"))
            with mock.patch.object(backend, "REPO_ROOT", Path(root)):
                rows = backend.WorkstationBackend.get_deployments()
            self.assertEqual(rows[0]["backend"], "gcs")
            self.assertEqual(rows[0]["attachment"], "present-unverified")
            self.assertEqual(rows[0]["backend_access"], "unknown")
            self.assertIn("ATTACHMENT", rows[0]["status"])
            self.assertNotIn("private-sentinel", json.dumps(rows))
            self.assertEqual(before, sorted(str(p) for p in Path(root).rglob("*")))

    def test_invalid_descriptor_does_not_fall_back_to_local_state(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "state" / "demo"
            directory.mkdir(parents=True)
            (directory / "backend.json").write_text('{"private":"private-sentinel"}')
            (directory / ".tfstate").write_text('{"outputs":{}}')
            with mock.patch.object(backend, "REPO_ROOT", Path(root)):
                row = backend.WorkstationBackend.get_deployments()[0]
            self.assertEqual(row["status"], "ATTACHMENT INVALID / VM UNKNOWN")
            self.assertNotIn("private-sentinel", json.dumps(row))


class UISeamTests(unittest.TestCase):
    def test_deploy_inherit_selector_is_not_an_explicit_local_choice(self):
        from types import SimpleNamespace
        ns = {"Select": SimpleNamespace(Changed=object)}
        method = source_method("src/tui/screens/deploy_modal.py", "DeployWorkstationModal",
                               "on_select_changed", ns)
        modal = SimpleNamespace(selected_state_backend="local", invalidate_backend_validation=mock.Mock(),
                                update_summary=mock.Mock())
        method(modal, SimpleNamespace(select=SimpleNamespace(id="sel-state-backend"), value="inherit"))
        self.assertIsNone(modal.selected_state_backend)

    def test_validated_inherited_local_submit_preserves_absent_override(self):
        from types import SimpleNamespace
        method = source_method("src/tui/screens/deploy_modal.py", "DeployWorkstationModal", "submit_deployment",
                               {"Input": object, "Checkbox": object})
        modal = SimpleNamespace(selected_cloud="aws", selected_profile="simple", selected_gpu="g5.xlarge",
                                selected_zone="us-east-1", scheduling_model="standard", selected_state_backend=None,
                                backend_config="", effective_state_backend="local",
                                validated_selection=("aws", None, "", "simple"),
                                dismiss=mock.Mock(), notify=mock.Mock(), start_backend_validation=mock.Mock(),
                                query_one=lambda *a: SimpleNamespace(value="demo"))
        method(modal)
        modal.dismiss.assert_called_once()
        self.assertIsNone(modal.dismiss.call_args.args[0]["state_backend"])

    def test_installer_missing_means_unknown_not_healthy_cloud_drift(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            installer = Path(root) / "missing-installer"
            method = source_method("src/tui/app.py", "Isaac9sApp", "action_run_heal",
                                   {"INSTALLER_BIN": installer})
            app = SimpleNamespace(log_message=mock.Mock(), run_async_command=mock.Mock())
            method(app)
            app.run_async_command.assert_not_called()
            shown = str(app.log_message.call_args_list).lower()
            self.assertNotIn("healthy", shown)
            self.assertIn("unknown", shown)
            self.assertIn("local", shown)
            self.assertIn("cloud drift", shown)

    def test_config_path_is_execution_only_not_log_or_process_status(self):
        from types import SimpleNamespace
        import time
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "private-config.json"
            path.write_text('{"backend":"local"}')
            cmd = backend.deployment_command({"cloud": "aws", "backend_config": str(path)})
            self.assertIn(str(path), cmd)
            method = source_method("src/tui/app.py", "Isaac9sApp", "run_async_command",
                                   {**vars(backend), "time": time})
            proc = mock.Mock(pid=123, returncode=0)
            proc.stdout.readline.side_effect = ["loaded " + str(path) + "\n", ""]
            app = SimpleNamespace(active_proc=None, log_message=mock.Mock(), action_tab_logs=mock.Mock(),
                                  logs_pane=mock.Mock(), workstations_pane=mock.Mock(),
                                  call_from_thread=lambda fn, *args: fn(*args),
                                  run_worker=lambda fn, **kwargs: fn())
            with mock.patch.object(backend.subprocess, "Popen", return_value=proc) as spawn:
                method(app, cmd)
            self.assertEqual(spawn.call_args.args[0], cmd)
            shown = str(app.log_message.call_args_list) + str(app.logs_pane.set_proc_running.call_args_list)
            self.assertNotIn(str(path), shown)

    def test_attached_unknown_workstations_cannot_start_or_stop(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            for operation in ("start", "stop"):
                (Path(root) / operation).touch()
                method = source_method("src/tui/app.py", "Isaac9sApp", "action_run_" + operation,
                                       {"REPO_ROOT": Path(root)})
                app = SimpleNamespace(workstations_pane=SimpleNamespace(get_selected_workstation=lambda: {
                    "name": "demo", "cloud": "GCP", "attachment": "present-unverified"}),
                    log_message=mock.Mock(), notify=mock.Mock(), run_async_command=mock.Mock())
                method(app)
                app.run_async_command.assert_not_called()

    def test_profile_roundtrip_preserves_canonical_intent_without_config_path(self):
        import yaml
        from types import SimpleNamespace
        from src.python.config import load_profile_spec
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            spec, _ = backend.backend_selection("gcp", "gcs", str(path))
            ns = {"backend_selection": backend.backend_selection, "Path": Path,
                  "REPO_ROOT": Path(root), "yaml": yaml}
            intent = source_method("src/tui/screens/profiles.py", "ProfilesPane", "backend_intent", ns)
            export = source_method("src/tui/screens/profiles.py", "ProfilesPane", "export_yaml", ns)
            pane = SimpleNamespace(selected_cloud="gcp", selected_state_backend="gcs", backend_config=str(path),
                                   validated_backend=spec, validated_selection=("gcp", "gcs", str(path)),
                                   selected_profile="fixture", selected_tier="team")
            pane.backend_intent = lambda: intent(pane)
            saved = export(pane)
            loaded = load_profile_spec(str(saved), repo_root=root)
            self.assertEqual(loaded["terraform_state"], spec.to_dict())
            self.assertEqual(loaded["state_bucket"], "")
            self.assertNotIn(str(path), saved.read_text())
            pane.backend_config = "changed.json"
            with self.assertRaises(ValueError):
                export(pane)

    def test_app_dispatch_uses_shared_transport_without_credential_recovery(self):
        source = Path("src/tui/app.py").read_text()
        self.assertIn("deployment_command", source)
        self.assertNotIn("shutil.copyfile(found_adc, adc_path)", source)
        self.assertNotIn('subprocess.run(["gcloud", "config", "get-value", "project"]', source)

    def test_inspector_only_displays_safe_summary_not_raw_params_outputs(self):
        from types import SimpleNamespace
        method = source_method("src/tui/screens/inspector.py", "WorkstationInspectorModal",
                               "get_state_content", {"json": json, "Path": Path})
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "meta.json").write_text('{"params":{"password":"private-sentinel"}}')
            (Path(root) / ".tfstate").write_text('{"outputs":{"token":{"value":"private-sentinel"}}}')
            result = method(SimpleNamespace(workstation={"path": root, "backend": "gcs",
                            "backend_access": "unknown", "attachment": "present-unverified"}))
        self.assertNotIn("private-sentinel", result)
        self.assertIn("present-unverified", result)
        self.assertIn("unknown", result)

    def test_deploy_submit_preserves_explicit_selection_in_result(self):
        import ast
        tree = ast.parse(Path("src/tui/screens/deploy_modal.py").read_text())
        keys = {key.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                for key in node.keys if isinstance(key, ast.Constant)}
        self.assertTrue({"state_backend", "backend_config"} <= keys)

    def test_profiles_do_not_generate_auto_remote_bucket(self):
        source = Path("src/tui/screens/profiles.py").read_text()
        self.assertNotIn('"state_bucket": "auto"', source)
        self.assertIn('"terraform_state"', source)


class HeadlessBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import importlib.util
        missing = [name for name in ("textual", "rich", "psutil") if importlib.util.find_spec(name) is None]
        if missing:
            self.skipTest("TUI runtime dependencies unavailable; no packages installed: " + ", ".join(missing))

    async def test_remote_selection_only_runs_offline_validation(self):
        from textual.app import App
        from textual.widgets import Button, Input, Select
        from src.tui.screens.deploy_modal import DeployWorkstationModal
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            app = App()
            submitted = mock.Mock()
            with mock.patch("src.python.config.list_available_profiles", return_value={}):
                async with app.run_test() as pilot:
                    modal = DeployWorkstationModal()
                    app.push_screen(modal, submitted)
                    await pilot.pause()
                    self.assertIsNone(modal.selected_state_backend)
                    modal.query_one("#sel-state-backend", Select).value = "gcs"
                    modal.query_one("#inp-backend-config", Input).value = str(path)
                    await pilot.pause()
                    self.assertTrue(modal.query_one("#btn-deploy-launch", Button).disabled)
                    with mock.patch.object(asyncio, "create_subprocess_exec", wraps=asyncio.create_subprocess_exec) as spawn:
                        modal.submit_deployment(dry_run=True)
                        await modal.backend_worker.wait()
                    self.assertEqual(spawn.call_count, 1)
                    self.assertEqual(spawn.call_args.args[1:4], ("-m", "src.tui.backend", "selection"))
                    self.assertTrue(modal.query_one("#btn-deploy-launch", Button).disabled)
                    submitted.assert_not_called()
                    modal.dismiss(None)

    async def test_profile_panel_saves_only_validated_intent(self):
        from textual.app import App
        from textual.widgets import Input, Select
        from src.tui.screens.profiles import ProfilesPane
        from src.python.config import load_profile_spec
        class ProfileApp(App):
            def compose(self):
                yield ProfilesPane()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "backend.json"
            path.write_text(json.dumps({"backend": "gcs", "namespace": "team", "destination": {
                "bucket": "example-state", "project": "example-project", "prefix": "state"}}))
            with mock.patch("src.tui.screens.profiles.REPO_ROOT", Path(root)):
                app = ProfileApp()
                async with app.run_test() as pilot:
                    pane = app.query_one(ProfilesPane)
                    pane.query_one("#sel-profile-backend", Select).value = "gcs"
                    pane.query_one("#inp-profile-backend-config", Input).value = str(path)
                    await pilot.pause()
                    with self.assertRaises(ValueError):
                        pane.save_custom_profile_yaml()
                    await pane.validate_backend()
                    saved = pane.save_custom_profile_yaml()
                    result = load_profile_spec(str(saved), repo_root=root)
                    self.assertEqual(result["terraform_state"]["backend"], "gcs")
                    self.assertEqual(result["state_bucket"], "")
                    self.assertNotIn(str(path), saved.read_text())


if __name__ == "__main__":
    unittest.main()
