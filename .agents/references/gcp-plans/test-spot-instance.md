# GCP Test Run: `test03` (g4-standard-48 Flex-start GPU Instance)

This reference document records the full parameters, cloud infrastructure, and operational state for the **`test03`** GCP deployment running on a `g4-standard-48` instance with Flex-start Dynamic Workload Scheduling and NVIDIA RTX PRO 6000 GPU acceleration.

---

## 1. Deployment Summary & Specifications

| Parameter | Value | Notes |
| :--- | :--- | :--- |
| **Deployment Name** | `test03` | Used across all Isaac Automator CLI tools (`./ssh`, `./novnc`, `./destroy`, etc.) |
| **Cloud Provider** | Google Cloud Platform (GCP) | Project ID: `cybernetic-renan` |
| **Target Zone** | `us-central1-b` | Region: `us-central1` |
| **VM Instance Name** | `isaacautomator-test03-isaac-workstation-vm` | GCE Instance Resource |
| **Machine Type** | `g4-standard-48` | 48 vCPUs, 192 GB RAM |
| **GPU Accelerator** | 1x `nvidia-rtx-pro-6000` | NVIDIA RTX PRO 6000 Ada Generation (48 GB VRAM) |
| **Boot Disk** | 255 GB `hyperdisk-balanced` | Hyperdisk Balanced required for G4 instance family |
| **Scheduling Model** | `FLEX_START` (Dynamic Workload Scheduler) | 7-day maximum run duration (`604800`s), termination action: `STOP` |
| **Static External IP** | `136.65.140.205` | Reserved static compute address |
| **VPC & Firewall** | `isaacautomator-test03-isaac-workstation-network` | Ports 22 (SSH), 5900 (VNC), 4000 (NoMachine), 8211/47995-49100 (WebRTC) |
| **Base OS** | Ubuntu 22.04 LTS (`jammy`) | `ubuntu-2204-jammy-v20251023` |
| **User Account** | `ubuntu` | Key-based authentication via `state/test03/key.pem` |

---

## 2. Command Executed

The deployment was launched non-interactively with the following parameters:

```bash
./deploy-gcp \
  --deployment-name test03 \
  --project cybernetic-renan \
  --zone us-central1-b \
  --instance-type g4-standard-48 \
  --isaac-workstation-gpu-count 1 \
  --flex-start \
  --ingress-cidrs 0.0.0.0/0 \
  --existing replace \
  --isaacsim latest \
  --isaaclab latest \
  --isaaclab-arena latest \
  --demos no \
  --no-upload \
  --debug
```

---

## 3. Scheduling & Architecture Details

### Flex-start Dynamic Workload Scheduling
The instance was provisioned with GCP Dynamic Workload Scheduler (Flex-start) in Terraform (`src/terraform/gcp/ovkit/main.tf`):

```hcl
scheduling {
  provisioning_model          = "FLEX_START"
  instance_termination_action = "STOP"
  automatic_restart           = false
  on_host_maintenance         = "TERMINATE" # Mandatory for GCP GPU instances

  max_run_duration {
    seconds = 604800 # 7-day max duration
  }
}
```

### Keyless IAM Storage Scopes
The VM is configured with `devstorage.read_write` scopes to enable keyless authentication for GCS continuous checkpoints and 30-second preemption metadata listener backups:

```hcl
service_account {
  scopes = [
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/logging.write",
    "https://www.googleapis.com/auth/monitoring.write",
    "https://www.googleapis.com/auth/servicecontrol",
    "https://www.googleapis.com/auth/service.management.readonly",
    "https://www.googleapis.com/auth/trace.append",
  ]
}
```

---

## 4. State Files & Local Artifacts

All local state artifacts are preserved in [`state/test03/`](file:///workspaces/IsaacAutomator/state/test03/):

* **[`.tfstate`](file:///workspaces/IsaacAutomator/state/test03/.tfstate)**: Contains 12 managed resources:
  1. `google_compute_instance.default` (`isaacautomator-test03-isaac-workstation-vm`)
  2. `google_compute_address.static_ip` (`136.65.140.205`)
  3. `google_compute_network.default`
  4. `google_compute_firewall.ssh`
  5. `google_compute_firewall.ssh_custom`
  6. `google_compute_firewall.nomachine`
  7. `google_compute_firewall.novnc`
  8. `google_compute_firewall.vnc`
  9. `google_compute_firewall.webrtc`
  10. `google_compute_firewall.egress`
  11. `google_project_service.compute_engine`
  12. `tls_private_key.ssh_key`
* **[`key.pem`](file:///workspaces/IsaacAutomator/state/test03/key.pem)**: RSA 4096 private key with `0600` permissions.
* **[`.inventory`](file:///workspaces/IsaacAutomator/state/test03/.inventory)**: Ansible inventory mapping host `136.65.140.205`.
* **[`info.txt`](file:///workspaces/IsaacAutomator/state/test03/info.txt)**: Connection strings and credentials.
* **[`meta.json`](file:///workspaces/IsaacAutomator/state/test03/meta.json)**: Complete execution and parameter metadata.

---

## 5. Operations & Runbook

### Checking Live GCP Status
```bash
CLOUDSDK_CONFIG=/workspaces/IsaacAutomator/state/.gcp gcloud compute instances describe \
  isaacautomator-test03-isaac-workstation-vm \
  --zone=us-central1-b \
  --format="yaml(name,status,machineType,scheduling,networkInterfaces[0].accessConfigs[0].natIP)"
```

### Running / Re-running Ansible Software Setup
Once the VM is in `RUNNING` status:
```bash
./deploy-gcp test03 --existing run_ansible
```

### Connecting to the Workstation
* **SSH:**
  ```bash
  ./ssh test03
  ```
* **Browser Remote Desktop (noVNC):**
  ```bash
  ./novnc test03
  ```
* **NoMachine (Live 3D Viewport):**
  * Host: `136.65.140.205`, Port: `4000`
  * Protocol: SSH Key-based (`state/test03/key.pem`)
  * Username: `ubuntu`

### Managing 7-Day Flex-start Uptime
```bash
# Check uptime without stopping:
./cycle-vm test03 --check-only

# Auto-cycle if uptime >= 6.5 days:
./cycle-vm test03

# Force cycle with quick restart:
./cycle-vm test03 --force --quick
```

### Clean Teardown
```bash
# Tear down and destroy all cloud resources when finished:
./destroy test03 --yes
```
