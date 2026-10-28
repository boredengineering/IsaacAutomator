#!/usr/bin/env python3
"""Comprehensive test suite for Dynamic Component Manifest Engine.

Verifies:
1. Open-world arbitrary component parsing, schema validation, and DAG resolution.
2. Adapter translation into profile_components manifest for Ansible.
3. Proper resolution of custom directories, runtimes, upstream remotes, and installers.
4. Validation and inventory serialization through Deployer.
"""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import yaml

from src.python.workstation_profile import (
    ProfileError,
    ComponentDAGResolver,
    resolve_profile,
    parse_profile_text,
)
from src.python.profile_adapters import render_profile
from src.python.config import c as config
from src.python.deployer import Deployer


class DynamicComponentEngineTests(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None

    def test_arbitrary_component_names_and_metadata_validation(self):
        """Verify open-world component identifiers and extended schema keys."""
        valid_profile = """
schema_version: v1alpha1
kind: workstation-profile
name: open-world-test
target: offline
extends: minimal
components:
  sim:
    enabled: true
    execution: native
    runtime: kit
    source:
      mode: standalone
      version: "6.0.1"
      url: https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.0.1-linux-x86_64.zip
      sha256: 348013c4d3ac398d40162566d0edfe4f3837a0eb5efa358ec87065f81aa68dd7
  robolab:
    enabled: true
    execution: native
    runtime: lab
    source:
      mode: git
      repository: https://github.com/boredengineering/RoboLab.git
      ref: main
    upstream: https://github.com/upstream-org/RoboLab.git
    install:
      method: editable
    desktop_shortcut:
      name: RoboLab Benchmark
      exec: /usr/local/bin/isaaclab-env python -m robolab.app
      icon: /usr/share/pixmaps/robolab.png
  custom_benchmark:
    enabled: true
    execution: native
    runtime: lab
    dependencies:
      - robolab
    source:
      mode: git
      repository: https://github.com/example/custom-benchmark.git
      ref: dev
    install:
      method: script
      command: bash setup.sh
"""
        parsed = parse_profile_text(valid_profile)
        self.assertIn('robolab', parsed['components'])
        self.assertIn('custom_benchmark', parsed['components'])
        self.assertEqual(parsed['components']['robolab']['upstream'], 'https://github.com/upstream-org/RoboLab.git')
        self.assertEqual(parsed['components']['custom_benchmark']['install']['method'], 'script')

    def test_invalid_component_keys_and_names_rejected(self):
        """Verify structural invariants reject invalid keys and bad names."""
        bad_name = """
schema_version: v1alpha1
kind: workstation-profile
name: bad-name-test
target: offline
extends: minimal
components:
  Invalid_Component_Name!:
    enabled: true
"""
        with self.assertRaises(ProfileError):
            parse_profile_text(bad_name)

        unknown_key = """
schema_version: v1alpha1
kind: workstation-profile
name: bad-key-test
target: offline
extends: minimal
components:
  my_pkg:
    enabled: true
    unsupported_property: 123
"""
        with self.assertRaises(ProfileError):
            parse_profile_text(unknown_key)

    def test_dag_resolver_topological_sort(self):
        """Verify Kahn's topological sort orders components according to declared dependencies."""
        components = [
            {'id': 'component_c', 'dependencies': ['component_b']},
            {'id': 'component_a', 'dependencies': []},
            {'id': 'component_b', 'dependencies': ['component_a']},
        ]
        ordered = ComponentDAGResolver.resolve_order(components)
        ordered_ids = [c['id'] for c in ordered]
        self.assertEqual(ordered_ids, ['component_a', 'component_b', 'component_c'])

    def test_dag_resolver_cycle_detection(self):
        """Verify Kahn's topological sort detects circular dependencies and raises ProfileError."""
        cyclic_components = [
            {'id': 'pkg_x', 'dependencies': ['pkg_y']},
            {'id': 'pkg_y', 'dependencies': ['pkg_z']},
            {'id': 'pkg_z', 'dependencies': ['pkg_x']},
        ]
        with self.assertRaises(ProfileError) as ctx:
            ComponentDAGResolver.resolve_order(cyclic_components)
        self.assertIn('Circular dependency detected', str(ctx.exception))

    def test_dynamic_dependencies_validation_enforced(self):
        """Verify _dependencies() raises ProfileError if an enabled component depends on an disabled or absent component."""
        profile_data = {
            'schema_version': 'v1alpha1',
            'kind': 'workstation-profile',
            'name': 'dep-check',
            'components': {
                'sim': {'enabled': True},
                'lab': {'enabled': True},
                'comp_child': {'enabled': True, 'dependencies': ['comp_parent']},
                'comp_parent': {'enabled': False},
            }
        }
        with self.assertRaises(ProfileError) as ctx:
            from src.python.workstation_profile import _dependencies
            _dependencies(profile_data)
        self.assertIn('components.comp_child requires enabled comp_parent', str(ctx.exception))

    def test_ansible_adapter_renders_open_world_profile_components(self):
        """Verify profile_adapters renders dynamic components into artifact['profile_components']."""
        raw_yaml = """
schema_version: v1alpha1
kind: workstation-profile
name: test-dynamic-render
target: offline
extends: minimal
workspace:
  root: ~/Documents/GitHub
  layout: named
  name: RoboticsLab
components:
  sim:
    enabled: true
    execution: native
    runtime: kit
    source:
      mode: standalone
      version: "6.0.1"
      url: https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.0.1-linux-x86_64.zip
      sha256: 348013c4d3ac398d40162566d0edfe4f3837a0eb5efa358ec87065f81aa68dd7
  lab:
    enabled: true
    execution: native
    runtime: lab
    source:
      mode: git
      repository: https://github.com/isaac-sim/IsaacLab.git
      ref: main
  robolab:
    enabled: true
    execution: native
    runtime: lab
    dependencies:
      - lab
    source:
      mode: git
      repository: https://github.com/boredengineering/RoboLab.git
      ref: dev
    upstream: https://github.com/original/RoboLab.git
    install:
      method: editable
    desktop_shortcut:
      name: RoboLab
      exec: /usr/local/bin/isaaclab-env python -m robolab
  extra_tool:
    enabled: true
    execution: native
    runtime: lab
    dependencies:
      - robolab
    source:
      mode: git
      repository: https://github.com/boredengineering/extra-tool.git
      ref: v1.0.0
    install_dir: ~/custom_tools/extra
    install:
      method: standard
"""
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as f:
            f.write(raw_yaml)
            f.flush()
            tmp_path = Path(f.name)
        try:
            resolved = resolve_profile(tmp_path)['profile']
        finally:
            tmp_path.unlink()
        report = render_profile(resolved, 'ansible', '/home/ubuntu')

        self.assertTrue(report['render_supported'], report.get('blockers'))
        self.assertEqual(len(report['blockers']), 0)

        artifact = report['artifact']
        self.assertIn('profile_components', artifact)
        profile_comps = artifact['profile_components']

        # Extra dynamic components should be present and sorted in DAG order:
        comp_ids = [c['id'] for c in profile_comps]
        self.assertEqual(comp_ids, ['robolab', 'extra_tool'])

        robolab_comp = profile_comps[0]
        self.assertEqual(robolab_comp['id'], 'robolab')
        self.assertEqual(robolab_comp['dest'], '/home/ubuntu/Documents/GitHub/RoboticsLab/RoboLab')
        self.assertEqual(robolab_comp['repository'], 'https://github.com/boredengineering/RoboLab.git')
        self.assertEqual(robolab_comp['ref'], 'dev')
        self.assertEqual(robolab_comp['upstream'], 'https://github.com/original/RoboLab.git')
        self.assertEqual(robolab_comp['install_method'], 'editable')
        self.assertEqual(robolab_comp['desktop_shortcut']['name'], 'RoboLab')

        extra_comp = profile_comps[1]
        self.assertEqual(extra_comp['id'], 'extra_tool')
        self.assertEqual(extra_comp['dest'], '/home/ubuntu/custom_tools/extra')
        self.assertEqual(extra_comp['install_method'], 'standard')

        # deploy_params must not leak open-world components to Click flags:
        self.assertNotIn('robolab', report['deploy_params'])
        self.assertNotIn('extra_tool', report['deploy_params'])

    def test_boredengineering_dev_profile_renders_successfully(self):
        """Verify configs/workstations/boredengineering-dev.yaml renders without blockers."""
        profile_path = Path(__file__).resolve().parents[2] / 'configs' / 'workstations' / 'boredengineering-dev.yaml'
        self.assertTrue(profile_path.is_file(), f"Profile file not found at {profile_path}")

        profile = resolve_profile(profile_path)['profile']
        report = render_profile(profile, 'ansible', '/home/ubuntu')

        self.assertTrue(report['render_supported'], f"Blockers: {report.get('blockers')}")
        self.assertEqual(len(report['blockers']), 0)

        # Check robolab is in profile_components:
        components = report['artifact']['profile_components']
        robolab_entries = [c for c in components if c['id'] == 'robolab']
        self.assertEqual(len(robolab_entries), 1)
        self.assertEqual(robolab_entries[0]['dest'], '/home/ubuntu/Documents/GitHub/BoredEngineer/RoboLab')
        self.assertEqual(robolab_entries[0]['repository'], 'https://github.com/boredengineering/RoboLab.git')

    def test_deployer_serializes_profile_components_to_inventory(self):
        """Verify Deployer writes profile_components and profile_components_json into inventory."""
        profile_path = Path(__file__).resolve().parents[2] / 'configs' / 'workstations' / 'boredengineering-dev.yaml'
        profile_doc = resolve_profile(profile_path)['profile']
        params = {
            'deployment_name': 'test-dep',
            'cloud': 'gcp',
            'in_china': 'no',
            'software_profile': profile_doc,
            'isaac_workstation_ip': '10.0.0.1',
            'ssh_user': 'ubuntu',
            'debug': False,
        }
        test_conf = copy.deepcopy(config)
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_conf.update(
                state_dir=str(Path(tmp_dir) / 'state'),
                ansible_dir=str(Path(__file__).resolve().parents[2] / 'src' / 'ansible'),
            )
            deployer = Deployer(params, test_conf)
            with mock.patch.object(deployer, 'require_backend', return_value=None), \
                 mock.patch.object(deployer, '_require_current_terraform_outputs', return_value=None):
                inventory_text = deployer.create_ansible_inventory(write=False)

            self.assertIn('[isaac_workstation:vars]', inventory_text)
            self.assertIn('profile_components=', inventory_text)
            self.assertIn('profile_components_json=', inventory_text)
            self.assertIn('RoboLab', inventory_text)


if __name__ == '__main__':
    unittest.main()
