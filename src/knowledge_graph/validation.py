"""Pinned local SHACL Core plus deterministic semantic acceptance checks.

Callers must run untrusted RDF parsing and this validator inside the pipeline's
OS sandbox/resource limits. This module neither opens data IRIs nor enables
imports, inference, JavaScript, advanced rules or source-supplied shapes.
"""
import hashlib
from pathlib import Path

from pyshacl import validate
from rdflib import BNode, Graph, URIRef
from rdflib.namespace import RDF, SH

from .model import (IA, PROV, _check, _digest, _object_term, _one, _path,
                    _read_claims, _selected_union, _sha)

SHAPES_PATH = Path(__file__).with_name("schema") / "shapes.ttl"
OPTIONS = {"inference": "none", "advanced": False, "js": False, "do_owl_imports": False}


def _semantic_checks(dataset, graph, root, records):
    claims_graph = dataset.graph(_one(dataset.default_graph, root, IA.claimsGraph))
    sources_graph = dataset.graph(_one(dataset.default_graph, root, IA.sourcesGraph))
    entities_graph = dataset.graph(_one(dataset.default_graph, root, IA.entitiesGraph))
    for node in graph.subjects(RDF.type, IA.Declaration):
        _check((node, RDF.type, IA.Declaration) in entities_graph, "misplaced_entity")
        source = _one(graph, node, PROV.wasDerivedFrom)
        _check(_one(graph, node, IA.path) == _one(sources_graph, source, IA.path), "entity_source_mismatch")
    for source in graph.subjects(RDF.type, IA.SourceFile):
        _check((source, RDF.type, IA.SourceFile) in sources_graph, "misplaced_source")
        path = str(_one(graph, source, IA.path))
        sha = str(_one(graph, source, IA.sha256))
        snapshot_id = str(_one(graph, source, PROV.wasDerivedFrom))
        _path(path)
        _sha(sha)
        _check(str(source) == "urn:ia:source:" + _digest([snapshot_id, path, sha]), "source_identity_mismatch")
    for record in records:
        node = URIRef(record["claim_id"])
        _check((node, RDF.type, IA.Claim) in claims_graph, "misplaced_claim")
        activity = URIRef(record["activity_id"])
        snapshot = URIRef(record["snapshot_id"])
        agent = _one(graph, node, IA.extractor)
        locator = _one(graph, node, PROV.wasDerivedFrom)
        source = _one(graph, locator, PROV.specializationOf)
        _check((activity, RDF.type, IA.ExtractionRun) in graph, "invalid_activity")
        _check((activity, PROV.used, snapshot) in graph, "invalid_usage")
        _check((activity, PROV.wasAssociatedWith, agent) in graph, "invalid_association")
        _check((source, PROV.wasDerivedFrom, snapshot) in sources_graph, "source_snapshot_mismatch")
        for field in ("path", "sha256"):
            _check(_one(graph, locator, IA[field]) == _one(sources_graph, source, IA[field]), "source_manifest_mismatch")
        base = (URIRef(record["subject"]), URIRef(record["predicate"]), _object_term(record["object"]))
        _check(base not in graph, "base_fact_asserted")


def validate_dataset(dataset) -> dict:
    """Return safe machine diagnostics, never untrusted RDF values/messages."""
    result = {"conforms": False, "errors": [], "options": dict(OPTIONS)}
    try:
        graph, root, selected = _selected_union(dataset)
        data = SHAPES_PATH.read_bytes()
        shapes = Graph().parse(data=data, format="turtle")
        allowed_types = {IA.Dataset, IA.NamedGraph, IA.Declaration, IA.Claim, IA.SourceSnapshot,
                         IA.SourceFile, IA.SourceLocator, IA.Scope, IA.Condition,
                         IA.ReviewAssessment, IA.ExtractionRun, PROV.Entity,
                         PROV.Activity, PROV.SoftwareAgent}
        allowed_predicates = set(shapes.objects(None, SH.path)) | {
            RDF.type, IA.declaredGraph, IA.claimsGraph, IA.provenanceGraph,
            IA.sourcesGraph, IA.entitiesGraph}
        for subject, predicate, obj in graph:
            _check(not isinstance(subject, BNode) and not isinstance(obj, BNode), "blank_identity")
            _check(predicate in allowed_predicates, "unexpected_data_predicate")
            if predicate == RDF.type:
                _check(obj in allowed_types, "unexpected_data_class")
        result["selected_graphs"] = [str(name) for name in selected]
        result["shapes_digest"] = hashlib.sha256(data).hexdigest()
        # N3 term strings retain RDF lexical identity; all data identities are IRIs.
        triples = sorted([tuple(term.n3() for term in triple) for triple in graph])
        result["union_digest"] = _digest(triples)
        conforms, _, _ = validate(data_graph=graph, shacl_graph=shapes,
                                  meta_shacl=True, **OPTIONS)
        if not conforms:
            return {"conforms": False, "errors": ["shacl_nonconformance"], "options": dict(OPTIONS)}
        records = _read_claims(graph)
        _semantic_checks(dataset, graph, root, records)
        result["conforms"] = True
    except Exception:
        # pySHACL diagnostics can echo secret-valued invalid nodes. Never return
        # their report graph, exception text, focus nodes, or supplied messages.
        result = {"conforms": False, "errors": ["dataset_validation_failed"],
                  "options": dict(OPTIONS)}
    return result


def require_valid(dataset):
    if not validate_dataset(dataset)["conforms"]:
        raise ValueError("dataset_validation_failed")
