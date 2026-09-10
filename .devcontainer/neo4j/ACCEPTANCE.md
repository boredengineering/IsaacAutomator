# Dedicated development Neo4j acceptance

Verified locally on 2026-09-10. This records the development-service milestone,
not evidence ingestion, production hardening or full graph-plan completion.

## Delivered

- Custom Neo4j 5.26.30 Community image, immutable upstream digest, narrowly
  allowlisted build context, non-root bootstrap and authenticated health check.
- Generated private named-volume credential. A small Java bridge invokes the
  pinned upstream initial-password command API in-process, accepting the password
  over stdin instead of exposing it in process arguments or environment variables.
  Build-time compilation checks that API; the real authenticated smoke verifies
  that the generated credential works. No upstream password-hash format is reimplemented.
- Compose devcontainer integration preserving existing features, lifecycle hooks,
  editor/agent customizations and credential mounts on the app only.
- Internal-only database with separate data/log/auth volumes. A digest-pinned,
  non-root read-only HAProxy gateway publishes localhost HTTP and Bolt without
  giving the database a default internet route. The gateway receives no secrets.
- Restart policy, graceful stop, resource limits, disabled file import/plugins,
  operational documentation and explicit independent-lifecycle/backup caveats.

## Actual checks and results

1. Both custom images built successfully with Docker Compose.
2. `python3 src/tests/knowledge_graph/neo4j_smoke.py` passed against an isolated
   newly created test project with random host ports. It verified authenticated
   writes/reads, unauthenticated HTTP 401, persistence after container recreation,
   private network/non-root/mount metadata, host HTTP connectivity, file-import
   denial and failure of a TCP internet probe. Only its own project/volumes were
   removed, including after failed attempts. This probe is not a proof of total
   host/network isolation.
3. Full graph suite: **97 tests passed**, including **22 Neo4j unit/config tests**.
   Source: optional graph Python environment and `unittest discover` with
   `-s src/tests/knowledge_graph -p 'test_*.py' -q`.
4. Existing deployment suite: **195 tests passed** using
   `PYTHONPATH=/workspaces/IsaacAutomator sh src/tests/run_all.sh`.
   These are local/mock checks, not cloud deployment validation. Existing RDFLib
   deprecations and Textual resource/slow-task warnings remain nonblocking.
5. Ruff 0.13.1 passed for graph, graph tests and Neo4j Python files.
   Compose config validation and `git diff --check` passed. A production Python
   AST scan found no eval/exec, os.system, unsafe pickle or shell=True calls.
6. The actual `isaacautomator-dev` database and gateway were started and both
   reported healthy. Gateway maps **127.0.0.1:17474** and **127.0.0.1:17687**.
   An independent host-network probe received HTTP 401 without credentials and
   negotiated **Bolt 5.4**. A complete authenticated Bolt driver query was not run;
   database authentication/read/write was verified over transactional HTTP.
7. Existing offline graph remains current and SHACL-valid: **226 claims,
   127 entities, 24 sources**. No claims were uploaded into Neo4j.
8. The old `neo4j-arena` remained stopped, exit code 137. No Arena image, volume,
   configuration or service was changed.

## Failures found and corrected

- The official image contains empty `databases` and `transactions` directories.
  Treating any data entry as an initialized database refused first boot. A strict
  empty-factory-layout check now handles that case; unknown/nonempty data still
  refuses credential regeneration. A separate regression ensures an incomplete
  seed alongside the empty factory layout cannot skip auth validation.
- Docker 29.7.2 accepted internal-only port bindings in HostConfig but did not
  actually publish them. Actual NetworkSettings and host connectivity exposed the
  problem. The fixed two-port gateway preserves internal-only DB networking and
  makes localhost endpoints reachable. Configured bindings alone are not proof.

## Review and boundaries

Independent review passed with no concrete security or logic blockers in the
requested local developer-service scope. The reviewer inspected the bootstrap,
Java bridge, Compose/devcontainer diff, gateway, health check and tests, and
independently ran all 22 focused tests successfully. Its initial prose verdict
received a JSON-format correction only; no additional review or test run is
claimed for that formatting step. Parent verification confirmed the JSON verdict.

The active editor container was not rebuilt or replaced; the user must use the
host editor's normal **Dev Containers: Rebuild Container** action to adopt the
Compose workspace/network. App image build, feature installation and post-create
hooks were not rerun. The new database/gateway are intentionally left available.
No cloud resources, commits, pushes, Enterprise acceptance or MCP configuration.

This is a trusted local developer/admin service. Community lacks the planned
reader/writer role isolation. It is not an agent-safe database endpoint. Evidence
publication, privacy/freshness revocation and bounded retrieval mediation remain
separate plan gates. Backup/restore, secret rotation and image-upgrade recovery
were documented but not exercised; current data/auth volumes must remain paired.
