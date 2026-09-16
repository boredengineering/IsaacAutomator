#!/usr/bin/python3
"""Offline profile selection preview, never installer checks or installation.

Exit 2: incomplete/unknown or unsupported input/mode. Exit 77: confinement/root
refusal. No successful preview is physical-run approval. Stage rows and pure
legacy subaction intent are not resolved host health or an executable plan.
"""
import importlib.util
import json
import os
import stat
import sys

STAGES = (
    ("driver", "NVIDIA GPU driver & kernel modules"),
    ("display", "X11 enforcement & GDM Wayland toggle"),
    ("prereqs", "Vulkan runtime, dev headers, GCC 11 & Git LFS"),
    ("python", "Miniforge & uv package manager"),
    ("devtools", "Profile-selected development tools"),
    ("physical_ai", "Hugging Face CLI, LeRobot, dataset visualization & codecs"),
    ("hardware_teleop", "Profile-selected hardware and teleoperation tools"),
    ("isaacsim", "Isaac Sim extraction & EULA"),
    ("isaaclab", "Isaac Lab checkout, runtime link & verification"),
    ("arena", "IsaacLab-Arena benchmark suite"),
    ("gr00t", "Isaac-GR00T foundation model stack"),
    ("demos", "Desktop launchers"),
)
ENABLED = {
    "arena": ("REPOSITORIES_ARENA_ENABLED", "REPOSITORIES_ARENA", "REPOSITORIES_ISAACLAB_ARENA_ENABLED", "REPOSITORIES_ISAACLAB_ARENA", "ISAACLAB_ARENA_ENABLED", "ISAACLAB_ARENA", "ARENA_ENABLED", "ARENA", "ECOSYSTEM_ARENA"),
    "physical_ai": ("REPOSITORIES_LEROBOT_ENABLED", "REPOSITORIES_LEROBOT", "REPOSITORIES_PHYSICAL_AI_ENABLED", "LEROBOT_ENABLED", "LEROBOT", "ECOSYSTEM_LEROBOT", "PHYSICAL_AI_ENABLED"),
    "gr00t": ("REPOSITORIES_GR00T_ENABLED", "REPOSITORIES_GR00T", "GR00T_ENABLED", "GR00T", "REPOSITORIES_ISAAC_GR00T_ENABLED"),
}


