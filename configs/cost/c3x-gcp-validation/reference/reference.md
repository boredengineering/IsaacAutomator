# G4 / C3X cost validation reference

**Scope:** four public synthetic fixtures only, `us-west1-c` / `us-west1`; no actual deployment, capacity, account-discount, or full-infrastructure validation. Official public docs retrieved 2026-09-13. Parent's 14 archived HTTP responses were read without credentials; independent verification matched every manifest SHA-256 and record count, all pagination terminated, and found **35,924 unique SKUs across the four captured services**, not all GCP. Evidence is in `source_evidence.json` and exact-decimal calculations in `reference_rates.json`.

## Outcome

* **Standard G4 has a defensible manual component reference. Original C3X does not implement it.** The real Oregon CPU/RAM/RTX component sums exactly match Google's Oregon full-machine public table.[13][18]
* **Flex-start has a directly published Oregon machine price.** Catalog `DWS Defined Duration` CPU/RAM/RTX candidates closely reconcile, but the retrieved docs do **not explicitly define that Catalog alias as Flex-start**. Keep the alias reconciliation conditional; do not choose these merely because `usageType=OnDemand`, because Standard and DWS candidates both carry that value.[11][13][18]
* **The disk is not safely priced as capacity alone.** The fixtures omit provisioned IOPS/throughput, while Google's documented defaults exceed the included baseline at 255 GiB. Boot-disk/provider default and integer-throughput realization remain unverified.[14]
* No combined infrastructure total is asserted. Storage lifetime, effective defaults, NAT IP count/lifetime, account-wide allowances and transfer remain separate assumptions.

## Shapes and bundle accounting

| Machine | vCPUs | Instance RAM | RTX PRO 6000 count | Total GPU memory |
|---|---:|---:|---:|---:|
| g4-standard-48 | 48 | 180 GiB | 1 | 96 GB |
| g4-standard-384 | 384 | 1,440 GiB | 8 | 768 GB |

Google identifies `nvidia-rtx-pro-6000` as NVIDIA RTX PRO 6000 Blackwell Server Edition; GPU memory is distinct from instance RAM.[1] The pricing page says: **“The GPU-accelerated machines are billed for their attached GPUs, predefined vCPU, memory, and bundled Local SSD storage (if applicable).”** It then says its tables show the **total cost** of each machine type.[13]

Thus use **either** the full machine rate **or** `vCPU_count × CPU_rate + RAM_GiB × RAM_rate + GPU_count × RTX_rate`; never add another GPU charge to the full machine rate. Raw Google billing decomposition into component SKUs is compatible with bundled machine presentation.[13][18] G4's documented maximum supported Titanium SSD capacities are optional attachment limits, not evidence that the public fixtures provision scratch disks; the fixtures have no `scratch_disk`.[1] Real Oregon G4 Local SSD SKU `FC94-13C6-4468` has an explicit **zero** unit rate in the archive; that is genuine catalog data, not a substitute for missing prices.[18] Do not infer arbitrary disks, snapshots, or Hyperdisk are free.

## Exact Oregon component rates

All entries below have `serviceRegions=["us-west1"]`, `category.usageType="OnDemand"`, USD, one tier starting at 0, and `effectiveTime="2026-09-13T07:00:00Z"` in this capture.[18] This timestamp is the API's returned latest-price effective marker, **not proof the tariff was first introduced that day**; absent a request time range, Google documents an effective time within the last 12 hours.[10]

| Model / component | SKU ID | Raw usage unit | Exact USD per unit |
|---|---|---|---:|
| Standard G4 core | A36E-7315-8862 | h | 0.04891 |
| Standard G4 RAM | C566-5B7E-28AA | GiBy.h | 0.00587 |
| Standard RTX 6000 96GB | 73C5-0031-0BF3 | h | 1.09565 |
| DWS Defined Duration G4 core **candidate** | 3B6F-2FBA-B0C5 | h | 0.024455 |
| DWS Defined Duration G4 RAM **candidate** | 4742-1C3C-6E23 | GiBy.h | 0.002935 |
| RTX attached to DWS Defined Duration **candidate** | 1DE7-2C1A-CBEB | h | 0.54783 |

