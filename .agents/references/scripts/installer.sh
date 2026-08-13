#!/bin/bash

# installer Version: 11 (Added a functional INSTALL_OPTIONAL and run_lfs)

# --- Configuration ---
# Dynamically find the repository directory, no matter where it was cloned
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

# --- Action Functions (Using Absolute Repo Paths) ---

run_novnc() {
    echo ">>> Starting Step 1: noVNC and Desktop Setup"
    if sudo bash "$BASE_DIR/setup-novnc.sh"; then
        update_status "stage_conda"
        exit 0 
    else
        echo "❌ Step 1 Failed. Halting."
        exit 1
    fi
}

run_conda() {
    echo ">>> Starting Step 2: Conda Installation"
    if sudo bash "$BASE_DIR/setup-conda.sh"; then
        # Update status so it resumes at the NEXT step after rebooting
        update_status "stage_lfs"
        
        echo "✅ Conda installed successfully. Rebooting to refresh shell environment..."
        sleep 2
        sudo reboot
        exit 0 # Exit the current script instance
    else
        echo "❌ Step 2 Failed. Halting."
        exit 1
    fi
}

run_lfs() {
    echo ">>> Starting Step 3: Git LFS Setup"
    if sudo bash "$BASE_DIR/setup-lfs.sh"; then
        update_status "stage_isaacsim"
    else
        echo "❌ Step 3 (LFS) Failed."
        exit 1
    fi
}

run_isaacsim() {
    echo ">>> Starting Step 4: Isaac Sim Installation"
    if sudo bash "$BASE_DIR/setup-isaacsim.sh"; then
        update_status "stage_isaaclab"
    else
        echo "❌ Step 4 Failed. Halting."
        exit 1
    fi
}

run_isaaclab() {
    echo ">>> Starting Step 5: Isaac Lab Installation"
    
    local ATTEMPT=1
    local MAX_ATTEMPTS=2

    while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
        echo ">>> Installation Attempt $ATTEMPT of $MAX_ATTEMPTS..."
        
        # Explicitly pass SHELL to bypass the 'unknown' error
        if sudo SHELL=/bin/bash bash "$BASE_DIR/setup-isaaclab.sh"; then
            echo ">>> Performing final verification..."
            
            # --- Fix: Use a login shell and set the working directory ---
            if sudo -i -u ubuntu bash -c "cd ~/IsaacLab && /opt/conda/bin/conda run -n isaaclab python -c 'import torch'"; then
                echo "✅ Isaac Lab successfully verified!"
                update_status "stage_leatherback"
                return 0
            fi
        fi

        echo "⚠️ Attempt $ATTEMPT failed."
        if [ $ATTEMPT -lt $MAX_ATTEMPTS ]; then
            echo ">>> Refreshing shell initialization..."
            sudo -H -u ubuntu bash -c "source /opt/conda/etc/profile.d/conda.sh && conda init bash" > /dev/null 2>&1
            sleep 5
        else
            echo "❌ Max attempts reached. Relaunching installer to force fresh pass..."
            sleep 2
            # exec replaces the current process with a fresh shell instance
            exec /bin/bash "$SCRIPT_PATH"
        fi
        ATTEMPT=$((ATTEMPT+1))
    done
}

run_leatherback() {
    echo ">>> Starting Step 6: Leatherback Setup"
    if sudo bash "$BASE_DIR/setup-leatherback.sh"; then
        # Check if we should proceed to optional steps or finish
        if [ "$INSTALL_OPTIONAL" = true ]; then
            update_status "stage_gr00t"
        else
            update_status "completed"
        fi
    else
        echo "❌ Step 6 Failed."
        exit 1
    fi
}

run_gr00t() {
    echo ">>> Starting Step 7: Isaac-GR00T Setup (Optional)"
    if sudo bash "$BASE_DIR/setup-gr00t.sh"; then
        update_status "stage_leisaac"
    else
        echo "❌ Step 7 Failed."
        exit 1
    fi
}

run_leisaac() {
    echo ">>> Starting Step 8: LeIsaac Setup (Optional)"
    if sudo bash "$BASE_DIR/setup-leisaac.sh"; then
        update_status "completed"
    else
        echo "❌ Step 8 Failed."
        exit 1
    fi
}

# --- Main Logic ---

# Ensure logs exist
sudo touch "$OUTPUT_LOG" "$STATUS_LOG"

# --- System Readiness Guard ---
echo "Checking system readiness at $(date)..." >> "$OUTPUT_LOG"

MAX_RETRIES=10
RETRY_COUNT=0

# Check if the target user environment exists before proceeding
while [ ! -d "$TARGET_HOME" ] || [ $RETRY_COUNT -lt 1 ]; do
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "System not ready after $MAX_RETRIES attempts. Exiting." >> "$OUTPUT_LOG"
        exit 1
    fi
    echo "Waiting for environment... (Attempt $((RETRY_COUNT+1)))" >> "$OUTPUT_LOG"
    sleep 20
    RETRY_COUNT=$((RETRY_COUNT+1))
    
    if ping -c 1 8.8.8.8 > /dev/null 2>&1; then
        echo "Network and Disk are ready!" >> "$OUTPUT_LOG"
        break
    fi
done

# Initialize Cron
add_to_cron

# Initialize status if empty
if [ ! -s "$STATUS_LOG" ]; then
    echo "stage_novnc" | sudo tee "$STATUS_LOG" > /dev/null
fi

# --- Execution Loop ---
while true; do
    CURRENT_STATUS="$(cat "$STATUS_LOG")"

    case "$CURRENT_STATUS" in
        stage_novnc)    run_novnc ;;
        stage_conda)    run_conda ;;
        stage_lfs)    run_lfs ;;
        stage_isaacsim) run_isaacsim ;;
        stage_isaaclab) run_isaaclab ;;
        stage_leatherback) run_leatherback ;;
        stage_gr00t)    run_gr00t ;;
        stage_leisaac)  run_leisaac ;;
        # Optional Stages
        stage_gr00t)
            if [ "$INSTALL_OPTIONAL" = true ]; then
                run_gr00t
            else
                update_status "completed"
            fi
            ;;
        stage_leisaac)
            if [ "$INSTALL_OPTIONAL" = true ]; then
                run_leisaac
            else
                update_status "completed"
            fi
            ;;
        completed)
            echo "✅ Installation Complete!"
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