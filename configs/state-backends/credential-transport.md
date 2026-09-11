# Host-wrapper credential transport

`./run` forwards only its explicit allowlist of ambient identity variables. Scalar
values are passed to Docker with `-e NAME`, not `-e NAME=secret`, so their values
are absent from Docker's command-line arguments. This is transport only: backend
and workload identity/role selection remain separate configuration decisions.

`GOOGLE_OAUTH_ACCESS_TOKEN` is supported as an explicitly supplied short-lived
Terraform/GCS token and forwarded by name. It is not written into backend config.
It does not automatically change the gcloud CLI identity used for IAP; authenticate
that CLI separately when using private workstation connections.

## External file references

The wrapper supports these top-level environment references:

- `AWS_WEB_IDENTITY_TOKEN_FILE`
- `AWS_SHARED_CREDENTIALS_FILE`
- `AWS_CONFIG_FILE`
- `GOOGLE_APPLICATION_CREDENTIALS`
- `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`
- `ARM_OIDC_TOKEN_FILE_PATH`
- `AZURE_FEDERATED_TOKEN_FILE`

Each nonempty reference must name a readable regular file using an absolute host
path. Symlinks (including any ancestor), `..` components, commas, double quotes,
carriage returns, and line feeds are rejected. Spaces are supported. Commas and
double quotes are refused rather than escaped into Docker's `--mount` CSV syntax.

The file is bind-mounted read-only at `/run/isaac-credentials/NAME`, where `NAME`
is the environment-variable name above. That variable is rewritten to the
container path. The wrapper checks file metadata but does not read or parse file
contents, copy them into the checkout, or put them in command-line arguments.
Host source paths and mapped container paths are visible in Docker arguments.

### Only top-level references are mapped

There is no recursive discovery, copying, or rewriting of file dependencies.
In particular, AWS config/profile entries such as `web_identity_token_file` or
other shared-file references, and GCP external-account JSON
`credential_source.file` entries, must **explicitly reference already mapped
container paths**, not host paths. A dependency must be supplied separately via
one of the supported references above with the correct provider semantics.

For example, when both `AWS_CONFIG_FILE` and `AWS_WEB_IDENTITY_TOKEN_FILE` are
supplied on the host, a profile's `web_identity_token_file` must name
`/run/isaac-credentials/AWS_WEB_IDENTITY_TOKEN_FILE`. Mounting `AWS_CONFIG_FILE`
alone does not transport the token it names. GCP external-account files likewise
do not cause `credential_source` dependencies to be mounted. Arbitrary nested
AWS/GCP configurations are not automatically supported; if a dependency cannot
be expressed through the supported mappings, this wrapper cannot transport it.

## Local Docker endpoint required

For external credential mounts, the wrapper checks the effective endpoint:

1. Nonempty `DOCKER_CONTEXT` selects a context and overrides `DOCKER_HOST`.
2. Otherwise, nonempty `DOCKER_HOST` supplies the endpoint directly.
3. Otherwise, the currently selected Docker context is inspected.

Context lookup uses read-only `docker context inspect`, requesting only
`Endpoints.docker.Host`; it does not change Docker settings. Accepted endpoint
forms are an absolute Unix socket (`unix:///path/to/socket`) or a local named
pipe (`npipe:////./pipe/name`, where supported by Docker). Remote endpoints,
including SSH, TCP (even loopback TCP), and remote named pipes, are unsupported.
Failed inspection, empty endpoints, and unknown endpoint forms are rejected
before `docker run`. The existing image lookup/build still happens first.
Invocations without external credential mounts retain their existing behavior.

Bind sources are resolved on the daemon host: a host-side file check cannot
prove that an identically named remote file is the intended credential. A local
socket must connect to a trusted local Docker service with the expected host
file sharing; forwarding a local socket to a remote daemon is not supported.
Endpoint syntax checking cannot attest to the service behind a socket.

## Security boundary

Read-only mounts prevent container writes through those mounts. They are **not
an encrypted sandbox**: the container and Docker daemon can read the files, and
forwarded environment values are available to the container and daemon even
when absent from command-line arguments. Use trusted images, daemon access, and
host paths. Metadata validation is not a defense against a host process racing
to replace files or change Docker context configuration before container start.
