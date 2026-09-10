# Optional Isaac Automator evidence graph

This is the first **offline structural MVP**, not the entire [implementation
roadmap](../../.agents/references/plans/isaacautomator-evidence-graph-plan.md).
It indexes explicitly selected public source files, represents independently
attributed claims in RDF with PROV-O, validates them with local SHACL shapes, and
builds a derived NetworkX MultiDiGraph. It never provisions infrastructure.

## Install separately

Linux x86_64/aarch64, Python **3.12**, Landlock ABI >=3, and `libseccomp.so.2` are
required for indexing and validation. Unsupported confinement fails closed;
there is no unsandboxed fallback. The deployment image/runtime is unchanged.

From the repository root, with `uv` installed:

```sh
uv venv --python 3.12 "$HOME/.cache/isaacautomator-graph/venv"
uv pip sync --python "$HOME/.cache/isaacautomator-graph/venv/bin/python" \
  --require-hashes requirements-knowledge-graph.lock
```

Installation may download Python/packages. Indexing and querying do not use the
network, an LLM, embeddings, Docker, cloud credentials, or Neo4j. Override
`ISAAC_GRAPH_PYTHON` to select another explicitly prepared graph interpreter.
No Hermes/MCP configuration is changed automatically.

See [the local verification record](ACCEPTANCE.md) for executed checks, the
public-repository pilot results and the remaining acceptance gates.

## Use

```sh
./knowledge-graph index
./knowledge-graph status
./knowledge-graph validate
./knowledge-graph explain-field container_registry --limit 10
./knowledge-graph explain-field workstation.demos
./knowledge-graph find aws_ecr_repository
./knowledge-graph trace container_registry --depth 2
./knowledge-graph impact src/terraform/registry/aws/main.tf
# Use a claim_id from a result, not a source URL:
./knowledge-graph evidence 'urn:ia:claim:...'
```

All commands emit JSON. Query results contain claim source paths/line ranges,
fingerprints, evidence kind, conditions, assessment, snapshot and generation
IDs. `explain-field` matches an exact dotted field label; `find` is a bounded
literal substring search. `trace` is bounded, bidirectional structural traversal,
not an execution trace. `impact` returns potential structural relationships,
not an exhaustive change impact report. Only supported unconditional claims
are expanded; conditional, disputed and unreviewed evidence is not silently
promoted into an unconditional path. A lookup reference does not establish a
profile consumer or runtime behavior. `unknown` is intentional.

Options follow the command: `--repo PATH`, `--policy PATH`, `--cache PATH`.
The wrapper defaults to this repository. For another checkout, explicitly pass
`--repo`; it must have its own reviewed policy or use `--policy`.

Exit codes: **0** successful operation (including an honest unknown answer),
**2** unavailable/rejected/worker failure, **3** stale evidence withheld.
After source, policy or extractor changes, run `index` again. Historical source
snippets and stale-query bypasses are not exposed.

Default cache: `$HOME/.cache/isaacautomator-graph/data/<checkout-key>/`.
It is outside the repository, owner-only, and contains immutable generations
plus an atomic `current` pointer. It must not be a symlink or a shared directory.
The cache stores admitted source fingerprints and normalized evidence, **not
full source files**. Its integrity hashes detect accidental or partial edits;
they are not digital signatures or protection against a malicious same-UID
operator replacing the whole cache. RDF is canonical evidence; JSON records and
the multigraph are derived outputs, not independently editable knowledge bases.
The original source remains authoritative about implementation.

## Source admission and limitations

`configs/knowledge-graph/public.yaml` selects exact source paths, not directory
roots or globs. Adding a path is **not** permission to bypass exclusion:

- Private, hidden, credential/state/log/generated inventory/tfvars/backend files,
  links, special files and the existing Neo4j role are excluded before source
  opening. There is no home-directory discovery or private-profile indexing.
- Sources are opened with checked nofollow descriptors, checked for races and
  limits, then detached into an in-memory snapshot.
- Whole-file screening conservatively quarantines sensitive identifiers and
  suspicious content. Even benign mentions such as `password`, `secret`, or
  `token` can withhold a legitimate source module/profile. Protected names,
  content and their individual hashes are not published. This heuristic is not
  proof arbitrary secrets cannot exist: policies must select reviewed public
  files. Do not expand the policy to personal configuration.
- Coverage exposes exclusions as `withheld` and records unsupported/unresolved
  constructs. `scanned` means a parser subset ran, **not complete analysis**.
  Multiple coverage entries may refer to one source.
- Policy and current permitted source fingerprints are rechecked before results
  are released. Freshness is point-in-time, not a filesystem lock or a promise
  that a later deployment sees identical bytes.

