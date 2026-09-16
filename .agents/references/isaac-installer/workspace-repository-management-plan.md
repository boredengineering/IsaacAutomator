# Shared Profile Discovery and Workspace Naming — Review Plan

**Status:** Implementation authorized by the user's subsequent explicit request. Code development, isolated fixture tests and independent review may proceed; physical-workstation observation/apply, settings changes, sync activation and cloud operations remain separately gated. Checklists below describe requirements, not completed work unless supported by recorded evidence.

**Latest scope clarification:** The user authorized all code development and isolated verification in this whole plan and rejected treating the prior partial milestone as completion. All six YAML/discovery/adapters/actions/sync/sandbox workstreams remain accountable to original requirements, including 8E. Real code and checkpoint receipts now exist; later independent rereviews identify blockers, so this is not a completed delivery. Parent owns remaining integration, independent whole-plan audit and final verification. No renewed code authorization is needed. Actual scans/installations/adoption/recovery/settings/sync/cloud remain separately gated; missing consumers must not be relabeled live-only gaps.

**Goal:** Use bounded observations of the working local setup, evidence-backed proposals and user review to discover an intuitive desired profile, including unique tools/dependencies, their host/container/environment placement, and stable custom workspace naming. Preserve the working machine and evaluate shared YAML intent for isaac-installer and Ansible without executing either installer. File synchronization and remote devcontainer use remain complementary work, not substitutes for environment provisioning.

**Architecture proposal:** Independent observation produces a baseline; a proposal layer derives a candidate desired profile with evidence and unresolved decisions; user review and comparison refine that candidate. Reuse the existing profile/resolution boundary where suitable, but never invoke mutating installer checks to collect observations. Local/Ansible execution is not part of profile discovery. Its implementation and disposable qualification are authorized; execution against actual resources needs separate target/action approval.

**Technology:** Existing YAML/PyYAML profile parsing, Bash installer, Python profile tooling and tests, Git, and later Ansible/Packer consumers. The admitted observer/preview additionally requires Linux x86_64 Landlock ABI >= 5 and seccomp; no sandbox package is auto-installed and unavailable enforcement fails closed.

**Implementation discipline:** Implementation is approved. Use failing offline tests before behavioral changes, independent code/security review for each slice and a separate whole-plan source review after integration. No commits, pushes, real installer execution or cloud operations without separate authorization.

## 1. Scope and review status

### Current host-discovery step-2 implementation

The user subsequently approved implementing the host-side discovery algorithm
in [main-workflow-action-plan.md](main-workflow-action-plan.md), step 2. This is
stdlib collector development, portable-report import and isolated verification;
it does not open the intentionally restricted devcontainer to the workstation.
The standalone collector, detailed provenance, request-only follow-up scopes,
package membership grouping and real review/render/dry-run chain are implemented.
Fresh parent verification passed 49 host tests and 267 selected core tests
(314 passed, 2 root-only skips), plus the ten-command synthetic vertical path.
Independent code/security closure and original-step-2 requirements reviews PASS.
The focused plan and `verification/step2/README.md` retain the scoped evidence.
No actual workstation collection, application, synchronization or cloud operation
occurred. This does not mark the broader plan complete or authorize a host run.

### Completed step-1 verification addendum

The preceding user instruction selected **step 1** of
[main-workflow-action-plan.md](main-workflow-action-plan.md), not another container,
sync or managed-execution workstream. Current evidence is retained at
[verification/step1/README.md](verification/step1/README.md): 267 tests across 19
selected suites, 265 passed and 2 root-only skips, plus a ten-invocation real CLI
synthetic observation/review/rescan/nonempty YAML/local+Ansible render/dry-run
chain. Current-source independent source/receipt review passed; the parent checked
all 133 reviewed source/artifact hashes. Step 1 is complete within its approved
synthetic/non-mutating scope, not whole-plan acceptance. Two relevant regressions
were fixed: explicit null desired tool location without losing observed provenance,
and metadata-only resolver ancestor traversal without broadening read grants.

This evidence supersedes stale pending-worker wording **only for that bounded
path**. The historical writer final rereview did PASS after two cycles; it is not
still awaiting that old review. Hash comparison found later source changes, so
old passes are not blanket current certification. Workspace case/error-propagation
residuals now pass current selected workspace/named/migration tests. The independent
sync rereview, separately, found an open custom `CLOUDSDK_CONFIG` exclusion defect.
Existing detailed whole-plan tables below remain historical accounting checkpoints,
not current all-green acceptance or reasons to rerun denied managed probes.

No real baseline/user-approved profile exists yet. Concrete preview is non-mutating,
not proof that a native installation is healthy or converged. Runtime-prefix and
unsupported action gaps remain explicit; actual observation needs selected roots
and approval, and apply/adoption/sync/cloud remain separately gated.

- [x] Capture the user's workspace-naming incident and current source behavior.
- [x] Record a proposed YAML interface and path-resolution rules.
- [x] Capture the corrected purpose: observations and comparison help discover desired intent; a complete desired profile is not a prerequisite.
- [x] Review the observer safety boundary, output contract and user decision workflow in section 8 (design review completed before implementation).
- [x] Implement and independently test the admitted fixture-only prototype after approval (bounded slices and remaining gates recorded below).
- [ ] Separately approve narrowly scoped observation on the actual local machine.
- [ ] Produce and refine a candidate desired profile with the user.
- [ ] Validate shared YAML semantics and non-executing adapter outputs offline.
- [x] Revisit naming code under explicit implementation approval; actual application remains gated and N1–N7 are not collectively complete.

This document began as a discussion draft; whole-plan code/isolated testing is now authorized. Historical milestones below remain historical. The current register and C01–C11 final-acceptance IDs take precedence for present status. Unchecked detailed requirements mean incomplete behavior or review, not withheld implementation permission. Checked items are scoped evidence, never collective P/N/S completion.

### Prior implementation milestone — bounded offline slices

| Slice | Implemented interface | Verification and remaining limit |
|---|---|---|
| Named workspace | `workspace.layout: named`, `workspace.name`, pure `workspace_paths.py`, CLI provenance, exact/case-collision refusal | Disposable resolution/config fixtures. No directory creation/chown by resolution; no automatic checkout adoption. All named legacy execution refuses before dispatch because application is not qualified. Legacy auto/org semantics are not promoted to safe adoption. |
| Metadata discovery | `observe` with explicit workspace selection, individual dist-info `METADATA` files and bounded `conda-meta` directories | Confinement tested on synthetic inputs. No Git execution, robotics imports, environment activation or whole-home discovery. More tools/probes remain unsupported; no actual workstation inventory has been collected. |
| Proposals and decisions | Three JSON companion documents bundled as baseline/candidate/review; `review-profile` and `--previous-report` | Evidence-backed proposals, accept/edit/reject/defer, rescan decision preservation and report validation. Candidates always non-executable; not a completed shared application YAML/export schema. |
| No-change entry | Early safe dispatch; isolated system Python; Landlock read-only + seccomp; root/unsupported paths refuse | Kernel enforcement and startup sentinel tests, invalid inputs, forbidden operations and unchanged fixture checks. `install --dry-run` remains incomplete profile-only selection, exit 2, not resolved host effects or apply authorization. |
| Narrow cloud fork pair | `--isaacsim-repo`, `--isaaclab-repo`, `--isaaclab-arena-repo`; selected refs validated and matching role variables transported | Offline Click and real inventory-rendering tests. Defaults unchanged. Full commit SHA reachability retains existing unverified behavior; custom source overrides on image-build paths refuse. No paid deployment or GPU readiness claim. |
| Safe installation/recovery/idempotence | **Not qualified / not enabled for named mode in the prior milestone** | Per-resource ownership/adoption, concurrency, stale-preview checks, tested operation-specific restore/cleanup and interruption handling remain implementation requirements; actions work is in progress, not verified here. No installer run on the working machine. |
| Sync and devcontainer alignment | **Not implemented by the prior slices; code work now in progress** | Writer/deletion rules, topology and environment-placement planning/testing are authorized implementation, not merely live gates. Actual engine, endpoints and activation require user choices and approval. No services, settings or containers started/changed. |

Usage and limitations: [`isaac-installer/docs/profile-discovery.md`](../../../isaac-installer/docs/profile-discovery.md). A design PASS or fixture PASS does not satisfy P3/P4 (real observation/user refinement), full S1–S5 application safety, or blanket Ansible parity.

