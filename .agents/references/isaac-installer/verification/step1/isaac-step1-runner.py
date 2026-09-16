#!/usr/bin/python3
"""Explicit STEP1 tests; unprivileged, kernel-confined fixtures, no default discovery."""
import ast
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import unittest

ROOT = Path('/workspaces/IsaacAutomator')
SUITES = ('installer_metadata_readers', 'installer_discovery', 'installer_desired_profile',
          'workstation_profile', 'workstation_profile_extensions', 'profile_adapters',
          'installer_action_plan', 'installer_migration_preview', 'installer_profile_read_boundary',
          'installer_discovery_cli', 'installer_profile_workflow', 'installer_export_conflict',
          'installer_output_entry', 'installer_report_writer', 'installer_writer_history',
          'installer_plan_evidence', 'installer_workspace_contract', 'installer_named_safety',
          'installer_target_observation')
EXCLUDED_METHODS = {
    'test_actual_fixture_journal_qualified_hash_metadata_is_preserved',
    'test_actual_fixture_metadata_is_preserved_without_aliases',
}
class Ruleset(ctypes.Structure):
    _fields_ = [('rights', ctypes.c_uint64)]
class Rule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('rights', ctypes.c_uint64), ('fd', ctypes.c_int)]
class Filter(ctypes.Structure):
    _fields_ = [('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
class Program(ctypes.Structure):
    _fields_ = [('length',ctypes.c_ushort),('filters',ctypes.POINTER(Filter))]

def confine(base):
    if os.uname().machine != 'x86_64':
        raise RuntimeError('x86_64 required')
    if os.geteuid() == 0:
        os.setgroups([1001, 1002]); os.setgid(65534); os.setuid(65534)
    if os.geteuid() == 0:
        raise RuntimeError('refusing root test execution')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syscall(444,0,0,1) < 5:
        raise RuntimeError('Landlock ABI5 required')
    allrights = (1 << 16)-1
    attrs = Ruleset(allrights)
    fd = libc.syscall(444,ctypes.byref(attrs),ctypes.sizeof(attrs),0)
    if fd < 0: raise OSError(ctypes.get_errno(), 'create ruleset')
    try:
        grants = [(str(ROOT),12),(str(base),allrights),('/usr',13)]
        for alias in ('/bin','/lib','/lib64'):
            if Path(alias).exists(): grants.append((str(Path(alias).resolve()),13))
        for file in ('/etc/ld.so.cache','/etc/localtime'):
            if Path(file).exists(): grants.append((str(Path(file).resolve()),4))
        grants.append(('/dev/null', (1 << 1)|(1 << 2)|(1 << 14)|(1 << 15)))
        for path,rights in grants:
            pin=os.open(path,os.O_PATH|os.O_CLOEXEC)
            try:
                rule=Rule(rights,pin)
                if libc.syscall(445,fd,1,ctypes.byref(rule),0):
                    raise OSError(ctypes.get_errno(),'add grant')
            finally: os.close(pin)
        if libc.prctl(38,1,0,0,0) or libc.syscall(446,fd,0):
            raise OSError(ctypes.get_errno(),'restrict')
    finally: os.close(fd)
    # Network and namespace/ptrace escape operations forbidden; subprocesses stay
    # under inherited filesystem confinement and unprivileged/no_new_privs.
    deny=0x50000|errno.EPERM
    ins=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(0x06,0,0,0x80000000),(0x20,0,0,0)]
    for num in (41,42,43,49,50,53,101,165,166,246,272,298,304,308,310,311,321,425,426,427):
        ins += [(0x15,0,1,num),(0x06,0,0,deny)]
    ins += [(0x35,0,1,0x40000000),(0x06,0,0,deny),(0x06,0,0,0x7fff0000)]
    buf=(Filter*len(ins))(*(Filter(*x) for x in ins)); prog=Program(len(ins),buf)
    if libc.prctl(22,2,ctypes.byref(prog),0,0): raise OSError(ctypes.get_errno(),'seccomp')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024*1024,32*1024*1024))

