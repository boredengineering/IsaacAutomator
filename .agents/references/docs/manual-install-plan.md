# Manual Installation Guide: Isaac Sim, Isaac Lab & Isaac Lab Arena

This document provides a comprehensive, step-by-step procedure to manually install and configure **NVIDIA Isaac Sim (Source Build)**, **Isaac Lab**, **Isaac Lab Arena**, reinforcement learning demos, and remote desktop services on an Ubuntu 22.04 LTS GPU workstation without using the automated Ansible deployer.

---

## 1. System Requirements & Architecture Overview

- **OS**: Ubuntu 22.04 LTS (Jammy Jellyfish) x86_64
- **GPU**: NVIDIA RTX (Ada Lovelace, Ampere, or Turing architecture) with minimum 16GB VRAM (e.g. L4, A10G, A100, RTX 4090/6000 Ada)
- **Driver**: NVIDIA Linux 64-bit Display Driver >= `535.129.03`
- **Compiler**: GCC 11 & G++ 11 (strict requirement for Omniverse C++ extensions)
- **Directory Layout**:
  - `~/IsaacSim-source`: Isaac Sim git checkout and build tree
  - `~/IsaacSim`: Symlink to `~/IsaacSim-source/_build/linux-x86_64/release`
  - `~/IsaacLab`: Isaac Lab repository containing `_isaac_sim` symlink
  - `~/IsaacLab-Arena`: Multi-agent / benchmark simulation environment

---

## 2. Base System & Toolchain Setup

### 2.1 Install Build Tools and Graphics Dependencies
```bash
sudo apt-get update && sudo apt-get install -y \
  build-essential cmake git git-lfs curl wget htop \
  gcc-11 g++-11 \
  python3 python3-pip python3-venv \
  libvulkan-dev vulkan-tools \
  libgl1-mesa-dev libglu1-mesa-dev \
  libx11-dev libxcursor-dev libxrandr-dev libxinerama-dev libxi-dev libxkbcommon-dev \
  xserver-xorg

# Set GCC 11 / G++ 11 as the default system compiler
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 200
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-11 200

# Initialize Git Large File Storage (LFS)
git lfs install
```

### 2.2 NVIDIA GPU Driver & Settings
```bash
# 1. Add NVIDIA CUDA repository
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update

# 2. Blacklist nouveau driver
echo -e "blacklist nouveau\noptions nouveau modeset=0" | sudo tee /etc/modprobe.d/blacklist-nouveau.conf
sudo update-initramfs -u

# 3. Install driver and tools
sudo apt-get install -y cuda-drivers-535 dkms

# 4. Enable persistence mode and disable ECC (recommended for single-GPU cloud VMs)
sudo nvidia-smi -pm ENABLED
sudo nvidia-smi --ecc-config=0 || true

# 5. Reboot to load fresh kernel modules
sudo reboot
```

### 2.3 Headless Virtual Display Configuration (Cloud VMs)
When running headless without a physical monitor, Omniverse Kit requires a virtual X11 display with an EDID file:

```bash
# Generate Xorg configuration with virtual display
sudo nvidia-xconfig -a \
  --allow-empty-initial-configuration \
  --virtual=1920x1080 \
  --busid=$(nvidia-xconfig --query-gpu-info | grep 'PCI BusID' | head -n 1 | cut -c15-)

# Ensure ~/.Xauthority exists
touch ~/.Xauthority
chmod 0666 ~/.Xauthority
```

---

## 3. Isaac Sim (Source Build)

### 3.1 Clone & Pull Assets
```bash
cd ~
git clone --depth 1 https://github.com/isaac-sim/IsaacSim.git IsaacSim-source
cd IsaacSim-source

# Pull binary assets via Git LFS
git lfs pull

# Accept the NVIDIA Omniverse / Isaac Sim EULA
touch .eula_accepted
```

### 3.2 Build Release Binaries
```bash
# Clean previous build artifacts if any
rm -rf _build

# Compile Omniverse Kit and Isaac Sim plugins (~15–40 mins)
./build.sh --release
```

### 3.3 Symlink & Post-Install
```bash
# 1. Create standard symlink
ln -sf ~/IsaacSim-source/_build/linux-x86_64/release ~/IsaacSim

# 2. Run post-installation script to package internal Python and desktop shortcuts
cd ~/IsaacSim
./post_install.sh

# 3. Ensure desktop entry forces GPU 0 (avoids Vulkan device mismatch on cloud GPUs)
if [ -f ~/.local/share/applications/IsaacSim.desktop ]; then
  sed -i 's|\(Exec=.*isaac-sim\.sh\)|\1 --/renderer/activeGpu=0|' ~/.local/share/applications/IsaacSim.desktop
  mkdir -p ~/Desktop
  cp ~/.local/share/applications/IsaacSim.desktop ~/Desktop/
  gio set ~/Desktop/IsaacSim.desktop metadata::trusted true 2>/dev/null || true
fi
```

