#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# setup-isaacsim.sh: Isaac Sim Installation Script (Source / Release)
# Downloads, builds, accepts EULA, pins active GPU, and configures shortcuts
# ------------------------------------------------------------------------------

TARGET_USER="ubuntu"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
ISAACSIM_SOURCE_DIR="$TARGET_HOME/isaacsim"
ISAACSIM_LINK="$TARGET_HOME/IsaacSim"
ZIP_NAME="isaac-sim-standalone-5.1.0-linux-x86_64.zip"
ZIP_URL="https://download.isaacsim.omniverse.nvidia.com/$ZIP_NAME"

# ---- Root Guard --------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  echo "❌ This script must be run as root (sudo)"
  exit 1
fi

echo "▶ Installing Isaac Sim for user: $TARGET_USER"
echo "▶ Target directory: $ISAACSIM_SOURCE_DIR"

if ! id "$TARGET_USER" &>/dev/null; then
  echo "❌ User '$TARGET_USER' does not exist"
  exit 1
fi

mkdir -p "$ISAACSIM_SOURCE_DIR" "$TARGET_HOME/.local/share/applications"
chown -R "$TARGET_USER:$TARGET_USER" "$ISAACSIM_SOURCE_DIR" "$TARGET_HOME/.local/share/applications"

cd "$TARGET_HOME"

# ---- Download Isaac Sim Package ----------------------------------------------
if [[ ! -f "$ISAACSIM_SOURCE_DIR/$ZIP_NAME" && ! -d "$ISAACSIM_SOURCE_DIR/post_install.sh" ]]; then
  echo "▶ Downloading Isaac Sim package..."
  sudo -H -u "$TARGET_USER" wget -q --show-progress -O "$ISAACSIM_SOURCE_DIR/$ZIP_NAME" "$ZIP_URL" || true
fi

# ---- Extract & Accept EULA --------------------------------------------------
if [[ -f "$ISAACSIM_SOURCE_DIR/$ZIP_NAME" ]]; then
  echo "▶ Extracting Isaac Sim archive..."
  sudo -H -u "$TARGET_USER" unzip -oq "$ISAACSIM_SOURCE_DIR/$ZIP_NAME" -d "$ISAACSIM_SOURCE_DIR"
  sudo -H -u "$TARGET_USER" touch "$ISAACSIM_SOURCE_DIR/.eula_accepted"
fi

# ---- Create Symlink to IsaacSim ---------------------------------------------
if [[ -d "$ISAACSIM_SOURCE_DIR/_build/linux-x86_64/release" ]]; then
  ln -sfn "$ISAACSIM_SOURCE_DIR/_build/linux-x86_64/release" "$ISAACSIM_LINK"
else
  ln -sfn "$ISAACSIM_SOURCE_DIR" "$ISAACSIM_LINK"
fi
chown -h "$TARGET_USER:$TARGET_USER" "$ISAACSIM_LINK"

# ---- Run post_install.sh -----------------------------------------------------
if [[ -x "$ISAACSIM_LINK/post_install.sh" ]]; then
  echo "▶ Running post_install.sh as $TARGET_USER..."
  sudo -H -u "$TARGET_USER" bash "$ISAACSIM_LINK/post_install.sh" || true
fi

# ---- Pin Active GPU in Desktop Shortcut -------------------------------------
DESKTOP_ICON_PATH="$TARGET_HOME/.local/share/applications/IsaacSim.desktop"
if [[ -f "$DESKTOP_ICON_PATH" ]]; then
  sed -i 's/^\(Exec=.*isaac-sim\.sh\)$/\1 --\/renderer\/activeGpu=0/' "$DESKTOP_ICON_PATH" || true
  cp -f "$DESKTOP_ICON_PATH" "$TARGET_HOME/Desktop/IsaacSim.desktop" || true
  chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/Desktop/IsaacSim.desktop" || true
  chmod 0755 "$TARGET_HOME/Desktop/IsaacSim.desktop" || true
  sudo -u "$TARGET_USER" gio set "$TARGET_HOME/Desktop/IsaacSim.desktop" metadata::trusted true || true
fi

echo "✅ Isaac Sim installation completed successfully for '$TARGET_USER'!"
