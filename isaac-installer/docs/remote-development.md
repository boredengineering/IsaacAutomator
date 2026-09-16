# Offline selected synchronization and remote development

The **CLI plans and renders candidates only**. It does not activate sync,
start services, discover cloud state, connect over SSH, rebuild containers, install
dependencies, or change the current `.devcontainer` / VS Code configuration.
A separate explicitly activated Python supervisor API is described below; it is
not connected to a CLI activation command. Its tests use synthetic loopback
engines, not a live native installation.
The historical `./sync watch` and `./dev code` examples are aspirational, not
commands supplied by this module. No continuous engine has been chosen for you.

## Review an explicit selection

The parent-owned `./remote-development` wrapper exposes the group. The module is
also directly runnable from the repository with the existing Python environment:

```sh
python3 -m src.python.remote_development_command plan --spec /absolute/selection.json
python3 -m src.python.remote_development_command render \
  --spec /absolute/selection.json --output-dir /absolute/new-candidate --reviewed
```

`plan` only reads the selected regular JSON file (maximum 1 MiB), validates
lexical path/endpoint strings, and prints JSON. It does not stat mapping, protected,
identity or trust paths, or inspect their contents. Its receipt marks target
observation as absent and preflight as required. `render`
creates only the explicit **new** output directory; its parent must exist.
Existing directories, symlinked path components, settings folders and output
folders overlapping synchronized folders are refused. Files are created
exclusively, with private permissions. Partial failed renders are retained for
inspection, never recursively removed or silently reused. `--reviewed` approves
candidate output only; it is not an installation or activation approval.

Example selection (replace every path and the image with reviewed values):

```json
{
  "engine": "rsync",
  "image": "example.invalid/robotics:reviewed-version",
  "initial_seed": "empty-target",
  "conflict_policy": "stop",
  "delete": false,
  "mappings": [
    {
      "name": "robot",
      "kind": "source",
      "local": "/home/developer/projects/robot",
      "remote": "/home/remote/workspaces/robot",
      "container": "/workspaces/robot"
    },
    {
      "name": "training-config",
      "kind": "config",
      "local": "/home/developer/selected-config/training",
      "remote": "/home/remote/selected-config/training",
      "container": "/configuration/training"
    },
    {
      "name": "results",
      "kind": "artifacts",
      "local": "/home/developer/retrieved/robot-results",
      "remote": "/home/remote/outputs/robot-results",
      "container": "/outputs/robot-results"
    }
  ]
}
```

`engine` must explicitly be `rsync`, `mutagen`, or `syncthing`; there is no auto
selection. Mappings preserve their input order. Names must be unique, and paths
must be absolute, narrow, literal selections without traversal, unsafe mount
syntax. Filesystem existence/type/symlink checks belong to execution preflight,
not planning. Case-insensitive/nested overlaps within
local, remote, or container namespaces are rejected. Source/config and retrieved
artifacts cannot share or nest their roots. With no `endpoint`, the remote paths
are interpreted as local endpoints for offline qualification, not a cloud target.

To render SSH/IAP argv without connecting, add an `endpoint` dictionary using the
existing `file_transfer.TransferEndpoint` fields: `host`, `user`, `identity_file`,
`known_hosts_file`, and optionally `iap`, `instance`, `project`, `zone`. Select the
actual preauthorized OS Login user/identity yourself. This command does not run
Terraform or gcloud to discover them, and never reads private-key contents.
Generated rsync previews reuse the shared SSH/IAP builder (including host-key
checking); they do not create the known-hosts file. The actual transfer helper's
first-use `accept-new` trust policy still requires separate security review.

## Direction, ownership and protection

| Kind | Direction | Canonical owner | Container mount |
|---|---|---|---|
| `source` | local → remote host | local developer | read-only |
| `config` | local → remote host | local developer | read-only |
| `artifacts` | remote host → separate local output | remote runtime | read-write |

### Shared desired profile and editable build placement

Both CLI commands accept `--desired-profile /absolute/desired.yaml`. This reads
only that explicitly selected regular shared `workstation-profile` YAML/JSON file
(no-follow at every ancestor; shared parser limit 128 KiB). Alternatively embed
the shared document in the selection as `desired_profile`. Selecting it both ways
is refused. Resolve inheritance beforehand; no preset or target discovery occurs.

