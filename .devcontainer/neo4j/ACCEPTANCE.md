# Dedicated development Neo4j acceptance

Verified locally on 2026-09-10. The original service milestone is recorded below;
the later explicit projection and advisory-skill milestone is appended at the end.
Neither establishes production hardening or full graph-plan completion.

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

## Follow-up: explicit projection and advisory skill (2026-09-10)

This follow-up supersedes the earlier service-only statement that no claims were
uploaded. The custom database image was rebuilt/recreated without rebuilding the
editor container, then `./knowledge-graph neo4j-load` succeeded against the actual
`isaacautomator-dev` service.

- Canonical input: 24 sources, 127 entities and 226 independently attributed claims.
- Neo4j: **190 entity/literal nodes, 226 claim nodes and 177 supported EVIDENCE edges**.
- Generation: `e8e3fbc5ece1cfd80f131c42c7a83f7b6e65ca912cd52654ee9d534abf3fef2f`.
- Snapshot: `urn:ia:snapshot:6e71661eb78d2a3f166c31429cc5e1f2b11bd47352e91f7475b2c18d5e2b2b20`.
- Actual paginated database readback compared every term/entity property, every
  full Claim record and hash, and every subject/object endpoint with the validated
  canonical export. Supported edge IDs, hashes and endpoints also matched.
- A repeated load did not duplicate data. A uniquely marked unrelated test node
  survived replacement and was then removed; cleanup was verified. An attempted
  clear with a deliberately different generation reported `matched: false`,
  deleted zero nodes and preserved the active projection.
- Full optional graph suite: **120 tests passed**, including **3 new skill contract
  tests** for frontmatter, links/discovery and real CLI argument parsing. Ruff,
  Compose config, wrapper shell syntax and `git diff --check` passed. RDFLib
  deprecation warnings remain. The prior 195-test deployment result above was
  not rerun for this optional documentation/import follow-up.
- Actual CLI validation conformed; `container_registry` returned source-backed
  desired/static evidence, while `__missing_graph_field__` returned an empty
  unknown result. Truncation and incomplete consumer paths remained explicit.
- Independent import review found no blockers in this developer snapshot scope
  and ran 20 focused importer/export/CLI tests. It did not run live Docker tests;
  the parent performed the database readback described above.
- A separate advisory-agent demonstration loaded the brief/skill/guide, ran
  status and the known/missing-field queries, and returned attributed claims,
  unresolved conditions, truncation and an honest unknown. It found no concrete
  documentation or authority contradictions. This is one demonstration, not a
  general model-quality benchmark.

The [guide](../../.agents/references/docs/evidence-graph-agent-guide.md),
[skill plan](../../.agents/references/plans/evidence-graph-agent-skill-plan.md),
[skill](../../.agents/skills/isaac-automator/evidence-graph/SKILL.md) and
[agent brief](../../ai/evidence-graph.agent.md) document the implemented workflow.
The protected AGENTS.md discovery edit was not applied because its approval
timed out; ordinary README links and explicit file loading provide discovery.

Remaining boundaries: Neo4j is an import-time-checked snapshot, not a continuously
fresh/revoked agent backend. Read-only agent mediation, generalized LLM answer
evaluation, concurrent-import stress/rollback testing and cross-scope integration
tests remain outside this acceptance. Owned projection nodes and their incident
relationships are disposable. An import with no receipt has an unknown commit
outcome; a guarded clear does not prove cancellation of outstanding work. No
credentials were emitted, no cloud resources provisioned, and no global agent
configuration, commits or pushes were performed.
