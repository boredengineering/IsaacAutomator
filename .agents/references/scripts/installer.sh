#!/bin/bash

# ------------------------------------------------------------------------------
# installer.sh: Master Installation Orchestrator for Ubuntu 22.04 LTS
# Provisions Isaac Sim, Isaac Lab, and IsaacLab-Arena for Isaac Workstations
# ------------------------------------------------------------------------------

BASE_DIR="$(dirname "$(readlink -f "$0")")"
TARGET_HOME="/home/ubuntu"
STATUS_LOG="/var/log/install_progress.log"
OUTPUT_LOG="/var/log/install_output.log"
SCRIPT_PATH="$BASE_DIR/installer.sh"
INSTALL_OPTIONAL=false

# Helper to log and update status
update_status() {
    local next_stage=$1
    echo "Transitioning to $next_stage at $(date)" | sudo tee -a "$OUTPUT_LOG"
    echo "$next_stage" | sudo tee "$STATUS_LOG" > /dev/null
}

# --- Crontab Management ---
add_to_cron() {
    sudo crontab -l 2>/dev/null | grep -q "$SCRIPT_PATH"
    if [ $? -ne 0 ]; then
        (sudo crontab -l 2>/dev/null; echo "@reboot /bin/bash $SCRIPT_PATH >> $OUTPUT_LOG 2>&1") | sudo crontab -
    fi
}

remove_from_cron() {
    sudo crontab -l 2>/dev/null | grep -v "$SCRIPT_PATH" | sudo crontab -
}

# --- Stage Execution Functions ---

run_novnc() {
    echo ">>> Starting Step 1: noVNC, X11 Virtual Display, and Desktop Setup"
    if sudo bash "$BASE_DIR/setup-novnc.sh"; then
        update_status "stage_conda"
        exit 0
    else
        echo "❌ Step 1 (noVNC) Failed. Halting."
        exit 1
    fi
}

run_conda() {
    echo ">>> Starting Step 2: Conda Environment Setup"
    if sudo bash "$BASE_DIR/setup-conda.sh"; then
        update_status "stage_lfs"
        echo "✅ Conda installed. Rebooting to refresh shell environment..."
        sleep 2
        sudo reboot
        exit 0
    else
        echo "❌ Step 2 (Conda) Failed. Halting."
        exit 1
    fi
}

run_lfs() {
    echo ">>> Starting Step 3: Git LFS Setup"
    if sudo bash "$BASE_DIR/setup-lfs.sh"; then
        update_status "stage_isaacsim"
    else
        echo "❌ Step 3 (Git LFS) Failed."
        exit 1
    fi
}

run_isaacsim() {
    echo ">>> Starting Step 4: Isaac Sim Installation"
    if sudo bash "$BASE_DIR/setup-isaacsim.sh"; then
        update_status "stage_isaaclab"
    else
        echo "❌ Step 4 (Isaac Sim) Failed. Halting."
        exit 1
    fi
}

run_isaaclab() {
    echo ">>> Starting Step 5: Isaac Lab Installation"
    if sudo bash "$BASE_DIR/setup-isaaclab.sh"; then
        update_status "stage_arena"
    else
        echo "❌ Step 5 (Isaac Lab) Failed. Halting."
        exit 1
    fi
}

run_arena() {
    echo ">>> Starting Step 6: IsaacLab-Arena Benchmark Setup"
    if sudo bash "$BASE_DIR/setup-isaaclab-arena.sh"; then
        update_status "stage_demos"
    else
        echo "❌ Step 6 (IsaacLab-Arena) Failed. Halting."
        exit 1
    fi
}

run_demos() {
    echo ">>> Starting Step 7: Desktop Shortcuts & Demo Launchers Setup"
    if sudo bash "$BASE_DIR/setup-demos.sh"; then
        if [ "$INSTALL_OPTIONAL" = true ]; then
            update_status "stage_gr00t"
        else
            update_status "completed"
        fi
    else
        echo "❌ Step 7 (Demos) Failed."
        exit 1
    fi
}

run_gr00t() {
    echo ">>> Starting Step 8: Isaac-GR00T Setup (Optional)"
    if sudo bash "$BASE_DIR/setup-gr00t.sh"; then
        update_status "completed"
    else
        echo "❌ Step 8 (GR00T) Failed."
        exit 1
    fi
}

# --- Main Logic ---

sudo touch "$OUTPUT_LOG" "$STATUS_LOG"
echo "Checking system readiness at $(date)..." >> "$OUTPUT_LOG"

MAX_RETRIES=10
RETRY_COUNT=0

while [ ! -d "$TARGET_HOME" ] || [ $RETRY_COUNT -lt 1 ]; do
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "System not ready after $MAX_RETRIES attempts. Exiting." >> "$OUTPUT_LOG"
        exit 1
    fi
    echo "Waiting for environment... (Attempt $((RETRY_COUNT+1)))" >> "$OUTPUT_LOG"
    sleep 10
    RETRY_COUNT=$((RETRY_COUNT+1))
    
    if ping -c 1 8.8.8.8 > /dev/null 2>&1; then
        echo "Network and Disk are ready!" >> "$OUTPUT_LOG"
        break
    fi
done

add_to_cron

if [ ! -s "$STATUS_LOG" ]; then
    echo "stage_novnc" | sudo tee "$STATUS_LOG" > /dev/null
fi

while true; do
    CURRENT_STATUS="$(cat "$STATUS_LOG")"

    case "$CURRENT_STATUS" in
        stage_novnc)    run_novnc ;;
        stage_conda)    run_conda ;;
        stage_lfs)      run_lfs ;;
        stage_isaacsim) run_isaacsim ;;
        stage_isaaclab) run_isaaclab ;;
        stage_arena)    run_arena ;;
        stage_demos)    run_demos ;;
        stage_gr00t)
            if [ "$INSTALL_OPTIONAL" = true ]; then
                run_gr00t
            else
                update_status "completed"
            fi
            ;;
        completed)
            echo "✅ Isaac Workstation Setup Complete! IsaacLab-Arena Ready."
            remove_from_cron
            exit 0
            ;;
        *)
            echo "Unknown status: $CURRENT_STATUS"
            exit 1
            ;;
    esac
    sleep 2 
done