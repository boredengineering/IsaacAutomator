# Shared Profile Discovery and Workspace Naming — Review Plan

**Status:** Discussion draft. Documentation only; implementation is not authorized by this document.

**Latest scope clarification:** Agent-led observer/shared-profile/installer implementation is paused at the user's request for manual review and implementation. Sections P1–P5 and N1–N7 are retained as discussion material, not an active execution queue. The user subsequently selected existing Ansible repository variables as a narrower possible cloud starting point. Section 8B records its specific CLI-validation mismatch; this addition authorizes documentation only, not code changes or deployment. It does not resume the broader profile work.

**Goal:** Use bounded observations of the working local setup, evidence-backed proposals and user review to discover an intuitive desired profile, including unique tools/dependencies, their host/container/environment placement, and stable custom workspace naming. Preserve the working machine and evaluate shared YAML intent for isaac-installer and Ansible without executing either installer. File synchronization and remote devcontainer use remain complementary work, not substitutes for environment provisioning.

**Architecture proposal:** Independent observation produces a baseline; a proposal layer derives a candidate desired profile with evidence and unresolved decisions; user review and comparison refine that candidate. Reuse the existing profile/resolution boundary where suitable, but never invoke mutating installer checks to collect observations. Local/Ansible execution is a separately authorized future stage, not part of profile discovery.

**Technology:** Existing YAML/PyYAML profile parsing, Bash installer, Python profile tooling and tests, Git, and later Ansible/Packer consumers. No new dependency is selected.

**Implementation discipline:** After design approval, use failing offline tests before behavioral changes and independent review for each bounded slice. No commits, pushes, real installer execution or cloud operations without separate authorization.

## 1. Scope and review status

- [x] Capture the user's workspace-naming incident and current source behavior.
- [x] Record a proposed YAML interface and path-resolution rules.
- [x] Capture the corrected purpose: observations and comparison help discover desired intent; a complete desired profile is not a prerequisite.
- [ ] Review the observer safety boundary, output contract and user decision workflow in section 8.
- [ ] Implement and independently test an isolated, fixture-only prototype after approval.
- [ ] Separately approve narrowly scoped observation on the actual local machine.
- [ ] Produce and refine a candidate desired profile with the user.
- [ ] Validate shared YAML semantics and non-executing adapter outputs offline.
- [ ] Revisit naming implementation and installation only under new scope approval; N1–N7 are deferred, not the current execution queue.

The user requested a place to continue discussing details, not a finished specification or immediate implementation. Proposed keys, commands and test files below are not delivered interfaces. Keep unresolved choices visible as this document evolves.

### In scope first

- More intuitive shared profile YAML, discovered from the user's working setup and preferences rather than designed entirely from assumptions.
- Observation → evidence/questions → candidate desired profile → user review → comparison/refinement.
- Custom grouping-folder names such as `BoredEngineer` or any other valid user-selected name.
- Clear separation of workspace root, workspace name, repository name and remote identity.
- Predictable precedence, collision handling and non-mutating preview.
- Compatibility with existing installer profiles and existing checkouts.
- Incremental discovery of custom dependencies/tools (section 8.1A), genuine no-change dry-run (8C), enforceable workstation protection (8D), and per-capability review/acceptance (8E). These are design requirements, not permission to execute.

### Deferred, but not forgotten

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

### Current implementation

Paths below are repository-relative; line references are inspection anchors, not permanent API locations.

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

This reproduces the destination-selection mechanism, not the complete historical installation. Original invocation inputs/logs were not recovered. The fixture is not a committed regression test, and the naming feature has not been implemented.

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

## 4. Proposed YAML contract — not supported yet

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

Proposed `--workspace-name` is a future interface, not an existing command. Decide whether environment overrides remain supported; do not let inherited environment values accidentally win or leak between profile loads.

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

- **User-approved naming policy: case-preserving names, exact selection, case-insensitive collision detection.** Preserve the user's chosen spelling/case; never automatically lowercase or substitute another folder's spelling. This approves the design only, not implementation or filesystem changes.
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
- Do not persist controller-specific absolute home paths as portable cloud intent. Resolve target paths on the selected target.

## 7. Decision register — review before implementation

