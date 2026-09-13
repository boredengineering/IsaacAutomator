# Public pricing fixtures — never apply these

These standalone Terraform JSON configurations are synthetic pricing inputs,
not deployment instructions or approved infrastructure. They contain no real
project identity, credentials, Terraform state or user data. Do not run
`terraform apply` against them.

Each directory contains one complete machine shape and scheduling model:

- `g4-standard-48-standard`: one RTX PRO 6000, Standard scheduling.
- `g4-standard-48-flex_start`: one RTX PRO 6000, Flex-start scheduling.
- `g4-standard-384-standard`: eight RTX PRO 6000 GPUs, Standard scheduling.
- `g4-standard-384-flex_start`: eight RTX PRO 6000 GPUs, Flex-start scheduling.

All select `us-west1-c`, a private network interface, a 255 GiB Hyperdisk
Balanced boot disk, OS Login, Cloud NAT and explicit example GCS/Artifact
Registry resources. Those owner resources are included for pricing coverage;
a Terraform `backend "gcs"` block alone would not price backend storage.
The Flex runtime limit is a synthetic configuration value, not an approved
experiment duration or a cost-estimator usage override.

These fixtures do not represent the complete enterprise profile: KMS,
secrets, log retention, snapshots, additional working storage, transfer,
licensing and external services need their own inputs/assumptions. Pricing
availability does not prove GPU quota, zone capacity, deployment success,
IAP access or application compatibility.

Do not add separate GPU/CPU/RAM line items to a complete G4 machine price.
An Infracost response recognizing the VM resource is not sufficient proof
that it priced Flex-start correctly. Until actual SKU/model coverage is
verified, Flex estimates must remain explicitly partial/unsupported.
