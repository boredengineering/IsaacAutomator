"""Offline backend input parsing and selection; never performs cloud actions."""
from click.core import ParameterSource
import os
import yaml

from src.python.terraform_backend import BackendSpec


class BackendSelectionError(ValueError):
    """Safe-to-display backend configuration error, without input values."""


class _UniqueLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise BackendSelectionError("Backend configuration aliases are forbidden")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag == 'tag:yaml.org,2002:merge':
                raise BackendSelectionError("Backend configuration merges are forbidden")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise BackendSelectionError("Duplicate or invalid configuration field")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_profile_yaml(path):
    """Read one bounded YAML/JSON mapping; duplicates/aliases/merges fail closed."""
    try:
        if not os.path.isfile(path):
            raise BackendSelectionError("Configuration must be a readable regular file")
        with open(path, 'rb') as stream:
            content = stream.read(65537)
        if len(content) > 65536:
            raise BackendSelectionError("Configuration exceeds the 64 KiB limit")
        data = yaml.load(content.decode('utf-8'), Loader=_UniqueLoader)
        if not isinstance(data, dict):
            raise BackendSelectionError("Configuration must be a mapping")
        return data
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError):
        raise BackendSelectionError("Cannot read or parse configuration file") from None


def load_backend_config(path):
    """Return a validated raw bare block from a standalone YAML/JSON file.

    A sole terraform_state wrapper is also accepted. Actual deployment cloud
    pairing must still be checked by BackendSpec.from_dict(data, cloud=...).
    """
    data = load_profile_yaml(path)
    if 'terraform_state' in data:
        if set(data) != {'terraform_state'}:
            raise BackendSelectionError("Standalone backend wrapper must be the only field")
        data = data['terraform_state']
    if not isinstance(data, dict):
        raise BackendSelectionError("terraform_state must be a mapping")
    cloud = {'local': 'aws', 's3': 'aws', 'gcs': 'gcp', 'azurerm': 'azure'}.get(
        data.get('backend') if isinstance(data.get('backend'), str) else None, 'aws')
    try:
        BackendSpec.from_dict(data, cloud=cloud)
    except ValueError:
        raise BackendSelectionError("Invalid backend configuration; check schema, fields and credential restrictions") from None
    return data


def normalize_profile_backend(data):
    """Normalize only explicit profile intent; legacy inspection stays possible."""
    if 'terraform_state' not in data:
        return {}
    block = data['terraform_state']
    if not isinstance(block, dict):
        raise BackendSelectionError("terraform_state must be a mapping")
    backend = block.get('backend', 'local')
    inferred = {'local': 'aws', 'gcs': 'gcp', 's3': 'aws', 'azurerm': 'azure'}
    cloud = data.get('cloud') or (inferred.get(backend) if isinstance(backend, str) else None)
    try:
        return {'terraform_state': BackendSpec.from_dict(block, cloud=cloud).to_dict()}
    except ValueError:
        raise BackendSelectionError("Invalid profile terraform_state configuration") from None


def select_backend(params, profile, cloud, ctx=None):
    """Resolve NEW intent, not saved attachment identity.

    Command line/prompt > environment > Click default-map > profile > local.
    Click DEFAULT is never opt-in. Programmatic nonempty inputs are explicit.
    Same-level choices must agree; destinations never merge across levels.
    """
    ranks = {ParameterSource.COMMANDLINE: 4, ParameterSource.PROMPT: 4,
             ParameterSource.ENVIRONMENT: 3, ParameterSource.DEFAULT_MAP: 2}
    inputs = []
    for key in ('state_backend', 'backend_config', 'state_bucket'):
        value = params.get(key)
        rank = ranks.get(ctx.get_parameter_source(key), 0) if ctx else 4
        if value and rank:
            inputs.append((rank, key, value))
    if ctx is None and not params.get('state_bucket') and os.environ.get('ISAAC_STATE_BUCKET'):
        inputs.append((3, 'state_bucket', os.environ['ISAAC_STATE_BUCKET']))
    if inputs:
        rank = max(item[0] for item in inputs)
        chosen = {key: value for level, key, value in inputs if level == rank}
        data = load_backend_config(chosen['backend_config']) if 'backend_config' in chosen else None
        backend = chosen.get('state_backend')
        if data is not None and backend and data.get('backend', 'local') != backend:
            raise BackendSelectionError("Conflicting backend choices at the same precedence level")
        if chosen.get('state_bucket'):
            if data is not None or backend:
                raise BackendSelectionError("Conflicting legacy and explicit backend choices")
            raise BackendSelectionError("Legacy remote state is not implemented safely; GCP-only compatibility requires verified attachment/migration support")
        if data is None:
            data = {'backend': backend}
    else:
        data = profile.get('terraform_state')
        storage = profile.get('raw', {}).get('security', {}).get('storage', {})
        legacy = profile.get('state_bucket') or storage.get('state_bucket') or storage.get('state_backend') not in (None, '', 'local')
        if legacy:
            if data is not None:
                raise BackendSelectionError("Conflicting legacy and explicit profile backend choices")
            raise BackendSelectionError("Legacy remote state is not implemented safely; GCP-only compatibility requires verified attachment/migration support")
    try:
        return BackendSpec.from_dict(data, cloud=cloud)
    except ValueError:
        raise BackendSelectionError("Invalid backend configuration or cloud pairing; remote lifecycle is not implemented safely") from None
