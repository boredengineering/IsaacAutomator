# Workstation software profiles — first offline contract slice

## Public API (for the standalone CLI)

Import `src.python.workstation_profile` (no import of deployment configuration).

- `list_profiles() -> list[str]`: exactly `default`, `full`, `minimal`, sorted;
  public presets only, no home-directory or private-profile scanning.
- `load_profile(name_or_path) -> dict`: read a preset or explicit local YAML path;
  strict syntax/shape validation, **unresolved desired document**, no inheritance.
- `resolve_profile(name_or_path, overrides=None) -> dict`: JSON-safe resolved
  manifest, `schema_version`, `kind: workstation-resolved`, `profile`, `digest`,
  leaf `provenance`, `references`, `unresolved`, `adapter`, `ready_for_apply`,
  `dependencies` and derived `endpoint` (null when not selected).
  `ProfileError` subclasses `ValueError`; errors never echo input values/paths.
- `validate_profile(name_or_path) -> dict`: equivalent to resolve, not a live
  acceptance check. CLI validate may simply call resolve and summarize.

Overrides are a nested partial desired-profile mapping, not dotted keys or shell
strings. Precedence: defaults → one named public preset (`extends`) → selected
file → explicit overrides. Maps merge; scalars/lists replace; explicit false
wins. Only public preset inheritance is supported, not paths/chains/multiple
parents. Deployment envelopes are **not** parsed in this slice: a future caller
must validate its own explicit software fields and pass an overlay. Identity,
kind, version and inheritance cannot be overridden. Missing profiles fail closed.

Only `target: offline` is supported. Local/Ansible/Packer targets raise an
unsupported-adapter error. This is inspectable software intent, **not** a working
installer transport. `ready_for_apply` remains false. Existing `--profile` security
selection/backend identity and the existing installer are untouched. Legacy
`version: '1.0'` installer and `schema_version: v1alpha1` cloud envelopes are
explicitly rejected rather than silently dropping fields. A versioned legacy
conversion adapter and live consumers remain Task 24/25 follow-ups.

## Inventory and mapping before schema selection

Inspected local `isaac-installer/config/{default-profile,minimal-headless,
full-ecosystem}.yaml`, `lib/core/config.sh`, modules and state/workspace consumers;
cloud `configs/profiles/example-profile.yaml`, `src/python/{config,deploy_command,
deployer}.py`, inventory template and role defaults. This matrix covers their
field families; `*` below means the explicitly enumerated siblings, not open
schema support. New fields are consumed by the resolver/validation/reference
report only until a target adapter is implemented.

