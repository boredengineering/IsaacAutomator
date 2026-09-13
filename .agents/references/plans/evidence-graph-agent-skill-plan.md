# IsaacAutomator Evidence-Graph Agent Skill Implementation Plan

**Status:** Initial explicit-load advisory skill implemented and verified on
2026-09-10; startup discovery and broader Graph-RAG development remain open.
Protected AGENTS.md discovery was omitted after its approval timed out; explicit
loading and README discovery work. See the continuation roadmap below for the
2026-09-13 readiness check and unimplemented milestones.
**Goal:** Make graph creation, visual exploration and evidence-grounded agent work reproducible.
**Architecture:** A repository skill and agent brief use the existing bounded graph CLI. Neo4j remains a one-way developer visualization copy. No new daemon, model runtime, MCP configuration or database-admin credential is added to an agent.
**Stack:** Markdown agent/skill specifications, existing Python graph CLI, unittest, optional Docker Compose/Neo4j.

## Current context and scope

The canonical graph contains source-attributed static claims with RDF/SHACL
validation and source-policy freshness checks. The initial `neo4j-load` snapshot
was published and independently read back in the historical execution results
below; that does not establish today's projection freshness or service health.
Existing source transport remains incomplete; graph data does not prove
successful cloud/GPU execution.

Follow this repository's `.agents/skills/isaac-automator/` convention, not the
Hermes application's own skill-source layout. Use the repository Apache-2.0
license. Do not invent a named contributor or install a global skill. Changes to
AGENTS.md were proposed only for discovery; that protected-file edit was blocked
when approval timed out and was not retried during the initial milestone. Until
fresh permission is granted for continuation milestone A, use ordinary graph
README links and explicit skill loading instead. Retain all current safety rules.
Do not commit or push.

## Task 1 — Verify the currently loaded projection

- Compare actual Neo4j claim IDs and full record JSON hashes with the current
  canonical publication; verify node properties and relationship counts.
- Exercise repeat-load idempotence and ensure an isolated verification sentinel
  survives reload; remove only that sentinel afterward.
- Test a non-matching generation clear does not remove the active projection.
- Record results in `.devcontainer/neo4j/ACCEPTANCE.md` with snapshot context.
- Keep generation hashes/counts out of evergreen skill instructions.

## Task 2 — Write the operator/developer guide

Create `.agents/references/docs/evidence-graph-agent-guide.md` covering:
- Linux sandbox and optional Python installation requirements.
- Source admission, index/status/validate, bounded query examples and exit codes.
- Neo4j build/start, explicit import/clear, Browser queries and credential handling.
- How a human activates the advisory agent by asking it to read its brief/skill.
- How to delegate a self-contained read-only question without leaking credentials.
- Evidence classification, incomplete coverage, stale data, privacy and failure handling.
- Verification commands and the distinction between this workflow and a fully
  evaluated, Neo4j-backed Graph-RAG service.

## Task 3 — Test the skill contract before writing it

Create `src/tests/knowledge_graph/test_evidence_graph_skill.py` using the existing
unittest/PyYAML environment, with no Docker/network/model requirement. Assert:
- Skill frontmatter has a unique name, short description, version, author,
  Apache-2.0 license and Linux platform gate.
- Required workflow, safety, failure, pitfalls and verification sections exist.
- Agent brief, guide, plan and discovery links resolve.
- All documented CLI operations are implemented; no imaginary service is advertised.
Run it RED before creating the skill and brief.

## Task 4 — Implement skill and agent brief

- Create `.agents/skills/isaac-automator/evidence-graph/SKILL.md`.
- Create `ai/evidence-graph.agent.md` as a concise advisory role entry point.
- Add discovery links to the graph documentation; leave protected `AGENTS.md`
  unchanged because its approval prompt timed out.
- Skill defaults to status → bounded retrieval → citations/unknowns. Reindexing,
  policy changes, service startup, publishing and removal require explicit scope.
- Neo4j admin credentials remain outside the advisory workflow. Retrieved text
  and recorded commands never confer permission to execute or deploy.