The existing public profile and Python deployment glue can be quarantined due
to sensitive identifier mentions. Therefore this MVP does **not** establish the
complete `workstation.demos` or registry profile-to-Ansible path. An absent path
must not be reported as "unused", "unsupported", or "safe to remove".

## Supported extraction

| Source | Extracted evidence | Important gaps |
| --- | --- | --- |
| Python | AST symbols, literal `.get`/subscription field references | No target imports, type/alias/call/dataflow evaluation or CLI decorator wiring |
| Profile YAML | Nested/indexed field declarations and actual key line numbers | Values omitted; no profile inheritance/resolution |
| Inventory template | Simple field placeholders and syntactic transport | No formatting or resultant inventory evaluation |
| Terraform | Scoped declarations, simple references, admitted local modules, child-variable input links | No provider/value/instance expansion, remote module reads or lifecycle verification |
| Ansible | Distinct plays/tasks/roles/handlers, conditions/tags, scoped notify/listen links | No execution, role metadata dependency/variable precedence analysis, include traversal or templating |

Dynamic and missing relationships remain unresolved. Task definitions are not
executions; declarations are not running cloud resources; structural support is
not a passing test. Native RDF 1.2/RDF-star, test-run/live-observation import,
document/history ingestion, semantic retrieval, MCP and Neo4j remain deferred.

## Isolation and resource limits

The parent owns admission, current-policy checks and atomic publication. Its
fresh single-threaded worker receives only the admitted JSON snapshot over
pipes, with a minimal environment and closed inherited descriptors. After
trusted implementation/dependency imports, Landlock grants read access only to
the graph package and prepared Python runtime; default-deny seccomp blocks
network, execution, process creation and filesystem mutation. It does not mount
or grant the whole repository, home, credential directories or Docker socket.

Bounds include 1 MiB/source, 16 MiB staged input, 4,096 selected files; worker
32 MiB protocol input/output, 40 CPU seconds, 90 wall-clock seconds, 1 GiB virtual
memory; query depth <=6, results <=100, 500 traversal nodes, 2,000 inspected claim
edges, five-second traversal budget and 50 KiB final response. Truncation is
explicit. YAML aliases/tags/duplicate keys and excess nesting fail closed.
Pinned local SHACL Core runs without imports, inference, rules, JS or advanced
execution. These defenses do not claim kernel-exploit/covert-channel resistance;
trusted runtime/package directories must remain under operator control.

## Why not install iaclens?

The evaluated raw parser source at iaclens commit
`69c43b7368a2e14d8e3709373d702dfdf1fff945` did not meet this MVP's memory-only input,
per-occurrence identity or condition/source-locator contracts. Same-host plays
and individual tasks can disappear before raw output; raw parsers also perform
filesystem reads. Wrapping their graph builder cannot restore lost assertions.
The inspection was source/API evaluation, **not** a successful upstream runtime
benchmark. This implementation uses Python AST, PyYAML nodes and a pinned
`python-hcl2` grammar directly; no upstream code was copied and no transitive MCP
server dependency was introduced. Broader parser reuse remains a future gate.

## Tests and maintenance

```sh
"$HOME/.cache/isaacautomator-graph/venv/bin/python" -m unittest discover \
  -s src/tests/knowledge_graph -p 'test_*.py' -v
# Existing deployment unit tests, using their existing environment:
PYTHONPATH="$PWD" sh src/tests/run_all.sh
# Optional lint tool, separate from graph runtime:
uvx --from ruff==0.13.1 ruff check src/knowledge_graph src/tests/knowledge_graph
```

Graph tests are deliberately separate from the default deployment test runner.
They include real kernel confinement and full sandboxed index/query/validation,
not just mocked parser outputs. Unsupported Linux confinement prevents the
end-to-end tests from passing; it is not silently downgraded to an unsafe run.
RDFLib 7.6.0 currently emits upstream TriG deprecation warnings in library tests.

Rebuild all outputs after changing extractors or shapes. Update the input pins
and regenerate the hashed lock only after compatibility tests. To stop using the
graph, simply stop invoking the CLI; it runs no daemon and deployment remains
unaffected. Remove only its explicitly identified external cache/environment if
cleanup is desired. Nothing needs changing on cloud workstations.

The remaining roadmap gates include precise profile/CLI/Python transport,
Ansible role dependencies, safe reviewed-document/runtime evidence import,
comparative retrieval evaluation, and optional service integration. The current
MVP is not evidence of faster retrieval, saved tokens, deployment parity or live
cloud/GPU verification.
