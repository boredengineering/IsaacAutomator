"""Anonymous public HTTPS artifact boundary, standalone and stdlib-only.

Import/validate_public_url are pure (no DNS, trust store or credential reads).
Syntax validation is not a public-reachability assertion. The downloader checks
DNS at each request and pins the checked address through TLS and HTTP.
Extraction/adoption/runtime compatibility are deliberately outside this module.
"""
import re


class ArtifactError(ValueError):
    """Artifact policy, transport or integrity failure (no successful output)."""


def validate_public_url(url):
    """Return the exact URL, or reject; no normalization broadens the schema."""
    host = r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?'
    segment = r'[A-Za-z0-9_-][A-Za-z0-9_.-]*'
    pattern = r'https://(' + host + r'(?:\.' + host + r')+)/' + segment + r'(?:/' + segment + r')*'
    if type(url) is not str or len(url) > 2048:
        raise ArtifactError('Expected a bounded public HTTPS archive URL')
    match = re.fullmatch(pattern, url)
    if not match:
        raise ArtifactError('Expected credential-free HTTPS DNS name and plain archive path')
    name = match.group(1).lower()
    labels = name.split('.')
    reserved = {'localhost', 'local', 'localdomain', 'internal', 'lan', 'home', 'invalid',
                'test', 'onion', 'arpa', 'example', 'alt', 'corp', 'intranet'}
    if (len(name) > 253 or any(len(label) > 63 for label in labels)
            or labels[-1] in reserved or not re.fullmatch(r'[a-z]{2,63}', labels[-1])
            or re.search(r'(?i)(?:token|password|secret|credential|bearer)[=_:-]|gh[pousr]_|sk-', url)):
        raise ArtifactError('Local, reserved, literal or sensitive-looking archive source refused')
    return url


def _public_addresses(hostname):
    import ipaddress
    import socket
    import queue
    import threading

    # libc getaddrinfo is not reliably interrupted by a Python signal. Keep it
    # off the main thread; the bounded queue wait and outer alarm can stop the
    # consumer even if the resolver hangs. No worker ever connects or writes.
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put(socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP))
        except Exception:
            result.put(None)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        answers = result.get(timeout=30)
    except queue.Empty:
        raise ArtifactError('DNS deadline exceeded') from None
    if not answers or len(answers) > 64:
        raise ArtifactError('DNS returned no bounded public address set')
    for family, kind, proto, _, address in answers:
        ip = ipaddress.ip_address(address[0])
        if (family not in (socket.AF_INET, socket.AF_INET6)
                or kind != socket.SOCK_STREAM or proto != socket.IPPROTO_TCP
                or address[1] != 443 or '%' in address[0]
                or not ip.is_global or ip.is_multicast or ip.is_reserved
                or (ip.version == 6 and (family != socket.AF_INET6 or len(address) != 4
                    or address[2:] != (0, 0) or ip not in ipaddress.ip_network('2000::/3')
                    or ip in ipaddress.ip_network('2001::/23')
                    or ip in ipaddress.ip_network('2002::/16')
                    or ip in ipaddress.ip_network('3fff::/20')))
                or (ip.version == 4 and (family != socket.AF_INET
                    or ip in ipaddress.ip_network('192.0.0.0/24')
                    or ip in ipaddress.ip_network('192.88.99.0/24')))):
            raise ArtifactError('DNS contains a nonpublic or unsupported destination')
    return answers