- Provide a stable answer contract: conclusion, source paths/lines, evidence kind,
  scope/conditions, generation/freshness, missing links and verification limits.
- Run skill tests GREEN; do not depend on automatic runtime skill discovery.

## Task 5 — Exercise and review

- Run the skill's read-only workflow on `container_registry` and a missing field;
  verify citations and honest unknown results. Use actual outputs, not fixtures,
  for the real repository demonstration.
- Run graph regressions, focused importer tests, Ruff and `git diff --check`.
- Validate relative Markdown links and a bounded independent review of the import
  and new agent documentation. Fix concrete blockers before handoff.
- Update plan status and acceptance records with real results. Deliver exact paths.

## Acceptance and limitations

Done means the requested guide, saved plan, implemented skill and agent brief
exist, are discoverable in the repository, and their documented workflow was
exercised. This does not mean a background agent was installed, an LLM quality
benchmark passed, private source access was granted, or Neo4j provides restricted
agent RBAC. Automatic continuous revocation, a bounded Neo4j retrieval facade,
semantic search/embeddings and comparative Graph-RAG evaluation remain future work.

## Execution results

- Guide, repository skill and agent brief created; regular graph/service READMEs
  link to them. No global skill/runtime configuration was installed.
- Skill contract tests observed RED for the absent skill, then GREEN after
  implementation. All three contract tests pass, including relative links and
  parsing the documented commands using the real CLI parser without side effects.
- Full graph suite: 120 tests passed; Ruff, Compose config, shell syntax and diff
  checks passed. A focused AST dangerous-call scan found no matches in the three
  new production projection modules. Existing RDFLib deprecation warnings remain.
- Actual Neo4j readback conserved all 226 claim records/hashes, 190 entity/literal
  node property sets and 177 supported edges. Repeat load, unrelated-node
  preservation, temporary sentinel cleanup and wrong-generation clear were tested.
- Independent import review passed with no blockers and 20 focused tests.
- A separate advisory agent loaded the implemented brief/skill and performed the
  read-only known-field/missing-field workflow. Its answer cited actual source
  claims, reported unresolved conditions/truncation, and abstained for the missing
  field. The same agent found no concrete documentation/authority contradictions.
  This was one bounded demonstration, not a generalized LLM benchmark.
- See [the acceptance record](../../../.devcontainer/neo4j/ACCEPTANCE.md) for the
  snapshot, commands, tested boundaries and remaining evaluation gaps.

## Continuation roadmap — startup discovery to evaluated Graph-RAG

### Scope and observed baseline — 2026-09-13

This update authorizes **planning only**. It does not authorize AGENTS.md edits,
index refresh, policy expansion, service startup, Neo4j publication, agent/MCP
configuration, cloud operations, commits or pushes. Obtain implementation scope
before executing any pending task. Preserve unrelated working-tree changes.

The [master graph plan](isaacautomator-evidence-graph-plan.md) owns extraction,
evidence semantics and backend/security release gates. This plan owns agent
discovery, activation, task routing and answer-quality acceptance. Future updates
must distinguish source implemented, offline tests passed, live workflow verified
and deployed integration; none is interchangeable with another.

| Capability | Evidence / present status | Remaining gate |
| --- | --- | --- |
| Repository startup instructions | AGENTS.md is in this session's startup context; it has no evidence-graph entry point | Explicitly approved discovery edit and fresh-session test |
| Advisory role and skill | Brief, repository skill and bounded CLI exist; explicit-load workflow was previously exercised | Automatic discovery is not established by file existence |
| Runtime tool integration | No dedicated graph tool is exposed in this session; CLI is reachable through terminal | Optional registered tools are a separate milestone |
| Canonical graph freshness | Actual `./knowledge-graph status` returned exit 3, `stale`: sources, policy or extractor changed | Authorized refresh and current-query checks; cause not narrowed to an individual file |
| Neo4j projection | Historical scoped import/readback passed | Current service health/projection generation not rechecked; not the agent query backend |
| Answer generation | Assistant can reason over CLI evidence; no embeddings or model calls inside graph CLI | Held-out comparison against direct source search |
| Shared graph support | `shared_contract.py` and `shared_client.py` exist as separate components | Do not infer a wired shared retrieval backend or make it a local-use prerequisite |

