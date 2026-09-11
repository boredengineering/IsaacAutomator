"""Local issuer tests: disposable synthetic plans/secrets; no credentials/cloud."""
import importlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


class LocalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix="local-approval-")
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "issuer"

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("src.python.drift_approval"),
                             "local approval issuer is not implemented")
        return importlib.import_module("src.python.drift_approval")

    def test_initialization_requires_explicit_enable_and_private_durable_storage(self):
        api = self.api()
        with self.assertRaises(api.LocalApprovalError):
            api.LocalApprovalIssuer(self.path)
        self.assertFalse(self.path.exists())
        with self.assertRaises(api.LocalApprovalError):
            api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=False)
        self.assertFalse(self.path.exists())
        issuer = api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        self.assertEqual(issuer.principal, "local-uid-" + str(os.getuid()))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.path / "key").stat().st_mode & 0o777, 0o600)
        key = (self.path / "key").read_bytes()
        self.assertEqual(len(key), 32)
        self.assertNotIn(key.hex(), repr(issuer))
        api.LocalApprovalIssuer(self.path)
        self.assertEqual((self.path / "key").read_bytes(), key)
        with self.assertRaises(api.LocalApprovalError):
            api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        self.assertEqual((self.path / "key").read_bytes(), key)

    def binding(self) -> dict:
        from src.python.drift_report import digest
        principal = "local-uid-" + str(os.getuid())
        return dict(schema_version=1, proposal_id="fixture", deployment="synthetic",
            scope="workstation_infrastructure", baseline=dict(schema_version=1,
                source_revision="a" * 40, input_digest="b" * 64, lock_digest="c" * 64,
                source_digest="d" * 64, inputs_ref="synthetic", source_ref="synthetic", applied_at=1),
            plan_digest=digest("synthetic"), plan_json_digest="e" * 64,
            observation=dict(backend_digest="f" * 64, baseline_digest=digest(dict(schema_version=1,
                source_revision="a" * 40, input_digest="b" * 64, lock_digest="c" * 64,
                source_digest="d" * 64, inputs_ref="synthetic", source_ref="synthetic", applied_at=1)),
                lineage="synthetic-lineage", serial=1, properties_digest="1" * 64,
                coverage_digest="2" * 64, observed_at=100, complete=True),
            actions=[dict(address="terraform_data.synthetic", actions=["update"], **{"class": "desired_change"})],
            actor=principal, executor=principal, identity_role="workload", elevated=False,
            risks=[], incident="3" * 64, created_at=100)

    def saved(self, binding):
        import hashlib
        from src.python.terraform_runner import SavedPlan
        path = Path(self.root.name) / "synthetic.tfplan"
        path.write_bytes(b"SYNTHETIC-PRIVATE-PLAN-NOT-A-CREDENTIAL")
        path.chmod(0o600)
        binding["plan_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return SavedPlan(True, path, binding["plan_digest"])

    def tty_run(self, operation, response=True):
        """Real isolated controlling PTY; child writes only its nonsecret result."""
        import json
        import pty
        import select
        import time
        result_path = Path(self.root.name) / "child-result.json"
        result_path.unlink(missing_ok=True)
        pid, master = pty.fork()
        if pid == 0:
            try:
                result = {"ok": operation()}
            except Exception as error:
                result = {"error": type(error).__name__, "message": str(error)}
            temporary = result_path.with_suffix(".pending")
            temporary.write_text(json.dumps(result))
            temporary.replace(result_path)
            os._exit(0)
        transcript = b""
        sent = False
        deadline = time.monotonic() + 8
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    transcript += chunk
                    if b"Type: " in transcript and not sent:
                        line = transcript.split(b"Type: ", 1)[1].split(b"\r\n", 1)[0]
                        if b"\r\n" in transcript.split(b"Type: ", 1)[1]:
                            os.write(master, (line if response else b"yes") + b"\n")
                            sent = True
                if result_path.exists():
                    break
            if not result_path.exists():
                os.kill(pid, 9)
                self.fail("local review failed to terminate")
        finally:
            os.close(master)
            os.waitpid(pid, 0)
        return json.loads(result_path.read_text()), transcript.decode(errors="replace")

    def synthetic_tty(self):
        """Challenge echo in memory only; does not prove human/TTY authority."""
        from contextlib import contextmanager
        from io import StringIO
        @contextmanager
        def streams():
            output = StringIO()
            class Reader:
                def readline(self, limit):
                    return output.getvalue().split("Type: ", 1)[1].splitlines()[0] + "\n"
            yield Reader(), output
        return streams()

    def contended_issue(self, *, after_wait, ttl=120):
        """Advance a synthetic clock only once real final-lock contention occurs."""
        import fcntl
        import threading
        from unittest.mock import patch
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        now = [100]
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: now[0])
        binding = self.binding()
        saved = self.saved(binding)
        holder = os.open(self.path / "lock", os.O_RDWR)
        blocked = threading.Event()
        outcome = {}
        real_flock = fcntl.flock
        def review(receipt):
            real_flock(holder, fcntl.LOCK_EX)
            return receipt
        def flock(fd, operation):
            try:
                real_flock(fd, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                blocked.set()
                real_flock(fd, operation)
        def issue():
            try:
                outcome["ref"] = issuer.review_and_issue(
                    binding=binding, saved_plan=saved, review=review, ttl=ttl)
            except Exception as error:
                outcome["error"] = error
        with patch.object(issuer, "_tty", side_effect=self.synthetic_tty), \
                patch("src.python.drift_approval.fcntl.flock", side_effect=flock):
            worker = threading.Thread(target=issue, daemon=True)
            worker.start()
            try:
                self.assertTrue(blocked.wait(3), "final ledger lock did not contend")
                now[0] = after_wait
            finally:
                real_flock(holder, fcntl.LOCK_UN)
                worker.join(3)
                os.close(holder)
            self.assertFalse(worker.is_alive(), "issuance did not terminate")
        return issuer, outcome

    def test_final_ledger_lock_rechecks_expiry_before_persisting_receipt(self):
        import json
        issuer, outcome = self.contended_issue(after_wait=120, ttl=20)
        self.assertIsInstance(outcome.get("error"), self.api().LocalApprovalError, outcome)
        self.assertNotIn("ref", outcome)
        self.assertEqual(json.loads((self.path / "ledger").read_text())["records"], {})

    def test_final_ledger_lock_samples_issued_at_without_extending_expiry(self):
        issuer, outcome = self.contended_issue(after_wait=130)
        self.assertIn("ref", outcome, outcome)
        grant = issuer.verify(outcome["ref"])
        self.assertEqual(grant.issued_at, 130)
        self.assertEqual(grant.expires_at, 220)

    def test_final_ledger_lock_rechecks_observation_freshness(self):
        import json
        _, outcome = self.contended_issue(after_wait=161)
        self.assertIsInstance(outcome.get("error"), self.api().LocalApprovalError, outcome)
        self.assertNotIn("ref", outcome)
        self.assertEqual(json.loads((self.path / "ledger").read_text())["records"], {})

    def test_real_tty_review_issues_exact_binding_signed_verified_approval(self):
        from src.python.drift_report import digest
        from src.python.drift_remediation import VerifiedApproval
        api = self.api()
        self.assertTrue(hasattr(api.LocalApprovalIssuer, "review_and_issue"), "review flow is missing")
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        binding = self.binding()
        saved = self.saved(binding)
        def operation():
            issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
            def review(receipt):
                self.assertEqual(receipt.plan_digest, saved.digest)
                self.assertEqual(receipt.binding_digest, digest(binding))
                self.assertNotIn("SYNTHETIC-PRIVATE", repr(receipt))
                return receipt
            return issuer.review_and_issue(binding=binding, saved_plan=saved, review=review)
        result, transcript = self.tty_run(operation)
        self.assertIn("ok", result, result)
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        grant = issuer.verify(result["ok"])
        self.assertIsInstance(grant, VerifiedApproval)
        self.assertEqual(grant.binding_digest, digest(binding))
        self.assertEqual(grant.reviewer, issuer.principal)
        self.assertEqual(grant.executor, issuer.principal)
        self.assertEqual(grant.expires_at, 220)
        self.assertNotIn("SYNTHETIC-PRIVATE", transcript)
        self.assertNotIn("synthetic.tfplan", transcript)
        self.assertIn(binding["plan_digest"], transcript)
        self.assertIn(binding["baseline"]["input_digest"], transcript)
        self.assertIn(binding["observation"]["properties_digest"], transcript)

    def issue_fixture(self):
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        binding = self.binding()
        saved = self.saved(binding)
        result, _ = self.tty_run(lambda: api.LocalApprovalIssuer(self.path, clock=lambda: 100)
            .review_and_issue(binding=binding, saved_plan=saved))
        self.assertIn("ok", result, result)
        return api, binding, saved, result["ok"]

    def test_consumption_is_durable_fsynced_and_single_use_across_processes(self):
        import multiprocessing
        from unittest.mock import patch
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        self.assertTrue(hasattr(issuer, "consume"), "durable consumption is missing")
        self.assertFalse(issuer.consume(ref, "0" * 64))
        issuer.verify(ref)
        context = multiprocessing.get_context("fork")
        start, results = context.Event(), context.Queue()
        def race():
            start.wait(3)
            results.put(api.LocalApprovalIssuer(self.path, clock=lambda: 100)
                .consume(ref, digest(binding)))
        workers = [context.Process(target=race) for _ in range(4)]
        for worker in workers:
            worker.start()
        start.set()
        outcomes = [results.get(timeout=4) for _ in workers]
        for worker in workers:
            worker.join(4)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(outcomes.count(True), 1)
        self.assertFalse(api.LocalApprovalIssuer(self.path, clock=lambda: 100).consume(ref, digest(binding)))
        with self.assertRaises(api.LocalApprovalError):
            issuer.verify(ref)
        # A second fresh nonce is separately consumable, with file + dir fsync.
        fresh, _ = self.tty_run(lambda: issuer.review_and_issue(binding=binding, saved_plan=self.saved(binding)))
        self.assertIn("ok", fresh, fresh)
        with patch("src.python.drift_approval.os.fsync", wraps=os.fsync) as sync:
            self.assertTrue(issuer.consume(fresh["ok"], digest(binding)))
            self.assertGreaterEqual(sync.call_count, 2)

    def test_policy_changes_revoke_existing_grants_including_review_in_flight(self):
        from src.python.drift_report import digest
        api, binding, saved, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        self.assertTrue(hasattr(issuer, "set_policy"), "policy revocation is missing")
        issuer.set_policy(digest({"policy": "new"}))
        with self.assertRaises(api.LocalApprovalError):
            issuer.verify(ref)
        self.assertFalse(issuer.consume(ref, digest(binding)))
        fresh, _ = self.tty_run(lambda: issuer.review_and_issue(binding=binding, saved_plan=saved))
        self.assertIn("ok", fresh, fresh)
        issuer.set_policy(digest({"policy": "new"}))
        issuer.verify(fresh["ok"])
        def during_review():
            def review(receipt):
                api.LocalApprovalIssuer(self.path).set_policy(digest({"policy": "changed-during-review"}))
                return receipt
            return issuer.review_and_issue(binding=binding, saved_plan=saved, review=review)
        denied, _ = self.tty_run(during_review)
        self.assertEqual(denied.get("error"), "LocalApprovalError")
        issuer.revoke_all()
        with self.assertRaises(api.LocalApprovalError):
            issuer.verify(fresh["ok"])

    def test_low_level_revocation_before_epoch_capture_requires_pinned_epoch(self):
        import json
        from unittest.mock import patch
        from src.python.drift_report import digest
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        binding = self.binding()
        saved = self.saved(binding)
        real_receipt = issuer._review_receipt
        for pinned in (False, True):
            with self.subTest(pinned=pinned):
                epoch = issuer.set_policy(digest({"policy": "synthetic"}))
                calls = []
                def prepare_then_revoke(*args):
                    receipt = real_receipt(*args)
                    if not calls:
                        issuer.revoke_all()
                    calls.append(receipt)
                    return receipt
                with patch.object(issuer, "_review_receipt", side_effect=prepare_then_revoke), \
                        patch.object(issuer, "_tty", side_effect=self.synthetic_tty):
                    if pinned:
                        with self.assertRaises(api.LocalApprovalError):
                            issuer.review_and_issue(binding=binding, saved_plan=saved,
                                                    expected_policy_epoch=epoch)
                        self.assertEqual(json.loads((self.path / "ledger").read_text())["records"], {})
                    else:
                        # Without an earlier pin, the call starts from the NEW epoch.
                        ref = issuer.review_and_issue(binding=binding, saved_plan=saved)
                        issuer.verify(ref)
                        issuer.revoke_all()
                        self.assertFalse(issuer.consume(ref, digest(binding)))

    def test_revoke_all_after_epoch_capture_cancels_low_level_review(self):
        import json
        from unittest.mock import patch
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        binding = self.binding()
        saved = self.saved(binding)
        def revoke_during_review(receipt):
            issuer.revoke_all()
            return receipt
        with patch.object(issuer, "_tty", side_effect=self.synthetic_tty):
            with self.assertRaises(api.LocalApprovalError):
                issuer.review_and_issue(binding=binding, saved_plan=saved, review=revoke_during_review)
        self.assertEqual(json.loads((self.path / "ledger").read_text())["records"], {})

    def test_setup_rejects_symlink_or_writable_ancestors_before_creating_keys(self):
        api = self.api()
        real = Path(self.root.name) / "real"
        real.mkdir(mode=0o700)
        link = Path(self.root.name) / "alias"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(api.LocalApprovalError):
            api.LocalApprovalIssuer.enable(link / "issuer", acknowledge_local_trust=True)
        self.assertFalse((real / "issuer").exists())
        real.chmod(0o777)
        with self.assertRaises(api.LocalApprovalError):
            api.LocalApprovalIssuer.enable(real / "issuer", acknowledge_local_trust=True)
        self.assertFalse((real / "issuer").exists())
        real.chmod(0o700)
        api.LocalApprovalIssuer.enable(real / "issuer", acknowledge_local_trust=True)
        with self.assertRaises(api.LocalApprovalError):
            api.LocalApprovalIssuer(link / "issuer")

    def test_consumed_bit_is_authenticated_not_a_replay_reset_switch(self):
        import json
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        self.assertTrue(issuer.consume(ref, digest(binding)))
        path = self.path / "ledger"
        ledger = json.loads(path.read_text())
        ledger["records"][ref]["consumed"] = False
        path.write_text(json.dumps(ledger))
        with self.assertRaises(api.LocalApprovalError):
            issuer.verify(ref)
        self.assertFalse(issuer.consume(ref, digest(binding)))

    def test_propose_adapter_uses_engine_protected_binding_without_relaxing_engine_gate(self):
        import runpy
        from src.python.drift_report import digest
        from src.python.drift_remediation import RemediationError
        from src.python.terraform_runner import SavedPlan
        api = self.api()
        self.assertTrue(hasattr(api.LocalApprovalIssuer, "propose"), "trusted CLI propose adapter is missing")
        fixture_module = runpy.run_path(str(Path(__file__).with_name("drift_remediation.test.py")))
        fixture = fixture_module["RemediationTests"]()
        self.addCleanup(fixture.doCleanups)
        from dataclasses import replace
        from src.python.drift_detector import runner_identity_digest
        engine, runner, saved, _, observed, *_ = fixture.fixture()
        runner.local_state_path = Path(self.root.name) / "synthetic.tfstate"
        observed[0] = replace(observed[0], backend_digest=runner_identity_digest(runner))
        saved = SavedPlan(saved.has_changes, saved.path, saved.digest)
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        engine.issuer = issuer
        engine.actor = engine.executor = issuer.principal
        def operation():
            proposal = issuer.propose(engine=engine, deployment="fixture", scope="workstation_infrastructure",
                baseline=fixture_module["BASELINE"], runner=runner, saved_plan=saved,
                policy_digest=digest({"policy": "synthetic"}))
            self.assertEqual(issuer.verify(proposal["approval_ref"]).binding_digest, proposal["binding_digest"])
            # Existing independent-review semantics MUST reject this same-UID grant.
            with self.assertRaises(RemediationError):
                engine.remediate(proposal_id=proposal["proposal_id"], approval_ref=proposal["approval_ref"])
            self.assertEqual(runner.calls, [])
            return proposal
        result, _ = self.tty_run(operation)
        self.assertIn("ok", result, result)
        self.assertNotIn("private", str(result))
        original_propose = engine.propose
        def change_policy_during_proposal(**kwargs):
            proposal = original_propose(**kwargs)
            issuer.set_policy(digest({"policy": "changed-before-review"}))
            return proposal
        engine.propose = change_policy_during_proposal
        result, _ = self.tty_run(operation)
        self.assertEqual(result.get("error"), "LocalApprovalError", result)
        runner.local_state_path = None
        with self.assertRaises(api.LocalApprovalError):
            issuer.propose(engine=engine, deployment="fixture", scope="workstation_infrastructure",
                baseline=fixture_module["BASELINE"], runner=runner, saved_plan=saved,
                policy_digest=digest({"policy": "synthetic"}))

    def test_review_rejects_bool_json_cloned_receipt_and_reusable_yes(self):
        import dataclasses
        import json
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        binding = self.binding()
        saved = self.saved(binding)
        for callback in (lambda receipt: True, lambda receipt: {"verified": True},
                         lambda receipt: dataclasses.replace(receipt), lambda receipt: receipt.plan_digest):
            result, _ = self.tty_run(lambda: issuer.review_and_issue(
                binding=binding, saved_plan=saved, review=callback))
            self.assertEqual(result.get("error"), "LocalApprovalError", result)
        result, _ = self.tty_run(lambda: issuer.review_and_issue(binding=binding, saved_plan=saved), response=False)
        self.assertEqual(result.get("error"), "LocalApprovalError", result)
        self.assertEqual(json.loads((self.path / "ledger").read_text())["records"], {})

    def test_no_tty_cannot_be_replaced_by_environment_or_stdin_claims(self):
        import subprocess
        import sys
        import json
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        binding = self.binding()
        saved = self.saved(binding)
        # Fresh session without controlling TTY, even if launched from a terminal.
        code = "\n".join([
            "import json,sys", "from pathlib import Path",
            "from src.python.drift_approval import LocalApprovalIssuer,LocalApprovalError",
            "from src.python.terraform_runner import SavedPlan",
            "d=json.load(sys.stdin)", "issuer=LocalApprovalIssuer(d['store'],clock=lambda:100)",
            "try:", " issuer.review_and_issue(binding=d['binding'],saved_plan=SavedPlan(True,Path(d['path']),d['binding']['plan_digest']),review=lambda receipt:receipt)",
            "except LocalApprovalError:", " print('refused')", "else:", " sys.exit(9)"])
        result = subprocess.run([sys.executable, "-c", code], start_new_session=True,
            input=json.dumps(dict(store=str(self.path), binding=binding, path=str(saved.path))),
            text=True, capture_output=True, timeout=5,
            env={**os.environ, "USER": "trusted-operator", "SUDO_USER": "root", "APPROVED": "true", "CI": "false"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "refused")
        self.assertEqual(json.loads((self.path / "ledger").read_text())["records"], {})

    def test_invalid_native_plan_principal_ttl_or_changed_review_cannot_issue(self):
        import copy
        from types import SimpleNamespace
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        binding = self.binding()
        saved = self.saved(binding)
        for ttl in (0, 301, True, "120"):
            with self.assertRaises(api.LocalApprovalError):
                issuer.review_and_issue(binding=binding, saved_plan=saved, ttl=ttl)
        for actor in ("root", "detector", "independent-reviewer", "local-uid-999999"):
            changed = {**binding, "actor": actor}
            with self.assertRaises(api.LocalApprovalError):
                issuer.review_and_issue(binding=changed, saved_plan=saved)
        with self.assertRaises(api.LocalApprovalError):
            issuer.review_and_issue(binding=binding, saved_plan=SimpleNamespace(path=saved.path, digest=saved.digest))
        for field in ("plan", "binding"):
            changed = copy.deepcopy(binding)
            self.saved(changed)
            def operation():
                def review(receipt):
                    if field == "plan":
                        saved.path.write_bytes(b"SYNTHETIC-MUTATED-PLAN")
                    else:
                        changed["observation"]["serial"] = 2
                    return receipt
                return issuer.review_and_issue(binding=changed, saved_plan=saved, review=review)
            result, _ = self.tty_run(operation)
            self.assertEqual(result.get("error"), "LocalApprovalError", result)

    def test_expiry_and_each_signed_payload_field_cannot_be_tampered(self):
        import copy
        import json
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        for now in (99, 220, 500):
            issuer = api.LocalApprovalIssuer(self.path, clock=lambda: now)
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            self.assertFalse(issuer.consume(ref, digest(binding)))
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        ledger_path = self.path / "ledger"
        original = json.loads(ledger_path.read_text())
        changes = [("nonce", "f" * 64), ("epoch", "f" * 32), ("producer_uid", os.getuid() + 1),
                   ("audience", "github-actions"), ("binding_digest", "0" * 64),
                   ("reviewer", "independent-reviewer"), ("executor", "other"),
                   ("issued_at", 99), ("expires_at", 300), ("role", "elevated_reviewer")]
        for field, value in changes:
            changed = copy.deepcopy(original)
            payload = changed["records"][ref]["payload"]
            (payload if field in payload else payload["grant"])[field] = value
            ledger_path.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            self.assertFalse(issuer.consume(ref, digest(binding)))
        ledger_path.write_text(json.dumps(original))
        for value in ({"verified": True}, "https://example.invalid/review", "../key", "unknown"):
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(value)
        issuer.verify(ref)

    def test_replaced_lock_inode_is_rejected_after_flock_before_ledger_read(self):
        import fcntl
        from unittest.mock import patch
        api, _, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        real_flock = fcntl.flock
        def replace_during_acquisition(fd, operation):
            real_flock(fd, operation)
            # Preserve nlink=1 on the old inode: fstat alone misses this split.
            (self.path / "lock").rename(self.path / "old-lock")
            replacement = os.open(self.path / "lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(replacement)
        with patch("src.python.drift_approval.fcntl.flock", side_effect=replace_during_acquisition), \
                patch.object(issuer, "_read_private", wraps=issuer._read_private) as read:
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            read.assert_not_called()

    def test_lock_replacement_during_consumption_cannot_return_two_successes(self):
        from unittest.mock import patch
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        competitor = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        real_save = issuer._save
        outcomes = []
        def split_lock_then_save(fd, ledger):
            # Synthetic unsupported store modification, NOT a same-UID boundary.
            (self.path / "lock").rename(self.path / "old-lock")
            replacement = os.open(self.path / "lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(replacement)
            outcomes.append(competitor.consume(ref, digest(binding)))
            real_save(fd, ledger)
        with patch.object(issuer, "_save", side_effect=split_lock_then_save):
            outcomes.append(issuer.consume(ref, digest(binding)))
        self.assertEqual(outcomes, [True, False])
        self.assertFalse(competitor.consume(ref, digest(binding)))

    def test_private_store_revalidates_permissions_links_and_corruption(self):
        api, _, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        for name in ("key", "ledger", "lock"):
            path = self.path / name
            path.chmod(0o644)
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            path.chmod(0o600)
            hardlink = self.path / "extra-link"
            os.link(path, hardlink)
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            hardlink.unlink()
            target = self.path / "original"
            path.rename(target)
            path.symlink_to(target)
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            path.unlink()
            target.rename(path)
        self.path.chmod(0o755)
        with self.assertRaises(api.LocalApprovalError):
            issuer.verify(ref)
        self.path.chmod(0o700)
        (self.path / "ledger").write_text("NOT-VALID-JSON-SYNTHETIC")
        with self.assertRaises(api.LocalApprovalError) as error:
            issuer.verify(ref)
        self.assertNotIn("SYNTHETIC", str(error.exception))

    def test_consumption_failure_before_replace_allows_only_fresh_durable_retry(self):
        from unittest.mock import patch
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        original = (self.path / "ledger").read_bytes()
        for syscall in ("fsync", "replace"):
            with self.subTest(syscall=syscall), \
                    patch("src.python.drift_approval.os." + syscall,
                          side_effect=OSError("SYNTHETIC-IO-FAILURE")):
                self.assertFalse(issuer.consume(ref, digest(binding)))
            self.assertEqual((self.path / "ledger").read_bytes(), original)
            self.assertEqual(list(self.path.glob("pending-*")), [])
            issuer.verify(ref)
        # False never authorizes mutation. A new, successful durable consume can.
        self.assertTrue(api.LocalApprovalIssuer(self.path, clock=lambda: 100).consume(ref, digest(binding)))
        self.assertFalse(issuer.consume(ref, digest(binding)))

    def test_failed_durable_consumption_never_returns_authorization(self):
        from unittest.mock import patch
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        original = os.fsync
        calls = []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError("SYNTHETIC-PRIVATE-ERROR")
            return original(fd)
        with patch("src.python.drift_approval.os.fsync", side_effect=fail_directory):
            self.assertFalse(issuer.consume(ref, digest(binding)))
        # Atomic replacement already happened: conservative burn, never reuse.
        self.assertFalse(api.LocalApprovalIssuer(self.path, clock=lambda: 100).consume(ref, digest(binding)))
        with self.assertRaises(api.LocalApprovalError):
            issuer.verify(ref)

    def test_review_shows_safe_actions_risks_and_fixed_expiry_not_extended_by_delay(self):
        import json
        api = self.api()
        api.LocalApprovalIssuer.enable(self.path, acknowledge_local_trust=True)
        binding = self.binding()
        binding["actions"][0]["address"] = 'terraform_data.item["SYNTHETIC-PRIVATE-KEY"]'
        binding["risks"] = ["destructive"]
        binding["elevated"] = True
        saved = self.saved(binding)
        def operation():
            now = [100]
            issuer = api.LocalApprovalIssuer(self.path, clock=lambda: now[0])
            def review(receipt):
                details = json.loads(receipt.summary)
                self.assertEqual(details["expires_at"], 220)
                self.assertEqual(details["scope"], "workstation_infrastructure")
                self.assertEqual(details["actions"][0]["actions"], ["update"])
                self.assertEqual(details["risks"], ["destructive"])
                self.assertNotIn("SYNTHETIC-PRIVATE-KEY", receipt.summary)
                now[0] = 130
                return receipt
            ref = issuer.review_and_issue(binding=binding, saved_plan=saved, review=review)
            grant = issuer.verify(ref)
            self.assertEqual(grant.issued_at, 130)
            self.assertEqual(grant.expires_at, 220)
            self.assertEqual(grant.role, "elevated_reviewer")
            return ref
        result, transcript = self.tty_run(operation)
        self.assertIn("ok", result, result)
        self.assertNotIn("SYNTHETIC-PRIVATE-KEY", transcript)

    def test_issuer_cannot_be_reused_after_os_principal_changes(self):
        from unittest.mock import patch
        from src.python.drift_report import digest
        api, binding, _, ref = self.issue_fixture()
        issuer = api.LocalApprovalIssuer(self.path, clock=lambda: 100)
        other = os.getuid() + 1
        # Only syscall identity is injected here; no credentials or real setuid.
        with patch("src.python.drift_approval.os.getuid", return_value=other), \
                patch("src.python.drift_approval.os.geteuid", return_value=other):
            with self.assertRaises(api.LocalApprovalError):
                issuer.verify(ref)
            self.assertFalse(issuer.consume(ref, digest(binding)))
        issuer.verify(ref)


if __name__ == "__main__":
    unittest.main()
