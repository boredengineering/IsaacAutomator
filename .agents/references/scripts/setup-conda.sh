#!/usr/bin/env bash
set -euo pipefail

# install-conda_v4.sh (Bulletproof & Crontab-Safe Edition)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
TARGET_USER="ubuntu"
CONDA_DIR="/opt/conda"
INSTALLER_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
INSTALLER_NAME="Miniforge3-Linux-x86_64.sh"
PROFILE_SCRIPT="/etc/profile.d/conda.sh"

# -----------------------------------------------------------------------------
log()  { echo "[conda-install] $1"; }
fail() { echo "[conda-install][ERROR] $1" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Root guard
# -----------------------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  fail "This script must be run as root (sudo)"
fi

if ! id "$TARGET_USER" &>/dev/null; then
  fail "Target user '$TARGET_USER' does not exist"
fi

# -----------------------------------------------------------------------------
# Idempotency & Cleanup check
# -----------------------------------------------------------------------------
if [[ -x "${CONDA_DIR}/bin/conda" ]]; then
  log "Conda already installed at ${CONDA_DIR}, skipping install."
else
  log "Conda executable not found, proceeding with installation."

  # --- Safely wipe corrupted/partial directory before installing ---
  if [[ -d "${CONDA_DIR}" ]]; then
    log "Found incomplete Conda directory. Removing ${CONDA_DIR} for a clean slate..."
    rm -rf "${CONDA_DIR}"
  fi

  log "Downloading Miniforge installer..."
  wget -q -O "${INSTALLER_NAME}" "${INSTALLER_URL}" || fail "Download failed"

  log "Running installer..."
  bash "${INSTALLER_NAME}" -b -p "${CONDA_DIR}" || fail "Installer failed"

  log "Cleaning up installer..."
  rm -f "${INSTALLER_NAME}"
fi

# -----------------------------------------------------------------------------
# Verify installation & Fix Permissions
# -----------------------------------------------------------------------------
if [[ ! -x "${CONDA_DIR}/bin/conda" ]]; then
  fail "Conda binary not found after installation"
fi

log "Conda installed at ${CONDA_DIR}"

# --- Hand ownership to target user so they can install packages ---
log "Setting ownership of ${CONDA_DIR} to ${TARGET_USER}"
chown -R "${TARGET_USER}:${TARGET_USER}" "${CONDA_DIR}"

# -----------------------------------------------------------------------------
# System-wide PATH (CRITICAL)
# -----------------------------------------------------------------------------
log "Configuring system-wide PATH"

cat > "${PROFILE_SCRIPT}" <<'EOF'
# System-wide Conda initialization
if [ -x /opt/conda/bin/conda ]; then
  export PATH="/opt/conda/bin:$PATH"
fi
EOF

chmod 644 "${PROFILE_SCRIPT}"

# -----------------------------------------------------------------------------
# Initialize conda for target user
# -----------------------------------------------------------------------------
log "Initializing conda for user '${TARGET_USER}'"

# --- NEW: Added -H flag to set $HOME properly ---
sudo -H -u "${TARGET_USER}" bash <<'EOF'
set -e
cd "$HOME" # --- NEW: Escape the /root directory

# Ensure profile.d is loaded
source /etc/profile || true

# Initialize conda (safe to re-run)
# Configure auto-yes to prevent frozen confirmation prompts
if ! grep -q "conda initialize" "$HOME/.bashrc"; then
  /opt/conda/bin/conda config --set always_yes true
  /opt/conda/bin/conda init bash
fi
EOF

# -----------------------------------------------------------------------------
# Final verification (non-root)
# -----------------------------------------------------------------------------
log "Final verification as ${TARGET_USER}"

# --- NEW: Added -H flag to set $HOME properly ---
sudo -H -u "${TARGET_USER}" bash <<'EOF'
set -e
cd "$HOME" # --- NEW: Escape the /root directory
source /etc/profile.d/conda.sh
conda --version
EOF

log "✅ Conda installation complete and usable by '${TARGET_USER}'"