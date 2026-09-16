# Main workflow action plan

**Goal:** Safely discover the existing native workstation setup, use evidence and review to produce useful shared desired YAML, align local installer and Ansible consumers, preserve repositories, and qualify selected local–cloud synchronization.

**Architecture:** Keep observations, proposed intent, approved desired configuration, action previews, and actual execution separate. Reuse the implemented observer, profile schema, adapters and SSH/IAP transfer machinery; do not build another framework. Containers and image building are complementary, not prerequisites for this workflow.

**Technology:** Existing Python/Bash tooling, shared workstation-profile YAML, Ansible and rsync/SSH/IAP. Optional continuous synchronization follows verified one-shot transfer.

## Scope and authority

This is an execution-order addendum to `workspace-repository-management-plan.md`, not a replacement or declaration that its unfinished requirements are complete. Existing-resource adoption/update/recovery, supported image consumers, and optional development-environment consistency remain accounted for there. They must not silently disappear, but they must not block safe observation and intent review when unrelated.

The user subsequently authorized **step 1 execution**: current-source reconciliation, bounded selected tests, a nonempty synthetic workflow, and fixes to relevant failures. Actual workstation observation, installation/settings changes, synchronization activation and cloud spending remain separately gated. Explicitly denied managed-execution/recovery probes remain blocked, including equivalent indirect invocations. No commits, pushes, reset, cleanup of user work, or new large delegation fan-out.

## Current evidence

- Current branch: `devcontainer`; extensive modified/untracked work is present. Preserve it and inspect before editing.
- Observer, review/export, writer, planner, migration, local/Ansible consumers and transfer code exist; do not start over.
- Historical writer and runtime-collision reviews passed within their scopes. Later code changes require evidence reconciliation rather than transferring old passes to the whole tree.
- Whole-plan/current-tree verification is incomplete. Worker test receipts overlap.
- Selected-transfer rereview found REREVIEW-SEL-SEC-1: custom CLOUDSDK_CONFIG inside selected data can be transferred. Treat as open until fixed and independently verified.
- Managed recovery/venv code has pure tests but missing denied execution qualification. This blocks apply acceptance, not profile discovery.
- A test fixture previously wrote outside its root to `/.env`; cleanup is worker-reported. Test harness isolation is not assumed sufficient merely because test inputs use `/tmp`.
- No actual approved workstation baseline or desired profile exists yet. Official GR00T `dev` was unresolved at the prior source check; do not substitute another source automatically.

## 1. Stabilize the existing implementation and verify the core workflow

**Outcome:** One current evidence receipt for the discovery/review/export/preview path, with an explicit failure and limitation list.

1. Reconcile the primary register against current files and later reviews; preserve historical receipts separately.
2. Audit the selected test call paths and their write/process boundaries before executing them. Repair fixture helpers that can write outside allocated roots. Exclude managed apply/builders/recovery probes; never run the default broad runner while it includes denied suites.
3. Recheck reviewed-source hashes; independently review changed observer/writer/entry seams rather than assuming a historical scoped PASS still applies.
4. Run explicitly selected discovery, metadata, profile/schema, writer/history, workspace/migration, export-conflict and workflow suites after boundary inspection. Record exact commands, exits, skips and source fingerprints.
5. Exercise one real CLI synthetic path: selected evidence -> proposals -> accept/edit/reject/defer and explicit declarations -> nonempty YAML -> local/Ansible rendering -> concrete no-change preview.
6. Require preserved decisions across rescans, optional unknowns retained without blocking unrelated intent, required gaps visibly blocking affected support, and no implicit Sim/Lab enabling or installation authority.

**Relevant files:** `isaac-installer/lib/core/{profile_discovery,metadata_readers,desired_profile,discovery_cli,profile_workflow,profile_output,report_writer,preview_sandbox}.py`; `src/python/workstation_profile.py`; `src/tests/run_profile_workflow_tests.py` and dedicated workflow tests.

**Gate:** No real observation until current read-only entry/output coverage is understood. Fix actual defects with RED -> minimal change -> GREEN; no new unrelated features.

**Step-1 verification receipt:** [verification/step1/README.md](verification/step1/README.md).
The final selected run has 267 tests in 19 suites (265 passed, 2 root-only skips,
zero failures/errors). Ten real CLI calls demonstrate nonempty native Sim/Lab and
optional custom-tool intent through review/rescan/YAML/both renderers/concrete
dry-run. The legacy parser consumes the local artifact; 11 exact output agreements
were checked. Reviewed-tool location and resolver ancestor-read bugs were fixed
with RED/GREEN evidence. Final independent source/receipt review passed, and all
133 reviewed source/artifact hashes were rechecked by the parent. Step 1 is complete
within this synthetic/non-mutating scope. No actual
workstation data was collected; no whole-plan or native-apply completion implied.

