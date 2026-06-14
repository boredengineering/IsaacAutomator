# Isaac Automator - Operator Agent <!-- omit in toc -->

- [What Isaac Automator does](#what-isaac-automator-does)
- [Mental model](#mental-model)
- [Prerequisites](#prerequisites)
- [Golden rules (read before deploying)](#golden-rules-read-before-deploying)
- [The operator loop](#the-operator-loop)
- [Running commands non-interactively](#running-commands-non-interactively)
- [Skills](#skills)
- [Connecting: which method shows what](#connecting-which-method-shows-what)

This file is the entry point for an **AI agent that operates Isaac Automator as a user** - to deploy a cloud
GPU workstation, connect to it, run demos, and tear it down. It is written for the *operator* role, not the
*developer* role: you drive the existing command-line tool, you do not edit its source (Python, Terraform,
Ansible). If you need to change how Isaac Automator itself works, that is a development task and out of scope
here.

If you are an agent and you just want to "get a working Isaac Sim / Isaac Lab machine in the cloud and use
it", you are in the right place. Read this file once, then open the matching skill in `skills/` for the task
at hand and follow it.

## What Isaac Automator does

Isaac Automator deploys **Isaac Sim**, **Isaac Lab**, and **Isaac Lab Arena** onto a GPU virtual machine in a
public cloud (AWS, GCP, Azure, or Alibaba Cloud) and configures it as a ready-to-use remote **Isaac
Workstation**: a GPU VM with a remote desktop, the requested Isaac apps installed, lifecycle controls
(start / stop / destroy), and data upload/download. It can also install ready-made **demos** that show up as
double-click shortcuts on the desktop.

## Mental model

- **Everything runs inside one Docker image** (`isaac_automator`). The top-level scripts (`./deploy-aws`,
  `./start`, ...) are thin wrappers that run the real command inside that container. You build the image once
  with `./build`.
- **A deployment has a name** (`--deployment-name` / `--dn`, e.g. `my-rig`). Every command after deploy takes
  that name. Its files (ssh key, terraform state, connection info) live under `state/<name>/`.
- **It provisions real, paid cloud infrastructure.** A deployment is a live GPU instance that bills by the
  hour until you stop it, plus disk that bills until you destroy it.
- **Two long-lived layers per deployment:** the cloud resources (created by deploy, removed by destroy) and
  the running instance (started/stopped to control compute cost; the public IP is preserved across
  stop/start).

## Prerequisites

> **Where you run these commands:** from the Isaac Automator repo root - the parent of this `ai/` directory,
> which holds `./build`, `./deploy-aws`, `./start`, etc. Shell commands below are run from that root; the
> `skills/` links in this guide are relative to this `ai/` folder.

1. **Docker** installed and running on the machine you operate from.
2. **Cloud credentials** for the target cloud (see `skills/deploy-workstation.skill.md` for how each cloud is
   authenticated). For AWS the simplest path is `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` in the
   environment, forwarded into the container.
3. **Build the image once:** `./build` (rebuild only if the tool itself changed).

## Golden rules (read before deploying)

- **It costs money.** Treat every deploy/start as live-fire. Use the cheapest viable GPU instance unless told
  otherwise, and prefer `--from-image` when speed/cost matters.
- **Always clean up what you create.** Stop the instance when idle (`./stop`), and **destroy** the deployment
  when done (`./destroy <name> --yes`). Stopped instances still bill for storage; only destroy stops all cost.
- **Use unique deployment names**, especially in a shared cloud account, so your resources are easy to find
  and never collide with someone else's.
- **Always pass options non-interactively.** The deploy commands prompt for missing required values; in an
  agent context an unanswered prompt hangs forever. Supply every required option on the command line.
- **Never print, paste, or commit credentials.** Reference them by name, pass them via environment variables.

## The operator loop

```
./build                      # once
  -> deploy-workstation       # ./deploy-<cloud> ... (creates infra + installs apps/demos)
     -> connect-workstation   # ./novnc / ./ssh / NoMachine
        -> run-demos          # launch a demo on the desktop
        -> transfer-data      # ./upload / ./download
     -> manage-lifecycle      # ./stop (idle) / ./start (resume) / ./repair
  -> ./destroy <name> --yes   # when finished (stops all billing)
```

## Running commands non-interactively

The `./run` wrapper uses `docker run -it`, which needs a TTY and fails in a non-interactive shell with
`cannot attach stdin to a TTY-enabled container`. When you are an agent driving this headlessly, invoke the
container directly instead of relying on a TTY:

```sh
docker run --rm --network host -v "$(pwd)":/app \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  isaac_automator "<command and args>"
```

The top-level scripts (`./deploy-aws`, `./stop`, ...) detect when they are outside the container and start it
for you, which is fine for interactive use; for reliable automation prefer the explicit `docker run` form
above (it is what the skills use).

## Skills

Open the matching file in `skills/` and follow it. Each is a self-contained operator procedure.

| Skill | Use it to |
|---|---|
| `skills/deploy-workstation.skill.md` | Deploy a new Isaac Workstation to AWS / GCP / Azure / Alibaba, with the apps (and demos) you want. |
| `skills/run-demos.skill.md` | List and launch the out-of-the-box demos (e.g. quadruped locomotion RL). |
| `skills/connect-workstation.skill.md` | Connect via noVNC (browser), NoMachine (best for 3D), or SSH. |
| `skills/manage-lifecycle.skill.md` | Check status, stop/start to control cost, repair, and destroy. |
| `skills/transfer-data.skill.md` | Upload inputs, download results, and set an autorun script. |
| `skills/troubleshoot.skill.md` | Diagnose the common failure modes (blank viewport, driver mismatch, hung prompts, ...). |

## Connecting: which method shows what

This matters because it is the most common point of confusion:

- **noVNC** (browser, `./novnc <name>`) shows the **2D desktop** reliably - good for launching apps, files, a
  terminal. It generally does **not** show the live Isaac Sim 3D viewport, because Omniverse Kit renders
  through a Vulkan surface that the VNC server does not capture. The window is there and running, but the
  viewport area can look empty.
- **NoMachine** (native client) is **GPU/Vulkan-aware** and is the reliable way to watch the live Isaac Sim /
  Isaac Lab 3D viewport. Use it when you actually need to see rendered robots.
- **SSH** (`./ssh <name>`) is for the shell: logs, launching commands, recording video headlessly.
- To capture rendered output programmatically (no display), use the app's own recorder (e.g. Isaac Lab's
  `--video`) rather than screenshotting noVNC.
