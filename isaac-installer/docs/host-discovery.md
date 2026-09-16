# Host metadata discovery without opening devcontainer access

The collector is a standalone standard-library Python script. Develop/test it in
this repository; run it explicitly on the host as the ordinary workstation user.
It does not need host mounts, SSH access from the devcontainer, package installs,
network access, Isaac imports, or an activated environment.

## Quickstart: save directly in the repository

In a **host terminal**, as your ordinary user, from the IsaacAutomator repository:

```sh
./collect-host-metadata --plan
# Review the scope above, then explicitly collect:
./collect-host-metadata --collect
```

The wrapper uses `/usr/bin/python3` in isolated, no-site/no-bytecode mode even
when Conda is active. It saves `configs/private/host-inventory.json` relative to
the script's repository, not your current directory, and prints the full path.
That directory is already Git-ignored. When this checkout is the devcontainer's
existing workspace mount, the report is available there without a separate copy.
This does not create mounts or allow a container to inspect the host.

Plan mode creates nothing. Collection first finishes the bounded metadata reads
in memory, then creates only the output directories and private report. This
explicit post-collection output is allowed even when the repository is inside
`~/Documents/GitHub`; the portable collector below still refuses outputs inside
observation trees. New private directories use mode 0700 and reports mode 0600.
An existing `configs/private` must be owned by you, have no group/other access,
and not be a symlink; the wrapper does not change existing permissions. Existing
reports and symlinks are never overwritten. Move an existing report yourself
before another run, or use the portable collector with a new external filename.
A failed/interrupted write can leave a partial report; only the success message
confirms completion. No installs, automatic import/review, or profile approvals
are performed. No `sudo` or stdout/stderr file redirection.

The wrapper accepts the same `--home`, `--system-root`, and `--max-*` scope/limit
options described below, but the output filename is fixed. To choose another
output location, use the standalone script below. Keep reports private and out
of commits or uploads, even though they live inside the checkout.

## 1. Review the scope on the host

From the host's copy of this repository (or copy just the collector script there):

```sh
/usr/bin/python3 -I -S -B isaac-installer/tools/collect_host_metadata.py \
  --plan --output "$HOME/isaac-host-inventory.json"
```

Plan mode is the default. It prints the planned seeds, metadata categories,
limits and destination without scanning target roots or creating the report.
Review that output before collection. `--home` defaults to the invoking user's
home; do not use the devcontainer's home as a proxy for the workstation.

No `sudo`. Do not redirect stdout/stderr into files: the entry refuses inherited
regular-file streams to avoid writing diagnostics into an existing file. Use its
explicit `--output` argument instead. The destination's parent must already exist
and the destination must be new, outside the selected observation trees.

## 2. Collect only after reviewing that scope

```sh
/usr/bin/python3 -I -S -B isaac-installer/tools/collect_host_metadata.py \
  --collect --output "$HOME/isaac-host-inventory.json"
```

This creates a private mode-0600 JSON report, never replaces an existing file,
and never installs, repairs, renames or updates anything. Ordinary reads may
update access times. A failed/interrupted collection may leave a new partial
report; do not assume success merely because a file exists. Collection success
means a report was written, not complete coverage or a healthy machine.

Defaults: 4096 entries, 8 MiB metadata read budget, 10 seconds, depth 4. Increase
explicitly only after examining reported coverage gaps; counts include directory
entries and metadata reads, not only packages. Supported positive upper bounds
are 100000 entries, 64 MiB, 120 seconds and depth 16. Bounded truncation and failed
reads are recorded, never silently presented as a complete inventory.

The portable schema also caps retained repositories at 128 and environments at
32. A separate 1 MiB serialized-report budget leaves room for the importer's
baseline/candidate/review envelope. Exceeding these limits produces truncated
evidence with coverage markers; raising the read budget does not remove them.

`--system-root` is primarily a synthetic/offline-root test seam. Non-root values
produce `identity: fixture`; they do not prove observations came from a running
host. With `/`, identity is explicitly *user-supplied-host*, not an attestation.
Container markers are best-effort facts; missing markers do not prove bare metal.

## What the algorithm collects

1. **Workspace first:** bounded names in `~/Documents/GitHub`, starting with
   BoredEngineer/case variants and the known legacy `boredengineering` alias.
   Multiple candidates remain ambiguous. Exact names and discovered repository
   paths are retained; nothing is renamed or created in that workspace.
2. **Repositories:** selected Git HEAD/config/ref metadata. No Git commands,
   hooks, checkout/status/fetch, object reads or config includes are executed.
   Remote URLs are reduced to supported credential-free GitHub repository URLs.
   Unknown sources, worktree indirections and unresolved revisions remain gaps.
   Dirty/index state stays `unknown`, never assumed clean.
3. **IsaacSim:** `~/IsaacSim/VERSION`, without executing Kit or scanning assets.
   A version file does not establish a verified source archive or runtime health.
4. **Machine facts:** fixed OS, kernel, CPU/RAM, NVIDIA driver and CUDA version
   records. OS discovery admits the conventional `/usr/lib/os-release` fallback,
   not an arbitrary symlink destination. Driver version and CUDA toolkit version
   are separate. GPU query execution is not enabled; unavailable facts remain null.
