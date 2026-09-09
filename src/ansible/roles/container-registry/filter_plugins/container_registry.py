"""Validate optional distribution input on the controller before host effects."""
import json
import re


COMPONENT = r'[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*'
REGION = r'(?!cn-)[a-z]{2}-[a-z]+-[0-9]+'
FIELDS = {
    'aws_ecr': {'account_id', 'region', 'repository'},
    'dockerhub': {'namespace', 'auth'},
    'gcp_artifact_registry': {'project', 'location', 'repository'},
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate container_registry JSON key')
        result[key] = value
    return result


def require(value, pattern, field):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('invalid container_registry.' + field)
    return value


def validate_settings(value, cloud):
    if isinstance(value, str):
        value = json.loads(value, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError('container_registry must be an object')
    enabled = value.get('enabled', False)
    if not isinstance(enabled, bool):
        raise ValueError('container_registry.enabled must be a boolean')
    provider = value.get('provider')
    if provider is not None and (not isinstance(provider, str) or provider not in FIELDS):
        raise ValueError('invalid container_registry.provider')
    allowed = {'enabled', 'provider', 'images'} | (FIELDS[provider] if provider else set())
    if set(value) - allowed:
        raise ValueError('unsupported container_registry fields')
    if not enabled:
        return {'enabled': False}
    result = dict(value)
    if provider == 'aws_ecr':
        if cloud != 'aws':
            raise ValueError('aws_ecr requires cloud aws')
        account = require(value.get('account_id'), r'[0-9]{12}', 'account_id')
        region = require(value.get('region'), REGION, 'region')
        repository = require(value.get('repository'), r'[a-z0-9]+(?:[._/-][a-z0-9]+)*', 'repository')
        if not 2 <= len(repository) <= 256:
            raise ValueError('invalid container_registry.repository length')
        host = account + '.dkr.ecr.' + region + '.amazonaws.com'
        image_pattern = re.escape(host + '/' + repository)
    elif provider == 'dockerhub':
        namespace = require(value.get('namespace'), r'[a-z0-9][a-z0-9_-]{1,254}', 'namespace')
        auth = value.get('auth', 'anonymous')
        if auth not in ('anonymous', 'existing'):
            raise ValueError('invalid container_registry.auth')
        result['auth'] = auth
        host = 'docker.io'
        image_pattern = re.escape(host + '/' + namespace + '/') + COMPONENT
    elif provider == 'gcp_artifact_registry':
        if cloud != 'gcp':
            raise ValueError('gcp_artifact_registry requires cloud gcp')
        project = require(value.get('project'), r'[a-z][a-z0-9-]{4,28}[a-z0-9]', 'project')
        location = require(value.get('location'), r'[a-z]+-[a-z]+[0-9]+', 'location')
        repository = require(value.get('repository'), r'[a-z][a-z0-9_-]{0,62}', 'repository')
        host = location + '-docker.pkg.dev'
        image_pattern = re.escape(host + '/' + project + '/' + repository + '/') + COMPONENT + rf'(?:/{COMPONENT})*'
    else:
        raise ValueError('container_registry.provider is required')
    images = value.get('images', {})
    if not isinstance(images, dict):
        raise ValueError('container_registry.images must be an object')
    for name, image in images.items():
        require(name, r'[a-z][a-z0-9_-]*', 'images workload')
        require(image, image_pattern + r'@sha256:[0-9a-f]{64}', 'images digest')
    result.update(registry=host, images=dict(images))
    return result


class FilterModule:
    def filters(self):
        return {'container_registry_settings': validate_settings}
