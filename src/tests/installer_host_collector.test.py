"""Synthetic-only portable collector tests; run via explicit confined runner."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import time

SCRIPT = Path(__file__).resolve().parents[2] / 'isaac-installer/tools/collect_host_metadata.py'

class HostCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='host-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.system = self.base / 'system'
        self.home.mkdir()
        self.system.mkdir()

    def collector(self):
        self.assertTrue(SCRIPT.is_file(), 'portable collector is not implemented')
        spec = importlib.util.spec_from_file_location('host_collector', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def collect(self, **limits):
        return self.collector().collect(str(self.home), str(self.system), **limits)

    def inventory(self, report):
        spec = importlib.util.spec_from_file_location('gap_inventory', SCRIPT.parent.parent/'lib/core/host_inventory.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_report(report)
        return module

    def test_explicit_workspace_scope_is_exact_and_retained_in_both_clis(self):
        parent = self.home/'Documents/GitHub'
        selected = parent/'BoredEngineer'
        selected.mkdir(parents=True)
        excluded = parent/'boredengineering'
        excluded.mkdir()
        excluded.chmod(0)
        self.addCleanup(excluded.chmod, 0o700)
        module = self.collector()
        original = module._directory
        from contextlib import contextmanager
        @contextmanager
        def guarded(path, *args, **kwargs):
            self.assertFalse(str(path).startswith(str(excluded)))
            self.assertNotEqual(str(path), str(parent), 'explicit scan must not enumerate siblings')
            with original(path, *args, **kwargs) as fd:
                yield fd
        with mock.patch.object(module, '_directory', guarded):
            report = module.collect(str(self.home), str(self.system), workspace_name='BoredEngineer')
        self.assertEqual(report['workspace'], {'parent':str(parent), 'candidates':[str(selected)],
            'selected':str(selected), 'requested_name':'BoredEngineer'})
        self.assertNotIn(str(excluded), json.dumps(report))
        self.inventory(report)
        for mode in ('--plan', '--collect'):
            output = self.base/(mode[2:]+'.json')
            proc = self.cli(mode, '--workspace-name', 'BoredEngineer', '--output', str(output))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout if mode == '--plan' else output.read_text())
            if mode == '--plan':
                self.assertEqual(payload['workspace_names'], ['BoredEngineer'])
            else:
                self.assertEqual(payload['workspace']['requested_name'], 'BoredEngineer')
            proc, repo = self.repository_cli(mode, '--workspace-name', 'BoredEngineer')
            self.assertEqual(proc.returncode, 0, proc.stderr)
            if mode == '--plan':
                self.assertEqual(json.loads(proc.stdout)['workspace_names'], ['BoredEngineer'])
            else:
                self.assertEqual(json.loads((repo/'configs/private/host-inventory.json').read_text())['workspace']['requested_name'], 'BoredEngineer')
        for name in ('../escape', '', 'token=PRIVATE'):
            with self.assertRaises(ValueError): self.collect(workspace_name=name)
        timed = self.collect(workspace_name='BoredEngineer', max_seconds=0.000000001)
        self.assertEqual(timed['workspace']['requested_name'], 'BoredEngineer')
        self.inventory(timed)
        proposals = [p for p in timed['details']['followups'].values() if p['kind'] == 'workspace']
        self.assertEqual(proposals[0]['records'], ['BoredEngineer'])

    def test_case_preserving_workspace_selection(self):
        parent = self.home / 'Documents/GitHub'
        candidate = parent / 'bOrEdEngineer'
        candidate.mkdir(parents=True)
        report = self.collect()
        self.assertEqual(report['workspace']['candidates'], [str(candidate)])
        self.assertEqual(report['workspace']['selected'], str(candidate))
        (parent / 'BoredEngineer').mkdir()
        report = self.collect()
        self.assertEqual(report['workspace']['candidates'], sorted([str(candidate),str(parent/'BoredEngineer')]))
        self.assertIsNone(report['workspace']['selected'])
        self.assertIn('ambiguous-workspace', [i['code'] for i in report['coverage']['issues']])

    def test_ambiguous_workspaces_collect_evidence_without_selecting_intent(self):
        parent = self.home/'Documents/GitHub'
        repos = [parent/name/'IsaacLab' for name in ('BoredEngineer', 'boredengineering')]
        for repo in repos:
            self.put(repo/'.git/config', '[remote "origin"]\n url = https://github.com/NVIDIA/IsaacLab.git\n')
            self.put(repo/'.git/HEAD', 'a'*40+'\n')
        report = self.collect()
        self.assertEqual([r['path'] for r in report['repositories']], list(map(str, repos)))
        self.assertIsNone(report['workspace']['selected'])
        self.assertIn('ambiguous-workspace', [i['code'] for i in report['coverage']['issues']])
        self.assertFalse(report['context']['execution_authorized'])
        spec = importlib.util.spec_from_file_location('ambiguous_inventory', SCRIPT.parent.parent/'lib/core/host_inventory.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_report(report)

    def test_repository_metadata_not_directory_name_identifies_component(self):
        workspace = self.home / 'Documents/GitHub/BoredEngineer'
        repo = workspace / 'IsaacLab-stale-name'
        self.put(repo/'.git/config', '[remote "origin"]\n url = https://secret:token@github.com/NVIDIA/Isaac-GR00T.git?access_token=SECRET\n')
        self.put(repo/'.git/HEAD', 'ref: refs/heads/dev\n')
        self.put(repo/'.git/refs/heads/dev', 'a'*40+'\n')
        self.put(repo/'.env', 'SUPER_SECRET=never-read\n')
        report = self.collect()
        self.assertEqual(report['repositories'], [{'path':str(repo),'component':'gr00t','repository':'https://github.com/NVIDIA/Isaac-GR00T.git','ref':'refs/heads/dev','commit':'a'*40,'dirty':'unknown'}])
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertNotIn('secret:token', json.dumps(report))

    def test_repository_payload_entries_do_not_exhaust_metadata_budget(self):
        repo = self.home/'Documents/GitHub/BoredEngineer/IsaacLab'
        self.put(repo/'.git/config', '[remote "origin"]\n url = https://github.com/NVIDIA/IsaacLab.git\n')
        self.put(repo/'.git/HEAD', 'a'*40+'\n')
        for i in range(200):
            self.put(repo/f'payload-{i}', 'NOT_METADATA')
        report = self.collect(max_entries=100, scope='software')
        self.assertEqual(len(report['repositories']), 1)
        self.assertEqual(report['repositories'][0]['commit'], 'a'*40)
        self.assertNotIn('entry-limit', [i['code'] for i in report['coverage']['issues']])
        self.assertNotIn('NOT_METADATA', json.dumps(report))

    def test_sim_prerelease_and_build_identifiers_are_retained_exactly(self):
        version = '6.0.1-rc.7+release.42383.32955d8d.gl'
        self.put(self.home/'IsaacSim/VERSION', version+'\n')
        report = self.collect(scope='software')
        self.assertEqual(report['isaacsim'][0]['version'], version)
        self.inventory(report)
        for malformed in ('6.0.1-rc..7+build', '6.0.1-rc+', '6.0.1+build+other'):
            self.put(self.home/'IsaacSim/VERSION', malformed)
            self.assertIsNone(self.collect(scope='software')['isaacsim'][0]['version'])

    def test_sim_version_is_metadata_only(self):
        self.put(self.home/'IsaacSim/VERSION', '5.1.0\n')
        self.put(self.home/'IsaacSim/isaac-sim.sh', 'raise RuntimeError("NEVER_EXECUTE")\n')
        report = self.collect()
        self.assertEqual(report['isaacsim'], [{'path':str(self.home/'IsaacSim'),'version':'5.1.0'}])
        self.put(self.home/'IsaacSim/VERSION', 'token=DO_NOT_REPORT\n')
        report = self.collect()
        self.assertEqual(report['isaacsim'][0]['version'], None)
        self.assertNotIn('DO_NOT_REPORT', json.dumps(report))
        self.assertIn('malformed-metadata', [x['code'] for x in report['coverage']['issues']])

    def test_machine_facts_use_only_explicit_fixture_records(self):
        self.put(self.system/'etc/os-release', 'ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu Fixture"\nSECRET=DO_NOT_EMIT\n')
        self.put(self.system/'proc/sys/kernel/osrelease', '6.8.0-fixture\n')
        self.put(self.system/'proc/cpuinfo', 'processor : 0\nmodel name : Fixture CPU\nserial : PRIVATE\n')
        self.put(self.system/'proc/meminfo', 'MemTotal: 1024 kB\n')
        self.put(self.system/'proc/driver/nvidia/version', 'NVRM version: NVIDIA UNIX x86_64 Kernel Module 580.1\n')
        self.put(self.system/'usr/local/cuda/version.json', '{"cuda":{"version":"12.8.0"}}')
        self.put(self.system/'run/systemd/container', 'docker\n')
        report = self.collect()
        expected = {'os':'Ubuntu Fixture','os_id':'ubuntu','os_version':'22.04','kernel':'6.8.0-fixture','cpu':'Fixture CPU','memory':1048576,'driver':'580.1','cuda_toolkit':'12.8.0','gpu':None,'container':'docker'}
        self.assertEqual({k:v['value'] for k,v in report['machine'].items()}, expected)
        for fact in report['machine'].values():
            self.assertEqual(set(fact), {'value','source'})
            self.assertTrue(fact['source'].startswith(str(self.system)+'/'))
        self.assertNotIn('DO_NOT_EMIT', json.dumps(report))
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertIn('gpu-probe-not-enabled', [x['code'] for x in report['coverage']['issues']])

    def test_dpkg_inventory_preserves_multiarch_and_manual_unknowns(self):
        status = ''
        for name, arch, state in [('libx','amd64','install ok installed'),('libx','i386','install ok installed'),('tool','all','install ok installed'),('gone','all','deinstall ok config-files')]:
            status += f'Package: {name}\nStatus: {state}\nArchitecture: {arch}\nVersion: 1:2.3-4\nDescription: PRIVATE\n\n'
        self.put(self.system/'var/lib/dpkg/status', status)
        self.put(self.system/'var/lib/apt/extended_states', 'Package: libx\nArchitecture: amd64\nAuto-Installed: 1\n\nPackage: libx\nArchitecture: i386\nAuto-Installed: 0\n\n')
        report = self.collect()
        self.assertEqual(report['packages'], [
            {'name':'libx','version':'1:2.3-4','architecture':'amd64','manual':False},
            {'name':'libx','version':'1:2.3-4','architecture':'i386','manual':True},
            {'name':'tool','version':'1:2.3-4','architecture':'all','manual':None}])
        self.assertNotIn('PRIVATE', json.dumps(report))
        (self.system/'var/lib/apt/extended_states').unlink()
        self.assertTrue(all(p['manual'] is None for p in self.collect()['packages']))

    def test_conda_large_python_record_has_priority_and_names_stay_manager_scoped(self):
        env = self.home/'miniconda3/envs/robot'
        python = self.put(env/'conda-meta/python-3.12.json', json.dumps({
            'name':'python', 'version':'3.12.1', 'files':['x'*70000]}))
        self.put(env/'conda-meta/_libgcc.json', json.dumps({'name':'_libgcc_mutex', 'version':'0.1', 'files':['x'*90000]}))
        too_big = self.put(env/'conda-meta/oversize.json', json.dumps({'name':'oversize', 'version':'1.0', 'files':['x'*1048576]}))
        report = self.collect(scope='software', max_bytes=80000)
        self.assertEqual(report['environments'][0]['python'], '3.12.1')
        self.assertEqual(report['details']['environments'][str(env)]['python'], str(python))
        self.inventory(report)
        report = self.collect(scope='software')
        self.assertEqual(report['coverage']['limits']['max_bytes'], 8388608)
        self.assertEqual(report['environments'][0]['packages'], [
            {'name':'_libgcc_mutex', 'version':'0.1'}, {'name':'python', 'version':'3.12.1'}])
        self.assertIn({'code':'file-size-limit', 'path':str(too_big)}, report['coverage']['issues'])
        inventory = self.inventory(report)
        with self.assertRaises(ValueError):
            inventory.package({'name':'_libgcc_mutex', 'version':'0.1', 'architecture':'all', 'manual':None}, system=True)
        self.put(self.system/'var/lib/dpkg/status', 'Package: _invalid\nArchitecture: all\nVersion: 1.0\nStatus: install ok installed\n\n')
        self.assertEqual(self.collect()['packages'], [])

    def test_conda_python_json_precedes_all_python_prefixed_records_under_budget(self):
        meta = self.home/'miniconda3/envs/robot/conda-meta'
        for filename, name, version in (
                ('python.json', 'python', '3.12.1'),
                ('python-3.11.9-build_0.json', 'python', '3.11.9'),
                ('python-dateutil-2.9.json', 'python-dateutil', '2.9.0')):
            self.put(meta/filename, json.dumps({'name':name, 'version':version, 'files':['x'*70000]}))
        report = self.collect(scope='software', max_bytes=80000)
        self.assertEqual(report['environments'][0]['python'], '3.12.1')
        self.assertEqual(report['details']['environments'][str(meta.parent)]['python'], str(meta/'python.json'))
        self.assertIn('byte-limit', [i['code'] for i in report['coverage']['issues']])
        self.inventory(report)

    def test_conda_versioned_python_precedes_unrelated_python_packages_under_budget(self):
        meta = self.home/'miniconda3/envs/robot/conda-meta'
        for filename, name, version in (
                ('python-2fa-1.0.json', 'python-2fa', '1.0'),
                ('python-3.12.1-build_0.json', 'python', '3.12.1'),
                ('python-dateutil-2.9.json', 'python-dateutil', '2.9.0')):
            self.put(meta/filename, json.dumps({'name':name, 'version':version, 'files':['x'*70000]}))
        report = self.collect(scope='software', max_bytes=80000)
        self.assertEqual(report['environments'][0]['python'], '3.12.1')
        self.assertEqual(report['environments'][0]['packages'], [{'name':'python', 'version':'3.12.1'}])
        self.assertIn('byte-limit', [i['code'] for i in report['coverage']['issues']])
        self.inventory(report)

    def test_conda_complete_stable_json_cap_is_inclusive(self):
        cap = 1048576
        payload = json.dumps({'name':'python', 'version':'3.12.1'})
        source = self.put(self.home/'miniconda3/envs/robot/conda-meta/python-3.12.json', payload)
        module = self.collector()
        real_read = os.read
        for size in (cap-1, cap, cap+1):
            with self.subTest(size=size):
                source.write_text(payload + ' '*(size-len(payload)))
                consumed = 0
                def bounded(fd, amount):
                    nonlocal consumed
                    self.assertLessEqual(amount, cap-consumed, 'extra read beyond cap')
                    data = real_read(fd, amount)
                    consumed += len(data)
                    return data
                with mock.patch.object(module.os, 'read', side_effect=bounded):
                    report = module.collect(str(self.home), str(self.system), scope='software')
                self.inventory(report)
                self.assertEqual(report['environments'][0]['python'], '3.12.1' if size <= cap else None)
                self.assertEqual(consumed, size if size <= cap else 0)
                self.assertEqual({'code':'file-size-limit', 'path':str(source)} in report['coverage']['issues'], size > cap)

    def test_conda_exact_remaining_global_budget_is_complete_without_extra_read(self):
        cap = 1048576
        prefix = '6.0.1\n'
        self.put(self.home/'IsaacSim/VERSION', prefix)
        payload = json.dumps({'name':'python', 'version':'3.12.1'})
        source = self.put(self.home/'miniconda3/envs/robot/conda-meta/python-3.12.json', payload + ' '*(cap-len(payload)))
        extra = self.put(source.with_name('z-extra.json'), '{"name":"extra","version":"1.0"}')
        module = self.collector()
        real_read = os.read
        for remaining in (cap-1, cap, cap+1):
            with self.subTest(remaining=remaining):
                maximum = len(prefix) + remaining
                consumed = 0
                def bounded(fd, amount):
                    nonlocal consumed
                    self.assertLessEqual(amount, maximum-consumed, 'extra read beyond global budget')
                    data = real_read(fd, amount)
                    consumed += len(data)
                    return data
                with mock.patch.object(module.os, 'read', side_effect=bounded):
                    report = module.collect(str(self.home), str(self.system), scope='software', max_bytes=maximum)
                self.inventory(report)
                self.assertEqual(report['environments'][0]['python'], '3.12.1' if remaining >= cap else None)
                self.assertLessEqual(consumed, maximum)
                if remaining >= cap:
                    self.assertEqual(consumed, len(prefix)+cap)
                    self.assertIn({'code':'byte-limit', 'path':str(extra)}, report['coverage']['issues'])
                else:
                    self.assertIn({'code':'byte-limit', 'path':str(source)}, report['coverage']['issues'])

    def test_zero_size_virtual_record_at_budget_remains_incomplete(self):
        from types import SimpleNamespace
        source = self.put(self.home/'virtual-record', '12345678')
        module = self.collector()
        report = self.collect(scope='software', max_bytes=8)
        reader = module._Reader(report)
        real_fstat, real_stat, real_read = os.fstat, os.stat, os.read
        inode = source.stat().st_ino
        def virtual(st):
            if st.st_ino != inode:
                return st
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns')
            return SimpleNamespace(**{key:getattr(st, key) for key in fields}, st_size=0)
        consumed = 0
        def bounded(fd, amount):
            nonlocal consumed
            self.assertLessEqual(amount, 8-consumed)
            data = real_read(fd, amount)
            consumed += len(data)
            return data
        with mock.patch.object(module.os, 'fstat', side_effect=lambda fd: virtual(real_fstat(fd))), \
                mock.patch.object(module.os, 'stat', side_effect=lambda *a, **kw: virtual(real_stat(*a, **kw))), \
                mock.patch.object(module.os, 'read', side_effect=bounded):
            self.assertIsNone(reader.read(str(source), cap=8))
        self.assertEqual(consumed, 8)
        self.assertEqual(reader.bytes, 8)
        self.assertIn({'code':'byte-limit', 'path':str(source)}, report['coverage']['issues'])

    def test_conda_selected_metadata_does_not_import_or_expose_urls(self):
        env = self.home/'miniconda3/envs/robot'
        self.put(env/'conda-meta/python-3.11.json', json.dumps({'name':'python','version':'3.11.9','url':'https://SECRET@example.org'}))
        self.put(env/'conda-meta/numpy-1.json', json.dumps({'name':'numpy','version':'1.26.4','files':['PRIVATE']}))
        self.put(env/'conda-meta/history', 'NEVER_READ')
        report = self.collect()
        self.assertEqual(report['environments'], [{'path':str(env),'name':'robot','manager':'conda','python':'3.11.9','packages':[{'name':'numpy','version':'1.26.4'},{'name':'python','version':'3.11.9'}]}])
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_venv_metadata_reads_only_complete_bounded_headers(self):
        env = self.home/'Documents/GitHub/BoredEngineer/.venv'
        self.put(env/'pyvenv.cfg', 'version = 3.12.1\n')
        source = env/'lib/python3.12/site-packages/pandas.dist-info/METADATA'
        header = b'Metadata-Version: 2.1\r\nName: pandas\r\nVersion: 2.2.0\r\n\r\n'
        self.put(source, '')
        source.write_bytes(header + b'PRIVATE_BODY'*10000)
        inode = source.stat().st_ino
        module = self.collector()
        real_read = os.read
        consumed = 0
        def guarded(fd, count):
            nonlocal consumed
            data = real_read(fd, count)
            if os.fstat(fd).st_ino == inode:
                consumed += len(data)
                self.assertLessEqual(consumed, len(header), 'METADATA body read')
            return data
        with mock.patch.object(module.os, 'read', side_effect=guarded):
            report = module.collect(str(self.home), str(self.system), scope='software')
        self.assertEqual(report['environments'][0]['packages'], [{'name':'pandas', 'version':'2.2.0'}])
        self.assertEqual(consumed, len(header))
        self.inventory(report)
        for text in ('Name: pandas\nName: other\nVersion: 2.2.0\n\n',
                     'Name: pandas\nname: other\nVersion: 2.2.0\n\n',
                     'Name: pandas\n folded\nVersion: 2.2.0\n\n',
                     'Name: pandas\nVersion: 2.2.0\n\tignored\n\n',
                     'Name: pandas\nVersion: 2.2.0\nX: '+ 'a'*65536 + '\n\n'):
            with self.subTest(header=text[:60]):
                source.write_text(text)
                report = self.collect(scope='software')
                self.assertEqual(report['environments'][0]['packages'], [])
                self.inventory(report)
        # A complete delimiter exactly at the cap is valid, not a partial prefix.
        prefix = 'Name: pandas\nVersion: 2.2.0\nX: '
        source.write_text(prefix + 'a'*(65536-len(prefix)-2) + '\n\nBODY')
        self.assertEqual(self.collect(scope='software')['environments'][0]['packages'][0]['name'], 'pandas')
        report = self.collect(scope='software', max_bytes=40)
        self.assertEqual(report['environments'][0]['packages'], [])
        self.assertIn('byte-limit', [i['code'] for i in report['coverage']['issues']])

    def test_venv_metadata_stable_eof_is_a_complete_header(self):
        env = self.home/'Documents/GitHub/BoredEngineer/.venv'
        self.put(env/'pyvenv.cfg', 'version = 3.12.1\n')
        source = env/'lib/python3.12/site-packages/pandas.dist-info/METADATA'
        for suffix in ('', '\n', '\r\n'):
            self.put(source, 'Name: pandas\nVersion: 2.2.0'+suffix)
            report = self.collect(scope='software')
            self.assertEqual(report['environments'][0]['packages'], [{'name':'pandas', 'version':'2.2.0'}])
            self.inventory(report)
        self.put(source, 'Name: pandas\n')
        self.assertEqual(self.collect(scope='software')['environments'][0]['packages'], [])

    def test_editable_direct_urls_are_opt_in_local_evidence_for_both_managers(self):
        envs = [self.home/'Documents/GitHub/BoredEngineer/.venv', self.home/'miniconda3/envs/robot']
        self.put(envs[0]/'pyvenv.cfg', 'version = 3.12.1\n')
        self.put(envs[1]/'conda-meta/python.json', '{"name":"python","version":"3.12.1"}')
        target = self.base/'unselected-source'
        target.mkdir()
        target.chmod(0)
        self.addCleanup(target.chmod, 0o700)
        sources = []
        for env in envs:
            info = env/'lib/python3.12/site-packages/local.dist-info'
            self.put(info/'METADATA', 'Name: local\nVersion: 1.0\n\n')
            sources.append(self.put(info/'direct_url.json', json.dumps({
                'url':target.as_uri(), 'dir_info':{'editable':True}})))
        module = self.collector()
        real_read = module._Reader.read
        def default_read(reader, path, *args, **kwargs):
            self.assertFalse(path.endswith(('direct_url.json', '.pth')))
            return real_read(reader, path, *args, **kwargs)
        with mock.patch.object(module._Reader, 'read', default_read):
            default = module.collect(str(self.home), str(self.system), scope='software')
        self.assertNotIn('editable', default['details'])
        report = self.collect(scope='software', include_editable=True)
        self.assertEqual(report['details']['editable']['version'], 1)
        for env, source in zip(envs, sources):
            self.assertEqual(report['details']['editable']['environments'][str(env)], {
                'status':'observed', 'records':[{'source':str(source), 'kind':'direct-url',
                    'line':None, 'editable':True, 'local_path':str(target), 'status':'local'}]})
        self.inventory(report)
        for mode in ('--plan', '--collect'):
            output = self.base/('editable-'+mode[2:]+'.json')
            proc = self.cli(mode, '--include-editable', '--output', str(output))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            if mode == '--plan':
                plan = json.loads(proc.stdout)
                self.assertTrue(plan['include_editable'])
                self.assertNotIn('direct_url.json', plan['excluded'])
            else:
                self.inventory(json.loads(output.read_text()))
            proc, repo = self.repository_cli(mode, '--include-editable')
            self.assertEqual(proc.returncode, 0, proc.stderr)
            if mode == '--collect':
                payload = json.loads((repo/'configs/private/host-inventory.json').read_text())
                self.assertEqual(len(payload['details']['editable']['environments']), 2)
        for url in ('https://user:PRIVATE@example.org/src?credential=PRIVATE',
                    'file://user:PRIVATE@localhost/src', 'file:///src?secret=PRIVATE',
                    'file:///src/%2e%2e/private', 'file:///src/%0aprivate'):
            for source in sources:
                source.write_text(json.dumps({'url':url, 'dir_info':{'editable':True}}))
            report = self.collect(scope='software', include_editable=True)
            self.assertNotIn('PRIVATE', json.dumps(report))
            for evidence in report['details']['editable']['environments'].values():
                self.assertIsNone(evidence['records'][0]['local_path'])
                self.assertEqual(evidence['status'], 'unknown')
            self.inventory(report)
        sources[0].write_text('{"url":"file:///src","dir_info":{"editable":"true"}}')
        sources[1].write_text('{"url":"file:///src","url":"file:///other","dir_info":{"editable":true}}')
        report = self.collect(scope='software', include_editable=True)
        self.assertTrue(all(e['records'][0]['status'] == 'unknown'
            for e in report['details']['editable']['environments'].values()))
        self.inventory(report)

    def test_pth_records_are_bounded_unresolved_text_not_code_or_target_reads(self):
        envs = [self.home/'Documents/GitHub/BoredEngineer/.venv', self.home/'miniconda3/envs/robot']
        self.put(envs[0]/'pyvenv.cfg', 'version = 3.12.1\n')
        self.put(envs[1]/'conda-meta/python.json', '{"name":"python","version":"3.12.1"}')
        target = self.base/'never-open'
        target.mkdir()
        sources = []
        for env in envs:
            source = env/'lib/python3.12/site-packages/local.pth'
            sources.append(self.put(source, '# ignored\n'+str(target)+'\nrelative-src\nimport NEVER_EXECUTE; PRIVATE\nhttps://user:PRIVATE@example.org\n'))
        module = self.collector()
        real_directory = module._directory
        from contextlib import contextmanager
        @contextmanager
        def guarded(path, *args, **kwargs):
            self.assertFalse(str(path).startswith(str(target)))
            with real_directory(path, *args, **kwargs) as fd:
                yield fd
        with mock.patch.object(module, '_directory', guarded):
            report = module.collect(str(self.home), str(self.system), include_editable=True, scope='software')
        for env, source in zip(envs, sources):
            evidence = report['details']['editable']['environments'][str(env)]
            self.assertEqual(evidence['status'], 'unknown')
            records = evidence['records']
            self.assertEqual([r['status'] for r in records], ['local', 'local', 'executable', 'nonlocal'])
            self.assertEqual([r['line'] for r in records], [2, 3, 4, 5])
            self.assertTrue(all(r['kind'] == 'pth' and r['editable'] is None and r['source'] == str(source) for r in records))
            self.assertEqual(records[0]['local_path'], str(target))
            self.assertEqual(records[1]['local_path'], 'relative-src')
            self.assertIsNone(records[2]['local_path'])
        self.assertNotIn('NEVER_EXECUTE', json.dumps(report))
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.inventory(report)
        for source in sources:
            source.write_text(''.join('relative'+str(i)+'\n' for i in range(150)))
        report = self.collect(include_editable=True, scope='software')
        self.assertEqual(sum(len(e['records']) for e in report['details']['editable']['environments'].values()), 128)
        self.assertIn('editable-limit', [i['code'] for i in report['coverage']['issues']])
        self.inventory(report)
        for source in sources:
            source.write_text('x'*65537)
        report = self.collect(include_editable=True, scope='software')
        self.assertTrue(all(e['status'] == 'unknown' for e in report['details']['editable']['environments'].values()))
        self.assertIn('file-size-limit', [i['code'] for i in report['coverage']['issues']])
        self.inventory(report)

    def test_editable_unsafe_sources_and_missing_sites_stay_unknown(self):
        env = self.home/'Documents/GitHub/BoredEngineer/.venv'
        self.put(env/'pyvenv.cfg', 'version = 3.12.1\n')
        site = env/'lib/python3.12/site-packages'
        site.mkdir(parents=True)
        outside = self.put(self.base/'outside/direct_url.json', '{"url":"file:///PRIVATE","dir_info":{"editable":true}}')
        (site/'linked.dist-info').symlink_to(outside.parent)
        source = self.put(site/'hard.dist-info/METADATA', 'Name: hard\nVersion: 1.0\n\n').with_name('direct_url.json')
        os.link(outside, source)
        report = self.collect(include_editable=True, scope='software')
        self.assertEqual(report['details']['editable']['environments'][str(env)]['status'], 'unknown')
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.inventory(report)
        source.unlink()
        # The first venv directory enumeration has already recorded this same
        # symlink issue: a repeated issue must not turn the second scan complete.
        report = self.collect(include_editable=True, scope='software')
        self.assertEqual(report['details']['editable']['environments'][str(env)]['status'], 'unknown')
        self.inventory(report)
        meta = self.home/'miniconda3/conda-meta'
        meta.mkdir(parents=True)
        report = self.collect(include_editable=True, scope='software')
        base = str(self.home/'miniconda3')
        self.assertEqual(report['details']['editable']['environments'][base], {'status':'unknown', 'records':[]})
        self.assertIn({'code':'editable-metadata-unavailable', 'path':base}, report['coverage']['issues'])
        self.inventory(report)

    def test_workspace_venv_dist_info_without_python_execution(self):
        env = self.home/'Documents/GitHub/BoredEngineer/.venv'
        self.put(env/'pyvenv.cfg', 'home = /UNTRUSTED\nversion = 3.11.8\n')
        self.put(env/'lib/python3.11/site-packages/torch-2.5.dist-info/METADATA', 'Metadata-Version: 2.1\nName: torch\nVersion: 2.5.0\n\nPRIVATE BODY\n')
        self.put(env/'lib/python3.11/site-packages/malicious.pth', 'import NEVER_EXECUTE\n')
        self.put(env/'lib/python3.11/site-packages/torch-2.5.dist-info/direct_url.json', '{"url":"https://SECRET@example.org"}')
        report = self.collect()
        self.assertEqual(report['environments'], [{'path':str(env),'name':'venv','manager':'venv','python':'3.11.8','packages':[{'name':'torch','version':'2.5.0'}]}])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertIn('unsupported-editable-metadata', [x['code'] for x in report['coverage']['issues']])

    def cli(self, *args, **kwargs):
        return subprocess.run(['/usr/bin/python3','-I','-B',str(SCRIPT),'--home',str(self.home),'--system-root',str(self.system), *args], cwd=self.base, env={'HOME':str(self.home),'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}, capture_output=True, text=True, timeout=10, **kwargs)

    def test_cli_default_plan_has_no_target_reads_or_report_write(self):
        self.home.chmod(0)
        self.system.chmod(0)
        self.addCleanup(self.home.chmod, 0o700)
        self.addCleanup(self.system.chmod, 0o700)
        output = self.base/'planned.json'
        proc = self.cli('--output', str(output))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip(), 'plan is not implemented')
        plan = json.loads(proc.stdout)
        self.assertEqual(plan['kind'], 'host-inventory-plan')
        self.assertFalse(plan['execution_authorized'])
        self.assertEqual(plan['output'], str(output))
        self.assertFalse(output.exists())
        self.assertIn(str(self.home/'IsaacSim'), plan['seeds'])

    def test_software_scope_cli_reserves_budget_for_environments(self):
        env = self.home/'miniconda3/envs/robot'
        self.put(env/'conda-meta/python.json', '{"name":"python","version":"3.12.1"}')
        self.put(self.system/'var/lib/apt/extended_states',
                 ''.join(f'Package: p{i}\nArchitecture: all\nAuto-Installed: 1\n\n' for i in range(200)))
        self.assertEqual(self.collect(max_entries=100)['environments'], [])
        output = self.base/'software.json'
        proc = self.cli('--plan', '--scope', 'software', '--output', str(output))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(proc.stdout)
        self.assertEqual(plan['scope'], 'software')
        self.assertEqual(plan['system_records'], [])
        self.assertNotIn('dpkg/APT records', plan['fields'])
        self.assertFalse(output.exists())
        self.system.chmod(0)
        self.addCleanup(self.system.chmod, 0o700)
        proc = self.cli('--collect', '--scope', 'software', '--max-entries', '100', '--output', str(output))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(report['environments'][0]['python'], '3.12.1')
        self.assertEqual(report['packages'], [])
        self.assertEqual(report['machine'], {})
        system_issues = [i for i in report['coverage']['issues'] if i['path'].startswith(str(self.system))]
        self.assertEqual(system_issues, [{'code':'system-scope-not-collected', 'path':str(self.system)}])
        self.assertFalse(report['coverage']['complete'])

    def test_software_scope_omission_survives_early_timeout(self):
        report = self.collect(scope='software', max_seconds=0.000000001)
        self.assertIn({'code':'system-scope-not-collected', 'path':str(self.system)},
                      report['coverage']['issues'])
        self.assertIn('time-limit', [i['code'] for i in report['coverage']['issues']])
        self.assertEqual(report['machine'], {})

    def test_cli_collect_creates_private_exclusive_report(self):
        self.put(self.home/'IsaacSim/VERSION', '5.1.0\n')
        self.put(self.system/'etc/os-release', 'ID=fixture\n')
        output = self.base/'report.json'
        proc = self.cli('--collect','--output',str(output))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(report['context']['identity'], 'fixture')
        self.assertEqual(report['isaacsim'][0]['version'], '5.1.0')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        before = output.read_bytes()
        proc = self.cli('--collect','--output',str(output))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(output.read_bytes(), before)
        # The real isolated script, not an in-process mock, produced this report.
        print('SYNTHETIC_CLI ' + json.dumps({'argv':['/usr/bin/python3','-I','-B',str(SCRIPT),'--collect','--home',str(self.home),'--system-root',str(self.system),'--output',str(output)],'exit_code':0,'schema_version':report['schema_version'],'identity':report['context']['identity'],'mode':'0600'}))

    def test_cli_refuses_observed_output_trees_and_symlinks(self):
        observed = [self.home/'Documents/GitHub/BoredEngineer', self.home/'IsaacSim', self.home/'miniconda3', self.home/'.conda/envs', self.system]
        for tree in observed:
            tree.mkdir(parents=True, exist_ok=True)
            destination = tree/'new-report.json'
            with self.subTest(tree=tree):
                proc = self.cli('--collect','--output',str(destination))
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertFalse(destination.exists())
        self.put(self.base/'canary', 'UNCHANGED')
        (self.base/'linked.json').symlink_to(self.base/'canary')
        self.assertEqual(self.cli('--collect','--output',str(self.base/'linked.json')).returncode, 2)
        (self.base/'alias').symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.cli('--collect','--output',str(self.base/'alias/escaped.json')).returncode, 2)
        self.assertFalse((self.base/'escaped.json').exists())
        self.assertEqual((self.base/'canary').read_text(), 'UNCHANGED')

    def repository_cli(self, *args):
        import shutil
        root = SCRIPT.parents[2]
        repo = self.home/'Documents/GitHub/BoredEngineer/IsaacAutomator'
        tools = repo/'isaac-installer/tools'
        tools.mkdir(parents=True, exist_ok=True)
        for source, destination in (
                (root/'collect-host-metadata', repo/'collect-host-metadata'),
                (root/'isaac-installer/tools/collect_repository_metadata.py', tools/'collect_repository_metadata.py'),
                (SCRIPT, tools/SCRIPT.name)):
            self.assertTrue(source.is_file(), 'repository collection wrapper is not implemented')
            shutil.copy2(source, destination)
        proc = subprocess.run(['/bin/bash', str(repo/'collect-host-metadata'),
                               '--home', str(self.home), '--system-root', str(self.system), *args],
                              cwd=self.base, capture_output=True, text=True, timeout=15,
                              env={'HOME':str(self.home), 'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8'})
        return proc, repo

    def test_repository_wrapper_plan_then_collect_private_report(self):
        version = self.put(self.home/'IsaacSim/VERSION', '6.0.1\n')
        proc, repo = self.repository_cli('--plan')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        output = repo/'configs/private/host-inventory.json'
        self.assertEqual(json.loads(proc.stdout)['output'], str(output))
        self.assertFalse((repo/'configs').exists(), 'plan must not create output directories')
        proc, _ = self.repository_cli('--collect')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(report['context']['identity'], 'fixture')
        self.assertEqual(report['isaacsim'][0]['version'], '6.0.1')
        self.assertFalse(report['context']['execution_authorized'])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(version.read_text(), '6.0.1\n')
        self.assertIn(str(output), proc.stdout)

    def test_repository_wrapper_targeted_followup_preserves_original(self):
        proc, repo = self.repository_cli('--collect')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        original = repo/'configs/private/host-inventory.json'
        before = original.read_bytes()
        args = ('--scope', 'software', '--report-name', 'host-software-02.json')
        proc, _ = self.repository_cli('--plan', *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        output = original.with_name('host-software-02.json')
        plan = json.loads(proc.stdout)
        self.assertEqual(plan['output'], str(output))
        self.assertEqual(plan['scope'], 'software')
        self.assertEqual(plan['system_records'], [])
        self.assertFalse(output.exists())
        proc, _ = self.repository_cli('--collect', *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(output.read_text())['machine'], {})
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(original.read_bytes(), before)
        followup = output.read_bytes()
        self.assertEqual(self.repository_cli('--collect', *args)[0].returncode, 2)
        self.assertEqual(output.read_bytes(), followup)
        for name in ('../escape.json', '/tmp/escape.json', '.hidden.json', 'not-json', 'token=PRIVATE.json'):
            proc, _ = self.repository_cli('--plan', '--report-name', name)
            self.assertEqual(proc.returncode, 2)
        output.unlink()
        output.symlink_to(original)
        self.assertEqual(self.repository_cli('--collect', *args)[0].returncode, 2)
        self.assertEqual(original.read_bytes(), before)

    def test_repository_wrapper_preserves_existing_report_and_rejects_links(self):
        proc, repo = self.repository_cli('--collect')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        output = repo/'configs/private/host-inventory.json'
        before = output.read_bytes()
        proc, _ = self.repository_cli('--collect')
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(output.read_bytes(), before)
        output.unlink()
        canary = self.put(self.base/'canary', 'UNCHANGED')
        output.symlink_to(canary)
        self.assertEqual(self.repository_cli('--collect')[0].returncode, 2)
        self.assertEqual(canary.read_text(), 'UNCHANGED')
        output.unlink()
        output.parent.rmdir()
        outside = self.base/'outside'
        outside.mkdir()
        output.parent.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.repository_cli('--collect')[0].returncode, 2)
        self.assertEqual(list(outside.iterdir()), [])
        output.parent.unlink()
        (repo/'configs').rmdir()
        (repo/'configs').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.repository_cli('--collect')[0].returncode, 2)
        self.assertEqual(list(outside.iterdir()), [])

    def test_repository_wrapper_default_plan_does_not_read_selected_metadata(self):
        sim = self.home/'IsaacSim'
        sim.mkdir()
        sim.chmod(0)
        self.system.chmod(0)
        self.addCleanup(sim.chmod, 0o700)
        self.addCleanup(self.system.chmod, 0o700)
        proc, repo = self.repository_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(proc.stdout)
        self.assertEqual(plan['kind'], 'host-inventory-plan')
        self.assertFalse(plan['execution_authorized'])
        self.assertFalse((repo/'configs').exists())

    def test_repository_wrapper_rejects_invalid_limits_and_public_private_directory(self):
        proc, repo = self.repository_cli('--collect', '--max-entries', '0')
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((repo/'configs').exists())
        private = repo/'configs/private'
        private.mkdir(parents=True)
        private.chmod(0o755)
        self.assertEqual(self.repository_cli('--collect')[0].returncode, 2)
        self.assertEqual(private.stat().st_mode & 0o777, 0o755)
        self.assertFalse((private/'host-inventory.json').exists())

    def test_incomplete_workspace_enumeration_never_selects_a_candidate(self):
        parent = self.home/'Documents/GitHub'
        (parent/'BoredEngineer').mkdir(parents=True)
        (parent/'boredengineer').mkdir()
        report = self.collect(max_entries=2)
        self.assertIsNone(report['workspace']['selected'])
        self.assertIn('entry-limit', [x['code'] for x in report['coverage']['issues']])
        with self.assertRaises(ValueError):
            self.collect(max_seconds=0)
        report = self.collect(max_seconds=0.000000001)
        self.assertEqual(report['workspace']['candidates'], [])
        self.assertIn('time-limit', [x['code'] for x in report['coverage']['issues']])

    def test_external_git_worktree_is_explicitly_unsupported(self):
        repo = self.home/'Documents/GitHub/BoredEngineer/worktree'
        self.put(repo/'.git', 'gitdir: '+str(self.base/'outside-private')+'\n')
        self.put(self.base/'outside-private/HEAD', 'SECRET_OUTSIDE\n')
        report = self.collect()
        self.assertEqual(report['repositories'], [])
        self.assertIn({'code':'unsupported-worktree','path':str(repo/'.git')}, report['coverage']['issues'])
        self.assertNotIn('SECRET_OUTSIDE', json.dumps(report))
        self.assertNotIn('outside-private', json.dumps(report))

    def test_invalid_limits_fail_before_output_creation(self):
        for args in [('--max-entries','-1'),('--max-bytes','-1'),('--max-depth','-1'),('--max-seconds','nan')]:
            output = self.base/('invalid'+args[0]+'.json')
            with self.subTest(args=args):
                proc = self.cli('--collect','--output',str(output), *args)
                self.assertEqual(proc.returncode, 2)
                self.assertFalse(output.exists())
                self.assertEqual(self.cli('--plan','--output',str(output),*args).returncode, 2)

    def test_deadline_interrupts_a_stalled_selected_read(self):
        self.put(self.home/'IsaacSim/VERSION', '5.1.0\n')
        module = self.collector()
        original = os.read
        def stalled(fd, count):
            time.sleep(0.4)
            return original(fd, count)
        started = time.monotonic()
        with mock.patch.object(module.os, 'read', side_effect=stalled):
            report = module.collect(str(self.home), str(self.system), max_seconds=0.05)
        self.assertLess(time.monotonic()-started, 0.3)
        self.assertIn('time-limit', [x['code'] for x in report['coverage']['issues']])
        self.assertFalse(report['coverage']['complete'])

    def test_os_release_symlink_uses_only_fixed_usr_lib_fallback(self):
        outside = self.put(self.base/'outside-os', 'ID=PRIVATE\n')
        (self.system/'etc').mkdir()
        (self.system/'etc/os-release').symlink_to(outside)
        self.put(self.system/'usr/lib/os-release', 'ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu Fixture"\n')
        report = self.collect()
        self.assertEqual(report['machine']['os_id'], {'value':'ubuntu','source':str(self.system/'usr/lib/os-release')})
        self.assertEqual(report['machine']['os_version']['value'], '22.04')
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_limits_use_positive_import_compatible_caps(self):
        for key, cap in [('max_entries',100000),('max_bytes',67108864),('max_depth',16),('max_seconds',120)]:
            for value in [0,-1,cap+1,True]:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.collect(**{key:value})

    def test_cpu_models_have_import_compatible_bound(self):
        self.put(self.system/'proc/cpuinfo', ''.join(f'model name : Fixture {i}\n' for i in range(33)))
        report = self.collect()
        self.assertEqual(len(report['machine']['cpu']['value']), 32)
        self.assertIn('fact-limit', [x['code'] for x in report['coverage']['issues']])

    def test_unsafe_files_and_ancestors_are_never_read(self):
        canary = self.put(self.base/'private-version', '5.1.0\n')
        sim = self.home/'IsaacSim'
        sim.mkdir()
        target = sim/'VERSION'
        module = self.collector()
        original = os.read
        forbidden = canary.stat().st_ino
        def guarded(fd, count):
            self.assertNotEqual(os.fstat(fd).st_ino, forbidden, 'private target was read')
            return original(fd, count)
        for kind in ('symlink','hardlink','fifo'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    target.symlink_to(canary)
                elif kind == 'hardlink':
                    os.link(canary, target)
                else:
                    os.mkfifo(target)
                with mock.patch.object(module.os, 'read', side_effect=guarded):
                    report = module.collect(str(self.home), str(self.system))
                self.assertIsNone(report['isaacsim'][0]['version'])
                self.assertFalse(report['coverage']['complete'])
                target.unlink()
        sim.rmdir()
        sim.symlink_to(self.base, target_is_directory=True)
        (self.system/'etc').symlink_to(self.base, target_is_directory=True)
        with mock.patch.object(module.os, 'read', side_effect=guarded):
            report = module.collect(str(self.home), str(self.system))
        self.assertEqual(report['isaacsim'], [])
        self.assertIsNone(report['machine']['os_id']['value'])

    def test_unstable_selected_file_is_rejected(self):
        target = self.put(self.home/'IsaacSim/VERSION', '5.1.0\n')
        module = self.collector()
        original = os.read
        changed = False
        def changing(fd, count):
            nonlocal changed
            data = original(fd, count)
            if not changed:
                changed = True
                target.write_text('6.0.0\n')
            return data
        with mock.patch.object(module.os, 'read', side_effect=changing):
            report = module.collect(str(self.home), str(self.system))
        self.assertIsNone(report['isaacsim'][0]['version'])
        self.assertIn('unstable-file', [x['code'] for x in report['coverage']['issues']])

    def test_total_byte_and_depth_budgets_cover_all_inputs(self):
        self.put(self.home/'IsaacSim/VERSION', '5.1.0\n')
        self.put(self.system/'etc/os-release', 'ID=ubuntu\n')
        self.put(self.system/'proc/cpuinfo', 'model name : Fixture\n')
        module = self.collector()
        original = os.read
        count = 0
        def counted(fd, amount):
            nonlocal count
            data = original(fd, amount)
            count += len(data)
            return data
        with mock.patch.object(module.os, 'read', side_effect=counted):
            report = module.collect(str(self.home), str(self.system), max_bytes=8)
        self.assertLessEqual(count, 8)
        self.assertIn('byte-limit', [x['code'] for x in report['coverage']['issues']])
        self.put(self.home/'Documents/GitHub/BoredEngineer/group/deep/.git/HEAD', 'a'*40+'\n')
        report = self.collect(max_depth=1)
        self.assertEqual(report['repositories'], [])
        self.assertIn('depth-limit', [x['code'] for x in report['coverage']['issues']])

    def test_cli_diagnostics_refuse_regular_redirects_before_help(self):
        for fd in ('stdout','stderr'):
            canary = self.put(self.base/(fd+'.txt'), 'UNCHANGED')
            with canary.open('r+') as stream:
                proc = subprocess.run(['/usr/bin/python3','-I','-B',str(SCRIPT),'--home',str(self.home),'--system-root',str(self.system),'--help'], cwd=self.base, env={'HOME':str(self.home)}, timeout=10,
                                      stdout=stream if fd == 'stdout' else subprocess.PIPE,
                                      stderr=stream if fd == 'stderr' else subprocess.PIPE)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(canary.read_text(), 'UNCHANGED')

    def test_known_legacy_shadow_workspace_stays_ambiguous(self):
        parent = self.home/'Documents/GitHub'
        (parent/'BoredEngineer').mkdir(parents=True)
        (parent/'boredengineering').mkdir()
        report = self.collect()
        self.assertEqual(report['workspace']['candidates'], [str(parent/'BoredEngineer'), str(parent/'boredengineering')])
        self.assertIsNone(report['workspace']['selected'])
        self.assertIn('ambiguous-workspace', [x['code'] for x in report['coverage']['issues']])

    def test_plan_discloses_fixed_metadata_scope(self):
        output = self.base/'not-created.json'
        proc = self.cli('--plan','--output',str(output))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(proc.stdout)
        self.assertIn('system_records', plan)
        self.assertIn(str(self.system/'usr/lib/os-release'), plan['system_records'])
        self.assertIn(str(self.system/'var/lib/dpkg/status'), plan['system_records'])
        self.assertIn('boredengineering', plan['workspace_names'])
        self.assertIn('conda-meta/*.json', plan['home_metadata'])
        self.assertIn('Git commands', plan['excluded'])
        self.assertFalse(output.exists())
        print('SYNTHETIC_PLAN ' + json.dumps({'argv':['/usr/bin/python3','-I','-B',str(SCRIPT),'--plan','--home',str(self.home),'--system-root',str(self.system),'--output',str(output)],'exit_code':proc.returncode,'kind':plan['kind'],'report_created':False}))

    def test_git_default_section_does_not_fabricate_origin(self):
        repo = self.home/'Documents/GitHub/BoredEngineer/unknown'
        self.put(repo/'.git/HEAD', 'a'*40+'\n')
        self.put(repo/'.git/config', '[DEFAULT]\nurl = https://github.com/isaac-sim/IsaacLab.git\n[remote "origin"]\nfetch = +refs/heads/*:refs/remotes/origin/*\n')
        report = self.collect()
        self.assertIsNone(report['repositories'][0]['repository'])
        self.assertIsNone(report['repositories'][0]['component'])

    def test_conflicting_environment_packages_remain_unknown(self):
        env = self.home/'miniconda3/envs/robot'
        for version in ('3.11.8','3.12.0'):
            self.put(env/('conda-meta/python-'+version+'.json'), json.dumps({'name':'python','version':version}))
        report = self.collect()
        self.assertEqual(report['environments'][0]['packages'], [])
        self.assertIsNone(report['environments'][0]['python'])
        self.assertIn('conflicting-environment-package', [x['code'] for x in report['coverage']['issues']])

    def test_source_credentials_and_noncanonical_refs_remain_importable_gaps(self):
        repo = self.home/'Documents/GitHub/BoredEngineer/IsaacLab'
        self.put(repo/'.git/HEAD', 'ref: refs/heads/a//b\n')
        self.put(repo/'.git/config', '[remote "origin"]\nurl=https://github.com/example/token-private.git\n')
        self.put(self.system/'var/lib/dpkg/status', 'Package: sk-private\nArchitecture: amd64\nVersion: 1.0\nStatus: install ok installed\n\n')
        report = self.collect()
        self.assertIsNone(report['repositories'][0]['ref'])
        self.assertIsNone(report['repositories'][0]['repository'])
        self.assertEqual(report['packages'], [])
        self.assertNotIn('private', json.dumps(report))
        spec = importlib.util.spec_from_file_location('credential_inventory', SCRIPT.parent.parent/'lib/core/host_inventory.py')
        assert spec is not None and spec.loader is not None
        inventory = importlib.util.module_from_spec(spec); spec.loader.exec_module(inventory)
        inventory.validate_report(report)

    def test_source_scalar_limits_produce_unknowns_not_invalid_reports(self):
        self.put(self.home/'IsaacSim/VERSION', '5.1.0+' + 'a'*64)
        self.put(self.system/'proc/driver/nvidia/version', 'Kernel Module ' + '1'*600 + '.2\n')
        self.put(self.system/'usr/local/cuda/version.json', json.dumps({'cuda': {'version': '1'*600 + '.2'}}))
        env = self.home/'miniconda3/envs/robot'
        self.put(env/'conda-meta/python.json', '{"name":"python","version":"1!2.0"}')
        self.put(env/'conda-meta/token=PRIVATE.json', '{"name":"bad","version":"1.0"}')
        self.put(self.home/'Documents/GitHub/BoredEngineer/bad\nname/.git/HEAD', 'a'*40)
        report = self.collect()
        self.assertIsNone(report['isaacsim'][0]['version'])
        self.assertIsNone(report['machine']['driver']['value'])
        self.assertIsNone(report['machine']['cuda_toolkit']['value'])
        self.assertIsNone(report['environments'][0]['python'])
        self.assertEqual(report['environments'][0]['packages'], [{'name':'python', 'version':'1!2.0'}])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertFalse(report['coverage']['complete'])
        spec = importlib.util.spec_from_file_location('scalar_inventory', SCRIPT.parent.parent/'lib/core/host_inventory.py')
        assert spec is not None and spec.loader is not None
        inventory = importlib.util.module_from_spec(spec); spec.loader.exec_module(inventory)
        inventory.validate_report(report)

    def test_report_size_truncation_terminates_with_empty_editable_and_limit_issues(self):
        import signal
        module = self.collector()
        for empty_environment in (False, True):
            with self.subTest(empty_environment=empty_environment):
                report = self.collect(scope='software', include_editable=True)
                if empty_environment:
                    env = str(self.home/'miniconda3/envs/robot')
                    report['environments'] = [{'path':env, 'name':'robot', 'manager':'conda',
                        'python':None, 'packages':[]}]
                    report['details']['environments'][env] = {'python':None, 'packages':{}}
                    report['details']['editable']['environments'][env] = {'status':'unknown', 'records':[]}
                report['coverage']['issues'] = [{'code':'entry-limit',
                    'path':str(self.home)+'/'+'x'*3500+str(i)} for i in range(350)]
                self.assertGreater(len(json.dumps(report).encode()), 1024*1024)
                reader = module._Reader(report)
                def expired(signum, frame):
                    self.fail('report size truncation did not terminate within 2 seconds')
                previous = signal.signal(signal.SIGALRM, expired)
                try:
                    signal.setitimer(signal.ITIMER_REAL, 2)
                    module._finish(report, reader)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous)
                self.assertLessEqual(len(json.dumps(report).encode()), 1024*1024)
                self.assertIn({'code':'report-size-limit', 'path':str(self.home)}, report['coverage']['issues'])
                self.assertEqual(report['details']['editable']['version'], 1)
                self.assertFalse(report['coverage']['complete'])
                self.inventory(report)

    def test_empty_fixture_contract(self):
        report = self.collect()
        self.assertEqual(set(report), {'schema_version','kind','context','workspace','repositories','isaacsim','machine','packages','environments','coverage','details'})
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['kind'], 'host-inventory')
        self.assertEqual(report['context'], {'home':str(self.home),'system_root':str(self.system),'identity':'fixture','execution_authorized':False})
        self.assertEqual(report['workspace'], {'parent':str(self.home/'Documents/GitHub'),'candidates':[],'selected':None})
        self.assertEqual(report['repositories'], [])
        self.assertFalse(report['coverage']['complete'])
        self.assertIn('missing-workspace', [i['code'] for i in report['coverage']['issues']])
        self.assertEqual(set(report['coverage']), {'complete','issues','limits'})
        json.dumps(report, allow_nan=False)
