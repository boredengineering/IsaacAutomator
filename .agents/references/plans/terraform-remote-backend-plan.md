# Opt-in Multi-Cloud Terraform Remote Backend and Drift Management Implementation Plan

> **For Hermes:** Use the subagent-driven-development skill, if available, to implement this plan task-by-task. Otherwise use focused `delegate_task` workers with independent specification and code review. Read the repository rules first. The user subsequently authorized implementation; that does not authorize live deployment, migration, workflow activation, commits, pushes or environment-setting changes.

**Goal:** Let users explicitly choose local state or a properly configured remote Terraform backend for AWS, GCP or Azure, with safe deployment, lifecycle operations, migration and recovery from another controller; then offer opt-in drift detection and controlled correction through the local CLI, generated GitHub Actions or selected cloud-native services.

**Architecture:** Preserve local state as the default. Introduce a validated backend descriptor and one backend-aware Terraform runner used by every deployment/lifecycle path. Provision durable backend infrastructure separately from workstations, isolate each Terraform operation, and keep recovery metadata distinct from Terraform state and VM data. Reuse that runner for drift reports and approved remediation; scheduling systems are adapters, not alternative Terraform owners.

**Tech stack:** Existing Python/Click CLI, Terraform, AWS S3, GCP Cloud Storage, Azure Blob Storage, Textual TUI, Python unittest/mock and provider-mocked Terraform tests. Prefer Python standard library and existing cloud CLIs; introduce dependencies only after checking packaging and supported environments.

**Status:** Implementation started with the fail-closed safety and offline backend/runner foundation slice. This is not a completed remote-backend product. Source baseline reviewed on 2026-09-10, branch `devcontainer`; line references below describe that baseline and must be rechecked before editing.

**First-slice scope:** `state-backend validate --cloud CLOUD --config PATH` is available with public examples in `configs/state-backends/`. BackendSpec adapters/version checks and an isolated runner are implemented as foundations. The runner's provider-free local test verifies state persistence through three disposable contexts; remote mutations remain disabled. Legacy destroy/output safety, explicit opt-in and host-wrapper exit-status/headless regressions are covered separately. See `configs/state-backends/README.md` for available behavior and limitations.

**Remaining gates:** Task 2 provider/bootstrap schema and lockfile validation, production call-site integration of Task 4, Task 5 bootstrap, authenticated portions of Task 6, and Tasks 7–23 are not delivered by this first slice. Task 3's saved-descriptor conflicts fail closed rather than enabling attachment/migration. Task 13 has configuration examples only, not completed operator/TUI documentation. No remote deployment, live IAM/locking acceptance, state migration, drift workflow or shared graph publication has been run. The installed Terraform 1.8.5 is sufficient for the local fixture, not the conservative remote >=1.10.0 feature gate; no binary or image setting was changed.

**Drift extension:** Added following the user's request on 2026-09-10. Provider and GitHub capabilities in section 4.6 were checked against official documentation; numbered references resolve to the Sources section. There is no `.github/` directory in the inspected checkout. Templates, generators, cloud monitors and corrective actions below are proposed deliverables, not files or services activated by this planning update.

**Shared evidence extension:** Section 11 adds a researched, optional remote evidence-ledger architecture and Tasks 19–23 for discussion and a separately approved pilot. It preserves the canonical RDF model and local agent caches. It is not a decision to deploy Neo4j remotely, synchronize personal agent memories, or make a graph service a dependency of Terraform/drift operations.

---

## 1. Scope, defaults and invariants

### In scope

- Local, GCS, S3 and Azure Blob (`azurerm`) Terraform backends.
- Explicit user selection through CLI, profiles and the deploy wizard.
- Create-new and use-existing backend infrastructure workflows.
- Backend authentication, scoped authorization, encryption, versioning, locking and recovery.
- Deploy, plan, outputs, SSH-key export, inventory, start/stop, repair, destroy, import/attach and TUI consumers.
- Local-to-remote, remote-to-local and remote-location migration with safety checks.
- A fresh controller attaching to an existing remote-managed deployment.
- Offline regression coverage and separately authorized live acceptance for each provider.
- Drift detection for backend protections, Terraform-managed workstation resources and controller identity; separate integration points for in-VM software checks.
- A common drift report/remediation contract with on-demand checks, optional scheduling, notifications, suppressions and failed/missed-check monitoring.
- Inert, configurable GitHub Actions templates and a user-invoked generator; separate explicit installation/activation and OIDC setup.
- Evaluation and optional adapters for AWS Config/EventBridge/CodeBuild, GCP Asset Inventory/Cloud Scheduler/Cloud Run, and Azure Policy/Resource Graph/Container Apps Jobs or Automation.

### Out of scope

- Copying the local Neo4j evidence graph to a VM or synchronizing graph databases.
- Backing up VM disks, datasets, model weights or training results through Terraform state.
- Changing the robotics software stack or installer/Ansible parity work.
- HCP Terraform remote execution, Kubernetes/Consul backends, Alibaba remote state, or unrestricted cross-cloud backend combinations in the first release.
- Automatically migrating the separately managed ECR/Artifact Registry states.
- Automatic activation of workflows, cloud policy remediation or recurring checks merely because remote state was selected.
- Unrestricted self-healing, blanket Terraform auto-apply, silent drift adoption, or multiple controllers enforcing incompatible desired values on the same resource attributes.
- Automatic sharing of private agent memories, conversations, credentials or operational state. Shared evidence scope is opt-in and defined separately in section 11; publishing agent hypotheses as verified facts is prohibited.

### Non-negotiable behavior

1. Omitted configuration means local state; local operation must not create remote storage or require additional cloud authentication for state.
2. Remote storage is an independent choice from security tier. Selecting team/enterprise must not silently provision or migrate a backend.
3. New deployment: an explicit remote profile block or explicit remote CLI choice expresses opt-in. Missing destination information is a configuration error in noninteractive mode, not an implicit fallback.
4. Existing deployment: its saved backend identity wins unless the user explicitly invokes migration. Editing a profile or selecting `--state-backend local` must not redirect existing resources to a new empty state.
5. Backend authentication/network/permission failures are errors, never evidence of an empty deployment. Never silently fall back to local state or a stale snapshot.
6. Never report destroy success or delete controller files until destruction is confirmed against the correct authoritative state.
7. Workstation destruction never deletes backend buckets, storage accounts, containers, keys, registry repositories or unrelated state objects.
8. Never put credentials into profile YAML, backend arguments/files, recovery manifests, logs or source control. Terraform state itself can contain sensitive values and must be treated as secret-bearing.
9. Remote backend storage does not imply remote execution. Terraform still runs on the controller.
10. State migration, backend creation and live verification require separate explicit user approval. Preserve the existing uncommitted session checkpoint files.
11. Detection is not correction: report by default. Cloud-native remediation and scheduled Terraform apply are disabled unless a separately approved, bounded correction policy explicitly enables them.
12. A denied, stale, partial, timed-out, skipped or never-executed check is not a clean result. Expose evidence coverage and last-success age; lock contention is not proof of drift.
13. Generated Actions YAML is inert until the user reviews and installs it. Generating a template never grants IAM, configures GitHub environments, commits, pushes or enables schedules.

## 2. Source-backed baseline and gaps

| Area | Current behavior | Required correction |
| --- | --- | --- |
| Initializer | `src/python/deployer.py:654-690` chooses only local/GCS, writes an override and calls `init -reconfigure` | Typed provider-aware initialization, pinned identity and explicit migration |
| Profiles | `src/python/config.py:180-213,270-305` assigns GCS-style buckets; backend/locking fields are not normalized | Validate and transport a complete backend specification |
| Cloud roots | `src/terraform/aws/main.tf:3`, `src/terraform/gcp/main.tf:3`, `src/terraform/azure/main.tf:4` declare local | Preserve local default; generate overrides in private run directories |
| Bootstrap | Only `src/terraform/bootstrap/gcp/main.tf` exists | Harden/test GCP; add independent AWS and Azure bootstrap roots and orchestration |
| Outputs | `src/python/utils.py:112-131` reads local `.tfstate` only | Read authoritative remote outputs through the runner; typed errors |
| Post-apply | `src/python/deployer.py:588-652,747-751,792-813` consumes those outputs | Verify outputs before inventory/key/instruction generation |
| Destroy | `destroy:78-172` detects cloud from local state, can skip Terraform and still delete files/report success | Fail-closed identity/state checks; confirmed destruction before cleanup |
| Repair | `repair:82-143` hardcodes local initialization and local outputs | Use saved descriptor and shared runner |
| Discovery | `src/python/utils.py:84-109` and `src/tui/backend.py:38-86` discover local directories | Local cache of explicit remote attachments, not fake `.tfstate` snapshots |
| Import | `import` constructs local state from discovered resources | Distinguish attach-to-existing-state from importing unmanaged resources |
| Workspace isolation | Provider roots share overrides; `Dockerfile:123-128` sets global `TF_DATA_DIR=/opt/tf-data` | Per-operation root and namespaced container-local Terraform data directory |
| Dry-run | `src/python/deployer.py:665` forces local backend | Separate offline validation from an accurate remote speculative plan |
| Registry exception | `src/terraform/registry/aws/main.tf` uses S3, with separately supplied backend prerequisites | Do not claim this implements workstation S3 support |

Historical audit evidence, not implementation acceptance: 22 deployer tests and 40 CLI tests passed; 11 temporary mocked probes confirmed the current backend/output behavior. A separate synthetic/mocked destroy probe confirmed false success when local `.tfstate` is absent. No real backend was opened. These checks need permanent regressions below.

## 3. Proposed user experience and configuration contract

Except for the offline validation and explicit selection foundation noted above, command names and workflows in this section remain **proposed**. Final help and tests must use the same names. A validated remote selection is currently refused for execution, never silently redirected to local state.

### 3.1 Commands

Add a top-level `state-backend` Click command with subcommands:

| Proposed command | Purpose and side effects |
| --- | --- |
| `state-backend validate --cloud CLOUD --config PATH [--terraform-version VERSION]` | Available: offline schema/cloud pairing and optional supplied-version compatibility validation; no cloud or Terraform calls |
| `state-backend bootstrap plan --config PATH` | Show backend infrastructure changes, identity, permissions and costs; cloud reads/refresh require authorization |
| `state-backend bootstrap apply --config PATH --yes` | Explicitly provision approved backend infrastructure, separately from any workstation |
| `state-backend doctor --config PATH` | Authenticated read-only checks; distinguish unknown from denied/missing |
| `state-backend doctor --config PATH --write-probe --yes` | Explicit write/delete/locking probe on a reserved disposable key, never production state |
| `state-backend status DEPLOYMENT` | Show backend identity, attachment and freshness without printing state/secrets |
| `state-backend attach --config PATH --manifest PATH` | Attach an existing state to this controller; no resource import/apply |
| `state-backend migrate DEPLOYMENT --to-config PATH` | Plan migration, then execute only with explicit confirmation; no ordinary deploy-time migration |
| `state-backend detach DEPLOYMENT` | Remove a local attachment only, with clear warning; never describe this as cloud destruction |

Add explicit `--state-backend local|gcs|s3|azurerm` and `--backend-config PATH` to deployment. Use a generic backend configuration file rather than a large matrix of cloud-specific CLI flags. Existing `--state-bucket`/`ISAAC_STATE_BUCKET` become deprecated GCP-only compatibility inputs; see migration policy below. An explicit CLI source must not be overridden by Click defaults; use parameter-source inspection.

No automatic storage creation from `deploy-*`: direct users to the bootstrap workflow when the destination does not exist. Setup tooling may offer that workflow interactively but must require approval before applying it.

### 3.2 BackendSpec v1

Normalize profile `terraform_state` and backend configuration files into one schema:

```yaml
# Proposed public example; identifiers are placeholders, not real resources.
terraform_state:
  schema_version: 1
  backend: s3                    # local | gcs | s3 | azurerm
  namespace: studio-dev          # logical collision boundary, not a secret
  workspace: default            # only default supported in v1; reject others
  destination:
    bucket: example-state-bucket
    region: us-east-1
    owner_account_id: "123456789012"
    key_prefix: isaacautomator/v2
  locking:
    mode: native
    timeout_seconds: 120
  authentication:
    mode: ambient               # approved SSO/ADC/Entra/OIDC environment; no tokens
```

Provider destination fields:

- Local: omit destination; canonical state remains `state/<deployment>/.tfstate`. Derive paths within the configured state root; reject traversal/symlink escapes.
- S3: bucket, region, owner account, key prefix; native S3 lockfile strategy and encryption settings verified against the selected Terraform version. Optional existing KMS key identifier is nonsecret but authorization is separate.
- GCS: bucket, backend project, prefix; native backend locking. Optional existing CMEK identifier and required service-agent permissions.
- Azure: tenant/subscription context, resource group, storage account, container and key prefix; Entra data-plane authentication and native Blob lease locking. No storage account keys or SAS strings in the schema.

Reject wrong-provider fields, unknown keys, credentials, ambiguous duplicate blocks, unsupported workspace/locking choices, control characters and unsafe object/path names. Validate native-cloud pairing in v1: AWS→S3, GCP→GCS, Azure→Azure Blob, or any supported deployment cloud→local. Explicitly document cross-account/project/subscription storage within the same cloud and validate both target identities. Cross-cloud state storage is deferred rather than accidentally selecting GCS.

Persist a canonical descriptor alongside local deployment metadata. Include backend type, exact object identity, deployment cloud and immutable target scope, namespace, schema version and expected Terraform lineage once established. Store a digest of canonical nonsecret configuration to detect drift. Do not use profile names as durable backend identity.

### 3.3 Object identity and compatibility

Use a versioned logical identity:

`isaacautomator/v2/<namespace>/<cloud>/<target-scope>/<deployment>/terraform`

The adapter maps this to the actual GCS prefix/default-workspace object or S3/Azure object key. Test that translation against Terraform's documented naming rules; do not assume all backends append identical suffixes. Account/project/subscription and namespace are validated canonical components, not raw shell text. Same deployment names in different clouds/scopes must not collide.

Existing GCS v1 prefixes remain exactly where they are. Never rename state objects or adopt the v2 prefix automatically. Migration to another prefix is an explicit state migration.

Precedence for a new deployment: explicit CLI choice/config > explicit normalized profile choice > local default. An explicit CLI local choice overrides a profile's remote choice; discard the unused profile destination rather than combining them. Reject contradictions within the same precedence level, such as an explicit CLI `--state-backend s3` paired with a backend-config file declaring GCS. Table-test these cases. For an existing deployment: saved descriptor is authoritative; new conflicting settings trigger migration guidance.

A new deployment may only initialize an unoccupied state identity. If the selected object already contains managed state and this controller has no verified attachment/lineage, refuse before plan/apply and direct the user to `attach`. Matching names or configuration are not proof of ownership. Handle a competing creator between preflight and apply through backend locking and saved-plan lineage/serial validation; reject changed state rather than automatically adopting it.

Legacy policy:

- Preserve existing local deployments without a descriptor via explicit local discovery and conservative descriptor creation.
- Treat explicit legacy GCP `--state-bucket`, environment bucket or profile storage settings as deprecated remote intent after validation. Do not reinterpret them for AWS/Azure.
- New built-in team/enterprise selection alone must no longer imply remote storage. Warn about the changed behavior and show the required explicit choice.
- Existing metadata containing `state_bucket=auto` is ambiguous if the destination cannot be reconstructed/verified. Require operator confirmation of the exact existing location; do not guess or default to local.
- A backend error must not cause import, overwrite or a second managed state to be created.

## 4. Architecture and security boundaries

### 4.1 Shared components (new proposed modules)

- `src/python/terraform_backend.py`: schema, normalization, identity, provider adapters and safe backend argument generation. No resource provisioning during normalization.
- `src/python/terraform_runner.py`: isolated run context, version checks, init/plan/apply/output/state-read/destroy, locking, cancellation and redacted errors.
- `src/python/deployment_state.py`: descriptor persistence, typed deployment state/status, attachment, output retrieval and legacy local compatibility.
- `src/python/backend_bootstrap.py`: independent backend infrastructure setup, authenticated preflight and readiness reports.
- `src/python/state_backend_command.py`: Click command implementation used by the new `state-backend` wrapper.

Use subprocess argument arrays (`shell=False`) for new paths; never concatenate user backend fields into shell strings. Reuse the project's cloud login helpers through explicit authorization boundaries, but distinguish backend credentials from workstation provider credentials. Read-only commands must not start interactive login in headless sessions; return actionable authentication errors.

Typed results must distinguish unconfigured, configured-but-not-created, attached, reachable-empty, populated, permission-denied, unreachable, identity-mismatch, locked, partially-destroyed and unknown. An empty output string is not a substitute for any of these states.

### 4.2 Run isolation

Every operation uses a source-only staged Terraform root with its own backend override, preserved relative module topology and a private `TF_DATA_DIR`. Do not copy operational `.terraform`, state, inventories, credentials, auto-tfvars or arbitrary overrides from the repository. Copy vetted Terraform sources, pinned provider lockfile and needed relative modules; explicitly supply the approved deployment variables.

