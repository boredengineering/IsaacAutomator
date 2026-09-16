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
import tempfile

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


class _BackendChoice(click.Choice):
    def convert(self, value, param, ctx):
        try:
            return super().convert(value, param, ctx)
        except click.BadParameter:
            raise click.BadParameter(
                "Unsupported backend; choose local, gcs, s3 or azurerm.",
                ctx=ctx, param=param,
            ) from None


class DeployCommand(click.core.Command):
    """
    Defines common cli options for "deploy-*" commands.
    """

    def get_params(self, ctx):
        params = super().get_params(ctx)
        # Image commands inherit these options, then replace deployment_name
        # with image_name. Their Packer adapters do not transport repository URLs.
        names = {param.name for param in params}
        if "image_name" in names and "deployment_name" not in names:
            repo_names = {f"{component}_repo" for component in self._APP_NAMES} | {'software_profile'}
            return [param for param in params if param.name not in repo_names]
        return params

    def parse_args(self, ctx, args):
        # Inspect Click's own token parse without invoking any callbacks. Profile
        # source pairs must populate defaults BEFORE eager repository validation.
        if not ctx.resilient_parsing and '--help' not in args:
            opts, _, _ = self.make_parser(ctx).parse_args(args=list(args))
            source = opts.get('software_profile')
            if source is not None:
                from src.python.workstation_profile import resolve_profile
                from src.python.profile_adapters import render_profile
                conflicts = (set(self._APP_NAMES) | {n + '_repo' for n in self._APP_NAMES}
                             | {'isaaclab_private_git'})
                if conflicts.intersection(opts):
                    raise click.UsageError('Software profile source selection cannot combine with component/ref/repository flags.')
                if opts.get('from_image') or str(opts.get('demos', 'no')).lower() not in ('', 'no', 'none'):
                    raise click.UsageError('Software profiles cannot combine with image or demo overrides.')
                try:
                    document = resolve_profile(source)['profile']
                    home = '/home/' + (opts.get('ssh_user') or config['default_ssh_user'])
                    report = render_profile(document, 'ansible', home)
                    if not report['render_supported']:
                        raise ValueError('Software profile has required unmapped fields; inspect software-profile render coverage.')
                except (ValueError, OSError) as exc:
                    raise click.BadParameter(str(exc), param_hint='--software-profile') from None
                ctx.meta['software_profile_document'] = document
                ctx.meta['software_profile_source'] = source
                # Explicit argv suppresses legacy interactive component prompts;
                # the original tokens were checked for conflicting overrides.
                args = list(args)
                for name, value in report['deploy_params'].items():
                    args.extend(['--' + name.replace('_', '-'), value])
        remainder = super().parse_args(ctx, args)
        document = ctx.params.get('software_profile')
        if document is not None:
            # Preserve reviewed intent separately, but transport the callback's
            # concrete latest selection rather than reintroducing literal latest.
            from copy import deepcopy
            resolved = deepcopy(document)
            changed = False
            # GR00T/LeRobot have no legacy ref option callbacks, but their
            # enabled Git sources require the same public-only preflight.
            for component in ('gr00t', 'lerobot'):
                value = resolved.get('components', {}).get(component, {})
                source = value.get('source', {})
                if value.get('enabled') and source.get('mode') == 'git':
                    selected = self._check_git_selection(
                        ctx, click.Option(('--' + component,)),
                        source.get('revision') or source['ref'], source['repository'], lambda message: None)
                    if not source.get('revision') and selected != source['ref']:
                        source['ref'] = selected
                        changed = True
            for component, parameter in (('sim', 'isaacsim'), ('lab', 'isaaclab'), ('arena', 'isaaclab_arena')):
                value = resolved.get('components', {}).get(component, {})
                source = value.get('source', {})
                if (value.get('enabled') and source.get('mode') == 'git'
                        and not source.get('revision') and str(source.get('ref', '')).lower() == 'latest'):
                    source['ref'] = ctx.params[parameter]
                    changed = True
            if changed:
                ctx.params['software_profile_requested'] = document
                ctx.params['software_profile'] = resolved
        return remainder

    @staticmethod
    def software_profile_callback(ctx, param, value):
        return ctx.meta.get('software_profile_document') if value is not None else None

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

    @staticmethod
    def git_repo_callback(ctx, param, value):
        """Accept deliberately narrow credential-free HTTPS URL syntax.

        This does not establish public visibility or anonymous reachability.
        ASCII DNS hosts and plain path segments only: no userinfo, query,
        fragment, escapes, shell syntax or Ansible interpolation. Preserve the
        exact spelling used for validation and checkout; never echo rejected data.
        """
        label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        match = re.fullmatch(
            rf"https://{label}(?:\.{label})*/([A-Za-z0-9_./-]+)", value
        ) if isinstance(value, str) else None
        if not match or any(part in ("", ".", "..") for part in match[1].split("/")):
            raise click.BadParameter(
                "Use a credential-free HTTPS repository URL with an ASCII DNS host "
                "and plain path segments; credentials, ports, queries, fragments, "
                "escapes and shell/template syntax are not supported.",
                ctx=ctx, param=param,
            )
        return value

    @staticmethod
    def remote_desktop_callback(ctx, param, value):
        """
        Validate and normalize the --remote-desktop option.
        Accepts a comma-separated list of providers, or special keywords:
        - "standard": expands to default standard providers (nomachine,novnc)
        - "all": all registered providers
        - "no" / "none": disables remote desktop installation
        """
        if value is None or str(value).strip() == "":
            return config.get("default_remote_desktop", "standard")

        val_str = str(value).strip().lower()
        if val_str in ("no", "none"):
            return "no"

        registry = config.get("remote_desktop_providers", {})
        valid_keys = set(registry.keys())
        aliases = {
            "rdp": "xrdp",
            "nice-dcv": "dcv",
            "nicedcv": "dcv",
            "moonlight": "sunshine",
        }

        parts = [p.strip() for p in val_str.split(",") if p.strip()]
        resolved = []
        for p in parts:
            if p == "standard":
                resolved.extend([k for k, v in registry.items() if v.get("standard")])
            elif p == "all":
                resolved.extend(list(registry.keys()))
            else:
                norm = aliases.get(p, p)
                if norm not in valid_keys:
                    valid_list = ", ".join(sorted(valid_keys)) + ", standard, all, no"
                    raise click.BadParameter(
                        colorize_error(
                            f"Unknown remote desktop provider '{p}'. Valid values: {valid_list}"
                        ),
                        ctx=ctx,
                        param=param,
                    )
                resolved.append(norm)

        # Deduplicate while preserving order
        deduped = []
        for r in resolved:
            if r not in deduped:
                deduped.append(r)

        return ",".join(deduped) if deduped else config.get("default_remote_desktop", "standard")

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
    def _anonymous_ls_remote(cmd):
        """Query without ambient auth/config/proxies or repository discovery.

        URL validation is syntax only. Anonymous reachability is an independent
        preflight, not proof of commit reachability or target-side checkout safety.
        Never copy the caller's environment: Git/curl have many auth/config inputs.
        """
        with tempfile.TemporaryDirectory(prefix='isaac-public-git-') as directory:
            env = {
                'PATH': os.defpath, 'HOME': directory, 'XDG_CONFIG_HOME': directory,
                'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
                'GIT_CONFIG_SYSTEM': os.devnull, 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_CEILING_DIRECTORIES': os.path.dirname(directory),
                'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false',
                'SSH_ASKPASS': '/bin/false', 'GIT_SSH_COMMAND': '/bin/false',
                'GIT_ALLOW_PROTOCOL': 'https',
            }
            settings = {
                'credential.helper': '', 'credential.interactive': 'false',
                'core.askPass': '/bin/false', 'http.proxy': '',
                'http.extraHeader': '', 'http.followRedirects': 'false',
                'http.sslVerify': 'true',
            }
            env['GIT_CONFIG_COUNT'] = str(len(settings))
            for index, (key, value) in enumerate(settings.items()):
                env[f'GIT_CONFIG_KEY_{index}'] = key
                env[f'GIT_CONFIG_VALUE_{index}'] = value
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                  stdin=subprocess.DEVNULL, cwd=directory, env=env)

    @staticmethod
    def _public_remote_refs(result):
        """Accept only a successful, nonempty Git ref advertisement (not a SHA proof)."""
        if type(getattr(result, 'returncode', None)) is not int or result.returncode != 0:
            raise subprocess.SubprocessError('Anonymous Git request failed')
        output = getattr(result, 'stdout', None)
        if not isinstance(output, str) or not output.strip():
            raise subprocess.SubprocessError('Anonymous Git advertisement missing')
        refs = set()
        for line in output.splitlines():
            match = re.fullmatch(
                r'[0-9a-fA-F]{40}\t(HEAD|refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]*(?:\^\{\})?)', line)
            if not match:
                raise subprocess.SubprocessError('Anonymous Git advertisement malformed')
            refs.add(match[1])
        return refs

    @staticmethod
    def _resolve_latest_ref(repo, dbg, public_only=False):
        """
        Auto-detect the latest release ref in `repo`: the highest version across its
        tags and release/* branches (prereleases included). On a version tie a
        release/* branch wins over a tag (matches how Lab/Arena are tracked). Returns
        the ref to check out (e.g. "v6.0.1" or "release/0.2.1"), or None if none found.
        """
        cmd = ["git", "ls-remote", "--tags", "--heads", repo]
        dbg("latest: resolving latest release for " + repo)
        dbg("running: " + " ".join(cmd))
        result = DeployCommand._anonymous_ls_remote(cmd)
        if public_only:
            DeployCommand._public_remote_refs(result)
        elif getattr(result, 'returncode', 0) != 0:
            raise subprocess.SubprocessError('Anonymous Git request failed')
        if not public_only and result.stderr.strip():
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

        if ctx is not None:
            repo = ctx.params.get(f"{param.name}_repo", repo)
        return DeployCommand._check_git_selection(ctx, param, value, repo, dbg)

    @staticmethod
    def _check_git_selection(ctx, param, value, repo, dbg):
        """Shared preflight for legacy selectors and every enabled profile Git source."""
        repo = DeployCommand.git_repo_callback(None, None, repo)
        public_only = (ctx is not None and
                       getattr(ctx, 'meta', {}).get('software_profile_document') is not None)

        # "latest" -> resolve the latest release ref and use that
        if value.strip().lower() == "latest":
            try:
                resolved = DeployCommand._resolve_latest_ref(repo, dbg, public_only=public_only)
            except (OSError, subprocess.SubprocessError) as e:
                if public_only:
                    raise click.BadParameter(
                        'Anonymous public repository/latest-ref preflight failed; deployment refused.',
                        ctx=ctx, param=param,
                    ) from None
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

        # Full profile SHAs require the actual anonymously fetched commit object,
        # not merely a nonempty advertisement. Legacy selectors remain syntax-only;
        # abbreviated profile refs preserve their explicit unverified compatibility policy.
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
            if public_only and len(value) == 40:
                from src.python.public_git import PublicGitError, prove_public_commit
                try:
                    prove_public_commit(repo, value)
                except PublicGitError:
                    raise click.BadParameter(
                        'Anonymous full-SHA commit proof failed; deployment refused.',
                        ctx=ctx, param=param,
                    ) from None
                return value
            if public_only:
                try:
                    result = DeployCommand._anonymous_ls_remote(
                        ['git', 'ls-remote', '--heads', '--tags', repo])
                    DeployCommand._public_remote_refs(result)
                except (OSError, subprocess.SubprocessError):
                    raise click.BadParameter(
                        'Anonymous public repository preflight failed; deployment refused.',
                        ctx=ctx, param=param,
                    ) from None
                click.echo('Anonymous repository reachable; SHA syntax accepted, '
                           'commit reachability unverified.', err=True)
            else:
                dbg(f"'{value}' looks like a commit sha - accepting without ls-remote")
            return value

        cmd = ["git", "ls-remote", "--quiet", repo,
               value, f"refs/tags/{value}", f"refs/heads/{value}"]
        dbg(f"checking ref '{value}' in {repo}")
        dbg("running: " + " ".join(cmd))
        try:
            result = DeployCommand._anonymous_ls_remote(cmd)
            if public_only:
                refs = DeployCommand._public_remote_refs(result)
                if not refs.intersection((value, f'refs/tags/{value}', f'refs/heads/{value}')):
                    raise subprocess.SubprocessError('Requested ref not advertised')
            elif getattr(result, 'returncode', 0) != 0:
                raise click.BadParameter('Anonymous Git ref request failed.', ctx=ctx, param=param)
        except (OSError, subprocess.SubprocessError) as e:
            if public_only:
                raise click.BadParameter(
                    'Anonymous public repository/ref preflight failed; deployment refused.',
                    ctx=ctx, param=param,
                ) from None
            # Legacy explicit refs retain their warning-only exception policy.
            click.echo(colorize_error(
                f"Warning: could not verify {param.name} ref '{value}' ({e}). Continuing."
            ), err=True)
            return value

        found = result.stdout.strip()
        if not public_only and getattr(result, 'stderr', '').strip():
            dbg('stderr: ' + result.stderr.strip())
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

    @staticmethod
    def demos_callback(ctx, param, value):
        """
        Normalize --demos / --demo values into a comma-separated string,
        supporting multiple flags (--demo A --demo B), comma lists (--demos A,B),
        or 'no'.
        """
        if not value:
            return "no"
        if isinstance(value, (list, tuple)):
            items = []
            for v in value:
                for item in str(v).split(","):
                    item = item.strip()
                    if item and item.lower() not in ("no", "none"):
                        items.append(item)
            return ",".join(items) if items else "no"
        return str(value)

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

        # --software-profile is desired software intent, not --security-profile.
        self.params.append(click.Option(
            ('--software-profile',), default=None,
            callback=DeployCommand.software_profile_callback,
            help='Reviewed software YAML; unsupported required mappings refuse before deployment.'))

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
            + 'comma separated. Type "myip" to resolve your public IP during deployment. '
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

        # --profile / --security-profile
        help = (
            'Security & deployment profile. Valid values: "simple" ($0 added cost, auto-locked /32 IP firewall), '
            + '"team" (shared asset access, local state by default), '
            + '"enterprise" (KMS CMEK, secret manager, zero-trust private access), '
            + 'or any custom profile name / YAML path in configs/profiles/'
        )
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--profile", "--security-profile"),
                type=str,
                default=config.get("default_security_profile", "simple"),
                show_default=True,
                help=help + ".",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--simple",),
                is_flag=True,
                default=False,
                help="Shorthand for --profile simple (beginner-friendly, $0 added cost).",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--state-bucket",),
                type=str,
                default="",
                envvar="ISAAC_STATE_BUCKET",
                help="Deprecated GCP-only state intent. Use --state-backend gcs with --backend-config instead.",
            ),
        )

        self.params.extend([
            click.Option(("--state-backend",), default="local", show_default=True,
                         type=_BackendChoice(["local", "gcs", "s3", "azurerm"]),
                         help="Explicit state backend choice. GCS execution is supported for GCP; S3/Azure execution remains unavailable. Omitted defaults never override a profile."),
            click.Option(("--backend-config",), type=str,
                         help="Path to a strict nonsecret backend YAML/JSON configuration. GCS deployment also requires an explicit --project."),
        ])

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--cmek",),
                is_flag=True,
                default=False,
                help="Enable Customer-Managed Encryption Keys (KMS CMEK).",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--iap", "--enable-iap-only"),
                is_flag=True,
                default=False,
                help="Enforce private VM with Identity-Aware Proxy (IAP) access and zero public IP.",
            ),
        )

        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--oslogin", "--enable-oslogin"),
                is_flag=True,
                default=False,
                help="Enforce OS Login with 2FA instead of metadata SSH keys.",
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

        # Resolve repository selection before any revision callback, independent
        # of argument order (including a repo flag following its revision).
        for component, app in self._APP_NAMES.items():
            self.params.append(click.Option(
                (f"--{component.replace('_', '-')}-repo",),
                default=config[f"{component}_git_repo"],
                show_default=True,
                is_eager=True,
                callback=DeployCommand.git_repo_callback,
                help=f"Public HTTPS repository for {app} validation and checkout.",
            ))

        # --isaacsim
        help = 'Install Isaac Sim? Valid values: "latest" (newest release), "no", or a git ref in the selected repository. Commit SHA reachability is not verified.'
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
        help = 'Install Isaac Lab? Valid values: "latest" (newest release), "no", or a git ref in the selected repository. Commit SHA reachability is not verified.'
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
        help = 'Install Isaac Lab Arena? Valid values: "latest" (newest release), "no", or a git ref in the selected repository. Commit SHA reachability is not verified.'
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

        # --demos / --demo
        demo_names = ", ".join(sorted(config["demos"].keys()))
        help = (
            'Out-of-the-box demos to install as desktop shortcuts. Valid values: "no", '
            + f"or a comma-separated list of: {demo_names}. "
            + "A demo auto-enables the apps it depends on (e.g. Isaac Sim / Isaac Lab)."
        )
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--demos", "--demo"),
                help=help,
                default=[config["default_demos"]],
                multiple=True,
                show_default=True,
                callback=DeployCommand.demos_callback,
            ),
        )

        # --remote-desktop
        provider_names = ", ".join(sorted(config.get("remote_desktop_providers", {}).keys()))
        help = (
            'Remote desktop and streaming providers to install. Valid values: "standard" '
            + f'(NoMachine + noVNC), "all", "no", or a comma-separated list of: {provider_names}.'
        )
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--remote-desktop",),
                help=help,
                default=config.get("default_remote_desktop", "standard"),
                show_default=True,
                callback=DeployCommand.remote_desktop_callback,
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

        # --dry-run/--no-dry-run
        self.params.insert(
            len(self.params),
            click.core.Option(
                ("--dry-run/--no-dry-run",),
                prompt=False,
                default=False,
                show_default=True,
                help="Validate Terraform plan and Ansible playbooks without provisioning resources or incurring billing.",
            ),
        )
