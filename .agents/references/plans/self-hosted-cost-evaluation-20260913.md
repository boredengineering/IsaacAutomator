# Self-hosted Cost Engine Evaluation Plan

**Status — closed evaluation, 2026-09-13:** the user selected C3X as the sole
future direction and retired competing tooling. This document preserves historical
trials, not an active implementation queue for TerraCost, IBM, Infracost or the
scope-screened tools. The old Infracost integration is removed, not retained
pending replacement. [Dedicated C3X project/devcontainer plan](c3x-dedicated-project-plan.md)
and the main roadmap §13.8 govern further work. C3X is selected but all four G4
pricing cases still fail; no replacement adapter or new project is delivered.

**Historical goal:** qualify a self-hosted estimator through bounded experiments.

**Initial-trial authorization:** user requested roadmap updates and local testing of the researched alternatives. Public source/dependency downloads and isolated local builds/services were in scope. No paid infrastructure, existing credential access, cloud/IAM changes, global installation, commits, pushes or editor settings changes were authorized for that initial trial.

**Subsequent OAuth scope:** the user explicitly requested adding OAuth to C3X
and testing it with configured GCP authentication. This permits the bounded,
read-only Catalog authentication checks recorded below and local code/tests;
it does not authorize IAM changes, login/credential creation, paid resources,
credential disclosure, or replacing the production cost engine.

**Architecture under test:** local input parsing -> local resource catalog -> local pricing API/database -> local calculation/report. A separate price-refresh operation may contact official cloud APIs. Estimation must not depend on Infracost/C3X hosted auth, pricing, catalog or telemetry. Synthetic price seeds and offline stubs are protocol evidence only.

## Feasibility matrix

| Trial | Given / when / then | Principal risk | Current status |
| --- | --- | --- | --- |
| C3X + pricing API | Given pinned CLI/server and locally populated PostgreSQL, when estimation runs without external access, then real vendor-derived prices are used without SaaS | G4/Flex missing-price and wrong-model behavior | PARTIAL: real Azure self-hosted estimate passed; all four G4 cases rejected |
| Cycloid TerraCost | Given built library and local MySQL vendor catalog, when a public JSON plan is estimated, then resource/price mapping works locally | Incomplete Google GPU/Flex model; transitive Terraform fork uses BSL | PARTIAL: native synthetic-price library/DB test passed; no real GCP price coverage |
| IBM-Cloud pricing API fork | Given pinned Node source and PostgreSQL, when init/direct refresh and local GraphQL are exercised, then a usable independent backend exists | Removed data downloader, stale packaging, client compatibility | PARTIAL: patched backend served real Azure price through test importer; native init failed |
| OptScale | Inspect whether actual-spend governance can satisfy pre-deployment Terraform gate | Wrong task and large stack | Scope-screened: not a replacement; not deployed |
| OpenCost | Inspect whether allocation of existing Kubernetes/cloud usage estimates future standalone G4 VMs | Wrong task | Scope-screened: not a replacement; not deployed |
| ACE | Check available cloud scope against required GCP fixtures | Azure-only | Scope-screened: does not satisfy GCP; not deployed |

## Acceptance levels

- **Build:** record source commit, license, toolchain, exact command and exit status. A successful compilation is not a usable price quote.
- **Local protocol:** real API/database/client path with synthetic prices clearly labeled. No fabricated or hard-coded value may count as pricing acceptance.
- **Self-hosted real-price path:** import genuine provider response with URL/time/currency/unit/region provenance; estimate with outbound access denied. Provider import and local estimate are separate phases. Confirm no silent external catalog/default/fallback.
- **GCP workload:** all four checked-in fixture combinations of `g4-standard-48`/`g4-standard-384` and Standard/Flex-start. No T4/L4 mapping for RTX PRO 6000, no on-demand/Spot for Flex, no double-counted GPU bundle. Include Hyperdisk capacity/performance, NAT, GCS, registry and independent running/storage-retention units.
- **Production integration:** selected engine must preserve allowlisted staging, privacy, cancellation, monetary precision, source-bound reports, unknown/free distinction and safe comparison; then rerun CLI/TUI/packaging acceptance. Not part of a claim that a standalone trial works.

