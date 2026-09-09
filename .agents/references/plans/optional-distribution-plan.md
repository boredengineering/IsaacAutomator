# Optional image and model distribution

Status: implementation complete, independent reviews approved; local code and offline verification only (2026-09-09).

## Contract

Existing `artifact_registry` remains supported, GCP-only. New `container_registry` is optional (omitted or enabled: false means no setup), and cannot coexist with an explicit legacy `artifact_registry` block. It selects one provider per profile:

- `gcp_artifact_registry`: enabled, provider, project, location, repository, images. Normalizes into the existing GCP contract and retains keyless authentication.
- `aws_ecr`: enabled, provider, account_id (12 digits), region (commercial AWS region), repository (one exact ECR repository), images (workload -> exact repository @sha256 digest). Requires cloud: aws. Dedicated attached EC2 role has token authorization plus repository-scoped pull permissions. A separate protected shared Terraform stack creates repositories; workstation teardown does not delete images. Cross-account pull also requires an owner-managed repository policy.
- `dockerhub`: enabled, provider, namespace, auth (`anonymous` default or `existing`), images (workload -> docker.io/namespace/image@sha256 digest). Works across deployment clouds. Anonymous pulls use isolated empty Docker config; existing auth uses operator-provisioned target root configuration. No token values in YAML or state; no registry creation.

Normalized new contract is `container_registry` (validated mapping). Inventory carries `container_registry_json` as serialized JSON (Ansible must also accept an already decoded mapping). GCP produces legacy enabled fields for existing Terraform/role consumption; new Ansible role handles only AWS/Docker Hub. AWS tfvars: enable_ecr, ecr_account_id, ecr_region, ecr_repository. Omitted/disabled choices emit no new Terraform variables.

Hugging Face is independently optional under `huggingface`: enabled, repositories list. Each entry: name (safe local cache label), repo_id, repo_type (`model` or `dataset`), revision (40 lowercase hex commit). Optional top-level token_file references an existing target SSH-user-readable absolute file; never contains a token value. Downloads run as resolved SSH user into a managed home cache, without executing repository code. No automatic service mounts or model selection. Normalized mapping `huggingface`; inventory `huggingface_json`. Can coexist with any or no image registry. Private repository IDs remain in ignored private profiles, generic examples only.

## Work ownership

- Parent: Python image schema/loader/deployer/inventory, integration tests, public examples and reference continuity.
- Terraform worker: AWS shared registry stack, EC2 reader IAM/instance-profile integration, dedicated offline/mock tests.
- Ansible worker: new container-registry role, ECR credential helper, Docker Hub pulls, GR00T selection, workstation dependency insertion, dedicated tests. Preserve reviewed GCP role behavior.
- HF worker: standalone Python HF schema module, new huggingface-artifacts role and dedicated tests. Parent owns loader/deployer/inventory and role dependency insertion for HF.

## Verification and acceptance

Test-first vertical slices, disabled compatibility, malformed configurations, saved-state repair/cloud identity, actual INI transport, digest pinning, scoped IAM, no credential leakage, role disabled/from-image paths and GR00T transitions. Run existing tests and mocked Terraform plans; record limitations honestly. No deployments, cloud changes, image/model downloads, uploads, credentials reads, commits or pushes during implementation.

## Remaining live gate

Operator selects real private profile, approved digests and model commits, registry/backend ownership, authentication/secret delivery, license permissions and data/mount requirements. Live pulls, IAM and GPU service health require separate authorized acceptance.

## Execution and review ledger

- Profile/controller path implemented: optional provider selection, legacy GCP bridge,
  cloud identity checks, normalized saved-state repair and actual Ansible INI transport.
  Independent Python review approved; public examples remain disabled and generic.
- AWS infrastructure implemented and independently approved: separate protected ECR
  stack, explicit publishers/readers, optional existing KMS key, attached EC2 role
  with repository-scoped pulls and IMDSv2. Parent and reviewer both ran 44 mocked
  plans (7 root, 17 instance, 20 registry), with all 3 configurations validating.
- Existing GCP regression: parent reran 17 mocked plans, all passed. Mocked AWS + GCP
  total is 61; public provider downloads only, no authenticated cloud operations.
- Ansible image consumers implemented: ECR helper refresh and sanitized environment,
  Docker Hub anonymous/existing-auth modes, exact digest cache/prepull, GR00T service
  selection, symmetric service-mode transitions and canonical/legacy GCP agreement.
- HF consumer implemented: pinned snapshots, target-token-file reference, non-root
  user cache, isolated client venv, no repository code execution. Parent added safe
  ASCII token paths and system venv setup. Review caught the Ansible pip module's
  additional system dependency; fix installs `python3-packaging` and explicitly uses
  `/usr/bin/python3` for that module. Enabled lifecycle regression proves both changes
  necessary, root only for package prerequisites, user UID for pip/download, and
  idempotent second runs. Final HF review approved; 18 HF tests passed without skips.
- Image-role review caught Docker Engine's familiar Docker Hub RepoDigests causing
  repeat pulls and a tagged `__gr00t` run selecting a container without its per-run
  Docker configuration fact. Regression fixes normalize only equivalent image names
  and require prerequisites before service effects. Final image-role review approved:
  23 image-role tests, 27 legacy GCP role tests and 3 independent adversarial probes
  passed. The prerequisite follows both existing fact tasks to preserve legacy test
  extraction while remaining ahead of all service effects.
- Disabled source/prebuilt-image role smoke test: changed=0, failed=0. Terraform
  formatting checked on 31 changed/new files; Python in-memory compilation, added
  production-code security scan and diff whitespace passed. Final full-suite rerun
  passed all **195 current-workspace tests** (18 profile GCP, 27 GCP role, 2 GCP TF
  contract, 17 AWS CLI, 23 generic registry role, 40 deployment command, 22 deployer,
  9 distribution integration, 6 ECR TF contract, 18 HF, 1 TUI, 4 privacy, 8 utilities).
  Final Ansible syntax check passed. Full suite log:
  `/tmp/optional-distribution-final-tests.log`.
- Black/isort/flake8/ansible-lint binaries unavailable; no such lint pass claimed.
  Existing TUI ResourceWarnings and the previous clean-checkout ignored initializer
  caveat remain outside scope (see original GCP ledger).
- No private profiles edited; no real repository identifiers or tokens copied into
  examples; no cloud resources, remote images/models, commits or pushes created.
