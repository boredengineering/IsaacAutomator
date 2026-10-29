"""Unit tests for model profile parser, validator, and plan generator."""
import unittest
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
        self.assertEqual(sorted(profiles), ["complete-model-zoo", "example-model"])

    def test_load_complete_model_zoo(self):
        data = load_model_profile("complete-model-zoo")
        self.assertEqual(data["model_profile_name"], "complete-model-zoo")
        self.assertEqual(data["schema_version"], "v1")
        self.assertEqual(len(data["models"]), 17)

    def test_resolve_complete_model_zoo(self):
        resolved = resolve_model_profile("complete-model-zoo", target_user="ubuntu", target_home="/home/ubuntu")
        self.assertEqual(resolved["model_profile_name"], "complete-model-zoo")
        self.assertIsNotNone(resolved["storage"])
        self.assertEqual(resolved["storage"]["physical_dir"], "/mnt/models_fast/models")
        self.assertEqual(len(resolved["models"]), 17)
        self.assertEqual(resolved["total_min_disk_gb"], 1038)
        repo_ids = [m["repo_id"] for m in resolved["models"]]
        self.assertIn("Qwen/Qwen2.5-72B-Instruct-AWQ", repo_ids)
        self.assertIn("zai-org/GLM-5.3", repo_ids)
        self.assertIn("zai-org/GLM-5.3-Flash", repo_ids)
        self.assertIn("nvidia/Cosmos-Reason2-2B", repo_ids)
        self.assertIn("nvidia/GR00T-N1.7-3B", repo_ids)
        self.assertIn("physical-intelligence/pi05_droid_jointpos", repo_ids)
        self.assertIn("nvidia/GR00T-N1.6-DROID", repo_ids)

    def test_resolve_example_model(self):
        resolved = resolve_model_profile("example-model", target_user="ubuntu", target_home="/home/ubuntu")
        self.assertEqual(resolved["model_profile_name"], "example-model")
        self.assertEqual(resolved["total_min_disk_gb"], 5)
        models = resolved["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["destination"], "/models/lerobot/diffusion_pusht")
        self.assertIn("/home/ubuntu/models/diffusion_pusht", models[0]["symlinks"])

    def test_generate_download_plan(self):
        resolved = resolve_model_profile("complete-model-zoo", target_user="ubuntu", target_home="/home/ubuntu")
        plan = generate_download_plan(resolved)
        self.assertEqual(plan["profile_name"], "complete-model-zoo")
        self.assertIn("/mnt/models_fast/models/glm-5.3-flash", plan["directories_to_create"])
        self.assertIn(("/mnt/models_fast/models", "/models"), plan["symlinks_to_create"])
        self.assertIn(("/mnt/models_fast/models/glm-5.3-flash", "/models/glm-5.3-flash"), plan["symlinks_to_create"])

        cmds = plan["download_commands"]
        self.assertEqual(len(cmds), 17)
        flash_cmd = next(c["command"] for c in cmds if c["model_name"] == "glm-5.3-flash")
        self.assertIn("HF_HUB_ENABLE_HF_TRANSFER=1", flash_cmd)
        self.assertIn("hf download zai-org/GLM-5.3-Flash", flash_cmd)
        self.assertIn("--local-dir /mnt/models_fast/models/glm-5.3-flash", flash_cmd)
        self.assertIn("--include '*.safetensors'", flash_cmd)

    def test_invalid_profile(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as tmp:
            tmp.write("invalid: true\n")
            tmp.flush()
            with self.assertRaises(ModelProfileError):
                resolve_model_profile(tmp.name)


if __name__ == "__main__":
    unittest.main()
