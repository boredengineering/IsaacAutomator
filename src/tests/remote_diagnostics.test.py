#!/usr/bin/env python3
"""Unit tests for remote workstation diagnostics and non-invasive observation."""
import json
import unittest
from unittest import mock
from pathlib import Path

from src.python.remote_diagnostics import probe_cloud_workstation


class RemoteDiagnosticsTests(unittest.TestCase):
    def test_probe_cloud_workstation_success(self):
        sample_report = {
            "hostname": "isaac-workstation-studio-workstation",
            "uptime": "up 4 hours",
            "gpu": "NVIDIA RTX PRO 6000 Blackwell Server Edition, 595.91.07",
            "services": {"kasmvnc": "active", "docker": "active"},
            "listening_ports": ["0.0.0.0:8444", "0.0.0.0:22"],
            "isaac_sim": {"installed": True, "version": "6.0.1"},
            "isaac_lab": {"conda_environment": True, "framework_version": "v3"},
            "repositories": {
                "colibri": {"branch": "renan-dev", "commit": "9eca5c64"}
            }
        }

        mock_proc = mock.Mock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_report)
        mock_proc.stderr = ""

        with mock.patch("src.python.remote_diagnostics.approved_deployment_path", return_value=Path("/tmp/state/studio-workstation")), \
             mock.patch("src.python.remote_diagnostics.read_meta", return_value={"command": "./deploy-gcp"}), \
             mock.patch("src.python.remote_diagnostics.read_tf_output", side_effect=lambda name, key, **kw: "34.67.145.166" if "ip" in key else "inst-1"), \
             mock.patch("src.python.remote_diagnostics.subprocess.run", return_value=mock_proc) as mock_run:
            
            result = probe_cloud_workstation("studio-workstation")
            self.assertEqual(result["hostname"], "isaac-workstation-studio-workstation")
            self.assertEqual(result["services"]["kasmvnc"], "active")
            self.assertEqual(result["repositories"]["colibri"]["branch"], "renan-dev")
            self.assertTrue(mock_run.called)

    def test_probe_cloud_workstation_failure(self):
        mock_proc = mock.Mock()
        mock_proc.returncode = 255
        mock_proc.stdout = ""
        mock_proc.stderr = "Connection timed out"

        with mock.patch("src.python.remote_diagnostics.approved_deployment_path", return_value=Path("/tmp/state/studio-workstation")), \
             mock.patch("src.python.remote_diagnostics.read_meta", return_value={"command": "./deploy-gcp"}), \
             mock.patch("src.python.remote_diagnostics.read_tf_output", side_effect=lambda name, key, **kw: "34.67.145.166" if "ip" in key else "inst-1"), \
             mock.patch("src.python.remote_diagnostics.subprocess.run", return_value=mock_proc):
            
            with self.assertRaises(RuntimeError) as ctx:
                probe_cloud_workstation("studio-workstation")
            self.assertIn("Connection timed out", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
