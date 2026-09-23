# Isaac9s — terminal interface for Isaac Automator

Isaac9s is the k9s-style, Textual-based terminal user interface in this directory.
It brings workstation deployment, fleet inspection, logs, connection helpers,
local diagnostics and profile configuration into one application. The executable
is [`../../isaac9s`](../../isaac9s), not a script inside `src/tui`.

**Status:** under development. This README is the maintained usage reference and
source material for future published user documentation. It describes existing
behavior separately from incomplete integrations. Source review is not evidence
of a successful live cloud deployment or robotics workload run.

The purpose is to operate workstations for the intended simulation, training or
policy-evaluation workload—not to inventory or reproduce every detail of a host.
Isaac9s reuses the deployment CLI; it is not a separate provisioning engine and
has no prerequisite dependency on the host collector.

## Contents

- [Launch and prerequisites](#launch-and-prerequisites)
- [First tour](#first-tour)
- [Keyboard reference](#keyboard-reference)
- [Deploy a workstation](#deploy-a-workstation)
- [Profiles: software versus infrastructure](#profiles-software-versus-infrastructure)
- [Inspect, connect and manage workstations](#inspect-connect-and-manage-workstations)
- [Logs and process control](#logs-and-process-control)
- [Current limitations](#current-limitations)
- [Troubleshooting](#troubleshooting)
- [Developer map and verification](#developer-map-and-verification)
- [Maintaining and publishing this guide](#maintaining-and-publishing-this-guide)

## Launch and prerequisites

From the repository root, in a terminal with the TUI dependencies available:

```sh
./isaac9s
```

The launcher uses `python3` from the current environment. An equivalent explicit
invocation is `python3 ./isaac9s`. Use an interactive terminal; do not redirect the
TUI's output to a file. Run from the repository root for consistent child-command
behavior.

The direct runtime dependencies are pinned in
[`requirements-tui.txt`](../../requirements-tui.txt): Textual, Rich, psutil,
PyYAML and Click. That manifest records an isolated Python 3.12 test environment.
If your existing Automator environment lacks them, an optional dedicated setup is:

```sh
# From the repository root; requires Python 3.12 with venv support.
python3.12 -m venv .venv-isaac9s
.venv-isaac9s/bin/python -m pip install -r requirements-tui.txt
.venv-isaac9s/bin/python ./isaac9s
```

This installs only the TUI dependencies into that environment. It does not set up
Terraform, Ansible, Docker, cloud SDKs, deployment CLI dependencies or credentials.
For actual operations, use the prepared Automator environment and follow the
[repository setup guide](../../README.md#development-environments). Do not install
these packages into an existing robotics environment merely to launch the TUI.

**Execution context matters:** telemetry and local checks observe the environment
running Isaac9s. Inside a devcontainer they do not establish the physical host's
configuration or the selected cloud VM's health. Startup/refresh can perform local
checks, including `nvidia-smi` when available; this is not a no-probe viewer.

## First tour

1. Launch Isaac9s and press `?` for the built-in help.
2. Press `2` for Fleet. Highlight a workstation and press `i` or select its table
   row with Enter to inspect it. Treat saved inventory as controller evidence,
   not a fresh cloud health check.
3. Press `5` to inspect software intent and security/backend settings. Selecting
   software here does not install it or select it for the deployment wizard yet.
4. Press `n` to inspect the deployment form. Use its Cancel button or Escape to
   leave without submitting. Opening the form resolves backend intent offline;
   it does not launch a VM.
5. Press `3` to view logs; press `q` from the main screen to exit.

Do not press lifecycle or launch controls merely to explore the interface. These
can invoke real cloud operations. Quitting the TUI is not cloud cleanup.

## Keyboard reference

These are the main-screen bindings in [`app.py`](app.py). Text inputs and modal
screens may consume keys; use Escape to leave an input or close a modal before
using main-screen shortcuts. Modal `q` handling can differ while typing.

| Key | Action |
|---|---|
| `1` | Subsystems & Health |
| `2` | Workstations & Fleet |
| `3` | Real-Time Logs |
| `4` | Pre-Flight Doctor |
| `5` | Security & Profiles, including offline software intent |
| `6` | Hardware Telemetry |
| `?` | Help |
| `:` | Open the command bar |
| `/` | Focus log filter on Logs; otherwise open the command bar |
| `n` | Open deployment wizard |
| `i` | Inspect highlighted workstation |
| `c` | Open connection selector |
| `a` | Open cloud authentication helpers |
| `p` | Refresh local hardware/subsystem/doctor checks |
| `h` | Invoke local installer `repair --dry-run`, if available; not cloud drift repair |
| `s` | Start highlighted eligible cloud workstation |
| `x` | Stop highlighted eligible cloud workstation |
| `k` | Cancel pending dispatch / attempt to terminate active subprocess |
| `r` | Refresh telemetry and dashboard panes |
| Escape | Dismiss command bar / leave focused input; modal close where supported |
| `q` | Quit from the main screen; close supported modals |

The command bar accepts commands such as `:ws`, `:sub`, `:logs`, `:doc`,
`:profiles`, `:hw`, `:deploy`, `:inspect`, `:auth`, `:connect`, `:probe`,
`:heal`, `:refresh`, `:copy` and `:q`.

Two important distinctions:

- `:stop`, `:kill` and `:abort` cancel the active subprocess. **They do not stop
  the highlighted VM.** Use the Fleet Stop button or `x` for that.
- `:validate`, `:dryrun` and `:plan` only open the deployment wizard. They do not
  perform validation until the appropriate wizard action is submitted.

## Deploy a workstation

**Live operation warning:** Launch Deployment invokes `deploy-<cloud>` and may
create paid infrastructure. The current command builder passes `--existing replace`.
Use a new, unique deployment name; reusing a name may replace an existing deployment.
There is no separate workload approval implied by backend validation.

1. Press `n` and enter a unique workstation name.
2. Select cloud, instance type, zone/region and provisioning model. For GCP,
   supply the explicit project ID. Flex-start is offered for GCP.
3. Select the security profile and inspect the Terraform backend selection.
   Backend intent is resolved offline on entry and when relevant choices change;
   the **Validate backend config (offline)** button can repeat it.
4. Review optional demos. **Franka Manipulation is checked by default.** Clear
   it if that is not the workload you want.
5. Check the summary and the [current limitations](#current-limitations).
6. Use **Dry Run / Validate** only when ready for a cloud-aware plan. For an
   already validated local backend, this invokes the deploy CLI's dry-run path.
   With unresolved or remote intent, it performs backend-intent validation instead
   of deployment. Inspect the resulting status rather than assuming both happened.
7. Use **Launch Deployment** only after reviewing the actual choices and costs.
   Follow command output and the exit status in Logs.

The current TUI permits deployment dispatch only with a validated **local
Terraform backend**. Here, “local” describes where Terraform state is managed;
its target is still a cloud workstation. Non-local backend choices are available
for intent validation but execution is blocked by the TUI.

**Dry-run is not offline and not workload acceptance.** The underlying CLI can
authenticate, read cloud APIs, acquire backend locks and write local controller
files. It runs Terraform planning and Ansible syntax validation, not a complete
installation or robotics workload. Do not assume dry-run is harmless when reusing
an existing deployment name with replacement behavior. Prefer a new name.

Source: [`screens/deploy_modal.py`](screens/deploy_modal.py),
[`backend.py`](backend.py), [`deploy-gcp`](../../deploy-gcp).

## Profiles: software versus infrastructure

The Profiles pane contains distinct concepts:

- **Workstation software intent:** preview a software preset. It is labeled
  “NOT APPLIED.” This choice is not currently transported to deployment through
  `--software-profile`.
- **Security/infrastructure intent:** Simple, Team, Enterprise or a custom set
  of infrastructure features. This is what the deployment command's `--profile`
  selects; it is not the robotics software profile.
- **Terraform backend intent:** an independent choice. A valid configuration does
  not prove access to its remote storage or enable TUI remote execution.

“Save Intent (not apply),” “Save Profile to YAML” and “Export Active Spec” are
configuration actions, not installation. Exports may create or overwrite local
files. The exported active spec is not proof of a deployable software profile.
Some generic success messages still say “applied”; do not interpret them as
successful cloud provisioning or software installation.

Source: [`screens/profiles.py`](screens/profiles.py).

## Inspect, connect and manage workstations

Use Fleet (`2`) to select a workstation, then Inspect (`i`) for saved details or
Connect (`c`) for endpoint helpers. The connection modal offers noVNC, NoMachine,
Sunshine and SSH. Offering a protocol does not mean its server/client is installed,
reachable, or configured for the selected security profile.

The current modal constructs direct endpoint URLs. It does **not** establish an
IAP tunnel. SSH selection logs the instruction to run `./ssh <name>` separately;
NoMachine selection does not automatically start a native client. For private/IAP
workstations, use the existing [connection procedures](../../.agents/skills/isaac-automator/connect-workstation/SKILL.md)
and CLI connection helpers rather than relying on the modal's direct IP URL.

`s` starts and `x` stops an eligible selected cloud workstation.
Saved remote attachments may be blocked by the TUI. Start can incur charges;
stop does not delete disks or eliminate all costs. There is no dedicated Destroy
binding in this TUI. Deliberate teardown uses the separate CLI, for example
`./destroy <name> --yes`, after checking the exact target and preserving needed data.

A successful connection message is not proof of a rendered simulation, working
policy service or completed training run.

## Logs and process control

The Logs pane shows the dispatched command, output and exit status. One active
command is tracked at a time. Use its filter field (or `/` on Logs) to search.

- **Stop Process / `k`:** attempts to terminate the tracked subprocess. It is not
  rollback, may not terminate every descendant, and does not destroy cloud
  resources already created. Inspect actual operation/resource state afterward.
- **Copy All (AI Paste) / `:copy`:** attempts to copy the full log, not only the
  filtered display, to the clipboard and writes `/tmp/isaac9s.log`. The file may
  be overwritten. Clipboard/file failures can be swallowed by the current code;
  check the destination before relying on the success notification.
- **Clear Log:** clears the in-app history/display; it does not undo commands or
  remove previously exported files.

Review and redact exported logs, diagnostic JSON and profile YAML before sharing.
Command redaction is not a guarantee that arbitrary subprocess output contains
no sensitive data. Export buttons perform filesystem writes; this is not a fully
read-only application.

## Current limitations

These are implementation boundaries, not promises of finished functionality:

| Area | Current behavior / consequence |
|---|---|
| Workload software selection | Profiles preview exists; deployment still hardcodes `latest` for Sim, Lab and Arena and does not pass `--software-profile`. A preview is not the deployed workload specification. |
| GCP GPU count | Command builder passes one GPU. Do not assume multi-GPU choices are correctly transported. |
| Remote Terraform backends | Non-local dispatch is blocked in the TUI even where underlying CLI support exists. Do not silently switch to local to bypass the block. |
| Cost | No working integrated quote is provided; “cost not estimated” is not zero cost. |
| Catalog labels | GPU/zone labels are static hints, not live quota, capacity, hardware or availability verification. |
| Local health | Checks run in the controller's environment. An empty fleet can display a local-workstation/READY fallback; that is not validated physical-host or cloud-workload readiness. |
| Connections | Direct URL helpers do not implement private/IAP tunnel setup or prove connection success. |
| Success messages | Command exit, “profile applied,” repair-preview success and connection messages do not establish end-to-end workload acceptance. |

For a workload needing exact sources/runtime settings or remote state, review the
CLI's supported configuration rather than trusting the current wizard to carry
those requirements. The desired future path is selected workload intent → exact
CLI transport → deployment → workload verification; the missing integration must
not be documented as already complete.

## Troubleshooting

| Symptom | Check |
|---|---|
| `ModuleNotFoundError` for Textual/Rich/etc. | Use the interpreter/environment containing `requirements-tui.txt`; installing UI dependencies alone does not install cloud tooling. |
| Shortcut types a character instead of acting | Leave the focused input with Escape or use the visible button. |
| Launch disabled | Inspect backend status. Resolve configuration errors; remote backend execution remains intentionally blocked in the TUI. |
| GCP dispatch refused | Supply an explicit project ID and inspect backend status. Authentication/account discovery is not a substitute for choosing the project. |
| No GPU or unexpected local paths | Confirm whether Isaac9s is running on the host, in a container or on a VM. Do not open extra host mounts merely to make the dashboard green. |
| Remote connection URL fails | Check required client/server and the real SSH/IAP route; the modal does not create tunnels. |
| A command appears stuck | Check Logs and underlying command status. Use Stop Process deliberately; cancellation is not cleanup. |
| Copy/export says success but nothing appears | Check clipboard support and the reported file destination; current export error reporting is incomplete. |

## Developer map and verification

| File | Responsibility |
|---|---|
| [`../../isaac9s`](../../isaac9s) | Repository-root launcher |
| [`app.py`](app.py) | Tabs, bindings, command routing and subprocess lifecycle |
| [`backend.py`](backend.py) | CLI command construction, controller inventory and bounded backend-intent validation |
| [`telemetry.py`](telemetry.py) | Local CPU/RAM/disk/GPU observations |
| [`screens/deploy_modal.py`](screens/deploy_modal.py) | Cloud deployment form and dispatch result |
| [`screens/profiles.py`](screens/profiles.py) | Software preview and security/backend intent |
| [`screens/workstations.py`](screens/workstations.py), [`screens/inspector.py`](screens/inspector.py) | Fleet view and workstation inspection |
| [`screens/logs.py`](screens/logs.py) | Log filtering, export and process controls |
| [`screens/remote.py`](screens/remote.py), [`screens/auth_modal.py`](screens/auth_modal.py) | Connection and authentication helpers |
| [`screens/subsystems.py`](screens/subsystems.py), [`screens/doctor.py`](screens/doctor.py), [`screens/hardware.py`](screens/hardware.py) | Local diagnostics and hardware views |
| [`styles/isaac9s.tcss`](styles/isaac9s.tcss) | Application styling |

Relevant tests are [`isaac9s.test.py`](../tests/isaac9s.test.py) (Textual Pilot)
and [`terraform_tui.test.py`](../tests/terraform_tui.test.py) (backend integration).
Do not run UI tests against operational state without reviewing and isolating
local checks, subprocesses and export destinations: the existing Pilot suite can
invoke checks and write reports/profile exports. Use synthetic state and mocked
operational calls for repeatable UI acceptance. Do not infer full runtime coverage
from a historical test total.

For this README's initial addition, verification is source/link/shortcut checking,
not a new interactive run, dependency installation or cloud deployment. A release
verification should separately record UI navigation, exact command transport,
backend behavior, and the selected real workload's outcome.

## Maintaining and publishing this guide

Update this README in the same change that alters user-visible controls, command
transport, prerequisites, effects or limitations. Keep the repository's
[Isaac9s overview](../../README.md#interactive-terminal-cockpit-isaac9s) linked here.
The [historical design plan](../../.agents/references/plans/isaac9s-gui-plan.md)
is background, not a substitute for current usage instructions.

Before deriving published documentation from this file:

- Verify launch instructions, labels, shortcuts and examples against the release.
- Exercise examples in an isolated environment; keep paid/cloud acceptance separate.
- Update or remove limitations only when their replacement behavior is implemented
  and tested; do not turn planned behavior into present-tense instructions.
- Split the stable material into quickstart, task guides, keyboard reference,
  troubleshooting and developer reference as needed, retaining relative-link meaning.
- Use sanitized examples/screenshots; never publish credentials, raw Terraform
  state or private logs. Document workload success separately from installation.
- Record the verified release/commit and acceptance scope in the published docs.

No documentation generator or publication pipeline is installed by this README.
It provides a maintained Markdown source that a later documentation tool can use.
