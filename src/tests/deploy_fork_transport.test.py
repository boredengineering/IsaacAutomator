#!/usr/bin/env python3
"""Offline repository/ref routing through real Click parsing and inventory rendering."""
import copy
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import click
from click.testing import CliRunner

from src.python.config import c as config
from src.python.deploy_command import DeployCommand
from src.python.deployer import Deployer


COMPONENTS = ("isaacsim", "isaaclab", "isaaclab_arena")
ROOT = Path(__file__).resolve().parents[2]


class TestForkTransport(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = copy.deepcopy(config)
        self.config.update(state_dir=str(self.root / "state"), app_dir=str(ROOT),
                           ansible_dir=str(ROOT / "src/ansible"))
        self.remotes = {}
        self.lookups = []
        self.deployer: Deployer | None = None
        self.inventory = ""
        patcher = mock.patch("src.python.deploy_command.subprocess.run", side_effect=self.git)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, argv, **kwargs):
        # Only the network boundary is replaced; no callback/resolver/render stubs.
        self.assertEqual(argv[:2], ["git", "ls-remote"])
        self.assertNotIn("shell", kwargs)
        repo = next(arg for arg in argv if arg.startswith("https://"))
        self.lookups.append(repo)
        refs = self.remotes.get(repo, {})
        patterns = argv[argv.index(repo) + 1:]
        output = "".join(f"{sha}\t{ref}\n" for ref, sha in refs.items()
                         if not patterns or ref in patterns)
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    def invoke(self, flags=(), refs=None, repo_first=False):
        refs = refs or {}

        def render(**params):
            params.update(cloud="gcp", isaac_workstation_ip="192.0.2.10")
            self.deployer = Deployer(params, self.config)
            self.inventory = self.deployer.create_ansible_inventory(write=False)

        command = DeployCommand("offline", callback=render)
        args = ["--deployment-name", "fork-test", "--ingress-cidrs", "192.0.2.1/32",
                "--in-china", "no", "--no-debug", "--demos", "no"]
        if repo_first:
            args.extend(flags)
        for component in COMPONENTS:
            args.extend(["--" + component.replace("_", "-"), refs.get(component, "no")])
        if not repo_first:
            args.extend(flags)
        return CliRunner().invoke(command, args, env={"DEBUG": "0"})

    def test_fork_only_ref_after_revision_reaches_same_inventory_repo(self):
        for component in COMPONENTS:
            with self.subTest(component=component):
                self.lookups.clear()
                fork = f"https://github.com/example/{component}.git"
                self.remotes[fork] = {"refs/heads/fork-only": "a" * 40}
                result = self.invoke(["--" + component.replace("_", "-") + "-repo", fork],
                                     {component: "fork-only"})
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(self.lookups, [fork])
                self.assertIn(f'{component}_git_repo="{fork}"', self.inventory)
                self.assertIn(f'{component}_git_checkpoint="fork-only"', self.inventory)
                self.assertFalse((self.root / "state/fork-test/.inventory").exists())

    def test_unsafe_repository_rejected_before_git_even_when_disabled(self):
        unsafe = [
            "", "--upload-pack=bad", "/tmp/local.git", "file:///tmp/local.git",
            "ext::sh -c bad", "git://example.com/team/repo.git",
            "ssh://git@example.com/team/repo.git", "git@example.com:team/repo.git",
            "http://example.com/team/repo.git", "https://token@example.com/team/repo.git",
            "https://user:secret@example.com/team/repo.git",
            "https://example.com/team/repo.git?token=secret",
            "https://example.com/team/repo.git#fragment",
            "https://example.com/team/repo.git --upload-pack=bad",
            "https://example.com/team/repo.git\nansible_connection=local",
            "https://example.com/team/repo.git\r", "https://example.com/team/repo.git\t",
            "https://example.com/team/repo.git\x00", "https://example.com/team/repo.git\x1b",
            "https://example.com/team/repo.git\x7f", "https://example.com/{{lookup}}/repo.git",
            "https://example.com/{%print%}/repo.git", "https://example.com/$(bad)/repo.git",
            "https://example.com/`bad`/repo.git", 'https://example.com/team/"bad".git',
            "https://example.com/team/repo.git;bad", "https://example.com/team/\\bad.git",
            "https://example.com/team/%0a.git", "https://example.com/team/../repo.git",
            "https://example.com", "https://example.com//repo.git",
        ]
        for value in unsafe:
            for ref in ("no", "fork-only"):
                with self.subTest(value=repr(value), ref=ref):
                    self.lookups.clear()
                    result = self.invoke(["--isaaclab-repo", value], {"isaaclab": ref})
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertIn("credential-free HTTPS repository", result.output)
                    self.assertEqual(self.lookups, [])
                    if value:
                        self.assertNotIn(value, result.output)

    def test_inventory_revalidates_restored_repository_before_writing(self):
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        assert self.deployer is not None
        for component in COMPONENTS:
            key = f"{component}_repo"
            original = self.deployer.params[key]
            self.deployer.params[key] = "https://example.com/{{unsafe}}/repo.git"
            with self.subTest(component=component), self.assertRaises(click.BadParameter):
                self.deployer.create_ansible_inventory(write=True)
            self.deployer.params[key] = original
        self.assertFalse((self.root / "state/fork-test/.inventory").exists())
        self.assertEqual(self.lookups, [])



    def test_demo_autoenabled_components_resolve_latest_in_selected_repos(self):
        flags = ["--demos", "arena-benchmark"]
        forks = []
        for component in COMPONENTS:
            fork = f"https://example.org/team/{component}.git"
            forks.append(fork)
            self.remotes[fork] = {"refs/tags/v1.2.3": "a" * 40}
            flags.extend(["--" + component.replace("_", "-") + "-repo", fork])
        result = self.invoke(flags)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.lookups, forks)
        for component, fork in zip(COMPONENTS, forks):
            self.assertIn(f'{component}_git_repo="{fork}"', self.inventory)
            self.assertIn(f'{component}_git_checkpoint="v1.2.3"', self.inventory)

    def test_image_commands_do_not_advertise_unsupported_fork_transport(self):
        for cloud in ("aws", "azure", "gcp"):
            with self.subTest(cloud=cloud):
                command = runpy.run_path(str(ROOT / f"image-{cloud}"),
                                         run_name="offline_fork_test")["main"]
                result = CliRunner().invoke(command, ["--help"])
                self.assertEqual(result.exit_code, 0, result.output)
                for component in COMPONENTS:
                    self.assertNotIn("--" + component.replace("_", "-") + "-repo", result.output)
                result = CliRunner().invoke(command, ["--isaaclab-repo", "https://example.org/repo"])
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("No such option", result.output)
        self.assertEqual(self.lookups, [])

    def test_same_ref_different_contents_is_checked_in_selected_repo(self):
        for component in COMPONENTS:
            upstream = config[f"{component}_git_repo"]
            fork = f"https://git.example.org/Team/{component}.git"
            self.remotes[upstream] = {"refs/heads/shared": "a" * 40}
            self.remotes[fork] = {"refs/heads/shared": "b" * 40}
            for repo_first in (True, False):
                for repo in (upstream, fork):
                    with self.subTest(component=component, repo=repo, repo_first=repo_first):
                        self.lookups.clear()
                        result = self.invoke(
                            ["--" + component.replace("_", "-") + "-repo", repo],
                            {component: "shared"}, repo_first=repo_first)
                        self.assertEqual(result.exit_code, 0, result.output)
                        self.assertEqual(self.lookups, [repo])
                        self.assertIn(f'{component}_git_repo="{repo}"', self.inventory)
                        self.assertIn(f'{component}_git_checkpoint="shared"', self.inventory)

    def test_repeated_repo_flag_uses_last_value_for_validation_and_inventory(self):
        first = "https://example.org/first/IsaacLab.git"
        last = "https://example.org/last/IsaacLab.git"
        self.remotes[last] = {"refs/heads/fork-only": "a" * 40}
        result = self.invoke(["--isaaclab-repo", first, "--isaaclab-repo", last],
                             {"isaaclab": "fork-only"})
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.lookups, [last])
        self.assertIn(f'isaaclab_git_repo="{last}"', self.inventory)
        self.assertNotIn(first, self.inventory)

    def test_missing_fork_ref_does_not_fall_back_to_matching_upstream(self):
        upstream = config["isaaclab_git_repo"]
        fork = "https://example.org/team/IsaacLab.git"
        self.remotes[upstream] = {"refs/heads/upstream-only": "a" * 40}
        result = self.invoke(["--isaaclab-repo", fork], {"isaaclab": "upstream-only"})
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertEqual(self.lookups, [fork])
        self.assertIn(f"was not found in {fork}", result.output)
        self.assertIsNone(self.deployer)

    def test_latest_uses_selected_repo_and_transports_resolved_revision(self):
        for component in COMPONENTS:
            with self.subTest(component=component):
                self.lookups.clear()
                upstream = config[f"{component}_git_repo"]
                fork = f"https://example.org/team/{component}.git"
                self.remotes[upstream] = {"refs/tags/v99.0.0": "a" * 40}
                self.remotes[fork] = {"refs/tags/v1.2.0": "b" * 40,
                                      "refs/heads/release/1.3.0": "c" * 40}
                result = self.invoke(["--" + component.replace("_", "-") + "-repo", fork],
                                     {component: "latest"})
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(self.lookups, [fork])
                self.assertIn(f'{component}_git_repo="{fork}"', self.inventory)
                self.assertIn(f'{component}_git_checkpoint="release/1.3.0"', self.inventory)

    def test_defaults_disabled_components_and_legacy_inventory(self):
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        assert self.deployer is not None
        self.assertEqual(self.lookups, [])
        for component in COMPONENTS:
            self.assertIn(f'{component}_git_repo="{config[component + "_git_repo"]}"',
                          self.inventory)
            self.assertIn(f'{component}_git_checkpoint="no"', self.inventory)
            del self.deployer.params[f"{component}_repo"]
        self.assertEqual(self.deployer.create_ansible_inventory(False), self.inventory)
        self.deployer.params.update(isaacsim="", isaaclab="no", isaaclab_arena="")
        legacy = self.deployer.create_ansible_inventory(False)
        self.assertIn('isaacsim_git_checkpoint=""', legacy)
        self.assertEqual(self.lookups, [])

    def test_repo_flags_recreated_without_leaking_to_tfvars(self):
        fork = "https://example.org/team/IsaacLab.git"
        result = self.invoke(["--isaaclab-repo", fork])
        self.assertEqual(result.exit_code, 0, result.output)
        assert self.deployer is not None
        self.assertIn(f"--isaaclab-repo {fork}", self.deployer.recreate_command_line(" "))
        self.deployer.create_tfvars()
        tfvars = (self.root / "state/fork-test/.tfvars").read_text()
        for component in COMPONENTS:
            self.assertNotIn(f"{component}_repo", tfvars)
            self.assertNotIn(f"{component}_git_repo", tfvars)
        self.assertNotIn(fork, tfvars)
        self.assertEqual(config["isaaclab_git_repo"], "https://github.com/isaac-sim/IsaacLab.git")

    def test_raw_sha_preserves_selected_repo_but_does_not_claim_reachability(self):
        fork = "https://example.org/team/IsaacLab.git"
        sha = "f" * 40
        result = self.invoke(["--isaaclab-repo", fork], {"isaaclab": sha})
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.lookups, [])
        self.assertIn(f'isaaclab_git_repo="{fork}"', self.inventory)
        self.assertIn(f'isaaclab_git_checkpoint="{sha}"', self.inventory)


if __name__ == "__main__":
    unittest.main()
