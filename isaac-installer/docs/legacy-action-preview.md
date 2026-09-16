# Legacy dry-run action intent (C04)

`install --dry-run --config PATH` and admitted `--profile` presets retain the
original `stages`, `workspace_intent`, selection count, exit code **2**, and
`execution_authorized: false`. JSON now adds `legacy_action_plan`; text output
prints its subactions as escaped JSON records after the existing stage summary.
No receipt is an executable plan or a physical-run approval.

```sh
# Unprivileged, with a private, data-only legacy YAML profile:
isaac-installer/bin/isaac-installer install --dry-run --config ./private-profile.yaml --json
isaac-installer/bin/isaac-installer install --dry-run --profile minimal --json
```

## What the additional records mean

Each action has `id`, `stage`, `selected`, `status`, `operation`, `target`,
`desired`, potential `effects`/`overwrite_effects`, `approval_required`, and
`blockers`. Every native action has `execution_supported: false` and
`execution_authorized: false`. Selected actions remain **unknown**, not
`would_change`, because no stage checks or target observations run. Excluded
stages retain their concrete potential subactions with `status: excluded`.
`--without` still wins over `--only`; `--only` still wins over profile stage
selection. Optional subaction toggles retain their own native semantics.

* Workspace/repository destinations reuse **`workspace_paths.resolve_paths`**
  with no directory evidence. Explicit flat/named roots produce pure intended
  destinations. Auto/org owner spelling and absent-root discovery stay unknown,
  with candidate paths where available; candidates are not observed targets.
* The legacy CLI has no admitted target-home option and does not resolve an
  account. **`/target-home` is symbolic**, not `$HOME`, root's home, or a detected
  installation. Explicit absolute profile paths remain declared values, not
  filesystem observations. The pure planner API can bind a caller-supplied home.
* Repo records include the actual `config.sh` defaults/aliases, requested repo,
  normalized requested URL, upstream, branch/tag/ref and recursive intent used
  by native Lab/Arena/LeRobot/GR00T checkout consumers. Tags/branches are not
  verified commits. Native fork fallback may change the eventual clone URL.
  Fork creation and Desktop registration have separate records/toggles.
* Sim records include explicit/fallback prefix intent, version, archive URL,
  checksum when supplied, cache name, EULA marker and post-install script target.
  Existing Sim discovery is not replaced by a guessed installed path. Lab's
  `_isaac_sim` source is separately reported because native Lab uses
  `ISAACSIM_DIR` or `~/IsaacSim`, not the Sim discovery function.
* Lab runtime pins and the native Python default are reported by branch.
  Pin-aware creation needs an explicit Python pin; no default is substituted.
  Conda prefixes stay null with an environment identity/prefix expression and a
  clearly labeled fresh-install candidate. GR00T's `.venv` is derived from its
  repo destination; lockfile/GPU versions remain unresolved. Native LeRobot
  fixes its named runtime to Python 3.10 and does not consume arbitrary
  `runtimes.lerobot` values.
* Config targets include scoped activation/deactivation hook suffixes, Arena
  `.env`, Lab's Sim link, user workspace scaffolds, desktop/script directories,
  and known system configuration paths. Potential destructive native effects
  (recursive ownership changes, legacy Conda cleanup, file replacement, global
  settings) are explicitly **unqualified**, never new-only guarantees.
* Tools, drivers, display, udev/groups, codec dependencies, system shims and
  streaming intent are included. Platform-dependent package lists and versions
  are null, not guessed from the development machine.
* `streaming.provider` is recorded as requested intent but the effective legacy
  install provider is **none**: native dispatch does not consume that profile
  key, and the existing safe CLI refuses `--stream`. Streaming is not silently
  enabled or treated as an install stage.

`unmapped_fields` lists flattened keys that have no action/selection mapping;
profile declarations are not silently promoted to native-consumer support.
For example repository `path` and arbitrary runtime placement fields are not
mapped by the legacy `config.sh` path. The old `unsupported_field_count` remains
the original **non-selection** count for compatibility, not the new coverage
count. The records are a review inventory of known effects, not exhaustive
expansion of remote scripts, package hooks or host-dependent branches.

The generic `action_plan.py` describes separate managed/new-only policies. Those
policies do **not** match native cleanup/chown/update effects and are not reused
as promises here. Only the matching pure workspace resolver is shared; neither
`action_plan.py`, `managed_apply.py` nor fixture builders are modified or invoked
by this work.

## Boundaries and remaining blockers

The trusted planner is preloaded alongside the parser, **after** the existing
stdio/root/argument guards and **before** confinement. Only the declared profile
is read after confinement. No shell helpers are sourced, target files opened,
existing trees inspected, commands launched or network/GPU calls made by the
planner. Confinement, unsafe-option refusal and executable-field refusal are
unchanged. Old stage-only fixture/distribution copies lacking the new module
retain an explicitly labeled incomplete fallback (`action_plan_status:
unavailable`). A broken/import-denied dependency does not authorize execution.

**The shipped default/full presets currently contain `custom_build.build_command`
even though custom builds are disabled.** The pre-existing executable-field
barrier therefore still refuses them (exit 2, no JSON plan). Tests exercise
preset routing with private data-only copies and separately verify refusal of
unaltered copies. This is a remaining public-preset C04 blocker, not a claim of
successful full-preset coverage. Removing inert executable declarations from
those public presets needs a separate owner change; do not weaken the guard.

Other remaining native gaps include the packages-only Lab branch mismatch
(Python provisioning does not select the pin-aware branch, while Lab/Arena do),
Conda/Sim discovery, immutable source identities, remote fork/auth behavior,
archive extraction safety, arbitrary source/package scripts, environment
adoption/updates, EULA consent, machine-wide changes, service state and GPU
compatibility. Named application remains explicitly denied. No managed executor
qualification or expansion is part of this change.

## Evidence

`src/tests/installer_legacy_actions.test.py` uses private fixture inputs and
controlled native value/argv seams: real flattened config assignments,
repository checkout arguments, native workspace-resolver arguments passed into
the shared pure API, Sim/runtime mapping, native Python-version logic, and the
native scaffold array. No actual installer consumer body is executed. Tests
also cover text/JSON receipts, stage/subaction exclusion, profile aliases,
mutability snapshots, import/guard order and no-I/O planner calls. Existing
`installer_safe_preview.test.py` covers the retained guard/stdio/confinement and
stage-selection contracts. Neither suite is installation qualification.