def download(url, sha256, output, *, max_bytes=34359738368, timeout=3600):
    """Linux/main-thread only; hard deadline includes blocking DNS/TLS/reads.

    Output parent must be an existing caller-controlled directory. No output
    overwrite or cached adoption; SHA256 is checked before exclusive linking.
    Call the CLI in a subprocess from threaded applications. Existing SIGALRM
    timers are refused rather than silently interfering with the application.
    """
    import http.client
    import math
    import signal
    import threading

    validate_public_url(url)
    if type(sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise ArtifactError('Expected an explicit lowercase SHA256')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 34359738368:
        raise ArtifactError('Byte limit must be positive and at most 32 GiB')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ArtifactError('Deadline must be positive and at most 3600 seconds')
    if (threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, 'setitimer') or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0)):
        raise ArtifactError('Hard deadline requires main thread and unused POSIX alarm')

    def expired(signum, frame):
        raise ArtifactError('Artifact download deadline exceeded')

    previous = signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        _download(url, sha256, output, max_bytes=max_bytes)
    except (OSError, http.client.HTTPException) as error:
        # Do not leak endpoint, local path or remote response details.
        raise ArtifactError('Artifact transport or exclusive publication failed') from error
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _download(url, sha256, output, *, max_bytes):
    """Internal implementation, always called under the hard deadline."""
    import hashlib
    import http.client
    import os
    from pathlib import Path
    import socket
    import ssl
    import tempfile
    from urllib.parse import urlsplit, urljoin

    validate_public_url(url)
    target = Path(output)
    if os.path.lexists(target):
        raise ArtifactError('Output already exists; archive adoption/overwrite refused')
    if not target.parent.is_dir():
        raise ArtifactError('Output parent must already exist')
    for redirects in range(6):
        validate_public_url(url)
        parts = urlsplit(url)
        hostname = parts.hostname
        assert hostname is not None  # already validated by the pure grammar
        answers = _public_addresses(hostname)
        family, kind, proto, _, sockaddr = answers[0]
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        # Explicit OS-managed CA paths: never SSL_CERT_FILE/DIR or user config.
        context.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')
        raw = socket.socket(family, kind, proto)
        connection = http.client.HTTPSConnection(hostname, timeout=30, context=context)
        response = None
        try:
            raw.settimeout(30)
            raw.connect(sockaddr)  # numeric sockaddr, NOT create_connection(hostname)
            connection.sock = context.wrap_socket(raw, server_hostname=parts.hostname)
            connection.request('GET', parts.path, headers={'Accept-Encoding': 'identity', 'Connection': 'close'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                locations = response.headers.get_all('Location', [])
                if redirects == 5 or len(locations) != 1:
                    raise ArtifactError('Missing/ambiguous redirect or redirect limit exceeded')
                location = locations[0]
                if not location or any(ord(c) < 33 or ord(c) > 126 for c in location):
                    raise ArtifactError('Unsafe redirect refused')
                url = validate_public_url(urljoin(url, location))
                continue
            if response.status != 200:
                raise ArtifactError('Only an anonymous complete HTTP 200 artifact is accepted')
            encodings = response.headers.get_all('Content-Encoding', [])
            lengths = response.headers.get_all('Content-Length', [])
            transfers = response.headers.get_all('Transfer-Encoding', [])
            if (encodings not in ([], ['identity']) or len(lengths) > 1
                    or (lengths and (not re.fullmatch(r'[0-9]{1,12}', lengths[0])
                                     or int(lengths[0]) > max_bytes))
                    or transfers not in ([], ['chunked']) or (transfers and lengths)):
                raise ArtifactError('Unsupported encoding, framing or excessive artifact size')
            expected_size = int(lengths[0]) if lengths else None
            count = 0
            with tempfile.TemporaryDirectory(prefix='.public-artifact-', dir=target.parent) as stage:
                temporary = Path(stage) / 'payload'
                digest = hashlib.sha256()
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                    while True:
                        chunk = response.read1(min(65536, max_bytes - count + 1))
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > max_bytes:
                            raise ArtifactError('Artifact size limit exceeded')
                        stream.write(chunk)
                        digest.update(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if expected_size is not None and count != expected_size:
                    raise ArtifactError('Truncated artifact body')
                if digest.hexdigest() != sha256:
                    raise ArtifactError(f'Archive checksum mismatch: got {digest.hexdigest()}, expected {sha256}')
                os.link(temporary, target)  # atomic publication, EEXIST never replaces
            return
        finally:
            if response is not None:
                response.close()
            connection.close()
            raw.close()


def main(argv=None):
    """Fixed-argument CLI; success means exact requested checksum was published."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-bytes', type=int, default=34359738368)
    parser.add_argument('--timeout', type=float, default=3600)
    args = parser.parse_args(argv)
    try:
        download(args.url, args.sha256, args.output, max_bytes=args.max_bytes, timeout=args.timeout)
    except ArtifactError as error:
        print(f'public-artifact: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
