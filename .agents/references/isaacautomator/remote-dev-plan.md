# Local Multi-Repo DevContainers & Cloud Sync Pipeline on GPU Workstations (v2.2)

## 1. Executive Summary & Problem Statement

Developers building complex robotics and Physical AI applications typically maintain **multiple repositories locally** (e.g., custom `IsaacLab-Arena` environments, `IsaacGR00T` / `openpi` policy architectures, custom robot assets, and evaluation runners).

### The Core Challenge:
* **Local limitations**: Laptops (e.g., macOS / lightweight Linux laptops) lack NVIDIA workstation GPUs, VRAM capacity (48GB–96GB+ required for RTX 6000 Ada / A100), and NVIDIA Container Toolkit drivers needed to run Isaac Sim and PhysX GPU physics.
* **Local code ownership**: Developers want their canonical code on their local laptop—allowing offline editing, local Git branching, and personal IDE extensions.
* **The Solution**: An **Automated Local $\leftrightarrow$ Remote DevContainer Sync Pipeline**. Your local repositories are synced via high-performance synchronization engines (Mutagen, Rsync, Unison) to the cloud VM, where a standardized **OCI DevContainer** mounts those directories and executes with full NVIDIA GPU hardware acceleration.

```mermaid
graph LR
    subgraph "Local Developer Machine (Mac / Linux)"
        IDE["Local VS Code / Cursor IDE"]
        LocalMultiRepo["Local Repositories (~/dev/)<br/>├── IsaacLab-Arena/<br/>├── IsaacGR00T/<br/>└── custom-robot-envs/"]
        SyncEngine["Sync Daemon<br/>(Mutagen / fswatch + Rsync)"]
    end

    subgraph "Cloud Isaac Workstation (GCP / AWS / Azure)"
        HostDir["Host Workspaces Directory<br/>(/home/ubuntu/workspaces/)"]
        
        subgraph "Remote GPU DevContainer"
            DevCont["Isaac Lab & Sim DevContainer<br/>(nvcr.io/nvidia/isaac-sim:4.5+)"]
            Mounts["Bind Mounts (/workspaces/)<br/>├── IsaacLab-Arena (editable)<br/>├── IsaacGR00T (editable)<br/>└── custom-robot-envs (editable)"]
            GPU["NVIDIA RTX 6000 Ada (96GB)<br/>• CUDA 12.x / PyTorch 2.4+<br/>• Vulkan & Display :0"]
        end
        
        Streamer["Sunshine / KasmVNC<br/>(60 FPS 3D Viewport)"]
    end

    IDE --> LocalMultiRepo
    LocalMultiRepo <== "1. Sub-second File Delta" ==> SyncEngine
    SyncEngine <== "2. SSH Tunnel" ==> HostDir
    HostDir <== "3. Docker Volume Bind" ==> Mounts
    Mounts --> GPU
    GPU --> Streamer
    Streamer ==> "4. Live 3D Viewport" ==> IDE
    HostDir <== "5. Pull Checkpoints" ==> LocalMultiRepo
```

---

## 2. Sync Software Ecosystem Comparison

There are several software tools developers use to sync local code with remote cloud instances. Isaac Automator provides a modular design supporting the best-in-class engines:

| Tool | Sync Type | Latency | Conflict Resolution | Remote Agent Needed? | Primary Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Mutagen** *(Recommended)* | **Bidirectional** (Real-time) | **$<100\text{ms}$** | **Automatic (Alpha/Beta rules)** | Auto-injected over SSH | **Gold standard for Docker & DevContainers**. Handles network disconnects and file locks effortlessly. |
| **`fswatch` + Rsync** | **One-way / Event-driven** | **$<300\text{ms}$** | Local overwrites remote | No (standard Unix tools) | **Zero-dependency lightweight watcher**. Standard on all Mac/Linux machines. |
| **Unison** | **Bidirectional** (Batch/Event) | $\sim 500\text{ms}$ | Archive-based detection | Yes (`unison` on remote) | Robust two-way sync for teams making edits on both sides. |
| **Syncthing** | **Bidirectional** (P2P Daemon) | $1\text{s} - 3\text{s}$ | Conflict file creation | Yes (`syncthing` service) | Long-lived background mesh sync with web UI monitoring. |
| **SSHFS** | **Live Mount** (Filesystem) | $50\text{ms} - 200\text{ms}$/op | N/A (single remote store) | No (FUSE module) | Direct mounting (slower for large python packages / git trees). |

