# IsaacAutomator Evidence and Dependency Graph Implementation Plan

**Status:** Implementation started: an optional offline structural MVP is present. The full first-release acceptance criteria below are not yet met; see [`src/knowledge_graph/README.md`](../../../src/knowledge_graph/README.md) for supported behavior and remaining gates.
**Prepared:** 2026-09-09.
**Repository inspected:** `devcontainer`, commit `419d0ef`; working tree was clean before this document.
**Goal:** Give the agent a source-grounded, optional knowledge service that explains Automator capabilities, traces infrastructure dependencies, identifies evidence gaps, and supports safer engineering decisions.
**Architecture:** Static, allowlisted extraction produces independently attributable Claims. A small Automator vocabulary, PROV-O, and SHACL govern a canonical RDF evidence dataset. A one-way, rebuildable labeled-property-graph projection supports bounded, read-only retrieval. Deployment remains independent.
**Proposed stack:** Python in an isolated optional environment; RDFLib and pySHACL for portable RDF 1.1 evidence; NetworkX `MultiDiGraph` for the initial LPG; native RDF 1.2 serialization and Neo4j only behind separate acceptance gates.
**Execution:** The user authorized implementation and subsequently explicitly requested a dedicated custom Neo4j container integrated with the devcontainer through Docker Compose. That request authorizes the local development service and its image/configuration, not cloud deployment, changes to existing editor/agent settings, commits or pushes. Use test-first implementation and independent specification/security review for each milestone.

## Approved milestone: dedicated development Neo4j (2026-09-10)

**Follow-up delivered:** Explicit developer projection import and the advisory
agent skill are now implemented and verified. See the
[usage guide](../docs/evidence-graph-agent-guide.md) and
[skill implementation plan](evidence-graph-agent-skill-plan.md).
Live readback conserved 226 claims, 190 entity/literal nodes and 177 supported
edges. This advances the projection milestone only: Neo4j agent mediation,
continuous privacy revocation and full Graph-RAG evaluation remain gated.

Deliver a separate **IsaacAutomator** Neo4j service, not the existing
`neo4j-arena` workstation container. Add a narrow-context custom Dockerfile under
`.devcontainer/neo4j/` and a Compose devcontainer definition. Preserve the existing
app Dockerfile, features, editor customizations, credential mounts and lifecycle
hooks; add only service wiring and workspace mounts. Do not rebuild/replace the
active editor container during implementation. Build and start only the new DB
and its fixed TCP gateway, then validate the complete Compose configuration. An editor rebuild is
a separate user action to attach the workspace container to the new network.

Architecture decision:
- Neo4j **5.26.30 Community**, pinned to the verified multi-platform official image
  digest `sha256:22ec5cd05a8cbb372fc4bed5e384c30bc75fd92504c72be4462039761b105f61`.
  The official image reports version 5.26.30. Community uses GPLv3; no Enterprise
  license or license-acceptance environment flag is introduced.
- Service `automator-neo4j`, independently scoped named data/log/auth volumes,
  no Arena mounts or shared data. Named volumes survive service recreation and
  ordinary Compose down; explicit volume removal is destructive and never part
  of normal stop/rebuild. Credentials and matching database state must be backed
  up/restored together while stopped; no automatic upgrades or rotation.
- Generate a strong per-installation credential inside the service's private
  named volume. No hardcoded/default password, source `.env`, password in Compose
  interpolation, image layer, command arguments, or diagnostic output. Bootstrap
  fails closed on unsafe or missing credentials for initialized database data.
- Run unprivileged, drop capabilities, disable privilege escalation and optional
  plugins/APOC, constrain import behavior and bound memory/process/log resources.
  An internal Docker network isolates the database from internet egress and from
  unrelated default networks. No repository, Docker socket or cloud credentials
  mounted into Neo4j. The app retains its normal development egress separately.
- Docker 29 runtime testing established that an internal-only endpoint does not
  publish ports. Keep database egress blocked; add `neo4j-gateway`, a non-root,
  read-only, capability-free HAProxy service with no mounts or credentials. It
  joins graph and ingress networks and only forwards the two fixed TCP backends.
  Pin its official 3.2-alpine base to
  `sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e`.
  Bake its config with `Dockerfile.gateway`; do not add host bind-mount dependencies.
- Publish HTTP/Bolt only on host **127.0.0.1:17474 / 127.0.0.1:17687** (configurable
  port numbers), avoiding Arena's 7475/7688. Inside Compose use
  `automator-neo4j:7474/7687`. Host loopback refers to the Docker daemon host,
  not this running container. Remote access requires a tunnel or a separate TLS
  design, never changing bindings to all interfaces casually.
- Readiness requires an **authenticated Cypher transaction**, not merely an open
  port. Configure restart policy and a bounded health check; verify authentication
  failure, a real read/write transaction and persistence across recreation.

Authorization boundary: this milestone is a **trusted-developer database**, not
an agent-accessible retrieval service. Community Edition does not provide the
planned granular reader/writer role isolation. Do not invent a restricted reader,
share its administrative credential with agents, install MCP, or route the bounded
graph CLI to it. The canonical RDF/NetworkX graph continues to work independently.
Freshness-aware projection publishing, read-only retrieval mediation and the
effective-privilege tests in section 8 remain separate acceptance gates before
using Neo4j as an evidence-query backend. A healthy empty database does not mean
the existing evidence graph was ingested.

Required verification: config/unit regression tests; image build; isolated
Compose smoke test; denied unauthenticated access; authenticated transaction;
volume persistence; no plaintext credentials in rendered config/image/container
metadata; non-root identity, private port bindings and network attachments;
independent review. Leave the old Arena container and existing deployment runtime
untouched. Preserve the new dev service after verification because the user asked
for it as part of the development environment, and document how to stop it.

Implementation status: custom images and Compose wiring are implemented. The
isolated real-Docker smoke passed authentication, read/write, persistence after
container recreation, host-loopback HTTP, non-root/mount/network checks, file-import
denial and an internet-denial probe. The actual development database and gateway
are running healthy; host Bolt negotiated protocol 5.4. The full graph suite
passed 97 tests and existing deployment tests passed. The editor container was
not rebuilt. Detailed commands, caveats and review outcome are recorded in
[Neo4j acceptance](../../../.devcontainer/neo4j/ACCEPTANCE.md).

Version/edition references checked for this milestone:
- https://hub.docker.com/v2/repositories/library/neo4j/tags/5.26.30-community
- https://hub.docker.com/v2/repositories/library/haproxy/tags/3.2-alpine
- https://raw.githubusercontent.com/neo4j/docker-neo4j/master/docker-image-src/5/coredb/docker-entrypoint.sh
- https://raw.githubusercontent.com/neo4j/docs-operations/5.x/modules/ROOT/pages/authentication-authorization/index.adoc

## 1. Scope and success criteria

### Approved follow-up: load existing evidence for visual exploration

The user explicitly selected loading the existing evidence into the dedicated
Neo4j development database. Implement an explicit `knowledge-graph neo4j-load`
operation, not automatic indexing or arbitrary Cypher retrieval. Export the
validated canonical dataset in the confined worker; preserve typed terms, every
claim occurrence, conditions and complete provenance. Recheck current source
policy before and after transfer. Parameterized fixed queries atomically replace
only importer-owned records for this repository scope; retain unrelated data.
Generation-guarded cleanup handles detected policy changes during import.

