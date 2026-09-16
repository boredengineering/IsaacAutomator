#!/usr/bin/env python3
"""Legacy installer YAML -> NUL-delimited key/value data, never shell source.

Requires PyYAML in the installer's python3 environment (OS package python3-yaml,
or `python3 -m pip install PyYAML` in a virtual environment). Parsing failures
never fall back to a partial/token-based interpretation of the document.
"""
import ctypes
import importlib.util
import os
import re
import stat
import sys

# Parsing and previews must not create adjacent bytecode caches.
sys.dont_write_bytecode = True
# Load the adjacent trusted helper by path, including under python -I previews;
# do not add the current directory or profile directory to Python's import path.
_workspace_spec = importlib.util.spec_from_file_location(
    "installer_workspace_paths", os.path.join(os.path.dirname(__file__), "workspace_paths.py"))
assert _workspace_spec is not None and _workspace_spec.loader is not None
_workspace_paths = importlib.util.module_from_spec(_workspace_spec)
_workspace_spec.loader.exec_module(_workspace_paths)
expand_path = _workspace_paths.expand_path
validate_settings = _workspace_paths.validate_settings

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required to load installer profiles. Install the OS package "
             "python3-yaml, or run `python3 -m pip install PyYAML` in your Python "
             "environment, then retry. No profile was applied.")


MAX_PROFILE_BYTES = 262144
MAX_YAML_DEPTH = 64
MAX_YAML_NODES = 16384
MAX_PROFILE_EXPANSION_BYTES = 1048576


class ProfileLoader(yaml.SafeLoader):
    """Safe YAML with explicit keys only; no overwrites, aliases or merge keys."""

    def __init__(self, stream):
        self._depth = 0
        self._nodes = 0
        super().__init__(stream)

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases and merge keys are unsupported.")
        self._nodes += 1
        if self._nodes > MAX_YAML_NODES or self._depth >= MAX_YAML_DEPTH:
            raise ValueError("YAML depth or node limit exceeded.")
        self._depth += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            if key_node.tag != "tag:yaml.org,2002:str":
                raise ValueError("Profile keys must be strings; YAML merge keys are unsupported.")
            key = self.construct_object(key_node, deep=deep)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid profile key: {key!r}; use letters, digits and underscores.")
            if key in mapping:
                raise ValueError(f"Duplicate profile key: {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def parse_profile(path, workspace_overrides=None):
    return parse_profile_text(read_profile_text(path), workspace_overrides=workspace_overrides)


class _StatxMount(ctypes.Structure):
    # Linux UAPI struct statx is 256 bytes; stx_mnt_id sits at offset 144.
    _fields_ = [("mask", ctypes.c_uint32), ("_basic", ctypes.c_byte * 140),
                ("mount_id", ctypes.c_uint64), ("_rest", ctypes.c_byte * 104)]


def _mount_id(fd):
    """Descriptor-only mount identity, including same-device bind mounts."""
    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, "statx"):
        raise OSError("Cannot inspect profile mount identity.")
    info = _StatxMount()
    # AT_EMPTY_PATH | AT_SYMLINK_NOFOLLOW, STATX_MNT_ID. No /proc read.
    if libc.statx(fd, b"", 0x1000 | 0x100, 0x1000, ctypes.byref(info)) != 0 or not info.mask & 0x1000:
        raise OSError("Cannot inspect profile mount identity.")
    return info.mount_id


