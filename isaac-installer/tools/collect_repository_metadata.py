#!/usr/bin/python3
"""Collect host metadata, then publish a private report in this repository.

Unlike the portable CLI, this explicitly permits one repository output artifact.
No destination directories/files are created until observation has finished.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys


def main(argv=None):
    source = Path(__file__).absolute().with_name('collect_host_metadata.py')
    spec = importlib.util.spec_from_file_location('host_collector', source)
    assert spec is not None and spec.loader is not None
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    if not collector._streams_safe():
        return 2
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        print('Run on the host as your ordinary user, without sudo.', file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plan', action='store_true')
    modes.add_argument('--collect', action='store_true')
    parser.add_argument('--home', default=os.path.expanduser('~'))
    parser.add_argument('--system-root', default='/')
    parser.add_argument('--scope', choices=('all', 'software'), default='all')
    parser.add_argument('--workspace-name')
    parser.add_argument('--include-editable', action='store_true')
    parser.add_argument('--report-name', default='host-inventory.json',
                        help='new .json basename inside configs/private; never overwritten')
    parser.add_argument('--max-entries', type=int, default=4096)
    parser.add_argument('--max-bytes', type=int, default=8388608)
    parser.add_argument('--max-seconds', type=float, default=10.0)
    parser.add_argument('--max-depth', type=int, default=4)
    args = parser.parse_args(argv)
    try:
        repo = collector._absolute(str(source.parents[2]))
        home = collector._absolute(args.home)
        system = collector._absolute(args.system_root)
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.json', args.report_name)
                or not collector._safe_label(args.report_name)):
            raise ValueError('safe JSON report basename required')
        output = repo + '/configs/private/' + args.report_name
        limits = dict(max_entries=args.max_entries, max_bytes=args.max_bytes,
                      max_seconds=args.max_seconds, max_depth=args.max_depth)
        collector._validate_limits(limits)
        collector._validate_workspace_name(args.workspace_name)
        if not args.collect:
            plan_args = ['--plan', '--home', home, '--system-root', system,
                         '--scope', args.scope, '--output', output]
            if args.workspace_name is not None:
                plan_args.extend(['--workspace-name', args.workspace_name])
            if args.include_editable:
                plan_args.append('--include-editable')
            for key, value in limits.items():
                plan_args.extend(['--' + key.replace('_', '-'), str(value)])
            return collector.main(plan_args)

        # Hold the repository descriptor throughout; do not follow output symlinks.
        with collector._directory(repo) as repo_fd:
            report = collector.collect(home, system, scope=args.scope, workspace_name=args.workspace_name,
                                       include_editable=args.include_editable, **limits)
            payload = json.dumps(report, sort_keys=True, allow_nan=False) + '\n'
            try:
                os.mkdir('configs', 0o700, dir_fd=repo_fd)
            except FileExistsError:
                pass
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            configs_fd = os.open('configs', flags, dir_fd=repo_fd)
            try:
                try:
                    os.mkdir('private', 0o700, dir_fd=configs_fd)
                except FileExistsError:
                    pass
                private_fd = os.open('private', flags, dir_fd=configs_fd)
                try:
                    info = os.fstat(private_fd)
                    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                        raise ValueError('configs/private must be owned by you with mode 0700')
                    fd = os.open(args.report_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=private_fd)
                    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                        os.fchmod(stream.fileno(), 0o600)
                        stream.write(payload)
                finally:
                    os.close(private_fd)
            finally:
                os.close(configs_fd)
        print('Private host inventory written: ' + output)
        print('Coverage gaps may remain. No installation or profile approval was performed.')
        return 0
    except (ValueError, OSError):
        # Never expose raw metadata/paths from an arbitrary OS error.
        print('Collection refused: invalid input, existing report, or unsafe/unavailable destination. '
              'Use a new --report-name or a new portable collector output; '
              'configs/private must be your own non-symlink directory with mode 0700.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