---

## 4. Isaac Lab Installation

### 4.1 Clone & Link Isaac Sim
```bash
cd ~
git clone --depth 1 https://github.com/isaac-sim/IsaacLab.git IsaacLab
cd IsaacLab

# Symlink Isaac Sim release directory to Isaac Lab's expected location
ln -sf ~/IsaacSim _isaac_sim
```

### 4.2 Install Extensions & Python Dependencies
```bash
# Execute Isaac Lab installation script
./isaaclab.sh --install
```

### 4.3 Smoke Test & Verification
```bash
# Test basic viewport and simulator initialization
./isaaclab.sh -p scripts/tutorials/00_sim/create_empty_scene.py
```

---

## 5. Isaac Lab Arena Installation

Isaac Lab Arena extends Isaac Lab with competitive multi-agent environments and structured benchmark tasks:

```bash
cd ~
git clone --depth 1 --recurse-submodules --shallow-submodules \
  -b release/0.1.1 https://github.com/isaac-sim/IsaacLab-Arena.git IsaacLab-Arena
```

---

## 6. Out-of-the-Box RL & Manipulation Demos

All demos run through the Isaac Lab entrypoint script `./isaaclab.sh -p`:

### 6.1 Unitree G1 Humanoid Locomotion (RSL-RL)
Trains a 29-DOF Unitree G1 humanoid robot to walk across rough terrain:
```bash
cd ~/IsaacLab
./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py \
  --task Isaac-Velocity-Rough-G1-v0 \
  --num_envs 64 \
  --max_iterations 300
```

### 6.2 Unitree Go2 Quadruped Locomotion (RSL-RL)
Trains a Unitree Go2 quadruped robot in rough terrain locomotion:
```bash
cd ~/IsaacLab
./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py \
  --task Isaac-Velocity-Rough-Unitree-Go2-v0 \
  --num_envs 64 \
  --max_iterations 300
```

### 6.3 Franka Arm Cube Lift (Manipulation RL)
Trains a Franka Emika Panda robotic arm to grasp and lift an object:
```bash
cd ~/IsaacLab
./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py \
  --task Isaac-Lift-Cube-Franka-v0 \
  --num_envs 64 \
  --max_iterations 300
```

> [!NOTE]
> For high-throughput headless batch training across thousands of parallel environments, append `--headless` and increase environments:
> `NUM_ENVS=4096 ./isaaclab.sh -p scripts/reinforcement_learning/rsl_rl/train.py --task Isaac-Velocity-Rough-G1-v0 --num_envs 4096 --headless`

---

## 7. Remote Desktop Streaming (3D Viewport)

Omniverse Kit renders directly onto hardware Vulkan swapchains. Standard 2D VNC will show the desktop UI but may render the 3D viewport black. For live 3D interaction, use one of the following streaming servers:

### Option A: NoMachine (Recommended for High FPS 3D)
```bash
wget https://download.nomachine.com/download/8.11/Linux/nomachine_8.11.3_4_amd64.deb
sudo dpkg -i nomachine_8.11.3_4_amd64.deb
# Default port: 4000 (NX protocol)
```

### Option B: Sunshine + Moonlight (Ultra Low Latency NVENC)
```bash
wget https://github.com/LizardByte/Sunshine/releases/download/v0.21.0/sunshine-ubuntu-22.04-amd64.deb
sudo apt-get install -y ./sunshine-ubuntu-22.04-amd64.deb
# Web UI configuration: https://<IP>:47990
```

### Option C: KasmVNC (Web Browser Access)
```bash
wget https://github.com/kasmtech/KasmVNC/releases/download/v1.3.1/kasmvncserver_jammy_1.3.1_amd64.deb
sudo apt-get install -y ./kasmvncserver_jammy_1.3.1_amd64.deb
# Web UI default port: 8443
```

---

## 8. Troubleshooting & Common Pitfalls

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **`libvulkan.so.1` or Vulkan device error** | Cloud GPU has multiple display devices or lacks active GPU flag. | Launch with `./isaac-sim.sh --/renderer/activeGpu=0`. |
| **`build.sh` C++ compilation error** | System defaulted to GCC 12+ which is incompatible with Kit 105/106. | Run `sudo update-alternatives --set gcc /usr/bin/gcc-11`. |
| **Missing mesh / USD assets** | Git LFS was not initialized before cloning. | Run `git lfs install && git lfs pull` in `~/IsaacSim-source`. |
| **`_isaac_sim` directory not found** | Isaac Lab was cloned without symlinking Isaac Sim. | Run `ln -sf ~/IsaacSim ~/IsaacLab/_isaac_sim`. |
| **Black 3D viewport over remote desktop** | VNC driver cannot capture hardware Vulkan surface. | Use **NoMachine**, **NICE DCV**, or **Sunshine/Moonlight** instead of standard VNC. |
