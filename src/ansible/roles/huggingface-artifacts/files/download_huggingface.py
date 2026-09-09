#!/usr/bin/env python3
"""Download data only, under the effective SSH user's home; JSON on stdin.

huggingface-hub==0.34.4 snapshot_download API:
https://huggingface.co/docs/huggingface_hub/v0.34.4/en/package_reference/file_download
Each label owns a Hub cache. Immutable snapshots stay in separate commit paths;
no local_dir overlay (which could retain stale files), imports, or model loading.
"""
import contextlib
import json
import os
from pathlib import Path
import pwd
import stat
import sys

from huggingface_contract import decode_settings


def managed_directory(path, home):
    """Refuse cache path symlinks instead of following writes outside the home."""
    relative = path.relative_to(home)
    current = home
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("managed Hugging Face directories must not be symlinks")
        current.mkdir(mode=0o700, exist_ok=True)
    return path


def fingerprint(snapshot, cache):
    if not snapshot.exists():
        return None
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("invalid snapshot directory")
    result = []
    for path in sorted(snapshot.rglob("*")):
        # Hub blob links within the label's cache are expected and safe.
        path.resolve().relative_to(cache.resolve())
        if path.is_file():
            info = path.stat()
            result.append((str(path.relative_to(snapshot)), info.st_size, info.st_mtime_ns))
    return result


def download(settings):
    if not settings["enabled"]:
        return {"changed": False, "snapshots": {}}
    if os.geteuid() == 0:
        raise ValueError("Hugging Face downloads must not run as root")
    home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    if not home.is_absolute() or home == Path("/") or home == Path("/root") or not home.is_dir():
        raise ValueError("SSH account must have an existing non-root home")
    home = home.resolve()
    if home == Path('/') or home == Path('/root'):
        raise ValueError("SSH account must have a non-root home")
    os.umask(0o077)
    base = managed_directory(home / ".cache/isaac-automator/huggingface", home)
    for directory in (".hub", ".xet"):
        managed_directory(base / directory, home)
    # Environment must be set before importing huggingface_hub (constants are
    # evaluated during import). token=False explicitly forbids cached auth.
    for key in list(os.environ):
        if key.startswith("HF_") or key == "HUGGING_FACE_HUB_TOKEN":
            os.environ.pop(key)
    os.environ.update({
        "HF_HOME": str(base / ".hub"),
        "HF_XET_CACHE": str(base / ".xet"),
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "NETRC": str(base / ".no-netrc"),
    })
    token = False
    if "token_file" in settings:
        # This is the sole explicit credential reference. Never serialize its
        # contents, expose it in argv, invoke login(), or print caught errors.
        fd = os.open(settings["token_file"], os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("token_file must be a regular file")
            token = stream.read(16385).strip()
        if not token or len(token) > 16384 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token):
            raise ValueError("invalid token file contents")
    from huggingface_hub import snapshot_download

    changed, snapshots = False, {}
    for entry in settings["repositories"]:
        cache = managed_directory(base / entry["name"], home)
        repo_folder = entry["repo_type"] + "s--" + entry["repo_id"].replace("/", "--")
        managed_directory(cache / repo_folder / "blobs", home)
        managed_directory(cache / ".locks" / repo_folder, home)
        # Refuse symlinked cache parents before the Hub creates files.
        snapshot = managed_directory(cache / repo_folder / "snapshots", home) / entry["revision"]
        before = fingerprint(snapshot, cache)
        returned = Path(snapshot_download(
            repo_id=entry["repo_id"], repo_type=entry["repo_type"],
            revision=entry["revision"], cache_dir=str(cache), token=token,
            endpoint="https://huggingface.co",
        ))
        if returned != snapshot:
            raise ValueError("Hub returned an unexpected snapshot path")
        changed = (before != fingerprint(snapshot, cache)) or changed
        snapshots[entry["name"]] = str(snapshot)
    return {"changed": changed, "snapshots": snapshots}


def main():
    try:
        settings = decode_settings(sys.stdin.read())
        # Libraries can include credentials in exception text/progress output.
        # Ansible also runs this entire task with no_log, as defense in depth.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = download(settings)
    except Exception:
        print("Hugging Face artifact download failed; check configuration, access and disk space", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
