---
name: transfer-data
description: Move data to/from an Isaac Workstation and configure what runs automatically on boot.
---

# transfer-data <!-- omit in toc -->

- [Upload inputs](#upload-inputs)
- [Download results](#download-results)
- [Selected-directory sync and IAP](#selected-directory-sync-and-iap)
- [Autorun on boot](#autorun-on-boot)

Standard folders on the workstation: `~/uploads` (inputs you send up), `~/results` (outputs to bring back),
`~/workspace` (general working dir). Locally they map to the `uploads/` and `results/` folders next to the
scripts.

## Upload inputs

Put files in the local `uploads/` folder, then:

```sh
./upload <name>
```

This copies your local `uploads/` to `~/uploads` on the workstation. You can also upload during deploy by
passing `--upload` (default) instead of `--no-upload`.

## Download results

```sh
./download <name>
```

This pulls `~/results` from the workstation into your local `results/` folder. Pulling artifacts back is an
explicit action - it does not happen automatically.

## Selected-directory sync and IAP

Preview a selected directory before sending it; rerun without `--dry-run` to copy:

```sh
./upload <name> --local-dir /absolute/local/project --remote-dir workspace/project --dry-run
./download <name> --local-dir /absolute/local/results --remote-dir results --dry-run
```

- These are explicit one-way copies of directory **contents**, not a two-way conflict
  merge. The source wins for changed files even without deletion.
- Deletion is **off by default**. `--delete --dry-run` previews destination files that
  would be removed; remove `--dry-run` only when that deletion is intended.
- Add repeatable `--exclude PATTERN`. Terraform state, private inputs/plans, common
  credential stores, personal agent memory and live Neo4j data are excluded by default.
  Exclusions are a safety default, not a scanner for arbitrary secrets. Prefer selected
  code/data directories rather than a home-directory mirror. Never rsync live state.
- On a host outside Docker, an explicit local directory must already exist. The wrapper
  maps it into the container, read-only for upload/previews and writable for download.
  The selected directory must be visible to the local Docker daemon. A Unix socket
  forwarded from another host or a devcontainer with a different filesystem does not
  establish that visibility. Inside the existing Automator container, commands run
  directly and paths refer to that container's mounted filesystem.
- Saved GCP IAP intent uses `gcloud compute start-iap-tunnel`, with explicit instance,
  project and zone; no public IP is needed. OS Login derives the actual POSIX user/key
  from gcloud rather than writing the Terraform `OS_LOGIN_ACTIVE` sentinel as a key.
  Effective IAP tunnel access and guest SSH/OS Login permissions are still required.
- First-use host trust uses `accept-new`; changed keys are refused. Preserve or pre-pin
  the deployment's `known_hosts` file. Do not delete it merely to bypass a mismatch.
- Partial transfers can be rerun. No `sudo` is used; the destination must be writable
  by the selected SSH identity. For Neo4j, transfer a consistent dump/backup, not its
  live database directory.

## Autorun on boot

To have the workstation automatically launch something when it boots (instead of the default Isaac Sim),
place a script at `uploads/autorun.sh` locally. It is uploaded to `~/uploads/autorun.sh` and, when present,
the desktop runs it on boot (and after each start). Use this to auto-launch a specific app or, for example, a
demo launcher (`~/.local/share/isaac-automator-demos/<demo>.sh`). Without an autorun script, the workstation
starts Isaac Sim by default.