---

## 3. Deep Dive into the Top Two Synchronization Engines

### Engine A: Mutagen (`mutagen.io`) — The Industry Leader for DevContainers

**Mutagen** was specifically engineered for remote development and Docker container volume synchronization.

#### How It Works:
1. **Low-Latency File System Watching**: Leverages native OS events (`FSEvents` on macOS, `kqueue` on BSD, `inotify` on Linux) to detect modifications instantly.
2. **Optimized Rsync Delta Transport**: Computes binary file diffs so only modified bytes are transmitted across the SSH tunnel.
3. **Automatic Lifecycle & Self-Healing**: Automatically pauses when your laptop sleeps or loses Wi-Fi, and resumes/re-indexes instantly upon reconnecting.

#### Mutagen Configuration in Isaac Automator (`mutagen.yml`):
```yaml
sync:
  isaac_dev:
    mode: "two-way-resolved"
    alpha: "/Users/renan/dev/IsaacLab-Arena"
    beta: "ubuntu@136.65.140.205:/home/ubuntu/workspaces/IsaacLab-Arena"
    configurationBeta:
      permissions:
        defaultFileMode: 0644
        defaultDirectoryMode: 0755
    ignore:
      vcs: true
      paths:
        - ".git"
        - "__pycache__"
        - "*.egg-info"
        - ".venv"
        - "logs/"
        - "checkpoints/"
        - "*.pt"
        - "*.h5"
        - "*.safetensors"
```

---

### Engine B: `fswatch` + Rsync — Zero-Dependency Unix Watcher

For environments where installing additional daemons like Mutagen is not desired, Isaac Automator includes a built-in event-driven `rsync` runner:

#### How It Works:
* On macOS: `fswatch -o ~/dev/IsaacLab-Arena | xargs -n1 -I{} ./sync push test03 ~/dev/IsaacLab-Arena`
* On Linux: `inotifywait -m -r -e modify,create,delete ~/dev/IsaacLab-Arena`

#### The Standard Rsync Command:
```bash
rsync -avzP \
  --delete \
  --exclude-from=".gitignore" \
  --exclude=".git/" \
  --exclude="__pycache__/" \
  --exclude="*.egg-info/" \
  --exclude="*.pt" \
  --exclude="*.h5" \
  -e "ssh -i state/test03/key.pem -p 22" \
  ~/dev/IsaacLab-Arena/ \
  ubuntu@136.65.140.205:/home/ubuntu/workspaces/IsaacLab-Arena/
```

---

## 4. The 3 Sync Modes of the Isaac Automator CLI

Isaac Automator wraps these engines into unified commands:

### Mode 1: Continuous Event Watcher (`./sync watch`)
```sh
# Start real-time sync for multiple repositories
./sync watch test03 ~/dev/IsaacLab-Arena ~/dev/IsaacGR00T --engine mutagen
```
*Any local edit in VS Code on your laptop is mirrored to the cloud VM in $<100\text{ms}$.*

---

### Mode 2: One-Shot Bulk Push / Seed (`./sync push`)
```sh
# Seed repositories to the cloud workstation in one shot
./sync push test03 ~/dev/IsaacLab-Arena
./sync push test03 ~/dev/IsaacGR00T
```

---

### Mode 3: Artifact & Checkpoint Retrieval (`./sync pull`)
```sh
# Pull trained PyTorch model checkpoints
./sync pull test03 --remote logs/rsl_rl/model_best.pt --local ~/dev/models/

# Pull recorded LeRobot demonstration dataset
./sync pull test03 --remote datasets/so_arm_teleop/ --local ~/dev/datasets/
```

---

## 5. Multi-Repo DevContainer Architecture on the Cloud VM

### The Directory Mapping:

```text
Local Laptop (~/dev/):                    Cloud Host (/home/ubuntu/):               Inside DevContainer:
├── IsaacLab-Arena/      == [sync] ==>    ├── workspaces/IsaacLab-Arena/     ==>   ├── /workspaces/IsaacLab-Arena
├── IsaacGR00T/          == [sync] ==>    ├── workspaces/IsaacGR00T/         ==>   ├── /workspaces/IsaacGR00T
└── custom-robot-envs/   == [sync] ==>    ├── workspaces/custom-robot-envs/  ==>   └── /workspaces/custom-robot-envs
```

