#!/usr/bin/python3
"""Scoped adaptation of artifact_registry_docker_config's privilege-safe writer.

ECR merges only its helper entry. Anonymous Docker Hub uses a distinct, empty
config, never the user's login. Existing auth is checked without changing it.
Each invocation configures one account, dropping root before any home access.
"""
import json
import os
from pathlib import Path
import re
import tempfile

from ansible.module_utils.basic import AnsibleModule


def configure(home, uid, gid, registry='', mode='ecr', check_mode=False):
    if mode not in ('ecr', 'anonymous', 'existing'):
        raise ValueError('invalid configuration mode')
    if mode == 'ecr' and not re.fullmatch(r'[0-9]{12}\.dkr\.ecr\.(?!cn-)[a-z]{2}-[a-z]+-[0-9]+\.amazonaws\.com', registry):
        raise ValueError('invalid ECR registry')
    # Do not "repair" user paths as root: directory swaps defeat symlink checks.
    if os.geteuid() == 0 and uid != 0:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid, uid, gid, gid):
        raise ValueError('Docker configuration must run as its owner')
    directory = Path(home) / ('.docker-isaac-anonymous' if mode == 'anonymous' else '.docker')
    path = directory / 'config.json'
    if directory.is_symlink() or path.is_symlink():
        raise ValueError('refusing symlink Docker configuration')
    if directory.exists() and not directory.is_dir():
        raise ValueError('Docker configuration directory is not a directory')
    if path.exists() and not path.is_file():
        raise ValueError('Docker configuration is not a regular file')
    try:
        existing = json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, UnicodeError):
        raise ValueError('invalid Docker configuration JSON') from None
    if not isinstance(existing, dict) or any(
        key in existing and not isinstance(existing[key], dict) for key in ('credHelpers', 'auths')
    ):
        raise ValueError('invalid Docker configuration shape')
    if mode == 'existing':
        if not path.exists():
            raise ValueError('existing auth requires preprovisioned root Docker configuration')
        return False
    merged = {}
    if mode == 'ecr':
        merged = dict(existing)
        merged['credHelpers'] = dict(existing.get('credHelpers', {}))
        merged['credHelpers'][registry] = 'isaac-ecr'
        if 'auths' in existing:
            merged['auths'] = dict(existing['auths'])
            for key in (registry, 'https://' + registry, 'https://' + registry + '/v1/'):
                merged['auths'].pop(key, None)
    changed = merged != existing or not path.exists()
    for target, permissions in ((directory, 0o700), (path, 0o600)):
        if not target.exists():
            changed = True
        else:
            stat = target.stat()
            changed |= (stat.st_mode & 0o7777, stat.st_uid, stat.st_gid) != (permissions, uid, gid)
    if check_mode or not changed:
        return changed
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    os.chown(directory, uid, gid)
    fd, temporary = tempfile.mkstemp(prefix='.config-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), uid, gid)
            json.dump(merged, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def main():
    module = AnsibleModule(argument_spec={
        'home': {'type': 'path', 'required': True},
        'uid': {'type': 'int', 'required': True},
        'gid': {'type': 'int', 'required': True},
        'registry': {'type': 'str', 'default': ''},
        'mode': {'type': 'str', 'choices': ['ecr', 'anonymous', 'existing'], 'default': 'ecr'},
    }, supports_check_mode=True)
    try:
        changed = configure(**module.params, check_mode=module.check_mode)
    except Exception:
        module.fail_json(msg='Cannot safely configure Docker; check JSON, ownership, symlinks and existing auth provisioning')
    module.exit_json(changed=changed)


if __name__ == '__main__':
    main()