| ID | Question | Recommendation | Status |
|---|---|---|---|
| D1 | Public field name? | `workspace.name`, separate from remote owner. | Proposed |
| D2 | Layout names and default? | Add `named`; retain `flat`; migrate legacy modes explicitly. Preserve current default until reviewed. | Open |
| D3 | Missing name? | Require it for named execution; interactive setup can suggest and persist a confirmed choice. | Proposed |
| D4 | Username suggestion source? | Optional explicit setup-time suggestion only; no implicit GitHub calls or Git author-name fallback. | Open |
| D5 | Case handling and case-only collisions? | Case-preserving names, exact selection, case-insensitive collision detection; require explicit resolution and preserve chosen spelling. No automatic lowercase/substitution; unattended ambiguity fails closed. | User-approved design; not implemented |
| D6 | Aliases such as the incident's names? | Explicit workspace selection is sufficient initially; defer a general alias registry. | Proposed |
| D7 | Allowed characters and root paths? | Spaces supported; reject unsafe segments; settle Unicode, whitespace, relative roots and symlinks with tests. | Open |
| D8 | Legacy keys and CLI flags? | Preview migration; define conflict/deprecation behavior, no silent precedence changes. | Open |
| D9 | Where does a user's selection persist? | Explicit user-selected profile, with no overwrite of existing content without approval. | Open |
| D10 | Existing checkout adoption? | Report identity/state and require an explicit policy; naming does not authorize Git mutation. | Deferred design |
| D11 | Shared implementation boundary? | Reuse the existing profile architecture; choose one tested resolution specification before Bash/cloud adapters. | Open |
| D12 | What is discovery for? | Use observed evidence and comparison to find the desired profile; automatically propose, but do not silently approve intent. | User-confirmed direction |
| D13 | Where may observation run first? | Disposable fixtures only; real-machine access requires independent safety review and explicit approved paths/operations. | Proposed safety gate |
| D14 | How broad is the first observer? | Workspace/repository metadata is a proposed first slice, not the whole goal. Admit custom tool/package/environment probes incrementally under 8.1A/8D; do not require the full catalogue up front. | Initial slice/probes open |
| D15 | Which output may be written? | New explicitly selected local report/candidate files only; no overwrite of active profiles or private-data publication. | Open: destination/retention |
| D16 | Which YAML is the candidate targeting? | Review the existing workstation-profile schema and legacy adapter limits; do not invent a third executable format or weaken baseline rejection. | Open |
| D17 | What happens to uncertain proposals? | Keep unresolved questions in the report; never convert unknown to healthy, disabled or approved intent. | Proposed |

## 8. Immediate workflow: discover the desired profile safely

### 8.1 Purpose and three distinct outputs

The observer is not merely an inventory utility. Its purpose is to help the user discover what the desired profile should express. It must work when no desired profile exists yet.

1. **Observed baseline:** bounded facts about the selected target, with evidence and limitations. This is not executable installation intent.
2. **Candidate desired profile:** proposed settings inferred from evidence plus the user's stated preferences. It may be incomplete. Every proposal remains distinct from a confirmed decision.
3. **Review/comparison report:** initial ambiguities and proposal rationale, then differences between observations and the evolving candidate. There is no meaningful conformance verdict against an absent desired profile.

Loop: observe → propose → ask/review → revise candidate → compare → resolve or retain uncertainty. Approval of the resulting profile means “this describes what I want,” not “apply it to my machine.”

Do not classify every difference as drift or repair work. A difference can be intentional, obsolete, a future desired change, unsupported, or not yet understood. The tool should propose sensible values proactively instead of making the user specify everything from scratch.

### 8.1A Custom tools and dependencies — reserved discovery space

**User clarification:** The unique tools/dependencies are not all known yet; discovering them is part of the goal. Do not require a complete customization catalogue before designing or, when separately authorized, implementing the bounded observation/proposal workflow. Leave explicit space for these findings instead of guessing requirements or narrowing the eventual inventory to repositories alone.

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

**Future code extension point, not a new framework:** when implementation is authorized, keep observation and profile-mapping logic modular so individual custom-item readers/mappings can be added and tested later. Choose the concrete location after inspecting reusable code. A documented TODO or unsupported-item result is sufficient until an item is understood; do not add arbitrary shell hooks, install commands from discovery, a plugin system or a no-op handler that claims success.

An undiscovered or optional unresolved item need not block a useful partial report or continued profile review. If the user selects an item as required but its installation mapping is unsupported, report that limitation and block claiming/applying a complete supported profile for that scope. Do not silently omit it or fabricate defaults. Full-machine parity remains unproven until actual coverage and acceptance justify it.

This is reserved planning space only. It does not resume agent-led implementation, scanning of the local machine or changes to existing profiles.

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

