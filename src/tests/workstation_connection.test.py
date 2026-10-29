#!/usr/bin/env python3
"""Unit tests for shared workstation connection resolver and IAP tunnel mechanics."""
import unittest
from unittest import mock
from pathlib import Path

from src.python.workstation_connection import (
    WorkstationConnectionInfo,
    ProtocolEndpoint,
    build_iap_tunnel_command,
    find_available_local_port,
    is_port_in_use,
    resolve_workstation_connection,
)


class WorkstationConnectionTests(unittest.TestCase):
    def test_gcp_iap_private_workstation_endpoints(self):
        info = WorkstationConnectionInfo(
            name="private-gcp-rig",
            cloud="gcp",
            instance_role="isaac_workstation",
            instance_name="my-blackwell-vm",
            public_ip="",
            private_ip="10.128.0.2",
            iap_enabled=True,
            oslogin_enabled=True,
            project="cybernetic-test",
            zone="us-central1-b",
            security_profile="enterprise",
            security_posture_label="Cloud IAP (Identity-Aware Proxy, Zero Public Ingress)",
        )

        self.assertTrue(info.iap_enabled)
        self.assertEqual(info.get_display_ip(), "IAP (10.128.0.2)")

        # 1. noVNC
        novnc_ep = info.get_protocol_endpoint("novnc")
        self.assertTrue(novnc_ep.supported)
        self.assertTrue(novnc_ep.requires_tunnel)
        self.assertEqual(novnc_ep.remote_port, 6080)
        self.assertEqual(novnc_ep.local_port, 6080)
        self.assertEqual(novnc_ep.target_endpoint, "http://127.0.0.1:6080/vnc.html?resize=scale")
        self.assertEqual(
            novnc_ep.tunnel_command,
            [
                "gcloud", "compute", "start-iap-tunnel", "my-blackwell-vm", "6080",
                "--local-host-port=127.0.0.1:6080",
                "--project=cybernetic-test", "--zone=us-central1-b", "--quiet"
            ]
        )

        # 1b. KasmVNC
        kasm_ep = info.get_protocol_endpoint("kasmvnc")
        self.assertTrue(kasm_ep.supported)
        self.assertTrue(kasm_ep.requires_tunnel)
        self.assertEqual(kasm_ep.remote_port, 8444)
        self.assertEqual(kasm_ep.target_endpoint, "https://127.0.0.1:8444")

        # 1c. VS Code Remote
        vscode_ep = info.get_protocol_endpoint("vscode")
        self.assertTrue(vscode_ep.supported)
        self.assertEqual(vscode_ep.target_endpoint, "vscode://vscode-remote/ssh-remote+private-gcp-rig/home/ubuntu/Documents/GitHub")

        # Custom local port for noVNC
        custom_novnc = info.get_protocol_endpoint("novnc", local_port=16080)
        self.assertEqual(custom_novnc.local_port, 16080)
        self.assertEqual(custom_novnc.target_endpoint, "http://127.0.0.1:16080/vnc.html?resize=scale")
        self.assertIn("--local-host-port=127.0.0.1:16080", custom_novnc.tunnel_command)

        # 2. NoMachine
        nomachine_ep = info.get_protocol_endpoint("nomachine")
        self.assertTrue(nomachine_ep.supported)
        self.assertTrue(nomachine_ep.requires_tunnel)
        self.assertEqual(nomachine_ep.remote_port, 4000)
        self.assertEqual(nomachine_ep.target_endpoint, "nx://127.0.0.1:4000")
        self.assertEqual(
            nomachine_ep.tunnel_command,
            [
                "gcloud", "compute", "start-iap-tunnel", "my-blackwell-vm", "4000",
                "--local-host-port=127.0.0.1:4000",
                "--project=cybernetic-test", "--zone=us-central1-b", "--quiet"
            ]
        )

        # 3. SSH
        ssh_ep = info.get_protocol_endpoint("ssh")
        self.assertTrue(ssh_ep.supported)
        self.assertTrue(ssh_ep.requires_tunnel)
        self.assertEqual(ssh_ep.target_endpoint, "./ssh private-gcp-rig")

        # 4. Sunshine (Must be unsupported over IAP due to UDP limitation)
        sunshine_ep = info.get_protocol_endpoint("sunshine")
        self.assertFalse(sunshine_ep.supported)
        self.assertEqual(sunshine_ep.target_endpoint, "UNAVAILABLE VIA IAP")
        self.assertIsNotNone(sunshine_ep.warning)
        self.assertIn("UDP", sunshine_ep.warning)

    def test_public_workstation_endpoints(self):
        info = WorkstationConnectionInfo(
            name="public-aws-rig",
            cloud="aws",
            public_ip="198.51.100.42",
            private_ip="172.31.10.5",
            iap_enabled=False,
            security_profile="simple",
            security_posture_label="Strict /32 Caller IP Filter",
        )

        self.assertFalse(info.iap_enabled)
        self.assertEqual(info.get_display_ip(), "198.51.100.42")

        novnc_ep = info.get_protocol_endpoint("novnc")
        self.assertTrue(novnc_ep.supported)
        self.assertFalse(novnc_ep.requires_tunnel)
        self.assertEqual(novnc_ep.target_endpoint, "http://198.51.100.42:6080/vnc.html?autoconnect=true&resize=remote")

        kasm_ep = info.get_protocol_endpoint("kasmvnc")
        self.assertTrue(kasm_ep.supported)
        self.assertFalse(kasm_ep.requires_tunnel)
        self.assertEqual(kasm_ep.target_endpoint, "https://198.51.100.42:8444")

        vscode_ep = info.get_protocol_endpoint("vscode")
        self.assertTrue(vscode_ep.supported)
        self.assertEqual(vscode_ep.target_endpoint, "vscode://vscode-remote/ssh-remote+ubuntu@198.51.100.42/home/ubuntu/Documents/GitHub")

        nomachine_ep = info.get_protocol_endpoint("nomachine")
        self.assertTrue(nomachine_ep.supported)
        self.assertFalse(nomachine_ep.requires_tunnel)
        self.assertEqual(nomachine_ep.target_endpoint, "nx://198.51.100.42:4000")

        sunshine_ep = info.get_protocol_endpoint("sunshine")
        self.assertTrue(sunshine_ep.supported)
        self.assertEqual(sunshine_ep.target_endpoint, "https://198.51.100.42:47990")

    def test_build_iap_tunnel_command(self):
        cmd = build_iap_tunnel_command("vm-01", 6080, 16080, "proj-1", "zone-1")
        self.assertEqual(cmd, [
            "gcloud", "compute", "start-iap-tunnel", "vm-01", "6080",
            "--local-host-port=127.0.0.1:16080",
            "--project=proj-1", "--zone=zone-1", "--quiet"
        ])

    def test_port_helpers(self):
        # Localhost port probe
        available_port = find_available_local_port(39123)
        self.assertIsInstance(available_port, int)
        self.assertGreaterEqual(available_port, 39123)
        self.assertFalse(is_port_in_use(available_port))

    def test_resolver_synthetic_gcp_iap(self):
        meta = {
            "command": "./deploy-gcp --deployment-name gcp-test --project proj-x --zone us-central1-a --iap",
            "params": {
                "deployment_name": "gcp-test",
                "project": "proj-x",
                "zone": "us-central1-a",
                "enable_iap_only": True,
                "enable_oslogin": True,
                "security_profile": "enterprise"
            }
        }
        outputs = {
            "cloud": "gcp",
            "isaac_workstation_ip": "",
            "isaac_workstation_private_ip": "10.0.0.9",
            "isaac_workstation_vm_id": "projects/proj-x/zones/us-central1-a/instances/inst-x",
            "iap_enabled": "true",
            "oslogin_enabled": "true",
        }

        with mock.patch("src.python.utils.approved_deployment_path", return_value=Path("/tmp/state/gcp-test")), \
             mock.patch("src.python.utils.read_meta", return_value=meta), \
             mock.patch("src.python.backend_runtime.load_backend_record", return_value=None), \
             mock.patch("src.python.utils.read_tf_output", side_effect=lambda name, key, **kwargs: outputs.get(key, "")):
            info = resolve_workstation_connection("gcp-test")

        self.assertEqual(info.name, "gcp-test")
        self.assertEqual(info.cloud, "gcp")
        self.assertTrue(info.iap_enabled)
        self.assertTrue(info.oslogin_enabled)
        self.assertEqual(info.instance_name, "inst-x")
        self.assertEqual(info.project, "proj-x")
        self.assertEqual(info.zone, "us-central1-a")
        self.assertEqual(info.private_ip, "10.0.0.9")
        self.assertEqual(info.public_ip, "")
        self.assertEqual(info.get_display_ip(), "IAP (10.0.0.9)")
        self.assertIn("Cloud IAP", info.security_posture_label)


if __name__ == "__main__":
    unittest.main()
