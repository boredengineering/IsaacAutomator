#!/usr/bin/env bash
# ==============================================================================
# demos.sh - Desktop Shortcuts (.desktop) and RL Demo Launchers
# ==============================================================================

check_demos() {
    local desktop_dir="${TARGET_HOME}/Desktop"
    if [[ -f "${desktop_dir}/Humanoid-Locomotion-G1.desktop" && -f "${desktop_dir}/Quadruped-Locomotion-Go2.desktop" ]]; then
        STAGE_CHECK_MSG="Desktop shortcuts for RL demos (G1, Go2, Franka) already deployed"
        return 0
    else
        STAGE_CHECK_MSG="Desktop shortcuts for RL demos missing"
        return 1
    fi
}

install_demos_and_shortcuts() {
    log_step "Installing Desktop Shortcuts and RL Demo Launchers..."

    local lab_dir="${ISAACLAB_DIR:-${TARGET_HOME}/IsaacLab}"
    local demos_dir="${TARGET_HOME}/.local/share/isaac-demos"
    local desktop_dir="${TARGET_HOME}/Desktop"

    mkdir -p "${demos_dir}" "${desktop_dir}"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${demos_dir}" "${desktop_dir}"

    # 1. Humanoid Locomotion Demo Launcher (Unitree G1 with RSL-RL)
    cat << 'HUMANOID' | sudo -u "${TARGET_USER}" tee "${demos_dir}/humanoid-locomotion.sh" >/dev/null
#!/usr/bin/env bash
set -euo pipefail
LAB_DIR="$HOME/IsaacLab"
cd "$LAB_DIR"
echo "Starting Unitree G1 Humanoid Locomotion RL Training..."
exec ./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py \
    --task Isaac-Velocity-Rough-G1-v0 \
    --num_envs 64 \
    --max_iterations 300
HUMANOID
    chmod 0755 "${demos_dir}/humanoid-locomotion.sh"

    # 2. Quadruped Locomotion Demo Launcher (Unitree Go2)
    cat << 'QUADRUPED' | sudo -u "${TARGET_USER}" tee "${demos_dir}/quadruped-locomotion.sh" >/dev/null
#!/usr/bin/env bash
set -euo pipefail
LAB_DIR="$HOME/IsaacLab"
cd "$LAB_DIR"
echo "Starting Unitree Go2 Quadruped Locomotion RL Training..."
exec ./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py \
    --task Isaac-Velocity-Rough-Unitree-Go2-v0 \
    --num_envs 64 \
    --max_iterations 300
QUADRUPED
    chmod 0755 "${demos_dir}/quadruped-locomotion.sh"

    # 3. Franka Manipulation Demo Launcher
    cat << 'FRANKA' | sudo -u "${TARGET_USER}" tee "${demos_dir}/franka-manipulation.sh" >/dev/null
#!/usr/bin/env bash
set -euo pipefail
LAB_DIR="$HOME/IsaacLab"
cd "$LAB_DIR"
echo "Starting Franka Arm Cube Lift RL Training..."
exec ./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py \
    --task Isaac-Lift-Cube-Franka-v0 \
    --num_envs 64 \
    --max_iterations 300
FRANKA
    chmod 0755 "${demos_dir}/franka-manipulation.sh"

    # Create .desktop entries on user Desktop
    cat << DESK1 | sudo -u "${TARGET_USER}" tee "${desktop_dir}/Humanoid-Locomotion-G1.desktop" >/dev/null
[Desktop Entry]
Version=1.0
Type=Application
Name=Humanoid Locomotion RL (G1)
Comment=Train Unitree G1 humanoid with RSL-RL in Isaac Lab
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 ${demos_dir}/humanoid-locomotion.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
DESK1

    cat << DESK2 | sudo -u "${TARGET_USER}" tee "${desktop_dir}/Quadruped-Locomotion-Go2.desktop" >/dev/null
[Desktop Entry]
Version=1.0
Type=Application
Name=Quadruped Locomotion RL (Go2)
Comment=Train Unitree Go2 quadruped with RSL-RL in Isaac Lab
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 ${demos_dir}/quadruped-locomotion.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
DESK2

    cat << DESK3 | sudo -u "${TARGET_USER}" tee "${desktop_dir}/Franka-Manipulation.desktop" >/dev/null
[Desktop Entry]
Version=1.0
Type=Application
Name=Franka Cube Lift RL
Comment=Train Franka robotic arm in object lifting with RSL-RL
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 ${demos_dir}/franka-manipulation.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
DESK3

    chmod 0755 "${desktop_dir}"/*.desktop
    chown "${TARGET_USER}:${TARGET_USER}" "${desktop_dir}"/*.desktop

    for icon in "${desktop_dir}"/*.desktop; do
        sudo -H -u "${TARGET_USER}" gio set "${icon}" metadata::trusted true 2>/dev/null || true
    done

    log_success "Desktop shortcuts created and marked trusted."
}
