# Workload-first workstation consolidation proposal

**Status:** Recommendation for discussion, not an approved implementation plan or authorization for paid infrastructure or physical-host changes.

**Goal:** A user can select a reviewed robotics workload, provision a private GCP RTX PRO 6000 workstation, connect through IAP from Isaac9s or the CLI, run the workload, preserve its results, and deliberately stop or destroy the resources without losing required data.

**Architecture:** Keep Terraform for infrastructure and Ansible for cloud configuration. Keep the local installer as a separate executor of shared software intent. Make Isaac9s and the CLI clients of the same operational behavior, not parallel implementations. Reuse existing code before introducing new layers.

**Stack:** Existing Python CLI, Textual TUI, Terraform, Ansible, GCP IAP/GCS, selected SSH/rsync transfers, and optional source-attributed evidence graph.

## Basis and limitations

This proposal uses direct public-source inspection and the current conversation. `./knowledge-graph status` returned stale; graph retrieval and automatic reindexing were not performed. No new runtime tests or cloud checks establish the deployability of this proposal.

Concrete integration examples:

- `src/tui/backend.py:40-73` transports a subset of CLI options, blocks non-local Terraform backends, hardcodes latest software and a single GCP GPU, and supplies replacement/public-ingress arguments. These need explicit intent and transport verification; they do not by themselves establish effective public exposure under every security profile.
- `src/tui/screens/remote.py:33-49` builds direct endpoints; its security labels are fixed text, not verified instance security posture. IAP-aware client launching is not established by those labels.
- `src/python/gcp.py` already has SSH/IAP tunnel helpers. Trace callers and lifecycle behavior before extracting or replacing them.
- `src/python/file_transfer.py` already has structured SSH/IAP endpoints and explicit one-way transfer semantics. Its module documentation correctly distinguishes transfer from backup.
- `src/python/remote_development.py` contains selected synchronization planning and validation. Do not conflate an offline plan with active synchronization.

These are examples motivating consolidation, not an exhaustive audit. Previously developed features must be reconciled against their plans rather than silently dropped.

## Product boundary

Core: private GPU workstation, workload software intent, IAP access, active persistent disk, GCS data/backup storage, optional remote Terraform state, selected local/cloud transfer, lifecycle and understandable status.

GCP is the first end-to-end acceptance target, not permission to delete AWS/Azure/Alibaba support. Preserve their interfaces and regression coverage while sequencing verification.

Not a default dependency: Nucleus, Filestore, Farm, DeepSearch, public application load balancers, broad host inventory, graph infrastructure, shared ledgers or automated drift systems. Preserve useful optional work and mark its status rather than removing it without review.

Cost estimation remains optional and follows the selected C3X direction; do not introduce another cost engine or make quotations a deployment prerequisite. Paid acceptance still requires an explicit budget and teardown scope.

## Workstreams and ordering

### 1. Reconcile promises before changing architecture

Create a small capability matrix for deploy, inspect, connect, transfer, backup, restore, lifecycle and workload validation. For each record CLI support, TUI support, configuration transport, tests and live acceptance evidence. Add states such as implemented/offline-tested/live-verified/unsupported; do not reduce everything to done/not-done.

Review the existing plans and record retained, superseded, optional and pending requirements. Correct the studio diagram and current user guide to the private-workstation architecture, clearly separating historical plans from active recommendations. No feature deletion is implied.

Acceptance: every feature the first release claims has an entry and an evidence source; no green READY label from a placeholder or merely successful process launch.

### 2. Establish one resolved deployment intent

Reuse `src/python/workstation_profile.py`, `profile_adapters.py`, `backend_selection.py`, `deployment_manifest.py`, `deploy_command.py` and `deployer.py`. Clarify existing responsibilities before creating another schema.

Software/workload intent, machine/security choices, Terraform backend and data policy are related but distinct. Preview exact resolved versions/sources, machine/GPU count, project/zone, access route and retention behavior. Preserve provenance of defaults and overrides. Reject unsupported combinations before provisioning.

TUI and CLI should resolve the same input identically. Keep current command wrappers working; do not demand a new daemon or HTTP API. Where subprocesses are the appropriate boundary, use structured arguments and machine-readable results rather than parsing display text.

Acceptance: contract tests prove selected intent reaches Terraform and Ansible without hardcoded replacement values or silent fallbacks. Software preview is demonstrably the software deployed.

### 3. Complete one private GCP deployment path

Wire private networking/IAP, explicit instance provisioning model, selected software, disk and GCS permissions using existing mechanisms. Implement optional GCS Terraform backend support end-to-end in the TUI rather than simply removing its current guard.

Account for required outbound package/model downloads from a private VM; no public IP is not synonymous with no egress needs. Verify selected IAM/SSH identity paths instead of assuming IAP transport alone grants login.

