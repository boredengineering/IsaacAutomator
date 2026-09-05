# Dynamic Multi-Cloud Security Tiering & Hardened Storage Architecture
**Comprehensive Architecture Guide, Declarative Profile Spec & Operator Instructions**

---

## 1. Architectural Philosophy: Zero Forced Overhead

Robotics researchers, indie developers, and enterprise platform teams have vastly different infrastructure requirements:
* A solo researcher testing an RL policy on an L4 GPU needs a **lean, fast, zero-added-cost** environment. They cannot afford and do not need a $32+/month Cloud NAT gateway or dedicated KMS key fees.
* An enterprise AI laboratory requires **Zero-Trust network isolation**, eliminating public IPs, enforcing Customer-Managed Encryption Keys (CMEK), centralizing IAM through OS Login with 2FA, and distributed state locking.

### The Non-Hardcoded, Dynamic Rule
In `IsaacAutomator`, **all enterprise infrastructure is 100% modular and feature-flagged**:
```hcl
count = var.enable_<feature> ? 1 : 0
```
When running with the default settings:
* **$0.00 Added Infrastructure Cost**: No Cloud NAT, no Cloud Router, no Cloud KMS Key Rings, no Secret Manager charges.
* **Zero Permission Blockers**: Does not require Organization Administrator, KMS Admin, or Security Admin privileges. Standard developer permissions (`roles/editor` or `roles/compute.instanceAdmin.v1`) work out of the box.

---

## 2. Multi-Cloud Security & Storage Tiering

| Tier / Profile | Added Monthly Overhead | Ingress / Perimeter | Outbound Internet | State & Shared Storage | Data Encryption | Identity & Access |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Simple Mode** *(Default)* | **$0.00 / month** | Ephemeral Public IP locked strictly to caller's `/32` | Direct ephemeral public routing | Local `.tfstate` in `./state/<name>/` (POSIX 0600) | Free cloud-default (Google-managed, AWS SSE-S3) | Direct SSH key injection into instance metadata |
| **Tier 2: Team Mode** | **<$0.10 / month** | Dynamic `/32` IP lock or shared team CIDR | Direct ephemeral public routing | Hardened GCS/S3 Remote State with distributed locking | Free cloud-default with bucket versioning | Scoped instance Service Account + Metadata key |
| **Tier 3: Enterprise Mode** | **~$35.00 - $180.00 / mo** | **Zero Public IP** (Cloud IAP TCP Forwarding only) | Managed **Cloud Router & Cloud NAT Gateway** | Hardened GCS Remote State + 7-day soft-delete protection | **Cloud KMS CMEK** with 90-day auto-rotation | **OS Login with 2FA** + **Shielded VM** (Secure Boot & vTPM) |
| **Special Custom Mode** | **Dynamic ($0 - $180+)** | **User-Selected** (Public /32 vs IAP Private) | **User-Selected** (Direct vs Cloud NAT) | **User-Selected** (Local vs GCS Remote Bucket) | **User-Selected** (Google-Managed vs KMS CMEK) | **User-Selected** (OS Login vs Metadata key) |

---

## 3. The 6 Hardened Enterprise Security Pillars

When **Tier 3 (Enterprise)** or corresponding custom flags are enabled, the following subsystems are synthesized:

### 1. Zero-Trust Private Network & Identity-Aware Proxy (IAP)
* The Compute Engine instance is provisioned with **no external public IP** (`access_config` is completely omitted).
* The instance is invisible to public internet port scans and brute-force attacks.
* Ingress firewall rules allow traffic **only from Google's official IAP CIDR (`35.235.240.0/20`)**.
* Operators connect through encrypted, IAM-authenticated tunnels (`gcloud compute ssh --tunnel-through-iap` or background port forwarders).
* Private Google Access (PGA) routes all internal API calls (GCS, KMS, Secret Manager) over Google's internal backbone without crossing the public internet.

### 2. Cloud Router & Cloud NAT Gateway
* To allow private instances to install Ubuntu packages (`apt`), Python packages (`uv` / `pip`), and Docker containers from NGC without exposing any inbound ports, a dedicated **Cloud Router** and **Cloud NAT Gateway** handle outbound network translation.

### 3. Hardened GCS Remote State with Concurrency Locking
* Replaces vulnerable local `backend "local" {}` `.tfstate` files with a hardened GCS backend (`src/terraform/bootstrap/gcp/main.tf`):
  * **Uniform Bucket-Level Access (UBLA)**: Disables legacy ACLs.
  * **Public Access Prevention**: `enforced`.
  * **Native Distributed State Locking**: Prevents race conditions or accidental state overwrites when multiple engineers or AI agents collaborate.
  * **Object Versioning & 7-Day Soft-Delete**: Guarantees recovery from accidental deletion or ransomware.

### 4. Customer-Managed Encryption Keys (Cloud KMS CMEK)
* Regional Key Ring (`${prefix}-${deployment_name}-keyring`) with 3 dedicated CryptoKeys:
  * `compute-disk-key`: Encrypts the workstation boot disk and persistent storage.
  * `storage-key`: Encrypts the GCS state bucket and robot simulation datasets.
  * `secrets-key`: Encrypts Secret Manager payloads.
* Configured with **90-day automatic rotation** conforming to CIS GCP Benchmark Control 1.10.

### 5. Shielded VM & Hardware Root-of-Trust
* `enable_secure_boot = true`: Ensures only cryptographically signed drivers (including official NVIDIA kernel modules) are loaded into the Linux kernel.
* `enable_vtpm = true`: Virtual Trusted Platform Module for measured boot and credential sealing.
* `enable_integrity_monitoring = true`: Compares runtime boot measurements against a baseline; alerts via Cloud Logging if an integrity mismatch occurs.

### 6. Centralized OS Login with Mandatory 2FA & Secret Manager
* **OS Login**: Replaces static RSA keys in metadata with IAM-managed access (`enable-oslogin = TRUE`, `block-project-ssh-keys = TRUE`). Revoking an engineer's IAM role immediately cuts VM access.
* **Google Secret Manager**: NGC API keys, Hugging Face tokens, and desktop session credentials are never stored in disk images or git; the instance retrieves them dynamically at boot using its service account token.

---

## 4. Declarative Profile Specification (`configs/profiles/*.yaml`)

Custom configurations can be saved and reused across teams using the declarative profile schema:

```yaml
schema_version: "v1alpha1"
profile_name: "cybernetic-studio"
description: "Collaborative team profile with remote GCS state and IAP zero-trust without KMS overhead"
cloud: "gcp"

security:
  tier: "custom" # "simple" | "team" | "enterprise" | "custom"
  
  # Network & Ingress Perimeter
  network:
    iap_only: true              # True = Zero public IP (Cloud IAP only)
    cloud_nat: true             # Cloud NAT for outbound package updates
    ingress_cidrs: []           # Empty when iap_only is true
  
  # Storage & State Locking
  storage:
    state_backend: "gcs"        # "local" | "gcs"
    state_bucket: "auto"        # Auto-provisioned: isaacautomator-state-<project>-<region>
    state_locking: true
    soft_delete_days: 7
  
  # Cryptographic Engine
  cryptography:
    encryption_type: "google_managed" # "google_managed" | "kms_cmek"
    kms_keyring_name: ""
    rotation_days: 90
  
  # Compute & Hardware Integrity
  compute:
    shielded_vm: true           # Secure Boot, vTPM, Integrity Monitoring
    os_login: true              # Central IAM authentication with mandatory 2FA
    service_account_type: "dedicated"
  
  # Credentials & Secrets Handling
  secrets:
    engine: "secret_manager"    # "secret_manager" | "env_vars"

workstation:
  gpu_model: "g2-standard-8"
  demos: ["franka-manipulation"]
  remote_desktop: "standard"
```

---

## 5. How to Use the System

### Method A: Using `isaac9s` (Interactive Terminal GUI)

1. Launch `isaac9s`:
   ```bash
   ./isaac9s
   ```
2. Press `6` or type `:profile` to open the **Declarative Profile & Security Configurator**.
3. Select your mode:
   * Select **Tier 1: Simple** for $0 added cost.
   * Select **Tier 2: Team** for shared GCS remote state.
   * Select **Tier 3: Enterprise** for full Zero-Trust IAP + Cloud NAT + KMS.
   * Select **Special Custom Mode** to customize each subsystem individually.
4. **Live Dynamic Cost Estimator**:
   * As you check/uncheck features (e.g. toggling Cloud NAT adds +$32.40/mo, KMS CMEK adds +$1.80/mo), the cost badge updates in real time.
5. Save or Apply:
   * Enter a profile name (e.g. `my-studio-rig`) and press `[Save Profile to YAML]` (`s`).
   * Your custom profile is saved to `configs/profiles/<name>.yaml`.
6. Launch via Deploy Wizard:
   * Press `n` or type `:deploy` anywhere in `isaac9s`.
   * Your custom profile automatically appears in the radio selection list!
   * Hit `Enter` to launch.

---

### Method B: Using the CLI (`deploy-gcp`)

You can invoke profiles directly from the command line:

```bash
# 1. Deploy using standard Simple Mode ($0 added cost, /32 auto IP lock):
./deploy-gcp my-box-01 --profile simple

# 2. Deploy using a pre-configured profile:
./deploy-gcp my-box-02 --profile team
./deploy-gcp my-box-03 --profile enterprise

# 3. Deploy using a saved custom profile by name:
./deploy-gcp my-box-04 --profile cybernetic-custom

# 4. Deploy using an explicit YAML file path:
./deploy-gcp my-box-05 --profile configs/profiles/enterprise-zero-trust.yaml

# 5. Fine-grained CLI overrides:
./deploy-gcp my-box-06 --profile simple --state-bucket auto --iap
```

---

### Method C: Connecting to Zero-Trust Private Instances

When a workstation is deployed in private IAP mode (zero public IP):

```bash
# 1. Direct SSH through Google IAP:
./ssh my-box-04

# Under the hood, this uses:
gcloud compute ssh my-box-04 --tunnel-through-iap --project=<project> --zone=<zone>

# 2. Web Remote Desktop (KasmVNC / noVNC) through IAP:
./remote my-box-04
# Automatically establishes a local forwarding tunnel on localhost:8444 / localhost:6080.
```
