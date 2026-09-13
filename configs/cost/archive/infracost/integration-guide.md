# Optional Infracost estimates

An optional, standalone [C3X GCP OAuth experiment](c3x-oauth/README.md) contains a
replayable upstream patch and authenticated Catalog probe evidence. It is not a
replacement for the Infracost integration below. The subsequent
[GCP catalog and cost acceptance test](c3x-gcp-validation/README.md) verified a real,
four-service, region-projected PostgreSQL import and local API/CLI execution, but
**rejected all four G4 Standard/Flex-start estimates** because of missing machine
prices and incorrect GPU/disk/model mappings. A complete scheduled import and
production integration remain unverified; temporary test services were removed.

`./cost` is a standalone, non-provisioning Python command. It uses the pinned
Infracost **2.16.3 `scan` JSON contract**, not legacy `breakdown`/`diff` flags.
Normal deploy/lifecycle commands do not invoke or require it.

## Supported scope and open gates

The initial adapter accepts an explicitly selected **flat public Terraform HCL
or `.tf.json` directory**, or an existing **public exported Terraform plan JSON**.
It also supports a bounded usage file, normalized reports and local comparison.
It does not run Terraform init/plan/apply, contact GCP to discover usage, create a
backend, install tooling on demand, or log in automatically.

The following are explicitly unsupported, not silently approximated:

- Private configuration/state/plan input: the hosted CLI's full private-data and
  telemetry policy is not accepted by this integration yet.
- Native binary Terraform plans and deployment-bound plan receipts. Exported JSON
  has a content digest, but that is not proof it matches a live deployment or an
  authorized saved plan from the backend-aware runner.
- `--profile` and `--deployment` input modes: profile/deployment binding remains
  open. The software resolver is not an executable cost/deployment envelope.
- Local/remote modules, implicit tfvars and unsafe file/template functions. Do
  not assume the modular production Terraform root is supported by flat-root mode.
- Non-GCP provider plugins, automatic plugin downloads and arbitrary CLI versions.
- Accurate Flex-start quotes: resource recognition alone cannot establish the
  correct consumption/SKU model. Flex inputs remain partial/unverified.

**Hosted Infracost G4 pricing acceptance is blocked until a valid token is
provided through an approved secret mechanism.** Synthetic test responses are
protocol fixtures, never price quotes. A successful `doctor` checks runtime
readiness, not credentials against the server, pricing accuracy or GPU capacity.

## Runtime installation

Requires Linux Python 3.10+, Click and PyYAML. The controller image already supplies
these through its existing dependencies. Optional image packaging installs the
pinned CLI and GCP plugins at build time:

```sh
./build --build-arg WITH_INFRACOST=1 --build-arg WITH_PACKER=0
```

`WITH_INFRACOST=0` is the default and does not download/install the CLI or plugins.
The existing `build` wrapper already forwards build arguments; no extra wrapper
is needed. Do not pass tokens as Docker build arguments.

For a separately approved isolated host installation, select the architecture
explicitly and use a **fresh** plugin directory (the installer refuses to replace
an existing plugin bundle):

The standalone installer publishes the CLI and plugin bundle separately. If a
plugin download fails, the checked CLI may already exist, but no partial plugin
bundle is published; `doctor`/estimation remain unavailable until the complete
bundle is installed. The Docker build step fails on either installation failure.

```sh
python3 scripts/install_infracost.py --enabled 1 --architecture amd64 \
  --destination /tmp/isaac-cost-runtime/bin/infracost \
  --with-plugins 1 --plugin-destination /tmp/isaac-cost-runtime/plugins

./cost doctor --infracost-binary /tmp/isaac-cost-runtime/bin/infracost \
  --plugin-dir /tmp/isaac-cost-runtime/plugins --format json
```

Use `arm64` for Linux ARM64. Both platform archives have checked-in digests; native
ARM64 execution is a separate acceptance check, not proven by downloading it.
`runtime.json` pins the Terraform HCL parser, Terraform-plan parser and Google
provider plugin. The adapter validates runtime binary hashes before use. It does
not treat a version string alone as trust or install missing plugins itself.

For normal host use, make the binary available on PATH and set
`ISAAC_INFRACOST_PLUGIN_DIR` to the explicitly installed plugin directory. The
container default is `/opt/isaac-infracost/plugins`.

## Authentication and privacy

Supply `INFRACOST_CLI_AUTHENTICATION_TOKEN` through an approved environment/secret
mechanism. Never put the value in this repository, usage YAML, CLI arguments,
build arguments, logs or chat. The old `INFRACOST_API_KEY` alone does not authenticate
this v2 hosted CLI. Account/token creation is user-controlled, not part of `cost`.

Both `--public-input` and `--allow-pricing` are required to request pricing.
They attest that the selected inputs are nonsecret and authorize external pricing
and required hosted run-parameter requests—not deployment or report publication.
Do not mark production plans public merely to get past the guard.

The wrapper isolates HOME/config/cache/temp directories, removes inherited cloud,
SSH, Terraform and arbitrary Infracost environment settings, pins a local plugin
bundle and disables update/agent checks. Event traffic is redirected to a refused
loopback endpoint; this is not a claim of a vendor-supported general telemetry-off
switch. Hosted authentication/dashboard run-parameter calls may still occur.
No raw scan output, diagnostics, source names, tags or credential values are
exported; reports contain a restricted projection and hashed identities.

