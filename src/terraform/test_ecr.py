#!/usr/bin/env python3
"""Isolated AWS ECR validation and mock plans; requires Terraform >=1.7.

Only public provider downloads during init use the network. No AWS auth, CLI,
backend, repository deployment state, tfvars, overrides, or credentials are read.
Every test must explicitly use plan; provider mocks prevent cloud operations.
"""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def copy_sources(source, target):
    if not source.is_dir() or not (source / "main.tf").is_file():
        raise ValueError(f"Missing Terraform sources: {source}")
    if source.is_symlink():
        raise ValueError(f"Refusing symlink: {source}")
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob("*.tf"):
        if path.name == "override.tf" or path.name.endswith("_override.tf"):
            continue
        if path.is_symlink():
            raise ValueError(f"Refusing symlink: {path}")
        shutil.copy2(path, target / path.name)
    tests = source / "tests"
    if tests.is_symlink():
        raise ValueError(f"Refusing symlink: {tests}")
    for path in tests.glob("*.tftest.hcl"):
        if path.is_symlink():
            raise ValueError(f"Refusing symlink: {path}")
        text = path.read_text()
        runs = len(re.findall(r'^run\s+"', text, re.MULTILINE))
        if not runs or len(re.findall(r'command\s*=\s*plan\b', text)) != runs or re.search(r'command\s*=\s*apply\b', text):
            raise ValueError(f"Only explicit plan-only tests are permitted: {path}")
        if 'mock_provider "aws"' not in text:
            raise ValueError(f"AWS must be mocked: {path}")
        (target / "tests").mkdir(exist_ok=True)
        shutil.copy2(path, target / "tests" / path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", choices=("workstation", "identity", "registry"), action="append")
    args = parser.parse_args()
    stacks = {"workstation": ROOT / "aws", "identity": ROOT / "aws/isaac-workstation", "registry": ROOT / "registry/aws"}
    with tempfile.TemporaryDirectory(prefix="isaac-ecr-terraform-") as temporary:
        temporary = Path(temporary)
        home = temporary / "home"
        home.mkdir()
        # Allowlist, not inherited cloud/TF environment: no real credentials or
        # TF_CLI_ARGS, TF_DATA_DIR, TF_WORKSPACE or operator CLI configuration.
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "CHECKPOINT_DISABLE": "1",
               "TF_IN_AUTOMATION": "1", "AWS_EC2_METADATA_DISABLED": "true",
               "AWS_SHARED_CREDENTIALS_FILE": str(home / "no-credentials"),
               "AWS_CONFIG_FILE": str(home / "no-config"),
               "TF_PLUGIN_CACHE_DIR": str(temporary / "provider-cache")}
        (temporary / "provider-cache").mkdir()
        for name in args.stack or stacks:
            target = temporary / name
            copy_sources(stacks[name], target)
            if name == "workstation":
                for child in ("common", "vpc", "isaac-workstation"):
                    copy_sources(ROOT / "aws" / child, target / child)
            print(f"\n=== {name}: isolated validation and mock plans ===", flush=True)
            for command in (("init", "-backend=false", "-input=false", "-no-color"),
                            ("validate", "-no-color"), ("test", "-no-color")):
                subprocess.run(["terraform", f"-chdir={target}", *command], env=env, check=True)


if __name__ == "__main__":
    main()
