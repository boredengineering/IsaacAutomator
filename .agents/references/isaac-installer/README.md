# Isaac Installer (`isaac-installer`)

A modular, zero-infrastructure, bare-metal robotics workstation provisioner for **Ubuntu 22.04 LTS**.

`isaac-installer` transforms a freshly booted or pre-existing physical desktop or server into a complete robotics development, teleoperation, and simulation workstation.

---

## Key Features

- **Deep Pre-Flight Audit (`plan` / `check`)**: Generates a comprehensive diff matrix comparing host versions vs target versions, highlighting missing packages, upgrade requirements, and potential conflict risks (e.g. Wayland active, low disk space, apt locks).
- **Dry-Run Simulation (`--dry-run`)**: Simulates the exact actions the installer would execute without modifying any system files or running package installations.
- **Interactive Step-by-Step Gate (`--step` / `-i`)**: Pauses before every major stage, displaying the proposed action and asking for operator confirmation (`[Y/n/s(kip)]`).
- **Hardware & Architecture Aware**: Auto-detects **Blackwell (RTX 50xx / GBxxx)**, **Ada Lovelace (RTX 40xx)**, and **Ampere (RTX 30xx)** GPUs, automatically selecting the correct driver branch (e.g. `>= 570` for Blackwell).
- **Physical AI & Imitation Learning**:
  - Installs **Hugging Face LeRobot** (`lerobot[all,dataset_viz]`) with native FFmpeg hardware acceleration.
  - Deploys **`lerobot-dataset-viz`** into PATH with **Rerun.io** and **Foxglove Studio** visualization backends.
- **Teleoperation & Robotics Peripherals**:
  - **XR Headsets (Apple Vision Pro, Meta Quest 3, Pico 4)**: Deploys `isaacteleop[cloudxr,retargeters]` into Isaac Lab with OpenXR dev headers.
  - **Manus VR Gloves**: Deploys `99-manus-gloves.rules` and grants `uinput`/`plugdev` group access.
  - **3D SpaceMouse**: Installs and starts `spacenavd` daemon with `99-spacenav.rules`.
  - **ALOHA & SO-100 Arms (Dynamixel / Feetech)**: Injects **1ms FTDI low-latency timer udev rule** (`99-ftdi-latency.rules`) for 1000Hz feedback without 16ms Linux serial lag.
  - **Depth Cameras (Intel RealSense)**: Injects `99-realsense.rules`.
- **Complete Developer Application Suite**:
  - **Visual Studio Code** (Pre-installed with ROS, Python, C++, USD, Jupyter, GitLens, and Foxglove extensions).
  - **Docker CE Engine & CLI** + **NVIDIA Container Toolkit** (`nvidia-ctk`) + non-root user permissions.
  - **GitHub Desktop** for Linux.
  - **Google Chrome / Native Chromium** (with hardware-accelerated WebGPU/WebXR/WebRTC for Foxglove and CloudXR).
  - **Discord** for robotics community channels.

---

## Usage Guide

### 1. Pre-Flight Audit & Conflict Matrix (`plan`)
Run `plan` to see the full state comparison before touching anything:
```bash
./bin/isaac-installer plan
```

### 2. Dry-Run Simulation (`--dry-run`)
Simulate execution non-destructively:
```bash
./bin/isaac-installer install --dry-run
```

### 3. Step-by-Step Interactive Installation (`--step`)
Prompt for confirmation before every stage:
```bash
sudo ./bin/isaac-installer install --step
```

### 4. Full Bare-Metal Installation
```bash
# Standard automated setup
sudo ./bin/isaac-installer install

# Skip driver if you wish to preserve your existing NVIDIA driver:
sudo ./bin/isaac-installer install --skip-driver
```

### 5. Verification Suite
```bash
./bin/isaac-installer test
```
