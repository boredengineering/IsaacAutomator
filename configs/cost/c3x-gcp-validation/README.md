# C3X GCP catalog and workstation-cost acceptance — 2026-09-13

## Verdict

**Catalog access PASS. Scoped real database import PASS. All four G4 cost cases FAIL.**
Do not use the C3X totals for deployment budgeting. No dedicated C3X project,
production integration, cloud deployment, IAM change or credential configuration
was created by this test. The temporary Docker stack was removed and its absence
verified; existing Neo4j services were not modified. See `cleanup.json`.

## What actually ran

1. Compiled a bounded, explicitly live-opt-in Go integration harness against the
   previously verified OAuth patch. It used existing ADC and quota project
   `cybernetic-renan`, with API-key environment variables removed. It called the
   production preflight, service discovery, SKU pagination, normalization and
   machine-synthesis functions. Only successful public Catalog bodies were saved;
   request headers, tokens and credential files were not archived.
2. Captured 14 real responses and 35,924 unique SKUs, completing pagination for
   Compute Engine, Cloud Storage, Networking and Artifact Registry. These are four
   relevant services, **not all GCP services**. Database projection retained
   us-west1, us-east1, us and global products. The harness finished successfully.
3. Passed the resulting unmodified NDJSON to a test importer invoking production
   migrations and `db.UpsertProducts` against real temporary PostgreSQL. Parent
   SQL verification found **3,787 products / 4,443 price entries / zero G4
   machine-type products**. The independent auditor compared every stored row
   with the imported dataset and independently recomputed normalized/derived rows.
4. Ran the real C3X CLI against a local pricing API through a transparent recording
   proxy. API/CLI had no cloud credentials, host mounts or published ports, and
   only a dedicated internal Docker network. Selected external DNS/TCP probes
   failed before/after testing; this is not a universal host-isolation audit.
5. Tested all four public fixtures: both `g4-standard-48` and `g4-standard-384`,
   each STANDARD and FLEX_START, in us-west1. Original `.tf.json` directories all
   failed with `no .tf files found`. Deterministic, value-preserving HCL projections
   all executed, both without usage and with the existing public usage example.
   Stopping the local API made the negative-control estimate fail rather than
   silently use another pricing service; API recovery was also verified.
6. Parent independently repeated all four HCL/usage cases, then repeated all four
   with **native C3X usage names**. No production mappings or prices were changed.
   The latter runs consume 1 GiB-month of GCS, 10 GiB-month of registry storage and
   100 GiB of NAT data, but the fundamental G4 defects remain.

This validates scoped native scraper functions → real data → production database
functions → API → CLI, using explicit test harnesses. It does **not** validate the
unmodified scheduled full-import lifecycle, refresh/pruning, the modular production
Terraform root, real provider defaults, actual account usage or GPU availability.

## Four-case result

| Case | Native-correct usage run | Acceptance |
|---|---|---|
| g4-standard-48 STANDARD | CLI exits 0 | FAIL |
| g4-standard-48 FLEX_START | CLI exits 0 | FAIL |
| g4-standard-384 STANDARD | CLI exits 0 | FAIL |
| g4-standard-384 FLEX_START | CLI exits 0 | FAIL |

The actual served definitions and HTTP requests establish:

- G4 machine lookup has no product. Compute is nevertheless reported as zero with
  `price_source: live`. Missing prices must instead be unknown/unsupported.
- `nvidia-rtx-pro-6000` falls through to **Tesla T4 at $0.35/GPU-hour**, not RTX.
- `hyperdisk-balanced` falls through to **Standard Persistent Disk at $0.04/GiB-month**.
  Real Oregon Hyperdisk Balanced capacity is $0.08/GiB-month, with separate
  provisioned IOPS and throughput charges above included amounts.
- STANDARD and FLEX_START produce identical results and OnDemand queries.
  Google also labels DWS Defined Duration candidate SKUs OnDemand, so that field
  alone cannot distinguish the pricing models.
- The original Infracost-style usage example uses `storage_gb`; native mappings
  require `monthly_storage_gb`. Correcting the usage names fixes those storage
  quantities, **not the G4 failure**. NAT uses `active_vms`. The existing native
  `monthly_hours()` is a constant 730, not measured runtime or a per-job duration.
