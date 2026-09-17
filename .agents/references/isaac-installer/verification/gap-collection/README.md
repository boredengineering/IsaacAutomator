# Host-discovery gap verification

This directory contains an independent **synthetic-only** acceptance runner for
BoredEngineer-scoped metadata collection and profile review. It is not a host
inventory, real installer acceptance, or user approval of a desired profile.

## Replay

Run from the repository in the devcontainer:

```sh
/usr/bin/python3 -I -S -B .agents/references/isaac-installer/verification/step2/run_bounded_tests.py
/usr/bin/python3 -I -S -B .agents/references/isaac-installer/verification/step1/isaac-step1-runner.py
/usr/bin/python3 -I -S -B .agents/references/isaac-installer/verification/gap-collection/run_acceptance.py
```

The runners allocate disposable fixtures under `/tmp`. They reuse the existing
unprivileged STEP1 Landlock/seccomp boundary: repository read-only, fixture-only
writes, denied network, and negative-control canaries. No extra host mounts or
permissions are granted. The acceptance runner copies the actual repository
collection wrapper and scripts byte-for-byte into a synthetic checkout and
records their SHA-256 digests.

The acceptance runner checks:

1. Kernel negative controls and an ordinary-user positive path.
2. Actual wrapper plan and collection using `--scope software`,
   `--workspace-name BoredEngineer`, and `--include-editable`.
3. Exclusion (not deletion) of the lowercase workspace; source files unchanged.
4. Full Isaac Sim prerelease/build version, large Conda Python record,
   underscore-prefixed Conda package, bounded dist-info header and editable source.
5. Actual `import-host-report`, retaining detailed evidence and leaving every
   initial candidate decision unapproved.
6. Explicitly **synthetic** review choices, reimport continuity, and YAML export.
7. Local rendering preserving the exact prerelease/build version.
8. Accurate Ansible rendering refusal for that prerelease: the current standalone
   role supports final `6.0.1` only. Exit 2 and the precise version blocker are
   required; replacing the version with final `6.0.1` is forbidden.
9. A profile-only `install --dry-run` with unknown targets and no execution.
10. Unchanged source/report canaries and no launcher/import execution markers.

`passed: true` in this acceptance receipt means all those checks behaved as
expected. It does **not** mean Ansible supports the prerelease, an archive exists,
a workstation was installed, or all host discovery gaps are closed. The receipt
reports `ansible_render_supported: false` separately from the successful check.
Fixture source URL/checksum values are deliberately synthetic and never fetched.

## Evidence and remaining gates

Each command prints its artifact root and result/receipt paths. The final session
verification summary records the actual run counts, review receipts, and source
hashes; earlier failing runs are retained to show the regression and review loop.
Do not treat an intermediate or stale review snapshot as final approval.

The next real operation is an ordinary-user host collection into a fresh
`configs/private/host-software-03.json`. Preserve older reports. Only after that
report is inspected can the real configuration proposal be completed and reviewed.
No actual workstation YAML, install, migration, or paid-cloud acceptance is
claimed by these disposable tests.
