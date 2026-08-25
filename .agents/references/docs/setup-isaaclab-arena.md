# Setup IsaacLan-Arena

Instructions to setup IsaacLab-Arena, validate and test the workflow works aiming to run the Agentic Environment Generation and Policy Evaluation.

---

IsaacLab-Arena 0.3.0-prerelease:
*   **Repository:** [IsaacLab-Arena 0.3.0-prerelease](https://github.com/isaac-sim/IsaacLab-Arena/tree/release/0.3.0-prerelease)
*   **Documentation:** [Installation Guide](https://isaac-sim.github.io/IsaacLab-Arena/release/0.3.0-prerelease/pages/quickstart/installation.html)

### Docker Installation

**Step 1: Clone the repository and initialize submodules**

```bash
git clone git@github.com:isaac-sim/IsaacLab-Arena.git
git submodule update --init --recursive
```
*Note: Cleanup when needed (if submodule cache is corrupted).*

```bash
# Step 1.1: Remove corrupted internal submodule cache and directories
rm -rf .git/modules/submodules
rm -rf submodules/IsaacLab submodules/Isaac-GR00T
git submodule deinit -f --all 2>/dev/null || true

# Step 1.2: Ensure .gitmodules specifies the official NVIDIA HTTPS endpoints
cat << 'EOF' > .gitmodules
[submodule "submodules/IsaacLab"]
path = submodules/IsaacLab
url = https://github.com/isaac-sim/IsaacLab.git
[submodule "submodules/Isaac-GR00T"]
path = submodules/Isaac-GR00T
url = https://github.com/NVIDIA/Isaac-GR00T.git
EOF

# Step 1.3: Enable submodule protocol transport
git config --global protocol.file.allow always

# Step 1.4: Synchronize remote URLs and checkout exact detached HEADs
git submodule sync
git submodule update --init --recursive

# Step 1.5: Verify clean detached HEAD status (leading space, no '+' or error)
git submodule status
```

**Step 2: Launch the docker container**

```bash
./docker/run_docker.sh
```

*The container will build (if needed) and drop you into an interactive shell.*

> **Note on Mounting:** The run docker script mounts the following directories from the host machine if they exist:
> *   **Datasets:** `$HOME/datasets` → `/datasets`
> *   **Models:** `$HOME/models` → `/models`
> *   **Evaluation:** `$HOME/eval` → `/eval`
> 
> *When mounted, a user avoids re-downloading datasets and models between container restarts, so our suggestion is to create these directories on the host machine before running the container. Note that the paths of the mounted directories are configurable — see `docker/run_docker.sh` for the full list of arguments.*

**Step 3: Optionally verify installation by running tests**

```bash
pytest -sv -m "with_cameras and not with_subprocess" isaaclab_arena/tests/
pytest -sv -m "not with_cameras and not with_subprocess" isaaclab_arena/tests/
pytest -sv -m with_subprocess isaaclab_arena/tests/
```

---

## Example Workflow: Imitation Learning

*   **Documentation:** [Imitation Learning Workflow](https://isaac-sim.github.io/IsaacLab-Arena/release/0.3.0-prerelease/pages/example_workflows/imitation_learning/index.html)

**Available Tasks:**
1.  G1 Loco-Manipulation Box Pick and Place Task
2.  Unitree G1 Static Apple-to-Plate Task
3.  GR1 Open Microwave Door Task
4.  GR1 Sequential Pick & Place and Close Door Task

### G1 Loco-Manipulation Box Pick and Place Task

**Start the IsaacLab docker container & Authenticate:**

```bash
./docker/run_docker.sh
# We store data on Hugging Face, so you’ll need log in to Hugging Face if you haven’t already.
hf auth login
```

**Create folders for data and models (Host environment):**

```bash
export DATASET_DIR=$HOME/datasets/isaaclab_arena/locomanipulation_tutorial
mkdir -p $DATASET_DIR
export MODELS_DIR=$HOME/models/isaaclab_arena/locomanipulation_tutorial
mkdir -p $MODELS_DIR
```

#### Environment Setup and Validation

**Export and Verify directories:**

```bash
# 1. Export and verify DATASET_DIR
export DATASET_DIR=$HOME/datasets/isaaclab_arena/locomanipulation_tutorial
# 2. Confirm the path is non-empty and points to the mounted volume
echo "Target directory is: $DATASET_DIR"
ls -ld "$DATASET_DIR"
```

**Download test dataset:**

```bash
hf download nvidia/Arena-G1-Loco-Manipulation-Task   arena_g1_loco_manipulation_dataset_generated_small.hdf5   --repo-type dataset   --revision arena_v0.2_lab_v3.0   --local-dir "$DATASET_DIR"
```

**Post-Download Verification:**

```bash
# Check on Container
ls -lh /datasets/isaaclab_arena/locomanipulation_tutorial

# Check on Host
ls -lh ~/datasets/isaaclab_arena/locomanipulation_tutorial/
```

**Validate Environment with Demo Replay (Inside the Container):**

```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial

python isaaclab_arena/scripts/imitation_learning/replay_demos.py   --viz kit   --device cpu   --enable_cameras   --dataset_file /datasets/isaaclab_arena/locomanipulation_tutorial/arena_g1_loco_manipulation_dataset_generated_small.hdf5   galileo_g1_locomanip_pick_and_place   --object brown_box   --embodiment g1_wbc_pink
```

---

#### Dataset Annotation & Generation

*Make sure to check the paths are correct:*

```bash
export DATASET_DIR=$HOME/datasets/isaaclab_arena/locomanipulation_tutorial
echo "Target directory is: $DATASET_DIR"
```

##### Step 1: Annotate Demonstrations

**Option A: Download Pre-annotated Dataset:**

```bash
hf download nvidia/Arena-G1-Loco-Manipulation-Task   arena_g1_loco_manipulation_dataset_annotated.hdf5   --repo-type dataset   --revision arena_v0.2_lab_v3.0   --local-dir $DATASET_DIR
```

**Option B: Annotate the dataset yourself (Inside the Container):**

```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial

python isaaclab_arena/scripts/imitation_learning/annotate_demos.py   --viz kit   --device cpu   --input_file $DATASET_DIR/arena_g1_loco_manipulation_dataset_recorded.hdf5   --output_file $DATASET_DIR/arena_g1_loco_manipulation_dataset_annotated.hdf5   --mimic   galileo_g1_locomanip_pick_and_place
```

##### Step 2: Generate Augmented Dataset

**Option A: Download Pre-generated Dataset:**

```bash
hf download nvidia/Arena-G1-Loco-Manipulation-Task   arena_g1_loco_manipulation_dataset_generated.hdf5   --repo-type dataset   --revision arena_v0.2_lab_v3.0   --local-dir $DATASET_DIR
```

**Option B: Generate the dataset yourself (Inside the Container):**

```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial

# Generate 100 demonstrations
python isaaclab_arena/scripts/imitation_learning/generate_dataset.py   --headless   --enable_cameras   --mimic   --input_file $DATASET_DIR/arena_g1_loco_manipulation_dataset_annotated.hdf5   --output_file $DATASET_DIR/arena_g1_loco_manipulation_dataset_generated.hdf5   --generation_num_trials 100   --device cpu   galileo_g1_locomanip_pick_and_place   --object brown_box   --embodiment g1_wbc_pink
```

> **ATTENTION:** Data generation takes 1-4 hours depending on your CPU/GPU. You can remove `--headless` and add `--viz kit` (before specifying the task name `galileo_g1_locomanip_pick_and_place`) to visualize during data generation.

##### Step 3: Validate Generated Dataset (Inside the Container)

```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial

python isaaclab_arena/scripts/imitation_learning/replay_demos.py   --viz kit   --device cpu   --enable_cameras   --dataset_file $DATASET_DIR/arena_g1_loco_manipulation_dataset_generated.hdf5   galileo_g1_locomanip_pick_and_place   --object brown_box   --embodiment g1_wbc_pink
```

---

#### Policy Post-Training

This workflow covers post-training an example policy using the generated dataset. Here we use **GR00T N1.6** as the base model.

##### Prerequisites

Start the isaaclab docker container:

```bash
./docker/run_docker.sh
```

Inside the container:

```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial
export MODELS_DIR=/models/isaaclab_arena/locomanipulation_tutorial

# Check on Container
ls -lh /datasets/isaaclab_arena/locomanipulation_tutorial
ls -lh /models/isaaclab_arena/locomanipulation_tutorial
```

##### Step 1: Convert to LeRobot Format

**Download Pre-converted LeRobot Dataset:**

```bash
hf download nvidia/Arena-G1-Loco-Manipulation-Task   --include lerobot/*   --repo-type dataset   --revision arena_v0.2_lab_v3.0   --local-dir $DATASET_DIR/arena_g1_loco_manipulation_dataset_generated
```

**Convert the HDF5 dataset to LeRobot format:**

```bash
python isaaclab_arena_gr00t/lerobot/convert_hdf5_to_lerobot.py   --yaml_file isaaclab_arena_gr00t/lerobot/config/g1_locomanip_config.yaml
```

##### Step 2: Post-train Policy

**Compute Requirements:**

*   **GPUs:** 8x with at least 48 GB VRAM each (e.g. L40s, GB200, etc.)
*   **System RAM:** 512 GB or more recommended — multi-GPU training with large batch sizes and multiple dataloader workers requires substantial host memory.

**Training Configuration:**

*   Base Model: GR00T-N1.6-3B (foundation model)
*   Tuned Modules: Visual backbone, projector, diffusion model
*   Frozen Modules: LLM (language model)
*   Batch Size: 96 (adjust based on GPU memory)
*   Training Steps: 20,000

To post-train the policy, open another terminal **outside** the Arena Base Docker container and `cd` to `submodules/Isaac-GR00T`:

```bash
cd submodules/Isaac-GR00T

uv run python -m torch.distributed.run --nproc_per_node=8 --standalone   gr00t/experiment/launch_finetune.py   --dataset-path ~/datasets/isaaclab_arena/locomanipulation_tutorial/arena_g1_loco_manipulation_dataset_generated/lerobot   --output-dir ~/models/isaaclab_arena/locomanipulation_tutorial   --modality-config-path ../../isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_config.py   --global-batch-size 96   --max-steps 20000   --num-gpus 8   --save-steps 5000   --save-total-limit 5   --base-model-path nvidia/GR00T-N1.6-3B   --no-tune-llm   --tune-visual   --tune-projector   --tune-diffusion-model   --dataloader-num-workers 16   --color-jitter-params brightness 0.3 contrast 0.4 saturation 0.5 hue 0.08   --embodiment-tag NEW_EMBODIMENT
```

---

#### 6. Closed-Loop Policy Inference and Evaluation

##### Prerequisites

Start the isaaclab docker container:

```bash
./docker/run_docker.sh
```

Inside the **host**:

```bash
export DATASET_DIR=$HOME/datasets/isaaclab_arena/locomanipulation_tutorial
export MODELS_DIR=$HOME/models/isaaclab_arena/locomanipulation_tutorial
```

Inside the **container**:

```bash
export DATASET_DIR=/datasets/isaaclab_arena/locomanipulation_tutorial
export MODELS_DIR=/models/isaaclab_arena/locomanipulation_tutorial

# Check on Container
ls -lh /datasets/isaaclab_arena/locomanipulation_tutorial
ls -lh /models/isaaclab_arena/locomanipulation_tutorial
```

**Download Pre-Trained Model:**

```bash
hf download   --revision gn1_6   nvidia/GN1x-Tuned-Arena-G1-Loco-Manipulation   --local-dir $MODELS_DIR/checkpoint-20000
```

##### Run GR00T Server (On HOST)

```bash
cd submodules/Isaac-GR00T

GR00T_DIT_SDPA_MODE=math TORCH_SDPA_USE_FLASH=0 USE_FLASH_ATTENTION=0 uv run python gr00t/eval/run_gr00t_server.py   --modality-config-path ../../isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_config.py   --model-path $MODELS_DIR/checkpoint-20000   --embodiment-tag NEW_EMBODIMENT   --device cuda --host 127.0.0.1 --port 5556
```

##### Step 1: Run Single Environment Evaluation (In Container)

```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy   --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/g1_locomanip_gr00t_closedloop_config.yaml   --remote_host 127.0.0.1   --remote_port 5556   --num_steps 5000   --enable_cameras   galileo_g1_locomanip_pick_and_place   --object brown_box   --embodiment g1_wbc_joint
```

##### Step 2: Run Parallel Environments Evaluation (In Container)

```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy   --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/g1_locomanip_gr00t_closedloop_config.yaml   --remote_host 127.0.0.1   --remote_port 5556   --num_steps 1200   --num_envs 5   --enable_cameras   --device cuda   --policy_device cuda   galileo_g1_locomanip_pick_and_place   --object brown_box   --embodiment g1_wbc_joint
```

---

## Agentic Environment Generation and Policy Evaluation

This is the workflow to do Agentic Environment Generation and Policy Evaluation using knowledge graph,

### Prompt to Environment Graph Spec

**1. Export API Keys & Base URLs:**

```bash
export GEMINI_API_KEY="AIzaSyYourGeminiKeyHere"
export NV_API_KEY="$GEMINI_API_KEY"
export OPENAI_API_KEY="$GEMINI_API_KEY"
export OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export NV_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export MPLCONFIGDIR=/tmp/matplotlib
```

**2. Run the environment generator:**

```bash
python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py   --mode resolve   --model "gemini-3.6-flash"   --prompt "Droid picks up the mustard bottle from the maple table and places it in the grey bin."   --out_dir /workspaces/isaaclab_arena/generated_envs/mustard_pick_and_place
```

#### Prompt to Simulation Environment

**Example 1: Droid Pick and Place**

```bash
python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py   --mode full   --model "gemini-3.6-flash"   --prompt "Droid picks up the mustard bottle from the maple table and places it in the grey bin."   --out_dir /workspaces/isaaclab_arena/generated_envs/mustard_pick_and_place
```

**Example 2: Franka Avocado Pick and Place**

```bash
python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py   --mode full   --model "gemini-3.6-flash"   --prompt "franka pick up avocado from the maple table and place it into a bowl on the table. there are other veggies on the table as distractor"   --out_dir /workspaces/isaaclab_arena/generated_envs/franka_avocado_pick_and_place
```

#### Interactive GUI Runner

Run the GUI from inside the Isaac Lab-Arena development container:

```bash
python isaaclab_arena_examples/agentic_environment_generation/gui_runner.py
```

*Open existing environment graph specs:*
```bash
# Example 1: Franka Avocado
python isaaclab_arena_examples/agentic_environment_generation/gui_runner.py   --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/franka_avocado_pick_and_place/franka_pick_avocado_into_bowl.yaml

# Example 2: Droid Mustard
python isaaclab_arena_examples/agentic_environment_generation/gui_runner.py   --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/mustard_pick_and_place/droid_pick_and_place_mustard_bottle.yaml
```

#### Run a Generated Environment

Generated environments are consumed through `--env_graph_spec_yaml`.

**Example:**

```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type zero_action   --enable_cameras   --num_steps 100   --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/mustard_pick_and_place/droid_pick_and_place_mustard_bottle.yaml
```

*The same YAML can also be built directly by the generation runner:*

```bash
python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py   --mode build   --env_graph_spec_yaml isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml   --headless
```

#### Policy Runner with Variations

*(Note: There may be issues with this specific command structure)*

```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type zero_action   --enable_cameras   isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml   light.hdr_image.enabled=true   droid_abs_joint_pos.camera_extrinsics_wrist_camera.enabled=true
```

---

### Evaluate with GR00T

Inside the **host**:
```bash
export DATASET_DIR=$HOME/datasets/isaaclab_arena/locomanipulation_tutorial
export MODELS_DIR=$HOME/models/isaaclab_arena/locomanipulation_tutorial
```

### Start the GR00T Server (Run on Host)
```bash
cd submodules/Isaac-GR00T

# For OXE_DROID
uv run python gr00t/eval/run_gr00t_server.py   --model-path nvidia/GR00T-N1.6-DROID   --embodiment-tag OXE_DROID   --device cuda --host 127.0.0.1 --port 5556

# For GR1 or G1
uv run python gr00t/eval/run_gr00t_server.py   --modality-config-path ../../isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_config.py   --model-path $MODELS_DIR/checkpoint-20000   --embodiment-tag NEW_EMBODIMENT   --device cuda --host 127.0.0.1 --port 5556
```

### Run the Generated Environment (Run on Container)

**Example 1: Run policy runner with generated environment graph spec YAML**
```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy   --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml   --remote_host 127.0.0.1   --remote_port 5556   --enable_cameras   --num_steps 1000   --env_graph_spec_yaml isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml
```

**Example 2: Add a language instruction (make the GR00T task explicit)**
```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy   --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml   --remote_host 127.0.0.1   --remote_port 5556   --enable_cameras   --num_steps 1000   --language_instruction "Pick up the mustard bottle and place it in the raisin box."   --env_graph_spec_yaml isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml
```

**Example 3: How to use with variations**
```bash
python isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy   --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml   --remote_host 127.0.0.1   --remote_port 5556   --language_instruction "Pick up the mustard bottle and place it in the grey bin."   --enable_cameras   --num_steps 1000   --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/mustard_pick_and_place/droid_pick_and_place_mustard_bottle.yaml   droid_abs_joint_pos.camera_extrinsics_wrist_camera.enabled=true
```
