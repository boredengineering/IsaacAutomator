"""Explicit opt-in backend commands. No implicit login or provisioning."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import click

from src.python.backend_selection import load_backend_config
from src.python.terraform_backend import BackendSpec, validate_terraform_version


@click.group()
def main():
    """Explicit backend validation and setup; workstation lifecycle is separate."""


@main.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--cloud", required=True, type=click.Choice(["aws", "gcp", "azure", "alicloud"]))
@click.option("--terraform-version", help="Check a supplied version string; does not execute Terraform.")
def validate(config_path, cloud, terraform_version):
    """Check YAML/JSON schema and cloud pairing without executing anything."""
    try:
        spec = BackendSpec.from_dict(load_backend_config(config_path), cloud=cloud)
        if terraform_version is not None:
            validate_terraform_version(terraform_version, spec.backend)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    canonical = json.dumps({"cloud": cloud, "terraform_state": spec.to_dict()},
                           sort_keys=True, separators=(",", ":"))
    click.echo(json.dumps({
        "status": "valid-config", "backend": spec.backend, "cloud": cloud,
        "configuration_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "cloud_access": "not_checked", "terraform_version": terraform_version or "not_checked",
        "remote_lifecycle": "not_checked",
    }, sort_keys=True))


@main.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--cloud", required=True, type=click.Choice(["aws", "gcp", "azure"]))
@click.option("--acknowledge-reads", is_flag=True, help="Authorize authenticated read-only cloud inspection.")
@click.option("--workload-resource-group", multiple=True, help="Azure workload groups excluded from backend ownership.")
def doctor(config_path, cloud, acknowledge_reads, workload_resource_group):
    """Inspect existing storage without login, writes or automatic repair.

    Exit 2 means incomplete/noncompliant evidence, never production readiness.
    Effective lock/write/restore permissions require separate verification.
    """
    if not acknowledge_reads:
        raise click.ClickException("Authenticated inspection requires --acknowledge-reads")
    from src.python.backend_bootstrap import doctor as inspect_backend
    try:
        spec = BackendSpec.from_dict(load_backend_config(config_path), cloud=cloud)
        report = inspect_backend(spec, acknowledge_reads=True,
                                 workload_resource_groups=workload_resource_group)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(json.dumps(asdict(report), sort_keys=True))
    if report.status != "verified":
        raise click.exceptions.Exit(2)


@main.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--cloud", required=True, type=click.Choice(["aws", "gcp", "azure"]))
@click.option("--bootstrap-state-root", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Absolute durable admin state root, separate from workstation state.")
@click.option("--region", required=True)
@click.option("--controller-principal", required=True, help="Nonsecret backend-controller principal identifier.")
@click.option("--workload-resource-group", multiple=True)
@click.option("--acknowledge-reads", is_flag=True)
@click.option("--apply", "apply_requested", is_flag=True, help="Create billable independent backend infrastructure.")
@click.option("--approve-creation", is_flag=True, help="Explicitly approve create-new storage/IAM for this configuration.")
def bootstrap(config_path, cloud, bootstrap_state_root, region, controller_principal,
              workload_resource_group, acknowledge_reads, apply_requested, approve_creation):
    """Plan create-new backend storage; use doctor for externally owned storage.

    Apply requires both explicit flags. Each invocation plans afresh: a preview
    digest is not a reusable approval or a persistent saved-plan reference.
    Workstation teardown does not destroy this protected admin stack.
    """
    if not acknowledge_reads:
        raise click.ClickException("Bootstrap planning requires --acknowledge-reads")
    if apply_requested != approve_creation:
        raise click.ClickException("Backend creation requires both --apply and --approve-creation")
    if not bootstrap_state_root.is_absolute():
        raise click.ClickException("Bootstrap state requires an absolute durable admin root")
    from src.python.backend_bootstrap import BootstrapSession, InspectionError
    from src.python.terraform_runner import TerraformRunnerError
    session = None
    try:
        spec = BackendSpec.from_dict(load_backend_config(config_path), cloud=cloud)
        session = BootstrapSession(spec, bootstrap_state_root=bootstrap_state_root,
                                   region=region, controller_principal=controller_principal,
                                   workload_resource_groups=workload_resource_group, acknowledge_reads=True)
        with session as active:
            plan = active.plan()
            click.echo(json.dumps({"status": "bootstrap-planned", "backend": spec.backend,
                                   "configuration": spec.to_dict(), "plan_sha256": plan.digest,
                                   "has_changes": plan.has_changes,
                                   "cost_boundary": "Independent protected storage and IAM; storage can incur charges",
                                   "plan_retained": False}, sort_keys=True))
            if apply_requested:
                active.apply(plan, acknowledge_creation=True)
                click.echo(json.dumps({"status": "bootstrap-applied", "backend": spec.backend,
                                       "workstation_created": False, "data_plane_acceptance": "not_verified"}, sort_keys=True))
    except (ValueError, TerraformRunnerError, InspectionError) as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        if session is not None and session.runner.recovery_directory is not None:
            click.echo("Private bootstrap recovery retained at " + str(session.runner.recovery_directory)
                       + "; secure it before reboot and review manually before retrying.", err=True)


@main.command()
@click.option("--cloud", required=True, type=click.Choice(["aws", "gcp", "azure"]))
@click.option("--namespace", required=True)
@click.option("--owner-scope", required=True, help="Backend owner account, project or subscription identifier.")
@click.option("--region", help="S3 region only; GCP/Azure location is selected separately during bootstrap.")
@click.option("--tenant-id", help="Azure tenant identifier only.")
def propose(cloud, namespace, owner_scope, region, tenant_id):
    """Emit deterministic config for review, without checking or creating storage.

    A name may already be occupied. Use doctor/bootstrap explicitly afterward;
    a different proposal never migrates an existing deployment's state.
    """
    from src.python.backend_proposal import propose_backend
    try:
        result = propose_backend(cloud=cloud, namespace=namespace, owner_scope=owner_scope,
                                 region=region, tenant_id=tenant_id)
    except (ValueError, TypeError):
        raise click.ClickException("Invalid nonsecret proposal identity for the selected cloud") from None
    click.echo(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
