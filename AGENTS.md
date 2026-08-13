# Isaac Automator - Agent Instructions <!-- omit in toc -->

- [Operator quickstart (the short version)](#operator-quickstart-the-short-version)
- [Rules for agents (read before acting)](#rules-for-agents-read-before-acting)
- [Map](#map)

This repository is **Isaac Automator**: a command-line tool that deploys Isaac Sim, Isaac Lab, and Isaac Lab
Arena to public clouds (AWS, GCP, Azure, Alibaba Cloud) as ready-to-use GPU **Isaac Workstations** (a remote
desktop cloud VM with the Isaac apps installed, plus start/stop/destroy lifecycle and data transfer).

If you are an AI agent working with this repository, first decide your role:

- **Operating** Isaac Automator - you want to *use* the tool: deploy a workstation, connect to it, run a
  demo, stop/start it, and tear it down. **Read [`ai/automator.agent.md`](ai/automator.agent.md) and follow the
  procedures in [`.agents/skills/isaac-automator/`](.agents/skills/isaac-automator/).** That is the entry point for operator agents. Start there.
- **Developing** Isaac Automator - you want to *change* the tool itself (its Python CLI, Terraform, or
  Ansible). See [`README.md`](README.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md). The operator docs are not
  for editing source.

## Operator quickstart (the short version)

The full procedures are in `.agents/skills/isaac-automator/`; this is the orientation.

1. **Prerequisite:** Docker running, cloud credentials available, then `./build` once.
2. **Everything runs in a container.** The top-level scripts (`./deploy-aws`, `./start`, `./novnc`, ...) wrap
   commands that run inside the `isaac_automator` Docker image. Run them from the repo root.
3. **Deploy:** `./deploy-<cloud>` with options; e.g. install Isaac Lab and a demo in one shot. See
   `.agents/skills/isaac-automator/deploy-workstation/SKILL.md`.
4. **Connect:** `./novnc <name>` (2D desktop), NoMachine (live 3D viewport), or `./ssh <name>` (shell). See
   `.agents/skills/isaac-automator/connect-workstation/SKILL.md`.
5. **Control cost / clean up:** `./stop <name>`, `./start <name>`, and `./destroy <name> --yes`. See
   `.agents/skills/isaac-automator/manage-lifecycle/SKILL.md`.

## Rules for agents (read before acting)

- **It provisions real, paid cloud infrastructure.** Treat every deploy/start as live-fire. Use the cheapest
  viable GPU instance unless told otherwise.
- **Always clean up what you create.** Stop when idle; **destroy** (`./destroy <name> --yes`) when done -
  stopped instances still bill for storage, only destroy stops all cost.
- **Run non-interactively.** The deploy commands prompt for any required option you omit; an unanswered prompt
  hangs an agent forever. Pass every required option on the command line, and use `--existing replace` (not
  `ask`). For a headless invocation that does not need a TTY, call the container directly:
  `docker run --rm --network host -v "$(pwd)":/app isaac_automator "<command>"`.
- **Never print, paste, or commit credentials.** Pass them via environment variables (e.g.
  `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) and reference them by name only.
- **Viewport over remote desktop:** noVNC shows the 2D desktop but generally not the live Isaac Sim 3D
  viewport (Omniverse Kit renders via a Vulkan surface VNC does not capture). Use **NoMachine** for live 3D,
  or capture rendered output headlessly with the app's own recorder. Details in
  `.agents/skills/isaac-automator/connect-workstation/SKILL.md` and `.agents/skills/isaac-automator/troubleshoot/SKILL.md`.
- **Explicit Push Permission Required:** **NEVER** execute `git push` (or `git push --force`) to remote repositories unless the user explicitly requests a push in their prompt (e.g. "push to github", "git push"). Local edits and local commits (`git commit`) are permitted, but remote pushes must strictly wait for explicit user instruction.

## Session Memory Protocol

- **Resuming Work**: When asked about past sessions, check [`.agents/memory/INDEX.md`](.agents/memory/INDEX.md) and load relevant logs from `.agents/memory/sessions/`.
- **Saving Checkpoints**: Upon completing major milestones, architectural changes, or when requested ("save session", "checkpoint"), follow [`.agents/skills/isaac-automator/session-memory/SKILL.md`](.agents/skills/isaac-automator/session-memory/SKILL.md) to log a 25-character `YYYYMMDD_HHMMSS_<short_uuid>.md` file in `.agents/memory/sessions/` and add an entry to [`.agents/memory/INDEX.md`](.agents/memory/INDEX.md).

## Map

- [`ai/automator.agent.md`](ai/automator.agent.md) - operator agent entry point (mental model, golden rules, skills index).
- [`.agents/skills/isaac-automator/`](.agents/skills/isaac-automator/) - step-by-step operator procedures (deploy, run-demos, connect, lifecycle, transfer-data, troubleshoot).
- [`.agents/memory/INDEX.md`](.agents/memory/INDEX.md) - master index of session memory checkpoints.
- [`README.md`](README.md) - full human documentation for using and understanding the tool.