Add explicit runtime placement to the synchronization selection, for example:

```json
"runtime_placements": {
  "gr00t": {
    "environment": "/opt/envs/training",
    "builds": [{
      "component": "gr00t",
      "source_mapping": "robot",
      "remote": "/home/remote/build/robot",
      "container": "/build/robot"
    }]
  }
}
```

`build_plan` emits `runtime_manifest`, and rendering exclusively creates
`runtime-placement.json` beside the candidate devcontainer. The manifest preserves
the shared selected component source dictionary verbatim (repository, ref,
revision or archive version/checksum), runtime identity/manager and exact selected
Python/Torch/CUDA/version values, plus original environment declarations. Nothing
is upgraded, fetched or inferred. Null and absent version intent is not a pin.
Each build entry links an explicit source mapping to a separate writable remote
and container location; the source remains read-only. Valid build locations become
additional candidate devcontainer bind mounts. The explicit environment path is
container-local placement intent, **not a host environment bind mount**, installer,
interpreter selection or environment already created in the image.

Build/environment overlap with source/artifact mounts, another writable runtime
location, credential/state/recovery roots or selected protected paths is reported
in `issues`. Candidate output may not overlap selected build outputs. Mandatory
mapping exclusions are included in the manifest; separate build output folders
are not synchronization mappings. Missing runtime/source/build/environment intent,
unbound or disagreeing environment declarations, draft state, and unsupported
shared workspace/repository/custom/serving/note consumers are visible. Unknown
top-level embedded profile fields are reported by name with their values omitted;
malformed/unknown nested schema or placement keys are refused by validation rather
than silently consumed. Shared YAML input uses the shared strict schema parser.
When any issue exists, `placement_complete` is false and **all additional writable
build mounts are omitted**, while the review manifest remains available.

This implements **manifest and candidate-mount generation, not runtime parity**.
There are no editable-install commands or lifecycle hooks. A build backend that
requires in-source writes cannot use these read-only source mounts unchanged;
its out-of-tree editable-install support must be qualified separately. Runtime
image contents, permissions, dependency compatibility, environment creation and
reproducibility remain unverified even if `placement_complete` is true.

The container's writable environment and the host's installed environment are not
source checkouts. Do not synchronize live environments, OCI writable layers or
host configuration to imitate runtime parity. Runtime writes belong in explicit
output mounts, not in source mounts. A desired-profile decision does not approve
sync, and synchronizing a profile does not approve installation.

Mandatory exclusions extend the existing transfer policy: Git metadata (including
worktree `.git` files), Terraform state, credential stores, `.env`, key files,
virtual environments, caches, database files/volumes, current editor/devcontainer
settings, recovery copies and backups. Model/checkpoint/dataset exclusions are
removed **only** for explicit `artifacts` mappings; credential, state, environment,
settings and live-database exclusions remain mandatory. No arbitrary exclusion
removal is accepted. An artifact folder is not permission to copy a live database;
use an independently reviewed application-consistent export instead.

For active profiles or recovery stores with arbitrary names, explicitly select
`protected_paths` (maximum 1000 entries), for example:

```json
"protected_paths": [
  {"namespace": "local", "path": "/home/developer/projects/robot/active-profile.toml"},
  {"namespace": "remote", "path": "/home/remote/workspaces/robot/rescue-2026"}
]
```

Namespaces are `local`, `remote`, or `container`. Protection is lexical: selecting
a mapping at or below a protected root is refused; a protected file/directory
inside a mapping becomes a root-anchored exclusion on **both** transfer sides.
Without an SSH endpoint, local and remote paths share one filesystem namespace.
Candidate output cannot overlap local protection (or local-mode remote protection).
Paths outside mappings remain recorded without inspection. Omitted selections
are not discovered automatically. These exclusions do not hide files from bind
mounts, sandbox a writable artifact mount, or protect against other writers.
Continuous-engine ignore semantics remain native-unvalidated; do not activate a
candidate on the strength of these rsync qualification tests.

