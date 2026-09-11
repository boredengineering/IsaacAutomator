# GCP report-only monitoring: Scheduler → Cloud Run Job

**Decision:** one Cloud Scheduler authenticated OAuth POST to the Cloud Run v2 jobs
API and one Cloud Run Job. No Asset Inventory feed, Pub/Sub or Infrastructure
Manager deployment is created. Exact provider pin: **hashicorp/google 6.37.0**.

Additional explicit inputs: `project`, `region`, existing private `network` and
`subnetwork`. Direct VPC egress is `ALL_TRAFFIC`; establish private Google API access
and approved registry/backend/report routes externally. Jobs expose no application
HTTP endpoint. The scheduler calls Google's authenticated control-plane HTTPS
endpoint, not a public unauthenticated workload endpoint. The image must be in
Artifact Registry; pin its digest and set the image's WORKDIR to the directory
containing the real executable `./drift`.

Scheduler identity is an existing same-project service-account email with
`roles/run.invoker` on this exact job only (`run.jobs.run`, see output). The
Scheduler service agent needs its standard token-minting service-agent role;
the provisioning admin needs narrowly scoped service-account act-as permissions.
Runtime service-account email is explicit, never the default project account;
review only selected detector reads/locks/report writes. The Cloud Run service
agent needs image repository read access (including cross-project grants when
applicable). No `allUsers`/`allAuthenticatedUsers`, project-wide invoker, workload
IAM grants or service enabling is performed by this module. Customer setup must
enable required APIs and validate service agents separately.

One task and parallelism one bound each execution, not global overlapping job
executions. Job retries consume `retries`; Scheduler retries are zero to avoid
multiplication. Job execution timeout is 60..900 seconds. The scheduler's 180-second
request deadline only covers starting the job, not its completion. Validate the
common detector's shared-backend exclusion independently. Costs include Cloud Run
CPU/memory time, scheduler requests, Artifact Registry/report storage and existing
network egress. Platform stdout/stderr can reach Cloud Logging: the pinned check
must emit sanitized output only; customer logging retention/access needs review.

Official schema/service references checked for this slice:
- https://github.com/hashicorp/terraform-provider-google/blob/v6.37.0/website/docs/r/cloud_run_v2_job.html.markdown
- https://github.com/hashicorp/terraform-provider-google/blob/v6.37.0/website/docs/r/cloud_scheduler_job.html.markdown
- https://cloud.google.com/run/docs/execute/jobs-on-schedule

## Ownership, defaults and runtime contract

This is an **independent monitoring root module**, not a workstation child module.
Use a separately approved state/backend namespace and admin identity. No backend,
report bucket/container, workload, IAM policy, organization policy, feed, secret,
registry, or image is created/adopted by this module. Default `provision=false`
creates no cloud resources (only a local Terraform validation guard).
`provision=true` creates the runtime with scheduling still disabled; activating a
paid schedule additionally requires `schedule_enabled=true` and explicit review.

Supply a real user-owned registry image pinned as `repository@sha256:<64 lowercase
hex characters>`; there is deliberately no default image or invented public URL.
The tested fixtures are synthetic references, not usable images. Before setup,
independently build/verify that image with the compatible pinned Automator source,
Python/Terraform/providers/cloud clients required by your detector and nonsecret
baseline/config artifacts. The executable must support exactly:

```
./drift check --config ABSOLUTE_CONFIG_ARTIFACT_PATH
```

`config_artifact` is a required absolute path **inside the image**, not an upload,
URL, controller path or credential file. Embed the approved nonsecret check config
and pinned baseline/source/input/provider-lock references in that immutable image.
Runtime credentials come only from the configured workload identity. The check
config must opt into only selected deployments/scopes, `report_only`, and the same
runtime/report references. Native scheduling does not validate image contents,
bootstrap a controller registry, resolve detector references, install dependencies,
or implement a second detector. Smoke-test the actual CLI/config/image together
before provisioning. A digest string alone is not evidence that the image exists.

`report_storage_ref` names customer-owned restricted report storage in the runtime
configuration. It is an ownership/preflight contract, **not a storage provisioner
or an uploader**. This stack cannot guarantee that a caller's report transport is
configured. Acceptance requires a verified sanitized report upload and retained
last-success/health evidence. Keep reports/audit history outside both monitoring
and workstation state; configure access controls, encryption, retention and an
independent owner there. Never send state, plan binaries or private inputs to logs.
Do not point report storage at an ephemeral job filesystem. Missing/denied storage
must remain an execution/reporting failure, never clean drift or automatic repair.

## Least privilege and setup review