Use a container-local data/cache root on Docker Desktop to preserve the current macOS provider-execution workaround. Replace the global effective data directory with a namespaced directory per operation. Do not solve this by moving plugins back onto the bind mount. A shared provider cache needs its own concurrency-safe policy; do not assume sharing it is safe.

Acquire a controller-local lock for the canonical deployment/backend identity around local metadata changes and the complete operation. Terraform's remote backend lock protects state writes; it does not serialize all Ansible/SSH/cloud-CLI operations or competing backend selection. Document that direct start/stop versus destroy requires operational coordination across controllers; refuse lifecycle actions if an active Terraform mutation is detected, while acknowledging check-then-act limitations. Do not promise a global distributed workflow lock in v1.

Ignore/reject dangerous inherited `TF_CLI_ARGS*`, unexpected `TF_WORKSPACE`, `TF_DATA_DIR` and operator-generated backend overrides for managed runs. Preserve approved credential-provider environment and proxy settings without logging values. Refuse `-lock=false` for remote mutating operations. Do not use `init -upgrade` for routine lifecycle actions; upgrades must be deliberate and lockfiles verified.

### 4.3 Durable backend infrastructure

Separate bootstrap roots from workstation and registry roots. Bootstrap state must itself be preserved: initially a protected controller bootstrap state, then an explicitly migrated durable admin location where required. State bootstrap cannot rely on the resource it is about to create. Supply a documented chicken-and-egg recovery path and retain bootstrap ownership information independently of workstation attachments.

Three ownership modes: create managed infrastructure, use existing managed infrastructure, or use externally managed infrastructure. Never automatically take ownership of an existing bucket/account merely because the name matches. Use-existing validates required properties and reports gaps without modifying them.

| Provider | Storage and protection | Locking and identity |
| --- | --- | --- |
| AWS | Dedicated S3 bucket, public-access block, ownership controls, versioning, server-side encryption, TLS-only policy, no force deletion; optional existing KMS key | Native S3 lockfile after Terraform feature/version gate; narrowly scoped state/lock object access and restricted listing; short-lived AWS identity |
| GCP | Dedicated GCS bucket, uniform access, public-access prevention, versioning, soft-delete, no force deletion; optional CMEK | Native GCS locking; backend project/bucket IAM and service-agent KMS permissions explicitly checked |
| Azure | Dedicated or explicitly selected storage account and private-access container; HTTPS/TLS policy, anonymous access disabled, versioning/soft-delete where supported by chosen account configuration; no automatic account deletion | Native Blob lease locking; Entra/OIDC data-plane identity with scoped blob permissions; management-plane access only where required |

For all providers, distinguish permissions to create storage, access state/locks, read versions, restore versions and administer encryption keys. GPU VM service identities must not receive Terraform-backend access by default. Backend resources are controlled by the controller/admin identity, not installed on the workstation.

Use resource-level deletion protection where available and Terraform `prevent_destroy` for owned durable resources; explain that these do not prevent every console/API/config-removal deletion. Bound historical-version retention without expiring active state or interfering with lock objects. Avoid WORM/immutability rules on active lock/state objects unless validated to permit required updates/deletes. Backend retirement is a separate approved runbook checking all dependent states; workstation destroy cannot invoke it.

Validate ancestor ownership as well as separate Terraform roots. In Azure, backend storage must reside in a resource group outside workstation ownership: `src/terraform/azure/common/main.tf:2-5` manages the workstation resource group. Reject both create-new and use-existing storage inside that group; a provider deletion guard is not sufficient isolation. Apply the equivalent rule to any backend parent resource managed by a workload stack, and test teardown with unrelated backend resources present.

Private endpoints are optional hardening: validate DNS/network reachability from the actual controller and CI, without automatically widening public access. State backend region can differ from VM region and must be explicit.

### 4.4 Recovery metadata and secrets

Remote Terraform state alone does not provide all controller inputs. Maintain a versioned, allowlisted recovery manifest with deployment identity, exact backend identity, Terraform source revision, provider-lockfile identity, normalized nonsecret deployment inputs and references to externally managed secrets.

Do not upload existing `meta.json`, `.tfvars`, `.inventory` or `state/<deployment>/` wholesale: they can contain credentials/passwords. A new `src/python/deployment_manifest.py` allowlists fields rather than attempting broad string redaction. Store the manifest as a separately ACL-protected object beside, not inside, Terraform's owned state object. Writes use conditional generation/ETag checks through provider adapters. It is not a transaction with Terraform state: record lineage/serial, detect mismatches and report successful infrastructure operations even if manifest publication fails, with an explicit recovery-needed status.

For a first release, explicit manifest export/import is a recovery path when remote manifest publication is unavailable; never claim fully automatic second-machine recovery in that case. Remote manifest availability and round-trip are a release gate for the advertised fresh-controller workflow.

State/output JSON can expose sensitive outputs even when marked sensitive in Terraform. Capture privately, never print full JSON, and export only specifically requested SSH material into mode-0600 files after validation. Support OS Login/no-key deployments without generating placeholders. Missing secret references must block operations needing them, not regenerate passwords or keys unexpectedly.

### 4.5 Drift detection contract: compare the right things

Implement a shared `drift` CLI and Python service after backend/lifecycle safety is ready. Remote storage itself is neither a scheduler nor a drift detector. The four scopes are deliberately separate:

| Scope | Baseline and detector | Correction owner |
| --- | --- | --- |
| Backend infrastructure/security | Bootstrap Terraform state/configuration for owned storage; explicit policy/property checks for externally managed storage | Bootstrap owner, never workstation destroy/apply |
| Workstation infrastructure | Exact last successfully applied source revision, approved input digest, provider lockfile and authoritative deployment state | Workstation Terraform stack |
| Controller/state identity | Canonical backend descriptor, lineage, relocation records and manifest/state consistency | Explicit attach/reconciliation/migration workflow |
| In-VM software/runtime | Approved installer/Ansible/runtime acceptance checks, not Terraform resource state | Existing runtime verification/repair workflow, separately authorized |

Terraform `plan -detailed-exitcode` distinguishes empty diff (0), execution error (1), and nonempty diff (2); exit 2 alone does not establish unauthorized drift. Terraform's JSON plan exposes `resource_drift` separately from proposed `resource_changes`.[1][2] Normalize these into `clean_within_coverage`, `external_drift`, `desired_change`, `policy_noncompliance`, `identity_mismatch`, `locked`, `error`, `partial`, `stale` or `not_run`; a report may contain multiple finding classes. Document the wrapper's own exit contract separately and ensure Actions do not treat Terraform exit 2 as an execution failure or exit 1 as clean.

Detection procedure:

1. Resolve a pinned trusted baseline and exact backend identity. A moving default branch or provider upgrade is not the baseline of a previously applied deployment. Optionally compare the latest approved desired revision as a separate planning report; do not label all intended Git changes as external drift.
2. Check backend health and identity before opening the workstation state. A legitimate serial increase from another authorized operation is not identity drift; refresh the view. A lineage/location mismatch, retired source or access failure blocks mutation.
3. Run a refresh-enabled plan in the isolated runner with bounded lock timeout and no apply. Parse a private plan with `terraform show -json`, honoring the selected Terraform JSON-format version and unknown/deferred values. Do not use `-refresh=false` to suppress findings: it can ignore external changes.[1][2]
4. Classify observed changes separately from desired actions, policy findings and lifecycle intent. An operator-requested stopped VM, scheduled scaling, cloud-computed fields or provider normalization needs explicit interpretation; do not restart compute solely to make a report green.
5. State and provider schemas do not cover every remote property. Return checked resources/rules, unsupported fields, ignored attributes, unknown values and collection errors. Unsupported coverage is not proof of no drift. Keep any `ignore_changes` exceptions explicit and reviewable.
6. Publish only a sanitized structured report: schema version, scope, backend identity digest, baseline revision/lockfile/input digests, lineage/serial, timestamps, evidence sources, addresses/action classes, severity, coverage and recommended next action. Exclude credentials, raw values, full state and raw plan JSON. Even provider-declared sensitive masks are insufficient for unknown/private values; use an allowlist for public summaries.
7. Maintain report history and a deduplication fingerprint scoped to deployment, baseline and finding. Repeated unchanged findings update one incident instead of opening repeated issues. A clean follow-up resolves only findings actually rechecked; a failed check cannot resolve an incident.

Planning does not apply the proposed infrastructure changes.[1] It is still an authenticated operation that can execute trusted provider/data-source code, read secrets/state, create transient lock objects and incur API costs. Detection identities should have cloud read access and narrowly scoped backend read/lock permissions, plus a separate report-write location if needed—not workload mutation permissions. Native locks may require write/delete access to lock objects or lease operations; do not promise literal read-only credentials for every backend.

### 4.6 Cloud-native options: capabilities, limits and recommended use

This comparison describes documented capabilities, not live acceptance. Proposed integrations must check account availability, supported resource/property coverage, region, quotas, identity, private networking and costs during setup. Do not create monitoring services automatically.

| Provider | Documented native capabilities | Recommended IsaacAutomator integration | Important boundary |
| --- | --- | --- | --- |
| AWS | AWS Config evaluates compliance and supports remediation through Systems Manager Automation documents.[3] EventBridge Scheduler schedules tasks; CodeBuild supplies managed/customizable execution environments.[5][18] | Optional Config security checks and change/compliance signals; optional Scheduler → CodeBuild job running the same pinned `drift check` CLI. Generate separate detection and remediation roles and explicitly reviewed rule/runbook assignments. | Config compliance is not a comparison against our complete Terraform desired configuration. CloudFormation drift detection concerns CloudFormation-managed stacks and only eligible explicitly specified properties; it is not a drop-in detector for these Terraform-owned stacks.[4] |
| GCP | Cloud Asset Inventory feeds publish resource/policy-change notifications through Pub/Sub.[6] Cloud Scheduler can execute Cloud Run jobs on a schedule.[15] Infrastructure Manager provides a managed Terraform toolchain with deployments, revisions and previews.[13] | Optional Asset Inventory events as evidence/trigger hints, plus Scheduler → Cloud Run Job executing the existing runner. Use dedicated service identities and the exact selected GCS backend; periodic reconciliation catches missed/incomplete events. | Asset changes do not by themselves establish drift from Terraform. Adopting Infrastructure Manager would change execution/state ownership; evaluate it as a separate migration/architecture decision, not a second writer attached casually to existing state. Do not claim an unverified native scheduled drift API. |
| Azure | Azure Policy can remediate noncompliance for `modify` and `deployIfNotExists` policies using an assignment identity; Resource Graph exposes resource property changes.[7][8] Container Apps Jobs support scheduled jobs, and Automation supports recurring runbook schedules.[17][14] | Optional Policy/Resource Graph signals plus a scheduled Container Apps Job running the pinned CLI image; consider an Automation runbook as an alternative after verifying Terraform runtime support. Use managed identities and the saved Azure Blob backend. | Policy evaluates assigned rules, not all Terraform intent; Resource Graph is change evidence, not a full desired-state reconciler. Policy remediation must not compete with Terraform over the same attributes. |

AWS Config automatic remediation may act on stale compliance snapshots, even after a resource becomes compliant.[16] Therefore every corrective adapter must recheck the live condition immediately before changing it, use bounded retries and verify afterwards. Apply the same defensive rule to queued/duplicate events from every provider.

Choose one Terraform reconciliation executor per deployment/scope: local/on-demand, GitHub Actions, or the matching cloud-native scheduler. Event feeds can coexist as signals; they must coalesce into that executor rather than starting overlapping applies. Define resource/attribute ownership between Terraform, externally managed policy and runtime configuration. Do not hide controller conflicts by adding blanket ignores or letting policies and Terraform repeatedly undo each other.

Recommended staged delivery: shared local detector first; optional GitHub generator next; cloud-native scheduling/report adapters after the common contract is stable. Cloud-native policy remediation remains a separate optional capability and is off by default. Account-level security tooling may be preferable for organization-wide guardrails, while the common Terraform detector remains necessary for full declared stack intent.

### 4.7 Correction policy: report, approve, execute, verify

Support these explicit choices:

- `report_only` (default): detect and notify; no corrective resource mutation.
- `approval_required`: propose restoration to the approved baseline and require an authorized reviewer before executing the exact reviewed operation.
- `preauthorized_allowlist` (later opt-in): only narrowly defined, tested corrections with a signed-off resource/attribute allowlist, expiry, actor scope, rate/cost bounds and a kill switch. Do not ship this enabled or equate general repository write access with approval.

Offer distinct resolution paths, not one opaque repair button:

1. **Restore declared configuration:** produce a corrective Terraform plan using the stack that owns the resources, review it, apply and recheck.
2. **Accept an intentional external change:** review a configuration/input change, then reconcile state through normal Terraform planning. Refresh-only mode updates Terraform's records to observed reality; it does not restore infrastructure to the old configuration.[1] Never auto-apply refresh-only to make drift disappear.
3. **Temporary exception:** record exact rule/resource, justification, owner and expiry. Continue showing the exception and reevaluate it when the baseline changes; do not silently suppress security-critical findings indefinitely.
4. **External policy-owned resource:** direct remediation to the declared owner/runbook and verify compatibility with Terraform. Do not adopt externally managed storage or install new ownership merely to fix a finding.

Correction requirements:

- Bind approval to deployment/backend identity, source revision, input/provider-lockfile digests, observed state lineage/serial, sanitized action fingerprint and plan digest, with an expiry. A general “approve this deployment” token is insufficient.
- Revalidate state, baseline and live preconditions immediately before apply. State serial alone cannot reveal an intervening out-of-band cloud edit: compare current observed properties with the proposal's protected observation record, including value changes hidden by the public summary. If the observations changed or cannot be checked, invalidate the proposal and require replanning/reapproval. Apply the reviewed saved plan only when its binding remains valid. Backend locking does not prevent console/API edits; document this residual race and enforce short approval/observation freshness limits and post-checks.
- Store binary plans only in restricted, short-lived storage when transfer is necessary; no plan/state files in ordinary public Actions artifacts, job summaries or issue comments. For the initial implementation, apply only the exact reviewed saved plan; any regenerated plan requires a new approval. A sanitized address/action list is not proof of plan equivalence: changed target values can produce the same action list. Do not authorize recomputed plans using that fingerprint alone.
- Destruction, replacement, imports, state surgery/migration, key deletion/rotation, IAM broadening, public exposure, disabling protection, restoring old state versions and force-unlock always require explicit elevated review. Never put them in the default automatic allowlist.
- Backend remediation uses a separate admin/owner identity and cannot depend solely on access already broken by the finding. Provide a documented break-glass manual path when the backend is inaccessible; do not recreate an empty backend and treat existing workloads as unmanaged.
- Recheck each proposed native policy/runbook correction, then verify the actual property and the Terraform plan after applying. Missing post-checks or partial fixes are unresolved—not success.
- Limit concurrency, retries and action count; stop on oscillation, unexpected changes, stale events, expired exceptions, increased cost or failures. Retain sanitized receipts and expose a user-controlled pause/disable action. Do not automatically roll back by restoring an old `.tfstate` file.

### 4.8 User-configured GitHub Actions templates and generator

**Required deliverable:** reusable inert templates plus a deterministic generator. No active workflows exist in this checkout at planning time. Keep templates outside `.github/workflows/`; generating them is separate from installing them in a user-selected repository.

Proposed files (created during implementation, not this planning update):

- `templates/github-actions/terraform-drift-check.yml.tmpl`
- `templates/github-actions/terraform-drift-remediate.yml.tmpl`
- `templates/github-actions/README.md`
- `src/python/drift_workflow.py` (validated rendering and setup checks)
- `configs/drift/example-github-actions.yaml` (generic, nonsecret example)
- `src/tests/drift_workflow.test.py` (rendering, YAML validation and security contracts)

Provide proposed `./drift workflow preview --config PATH`, `./drift workflow generate --config PATH --output-dir PATH` and `./drift workflow verify-setup --config PATH` commands. Preview/generation are offline. Setup verification may read GitHub/cloud configuration only when authorized. Default output is `.generated/isaacautomator/workflows/`, not `.github/workflows/`; add an appropriate ignore rule during implementation. An explicit installation step displays the destination/diff and refuses to overwrite unrelated workflows. It must not commit, push, create secrets, grant IAM or enable Actions automatically.

Configuration must allow the user to choose:

