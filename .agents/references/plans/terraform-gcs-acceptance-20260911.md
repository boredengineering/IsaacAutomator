# GCS and private GCP infrastructure acceptance — 2026-09-11

## Scope and honest outcome

User authorized implementation, checking the requested GCP project and bounded experiments
provided the resulting infrastructure is destroyed. The discovered project is
**`cybernetic-renan`**, display name `renan`.
`renan-cybernetic` was not accessible. No existing infrastructure or IAM policy was changed.

### Live evidence

- Billing enabled; Compute, Storage, IAP and OS Login APIs enabled.
- Project permission probe granted the tested Compute instance/network/firewall/disk
  creation/deletion operations and bucket creation/deletion. These are probes of the
  active account, not proof of every possible enterprise/GPU configuration.
- A real private temporary bucket verified object create/get/list/delete and
  generation-match collision rejection. Project-level object permissions were initially
  inconclusive; the bucket-level probe and actual operations resolved that question.
- Native Terraform **1.10.5** initialized GCS state, planned/applied a provider-free
  `terraform_data` resource, read its outputs from a fresh controller directory and
  destroyed it. All versions of its state objects and its bucket were deleted.
- A separate native Terraform fixture with Google provider **6.45.0** created an
  **e2-micro** VM in `us-central1-a`, a dedicated VPC/subnet and an IAP-source SSH firewall.
  The VM had no external IP or attached service account; Secure Boot, vTPM and integrity
  monitoring were verified. Stop/start and observed TERMINATED/RUNNING states passed.
  Terraform destroyed the VM, boot disk, firewall, subnet and VPC. Individual resource
  GETs returned absence, followed by deletion/absence verification of its state bucket.
- The real Automator `TerraformRunner` plus `backend_runtime.runtime_guard` passed GCS
  init → exact saved-plan apply → output → fresh read-only runtime output → saved destroy
  plan/apply → empty state. This used a provider-free fixture, not a GPU workstation.
- The first runner live test exposed an incorrect serial-zero assumption: GCS init
  creates empty state at **serial 1**. A diagnostic repeat confirmed it; the corrected
  implementation passed. Both failed experiment buckets were also deleted.
- The first private-VM harness failed local HCL parsing before Compute creation. Its
  temporary bucket was removed; the corrected harness validated and passed.

### Permission gap / operations not performed

The project-level **and actual instance-level** IAP permission checks returned no
`iap.tunnelInstances.accessViaIAP`. No role was self-granted. The clarification asking
how to handle IAP access timed out, so no IAM change was authorized. Live IAP SSH,
rsync and OS Login provisioning remain **unverified**, not silently downgraded to
public SSH. A suitable existing identity or an explicitly authorized scoped IAP grant
is needed before that experiment. Guest SSH/OS Login permissions must also be effective.

An additional live experiment using the built Docker image was **blocked before
execution by the approval tool after timeout**. It was not retried or routed around.
That block created no resources and requires fresh user approval to resume.

## Resource accounting

All **7** experiment buckets below were deleted, including object versions.
No GPU, NAT gateway, persistent ledger service or public IP was provisioned. The one
successful VM experiment and all associated Compute resources were destroyed.
Short-lived storage/Compute usage may incur small charges; exact billing has not been
queried and **zero cost is not claimed**.

| Temporary bucket | Outcome | Local evidence |
|---|---|---|
| isaac-exp-8ac207c94b0e45a4bd1e | Passed, cleaned | `/tmp/isaac-gcs-permission-result.json` |
| isaac-tf-exp-ee67ac33f8ff4c2099 | Passed, cleaned | `/tmp/isaac-native-gcs-mdncqcjb/result.json` |
| isaac-exp-0498ab695383-state | Failed test, cleaned | `/tmp/isaac-gcp-infra-pxg2_191/result.json` |
| isaac-exp-e555b694d5a1-state | Passed, cleaned | `/tmp/isaac-gcp-infra-urpozfts/result.json` |
| isaac-runner-77c578fa6a-state | Failed test, cleaned | `/tmp/isaac-gcs-runner-live-lhgf2mt9/result.json` |
| isaac-runner-f64bc1e91b-state | Failed test, cleaned | `/tmp/isaac-gcs-runner-live-fju3u8dw/result.json` |
| isaac-runner-3bd002c3d4-state | Passed, cleaned | `/tmp/isaac-gcs-runner-live-amaf8cw8/result.json` |