Identities are explicit existing references. Runtime, scheduler and admin must be
distinct (Azure uses a platform scheduler marker). The stack **does not grant IAM**,
validate effective permissions, or impersonate `admin_identity`; that field records
the reviewed setup owner. Comparing strings is not a live identity/trust audit.
The authenticated Terraform operator must separately prove they are the approved
monitoring admin. Limit its resource creation and pass/act-as authority to these
monitoring resources and the selected runtime/scheduler identities.

Runtime: narrow provider read permissions for the selected resources, exact saved
backend read plus only the detector's required transient locking permissions,
read-only image/baseline access, and write-only sanitized report objects in the
approved prefix. No infrastructure apply/delete/IAM/policy mutation or backend
administration. Never grant an account-wide administrator role to make a check
pass. Some provider reads or token APIs inherently require unscoped permissions;
review their conditions/account boundaries individually rather than treating a
wildcard as acceptable for all runtime actions. Existing network/registry/report
access is a customer prerequisite; no secret values belong in tfvars or examples.

## Limits, costs, disable and retirement

Only **once-daily UTC** cron (`minute hour * * *`) is supported in this cost-limited
slice. Default retries are zero; explicit retries are 0..4 and
`max_attempts_per_day` (1..5) must include initial attempt plus retries. Runtime
execution is bounded to at most 900 seconds per attempt. This is a configuration
budget, **not a hard billing quota or distributed execution counter**: manual runs,
at-least-once delivery and external callers can exceed it. Platform concurrency
limits are not a shared-backend lock. Retain the common detector's shared-state
coordination/deduplication and never use this schedule as a second Terraform owner.
External quotas, cost alerts and an independent overdue-check monitor are required
before unattended use. This stack does not provision budgets, notifications,
last-success storage or overdue alerts. A completed scheduler API request does not
prove detector success or report delivery. Check those independently.

Pause by reviewing/applying `schedule_enabled=false`, then inspect/drain in-flight
runs; disabling a schedule does not cancel already running work. After report/audit
retention and independent alerts are checked, a separately approved monitoring
teardown (`provision=false` or destroy in **monitoring state only**) retires runtime
resources. External report storage and external identities remain untouched.
Workstation teardown never owns this module. Preserve report access and manual
break-glass inspection even when backend access is broken; do not recreate an
empty backend as a recovery shortcut.

## Offline API and verification

`src.python.drift_native.native_manifest(mapping)` is a pure, deterministic API
returning normalized `invocation`, `executor`, `terraform_variables`, activation
flags and report ownership. It never calls cloud APIs or Terraform and never writes
files. Common native input is separate from the detector's `DriftConfig`; pass the
actual detector JSON path as `config_artifact`, not this native manifest. The
`configs/drift/example-*-native.yaml` files use the JSON subset of YAML and are
inert, intentionally incomplete until real image/path/identities/report references
are supplied. Provider-specific network/account inputs are separate Terraform
variables, not arbitrary fields accepted by the Python adapter. The parent CLI can
expose this API; this module does not claim a native CLI subcommand is installed.

From repository root, with existing Terraform >=1.7 (verified with 1.8.5):

```
PYTHONPATH="$PWD" python3 -B src/tests/drift_native.test.py
python3 -B src/terraform/test_drift_monitoring.py
terraform fmt -check -recursive src/terraform/monitoring
```

The harness copies only source `.tf` and test `.tftest.hcl` files into disposable
folders, clears credential/TF configuration environment, uses an empty HOME,
initializes with `-backend=false`, validates real pinned provider schemas and runs
`mock_provider` plans. Public signed provider downloads are allowed; no tools are
installed/upgraded and no cloud/state/credential APIs are used. No test state,
provider cache or lockfile is copied back into the repository. At authorized setup,
retain/review the generated provider lockfile in the separately owned stack.

## Acceptance status / unsupported modes

Implemented and offline-tested: inert manifest generation, report-only command
selection, pinned image validation, disabled defaults, private runtime wiring,
separate identity references, retry/timeout budgets and external report ownership.
`init -backend=false`, `validate` and mocked plan tests passed with the provider
version below. **Not live-tested on any provider.** No resources or schedules were
activated. Actual image execution, registry pulls, IAM/trust, network routing,
backend locking, report transport/retention, duplicate/missed schedules, independent
health/overdue alerts and safe retirement remain an explicitly authorized acceptance
gate. Do not infer success on one cloud from another cloud's offline results.

Unsupported: native Config/Asset Inventory/Policy/Resource Graph signals,
policy mutations, remediation runbooks, automatic/preauthorized correction,
Infrastructure Manager/Automation alternatives, arbitrary cron/event triggers,
organization-wide rules, autonomous notifications or overdue monitoring. Native
configuration rejects these modes/unknown fields; they are not silently enabled.
Use the common local/manual detector or separately generated GitHub workflow where
appropriate. Native execution is optional and does not replace Terraform ownership.
