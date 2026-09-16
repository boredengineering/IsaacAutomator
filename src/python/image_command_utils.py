"""Local image previews and protected Packer command transport."""
import json
import os
import shlex
import subprocess
import tempfile
import sys
import runpy
from pathlib import Path

import click

from src.python.deploy_command import DeployCommand


class ImageCommand(DeployCommand):
    """Image-only shared intent parsing; legacy deploy parsing stays untouched."""

    def get_params(self, ctx):
        # Profiles transport repositories through the Ansible JSON file, not
        # independently overridable legacy repository flags.
        return [param for param in click.Command.get_params(self, ctx)
                if param.name not in {name + '_repo' for name in self._APP_NAMES}]

    def parse_args(self, ctx, args):
        if ctx.resilient_parsing or '--help' in args:
            return click.Command.parse_args(self, ctx, args)
        opts, _, _ = self.make_parser(ctx).parse_args(args=list(args))
        source = opts.get('software_profile')
        if source is None:
            return super().parse_args(ctx, args)
        conflicts = set(self._APP_NAMES) | {'isaaclab_private_git', 'demos'}
        if conflicts.intersection(opts):
            raise click.UsageError('Software profiles cannot combine with component/ref, private repository or demo overrides.')
        if opts.get('ssh_user', 'ubuntu') != 'ubuntu':
            raise click.UsageError('Software profiles cannot combine with another SSH user; image templates use ubuntu.')
        from src.python.workstation_profile import resolve_profile
        try:
            document = resolve_profile(source)['profile']
            report = image_profile_report({**opts, 'software_profile': document})
        except (ValueError, OSError) as exc:
            raise click.BadParameter(str(exc), param_hint='--software-profile') from None
        ctx.meta['software_profile_document'] = document
        ctx.meta['software_profile_source'] = source
        if not opts.get('dry_run'):
            for component, value in document.get('components', {}).items():
                selection = value.get('source', {})
                if value.get('enabled') and selection.get('mode') == 'git':
                    resolved = self._check_git_selection(
                        ctx, click.Option(('--' + component,)),
                        selection.get('revision') or selection['ref'],
                        selection['repository'], lambda message: None)
                    if not selection.get('revision'):
                        selection['ref'] = resolved
            report = image_profile_report({'software_profile': document})
        args = list(args)
        for name in self._APP_NAMES:
            args.extend(['--' + name.replace('_', '-'), report['deploy_params'][name]])
        # Skip legacy callbacks, whose repository defaults do not describe the
        # profile. Selected source pairs were preflighted above (except dry-run).
        return click.Command.parse_args(self, ctx, args)


def image_profile_report(params):
    """Render for the fixed ubuntu image user, before any cloud effects."""
    if params.get('software_profile') is None:
        return None
    from src.python.profile_adapters import render_profile
    report = render_profile(params['software_profile'], 'packer', '/home/ubuntu')
    if not report['render_supported']:
        raise ValueError('Software profile has required unmapped fields; inspect software-profile render coverage.')
    expected = {**report['deploy_params'], 'install_gr00t': report['artifact']['install_gr00t']}
    if (any(name in params and params[name] != value for name, value in expected.items())
            or DeployCommand.demos_callback(None, None, params.get('demos')) != 'no'
            or params.get('isaaclab_private_git')
            or params.get('ssh_user', 'ubuntu') != 'ubuntu'):
        raise ValueError('Software profiles cannot combine with conflicting source, demo or image-user overrides.')
    return report


def forward_image_command(entrypoint, image_command=None):
    """Use the existing /app bind mount, never shell/OS argv for user arguments.

    __* is excluded by both .gitignore and .dockerignore, including a first-run
    Docker build. The short-lived directory is owner-only, not persistent state.
    """
    root = Path(entrypoint).resolve().parent
    try:
        with tempfile.TemporaryDirectory(prefix="__isaac-image-", dir=root) as directory:
            arguments = list(sys.argv[1:])
            if image_command is not None:
                # Use the actual command parser, not substring matching (a
                # password or other option value may itself resemble a flag).
                with click.Context(image_command) as ctx:
                    options, positional, _ = image_command.make_parser(ctx).parse_args(list(arguments))
                    parameters = {p.name: p for p in image_command.get_params(ctx)}
                source = options.get('software_profile')
                if source is not None:
                    from src.python.workstation_profile import resolve_profile
                    document = resolve_profile(source)['profile']
                    image_profile_report({'software_profile': document})
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.yaml',
                                                     dir=directory, delete=False) as profile_stream:
                        # JSON is a YAML subset accepted by the shared reader;
                        # fully resolved intent needs no host-only parent paths.
                        json.dump(document, profile_stream)
                        options['software_profile'] = str(Path('/app') / Path(profile_stream.name).relative_to(root))
                    arguments = list(positional)
                    for name, value in options.items():
                        parameter = parameters[name]
                        if parameter.is_flag:
                            arguments.append((parameter.opts if value else parameter.secondary_opts)[0])
                        else:
                            for item in (value if parameter.multiple else [value]):
                                arguments.extend([parameter.opts[0], str(item)])
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json",
                                             dir=directory, delete=False) as stream:
                json.dump([Path(entrypoint).name, *arguments], stream)
                relative = Path(stream.name).relative_to(root)
            command = shlex.join(["python3", "-m", "src.python.image_command_utils",
                                  str(Path("/app") / relative)])
            result = subprocess.run([str(root / "run"), command], cwd=root)
            return result.returncode
    except OSError:
        click.echo("Unable to route image build. Use a writable checkout and a local Docker "
                   "daemon, or run image-* inside the Automator container.", err=True)
        return 1


