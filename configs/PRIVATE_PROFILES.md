# Private workstation profiles and cloud/local parity

Personal profiles belong in `configs/private/`, not in tracked example presets.
This directory is excluded by both `.gitignore` and `.dockerignore`. Keep private
files owner-readable only; never force-add them, paste them into issues, or put
credentials in them. Back them up separately using private storage.

The public installer presets use official upstream repositories and disable
automatic fork creation. For a customized **legacy native installer profile**,
copy `isaac-installer/config/example-profile.yaml` into `configs/private/`, edit
its placeholders, and pass its explicit path with `--config`. A **cloud security
profile** can likewise live there and be passed by explicit path to `--profile`.
These two existing schemas are not interchangeable.

## Private observed baseline

`configs/private/host-workstation.yaml`, when present, is an observed configuration
baseline. It uses `kind: workstation-baseline` and
`schema_version: workstation-baseline/v1`. It is deliberately **not executable**:
cloud and installer profile loaders reject it rather than silently installing
legacy defaults. The prior development preset may be retained privately as
`configs/private/previous-default-profile.yaml`; it is historical intent, not
proof of what is currently installed.

The baseline separates:

- `observed.host`: hardware, operating system and workspace information, with
  the probe source/visibility limits recorded.
- `observed.repositories`: actual branches, exact commits, submodule locations
  and tracked-change counts. Do not discard changes to produce a clean snapshot.
- `observed.services`: image IDs/digests, mounts, networking and runtime-specific
  Python/package versions. Package presence is not an end-to-end health check.
- `mirror_contract`: properties that must match across local and cloud targets,
  target-specific substitutions, and unresolved capture/provisioning requirements.
- `status`: capture completeness, provisioning readiness and parity verification.

No credentials, secret environment variables, private keys or database passwords
belong in the baseline. Keep secret references separate from secret values.

## What mirroring means

The same robotics stack should be reproducible on local and cloud targets:
repository/submodule revisions, container image content, per-runtime dependency
versions, service interfaces and container-side mount paths. Host usernames,
absolute source paths, instance types, network topology and secret delivery are
target-specific overlays. Copying datasets, model weights and database contents
is a separate authorized operation, not an implicit consequence of mirroring.

Mutable local image tags are insufficient to reproduce a machine elsewhere.
Private images need a private registry digest or a reproducible build recipe.
Likewise, a branch name does not capture uncommitted changes. Distinct development,
simulation and inference environments must not be collapsed into one Python or
PyTorch installation just because they share a GPU.

## Current implementation boundary

The cloud loader normalizes security settings. `src/ansible/inventory.template`
does not transport the complete robotics profile, and the local Bash installer
primarily targets native standalone/Conda installations. Writing a YAML file does
not close this gap. Cloud example fields such as `workstation.base_profile` do not
yet establish actual inheritance of the installer stack.

Before a baseline can become deployable:

1. Complete the native-host audit and select/verify intended active runtimes.
2. Capture secret-free service launch specifications and reproducible images.
3. Define a shared robotics-stack schema plus local/cloud infrastructure overlays.
4. Implement explicit consumers in the local, Ansible and Packer paths, rejecting
   unsupported settings rather than ignoring them.
5. Compare resolved manifests in tests and verify the actual robotics workload on
   both targets before marking parity as verified.

## Privacy scope

Ignoring new files does not remove information from already tracked documents,
prior commits, published images or remote repositories. Existing historical
references need a separate privacy review; do not rewrite Git history or delete
operational records as an automatic cleanup step.

Run the regression checks with `python3 src/tests/profile_privacy.test.py`.