- Repository owner/name, protected source branch and approved deployment manifest/config references.
- AWS/GCP/Azure, deployment allowlist, backend scope and namespace; never unrestricted account-wide enumeration.
- Detection scopes and executor; schedule enabled/disabled, UTC cron, manual dispatch and timeout/max-parallel settings. Recommend an off-hour-boundary cadence such as every six hours, but do not activate it by default or assume schedules are precise timers.
- Runner type/labels and private network requirements. GitHub-hosted is the simpler starting point when approved network paths exist; self-hosted must be dedicated, hardened and preferably ephemeral, never the user's interactive GPU workstation.
- Pinned Terraform/Automator image/source versions, trusted action SHAs, state/input/provider-lockfile references and approved secret references—not secret values.
- Separate provider identity references for detection and remediation, GitHub environment name/protection requirements, correction policy, approval expiry and plan/report retention.
- Notification choice: job summary only, an explicitly selected deduplicated GitHub issue destination, or an approved external channel. Additional write permissions and secret references are opt-in. Include severity thresholds, repeat-notification policy and a missed-check deadline.

Illustrative proposed input, deliberately incomplete until the user supplies their real nonsecret references:

```yaml
schema_version: 1
drift:
  enabled: false
  scopes: [backend_security, workstation]
  executor: github_actions
  baseline: last_applied
  schedule:
    enabled: false
    cron_utc: "17 */6 * * *"
  correction:
    mode: report_only
  github:
    repository: "OWNER/REPOSITORY"
    protected_branch: main
    runner_labels: [ubuntu-latest]
    remediation_environment: infrastructure-approval
  deployments:
    - manifest: "configs/deployments/EXAMPLE.manifest.json"
      backend_config: "configs/backends/EXAMPLE.yaml"
  notifications:
    mode: job_summary
```

The generator resolves supported authentication snippets from validated provider identity references. Reject arbitrary shell fragments, untrusted Actions expressions, unknown fields, traversal, credential values, branch/repository ambiguity and user-supplied action URLs/SHAs not approved by the template policy. Preserve GitHub `${{ ... }}` expressions through the template engine without evaluating user input as expressions. Validate GitHub's YAML semantics, especially the `on` key, rather than relying on a YAML 1.1 boolean interpretation. Render deterministically with a generator/schema version and provenance digest; regeneration must be idempotent, diffable and fail on unmanaged-file conflicts.

**Authentication and execution boundary:** GitHub OIDC exchanges workflow identity for short-lived cloud tokens rather than duplicating long-lived cloud credentials.[9]

Generate AWS trust scoped by repository/ref or environment and audience; GCP Workload Identity Federation and Azure federated credentials must also be bound to the intended repository/workflow context.[19][20][21]

Trust setup is a separately approved bootstrap/admin operation. `id-token: write` permits token issuance, not cloud-resource mutation by itself; cloud roles determine actual authority.[20][21]

Generated workflows must:

1. Separate scheduled/manual detection from manually requested approved remediation. Default to `contents: read`, and grant `id-token: write` only to jobs requiring cloud access; add issue/report permissions only where selected. Detection credentials cannot assume the remediation role.
2. Run only trusted, pinned source and modules with state-bearing credentials. Do not check out untrusted PR/fork code or use `pull_request_target`/`workflow_run` as an implicit privileged execution path. Never execute a plan/config/artifact merely because another workflow produced it. Pin third-party actions to verified full-length commit SHAs and execution images to approved digests; GitHub recommends full-length SHA pinning for immutable action references.[12]
3. Require protection of workflow/config/template files through branch review/CODEOWNERS or an equivalent repository policy, with OIDC trust conditions matching the actual protected workflow/ref/environment claims. Protect privileged reusable workflows and their inputs if introduced; a repository name alone is not a sufficient trust boundary.
4. Check actual environment approval capability before enabling remediation. GitHub documents repository-plan/visibility restrictions on required reviewers.[10] Merely naming an environment does not prove approvals exist. If the selected repository cannot enforce the required independent approval policy, generate detection-only workflows and require a separately validated external approval mechanism; never silently weaken the gate.
5. Validate report and plan bindings across manual dispatch and approval. A dispatch request/issue comment is not approval to apply arbitrary inputs. Use explicit deployment choices and report references, not arbitrary shell or Terraform options supplied by the triggering user.
6. Set concurrency groups from canonical backend/deployment identity; do not cancel an active apply in favor of a new scheduled check. GitHub concurrency is not a cross-repository/cross-cloud lock: retain Terraform backend locking and controller coordination. Use a separate group for the shared bootstrap stack when multiple workstations share a backend.
7. Clean private temporary plans/credentials, minimize artifact retention, sanitize all summaries and fail if the result cannot be classified. Continue report publishing after drift/error without converting an execution error into clean success; handle Terraform 0/1/2 explicitly.[1]
8. Track `last_attempt`, `last_success`, coverage and expected-next-check. GitHub schedules can be delayed or dropped, run only on the default branch, and public-repository schedules can be disabled after inactivity.[11] An independent opt-in watchdog or cloud alert must detect overdue checks; a workflow cannot reliably alert that it never ran. Show stale status locally even if no notification integration was selected.
9. Reject unsafe self-hosted runner configurations and document the risk of persistent compromise from untrusted code; GitHub warns that self-hosted runners lack clean-instance guarantees.[12] Validate backend reachability without opening storage publicly to accommodate CI.

### 4.9 Scheduling, notifications and native ownership

Keep `drift.enabled=false`, schedules disabled, and correction `report_only` unless explicitly configured. Users may run a one-off check without adopting GitHub or a provider scheduler. Local-backend deployments can be checked on their controller; reject cloud/Actions execution without an approved accessible state/attachment rather than uploading local state as a CI artifact.

Provider-native adapters run the same detector/report schema in a pinned job image. Their setup includes explicit scheduler target identity, separate runtime detection identity, report storage/notification permissions, retry/backoff limits, event deduplication, budgets and private networking. Monitoring infrastructure belongs to a durable independent stack, not the monitored GPU VM; protect its state and avoid circular dependency on an unavailable workstation. Retain ownership/retirement metadata and require approval to provision or remove schedulers/rules/jobs.

Event feeds are hints to recheck, not commands to repair. Normalize duplicate/out-of-order events, debounce bursts, recheck current truth, and rate-limit by canonical scope. Resolve state addresses from trusted descriptors, never event-supplied arbitrary code/backend locations. Scheduled full reconciliation remains necessary for missed events and coverage gaps. A detector's `clean` status is scoped and timestamped; it is not proof that the platform has no other unmanaged resources.

Users choose alert channels and destinations explicitly. Report new/changed high-severity findings, failed checks, overdue checks, remediation outcomes and recoveries, with links to access-controlled evidence. Track notifications separately from detection success: a failed delivery must not mark the underlying check failed or its drift resolved, and must itself be visible. Suppressions have owners/expiry and remain auditable. Setup should show estimated service categories/cost drivers, not unsupported fixed price claims.

## 5. Implementation tasks and dependency order

Each code task follows RED → GREEN → review: add its smallest failing unittest/mock case, run it, implement only that behavior, rerun focused tests, then the relevant existing suite. Split numbered steps into small changes. Do not commit or push unless requested. New file paths below are proposed creations, not existing APIs.

### Task 1 — Permanently capture unsafe current behavior

**Files:** Modify `destroy`, `src/python/utils.py`; create `src/tests/terraform_lifecycle.test.py`; extend `src/tests/deployer.test.py` and `src/tests/utils.test.py`.

1. Add a synthetic remote-only deployment regression: no local `.tfstate`, backend descriptor present; mock all cloud commands and directory deletion.
2. Assert destroy refuses unknown state, returns nonzero, preserves files and never prints success. Reproduce the current failure first.
3. Add inaccessible/malformed state and failed Terraform destroy cases; assert identical preservation.
4. Add a temporary fail-closed guard until full remote destroy exists. Do not read credentials or live state in tests.
5. Capture missing/stale local output and dry-run masking regressions for subsequent runner integration. Mark intentionally pending feature tests explicitly rather than claiming they pass.

**Gate:** The false-success destruction path is closed before any new remote backend is enabled.

### Task 2 — Establish supported Terraform/backend versions

**Files:** Inspect `Dockerfile`, `.devcontainer/Dockerfile`, `.devcontainer/devcontainer.json`, `src/terraform/{aws,gcp,azure}/main.tf`, `src/terraform/bootstrap/gcp/main.tf`, `.terraform.lock.hcl` files where present; create a version contract test in `src/tests/terraform_backend.test.py`.

1. Verify authoritative backend docs listed in section 9 and record the chosen tested Terraform version/range and provider constraints.
2. Prefer native S3 lockfiles; choose a minimum Terraform version supporting them and test it. Do not claim the current `>=1.3.5` declaration is sufficient. Do not silently add legacy DynamoDB locking; support it only if maintaining older Terraform is explicitly approved and separately tested.
3. Check GCS soft-delete schema and Azure auth/storage feature compatibility against chosen provider versions. Replace overly broad unsupported constraints with tested bounds and committed provider locks under normal repo policy.
4. Add actionable preflight errors for unsupported binaries. Define local-only compatibility separately if preserving old Terraform locally.
5. Plan any tool-image version change separately; never modify VS Code settings or devcontainer configuration without the repository-required explicit permission. Runtime checks can ship without such changes.

**Gate:** Backend feature support has a documented version matrix, not assumptions about whichever apt package is installed.

### Task 3 — Implement BackendSpec and explicit opt-in

**Files:** Create `src/python/terraform_backend.py`, `src/tests/terraform_backend.test.py`; modify `src/python/config.py`, `src/python/deploy_command.py`, `src/python/deployer.py`, `configs/profiles/README.md`; later add examples in Task 13.

1. Test local-by-default and all valid provider descriptors, exact identity construction, missing/wrong fields and backend/cloud mismatch.
2. Test CLI/profile/default precedence using real Click parameter sources, explicit local overriding a remote new-deployment profile, saved descriptors resisting implicit changes and legacy bucket conflict handling.
3. Implement normalization without authentication, filesystem writes or cloud calls. Reject secrets and unsafe strings early.
4. Transport the normalized backend spec as controller-only data; exclude it from Ansible inventory and workstation Terraform variables unless a specific nonsecret resource input actually requires it.
5. Test that selecting team/enterprise alone performs no remote creation/migration and gives clear setup guidance.

**Gate:** Opt-in is unambiguous, validated and independent of security tier.

### Task 4 — Build the isolated Terraform runner

**Files:** Create `src/python/terraform_runner.py`, `src/tests/terraform_runner.test.py`; modify initialization/plan/apply call sites in `src/python/deployer.py` only after runner tests pass.

1. Test staged source selection, relative modules, per-operation backend override and per-operation container-local `TF_DATA_DIR`.
2. Test argv construction for local/GCS/S3/Azure; injected shell metacharacters never execute. Redact sensitive output/errors and enforce private file modes.
3. Implement explicit initialization, timeout, subprocess cancellation/process cleanup, exit-code handling and typed JSON parsing.
4. Pin backend identity through init→plan→apply/output/destroy. Reject conflicting profile/environment/workspace changes.
5. Run a concurrency regression interleaving operations on two deployments/clouds; assert no backend/cache/variables crossover. Test same-deployment controller lock and cancellation release.
6. Test no unsolicited `-upgrade`, `-reconfigure`, `-lock=false` or hidden migration. Allow controlled reconfiguration only when attaching an already selected backend in an isolated fresh context.
7. Add a real offline, provider-free Terraform fixture with a constant output and local backend. Configure an absolute canonical state path outside all temporary run/data directories, apply through one runner context, delete its staging/data directories, read outputs through a fresh context, then destroy through another. Assert the canonical state survives staging cleanup and no state is stranded in disposable directories. Use only a temporary test state root, never operational state or cloud providers.

**Gate:** Every Terraform command has an immutable operation context and verified target identity.

### Task 5 — Create independent bootstrap implementations

**Files:** Modify `src/terraform/bootstrap/gcp/main.tf`; create `src/terraform/bootstrap/gcp/README.md`, `src/terraform/bootstrap/gcp/tests/backend.tftest.hcl`; create corresponding `main.tf`, `variables.tf`, `outputs.tf`, `README.md`, `tests/backend.tftest.hcl` under `src/terraform/bootstrap/aws/` and `src/terraform/bootstrap/azure/`; create `src/python/backend_bootstrap.py`, `src/tests/backend_bootstrap.test.py`.

For each provider, implement and review independently:

1. Write mocked plan assertions for storage protection, encryption, versioning, locking prerequisites, scoped authorization and deletion protection; inspect negative plans for public access and invalid configuration.
2. Implement create-new/use-existing behavior and the exact properties from section 4.3.
3. Test deterministic valid names with account/project/subscription uniqueness; `auto` is only a name proposal until explicitly approved bootstrap apply.
4. Define bootstrap-state location, protection and optional explicit migration; prove the workstation graph cannot destroy backend resources.
   Explicitly test Azure backend/workstation resource-group overlap rejection, including use-existing accounts, and confirm backend ancestors are outside workload ownership.
5. Add use-existing checks with no writes. Missing permissions/features return precise remediation, not automatic IAM changes.
6. Document backend identity vs workload identity, optional private access and CMEK dependencies.

**Gate:** AWS, GCP and Azure each have independently testable setup and externally managed storage paths. Passing mocked plans is not live IAM acceptance.

### Task 6 — Add state-backend CLI and preflight

**Files:** Create `state-backend`, `src/python/state_backend_command.py`, `src/tests/state_backend_command.test.py`; modify `.completions` and `run` only if required by the existing wrapper pattern.

1. Add Click tests for the proposed subcommands, noninteractive missing-input failures and separate plan/apply approval behavior.
2. Implement offline validation separately from authenticated doctor. Doctor must distinguish not-found, forbidden, wrong identity, unreachable and unsupported feature.
3. Implement explicit disposable-object write/lock probes with cleanup receipts; never probe by modifying production state.
4. Integrate provider login helpers without exposing credentials. A deploy login must not be mistaken for sufficient backend data-plane authorization.
5. Show a nonsecret effective destination and costs/security summary before bootstrap apply or migration.
6. Test execution in the devcontainer, the top-level Docker wrapper and headless CI. `run:17-25` currently forwards a limited AWS-oriented environment whitelist; explicitly support approved backend identity variables and container-readable external credential/token-file references for AWS, GCP and Azure. Do not forward the entire host environment, copy credential files into the repo, or assume host paths exist inside the container. Keep backend and workload authentication contexts distinguishable.
7. Preserve the invoked command's failure exit code through wrapper cleanup, and support a non-TTY execution path. Test that authentication failure, lock timeout, declined migration and failed destroy are nonzero at the outermost CLI, not masked by watcher cleanup or shell wrappers.

**Gate:** Users can intentionally prepare a backend without starting a VM, and simply selecting remote state does not create infrastructure.

### Task 7 — Make outputs and deployment state backend-aware

**Files:** Create `src/python/deployment_state.py`, `src/tests/deployment_state.test.py`; modify `src/python/utils.py`, `src/python/deployer.py`, `deploy-aws`, `deploy-gcp`, `deploy-azure`.

1. Test authoritative output retrieval with no local state file for every remote backend; do not use copied remote `.tfstate` as the long-term solution.
   Add occupied-destination and competing-first-creator tests: a new deployment without a verified attachment cannot adopt a populated state, even when names/configuration match. Preserve the existing state and require `attach`.
2. Preserve legacy local JSON-read compatibility if safe, but dispatch via descriptor and use typed missing/error results.
3. Fetch output JSON once per operation, retain native value types, validate required fields and never cache beyond the relevant mutation without refreshing.
4. Integrate Terraform apply completion with validated inventory, key export and connection instructions. Missing outputs must stop downstream actions; do not write blank keys or inventories.
5. Test partial apply: retain descriptor/state/artifacts, expose partial failure, provide a resume path and do not attempt to create another deployment.
6. Preserve existing registry/Hugging Face identity checks, profile behavior and disabled-mode tests.

**Gate:** A remote apply can be followed by real post-apply orchestration without a local `.tfstate` snapshot.

### Task 8 — Update every lifecycle and connection consumer

**Files:** Modify `start`, `stop`, `destroy`, `repair`, `ssh`, `novnc`, `upload`, `download`, `cycle-vm`, `cycle-vm.sh`, `src/python/utils.py`; trace all usages before editing. Extend `src/tests/terraform_lifecycle.test.py` and create `src/tests/terraform_consumers.test.py`.

1. Inventory every `read_tf_output`, direct `.tfstate` read and direct Terraform invocation in these paths and `import`; assign each to shared runner/state APIs or a documented local-only exception.
2. Start/stop use validated current cloud/instance identity; unsupported or unknown identity must fail rather than guess. Remote-state failures must not invoke unrelated cloud commands.
3. Repair uses the exact saved backend, preserves AMI-pinning behavior and resolves required inputs before infrastructure mutation; regenerate inventory from authoritative outputs as needed.
4. Destroy plans/applies against that same state, checks exit status and confirms no remaining managed resources before optional local-file cleanup. Partial failure, empty-but-ambiguous state, denied reads and lost receipts retain recovery material and report uncertainty. Warn that resources manually removed from Terraform state cannot be detected by an empty-state check alone.
5. Preserve backend storage and shared registry resources after workstation teardown. Keep a minimal safe tombstone/recovery receipt; remove credentials only after confirmed completion and the chosen cleanup policy.
6. Test cancellation and interrupted operations; never print successful cleanup when it was not verified. Fix all equivalent local/remote failure paths, not only `destroy`.

