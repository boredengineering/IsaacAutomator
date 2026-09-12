"""Read-only workstation software-profile commands, independent of cloud setup."""
import json

import click


@click.group()
def main():
    """Inspect software profiles offline; this does not deploy or install.

    Use list, validate and resolve to inspect proposed software intent.
    """


@main.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit the public preset names as JSON.")
def list_command(as_json):
    """List public software presets; never discover private host baselines."""
    from src.python import workstation_profile

    names = workstation_profile.list_profiles()
    click.echo(json.dumps(names) if as_json else "\n".join(names))


@main.command("validate")
@click.argument("profile")
def validate_command(profile):
    """Validate desired software intent; success is not runtime acceptance."""
    from src.python import workstation_profile

    try:
        workstation_profile.resolve_profile(profile)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(json.dumps({
        "status": "valid-profile", "cloud_access": "not_checked",
        "runtime": "not_verified", "deployment": "not_performed",
    }, sort_keys=True))


@main.command("resolve")
@click.argument("profile")
@click.option("--disable", multiple=True,
              type=click.Choice(["sim", "lab", "arena", "gr00t", "lerobot"]),
              help="Disable a component in this resolution only; repeat as needed.")
@click.option("--enable", multiple=True,
              type=click.Choice(["sim", "lab", "arena", "gr00t", "lerobot"]),
              help="Enable a component in this resolution only; dependencies must be selected.")
def resolve_command(profile, disable, enable):
    """Emit resolved intent as JSON, retaining unresolved pins and adapter gaps."""
    from src.python import workstation_profile

    if set(disable) & set(enable):
        raise click.UsageError("A component cannot be both enabled and disabled.")
    try:
        components = {name: {"enabled": False} for name in disable}
        components.update({name: {"enabled": True} for name in enable})
        overrides = {"components": components} if components else None
        manifest = workstation_profile.resolve_profile(profile, overrides=overrides)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(json.dumps(manifest, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
