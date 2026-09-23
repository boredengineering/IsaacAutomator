# Host discovery continuation plan

## Decision — 2026-09-19: stop the broad collector direction

**Status: closed as a development direction, not completed as host acceptance.**
The user clarified that the intended input was a **small amount of relevant
information**, not a system inventory or an agent orchestrating repeated searches
to find everything installed. We are moving on from expanding this collector.
This decision supersedes the next-scan instructions and pending collection gates
below. They are retained as history, not a current task queue or permission.

### Reflection and source-backed findings

Research for this decision was a read-only review of the current source, plans,
documentation and previous conversation. No host scan, private-report reread,
runtime probe or external benchmark was performed. Source line references below
describe the code inspected on this date; historical results are labeled as such.

1. **We confused bounded execution with a small information need.**
   `isaac-installer/tools/collect_host_metadata.py:1008-1084,1110-1146`
   defaults to `scope='all'` and combines workspace/Git, Sim, machine, system
   package and environment metadata. Byte/entry/time limits constrain work but
   do not establish which facts are necessary for the user's next decision.
   The implementation is not literally an unrestricted scan of the whole system;
   its category breadth is nevertheless larger than the clarified task warrants.
2. **The narrower flags did not make collection question-specific.**
   `collect_host_metadata.py:1076-1082,1160-1163` omits machine/system-package
   reads in software mode, but still collects environment metadata.
   `isaac-installer/docs/host-discovery.md:82-88` explicitly says workspace
   selection retains the usual Sim and Conda seeds. Selecting a folder is not
   equivalent to selecting a small set of needed facts.
3. **Coverage became the objective instead of usefulness.**
   The earlier stopping point below records 1,756 package records and no collected
   repositories/environments. The documented shared-budget problem
   (`isaac-installer/docs/host-discovery.md:47-55`) led to software-only reruns;
   later work added metadata formats and editable relationships. Those fixes can
   be technically valid while the repeated gap-closing loop is the wrong product
   direction. Missing optional facts need not become another discovery task.
4. **More observations still did not answer what belongs in the profile.**
   `isaac-installer/lib/core/host_inventory.py:396-475` keeps proposals unapproved,
   uses heuristic package groups and proposes at most the first 32 packages per
   environment with unknown purpose/source. These safeguards correctly avoid
   inventing intent; they also show why inventory volume cannot substitute for
   relevance, user choices or runtime compatibility evidence.
5. **The agent's process drifted toward orchestration.**
   The code does not autonomously execute its proposed follow-ups: they are
   explicit scope-review notes (`host_inventory.py:431-435`). The problem was our
   workflow of turning gaps into more collection, fixes, scans and review work.
   Replacing the collector with an autonomous discovery agent would repeat that
   mistake; no such replacement is selected or authorized.
6. **The last suggested YAML integration addressed the wrong level.**
   Reading workspace settings from a partial profile could remove duplicate CLI
   input, but would not itself reduce what the collector tries to learn. The
   previous session's recommendation to implement it before another scan is
   withdrawn as the immediate next step, not promoted into a new implementation
   plan. Earlier approvals and offline tests remain historical facts; this is a
   course correction, not a claim that all earlier work was unauthorized.

### Why move on, and what remains useful

The marginal work was improving inventory coverage rather than delivering a
small, understandable answer. Broader evidence also increases review burden and
the amount of private metadata retained. More tests or additional readers cannot
resolve that mismatch. We therefore stop investing in broader collector coverage
instead of treating sunk implementation effort as a reason to continue.

Preserve the source, regression tests, private reports and historical verification.
Retain the useful principles: exact evidence, explicit unknowns, read-only scope,
host/container separation, and observation distinct from desired intent and
execution authority. Nothing is deleted, disabled or represented as deployed.
The recorded 343 passing tests and two skips qualify the previous offline scope;
they neither establish product fit nor finish real-host/profile acceptance.

### Disposition and resumption boundary

| Item | Current disposition |
|---|---|
| Existing collector and tests | Preserved; no implementation change in this closeout |
| Fresh report-03 / further coverage reruns | No longer a requested next action under this plan |
| Profile-driven collector integration | Not pursued as the next step; does not solve overscope |
| Readable proposal and reviewed real YAML | Not completed; broader goal retained without an inventory-completeness prerequisite |
| Replacement scanner or agent orchestrator | Not approved or designed here |
| Installation, migration, sync, settings or cloud work | Not authorized by this decision |

