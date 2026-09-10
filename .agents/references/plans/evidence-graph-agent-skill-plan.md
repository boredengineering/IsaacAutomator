# IsaacAutomator Evidence-Graph Agent Skill Implementation Plan

**Status:** Implemented and verified on 2026-09-10. Protected AGENTS.md discovery
was omitted after its approval timed out; explicit loading and README discovery work.
**Goal:** Make graph creation, visual exploration and evidence-grounded agent work reproducible.
**Architecture:** A repository skill and agent brief use the existing bounded graph CLI. Neo4j remains a one-way developer visualization copy. No new daemon, model runtime, MCP configuration or database-admin credential is added to an agent.
**Stack:** Markdown agent/skill specifications, existing Python graph CLI, unittest, optional Docker Compose/Neo4j.

## Current context and scope

The canonical graph contains source-attributed static claims with RDF/SHACL
validation and source-policy freshness checks. `neo4j-load` has successfully
published the current dataset; stored content still needs independent readback
verification before claiming import fidelity. Existing source transport remains
incomplete; graph data does not prove successful cloud/GPU execution.

Follow this repository's `.agents/skills/isaac-automator/` convention, not the
Hermes application's own skill-source layout. Use the repository Apache-2.0
license. Do not invent a named contributor or install a global skill. Changes to
AGENTS.md were proposed only for discovery; that protected-file edit was blocked
when approval timed out and will not be retried. Use ordinary graph README links
and explicit skill loading instead. Retain all current safety rules. Do not commit or push.

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
