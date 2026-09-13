# Non-C3X active tooling retirement

The user selected C3X for future development in a dedicated project. This change
removes the old implementation; it does **not** deliver a C3X replacement.

## Removed from active IsaacAutomator

- `cost` command and `src/python/cost_command.py`, `cost_estimate.py`.
- `scripts/install_infracost.py` and the Dockerfile's optional Infracost argument,
  installer COPY/RUN steps and plugin environment variables.
- The shared cost widget and its usage in profiles, deployment and inspector.
  Backend validation, profile intent export, dry-run payloads and connect/state
  inspection remain; obsolete cost prompts are removed, not replaced by zeroes.
- Five tests for the retired implementation. A new
  `src/tests/cost_retirement.test.py` verifies the retirement and remaining UI.
- Active version/usage metadata. Six original records, including the old guide,
  are preserved byte-for-byte in `../archive/infracost/` with a hash manifest.

TerraCost and the IBM pricing fork were standalone experiments, not active
application dependencies; their implementation queues are closed. Their existing
historical evidence remains. This is repository cleanup, not global uninstallation
or deletion of unrelated host binaries, shared images or dependency caches.

## Actual verification

`test-results.json` records **271 passing tests across 12 suites, no skips**,
independently rerun by the parent agent. It includes executable commands, return
codes, output and source hashes; the tested source was unchanged during the run.

- CLI/backend/lifecycle/profile/Flex suites used installed system Python 3.10.
- Textual/TUI suites used the existing Python 3.12 TUI test environment.
- Tests used an allowlisted environment, temporary HOME, the repository as APP_DIR,
  mocked cloud/deployment boundaries and disposable provider-free local Terraform.
- The first parent harness omitted Terraform from PATH, used the TUI-only Python
  for CLI dependencies and set APP_DIR to a nonexistent directory. Correcting
  that harness fixed these setup errors; no dependencies or production code were
  changed to suppress failures.

`structural-checks.json` verifies six archived records equal their HEAD originals,
72 C3X evidence/public fixture files are unchanged, no retired references remain
in active Python/tooling, changed Python parses and added-line security pattern
checks found no matches. Existing `.devcontainer/`, `AGENTS.md` and `CLAUDE.md`
were not changed. `git diff --check` passed.

`code-review.json` and `plan-review-final.json` both record independent PASS.
The initial plan review found a fail-open bootstrap; `plan-review-initial.json`
preserves that finding. The final review verifies the fail-fast guards, narrower
build context, bounded readiness and removal of stale profile-guide claims.
The code review retains one non-blocking suggestion to broaden hardcoded-price
regression coverage; no code/security blocker remains.

`devcontainer-template-check.json` records JSON/Compose rendering, both shell
syntax checks and isolated bootstrap guard tests. These checks are not a production
Docker build, devcontainer startup, live deployment or successful cost estimate.

## Remaining work

C3X still fails all four G4 pricing cases. Continue with
[the dedicated project/devcontainer plan](../../../.agents/references/plans/c3x-dedicated-project-plan.md)
and main roadmap §13.8. The devcontainer examples are future instructions, not a
created project or running service. No cloud actions, existing-container changes,
commits or pushes were performed by this cleanup.