**Gate:** Remote-only start/stop/repair/destroy/connection operations work in mocks, and destructive ambiguity fails closed.

### Task 9 — Add recovery manifest and fresh-controller attachment

**Files:** Create `src/python/deployment_manifest.py`, `src/tests/deployment_manifest.test.py`, `src/tests/backend_attachment.test.py`; extend `src/python/deployment_state.py`, `src/python/state_backend_command.py`; modify `import` and discovery consumers.

1. Write allowlist tests with synthetic credentials in nested legacy metadata; prove they never reach exported manifests, logs or public examples.
2. Implement manifest validation, schema revision, immutable identity, source/lockfile references and conditional remote publication through provider adapters; add interruption and state/manifest-serial mismatch cases.
3. Attach requires explicit backend/manifest scope, verifies lineage/cloud identity, reads authoritative state, and creates only local attachment metadata. It must not apply, import, fork state or silently check out/execute an untrusted repository referenced in a manifest.
4. Reconstruct only approved inputs. Report capabilities separately: state inspection, VM start/stop and full repair/destroy; missing source inputs/secrets block the affected capability rather than pretending full recovery.
5. Keep existing `import` for unmanaged resources, but refuse known remote-managed identities. Check the configured catalog/namespace and explain that unmanaged status cannot be proven across arbitrary inaccessible backends. Require explicit ownership attestation where discovery cannot establish it.
6. Test a clean temporary controller with no `state/` directory: attach, show outputs, generate valid permitted connection data, and run lifecycle mocks. Remote state alone must not be advertised as full controller backup.

**Gate:** Second-machine recovery is demonstrated without copying secret-bearing directories or creating duplicate state ownership.

### Task 10 — Implement explicit state migration and recovery

**Files:** Extend `src/python/state_backend_command.py`, `src/python/deployment_state.py`, `src/python/terraform_runner.py`; create `src/tests/backend_migration.test.py`.

1. Require source descriptor, exact destination, backend preflight, operator quiescence across controllers and a protected backup. Terraform locking cannot atomically lock arbitrary backend locations across every step; document that migration is an exclusive maintenance operation.
2. Compare source lineage/serial/resource addresses and destination contents. Refuse populated unrelated destinations, wrong cloud/scope, concurrent writes, unknown current state or unchanged-location mistakes.
3. Execute Terraform-supported migration in an isolated context using `init -migrate-state` and version-tested noninteractive confirmation behavior. Never substitute `-reconfigure`, generic blob copy or unguarded `state push`. If the tested Terraform version cannot complete safely noninteractively, require an explicit supervised migration instead of weakening checks.
4. Pull privately and compare destination/source resource identity and outputs after migration; allow documented serial/version changes. Verify a read-only plan for unexpected creates/deletes.
5. Commit the new local descriptor and recovery manifest only after verification. Preserve source backups; mark them inactive. Partial/unknown outcomes require diagnosis before retry; never automatically reactivate both locations.
6. Cover local→remote, remote→local and same-provider destination moves. Remote→local requires a warning that shared-controller coordination is lost. Cross-cloud remote migration is deferred with explicit refusal.
7. Add version-restore and stale-lock recovery runbooks: backup current state, prove exclusive ownership, explicitly approve restore/unlock and verify afterwards. Never auto-force-unlock or rewind state serials.
8. Retire the old location before declaring migration complete. Publish a protected relocation record outside the source state object; every managed runner checks it before planning, mutating or interpreting missing state as empty. A stale descriptor must fail with migration guidance, not follow an unverified redirect or recreate state at the source. Keep the source fenced during uncertain migration outcomes.
9. A relocation record alone cannot stop old clients or raw Terraform. Before ending the maintenance window, establish a provider-tested write fence on the retired source state/lock location, or retire/rotate every identity able to write it and update every authorized controller. Such IAM changes need separate approval and must preserve destination access and unrelated states. If source fencing cannot be established with the available permissions, report migration as requiring supervised retirement rather than claiming safe unattended completion. Test an old-controller write attempt, not just the current controller's updated descriptor.

**Gate:** Migration preserves one authoritative state and cannot happen as a side effect of deploy or profile editing.

### Task 11 — Correct planning semantics

**Files:** Modify `src/python/deployer.py`, `src/python/deploy_command.py`, `deploy-aws`, `deploy-gcp`, `deploy-azure`; extend `src/tests/deployer.test.py`, `src/tests/deploy_command.test.py`, `src/tests/terraform_runner.test.py`.

1. Separate offline source/schema validation (`init -backend=false` in a disposable source tree where appropriate) from authenticated speculative planning against the actual backend.
2. Define and document backward-compatible handling of `--dry-run`; do not keep silently substituting local state for remote. A real plan can read cloud APIs, temporarily create locks and refresh data; it is not an offline test or a promise of zero side effects.
3. Saved plan files can contain secrets: private permissions, short lifetime, no Git/artifact publication by default, and bind apply to the same backend/config identity.
4. Move Azure resource-group import out of the dry-run path; `deploy-azure:212-215` currently calls import during dry-run, which must not be treated as read-only.
5. Test missing backend/credentials, plan exit codes, lock contention and no automatic bootstrap/migration/import during validation.

**Gate:** The tool accurately tells the user whether it performed offline validation or a remote-backed plan.

### Task 12 — Update the TUI without a second backend implementation

**Files:** Modify `src/tui/backend.py`, `src/tui/screens/profiles.py`, `src/tui/screens/deploy_modal.py`, `src/tui/screens/inspector.py`, `src/tui/app.py`; extend `src/tests/isaac9s.test.py` and add `src/tests/terraform_tui.test.py` for isolated backend-specific UI cases.

1. Add explicit local/remote choice and provider-specific setup/use-existing guidance. No hidden bootstrap from toggles or profile selection.
2. Display backend type, safe destination, attachment and accessibility separately from VM status. Do not label unreachable state as an undeployed VM.
3. Invoke shared state APIs/commands asynchronously with bounded timeouts and cancellation; never block the UI on cloud discovery.
4. Use explicit known namespaces/attachments, not unrestricted account-wide bucket enumeration. Persist backend-aware profile fields without secret values.
5. Ensure all lifecycle actions and inspector output use the same fail-closed semantics and redaction as the CLI; distinguish local installer healing from cloud repair.

**Gate:** CLI and TUI select and operate the same backend identity with identical safety boundaries.

### Task 13 — Documentation, compatibility and release gating

**Files:** Modify `README.md`, `configs/profiles/README.md`, affected public profile YAMLs, `.agents/references/docs/dynamic-security-and-storage-guide.md`, `.agents/references/docs/isaac9s-cockpit-guide.md`, `ai/automator.agent.md`, `.agents/skills/isaac-automator/deploy-workstation/SKILL.md`, `.agents/skills/isaac-automator/manage-lifecycle/SKILL.md`; create `.agents/references/docs/terraform-remote-backend-guide.md` and generic `configs/profiles/example-{aws,gcp,azure}-remote-state.yaml` examples.

1. Document local default, explicit remote opt-in, create-new/use-existing, costs, least privilege, state sensitivity, version constraints and exact command syntax.
2. Publish provider-specific bootstrap and acceptance runbooks, fresh-controller attach, migration, restore/unlock, partial failure and backend-retirement procedures.
3. Correct claims that remote backends work end-to-end or that `auto` always provisions storage. Document changed built-in profile behavior and legacy GCS paths.
4. Keep registry-state and VM-result backups explicitly separate. Show which controller artifacts are recoverable and which require external secret/config sources.
5. Do not modify AGENTS.md, VS Code settings or global agent configuration as part of this feature. Update the session checkpoint only under the normal checkpoint workflow after a separately authorized implementation milestone.
6. Maintain an acceptance ledger per provider: implemented, offline-tested, live-tested, or blocked. Do not label all providers production-ready based on one provider's successful deployment.

**Gate:** Documentation describes demonstrated behavior and makes remaining live acceptance gaps visible.

### Task 14 — Drift configuration, baseline and report contract

**Depends on:** Tasks 2–4, 6–7, 9 and 11. Remote detection is released only after the applicable provider's lifecycle/recovery gates pass; reporting must not become a shortcut around them.

**Files:** Create `src/python/drift_config.py`, `src/python/drift_report.py`, `configs/drift/README.md`, `src/tests/drift_config.test.py`, `src/tests/drift_report.test.py`; extend the proposed `src/python/deployment_manifest.py` and its tests for last-applied baseline metadata.

1. Write failing tests for opt-in defaults, executor/scope compatibility, unknown/secret-bearing fields, expired exceptions and malformed schedules; run the new config suite before implementation.
2. Add a versioned configuration for scopes, provider identity references, baseline, executor, reporting, correction and retention. Keep schedules and correction disabled by default; migrations between schema versions require explicit compatibility rules.
3. Capture source revision, input digest and provider lockfile digest on a successful apply. Preserve reproducible protected input references; a digest alone cannot reconstruct inputs. Treat missing historical baseline as `partial`/setup-required rather than inventing one from HEAD.
4. Write failing report tests for overlapping finding classes, coverage gaps, freshness, redaction, deduplication and resolution only after successful rechecks; implement section 4.5's structured contract.
5. Keep operational findings out of the static codebase evidence graph by default. Adding Neo4j or an agent is not a prerequisite for drift detection, and no detector should execute graph-provided remediation instructions.

**Gate:** Versioned nonsecret configuration, reconstructible approved baselines and honest reports are verified offline; selecting a remote backend does not enable monitoring.

### Task 15 — Shared drift detector and on-demand CLI

**Depends on:** Task 14 and the shared runner/health/attachment work.

**Files:** Create `drift`, `src/python/drift_command.py`, `src/python/drift_detector.py`, `src/tests/drift_detector.test.py`, `src/tests/drift_command.test.py`; modify `run`, `.completions`, the proposed `src/python/terraform_runner.py`, `src/python/backend_bootstrap.py` and `src/python/state_backend_command.py` as needed. Reuse Task 6's backend health implementation; do not invent a second health service. Extend `src/tui/screens/inspector.py` only for read-only report/freshness display and test it in `src/tests/terraform_tui.test.py`.

1. Write fixture-driven failing tests for Terraform exit 0/1/2, `resource_drift` versus `resource_changes`, unsupported JSON fields, partial reads, policy findings and identity errors. Use synthetic nonsecret plans; no live state fixtures.
2. Implement proposed `./drift check NAME --scope SCOPE --format json` and report/history access through the same isolated runner, state descriptor and baseline validation. Define scope enumeration/help and headless input handling; return documented wrapper exit codes without masking subprocess failure.
3. Evaluate bootstrap Terraform drift for owned backend infrastructure and read-only property/policy checks for external storage. Record unsupported checks and blocked backend access. Integrate runtime check results only via existing approved read-only verification contracts, not automatic SSH/Ansible repair.
4. Add lifecycle-intent handling, explicit exceptions, bounded locking and cancellation. Verify that a deliberately stopped VM is not started and a migrated source is not used.
5. Run a provider-free real Terraform fixture in isolated temporary storage, using a compatible built-in resource where available, to exercise actual plan/JSON parsing and distinguish intentional configuration changes. Use provider mocks/synthetic outputs for external-cloud drift until separate live acceptance. Do not mistake the fixture for cloud drift validation.
6. Expose sanitized reports consistently in CLI/TUI. Test lock contention, authentication failure and missing baseline without any mutation or “clean” claim.

**Gate:** The CLI detects/classifies tested cases without applying changes, leaks or new backend assumptions, and publishes explicit coverage/freshness.

### Task 16 — Approved correction and verification engine

**Depends on:** Tasks 14–15 and applicable lifecycle/recovery acceptance.

**Files:** Create `src/python/drift_remediation.py`, `src/tests/drift_remediation.test.py`; modify `src/python/drift_command.py`, `src/python/drift_config.py`, `src/python/drift_report.py` and the shared runner only where needed.

1. Write failing tests showing `report_only` cannot mutate; general dispatch/issue comments cannot approve; altered resource actions, baseline, state lineage, expired approval or backend identity invalidate a request.
2. Implement proposed `./drift propose NAME --report REPORT_ID` and `./drift remediate NAME --proposal PROPOSAL_ID --approval APPROVAL_REF`. IDs resolve through trusted local/protected report storage; reject arbitrary executable paths/URLs and require a verifiable actor/scope binding. Final syntax must be documented and noninteractive.
3. Implement the approval record and plan identity contract in section 4.7. Separate workload and backend-owner correction identities. Select and document the trust anchor for approval verification: authenticated protected-environment review or a separately managed signed approval issuer, not a caller-editable JSON flag. Detector/report writers cannot mint approvals; test forged, replayed, self-approved and wrong-actor records. Display proposed operations and ensure any regenerated plan requires renewed approval. Test intervening cloud edits with an unchanged Terraform state serial.
4. Implement restore, intentional-change guidance and expiring exceptions as distinct outcomes. Any native policy/runbook adapter must validate live preconditions and return a sanitized execution receipt; none bypasses the correction policy.
5. Re-plan and check properties after a correction. Mark partial/error/unverified outcomes honestly; add retry caps, pause/kill switch and oscillation detection. Verify no automatic old-state restore, force-unlock or resource replacement occurs.
6. Keep `preauthorized_allowlist` rejected as unsupported until its exact rule engine, identity separation, emergency stop and provider-specific acceptance are implemented/reviewed. Add those tests before enabling even one automatic rule; high-risk operations remain excluded.

**Gate:** Unauthorized/stale/broadened corrections fail closed; approved corrections have verifiable post-checks. Detection and correction remain independently permissioned.

### Task 17 — Configurable GitHub Actions template generator

**Depends on:** Tasks 14–16. A detection-only subset can ship after Task 15 with remediation generation explicitly unavailable.

**Files:** Create all proposed template/example/generator/test files in section 4.8; modify `src/python/drift_command.py`, `src/python/drift_config.py`, `.gitignore`, `.completions`, `configs/drift/README.md` and `src/tests/drift_command.test.py`. Do not create active `.github/workflows/*.yml` in this repository as part of adding the templates.

1. Write failing golden-output/schema tests for AWS/GCP/Azure, report-only/manual-approval choices, schedule disabled/enabled, custom repository/branch/environment/runner and notification references.
2. Implement offline preview/render to an inert output directory. Generate separate check/remediation templates and a setup checklist with nonsecret OIDC trust requirements; refuse incomplete authentication references rather than emitting plausible but nonfunctional provider steps.
3. Add explicit install preview/confirmation, deterministic provenance, conflict detection and safe regeneration. Test no Git/GitHub/cloud writes during preview/generation and no implicit workflow installation, even when `drift.enabled=true` in the input.
4. Generate provider-specific OIDC login steps, pinned actions/images, least-privilege jobs, lock/concurrency handling and exact wrapper exit-code reporting. Test safe preservation of GitHub expressions and rejection of user expression/shell injection, traversal, secret values and unsafe action references.
5. Add authorized setup verification for repository identity, protected source policy, actual environment approval support, OIDC trust/audience/subject, runtime versions, private endpoint reachability and report permissions. Offline preview labels these unverified. Fail closed or emit detection-only when remediation approvals cannot be enforced; do not mutate remote settings to make checks pass.
6. Validate rendered YAML with a GitHub-compatible parser and `actionlint` when available; check tooling/dependency manifests first and do not install silently. Test missing validator reporting, no privileged PR/fork paths, no plaintext state/plan artifacts and `cancel-in-progress` safety for applies.
7. Test duplicate/failed/missed checks and selected notifications, including unavailable issue permissions and external approval paths. Document scheduled-run limitations and independent heartbeat monitoring.

**Gate:** Each user-selected provider/configuration renders validated inert workflows; activation requires explicit review/setup. No remediation workflow can run without its real approval/identity requirements.

### Task 18 — Optional cloud-native adapters, drift documentation and release evidence

**Depends on:** Tasks 14–16 and independently approved monitoring infrastructure setup. Reuse their common configuration/report logic, not GitHub-specific authentication or scheduling; Task 17 is not a prerequisite.

**Files:** Create `src/python/drift_native.py`, `src/tests/drift_native.test.py`, `configs/drift/example-{aws,gcp,azure}-native.yaml`, `.agents/references/docs/terraform-drift-guide.md` and `src/terraform/test_drift_monitoring.py`. Proposed independently owned scheduler stacks: `src/terraform/monitoring/{aws,gcp,azure}/main.tf`, `variables.tf`, `outputs.tf`, `README.md` and `tests/monitoring.tftest.hcl` within each provider directory. Modify `src/python/drift_command.py`, `README.md`, the Task 13 backend guide and relevant lifecycle operator documentation.