Store an explicit historical snapshot marker, not an indefinitely current claim.
Document that later policy/source changes require reload or explicit removal;
this trusted developer database does not enforce continuous privacy revocation.
Do not send credentials into the host CLI or expose an unrestricted agent reader.
Verify actual Neo4j claim IDs/hashes, term counts and parallel relationships against
the export, repeat-load idempotence, unrelated-data preservation and visual Cypher
examples. Keep the canonical RDF independent. Full Graph-RAG evaluation and the
separate bounded retrieval/security gates remain pending.

The graph describes software and infrastructure relationships; it is neither an orchestration engine nor a replacement for complete profiles, tests, or live verification.

Primary vertical slice:

`Profile field → loader/normalizer → CLI/Python parameter → Terraform or Ansible consumer → supporting verification evidence`

A successful answer identifies the supported path, relevant conditions, exact source locations, snapshot, verification scope, and the point at which evidence stops. It must not invent missing links.

The first release must:

- Explain selected registry/security/Hugging Face profile paths and distinguish unsupported or partially wired workstation fields.
- Distinguish cloud-specific behavior, separate registry ownership, and conditional provisioning paths.
- Preserve desired, documented, statically implemented, test-defined, test-executed, and observed information separately.
- Answer unknown, disputed, stale, and truncated honestly; these states may coexist.
- Operate without Neo4j, embeddings, remote LLM calls, live cloud credentials, or a running workstation.
- Leave ordinary deployment behavior unchanged when the graph is absent, corrupt, or unavailable.

Out of scope for the initial release: fixing profile wiring, executing Ansible/Terraform during indexing, autonomous remediation, remote graph hosting, Arena episode/scene ingestion, model downloads, production cloud acceptance, and arbitrary natural-language-to-Cypher/SPARQL execution.

## 2. Research-backed decisions

External findings below are source/metadata inspections, not reproduced project benchmarks or tested dependency locks. Repository findings refer to the inspected revision and must be rechecked before implementation.

### 2.1 Reuse extraction, not an upstream graph as authority

| Candidate | Inspected commit | Decision |
|---|---|---|
| `ScrimReaper/iaclens` | `69c43b7368a2e14d8e3709373d702dfdf1fff945` | First parser-adapter pilot; Apache-2.0 license file.[7] |
| `vparab7/infra-graph` | `f4caf2b316cbf6252806ee6bdeddc71d7ea016cc` | Comparison baseline; Apache-2.0 license file.[13] |
| `onecommons/unfurl` | `65b47ce0551c5e7fe8153f6b3d46bcb4f75b2949` | Study topology/execution lineage only; MIT license file.[16] |

Important selection constraints:

- iaclens exposes Terraform module input/output references and richer Ansible role/handler/variable-file structure than the inspected upstream parser.[9][10][15]
- Its builder deduplicates assertions and inserts into `DiGraph`; distinct relationships between the same endpoints can overwrite each other. Consume raw parser output before builder deduplication; use independent Claim IDs and a `MultiDiGraph` projection.[12][25]
- Its identifiers are not globally repository/environment-qualified; same-name roles and same-host plays can collide. Automator must supply identity before merging, not simply prefix an already-collapsed graph.[10][11]
- References may point to unparsed or nonexistent targets. `EXTRACTED` and numeric confidence do not establish target existence, execution, or truth.[9][12]
- The Ansible parser does not model every individual task, and its include/role edges do not preserve the full task condition semantics. Role-scoped handler resolution and simplified inventory matching are not a complete Ansible execution model.[10]
- Terraform `count`, `for_each`, dynamic references, and remote modules require explicit coverage limits; graph node counts are not provisioned instance counts.[9]
- Do not expose upstream graph-build/update tools through our read-only MCP service. The upstream MCP tool module includes a mutating build operation.[21]
- Both graph projects use the `infra_graph` Python namespace: compare them in separate environments.[8][14]
- Unfurl invokes Terraform/Ansible as an orchestrator; it is not a read-only extraction plugin. Do not introduce a second deployment engine.[17][19][20]
- Review Unfurl's separate package/dependency manifest if a future exported-evidence adapter is proposed; it is not part of the initial graph runtime.[18]
- Review exact distributed licenses, transitive dependencies, notices, and upstream maintenance before adopting code. A permissive top-level license is not a transitive-license clearance.

Adoption options, in order: pinned parser dependency behind our adapter; narrowly maintained extraction fork if indispensable semantics are inaccessible; own minimal parser only for failed pilot requirements. Record the decision and attribution; do not copy the entire upstream application by default.

### 2.2 Ontology and representation

PROV-O supplies provenance entities, activities, agents, and qualified relationships; it does not define Automator components or prove that a claim is true.[1]

Use a small versioned Automator vocabulary with PROV-O and SHACL. SHACL validates the supplied graph against constraints; it does not establish deployment correctness or closed-world completeness.[2]

Refinement of the original RDF-star idea:

- Canonical baseline: RDF 1.1 explicit Claim entities with subject/predicate/object and provenance.
- Native RDF 1.2: optional serialization adapter after end-to-end compatibility tests.
- Current inspected RDF 1.2 Concepts is a Candidate Recommendation Snapshot dated 2026-04-07; triple terms occur in object position and reifiers can identify assertions about their propositions.[3]
- Current inspected RDF 1.2 Turtle is a Working Draft dated 2026-09-03. Its reification/annotation syntax must not be treated as interchangeable with legacy RDF-star syntax; annotation shortcuts can assert the underlying triple.[4]
- Do not assume RDFLib + pySHACL + a chosen database support identical statement-annotation semantics merely because each supports RDF. Keep disputed/unasserted claims portable.
- Defer P-Plan. Its plan/execution correspondence is relevant, but its documentation displays CC BY-NC-SA 2.0 licensing; review the specific artifact before incorporation. This is not a claim that referencing its IRIs is prohibited.[6]

### 2.3 Runtime selection gate

Metadata-compatible candidates are RDFLib 7.6.0, pySHACL 0.40.1, and NetworkX 3.6.1—not an accepted lockfile.[22][23][24]

The inspected shell uses Python 3.10.12; NetworkX 3.6.1 requires Python >=3.11. Therefore choose an explicitly approved isolated Python 3.11/3.12 environment, or evaluate a compatible older NetworkX version. Do not upgrade the deployment runtime to satisfy graph dependencies. Resolve and test the complete lock, including parser/YAML/HCL dependencies and license notices, in Task 1. Neo4j dependencies remain a separate optional extra; MCP server activation is always optional.

The pinned iaclens package declares `mcp>=1.0`, Click and watchdog as mandatory dependencies, even if only parser modules are imported.[8] Task 1 must choose either a reviewed parser-only distribution/fork with its own complete lock, or the unmodified package with its transitive MCP installation explicitly disclosed. Never promise that MCP is absent from the environment when installing the unmodified package. A transitive library installation does not authorize launching or registering an MCP server.

## 3. Repository integration map

These are existing source anchors, not files to modify automatically.

