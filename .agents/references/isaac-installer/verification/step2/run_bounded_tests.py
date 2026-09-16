#!/usr/bin/python3
"""Explicit host-discovery fixtures using the retained, restricted STEP1 harness.

No default repository discovery, managed probes or real host inventory. Re-audit
selected test bodies before reusing this allowlist after changes.
"""
import importlib.util
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1] / 'step1' / 'isaac-step1-runner.py'
spec = importlib.util.spec_from_file_location('bounded_step1', SOURCE)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
setattr(runner, 'SUITES', ('installer_host_inventory', 'installer_host_collector'))
if __name__ == '__main__':
    sys.exit(runner.parent())