1. Record a capability/cost/ownership decision per provider using section 4.6 and recheck the cited docs. Choose the minimal supported executor: AWS Scheduler/CodeBuild, GCP Scheduler/Cloud Run Job or Azure Container Apps Job. Treat Automation/Infrastructure Manager as alternatives to evaluate, not extra mandatory services.
2. Write failing provider-mocked tests for disabled defaults, separate scheduler/runtime/admin roles, private networking, report storage, budget/retry limits and teardown protections. Implement one provider slice at a time in the independent monitoring stack.
3. Add optional Config/Asset Inventory/Policy/Resource Graph signal adapters only for explicitly selected resource/rule coverage. Reuse existing customer-owned policy/feed resources where authorized; never create broad organization-wide assignments by default. Deduplicate events and trigger the same detector, not immediate apply.
4. Native corrective runbooks/policies are a separately enabled slice governed by Task 16. Test shared resource/attribute ownership, current-condition rechecks, stale compliance, least privilege, no oscillation and independent post-correction verification.
5. Implement health/last-success tracking, selected notification destinations, independent overdue-check monitoring and safe disable/retirement. Deduplicate shared-backend checks across workloads and preserve report/audit retention during cleanup.
6. Document local/manual, generated GitHub and native choices side by side; show how users configure identities, schedules, approvals, exclusions, costs and recovery when storage access is broken. Include example generation commands and label proposed/unsupported modes accurately.
7. Run offline suites and section 7's separately authorized drift acceptance. Record each provider/executor/correction mode as proposed, implemented, offline-tested, live-tested or blocked. Do not infer AWS/Azure acceptance from GCP results, or native acceptance from a GitHub workflow lint pass.

**Gate:** Optional native integrations have independent ownership and measured acceptance; the docs/template generator describe only supported combinations and never activate paid services implicitly.

## 6. Test strategy and exact execution targets

### 6.1 Existing regression baseline

Inspect test files before executing; keep operational state/private profiles inaccessible to tests. Existing focused commands:

```sh
PYTHONPATH="$PWD" python3 -B src/tests/deployer.test.py
PYTHONPATH="$PWD" python3 -B src/tests/deploy_command.test.py
PYTHONPATH="$PWD" python3 -B src/tests/utils.test.py
```

Run the existing distribution, registry, Hugging Face and TUI suites after shared config/deployer changes. Discover their actual entry points rather than assuming pytest naming; this repository uses standalone `*.test.py` unittest scripts. Preserve known unrelated failures as explicitly reported baseline issues, not silent skips.

### 6.2 New focused tests (proposed files from tasks)

Each new test script must support the same direct unittest invocation. For example:

```sh
PYTHONPATH="$PWD" python3 -B src/tests/terraform_backend.test.py
PYTHONPATH="$PWD" python3 -B src/tests/terraform_runner.test.py
PYTHONPATH="$PWD" python3 -B src/tests/terraform_lifecycle.test.py
PYTHONPATH="$PWD" python3 -B src/tests/backend_bootstrap.test.py
PYTHONPATH="$PWD" python3 -B src/tests/state_backend_command.test.py
PYTHONPATH="$PWD" python3 -B src/tests/deployment_state.test.py
PYTHONPATH="$PWD" python3 -B src/tests/terraform_consumers.test.py
PYTHONPATH="$PWD" python3 -B src/tests/deployment_manifest.test.py
PYTHONPATH="$PWD" python3 -B src/tests/backend_attachment.test.py
PYTHONPATH="$PWD" python3 -B src/tests/backend_migration.test.py
PYTHONPATH="$PWD" python3 -B src/tests/terraform_tui.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_config.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_report.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_detector.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_command.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_remediation.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_workflow.test.py
PYTHONPATH="$PWD" python3 -B src/tests/drift_native.test.py
```

Expected RED: the specific new contract assertion fails against the old behavior. Expected GREEN: the focused suite exits zero with no hidden skips for the implemented behavior. Do not predeclare test counts or invent live output.

### 6.3 Required coverage matrix

Run applicable scenarios for local, GCS, S3 and Azure Blob:

- New deployment with omitted/local settings; no remote provisioning calls.
- New explicit remote destination, use-existing backend and explicit bootstrap.
- CLI/profile precedence; wrong provider; unsupported Terraform; malformed/secret-bearing config.
- Missing, denied, unreachable, wrong-owner, empty and populated backend states.
- Output retrieval with no local `.tfstate`; stale local snapshot cannot win over remote authority.
- Same name across accounts/projects/subscriptions/clouds; preserved v1 GCS identity.
- New deployment cannot adopt an occupied remote object; competing first creators cannot create duplicate ownership.
- Canonical local state persists across discarded runner/staging/data directories in a real offline fixture.
- Two concurrent deployments; same-state lock contention; process cancellation; unexpected inherited Terraform settings.
- Partial apply; interrupted manifest publication; partial destroy; no false success/local data loss.
- Remote-only start/stop/repair/SSH/inventory and TUI display.
- Fresh controller attach with valid manifest, missing secrets, incompatible source revision and malicious manifest fields.
- Migration directions, nonempty destination, lineage mismatch, interrupted migration and safe retry.
- Stale controllers and raw Terraform cannot write to a retired source after the approved source-fencing procedure; managed clients honor relocation records.
- Offline validation versus authenticated plan; no state import/migration in dry-run.
- Backend storage/registry survival after workstation destroy; deleted workstation does not leave compute billing.
- Azure create-new/use-existing backend storage is rejected if its resource group is owned by the workstation stack.
- Manifest/state backups protect sensitive data; debug logs, exceptions and subprocess output do not leak values.
- Drift disabled/report-only defaults, all four scopes and provider/property coverage limits; Terraform 0/1/2 mapped without false clean or false execution failure.
- Pinned last-applied baseline versus intended source/provider changes; missing inputs/baseline, unknown/deferred values, ignored properties and lifecycle-intent exceptions.
- Legitimate state serial advance, migration relocation, denied/partial/timed-out checks, lock contention and stale last-success evidence.
- No mutation during detection except authorized transient locking/report writes; no state/plan/private values in public artifacts, logs or notifications.
- Approval binding, expiry, untrusted report inputs, stale or broadened plans, elevated-risk operations, post-check failure, kill switch and correction oscillation.
- Workflow generation for AWS/GCP/Azure with custom user configuration, inert output, idempotence, conflicts, YAML semantics, expression injection and no implicit installation/activation.
- OIDC audience/subject/ref/environment restrictions, separated roles, unavailable GitHub reviewer protections, pinned actions and untrusted PR/artifact rejection.
- Shared-state concurrency across repositories/executors, non-cancelling applies, scheduled/manual check races, duplicates, dropped/missed schedules and independently monitored overdue checks.
- Native policy/event coverage, duplicate/stale/out-of-order evidence, Terraform/policy ownership conflicts, monitoring stack survival and approved scheduler teardown.
- Notification failure separate from check outcome; explicit destinations, issue deduplication, exception expiry and incident resolution only after a successful covered recheck.

### 6.4 Terraform bootstrap verification

Create `src/terraform/test_remote_backends.py` following the source-only disposable-copy pattern in `src/terraform/test_ecr.py`. Clear unsafe Terraform environment, use dummy provider identities, `init -backend=false`, validation and provider-mocked plan tests. Mock plans do not test real S3/GCS/Blob state locks. Public provider downloads must be reported; no real credentials or backend initialization in this tier.

Run after implementation:

```sh
python3 -B src/terraform/test_remote_backends.py
terraform fmt -check -recursive src/terraform/bootstrap
```

Also verify all modified Python code compiles, applicable project linters are available/run, source-only git diff passes whitespace checks, and no generated `.terraform`/state/plan/backend credentials enter tracked files. Treat missing tooling as a reported limitation.

### 6.5 Drift templates and monitoring infrastructure verification

After implementation, run `python3 -B src/terraform/test_drift_monitoring.py` using the same disposable-copy/provider-mocked pattern, and `terraform fmt -check -recursive src/terraform/monitoring`. These checks must not activate native schedules or contact operational state. Exercise generated GitHub workflows in temporary directories with the Task 17 test suite; validate all provider variants with `actionlint` if approved/available. Do not assert functional authentication, reviewer enforcement, notifications or scheduling from YAML lint alone. Keep source/config fixtures synthetic and nonsecret; verify rendered actions reference valid approved upstream SHAs during the separate dependency review.

## 7. Separately authorized live acceptance

Do not perform these steps merely because this plan exists. Obtain the provider, backend owner/scope, credential method, budget, resource names, retention and cleanup approval first. Use disposable accounts/projects/resource groups where feasible. Backend-only tests need no GPU; full workstation tests require separately approved minimal viable compute and the standard cleanup procedure.

For each of AWS, GCP and Azure:

1. Verify the selected Terraform/provider versions and controller identity; create or select protected backend storage through the approved workflow.
2. Verify IAM/data-plane authorization, encryption, versioning, network access and denied unauthorized identity. Run the explicit disposable lock/write probe.
3. Apply a tiny non-GPU acceptance fixture using the real backend. From another isolated controller, attempt a conflicting state mutation and prove native locking prevents simultaneous writes; clean up the fixture after testing.
4. Deploy an approved small workstation through the normal wrapper with remote state selected. Verify real outputs, valid connection material and successful downstream orchestration; no local `.tfstate` dependency.
5. On a fresh controller, attach using the manifest/config and independently supplied credentials. Verify no duplicate resources or state ownership; plan shows no unexplained changes.
6. Exercise supported stop/start, repair and accurate remote plan. Confirm state/manifest freshness after each mutation.
7. Exercise migration/restore only on disposable test states; verify resource identity and lineage checks, no unintended creation/destruction and recovery from an interrupted step.
8. Destroy the workstation through the wrapper. Independently check cloud APIs for managed VM/disk/network leftovers; verify backend storage and unrelated states/registries still exist.
9. Record bounded sanitized evidence: commands, exit status, resource identifiers where approved, state lineage/serial comparisons, lock behavior and teardown result. Never paste full state, credentials or sensitive outputs.
10. Stop idle compute immediately; destroy approved disposable workload resources. Retain durable backend resources according to the approved retention policy, disclose ongoing storage costs, and retire disposable bootstrap resources only through the separate approved procedure.

A backend is not accepted until these provider-specific outcomes are recorded. If only fixture acceptance passes, label it backend-accepted but workstation integration unverified.

### 7.1 Additional drift acceptance, separately approved per executor

Use disposable non-GPU resources wherever possible. Approval must name the specific external change, restoration, identities, notification destination, scheduler duration and cleanup policy. Do not deliberately expose storage, revoke production access or weaken production encryption to demonstrate detection.

1. Establish a reproducible clean baseline, run the detector and verify coverage, source/state identity and no mutation. Confirm detector credentials cannot apply workload changes.
2. Make one approved benign out-of-band change to a supported disposable resource property. Detect it as external drift, then change the desired configuration separately and verify it is classified as desired change rather than unauthorized drift.
3. Submit a correction proposal. Prove missing/expired/mismatched approvals are refused and no resource changes occur. Approve the exact operation, execute it with the separate correction identity, and independently verify both the cloud property and a clean covered follow-up plan.
4. Test shared backend policy checks without risking production state. For inaccessible-state scenarios use isolated test identities/resources; prove the report is blocked/error, not clean, and that correction follows the independent owner/break-glass procedure without creating an empty replacement backend.
5. For each selected GitHub configuration: generate/inspect/install in an explicitly approved test repository, configure OIDC and real environment protections, then verify trusted manual and scheduled runs, rejected unauthorized identities, actual independent remediation approval and selected alert delivery. YAML validation alone is insufficient. Do not publish raw plans/state as evidence.
6. For each selected native executor: explicitly provision the disposable monitoring stack, verify one actual scheduled run, target/runtime identity separation, report delivery and teardown. If optional policy remediation is selected, verify current-condition checks and ownership conflict prevention independently of Terraform correction.
7. Exercise lock contention and stale findings between detection and remediation. Verify re-planning invalidates changed approvals, active applies are not cancelled, and a deliberately stopped workstation remains stopped unless an explicit operation requests otherwise.
8. Pause a test scheduler for an approved window; verify an independent watchdog reports overdue checks and subsequent successful runs restore freshness. Test notification delivery failure and incident deduplication without falsely resolving drift.
9. Remove approved disposable jobs/schedules/rules/resources, retain reports/state only per the approved policy, and independently check residual billable resources. Record sanitized receipts by provider, executor, detection scope and correction mode.

Maintain separate acceptance labels for backend support, workstation lifecycle, drift detector, GitHub generation, GitHub live execution and each native adapter/correction mode. A missing optional adapter does not invalidate accepted local/backend behavior, but must remain explicitly unavailable rather than advertised as working.

## 8. Delivery order, risks and decisions

**Dependency order:** Task 1 safety guard → Tasks 2–4 contract/runner → Task 5 provider bootstrap slices and Task 6 CLI → Tasks 7–8 deployment/lifecycle → Tasks 9–10 attachment/migration → Tasks 11–12 planning/TUI → Task 13 backend documentation and verification → Tasks 14–15 drift contract/detector → Task 16 controlled correction → Task 17 opt-in GitHub templates/generator → Task 18 selected native adapters and drift release evidence. Bootstrap providers can be developed in parallel after the shared schema stabilizes; one owner maintains the shared runner/config contract. Native adapters can be developed independently of GitHub once shared drift contracts stabilize; they do not make GitHub mandatory.

Review each slice first for requirements/safety, then for code quality. Keep provider setup independent from rollout of remote lifecycle support. Do not expose an enabled remote UI choice before the matching lifecycle path is ready; an experimental setup command must label its limits.

| Risk / decision | Default recommendation / resolution gate |
| --- | --- |
| Existing team/enterprise remote implication | Decouple tier from storage; explicit compatibility warning and saved descriptor preservation |
| Terraform minimum vs existing installations | Choose and verify native S3 lockfile-capable version; do not silently weaken locking |
| Migration and stale controllers | Exclusive maintenance window, relocation record, tested source write fence or retirement of all writer identities/controllers; no claim of atomic cross-backend locking |
| Recovery metadata contains secrets | Allowlisted manifest and external secret references; no raw metadata-directory upload |
| Backend and workload in different ownership scopes | Explicit scope fields and independent auth preflight; same-cloud only in v1 |
| Shared Terraform plugin data in Docker | Per-operation container-local data dirs; preserve macOS workaround |
| Remote mutation race with direct VM start/stop | Detect known active mutation and require operator coordination; no unsupported distributed workflow-lock claim |
| Empty state but manually orphaned resources | Fail closed on uncertain history; destruction verification includes approved independent cloud checks |
| Backend storage lifetime/cost | Durable by default; separate retirement and retained-state inventory |
| State schema/provider changes during recovery | Match saved source/lockfile identity; do not silently upgrade or execute arbitrary manifest-specified code |
| Private endpoints | Opt-in, controller reachability proven; no silent public exposure workaround |
| Backend opt-in mistaken for monitoring opt-in | Keep detection/schedules/correction separate; offer local CLI, GitHub or native executor explicitly |
| GitHub scheduled runs delayed/disabled | Track freshness and use a separately enabled independent overdue-check monitor |
| Repository cannot enforce required reviewers | Detection-only until a verifiable approval mechanism exists; no silent gate downgrade |
| Detection credentials leak state or gain mutation rights | Pinned trusted code, narrowly scoped identities, private plans and allowlisted summaries |
| Native policy and Terraform repair compete | Explicit resource/attribute owner map and one reconciliation executor; stop on oscillation |
| Intended stop/config update reported as unauthorized drift | Recorded lifecycle intent, last-applied baseline and separate desired-change classification |
| Approval becomes stale while queued | Bind plan/baseline/state identity, expire approval and reapprove changed actions |
| Shared backend/monitor resources deleted with a VM | Separate durable owner stack and explicit retirement/retention policy |

Open implementation-time decisions must be recorded here before the affected task proceeds: supported Terraform/provider versions; exact cloud CLI/API method for conditional manifest writes; minimum secret/input set required for full fresh-controller repair; optional organization-specific IAM/private networking. These require design decisions, not guesses about the user's real cloud resources.

Drift setup additionally requires the user's executor choice, scopes/deployments, schedule and missed-check deadline, notification destination, provider identity references, approved correction policy and repository protection requirements if using Actions. Unknown values remain placeholders in previews; do not infer them from local credentials or create paid services to discover suitable defaults. Revisit provider-native alternatives during Task 18 before selecting an implementation slice.

## 9. Authoritative references to verify during implementation

These are reference targets, not claims that live provider behavior was tested during planning:

- Terraform backend configuration: https://developer.hashicorp.com/terraform/language/backend
- S3 backend, permissions and locking: https://developer.hashicorp.com/terraform/language/backend/s3
- GCS backend, credentials and object naming: https://developer.hashicorp.com/terraform/language/backend/gcs
- Azure Blob backend and Entra/OIDC authentication: https://developer.hashicorp.com/terraform/language/backend/azurerm
- Initialization/migration semantics: https://developer.hashicorp.com/terraform/cli/commands/init
- State locking/recovery: https://developer.hashicorp.com/terraform/language/state/locking
- Terraform JSON outputs and sensitive values: https://developer.hashicorp.com/terraform/cli/commands/output
- Provider resource schemas must be checked against the selected locked AWS/Google/AzureRM versions, not only the latest docs.