| Existing source | What to extract or characterize |
|---|---|
| `src/python/config.py:217-318` | Profile lookup/normalization. Public and home-profile search are mixed; ingestion must not call discovery. Selected fields are normalized; other YAML remains `raw`. |
| `src/python/registry_profile.py:137-157` | New/legacy registry normalization and saved-state consistency checks. |
| `src/python/huggingface_profile.py` and `src/ansible/roles/huggingface-artifacts/files/huggingface_contract.py` | Shared Hugging Face contract; inspect source without dynamic imports. |
| `src/python/deployer.py:195-255` | `resolve_security_profile`: actual precedence and normalized parameter consumers. |
| `src/python/deploy_command.py:481-507` | CLI security names differ from `enable_*` consumers. Treat as a suspected wiring gap requiring offline characterization, not a proven working override. |
| `src/python/deployer.py:399-652` | `create_tfvars`, serialization, `create_ansible_inventory`; values and serialized representations differ. |
| `src/ansible/inventory.template:4-31` | Actual inventory transport, not all fields in raw profiles. |
| `src/python/deployer.py:278-302` | Metadata schema/resolved inputs; do not ingest real metadata artifacts. |
| `src/python/deployer.py:654-693` | Backend initialization and automatic bucket naming, not automatic bucket creation. |
| `deploy-aws`, `deploy-gcp`, `deploy-azure`, `deploy-alicloud` | Cloud-specific parameter transformations and selected Terraform roots; AST/text only. |
| `src/terraform/{aws,gcp,azure,alicloud}/main.tf` | Root/module ownership and actual variable forwarding per provider. |
| `src/terraform/gcp/ovkit/main.tf` | GCP scheduling, image, security and VM consumers. |
| `src/terraform/registry/{gcp,aws}/main.tf` | Registry ownership in separate stacks; consuming IAM is not repository ownership. |
| `src/terraform/bootstrap/gcp/main.tf` | Explicit state-bucket provisioning separate from workstation deployment. |
| `src/ansible/isaac-workstation.yaml` and `src/ansible/roles/isaac-workstation/meta/main.yml` | Entry play, ordered role dependencies, tags, defaults and conditions. |
| `src/ansible/roles/{neo4j,gr00t,remote-desktop,state-ledger}/` | Service definitions, conditional paths and verification-producing code—not proof of running services. |
| `src/packer/{aws,gcp,azure}/isaac-workstation.pkr.hcl` | Image-build playbook/skip-tags path, distinct from image selection and post-image configuration. |
| `isaac-installer/lib/core/config.sh` | Separate native profile schema and selective consumers; never source/eval this loader for ingestion. |
| `configs/PRIVATE_PROFILES.md:55-78` | Explicit cloud/local parity and historical-privacy boundaries. |
| `src/tests/run_all.sh` | Existing runner invokes top-level `*.test.py`; it will not discover new nested graph tests. |

Critical safety facts from source inspection:

- Deployment CLI construction can probe public IP; GCP module-level setup can invoke `gcloud`; Git-ref resolution can contact remotes. Do not import CLI modules or invoke `--help` during extraction.
- `--dry-run` is not an inspection sandbox: paths can write state/metadata and perform cloud setup before reaching dry-run handling. Do not use it for this project’s graph acceptance.
- Shared tfvars do not establish equal support on every provider. Preserve exact module forwarding and provider scope.
- The existing workstation Neo4j role is not an evidence-graph service. Inspection found unsafe default credential handling, broad port publication, and ignored service-start errors. Do not copy credential literals into the graph or reuse that service automatically.
- `.gitignore` and `.dockerignore` match `__*`. Initial implementation should use namespace packages and `python3 -m src.knowledge_graph.cli`, avoiding ignored `__init__.py`/`__main__.py`, or separately review narrow exceptions. Never rely on ignored local initializers.

## 4. Architecture and ownership

```text
Reviewed source policy + approved repository snapshot
                      |
       safe staging, sanitization, content manifest
                      |
       static adapters + explicit coverage records
                      |
          normalized Claim occurrence records
                      |
        canonical RDF dataset + PROV-O lineage
                      |
         SHACL + application acceptance policy
                      |
              atomic validated publication
                      |
       derived MultiDiGraph + lexical search index
                      |
       bounded read-only CLI / optional stdio MCP
                      |
       agent checks citations and explains limits
```

There is one write direction. Original code, documents, and execution artifacts remain the source evidence; canonical RDF is authoritative only for the accepted knowledge representation. LPG/search indexes are disposable projections, never independently edited authorities.

Normalized records are ingestion envelopes, not a second mutable database. Retain their versions/digests for audit. Use RDF datasets/named graphs for source/run organization; a graph name alone is not provenance or authorization.

Initial storage is local, outside the repository and Docker build context, under an explicitly configured owner-only cache directory. Store manifests, validated RDF, projection JSON, and sanitized lexical documents separately. No pickle or untrusted executable serialization. Do not add a triple-store server merely to store a small pilot corpus.

Separate processes/capabilities:

- **Indexer:** approved local maintenance command; reads only staged inputs; writes new snapshot artifacts.
- **Validator/projector:** trusted schemas and bounded sandbox; publishes only complete validated output.
- **Retriever:** read-only evidence mount and bounded disposable cache; cannot rebuild, install, deploy, or write canonical evidence.
- **Source-admission/freshness component:** narrowly scoped local capability reusing Task 2's pre-open policy, checked-descriptor staging and sanitization. Only this component can compare approved current-source fingerprints and supply sanitized excerpts. It accepts admitted source IDs, not arbitrary paths, and returns policy/snapshot-bound results. The retriever never receives unrestricted repository access. If this capability is unavailable, freshness is unknown and only authorized snapshot-qualified evidence may be returned.
- **Optional observation importer:** accepts explicitly supplied sanitized evidence envelopes; does not connect to clouds or inspect a workstation automatically.

## 5. Evidence and ontology contract

### 5.1 Entity categories

Define proposed terms in a versioned Automator namespace; do not mint domain classes inside `prov:`.

- Logical declarations: ProfileField, CLIOption, PythonSymbol, TerraformModuleDefinition, ModuleCall, TerraformVariable, ResourceDeclaration, AnsibleRole, TaskDefinition, HandlerDefinition, ServiceDefinition, TestDefinition.
- Immutable artifacts: SourceSnapshot, ProfileVersion, ResolvedConfiguration, ImageArtifact, ModelRevision, PlanArtifact, TestReport, ObservationReport, DecisionRecord.
- Runtime identities: DeploymentInstance, ResourceInstance, ServiceInstance; only introduced with evidence identifying the actual instance.
- Evidence: Claim, SourceLocator, ExtractionCoverage, ReviewAssessment, ValidationReport, ProjectionManifest.
- Activities: ExtractionRun, ConfigurationResolution, VerificationRun, ProvisioningRun, InspectionRun, ProjectionRun. Use `prov:Activity` where appropriate.
- Agents: extractor software, runner, human reviewer, AI assistant; separate assertion author from extracting software. Unknown author remains unknown.

A declaration is not an instance. A test definition is not a test run. A plan artifact is not an execution. An image tag is not a content digest. A model branch is not an immutable revision. GPU/model compatibility requires supporting tests or observations, not a graph-level assumption.

### 5.2 Claim occurrence versus proposition