Acceptance: offline contracts and infrastructure validation first; separately approved live acceptance verifies a private VM and the actual chosen robotics workload. Installation success is not workload success.

### 4. Make Connect a complete operation

Reuse and consolidate existing GCP SSH/IAP helpers, the noVNC path, connection metadata and the TUI modal. Own the tunnel process, detect readiness, handle port conflicts, explain authentication failures, and close only owned tunnels.

Support the actual placement of the CLI/TUI: inside a devcontainer, localhost and installed desktop clients may not be on the user's desktop. Show accurate tunnel/client instructions when automatic local launch is unavailable.

Prioritize SSH and a usable desktop route. IAP TCP forwarding is not a general UDP tunnel; do not promise every streaming protocol works through it. Verify NoMachine/live viewport separately from noVNC's 2D desktop behavior.

Acceptance: select a workstation and connect without guessing project, zone, IP or local port. Stop and error paths leave no unidentified tunnel processes. UI security labels reflect evidence, not constants.

### 5. Close the data durability loop

Reuse selected transfer, synchronization and remote-development code. Keep active VM disk, local source, GCS datasets/artifacts, backup versions, Terraform state and controller connection metadata distinct.

Define source of truth and direction for each selected path; preserve exclusion, conflict and overwrite safeguards. Do not copy environments, home directories, secrets or live databases indiscriminately. Use consistent database exports if explicitly included.

Separate storage from backup, transfer from synchronization, and configured backup from a tested restore. Specify retention, last successful transfer/backup, restore target and what survives stop, destroy and controller loss. A preemption hook alone is not a complete backup strategy.

Acceptance: a selected output is backed up and restored to an isolated destination with content verification. No physical-host overwrite or cloud test without explicit permission. Destruction clearly discloses retained disks/buckets and ongoing storage cost.

### 6. Consolidate Isaac9s around the same operations

Expose actual capabilities, lifecycle state, operation progress and actionable failures. Start with fleet, deploy, connect, logs, transfer and stop; add backup/restore controls only once their underlying operations are verified.

Refactor at points where UI and CLI disagree. Prefer small operation-specific adapters and pure validation functions over a new general orchestration framework. Keep long-running work cancellable and distinguish cancelling a client process from stopping a VM or rolling back resources.

Acceptance: Textual tests verify exact command/intent transport and failure handling with isolated state and mocked external effects. No UI success message can be satisfied merely by opening a URL or writing intent YAML.

## First release acceptance journey

1. Choose an explicit workload profile and deployment target.
2. Preview software, access, compute, storage and retention choices.
3. Provision the private workstation through CLI and verify equivalent TUI transport.
4. Connect via IAP and inspect the workload environment.
5. Run a named simulation/training/policy-evaluation case and produce an expected artifact.
6. Transfer and back up selected outputs; verify restore separately.
7. Stop/start and confirm the intended persistence boundary.
8. Deliberately tear down test compute; verify remaining resources and disclosed retained-storage costs.

The workload, expected output, input/model availability and acceptable runtime must be selected before live acceptance. Do not invent a generic GPU smoke test as a substitute.

GCP Flex-start acceptance retains the user's separate `g4-standard-48` and `g4-standard-384` targets; success on one does not certify the other. Run sequential, explicitly budgeted experiments with verified cleanup, not both by default.

## Validation and refactoring discipline

- Characterization/regression tests before moving shared behavior; test-first fixes for broken transport and lifecycle semantics.
- Start with existing tests such as `src/tests/profile_adapter_transport.test.py`, `workstation_profile.test.py`, `terraform_tui.test.py`, `isaac9s.test.py` and `novnc_iap.test.py`. Confirm runner/environment and side effects before execution; some UI tests write exports or run checks.
- Separate pure offline tests, local sandbox integration tests, cloud control-plane checks and paid GPU workload acceptance. Report each independently.
- Preserve compatibility wrappers, existing user configuration and local robotics progress. Deprecate with migration guidance, not abrupt deletion.
- Require independent review at each slice. Parallelize independent contract tests/documentation/review, not simultaneous rewrites of the same orchestrator.
- Keep docs and capability status alongside implementation. Update `src/tui/README.md` when controls change.
- Use current bounded graph evidence for relevant relationship questions once an index refresh is explicitly authorized. Evaluate its benefit separately; Neo4j is not a deployment dependency.

## Recommended first slice

Start with the capability/requirements reconciliation and then make **select an existing private GCP workstation → connect through IAP** reliable in both CLI and Isaac9s. This gives a concrete user-facing improvement while revealing the shared connection and subprocess contracts. In parallel, review profile transport and data durability requirements without changing the host or provisioning resources.

This ordering does not declare the larger plan finished after Connect. The release remains the full deploy → connect → workload → preserve → restore → lifecycle journey above. Detailed implementation tasks, exact tests and permission gates should be agreed per workstream before execution.
