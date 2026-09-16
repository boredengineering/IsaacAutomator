#!/usr/bin/python3
"""Confined desired-profile rendering and concrete planning; never apply."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('Invalid profile workflow arguments.')


def main(argv=None):
    # Admit inherited receipt FDs before root/parser errors or trusted loaders.
    try:
        if any(not (stat.S_ISFIFO(os.fstat(fd).st_mode) or os.isatty(fd)) for fd in (1, 2)):
            return 2
    except OSError:
        return 2
    if os.getuid() == 0 or os.geteuid() == 0:
        print('Profile workflow refused as root.', file=sys.stderr)
        return 77
    parser = Parser(description='Offline desired-profile planning and rendering; no execution.')
    parser.add_argument('command', choices=('plan-profile', 'render-profile', 'migration-profile', 'observe-targets', 'status', 'audit', 'install'))
    parser.add_argument('--desired-profile', required=True)
    parser.add_argument('--target-home', required=True)
    parser.add_argument('--adapter', choices=('local', 'ansible', 'packer'), default='local')
    parser.add_argument('--evidence')
    parser.add_argument('--old-profile')
    parser.add_argument('--repositories')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(argv)
        if args.command == 'install' and not args.dry_run:
            raise ValueError('Only dry-run installation planning is admitted.')
        if args.command == 'migration-profile':
            if not args.old_profile or not args.repositories:
                raise ValueError('Migration needs explicitly selected old profile and repository descriptions.')
        elif args.old_profile or args.repositories:
            raise ValueError('Migration inputs are only valid for migration previews.')
        if args.command == 'observe-targets' and args.evidence:
            raise ValueError('Explicit observation does not consume supplied target evidence.')
        core = Path(__file__).resolve().parent
        sys.path.insert(0, str(core))
        sys.path.insert(0, str(core.parents[2]))
        from preview_sandbox import confine_readonly, require_unprivileged
        from workspace_paths import expand_path
        from src.python import workstation_profile
        from action_plan import build_action_plan
        from discovery_cli import _read_json, _dump_json
        from profile_parser import read_profile_text
        from plan_evidence import validate_evidence
        # Public shipped presets are trusted code inputs, not observed files.
        # Load before confinement; user-provided YAML is still read only after it.
        presets = {name: workstation_profile.load_profile(name) for name in workstation_profile.PRESETS}
        adapters = None
        migration = None
        collector = None
        if args.command == 'render-profile':
            from src.python import profile_adapters as adapters
        if args.command == 'migration-profile':
            from migration_preview import build_migration_preview as migration
        if args.command == 'observe-targets':
            from target_observation import collect_evidence as collector
        require_unprivileged()
        # Validate target syntax only: the controller is not the target machine.
        target_home = str(expand_path(args.target_home, '/target-home'))
        if target_home != args.target_home or target_home in ('/', '/home', '/root'):
            raise ValueError('Select an explicit non-root target user home.')
        paths = [args.desired_profile] + ([args.evidence] if args.evidence else [])
        if migration is not None:
            paths.extend([args.old_profile, args.repositories])
        confine_readonly(paths)
        profile = workstation_profile.parse_profile_text(read_profile_text(args.desired_profile))
        profile = workstation_profile.resolve_document(profile, presets=presets)['profile']
        evidence = _read_json(args.evidence) if args.evidence else None
        if migration is not None:
            if evidence is not None:
                if (type(evidence) is not dict or any(type(row) is not dict or
                        set(row) - {'state', 'dirty', 'conflict'} for row in evidence.values())):
                    raise ValueError('Invalid migration evidence.')
                validate_evidence({path: {key: value for key, value in row.items() if key != 'dirty'}
                                   for path, row in evidence.items()})
            old = workstation_profile.parse_profile_text(read_profile_text(args.old_profile))
            old = workstation_profile.resolve_document(old, presets=presets)['profile']
            report = migration(old, profile, target_home, _read_json(args.repositories), observed=evidence)
            complete = True  # A completed comparison is explicitly never migration/apply support.
        elif adapters is not None:
            evidence = validate_evidence(evidence) if evidence is not None else None
            report = adapters.render_profile(profile, args.adapter, target_home)
            complete = report['render_supported']
        else:
            evidence = validate_evidence(evidence) if evidence is not None else None
            report = build_action_plan(profile, target_home=target_home, observed=evidence)
            if collector is not None:
                # Plain strict evidence mapping is directly consumable by
                # --evidence. Managed remains false; no health/approval claim.
                print(_dump_json(collector(report, target_home=target_home)))
                return 0
            complete = all(row['status'] in ('satisfied', 'excluded', 'would_change')
                           for row in report['actions']) and not profile.get('draft', False)
        report['execution_authorized'] = False
        report['evidence_scope'] = 'supplied-metadata-unverified' if evidence else 'profile-only'
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
        return 0 if complete else 2
    except (ValueError, OSError, RuntimeError, ImportError, KeyError, TypeError, RecursionError, MemoryError):
        print('Profile workflow refused: invalid or unsupported input, or confinement unavailable. No application performed.',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
