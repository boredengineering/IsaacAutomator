"""Runner foundation tests: only disposable, provider-free local state is real."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import Mock, patch, call as mock_call

from src.python.terraform_backend import BackendSpec


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runner-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "main.tf").write_text('''terraform {
  required_version = ">= 1.3.5"
  backend "local" {}
}
module "nested" { source = "./modules/nested" }
output "answer" { value = module.nested.answer }
''')
        (self.source / "modules/nested").mkdir(parents=True)
        (self.source / "modules/nested/main.tf").write_text('output "answer" { value = "offline-persistent" }\n')
        self.spec = BackendSpec.from_dict({}, cloud="aws")
        self.options = dict(source_root=self.source,
                            source_files=["main.tf", "modules/nested/main.tf"],
                            backend_spec=self.spec, target_scope="123456789012",
                            deployment_name="fixture", state_root=self.root / "state",
                            lock_root=self.root / "locks", controller_lock_timeout=0.1,
                            environment={"PATH": os.environ["PATH"], "CHECKPOINT_DISABLE": "1"})

    def runner(self, **changes):
        from src.python.terraform_runner import TerraformRunner
        return TerraformRunner(**{**self.options, **changes})

    def test_real_saved_plan_json_and_state_identity(self):
        with self.runner() as run:
            run.init()
            plan = run.plan()
            self.assertTrue(callable(getattr(run, "plan_json", None)), "saved plan inspection is missing")
            document = run.plan_json(plan)
            self.assertEqual(document["format_version"], "1.2")
            self.assertIn("planned_values", document)
            run.apply(plan, acknowledge_mutation=True)
            state = run.pull_state()
            self.assertEqual(state["version"], 4)
            self.assertIsInstance(state["lineage"], str)
            self.assertIsInstance(state["serial"], int)
            self.assertEqual(state["outputs"]["answer"]["value"], "offline-persistent")

    def test_real_destroy_and_refresh_only_saved_plans(self):
        from src.python.terraform_runner import TerraformRunnerError
        with self.runner() as run:
            run.init()
            run.apply(run.plan(), acknowledge_mutation=True)
            refresh = run.plan(refresh_only=True)
            self.assertFalse(refresh.has_changes)
            with self.assertRaises(TerraformRunnerError):
                run.plan(destroy=True, refresh_only=True)
            destruction = run.plan(destroy=True)
            self.assertTrue(destruction.has_changes)
            run.apply(destruction, acknowledge_mutation=True)
            self.assertEqual(run.pull_state()["outputs"], {})

    def test_state_pull_rejects_missing_and_malformed_identity(self):
        from src.python.terraform_runner import TerraformRunnerError
        valid = {"version": 4, "lineage": "fixture-lineage", "serial": 0, "outputs": {}, "resources": []}
        malformed = [b"", b"{}", b"[]", b"null", b"SECRET-NOT-JSON"]
        for field, value in (("version", True), ("serial", True), ("serial", -1),
                             ("lineage", ""), ("resources", [{}]), ("outputs", {"x": "bad"})):
            malformed.append(json.dumps({**valid, field: value}).encode())
        with self.runner() as run:
            run.init()
            with self.assertRaises(TerraformRunnerError):
                run.pull_state()
            for raw in malformed:
                with self.subTest(raw=raw), patch.object(run, "_execute", return_value=(0, raw)):
                    with self.assertRaises(TerraformRunnerError) as error:
                        run.pull_state()
                    self.assertNotIn("SECRET", str(error.exception))

    def test_import_is_explicit_argv_and_invalidates_saved_plan(self):
        from src.python.terraform_runner import TerraformRunnerError
        with self.runner() as run:
            run.init()
            plan = run.plan()
            self.assertTrue(callable(getattr(run, "import_resource", None)), "isolated import is missing")
            with patch.object(run, "_execute", return_value=(0, b"")) as execute:
                with self.assertRaises(TerraformRunnerError):
                    run.import_resource("module.common.azurerm_resource_group.isa_rg", "/subscriptions/fixture/resourceGroups/fixture")
                execute.assert_not_called()
                run.import_resource("module.common.azurerm_resource_group.isa_rg", "/subscriptions/fixture/resourceGroups/fixture",
                                    acknowledge_mutation=True)
                argv = execute.call_args.args[0]
                self.assertEqual(argv[0], "import")
                self.assertEqual(argv[-2:], ["module.common.azurerm_resource_group.isa_rg", "/subscriptions/fixture/resourceGroups/fixture"])
                self.assertIn("-input=false", argv)
                with self.assertRaises(TerraformRunnerError):
                    run.apply(plan, acknowledge_mutation=True)
            for address, identifier in (("-bad", "id"), ("x.y", "-flag"), ("x.y", "bad\nvalue"),
                                        ("$(touch bad)", "id"), ("x.y", "")):
                with self.subTest(address=address), patch.object(run, "_execute") as execute:
                    with self.assertRaises(TerraformRunnerError):
                        run.import_resource(address, identifier, acknowledge_mutation=True)
                    execute.assert_not_called()

    def test_init_requires_matching_backend_metadata(self):
        from src.python.terraform_runner import TerraformRunnerError
        for kind in ("absent", "wrong-type", "wrong-path", "malformed", "nondefault-workspace"):
            with self.subTest(kind=kind), self.runner() as run:
                def execute(arguments, **kwargs):
                    if arguments[0] == "version":
                        return 0, b'{"terraform_version":"1.8.5"}'
                    data = {"backend": {"type": "local", "config": {"path": str(run.local_state_path)}}}
                    if kind == "wrong-type":
                        data["backend"]["type"] = "s3"
                    elif kind == "wrong-path":
                        data["backend"]["config"]["path"] = "/tmp/unrelated.tfstate"
                    if kind != "absent":
                        (run.data_dir / "terraform.tfstate").write_text("null" if kind == "malformed" else json.dumps(data))
                    if kind == "nondefault-workspace":
                        (run.data_dir / "environment").write_text("other")
                    return 0, b""
                with patch.object(run, "_execute", side_effect=execute):
                    with self.assertRaises(TerraformRunnerError):
                        run.init()

    def test_existing_hcl_inputs_are_private_immutable_operation_snapshot(self):
        (self.source / "main.tf").write_text('variable "message" { type = string }\noutput "message" { value = var.message }')
        inputs = self.root / "legacy.tfvars"
        inputs.write_text('message = "legacy-value"\n')
        run = self.runner(source_files=["main.tf"], variables_file=inputs)
        with run:
            inputs.write_text('message = "changed-after-selection"\n')
            run.init()
            run.apply(run.plan(), acknowledge_mutation=True)
            self.assertEqual(run.output()["message"]["value"], "legacy-value")
            private_inputs = run.staged_root.parent / "inputs.tfvars"
            self.assertEqual(private_inputs.stat().st_mode & 0o777, 0o600)
            private_inputs.write_text('message = "changed-staged"\n')
            from src.python.terraform_runner import TerraformRunnerError
            with self.assertRaises(TerraformRunnerError):
                run.plan()

    def test_external_input_file_rejects_ambiguous_or_unsafe_paths(self):
        from src.python.terraform_runner import TerraformRunnerError
        inputs = self.root / "legacy.tfvars"
        inputs.write_text('message = "fixture"')
        linked = self.root / "linked.tfvars"
        linked.symlink_to(inputs)
        special = self.root / "special.tfvars"
        os.mkfifo(special)
        for changes in ({"variables_file": inputs, "variables": {}}, {"variables_file": linked},
                        {"variables_file": special}, {"variables_file": Path("relative.tfvars")},
                        {"variables_file": self.root / "absent.tfvars"}):
            with self.subTest(changes=changes), self.assertRaises(TerraformRunnerError):
                self.runner(**changes)

    def test_input_snapshot_pins_ancestors_before_final_open(self):
        from src.python.terraform_runner import _input_snapshot
        selected = self.root / "selected"
        selected.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        inputs = selected / "inputs.tfvars"
        inputs.write_bytes(b"APPROVED-SYNTHETIC")
        (outside / inputs.name).write_bytes(b"UNAPPROVED-SYNTHETIC")
        real_open = os.open
        swapped = False

        def swap_before_final_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path).name == inputs.name:
                self.assertFalse(swapped)
                selected.rename(self.root / "pinned-original")
                selected.symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        with patch("src.python.terraform_runner.os.open", side_effect=swap_before_final_open):
            snapshot = _input_snapshot(inputs)
        self.assertTrue(swapped, "the synthetic race did not execute")
        self.assertEqual(snapshot, b"APPROVED-SYNTHETIC")

    def test_input_snapshot_rejects_ancestor_replaced_before_directory_open(self):
        from src.python.terraform_runner import _input_snapshot, TerraformRunnerError
        selected = self.root / "selected"
        selected.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        inputs = selected / "inputs.tfvars"
        inputs.write_bytes(b"APPROVED-SYNTHETIC")
        (outside / inputs.name).write_bytes(b"UNAPPROVED-SYNTHETIC")
        real_open = os.open
        swapped = False
        opened_final = False

        def swap_before_directory_open(path, flags, *args, **kwargs):
            nonlocal swapped, opened_final
            if Path(path).name == selected.name:
                selected.rename(self.root / "pinned-original")
                selected.symlink_to(outside, target_is_directory=True)
                swapped = True
            if Path(path).name == inputs.name:
                opened_final = True
            return real_open(path, flags, *args, **kwargs)

        with patch("src.python.terraform_runner.os.open", side_effect=swap_before_directory_open):
            with self.assertRaises(TerraformRunnerError) as raised:
                _input_snapshot(inputs)
        self.assertTrue(swapped)
        self.assertFalse(opened_final)
        self.assertNotIn(str(self.root), "".join(traceback.format_exception(raised.exception)))

    def test_input_snapshot_rejects_unsafe_paths_and_enforces_size_boundary(self):
        from src.python.terraform_runner import _input_snapshot, TerraformRunnerError
        inputs = self.root / "inputs.tfvars"
        inputs.write_bytes(b"x" * (1024 * 1024))
        self.assertEqual(_input_snapshot(inputs), b"x" * (1024 * 1024))
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        final_link = self.root / "linked.tfvars"
        final_link.symlink_to(inputs)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for path in (self.root, Path("/"), linked / inputs.name, final_link, fifo,
                     self.root / "absent", self.root / ".." / inputs.name,
                     Path("relative.tfvars"), self.root / "invalid\0SYNTHETIC"):
            with self.subTest(path=path), self.assertRaises(TerraformRunnerError) as raised:
                _input_snapshot(path)
            diagnostic = "".join(traceback.format_exception(raised.exception))
            self.assertNotIn(str(self.root), diagnostic)
            self.assertNotIn("SYNTHETIC", diagnostic)
        inputs.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaises(TerraformRunnerError):
            _input_snapshot(inputs)

    def test_input_snapshot_bounds_read_when_file_grows_after_fstat(self):
        from src.python.terraform_runner import _input_snapshot, TerraformRunnerError
        inputs = self.root / "inputs.tfvars"
        inputs.write_bytes(b"approved")
        real_fstat = os.fstat

        def grow_after_fstat(fd):
            info = real_fstat(fd)
            inputs.write_bytes(b"x" * (1024 * 1024 + 1))
            return info

        with patch("src.python.terraform_runner.os.fstat", side_effect=grow_after_fstat):
            with self.assertRaisesRegex(TerraformRunnerError, "size limit"):
                _input_snapshot(inputs)

    def test_input_snapshot_closes_descriptors_and_sanitizes_io_failures(self):
        from contextlib import ExitStack
        import src.python.terraform_runner as module
        inputs = self.root / "inputs.tfvars"
        inputs.write_bytes(b"APPROVED-SYNTHETIC")
        real_open, real_close, real_fdopen, real_fstat = os.open, os.close, os.fdopen, os.fstat
        for failure in (None, "directory-open", "final-open", "fdopen", "fstat", "read", "close"):
            with self.subTest(failure=failure), ExitStack() as patches:
                opened, closed = [], []

                def open_file(path, flags, *args, **kwargs):
                    if ((failure == "directory-open" and Path(path).name == self.root.name)
                            or (failure == "final-open" and Path(path).name == inputs.name)):
                        raise OSError("SYNTHETIC-PRIVATE-DIAGNOSTICS")
                    fd = real_open(path, flags, *args, **kwargs)
                    opened.append(fd)
                    return fd

                def close_file(fd):
                    real_close(fd)
                    closed.append(fd)
                    if failure == "close":
                        raise OSError("SYNTHETIC-PRIVATE-DIAGNOSTICS")

                def open_stream(*args, **kwargs):
                    if failure == "fdopen":
                        raise OSError("SYNTHETIC-PRIVATE-DIAGNOSTICS")
                    stream = real_fdopen(*args, **kwargs)
                    if failure == "read":
                        patches.enter_context(patch.object(stream, "read", side_effect=
                                                          OSError("SYNTHETIC-PRIVATE-DIAGNOSTICS")))
                    return stream

                patches.enter_context(patch.object(module.os, "open", side_effect=open_file))
                patches.enter_context(patch.object(module.os, "close", side_effect=close_file))
                patches.enter_context(patch.object(module.os, "fdopen", side_effect=open_stream))
                if failure == "fstat":
                    patches.enter_context(patch.object(module.os, "fstat", side_effect=
                                                      OSError("SYNTHETIC-PRIVATE-DIAGNOSTICS")))
                if failure is None:
                    self.assertEqual(module._input_snapshot(inputs), b"APPROVED-SYNTHETIC")
                else:
                    with self.assertRaises(module.TerraformRunnerError) as raised:
                        module._input_snapshot(inputs)
                    diagnostic = "".join(traceback.format_exception(raised.exception))
                    self.assertNotIn("SYNTHETIC-PRIVATE-DIAGNOSTICS", diagnostic)
                    self.assertNotIn(str(self.root), diagnostic)
                self.assertTrue(opened)
                self.assertEqual(closed, list(reversed(opened)))
                for fd in opened:
                    with self.assertRaises(OSError):
                        real_fstat(fd)

    def test_plan_inspection_refuses_tampered_or_consumed_plan(self):
        from src.python.terraform_runner import TerraformRunnerError
        with self.runner() as run:
            run.init()
            plan = run.plan()
            self.assertTrue(callable(getattr(run, "plan_json", None)), "saved plan inspection is missing")
            plan.path.write_bytes(b"tampered")
            with self.assertRaises(TerraformRunnerError):
                run.plan_json(plan)
            plan = run.plan()
            run.apply(plan, acknowledge_mutation=True)
            with self.assertRaises(TerraformRunnerError):
                run.plan_json(plan)

    def test_failed_apply_retains_discoverable_private_recovery_state(self):
        from src.python.terraform_runner import TerraformRunnerError
        run = self.runner()
        def fake_terraform(argv, **kwargs):
            code, raw = 0, b'{}'
            if argv[1] == "version":
                raw = b'{"terraform_version":"1.8.5"}'
            elif argv[1] == "init":
                (run.data_dir / "terraform.tfstate").write_text(json.dumps({"backend": {
                    "type": "local", "config": {"path": str(run.local_state_path)}}}))
            elif argv[1] == "plan":
                Path(next(arg[5:] for arg in argv if arg.startswith("-out="))).write_bytes(b"PLAN")
                code = 2
            elif argv[1] == "apply":
                state = Path(kwargs["cwd"]) / "errored.tfstate"
                state.write_bytes(b"TEST-SECRET-RECOVERY")
                state.chmod(0o644)
                code, raw = 1, b"TEST-SECRET-DIAGNOSTICS"
            process = Mock(returncode=code)
            process.communicate.return_value = (raw, b"TEST-SECRET-DIAGNOSTICS")
            return process
        with self.assertRaises(TerraformRunnerError) as raised:
            with run, patch("src.python.terraform_runner.subprocess.Popen", side_effect=fake_terraform):
                base = run.staged_root.parent
                self.addCleanup(shutil.rmtree, base, ignore_errors=True)
                run.init()
                run.apply(run.plan(), acknowledge_mutation=True)
        state = base / "source/errored.tfstate"
        self.assertTrue(state.exists(), "context cleanup deleted recovery state")
        self.assertEqual(state.read_bytes(), b"TEST-SECRET-RECOVERY")
        self.assertEqual(run.recovery_directory, base)
        self.assertEqual(run.recovery_state, state)
        self.assertEqual(base.stat().st_mode & 0o777, 0o700)
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        for attribute in ("recovery_directory", "recovery_state"):
            with self.assertRaises(AttributeError):
                setattr(run, attribute, self.root)
        message = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn("TEST-SECRET", message)
        self.assertIn("recovery_directory", message)
        self.assertIn("manual", message)
        run.__exit__(None, None, None)
        self.assertTrue(state.exists(), "repeated cleanup deleted recovery state")
        with self.runner():
            pass  # Retaining staging must not retain the controller lock.

    def test_active_recovery_gate_fails_closed_without_unlocking(self):
        import src.python.terraform_runner as module
        for kind in ("absent", "present", "unknown"):
            with self.subTest(kind=kind):
                run = self.runner()
                self.assertTrue(callable(getattr(run, "assert_no_recovery", None)),
                                "cleanup needs an active-context recovery gate")
                with self.assertRaises(module.TerraformRunnerError):
                    run.assert_no_recovery()
                real_stat = os.stat

                def inspect(path, *args, **kwargs):
                    if kind == "unknown" and path == "errored.tfstate":
                        raise PermissionError("SYNTHETIC-PRIVATE")
                    return real_stat(path, *args, **kwargs)

                base = marker = None
                with patch.object(module.os, "stat", side_effect=inspect):
                    try:
                        with run:
                            base = run.staged_root.parent
                            self.addCleanup(shutil.rmtree, base, ignore_errors=True)
                            marker = run.staged_root / "errored.tfstate"
                            if kind == "present":
                                marker.write_bytes(b"SYNTHETIC-RECOVERY")
                            if kind == "absent":
                                self.assertIsNone(run.assert_no_recovery())
                            else:
                                with self.assertRaises(module.TerraformRunnerError) as raised:
                                    run.assert_no_recovery()
                                self.assertNotIn("SYNTHETIC", str(raised.exception))
                                self.assertEqual(run.recovery_directory, base)
                            with self.assertRaises(module.TerraformLockError):
                                with self.runner():
                                    self.fail("recovery gate released the controller lock")
                    except module.TerraformRunnerError:
                        self.assertNotEqual(kind, "absent")
                assert base is not None and marker is not None
                self.assertEqual(base.exists(), kind != "absent")
                if kind == "present":
                    self.assertEqual(marker.read_bytes(), b"SYNTHETIC-RECOVERY")
                with self.assertRaises(module.TerraformRunnerError):
                    run.assert_no_recovery()

    def test_recovery_gate_uncertainty_is_not_cleared_by_later_absence(self):
        import src.python.terraform_runner as module
        run = self.runner()
        base = None
        with self.assertRaises(module.TerraformRunnerError):
            with run:
                base = run.staged_root.parent
                self.addCleanup(shutil.rmtree, base, ignore_errors=True)
                real_stat = os.stat

                def uncertain(path, *args, **kwargs):
                    if path == "errored.tfstate":
                        raise PermissionError("SYNTHETIC-PRIVATE")
                    return real_stat(path, *args, **kwargs)

                with patch.object(module.os, "stat", side_effect=uncertain):
                    run.assert_no_recovery()
        assert base is not None
        self.assertTrue(base.is_dir(), "uncertain recovery must remain retained after the gate raises")
        self.assertEqual(run.recovery_directory, base)

    def test_recovery_cleanup_never_follows_replaced_staging_directory(self):
        from src.python.terraform_runner import TerraformRunnerError
        outside = self.root / "outside"
        outside.mkdir()
        state = outside / "errored.tfstate"
        state.write_bytes(b"TEST-SECRET")
        state.chmod(0o644)
        run = self.runner()
        with self.assertRaises(TerraformRunnerError):
            with run:
                base = run.staged_root.parent
                self.addCleanup(shutil.rmtree, base, ignore_errors=True)
                run.staged_root.rename(base / "original-source")
                run.staged_root.symlink_to(outside, target_is_directory=True)
                raise TerraformRunnerError("Synthetic failure")
        self.assertEqual(state.stat().st_mode & 0o777, 0o644, "followed a staging symlink")
        self.assertEqual(run.recovery_directory, base)
        self.assertTrue((base / "original-source").exists())
        with self.runner():
            pass

    def test_recovery_survives_timeout_cancellation_and_interrupt(self):
        import src.python.terraform_runner as module
        for reason in ("timeout", "cancel", "interrupt"):
            with self.subTest(reason=reason):
                cancel = threading.Event()
                run = self.runner(cancel_event=cancel, command_timeout=1)
                expected = module.TerraformTimeout if reason == "timeout" else module.TerraformCancelled
                calls = 0
                def communicate(**kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        if reason == "interrupt":
                            raise KeyboardInterrupt()
                        if reason == "cancel":
                            cancel.set()
                        raise subprocess.TimeoutExpired("synthetic", 0.05)
                    # Simulate Terraform flushing recovery during termination.
                    (run.staged_root / "errored.tfstate").write_bytes(b"TEST-SECRET")
                    return b"TEST-SECRET", b"TEST-SECRET"
                with self.assertRaises(expected) as raised:
                    with run:
                        self.addCleanup(shutil.rmtree, run.staged_root.parent, ignore_errors=True)
                        run.init()  # Existing, disposable provider-free fixture.
                        process = Mock(pid=987654)
                        process.communicate.side_effect = communicate
                        with patch.object(module.subprocess, "Popen", return_value=process), \
                                patch.object(module.os, "killpg") as kill, \
                                patch.object(module.time, "monotonic", side_effect=[0, 0, 2]):
                            run.output()
                self.assertEqual(run.recovery_state.read_bytes(), b"TEST-SECRET")
                self.assertEqual([call.args for call in kill.call_args_list],
                                 [(987654, signal.SIGTERM), (987654, signal.SIGKILL)])
                message = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn("TEST-SECRET", message)
                self.assertIn("recovery_directory", message)
                with self.runner():
                    pass

    def test_recovery_unknown_or_unsafe_marker_retains_original_directory(self):
        import src.python.terraform_runner as module
        for kind in ("symlink", "dangling", "directory", "fifo", "unknown", "unreadable", "chmod"):
            with self.subTest(kind=kind):
                run = self.runner()
                outside = self.root / "outside-state"
                outside.write_bytes(b"TEST-SECRET")
                outside.chmod(0o644)
                real_stat, real_open, real_chmod = os.stat, os.open, os.fchmod
                def inspect(path, *args, **kwargs):
                    if kind == "unknown" and path == "errored.tfstate":
                        raise PermissionError("TEST-SECRET")
                    return real_stat(path, *args, **kwargs)
                def open_file(path, *args, **kwargs):
                    if kind == "unreadable" and path == "errored.tfstate":
                        raise PermissionError("TEST-SECRET")
                    return real_open(path, *args, **kwargs)
                def chmod(fd, mode):
                    if kind == "chmod" and mode == 0o600:
                        raise PermissionError("TEST-SECRET")
                    return real_chmod(fd, mode)
                with patch.object(module.os, "stat", side_effect=inspect), \
                        patch.object(module.os, "open", side_effect=open_file), \
                        patch.object(module.os, "fchmod", side_effect=chmod):
                    with self.assertRaises(module.TerraformRunnerError) as raised:
                        with run:
                            base = run.staged_root.parent
                            self.addCleanup(shutil.rmtree, base, ignore_errors=True)
                            state = run.staged_root / "errored.tfstate"
                            if kind in ("symlink", "dangling"):
                                state.symlink_to(outside if kind == "symlink" else self.root / "absent")
                            elif kind == "directory":
                                state.mkdir()
                            elif kind == "fifo":
                                os.mkfifo(state)
                            elif kind != "unknown":
                                state.write_bytes(b"TEST-SECRET")
                            # Even normal context exit must report retained recovery.
                self.assertTrue(base.exists())
                self.assertEqual(run.recovery_directory, base)
                self.assertEqual(run.recovery_state, state)
                self.assertEqual(outside.stat().st_mode & 0o777, 0o644)
                self.assertNotIn("TEST-SECRET", "".join(traceback.format_exception(raised.exception)))
                with self.runner():
                    pass

    def test_absent_recovery_cleans_success_and_json_or_command_failure(self):
        from src.python.terraform_runner import TerraformRunnerError
        for result in ("success", "json", "failure"):
            with self.subTest(result=result):
                run = self.runner()
                self.assertIsNone(run.recovery_directory)
                self.assertIsNone(run.recovery_state)
                try:
                    with run:
                        run.init()
                        process = Mock(returncode=1 if result == "failure" else 0)
                        process.communicate.return_value = (b"{}" if result == "success" else b"TEST-SECRET", b"")
                        with patch("src.python.terraform_runner.subprocess.Popen", return_value=process):
                            run.output()
                except TerraformRunnerError as error:
                    self.assertNotEqual(result, "success")
                    self.assertNotIn("TEST-SECRET", str(error))
                else:
                    self.assertEqual(result, "success")
                self.assertFalse(run.staged_root.parent.exists())
                self.assertIsNone(run.recovery_directory)
                self.assertIsNone(run.recovery_state)

    def test_local_lock_info_symlink_is_rejected_before_terraform(self):
        from src.python.terraform_runner import TerraformRunnerError
        with self.runner() as run:
            lock_info = run.local_state_path.parent / "..tfstate.lock.info"
            lock_info.symlink_to(self.root / "outside-lock-info")
            with patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                process = spawn.return_value
                process.returncode = 0
                process.communicate.return_value = (b'{"terraform_version":"1.8.5"}', b"")
                with self.assertRaises(TerraformRunnerError):
                    run.init()
                spawn.assert_not_called()

    def test_controller_lock_coordinates_independent_python_processes(self):
        options = {key: str(value) if isinstance(value, Path) else value
                   for key, value in self.options.items() if key != "backend_spec"}
        script = f'''from src.python.terraform_runner import TerraformRunner, TerraformLockError
from src.python.terraform_backend import BackendSpec
try:
    with TerraformRunner(**{options!r}, backend_spec=BackendSpec.from_dict({{}}, cloud="aws")):
        print("opened")
except TerraformLockError:
    print("locked")
'''
        def probe():
            result = subprocess.run([sys.executable, "-B", "-c", script],
                                    cwd=Path(__file__).resolve().parents[2],
                                    env=self.options["environment"], capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0, "independent lock probe failed")
            return result.stdout.strip()
        with self.runner():
            self.assertEqual(probe(), b"locked")
        self.assertEqual(probe(), b"opened")

    def test_two_cloud_contexts_overlap_without_state_variables_or_data_crossover(self):
        with (self.source / "main.tf").open("a") as stream:
            stream.write('variable "approved" { type = string }\noutput "approved" { value = var.approved }\n')
        barrier = threading.Barrier(2)
        def operate(cloud, scope):
            spec = BackendSpec.from_dict({}, cloud=cloud)
            with self.runner(backend_spec=spec, target_scope=scope, deployment_name=cloud,
                             variables={"approved": cloud}) as run:
                barrier.wait(timeout=3)
                run.init()
                run.apply(run.plan(), acknowledge_mutation=True)
                result = run.output()["approved"]["value"]
                self.assertFalse(run.plan().has_changes)
                run.destroy(acknowledge_mutation=True)
                return result, run.data_dir, run.local_state_path
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(operate, "aws", "123456789012")
            second = pool.submit(operate, "gcp", "target-project")
            a, b = first.result(timeout=5), second.result(timeout=5)
        self.assertEqual((a[0], b[0]), ("aws", "gcp"))
        self.assertNotEqual(a[1], b[1])
        self.assertNotEqual(a[2], b[2])
        self.assertFalse(a[1].exists())
        self.assertFalse(b[1].exists())

    def test_keyboard_interrupt_during_command_cleans_group(self):
        from src.python.terraform_runner import TerraformCancelled
        with self.runner() as run:
            run.init()
            with patch("src.python.terraform_runner.subprocess.Popen") as spawn, \
                    patch("src.python.terraform_runner.os.killpg") as kill:
                process = spawn.return_value
                process.pid = 987654
                process.communicate.side_effect = [KeyboardInterrupt(), (b"TEST-SECRET", b"TEST-SECRET"), (b"", b"")]
                with self.assertRaises(TerraformCancelled):
                    run.output()
                self.assertEqual([call.args for call in kill.call_args_list],
                                 [(987654, signal.SIGTERM), (987654, signal.SIGKILL)])
        with self.runner():
            pass

    def test_staging_failure_cleans_partial_directory_and_releases_lock(self):
        from src.python.terraform_runner import TerraformRunnerError
        run = self.runner()
        with patch("src.python.terraform_runner._private_write", side_effect=OSError("TEST-SECRET")):
            with self.assertRaises(TerraformRunnerError) as raised:
                with run:
                    self.fail("staging failure was hidden")
        self.assertNotIn("TEST-SECRET", "".join(traceback.format_exception(raised.exception)))
        self.assertFalse(run.staged_root.exists())
        with self.runner():
            pass

    def test_init_preserves_explicit_provider_lockfile(self):
        (self.source / ".terraform.lock.hcl").write_text("# Vetted provider-free fixture lock\n")
        files = ["main.tf", "modules/nested/main.tf", ".terraform.lock.hcl"]
        with self.runner(source_files=files) as run:
            real_popen = subprocess.Popen
            with patch("src.python.terraform_runner.subprocess.Popen", wraps=real_popen) as spawn:
                run.init()
                init_args = spawn.call_args.args[0]
                self.assertIn("-lockfile=readonly", init_args)
                self.assertIn("-lock-timeout=120s", init_args)
            self.assertEqual((run.staged_root / ".terraform.lock.hcl").read_text(),
                             "# Vetted provider-free fixture lock\n")

    def test_invalid_execution_options_fail_before_any_staging_or_spawn(self):
        from src.python.terraform_runner import TerraformRunnerError
        invalid = [{"command_timeout": value} for value in (0, -1, True, float("nan"), float("inf"), "1")]
        invalid += [{"controller_lock_timeout": value} for value in (-1, True, float("nan"), "1")]
        invalid += [{"source_files": []}, {"source_files": ["main.tf", "main.tf"]},
                    {"variables": {"bad-name;": "TEST-SECRET"}},
                    {"variables": {"key": float("nan")}}, {"terraform_binary": ""},
                    {"environment": {"PATH": "TEST-SECRET\0"}}, {"lock_root": "relative"}]
        for changes in invalid:
            with self.subTest(changes=changes), patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                with self.assertRaises(TerraformRunnerError) as raised:
                    self.runner(**changes)
                self.assertNotIn("TEST-SECRET", str(raised.exception))
                spawn.assert_not_called()

    def test_explicit_durable_staging_retains_publication_recovery(self):
        from src.python.terraform_runner import TerraformRunnerError
        durable = self.root / 'durable-operations'
        self.assertIn('staging_root', __import__('inspect').signature(type(self.runner())).parameters)
        run = self.runner(staging_root=durable)
        with self.assertRaises(TerraformRunnerError):
            with run:
                run.init()
                run.apply(run.plan(), acknowledge_mutation=True)
                run.retain_recovery()
        self.assertTrue(run.recovery_directory.is_relative_to(durable))
        self.assertTrue(run.recovery_directory.exists())
        self.assertEqual(durable.stat().st_mode & 0o777, 0o700)
        self.assertEqual(run.recovery_directory.stat().st_mode & 0o777, 0o700)

    def test_failed_gcs_apply_keeps_durable_operation_evidence_without_state_marker(self):
        from src.python.terraform_runner import TerraformRunnerError, SavedPlan
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        run = self.runner(backend_spec=spec, target_scope='target-project', remote_guard=Mock(),
                          staging_root=self.root / 'durable-operations')
        # Native subprocess errors are unavoidable doubles; keep context/source/plan verification real.
        with self.assertRaises(TerraformRunnerError), run:
            def execute(argv, **kwargs):
                if argv[0] == 'version':
                    return 0, b'{"terraform_version":"1.10.0"}'
                (run.data_dir / 'terraform.tfstate').write_text(json.dumps({'backend': {
                    'type': 'gcs', 'config': spec.backend_config('target-project', 'fixture')}}))
                return 0, b''
            with patch.object(run, '_execute', side_effect=execute):
                run.init()
            plan_file = run.staged_root.parent / 'saved.tfplan'
            plan_file.write_bytes(b'private-plan')
            run._plan = SavedPlan(True, plan_file, __import__('hashlib').sha256(b'private-plan').hexdigest())
            with patch.object(run, '_execute', side_effect=TerraformRunnerError('uncertain apply')), \
                 self.assertRaises(TerraformRunnerError):
                run.apply(run._plan, acknowledge_mutation=True)
            self.assertIsNotNone(run.recovery_directory, 'uncertain apply must retain evidence')
        self.assertTrue(run.recovery_directory.exists())

    def test_gcs_exact_saved_plan_uses_live_guard_and_native_locking(self):
        from src.python.terraform_runner import TerraformRunnerError
        spec = BackendSpec.from_dict({'backend': 'gcs', 'namespace': 'tests', 'destination': {
            'bucket': 'example-state', 'project': 'backend-project', 'prefix': 'state'}}, cloud='gcp')
        guard = Mock()
        self.assertIn('remote_guard', __import__('inspect').signature(type(self.runner())).parameters)
        with self.runner(backend_spec=spec, target_scope='target-project', remote_guard=guard) as run:
            def execute(argv, **kwargs):
                if argv[0] == 'version':
                    return 0, b'{"terraform_version":"1.10.0"}'
                if argv[0] == 'init':
                    (run.data_dir / 'terraform.tfstate').write_text(json.dumps({'backend': {
                        'type': 'gcs', 'config': spec.backend_config('target-project', 'fixture')}}))
                if argv[0] == 'plan':
                    Path(next(a[5:] for a in argv if a.startswith('-out='))).write_bytes(b'exact-plan')
                    return 2, b''
                if argv[0] == 'apply':
                    self.assertIn('-lock-timeout=120s', argv)
                    self.assertEqual(Path(argv[-1]).read_bytes(), b'exact-plan')
                    self.assertEqual(guard.call_args.args, (run, 'apply'))
                return 0, b'{}'
            with patch.object(run, '_execute', side_effect=execute):
                run.init()
                self.assertEqual(guard.call_args_list, [mock_call(run, 'pre-init'), mock_call(run, 'init')])
                plan = run.plan()
                run.apply(plan, acknowledge_mutation=True)
                with self.assertRaises(TerraformRunnerError):
                    run.apply(plan, acknowledge_mutation=True)

    def test_remote_adapters_are_mocked_and_mutation_remains_gated(self):
        from src.python.terraform_runner import TerraformRunnerError, TerraformLockError
        uuid = "11111111-1111-1111-1111-111111111111"
        cases = [
            ("aws", "123456789012", {"backend": "s3", "namespace": "tests", "destination": {
                "bucket": "example-state", "region": "us-east-1", "owner_account_id": "123456789012",
                "key_prefix": "isaacautomator/v2"}}),
            ("gcp", "target-project", {"backend": "gcs", "namespace": "tests", "destination": {
                "bucket": "example-state", "project": "backend-project", "prefix": "isaacautomator/v2"}}),
            ("azure", uuid, {"backend": "azurerm", "namespace": "tests", "destination": {
                "tenant_id": uuid, "subscription_id": uuid, "resource_group_name": "backend-rg",
                "storage_account_name": "examplestate", "container_name": "tfstate", "key_prefix": "isaacautomator/v2"}})]
        def fake_terraform(argv, **kwargs):
            if argv[1] == "version":
                raw, code = b'{"terraform_version":"1.10.0"}', 0
            elif argv[1] == "init":
                (run.data_dir / "terraform.tfstate").write_text(json.dumps({"backend": {
                    "type": spec.backend, "config": spec.backend_config(scope, "fixture")}}))
                raw, code = b"{}", 0
            elif argv[1] == "plan":
                path = Path(next(arg[len("-out="):] for arg in argv if arg.startswith("-out=")))
                path.write_bytes(b"MOCK-REMOTE-PLAN")
                raw, code = b"TEST-SECRET", 2
            else:
                raw, code = b"{}", 0
            process = Mock(returncode=code)
            process.communicate.return_value = (raw, b"TEST-SECRET")
            return process
        for cloud, scope, data in cases:
            with self.subTest(backend=data["backend"]):
                spec = BackendSpec.from_dict(data, cloud=cloud)
                with self.runner(backend_spec=spec, target_scope=scope) as run:
                    self.assertIsNone(run.local_state_path)
                    self.assertEqual(run.backend_identity, json.dumps(spec.identity(scope, "fixture"),
                                                                      sort_keys=True, separators=(",", ":")))
                    with self.assertRaises(TerraformLockError):
                        with self.runner(backend_spec=spec, target_scope=scope):
                            self.fail("same remote identity was opened twice")
                    expected = "\n".join(f"{key} = {json.dumps(value)}" for key, value in
                                         sorted(spec.backend_config(scope, "fixture").items()))
                    self.assertEqual((run.staged_root.parent / "backend.hcl").read_text(), expected)
                    with patch("src.python.terraform_runner.subprocess.Popen", side_effect=fake_terraform) as spawn:
                        run.init()
                        plan = run.plan()
                        self.assertTrue(plan.has_changes)
                        self.assertEqual(run.output(), {})
                        count = spawn.call_count
                        for action in (lambda: run.apply(plan, acknowledge_mutation=True),
                                       lambda: run.destroy(acknowledge_mutation=True)):
                            with self.assertRaisesRegex(TerraformRunnerError, "remote|Remote"):
                                action()
                        self.assertEqual(spawn.call_count, count)
                        for call in spawn.call_args_list:
                            argv = call.args[0]
                            self.assertIsInstance(argv, list)
                            self.assertFalse(call.kwargs["shell"])
                            for flag in ("-upgrade", "-reconfigure", "-migrate-state", "-lock=false"):
                                self.assertNotIn(flag, argv)
                            self.assertNotIn("TEST-SECRET", repr(argv))
                with self.runner(backend_spec=spec, target_scope=scope) as run, \
                        patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                    process = spawn.return_value
                    process.returncode = 0
                    process.communicate.return_value = (b'{"terraform_version":"1.8.5"}', b"")
                    with self.assertRaisesRegex(TerraformRunnerError, "Unsupported Terraform version"):
                        run.init()
                    self.assertEqual(spawn.call_count, 1, "old binary must not initialize a remote backend")

    def test_context_requires_init_and_rejects_reuse_or_changed_files(self):
        from src.python.terraform_runner import TerraformRunnerError
        run = self.runner()
        with patch("src.python.terraform_runner.subprocess.Popen") as spawn:
            for action in (run.init, run.plan, run.output,
                           lambda: run.destroy(acknowledge_mutation=True)):
                with self.assertRaises(TerraformRunnerError):
                    action()
            spawn.assert_not_called()
        with run:
            with self.assertRaises(TerraformRunnerError):
                run.output()
            run.init()
            with self.assertRaises(TerraformRunnerError):
                run.init()
            for path in (run.staged_root / "runner_override.tf.json",
                         run.staged_root / "main.tf",
                         run.staged_root.parent / "backend.hcl",
                         run.staged_root.parent / "inputs.tfvars.json",
                         run.data_dir / "terraform.tfstate"):
                original = path.read_bytes()
                path.write_bytes(b"TEST-SECRET changed context")
                with self.assertRaises(TerraformRunnerError):
                    run.output()
                path.write_bytes(original)
            with self.assertRaises(AttributeError):
                run.staged_root = self.source
            with self.assertRaises(AttributeError):
                run.data_dir = self.source
            self.assertEqual(run.output(), {})
        with self.assertRaises(TerraformRunnerError):
            run.output()
        with self.assertRaises(TerraformRunnerError):
            with run:
                self.fail("single-use context reused")

    def test_timeout_and_cancellation_reap_process_groups_and_release_lock(self):
        import src.python.terraform_runner as module
        self.assertTrue(hasattr(module, "TerraformTimeout"), "timeout must have a sanitized error type")
        for cancel_requested in (False, True):
            with self.subTest(cancel=cancel_requested):
                pid_file = self.root / ("cancel.pid" if cancel_requested else "timeout.pid")
                executable = self.root / "blocking-terraform"
                executable.write_text(f'''#!{sys.executable}
import os, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"])
with open({str(pid_file)!r}, "w") as stream:
    stream.write(str(child.pid))
print("TEST-SECRET", flush=True)
print("TEST-SECRET", file=sys.stderr, flush=True)
time.sleep(60)
''')
                executable.chmod(0o700)
                cancel = threading.Event()
                timer = threading.Timer(0.2, cancel.set)
                processes = []
                real_popen = subprocess.Popen
                def spawn(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    processes.append(process)
                    return process
                try:
                    if cancel_requested:
                        timer.start()
                    expected = module.TerraformCancelled if cancel_requested else module.TerraformTimeout
                    with self.assertRaises(expected) as raised:
                        with self.runner(terraform_binary=str(executable), cancel_event=cancel,
                                         command_timeout=3 if cancel_requested else 0.2) as run:
                            stage = run.staged_root
                            with patch.object(module.subprocess, "Popen", side_effect=spawn):
                                run.init()
                    self.assertNotIn("TEST-SECRET", "".join(traceback.format_exception(raised.exception)))
                    self.assertFalse(stage.exists())
                    self.assertIsNotNone(processes[0].returncode)
                    child_pid = int(pid_file.read_text())
                    for _ in range(100):
                        status = Path(f"/proc/{child_pid}/stat")
                        if not status.exists() or status.read_text().split()[2] == "Z":
                            break
                        time.sleep(0.01)
                    else:
                        self.fail("Terraform descendant survived process-group cleanup")
                    with self.runner():
                        pass
                finally:
                    timer.cancel()
                    # Even a RED regression may never leak the test's processes.
                    for process in processes:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.communicate(timeout=3)

    def test_failures_and_malformed_json_never_expose_provider_diagnostics(self):
        from src.python.terraform_runner import TerraformRunnerError
        with self.runner() as run:
            run.init()
            for raw in (b"TEST-SECRET", b'"TEST-SECRET"', b'["TEST-SECRET"]',
                        b'{"answer":"TEST-SECRET"}', b'{"answer":{"value":"TEST-SECRET"}}'):
                with self.subTest(raw=raw), patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                    process = spawn.return_value
                    process.communicate.return_value = (raw, b"TEST-SECRET")
                    process.returncode = 0
                    with self.assertRaises(TerraformRunnerError) as raised:
                        run.output()
                    self.assertNotIn("TEST-SECRET", "".join(traceback.format_exception(raised.exception)))
            with patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                process = spawn.return_value
                process.communicate.return_value = (b"TEST-SECRET", b"TEST-SECRET")
                process.returncode = 1
                with self.assertRaises(TerraformRunnerError) as raised:
                    run.output()
                self.assertNotIn("TEST-SECRET", repr(raised.exception))
            with patch("src.python.terraform_runner.subprocess.Popen", side_effect=OSError("TEST-SECRET")):
                with self.assertRaises(TerraformRunnerError) as raised:
                    run.output()
                self.assertNotIn("TEST-SECRET", "".join(traceback.format_exception(raised.exception)))
        for raw in (b"TEST-SECRET", b"{}", b'{"terraform_version":"TEST-SECRET"}'):
            with self.runner() as run, patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                process = spawn.return_value
                process.communicate.return_value = (raw, b"TEST-SECRET")
                process.returncode = 0
                with self.assertRaises(TerraformRunnerError) as raised:
                    run.init()
                self.assertNotIn("TEST-SECRET", "".join(traceback.format_exception(raised.exception)))
                self.assertEqual(spawn.call_count, 1)

    def test_context_lock_keys_exact_local_path_and_releases_on_exception(self):
        from src.python.terraform_runner import TerraformLockError, TerraformCancelled
        with self.runner() as first:
            alias = BackendSpec.from_dict({"namespace": "different"}, cloud="gcp")
            with self.assertRaises(TerraformLockError):
                with self.runner(backend_spec=alias, target_scope="target-project"):
                    self.fail("same absolute local state was concurrently opened")
            with self.runner(deployment_name="other") as other:
                self.assertNotEqual(first.data_dir, other.data_dir)
                self.assertNotEqual(first.local_state_path, other.local_state_path)
            with self.runner(state_root=self.root / "another-state"):
                pass
            cancel_wait = threading.Event()
            timer = threading.Timer(0.02, cancel_wait.set)
            timer.start()
            try:
                with self.assertRaises(TerraformCancelled):
                    with self.runner(cancel_event=cancel_wait):
                        self.fail("cancelled lock waiter entered")
            finally:
                timer.cancel()
            with self.assertRaises(TerraformLockError):
                with self.runner():
                    self.fail("cancelled waiter released another context's lock")
        with self.assertRaises(KeyboardInterrupt):
            with self.runner():
                raise KeyboardInterrupt()
        with self.runner():
            pass
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(TerraformCancelled):
            with self.runner(cancel_event=cancel):
                self.fail("cancelled operation acquired lock")
        with self.runner():
            pass

    def test_apply_requires_acknowledged_unchanged_context_owned_plan(self):
        from src.python.terraform_runner import TerraformRunnerError, SavedPlan
        with self.runner() as run:
            run.init()
            plan = run.plan()
            with patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                for acknowledgement in (False, "yes", 1):
                    with self.assertRaises(TerraformRunnerError):
                        run.apply(plan, acknowledge_mutation=acknowledgement)
                    with self.assertRaises(TerraformRunnerError):
                        run.destroy(acknowledge_mutation=acknowledgement)
                with self.assertRaises(TerraformRunnerError):
                    run.apply(SavedPlan(True, self.root / "other"), acknowledge_mutation=True)
                spawn.assert_not_called()
            original = plan.path.read_bytes()
            plan.path.write_bytes(b"TEST-SECRET-tampered-plan")
            with self.assertRaises(TerraformRunnerError):
                run.apply(plan, acknowledge_mutation=True)
            plan.path.unlink()
            outside = self.root / "other.tfplan"
            outside.write_bytes(original)
            plan.path.symlink_to(outside)
            with self.assertRaises(TerraformRunnerError):
                run.apply(plan, acknowledge_mutation=True)
            plan.path.unlink()
            plan.path.write_bytes(original)
            run.apply(plan, acknowledge_mutation=True)
            with self.assertRaises(TerraformRunnerError):
                run.apply(plan, acknowledge_mutation=True)
            run.destroy(acknowledge_mutation=True)

    def test_explicit_variables_and_environment_cannot_inject_cli(self):
        from src.python.terraform_runner import TerraformRunnerError
        marker = self.root / "NEVER-CREATED"
        value = f'$(touch {marker}); "TEST-SECRET"'
        with (self.source / "main.tf").open("a") as stream:
            stream.write('variable "approved" { type = string }\noutput "approved" { value = var.approved }\n')
        env = {**self.options["environment"], "TF_CLI_ARGS": "-lock=false -upgrade",
               "TF_CLI_ARGS_plan": "-destroy", "TF_DATA_DIR": "/do/not/use",
               "TF_VAR_approved": "WRONG", "TF_LOG": "TRACE", "TF_LOG_PATH": str(marker),
               "TF_PLUGIN_CACHE_DIR": "/do/not/use", "TF_REATTACH_PROVIDERS": "TEST-SECRET",
               "TF_CLI_CONFIG_FILE": "/do/not/use", "HTTPS_PROXY": "http://approved.invalid"}
        variables = {"approved": value}
        with self.runner(environment=env, variables=variables) as run:
            variables["approved"] = "changed-after-construction"
            run.init()
            plan = run.plan()
            run.apply(plan, acknowledge_mutation=True)
            self.assertEqual(run.output()["approved"]["value"], value)
            self.assertFalse(marker.exists())
            with patch("src.python.terraform_runner.subprocess.Popen") as spawn:
                process = spawn.return_value
                process.communicate.return_value = (b"{}", b"")
                process.returncode = 0
                run.output()
                args, kwargs = spawn.call_args
                self.assertEqual(args[0][1:], ["output", "-json", "-no-color"])
                self.assertFalse(kwargs["shell"])
                self.assertTrue(kwargs["start_new_session"])
                self.assertEqual(kwargs["env"]["TF_DATA_DIR"], str(run.data_dir))
                self.assertEqual(kwargs["env"]["HTTPS_PROXY"], env["HTTPS_PROXY"])
                self.assertFalse(any(k.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG")) for k in kwargs["env"]))
                self.assertNotIn("TF_PLUGIN_CACHE_DIR", kwargs["env"])
                self.assertNotIn("TF_REATTACH_PROVIDERS", kwargs["env"])
                self.assertNotEqual(kwargs["env"]["TF_CLI_CONFIG_FILE"], env["TF_CLI_CONFIG_FILE"])
            run.destroy(acknowledge_mutation=True)
        with self.assertRaises(TerraformRunnerError):
            with self.runner(environment={"TF_WORKSPACE": "unexpected"}):
                self.fail("unexpected workspace accepted")

    def test_local_state_rejects_escape_and_identity_is_read_only(self):
        from src.python.terraform_runner import TerraformRunnerError
        for changes in ({"deployment_name": "../escaped"}, {"deployment_name": "/tmp/escaped"},
                        {"state_root": None}, {"state_root": "relative"},
                        {"state_root": self.root / "state/../escaped"}):
            with self.subTest(changes=changes):
                with self.assertRaises((TerraformRunnerError, ValueError)):
                    with self.runner(**changes):
                        self.fail("unsafe state path accepted")
        actual = self.root / "actual"
        actual.mkdir()
        link = self.root / "link"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(TerraformRunnerError):
            with self.runner(state_root=link):
                self.fail("symlink state root accepted")
        state_dir = self.root / "state/fixture"
        state_dir.mkdir(parents=True)
        (state_dir / ".tfstate").symlink_to(actual / "outside")
        with self.assertRaises(TerraformRunnerError):
            with self.runner():
                self.fail("symlink state accepted")
        (state_dir / ".tfstate").unlink()
        with self.runner() as run:
            with self.assertRaises(AttributeError):
                run.local_state_path = actual / ".tfstate"
            with self.assertRaises(AttributeError):
                run.backend_identity = "other"
            self.assertIsInstance(run.backend_identity, str)
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)

    def test_selected_sources_are_immutable_before_lock_acquisition(self):
        for replacement in ("file", "ancestor"):
            with self.subTest(replacement=replacement):
                selected = self.root / replacement
                selected.mkdir()
                source = selected / "main.tf"
                source.write_bytes(b"APPROVED-SYNTHETIC")
                outside = self.root / (replacement + "-outside")
                outside.mkdir()
                (outside / "main.tf").write_bytes(b"UNAPPROVED-SYNTHETIC")
                run = self.runner(source_root=selected, source_files=["main.tf"])
                # Approval binds to construction, not a later lock wait.
                source.write_bytes(b"CHANGED-AFTER-SELECTION")
                acquire = run._acquire_lock

                def replace_after_lock():
                    acquire()
                    if replacement == "file":
                        source.unlink()
                        source.symlink_to(outside / "main.tf")
                    else:
                        selected.rename(self.root / (replacement + "-original"))
                        selected.symlink_to(outside, target_is_directory=True)

                with patch.object(run, "_acquire_lock", side_effect=replace_after_lock), run:
                    self.assertEqual((run.staged_root / "main.tf").read_bytes(), b"APPROVED-SYNTHETIC")

    def test_source_snapshot_rejects_links_or_reads_pinned_ancestor(self):
        from src.python.terraform_runner import TerraformRunnerError
        for race in ("final-link", "before-directory", "after-directory"):
            with self.subTest(race=race):
                selected = self.root / race
                selected.mkdir()
                source = selected / "main.tf"
                source.write_bytes(b"APPROVED-SYNTHETIC")
                outside = self.root / (race + "-outside")
                outside.mkdir()
                (outside / "main.tf").write_bytes(b"UNAPPROVED-SYNTHETIC")
                real_open = os.open
                swapped = False

                def replace_during_open(path, flags, *args, **kwargs):
                    nonlocal swapped
                    component = Path(path).name
                    boundary = selected.name if race == "before-directory" else "main.tf"
                    if component == boundary:
                        self.assertFalse(swapped)
                        self.assertTrue(flags & os.O_NOFOLLOW)
                        self.assertIsNotNone(kwargs.get("dir_fd"))
                        if race == "final-link":
                            source.unlink()
                            source.symlink_to(outside / "main.tf")
                        else:
                            selected.rename(self.root / (race + "-original"))
                            selected.symlink_to(outside, target_is_directory=True)
                        swapped = True
                    return real_open(path, flags, *args, **kwargs)

                run = None
                with patch("src.python.terraform_runner.os.open", side_effect=replace_during_open):
                    if race == "after-directory":
                        run = self.runner(source_root=selected, source_files=["main.tf"])
                    else:
                        with self.assertRaises(TerraformRunnerError) as raised:
                            self.runner(source_root=selected, source_files=["main.tf"])
                        self.assertNotIn(str(self.root), str(raised.exception))
                self.assertTrue(swapped, "synthetic source race must execute")
                if race == "after-directory":
                    assert run is not None
                    with run:
                        self.assertEqual((run.staged_root / "main.tf").read_bytes(), b"APPROVED-SYNTHETIC")

    def test_staging_rejects_non_source_paths_and_symlinks(self):
        from src.python.terraform_runner import TerraformRunnerError
        for name in (".terraform/private.tf", "state/private.tf", "credentials.tf",
                     "terraform.tfstate", "x.auto.tfvars", "x.auto.tfvars.json",
                     "override.tf", "x_override.tf.json", ".env", "inventory.tf",
                     "../outside.tf", str(self.source / "main.tf")):
            with self.subTest(name=name):
                with self.assertRaises(TerraformRunnerError):
                    with self.runner(source_files=[name]):
                        self.fail("unsafe source was staged")
        (self.source / "link.tf").symlink_to(self.source / "main.tf")
        (self.source / "linked").symlink_to(self.source / "modules", target_is_directory=True)
        for name in ("link.tf", "linked/nested/main.tf"):
            with self.assertRaises(TerraformRunnerError):
                with self.runner(source_files=[name]):
                    self.fail("symlink was staged")
        # A source-only allowlist must not even inspect omitted operational data.
        (self.source / ".env").write_text("TEST-SECRET")
        with self.runner() as run:
            self.assertFalse((run.staged_root / ".env").exists())
            self.assertEqual((run.staged_root / "modules/nested/main.tf").read_text(),
                             (self.source / "modules/nested/main.tf").read_text())
            for path in run.staged_root.parent.rglob("*"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_real_local_state_survives_three_disposable_contexts(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.terraform_runner"),
                             "isolated Terraform runner must exist")
        expected = self.root / "state/fixture/.tfstate"
        with self.runner() as run:
            first_stage, first_data = run.staged_root, run.data_dir
            self.assertTrue(first_stage.is_relative_to(Path("/tmp")))
            self.assertFalse(first_stage.is_relative_to(self.source))
            self.assertEqual(run.local_state_path, expected)
            run.init()
            plan = run.plan()
            self.assertTrue(plan.has_changes)
            run.apply(plan, acknowledge_mutation=True)
            self.assertEqual(run.output()["answer"]["value"], "offline-persistent")
            self.assertTrue(expected.is_file())
            self.assertEqual(expected.stat().st_mode & 0o777, 0o600)
            self.assertEqual(plan.path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((run.staged_root / "terraform.tfstate").exists())
        self.assertFalse(first_stage.exists())
        self.assertFalse(first_data.exists())
        self.assertTrue(expected.is_file())
        with self.runner() as run:
            self.assertNotEqual(run.staged_root, first_stage)
            run.init()
            self.assertEqual(run.output()["answer"]["value"], "offline-persistent")
        with self.runner() as run:
            run.init()
            run.destroy(acknowledge_mutation=True)
            self.assertEqual(run.output(), {})
        state = json.loads(expected.read_text())
        self.assertEqual(state["resources"], [])
        self.assertEqual(state["outputs"], {})


if __name__ == "__main__":
    unittest.main()