## 2. Build algorithmic host discovery, starting with the basics

**User correction:** The devcontainer's restricted host access is intentional.
Do not ask the user to manually enumerate every installation path or open host
mounts/SSH to the agent. Develop and fixture-test a small host-side collector here;
the user can run it on the host and return its private report for configuration
review. Algorithmic discovery must supply candidate paths, not require them all
as inputs. Host execution remains separate from code-development permission.

**Outcome:** Find the existing BoredEngineer workspace and IsaacSim first, then
collect machine/system-package facts and selected environment metadata. Preserve
observed facts separately from proposed desired configuration.

### A. Reuse repository knowledge as hints, not live observations

`../plans/isaac-installer-host-compat.md:19-20,54,245` records Ubuntu 22.04,
RTX PRO 6000 Blackwell, prior driver/CUDA versions and
`/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena`. These are historical
hints to verify, never grounds to claim current host state. Project defaults also
suggest `~/IsaacSim`. Do not run or source legacy installer detection/doctor code.

### B. Small collector and bounded search algorithm

Implemented entry: `isaac-installer/tools/collect_host_metadata.py`, stdlib-only,
using the host system Python in isolated mode. Offline implementation and bounded
verification are complete; real host execution remains separately gated. Initial
audit findings were closed, with independent code/security closure and separate
original-step-2 requirements reviews PASS. Fresh parent verification: 49 host
tests plus 267 selected core tests (314 passed, 2 root-only skips, no failures or
errors), and the ten-command collector-to-YAML/both-renderers/dry-run fixture demo.
No actual workstation baseline or approved real desired profile is implied.

1. A plan mode describes seed locations, metadata fields, excluded data, budgets
   and output destination without scanning directories or invoking probes. Resolve
   the invoking user's home, not a hardcoded username or this container's `/root`.
   Label execution context; never describe container package data as host inventory.
2. Collection checks `~/Documents/GitHub/BoredEngineer` and `~/IsaacSim` first.
   At the selected GitHub parent, inspect bounded directory names to find casing
   alternatives, preserving exact spelling and reporting duplicates/ambiguity.
   Enumerate repository candidates inside the selected workspace with explicit
   depth/entry/time caps; identify them by Git/project metadata, not names alone.
3. Detect IsaacSim using selected version/application metadata, never launcher
   execution or recursive asset inspection. Record symlink targets without silently
   following them outside the approved seed set. Missing/ambiguous paths produce
   targeted proposals for additional search roots, not a whole-home/filesystem scan.
4. Read only selected HEAD/config/ref metadata for repositories. Strip credentials
   from remote information before output; do not emit raw config. Separate Git
   worktree/common-dir targets require containment checks/additional approval.
   Dirty/index state stays unknown; no Git subprocess, fetch, reset or status.
5. Capture OS/kernel/CPU/RAM and narrow driver/toolkit metadata in a separate
   machine section. Installed NVIDIA packages, loaded driver version, GPU model,
   CUDA toolkit and driver-supported CUDA level are distinct facts. An optional
   fixed-field `nvidia-smi` probe has its own explicit scope and timeout; failure
   means unavailable, not healthy. No robotics imports or runtime activation.
6. Ubuntu/Debian system-package inventory uses local dpkg/APT records: installed
   name/version/architecture/status, and automatic/manual classification where
   evidence permits. Default to parsing selected database fields, not running
   package management. A future fixed read-only `dpkg-query`/`apt-mark` mode must
   be separately admitted, clean-environment, no-shell, timeout/output bounded;
   never update/install/repair or emit repository/auth configuration. Unsupported
   managers and truncated databases are explicit coverage gaps.
7. System packages are not all installed software. After the first basic batch,
   propose selected Conda metadata, Python dist-info/editable metadata, and known
   UV/environment descriptors for review. Standalone IsaacSim, source repos,
   Python environments, Snap/Flatpak and containers are not covered by dpkg alone.
   Manual package classification is a relevance hint, not installation intent or
   proof that the user personally installed a package.
8. Write one new private report using an exclusive output destination; refuse
   overwrites and output within observed roots. Include schema version, collection
   context, per-fact source, coverage and unknowns. No logs, shell history, `.env`,
   credential files, arbitrary config dumps, package scripts, network, sudo or
   settings changes. Report writing and possible access-time effects are not zero
   physical effects. Do not claim the portable collector inherits the existing
   confined CLI's security qualification.

### C. Wire the report back into configuration discovery

Reuse the existing metadata validation/proposal/review/export code through a
validated import adapter; do not create a disconnected inventory application or
pretend new machine/package records already fit the strict existing schema.
Implemented adapter/test files: `isaac-installer/lib/core/host_inventory.py` and
`src/tests/installer_host_inventory.test.py`. Keep unsupported machine/system
package intent visible as evidence/backlog until actual consumer mappings exist.
The human reviews proposals, not hundreds of dependencies one by one; group OS
baseline, drivers/CUDA, build tools and optional application dependencies.

