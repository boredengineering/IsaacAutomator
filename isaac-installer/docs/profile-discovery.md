# Bounded profile discovery and safety

This workflow separates observation, reviewed desired YAML, consumer mapping and
action planning. It is not a complete machine-reproduction or runtime guarantee. Approval records intent;
it never grants permission to install. It does not start synchronization or change
VS Code settings. No component is inferred healthy from package/directory presence.

## Supported boundary

For algorithmic discovery outside the intentionally restricted devcontainer, see
[host metadata discovery](host-discovery.md). Its standalone host-side collector
has separate scope and safety properties. Bring back its private JSON report with
`import-host-report --report ... --output ...`; that importer uses the boundary
below and never treats embedded host paths as local read grants. Actual host
collection remains a separate user-run step, not an automatic action here.

- Linux x86_64, non-root, Landlock ABI >= 5 and seccomp are required. No extra
  sandbox package is installed automatically. Missing enforcement refuses work.
- The privilege policy requires matching nonzero real/effective/saved IDs and
  filesystem IDs and no retained capabilities. Ordinary nonzero supplementary
  groups are admitted without changing memberships; scoped filesystem and syscall
  enforcement still applies. Do not escalate with sudo to bypass a refusal.
  Actual-machine access remains separately authorized; tests use synthetic inputs.
- Early CLI dispatch avoids installer sources, logging/state initialization,
  module checks and optional streaming installation for `--dry-run` and supported
  observation commands. Unqualified legacy observation modes refuse instead of
  falling back to mutating checks.
- A trusted system Python runs in isolated mode. The observer imports neither
  robotics packages nor the selected environments. It executes no Git, shell,
  package-manager, network or container commands.
- Read access is limited to explicit inputs; network, execution, process creation
  and filesystem writes are denied by the kernel. Inherited descriptors are
  closed except stdout/stderr, which must be terminals or pipes, not regular files
  or sockets. CPU, memory and input-size limits bound work.
- Directory grants currently include descendant content at the kernel layer.
  The reviewed observer restricts itself to the declared metadata and never reads
  private checkout content, but confinement does not independently hide private
  files **inside** an admitted directory from compromised reader code. Select
  narrow roots; directory grants are not a fine-grained secret-isolation claim.
- Symlinks, ambiguous names and unsupported input are not silently adopted.
  Access-time effects of filesystem reads are outside the no-content-mutation
  claim. Report contents can include chosen paths and metadata: keep them private.
- Ordinary legacy installation remains unqualified for modifying a working
  developer machine. All named-layout legacy execution is deliberately blocked until
  ownership, recovery, stale-preview and concurrency safeguards are qualified.

## Observe only selected metadata

Run from `isaac-installer/`, as an unprivileged user. The following paths are
examples; replace them only with explicitly selected targets. These commands
are **not** permission to scan your workstation automatically.

```bash
./bin/isaac-installer observe \
  --workspace-root /approved/workspace-parent \
  --workspace-name BoredEngineer \
  --target local-workstation

./bin/isaac-installer observe \
  --dist-info /approved/environment/lib/python3.10/site-packages/custom_tool-1.0.dist-info/METADATA \
  --environment robotics-env --target local-workstation

./bin/isaac-installer observe \
  --conda-meta /approved/environment/conda-meta \
  --environment robotics-env --target local-workstation
```

`--dist-info` selects individual `METADATA` files, not a Python import or a whole
site-packages scan. `--conda-meta` selects a bounded directory of package records.
Repeat either option for additional sources; all sources in one invocation share
its explicit environment label. Use separate invocations for other environments.
Workspace observation examines bounded immediate directory entries only. It does
not read repository contents/remotes, run Git or inspect the entire home tree.

Exit 0 means the bounded report was produced, **not** that coverage is complete,
that the target conforms or that installation is safe. Examine coverage/unknowns.
Invalid input or missing confinement returns nonzero. Root is rejected before
reading input. The output is one JSON bundle containing three separate documents:

1. `baseline`: observations, source evidence, bounds and limitations.
2. `candidate`: proposals and reviewed decisions; always `apply_supported: false`.
3. `review`: unresolved required intent, comparisons and customization backlog;
   `apply_supported: false` and `executable_export_supported: false`.

