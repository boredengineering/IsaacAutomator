"""Read-only checker qualification: SYNTHETIC metadata/protocol, not real runtimes."""
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ContainerRuntimeCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-runtime-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / 'prepared-runtime'
        self.lib = self.env / 'lib/python3.11/site-packages'
        self.lib.mkdir(parents=True)
        self.source = self.root / 'source'
        self.build = self.root / 'build'
        self.source.mkdir()
        self.build.mkdir()
        self.interpreter = self.env / 'bin/python'
        self.interpreter.parent.mkdir()
        self.observation = dict(protocol=1, version='3.11.9', executable=str(self.interpreter),
                                prefix=str(self.env), base_prefix=str(self.env),
                                package_paths=[str(self.lib)], isolated=1, no_site=1)
        self.runtime: dict = dict(intent=dict(manager='uv', environment='selected', python='3.11',
                                       torch='2.7.0', torchvision='0.22.0'),
            environment_container=str(self.env),
            components={'gr00t': dict(enabled=True, runtime='gr00t', source=dict(
                mode='git', repository='https://github.com/NVIDIA/Isaac-GR00T.git', ref='main'))},
            build_outputs=[dict(component='gr00t', source_container=str(self.source),
                                container=str(self.build))],
            check=dict(interpreter=str(self.interpreter), distributions={},
                source_bindings=[dict(component='gr00t', distribution='synthetic-gr00t',
                                      source_container=str(self.source))]))
        for name, version in [('torch', '2.7.0'), ('torchvision', '0.22.0'), ('synthetic-gr00t', '0.0.0')]:
            path = self.lib / (name.replace('-', '_') + '-' + version + '.dist-info')
            path.mkdir()
            (path / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')
            self.runtime['check']['distributions'][name] = str(path)
        self.origin = Path(self.runtime['check']['distributions']['synthetic-gr00t']) / 'direct_url.json'
        self.origin.write_text(json.dumps(dict(url=self.source.as_uri(), dir_info=dict(editable=True))))
        self.write_interpreter()

    def write_interpreter(self, extra=''):
        # Deliberate protocol test double, never represented as a Python runtime.
        self.interpreter.write_text('#!/usr/bin/env -S ' + sys.executable + ' -I -S -B\n' +
            'import json,sys\n' +
            'assert sys.argv[1:5] == ["-I", "-S", "-B", "-c"]\n' + extra + '\n' +
            'print(' + repr(json.dumps(self.observation)) + ')\n')
        self.interpreter.chmod(0o700)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.container_runtime_check'),
                             'read-only runtime checker consumer is missing')
        return importlib.import_module('src.python.container_runtime_check')

    def rows(self, result):
        return {item['field']: item for item in result['checks']}

    def test_actual_checker_consumes_selected_protocol_and_metadata_without_imports(self):
        result = self.module().check_runtime(self.runtime)
        rows = self.rows(result)
        for field in ('python', 'prefix', 'executable', 'packages.torch', 'packages.torchvision',
                      'sources.gr00t.origin', 'builds.gr00t.location'):
            self.assertEqual(rows[field]['status'], 'matching', (field, rows))
        self.assertTrue(result['selected_checks_match'])
        self.assertFalse(result['runtime_parity_verified'])
        self.assertEqual(rows['sources.gr00t.editability']['status'], 'unsupported')
        self.assertEqual(rows['builds.gr00t.backend']['status'], 'unsupported')
        self.assertEqual(rows['gpu_abi']['status'], 'unsupported')

    def test_mismatch_and_missing_observations_fail_closed(self):
        module = self.module()
        for key, wrong in [('version', '3.10.9'), ('prefix', str(self.root / 'wrong-prefix')),
                           ('executable', str(self.root / 'wrong-python'))]:
            original = self.observation[key]
            self.observation[key] = wrong
            self.write_interpreter()
            self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'], key)
            self.observation[key] = original
        self.write_interpreter()
        for name in ('torch', 'torchvision'):
            path = Path(self.runtime['check']['distributions'][name]) / 'METADATA'
            original = path.read_text()
            path.write_text(f'Name: {name}\nVersion: 9.9.9\n')
            rows = self.rows(module.check_runtime(self.runtime))
            self.assertEqual(rows['packages.' + name]['status'], 'mismatching')
            path.unlink()
            self.assertEqual(self.rows(module.check_runtime(self.runtime))['packages.' + name]['status'], 'missing')
            path.write_text(original)
        self.origin.write_text(json.dumps(dict(url=(self.root / 'different-source').as_uri())))
        self.assertEqual(self.rows(module.check_runtime(self.runtime))['sources.gr00t.origin']['status'], 'mismatching')
        self.build.rmdir()
        self.assertEqual(self.rows(module.check_runtime(self.runtime))['builds.gr00t.location']['status'], 'missing')

    def test_missing_build_binding_and_intent_are_not_silently_ready(self):
        self.runtime['build_outputs'] = []
        result = self.module().check_runtime(self.runtime)
        self.assertFalse(result['selected_checks_match'])
        self.assertEqual(self.rows(result)['builds.gr00t.location']['status'], 'missing')
        self.runtime['check']['source_bindings'] = []
        self.assertEqual(self.rows(self.module().check_runtime(self.runtime))['sources.gr00t.origin']['status'], 'missing')

    def test_unknown_readiness_and_unbounded_input_rejected_before_probe(self):
        from unittest import mock
        module = self.module()
        for update in ({'ready': True}, {'distributions': {f'data{i}': '/tmp/item' for i in range(129)}},
                       {'source_bindings': [self.runtime['check']['source_bindings'][0]] * 129}):
            runtime = copy.deepcopy(self.runtime)
            runtime['check'].update(update)
            with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('probe before validation')):
                with self.assertRaises(ValueError):
                    module.check_runtime(runtime)

    def test_metadata_is_bounded_no_follow_data_not_project_imports(self):
        module = self.module()
        marker = self.root / 'FORBIDDEN-IMPORT'
        # These files would execute if site/project hooks were ever evaluated.
        (self.lib / 'evil.pth').write_text(f'import pathlib; pathlib.Path({str(marker)!r}).touch()\n')
        (self.source / 'sitecustomize.py').write_text(f'open({str(marker)!r}, "w").close()')
        (self.source / 'torch.py').write_text('raise AssertionError("Torch import forbidden")')
        self.assertTrue(module.check_runtime(self.runtime)['selected_checks_match'])
        self.assertFalse(marker.exists())
        metadata = Path(self.runtime['check']['distributions']['torch']) / 'METADATA'
        metadata.write_text('x' * (module.MAX_BYTES + 1))
        self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'])
        metadata.unlink()
        outside = self.root / 'not-installed-metadata'
        outside.write_text('Name: torch\nVersion: 2.7.0\n')
        metadata.symlink_to(outside)
        self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'])

    def test_fixture_protocol_is_isolated_bounded_and_never_trusted_ready(self):
        module = self.module()
        self.write_interpreter('assert sys.flags.isolated and sys.flags.no_site\nassert set(__import__("os").environ) <= {"LC_ALL", "LC_CTYPE"}\nassert __import__("os").getcwd() == "/"')
        self.assertTrue(module.check_runtime(self.runtime)['selected_checks_match'])
        self.observation['isolated'] = 0
        self.observation['ready'] = True
        self.write_interpreter()
        self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'])
        self.write_interpreter('print("x" * 140000)')
        self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'])
        self.write_interpreter('import time; time.sleep(1)')
        self.assertFalse(module.check_runtime(self.runtime, timeout=0.05)['selected_checks_match'])

    def candidate_spec(self) -> dict:
        return dict(engine='rsync', image='example.invalid/preprepared:test-data',
            mappings=[dict(name='repo', kind='source', local=str(self.root / 'local-source'),
                           remote=str(self.root / 'remote-source'), container=str(self.source)),
                      dict(name='cfg', kind='config', local=str(self.root / 'local-config'),
                           remote=str(self.root / 'remote-config'), container=str(self.root / 'container-config'))],
            desired_profile=dict(schema_version='v1alpha1', kind='workstation-profile', name='synthetic',
                defaults=False, components=self.runtime['components'], runtimes={'gr00t': self.runtime['intent']}),
            runtime_placements={'gr00t': dict(environment=str(self.env),
                builds=[dict(component='gr00t', source_mapping='repo', remote=str(self.root / 'remote-build'),
                             container=str(self.build))],
                check=dict(interpreter=str(self.interpreter), distributions=self.runtime['check']['distributions'],
                    source_bindings=[dict(component='gr00t', distribution='synthetic-gr00t', source_mapping='repo')],
                    bundle=dict(config_mapping='cfg', relative_path='runtime-review')) )})

    def test_rendered_checker_bundle_runs_manually_from_selected_config_mapping(self):
        from src.python.remote_development import render_candidate
        spec = self.candidate_spec()
        out = self.root / 'candidate'
        result = render_candidate(spec, out, reviewed=True)
        manifest = result['runtime_manifest']
        self.assertEqual((out / 'container_runtime_check.py').read_bytes(), Path(str(self.module().__file__)).read_bytes())
        self.assertFalse(manifest['image_verified'])
        check = manifest['runtimes']['gr00t']['check']
        bundle = check['bundle']
        self.assertEqual(bundle['local'], str(self.root / 'local-config/runtime-review'))
        self.assertEqual(bundle['remote'], str(self.root / 'remote-config/runtime-review'))
        self.assertEqual(bundle['container'], str(self.root / 'container-config/runtime-review'))
        self.assertEqual(bundle['manual_argv'], [str(self.interpreter), '-I', '-S', '-B',
            bundle['container'] + '/container_runtime_check.py', '--manifest',
            bundle['container'] + '/runtime-placement.json', '--runtime', 'gr00t'])
        self.assertNotIn('Command', ''.join(result['devcontainer']))
        self.assertFalse(Path(bundle['local']).exists())
        # Manual placement into new SYNTHETIC in-container config, not real config.
        target = Path(bundle['container'])
        target.mkdir(parents=True)
        for filename in bundle['files']:
            (target / filename).write_bytes((out / filename).read_bytes())
        # Test interpreter delegates the script path to the existing test Python;
        # only the -c observation reply is synthetic. No venv/package installation.
        self.interpreter.write_text('#!/usr/bin/env -S ' + sys.executable + ' -I -S -B\nimport sys,os\n' +
            'if sys.argv[4] != "-c": os.execv(' + repr(sys.executable) + ', [' + repr(sys.executable) + '] + sys.argv[1:])\n' +
            'assert sys.argv[1:5] == ["-I", "-S", "-B", "-c"]\n' +
            'print(' + repr(json.dumps(self.observation)) + ')\n')
        execution = subprocess.run(bundle['manual_argv'], capture_output=True, text=True, timeout=10,
                                   env={'LC_ALL': 'C'}, cwd='/')
        self.assertEqual(execution.returncode, 0, execution.stderr + execution.stdout)
        receipt = json.loads(execution.stdout)
        self.assertTrue(receipt['selected_checks_match'])
        self.assertFalse(receipt['runtime_parity_verified'])
        self.origin.write_text(json.dumps(dict(url=(self.root / 'wrong-origin').as_uri())))
        failed = subprocess.run(bundle['manual_argv'], capture_output=True, text=True, timeout=10,
                                env={'LC_ALL': 'C'}, cwd='/')
        self.assertEqual(failed.returncode, 1, failed.stdout)
        self.assertFalse(json.loads(failed.stdout)['selected_checks_match'])
        self.assertIn('manually', (out / 'runtime-check.README.md').read_text())
        with self.assertRaises(FileExistsError):
            render_candidate(spec, out, reviewed=True)

    def test_standalone_kit_does_not_require_editable_source_build(self):
        from src.python.remote_development import build_plan
        spec = self.candidate_spec()
        spec['desired_profile']['components'] = {'sim': dict(enabled=True, runtime='kit', source=dict(mode='standalone', version='6.0.1'))}
        spec['desired_profile']['runtimes'] = {'kit': dict(manager='bundled', environment='kit')}
        spec['runtime_placements'] = {'kit': dict(environment='/opt/standalone-kit')}
        manifest = build_plan(spec)['runtime_manifest']
        self.assertFalse(any('editable build' in row['reason'] for row in manifest['issues']))
        self.assertEqual(manifest['build_mounts'], [])
        self.assertFalse(manifest['runtime_parity_verified'])

    def test_manifest_issues_block_observation_instead_of_trusting_intent(self):
        from unittest import mock
        module = self.module()
        self.assertTrue(hasattr(module, 'check_manifest'), 'manifest consumer must enforce placement issues')
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('unsafe placement probe')):
            result = module.check_manifest(dict(runtimes={'gr00t': self.runtime},
                issues=[dict(field='runtime_placements.gr00t', reason='writable location overlap')]), 'gr00t')
        self.assertFalse(result['selected_checks_match'])
        self.assertEqual(self.rows(result)['manifest.runtime_placements.gr00t']['status'], 'missing')

    def test_checker_input_cannot_launch_outside_prefix_or_with_overlap(self):
        from unittest import mock
        module = self.module()
        for mutation in ('outside', 'overlap'):
            runtime = copy.deepcopy(self.runtime)
            if mutation == 'outside':
                runtime['check']['interpreter'] = str(self.root / 'not-selected/python')
            else:
                runtime['check']['source_bindings'][0]['source_container'] = str(self.env)
            with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('unsafe probe')):
                with self.assertRaises(ValueError):
                    module.check_runtime(runtime)

    def test_protocol_code_itself_runs_with_only_synthetic_sysconfig_data(self):
        module = self.module()
        fixture = ('import sys,types\n' +
            'sys.version_info=(3,11,9)\nsys.prefix="/fixture/prepared"\nsys.base_prefix="/fixture/prepared"\n' +
            'sys.executable="/fixture/prepared/bin/python"\n' +
            'cfg=types.ModuleType("sysconfig")\n' +
            'cfg.get_paths=lambda:{"purelib":"/fixture/prepared/lib", "platlib":"/fixture/prepared/lib"}\n' +
            'sys.modules["sysconfig"]=cfg\n' + module.PROTOCOL_CODE)
        # Executes the real protocol code against explicit test data; no runtime
        # scan and no actual sysconfig.get_paths of the test host.
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', fixture],
            env={'LC_ALL': 'C'}, cwd=str(self.source), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['prefix'], '/fixture/prepared')
        self.assertEqual(observed['package_paths'], ['/fixture/prepared/lib'])
        self.assertEqual((observed['isolated'], observed['no_site']), (1, 1))

    def test_custom_selection_paths_cannot_shadow_source_or_protection(self):
        from src.python.remote_development import build_plan, render_candidate
        from unittest import mock
        spec = self.candidate_spec()
        for namespace in ('local', 'remote', 'container'):
            case = copy.deepcopy(spec)
            case['protected_paths'] = [dict(namespace=namespace,
                path=case['mappings'][1][namespace] + '/runtime-review/saved')]
            with self.assertRaisesRegex(ValueError, 'protected'):
                render_candidate(case, self.root / ('blocked-' + namespace), reviewed=True)
            self.assertFalse((self.root / ('blocked-' + namespace)).exists())
        for path in ('../escape', 'nested/../../escape', '.vscode/new', 'state/check', 'normal/.ssh/check'):
            case = copy.deepcopy(spec)
            case['runtime_placements']['gr00t']['check']['bundle']['relative_path'] = path
            with self.assertRaises(ValueError):
                build_plan(case)
        for field in ('interpreter', 'distributions'):
            case = copy.deepcopy(spec)
            check = case['runtime_placements']['gr00t']['check']
            if field == 'interpreter':
                check[field] = str(self.source / 'bin/python')
            else:
                check[field]['torch'] = str(self.source / 'torch.dist-info')
            with self.assertRaises(ValueError):
                build_plan(case)
        case = copy.deepcopy(spec)
        case['runtime_placements']['gr00t']['check']['bundle']['config_mapping'] = 'repo'
        with self.assertRaises(ValueError):
            build_plan(case)
        # Complete explicit selection is still pure: no selected paths inspected.
        with mock.patch.object(Path, 'stat', side_effect=AssertionError('target stat')), \
             mock.patch.object(Path, 'lstat', side_effect=AssertionError('target stat')), \
             mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('target executable')):
            plan = build_plan(spec)
        self.assertTrue(plan['runtime_manifest']['checker_selection_complete'])

    def test_no_profile_candidates_remain_exactly_two_files_and_no_checker(self):
        from src.python.remote_development import render_candidate
        spec = self.candidate_spec()
        del spec['desired_profile']
        del spec['runtime_placements']
        output = self.root / 'no-profile'
        result = render_candidate(spec, output, reviewed=True)
        self.assertEqual({p.name for p in output.iterdir()}, {'devcontainer.json', 'review.json'})
        self.assertNotIn('runtime_manifest', result)

    def test_missing_source_and_unverified_capabilities_are_explicit(self):
        runtime = copy.deepcopy(self.runtime)
        runtime['components']['gr00t'].pop('source')
        result = self.module().check_runtime(runtime)
        self.assertFalse(result['selected_checks_match'])
        self.assertEqual(self.rows(result)['sources.gr00t']['status'], 'missing')
        self.assertFalse(result['image_verified'])
        self.assertFalse(result['gpu_abi_verified'])
        self.assertEqual(self.rows(result)['runtime_manager']['status'], 'unsupported')

    def test_invalid_metadata_and_protocol_data_fail_without_following_or_echoing(self):
        module = self.module()
        metadata = Path(self.runtime['check']['distributions']['torch']) / 'METADATA'
        for raw in ('Name: torch\nName: other\nVersion: 2.7.0\n',
                    'Name: torchvision\nVersion: 2.7.0\n'):
            metadata.write_text(raw)
            self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'])
        metadata.unlink()
        os.mkfifo(metadata)
        self.assertFalse(module.check_runtime(self.runtime)['selected_checks_match'])
        metadata.unlink()
        metadata.write_text('Name: torch\nVersion: 2.7.0\n')
        self.origin.write_text('{"url":"file:///first/source","url":"file:///second/source"}')
        self.assertEqual(self.rows(module.check_runtime(self.runtime))['sources.gr00t.origin']['status'], 'missing')
        for raw in ('{"url":1}', '{"url":{}}', '[1,2]', '{"url":null}'):
            self.origin.write_text(raw)
            self.assertEqual(self.rows(module.check_runtime(self.runtime))['sources.gr00t.origin']['status'], 'missing')
        # A deeply nested bounded JSON file should produce the normal error code.
        invalid = self.root / 'invalid-manifest.json'
        invalid.write_text('[' * 1100 + ']' * 1100)
        run = subprocess.run([sys.executable, '-I', '-S', '-B', str(module.__file__),
                              '--manifest', str(invalid), '--runtime', 'gr00t'],
                             env={'LC_ALL': 'C'}, capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stderr, '')
        self.assertIn('error', json.loads(run.stdout))


if __name__ == '__main__':
    unittest.main()
