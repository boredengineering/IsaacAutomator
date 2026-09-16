"""Manual, read-only checks of an explicitly preprepared container runtime.

Only stdlib is imported. Run with a reviewed Python: -I -S -B this-file.py.
The selected executable and its stdlib/loader are trusted prerequisites, NOT a
sandbox for hostile interpreters. No site initialization, .pth, project code,
robotics/Torch imports, environment discovery or installation is performed.
PEP 566 METADATA and PEP 610 direct_url.json are bounded data, not executable
proof of importability. CPython -S before 3.14 does not initialize venv prefixes:
such a prefix mismatch fails closed, rather than evaluating site.py/.pth.
"""
import argparse
from email.parser import Parser
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import time
from urllib.parse import unquote, urlsplit

MAX_BYTES = 128 * 1024
MAX_ITEMS = 128
PROTOCOL_CODE = '''import json,sys,sysconfig
p=sysconfig.get_paths()
print(json.dumps(dict(protocol=1,version=".".join(map(str,sys.version_info[:3])),
 executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,
 package_paths=sorted(set([p["purelib"],p["platlib"]])),
 isolated=sys.flags.isolated,no_site=sys.flags.no_site)))
'''


def _path(value):
    if (type(value) is not str or len(value) > 4096 or not value.startswith('/')
            or value.startswith('//') or len(value.split('/')) < 3
            or any(p in ('', '.', '..') for p in value.split('/')[1:])
            or any(ord(c) < 32 for c in value)):
        raise ValueError('expected narrow absolute literal path')
    return Path(value)


