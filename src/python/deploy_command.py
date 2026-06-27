# region copyright
# Copyright 2023-2026 NVIDIA Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# endregion

"""
Base deploy- command
"""

import os
import re
import subprocess
import sys

import click
import randomname
from pwgen import pwgen

from src.python.config import c as config
from src.python.debug import debug_break  # noqa
from src.python.utils import (
    colorize_error,
    colorize_info,
    colorize_prompt,
    get_my_public_ip,
    subnet_from_ip,
)


class DeployCommand(click.core.Command):
    """
    Defines common cli options for "deploy-*" commands.
    """

    def make_context(self, info_name, args, parent=None, **extra):
        """
        Allow deployment name as an unnamed first argument.
        e.g. ./deploy-aws mydeployment is equivalent to ./deploy-aws --deployment-name mydeployment
        """
        args = list(args)
        if (
            args
            and not args[0].startswith("-")
            and "--deployment-name" not in args
            and "--dn" not in args
        ):
            args = ["--deployment-name", args[0]] + args[1:]
        return super().make_context(info_name, args, parent=parent, **extra)

    @staticmethod
    def deployment_name_callback(ctx, param, value):
        # validate
        if not re.match("^[a-z0-9\\-]{1,32}$", value):
            raise click.BadParameter(
                colorize_error(
                    "Only lower case letters, numbers and '-' are allowed."
                    + f" Length should be between 1 and 32 characters ({len(value)} provided)."
                )
            )

        return value

    def ingress_cidrs_callback(ctx, param, value):
        """
        Called after parsing --ingress-cidrs option
        """

        # allow special values
        if value is None or value == "":
            return value

        # split by commas
        value = value.split(",")

        # strip spaces, convert to lower case
        value = [v.strip().lower() for v in value]

        # validate each CIDR block
        for cidr in value:
            if cidr not in [
                "",
                "auto",
                "myip",
                "myip/8",
                "myip/16",
                "myip/24",
                "mynet",
                "nvidia",
                None,
            ] and not re.match(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$", cidr):
                raise click.BadParameter(colorize_error(f"Invalid CIDR block: {cidr}"))

        return ",".join(value)

    # human-readable app names for the --isaacsim/--isaaclab/--isaaclab-arena options
    _APP_NAMES = {
        "isaacsim": "Isaac Sim",
        "isaaclab": "Isaac Lab",
        "isaaclab_arena": "Isaac Lab Arena",
    }

    # release-version comparison ranks: a stable release outranks any of its
    # prereleases; among prereleases dev < alpha < beta < rc.
    _PRE_RANK = {"dev": 0, "alpha": 1, "a": 1, "beta": 2, "b": 2, "rc": 3, "c": 3}

    @staticmethod
    def _version_key(ver):
        """
        Sort key for a release version string ("6.0.1", "3.0.0-beta2", "6.0.0-dev2").
        Returns None when the string is not a recognizable version. Higher key = newer:
        stable sorts above its own prereleases; numeric components dominate.
        """
        m = re.match(r"^(\d+(?:\.\d+)*)(?:[-.]?([A-Za-z]+)\.?(\d+)?)?$", ver)
        if not m:
            return None
        nums = tuple(int(x) for x in m.group(1).split("."))
        nums = nums + (0,) * (4 - len(nums)) if len(nums) < 4 else nums
        pre = m.group(2)
        if pre is None:
            return (nums, 1, 0, 0)  # stable
        return (nums, 0, DeployCommand._PRE_RANK.get(pre.lower(), -1),
                int(m.group(3)) if m.group(3) else 0)

    @staticmethod
    def _resolve_latest_ref(repo, dbg):
        """
        Auto-detect the latest release ref in `repo`: the highest version across its
        tags and release/* branches (prereleases included). On a version tie a
        release/* branch wins over a tag (matches how Lab/Arena are tracked). Returns
        the ref to check out (e.g. "v6.0.1" or "release/0.2.1"), or None if none found.
        """
        cmd = ["git", "ls-remote", "--tags", "--heads", repo]
        dbg("latest: resolving latest release for " + repo)
        dbg("running: " + " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.stderr.strip():
            dbg("stderr: " + result.stderr.strip())

        best = None  # (version_key, is_branch, ref)
        for line in result.stdout.splitlines():
            ref = line.split("\t")[-1].strip()
            if ref.endswith("^{}"):  # peeled tag line, skip
                continue
            if ref.startswith("refs/tags/"):
                name = ref[len("refs/tags/"):]
                ver, is_branch = name.lstrip("v"), False
            elif ref.startswith("refs/heads/release/"):
                name = ref[len("refs/heads/"):]
                ver, is_branch = name[len("release/"):], True
            else:
                continue
            key = DeployCommand._version_key(ver)
            if key is None:
                dbg(f"candidate {name}: version '{ver}' unparseable - skipping")
                continue
            dbg(f"candidate {name}: version {ver}")
            cand = (key, is_branch, name)
            if best is None or cand[:2] > best[:2]:
                best = cand

        if best is None:
            dbg("latest: no release tags or release/* branches found")
            return None
        dbg(f"latest: selected {best[2]}")
        return best[2]

    @staticmethod
    def git_ref_callback(ctx, param, value):
        """
        Validate an Isaac component git ref (--isaacsim / --isaaclab / --isaaclab-arena).

        'no' or empty means "don't install", so skip the check. "latest" auto-detects the
        latest release. Otherwise confirm the ref actually exists in the repo, so a bad
        value fails fast here with a clear message instead of dying deep in the Ansible git
        checkout (NVBugs 6380502: a 4-part product version like v6.0.1.0 was passed, but the
        release tag is the 3-part v6.0.1).
        """
        # --debug (parsed before these options) turns on a trace of the check
        debug = (
            bool(ctx and ctx.params.get("debug"))
            or os.environ.get("DEBUG", "0") == "1"
            or "--debug" in sys.argv
        )

        def dbg(msg):
            if debug:
                click.echo(colorize_info(f"* [git-ref] {param.name}: {msg}"), err=True)

        # skip when not installing / no value
        if value is None or str(value).strip().lower() in ("", "no"):
            dbg(f"value {value!r} means 'do not install' - skipping ref check")
            return value

        repo = {
            "isaacsim": config["isaacsim_git_repo"],
            "isaaclab": config["isaaclab_git_repo"],
            "isaaclab_arena": config["isaaclab_arena_git_repo"],
        }.get(param.name)
        if repo is None:
            dbg("no repo mapped for this option - skipping ref check")
            return value

        # "latest" -> resolve the latest release ref and use that
        if value.strip().lower() == "latest":
            try:
                resolved = DeployCommand._resolve_latest_ref(repo, dbg)
            except (OSError, subprocess.SubprocessError) as e:
                raise click.BadParameter(
                    colorize_error(
                        f"could not auto-detect the latest {param.name} release"
                        f" from {repo} ({e}). Pass an explicit git ref or 'no'."
                    ),
                    ctx=ctx, param=param,
                )
            if not resolved:
                raise click.BadParameter(
                    colorize_error(
                        f"could not auto-detect the latest {param.name} release"
                        f" from {repo}. Pass an explicit git ref or 'no'."
                    ),
                    ctx=ctx, param=param,
                )
            app = DeployCommand._APP_NAMES.get(param.name, param.name)
            click.echo(colorize_info(
                f"* Detected latest release for {app}: {resolved}"
            ))
            return resolved

        # a raw commit sha is a valid ref but cannot be matched by ls-remote; let it pass
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
            dbg(f"'{value}' looks like a commit sha - accepting without ls-remote")
            return value

        cmd = ["git", "ls-remote", "--quiet", repo,
               value, f"refs/tags/{value}", f"refs/heads/{value}"]
        dbg(f"checking ref '{value}' in {repo}")
        dbg("running: " + " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            # network/git problem: warn but do not block the deploy on it
            click.echo(colorize_error(
                f"Warning: could not verify {param.name} ref '{value}' ({e}). Continuing."
            ), err=True)
            return value

        found = result.stdout.strip()
        if debug:
            if result.stderr.strip():
                dbg("stderr: " + result.stderr.strip())
            dbg("matched refs:\n" + found if found else "no matching refs returned")

        if not found:
            raise click.BadParameter(
                colorize_error(
                    f"git ref '{value}' was not found in {repo}."
                    " Pass a valid tag, branch, or commit, or 'no' to skip."
                ),
                ctx=ctx, param=param,
            )

        dbg(f"ref '{value}' OK")
        return value

    def param_index(self, param_name):
        """
        Return index of parameter with given name.
        Useful for inserting new parameters at a specific position.
        """
        return list(
            filter(
                lambda param: param[1].name == param_name,
                enumerate(self.params),
            )
        )[0][0]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # add common options

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--debug/--no-debug",),
                default=os.environ.get("DEBUG", "0") == "1",
                show_default=True,
                help="Enable debug output.",
            ),
        )

        # --prefix
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--prefix",),
                default=config["default_prefix"],
                show_default=True,
                help="Prefix for all cloud resources.",
            ),
        )

        # --from-image/--not-from-image
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--from-image/--not-from-image",),
                default=False,
                show_default=True,
                help="Deploy from pre-built image, from bare OS otherwise.",
            ),
        )

        # --in-china
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--in-china",),
                type=click.Choice(["auto", "yes", "no"]),
                prompt=False,
                default="auto",
                show_default=True,
                help="Is deployment in China? (Local mirrors will be used.)",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--deployment-name", "--dn"),
                prompt=colorize_prompt(
                    '* Deployment Name (lower case letters, numbers and "-")'
                ),
                default=randomname.get_name,
                callback=DeployCommand.deployment_name_callback,
                show_default="<randomly generated>",
                help="Name of the deployment. Used to identify the created cloud resources and files.",
            ),
        )

        # ingress cidr blocks
        help = (
            "CIDR blocks for ingress traffic on the created VM, "
            + f'comma separated. Type "myip" to use your public IP ({get_my_public_ip(verbose="--debug" in sys.argv or os.environ.get("DEBUG", "0") == "1")}). '
            + "Add /8, /16, or /24 to specify the subnet mask."
        )
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--ingress-cidrs",),
                default=config["default_ingress_cidrs"],
                show_default=True,
                type=str,
                help=help + ".",
                prompt=colorize_prompt("* " + help),
                callback=DeployCommand.ingress_cidrs_callback,
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--existing",),
                type=click.Choice(
                    ["ask", "repair", "modify", "replace", "run_ansible"]
                ),
                default="ask",
                show_default=True,
                help="""What to do if deployment already exists:
                \n* 'repair' will try to fix broken deployment without applying new user parameters.
                \n* 'modify' will update user selected parameters and attempt to update existing cloud resources.
                \n* 'replace' will attempt to delete old deployment's cloud resources first.
                \n* 'run_ansible' will re-run Ansible playbooks.""",
            ),
        )

        # --isaacsim
        help = 'Install Isaac Sim? Valid values: "latest" (newest release), "no", or a git ref at https://github.com/isaac-sim/IsaacSim'
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--isaacsim",),
                help=help,
                default=config["default_isaacsim_git_checkpoint"],
                show_default=True,
                prompt=colorize_prompt("* " + help),
                callback=DeployCommand.git_ref_callback,
            ),
        )

        # --isaaclab
        help = 'Install Isaac Lab? Valid values: "latest" (newest release), "no", or a git ref at https://github.com/isaac-sim/IsaacLab'
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--isaaclab",),
                help=help,
                default=config["default_isaaclab_git_checkpoint"],
                show_default=True,
                prompt=colorize_prompt("* " + help),
                callback=DeployCommand.git_ref_callback,
            ),
        )

        # --isaaclab-arena
        help = 'Install Isaac Lab Arena? Valid values: "latest" (newest release), "no", or a git ref at https://github.com/isaac-sim/IsaacLab-Arena'
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--isaaclab-arena",),
                help=help,
                default=config["default_isaaclab_arena_git_checkpoint"],
                show_default=True,
                prompt=colorize_prompt("* " + help),
                callback=DeployCommand.git_ref_callback,
            ),
        )

        # [DEV]
        # private git repo for Isaac Lab
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--isaaclab-private-git",),
                default="",
                help="[DEV] Private git repo for Isaac Sim Lab.",
                hidden=True,
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--vnc-password",),
                default=lambda: pwgen(10),
                help="Password for VNC access to DRIVE Sim/Isaac Sim/etc.",
                show_default="<randomly generated>",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--system-user-password",),
                default=lambda: pwgen(10),
                help="System user password",
                show_default="<randomly generated>",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--ssh-port",),
                default=config["default_ssh_port"],
                help="SSH port for connecting to the deployed machines.",
                show_default=True,
            ),
        )

        # --ssh-user
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--ssh-user",),
                default=config["default_ssh_user"],
                help="OS username on the deployed instances.",
                show_default=True,
            ),
        )

        # --upload/--no-upload
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--upload/--no-upload",),
                prompt=False,
                default=True,
                show_default=True,
                help=f"Upload user data from \"{config['uploads_dir']}\" to cloud "
                + f"instances (to \"{config['default_remote_uploads_dir']}\")?",
            ),
        )