## 10. Definition of done and implementation ledger

**Overall status: partially implemented; full-plan definition of done NOT met.** The completed milestone below records delivered foundations without reducing the original acceptance criteria. An unchecked full-product criterion means it has not been signed off for the complete release, not necessarily that no supporting code exists.

### 10.1 Completed milestone: safety and offline foundations

Evidence baseline: the implementation checkpoint [20260910_193701_a5b58500](../../memory/sessions/20260910_193701_a5b58500.md) records **237 passing tests across 15 targeted suites**, with warnings treated as errors and no skips. The execution report is `/tmp/isaac-backend-final-g1vj2d8b/results.json` (temporary, local evidence). This is the recorded implementation run, not a claim of a new full-suite run each time this document is edited.

- [x] Local defaults and explicit backend-selection precedence are covered; unsupported remote execution is refused rather than silently redirected.
- [x] Immutable BackendSpec, native-cloud field adapters, strict nonsecret configuration parsing and version gates have offline tests. This does not establish provider/bootstrap compatibility or live storage ownership.
- [x] Legacy-local destroy/output guards reject missing, malformed, ambiguous and known-remote state; regression tests cover path/symlink safety and preservation of recovery files on failure.
- [x] The isolated runner foundation has a real provider-free local apply → fresh-context output → destroy test, plus locking, cancellation and saved-plan integrity tests. Production lifecycle callers are not yet integrated.
- [x] Possible `errored.tfstate` is retained instead of deleted during runner cleanup. Retained staging is private but not reboot-durable; secure manual recovery remains necessary.
- [x] The offline validation CLI, Bash completion and four public backend examples are available; validation explicitly does not establish cloud readiness.
- [x] Host-wrapper non-TTY execution/exit codes and backend rejection before cloud authentication/discovery have regression coverage. Generic public-IP/git-ref lookups and outside-container Docker startup are not claimed to be offline.
- [x] Targeted regression evidence and implementation limitations are recorded; no live deployment, migration, drift workflow or shared-ledger publication was performed.

### 10.2 Task delivery ledger

| Plan tasks | Current delivery status | Work still required for task/release acceptance |
| --- | --- | --- |
| 1 — safety regressions | Implemented at the legacy-local boundary | Carry these guarantees through the backend-aware lifecycle; mocked failures are not live remote acceptance. |
| 2 — compatibility baseline | Partial: schema adapters and runtime feature gates | Validate selected Terraform/provider/bootstrap combinations and provider lockfiles. |
| 3 — configuration and selection | Partial: validation, precedence and fail-closed selection | Complete saved-descriptor identity/attachment integration; refusal is not migration support. |
| 4 — isolated runner | Partial: production local deploy/import/destroy integration exercised; review fixes in progress | Finish all backend-aware consumers and durable recovery/release gates before remote mutation. |
| 5 — durable bootstrap | Partial: create-new stacks, explicit plan/apply CLI, proposals and read-only doctor implemented | Complete reviewed use-existing/ownership/effective-IAM, restore and provider-specific acceptance; read-only checks leave write/locking status unknown. |
| 6 — setup/CLI integration | Partial: explicit setup commands and credential/admin-root transport exercised | Finish concrete authenticated controller integration, write probes and end-to-end command parity; local transport is not identity proof. |
| 7–12 — remote lifecycle, recovery, migration and acceptance | Partial components under implementation/review; not delivered end-to-end | Integrate exact manifest/claim/state-content contracts, recovery/migration and TUI; fix review findings and verify concrete lifecycle consumers. |
| 13 — user-facing integration/documentation | Partial: examples and limitation documentation | Finish CLI/TUI/operator documentation and workflow parity. |
| 14–18 — drift and configurable automation | Partial: detector/approval contracts, private baselines, inert workflows and disabled native stacks exercised | Complete concrete detector/approval/reporting/watchdog integration and independent review; runtime, identity, notification and correction acceptance remain open. |
| 19–23 — optional shared evidence ledger | Partial trust/cache primitives under review; no registry/service/pilot delivery | Complete publication/admission and selected synchronization path; optional service and comparative pilot decisions remain separate. |

Live acceptance requires separate authorization, but that is not a reason to mark unfinished implementation complete. Record each provider as untested, blocked or verified with evidence; do not infer one provider's readiness from another's tests. The optional ledger has its own acceptance checklist in section 11 and must not be presented as delivered with the core foundation.

The intermediate [implementation/review checkpoint](../../memory/sessions/20260910_204512_c2887b81.md)
records **350 passing tests across 23 suites**, including provider-free local Terraform
execution. It is not a final run over all changing components or a clean final review.
Native scheduler pinned-provider schema/mocked-plan verification is distinct from live
operation. Follow the [work log](terraform-remote-backend-implementation-log.md) for review
findings and integration gaps; none of the full-product boxes below is closed by this update.

### 10.3 Full-product acceptance criteria — still open

The original requirements below remain unchanged. Mark an item complete only when its whole stated scope is implemented and verified, citing the relevant tests/review or separately authorized live acceptance. Passing the foundation milestone alone does not close these criteria.

- [ ] Local remains the default and works without backend setup.
- [ ] Users explicitly choose remote storage; no silent bootstrap, fallback or migration.
- [ ] GCS/S3/Azure Blob adapters and version gates are implemented and independently reviewed.
- [ ] Durable bootstrap and use-existing workflows have tested protection/IAM contracts.
- [ ] Terraform commands use isolated contexts and one saved backend identity.
- [ ] Every output, lifecycle and connection consumer is backend-aware.
- [ ] Destroy cannot claim success or delete recovery material on unknown/failed state.
- [ ] Fresh-controller attachment works with protected manifests and external credentials.
- [ ] Explicit migration preserves resource ownership and has a tested failure-recovery path.
- [ ] Offline validation and remote speculative plan are accurately distinguished.
- [ ] CLI/TUI/docs/operator skills agree on behavior and limitations.
- [ ] Existing and new offline suites pass; security, cancellation and concurrency cases are covered.
- [ ] Live backend and workstation acceptance is recorded separately for AWS, GCP and Azure.
- [ ] Drift scopes, last-applied baseline and structured reports distinguish external drift, desired changes, policy failures, errors and coverage/freshness limits.
- [ ] Detection cannot apply resource changes; corrections require valid scoped approval and independent post-checks.
- [ ] User-configurable inert GitHub templates and deterministic generator support validated AWS/GCP/Azure configurations without implicit installation/activation.
- [ ] Generated workflows enforce OIDC identity separation, trusted inputs, actual approval protection, sanitized reporting and safe concurrency.
- [ ] Optional scheduling/notifications expose failures and missed checks; alerts and native services are activated only when explicitly chosen.
- [ ] Cloud-native capability/ownership decisions are documented; selected adapters are independently tested and unsupported combinations remain unavailable.
- [ ] Workflow/native drift acceptance and correction modes are recorded separately from backend/lifecycle readiness.
- [ ] No secrets/state artifacts committed; no unapproved environment edits or cloud resources left running.

Planning completion and foundation completion are not full-plan completion. Keep remaining boxes unchecked until backed by the specified evidence; record provider-specific blockers rather than filling gaps with assumed success. Update the task ledger and evidence alongside future checkbox changes rather than weakening the definition of done to match partial delivery.

### 10.4 Review guide: remaining work and remote-mutation gates

**Status snapshot: 2026-09-10, after the latest review-fix batch. The feature is partially implemented, not ready for remote production use.** This section summarizes the remaining work for human review; it does not lower section 10.3's acceptance criteria. Earlier milestones and the implementation work log contain historical intermediate statuses. Worker-reported fixes are not independently accepted until re-reviewed against a consistent code snapshot.

#### Remaining tasks, in recommended order

| Order | Remaining task | Completion evidence required |
| --- | --- | --- |
| 1 | Independently review the latest drift/workflow, baseline/history, migration/controller, approval-issuer, deployment-state and TUI fixes; review the new local drift CLI integration. | Reviewer checks actual code and reproduces each regression; explicit scoped pass/fail, with unresolved findings listed. |
| 2 | Resolve the three registry-related suite failures around changed inventory-output behavior. | Establish whether code or fixtures violate the intended contract; fix the cause without weakening safety assertions, then rerun affected and integration suites. |
| 3 | Complete the reproducible test environment and run one consistent full regression. | Supported Terraform/runtime/dependencies, explicit skip accounting, exact commands and saved results for the same source snapshot. Do not add overlapping worker test totals. |
| 4 | Finish remote lifecycle wiring. | Authenticated identity/scope, protected ownership claims, saved attachment/state verification and guarded runner execution connected to deploy/apply/import/destroy and remaining lifecycle/output/connection consumers. |
| 5 | Finish recovery and migration integration. | Durable runner recovery, explicit pending-claim reconciliation, fresh-controller recovery, preserved state identity and verified source retirement/old-writer exclusion. |
| 6 | Complete remote drift and operational monitoring. | Deployment-time applied-baseline capture, verified remote checks, durable sanitized reports, notification delivery and independent overdue-check monitoring exercised end to end. Local `drift check` now exists but still needs independent integration review. |
| 7 | Implement genuinely independent remediation approval. | Authenticated distinct reviewer/executor identities, exact-plan approval, single-use consumption and immediate live revalidation. Same-UID local issuer grants remain correctly rejected; do not relabel identities or weaken that gate. |
| 8 | Complete the selected optional shared-ledger path. | Authorized identity capture, publication/synchronization, confined RDF validation and query admission. Signature/cache verification alone is not query readiness; hosting remains conditional on the pilot decision. |
| 9 | Perform separately authorized provider acceptance and reconcile documentation. | AWS/GCP/Azure results recorded individually; final CLI/TUI/operator guidance and task ledger reflect actual evidence. No inferred multi-cloud success from one provider or a mocked test. |

#### What the user needs to provide for review

**Offline code review needs no additional credentials or manual inspection of every file.** Existing implementation authorization covers offline development, tests and review. The review process must provide:

- A fixed source snapshot including untracked new files, not only ordinary `git diff` output. Creating a commit or pushing is not required and is not authorized by this checklist.
- Independent examination of each finding, its fix and its regression test.
- Integrated tests against that same snapshot, with pass/fail/skip results and limitations.
- Separate evidence for implementation, independent review and live acceptance.

**User decisions or explicit permission are needed for:**

- Test-environment dependency changes or tool upgrades; no installation was performed by this status update.
- Selecting the independent approval architecture, such as protected CI review with a separate execution identity.
- Live cloud acceptance: designated account/project/subscription, region, spending limit, permitted operations and cleanup authorization. Do not paste credentials into chat.
- Installing/activating workflows or schedulers later. Inert generation is not activation.

#### What is missing or failing in the test runs

These are observations from the status inspection and saved run logs, not permanent environment facts; recheck them before execution.

| Item | Observed limitation | Required follow-up |
| --- | --- | --- |
| Terraform | Installed version is **1.8.5**; remote policy requires **>=1.10,<2**. | Use an explicitly approved compatible test runtime and validate provider/backend combinations. Local 1.8.5 fixtures do not establish remote acceptance. |
| TUI | **Textual and Rich are absent**; full UI execution is unverified. | Declare/provision the agreed dependencies with permission and run actual headless/runtime UI tests. |
| Workflow linting | **actionlint is absent**; its test was skipped. | Run it in the agreed test environment and record the result. |
| Registry regressions | `artifact_registry`, `artifact_registry_ansible` and `container_registry_ansible` suites are nonpassing around inventory-output expectations. | Diagnose against the intended production contract, repair and rerun. These are failures, not merely unavailable tools. |
| Knowledge graph | Default Python lacks RDFLib; the worker reports passing tests in the existing graph virtualenv. | Use the correct declared runtime; do not interpret a wrong-interpreter failure as a graph regression or silently install globally. |
| Cloud acceptance | No live multi-cloud ownership, locking, restore, permission or remote-migration acceptance has run. | Execute bounded, separately authorized sandbox tests and record results per provider. |
| Aggregate evidence | Latest worker suites overlap and ran while other files changed. | Produce one consistent full-run report; earlier green totals do not supersede later review findings. |

Saved broader-run diagnostics: `/tmp/migration-review-tests-mlr0qmmg/` (temporary local evidence; retain sanitized results before relying on them long-term). Source/runtime inspection confirmed the installed version and missing UI/lint dependencies; this documentation edit is not a new test execution.

#### Remote execution integration — clarified implementation scope

**The refusals below are temporary implementation restrictions, not inherent cloud/Terraform limitations or reasons to postpone implementation.** Complete backend-aware execution rather than treating every optional coordination feature as a prerequisite. In the inspected source:

- `src/python/terraform_runner.py`, `TerraformRunner.apply()` (lines 590–594), refuses nonlocal backends.
- `TerraformRunner.import_resource()` (lines 609–617) refuses remote import without the integrated ownership/attachment path.
- `TerraformRunner.destroy()` (lines 639–643) refuses remote destruction.
- `src/python/deployment_state.py` defines a trusted `mutation_adapter`/guard contract, but that interface alone is not a production mutation bridge.
- `src/python/backend_controller.py` supplies restricted **read-only** authenticated adapters. Its read receipt is deliberately not write authority. The current credential modes also do not establish CI/OIDC parity.

The core deployment path must provide these practical safeguards:

- [ ] Configure supported backend/provider authentication and explicit project/account/subscription scope. Different backend and workload identities are legitimate when deliberately configured and authorized.
- [ ] Persist the selected backend location; reject accidental new-deployment reuse and unknown access failures. Existing remote state is normal for an existing deployment; explicit attachment/migration must not be confused with silent adoption.
- [ ] Use native backend locking and Terraform saved-plan/state consistency checks. Native locking does not prevent selection of the wrong destination or duplicate management through separate states.
- [ ] Execute the deliberately selected source, inputs and provider locks through an isolated operation and saved plan. Ordinary configuration updates do not require reconstruction of a last-applied baseline; baseline reconstruction remains important for drift comparison and recovery.
- [ ] Retain durable recovery evidence after partial apply, failed state writes or uncertain publication; temporary runner staging is not reboot-durable.
- [ ] Verify post-operation state/publication, destroy cleanup and migration/source-retirement behavior, including failure paths.
- [ ] Obtain independent code-review approval and provider-specific acceptance evidence before release.

Custom distributed reservations/claims, continuous state-content attestation, independent drift-approval issuers and shared-ledger admission are separate capabilities, not universal prerequisites for user-requested deployment. Preserve protections for already-written claim/migration records while reconciling existing code; do not bypass them blindly or remove the remote refusals without connecting and testing the actual execution path. This clarification supersedes broader prerequisite wording elsewhere in the plan for the initial remote-backend delivery; it does not declare existing code complete.

Bootstrap is a separate boundary: explicitly creating backend infrastructure uses its own local administration state. It does **not** enable remote workstation mutation. Likewise, the dedicated supervised migration service is not proof that general remote lifecycle mutations are ready. Terraform state storage in the cloud also does not imply Terraform execution runs in the cloud.

**Recommended sequence:** deliver the GCS deployment/lifecycle path and usable local–cloud file synchronization below → independently review and run authorized GCP acceptance → complete S3/Azure parity → optional advanced drift/ledger capabilities. IAP/security and Neo4j infrastructure can proceed independently of those optional capabilities.

### 10.5 Immediate solution: remote Terraform state and local–cloud file sync

**User requirement:** provide both a usable remote backend and an explicit way to synchronize selected local work with cloud storage/workstations. Do not delay this delivery for research into another repository or completion of optional trust frameworks. This is an implementation specification, not a claim that the proposed options already exist.

#### Separate the two kinds of data

| Data | Mechanism | Authority and lifecycle |
| --- | --- | --- |
| Terraform infrastructure state | Native GCS backend first; S3/Azure parity afterward | Terraform is the writer. State bucket survives workstation destruction. Use Terraform's explicit migration, never rsync `.tfstate` or `.terraform`. |
| Working files: selected code, assets, datasets, models and results | rsync over SSH; GCP private VMs use an IAP-backed SSH transport | Explicit push or pull per selected directory. No implicit bidirectional merge or automatic destructive mirroring. |
| Durable off-VM file copies | Optional `gcloud storage rsync` to a separate data bucket/prefix | User selects what to copy and when to restore. Object storage is not a POSIX filesystem; permissions/symlink semantics need documented handling. Data storage is separate from Terraform state. |
| Neo4j data | Database-consistent backup/export and restore | Do not rsync a live database data directory. Independently retained database storage/backups must survive GPU workstation teardown. |

#### Existing code to extend, not replace with another framework

