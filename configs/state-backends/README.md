# Terraform backend configuration — implementation and acceptance boundaries

These files are public, offline schema examples. Their identifiers are placeholders,
not deployed storage. Validation does not create, attach, authenticate, migrate or
verify cloud resources. Do not add credentials to these files.

## Available now

From the repository root (the top-level entrypoint uses the normal container wrapper):

```sh
./state-backend validate --cloud aws --config configs/state-backends/local.yaml
./state-backend validate --cloud aws --config configs/state-backends/s3.yaml --terraform-version 1.10.0
./state-backend validate --cloud gcp --config configs/state-backends/gcs.yaml
./state-backend validate --cloud azure --config configs/state-backends/azurerm.yaml
```

The equivalent native Python entrypoint is `python3 -m src.python.state_backend_command`.
It requires the project's existing Click and PyYAML dependencies. Configuration paths
must be readable in the execution environment; the Docker wrapper does not mount
arbitrary host paths. No Terraform/cloud process is started by `validate`.

Exit 0 means **valid configuration only**, not a ready backend. JSON explicitly reports
`cloud_access: not_checked`, `remote_lifecycle: not_checked`, and a digest of normalized
nonsecret configuration plus deployment cloud. The optional `--terraform-version`
checks the supplied string; it does not discover or execute the installed binary.

The version contract accepts stable Terraform >=1.3.5,<2 for the local foundation and
>=1.10.0,<2 for remote adapters, including native S3 lockfiles. This is a feature floor,
not certification of every 1.x release. Provider/bootstrap constraints and lockfiles
still need validation before remote enablement. No tool-image/devcontainer update is
performed automatically.

## Input contract

- Standalone files accept a bare BackendSpec block or a sole `terraform_state` wrapper.
- YAML/JSON duplicate keys, aliases, merges, multiple documents, credentials, unknown
  fields, and unsafe names are rejected. Files are limited to 64 KiB.
- A profile's optional `terraform_state` block is controller configuration, not a VM
  installation option. Workspace is `default`, locking is `native`, authentication is
  `ambient`. Tokens, storage-account keys, SAS strings and endpoints are not accepted.
- AWS pairs with S3, GCP with GCS, Azure with `azurerm`. Local is also valid for Alibaba.
  Cross-cloud remote storage is not supported. Storage and workload accounts/projects/
  subscriptions may differ within one cloud; identity and permissions are not checked
  by offline validation.
- Native S3 lock configuration restricts the authenticated account, but that restriction
  does not prove bucket ownership. GCS `project` is descriptor metadata, not an init flag.
- New remote object identities include prefix, namespace, cloud, target scope and
  deployment. S3/Azure use `terraform.tfstate`; GCS uses `terraform/default.tfstate`.
  No existing v1 state is renamed or adopted by parsing a v2 descriptor.

## Explicit proposals, inspection and bootstrap

`state-backend propose` emits deterministic, loadable, nonsecret configuration. It
does not check availability, adopt storage or migrate anything. For example:

```sh
./state-backend propose --cloud aws --namespace example --owner-scope 123456789012 --region us-east-1
./state-backend doctor --help
./state-backend bootstrap --help
```

`doctor` requires `--acknowledge-reads`. It executes authenticated, read-only cloud
CLI requests and reports each check as passed/failed/unknown/not-applicable. Exit 2
and `partial` are expected when effective write/locking permissions are unproved.
Read-only inspection must not be presented as a successful write/locking probe.

`bootstrap` plans new protected storage only after explicit acknowledged reads.
It rejects pre-existing or ambiguously unavailable destinations rather than adopting
them. Applying additionally requires both `--apply` and `--approve-creation`; this
creates paid infrastructure. It is not part of workstation deploy or destroy.
Provider, identity, permission and disaster-recovery acceptance remains unverified
until separately authorized live tests run against concrete destinations.

Bootstrap administration state is separate from workstation state. The host entrypoint
maps an explicitly supplied, existing, owner-only (0700) `--bootstrap-state-root`
directory into the local Docker daemon at `/run/isaac-bootstrap-state`. That directory
must be on durable storage and retained/backed up independently. Direct container/native
invocations must likewise select durable mounted storage, not an ephemeral `/tmp` path.
Changing this root loses the local administration attachment; do not re-bootstrap as a
substitute for recovery.

## GCS deployment path

GCP deployment now accepts explicit GCS configuration, persists its destination in
the controller's deployment metadata, and uses native Terraform init, locking and
saved-plan apply. Output reads, repair and destroy use that persisted destination;
an authentication/read failure never falls back to a local state snapshot. Ordinary
deployment does not require drift approval, Neo4j, or the optional shared ledger.