Independent review must approve the concrete observation mechanisms and confinement before a real-machine run. The implementation is not yet written or proven safe. Existing devcontainer mounts or Docker access must not be assumed isolated.

### 8.4 Immediate stages and approval gates

#### P1 — Review output examples and scope

- [ ] Resolve the D12–D17 choices needed for the first admitted probe slice; choose the intended profile schema using existing code/documentation. Record undecided custom-item coverage in 8.1A without blocking unrelated discovery design.
- [ ] Review synthetic baseline/candidate/report examples, including no initial profile, dirty checkouts, multiple installations and unresolved fields.
- [ ] Select exact proposed implementation/test paths only after locating reusable resolver/report boundaries. No observer command/API is advertised yet.

#### P2 — Implement a fixture-only prototype after approval

- [ ] Add failing tests for the observation/proposal/decision loop before implementation.
- [ ] Use temporary directories and tiny local Git repositories, including submodule/worktree fixtures; no copies of private projects or live installation.
- [ ] Constrain execution to disposable storage, no credentials/network/privileged access/host Docker socket and no writable real-home/repository mounts. Stub refusal is useful testing but not a substitute for an enforced boundary.
- [ ] Test that the observer neither creates success markers nor invokes legacy mutating checks; record before/after file/index/ref state and attempted operations.
- [ ] Independently review safety and proposal correctness. A fixture pass does not authorize real-host access or establish robotics runtime compatibility.

#### P3 — Separately approved bounded local observation

- [ ] Confirm the actual target machine; this repository's devcontainer is not automatically the user's physical workstation.
- [ ] Agree explicit read roots, admitted commands, exclusions, report destination, resource limits and enforcement mechanism with the user; satisfy section 8D S1 and applicable target/path protections first. No agent should guess host paths or escalate privileges.
- [ ] Only after approval, execute the admitted observer and verify its action log/output scope. If adequate protection is unavailable, stop and offer user-supplied sanitized metadata; do not substitute a cloud deployment.
- [ ] Record actual coverage and limitations. No install, repair, runtime smoke test or automatic profile application follows this step.

#### P4 — Discover and approve desired intent with the user

- [ ] Generate proposals from evidence and stated preferences; do not require a finished profile first.
- [ ] Review meaningful choices in small groups; accept, reject or defer each without changing the target.
- [ ] Recompare after candidate edits and expose unresolved dependencies/unsupported fields.
- [ ] Export only to explicitly approved new draft/profile files. Preserve active profiles, local changes and existing naming. Record that profile approval is not execution approval.

#### P5 — Offline shared-profile evaluation

- [ ] Check which approved fields map to both local and Ansible intent; keep target-specific settings explicit rather than force one-to-one scripts.
- [ ] Where safe rendering adapters exist, compare their outputs on fixtures; missing adapters remain unimplemented, not presumed equivalent. Creating adapters needs its own bounded approval.
- [ ] Report schema validity, consumer coverage and configuration consistency separately from runtime acceptance.
- [ ] Stop here. Naming behavior changes N1–N5, repository mutation N6 and execution integration N7 require a new scope decision. No cloud spending, sync claim or live reinstallation is necessary for this milestone.

### 8.5 Additional acceptance tests for discovery

- No desired profile provided: still produce evidence-backed candidate proposals and questions, not an error requiring the user's final intent.
- Proposed values do not become accepted automatically; user rejection/edits survive rescans.
- Candidate comparison distinguishes accepted differences from unknown/unsupported data; no repair commands emitted for automatic execution.
- Dirty checkout is not represented as reproducible solely by its HEAD; no private patch contents collected.
- Failed, timed-out and inaccessible probes remain explicit; candidate export refuses unresolved required fields.
- Safety tests include credential-bearing URL fixtures, hostile paths, config includes, symlink escape, worktrees, external helpers, offline partial-clone behavior and output overwrite attempts. No real credentials used.
- Before/after fixture state and confinement checks support the read-only claim; metadata-only success is not a runtime test.

## 8A. Deferred installer implementation slices — not the current queue

The original N1–N7 sequence below is preserved for later review, not automatic execution after discovery. Each requires new scope approval, failing offline tests before changes, passing scoped checks and independent review. The working machine is never an implicit installation target.

### N1 — Approve semantics and capture regressions

- [ ] Resolve D1–D9 sufficiently for a bounded local naming implementation.
- [ ] Add proposed `src/tests/installer_workspace_contract.test.py` using temporary directories and controlled environment/commands.
- [ ] Capture the incident, explicit-name precedence, legacy behavior and naming preview side effects before changes.
- [ ] Record actual failures without running installer install/repair/status against a real workstation.

