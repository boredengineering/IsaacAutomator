# Durable GCP Artifact Registry

This **separate Terraform root** manages shared images infrastructure, not a
workstation. The workstation stack only consumes an existing repository. No
workstation deploy/destroy command invokes this root. Creating a repository does
not build, upload, run, or license any image.

## Operator-owned lifecycle and state

Use an **existing durable GCS state bucket** and a dedicated backend prefix,
never a workstation's backend/state or a bucket scheduled for workstation
teardown. This root requires explicit backend initialization; it does not create
a state bucket. Protect and back up the state bucket independently.

After obtaining authorization and authenticating locally, an operator can run:

```sh
terraform -chdir=src/terraform/registry/gcp init \
  -backend-config='bucket=YOUR_DURABLE_STATE_BUCKET' \
  -backend-config='prefix=shared/artifact-registry/PROJECT/REPOSITORY'
terraform -chdir=src/terraform/registry/gcp plan \
  -var='project=images-project' \
  -var='location=us-central1' \
  -var='repository=workloads'
```

These are operator instructions, not part of automated workstation deployment.
Review the plan before any separately authorized apply. Never run a registry
stack destroy as part of VM cleanup. Keep backend coordinates with your durable
infrastructure records and do not point multiple state files at the same repo.

`prevent_destroy = true` blocks Terraform repository deletion/replacement while
its resource block remains in configuration. It does **not** block manual cloud
deletion, image deletion by writers, or removing the resource block itself.
The API uses `disable_on_destroy = false`. No automatic image cleanup policies,
public IAM bindings, or KMS keys are created.

## Inputs and permissions

| Input | Purpose |
| --- | --- |
| `project` | Required explicit repository project ID |
| `location` | Required regional location, e.g. `us-central1` (not `us`) |
| `repository` | Required Docker repository ID |
| `kms_key_name` | Optional existing CryptoKey ID; empty uses Google-managed encryption |
| `publisher_members` | Set of explicit IAM principals; empty grants no publishers |

A CMEK input must be `projects/KEY_PROJECT/locations/REGION/keyRings/RING/cryptoKeys/KEY`
and match the repository region. The key and its API must already exist and
outlive the repository. The root generates the Artifact Registry service identity
with the `google-beta` provider, then grants that identity
`roles/cloudkms.cryptoKeyEncrypterDecrypter` **on the supplied key only**, before
creating the repository. A cross-project key requires IAM administration rights
in its owning project. No key material or service-account keys are handled here.

Publishers receive additive `roles/artifactregistry.writer` membership on this
repository only. Supported member forms are `serviceAccount:`, `user:`, `group:`,
`principal://`, and `principalSet://`; public/domain-wide grants are rejected.
The operator needs permission to enable Artifact Registry, create repositories,
and set repository IAM in the images project, plus key IAM rights when using
CMEK. IAM propagation and organization policy remain live acceptance checks.

Outputs include the full resource `repository_id`, Docker `repository_url`, and
`project`, `location`, `repository` for consumption. Image consumers should use
`LOCATION-docker.pkg.dev/PROJECT/REPOSITORY/IMAGE@sha256:DIGEST`, not mutable tags.

## Workstation contract

The GCP workstation root accepts these optional variables:

```hcl
enable_artifact_registry     = false
artifact_registry_project    = ""
artifact_registry_location   = ""
artifact_registry_repository = ""
```

When enabled, all three repository coordinates are required explicitly; the
project is never inferred from the VM project. The repository must exist before
the workstation plan/apply. The stack enables Artifact Registry in the repository
project and adds repository-scoped reader membership for the dedicated service
account actually attached to the VM, with `cloud-platform` scopes. This applies
to simple, team, and enterprise tiers. VM creation depends on the reader grant;
this ordering cannot guarantee IAM propagation has completed. Cross-project
consumption requires permissions to manage repository IAM/API in that project
and create/attach service accounts in the VM project. Disabled mode creates no
registry API resource or reader binding. `security_profile` is now passed through
the root; enterprise therefore correctly selects the existing dedicated-SA path.

**Upgrade warning:** changing the attached service account may stop/update an
existing VM. The dedicated account does not inherit default-account permissions.
This feature grants registry reader only; it does not grant access to backup
buckets, Secret Manager or logging/monitoring. Explicitly arrange least-privilege
permissions for those workloads before applying an identity migration. Do not
grant broad Editor access to compensate. Inspect the full plan even when only
enabling the registry or upgrading an existing enterprise deployment.

The VM project needs the IAM API (`iam.googleapis.com`) enabled before creating
its dedicated service account, including simple/team registry opt-in. Service
Usage must be available to manage project APIs. These are project bootstrap
prerequisites, not APIs managed by this registry feature; verify their readiness
and the deploying identity's permissions before a real deployment.

## Offline verification

From the repository root:

```sh
python3 src/tests/artifact_registry_terraform.test.py
python3 src/terraform/test_artifact_registry.py
terraform fmt -check -recursive src/terraform/registry/gcp
```

The Python runner copies only Terraform source and test files to temporary
directories, excluding backend overrides, tfvars, state, and existing `.terraform`
directories. It runs `init -backend=false`, `validate`, and provider-mocked
`terraform test` plans for the workstation root, identity module, and this root.
Terraform **>=1.7** is required for mocked tests (verified with 1.8.5); provider
installation can require network access, but no cloud API, apply, or refresh is
performed. Verified providers: Google/Google Beta 8.2.0 and TLS 4.4.0. Computed
service-account emails are unknown in mocked plans on Terraform 1.8; source-level
guards additionally verify reader/VM identity wiring and lifecycle dependencies.

These tests do not establish live IAM propagation, key availability, metadata
identity, network egress, image publishing, or successful GPU workloads.
