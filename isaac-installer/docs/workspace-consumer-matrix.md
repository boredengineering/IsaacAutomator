# Workspace naming consumer matrix

This is a **source-backed acceptance boundary**, not qualification of legacy
installation, status or repair as read-only operations. Scope: primary
[workspace plan](../../.agents/references/isaac-installer/workspace-repository-management-plan.md)
N4/N5/N6, sections 6/9, and the separate unsupported-adoption allowance in 8E.
No physical workstation was inspected and no full installer or real-host module
operation was executed to produce this matrix. Extracted consumer seams and
synthetic fixture tests are not runtime installation proof.

## Selection contract

- `config.sh:load_config_profile` transports `workspace.root/layout/name/default_owner`
  through `CFG_WORKSPACE_*` to `WORKSPACE_DIR/LAYOUT/NAME/DEFAULT_OWNER`. Explicit
  `CLI_WORKSPACE_*` wins over profile over defaults; explicit empty root/name/owner
  clears the profile value. Inherited operational values are not CLI overrides.
  Defaults retain legacy `auto`. Named requires an ASCII, case-preserving single
  directory segment; internal spaces are supported. Conflicting name/owner is
  rejected; identical values are accepted. A name on other layouts is rejected.
- `git_workspace.sh:resolve_repo_dest_path(name, slug, explicit_path)` validates
  workspace settings first, then gives a supplied explicit repository path priority
  over root/group/owner derivation. A repository override is an argument such as
  `ISAACLAB_DIR`, **not** an invented `repositories.*.directory` YAML binding.
- `~` expands against the selected target home, never the controller's home.
  Named is `<root>/<workspace.name>/<repo-name>`; flat is `<root>/<repo-name>`.
  Neither derives a local group from a GitHub owner.
- Legacy `auto/org` destination behavior is conditional: configured owner (ignoring
  `<...>` placeholders), otherwise personal GitHub slug/HTTPS/SSH owner, excluding
  exact upstream owners `isaac-sim`, `NVIDIA`, `huggingface`; otherwise flat.
  The **shared pure** `workspace_paths.resolve_paths` reproduces the original
  candidate ordering (resolved owner, then slug owner, even official upstreams)
  using complete caller-supplied immediate directory entries. It reuses a unique
  existing owner spelling; multiple case-fold matches refuse rather than picking
  a `find | head` result. Thus an existing slug-owner directory can still win when
  the configured-owner directory is absent, preserving actual legacy semantics.
  Missing auto/org root entries mean `destination: null`, `status: unknown`, with
  a separately labelled lexical `candidate_destination`; no invented observation.
- Configured active selection (named/flat, explicit repository path, root or
  owner) uses the same exact destination even if missing. Only unconfigured
  `auto/org` retains bounded unique discovery before destination fallback.
  Empty-source active callers use canonical module source defaults. Discovery
  is not adoption and never overrides configured destination selection.
- `resolve_repo_dest_path` now calls the shared Python runtime wrapper for **all**
  layouts and overrides, not a duplicated shell owner algorithm. The wrapper
  delegates selection to the pure API, opens directory components relative to
  nofollow handles, and inspects only bounded immediate metadata. No `.git`
  contents are read by destination resolution. Each listing is capped at 4096;
  supplied/global discovery evidence is capped at 16384 total entries.
- `find_existing_repo` now uses bounded nofollow legacy discovery and rejects
  multiple checkouts, case ambiguities, symlink paths and unsupported `.git` files.
  `resolve_active_repo_dir` falls back only on proven no-match (exit 1), not on
  inspection/ambiguity refusal (exit 2). This does not make legacy status safe.
- The filesystem-inspecting shell helpers reject unsupported selected symlinks,
  path-component files/inaccessibility and selected repository-leaf case-only
  collisions in **every** layout/override, even when the exact spelling also exists.
  Named group collisions are also rejected. The shared runtime wrapper obtains
  bounded nofollow selected-parent listings; configured flat collisions refuse
  distinctly from global discovery ambiguity, not by reviving global search. The pure
  migration API performs **no filesystem inspection**: missing evidence is unknown,
  never absence, cleanliness, ownership or permission to create/adopt.

## Actual consumers and boundaries

Paths in this table are relative to `isaac-installer/`.