| Existing field(s) | Actual current consumer / gap | New contract / disposition |
| --- | --- | --- |
| Local `version`, `profile_name`, `description`; cloud `schema_version`, `profile_name`, `description` | Bash CFG flattening/profile label; Python discovery | Strict `schema_version`, `kind`, `name`; descriptions unsupported to keep display nonsecret |
| `hardware.force_gpu_index`, `enforce_x11`, `auto_blacklist_nouveau` | No matching CFG read in inspected shell libraries; stage/driver decisions exist independently | Unsupported; no claimed hardware parity |
| `hardware.enable_nvme_storage_tools` | `lib/modules/dev_tools.sh` | Unsupported host provisioning |
| `workspace.root`, `layout`, `default_owner`, `auto_create_fork` | `config.sh` → `git_workspace.sh` (tilde/user expansion, fork actions) | Unsupported target-path/fork binding; resolver expands nothing |
| `workspace.auto_register_github_desktop` | No matching CFG read in inspected shell libraries | Unsupported |
| `repositories.{isaaclab,arena,lerobot,gr00t}.enabled` | Installer stage/state decisions; cloud `install_gr00t/install_lerobot` role gates not transported by inventory | `components.{lab,arena,lerobot,gr00t}.enabled`; resolver checks dependencies, no auto-enable |
| Same repositories: `repo`, `upstream`, `branch`, `tag` | `config.sh` exports → component modules/git workspace; cloud role git vars; only Sim/Lab/Arena checkpoint strings in inventory | `components.*.source.repository/ref/revision`; upstream fork topology unsupported; no simultaneous branch/tag selectors |
| `repositories.{lerobot,gr00t}.isolated_env` | Exported by Bash, component environment logic; Ansible defaults still share/generalize environment inputs | Named `runtimes` with isolation validation; no claim of upstream dependency compatibility |
| GR00T `model_path`, `vlm_backbone`, `server_host`, `server_port` | Bash exports model/backbone/port (not server_host mapping); Ansible GR00T role defaults native port 5556/container port 5561 and different embodiment | `serving.model`, `bind`, `port`, `embodiment`; backbone override unsupported |
| `simulation.isaacsim.enabled/version/source_type/install_dir` | Bash Sim module/config; cloud Sim role is source-build/checkpoint oriented, not interchangeable Standalone Kit | `components.sim.enabled/source.mode/source.version`; only standalone intent supported; install_dir unsupported |
| `simulation.isaacsim.custom_build.{enabled,source_path,build_command}` | Bash config exports build command/source path | Unsupported; never evaluate commands or reinterpret build as standalone |
| `simulation.isaacsim.accept_eula` | Legacy profile expresses consent; not a shared authorization boundary | Unsupported; preset enablement does not accept license/model terms |
| `devtools.{docker,nvidia_container_toolkit,vscode,github_desktop,chromium,discord}` and `cloud_clis.{aws,gcloud,gh}` | dev_tools reads GUI/AWS/GCloud flags; Docker/toolkit/GH stage behavior is separate | Unsupported; no blanket stage parity |
| `teleoperation.{ftdi_1ms_latency_rule,spacemouse_daemon,manus_vr_gloves,realsense_cameras,xr_cloudxr}` | hardware_teleop module, separate cloud role defaults | Unsupported local peripherals, especially on headless cloud |
| `streaming.provider`, `demos.desktop_shortcuts` | Local stage dispatch/demos module uses other gates too | Unsupported; not equivalent to cloud demo/provider registries |
| Cloud `cloud`, `security.tier`, `network.{iap_only,cloud_nat,ingress_cidrs}` | config/deployer normalization; provider Terraform mapping (not every descriptive YAML field has independent handoff) | Separate existing security envelope, rejected here |
| `security.storage.{state_backend,state_bucket,state_locking,soft_delete_days}` / `terraform_state` | backend_selection and saved identity; not generic software state | Separate existing backend contract, never migrated/overridden here |
| `security.cryptography.{encryption_type,kms_keyring_name}`, `compute.{shielded_vm,os_login,service_account_type,scheduling}`, `secrets.engine` | config/deployer → provider mapping; normalization explicitly reads encryption, OS Login, scheduling, engine; others require provider review | Separate infrastructure/security scope; unsupported here |
| `container_registry` / legacy `artifact_registry`, `huggingface` | registry_profile/huggingface_profile, deployer JSON inventory → distribution roles | Existing independently validated distribution contracts; not embedded here |
| Cloud `workstation.{gpu_model,base_profile,remote_desktop,demos}` | `base_profile` is documented intent, not implemented inheritance; CLI/deployer handles machine/demo/desktop options separately | No legacy promotion; `extends` means one public software preset only |
| Cloud `workstation.workspace`, `repositories`, `teleoperation` | Example explicitly states incomplete Ansible handoff | Same unsupported or conceptual mapping as local rows; no silent drop |
| CLI Sim/Lab/Arena `latest`, checkpoints; Conda role Python default 3.10 | deploy callback performs Git lookup; inventory role parameters | Offline symbolic refs stay unresolved; Lab runtime explicitly 3.12; no lookup |

## Finite v1alpha1 schema and assertions

Only regular local files up to 128 KiB are accepted. Only the fields exercised
below are accepted. Unknown/duplicate keys, YAML merge
keys/aliases, non-mappings and observed `kind: workstation-baseline` fail. The
resolver never scans credentials, imports deployment configuration, fetches Git,
installs, evaluates shell, interpolates environment variables, or writes state.

- Identity: `schema_version: v1alpha1`, `kind: workstation-profile`, slug `name`,
  optional `extends` public preset; `target: offline` only.
- `components`: `sim`, `lab`, `arena`, `gr00t`, `lerobot`; each has boolean
  `enabled`, `execution: native`, fixed `runtime` and a `source`. Container
  execution is explicitly unsupported in this slice. Sim source: `mode: standalone`,
  `version`, optional `sha256`. Git sources: `mode: git`, public credential-free
  HTTPS GitHub `repository`, `ref`, optional full 40-hex `revision`.
- `runtimes`: `kit`, `lab`, `gr00t`, `lerobot`; `manager`, `environment`, `python`,
  `torch`, `torchvision`, `cuda_runtime`, `architecture`. Kit is bundled; Lab and
  LeRobot are isolated Conda intent, not base. GR00T uses UV with logical
  environment ID `gr00t`, matching the installer's repo-local `.venv`; a future
  adapter must bind that ID to the target repository path. Other manager/runtime
  pairings are unsupported. Arena deliberately shares Lab. GR00T and
  LeRobot interpreter/wheel values default to null (unresolved), **not** guessed
  Python 3.12 compatibility. Lab target is 3.12 / torch 2.10.0+cu128 / sm_120;
  torchvision is unknown. CUDA wheel runtime is not the host driver/toolkit.
