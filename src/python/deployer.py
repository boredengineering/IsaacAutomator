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

from contextlib import contextmanager
import json
import copy
import ipaddress
import os
import re
import shlex
import sys
from pathlib import Path

import click
from src.python.backend_selection import BackendSelectionError, load_profile_yaml, select_backend
from src.python.terraform_backend import BackendSpec
from src.python.terraform_runner import TerraformRunner, TerraformRunnerError
from src.python.terraform_sources import workstation_source_files
from src.python.backend_runtime import load_backend_record, runtime_guard, write_private_metadata

from src.python.debug import debug_break  # noqa
from src.python.utils import (
    colorize_error,
    colorize_info,
    colorize_prompt,
    colorize_result,
    get_my_public_ip,
    read_tf_output,
    require_legacy_local_backend,
    shell_command,
    subnet_from_ip,
)


class Deployer:
    cloud = None
    _BACKEND_CONTROLLER_FIELDS = frozenset({
        'terraform_state', 'state_backend', 'state_bucket', 'backend_config', 'profile_spec', 'backend_runtime',
    })

    def __init__(self, params, config):
        self._persistence_ready = False
        # A concrete deployer identity must never come from restored metadata.
        self.cloud = self.cloud or params.get("cloud")
        self.tf_outputs = {}
        self.params = params
        self.config = config
        self.existing_behavior = None
        saved = self.require_saved_backend()
        if saved is not None:
            if self.cloud != saved.backend_spec.cloud:
                raise click.ClickException('Saved backend cloud cannot be changed.')
            self.params.setdefault('terraform_state', saved.backend_spec.to_dict())
            if self.params.get('project') is None:
                self.params['project'] = saved.target_scope
            self.params['backend_runtime'] = {'identity': saved.identity, 'status': saved.status,
                                             'lineage': saved.lineage}

        # save original params so we can recreate command line
        self.input_params = params.copy()

        # convert "in_china"
        self.params["in_china"] = {"yes": True, "no": False, "auto": False}[
            self.params["in_china"]
        ]

        # resolve --demos: validate names and auto-enable required apps
        self.resolve_demos()

        # resolve --remote-desktop: validate providers
        self.resolve_remote_desktop()

        # resolve --security-profile: simple / team / enterprise
        self.resolve_security_profile()

        # create state directory if it doesn't exist
        os.makedirs(self.config["state_dir"], exist_ok=True)

        # override default_ssh_user from CLI param
        if "ssh_user" in self.params:
            self.config["default_ssh_user"] = self.params["ssh_user"]
            self.config["default_remote_uploads_dir"] = (
                f"/home/{self.config['default_ssh_user']}/uploads"
            )
            self.config["default_remote_results_dir"] = (
                f"/home/{self.config['default_ssh_user']}/results"
            )
            self.config["default_remote_workspace_dir"] = (
                f"/home/{self.config['default_ssh_user']}/workspace"
            )

        # print complete command line
        if self.params["debug"]:
            click.echo(colorize_info("* Command:\n" + self.recreate_command_line()))

        self._persistence_ready = True

    def resolve_demos(self):
        """
        Normalize the --demos option, validate demo names against the registry,
        and auto-enable the apps each selected demo depends on.

        A demo that needs an app (e.g. Isaac Sim / Isaac Lab) which the user left
        off ("no"/empty) flips that app back on using its default git ref, so a
        demo is deployable with a single flag.
        """

        if "demos" not in self.params:
            return

        raw = self.params.get("demos")
        if isinstance(raw, (list, tuple)):
            raw = ",".join(str(x) for x in raw)
        else:
            raw = str(raw or "no").strip()

        # treat "no"/empty as no demos
        if raw.lower() in ("", "no", "none"):
            self.params["demos"] = "no"
            return

        registry = self.config.get("demos", {})
        selected = [d.strip() for d in raw.split(",") if d.strip()]

        # validate
        unknown = [d for d in selected if d not in registry]
        if unknown:
            click.echo(
                colorize_error(
                    f"* Unknown demo(s): {', '.join(unknown)}. "
                    + f"Valid demos: {', '.join(sorted(registry.keys())) or '(none)'}."
                ),
                err=True,
            )
            sys.exit(1)

        # auto-enable required apps
        for demo in selected:
            for app in registry[demo].get("requires", []):
                current = str(self.params.get(app, "no")).strip().lower()
                if current in ("", "no", "none"):
                    default_ref = self.config.get(f"default_{app}_git_checkpoint")
                    if default_ref:
                        self.params[app] = default_ref
                        click.echo(
                            colorize_info(
                                f'* Demo "{demo}" requires {app}; enabling it'
                                f" ({default_ref})."
                            )
                        )

        # store back the normalized, de-duplicated selection
        self.params["demos"] = ",".join(dict.fromkeys(selected))

    def resolve_remote_desktop(self):
        """
        Normalize the --remote-desktop option and validate providers against the registry.
        """
        if "remote_desktop" not in self.params:
            self.params["remote_desktop"] = self.config.get(
                "default_remote_desktop", "standard"
            )

        raw = str(self.params.get("remote_desktop") or "standard").strip()
        if raw.lower() in ("", "no", "none"):
            self.params["remote_desktop"] = "no"
            return

        registry = self.config.get("remote_desktop_providers", {})
        aliases = {
            "rdp": "xrdp",
            "nice-dcv": "dcv",
            "nicedcv": "dcv",
            "moonlight": "sunshine",
        }

        selected = []
        for item in [x.strip().lower() for x in raw.split(",") if x.strip()]:
            if item == "standard":
                selected.extend(
                    [k for k, v in registry.items() if v.get("standard")]
                )
            elif item == "all":
                selected.extend(list(registry.keys()))
            else:
                norm = aliases.get(item, item)
                if norm not in registry:
                    click.echo(
                        colorize_error(
                            f"* Unknown remote desktop provider: {item}. "
                            f"Valid providers: {', '.join(sorted(registry.keys()))}, standard, all, no."
                        ),
                        err=True,
                    )
                    sys.exit(1)
                selected.append(norm)

        self.params["remote_desktop"] = (
            ",".join(dict.fromkeys(selected)) if selected else "standard"
        )

    def resolve_security_profile(self):
        """
        Resolves security profile with beginner-friendly defaults and user choice.
        Supports built-in profiles ('simple', 'team', 'enterprise') or custom YAML specs
        discovered in configs/profiles/ or passed as paths.
        """
        if self.params.get("simple"):
            profile_name = "simple"
        else:
            profile_name = self.params.get("profile") or self.params.get("security_profile")

        if not profile_name:
            profile_name = self.config.get("default_security_profile", "simple")

        from src.python.config import list_available_profiles, load_profile_spec

        from src.python.registry_profile import RegistryProfileError

        try:
            spec = load_profile_spec(str(profile_name), repo_root=self.config.get("app_dir"))
        except (RegistryProfileError, BackendSelectionError) as exc:
            raise click.ClickException(str(exc)) from exc

        if not spec:
            available = list(list_available_profiles(self.config.get("app_dir")).keys())
            click.echo(
                colorize_error(
                    f"* Unknown security profile '{profile_name}'. "
                    f"Valid profiles: {', '.join(sorted(available))}."
                ),
                err=True,
            )
            sys.exit(1)

        tier = spec.get("tier", "simple")
        if not spec.get("path") and spec.get("name") in ("team", "enterprise"):
            click.echo(
                "Warning: built-in team/enterprise now use local state by default; "
                "remote state requires explicit --state-backend and --backend-config opt-in. "
                "GCS lifecycle is supported; S3/Azure workstation mutation is not enabled.", err=True,
            )
        self.params["security_profile"] = tier
        self.params["profile"] = profile_name
        self.params["profile_spec"] = spec

        from src.python.registry_profile import normalize_registries
        from src.python.huggingface_profile import normalize_huggingface

        registry = {**normalize_registries(spec.get("raw", {})),
                    **normalize_huggingface(spec.get("raw", {}))}
        self.validate_registry_params(dict(self.params, **registry))
        self.params.update(registry)

        # Apply profile toggles to params if not explicitly overridden on CLI
        if "enable_cmek" not in self.params:
            self.params["enable_cmek"] = spec.get("enable_cmek", False)
        if "enable_iap_only" not in self.params:
            self.params["enable_iap_only"] = spec.get("enable_iap_only", False)
        if "enable_oslogin" not in self.params:
            self.params["enable_oslogin"] = spec.get("enable_oslogin", False)
        if "enable_secrets" not in self.params:
            self.params["enable_secrets"] = spec.get("enable_secrets", False)
        backend_profile = dict(spec)
        if 'terraform_state' in self.params:
            backend_profile['terraform_state'] = self.params['terraform_state']
        try:
            backend = select_backend(
                self.params, backend_profile, self.cloud or 'aws',
                click.get_current_context(silent=True),
            )
        except BackendSelectionError as exc:
            raise click.ClickException(str(exc)) from None
        if backend.backend not in ('local', 'gcs'):
            raise click.ClickException(
                "Remote backend lifecycle is not implemented safely; deployment is refused "
                "until verified attachment/migration support is available."
            )
        self.params['terraform_state'] = backend.to_dict()
        self.params['state_backend'] = backend.backend
        self.params['state_bucket'] = ''
        self.params.pop('backend_config', None)
        if backend.backend == 'gcs':
            project = self.params.get('project')
            if not isinstance(project, str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project):
                raise click.ClickException('GCS deployment requires an explicit --project workload project ID.')
            self.params.setdefault('backend_runtime', {
                'identity': backend.identity(self.params.get('project'), self.params['deployment_name']),
                'status': 'configured', 'lineage': None})
        # Save effective selection, never paths to mutable external config or
        # discarded lower-priority intent that could mask a future attachment.
        for key in self._BACKEND_CONTROLLER_FIELDS:
            self.input_params.pop(key, None)
        self.input_params['state_backend'] = backend.backend
        effective_profile = copy.deepcopy(spec)
        # Retain workload profile settings, but not a discarded state destination.
        for block in (effective_profile, effective_profile.get('raw', {}),
                      effective_profile.get('raw', {}).get('security', {}).get('storage', {})):
            for key in ('terraform_state', 'state_backend', 'state_bucket', 'backend_config'):
                block.pop(key, None)
        self.params['profile_spec'] = effective_profile
        self.require_backend()

        if self.params.get("debug"):
            click.echo(colorize_info(f"* Selected security profile: '{profile_name}' (Tier: {tier})"))

    def _require_local_intent(self, params):
        if not isinstance(params, dict):
            raise click.ClickException("Cannot verify backend metadata; attachment/migration review is required.")
        if params.get('state_bucket') or params.get('backend_config') or params.get('state_backend') not in (None, '', 'local'):
            raise click.ClickException("Remote backend lifecycle is not implemented safely; verify attachment/migration before continuing.")
        try:
            backend = BackendSpec.from_dict(params.get('terraform_state'), cloud=self.cloud or 'aws')
        except ValueError:
            raise click.ClickException("Invalid backend configuration; remote lifecycle is not implemented safely.") from None
        if backend.backend != 'local':
            raise click.ClickException("Remote backend lifecycle is not implemented safely; verify attachment/migration before continuing.")
        for key in ('profile_spec', 'raw'):
            if key in params:
                self._require_local_intent(params[key])
        if 'security' in params:
            security = params['security']
            if not isinstance(security, dict):
                raise click.ClickException("Cannot verify backend metadata; attachment/migration review is required.")
            if 'storage' in security:
                self._require_local_intent(security['storage'])

    def require_saved_local_backend(self):
        """Saved identity wins, including against an explicit new local choice."""
        directory = Path(self.config['state_dir']) / self.params['deployment_name']
        try:
            require_legacy_local_backend(directory)
        except click.ClickException:
            raise click.ClickException(
                "Saved backend attachment cannot be used by the legacy executor; "
                "backend-aware attachment/migration is not implemented safely. "
                "Preserve existing metadata and verify the authoritative state; do not change its destination."
            ) from None
        meta = directory / 'meta.json'
        if meta.exists():
            try:
                data = load_profile_yaml(meta)
            except BackendSelectionError:
                raise click.ClickException("Cannot verify backend metadata; attachment/migration review is required.") from None
            for section in ('params', 'input_params'):
                self._require_local_intent(data.get(section, {}))

    def require_saved_backend(self):
        """Saved GCS params dispatch natively; old claim/migration records stay fenced."""
        try:
            record = load_backend_record(self.params['deployment_name'], state_root=self.config['state_dir'])
        except TerraformRunnerError as exc:
            raise click.ClickException(str(exc)) from None
        if record is None:
            self.require_saved_local_backend()
        return record

    def require_backend(self, params=None):
        """Check effective intent against persisted destination before any write."""
        params = self.params if params is None else params
        saved = self.require_saved_backend()
        try:
            spec = BackendSpec.from_dict(params.get('terraform_state'), cloud=self.cloud or 'aws')
            if spec.backend == 'local':
                if saved is not None:
                    raise ValueError()
                self._require_local_intent(params)
                return
            if spec.backend != 'gcs' or params.get('state_backend') not in (None, 'gcs'):
                raise ValueError()
            identity = spec.identity(params.get('project'), self.params['deployment_name'])
            if saved is not None and saved.identity != identity:
                raise ValueError()
            if (saved is not None and saved.lineage is not None
                    and params.get('backend_runtime', {}).get('status') == 'configured'):
                # init may have durably pinned an empty GCS state during a plan.
                # A later ordinary metadata save must not erase that receipt.
                params['backend_runtime'] = {'identity': saved.identity, 'status': saved.status, 'lineage': saved.lineage}
            directory = Path(self.config['state_dir']) / self.params['deployment_name']
            if saved is None and ((directory / '.tfstate').exists() or (directory / 'meta.json').exists()):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise click.ClickException('Backend destination is invalid or changed; explicit attachment/migration is required.') from None

    def require_local_backend(self, params=None):
        """Recheck disk and current/restored intent before any legacy mutation."""
        self.require_saved_local_backend()
        self._require_local_intent(self.params if params is None else params)

    def validate_registry_params(self, params, cloud=None):
        from src.python.huggingface_profile import normalize_huggingface
        from src.python.registry_profile import (
            RegistryProfileError,
            normalize_saved_registries,
        )

        if cloud is None:
            cloud = self.cloud or params.get("cloud") or params.get(
                "profile_spec", {}
            ).get("raw", {}).get("cloud")
        try:
            registry = normalize_saved_registries(params, cloud)
            if params.get("cloud") is not None:
                normalize_saved_registries(params, params["cloud"])
            registry.update(normalize_huggingface(params))
            return registry
        except RegistryProfileError as exc:
            self._persistence_ready = False
            raise click.ClickException(str(exc)) from exc

    def save_meta(self):
        """
        Save validated command parameters at explicit workflow boundaries.

        Never save during object finalization: a most-derived constructor may
        fail after base initialization succeeds, and must not overwrite state.
        """

        if not getattr(self, "_persistence_ready", False):
            return
        self.require_backend()
        self.params.update(self.validate_registry_params(self.params))

        meta_file = (
            f"{self.config['state_dir']}/{self.params['deployment_name']}/meta.json"
        )

        data = {
            "command": self.recreate_command_line(separator=" "),
            "input_params": self.input_params,
            "params": self.params,
            "config": self.config,
        }

        Path(meta_file).parent.mkdir(parents=True, exist_ok=True)
        try:
            write_private_metadata(meta_file, data)
        except TerraformRunnerError as exc:
            raise click.ClickException(str(exc)) from None

        if self.params["debug"]:
            click.echo(colorize_info(f"* Meta info saved to '{meta_file}'"))

    def read_meta(self):
        try:
            return load_profile_yaml(Path(self.config['state_dir']) / self.params['deployment_name'] / 'meta.json')
        except BackendSelectionError:
            raise click.ClickException("Cannot read deployment metadata; recovery files are preserved.") from None

    def recreate_command_line(self, separator=" \\\n"):
        """
        Recreate command line
        """

        command_line = sys.argv[0]

        for k, v in self.input_params.items():
            if k in self._BACKEND_CONTROLLER_FIELDS and k != 'state_backend':
                continue
            k = k.replace("_", "-")

            if isinstance(v, bool):
                if v:
                    command_line += separator + "--" + k
                else:
                    not_prefix = "--no-"

                    if k in ["from-image"]:
                        not_prefix = "--not-"

                    command_line += separator + not_prefix + k
            else:
                command_line += separator + "--" + k + " "

                if isinstance(v, str):
                    command_line += shlex.quote(v)
                else:
                    command_line += str(v)

        return command_line

    def ask_existing_behavior(self):
        """
        Ask what to do if deployment already exists
        """

        self.require_backend()
        deployment_name = self.params["deployment_name"]
        existing = self.params["existing"]

        self.existing_behavior = existing

        if existing == "ask" and os.path.isfile(
            f"{self.config['state_dir']}/{deployment_name}/.tfvars"
        ):
            self.existing_behavior = click.prompt(
                text=colorize_prompt(
                    "* Deploymemnt exists, what would you like to do? See --help for details."
                ),
                type=click.Choice(["repair", "modify", "replace", "run_ansible"]),
                default="replace",
            )

        if (
            self.existing_behavior == "repair"
            or self.existing_behavior == "run_ansible"
        ):
            # restore params from meta file
            self._persistence_ready = False
            r = self.read_meta()
            self.require_backend(r["params"])
            registry = self.validate_registry_params(r["params"])
            self.params = r["params"]
            self.params.update(registry)
            self._persistence_ready = True

            click.echo(
                colorize_info(
                    f"* Repairing existing deployment \"{self.params['deployment_name']}\"..."
                )
            )

        # Preserve the old inputs and receipt until active GCS destruction is
        # verified. A failed replacement must still describe the old workload.
        self._gcs_replacement_destroyed = False
        active_gcs_replace = (self.existing_behavior == 'replace'
            and self.params.get('state_backend') == 'gcs'
            and self.params.get('backend_runtime', {}).get('status') != 'configured')
        if not active_gcs_replace:
            self.save_meta()

        # destroy existing deployment``
        if self.existing_behavior == "replace" and not self.params.get('dry_run') and not (
                self.params.get('state_backend') == 'gcs'
                and self.params.get('backend_runtime', {}).get('status') == 'configured'):
            debug = self.params["debug"]
            click.echo(colorize_info("* Deleting existing deployment..."))

            if self.params.get('state_backend') == 'gcs':
                with self._terraform_operation(str(Path(self.config['terraform_dir']) / self.cloud)) as runner:
                    runner.init()
                    runner.apply(runner.plan(destroy=True), acknowledge_mutation=True)
                    state = runner.pull_state()
                    if (state['lineage'] != self.params['backend_runtime']['lineage']
                            or any(resource['mode'] == 'managed' and resource['instances'] for resource in state['resources'])):
                        runner.retain_recovery()
                        raise click.ClickException('GCS replacement destruction is incomplete; recovery review required.')
                    runner.assert_no_recovery()
                    try:
                        self.save_meta()
                    except BaseException:
                        runner.retain_recovery()
                        raise
                self._gcs_replacement_destroyed = True
            else:
                shell_command(
                    command=f'{self.config["app_dir"]}/destroy "{deployment_name}" --yes'
                    + f' {"--debug" if debug else ""}',
                    verbose=debug,
                )

            # GCS publication above stays inside the recovery-capable context.
            if self.params.get('state_backend') != 'gcs':
                self.save_meta()

    def create_tfvars(self, tfvars: dict | None = None):
        """
        - Check if deployment with this deployment_name exists and deal with it
        - Create/update tfvars file

        Expected values for "existing_behavior" arg:
            - repair: keep tfvars/tfstate, don't ask for user input
            - modify: keep tfstate file, update tfvars file with user input
            - replace: delete tfvars/tfstate files
            - run_ansible: keep tfvars/tfstate, don't ask for user input, skip terraform steps
        """

        self.require_backend()
        self.params.update(self.validate_registry_params(self.params))
        if tfvars is None:
            tfvars = {}
        debug = self.params["debug"]

        # convert CIDRs from special values

        ingress_cidrs = [
            x.strip().lower() for x in str(self.params["ingress_cidrs"]).split(",")
        ]

        ingress_cidrs_actual = []

        for cidr in ingress_cidrs:

            # if no ingress CIDRs are specified, use my public IP
            if cidr in ("", "auto", "myip"):
                cidr = get_my_public_ip(verbose=debug) + "/32"
                if debug:
                    click.echo(
                        colorize_info(
                            f"* No ingress CIDRs specified, using public IP: {cidr}"
                        )
                    )
            elif cidr in ("mynet", "myip/16"):
                # if "mynet" is specified, use my public IP with /16 mask
                cidr = subnet_from_ip(get_my_public_ip(verbose=debug), "16")
                if debug:
                    click.echo(
                        colorize_info(f"* Using CIDR block for my network: {cidr}")
                    )
            elif cidr in ("myip/24"):
                cidr = subnet_from_ip(get_my_public_ip(verbose=debug), "24")
                if debug:
                    click.echo(
                        colorize_info(f"* Using CIDR block for my network: {cidr}")
                    )
            elif cidr in ("myip/8"):
                cidr = subnet_from_ip(get_my_public_ip(verbose=debug), "8")
                if debug:
                    click.echo(
                        colorize_info(f"* Using CIDR block for my network: {cidr}")
                    )
            # elif cidr == "nvidia": TODO

            ingress_cidrs_actual.append(cidr)

        # remove duplicates
        ingress_cidrs_actual = list(set(ingress_cidrs_actual))

        # Simple Mode IP Lockdown:
        # In simple mode, lock ingress strictly to caller IP if default (0.0.0.0/0, auto, empty)
        # to guarantee zero open-port internet exposure for beginners.
        if self.params.get("security_profile") == "simple":
            raw_cidrs = str(self.params.get("ingress_cidrs", "")).strip().lower()
            if raw_cidrs in ("", "auto", "myip", "0.0.0.0/0", "none"):
                my_ip = get_my_public_ip(verbose=debug)
                ingress_cidrs_actual = [f"{my_ip}/32"]
                if debug:
                    click.echo(
                        colorize_info(
                            f"* Simple Mode: Ingress firewall locked strictly to caller IP ({my_ip}/32)."
                        )
                    )

        # default values common for all clouds
        tfvars.update(
            {
                "isaac_workstation_enabled": True,
                #
                "isaac_workstation_instance_type": (
                    self.params["isaac_workstation_instance_type"]
                    if "isaac_workstation_instance_type" in self.params
                    else "none"
                ),
                #
                "prefix": self.params["prefix"],
                "ssh_port": self.params["ssh_port"],
                #
                "from_image": (
                    self.params["from_image"] if "from_image" in self.params else False
                ),
                #
                "deployment_name": self.params["deployment_name"],
                "ingress_cidrs": ingress_cidrs_actual,
                "os_username": self.config["default_ssh_user"],
                "security_profile": self.params.get("security_profile", "simple"),
                "enable_cmek": self.params.get("enable_cmek", False),
                "enable_iap_only": self.params.get("enable_iap_only", False),
                "enable_oslogin": self.params.get("enable_oslogin", False),
                "enable_secrets": self.params.get("enable_secrets", False),

            }
        )

        if self.params.get("enable_artifact_registry"):
            for key in (
                "enable_artifact_registry",
                "artifact_registry_project",
                "artifact_registry_location",
                "artifact_registry_repository",
            ):
                tfvars[key] = self.params[key]

        registry = self.params.get("container_registry", {})
        if registry.get("enabled") and registry.get("provider") == "aws_ecr":
            tfvars["enable_ecr"] = True
            for key in ("account_id", "region", "repository"):
                tfvars[f"ecr_{key}"] = registry[key]

        debug = self.params["debug"]
        deployment_name = self.params["deployment_name"]

        # deal with existing deployment:

        tfvars_file = f"{self.config['state_dir']}/{deployment_name}/.tfvars"
        tfstate_file = f"{self.config['state_dir']}/{deployment_name}/.tfstate"

        # tfvars
        if os.path.exists(tfvars_file):
            if (
                self.existing_behavior == "modify"
                or self.existing_behavior == "overwrite"
            ):
                os.remove(tfvars_file)
                if debug:
                    click.echo(colorize_info(f'* Deleted "{tfvars_file}"...'))

        # tfstate
        if os.path.exists(tfstate_file):
            if self.existing_behavior == "overwrite":
                os.remove(tfstate_file)
                if debug:
                    click.echo(colorize_info(f'* Deleted "{tfstate_file}"...'))

        # create tfvars file
        if (
            self.existing_behavior == "modify"
            or self.existing_behavior == "overwrite"
            or (self.existing_behavior == 'replace'
                and getattr(self, '_gcs_replacement_destroyed', False))
            or not os.path.exists(tfvars_file)
        ):
            self._write_tfvars_file(path=tfvars_file, tfvars=tfvars)

    def _write_tfvars_file(self, path: str, tfvars: dict):
        """
        Write tfvars file
        """
        self.require_backend()
        debug = self.params["debug"]

        if debug:
            click.echo(colorize_info(f'* Created tfvars file "{path}"'))

        # create <dn>/ directory if it doesn't exist
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            for key, value in tfvars.items():
                if key.replace('-', '_') in self._BACKEND_CONTROLLER_FIELDS:
                    continue
                # convert booleans to strings
                if isinstance(value, bool):
                    value = {
                        True: "true",
                        False: "false",
                    }[value]

                # format key names
                key = key.replace("-", "_")

                # write values
                if isinstance(value, str):
                    value = value.replace('"', '\\"')
                    f.write(f'{key} = "{value}"\n')
                elif isinstance(value, list):
                    f.write(f"{key} = " + str(value).replace("'", '"') + "\n")
                else:
                    f.write(f"{key} = {value}\n")

    def create_ansible_inventory(self, write: bool = True):
        """
        Create Ansible inventory, return it as text
        Write to file if write=True
        """

        self.require_backend()
        self._require_current_terraform_outputs()
        self.params.update(self.validate_registry_params(self.params))
        debug = self.params["debug"]
        deployment_name = self.params["deployment_name"]

        ansible_vars = {key: value for key, value in self.params.items()
                        if key not in self._BACKEND_CONTROLLER_FIELDS}

        # add config
        ansible_vars["config"] = self.config

        # default resilience parameters
        ansible_vars.setdefault("gcs_backup_bucket", self.params.get("backup_bucket", "") or "")
        ansible_vars.setdefault("gcs_auto_restore", self.params.get("auto_restore", False))

        ansible_vars.setdefault("enable_artifact_registry", False)
        for key in ("project", "location", "repository"):
            ansible_vars.setdefault(f"artifact_registry_{key}", "")
        ansible_vars["artifact_registry_images_json"] = json.dumps(
            self.params.get("artifact_registry_images", {}), sort_keys=True
        )
        ansible_vars["container_registry_json"] = json.dumps(
            self.params.get("container_registry", {"enabled": False}), sort_keys=True
        )
        ansible_vars["huggingface_json"] = json.dumps(
            self.params.get("huggingface", {"enabled": False}), sort_keys=True
        )

        # get missing values from terraform
        for k in [
            "isaac_workstation_ip",
            "cloud",
        ]:
            if (getattr(self, '_terraform_outputs_ready', None) is True
                    or k not in self.params or ansible_vars[k] is None):
                ansible_vars[k] = self.tf_output(k)

        if (ansible_vars['cloud'] not in ('aws', 'gcp', 'azure', 'alicloud')
                or (self.cloud is not None and ansible_vars['cloud'] != self.cloud)):
            raise click.ClickException('Terraform cloud output is absent or inconsistent; inventory write refused.')
        endpoint = None
        if ansible_vars['cloud'] == 'gcp' and (self.params.get('enable_iap_only') or self.params.get('enable_oslogin')):
            values = self._connection_outputs()
            ansible_vars['isaac_workstation_ip'] = self._connection_ip(values)
            endpoint = self._ssh_endpoint(values)
        try:
            if not isinstance(ansible_vars['isaac_workstation_ip'], str):
                raise ValueError
            ipaddress.ip_address(ansible_vars['isaac_workstation_ip'])
        except ValueError:
            # An explicit inventory-only localhost target is supported, but actual
            # Terraform address outputs must remain IPs, never inventory text.
            host = ansible_vars['isaac_workstation_ip']
            explicit_hostname = (
                getattr(self, '_terraform_outputs_ready', None) is not True
                and self.params.get('isaac_workstation_ip') == host
                and host == 'localhost'
            )
            if not explicit_hostname:
                raise click.ClickException('Terraform workstation IP output is absent or invalid; inventory write refused.') from None

        # Validate the actual cloud handed to Ansible, not only class identity.
        self.validate_registry_params(self.params, cloud=ansible_vars["cloud"])

        # convert booleans to ansible format
        ansible_booleans = {True: "true", False: "false"}
        for k, v in ansible_vars.items():
            if isinstance(v, bool):
                ansible_vars[k] = ansible_booleans[v]

        template = Path(f"{self.config['ansible_dir']}/inventory.template").read_text()
        res = template.format(**ansible_vars)
        if endpoint is not None:
            # Child-group values override legacy parent key/user settings.
            # Explicit true overrides ansible.cfg's legacy host checking=false.
            res += ('\n[isaac_workstation:vars]\n'
                    f'ansible_user={endpoint.user}\n'
                    f'ansible_ssh_private_key_file={endpoint.identity_file}\n'
                    f'ansible_ssh_common_args={shlex.join(endpoint.ssh_argv()[1:])}\n'
                    'ansible_ssh_host_key_checking=True\n')

        # write to file
        if write:
            inventory_file = f"{self.config['state_dir']}/{deployment_name}/.inventory"
            Path(inventory_file).parent.mkdir(parents=True, exist_ok=True)  # create dir
            Path(inventory_file).write_text(res)  # write file
            if debug:
                click.echo(
                    colorize_info(
                        f'* Created Ansible inventory file "{inventory_file}"'
                    )
                )

        return res

    def _new_terraform_runner(self, cwd: str):
        """Build an unentered local/GCS operation with exact persisted selection."""
        self.require_backend()
        cloud = self.cloud or Path(cwd).name
        source = Path(cwd).absolute()
        if source != Path(self.config['terraform_dir']).absolute() / cloud:
            raise click.ClickException('Terraform source root must match the configured workstation cloud root.')
        try:
            source_files = workstation_source_files(cloud)
            for relative in source_files:
                path = source / relative
                if ('..' in path.parts or not path.is_file()
                        or any(p.is_symlink() for p in (path, *path.parents))):
                    raise click.ClickException('Allowlisted Terraform source is missing or unsafe.')
        except (ValueError, OSError):
            raise click.ClickException('Cannot preflight reviewed Terraform sources; diagnostics withheld.') from None
        spec = BackendSpec.from_dict(self.params.get('terraform_state'), cloud=cloud)
        guard = None
        if spec.backend == 'gcs':
            record = load_backend_record(self.params['deployment_name'], state_root=self.config['state_dir'])
            if record is None:
                raise click.ClickException('Persist the exact GCS backend selection before running Terraform.')
            guard = runtime_guard(record, state_root=self.config['state_dir'])
        return TerraformRunner(
            source_root=source,
            source_files=source_files,
            backend_spec=spec,
            target_scope=self.params.get('project') if spec.backend == 'gcs' else None,
            deployment_name=self.params['deployment_name'],
            state_root=Path(self.config['state_dir']).absolute(),
            variables_file=Path(self.config['state_dir']).absolute() / self.params['deployment_name'] / '.tfvars',
            remote_guard=guard,
            staging_root=Path(self.config['state_dir']).absolute() / '.terraform-operations',
        )

    @contextmanager
    def _terraform_operation(self, cwd: str):
        operation = None
        try:
            operation = self._new_terraform_runner(cwd)
            with operation as runner:
                yield runner
        except TerraformRunnerError as exc:
            # Runner errors intentionally contain no Terraform diagnostics/inputs.
            raise click.ClickException(str(exc)) from None
        finally:
            if operation is not None and operation.recovery_directory is not None:
                # Never let the only recovery copy disappear with a local runner.
                # Keep the private paths available to API and CLI callers alike.
                self.terraform_recovery_directory = operation.recovery_directory
                self.terraform_recovery_state = operation.recovery_state
                click.echo(colorize_error(
                    f'* Terraform recovery requires manual review: {operation.recovery_directory}. '
                    'Contains secrets; retain securely before reboot or temporary-directory cleanup. '
                    'Do not retry or delete until recovery is reviewed.'
                ), err=True)

    def initialize_terraform(self, cwd: str):
        """Preflight only; actual init is deferred to each isolated operation.

        No active context, lock or temporary directory survives this call. This
        preserves the public call shape without leaking resources when a caller
        fails between initialize and run/plan. Import must likewise use the
        isolated import API, never a shell command in this source directory.
        Every operation rechecks current and saved backend intent.
        """
        try:
            self._new_terraform_runner(cwd)
        except TerraformRunnerError as exc:
            raise click.ClickException(str(exc)) from None

    def run_terraform(self, cwd: str):
        """Initialize, save a plan and apply that exact plan in one context."""
        self.require_backend()
        if self.params.get('dry_run'):
            raise click.ClickException('Terraform apply is forbidden during dry-run.')
        self.tf_outputs = {}
        self._terraform_outputs_ready = False
        with self._terraform_operation(cwd) as runner:
            runner.init()
            plan = runner.plan()
            runner.apply(plan, acknowledge_mutation=True)
            if self.params['terraform_state']['backend'] == 'gcs':
                previous = copy.deepcopy(self.params.get('backend_runtime'))
                try:
                    state = runner.pull_state()
                    self.params['backend_runtime'] = {
                        'identity': json.loads(runner.backend_identity), 'status': 'active', 'lineage': state['lineage']}
                    self.save_meta()
                except BaseException:
                    self.params['backend_runtime'] = previous
                    runner.retain_recovery()
                    raise TerraformRunnerError('GCS apply completed but metadata publication is uncertain; recovery evidence retained') from None
            outputs = runner.output()
        values = {key: copy.deepcopy(item['value']) for key, item in outputs.items()}
        if any(not isinstance(values.get(key), str) or not values[key].strip()
               for key in ('ssh_key', 'isaac_workstation_ip', 'cloud')):
            raise click.ClickException('Required Terraform workstation output is absent or invalid; downstream writes refused.')
        if values['cloud'] != (self.cloud or Path(cwd).name):
            raise click.ClickException('Terraform cloud output does not match the deployment; downstream writes refused.')
        try:
            ipaddress.ip_address(self._connection_ip(values))
        except ValueError:
            raise click.ClickException('Terraform workstation IP output is invalid; downstream writes refused.') from None
        self.tf_outputs = values
        self._terraform_outputs_ready = True

    def _connection_ip(self, values):
        """Validate fresh GCP connection scope/flags, without guessing a public IP."""
        if values.get('cloud') != 'gcp':
            return values.get('isaac_workstation_ip')
        for output, parameter in (('iap_enabled', 'enable_iap_only'), ('oslogin_enabled', 'enable_oslogin')):
            value = values.get(output, False)
            if type(value) is not bool or value != bool(self.params.get(parameter, False)):
                raise click.ClickException('Terraform SSH security output disagrees with the selected deployment.')
        if values.get('iap_enabled') or values.get('oslogin_enabled'):
            match = re.fullmatch(r'projects/([a-z][a-z0-9-]{4,28}[a-z0-9])/zones/([a-z][a-z0-9-]+)/instances/([a-z][a-z0-9-]{0,62})',
                                 values.get('isaac_workstation_vm_id', ''))
            if not match or match.group(1) != self.params.get('project') or match.group(2) != self.params.get('zone'):
                raise click.ClickException('Terraform IAP/OS Login instance scope is absent or inconsistent.')
        return values.get('isaac_workstation_private_ip') if values.get('iap_enabled') else values.get('isaac_workstation_ip')

    def _connection_outputs(self):
        if getattr(self, '_terraform_outputs_ready', None) is True:
            return self.tf_outputs
        values = {name: self.tf_output(name) for name in ('cloud', 'iap_enabled', 'oslogin_enabled',
            'isaac_workstation_ip', 'isaac_workstation_private_ip', 'isaac_workstation_vm_id')}
        for name in ('iap_enabled', 'oslogin_enabled'):
            if values[name] in ('True', 'true', 'False', 'false'):
                values[name] = values[name].lower() == 'true'
        return values

    def _ssh_endpoint(self, values):
        from src.python.file_transfer import endpoint_from_config
        try:
            return endpoint_from_config(self.params, values,
                Path(self.config['state_dir']).absolute() / self.params['deployment_name'],
                default_user=self.config['default_ssh_user'])
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None

    def _require_current_terraform_outputs(self):
        if getattr(self, '_terraform_outputs_ready', None) is False:
            raise click.ClickException('Verified Terraform outputs are unavailable; downstream writes refused.')

    def plan_terraform(self, cwd: str):
        """Validate through a real plan, without applying or logging its inputs.

        Terraform planning includes configuration validation. It may contact the
        backend and execute providers; this is not offline validation. The saved
        plan is secret-bearing and is discarded at context exit.
        """
        with self._terraform_operation(cwd) as runner:
            runner.init()
            plan = runner.plan()
            return plan.has_changes

    def import_terraform_resource(self, cwd: str, address: str, resource_id: str):
        """Import LOCAL state in its own initialized context, never shared cwd."""
        self.require_backend()
        if self.params.get('dry_run'):
            raise click.ClickException('Terraform import is forbidden during dry-run.')
        with self._terraform_operation(cwd) as runner:
            runner.init()
            runner.import_resource(address, resource_id, acknowledge_mutation=True)

    def validate_ansible(self, playbook_name: str = "isaac-workstation"):
        """
        Validate Ansible playbook syntax without running tasks.
        """
        self.require_backend()
        click.echo(colorize_info(f"* Validating Ansible playbook syntax ({playbook_name}.yaml)..."))
        shell_command(
            f"ansible-playbook --syntax-check {playbook_name}.yaml",
            cwd=f"{self.config['ansible_dir']}",
            verbose=self.params.get("debug", False),
        )

    def export_ssh_key(self):
        """
        Export SSH key from Terraform state
        """
        self.require_backend()
        self._require_current_terraform_outputs()
        deployment_name = self.params["deployment_name"]
        if self.cloud == 'gcp':
            # Saved flags may be stale: validate authoritative security outputs
            # independently on export, including paths without a fresh apply.
            values = self._connection_outputs()
            self._connection_ip(values)
            if values.get('oslogin_enabled'):
                self._ssh_endpoint(values)  # Resolve the actual gcloud OS Login identity.
                return  # Never serialize OS_LOGIN_ACTIVE or copy the user's private key.

        key = self.tf_output('ssh_key')
        if not isinstance(key, str) or not key.strip() or key.strip() == 'OS_LOGIN_ACTIVE':
            raise click.ClickException('Terraform SSH key output is absent or invalid; key export refused.')
        key_file = f"{self.config['state_dir']}/{deployment_name}/key.pem"
        with open(key_file, "w") as f:
            f.write(key if key.endswith("\n") else key + "\n")
        os.chmod(key_file, 0o600)

    def run_ansible(
        self,
        playbook_name: str,
        cwd: str,
        tags: [str] = [],
        skip_tags: [str] = [],
    ):
        """
        Run Ansible playbook via shell command
        """
        self.require_backend()
        debug = self.params["debug"]
        deployment_name = self.params["deployment_name"]

        if len(tags) > 0:
            tags = ",".join([f'--tags "{tag}"' for tag in tags])
        else:
            tags = ""

        if len(skip_tags) > 0:
            skip_tags = ",".join([f'--skip-tags "{tag}"' for tag in skip_tags])
        else:
            skip_tags = ""

        shell_command(
            f"ansible-playbook -i {self.config['state_dir']}/{deployment_name}/.inventory "
            + f"{playbook_name}.yaml {tags} {skip_tags} {'-vv' if self.params['debug'] else ''}",
            cwd=cwd,
            verbose=debug,
        )

    def run_all_ansible(self):
        # run ansible for isaac
        click.echo(colorize_info("* Running Ansible for Isaac Workstation..."))
        self.run_ansible(
            playbook_name="isaac-workstation",
            cwd=f"{self.config['ansible_dir']}",
        )

    def tf_output(self, key: str, default: str = ""):
        """
        Read Terraform output, preserving native types from a fresh apply snapshot.
        Other reads dispatch the saved backend in the explicitly configured state root.
        """
        self.require_backend()
        self._require_current_terraform_outputs()
        if getattr(self, '_terraform_outputs_ready', None) is True:
            return copy.deepcopy(self.tf_outputs.get(key, default))

        if key not in self.tf_outputs:
            deployment_name = self.params["deployment_name"]
            value = read_tf_output(
                deployment_name, key, verbose=self.params["debug"],
                state_dir=self.config["state_dir"],
            )
            if value == "" and self.params["debug"]:
                click.echo(
                    colorize_error(
                        f"* Warning: Terraform output '{key}' cannot be read."
                    ),
                    err=True,
                )
            self.tf_outputs[key] = value if value != "" else default

        # update meta file to reflect tf outputs
        self.save_meta()

        return self.tf_outputs[key]

    def upload_user_data(self):
        self.require_backend()
        shell_command(
            f'./upload "{self.params["deployment_name"]}" '
            + f'{"--debug" if self.params["debug"] else ""}',
            cwd=self.config["app_dir"],
            verbose=self.params["debug"],
            exit_on_error=True,
            capture_output=False,
        )

    # generate ssh connection command for the user
    def ssh_connection_command(self, ip: str):
        r = f"ssh -i state/{self.params['deployment_name']}/key.pem "
        r += f"-o StrictHostKeyChecking=no {self.config['default_ssh_user']}@{ip}"
        if self.params["ssh_port"] != 22:
            r += f" -p {self.params['ssh_port']}"
        return r

    def output_deployment_info(self, extra_text: str = "", print_text=True):
        """
        Print connection info for the user
        Save info to file (_state_dir_/_deployment_name_/info.txt)
        """

        dn = self.params["deployment_name"]
        ip = self.tf_output("isaac_workstation_ip")
        user = self.config["default_ssh_user"]
        banner = f"* Isaac Workstation is deployed at {ip} *"
        vnc_pw = self.params.get("vnc_password", "")
        sys_pw = self.params.get("system_user_password", "")

        rd_raw = str(self.params.get("remote_desktop", "standard")).lower()
        if rd_raw == "standard":
            rd_providers = ["nomachine", "novnc"]
        else:
            rd_providers = [p.strip() for p in rd_raw.split(",") if p.strip()]

        sections = [
            f"{'*' * len(banner)}",
            banner,
            f"{'*' * len(banner)}",
            "",
            "* To connect via SSH:",
            "",
            f"./ssh {dn}",
        ]

        if "novnc" in rd_providers:
            sections.extend([
                "",
                "* To connect via noVNC (opens in browser):",
                "",
                f"./novnc {dn}",
            ])

        if "nomachine" in rd_providers:
            sections.extend([
                "",
                "* To connect via NoMachine:",
                "",
                "0. Download NoMachine client at https://downloads.nomachine.com/, install and launch it.",
                '1. Click "Add" button.',
                f'2. Enter Host: "{ip}".',
                '3. In "Configuration" > "Use key-based authentication with a key you provide",',
                f'   select file "state/{dn}/key.pem".',
                '4. Click "Connect" button.',
                f'5. Enter "{user}" as a username when prompted.',
            ])

        if "kasmvnc" in rd_providers:
            sections.extend([
                "",
                "* To connect via KasmVNC (WebRTC browser access with native clipboard):",
                f"https://{ip}:8444 (VNC Password: {vnc_pw})",
            ])

        if "dcv" in rd_providers:
            sections.extend([
                "",
                "* To connect via NICE DCV:",
                f'https://{ip}:8443 (Username: "{user}", Password: "{sys_pw}")',
                f'Or connect via native NICE DCV client to "{ip}:8443".',
            ])

        if "xrdp" in rd_providers:
            sections.extend([
                "",
                "* To connect via Microsoft Remote Desktop (RDP):",
                f'Connect to "{ip}:3389" (Username: "{user}", Password: "{sys_pw}").',
            ])

        if "sunshine" in rd_providers:
            sections.extend([
                "",
                "* To connect via Moonlight (Ultra-low latency streaming):",
                f'1. Add host "{ip}" in Moonlight client.',
                f"2. Open https://{ip}:47990 in browser and enter the 4-digit pairing PIN.",
            ])

        if "parsec" in rd_providers:
            sections.extend([
                "",
                "* To connect via Parsec:",
                f'Open Parsec client and connect to host "{dn}".',
            ])

        instructions = "\n".join(sections) + "\n"

        if extra_text:
            instructions += extra_text + "\n"

        if print_text:
            click.echo(colorize_result("\n" + instructions))

        instructions_file = f"{self.config['state_dir']}/{dn}/info.txt"
        Path(instructions_file).parent.mkdir(parents=True, exist_ok=True)
        Path(instructions_file).write_text(instructions)

        return instructions