### D. Implementation and acceptance

- Add failing fixtures for exact/colliding workspace case, missing seeds, bounded
  search, symlink escape, malformed metadata, multiarch/removed packages, missing
  manual flags, stale/conflicting repository hints, output collisions and secrets.
- Implement the minimal collector, then validate a synthetic BoredEngineer +
  IsaacSim + dpkg inventory report through import/proposals/review/nonempty YAML.
- Run only audited fixture tests with fixture roots and fake query commands;
  never query this devcontainer's real package inventory as a host test. Extend
  integration coverage and independently review the new read/output boundary.
- After that verification, present the short host invocation and its scope for
  the user to run. Bring its report into the existing workflow without requiring
  agent access to the host. No automatic host execution in this planning turn.

**Acceptance:** Tested discovery of basic paths and useful machine/package facts,
integrated into baseline/candidate review with provenance. Actual collection needs
the host-run step; observed presence never grants installation/adoption permission.

### Requirement-to-evidence register

The independent original-step-2 requirements audit finds the promised
implementation behaviors present. The final ancestor-link contract defect was
fixed through RED/GREEN regressions and independently rereviewed PASS. This closes
the implementation/synthetic gate, not the actual host-run gate.

| Requirement | Implemented behavior | Fixture evidence | Real-operation gate |
|---|---|---|---|
| B1 scope/context | Standalone default plan; explicit home/system roots, limits and effects | Inaccessible fixture roots; no planned report created | User reviews/runs on host |
| B2/B3 basic discovery | BoredEngineer/case/legacy-alias ambiguity; Git identity and Sim VERSION; bounded traversal | Case collisions, fake Git markers, missing/malformed markers, cap tests | Actual paths unobserved |
| B3 linked/missing scopes | Bounded link text/redaction and explicit targeted scope requests; no target traversal | Link canaries, exact scope keys, visible backlog; Documents and shallow-system ancestor regressions | No follow-up scope automatically runs |
| B4/B8 repository/source evidence | Stable source maps for HEAD/config/ref, Sim, Conda/dist-info; pure lexical binding | Held source identities, reordering, cross-root/mismatched-source refusal | Not source-content attestation |
| B5 machine facts | Fixed source-bearing OS/kernel/CPU/RAM/driver/toolkit records; separate uncollected GPU/driver-CUDA level | Synthetic records and fixed OS-release fallback | No live compatibility claim/probe |
| B6 system packages | Installed multiarch inventory, explicit held/installed status, manual/automatic/unknown and unsupported-manager coverage | Synthetic dpkg/APT records, removed/conflicting/truncated cases | No package-manager execution |
| B7 later metadata | Selected Conda/venv observations plus named editable/UV descriptor scope proposals | Exact descriptor lists, request-only actions and source bindings | Full additional readers not inferred |
| B8 private output/bounds | Exclusive nofollow mode-0600 report; entry/byte/time/schema/serialization bounds; orphan pruning | Output collisions, redirects, links/hardlinks/FIFO, deadlines and import-envelope caps | Portable collector is not CLI confinement |
| C grouping and intent | Five heuristic package-member groups; unapproved proposals; unsupported evidence retained | Group identities/backlog, unknown tool sources, no system-package install proposals | Human review does not authorize installation |
| C/D actual pipeline | Collector → import → review → reimport → nonempty YAML → both renderers → concrete dry-run | Ten real synthetic CLI calls; unchanged source hashes/modes/directory entries | Actual host report/profile still absent |

Reproduction, raw logs, source fingerprints and review reports are retained in
[verification/step2/README.md](verification/step2/README.md). Optional query modes,
full editable/UV parsing, broader Git layouts and native system-package consumers
remain explicitly outside this minimal batch, not silently claimed implemented.

## 3. Discover and review desired intent iteratively

**Outcome:** A useful shared YAML profile and separate evidence/decision record.

1. Present each finding as keep/change/exclude/defer, with evidence, uncertainty, intended purpose and installation placement. Do not make the user design a complete profile first.
2. Confirm exact case-preserving workspace/repository paths and selected fork/ref; never invent aliases or create a differently cased owner directory.
3. Separate important custom dependencies/tools from experiments. Preserve unknown optional items as a backlog; ask targeted questions only for gaps affecting selected required behavior.
4. Use explicit declarations for intent not discoverable from metadata. Neither presence nor acceptance implies installed health or execution permission.
5. Rescan only newly approved evidence as needed; keep edits/rejections and historical excluded roots, and require re-review of changed evidence.
6. Export to an explicitly selected new private YAML path. Preserve the original baseline and reviewed decisions; no overwriting active profiles.

