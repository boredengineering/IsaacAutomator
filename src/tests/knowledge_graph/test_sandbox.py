"""All irreversible OS sandbox actions run only in disposable subprocesses."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).absolute().parents[3]


def child(code, *args):
    return subprocess.run([sys.executable, '-B', '-c', code, *map(str, args)],
                          cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=20, env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})


class SandboxTests(unittest.TestCase):
    def test_actual_os_denies_reads_writes_network_exec_and_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / 'allowed.txt'
            denied = Path(tmp) / 'denied.txt'
            allowed.write_text('approved')
            denied.write_text('synthetic private')
            result = child('''
import errno, json, os, socket, sys
from src.knowledge_graph.sandbox import restrict_process
allowed, denied = sys.argv[1:]
restrict_process([allowed])
results = {'allowed_read': open(allowed).read() == 'approved'}
def blocked(name, action):
    try:
        action()
    except OSError as error:
        results[name] = error.errno in (errno.EPERM, errno.EACCES, errno.EBADF)
    else:
        results[name] = False
blocked('outside_read', lambda: open(denied).read())
blocked('allowed_write', lambda: open(allowed, 'w'))
blocked('new_write', lambda: open(allowed + '.new', 'w'))
blocked('mkdir', lambda: os.mkdir(allowed + '.dir'))
blocked('unlink', lambda: os.unlink(allowed))
blocked('rename', lambda: os.rename(allowed, allowed + '.moved'))
blocked('chmod', lambda: os.chmod(allowed, 0o777))
blocked('socket_inet', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
blocked('socket_unix', lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
blocked('exec', lambda: os.execve('/bin/true', ['/bin/true'], {}))
blocked('fork', lambda: os.fork())
print(json.dumps(results))
''', allowed, denied)
            self.assertEqual(result.returncode, 0, result.stderr)
            checks = json.loads(result.stdout)
            self.assertTrue(all(checks.values()), checks)
            self.assertEqual(allowed.read_text(), 'approved')
            self.assertFalse(Path(str(allowed) + '.new').exists())

    def test_probe_is_real_and_leaves_caller_unrestricted(self):
        from src.knowledge_graph.sandbox import sandbox_available
        self.assertTrue(sandbox_available(), 'This Linux acceptance host must provide the real sandbox')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'caller-writable'
            p.write_text('still unrestricted')
            self.assertEqual(p.read_text(), 'still unrestricted')

    def test_read_grants_reject_broad_or_linked_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'nested').mkdir()
            (root / 'nested' / 'a.txt').write_text('approved')
            (root / 'alias').symlink_to('nested', target_is_directory=True)
            os.link(root / 'nested' / 'a.txt', root / 'hard.txt')
            for path in ('/', '/root', str(ROOT), '/proc', str(root / 'alias' / 'a.txt'), str(root / 'hard.txt')):
                with self.subTest(path=path):
                    result = child('''
import sys
from src.knowledge_graph.sandbox import restrict_process, SandboxError
try:
    restrict_process([sys.argv[1]])
except SandboxError:
    print('rejected')
else:
    print('accepted')
''', path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), 'rejected')

    def test_preopened_descriptors_are_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'preopened.txt'
            target.write_text('unchanged')
            result = child('''
import errno, json, os, socket, sys
from src.knowledge_graph.sandbox import restrict_process
fd = os.open(sys.argv[1], os.O_RDWR)
a, b = socket.socketpair()
restrict_process([])
checks = []
for action in (lambda: os.write(fd, b'bad'), lambda: os.read(fd, 9), lambda: a.send(b'bad')):
    try:
        action()
    except OSError as error:
        checks.append(error.errno in (errno.EBADF, errno.EPERM, errno.EACCES))
    else:
        checks.append(False)
print(json.dumps(checks))
''', target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [True, True, True])
            self.assertEqual(target.read_text(), 'unchanged')

    def test_multithreaded_or_file_stdio_workers_are_refused(self):
        threaded = child('''
import threading
from src.knowledge_graph.sandbox import restrict_process, SandboxError
stop = threading.Event()
thread = threading.Thread(target=stop.wait, daemon=True)
thread.start()
try:
    restrict_process([])
except SandboxError:
    print('rejected')
else:
    print('accepted')
stop.set()
thread.join()
''')
        self.assertEqual(threaded.returncode, 0, threaded.stderr)
        self.assertEqual(threaded.stdout.strip(), 'rejected')

    def test_file_stdio_worker_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'stdio.txt'
            redirected = child('''
import os, sys
from src.knowledge_graph.sandbox import restrict_process, SandboxError
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT, 0o600)
os.dup2(fd, 1)
try:
    restrict_process([])
except SandboxError:
    os.write(2, b'rejected')
else:
    os.write(2, b'accepted')
''', p)
            self.assertEqual(redirected.returncode, 0)
            self.assertEqual(redirected.stderr.strip(), 'rejected')

    def test_unavailable_is_fail_closed(self):
        from unittest.mock import patch
        from src.knowledge_graph.sandbox import sandbox_available
        with patch('src.knowledge_graph.sandbox.subprocess.run', side_effect=OSError('synthetic failure')):
            self.assertFalse(sandbox_available())
        result = child('''
from unittest.mock import patch
from src.knowledge_graph.sandbox import restrict_process, SandboxError
with patch('src.knowledge_graph.sandbox._libraries', side_effect=OSError('synthetic secret error')):
    try:
        restrict_process([])
    except SandboxError as error:
        print(str(error))
    else:
        print('unsafe continuation')
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'sandbox_unavailable')

    def test_real_graph_parser_and_shacl_run_after_confinement(self):
        result = child('''
import json, sys
from pathlib import Path
import rdflib
import pyshacl
from src.knowledge_graph.sandbox import restrict_process
restrict_process([str(Path(rdflib.__file__).parent), str(Path(pyshacl.__file__).parent),
                  sys.prefix, sys.base_prefix])
data = rdflib.Graph().parse(data='@prefix e: <urn:test:> . e:item a e:Thing .', format='turtle')
shapes = rdflib.Graph().parse(data=''' + repr('@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix e: <urn:test:> . e:Shape a sh:NodeShape; sh:targetClass e:Thing; sh:nodeKind sh:IRI .') + ''', format='turtle')
conforms, report, text = pyshacl.validate(data, shacl_graph=shapes, inference='none',
                                        advanced=False, js=False, do_owl_imports=False)
print(json.dumps({'conforms': conforms, 'triples': len(data)}))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'conforms': True, 'triples': 1})


if __name__ == '__main__':
    unittest.main()