### N2 — Parse and validate configuration

- [ ] Extend `isaac-installer/lib/core/profile_parser.py` and `config.sh` for the approved fields and compatibility rules.
- [ ] Extend `src/tests/installer_profile_contract.test.py` for new keys, invalid combinations and sequential profile loads.
- [ ] Avoid an unrelated rewrite of every legacy field; validate touched workspace semantics and report unsupported proposed fields explicitly.

### N3 — Wire CLI precedence

- [ ] Inspect full argument/profile loading flow in `isaac-installer/bin/isaac-installer`.
- [ ] Implement the reviewed name override and compatibility flags without profile loading clobbering explicit CLI values.
- [ ] Test real argument-to-loader transport through a non-mutating seam; do not bypass it with mocks that simply pre-populate the final environment.

### N4 — Implement pure resolution and preview

- [ ] Refactor the relevant helpers in `isaac-installer/lib/core/git_workspace.sh` behind the approved contract.
- [ ] Remove mutations from resolution; separate narrowly scoped execution actions.
- [ ] Handle existing paths, collisions, explicit overrides and root/home semantics; test preview/execution precondition changes.
- [ ] Agree an actual preview entry point after inspecting current CLI commands; do not advertise invented commands.

### N5 — Unify consumers and document compatibility

- [ ] Trace all helper consumers in `isaac-installer/lib/modules/`, `lib/core/state.sh`, `lib/core/audit.sh`, demos and CLI paths.
- [ ] Ensure install/status/audit/repair use the same resolved selection; do not let naming updates activate automatic drift relocation.
- [ ] Remove personal-name fallbacks only where this slice requires them, replacing them with shared resolution or explicit unknown errors.
- [ ] Update `isaac-installer/config/{default-profile,example-profile,minimal-headless,full-ecosystem}.yaml` and `isaac-installer/README.md` to match implemented behavior.
- [ ] Review all touched consumers independently and preserve unrelated installation functionality.

### N6 — Design repository adoption and update separately

- [ ] Distinguish installer-managed checkout from user-owned development checkout.
- [ ] Specify identity checks using repository metadata, not folder name alone; cover multiple clones and Git worktrees where `.git` is a file.
- [ ] Define dirty/untracked files, local commits, detached HEAD, remote mismatch and requested-ref changes.
- [ ] Specify explicit adoption/update choices; default to no destructive mutation.
- [ ] Review fork fallback and creation scope, tag provenance, upstream push protection, submodules/LFS and failure propagation.
- [ ] Add new tasks/tests after design review; this document does not yet authorize implementing these policies.

### N7 — Reuse in IsaacAutomator

- [ ] Reconcile with `src/python/workstation_profile.py`, `workstation_profile_command.py` and the existing Tasks 24–27 roadmap.
- [ ] Extend real profile-to-deployment/Ansible/Packer transport only after local naming rules are stable.
- [ ] Share a fixture matrix with target-specific home/path translation; do not assume cloud machines are disposable checkouts.
- [ ] Verify lifecycle/backend/distribution behavior remains independent.
- [ ] Record local and cloud acceptance separately; no parity claim from profile parsing alone.

## 8B. Narrow cloud starting point: Ansible fork overrides and CLI validation

**User direction:** Start from existing Ansible repository variables for one explicit cloud configuration. A more robust reusable flow can be considered later. Do not make shared-profile redesign, observer implementation or local-installer changes prerequisites for this bounded work.

> **Critical mismatch to resolve:** The deployment CLI validates Sim/Lab/Arena revisions against the official repositories before Ansible runs. A branch that exists only in the user's fork could be rejected even if Ansible is configured to clone that fork. Resolve this specific mismatch rather than starting a broader configuration redesign.

### What current source establishes

- `src/python/config.py:89–91` selects official Sim/Lab/Arena repository URLs.
- `DeployCommand.git_ref_callback()` in `src/python/deploy_command.py:243` chooses its validation repository from those configuration values; `latest` discovery uses the selected validation repository too.
- `src/ansible/inventory.template:11–15` transports component revision values but does not transport custom Sim/Lab/Arena repository URLs.
- The `isaacsim-source`, `isaaclab-source` and `isaaclab-arena-source` roles each have repository/checkpoint variables in their `defaults/main.yml`. Ansible-level overrides are possible, but their presence does not establish an end-to-end fork-selection flow in `deploy-gcp`.
- Native GR00T has separate `gr00t_git_repo` and `gr00t_git_checkpoint` variables and defaults to disabled. Its enablement and native/container selection require explicit review; do not assume the Sim/Lab/Arena callback controls it.

