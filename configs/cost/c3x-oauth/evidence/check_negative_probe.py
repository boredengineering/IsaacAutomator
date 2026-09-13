"""Exercise compiled C3X probe fail-closed paths without real credentials."""
import json
import subprocess
import sys
from pathlib import Path

binary = sys.argv[1]
base = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp/isaac-c3x-oauth-parent/empty-home'}
cases = [
    ('explicit_opt_in', [], {}, 'opt-in required:'),
    ('missing_api_key', ['--live'], {}, 'GCP_API_KEY is required'),
    ('invalid_mode', ['--live'], {'GCP_AUTH_MODE': 'invalid-mode-marker'}, 'GCP_AUTH_MODE must be'),
    ('missing_adc', ['--live'], {'GCP_AUTH_MODE': 'adc', 'GOOGLE_APPLICATION_CREDENTIALS': '/nonexistent-private-path-marker'}, 'GCP ADC authentication failed'),
    ('invalid_quota', ['--live'], {'GCP_AUTH_MODE': 'adc', 'GCP_QUOTA_PROJECT': 'invalid\nquota'}, 'GCP_QUOTA_PROJECT must be'),
]
receipts = []
for name, args, overrides, expected in cases:
    proc = subprocess.run([binary, *args], env={**base, **overrides}, capture_output=True, text=True, timeout=15)
    passed = proc.returncode == 1 and not proc.stdout and proc.stderr.startswith(expected)
    passed = passed and all(marker not in proc.stdout + proc.stderr for marker in ('private-path-marker', 'invalid-mode-marker', 'invalid\nquota'))
    receipts.append({'case': name, 'exit_code': proc.returncode, 'passed': passed})
result = {'real_credentials_supplied': False, 'cases': receipts, 'passed': all(r['passed'] for r in receipts)}
Path(__file__).with_name('negative-probe.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
sys.exit(0 if result['passed'] else 1)
