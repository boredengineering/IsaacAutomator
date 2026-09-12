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


def forward_image_command(entrypoint):
    """Use the existing /app bind mount, never shell/OS argv for user arguments.

    __* is excluded by both .gitignore and .dockerignore, including a first-run
    Docker build. The short-lived directory is owner-only, not persistent state.
    """
    root = Path(entrypoint).resolve().parent
    try:
        with tempfile.TemporaryDirectory(prefix="__isaac-image-", dir=root) as directory:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json",
                                             dir=directory, delete=False) as stream:
                json.dump([Path(entrypoint).name, *sys.argv[1:]], stream)
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
                if ctx.params.get("dry_run", False):
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
    click.echo(json.dumps(preview, indent=2, sort_keys=True))
    click.echo(
        "Dry-run rendering-only: Packer and Ansible not validated; "
        "no authentication, image deletion, resource creation, plugin initialization "
        "or build performed. Cloud availability and permissions are not checked."
    )
    return preview


def run_packer_build(template, variables, *, debug=False, env=None, force=False):
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
        # Ansible runs on the controller, so this file must survive the entire
        # Packer provisioning process. Never interpolate passwords into its argv.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".ansible.json",
                                         dir=directory, delete=False) as stream:
            json.dump({key: variables.get(key, "") for key in
                       ("system_user_password", "vnc_password")}, stream)
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