If collection is reconsidered later, first name one concrete user question and
the few facts needed to answer it. Any proposal should state its exact read scope,
small output and stopping condition; unknowns should remain unknown rather than
triggering automatic search expansion. This is a lesson and reconsideration
criterion, **not a new approved implementation plan**. No successor task has been
chosen; the immediate action is to save this decision and the session checkpoint.

## Historical plan and evidence — superseded for continuation

The remaining sections preserve the earlier intent, approvals, implementation
receipts and unfulfilled deliverables. Their future-tense instructions and
"Pending" gates are historical and do not override the decision above.

## Goal
Turn observations of the existing workstation into a reviewed shared YAML profile, without installing, repairing, moving repositories, or deploying cloud resources.

## Earlier stopping point (historical)
- Last conversation: `20260916_043419_b58fc1`. The final agreement was targeted collection first, then a readable proposal; a new review interface is not a prerequisite.
- Checkpoint: `.agents/memory/sessions/20260916_045559_8a7a617c.md`.
- Current branch: `devcontainer`; six tracked modifications and two untracked entries preserve the targeted-collection work. No commit or push performed during this review.
- Existing `configs/private/host-inventory.json`: private mode 0600; 1,756 package records, zero collected repositories/environments, incomplete coverage. Zero observations do not establish absence.
- At that checkpoint, `configs/private/host-software-02.json` had not yet been collected. The user subsequently collected it and it was inspected and validated in this conversation.
- The checkpoint records 324 passing scoped tests and two skips, plus a synthetic ten-command pipeline and independent source review. These are previous verification results, not tests rerun for this status review or proof of host/cloud acceptance.

## Original collection sequence (completed through report inspection)
1. On the physical workstation, as the ordinary user in the IsaacAutomator repository, run:
   `./collect-host-metadata --plan --scope software --report-name host-software-02.json`
2. Review that scope, then explicitly collect:
   `./collect-host-metadata --collect --scope software --report-name host-software-02.json`
   Do not use sudo or redirection. Preserve the original inventory. If the filename exists on the host, use a fresh report name. Do not run this in the devcontainer as a substitute for host observations.
3. After collection succeeds, inspect the private report in the existing shared checkout. Validate the report and examine coverage before interpreting missing entries. Present a concise proposal organized as observed facts, proposed choices, unresolved questions, and decisions needed.
4. Review workspace naming, Isaac Sim, repositories, and environments together. Treat package inventory as reference evidence, not automatic installation intent. Keep unsupported or uncollected facts unresolved. Request only narrowly scoped follow-up evidence where necessary.
5. Translate reviewed decisions into a private draft shared YAML. Validate the schema and exercise local-installer/cloud-Ansible render and dry-run paths offline. Report unsupported mappings and unresolved requirements explicitly; draft intent is not install approval.

## Boundaries and known gaps
- Software-only inventory deliberately omits machine/system-package records. Reports are not automatically unioned; previous-report handling preserves review continuity, not all facts from earlier snapshots.
- The host supplied `6.0.1-rc.7+release.42383.32955d8d.gl` from `~/IsaacSim/VERSION`. The collector incorrectly rejected the combined prerelease/build suffix. Preserve the exact version; do not infer it from target-stack instructions or relabel it a final release.
- Existing repositories, environments, host settings, and credentials remain untouched.
- No UI redesign, installer apply, synchronization, or paid cloud acceptance is part of this immediate continuation.
- If evidence reveals a collector defect, reproduce it with synthetic fixtures in `src/tests/installer_host_collector.test.py` or `src/tests/installer_host_inventory.test.py`, then make a narrow fix and independently review it before requesting another host run.

## Next deliverable
A readable, evidence-backed proposal for the user's actual setup, followed by a reviewed and validated draft YAML—not another architecture plan or an installation.

## Approved gap-resolution work

The user approved implementation and offline testing, followed by a new host-run
collection. **BoredEngineer alone is the intended workspace**. The lowercase
`boredengineering` tree was created by mistake by isaac-installer; exclusion does
not authorize deletion, migration, or treating it as a desired release environment.

