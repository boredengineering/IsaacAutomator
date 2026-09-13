# Dedicated C3X Project Implementation Plan

> **For Hermes:** Implement only after explicit review/authorization; use the
> subagent-driven-development skill for later task-by-task implementation.

**Goal:** Establish a separately owned C3X development workspace, then qualify its
pricing before proposing an optional IsaacAutomator integration.
**Architecture:** Maintain API and CLI forks as separate Git checkouts in a small
workspace repository. Use a credential-free Go editor, optional PostgreSQL/local
API, and a separately authorized importer; keep IsaacAutomator independent.
**Tech stack:** Go, PostgreSQL 16, pgx/v5, JSONB, Docker Compose and Dev Containers.

**Status: proposal only. Templates below were NOT built or run.** This document
creates no project, fork, container, cloud resource, credential or production
rollout. All implementation checkboxes remain open. Parent sequence:
[roadmap §13.8](terraform-remote-backend-plan.md#138-dedicated-c3x-project-continuation).

## 1. Grounding and boundaries

- Read IsaacAutomator `.devcontainer/devcontainer.json`, `Dockerfile` and
  `docker-compose.yml`; README development instructions and CONTRIBUTING.
- Reuse the structural pattern: `.devcontainer/`, explicit Compose service,
  `/workspaces/<project>` workspace, named data/cache volumes, documented setup.
- Do **not** copy its Playwright/robotics image, Python/R/cloud/agent installers,
  Terraform setup, `/app` alias, Neo4j/gateway services or `.devcontainer/setup.sh`.
- Do **not** inherit `remoteEnv`, home/cloud credential mounts, host Docker socket,
  Docker-outside-of-Docker feature, auth hooks or agent-key loading shell startup.
- Retain the contribution principles: small scoped reviews, accompanying tests,
  source attribution/license review and signed-off commits when later authorized.
  Choose new-project issue/fork owners explicitly; do not reuse Isaac issue URLs.
- Current Infracost core/installer/CLI/TUI integration is retired and deleted.
  Historical metadata is under `configs/cost/archive/infracost/`; its old guide
  and receipts are not current installation instructions. TerraCost/IBM work is closed.
- C3X evidence and four public fixtures remain unchanged in IsaacAutomator.
  This handoff is not permission to move them, rewrite hashes or resurrect costing.

### Source identities and actual interfaces

| Component | Verified source / interface |
| --- | --- |
| API upstream | `https://github.com/c3xdev/c3x-pricing-api` |
| API baseline | `cc58da98652a0ce9f8aac6d1f574d3578544d8c1` |
| API replay inspected | `/tmp/isaac-c3x-oauth-parent/replay` |
| CLI upstream module | `github.com/c3xdev/c3x` |
| CLI baseline | `21bc4dc26eb779b7ee18bd4cdcbb6986578b1703` |
| CLI checkout inspected | `/tmp/isaac-selfhost-trials/c3x/c3x` (directory, not executable) |
| Historical toolchain | Go 1.26.8 linux/amd64; both modules declare Go 1.25.0 |

API `cmd/server/main.go` exposes `serve`, `seed --file` and `scrape --vendor gcp`.
`internal/config/config.go` reads `DATABASE_URL`, `PORT` (default 4000), `ENV`,
`GCP_AUTH_MODE` and `GCP_QUOTA_PROJECT`. The archived patch adds explicit
`GCP_AUTH_MODE=adc`; unset mode stays `api_key`, with no automatic ADC fallback.
`cmd/gcp-catalog-probe` is patch-provided; its `--live` flag is explicit consent
for bounded Catalog calls, not a database import or a login command.

API storage is **PostgreSQL 16, not Neo4j**: `internal/db/db.go` uses pgxpool,
embedded schema migrations and SQL; `schema.sql` stores product attributes and
price arrays as JSONB. Price-entry counts are not counts of a separate price table.
The upstream Compose uses `postgres:16-alpine`; do not copy its password-in-env
wiring. Local API catalog serving does not require Google credentials.

CLI `cmd/c3x/estimate.go` exposes `estimate --path`, `--format`, `--usage`,
`--pricing-endpoint`, `--no-remote-modules`, `--no-cache` and `--currency`.
`cmd/c3x/catalog_client.go` derives `/catalog` from the configured `/graphql` URL;
its loader can fall back to cached/embedded definitions. Test both request paths.
**Do not use `--offline` as pricing acceptance:** this pinned CLI selects an
offline pricing stub that returns zero for most resources, not the local API.

## 2. CS1 — ownership and evidence transfer

- [ ] Approve owners for a workspace repository, API fork and CLI fork. Record
  actual remotes only after they exist; no speculative organization/repository URL.
- [ ] API owner owns OAuth/import, database lifecycle, catalog definitions and
  provenance. CLI owner owns parsing, model/usage selection, calculator/reporting
  and compatibility with served definitions; changes can require coordinated PRs.
- [ ] IsaacAutomator owns profiles, deployment/lifecycle and eventual adapter/UI.
  Never vendor entire C3X source trees into IsaacAutomator.
- [ ] Record upstream SHAs, patch SHA-256, licenses, fork commits, dependency locks,
  Go version and resolved image digests in proposed `docs/source-lock.md`.

Proposed independent layout (names are local layout choices, not existing repos):

```text
c3x-workspace/
  .devcontainer/{Dockerfile,docker-compose.yml,devcontainer.json}
  api/                    # API fork checkout; its own .git
  cli/                    # CLI fork checkout; its own .git
  evidence/isaac/          # reviewed public copies only
  acceptance/             # new tests, schemas and sanitized receipts
  build/                  # ignored local binaries
  docs/{source-lock.md,acceptance.md}
```

Workspace `.gitignore` must exclude `/api/`, `/cli/`, `/build/`, private local
outputs and any secrets; track fork revisions in the lock, not nested source.
Prefer sibling checkouts over wholesale vendoring. A later submodule decision
needs explicit review. No current commit, fork creation or push is requested.

**Future commands, on an approved host outside IsaacAutomator:**

```sh
(
set -eu
# Set C3X_WORKSPACE to an approved NEW absolute directory with an existing parent.
: "${C3X_WORKSPACE:?Choose the new workspace path}"
case "$C3X_WORKSPACE" in /*) ;; *) printf '%s\n' 'Absolute workspace path required' >&2; exit 1 ;; esac
test ! -e "$C3X_WORKSPACE"
test ! -L "$C3X_WORKSPACE"
mkdir "$C3X_WORKSPACE"
cd "$C3X_WORKSPACE"
git clone https://github.com/c3xdev/c3x-pricing-api.git api
git -C api checkout --detach cc58da98652a0ce9f8aac6d1f574d3578544d8c1
git clone https://github.com/c3xdev/c3x.git cli
git -C cli checkout --detach 21bc4dc26eb779b7ee18bd4cdcbb6986578b1703
ISAAC=/workspaces/IsaacAutomator
mkdir -p evidence/isaac
cp -a "$ISAAC/configs/cost/c3x-oauth" evidence/isaac/
cp -a "$ISAAC/configs/cost/c3x-gcp-validation" evidence/isaac/
cp -a "$ISAAC/configs/cost/fixtures" evidence/isaac/
git -C api apply --check "$C3X_WORKSPACE/evidence/isaac/c3x-oauth/upstream.patch"
git -C api apply "$C3X_WORKSPACE/evidence/isaac/c3x-oauth/upstream.patch"
)
```

Before copying, allowlist the public evidence directories and inspect filenames;
exclude secrets, Terraform state/private plans and user/cloud configuration.
Compare every copied file's SHA-256 to its source and validate saved manifests.
Retain `LICENSE.upstream`, attribution and original hashes; annotate adaptations
in new files. Native usage is already in `c3x-gcp-validation/native-c3x-usage.yml`.
Archived Infracost material is reference-only: copy selected historical documents
only if needed, never its obsolete integration code. Temporary `/tmp` checkouts
are inspection aids, not durable prerequisites. Create feature branches and set
approved fork remotes only after ownership and patch/license review.

## 3. CS2 — proposed minimal devcontainer

**All three templates are proposed, NOT built or run.** Only embedded JSON and
Compose configuration rendering were checked; this is not runtime validation. Create them
only in the new workspace. Before use, resolve approved Go/Postgres images to
immutable digests; a historically used Go version does not prove an image exists.
Set host `C3X_GO_IMAGE` to the reviewed Go 1.26.8 Debian-based image reference.
The image must supply Go, a C compiler for race tests, apt and standard user tools.

### `.devcontainer/Dockerfile`

```dockerfile
ARG GO_IMAGE
FROM ${GO_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl jq postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 dev && useradd --uid 1000 --gid 1000 -m -s /bin/bash dev \
    && mkdir -p /workspaces/c3x /home/dev/go/pkg/mod /home/dev/.cache/go-build \
    && chown -R dev:dev /workspaces/c3x /home/dev/go /home/dev/.cache
ENV GOPATH=/home/dev/go GOCACHE=/home/dev/.cache/go-build GOTOOLCHAIN=local
WORKDIR /workspaces/c3x
USER dev
CMD ["sleep", "infinity"]
```

Review UID/GID collisions and bind-mount ownership on the actual host; adapt
consistently, not with `chmod 777`. No cloud CLI, login, scraper, telemetry exporter
or Docker CLI/socket is installed. Dependency downloads are manual and networked.

### `.devcontainer/docker-compose.yml`

```yaml
name: c3x-dev
services:
  editor:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        GO_IMAGE: ${C3X_GO_IMAGE:?Set a reviewed Go image reference}
    image: c3x-dev-toolchain:local
    command: [sleep, infinity]
    volumes:
      - ..:/workspaces/c3x
      - gomod:/home/dev/go/pkg/mod
      - gobuild:/home/dev/.cache/go-build
    networks: [development, catalog]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
  db:
    profiles: [catalog]
    image: postgres:16-alpine # Replace with reviewed immutable digest.
    environment:
      POSTGRES_USER: c3x
      POSTGRES_DB: c3x_pricing
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets: [db_password]
    volumes: [pgdata:/var/lib/postgresql/data]
    networks: [catalog]
    healthcheck:
      test: [CMD, pg_isready, -U, c3x, -d, c3x_pricing]
      interval: 3s
      timeout: 3s
      retries: 20
  api:
    profiles: [catalog]
    image: c3x-dev-toolchain:local
    command: [/workspaces/c3x/build/c3x-pricing-api, serve]
    environment:
      PORT: "4000"
      ENV: development
      DATABASE_URL: "host=db port=5432 user=c3x dbname=c3x_pricing sslmode=disable passfile=/run/secrets/db_pgpass"
      OTEL_EXPORTER_OTLP_ENDPOINT: ""
    secrets: [db_pgpass]
    volumes: [../build:/workspaces/c3x/build:ro]
    networks: [catalog]
    depends_on:
      db:
        condition: service_healthy
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
networks:
  development: {}
  catalog:
    internal: true
volumes:
  gomod: {}
  gobuild: {}
  pgdata: {}
secrets:
  db_password:
    file: ${C3X_DB_PASSWORD_FILE:-/nonexistent/c3x-db-password}
  db_pgpass:
    file: ${C3X_DB_PGPASS_FILE:-/nonexistent/c3x-db-pgpass}
```

### `.devcontainer/devcontainer.json`

```json
{
  "name": "C3X development (proposal)",
  "dockerComposeFile": "docker-compose.yml",
  "service": "editor",
  "runServices": ["editor"],
  "workspaceFolder": "/workspaces/c3x",
  "remoteUser": "dev",
  "shutdownAction": "stopCompose",
  "customizations": {"vscode": {"extensions": ["golang.go"]}}
}
```

The build context is only `.devcontainer/`, not source, evidence, or private outputs.
Only the editor starts by default; no database dependency, API, importer, forwarded
port, post-create/start hook, automatic tool install or environment passthrough.
Disable editor credential/agent forwarding and Settings Sync inheritance in the
approved launch workflow; verify effective mounts/environment, not just this JSON.
Do not inherit OTEL exporter settings, proxy credentials or cloud/agent keys.

### Database secrets and optional local catalog

- [ ] Provision a random local DB password through an approved secret workflow.
  Store it in a private file **outside the workspace/build context**; never in
  Compose `environment`, `.env`, shell argv, logs, committed files or documentation.
- [ ] Provision a second protected pgpass-format file for the same password:
  `db:5432:c3x_pricing:c3x:<secret>` (notation only; not a literal usable value).
  Escape pgpass delimiters correctly. Set mode 0600 and verified ownership.
- [ ] Set `C3X_DB_PASSWORD_FILE` and `C3X_DB_PGPASS_FILE` to these absolute file
  paths on the host. These variables contain paths only; the secrets are mounted
  individually at `/run/secrets/`. No whole secret directory is mounted.
- [ ] Verify readability by the intended container users without displaying
  contents. Local Compose file secrets use bind semantics; do not assume its
  uid/gid/mode declarations remap host ownership. Resolve host UID differences.
- [ ] Check pgx passfile authentication with the pinned driver. `DATABASE_URL`
  above contains no password; there is no invented `DATABASE_PASSWORD_FILE` API
  setting. The password-file setting belongs to the Postgres image only.
- [ ] This bootstrap database user is migration-capable (the image initializes
  it as a superuser). It is **not** a qualified read-only serving identity.
  Keep the stack disposable/private; replace this with CS3 role separation.

No DB/API host ports are published. The editor can reach `http://api:4000`.
The developer editor has ordinary outbound network access and joins both networks:
**this developer network is NOT offline acceptance isolation**. It can become an
egress bridge. Even the API's internal network is not a universal security proof.

## 4. CS2/CS3 — future setup and local validation order

1. [ ] Review templates, source locks, external secret handling and exact host
   paths. On the host run `docker compose -f .devcontainer/docker-compose.yml
   config --quiet`; inspect sanitized effective service/mount/network metadata.
   Confirm no secrets embedded in environment/commands, Docker socket or host home.
2. [ ] Build/start **editor only**, via VS Code “Reopen in Container”, or explicitly
   `docker compose -f .devcontainer/docker-compose.yml up -d --build editor`.
   Do not run IsaacAutomator's `./build`, `./run` or setup hooks for this project.
3. [ ] Inside editor, run the following manually; record real outputs and exits.
   Dependency downloads need developer network, but no cloud credentials:

```sh
(
set -eu
cd /workspaces/c3x
go version
(cd api && go mod download)
(cd cli && go mod download)
(cd api && go test -mod=readonly -short -count=1 ./...)
(cd cli && go test -mod=readonly -short -count=1 ./...)
(cd api && go test -mod=readonly -race -short -count=1 ./...)
(cd cli && go test -mod=readonly -race -short -count=1 ./...)
(cd api && go vet -mod=readonly ./...)
(cd cli && go vet -mod=readonly ./...)
mkdir -p build
(cd api && go build -mod=readonly -o ../build/c3x-pricing-api ./cmd/server)
(cd api && go build -mod=readonly -o ../build/gcp-catalog-probe ./cmd/gcp-catalog-probe)
(cd cli && go build -mod=readonly -o ../build/c3x ./cmd/c3x)
./build/c3x-pricing-api --help
./build/c3x estimate --help
)
```

4. [ ] Only after binaries and mounted secrets are ready, opt into the local
   catalog on the host: `docker compose -f .devcontainer/docker-compose.yml
   --profile catalog up -d db api`. From editor check readiness with bounded retries:
   `timeout 45s curl --fail --retry 10 --retry-connrefused --retry-delay 1 --connect-timeout 2 --max-time 5 http://api:4000/readyz`.
   Stop on failure; readiness alone is not catalog completeness.
5. [ ] Replay the archived public dataset using a reviewed adaptation of its
   native importer harness. NDJSON is **not** automatically compatible with
   `seed --file` (JSON); inspect `SeedFromFile` before choosing a conversion.
   Do not invent a bulk-import flag. Keep test helpers in the API fork where
   Go `internal/` package rules permit production DB helper access.
6. [ ] Reproduce the historical dataset's 3,787 products / 4,443 JSONB price
   entries / zero G4 machine products, then record new corrected datasets
   separately. A count match is a replay check, not correct G4 pricing.
7. [ ] **CS3 requires code:** `serve`, `seed` and `scrape` currently call
   `RunMigrations`. Separate migration/import writes from serving, then add
   least-privilege roles and startup/schema-compatibility tests. A read-only DB
   URL/env change alone cannot implement this. No existing migration-only flag
   is promised here; design its interface and negative tests in the fork.
8. [ ] Stop only this dedicated stack using the same Compose file and project
   name. Named volumes persist by default; deleting them or external secrets
   requires deliberate review. Never touch IsaacAutomator's Neo4j volumes.

## 5. CS3 — importer opt-in, never default editor/server credentials

- [ ] First qualify offline OAuth tests and the compiled probe refusing to access
  credentials without `--live`. Keep API-key/ADC selection and redaction tests.
- [ ] Design a separate, explicit one-shot importer service/job after review.
  Supply only its individually approved ADC credential file via secret mount and
  `GOOGLE_APPLICATION_CREDENTIALS` path; never mount home or cloud directories.
- [ ] Set `GCP_AUTH_MODE=adc` only there, remove API-key variables, and select an
  authorized quota project explicitly. Do not silently reuse the historical one.
- [ ] Separate bounded `gcp-catalog-probe --live` from full
  `c3x-pricing-api scrape --vendor gcp`; the latter writes DB and is not bounded
  like the probe. Review service scope, pagination, timeout, refresh/prune and
  partial-import handling before authorizing it. No scheduled scrape on attach.
- [ ] Grant temporary outbound connectivity only for the approved importer;
  remove its credentials/connectivity afterward. Never automate login, create
  keys, change IAM/API enablement or assume refresh-token credentials are RAM-only.

## 6. CS4–CS8 — acceptance gates before any Isaac integration

Historical [GCP evidence](../../../configs/cost/c3x-gcp-validation/README.md) proves
Catalog access/scoped import, **not usable prices: all four G4 cases FAIL**.
For every implementation change: write a failing regression, demonstrate RED,
make the smallest fix, demonstrate GREEN, then run the affected full suite.

- [ ] **CS4 fidelity/errors:** retain SKU, region, model, currency, effective time,
  exact Money, units, tiers and aggregation/provenance. Missing/ambiguous/stale
  prices must be unknown/unsupported, never zero with `price_source: live`.
  Test genuine free items separately; prohibit silent region/model substitution.
- [ ] **CS5 compute/models:** test `g4-standard-48` and `g4-standard-384` in us-west1,
  each STANDARD and FLEX_START. Correct CPU/RAM/RTX PRO 6000 bundle semantics;
  no T4/L4 fallback, Spot substitution or GPU double counting. OnDemand alone
  cannot establish Flex eligibility; DWS candidate similarity is not proof.
- [ ] **CS6 infrastructure/lifetimes:** replace Hyperdisk→Standard PD fallback;
  include capacity, provisioned IOPS/throughput and confirmed defaults. Cover NAT
  VM/IP/data/egress, GCS operations/storage and registry tiers with explicit
  account-wide allowances, persistent-storage lifetime and unknown dimensions.
- [ ] **CS7 input/usage/JSON:** support original `.tf.json` directories (currently
  `no .tf files found`), equivalent HCL and validated Terraform plan JSON; test
  module/variable/default handling without apply or uncontrolled remote fetching.
  Verify each native usage field (`monthly_storage_gb`, `active_vms`, etc.) is
  consumed; reject/flag unsupported fields. Replace constant `monthly_hours()`
  = 730 for explicit runtime scenarios; the Flex fixture limit is 3,600 seconds.
- [ ] **CS8 isolation:** build/cache dependencies first, then use a separate
  disposable DB/API/CLI stack on an internal-only network, no editor attachment,
  credentials, host mounts, published ports or inherited telemetry. Stage only
  public fixtures/binaries/catalog; verify external DNS/TCP denial before/after.
  Bind local `/graphql` and `/catalog`, use clean caches, disable remote modules,
  keep USD to avoid FX fetches, and prove stopped API fails without hosted fallback.
- [ ] Execute all four with `estimate --path <reviewed-fixture> --format json
  --usage <native-usage-file> --pricing-endpoint http://api:4000/graphql
  --no-remote-modules --no-cache --currency USD` in that future harness. These
  angle-bracket inputs require actual staged paths, not literal shell execution.
  Reconcile every component against independent exact official evidence, not
  rejected historic totals. Distinguish compute references from complete totals.
- [ ] Validate versioned machine-readable reports, unknowns/coverage, immutable
  input/source bindings, error exits, auth/cancellation and database permissions.
  Exercise real PostgreSQL integration separately; no testcontainers socket in
  the editor. Record teardown and limitations, not just successful process exits.

## 7. CS9 handoff and present verification limits

Only after CS8 passes should a reviewed C3X release pin unlock a **new optional**
Isaac adapter/CLI/TUI proposal (roadmap Tasks 29–30). No placeholder panels,
unavailable-only wrapper, automatic estimate or deployment dependency counts.
No production rollout, remote creation, commit/push or cloud action is included.

This authoring pass read the listed repository templates/docs and pinned API/CLI
source interfaces, verified both Git HEADs, and checked document structure and
embedded JSON/YAML syntax locally. It did not build images, resolve image tags,
run Go tests, start Compose, provision secrets, import data or rerun acceptance.
The parent additionally rendered Compose configuration using an explicitly
nonexistent syntax-only image reference, without reading secrets or contacting a
registry/daemon. See `configs/cost/retirement/devcontainer-template-check.json` in
IsaacAutomator; this does not verify image availability or runtime behavior.
Historical test results remain attributed to preserved evidence, not this pass.
Host UID/secret compatibility, pgx passfile runtime, image availability, all new
bootstrap commands and every CS1–CS9 implementation checkbox remain unverified.