These are filename policies, **not a secret scanner**. A credential saved under an
ordinary unrecognized filename is not detected. Review narrowly selected source
contents separately before live use. Plans expose selected paths and identity-file
references, not credential bytes. Excluded destination files are protected from
rsync deletion as well as transfer.

Every rsync argv is deterministic and includes `--dry-run`. This is an argv
preview, **not a remote filesystem dry-run that has already happened**. Reusing
`file_transfer.transfer_directory()` for rendering would itself write SSH trust
metadata, so a read-only renderer mirrors its argv contract and tests parity with
the existing helper. Actual disposable-local transfers delegate to that helper
with explicit `isolated_local=True, checksum=True` options; the preview retains
the default shared-helper argv contract and does not represent an executed seed.
No replacement remote transfer engine is implemented here.

Deletion defaults off. `delete: true` additionally requires the separate boolean
`delete_approved: true`. A seed defaults to `empty-target`: the local qualification
adapter accepts an empty target or unchanged already-seeded files; unknown target
files and differing incoming files stop. Explicit reviewed adoption/overwrite
requires **both** `initial_seed: "reviewed-overwrite"` and
`overwrite_approved: true`. Overwrite approval does not approve deletion.
File/directory replacements and symlink/hardlink/device inputs are refused by the
qualification adapter. No automatic bidirectional merge is attempted. Direct
shared-helper callers retain size/mtime comparison by default. The qualification
adapter uses `--checksum` to repair even equal-size/equal-mtime differences and
snapshots SHA-256 manifests before launching rsync. After all mappings finish,
it compares source and destination regular-file bytes against those pre-launch
manifests, including expected retained/deleted files, preservation of excluded
destination bytes, and absence of newly leaked excluded files. This reads protected
bytes only inside the newly allocated synthetic fixture. A zero process
exit is not enough; changed sources or mismatched results fail without a verified
receipt. The receipt's verification scope is regular-file bytes, not empty-directory
layout, metadata parity, crash durability or an adversarial concurrent filesystem.

## Candidate files and continuous engines

All selections render `devcontainer.json` and `review.json`. The devcontainer uses
only the explicitly selected image and explicit remote-host bind mounts. It has
no lifecycle hooks, `pip install -e`, extension installation, GPU/display/network
flags, inherited editor customizations, or inferred runtime user. Source/config
mounts are read-only. Nothing copies the result into an active `.devcontainer`.
Image contents, UID/GID permissions, GPU/display access, host path ownership,
Python dependencies and runtime parity remain unverified.

An explicit `mutagen` selection also renders `mutagen.candidate.yml` (JSON syntax,
valid YAML) with one-way-safe sessions, local ownership, mandatory ignores and
ignored symlinks. It contains no project hooks. **Mutagen does not automatically
consume the rsync SSH argv**: a dedicated reviewed SSH transport matching the
shared SSH/IAP preview is still required. Ambient SSH configuration has not been
qualified. No Mutagen backup/versioning claim is made.

An explicit `syncthing` selection also renders paused local/remote XML folder
candidates plus per-mapping `.stignore.candidate` files. Local source/config folders
are send-only; remote counterparts receive-only. Artifact directions are reversed.
Device IDs, addresses, trust and pairing are deliberately absent: these are
**folder configuration candidates, not deployment-ready paired configurations**.
Both endpoints need reviewed ignore files installed before unpausing. Syncthing
uses its own transport, not the SSH/IAP mechanism. Staggered versioning is rendered
as a candidate, but recovery has not been tested with a live engine.

Both continuous candidates propagate deletions inherently. `delete: false` applies
to rsync, **not a promise that continuous engines suppress deletion**. They stay
non-activatable until deletion, versioning/recovery, transport, seed and writer
ownership are separately reviewed and tested. Conflict files are not backups.
Neither executable is installed, invoked, or native-schema-validated here.
JSON/XML parsing tests establish candidate syntax only, not native engine validity.
The fix environment has no Mutagen, Syncthing or Go; native parser/source validation
was unavailable and no tool installation was attempted.

## Lifecycle code and offline evidence

`Lifecycle(spec).transition(...)` implements non-executing orchestration:

1. `seed-start` reserves the modeled rsync writer.
2. `seed-complete` requires verified postconditions and leaves the engine paused.
3. `resume` requires a chosen continuous engine, verified preflight, separate
   deletion approval and verified recovery.
4. `pause` requires confirmation the writer stopped before releasing ownership.
5. `conflict`/`failure` block progress; `stop` cannot automatically resume.

Receipts always say `executed: false`, `model_only: true`,
`supervisor_implemented: false`, `process_status: "not-observed"` and
`activation_allowed: false`, including when the **modeled** state is `continuous`.
`modeled_writer` describes intent, not a live writer. New instances require a
fresh seed. The state machine is not a process supervisor and does not prove
daemon status. No offline model transition authorizes launching an engine.
The separate concrete supervisor below replaces the former model-only backlog
for its expressly limited adapter scope; it does not change these model receipts.

### Explicitly activated Syncthing supervisor API

`src.python.sync_supervisor` implements actual REST operations, not fabricated
lifecycle receipts. **No CLI command can activate it.** Constructors and digest
calculation are pure. Every public observing/executing API requires a separate
literal `activation=True`; readiness flags alone never connect to an engine.

Supported interfaces:

- `SyncthingREST(local_url=..., remote_url=..., local_device=..., remote_device=...,
  local_api_key=..., remote_api_key=..., timeout=3)` explicitly selects both
  engines. Only distinct numeric `http://127.0.0.1:PORT` endpoints are supported.
  No DNS, redirects, proxies, inherited environment, shell or engine subprocess
  is used. Keys are caller-provided in memory and excluded from receipts/digests.
- `Supervisor(spec, backend=adapter, lock_directory=...)` requires
  `engine: syncthing`, no SSH endpoint, and both mapping paths accessible on the
  same host. `plan_digest` binds the complete selection, normalized plan, adapter
  endpoints/device IDs and lock scope. The directory must already exist for
  activation; its lock cannot be inside mappings, settings or selected protection.
- `acquire(readiness=..., recover=False, activation=False)` requires exactly
  `plan_digest` and true booleans `transport_reviewed`, `recovery_verified`,
  `deletion_approved`, `paths_reviewed`; the selected spec must also approve
  continuous deletion. These are explicit caller review attestations, **not a
  cryptographic proof of backup or transport qualification**. It acquires a
  nonblocking, no-follow host control `flock` plus directory-inode dataset locks, verifies native paused folders and their
  identities, paths, one-way roles, selected peer connectivity, receiver staggered
  versioning, exact ignore lines and native health. It then independently compares
  SHA-256 regular-file manifests across both local roots. Initially mismatched
  roots must be seeded by a separately qualified writer before acquisition.
- `resume(activation=False)` rechecks the stopped native state, process generation
  and the saved seed bytes before any unpause. Every selected root and ancestor
  must still have the pinned device/inode identity and be readable; an observable
  missing/replaced root blocks and attempts pause, including same-byte replacement. It PATCHes only the selected folder
  `paused` fields and verifies native runner state afterward. Partial failure
  attempts to pause every still-owned reachable folder; it never treats HTTP 200
  or a CLI exit as successful state verification.
- `poll(activation=False)` performs real health observations and checks conflict
  filenames and pinned root identity/existence/readability before and after native
  observations, native receive-only changes, pull errors, peer/config drift and
  daemon `startTime`. Conflict or failure blocks the session and attempts a safe
  pause. Unreachable or unverified writers become `stop-unverified`, not stopped.
- `pause(activation=False)` retains writer ownership. `stop(activation=False)`
  releases it only after verifying selected folders have no native runner.
  Reassigned folders are never mutated merely because their old ID was owned.
- `reseed(readiness=..., fixture=None, activation=False)` requires a new explicit
  review and verifiably paused healthy folders. By default it verifies newly
  supplied equal local byte trees. With a `local_fixture()` capability whose root
  exactly equals the held lock scope, it additionally executes the existing
  fixed-system-rsync, checksum/SHA-256-verified disposable reseed under that lock.
  It accepts no arbitrary seed command/callback and offers no real-root transfer.
  Reseed never silently adopts replaced roots: restore the pinned roots, or verify
  stop and create a newly reviewed session for the replacement paths.
