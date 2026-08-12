---
name: transfer-data
description: Move data to/from an Isaac Workstation and configure what runs automatically on boot.
---

# transfer-data <!-- omit in toc -->

- [Upload inputs](#upload-inputs)
- [Download results](#download-results)
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

## Autorun on boot

To have the workstation automatically launch something when it boots (instead of the default Isaac Sim),
place a script at `uploads/autorun.sh` locally. It is uploaded to `~/uploads/autorun.sh` and, when present,
the desktop runs it on boot (and after each start). Use this to auto-launch a specific app or, for example, a
demo launcher (`~/.local/share/isaac-automator-demos/<demo>.sh`). Without an autorun script, the workstation
starts Isaac Sim by default.