These are deliberately not executable workstation-profile YAML. Unknown optional
customizations remain a backlog; required unknowns/unsupported mappings remain
visible. Accepting a package does not invent an installer or Ansible consumer.
Tools detected through package metadata have unknown purpose until reviewed.

For an observed `tool:` candidate, an explicit review edit may set `location: null`
to use the selected consumer environment rather than pinning the observation
metadata path as an installation location. The baseline, suggested location and
original writer-exclusion roots remain unchanged. This is desired intent, not an
observation or permission to install. Supported exact PyPI pins for the selected
Lab environment can then map to both local and Ansible package fields; other
custom tools remain explicitly unsupported rather than silently installed.

Explicit `--metadata-source` JSON objects extend this workflow with selected
environment/tool metadata, including placement and purpose. For example:

```bash
./bin/isaac-installer observe --metadata-source '{"id":"robot-tools","path":"/approved/metadata/tools.json","format":"environment-json","environment":"robot-project","placement":"container"}'
```

An `environment-json` input is a selected sanitized description, not an environment
dump. Its fields are `name`, `manager`, `python`, `tools`, `notes`; each tool has
`name`, `version`, `source`, `purpose` (unknown values use `null`). Reader support
and parsing failures remain explicit in the baseline. No imports, activation or
package-manager execution follow from this metadata.
The admitted JSON basenames are `environment.json` and `tools.json`. Optional
`runtime` association in the selection proposes a runtime choice; it does not
enable that component or approve placement. `--max-entries`, `--max-bytes` and
`--max-seconds` select bounded collection budgets; exceeded coverage remains
explicit. Discovery JSON encoding and rereading share an 8 MiB cap. Desired YAML
retains its separate 128 KiB schema limit; reduce or review a smaller selection
instead of assuming every observed package belongs in executable intent.

`--git-source` accepts an explicit JSON object containing `id`, `root`, `git_dir`,
`common_dir`, and `ref_paths`. Only individually selected Git metadata files are
admitted, including separately specified worktree/common-directory indirections;
the CLI does not grant checkout-wide or `.git`-wide file reads for this reader.
It never runs Git, follows config includes, reads private diffs or claims that HEAD
reproduces dirty/untracked work. Absent or refused metadata remains unknown.

## Persist only to an explicitly selected new report file

```bash
./bin/isaac-installer observe \
  --workspace-root /approved/observations/workspace \
  --workspace-name BoredEngineer \
  --output /approved/reports/observation.json
```

`--output` runs the read-only producer first and a separate confined writer only
after a bounded valid report is available. It requires a new absolute destination
with an existing parent outside selected/observed input roots. It never creates
parents or overwrites a file. Output is mode 0600; collisions, linked/unsafe paths
and unsupported mount boundaries refuse. The writer can write its approved file
descriptor and receipt pipes, not arbitrary paths, network or executable helpers.
It does not widen the observer's read-only confinement.

Stdout carries a receipt, not the file contents. A producer's incomplete but valid
draft can be saved with exit 2 and `status: written`; this is not profile or runtime
completion. Postcreation write failure/interruption may leave the owned partial
file. Receipts identify that condition; forced process death can leave a
`possibly_partial` outcome. There is no automatic overwrite, cleanup or resume.

The original stdout-only form remains available. To persist it with an external
writer instead, deliberately choose a new destination. With Bash:

```bash
set -o pipefail
./bin/isaac-installer observe \
  --workspace-root /approved/workspace-parent --workspace-name BoredEngineer \
  | (umask 077; set -C; cat > /approved/reports/discovery.json)
```

The writer refuses to overwrite an existing file. A failed command can leave an
empty/partial report; preserve its nonzero status and do not treat that file as a
successful baseline. Do not overwrite an earlier report during a rescan.

## Review intent, then rescan

Create a JSON decisions file. Field IDs are taken from `candidate.fields`; for
example, an explicit workspace name review:

```json
[
  {"field_id": "workspace:workspace.name", "decision": "edit", "value": "BoredEngineer"},
  {"field_id": "workspace:workspace.root", "decision": "accept"}
]
```

```bash
./bin/isaac-installer review-profile \
  --report /approved/reports/discovery.json \
  --decisions /approved/reports/decisions.json
```