- `run(readiness=..., stop_event=threading.Event(), poll_interval=1,
  activation=False)` provides a blocking supervision loop and cleanup in `finally`.
  The caller owns its thread and sets the event to stop. Use one control thread;
  concurrent calls on the same supervisor are unsupported. The return separates
  the loop `outcome` from the `cleanup` receipt.
- `close(activation=False)` attempts owned-folder cleanup without deleting folder
  configuration or stopping an unowned daemon. If verification fails it closes
  the legacy control descriptor (`writer_owned=false`) but **retains the dataset
  directory descriptors** in process-local cleanup escrow (`dataset_lock_held=true`)
  and leaves the dirty guard in `.writer.lock`. Different control directories cannot
  bypass those retained inode locks while this process lives. Explicit same-scope
  `recover=True` with the exact prior digest, pinned roots, fresh native paused
  verification and a fresh seed can reclaim the escrowed locks. Another process
  cannot reclaim live descriptor locks. Never delete the stable guard inode to bypass recovery.

The supervisor owns a **folder session**, not an engine process. It does not
launch, install, globally shut down, delete configurations, pair devices, edit
ignore files, change native options, or automatically restart a daemon. Both
preconfigured endpoints and their approved recovery policy must already exist.
`DatasetLock` combines **all selected root and ancestor device/inode identities**
into one sorted, deduplicated nonblocking `flock` set: exclusive on selected roots,
shared on their ancestors (exclusive wins when both apply). Identical or nested
selections therefore conflict even with different control directories; disjoint
sibling datasets can coexist. Directory descriptors pin the observed roots; no
source marker or global permission/registry directory is created. The local rsync
fixture writer uses the same API with its fixture root exclusively locked, also
covering destinations it has not yet created. Supervisor fixture reseeding reuses
its held dataset lock rather than reacquiring conflicting descriptors.

The separate API-only `SelectedTransfer.seed` also uses this shared lock for all
**physically local** selected roots, before its first manifest subprocess and
through final verification. For `endpoint=None`, both mapping sides are local;
for SSH/IAP only each mapping's `local` side is locked. Foreign `remote` paths are
never opened on this host merely to obtain a lock. `local_dataset_exclusion=true`
records cooperating local exclusion **during that completed seed**, not a retained
lease; the descriptors release on return. `local_root_identity_evidence` records
checked local pins. `exclusive_writer_reviewed` remains the caller's attestation,
not global writer proof; SSH/IAP `remote_writer_exclusion='unverified'` and
`distributed_lock=false` remain explicit. No remote controller lease was added.

Receipts distinguish the **historical SHA-256 seed snapshot**
(`seed_verification_scope`, `historical_seed_verified`) from current root evidence
(`current_root_verification`, `root_identity_evidence` at the last check). Ordinary
in-tree edits are allowed during continuous polling; polling is not byte parity
verification. Paused resume retains the existing strict seed-byte review policy.

These are local cooperating-controller locks, **not a distributed or crash-surviving
lease**. Kernel locks disappear on process exit; the same-scope dirty marker remains
but does not provide cross-scope crash recovery. No confinement of independent
GUIs, hostile same-UID writers, filesystem/native-engine name-resolution races or
unrelated bind-mount ancestry is claimed. Checks are observations, not atomic
filesystem/network transactions. Power-loss durability, transactional multi-daemon
updates, native ignore behavior and backup restore remain unqualified. A delayed
native pause acknowledgement retains locks and fails conservatively; retry stop or
perform exact-plan recovery only after native stopped evidence is restored.

#### Native API grounding and qualification boundary

The adapter accepts only **Syncthing `v1.27.12` response semantics**. This is a
source-grounded API compatibility boundary, not a recommendation to install an
old release. Other versions, remote/TLS endpoints, engine launching and a Mutagen
supervisor are **unsupported implementation scope**, not silently auto-selected.
Mutagen still has candidate generation and the lifecycle model only; rsync has
its verified disposable one-shot adapter, not a continuous service.

Authoritative protocol references (read-only documentation/source inspection):

