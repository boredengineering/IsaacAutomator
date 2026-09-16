"""Bounded anonymous full-commit preflight; no checkout or deployment authorization.

This fetch proves only that this HTTPS endpoint returned the exact commit object
at preflight time. It does not prove ref ancestry, target checkout, submodules,
build compatibility, publisher identity, or managed-repository qualification.
"""
import os
import re
import resource
import subprocess
import tempfile
import time

SYSTEM_GIT = '/usr/bin/git'
TOTAL_SECONDS = 30
COMMAND_SECONDS = 10
MAX_FILE_BYTES = 64 * 1024 * 1024


class PublicGitError(ValueError):
    """Sanitized failure: never expose server output, environment or credentials."""


def _limit_files():
    # Bounds each fetched pack/index/object file. The wall-clock budget separately
    # bounds the entire proof; this is not an aggregate repository-size quota.
    _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    limit = MAX_FILE_BYTES if hard == resource.RLIM_INFINITY else min(MAX_FILE_BYTES, hard)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def public_git_environment(directory):
    """Allowlist only: never merge os.environ, even for PATH or proxies."""
    env = {
        'PATH': '/usr/bin:/bin', 'HOME': directory, 'XDG_CONFIG_HOME': directory,
        'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_SYSTEM': os.devnull, 'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_CEILING_DIRECTORIES': os.path.dirname(directory),
        'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false',
        'SSH_ASKPASS': '/bin/false', 'GIT_SSH_COMMAND': '/bin/false',
        'GIT_ALLOW_PROTOCOL': 'https', 'GIT_NO_REPLACE_OBJECTS': '1',
        'GIT_ATTR_NOSYSTEM': '1', 'GIT_LFS_SKIP_SMUDGE': '1',
    }
    settings = {
        'credential.helper': '', 'credential.interactive': 'false',
        'core.askPass': '/bin/false', 'core.hooksPath': os.devnull,
        'init.templateDir': '', 'http.proxy': '', 'http.extraHeader': '',
        'http.followRedirects': 'false', 'http.sslVerify': 'true',
        'protocol.allow': 'never', 'protocol.https.allow': 'always',
        'gc.auto': '0', 'maintenance.auto': 'false',
        'fetch.recurseSubmodules': 'false', 'submodule.recurse': 'false',
    }
    env['GIT_CONFIG_COUNT'] = str(len(settings))
    for index, (key, value) in enumerate(settings.items()):
        env[f'GIT_CONFIG_KEY_{index}'] = key
        env[f'GIT_CONFIG_VALUE_{index}'] = value
    return env


def _source_repository(repository):
    label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    url = re.fullmatch(rf'https://{label}(?:\.{label})*/([A-Za-z0-9_./-]+)', repository) if isinstance(repository, str) else None
    if not url or any(part in ('', '.', '..') for part in url[1].split('/')):
        raise PublicGitError('Anonymous Git refused invalid source.')


def _runner(directory, deadline):
    env = public_git_environment(directory)

    def run(*args, output_limit=4096):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise PublicGitError('Anonymous Git exceeded budget.')
        budget = min(COMMAND_SECONDS, remaining)
        # GNU timeout kills the process group (including Git's HTTPS/pack children)
        # before subprocess.run's outer deadline; no orphaned network fetch retry.
        # Output goes to a file subject to RLIMIT_FSIZE, then a bounded read. Never
        # accumulate an arbitrary recursive tree/remote response in a Python pipe.
        with tempfile.TemporaryFile(mode='w+b') as output:
            result = subprocess.run(
                ['/usr/bin/timeout', '--signal=KILL', str(budget - 1), SYSTEM_GIT, *args],
                cwd=directory, env=env, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.DEVNULL, text=True,
                timeout=budget, preexec_fn=_limit_files,
            )
            output.seek(0)
            text = output.read(output_limit + 1)
        if (type(result.returncode) is not int or result.returncode != 0
                or len(text) > output_limit or time.monotonic() > deadline):
            raise PublicGitError('Anonymous Git failed.')
        return text.decode('utf-8').strip()
    return run


