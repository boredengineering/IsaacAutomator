#!/usr/bin/python3
"""Explicit discovery/review entry; never executes installer functions."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

MAX_REPORT_BYTES = 8 * 1024 * 1024


class InputError(ValueError):
    """Fixed-message CLI input error; never render user input."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError('Invalid discovery arguments; consult --help.')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError('Duplicate JSON keys are unsupported.')
        result[key] = value
    return result


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise InputError('Invalid JSON number.')
    return number


def _dump_json(document):
    payload = json.dumps(document, ensure_ascii=True, sort_keys=True, allow_nan=False)
    if len(payload.encode('utf-8')) + 1 > MAX_REPORT_BYTES:
        raise InputError('Report exceeds output limit; reduce the selected entry budget.')
    return payload


def _read_json(path):
    """Read only a bounded explicitly admitted JSON file, never follow links."""
    if not isinstance(path, str) or not path.startswith('/'):
        raise InputError('Report paths must be absolute.')
    parts = path.split('/')[1:]
    if any(part in ('', '.', '..') for part in parts):
        raise InputError('Invalid report path.')
    directory = os.open('/', os.O_PATH | os.O_DIRECTORY)
    fd = None
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_REPORT_BYTES:
            raise InputError('Report is not an admitted bounded regular file.')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            payload = stream.read(MAX_REPORT_BYTES + 1)
        if len(payload) > MAX_REPORT_BYTES:
            raise InputError('Report exceeds input limit.')
        return json.loads(payload, object_pairs_hook=_unique_pairs,
                          parse_float=_finite_float,
                          parse_constant=lambda value: (_ for _ in ()).throw(InputError('Invalid JSON number.')))
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def _load_bundle(path, discovery):
    bundle = _read_json(path)
    if type(bundle) is not dict or set(bundle) != {'baseline', 'candidate', 'review'}:
        raise InputError('Expected a discovery report bundle.')
    # Recompute review rather than trust stale or forged summary data.
    bundle['review'] = discovery.build_review(bundle['baseline'], bundle['candidate'])
    return bundle


