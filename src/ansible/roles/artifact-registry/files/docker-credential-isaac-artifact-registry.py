#!/usr/bin/python3
"""Docker credential protocol backed only by the VM's attached service account.

No cached tokens, gcloud, service-account keys, environment endpoint overrides,
HTTP proxies, or redirects. The root-owned config contains only a registry host.
"""
import json
from pathlib import Path
import re
import sys
import urllib.request

CONFIG_PATH = Path("/etc/isaac-automator/artifact-registry.json")
METADATA_URL = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("metadata redirect refused")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ["list"]:
            print("{}")
            return 0
        if argv == ["erase"]:
            return 0  # Nothing is persisted, including credentials from docker login.
        if argv != ["get"]:
            raise ValueError("unsupported credential operation")
        server = sys.stdin.readline(4097).strip()
        registry = json.loads(CONFIG_PATH.read_text())["registry"]
        if not isinstance(registry, str) or not re.fullmatch(r"[a-z][a-z0-9-]*-docker\.pkg\.dev", registry) or server != registry:
            raise ValueError("registry not allowed")
        request = urllib.request.Request(METADATA_URL, headers={"Metadata-Flavor": "Google"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=5) as response:
            if response.headers.get("Metadata-Flavor") != "Google":
                raise ValueError("invalid metadata response")
            body = response.read(65537)
            if len(body) > 65536:
                raise ValueError("oversized metadata response")
            token = json.loads(body)
        if (not isinstance(token.get("access_token"), str)
                or not token["access_token"] or any(c.isspace() for c in token["access_token"])
                or token.get("token_type") != "Bearer"
                or type(token.get("expires_in")) is not int or token["expires_in"] <= 0):
            raise ValueError("invalid metadata token")
        print(json.dumps({"ServerURL": server, "Username": "oauth2accesstoken", "Secret": token["access_token"]}))
        return 0
    except Exception:
        # Never include response bodies, exceptions, or tokens in diagnostics.
        print("Artifact Registry credentials unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