Private input remains rejected until the full policy can be verified. The adapter
is not an operating-system sandbox for untrusted executable tooling.

## Estimate public fixtures

The checked-in fixtures are **never-to-be-applied pricing examples**, not a full
enterprise deployment. See [fixtures/README.md](fixtures/README.md).

```sh
./cost estimate \
  --path configs/cost/fixtures/g4-standard-48-standard \
  --usage-file configs/cost/infracost-usage.example.yml \
  --region us-west1 --public-input --allow-pricing --format json > before.json

./cost estimate \
  --path configs/cost/fixtures/g4-standard-384-standard \
  --usage-file configs/cost/infracost-usage.example.yml \
  --region us-west1 --public-input --allow-pricing --format json > after.json

./cost compare --before before.json --after after.json --format markdown
```

`--region` is an assertion checked against the selected input, not an override
of pricing or a region/quota/capacity lookup. Conflicting assertions fail. Reports
include conservative location evidence; unresolved/mixed-region inputs cannot be
compared as if they had the same verified region. Text HCL is not evaluated by a
second Terraform interpreter, so its region binding can remain unverified; omit
the assertion rather than relabeling such a quote.
For an existing public exported JSON input, replace `--path` with
`--saved-plan /absolute/path/to/public-plan.json`. Do not pass raw Terraform state.
Generating/exporting a production plan is a separate operation; `cost` does not
invoke a hidden refreshed plan or bypass saved-plan identity checks.

Reports distinguish covered subtotals from complete quotes and include coverage,
input/usage digests, tool/plugin identity and assumptions. Exit codes:

- `0`: complete within the declared scope, or a successful local comparison/runtime check.
- `3`: partial coverage/diagnostics. Inspect the report; do not call it a complete quote.
- `2`: unavailable, unsupported or failed request. Missing prices are not zero.

Changing usage/region/currency/scope can make reports incomparable. The comparator
fails explicitly instead of subtracting incompatible totals or trusting hand-edited
subtotals. Lost coverage withholds misleading deltas rather than representing an
unpriced resource as a saving. Usage-file equality does not establish identical
effective hosted organization defaults; reports and comparisons warn about that
unobserved input. Do not aggregate reports that share owner resources without deduplicating
ownership; this initial CLI does not implement a multi-stack allocation engine.

## Usage and lifetime assumptions

Use `version: "0.1"` with a `resource_usage` mapping keyed by static Terraform
resource addresses. The admitted scalar GCP quantities are `monthly_hrs`,
`storage_gb`, `assigned_vms`, `monthly_data_processed_gb`,
`monthly_class_a_operations`, `monthly_class_b_operations` and
`monthly_data_retrieval_gb`. Unknown keys, duplicates, aliases and unsupported
nested quantities fail closed. This is a deliberately bounded subset of the
upstream usage format.

`infracost-usage.example.yml` is a monthly baseline; `gcp-flex-start.example.yaml`
uses fewer compute hours while retaining storage assumptions for the month.
**Neither is an all-in short experiment quote.** The adapter never multiplies all
monthly charges by a compute-hours fraction. Storage lifetime, tiered transfer,
logging, snapshots, KMS, secrets, images and shared resources require independent
scope/usage coverage. Unsupported usage/SKUs and external licensing remain open
costs, not free resources. These scenarios are assumptions, not measured billing.

## isaac9s

Install `requirements-tui.txt` in an isolated environment if needed. The Profiles,
Inspector and Deploy screens expose explicit-input cost panels. Select the public
HCL directory/plan JSON and optional usage file, acknowledge public input/external
pricing, then choose **Estimate / Refresh**. Cancel stops the operation; edits
invalidate old results. No estimate is triggered on every edit or screen mount.

The panels use the same adapter and formatter as the CLI. They do not claim that
the selected software/security/machine UI intent has been converted into the
explicitly supplied pricing input. Software presets remain intent-only until
execution transport is implemented. Bare-metal expense is not estimated, not zero.

## Verification

See [the executed verification receipt](VERIFICATION.md) for scoped test counts,
actual runtime/packaging checks, independent review and remaining blocked gates.

```sh
PYTHONPATH=. python3 -B src/tests/cost_estimate.test.py
PYTHONPATH=. python3 -B src/tests/cost_command.test.py
PYTHONPATH=. python3 -B src/tests/infracost_contract.test.py
python3 -B src/tests/infracost_packaging.test.py
# Use the isolated Textual environment for actual headless UI integration:
PYTHONPATH=. /path/to/tui-venv/bin/python -B src/tests/cost_tui.test.py
```

Ordinary tests use explicitly synthetic responses and no live credentials. Keep
real public pricing, runtime/plugin installation, provider validation and UI/unit
test receipts distinct. None establishes paid deployment, private IAP access,
GPU/robotics acceptance, final billing or teardown.

Upstream contract references: [CLI v2.16.3](https://github.com/infracost/cli/tree/v2.16.3),
[JSON formatter](https://github.com/infracost/cli/blob/v2.16.3/internal/format/json.go),
[usage schema v0.18.0](https://github.com/infracost/config/blob/v0.18.0/usage.go),
[usage examples](https://github.com/infracost/config/blob/v0.18.0/infracost-usage-example.yml).
