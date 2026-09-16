#!/usr/bin/env python3
"""Read-only workspace naming rules, shared by profile and shell resolvers.

Initial names are ASCII, case-preserving single segments: alphanumeric first,
then letters/digits/spaces/dots/underscores/hyphens; no surrounding whitespace.
Unicode normalization/adoption and filesystem mutation are not supported here.
"""
import os
from pathlib import Path
import re
import sys
import stat
import unicodedata


def validate_segment(value, label="name"):
    if (not isinstance(value, str) or value != value.strip()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", value)):
        raise ValueError(f"workspace {label} must be an ASCII directory name beginning with "
                         "a letter/digit, using only letters, digits, internal spaces, . _ -")


def validate_settings(layout="auto", name="", owner=""):
    if layout not in ("auto", "org", "flat", "named"):
        raise ValueError("workspace layout must be auto, org, flat or named")
    if layout == "named":
        validate_segment(name)
        if owner and owner != name:
            raise ValueError("workspace name conflicts with default_owner; clear the owner explicitly")
    elif name:
        raise ValueError("workspace name requires layout named; clear the name explicitly")


def expand_path(value, home):
    if (not isinstance(value, str) or not value or value != value.strip()
            or "\\" in value or any(unicodedata.category(c).startswith("C") for c in value)):
        raise ValueError("workspace path must be nonempty without controls or surrounding whitespace")
    if value == "~" or value.startswith("~/"):
        value = home + value[1:]
    if not value.startswith("/") or value.startswith("//") or any(
            part in (".", "..") for part in value.split("/")):
        raise ValueError("workspace path must be absolute or ~/ relative, without traversal")
    path = Path(value)
    if path == Path("/"):
        raise ValueError("workspace path cannot be filesystem root")
    return path


def open_directory_nofollow(path):
    """Open component-relative handles, or None on absence; never follow links."""
    # Traversal needs search/metadata authority, not directory-list access to
    # every ancestor. Read permission is requested only on the selected inode.
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in Path(path).parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                os.close(fd)
                return None
            os.close(fd)
            fd = child
            mode = os.fstat(fd).st_mode
            if not mode & 0o444 or not mode & 0o111:
                raise ValueError('workspace directory is inaccessible; review read/search permissions')
        readable = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        os.close(fd)
        return readable
    except BaseException:
        os.close(fd)
        raise


def inspect_directory(path):
    fd = open_directory_nofollow(path)
    if fd is not None:
        os.close(fd)

def root_path(value, home):
    path = expand_path(value, home)
    inspect_directory(path)
    return path


def check_collision(path):
    check_supplied_path(path, {str(path.parent): bounded_directory_entries(path.parent)}, collision=True)


def explicit_destination(value, home):
    path = root_path(value, home)
    if path == Path(home):
        raise ValueError("workspace repository destination cannot be target home")
    check_collision(path)
    return path


def named_destination(root, name, repo):
    validate_segment(name)
    validate_segment(repo, "repository name")
    group = Path(root) / name
    inspect_directory(group)
    check_collision(group)
    target = group / repo
    inspect_directory(target)
    check_collision(target)
    return target


def extract_owner(slug):
    """GitHub spellings accepted by extract_repo_owner in the shell."""
    for pattern in (r'^https?://github\.com/([^/]+)/', r'^git@github\.com:([^/]+)/',
                    r'^([A-Za-z0-9_.-]+)/[A-Za-z0-9_.-]+$'):
        match = re.search(pattern, slug)
        if match:
            return match.group(1)
    return ""


ENTRY_LIMIT = 4096


def normalize_entries(entries):
    if entries is None:
        return {}
    if not isinstance(entries, dict) or len(entries) > ENTRY_LIMIT:
        raise ValueError("workspace directory evidence must be a bounded mapping")
    result = {}
    total = 0
    for parent, children in entries.items():
        if parent != '/':
            expand_path(parent, '')
        if not isinstance(children, (list, tuple)) or len(children) > ENTRY_LIMIT:
            raise ValueError("workspace directory entry limit exceeded")
        total += len(children)
        if total > ENTRY_LIMIT * 4:
            raise ValueError("workspace total directory evidence limit exceeded")
        listing = []
        seen = set()
        for child in children:
            child = {'name': child, 'kind': 'directory'} if isinstance(child, str) else child
            if not isinstance(child, dict) or child.get('kind') not in ('directory', 'file', 'symlink', 'other'):
                raise ValueError("workspace entry needs name and kind")
            value = child.get('name')
            # Arbitrary unrelated filesystem names are allowed, but never paths.
            if not isinstance(value, str) or not value or value in ('.', '..') or '/' in value or '\x00' in value:
                raise ValueError("workspace directory entry must be a single name")
            if value in seen:
                raise ValueError("workspace duplicate directory evidence")
            seen.add(value)
            listing.append(dict(name=value, kind=child['kind']))
        result[str(Path(parent))] = listing
    return result


def check_supplied_path(path, entries, collision=False):
    for current in (*reversed(path.parents), path):
        for entry in entries.get(str(current.parent), []):
            if entry['name'] == current.name and entry['kind'] != 'directory':
                raise ValueError("workspace path component is not a directory or is a symlink")
    if collision and any(entry['name'] != path.name and entry['name'].casefold() == path.name.casefold()
                         for entry in entries.get(str(path.parent), [])):
        raise ValueError("workspace case-only collision; select exact spelling and resolve duplicates")


def resolve_paths(*, home, repo, slug="", path_override="", root="", layout="auto",
                  name="", configured_owner="", directory_entries=None, github_desktop=False):
    """Resolve supplied intent only; no filesystem, environment or process reads.

    Missing listings are unknown, never observed absence. A listing must contain
    all immediate entries (at most 4096), not a prefiltered sample.
    """
    if (not all(isinstance(value, str) for value in (home, repo, slug, path_override, root, layout, name, configured_owner))
            or not home.startswith('/') or type(github_desktop) is not bool):
        raise ValueError('workspace requires explicit absolute home, string settings and boolean desktop availability')
    home = str(expand_path(home, ""))
    validate_settings(layout, name, configured_owner)
    validate_segment(repo, "repository name")
    entries = normalize_entries(directory_entries)
    status, reason = "resolved", "explicit destination selection"
    if path_override:
        target = expand_path(path_override, home)
        if target == Path(home):
            raise ValueError("workspace repository destination cannot be target home")
        base = group = None
    else:
        if not root:
            documents = str(Path(home) / 'Documents')
            if github_desktop or any(e == {'name': 'GitHub', 'kind': 'directory'} for e in entries.get(documents, [])):
                root = documents + '/GitHub'
            elif documents not in entries or home not in entries:
                return dict(root=None, group=None, destination=None, candidate_destination=None,
                            status='unknown', reason='default root requires supplied home/Documents entries or desktop availability',
                            filesystem_status='unknown')
            else:
                root = home + '/workspace' if any(e == {'name': 'workspace', 'kind': 'directory'}
                                                  for e in entries[home]) else home
        base = expand_path(root, home)
        group = base / name if layout == "named" else base
        if layout in ("auto", "org"):
            owner = configured_owner if not any(c in configured_owner for c in '<>') else ''
            slug_owner = extract_owner(slug)
            if not owner and slug_owner not in ('isaac-sim', 'NVIDIA', 'huggingface'):
                owner = slug_owner
            if owner:
                validate_segment(owner, "owner")
            if str(base) not in entries:
                status, reason = "unknown", "legacy owner spelling requires complete root directory entries"
            else:
                candidates = list(dict.fromkeys(c for c in (owner, slug_owner) if c))
                for candidate in candidates:
                    matches = [entry['name'] for entry in entries[str(base)]
                               if entry['kind'] == 'directory' and entry['name'].casefold() == candidate.casefold()]
                    if len(matches) > 1:
                        raise ValueError("workspace ambiguous owner spelling; resolve duplicate directories")
                    if matches:
                        owner = matches[0]
                        break
            group = base / owner if owner else base
        target = group / repo
    check_supplied_path(target, entries, collision=True)
    if group is not None:
        check_supplied_path(group, entries, collision=layout == 'named')
    return dict(root=str(base) if base else None, group=str(group) if group else None,
                destination=str(target) if status == "resolved" else None,
                candidate_destination=str(target), status=status, reason=reason,
                filesystem_status="supplied" if directory_entries is not None else "unknown")


def bounded_directory_entries(path):
    """Immediate metadata only; open every component nofollow, with a hard budget."""
    fd = open_directory_nofollow(path)
    if fd is None:
        return []
    try:
        result = []
        with os.scandir(fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > ENTRY_LIMIT:
                    raise ValueError('workspace directory inspection limit exceeded')
                mode = entry.stat(follow_symlinks=False).st_mode
                kind = ('symlink' if stat.S_ISLNK(mode) else 'directory' if stat.S_ISDIR(mode)
                        else 'file' if stat.S_ISREG(mode) else 'other')
                result.append(dict(name=entry.name, kind=kind))
        return result
    finally:
        os.close(fd)


def resolve_runtime(home, repo, slug, path_override, root, layout, name, configured_owner):
    """Runtime-only inspection seam; shell passes already selected effective values."""
    args = dict(home=home, repo=repo, slug=slug, path_override=path_override,
                root=root, layout=layout, name=name, configured_owner=configured_owner)
    # Validate before reading; explicit overrides never touch unrelated roots.
    result = resolve_paths(**args)
    entries = {}
    if not path_override and result['root']:
        entries[result['root']] = bounded_directory_entries(result['root'])
        result = resolve_paths(**args, directory_entries=entries)
    target = result['destination']
    if target is None:
        raise ValueError(result['reason'])
    path = Path(target)
    inspect_directory(path)
    # Inspect only immediate selected parents, never repository contents/.git.
    for parent in (path.parent, Path(result['root']) if result['root'] else path.parent):
        if str(parent) not in entries:
            entries[str(parent)] = bounded_directory_entries(parent)
    return resolve_paths(**args, directory_entries=entries)['destination']


def discover_runtime(home, repo, workspace=''):
    """Bounded legacy discovery, refusing multiple clones rather than first-match."""
    home = str(expand_path(home, ''))
    validate_segment(repo, 'repository name')
    documents = str(Path(home) / 'Documents/GitHub')
    cache, total = {}, 0

    def listing(path):
        nonlocal total
        if path not in cache:
            if len(cache) >= ENTRY_LIMIT:
                raise ValueError('workspace discovery directory limit exceeded')
            cache[path] = bounded_directory_entries(path)
            total += len(cache[path])
            if total > ENTRY_LIMIT * 4:
                raise ValueError('workspace discovery total entry limit exceeded')
        return cache[path]

    bases = ([str(expand_path(workspace, home))] if workspace else []) + [documents]
    bases += [str(Path(documents) / e['name']) for e in listing(documents) if e['kind'] == 'directory']
    bases += [str(Path(home) / name) for name in ('workspace', 'projects', 'dev')] + [home]
    matches = set()
    for base in dict.fromkeys(bases):
        children = [e for e in listing(base) if e['name'].casefold() == repo.casefold()]
        if len(children) > 1:
            raise ValueError('workspace ambiguous repository spelling')
        for child in children:
            if child['kind'] == 'symlink':
                raise ValueError('workspace repository discovery refuses symlinks')
            if child['kind'] != 'directory':
                continue
            target = str(Path(base) / child['name'])
            marker = next((e for e in listing(target) if e['name'] == '.git'), None)
            if marker and marker['kind'] == 'directory':
                matches.add(target)
            elif marker:
                raise ValueError('workspace .git file/symlink discovery unsupported; select explicit named destination')
    if len(matches) > 1:
        raise ValueError('workspace ambiguous existing repositories; select explicit named destination')
    return next(iter(matches), None)


def main():
    try:
        if sys.argv[1] == "settings":
            validate_settings(*sys.argv[2:])
        elif sys.argv[1] == "discover":
            destination = discover_runtime(*sys.argv[2:])
            if destination is None:
                return 1
            print(destination)
        elif sys.argv[1] == "resolve":
            print(resolve_runtime(*sys.argv[2:]))
        elif sys.argv[1] == "root":
            print(root_path(*sys.argv[2:]))
        elif sys.argv[1] == "explicit":
            print(explicit_destination(*sys.argv[2:]))
        elif sys.argv[1] == "named":
            print(named_destination(*sys.argv[2:]))
        else:
            raise ValueError("unsupported workspace operation")
    except (ValueError, OSError) as error:
        print(f"Invalid workspace: {error}", file=sys.stderr)
        return 2 if sys.argv[1] == 'discover' else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
