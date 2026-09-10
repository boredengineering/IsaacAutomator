"""JSON claim construction for admitted in-memory sources only."""
import hashlib
import json
from pathlib import PurePosixPath


def scope(path):
    parts = PurePosixPath(path).parts
    clouds = [p for p in parts if p in {"aws", "gcp", "azure", "alicloud"}]
    return {"cloud": clouds[-1] if clouds else "unknown", "execution_path": "unknown"}


class Result:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.data = {"entities": [], "claims": [], "coverage": []}
        self.ids = set()

    def entity(self, path, anchor, kind, label, line=1):
        identity = json.dumps([self.snapshot["repo_id"], path, anchor], ensure_ascii=True)
        iri = "urn:ia:decl:" + hashlib.sha256(identity.encode()).hexdigest()
        if iri not in self.ids:
            self.ids.add(iri)
            self.data["entities"].append({"id": iri, "kind": kind, "label": label, "path": path, "line": line})
        return iri

    def claim(self, subject, predicate, value, path, line=1, end_line=None,
              iri=False, evidence="static_implementation", condition=None,
              assessment="supported", extractor="automator-ast/v1", occurrence=None):
        claim = {
            "subject": subject, "predicate": "urn:ia:" + predicate,
            "object": {"kind": "iri" if iri else "literal", "value": str(value)},
            "source": {"path": path, "line": line, "end_line": end_line or line,
                       "sha256": self.snapshot["manifest"][path]},
            "evidence_kind": evidence, "scope": scope(path),
            "condition": condition or {"state": "unconditional", "expression": ""},
            "assessment": assessment, "extractor": extractor,
        }
        if occurrence is not None:
            claim["occurrence"] = str(occurrence)
        self.data["claims"].append(claim)

    def coverage(self, path, status, reason):
        row = {"path": path, "status": status, "reason": reason}
        if row not in self.data["coverage"]:
            self.data["coverage"].append(row)
