# GCP Artifact Registry: architecture, operation and agent handoff

Implementation ledger: [artifact-registry-plan.md](../plans/artifact-registry-plan.md).
This guide describes repository capabilities, not a completed cloud deployment.
No API was activated, repository created, image published, or GPU VM started by
this implementation task. Live acceptance remains separately authorized work.

For the newer provider-neutral `container_registry` selector (GCP, AWS ECR,
Docker Hub) and independent Hugging Face snapshots, see the
[optional distribution guide](optional-distribution-guide.md). The GCP-only
restrictions below describe this legacy `artifact_registry` block and role,
not all distribution choices. Existing profiles remain supported unchanged.

## 1. Ownership and lifecycle

| Layer | Owner / code | Responsibilities |
| --- | --- | --- |
| Shared registry | `src/terraform/registry/gcp/` | Regional Docker repository, API activation, optional existing CMEK, scoped publisher IAM. Separate GCS backend state; repository protected with `prevent_destroy`. |
| Workstation | `src/terraform/gcp/` and `ovkit/` | Consume an existing repository, attach dedicated VM identity, grant repository-scoped reader, use cloud-platform access scope. No repository ownership. |
| Host configuration | `src/ansible/roles/artifact-registry/` | Configure root and SSH-user Docker helpers, pull approved image digests, select the GR00T container service when explicitly listed. |
| Image production | Separately reviewed build/publishing workflow | Build, test, license/secret review, publish, record digest. Not run by Ansible or workstation Terraform. |
| Private desired state | Ignored `configs/private/` profile | Real project/repository settings and approved image digests. Never copy workstation fingerprints into public presets. |

Create a shared repository once or use an existing regional Docker repository.
Workstation teardown removes its own reader membership/service account; it does
not remove the repository or image contents. Shared registry storage continues to
incur charges independently of VM lifetime. No automatic image-deletion policy
is installed. `prevent_destroy` is a plan-time guard, not an IAM protection against
manual deletion, and removing the entire protected resource block can bypass it.
Keep the shared Terraform configuration/state and any CMEK key durable and backed up.

The shared root's GCS backend requires an already-provisioned state bucket and a
unique prefix. Do not reuse a workstation's state key. Never copy a generated
`backend_override.tf.json` from a disposable deployment into the shared root.
Use the root's [README](../../../src/terraform/registry/gcp/README.md) for exact
variables and initialization commands. Existing repositories can be consumed
without importing them; import only if deliberately transferring ownership to
the shared stack, after reviewing the full plan.

## 2. Profile contract (executable)

The optional top-level block is independent of the still-incomplete
`workstation` robotics-stack schema. Public `example-profile.yaml` includes a
disabled version. Personal settings belong in `configs/private/`.

```yaml
schema_version: "v1alpha1"
profile_name: "private-registry-workstation"
cloud: "gcp"
security:
  tier: "custom"
  network:
    iap_only: true
  compute:
    os_login: true

artifact_registry:
  enabled: true
  project: "example-project"   # Replace with repository-owning project ID
  location: "us-central1"       # Regional repositories only in this version
  repository: "robotics"
  images: {}                   # Auth-only setup; no container started
  # To consume published images, replace {} with a mapping like:
  # gr00t: "us-central1-docker.pkg.dev/example-project/robotics/gr00t@sha256:<64-lowercase-hex>"
  # arena: "us-central1-docker.pkg.dev/example-project/robotics/arena@sha256:<64-lowercase-hex>"
```

The digest placeholders above are deliberately NOT runnable values. Obtain the
real registry digest from the approved publisher. Mutable tags (`latest`),
tag-plus-digest references, images from another repository, unsupported fields,
malformed mappings and string booleans are rejected. Enabled profiles require
`cloud: gcp`; other deployers reject enabled registry consumption. All images in
one profile belong to the configured repository. Multi-region repositories,
remote/virtual repositories and cross-registry image sets are not supported here.

- `images.gr00t`: selects the GR00T container service and its image digest. It does
  not install native GR00T dependencies for that container path.
