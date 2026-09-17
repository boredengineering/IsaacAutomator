#!/usr/bin/python3
"""Independent SYNTHETIC acceptance; never a real-host or approval receipt.

Run: /usr/bin/python3 -B .agents/references/isaac-installer/verification/gap-collection/run_acceptance.py
Only this script and fresh /tmp artifacts are owned by this rehearsal. The exact
repository wrapper and its two Python files are copied byte-for-byte into the
synthetic checkout, following installer_host_collector.test.py's copier seam.
All production execution starts AFTER the retained runner.confine() boundary.
Missing implementation fails closed; rerun explicitly after changes, never poll.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import traceback

ROOT = Path('/workspaces/IsaacAutomator')
HERE = Path(__file__).resolve().parent
VERSION = '6.0.1-rc.7+release.42383.32955d8d.gl'
STEPS = ('controls', 'wrapper-plan', 'wrapper-collect', 'import-host-report',
         'review-profile', 'reimport-host-report', 'export-yaml',
         'render-local', 'render-ansible', 'install-dry-run')
COPIES = ('collect-host-metadata', 'isaac-installer/tools/collect_repository_metadata.py',
          'isaac-installer/tools/collect_host_metadata.py')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def fingerprint(path):
    info = path.lstat()
    result = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
    if path.is_symlink():
        result['link'] = os.readlink(path)
    elif path.is_file():
        result['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def snapshot(trees):
    return {str(p): fingerprint(p) for tree in trees for p in [tree, *sorted(tree.rglob('*'))]}


def scalars(value):
    """Inspect evidence data without assuming the pending editable schema."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from scalars(item)
    elif isinstance(value, list):
        for item in value:
            yield from scalars(item)
    else:
        yield value


