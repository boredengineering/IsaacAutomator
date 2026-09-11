"""Explicit drift commands; offline generation does not activate automation."""
import json
from pathlib import Path
import click

from src.python.backend_selection import load_profile_yaml
from src.python import drift_workflow


@click.group()
def main():
    """Inspect drift and explicitly configure opt-in automation."""


@main.group()
def workflow():
    """Generate inactive, report-only GitHub Actions templates."""


def _workflow_config(path):
    try:
        return drift_workflow.WorkflowConfig.from_dict(load_profile_yaml(path))
    except ValueError:
        raise click.ClickException("Invalid workflow configuration; check schema and approved nonsecret identity/pins") from None


@workflow.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output-dir", default=str(drift_workflow.DEFAULT_OUTPUT), type=click.Path(file_okay=False, path_type=Path))
def generate(config_path, output_dir):
    """Write inert files outside .github; never overwrite conflicting content."""
    config = _workflow_config(config_path)
    try:
        files = drift_workflow.generate(config, output_dir)
    except (ValueError, OSError):
        raise click.ClickException("Workflow generation refused; verify output safety and rendered validation") from None
    click.echo(json.dumps({"status": "generated-inactive", "files": sorted(str(path) for path in files),
                           "setup_status": "UNVERIFIED", "remote_activation": False}, sort_keys=True))


@workflow.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def preview(config_path):
    """Render and validate without writing files or inspecting remote setup."""
    config = _workflow_config(config_path)
    try:
        report = drift_workflow.preview(config)
    except (ValueError, OSError):
        raise click.ClickException("Workflow preview validation failed") from None
    click.echo(json.dumps(report, sort_keys=True))


@main.command('check')
@click.argument('deployment', required=False)
@click.option('--config', 'config_path', required=True, type=click.Path(path_type=Path))
@click.option('--scope', default=None)
@click.option('--format', 'output_format', default='json')
@click.option('--report-dir', default=None, type=click.Path(path_type=Path))
def check_command(config_path, deployment, scope, output_format, report_dir):
    """Plan against a verified applied local recipe; never apply."""
    from src.python.drift_runtime import RuntimeConfig, check
    from src.python.drift_report import wrapper_exit_code
    try:
        config = RuntimeConfig.load(config_path)
        if deployment not in (None, config.deployment) or scope not in (None, config.scope) or output_format != 'json':
            raise ValueError()
        if report_dir is not None:
            # Explicit CLI approval may supply the dedicated report destination;
            # it must not silently replace a conflicting configured destination.
            from dataclasses import replace
            from src.python.drift_runtime import _path
            approved = _path(str(report_dir))
            if config.report_root not in (None, approved):
                raise ValueError()
            config = replace(config, report_root=approved)
        report = check(config)
    except (ValueError, OSError):
        report = {'schema_version': 1, 'classes': ['error'],
                  'error': 'invalid_runtime_configuration_or_report_store'}
    click.echo(json.dumps(report, sort_keys=True))
    raise click.exceptions.Exit(wrapper_exit_code(report))


if __name__ == "__main__":
    main()