The stale result is an observed checkpoint, not a permanent environment fact.
No rebuild or service mutation occurred during this readiness check. General
session history retrieval is separate from graph retrieval; reports must state
which source was actually used.

### Milestone A — Discover the existing workflow at agent startup

**Objective:** Make relevant repository work discover the bounded advisory skill
without installing a service or making graph use mandatory for unrelated tasks.

**Files:** proposed edits to `AGENTS.md`, `ai/evidence-graph.agent.md`,
`.agents/skills/isaac-automator/evidence-graph/SKILL.md`, and
`src/tests/knowledge_graph/test_evidence_graph_skill.py`. Keep `CLAUDE.md` as its
existing shared-instructions pointer; do not duplicate the rules there.

- [ ] Obtain explicit permission to add the small AGENTS.md discovery section;
  the previous timed-out approval and this plan update are not that permission.
- [ ] Add a failing contract test for the discovery link and trigger language.
  Require configuration wiring, dependency tracing and change-impact triggers,
  plus a distinction between graph evidence and runtime verification.
- [ ] Add the minimal discovery text: read the brief/skill, check status, use
  bounded queries only when current, and report stale/unavailable honestly.
  Do not require reindexing, database access or a graph query for every prompt.
- [ ] Clarify failure behavior in the brief/skill: stop the graph path on stale
  or unavailable; separately scoped public source inspection may continue, with
  an explicit label. Never use direct reads to bypass quarantined graph sources.
- [ ] Run contract tests GREEN and independently review authority boundaries.
- [ ] Exercise a genuinely fresh supported agent session from the repo root,
  with no resumed history or explicit graph hint in the question. Ask a neutral
  configuration-wiring question and inspect the tool trace for brief/skill load,
  status, then bounded query or an honest stale/unavailable report.
- [ ] Test subdirectory launches and a fresh checkout separately. Record the
  context file actually loaded for each agent/runtime; do not claim all clients
  recursively discover repository skills. No global skill installation or
  Hermes/VS Code configuration change without separate approval.

**Acceptance:** Both static contract checks and a fresh-session behavioral trace
pass. Instructions guide model behavior; they are not enforced tool permissions.
Record model/runtime and startup directory. A session that already read the
brief, like the current one, is not evidence of automatic discovery.

### Milestone B — Restore and maintain usable evidence explicitly

**Objective:** Make freshness failures actionable while preserving fail-closed
retrieval and independent developer control of the Neo4j copy.

**Files:** existing `src/knowledge_graph/cli.py`, `publication.py`, `queries.py`,
`src/tests/knowledge_graph/test_cli.py`, `test_publication.py`, `test_queries.py`,
and `.agents/references/docs/evidence-graph-agent-guide.md`; edit production code
only if characterization exposes an actual defect.

- [ ] Obtain explicit local-index refresh permission. Inspect the public policy
  without expanding it, then run `./knowledge-graph index`, `status`, and
  `validate` sequentially, stopping on the first failure.
- [ ] On current/conforming output, exercise a known field and a missing field;
  capture generation, citations, scope, conditions and truncation.
- [ ] Use isolated public test fixtures to exercise source/policy/extractor
  changes, unavailable runtime, failed rebuild and concurrent publication.
  Never dirty real source or revoke the user's real policy merely for a test.
- [ ] Require stale results to be withheld; a failed rebuild must not promote an
  old generation as current. Show the next authorized action, not an automatic
  startup mutation. Use RED/GREEN tests before any needed implementation fix.
- [ ] If Neo4j refresh is separately authorized, validate the canonical data,
  run `neo4j-load`, and independently read back scope/generation/provenance.
  Otherwise explicitly record the projection as not refreshed.

**Acceptance:** Current known/unknown queries and isolated failure-path tests
pass. No unauthorized indexing, publication, credential access or service change.
Recurring refresh, watchers and startup hooks are deferred opt-ins, not defaults.

### Milestone C — Cover the tools we are actually developing

**Objective:** Answer useful cross-component questions without treating design
plans, tool names or static declarations as proof of working integration.