The local evidence paths contain sanitized summaries; Terraform plans/state/logs elsewhere
in experiment directories remain private diagnostics, not artifacts for publication.

## Implementation and verification boundaries

- GCS native execution, saved backend dispatch, durable runner staging under controller
  state root, authoritative output reads and lifecycle integration were implemented.
- Selected-directory upload/download use rsync, deletion opt-in, dry-run, exclusions,
  partial-transfer retry, IAP/OS Login endpoint selection and host key checking.
- Outside Docker, explicit host directories are mapped into the tool container with
  direction-appropriate read/write scope. They must exist and be visible to the daemon.
- The real Docker bind test from this devcontainer failed because the Docker daemon
  does not share this container's `/tmp` namespace. No persistence success is claimed.
  Normal Python wrappers run directly when `/.dockerenv` is present. Fake-Docker
  boundary tests and real local rsync tests separately exercise those contracts.
- `./build --build-arg WITH_PACKER=0` succeeded. The built image reports Terraform
  **1.16.2**, and Click/PyYAML import successfully. No global Terraform upgrade or
  VS Code/devcontainer setting change was made. The live runner experiments used 1.10.5.
- This does **not** establish a fully provisioned Isaac Sim/Lab GPU workstation, a
  live IAP transfer, complete S3/Azure remote execution, general migration/attachment,
  native drift activation or Neo4j ledger deployment. Optional ledger/drift mechanisms
  are not prerequisites for normal GCS workstation deployment.

## Offline review / final regression

Final same-snapshot regression: **536 passed, 1 skipped across 35 suites** (537
reported tests), no failed suites. Source and test hashes were unchanged across the
run and independently compared with the final checkout afterward. Evidence:
`/tmp/isaac-gcs-integrated-7d70iacu/results.json` and its per-suite logs.

The skip is the optional `actionlint` check (not installed). The original
credential-bearing `Test_Deployer.test_output_deployment_info` fixture was excluded;
TUI/graph/optional automation suites were outside this change scope. The existing
localhost inventory regression was **not** excluded from final acceptance.
This is a scoped integration result, not an all-repository acceptance claim.
`git diff --check` and `bash -n run` also passed.

Independent review/fix outcomes:

- Transfer review exposed normalized-root bypasses, missing/replaced identity handling
  and missing host-directory transport. Fixes passed independent rereview, including
  real local rsync fixtures and fake-Docker host-boundary tests.
- GCS review exposed stale replacement tfvars, start/stop using mismatched or guessed
  VM scope, and stale OS Login flags permitting sentinel key export. All three fixes
  received qualified approval in independent rereview with reproduced cases passing.
- The rereview also covered noVNC IAP tunnel behavior and offline deploy help. The
  legacy help-time public-IP network lookup was removed with an observed failing then
  passing regression. noVNC URLs no longer contain passwords.
- Final core rereview still flagged the explicit localhost inventory regression. The
  parent corrected this narrowly: explicit inventory-only `localhost` remains valid,
  but real Terraform outputs and other invalid IP strings remain rejected. Both
  interacting regressions passed, then the entire scoped 35-suite run passed above.
  No claim of a further independent rereview of that last narrow fix is made.

Earlier intermediate runs failed (including a changing-source 528-test run); they
were diagnostic, not accepted as final evidence. No commits or pushes were made.
The successful image build predates the final review fixes: normal wrappers mount
the live checkout; rebuild before relying on a standalone immutable image snapshot.
