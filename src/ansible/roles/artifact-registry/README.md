# Keyless Artifact Registry consumption

This opt-in role runs after `system`/Docker and before image consumers. It requires
GCP, an attached VM service account with repository-scoped Artifact Registry reader
permission and suitable OAuth scopes, and Python 3 already on the workstation.
It does not install gcloud, create a repository, grant IAM, publish images, or use
service-account keys.

## Inputs

- `enable_artifact_registry`: boolean (default `false`); INI `true`/`false` strings
  are accepted, not arbitrary truthy strings.
- `cloud: gcp` when enabled.
- `artifact_registry_project`: GCP project ID.
- `artifact_registry_location`: **regional** location, e.g. `us-central1`;
  multi-regions such as `us` and `eu` are intentionally unsupported.
- `artifact_registry_repository`: repository ID.
- `artifact_registry_images_json`: JSON object string, or mapping already decoded
  by Ansible's inventory/templating. Default `{}` is authentication-only setup.
  Workload keys match `[a-z][a-z0-9_-]*`. Every value must be a tag-free image
  reference inside the exact configured project/repository with a lowercase,
  64-hex-character `@sha256:` digest.

Direct Ansible inputs are validated before this role's remote changes, even when bypassing
Python deployment normalization. Disabled mode does not require registry variables
or modify the host, preserving Packer, from-image, and non-GCP defaults. It does
not uninstall previously configured authentication or stop an existing service.
The role tag is `__artifact_registry`; do not skip it when changing images.

## Credential and configuration behavior

`/usr/local/bin/docker-credential-isaac-artifact-registry` implements Docker's
credential-helper protocol using only Python's standard library. For `get`, it
accepts only the exact host in root-owned
`/etc/isaac-automator/artifact-registry.json` (a public, nonsecret host allowlist).
It contacts only
`http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token`,
with the Google metadata header and a 5-second socket timeout, rejecting redirects,
HTTP proxies, oversized responses, and invalid/expired token payloads. Tokens go
only to Docker via stdout: they are not cached on disk or logged. `store` is
refused; `erase` is a no-op; `list` returns an empty mapping.

The role resolves both `root` and `ansible_user` through passwd, rather than assuming
`/home/<user>`. Their `.docker/config.json` files are merged atomically and assigned
their account UID/GID, with directory `0700` and file `0600`. Unrelated settings,
credential helpers and credentials are preserved; obsolete static auth entries for
the configured registry are removed. Each account is configured in a separate
Ansible module process. For non-root accounts, the module permanently clears
supplementary groups and drops to the resolved GID/UID **before accessing any
home/configuration path**. A concurrent user-controlled directory or symlink swap
therefore cannot redirect a privileged write or chmod. Existing inaccessible
files (including root-owned files in a user's home) fail closed rather than
regaining root to repair ownership; an administrator must repair these separately.
Existing invalid JSON/shapes or symlink configurations are refused. The module
never returns config contents; its task uses `no_log: true` and `diff: false`.

## Image and GR00T behavior

Digest-qualified `docker image inspect`/`docker pull` use argument arrays, never a
shell. A digest already present in `RepoDigests` is not pulled again. Other
workload names are **pre-pulled only**, never launched by this role.

`images.gr00t` selects the existing `isaac-gr00t-container` service, enables it,
and uses that immutable digest. Native source checkout, pip setup, native launcher
and desktop shortcut provisioning are skipped in container mode. An existing
native `isaac-gr00t` service is stopped/disabled to avoid port conflicts. Changes
to the container unit/digest restart the container unit, not the native unit.
Explicit native installation (`install_gr00t: true`, native serving mode, and no
registry GR00T selection) stops/disables an existing container **before** native
provisioning, even when `gr00t_service_enabled` is false. With no explicit GR00T
install request, disabling registry integration or providing only non-GR00T images
remains a no-op, not an uninstall operation.
Model/dataset bind mounts and the existing container's server command remain the
operator's responsibility; an image digest alone does not supply these assets.

## Offline verification

From the repository root:

```sh
python3 src/tests/artifact_registry_ansible.test.py -v
ANSIBLE_STDOUT_CALLBACK=default ansible-playbook -i localhost, --syntax-check src/ansible/isaac-workstation.yaml
```

Tests use temporary account homes, a loopback metadata HTTP server and a fake
Docker executable. They exercise real Ansible configuration/pull tasks, generated
GCP inventory with `from_image`, and role/handler service transitions with sandboxed
host operations. They verify unchanged-digest idempotence, digest-change restarts,
and disabled/no-GR00T no-op behavior without starting services or executing images.
Root-only tests spawn isolated processes to prove real UID/GID/group dropping and
adversarial directory-swap safety, and run the actual Ansible module wrapper twice
against root and non-root temporary homes. These tests skip when not root;
Ansible-dependent tests skip when `ansible-playbook` is absent. Live IAM
propagation, attached-SA access, network,
image availability, GPU support and model health still require separately
authorized verification on a workstation.
