# Step 1 — core workflow verification receipt

## Result and scope

**Step 1 completed within its approved synthetic/non-mutating scope.** The current
selected regression run and retained nonempty synthetic CLI workflow pass. Final
independent source/receipt review also passed with no blocking finding; the parent
recomputed all 133 reviewed source/artifact hashes and found no mismatch. The
reviewer inspected receipts, not an independent second execution. Do not treat
this as whole-plan, physical-workstation, native-runtime or cloud acceptance.

- Final run: **19 selected suites; 267 tests counted, 265 passed, 2 skipped; zero
  failures/errors**. The skips are root-only diagnostics; test processes deliberately
  ran as UID 65534 with nonzero supplementary groups.
- Real CLI demonstration: **10 invocations**, followed by the real legacy parser;
  no mocked observer/export/render/planner implementation.
- One artifact contains native Sim + Lab intent and an optional custom tool.
- Parent checked **11 exact field agreements** across the retained YAML, local
  artifact, Ansible artifact and concrete planner targets.
- Existing fixture files and modes were unchanged; the prepared empty fixture
  home remained empty. CLI report output used private, new, exclusive files.
- All sources, revision strings, archive checksum and package name in the demo
  are deliberately synthetic. No source reachability or package availability
  is implied. **Do not use this demo YAML as your actual workstation profile.**

## Evidence map

| Evidence | File |
|---|---|
| Final counted run | `test-summary.json`, `tests/results.json`, individual `tests/*.log` |
| Exact source snapshot | `source-fingerprints.json` (39 code/test/harness files) |
| Original source audit / historical hash comparisons | `initial-independent-review.json` |
| Final independent scoped review and limitations | `final-independent-review.json` |
| Synthetic CLI stdout/stderr/exit codes and argv | `demo/commands.json` |
| Bounded baseline, proposals | `demo/01-observed.json` |
| Explicit accept/edit/declaration decisions | `demo/02-decisions.json` |
| Reviewed report, unchanged-evidence rescan | `demo/03-reviewed.json`, `demo/04-rescanned.json` |
| Actual nonempty YAML export | `demo/05-desired.yaml` |
| Completeness, gaps and provenance | `demo/06-export-review.json` |
| Local and Ansible artifacts / coverage | `demo/07-local.json`, `demo/08-ansible.json` |
| Concrete dry-run, no target inspection | `demo/09-dry-run.json` |
| Explicit fixture target metadata and resulting preview | `demo/09b-target-metadata.json`, `demo/09c-dry-run-with-evidence.json` |
| Real legacy parser's NUL-contract values | `demo/10-legacy-parser.json` |
| Independently compared output values | `demo/11-consumer-agreement.json` |
| End-to-end assertions | `demo/summary.json` |

Original final run directories were `/tmp/isaac-step1-ptww1ez4` and
`/tmp/isaac-step1-demo-j0pu_ozq`. Stored paths and commands intentionally retain
those identities rather than rewriting evidence to pretend the fixture existed
in this documentation folder. Logs/JSON/YAML were copied here for retention.

## Relevant fixes, each reproduced before changing production code

1. **Reviewed custom-tool location:** observed environment metadata produces a
   concrete source location. The local package adapter accepts a null desired
   location to use its selected Lab environment, but review formerly rejected
   that intent. Candidate tool validation now admits explicit null location;
   the metadata validator's default remains strict, baseline/suggested paths and
   cumulative writer exclusions remain intact. Invalid non-null paths still
   refuse. Regression covers both renderers and review persistence over rescan.
   See `tool-location-red.log` and the final desired-profile suite.
2. **Resolver traversal authority:** the runtime path helper requested read
   permission on `/` and every ancestor just to reach an explicitly selected
   directory. It now traverses with nofollow `O_PATH` handles and opens `.` on
   the selected pinned directory for reading. Existing mode, case-collision,
   nofollow and ambiguity checks remain. The test boundary was not broadened.
   See `workspace-traversal-red.log` and final workspace/named/migration suites.

Modified product files are `metadata_readers.py`, `profile_discovery.py` and
`workspace_paths.py` under `isaac-installer/lib/core/`. Regression additions are
in `installer_desired_profile.test.py` and `installer_workspace_contract.test.py`.
The discovery documentation explains explicit null desired locations.

## What the dry-run establishes

