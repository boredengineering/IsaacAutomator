"""Pure reviewed discovery -> existing workstation-profile YAML bridge.

Import before confinement. Functions never read presets, inspect targets or
write output. Profile approval is never authorization to execute.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path
import yaml


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError('Trusted profile module unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CORE = Path(__file__).resolve().parent
_discovery = _load('desired_discovery', _CORE / 'profile_discovery.py')
_shared = _load('desired_workstation', _CORE.parents[2] / 'src/python/workstation_profile.py')


def export_candidate(baseline, candidate, *, name='reviewed-workstation'):
    """Return loadable draft, decision/coverage review and completeness flag."""
    _discovery.build_review(baseline, candidate)  # Strict companion validation.
    profile = {'schema_version': 'v1alpha1', 'kind': 'workstation-profile',
               'name': name, 'target': 'offline', 'defaults': False, 'draft': True}
    gaps, coverage = [], []
    workspace_scopes = {f['id'].rsplit('.', 1)[0] for f in candidate['fields']
                        if f['id'].startswith('workspace:') and f['state'] == 'accepted'}
    ambiguous_workspace = len(workspace_scopes) > 1
    selected_components = next((set(f['value']) for f in candidate['fields']
                               if f['id'] == 'components.selection' and f['state'] == 'accepted'), set())
    required_bindings = {'component:' + name + '.source' for name in selected_components}
    required_bindings.update('runtime:' + _shared.COMPONENT_RUNTIME[name] for name in selected_components)
    required_bindings.update('component:' + name + '.execution' for name in selected_components)
    observations = {item['id']: item for item in baseline['observations']}
    fields_by_id = {field['id']: field for field in candidate['fields']}
    native_runtimes, placement_fields = set(), set()
    for field in candidate['fields']:
        if not field['id'].startswith('runtime:') or field['state'] != 'accepted':
            continue
        for evidence_id in field['evidence']:
            environment = fields_by_id.get(evidence_id)
            if environment is not None and environment['state'] == 'accepted':
                value = environment['value']
                if (value.get('placement') in ('host', 'environment', 'project')
                        and value.get('name') == field['value']['environment']
                        and value.get('manager') == field['value']['manager']):
                    native_runtimes.add(field['id'].split(':', 1)[1])
                    if field['id'] in required_bindings:
                        placement_fields.add(evidence_id)
    for field in candidate['fields']:
        identifier = field['id']
        required_field = field['required'] or identifier in required_bindings
        if field['state'] == 'accepted' and (field['evidence_changed'] or field['not_selected']):
            gaps.append({'field_id': identifier, 'reason': 'evidence_changed_review_required',
                         'required': required_field or identifier in placement_fields})
        status = 'excluded' if field['state'] == 'rejected' else 'unresolved'
        if field['state'] == 'accepted':
            if identifier.startswith('workspace:'):
                if ambiguous_workspace:
                    gaps.append({'field_id': identifier, 'reason': 'multiple_workspace_scopes',
                                 'required': required_field})
                    status = 'conflicting'
                elif identifier.endswith('.layout') and field['value'] == 'legacy':
                    gaps.append({'field_id': identifier, 'reason': 'legacy_layout_requires_reviewed_migration',
                                 'required': required_field})
                    status = 'unsupported'
                else:
                    profile.setdefault('workspace', {})[identifier.rsplit('.', 1)[1]] = deepcopy(field['value'])
                    status = 'mapped'
            elif identifier == 'components.selection':
                for component in _shared.COMPONENTS:
                    profile.setdefault('components', {}).setdefault(component, {})['enabled'] = component in field['value']
                status = 'mapped'
            elif identifier.startswith('component:') and identifier.endswith('.source'):
                component = identifier.split(':', 1)[1].split('.', 1)[0]
                profile.setdefault('components', {}).setdefault(component, {})['source'] = deepcopy(field['value'])
                status = 'mapped'
            elif identifier.startswith('component:') and identifier.endswith('.execution'):
                component = identifier.split(':', 1)[1].split('.', 1)[0]
                profile.setdefault('components', {}).setdefault(component, {})['execution'] = field['value']
                status = 'mapped'
            elif identifier.startswith('runtime:'):
                runtime = identifier.split(':', 1)[1]
                try:
                    _shared._validate({'runtimes': {runtime: field['value']}}, overlay=True)
                except _shared.ProfileError:
                    gaps.append({'field_id': identifier, 'reason': 'unsupported_runtime_intent',
                                 'required': required_field})
                    status = 'unsupported'
                else:
                    profile.setdefault('runtimes', {})[runtime] = deepcopy(field['value'])
                    status = 'mapped'
                    evidence = [observations[e] for e in field['evidence'] if e in observations
                                and observations[e]['value'].get('name') == field['value']['environment']
                                and observations[e]['value'].get('manager') == field['value']['manager']]
                    # A reviewed matching placement chooses the alternative.
                    # Unchosen observations remain coverage, not veto authority.
                    if runtime not in native_runtimes and any(
                            item['value'].get('placement') not in ('host', 'environment', 'project') for item in evidence):
                        gaps.append({'field_id': identifier, 'reason': 'unsupported_runtime_placement',
                                     'required': required_field})
                        status = 'unsupported'
            elif identifier.startswith(('custom:', 'tool:')):
                item = {'id': identifier, 'purpose': None, 'source': None, 'placement': 'unknown',
                        **deepcopy(field['value']), 'required': required_field, 'support': 'unsupported'}
                profile.setdefault('custom_dependencies', []).append(item)
                status = 'unsupported'
            elif identifier.startswith(('environment:', 'repository:', 'note:')):
                key = {'environment': 'environments', 'repository': 'repositories', 'note': 'notes'}[identifier.split(':', 1)[0]]
                value = {'text': field['value']} if key == 'notes' else deepcopy(field['value'])
                profile.setdefault(key, []).append({'id': identifier, **value,
                                                    'required': required_field, 'support': 'unsupported'})
                status = 'unsupported'
        if status != 'mapped' and (status != 'excluded' or required_field):
            gaps.append({'field_id': identifier, 'reason': ('unsupported_mapping' if status == 'unsupported'
                                                           else 'required_intent_unresolved'),
                         'required': required_field})
        coverage.append({'field_id': identifier, 'status': status, 'required': required_field})
    for component, value in profile.get('components', {}).items():
        if value.get('enabled'):
            for dependency in _shared.DEPENDENCIES[component]:
                if dependency not in selected_components:
                    gaps.append({'field_id': 'components.' + component,
                                 'reason': 'requires_enabled_' + dependency, 'required': True})
            runtime = _shared.COMPONENT_RUNTIME[component]
            if runtime in profile.get('runtimes', {}):
                value['runtime'] = runtime
            if runtime in native_runtimes and 'component:' + component + '.execution' not in fields_by_id:
                value['execution'] = 'native'
            elif value.get('execution') != 'native':
                gaps.append({'field_id': 'components.' + component + '.execution',
                             'reason': 'native_placement_review_required', 'required': True})
            if not value.get('source') or 'runtime' not in value:
                gaps.append({'field_id': 'components.' + component,
                             'reason': 'source_runtime_intent_unresolved', 'required': True})
    # Syntax validation alone misses cross-field conflicts. Reuse the same
    # pure intent contract as shared resolution, retaining declarations to edit.
    try:
        _shared._dependencies(profile)
    except _shared.ProfileError:
        gaps.append({'field_id': 'dependencies', 'reason': 'dependency_intent_unresolved',
                     'required': True})
    required = [deepcopy(gap) for gap in gaps if gap['required']]
    complete = not required
    # Reviewed declarations can be supported by one consumer but not another.
    # Keep their required support gaps without falsely marking intent unreviewed.
    intent_complete = not any(gap['reason'] != 'unsupported_mapping' for gap in required)
    profile['draft'] = not intent_complete
    # Persistence exclusions are original observation authority, never editable
    # desired intent. build_review above validated this baseline/companion pair.
    original_roots = _discovery.original_observed_roots(baseline)
    review = {'baseline_revision': baseline['revision'], 'candidate_revision': candidate['revision'],
              'original_observed_roots': sorted(original_roots),
              'intent_complete': intent_complete,
              'fields': deepcopy(candidate['fields']), 'coverage': coverage, 'gaps': gaps,
              'required_unresolved': required, 'apply_supported': False,
              'observation_incomplete': baseline['incomplete'],
              'observation_coverage': [{key: deepcopy(item[key]) for key in ('id', 'status', 'reason', 'evidence')
                                        if key in item} for item in baseline['observations']],
              'limitations': deepcopy(baseline['limitations']), 'conformance': 'not_evaluated'}
    _shared.parse_profile_text(yaml.safe_dump(profile))
    return {'profile': profile, 'review': review, 'complete': complete}