## Historical execution and reproducibility (not a new action request)

1. Preserve existing repo changes; use `/tmp/isaac-selfhost-trials/{c3x,terracost,ibm}` for candidate checkouts, dependencies, probes and raw sanitized logs.
2. Use uniquely named trial Docker resources with bounded CPU/memory and time. Never mount HOME, cloud credentials, host Docker socket or production Terraform state into a candidate.
3. Read manifests and code before executing. Record any disposable compatibility patch separately from upstream behavior. Do not rewrite a candidate to conceal a failing trial.
4. Prefer documented CLI/API/library paths; minimal synthetic fixtures may establish protocol. Do not generate a cloud-refreshed Terraform plan or apply infrastructure.
5. On failure inspect the real output, try a bounded justified alternative, and stop after three fixes to the same blocker for reassessment. Record build-blocked, unsupported scope, absent credentials and incorrect output separately.
6. Ask for a dedicated approved Google pricing API credential mechanism only when required. Never search credential fixtures or paste keys into reports. Other public vendor pricing can validate local operation but cannot validate GCP/Flex.
7. Read and independently review each candidate receipt. Verify all containers/networks/volumes/image tags created by the trial are removed; never global-prune Docker resources. Preserve source/log evidence until the user no longer needs it.
8. Select a winner only with a precise acceptance scope. If self-hosted operation passes but G4 fails, record PARTIAL and the concrete extension required, not “works entirely” for Isaac Automator.

## Evidence

- `/tmp/isaac-selfhost-trials/c3x/receipt.json`
- `/tmp/isaac-selfhost-trials/terracost/receipt.json`
- `/tmp/isaac-selfhost-trials/ibm/receipt.json`
- [Durable evidence directory](self-hosted-cost-evidence-20260913/manifest.json): condensed candidate receipts, selected raw outputs and disposable harnesses. SHA-256 manifest pins archived bytes; raw workspaces retain full source/commands.
- Independent review and parent cleanup verification are recorded alongside the evidence. A passing evidence audit approves the accuracy of the bounded verdict, **not** G4 adoption.

## Candidate source references

- https://github.com/c3xdev/c3x
- https://github.com/c3xdev/c3x-pricing-api
- https://github.com/cycloidio/terracost
- https://github.com/IBM-Cloud/infracost-cloud-pricing-api
- https://github.com/hystax/optscale
- https://github.com/opencost/opencost
- https://github.com/TheCloudTheory/arm-estimator

Prior research: `/tmp/isaac-selfhost-cost-research/REPORT.md`. Prior delivered Infracost slice: `configs/cost/archive/infracost/VERIFICATION.md`. Neither is new execution evidence for these trials.

## Results

**Historical trial conclusion:** C3X led for self-hosted architecture; no tested
option passed the complete G4/Flex gate. The old implementation remained at that
milestone. **Subsequent decision:** C3X alone is selected for dedicated development;
competing active tooling is retired rather than kept as a fallback.

### C3X — self-hosting proved, GCP acceptance failed

- Built the actual CLI and server at the commits in `c3x/receipt.json`. No
  production-source patches. A service-scoped test harness invoked the unchanged
  Azure scraper/importer; this was not a complete multi-cloud catalog refresh.
- Imported 832 Azure Key Vault products from Microsoft's public API into local
  PostgreSQL. With explicit `--region eastus`, 100,000 operations at USD 0.03 per
  10,000 operations yielded **USD 0.30/month** through the actual CLI/API/database.
  Archived official response and arithmetic independently checked. No API key,
  Infracost account or C3X account was used.
- CLI/API/proxy/database ran on an internal Docker network; external DNS/IP tests
  failed, local catalog and pricing requests were observed, and stopping the API
  caused failure rather than a replacement hosted quote. This proves the tested
  configuration, not every optional FX/module/telemetry configuration.
