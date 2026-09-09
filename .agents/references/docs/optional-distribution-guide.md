# Optional image and model distribution

This extends the [GCP registry guide](artifact-registry-guide.md). Execution status
and verification belong in the [implementation ledger](../plans/optional-distribution-plan.md).

## What to choose

Image distribution and model/data distribution are separate choices:

| Choice | Purpose | Target / authentication |
| --- | --- | --- |
| Disabled / omitted | Native/source installations without added distribution setup | Default |
| `gcp_artifact_registry` | Private OCI images | GCP attached service account, existing GCP helper |
| `aws_ecr` | Private OCI images | AWS EC2 instance role, keyless refreshing ECR helper |
| `dockerhub` | Public or already-authorized private Docker images | Any supported deployment cloud; anonymous or separately provisioned Docker credentials |
| `huggingface` block | Pinned model/dataset repository snapshots, not OCI images | Independent of image choice; anonymous or existing target token file |

Everything is opt-in. This does not make a private registry a prerequisite for
Isaac Sim, Lab, Arena or GR00T source installations. Omitting or disabling a block
prevents its setup; it does not uninstall helpers, erase caches, revoke remote
access or stop a previously running service. Explicit native GR00T provisioning
retires its old container service.

Only one image provider is selected per profile. Hugging Face can be enabled with
any image provider, or alone. Cross-provider image maps and automatic image
mirroring/build/publish are not implemented.

## Profile examples

Copy a generic example into `configs/private/` and keep personal identifiers there:

- [GCP](../../../configs/profiles/example-profile.yaml)
- [AWS ECR](../../../configs/profiles/example-aws-ecr.yaml)
- [Docker Hub](../../../configs/profiles/example-dockerhub.yaml)
- [Hugging Face](../../../configs/profiles/example-huggingface.yaml)

All shipped examples are disabled. The following snippets describe enabled
selections, but placeholders must be replaced with actual approved digests/commits.
They are not ready-to-run deployments.

### AWS ECR

```yaml
cloud: aws
container_registry:
  enabled: true
  provider: aws_ecr
  account_id: "123456789012"  # Replace with repository owner's AWS account.
  region: us-east-1
  repository: robotics/gr00t
  images:
    gr00t: "123456789012.dkr.ecr.us-east-1.amazonaws.com/robotics/gr00t@sha256:<64-lowercase-hex>"
```

`images: {}` configures authentication without pre-pulling images or selecting a
workload. ECR entries must use the exact configured repository, not an arbitrary
repository beneath a namespace. China and GovCloud partitions are intentionally
unsupported in this first implementation. Repository and workstation regions may
differ, but latency, routing and transfer charges need operator review.

Repository creation is a separately managed Terraform operation under
`src/terraform/registry/aws`; see its README. Workstation YAML selects consumption
and grants its dedicated EC2 role read access—it does not create or publish a
repository. Keep shared registry state separate from disposable workstation state.
The shared repository is deletion-protected; no destructive lifecycle cleanup is
automatically configured.

The VM role requires `ecr:GetAuthorizationToken` with resource `*` (the API does
not support repository scoping); image read permissions are scoped to the selected
repository ARN. This is not publisher permission. Cross-account access additionally
requires authorization in the repository owner's policy. Networking must permit
ECR API, registry and layer downloads (public egress or suitable private endpoints).
Other AWS integrations may require separately scoped permissions; ECR does not
solve all workload IAM.

### Docker Hub

```yaml
container_registry:
  enabled: true
  provider: dockerhub
  namespace: exampleorg
  auth: anonymous
  images:
    gr00t: "docker.io/exampleorg/gr00t@sha256:<64-lowercase-hex>"
```

`anonymous` uses an isolated empty Docker configuration for automated pulls.
`existing` explicitly opts into separately provisioned target-root Docker
credentials/helpers; it does not run `docker login`, copy the controller's login,
or embed a PAT in profile YAML, inventory, command arguments or Terraform state.
GR00T runs its container as root, so an SSH user's login alone is insufficient.
Docker Hub availability, pull limits, subscription and transfer costs remain
operator considerations. No Docker Hub organization/repository is provisioned.

