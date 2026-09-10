"""Development database isolation without starting Docker in the unit suite."""
import json
import hashlib
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / ".devcontainer/docker-compose.yml"


class Neo4jComposeTests(unittest.TestCase):
    def test_devcontainer_uses_compose_without_editor_or_agent_setting_changes(self):
        config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
        self.assertEqual(config.get("dockerComposeFile"), "docker-compose.yml")
        self.assertNotIn("build", config)
        self.assertEqual(config["service"], "app")
        self.assertEqual(config["runServices"], ["app", "automator-neo4j", "neo4j-gateway"])
        self.assertEqual(config["workspaceFolder"], "/workspaces/IsaacAutomator")
        self.assertEqual(config["shutdownAction"], "stopCompose")
        preserved = ['customizations', 'features', 'forwardPorts', 'mounts', 'name',
                     'postAttachCommand', 'postCreateCommand', 'postStartCommand', 'remoteEnv']
        digest = hashlib.sha256(json.dumps({k: config[k] for k in preserved}, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, "3274097c1c22847af99d89b20341947f977f2e2563c7253392eb87979c019a37")
        app = yaml.safe_load(COMPOSE.read_text())["services"]["app"]
        self.assertEqual(app["build"], {"context": "..", "dockerfile": ".devcontainer/Dockerfile"})
        self.assertEqual(set(app["networks"]), {"default", "graph"})
        self.assertEqual(app["depends_on"]["automator-neo4j"]["condition"], "service_healthy")
        self.assertIn("..:/workspaces/IsaacAutomator:cached", app["volumes"])
        self.assertIn("..:/app:cached", app["volumes"])
        self.assertEqual(app["environment"]["ISAAC_AUTOMATOR_NEO4J_URI"], "bolt://automator-neo4j:7687")
        self.assertNotIn("neo4j-auth:/automator-secrets", app["volumes"])

    def test_dedicated_service_is_private_and_independent(self):
        self.assertTrue(COMPOSE.is_file(), "dedicated development Compose definition is missing")
        config = yaml.safe_load(COMPOSE.read_text())
        self.assertEqual(config["name"], "isaacautomator-dev")
        service = config["services"]["automator-neo4j"]
        self.assertEqual(service["build"]["context"], "./neo4j")
        self.assertEqual(service["networks"], ["graph"])
        self.assertTrue(config["networks"]["graph"]["internal"])
        self.assertEqual(service["user"], "7474:7474")
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", service["security_opt"])
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertNotIn("ports", service)
        gateway = config["services"]["neo4j-gateway"]
        self.assertEqual(set(gateway["networks"]), {"graph", "ingress"})
        self.assertEqual(gateway["user"], "65532:65532")
        self.assertEqual(gateway["cap_drop"], ["ALL"])
        self.assertNotIn("volumes", gateway)
        self.assertEqual(gateway["depends_on"]["automator-neo4j"]["condition"], "service_healthy")
        for port in gateway["ports"]:
            self.assertEqual(port["host_ip"], "127.0.0.1")
        self.assertEqual({p["target"] for p in gateway["ports"]}, {7474, 7687})
        self.assertEqual(service["healthcheck"]["test"],
                         ["CMD", "python3", "/opt/automator-neo4j/healthcheck.py"])
        self.assertEqual(service["volumes"], ["neo4j-data:/data", "neo4j-logs:/logs",
                                               "neo4j-auth:/automator-secrets"])
        self.assertNotIn("container_name", service)
        self.assertNotIn("NEO4J_AUTH", service["environment"])
        self.assertNotIn("NEO4J_PLUGINS", service["environment"])
        self.assertNotIn("neo4j-arena", COMPOSE.read_text())


if __name__ == "__main__":
    unittest.main()
