# Cost estimation — C3X selected, implementation deferred

C3X is the sole selected future cost-engine direction. It is **not yet a reliable
G4 estimator**: OAuth/catalog access and a scoped real PostgreSQL import pass,
but all four Standard/Flex-start G4 cases fail the correct-price gate.

The old Infracost command, adapter, installer, Docker build hooks and isaac9s
estimate panels are retired. There is no active `./cost` command or replacement
C3X integration. Normal deployment and lifecycle remain independent of costing.
TerraCost and the IBM pricing fork are closed standalone experiments, not active
dependencies. This cleanup does not uninstall unrelated host tools/shared caches.

## Continue in the dedicated C3X project

- [Main roadmap, dedicated C3X section](../../.agents/references/plans/terraform-remote-backend-plan.md#138-dedicated-c3x-project-continuation).
- [Dedicated project and devcontainer instructions](../../.agents/references/plans/c3x-dedicated-project-plan.md).
- [OAuth patch, pinned source and verification](c3x-oauth/README.md).
- [Real GCP catalog/import and failed G4 acceptance](c3x-gcp-validation/README.md).
- [Four public acceptance inputs — never apply](fixtures/README.md).
- Native test usage: `c3x-gcp-validation/native-c3x-usage.yml` (not a complete
  billing model; the tested CLI still fixes VM hours at 730).

Future work fixes exact G4/RTX/Flex/Hyperdisk mappings, unknown-price handling,
units/tiers/provenance and usage/lifetime coverage in C3X itself. Only after
independent four-case acceptance should IsaacAutomator gain an optional adapter
and explicit CLI/TUI estimates. Do not resurrect the retired vendor integration.

## Cleanup verification

[Retirement report and regression receipts](retirement/README.md): 271 passing
tests across 12 suites, unchanged C3X evidence and byte-identical archived records.
This verifies cleanup, not C3X pricing or a new devcontainer build.

## Historical records, not supported tooling

[Retired Infracost metadata and receipts](archive/infracost/README.md) preserve
prior tests and the old guide byte-for-byte. They are not installation instructions
for the current repo. [Multi-candidate evaluation](../../.agents/references/plans/self-hosted-cost-evaluation-20260913.md)
and its archived TerraCost/IBM trial evidence remain available for audit; their
implementation work is closed. C3X validation snapshots and hashes are unchanged.

No dedicated repository, C3X devcontainer, production service or cloud resource
is created by the cleanup. Follow the handoff's unchecked implementation gates.
