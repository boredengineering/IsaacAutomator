"""Fixed evidence queries; no query-language evaluation or operational authority."""
import json
import time

MAX_BYTES = 50 * 1024
MAX_NODES = 500
MAX_EDGES = 2000
OPERATIONS = {"explain-field", "find", "trace", "evidence", "impact"}


def query(claims, entities, operation, value, *, depth=3, limit=25):
    if operation not in OPERATIONS or not isinstance(value, str) or len(value) > 256:
        raise ValueError("unsupported operation or query length")
    if type(depth) is not int or not 0 <= depth <= 6:
        raise ValueError("depth must be between 0 and 6")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    result = {
        "operation": operation, "query": value, "status": ["unknown"],
        "message": "Implementation is not established by this scoped evidence search.",
        "claims": [], "entities": [], "truncated": False,
    }
    deadline = time.monotonic() + 5.0
    needle = value.casefold()
    seeds = set()
    matched = []
    for i, entity in enumerate(entities):
        if i >= 20000 or time.monotonic() > deadline:
            result["truncated"] = True
            break
        label = str(entity.get("label", ""))
        if operation == "explain-field":
            match = entity.get("kind") == "ProfileField" and label == value
        elif operation == "impact":
            match = entity.get("path") == value
        elif operation in {"find", "trace"}:
            match = value == entity.get("id") or (bool(needle) and (
                needle in label.casefold() or needle in str(entity.get("path", "")).casefold()))
        else:
            match = False
        if match:
            if len(seeds) >= MAX_NODES:
                result["truncated"] = True
                break
            seeds.add(entity["id"])
            matched.append(entity)
    if len(matched) > limit:
        result["truncated"] = True
    result["entities"] = matched[:limit]
    frontier = seeds
    visited = set(seeds)
    collected = {}
    inspected = 0
    rounds = 1 if operation in {"find", "evidence"} else max(1, depth)
    for _ in range(rounds):
        following = set()
        for claim in claims:
            inspected += 1
            if inspected > MAX_EDGES or time.monotonic() > deadline:
                result["truncated"] = True
                break
            subject = claim["subject"]
            obj = claim["object"]
            target = obj["value"] if obj["kind"] == "iri" else None
            match = claim.get("claim_id") == value if operation == "evidence" else (
                subject in frontier or target in frontier)
            if operation == "impact" and claim.get("source", {}).get("path") == value:
                match = True
            if not match:
                continue
            collected[claim["claim_id"]] = claim
            if claim.get("assessment") == "disputed" and "disputed" not in result["status"]:
                result["status"].append("disputed")
            if claim.get("assessment") == "supported" and claim.get("condition", {}).get("state") == "unconditional":
                following.update(x for x in (subject, target) if x is not None and x not in visited)
        if inspected > MAX_EDGES or time.monotonic() > deadline:
            break
        if len(visited | following) > MAX_NODES:
            result["truncated"] = True
            break
        visited.update(following)
        frontier = following
        if not frontier:
            break
    if frontier and operation not in {"find", "evidence"}:
        result["truncated"] = True
    selected = list(collected.values())
    if len(selected) > limit:
        result["truncated"] = True
    result["claims"] = selected[:limit]
    if matched or selected:
        result["message"] = "Static evidence found; a complete executable consumer path is not established."
        result["status"].insert(0, "evidence_found")
    while len(json.dumps(result, ensure_ascii=True).encode()) > MAX_BYTES - 64:
        result["truncated"] = True
        if result["claims"]:
            result["claims"].pop()
        elif result["entities"]:
            result["entities"].pop()
        else:
            break
    if result["truncated"]:
        result["status"].append("truncated")
    return result
