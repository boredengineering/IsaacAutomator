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

    def test_conda_selected_metadata_does_not_import_or_expose_urls(self):
        env = self.home/'miniconda3/envs/robot'
        self.put(env/'conda-meta/python-3.11.json', json.dumps({'name':'python','version':'3.11.9','url':'https://SECRET@example.org'}))
        self.put(env/'conda-meta/numpy-1.json', json.dumps({'name':'numpy','version':'1.26.4','files':['PRIVATE']}))
        self.put(env/'conda-meta/history', 'NEVER_READ')
        report = self.collect()
        self.assertEqual(report['environments'], [{'path':str(env),'name':'robot','manager':'conda','python':'3.11.9','packages':[{'name':'numpy','version':'1.26.4'},{'name':'python','version':'3.11.9'}]}])
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertNotIn('PRIVATE', json.dumps(report))

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