The `h` for core/GPU requires the component count; it is not one entire VM-hour. Descriptions are preserved verbatim in JSON and source archives.[18]

| Oregon reference | Hourly USD | 730 aggregate compute-hours USD | Status |
|---|---:|---:|---|
| 48 Standard | 4.49993 | 3284.94890 | Exact Catalog sum = official full machine price |
| 384 Standard | 35.99944 | 26279.59120 | Exact Catalog sum = official full machine price |
| 48 Flex-start **published machine price** | 2.25 | 1642.50 | Direct official reference, not an invoice |
| 384 Flex-start **published machine price** | 18 | 13140 | Direct official reference, not an invoice |
| 48 DWS Defined Duration candidate sum | 2.249970 | 1642.478100 | Alias not explicitly established; keep separate |
| 384 DWS Defined Duration candidate sum | 17.999760 | 13139.824800 | Alias not explicitly established; keep separate |

These calculations use Python `Decimal`, not floating point. Standard uses the three Standard IDs; the candidate rows use the three DWS IDs; the published Flex rows come independently from Google's explicitly Oregon-labelled data.[13][18] Differences from published Flex are preserved, not silently rounded away. Public table `Price (USD)` carries consumption-model ID `7754-699E-0EBF`; adjacent CUD IDs must not be mistaken for Flex-start. No Flex consumption-model ID is displayed in the retrieved table.[13]

**Region separation:** the default rendered pricing page is Iowa. `public_regional_tables.json` instead preserves explicitly labelled **Oregon** and **Iowa** embedded table records, JSON paths, raw rows and all price columns. Both currently show the same Standard/Flex totals above; their Spot columns differ, proving that default-region data cannot simply be relabelled Oregon. Spot, commitments, vGPU Local SSD, dual-region GCS and Hyperdisk HA/storage-pool variants remain separate candidates, never a min/max-price winner.

## Flex-start usage and duration

Google states: **“Dynamic Workload Scheduler Flex-start VMs are charged based on usage, in the same way as on-demand instances.”** Calendar mode instead pays for the full reservation duration; DWS prices are variable and the running-time price applies.[11] Flex-start can run for up to seven days; stopping a VM does not stop charges for retained disks/IP resources.[4] The DWS page announces prices scheduled to change in **November 2026**; do not extrapolate today's rates beyond their effective period.[11]

The fixtures' `max_run_duration.seconds=3600` is a per-run synthetic limit, while `monthly_hrs=730` is an independent aggregate monthly scenario. It is not a single 730-hour Flex job, proof that 730 hours are obtainable, or measured runtime. Do not multiply every ancillary quantity by one hour or assume stopped resources vanish.

## Hyperdisk Balanced: capacity AND provisioned performance

Oregon Catalog rates are `E917-4171-722C` **0.08 USD/GiBy.mo**, `56CC-5367-43E6` **0.005 USD/mo per billable IOPS**, and `6E3F-6819-5B7A` **0.04 USD/mo per billable MiB/s**; raw performance unit is only `mo`, so the resource multiplier comes from the SKU and product documentation.[18][14]

The first **3,000 IOPS and 140 MiB/s** provisioned per volume are included; provisioned performance above that is billable, regardless of observed utilization.[14] Pricing prose says MBps while technical docs explicitly say MiB/s; keep the technical binary unit and the raw Catalog base-unit metadata rather than silently converting to decimal MB/s.[5][6]

Monthly billing-unit formula:

`255 × 0.08 + max(P_IOPS − 3000, 0) × 0.005 + max(P_MiBps − 140, 0) × 0.04`

Capacity alone is **20.40 USD per full storage billing-unit month**, not a proven boot-disk total. Google documents defaults `IOPS=6×size+3000`, `throughput=min(2400,1.5×size+140)` above 6 GiB.[14] At 255 GiB these formulas produce **4,530 IOPS and 522.5 MiB/s** before any service integer rounding: **7.65** extra IOPS cost and **15.30** extra throughput cost, or **43.35 USD/month formula-only** including capacity. These are **not realized API settings**: confirm boot initialization/provider semantics and throughput rounding before using the formula as the fixture's precise disk estimate. Never label omitted performance fields zero-cost by default.

