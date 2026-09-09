# GCP Artifact Registry Implementation Plan

Status: implemented and locally verified on 2026-09-09. No cloud resources or images have been created; live acceptance remains separate.

Follow-on scope: [optional provider selection and Hugging Face](optional-distribution-plan.md).
This ledger records the original GCP implementation and its verification totals;
consult the follow-on ledger for subsequent changes and current verification.

## Goal and boundaries

Add optional private Docker image distribution for GCP workstations without tying shared image lifetime to disposable GPU VMs. Terraform owns infrastructure/IAM, Ansible owns keyless pull configuration and digest-pinned image consumption, and a separately authorized publishing workflow owns image builds/uploads. This does not mirror datasets, models, bind-mounted source, or the complete host stack.

The user requested planning AND implementation. The plan-only skill's execution stop does not apply to this request. No commits, pushes, live applies, API activation, image publishing, private-profile changes, or workstation changes are authorized by this implementation task.

## Context loaded

- AGENTS.md, CLAUDE.md, README.md, CONTRIBUTING.md.
- `.agents/references/INDEX.md`, host compatibility plan, cloud image baking plan, and dynamic security/storage guide.
- `.agents/skills/isaac-automator/session-memory/SKILL.md`.
- Profile normalization (`src/python/config.py`), deployment rendering (`src/python/deployer.py`), GCP Terraform root/ovkit, Ansible inventory and role dependencies.
- Environment-profile-management and test-driven-development skills.

## Architecture / configuration contract

1. Separate reusable Terraform root: `src/terraform/registry/gcp/`. An explicit operator Terraform invocation creates a repository in its OWN durable state; it is not called by workstation deploy/destroy. Support optional existing CMEK key, repository-scoped publisher membership, API enablement with disable_on_destroy=false, and prevent_destroy. No automatic image cleanup/deletion policy.
2. Workstation GCP root consumes an existing repository, grants its dedicated VM service account repository-scoped reader access, and supplies cloud-platform scopes. Enable registry API only when opted in. Repository project may differ from VM project; callers need IAM rights in both. Disabled mode adds no registry resources.
3. Optional top-level YAML `artifact_registry`: `enabled` (boolean, default false), `project`, `location`, `repository`, `images` (mapping of workload name to fully qualified sha256 image digest). `images.gr00t` additionally selects the existing containerized GR00T service; other images are pre-pulled only, not launched. Empty image mapping is allowed for registry authentication-only setup.
4. Normalized Terraform parameters: `enable_artifact_registry`, `artifact_registry_project`, `artifact_registry_location`, `artifact_registry_repository`. Python retains `artifact_registry_images` as a mapping; Ansible receives `artifact_registry_images_json` (JSON text, which InventoryManager may already decode to a mapping). Only GCP accepts enabled configuration. Validate mappings, names, booleans, matching repository and digest references; never silently fall back on malformed profiles.
5. Ansible configures short-lived metadata-based Docker authentication for root (systemd) and the resolved SSH user, preserves unrelated Docker configuration, and pre-pulls immutable digests before GR00T starts. No service-account key or embedded token. Do not execute unapproved images as a health check. GPU/workload health remains a separately authorized live verification step.
6. Preserve existing behavior when disabled, including Packer/non-GCP paths. No new generic enterprise default dependencies and no personal identifiers in public examples.

## Implementation tasks

### 1. Terraform registry lifecycle and identity
- Add isolated registry root, outputs, README, and tests.
- Add GCP workstation opt-in variables, reader IAM, dedicated-SA plumbing, and module dependency ordering.
- Write and run a failing offline test before implementation; run fmt/validate and mocked plans where supported. Never use live apply or refresh against existing deployment state.

### 2. Ansible keyless consumption
- Add `artifact-registry` role defaults/tasks and tested helper/configuration logic as necessary.
- Insert role after Docker setup and before container consumers.
- Wire GR00T image mapping to container mode without unnecessary native environment setup; ensure service changes restart the correct unit.
- Test config merge/idempotence, malformed inputs, metadata authentication protocol, disabled behavior, and service template integration without accessing real metadata or running Docker on the host.