def _read(path):
    """Read one bounded regular metadata file; never follow ancestor links."""
    path = _path(str(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(leaf, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                raise ValueError('metadata is not a bounded single-link regular file')
            raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('metadata byte limit exceeded')
            return raw.decode('utf-8')
    finally:
        os.close(fd)


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON field')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except RecursionError:
        raise ValueError('JSON nesting limit exceeded') from None
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError('JSON nesting limit exceeded')
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
    return value


def _name(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('invalid distribution name')
    return re.sub('[-_.]+', '-', value).lower()


def _directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in _path(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return True
    finally:
        os.close(fd)


def _probe(executable, timeout):
    """Bound process wall-time and combined output in memory, no scratch files."""
    _path(executable)
    argv = [executable, '-I', '-S', '-B', '-c', PROTOCOL_CODE]
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, cwd='/', env={'LC_ALL': 'C'},
                          close_fds=True) as process:
        try:
            assert process.stdout is not None and process.stderr is not None
            stdout_fd, stderr_fd = process.stdout.fileno(), process.stderr.fileno()
            chunks = {stdout_fd: bytearray(), stderr_fd: bytearray()}
            with selectors.DefaultSelector() as selector:
                for fd in chunks:
                    os.set_blocking(fd, False)
                    selector.register(fd, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout
                total = 0
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError('interpreter protocol timeout')
                    for key, _ in selector.select(min(remaining, 0.1)):
                        raw = os.read(key.fd, 4096)
                        total += len(raw)
                        if total > MAX_BYTES:
                            raise ValueError('interpreter protocol byte limit exceeded')
                        if raw:
                            chunks[key.fd].extend(raw)
                        else:
                            selector.unregister(key.fileobj)
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if process.returncode or chunks[stderr_fd]:
                raise ValueError('interpreter protocol failed or emitted stderr')
            return _json(chunks[stdout_fd].decode('utf-8'))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def validate_runtime(runtime, *, check_paths=True):
    """Pure input validation, before launching or opening any selected path."""
    if type(runtime) is not dict or len(json.dumps(runtime)) > MAX_BYTES:
        raise ValueError('runtime must be a bounded mapping')
    if set(runtime) - {'intent', 'environment_container', 'components', 'build_outputs',
                       'original_environment_declarations', 'check'}:
        raise ValueError('unknown runtime requirement fields')
    intent = runtime.get('intent', {})
    if type(intent) is not dict or set(intent) - {'python', 'torch', 'torchvision', 'manager', 'environment', 'cuda_runtime', 'architecture'}:
        raise ValueError('unknown runtime intent')
    for key in ('python', 'torch', 'torchvision'):
        pin = intent.get(key)
        pattern = r'[0-9]+\.[0-9]+(?:\.[0-9]+)?' if key == 'python' else r'[0-9]+\.[0-9]+\.[0-9]+(?:\+cu[0-9]+)?'
        if pin is not None and (type(pin) is not str or not re.fullmatch(pattern, pin)):
            raise ValueError('unsupported version pin')
    prefix = runtime.get('environment_container')
    if prefix is not None:
        _path(prefix)
    selection = runtime.get('check', {})
    if type(selection) is not dict or set(selection) - {'interpreter', 'distributions', 'source_bindings', 'bundle'}:
        raise ValueError('unknown checker selection fields; no readiness booleans accepted')
    if selection.get('interpreter') is not None:
        _path(selection['interpreter'])
    distributions = selection.get('distributions', {})
    if type(distributions) is not dict or len(distributions) > MAX_ITEMS:
        raise ValueError('distribution selection bound exceeded')
    seen = set()
    for name, path in distributions.items():
        canonical = _name(name)
        if canonical in seen:
            raise ValueError('duplicate normalized distribution name')
        seen.add(canonical)
        _path(path)
    components = runtime.get('components', {})
    if type(components) is not dict or len(components) > MAX_ITEMS:
        raise ValueError('component selection bound exceeded')
    for name, component in components.items():
        _name(name)
        if type(component) is not dict or type(component.get('source', {})) is not dict:
            raise ValueError('invalid component source intent')
    for key, items in [('source_bindings', selection.get('source_bindings', [])),
                       ('build_outputs', runtime.get('build_outputs', []))]:
        if type(items) is not list or len(items) > MAX_ITEMS:
            raise ValueError('binding/build selection bound exceeded')
        seen = set()
        for item in items:
            if type(item) is not dict or item.get('component') not in components or item['component'] in seen:
                raise ValueError('unknown or duplicate component binding/build')
            seen.add(item['component'])
            if key == 'source_bindings':
                if set(item) - {'component', 'distribution', 'source_mapping', 'source_container'}:
                    raise ValueError('unknown source binding fields')
                _name(item.get('distribution'))
            else:
                _path(item.get('container'))
            _path(item.get('source_container'))
    if check_paths:
        def overlaps(a, b):
            a, b = PurePosixPath(a.casefold()), PurePosixPath(b.casefold())
            return a == b or a in b.parents or b in a.parents
        selected = list(distributions.values())
        if selection.get('interpreter'):
            selected.append(selection['interpreter'])
        for path in selected:
            if prefix is None or _path(prefix) not in _path(path).parents:
                raise ValueError('interpreter/metadata outside selected prefix')
        sources = [b['source_container'] for b in selection.get('source_bindings', [])]
        sources += [b['source_container'] for b in runtime.get('build_outputs', [])]
        writable = [b['container'] for b in runtime.get('build_outputs', [])]
        if prefix:
            writable.append(prefix)
        if any(overlaps(source, path) for source in sources for path in writable):
            raise ValueError('runtime/build location overlaps source')
        for i, path in enumerate(writable):
            if any(overlaps(path, other) for other in writable[:i]):
                raise ValueError('overlapping runtime/build locations')


def check_runtime(runtime, *, timeout=5):
    """Observe ONLY a caller-selected runtime. Never accept a readiness flag.

    matching/missing/mismatching are actual bounded observations. unsupported
    remains visible and does not turn selected_checks_match into parity proof.
    """
    validate_runtime(runtime)
    if type(timeout) not in (int, float) or not 0 < timeout <= 30:
        raise ValueError('timeout must be bounded to 30 seconds')
    checks = []

    def record(field, status, expected=None, observed=None, reason=None):
        checks.append(dict(field=field, status=status, expected=expected, observed=observed, reason=reason))

    intent = runtime.get('intent', {})
    selection = runtime.get('check', {})
    executable = selection.get('interpreter')
    observation = None
    if executable is None:
        record('interpreter', 'missing', reason='explicit preprepared interpreter path required')
    else:
        try:
            observation = _probe(executable, timeout)
            if (type(observation) is not dict or observation.get('protocol') != 1 or
                    observation.get('isolated') != 1 or observation.get('no_site') != 1):
                raise ValueError('invalid isolated interpreter protocol')
            for key in ('executable', 'prefix', 'base_prefix'):
                _path(observation[key])
            if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', observation['version']):
                raise ValueError('invalid interpreter version')
            paths = observation['package_paths']
            if type(paths) is not list or not 1 <= len(paths) <= 4:
                raise ValueError('invalid package paths')
            for path in paths:
                _path(path)
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            observation = None
            record('interpreter', 'missing', reason='isolated interpreter protocol unavailable or invalid')
    if observation:
        for key, expected in [('executable', executable), ('prefix', runtime.get('environment_container'))]:
            record(key, 'matching' if expected == observation[key] else 'mismatching', expected, observation[key],
                   'Before CPython 3.14, -S venv prefix initialization is unsupported; no site fallback' if key == 'prefix' else None)
        pin = intent.get('python')
        if pin:
            actual = observation['version']
            record('python', 'matching' if actual.split('.')[:len(pin.split('.'))] == pin.split('.') else 'mismatching', pin, actual)
        else:
            record('python', 'unsupported', reason='no explicit Python pin selected')
    distributions = selection.get('distributions', {})
    packages = {}
    for name, directory in distributions.items():
        canonical = _name(name)
        try:
            path = _path(directory)
            if not observation or str(path.parent) not in observation['package_paths'] or not path.name.endswith('.dist-info'):
                raise ValueError('metadata must be immediately in an observed interpreter package directory')
            if not runtime.get('environment_container') or _path(runtime['environment_container']) not in path.parents:
                raise ValueError('metadata outside selected prefix')
            data = Parser().parsestr(_read(path / 'METADATA'), headersonly=True)
            if len(data.get_all('Name', [])) != 1 or len(data.get_all('Version', [])) != 1 or _name(data['Name']) != canonical:
                raise ValueError('ambiguous or wrong distribution identity')
            packages[canonical] = dict(version=data['Version'], path=path)
        except (OSError, ValueError, UnicodeError):
            record('metadata.' + canonical, 'missing', reason='selected metadata absent, unsafe, ambiguous or outside interpreter package paths')
    for name in ('torch', 'torchvision'):
        pin = intent.get(name)
        if pin is not None:
            actual = packages.get(name, {}).get('version')
            record('packages.' + name, 'missing' if actual is None else 'matching' if pin == actual else 'mismatching', pin, actual)
    bindings = {item['component']: item for item in selection.get('source_bindings', [])}
    for component, component_intent in runtime.get('components', {}).items():
        source = component_intent.get('source', {})
        if not source:
            record('sources.' + component, 'missing', reason='selected component has no source intent')
            continue
        if source.get('mode') != 'git':
            record('sources.' + component, 'unsupported', expected=source,
                   reason='standalone/non-source runtime requires preprepared image; no archive or Kit verification')
            continue
        if not any(b['component'] == component for b in runtime.get('build_outputs', [])):
            record('builds.' + component + '.location', 'missing', reason='explicit out-of-tree build location required for Git source')
        binding = bindings.get(component)
        actual = None
        expected = binding.get('source_container') if binding else None
        if binding and _name(binding['distribution']) in packages:
            try:
                data = _json(_read(packages[_name(binding['distribution'])]['path'] / 'direct_url.json'))
                if type(data) is not dict or type(data.get('url')) is not str:
                    raise ValueError('source origin must be a literal URL string')
                url = urlsplit(data['url'])
                if url.scheme == 'file' and not url.netloc and not url.query and not url.fragment:
                    actual = str(_path(unquote(url.path)))
                else:
                    actual = data['url']
            except (OSError, ValueError, KeyError, TypeError, UnicodeError):
                pass
        record('sources.' + component + '.origin', 'missing' if actual is None or expected is None else
               'matching' if actual == expected else 'mismatching', expected, actual,
               'PEP 610 declared origin only, not effective import/editability proof')
        if expected:
            try:
                _directory(expected)
                record('sources.' + component + '.location', 'matching', expected, expected)
            except (OSError, ValueError):
                record('sources.' + component + '.location', 'missing', expected)
        record('sources.' + component + '.editability', 'unsupported', reason='no .pth, editable finder or project code is executed')
        record('sources.' + component + '.revision', 'unsupported', expected=source,
               reason='source mapping excludes .git; local direct_url does not prove repository/ref/revision')
    for build in runtime.get('build_outputs', []):
        field = 'builds.' + build['component']
        try:
            _directory(build['container'])
            record(field + '.location', 'matching', build['container'], build['container'])
        except (OSError, ValueError):
            record(field + '.location', 'missing', build['container'])
        record(field + '.backend', 'unsupported', reason='mount existence does not implement an out-of-tree editable build or prove writability')
    record('runtime_manager', 'unsupported', expected=intent.get('manager'),
           reason='isolated interpreter prefix is checked; manager installation/activation and environment label are not verified')
    record('gpu_abi', 'unsupported', expected={k: intent[k] for k in ('cuda_runtime', 'architecture') if k in intent},
           reason='no GPU/ABI, Torch/robotics imports or full-runtime parity qualification')
    return dict(checks=checks, selected_checks_match=not any(c['status'] in ('missing', 'mismatching') for c in checks),
                runtime_parity_verified=False, image_verified=False, gpu_abi_verified=False, activation_allowed=False,
                scope='selected interpreter and metadata only; image, loader, stdlib and executable trust are prerequisites')


def check_manifest(manifest, runtime_name):
    """Consume the rendered manifest, preserving blockers before observation."""
    if type(manifest) is not dict or len(json.dumps(manifest)) > MAX_BYTES:
        raise ValueError('manifest must be a bounded mapping')
    runtime = manifest['runtimes'][runtime_name]
    issues = manifest.get('issues', []) + manifest.get('checker_issues', [])
    if len(issues) > MAX_ITEMS:
        raise ValueError('manifest issue bound exceeded')
    if issues:
        return dict(checks=[dict(field='manifest.' + item['field'], status='missing',
                                expected=None, observed=None, reason=item['reason']) for item in issues],
                    selected_checks_match=False, runtime_parity_verified=False, image_verified=False, gpu_abi_verified=False, activation_allowed=False,
                    scope='manifest blocked; no selected interpreter or metadata observed')
    return check_runtime(runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args(argv)
    try:
        manifest = _json(_read(args.manifest))
        result = check_manifest(manifest, args.runtime)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['selected_checks_match'] else 1
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        print(json.dumps(dict(error='invalid or inaccessible selected manifest', runtime_parity_verified=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
