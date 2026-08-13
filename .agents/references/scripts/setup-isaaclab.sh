#!/usr/bin/env bash
set -euo pipefail

# setup-isaaclab_v9.sh (Adding IsaacLab checkout specific version)

# --- Configuration ---
TARGET_USER="ubuntu"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
WORKDIR="$TARGET_HOME"
ISAACSIM_PATH="$TARGET_HOME/isaacsim"
ISAACLAB_DIR="$WORKDIR/IsaacLab"
CONDA_ENV_NAME="isaaclab"
ISAACLAB_VERSION="v2.3.2"

# --- Root guard ---
if [[ "$EUID" -ne 0 ]]; then
  echo "❌ This script must be run as root (sudo)"
  exit 1
fi

# --- System dependencies ---
echo "▶ Installing system dependencies"
apt-get update -y
apt-get install -y --no-install-recommends git cmake build-essential

# --- Repo Setup ---
cd "$TARGET_HOME"
if [[ ! -d "$ISAACLAB_DIR/.git" ]]; then
  echo "▶ Cloning IsaacLab repository"
  sudo -H -u "$TARGET_USER" git clone https://github.com/isaac-sim/IsaacLab.git "$ISAACLAB_DIR"
fi

echo "▶ Checking out version: $ISAACLAB_VERSION"
# We run this as the target user to maintain correct file ownership
sudo -H -u "$TARGET_USER" bash -c "
  cd '$ISAACLAB_DIR'
  git fetch --all --tags
  git checkout '$ISAACLAB_VERSION'
"

SYMLINK_PATH="$ISAACLAB_DIR/_isaac_sim"
if [[ ! -L "$SYMLINK_PATH" ]]; then
  echo "▶ Creating _isaac_sim symlink"
  sudo -H -u "$TARGET_USER" ln -s "$ISAACSIM_PATH" "$SYMLINK_PATH"
fi

# --- Environment Setup (The Fix) ---
echo "▶ Setting up Conda and installing Isaac Lab extensions"

# Use QUOTED Heredoc to protect 'awk' and internal variables
sudo -H -u "$TARGET_USER" bash <<'EOF'
set -euo pipefail

# 1. Force environment identity to prevent 'unknown' error
export SHELL=/bin/bash
export TERM=xterm-256color
export USER="ubuntu"
export HOME="/home/ubuntu"
export ISAACLAB_DIR="/home/ubuntu/IsaacLab"
export CONDA_ENV_NAME="isaaclab"

# 2. Load Conda
source /opt/conda/etc/profile.d/conda.sh
cd "$ISAACLAB_DIR"

# 3. Zombie Environment Guard (Fixed AWK syntax)
ENV_HEALTHY=false
if conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME"; then
  echo "▶ Conda environment '$CONDA_ENV_NAME' exists. Checking health..."
  
  if conda run -n "$CONDA_ENV_NAME" python --version &>/dev/null; then
    echo "▶ Environment is healthy."
    ENV_HEALTHY=true
  else
    echo "▶ Detected broken environment! Removing for a clean slate..."
    conda env remove -n "$CONDA_ENV_NAME" -y || true
    rm -rf "/opt/conda/envs/$CONDA_ENV_NAME"
  fi
fi

# 4. Create environment
if [ "$ENV_HEALTHY" = false ]; then
  echo "▶ Creating conda environment: $CONDA_ENV_NAME"
  # Force SHELL identity into the internal wrapper
  SHELL=/bin/bash ./isaaclab.sh --conda "$CONDA_ENV_NAME"
fi

# --- FIX: Pre-install critical build tools ---
CURRENT_GIT_VER=$(git describe --tags --abbrev=0 2>/dev/null || git rev-parse --abbrev-ref HEAD)
echo "▶ Detected IsaacLab version in folder: $CURRENT_GIT_VER"

if [[ "$CURRENT_GIT_VER" == "v2.3.2" ]]; then
  echo "▶ Patching build tools to prevent flatdict errors..."
  conda run -n "$CONDA_ENV_NAME" python -m pip install pip==23.0
  conda run -n "$CONDA_ENV_NAME" python -m pip install setuptools==65.0.0
  conda run -n "$CONDA_ENV_NAME" python -m pip install flatdict
else
  echo "▶ Version is $CURRENT_GIT_VER. Skipping legacy patches (standard install)."
fi

# 5. Build extensions
echo "▶ Building extensions (This may take 10+ minutes)..."
# Force the use of the conda-specific python for the install
conda run -n "$CONDA_ENV_NAME" ./isaaclab.sh -i

# 6. Post-Installation Health Check
echo "▶ Running Post-Install Verification..."
# Use conda run to ensure we are actually hitting the environment we just built
if conda run -n "$CONDA_ENV_NAME" python -c "import torch; print('PyTorch Version:', torch.__version__)" &>/dev/null; then
    echo "✅ Verification Passed: PyTorch is successfully installed in $CONDA_ENV_NAME."
else
    echo "❌ Verification Failed: torch not found in environment '$CONDA_ENV_NAME'."
    # Debug: show where python is pointing
    conda run -n "$CONDA_ENV_NAME" which python
    exit 1
fi
EOF

echo "✅ Isaac Lab installation complete version $ISAACLAB_VERSION"