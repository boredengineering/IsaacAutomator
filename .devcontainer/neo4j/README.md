# IsaacAutomator development Neo4j

A dedicated developer-side database, separate from the workstation's Arena
service. The Compose project is `isaacautomator-dev`; service is
`automator-neo4j`. Do not reuse Arena credentials, volumes or its container.

## Start and connect

From the repository root:

```sh
docker compose --env-file /dev/null -f .devcontainer/docker-compose.yml \
  up -d --build --no-deps --wait --wait-timeout 180 automator-neo4j neo4j-gateway
docker compose --env-file /dev/null -f .devcontainer/docker-compose.yml ps
```

This starts **only Neo4j and its localhost TCP gateway**, not a replacement editor
container. The custom images are built from the narrow `.devcontainer/neo4j`
context. `/dev/null` suppresses
implicit host `.env` loading for these standalone commands; no source secret file
is required. Shell port overrides still work.

Host endpoints (on the machine running the Docker daemon):
- Browser/HTTP: `http://127.0.0.1:17474`
- Direct Bolt: `bolt://127.0.0.1:17687`

After **Dev Containers: Rebuild Container** from the host editor, the workspace
service joins the private network and can reach `automator-neo4j:7474/7687`.
The app gets non-secret `ISAAC_AUTOMATOR_NEO4J_URI` and
`ISAAC_AUTOMATOR_NEO4J_HTTP_URI` discovery variables. These are not credentials and
are not automatically consumed by the evidence CLI or an agent/MCP server.
Use `bolt://` directly inside Compose; the host-advertised address is for Browser,
not a routing address for other containers.

The app's original Dockerfile, features, mounts, editor settings, agent setup and
lifecycle hooks are preserved. Both `/workspaces/IsaacAutomator` and legacy `/app`
refer to the workspace. Rebuilding the editor is disruptive, so service-only
verification does not perform that rebuild or execute the existing setup hooks.
Do not run `up app` from a container against an external Docker daemon: bind paths
must resolve on the daemon host; use the host editor's normal rebuild workflow.

Change host ports with `ISAAC_NEO4J_HTTP_PORT` / `ISAAC_NEO4J_BOLT_PORT` in the
launch environment. Bind addresses remain **127.0.0.1**. Use SSH tunneling when the
Docker daemon is remote; do not expose plaintext HTTP/Bolt on a public interface.
Multiple checkouts need separate Compose project names and non-conflicting ports.
Use the same project/port overrides consistently for start, stop and rebuild.

## Credentials and readiness

Bootstrap generates a cryptographically random administrator password inside the
private `neo4j-auth` named volume. Directory ownership is the Neo4j user, mode
0700; the auth file `/automator-secrets/auth` is mode 0600. It is not mounted into
the workspace service, stored in Git, baked into the image, or printed by health
checks. Existing credentials are not overwritten. Missing credentials alongside
initialized data, unsafe file permissions or links cause startup failure.

The initial account is `neo4j`. For interactive Browser access, a trusted human
administrator may retrieve the generated credential locally from that protected
volume into a password manager. Do not paste it into a chat, repository, command
history or Compose environment. Ordinary health checks do not require revealing it:

```sh
docker compose --env-file /dev/null -f .devcontainer/docker-compose.yml \
  exec -T automator-neo4j python3 /opt/automator-neo4j/healthcheck.py
```

The health check performs an authenticated `RETURN 1` transaction and verifies
its result. An open HTTP port alone is not readiness. Keep the generated
credential and database in sync; changing the database password separately makes
the saved health credential stale. No automatic password rotation is implemented.

## Security and scope

- Official Neo4j **5.26.30 Community** base pinned by multi-platform SHA256 digest.
  Custom image installs Python 3 for bootstrap/health logic. OS package installation
  is not a fully reproducible package lock; upgrade/rebuild only after validation.
- Non-root UID/GID 7474; all capabilities dropped; no privilege escalation.
- Internal-only graph network; no repo, Docker socket, cloud credentials or
  user-home mounts in the database container. Docker 29 does not publish ports
  on internal-only endpoints. A digest-pinned HAProxy 3.2 gateway joins the graph
  and ingress networks and publishes only the two loopback ports. Its configuration
  forwards TCP only to the fixed database endpoints; it receives no secrets or
  volumes. It runs as UID/GID 65532, read-only, without capabilities, with bounded
  resources. Docker DNS resolvers track database replacement. Gateway health
  checks configuration; database readiness separately authenticates a transaction.
- No APOC/plugin installation, no unrestricted procedures, restricted procedure
  allowlist, file-URL CSV imports disabled and usage reporting disabled.
- 2 GiB memory limit, bounded heap/page cache, 2 CPUs, process limit and rotated
  Docker logs. Internal networking blocks ordinary internet egress, not access
  to every possible service on the Docker host; this is not a hostile-admin sandbox.

**This is a trusted-developer database, not an agent-safe query endpoint.**
Community Edition does not supply the planned granular reader/writer RBAC.
Its administrator credential must not become an agent retrieval credential.
No Enterprise license acceptance, MCP registration or fake restricted reader is
introduced. Direct administrator database access is powerful and not bounded by
the offline graph CLI's query policy.

The canonical RDF/NetworkX evidence graph remains independent. Creating this
service does **not** ingest its existing claims. Freshness-aware publication of a
rebuildable Neo4j projection and a separately authorized read-only retrieval
boundary remain explicit roadmap gates. Do not treat manually inserted data as
canonical, current, reviewed or verified deployment evidence.

## Lifecycle, backup and removal

```sh
# Stop with data and credentials retained:
docker compose --env-file /dev/null -f .devcontainer/docker-compose.yml stop neo4j-gateway automator-neo4j
# Restart the same persisted service:
docker compose --env-file /dev/null -f .devcontainer/docker-compose.yml \
  start --wait --wait-timeout 180 automator-neo4j neo4j-gateway
```

Closing the Compose-backed devcontainer stops the project; named volumes survive.
`unless-stopped` restarts the service after an unexpected exit/daemon restart,
not after an explicit stop. Docker health failures do not themselves trigger a
restart; inspect a failed health state rather than assuming automatic recovery.

Data, logs and auth have separate project-scoped named volumes. Plain Compose
`down` preserves them. **`down --volumes` deletes the graph and its credentials**;
never use that for a normal stop, upgrade or rebuild. Do not prune volumes broadly.
Stop the database before making a coordinated volume backup; protect the auth
backup as a secret. Restore matching data/auth snapshots together. Neo4j volumes
are independent of the disposable app container, not immune to host disk loss.
An image upgrade requires a compatible backup and explicit recovery/upgrade tests.

## Verification

Unit/config tests are in `src/tests/knowledge_graph/test_neo4j_*.py`:

```sh
"$HOME/.cache/isaacautomator-graph/venv/bin/python" -m unittest discover \
  -s src/tests/knowledge_graph -p 'test_neo4j_*.py' -v
# Real smoke test, after building both images:
python3 src/tests/knowledge_graph/neo4j_smoke.py
```

The smoke test creates a uniquely named temporary Compose project and random host
ports. It tests authenticated read/write, rejection of unauthenticated requests,
host-loopback connectivity, non-root/network/mount settings, persistence across
container recreation, file-import denial and an internet-connectivity denial
probe. Finally it deletes **only its own test project and test volumes**, never
normal development or Arena data. Credentials and server logs are not emitted.

See [recorded verification](ACCEPTANCE.md) and the
[approved plan milestone](../../.agents/references/plans/isaacautomator-evidence-graph-plan.md)
for architecture and remaining acceptance gates.
