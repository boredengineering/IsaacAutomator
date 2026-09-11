"""noVNC endpoint tests with synthetic metadata; never open a tunnel/browser."""
import importlib.machinery
import importlib.util
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from click.testing import CliRunner


class NoVNCTests(unittest.TestCase):
    def load(self, *, iap=True):
        loader = importlib.machinery.SourceFileLoader('test_novnc_command', str(Path(__file__).resolve().parents[2] / 'novnc'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        module: Any = importlib.util.module_from_spec(spec)
        with mock.patch('src.python.utils.deployments', return_value=['fixture']):
            loader.exec_module(module)
        module.deployments = lambda: ['fixture']
        self.outputs = {'cloud': 'gcp', 'iap_enabled': 'true' if iap else 'false',
                        'isaac_workstation_ip': 'IAP_ONLY' if iap else '192.0.2.10',
                        'isaac_workstation_vm_id': 'projects/fixture-project/zones/us-central1-a/instances/fixture-vm'}
        module.read_tf_output = mock.Mock(side_effect=lambda name, key, **kwargs: self.outputs.get(key, ''))
        module.read_meta = mock.Mock(return_value={'params': {'project': 'fixture-project', 'zone': 'us-central1-a', 'enable_iap_only': iap},
                                                   'input_params': {'vnc_password': 'synthetic-password-never-in-url'}})
        return module

    def test_iap_uses_loopback_tunnel_and_never_prints_password(self):
        command = self.load()
        with mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 7)) as run:
            result = CliRunner().invoke(command.main, ['fixture'])
        self.assertEqual(result.exit_code, 7, (result.output, result.exception))
        self.assertIn('http://127.0.0.1:6080/', result.output)
        self.assertNotIn('synthetic-password', result.output)
        self.assertNotIn('IAP_ONLY', result.output)
        self.assertEqual(run.call_args.args[0], ['gcloud', 'compute', 'start-iap-tunnel', 'fixture-vm', '6080',
                         '--local-host-port=127.0.0.1:6080', '--project=fixture-project', '--zone=us-central1-a', '--quiet'])

    def test_missing_or_wrong_scope_never_opens_tunnel(self):
        for value in ('', 'projects/other-project/zones/us-central1-a/instances/fixture-vm'):
            command = self.load()
            self.outputs['isaac_workstation_vm_id'] = value
            with mock.patch('subprocess.run') as run:
                result = CliRunner().invoke(command.main, ['fixture'])
            self.assertNotEqual(result.exit_code, 0)
            run.assert_not_called()

    def test_public_url_omits_password_and_rejects_non_ip(self):
        command = self.load(iap=False)
        with mock.patch.object(command.os.path, 'exists', return_value=False):
            result = CliRunner().invoke(command.main, ['fixture'])
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        self.assertIn('http://192.0.2.10:6080/', result.output)
        self.assertNotIn('password=', result.output)
        self.outputs['isaac_workstation_ip'] = 'IAP_ONLY'
        with mock.patch.object(command.os.path, 'exists', return_value=False):
            invalid = CliRunner().invoke(command.main, ['fixture'])
        self.assertNotEqual(invalid.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
