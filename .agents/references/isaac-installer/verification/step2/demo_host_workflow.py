#!/usr/bin/python3
"""Retained real CLI host-collector -> import -> review -> YAML demonstration.

All source data is synthetic. This never collects the executing machine's
packages or workstation files. The child inherits the bounded STEP1 sandbox.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bounded_host_demo', HERE.parent / 'step1/isaac-step1-runner.py')
assert spec is not None and spec.loader is not None
boundary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)


def child(base):
    os.environ.update(HOME=str(base), TMPDIR=str(base), PYTHONDONTWRITEBYTECODE='1')
    tempfile.tempdir = str(base)
    boundary.confine(base)
    home = base / 'host-home'
    system = base / 'host-system'
    reports = base / 'reports'
    reports.mkdir(mode=0o700)
    checkout = home / 'Documents/GitHub/BoredEngineer/IsaacLab'
    def fixture(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    fixture(checkout / '.git/HEAD', 'ref: refs/heads/synthetic\n')
    fixture(checkout / '.git/refs/heads/synthetic', 'a' * 40 + '\n')
    fixture(checkout / '.git/config', '[remote "origin"]\n url = https://github.com/example/IsaacLab.git\n')
    fixture(checkout / 'untracked-progress.txt', 'SYNTHETIC_PROGRESS_NOT_FOR_COLLECTION')
    fixture(home / 'IsaacSim/VERSION', '6.0.1\n')
    fixture(system / 'etc/os-release', 'PRETTY_NAME="Synthetic Ubuntu 22.04"\nID=ubuntu\nVERSION_ID="22.04"\n')
    fixture(system / 'proc/sys/kernel/osrelease', '6.8.0-synthetic\n')
    fixture(system / 'proc/cpuinfo', 'model name : Synthetic CPU\n')
    fixture(system / 'proc/meminfo', 'MemTotal: 123456 kB\n')
    fixture(system / 'proc/driver/nvidia/version', 'NVRM version: NVIDIA UNIX Kernel Module 595.84 Synthetic\n')
    fixture(system / 'usr/local/cuda/version.json', '{"cuda":{"version":"13.2"}}')
    fixture(system / 'var/lib/dpkg/status', 'Package: cmake\nStatus: install ok installed\nVersion: 3.22.1-1ubuntu1\nArchitecture: amd64\n\nPackage: synthetic-library\nStatus: install ok installed\nVersion: 1.0\nArchitecture: amd64\n\n')
    fixture(system / 'var/lib/apt/extended_states', 'Package: synthetic-library\nArchitecture: amd64\nAuto-Installed: 1\n\n')
    env_dir = home / 'miniconda3/envs/isaaclab'
    fixture(env_dir / 'conda-meta/python-3.12.json', '{"name":"python","version":"3.12.1"}')
    fixture(env_dir / 'conda-meta/synthetic-tool-1.0.json', '{"name":"synthetic-tool","version":"1.0"}')
    inputs = [p for tree in (home, system) for p in tree.rglob('*') if p.is_file()]
    entries_before = {str(p) for tree in (home, system) for p in tree.rglob('*')}
    before = {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode) for p in inputs}
    commands = []
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(base), 'LANG': 'C.UTF-8'}
    def run(argv, expected=0):
        result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=45)
        commands.append({'argv': argv, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        (reports / 'commands.json').write_text(json.dumps(commands, indent=2))
        assert result.returncode == expected, commands[-1]
        return result
    collector = str(ROOT / 'isaac-installer/tools/collect_host_metadata.py')
    raw = reports / '01-host-inventory.json'
    collector_args = ['/usr/bin/python3', '-I', '-S', '-B', collector, '--home', str(home),
                      '--system-root', str(system), '--output', str(raw)]
    planned = run([*collector_args, '--plan'])
    assert not raw.exists()
    (reports / '00-collection-plan.json').write_text(planned.stdout)
    run([*collector_args, '--collect'])
    report = json.loads(raw.read_text())
    assert report['context']['identity'] == 'fixture'
    assert report['workspace']['selected'] == str(checkout.parent)
    assert report['isaacsim'][0]['version'] == '6.0.1'
    assert report['repositories'][0]['commit'] == 'a' * 40
    assert {p['name'] for p in report['packages']} == {'cmake', 'synthetic-library'}
    details = report['details']
    assert details['version'] == 1
    assert details['repositories'][str(checkout)]['config'] == str(checkout / '.git/config')
    assert details['isaacsim'][str(home / 'IsaacSim')]['version'] == str(home / 'IsaacSim/VERSION')
    assert details['system_packages']['status']['cmake:amd64'] == 'install ok installed'
    assert details['package_groups']['groups']['build-tools'] == ['cmake:amd64']
    assert details['package_groups']['groups']['uncertain'] == ['synthetic-library:amd64']
    assert details['environments'][str(env_dir)]['packages']['synthetic-tool'] == str(env_dir / 'conda-meta/synthetic-tool-1.0.json')
    assert any(p['kind'] == 'environment-descriptors' and 'uv.lock' in p['records'] for p in details['followups'].values())
    assert all(p['action'] == 'request-explicit-scope' for p in details['followups'].values())
    assert 'SYNTHETIC_PROGRESS_NOT_FOR_COLLECTION' not in raw.read_text()
    entry = ['/bin/bash', str(ROOT / 'isaac-installer/bin/isaac-installer')]
    def cli(name, arguments, expected=0):
        output = reports / name
        result = run([*entry, *arguments, '--output', str(output)], expected)
        assert json.loads(result.stdout)['status'] == 'written'
        return output
    imported = cli('02-imported.json', ['import-host-report', '--report', str(raw)])
    bundle = json.loads(imported.read_text())
    assert all(f['decision'] is None for f in bundle['candidate']['fields'])
    assert bundle['baseline']['original_observed_roots'] == [str(raw)]
    decisions = [{'field_id': 'workspace:host.' + key, 'decision': 'accept'} for key in ('root', 'name', 'layout')]
    decisions += [
        {'field_id': 'components.selection', 'decision': 'edit', 'value': ['sim', 'lab']},
        {'field_id': 'component:lab.source', 'decision': 'accept'},
        {'field_id': 'component:lab.execution', 'decision': 'declare', 'value': 'native'},
        {'field_id': 'runtime:lab', 'decision': 'declare', 'value': {'manager': 'conda', 'environment': 'isaaclab', 'python': '3.12'}},
        {'field_id': 'component:sim.source', 'decision': 'declare', 'value': {'mode': 'standalone',
         'version': '6.0.1', 'url': 'https://example.org/synthetic-only.zip', 'sha256': 'b' * 64}},
        {'field_id': 'component:sim.execution', 'decision': 'declare', 'value': 'native'},
        {'field_id': 'runtime:kit', 'decision': 'declare', 'value': {'manager': 'bundled', 'environment': 'kit'}},
    ]
    decision_file = reports / '03-decisions.json'
    decision_file.write_text(json.dumps(decisions, indent=2))
    reviewed = cli('04-reviewed.json', ['review-profile', '--report', str(imported), '--decisions', str(decision_file)])
    refreshed = cli('05-reimported.json', ['import-host-report', '--report', str(raw), '--previous-report', str(reviewed)])
    profile = cli('06-desired.yaml', ['export-profile', '--report', str(refreshed), '--name', 'synthetic-host', '--format', 'yaml'])
    exported = cli('07-export-review.json', ['export-profile', '--report', str(refreshed), '--name', 'synthetic-host'])
    assert json.loads(exported.read_text())['complete']
    local = cli('08-local.json', ['render-profile', '--desired-profile', str(profile), '--target-home', str(home), '--adapter', 'local'])
    ansible = cli('09-ansible.json', ['render-profile', '--desired-profile', str(profile), '--target-home', str(home), '--adapter', 'ansible'])
    planned = cli('10-dry-run.json', ['install', '--dry-run', '--desired-profile', str(profile), '--target-home', str(home), '--json'], 2)
    l = json.loads(local.read_text()); a = json.loads(ansible.read_text()); p = json.loads(planned.read_text())
    assert l['render_supported'] and a['render_supported']
    assert not l['execution_authorized'] and not a['execution_authorized'] and not p['execution_authorized']
    assert l['artifact']['repositories']['isaaclab']['tag'] == a['artifact']['isaaclab_git_checkpoint'] == 'a' * 40
    assert a['artifact']['isaaclab_dir'] == str(checkout)
    assert next(x for x in p['actions'] if x['id'] == 'component.lab')['target'] == str(checkout)
    assert all(not f['evidence_changed'] for f in json.loads(refreshed.read_text())['candidate']['fields'] if f['state'] == 'accepted')
    after = {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode) for p in inputs}
    assert before == after
    assert entries_before == {str(p) for tree in (home, system) for p in tree.rglob('*')}
    summary = {'passed': True, 'cli_calls': len(commands), 'fixture_files_unchanged': len(inputs),
               'workspace_spelling': 'BoredEngineer', 'packages': len(report['packages']),
               'environments': len(report['environments']), 'collection_complete': report['coverage']['complete'],
               'export_complete': True, 'both_renderers_supported': True, 'execution_authorized': False,
               'limitations': ['Entirely synthetic sources and versions; no installed health or source availability proof.',
                              'Host collection gaps remain in raw report; acceptance here is reviewed intent only.',
                              'Dry-run intentionally lacks live target evidence even though fixture paths exist.']}
    (reports / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps({'reports': str(reports), **summary}))


if __name__ == '__main__':
    if sys.argv[1:2] == ['--child']:
        child(Path(sys.argv[2]))
    else:
        base = Path(tempfile.mkdtemp(prefix='isaac-host-demo-'))
        if os.geteuid() == 0:
            os.chown(base, 65534, 65534)
        result = subprocess.run(['/usr/bin/python3', '-B', __file__, '--child', str(base)],
                                capture_output=True, text=True, timeout=180,
                                env={'PATH': '/usr/bin:/bin', 'HOME': str(base), 'LANG': 'C.UTF-8'})
        print('ARTIFACT_ROOT ' + str(base))
        print(result.stdout + result.stderr)
        sys.exit(result.returncode)