**Consequence:** An Ansible override alone may be too late to affect CLI preflight. A shared branch/tag name could also validate successfully upstream while naming different content in the fork. Successful validation must refer to the same repository/ref pair that will be installed, not merely a matching ref string somewhere else.

### Bounded review and implementation checklist — not yet authorized to execute

- [ ] Record the intended repository URL and revision for each enabled component; distinguish remotely available commits from uncommitted local work. Review Arena submodule pins without changing them.
- [ ] Trace the supported Ansible override-file invocation and precedence through the existing deploy command. Do not invent a CLI flag or assume an extra-vars file is already forwarded. Keep shared defaults and the local installation untouched.
- [ ] Reproduce the mismatch with offline tests in `src/tests/deploy_command.test.py`: a fork-only branch must be checked against the fork, not upstream. Include the same ref name with different fork/upstream contents, missing refs and `latest` selection.
- [ ] Choose the smallest explicit transport change needed so repository selection is available before revision validation and the same effective source selection reaches Ansible. Review callback ordering and inventory/override precedence; do not build a new general profile system to solve this.
- [ ] Preserve validation. Do not work around the mismatch by disabling checks, silently substituting an upstream ref or modifying global repository defaults for everyone.
- [ ] Test actual configuration transport through the chosen non-mutating boundary, including default-upstream compatibility and disabled components. Mock network lookups only in tests; no live GitHub/cloud access is required to reproduce routing errors.
- [ ] Independently review the bounded fix and report which source/ref pairs reach Ansible. Exact installed commits and runtime behavior remain later acceptance evidence; branch names alone do not guarantee immutable reproduction.

No override file, callback fix or deployment is created by this plan addition. A real GCP run requires separate explicit authorization and review of IAM, capacity, spending, cleanup and the chosen software configuration. Selecting forks does not synchronize local edits or prove a working Sim/Lab/Arena/GR00T stack.

## 8C. Required installer dry-run: preview actions without applying them

**User requirement:** isaac-installer needs a reliable dry-run capability to make development and review safer. This records a requirement, not authorization to resume implementation or test the installer on the working machine.

### Existing flag is not a verified safety boundary

`isaac-installer/bin/isaac-installer` already accepts `--dry-run` and advertises no system changes. Source inspection shows incomplete enforcement:

- `evaluate_and_run_stage():130–171` invokes `check_func` before the dry-run branch. Some existing checks mutate state; for example, `check_isaac_sim()` in `lib/modules/isaacsim.sh` can write an EULA marker and deploy runtime bridges.
- `cmd_install():381–390` calls logging initialization, system probing and state initialization without a dry-run guard. Confirmed source writes: `lib/core/logging.sh:45–60` creates a log directory/file, replaces a latest-log symlink and attempts recursive ownership changes; `lib/core/state.sh:18–37` creates the state directory and, when absent, a state file with ownership changes. Full startup/probe call paths still need audit; this is not merely a hypothetical risk from misleading function names.
- `cmd_install():422–425` calls `install_streaming_provider` when selected without checking `DRY_RUN`.
- The final message at `cmd_install():435` says no modifications were made, but the above control flow does not justify that guarantee. This is source-backed risk identification, not a live dry-run test.

Do not recommend the current flag as protection for the user's working setup. Unprivileged execution alone is insufficient: user-owned repositories, environments and configuration can still be changed.

### Required semantics

- Dry-run previews actions for a supplied candidate/desired profile. The observer workflow discovers that profile from evidence and user decisions. These are complementary functions, not substitutes for one another.
- Share pure configuration resolution, admitted read-only observations and action planning with execution so preview does not become a second divergent implementation. Mutations must sit behind an explicit execution boundary; do not merely add scattered `if DRY_RUN` checks while leaving initialization/checks unsafe.
- Default dry-run writes nothing on purpose: no logs, state ledgers, resume hooks, EULA markers, directories, links, ownership changes, Git index/config/ref changes, services, packages, downloads or repairs. An optional report export is a separate explicit write to a new approved destination, never an implicit log side effect. Ordinary read access-time caveats from section 8.3 still apply.
- No sudo, network/auth discovery, arbitrary custom-build commands, imports from observed environments or runtime launches during the initial offline dry-run. Missing information is reported as unknown/blocked, not fetched or guessed. Future network preflight, if needed, must be a separate explicitly scoped operation.
- Cover every path reachable from the selected command, including startup, profile loading, detection, excluded stages, optional streaming, failure handlers and cleanup. Commands/modes that do not support dry-run must reject it before mutation rather than silently ignore it.
- Show proposed action, target, reason, evidence and potential overwrite/destructive effects; distinguish excluded, already satisfied, would change, unknown and blocked. Never describe a proposed install or uncertain check as successful installation.
- Unsupported/unsafe probes must report incomplete preview and a documented failure status; define exit-code meanings before implementation. Do not print an unconditional “no changes” guarantee without supporting enforcement and verification.
- Dry-run is not a transaction or rollback mechanism. A successful preview does not authorize execution or guarantee that later apply will succeed; execution must recheck relevant preconditions.

