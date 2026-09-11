"""Reviewed workstation Terraform source allowlists.

Only these repository-controlled files are executable deployment inputs. Never
expand this list by globbing a working tree: it may contain credentials, state,
backend overrides, auto-loaded variables and downloaded modules. Module paths
are relative to each cloud root and must retain their topology. Changes to
Terraform source topology require explicit review of this manifest. Registry
and bootstrap roots have separate lifecycle ownership and are not included.
"""
from types import MappingProxyType


_WORKSTATION_FILES = MappingProxyType({
    'aws': (
        'main.tf', 'variables.tf', 'outputs.tf', 'ecr_variables.tf', 'ecr_outputs.tf',
        'common/main.tf', 'common/variables.tf', 'common/outputs.tf',
        'vpc/main.tf', 'vpc/variables.tf', 'vpc/outputs.tf',
        'isaac-workstation/main.tf', 'isaac-workstation/variables.tf',
        'isaac-workstation/outputs.tf', 'isaac-workstation/versions.tf',
        'isaac-workstation/ami.tf', 'isaac-workstation/security.tf',
        'isaac-workstation/ecr.tf', 'isaac-workstation/ecr_variables.tf',
        'isaac-workstation/ecr_outputs.tf',
    ),
    'gcp': (
        'main.tf', 'variables.tf', 'outputs.tf', 'common.tf', 'kms.tf', 'secrets.tf',
        'artifact_registry.tf', 'artifact_registry_variables.tf',
        'ovkit/main.tf', 'ovkit/variables.tf', 'ovkit/outputs.tf', 'ovkit/security.tf',
        'ovkit/artifact_registry.tf', 'ovkit/artifact_registry_variables.tf',
    ),
    'azure': (
        'main.tf', 'variables.tf', 'outputs.tf',
        'common/main.tf', 'common/variables.tf', 'common/outputs.tf',
        'isaac-workstation/main.tf', 'isaac-workstation/variables.tf',
        'isaac-workstation/outputs.tf', 'isaac-workstation/security.tf',
    ),
    'alicloud': (
        'main.tf', 'variables.tf', 'outputs.tf',
        'common/main.tf', 'common/variables.tf', 'common/outputs.tf',
        'ovkit/main.tf', 'ovkit/variables.tf', 'ovkit/outputs.tf', 'ovkit/security.tf',
    ),
})


def workstation_source_files(cloud):
    """Return an immutable explicit allowlist; no filesystem discovery."""
    try:
        return _WORKSTATION_FILES[cloud]
    except (KeyError, TypeError):
        raise ValueError('No reviewed Terraform workstation source manifest for this cloud') from None