5. **Ubuntu/Debian packages:** selected fields from `/var/lib/dpkg/status` and
   `/var/lib/apt/extended_states`. Only installed dpkg records are included;
   architecture and automatic/manual/unknown classification are retained.
   Observed `install ok installed` versus `hold ok installed` status is retained
   separately in the detailed evidence, rather than lost after filtering.
   No `apt update`, package-manager executable, sources/auth configuration,
   maintainer script, log, shell history or package import is used.
6. **Environment metadata:** bounded known Conda seeds plus workspace/repository
   `.venv` metadata. Conda records and dist-info name/version data are read without
   activating an environment. Editable/source tooling not safely understood is
   reported as unsupported rather than followed or imported.

This is not every installed program: Snap/Flatpak, container contents, arbitrary
prefixes, live GPU compatibility and unsupported editable/source metadata remain
outside coverage. Manually marked packages include dependencies/base-image choices;
that flag is not proof the user intentionally wants a package in a future profile.
No automatic all-package reproduction is proposed.

## Detailed evidence and follow-up review

New collector reports include a versioned `details` section:

- `repositories`, `isaacsim`, and `environments` bind each retained fact/package
  to its selected metadata source. Keys use stable paths/package identities,
  never positions in an enumeration.
- `system_packages` retains the fixed dpkg/APT source paths and each installed
  package's observed status, keyed by name and architecture. Package/manual
  selectors are defined by the schema, not arbitrary executable queries.
- `links` records bounded link-target text without following the target. Unsafe
  or unrepresentable text is redacted/unknown. A reported target is not a new
  read grant or permission to search it.
- `followups` proposes specific next-batch scopes for missing/ambiguous seeds,
  links, unresolved Git references/worktrees and selected editable/UV/environment
  descriptors. Every proposal requests explicit scope; none triggers collection.
- `package_groups` lists deterministic member identities for OS baseline,
  drivers/CUDA, build tools, optional applications and an uncertain bucket.
  These are name-based review hints—not assertions about necessity, ownership,
  compatibility or installation intent.

The importer validates these relationships lexically without opening any source
paths. Group/scope summary notes point back to the structured baseline details.
Older reports without `details` remain explicitly limited evidence, not retroactive
per-fact source proof. All hashes/provenance here provide consistency and
attribution, not cryptographic attestation of a host or its current state.

The script pins paths with nofollow descriptors and rejects unsafe input files,
bounds reads/enumeration, and has a collection deadline. It is **not** the existing
CLI's Landlock/seccomp sandbox and is not generic hostile-code isolation. Symlinks
are not followed outside the explicit read set. Unusual locations should be
reviewed as additional scope, not handled by disabling checks.

## 3. Bring the report back into the devcontainer

Transfer the report yourself through your existing approved workflow. The report
contains private paths and package details; it is not automatically uploaded or
committed. Keep it private and out of Git. Inspect/review it locally before sharing.

The existing non-root installer entry now accepts:

```sh
./isaac-installer/bin/isaac-installer import-host-report \
  --report /absolute/private/host-inventory.json \
  --output /absolute/private/new-candidate.json
```

Run the importer as an unprivileged account with read permission on that report
and write permission on the private output directory. The existing CLI still
refuses root. A root-running devcontainer therefore needs an explicitly prepared
unprivileged report-processing session; do not change workstation permissions,
add mounts, or weaken the reader boundary to work around it.

The importer validates the whole bounded schema and reads only the selected local
report (and explicitly selected previous report). Host paths inside the JSON are
**data**, not local read grants. Original local report roots are retained across
reimports and exclude overwriting input artifacts. Imported data is not an
attestation that those host files still exist or match the report.

Its output is the existing baseline/candidate/review bundle:

- Workspace spelling/root and recognized repository source/revision proposals.
- Environment and optional tool proposals, with machine/system-package inventory
  retained as grouped evidence/backlog—not thousands of automatic approvals.
- Original IsaacSim version/path, but no invented download URL or checksum.
- No accepted fields and no execution authorization.
- Required path-review notes when an existing checkout does not match conventional
  consumer destinations. Accepting an unsupported note alone does not make the
  path mapping implemented; resolve the target intent explicitly.

Use the existing `review-profile`, `export-profile`, `render-profile` and
`install --dry-run --desired-profile` commands documented in `profile-discovery.md`.
An accepted package still needs purpose/source/environment decisions before it
can map to a consumer. System packages/machine settings currently remain evidence,
not implemented Ansible installation intent.

Re-import with `--previous-report /absolute/private/reviewed.json` to retain
previous decisions. Enumeration reordering is canonicalized, and environment
identities derive from paths rather than array positions. A changed report or
changed local evidence path conservatively requires renewed evidence review;
there is no automatic approval of changes.

## Verification

The retained step-2 harness and end-to-end demo live in
`.agents/references/isaac-installer/verification/step2/`. They use explicit
synthetic home/system roots under the established unprivileged filesystem/network
boundary. Do not replace these with the broad default test runner, managed
apply/recovery probes, or collection against the executing machine.

The synthetic demo's revisions, archive URL/checksum and package records are
illustrative test data. A complete reviewed test profile is not a real host
profile, verified runtime, or permission to deploy/install/synchronize.
