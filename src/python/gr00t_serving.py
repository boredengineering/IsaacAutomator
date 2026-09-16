#!/usr/bin/env python3
"""Opt-in consumer of ONE reviewed immutable GR00T API, not support for dev.

No source selection, installation, credential lookup, service activation or
model download occurs on import. The caller must select/review the supported
pin; neither a branch name nor a fork is an authorized replacement. Hashes
attest inspected interface files only, not the entire environment or model.
"""

import argparse
import json
import sys
import hashlib
import os
from pathlib import Path
import subprocess
import re

COMMIT = '51d4c89f72fda44cbf77285c6a8114b52676b8a1'
REPOSITORY = 'https://github.com/NVIDIA/Isaac-GR00T.git'


def source_supported(source):
    """Pure fail-closed source contract; a label alone never selects main."""
    return (isinstance(source, dict)
            and not set(source) - {'mode', 'repository', 'ref', 'revision'}
            and source.get('mode') == 'git'
            and source.get('repository') == REPOSITORY
            and source.get('revision') in (None, COMMIT)
            and (source.get('revision') or source.get('ref')) == COMMIT)


# SHA-256 of exact text inspected at raw.githubusercontent.com/NVIDIA/Isaac-GR00T/
# <COMMIT>/<path>; no branch lookup or remote fetch occurs in this consumer.
INTERFACE_HASHES = {
    'gr00t/eval/run_gr00t_server.py': 'b94d8f879bc83b97120cfcf3e3c9d7a506d93f633a036474c7f60db81792705d',
    'gr00t/policy/server_client.py': 'd29d2e68e97ceae1762243315f23f22e696538da60fecd87d9a1391d20f7f1b9',
    'gr00t/policy/gr00t_policy.py': 'ad1183a3ce1ebed6cace4a9cb8c5a123e823a0760ebf46f3694639a5ad1521ec',
}


def verify_checkout(repo_dir):
    """Inspect only the caller-selected checkout; never invoke Git or repair it.

    This bounded version requires a detached checkout, as produced by an exact
    commit checkout. Linked worktrees, symbolic HEADs and modified interfaces
    require separate review and are refused rather than inferred.
    """
    root = Path(repo_dir)
    try:
        if (root / '.git/HEAD').read_text().strip() != COMMIT:
            raise ValueError('HEAD must be detached at the reviewed immutable commit')
        for name, digest in INTERFACE_HASHES.items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Inspected interface hash mismatch: ' + name)
    except OSError as exc:
        raise ValueError('Missing HEAD or inspected interface file') from exc


def _keys(value, allowed, required, label):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(label + ': missing or unsupported fields')


def _path(value):
    if (not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./ -]+', value)
            or any(part in ('.', '..') for part in value.split('/'))):
        raise ValueError('Explicit safe absolute path required')
    return str(Path(value))


