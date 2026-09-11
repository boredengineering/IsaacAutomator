# Azure backend bootstrap

Candidate provider: `hashicorp/azurerm = 4.30.0` (independent of workload Azure 2.x).
Reference to verify: https://registry.terraform.io/providers/hashicorp/azurerm/4.30.0/docs/resources/storage_account

New dedicated resource group, Standard LRS non-HNS StorageV2 account, infrastructure
and platform encryption, HTTPS/TLS1.2, no shared-key/anonymous blob access, versioning,
7-day blob/container soft delete, private container and CanNotDelete account lock.
Explicit controller Entra **object ID**, not client/application ID, receives Storage
Blob Data Contributor at container scope. Bootstrap operator separately needs account,
RG, role-assignment, lock and Entra data-plane administration privileges. Provider
registration is disabled; required Microsoft.Storage provider registration is a
separate admin prerequisite, not an implicit account-wide mutation.

Both Python create/use-existing preflight and Terraform preconditions reject backend
RG names that overlap ANY supplied workload-owned RG, case-insensitively. Supply the
complete ancestor inventory. Account locks do not replace ancestor separation.
Create-new refuses existing RGs too; to use an existing account/RG, inspect using
`doctor` and keep its original ownership instead of importing it. Container private
access disables anonymous access, NOT public network endpoints. Private networking
is an explicit future extension; do not widen network controls to make CI work.
CanNotDelete protects management-plane account deletion, not blob deletion: keep
soft-delete/versioning, restricted data roles and administrator recovery backups.
Historical blob versions remain until separately reviewed lifecycle retention is
configured; monitor version costs. No active state expiration or immutability policy
is installed. Azure CMEK is not represented in current BackendSpec and is not enabled.

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