**Month-unit mismatch:** captured `mo` uses `baseUnitConversionFactor=2592000` seconds (**720 hours**); `GiBy.mo` uses `2783138807808000` byte-seconds. The public UI's monthly/hourly display uses a 730-hour presentation (e.g. 0.08/mo versus 0.000109589/GiB-hour). Preserve both conventions; do not interchange a full billing-unit month with exactly 730 elapsed storage hours. Use the raw conversion factors when modeling elapsed seconds, and disclose the chosen storage-duration convention.[10][18]

## Ancillary components (not a total)

All selected ancillary prices also carry `2026-09-13T07:00:00Z`; all tiers and account aggregation metadata are retained in `reference_rates.json`.[19][20][21]

| Component | Exact SKU ID | Scope / rate / conditional example |
|---|---|---|
| Public NAT assigned VM uptime | 32E2-4EFC-EF9F | global SKU; 0.0014 USD/VM-hour; 1 VM × 730 h = **1.022** |
| Public NAT processed data | 015F-5732-FFF0 | global; 0.045 USD/GiB inbound + outbound processed; 100 GiB = **4.50** |
| Public NAT external IP usage | 8515-9425-D2CE | global; 0.005 USD/IP-hour; **if** one IP for 730 h: **3.65** |
| GCS Standard US Regional | E5F0-6A5D-7BAD | `us-west1/us-central1/us-east1`; tier 0–5 GiB.mo: 0; above 5: 0.02/GiB.mo |
| GCS regional Standard Class A | 4DBF-185F-A415 | global SKU; first 5000 operations: 0; then **0.000005/count** |
| GCS regional Standard Class B | 7870-010B-2763 | global SKU; first 50000 operations: 0; then **0.0000004/count** |
| Artifact Registry storage | 8502-299A-ABAF | global; account-month first 0.5 GiB.mo: 0; then **0.1/GiB.mo** |

Despite the Terraform resource label `private`, `AUTO_ONLY` describes **Public NAT for private-address VMs**, not Google's separate Private NAT product. Public NAT charges also include external IP use and outbound network transfer; its per-VM gateway charge is capped for larger fleets.[7] With the additional explicit assumption of one allocated external IP for 730 hours, the listed NAT components sum to **9.172 USD**, excluding egress; auto-allocation does not establish the actual IP count or lifetime.[7][19]

The GCS fixture is regional, not dual-region, and does not enable Autoclass or hierarchical namespace. Google's free allowances aggregate across eligible US regions and account context; operation pricing uses `count` with `displayQuantity=1000`, which is presentation only, not another divisor.[8][10][20] The 1 GiB-month + 100 Class A + 100 Class B scenario costs **0 only if applicable allowances are available**, versus **0.02054 USD at paid marginal rates** if already exhausted. Zero retrieval is explicit usage; zero network transfer is not declared. Metadata, versions and soft-deleted data can consume storage.[8]

Artifact Registry's 10 GiB-month costs **0.95 USD if its account-wide 0.5 GiB-month allowance remains**, versus **1.00 USD if exhausted**. Transfer and optional scanning are separate; do not assume this repository alone owns the free allowance.[9][21]

## Why original C3X is not yet a proper estimator here

Local source evidence is hashed with exact line extracts in `source_evidence.json` (no production files modified):

