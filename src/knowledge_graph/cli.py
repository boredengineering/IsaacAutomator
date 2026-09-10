"""Explicit optional local graph CLI; never imported by deployment commands."""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from . import publication

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Optional, offline infrastructure evidence graph")
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ["index", "status", "validate", "explain-field", "find", "trace", "evidence", "impact"]:
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, default=Path.cwd())
        command.add_argument("--cache", type=Path)
        command.add_argument("--policy", type=Path)
        if name in {"explain-field", "find", "trace", "evidence", "impact"}:
            command.add_argument("value")
            command.add_argument("--limit", type=int, default=25)
            command.add_argument("--depth", type=int, default=3)
    args = parser.parse_args(argv)
    repo = Path(os.path.abspath(args.repo))
    repo_key = hashlib.sha256(str(repo).encode()).hexdigest()[:16]
    cache = args.cache or Path.home() / ".cache/isaacautomator-graph/data" / repo_key
    policy_path = args.policy or repo / "configs/knowledge-graph/public.yaml"
    try:
        if Path(os.path.abspath(cache)).is_relative_to(repo):
            raise ValueError("graph cache must be outside the repository")
        if args.operation != "index":
            generation, artifacts = publication.load(cache)
        from .ingest import implementation_digest, run_worker
        from .snapshot import capture_snapshot, check_freshness
        from .source_policy import load_policy

        policy = load_policy(policy_path)
        implementation = implementation_digest()
        if args.operation == "index":
            snapshot = capture_snapshot(repo, policy)
            if not snapshot["sources"]:
                raise ValueError("no admitted source")
            result = run_worker({"operation": "build", "snapshot": snapshot,
                                 "implementation_digest": implementation})
            if not check_freshness(repo, load_policy(policy_path), snapshot)["current"] or implementation != implementation_digest():
                raise ValueError("sources or policy changed during extraction")
            metadata = {
                "snapshot": {key: value for key, value in snapshot.items() if key != "sources"},
                "implementation_digest": implementation, "versions": result["versions"],
                "sandbox": result["sandbox"], "validation": result["validation"],
            }
            artifacts = {"dataset.trig": result["dataset"], "manifest.json": json.dumps(metadata, sort_keys=True)}
            for key in ("claims", "entities", "coverage", "projection"):
                artifacts[key + ".json"] = json.dumps(result[key], sort_keys=True)
            generation = publication.publish(cache, artifacts)
            _emit({"status": "indexed", "generation": generation,
                   "snapshot_id": snapshot["snapshot_id"], "sandbox": result["sandbox"],
                   "sources": len(snapshot["sources"]), "claims": len(result["claims"]),
                   "entities": len(result["entities"]), "verification": "static_only",
                   "coverage": dict(Counter(item["status"] for item in result["coverage"]))})
            return 0
        metadata = json.loads(artifacts["manifest.json"])
        snapshot = metadata["snapshot"]
        fresh = check_freshness(repo, load_policy(policy_path), snapshot)
        if not fresh["current"] or metadata["implementation_digest"] != implementation:
            _emit({"status": "stale", "message": "Sources, policy or extractor changed; rebuild before querying."})
            return 3
        if args.operation == "validate":
            result = run_worker({"operation": "validate", "dataset": artifacts["dataset.trig"]})
            if not check_freshness(repo, load_policy(policy_path), snapshot)["current"]:
                _emit({"status": "stale", "message": "Sources or policy changed during validation; results withheld."})
                return 3
            _emit({"status": "conforms", "generation": generation, "validation": result["validation"]})
            return 0
        claims = json.loads(artifacts["claims.json"])
        entities = json.loads(artifacts["entities.json"])
        if args.operation == "status":
            _emit({"status": "current", "generation": generation, "snapshot_id": snapshot["snapshot_id"],
                   "claims": len(claims), "entities": len(entities), "sources": len(snapshot["manifest"]),
                   "sandbox": metadata["sandbox"], "verification": "static_only", "versions": metadata["versions"]})
            return 0
        from .queries import query
        result = query(claims, entities, args.operation, args.value, depth=args.depth, limit=args.limit)
        # Recheck before returning, so a mutation during traversal cannot yield a current citation.
        if not check_freshness(repo, load_policy(policy_path), snapshot)["current"]:
            _emit({"status": "stale", "message": "Sources or policy changed during query; results withheld."})
            return 3
        result.update({"generation": generation, "snapshot_id": snapshot["snapshot_id"],
                       "policy_digest": snapshot["policy_digest"], "freshness": "current"})
        _emit(result)
        return 0
    except (OSError, ValueError, KeyError, ImportError) as exc:
        from .ingest import WorkerError
        message = str(exc) if isinstance(exc, WorkerError) else "Graph unavailable or input rejected; check optional setup, policy and source admission."
        _emit({"status": "unavailable", "message": message})
        return 2


def _emit(result):
    # Envelope metadata consumes bytes too; enforce the final CLI output ceiling.
    while len(json.dumps(result, ensure_ascii=True).encode()) > 50 * 1024 - 1:
        result["truncated"] = True
        if result.get("claims") and isinstance(result["claims"], list):
            result["claims"].pop()
        elif result.get("entities") and isinstance(result["entities"], list):
            result["entities"].pop()
        else:
            result = {"status": "truncated", "message": "Response exceeds output budget."}
            break
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
