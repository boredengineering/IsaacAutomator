#!/usr/bin/env bash
set -euo pipefail

############################
# CONFIG
############################
ANSIBLE_USER="ubuntu"
HOME_DIR="/home/${ANSIBLE_USER}"
CONDA_ENV_NAME="gr00t"
LEROBOT_VERSION="v0.4.3"

log() { echo -e "\n>>> $*\n"; }

# Helper to ensure conda commands work in subshell
init_conda() {
    local conda_path
    conda_path=$(sudo -u "$ANSIBLE_USER" -i conda info --base)
    source "$conda_path/etc/profile.d/conda.sh"
}

############################
# PRE-REQUISITES (APT)
############################
log "Installing system dependencies for FFmpeg and Video"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libavdevice-dev

############################
# HUGGINGFACE CLI
############################
log "Installing Huggingface CLI"
if ! sudo -u "$ANSIBLE_USER" command -v huggingface-cli &> /dev/null; then
    sudo -u "$ANSIBLE_USER" -i bash -c "curl -LsSf https://hf.co/cli/install.sh | bash"
fi

############################
# LEROBOT SETUP
############################
log "Cloning LeRobot (${LEROBOT_VERSION})"
if [ ! -d "$HOME_DIR/lerobot" ]; then
    sudo -u "$ANSIBLE_USER" git clone https://github.com/huggingface/lerobot.git "$HOME_DIR/lerobot"
    cd "$HOME_DIR/lerobot"
    sudo -u "$ANSIBLE_USER" git checkout "$LEROBOT_VERSION"
fi

############################
# CONDA ENVIRONMENT
############################
log "Creating Conda environment: ${CONDA_ENV_NAME}"
init_conda

if ! sudo -u "$ANSIBLE_USER" -i conda info --envs | grep -q "$CONDA_ENV_NAME"; then
    sudo -u "$ANSIBLE_USER" -i conda create -y -n "$CONDA_ENV_NAME" python=3.10
fi

log "Installing FFmpeg in Conda"
sudo -u "$ANSIBLE_USER" -i conda install -y -n "$CONDA_ENV_NAME" ffmpeg -c conda-forge

############################
# INSTALL LEROBOT
############################
log "Installing LeRobot in editable mode"
# sudo -u "$ANSIBLE_USER" -i bash -c "conda activate $CONDA_ENV_NAME && cd $HOME_DIR/lerobot && pip install -e ."

sudo -u "$ANSIBLE_USER" -i conda run -n "$CONDA_ENV_NAME" --cwd "$HOME_DIR/lerobot" pip install -e .

############################
# ISAAC-GR00T SETUP
############################
log "Cloning Isaac-GR00T"
if [ ! -d "$HOME_DIR/Isaac-GR00T" ]; then
    sudo -u "$ANSIBLE_USER" git clone https://github.com/NVIDIA/Isaac-GR00T "$HOME_DIR/Isaac-GR00T"
fi

log "Verifying Isaac-GR00T pyproject.toml"
SOURCE_TOML="$HOME_DIR/pyproject.toml"
TARGET_TOML="$HOME_DIR/Isaac-GR00T/pyproject.toml"

if [ -f "$SOURCE_TOML" ]; then
    if ! cmp -s "$SOURCE_TOML" "$TARGET_TOML"; then
        log "Updating pyproject.toml to match source"
        cp "$SOURCE_TOML" "$TARGET_TOML"
        chown "$ANSIBLE_USER:$ANSIBLE_USER" "$TARGET_TOML"
    fi
else
    log "Warning: Source pyproject.toml not found at $HOME_DIR, skipping replacement"
fi

############################
# INSTALL ISAAC-GR00T
############################
log "Installing Isaac-GR00T in editable mode"
# sudo -u "$ANSIBLE_USER" -i bash -c "conda activate $CONDA_ENV_NAME && cd $HOME_DIR/Isaac-GR00T && pip install -e . --no-build-isolation"

sudo -u "$ANSIBLE_USER" -i conda run -n "$CONDA_ENV_NAME" --cwd "$HOME_DIR/Isaac-GR00T" pip install -e . --no-build-isolation

log "Setup completed successfully."