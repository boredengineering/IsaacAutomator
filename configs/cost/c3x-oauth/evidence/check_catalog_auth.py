"""Bounded read-only auth check; never output/persist credentials or error bodies."""
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(source):
    command = ['gcloud', 'auth']
    if source == 'adc':
        command.append('application-default')
    command += ['print-access-token', '--quiet']
    try:
        result = subprocess.run(command, capture_output=True, timeout=45, check=False)
    except subprocess.TimeoutExpired:
        return {'source': source, 'credential_status': 'timeout'}
    if result.returncode:
        return {'source': source, 'credential_status': 'unavailable', 'credential_exit': result.returncode}
    token = result.stdout.decode().strip()
    if not token or any(c.isspace() for c in token):
        return {'source': source, 'credential_status': 'invalid_output'}
    outcome = {'source': source, 'credential_status': 'obtained_in_memory', 'requests': []}
    opener = urllib.request.build_opener(NoRedirect)
    for suffix in ['services?pageSize=1', 'services/6F81-5844-456A/skus?pageSize=1&currencyCode=USD']:
        request = urllib.request.Request('https://cloudbilling.googleapis.com/v1/' + suffix,
            headers={'Authorization': 'Bearer ' + token, 'X-Goog-User-Project': 'cybernetic-renan'})
        item: dict[str, object] = {'path': suffix}
        try:
            with opener.open(request, timeout=30) as response:
                item['http_status'] = response.status
                body = json.load(response)
            key = 'skus' if '/skus?' in suffix else 'services'
            item['records_received'] = len(body.get(key, []))
            item['more_pages'] = bool(body.get('nextPageToken'))
        except urllib.error.HTTPError as exc:
            item['http_status'] = exc.code
            exc.close()
        except Exception:
            item['status'] = 'request_failed_details_suppressed'
        outcome['requests'].append(item)
    return outcome


if __name__ == '__main__':
    results = [probe('adc'), probe('gcloud')]
    receipt = {'project': 'cybernetic-renan', 'api': 'Cloud Billing Catalog v1',
               'scope': 'four bounded GET requests at most; no imports or provisioning',
               'credentials_printed_or_saved': False, 'results': results}
    dest = Path(__file__).with_name('auth-check.json')
    dest.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
