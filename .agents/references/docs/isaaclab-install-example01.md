## 1. Isaac Sim Installation

First, create and enter the installation directory:

```bash
mkdir ~/isaacsim
cd ~/isaacsim
```

**Download and Unzip Isaac Sim**
*(Note: You can choose between version 5.1.0 or 6.0.1. The commands below download both, but you typically only need one.)*

```bash
# Download versions
wget -O isaacsim_510.zip 'https://download.isaacsim.omniverse.nvidia.com/isaac-sim-standalone-5.1.0-linux-x86_64.zip'
wget -O isaacsim_601.zip 'https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.0.1-linux-x86_64.zip'

# Unzip versions
unzip isaacsim_510.zip
unzip isaacsim_601.zip
```

**Run Post-Installation Scripts**

```bash
./post_install.sh
./warmup.sh
```

---

## 2. Environment Variables & Verification

To avoid the overhead of finding the Isaac Sim installation directory every time, export the following environment variables to your terminal:

```bash
# Isaac Sim root directory
export ISAACSIM_PATH="${HOME}/isaacsim"

# Isaac Sim python executable
export ISAACSIM_PYTHON_EXE="${ISAACSIM_PATH}/python.sh"
```

**Verify the Installation**

```bash
# Check that the simulator runs as expected (pass "--help" to see all options)
${ISAACSIM_PATH}/isaac-sim.sh

# Check that the python path is set correctly
${ISAACSIM_PYTHON_EXE} -c "print('Isaac Sim configuration is now complete.')"

# Check that Isaac Sim can be launched from a standalone Python script
${ISAACSIM_PYTHON_EXE} ${ISAACSIM_PATH}/standalone_examples/api/isaacsim.core.api/add_cubes.py
```

> **ATTENTION:** If you have been using a previous version of Isaac Sim, you need to run the following command for the first time after installation to remove all old user data and cached variables:
> ```bash
> ${ISAACSIM_PATH}/isaac-sim.sh --reset-user
> ```

---

## 3. Installing Isaac Lab

**Clone the Repository and Create a Symbolic Link**

```bash
# Clone the repository
git clone https://github.com/isaac-sim/IsaacLab.git

# Enter the cloned repository
cd IsaacLab

# Create a symbolic link to your Isaac Sim installation
ln -s ${ISAACSIM_PATH} _isaac_sim
```

**Set Up the Conda Environment**

```bash
# Create the conda environment (using custom name 'isaaclab')
./isaaclab.sh --conda isaaclab

# Activate the environment before proceeding
conda activate isaaclab
```

**Install Dependencies (Linux Only)**

```bash
# These dependencies are needed by robomimic
sudo apt install cmake build-essential
```

**Install Isaac Lab Extensions**

```bash
# Iterates over all extensions in the source directory and installs them using pip (--editable)
./isaaclab.sh --install
```

---

## 4. Verifying Isaac Lab & Training

**Verify Isaac Lab Installation**

```bash
# Option 1: Using the isaaclab.sh executable
./isaaclab.sh -p scripts/tutorials/00_sim/create_empty.py

# Option 2: Using Python directly in your active virtual environment
python scripts/tutorials/00_sim/create_empty.py
```

**Train a Robot!**
*(Note: If you have aliased `./isaaclab.sh` to `isaaclab`, you can use the commands below)*

```bash
# Train Ant
isaaclab -p scripts/reinforcement_learning/rsl_rl/train.py --task=Isaac-Ant-v0 --headless
isaaclab -p scripts/reinforcement_learning/rsl_rl/play.py --task=Isaac-Ant-v0 --num_envs 32

# Train Anymal
isaaclab -p scripts/reinforcement_learning/rsl_rl/train.py --task=Isaac-Velocity-Rough-Anymal-C-v0 --headless
isaaclab -p scripts/reinforcement_learning/rsl_rl/play.py --task=Isaac-Velocity-Rough-Anymal-C-v0 --num_envs 32
```
