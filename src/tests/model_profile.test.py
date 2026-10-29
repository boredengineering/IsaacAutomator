"""Unit tests for model profile parser, validator, and plan generator."""
import unittest
from pathlib import Path
import tempfile

from src.python.model_profile import (
    list_model_profiles,
    load_model_profile,
    resolve_model_profile,
    generate_download_plan,
    ModelProfileError,
)


class TestModelProfile(unittest.TestCase):
    def test_list_model_profiles(self):
        profiles = list_model_profiles()
        self.assertIn("colibri-flash", profiles)
        self.assertIn("colibri-streaming", profiles)
        self.assertIn("example-model", profiles)
        self.assertIn("gr00t-foundation", profiles)

    def test_load_colibri_flash(self):
        data = load_model_profile("colibri-flash")
        self.assertEqual(data["model_profile_name"], "colibri-flash")
        self.assertEqual(data["schema_version"], "v1")
        self.assertGreaterEqual(len(data["models"]), 1)
        self.assertEqual(data["models"][0]["repo_id"], "zai-org/GLM-5.3-Flash")

    def test_resolve_colibri_flash(self):
        resolved = resolve_model_profile("colibri-flash", target_user="ubuntu", target_home="/home/ubuntu")
        self.assertEqual(resolved["model_profile_name"], "colibri-flash")
        self.assertEqual(resolved["total_min_disk_gb"], 190)
        models = resolved["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["destination"], "/models/glm-5.3-flash")
        self.assertIn("/models/glm-5.3", models[0]["symlinks"])

    def test_resolve_colibri_streaming(self):
        resolved = resolve_model_profile("colibri-streaming", target_user="ubuntu", target_home="/home/ubuntu")
        self.assertEqual(resolved["model_profile_name"], "colibri-streaming")
        self.assertIsNotNone(resolved["storage"])
        self.assertEqual(resolved["storage"]["physical_dir"], "/mnt/models_fast/models")
        self.assertEqual(len(resolved["models"]), 2)
        # Check sum of min disk requirements
        self.assertEqual(resolved["total_min_disk_gb"], 630)

    def test_generate_download_plan(self):
        resolved = resolve_model_profile("colibri-flash", target_user="ubuntu", target_home="/home/ubuntu")
        plan = generate_download_plan(resolved)
        self.assertEqual(plan["profile_name"], "colibri-flash")
        self.assertIn("/models/glm-5.3-flash", plan["directories_to_create"])
        self.assertIn(("/models/glm-5.3-flash", "/models/glm-5.3"), plan["symlinks_to_create"])
        
        cmds = plan["download_commands"]
        self.assertEqual(len(cmds), 1)
        cmd_str = cmds[0]["command"]
        self.assertIn("HF_HUB_ENABLE_HF_TRANSFER=1", cmd_str)
        self.assertIn("hf download zai-org/GLM-5.3-Flash", cmd_str)
        self.assertIn("--local-dir /models/glm-5.3-flash", cmd_str)
        self.assertIn("--include '*.safetensors'", cmd_str)

    def test_invalid_profile(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as tmp:
            tmp.write("invalid: true\n")
            tmp.flush()
            with self.assertRaises(ModelProfileError):
                resolve_model_profile(tmp.name)


if __name__ == "__main__":
    unittest.main()