Each immutable Claim has exactly one subject, predicate and object; use portable `rdf:subject`, `rdf:predicate`, `rdf:object` properties. Predicate is an IRI; subject is an application-assigned stable IRI; object is an IRI or explicitly typed/language-tagged literal. Avoid blank nodes for durable application identities.

Required envelope:

| Field | Contract |
|---|---|
| `claim_id` | Identifies one independently attributable assertion occurrence, not just an S/P/O tuple. |
| `proposition_key` | Deterministic grouping of normalized terms; scope compared separately. Never merges assertion provenance. |
| `evidence_kind` | desired, documented, static_implementation, test_definition, test_execution, observation, or historical_report. Not a truth ranking. |
| `scope` | Repository, cloud, execution path, applicable input context and versions; explicit unknown values. |
| `conditions` | Explicit state: `unconditional`, `expression`, or `unresolved`; original expression and normalized representation when recoverable; true/false/unknown evaluation tied to a context. Missing extraction is `unresolved`, never `unconditional`. Never evaluate arbitrary code. |
| `source_locator` | Snapshot, relative path, semantic anchor, exact approved range and content fingerprint. |
| `extraction` | Activity ID, method, extractor code/version/config digest, recorded time. |
| `attribution` | Known source actor and extracting agent separately. |
| `assessment` | Separate immutable review/policy assessment with supported/disputed/rejected/unreviewed disposition and rationale. |
| `verification_link` | For executed/observed evidence: run, result, target/input context, source revision and mock/skip/failure details. |

Extraction does not assert the base `S P O` into trusted facts. Independent sources with identical propositions remain independent claims. A parser's confidence value is retained as parser metadata, never translated into runtime verification.

Assessment changes create new assessment records; they do not rewrite immutable claims. “Accepted” means accepted for a stated query/policy purpose, not universally true. Failed and skipped tests remain test-execution evidence without becoming positive verification.

### 5.3 Identity and freshness

- Repository identity is explicitly assigned and stable; do not infer it from a personal remote URL.
- Logical declaration identity includes repository, language, relative module/role root, semantic symbol and necessary disambiguator. Same-host plays and same-name roles must remain distinct.
- Module definitions and call sites/instances are separate, including repeated use of the same local module.
- Snapshot identity includes admitted content manifest digest and schema/policy versions; record HEAD when available. HEAD or a dirty boolean alone is insufficient.
- Include explicitly admitted untracked content in the manifest; never crawl untracked files by default.
- Semantic anchors survive line movement when identity is unambiguous. Renames are explicit mappings, not automatic fuzzy equivalence.
- Canonical term hashing preserves literal lexical form, datatype, language, Unicode and escaping. Publish a versioned deterministic encoding; do not hash ad hoc string concatenations.
- Re-importing the same envelope is idempotent; a new extraction activity creates attributable occurrences rather than erasing prior provenance. Deduplicate storage separately from assertion identity.
- Separate extracted/recorded/observed time from applicability. No blanket TTL makes cloud observations safe for future operational action.

### 5.4 Relationship semantics

| Proposed predicate | Meaning and restriction |
|---|---|
| `consumed_by` | Field/value read or interpreted by a supported static path; a text mention alone is insufficient. |
| `passed_to` | Value transferred across an interface; preserve transformation, type and conditions. |
| `declares` / `instantiates` | Keep code declaration and evidence of runtime instance creation separate. |
| `provisions` | Qualified provisioning responsibility; declaration-level capability is distinct from an executed result. |
| `requires` | Scoped prerequisite; not automatically temporal execution order or `prov:wasDerivedFrom`. |
| `notifies` | Ansible notification reference, with separate target-resolution evidence. Not proof a handler ran. |
| `verified_by` | A specific claim supported by a particular qualifying result under matching inputs/scope. |
| `contradicts` | Evidenced incompatible claims with overlapping applicability; differing clouds are not inherently contradictions. |
| `supersedes` | Explicit replacement assessment, never just a later timestamp. |

Use a small registered predicate set with domain/range rules. Allow unresolved reference entities without pretending they are resolved definitions. Separate dataflow, control dependencies, ownership and execution order.

Qualified PROV directions must follow the specification: activity → qualified usage → input entity; report entity → qualified generation → activity; activity → qualified association → agent/plan. Attach `prov:hadPlan` through the appropriate association. Provenance lineage is not proof of success.[1]

### 5.5 Coverage, conflicts and SHACL

Coverage records identify attempted/scanned/excluded/failed/unsupported files or semantic regions, adapter version, supported language subset, dynamic unresolved expressions and truncation. Counts must be derived from records, not guessed. Protected exclusions must not leak filenames to unauthorized clients.

“No consumer found in these covered paths” is valid. “This field is unused everywhere” requires an explicit scoped completeness contract and supporting review/characterization tests. `sh:closed` does not establish repository completeness.

SHACL validates cardinality, term types, allowed values, source/extraction linkage, and required execution/observation context. Application checks validate stable IDs, safe locators, scope compatibility, acceptance policy, coverage arithmetic and referential integrity. Record dataset/shapes digests, validator version/options and detailed safe diagnostics. No publication on nonconformance, malformed shapes, timeout or exception.

The validator receives an explicitly constructed RDF graph: the union of the candidate generation's admitted default graph and all claim, provenance, coverage and assessment named graphs listed in its manifest. Cross-graph provenance must be present in that union; do not rely on a library's implicit default-union setting. Reject unlisted graph contexts and missing required contexts before validation. Keep trusted shapes separate from data, validate their structure/configuration separately, and do not union arbitrary source-supplied shapes or schema assertions into the trusted shapes graph. Record the selected graph IDs and union digest in the validation manifest. An invalid Claim placed only in a named graph must fail publication; an unexpectedly empty selection must not pass vacuously.

Default validation: trusted local shapes, no remote imports, JavaScript, SHACL rules, or implicit inference. If a specific SHACL-SPARQL constraint becomes necessary, pin and test it under the same no-egress sandbox. pySHACL exposes optional import/advanced functionality; do not enable it indiscriminately.[5]

## 6. Extraction design

### 6.1 Admission before parsing

Start with an explicit source-file allowlist assembled from approved structural roots and synthetic fixtures. Initial candidate roots are `src/python`, root deployment scripts, `src/terraform`, `src/ansible`, and generic `configs/profiles`; admitting a root still requires file-type and content policy review.

Do not ingest `configs/private`, home profiles, `.env`, keys, credentials, live `state`, `results`, `uploads`, generated inventories/hosts/tfvars/backend overrides, `.terraform`, Git objects/history, installed third-party skills, dependency caches, raw logs, or personal operational records. Publicly tracked documents can still contain sensitive content; they are not automatically approved. Historical session documents and plans are opt-in reviewed sources, not a default recursive corpus.

No forbidden file may be opened or hashed. Reject path traversal, symlinks and out-of-root references; constrain hard-link aliases and link-swap races through checked file descriptors and controlled staging. Restrict the indexer's mounts to admitted snapshots, not the user's whole home/repository. Source literal redaction and output-schema checks occur before graph/cache/log persistence. Keep useful structural keys while dropping sensitive values; an approved excerpt must not expand into adjacent unapproved text.

### 6.2 Adapter contract

