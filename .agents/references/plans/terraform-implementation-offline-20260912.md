# Offline implementation evidence — 2026-09-12

## Scope and limits

First implementation batch for Tasks 24/25, Task 31 generation and Task 35
pre-build safety in `terraform-remote-backend-plan.md`. This is **not** completion
of those tasks or of the whole roadmap. No paid resources, IAM changes, local
robotics installation, registry publication, real image build or VM deployment
were performed. The user's pre-existing notes edit was not changed.

## Delivered and exercised

- Pure versioned software-profile resolver, three public presets, documented
  consumer mapping and standalone `workstation-profile list/validate/resolve`.
  Explicit component overrides, strict parsing, pin invalidation and provenance
  tests pass. `ready_for_apply` stays false: local/cloud/Packer consumers and
  immutable runtime verification remain outstanding.
- Existing legacy installer parsing is data-only (no generated-shell eval), with
  exact/unambiguous path handling, duplicate/schema checks and sanitized errors.
  PyYAML is now an explicit dependency. Legacy presets are not a shared adapter.
- GCP Flex runtime/create-polling controls and validation precede replacement
  side effects. Restored scheduling and replay optional values are tested.
  Google provider 8.2.0 schema has `max_run_duration` but does not expose
  `request_valid_for_duration`. Create polling is not allocation wait/cancellation.
- All three image wrappers have local previews, protected host argument routing,
  private Packer and Ansible JSON variable files, cleanup and redacted errors.
  AWS image auth exports the CLI credential chain without `configure set` argv.
  Real builds still require VERSION; host previews can report it as null.

## Fresh Python regression

**315 tests passed, 0 skipped, across 20 scoped suites.**
These are standalone unittest files, not pytest collection or all-repository
acceptance. Most cloud boundaries use synthetic inputs/mocked subprocesses;
file-transfer coverage includes disposable local rsync, not an IAP cloud tunnel.

Executed using `PYTHONPATH=. python3 -B src/tests/<suite>.test.py`, each in a
subprocess with a temporary HOME and a small explicit environment (no inherited
cloud credential variables). All child exit codes were checked before counting.

| Suite under `src/tests/` | Tests | Skipped |
| --- | ---: | ---: |
| `profile_privacy.test.py` | 4 | 0 |
| `deploy_command.test.py` | 43 | 0 |
| `backend_entrypoints.test.py` | 14 | 0 |
| `distribution_profile.test.py` | 9 | 0 |
| `artifact_registry.test.py` | 18 | 0 |
| `gcs_lifecycle.test.py` | 11 | 0 |
| `backend_runtime.test.py` | 7 | 0 |
| `terraform_backend.test.py` | 14 | 0 |
| `terraform_runner.test.py` | 42 | 0 |
| `workstation_profile.test.py` | 11 | 0 |
| `workstation_profile_command.test.py` | 12 | 0 |
| `installer_profile_contract.test.py` | 16 | 0 |
| `gcp_flex_start.test.py` | 16 | 0 |
| `aws.test.py` | 17 | 0 |
| `backend_selection.test.py` | 5 | 0 |
| `terraform_sources.test.py` | 2 | 0 |
| `file_transfer.test.py` | 28 | 0 |
| `state_backend_command.test.py` | 11 | 0 |
| `run_wrapper.test.py` | 18 | 0 |
| `workstation_image_contract.test.py` | 17 | 0 |

The full historical `deployer.test.py` fixture suite and the all-repository runner
were not executed. Do not combine these fresh counts with historical 536/1 or
other session results.

## Terraform and Packer

- Terraform 1.8.5, an isolated source copy with locally initialized Google 8.2.0
  provider: `terraform validate -no-color` passed; `terraform test -no-color
  -filter=tests/flex_start.tftest.hcl` passed **15 mocked plan runs**, zero failures.
  Includes independent g4-standard-48 and g4-standard-384 plans, private IAP/OS
  Login checks, timing/shape rejections and preserved Standard/Spot behavior.
  No real provider API reads or applies; the test provider is mocked.
- `terraform fmt -check` passed for the five changed HCL/test files.
- Downloaded Packer 1.16.0 into a temporary directory; checked the archive against
  the official HTTPS SHA256SUMS before execution. With an empty temporary HOME,
  `packer validate -syntax-only` passed for GCP, AWS and Azure templates.
  No plugins initialized and **no full Packer/provider validation or build**.
- Python AST checks, shell `bash -n` and scoped `git diff --check` passed. The
  notes file is excluded from whitespace checks to preserve the user's edit.

## CLI smoke and review

- `./workstation-profile list --json`, `validate full` and
  `resolve default --disable arena` ran successfully, retaining explicit
  unresolved/unverified fields instead of claiming deployment readiness.
- GCP/AWS/Azure preview entrypoints were exercised with host detection, VERSION
  unset, empty HOME/environment, forbidden child process/network operations and
  synthetic password input. Each rendered a null version and no password.
- Independent reviews caught repository pin carry-over, unsafe parsing/path
  cases, replacement-order and repair/replay bugs, and image host/downstream
  secret handling. These received focused regression fixes. A parent host smoke
  additionally caught the VERSION regression, now reproduced and fixed.

## Remaining implementation/acceptance

Shared adapters and persisted profile transport (Tasks 24–27); component/Python/
wheel/runtime parity; optional Infracost and isaac9s integration (28–30); real
private IAP/Flex-start capacity/lifecycle on each RTX PRO 6000 shape; local vs
source-cloud vs image-cloud robotics receipts; distribution/model/image/live
cleanup gates; optional graph improvements and remaining S3/Azure/migration/drift
scope. A generated plan or an e2-micro experiment cannot replace GPU acceptance.