def read_profile_text(path):
    """Return bounded UTF-8 text from one stable regular-file descriptor.

    Every explicit path component is walked without following symlinks. The
    selected leaf must be single-link and on its parent directory's mount (a
    mounted /home or workspace ancestor is fine; a file bind mount is not).
    No content pathname is reopened and no /proc lookup is used. Metadata before
    and after the read detects replacement, relinking, growth and ordinary
    concurrent edits; it is not an atomic filesystem snapshot against a hostile
    filesystem/server or privileged writer. Import before entering confinement.
    """
    path = os.fsdecode(os.fspath(path))
    if not path or "\0" in path:
        raise ValueError("Invalid profile path.")
    parts = path.split("/")
    directory = os.open("/" if path.startswith("/") else ".",
                        os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    fd = None
    try:
        for part in parts[:-1]:
            if not part or part == ".":
                continue
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("Cannot read profile: expected a regular single-link file.")
        if _mount_id(fd) != _mount_id(directory):
            raise ValueError("Cannot read profile: mounted files are unsupported.")
        if before.st_size > MAX_PROFILE_BYTES:
            raise ValueError("Profile size limit exceeded.")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, MAX_PROFILE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_PROFILE_BYTES:
                raise ValueError("Profile size limit exceeded.")
        after = os.fstat(fd)
        named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (total != before.st_size or
                any(getattr(before, field) != getattr(after, field) or
                    getattr(before, field) != getattr(named, field) for field in fields)):
            raise ValueError("Profile changed during read.")
        return b"".join(chunks).decode("utf-8")
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def parse_profile_text(raw, workspace_overrides=None):
    """Validate legacy YAML text and return the unchanged NUL key/value contract."""
    if not isinstance(raw, (str, bytes)):
        raise TypeError("Profile text must be str or UTF-8 bytes.")
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError("Profile size limit exceeded.")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ValueError("Profile size limit exceeded.")
    data = yaml.load(raw, Loader=ProfileLoader)
    if not isinstance(data, dict) or not data:
        raise ValueError("Expected a non-empty legacy profile mapping.")
    # Legacy public presets have no kind. Never interpret newer schemas as defaults.
    for key, value in data.items():
        if key.upper() == "KIND":
            if value == "workstation-baseline":
                raise ValueError("Workstation baseline is an inventory, not an executable installer profile.")
            raise ValueError("Unsupported installer profile kind; use a kind-less legacy installer preset. "
                             "workstation-profile documents require a separate adapter.")
    items = []
    names = set()
    active = set()
    expansion_bytes = 0

    def flatten(node, prefix="CFG_"):
        nonlocal expansion_bytes
        if id(node) in active:
            raise ValueError("Recursive YAML aliases are unsupported.")
        active.add(id(node))
        for key, value in node.items():
            name = prefix + key.upper()
            # Count intermediate mapping names too, so empty mappings cannot
            # amplify shared long prefixes without consuming the work budget.
            expansion_bytes += len(name) + 1
            if expansion_bytes > MAX_PROFILE_EXPANSION_BYTES:
                raise ValueError("Profile expansion limit exceeded.")
            if name in names:
                raise ValueError(f"Colliding flattened profile key: {name}")
            names.add(name)
            if name == "CFG_WORKSPACE" and not isinstance(value, dict):
                raise ValueError("workspace must be a mapping")
            if name.startswith("CFG_WORKSPACE_"):
                field = name.removeprefix("CFG_WORKSPACE_")
                if field not in ("ROOT", "LAYOUT", "NAME", "DEFAULT_OWNER",
                                  "AUTO_CREATE_FORK", "AUTO_REGISTER_GITHUB_DESKTOP"):
                    raise ValueError("Unsupported workspace key")
                if field in ("ROOT", "LAYOUT", "NAME", "DEFAULT_OWNER") and not isinstance(value, str):
                    raise ValueError("workspace root/layout/name/default_owner must be strings")
            if isinstance(value, dict):
                flatten(value, name + "_")
            else:
                if not isinstance(value, (str, bool, int, float)):
                    raise ValueError(f"Expected a string, boolean or number for {name}.")
                text = "true" if value is True else "false" if value is False else str(value)
                if "\0" in text:
                    raise ValueError(f"NUL characters cannot be exported for {name}.")
                expansion_bytes += len(text.encode("utf-8")) + 1
                if expansion_bytes > MAX_PROFILE_EXPANSION_BYTES:
                    raise ValueError("Profile expansion limit exceeded.")
                items.extend((name, text))
        active.remove(id(node))

    flatten(data)
    values = dict(zip(items[::2], items[1::2]))
    workspace = {field: values.get("CFG_WORKSPACE_" + field, default)
                 for field, default in (("ROOT", ""), ("LAYOUT", "auto"),
                                        ("NAME", ""), ("DEFAULT_OWNER", ""))}
    workspace.update(workspace_overrides or {})
    validate_settings(workspace["LAYOUT"], workspace["NAME"], workspace["DEFAULT_OWNER"])
    if workspace["ROOT"]:
        # Syntax only: target filesystem inspection belongs to the path resolver.
        expand_path(workspace["ROOT"], "/target-home")
    return b"".join(item.encode("utf-8") + b"\0" for item in items)


def main():
    try:
        overrides = {("ROOT" if field == "DIR" else field): os.environ["CLI_WORKSPACE_" + field]
                     for field in ("DIR", "LAYOUT", "NAME", "DEFAULT_OWNER")
                     if "CLI_WORKSPACE_" + field in os.environ}
        payload = parse_profile(sys.argv[1], overrides)
    except yaml.YAMLError:
        # PyYAML diagnostics may include private source text, tags and filenames.
        print("Invalid installer profile: Malformed or unsupported YAML; check syntax and tags.",
              file=sys.stderr)
        return 1
    except OSError:
        print("Invalid installer profile: Cannot read profile; check that it is an existing "
              "readable file and verify access permissions.", file=sys.stderr)
        return 1
    except (ValueError, RecursionError) as error:
        print(f"Invalid installer profile: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