Supported decisions: `accept`, `edit`, `reject`, `defer`; optional `reason` and
`required` record bounded review context. Unknown values require an explicit edit,
not blind acceptance. Save the returned bundle to a **new** selected destination.
Rescan the same bounded inputs with `--previous-report` pointing at that reviewed
bundle. Decisions survive rescans, including reordering package source flags;
changed or no-longer-selected evidence is marked rather than silently resetting
intent. JSON shape/revision validation prevents malformed reports from becoming
approved executable intent; these hashes are integrity checks, not signatures.

## Explicit intent when observation cannot supply an answer

`observe --empty` starts a review document with no target observations and no
filesystem content grants. It is optional: it does not replace the normal
observation/proposal workflow or require a complete profile up front. A missing
source/runtime/execution field can be filled deliberately:

```bash
./bin/isaac-installer review-profile \
  --report /approved/reports/observation.json \
  --field-id component:sim.source --decision declare \
  --value-json '{"mode":"standalone","version":"6.0.1","sha256":null}' \
  --output /approved/reports/new-review.json
```

`declare` applies only to missing supported component-source/runtime/execution
fields. Existing fields still use accept/edit/reject/defer. Declaration records
`user_declared_intent` and empty observed evidence; a rescan never relabels it as a
verified installation. Component selection, missing runtime and native execution
intent still need their own explicit choices. An unspecified checksum, source URL
or runtime pin is not fabricated or considered verified. A bounded `--decisions`
JSON file remains available for multiple choices, including declarations.

## Export reviewed desired YAML and inspect its consumers

```bash
./bin/isaac-installer export-profile \
  --report /approved/reports/reviewed.json --name robotics --format json

./bin/isaac-installer export-profile \
  --report /approved/reports/reviewed.json --name robotics --format yaml
```

The JSON form contains `profile`, `review` and `complete`. The YAML form emits the
existing `workstation-profile` / `v1alpha1` schema, not a third installer format.
Self-contained discovery drafts use `defaults: false`, so unreviewed preset
components are not silently enabled. `draft: true` records incomplete required
intent. Reviewed required declarations unsupported by a generic exporter can also
have `complete: false` while `draft: false`: each real adapter determines whether it
can consume them. Exit 2 can therefore accompany useful output; it is not a
completed application profile. Keep the companion review alongside the YAML.
Append `--output /approved/reports/new-desired.yaml` to use the separate confined
writer, or omit it for stdout. Profile completeness is not runtime readiness or
execution approval.

Inspect actual local and Ansible mappings with an explicit target home:

```bash
./bin/isaac-installer render-profile \
  --desired-profile /approved/reports/desired.yaml \
  --target-home /home/robot --adapter local

./bin/isaac-installer render-profile \
  --desired-profile /approved/reports/desired.yaml \
  --target-home /home/robot --adapter ansible
```

Reports contain the adapter artifact, field coverage and blockers. Unsupported
required source/runtime/custom-tool mappings are not silently discarded. The
controller's home is never substituted for the supplied target home. Rendering
does not run installer functions or Ansible.

## Concrete planning and read-only diagnostics

```bash
./bin/isaac-installer install --dry-run \
  --desired-profile /approved/reports/desired.yaml \
  --target-home /home/robot --json
```

`plan-profile`, `status` and `audit` with the same `--desired-profile` and
`--target-home` use the same concrete planner. These diagnostics describe selected
intent, not live runtime health. Actions carry targets, reasons, effects,
preconditions and execution-support limits. Without admitted target evidence,
existence/conflicts remain unknown. Optional `--evidence` selects a bounded JSON
path-evidence mapping, explicitly labelled supplied/unverified; it is not authority
to mutate. No plan command installs, repairs or resumes anything. Exit 0 means the
reported plan has no unknown/blocked actions; exit 2 means incomplete or refused.

These shared-profile commands are separate from the legacy profile-only stage
preview below. They do not turn legacy installation into a qualified executor.

When the operator separately authorizes observations on the actual target machine,
`observe-targets --desired-profile ... --target-home ...` collects metadata for
explicit planned paths only. Unlike planning/status above, this **does inspect
filesystem metadata on the machine running the command**. It does not enumerate
directories, read target contents, hash files, run Git or infer installer ownership
from user ownership. Symlink/mount/permission uncertainty remains unsupported or
unknown; all records have `managed: false`. Its plain JSON mapping can be supplied
back through `plan-profile --evidence ...` without inventing target records.
Metadata is point-in-time and racy, not a clean-install or recovery certificate.
No such command has been run on a real workstation by the implementation tests.