- `serving`: `enabled`, `bind` (loopback only), integer `port`, `embodiment`,
  `model` (`repository`, `ref`, optional full Git `revision`). Endpoint is derived
  once as a ZeroMQ `tcp://` endpoint (not HTTP), and absent when serving is off.
  Service requires enabled GR00T; Arena
  requires Lab, Lab requires Sim. Enabling components never authorizes downloads.

Git tags/branches and model refs remain unresolved without supplied full commits
(in `revision` or directly in `ref`);
Sim version labels need an archive sha256. Supplied content IDs are syntactically
resolved but **unverified assertions**, not fetched upstream evidence. Changing a
ref/repository/version in an overlay discards an inherited content ID unless that
overlay explicitly supplies a replacement. If a Git/model `ref` is itself a full
commit, changing its repository requires an explicit `ref` or non-null `revision`
in that same layer; repository-only changes (including `revision: null`) fail
closed rather than reusing the old repository's commit. Explicit immutable
selectors must still agree: a different `revision` also requires replacing the
inherited immutable `ref`. This applies to presets, files and explicit overrides;
input documents remain unchanged. Disabled components report `not_selected`.
Runtime compatibility is always unverified offline.

Digest is SHA-256 of canonical JSON of the effective desired `profile` only,
excluding local filenames, provenance and reference reports. Leaf provenance
contains only fixed origin labels (`defaults`, `preset:<name>`, `profile`,
`overrides`), never file paths or raw YAML. Only nonsecret typed values are allowed;
URLs reject credentials, query strings and fragments. Do not put secrets in
repository/ref/environment identifiers. Digest is desired-configuration identity,
not proof of reproducibility or software acceptance.

Examples `default`, `minimal`, `full` target Sim 6.0.1 and Lab v3.0.0-beta2.
Default adds Arena release/0.3.0-prerelease; minimal disables Arena and optional
stacks; full selects GR00T dev, LeRobot v0.4.3 and loopback serving on 5561 with
NEW_EMBODIMENT. Full means **all five software components**, not legacy teleop,
desktop, cloud or distribution features. All await target adapters, source/model
pin verification, upstream runtime manifests, license decisions and §12.3 live
acceptance. None is a tested compatibility claim.

## Implemented consumers and verification

| Profile field → resolved output | Current consumer | Observable offline assertion |
| --- | --- | --- |
| Identity/extends/target → `profile`, `provenance`, `adapter` | `load_profile`, `_validate`, `_merge` | Exact preset discovery, invalid/observed/legacy rejection, explicit false and overlay precedence |
| Component enabled/runtime/execution → `profile`, `dependencies` | `_validate`, `_dependencies` | No implicit dependency enablement, native-only intent, distinct Kit/Lab/GR00T/LeRobot runtime IDs |
| Source mode/repository/ref/revision/version/sha256 → `profile`, `references`, `unresolved` | `_source`, `_merge`, `_reference_report` | Branch/tag unresolved; supplied full IDs unverified; selector changes clear inherited pins; conflicting full IDs fail |
| Runtime manager/environment/version/wheels/CUDA/architecture → `profile`, `unresolved` | `_validate`, `_dependencies`, `_reference_report` | UV GR00T vs Conda Lab/LeRobot; no base/shared environment; null pins and compatibility gaps explicitly reported |
| Serving enabled/bind/port/embodiment/model → `profile`, `endpoint`, `references` | `_validate`, `_dependencies`, `_reference_report` | Disabled service has null endpoint/not-selected model; enabled service requires GR00T; one loopback ZeroMQ endpoint |
| Effective nonsecret fields → `digest`, leaf `provenance` | `resolve_profile` canonical JSON/SHA-256 | Path-independent digest, override origin without filenames, no raw invalid values in errors |

Focused tests (no credential fixtures or live deployment):

```text
python3 src/tests/workstation_profile.test.py
python3 src/tests/workstation_profile_command.test.py
python3 src/tests/profile_privacy.test.py
python3 src/tests/distribution_profile.test.py
```

The standalone CLI is a separate adapter for **inspection**, not deployment.
Outstanding: versioned legacy conversion, explicit deployment-envelope overlay,
typed Bash/Ansible/Packer transport and saved-manifest recovery, target path/fork
binding, source/archive verification, interpreter/lock/wheel compatibility,
license/model-access decisions, and actual installation/physics/policy acceptance.
These are not silently accepted as v1alpha1 executable capabilities.
