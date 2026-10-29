"""Unit tests for model profile parser, validator, cloud archive proposals, and plan generator."""
import unittest
import tempfile

from src.python.model_profile import (
    list_model_profiles,
    load_model_profile,
    resolve_model_profile,
    generate_download_plan,
    propose_models_bucket,
    build_bucket_labels,
    generate_bucket_readme,
    calculate_models_disk_spec,
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
        self.assertEqual(resolved["total_min_disk_gb"], 1428)
        repo_ids = [m["repo_id"] for m in resolved["models"]]
        self.assertIn("Qwen/Qwen2.5-72B-Instruct-AWQ", repo_ids)
        self.assertIn("zai-org/GLM-5.3", repo_ids)
        self.assertIn("zai-org/GLM-5.3-Flash", repo_ids)
        self.assertIn("nvidia/Cosmos-Reason2-2B", repo_ids)
        self.assertIn("nvidia/GR00T-N1.7-3B", repo_ids)
        self.assertIn("gs://openpi-assets/checkpoints/pi05_droid_jointpos", repo_ids)
        self.assertIn("nvidia/GR00T-N1.6-DROID", repo_ids)

    def test_resolve_subset_and_disk_sizing(self):
        resolved = resolve_model_profile(
            "complete-model-zoo",
            target_user="ubuntu",
            target_home="/home/ubuntu",
            selected_models=["gr00t-n1.7-3b", "cosmos-reason2-2b", "qwen2.5-vl-7b-instruct"],
        )
        self.assertEqual(len(resolved["models"]), 3)
        self.assertEqual(resolved["total_min_disk_gb"], 15 + 8 + 17)
        spec = calculate_models_disk_spec(resolved)
        self.assertEqual(spec["selected_model_count"], 3)
        self.assertEqual(spec["raw_total_gb"], 40)
        self.assertEqual(spec["recommended_disk_gb"], 100)

        full_resolved = resolve_model_profile("complete-model-zoo")
        full_spec = calculate_models_disk_spec(full_resolved)
        self.assertEqual(full_spec["raw_total_gb"], 1428)
        self.assertEqual(full_spec["recommended_disk_gb"], 1800)

    def test_propose_models_bucket_deterministic_hash(self):
        proposed = propose_models_bucket(
            cloud="gcp",
            namespace="studio",
            owner_scope="cybernetic-renan",
        )
        self.assertEqual(proposed["hash_prefix"], "c3527cbb69c601fa1dd9")
        self.assertEqual(proposed["bucket"], "isaac-models-c3527cbb69c601fa1dd9")
        self.assertEqual(proposed["uri"], "gs://isaac-models-c3527cbb69c601fa1dd9")
        self.assertEqual(proposed["labels"]["managed_by"], "isaac-automator")
        self.assertEqual(proposed["labels"]["purpose"], "ai-models-master-archive")

    def test_bucket_labels_and_readme(self):
        labels = build_bucket_labels(purpose="terraform-remote-state", namespace="studio", profile="studio-enterprise")
        self.assertEqual(labels["purpose"], "terraform-remote-state")
        self.assertEqual(labels["description"], "isaac-automator-terraform-remote-state-and-locks")

        readme = generate_bucket_readme(
            bucket_name="isaac-models-c3527cbb69c601fa1dd9",
            purpose="ai-models-master-archive",
            project="cybernetic-renan",
        )
        self.assertIn("gs://isaac-models-c3527cbb69c601fa1dd9", readme)
        self.assertIn("Permanent AI Model Zoo Master Archive", readme)

    def test_resolve_example_model(self):
        resolved = resolve_model_profile("example-model", target_user="ubuntu", target_home="/home/ubuntu")
        self.assertEqual(resolved["model_profile_name"], "example-model")
        self.assertEqual(resolved["total_min_disk_gb"], 5)
        models = resolved["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["destination"], "/models/lerobot/diffusion_pusht")
        self.assertIn("/home/ubuntu/models/diffusion_pusht", models[0]["symlinks"])

    def test_generate_download_plan_and_gcs_waterfall(self):
        resolved = resolve_model_profile("complete-model-zoo", target_user="ubuntu", target_home="/home/ubuntu")
        plan = generate_download_plan(resolved, models_bucket="isaac-models-c3527cbb69c601fa1dd9")
        self.assertEqual(plan["profile_name"], "complete-model-zoo")
        self.assertIn("/mnt/models_fast/models/glm-5.3-flash", plan["directories_to_create"])
        self.assertIn(("/mnt/models_fast/models", "/models"), plan["symlinks_to_create"])
        self.assertIn(("/mnt/models_fast/models/qwen/Qwen2.5-72B-Instruct-AWQ", "/models/Qwen2.5-72B-Instruct-AWQ"), plan["symlinks_to_create"])
        self.assertIn('export ISAAC_MODELS_BUCKET="isaac-models-c3527cbb69c601fa1dd9"', plan["env_file_content"])
        self.assertIn('export ISAAC_MODEL_GR00T_N1_7_3B_PATH="/models/gr00t-n1.7-3b"', plan["env_file_content"])

        cmds = plan["download_commands"]
        self.assertEqual(len(cmds), 17)
        flash_cmd = next(c["command"] for c in cmds if c["model_name"] == "glm-5.3-flash")
        self.assertIn("gcloud storage rsync -r 'gs://isaac-models-c3527cbb69c601fa1dd9/models/glm-5.3-flash'", flash_cmd)
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
