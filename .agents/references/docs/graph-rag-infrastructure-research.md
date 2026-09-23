# Graph-assisted infrastructure reasoning: comparison and next steps

## Scope and outcome

This is a source-based comparison of existing approaches, not a framework
installation, new collection plan or measured performance result. The goal is
better reasoning about the infrastructure needed for the robotics workload,
not reproduction of every host detail.

The shared-startup guidance is now implemented in
[`AGENTS.md`](../../../AGENTS.md#evidence-graph-for-infrastructure-reasoning)
after renewed user authorization. The earlier protected-file approval timed out;
the subsequent edit added links and task-specific graph-use instructions following
the existing brief and skill, without granting new mutation permissions. This is
instruction-based discovery for agents that load the file, not an installed
retrieval hook. The index was not refreshed and performance remains unmeasured.

## What this repository already has

Direct source review, not graph retrieval:

- [`ai/evidence-graph.agent.md`](../../../ai/evidence-graph.agent.md) defines an
  advisory role using bounded CLI queries and explicit source attribution.
- The [graph skill](../../skills/isaac-automator/evidence-graph/SKILL.md) specifies
  freshness checks, source paths/lines and claim IDs, limits, conditions and honest
  unknowns. `find` is literal substring search, not vector search.
- The [usage guide](evidence-graph-agent-guide.md) describes a canonical
  RDF/PROV-O evidence index and a separately published Neo4j visualization snapshot.
  It explicitly says that a restricted Neo4j reader and evaluated answer-generation
  pipeline are not implemented.
- The latest read-only status check in this session returned exit 3, `stale`:
  “Sources, policy or extractor changed; rebuild before querying.” No refresh,
  Neo4j publication or graph retrieval was performed after that result.

This is already a useful foundation for graph-assisted retrieval, but not an
installed equivalent of the external end-to-end GraphRAG systems below. The
assistant must actually consult current evidence for it to help.

## Comparable approaches

### 1. Microsoft GraphRAG: entity questions versus whole-corpus questions

Microsoft's Local Search combines an AI-extracted knowledge graph with original
text chunks for questions about specific entities. Global Search instead uses
map-reduce over AI-generated community reports and is described as
resource-intensive; DRIFT adds community context to local queries and develops
follow-up questions.[1]

**Assessment for IsaacAutomator:** configuration wiring and change impact are
usually closer to local, entity-focused retrieval than whole-corpus synthesis.
Borrow the distinction between local evidence retrieval and broader design
summaries. Do not add community-report generation merely to answer a known-field
question. Generated summaries should not replace exact source evidence.

**Boundary:** the external query strategies do not show that our current graph
covers an entire CLI → Terraform → Ansible path, or that global search will improve
our engineering decisions.

### 2. Neo4j GraphRAG Python: targeted graph expansion after retrieval

Neo4j provides vector, hybrid full-text/vector and Cypher-enhanced retrievers.
`VectorCypherRetriever` uses a similarity-search result as an entry point for
additional graph traversal; `HybridCypherRetriever` adds traversal after combined
vector/full-text search. Custom retrievers are also supported.[2]

Its Text2Cypher retriever asks an LLM to generate and execute a query before using
the records to answer the question. The documentation warns that generated
queries are not guaranteed to be syntactically correct.[2]

**Assessment for IsaacAutomator:** this is the closest potential extension pattern:
find a field/resource, traverse a small relevant neighborhood, return only cited
facts. Our bounded CLI already implements a narrower form of the entry-point and
traversal idea, without needing semantic retrieval or database credentials.

**Boundary:** using Neo4j's library would require separate integration and security
review. A custom read-only, bounded retrieval interface would be preferable to
unrestricted generated Cypher. Do not give an agent Neo4j administrator access
or assume the existing developer snapshot is a fresh retrieval backend.

### 3. LightRAG: combine detailed facts, relationships and text

LightRAG describes a knowledge-graph/vector architecture and query modes for
local entity retrieval, global relationships, hybrid retrieval, text-only naive
retrieval and a mix of those modes. It also describes incremental updates and
selective deletion with regeneration of affected graph content.[4]

**Assessment for IsaacAutomator:** two useful ideas are combining exact
configuration evidence with explanatory text, and treating freshness/deletion as
part of retrieval quality. If exact-name retrieval proves insufficient, hybrid
retrieval could be evaluated on the same reviewed public sources.

**Boundary:** this is not a drop-in upgrade to the existing index. Entity
extraction, embeddings, model calls and storage choices add operational complexity.
The project's performance claims are not evidence of gains on our codebase; no
speed, cost or accuracy figure is adopted here.

### 4. Cartography: the infrastructure-relationship analogy

Cartography pulls infrastructure assets and relationships into Neo4j, with
examples such as finding internet-exposed EC2 instances and unencrypted RDS
instances.[3]

**Assessment for IsaacAutomator:** useful inspiration for asking connected
questions about resources, networks and security rather than inspecting isolated
settings. It is an infrastructure graph tool, not by itself a GraphRAG
answer-generation pipeline.

**Boundary:** its infrastructure collection model is not the proposed scope here.
We should not adopt broad asset ingestion, credential access or live cloud scans
to improve repository reasoning. Distinguish declared source relationships from
observed infrastructure; this research does not authorize collecting either new
host or cloud inventories.

## Recommendation: use the existing evidence, measure before expanding

The following are recommendations, not newly implemented features or an approved
large redesign:

1. **Make discovery reliable.** Add concise shared startup guidance in `AGENTS.md`:
   when answering wiring/relationship/change-impact questions, load the brief and
   skill, check status, then choose one narrow query. Skip graph queries for simple
   edits or unrelated tasks. This is instruction-based behavior, not a daemon.
2. **Keep existing boundaries.** On stale/unavailable status, stop graph retrieval
   and report it. A separately authorized public-source review can continue,
   clearly labeled, without bypassing excluded/quarantined sources. Refresh,
   indexing, policy expansion and Neo4j changes remain separately authorized.
3. **Return a compact evidence packet.** Preserve claim IDs, source lines,
   conditions, freshness and truncation in the answer. Separate current
   implementation facts from design proposals and runtime acceptance.
4. **Evaluate the current approach before selecting a framework.** Start with
   questions about reviewed public sources; do not enlarge collection to force
   every test case to have an answer. Coverage gaps are valid findings.
5. **Only then consider retrieval improvements.** If measured failures are about
   naming/synonyms, try hybrid retrieval. If they concern missing modeled
   relationships, consider an explicitly reviewed extractor change. If they concern
   stale data, address freshness maintenance rather than adding embeddings.

I expect the most plausible benefit to be less repeated source exploration and
better-supported cross-file answers. More context can also add latency, stale
claims and distracting relationships. Whether the net effect is positive remains
unmeasured for this repository.

## Small evaluation proposal

No evaluation was run as part of this research. For an explicitly authorized
follow-up, compare ordinary source search with graph-first retrieval:

- Same model, checkout, question, source permissions and answer format; use fresh
  sessions so prior answers do not leak into the comparison.
- Have a reviewer establish expected facts and source citations independently.
- Include an exact-field question, a resource relationship, a change-impact
  question, a missing-link question and a stale-index case.
- Candidate task: “Does a selected software intent reach the deployment command?”
  This is an evaluation question, not a claim that those TUI files are admitted
  by the current graph policy.
- Measure factual correctness, citation support, honest unknowns, required manual
  corrections, files/tool calls, elapsed time and model tokens where available.
- Preserve the freshness gate. Include refresh/setup cost separately rather than
  hiding it in faster query-time measurements.
- Repeat enough to distinguish retrieval gains from model variability; agree the
  acceptable quality/cost trade-off before claiming success.
- Require no forbidden-source access or unauthorized mutations. An apparently
  faster answer that invents a relationship fails acceptance.

Graph retrieval should help us reason about the implementation we have, propose
changes with clearer evidence and find the smallest verification needed. It does
not substitute for Terraform validation, software installation checks or the
actual robotics workload acceptance test.

## Research method and limitations

Read the primary Microsoft and Neo4j documentation and the upstream Cartography
and LightRAG READMEs. The browser search failed to start; an HTTP Google search
returned no useful extracted results. The comparison therefore uses directly
retrieved primary sources, not a comprehensive search ranking or exhaustive market
survey. No package or external project was installed or executed. Upstream pages
can change; source descriptions are observations from this session.

## Sources

[1] https://microsoft.github.io/graphrag/query/overview — microsoft
[2] https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html — neo4j
[3] https://raw.githubusercontent.com/cartography-cncf/cartography/master/README.md — cartography
[4] https://raw.githubusercontent.com/HKUDS/LightRAG/main/README.md — lightrag
