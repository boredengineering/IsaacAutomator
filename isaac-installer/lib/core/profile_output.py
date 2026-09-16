#!/usr/bin/python3
"""Supervise a confined producer and separate, explicitly selected report writer.

This entry never reads a selected input itself, sources installer shell code, or
executes installation/sync. Only the writer opens the new approved destination.
"""
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys

CORE = Path(__file__).resolve().parent
MAX_REPORT_BYTES = 8 * 1024 * 1024
PATH_OPTIONS = {'--workspace-root', '--dist-info', '--conda-meta', '--report', '--decisions',
                '--previous-report', '--desired-profile', '--evidence', '--old-profile', '--repositories',
                '--target-home'}
REPEATABLE_OPTIONS = {'--dist-info', '--conda-meta', '--metadata-source', '--git-source'}
VALUE_OPTIONS = PATH_OPTIONS | REPEATABLE_OPTIONS | {
    '--output', '--workspace-name', '--environment', '--target', '--max-entries', '--max-bytes',
    '--max-seconds', '--field-id', '--decision', '--value-json', '--name', '--format', '--adapter'}
FLAG_OPTIONS = {'--empty', '--dry-run', '--json'}


def _canonical_options(arguments):
    """One interpretation for supervisor exclusions AND the producer's argv.

    No argparse abbreviations or repeated singleton options; equals is normalized
    before either side runs. Repeatable source selections keep every value.
    """
    options = {}
    index = 0
    while index < len(arguments):
        option, equals, value = arguments[index].partition('=')
        if option not in VALUE_OPTIONS | FLAG_OPTIONS:
            raise ValueError('Unknown persistent-output option.')
        if option in options and option not in REPEATABLE_OPTIONS:
            raise ValueError('Repeated singleton option.')
        if option in FLAG_OPTIONS:
            if equals:
                raise ValueError('Flag does not accept a value.')
            values = []
        else:
            if not equals:
                index += 1
                value = arguments[index]
            if not value or value.startswith('--'):
                raise ValueError('Missing option value.')
            values = [value]
        options.setdefault(option, []).extend(values)
        index += 1
    return options


def _producer_arguments(command, options):
    arguments = [command]
    for option, values in options.items():
        if option in FLAG_OPTIONS:
            arguments.append(option)
        else:
            for value in values:
                arguments.extend((option, value))
    return arguments


def _origin_contract(roots):
    # The producer validates the complete baseline; independently enforce the
    # bounded path-only exclusion wire contract, without inspecting intent.
    if type(roots) is not list or len(roots) > 128:
        raise ValueError('Invalid original observation roots.')
    for root in roots:
        if (type(root) is not str or len(root) > 4096 or not root.startswith('/') or
                any(part in ('', '.', '..') for part in root.split('/')[1:]) or
                any(ord(character) < 32 or ord(character) == 127 for character in root)):
            raise ValueError('Invalid original observation root.')
    if roots != sorted(set(roots)):
        raise ValueError('Noncanonical original observation roots.')
    return roots


def _limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))


def _run(script, arguments, data=None):
    return subprocess.run(['/usr/bin/python3', '-I', '-B', str(CORE / script), *arguments],
                          input=data, capture_output=True, cwd='/', close_fds=True,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                          preexec_fn=_limits, timeout=45)


