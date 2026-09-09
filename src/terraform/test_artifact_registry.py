#!/usr/bin/env python3
"""Validate and mock-plan GCP Terraform in disposable directories.

Requires Terraform >=1.7 for provider mocks. `init` may download providers;
validate/test never use GCP, credentials, metadata, or deployment state.
Only .tf and .tftest.hcl sources are copied, never overrides/tfvars/state.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent


def copy_sources(source, target):
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob("*.tf"):
        if path.name == "override.tf" or path.name.endswith("_override.tf"):
            continue
        if path.is_symlink():
            raise ValueError(f"Refusing symlink: {path}")
        shutil.copy2(path, target / path.name)
    tests = source / "tests"
    if tests.is_dir():
        (target / "tests").mkdir(exist_ok=True)
        for path in tests.glob("*.tftest.hcl"):
            shutil.copy2(path, target / "tests" / path.name)


def main():
    with tempfile.TemporaryDirectory(prefix="isaac-ar-terraform-") as temporary:
        for name, source in (("workstation", ROOT / "gcp"),
                             ("identity", ROOT / "gcp/ovkit"),
                             ("registry", ROOT / "registry/gcp")):
            target = Path(temporary) / name
            copy_sources(source, target)
            if name == "workstation":
                copy_sources(ROOT / "gcp/ovkit", target / "ovkit")
            print(f"\n=== {name}: isolated validation and mocked plans ===", flush=True)
            for args in (("init", "-backend=false", "-input=false", "-no-color"),
                         ("validate", "-no-color"), ("test", "-no-color")):
                subprocess.run(["terraform", f"-chdir={target}", *args], check=True)


if __name__ == "__main__":
    main()
