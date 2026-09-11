# The overall picture


We’ve been building three connected parts:

- Isaac Automator: provisioning and managing cloud GPU workstations.
- isaac-installer: installing and maintaining the robotics stack on a local/bare-metal workstation.
- Supporting tools: the isaac9s terminal interface, optional artifact distribution, and a codebase evidence graph.

1. Cloud workstation foundation

Need to implement the same profile idea done for the isaac-installer.

2. Local robotics installer—and the parity problem

The local installer gained modular support for Sim, Lab, Arena, GR00T and LeRobot, alongside:

- Conda/UV environment setup and isolation.
- Blackwell-specific dependency handling.
- Workspace organization, fork/upstream remotes and version switching.
- Installation-state tracking and drift repair.
- Native and Docker execution paths.

However, our later review found that local and cloud installation are still not equivalent.

Important gaps included Python/version defaults, GR00T/LeRobot environment isolation, incomplete profile-to-Ansible transport, requested-version handling on reruns, failure propagation, and GR00T service/port wiring.

Those findings were documented and we still need to work to resolve that entire parity backlog. Earlier “complete compatibility” claims were too broad.

This needs a better plan and it goes back to the profile idea done for the isaac-installer.

3. Optional registries and model distribution

We implemented optional:

- GCP Artifact Registry.
- AWS ECR and Docker Hub image selection.
- Pinned Hugging Face model/dataset staging.

The implementation was reviewed and exercised with offline tests and mocked Terraform plans. Those checkpoints explicitly did not claim live registry pulls or complete workstation deployment.

Need to proceed with the live test to see if we can provision the machines properly and create the images as well.

4. Evidence graph and Neo4j


We built a sandboxed source-evidence index with RDF/PROV/SHACL, bounded queries and a dedicated Neo4j visualization service.

Verified milestones included:

- Indexing public source evidence and validating it.
- Importing and reading back 226 claim records in Neo4j.
- Authentication and persistence checks.
- A bounded advisory-agent interface and usage guide.
- A recorded 120-test graph suite pass.

The key architectural distinction: RDF is authoritative; Neo4j is a derived snapshot. This is not automatic local/cloud database synchronization, nor proof that indexed deployment code works at runtime.

5. Most recent implementation: GCS state and file sync


We implemented:

- Explicit backend selection, keeping local state as the default.
- An isolated Terraform runner and persisted backend identity.
- GCS execution and integration with deployment/lifecycle operations.
- Authoritative output reads and safer destroy/recovery behavior.
- Selected-directory upload/download using rsync.
- IAP/OS Login connection selection.
- Dry-run, exclusions, retries and opt-in deletion for transfers.
- Private noVNC tunneling without passwords in connection URLs.

Optional drift automation and shared-ledger features were kept separate from ordinary GCS deployment.

The final recorded scoped regression was 536 passed and 1 skipped across 35 suites—not an all-repository acceptance result.

6. What actually ran in GCP


In project cybernetic-renan, the previous session verified:

- Real GCS object operations and generation-match collision rejection.
- Terraform state persistence and output reads from a fresh controller directory.
- The Automator runner’s GCS apply/output/destroy path using a provider-free fixture.
- Creation, security checks, stop/start and destruction of a private e2-micro VM.

All seven experiment buckets and the test VM, disk, firewall, subnet and VPC were verified deleted at the end of those experiments.

The e2-micro test validated infrastructure mechanics only. It did not satisfy your RTX PRO 6000 acceptance requirement.

Where we stopped


The next acceptance target was g4-standard-48 with one RTX PRO 6000, preferably in us-west1.

The last session reported available quota, but actual capacity was unverified. Effective IAP tunnel permission was missing. The authorization question timed out, so no IAM grant or GPU launch occurred.

Still outstanding:

- Live private IAP SSH and rsync acceptance.
- Full RTX PRO 6000 workstation provisioning and robotics runtime validation.
- Local/cloud installer parity fixes.
- Complete S3/Azure workstation backend execution and general migration/attachment.
- The wider optional drift/shared-evidence roadmap.

Current checkout


I checked Git now: branch devcontainer, clean working tree, HEAD 1cdc4f0. The test and cloud results above are recovered historical evidence; I have not rerun them in this turn.

The latest detailed acceptance record is:
.agents/references/plans/terraform-gcs-acceptance-20260911.md

Bottom line: we now have implemented GCS deployment plumbing and file-transfer integration, backed by offline tests and bounded live infrastructure experiments. We have not yet demonstrated the complete private RTX PRO 6000 Isaac workstation deployment end to end.