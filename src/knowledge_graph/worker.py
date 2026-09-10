"""Private bounded worker protocol. All source parsing occurs after OS isolation."""
import json
from pathlib import Path
import resource
import sys


def main():
    stage = "imports"
    try:
        # Trusted implementation imports precede restriction; target source never imports.
        import hashlib
        import importlib.metadata
        import networkx as nx
        from rdflib import Dataset
        from .extractors.structural import extract
        from .model import build_dataset, claims_from_dataset
        from .projection import project
        from .sandbox import restrict_process
        from .validation import validate_dataset

        resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,) * 2)
        versions = {name: importlib.metadata.version(name) for name in
                    ("rdflib", "pyshacl", "networkx", "python-hcl2", "PyYAML")}
        stage = "sandbox"
        restrict_process([str(Path(__file__).parent.resolve()), sys.prefix, sys.base_prefix])
        stage = "input"
        raw = sys.stdin.buffer.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("input limit")
        request = json.loads(raw)
        if request.get("operation") == "validate":
            dataset = Dataset()
            dataset.parse(data=request["dataset"], format="trig")
            stage = "validate"
            report = validate_dataset(dataset)
            if not report["conforms"]:
                raise ValueError("invalid dataset")
            print(json.dumps({"status": "ok", "validation": report}))
            return 0
        if request.get("operation") != "build":
            raise ValueError("invalid operation")
        snapshot = request["snapshot"]
        stage = "extract"
        extracted = extract(snapshot)
        stage = "model"
        activity = "urn:ia:extraction:" + hashlib.sha256(
            (snapshot["snapshot_id"] + request["implementation_digest"]).encode()).hexdigest()
        dataset = build_dataset(extracted["claims"], snapshot, activity, entities=extracted["entities"])
        stage = "validate"
        report = validate_dataset(dataset)
        if not report["conforms"]:
            raise ValueError("invalid dataset")
        stage = "project"
        graph = project(dataset)
        records = claims_from_dataset(dataset)
        stage = "serialize"
        payload = {
            "status": "ok", "dataset": dataset.serialize(format="trig"),
            "claims": records, "entities": extracted["entities"],
            "coverage": [item for item in snapshot["coverage"] if item["status"] != "scanned"] + extracted["coverage"],
            "projection": nx.node_link_data(graph, edges="edges"),
            "validation": report, "versions": versions,
            "sandbox": "landlock+seccomp",
        }
        result = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        if len(result.encode()) > 32 * 1024 * 1024:
            raise ValueError("output limit")
        print(result)
        return 0
    except Exception:
        # Source literals, exception text and traceback must not cross the boundary.
        print(json.dumps({"status": "error", "stage": stage}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