- All four original `.tf.json` fixtures failed discovery. Converted HCL variants
  returned exit 0 but zero-priced VM/disk/GPU lines tagged `live`; these outputs
  were **rejected**. Flex queried OnDemand, RTX PRO 6000 mapped toward T4,
  Hyperdisk mapped toward PD, and missing regional prices can fall back to a
  reference region. Do not expose these reports as trustworthy G4 totals.

### TerraCost — library feasibility only

- Unmodified library/example built and ran with real local MySQL. Five tested
  packages passed **25 top-level tests / 68 pass events including subtests**;
  the sixth selected package had no tests. One test was an added ingestion probe.
- Four synthetic exported-plan-shaped projections and synthetic price seeds
  exercise protocol only: they are neither Terraform-generated plans nor real
  vendor prices. Missing G4 yielded resource errors/invalidity despite top-level
  nil errors and zero totals; its example exited successfully with zeros.
- The tested Google ingester excludes G4. GPU count/Flex changes did not change
  the single compute component; ancillary fixture resources were skipped.
- Root MIT license does not settle the full open-source requirement: the pinned
  Terraform fork dependency contains BSL 1.1. Resolve/replace that dependency
  before treating the whole stack as OSI-open-source. No legal opinion implied.

### IBM fork — repaired pricing backend only

- Stock Docker build failed on an unavailable IBM logger package (npm 404).
  Disposable repairs use public log4js, Node 22, matching types/TypeScript and
  three Promise annotations. The repaired image built successfully.
- Native `job:init` still exits 1 at the removed `data:download` command after
  successful database setup. No successful native refresh is claimed.
- An explicit test harness passed six genuine archived Microsoft records through
  upstream normalization/upsert. Local GraphQL returned **USD 0.096/hour** for
  Linux D2s v3 in eastus, matching the official record, with external egress denied.
  This is a backend lookup, not a Terraform estimate or v2 Infracost compatibility.

### Historical gates, continued for C3X only

- [x] Execute and compare the three plausible self-hosted candidates; scope-screen
  OptScale/OpenCost/ACE rather than claiming these uninstalled tools passed.
- [x] Prove a genuine self-hosted CLI/API/database estimate (C3X, bounded Azure).
- [x] Obtain explicitly approved GCP pricing-source access: the subsequent OAuth
  trial used configured ADC and active gcloud authentication for bounded Catalog
  GETs; both returned HTTP 200 for services and Compute Engine SKUs. Tokens were
  neither printed nor persisted. The earlier API-key trial used no credentials.
- [x] Implement optional C3X OAuth ADC authentication and verify its bounded
  production-path Catalog probe with API-key variables removed: one service and
  one Compute Engine SKU, exit 0. A clean patch replay passed short unit tests,
  race tests, vet, and server/probe builds; negative CLI checks failed closed.
  See the [durable patch and verification evidence](../../../configs/cost/c3x-oauth/README.md).
- [x] Subsequent GCP test fully paginated four relevant services (35,924 SKUs)
  and performed a region-projected real import (3,787 products / 4,443 prices).
  [Evidence](../../../configs/cost/c3x-gcp-validation/README.md).
- [ ] Dedicated C3X project: verify the full scheduled refresh lifecycle and
  correct mappings; the scoped test is not an all-GCP import or a valid estimate.
- [ ] Dedicated C3X project: add/review G4 Standard/Flex, RTX bundle and Hyperdisk
  models. Fix unknown-price zeroing, region fallback,
  input format and provenance before any C3X adapter acceptance.
- [ ] Verify every required compute/storage/network/retention component using
  actual provider-derived data; do not promote synthetic seeds to live prices.
- [ ] Only then implement an optional self-hosted adapter in Tasks 29–30, with
  RED/GREEN tests and independent privacy/report/UI/packaging requalification.

No cloud infrastructure was created. Trial-owned containers, networks and tags
were removed; shared downloaded base layers/build cache may remain. Selected
sources/logs are retained, not installed into Isaac Automator. All prices above
are scoped test observations, not workstation quotations or billing guarantees.
