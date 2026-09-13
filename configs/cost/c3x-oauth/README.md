# Optional C3X GCP OAuth patch and verification

This directory preserves a standalone C3X pricing-API experiment. It does not
register C3X as Isaac Automator's cost engine or modify the existing Infracost
adapter, deployment commands, or isaac9s.

## Scope

The upstream baseline is `c3xdev/c3x-pricing-api` at
`cc58da98652a0ce9f8aac6d1f574d3578544d8c1`:
https://github.com/c3xdev/c3x-pricing-api

The patch adds explicit OAuth Application Default Credentials (ADC) support for
the Google Cloud Billing Catalog importer while preserving its existing API-key
mode. It uses Google's refreshable credential library; it does not add an
access-token string to configuration or invoke gcloud from the importer.

## Modes and reproduction

- `GCP_AUTH_MODE=adc`: explicitly use ADC with automatic OAuth token refresh.
  An API key is neither required nor used in this mode.
- `GCP_AUTH_MODE=api_key`: legacy mode, also the default when unset; requires
  `GCP_API_KEY` supplied through an approved secret mechanism. No ADC fallback.
- `GCP_QUOTA_PROJECT`: optional project identifier sent in `X-Goog-User-Project`.
  The live test explicitly selected `cybernetic-renan`.

`upstream.patch` is for the exact baseline above. Apply it to a fresh checkout;
do not apply it blindly to a different revision or a checkout with user changes.
Go 1.26.8 linux/amd64 was used for this trial; the module retains its Go 1.25
declaration. No Go toolchain was installed globally.

```sh
git clone https://github.com/c3xdev/c3x-pricing-api.git c3x-pricing-api
git -C c3x-pricing-api checkout --detach cc58da98652a0ce9f8aac6d1f574d3578544d8c1
git -C c3x-pricing-api apply --check /workspaces/IsaacAutomator/configs/cost/c3x-oauth/upstream.patch
git -C c3x-pricing-api apply /workspaces/IsaacAutomator/configs/cost/c3x-oauth/upstream.patch
cd c3x-pricing-api
go test -short -count=1 ./...
go build -o build/c3x-pricing-api ./cmd/server
go build -o build/gcp-catalog-probe ./cmd/gcp-catalog-probe
```

Build/test commands do not need cloud credentials. Dependency download may need
network access; the parent also checks replay with cached dependencies offline.
The following command is a separate, explicitly live credential/network test:

```sh
env -u GCP_API_KEY -u GOOGLE_API_KEY \
  GCP_AUTH_MODE=adc GCP_QUOTA_PROJECT=cybernetic-renan \
  ./build/gcp-catalog-probe --live
```

Without `--live`, the probe refuses to initialize credentials. With opt-in it
uses the importer's production authentication, destination and response helpers
for at most two Catalog GETs, without pagination/retries or a database. It prints
only status and record counts. This is not the full `scrape --vendor gcp` job,
which requires an explicitly configured database and writes imported products.

The user authorized local implementation/testing and use of configured GCP
credentials for bounded read-only Catalog calls. No login, key creation, IAM
change, paid resources, database publication or production engine replacement
is included.

## Initial direct authentication check

`evidence/auth-check.json` records the executed preliminary check, and
`evidence/check_catalog_auth.py` is its reproducible harness. It is an explicit
network/credential operation, not an offline unit test; do not run it as an
import hook or automatic CI step. It currently targets `cybernetic-renan` as the
quota project.

Both configured ADC and the active gcloud login obtained a token internally and
returned HTTP 200 for:

- One page containing one service from the services list.
- One page containing one Compute Engine SKU.

The harness captures token-command output in process memory, never prints or
writes the token, never passes it on a command line, refuses HTTP redirects,
and stores only status/count information. Google credential tools may manage
their own existing credential caches; this is not a claim that their credentials
exist exclusively in RAM. No credential file was displayed or copied.

This preliminary check uses Python/gcloud, **not patched C3X**. The parent also
built and executed the patched C3X probe with API-key variables removed: it
returned `{"status":"ok","services":1,"compute_engine_skus":1}` with exit 0.
Final replay, test and review receipts are recorded separately in this directory.

## Verification results

The parent applied `upstream.patch` to a fresh checkout at the exact baseline
and verified all 23 changed/new file hashes against the implementation manifest.
Using isolated, credential-free build/test environments and cached dependencies:

| Check | Result |
| --- | --- |
| Clean patch application and whitespace check | PASS |
| Baseline short suite, before patch | PASS |
| Replayed `go test -mod=readonly -short -count=1 ./...` | PASS |
| Replayed `go test -mod=readonly -race -short -count=1 ./...` | PASS |
| Replayed `go vet -mod=readonly ./...` | PASS |
| Server and bounded probe builds | PASS |
| Five compiled-probe negative checks | PASS: exit 1, no success output or marker leakage |
| Final replayed binary with live ADC and no API-key variables | PASS: one service, one Compute Engine SKU |
| Independent final review of complete patch | PASS: no security or logic blockers |

Database integration build-tag tests were **not** run. Refresh, cancellation,
concurrency, both authentication modes, redirect/origin restrictions and redacted
errors are covered by offline tests; a long-running real token-expiry soak was
not performed. Review retained two non-blocking test-coverage suggestions for
explicit probe-deadline assertions and an injectable CLI ADC-failure test.

- `verification.json`: parent replay/build/live receipt and final probe digest.
- `evidence/final-review.json`: independent verdict bound to the patch digest.
- `evidence/replay-*.json`: parent test, race, vet and build command results.
- `evidence/negative-probe.json`: five fail-closed CLI cases, with no real credentials.
- `evidence/implementer-manifest.json`: source and binary hash manifest; its
  binaries are the implementer's builds, not the separately rebuilt parent probe.
- `evidence/implementer-DELIVERY.md` and `evidence/tdd/`: implementation notes and
  recorded RED/GREEN cycles. Their `/tmp` paths are historical execution paths.
- `LICENSE.upstream`: upstream Apache 2.0 license.

The parent's verified source is `/tmp/isaac-c3x-oauth-parent/replay`; the verified
native probe is `/tmp/isaac-c3x-oauth-parent/gcp-catalog-probe-final`. These are
temporary paths. The patch and saved reproduction instructions are the
durable deliverable; no binary or credential file is bundled in this directory.

## Security and interpretation

- Enabling Cloud Billing API is separate from authentication. gcloud login and
  ADC configuration are also separate; both happened to work in this trial.
- ADC must be explicitly selected for the importer. Do not mount a whole home
  directory or cloud credential directory into build/test containers.
- Only the importer needs Google authentication. A local catalog/database and
  estimator can serve imported prices without retaining those credentials.
- An explicit quota project may require the caller's permission to consume that
  project's services. A denied request is a blocker, not permission to add IAM.
- Catalog responses contain public list pricing, not proof of account-specific
  discounts, actual billed usage, GPU capacity or a complete Terraform estimate.
- G4/Flex-start/RTX PRO 6000/Hyperdisk mapping, unknown-price zeroing and regional
  fallback qualification remain separate from this authentication change.

References:
- https://cloud.google.com/billing/docs/reference/rest/v1/services.skus/list
- https://cloud.google.com/docs/authentication/application-default-credentials
- https://cloud.google.com/docs/authentication/api-keys-best-practices