- Other names: pre-pull/cache only. No Arena, Neo4j, or arbitrary service is created
  merely because its image appears in the map.
- `images: {}`: configure authentication without pulling or starting images.
- `enabled: false` or omitted block: no registry infrastructure/host setup added.
  Disabling is not an uninstall operation: existing cached images, helper files,
  Docker configuration, or previously started services are not automatically removed.

Enabling the registry does not turn a native workstation inventory into a fully
executable mirroring profile. It does not migrate models, datasets, source mounts,
Git dirty worktrees, Neo4j data, Docker volumes, ports, or all container arguments.
The GR00T service expects a compatible image entrypoint/layout and model data at
its configured host mount. Match these to the selected image before deployment.

The full workstation play orders registry configuration/pulls before GR00T.
For a selective registry-backed GR00T rerun, include both `__artifact_registry`
and `__gr00t` tags; selecting only `__gr00t` skips the registry dependency's tag.
Docker/NVIDIA runtime setup must already exist when skipping the system role.
Use normal full provisioning for a new workstation.

Repair and saved-state Ansible reruns validate the saved normalized registry
settings; they do not need the original YAML to still exist. They do not adopt
new YAML image selections automatically. Use the explicit modify workflow to
apply changed desired settings. Rejected profiles or saved registry metadata do
not overwrite the existing deployment metadata, and concrete deployer identity
takes precedence over a saved/spoofed cloud string.

An explicit switch back to native GR00T (`install_gr00t: true`, native serving
mode, no registry `gr00t` image selected) stops/disables the old container before
native provisioning. Merely disabling the registry or omitting GR00T installation
is not an uninstall operation and leaves an already-running workload alone.

## 3. IAM, encryption and networking

The registry project may differ from the VM project. The deployment identity
needs permission to enable the registry API and manage repository IAM in the
registry project, plus the existing VM/service-account permissions in the VM
project. Workstation reader grants do not grant publishing or administration.
A separate explicit publisher identity receives repository-scoped writer from
the shared stack. Prefer federation or approved interactive credentials for that
publisher; do not download service-account keys.

The VM project must already have `iam.googleapis.com` enabled to create the
dedicated VM service account, and Service Usage must be available for API
management. This feature manages the Artifact Registry API, not those project
bootstrap prerequisites. Check IAM API readiness even for simple/team opt-in;
mocked Terraform plans do not establish it.

**Identity migration warning:** opting in changes the attached VM identity to a
dedicated service account. The corrected enterprise-tier forwarding can also
select that existing dedicated-SA path on an upgraded enterprise deployment.
Terraform may stop/update the VM to change its identity. The new account does not
inherit the default Compute Engine account's permissions: this feature grants
registry reader only, not backup-bucket, Secret Manager or telemetry permissions.
Before applying, explicitly provision any required bucket-/secret-scoped or
telemetry grants and verify them against the actual attached account. Do not
restore broad Editor access as a workaround.

The VM obtains short-lived OAuth access tokens from its attached service account
through the fixed Compute Engine metadata endpoint. The Docker helper exposes a
token only through Docker's credential protocol for its configured registry host;
it does not write tokens to disk or use environment-configurable metadata URLs,
HTTP proxies or redirects. Root and the resolved SSH account get a host-specific
`credHelpers` entry. Unrelated Docker settings remain intact. Existing static auth
for the selected host is removed and config files/directories get owner-only
permissions. Never execute the helper's `get` operation in a logged terminal: its
successful stdout is a credential intended only for Docker.

Each account's configuration merge runs in its own module process. Before any
SSH-user home/config access, the module permanently drops root and supplementary
groups to that account. This prevents user-controlled directory swaps from
redirecting privileged writes. Inaccessible/root-owned user configs fail closed;
an administrator must repair their ownership separately rather than this role
attempting privileged repair of user-controlled paths.

