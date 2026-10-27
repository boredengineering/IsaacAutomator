# Architectural Re-evaluation: Hardcoded Profile Configurations & Dynamic Extensibility Flaws

> **Date**: 2026-10-27  
> **Status**: Review & Action Plan  
> **Scope**: Profile Schema (`workstation_profile.py`), Adapters (`profile_adapters.py`), Ansible Engine (`isaac-workstation.yaml`, `meta/main.yml`, individual roles), Inventory Generator (`deployer.py`, `inventory.template`), and Verification Ledger (`state-ledger`).

---

## 1. Executive Summary

The current architecture of Isaac Automator suffers from a fundamental design flaw: **the profile system is implemented as a closed-world, hardcoded enum rather than an open, declarative manifest system**.

While user profiles (`configs/workstations/*.yaml`) appear declarative on the surface, adding or modifying any robotics framework, foundation model, teleoperation library, or benchmark suite (e.g., `robolab`, `unitree_sdk`, custom VLAs, or user-defined ROS packages) requires invasive, multi-file code modifications across at least **7 distinct layers** in the repository.

This document catalogs every hardcoded value, analyzes the systemic consequences, and defines the target architecture to transition Isaac Automator to a truly generic, data-driven physical AI workstation engine.

---

## 2. Exhaustive Audit of Hardcoded Configurations

### Layer 1: Closed-World Schema Validation ([`src/python/workstation_profile.py`](file:///workspaces/IsaacAutomator/src/python/workstation_profile.py))

| Location | Hardcoded Value | Architectural Flaw & Consequence |
| :--- | :--- | :--- |
| **Line 32** | `COMPONENTS = ('sim', 'lab', 'arena', 'gr00t', 'lerobot', 'robolab')` | Closed-world enum. Any component outside this tuple throws `ProfileError: components: expected mapping with supported keys only`. |
| **Line 33** | `RUNTIMES = ('kit', 'lab', 'gr00t', 'lerobot')` | Fixed runtime identifiers. Cannot declare a custom runtime (e.g. `ros2_humble`, `jax_env`, `pytorch25`). |
| **Line 34** | `RUNTIME_MANAGERS = {'kit': 'bundled', 'lab': 'conda', 'gr00t': 'uv', 'lerobot': 'conda'}` | Enforces static 1-to-1 mapping between runtime names and managers (`conda` vs `uv` vs `bundled`). |
| **Line 36** | `COMPONENT_RUNTIME = {'sim': 'kit', 'lab': 'lab', 'arena': 'lab', 'gr00t': 'gr00t', 'lerobot': 'lerobot', 'robolab': 'lab'}` | Rigid binding. Profile cannot choose runtime placement (e.g., placing `robolab` in an isolated conda environment or `gr00t` in conda instead of uv). |
| **Line 37** | `DEPENDENCIES = {'sim': [], 'lab': ['sim'], 'arena': ['lab'], 'gr00t': [], 'lerobot': [], 'robolab': ['lab']}` | Static dependency DAG in Python instead of manifest-declared `dependencies: [lab]`. |
| **Line 208** | `if item.get('component') not in (None, 'lab', 'arena', 'gr00t', 'lerobot', 'robolab'):` | Repositories section cannot declare upstream/fork tracking for arbitrary components. |
| **Line 420** | `if len(environments) != len(set(environments)): raise ProfileError('Runtime environments must be isolated; only Arena shares Lab')` | Hardcoded special-case assumption ("only Arena shares Lab") instead of generic environment namespace resolution. |

---

### Layer 2: Profile Adapter & Inventory Translation ([`src/python/profile_adapters.py`](file:///workspaces/IsaacAutomator/src/python/profile_adapters.py))