### 3. Profile-to-deployment tracer bullet
- Add regression tests in `src/tests/artifact_registry.test.py`: profile -> params -> Terraform variables -> Ansible inventory.
- Implement normalization in `src/python/config.py` and/or a small dedicated module, with GCP-only consumption in deployer.
- Preserve old profiles and add a generic disabled/example profile and documented schema. Run existing unit suite (`PYTHONPATH=. sh src/tests/run_all.sh`).

### 4. Verification and continuity
- Inspect aggregate diff and run relevant Terraform, Ansible, Python tests; record actual results and limitations.
- Add operator/architecture guide under `.agents/references/docs/` and index the plan and guide.
- Add bounded cross-links/status notes to host compatibility, security/storage and image-baking references; distinguish implemented support from full stack parity.
- Save dated session checkpoint and update `.agents/memory/INDEX.md`.

## Risks / live acceptance gate

- A local Docker image ID is not a registry digest. Publishing licensed or private images requires a separate explicit review and permission.
- IAM propagation, cross-project policies, metadata identity, network/DNS egress, CMEK region/access, and actual GPU compatibility need live verification after authorization.
- Artifact Registry is IAM-private; this does not create a VPC Service Controls perimeter or eliminate NAT/public egress for other registries.
- Shared state and CMEK must outlive workstations. Removing a protected Terraform resource block can bypass lifecycle safeguards; review shared-stack changes carefully.
- Existing historical references include broad readiness/security claims. This feature must not repeat them as verified facts.

## Execution ledger

- Context and design: complete.
- Terraform/profile/Ansible implementation: complete for the documented optional GCP registry contract, not full workstation parity.
- Review history: two bounded fix cycles resolved metadata-restore validation, failed-constructor persistence (including Alicloud after `super()`), a privileged Docker-config race and asymmetric GR00T transitions. Destructor autosave was removed; explicit workflow saves retain valid metadata, including resolved GCP scheduling/backup values. Registry tests deny unexpected external calls and mock import-time public-IP/local gcloud-default probes.
- Final Python independent review: approved. Failed-constructor preservation, explicit persistence, saved-state repair and cloud boundaries were rechecked. No security/logic blockers remained in either final reviewer verdict.
- Final current-workspace suite: **139 tests passed**, exit 0 (`PYTHONPATH=. sh src/tests/run_all.sh`). Includes 18 profile/state tests, 27 Ansible/helper tests and 2 Terraform source guardrails. Existing TUI ResourceWarning diagnostics are not hidden; see baseline caveat below.
- Terraform isolated provider validation and mocked plans: 17 passed, no existing state or live resources touched. Live IAM/API readiness remains unverified.
- Ansible independent re-review: approved after cycle 1. All 27 role/helper tests ran without skips, including non-root module-wrapper integration, adversarial path swaps, mode transitions, changed-digest handlers and loopback proxy/redirect checks.
- Ansible workstation syntax check, Terraform formatting, Python compilation, added-code security scan and `git diff --check`: passed. New/changed relative documentation links checked: 17, none broken. Lint tools/Black were unavailable; no lint pass is claimed.
- Baseline caveat: clean detached HEAD has an unrelated TUI ImportError because `.gitignore` excludes `src/tui/screens/__init__.py`. The baseline's other 91 tests passed; supplementing only that unchanged local initializer makes its TUI test pass with ResourceWarnings. This task does not change the TUI/ignore rule. Current-workspace suite results are not proof of clean-checkout TUI readiness.
- Live GCP deployment / image upload: not authorized, not performed.
- Continuity checkpoint: `.agents/memory/sessions/20260909_010737_16cf40c4.md`; related security/storage, host-compatibility, Ansible-testing and image-baking references are cross-linked. No commits or pushes were made.
