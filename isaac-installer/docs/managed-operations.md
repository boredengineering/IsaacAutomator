# Managed-operation qualification and recovery

This is the implementation/fixture contract, **not a general installation guide**.
No real-target apply command is exposed. The legacy installer has not become a
qualified adoption/update mechanism. A reviewed profile, complete rendering,
filesystem observation or successful test is not authorization to change a working
installation.

The shared-profile artifact marker also prevents flat/auto/org profiles from
falling through to the legacy native stage dispatcher. This is a pre-stage refusal,
not a promise that legacy sourcing/config initialization is a confined observation.
Use the dedicated offline entry points for reads and previews; manually removing
the marker does not qualify legacy installation.

**Qualification is currently blocked.** Independent managed-apply/recovery probes
were explicitly denied by the execution layer; a renewal request timed out. They
must not be rerun through equivalent commands. Subsequent pure validation/source
fixes do not replace the missing execution evidence. Venv expected-byte validation
and recovery-manifest validation findings are tracked in the plan; no passing
independent managed qualification is claimed. Do not use these APIs on existing
resources.

## One planner, different evidence and execution boundaries

`action_plan.build_action_plan` produces concrete operations and target paths from
selected intent and optional strict metadata. The read-only CLI adds observation
and authorization disclaimers. The managed executor accepts the exact undecorated
planner schema, verifies its digest, and independently qualifies operation shape;
removing disclaimers or rehashing arbitrary input does not qualify an operation.

`managed_apply.apply_plan(plan, fixture_root=..., approved=False, action_ids=None)`
is the internal execution API. `approved=True` is an explicit caller decision, not
a cryptographic authorization capability. Source-code callers already have their
own operating-system permissions. Tests call it only on newly allocated private
fixtures; no invocation has targeted a real robotics installation.

## Implemented recipe families with bounded fixture coverage

- New workspace directories and bounded new declarative files.
- A new stdlib venv, without pip, created from the fixed system Python.
- A new detached checkout of an explicitly selected synthetic local Git source,
  with object/worktree fingerprint verification. The fixture builder does not
  fetch a network repository, execute repository hooks/builds or update submodules.
- Managed-file backup and verified restoration to a different new file. This is
  not repository/environment backup or in-place rollback.

Recipes refuse unsupported operations rather than returning an installation
receipt. Receipts explicitly keep `robotics_installed: false`. Optional unsupported
items remain deferred and visible; required unsupported operations block the
corresponding requested execution. No source version, environment or setting is
silently substituted.

## Preservation and interruption

The implementation pins resource descriptors, compares root/ancestor identity,
coordinates inode locks, refuses foreign/symlink/hardlinked or changed resources,
and publishes supported new resources without overwriting existing destinations.
Child builders use explicit binaries, a restricted process environment and a
scoped filesystem boundary. Builders and publisher compare expected content as
well as metadata; an unkeyed plan hash or a supplied `satisfied` label is not proof
of current content.

The bounded private journal records intended/started/verified/failed operations.
Unresolved interrupted or failed runs block another apply. An unchanged rerun
checks desired predicates and postconditions rather than blindly trusting the
journal. Old installed resources are not adopted merely because the user owns
their directory or because a marker file exists.

Recovery is explicit:

1. `read_journal(fixture_root=...)` reads the bounded typed journal.
2. Review the exact events and the remaining partial resources separately.
3. `review_recovery(fixture_root=..., run_ids=..., journal_digest=...,
   approved=True)` acknowledges only the selected unresolved events with the exact
   reviewed journal digest.
4. Build and approve a fresh operation plan. Acknowledgement does **not** remove
   files, restore an installation, resume a build or certify that cleanup happened.

`backup_managed_file` and `restore_backup` also require explicit approval and
separate roots. They preserve the original and later user edits. A backup does not
authorize mutation, and file restoration evidence does not qualify an entire Git
checkout, environment, service or disk recovery workflow.

## Explicitly not qualified

Network fetch, installing packages into Conda/uv, Sim archive/EULA/extraction,
robotics builds, GPU compatibility, service/settings changes, existing-checkout
adoption/update, in-place restoration and automatic cleanup/resume are not managed
executor qualifications. Dedicated local/Ansible consumers may implement such
operations, but consumer wiring is not equivalent to safe-apply qualification.

Process interruption tests are not power-loss/crash-consistency tests. Not every
builder-created file is comprehensively fsynced. Same-device bind mounts, hostile
concurrent namespace changes, arbitrary same-UID writers, compromised system
binaries and multithreaded callers are not proven safe by these fixtures. Locks
coordinate cooperating code; final filesystem checks remain point-in-time.

## Reproduce offline evidence

After the denied fixture workflow has been explicitly reauthorized, the relevant
suite selection is below. This is a reproduction reference, **not a request or
authorization to execute it while the gate remains blocked**:

```bash
/usr/bin/python3 -B src/tests/run_profile_workflow_tests.py \
  installer_action_plan installer_managed_apply installer_plan_evidence
```

The suites create and clean their own disposable fixtures. They do not use a
selected real home/workspace, run installers, contact a cloud, or activate sync.
Final security-review and whole-plan status belongs to the implementation register
in `.agents/references/isaac-installer/workspace-repository-management-plan.md`, not
to an isolated passing test count or this API description.
