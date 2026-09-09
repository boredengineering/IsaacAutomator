#!/usr/bin/python3
"""Merge a host-specific credential helper without returning Docker secrets."""
import json
import os
from pathlib import Path
import re
import tempfile

from ansible.module_utils.basic import AnsibleModule


def configure(home, uid, gid, registry, check_mode=False):
    if not re.fullmatch(r"[a-z][a-z0-9-]*-docker\.pkg\.dev", registry):
        raise ValueError("invalid registry")
    # Each Ansible invocation configures one account in a dedicated process.
    # Drop privilege permanently BEFORE inspecting any user-controlled path:
    # pathname/symlink checks alone cannot protect root from directory swaps.
    # Clear supplementary groups too (notably root/docker), and never regain
    # root to repair a user's existing files. Inaccessible files fail closed.
    if os.geteuid() == 0 and uid != 0:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid, uid, gid, gid):
        raise ValueError("Docker configuration must run as its owner")
    directory = Path(home) / ".docker"
    path = directory / "config.json"
    if directory.is_symlink() or path.is_symlink():
        raise ValueError("refusing symlink Docker configuration")
    if directory.exists() and not directory.is_dir():
        raise ValueError("Docker configuration directory is not a directory")
    if path.exists() and not path.is_file():
        raise ValueError("Docker configuration is not a regular file")
    try:
        existing = json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, UnicodeError):
        raise ValueError("invalid Docker configuration JSON") from None
    if not isinstance(existing, dict) or any(
        key in existing and not isinstance(existing[key], dict)
        for key in ("credHelpers", "auths")
    ):
        raise ValueError("invalid Docker configuration shape")
    merged = dict(existing)
    merged["credHelpers"] = dict(existing.get("credHelpers", {}))
    merged["credHelpers"][registry] = "isaac-artifact-registry"
    # A static credential for this host is obsolete. Leave all other auth alone.
    if "auths" in existing:
        merged["auths"] = dict(existing["auths"])
        for key in (registry, "https://" + registry, "https://" + registry + "/v1/"):
            merged["auths"].pop(key, None)
    changed = merged != existing or not path.exists()
    for target, mode in ((directory, 0o700), (path, 0o600)):
        if not target.exists():
            changed = True
        else:
            stat = target.stat()
            changed |= (stat.st_mode & 0o7777, stat.st_uid, stat.st_gid) != (mode, uid, gid)
    if check_mode or not changed:
        return changed
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    os.chown(directory, uid, gid)
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), uid, gid)
            json.dump(merged, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def main():
    module = AnsibleModule(argument_spec={
        "home": {"type": "path", "required": True},
        "uid": {"type": "int", "required": True},
        "gid": {"type": "int", "required": True},
        "registry": {"type": "str", "required": True},
    }, supports_check_mode=True)
    try:
        changed = configure(**module.params, check_mode=module.check_mode)
    except Exception:
        module.fail_json(msg="Cannot safely merge Docker configuration; check JSON, ownership and symlinks")
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