def prove_public_commit(repository, revision):
    """Fetch depth-one blobless commit, require commit type and exact FETCH_HEAD.

    Unsupported filtering/client flags fail closed, with no unfiltered/deeper
    retry. Servers may ignore filters; per-file and wall-clock budgets still
    apply. Caller must not treat this control-side preflight as target proof.
    """
    _source_repository(repository)
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        raise PublicGitError('Anonymous full-SHA commit proof refused invalid source.')
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        with tempfile.TemporaryDirectory(prefix='isaac-public-commit-') as directory:
            bare = os.path.join(directory, 'proof.git')
            run = _runner(directory, deadline)
            run('init', '--bare', '--template=', bare)
            run('--git-dir=' + bare, 'fetch', '--quiet', '--depth=1', '--filter=blob:none',
                '--no-tags', '--no-recurse-submodules', '--no-auto-maintenance',
                '--', repository, revision)
            if run('--git-dir=' + bare, 'cat-file', '-t', 'FETCH_HEAD') != 'commit':
                raise PublicGitError('Anonymous full-SHA commit proof returned non-commit object.')
            if run('--git-dir=' + bare, 'rev-parse', '--verify', 'FETCH_HEAD') != revision.lower():
                raise PublicGitError('Anonymous full-SHA commit proof returned mismatched hash.')
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise PublicGitError('Anonymous full-SHA commit proof failed.') from None
    return revision


def checkout_public_source(repository, ref, destination):
    """Fresh-only target Git boundary, never adoption/update/force/discard.

    An existing destination (including a mismatched origin or symlink) is refused
    without reading its Git configuration or running Git. Fresh partial failures
    are left in place for explicit operator review; no automatic destructive retry.
    Submodules and LFS materialization are NOT implemented or qualified here.
    """
    _source_repository(repository)
    if (not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', ref)
            or '..' in ref or any(not p or p.startswith('.') or p.endswith(('.', '.lock')) for p in ref.split('/'))):
        raise PublicGitError('Anonymous Git refused invalid ref.')
    if not isinstance(destination, str) or not os.path.isabs(destination):
        raise PublicGitError('Anonymous Git requires an absolute fresh destination.')
    if os.path.lexists(destination):
        raise PublicGitError('Refusing existing destination/origin: adoption and update are not implemented.')
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        # Exclusive mkdir refuses a newly appeared destination, too. Parents must
        # be prepared by the native consumer; never traverse/create arbitrary roots.
        os.mkdir(destination, 0o700)
        with tempfile.TemporaryDirectory(prefix='isaac-public-target-') as directory:
            run = _runner(directory, deadline)
            run('init', '--template=', destination)
            base = ('-C', destination)
            run(*base, 'remote', 'add', 'origin', repository)
            run(*base, 'fetch', '--quiet', '--depth=1', '--filter=blob:none', '--no-tags',
                '--no-recurse-submodules', '--no-auto-maintenance', '--', repository, ref)
            # Named tags may be annotated objects. Peel named refs to commits;
            # the equality check below still forbids treating a tag-object SHA
            # as an explicitly requested immutable commit SHA.
            selected = run(*base, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}')
            if (not re.fullmatch(r'[0-9a-f]{40}', selected)
                    or re.fullmatch(r'[0-9a-fA-F]{40}', ref) and selected != ref.lower()):
                raise PublicGitError('Anonymous target Git returned mismatched commit hash.')
            if run(*base, 'cat-file', '-t', selected) != 'commit':
                raise PublicGitError('Anonymous target Git returned non-commit object.')
            tree = run(*base, 'ls-tree', '-r', '--full-tree', selected, output_limit=1024 * 1024)
            for line in tree.splitlines():
                entry = re.fullmatch(r'(100644|100755|120000|160000) (blob|commit) [0-9a-f]{40}\t(.+)', line)
                if not entry:
                    raise PublicGitError('Anonymous target Git tree is malformed or over budget.')
                if entry[1] == '160000' or entry[3] == '.gitmodules':
                    raise PublicGitError('Profile target submodules are not implemented; checkout refused.')
            run(*base, 'checkout', '--detach', selected)
            if run(*base, 'rev-parse', '--verify', 'HEAD') != selected:
                raise PublicGitError('Anonymous target Git checkout hash mismatch.')
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise PublicGitError('Anonymous target Git failed; no existing checkout was adopted.') from None
    return selected


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['checkout'])
    parser.add_argument('repository')
    parser.add_argument('ref')
    parser.add_argument('destination')
    args = parser.parse_args(argv)
    try:
        checkout_public_source(args.repository, args.ref, args.destination)
    except PublicGitError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
