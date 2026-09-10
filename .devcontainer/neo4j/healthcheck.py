"""Authenticated, loopback-only transactional readiness (Python stdlib)."""
import base64
import http.client
import json
import socket
import sys
import threading

from bootstrap import read_auth

AUTH_PATH = '/automator-secrets/auth'
PORT = 7474
TIMEOUT = 2
MAX_RESPONSE = 65536


def transaction(statement, parameters=None):
    """Trusted-developer helper: return Neo4j's decoded transactional JSON."""
    connection = None
    deadline = None
    try:
        auth = read_auth(AUTH_PATH).replace('/', ':', 1)
        headers = {
            'Authorization': 'Basic ' + base64.b64encode(auth.encode('ascii')).decode('ascii'),
            'Content-Type': 'application/json',
        }
        body = json.dumps({'statements': [{'statement': statement, 'parameters': parameters or {}}]})
        # HTTPConnection is direct: no proxy environment lookup, URL parsing,
        # redirect following or retries that could forward the Basic credential.
        connection = http.client.HTTPConnection('127.0.0.1', PORT, timeout=TIMEOUT)
        connection.connect()
        transport = connection.sock
        # Socket timeouts alone can be extended indefinitely by slow-drip
        # headers/body. A deadline shuts down the transport regardless of reads.
        def expire():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = threading.Timer(TIMEOUT, expire)
        deadline.daemon = True
        deadline.start()
        connection.request('POST', '/db/neo4j/tx/commit', body=body, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError
        result = json.loads(raw)
        if (not isinstance(result, dict) or result.get('errors') != []
                or not isinstance(result.get('results'), list)):
            raise ValueError
        return result
    except Exception:
        # Never expose response bodies, request headers, credentials or chained
        # exceptions (Neo4j errors may contain user-supplied data).
        raise RuntimeError('Neo4j transaction failed') from None
    finally:
        if deadline is not None:
            deadline.cancel()
        if connection is not None:
            connection.close()


def check_health():
    try:
        results = transaction('RETURN 1')['results']
        if len(results) != 1 or results[0]['columns'] != ['1']:
            raise ValueError
        data = results[0]['data']
        if (len(data) != 1 or data[0]['row'] != [1]
                or type(data[0]['row'][0]) is not int):
            raise ValueError
        return True
    except Exception:
        raise RuntimeError('Neo4j health check failed') from None


def main(argv=None):
    try:
        if sys.argv[1:] if argv is None else argv:
            raise ValueError
        check_health()
        return 0
    except Exception:
        print('Neo4j health check failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