def load_suite(name):
    path=ROOT/'src/tests'/(name+'.test.py')
    spec=importlib.util.spec_from_file_location('step1_'+name,path)
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    suite=unittest.TestSuite()
    for _, cls in vars(module).items():
        if isinstance(cls,type) and issubclass(cls,unittest.TestCase) and cls.__module__==module.__name__:
            for method in unittest.defaultTestLoader.getTestCaseNames(cls):
                if method not in EXCLUDED_METHODS: suite.addTest(cls(method))
    return suite

def child(base,name):
    base=Path(base)
    os.environ.update(HOME=str(base),TMPDIR=str(base),TMP=str(base),TEMP=str(base),PYTHONDONTWRITEBYTECODE='1')
    tempfile.tempdir=str(base); os.chdir(base)
    confine(base)
    sys.dont_write_bytecode=True; sys.path.insert(0,str(ROOT))
    if name=='controls':
        import socket
        inside=base/'inside'; inside.write_text('synthetic')
        denied=[]
        # Sibling canaries are explicitly allocated by parent, never real data.
        for mode in ('r','w'):
            try:
                with open(base.parent/'outside-canary',mode): pass
            except PermissionError: denied.append(mode)
        try: socket.socket()
        except PermissionError: denied.append('network')
        assert denied==['r','w','network'],denied
        print(json.dumps({'kernel_controls':denied,'inside_write':inside.read_text()=='synthetic','uid':os.getuid()}))
        return 0
    def audit(event,args):
        if event=='exec':
            filename=getattr(args[0],'co_filename','')
            if Path(filename).name in ('managed_apply.py','fixture_builders.py'):
                raise RuntimeError('Forbidden managed module in STEP1')
    sys.addaudithook(audit)
    result=unittest.TextTestRunner(verbosity=2).run(load_suite(name))
    print('STEP1_RESULT '+json.dumps({'suite':name,'tests':result.testsRun,'skipped':len(result.skipped),
          'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}),flush=True)
    return 0 if result.wasSuccessful() else 1

def parent():
    selected=sys.argv[1:] or list(SUITES)
    if any(x not in SUITES for x in selected): raise ValueError('unknown selection')
    root=Path(tempfile.mkdtemp(prefix='isaac-step1-')); root.chmod(0o755)
    (root/'outside-canary').write_text('SYNTHETIC_OUTSIDE_UNCHANGED')
    (root/'outside-canary').chmod(0o666)
    results=[]
    print('ARTIFACT_ROOT '+str(root),flush=True)
    for name in ('controls',*selected):
        base=root/name; base.mkdir(mode=0o700)
        if os.geteuid()==0: os.chown(base,65534,65534)
        env={'PATH':'/usr/bin:/bin','HOME':str(base),'TMPDIR':str(base),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
        proc=subprocess.run(['/usr/bin/python3','-B',__file__,'--child',str(base),name],cwd=base,env=env,capture_output=True,text=True,timeout=180)
        text=proc.stdout+proc.stderr; (root/(name+'.log')).write_text(text)
        record={'suite':name,'exit_code':proc.returncode,'log':str(root/(name+'.log'))}
        for line in proc.stdout.splitlines():
            if line.startswith('STEP1_RESULT '): record.update(json.loads(line[13:]))
        results.append(record); (root/'results.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(record),flush=True)
        if name=='controls' and proc.returncode: print(text); return 1
    assert (root/'outside-canary').read_text()=='SYNTHETIC_OUTSIDE_UNCHANGED'
    failed=[r['suite'] for r in results if r['exit_code'] or (r['suite']!='controls' and not r.get('passed'))]
    print(json.dumps({'failed':failed,'tests':sum(r.get('tests',0) for r in results),
          'skipped':sum(r.get('skipped',0) for r in results),'artifacts':str(root)}))
    return bool(failed)
if __name__=='__main__':
    sys.exit(child(*sys.argv[2:]) if sys.argv[1:2]==['--child'] else parent())
