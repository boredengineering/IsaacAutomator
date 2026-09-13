"""Optional, explicitly requested cost estimates. No deployment side effects.

Public reports contain only allowlisted fields; monetary values are decimal
strings. Covered subtotal is never a claim about undeclared spending.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
from pathlib import Path
import os
import math
import selectors
import signal
import subprocess
import time
import tempfile
import shutil
import platform
import stat


class CostRuntimeError(RuntimeError):
    """Only fixed, public error codes; no subprocess diagnostics."""


def run_process(argv, *, cwd, environment, timeout, cancel_event=None):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise CostRuntimeError('invalid_timeout')
    if cancel_event is not None and cancel_event.is_set():
        raise CostRuntimeError('cancelled')
    process = None
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        deadline = time.monotonic() + timeout
        output = bytearray()
        consumed = 0
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise CostRuntimeError('cancelled')
                if time.monotonic() >= deadline:
                    raise CostRuntimeError('timeout')
                for key, _ in selector.select(0.025):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    consumed += len(chunk)
                    if consumed > 4 * 1024 * 1024:
                        raise CostRuntimeError('output_limit')
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
        return process.returncode, bytes(output)
    except OSError:
        raise CostRuntimeError('runtime_execution_failed') from None
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
            process.stderr.close()


def _unverified_model(value):
    if isinstance(value, dict):
        return any((key == 'provisioning_model' and item not in ('STANDARD', 'SPOT')) or
                   _unverified_model(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_unverified_model(item) for item in value)
    return False


def snapshot_input(*, path=None, saved_plan=None):
    """Snapshot selected public files via the runner's bounded no-follow reader.

    Initial HCL mode is deliberately a flat root, without modules, data sources,
    implicit tfvars or filesystem functions. This is not a general HCL sandbox.
    """
    from src.python.terraform_runner import _input_snapshot, TerraformRunnerError
    try:
        if path is None:
            content = _input_snapshot(Path(saved_plan).absolute(), label='Cost plan')
            plan = json.loads(content)
            if not isinstance(plan, dict) or plan.get('format_version') not in ('1.0', '1.1', '1.2') or not isinstance(plan.get('planned_values'), dict):
                raise ValueError('Native or invalid plan unsupported')
            digest = hashlib.sha256(content).hexdigest()
            return {'plan.json': content}, {'mode': 'saved_plan_json', 'input_digest': digest,
                'source_digest': None, 'plan_digest': digest, 'binding': 'standalone_not_deployment_bound',
                'flex_unverified': _unverified_model(plan)}
        root = Path(path).absolute()
        if '..' in root.parts or any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
            raise ValueError('Unsafe source root')
        files = {}
        flex_unverified = False
        for entry in root.iterdir():
            if entry.is_symlink():
                raise ValueError('Symlink source rejected')
            if entry.name.endswith(('.tfvars', '.tfvars.json')) or entry.name.startswith('terragrunt'):
                raise ValueError('Implicit variables and hooks unsupported')
            if entry.suffix != '.tf' and not entry.name.endswith('.tf.json'):
                continue
            if len(files) >= 100:
                raise ValueError('Source file limit exceeded')
            content = _input_snapshot(entry, label='Cost source')
            text = content.decode('utf-8')
            if entry.name.endswith('.tf.json'):
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError('Invalid JSON HCL')
                # Decode escaped JSON tokens before checking forbidden constructs.
                text = json.dumps(value, ensure_ascii=False)
                flex_unverified |= _unverified_model(value)
            else:
                # No general HCL evaluator: computed/unknown models are unpriced.
                models = re.findall(r'\bprovisioning_model\b', text)
                literals = re.findall(r'\bprovisioning_model\s*=\s*"(?:STANDARD|SPOT)"[ \t]*(?=[\n}]|$)', text)
                flex_unverified |= len(models) != len(literals)
            if re.search(r'\b(module|data|provisioner|file|filebase64|fileexists|fileset|templatefile|pathexpand|abspath|run_cmd|external)\b', text):
                raise ValueError('Indirect source or execution unsupported')
            files[entry.name] = content
        if not files or sum(map(len, files.values())) > 4 * 1024 * 1024:
            raise ValueError('Source selection empty or too large')
        digest = hashlib.sha256()
        for name, content in sorted(files.items()):
            digest.update(name.encode() + b'\0' + content + b'\0')
        return files, {'input_digest': digest.hexdigest(), 'source_digest': digest.hexdigest(),
                       'mode': 'hcl', 'binding': 'standalone_not_deployment_bound',
                       'flex_unverified': flex_unverified}
    except (OSError, UnicodeError, TerraformRunnerError):
        raise ValueError('Input unavailable or unsafe; diagnostics withheld') from None


def validate_usage(value):
    """Validate the wrapper's v1 usage object (not an Infracost config).

    Exact keys: version: 1, resource_usage: {static Terraform address: {quantity:
    nonnegative decimal}}. Quantities admitted: monthly_hrs, storage_gb,
    monthly_egress_data_transfer_gb, monthly_requests. Runtime conversion is
    separately gated on verified tool support. Never scale retained storage.
    """
    if not isinstance(value, dict) or set(value) != {'version', 'resource_usage'} or value['version'] not in (1, '0.1') or isinstance(value['version'], bool):
        raise ValueError('Invalid usage schema')
    entries = value['resource_usage']
    if not isinstance(entries, dict) or len(entries) > 1000:
        raise ValueError('Invalid resource usage')
    result = {}
    for address, quantities in entries.items():
        if not isinstance(address, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,255}', address):
            raise ValueError('Usage requires static resource addresses')
        allowed = {'monthly_hrs', 'storage_gb', 'assigned_vms', 'monthly_data_processed_gb',
                   'monthly_class_a_operations', 'monthly_class_b_operations', 'monthly_data_retrieval_gb'}
        if value['version'] == 1:
            allowed |= {'monthly_egress_data_transfer_gb', 'monthly_requests'}
        if not isinstance(quantities, dict) or not quantities or set(quantities) - allowed:
            raise ValueError('Unsupported usage quantity')
        result[address] = {key: str(_money(number)) for key, number in quantities.items()}
    return {'version': value['version'], 'resource_usage': result}


def _load_usage(path):
    from src.python.terraform_runner import _input_snapshot, TerraformRunnerError
    import yaml
    class StrictLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ValueError('Duplicate or invalid usage key')
            result[key] = loader.construct_object(value_node)
        return result
    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    StrictLoader.add_constructor('tag:yaml.org,2002:float', lambda loader, node: Decimal(node.value))
    try:
        raw = _input_snapshot(Path(path).absolute(), label='Cost usage')
    except TerraformRunnerError:
        raise ValueError('Usage input unavailable') from None
    if len(raw) > 65536:
        raise ValueError('Usage file too large')
    try:
        if any(isinstance(token, (yaml.AliasToken, yaml.AnchorToken, yaml.TagToken)) for token in yaml.scan(raw)):
            raise ValueError('Usage aliases or tags unsupported')
        usage = validate_usage(yaml.load(raw, Loader=StrictLoader))
    except yaml.YAMLError:
        raise ValueError('Invalid usage YAML') from None
    if usage['version'] != '0.1':
        raise ValueError('Runtime usage requires version 0.1')
    # Render validated decimals as YAML numeric scalars, never quoted strings.
    lines = ['version: "0.1"', 'resource_usage:']
    for address, values in sorted(usage['resource_usage'].items()):
        lines.append('  ' + address + ':')
        for key, number in sorted(values.items()):
            lines.append('    ' + key + ': ' + format(Decimal(number), 'f'))
    content = ('\n'.join(lines) + '\n').encode()
    public = {hashlib.sha256(address.encode()).hexdigest(): quantities for address, quantities in usage['resource_usage'].items()}
    return content, hashlib.sha256(content).hexdigest(), public


def _money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal('1e15') or number.as_tuple().exponent < -18 or len(number.as_tuple().digits) > 34:
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid nonnegative finite monetary value') from None


def _sum_money(values):
    with localcontext() as context:
        context.prec = 60
        return sum(values, Decimal(0))


def _resource_type(value):
    return value if value in ('google_compute_instance', 'google_compute_instance_template',
        'google_compute_region_instance_template', 'google_compute_disk', 'google_storage_bucket',
        'google_compute_address', 'google_compute_router_nat', 'google_artifact_registry_repository',
        'google_compute_snapshot', 'google_compute_image') else 'other'


def normalized_report(resources, *, currency='USD', scope='workstation'):
    if currency not in ('USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY') or scope not in ('workstation', 'backend', 'registry', 'backup', 'evidence'):
        raise ValueError('Unsupported currency or scope')
    counts = dict(priced=0, free=0, unpriced=0, unknown=0)
    rows = []
    subtotal = Decimal(0)
    for resource in resources:
        state = resource['state']
        if state not in counts:
            raise ValueError('Invalid coverage state')
        amount = _money(resource['monthly_cost']) if state in ('priced', 'free') else None
        if state == 'free' and amount != 0:
            raise ValueError('Free resource has a nonzero amount')
        counts[state] += 1
        if amount is not None:
            subtotal = _sum_money((subtotal, amount))
        rows.append({'id': hashlib.sha256(str(resource['id']).encode()).hexdigest(),
                     'state': state, 'monthly_cost': str(amount) if amount is not None else None})
        if 'resource_type' in resource:
            rows[-1]['resource_type'] = _resource_type(resource['resource_type'])
    return {'schema_version': 1, 'status': 'partial' if counts['unknown'] + counts['unpriced'] else
            'complete_within_declared_scope', 'timestamp': datetime.now(timezone.utc).isoformat(),
            'currency': currency, 'unit': 'month', 'scope': scope, 'counts': counts,
            'covered_subtotal': str(subtotal), 'resources': rows,
            'exclusions': ['undeclared_resources', 'taxes_discounts_and_external_charges']}


def normalize_scan(raw, *, scope='workstation', flex_unverified=False):
    """Project the pinned v2.16.3 scan schema; never export raw diagnostics/tags."""
    if not isinstance(raw, dict) or raw.get('currency') != 'USD' or not isinstance(raw.get('projects'), list):
        raise ValueError('Unsupported scan schema')

    def cost(resource, depth=0):
        if depth > 32 or not isinstance(resource, dict) or type(resource.get('is_supported')) is not bool or type(resource.get('is_free')) is not bool:
            raise ValueError('Invalid scan resource')
        if not resource['is_supported']:
            return 'unpriced', None
        components, children = resource.get('cost_components', []), resource.get('subresources', [])
        if not isinstance(components, list) or not isinstance(children, list):
            raise ValueError('Invalid component collection')
        amounts = []
        missing = not resource['is_free'] and not components and not children
        for component in components:
            if not isinstance(component, dict):
                raise ValueError('Invalid component')
            if any(component.get(key) is None for key in ('price', 'quantity', 'total_monthly_cost')):
                missing = True
            else:
                _money(component['price'])
                _money(component['quantity'])
                amounts.append(_money(component['total_monthly_cost']))
        for child in children:
            state, amount = cost(child, depth + 1)
            if amount is None:
                missing = True
            else:
                amounts.append(amount)
        subtotal = _sum_money(amounts)
        if resource['is_free']:
            if missing or subtotal != 0:
                raise ValueError('Contradictory free resource coverage')
            return 'free', Decimal(0)
        return ('unknown', None) if missing else ('priced', subtotal)

    rows = []
    seen = {}
    diagnostics = False
    for project in raw['projects']:
        if not isinstance(project, dict) or not isinstance(project.get('resources'), list):
            raise ValueError('Invalid scan project')
        diagnostics = diagnostics or bool(project.get('diagnostics'))
        for resource in project['resources']:
            state, amount = cost(resource)
            if not isinstance(resource.get('name'), str):
                raise ValueError('Resource identity absent')
            if flex_unverified and resource.get('type') in ('google_compute_instance', 'google_compute_instance_template', 'google_compute_region_instance_template'):
                state, amount = 'unpriced', None
            row = {'id': resource['name'], 'state': state,
                   'resource_type': _resource_type(resource.get('type')),
                   'monthly_cost': str(amount) if amount is not None else None}
            if row['id'] in seen:
                if row != seen[row['id']]:
                    raise ValueError('Conflicting duplicate resource')
                continue
            seen[row['id']] = row
            rows.append(row)
    report = normalized_report(rows, scope=scope)
    report['warnings'] = []
    if diagnostics:
        report['warnings'].append('scan_diagnostics')
    if flex_unverified:
        report['warnings'].append('flex_pricing_model_unverified')
    if not rows or diagnostics or flex_unverified:
        report['status'] = 'partial'
        report['reason'] = 'flex_pricing_model_unverified' if flex_unverified else 'empty_or_diagnostic_coverage'
    return report


def _failure(status, reason):
    report = normalized_report([])
    report.update(status=status, reason=reason, covered_subtotal=None)
    return report


def runtime_platform():
    architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    # Extracted binary hashes verified against official archive checksums and
    # GitHub release asset digests; not a cryptographic signature verification.
    expected = {'amd64': '4c2cf0466a587b0d8b1bbee61b0fd3c43e2be3b8afbcd689f800abc3e3531101',
                'arm64': 'ce46b4ec6e40cf68473249737aab6288285a6c771465a91cccc69a7fa473243e'}
    if platform.system() != 'Linux' or architecture not in expected:
        raise CostRuntimeError('platform_not_verified')
    return architecture, expected[architecture]


def _runtime_snapshot(path, reason):
    """Read checked bytes once; no blocking special files or symlink ancestors."""
    descriptors = []
    try:
        path = Path(path).absolute()
        if '..' in path.parts:
            raise ValueError()
        parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for part in path.parts[1:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 128 * 1024 * 1024:
            raise ValueError()
        data = bytearray()
        while len(data) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if len(data) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError()
        return bytes(data)
    except (OSError, ValueError):
        raise CostRuntimeError(reason) from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def verify_runtime(infracost_binary='infracost', plugin_dir=None):
    """Validate explicitly provisioned runtime; never install or inspect HOME."""
    binary = shutil.which(str(infracost_binary))
    if binary is None:
        raise CostRuntimeError('binary_missing')
    binary = Path(binary).absolute()
    architecture, checksum = runtime_platform()
    binary_bytes = _runtime_snapshot(binary, 'unsafe_binary')
    if hashlib.sha256(binary_bytes).hexdigest() != checksum:
        raise CostRuntimeError('binary_checksum_mismatch')
    manifest = json.loads((Path(__file__).resolve().parents[2] / 'configs/cost/runtime.json').read_bytes())
    if manifest.get('cli_version') != '2.16.3':
        raise CostRuntimeError('plugin_manifest_incompatible')
    root = Path(plugin_dir or os.environ.get('ISAAC_INFRACOST_PLUGIN_DIR') or manifest['plugin_directory']).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise CostRuntimeError('pinned_plugins_missing')
    plugins, versions = {}, {}
    for entry in manifest['plugins']:
        name = entry['name']
        if name not in ('infracost-parser-terraform', 'infracost-parser-terraform-plan', 'infracost-provider-google'):
            raise CostRuntimeError('plugin_manifest_incompatible')
        file = root / name
        content = _runtime_snapshot(file, 'pinned_plugins_missing')
        if hashlib.sha256(content).hexdigest() != entry['platforms']['linux-' + architecture]['binary_sha256']:
            raise CostRuntimeError('plugin_checksum_mismatch')
        plugins[name], versions[name] = content, entry['version']
    if len(plugins) != 3:
        raise CostRuntimeError('pinned_plugins_missing')
    return {'binary': str(binary), 'binary_bytes': binary_bytes, 'plugins': plugins, 'versions': versions}


def _input_inventory(files, mode):
    identities = set()
    uncertain = False
    if mode == 'saved_plan_json':
        plan = json.loads(files['plan.json'])
        uncertain = plan.get('complete') is False or plan.get('errored') is True or bool(plan.get('deferred_changes'))
        def walk(module, depth=0):
            if depth > 32 or not isinstance(module, dict):
                raise ValueError('Invalid plan module')
            for resource in module.get('resources', []):
                if resource.get('mode', 'managed') == 'managed':
                    identities.add(resource['address'])
            for child in module.get('child_modules', []):
                walk(child, depth + 1)
        walk(plan['planned_values'].get('root_module', {}))
        def unknown(value):
            if isinstance(value, dict):
                return any(unknown(v) for v in value.values())
            if isinstance(value, list):
                return any(unknown(v) for v in value)
            return value is True
        uncertain |= any(unknown(item.get('change', {}).get('after_unknown', {})) for item in plan.get('resource_changes', []))
    else:
        for filename, content in files.items():
            text = content.decode()
            if filename.endswith('.tf.json'):
                parsed = json.loads(text)
                text = json.dumps(parsed)
                for kind, named in parsed.get('resource', {}).items():
                    for name in named:
                        identities.add(kind + '.' + name)
            else:
                identities.update(kind + '.' + name for kind, name in re.findall(r'\bresource\s+"([A-Za-z0-9_]+)"\s+"([A-Za-z0-9_-]+)"', text))
            uncertain |= bool(re.search(r'\b(count|for_each|dynamic)\b', text))
    return {hashlib.sha256(identity.encode()).hexdigest() for identity in identities}, uncertain


def _input_regions(files, mode):
    """Conservative location evidence, not a region override or HCL evaluator."""
    regions, locations = set(), []
    uncertain = False
    def location(resource_type, key, value):
        if not isinstance(value, str):
            return None
        # GCS regional locations are uppercase in provider state; this
        # normalization is not valid for arbitrary resource attributes.
        if resource_type == 'google_storage_bucket' and key == 'location':
            value = value.lower()
        pattern = r'([a-z]+-[a-z]+[0-9])' + (r'-[a-z]' if key == 'zone' else '')
        match = re.fullmatch(pattern, value)
        return match[1] if match else None
    def resource(resource_type, values):
        nonlocal uncertain
        # Only explicitly known global types may omit location evidence. Never
        # infer this from a missing region (billable/unknown types fail closed).
        global_types = {'google_compute_network'}
        selected = [(resource_type, key, values[key]) for key in ('region', 'zone', 'location') if key in values]
        if not selected and resource_type not in global_types:
            uncertain = True
        locations.extend(selected)
    if mode == 'saved_plan_json':
        def walk(module):
            for item in module.get('resources', []):
                if item.get('mode', 'managed') == 'managed':
                    resource(item.get('type'), item.get('values', {}))
            for child in module.get('child_modules', []):
                walk(child)
        walk(json.loads(files['plan.json'])['planned_values'].get('root_module', {}))
    else:
        for name, content in files.items():
            if name.endswith('.tf.json'):
                for resource_type, named in json.loads(content).get('resource', {}).items():
                    for values in named.values():
                        resource(resource_type, values)
            else:
                # Text HCL does not provide verified per-resource location binding.
                uncertain = True
                locations.extend((None, key, value) for key, value in
                                 re.findall(r'\b(region|zone|location)\s*=\s*"([^"\n]+)"', content.decode()))
    for resource_type, key, value in locations:
        found = location(resource_type, key, value)
        if found is None:
            uncertain = True
        else:
            regions.add(found)
    status = 'mixed' if len(regions) > 1 else 'unknown' if uncertain or not regions else 'verified_single'
    return {'region': next(iter(regions)) if status == 'verified_single' else None,
            'region_status': status, 'observed_regions': sorted(regions)}


def doctor(*, infracost_binary='infracost', plugin_dir=None):
    try:
        runtime = verify_runtime(infracost_binary, plugin_dir)
        report = _failure('unavailable', 'authentication_token_required') if not os.environ.get('INFRACOST_CLI_AUTHENTICATION_TOKEN') else _failure('complete_within_declared_scope', 'runtime_ready_not_a_quote')
        report['tool'] = {'name': 'infracost', 'version': '2.16.3', 'schema': 'scan-v2.16.3', 'plugins': runtime['versions']}
        return report
    except CostRuntimeError as exc:
        return _failure('unavailable', str(exc))
    except (OSError, ValueError, KeyError, TypeError):
        return _failure('unavailable', 'runtime_manifest_invalid')


def estimate(*, path=None, saved_plan=None, usage_file=None, timeout=60,
             cancel_event=None, profile=None, deployment=None,
             allow_external_pricing=False, allow_pricing=False, public_input=False,
             scope='workstation', region=None, infracost_binary='infracost', plugin_dir=None):
    """Price explicitly selected public input; never generate a Terraform plan.

    Private input, profiles, deployment bindings and native binary plans remain
    unsupported. Exported JSON is a standalone snapshot, not an attestation of
    deployed inputs. Consent permits pricing network traffic, not cloud mutation.
    """
    source, expected_resources = None, set()
    region_metadata = {}
    def fail(status, reason):
        report = _failure(status, reason)
        if scope in ('workstation', 'backend', 'registry', 'backup', 'evidence'):
            report['scope'] = scope
        if source is not None:
            report['source'] = source
            report['input_digest'] = source['input_digest']
        for identity in sorted(expected_resources):
            report['resources'].append({'id': identity, 'state': 'unknown', 'monthly_cost': None})
        report['counts']['unknown'] = len(expected_resources)
        report.update(region_metadata)
        return _public_report(report)
    if profile is not None:
        return fail('unsupported', 'profile_not_bound')
    if deployment is not None:
        return fail('unsupported', 'deployment_not_bound')
    if (path is None) == (saved_plan is None):
        return fail('error', 'select_one_input')
    if not (allow_external_pricing or allow_pricing):
        return fail('unsupported', 'external_pricing_consent_required')
    if not public_input:
        return fail('unsupported', 'private_input_not_approved')
    try:
        if scope not in ('workstation', 'backend', 'registry', 'backup', 'evidence'):
            return fail('unsupported', 'scope_not_supported')
        if region is not None and (not isinstance(region, str) or not re.fullmatch(r'[a-z]+-[a-z]+[0-9]', region)):
            return fail('unsupported', 'region_not_supported')
        files, source = snapshot_input(path=path, saved_plan=saved_plan)
        expected_resources, uncertain_inputs = _input_inventory(files, source['mode'])
        region_metadata = _input_regions(files, source['mode'])
        if region is not None:
            if any(value != region for value in region_metadata['observed_regions']):
                return fail('unsupported', 'region_conflicts_with_input')
            if region_metadata['region_status'] != 'verified_single':
                return fail('unsupported', 'region_unverified')
        usage_digest = hashlib.sha256(b'tool_defaults_not_measured-v1').hexdigest()
        usage_values = {}
        if usage_file is not None:
            usage_content, usage_digest, usage_values = _load_usage(usage_file)
            files['usage.yml'] = usage_content
        # Always supply a local explicit configuration so hosted templates cannot
        # expand scan scope or inject projects, variables, modules or hooks.
        project_path = '.' if path is not None else 'plan.json'
        config = {'version': '0.3', 'projects': [{'path': project_path}]}
        if usage_file is not None:
            config['usage_file'] = 'usage.yml'
        files['infracost.yml'] = json.dumps(config).encode()
        if cancel_event is not None and cancel_event.is_set():
            return fail('error', 'cancelled')
        runtime = verify_runtime(infracost_binary, plugin_dir)
        if not os.environ.get('INFRACOST_CLI_AUTHENTICATION_TOKEN'):
            return fail('unavailable', 'authentication_token_required')
        with tempfile.TemporaryDirectory(prefix='isaac-cost-') as directory:
            root = Path(directory)
            executable = runtime['binary']
            if 'binary_bytes' in runtime:
                executable = str(root / 'infracost')
                Path(executable).write_bytes(runtime['binary_bytes'])
                Path(executable).chmod(0o700)
            for name in ('input', 'home', 'cache', 'config', 'plugins', 'tmp'):
                (root / name).mkdir(mode=0o700)
            for name, content in files.items():
                with (root / 'input' / name).open('xb') as stream:
                    os.chmod(stream.name, 0o600)
                    stream.write(content)
            for name, content in runtime['plugins'].items():
                destination = root / 'plugins' / name
                destination.write_bytes(content)
                destination.chmod(0o700)
            environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                'HOME': str(root / 'home'), 'XDG_CONFIG_HOME': str(root / 'config'),
                'XDG_CACHE_HOME': str(root / 'cache'), 'TMPDIR': str(root / 'tmp'),
                'INFRACOST_CLI_PLUGIN_DIR': str(root / 'plugins'),
                'INFRACOST_SKIP_UPDATE_CHECK': 'true', 'INFRACOST_SKIP_AGENT_CHECK': 'true',
                'INFRACOST_CLI_PLUGIN_AUTO_UPDATE': 'false', 'INFRACOST_CLI_LOG_LEVEL': 'disabled',
                'INFRACOST_CLI_EVENTS_ENDPOINT': 'http://127.0.0.1:1',

                'INFRACOST_CLI_AUTHENTICATION_TOKEN': os.environ['INFRACOST_CLI_AUTHENTICATION_TOKEN']}
            target = root / 'input' if path is not None else root / 'input' / 'plan.json'
            exit_code, output = run_process([executable, 'scan', str(target), '--currency', 'USD', '--json', '--no-color'],
                cwd=directory, environment=environment, timeout=timeout, cancel_event=cancel_event)
            if not output:
                return fail('unavailable', 'pricing_failed_auth_network_or_runtime')
            report = normalize_scan(json.loads(output), scope=scope, flex_unverified=source['flex_unverified'])
            missing = expected_resources - {row['id'] for row in report['resources']}
            for identity in sorted(missing):
                report['resources'].append({'id': identity, 'state': 'unknown', 'monthly_cost': None})
                report['counts']['unknown'] += 1
            if missing or uncertain_inputs:
                report.update(status='partial', reason='input_coverage_incomplete')
                report['warnings'].append('input_coverage_incomplete')
            if region_metadata['region_status'] != 'verified_single':
                report['status'] = 'partial'
                report.setdefault('reason', 'region_unverified')
                report['warnings'].append('region_unverified')
            if exit_code != 0:
                report.update(status='partial', reason='scan_diagnostics')
                report['warnings'].append('scan_diagnostics')
            report['warnings'] = sorted(set(report['warnings'] + ['tool_defaults_not_observed']))
            report.update(region_metadata)
            report.update(source=source, input_digest=source['input_digest'],
                tool={'name': 'infracost', 'version': '2.16.3', 'schema': 'scan-v2.16.3',
                      'plugins': runtime.get('versions', {})},
                usage={'basis': 'explicit_file_with_tool_defaults' if usage_file is not None else 'tool_defaults_not_measured',
                       'resource_usage': usage_values, 'reference_month_hours': '730', 'effective_usage': 'not_observed',
                       'runtime_scenario': 'not_estimated', 'retained_resources': 'not_separately_estimated'},
                usage_digest=usage_digest)
            return _public_report(report)
    except CostRuntimeError as exc:
        return fail('unavailable' if str(exc) not in ('cancelled', 'timeout', 'output_limit') else 'error', str(exc))
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError):
        return fail('error', 'invalid_input_or_scan_schema')


def _public_report(report):
    """Validate money/coverage and project nested metadata through allowlists."""
    if not isinstance(report, dict) or report.get('schema_version') != 1:
        raise ValueError('Unsupported cost report')
    def digest(value):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('Invalid digest')
        return value
    def choose(value, allowed):
        if value not in allowed:
            raise ValueError('Invalid public report field')
        return value
    out = {'schema_version': 1,
        'status': choose(report.get('status'), ('complete_within_declared_scope', 'partial', 'unsupported', 'unavailable', 'stale', 'error')),
        'currency': choose(report.get('currency'), ('USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY')),
        'unit': choose(report.get('unit'), ('month',)),
        'scope': choose(report.get('scope'), ('workstation', 'backend', 'registry', 'backup', 'evidence'))}
    for key in ('timestamp', 'before_timestamp', 'after_timestamp'):
        if key in report:
            stamp = datetime.fromisoformat(report[key])
            if stamp.tzinfo is None:
                raise ValueError('Timestamp must include timezone')
            out[key] = stamp.isoformat()
    if report.get('kind') == 'comparison':
        out['kind'] = 'comparison'
        delta = report['covered_subtotal_delta']
        if delta is not None:
            delta = Decimal(str(delta))
            _money(delta.copy_abs())
        out['covered_subtotal_delta'] = str(delta) if delta is not None else None
        for key in ('added', 'removed', 'changed'):
            out[key] = [digest(value) for value in report[key]]
        out['changes'] = []
        for item in report.get('changes', []):
            row = {'id': digest(item['id']), 'change': choose(item['change'], ('added', 'removed', 'changed'))}
            for key in ('before_monthly_cost', 'after_monthly_cost'):
                row[key] = str(_money(item[key])) if item[key] is not None else None
            for key in ('before_state', 'after_state'):
                row[key] = choose(item[key], ('priced', 'free', 'unknown', 'unpriced', 'absent'))
            delta = item['covered_monthly_delta']
            if delta is not None:
                _money(Decimal(delta).copy_abs())
            row['covered_monthly_delta'] = delta
            out['changes'].append(row)
    else:
        counts = dict(priced=0, free=0, unpriced=0, unknown=0)
        rows, ids, subtotal = [], set(), Decimal(0)
        for row in report['resources']:
            identity = digest(row['id'])
            if identity in ids:
                raise ValueError('Duplicate report resource')
            ids.add(identity)
            state = choose(row['state'], counts)
            amount = _money(row['monthly_cost']) if state in ('priced', 'free') else None
            if state == 'free' and amount != 0 or state in ('unknown', 'unpriced') and row['monthly_cost'] is not None:
                raise ValueError('Inconsistent resource coverage')
            counts[state] += 1
            subtotal = _sum_money((subtotal, amount if amount is not None else Decimal(0)))
            rows.append({'id': identity, 'state': state, 'monthly_cost': str(amount) if amount is not None else None})
            if 'resource_type' in row:
                rows[-1]['resource_type'] = _resource_type(row['resource_type'])
        if report['counts'] != counts:
            raise ValueError('Inconsistent resource counts')
        declared = report['covered_subtotal']
        if declared is not None and _money(declared) != subtotal:
            raise ValueError('Inconsistent covered subtotal')
        if out['status'] == 'complete_within_declared_scope' and counts['unknown'] + counts['unpriced']:
            raise ValueError('Incomplete coverage labelled complete')
        out.update(resources=rows, counts=counts, covered_subtotal=str(_money(declared)) if declared is not None else None,
                   exclusions=['undeclared_resources', 'taxes_discounts_and_external_charges'])
    if 'reason' in report:
        out['reason'] = choose(report['reason'], {
            'profile_not_bound', 'deployment_not_bound', 'select_one_input', 'external_pricing_consent_required',
            'private_input_not_approved', 'scope_not_supported', 'region_not_supported', 'region_conflicts_with_input', 'region_unverified', 'cancelled', 'timeout',
            'output_limit', 'invalid_timeout', 'runtime_execution_failed', 'authentication_token_required',
            'pricing_failed_auth_network_or_runtime', 'scan_diagnostics', 'invalid_input_or_scan_schema',
            'binary_missing', 'unsafe_binary', 'platform_not_verified', 'binary_checksum_mismatch',
            'plugin_manifest_incompatible', 'pinned_plugins_missing', 'plugin_checksum_mismatch',
            'runtime_manifest_invalid', 'runtime_ready_not_a_quote', 'incompatible_or_invalid_reports',
            'flex_pricing_model_unverified', 'empty_or_diagnostic_coverage', 'input_coverage_incomplete'})
    for key in ('input_digest', 'usage_digest'):
        if key in report:
            out[key] = digest(report[key])
    if 'region' in report:
        region = report['region']
        if region is not None and (not isinstance(region, str) or not re.fullmatch(r'[a-z]+-[a-z]+[0-9]', region)):
            raise ValueError('Invalid region')
        out['region'] = region
    if 'region_status' in report:
        out['region_status'] = choose(report['region_status'], ('verified_single', 'mixed', 'unknown'))
        out['observed_regions'] = []
        for value in report['observed_regions']:
            if not isinstance(value, str) or not re.fullmatch(r'[a-z]+-[a-z]+[0-9]', value):
                raise ValueError('Invalid region')
            out['observed_regions'].append(value)
        if out['region_status'] == 'verified_single':
            if out['observed_regions'] != [out.get('region')] or out.get('region') is None:
                raise ValueError('Inconsistent verified region')
        elif out.get('region') is not None:
            raise ValueError('Unverified region labelled verified')
    if 'source' in report:
        source = report['source']
        out['source'] = {'mode': choose(source['mode'], ('hcl', 'saved_plan_json')),
                         'binding': choose(source['binding'], ('standalone_not_deployment_bound',))}
        for key in ('input_digest', 'source_digest', 'plan_digest'):
            if key in source:
                out['source'][key] = digest(source[key]) if source[key] is not None else None
        if 'flex_unverified' in source:
            if type(source['flex_unverified']) is not bool:
                raise ValueError('Invalid source coverage')
            out['source']['flex_unverified'] = source['flex_unverified']
    if 'tool' in report:
        tool = report['tool']
        versions = {}
        for name, version in tool.get('plugins', {}).items():
            choose(name, ('infracost-parser-terraform', 'infracost-parser-terraform-plan', 'infracost-provider-google'))
            if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
                raise ValueError('Invalid plugin version')
            versions[name] = version
        out['tool'] = {'name': choose(tool['name'], ('infracost',)), 'version': choose(tool['version'], ('2.16.3',)),
                       'schema': choose(tool['schema'], ('scan-v2.16.3',)), 'plugins': versions}
    if 'usage' in report:
        usage = report['usage']
        out['usage'] = {'basis': choose(usage['basis'], ('tool_defaults_not_measured', 'explicit_file_with_tool_defaults')),
                        'reference_month_hours': '730', 'effective_usage': 'not_observed',
                        'runtime_scenario': 'not_estimated', 'retained_resources': 'not_separately_estimated',
                        'resource_usage': {digest(identity): {choose(key, ('monthly_hrs', 'storage_gb', 'assigned_vms',
                            'monthly_data_processed_gb', 'monthly_class_a_operations', 'monthly_class_b_operations',
                            'monthly_data_retrieval_gb')): str(_money(value)) for key, value in values.items()}
                            for identity, values in usage.get('resource_usage', {}).items()}}
    if 'warnings' in report:
        out['warnings'] = [choose(value, ('pricing_timestamp_differs', 'coverage_differs', 'tool_defaults_not_observed',
            'scan_diagnostics', 'input_coverage_incomplete', 'flex_pricing_model_unverified', 'region_unverified')) for value in report['warnings']]
    return out


def compare_reports(before, after):
    before, after = _public_report(before), _public_report(after)
    if any('source' in report and (report.get('region') is None or report.get('region_status') != 'verified_single') for report in (before, after)):
        raise ValueError('Input-backed reports require a verified comparable region')
    for key in ('schema_version', 'currency', 'unit', 'scope', 'region', 'usage_digest', 'usage', 'tool'):
        if before.get(key) != after.get(key):
            raise ValueError('Reports have incompatible currency, units, scope, region or usage')
    if any(r['status'] not in ('partial', 'complete_within_declared_scope') for r in (before, after)):
        raise ValueError('Only usable nonstale reports can be compared')
    old = {r['id']: r for r in before['resources']}
    new = {r['id']: r for r in after['resources']}
    changes = []
    for identity in sorted(old.keys() | new.keys()):
        if old.get(identity) == new.get(identity):
            continue
        left, right = old.get(identity, {}).get('monthly_cost'), new.get(identity, {}).get('monthly_cost')
        delta = None
        # Missing resource is not the same as a present resource with unknown cost.
        if (identity in old and left is not None or identity not in old and before['status'] == 'complete_within_declared_scope') and (identity in new and right is not None or identity not in new and after['status'] == 'complete_within_declared_scope'):
            delta = str(_sum_money((_money(right or '0'), _money(left or '0').copy_negate())))
        changes.append({'id': identity, 'change': 'added' if identity not in old else 'removed' if identity not in new else 'changed',
                        'before_state': old.get(identity, {}).get('state', 'absent'),
                        'after_state': new.get(identity, {}).get('state', 'absent'),
                        'before_monthly_cost': left, 'after_monthly_cost': right, 'covered_monthly_delta': delta})
    warnings = ['pricing_timestamp_differs'] if before['timestamp'] != after['timestamp'] else []
    if {key: row['state'] for key, row in old.items()} != {key: row['state'] for key, row in new.items()}:
        warnings.append('coverage_differs')
    # Usage-file equality cannot attest hosted organization defaults.
    warnings.append('tool_defaults_not_observed')
    warnings = sorted(set(warnings + before.get('warnings', []) + after.get('warnings', [])))
    uncovered_old = {key for key, row in old.items() if row['monthly_cost'] is None}
    uncovered_new = {key for key, row in new.items() if row['monthly_cost'] is None}
    incomparable = uncovered_old != uncovered_new or (old.keys() != new.keys() and
        'partial' in (before['status'], after['status']))
    return {'schema_version': 1, 'kind': 'comparison',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'before_timestamp': before['timestamp'], 'after_timestamp': after['timestamp'],
            'status': 'partial' if 'partial' in (before['status'], after['status']) else 'complete_within_declared_scope',
            'currency': before['currency'], 'unit': before['unit'], 'scope': before['scope'],
            'covered_subtotal_delta': None if incomparable else str(_sum_money((_money(after['covered_subtotal']), _money(before['covered_subtotal']).copy_negate()))),
            'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()),
            'changed': sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
            'changes': changes, 'warnings': warnings}


def format_report(report, format='table'):
    report = _public_report(report)
    if format == 'json':
        return json.dumps(report, sort_keys=True, allow_nan=False)
    if format not in ('table', 'markdown'):
        raise ValueError('Unsupported report format')
    value = report.get('covered_subtotal_delta') if report.get('kind') == 'comparison' else report.get('covered_subtotal')
    lines = [('Status', report['status']), ('Scope', report['scope']),
             ('Covered subtotal delta' if report.get('kind') == 'comparison' else 'Covered subtotal',
              'Not estimated' if value is None else f"{value} {report['currency']}/month")]
    if report.get('reason'):
        lines.append(('Reason', report['reason']))
    for key in ('timestamp', 'before_timestamp', 'after_timestamp'):
        if key in report:
            lines.append((key, report[key]))
    for warning in report.get('warnings', []):
        lines.append(('Warning', warning))
    for key in ('counts', 'region', 'region_status', 'observed_regions', 'usage'):
        if key in report:
            lines.append((key, json.dumps(report[key], sort_keys=True)))
    for row in report.get('changes', []):
        lines.append(('Resource ' + row['id'], row['change'] + ' / ' + row['before_state'] + ' -> ' +
                      row['after_state'] + ' / ' + (row['covered_monthly_delta'] if row['covered_monthly_delta'] is not None else 'Not estimated')))
    for row in report.get('resources', []):
        lines.append(('Resource ' + row['id'], row.get('resource_type', 'other') + ' / ' + row['state'] + ' / ' +
                      (row['monthly_cost'] if row['monthly_cost'] is not None else 'Not estimated')))
    if format == 'markdown':
        return '| Field | Value |\n| --- | --- |\n' + '\n'.join(f'| {k} | {v} |' for k, v in lines)
    return '\n'.join(f'{k}: {v}' for k, v in lines)