| Consumer | Actual selection/data flow | Implemented vs refused/unqualified |
|---|---|---|
| `lib/core/config.sh`, `profile_parser.py` | Effective workspace field precedence/clearing above; repository source/ref exports are separate. | Parsing/transport implemented; does not move profiles/checkouts or silently bind new per-repository directory fields. |
| `lib/modules/isaaclab.sh:resolve_isaaclab_dir` | `resolve_repo_dest_path("IsaacLab", ISAACLAB_REPO or canonical upstream, ISAACLAB_DIR)`; check/install and CLI validation reuse destination. | Exact named destination helper implemented. Installation links Sim, installs editable packages, runs repository code and registers Desktop: not read-only or migration-qualified. |
| `lib/modules/isaaclab_arena.sh:resolve_arena_dir` | `IsaacLab-Arena`, `ARENA_REPO` or canonical upstream, `ARENA_DIR`; install/test also resolve Lab. | Same naming helper; installation may alter submodules, editable packages and `.env`. Existing-resource adoption not qualified. |
| `lib/modules/gr00t.sh:resolve_gr00t_dir` | `Isaac-GR00T`, `GR00T_REPO` or canonical upstream, `GR00T_DIR`; check/install/sync/test use destination. | Same naming helper; uv/Git/LFS/submodule/runtime operations are not part of preview. |
| `lib/modules/physical_ai.sh:resolve_lerobot_dir` | `lerobot`, `LEROBOT_REPO` or canonical upstream, `LEROBOT_DIR`; install uses destination. | Same naming helper. `check_physical_ai` checks package/CLI presence, not checkout identity; cannot prove repository satisfaction. |
| `lib/modules/isaacsim.sh` | `resolve_isaacsim_dir` selects explicit Sim prefix or standalone `TARGET_HOME/IsaacSim`; some integration paths resolve Lab. | Sim is a separate artifact prefix, not implicitly a repository in a named group. No artifact migration implied. |
| Lab/Arena/GR00T `cmd_* status` | `resolve_active_repo_dir` with each source and explicit override; all four initial assignments (including both Arena and Lab) explicitly return resolver errors before the status arm, even under conditional invocation. | Configured selection agrees with destination; unconfigured auto/org discovery remains distinct. Prefix-only synthetic tests execute no status probes. **CLI named dispatch is refused**; real status can write Git safe-directory config/fetch upstream and is not an admitted read-only preview. `.git` files/worktrees remain unqualified. |
| `lib/core/audit.sh:audit_all_components` | Lab/Arena/GR00T use destination helpers and propagate errors in every layout; no personal repository-path fallback. Sim and Conda resolved separately; LeRobot checks visualizer presence. | Selected repository wiring and report-wrapper refusal implemented; named CLI dispatch remains refused. Broad audit still inspects hardware/packages/auth; naming alone is not healthy-state proof. |
| `lib/core/state.sh:sync_state_ledger` | Resolves all four module repository destinations plus root/Conda/Sim before initialization; records selected paths even when missing, transports paths/metadata via argv, propagates resolver/metadata/write errors. | Configured selection unified; snapshot still writes `TARGET_HOME/.isaac-installer/state.json` and chowns. Fixture snapshots are not read-only real-host qualification or adoption proof. Not used by preview. |
| `state.sh:init_state/set_stage/update_repo_ledger` | State prefix is `TARGET_HOME/.isaac-installer`, independent of workspace name. Initial state records layout; repository ledger accepts caller path. Stage completion is a marker. | No workspace-name migration/identity proof; no automatic ledger rewrite in preview. Marker presence does not prove desired-state idempotence. |
| `state.sh:audit_workspace_drift` | Repository paths use selected module destinations, not first-found/personal checkout paths; root/repository/metadata failures propagate. | Repository path agreement implemented, not a broad audit rewrite. Legacy desired-source/ref checks and host/Git/link/Conda probes remain unqualified; not the evidence-only preview. |
| `state.sh:plan_workspace_repair/repair_workspace_drift` (`repair/fix`) | Selection-only plan reports four selected paths, `actions: []`, and unsupported mutation. Wrapper returns resolver failure or 77; removed self-healing body cannot run drift, ledger writes, moves, Git or adoption. | **Named CLI still refused**. No migration/repair apply is implemented; path reporting does not authorize adoption or qualify existing-resource health. |
| `lib/modules/demos.sh:install_demos_and_shortcuts` | Resolves Lab/Arena/GR00T destination helpers in all layouts before writes; six generated scripts bind selected paths via Bash `%q`, never rediscover. Desktop Exec passes the spaced launcher as quoted argv. | Fixture generation/execution proves bound-path selection; missing paths fail rather than fall back. Real generation writes/chmods/chowns and launchers execute runtime code: neither real operation is qualified by these fixtures; named refusal remains. |
| `lib/modules/conda.sh:install_python_env` | Lab active resolution includes source/override and explicitly returns errors in every layout, before cleanup/install; no swallowing or secondary destination fallback. Conda prefix remains separate from workspace naming. | Conditional and ordinary synthetic prefix tests prove refusal plus positive legacy cases. Workspace name is not Conda environment name; pin/runtime helpers are separately owned, and cleanup/hooks/install operations remain unqualified here. |
| `bin/isaaclab-env`, generated Conda hooks/shim | Sim prefix and resolved Conda runtime drive execution; standalone checked-in shim does not load workspace profile or select repository. | Not a workspace resolver or migration executor. Existing/generated shims must not be assumed to follow profile changes. |
| `lib/modules/hardware_teleop.sh` | Deployment of interface helpers resolves Lab via `resolve_isaaclab_dir`. | Inherits destination naming only; actual hardware/helper installation unqualified here. |
| `lib/modules/ecosystem.sh` and other modules | No direct workspace destination consumers found; their package/system/auth behavior is outside naming. | No implied migration support or authorization. |
| `bin/isaac-installer` legacy dispatch | Effective profile loaded, then named-layout refusal before command dispatch. Early read-only profile/discovery/preview routes are separate. | Do not remove refusal on strength of naming tests. Parent-owned `migrate-profile` integration must remain early/read-only and never call legacy status/audit/repair/install/state. |

