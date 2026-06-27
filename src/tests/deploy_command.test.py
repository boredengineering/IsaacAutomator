#!/usr/bin/env python3

import contextlib
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

import click

from src.python.config import c as config
from src.python.deploy_command import DeployCommand


class Test_DeploymentNameCallback(unittest.TestCase):
    def test_valid_names(self):
        for name in ["a", "abc", "abc-123", "0", "x" * 32]:
            self.assertEqual(DeployCommand.deployment_name_callback(None, None, name), name)

    def test_uppercase_rejected(self):
        with self.assertRaises(click.BadParameter):
            DeployCommand.deployment_name_callback(None, None, "ABC")

    def test_underscore_rejected(self):
        with self.assertRaises(click.BadParameter):
            DeployCommand.deployment_name_callback(None, None, "abc_def")

    def test_empty_rejected(self):
        with self.assertRaises(click.BadParameter):
            DeployCommand.deployment_name_callback(None, None, "")

    def test_too_long_rejected(self):
        with self.assertRaises(click.BadParameter):
            DeployCommand.deployment_name_callback(None, None, "x" * 33)


class Test_IngressCidrsCallback(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(DeployCommand.ingress_cidrs_callback(None, None, None))

    def test_empty_returns_empty(self):
        self.assertEqual(DeployCommand.ingress_cidrs_callback(None, None, ""), "")

    def test_special_values(self):
        for value in ["auto", "myip", "myip/8", "myip/16", "myip/24", "mynet", "nvidia"]:
            self.assertEqual(
                DeployCommand.ingress_cidrs_callback(None, None, value),
                value,
            )

    def test_valid_cidr(self):
        self.assertEqual(
            DeployCommand.ingress_cidrs_callback(None, None, "10.0.0.0/16"),
            "10.0.0.0/16",
        )

    def test_multiple_values(self):
        self.assertEqual(
            DeployCommand.ingress_cidrs_callback(None, None, "myip, 10.0.0.0/8"),
            "myip,10.0.0.0/8",
        )

    def test_invalid_cidr_rejected(self):
        with self.assertRaises(click.BadParameter):
            DeployCommand.ingress_cidrs_callback(None, None, "not-a-cidr")

    def test_case_normalized(self):
        self.assertEqual(
            DeployCommand.ingress_cidrs_callback(None, None, "MyIP"),
            "myip",
        )


class Test_GitRefCallback(unittest.TestCase):
    """Tests for DeployCommand.git_ref_callback (NVBugs 6380502)."""

    @staticmethod
    def _param(name="isaacsim"):
        return SimpleNamespace(name=name)

    def _call(self, value, name="isaacsim"):
        return DeployCommand.git_ref_callback(None, self._param(name), value)

    def test_skip_values_never_touch_network(self):
        # 'no'/empty/None mean "don't install" - returned unchanged, no ls-remote
        for value in [None, "", "no", "No", " no ", "NO"]:
            with mock.patch.object(subprocess, "run") as run:
                self.assertEqual(self._call(value), value)
                run.assert_not_called()

    def test_commit_sha_accepted_without_network(self):
        # a raw sha cannot be matched by ls-remote, so it is accepted as-is
        for sha in ["045ca8b", "045ca8b59622b99a408092124377c66346e8d9c2"]:
            with mock.patch.object(subprocess, "run") as run:
                self.assertEqual(self._call(sha), sha)
                run.assert_not_called()

    def test_existing_ref_passes(self):
        with mock.patch.object(
            subprocess, "run",
            return_value=SimpleNamespace(stdout="abc123\trefs/tags/v6.0.1\n"),
        ):
            self.assertEqual(self._call("v6.0.1"), "v6.0.1")

    def test_missing_ref_rejected(self):
        with mock.patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="")):
            with self.assertRaises(click.BadParameter):
                self._call("v6.0.1.0")

    def test_isaacsim_message_hints_three_part_tag(self):
        with mock.patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="")):
            with self.assertRaises(click.BadParameter) as cm:
                self._call("v6.0.1.0", name="isaacsim")
        self.assertIn("v6.0.1", str(cm.exception))

    def test_network_error_warns_but_does_not_block(self):
        for err in [OSError("git missing"), subprocess.TimeoutExpired("git", 30)]:
            with mock.patch.object(subprocess, "run", side_effect=err):
                self.assertEqual(self._call("v6.0.1"), "v6.0.1")

    def test_repo_selected_per_param_name(self):
        cases = {
            "isaacsim": config["isaacsim_git_repo"],
            "isaaclab": config["isaaclab_git_repo"],
            "isaaclab_arena": config["isaaclab_arena_git_repo"],
        }
        for name, repo in cases.items():
            with mock.patch.object(
                subprocess, "run",
                return_value=SimpleNamespace(stdout="hit\n"),
            ) as run:
                self._call("some-ref", name=name)
                # repo url is the 4th element of the git ls-remote argv
                self.assertIn(repo, run.call_args.args[0])

    def test_unknown_param_name_passes_through(self):
        with mock.patch.object(subprocess, "run") as run:
            self.assertEqual(self._call("whatever", name="other"), "whatever")
            run.assert_not_called()

    def test_debug_traces_the_check_to_stderr(self):
        ctx = SimpleNamespace(params={"debug": True})
        buf = io.StringIO()
        with mock.patch.object(
            subprocess, "run",
            return_value=SimpleNamespace(stdout="abc\trefs/tags/v6.0.1\n", stderr=""),
        ):
            with contextlib.redirect_stderr(buf):
                DeployCommand.git_ref_callback(ctx, self._param("isaacsim"), "v6.0.1")
        out = buf.getvalue()
        self.assertIn("[git-ref]", out)
        self.assertIn("git ls-remote", out)

    def test_no_debug_is_quiet(self):
        ctx = SimpleNamespace(params={"debug": False})
        buf = io.StringIO()
        with mock.patch.object(
            subprocess, "run",
            return_value=SimpleNamespace(stdout="hit\n", stderr=""),
        ):
            with contextlib.redirect_stderr(buf):
                DeployCommand.git_ref_callback(
                    ctx, self._param("isaaclab"), "release/3.0.0-beta2"
                )
        self.assertEqual(buf.getvalue(), "")

    def test_latest_resolves_to_newest(self):
        out = "".join(
            f"x\t{r}\n" for r in ["refs/tags/v6.0.0", "refs/tags/v6.0.1"]
        )
        buf = io.StringIO()
        # _call passes ctx=None -> debug off; the resolved version must still print
        with mock.patch.object(
            subprocess, "run", return_value=SimpleNamespace(stdout=out, stderr="")
        ):
            with contextlib.redirect_stdout(buf):
                self.assertEqual(self._call("latest", name="isaacsim"), "v6.0.1")
        self.assertIn("v6.0.1", buf.getvalue())  # shown even without --debug

    def test_latest_unresolvable_raises(self):
        buf = io.StringIO()
        with mock.patch.object(
            subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="")
        ):
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(click.BadParameter):
                    self._call("latest", name="isaacsim")


