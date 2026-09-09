# Durable AWS ECR registry (independent state)

This root is **never invoked by workstation Terraform**. It owns one shared
repository and an optional complete repository policy. Workstation destruction
removes its EC2 role/profile, not this repository or any images. No image cleanup
or ECR lifecycle policy is installed. `prevent_destroy = true` rejects repository
delete/replacement while this resource block remains; `force_delete = false`
provides additional protection for nonempty repositories. These are not a backup
or protection against an authorized console deletion/removing configuration.
Any eventual retirement needs a separate reviewed, explicitly approved process.

## Explicit backend initialization (operator only)

Use a separately provisioned, access-controlled S3 backend with versioning,
encryption and state locking. This root does not create a backend bucket, locking
table or encryption key. Use a **separate key from all workstation states** and
from other repositories. Do not run the workstation deploy wrapper for this root.
Do not reuse a workstation local backend override, state file or workspace.

After approval, initialize with your own nonsecret values, for example:

```sh
terraform -chdir=src/terraform/registry/aws init \
  -backend-config="bucket=YOUR-REGISTRY-STATE-BUCKET" \
  -backend-config="key=shared/ecr/REGION/REPOSITORY.tfstate" \
  -backend-config="region=YOUR-BACKEND-REGION" \
  -backend-config="encrypt=true" \
  -backend-config="dynamodb_table=YOUR-STATE-LOCK-TABLE"
```

The example uses the DynamoDB locking supported by Terraform 1.3.5+. For a newer
Terraform version, select a backend locking strategy supported by that version.
Backend account/region may differ from the repository owner: backend IAM must be
reviewed independently. Never pass credentials as backend arguments, tfvars or
profile YAML. Use operator-managed short-lived AWS authentication out of band.
The provider's `allowed_account_ids` refuses a repository owner account mismatch.

Set `account_id`, `region`, `repository` in a private operator-managed variable
file. Use the same values for workstation `ecr_account_id`, `ecr_region`,
`ecr_repository`, with `enable_ecr = true`. This root is commercial AWS only.
Repository names use 2-256 lowercase characters and safe namespace separators.
No registry resource is required in a workstation's state, including when the
existing repository is managed by a different owner/tool.

## Principals and cross-account access

`publisher_principal_arns` defaults to empty. Explicit existing IAM role/user
ARNs receive only push/pull on this exact repository. No root principals,
wildcards, administrator permissions, deletion, IAM creation or access keys.
Publishers need an owner-managed **identity policy** allowing
`ecr:GetAuthorizationToken` on `"*"` (AWS requires this wildcard); cross-account
publishers also need the exact-repository push/pull actions in that identity
policy. The repository policy does not grant token authorization.

`reader_principal_arns` optionally grants owner-approved pull-only access, notably
for cross-account workstations. Use their `ecr_reader_role_arn` output; the
workstation attaches its own dedicated EC2 role with token authorization and
exact-repository pull permissions. Same-account identity policy is generally
sufficient unless another policy denies access. Cross-account access requires
**both** sides' policies. Account opt-in regions, SCPs and explicit denies can
still prevent access. If a workstation role is deleted and recreated, review and
refresh the owner policy because AWS stores principal identities internally.

This root owns the **entire** ECR repository policy whenever either principal set
is nonempty. Do not manage another policy resource/manual policy concurrently;
include every intended grant in these inputs or use a separately owner-managed
repository instead. Workstation Terraform never edits the repository policy.

## Encryption and retention

Default encryption is AES256. Optional `kms_key_arn` selects an existing symmetric
customer-managed KMS key in the repository account and region. Its lifecycle and
policy stay with its owner. ECR requires the creating principal/key policy to
allow `kms:DescribeKey`, `kms:CreateGrant` and `kms:RetireGrant` as documented by
AWS. ECR creates its service grants; this stack does not create keys or grant
readers blanket KMS permissions. Do not revoke ECR grants or delete/disable the
key while images remain. Encryption is creation-time only: changing it requires
replacement, intentionally blocked by `prevent_destroy`.

## Offline verification

From the repository root: `python3 src/tests/ecr_terraform.test.py` and
`python3 src/terraform/test_ecr.py`. The second command requires Terraform >=1.7,
initializes disposable source-only copies with `-backend=false`, and runs
validation and plan-only AWS/TLS provider mocks. It downloads public providers
but never opens a real backend, uses cloud credentials or deploys resources.
Live IAM, KMS, image pulls and GPU workload health remain separate acceptance.

References:
- https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-policy-examples.html
- https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html
- https://docs.aws.amazon.com/AmazonECR/latest/userguide/encryption-at-rest.html