Adapters consume immutable sanitized snapshots and return declarations, reference occurrences, conditions, locators, diagnostics and coverage. They never receive credentials or resolve dependencies through network access. Results must pass the same privacy and schema checks as source ingestion.

- **Terraform:** local module calls, variables/outputs/resources, expressions, ownership, explicit dependencies. Record unresolved remote module source/revision without downloading it. Do not infer actual plan values/instances. Add a separate approved plan-artifact importer later.
- **Ansible:** role and task roots, ordered dependencies, individual task/source anchors, include/import differences, block/rescue/always, when/tags, variable references, notify/listen scope, templates and service definitions. Unresolved Jinja remains unresolved. Do not invoke Ansible or render templates.
- **Python/CLI/profile:** AST/string-literal extraction for field lookup, normalization, parameter assignment and template transport. Use reviewed declarative bridge rules for dynamic paths; label these as reviewed mappings, not automatic whole-program proof. Never import target code.
- **Test definitions:** identify definitions/assertions and their explicitly supported claim coverage; heuristic name matching produces candidates only.
- **Documents/decisions:** selected sanitized sources with source-attributed claims; LLM suggestions, if later approved, remain candidates until reviewed.
- **Packer/native installer:** initially record path/declaration references and coverage limits; detailed shell dataflow and runtime parity belong to a later milestone. Never source shell files.

## 7. Publication, projection and retrieval

### 7.1 Atomic datasets and rebuilds

Build a new immutable generation in a temporary private directory, validate it, compute manifest checksums, then atomically publish a pointer. A writer lock prevents competing publishers. Readers pin one generation per request. An incomplete build cannot replace the last validated snapshot.

For the pilot, rebuild all admitted cross-file relationships on source changes. Hashes can skip an unchanged rebuild, but do not independently reuse cross-file edges without validating their dependencies. Deletion, rename, policy/schema/extractor changes trigger appropriate invalidation. Incremental extraction is a later optimization requiring comparison against full rebuild.

Current-query freshness is checked through the source-admission/freshness component against the admitted manifest and all dependency sources relevant to the answer, not just one cited line. Bind the comparison and sanitized excerpts to one checked source generation; a concurrent change, policy revocation or denied read yields stale/unknown status and withholds mismatched excerpts. A failed rebuild leaves historical data available only as explicitly historical/authorized data; it must not silently remain “current.”

Current policy applies to old generations, caches, exports, cursors and excerpts. Revocation overrides immutable history. Quarantine/rebuild controlled artifacts; document that already distributed copies cannot be recalled automatically. Never rewrite Git history as graph cleanup.

### 7.2 LPG projection

Use a directed multigraph keyed by Claim ID for accepted relationships, with Claim nodes for disputed/unreviewed assertions and evidence navigation. Preserve original IRIs, literal lexical forms/datatype/language, scope, conditions, source snapshots, claim IDs and selection-policy version. Multiple predicates and multiple supporting occurrences must survive.

The projection may deliberately include only a subset of RDF; record that subset/coverage. Only explicitly established `unconditional` edges qualify for unconditional reachability. Expressions remain conditional, and unrecovered conditions remain `unresolved` even when an upstream parser emitted the edge. Rebuilds must be deterministic for the same dataset and policy. No reverse LPG-to-RDF edits.

### 7.3 Read-only API

Proposed operations—not existing commands:

- `graph_status`: generation, policy/schema/extractor versions, coverage and freshness.
- `explain_field`: known consumer chain and evidence gaps for an admitted profile field.
- `trace_dependency`: bounded upstream/downstream traversal with conditions.
- `find_evidence`: claim provenance, qualifying reports and conflicting assessments.
- `impact_analysis`: affected declarations/tests from an approved source diff.
- `find_decisions`: selected reviewed decisions, not unrestricted session-history search.

Each result envelope includes snapshot/policy IDs, scope, claim/evidence IDs, safe source locators, conditions, uncertainty, coverage, truncation and a statement of verification limits. Do not return arbitrary filesystem contents. Obtain fresh excerpt/fingerprint attestations from the source-admission/freshness component before returning current citations; reject or label historical/unknown on mismatch or component failure. Snapshot-mounted evidence alone cannot establish working-tree freshness.

Start with exact symbol/path search plus bounded lexical and graph retrieval. Semantic embeddings are an optional later benchmark, not a prerequisite. No remote embedding/LLM transmission by default.

Proposed initial server ceilings, to be measured and tuned: depth 6, 500 visited nodes, 2,000 inspected edges, 50 KiB response, 5-second query deadline, and 2 concurrent queries. Bound input length and index size separately. Clients may lower but never raise hard limits. Cancellation releases resources; output truncation is explicit. Pagination handles bind generation, policy and scope and are reauthorized on every request.

MCP is optional stdio and explicitly registered by the user only after release gates pass. No raw Cypher/SPARQL/SQL, shell, build/reindex, deployment commands, arbitrary regex, or URL fetch tools. Retrieved instructions and historical approvals are untrusted data, not authorization. Local servers inherit significant client capabilities unless constrained; use sandboxed least privilege.[28]

## 8. Privacy and security release gates

RDFLib can access indirect files/network resources; its security guidance recommends operating-system controls rather than relying on Python hooks alone.[26]

Required controls:

- No-egress sandbox for extraction, parsing and validation; read-only staged inputs; bounded CPU, memory, file size, recursion and runtime.
- Disable YAML object construction, XML external entities, Jinja evaluation, target Python imports, remote RDF contexts/imports, SPARQL `SERVICE`, arbitrary plugins and untrusted shapes.
- Fail closed when the required sandbox is unavailable. A synthetic-fixture development mode may exist but must be explicit and cannot index a real repository.
- Separate public and explicitly approved private stores, indexes, caches, logs and exports. Visibility labels alone are not an access-control boundary. Same-UID processes are not magically isolated from each other's files.
- No secret values, secret field digests, private source names or credential-bearing URLs in public evidence. Keep opaque IDs where necessary. Test all diagnostic and exception paths.
- No privacy claim based solely on `.gitignore`; optional artifacts must also stay outside Docker contexts and public backups.
- No external service installs, cloud probes, registry pulls, image builds, target verification, or agent settings changes during graph indexing or query.

The approved development-service milestone above supplies an independently managed local Neo4j service, not the disposable workstation database. Its trusted-developer Community Edition scope does not waive the following agent-backend acceptance gates. Remote/production service use still requires an ADR for edition/version/image digest/license, credentials delivery, private binding, TLS, volume ownership, readiness, restart/upgrade behavior, backup/restore and retention.

Separate projection writer and retriever identities. Verify effective privileges, including inherited `PUBLIC`; the inspected manual documents procedure/function execution and loading grants, so a role called `reader` alone is not sufficient evidence of least privilege.[27] Disable unnecessary APOC/plugins, restrict imports/egress, test writes/admin calls/other databases/URL loads with the actual reader identity, and ensure the selected edition can enforce the design. If not, defer Neo4j rather than give the agent admin credentials. No automatic reuse or hardening of the existing workstation role in the initial implementation.

## 9. Proposed files and implementation tasks

All files below are **proposed new files** unless explicitly labeled existing. None are implemented by this plan. Use namespace-package imports to avoid the repository's broad `__*` ignore patterns.

