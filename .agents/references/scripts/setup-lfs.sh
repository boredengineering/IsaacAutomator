#!/usr/bin/env bash
set -euo pipefail

# setup-lfs.sh v0

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TARGET_USER="ubuntu"

log() { echo -e "\n>>> [Git LFS Setup] $*"; }
fail() { echo -e "\n❌ [ERROR] $*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Pre-checks
# -----------------------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  fail "This script must be run as root (sudo)"
fi

# -----------------------------------------------------------------------------
# Install Git LFS
# -----------------------------------------------------------------------------
log "Checking for Git LFS..."

if ! command -v git-lfs &> /dev/null; then
    log "Git LFS not found. Installing via PackageCloud..."
    
    # We don't need 'sudo bash' here because the script is already running as root
    curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
    apt-get update
    apt-get install -y git-lfs
    
    log "✅ Git LFS installed successfully."
else
    log "✅ Git LFS is already installed."
fi

# -----------------------------------------------------------------------------
# Initialize Git LFS
# -----------------------------------------------------------------------------
log "Initializing Git LFS for user: $TARGET_USER"

# Run the initialization as the target user so their ~/.gitconfig is updated
sudo -H -u "$TARGET_USER" git lfs install

log "✅ Git LFS setup complete!"