## Acceptance and explicit non-goals

- `installer_workspace_contract.test.py`: exact named paths, explicit overrides,
  legacy conditional behavior, case/path conflicts and read-only helper selection.
- `installer_profile_contract.test.py`: actual precedence/clearing/profile transport.
- `installer_named_safety.test.py`: refusal and bounded mocked consumer error
  propagation in all layouts, including real cmd assignment prefixes cut off before
  any status probe, not real installation/status acceptance.
- `installer_consumer_agreement.test.py`: synthetic actual consumer seams cover
  selected state paths, repository audit/drift, unsupported repair planning and
  generated launcher bindings. Prior worker receipts are fixture evidence only.
- `installer_migration_preview.test.py`: nonempty flat/named/auto/org comparison,
  exact case preservation, per-repository old/new overrides, same destinations,
  case-only changes, supplied dirty/existing/collision evidence, duplicate output
  destinations and unresolved legacy active discovery. Pure calls are exercised
  with filesystem reads prohibited. Migration apply remains unsupported.
- Shared-API sentinel testing proves the real shell destination consumer invokes
  `resolve_paths`. Existing profile precedence and named safety suites remain
  passing; these are isolated fixture tests, never real-host installer sourcing.

Preview support is separate from migration/adoption apply support. Identity,
worktrees, dirty/untracked/ignored data, local commits, fork/ref provenance,
submodules/LFS and operation-appropriate recovery are not established by folder
names. A clean observation is not adoption approval. No moves, copies, merges,
renames, fetches, stashes, checkouts, ownership changes or profile/state writes are
performed. Known mismatches must stay visible and uncertain evidence must remain
unknown. Execution-time revalidation/recovery is an apply requirement, not a
capability claimed by this comparison API. Other workers own concrete action and
broader action-plan qualification; this matrix does not erase the legacy gaps above.

## Pure API and migration evidence schema

`resolve_paths(*, home, repo, slug='', path_override='', root='', layout='auto',
name='', configured_owner='', directory_entries=None, github_desktop=False)`
returns `root`, `group`, `destination`, `candidate_destination`, `status`, `reason`
and `filesystem_status`. It reads neither environment nor filesystem. Effective
CLI/profile/default values must already be selected by the caller. An explicit
repository override is independent of unrelated invalid/default roots. `named`
and `flat` destinations are lexical selections even when evidence is absent;
`filesystem_status` is not an absence or cleanliness assertion.

`directory_entries` maps absolute parent paths to complete immediate listings:
`[{"name": "Chosen", "kind": "directory"}]`; strings are shorthand directories.
Kinds are directory/file/symlink/other. Missing keys mean unknown, empty lists mean
supplied absence. At most 4096 parents, 4096 entries per listing and 16384 total
entries. Default root selection requires supplied home/Documents information or
explicit desktop availability; it never checks installed applications offline.

`build_migration_preview(old_config, new_config, target_home, repositories,
observed=None)` accepts each config's `workspace` fields, optional
`directory_entries` and `github_desktop`. Repository records have `name`, optional
`slug`, `path_override`, `old_path_override`, `new_path_override`, `active_path`,
and boolean `active_discovery_complete`. Per-side override keys take priority,
including explicit empty strings. Legacy discovery is unresolved unless a caller
supplies the active path or states the bounded discovery was complete with no
match (then the old destination is the fallback). Named active selection remains
authoritative, never adopted from unrelated discovery evidence.

`observed` maps absolute paths to caller evidence: `state` (missing, directory,
file, symlink, other, unknown), optional boolean/null `dirty` and `conflict`.
Every row reports old/new **resolved destinations**, separate resolution reasons
and candidate paths, active source selection, destination/active path changes,
and status: unknown, blocked, unchanged (path only), or review_required. Exact or
case-fold destination overlaps across requested repositories block all affected
rows. Case-only changes and supplied collisions/dirty work remain visible.
`review_required` is not migration eligibility or permission: `apply_supported`
is always false and no executable commands are emitted. Runtime, Sim artifact,
state/profile storage and other independent roots are not renamed by this API.

The original plan's sections 5.2–6, 8E and 9 were checked against these fixtures.
This completion is the resolver/consumer-wiring/migration-preview slice, not a
whole-plan completion claim. Parent integration owns the original plan register,
CLI migration entry and action preview integration; independent review is still
required before promoting broader consumer or application claims.

