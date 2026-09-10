"""Explicit operator transport to the fixed development service, not an agent API."""
import json
from pathlib import Path
import re
import subprocess

SCHEMA = 'automator-neo4j/v1'
ROOT = Path(__file__).resolve().parents[2]


def transfer(payload, project, operation='load'):
    if operation not in {'load', 'clear'} or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
        raise ValueError('invalid projection operation or project')
    for field in ('scope', 'generation'):
        if not re.fullmatch(r'[0-9a-f]{64}', payload.get(field, '')):
            raise ValueError('invalid projection identity')
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()
    if len(encoded) > 4 * 1024 * 1024:
        raise ValueError('projection exceeds transfer budget')
    command = ['docker', 'compose', '--env-file', '/dev/null', '-f',
               str(ROOT / '.devcontainer/docker-compose.yml'), '-p', project,
               'exec', '-T', 'automator-neo4j', 'python3',
               '/opt/automator-neo4j/import_projection.py', operation]
    try:
        result = subprocess.run(command, input=encoded, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=120, check=False)
        if result.returncode or len(result.stdout) > 8192:
            raise ValueError
        receipt = json.loads(result.stdout)
        expected = 'loaded' if operation == 'load' else 'cleared'
        if (not isinstance(receipt, dict) or receipt.get('status') != expected
                or any(receipt.get(k) != payload[k] for k in ('scope', 'generation'))):
            raise ValueError
        return receipt
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError('Neo4j transfer failed or receipt unavailable') from None
