---
name: isaac-installer
description: Discover, provision, audit, heal, and evaluate physical bare-metal robotics workstations with Isaac Sim, Isaac Lab, IsaacLab-Arena, and NVIDIA Isaac-GR00T using declarative YAML profiles.
---

# Isaac Bare-Metal Installer (`isaac-installer`) <!-- omit in toc -->

- [1. Quick Start & Overview](#1-quick-start--overview)
- [2. System Doctor & Pre-Flight Audit](#2-system-doctor--pre-flight-audit)
- [3. Profile-Based Declarative Provisioning](#3-profile-based-declarative-provisioning)
- [4. Dual-Remote Fork Topology & Sync Workflows](#4-dual-remote-fork-topology--sync-workflows)
- [5. IsaacLab-Arena Submodule & Standalone Bridging](#5-isaaclab-arena-submodule--standalone-bridging)
- [6. NVIDIA Isaac-GR00T Foundation Model Stack & Closed-Loop Rollouts](#6-nvidia-isaac-gr00t-foundation-model-stack--closed-loop-rollouts)
- [7. State Tracking, Drift Detection & Self-Healing](#7-state-tracking-drift-detection--self-healing)
- [8. 15-Subsystem Verification Suite](#8-15-subsystem-verification-suite)

---

## 1. Quick Start & Overview

The **Isaac Bare-Metal Installer (`isaac-installer`)** is a zero-infrastructure provisioner for Ubuntu 22.04 physical machines and GPU nodes. Unlike containerized cloud automation, it configures local developer workspaces (`~/Documents/GitHub/<Owner>/<Repo>`), Dual-Remote Git topologies, hybrid Conda+UV Python runtimes, and desktop UI launchers.

Binary location: `.agents/references/isaac-installer/bin/isaac-installer` (or `/usr/local/bin/isaac-installer` if installed globally).

---

## 2. System Doctor & Pre-Flight Audit

Before running installations, probe the hardware and conflict matrix:

```bash
cd /workspaces/IsaacAutomator/.agents/references/isaac-installer

# 1. Probe CPU, RAM, NVMe SSDs, LVM, NVIDIA Blackwell/Ada GPUs, and Display:
./bin/isaac-installer doctor

# 2. Output structured JSON hardware telemetry:
./bin/isaac-installer doctor --json

# 3. Perform 20-component pre-flight audit and conflict detection:
./bin/isaac-installer plan

# 4. Check unified authentication status (GitHub, HF, NGC, WandB, hardware groups):
./bin/isaac-installer auth status
```

---

## 3. Profile-Based Declarative Provisioning

Install workloads according to declarative YAML configurations (`config/*.yaml`):

```bash
# Standard interactive robotics workstation (Sim + Lab + Dev Apps + 1ms FTDI serial):
sudo ./bin/isaac-installer install

# Minimal headless server (RL training / CI cluster node):
sudo ./bin/isaac-installer install --profile minimal

# Full ecosystem (+ LeRobot, Arena, GR00T, SpaceMouse, Manus VR):
sudo ./bin/isaac-installer install --profile full

# Selective CLI overrides:
sudo ./bin/isaac-installer install --with-arena --with-gr00t --with-lerobot

# Custom fork and workspace hierarchy:
sudo ./bin/isaac-installer install \
  --workspace-dir ~/Documents/GitHub \
  --workspace-layout org \
  --workspace-owner BoredEngineer \
  --isaaclab-repo BoredEngineer/IsaacLab \
  --arena-repo BoredEngineer/IsaacLab-Arena \
  --gr00t-repo boredengineering/Isaac-GR00T
```

---

## 4. Dual-Remote Fork Topology & Sync Workflows

All cloned repositories are wired with `origin` pointing to your personal fork (push enabled) and `upstream` pointing to canonical NVIDIA/HF repositories (push locked):

```bash
# Check sync status and commit deltas (ahead/behind):
./bin/isaac-installer lab status
./bin/isaac-installer arena status
./bin/isaac-installer gr00t status

# Synchronize branch with canonical upstream:
./bin/isaac-installer lab sync
./bin/isaac-installer arena sync
./bin/isaac-installer gr00t sync

# Switch between release tags and branches:
./bin/isaac-installer lab list-tags
./bin/isaac-installer lab switch v3.0.0-beta2
./bin/isaac-installer arena switch release/0.3.0
```

---

## 5. IsaacLab-Arena Submodule & Standalone Bridging

`isaac-sim/IsaacLab-Arena` references internal submodules (`submodules/IsaacLab`, `submodules/Isaac-GR00T`). Use the Submodule Bridging Engine to switch between live development and deterministic replication:

```bash
# 1. Audit submodule vs standalone commit alignment:
./bin/isaac-installer arena submodules status

# 2. Strategy A (Recommended): Non-Invasive Python Editable Bridge (0% Git dirt):
./bin/isaac-installer arena submodules editable-bridge

# 3. Strategy B: In-place directory symlinks for live filesystem edits:
./bin/isaac-installer arena submodules link-standalone

# 4. Safe Reset: Strip symlinks and restore exact upstream pinned commits:
./bin/isaac-installer arena submodules restore-pinned
```

---

## 6. NVIDIA Isaac-GR00T Foundation Model Stack & Closed-Loop Rollouts

Run foundation model inference, ZeroMQ serving, and closed-loop PhysX rollouts (supporting both native bare-metal and containerized baseline execution):

```bash
# 1. Pre-cache gated model weights (nvidia/GR00T-N1.7-3B, Cosmos-Reason2-2B):
./bin/isaac-installer gr00t download-weights

# 2. Offline / CI mock model fixture:
./bin/isaac-installer gr00t download-weights --mock

# 3. Launch ZeroMQ Policy Server (Port 5556) [Native or Docker]:
./bin/isaac-installer gr00t server 5556
./bin/isaac-installer gr00t server 5556 --docker

# 4. Interactive Live 3D Kit Viewport Rollout (Visual GUI) [Native or Docker]:
./bin/isaac-installer arena play pick_and_place_maple_table --policy gr00t --port 5556
./bin/isaac-installer arena play pick_and_place_maple_table --docker --policy gr00t --port 5556

# 5. Headless Closed-Loop Benchmark Evaluation:
./bin/isaac-installer arena eval-gr00t cube_goal_pose 5556
./bin/isaac-installer arena eval-gr00t cube_goal_pose 5556 --docker

# 6. Extract Working Container Manifests for Native Conversion:
./bin/isaac-installer arena extract-container-manifest
```

---

## 7. State Tracking, Drift Detection & Self-Healing

If repos are moved, remotes misconfigured, or symlinks broken, detect and reconcile automatically:

```bash
# Audit workspace hierarchy, remote URLs, and symlink drift:
./bin/isaac-installer drift

# Automatically reconcile and heal workspace drift:
sudo ./bin/isaac-installer repair
```

---

## 8. 15-Subsystem Verification Suite

Run granular health verification across all subsystems:

```bash
# Run full 15-subsystem verification scorecard:
./bin/isaac-installer test

# Run targeted component tests:
./bin/isaac-installer test arena
./bin/isaac-installer test gr00t
./bin/isaac-installer test lab
```