class Test_VersionKeyAndResolve(unittest.TestCase):
    """Tests for the auto-detect helpers (NVBugs 6380502 follow-up)."""

    def test_version_key_ordering(self):
        vk = DeployCommand._version_key
        self.assertGreater(vk("6.0.1"), vk("6.0.0"))
        self.assertGreater(vk("6.0.0"), vk("6.0.0-dev2"))
        self.assertGreater(vk("3.0.0-beta2"), vk("3.0.0-beta"))
        self.assertGreater(vk("3.0.0-beta2"), vk("2.3.2"))
        self.assertGreater(vk("3.0.0"), vk("3.0.0-beta2"))
        self.assertIsNone(vk("not-a-version"))

    @staticmethod
    def _resolve(refs):
        out = "".join(
            f"0000000000000000000000000000000000000000\t{r}\n" for r in refs
        )
        with mock.patch.object(
            subprocess, "run", return_value=SimpleNamespace(stdout=out, stderr="")
        ):
            return DeployCommand._resolve_latest_ref("repo", lambda m: None)

    def test_resolve_sim_like_tags_only(self):
        self.assertEqual(
            self._resolve([
                "refs/tags/v5.1.0", "refs/tags/v6.0.0-dev2", "refs/tags/v6.0.0",
                "refs/tags/v6.0.1", "refs/tags/v6.0.1^{}",
            ]),
            "v6.0.1",
        )

    def test_resolve_lab_like_branch_wins_tie(self):
        self.assertEqual(
            self._resolve([
                "refs/tags/v2.3.2", "refs/tags/v3.0.0-beta2",
                "refs/heads/release/2.3.0", "refs/heads/release/3.0.0-beta2",
                "refs/heads/main",
            ]),
            "release/3.0.0-beta2",
        )

    def test_resolve_arena_like_branches_only(self):
        self.assertEqual(
            self._resolve([
                "refs/heads/release/0.1.0", "refs/heads/release/0.2.0",
                "refs/heads/release/0.2.1", "refs/heads/main",
            ]),
            "release/0.2.1",
        )

    def test_resolve_none_when_no_releases(self):
        self.assertIsNone(self._resolve(["refs/heads/main", "refs/heads/develop"]))


if __name__ == "__main__":
    unittest.main()