Copy `gcs.yaml`, replace the bucket/project/namespace placeholders, and keep the
nonsecret configuration under the repository so the normal wrapper can read it.
Provision the backend separately or select a bucket you already administer. Then
add these options to your normal, fully specified `deploy-gcp` invocation:

```sh
--project YOUR_WORKLOAD_PROJECT --state-backend gcs --backend-config configs/state-backends/YOUR_CONFIG.yaml
```

The destination project identifies backend storage; `--project` selects workload
scope. They need not be the same project or principal. Use ADC or a deliberately
supplied `GOOGLE_OAUTH_ACCESS_TOKEN` (forwarded by name, never saved into config).
Terraform >=1.10,<2 is required. The bucket is not destroyed with the workstation.
The deployment metadata, private inputs and SSH trust/key material still need a
durable controller directory: remote Terraform state is not a backup of all these files.

The GCS runner has passed a live provider-free apply/read/destroy experiment in
`cybernetic-renan`. A separate native Terraform experiment created, stopped, started
and destroyed a private VM. This is not full GPU/Isaac installation or live IAP
transfer acceptance. See the dated acceptance report in the implementation plan.

S3/Azure ordinary remote execution, complete cross-controller attachment/migration,
and remote drift execution are not enabled by this GCS slice. Existing protected
claim/manifest and migration records retain their separate reconciliation path;
they cannot be silently adopted through the simpler native GCS bridge.

Built-in `team`/`enterprise` presets no longer imply a state bucket. Existing YAML
profiles that specify legacy remote `security.storage` settings remain remote intent
and are refused for execution; `auto` never provisions a bucket. For **new local**
deployments, an explicit `--state-backend local` can override a profile's remote intent.
It cannot redirect an existing remote/ambiguous attachment. Existing metadata must be
verified; changing a profile is not a migration.

`destroy` refuses absent, malformed, unreadable, symlinked or ambiguous local state and
unresolved protected attachments. For GCS it pulls authoritative remote state. After
a successful Terraform command it checks state identity
and remaining managed resources before removing recovery files. This temporary legacy
guard now uses one isolated saved-plan operation and cleans up while holding its
controller lock. Pending migration/retirement markers freeze legacy local commands
without reading or automatically following redirects. If a deployment is
already empty, do not delete its directory merely to silence the error: verify ownership
and recovery first. Local outputs now fail explicitly when state is unavailable rather
than returning a misleading empty string; optional missing output fields still return
an empty value. Unknown provenance of an unmarked legacy snapshot cannot be resolved by
these checks alone.

The host `run` wrapper preserves command failure status and does not allocate a TTY in
headless sessions. Explicit multi-cloud credential-file references are mounted read-only
only for a verified local Docker daemon; allowlisted secret environment variables are
forwarded by name, not embedded as values in Docker arguments. See
[credential transport](credential-transport.md) for boundaries and unsupported modes.
This transport is not an authorized write probe or proof of effective cloud identity.

## Runner recovery boundary

If Terraform leaves `errored.tfstate`, the isolated runner retains private staging
instead of deleting possible recovery state, and refuses overall success even when a
Terraform command returned zero. Callers must inspect its read-only
`recovery_directory` and `recovery_state` properties after failure. A recovery path
is only a candidate, not verified usable state. Retained staging can contain secrets.
Deployment/lifecycle callers now stage beneath the selected
state root's `.terraform-operations/`, which survives container removal when that root
is mounted durably. Direct runner callers must explicitly select a durable
`staging_root`; the default temporary staging remains **not reboot-durable**.
Secure retained artifacts and review recovery manually before retrying.
Nothing automatically restores, pushes or publishes that state. Ordinary runs still
remove staging and release the controller lock; recovery retention also releases it.

## Next gates

Follow [the implementation plan](../../.agents/references/plans/terraform-remote-backend-plan.md):
provider/bootstrap compatibility, isolated runner integration, durable descriptors and
fresh-controller recovery, safe lifecycle/attachment/migration, then drift and approved
correction. `./drift workflow preview` and `generate` support inert, report-only
Actions output outside `.github`; generation does not verify GitHub trust/protections
or activate a schedule. Shared evidence verification remains an optional component,
not a selected or activated hosting service. See the
[work log](../../.agents/references/plans/terraform-remote-backend-implementation-log.md)
for implementation/review status. Live acceptance and cloud spending
need separate approval and concrete provider/identity/budget choices.
