#!/usr/bin/env bash
# ==============================================================================
# demos.sh - Desktop Shortcuts (.desktop) and RL Demo Launchers
# ==============================================================================

check_demos() {
    detect_target_user
    local desktop_dir="${TARGET_HOME}/Desktop"
    if [[ ! -d "${desktop_dir}" ]] || [[ "${CFG_STAGES_DEMOS:-true}" == "false" ]]; then
        STAGE_CHECK_MSG="Desktop shortcuts disabled or running in headless environment (Skipped)"
        return 0
    fi

    if [[ -f "${desktop_dir}/Humanoid-Locomotion-G1.desktop" && -f "${desktop_dir}/Arena-Benchmark-Kit.desktop" && -f "${desktop_dir}/Isaac-GR00T-Server.desktop" ]]; then
        STAGE_CHECK_MSG="Desktop shortcuts for RL and Physical AI demos (G1, Go2, Franka, Arena, GR00T) already deployed"
        return 0
    else
        STAGE_CHECK_MSG="Desktop shortcuts for demos missing or incomplete"
        return 1
    fi
}

install_demos_and_shortcuts() {
    detect_target_user
    log_step "Installing Desktop Shortcuts and Physical AI Demo Launchers (Optional)..."

    local lab_dir="${ISAACLAB_DIR:-${TARGET_HOME}/IsaacLab}"
    local arena_dir="${ARENA_DIR:-${TARGET_HOME}/Documents/GitHub/BoredEngineer/IsaacLab-Arena}"
    local gr00t_dir="${GR00T_DIR:-${TARGET_HOME}/Documents/GitHub/boredengineering/Isaac-GR00T}"
    local demos_dir="${TARGET_HOME}/.local/share/isaac-demos"
    local desktop_dir="${TARGET_HOME}/Desktop"

    mkdir -p "${demos_dir}" "${desktop_dir}"
    chown -R "${TARGET_USER}:${TARGET_USER}" "${demos_dir}" "${desktop_dir}" 2>/dev/null || true

    # 1. Humanoid Locomotion Demo Launcher (Unitree G1 with RSL-RL)
    cat << 'HUMANOID' | run_as_user_stdin "${demos_dir}/humanoid-locomotion.sh"
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
    chmod 0755 "${demos_dir}/humanoid-locomotion.sh" 2>/dev/null || true

    # 2. Quadruped Locomotion Demo Launcher (Unitree Go2)
    cat << 'QUADRUPED' | run_as_user_stdin "${demos_dir}/quadruped-locomotion.sh"
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
    chmod 0755 "${demos_dir}/quadruped-locomotion.sh" 2>/dev/null || true

    # 3. Franka Manipulation Demo Launcher
    cat << 'FRANKA' | run_as_user_stdin "${demos_dir}/franka-manipulation.sh"
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
    chmod 0755 "${demos_dir}/franka-manipulation.sh" 2>/dev/null || true

    # 4. IsaacLab-Arena Benchmark Kit GUI Launcher
    cat << 'ARENA_DEMO' | run_as_user_stdin "${demos_dir}/arena-benchmark.sh"
#!/usr/bin/env bash
set -euo pipefail
LAB_DIR="$HOME/IsaacLab"
ARENA_DIR="$(find "$HOME/Documents/GitHub" -name "IsaacLab-Arena" -type d 2>/dev/null | head -n 1 || echo "$HOME/Documents/GitHub/BoredEngineer/IsaacLab-Arena")"
if [[ -d "$ARENA_DIR" ]]; then
    cd "$ARENA_DIR"
    echo "Starting IsaacLab-Arena Visual Benchmark Rollout (cube_goal_pose)..."
    exec "$LAB_DIR/isaaclab.sh" -p isaaclab_arena/evaluation/policy_runner.py --viz kit --policy_type zero_action --num_steps 300 cube_goal_pose
else
    echo "IsaacLab-Arena directory not found at $ARENA_DIR"
    sleep 3
fi
ARENA_DEMO
    chmod 0755 "${demos_dir}/arena-benchmark.sh" 2>/dev/null || true

    # 5. NVIDIA Isaac-GR00T Policy Server Launcher
    cat << 'GR00T_SERVER' | run_as_user_stdin "${demos_dir}/gr00t-policy-server.sh"
#!/usr/bin/env bash
set -euo pipefail
GR00T_DIR="$(find "$HOME/Documents/GitHub" -name "Isaac-GR00T" -type d 2>/dev/null | head -n 1 || echo "$HOME/Documents/GitHub/boredengineering/Isaac-GR00T")"
if [[ -d "$GR00T_DIR" ]]; then
    cd "$GR00T_DIR"
    export PATH="$HOME/.cargo/bin:$PATH"
    echo "Starting NVIDIA Isaac-GR00T ZeroMQ Policy Server on Port 5555..."
    exec uv run python gr00t/eval/run_gr00t_server.py \
        --model-path nvidia/GR00T-N1.7-3B \
        --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT \
        --port 5555 \
        --device cuda:0
else
    echo "Isaac-GR00T directory not found at $GR00T_DIR"
    sleep 3
fi
GR00T_SERVER
    chmod 0755 "${demos_dir}/gr00t-policy-server.sh" 2>/dev/null || true

    # 6. Arena + GR00T Closed-Loop Demo Launcher
    cat << 'CLOSED_LOOP' | run_as_user_stdin "${demos_dir}/arena-gr00t-closed-loop.sh"
#!/usr/bin/env bash
set -euo pipefail
LAB_DIR="$HOME/IsaacLab"
ARENA_DIR="$(find "$HOME/Documents/GitHub" -name "IsaacLab-Arena" -type d 2>/dev/null | head -n 1 || echo "$HOME/Documents/GitHub/BoredEngineer/IsaacLab-Arena")"
if [[ -d "$ARENA_DIR" ]]; then
    cd "$ARENA_DIR"
    echo "Starting Closed-Loop IsaacLab-Arena + Isaac-GR00T Policy Benchmark..."
    exec "$LAB_DIR/isaaclab.sh" -p isaaclab_arena/evaluation/policy_runner.py \
        --viz kit \
        --policy_type gr00t \
        --policy_host 127.0.0.1 \
        --policy_port 5555 \
        --num_steps 300 \
        cube_goal_pose
else
    echo "IsaacLab-Arena directory not found at $ARENA_DIR"
    sleep 3
fi
CLOSED_LOOP
    chmod 0755 "${demos_dir}/arena-gr00t-closed-loop.sh" 2>/dev/null || true

    # Create .desktop entries on user Desktop if directory exists
    if [[ -d "${desktop_dir}" ]]; then
        cat << DESK1 | run_as_user_stdin "${desktop_dir}/Humanoid-Locomotion-G1.desktop"
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

        cat << DESK2 | run_as_user_stdin "${desktop_dir}/Quadruped-Locomotion-Go2.desktop"
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

        cat << DESK3 | run_as_user_stdin "${desktop_dir}/Franka-Manipulation.desktop"
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

        cat << DESK4 | run_as_user_stdin "${desktop_dir}/Arena-Benchmark-Kit.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=IsaacLab-Arena Benchmark (Kit GUI)
Comment=Launch IsaacLab-Arena task runner with live Omniverse Kit 3D viewport
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 ${demos_dir}/arena-benchmark.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
DESK4

        cat << DESK5 | run_as_user_stdin "${desktop_dir}/Isaac-GR00T-Server.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Isaac-GR00T Policy Server
Comment=Launch NVIDIA Isaac-GR00T ZeroMQ VLA Policy Server (Port 5555)
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 ${demos_dir}/gr00t-policy-server.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
DESK5

        cat << DESK6 | run_as_user_stdin "${desktop_dir}/Arena-GR00T-Closed-Loop.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Arena + GR00T Closed-Loop Demo
Comment=Launch closed-loop IsaacLab-Arena rollout driven by Isaac-GR00T VLA policy
Exec=gnome-terminal -- /bin/bash -c "DISPLAY=:0 ${demos_dir}/arena-gr00t-closed-loop.sh; exec bash"
Icon=utilities-terminal
Terminal=false
Categories=Development;Science;Robotics;
DESK6

        chmod 0755 "${desktop_dir}"/*.desktop 2>/dev/null || true
        chown "${TARGET_USER}:${TARGET_USER}" "${desktop_dir}"/*.desktop 2>/dev/null || true

        for icon in "${desktop_dir}"/*.desktop; do
            run_as_user "gio set '${icon}' metadata::trusted true 2>/dev/null || true"
        done
    fi

    log_success "Physical AI Demo Launchers configured at ${demos_dir}."
}