- [REST API authentication](https://docs.syncthing.net/dev/rest.html): `X-API-Key`.
- [Config endpoints](https://docs.syncthing.net/rest/config.html): granular GET and
  PATCH `/rest/config/folders/{id}`, plus `/rest/config/restart-required`.
- [System status](https://docs.syncthing.net/rest/system-status-get.html) and
  [connections](https://docs.syncthing.net/rest/system-connections-get.html):
  `myID`, `startTime` and selected peer connectivity.
- [Folder status](https://docs.syncthing.net/rest/db-status-get.html),
  [ignore lines](https://docs.syncthing.net/rest/db-ignores-get.html), and
  [version](https://docs.syncthing.net/rest/system-version-get.html).
- Pinned upstream [model.State implementation](https://github.com/syncthing/syncthing/blob/v1.27.12/lib/model/model.go)
  and [folder summary](https://github.com/syncthing/syncthing/blob/v1.27.12/lib/model/folder_summary.go):
  empty `state` denotes absence of a folder runner. Stopped verification requires
  both that native observation and `paused: true`, not the config flag alone.

`sync_supervisor.test.py` runs controlled ephemeral loopback HTTP servers with the
above route/JSON/header contract, real sockets, actual lock contention, generation
changes, partial/no-op mutations, unavailable endpoints, dirty-guard recovery and
joined server-thread cleanup. One reseed test runs real isolated system rsync on
new disposable files. **This is explicitly synthetic protocol qualification, not
native Syncthing qualification, ignore-semantics equivalence, real backup testing,
cross-host sync qualification or runtime parity.** No actual sync engine, SSH,
cloud endpoint, existing workstation tree, settings or credentials were activated
for this work. Live native testing requires its own approval and qualification.

`local_fixture()` allocates fresh disposable endpoints; only its adapter can run
real rsync, always with `endpoint=None` and selected paths inside that fixture.
All mappings are preflighted before any transfer. Each child uses fixed
`/usr/bin/rsync` (no PATH-selected replacement), an empty disposable HOME/config/cwd,
and only `PATH=/usr/bin:/bin`, `HOME`, `LC_ALL=C`, `TMPDIR`, and `XDG_CONFIG_HOME`
in its environment. Loader, SSH, rsync and ambient configuration environment hooks
are not inherited. System binary/libraries and system `/etc/popt` remain trusted;
this hygiene is not a filesystem or network sandbox. The direct helper's legacy
process defaults remain unchanged unless the explicit local isolation option is
selected. Its shared dataset-lock API exclusively locks the fixture directory
inode and pins both directional source/destination roots before use. Thus rsync
cannot write while a cooperating continuous writer holds a nested dataset, even
with a different control directory. Missing sources are never created. Root
replacement during transfer refuses the verified receipt, even for equal bytes.
The legacy control lock inode remains stable until fixture cleanup. This is not a
production sandbox or a lock against independently launched external daemons;
real multi-host supervision, remote symlink revalidation and cross-host writer
coordination remain unimplemented. A same-UID noncooperating writer can replace
paths/lock inodes; no race-confinement claim is made.

Reproducible offline tests (repository root, existing dependencies):

```sh
PYTHONPATH=. /usr/bin/python3 src/tests/remote_development.test.py -v
PYTHONPATH=. /usr/bin/python3 src/tests/remote_development_command.test.py -v
PYTHONPATH=. /usr/bin/python3 src/tests/sync_supervisor.test.py -v
PYTHONPATH=. /usr/bin/python3 src/tests/dataset_lock.test.py -v
```

The new tests execute real disposable-local source push and artifact retrieval,
unchanged reruns, separately approved overwrite/deletion, exclusion preservation,
conflict/symlink/overlap/secret-leakage controls, candidate-only engine generation,
lifecycle writer gates, lexical-only planning, protected-path exclusions, trusted
process context and byte-verification failures, and the real Click plan/render path.
The new security regression uses a nonexistent PATH and syscall fault injection,
not an executable PATH wrapper. The historical shared-helper interruption test is
not evidence that the new isolated qualification path accepts wrappers.
Real rsync tests skip if the required binary is unavailable; they never install it. No live cloud, container, service,
physical-workstation or continuous-engine qualification is implied.