def child(base):
    # Loading the retained harness is not a production import. No collectors,
    # installers, repository tests, YAML loaders or observed runtimes imported.
    spec = importlib.util.spec_from_file_location('gap_boundary', HERE.parent / 'step1/isaac-step1-runner.py')
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    os.umask(0o077)
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', HOME=str(base / 'synthetic-home'),
                      TMPDIR=str(base), TMP=str(base), TEMP=str(base),
                      LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
    tempfile.tempdir = str(base)
    sys.dont_write_bytecode = True
    os.chdir(base)
    runner.confine(base)  # Exact existing grants, UID drop, Landlock and seccomp.
    assert os.geteuid() != 0
    reports = base / 'receipts'
    reports.mkdir(mode=0o700)
    receipt = {'synthetic_only': True, 'passed': False, 'execution_authorized': False,
               'uid': os.geteuid(), 'artifact_root': str(base), 'exact_sim_version': VERSION,
               'boundary': 'unchanged step1 runner.confine; no additional grants',
               'steps': [{'step': step, 'status': 'not-run', 'exit_code': None} for step in STEPS],
               'limitations': ['No real workstation observed; no user-approved desired YAML.',
                               'Synthetic source URL/checksum are not availability or integrity proof.',
                               'Cross-consumer rehearsal only, not full source/security review.',
                               'Ansible standalone role accepts final 6.0.1 only; exact prerelease must remain blocked.']}
    receipt_path = reports / 'receipt.json'
    current = 'controls'
    trees = []
    before = None
    raw = None
    raw_before = None
    marker = base / 'SYNTHETIC_EXECUTION_OCCURRED'

    def save():
        dump(receipt_path, receipt)

    def record(name):
        return next(row for row in receipt['steps'] if row['step'] == name)

    def run(name, argv, expected=0):
        nonlocal current
        current = name
        row = record(name)
        row.update(status='running', argv=list(map(str, argv)), expected_exit_code=expected)
        save()
        result = subprocess.run(row['argv'], capture_output=True, text=True,
                                cwd=base, env=dict(os.environ), timeout=45)
        stdout, stderr = reports / (name + '.stdout'), reports / (name + '.stderr')
        stdout.write_text(result.stdout)
        stderr.write_text(result.stderr)
        row.update(exit_code=result.returncode, stdout=str(stdout), stderr=str(stderr),
                   status='passed' if result.returncode == expected else 'failed')
        save()
        assert result.returncode == expected, '%s returned %s, expected %s; see %s' % (
            name, result.returncode, expected, stderr)
        return result

    def cli(name, args, filename, expected=0):
        output = reports / filename
        result = run(name, ['/bin/bash', ROOT / 'isaac-installer/bin/isaac-installer',
                            *args, '--output', output], expected)
        assert json.loads(result.stdout)['status'] == 'written'
        record(name)['artifact'] = str(output)
        save()
        return output

    def put(path, text, executable=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if executable:
            path.chmod(0o700)
        return path

    try:
        denied = []
        for mode in ('r', 'w'):
            try:
                with open(base.parent / 'outside-canary', mode):
                    pass
            except PermissionError:
                denied.append(mode)
        try:
            with socket.socket():
                pass
        except PermissionError:
            denied.append('network')
        assert denied == ['r', 'w', 'network'], denied
        record('controls').update(status='passed', exit_code=0, denied=denied)
        save()
        home, system = base / 'synthetic-home', base / 'synthetic-system'
        home.mkdir(); system.mkdir()
        workspace = home / 'Documents/GitHub/BoredEngineer'
        checkout = workspace / 'IsaacLab'
        excluded = home / 'Documents/GitHub/boredengineering/IsaacLab'
        for path, commit in ((checkout, 'a'), (excluded, 'c')):
            put(path / '.git/HEAD', 'ref: refs/heads/synthetic\n')
            put(path / '.git/refs/heads/synthetic', commit * 40 + '\n')
            put(path / '.git/config', '[remote "origin"]\nurl=https://github.com/example/IsaacLab.git\n')
            put(path / 'source-canary.txt', 'SYNTHETIC_SOURCE_UNCHANGED\n')
        put(home / 'IsaacSim/VERSION', VERSION + '\n')
        trap = '#!/bin/sh\nprintf SYNTHETIC_EXECUTION > ' + str(marker) + '\nexit 99\n'
        put(home / 'IsaacSim/isaac-sim.sh', trap, True)
        put(home / 'IsaacSim/python.sh', trap, True)
        put(checkout / 'isaaclab.sh', trap, True)
        put(system / 'etc/os-release', 'ID=synthetic\nPRETTY_NAME="SYNTHETIC SYSTEM OMITTED"\n')
        put(system / 'var/lib/dpkg/status', 'Package: synthetic-system-only\nVersion: 1.0\nStatus: install ok installed\nArchitecture: amd64\n\n')
        conda = home / 'miniconda3/envs/isaaclab'
        put(conda / 'conda-meta/python-3.12.json', json.dumps({'name': 'python', 'version': '3.12.1', 'files': ['x' * 70000]}))
        put(conda / 'conda-meta/_libgcc_mutex.json', json.dumps({'name': '_libgcc_mutex', 'version': '0.1'}))
        put(conda / 'bin/python', trap, True)
        venv = checkout / '.venv'
        put(venv / 'pyvenv.cfg', 'version = 3.12.1\n')
        put(venv / 'bin/python', trap, True)
        site = venv / 'lib/python3.12/site-packages'
        info = site / 'synthetic_editable-1.0.dist-info'
        put(info / 'METADATA', 'Metadata-Version: 2.1\nName: synthetic-editable\nVersion: 1.0\n\n' + 'SYNTHETIC_DESCRIPTION_NOT_EVIDENCE' * 5000)
        editable_source = checkout / 'source/synthetic_editable'
        put(editable_source / '__init__.py', 'raise RuntimeError("SYNTHETIC_MODULE_MUST_NOT_EXECUTE")\n')
        direct_url = put(info / 'direct_url.json', json.dumps({'url': editable_source.as_uri(), 'dir_info': {'editable': True}}))
        put(site / 'synthetic_editable.pth', str(editable_source) + '\n')
        put(site / 'synthetic_never_execute.pth', 'import pathlib; pathlib.Path(' + repr(str(marker)) + ').write_text("SYNTHETIC_EXECUTION")\n')

        # Copy the real wrapper exactly as the existing repository CLI tests do.
        # Put it outside the observed home so only collector outputs may appear
        # there, while the ENTIRE synthetic home/system must remain unchanged.
        wrapper_repo = base / 'synthetic-wrapper-checkout'
        copies = {}
        for relative in COPIES:
            source, destination = ROOT / relative, wrapper_repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copies[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
            assert hashlib.sha256(destination.read_bytes()).hexdigest() == copies[relative]
        dump(reports / 'wrapper-source-sha256.json', copies)
        receipt['wrapper_copy_hashes'] = str(reports / 'wrapper-source-sha256.json')
        trees = [home, system]
        before = snapshot(trees)
        dump(reports / 'source-canaries-before.json', before)
        raw = wrapper_repo / 'configs/private/host-software-03.json'
        args = ['--scope', 'software', '--workspace-name', 'BoredEngineer', '--include-editable',
                '--report-name', 'host-software-03.json', '--home', str(home), '--system-root', str(system)]
        wrapper = ['/bin/bash', wrapper_repo / 'collect-host-metadata']
        result = run('wrapper-plan', [*wrapper, '--plan', *args])
        plan = json.loads(result.stdout)
        assert plan['workspace_names'] == ['BoredEngineer']
        assert plan['scope'] == 'software' and plan['system_records'] == []
        assert plan['execution_authorized'] is False and plan['output'] == str(raw)
        assert not (wrapper_repo / 'configs').exists(), 'plan created output directories'
        run('wrapper-collect', [*wrapper, '--collect', *args])
        record('wrapper-collect')['artifact'] = str(raw)
        raw_before = fingerprint(raw)
        report = json.loads(raw.read_text())
        assert report['context']['identity'] == 'fixture'
        assert report['context']['execution_authorized'] is False
        assert report['workspace']['requested_name'] == 'BoredEngineer'
        assert report['workspace']['selected'] == str(workspace)
        assert report['workspace']['candidates'] == [str(workspace)]
        assert report['machine'] == {} and report['packages'] == []
        assert all(row['path'].startswith(str(workspace) + '/') for row in report['repositories'])
        assert str(excluded.parent) not in raw.read_text()
        assert report['isaacsim'][0]['version'] == VERSION
        assert raw.stat().st_mode & 0o777 == 0o600
        assert raw.parent.stat().st_mode & 0o777 == 0o700
        observed_conda = next(e for e in report['environments'] if e['path'] == str(conda))
        assert observed_conda['python'] == '3.12.1'
        assert {'name': '_libgcc_mutex', 'version': '0.1'} in observed_conda['packages']
        observed_venv = next(e for e in report['environments'] if e['path'] == str(venv))
        assert {'name': 'synthetic-editable', 'version': '1.0'} in observed_venv['packages']
        # Do not let an unfulfilled follow-up proposal masquerade as collected
        # editable evidence. Check exact source + metadata provenance, not an API
        # shape guessed while its implementation is still in flight.
        evidence = {k: v for k, v in report['details'].items() if k != 'followups'}
        values = list(scalars(evidence))
        assert str(direct_url) in values, 'editable direct_url provenance not collected'
        assert str(editable_source) in values or editable_source.as_uri() in values, 'editable source relationship missing'
        assert 'SYNTHETIC_DESCRIPTION_NOT_EVIDENCE' not in raw.read_text()
        imported = cli('import-host-report', ['import-host-report', '--report', raw], '02-imported.json')
        bundle = json.loads(imported.read_text())
        retained = bundle['baseline']['observations'][0]['value']
        assert retained['workspace'] == report['workspace']
        assert retained['isaacsim'] == report['isaacsim']
        assert retained['details'] == report['details'], 'import lost editable/source evidence'
        assert bundle['baseline']['original_observed_roots'] == [str(raw)]
        candidate = bundle['candidate']
        assert candidate['apply_supported'] is False
        assert all(f['decision'] is None for f in candidate['fields'])
        fields = {f['id']: f for f in candidate['fields']}
        assert fields['workspace:host.name']['value'] == 'BoredEngineer'
        decisions = [{'field_id': 'workspace:host.' + k, 'decision': 'accept'} for k in ('root', 'name', 'layout')]
        decisions += [
            {'field_id': 'components.selection', 'decision': 'edit', 'value': ['sim', 'lab']},
            {'field_id': 'component:lab.source', 'decision': 'accept'},
            {'field_id': 'component:lab.execution', 'decision': 'declare', 'value': 'native'},
            {'field_id': 'runtime:lab', 'decision': 'declare', 'value': {'manager': 'conda', 'environment': 'isaaclab', 'python': '3.12'}},
            {'field_id': 'component:sim.source', 'decision': 'declare', 'value': {
                'mode': 'standalone', 'version': VERSION,
                'url': 'https://example.org/synthetic-only.zip', 'sha256': 'b' * 64}},
            {'field_id': 'runtime:kit', 'decision': 'declare', 'value': {'manager': 'bundled', 'environment': 'kit'}},
            {'field_id': 'component:sim.execution', 'decision': 'declare', 'value': 'native'},
        ]
        decision_file = reports / '03-SYNTHETIC-decisions.json'
        dump(decision_file, decisions)
        receipt['synthetic_decisions'] = str(decision_file)
        reviewed = cli('review-profile', ['review-profile', '--report', imported, '--decisions', decision_file], '04-reviewed.json')
        refreshed = cli('reimport-host-report', ['import-host-report', '--report', raw, '--previous-report', reviewed], '05-reimported.json')
        refreshed_bundle = json.loads(refreshed.read_text())
        assert refreshed_bundle['candidate']['apply_supported'] is False
        sim = next(f for f in refreshed_bundle['candidate']['fields'] if f['id'] == 'component:sim.source')
        assert sim['value']['version'] == VERSION
        profile = cli('export-yaml', ['export-profile', '--report', refreshed, '--name', 'synthetic-gap-acceptance', '--format', 'yaml'], '06-SYNTHETIC-desired.yaml')
        import yaml  # System parser only, after confinement; no observed runtime.
        desired = yaml.safe_load(profile.read_text())
        assert VERSION in list(scalars(desired)), 'YAML lost exact prerelease/build'
        assert '6.0.1' not in list(scalars(desired)), 'final-release fallback forbidden'
        rendered = {}
        for adapter in ('local', 'ansible'):
            path = cli('render-' + adapter, ['render-profile', '--desired-profile', profile,
                       '--target-home', home, '--adapter', adapter], 'render-' + adapter + '.json',
                       expected=2 if adapter == 'ansible' else 0)
            rendered[adapter] = json.loads(path.read_text())
            assert rendered[adapter]['render_supported'] is (adapter == 'local')
            assert rendered[adapter]['execution_authorized'] is False
            assert VERSION in list(scalars(rendered[adapter]['artifact']))
        # This is an intentional consumer restriction, not parser data loss.
        # Do not silently replace the host's prerelease with the final release,
        # or weaken the real Ansible role to manufacture a supported preview.
        assert [b['field'] for b in rendered['ansible']['blockers']] == ['components.sim.source.version']
        assert rendered['ansible']['coverage']['components.sim.source.version']['status'] == 'unsupported'
        record('render-ansible')['expected_blocker'] = rendered['ansible']['blockers']
        assert rendered['local']['artifact']['repositories']['isaaclab']['tag'] == 'a' * 40
        assert rendered['ansible']['artifact']['isaaclab_git_checkpoint'] == 'a' * 40
        assert rendered['ansible']['artifact']['isaaclab_dir'] == str(checkout)
        dry_path = cli('install-dry-run', ['install', '--dry-run', '--desired-profile', profile,
                      '--target-home', home, '--json'], '10-dry-run.json', expected=2)
        dry = json.loads(dry_path.read_text())
        assert dry['execution_authorized'] is False and dry['evidence_scope'] == 'profile-only'
        action = next(a for a in dry['actions'] if a['id'] == 'component.lab')
        assert action['target'] == str(checkout) and action['status'] == 'unknown'
        assert VERSION in list(scalars(dry)), 'dry-run lost exact Sim source version'
        receipt.update(passed=True, collection_complete=report['coverage']['complete'],
                       local_render_supported=True, ansible_render_supported=False,
                       ansible_prerelease_blocker_verified=True, candidate_unapproved_before_review=True)
    except Exception as exc:
        receipt['failure'] = {'step': current, 'type': type(exc).__name__, 'message': str(exc)}
        record(current)['status'] = 'failed'
        (reports / 'failure.log').write_text(traceback.format_exc())
    finally:
        if before is not None:
            after = snapshot(trees)
            dump(reports / 'source-canaries-after.json', after)
            receipt['source_canaries_unchanged'] = before == after
            receipt['source_canary_entries'] = len(before)
            receipt['passed'] = receipt['passed'] and before == after
        receipt['execution_marker_absent'] = not marker.exists()
        receipt['passed'] = receipt['passed'] and not marker.exists()
        if raw_before is not None:
            receipt['raw_report_unchanged_after_import'] = raw_before == fingerprint(raw)
            receipt['passed'] = receipt['passed'] and receipt['raw_report_unchanged_after_import']
        save()
    print(json.dumps({'passed': receipt['passed'], 'receipt': str(receipt_path),
                      'failure': receipt.get('failure')}), flush=True)
    return 0 if receipt['passed'] else 1


def parent():
    if sys.argv[1:]:
        raise SystemExit('No live inputs accepted; run without arguments.')
    root = Path(tempfile.mkdtemp(prefix='isaac-gap-synthetic-'))
    root.chmod(0o755)
    outside = root / 'outside-canary'
    outside.write_text('SYNTHETIC_OUTSIDE_UNCHANGED')
    outside.chmod(0o666)  # Landlock, not DAC, must block the child's write.
    base = root / 'confined'
    base.mkdir(mode=0o700)
    if os.geteuid() == 0:
        os.chown(base, 65534, 65534)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(base), 'TMPDIR': str(base),
           'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run(['/usr/bin/python3', '-B', str(Path(__file__).resolve()), '--child', str(base)],
                            capture_output=True, text=True, cwd=base, env=env, timeout=180)
    (root / 'child.log').write_text(result.stdout + result.stderr)
    summary = {'synthetic_only': True, 'child_exit_code': result.returncode,
               'receipt': str(base / 'receipts/receipt.json'), 'log': str(root / 'child.log'),
               'outside_canary_unchanged': outside.read_text() == 'SYNTHETIC_OUTSIDE_UNCHANGED'}
    dump(root / 'result.json', summary)
    print(json.dumps({'result': str(root / 'result.json'), **summary}, indent=2))
    print(result.stdout + result.stderr)
    return result.returncode or (0 if summary['outside_canary_unchanged'] else 1)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--child']:
        # Internal parent-created /tmp directory only; reject arbitrary roots.
        base = Path(sys.argv[2]) if len(sys.argv) == 3 else Path('/')
        assert base.name == 'confined' and base.parent.parent == Path('/tmp')
        assert base.parent.name.startswith('isaac-gap-synthetic-') and not base.is_symlink()
        sys.exit(child(base))
    sys.exit(parent())