### GCP using the provider selector

```yaml
cloud: gcp
container_registry:
  enabled: true
  provider: gcp_artifact_registry
  project: example-project
  location: us-central1
  repository: robotics
  images: {}
```

This maps to the existing GCP infrastructure and keyless role. Legacy
`artifact_registry` YAML remains accepted unchanged. Do not include both blocks,
even if one is disabled. Saved normalized GCP settings must agree with their legacy
transport fields; inconsistent metadata is rejected rather than silently repaired.

### Hugging Face alongside any image choice

```yaml
huggingface:
  enabled: true
  repositories:
    - name: policy
      repo_id: exampleorg/policy
      repo_type: model
      revision: "<40-lowercase-hex-commit>"
    - name: evaluation-data
      repo_id: exampleorg/evaluation-data
      repo_type: dataset
      revision: "<40-lowercase-hex-commit>"
  # Optional, for private/gated access, already on the TARGET:
  # token_file: /home/ubuntu/.config/isaac-automator/hf-token
```

The role stages snapshots as the resolved SSH user in that account's managed
`.cache/isaac-automator/huggingface/` tree. A name labels an artifact; it is not a
free-form destination path. Full commit pins are required, not `main`, a tag or a
short SHA. Repository code is downloaded as data, never imported or executed.
Only model/dataset repositories are supported here—not Spaces image deployment.

Private/gated downloads require a pre-provisioned readable token file and accepted
repository terms. The token value is read only on the target at runtime, never
stored in the profile or passed on the command line. Without `token_file`, the
consumer requests anonymous access rather than reusing an ambient Hugging Face
login. Do not place tokens inside image layers or public examples.

This stages files only: it does not configure GR00T's checkpoint path, bind mounts,
dataset selection, database restoration or model-serving health. Review snapshot
size, disk space, licenses and egress before enabling. No actual personal Hub
repository has been accessed or populated by this implementation work.

## Workload and security boundaries

- All image references are tag-free, lowercase SHA-256 digests.
- `images.gr00t` selects the existing root-run GR00T container service. Other image
  keys pre-pull only; they do not create services.
- Registry availability is not proof of GPU compatibility or complete local/cloud
  workstation parity. Source mounts, models, datasets and persistent state remain
  separate.
- ECR pulls use EC2 IAM with refresh, not downloaded keys. Profile credentials,
  arbitrary helper commands, custom metadata endpoints and Docker Hub PAT values
  are rejected/not supported by the schema.
- Repair validates saved normalized choices without requiring the original YAML.
  Authoritative cloud identity is checked again before Terraform/Ansible handoff.
- Full provisioning applies optional roles to source and prebuilt-image paths.
  YAML handoff is supported through deployers; dedicated TUI controls and universal
  bare-metal installer parity are not implied.
- Switching providers does not purge old cached images or remove unrelated Docker
  configuration entries. Revocation/cleanup is an explicit operator task.

### Tagged reruns

For an ECR/Docker Hub-selected GR00T container, use full provisioning or include
both `__container_registry` and `__gr00t` tags. A fresh `__gr00t`-only invocation
does not inherit the previous run's Docker configuration facts; it must fail before
stopping/changing services rather than guess authentication paths. Use
`__artifact_registry` with `__gr00t` for the legacy GCP setup. Hugging Face has its
own optional `__huggingface_artifacts` tag; it does not start model consumers.

Docker Hub cache inspection accepts Docker Engine's equivalent shortened
repository names, including official `library/` images, while still requiring the
exact namespace/repository and digest. A familiar-name cache entry is not a reason
to repull an already cached approved image.

## Live acceptance gate

No cloud provisioning, image publication, real registry login/pull, Hugging Face
snapshot download or GPU execution is part of offline verification. Before a live
run: select private profile and immutable artifacts; provision/review repository
and backend ownership; review IAM, secret delivery, networking, disk budget and
licenses; then verify actual authentication, digest availability, service mode
transitions and workload health. Stop/destroy any paid test workstation when done.
