"""Cost report tracer tests; monetary fixtures are synthetic, not prices."""
import copy
import json
import unittest
import tempfile
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch


class ReportTests(unittest.TestCase):
    def test_all_public_fixtures_verify_asserted_region_before_authentication(self):
        from src.python.cost_estimate import estimate
        fixtures = Path(__file__).resolve().parents[2] / 'configs/cost/fixtures'
        for size in (48, 384):
            for model in ('standard', 'flex_start'):
                with self.subTest(size=size, model=model), \
                     patch('src.python.cost_estimate.verify_runtime', return_value={}) as runtime, \
                     patch('src.python.cost_estimate.run_process') as process, \
                     patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': ''}):
                    report = estimate(path=fixtures / f'g4-standard-{size}-{model}',
                                      region='us-west1', public_input=True, allow_pricing=True)
                    self.assertEqual(report['region_status'], 'verified_single')
                    self.assertEqual(report['region'], 'us-west1')
                    self.assertEqual(report['observed_regions'], ['us-west1'])
                    self.assertEqual(report['status'], 'unavailable')
                    self.assertEqual(report['reason'], 'authentication_token_required')
                    runtime.assert_called_once()
                    process.assert_not_called()

    def test_typed_regions_preserve_unknown_mixed_and_conflicting_inputs(self):
        from src.python.cost_estimate import estimate
        known = {'type': 'google_compute_instance', 'values': {'zone': 'us-west1-c'}}
        network = {'type': 'google_compute_network', 'values': {}}
        bucket = {'type': 'google_storage_bucket', 'values': {'location': 'US-WEST1'}}
        cases = [
            ('regional_with_global', [known, network, bucket], 'verified_single', 'authentication_token_required'),
            ('only_global', [network], 'unknown', 'region_unverified'),
            ('unlocated_compute', [known, network, {'type': 'google_compute_disk', 'values': {}}], 'unknown', 'region_unverified'),
            ('unlocated_unknown', [known, {'type': 'google_future_resource', 'values': {}}], 'unknown', 'region_unverified'),
            ('missing_type', [known, {'values': {}}], 'unknown', 'region_unverified'),
            ('mixed_bucket', [known, {'type': 'google_storage_bucket', 'values': {'location': 'US-EAST1'}}], 'mixed', 'region_conflicts_with_input'),
            ('contradictory_global', [known, {'type': 'google_compute_network', 'values': {'region': 'us-east1'}}], 'mixed', 'region_conflicts_with_input'),
        ]
        for value in (None, '${var.location}', 'US', 'EU', 'ASIA', 'NAM4', 'unknown', 'US-WEST1-C'):
            cases.append(('unresolved_bucket_' + str(value), [known, {'type': 'google_storage_bucket', 'values': {'location': value}}], 'unknown', 'region_unverified'))
        for resource_type, values in (
                ('google_compute_instance', {'zone': 'US-WEST1-C'}),
                ('google_compute_instance', {'zone': 'us-west1'}),
                ('google_compute_subnetwork', {'region': 'us-west1-c'}),
                ('google_storage_bucket', {'region': 'US-WEST1'}),
                ('google_artifact_registry_repository', {'location': 'US-WEST1'}),
                ('google_future_resource', {'location': 'US-WEST1'})):
            cases.append(('invalid_key_value_' + resource_type, [known, {'type': resource_type, 'values': values}], 'unknown', 'region_unverified'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mode in ('terraform_directory', 'saved_plan_json'):
                for label, resources, status, reason in cases:
                    with self.subTest(mode=mode, case=label):
                        if mode == 'saved_plan_json':
                            # Include child-module traversal; data resources are not managed evidence.
                            rows = [dict(item, address=item.get('type', 'unknown') + '.x' + str(i))
                                    for i, item in enumerate(resources)]
                            payload = {'format_version': '1.2', 'planned_values': {'root_module': {
                                'resources': [{'mode': 'data', 'type': 'google_compute_instance', 'address': 'data.google_compute_instance.x', 'values': {}}],
                                'child_modules': [{'resources': rows}]}}}
                            file = root / 'plan.json'
                        else:
                            payload = {'resource': {}}
                            for i, item in enumerate(resources):
                                payload['resource'].setdefault(item.get('type', 'unknown'), {})['x' + str(i)] = item['values']
                            file = root / 'main.tf.json'
                        file.write_text(json.dumps(payload))
                        with patch('src.python.cost_estimate.verify_runtime', return_value={}) as runtime, \
                             patch('src.python.cost_estimate.run_process') as process, \
                             patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': ''}):
                            report = estimate(path=root if mode == 'terraform_directory' else None,
                                              saved_plan=file if mode == 'saved_plan_json' else None,
                                              region='us-west1', public_input=True, allow_pricing=True)
                        file.unlink()
                        self.assertEqual(report['region_status'], status)
                        self.assertEqual(report['reason'], reason)
                        self.assertEqual(report['region'], 'us-west1' if status == 'verified_single' else None)
                        self.assertEqual(runtime.call_count, int(status == 'verified_single'))
                        process.assert_not_called()
            (root / 'main.tf').write_text('resource "google_compute_instance" "x" { zone = "us-west1-c" }')
            with patch('src.python.cost_estimate.verify_runtime') as runtime:
                report = estimate(path=root, region='us-west1', public_input=True, allow_pricing=True)
            self.assertEqual(report['region_status'], 'unknown')
            self.assertEqual(report['reason'], 'region_unverified')
            runtime.assert_not_called()

    def test_real_adapter_transport_failure_paths_are_sanitized_and_cleaned(self):
        from src.python.cost_estimate import estimate, run_process, format_report
        raw = {'currency': 'USD', 'projects': [{'resources': [{
            'name': 'google_compute_disk.x', 'type': 'google_compute_disk', 'is_supported': True,
            'is_free': True}]}]}
        cases = [(1, json.dumps(raw), 'partial', 'scan_diagnostics'),
                 (0, '', 'unavailable', 'pricing_failed_auth_network_or_runtime'),
                 (0, '{CANARY', 'error', 'invalid_input_or_scan_schema')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.tf.json').write_text(json.dumps({'resource': {'google_compute_disk': {'x': {'zone': 'us-east1-b'}}}}))
            for exit_code, stdout, status, reason in cases:
                with self.subTest(reason=reason):
                    script = ('#!' + sys.executable + '\nimport sys,os\n'
                              'sys.stderr.write(os.environ["INFRACOST_CLI_AUTHENTICATION_TOKEN"])\n'
                              'sys.stdout.write(' + repr(stdout) + ')\nsys.exit(' + str(exit_code) + ')\n').encode()
                    locations = []
                    def transport(*args, **kwargs):
                        locations.append(Path(kwargs['cwd']))
                        return run_process(*args, **kwargs)
                    with patch('src.python.cost_estimate.verify_runtime', return_value={
                            'binary': '/unused', 'binary_bytes': script, 'plugins': {}}), \
                         patch('src.python.cost_estimate.run_process', side_effect=transport), \
                         patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'CANARY'}):
                        report = estimate(path=root, timeout=2, public_input=True, allow_external_pricing=True)
                    self.assertEqual(report['status'], status)
                    self.assertEqual(report['reason'], reason)
                    self.assertTrue(locations)
                    self.assertTrue(all(not location.exists() for location in locations))
                    for style in ('json', 'table', 'markdown'):
                        self.assertNotIn('CANARY', format_report(report, style))

    def test_midflight_cancellation_kills_descendants_and_never_exports_stderr(self):
        import time
        from src.python.cost_estimate import estimate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile = root / 'child.pid'
            (root / 'main.tf').write_text('resource "google_compute_disk" "x" {}')
            script = ('#!' + sys.executable + '\nimport subprocess,sys,time,pathlib\n'
                      'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"])\n'
                      'pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(child.pid))\n'
                      'sys.stderr.write("CANARY");sys.stderr.flush();time.sleep(10)\n').encode()
            event = threading.Event()
            def cancel_when_running():
                deadline = time.monotonic() + 1.5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                event.set()
            watcher = threading.Thread(target=cancel_when_running, daemon=True)
            watcher.start()
            with patch('src.python.cost_estimate.verify_runtime', return_value={
                    'binary': '/unused', 'binary_bytes': script, 'plugins': {}}), \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'CANARY'}):
                report = estimate(path=root, timeout=2, cancel_event=event, public_input=True, allow_external_pricing=True)
            watcher.join(timeout=2)
            self.assertEqual(report['reason'], 'cancelled')
            self.assertNotIn('CANARY', json.dumps(report))
            self.assertTrue(pidfile.exists(), 'Cancellation must exercise a running descendant')
            child = int(pidfile.read_text())
            state = Path('/proc') / str(child) / 'stat'
            deadline = time.monotonic() + 1
            while state.exists() and state.read_text().split()[2] != 'Z' and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(not state.exists() or state.read_text().split()[2] == 'Z')

    def test_runtime_snapshots_reject_special_oversized_growing_and_swapped_files(self):
        from src.python.cost_estimate import _runtime_snapshot, CostRuntimeError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'runtime'
            file.write_bytes(b'checked')
            self.assertEqual(_runtime_snapshot(file, 'unsafe_binary'), b'checked')
            fifo = root / 'fifo'
            os.mkfifo(fifo)
            for unsafe in (fifo, root, Path('/dev/null')):
                with self.subTest(unsafe=unsafe), self.assertRaisesRegex(CostRuntimeError, 'unsafe_binary'):
                    _runtime_snapshot(unsafe, 'unsafe_binary')
            with file.open('wb') as stream:
                stream.truncate(128 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(CostRuntimeError, 'unsafe_binary'):
                _runtime_snapshot(file, 'unsafe_binary')
            file.write_bytes(b'checked')
            real_read = os.read
            reads = []
            def grow(fd, amount):
                reads.append(amount)
                with file.open('ab') as stream:
                    stream.write(b'growth')
                return real_read(fd, amount)
            with patch('src.python.cost_estimate.os.read', side_effect=grow), self.assertRaisesRegex(CostRuntimeError, 'unsafe_binary'):
                _runtime_snapshot(file, 'unsafe_binary')
            self.assertLessEqual(sum(reads), len(b'checked') + 1)
            target = root / 'replacement'
            target.write_bytes(b'CANARY')
            real_open = os.open
            def swap(name, flags, *args, **kwargs):
                if name == file.name:
                    file.unlink()
                    file.symlink_to(target)
                return real_open(name, flags, *args, **kwargs)
            with patch('src.python.cost_estimate.os.open', side_effect=swap), self.assertRaisesRegex(CostRuntimeError, 'unsafe_binary'):
                _runtime_snapshot(file, 'unsafe_binary')
            linked = root / 'linked'
            linked.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(CostRuntimeError, 'unsafe_binary'):
                _runtime_snapshot(linked / target.name, 'unsafe_binary')

    def test_verified_runtime_freezes_binary_and_plugins_and_rejects_plugin_symlinks(self):
        import hashlib
        from src.python.cost_estimate import verify_runtime, CostRuntimeError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'infracost'
            binary.write_bytes(b'SYNTHETIC_BINARY')
            binary.chmod(0o700)
            plugins = root / 'plugins'
            plugins.mkdir()
            names = ('infracost-parser-terraform', 'infracost-parser-terraform-plan', 'infracost-provider-google')
            manifest = {'cli_version': '2.16.3', 'plugins': [
                {'name': name, 'version': '0.0.1', 'platforms': {'linux-amd64': {
                    'binary_sha256': hashlib.sha256(name.encode()).hexdigest()}}} for name in names]}
            for name in names:
                (plugins / name).write_bytes(name.encode())
            with patch('src.python.cost_estimate.runtime_platform', return_value=('amd64', hashlib.sha256(binary.read_bytes()).hexdigest())), \
                 patch('src.python.cost_estimate.json.loads', return_value=manifest):
                checked = verify_runtime(binary, plugins)
                (plugins / names[0]).unlink()
                (plugins / names[0]).symlink_to(binary)
                with self.assertRaisesRegex(CostRuntimeError, 'pinned_plugins_missing'):
                    verify_runtime(binary, plugins)
                linked = root / 'linked'
                linked.symlink_to(root, target_is_directory=True)
                with self.assertRaisesRegex(CostRuntimeError, 'pinned_plugins_missing'):
                    verify_runtime(binary, linked / 'plugins')
            binary.write_bytes(b'REPLACEMENT')
            self.assertEqual(checked['binary_bytes'], b'SYNTHETIC_BINARY')
            self.assertEqual(checked['plugins'], {name: name.encode() for name in names})

    def test_comparison_preserves_report_times_and_input_warning_flags(self):
        from src.python.cost_estimate import normalized_report, compare_reports, format_report
        before = normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '10'}])
        after = copy.deepcopy(before)
        before['timestamp'] = '2026-01-01T00:00:00+00:00'
        after['timestamp'] = '2026-01-02T00:00:00+00:00'
        after.update(status='partial', warnings=['scan_diagnostics'])
        result = compare_reports(before, after)
        self.assertEqual(result['before_timestamp'], before['timestamp'])
        self.assertEqual(result['after_timestamp'], after['timestamp'])
        self.assertIn('scan_diagnostics', result['warnings'])
        for style in ('json', 'table', 'markdown'):
            text = format_report(result, style)
            self.assertIn(before['timestamp'], text)
            self.assertIn(after['timestamp'], text)
            self.assertIn('pricing_timestamp_differs', text)
            self.assertIn('scan_diagnostics', text)

    def test_identical_usage_digest_does_not_override_different_declared_usage(self):
        from src.python.cost_estimate import normalized_report, compare_reports
        before = normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '10'}])
        before['usage_digest'] = 'a' * 64
        before['usage'] = {'basis': 'explicit_file_with_tool_defaults',
                           'resource_usage': {before['resources'][0]['id']: {'monthly_hrs': '8'}}}
        after = copy.deepcopy(before)
        after['usage']['resource_usage'][before['resources'][0]['id']]['monthly_hrs'] = '730'
        with self.assertRaises(ValueError):
            compare_reports(before, after)

    def test_partial_scan_removal_does_not_become_a_resource_saving(self):
        from src.python.cost_estimate import normalized_report, compare_reports
        before = normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '10'}])
        after = normalized_report([])
        after.update(status='partial', reason='empty_or_diagnostic_coverage')
        compared = compare_reports(before, after)
        self.assertIsNone(compared['covered_subtotal_delta'])
        self.assertIsNone(compared['changes'][0]['covered_monthly_delta'])
        # Proven complete absence remains a covered cost movement, not a saving claim.
        after['status'] = 'complete_within_declared_scope'
        self.assertEqual(compare_reports(before, after)['covered_subtotal_delta'], '-10')

    def test_estimate_exposes_unobserved_effective_usage_and_all_coverage_flags(self):
        from src.python.cost_estimate import estimate, format_report
        raw = {'currency': 'USD', 'projects': [{'diagnostics': [{'message': 'CANARY'}], 'resources': [{
            'name': 'google_compute_instance.x', 'type': 'google_compute_instance',
            'is_supported': True, 'is_free': True}]}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.tf').write_text('resource "google_compute_instance" "x" { scheduling { provisioning_model = var.model } }\nresource "google_compute_disk" "missing" {}')
            usage = root / 'usage.yml'
            usage.write_text('version: "0.1"\nresource_usage:\n  google_compute_instance.x:\n    monthly_hrs: 8\n')
            with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'plugins': {}}), \
                 patch('src.python.cost_estimate.run_process', return_value=(1, json.dumps(raw).encode())), \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC'}):
                report = estimate(path=root, usage_file=usage, public_input=True, allow_external_pricing=True)
            self.assertEqual(report['usage']['effective_usage'], 'not_observed')
            self.assertNotIn('baseline_hours', report['usage'])
            self.assertEqual(report['usage']['reference_month_hours'], '730')
            for flag in ('scan_diagnostics', 'input_coverage_incomplete', 'flex_pricing_model_unverified',
                         'region_unverified', 'tool_defaults_not_observed'):
                self.assertIn(flag, report['warnings'])
                for style in ('json', 'table', 'markdown'):
                    rendered = format_report(report, style)
                    self.assertIn(flag, rendered)
                    self.assertIn('not_observed', rendered)
                    self.assertIn('8', rendered)
                    self.assertNotIn('CANARY', rendered)

    def test_export_normalizes_numeric_subtotal_to_money_string(self):
        from src.python.cost_estimate import normalized_report, format_report
        report = normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '10'}])
        report['covered_subtotal'] = 10
        self.assertEqual(json.loads(format_report(report, 'json'))['covered_subtotal'], '10')

    def test_lost_coverage_withholds_delta_and_exposes_warnings_in_every_format(self):
        from src.python.cost_estimate import normalized_report, compare_reports, format_report
        before = normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '10'}])
        after = normalized_report([{'id': 'x', 'state': 'unknown', 'monthly_cost': None}])
        after['timestamp'] = before['timestamp']
        result = compare_reports(before, after)
        self.assertIsNone(result['covered_subtotal_delta'])
        self.assertIsNone(result['changes'][0]['covered_monthly_delta'])
        self.assertIn('coverage_differs', result['warnings'])
        self.assertIn('tool_defaults_not_observed', result['warnings'])
        for style in ('table', 'json', 'markdown'):
            text = format_report(result, style)
            self.assertIn('coverage_differs', text)
            self.assertIn('tool_defaults_not_observed', text)
            self.assertIn(before['resources'][0]['id'], text)
            self.assertIn('unknown', text)
        # Equal counts can conceal a swap in which resource is covered.
        first = normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '10'},
                                   {'id': 'y', 'state': 'unknown', 'monthly_cost': None}])
        second = normalized_report([{'id': 'y', 'state': 'priced', 'monthly_cost': '10'},
                                    {'id': 'x', 'state': 'unknown', 'monthly_cost': None}])
        self.assertIsNone(compare_reports(first, second)['covered_subtotal_delta'])
        self.assertIn('coverage_differs', compare_reports(first, second)['warnings'])

    def test_region_is_derived_from_inputs_and_assertions_cannot_relabel_prices(self):
        from src.python.cost_estimate import estimate, compare_reports
        raw = {'currency': 'USD', 'projects': [{'resources': [{
            'name': 'google_compute_instance.x', 'type': 'google_compute_instance',
            'is_supported': True, 'is_free': True}]}]}
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / 'plan.json'
            def scan(zones, asserted=None):
                plan.write_text(json.dumps({'format_version': '1.2', 'planned_values': {'root_module': {
                    'resources': [{'address': 'google_compute_instance.' + ('x' if i == 0 else 'y'),
                                   'values': {'zone': zone}} for i, zone in enumerate(zones)]}}}))
                return estimate(saved_plan=plan, region=asserted, public_input=True, allow_external_pricing=True)
            with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'plugins': {}}), \
                 patch('src.python.cost_estimate.run_process', return_value=(0, json.dumps(raw).encode())) as run, \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC'}):
                east = scan(['us-east1-b'])
                self.assertEqual(east['region'], 'us-east1')
                self.assertEqual(east['region_status'], 'verified_single')
                west = scan(['europe-west1-b'])
                with self.assertRaises(ValueError):
                    compare_reports(east, west)
                run.reset_mock()
                conflict = scan(['us-east1-b'], 'europe-west1')
                self.assertEqual(conflict['reason'], 'region_conflicts_with_input')
                run.assert_not_called()
                for zones in ([None], ['us-east1-b', 'europe-west1-b']):
                    unresolved = scan(zones)
                    self.assertIsNone(unresolved['region'])
                    self.assertEqual(unresolved['status'], 'partial')
                    with self.assertRaises(ValueError):
                        compare_reports(unresolved, unresolved)
                plan.unlink()
                (Path(directory) / 'main.tf').write_text('resource "google_compute_instance" "x" { zone = "us-east1-b" }')
                conflict = estimate(path=directory, region='europe-west1', public_input=True, allow_external_pricing=True)
                self.assertEqual(conflict['reason'], 'region_conflicts_with_input')

    def test_escaped_or_computed_provisioning_models_never_receive_on_demand_prices(self):
        from src.python.cost_estimate import estimate
        raw = {'currency': 'USD', 'projects': [{'resources': [{
            'name': 'google_compute_instance.x', 'type': 'google_compute_instance',
            'is_supported': True, 'is_free': False, 'cost_components': [
                {'price': '1', 'quantity': '730', 'total_monthly_cost': '730'}]}]}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mode in ('saved_plan_json', 'json_hcl', 'computed_hcl'):
                with self.subTest(mode=mode):
                    path = root / ('main.tf' if mode == 'computed_hcl' else 'main.tf.json')
                    if mode == 'saved_plan_json':
                        value = {'format_version': '1.2', 'planned_values': {'root_module': {'resources': [{
                            'address': 'google_compute_instance.x', 'values': {'scheduling': [
                                {'provisioning_model': 'FLEX_START'}]}}]}}}
                    else:
                        value = {'resource': {'google_compute_instance': {'x': {
                            'scheduling': {'provisioning_model': 'FLEX_START'}}}}}
                    path.write_text('resource "google_compute_instance" "x" { scheduling { provisioning_model = var.model } }'
                                    if mode == 'computed_hcl' else json.dumps(value).replace('FLEX_START', r'FLEX\u005fSTART'))
                    with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'plugins': {}}), \
                         patch('src.python.cost_estimate.run_process', return_value=(0, json.dumps(raw).encode())), \
                         patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC'}):
                        report = estimate(**({'saved_plan': path} if mode == 'saved_plan_json' else {'path': root}),
                                          public_input=True, allow_external_pricing=True)
                    self.assertTrue(report['source']['flex_unverified'])
                    self.assertEqual(report['status'], 'partial')
                    self.assertIsNone(report['resources'][0]['monthly_cost'])
                    path.unlink()

    def test_executable_fifo_is_rejected_before_runtime_verification_can_block(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / 'infracost'
            os.mkfifo(fifo, 0o700)
            script = ('from src.python.cost_estimate import verify_runtime, CostRuntimeError\n'
                      'import sys\ntry: verify_runtime(sys.argv[1])\n'
                      'except CostRuntimeError as exc: print(str(exc))\n')
            try:
                result = subprocess.run([sys.executable, '-c', script, str(fifo)],
                                        capture_output=True, text=True, timeout=1)
            except subprocess.TimeoutExpired:
                self.fail('runtime snapshot blocked opening an executable FIFO')
            self.assertEqual(result.stdout.strip(), 'unsafe_binary')

    def test_comparison_exposes_per_resource_delta_and_flags_changed_coverage(self):
        from src.python.cost_estimate import normalized_report, compare_reports, format_report
        before = normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': '1.1'}])
        after = normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': '1.3'},
                                   {'id': 'b', 'state': 'unknown', 'monthly_cost': None}])
        result = compare_reports(before, after)
        changed = next(row for row in result['changes'] if row['change'] == 'changed')
        self.assertEqual(changed['covered_monthly_delta'], '0.2')
        self.assertIn('coverage_differs', result['warnings'])
        self.assertEqual(json.loads(format_report(result, 'json'))['changes'], result['changes'])
        with self.assertRaises(ValueError):
            compare_reports({**before, 'source': {'mode': 'hcl', 'binding': 'standalone_not_deployment_bound'}},
                            {**after, 'source': {'mode': 'hcl', 'binding': 'standalone_not_deployment_bound'}})

    def test_unavailable_estimate_retains_selected_scope_and_input_provenance(self):
        from src.python.cost_estimate import estimate
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'main.tf').write_text('resource "google_compute_disk" "example" {}')
            report = estimate(path=directory, scope='registry', public_input=True, allow_pricing=True,
                              infracost_binary='/missing/infracost')
            self.assertEqual(report['status'], 'unavailable')
            self.assertEqual(report['scope'], 'registry')
            self.assertEqual(len(report['source']['input_digest']), 64)
            self.assertEqual(report['counts']['unknown'], 1)
            self.assertIsNone(report['covered_subtotal'])

    def test_money_aggregation_does_not_use_ambient_decimal_precision(self):
        from src.python.cost_estimate import normalized_report, compare_reports
        from decimal import Decimal, localcontext
        amounts = ['1000000000000.123456789012345678', '0.123456789012345678']
        with localcontext() as context:
            context.prec = 60
            expected = str(sum(map(Decimal, amounts)))
        report = normalized_report([{'id': str(i), 'state': 'priced', 'monthly_cost': value} for i, value in enumerate(amounts)])
        self.assertEqual(report['covered_subtotal'], expected)

    def test_malformed_input_and_tiny_money_are_bounded_without_tracebacks(self):
        from src.python.cost_estimate import estimate, normalized_report
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'main.tf.json').write_text('{"resource": []}')
            report = estimate(path=directory, public_input=True, allow_pricing=True)
            self.assertEqual(report['status'], 'error')
        with self.assertRaises(ValueError):
            normalized_report([{'id': 'x', 'state': 'priced', 'monthly_cost': '1e-999999999'}])

    def test_runtime_platform_pins_include_verified_arm_archive_without_claiming_native_execution(self):
        from src.python.cost_estimate import runtime_platform, CostRuntimeError
        with patch('platform.system', return_value='Linux'), patch('platform.machine', return_value='aarch64'):
            architecture, checksum = runtime_platform()
            self.assertEqual(architecture, 'arm64')
            self.assertEqual(checksum, 'ce46b4ec6e40cf68473249737aab6288285a6c771465a91cccc69a7fa473243e')
        with patch('platform.system', return_value='Darwin'), self.assertRaises(CostRuntimeError):
            runtime_platform()

    def test_missing_usage_and_bad_runtime_response_are_sanitized_and_cleaned(self):
        from src.python.cost_estimate import estimate, CostRuntimeError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.tf').write_text('resource "google_compute_disk" "example" {}')
            report = estimate(path=root, usage_file=root / 'CANARY', public_input=True, allow_pricing=True)
            self.assertEqual(report['status'], 'error')
            self.assertNotIn('CANARY', json.dumps(report))
            locations = []
            def transport(argv, *, cwd, **kwargs):
                locations.append(Path(cwd))
                raise CostRuntimeError('timeout')
            with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'plugins': {}}), \
                 patch('src.python.cost_estimate.run_process', side_effect=transport), \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC'}):
                report = estimate(path=root, public_input=True, allow_pricing=True)
            self.assertEqual(report['reason'], 'timeout')
            self.assertTrue(all(not path.exists() for path in locations))

    def test_missing_input_resources_are_unknown_not_a_complete_quote(self):
        from src.python.cost_estimate import estimate
        raw = {'currency': 'USD', 'projects': [{'resources': [{
            'name': 'google_compute_disk.first', 'type': 'google_compute_disk', 'is_supported': True,
            'is_free': True}]}]}
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'main.tf.json').write_text(json.dumps({'resource': {'google_compute_disk': {'first': {}, 'missing': {}}}}))
            with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'plugins': {}}), \
                 patch('src.python.cost_estimate.run_process', return_value=(0, json.dumps(raw).encode())), \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC'}):
                report = estimate(path=directory, public_input=True, allow_pricing=True)
            self.assertEqual(report['status'], 'partial')
            self.assertEqual(report['counts']['unknown'], 1)
            self.assertNotIn('missing', json.dumps(report))

    def test_public_report_rejects_forged_values_and_strips_nested_secret_fields(self):
        from src.python.cost_estimate import normalized_report, format_report, compare_reports
        report = normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': '1'}])
        report['source'] = {'mode': 'hcl', 'input_digest': 'a' * 64, 'binding': 'standalone_not_deployment_bound', 'secret': 'CANARY'}
        report['tool'] = {'name': 'infracost', 'version': '2.16.3', 'schema': 'scan-v2.16.3', 'plugins': {}, 'secret': 'CANARY'}
        self.assertNotIn('CANARY', format_report(report, 'json'))
        forged = copy.deepcopy(report)
        forged['resources'][0]['id'] = 'CANARY'
        with self.assertRaises(ValueError):
            compare_reports(report, forged)
        forged = copy.deepcopy(report)
        forged['covered_subtotal'] = '99'
        with self.assertRaises(ValueError):
            compare_reports(report, forged)

    def test_usage_file_is_numeric_yaml_at_verified_config_boundary(self):
        from src.python.cost_estimate import estimate
        import yaml
        def transport(argv, *, cwd, **kwargs):
            root = Path(cwd) / 'input'
            config = yaml.safe_load((root / 'infracost.yml').read_text())
            self.assertEqual(config['version'], '0.3')
            self.assertEqual(config['usage_file'], 'usage.yml')
            usage = yaml.safe_load((root / 'usage.yml').read_text())
            self.assertEqual(usage['version'], '0.1')
            self.assertEqual(usage['resource_usage']['google_compute_instance.example']['monthly_hrs'], 8)
            self.assertEqual(usage['resource_usage']['google_storage_bucket.example']['storage_gb'], 100)
            return 0, b'{"currency":"USD","projects":[{"resources":[]}]}'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.tf').write_text('resource "google_compute_instance" "example" {}')
            usage = root / 'selected-usage.yml'
            usage.write_text('version: "0.1"\nresource_usage:\n  google_compute_instance.example:\n    monthly_hrs: 8\n  google_storage_bucket.example:\n    storage_gb: 100\n')
            with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'plugins': {}}), \
                 patch('src.python.cost_estimate.run_process', side_effect=transport), \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC'}):
                report = estimate(path=root, usage_file=usage, public_input=True, allow_pricing=True)
            self.assertEqual(report['usage']['basis'], 'explicit_file_with_tool_defaults')
            self.assertEqual(len(report['usage_digest']), 64)

    def test_runtime_verification_never_executes_missing_or_unpinned_binary(self):
        from src.python.cost_estimate import verify_runtime, CostRuntimeError
        with self.assertRaisesRegex(CostRuntimeError, 'binary_missing'):
            verify_runtime('/nonexistent/infracost')
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'infracost'
            binary.write_text('#!/bin/sh\nprintf CANARY')
            binary.chmod(0o700)
            with self.assertRaisesRegex(CostRuntimeError, 'binary_checksum_mismatch'):
                verify_runtime(binary)

    def test_estimate_stages_public_input_privately_and_normalizes_verified_protocol(self):
        from src.python.cost_estimate import estimate
        locations = []
        def transport(argv, *, cwd, environment, timeout, cancel_event=None):
            locations.append(Path(cwd))
            self.assertEqual(Path(argv[0]).read_bytes(), b'SYNTHETIC_RUNTIME_SNAPSHOT')
            self.assertEqual(argv[1:], ['scan', str(Path(cwd) / 'input'), '--currency', 'USD', '--json', '--no-color'])
            self.assertEqual(Path(cwd).stat().st_mode & 0o777, 0o700)
            self.assertEqual((Path(cwd) / 'input/main.tf').stat().st_mode & 0o777, 0o600)
            self.assertNotIn('AWS_SECRET_ACCESS_KEY', environment)
            self.assertEqual(environment['INFRACOST_CLI_EVENTS_ENDPOINT'], 'http://127.0.0.1:1')
            # v2 requires hosted read-only run parameters before pricing. Consent
            # covers that boundary; overriding to loopback would break every scan.
            self.assertNotIn('INFRACOST_CLI_DASHBOARD_ENDPOINT', environment)
            return 0, json.dumps({'currency': 'USD', 'projects': [{'resources': [{
                'name': 'google_compute_disk.example', 'type': 'google_compute_disk',
                'is_supported': True, 'is_free': False, 'cost_components': [{
                    'price': '0.1', 'quantity': '1', 'total_monthly_cost': '0.1', 'unit': 'GB'}]}]}]}).encode()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'main.tf').write_text('resource "google_compute_disk" "example" { size = 1 }')
            with patch('src.python.cost_estimate.verify_runtime', return_value={'binary': '/verified/infracost', 'binary_bytes': b'SYNTHETIC_RUNTIME_SNAPSHOT', 'plugins': {}}), \
                 patch('src.python.cost_estimate.run_process', side_effect=transport), \
                 patch.dict(os.environ, {'INFRACOST_CLI_AUTHENTICATION_TOKEN': 'SYNTHETIC', 'AWS_SECRET_ACCESS_KEY': 'CANARY'}):
                report = estimate(path=directory, public_input=True, allow_pricing=True)
            self.assertEqual(report['covered_subtotal'], '0.1')
            self.assertEqual(report['tool']['version'], '2.16.3')
            self.assertEqual(report['source']['binding'], 'standalone_not_deployment_bound')
            self.assertNotIn('CANARY', json.dumps(report))
            self.assertTrue(all(not location.exists() for location in locations))

    def test_json_hcl_and_exported_plan_preserve_snapshot_and_flag_flex(self):
        from src.python.cost_estimate import snapshot_input
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hcl = root / 'main.tf.json'
            hcl.write_text(json.dumps({'resource': {'google_compute_instance': {'x': {
                'machine_type': 'g4-standard-48', 'scheduling': {'provisioning_model': 'FLEX_START'}}}}}))
            files, source = snapshot_input(path=root)
            self.assertEqual(set(files), {'main.tf.json'})
            self.assertTrue(source['flex_unverified'])
            hcl.write_text(json.dumps({'module': {'x': {'source': '../CANARY'}}}))
            with self.assertRaises(ValueError):
                snapshot_input(path=root)
            plan = root / 'plan.json'
            plan.write_text(json.dumps({'format_version': '1.2', 'planned_values': {'root_module': {'resources': []}}}))
            files, source = snapshot_input(saved_plan=plan)
            self.assertEqual(files['plan.json'], plan.read_bytes())
            self.assertEqual(source['binding'], 'standalone_not_deployment_bound')
            self.assertEqual(source['mode'], 'saved_plan_json')
            plan.write_bytes(b'PK\x00native-plan')
            with self.assertRaises(ValueError):
                snapshot_input(saved_plan=plan)

    def test_process_boundary_bounds_output_timeout_cancel_and_sanitizes_errors(self):
        from src.python.cost_estimate import run_process, CostRuntimeError
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(run_process([sys.executable, '-c', 'print("ok")'], cwd=directory,
                                         environment={}, timeout=2), (0, b'ok\n'))
            for script, limit, expected in [('import time;time.sleep(4)', 0.1, 'timeout'),
                                           ('print("x" * 5000000)', 2, 'output_limit')]:
                with self.subTest(expected=expected), self.assertRaisesRegex(CostRuntimeError, expected):
                    run_process([sys.executable, '-c', script], cwd=directory, environment={}, timeout=limit)
            event = threading.Event()
            event.set()
            with self.assertRaisesRegex(CostRuntimeError, 'cancelled'):
                run_process([sys.executable, '-c', 'print("CANARY")'], cwd=directory,
                            environment={}, timeout=2, cancel_event=event)

    def test_exports_drop_extra_fields_and_validate_money_identity_and_coverage(self):
        from src.python.cost_estimate import normalized_report, format_report
        report = normalized_report([{'id': 'SECRET_CANARY', 'state': 'priced', 'monthly_cost': '1',
                                     'tags': {'password': 'SECRET_CANARY'}}])
        report['raw'] = 'SECRET_CANARY'
        report['resources'][0]['tags'] = 'SECRET_CANARY'
        for style in ('json', 'table', 'markdown'):
            self.assertNotIn('SECRET_CANARY', format_report(report, style))
        for amount in ['NaN', 'Infinity', '-1', '1e999', True]:
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': amount}])
        with self.assertRaises(ValueError):
            normalized_report([{'id': 'a', 'state': 'free', 'monthly_cost': '1'}])
        with self.assertRaises(ValueError):
            normalized_report([], currency='SECRET_CANARY')

    def test_source_snapshot_is_bounded_and_rejects_execution_or_indirect_inputs(self):
        from src.python.cost_estimate import snapshot_input
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hcl = root / 'main.tf'
            hcl.write_text('resource "google_compute_disk" "example" { size = 10 }')
            files, metadata = snapshot_input(path=root)
            self.assertEqual(set(files), {'main.tf'})
            self.assertEqual(len(metadata['input_digest']), 64)
            self.assertEqual(metadata['binding'], 'standalone_not_deployment_bound')
            for text in ['module "x" { source = "./x" }', 'data "external" "x" {}',
                         'locals { x = file("/secret") }', 'resource "x" "x" { provisioner "local-exec" {} }']:
                hcl.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    snapshot_input(path=root)
            hcl.unlink()
            hcl.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                snapshot_input(path=root)

    def test_estimate_requires_explicit_public_pricing_consent_and_rejects_unbound_modes(self):
        from src.python.cost_estimate import estimate
        for options, reason in [({}, 'select_one_input'), ({'profile': 'CANARY'}, 'profile_not_bound'),
                                ({'deployment': 'CANARY'}, 'deployment_not_bound'),
                                ({'path': '/CANARY'}, 'external_pricing_consent_required'),
                                ({'path': '/CANARY', 'allow_external_pricing': True}, 'private_input_not_approved')]:
            report = estimate(**options)
            self.assertIn(report['status'], ('unsupported', 'error'))
            self.assertEqual(report['reason'], reason)
            self.assertIsNone(report['covered_subtotal'])
            self.assertNotIn('CANARY', json.dumps(report))

    def test_usage_validates_nonsecret_per_resource_quantities_without_scaling_retention(self):
        from src.python.cost_estimate import validate_usage
        usage = {'version': 1, 'resource_usage': {
            'google_compute_instance.example': {'monthly_hrs': '8'},
            'google_storage_bucket.example': {'storage_gb': '100', 'monthly_egress_data_transfer_gb': '2'}}}
        result = validate_usage(usage)
        self.assertEqual(result['resource_usage']['google_storage_bucket.example']['storage_gb'], '100')
        for bad in ({**usage, 'secret': 'CANARY'}, {'version': 1, 'resource_usage': {'x': {'monthly_hrs': -1}}},
                    {'version': 1, 'resource_usage': {'x': {'monthly_hrs': 'NaN'}}},
                    {'version': 1, 'resource_usage': {'x': {'password': 'CANARY'}}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_usage(bad)

    def test_comparison_rejects_incompatible_reports_and_keeps_partial_delta(self):
        from src.python.cost_estimate import normalized_report, compare_reports
        before = normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': '0.1'}])
        after = normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': '0.3'},
                                   {'id': 'b', 'state': 'unknown', 'monthly_cost': None}])
        compared = compare_reports(before, after)
        self.assertIsNone(compared['covered_subtotal_delta'])
        self.assertEqual(compared['status'], 'partial')
        self.assertEqual(len(compared['added']), 1)
        for key, value in [('currency', 'EUR'), ('unit', 'hour'), ('scope', 'registry'),
                           ('usage_digest', 'different'), ('region', 'different')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare_reports(before, {**after, key: value})

    def test_decimal_covered_subtotal_preserves_unknown_and_free(self):
        from src.python.cost_estimate import normalized_report, format_report
        report = normalized_report([
            {'id': 'a', 'monthly_cost': '0.1', 'state': 'priced'},
            {'id': 'b', 'monthly_cost': '0.2', 'state': 'priced'},
            {'id': 'c', 'monthly_cost': '0', 'state': 'free'},
            {'id': 'd', 'monthly_cost': None, 'state': 'unknown'},
        ], currency='USD', scope='workstation')
        self.assertEqual(report['covered_subtotal'], '0.3')
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['counts'], dict(priced=2, free=1, unknown=1, unpriced=0))
        self.assertNotIn('total', report)
        self.assertEqual(json.loads(format_report(report, 'json')), report)
        self.assertIn('Covered subtotal', format_report(report))


if __name__ == '__main__':
    unittest.main()