def main(argv=None):
    # Admit inherited receipt FDs before root/parser errors or trusted loaders.
    try:
        if any(not (stat.S_ISFIFO(os.fstat(fd).st_mode) or os.isatty(fd)) for fd in (1, 2)):
            return 2
    except OSError:
        return 2
    if os.geteuid() == 0:
        print('Discovery refused as root; use an unprivileged account.', file=sys.stderr)
        return 2
    parser = Parser(description='Bounded metadata discovery and review; never installs or applies.')
    commands = parser.add_subparsers(dest='command', required=True)
    observe_parser = commands.add_parser('observe')
    observe_parser.add_argument('--empty', action='store_true', help='Start explicit intent review without observing targets.')
    observe_parser.add_argument('--workspace-root')
    observe_parser.add_argument('--workspace-name')
    observe_parser.add_argument('--dist-info', action='append', default=[])
    observe_parser.add_argument('--conda-meta', action='append', default=[])
    observe_parser.add_argument('--metadata-source', action='append', default=[],
                                help='Explicit bounded metadata selection as a JSON object; repeatable.')
    observe_parser.add_argument('--git-source', action='append', default=[],
                                help='Explicit Git metadata selection as a JSON object; never runs Git.')
    observe_parser.add_argument('--environment', default='unspecified')
    observe_parser.add_argument('--target', default='selected-target')
    observe_parser.add_argument('--previous-report')
    observe_parser.add_argument('--max-entries', type=int)
    observe_parser.add_argument('--max-bytes', type=int)
    observe_parser.add_argument('--max-seconds', type=float)
    host_parser = commands.add_parser('import-host-report', help='Import portable metadata without accessing host paths.')
    host_parser.add_argument('--report', required=True)
    host_parser.add_argument('--previous-report')
    review_parser = commands.add_parser('review-profile')
    review_parser.add_argument('--report', required=True)
    review_selection = review_parser.add_mutually_exclusive_group(required=True)
    review_selection.add_argument('--decisions')
    review_selection.add_argument('--field-id')
    review_parser.add_argument('--decision', choices=('accept', 'edit', 'reject', 'defer', 'declare'))
    review_parser.add_argument('--value-json')
    export_parser = commands.add_parser('export-profile')
    export_parser.add_argument('--report', required=True)
    export_parser.add_argument('--name', required=True)
    export_parser.add_argument('--format', choices=('json', 'yaml'), default='json')
    try:
        args = parser.parse_args(argv)
        optional_files = []
        metadata_sources, git_sources = [], []
        if args.command == 'observe':
            if args.empty and (args.workspace_root or args.dist_info or args.conda_meta or
                               args.metadata_source or args.git_source):
                raise InputError('Empty intent review cannot also observe selected targets.')
            if len(args.git_source) > 16:
                raise InputError('Select at most 16 repositories.')
            for selected in args.git_source:
                if len(selected) > 8192:
                    raise InputError('Git selection exceeds input limit.')
                source = json.loads(selected, object_pairs_hook=_unique_pairs)
                required = {'id', 'root', 'git_dir', 'common_dir', 'ref_paths'}
                if (type(source) is not dict or not required <= source.keys() or
                        source.keys() - required - {'component'} or
                        any(type(source[key]) is not str for key in required - {'ref_paths'}) or
                        type(source['ref_paths']) is not list or len(source['ref_paths']) > 16 or
                        any(type(ref) is not str or not ref.startswith('refs/') or
                            any(part in ('', '.', '..') for part in ref.split('/'))
                            for ref in source['ref_paths'])):
                    raise InputError('Invalid Git metadata selection.')
                for key in ('root', 'git_dir', 'common_dir'):
                    path = source[key]
                    if not path.startswith('/') or any(part in ('', '.', '..') for part in path.split('/')[1:]):
                        raise InputError('Git roots must be explicit absolute paths.')
                root, git_dir, common = source['root'], source['git_dir'], source['common_dir']
                if root + '/.git' != git_dir:
                    optional_files.append(root + '/.git')
                optional_files.extend([root + '/.gitmodules', git_dir + '/HEAD', git_dir + '/commondir',
                                       common + '/config', common + '/packed-refs'])
                optional_files.extend(common + '/' + ref for ref in source['ref_paths'])
                git_sources.append(source)
            if len(args.metadata_source) > 32:
                raise InputError('Select at most 32 metadata sources.')
            for selected in args.metadata_source:
                if len(selected) > 8192:
                    raise InputError('Metadata selection exceeds input limit.')
                source = json.loads(selected, object_pairs_hook=_unique_pairs)
                required = {'id', 'path', 'format', 'environment', 'placement'}
                if (type(source) is not dict or not required <= source.keys() or
                        source.keys() - required - {'runtime'} or
                        any(type(value) is not str for value in source.values())):
                    raise InputError('Invalid metadata selection.')
                metadata_sources.append(source)
            if bool(args.workspace_root) != bool(args.workspace_name):
                raise InputError('Workspace root and name must be supplied together.')
            paths = ([args.workspace_root] if args.workspace_root else []) + args.dist_info + args.conda_meta
            paths.extend(source['path'] for source in metadata_sources)
            if not paths and not optional_files and not args.empty:
                raise InputError('Select at least one metadata source.')
            if args.previous_report:
                paths.append(args.previous_report)
        elif args.command == 'import-host-report':
            paths = [args.report] + ([args.previous_report] if args.previous_report else [])
        elif args.command == 'review-profile':
            if (args.decisions and (args.decision or args.value_json is not None) or
                    args.field_id and (not args.decision or
                        args.decision in ('edit', 'declare') and args.value_json is None) or
                    args.value_json is not None and len(args.value_json) > 8192):
                raise InputError('Invalid explicit review decision.')
            paths = [args.report] + ([args.decisions] if args.decisions else [])
        else:
            paths = [args.report]
        if len(paths) > 32:
            raise InputError('Select at most 32 input paths.')
        # -I excludes environment/user-site imports. Only this trusted code directory
        # is added, before confinement; selected environments are never imported.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import profile_discovery as discovery
        from preview_sandbox import confine_readonly

        if args.command == 'export-profile':
            import desired_profile
            import yaml

        if optional_files:
            confine_readonly(paths, optional_files=list(dict.fromkeys(optional_files)))
        elif args.command == 'observe' and args.empty:
            confine_readonly(paths, allow_empty=True)
        else:
            confine_readonly(paths)
        if args.command == 'export-profile':
            prior = _load_bundle(args.report, discovery)
            exported = desired_profile.export_candidate(prior['baseline'], prior['candidate'], name=args.name)
            if args.format == 'yaml':
                print(yaml.safe_dump(exported['profile'], sort_keys=False, allow_unicode=False), end='')
            else:
                print(_dump_json(exported))
            return 0 if exported['complete'] else 2
        if args.command == 'import-host-report':
            prior = _load_bundle(args.previous_report, discovery) if args.previous_report else None
            baseline = discovery._host.baseline(_read_json(args.report), args.report, discovery,
                                                previous=prior['baseline'] if prior else None)
            candidate = discovery.propose(baseline, previous=prior['candidate'] if prior else None)
        elif args.command == 'observe':
            packages = []
            for fmt, selected in [('dist-info', args.dist_info), ('conda', args.conda_meta)]:
                for path in selected:
                    identity = json.dumps([fmt, path, args.environment], ensure_ascii=True)
                    source_id = fmt + '-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
                    packages.append({'id': source_id, 'path': path,
                                     'format': fmt, 'environment': args.environment})
            workspaces = ([{'id': 'workspace', 'root': args.workspace_root, 'name': args.workspace_name}]
                          if args.workspace_root else [])
            prior = (_load_bundle(args.previous_report, discovery)
                     if args.previous_report else None)
            previous = prior['candidate'] if prior is not None else None
            extra_sources: dict = {'metadata_sources': metadata_sources} if metadata_sources else {}
            limits = {key: getattr(args, key) for key in ('max_entries', 'max_bytes', 'max_seconds')
                      if getattr(args, key) is not None}
            if limits:
                extra_sources['limits'] = limits
            if git_sources:
                extra_sources['git_sources'] = git_sources
            baseline = discovery.observe(workspaces=workspaces, package_sources=packages, target=args.target,
                                         previous_baseline=prior['baseline'] if prior is not None else None,
                                         **extra_sources)
            candidate = discovery.propose(baseline, previous=previous)
        else:
            prior = _load_bundle(args.report, discovery)
            baseline, candidate = prior['baseline'], prior['candidate']
            if args.decisions:
                decisions = _read_json(args.decisions)
            else:
                decision = {'field_id': args.field_id, 'decision': args.decision}
                if args.value_json is not None:
                    decision['value'] = json.loads(args.value_json, object_pairs_hook=_unique_pairs,
                                                  parse_float=_finite_float,
                                                  parse_constant=lambda value: (_ for _ in ()).throw(InputError('Invalid JSON number.')))
                decisions = [decision]
            if type(decisions) is not list or len(decisions) > 128:
                raise InputError('Decisions must be a bounded list.')
            for decision in decisions:
                if (type(decision) is not dict or not {'field_id', 'decision'} <= decision.keys()
                        or decision.keys() - {'field_id', 'decision', 'value', 'reason', 'required'}):
                    raise InputError('Unsupported review decision fields.')
                candidate = discovery.review(candidate, **decision)
        output = {'baseline': baseline, 'candidate': candidate,
                  'review': discovery.build_review(baseline, candidate)}
        print(_dump_json(output))
        return 0
    except (ValueError, OSError, RuntimeError, ImportError, RecursionError, KeyError, TypeError, MemoryError):
        print('Discovery refused: invalid input or required confinement unavailable; no installation performed.',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