| Location | Hardcoded Value | Architectural Flaw & Consequence |
| :--- | :--- | :--- |
| **Line 14** | `LEGACY_NAMES = {'lab': 'isaaclab', 'arena': 'arena', 'gr00t': 'gr00t', 'lerobot': 'lerobot', 'robolab': 'robolab'}` | Static dictionary mapping short component names to legacy names. |
| **Line 15** | `REPO_DIRS = {'lab': 'IsaacLab', 'arena': 'IsaacLab-Arena', 'gr00t': 'Isaac-GR00T', 'lerobot': 'lerobot', 'robolab': 'RoboLab'}` | Hardcoded directory folder names on the host/workstation filesystem. |
| **Line 174** | `artifact = {'public_git_profile': True, 'install_gr00t': False, 'install_lerobot': False, 'install_robolab': False, ...}` | Static boolean flags created individually for each component instead of a dynamic component payload dictionary. |
| **Lines 182–183** | `for name, consumer in (('sim', 'isaacsim'), ('lab', 'isaaclab'), ('arena', 'isaaclab_arena'), ('gr00t', 'gr00t'), ('lerobot', 'lerobot'), ('robolab', 'robolab')):` | Fixed iteration tuple. New components cannot be parsed without adding them to this loop. |
| **Lines 218–236** | `if name in ('gr00t', 'lerobot', 'robolab'): if name == 'gr00t': ... elif name == 'lerobot': ... elif name == 'robolab': ...` | Cascading `if/elif` blocks hardcoding special-case runtime variables (`profile_lerobot_isolated`, `profile_gr00t_isolated`, etc.) instead of generic runtime execution handlers. |
| **Line 204** | `mark(path + '.source.version', 'mapped' if source.get('version') == '6.0.1' else 'unsupported')` | Hardcoded version check specifically for Isaac Sim "6.0.1". |
| **Line 262** | `artifact['isaacsim_source_dir'] = base + '/IsaacSim'` | Static folder path assumption for simulation source. |

---

### Layer 3: Ansible Monolithic Role Chain ([`src/ansible/roles/isaac-workstation/meta/main.yml`](file:///workspaces/IsaacAutomator/src/ansible/roles/isaac-workstation/meta/main.yml))

| Location | Hardcoded Value | Architectural Flaw & Consequence |
| :--- | :--- | :--- |
| **Lines 24–40** | `dependencies:` list containing 17 fixed roles (`system`, `container-registry`, ..., `gr00t`, `lerobot`, `robolab`, `demos`, `state-ledger`) | Monolithic static dependency chain. Every single role runs in fixed sequence. Adding a new component requires creating a whole new Ansible role folder and adding it to this file. |
| **Duplicated Tasks** | `roles/{isaaclab-source,isaaclab-arena-source,gr00t,lerobot,robolab}/tasks/main.yml` | 80% code duplication across roles (calling `public-git/tasks/source.yml`, creating directories, git clone, configuring remotes). |

---

### Layer 4: State Ledger & Verification Hardcoding ([`src/ansible/roles/state-ledger/tasks/main.yml`](file:///workspaces/IsaacAutomator/src/ansible/roles/state-ledger/tasks/main.yml))

| Location | Hardcoded Value | Architectural Flaw & Consequence |
| :--- | :--- | :--- |
| **Lines 33–67** | Discrete probe tasks: `isaacsim_stat`, `isaaclab_commit`, `arena_commit`, `gr00t_commit`, `robolab_commit` | Individual hardcoded `find` and `git rev-parse` shell tasks for every component. |
| **Lines 68–108** | Statically templated JSON: `"components": { "isaacsim": { ... }, "isaaclab": { ... }, "isaaclab_arena": { ... }, "gr00t": { ... }, "robolab": { ... } }` | The ledger cannot dynamically report what was installed; it only reports the hardcoded keys written into the Ansible copy task. |

---

### Layer 5: Inventory & Deployment Boundary ([`src/ansible/inventory.template`](file:///workspaces/IsaacAutomator/src/ansible/inventory.template) & [`src/python/deployer.py`](file:///workspaces/IsaacAutomator/src/python/deployer.py))

| Location | Hardcoded Value | Architectural Flaw & Consequence |
| :--- | :--- | :--- |
| **`inventory.template`** | Hardcoded placeholders: `{isaacsim_git_repo}`, `{isaaclab_git_repo}`, `{isaaclab_arena_git_repo}`, `{isaaclab_git_checkpoint}` | The INI inventory file has fixed positional keys that break if omitted or if arbitrary components are added. |
| **`deployer.py:874`** | `for component in ("isaacsim", "isaaclab", "isaaclab_arena"):` | Fixed fallback loops in parameter validation and inventory formatting. |

---

## 3. Impact & Cost of the Anti-Pattern

1. **High Friction for Developers**:
   Adding a single repository (like RoboLab) required editing:
   - `workstation_profile.py` (3 different tuples & validator rules)
   - `profile_adapters.py` (constant dictionaries, initialization artifacts, loop tuples, and if/else conditions)
   - `isaac-workstation/meta/main.yml` (role dependency list)
   - `roles/robolab/` (entire new role: `defaults/main.yml`, `tasks/main.yml`, `meta/main.yml`, templates)
   - `state-ledger/tasks/main.yml` (probe tasks and JSON template)
