#!/usr/bin/env bash
set -euo pipefail

# isaacsim_v3.sh (Crontab-Safe Edition)

TARGET_USER="ubuntu"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
INSTALL_DIR="$TARGET_HOME/isaacsim"
ZIP_NAME="isaacsim_510.zip"
ZIP_URL="https://download.isaacsim.omniverse.nvidia.com/isaac-sim-standalone-5.1.0-linux-x86_64.zip"

# ---- root guard -------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  echo "❌ This script must be run as root (sudo)"
  exit 1
fi

echo "▶ Installing Isaac Sim for user: $TARGET_USER"
echo "▶ Target directory: $INSTALL_DIR"

# ---- ensure user exists -----------------------------------------------------
if ! id "$TARGET_USER" &>/dev/null; then
  echo "❌ User '$TARGET_USER' does not exist"
  exit 1
fi

# ---- create install dir with correct ownership -----------------------------
mkdir -p "$INSTALL_DIR"
chown -R "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR"

# --- NEW: Escape the /root directory so cron doesn't trap post_install.sh ---
cd "$TARGET_HOME"

# ---- download as ubuntu -----------------------------------------------------
if [[ ! -f "$INSTALL_DIR/$ZIP_NAME" ]]; then
  echo "▶ Downloading Isaac Sim…"
  # --- NEW: Added -H flag to properly set $HOME ---
  sudo -H -u "$TARGET_USER" wget -q -O "$INSTALL_DIR/$ZIP_NAME" "$ZIP_URL"
else
  echo "▶ Zip already exists, skipping download"
fi

# ---- unzip as ubuntu --------------------------------------------------------
echo "▶ Extracting…"
# --- NEW: Added -H flag to properly set $HOME ---
sudo -H -u "$TARGET_USER" unzip -oq "$INSTALL_DIR/$ZIP_NAME" -d "$INSTALL_DIR"

# ---- run post_install as ubuntu --------------------------------------------
if [[ -x "$INSTALL_DIR/post_install.sh" ]]; then
  echo "▶ Running post_install.sh as $TARGET_USER"
  # --- NEW: Added -H flag to properly set $HOME ---
  sudo -H -u "$TARGET_USER" bash "$INSTALL_DIR/post_install.sh"
else
  echo "❌ post_install.sh not found or not executable"
  exit 1
fi

echo "✅ Isaac Sim installed successfully for user '$TARGET_USER'"