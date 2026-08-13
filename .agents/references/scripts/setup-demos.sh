#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# setup-demos.sh: Desktop Shortcuts & Demo Launchers Setup
# Creates ready-to-run shortcuts for Quadruped RL & IsaacLab-Arena Benchmarks
# ------------------------------------------------------------------------------

TARGET_USER="ubuntu"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
DEMOS_DIR="$TARGET_HOME/.local/share/isaac-automator-demos"
DESKTOP_DIR="$TARGET_HOME/Desktop"
ISAACLAB_DIR="$TARGET_HOME/IsaacLab"
ARENA_DIR="$TARGET_HOME/IsaacLab-Arena"

# ---- Root Guard --------------------------------------------------------------
if [[ "$EUID" -ne 0 ]]; then
  echo "❌ This script must be run as root (sudo)"
  exit 1
fi

echo "▶ Setting up Demos & Desktop Shortcuts for user: $TARGET_USER"

# ---- Create Directories ------------------------------------------------------
mkdir -p "$DEMOS_DIR" "$DESKTOP_DIR"
chown -R "$TARGET_USER:$TARGET_USER" "$DEMOS_DIR" "$DESKTOP_DIR"

# ---- 1. Quadruped Locomotion Demo Launcher -----------------------------------
cat > "$DEMOS_DIR/quadruped-locomotion.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

TARGET_HOME="$HOME"
ISAACLAB_DIR="$TARGET_HOME/IsaacLab"

source /opt/conda/etc/profile.d/conda.sh
conda activate isaaclab || source "$ISAACLAB_DIR/_isaac_sim/setup_python_env.sh"

cd "$ISAACLAB_DIR"
echo "▶ Starting Quadruped Locomotion RL Demo (ANYmal-D with RSL-RL)..."
python3 source/standalone/workflows/rsl_rl/train.py \
  --task Isaac-Velocity-Flat-Anymal-D-v0 \
  --num_envs ${NUM_ENVS:-4096} \
  --max_iterations ${MAX_ITERATIONS:-1500} \
  ${HEADLESS:+--headless}
EOF

chmod 0755 "$DEMOS_DIR/quadruped-locomotion.sh"
chown "$TARGET_USER:$TARGET_USER" "$DEMOS_DIR/quadruped-locomotion.sh"

# ---- 2. IsaacLab-Arena Benchmark Demo Launcher -----------------------------
cat > "$DEMOS_DIR/isaaclab-arena-benchmark.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

TARGET_HOME="$HOME"
ISAACLAB_DIR="$TARGET_HOME/IsaacLab"
ARENA_DIR="$TARGET_HOME/IsaacLab-Arena"

source /opt/conda/etc/profile.d/conda.sh
conda activate isaaclab || source "$ISAACLAB_DIR/_isaac_sim/setup_python_env.sh"

if [ -d "$ARENA_DIR" ]; then
  cd "$ARENA_DIR"
  echo "▶ Starting IsaacLab-Arena Multi-Agent Benchmark..."
  python3 scripts/run_arena.py --help || python3 -m isaaclab_arena --help || echo "IsaacLab-Arena ready!"
else
  echo "❌ IsaacLab-Arena directory not found at $ARENA_DIR"
  exit 1
fi
EOF

chmod 0755 "$DEMOS_DIR/isaaclab-arena-benchmark.sh"
chown "$TARGET_USER:$TARGET_USER" "$DEMOS_DIR/isaaclab-arena-benchmark.sh"

# ---- 3. Create Desktop Shortcuts --------------------------------------------
cat > "$DESKTOP_DIR/Quadruped_Locomotion_RL.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Quadruped Locomotion RL Demo
Comment=Train ANYmal-D quadruped with RSL-RL in Isaac Lab
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 $DEMOS_DIR/quadruped-locomotion.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
EOF

cat > "$DESKTOP_DIR/IsaacLab_Arena_Benchmark.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=IsaacLab-Arena Multi-Agent Benchmark
Comment=Run IsaacLab-Arena multi-agent environments & benchmarks
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 $DEMOS_DIR/isaaclab-arena-benchmark.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
EOF

chown "$TARGET_USER:$TARGET_USER" "$DESKTOP_DIR/Quadruped_Locomotion_RL.desktop" "$DESKTOP_DIR/IsaacLab_Arena_Benchmark.desktop"
chmod 0755 "$DESKTOP_DIR/Quadruped_Locomotion_RL.desktop" "$DESKTOP_DIR/IsaacLab_Arena_Benchmark.desktop"

sudo -u "$TARGET_USER" gio set "$DESKTOP_DIR/Quadruped_Locomotion_RL.desktop" metadata::trusted true || true
sudo -u "$TARGET_USER" gio set "$DESKTOP_DIR/IsaacLab_Arena_Benchmark.desktop" metadata::trusted true || true

echo "✅ Demos and desktop shortcuts setup completed successfully!"