**Acceptance:** At least one nonempty real desired scope is loadable and its required unresolved decisions are explicit. Unresolved GR00T source intent stays unresolved without blocking unrelated components.

## 4. Align the same YAML with installer and Ansible

**Outcome:** One field-level comparison plus concrete no-change plans, not a claim based only on serialization.

1. Render the reviewed profile for both targets with explicit target homes.
2. Compare component enablement, exact repository/ref/revision, paths, archive URL/checksum, environment manager/name/Python, supported package pins and custom dependencies.
3. Trace every supported field to its actual local shell or Ansible consumer. Distinguish differences by target from silent field loss or default substitution.
4. Finish residual resolver/error-propagation and post-dependency pin checks using bounded fake-command/template seams; no package installation or playbook task execution against the workstation.
5. Present target/action/reason/effect/unknown/blocked results. Resolve relevant mismatches before calling the profile aligned.

**Relevant files:** `src/python/{profile_adapters,deploy_command,deployer,public_git,public_artifact}.py`, `isaac-installer/lib/core/{workspace_paths,action_plan,legacy_action_plan}.py`, native component modules and corresponding Ansible roles. Tests include consumer agreement, runtime consumers, pin conformance, adapter transport and source proof.

**Acceptance:** Exact supported intent reaches both consumers; required unsupported fields fail visibly. Syntax/mocked tests are not installed runtime compatibility. No native apply enabled by this step.

## 5. Preserve repositories throughout; qualify any later modification separately

**Outcome now:** Exact existing selections and a preservation/conflict report; no adoption or relocation.

- Use migration preview only to compare existing and desired destinations. Preserve exact casing and explicit overrides; refuse ambiguous selection.
- Never infer clean Git state, absence of local commits, or ownership from metadata/UID/path. Dirty/untracked/ignored files, worktrees, submodules and local changes remain protected; unsupported evidence stays unknown.
- No fetch/checkout/reset/clean/chown, automatic fork creation, repo replacement or environment-link switching during discovery/alignment.
- Before future apply, complete applicable adoption/update policy and independently qualified per-operation recovery, backups, concurrency, interruption and postconditions. Keep these as implementation requirements, not merely a request for user approval.
- The denied managed probes require explicit resolution of their gate; pure tests cannot replace them. Do not run an installer on the working setup to discover whether safeguards work.

## 6. Qualify one-shot local–cloud synchronization, then optional continuity

**Outcome:** Verified selected source/config push and separate results pull without credential or environment copying.

1. Fix REREVIEW-SEL-SEC-1 before any activation: resolve known IAP authentication-context paths before manifest generation; reject overlap or enforce reviewed protection across ancestor/equal/descendant cases. Never read credential bytes to detect secrets.
2. Add synthetic negative tests that custom configuration and legacy ADC files are neither hashed nor copied. Check both selected transfer and new remote-supervisor call paths; independently review current changes.
3. Verify exact roots/directions, exclusions, existing-target conflicts, checksum postconditions, locks and failed/partial receipts using bounded disposable fake transports. Default no deletion and no overwrite of conflicting user work.
4. Agree actual endpoint, source/config selection, disjoint result paths, initial seed policy and approval. No cloud deployment is required for code qualification; a future endpoint may be existing infrastructure.
5. After explicit activation approval, run a small selected transfer and verify intended bytes and protected paths. Do not synchronize whole homes, credentials, environments, caches, Terraform/state data or repository internals by default. Source synchronization is not a Git-history backup.
6. Add/activate Syncthing only if continuous synchronization is wanted and current coordination/conflict/recovery controls are independently accepted. Keep rsync usable without requiring a daemon. Real cloud resources require cost/teardown agreement separately.

**Relevant files:** `src/python/{selected_transfer,remote_development,dataset_lock,sync_supervisor,remote_sync_supervisor,file_transfer}.py` and matching tests.

## Reporting and completion

Deliver in this order:
1. Current core verification receipt and honest blockers.
2. Approved, bounded baseline and evidence-backed proposals.
3. User-reviewed shared YAML plus optional-customization backlog.
4. Local/Ansible field comparison and concrete previews.
5. Repository preservation/conflict report and separately tracked apply gaps.
6. Qualified selected synchronization path; actual transfer receipt only after activation approval.

A container checker, Packer build, GPU demo, managed-apply fixture or large test total is not a substitute for these deliverables. Optional container/development consistency work remains separate and does not move the native installation into containers. Whole-plan completion must still reconcile the original requirements, including unfinished apply/adoption capabilities; completion of this core sequence is not permission to relabel those done.

**Immediate next action:** Implement and fixture-test the small algorithmic host collector/import path in step 2, starting with BoredEngineer and IsaacSim, then system-package/machine metadata. Do not expand devcontainer access or start real host observation automatically. Fix sync protection in its own bounded slice without delaying unrelated observation/review work.