2. **Fragility & Schema Desynchronization**:
   If a developer edits the YAML profile to test a new framework or package, the profile validator rejects it immediately with schema errors before any provisioning even begins.
3. **Bloated Ansible Playbook Execution**:
   The monolithic role list runs all 17 roles sequentially, adding unnecessary task evaluation overhead during `--existing run_ansible` updates.

---

## 4. Target Architecture: Dynamic, Manifest-Driven Component Engine

To eliminate all hardcoded component enums, Isaac Automator should migrate to a **data-driven component specification**:

```
[Profile YAML (Manifest)]
         │
         ▼
[Generic Component Validator]  <── Validates shape & security (HTTPS, valid git ref, safe paths)
         │
         ▼
[Dynamic Profile Adapter]       <── Serializes components as a JSON payload: `profile_components: [...]`
         │
         ▼
[Universal Ansible Component Role] <── Iterates over `profile_components` in a loop:
         │                             1. Checks out source (with dual remotes)
         │                             2. Executes environment binding (Conda, uv, pip)
         │                             3. Generates optional desktop entry
         ▼
[Dynamic State Ledger Engine]   <── Probes installed paths from `profile_components` and writes ledger
```

### Proposed Schema (Open-World Specification)

```yaml
schema_version: v1alpha2
kind: workstation-profile
name: boredengineering-dev

workspace:
  root: ~/Documents/GitHub
  name: BoredEngineer

runtimes:
  kit: { manager: bundled, environment: kit }
  lab: { manager: conda, environment: isaaclab, python: "3.12", torch: "2.10.0+cu128" }
  gr00t: { manager: uv, environment: gr00t }
  lerobot: { manager: conda, environment: lerobot, python: "3.10" }

components:
  - id: sim
    type: standalone
    runtime: kit
    url: https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.0.1-linux-x86_64.zip
    sha256: 348013c4d3ac398d40162566d0edfe4f3837a0eb5efa358ec87065f81aa68dd7
    install_dir: ~/IsaacSim

  - id: lab
    type: git
    runtime: lab
    repository: https://github.com/boredengineering/IsaacLab.git
    ref: dev/arena_v0.3.0-compat
    upstream: https://github.com/isaac-sim/IsaacLab.git
    install: { method: editable }

  - id: arena
    type: git
    runtime: lab
    repository: https://github.com/boredengineering/IsaacLab-Arena.git
    ref: dev/0.3.0-prerelease
    upstream: https://github.com/isaac-sim/IsaacLab-Arena.git
    install: { method: editable }

  - id: robolab
    type: git
    runtime: lab
    repository: https://github.com/boredengineering/RoboLab.git
    ref: main
    upstream: https://github.com/NVlabs/RoboLab.git
    install: { method: editable }
    desktop_shortcut:
      name: RoboLab Dashboard
      exec: "/usr/local/bin/isaaclab-env python -m dashboard.cli"
```

---

## 5. Phased Refactoring Roadmap

### Phase 1: Unify Component Execution in Ansible
- Create a single, generic `workspace-component` Ansible role.
- Replace individual boilerplate roles (`roles/robolab`, `roles/lerobot`, `roles/isaaclab-arena-source`) with a parameterized task that accepts `repo`, `ref`, `upstream`, `dest`, `runtime`, and `install_command`.

### Phase 2: Dynamic Adapter Payload
- In `profile_adapters.py`, remove the fixed `(('sim', 'isaacsim'), ...)` loop.
- Emit a structured JSON list `profile_components_json` into the Ansible inventory vars.
- Remove hardcoded flags (`install_gr00t`, `install_lerobot`, `install_robolab`).

### Phase 3: Open-World Schema Validation
- In `workstation_profile.py`, replace `COMPONENTS = (...)` with open-world dictionary/list validation.
- Assert valid schema properties (valid git URL, valid SHA/ref format, non-overlapping destination paths) instead of matching exact keyword strings.

### Phase 4: Dynamic State Ledger & Probing
- In `state-ledger`, iterate over `profile_components` to dynamically query HEAD commits and output the receipt JSON without any hardcoded keys.

---

## 6. Formal Implementation Proposal

A comprehensive, phased engineering proposal detailing the target schema (`v1alpha2`), invariant-based validation engine, universal `workspace-component` Ansible role, dynamic state ledger, and backward-compatibility migration path has been authored:

👉 **See Formal Plan:** [Dynamic Component Manifest Engine Plan](file:///workspaces/IsaacAutomator/.agents/references/plans/dynamic-component-manifest-engine-plan.md)