For every code task: add the named failing tests; run and record the failure; implement the smallest change; rerun targeted tests and applicable regressions; request independent review; retain actual commands/results. Do not claim a passing count before execution. Commits/pushes remain separately authorized.

### Task 1 — Isolated runtime and extractor decision

Create `requirements-knowledge-graph.in`, `requirements-knowledge-graph.lock`, `src/knowledge_graph/README.md`, `src/tests/run_knowledge_graph.sh`, and `src/tests/knowledge_graph/test_optional_boundary.py`.

1. Establish approved Python runtime and lock-generation process without changing the deployment image.
2. Compare pinned candidates in separate environments against synthetic role/module collision fixtures; never invoke their assistant-install commands.
3. Confirm raw parser outputs are available before identity loss/deduplication. If not, record minimal fork requirements before adoption.
   Decide the parser-only distribution versus disclosed transitive MCP dependency boundary; test the actual installed dependency graph, not just import statements.
4. Resolve artifact hashes/licenses and test imports from a clean checkout; record the selected pins and fallback.
5. Prove deployment source has no graph dependency and nested tests have an explicit runner.

Gate: reproducible isolated setup, no agent configuration edits, no graph dependencies added to existing `Dockerfile`, extractor choice justified by fixtures rather than popularity.

### Task 2 — Safe source policy and immutable snapshots

Create `configs/knowledge-graph/public.yaml`, `src/knowledge_graph/source_policy.py`, `snapshot.py`, `sandbox.py`, `src/tests/knowledge_graph/test_source_policy.py`, `test_snapshot.py`, `test_sandbox.py`, and synthetic fixtures under `src/tests/knowledge_graph/fixtures/`.

1. Define versioned allowlist, reviewed content policy and hard exclusions.
2. Test forbidden opens, path aliases/races, fake secret literals, source-size limits and no-egress behavior.
3. Implement controlled staging, safe locators, admitted manifest and stable repository/snapshot IDs.
4. Test dirty/untracked/renamed/deleted files and unknown formats without executing target code.
5. Expose the narrow source-ID-based freshness/excerpt capability; test denied reads, concurrent mutation and revoked source IDs without granting broad retriever access.

Gate: forbidden files never opened/hashed; fake secret markers absent from every output; production indexing refuses an unavailable sandbox.

### Task 3 — Claim model, vocabulary and validation

Create `src/knowledge_graph/model.py`, `identity.py`, `rdf_store.py`, `validation.py`, `schema/vocabulary.ttl`, `schema/shapes.ttl`; tests `test_claims.py`, `test_identity.py`, `test_validation.py`.

1. Write golden portable RDF fixtures covering duplicate propositions, independent occurrences and scoped conflicts.
2. Implement typed term encoding, PROV activity/agent linkage and separate assessments.
3. Add shapes and semantic checks with explicit validation configuration.
4. Test wrong PROV direction, missing locators/results, invalid terms and unasserted claims.
5. Test named-graph-only invalid Claims, empty/missing context selection and cross-graph provenance. Require explicit condition states; absence of recovered conditions is unresolved.

Gate: conventional RDF round-trip preserves all claims/types; no extracted base fact is asserted automatically; malformed or timed-out validation never publishes.

### Task 4 — Terraform raw-output adapter

Create `src/knowledge_graph/extractors/terraform.py`, `extractors/iaclens_adapter.py`, and `src/tests/knowledge_graph/test_terraform.py`.

1. Normalize raw declarations/references into Automator identity before merging.
2. Add local module-call input/output and ownership fixtures, repeated module instances and absent targets.
3. Preserve expressions/conditions; record unsupported remote modules/dynamic paths.
4. Add representative GCP, AWS and shared-registry source fixtures.

Gate: same resource names in different roots never merge; missing targets remain unresolved; no runtime instances appear without execution evidence.

### Task 5 — Ansible task-aware adapter

Create `src/knowledge_graph/extractors/ansible.py`, tests `test_ansible.py`, and source-only service/handler fixtures.

1. Add distinct task/play/role-root identities beyond upstream task-file links.
2. Retain meta order, includes/imports, when/tags, block/rescue/always and notify/listen resolution scope.
3. Preserve unresolved template expressions and distinguish service definition from execution.
4. Test same-host plays, same-name roles, dynamic include targets, conditional paths and ambiguous handlers.
5. Inject an adapter edge whose enclosing `when` could not be recovered; its condition must remain unresolved through validation and traversal.

Gate: file-level variable references cannot masquerade as field-level consumption; handler notification is not handler execution; no Ansible/Jinja commands run.

### Task 6 — Automator profile/CLI/Python bridge

Create `src/knowledge_graph/extractors/python_source.py`, `extractors/profile.py`, `schema/bridge_rules.yaml`, tests `test_profile_paths.py`, `test_cloud_scope.py`.

1. Trace admitted profile fields through actual normalizers/assignments and inventory/tfvars templates with AST/static rules.
2. Model actual precedence and transformations; do not assume intended CLI override behavior.
3. Add reviewed mappings only where static evidence supports them and attach rule/source provenance.
4. Characterize suspected security-option naming and profile-ingress gaps using isolated mocked tests outside the ingestion process; record gaps, do not fix deployment code under this task.
5. Trace `container_registry`, legacy `artifact_registry`, independent Hugging Face settings, automatic state-bucket naming and `workstation.demos` coverage boundaries.

Gate: positive, partial and unsupported paths are distinguishable; no cloud/local parity or cross-provider support is inferred from a shared parameter name.

### Task 7 — Test, observation and decision evidence

Create `src/knowledge_graph/extractors/test_definitions.py`, `evidence_import.py`, `schema/evidence-envelope.json`, tests `test_evidence_import.py`, `test_decisions.py`.

1. Define sanitized report envelope with artifact digest, source snapshot, command/tool identity, inputs, mocks, skips, outcome and target scope.
2. Separate test definitions from reports and trusted execution origin from self-reported imported claims.
3. Reject forged/mismatched identity and missing context; signatures, if added, attest origin—not successful behavior by themselves.
4. Use synthetic reports first. Add explicitly reviewed decision documents without indexing private session history.

Gate: historical counts, failed/skipped runs and mocked Terraform results cannot establish live cloud/GPU readiness. Observation import never runs verification commands.

### Task 8 — Atomic publication and faithful projection

Create `src/knowledge_graph/ingest.py`, `publication.py`, `projection.py`; tests `test_publication.py`, `test_projection.py`, `test_freshness.py`.

1. Assemble complete RDF generations and validation manifests.
2. Implement writer locking, atomic publication and pinned reader generations.
3. Build claim-keyed `MultiDiGraph` and safe lexical documents with coverage metadata.
4. Test crash recovery, changed/deleted source, policy revocation, parallel edges and deterministic rebuild.

Gate: RDF and LPG agree on the declared projected subset; no provenance/type/claim loss; old data never silently becomes current after failed reindex.

### Task 9 — Bounded retrieval CLI

Create `src/knowledge_graph/queries.py`, `retrieval.py`, `cli.py`; tests `test_queries.py`, `test_retrieval_security.py`.

1. Implement fixed operation schemas and a common evidence result envelope.
2. Add exact/lexical source lookup and condition-aware graph traversal.
3. Add hard budgets, cancellation, scoped cursors, safe source rereads and simultaneous uncertainty flags.
   Route all current-source access through the source-admission/freshness component; test component outage, denied/revoked sources and concurrent changes. Never fall back to unrestricted repository reads.