### Standardized `devcontainer.json` for Multi-Repo Robotics:

```json
{
  "name": "NVIDIA Isaac Robotics Multi-Repo Workspace",
  "image": "nvcr.io/nvidia/isaac-sim:4.5.0",
  "runArgs": [
    "--gpus=all",
    "--network=host",
    "--ipc=host",
    "--ulimit=memlock=-1",
    "--ulimit=stack=67108864",
    "-v", "/home/ubuntu/workspaces:/workspaces:rw",
    "-v", "/tmp/.X11-unix:/tmp/.X11-unix:rw",
    "-v", "/home/ubuntu/.Xauthority:/root/.Xauthority:rw",
    "-e", "DISPLAY=:0",
    "-e", "ACCEPT_EULA=Y",
    "-e", "NVIDIA_VISIBLE_DEVICES=all",
    "-e", "NVIDIA_DRIVER_CAPABILITIES=all"
  ],
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "ms-toolsai.jupyter",
        "eamodio.gitlens"
      ],
      "settings": {
        "python.defaultInterpreterPath": "/isaac-sim/python.sh",
        "python.analysis.extraPaths": [
          "/isaac-sim/exts",
          "/isaac-sim/extscache",
          "/workspaces/IsaacLab",
          "/workspaces/IsaacLab-Arena",
          "/workspaces/IsaacGR00T"
        ]
      }
    }
  },
  "postCreateCommand": "bash /workspaces/.devcontainer/post_create.sh",
  "remoteUser": "root"
}
```

### Automatic Editable Python Setup (`post_create.sh`):
Whenever the DevContainer starts or a new repo is synced, all repositories are installed in editable mode (`pip install -e .`):
```bash
#!/bin/bash
set -e

echo "=== Initializing Synced Repositories in Editable Mode ==="
cd /workspaces

for repo in IsaacLab-Arena IsaacGR00T custom-robot-envs; do
  if [ -d "/workspaces/$repo" ]; then
    echo "Registering $repo in editable Python mode..."
    /isaac-sim/python.sh -m pip install -e "/workspaces/$repo" || true
  fi
done

echo "=== All repositories linked and active! ==="
```

---

## 6. End-to-End Daily Workflow

### Step 1: Start Continuous Sync
```sh
./sync watch test03 ~/dev/IsaacLab-Arena ~/dev/IsaacGR00T
```

### Step 2: Open VS Code attached to Remote DevContainer
```sh
./dev code test03
```

### Step 3: Run & Debug on Cloud GPU
```sh
# Execute training on the remote GPU
./exec test03 "python -m isaaclab.tasks.train --task Isaac-Velocity-Rough-Go2 --headless"

# Stream live 3D visual viewport via Moonlight
./exec test03 "python -m isaaclab.tasks.train --task Isaac-Velocity-Rough-Go2"
```

### Step 4: Pull Results Back to Laptop
```sh
./sync pull test03 --remote logs/rsl_rl/model_best.pt --local ~/dev/models/
```

---

## 7. Phased Implementation Roadmap

- [ ] **Phase 1: Multi-Engine Sync Module (`src/python/sync_manager.py`)**
  - Implement Mutagen driver and `fswatch` + `rsync` fallback driver.
  - Implement `./sync watch`, `./sync push`, `./sync pull`, and `./sync status` CLI commands.
  - Add standard robotics exclude profiles (`.gitignore` aware).
- [ ] **Phase 2: Standardized Multi-Repo DevContainer Template**
  - Create `src/devcontainer/` templates with GPU passthrough, X11 socket mapping, and editable pip hooks.
  - Implement `post_create.sh` multi-repo linker.
- [ ] **Phase 3: Remote Job Runner CLI (`./exec`)**
  - Implement `./exec <name> <command>` with PTY allocation, ANSI colors, and environment variable passing.
  - Add background `tmux` runner support (`--detach`, `--attach`).
- [ ] **Phase 4: VS Code Remote & SSH Integration**
  - Generate dynamic SSH Host entries in `~/.ssh/config`.
  - Implement `./code <name>` launcher.
- [ ] **Phase 5: Documentation & Developer Walkthrough**
  - Add multi-repo DevContainer & Rsync guide to `README.md`.
  - Add operator skills in `.agents/skills/isaac-automator/remote-dev/`.
