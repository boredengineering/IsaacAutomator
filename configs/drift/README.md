# Drift configuration and release boundaries

The example identities, hashes, registries and storage references here are
placeholders, not configured or verified services. All scheduling examples default
to disabled/report-only. Do not put credentials, Terraform state, private inputs or
saved binary plans in these files.

## Inactive workflow generation

First copy the matching provider example into your own configuration and replace
the source/image placeholders with reviewed immutable pins. The distributed examples
are deliberately invalid until those replacements are made. From the repository root:

```sh
./drift workflow preview --config path/to/my-reviewed-workflow.yaml
./drift workflow generate --config path/to/my-reviewed-workflow.yaml --output-dir .agents/generated/drift
```

Use the corresponding GCP/Azure example for those providers. Review the generated
configuration and identity/trust requirements with real immutable source/action/image
pins. Output is deliberately outside `.github`. Generation is not installation,
GitHub environment verification, IAM verification or activation. Runtime Terraform
must satisfy the same remote >=1.10,<2 feature floor as the backend adapters; a valid
version string is not proof that an image contains that binary.

## Runtime and evidence

The common detector, private last-applied baseline store and report history are
separate components. A profile or repository HEAD is not a trustworthy applied
baseline. A valid backend descriptor is not evidence of state ownership, effective
credentials, successful monitoring or authorized correction.

A complete check must reconstruct approved source/input/provider-lock bytes,
verify the authoritative attachment and lifecycle state, execute only a native
nonmutating plan, and persist a sanitized report through an approved private store.
Local evidence directories must be durable, owner-only and independently retained.
A scheduler successfully launching a process is not a successful drift check.

Native scheduling modules under `src/terraform/monitoring/` have isolated ownership
and no remediation enablement. Their private report, notification and independent
watchdog integration requires separate verification. Do not activate a stack merely
because its provider schema or mocked Terraform plan validates.

## Correction boundary

Corrections remain gated until the exact saved binary plan, source/inputs/provider
lock, backend/state identity, permitted scope, fresh live conditions and a genuine
independent approval can all be verified together. Raw plan/state/input artifacts
must not be placed in normal CI logs or public artifacts.

The local OS-principal/TTY issuer is a bounded component, not a substitute for the
required independent approval authority. Its same-principal receipts are not silently
relabelled as independent identities. Generated GitHub workflows do not by themselves
prove protected-environment review, OIDC trust or global one-use approval consumption.

## Interpreting results

- `clean_within_coverage` is bounded evidence, not universal absence of drift.
- External drift, desired changes and policy failures are different classes.
- Missing baselines, unknown ownership, denied reads, stale evidence and unsupported
  checks must never become clean results.
- Lifecycle stop/scaling intent and ignored coverage limit automatic interpretation.
- Expired exceptions require review; they do not hide findings.
- Same-baseline, fresh, covered rechecks are required before resolving incidents.
- Missing or stale detector/heartbeat evidence is a monitoring gap, not healthy state.

See `.agents/references/plans/terraform-remote-backend-plan.md` and its adjacent
implementation work log. Full remote lifecycle/drift/notification/shared-registry
acceptance remains open; no cloud infrastructure or workflow was activated by the
implementation tests.