def main(argv=None):
    # Children use capture pipes; their checks cannot protect our inherited
    # streams. Refuse silently before any diagnostic or subprocess work.
    try:
        if any(not (stat.S_ISFIFO(os.fstat(fd).st_mode) or os.isatty(fd)) for fd in (1, 2)):
            return 2
    except OSError:
        return 2
    args = list(sys.argv[1:] if argv is None else argv)
    destination = None
    writer_started = False
    try:
        if os.geteuid() == 0 or not args:
            raise ValueError('Invalid output request.')
        command = args[0]
        options = _canonical_options(args[1:])
        destination = options.pop('--output')[0]
        if not destination.startswith('/'):
            raise ValueError('Explicit absolute output required.')
        yaml_output = False
        if command in ('observe', 'import-host-report', 'review-profile', 'export-profile'):
            script = 'discovery_cli.py'
            if command == 'export-profile' and '--format' in options:
                yaml_output = options['--format'] == ['yaml']
                if yaml_output:
                    options['--format'] = ['json']
        elif command in ('plan-profile', 'render-profile', 'migration-profile', 'observe-targets', 'status', 'audit') or (
                command == 'install' and '--dry-run' in options and '--desired-profile' in options):
            script = 'profile_workflow.py'
        else:
            raise ValueError('Unsupported persistent-output command.')
        excluded = []
        for option, values in options.items():
            if option in PATH_OPTIONS:
                # Planning/rendering takes a remote target-home as syntax only;
                # only observe-targets treats that home as an observed root.
                if option != '--target-home' or command == 'observe-targets':
                    excluded.extend(values)
            elif option in ('--metadata-source', '--git-source'):
                for value in values:
                    source = json.loads(value)
                    excluded.extend(source[key] for key in ('path', 'root', 'git_dir', 'common_dir') if key in source)
        args = _producer_arguments(command, options)
        producer = _run(script, args)
        if producer.returncode not in (0, 2) or not producer.stdout or len(producer.stdout) > MAX_REPORT_BYTES:
            raise ValueError('Producer did not emit a bounded report.')
        document = json.loads(producer.stdout)
        if type(document) is not dict:
            raise ValueError('Invalid producer report.')
        if script == 'discovery_cli.py':
            if command == 'export-profile':
                if set(document) != {'profile', 'review', 'complete'} or type(document['complete']) is not bool:
                    raise ValueError('Invalid desired-profile report.')
                # This contract is computed by the confined producer from its
                # validated baseline, not candidate fields or desired intent.
                excluded.extend(_origin_contract(document['review']['original_observed_roots']))
                observations = document['review']['observation_coverage']
            else:
                if set(document) != {'baseline', 'candidate', 'review'}:
                    raise ValueError('Invalid observation report.')
                excluded.extend(_origin_contract(document['baseline']['original_observed_roots']))
                observations = document['baseline']['observations']
            for observation in observations:
                excluded.append(observation['evidence']['path'])
                if observation['id'].startswith('repository:') and 'value' in observation:
                    excluded.extend(observation['value'][key] for key in ('root', 'git_dir', 'common_dir'))
        if command == 'observe-targets':
            # The confined producer returns the strict target-evidence mapping.
            # Home covers missing descendants without admitting their paths;
            # external observed targets must still pass writer inode admission.
            target_home = options['--target-home'][0]
            excluded.append(target_home)
            for target in document:
                if not target.startswith('/'):
                    raise ValueError('Invalid observed target path.')
                if target != target_home and not target.startswith(target_home + '/'):
                    excluded.append(target)
        no_observed_roots = (command == 'observe' and '--empty' in options and
                             document['baseline']['original_observed_roots'] == [] and
                             not document['baseline']['observations'] and not excluded)
        payload = producer.stdout
        if yaml_output:
            import yaml
            payload = yaml.safe_dump(document['profile'], sort_keys=False, allow_unicode=False).encode('utf-8')
        maximum = 131072 if yaml_output else MAX_REPORT_BYTES
        if (not payload or len(payload) > maximum or (not excluded and not no_observed_roots)
                or any(type(p) is not str for p in excluded) or len(set(excluded)) > 128):
            raise ValueError('Invalid output bounds or selected roots.')
        writer_args = ['--output', destination, '--expected-bytes', str(len(payload)), '--max-bytes', str(maximum)]
        if no_observed_roots:
            writer_args.append('--no-observed-roots')
        for path in sorted(set(excluded)):
            writer_args.extend(('--exclude-root', path))
        writer_started = True
        written = _run('report_writer.py', writer_args, payload)
        receipt = json.loads(written.stdout)
        if type(receipt) is not dict:
            raise ValueError('Invalid writer receipt.')
        receipt['producer_exit_code'] = producer.returncode
        receipt['execution_authorized'] = False
        print(json.dumps(receipt, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return 0 if written.returncode == 0 and producer.returncode == 0 else 2
    except (ValueError, OSError, RuntimeError, ImportError, IndexError, KeyError, TypeError,
            RecursionError, MemoryError, subprocess.SubprocessError):
        receipt = {'status': 'possibly_partial' if writer_started else 'refused',
                   'execution_authorized': False, 'reason': 'output_workflow_failed'}
        if writer_started:
            receipt['destination'] = destination
        print(json.dumps(receipt, ensure_ascii=True, allow_nan=False))
        print('Output workflow refused or interrupted; no installation performed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