1. **No G4 synthesized machine products.** Patched API `gcp.go:380–473` lists only n1/n2/e2/n2d/c2/c2d/t2d/t2a families and CPU/RAM patterns; `617–632` builds CPU+RAM totals only. CLI `google_compute_instance.toml:14–19` requires a synthesized `machineType` product. Adding auth/catalog access alone does not add G4 support.
2. **Wrong GPU fallback.** `google_compute_instance.toml:46–55,96–102` selects L4 only for exactly `nvidia-l4`; every other accelerator, including RTX PRO 6000, resolves to **Tesla T4**, and charges an additional GPU dimension. This is neither correct RTX pricing nor safe bundle accounting.
3. **Wrong boot storage fallback.** `:35–44` recognizes pd-ssd/pd-balanced only; hyperdisk-balanced falls through to **Storage PD Capacity**. There are no Hyperdisk provisioned IOPS/throughput dimensions. The separate `google_compute_disk.toml` also always maps Standard PD.
4. **No scheduling-model selection.** The VM mapping ignores `scheduling.provisioning_model`. `internal/pricing/purchaseoption.go:8–18` defaults GCP to `OnDemand`; both Standard and actual DWS candidate SKUs carry that value. Flex-start cannot be identified by this filter.
5. **Lossy normalization/selection.** `gcp.go:248–282,308–369` only uses the first `pricingInfo` entry, omits effective-time/base-unit/display/aggregation fields, and converts Money through `float64`. CPU/RAM indexing `525–576` chooses minimum nonzero matches; CLI `internal/pricing/http.go:219–252,272–312` fetches up to 50 products and chooses maximum nonzero rate, discarding SKU provenance and tier application. Neither heuristic is valid evidence of unique model mapping.
6. **Ancillary/usage gaps.** NAT TOML uses static 0.0014/0.045, lacks IP and egress costs, and expects `active_vms`, not example `assigned_vms`. GCS only models storage (no operations/retrieval), and GCS/registry expect `monthly_storage_gb`, not example `storage_gb`. `monthly_hours()` is a constant 730. The example Infracost usage YAML is not evidence that C3X consumes those fields. Parent must verify CLI ingestion/overrides separately.

## Artifacts and reproducibility

* `source_evidence.json`: quote extracts, exact URLs, public retrieval hashes, local source hashes/extracts, independently verified Catalog page metadata.
* `reference_rates.json`: 17 explicitly reviewed unique SKU records, exact raw tiers/units/effective times, four fixture inventories, Decimal component calculations, assumptions.
* `public_regional_tables.json`: 24 Oregon/Iowa regional table records with raw embedded data and JSON paths; avoid confusing GCS regional and dual-region records.
* `catalog_candidates_uswest_global.json`: 435 candidate variants; `catalog_candidates_all_regions.json`: 4,387 unique candidate SKUs. Search tags are not eligibility decisions.
* `extract_catalog.py`: rerun with `python3 extract_catalog.py /tmp/isaac-gcp-cost-validation/catalog`; retains every relevant candidate and raw metadata, rejects empty input, no network or winner selection.
* `model_analysis.py`, `extract_public_tables.py`, `build_evidence.py`: exercised successfully on real archived/fetched data. HTML/text source snapshots and URL retrieval outcomes are saved alongside.

**Remaining limitations:** no direct retrieved alias definition for DWS Defined Duration → Flex-start; no actual disk default realization; no account allowance usage, negotiated prices, or infrastructure state. Old pricing URLs redirected to an overview; canonical accelerator/DWS pages were recovered through their official links. Browser startup failed, so regional verification used local parsing of fetched public HTML, without executing page JavaScript. No cloud actions, credentials, production edits, commits, or pushes were performed.

## Sources

[1] https://cloud.google.com/compute/docs/accelerator-optimized-machines — g4_specs
[4] https://cloud.google.com/compute/docs/instances/about-flex-start-vms — flex
[5] https://cloud.google.com/compute/disks-image-pricing — disk_pricing
[6] https://cloud.google.com/compute/docs/disks/hyperdisks — hyperdisk
[7] https://cloud.google.com/nat/pricing — nat
[8] https://cloud.google.com/storage/pricing — gcs
[9] https://cloud.google.com/artifact-registry/pricing — registry
[10] https://cloud.google.com/billing/docs/reference/rest/v1/services.skus/list — catalog_schema
[11] https://cloud.google.com/products/dws/pricing — dws_current
[13] https://cloud.google.com/products/compute/pricing/accelerator-optimized — accelerator_pricing
[14] https://cloud.google.com/compute/docs/disks/hd-types/hyperdisk-balanced — hyperdisk_balanced
[18] https://cloudbilling.googleapis.com/v1/services/6F81-5844-456A/skus — Compute Engine captured public Catalog
[19] https://cloudbilling.googleapis.com/v1/services/E505-1604-58F8/skus — Networking captured public Catalog
[20] https://cloudbilling.googleapis.com/v1/services/95FF-2EF5-5EA1/skus — Cloud Storage captured public Catalog
[21] https://cloudbilling.googleapis.com/v1/services/149C-F9EC-3994/skus — Artifact Registry captured public Catalog