**Files:** `configs/knowledge-graph/public.yaml`, existing extractors under
`src/knowledge_graph/extractors/`, existing `test_profile_paths.py`,
`test_terraform.py`, `test_ansible.py`, `test_extractors.py`; benchmark files
proposed under master-plan Task 10, not yet claimed as implemented.

- [ ] Inventory public source candidates for workstation profiles, CLI/TUI,
  Terraform backend selection, Ansible transport, cost estimation and graph
  commands. Start from observed definitions/usages; no directory-wide admission.
- [ ] Independently review each candidate before any exact-path policy addition.
  Never relax screening because a needed file is withheld. Report that coverage
  gap, or design a separately reviewed public contract instead.
- [ ] Write failing fixtures for one missing relation at a time; extend the
  relevant existing extractor only within its static-analysis contract; rerun
  identity, conditions, source-location and privacy regressions.
- [ ] Add independent source-backed questions about backend selection versus
  bucket creation, profile declaration versus consumer, estimator availability
  versus an authenticated quote, and graph CLI versus Neo4j visualization.
- [ ] For costing, distinguish the in-repo Infracost adapter from disposable
  C3X trials; importing a catalog is not correct G4/Flex pricing. Never admit
  GCP_API_KEY, credentials, raw state, private plans or operational logs.
- [ ] Keep document/history and test-execution ingestion behind the master
  plan's separate evidence-adapter gate. An existing plan is not automatically
  indexed evidence, and a test definition is not a passing test result.

**Acceptance:** Each newly covered relation has an attributed fixture and a
current bounded-query demonstration after authorized refresh. Unresolved and
withheld paths remain explicit; no promise of exhaustive codebase understanding.

### Milestone D — Evaluate whether graph-assisted answers help

**Objective:** Demonstrate benefit over direct source search before adding more
retrieval infrastructure. Execute with master-plan Task 10 and section 10.

**Proposed new files:** `src/tests/knowledge_graph/benchmark_cases.json`,
`src/knowledge_graph/benchmark.py`, and
`src/tests/knowledge_graph/test_benchmark_contract.py`. These are future files.

- [ ] Freeze independently reviewed gold answers before running the comparison;
  include direct lookups, multi-hop paths, conditional links, stale/unknown,
  conflicting evidence and embedded prompt-injection cases.
- [ ] Write the benchmark contract tests RED, implement bounded case/result
  validation GREEN, and review it independently of extractor implementation.
- [ ] Compare direct source search and CLI-assisted retrieval over the same
  admitted public corpus, with matching model, prompt and resource budgets.
  Keep restricted/private input out of both arms; obtain model/network scope
  before external inference and retain sanitized real traces only.
- [ ] Measure citation correctness, supported answers, abstention, coverage,
  latency, output/token costs and repeated-run variation. Do not count a
  retrieval response or SHACL pass as answer-quality acceptance.
- [ ] Require zero safety violations and fabricated execution claims, and the
  master plan's usefulness gate; record negative results rather than adding
  infrastructure to conceal them.

**Acceptance:** Independent review of actual benchmark outputs supports the
bounded usefulness claim. If not, retain the explicit experimental CLI and
investigate coverage/answering failures before proceeding.

### Milestone E — Optional first-class agent tools

**Objective:** Expose the already qualified bounded reads without giving the
agent writer operations or arbitrary database access. Not needed for A–D.

**Proposed new files:** `src/knowledge_graph/mcp_server.py`,
`src/tests/knowledge_graph/test_mcp.py`, and a separately reviewed optional
dependency manifest, following master-plan Task 11.

- [ ] After D passes, choose opt-in stdio MCP or continue with the CLI; verify
  current Hermes/tool-client documentation before designing registration.
- [ ] Write RED/GREEN schema and permission tests for only status, field lookup,
  find, trace, impact and evidence detail. Do not expose index, load, clear,
  arbitrary shell, arbitrary Cypher or credentials.
- [ ] Verify freshness, cancellation, resource bounds, malformed arguments and
  unavailable-service behavior through real protocol calls, not mocks alone.
