# Offline MVP verification record

Verified locally on 2026-09-10. This is implementation/fixture acceptance for a
limited structural MVP, **not** acceptance of every requirement in the full
implementation plan, a retrieval-quality benchmark, or cloud/GPU verification.

## Executed checks

- Optional Python 3.12.14 environment installed from
  `requirements-knowledge-graph.lock` with hash verification.
- `python -m unittest discover -s src/tests/knowledge_graph -p 'test_*.py' -v`:
  **75 tests passed**, including real Landlock/seccomp denial tests, actual
  sandboxed RDF parsing/SHACL validation, full CLI indexing/querying, stale
  source rejection, policy revocation at request boundaries, cache corruption,
  symlink rejection and concurrent publication.
- `PYTHONPATH="$PWD" sh src/tests/run_all.sh`: **195 existing tests passed**,
  exit 0, in the existing deployment development environment. The unconfigured
  host invocation first failed to import `src` in several tests; setting the
  repository import path resolved that environment issue without changing the
  existing test runner or deployment code.
- `uvx --from ruff==0.13.1 ruff check src/knowledge_graph src/tests/knowledge_graph`:
  passed. Shell syntax, Python compile checks and tracked diff whitespace checks
  passed. An AST scan found no `eval`, `exec`, `os.system`, pickle load calls or
  `shell=True` in graph implementation code. This scan is not a security audit.
- Upstream RDFLib TriG deprecation warnings remain. Existing Textual tests also
  emitted resource/timing warnings; these did not fail their tests.

## Real repository pilot

The checked-in public policy selected **33** paths. The actual source reader
admitted **24** and withheld **9**. Indexing produced **226 claims** and **127
entities**. Coverage additionally recorded **13 unsupported** and **19
unresolved** entries; these are not counts of distinct files.

| Actual command | Result |
| --- | --- |
| `./knowledge-graph index` | Indexed; Landlock + seccomp; static evidence only |
| `./knowledge-graph status` | Current snapshot, 226 claims / 127 entities |
| `./knowledge-graph validate` | SHACL/semantic validation conforms |
| `./knowledge-graph explain-field container_registry --limit 10` | 4 claims / 4 entities; evidence found, complete behavior unknown |
| `./knowledge-graph evidence <returned-claim-id>` | 1 matching attributed claim |
| `./knowledge-graph explain-field workstation.demos` | Unknown; 0 admitted matches, not an assertion that the field is unused |
| `./knowledge-graph find aws_ecr_repository --limit 5` | Evidence found; explicitly truncated |
| `./knowledge-graph impact src/terraform/registry/aws/main.tf --limit 5` | Potential structural evidence; explicitly truncated |
| Second independent `./knowledge-graph index` | Same snapshot ID, identical normalized claim JSON and identical derived multigraph checksum |

Repeated graph building therefore preserved the semantic snapshot, claim
identities and projection bytes in this pilot. RDF serialization order and the
outer generation ID are not promised to be identical. Observed index time was
about 3.4 seconds and these CLI queries about 0.05–0.07 seconds on this host;
these single-run observations establish neither a speedup nor token savings.

The detailed local execution output was generated at
`/tmp/isaacautomator-graph-acceptance.json`; temporary evidence is not a durable
artifact or a dependency of the application. Reproduce using the commands above
and the test suite rather than treating this document as a current run result.

## Review findings corrected during integration

Separate independent re-reviews approved the freshness/revocation fixes (16
focused tests plus a raw-source-free cache probe) and identity fixes (18 focused
tests plus five additional synthetic collision probes). These are bounded code
reviews, not a claim of comprehensive security certification.

- Worker file-backed stdout was rejected by the sandbox. Parent orchestration
  now uses bounded nonblocking pipes; confinement was not weakened.
- Cached manifests intentionally omit full source text. Metadata-only freshness
  validation now checks canonical manifest/coverage identity and current
  admission instead of incorrectly requiring persisted source text.
- Current policy is reread at freshness boundaries so revocation during indexing,
  traversal or validation withholds publication/results.
- Source exclusions are retained in published coverage without disclosing
  protected names, source contents or individual source hashes.
- Typed path identities distinguish literal dotted/bracket/slash keys from
  nested mappings, sequence indices and Python attributes/lookup operations.
  Complete source spans preserve nested lookup occurrences sharing a start
  position. Regression tests retain distinct assertions through RDF round-trip
  and multigraph projection rather than silently deduplicating them.

## Remaining gates

Precise profile/CLI/Python-to-Ansible transport, role metadata dependencies,
reviewed-document/history/runtime evidence import and comparative question-level
retrieval evaluation are not implemented/accepted yet. Native RDF 1.2, MCP and
Neo4j remain optional future gates. No agent settings, infrastructure, registry,
model downloads or deployment lifecycle were changed. No commit or push was
performed.
