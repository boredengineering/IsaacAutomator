#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# setup-isaaclab.sh: Isaac Lab Installation Script
# Clones Isaac Lab, creates _isaac_sim symlink, installs python packages
# ------------------------------------------------------------------------------

TARGET_USER="ubuntu"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
ISAACSIM_DIR="$TARGET_HOME/IsaacSim"
ISAACLAB_DIR="$TARGET_HOME/IsaacLab"
ISAACLAB_GIT_REPO="https://github.com/isaac-sim/IsaacLab.git"
ISAACLAB_CHECKPOINT="main"

# ---- Root Guard --------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  echo "❌ This script must be run as root (sudo)"
  exit 1
fi

echo "▶ Installing Isaac Lab for user: $TARGET_USER"

if ! id "$TARGET_USER" &>/dev/null; then
  echo "❌ User '$TARGET_USER' does not exist"
  exit 1
fi

# ---- Configure Git for HTTPS -------------------------------------------------
sudo -H -u "$TARGET_USER" git config --global url."https://github.com/".insteadOf git@github.com: || true

# ---- Clone / Update Isaac Lab ------------------------------------------------
if [[ -d "$ISAACLAB_DIR/.git" ]]; then
  echo "▶ Updating existing Isaac Lab repository..."
  sudo -H -u "$TARGET_USER" bash -c "cd '$ISAACLAB_DIR' && git fetch origin && git checkout '$ISAACLAB_CHECKPOINT'"
else
  echo "▶ Cloning Isaac Lab repository ($ISAACLAB_CHECKPOINT)..."
  sudo -H -u "$TARGET_USER" git clone --depth 1 -b "$ISAACLAB_CHECKPOINT" "$ISAACLAB_GIT_REPO" "$ISAACLAB_DIR"
fi

# ---- Symlink Isaac Sim -------------------------------------------------------
if [[ -d "$ISAACSIM_DIR" ]]; then
  echo "▶ Symlinking _isaac_sim to $ISAACSIM_DIR..."
  ln -sfn "$ISAACSIM_DIR" "$ISAACLAB_DIR/_isaac_sim"
  chown -h "$TARGET_USER:$TARGET_USER" "$ISAACLAB_DIR/_isaac_sim"
else
  echo "⚠️ WARNING: Isaac Sim directory $ISAACSIM_DIR not found. Skipping _isaac_sim symlink."
fi

# ---- Install Isaac Lab -------------------------------------------------------
echo "▶ Running isaaclab.sh --install..."
sudo -H -u "$TARGET_USER" bash -c "
  cd '$ISAACLAB_DIR'
  ./isaaclab.sh --install
"

# ---- Verify Installation ----------------------------------------------------
echo "▶ Verifying Isaac Lab & PyTorch installation..."
if sudo -H -u "$TARGET_USER" bash -c "
  cd '$ISAACLAB_DIR'
  source /opt/conda/etc/profile.d/conda.sh
  conda activate isaaclab || source '$ISAACLAB_DIR/_isaac_sim/setup_python_env.sh'
  python3 -c 'import torch; print(\"PyTorch CUDA Available:\", torch.cuda.is_available())'
"; then
  echo "✅ Isaac Lab successfully installed and verified!"
else
  echo "❌ Isaac Lab verification failed."
  exit 1
fi