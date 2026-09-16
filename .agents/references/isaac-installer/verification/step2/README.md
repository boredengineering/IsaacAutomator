# Host discovery step 2 — retained verification

Status: step-2 implementation and bounded parent fixture verification complete.
Independent code/security closure and separate original-step-2 completeness
reviews PASS, reconciled against frozen source hashes and real parent runs.
This is not actual workstation collection, native installation qualification or
completion of the broader six-step plan.

## Fresh parent execution

| Scope | Tests | Passed | Skipped | Failures/errors |
|---|---:|---:|---:|---:|
| Host collector/importer, two explicit suites | 49 | 49 | 0 | 0 |
| Existing core, 19 explicit selected suites | 267 | 265 | 2 | 0 |
| Total (disjoint suites; not accumulated reruns) | 316 | 314 | 2 | 0 |

- Host: `/tmp/isaac-step1-718qtqdx`, retained in `final-host/`.
- Core: `/tmp/isaac-step1-4itzamyt`, retained in `final-core/`.
- Demo: `/tmp/isaac-host-demo-scl8fn_8/reports`, retained in `demo/`.
- `test-summary.json` is computed from the real test receipts.
- `source-fingerprints.json` records 46 current source/test/harness/doc hashes.
  The parent verified the earlier four frozen closure-worker hashes, then the two
  new hashes from the final ancestor-contract fix; unchanged sources remain pinned.
- `tdd-receipts.json` retains 30 selected RED/GREEN phase receipts and raw logs.
  Original collector development and the broader closure history are additionally
  described in the retained worker reports under `reviews/`.

The two skips are existing root-only tests. The children deliberately drop to an
unprivileged identity. Both managed-dependent plan-evidence methods remain
excluded by the established harness; no default-runner or equivalent managed
execution was substituted.

## Reproduce only the bounded scope

From the repository root:

```sh
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step2/run_bounded_tests.py
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step1/isaac-step1-runner.py
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step2/demo_host_workflow.py
```

The step-2 runner reuses the retained step-1 child confinement, not the unsafe
broad default suite runner. Only the two named new suites are selected. New test
bodies and their transitive helpers were inspected for fixture-only I/O and
absence of managed probes. The collector's portable implementation itself does
not inherit this kernel confinement when run on a host.

## Actual ten-command synthetic vertical path

The retained demo constructs a fake home/system root, then invokes the actual
standalone collector with isolated Python for plan and collection. It runs:

1. Collector plan: no target report created.
2. Collector collect: private portable report from explicit synthetic roots.
3. `import-host-report`: unapproved baseline/candidate/review.
4. `review-profile`: explicit fixture-only intent decisions/declarations.
5. Re-import with the previous report: unchanged evidence decisions retained.
6. `export-profile --format yaml`: nonempty Sim/Lab shared YAML.
7. `export-profile`: complete intent status and review evidence.
8. `render-profile --adapter local`.
9. `render-profile --adapter ansible`.
10. `install --dry-run --desired-profile`: concrete targets and unknowns; expected
    incomplete target-evidence exit, with no installation authority.

Assertions cover exact BoredEngineer/IsaacLab target spelling; selected commit
mapping to both renderers; private report identity; unknown dirty state; recorded
repo/Sim/Conda metadata source paths; dpkg installed status; build-tool/uncertain
package membership; selected UV/environment follow-up proposals; and false
execution authorization throughout. All 15 synthetic source files retain their
hashes and modes, and both source-tree directory-entry sets are unchanged.

Important artifacts:

- `demo/00-collection-plan.json` — planned fixed seeds/metadata/effects.
- `demo/01-host-inventory.json` — raw synthetic evidence and `details`.
- `demo/02-imported.json` — proposals, no automatic approvals.
- `demo/04-reviewed.json`, `05-reimported.json` — explicit intent and continuity.
- `demo/06-desired.yaml` — synthetic example, NOT the user's real profile.
- `demo/08-local.json`, `09-ansible.json`, `10-dry-run.json` — consumer/preview output.
- `demo/commands.json`, `summary.json` — exact invocations, original exit codes,
  captured outputs and checked assertions.

The fixture's archive URL/checksum, commit, versions and packages are test data.
No network/source-availability, runtime compatibility, clean checkout or native
convergence is claimed. Collection coverage intentionally remains incomplete;
complete reviewed intent is a different property from complete observation.

## Review history and fixes

Initial importer review found metadata-to-desired grammar mismatches. Broader
code review found ordinary punctuation/Unicode paths, package epochs/private
environment names, and independent array limits could produce collector reports
that the importer rejected. The separate original-requirements audit identified
missing detailed provenance, package status/group membership, link target/scope
proposals, selected editable/UV followups and explicit unknown driver CUDA level.
These prompted further implementation—not a redefinition of the approved step.

The retained closure report documents the resulting optional strict `details`
version, bounded report normalization/headroom, stable identity maps, data-only
link targets, deterministic membership groups and action=`request-explicit-scope`
followups. Legacy limited reports remain accepted as explicitly limited evidence.

The interim parent run `vp94b_9d` caught an evolving synthetic budget fixture that
used an unadmitted environment scope. It is not a final passing receipt; the
fixture was corrected without weakening source binding. A subsequent review
identified HOST-CLOSURE-01: selected home-seed symlink ancestors and shallow system
ancestor labels were importable collector evidence but rejected by the raw-evidence
validator. Two new RED/GREEN regressions cover the real Documents-link CLI import
and a pure-data `/var` record. Raw labels were aligned without expanding local
report/read/desired paths or following targets. Outside-scope ancestors remain
rejected. The final parent run above passed all 49 new tests.

Final independent requirements audit: `reviews/isaac-host-completeness-final.json`.
Final code gate: `reviews/isaac-host-final-accepted-review.json`, closing
HOST-CLOSURE-01 and preserving the original requirements closure. The parent
verified all eight reviewer-recorded hashes before updating plan/status prose;
seven are unchanged source/test/demo/guide files, while the plan then received
completion wording. Earlier failed reviews remain retained as history, not open
findings. These are source reviews, not independent test reruns or certification
of the physical workstation.

## Safety and remaining operational gates

No actual workstation was inventoried. No host mounts, SSH access expansion,
package-manager command, Git command against an observed workstation checkout,
import from observed environments or robotics installations,
installer/Ansible application, settings change, synchronization or paid cloud
operation was performed. Embedded host paths and link targets remain report data,
not local grants. Existing private-output supervision remains exclusive/no-replace.

This collector has a selected metadata scope, not whole-machine reproduction.
Live GPU query/driver-supported CUDA discovery, full editable/UV parsing, packed
Git refs/worktree targets and alternate prefixes remain explicit uncollected or
separately proposed scopes. System package membership is review evidence, not
implemented native/Ansible package installation intent. The actual host-run step
is still the user's separate decision; see `isaac-installer/docs/host-discovery.md`.
