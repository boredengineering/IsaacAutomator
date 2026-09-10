"""Bounded subprocess orchestration; the worker has no repository capability."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import selectors
import time

ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT = 32 * 1024 * 1024
MAX_OUTPUT = 32 * 1024 * 1024


class WorkerError(ValueError):
    pass


def implementation_digest():
    package = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        if path.suffix not in {".py", ".ttl"}:
            continue
        if path.is_symlink() or not path.is_file():
            raise WorkerError("unsafe graph implementation path")
        digest.update(str(path.relative_to(package)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_worker(payload):
    data = json.dumps(payload, ensure_ascii=True).encode()
    if len(data) > MAX_INPUT:
        raise WorkerError("worker input limit exceeded")
    environment = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
    }
    child = subprocess.Popen(
        [sys.executable, "-m", "src.knowledge_graph.worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd=ROOT, env=environment, close_fds=True,
    )
    deadline = time.monotonic() + 90
    raw = bytearray()
    sent = 0
    try:
        with selectors.DefaultSelector() as streams:
            os.set_blocking(child.stdin.fileno(), False)
            os.set_blocking(child.stdout.fileno(), False)
            streams.register(child.stdin, selectors.EVENT_WRITE)
            streams.register(child.stdout, selectors.EVENT_READ)
            while streams.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerError("worker time limit exceeded")
                for key, _ in streams.select(remaining):
                    if key.fileobj is child.stdin:
                        try:
                            sent += os.write(child.stdin.fileno(), data[sent:sent + 65536])
                        except BrokenPipeError:
                            sent = len(data)
                        if sent == len(data):
                            streams.unregister(child.stdin)
                            child.stdin.close()
                    else:
                        chunk = os.read(child.stdout.fileno(), 65536)
                        if not chunk:
                            streams.unregister(child.stdout)
                            child.stdout.close()
                        else:
                            raw.extend(chunk)
                            if len(raw) > MAX_OUTPUT:
                                raise WorkerError("worker output limit exceeded")
        child.wait(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        raise WorkerError("worker time limit exceeded") from exc
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
        child.stdin.close()
        child.stdout.close()
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise WorkerError("worker failed without a valid result") from exc
    if child.returncode or result.get("status") != "ok":
        stage = result.get("stage", "unknown")
        if stage not in {"imports", "sandbox", "input", "extract", "model", "validate", "project", "serialize"}:
            stage = "unknown"
        raise WorkerError("isolated worker failed at " + stage)
    return result
