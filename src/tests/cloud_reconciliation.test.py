#!/usr/bin/env python3
"""Verification of cloud profile and local host profile reconciliation."""
import importlib.machinery
import unittest
from unittest import mock
from pathlib import Path
from click.testing import CliRunner

from src.python.workstation_profile import resolve_profile
from src.python.profile_adapters import render_profile
from src.python.config import c as config, load_profile_spec


class TestCloudReconciliation(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.cloud_ecosystem_path = self.root / "configs" / "workstations" / "cloud-ecosystem.yaml"
        self.studio_profile_path = self.root / "configs" / "profiles" / "studio-enterprise.yaml"

    def test_cloud_ecosystem_yaml_exists(self):
        self.assertTrue(self.cloud_ecosystem_path.exists())
        self.assertTrue(self.studio_profile_path.exists())

    def test_cloud_ecosystem_renders_for_ansible(self):
        profile = resolve_profile(self.cloud_ecosystem_path)
        report = render_profile(profile, 'ansible', '/home/ubuntu')
        self.assertTrue(report['render_supported'])
        self.assertEqual(report['blockers'], [])
        
        artifact = report['artifact']
        self.assertTrue(artifact['profile_isaacsim_archive_enabled'])
        self.assertEqual(artifact['isaacsim_version'], '6.0.1')
        self.assertEqual(artifact['isaaclab_git_checkpoint'], 'v3.0.0-beta2')
        self.assertEqual(artifact['isaaclab_arena_git_checkpoint'], 'release/0.3.0-prerelease')
        self.assertTrue(artifact['install_gr00t'])
        self.assertEqual(artifact['gr00t_git_checkpoint'], '51d4c89f72fda44cbf77285c6a8114b52676b8a1')
        self.assertTrue(artifact['install_lerobot'])
        self.assertEqual(artifact['lerobot_git_checkpoint'], 'v0.4.3')
        self.assertEqual(artifact['profile_lab_architecture'], 'sm_120')
        self.assertEqual(artifact['profile_lab_torch'], '2.10.0+cu128')
        self.assertEqual(artifact['profile_lab_cuda_runtime'], '12.8')
        self.assertEqual(artifact['conda_python_version'], '3.12')
        self.assertIn('profile_gr00t_serving', artifact)
        self.assertEqual(artifact['profile_gr00t_serving']['serving']['port'], 5561)
        self.assertEqual(artifact['profile_gr00t_serving']['serving']['embodiment'], 'NEW_EMBODIMENT')

    def test_cloud_ecosystem_renders_for_local_host(self):
        profile = resolve_profile(self.cloud_ecosystem_path)
        report = render_profile(profile, 'local', '/home/ubuntu')
        self.assertTrue(report['render_supported'])
        self.assertEqual(report['blockers'], [])

        artifact = report['artifact']
        self.assertEqual(artifact['simulation']['isaacsim']['version'], '6.0.1')
        self.assertEqual(artifact['simulation']['isaacsim']['source_type'], 'standalone')
        self.assertEqual(artifact['repositories']['isaaclab']['tag'], 'v3.0.0-beta2')
        self.assertEqual(artifact['repositories']['arena']['tag'], 'release/0.3.0-prerelease')
        self.assertEqual(artifact['repositories']['gr00t']['tag'], '51d4c89f72fda44cbf77285c6a8114b52676b8a1')
        self.assertEqual(artifact['repositories']['lerobot']['tag'], 'v0.4.3')
        self.assertEqual(artifact['runtimes']['lab']['python'], '3.12')
        self.assertEqual(artifact['runtimes']['lab']['architecture'], 'sm_120')
        self.assertIn('gr00t_serving', artifact)

    def test_studio_enterprise_profile_adoption(self):
        loader = importlib.machinery.SourceFileLoader('deploy_gcp', str(self.root / 'deploy-gcp'))
        mod = loader.load_module()

        captured = []
        def capture_cb(**params):
            captured.append(mod.GCPDeployer(params, mod.config))

        cmd = mod.DeployGCPCommand('deploy-gcp', callback=capture_cb)
        runner = CliRunner()
        result = runner.invoke(cmd, [
            '--deployment-name', 'reconciled-studio',
            '--project', 'test-project',
            '--zone', 'us-central1-a',
            '--profile', str(self.studio_profile_path),
            '--existing', 'replace',
        ])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(len(captured) > 0)
        
        deployer = captured[0]
        deployer.validate_configuration()
        self.assertEqual(deployer.params.get('isaac_workstation_instance_type'), 'g4-standard-48')
        self.assertEqual(deployer.params.get('isaac_workstation_gpu_count'), '1')
        self.assertEqual(deployer.params.get('remote_desktop'), 'nomachine,novnc')
        self.assertTrue(deployer.params.get('flex_start'))
        self.assertTrue(deployer.params.get('enable_iap_only'))
        
        report = deployer.software_profile_report()
        self.assertTrue(report['render_supported'])
        self.assertEqual(deployer.params['software_profile']['name'], 'cloud-ecosystem')
        self.assertEqual(report['artifact']['profile_lab_architecture'], 'sm_120')

    def test_example_workstation_profile_renders(self):
        example_path = self.root / "configs" / "workstations" / "example-workstation.yaml"
        self.assertTrue(example_path.exists())
        profile = resolve_profile(example_path)
        report = render_profile(profile, 'ansible', '/home/ubuntu')
        self.assertTrue(report['render_supported'])
        self.assertEqual(report['blockers'], [])
        self.assertEqual(report['artifact']['workspace_dir'], '/home/ubuntu/Documents/GitHub/Robotics')

    def test_boredengineering_dev_profile_renders(self):
        bored_path = self.root / "configs" / "workstations" / "boredengineering-dev.yaml"
        self.assertTrue(bored_path.exists())
        profile = resolve_profile(bored_path)
        
        ansible_report = render_profile(profile, 'ansible', '/home/ubuntu')
        self.assertTrue(ansible_report['render_supported'])
        self.assertEqual(ansible_report['blockers'], [])
        art = ansible_report['artifact']
        self.assertEqual(art['workspace_dir'], '/home/ubuntu/Documents/GitHub/BoredEngineer')
        self.assertEqual(art['isaaclab_arena_git_repo'], 'https://github.com/boredengineering/IsaacLab-Arena.git')
        self.assertEqual(art['isaaclab_arena_git_checkpoint'], 'dev/0.3.0-prerelease')
        self.assertEqual(art['isaaclab_git_repo'], 'https://github.com/boredengineering/IsaacLab.git')
        self.assertEqual(art['isaaclab_git_checkpoint'], 'dev/0.3.0-prerelease')
        self.assertEqual(art['gr00t_git_repo'], 'https://github.com/boredengineering/Isaac-GR00T.git')
        self.assertEqual(art['gr00t_git_checkpoint'], '51d4c89f72fda44cbf77285c6a8114b52676b8a1')
        self.assertEqual(art['lerobot_git_repo'], 'https://github.com/boredengineering/lerobot.git')
        self.assertEqual(art['lerobot_git_checkpoint'], 'v0.4.3')
        self.assertEqual(art['profile_lab_architecture'], 'sm_120')
        self.assertEqual(art['profile_gr00t_serving']['serving']['port'], 5561)

        local_report = render_profile(profile, 'local', '/home/ubuntu')
        self.assertTrue(local_report['render_supported'])
        self.assertEqual(local_report['blockers'], [])
        self.assertEqual(local_report['artifact']['workspace']['name'], 'BoredEngineer')


if __name__ == '__main__':
    unittest.main()
