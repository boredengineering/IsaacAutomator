"""Explicitly enabled, single-controller local-operator approval storage.

This is NOT a remote/protected-review issuer or an independent-principal boundary.
The OS UID (including every process and provider executing as that UID) is trusted.
Never inject this into an independent-review workflow to manufacture separation.
No initialization occurs on import, construction, detection, or report generation.
The caller must choose durable LOCAL storage with working flock/rename/fsync;
network filesystems, multiple controllers, state rollback and same-UID isolation
are unsupported. External GitHub/protected-review issuers remain separate.
"""
from contextlib import contextmanager
import copy
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import time

from src.python.drift_config import opaque_ref
from src.python.drift_report import Baseline, digest, require_digest, public_address, _ACTIONS
from src.python.drift_remediation import Observation, RemediationEngine, VerifiedApproval, _plan_digest
from src.python.terraform_runner import SavedPlan


@dataclass(frozen=True)
class PlanReview:
    """Native review challenge, not a portable authorization or caller JSON flag."""
    plan_digest: str
    binding_digest: str
    nonce: str
    summary: str


class LocalApprovalError(ValueError):
    """Sanitized local approval rejection."""


class LocalApprovalIssuer:
    """Private local store. Call enable only from explicit opt-in CLI setup."""

    def __init__(self, directory, *, clock=time.time):
        self._directory = Path(directory)
        self._uid = os.getuid()
        self._clock = clock
        try:
            with self._open_directory() as fd:
                self._read_private(fd, "key", 32)
        except (OSError, ValueError):
            raise LocalApprovalError("Local approval store is unavailable or unsafe") from None

    @property
    def principal(self):
        return "local-uid-" + str(self._uid)

    @classmethod
    def enable(cls, directory, *, acknowledge_local_trust=False):
        if acknowledge_local_trust is not True:
            raise LocalApprovalError("Explicit local issuer opt-in is required")
        directory = Path(directory)
        try:
            with cls._parent_directory(directory) as parent_fd:
                os.mkdir(directory.name, mode=0o700, dir_fd=parent_fd)
                fd = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=parent_fd)
                try:
                    for name, data in (("key", secrets.token_bytes(32)), ("lock", b""),
                            ("ledger", json.dumps({"epoch": secrets.token_hex(16), "records": {}}).encode())):
                        file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                          0o600, dir_fd=fd)
                        with os.fdopen(file_fd, "wb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.fsync(parent_fd)
            return cls(directory)
        except (OSError, ValueError):
            raise LocalApprovalError("Local issuer initialization refused") from None

    @staticmethod
    @contextmanager
    def _parent_directory(path):
        # Open each component relative to a pinned parent: no symlink traversal.
        if (not path.is_absolute() or ".." in path.parts or path == Path("/")
                or os.getuid() != os.geteuid() or os.getgid() != os.getegid()):
            raise LocalApprovalError("Unsafe local approval directory")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                # Root-owned sticky /tmp is safe for creating an exclusive UID-owned leaf.
                if (info.st_uid not in (0, os.getuid()) or
                        (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
                    raise LocalApprovalError("Unsafe local approval ancestor")
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _open_directory(self):
        if os.getuid() != self._uid or os.geteuid() != self._uid:
            raise LocalApprovalError("Local OS principal changed")
        with self._parent_directory(self._directory) as parent_fd:
            fd = os.open(self._directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if info.st_uid != self._uid or info.st_mode & 0o077:
                raise LocalApprovalError("Unsafe local approval directory")
            yield fd
        finally:
            os.close(fd)

    def _read_private(self, directory_fd, name, size=None):
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self._uid
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise LocalApprovalError("Unsafe local approval file")
            data = stream.read()
        if size is not None and len(data) != size:
            raise LocalApprovalError("Invalid local approval file")
        return data

    @contextmanager
    def _locked(self):
        try:
            with self._open_directory() as directory_fd:
                lock_fd = os.open("lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=directory_fd)
                try:
                    info = os.fstat(lock_fd)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != self._uid
                            or info.st_mode & 0o077 or info.st_nlink != 1):
                        raise LocalApprovalError("Unsafe local approval lock")
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                    self._check_lock_inode(directory_fd, lock_fd)
                    key = self._read_private(directory_fd, "key", 32)
                    ledger = json.loads(self._read_private(directory_fd, "ledger"))
                    yield directory_fd, key, ledger
                    # A pending return (including consume=True) must fail closed
                    # if the stable-lock prerequisite broke during the operation.
                    self._check_lock_inode(directory_fd, lock_fd)
                finally:
                    os.close(lock_fd)
        except (OSError, ValueError, KeyError, TypeError):
            raise LocalApprovalError("Local approval operation refused") from None

    def _check_lock_inode(self, directory_fd, lock_fd):
        # Detect accidental/excluded lock replacement, not hostile same-UID races.
        held = os.fstat(lock_fd)
        named = os.stat("lock", dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(held.st_mode) or held.st_uid != self._uid
                or held.st_mode & 0o077 or held.st_nlink != 1
                or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)):
            raise LocalApprovalError("Local approval lock changed")

    def _save(self, directory_fd, ledger):
        temporary = "pending-" + secrets.token_hex(16)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps(ledger, sort_keys=True, allow_nan=False).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, "ledger", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass

    @staticmethod
    def _signature(key, payload):
        # Local HMAC authentication only: NOT an asymmetric/external signing standard.
        return hmac.new(key, b"drift-local-approval-v1\0" + digest(payload).encode(),
                        hashlib.sha256).hexdigest()

    @contextmanager
    def _tty(self):
        fd = None
        try:
            if (os.getuid() != self._uid or os.geteuid() != self._uid
                    or os.getgid() != os.getegid() or not os.isatty(0)
                    or os.fstat(0).st_uid != self._uid):
                raise LocalApprovalError("A foreground local OS-principal TTY is required")
            fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
            if (not os.isatty(fd) or os.tcgetpgrp(fd) != os.getpgrp()
                    or os.tcgetpgrp(0) != os.getpgrp()):
                raise LocalApprovalError("A foreground local OS-principal TTY is required")
            with os.fdopen(os.dup(fd), "r", encoding="utf-8") as reader, \
                    os.fdopen(os.dup(fd), "w", buffering=1, encoding="utf-8") as writer:
                yield reader, writer
        except (OSError, ValueError):
            raise LocalApprovalError("Local interactive review refused") from None
        finally:
            if fd is not None:
                os.close(fd)

    def _review_receipt(self, binding, saved_plan, nonce, expires_at):
        if type(saved_plan) is not SavedPlan or _plan_digest(saved_plan) != binding["plan_digest"]:
            raise LocalApprovalError("A native exact saved plan is required")
        if binding["actor"] != self.principal or binding["executor"] != self.principal:
            raise LocalApprovalError("Producer and executor must be the authenticated local UID")
        baseline = Baseline.from_dict(binding["baseline"])
        observation = Observation(**binding["observation"])
        now = int(self._clock())
        if (baseline is None or observation.complete is not True
                or type(observation.observed_at) is not int
                or not 0 <= now - observation.observed_at <= 60
                or type(binding["created_at"]) is not int
                or not 0 <= now - binding["created_at"] < 300
                or observation.baseline_digest != digest(baseline.to_dict())
                or type(observation.serial) is not int or observation.serial < 0):
            raise LocalApprovalError("Incomplete or stale local proposal")
        for value in (binding["plan_digest"], binding["plan_json_digest"],
                      observation.backend_digest, observation.properties_digest,
                      observation.coverage_digest):
            require_digest(value)
        opaque_ref(observation.lineage)
        if (binding["scope"] not in ("workstation_infrastructure", "backend_infrastructure")
                or type(binding["elevated"]) is not bool or now >= expires_at):
            raise LocalApprovalError("Unsupported or expired local review")
        risks = binding["risks"]
        known_risks = {"iam_broadening", "public_exposure", "protection_disabled", "key_change",
                       "cost_increase", "destructive", "import", "ownership_change"}
        if not isinstance(risks, list) or any(risk not in known_risks for risk in risks):
            raise LocalApprovalError("Unsupported risk review")
        actions = []
        for finding in binding["actions"]:
            if tuple(finding["actions"]) not in _ACTIONS:
                raise LocalApprovalError("Unsupported action review")
            actions.append(dict(address=public_address(finding["address"]), actions=finding["actions"]))
        summary = json.dumps(dict(mode="single-controller trusted local UID; NOT independent review",
            scope=binding["scope"], actions=actions, risks=risks, elevated=binding["elevated"],
            expires_at=expires_at,
            producer_uid=self._uid, plan_digest=saved_plan.digest, binding_digest=digest(binding),
            backend_digest=observation.backend_digest, lineage=observation.lineage,
            serial=observation.serial, source_revision=baseline.source_revision,
            source_digest=baseline.source_digest, input_digest=baseline.input_digest,
            provider_lock_digest=baseline.lock_digest, live_fingerprint=observation.properties_digest,
            coverage_digest=observation.coverage_digest), sort_keys=True)
        return PlanReview(saved_plan.digest, digest(binding), nonce, summary)

    def propose(self, *, engine, deployment, scope, baseline, runner, saved_plan,
                policy_digest, review=None, ttl=120):
        """Parent CLI integration: propose + fresh local review, NEVER apply.

        Configure engine.actor == engine.executor == issuer.principal, explicitly
        opt into local-operator semantics at composition, and keep remote runner
        construction/mutation gates unchanged. Existing independent-review engine
        semantics deliberately reject these honest same-UID grants.

        The current engine has no public protected-binding accessor. This narrow
        adapter snapshots its actual protected registry under its operation lock;
        it NEVER signs the caller's public proposal summary. Replace this seam
        with a native engine review accessor if/when that contract is introduced.
        """
        try:
            if (not isinstance(engine, RemediationEngine) or engine.issuer is not self
                    or engine.actor != self.principal or engine.executor != self.principal
                    or runner.local_state_path is None):
                raise LocalApprovalError("Explicit trusted local composition is required")
            policy_epoch = self.set_policy(policy_digest)
            proposal = engine.propose(deployment=deployment, scope=scope, baseline=baseline,
                                      runner=runner, saved_plan=saved_plan)
            with engine._operation_lock:
                binding, fingerprint, owner_runner, owner_plan, _ = engine._proposals[proposal["proposal_id"]]
                if (owner_runner is not runner or owner_plan is not saved_plan
                        or fingerprint != proposal["binding_digest"] or digest(binding) != fingerprint):
                    raise LocalApprovalError("Protected proposal binding changed")
                binding = copy.deepcopy(binding)
            ref = self.review_and_issue(binding=binding, saved_plan=saved_plan, review=review,
                                        ttl=ttl, expected_policy_epoch=policy_epoch)
            return {**proposal, "approval_ref": ref}
        except Exception:
            raise LocalApprovalError("Local proposal review refused") from None

    def review_and_issue(self, *, binding, saved_plan, review=None, ttl=120, expected_policy_epoch=None):
        """Trusted application-composition API, NEVER a request-JSON endpoint.

        binding must come directly from the engine's protected proposal, not its
        public summary. Pin expected_policy_epoch to set_policy's return before
        preparing a proposal (propose does this automatically). Without that pin,
        the epoch is captured only AFTER initial receipt preparation: an earlier
        revoke_all does not cancel this call, which adopts the new epoch instead.
        Optional trusted CLI review callback receives PlanReview
        and must return THAT exact object, not bool/dict/a shell digest string.
        The callback cannot bypass the additional fresh controlling-TTY challenge.
        No raw plan/state or signing material is given to the callback or receipt.
        The existing engine rejects same-UID self-review; only explicitly designed
        local-operator composition may accept it. Remote runners remain gated.
        """
        try:
            if type(ttl) is not int or not 1 <= ttl <= 300:
                raise LocalApprovalError("Approval lifetime must be within 1..300 seconds")
            nonce = secrets.token_hex(32)
            expires_at = min(int(self._clock()) + ttl, binding["created_at"] + 300)
            receipt = self._review_receipt(binding, saved_plan, nonce, expires_at)
            with self._locked() as (_, _, ledger):
                epoch = ledger["epoch"]
                if expected_policy_epoch is not None and epoch != expected_policy_epoch:
                    raise LocalApprovalError("Approval policy changed since proposal preparation")
            with self._tty() as (reader, tty):
                tty.write(receipt.summary + "\n")
                if review is not None and review(receipt) is not receipt:
                    raise LocalApprovalError("Exact native plan review receipt required")
                challenge = "approve " + receipt.plan_digest + " " + receipt.binding_digest + " " + nonce
                tty.write("Type: " + challenge + "\n")
                tty.flush()
                if reader.readline(512).rstrip("\r\n") != challenge:
                    raise LocalApprovalError("Review was not confirmed")
            with self._locked() as (fd, key, ledger):
                # Lock contention can outlast the review; recheck exact bytes and
                # freshness before persisting, without extending the shown expiry.
                if self._review_receipt(binding, saved_plan, nonce, expires_at) != receipt:
                    raise LocalApprovalError("Proposal changed during review")
                if ledger["epoch"] != epoch:
                    raise LocalApprovalError("Approval policy changed during review")
                now = int(self._clock())
                grant = VerifiedApproval(receipt.binding_digest, self.principal, self.principal,
                    now, expires_at,
                    "elevated_reviewer" if binding["elevated"] else "reviewer")
                payload = dict(grant=asdict(grant), nonce=nonce, epoch=epoch,
                    producer_uid=self._uid, audience="local-single-controller-v1")
                ledger["records"][nonce] = dict(payload=payload,
                    signature=self._signature(key, dict(payload=payload, consumed=False)), consumed=False)
                self._save(fd, ledger)
            return nonce
        except Exception:
            raise LocalApprovalError("Local plan approval refused") from None

    def _verified(self, approval_ref, key, ledger):
        opaque_ref(approval_ref)
        record = ledger["records"][approval_ref]
        payload = record["payload"]
        if (not hmac.compare_digest(record["signature"], self._signature(key,
                dict(payload=payload, consumed=record["consumed"])))
                or payload["nonce"] != approval_ref or payload["epoch"] != ledger["epoch"]
                or payload["audience"] != "local-single-controller-v1"
                or payload["producer_uid"] != self._uid or record["consumed"] is not False):
            raise LocalApprovalError("Approval is invalid or revoked")
        grant = VerifiedApproval(**payload["grant"])
        require_digest(grant.binding_digest)
        if (grant.reviewer != self.principal or grant.executor != self.principal
                or type(grant.issued_at) is not int or type(grant.expires_at) is not int
                or not grant.issued_at <= int(self._clock()) < grant.expires_at
                or not 1 <= grant.expires_at - grant.issued_at <= 300):
            raise LocalApprovalError("Approval is invalid or expired")
        return grant

    def set_policy(self, policy_digest):
        """Trusted CLI must call on every relevant config/authorization-policy change.

        Hash the complete local policy including adapter versions/owner identity.
        Only a digest is persisted. Equal policy is idempotent; any change revokes
        all outstanding receipts, even if policy later reverts to its old value.
        This is a local controller hook, not remote policy discovery.
        """
        require_digest(policy_digest)
        with self._locked() as (fd, _, ledger):
            if ledger.get("policy_digest") != policy_digest:
                ledger["policy_digest"] = policy_digest
                ledger["epoch"] = secrets.token_hex(16)
                ledger["records"] = {}
                self._save(fd, ledger)
            return ledger["epoch"]

    def revoke_all(self):
        """Durably invalidate existing grants and reviews pinned to the old epoch.

        Low-level review_and_issue callers must supply expected_policy_epoch from
        before proposal preparation to cover that whole interval. Without it,
        only reviews past their initial locked epoch capture are cancelled;
        calls still preparing their initial receipt may adopt the new epoch.
        """
        with self._locked() as (fd, _, ledger):
            ledger["epoch"] = secrets.token_hex(16)
            ledger["records"] = {}
            self._save(fd, ledger)

    def consume(self, approval_ref, binding_digest):
        """One local durable filesystem, cooperating processes; NOT multi-controller.

        Consume before mutation; False NEVER authorizes mutation. Failure before
        ledger replacement (e.g. file fsync) can leave the grant unconsumed: only
        a fresh consume returning True may authorize a later mutation attempt.
        Failure after replacement (e.g. directory fsync) may conservatively burn
        the grant; do not reset it or infer permission from an uncertain outcome.
        The persistent lock inode must not be replaced. Entry/exit inode checks
        detect some replacements, but cannot establish hostile-writer isolation.
        No filesystem rollback/restore or same-UID attacker resistance is claimed.
        """
        try:
            require_digest(binding_digest)
            with self._locked() as (fd, key, ledger):
                grant = self._verified(approval_ref, key, ledger)
                if grant.binding_digest != binding_digest:
                    return False
                record = ledger["records"][approval_ref]
                record["consumed"] = True
                record["signature"] = self._signature(key, dict(payload=record["payload"], consumed=True))
                self._save(fd, ledger)
                return True
        except LocalApprovalError:
            return False

    def verify(self, approval_ref):
        """Resolve a private HMAC-authenticated grant; no caller claims are trusted."""
        with self._locked() as (_, key, ledger):
            return self._verified(approval_ref, key, ledger)
