# Self-hosted estimator trial evidence — 2026-09-13

Read [the evaluation report](../self-hosted-cost-evaluation-20260913.md) first.

## Verdict

C3X demonstrated a genuine, narrow self-hosted Azure estimate. None of the three
executed candidates passed the complete G4/Flex workload gate. No production
cost engine was replaced. OptScale/OpenCost/ACE were scope-screened, not deployed.

## Contents and integrity

- `manifest.json` pins the archived evidence files by SHA-256. This README and
  the manifest itself are not self-hashed. Verify bytes rather than relying on
  filenames or summaries.
- `independent-review.json` contains the independent evidence audit. Its `passed`
  flag means the bounded conclusions are supported, **not** replacement approval.
- `parent-verification.json` contains independent parent arithmetic/test-count
  checks and live post-trial cleanup listings.
- Each candidate directory contains a condensed receipt and selected raw output.
  Verbose command bodies were omitted from the durable receipts. Full sources,
  binaries and command logs remain at `/tmp/isaac-selfhost-trials/` for now.
- Selected temporary harnesses are archived as evidence, not installed tools or
  standalone turnkey reproducers. They reference disposable paths/containers and
  pinned source/dependencies from their receipts; do not run them in production.

## Interpretation safeguards

- C3X used the C3X CLI, not Microsoft's Azure CLI. Its service-scoped importer
  fetched official prices while egress was allowed; subsequent serving and
  estimation ran on an internal Docker network with explicit region, USD,
  no remote modules and no price cache. This is not an air-gapped refresh claim.
- The proxy log contains 26 JSON request records plus ordinary error lines.
  All recorded requests **targeted** the local API. Three deliberate API-down
  forwarding attempts failed; `all_forwarded_to_local_api` in the original
  receipt is a routing assertion, not a claim that all requests succeeded.
- The C3X trial DB contained Azure prices, not GCP prices. Zero G4 results prove
  missing-price handling is unsafe; they do not by themselves establish what a
  populated GCP catalog would return. Source inspection separately found the G4
  synthesis omission and incorrect GPU/disk/Flex fallbacks.
- TerraCost's price seeds and exported-plan-shaped inputs were synthetic. Its
  25 top-level tests / 68 pass events are not genuine provider-price validation.
  The Terraform dependency's BSL 1.1 includes an Additional Use Grant; review
  obligations rather than treating the root MIT license as sufficient or
  claiming all production use is prohibited.
- IBM's repaired API served a real Azure price through a test importer. Native
  initialization still fails. Estimator compatibility is **unverified**, not
  demonstrated incompatible. Its internal-network + HTTPS-failure evidence is
  narrower than a packet-level network audit.
- Vendor matches are against archived official API responses and retrieval
  metadata, not signed vendor attestations. No exhaustive dependency-license,
  supply-chain or production security review was completed.
- Trial-prefixed containers/networks/volumes/image tags were absent in final
  listings. Shared base images/build cache may remain; no global Docker prune.

All prices are scoped trial observations, not G4 workstation quotations or
billing guarantees. The existing protected backend notes were not edited.