- `upload`: rsync from configured local uploads directory to a selectable remote directory; currently direct-IP/key SSH, host-key checks disabled and deletion enabled by default.
- `download`: rsync from a remote results directory to local results; currently direct-IP/key SSH, host-key checks disabled, deletion enabled by default and elevated remote rsync.
- `src/python/gcp.py`: existing IAP SSH helper. Reuse its intended connection behavior after checking argument handling; it is not yet proof that rsync/IAP works.
- `src/python/utils.py`: output/discovery consumers must resolve the saved backend rather than require a local state file.
- `.agents/skills/isaac-automator/transfer-data/SKILL.md` and README data-transfer section: update alongside command behavior.

#### Delivery sequence and acceptance

1. **Finish GCS backend execution.** Connect `backend_selection`, `TerraformRunner`, `Deployer` and lifecycle/output callers. Support create-new/use-existing storage, explicit saved destination and local-to-GCS migration. Keep local default and do not automatically migrate registry states. Verify deploy → outputs → fresh-controller management → destroy, leaving the bucket intact. Code review and offline tests precede separately authorized cloud execution.
2. **Create one reusable connection description for transfer and shell operations.** Carry instance/project/zone, SSH identity and known-host policy from the deployment configuration/authoritative outputs. Support ordinary SSH and GCP IAP without requiring a public IP; handle OS Login deliberately. Do not assume the username/key path from direct SSH works for every OS Login configuration. Use scoped IAP/OS Login permissions and retain SSH host verification.
3. **Extend `upload`/`download` for selected paths.** Preserve existing folder conventions; add explicit local-path selection, dry-run, exclusion rules and resumable partial transfers using supported rsync options. Make deletion opt-in, document that compatibility change and show affected deletions in preview. Avoid blanket `sudo rsync`; use the selected user's writable directories. Quote local and remote arguments safely, bound subprocesses and preserve exit status/cancellation.
4. **Add named transfer mappings.** Each mapping names a local directory, a remote directory and a direction (`push` or `pull`). Suggested use: local source → cloud workspace; cloud results → local results. Reject overlapping contradictory mappings; define which side wins instead of running two mirrors and calling it conflict resolution. Scheduling is optional and off by default.
5. **Add optional durable GCS data sync.** Implement explicit upload/restore for selected data prefixes, separate from state. No deletion by default. Do not promise a cloud copy exists until transfer and verification succeed. Explain egress/storage costs and distinguish VM-mounted persistence from off-VM backup.
6. **Verify and document the complete workflow.** Test direct SSH and IAP argument construction, explicit direction, spaces/special characters, exclusions, dry-run, no-delete default, overwrite behavior, interrupted/resumed transfers and surfaced failures. Exercise real rsync against disposable local fixtures where available, then a user-authorized private GCP VM. Confirm remote-state deployments can use upload/download without reading stale local `.tfstate`.

**Transfer safety defaults:** exclude Terraform state/staging, credential/key files, `.env`, local secret stores and live database directories from general workspace mappings. Use scoped allowlists; a broad home-directory or repository mirror is not the default. Credentials use the existing explicit authentication transport, not file sync. Rsync push/pull may overwrite changed files even without `--delete`; previews and documented source-of-truth rules must make that clear. Remote absence/read failure must never trigger local deletion.

**First usable milestone:** deploy a GCP workstation with GCS-managed Terraform state, connect through IAP, push a selected local working directory, pull results, optionally retain a data copy in GCS, and destroy the workstation without deleting backend/data storage. Neo4j deployment/ingestion is a parallel infrastructure track, not a dependency of this milestone. Full S3/Azure and optional drift/ledger acceptance remain separate tasks, not silently dropped scope.

### 10.6 GCS implementation and live acceptance update — 2026-09-11

This dated update supersedes older statements that **all** ordinary remote operations
remain unimplemented; it does not mark the entire 23-task plan complete.

- GCS native execution and persisted backend-aware output/lifecycle integration are
  implemented. S3/Azure ordinary remote execution remains outside this enabled slice.
- Selected-directory rsync upload/download, IAP/OS Login endpoint selection, opt-in
  deletion, previews, safe defaults and explicit host/container directory mapping are
  implemented and independently reviewed. The final scoped same-snapshot regression
  has **536 passed, 1 skipped across 35 suites**; exclusions and review boundaries are
  explicit in the acceptance report. Private noVNC uses a loopback IAP tunnel.
- Real GCS permission and native Terraform experiments passed in **cybernetic-renan**
  (the actual project ID). The Automator GCS runner also passed live init/apply/read/
  destroy with a provider-free resource, including a fresh read-only controller context.
- A separate private e2-micro Terraform experiment verified creation, no public IP,
  Shielded VM settings and stop/start. Its VM, disk, network resources and backend were
  destroyed and absence verified. No GPU or NAT gateway was provisioned.
- All seven temporary experiment buckets were deleted, including object versions.
  Exact short-lived usage charges are not measured; zero cost is not claimed.
- The current identity lacks IAP tunnel access in both project and instance probes.
  No IAM grants were added. Live IAP rsync and complete GPU/Isaac installation remain
  unverified. This is an actual permission/acceptance gap, not a ledger/approval prerequisite.
- A subsequent Docker-image live test was blocked before execution by the approval
  tool and was not retried. Further live experimentation awaits user approval.

Detailed resource accounting, evidence, review findings and final test results:
[GCS acceptance report](terraform-gcs-acceptance-20260911.md).

## 11. Optional shared evidence ledger and local agent caches

### 11.1 Research conclusion and project-specific baseline

**Provisional recommendation:** beneficial for a team repeatedly investigating the same revisions, but begin with a shared registry of reviewed immutable RDF generations and verified local caches. Introduce an authenticated bounded query service only if the pilot demonstrates a collaboration/availability need. Add a Neo4j query projection only if measured traversal/visualization needs justify it. Do not start with a multi-writer database in which every agent's local memory is automatically merged.

Source inspection and a read-only `./knowledge-graph status` check on 2026-09-10 found a current index containing 24 sources, 226 claims and 127 entities, labeled `static_only`. This is a planning observation, not a scaling benchmark or a permanent expected count. Relevant implementation facts:

- `src/knowledge_graph/publication.py:12-14,86-144` publishes bounded, immutable local artifact generations with integrity hashes, a local writer lock and atomic `current` replacement. Filesystem permissions and same-host locks are not a remote authentication/publication protocol.
- `src/knowledge_graph/cli.py:32-37` derives cache and Neo4j scope identifiers from the absolute checkout path. `src/knowledge_graph/snapshot.py:17-24,134` already gives admitted content a repository/policy-based snapshot identity; a team registry must bind that identity to a trusted repository/revision without confusing it with the path-derived visualization scope.
- `src/knowledge_graph/cli.py:74-80,131-138` checks source/policy/extractor freshness before releasing results. `src/knowledge_graph/queries.py:8-17` exposes fixed bounded operations, not arbitrary Cypher or semantic/vector search.
- `src/knowledge_graph/README.md:70-78` explicitly distinguishes integrity hashes from digital signatures; JSON/NetworkX are derived from RDF and the original source remains authoritative about implementation. The owner-only local cache is not a shared network filesystem design.
- `src/knowledge_graph/neo4j_projection.py:1,16-60` creates a one-way visualization payload. `.agents/references/docs/evidence-graph-agent-guide.md:157-187` documents replacement of owned projection data, snapshot-only freshness and no preservation of user-authored edges attached to that projection.
- `ai/evidence-graph.agent.md:19-22` and `.devcontainer/neo4j/README.md:92-106` prohibit treating the current developer/admin database as an agent-safe retrieval backend. The optional package manifest `requirements-knowledge-graph.in` does not provide a network service framework or remote authentication stack.

The current codebase evidence graph should not be confused with Microsoft's GraphRAG indexing pipeline: that pipeline extracts entities/relationships/claims using LLMs, performs community detection and produces summaries/embeddings.[23] Adopting those mechanisms would be a separate retrieval-quality experiment, not a necessary consequence of hosting this existing ledger remotely.

### 11.2 What “one source of truth” should mean

Use one authoritative publication catalog **per authorized team/repository/revision/policy**, not one undifferentiated global graph. All authorized users can select the same reviewed generation, while different branches, forks, policy versions and organizations remain distinct. A graph is a source of attributed evidence, not the ultimate authority for every kind of fact:

| Kind of information | Authority | Shared representation |
| --- | --- | --- |
| Intended code/configuration | Reviewed Git revision and admitted source fingerprints | Canonical RDF static evidence with exact source locators |
| Terraform resource ownership | Selected Terraform backend and saved deployment identity | Optional nonsecret reference only; never raw state in the graph |
| Actual cloud/runtime condition | Fresh authorized detector/verification result, within its coverage | Optional separately access-controlled observation receipt with timestamp and expiry |
| Human decision/runbook | Approved document/change record and accountable author | Separate reviewed assertion with provenance, not a fabricated code fact |
| Agent interpretation or dirty local edits | Local hypothesis/private working context | Local-only overlay; proposed contributions require review before publication |

W3C PROV describes entities, activities and people involved in producing data so consumers can assess its provenance.[24] Preserve that distinction: provenance, SHACL conformance, signatures and graph consensus do not establish that an assertion is true or a deployment passed. Conflicting claims remain attributed and visible; neither majority agreement between agents nor a last-write-wins update resolves them.

**Important scope default:** share the currently admitted public codebase evidence only. Personal Hermes memory/session stores and other agents' histories are not this ledger and are never synchronized implicitly. Any later drift/installation/test observations need a separate schema, tenant/deployment ACL, retention policy, authorized ingestion path and user approval. Static `supported` evidence must never be promoted into a successful runtime observation.

### 11.3 Options and expected trade-offs

| Option | Useful when | Cost/complexity and boundary |
| --- | --- | --- |
| A. Existing local graph with Git-reviewed source/policy | One contributor, short-lived branches, offline-first work | Simplest; repeat indexing and different generations must be managed explicitly. No shared service outage or database administration. |
| B. Shared signed snapshot registry + local caches (**recommended pilot**) | Several agents/users need identical reviewed evidence and easy onboarding | Object storage/artifact publication, signing/trust and revocation management; no always-on graph database required. Retains fast local bounded retrieval, subject to measured performance. |
| C. B plus authenticated bounded query API | Clients lack the local graph runtime, centralized access/audit is needed, or cache distribution becomes impractical | API hosting, identity/authorization, availability, quotas and cache isolation. Serve canonical-derived JSON/RDF initially; Neo4j is optional behind the same contract. |
| D. C plus hosted Neo4j projection | Measured query scale, richer graph exploration or centralized visualization warrants it | Database/license/backup/network costs and an additional freshness boundary. No direct unrestricted agent Cypher or shared admin credentials. |

Neo4j Aura offers a managed graph database service, while self-hosting keeps operations under the project's control.[28] Managed database hosting does not implement our RDF publication, provenance, client cache validation or bounded agent API. Verify the selected tier's supported region, private networking, authorization, backup/export and recovery terms before committing; do not assume a free tier supplies production isolation or availability.

Neo4j's authorization documentation distinguishes Enterprise security capabilities from the limited user management available in Community.[27] Do not deploy the current Community admin-only developer pattern as a shared multi-user endpoint. Choose a verified reader/writer privilege model where available; otherwise keep Community behind a narrow trusted service and explicitly acknowledge that its database credential is still powerful, with weaker defense in depth. For strict tenant separation, reject a topology whose isolation cannot be independently demonstrated.

Neo4j's backup documentation also distinguishes Community dump/load from additional Enterprise online-backup facilities.[22] A persistent volume is not an off-host backup. Since Neo4j remains derived, favor tested rebuilds from canonical generations; independently preserve identity configuration, catalog/approval records and any intentionally retained audit records.

### 11.4 Recommended architecture and lifecycle

```text
Reviewed Git revision + exact public admission policy
    -> isolated publisher (confined extraction, RDF/SHACL validation)
    -> immutable canonical bundle + signed provenance
    -> protected object/artifact registry + versioned publication catalog
          |                                  |
          | explicit verified pull           | optional materializer
          v                                  v
    per-user local cache              read-only query projection
    + private local overlay           (JSON/RDF first; Neo4j optional)
          |                                  |
          |                                  v
          |                          authenticated bounded API
          +------------------+---------------+
                             v
                  local agents: cited evidence
```

**Two distinct backends:** the Terraform backend stores infrastructure state; the evidence registry stores approved graph artifacts/catalogs. The graph service infrastructure may itself be managed through a separate Terraform stack using the accepted remote-state runner. Its database, graph objects and credentials must not be stored in the Terraform state bucket/container namespace or inherit workstation state-reader roles. Use separate storage resources and IAM for the first shared deployment, even when the same provider/account hosts both.

Use independently managed non-GPU service infrastructure, never an individual user's workstation or the monitored GPU VM. Shared-service destroy requires a separate scope and approval; workstation teardown must not remove the evidence registry, API, signing keys or database. Do not copy the development Compose topology to public ports: its HAProxy gateway is a TCP forwarder, not team authentication or a tenant-aware authorization layer.

**Publication protocol:**

1. Register an issuer-controlled organization/repository identity with an explicit binding to the approved source repository; do not trust a caller's `repo_id` string, branch label or absolute checkout path. Scope forks and organizations separately. Include exact Git revision, admitted content manifest, policy digest, extractor/locked dependency versions, schema and generation digest. Record the checkout-local identity separately, never as the shared identity.
2. Only a trusted publisher may publish accepted generations. Run extraction in the existing confined worker with reviewed public inputs; no private state, arbitrary repository URLs, credential mounts, Docker socket or network-capable parser escape. Pull requests/agent candidates are untrusted and cannot publish or widen admission automatically.
3. Publish complete content-addressed bundles to staging with hard byte/count/schema limits. Revalidate the RDF and derive/compare the JSON claims/entities instead of trusting independently edited sidecars. Integrity hashes detect corruption, but signatures/attestations and pinned publisher identity establish provenance. GitHub artifact attestations can bind an artifact to a workflow/repository/commit; use them only if the chosen publication platform supports the required verification, otherwise use an approved signing service.[26]
4. Promote a verified generation by conditional catalog update using the expected previous catalog version. S3 documents `If-None-Match`/`If-Match` conditional writes; GCS provides generation-match preconditions; Azure Blob supports ETag/`If-Match` optimistic concurrency.[25][29][30]
5. Catalog pointers are qualified by repository/revision/policy/channel; immutable accepted generations are never edited in place. Include publication status, actor, approval, revocation epoch and digest in a protected receipt. Conflicting promoters must retry/review rather than overwrite each other. Unknown commit outcomes require read-back by generation/receipt, not unconditional republish.
6. Materialize any Neo4j generation into a separate inactive namespace, validate completeness against canonical claim records and then expose that exact generation. Catalog promotion and a database import are not one cross-system transaction. If the projection lags or fails, return not-ready or use an explicitly selected canonical path; never label the old projection current. Preserve the existing no-mixed-snapshot rule and include conditional/disputed claims in the contract, not just supported visualization edges.
7. Retain content-addressed history per the chosen privacy policy, with independently backed-up catalog, trust configuration and revocations. Immutable means no in-place edits, not an unreviewed permanent retention lock; withdrawal/deletion must account for published objects, projections, local caches and backups.

**Local client synchronization:**

- Local agents are readers by default. Add proposed explicit `knowledge-graph remote status`, `remote pull` and `remote query` commands; ordinary local queries remain local and do not silently upload or download. Any later automatic pull setting must be a user-selected policy with documented cache writes and network use.
- Retain independent local-policy authority: a remote publisher cannot enlarge a client's admitted source set. Local queries over imported bundles still require the supported confined validator/runtime. For clients without that runtime, a separately packaged lightweight remote-query adapter may consume bounded validated API responses labeled `approved_revision`; it must not deserialize raw RDF unsandboxed or pretend local-checkout verification occurred.
- Pull an approved generation into a temporary owner-only directory outside the repository; enforce authentication, endpoint allowlisting, schema/size limits, digest/signature verification, publisher/repository/revision binding and current revocation policy. Verify all files before atomic activation. No shared writable NFS cache, rsync of Neo4j data volumes or disabling existing symlink/special-file protections.
- Compare the imported admitted source/policy/extractor fingerprints with the local checkout before calling results `current_checkout`. A signed remote snapshot of `main` is not current for another branch or dirty checkout. Without matching local sources, return only an explicitly requested `approved_revision` answer, not a claim about local code. On mismatch, offer an authorized local reindex or explicit historical-revision query; never merge incompatible generations silently.
- Keep local hypotheses and uncommitted-source evidence in a separate private overlay with base generation and provenance. Initial shared mode does not publish overlays. Later contributions go through a proposal/review pipeline with source admission and tenant checks; persistent annotations cannot be attached directly to replaceable Neo4j-owned projection nodes.
- Offline use requires both a previously verified bundle and an unexpired signed authorization/revocation lease. If the policy lease expires or the generation is known revoked, withhold graph evidence as current. A disconnected client cannot learn an immediate revocation or erase previously learned data; document that bounded stale-access window and choose an acceptable lease/retention policy. Do not turn local unavailability into silent remote fallback.
- Responses expose requested/effective repository/revision, generation, source/policy fingerprints, evidence class, freshness/lease status, transport (`local`, `verified_cache`, `remote_api`), backend (`canonical` or `neo4j_projection`), claim IDs, coverage and truncation. Add an optional sanitized request/receipt ID so users can verify that an agent actually queried this service rather than merely having it configured. Avoid logging query bodies, source text or personal conversations by default.