4. Separate writer CLI subcommands from the read-only retriever capability; no arbitrary query languages.

Gate: adversarial input cannot write evidence, escape paths, contact networks, or turn a truncated traversal into a negative claim.

### Task 10 — Benchmark, docs and initial release

Create `src/tests/knowledge_graph/benchmark_cases.json`, `benchmark.py`, `test_benchmark_contract.py`, and `.agents/references/docs/evidence-graph-guide.md`.

Potential existing documentation edits, only during implementation: `ai/automator.agent.md`, `README.md`, `.agents/references/INDEX.md`. Explain optional use, limitations, no-graph fallback, privacy, rebuild and rollback. Do not modify deployment entry points.

1. Freeze a reviewed held-out question set and source-backed expected claim paths/statuses.
2. Compare ordinary exact source search, isolated upstream extractor lookup, and Automator lexical+graph retrieval using identical corpus/model/budgets where applicable.
3. Record correctness, evidence coverage, stale/unsupported claims, latency, output size and token use; retain actual raw safe results.
4. Resolve release-blocking regressions; if benefit is unproven, ship only an explicit experimental CLI or stop the expansion.

Gate: Section 10 acceptance matrix passes; benchmark supports usefulness without sacrificing correct abstention or privacy.

### Task 11 — Optional stdio MCP integration

Create `src/knowledge_graph/mcp_server.py`, an MCP server dependency manifest consistent with Task 1's parser lock, and `src/tests/knowledge_graph/test_mcp.py` only after Task 10. If iaclens already brings MCP transitively, reconcile that version rather than claiming the library is newly optional; server activation/registration remains opt-in.

Expose only read operations. Test schemas, cancellation, policy-bound handles, unavailable graph and process isolation. Publish opt-in setup instructions; do not change `.mcp.json`, `.devcontainer/setup.sh`, Hermes profiles or VS Code settings automatically. Remote HTTP is a separate authentication/authorization review, not a hidden extension of local stdio.

### Task 12 — Optional extensions, each separately gated

- **Native RDF 1.2:** create `src/knowledge_graph/rdf12_export.py` and `test_rdf12_roundtrip.py` only after parser/store/query/validator/export tests demonstrate supported semantics. Preserve distinct reifiers and unasserted claims; reject unsupported legacy/native syntax rather than reinterpret it.
- **Neo4j:** create `src/knowledge_graph/neo4j_projection.py` and integration tests only after the service/edition/security ADR. Verify projection equivalence and outage independence. Keep canonical RDF writer separate; no dual-write synchronization.
- **Packer/native detail:** add `extractors/packer.py` and `extractors/installer_source.py` with fixtures for image build/selection/post-image paths and native/cloud non-equivalence. Do not claim full shell dataflow.
- **Semantic retrieval:** use an explicitly approved model/data policy and an ablation benchmark; retain lexical fallback and separate privacy stores.
- **Incremental ingestion/cross-repository federation:** compare with full rebuild, preserve repo/environment identity, reject fuzzy identity merging and require explicit source permission.

Task dependency order: 1 → 2 → 3; 4 and 5 may proceed independently after 3; 6 joins 4/5; 7 may proceed after 3; 8 joins 6/7; then 9 → 10 → optional 11/12. One coordinator owns model/schema changes to avoid incompatible adapter assumptions.

## 10. Acceptance matrix and benchmark contract

All outcomes below are requirements, not results already achieved.

| Case | Required behavior |
|---|---|
| `container_registry` enabled/disabled | Trace actual normalization and consumers; disabled does not imply provisioning. |
| Legacy/new registry conflict | Cite validation path and error contract, not a fabricated deployment outcome. |
| Hugging Face independent of image registry | Preserve independent configuration/consumer paths and pinned-revision requirements. |
| `workstation.demos` in raw YAML | Report covered consumer gap; do not confuse it with working CLI `--demos`. |
| Security CLI-name mismatch | Report source-supported suspected gap and characterization evidence, not intended override semantics. |
| `state_bucket: auto` | Distinguish generated bucket name, backend use, and separate bootstrap resource. |
| Destroy workstation/shared registry | Trace separate stack ownership; do not claim a live teardown was tested. |
| GCP versus other clouds | Do not project GCP-specific security forwarding onto other providers. |
| Neo4j role/service | Distinguish declaration, attempted start, reported result and query readiness. |
| Image build/from-image/native install | Show separate paths/coverage; no automatic local/cloud parity. |
| Same-host plays/same-name roles/multi-root modules | Distinct identities before merge. |
| Parallel predicates and repeated assertions | Preserve every claim/provenance and typed literal through RDF/LPG round-trip. |
| Unresolved target/dynamic or missing condition | Return unknown/conditional, not implemented or absent; missing enclosing `when` never becomes unconditional. |
| Invalid Claim only in a named graph | Explicit union selection includes it and publication fails; empty selection cannot pass vacuously. |
| Freshness component unavailable/denied/revoked | No unrestricted source-read fallback; authorized snapshot evidence is historical or freshness-unknown. |
| Test definition versus execution | Existing test source alone never becomes a pass. |
| Mocked/pass/fail/skip/stale reports | Exact outcome/scope; none incorrectly becomes current live verification. |
| Dirty file/rename/delete/branch switch | Correct snapshot invalidation; no stale current citation. |
| Crash/revocation/cursor replay | Atomic generation and current-policy authorization throughout. |
| Private path/secret marker/injection | No forbidden open, persistence, transmission or authority escalation. |
| Query fan-out/time/size/cancellation | Enforced ceilings and explicit truncation/partial coverage. |
| Graph/Neo4j absent | Existing deployment behavior unchanged in mocked regression tests. |

Release thresholds are proposed policy, not measured performance: all mandatory synthetic safety/identity/uncertainty cases pass; zero forbidden-file opens, secret leaks, unauthorized mutations, or fabricated live-verification claims; every returned evidence-bearing relationship has a resolvable authorized source/claim chain. Measure precision/recall separately on each supported adapter subset, with explicit denominators and unknown cases. No overall score may hide a failing safety case.

For usefulness, require a documented improvement over exact-search baseline on the held-out multi-hop questions, with no correctness regression on direct lookups or appropriate abstention. Do not invent a percentage improvement in advance. Record corpus snapshot, model/provider/settings if used, prompt/budget, extractor/schema/policy versions, repeated-run variation, hardware/runtime, cold/warm latency and index build costs. Gold answers need independent source review and must not be generated solely by the evaluated graph.

## 11. Verification commands and existing regressions

Commands here are for future implementation; they were not run as part of this planning task. Execute only after Task 1 establishes the isolated environment. `python3` below means that environment's interpreter.

```sh
python3 -m unittest discover -s src/tests/knowledge_graph -p 'test_*.py' -v
sh src/tests/run_knowledge_graph.sh
python3 -m src.knowledge_graph.cli --help
python3 -m src.knowledge_graph.cli index --repo . --policy configs/knowledge-graph/public.yaml
python3 -m src.knowledge_graph.cli validate
python3 -m src.knowledge_graph.cli status
python3 -m src.knowledge_graph.cli explain-field container_registry
python3 -m src.knowledge_graph.cli explain-field workstation.demos
python3 src/tests/knowledge_graph/benchmark.py
```

