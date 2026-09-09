#!/usr/bin/env python3

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.python.config import list_available_profiles, load_profile_spec


class TestProfilePrivacy(unittest.TestCase):
    def test_private_profiles_are_ignored_by_git_and_docker(self):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "configs/private/example.yaml"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, "Private profiles must be gitignored")
        docker_patterns = {
            line.strip().strip("/")
            for line in (ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("configs/private", docker_patterns)

    def test_public_presets_use_upstreams_without_personal_fork_creation(self):
        upstreams = {
            "isaaclab": "https://github.com/isaac-sim/IsaacLab.git",
            "arena": "https://github.com/isaac-sim/IsaacLab-Arena.git",
            "lerobot": "https://github.com/huggingface/lerobot.git",
            "gr00t": "https://github.com/NVIDIA/Isaac-GR00T.git",
        }
        for name in ["default-profile", "full-ecosystem", "minimal-headless"]:
            with self.subTest(profile=name):
                data = yaml.safe_load(
                    (ROOT / "isaac-installer" / "config" / f"{name}.yaml").read_text()
                )
                self.assertFalse(data["workspace"].get("default_owner"))
                self.assertIs(data["workspace"].get("auto_create_fork"), False)
                for key, repo in data["repositories"].items():
                    if "repo" in repo:
                        self.assertEqual(repo["repo"], upstreams[key])

    def test_inventory_baseline_is_not_a_deployable_security_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "configs" / "profiles"
            profiles.mkdir(parents=True)
            baseline = profiles / "baseline.yaml"
            baseline.write_text("kind: workstation-baseline\nprofile_name: baseline\n")
            self.assertIsNone(load_profile_spec(str(baseline), repo_root=str(root)))
            self.assertNotIn("baseline", list_available_profiles(repo_root=str(root)))

    def test_installer_rejects_inventory_baseline_instead_of_applying_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.yaml"
            baseline.write_text("kind: workstation-baseline\nprofile_name: baseline\n")
            result = subprocess.run(
                [
                    "bash", "-c",
                    'SCRIPT_DIR="$1"; source "$1/lib/core/detect.sh"; '
                    'source "$1/lib/core/config.sh"; load_config_profile "$2"',
                    "profile-test", str(ROOT / "isaac-installer"), str(baseline),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inventory", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
