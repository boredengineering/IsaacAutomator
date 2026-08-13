#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# setup-isaaclab-arena.sh: IsaacLab-Arena Installation Script
# Installs NVIDIA IsaacLab-Arena multi-agent benchmarks and environments
# ------------------------------------------------------------------------------

TARGET_USER="ubuntu"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
ISAACLAB_DIR="$TARGET_HOME/IsaacLab"
ARENA_DIR="$TARGET_HOME/IsaacLab-Arena"
ARENA_GIT_REPO="https://github.com/isaac-sim/IsaacLab-Arena.git"
ARENA_CHECKPOINT="main"

# ---- Root Guard --------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  echo "❌ This script must be run as root (sudo)"
  exit 1
fi

echo "▶ Setting up IsaacLab-Arena for user: $TARGET_USER"

# ---- Ensure Target User Exists -----------------------------------------------
if ! id "$TARGET_USER" &>/dev/null; then
  echo "❌ Target user '$TARGET_USER' does not exist"
  exit 1
fi

# ---- Ensure Isaac Lab Is Installed -----------------------------------------
if [[ ! -d "$ISAACLAB_DIR" ]]; then
  echo "❌ Isaac Lab directory ($ISAACLAB_DIR) not found. Run setup-isaaclab.sh first."
  exit 1
fi

# ---- Configure Git for HTTPS -------------------------------------------------
sudo -H -u "$TARGET_USER" git config --global url."https://github.com/".insteadOf git@github.com: || true

# ---- Clone / Update IsaacLab-Arena ------------------------------------------
if [[ -d "$ARENA_DIR/.git" ]]; then
  echo "▶ Updating existing IsaacLab-Arena repository..."
  sudo -H -u "$TARGET_USER" bash -c "cd '$ARENA_DIR' && git fetch origin && git checkout '$ARENA_CHECKPOINT' && git submodule update --init --recursive --depth 1"
else
  echo "▶ Cloning IsaacLab-Arena repository ($ARENA_CHECKPOINT)..."
  sudo -H -u "$TARGET_USER" git clone --depth 1 --recurse-submodules --shallow-submodules \
    -b "$ARENA_CHECKPOINT" "$ARENA_GIT_REPO" "$ARENA_DIR"
fi

# ---- Install IsaacLab-Arena Python Package ---------------------------------
echo "▶ Installing IsaacLab-Arena extension packages into Conda environment..."
sudo -H -u "$TARGET_USER" bash -c "
  source /opt/conda/etc/profile.d/conda.sh
  conda activate isaaclab || source '$ISAACLAB_DIR/_isaac_sim/setup_python_env.sh'
  cd '$ARENA_DIR'
  pip install -e .
"

# ---- Verify Installation ----------------------------------------------------
echo "▶ Verifying IsaacLab-Arena installation..."
if sudo -H -u "$TARGET_USER" bash -c "
  source /opt/conda/etc/profile.d/conda.sh
  conda activate isaaclab || source '$ISAACLAB_DIR/_isaac_sim/setup_python_env.sh'
  python3 -c 'import isaaclab; print(\"Isaac Lab Version:\", isaaclab.__version__)'
"; then
  echo "✅ IsaacLab-Arena successfully installed and verified!"
else
  echo "❌ IsaacLab-Arena verification failed."
  exit 1
fi