Repository CMEK is an explicit `kms_key_name` in the shared registry stack, using
an existing key in the repository region. The Artifact Registry service agent
receives key-scoped encrypt/decrypt permission. Workstation disk CMEK settings do
not implicitly configure repository CMEK. The key must outlive all dependent
images; deleting/disabling it can make them unreadable.

IAM-private does NOT mean VPC-perimeter isolated. The workstation subnet already
has Private Google Access, and IAP-only deployments use Cloud NAT for other
outbound downloads. Verify actual DNS/routing, HTTPS egress, organization policies,
and any VPC Service Controls perimeter before claiming private-path enforcement.
No public registry IAM grant or new inbound firewall rule is needed for image pulls.

## 4. Publishing boundary and reproducibility

Before any upload, obtain explicit authorization for the destination and images.
Review Docker build context, licenses (including redistribution terms for NVIDIA
components), image layers, caches and build logs for secrets/personal data. A local
Docker image ID is not proof of a pullable registry digest. Container images also
do not include data in bind mounts or named volumes.

A separate approved publishing session should:
1. Select the authoritative source revision/build recipe and target CPU/GPU stack.
2. Build and test without embedding credentials; use approved publisher identity.
3. Tag and push the reviewed image to the configured repository.
4. Record the registry manifest digest, not just the mutable tag or local image ID.
5. Verify a pull by digest and the expected runtime independently.
6. Put the digest in the private profile; retain build provenance and licenses.

No build/push wrapper or automatic publication was added. The VM's read-only
identity must not be reused as a publisher. Image availability does not establish
Blackwell/Ada CUDA compatibility, model availability, or end-to-end inference.

## 5. Offline verification and live acceptance

From the repository root:

```sh
PYTHONPATH=. sh src/tests/run_all.sh
ANSIBLE_CONFIG=src/ansible/ansible.cfg ansible-playbook --syntax-check \
  -i 'localhost,' src/ansible/isaac-workstation.yaml
```

The registry test files cover the real profile/deployer/INI handoff, invalid input,
disabled isolation, credential helper protocol with synthetic metadata responses,
Docker configuration merging/idempotence, and Terraform contracts. Tests must not
access live metadata or modify the operator's Docker config. Terraform mock-provider
tests need Terraform >=1.7 and initialized provider plugins; see the shared root's
README and implementation ledger for tested commands/version details. Test in a
temporary copy without deployment state or backend override files. Do not run
`terraform apply`, `destroy`, a refreshing real plan, or `./deploy-gcp --dry-run`
merely to exercise offline validation.

Before a separately authorized live deployment:
- Confirm shared state ownership/bucket and repository existence/format/location.
- Confirm billing, GPU quota/capacity, deployer permissions, actual attached VM
  identity, reader IAM propagation, scopes and organization policies.
- Verify any CMEK key/service-agent grants and independent key lifetime.
- Verify registry network access and digest pull using Docker, without printing tokens.
- Check second-pass provisioning idempotence and correct service restart behavior.
- Supply model/dataset mounts and run an agreed GPU/application smoke test.
- Verify workstation teardown leaves the shared repository/images intact.

## 6. Future-agent entry point

1. Read the implementation ledger and latest indexed `.agents/memory/` checkpoint.
2. Inspect live Git status; do not treat this guide as proof of current deployment.
3. Trace profile normalization -> Deployer -> Terraform variables -> Ansible
   inventory -> registry role -> GR00T service before claiming executable support.
4. Keep Artifact Registry and Packer machine images distinct. `image-*` profile
   propagation and Packer identity provisioning are not included in this change.
   Registry settings are YAML-driven; no registry-specific TUI controls were added.
5. Keep personal settings private; do not infer upload/deploy permission from the
   existence of a profile or this runbook.
6. Update the ledger and checkpoint with actual commands/results and unresolved
   gates, never plausible-looking synthetic cloud output.

Reference documentation:
- https://cloud.google.com/artifact-registry/docs/docker/authentication
- https://cloud.google.com/artifact-registry/docs/access-control
- https://cloud.google.com/artifact-registry/docs/cmek
- https://cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling
