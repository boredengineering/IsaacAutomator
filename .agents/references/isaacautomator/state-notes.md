# Isaac Automator State & Version Audit Reference

Comprehensive reference guide analyzing the deployed state files, cloud deployment metadata, and upstream branch resolution behaviors across all **Isaac Automator** deployments.

---

## 1. Overview & Audit Summary

An audit of all deployment state folders in `state/` confirms the exact component versions resolved and installed by Isaac Automator during cloud workstation provisioning.

Across all deployments where `--isaacsim`, `--isaaclab`, and `--isaaclab-arena` were left to the default `"latest"` dynamic auto-detection:
* **Isaac Sim**: Resolved and installed **`v6.0.1`**
* **Isaac Lab**: Resolved and installed **`release/3.0.0-beta2`**
* **IsaacLab-Arena**: Resolved and installed **`release/0.3.0-prerelease`**

---

## 2. Deployment State Matrix

Below is the verified record from all `.inventory` and `meta.json` files in `state/`:

| Deployment Directory | Cloud Provider | Instance Type & GPU | Isaac Sim (`isaacsim`) | Isaac Lab (`isaaclab`) | IsaacLab-Arena (`isaaclab_arena`) | Demos |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`state/test03`** | GCP (`us-central1-b`) | `g4-standard-48` (1 GPU) | `v6.0.1` | `release/3.0.0-beta2` | `release/0.3.0-prerelease` | `no` |
| **`state/renan-test`** | GCP (`us-central1-b`) | `g2-standard-8` (1 GPU) | `v6.0.1` | `release/3.0.0-beta2` | `release/0.3.0-prerelease` | `no` |
| **`state/test02`** | GCP (`us-central1-b`) | `g2-standard-8` (1 GPU) | `v6.0.1` | `release/3.0.0-beta2` | `release/0.3.0-prerelease` | `no` |
| **`state/renan-test-1`** | GCP (`us-central1-b`) | `g2-standard-8` (1 GPU) | `v6.0.1` | `release/3.0.0-beta2` | `release/0.3.0-prerelease` | `no` |
| **`state/renan-test01`** | GCP (`us-central1-b`) | `g2-standard-8` (1 GPU) | `v6.0.1` | `release/3.0.0-beta2` | `release/0.3.0-prerelease` | `no` |
| **`state/vm-test`** | GCP (`us-central1-b`) | `g2-standard-8` (1 GPU) | `v6.0.1` | `release/3.0.0-beta2` | `release/0.3.0-prerelease` | `no` |

---

## 3. Deep Dive: IsaacLab-Arena Version Resolution

### Upstream Repository Structure
Inspection of `https://github.com/isaac-sim/IsaacLab-Arena.git` reveals that the repository **does not publish standard git tags** (`refs/tags/*`). All releases are tracked exclusively via `release/*` heads:
* `refs/heads/release/0.1.0`
* `refs/heads/release/0.1.1` *(Default static fallback in Ansible role `defaults/main.yml`)*
* `refs/heads/release/0.2.0`
* `refs/heads/release/0.2.1` *(Latest stable release branch)*
* `refs/heads/release/0.3.0-prerelease` *(Active development / prerelease branch)*

### Resolution Mechanics (`DeployCommand._resolve_latest_ref`)
When `--isaaclab-arena latest` is evaluated:
1. `git ls-remote --tags --heads https://github.com/isaac-sim/IsaacLab-Arena.git` retrieves all remote references.
2. The method filters for `refs/heads/release/*`.
3. `_version_key` parses each version into `(nums, is_stable, pre_rank, pre_num)`:
   - `0.2.1` -> `((0, 2, 1), 1, 0, 0)`
   - `0.3.0-prerelease` -> `((0, 3, 0), 0, 1, 0)`
4. In tuple sorting, `(0, 3, 0) > (0, 2, 1)`. Therefore, the higher major/minor version (`0.3.0-prerelease`) is selected as the candidate.

### Pinning Stable Versions
To avoid prerelease branches in production or testing environments, operators can explicitly pass the stable branch:
```bash
./deploy-gcp --deployment-name prod-arena --isaaclab-arena release/0.2.1
```

---

## 4. Deep Dive: Isaac Sim & Isaac Lab Resolution

### Isaac Sim (`https://github.com/isaac-sim/IsaacSim.git`)
- **Remote Tags Available**: `v5.0.0`, `v5.1.0`, `v6.0.0`, `v6.0.0-dev`, `v6.0.1`.
- **Selected Version**: `v6.0.1` (highest release tag).
- **Installed Artifacts**: Cloned to `~/IsaacSim-source`, compiled with `./build.sh --release`, symlinked to `~/IsaacSim`, and pinned to GPU 0 (`--/renderer/activeGpu=0`).

### Isaac Lab (`https://github.com/isaac-sim/IsaacLab.git`)
- **Remote Branches & Tags**: Tags range from `v0.3.1` to `v2.3.2`, plus `v3.0.0-beta`, `v3.0.0-beta2`, and `release/3.0.0-beta2`.
- **Selected Version**: `release/3.0.0-beta2` (highest version candidate).
- **Installed Artifacts**: Cloned to `~/IsaacLab`, linked via `_isaac_sim -> ~/IsaacSim`, and installed via `./isaaclab.sh --install`.
- **Stable Alternative**: If version 2.x stability is needed, operators can pin `--isaaclab v2.3.2`.

---

## 5. Summary of Files in `state/<deployment-name>/`

Each deployment state directory manages the complete lifecycle and idempotency of the workstation:

* `.tfstate`: Terraform state file tracking all provisioned cloud infrastructure (Compute instances, VPC networks, firewall rules, public IPs, disk volumes).
* `.tfvars`: Input variables passed to Terraform (instance type, GPU count, zone, project, Flex-start flags).
* `.inventory`: Rendered Ansible inventory containing target IP addresses, SSH keys, credentials, and resolved software versions (`isaacsim_git_checkpoint`, `isaaclab_git_checkpoint`, `isaaclab_arena_git_checkpoint`).
* `key.pem`: Ephemeral RSA/ED25519 SSH private key generated specifically for workstation administrative access.
* `meta.json`: Full JSON dump of the invocation parameters, input options, global configuration, and deployment timestamps.
* `info.txt`: Human-readable summary containing connection URLs (noVNC port 8080, SSH, VNC passwords).