| Requirement | Implementation / consumer | Acceptance evidence | Status | Real-operation gate |
|---|---|---|---|---|
| Exact BoredEngineer-only discovery | Explicit `--workspace-name` in portable CLI, repository wrapper, report/importer | Synthetic included/excluded trees and plan/collect transport | Implemented; offline tests pass | Next host scan by user |
| Full Isaac Sim version | Bounded VERSION parser, importer, and shared desired-profile validator | Exact prerelease/build round-trip through review, YAML and local rendering; Ansible retains version but explicitly refuses it | Implemented; offline tests pass | Next host scan by user |
| Conda Python/package gaps | Prioritize Python records, bounded larger JSON cap, valid underscore package names | Large records, exact cap/global-budget boundaries, Python priority and legacy importer grammar | Implemented; offline tests pass | Next host scan by user |
| Oversized dist-info descriptions | Bounded metadata-header reader, no full-body requirement | LF/CRLF, stable EOF, duplicate/folded fields, truncated header, preservation controls | Implemented; offline tests pass | Next host scan by user |
| Editable-install relationships | Opt-in `--include-editable`, metadata-only evidence and strict importer validation | Both managers, executable `.pth`, external/symlink refusal, malformed input and terminating size truncation | Implemented; offline tests pass | User reviews expanded scan scope |
| Offline integration and independent review | Confined synthetic runner, importer/proposal and existing renderer paths | 345 tests run, two existing skips; synthetic acceptance and separate code/security + completeness reviews pass | Complete offline | No live changes needed |
| New host evidence and comparison | Fresh `host-software-03.json`, preserve earlier reports | Validate actual new report and compare remaining gaps | Pending | User must run collector outside devcontainer |
| Readable proposal, then shared YAML | Observed facts → proposed choices → user review → local/Ansible render | Actual evidence and reviewed decisions, offline validation | Pending | New host evidence and user intent review; no install permission implied |

Do not declare the last two rows complete from synthetic tests. No mounts, VS Code
settings, runtime imports, environment activation, package-manager commands,
cloud deployment, or workstation changes are authorized by this continuation.

### Consumer limit discovered during real offline rehearsal

The first end-to-end run reached review and exposed the shared profile validator's
plain `X.Y.Z` restriction. A regression test failed for combined suffixes before
the validator was fixed. The exact host version now survives desired-profile YAML.

The current Ansible standalone role independently requires **exactly final
`6.0.1`** (`src/ansible/roles/isaacsim-source/tasks/standalone.yml:6`). Its renderer
accurately refuses the prerelease, retaining the full version and identifying
`components.sim.source.version` as unsupported. This is not a successful Ansible
deployment or check-mode run. No version relabeling or native-role bypass was
introduced. A source URL/checksum and any desired-version change remain review
decisions; discovery does not establish archive availability or compatibility.

### Refreshed verification

- Final parent runs: **345 tests run, 343 passed, two existing skips, zero
  failures/errors**, across 21 non-overlapping suites. This is the scoped
  discovery/profile suite, not every test in the entire repository.
- Scoped collector/importer: `/tmp/isaac-step1-b_w_5ba5/results.json` (77 tests).
- Broader profile/discovery consumers: `/tmp/isaac-step1-0gh0aj0o/results.json`
  (268 tests, two skips).
- Refreshed synthetic acceptance:
  `/tmp/isaac-gap-synthetic-hn62_k69/confined/receipts/receipt.json`.
  Copied wrapper/collector hashes match the final source. It checks both
  renderer paths (including expected Ansible rejection) and the local
  profile-only installer dry-run; it performs no Ansible check-mode execution.
- Syntax and `git diff --check` pass; independent first-slice probes also pass.
- The initial reviews found five defects (inclusive cap, Python priority,
  legacy Conda grammar, no-progress truncation, malformed optional containers).
  All have regression tests and were fixed in a separate agent context.
- Replay instructions and aggregate evidence:
  `.agents/references/isaac-installer/verification/gap-collection/`.
- Final independent code-review closure and refreshed completeness verdict both
  **pass**, with reviewed source hashes rechecked against the final tree. Their
  full JSON verdicts and review-fix evidence are saved alongside `verification.json`.
- Actual host collection/proposal/YAML remain separately gated. The next commands
  are the BoredEngineer-only, opt-in editable scope documented in
  `isaac-installer/docs/host-discovery.md`; use fresh `host-software-03.json`,
  ordinary user, physical host, no sudo or output redirection.
