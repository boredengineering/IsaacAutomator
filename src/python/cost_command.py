"""Explicit cost CLI, independent of deployment and cloud credentials."""
from pathlib import Path
import json
import click
from src.python import cost_estimate


@click.group()
def main():
    """Estimate selected public IaC without provisioning. Optional pinned runtime."""


def _emit(report, output_format):
    click.echo(cost_estimate.format_report(report, output_format))
    raise click.exceptions.Exit(0 if report['status'] == 'complete_within_declared_scope' else
                                3 if report['status'] == 'partial' else 2)


@main.command('estimate')
@click.option('--path', type=click.Path(path_type=Path))
@click.option('--saved-plan', type=click.Path(path_type=Path), help='Existing exported plan JSON, not deployment-bound.')
@click.option('--profile', help='Currently unsupported: profile-to-cost binding is not implemented.')
@click.option('--deployment', help='Currently unsupported: no implicit plan, cloud read or deployment lookup.')
@click.option('--usage-file', type=click.Path(path_type=Path))
@click.option('--allow-pricing', is_flag=True, help='Consent to hosted pricing and required run-parameter requests, not publication.')
@click.option('--public-input', is_flag=True, help='Attest selected IaC and usage are public/nonsecret. Private input is refused.')
@click.option('--scope', default='workstation', type=click.Choice(['workstation', 'backend', 'registry', 'backup', 'evidence']))
@click.option('--region', help='Validate input region; not a pricing override. Mixed or unresolved locations (including text HCL) cannot be asserted.')
@click.option('--timeout', default=60.0, type=click.FloatRange(min=0.01, max=600))
@click.option('--infracost-binary', default='infracost')
@click.option('--plugin-dir', type=click.Path(path_type=Path))
@click.option('--format', 'output_format', default='table', type=click.Choice(['table', 'json', 'markdown']))
def estimate_command(output_format, **options):
    """Scan a flat trusted public root or existing plan JSON; never apply/plan.

    Local/remote modules, hooks, implicit tfvars, native plans and private input
    are unsupported in this initial adapter. Missing coverage is not zero cost.
    """
    _emit(cost_estimate.estimate(**options), output_format)


@main.command('compare')
@click.option('--before', required=True, type=click.Path(path_type=Path))
@click.option('--after', required=True, type=click.Path(path_type=Path))
@click.option('--format', 'output_format', default='table', type=click.Choice(['table', 'json', 'markdown']))
def compare_command(before, after, output_format):
    """Compare two saved normalized reports locally."""
    from src.python.terraform_runner import _input_snapshot, TerraformRunnerError
    try:
        reports = [json.loads(_input_snapshot(path.absolute(), label='Cost report')) for path in (before, after)]
        report = cost_estimate.compare_reports(*reports)
    except (ValueError, OSError, KeyError, TypeError, TerraformRunnerError):
        report = cost_estimate._failure('error', 'incompatible_or_invalid_reports')
    _emit(report, output_format)


@main.command('doctor')
@click.option('--infracost-binary', default='infracost')
@click.option('--plugin-dir', type=click.Path(path_type=Path))
@click.option('--format', 'output_format', default='table', type=click.Choice(['table', 'json', 'markdown']))
def doctor_command(infracost_binary, plugin_dir, output_format):
    """Check optional runtime without installing, logging in or contacting cloud."""
    _emit(cost_estimate.doctor(infracost_binary=infracost_binary, plugin_dir=plugin_dir), output_format)


if __name__ == '__main__':
    main()
