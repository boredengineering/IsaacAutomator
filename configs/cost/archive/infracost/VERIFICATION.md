# Infracost integration verification — 2026-09-12

This records a **bounded public-input implementation**, not completion of every
Task 28–30 requirement or the infrastructure roadmap. Source fingerprints and
machine-readable results: [verification.json](verification.json).
Final bounded core review: [core-review.json](core-review.json).

## Executed tests

**221 passed, 0 skipped, across 14 explicitly selected suites.** This is
not an all-repository test result. Core/adjacent suites used Python 3.10; headless
UI suites used Python 3.12.14 and `requirements-tui.txt`.

| Suite | Tests | Skipped |
| --- | ---: | ---: |
| `backend_selection` | 5 | 0 |
| `backend_entrypoints` | 14 | 0 |
| `backend_runtime` | 7 | 0 |
| `terraform_runner` | 42 | 0 |
| `terraform_lifecycle` | 23 | 0 |
| `workstation_profile` | 11 | 0 |
| `workstation_profile_command` | 12 | 0 |
| `cost_estimate` | 34 | 0 |
| `cost_command` | 3 | 0 |
| `infracost_contract` | 4 | 0 |
| `infracost_packaging` | 16 | 0 |
| `cost_tui` | 15 | 0 |
| `terraform_tui` | 34 | 0 |
| `isaac9s_existing_full_app_guarded` | 1 | 0 |

The existing isaac9s full-app smoke ran with temporary APP_DIR, patched
inventory/telemetry/authentication and guards against external commands/socket
connections. New cost UI tests mount the production app, exercise reachable
estimate/consent/cancel controls and actual offline child termination. Synthetic
prices are protocol fixtures, not vendor quotes. Textual emitted asyncio
slow-task diagnostics; these were not test failures or never-awaited warnings.

## Actual runtime and packaging

- Official Infracost **2.16.3** archive checksum verified; actual Linux amd64
  version/help succeeded.
- HCL parser **0.0.71**, plan parser **0.0.20**, Google provider **0.0.12** installed
  from checked archives and exercised via real plugin handshakes.
- amd64 and arm64 CLI/plugin archives and extracted-binary pins checked.
  **ARM64 was not executed natively.**
- Both enabled and disabled variants of the **actual optional Dockerfile stage**
  built on python:3.10-slim. Disabled mode had no runtime/plugins; enabled mode
  ran version/plugin checks with container networking disabled.
- Experiment image tags removed and absence independently checked. This does not
  claim a full controller build or removal of shared builder cache.

## Public G4 inputs and pricing blocker

Four public fixtures (48/384, Standard/Flex-start) passed Terraform validation
against Google provider **8.2.0** in an isolated backend-disabled context. No
plan, apply, GCP authentication or guest operation occurred. Validation is not
pricing support, GPU capacity or runtime acceptance.

Actual `./cost estimate` calls for all four fixtures used the pinned runtime.
Each returned exit **2**, **unavailable**, **authentication_token_required**,
input-backed region **us-west1 / verified_single**, **7 unknown declared
resources** and a **null covered subtotal**, never zero. No authenticated price
was obtained; initial native CLI scans also reported missing authentication.
No manual/fallback rates were substituted.

## Review and remaining gates

Packaging, bounded adapter/CLI and UI passed independent scoped reviews after
fixes. Regressions cover special-file reads, escaped Flex JSON, false regional
labels, free-parent coverage loss, misleading comparison deltas, stale estimates
and clipped UI controls. The final core reviewer also exercised the four actual
fixture sets as synthetic exported-plan variants; those are not real plans.

Still open: authenticated pricing/coverage, private-data policy, production
modules/variables, profile/deployment/native-plan binding, effective hosted usage
provenance, advanced lifetime/multi-stack allocation and attributed supplemental
Flex pricing. Unsupported modes are rejected rather than pricing a fictional
production topology. Software presets remain intent-only.

No cloud resources, IAM changes, commits, pushes or VS Code settings changes were
performed. The pre-existing plan modification was not edited. The credential-risk
`deployer.test.py` and broad test discovery were excluded.

## Reproduction artifacts

- Runtime contract: `/tmp/isaac-infracost-spike/runtime-contract.json`
- Real plugins: `/tmp/isaac-infracost-plugins/verification.json`
- Packaging: `/tmp/isaac-cost-image-check-w5throjm/receipt.json`
- Terraform: `/tmp/isaac-cost-tf-by64seco/results.json`
- Test/CLI logs: `/tmp/isaac-cost-regression/`
- Four guarded real CLI receipts: `/tmp/isaac-cost-region-fix.json`

Temporary artifacts may disappear. The checked-in receipt preserves bounded
results and source fingerprints without credentials.