## Migration comparison without checkout changes

```bash
./bin/isaac-installer migration-profile \
  --old-profile /approved/reports/old.yaml \
  --desired-profile /approved/reports/desired.yaml \
  --repositories /approved/reports/repositories.json \
  --target-home /home/robot \
  --output /approved/reports/new-migration-preview.json
```

The repository input is a bounded JSON list, for example
`[{"name":"IsaacLab","slug":"isaac-sim/IsaacLab"}]`. Explicit per-repository
old/new path overrides and supplied active-path evidence are supported by the
comparison API. Both the shell repository resolver and this preview use the same
pure path contract. Legacy active-checkout selection remains unknown without
supplied evidence; matching destination paths alone do not prove cleanliness.
Case-only changes, destination collisions and dirty evidence require review.
`apply_supported: false` is unconditional: no rename, checkout, adoption, update or
copy follows, even when command exit 0 reports a valid comparison.

## Workspace naming and preview

```yaml
workspace:
  root: "~/Documents/GitHub"
  layout: "named"
  name: "BoredEngineer"
  auto_register_github_desktop: false
  auto_create_fork: false
```

This means `root/name/repository`. Exact spelling is preserved; a conflicting
case-insensitive match requires an explicit user decision. `boredengineering`
is not an alias for `BoredEngineer`. `flat` means `root/repository` and forbids a
nonempty `name`. The initial name grammar starts with an ASCII letter/digit and
permits ASCII letters/digits, internal spaces, `.`, `_`, `-`; Unicode name support
is not implemented. Legacy `auto`/`org` profiles retain legacy selection rules, not a
new safety guarantee. Resolution never creates/chowns directories. Existing
checkouts are not adopted by selecting their parent.

Explicit `--workspace-root` (alias `--workspace-dir`), `--workspace-layout` and
`--workspace-name` override the profile; omitted flags preserve profile/default
provenance. Do not set inherited `CLI_WORKSPACE_*` variables to fake CLI choices.

```bash
./bin/isaac-installer install --dry-run --profile minimal --json
```

This is **profile-only**, deliberately incomplete (exit 2), and reports stage
selection rather than actual host health, concrete overwrite effects or a safe
installation transaction. Unsupported fields must not silently imply parity.
No successful first run/unchanged rerun/failure recovery has been qualified for
real installation; YAML alone is not idempotence.

## Cloud fork selection: separate narrow implementation

Deployment commands accept explicit `--isaacsim-repo`,
`--isaaclab-repo`, and `--isaaclab-arena-repo` public HTTPS URLs.
The corresponding branch/tag revision is checked against that selected repository, and the
same repository/ref pair reaches the existing Ansible role variables. Defaults
remain the official repositories. Full commit SHAs retain the existing syntax-only
acceptance behavior; their reachability in the selected repository is not verified.
The existing explicit-ref network-error policy can warn and continue; a transport
error is not proof that a remote revision exists.
Source URLs are not Terraform variables. Custom repositories on golden-image
build paths are refused because those adapters do not transport the override.

This does not copy local changes, select a private authentication scheme, validate
all cross-project API compatibility, reproduce standalone Sim, or establish G4
GPU readiness. Repository URLs must contain no credentials. Offline transport
verification is not a paid cloud deployment acceptance test.

## Reproducible offline tests

From the repository root, using the project's Python dependencies:

```bash
/usr/bin/python3 -B src/tests/run_profile_workflow_tests.py
```

The explicit offline runner prints each suite's exit/count/skip result and saves
per-suite logs plus `results.json` in a new temporary report directory. Optional
positional suite names select narrower runs; these do not establish whole-plan
coverage. The runner is not the repository's full GPU/live-deployment acceptance.

Tests use disposable synthetic fixtures. Privileged test runners drop to an
unprivileged identity for confinement tests; the installer itself rejects root.
Running these tests does not authorize real-machine discovery/install/cloud work.
See the [implementation plan](../../.agents/references/isaac-installer/workspace-repository-management-plan.md)
for remaining acceptance gates, including selected-file rsync/continuous-sync
ownership, recovery and local/cloud devcontainer consistency.
