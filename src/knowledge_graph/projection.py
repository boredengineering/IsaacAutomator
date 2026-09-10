"""Rebuildable claim-keyed MultiDiGraph; never a second RDF authority."""
from copy import deepcopy
import json

import networkx as nx
from rdflib.namespace import RDF, RDFS

from .model import IA, _one, _selected_union, claims_from_dataset


def project(dataset) -> nx.MultiDiGraph:
    records = claims_from_dataset(dataset)  # Strict full RDF validation first.
    union, _, _ = _selected_union(dataset)
    graph = nx.MultiDiGraph()
    graph.graph.update(policy_version="automator-projection/v1",
                       subset="supported-claim-edges;other-claim-nodes;declared-entities",
                       claim_count=len(records))
    for node in sorted(set(union.subjects(RDF.type, IA.Declaration)), key=str):
        graph.add_node(str(node), id=str(node),
                       kind=str(_one(union, node, IA.kind)),
                       label=str(_one(union, node, RDFS.label)),
                       path=str(_one(union, node, IA.path)),
                       line=int(_one(union, node, IA.line)))
    for record in records:
        data = deepcopy(record)
        if record["assessment"] != "supported":
            graph.add_node(record["claim_id"], kind="Claim", **data)
            continue
        obj = record["object"]
        if obj["kind"] == "iri":
            target = obj["value"]
        else:
            # A tagged tuple cannot alias any application IRI string. Use the
            # complete canonical term rather than a lossy lexical-only label.
            target = ("literal", json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
            graph.add_node(target, kind="Literal", term=deepcopy(obj), label=obj["value"])
        graph.add_edge(record["subject"], target, key=record["claim_id"],
                       unconditional=record["condition"]["state"] == "unconditional", **data)
    return graph
