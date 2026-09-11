"""Source-only disposable Terraform tests. Public downloads, never cloud APIs.

Usage: python3 -B src/terraform/test_drift_monitoring.py [aws|gcp|azure]
Requires existing Terraform >=1.7 (mock_provider); installs/upgrades no tools.
Copies only *.tf and tests/*.tftest.hcl; never reads state or private tfvars.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent / 'monitoring'
SELECTED = sys.argv.pop() if len(sys.argv) > 1 and sys.argv[-1] in ('aws', 'gcp', 'azure') else None


class MonitoringTests(unittest.TestCase):
    def verify(self, provider):
        source = ROOT / provider
        self.assertTrue((source / 'main.tf').is_file(), f'{provider} monitoring stack missing')
        self.assertTrue((source / 'tests/monitoring.tftest.hcl').is_file())
        terraform = shutil.which('terraform')
        if terraform is None:
            self.fail('Install-free test requires existing Terraform >=1.7')
        with tempfile.TemporaryDirectory(prefix=f'drift-{provider}-') as temp:
            target = Path(temp)
            (target / 'tests').mkdir()
            for filename in source.glob('*.tf'):
                shutil.copyfile(filename, target / filename.name)
            for filename in (source / 'tests').glob('*.tftest.hcl'):
                shutil.copyfile(filename, target / 'tests' / filename.name)
            home = target / 'empty-home'; home.mkdir()
            config = target / 'terraformrc'; config.write_text('disable_checkpoint = true\n')
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(home),
                   'TF_IN_AUTOMATION': '1', 'TF_INPUT': '0', 'CHECKPOINT_DISABLE': '1',
                   'TF_CLI_CONFIG_FILE': str(config), 'AWS_EC2_METADATA_DISABLED': 'true'}
            for args in [('init', '-backend=false', '-input=false', '-no-color'),
                         ('validate', '-no-color'), ('test', '-no-color')]:
                result = subprocess.run([terraform, *args], cwd=target, env=env,
                                        text=True, capture_output=True, timeout=300)
                print(f'[{provider}] terraform {args[0]}\n{result.stdout}{result.stderr}', flush=True)
                self.assertEqual(result.returncode, 0, f'{provider} {args[0]} failed')

    def test_aws(self):
        self.verify('aws')

    def test_gcp(self):
        self.verify('gcp')

    def test_azure(self):
        self.verify('azure')


if __name__ == '__main__':
    unittest.main(defaultTest=f'MonitoringTests.test_{SELECTED}' if SELECTED else None)
