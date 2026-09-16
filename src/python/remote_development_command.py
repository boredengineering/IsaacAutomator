"""Offline plan/render CLI. No transfer, service or discovery commands."""
import json
from pathlib import Path

import click
from src.python.remote_development import build_plan, render_candidate


def _load_spec(path, *, desired_profile=False):
    """Read one selected regular JSON file, bounded and no-follow throughout."""
    import os
    import stat
    selected = Path(path).absolute()
    if '..' in selected.parts:
        raise ValueError('Parent traversal is not supported')
    parent_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in selected.parent.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(selected.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1048576:
            raise ValueError('Selection must be a regular JSON file of at most 1 MiB')
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('Selection exceeds 1 MiB')
    if desired_profile:
        from src.python.workstation_profile import parse_profile_text
        return parse_profile_text(raw)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate selection key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, RecursionError):
        raise ValueError('Invalid JSON selection') from None


def _selection(spec, desired_profile):
    result = _load_spec(spec)
    if desired_profile is not None:
        if not isinstance(result, dict) or 'desired_profile' in result:
            raise ValueError('Select shared desired profile once, not twice')
        result['desired_profile'] = _load_spec(desired_profile, desired_profile=True)
    return result


@click.group(name='remote-development')
def remote_development():
    """Review explicit source/artifact synchronization; never activate it."""


@remote_development.command('plan')
@click.option('--spec', required=True, type=click.Path(dir_okay=False))
@click.option('--desired-profile', type=click.Path(dir_okay=False), help='Explicit shared desired YAML; no discovery or preset reads.')
def plan_command(spec, desired_profile):
    """Read only selections; print lexical paths/runtime intent, not target preflight."""
    try:
        click.echo(json.dumps(build_plan(_selection(spec, desired_profile)), indent=2, sort_keys=True))
    except (ValueError, OSError):
        raise click.ClickException('Invalid or unsafe development selection; no transfer was run.') from None


@remote_development.command('render')
@click.option('--spec', required=True, type=click.Path(dir_okay=False))
@click.option('--desired-profile', type=click.Path(dir_okay=False), help='Explicit shared desired YAML; no runtime activation.')
@click.option('--output-dir', required=True, type=click.Path(file_okay=False))
@click.option('--reviewed', is_flag=True, help='Confirm review of the selected candidate output, not activation.')
def render_command(spec, desired_profile, output_dir, reviewed):
    """Write candidate files ONLY to a new explicit directory; no settings edits."""
    try:
        result = render_candidate(_selection(spec, desired_profile), output_dir, reviewed=reviewed)
        click.echo(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, OSError):
        raise click.ClickException('Render refused: require reviewed selection and a new safe output directory; no activation occurred.') from None


main = remote_development

if __name__ == '__main__':
    remote_development()