### Future validation gate

- [ ] Audit the full command call graph and reuse suitable pure resolver logic; do not execute existing dry-run on the live workstation to discover its side effects.
- [ ] Add failing fixture tests for mutating checks, unconditional initialization, optional streaming, custom commands, failure paths and unsupported subcommands.
- [ ] Test all selected/excluded component combinations relevant to those paths, with before/after fixture filesystem and Git-state checks plus detection of attempted writes, network, privilege escalation and external helpers.
- [ ] Use enforced disposable isolation, not only command mocks or a branch/worktree. No writable real-home mounts, cloud credentials or host Docker socket.
- [ ] Compare previewed actions with execution against disposable fixtures where safe, so stage selection and resolved targets agree; this is not GPU/runtime acceptance.
- [ ] Independently review enforcement and evidence before advertising no-change dry-run as trustworthy. Any real-machine use requires separate explicit approval.

The existing flag remains unqualified. No installer code or documentation advertising it has been changed by this requirement entry; implementation and real-host testing remain paused.

## 8D. Workstation protection mechanisms to implement and verify

**Required safety outcome:** protect the existing working installation, uncommitted progress, repositories, environments, configuration and data. No software can promise zero risk or automatic recovery from every system change. The enforceable default for this current machine is observation/preview only, once separately qualified and authorized; installation, repair, migration and removal stay unavailable under that authorization.

### S1 — Separate observation, preview and execution before initialization

- [ ] Dispatch observation/dry-run before any mutating logging/state/bootstrap initialization. Admit only reviewed read-only probes; do not source broad installer entry points. Audit CLI startup, profile parsing, modules, traps, cleanup, resume and optional stages—not only install functions.
- [ ] Parse profile data as data, never shell code. Reject unsupported executable hooks in observation/preview. Scrub inherited command/config overrides, use controlled subprocess environments and disallow external helpers as specified in 8.3.
- [ ] Refuse observation/dry-run as root and prevent privilege escalation in their execution environment. Confinement must deny network, writable inspected mounts, host control sockets/devices and access outside approved metadata roots, except explicitly allowlisted read-only runtime/interpreter files and minimal sandbox pseudo-devices. Subprocesses inherit those restrictions; needed tool files do not authorize arbitrary host reads. A missing enforcement mechanism is a blocker, not permission to fall back to an ordinary shell.
- [ ] Use a disposable report writer with only the explicitly approved output destination writable; stdout-only preview needs no persistent output directory. Bounded temporary storage may exist outside inspected roots, but must not expose real home/state/credential stores. Verify attempted writes are denied, not merely absent in one successful run.
- [ ] Set traversal depth/file-count/output/time limits and cancellation behavior; do not exhaust workstation memory/disk or recursively scan model/data trees. Record truncated coverage as incomplete. Exact budgets and confinement implementation must be reviewed before P3.

### S2 — Protect targets and ownership at every mutation boundary

