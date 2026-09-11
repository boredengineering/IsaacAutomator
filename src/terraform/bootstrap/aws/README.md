# AWS backend bootstrap

Candidate provider: `hashicorp/aws = 5.100.0` (independent of workload AWS 4.x).
Reference to verify: https://registry.terraform.io/providers/hashicorp/aws/5.100.0/docs

Dedicated bucket with all public-access blocks, bucket-owner-enforced ownership,
versioning, SSE-S3 or explicit existing SSE-KMS, TLS-only resource policy and
noncurrent-version retention (90 days plus ten newer noncurrent versions).
Controller role gets prefix-restricted listing, state get/put and get/put/delete
only for `.tflock` objects. No state DeleteObject grant is included. Restore/version
and KMS Encrypt/Decrypt/GenerateDataKey permissions/key policy are separate admin
responsibilities and are not silently granted. AWS/GCP lack an account-level delete
lock equivalent here: no force destruction plus Terraform prevent_destroy are not
console/API deletion guarantees. Bootstrap currently supports commercial `arn:aws`
principals; GovCloud/China require a separately verified partition-aware extension.
Private endpoint/network restrictions must be explicitly designed for controller
and CI access; this stack does not create VPC endpoints or widen an existing policy.

## Ownership and safety

This is an independent admin stack, not a workstation module. Use explicit names
from a validated BackendSpec. There is no automatic `auto` naming/provisioning.
Create-new refuses an existing destination; use-existing and externally managed
storage use `doctor()` only, with no import, IAM repair or resource changes.
Backend and GPU workload principals are separate; never pass a GPU service identity
as `controller_principal`. The caller must attest that distinction.

`prevent_destroy` protects resources only while their configuration remains in
this stack. It cannot prevent deletion through every API, console, removal of
configuration, or state surgery. There is no WORM/retention lock on active lock
objects. Retirement requires a separate approved inventory of all dependent
states, version backups and explicit admin action, never workstation destroy.

## Controller API (CLI wiring is separate)

```python
from src.python.backend_bootstrap import BootstrapSession, doctor
report = doctor(spec, acknowledge_reads=True,
                workload_resource_groups=["workload-rg"])  # required for Azure
with BootstrapSession(spec, bootstrap_state_root=approved_admin_root,
                      region=backend_region, controller_principal=controller,
                      workload_resource_groups=["workload-rg"],
                      acknowledge_reads=True) as session:
    plan = session.plan()  # authenticated refresh; private SavedPlan
    # Review the exact saved plan; this line requires separate user approval:
    session.apply(plan, acknowledge_creation=True)
```

No cloud calls were used to test this implementation. Doctor uses installed AWS,
gcloud or Azure CLI through bounded subprocess argv, stdin disabled, JSON captured,
never login or write/lease probes. It checks the CLI's identity/context, not proof
that Terraform's separately configured ambient credentials are identical. Reports
contain only static status/check names and remediation text, never cloud output.
`partial` is NOT ready/clean: effective write/lock, restore/version permissions,
CMEK key authorization and Terraform credential equivalence are not established
by metadata reads. Errors distinguish not-found, permission-denied, identity-mismatch,
unreachable, authentication-required, unsupported-feature and unknown. No fallback
to local state and no production object contents are read or printed.

## Bootstrap-state recovery

The shared runner writes private local state to
`<approved_admin_root>/bootstrap/backend-<storage-identity-digest>/.tfstate`, outside
all disposable staging and all workstation deployment directories. Keep that root,
the reviewed descriptor/inputs, source revision, provider locks when generated, and
an ownership record in encrypted administrator backups. The digest is stable across
namespace/prefix changes and does not make an existing destination adoptable.
This create-new API deliberately refuses existing bootstrap state. For interrupted
creation or subsequent maintenance, recover the original admin stack and its state;
never discard it and run another create-new. Check `session.runner.recovery_directory`
and `recovery_state` after errors; retained staging can contain secrets and must be
secured durably before /tmp cleanup or reboot.

The bootstrap state cannot initially live in the bucket/account being created.
After creation, explicit migration to an independently managed durable admin backend
is a separate operator workflow, not implemented by BootstrapSession. First back up
local bootstrap state, quiesce all controllers, verify admin backend identity and
permissions, migrate with Terraform's explicit migration workflow, then verify
lineage/resources and preserve a recovery receipt. Never automatically self-migrate.
There remains a cross-controller/API race between absence checks and create; use one
approved bootstrap owner and prevent concurrent creators. No distributed bootstrap
lock or atomic cloud-name claim is promised.

## Verification status and version matrix

Bootstrap roots use local state with Terraform >=1.7,<2 (mock-provider testing
requires >=1.7); workstation remote backend adapters separately require >=1.10,<2
for native S3 lockfiles. Terraform 1.8.5 syntax/format and Python structural checks
were run offline. Exact provider pins below are **candidates, NOT schema-verified**.
An attempt to read official versioned provider documentation was tool-denied;
provider binaries are not available in clean test staging. No dependency locks have
been fabricated. Do not treat these roots as production-accepted until an authorized
review verifies official schema, initializes pinned providers in disposable staging,
records lockfiles, and runs `terraform validate`, `terraform providers schema -json`
and `terraform test` there. Mocked plans are not live IAM/locking acceptance.