- GCS operations, NAT external-IP charges and other dimensions are absent from
  these mappings. Account-wide free tiers and transfer are not established.

For audit only, native-correct usage produced rejected project totals $272.24 for
both 48-size models and $2,060.74 for both 384-size models. **These are erroneous
outputs, not estimates.** Exact reports are in `parent-native-usage-rechecks.json`.

## Independent official compute reference — not a C3X quote

Google's explicitly **Oregon** regional pricing tables and genuine component SKUs
were checked separately. Parent rechecked raw Money values, component counts,
Decimal arithmetic and the extracted regional table rows.

| Machine | Standard USD/hour | Published Flex-start USD/hour |
|---|---:|---:|
| g4-standard-48: 48 vCPU, 180 GiB RAM, 1 RTX PRO 6000 | 4.49993 | 2.25 |
| g4-standard-384: 384 vCPU, 1,440 GiB RAM, 8 RTX PRO 6000 | 35.99944 | 18.00 |

These are compute references including CPU, RAM and the specified GPU count;
**do not add the GPU again**. Disks, networking, storage and other services are
separate. They are not full infrastructure totals or negotiated account prices.

Standard component sums match the published machine rate exactly. DWS Defined
Duration component sums closely match published Flex rates, but the retrieved
sources did not explicitly define that SKU alias as Flex-start. The reference
keeps that mapping conditional and preserves the numerical differences. The
published Flex rate is independently explicit; neither similarity nor OnDemand
classification proves automatic SKU eligibility.

The 730-hour figures in `reference-matrix.json` are an aggregate planning scenario,
not a single Flex job or proof that capacity is obtainable. The fixture's Flex
run limit is 3,600 seconds. Storage can persist after a job stops. Hyperdisk's
omitted performance settings need confirmation; do not assume capacity-only cost.
See `reference/reference.md` for exact SKUs, regional-table evidence, storage
month-unit differences, ancillary rates, free-tier assumptions and open gates.

Official sources:
- https://cloud.google.com/products/compute/pricing/accelerator-optimized
- https://cloud.google.com/products/dws/pricing
- https://cloud.google.com/compute/docs/disks/hd-types/hyperdisk-balanced

## Evidence, review and reproduction boundaries

- `catalog-evidence.tar.gz` + `catalog-manifest.json`: all 14 public response
  bodies, capture summary, projected production products and the native live test
  harness. Every archive member was read back and hash-verified.
- `runtime-evidence.tar.gz` + `runtime-manifest.json`: exact public inputs/HCL,
  importer harness/tests, native runtime helper scripts, CLI reports, HTTP audit,
  served catalog, database counts and selected isolation/control receipts.
  Unrestricted Docker inspection and command logs were deliberately omitted.
- `parent-cli-rechecks.json`, `parent-native-usage-rechecks.json`,
  `native-c3x-usage.yml`: parent-executed confirmation and explicit usage projection.
- `final-audit.json`: independent evidence review PASS; G4 acceptance FAIL.
  Its historical cleanup-pending observation is superseded by `cleanup.json`.
  Native-correct parent rechecks supplement, not rewrite, the reviewed initial run.
- `reference/`: exact-decimal reference data, official-source quote extracts,
  regional table snapshots and exercised extraction/calculation scripts.
- `verification.json`: final archive/syntax/count checks and boundaries.

The experiment uses the existing pinned CLI and the OAuth API patch documented
in `../c3x-oauth/README.md`; it adds test harnesses only. Archived scripts preserve
original temporary paths/toolchain prerequisites and are **not a new installer
or production service**. Full temporary runtime/source/doc snapshots remain at
`/tmp/isaac-gcp-cost-validation/`; the repository preserves the selected evidence.
Runtime README/logs describe services while the test ran, not their final state.
No credentials should ever be supplied to these disposable API/CLI containers.

## Next gate before adoption

A bounded follow-up must add correct G4 component/bundle semantics, explicit
pricing-model and region selection, RTX and Hyperdisk mappings, useful usage
conversion, tier/unit/provenance handling, and fail-closed missing-price coverage.
Retest all four cases with independently reconciled components and explicit disk,
network and lifetime assumptions. This test does not adopt C3X or authorize a new
repository, production integration, commit or push.
