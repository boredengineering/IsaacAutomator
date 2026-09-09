#!/usr/bin/python3 -I
"""Scoped ECR helper: official distro binary, EC2 IAM only, no disk tokens.

No caller environment, profile, web identity, ECS credential URI, proxy or
endpoint override is forwarded. The root-managed config is public/nonsecret.
Each get executes the helper anew; the helper refreshes from EC2 metadata.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

CONFIG_PATH = Path('/etc/isaac-automator/ecr.json')
HELPER = '/usr/bin/docker-credential-ecr-login'
REGION = r'(?!cn-)[a-z]{2}-[a-z]+-[0-9]+'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ['list']:
            print('{}')
            return 0
        if argv == ['erase']:
            return 0
        if argv != ['get']:
            raise ValueError('unsupported operation')
        config = json.loads(CONFIG_PATH.read_text())
        region, host = config['region'], config['registry']
        if set(config) != {'region', 'registry'} or not isinstance(region, str) or not re.fullmatch(REGION, region):
            raise ValueError('invalid region')
        if not isinstance(host, str) or not re.fullmatch(r'[0-9]{12}\.dkr\.ecr\.' + re.escape(region) + r'\.amazonaws\.com', host):
            raise ValueError('invalid host')
        # Permit Docker's optional single line ending, not arbitrary whitespace,
        # URL prefixes, multiple lines, ports or attacker-selected hosts.
        requested = sys.stdin.read(1024)
        if requested not in (host, host + '\n'):
            raise ValueError('host not allowed')
        env = {
            'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent',
            'AWS_CONFIG_FILE': '/dev/null', 'AWS_SHARED_CREDENTIALS_FILE': '/dev/null',
            'AWS_REGION': region, 'AWS_DEFAULT_REGION': region,
            'AWS_ECR_DISABLE_CACHE': 'true', 'AWS_ECR_CACHE_DIR': '/dev/null',
            # The helper logger falls back to os.TempDir if cache/log fails.
            # Block that path too: no shared /tmp log or root symlink writes.
            'TMPDIR': '/dev/null',
            'AWS_EC2_METADATA_DISABLED': 'false',
            'AWS_EC2_METADATA_V1_DISABLED': 'true',
            'AWS_EC2_METADATA_SERVICE_ENDPOINT': 'http://169.254.169.254',
        }
        result = subprocess.run([HELPER, 'get'], input=host + '\n', env=env,
                                text=True, capture_output=True, timeout=45, check=True)
        credentials = json.loads(result.stdout)
        if (credentials.get('ServerURL') != host or credentials.get('Username') != 'AWS'
                or not isinstance(credentials.get('Secret'), str) or not credentials['Secret']):
            raise ValueError('invalid helper response')
        print(json.dumps({key: credentials[key] for key in ('ServerURL', 'Username', 'Secret')}))
        return 0
    except Exception:
        # Never print subprocess stderr, stdout, SDK exception or token material.
        print('ECR credentials unavailable; check instance IAM and registry configuration', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
