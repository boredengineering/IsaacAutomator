#!/usr/bin/env python3
"""Run the profile workflow's offline suites with clean homes and honest exits.

No test discovery imports cloud commands. Each explicitly listed suite owns its
synthetic fixture boundaries. This is not the entire repository/GPU acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    'installer_profile_contract', 'installer_workspace_contract', 'installer_discovery',
    'installer_safe_preview', 'installer_discovery_cli', 'installer_sandbox_regression',
    'installer_named_safety', 'workstation_profile', 'workstation_profile_command',
    'profile_privacy', 'deploy_command', 'deploy_fork_transport', 'deployer',
    'artifact_registry', 'distribution_profile', 'installer_desired_profile',
    'workstation_profile_extensions', 'installer_metadata_readers', 'profile_adapters',
    'profile_adapter_transport', 'installer_action_plan', 'installer_managed_apply',
    'installer_profile_read_boundary', 'installer_profile_workflow', 'remote_development',
    'remote_development_command', 'remote_development_entry', 'file_transfer',
    'installer_plan_evidence', 'installer_report_writer', 'installer_output_entry',
    'installer_migration_preview', 'installer_target_observation', 'sync_supervisor',
    'selected_transfer', 'public_artifact', 'profile_public_preflight',
    'installer_runtime_consumers', 'profile_ansible_runtime_consumers',
    'installer_export_conflict',
    'dataset_lock', 'installer_writer_history',
    'managed_pure_validation',
    'profile_sha_proof', 'profile_packer_transport', 'installer_pin_conformance',
    'installer_consumer_agreement', 'installer_legacy_actions',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suites', nargs='*', help='Optional names from the explicit offline suite list.')
    args = parser.parse_args()
    if any(name not in SUITES for name in args.suites):
        parser.error('Unknown offline suite selection.')
    selected = args.suites or SUITES
    log_dir = Path(tempfile.mkdtemp(prefix='isaac-profile-tests-'))
    results = []
    for name in selected:
        with tempfile.TemporaryDirectory(prefix='isaac-test-home-') as home:
            env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': home, 'PYTHONPATH': str(ROOT),
                   'PYTHONDONTWRITEBYTECODE': '1', 'APP_DIR': str(ROOT), 'LANG': 'C.UTF-8'}
            try:
                completed = subprocess.run([sys.executable, '-B', str(ROOT / 'src/tests' / (name + '.test.py'))],
                                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
                text, status = completed.stdout + completed.stderr, completed.returncode
            except subprocess.TimeoutExpired:
                text, status = 'Suite exceeded 180-second limit.\n', 124
            log = log_dir / (name + '.log')
            log.write_text(text)
            count = re.search(r'Ran (\d+) tests?', text)
            skipped = re.search(r'skipped=(\d+)', text)
            tests = int(count[1]) if count else 0
            row = dict(suite=name, exit_code=status, tests=tests,
                       skipped=int(skipped[1]) if skipped else 0, log=str(log),
                       passed=status == 0 and tests > 0)
            results.append(row)
            print(json.dumps(row), flush=True)
            (log_dir / 'results.json').write_text(json.dumps(results, indent=2))
    failed = [r['suite'] for r in results if not r['passed']]
    print(json.dumps(dict(suites=len(results), tests=sum(r['tests'] for r in results),
                          skipped=sum(r['skipped'] for r in results), failed_suites=failed,
                          results=str(log_dir / 'results.json'))))
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