### 11.5 Service security, agent integration and drift correlation

For the optional API, offer only the existing fixed query operations with typed inputs, bounded depth/results/time, rate limits and cancellation. No arbitrary Cypher/SPARQL, URLs, plugin/procedure execution or writes supplied by an agent. Keep parsing confined; do not add network privileges to the extraction worker merely to host an API. Select a separately packaged service runtime only after inspecting dependency/security requirements.

Authenticate users/workloads with an approved identity provider and short-lived credentials. Authorize every request and cache lookup by tenant, repository, revision/generation and evidence class **before** traversal; checking only the returned rows is insufficient. Never trust client-provided scope fields as authorization. Separate publisher, query-service, reader and admin roles; do not give an agent the developer Neo4j admin credential. Use TLS and private/explicitly approved ingress; harden any load balancer, budgets, access logs and dependency patching independently of database health.

Do not claim RBAC prevents all inference leaks in a mixed graph: use separate namespaces/databases/service instances as required, and test edges, aggregates, errors, timing-sensitive enumeration and caches for cross-tenant disclosure. Signed artifacts are still untrusted parser input and retrieved text remains data, not instructions. Do not ingest conversation instructions, forged approvals or LLM-generated claims into a trusted operational path. External model use for retrieved evidence requires a separately approved data-handling policy.

A thin CLI adapter is the first agent integration: Hermes and other repository-aware agents can call the same bounded protocol and return its provenance fields. Optional MCP registration can be evaluated later; neither a graph server nor an MCP connection proves that a model used retrieval. Do not modify global Hermes settings, VS Code settings or any other agent profile automatically. The existing advisory brief/skill must be explicitly versioned and updated only when the new transport meets its safety contract.

If drift history is later chosen, ingest only sanitized Task 14–18 receipts through a separate authenticated observation stream. Store exact deployment/backend identity digests, detector baseline, observed-at/expiry, coverage, evidence kind and report reference; never raw plans/state/SSH material. Keep observations separate from static claims and restrict them to authorized team/deployment scopes. This can help agents explain which code/rule relates to a finding, but the original detector and live preconditions remain authoritative. A graph lookup never grants remediation approval, changes IAM or invokes Terraform apply. Neither deployment nor drift checking should fail merely because the optional graph service is down.

### 11.6 Benefit hypothesis, evaluation and decision gates

**Likely benefits to test:** consistent citations for the same revision; fewer duplicate indexing/setup steps; team onboarding; reviewed annotations available to multiple agents; reproducible investigation receipts; optional correlation of sanitized findings across deployments. Sharing an approved dataset improves consistency, not necessarily truth or retrieval coverage.

**Costs/risks:** publication and identity management, signing/revocation, hosting/backup/egress, stale projections and cache policy, poisoning with a larger blast radius, tenant isolation, branch collisions, new operational ownership and possibly Neo4j licensing. More agents do not automatically justify a database server: identical small datasets can be distributed as artifacts. Limited source admission/extractor coverage remains the current bottleneck for questions the graph cannot answer; remote hosting will not reconstruct missing profile-to-Ansible paths.

Run a separately approved pilot with two isolated checkouts/agents and a representative, manually reviewed question set drawn from configuration transport, Terraform backend ownership, lifecycle safety and structural impact. Compare A (local graph/direct-source baseline), B (shared verified snapshots), and C/D only if justified. Measure:

- Correct source/claim citations, unsupported conclusions, appropriate `unknown` answers and stale/mismatched revision rejection; record actual tool use, not agent self-report alone.
- Cross-agent agreement when pinned to the same generation, plus preserved disagreement for genuinely conflicting evidence. Do not score repeated shared mistakes as success.
- Setup/indexing effort, publish-to-reader freshness, query latency, response size, LLM/tool overhead and operator maintenance time; central hosting alone does not imply token savings.
- Storage/API/compute/egress and any database-license costs, using the selected provider's actual configuration; obtain a budget before live setup rather than inventing fixed prices.
- Outage/offline behavior, revoked-generation handling, concurrent promotion, projection rebuild, recovery within user-chosen RPO/RTO and zero unauthorized cross-tenant reads in the acceptance scenarios.

Approve B if it provides material collaboration/onboarding benefit without weakening local freshness/privacy. Approve C only if remote-only clients, centralized authorization or measured distribution overhead require it. Approve D only if Neo4j demonstrates a capability/performance advantage over the canonical query implementation. Otherwise retain local graphs and Git-reviewed evidence policies. This workstream is optional and does not block accepted remote-backend/drift features.

### Task 19 — Shared identity, provenance and namespace contract (optional)

**Depends on:** Explicit approval of the public-code-only shared-ledger scope, not Tasks 14–18. If hosted infrastructure is later selected, reuse accepted backend lifecycle work. No implementation is authorized by this document.

**Files:** Create `src/knowledge_graph/shared_contract.py`, `src/tests/knowledge_graph/test_shared_contract.py`, `configs/knowledge-graph/shared.example.yaml`; modify `src/knowledge_graph/snapshot.py`, `src/knowledge_graph/cli.py`, `src/knowledge_graph/neo4j_projection.py` only where the versioned identity bridge requires it.

1. Specify issuer-bound organization/repository identity, revision/content/policy/extractor bindings, catalog version, artifact schema, trusted publisher and revocation lease. Keep personal/local overlay identity separate.
2. Write failing tests for identical reviewed sources in differently located checkouts, forks with the same display name, branch/revision mismatch, dirty admitted sources, malicious tenant selectors and incompatible schema/extractor versions.
3. Implement portable shared identity while preserving existing local path scopes and generation receipts for cleanup/migration. Never reassign existing Neo4j data to a team based on a matching repository name.
4. Define approval/signing/trust bootstrapping and rotation/revocation ownership. Checksums alone cannot authenticate another user's publication; do not store private signing keys in source or agent context.

**Gate:** Stable cross-machine identity and explicit trust/namespace boundaries are tested without publishing anything remotely.

### Task 20 — Reviewed publication catalog and immutable bundles (optional)

**Depends on:** Task 19, explicit selection of one initial object/artifact storage provider and separate publication/storage approval.

**Files:** Create `src/knowledge_graph/shared_publish.py`, `src/knowledge_graph/shared_registry.py`, `src/tests/knowledge_graph/test_shared_publish.py`, `src/tests/knowledge_graph/test_shared_registry.py`; extend `src/knowledge_graph/publication.py` through a distinct remote adapter, not replacement of its local filesystem guarantees. If the user chooses GitHub CI publishing, add an inert `templates/github-actions/evidence-publish.yml.tmpl`, not an active workflow.

1. Write failing tests for oversized/incomplete bundles, tampered RDF/JSON sidecars, signature/issuer mismatch, stale/revoked generations, concurrent catalog updates and lost promotion receipts.
2. Implement section 11.4's staged immutable upload, protected provenance and compare-and-swap catalog promotion. Publisher approval/source allowlisting stays separate from artifact integrity; do not auto-publish unreviewed agent output or arbitrary PR branches.
3. Validate RDF/SHACL and compare derived views in the confined runtime before admission; enforce offline parsing and strict artifact names/limits on both sender and receiver.
4. Test idempotent retry and read-back after unknown outcomes, signing-key rotation, revocation records, retention and restore. Reject backdating/replay of older catalogs unless a specifically approved historical revision is requested and still authorized.

**Gate:** Readers can identify one accepted generation per scoped pointer; competing publishers cannot silently overwrite acceptance or expand source admission.

### Task 21 — Verified local cache synchronization and agent receipts (optional)

**Depends on:** Tasks 19–20; preserve existing local-only behavior.

**Files:** Create `src/knowledge_graph/shared_client.py`, `src/tests/knowledge_graph/test_shared_client.py`; modify `src/knowledge_graph/cli.py`, `src/tests/knowledge_graph/test_cli.py` and `src/tests/knowledge_graph/test_publication.py`; update `ai/evidence-graph.agent.md` and its linked skill only after acceptance.

1. Write failing tests for explicit opt-in, authenticated pull, owner-only staging, byte/schema/signature limits, atomic activation, no symlink traversal, stale checkout/branch and incompatible policy/extractor rejection.
2. Add explicit remote status/pull commands with trusted endpoint and identity references; keep credentials outside profile examples and logs. Never upload the user's cache, local modifications or personal memory as a side effect of a query.
3. Implement freshness classifications, transport/backend provenance and bounded offline leases. Test revocation, unavailable authority, historical revision selection and no silent network fallback.
4. Verify two isolated clients consume the same accepted generation and return consistent claim/source identities; an unrelated fork/tenant is rejected. Test that a local overlay remains private and cannot become globally accepted evidence without a separate proposal workflow.

**Gate:** Shared evidence is demonstrably used through tool receipts while local policy and freshness remain enforced; local-only commands work with no service configured.

### Task 22 — Optional bounded service and replaceable Neo4j projection

**Depends on:** Tasks 19–21 and a pilot decision that Option C or D is warranted. Do not require Neo4j for Option B.

Run Task 23's Option B evaluation first; only a positive server decision opens this task. Then return to Task 23 for separate C/D acceptance. This is a staged evaluation, not a circular requirement to build a server before deciding whether one is useful.

**Files:** Proposed `src/knowledge_graph/service.py`, `src/knowledge_graph/shared_projection.py`, `src/tests/knowledge_graph/test_service.py`, `src/tests/knowledge_graph/test_shared_projection.py`. Add separately reviewed `requirements-knowledge-service.in`/`.lock` only after choosing a suitable optional service/auth runtime. If self-hosting is chosen, propose `src/terraform/evidence-service/<selected-provider>/main.tf`, `variables.tf`, `outputs.tf`, `README.md` and `tests/service.tftest.hcl`; do not repurpose the workstation's Neo4j role or edit the developer Compose network to expose it.

1. Write failing tests for authentication, per-scope authorization before traversal, fixed-operation validation, bounded responses/time, cache isolation and exclusion of arbitrary query language/URLs/procedures.
2. Implement the canonical query API first by reusing `src/knowledge_graph/queries.py`; retain evidence conditions/dispositions and freshness. Only then add a parameterized Neo4j adapter if justified, preserving exact-generation equivalence and no mixed snapshots.
3. Stage projections, validate canonical parity and switch routing only after readiness. Test import interruption, catalog/projection lag, duplicate delivery, withdrawal and complete rebuild without loss of reviewed annotations (which live outside replaceable graph nodes).
4. Select and verify real reader/writer privileges for the chosen database edition/tier, TLS/identity/private ingress, tenant isolation, quotas, audit redaction, backups and restore. No direct agent admin/Bolt endpoint. Use separate deploy/query/publisher credentials and approved secret references.
5. Prove shared-service teardown is independent of workstation destruction. API/database outages must not trigger cloud recreation, graph truth fabrication or failure of unrelated Terraform/drift commands.

**Gate:** Authorized remote queries match canonical evidence for their pinned generation; permissions, projection freshness and restore behavior are demonstrated for the chosen topology.

### Task 23 — Collaboration pilot, cost decision and optional observation ingestion

**Depends on:** Tasks 19–21 for Option B, Task 22 only for C/D. Sanitized drift ingestion additionally depends on accepted Tasks 14–18 and separate data-sharing approval.

**Files:** Create `.agents/references/docs/shared-evidence-ledger-guide.md`, `src/tests/knowledge_graph/test_shared_acceptance.py` and a reviewed nonsecret question fixture under `src/tests/knowledge_graph/fixtures/shared_questions.json`; update `src/knowledge_graph/README.md` and the existing evidence-agent guide. Only if observation sharing is selected, propose a distinct `src/knowledge_graph/observation_ingest.py` and `src/tests/knowledge_graph/test_observation_ingest.py` with a separately reviewed admission/schema policy.

1. Agree team/repositories, identities, source admission, selected provider/topology, budget, retention, acceptable offline revocation window and RPO/RTO before any live setup.
2. Run the comparative pilot in section 11.6 with actual retrieval traces and manually checked references. Include known unknowns, changed branches, misleading source text, stale publications and unauthorized tenant queries.
3. Exercise isolated storage/API outages, concurrent promotion, signing-key rotation, revoked snapshots, cold-cache recovery and projection rebuild. Retire only approved disposable pilot resources and report retained/billable storage separately.
4. Record measured benefits and overhead and a go/no-go decision for each option, not a blanket “Graph-RAG improves accuracy” claim. If the shared snapshot registry suffices, stop there; leave query server/Neo4j disabled.
5. If separately selected, test sanitized operational receipts in an isolated ACL-protected namespace, distinguish observations from code facts, and reject raw state/secrets or graph-authored approvals. Keep this integration advisory and optional.

**Gate:** A documented user decision backed by observed collaboration/security/cost results; remote evidence is never mandatory for backend deployment or drift correction.

### 11.7 Verification and separate acceptance ledger

After implementation, use the existing optional graph interpreter, not the deployment runtime:

```sh
"$HOME/.cache/isaacautomator-graph/venv/bin/python" -m unittest discover -s src/tests/knowledge_graph -p 'test_*.py' -v
"$HOME/.cache/isaacautomator-graph/venv/bin/python" -m unittest src.tests.knowledge_graph.test_shared_contract src.tests.knowledge_graph.test_shared_registry src.tests.knowledge_graph.test_shared_publish src.tests.knowledge_graph.test_shared_client -v
```

The named new modules are proposed Task 19–21 deliverables, not tests that exist or passed during planning. New default-discovery suites must be offline with synthetic nonsecret fixtures and mocked transports. Put live storage/service/database tests behind explicit selection, separate identities and cleanup approval; do not auto-start Docker, access real graph caches or change Neo4j via ordinary discovery. Optional API/database tests use their separately approved service runtime. Preserve existing source-policy, sandbox, freshness, CLI and Neo4j projection regression contracts.

- [ ] Shared identity/trust/publication schema reviewed; private memory and raw state excluded.
- [ ] Verified immutable publication and concurrent promotion tested for the selected provider.
- [ ] Local clients enforce revision/policy/source and revocation-lease checks, with explicit transport receipts.
- [ ] Optional service/projection has actual per-scope authorization, canonical parity and recovery evidence.
- [ ] Comparative pilot records retrieval quality, setup/maintenance effort, latency and costs; user approves the selected option.
- [ ] Shared-service retention/teardown is independent of workstation lifecycle; no unsupported multi-user or accuracy claims.

Keep this ledger separate from section 10's backend/drift acceptance. A decision not to deploy a shared graph is a valid outcome, not an incomplete Terraform feature.

## Sources

[1] https://developer.hashicorp.com/terraform/cli/commands/plan — tf-plan
[2] https://developer.hashicorp.com/terraform/internals/json-format — tf-json
[3] https://docs.aws.amazon.com/config/latest/developerguide/remediation.html — aws-config
[4] https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html — aws-cfn
[5] https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html — aws-scheduler
[6] https://docs.cloud.google.com/asset-inventory/docs/monitor-asset-changes — gcp-assets
[7] https://learn.microsoft.com/en-us/azure/governance/policy/how-to/remediate-resources — azure-policy
[8] https://learn.microsoft.com/en-us/azure/governance/resource-graph/changes/get-resource-changes — azure-changes
[9] https://docs.github.com/en/actions/concepts/security/openid-connect — github-oidc
[10] https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments — github-env
[11] https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows — github-events
[12] https://docs.github.com/en/actions/reference/security/secure-use — github-security
[13] https://docs.cloud.google.com/infrastructure-manager/docs/overview — gcp-infra
[14] https://learn.microsoft.com/en-us/azure/automation/shared-resources/schedules — azure-automation
[15] https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule — gcp-job-schedule
[16] https://docs.aws.amazon.com/config/latest/developerguide/setup-autoremediation.html — aws-config-auto
[17] https://learn.microsoft.com/en-us/azure/container-apps/jobs — azure-jobs
[18] https://docs.aws.amazon.com/codebuild/latest/userguide/welcome.html — aws-build
[19] https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws — oidc-aws
[20] https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-google-cloud-platform — oidc-gcp
[21] https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure — oidc-azure
[22] https://neo4j.com/docs/operations-manual/current/backup-restore — neo4j-backup
[23] https://microsoft.github.io/graphrag/index/overview — graphrag-index
[24] https://www.w3.org/TR/prov-overview — prov-overview
[25] https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html — s3-conditional
[26] https://docs.github.com/en/actions/concepts/security/artifact-attestations — github-attest
[27] https://neo4j.com/docs/operations-manual/current/authentication-authorization — neo4j-access
[28] https://neo4j.com/docs/aura — neo4j-aura
[29] https://docs.cloud.google.com/storage/docs/request-preconditions — gcs-conditions
[30] https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage — azure-conditions
