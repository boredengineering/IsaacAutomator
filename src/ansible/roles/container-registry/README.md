# Optional container registry consumption

AWS ECR and Docker Hub configuration and approved digest pulls run before GR00T
service changes. Run the full play normally. For a targeted GR00T rerun with a
selected generic registry image, use `--tags __container_registry,__gr00t`.
`--tags __gr00t` alone fails before service changes when registry prerequisites
are absent in the current invocation, even on a previously provisioned host:
Ansible's resolved root Docker configuration fact is not persisted between runs.
Do not supply that internal fact manually to bypass authentication/image setup.

Docker Hub inputs remain fully qualified, digest-pinned `docker.io/namespace/repo`
references. Cache checks also accept Docker Engine's familiar RepoDigests
(`namespace/repo@sha256:…`, or `repo@sha256:…` for `docker.io/library/repo`).
The complete repository and digest must match; another namespace or digest does
not satisfy the cache check. Cached images are not pulled again.