def _trusted_module(name):
    directory = os.path.dirname(os.path.abspath(__file__))
    if directory not in sys.path:
        sys.path.insert(0, directory)  # trusted shipped modules, never profile paths
    path = os.path.join(directory, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("Trusted module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arguments(argv):
    values = {}
    positional = []
    workspace_options = {"--workspace-dir": "ROOT", "--workspace-root": "ROOT",
                         "--workspace-name": "NAME", "--workspace-layout": "LAYOUT",
                         "--workspace-owner": "DEFAULT_OWNER", "--workspace-default-owner": "DEFAULT_OWNER"}
    workspace_overrides = {}
    options = {"--config", "--profile", "--only", "--without"} | set(workspace_options)
    switches = {"--dry-run", "--json", "--with-arena", "--with-lerobot", "--with-gr00t"}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in values:
            raise ValueError("Duplicate options are unsupported.")
        if arg in switches:
            values[arg] = True
        elif arg in options:
            index += 1
            if index >= len(argv) or argv[index].startswith("-") or (not argv[index] and arg not in workspace_options):
                raise ValueError("Missing option value.")
            values[arg] = argv[index]
            if arg in workspace_options:
                field = workspace_options[arg]
                if field in workspace_overrides:
                    raise ValueError("Duplicate workspace aliases are unsupported.")
                workspace_overrides[field] = argv[index]
        elif arg.startswith("-"):
            raise ValueError("Unsafe or unsupported preview option; no profile was read.")
        else:
            positional.append(arg)
        index += 1
    if positional != ["install"] or not values.get("--dry-run"):
        raise ValueError("Observation unknown: this mode has no admitted offline probe. Use install --dry-run --config PATH.")
    if "--config" in values and "--profile" in values:
        raise ValueError("Select exactly one profile source.")
    if "--config" not in values and "--profile" not in values:
        raise ValueError("An explicit --config PATH or --profile preset is required.")
    if "--profile" in values:
        names = {"default": "default-profile.yaml", "minimal": "minimal-headless.yaml", "full": "full-ecosystem.yaml"}
        if values["--profile"] not in names:
            raise ValueError("Unsupported profile preset.")
        values["--config"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config", names[values["--profile"]]))
    else:
        values["--config"] = os.path.abspath(values["--config"])
    for option in ("--only", "--without"):
        parts = values.get(option, "").split(",") if option in values else []
        if any(part not in dict(STAGES) for part in parts):
            raise ValueError("Unknown stage name; stage aliases are not supported by the installer.")
        values[option] = set(parts)
    values["workspace_overrides"] = workspace_overrides
    return values


def _preview(config, args, planner: object = False):
    rows = []
    for stage, description in STAGES:
        selected, reason = True, "Selected by installer stage rules; host checks were not run."
        if stage in args["--without"]:
            selected, reason = False, "Excluded by --without (takes precedence over --only)."
        elif args["--only"]:
            selected = stage in args["--only"]
            reason = "Selected by --only; host checks were not run." if selected else "Excluded by --only."
        elif stage in ('isaacsim', 'isaaclab'):
            key = {'isaacsim': 'CFG_SIMULATION_ISAACSIM_ENABLED',
                   'isaaclab': 'CFG_REPOSITORIES_ISAACLAB_ENABLED'}[stage]
            selected = config.get(key, 'true') == 'true'
            if not selected:
                reason = 'Disabled in profile.'
        elif stage in ENABLED:
            cli = {"arena": "--with-arena", "physical_ai": "--with-lerobot", "gr00t": "--with-gr00t"}[stage]
            selected = bool(args.get(cli)) or any(config.get("CFG_" + key) == "true" for key in ENABLED[stage])
            if not selected:
                reason = "Disabled in profile."
        elif stage == "demos":
            selected = config.get("CFG_DEMOS_DESKTOP_SHORTCUTS", config.get("CFG_ECOSYSTEM_DEMOS", "true")) == "true"
            if not selected:
                reason = "Disabled in profile."
        rows.append({"stage": stage, "status": "unknown" if selected else "excluded",
                     "proposed_action": description if selected else None,
                     "target": "unknown" if selected else None, "reason": reason,
                     "evidence": "profile-and-cli-only", "overwrite_effects": "unknown" if selected else None})
    selection_keys = {"CFG_" + key for keys in ENABLED.values() for key in keys}
    selection_keys.update(('CFG_SIMULATION_ISAACSIM_ENABLED', 'CFG_REPOSITORIES_ISAACLAB_ENABLED'))
    selection_keys.update(("CFG_DEMOS_DESKTOP_SHORTCUTS", "CFG_ECOSYSTEM_DEMOS", "CFG_PROFILE_NAME", "CFG_DESCRIPTION", "CFG_VERSION"))
    workspace: dict[str, object] = {"target_home": "unknown", "filesystem_status": "unknown"}
    for field, default in (("ROOT", ""), ("LAYOUT", "auto"), ("NAME", ""), ("DEFAULT_OWNER", "")):
        key = "CFG_WORKSPACE_" + field
        selection_keys.add(key)
        if field in args["workspace_overrides"]:
            value, source = args["workspace_overrides"][field], "cli"
        elif key in config:
            value, source = config[key], "profile"
        else:
            value, source = default, "default"
        workspace[field.lower()] = {"value": value, "source": source}
    # Trusted pure augmentation only. Older stage-only fixture distributions may
    # omit the new planner; they retain the original incomplete stage receipt.
    if planner is False:  # pure test seam; CLI injects the pre-confined module
        try:
            planner = _trusted_module("legacy_action_plan")
        except FileNotFoundError:
            planner = None
    plan = getattr(planner, 'build_legacy_action_plan')(config, rows, workspace) if planner else None
    if plan is not None:
        plan['unmapped_fields'] = sorted(set(plan['unmapped_fields']) - selection_keys)
    augmentation = {"legacy_action_plan": plan, "action_plan_status": "available" if plan else "unavailable"}
    limitations = ["Host state, resolved targets and overwrite effects are unknown.",
                   "Only stage selection is evaluated; other profile fields are not an executable plan.",
                   "Independent safety review and explicit physical-run approval remain required."]
    if plan is not None:
        limitations[:2] = ["Targets are profile-derived intent, not existing-state observations; /target-home is symbolic.",
                           "Native subactions remain unqualified; no package/platform resolution or executable plan is claimed."]
    else:
        limitations.append("Concrete legacy planner unavailable in this distribution; stage-only fallback.")
    return {**augmentation, "scope": "offline-profile-only", "complete": False, "execution_authorized": False,
            "workspace_intent": workspace,
            "confinement": "landlock-readonly+seccomp-no-network-no-exec", "stages": rows,
            "unsupported_field_count": len(set(config) - selection_keys),
            "limitations": limitations}


def main(argv=None):
    # Admit inherited receipt FDs before root/parser errors or trusted loaders.
    try:
        if any(not (stat.S_ISFIFO(os.fstat(fd).st_mode) or os.isatty(fd)) for fd in (1, 2)):
            return 2
    except OSError:
        return 2
    if os.getuid() == 0 or os.geteuid() == 0:
        print("Safe preview refused: root is not permitted.", file=sys.stderr)
        return 77
    try:
        sandbox = _trusted_module("preview_sandbox")
    except (ImportError, OSError, SystemExit):
        print("Safe preview blocked: trusted sandbox unavailable.", file=sys.stderr)
        return 77
    try:
        sandbox.require_unprivileged()
    except (sandbox.SandboxError, OSError):
        print("Safe preview refused: unprivileged process credentials are required.", file=sys.stderr)
        return 77
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv in (["help"], ["--help"], ["-h"]):
        print("""Isaac Installer — offline preview entry (run without sudo)
  install --dry-run --config PATH [--json] [--only STAGES] [--without STAGES]
  install --dry-run --profile default|minimal|full [same options]
  Optional stage selection: --with-arena --with-lerobot --with-gr00t
  observe [--empty] / review-profile / export-profile: confined evidence and intent
  plan-profile / render-profile --desired-profile PATH --target-home HOME
  migration-profile --old-profile PATH --desired-profile PATH --repositories JSON --target-home HOME
  observe-targets --desired-profile PATH --target-home HOME: explicit metadata observation
  --output NEW_FILE: separate confined private report writer, never overwrite
  Full workflow and report schemas: docs/profile-discovery.md
Stages: driver,display,prereqs,python,devtools,physical_ai,hardware_teleop,
        isaacsim,isaaclab,arena,gr00t,demos
Preview admits only the above options. Other observation modes are unknown and
refused, not routed to legacy checks. Profile hooks/custom commands are refused.
Exit 2: incomplete/unknown/unsupported; 77: root or confinement refused.
Resource-limit signal termination is incomplete, never success.
No host qualification or physical-run authorization follows from preview.
Legacy apply remains separate and unqualified; named install/resume is blocked.
Workspace intent flags (also supported in preview): --workspace-root (alias --workspace-dir), --workspace-name,
--workspace-layout, --workspace-default-owner (alias --workspace-owner).""")
        return 0
    try:
        args = _arguments(argv)
    except ValueError as error:
        print("Safe preview blocked: " + str(error), file=sys.stderr)
        return 2
    try:
        parser = _trusted_module("profile_parser")  # trusted parser/PyYAML only; no profile read
        try:
            planner = _trusted_module("legacy_action_plan")  # pure output dependency, before confinement
        except FileNotFoundError:
            planner = None  # older stage-only distributions remain incomplete
    except (ImportError, OSError, SystemExit):
        print("Safe preview blocked: trusted sandbox/parser or PyYAML unavailable.", file=sys.stderr)
        return 77
    try:
        # Reject syntactically unsafe explicit overrides before pinning/reading
        # the profile. Cross-field precedence is validated by the shared parser.
        rules = _trusted_module("workspace_paths")
        overrides = args["workspace_overrides"]
        if "LAYOUT" in overrides and overrides["LAYOUT"] not in ("auto", "org", "flat", "named"):
            raise ValueError("Unsupported layout")
        for field in ("NAME", "DEFAULT_OWNER"):
            if overrides.get(field):
                rules.validate_segment(overrides[field])
        if overrides.get("ROOT"):
            rules.expand_path(overrides["ROOT"], "/target-home")
    except (ValueError, TypeError):
        print("Safe preview blocked: invalid explicit workspace option; no profile was read.", file=sys.stderr)
        return 2
    except (ImportError, OSError):
        print("Safe preview blocked: trusted workspace validator unavailable.", file=sys.stderr)
        return 77
    try:
        sandbox.confine_readonly([args["--config"]])
    except sandbox.SandboxError as error:
        print("Safe preview refused: " + str(error), file=sys.stderr)
        return 77
    try:
        if os.stat(args["--config"]).st_size > 262144:
            raise ValueError("Profile size limit exceeded.")
        payload = parser.parse_profile(args["--config"], workspace_overrides=args["workspace_overrides"])
        if len(payload) > 1048576:
            raise ValueError("Profile expansion limit exceeded.")
        parts = payload.decode("utf-8").split("\0")[:-1]
        config = dict(zip(parts[::2], parts[1::2]))
        # The shipped presets contain this example even when native standalone
        # selection cannot execute it. Do not echo or interpret its value. This
        # exact exception is not a general hook/custom-command admission.
        inactive_executable_fields = []
        inactive_build_key = "CFG_SIMULATION_ISAACSIM_CUSTOM_BUILD_BUILD_COMMAND"
        if (config.get("CFG_SIMULATION_ISAACSIM_SOURCE_TYPE") == "standalone"
                and config.get("CFG_SIMULATION_ISAACSIM_CUSTOM_BUILD_ENABLED") == "false"
                and inactive_build_key in config):
            del config[inactive_build_key]
            inactive_executable_fields.append(inactive_build_key)
        if any(any(word in key.split("_") for word in ("HOOK", "HOOKS", "COMMAND", "COMMANDS", "SCRIPT")) for key in config):
            raise ValueError("Executable fields are unsupported.")
        data = _preview(config, args, planner=planner)
        data["inactive_executable_fields"] = inactive_executable_fields
    except (OSError, ValueError, TypeError, RecursionError, MemoryError, parser.yaml.YAMLError):
        print("Safe preview blocked: invalid, unsupported or oversized profile; no content is echoed.", file=sys.stderr)
        return 2
    if args.get("--json"):
        print(json.dumps(data, indent=2))
    else:
        print("Incomplete offline profile-only preview; no host checks or execution approval.")
        for field in data["inactive_executable_fields"]:
            print("Inactive executable example omitted (value not disclosed):", field)
        for row in data["stages"]:
            print("{stage}: {status} — {reason}".format(**row))
        print("Workspace intent (not a filesystem resolution):", json.dumps(data["workspace_intent"]))
        print("Unsupported/non-selection fields:", data["unsupported_field_count"])
        plan = data.get("legacy_action_plan")
        if plan:
            print("Concrete native intent (not executable):", plan['home_binding'])
            for action in plan['actions']:
                print(json.dumps(action, sort_keys=True))
            print("Unmapped action fields:", json.dumps(plan['unmapped_fields']))
        else:
            print("Concrete legacy planner unavailable; stage-only fallback.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
