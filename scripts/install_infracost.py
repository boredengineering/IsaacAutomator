#!/usr/bin/env python3
"""Optional build-time Infracost installation; never installs on estimate."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
from urllib.request import urlopen

VERSION = "2.16.3"
# Official github.com/infracost/cli v2.16.3 release asset digests.
SHA256 = {
    "amd64": "4daac899c22d82cbd7bdf042e3bfb41f286dfc2e731e864136b4bbadf241a676",
    "arm64": "7e956c16e99acec429266e13201a33c3b604e30626645f947502bbb1e9186c56",
}
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_BINARY_BYTES = 128 * 1024 * 1024


def install(enabled, architecture, destination):
    """Install a pinned regular binary atomically, never extract arbitrary paths."""
    if enabled == "0":
        return
    if enabled != "1" or architecture not in SHA256:
        raise ValueError("Infracost requires enabled=0|1 and supported amd64|arm64")
    url = (f"https://github.com/infracost/cli/releases/download/v{VERSION}/"
           f"infracost-linux-{architecture}.tar.gz")
    binary = download_binary(url, SHA256[architecture], "infracost")
    write_binary(destination, binary)


def download_binary(url, archive_sha256, name):
    """Read exactly one bounded regular executable, never extract tar paths."""
    with urlopen(url, timeout=60) as response:
        archive = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("Infracost archive exceeds size limit")
    if hashlib.sha256(archive).hexdigest() != archive_sha256:
        raise ValueError("Infracost archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = bundle.getmembers()
        if (len(members) != 1 or members[0].name != name
                or not members[0].isfile() or members[0].size > MAX_BINARY_BYTES):
            raise ValueError("Unexpected Infracost archive layout")
        stream = bundle.extractfile(members[0])
        if stream is None:
            raise ValueError("Missing Infracost archive executable")
        with stream:
            binary = stream.read(MAX_BINARY_BYTES + 1)
        if not binary or len(binary) != members[0].size:
            raise ValueError("Invalid Infracost archive executable")
    return binary


def write_binary(destination, binary):
    """Publish one checked executable atomically."""
    destination = Path(destination)
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("Symlink installation destination is forbidden")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".infracost-install-", dir=destination.parent) as root:
        staged = Path(root) / "infracost"
        staged.write_bytes(binary)
        staged.chmod(0o755)
        os.replace(staged, destination)


def read_manifest(path):
    """Validate the checked-in trust manifest before filesystem/network work."""
    try:
        manifest = json.loads(Path(path).read_text())
        if manifest["schema_version"] != 1 or manifest["cli_version"] != VERSION:
            raise ValueError("Unsupported runtime manifest")
        plugins = manifest["plugins"]
        if len(plugins) != 3 or {p["name"] for p in plugins} != {
            "infracost-parser-terraform", "infracost-parser-terraform-plan",
            "infracost-provider-google",
        }:
            raise ValueError("Unexpected plugin manifest bundle")
        for plugin in plugins:
            if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", plugin["version"]):
                raise ValueError("Unpinned plugin manifest version")
            for arch in SHA256:
                pin = plugin["platforms"][f"linux-{arch}"]
                url = (f"https://releases.infracost.io/{plugin['name']}/linux/{arch}/"
                       f"v{plugin['version']}/data.tar.gz")
                if pin["url"] != url or pin["checksum_url"] != url + ".sha256":
                    raise ValueError("Unexpected plugin manifest URL")
                for field in ("archive_sha256", "binary_sha256"):
                    if not re.fullmatch(r"[0-9a-f]{64}", pin[field]):
                        raise ValueError("Invalid plugin manifest checksum")
        return manifest
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid runtime manifest") from exc


def install_plugins(enabled, architecture, destination,
                    manifest_path=Path(__file__).resolve().parents[1] / "configs/cost/runtime.json"):
    """Install the optional pinned GCP parser/provider bundle at build time."""
    if enabled == "0":
        return
    if enabled != "1" or architecture not in SHA256:
        raise ValueError("Infracost requires enabled=0|1 and supported amd64|arm64")

    manifest = read_manifest(manifest_path)
    destination = Path(destination)
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("Symlink installation destination is forbidden")
    if destination.exists():
        raise ValueError("Plugin destination must not exist; use a fresh bundle directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".infracost-plugins-", dir=destination.parent) as root:
        staged = Path(root) / "plugins"
        staged.mkdir()
        for plugin in manifest["plugins"]:
            pin = plugin["platforms"][f"linux-{architecture}"]
            binary = download_binary(pin["url"], pin["archive_sha256"], plugin["name"])
            if hashlib.sha256(binary).hexdigest() != pin["binary_sha256"]:
                raise ValueError("Infracost plugin binary checksum mismatch")
            write_binary(staged / plugin["name"], binary)
        os.replace(staged, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enabled", choices=("0", "1"), required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--destination", default="/usr/local/bin/infracost")
    parser.add_argument("--with-plugins", choices=("0", "1"), default="0",
                        help="Also install the pinned GCP HCL/plan JSON plugin bundle")
    parser.add_argument("--plugin-destination", default="/opt/isaac-infracost/plugins")
    args = parser.parse_args()
    try:
        install(args.enabled, args.architecture, args.destination)
        install_plugins(args.with_plugins if args.enabled == "1" else "0",
                        args.architecture, args.plugin_destination)
    except (OSError, ValueError, tarfile.TarError):
        parser.exit(1, "Pinned Infracost installation failed; no credentials are required.\n")


if __name__ == "__main__":
    main()