These CLI names/flags are a proposed contract to implement and test, not existing commands. Index is an explicitly local writer operation; it must enforce the source/sandbox gates and must not be exposed to MCP.

Existing regression targets to inspect and execute in the established deployment test environment, not by casually importing deployment CLIs:

- `src/tests/profile_privacy.test.py`.
- `src/tests/deployer.test.py` and `src/tests/deploy_command.test.py` if present at implementation time; confirm names with discovery.
- `src/tests/artifact_registry.test.py`, `src/tests/distribution_profile.test.py`.
- `src/tests/artifact_registry_terraform.test.py`, `src/tests/ecr_terraform.test.py`.
- `sh src/tests/run_all.sh` after prerequisites/safety of its current contents are reviewed.

Follow existing isolated-HOME, socket/subprocess mocking patterns. Do not automatically run `src/tests/e2e/lifecycle.py` or `src/tests/e2e/verify.py`: they can deploy/connect to real resources. Terraform provider initialization may use network even with mocked plans; it is outside default offline graph acceptance. Do not cite historical test totals as current results.

## 12. Operational handoff, rollback and maintenance

- Default mode is offline/public-source-only and explicitly invoked, not a background watcher.
- Status must show stale/failed/partial extraction instead of only a green process-health flag.
- Rebuild sanitized projections from validated RDF; rebuild RDF from admitted source/evidence envelopes when schema/extractor changes require it.
- Keep versioned schema/policy migrations with before/after golden datasets. Never silently reinterpret old claims under new semantics.
- Record extractor upstream pins and local patches; dependency/security upgrades rerun identity, privacy, sandbox and round-trip tests.
- Back up only approved sanitized canonical evidence and manifests; exclude secrets and private corpus unless separately authorized. Test restore before relying on a backup. Apply retention and revocation to controlled backups too.
- Rollback disables optional retrieval and selects a compatible authorized generation; deployment is unaffected. A revoked source must not reappear through rollback.
- If no graph is available, the agent uses ordinary source search and says so. It must not fabricate graph results.

## 13. Review loop and implementation exit decisions

Before accepting each milestone:

1. Builder records exact artifacts, tests and known limitations.
2. Independent reviewer checks specification, source grounding and adversarial cases.
3. Coordinator classifies blockers, revises only affected design/code, and reruns relevant checks.
4. Reviewer rechecks addressed blockers; record unresolved items and explicit deferrals.
5. After two revision cycles on the same unresolved architectural blocker, stop and request an owner decision rather than endlessly expanding research or agents.

Mandatory owner decisions before implementation: approve this plan and optional isolated runtime/package installation. Later approvals are separate: private source ingestion, agent/MCP registration, Neo4j service, cloud observations, remote embeddings and any actual provisioning.

No mandatory Neo4j decision blocks Tasks 1–10. No native RDF 1.2 compatibility result blocks the portable RDF baseline. Missing profile consumers are separate engineering issues, not reasons to weaken evidence requirements.

### Planning review ledger

- Repository specialist: inspected exact profile/CLI/Python/Terraform/Ansible/Packer/installer paths; findings incorporated, no runtime results claimed.
- Ontology specialist: checked PROV-O, SHACL and current RDF 1.2 semantics; portable claims and compatibility gate incorporated.
- Reuse specialist: checked pinned source/license/metadata; identity collisions, parallel-edge loss and raw-parser boundary incorporated.
- Security specialist: original worker failed after API retries; its incomplete run is not approval. Replacement reviewed saved authoritative sources and supplied privacy/sandbox/revocation/query/Neo4j gates; incorporated.
- Final document review: independent reviewer found no fundamental architecture blocker and identified four high-value corrections. The coordinator incorporated all four: actual transitive MCP packaging disclosure, a scoped source-admission/freshness capability, explicit named-graph SHACL selection, and unconditional/expression/unresolved condition states. Each correction has an associated implementation acceptance test. These are document-review outcomes, not runtime acceptance or a claim that a second reviewer reran the corrected design.

## Sources

The numbered references are generated from the research ledger. Mutable standards/docs were accessed on 2026-09-09; pinned GitHub links identify inspected code. Source inspection and proposed acceptance criteria are not executable validation.

[1] https://www.w3.org/TR/prov-o — PROV-O: The PROV Ontology
[2] https://www.w3.org/TR/shacl — Shapes Constraint Language (SHACL)
[3] https://www.w3.org/TR/rdf12-concepts — RDF 1.2 Concepts and Abstract Data Model
[4] https://www.w3.org/TR/rdf12-turtle — RDF 1.2 Turtle
[5] https://github.com/RDFLib/pySHACL — GitHub - RDFLib/pySHACL: A Python validator for SHACL · GitHub
[6] https://www.opmw.org/model/p-plan — The P-Plan Ontology
[7] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/LICENSE
[8] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/pyproject.toml
[9] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/infra_graph/parsers/tf_parser.py
[10] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/infra_graph/parsers/ansible_schema.py
[11] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/infra_graph/parsers/_ids.py
[12] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/infra_graph/graph/builder.py
[13] https://github.com/vparab7/infra-graph/blob/f4caf2b316cbf6252806ee6bdeddc71d7ea016cc/LICENSE
[14] https://github.com/vparab7/infra-graph/blob/f4caf2b316cbf6252806ee6bdeddc71d7ea016cc/pyproject.toml
[15] https://github.com/vparab7/infra-graph/blob/f4caf2b316cbf6252806ee6bdeddc71d7ea016cc/infra_graph/parsers/ansible_schema.py
[16] https://github.com/onecommons/unfurl/blob/65b47ce0551c5e7fe8153f6b3d46bcb4f75b2949/LICENSE
[17] https://github.com/onecommons/unfurl/blob/65b47ce0551c5e7fe8153f6b3d46bcb4f75b2949/README.md
[18] https://github.com/onecommons/unfurl/blob/65b47ce0551c5e7fe8153f6b3d46bcb4f75b2949/pyproject.toml
[19] https://github.com/onecommons/unfurl/blob/65b47ce0551c5e7fe8153f6b3d46bcb4f75b2949/unfurl/configurators/terraform.py
[20] https://github.com/onecommons/unfurl/blob/65b47ce0551c5e7fe8153f6b3d46bcb4f75b2949/unfurl/configurators/ansible.py
[21] https://github.com/ScrimReaper/iaclens/blob/69c43b7368a2e14d8e3709373d702dfdf1fff945/infra_graph/mcp/tools.py
[22] https://pypi.org/pypi/rdflib/7.6.0/json
[23] https://pypi.org/pypi/pyshacl/0.40.1/json
[24] https://pypi.org/pypi/networkx/3.6.1/json
[25] https://raw.githubusercontent.com/networkx/networkx/networkx-3.6.1/networkx/classes/multidigraph.py
[26] https://raw.githubusercontent.com/RDFLib/rdflib/main/docs/security_considerations.md
[27] https://neo4j.com/docs/operations-manual/current/authentication-authorization/built-in-roles
[28] https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/docs/2026-07-28/tutorials/security/security_best_practices.mdx