- [ ] Future execution must identify the selected host, target user/home, profile revision and exact resource/action set. Never infer the physical workstation from the current devcontainer or treat a cloud checkout as automatically disposable.
- [ ] Default all pre-existing resources to user-owned/unmanaged unless explicit adoption has been reviewed. An installer marker, matching directory name or clean Git status is not sufficient permission to modify them. Adoption records the permitted actions; it is not blanket ownership of a parent directory.
- [ ] Naming, discovery and adoption never automatically reset/clean/stash, rewrite remotes, change branches/submodule pins, delete untracked files, rename/merge workspaces, or recursively chmod/chown existing trees. A later managed-repository update requires a separately approved exact action, ownership and recovery policy; it cannot inherit permission from selecting a workspace. Dirty, ignored, untracked and nested-repository content must remain protected. Case-preserving resolution and explicit case-only collision handling still apply.
- [ ] Enforce validated destination containment at use time, not just at preview: reject empty/root/home-wide destinations, traversal, unsupported symlink/mount/hardlink cases and changed target identity. Use safe exclusive creation/no-follow or equivalent primitives; a string-prefix check or one earlier `realpath` is insufficient against races. If a safe primitive is unavailable for an operation, keep that operation unsupported.
- [ ] New profile/report writes refuse overwrite by default. Future authorized managed-file replacement uses same-directory staging and atomic replacement where supported, with expected-content checks; refuse concurrent edits and never overwrite a changed user file during rollback.
- [ ] Scope a local execution lock to the actual affected resources, including overlapping profiles. Lock conflict stops execution. Because locks do not stop editors or external package managers, recheck relevant preconditions immediately before each change and abort/review stale plans.

### S3 — Keep high-risk operations out of discovery and ordinary approval

- [ ] GPU drivers, kernel/DKMS modules, bootloader/initramfs, display manager, system Python, global package removal/upgrades, storage/mounts, network/firewall/SSH and service enablement require a separate high-risk maintenance scope. Profile approval, `--yes`, resume and a successful dry-run must not implicitly authorize them on this machine.
- [ ] Treat modifications to existing Conda/UV environments, Sim/Lab/Arena/GR00T installations and shared libraries as preservation-sensitive. Prefer explicitly selected new versioned environments/directories for evaluation; do not upgrade the working environment in place as a test. Do not switch active links until separately approved and verified.
- [ ] No automatic reboot, driver replacement, resume-on-login/reboot hook, or startup service from observation/preview. Future apply may recommend a manual maintenance step, but must stop if its required protection is unavailable. Installation hooks/custom build scripts are executing code, not harmless configuration; review and isolate them before any apply.
- [ ] Existing VS Code/devcontainer settings, AGENTS.md, credentials, models, datasets and live databases remain outside mutation scope. No inferred consent from a profile, scan or report. Specific later permission is required for any applicable change.

### S4 — Recovery and interrupted operations, without false rollback promises

- [ ] Before any separately authorized mutation of existing resources, review a recovery manifest: affected paths/resources, local and untracked work, nested repositories/submodules, environment definitions versus non-reconstructible contents, configuration, data, ownership/permissions and external dependencies. A Git commit or package list alone is not sufficient recovery.
- [ ] Choose protected backup/snapshot storage outside the affected tree and synchronization scope; check capacity and appropriate consistency. Databases need application-consistent backup. Credential backup is a separate user-controlled security decision, not observer collection.
- [ ] Restore representative affected content into an alternate disposable destination and verify bytes/metadata and relevant usability before relying on recovery. Any system-level maintenance additionally needs a tested rescue/console path and recovery procedure appropriate to that host. No restoration experiment on the working installation.
- [ ] Record intended/started/verified/failed operations and created-resource identities in an apply-only journal. Atomically mark success only after postconditions; never mark failed/partial work healthy. SIGTERM, timeout, crash or reboot must not auto-resume mutations on next launch. Revalidate before a separately authorized resume.
- [ ] On failure stop dependent actions, retain sanitized diagnostics and report partial changes. Cleanup can remove only verified unchanged resources created by that run within approved bounds; never recursively delete a pre-existing path or “restore” over subsequent user edits. Prefer manual recovery when identity or ownership is uncertain.
- [ ] Package changes, drivers and arbitrary scripts are not universally reversible. If rollback/recovery is unproven, refuse that local operation rather than advertise a transaction. Backups reduce risk but neither authorize changes nor guarantee recovery.

### S5 — Sync and remote-development safeguards

Preserve the existing [remote-development plan](../isaacautomator/remote-dev-plan.md) as related context: local source → rsync/continuous sync → cloud workspace → GPU devcontainer bind mounts. Syncthing is a recorded candidate; the historical recommendation was Mutagen. No engine selection or continuous-sync implementation is implied here.

- [ ] Never synchronize live virtual environments, container writable layers, Git metadata, Terraform state, credential stores or live database volumes by default. Select source/configuration and artifact folders explicitly; user-approved exceptions need their own consistency and recovery review.
- [ ] Define direction, ownership, exclusions, conflict/deletion policy and initial seed before enabling synchronization. Do not let rsync and a continuous engine independently write the same destination concurrently. Versioning/backup and deletion propagation must be deliberately configured and tested; conflict files are not a backup.
- [ ] Protect profiles, recovery copies and active local configuration from automatic remote overwrites. Transferring a devcontainer definition does not authorize its hooks, rebuild, dependency installation or VS Code setting changes. Sync is separate from desired-profile approval and installer execution.

