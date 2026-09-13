# C3X OAuth ADC delivery

Source: `/tmp/isaac-c3x-oauth/source`
Base: `cc58da98652a0ce9f8aac6d1f574d3578544d8c1`
Complete portable patch: `/tmp/isaac-c3x-oauth/upstream.patch`
SHA256: `71cb0b8ef8f1ead3ee1f6a2132b63283e92ac5dd31de33c6a23c7f9c8fab5ab7`
Manifest of before/after file hashes and binaries: `manifest.json`.
The patch includes all 13 new files and all 10 modified tracked files. It was
applied to a fresh pinned clone at `patch-check`; all 23 resulting hashes matched.
No commits, pushes, cloud deployment, database provisioning or credential access
were performed by this implementation worker. The old untracked trial harness
was omitted by cloning the local Git repository.

## Artifacts

- Server: `/tmp/isaac-c3x-oauth/bin/c3x-pricing-api`
- Bounded probe: `/tmp/isaac-c3x-oauth/bin/gcp-catalog-probe`
- Isolated official Go: `/tmp/isaac-c3x-oauth/go/bin/go` (go1.26.8 linux/amd64)
- Toolchain archive: `go.tar.gz`, SHA256 verified against official go.dev release
  metadata: `d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b`.
- Source retains `go 1.25.0`; new direct dependency is oauth2 v0.36.0, with
  compute/metadata v0.9.0 indirect. No existing module versions changed.
- User documentation: `source/docs/gcp-auth.md`.

Parent-only live invocation, in the parent's ADC-provisioned environment:

```sh
GCP_AUTH_MODE=adc GCP_QUOTA_PROJECT=cybernetic-renan \
  /tmp/isaac-c3x-oauth/bin/gcp-catalog-probe --live
```

Do not use the offline `run-go` wrapper for live ADC: it deliberately substitutes
an empty HOME and removes credential-related environment variables. Parent
reported successful production-path live output during development; this worker
has not read credentials or made live Google catalog requests. Re-run the final
binary if verifying the final source revision is required.

## Exact verification commands

All commands run from `source`; `sh /tmp/isaac-c3x-oauth/run-go` invokes the isolated
Go binary with local caches/toolchain, GOMAXPROCS=2, GOMEMLIMIT=2GiB and `-p=2`.
Final verification also uses CPU affinity 0,1 (early RED/GREEN cycles used only
GOMAXPROCS and build parallelism controls). These are process/heap controls,
not a container-wide hard 3GB cgroup limit. No containers or background servers
were started.

```sh
sh /tmp/isaac-c3x-oauth/run-go test -count=1 ./...
sh /tmp/isaac-c3x-oauth/run-go test -short -count=1 ./...
sh /tmp/isaac-c3x-oauth/run-go test -race -short -count=1 ./...
sh /tmp/isaac-c3x-oauth/run-go vet ./...
sh /tmp/isaac-c3x-oauth/run-go build -o /tmp/isaac-c3x-oauth/bin/c3x-pricing-api ./cmd/server
sh /tmp/isaac-c3x-oauth/run-go build -o /tmp/isaac-c3x-oauth/bin/gcp-catalog-probe ./cmd/gcp-catalog-probe
git diff --check
```

All passed (seven tested packages; catalog has no tests). Actual server `--help`
worked. Probe without `--live` returned exit 1 with the explicit opt-in message;
probe with an invalid auth mode returned exit 1 with the redacted mode error,
without invoking credential discovery. Build stdout receipts are in
`logs/final-build.log`; complete suite/race/vet outputs are in `logs/final-*`.
DB integration build-tag tests were not run.

## RED/GREEN receipts

Each row used this command form and recorded actual output with shell `pipefail`:

```sh
sh /tmp/isaac-c3x-oauth/run-go test PACKAGE -run 'PATTERN' -count=1 -v
```

Logs `logs/NN-red.log` contain actual failures before their production fix;
`logs/NN-green.log` contain passes after it. The complete suite was re-run afterward.
Some surrounding compatibility tests already passed in later RED rounds.

| NN | PACKAGE | PATTERN (RED; GREEN same except noted) | Initial failure |
|---|---|---|---|
| 01 | ./internal/scraper | TestGCPServicesErrorRedacted | raw 403 response leaked |
| 02 | ./internal/config | TestGCPAuthEnvironment | mode/quota fields absent |
| 03 | ./internal/scraper | TestGCPInvalidModeDoesNotScrape | invalid mode silently scraped |
| 04 | ./internal/scraper | TestGCPADCOnBothCatalogEndpoints | wrong key-only headers; GREEN: TestGCP |
| 05 | ./internal/scraper | TestGCPCatalog\|TestGCPQuotaHeader | unsafe origins/redirects and raw transport errors accepted |
| 06 | ./internal/scraper | TestGCPAuthFailureNotSwallowed\|TestGCPResponseErrorsRedacted | 401/403 swallowed, response/decode/read errors leaked |
| 07 | ./cmd/server | TestScrapeGCPAuthBeforeDatabase | DB parsing occurred before auth validation |
| 08 | ./internal/scraper | TestGCPBoundedCatalogProbe\|TestGCPProbeStopsOnError | public bounded probe absent |
| 09 | ./cmd/gcp-catalog-probe | (omit -run) | opt-in/output/error behavior absent |
| 10 | ./internal/scraper | TestGCPADCRejects\|TestGCPMissing\|TestGCPADCFailure\|TestGCPADCDiscovery\|TestGCPADCRefreshAnd\|TestGCPADCCancellation\|TestGCPCatalogCancellation | expired/header-unsafe tokens accepted; discovery cancellation lost |
| 11 | ./internal/scraper | TestGCPAuthFailureNotSwallowed/.*Bad | HTTP400 (invalid API keys) swallowed |
| 12 | ./internal/scraper | TestGCPChildCancellationDuringSharedRefresh | child cancellation waited for root-context refresh; GREEN adds \|TestGCPADC |

Additional regression tests exercise the official OAuth refresh implementation
through a fake transport, concurrent reuse, SDK refresh redirect rejection, both
API-key endpoint headers, quota headers, and no fallback. No test uses live ADC.

## Boundaries / limitations

- Catalog preflight obtains credentials/tokens before DB operations, but a token's
  catalog permissions/quota cannot be validated locally; use the bounded probe.
- Default API-key behavior is preserved; ADC is explicit. Quota project is explicit,
  not inferred from credential JSON or gcloud. All 400s are conservatively fatal
  because invalid Google API keys can be reported with HTTP400.
- One scraper is tied to one scrape/probe lifetime context. Create a new scraper
  after cancellation. One shared SDK acquisition may finish in the background
  after a worker cancels; it remains bounded by the SDK HTTP timeout/lifetime.
- Standard Google ADC discovery and trusted ADC-configured token exchange remain
  SDK responsibilities; no static bearer-token option or application gcloud call.
- This patch is an optional upstream C3X change, not an IsaacAutomator production
  integration. No G4/Flex/Hyperdisk mapping, DB migration, or full import validation.
