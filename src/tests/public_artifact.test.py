"""Offline public-source regressions: never use native external networking."""
import importlib
import importlib.util
import sys
import hashlib
import io
import os
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


class WireSocket:
    def __init__(self, wire):
        self.wire = wire
        self.sent = b''
        self.destination = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, destination):
        self.destination = destination

    def sendall(self, data):
        self.sent += data

    def makefile(self, *args):
        return io.BytesIO(self.wire)

    def close(self):
        pass


@contextmanager
def protocol(wires, addresses=None):
    socks = [WireSocket(wire) for wire in wires]
    context = MagicMock()
    context.wrap_socket.side_effect = lambda sock, **kwargs: sock
    addresses = addresses or [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
    with patch('socket.getaddrinfo', return_value=addresses) as dns, \
            patch('socket.socket', side_effect=socks) as create, \
            patch('ssl.SSLContext', return_value=context):
        yield socks, context, dns, create


def reply(body=b'archive', status='200 OK', headers=b''):
    return ('HTTP/1.1 ' + status + '\r\n').encode() + headers + b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))


class PublicArtifactTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('public_artifact'), 'public boundary helper missing')
        return importlib.import_module('public_artifact')

    def test_download_pins_public_sockaddr_and_tls_name_without_ambient_auth(self):
        m = self.module()
        self.assertTrue(hasattr(m, 'download'), 'actual request-boundary downloader missing')
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]) as (socks, tls, dns, create), \
                patch.dict(os.environ, {'HTTPS_PROXY': 'http://localhost', 'NETRC': '/no/read',
                                        'SSL_CERT_FILE': '/no/read', 'SSL_CERT_DIR': '/no/read'}):
            out = Path(tmp) / 'archive.zip'
            m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), out)
            self.assertEqual(out.read_bytes(), b'archive')
            self.assertEqual(socks[0].destination, ('93.184.216.34', 443))
            self.assertEqual(dns.call_count, 1)
            tls.wrap_socket.assert_called_once_with(socks[0], server_hostname='artifacts.example.org')
            self.assertTrue(tls.check_hostname)
            self.assertEqual(tls.verify_mode, __import__('ssl').CERT_REQUIRED)
            tls.load_default_certs.assert_not_called()
            self.assertNotIn(b'Authorization', socks[0].sent)
            self.assertNotIn(b'Cookie:', socks[0].sent)
            self.assertIn(b'Host: artifacts.example.org\r\n', socks[0].sent)
            self.assertIn(b'GET /a.zip HTTP/1.1\r\n', socks[0].sent)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['archive.zip'])

    def test_dns_rejects_every_nonpublic_answer_before_connect(self):
        m = self.module()
        for ip in ('127.0.0.1', '10.0.0.1', '172.16.0.1', '192.168.0.1', '169.254.169.254',
                   '0.0.0.0', '100.64.0.1', '192.0.2.1', '198.18.0.1', '224.0.0.1', '240.0.0.1',
                   '::1', '::', 'fc00::1', 'fe80::1', 'ff02::1', '::ffff:8.8.8.8',
                   '2002:0808:0808::1', '2001::1', '64:ff9b::808:808', '2001:db8::1',
                   '2001:20::1'):
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            addr = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443)
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
                       (family, socket.SOCK_STREAM, 6, '', addr)]
            with self.subTest(ip=ip), tempfile.TemporaryDirectory() as tmp, protocol([reply()], answers) as (_, _, _, create):
                with self.assertRaises(ValueError):
                    m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), Path(tmp) / 'a')
                create.assert_not_called()
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_redirect_revalidates_url_and_dns_including_same_host_rebinding(self):
        m = self.module()
        checksum = hashlib.sha256(b'archive').hexdigest()
        with tempfile.TemporaryDirectory() as tmp, protocol([
                reply(b'', '302 Found', b'Location: https://cdn.example.org/b.zip\r\n'), reply()]) as (socks, tls, dns, _):
            out = Path(tmp) / 'a'
            m.download('https://artifacts.example.org/a.zip', checksum, out)
            self.assertEqual(out.read_bytes(), b'archive')
            self.assertEqual(dns.call_count, 2)
            self.assertEqual(tls.wrap_socket.call_args.kwargs['server_hostname'], 'cdn.example.org')
            self.assertIn(b'Host: cdn.example.org', socks[1].sent)
        for destination in ('https://localhost/a.zip', 'http://artifacts.example.org/a.zip',
                            'https://u:p@artifacts.example.org/a.zip', 'https://artifacts.example.org/a.zip?x=y'):
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as tmp, protocol([
                    reply(b'', '302 Found', ('Location: ' + destination + '\r\n').encode())]) as (_, _, dns, create):
                with self.assertRaises(ValueError):
                    m.download('https://artifacts.example.org/a.zip', checksum, Path(tmp) / 'a')
                self.assertEqual(create.call_count, 1)
                self.assertEqual(list(Path(tmp).iterdir()), [])
        with tempfile.TemporaryDirectory() as tmp, protocol([
                reply(b'', '302 Found', b'Location: /b.zip\r\n')]) as (_, _, dns, create):
            dns.side_effect = [[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))],
                               [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]]
            with self.assertRaises(ValueError):
                m.download('https://artifacts.example.org/a.zip', checksum, Path(tmp) / 'a')
            self.assertEqual(create.call_count, 1)

    def test_http_limits_fail_closed_and_clean_partial_bytes(self):
        m = self.module()
        cases = [
            (reply(status='401 Unauthorized'), 100),
            (reply(status='404 Not Found'), 100),
            (reply(headers=b'Content-Encoding: gzip\r\n'), 100),
            (reply(headers=b'Content-Length: 7\r\n'), 100),
            (reply(), 3),
            (b'HTTP/1.1 200 OK\r\n\r\narchive', 3),
            (b'HTTP/1.1 200 OK\r\nContent-Length: 99\r\n\r\narchive', 100),
            (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n7\r\narchive\r\n0\r\n\r\n', 3),
        ]
        for wire, maximum in cases:
            with self.subTest(wire=wire, maximum=maximum), tempfile.TemporaryDirectory() as tmp, protocol([wire]):
                with self.assertRaises(ValueError):
                    m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(),
                               Path(tmp) / 'a', max_bytes=maximum)
                self.assertEqual(list(Path(tmp).iterdir()), [])
        with tempfile.TemporaryDirectory() as tmp, protocol([reply(b'', '302 Found', b'Location: /b.zip\r\n')] * 6) as (_, _, _, create):
            with self.assertRaises(ValueError):
                m.download('https://artifacts.example.org/a.zip', 'a' * 64, Path(tmp) / 'a')
            self.assertEqual(create.call_count, 6)

    def test_deadline_covers_dns_and_restores_alarm(self):
        import signal
        import time
        m = self.module()
        original = signal.getsignal(signal.SIGALRM)
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]) as (_, _, dns, create):
            dns.side_effect = lambda *a, **kw: time.sleep(0.15) or [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
            with self.assertRaisesRegex(ValueError, 'deadline'):
                m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), Path(tmp) / 'a', timeout=0.02)
            create.assert_not_called()
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
            self.assertEqual(signal.getsignal(signal.SIGALRM), original)

    def test_new_output_is_private_and_existing_objects_never_touched(self):
        import stat
        m = self.module()
        checksum = hashlib.sha256(b'archive').hexdigest()
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]):
            out = Path(tmp) / 'a'
            m.download('https://artifacts.example.org/a.zip', checksum, out)
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        for kind in ('file', 'symlink', 'directory'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, protocol([reply()]) as (_, _, dns, _):
                other = Path(tmp) / 'untouched'
                other.write_bytes(b'keep')
                out = Path(tmp) / 'a'
                if kind == 'file':
                    out.write_bytes(b'original')
                elif kind == 'symlink':
                    out.symlink_to(other)
                else:
                    out.mkdir()
                with self.assertRaises(ValueError):
                    m.download('https://artifacts.example.org/a.zip', checksum, out)
                dns.assert_not_called()
                self.assertEqual(other.read_bytes(), b'keep')
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['a', 'untouched'])

    def test_checksum_mismatch_and_publication_race_preserve_other_files(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                m.download('https://artifacts.example.org/a.zip', 'a' * 64, Path(tmp) / 'a')
            self.assertEqual(list(Path(tmp).iterdir()), [])
        link = os.link
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]):
            out = Path(tmp) / 'a'
            def raced(src, dst, **kwargs):
                out.write_bytes(b'other publisher')
                return link(src, dst, **kwargs)
            with patch('os.link', side_effect=raced), self.assertRaises(ValueError):
                m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), out)
            self.assertEqual(out.read_bytes(), b'other publisher')
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['a'])

    def test_shared_schema_rejects_nonpublic_without_network(self):
        profiles = importlib.import_module('workstation_profile')
        with patch('socket.getaddrinfo', side_effect=AssertionError('pure validation only')):
            for url in ('https://localhost/a.zip', 'https://127.0.0.1/a.zip', 'https://host.local/a.zip'):
                with self.subTest(url=url), self.assertRaises(profiles.ProfileError):
                    profiles._source({'mode': 'standalone', 'url': url}, 'components.sim.source', 'standalone')
            profiles._source({'mode': 'standalone', 'url': 'https://artifacts.example.org/a.zip'}, 'components.sim.source', 'standalone')

    def test_cli_dispatches_actual_checked_download(self):
        m = self.module()
        self.assertTrue(callable(getattr(m, 'main', None)), 'usable CLI missing')
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]):
            out = Path(tmp) / 'a'
            self.assertEqual(m.main(['--url', 'https://artifacts.example.org/a.zip',
                                     '--sha256', hashlib.sha256(b'archive').hexdigest(),
                                     '--output', str(out), '--max-bytes', '100', '--timeout', '2']), 0)
            self.assertEqual(out.read_bytes(), b'archive')

    def test_ansible_uses_copied_helper_fixed_argv_and_exact_pair(self):
        import jinja2
        import runpy
        import yaml
        root = Path(__file__).resolve().parents[2]
        tasks = yaml.safe_load((root / 'src/ansible/roles/isaacsim-source/tasks/standalone.yml').read_text())
        def flatten(items):
            for item in items:
                yield item
                for key in ('block', 'always', 'rescue'):
                    yield from flatten(item.get(key, []))
        all_tasks = list(flatten(tasks))
        self.assertFalse(any('ansible.builtin.get_url' in t for t in all_tasks), 'get_url bypasses network policy')
        downloader = next(t for t in all_tasks if t['name'] == 'Download the exact reviewed standalone archive')
        command = downloader['ansible.builtin.command']
        argv = command['argv']
        helper_copy = next(t['ansible.builtin.copy'] for t in all_tasks
                           if 'ansible.builtin.copy' in t and 'public_artifact.py' in t['ansible.builtin.copy'].get('dest', ''))
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]):
            values = {'playbook_dir': str(root / 'src/ansible'), 'isaacsim_artifact_helper': {'path': tmp},
                      'isaacsim_version': '6.0.1', 'isaacsim_archive_sha256': hashlib.sha256(b'archive').hexdigest(),
                      'isaacsim_archive_url': 'https://artifacts.example.org/sim-6.0.1.zip'}
            render = lambda text: jinja2.Template(text, undefined=jinja2.StrictUndefined).render(**values)
            source, dest = Path(render(helper_copy['src'])), Path(render(helper_copy['dest']))
            self.assertEqual(source.resolve(), root / 'src/python/public_artifact.py')
            dest.write_bytes(source.read_bytes())
            rendered = [render(value) for value in argv]
            self.assertEqual(rendered[:3], ['/usr/bin/python3', '-I', str(dest)])
            self.assertEqual(rendered[rendered.index('--url') + 1], values['isaacsim_archive_url'])
            self.assertEqual(rendered[rendered.index('--sha256') + 1], values['isaacsim_archive_sha256'])
            self.assertIn(values['isaacsim_archive_sha256'], rendered[rendered.index('--output') + 1])
            # Execute the copied CLI with only the output redirected to an owned fixture.
            rendered[rendered.index('--output') + 1] = str(Path(tmp) / 'archive.zip')
            with patch.object(sys, 'argv', [str(dest)] + rendered[3:]), self.assertRaises(SystemExit) as exit:
                runpy.run_path(str(dest), run_name='__main__')
            self.assertEqual(exit.exception.code, 0)
            self.assertEqual((Path(tmp) / 'archive.zip').read_bytes(), b'archive')

    def test_dns_runs_in_daemon_worker_not_uninterruptible_main_thread(self):
        import threading
        m = self.module()
        seen = []
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]) as (_, _, dns, _):
            def resolve(*args, **kwargs):
                seen.append(threading.current_thread())
                return answer
            dns.side_effect = resolve
            m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), Path(tmp) / 'a')
        self.assertIsNot(seen[0], threading.main_thread())
        self.assertTrue(seen[0].daemon)

    def test_version_independent_special_address_and_name_denials(self):
        m = self.module()
        for host in ('x.localdomain', 'x.example', 'x.alt', 'x.corp', 'x.intranet'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                m.validate_public_url('https://' + host + '/a.zip')
        for ip in ('192.0.0.8', '192.0.0.9', '192.88.99.1', '3fff::1'):
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            sockaddr = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443)
            with self.subTest(ip=ip), tempfile.TemporaryDirectory() as tmp, protocol([reply()], [(family, socket.SOCK_STREAM, 6, '', sockaddr)]) as (_, _, _, create):
                with self.assertRaises(ValueError):
                    m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), Path(tmp) / 'a')
                create.assert_not_called()

    def test_shared_validator_loads_trusted_sibling_in_isolated_spec_loader(self):
        import subprocess
        source = Path(__file__).resolve().parents[1] / 'python/workstation_profile.py'
        code = """
import importlib.util, socket, sys
socket.getaddrinfo = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('network'))
spec = importlib.util.spec_from_file_location('isolated_shared_profile', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module._source({'mode':'standalone','url':'https://artifacts.example.org/a.zip'}, 'source', 'standalone')
try:
    module._source({'mode':'standalone','url':'https://localhost/a.zip'}, 'source', 'standalone')
except module.ProfileError:
    pass
else:
    raise AssertionError('nonpublic source accepted')
"""
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(source)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tls_failure_and_midstream_deadline_never_publish(self):
        import ssl
        import time
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]) as (socks, tls, _, _):
            tls.wrap_socket.side_effect = ssl.SSLError('fixture untrusted certificate')
            with self.assertRaises(ValueError):
                m.download('https://artifacts.example.org/a.zip', 'a' * 64, Path(tmp) / 'a')
            self.assertEqual(socks[0].sent, b'')
            self.assertEqual(list(Path(tmp).iterdir()), [])

        class SlowBody(io.BytesIO):
            reads = 0
            def read1(self, size=None):
                self.reads += 1
                if self.reads > 1:
                    time.sleep(0.15)
                return super().read1(min(size, 3) if size is not None and size >= 0 else 3)

        with tempfile.TemporaryDirectory() as tmp, protocol([reply()]) as (socks, _, _, _):
            wire = SlowBody(reply())
            socks[0].makefile = lambda *args: wire
            with self.assertRaisesRegex(ValueError, 'deadline'):
                m.download('https://artifacts.example.org/a.zip', hashlib.sha256(b'archive').hexdigest(), Path(tmp) / 'a', timeout=0.02)
            self.assertGreater(wire.reads, 1)
            self.assertTrue(wire.closed)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_pure_url_boundary_preserves_exact_public_schema(self):
        m = self.module()
        with patch('socket.getaddrinfo', side_effect=AssertionError('offline only')):
            for url in ('https://artifacts.example.org/sim-6.0.1.zip',
                        'https://Downloads.NVIDIA.com/isaac_sim/a-b_1.zip'):
                self.assertEqual(m.validate_public_url(url), url)
            for host in ('localhost', 'LOCALHOST', 'host.local', 'x.localhost', 'x.internal',
                         'x.lan', 'x.home', 'x.invalid', 'x.test', 'x.onion', 'x.arpa',
                         '127.0.0.1', '8.8.8.8', '10.0.0.1', '2130706433', '127.1',
                         '0177.0.0.1', '0x7f000001', '0x7f.0.0.1', '[::1]',
                         '[::ffff:127.0.0.1]', '%31%32%37.0.0.1', 'localhost.',
                         'metadata.google.internal', 'intranet', 'x.123'):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    m.validate_public_url('https://' + host + '/archive.zip')
            for url in ('http://artifacts.example.org/a.zip', 'https://u:p@artifacts.example.org/a.zip',
                        'https://artifacts.example.org/a.zip?token=x', 'https://artifacts.example.org/a.zip#x',
                        'https://artifacts.example.org:443/a.zip', 'https://artifacts.example.org/%61.zip',
                        'https://artifacts.example.org/../a.zip', 'https://artifacts.example.org/a.zip\n'):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    m.validate_public_url(url)


if __name__ == '__main__':
    unittest.main()
