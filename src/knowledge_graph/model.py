"""Versioned explicit claim occurrences; no quoted proposition is asserted."""
from copy import deepcopy
import hashlib
import json
import re
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

IA = Namespace("urn:ia:")
PROV = Namespace("http://www.w3.org/ns/prov#")
EVIDENCE_KINDS = {"desired", "documented", "static_implementation", "test_definition", "test_execution", "observation", "historical_report"}
ASSESSMENTS = {"supported", "unreviewed", "disputed", "rejected"}
RAW_KEYS = {"subject", "predicate", "object", "source", "evidence_kind", "scope", "condition", "assessment", "extractor"}
DERIVED_KEYS = {"claim_id", "proposition_key", "snapshot_id", "activity_id"}


def _check(condition, code="invalid_claim"):
    if not condition:
        raise ValueError(code)


def _keys(value, required, optional=()):
    _check(isinstance(value, dict) and required <= value.keys() and value.keys() <= required | set(optional))


def _text(value, empty=False):
    _check(isinstance(value, str) and (empty or bool(value)) and len(value) <= 16384)
    _check(not any(ord(c) < 32 and c not in "\n\t" for c in value))
    return value


def _iri(value):
    _text(value)
    _check(bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+", value)))
    return URIRef(value)


def _path(value):
    _text(value)
    _check(bool(re.fullmatch(r"[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*", value)))
    _check(not any(part in {".", ".."} for part in value.split("/")))
    return value


def _sha(value):
    _check(isinstance(value, str) and bool(re.fullmatch("[a-f0-9]{64}", value)))


def _term(raw):
    _keys(raw, {"kind", "value"}, {"datatype", "language"})
    _text(raw["value"], empty=True)
    if raw["kind"] == "iri":
        _check(set(raw) == {"kind", "value"})
        _iri(raw["value"])
        return deepcopy(raw)
    _check(raw["kind"] == "literal")
    _check(not ("datatype" in raw and "language" in raw))
    result = deepcopy(raw)
    if "language" in raw:
        _check(isinstance(raw["language"], str) and bool(re.fullmatch(r"[A-Za-z]+(?:-[A-Za-z0-9]+)*", raw["language"])))
        result["language"] = raw["language"].lower()
    else:
        datatype = raw.get("datatype", str(XSD.string))
        _iri(datatype)
        _check(datatype != str(RDF.langString))
        if datatype in {str(XSD.integer), str(XSD.int), str(XSD.nonNegativeInteger), str(XSD.positiveInteger)}:
            _check(bool(re.fullmatch(r"[+-]?[0-9]+", raw["value"])))
            number = int(raw["value"])
            if datatype == str(XSD.int):
                _check(-(2 ** 31) <= number < 2 ** 31)
            if datatype == str(XSD.nonNegativeInteger):
                _check(number >= 0)
            if datatype == str(XSD.positiveInteger):
                _check(number > 0)
        if datatype == str(XSD.boolean):
            _check(raw["value"] in {"true", "false", "0", "1"})
        result["datatype"] = datatype
    return result


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_claim(raw: dict, snapshot_id: str, activity_id: str) -> dict:
    _keys(raw, RAW_KEYS, {"occurrence"} | DERIVED_KEYS)
    _iri(snapshot_id)
    _iri(activity_id)
    _iri(raw["subject"])
    _iri(raw["predicate"])
    _check(_text(raw["evidence_kind"]) in EVIDENCE_KINDS)
    # v1 raw envelopes have no execution result/context schema. Fail closed.
    _check(raw["evidence_kind"] not in {"test_execution", "observation"}, "runtime_run_context_required")
    _check(_text(raw["assessment"]) in ASSESSMENTS)
    _text(raw["extractor"])
    _keys(raw["source"], {"path", "line", "end_line", "sha256"})
    _path(raw["source"]["path"])
    _sha(raw["source"]["sha256"])
    _check(type(raw["source"]["line"]) is int and type(raw["source"]["end_line"]) is int)
    _check(1 <= raw["source"]["line"] <= raw["source"]["end_line"])
    _keys(raw["scope"], {"cloud", "execution_path"})
    _check(_text(raw["scope"]["cloud"]) in {"gcp", "aws", "azure", "alicloud", "unknown", "shared"})
    _check(_text(raw["scope"]["execution_path"]) in {"source", "image", "unknown"})
    _keys(raw["condition"], {"state", "expression"})
    state = _text(raw["condition"]["state"])
    expression = _text(raw["condition"]["expression"], empty=True)
    _check(state in {"unconditional", "expression", "unresolved"})
    _check(state != "expression" or bool(expression.strip()))
    _check(state != "unconditional" or expression == "")
    if "occurrence" in raw:
        _text(raw["occurrence"])
    record = {key: deepcopy(value) for key, value in raw.items() if key not in DERIVED_KEYS}
    record["object"] = _term(raw["object"])
    record["snapshot_id"] = snapshot_id
    record["activity_id"] = activity_id
    record["proposition_key"] = "urn:ia:proposition:" + _digest(
        ["automator-terms/v1", record["subject"], record["predicate"], record["object"]])
    record["claim_id"] = "urn:ia:claim:" + _digest(["automator-claim/v1", record])
    return record


def _literal(value):
    return Literal(value, datatype=XSD.string)


def _object_term(term):
    if term["kind"] == "iri":
        return URIRef(term["value"])
    return Literal(term["value"], datatype=term.get("datatype"), lang=term.get("language"), normalize=False)


def build_dataset(records: list[dict], snapshot: dict, activity_id: str,
                  entities: list[dict] | None = None) -> Dataset:
    """Build only explicitly declared contexts and admitted manifest sources."""
    snapshot_id = snapshot["snapshot_id"]
    snap, activity = _iri(snapshot_id), _iri(activity_id)
    _check(snapshot.get("schema_version") == "automator-snapshot/v1")
    _check(bool(re.fullmatch(r"[A-Za-z0-9_-]+", snapshot["repo_id"])))
    _sha(snapshot["policy_digest"])
    manifest = snapshot["manifest"]
    _check(isinstance(manifest, dict))
    for path, sha in manifest.items():
        _path(path)
        _sha(sha)
    normalized = [normalize_claim(r, snapshot_id, activity_id) for r in records]
    for record in normalized:
        source = record["source"]
        _check(manifest.get(source["path"]) == source["sha256"], "source_not_admitted")
    dataset = Dataset()
    dataset.bind("ia", IA)
    dataset.bind("prov", PROV)
    root = URIRef("urn:ia:dataset:" + _digest([snapshot_id, activity_id]))
    default = dataset.default_graph
    default.add((root, RDF.type, IA.Dataset))
    graphs = {}
    for role in ("claims", "provenance", "sources", "entities"):
        name = URIRef(str(root) + ":" + role)
        default.add((root, IA.declaredGraph, name))
        default.add((root, IA[role + "Graph"], name))
        graphs[role] = dataset.graph(name)
        graphs[role].add((name, RDF.type, IA.NamedGraph))
    prov = graphs["provenance"]
    prov.add((snap, RDF.type, IA.SourceSnapshot))
    prov.add((snap, RDF.type, PROV.Entity))
    prov.add((snap, IA.repoId, _literal(snapshot["repo_id"])))
    prov.add((snap, IA.policyDigest, _literal(snapshot["policy_digest"])))
    prov.add((activity, RDF.type, IA.ExtractionRun))
    prov.add((activity, RDF.type, PROV.Activity))
    prov.add((activity, PROV.used, snap))
    sources = {}
    for path, sha in sorted(manifest.items()):
        node = URIRef("urn:ia:source:" + _digest([snapshot_id, path, sha]))
        sources[path] = node
        graphs["sources"].add((node, RDF.type, IA.SourceFile))
        graphs["sources"].add((node, RDF.type, PROV.Entity))
        graphs["sources"].add((node, IA.path, _literal(path)))
        graphs["sources"].add((node, IA.sha256, _literal(sha)))
        graphs["sources"].add((node, PROV.wasDerivedFrom, snap))
    seen_entities = {}
    for entity in entities or []:
        _keys(entity, {"id", "kind", "label", "path", "line"})
        node = _iri(entity["id"])
        _text(entity["label"], empty=True)
        _check(isinstance(entity["kind"], str) and bool(re.fullmatch(r"[A-Z][A-Za-z0-9]+", entity["kind"])))
        _check(not entity["kind"].endswith("Instance"), "runtime_run_context_required")
        _path(entity["path"])
        _check(entity["path"] in sources, "source_not_admitted")
        _check(type(entity["line"]) is int and entity["line"] >= 1)
        _check(node not in seen_entities or seen_entities[node] == entity, "entity_identity_conflict")
        seen_entities[node] = entity
        graph = graphs["entities"]
        graph.add((node, RDF.type, IA.Declaration))
        graph.add((node, IA.kind, _literal(entity["kind"])))
        graph.add((node, RDFS.label, _literal(entity["label"])))
        graph.add((node, IA.path, _literal(entity["path"])))
        graph.add((node, IA.line, Literal(entity["line"], datatype=XSD.integer)))
        graph.add((node, PROV.wasDerivedFrom, sources[entity["path"]]))
    claims = graphs["claims"]
    for record in normalized:
        node = URIRef(record["claim_id"])
        locator = URIRef(str(node) + ":source")
        scope = URIRef(str(node) + ":scope")
        condition = URIRef(str(node) + ":condition")
        assessment = URIRef(str(node) + ":assessment")
        agent = URIRef("urn:ia:extractor:" + _digest(record["extractor"]))
        for predicate, obj in [(RDF.type, IA.Claim), (RDF.type, PROV.Entity),
                               (RDF.subject, URIRef(record["subject"])),
                               (RDF.predicate, URIRef(record["predicate"])),
                               (RDF.object, _object_term(record["object"])),
                               (IA.propositionKey, URIRef(record["proposition_key"])),
                               (IA.evidenceKind, _literal(record["evidence_kind"])),
                               (IA.scope, scope), (IA.condition, condition),
                               (IA.assessment, assessment), (IA.extractor, agent),
                               (PROV.wasGeneratedBy, activity), (PROV.wasDerivedFrom, locator)]:
            claims.add((node, predicate, obj))
        if record["object"]["kind"] == "literal":
            # RDFLib parsers may normalize numeric native literals; this explicit
            # lexical property retains the original RDF term, not a JSON payload.
            claims.add((node, IA.objectLexical, _literal(record["object"]["value"])))
        if "occurrence" in record:
            claims.add((node, IA.occurrence, _literal(record["occurrence"])))
        claims.add((scope, RDF.type, IA.Scope))
        claims.add((scope, IA.cloud, _literal(record["scope"]["cloud"])))
        claims.add((scope, IA.executionPath, _literal(record["scope"]["execution_path"])))
        claims.add((condition, RDF.type, IA.Condition))
        claims.add((condition, IA.conditionState, _literal(record["condition"]["state"])))
        claims.add((condition, IA.expression, _literal(record["condition"]["expression"])))
        claims.add((assessment, RDF.type, IA.ReviewAssessment))
        claims.add((assessment, IA.disposition, _literal(record["assessment"])))
        prov.add((agent, RDF.type, PROV.SoftwareAgent))
        prov.add((agent, IA.extractorVersion, _literal(record["extractor"])))
        prov.add((activity, PROV.wasAssociatedWith, agent))
        prov.add((locator, RDF.type, IA.SourceLocator))
        prov.add((locator, RDF.type, PROV.Entity))
        prov.add((locator, PROV.specializationOf, sources[record["source"]["path"]]))
        prov.add((locator, IA.snapshot, snap))
        for field in ("path", "sha256", "line", "end_line"):
            value = record["source"][field]
            prov.add((locator, IA[field], Literal(value, datatype=XSD.integer) if type(value) is int else _literal(value)))
    return dataset


def _one(graph, subject, predicate, optional=False):
    values = list(graph.objects(subject, predicate))
    _check(len(values) == 1 or (optional and not values), "invalid_rdf_cardinality")
    return values[0] if values else None


def _selected_union(dataset):
    """Do not depend on Dataset.default_union or implicit context selection."""
    _check(isinstance(dataset, Dataset), "dataset_required")
    default = dataset.default_graph
    roots = list(default.subjects(RDF.type, IA.Dataset))
    _check(len(roots) == 1, "dataset_manifest_required")
    root = roots[0]
    declared = set(default.objects(root, IA.declaredGraph))
    _check(bool(declared) and all(isinstance(n, URIRef) for n in declared), "invalid_context_selection")
    actual = {g.identifier for g in dataset.graphs() if g.identifier != default.identifier and len(g)}
    _check(actual == declared, "undeclared_or_missing_context")
    roles = [_one(default, root, IA[role + "Graph"]) for role in ("claims", "provenance", "sources", "entities")]
    _check(set(roles) == declared and len(set(roles)) == 4, "invalid_context_selection")
    union = Graph()
    for triple in default:
        union.add(triple)
    for name in sorted(declared, key=str):
        for triple in dataset.graph(name):
            union.add(triple)
    return union, root, sorted(declared, key=str)


def _read_claims(graph):
    records = []
    for node in sorted(set(graph.subjects(RDF.type, IA.Claim)), key=str):
        obj = _one(graph, node, RDF.object)
        if isinstance(obj, URIRef):
            term = {"kind": "iri", "value": str(obj)}
        else:
            _check(isinstance(obj, Literal), "invalid_object_term")
            lexical = _one(graph, node, IA.objectLexical)
            _check(isinstance(lexical, Literal), "invalid_object_lexical")
            term = {"kind": "literal", "value": str(lexical)}
            if obj.language:
                term["language"] = obj.language
            else:
                term["datatype"] = str(obj.datatype or XSD.string)
            _term(term)
            restored = _object_term(term)
            _check(restored == obj or restored.eq(obj) is True, "object_lexical_mismatch")
        source = _one(graph, node, PROV.wasDerivedFrom)
        scope = _one(graph, node, IA.scope)
        condition = _one(graph, node, IA.condition)
        assessment = _one(graph, node, IA.assessment)
        agent = _one(graph, node, IA.extractor)
        raw = {"subject": str(_one(graph, node, RDF.subject)),
               "predicate": str(_one(graph, node, RDF.predicate)), "object": term,
               "source": {field: str(_one(graph, source, IA[field])) for field in ("path", "sha256")},
               "scope": {"cloud": str(_one(graph, scope, IA.cloud)), "execution_path": str(_one(graph, scope, IA.executionPath))},
               "condition": {"state": str(_one(graph, condition, IA.conditionState)), "expression": str(_one(graph, condition, IA.expression))},
               "evidence_kind": str(_one(graph, node, IA.evidenceKind)),
               "assessment": str(_one(graph, assessment, IA.disposition)),
               "extractor": str(_one(graph, agent, IA.extractorVersion))}
        for field in ("line", "end_line"):
            raw["source"][field] = int(_one(graph, source, IA[field]))
        occurrence = _one(graph, node, IA.occurrence, optional=True)
        if occurrence is not None:
            raw["occurrence"] = str(occurrence)
        normalized = normalize_claim(raw, str(_one(graph, source, IA.snapshot)), str(_one(graph, node, PROV.wasGeneratedBy)))
        _check(normalized["claim_id"] == str(node), "claim_identity_mismatch")
        _check(normalized["proposition_key"] == str(_one(graph, node, IA.propositionKey)), "proposition_identity_mismatch")
        records.append(normalized)
    return records


def claims_from_dataset(dataset) -> list[dict]:
    from .validation import require_valid
    require_valid(dataset)
    graph, _, _ = _selected_union(dataset)
    return _read_claims(graph)