Without target evidence, the selected paths are concrete while target state is
unknown. Explicit metadata observation of the synthetic fixture then reports:

| Action | Status | Meaning |
|---|---|---|
| Workspace root / BoredEngineer group | satisfied | Existing directory, no adoption or modification |
| Existing IsaacLab checkout | blocked | Existing repository must not be overwritten/adopted |
| Missing IsaacSim prefix | would_change | Potential artifact installation, not executed or qualified |
| Conda / bundled Kit prefix | unknown | No separately established runtime prefix |
| Custom package and environment declaration | unknown/unsupported | Intent retained; no qualified action execution claim |

Both previews correctly return **exit 2** with `execution_authorized: false`.
This is a concrete **non-mutating preview**, not a claim that a real installation
is fully satisfied, operationally compatible, or safe to update. Render support
and package-field transport do not prove Ansible tasks or native installers ran.

## Test boundary and preserved failed attempts

`isaac-step1-runner.py` is a session-specific, explicit allowlist, **not** the
project's broad default runner. It provides a clean environment, unprivileged
identity, Landlock filesystem grants limited to trusted runtime/repository reads
and one disposable writable tree, plus seccomp denial of sockets and selected
escape syscalls. Child processes inherit confinement. Parent reads/reports are
limited to explicitly allocated artifacts. Positive fixture writes and denied
outside-canary reads/writes/socket creation passed (`tests/controls.log`).

This is defense in depth for inspected trusted tests, not a general hostile-code
sandbox or a proof of zero physical effects. Metadata traversal/access-time
residuals remain; trusted repository/runtime source reads are allowed. In-memory
Python import guarding is supplementary and is not a cross-exec managed gate.
The explicit source-audited suite/method selection is essential.

- No default `run_profile_workflow_tests.py` invocation was made.
- Both managed-dependent methods in `installer_plan_evidence.test.py` are excluded:
  `test_actual_fixture_journal_qualified_hash_metadata_is_preserved` and
  `test_actual_fixture_metadata_is_preserved_without_aliases`.
- The first selection missed the second method. The audit guard rejected its
  `managed_apply` module execution **before the module body ran**. No managed
  builder/apply/recovery executed. The selection was corrected, not the guard
  bypassed. See `excluded-method-guard.log` and `initial-suite-attempt.json`.
- An initial demonstration recorder incorrectly tried to JSON-serialize the
  legacy parser's bytes contract. The real CLI stages had completed; decoding
  the actual NUL key/value contract fixed the harness, not production code.
- The target-evidence writer correctly refused a nonexistent exclusion home.
  The final fixture precreates an empty synthetic home before CLI execution;
  no writer checks were weakened and no installed environment was fabricated.
- Initial expanded workspace tests failed under the restricted root read grant.
  The resolver fix reduced required read authority rather than adding global
  filesystem reads to the harness.

The historical `/.env` fixture incident remains in the primary plan. This run
neither inspected that path nor independently attested to its earlier cleanup.

## Repeating this bounded snapshot

From `/workspaces/IsaacAutomator`, with the existing system Python/PyYAML and Linux
x86_64 Landlock ABI >= 5/seccomp available:

```sh
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step1/isaac-step1-runner.py installer_metadata_readers installer_discovery installer_desired_profile workstation_profile workstation_profile_extensions profile_adapters installer_action_plan installer_migration_preview installer_profile_read_boundary installer_discovery_cli installer_profile_workflow installer_export_conflict installer_output_entry installer_report_writer installer_writer_history installer_plan_evidence installer_workspace_contract installer_named_safety installer_target_observation
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step1/isaac-step1-demo.py
```

These are Linux/session-specific verification tools with an explicit repository
root, not a new installer framework. Each run allocates new private fixture/output
directories. Re-audit changed test bodies before reusing the allowlist. Do not
use this as authorization to repeat previously denied managed probes.

## Boundaries that remain

No actual workstation inventory, Git fetch/checkout, model/package install,
Ansible deployment, paid resource creation, sync activation, current devcontainer
or VS Code settings changes occurred. No commit/push was requested or performed.

Next is agreement on exact real-machine identity, metadata inputs, exclusions,
budgets and private report destination—not automatic scanning. The original
whole-plan requirements, managed/adoption qualification, synchronization credential
exclusion blocker and native/runtime acceptance remain separately open.