def validate_config(config):
    """Pure closed-schema validation for both renderers and launchers."""
    _keys(config, ('source', 'serving', 'cache_dir'), ('source', 'serving', 'cache_dir'), 'config')
    if not source_supported(config['source']):
        raise ValueError('Selected GR00T source unsupported; no fallback to main or another ref')
    serving = config['serving']
    _keys(serving, ('enabled', 'bind', 'port', 'embodiment', 'model'),
          ('enabled', 'bind', 'port', 'embodiment', 'model'), 'serving')
    if type(serving['enabled']) is not bool or serving['bind'] != '127.0.0.1':
        raise ValueError('Only boolean serving.enabled and loopback bind are supported')
    if type(serving['port']) is not int or not 1 <= serving['port'] <= 65535:
        raise ValueError('serving.port must be an integer in 1..65535')
    if not isinstance(serving['embodiment'], str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', serving['embodiment']):
        raise ValueError('Invalid embodiment tag')
    model = serving['model']
    _keys(model, ('repository', 'ref', 'revision'), ('repository',), 'model')
    if not isinstance(model['repository'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', model['repository']):
        raise ValueError('Explicit public Hugging Face repository required')
    for key in ('ref', 'revision'):
        value = model.get(key)
        if value is not None and (not isinstance(value, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,199}', value)
                or '..' in value):
            raise ValueError('Invalid model ref/revision')
    if not (model.get('revision') or model.get('ref')):
        raise ValueError('Explicit model revision or ref required')
    _path(config['cache_dir'])


def execute(config, repo_dir, *, action='serve', activate=False, reviewed_source=False,
            allow_download=False,
            snapshot_download=None, process_run=None):
    """Consume a cached snapshot and native CLI using a fixed argv, not a shell."""
    if reviewed_source is not True:
        raise ValueError('Explicit reviewed-source acknowledgement required')
    if action not in ('serve', 'download'):
        raise ValueError('Unsupported serving action')
    if action == 'serve' and allow_download:
        raise ValueError('Model download is a separate explicit action, never implicit startup')
    if action == 'download' and (allow_download is not True or activate):
        raise ValueError('Explicit download permission required; download cannot activate serving')
    if action == 'serve' and activate is not True:
        raise ValueError('Explicit startup activation required independently of serving.enabled')
    validate_config(config)
    if config['serving']['enabled'] is not True:
        raise ValueError('serving.enabled must be true')
    repo_dir = _path(repo_dir)
    verify_checkout(repo_dir)
    serving = config['serving']
    model = serving['model']
    cache = config['cache_dir']
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path(cache) / '.runtime-home'),
           'HF_HUB_OFFLINE': '1' if action == 'serve' else '0',
           'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
           'HF_HOME': str(Path(cache) / '.hf-home'), 'HF_HUB_CACHE': cache,
           'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_ENDPOINT': 'https://huggingface.co'}
    # Standalone, single-threaded consumer. Sanitize BEFORE importing Hub so its
    # module-level environment constants cannot select ambient credentials/home.
    original_env = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        if snapshot_download is None:
            from huggingface_hub import snapshot_download
        snapshot = snapshot_download(repo_id=model['repository'],
            revision=model.get('revision') or model['ref'], cache_dir=cache,
            token=False, local_files_only=(action == 'serve'), endpoint='https://huggingface.co')
    except Exception as exc:
        raise ValueError('Public snapshot resolution failed; pre-cache locally or explicitly request download; no authentication fallback') from exc
    finally:
        os.environ.clear()
        os.environ.update(original_env)
    if (not isinstance(snapshot, str) or not Path(snapshot).is_absolute()
            or not Path(snapshot).is_dir()
            or not Path(snapshot).resolve().is_relative_to(Path(cache).resolve())):
        raise ValueError('Resolved snapshot must be an existing directory inside the selected cache')
    if action == 'download':
        return 0
    argv = [str(Path(repo_dir) / '.venv/bin/python'), '-I',
            str(Path(repo_dir) / 'gr00t/eval/run_gr00t_server.py'),
            '--host', serving['bind'], '--port', str(serving['port']),
            '--embodiment-tag', serving['embodiment'], '--model-path', str(snapshot)]
    return (process_run or subprocess.run)(argv, cwd=repo_dir, env=env, check=False).returncode


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate config key: ' + key)
        result[key] = value
    return result


def main(argv=None):
    """Explicit activation and download are distinct caller permissions.

    --config reads an explicitly selected JSON file. --config-json is the
    equivalent transport used by the self-contained Ansible launcher. Neither
    transport accepts Python, interpreter paths, shell hooks or extra argv.
    """
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('serve', 'download'))
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--config')
    inputs.add_argument('--config-json')
    parser.add_argument('--repo-dir', required=True)
    parser.add_argument('--cache-dir', help='Explicit absolute public snapshot cache override')
    parser.add_argument('--reviewed-source', action='store_true')
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--allow-download', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.config:
            with open(args.config, 'rb') as stream:
                raw = stream.read(65537)
        else:
            raw = args.config_json.encode('utf-8')
        if len(raw) > 65536:
            raise ValueError('Serving config exceeds 64 KiB')
        config = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(config, dict):
            raise ValueError('Serving config must be an object')
        if args.cache_dir is not None:
            config['cache_dir'] = _path(args.cache_dir)
        return execute(config, args.repo_dir, action=args.action, activate=args.activate,
                       reviewed_source=args.reviewed_source, allow_download=args.allow_download)
    except (ValueError, OSError) as exc:
        print('GR00T serving refused: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