### Implementation seams and proof required

Audit existing `isaac-installer/bin/isaac-installer`, `isaac-installer/lib/core/profile_parser.py`, `isaac-installer/lib/core/{config,git_workspace,state,logging,audit}.sh`, and each selected `isaac-installer/lib/modules/` consumer before placing the boundaries. `state.sh` and `logging.sh` include ownership-changing paths; state/cleanup logic cannot be assumed passive. Reuse existing helpers only after making their contracts safe. Do not create a general authorization framework; keep local guards and an operation record bounded to this installer.

- [ ] Add failing tests before fixes, then enforce read-only observation/preview in disposable isolation. Mutation tests use synthetic writable targets only; driver/boot/service behavior requires a disposable VM, not a container presumed to isolate host effects. No paid cloud test is required for this planning/discovery phase.
- [ ] Include denied writes/network/helpers, malicious profile/path data, case collisions, symlink/hardlink/race escapes, output collisions, changed targets, overlapping runs, disk-full/permission errors, interrupted writes, SIGTERM/crash, failed postconditions, stale resume and cleanup of foreign resources. Use fake secrets only.
- [ ] Compare before/after fixture contents, permissions, links, Git refs/index/config and attempted operations. Add a negative-control writer to prove confinement actually rejects writes. Tests of safety guards must not rely solely on mocks.
- [ ] Demonstrate unchanged rerun, a single intended change, preserved dirty/untracked/ignored/nested work and failure recovery on disposable fixtures. Qualify each supported action separately; no blanket safety/idempotence claim.
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

**Review completion:** record concrete decisions and evidence links per slice. Documentation review can accept this direction while confinement mechanism, resource budgets, recovery storage and custom-item mappings remain explicitly open. Those choices become hard blockers only before the relevant real operation. Implementation remains paused until separately requested.

## 9. Deferred naming validation matrix and commands

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

Existing regression targets (commands are for future authorized implementation, not recorded as run for this draft):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 -B src/tests/installer_profile_contract.test.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 -B src/tests/workstation_profile.test.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 -B src/tests/workstation_profile_command.test.py
```

Run from the repository root using a verified interpreter with the existing required dependencies, including PyYAML. The proposed new suite should follow the existing unittest style and be run directly once created. Shell syntax checks are supplementary, not behavioral acceptance. Keep subprocess environments isolated from credentials and real home directories; stub/refuse mutating commands in fixture tests.

## 10. Related records

- [Original installer architecture and workspace discussion](../docs/isaac-install-plan.md)
- [Host compatibility plan](../plans/isaac-installer-host-compat.md)
- [Installer/Ansible compatibility plan](../plans/isaac-installer-ansible-compat.md)
- [Shared workstation roadmap, especially Tasks 24–27](../plans/terraform-remote-backend-plan.md)
- [Historical workspace implementation checkpoint](../../memory/sessions/20260820_215440_f1a2b3c4.md)
- [Later source-backed local/cloud parity review](../../memory/sessions/20260910_061133_51928612.md)
- [Multi-repository remote development and synchronization plan](../isaacautomator/remote-dev-plan.md)

These records contain historical completion claims as well as later corrections. Use current source and fresh verification before claiming an old issue is fixed. This draft adds discussion context without rewriting those records or changing the active software stack.

## 11. Completion criteria and next discussion

**Paused profile-discovery milestone:** a safely collected or user-supplied baseline, evidence-backed candidate desired profile, reviewable decisions and comparison report, with schema/consumer limitations explicit. Fixture validation and a separately approved real-host observation are distinct achievements; neither may be reported as the other. An incomplete candidate can be a useful discussion result but is not a completed executable profile.

**Later naming milestone:** explicit names resolve deterministically, conflicts are reported safely, legacy behavior is accounted for, previews have no application writes, consumers agree, and offline regression evidence plus independent review are recorded.

Full existing-repository safety and local/cloud runtime parity remain separate gates.

**Current review scope:** the discovery/profile direction, case-preserving section 4/5 contract, custom-item backlog, no-change dry-run, workstation protection (8D) and incremental acceptance (8E). Section 8B remains an independent narrow cloud fork-selection path, not a dependency on this broader work. Review/update authorization is documentation-only; implementation remains paused. No observer, installer, sync service, backup/restore or cloud operation is authorized or executed by this update.
