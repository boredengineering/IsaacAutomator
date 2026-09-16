# Selected SSH/IAP transfer: implementation and qualification boundary

`src/python/selected_transfer.py` is the execution consumer for an explicitly
reviewed selection compiled by `remote_development.build_plan`. It uses the
existing SSH/IAP command construction in `src/python/file_transfer.py`, not a new
cloud deployment or credential provisioning mechanism.

No CLI activation is exposed. Construction of `SelectedTransfer(spec)` is pure;
`plan_digest` identifies the frozen selection. `seed(readiness=..., activation=False)`
refuses without explicit activation. Readiness contains the exact digest and the
caller decisions `transport_reviewed`, `paths_reviewed` and
`exclusive_writer_reviewed`. These are decisions, not cryptographic authority,
proof of a remote lease, verification of recovery, or permission inferred from a
profile. Existing endpoint credentials/known-hosts configuration are references,
not values to paste into a profile or report.

## Implemented transfer path

- Validate each selected mapping and all endpoint roots before starting any rsync.
- Run a fixed read-only manifest probe via the selected SSH/IAP transport. It reads
  only included files under the selected root, using no-follow descriptor-relative
  traversal and bounded regular-file SHA-256 checks. It does not publish a remote
  helper file or invoke project code.
- Consume the compiled rsync argv with the fixed system binary, checksum enabled,
  no deletion, retained credential/cache/environment/settings exclusions and the
  selected direction. Source/configuration mappings and results mappings can have
  opposite directions.
- Recheck source intent before launch and verify destination bytes after transfer.
  A successful child exit alone is not a verified transfer. Failure or mismatch
  does not return a success receipt.

The metadata/byte snapshots are not filesystem transaction isolation. Arbitrary
concurrent writers, hostile namespace races, protected descendant bytes that were
not read, full metadata parity and power-loss durability are not qualified. Local
cooperative dataset locking is reviewed separately with the sync supervisor;
remote/distributed exclusive ownership must not be inferred from caller booleans.

## Conservative unsupported cases

Deletion remains unavailable even when a caller marks it reviewed: applicable
recovery checks are not implemented. Missing/unowned roots, included symlinks,
hardlinks, special files, file/directory replacement, case collisions and existing
`.rsync-partial` entries require separate resolution. Observation is bounded to
10,000 entries and 256 MiB of included bytes per root. Hitting a bound is not a
complete inventory. A partial transfer has no automatic rollback; preserving or
recovering its artifacts is a separate operation.

## What was exercised

The offline suite uses fresh private trees and a controlled fake-SSH executable
that actually launches the rsync server and the real fixed manifest probe. Both
push and IAP-shaped pull exercise real local processes and byte comparison. This
proves command/protocol consumption; it does not prove an actual cloud tunnel,
authentication, host-key policy, remote permissions or GPU workstation deployment.
No real SSH connection, cloud resource, active synchronization service, user data
scan, installation or settings change was performed.

```bash
/usr/bin/python3 -B src/tests/run_profile_workflow_tests.py selected_transfer
```

Before any live use, separately review the actual hosts, credentials/known-hosts
policy, selected paths and exclusions, independent writers, seed direction,
transfer budget and recovery. Both endpoints require the fixed Python/rsync
executables used by the adapter; IAP additionally requires the existing approved
gcloud context. No automatic login, new keys, deployment or service activation is
part of this API. Native synchronization choice and devcontainer application
remain separate explicit decisions.