- [ ] Obtain explicit agent-runtime configuration permission, register only
  allowlisted read operations, then verify discovery in a new client session.
- [ ] Test removal/disabled mode and deployment independence. A successful
  server launch is not successful client registration or model tool selection.

**Acceptance:** Protocol tests, effective tool list and fresh-session call trace
agree. Do not describe CLI-only operation as an installed MCP integration.

### Milestone F — Optional Neo4j-backed or semantic retrieval

**Objective:** Extend the backend only if measurements justify it. The existing
Neo4j developer copy is not automatically promoted into an agent service.

- [ ] First write a separate backend design under the master plan's section 8
  security gates: fixed query templates, repository scope, generation/policy
  binding, timeout/result bounds, credentials isolated from the model, and
  effective-privilege tests. Do not claim Community admin credentials are a
  server-enforced read-only identity.
- [ ] Plan application mediation with its actual threat model and independent
  review, including malicious requests, revoked/stale projections and outages.
  No agent-supplied Cypher or admin escape hatch.
- [ ] Preserve canonical RDF and local CLI independence; test cross-backend
  provenance/condition parity and forbid stale fallback answers.
- [ ] If semantic retrieval is justified, obtain separate model/data approval,
  maintain independently revocable derived stores, and compare against D using
  ablation tests. Embeddings are optional, not synonymous with Graph-RAG.

**Acceptance:** Backend security/parity tests and measured answer benefit pass
before making any Neo4j-backed Graph-RAG claim. Exact new files and dependencies
must be specified in the reviewed design; no placeholder service is a deliverable.

### Execution order, verification and handoff

Priority: **A → B → C → D → optional E/F**. Evidence schemas and policy changes
have one coordinating owner; independent workers may review public source paths
or author non-overlapping test fixtures. Use independent specification/security
review at each gate, followed by test/result review before marking it complete.
Shared-ledger, drift approval and remote-backend mechanisms remain optional;
none blocks the local advisory workflow or ordinary cloud deployment.

Existing offline verification commands, to run with the prepared environment:

```sh
"$HOME/.cache/isaacautomator-graph/venv/bin/python" -B -m unittest src.tests.knowledge_graph.test_evidence_graph_skill -v
"$HOME/.cache/isaacautomator-graph/venv/bin/python" -B -m unittest discover -s src/tests/knowledge_graph -p 'test_*.py' -v
git diff --check -- .agents/references/plans/evidence-graph-agent-skill-plan.md .agents/references/plans/isaacautomator-evidence-graph-plan.md
```

Review test entry points before execution; Docker smoke tests, model runs and
index/publication operations need their separate authorized scope. Missing
optional dependencies are a reported blocker, not permission to install them.
New benchmark/MCP suites are not runnable until their proposed files exist.

For each completed milestone record the actual command/exit status, source and
generation context, test scope, review outcome, limitations and next unchecked
task. Keep historical results above; do not overwrite them with today's claims.
The immediate next implementation batch is **A plus an explicitly authorized
local refresh for B**, not a new database, embedding service or automatic agent.

### Planning-update verification — 2026-09-13

- Existing `test_evidence_graph_skill` suite: **3 tests passed** (contract,
  relative links and documented CLI argument parsing). This does not test the
  proposed startup discovery behavior or future benchmark/MCP implementation.
- New inter-plan links and the continuation heading anchor resolve.
- Scoped `git diff --check` passed. AGENTS.md, CLAUDE.md, the agent brief and
  repository skill remain unchanged; this update changes only the two graph plans.
- No full graph regression, cloud deployment, index refresh, service change,
  Neo4j publication or fresh-session behavioral acceptance was performed.
- Independent planning review found two corrections: historical AGENTS.md
  permission wording (already corrected while review ran), and a proposed
  benchmark-runner path mismatch. Both are resolved in the final plans; the
  runner is consistently `src/knowledge_graph/benchmark.py`, invoked as
  `python3 -m src.knowledge_graph.benchmark`. The reviewer otherwise found the
  scope and acceptance gates appropriately bounded. This is plan review, not
  implementation acceptance; no second reviewer pass is claimed.