def invoke_image_file(path):
    """Container-side reader: restore Python arguments without exec/secret argv."""
    path = Path(path)
    with path.open(encoding="utf-8") as stream:
        argv = json.load(stream)
    path.unlink()
    if (not isinstance(argv, list) or not argv or
            not all(isinstance(value, str) for value in argv) or
            argv[0] not in ("image-gcp", "image-aws", "image-azure")):
        raise click.ClickException("Invalid image invocation file.")
    previous = sys.argv
    try:
        sys.argv = argv
        runpy.run_path(str(Path(__file__).resolve().parents[2] / argv[0]), run_name="__main__")
    finally:
        sys.argv = previous


def local_image_mode(command):
    """Inspect Click's tokens without callbacks, prompts or cloud defaults."""
    with click.Context(command) as ctx:
        try:
            options, _, _ = command.make_parser(ctx).parse_args(sys.argv[1:])
        except click.ClickException:
            # Let the local CLI explain malformed options, never start Docker.
            return True
    return bool(options.get("dry_run") or options.get("help"))


def configure_image_preview(command):
    """Eagerly parse preview before any remote-ref/default callbacks (image only)."""
    for param in command.params:
        if param.name == "dry_run":
            param.is_eager = True
            param.help = "Local rendering-only preview; no authentication, plugins or build. Not validation."
        elif param.name in ("isaacsim", "isaaclab", "isaaclab_arena"):
            original = param.callback
            def callback(ctx, option, value, original=original):
                if ctx.params.get("dry_run", False) or ctx.meta.get("software_profile_document") is not None:
                    return value
                return original(ctx, option, value)
            param.callback = callback


def preview_image_build(provider, params, version):
    """Render selected inputs only; no credential, plugin or cloud inspection."""
    fields = (
        "image_name", "existing", "project", "zone", "region", "resource_group",
        "isaac_workstation_instance_type", "gpu_type", "gpu_count", "isaacsim",
        "isaaclab", "isaaclab_arena", "demos", "install_gr00t", "enable_neo4j",
    )
    preview = {
        "status": "rendering-only",
        "provider": provider,
        "version": version,
        "inputs": {key: params[key] for key in fields if key in params},
        "system_user_password": "<redacted>",
    }
    report = image_profile_report(params)
    if report is not None:
        preview["software_profile"] = report
    click.echo(json.dumps(preview, indent=2, sort_keys=True))
    click.echo(
        "Dry-run rendering-only: Packer and Ansible not validated; "
        "no authentication, image deletion, resource creation, plugin initialization "
        "or build performed. Cloud availability and permissions are not checked."
    )
    return preview


def run_packer_build(template, variables, *, debug=False, env=None, force=False, software_profile_vars=None):
    """Keep variable values out of shell/child argv and remove the private file."""
    environment = os.environ.copy()
    environment.update(env or {})
    # Packer's raw trace file bypasses our output redaction, even without --debug.
    environment["PACKER_LOG"] = "0"
    environment.pop("PACKER_LOG_PATH", None)
    secrets = [str(value) for key, value in variables.items() if "password" in key and value]
    secrets.extend(value for key, value in environment.items()
                   if value and any(word in key.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "ACCESS_KEY")))

    def redact(text):
        text = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else (text or "")
        forms = {form for value in secrets for form in (
            value, json.dumps(value)[1:-1], shlex.quote(value)
        )}
        for secret in sorted(forms, key=len, reverse=True):
            text = text.replace(secret, "<redacted>")
        return text

    with tempfile.TemporaryDirectory(prefix="isaac-packer-") as directory:
        # Every existing provider HCL passes this file LAST to the same Ansible
        # playbook, so profile variables override legacy software/path defaults.
        # It survives the entire provisioning process; no values enter argv.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".ansible.json",
                                         dir=directory, delete=False) as stream:
            json.dump({**(software_profile_vars or {}),
                       **{key: variables.get(key, "") for key in
                          ("system_user_password", "vnc_password")}}, stream)
            variables = {**variables, "ansible_secret_vars_file": stream.name}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".pkrvars.json",
                                         dir=directory, delete=False) as stream:
            json.dump(variables, stream)
            variable_file = stream.name
        commands = [
            ["packer", "init", str(template)],
            ["packer", "build", *(["-force"] if force else []),
             f"-var-file={variable_file}", str(template)],
        ]
        for argv in commands:
            click.echo(f"* Packer {argv[1]}...")
            if debug:
                click.echo(f"* Command: {shlex.join(argv)}")
            try:
                result = subprocess.run(argv, env=environment, capture_output=True, text=True)
            except OSError:
                raise click.ClickException(f"Unable to start Packer {argv[1]}.") from None
            if result.stdout:
                click.echo(redact(result.stdout), nl=False)
            if result.stderr:
                click.echo(redact(result.stderr), err=True, nl=False)
            if result.returncode != 0:
                raise click.ClickException(
                    f"Packer {argv[1]} failed (exit {result.returncode}); image build not complete."
                )


if __name__ == "__main__":
    invoke_image_file(sys.argv[1])