**Prior offline verification receipt (2026-09-15; historical, not a run of the current workers' changes):** Parent recorded **274 tests across 15 suites**, all passing without skips: installer profile 24, workspace 17, discovery 22, safe preview 17, discovery CLI 6, sandbox regressions 10, named safety 11, shared workstation profile 11, profile command 12, privacy 4, deploy command 44, fork transport 12, deployer 57, artifact registry 18, distribution profile 9. Python syntax, changed shell syntax, `git diff --check`, documentation links and added-source security pattern checks also passed. This is a scoped offline run, not the entire repository test suite or robotics runtime acceptance. Temporary logs were recorded at `/tmp/isaac-profile-verification/`; this reconciliation inspected source/tests, not those logs, and did not rerun that receipt. Integration must record fresh commands, exit codes, skips and review results before promoting new work to verified.

**Independent review:** Cloud repository transport passed. The first installer review found a high inherited-FD sandbox escape, insufficient privilege rejection, named mutation bypasses and swallowed resolver failures. Regression-first fixes closed these; independent follow-up verified kernel/caller failure paths and named mutation refusal. A remaining discovery/name-validator mismatch was corrected to use the shared validator; the final narrow review also passed with no outstanding blockers for these bounded slices. No physical-machine experiment was used to discover or fix these issues. Review PASS does not qualify the residual/future operations below.

**Historical residuals, reconciled:** Descriptor-pinned bounded YAML reading and ordinary supplementary-group usability now have code and checkpoint fixtures; richer metadata admission avoids whole-checkout read grants. These are no longer simply missing implementations. The separate stdout/stderr-safe writer and original-root bridge exist, but its independent rereview found historical-root continuation and target-home parsing bugs C01. Named legacy mutation refusal remains necessary; direct/legacy consumers and native execution remain partial C04–C06. None of the current mechanisms is approved for this actual workstation.

### Whole-plan requirement / evidence / status / live-gate register

**Ongoing verification gate:** The execution layer explicitly denied the independent
managed-apply/recovery probe workflow. A subsequent request to renew authorization
timed out. Those probes remain blocked: no equivalent rerun is authorized by that
timeout. Pure validation/source fixes may continue, but managed qualification and
existing-resource adoption/recovery cannot be marked verified. This restriction
does not revoke the existing authorization for other code and isolated tests.

Writer cycle 2 and dataset-lock cycle 1 fixes have since been produced; fresh
independent reviews are pending. The export runtime-collision fix has a focused
independent PASS in `/tmp/isaac-full-export-rereview.json`. C04/C05/C07/C08/C09/C10/C11
have further implementation work underway; the table below is an accounting
checkpoint, not a final completion receipt. No third automatic writer fix cycle
is authorized if its final review still finds a genuine defect.

**Accounting checkpoint (not final acceptance):** Actual parent receipts `/tmp/isaac-profile-tests-vpo06eqd/results.json` record **547 tests / 32 suites** and `/tmp/isaac-profile-tests-chf2j9be/results.json` a later overlapping **107 tests / 8 suites**. All suites in both have exit 0, passed=true and zero skips. These are not additive totals, not a frozen current revision and not a new final PASS. Preserve the historical 274/15 receipt above. Current source and later module API/result files were inspected. Parent owns final tests, independent whole-plan audit and freezing verified counts. Implemented/pending review is not approval; partial/code gap includes requirements protected only by refusal. Live/user gates concern actual target choices/operations. No P/N/S group or whole plan is collectively complete.

| Requirement | Implemented behavior / real consumer inspected | Acceptance evidence and remaining proof | Implementation status | Real-operation gate |
|---|---|---|---|---|
| P1 — scope/examples/schema | `profile_discovery`, `metadata_readers`, `desired_profile.export_candidate`, shared `workstation_profile`: alternatives/declarations/full sources/runtime/placement, duplicates, complete nonempty YAML | Parent discovery/metadata/desired/schema suites; later collision correction awaits independent review | Implemented admitted schema/examples, pending integrated review | Actual installation/customization choices |
| P2 — enforced fixture prototype | Real confined observe; selected Git/worktree/common-dir, dist-info/Conda, environment/pyproject/UV metadata, rescan decisions/manual intent | Parent discovery/CLI/read/sandbox suites; dirty/index state remains unknown; writer continuation C01 blocks safety promotion | Broader prototype implemented/checkpoint-tested, review blocked | No actual observation before P3 |
| P3 — actual observation | observe-targets -> `target_observation.collect_evidence` -> `plan_evidence.validate_evidence` -> planner | Later parent target-observation 11/evidence 9; unmanaged metadata, not installed health | Collector/bridge implemented; no actual workstation baseline | Physical target/read roots/budgets or sanitized metadata |
| P4 — desired intent/review/export | Real observe --empty, review-profile --decision declare, export-profile; full reviewed source/runtime/native intent; JSON/YAML via `profile_output` -> `report_writer` | Parent workflow/output/writer; focused export-collision rereview PASS; C01 writer final review pending | Real vertical code implemented; partial/security-review blocked; no actual approved profile | User values/new destination; intent not apply |
| P5 — shared semantics/consumer evaluation | render-profile, `profile_adapters`, actual legacy parser/config; DeployCommand --software-profile -> actual Deployer inventory -> roles | Parent adapter/transport; worker real INI/syntax; new local pins/archive and isolated Ansible runtime receipts pending review; C07–C10 | Real transport implemented, partial consumer coverage | Actual selected sources/runtime; deployment separate |
| N1 — naming semantics/regressions | Case-preserving named/flat grammar, explicit collision/override/legacy path policy | Parent workspace 27/profile 24 and migration 12 checkpoints; ASCII/internal-space policy explicit | Bounded semantics checkpoint-tested; full application not implied | Actual spelling/reuse choice |
| N2 — parse/validate | Legacy workspace and shared typed schema; bounded descriptor-pinned YAML parser, duplicates/required-unresolved validation | Parent profile/read-boundary/desired/schema suites | Implemented/checkpoint-tested, final integration review pending | None for fixture code; actual new output separately selected |
| N3 — CLI precedence | Early review/export/plan/render/migration/observe-targets and desired-profile status/audit/dry-run entry | Parent CLI/workflow/output; C01 repeated/equals target-home exclusion mismatch and final cross-entry audit remain | Implemented/pending security closure | None for isolated code/tests |
| N4 — pure resolution/concrete preview | `workspace_paths.resolve_paths` consumed by actual shell destination helper, action planner and migration; observe-target evidence bridge | Parent workspace/migration/planner/evidence; legacy stage-only dry-run and native runtime/action gaps C04 | Pure paths/concrete planning implemented; execution agreement partial | Exact actual host/home/actions |
| N5 — all consumers/compatibility | Shared destination/named active helpers, bounded ambiguity refusal; four generic presets/README and docs/workspace-consumer-matrix.md; real migration-profile | Matrix exposes state/drift/repair/generated-launcher selection gaps C05; named refusal not consumer implementation | Trace/docs implemented; all-consumer agreement partial | Actual adoption/reuse choice |
| N6 — repository identity/adoption/update | Inspection-only inspect_adoption; managed new-only files/local pinned Git/stdlib venv fixture adapters | Parent managed 33; actions fix receipt; independent rereview FAIL C02; existing-resource/fork/submodule/LFS C06 remains | Bounded code implemented/pending fixes/review; full policy partial | Actual action/preservation/recovery choices |
| N7 — IsaacAutomator reuse | Actual local/Ansible target-home transport; isolated GR00T/LeRobot role placement and Arena SHA added | Parent adapter/deployer/regressions; runtime worker receipts pending review. Packer C07, serving C08, runtime C09 | Partial real consumers, no local/cloud parity | Separate runtime/cloud acceptance/spending |
| 8B — repository/ref routing | Selected repo/ref flags/inventory; controller anonymous public preflight/downloader fixes reported; Arena role SHA branch | Historical narrow PASS retained; profile SHA checks repository advertisement NOT commit existence/reachability; target Git/auth C10 | Narrow routing delivered; new fixes pending review; source proof partial | Actual source/ref/archive/network/deploy approval |
| 8C — genuine no-change action preview | Early safe entry; desired-profile action targets/reasons/effects/evidence/status; shared bounded fixture planner | Parent planner/workflow/evidence; legacy --config/--profile dry-run remains stage-only; native paths/actions C04 | Concrete desired-profile preview implemented; full command/consumer requirement partial | Actual reads approved; apply separate |
| S1 — pre-init read-only confinement | Landlock/seccomp, pinned bounded readers, ordinary supplementary-group positive path, pipe/TTY stdout/stderr, private exclusive writer/origin exclusions | Parent sandbox/read/output/writer; readonly review closed prior reader defects but failed collision; writer rereview two high C01 findings | Implemented usable fixtures; SECURITY REVIEW BLOCKED | Actual enforcement/read/output budget approval |
| S2 — ownership/containment/concurrency | Descriptor-relative Root/locks/identity, exact plan validation, new-only publication | Parent managed receipt/fix; rereview C02 open; no adoption from marker/path/clean status; native apply C04/C06 incomplete | Partial operation-specific implementation, pending fixes/review | Exact actual host/user/profile/resources/actions |
| S3 — high-risk/preservation boundaries | Early offline denial and managed unsupported high-risk/native actions; no approval inherited from --yes/resume/profile | Parent sandbox/action tests; legacy mutation not qualified by managed guards; C04/C06 remain | Partial protections; refusal not full operation implementation | Separate maintenance/settings/environment/link scope |
| S4 — recovery/interruption/idempotence | Apply journal/failed-run gate, review_recovery, managed-file backup/alternate restore, Git/venv postconditions | Managed 33 checkpoint; rereview RLOGIC-1/2 and unexecuted independent probes C02; file recovery not repo/environment/package recovery C04/C06 | Bounded mechanisms implemented/pending fixes/review; broader recovery partial | Actual storage/capacity/consistency/rescue |
| S5 — sync/devcontainer safeguards | Policy/candidate/runtime-placement, actual disposable rsync, actual SyncthingREST/Supervisor; cross-host SelectedTransfer.seed in progress | Supervisor worker receipt: 45 tests/three suites; parent remote/supervisor subset: 46 tests/four suites (overlapping), not native engine; independent FAIL C03; continuous cross-host C11 distinct from one-shot | Beyond policy implemented; review blocked/partial, native unverified | Actual engine/endpoints/seed/deletion/versioning; activation/settings/hooks separate |
| 8E — incremental acceptance | Review declarations/required-optional coverage and per-action evidence remain distinct from apply authorization | Register/checklists/C01–C11; bounded unsupported adoption does not erase whole-plan N6 | Accounting updated; independent whole-plan audit outstanding | Actual per-item decisions separate |

### All six authorized workstreams — implemented slices, remaining integration and review

These six workstreams implement the whole user-authorized plan, not six reduced demonstrations. Current code/evidence is listed below; parent integration, final tests and separate whole-plan review are still required. Safety gates on real operations do not revoke already-authorized missing code development.

| Step / owner | Authorized deliverable and requirements | Acceptance before status promotion | Remaining live/user gate |
|---|---|---|---|
| A1 — YAML worker | Full reviewed shared declarations/sources/runtime/YAML and strict required/optional/duplicate/dependency guards now implemented | Parent desired/schema/workflow fixtures; later runtime-collision fix and changed consumer assertions need independent integration review | User actual values/new output destination, not implementation permission |
| A2 — discovery worker | Bounded Git/worktree/common-dir, package/environment/pyproject/UV metadata, alternatives/manual intent/rescan decisions implemented | Parent metadata/discovery/CLI fixtures; dirty state unknown; C01 historical-root continuation remains | Actual selected roots/probes/exclusions/intent |
| A3 — adapters worker | Real local parser/config and Click-to-Deployer-to-role transport; local Lab pins/PyPI/archive pair and isolated Ansible runtimes/Arena SHA added | Parent adapter/transport and later worker receipts; final review and C07–C10 still pending | Actual cloud/source/runtime selection and operation acceptance |
| A4 — actions worker | Concrete planner/observed-target evidence, new managed files/local pinned Git/stdlib venv, locks/journal/backup/alternate restore implemented | Managed 33 checkpoint; independent rereview FAIL C02; broader native/adoption/recovery C04–C06 | Actual action/adoption/recovery approval, not fixture-code permission |
| A5 — sync worker | Policy/topology/runtime placement, actual disposable rsync and pinned Syncthing REST supervisor implemented; selected cross-host seed worker active | Supervisor worker 45/three-suite synthetic receipt and parent overlapping 46/four-suite subset; independent FAIL C03; selected transfer and continuous cross-host C11 | Actual engine/endpoints/seed/deletion/versioning; activation/settings/hooks separate |
| A6 — sandbox worker | Pinned bounded readers, ordinary-account path, early deny and pipe/TTY-safe separate writer implemented | Parent sandbox/read/output fixtures; writer rereview FAIL C01 and export collision rereview pending | Actual enforcement/budgets/read scope approval |

- [x] Real observation/manual-review → reviewed desired YAML → actual local/Ansible mapping → concrete action preview wiring has checkpoint fixtures. This is a wiring checkbox only, not acceptance of every selected field/action or actual user intent.
- [ ] Parent integrates later worker results, reconciles stale/failed test assertions, independently closes review findings, then records final commands/exit codes/skips. The 547/32 and overlapping 107/8 receipts are checkpoints, not current-final counts.
- [ ] Separate whole-plan source review checks every P/N/8B/8C/S item, original validation matrix, adoption/update/fork/submodule/LFS backlog, Packer/consumer coverage and actual sync/apply implementation, including omissions outside the changed diff. Update both this register and detailed checkboxes only after verification.

**Later evidence and failed reviews:** Module API/result files were inspected, including `/tmp/isaac-full-{bridge-integration-result,migration-complete-result,target-observation-result,actions-fix-result,supervisor-result,selected-transfer-api,local-consumer-result,ansible-runtime-result,preflight-fix-result,public-artifact-result,export-conflict-fix}.json`. Source/later evidence supersedes stale initial worker omissions. `/tmp/isaac-full-{writer-rereview,actions-rereview,supervisor-review,readonly-final-review}.json` all record **passed=false**. The collision worker reports a correction, not independent clearance. Intermediate failures after concurrent support/downloader/preflight changes require parent reconciliation; do not hide them behind earlier passing checkpoints.

### Actual decisions versus implementable gaps

**Actual user decisions before the corresponding operation:** physical target/user/home; selected roots/probes/exclusions and read/report budgets; final workspace spelling/reuse if conflicting; desired components/sources/versions and each custom item's purpose/requiredness/environment placement; new profile/report destination and retention; actual checkout adoption/update actions; recovery destination/capacity/consistency and rescue path where applicable; sync engine/endpoints/direction/seed/conflict/deletion/versioning; deployment configuration/IAM/spending/cleanup. No actual-machine choices are inferred from examples or this devcontainer.

**Engineering work, not renewed user authorization:** C01–C11 distinguish actual remaining code from real-target approval. Reviewed schema/export, broad admitted metadata, real adapters, concrete planner/evidence bridge, ordinary-account confinement and sync protocol code now exist; their current independent findings and exact remaining consumers still require fixes/review. Do not erase adoption/update/Packer/continuous cross-host requirements because bounded supported slices can refuse them.

### In scope first

- More intuitive shared profile YAML, discovered from the user's working setup and preferences rather than designed entirely from assumptions.
- Observation → evidence/questions → candidate desired profile → user review → comparison/refinement.
- Custom grouping-folder names such as `BoredEngineer` or any other valid user-selected name.
- Clear separation of workspace root, workspace name, repository name and remote identity.
- Predictable precedence, collision handling and non-mutating preview.
- Compatibility with existing installer profiles and existing checkouts.
- Incremental discovery of custom dependencies/tools (section 8.1A), genuine no-change dry-run (8C), enforceable workstation protection (8D), and per-capability review/acceptance (8E). Code and isolated verification are authorized; these requirements do not authorize real-target execution.

### Original later requirements — retained in the authorized whole-plan backlog

These were outside the first offline milestone, not abandoned requirements. Design and isolated implementation may proceed; actual application and operational acceptance remain separately gated. A narrow new-resource action or adapter does not complete the broader requirements below.

- Full repository adoption/update/repair policy, branch/tag/commit selection, submodules and Git LFS.
- Fork creation, origin/upstream configuration and push protection.
- Installation environments, version-change reruns and trustworthy success receipts.
- Shared local/cloud profile transport and runtime parity.

Arena decoupling is explicitly **not current scope**; it was a far-future thought, not an architectural direction approved for this work. No new overarching redesign, private-repository rollout or cloud experiment is part of this update. Arena/submodule metadata may be observed to describe the current setup, not to restructure it.

No automatic folder rename, merge, deletion, repository relocation, reset, clean, stash, checkout, remote rewrite or ownership rewrite is authorized by a naming change. Do not modify existing `.devcontainer`, VS Code settings, AGENTS.md or credential files as part of this plan.

The working local machine is not an installer test fixture. A branch, worktree or backup alone is not isolation. Shared YAML does not synchronize local edits, environments, models or results; cloud deployment is neither a backup nor evidence of local/cloud equivalence.

## 2. Incident and source-backed findings

### User report

The installer created `~/Documents/GitHub/boredengineering` although `~/Documents/GitHub/BoredEngineer` already existed. The user remembers a default based on the user identity when no workspace name was supplied and wants a reliable custom-name mechanism.

`BoredEngineer` and `boredengineering` are different names, not merely different capitalization. The later spelling `BoredEgineer` in discussion has not been confirmed as a requested rename. Examples preserve the reported existing name; implementation must preserve any explicitly chosen valid spelling.

### Source findings before the first implementation milestone (historical)

Paths below are repository-relative; line references are historical inspection anchors, not permanent API locations. Preserve these incident findings, but do not mistake them for the current diff: root resolution is now pure, explicit named selection and workspace CLI precedence exist, and 8B transports repository URLs. Legacy auto/org discovery/adoption remains distinct and unqualified. The current accounting register above takes precedence for delivered status.

| Area | Inspected evidence | Consequence |
|---|---|---|
| Root resolution | `isaac-installer/lib/core/git_workspace.sh:7-29` | Resolving a root can create directories and recursively chown Documents; it is not currently a pure read. |
| Destination resolution | `isaac-installer/lib/core/git_workspace.sh:96-162` | Explicit per-repo path wins; flat layout bypasses owner nesting; otherwise configured owner precedes inferred fork owner, followed by case-insensitive directory lookup. |
| Claimed duplicate protection | `isaac-installer/lib/core/git_workspace.sh:136-151` | `find -iname` cannot equate `BoredEngineer` with `boredengineering`; first-match selection can hide ambiguity. Candidate selection can also fall through to a remote-owner folder. |
| Existing checkout discovery | `isaac-installer/lib/core/git_workspace.sh:59-93,165-177` | Discovery is separate from destination calculation; it selects by directory name rather than a fully reviewed repository identity/adoption contract. |
| Installer consumers | `isaac-installer/lib/modules/isaaclab.sh` | Installation uses destination resolution; a status path uses active-checkout discovery. These can disagree. |
| Profile export | `isaac-installer/lib/core/profile_parser.py:36-73` | Generic key flattening does not establish that a new YAML field has a consumer or semantic validation. |
| Config precedence | `isaac-installer/lib/core/config.sh:111-118`; `isaac-installer/bin/isaac-installer:782-808` | CLI workspace options are parsed before loading a profile; profile assignments can overwrite layout/owner. |
| Existing repository setup | `isaac-installer/lib/core/git_workspace.sh:402-484` | Existing paths can still have remotes rewritten and refs checked out; naming is not the whole preservation problem. |
| Cloud Lab checkout | `src/ansible/roles/isaaclab-source/tasks/install.yml:25-74` | Marker-gated Git task uses `force: true`; cloud behavior is not equivalent to safe adoption of a developer checkout. |

Git history inspected during discussion showed an earlier ordering of remote owner, configured owner, then GitHub login/Git author name. A subsequent change prioritized configured owner and removed the user-identity fallback, but retained the inadequate case-insensitive safeguard. Historical implementation claims do not establish correct behavior.

### Bounded reproduction already performed during discussion

A temporary fixture contained `BoredEngineer/IsaacLab/.git`. The current destination helper was invoked with user detection and root resolution replaced by no-op/read-only fixture helpers. No Git, network, installer or real home-directory operations were invoked.

- Remote owner `boredengineering`, no explicit workspace owner: selected `boredengineering/IsaacLab`.
- Remote owner `boredengineer`: selected existing `BoredEngineer/IsaacLab`.
- Explicit workspace owner `BoredEngineer`: selected `BoredEngineer/IsaacLab`.

This reproduces the destination-selection mechanism, not the complete historical installation. Original invocation inputs/logs were not recovered. That original discussion fixture was not a committed regression test. The subsequent `src/tests/installer_workspace_contract.test.py` and pure named resolver now cover bounded naming behavior; actual naming application and broader migration/adoption remain incomplete.

## 3. Separate the concepts

| Concept | Example | Meaning |
|---|---|---|
| Workspace root | `~/Documents/GitHub` | Base directory on the selected target host. |
| Workspace name | `BoredEngineer` | User-chosen local grouping folder; not a GitHub identity. |
| Repository directory | `IsaacLab` | Local checkout name; existing per-component overrides need precedence review. |
| Remote owner | `boredengineering` or `isaac-sim` | Git hosting namespace; not an implicit workspace folder selection. |
| OS user | Target workstation account | Determines home expansion and execution ownership, not the workspace name. |
| GitHub login / Git author | Separately configured identities | Neither is a reliable mandatory folder-name source. |

A developer workstation can be local or cloud-hosted. Reproducible managed installation versus user-owned development checkout is a separate distinction, not a synonym for local versus cloud.

## 4. Workspace YAML contract — implemented parsing/export; application partial

`root`, `layout: named` and `name` parse and resolve with explicit CLI precedence. Shared desired YAML/schema and real local/Ansible transport now exist. The example never authorizes GitHub Desktop/fork/workspace mutation. Migration preview exists; adoption/application and missing consumers remain P5/N7/C04–C10.

```yaml
workspace:
  root: "~/Documents/GitHub"
  layout: "named"
  name: "BoredEngineer"
  auto_register_github_desktop: true
  auto_create_fork: false
```

Expected intent for this example:

```text
~/Documents/GitHub/BoredEngineer/IsaacLab
~/Documents/GitHub/BoredEngineer/IsaacLab-Arena
~/Documents/GitHub/BoredEngineer/Isaac-GR00T
```

The enabled component set still controls which repositories are needed. This example does not enable GR00T or create all listed paths. Repository URLs, upstreams and revisions remain in their existing separate configuration areas.

Proposed layout meanings:

- `named`: `root/name/repository`; require a nonempty explicit name at execution time.
- `flat`: `root/repository`; reject a nonempty name rather than silently ignore it.
- Legacy `auto`/`org` plus `default_owner`: support through a reviewed compatibility/migration path, not silent reinterpretation.

Do not change every public preset to a personal name. Keep reusable examples generic and user selections in explicitly selected user profiles. Do not introduce a schema version value until migration/versioning is agreed.

## 5. Proposed tool behavior

### 5.1 Precedence and persistence

1. Explicit CLI override, including an intentional supported clearing value.
2. Explicit selected profile setting.
3. Documented default where the selected layout permits one.

`--workspace-name` is now implemented, including the admitted offline preview. `--workspace-root`/`--workspace-dir` and owner aliases are also wired. Explicit clearing is tested; inherited operational `WORKSPACE_*` values do not override a selected profile and CLI provenance is cleared on entry. Wider compatibility/migration UX remains to be reviewed; do not reintroduce inherited values leaking across loads.

An interactive setup flow may suggest a name or offer existing folders. Installation in unattended mode must not prompt indefinitely or guess a named workspace. Persist a user's selected name only through an explicitly authorized profile write, never as a hidden side effect of preview/install or by overwriting a shared preset.

### 5.2 Pure resolution followed by explicit actions

- Expand `~` against the selected target user's home, not the controller/root account's home.
- Validate inputs and inspect relevant paths without mkdir, chown, Git fetch, cloud/GitHub calls or login discovery.
- Produce the chosen path, the source of each effective setting, existence/type information and conflicts.
- Do not resolve ambiguity by taking the first directory returned by the filesystem.
- Execution rechecks preconditions before creation/adoption; account for paths changing after preview.
- Create only missing, approved directories; never recursively chown a pre-existing Documents/workspace tree.
- Use argument arrays/quoted path handling, not shell interpolation of profile data.

### 5.3 Names, collisions and containment

Recommended initial rules, subject to review:

- **User-approved naming policy: case-preserving names, exact selection, case-insensitive collision detection.** Preserve the user's chosen spelling/case; never automatically lowercase or substitute another folder's spelling. The bounded pure resolver is implemented/tested; the whole code scope is authorized, but actual filesystem changes require separate approval.
- An exact existing directory is the selected path, not permission to modify repositories inside it. For case-only alternatives, report the conflict and require explicit user selection before reuse or creation; unattended execution must stop with an actionable error rather than guess or hang on a prompt. Apply this policy consistently regardless of whether the target filesystem permits case-only duplicates.
- Example: choosing `BoredEngineer` selects that exact spelling. Choosing `boredengineer` when `BoredEngineer` exists requires a decision; explicit reuse retains `BoredEngineer`. `boredengineering` remains a distinct name, not a case variant or inferred alias of `BoredEngineer`.
- This rule concerns local workspace folder naming. It does not normalize repository URLs or Git refs. Unicode comparison/normalization details remain open under D7; do not introduce silent normalization.
- Support internal spaces with correct quoting.
- Reject empty or whitespace-only names, `.`/`..`, separators and control characters. Decide whether leading/trailing whitespace is rejected rather than normalized.
- Do not lowercase, fuzzy-match, correct spelling or infer aliases from remote ownership.
- For a case-only existing-folder conflict, report it and require explicit selection/reuse; do not create an ambiguous duplicate silently.
- A distinctly named existing folder is not automatically equivalent. Similar-name hints may be advisory only, never authorization to reuse/move.
- Detect symlinks and dangling symlinks. Initially fail closed on unsupported symlink cases; agree which explicitly selected symlink roots can safely be supported.
- Distinguish missing path, existing directory, regular file, unreadable path and ambiguous candidates.
- Ensure the intended grouping directory remains within the approved resolved root. Define mount/symlink handling before claiming containment.

### 5.4 Existing repositories: minimum boundary for naming work

Reusing a workspace folder does not grant permission to modify its repositories. Inspect existing checkouts separately. Do not automatically rename or merge the two folders from the incident.

When configured destination and discovered checkout differ, preview both and stop that repository's mutation pending an explicit choice. The first naming slice may report unsupported adoption scenarios rather than implement a destructive migration tool.

## 6. Compatibility and migration proposal

- Preserve original profiles and folders; provide a non-mutating migration preview.
- If both `name` and `default_owner` are present, reject conflicting values; review whether equivalent values are permitted with a deprecation warning or rejected uniformly.
- Do not translate legacy `default_owner` into a promise that every old `auto`/`org` profile resolved identically. Preview actual old/new paths and conflicts.
- Clarify the role of per-repository directory overrides: recommended explicit override wins, but must be reported and validated; no silent adoption elsewhere.
- Keep compatibility adapters bounded. The newer workstation-profile schema currently requires a separate installer adapter; adding a legacy field does not complete that transport.
- Do not persist controller-specific absolute home paths as portable cloud intent. Real local/Ansible adapters resolve against explicit target home; target runtime/native behavior remains separately unverified.

## 7. Decision register — bounded implementation choices versus actual user decisions

The statuses below record the existing bounded contract, not retroactive user approval of every design detail. Remaining engineering choices can be developed/tested conservatively under current authorization; actual-machine values and changes require user selection. D1–D17 are not a blanket pause on code work.

| ID | Question | Recommendation | Status |
|---|---|---|---|
| D1 | Public field name? | `workspace.name`, separate from remote owner. | Implemented legacy and shared reviewed YAML; current review/integration limitations in register |
| D2 | Layout names and default? | Add `named`; retain `flat`; migrate legacy modes explicitly. Preserve current default until reviewed. | named/flat and legacy auto retained; shared resolver and nonmutating migration-profile implemented; migration apply unsupported C06 |
| D3 | Missing name? | Require it for named execution; interactive setup can suggest and persist a confirmed choice. | Missing named value rejected; optional interactive suggestion/persistence UX not part of current noninteractive acceptance; actual selection via review/export |
| D4 | Username suggestion source? | Optional explicit setup-time suggestion only; no implicit GitHub calls or Git author-name fallback. | Open |
| D5 | Case handling and case-only collisions? | Case-preserving names, exact selection, case-insensitive collision detection; require explicit resolution and preserve chosen spelling. No automatic lowercase/substitution; unattended ambiguity fails closed. | Pure resolver/checkpoint fixtures preserve case and collisions; migration preview implemented; real application remains blocked/unqualified |
| D6 | Aliases such as the incident's names? | Explicit workspace selection is sufficient initially; defer a general alias registry. | Exact selection implemented; no alias inference; no user request for a general registry established |
| D7 | Allowed characters and root paths? | Spaces supported; reject unsafe segments; settle Unicode, whitespace, relative roots and symlinks with tests. | Initial ASCII/internal-space grammar; surrounding whitespace, relative roots and symlink traversal refuse. Unicode/supported-link extension remains explicit design work, not silent normalization |
| D8 | Legacy keys and CLI flags? | Preview migration; define conflict/deprecation behavior, no silent precedence changes. | Precedence/clearing/reloads and shared old/new migration preview implemented; all-consumer compatibility C05 still partial |
| D9 | Where does a user's selection persist? | Explicit user-selected profile, with no overwrite of existing content without approval. | Separate explicit private export writer implemented; C01 security defects block approval; actual destination/retention is user choice |
| D10 | Existing checkout adoption? | Report identity/state and require an explicit policy; naming does not authorize Git mutation. | Full policy/qualification remains authorized design/code backlog; real adoption choice not made |
| D11 | Shared implementation boundary? | Reuse the existing profile architecture; choose one tested resolution specification before Bash/cloud adapters. | Shared resolve_paths now consumed by actual shell destination/planner/migration; shared YAML/adapters implemented; C05 residual consumers remain |
| D12 | What is discovery for? | Use observed evidence and comparison to find the desired profile; automatically propose, but do not silently approve intent. | User-confirmed direction |
| D13 | Where may observation run first? | Disposable fixtures only; real-machine access requires independent safety review and explicit approved paths/operations. | Fixture prototype exercised; actual target/path approval still pending |
| D14 | How broad is the first observer? | Workspace/repository metadata is a first slice, not the whole goal. Admit custom tool/package/environment probes incrementally under 8.1A/8D; do not require the full catalogue up front. | Explicit Git/worktree/common-dir, package/Conda and environment/pyproject/UV metadata readers implemented; dirty/index state unknown; actual roots unselected |
| D15 | Which output may be written? | New explicitly selected local report/candidate files only; no overwrite of active profiles or private-data publication. | Integrated stdio-safe private writer and original roots bridge implemented; historical continuation/target-home exclusion bugs C01 still open |
| D16 | Which YAML is the candidate targeting? | Review the existing workstation-profile schema and legacy adapter limits; do not invent a third executable format or weaken baseline rejection. | Existing workstation-profile schema reused for full reviewed YAML and actual local/Ansible adapters; collision review and selected consumer gaps remain |
| D17 | What happens to uncertain proposals? | Keep unresolved questions in the report; never convert unknown to healthy, disabled or approved intent. | Review/rescan and YAML preserve unknown/required-unresolved/optional distinctions; generic intent completion never grants consumer/apply completeness |

## 8. Immediate workflow: discover the desired profile safely

### 8.1 Purpose and three distinct outputs

The observer is not merely an inventory utility. Its purpose is to help the user discover what the desired profile should express. It must work when no desired profile exists yet.

1. **Observed baseline:** bounded facts about the selected target, with evidence and limitations. This is not executable installation intent.
2. **Candidate desired profile:** proposed settings inferred from evidence plus the user's stated preferences. It may be incomplete. Every proposal remains distinct from a confirmed decision.
3. **Review/comparison report:** initial ambiguities and proposal rationale, then differences between observations and the evolving candidate. There is no meaningful conformance verdict against an absent desired profile.

Loop: observe → propose → ask/review → revise candidate → compare → resolve or retain uncertainty. Approval of the resulting profile means “this describes what I want,” not “apply it to my machine.”

Do not classify every difference as drift or repair work. A difference can be intentional, obsolete, a future desired change, unsupported, or not yet understood. The tool should propose sensible values proactively instead of making the user specify everything from scratch.

### 8.1A Custom tools and dependencies — reserved discovery space

**User clarification:** The unique tools/dependencies are not all known yet; discovering them is part of the goal. Do not require a complete customization catalogue before designing or implementing the now-authorized bounded observation/proposal workflow. Leave explicit space for these findings instead of guessing requirements or narrowing the eventual inventory to repositories alone.

The intended outcomes remain: bounded inventory, evidence-backed candidate profile, user-reviewed customizations, predictable case-preserving workspace naming, safer existing-path handling and a genuine no-change dry-run. Unknown customizations do not invalidate this direction. Inventory is not a complete backup, and partial coverage must remain visible.

Reserve a **customization discovery backlog** in the companion review report. Start empty; entries may come from bounded observations or the user's manual notes. Do not fabricate an inventory of the physical machine.

| Information to capture when known | Purpose |
|---|---|
| Tool/dependency/customization name | Identify the item without assuming it belongs in the final profile. |
| Location and environment | Distinguish host, devcontainer, Conda/UV environment and project-local installation. |
| Observed version/source and evidence | Record what is established; leave unavailable details unknown. |
| Purpose or workflow | Ask why it matters; installation alone does not establish necessity. |
| User decision | Include, exclude or leave unresolved. |
| Profile/installer/Ansible support | Mark existing support, a proposed mapping or an unimplemented extension explicitly. |

**Authorized code extension point, not a new framework:** keep observation and profile-mapping logic modular so individual custom-item readers/mappings can be added and tested. Extend the inspected `profile_discovery.py`/shared profile boundaries rather than inventing an unrelated framework. A documented TODO or unsupported-item result is sufficient until an item is understood; do not add arbitrary shell hooks, install commands from discovery, a plugin system or a no-op handler that claims success.

An undiscovered or optional unresolved item need not block a useful partial report or continued profile review. If the user selects an item as required but its installation mapping is unsupported, report that limitation and block claiming/applying a complete supported profile for that scope. Do not silently omit it or fabricate defaults. Full-machine parity remains unproven until actual coverage and acceptance justify it.

This remains authorized incremental work. Bounded metadata, alternatives/manual declarations, reviewed full YAML and narrow real local/Ansible custom-PyPI consumers now exist. Unknown optional tools remain useful partial reports; selected required unmapped declarations remain explicit C09 code gaps, not guessed hooks or full-machine parity. No actual-machine scan/profile change is authorized.

### 8.2 Evidence and decision contract

For each observation record a stable item/check ID, target identity without secrets, selected path, collection time, method, bounded result and status (`observed`, `conflicting`, `inaccessible`, `unknown`, or `not_selected`). Human-readable reports must explain what a check cannot establish. File presence and package metadata do not prove runtime compatibility.

For each proposed field record:

- Candidate value and the observation IDs or explicit user preference supporting it.
- Rationale, alternatives and uncertainty; do not imply numerical confidence is measured.
- Review state: proposed, accepted, rejected or unresolved.
- User decision and reason where provided; source revision of the baseline/candidate so later observations cannot silently replace accepted intent.

Keep this metadata in a companion report rather than inserting unsupported keys into executable YAML. Draft serialization must respect the selected schema. If required values are unresolved, report the candidate as incomplete and block executable export; do not fill gaps with plausible defaults. Preserve the existing distinction between `workstation-baseline` and executable profiles.

Examples for review, not observations already made on the physical machine:

| Evidence scenario | Useful proposal/question | What must not happen |
|---|---|---|
| Existing `BoredEngineer` folder and differently named remote owner | Propose the existing local name; ask whether to preserve it. | Infer a move/rename or choose the remote owner instead. |
| Checkout has local changes | Propose preserving this development checkout; ask whether reproducibility from a base revision is also required. | Claim the base commit reproduces uncommitted work, or collect private diffs automatically. |
| Arena has submodule pins and external symlinks | Describe both and ask which arrangement belongs to the working setup. | Restore pins, replace links, change branches or decouple Arena. |
| Multiple Sim installations | Offer candidates with available metadata; ask which is used for the working workflow. | Choose the newest or run launchers to decide without authorization. |
| An observation differs from accepted intent | Show the discrepancy and retain the user's choice until reviewed. | Rewrite intent or “repair” the machine automatically. |

### 8.3 Independent observer, not an installer dry run

Use the installer's configuration topics as a checklist, not its check/install/repair functions. Previously inspected `check_isaac_sim()` can write EULA markers and runtime bridges; root-resolution helpers can mkdir/chown. Do not source broad installer initialization to collect facts.

Before each probe is admitted, document exactly what it reads, subprocesses it invokes, possible indirect writes/network access, failure behavior and what its result proves.

Required initial restrictions:

- No sudo, package operations, environment activation, Python imports from observed environments, Sim launch, service changes or model downloads.
- No Git fetch/pull/checkout/reset/clean/stash/submodule update, automatic authentication, network or cloud operations.
- Restrict reads to approved roots and metadata. No broad home scan, file-content diffs, `.env`, credential stores, unrestricted environment dumps or copied configuration trees.
- Git inspection must account for optional index writes, fsmonitor/external helpers, repository config/includes, partial-clone fetching, pagers and worktree `.git` indirection. Design and test safe invocations or bounded metadata readers; a command called “status” is not inherently admitted.
- Redact credentials in remote URLs before rendering or logging; avoid reading config includes that escape approved roots. If a safe result cannot be obtained, report unknown rather than relaxing access.
- Treat paths/metadata as untrusted data: argument-safe execution, bounded output, escaping of terminal control characters, timeouts and cancellation.
- Detect symlinks and root escape; deny out-of-scope traversal rather than following it silently. Metadata and file names can be private too: keep reports local with restrictive permissions and no automatic commit/upload/telemetry.
- No writes to inspected paths. The only application-requested persistent writes are new files in an explicitly approved report destination, outside inspected roots, with overwrite refusal and restrictive permissions. Do not promise zero filesystem-level effects such as access-time updates from ordinary reads; stronger read-only/snapshot enforcement must be chosen before making that claim.

Independent review must approve the concrete observation mechanisms and confinement before a real-machine run. The prior bounded implementation has scoped fixture/security evidence, not blanket safety for new probes or actual-machine use. New workers' mechanisms require fresh integrated review. Existing devcontainer mounts or Docker access must not be assumed isolated.

### 8.4 Immediate stages and approval gates

#### P1 — Review output examples and scope

- [ ] Complete integrated review of D12–D17: shared YAML/export/declarations are implemented and checkpoint-tested, not merely JSON companions. Collision correction and writer C01 remain review blockers. Unknown optional custom-item coverage stays in 8.1A without blocking unrelated discovery.
- [ ] Complete independent review of expanded synthetic examples: multiple repository/runtime alternatives, manual declarations and no-profile paths are checkpoint-tested; dirty/index state is conservatively unknown rather than a false reproducibility claim. No actual installation was inspected.
- [x] Select implementation/test paths after locating reusable boundaries: `profile_discovery.py`, `discovery_cli.py`, `workspace_paths.py` and the installer discovery/workspace suites. `observe` and `review-profile` are now real, scoped commands; new worker APIs are not certified by this checkbox.

#### P2 — Fixture prototype delivered narrowly; extend under current approval

- [x] Prior observation/proposal/decision-loop tests and regression-first security fixes are recorded in the prior receipt; failing tests remain required for every new behavioral extension.
- [x] Add bounded synthetic Git/worktree/common-dir/submodule metadata and multiple-installation fixtures (`installer_metadata_readers` 25 and discovery 30 at checkpoint). These inspect admitted metadata, not full dirty/index state or private project copies.
- [x] Prior CLI fixture paths enforce Landlock/seccomp denial of writes/network/helpers and inherited FDs; negative controls are in the safe-preview/sandbox suites. No host Docker socket or writable real-home target is admitted. New readers/writers require renewed technical verification, not renewed code authorization.
- [ ] Complete integrated startup/unchanged-state review across all new probes/writers. Parent metadata/CLI/sandbox fixtures now cover nofollow/mount/limits/helper refusals; full Git index/dirty observation is not claimed, and writer C01 remains.
- [ ] Complete independent review of the broader integrated prototype; the prior narrow safety/proposal review passed. No fixture PASS authorizes real-host access or establishes robotics runtime compatibility.

#### P3 — Separately approved bounded local observation

- [ ] Confirm the actual target machine; this repository's devcontainer is not automatically the user's physical workstation.
- [ ] Agree explicit read roots, admitted commands, exclusions, report destination, resource limits and enforcement mechanism with the user; satisfy section 8D S1 and applicable target/path protections first. No agent should guess host paths or escalate privileges.
- [ ] Only after approval, execute the admitted observer and verify its action log/output scope. If adequate protection is unavailable, stop and offer user-supplied sanitized metadata; do not substitute a cloud deployment.
- [ ] Record actual coverage and limitations. No install, repair, runtime smoke test or automatic profile application follows this step.

#### P4 — Discover and approve desired intent with the user

- [ ] Generate the user's actual proposals from evidence/preferences. The mechanism is prior fixture-verified; P3 or user-supplied metadata is still needed for actual intent discovery, not a prewritten desired profile.
- [ ] Review the user's meaningful choices in small groups. Prior code supports accept/edit/reject/defer; no actual candidate acceptance is recorded here.
- [ ] Recompare the actual user candidate and expose unresolved dependencies/unsupported fields. Code now preserves review/rescan decisions and full shared YAML; no actual user candidate has been accepted. Collision fix and writer review remain engineering, not user intent.
- [ ] Finish safety review of implemented export-profile JSON/YAML and separate new-file writer; parent checkpoint fixtures exist, but C01 historical exclusions/argument canonicalization and collision rereview remain. Only then use an explicitly approved new destination; never active profile overwrite or inferred apply.

#### P5 — Offline shared-profile evaluation

- [x] Implement field-by-field local/Ansible coverage and actual transport (`profile_adapters`, real legacy parser/config, Click/Deployer inventory/roles). This is offline mapping evidence; selected unsupported fields and C07–C10 remain visible.
- [ ] Complete independent evaluation of current adapters/real consumers. Parent adapter/transport fixtures pass at checkpoint; later local pins/archive and isolated Ansible runtime/Arena SHA have worker receipts, not final integration approval.
- [x] Report schema validity, per-field mapped/not-selected/unsupported coverage and configuration consistency separately from runtime acceptance; render/apply/runtime/reference flags remain distinct. Final independent review is still pending.
- [ ] Record this offline evaluation independently, then continue the authorized N1–N7/8C/S1–S5 code and isolated-test backlog. The former instruction to stop for new code scope approval is superseded. No cloud spending, sync activation or live reinstallation is needed to finish offline integration.

### 8.5 Additional acceptance tests for discovery

- No desired profile provided: still produce evidence-backed candidate proposals and questions, not an error requiring the user's final intent.
- Proposed values do not become accepted automatically; user rejection/edits survive rescans.
- Candidate comparison distinguishes accepted differences from unknown/unsupported data; no repair commands emitted for automatic execution.
- Dirty checkout is not represented as reproducible solely by its HEAD; no private patch contents collected.
- Failed, timed-out and inaccessible probes remain explicit; candidate export refuses unresolved required fields.
- Safety tests include credential-bearing URL fixtures, hostile paths, config includes, symlink escape, worktrees, external helpers, offline partial-clone behavior and output overwrite attempts. No real credentials used.
- Before/after fixture state and confinement checks support the read-only claim; metadata-only success is not a runtime test.

## 8A. Installer implementation slices — authorized; partially delivered

The original N1–N7 acceptance sequence is retained in full. All code/isolated tasks are authorized; no new blanket scope approval is needed. Use failing tests, scoped checks and independent review. Detailed statuses distinguish the prior milestone from current work; the working machine is never an implicit installation target.

### N1 — Approve semantics and capture regressions

- [x] Establish the bounded D1–D9 local naming contract recorded in section 7; unresolved migration/Unicode/UX choices remain visible, not silently resolved.
- [x] Add `src/tests/installer_workspace_contract.test.py` using temporary directories and controlled environment/commands (prior receipt).
- [x] Capture incident-style explicit names versus remote owner, CLI precedence, legacy compatibility and no-mkdir/chown resolution in workspace/profile tests.
- [x] Record bounded offline regression/failure fixes without running install/repair/status on a real workstation; broader application coverage remains N4–N6/S2–S4.

### N2 — Parse and validate configuration

- [x] Extend profile_parser.py/config.sh for workspace fields/precedence/clearing/conflicts; bounded pinned YAML, reviewed shared schema and migration preview now also have separate checkpoint fixtures. Consumer/apply limitations remain explicit.
- [x] Extend `src/tests/installer_profile_contract.test.py` for workspace keys, invalid combinations and sequential loads (prior receipt).
- [x] Validate workspace semantics and reject baselines/new kinds at legacy boundary; bounded shared YAML ingestion/export is implemented and checkpoint-tested. Export collision review and writer C01 remain, not a missing schema claim.

### N3 — Wire CLI precedence

- [x] Inspect argument/profile loading in `isaac-installer/bin/isaac-installer` for the bounded workspace slice.
- [x] Implement name/root/layout/owner overrides without profile clobbering; explicit clearing and inherited-value rejection are tested.
- [x] Test real workspace and desired-YAML/adapter/action CLI transport in checkpoint suites. Later consumer fixes need final integration/review; these fixtures do not qualify all legacy commands.

### N4 — Implement pure resolution and preview

- [x] Route all destination layouts/overrides through shared workspace_paths.resolve_paths and the real shell helper; named active selection agrees. Planner/migration use the same pure API; legacy state/active/launcher gaps C05 remain.
- [ ] Complete the separate native action boundary. managed_apply/fixture_builders implement new files/local pinned Git/stdlib venv fixtures with parent 33-test receipt, not safe native installer application. Independent C02 defects and native action backlog C04 remain.
- [ ] Complete preview/execution stale-precondition qualification across supported operations. Managed fixture tests now cover identity/locks/failure/rerun boundaries; independent C02 review has remaining findings/unexecuted probes. Native consumer agreement C04 is not proved by fixture actions.
- [x] Use real early dry-run entries: legacy --config/--profile is still incomplete stage selection; --desired-profile reaches concrete planner/evidence. Do not imply concrete planning was absent or that the legacy/native gap C04 is solved.

### N5 — Unify consumers and document compatibility

**Current N5 evidence:** shared pure destination resolution is wired into actual shell/planner/migration; docs/workspace-consumer-matrix.md traces real modules/state/audit/demos, and migration-profile has checkpoint fixtures. Named legacy dispatch still refuses. State/drift/repair/legacy active and generated-launcher mismatches are genuine C05 code backlog, not live-only qualification.

- [x] Trace helper consumers in modules/state/audit/demos/CLI and document actual selection differences in docs/workspace-consumer-matrix.md. This records source tracing, not all-consumer agreement or qualification.
- [ ] Ensure install/status/audit/repair/state/generated launchers use the same reviewed resolved selection. C05 lists exact remaining consumers; do not enable automatic drift relocation or remove named refusal on the strength of resolver tests.
- [ ] Remove personal-name fallbacks only where this slice requires them, replacing them with shared resolution or explicit unknown errors.
- [ ] Complete independent compatibility review of four generic presets/README and consumer matrix. Changes/migration examples now exist; verify all consumers without assuming every public preset needed personal values. Original profiles preserved.
- [ ] Review all touched consumers independently and preserve unrelated installation functionality.

### N6 — Repository adoption and update policy — retained, code/design authorized

**N6 partial, not just live approval:** inspect_adoption is inspection-only. New-resource file/local-Git/venv actions and per-file backup/alternate restore exist, with 33 managed checkpoint tests, but independent C02 review is not PASS. Full existing-checkout/fork/ref/submodule/LFS and operation-specific recovery C06 remains authorized code backlog. 8E allows bounded unsupported adoption, not whole-plan deletion.

- [ ] Distinguish installer-managed checkout from user-owned development checkout.
- [ ] Specify identity checks using repository metadata, not folder name alone; cover multiple clones and Git worktrees where `.git` is a file.
- [ ] Define dirty/untracked files, local commits, detached HEAD, remote mismatch and requested-ref changes.
- [ ] Specify explicit adoption/update choices; default to no destructive mutation.
- [ ] Review fork fallback and creation scope, tag provenance, upstream push protection, submodules/LFS and failure propagation.
- [ ] Add supported-policy tasks/tests with design and independent safety review under the existing code authorization; do not treat this unfinished design as abandonment or silently enable real Git mutation.

### N7 — Reuse in IsaacAutomator

**Current N7 evidence:** shared reviewed schema, actual local config and --software-profile Click-to-Deployer-to-Ansible inventory transport now exist. New local pins/archive and isolated Ansible GR00T/LeRobot/Arena SHA consumers have worker receipts pending review. Packer C07, serving C08, runtime C09 and full source proof C10 remain real gaps, not blanket runtime-only gates.

- [ ] Reconcile with `src/python/workstation_profile.py`, `workstation_profile_command.py` and the existing Tasks 24–27 roadmap.
- [ ] Finish real profile-to-deployment/Ansible/Packer coverage. Local/Ansible transport exists; Packer image/profile source transport is absent C07 and remains refused, not completed.
- [x] Share actual local/Ansible fixtures with explicit target-home translation and nonempty source/runtime intent. Pure mapping does not inspect existing target collisions or qualify cloud checkouts as disposable; later worker integration still pending.
- [ ] Verify lifecycle/backend/distribution behavior remains independent.
- [x] Separate local/Ansible rendering/configuration evidence from references, apply and runtime acceptance. Neither actual local nor cloud runtime was exercised; no parity claim from passing mapping tests.

## 8B. Narrow cloud starting point: Ansible fork overrides and CLI validation

**User direction:** Start from existing Ansible repository variables for one explicit cloud configuration. A more robust reusable flow can be considered later. Do not make shared-profile redesign, observer implementation or local-installer changes prerequisites for this bounded work.

> **Historical critical mismatch, resolved narrowly in the prior milestone:** CLI validation used official repositories before Ansible fork selection. The new explicit repository flags route validation and inventory to the same source/ref pair. This fix does not establish full SHA reachability, Packer transport, local-edit synchronization or runtime acceptance.

### Pre-fix source findings (historical; retained to explain the requirement)

- `src/python/config.py:89–91` selects official Sim/Lab/Arena repository URLs.
- `DeployCommand.git_ref_callback()` in `src/python/deploy_command.py:243` chooses its validation repository from those configuration values; `latest` discovery uses the selected validation repository too.
- `src/ansible/inventory.template:11–15` transports component revision values but does not transport custom Sim/Lab/Arena repository URLs.
- The `isaacsim-source`, `isaaclab-source` and `isaaclab-arena-source` roles each have repository/checkpoint variables in their `defaults/main.yml`. Ansible-level overrides are possible, but their presence does not establish an end-to-end fork-selection flow in `deploy-gcp`.
- Native GR00T has separate `gr00t_git_repo` and `gr00t_git_checkpoint` variables and defaults to disabled. Its enablement and native/container selection require explicit review; do not assume the Sim/Lab/Arena callback controls it.

**Consequence:** An Ansible override alone may be too late to affect CLI preflight. A shared branch/tag name could also validate successfully upstream while naming different content in the fork. Successful validation must refer to the same repository/ref pair that will be installed, not merely a matching ref string somewhere else.

### Bounded implementation checklist — prior offline fix delivered; live run not authorized

- [ ] Record the intended repository URL and revision for each enabled component; distinguish remotely available commits from uncommitted local work. Review Arena submodule pins without changing them.
- [x] Trace source-selection precedence and implement actual explicit `--isaacsim-repo`, `--isaaclab-repo`, `--isaaclab-arena-repo` flags rather than assuming an extra-vars file is forwarded. Defaults and local installation remain unchanged; no general override-file interface is claimed.
- [x] Cover fork-only/shared-name-different-content/missing/latest routing in `src/tests/deploy_fork_transport.test.py` and retain `deploy_command.test.py` regressions (prior receipt).
- [x] Make repository selection available before ref validation and transport the same effective pair to Ansible inventory; test flag order and repeated selection without a new general profile system.
- [x] Preserve validation and prohibit upstream fallback for a missing selected-fork ref. Existing unverified full-SHA behavior is an explicit limitation, not a new reachability guarantee.
- [x] Test actual Click-to-`Deployer.create_ansible_inventory(write=False)` transport, default upstreams and disabled components with mocked network lookups only; no live GitHub/cloud execution.
- [x] Record the prior independent narrow transport review PASS. Exact installed commits/runtime remain separate acceptance; mutable branch names are not immutable reproduction.

The callback/inventory fix is now implemented and prior fixture-verified; this reconciliation creates no deployment or override file. A real GCP run requires separate explicit authorization and review of IAM, capacity, spending, cleanup and the chosen software configuration. Selecting forks does not synchronize local edits or prove a working Sim/Lab/Arena/GR00T stack.

## 8C. Required installer dry-run: preview actions without applying them

**User requirement:** isaac-installer needs reliable no-change dry-run. Full code/isolated verification remains authorized. Concrete desired-profile planner, target-observation bridge and bounded fixture executor now exist; legacy --config/--profile stage-only preview and native action/target agreement remain incomplete C04. No working-machine test authorized.

### Historical unsafe flag versus current incomplete safe preview

The legacy `--dry-run` accepted by `isaac-installer/bin/isaac-installer` had incomplete enforcement, as documented below. The prior milestone now intercepts it before legacy sources/checks with `safe_preview.py`; these old paths explain the regression requirements, not the present offline call graph:

- `evaluate_and_run_stage():130–171` invokes `check_func` before the dry-run branch. Some existing checks mutate state; for example, `check_isaac_sim()` in `lib/modules/isaacsim.sh` can write an EULA marker and deploy runtime bridges.
- `cmd_install():381–390` calls logging initialization, system probing and state initialization without a dry-run guard. Confirmed source writes: `lib/core/logging.sh:45–60` creates a log directory/file, replaces a latest-log symlink and attempts recursive ownership changes; `lib/core/state.sh:18–37` creates the state directory and, when absent, a state file with ownership changes. Full startup/probe call paths still need audit; this is not merely a hypothetical risk from misleading function names.
- `cmd_install():422–425` calls `install_streaming_provider` when selected without checking `DRY_RUN`.
- The final message at `cmd_install():435` says no modifications were made, but the above control flow does not justify that guarantee. This is source-backed risk identification, not a live dry-run test.

Do not recommend an unqualified live run on the working setup. Early entries enforce confinement in fixtures. The legacy config/profile route still returns incomplete stage selection; the desired-profile route now produces concrete actions with unknown/blocked/unsupported values. Both differ from native execution qualification; unprivileged status alone is insufficient protection.

### Required semantics

- Dry-run previews actions for a supplied candidate/desired profile. The observer workflow discovers that profile from evidence and user decisions. These are complementary functions, not substitutes for one another.
- Share pure configuration resolution, admitted read-only observations and action planning with execution so preview does not become a second divergent implementation. Mutations must sit behind an explicit execution boundary; do not merely add scattered `if DRY_RUN` checks while leaving initialization/checks unsafe.
- Default dry-run writes nothing on purpose: no logs, state ledgers, resume hooks, EULA markers, directories, links, ownership changes, Git index/config/ref changes, services, packages, downloads or repairs. An optional report export is a separate explicit write to a new approved destination, never an implicit log side effect. Ordinary read access-time caveats from section 8.3 still apply.
- No sudo, network/auth discovery, arbitrary custom-build commands, imports from observed environments or runtime launches during the initial offline dry-run. Missing information is reported as unknown/blocked, not fetched or guessed. Future network preflight, if needed, must be a separate explicitly scoped operation.
- Cover every path reachable from the selected command, including startup, profile loading, detection, excluded stages, optional streaming, failure handlers and cleanup. Commands/modes that do not support dry-run must reject it before mutation rather than silently ignore it.
- Show proposed action, target, reason, evidence and potential overwrite/destructive effects; distinguish excluded, already satisfied, would change, unknown and blocked. Never describe a proposed install or uncertain check as successful installation.
- Unsupported/unsafe probes must report incomplete preview and a documented failure status; define exit-code meanings before implementation. Do not print an unconditional “no changes” guarantee without supporting enforcement and verification.
- Dry-run is not a transaction or rollback mechanism. A successful preview does not authorize execution or guarantee that later apply will succeed; execution must recheck relevant preconditions.

### Validation gate — concrete desired-profile path implemented; full native/legacy coverage partial

- [ ] Finish independent cross-entry/call-graph audit. Shared planner, real plan/render/migration/observe-targets and desired-profile dry-run/status/audit entries exist; C01 exclusions and C04 legacy/native coverage remain. No live machine used to discover side effects.
- [ ] Extend prior startup/custom-command/unsupported-subcommand refusal tests to concrete planning, all applicable streaming/optional paths and failure/cleanup paths; regression-first tests remain mandatory.
- [ ] Complete all relevant selected/excluded component combinations with filesystem/Git-state snapshots and attempted-operation detection; prior stage-selection comparison and sandbox negative controls are only partial coverage.
- [x] Prior offline CLI uses enforced Landlock/seccomp in disposable fixtures, with denied network/helpers/writes and no writable real-home target, cloud credentials or host Docker socket. Repeat qualification for new worker seams.
- [ ] Complete operation-specific preview/execution comparisons. Parent managed fixtures exercise same planner on new file/local-Git/venv resources, but C02 review and native C04 postcondition/idempotence/recovery requirements remain. Not GPU/runtime acceptance.
- [ ] Independently close concrete preview/writer/managed review findings: current readonly/writer/actions reports are not PASS. Export collision fix is reported, C01/C02 still open. Prior narrow PASS never transfers automatically; real use separately approved.

The full action-preview requirement remains partial, not paused. Concrete desired-profile planning and metadata/evidence bridge are implemented/checkpoint-tested; the legacy stage-only exit-2 route and unqualified native targets/actions C04 remain. A refusal-only operation does not satisfy its implementation requirement; real-host operations remain separately gated.

## 8D. Workstation protection mechanisms to implement and verify

**Required safety outcome:** protect the existing working installation, uncommitted progress, repositories, environments, configuration and data. No software can promise zero risk or automatic recovery from every system change. The enforceable default for this current machine is observation/preview only, once separately qualified and authorized; installation, repair, migration and removal stay unavailable under that authorization.

### S1 — Separate observation, preview and execution before initialization

**Current S1 evidence:** Pinned bounded readers, ordinary supplementary-group usability, denied writes/network/helpers/FD reuse, resource limits and pipe/TTY-safe separate writer now have checkpoint fixtures. All scope is synthetic. Readonly review closed earlier reader defects but failed runtime-collision completeness; a fix is reported, not independently cleared. Writer rereview found two independently reproduced high C01 exclusions bugs. S1 remains review-blocked; no actual target admission.

- [ ] Finish independent integrated startup/parsing/modules/traps/cleanup/resume/optional-stage audit. Actual early observation/export/plan/render/migration/target-evidence commands bypass legacy sources/logging/state; C01 and C04 remaining seams preclude blanket completion.
- [x] Implement bounded descriptor-pinned YAML ingestion and pure preloaded-preset resolution across admitted profile workflows; parent read-boundary/schema/workflow suites cover it. This reader checkbox does not clear separate writer C01, exporter collision or native execution review.
- [ ] Refuse observation/dry-run as root and prevent privilege escalation in their execution environment. Confinement must deny network, writable inspected mounts, host control sockets/devices and access outside approved metadata roots, except explicitly allowlisted read-only runtime/interpreter files and minimal sandbox pseudo-devices. Subprocesses inherit those restrictions; needed tool files do not authorize arbitrary host reads. A missing enforcement mechanism is a blocker, not permission to fall back to an ordinary shell. **Current evidence:** parent sandbox ordinary-account/privilege/FD/syscall fixtures exist; this whole S1 boundary remains open for integrated review/C01, not a missing root-denial implementation.
- [ ] Qualify the implemented separate report/profile writer: restricted new destination, exclusive no-follow/private output, stdio-safe producer/supervisor and original-root exclusions have checkpoint tests. Independent C01 continuation/canonical target-home defects remain; never claim complete confinement before rereview. Preserve no writable actual home/credentials/inspected targets.
- [ ] Set traversal depth/file-count/output/time limits and cancellation behavior; do not exhaust workstation memory/disk or recursively scan model/data trees. Record truncated coverage as incomplete. Exact budgets and confinement implementation must be reviewed before P3. **Current evidence:** shared reader budgets/cancellation/truncation and confinement fixtures exist; target-specific limits and final integrated review are still required.

### S2 — Protect targets and ownership at every mutation boundary

**Current S2 status:** managed_apply.Root now implements descriptor-relative identity/ancestry checks, locks, exact plan validation, new-only publication and stale/foreign refusal on disposable resources. Checkpoint managed suite has 33 tests. C02 managed rereview remains failed; original all-consumer/adoption/native protections C04–C06 remain partial. Output exclusivity also depends on C01 closure.

- [ ] Future execution must identify the selected host, target user/home, profile revision and exact resource/action set. Never infer the physical workstation from the current devcontainer or treat a cloud checkout as automatically disposable. **Implemented slice:** managed plans bind target_home/profile digest/actions and revalidate fixture identity; actual host/native consumer qualification remains C04.
- [ ] Default all pre-existing resources to user-owned/unmanaged unless explicit adoption has been reviewed. An installer marker, matching directory name or clean Git status is not sufficient permission to modify them. Adoption records the permitted actions; it is not blanket ownership of a parent directory. **Implemented slice:** new-only managed executor and inspection-only adoption refuse unmanaged resources; full adoption policy remains C06.
- [ ] Naming, discovery and adoption never automatically reset/clean/stash, rewrite remotes, change branches/submodule pins, delete untracked files, rename/merge workspaces, or recursively chmod/chown existing trees. A later managed-repository update requires a separately approved exact action, ownership and recovery policy; it cannot inherit permission from selecting a workspace. Dirty, ignored, untracked and nested-repository content must remain protected. Case-preserving resolution and explicit case-only collision handling still apply.
- [ ] Enforce validated destination containment at use time, not just at preview: reject empty/root/home-wide destinations, traversal, unsupported symlink/mount/hardlink cases and changed target identity. Use safe exclusive creation/no-follow or equivalent primitives; a string-prefix check or one earlier `realpath` is insufficient against races. If a safe primitive is unavailable for an operation, keep that operation unsupported. **Implemented slice:** Root no-follow descriptor ancestry/identity and stale/lock tests exist; independent C02 and operation-specific C04–C06 review remain.
- [ ] New profile/report writes refuse overwrite by default. Future authorized managed-file replacement uses same-directory staging and atomic replacement where supported, with expected-content checks; refuse concurrent edits and never overwrite a changed user file during rollback. **Implemented slice:** exclusive writer and new-file atomic publication exist; C01 output exclusions and any future in-place CAS/replacement/rollback qualification remain open.
- [ ] Scope a local execution lock to the actual affected resources, including overlapping profiles. Lock conflict stops execution. Because locks do not stop editors or external package managers, recheck relevant preconditions immediately before each change and abort/review stale plans. **Implemented slice:** managed root/resource lock tests exist. Official sync controllers can choose conflicting lock scopes (C03); broad native/overlapping consumer qualification remains.

### S3 — Keep high-risk operations out of discovery and ordinary approval

**Current S3 status:** confined offline entries and the bounded managed executor exclude high-risk/native operations; no actual maintenance/settings consent exists. Native legacy consumers remain unqualified C04–C06. Safe refusal is a boundary, not implementation of an originally required operation; no checkbox below grants maintenance approval.

- [ ] GPU drivers, kernel/DKMS modules, bootloader/initramfs, display manager, system Python, global package removal/upgrades, storage/mounts, network/firewall/SSH and service enablement require a separate high-risk maintenance scope. Profile approval, `--yes`, resume and a successful dry-run must not implicitly authorize them on this machine.
- [ ] Treat modifications to existing Conda/UV environments, Sim/Lab/Arena/GR00T installations and shared libraries as preservation-sensitive. Prefer explicitly selected new versioned environments/directories for evaluation; do not upgrade the working environment in place as a test. Do not switch active links until separately approved and verified.
- [ ] No automatic reboot, driver replacement, resume-on-login/reboot hook, or startup service from observation/preview. Future apply may recommend a manual maintenance step, but must stop if its required protection is unavailable. Installation hooks/custom build scripts are executing code, not harmless configuration; review and isolate them before any apply.
- [ ] Existing VS Code/devcontainer settings, AGENTS.md, credentials, models, datasets and live databases remain outside mutation scope. No inferred consent from a profile, scan or report. Specific later permission is required for any applicable change.

### S4 — Recovery and interrupted operations, without false rollback promises

**Current S4 status:** apply-only journal/failed-run gate, digest-bound review_recovery, managed-file backup/alternate restore and new-resource Git/venv postconditions now exist with 33-test parent checkpoint evidence. Independent rereview C02 is failed: initial venv expected-byte and strict manifest-schema issues remain, and several fresh independent probes were not executed. This is not blanket repository/environment/package recovery or crash durability; C04/C06 remain real backlog.

- [ ] Before any separately authorized mutation of existing resources, review a recovery manifest: affected paths/resources, local and untracked work, nested repositories/submodules, environment definitions versus non-reconstructible contents, configuration, data, ownership/permissions and external dependencies. A Git commit or package list alone is not sufficient recovery. **Implemented slice:** managed-file-only backup manifest exists, not full existing-workspace/environment recovery. Strict manifest validation C02 and broader C06 recovery remain code gaps.
- [ ] Choose protected backup/snapshot storage outside the affected tree and synchronization scope; check capacity and appropriate consistency. Databases need application-consistent backup. Credential backup is a separate user-controlled security decision, not observer collection.
- [ ] Restore representative affected content into an alternate disposable destination and verify bytes/metadata and relevant usability before relying on recovery. Any system-level maintenance additionally needs a tested rescue/console path and recovery procedure appropriate to that host. No restoration experiment on the working installation. **Implemented slice:** managed mode0600 file alternate-restore API/tests exist; C02 validation/rereview and other operation-specific recovery are incomplete. Actual rescue/host choice remains separate.
- [ ] Record intended/started/verified/failed operations and created-resource identities in an apply-only journal. Atomically mark success only after postconditions; never mark failed/partial work healthy. SIGTERM, timeout, crash or reboot must not auto-resume mutations on next launch. Revalidate before a separately authorized resume. **Implemented slice:** apply journal and explicit digest-bound review_recovery/failed-run gates exist, with managed checkpoint tests; C02 and independent interruption/race reviews prevent blanket qualification.
- [ ] On failure stop dependent actions, retain sanitized diagnostics and report partial changes. Cleanup can remove only verified unchanged resources created by that run within approved bounds; never recursively delete a pre-existing path or “restore” over subsequent user edits. Prefer manual recovery when identity or ownership is uncertain. **Implemented slice:** managed failures/journal/created-resource checks and local fixture postconditions tested; cleanup/foreign-edit handling needs full C02/native C04–C06 review.
- [ ] Package changes, drivers and arbitrary scripts are not universally reversible. If rollback/recovery is unproven, refuse that local operation rather than advertise a transaction. Backups reduce risk but neither authorize changes nor guarantee recovery.

### S5 — Sync and remote-development safeguards

Preserve the existing [remote-development plan](../isaacautomator/remote-dev-plan.md): selected source -> one-shot/continuous synchronization -> cloud workspace -> GPU devcontainer. Policy/topology/runtime-placement and candidate rendering, actual disposable rsync, and real pinned SyncthingREST/Supervisor now exist. Supervisor worker receipt records 45 tests in three suites; parent remote/supervisor subset has 46 in four overlapping suites, not native engine qualification. Independent supervisor review fails C03; SelectedTransfer cross-host one-shot is in progress and does not complete continuous cross-host C11. Mutagen/native versions outside the explicit adapter are not arbitrary new implementation requirements. No service/settings/container activated.

- [ ] Never synchronize live virtual environments, container writable layers, Git metadata, Terraform state, credential stores or live database volumes by default. Select source/configuration and artifact folders explicitly; user-approved exceptions need their own consistency and recovery review. **Implemented slice:** exclusion policy/real disposable rsync/candidate fixtures exist, with protected source/config read-only mounts and separate build/artifact outputs; native ignore equivalence not executed.
- [ ] Define direction, ownership, exclusions, conflict/deletion policy and initial seed before enabling synchronization. Do not let rsync and a continuous engine independently write the same destination concurrently. Versioning/backup and deletion propagation must be deliberately configured and tested; conflict files are not a backup. **Implemented slice:** real protocol supervisor and seed policy exist, but C03 official-writer overlap/root-identity defects and cross-host C11 remain. Caller attestations are not backup/ownership proof.
- [ ] Protect profiles, recovery copies and active local configuration from automatic remote overwrites. Transferring a devcontainer definition does not authorize its hooks, rebuild, dependency installation or VS Code setting changes. Sync is separate from desired-profile approval and installer execution. **Implemented slice:** candidate rendering preserves existing settings and mounts source/config read-only; runtime-placement manifest is not installation/parity. C03/C11 and native protocol/restore qualification remain.

### Implementation seams and proof required

Audit existing `isaac-installer/bin/isaac-installer`, `isaac-installer/lib/core/profile_parser.py`, `isaac-installer/lib/core/{config,git_workspace,state,logging,audit}.sh`, and each selected `isaac-installer/lib/modules/` consumer before placing the boundaries. `state.sh` and `logging.sh` include ownership-changing paths; state/cleanup logic cannot be assumed passive. Reuse existing helpers only after making their contracts safe. Do not create a general authorization framework; keep local guards and an operation record bounded to this installer.

- [ ] Add failing tests before fixes, then enforce read-only observation/preview in disposable isolation. Mutation tests use synthetic writable targets only; driver/boot/service behavior requires a disposable VM, not a container presumed to isolate host effects. No paid cloud test is required for this planning/discovery phase. **Current evidence:** module RED/GREEN receipts and parent checkpoint suites exist. Final integrated proof and independent C01–C03/collision closure still pending; no new final test count here.
- [ ] Include denied writes/network/helpers, malicious profile/path data, case collisions, symlink/hardlink/race escapes, output collisions, changed targets, overlapping runs, disk-full/permission errors, interrupted writes, SIGTERM/crash, failed postconditions, stale resume and cleanup of foreign resources. Use fake secrets only.
- [ ] Compare before/after fixture contents, permissions, links, Git refs/index/config and attempted operations. Add a negative-control writer to prove confinement actually rejects writes. Tests of safety guards must not rely solely on mocks.
- [ ] Demonstrate unchanged rerun, a single intended change, preserved dirty/untracked/ignored/nested work and failure recovery on disposable fixtures. Qualify each supported action separately; no blanket safety/idempotence claim. **Current evidence:** managed/disposable-rsync fixtures now demonstrate bounded unchanged/single-change paths, but do not cover entire installer/environment/repository update pipeline (C02/C04/C06/C09).
- [ ] Independent review must inspect enforcement and test evidence, not just this checklist. P3 requires S1 read-only safeguards plus applicable target/path limits; existing-resource apply additionally requires S2–S4 and its own authorization. S5 is mandatory before sync activation. No gate auto-triggers the next stage.

## 8E. Acceptance and review register — incremental, not all-or-nothing

Track each capability or custom item with its question, proposed behavior, owner of the decision, affected scope, and separate **decision / implementation / verification** statuses. Use accepted/rejected/unresolved decisions, absent/implemented code, and not-tested/failed/passed-with-scope verification, with test/report references. Do not label draft-plan review as execution acceptance.

| Area | Minimum acceptance for a supported slice | What may remain open |
|---|---|---|
| Inventory coverage | Name admitted probes, roots, environment and limitations; prove the admitted process cannot modify inspected resources within the documented confinement boundary. State filesystem-level read effects and approved output exceptions; expose unknown/inaccessible/truncated results. | Additional custom tools go into 8.1A; a partial inventory remains useful. |
| Profile generation | Trace each proposal to evidence/input; accept/edit/reject/defer; preserve decisions across rescans; validate actual schema and reject unsupported executable fields. | Incomplete drafts are allowed; required unresolved fields block executable export for that scope. |
| Safe application | Explicit target/action and managed versus user-owned policy, enforced preconditions and S2–S4 protections; unsafe ownership or missing operation-appropriate recovery blocks mutation. New-resource-only actions require bounded cleanup and protection of existing resources, not backup of unrelated trees. | Adoption/migration can remain unsupported. |
| Idempotence | Same supported profile rerun has no unnecessary changes; changed settings affect only intended targets; failures cannot record success or destroy user work. Test markers against actual desired state. | Untested actions remain unqualified; fresh-install success is not rerun proof. |
| Ansible mapping | Each supported field has real local/Ansible consumers and matching intended source/version/environment/path semantics; shared fixtures exercise actual transport, including 8B fork validation. | Local-only/unsupported fields are explicit; no silent loss. Offline mapping is not runtime parity. |

Review questions are resolved where they affect a slice: naming Unicode/collision rules before that resolver ships; probe admission before collection; user intent before profile inclusion; ownership and recovery before apply; mapping before claiming cloud support. Unknown optional customizations must not block unrelated qualified work. An unsupported required item blocks only the claimed/apply scope that depends on it, not partial discovery or review.

**Review completion:** concrete decisions, implementation and scoped evidence are recorded above and in C01–C11/W01/V01/U01/L01. Current code/isolated authorization is explicit. Readers/ordinary-account/resource limits/shared schema/transport/planner/sync protocol are no longer merely absent, but current independent readonly/writer/actions/supervisor reviews are not PASS. Later fixes require fresh independent review and parent integration. User values/targets/recovery storage/native operations remain separate. Whole-plan source audit and frozen final test receipt are outstanding.

## 9. Naming validation matrix — prior subset covered; full acceptance retained

Required cases for the new offline suite:

- Explicit `BoredEngineer` with remote owner `boredengineering`; no alternate folder creation.
- Arbitrary custom name with multiple remote owners; all intended destinations share the chosen grouping folder.
- Exact existing folder; case-only conflict; distinct similar name; multiple candidates.
- Case-preserving policy: test exact `BoredEngineer` reuse, `boredengineer` conflict requiring explicit selection, retention of existing spelling after approved reuse, and distinct `boredengineering` with no inferred alias. Test unattended refusal and filesystem-independent collision policy; no automatic rename, lowercase or repository mutation.
- Missing name in named mode; flat mode with/without name; legacy mappings/conflicts.
- Spaces, unsafe separators, control characters, whitespace, symlink/dangling symlink, regular-file collision and permission denial.
- Per-repo explicit paths, differing discovered checkouts and `.git` file worktrees.
- CLI/profile/default precedence, controlled environment behavior and sequential profile loads.
- Preview creates no paths, changes no ownership, invokes no Git/network/auth, and never writes the profile.
- Execution rechecks stale preview preconditions and preserves existing files and Git state.
- Install/status/audit agree on destinations without invoking real install/repair in tests.

Existing regression targets (authorized; the prior receipt records older runs, not current worker/integration results):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 -B src/tests/installer_profile_contract.test.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 -B src/tests/workstation_profile.test.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 -B src/tests/workstation_profile_command.test.py
```

Run from the repository root using a verified interpreter with existing required dependencies, including PyYAML. The workspace/discovery/preview/named/sandbox/fork suites now exist and follow the direct unittest style; new worker suites and vertical integration must also run. Shell syntax checks supplement, not replace, behavioral acceptance. Keep subprocess environments isolated from credentials and real home directories; use enforced boundaries as well as action stubs where appropriate.

## 10. Related records

- [Original installer architecture and workspace discussion](../docs/isaac-install-plan.md)
- [Host compatibility plan](../plans/isaac-installer-host-compat.md)
- [Installer/Ansible compatibility plan](../plans/isaac-installer-ansible-compat.md)
- [Shared workstation roadmap, especially Tasks 24–27](../plans/terraform-remote-backend-plan.md)
- [Historical workspace implementation checkpoint](../../memory/sessions/20260820_215440_f1a2b3c4.md)
- [Later source-backed local/cloud parity review](../../memory/sessions/20260910_061133_51928612.md)
- [Multi-repository remote development and synchronization plan](../isaacautomator/remote-dev-plan.md)

These records contain historical completion claims as well as later corrections. Use current source and fresh verification before claiming an old issue is fixed. This reconciliation changes only this plan within the repository; it neither rewrites related records nor changes the active software stack.

### Final-acceptance checklist — code, technical review, user intent and live gates

These IDs retain original approved requirements, not new scope or every arbitrary unsupported platform. Unassigned code means outside the active worker scopes supplied for this reconciliation; parent may assign it under existing authorization. Unsupported adoption may be a bounded 8E slice, not whole-plan completion. Exact expanded handoff: `/tmp/isaac-full-register-update.json`.

| ID | Type | Exact remaining acceptance / consumers |
|---|---|---|
| C01 | Code: S1/P2/P4 | **discovery_cli.py previous-report continuation; desired_profile.export_candidate; profile_output.py observe-targets exclusions**: Preserve immutable original-root union through empty/nonempty rescans and historical edit/reject/defer; canonicalize repeated/equals --target-home rather than taking first argv occurrence. Evidence: /tmp/isaac-full-writer-rereview.json WRITER-REREVIEW-01/02. Both independently reproduced; current review passed=false. Distinct from active export runtime-collision fix. |
| C02 | Code: S2/S4/N6 | **fixture_builders.build_environment; managed_apply.restore_backup/_validate_record**: Validate trusted expected venv bytes before initial tree fingerprint; exact bounded recovery manifest schema and coherent source/source_root/original_name before I/O; bound journal identity/errno integers. Evidence: /tmp/isaac-full-actions-rereview.json RLOGIC-1/2. Venv pre-baseline issue source-grounded, tampering reproduction not executed. Manifest malformed cases reproduced; original-tree consequence unexecuted. Preserve positive paths and complete independent ancestry/forged-plan/interruption review. |
| C03 | Code: S5 | **sync_supervisor.Supervisor acquire/resume/poll/_seed_bytes; remote_development._LocalFixture**: Canonical common coordination for identical/overlapping datasets across official callers regardless of selected lock directory, shared with seed writer; reject missing/replaced selected root identities on both directions. Evidence: /tmp/isaac-full-supervisor-review.json SUP-SEC-1/SUP-LOGIC-1/SUP-LOGIC-2. All three independently reproduced. Caller exclusive-writer attestation and chosen-directory flock do not satisfy dataset ownership. |
| C04 | Code: 8C/N4/S2-S4 | **safe_preview._preview/main; profile_workflow; action_plan.build_action_plan; managed_apply.apply_plan and native module consumers**: Legacy --config/--profile dry-run remains stage-only, unlike desired-profile planner. Complete selected/excluded/streaming concrete planning and actual native runtime prefixes. Qualified native artifact/Conda/UV/package/tool execution and planner-to-consumer equality with per-action postconditions/rerun/recovery remain absent; managed executor only qualifies bounded fixture actions. Evidence: Current source: action_plan unsupported native branches; safe_preview always incomplete exit2; profile_workflow refuses install without dry-run.. Retain this real code backlog; refusing existing operations is not implementing them. Do not expand to arbitrary platforms. |
| C05 | Code: N5/section9 | **state.sh sync_state_ledger/audit_workspace_drift/repair_workspace_drift; git_workspace.sh resolve_active_repo_dir legacy; audit.sh legacy fallbacks; demos.sh generated launchers**: Unify reviewed selection across install/status/audit/repair/state/launchers, eliminate independent first-found/personal fallbacks and preserve error propagation. Named dispatch refusal does not close consumer agreement. Evidence: isaac-installer/docs/workspace-consumer-matrix.md actual consumer table. Matrix/tracing and migration preview implemented, full consumer behavior not qualified. |
| C06 | Code: N6/S2-S4/original later requirements | **git_workspace.sh setup_git_repo/fork/ref helpers; Lab/Arena/GR00T switch/sync/fork; state.sh repair; Ansible source-role existing-tree/marker/force paths**: Managed versus user-owned adoption/update choices; dirty/untracked/ignored/local commits/worktrees/nested preservation; requested ref/tag provenance, origin/upstream/push protection, submodules/LFS and operation-specific recovery/failure policy. Evidence: inspect_adoption is inspection-only; managed new-resource fixtures do not implement these consumers. 8E permits bounded unsupported adoption, not deletion of whole-plan N6. Actual operation choices remain separately gated. |
| C07 | Code: P5/N7 | **profile_adapters.render_profile and DeployCommand image/Packer paths**: Shared profile/source/ref/path transport into existing Packer image consumer absent; render_profile only local/ansible and image paths refuse/hide software-profile overrides. Evidence: Current adapter/DeployCommand source and adapter result. Implement/test offline without paid image build; refusal not transport. |
| C08 | Code: P5/N7 shared selected serving | **public full profile; profile_adapters serving coverage; gr00t-policy-server.sh.j2 and isaac-gr00t.service.j2**: Selected shared serving bind/port/model ref/revision lacks equivalent local/native Ansible consumer. Legacy launcher is not shared serving parity. Evidence: Current profile_adapters.py required serving unsupported; Ansible runtime result. Implement selected semantics without service activation; do not invent arbitrary serving platforms. |
| C09 | Code: P5/N7/S4 installation environments and reruns | **conda.sh install_profile_lab_runtime; isaaclab.sh install_isaac_lab; detect.sh; profile_adapters runtime/declaration coverage**: Later Lab UV/native -i dependency installs can replace new pins; full-pipeline final conformance/rerun not enforced. Fresh pinned path requires existing Conda; qualified manager bootstrap/prerequisite flow absent. Nondefault declared Lab identities remain hardcoded; selected non-null Kit/GR00T/LeRobot pins and unmatched required environment/custom placements lack consumers. Evidence: /tmp/isaac-full-local-consumer-result.json remaining_code_gaps_not_live_gates; /tmp/isaac-full-ansible-runtime-result.json remaining_gaps. New default local pins/archive/PyPI and isolated role consumers are delivered active-worker scope, not repeated as missing. Residual fields matter only when actually selected; unknown optional custom tools remain useful partial reports. |
| C10 | Code: 8B/N6/N7 source proof | **DeployCommand profile SHA preflight; local Git helpers; Ansible isaaclab-source/isaaclab-arena-source/gr00t/lerobot target Git/submodules**: Anonymous repository advertisement does not establish selected full-SHA existence/fetchability/reachability. Actual target-side clone/ref/submodule credential isolation and matching pair/postconditions remain unqualified beyond controller fixes. Evidence: /tmp/isaac-full-preflight-fix-result.json support_limits; /tmp/isaac-full-ansible-runtime-result.json. Public downloader verifies bytes only, not extraction/build/runtime. Controller/archive worker fixes do not close target Git. |
| C11 | Code: S5 related approved cross-host workflow | **SelectedTransfer.seed; SyncthingREST; Supervisor**: One-shot SSH/IAP seed in active worker is not continuous engine adapter. Supervisor requires both data roots locally accessible, rejects endpoint and uses paired loopback REST. Selected cross-host source/artifact seed/reseed/supervision with common ownership remains unwired. Evidence: /tmp/isaac-full-selected-transfer-api.json; /tmp/isaac-full-supervisor-api.json. Do not demand arbitrary engines/versions or automatic pairing/provisioning. Native current supported protocol behavior remains separately unverified. |
| W01 | Active worker / parent integration | selected_transfer cross-host one-shot completion and review; local default pins/PyPI/exact archive URL+SHA consumer integration/review; isolated Ansible GR00T/LeRobot and Arena SHA integration/review; controller anonymous preflight and public downloader fixes review; export runtime-collision fix independent review; reconcile stale installer_desired_profile/profile_adapter_transport assertions after changed consumers, then rerun parent integration. Worker handoff is not final approval. |
| V01 | Technical review, not user intent | Independent C01-C03/collision closure, ordinary-user/adversarial boundaries, selected public consumer matrix, per-action rerun/recovery and separate whole-plan audit. Native Syncthing/ignore/versioning-restore and robotics runtime unverified, not fabricated; no final counts until parent pass. |
| U01 | User intent/real observation | Actual physical target/home/roots/exclusions/budgets, reviewed desired sources/versions/placement/requiredness, explicit real archive URL/SHA, new report destination/retention. No actual P3/P4 acceptance. |
| L01 | Live operation | Installation/adoption/update/recovery, native sync/endpoints/deletion/versioning, settings/hooks/rebuild/service, cloud/IAM/capacity/spending/cleanup separately approved. No commits/pushes, source modifications, real scans, installation or cloud/settings operations by this worker. |

- [ ] C01–C03 corrected and independently rereviewed; distinguish reproduced from source-only findings.
- [ ] C04–C11 completed or explicitly retained as genuine partial code backlog; no refusal-to-completion conversion.
- [ ] W01 integrated and V01 independently audited; parent freezes final verified counts afterward.
- [ ] U01 actual decisions recorded when supplied; L01 separate gates never auto-triggered.

## 11. Completion criteria — whole-plan implementation and separately gated acceptance

**Profile-discovery acceptance:** actual safely collected or user-supplied baseline, evidence-backed desired candidate, reviewed decisions/comparison and explicit schema/consumer limitations. Complete nonempty shared YAML, expanded admitted metadata/manual declarations, writer/consumer/planner wiring now exist with checkpoint evidence. C01 and collision rereview remain engineering blockers; actual P3/P4 has not occurred. Fixture validation is not physical-host observation or actual approved intent.

**Naming acceptance:** deterministic explicit names, safe conflicts, accounted legacy behavior, no-write preview, agreement across consumers and independently reviewed offline evidence. Shared resolver, actual shell/planner/migration preview and precedence are implemented/checkpoint-tested. C05 all-consumer agreement and C04/C06 safe native/adoption behavior remain incomplete; migration preview is not migration apply.

**Whole authorized implementation acceptance:** all original P/N/8B/8C/S requirements are accounted for, missing implementable behavior is completed or precisely exposed, the real reviewed-YAML-to-consumer-to-action path is verified, and security review and whole-plan source review are recorded separately. Per-action supported behavior, idempotence/recovery and sync policy/execution limits must be explicit. Six worker completions, a high test count or a narrow PASS alone do not fulfill the whole plan. Full existing-repository safety includes missing policy/code as well as separately gated live acceptance; local/cloud runtime parity remains unproven until actually exercised under authorization.

**Current scope and handoff:** all original code/isolated tasks are authorized; this worker updates requirements accounting only. Actual parent checkpoints were read, later APIs/source/reviews reconciled and C01–C11 gaps separated from W01 integration, V01 review and U01/L01 actual decisions/operations. Parent will independently audit the whole plan and freeze final test counts after its own integrated pass. No final approval, commit/push, source change, real scan/install/settings/sync/recovery/cloud operation by this worker.
