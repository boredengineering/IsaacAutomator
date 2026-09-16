"""Offline development workflow; only disposable local endpoints can execute."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


class RemoteDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.spec = {
            'engine': 'rsync', 'image': 'example.invalid/robotics:review-me',
            'mappings': [dict(name='repo', kind='source', local=str(self.source),
                              remote=str(self.root / 'remote-source'), container='/workspaces/repo'),
                         dict(name='results', kind='artifacts', local=str(self.root / 'results'),
                              remote=str(self.root / 'remote-results'), container='/outputs/results')],
        }

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.remote_development'),
                             'offline workflow module is missing')
        return importlib.import_module('src.python.remote_development')

    def test_desired_profile_becomes_exact_runtime_placement_candidate(self):
        import json
        profile = dict(schema_version='v1alpha1', kind='workstation-profile', name='selected',
            defaults=False, components={'gr00t': dict(enabled=True, runtime='gr00t', execution='native',
                source=dict(mode='git', repository='https://github.com/NVIDIA/Isaac-GR00T.git',
                            ref='selected-tag', revision='a' * 40))},
            runtimes={'gr00t': dict(manager='uv', environment='training', python='3.11', torch='2.7.0')},
            environments=[dict(id='environment:training', name='training', manager='uv', python='3.11',
                placement='project', location='/selected/original/env', required=True, support='unsupported')])
        placement = {'gr00t': dict(environment='/opt/envs/training', builds=[dict(component='gr00t',
            source_mapping='repo', remote=str(self.root / 'build-output'), container='/build/gr00t')])}
        spec = dict(self.spec, desired_profile=profile, runtime_placements=placement)
        result = self.module().render_candidate(spec, self.root / 'candidate', reviewed=True)
        manifest = result['runtime_manifest']
        self.assertEqual(manifest['desired_profile'], profile)
        selected = manifest['runtimes']['gr00t']
        self.assertEqual(selected['intent'], profile['runtimes']['gr00t'])
        self.assertEqual(selected['environment_container'], '/opt/envs/training')
        self.assertEqual(selected['components']['gr00t']['source'], profile['components']['gr00t']['source'])
        self.assertEqual(selected['build_outputs'][0]['source_container'], '/workspaces/repo')
        self.assertFalse(manifest['runtime_parity_verified'])
        self.assertFalse(manifest['issues'])
        self.assertIn('type=bind,source=' + str(self.root / 'build-output') + ',target=/build/gr00t',
                      result['devcontainer']['mounts'])
        self.assertEqual(json.loads((self.root / 'candidate/runtime-placement.json').read_text()), manifest)
        self.assertNotIn('postCreateCommand', result['devcontainer'])

    def test_runtime_placement_conflicts_and_unknowns_are_reported_without_target_stat(self):
        from unittest import mock
        profile = dict(schema_version='v1alpha1', kind='workstation-profile', name='draft', defaults=False,
            components={'gr00t': dict(enabled=True, runtime='gr00t')}, runtimes={'gr00t': dict(manager='uv')},
            future_field='do-not-copy-unknown-values')
        spec = dict(self.spec, desired_profile=profile, runtime_placements={'gr00t': dict(
            environment='/workspaces/repo/env', builds=[dict(component='gr00t', source_mapping='repo',
                remote=str(self.source / 'build'), container='/workspaces/repo/build')])})
        with mock.patch.object(Path, 'stat', side_effect=AssertionError('target stat')), \
             mock.patch.object(Path, 'lstat', side_effect=AssertionError('target lstat')):
            manifest = self.module().build_plan(spec)['runtime_manifest']
        self.assertTrue(any(i['field'] == 'future_field' for i in manifest['issues']))
        self.assertTrue(any('overlap' in i['reason'] for i in manifest['issues']))
        self.assertTrue(any('source' in i['reason'] for i in manifest['issues']))
        self.assertNotIn('future_field', manifest['desired_profile'])
        self.assertEqual(manifest['build_mounts'], [])
        self.assertFalse(manifest['placement_complete'])
        result = self.module().render_candidate(spec, self.root / 'candidate', reviewed=True)
        self.assertEqual(len(result['devcontainer']['mounts']), 1)
        # A non-conflicting writable mount still cannot cover protection or active settings.
        for path in (str(self.root / 'protected'), str(self.root / '.devcontainer/build')):
            protected_spec = dict(spec, protected_paths=[dict(namespace='remote', path=str(self.root / 'protected'))],
                runtime_placements={'gr00t': dict(environment='/opt/envs/gr00t', builds=[dict(
                    component='gr00t', source_mapping='repo', remote=path, container='/build/gr00t')])})
            blocked = self.module().build_plan(protected_spec)['runtime_manifest']
            self.assertEqual(blocked['build_mounts'], [])
            self.assertTrue(blocked['issues'])

    def test_candidate_output_cannot_overlap_editable_build_mounts(self):
        profile = dict(schema_version='v1alpha1', kind='workstation-profile', name='selected', defaults=False,
            components={'gr00t': dict(enabled=True, runtime='gr00t', source=dict(mode='git',
                repository='https://github.com/NVIDIA/Isaac-GR00T.git', ref='main'))},
            runtimes={'gr00t': dict(manager='uv', environment='training')})
        spec = dict(self.spec, desired_profile=profile, runtime_placements={'gr00t': dict(
            environment='/opt/envs/training', builds=[dict(component='gr00t', source_mapping='repo',
                remote=str(self.root / 'candidate'), container='/build/gr00t')])})
        with self.assertRaisesRegex(ValueError, 'build'):
            self.module().render_candidate(spec, self.root / 'candidate', reviewed=True)
        self.assertFalse((self.root / 'candidate').exists())

    def test_editable_build_mount_refuses_excluded_credential_root(self):
        profile = dict(schema_version='v1alpha1', kind='workstation-profile', name='selected', defaults=False,
            components={'gr00t': dict(enabled=True, runtime='gr00t', source=dict(mode='git',
                repository='https://github.com/NVIDIA/Isaac-GR00T.git', ref='main'))},
            runtimes={'gr00t': dict(manager='uv', environment='training')})
        spec = dict(self.spec, desired_profile=profile, runtime_placements={'gr00t': dict(
            environment='/opt/envs/training', builds=[dict(component='gr00t', source_mapping='repo',
                remote=str(self.root / '.ssh'), container='/build/gr00t')])})
        manifest = self.module().build_plan(spec)['runtime_manifest']
        self.assertEqual(manifest['build_mounts'], [])
        self.assertTrue(any('excluded' in issue['reason'] for issue in manifest['issues']))

    def test_missing_runtime_and_conflicting_environment_declarations_are_visible(self):
        profile = dict(schema_version='v1alpha1', kind='workstation-profile', name='selected', defaults=False,
            components={'gr00t': dict(enabled=True, runtime='gr00t')})
        manifest = self.module().build_plan(dict(self.spec, desired_profile=profile))['runtime_manifest']
        self.assertFalse(manifest['placement_complete'])
        self.assertTrue(any('runtime' in issue['reason'] for issue in manifest['issues']))
        profile['runtimes'] = {'gr00t': dict(manager='uv', environment='training', python='3.11')}
        profile['environments'] = [dict(id='environment:training', name='training', manager='conda',
            python='3.10', location='/selected/env', placement='project', required=True, support='unsupported')]
        manifest = self.module().build_plan(dict(self.spec, desired_profile=profile))['runtime_manifest']
        self.assertTrue(any('environment disagreement' in issue['reason'] for issue in manifest['issues']))
        self.assertEqual(manifest['runtimes']['gr00t']['intent']['python'], '3.11')

    def test_qualified_fixture_uses_system_rsync_and_private_process_context(self):
        import os
        import subprocess
        from unittest import mock
        if not Path('/usr/bin/rsync').is_file():
            self.skipTest('trusted /usr/bin/rsync unavailable; no PATH fallback')
        original_run = subprocess.run
        contexts = []
        def inspect_run(argv, **kwargs):
            self.assertEqual(argv[0], '/usr/bin/rsync')
            env = kwargs['env']
            self.assertEqual(set(env), {'PATH', 'HOME', 'LC_ALL', 'TMPDIR', 'XDG_CONFIG_HOME'})
            self.assertEqual(env['PATH'], '/usr/bin:/bin')
            home = Path(env['HOME'])
            self.assertTrue(home.is_dir())
            self.assertEqual(list(home.iterdir()), [])
            self.assertEqual(kwargs['cwd'], str(home))
            self.assertEqual(env['TMPDIR'], str(home))
            self.assertEqual(env['XDG_CONFIG_HOME'], str(home))
            contexts.append(home)
            return original_run(argv, **kwargs)
        with self.module().local_fixture() as fixture:
            source = fixture.root / 'source'
            source.mkdir()
            (source / 'hello').write_bytes(b'qualified local bytes')
            spec = dict(engine='rsync', mappings=[dict(name='repo', kind='source',
                local=str(source), remote=str(fixture.root / 'target'), container='/workspaces/repo')])
            # Nonexistent PATH is a negative control, never an executable hook.
            ambient = {'PATH': str(fixture.root / 'no-executables'), 'RSYNC_RSH': 'forbidden',
                       'LD_PRELOAD': 'forbidden', 'PYTHONPATH': 'forbidden', 'HOME': str(self.root)}
            with mock.patch.dict(os.environ, ambient), mock.patch('subprocess.run', side_effect=inspect_run):
                fixture.transfer(spec)
            self.assertEqual((fixture.root / 'target/hello').read_bytes(), b'qualified local bytes')
        self.assertTrue(contexts)
        self.assertTrue(all(not home.exists() for home in contexts))

    def test_reviewed_seed_repairs_equal_metadata_using_checksum(self):
        import os
        import subprocess
        from unittest import mock
        if not Path('/usr/bin/rsync').is_file():
            self.skipTest('trusted /usr/bin/rsync unavailable')
        original_run = subprocess.run
        with self.module().local_fixture() as fixture:
            source, target = fixture.root / 'source', fixture.root / 'target'
            source.mkdir()
            target.mkdir()
            (source / 'code').write_bytes(b'new bytes')
            (target / 'code').write_bytes(b'old bytes')
            for path in (source / 'code', target / 'code'):
                os.utime(path, ns=(1700000000000000000, 1700000000000000000))
            spec = dict(engine='rsync', initial_seed='reviewed-overwrite', overwrite_approved=True,
                mappings=[dict(name='repo', kind='source', local=str(source), remote=str(target),
                               container='/workspaces/repo')])
            with mock.patch('subprocess.run', wraps=original_run) as process:
                fixture.transfer(spec)
            self.assertEqual((target / 'code').read_bytes(), b'new bytes')
            self.assertIn('--checksum', process.call_args.args[0])

    def test_seed_receipt_verifies_preflight_bytes_not_process_success(self):
        import subprocess
        from unittest import mock
        for corruption in ('missing-copy', 'both-endpoints-changed', 'source-changed', 'orphan-retained'):
            with self.subTest(corruption=corruption), self.module().local_fixture() as fixture:
                source, target = fixture.root / 'source', fixture.root / 'target'
                source.mkdir()
                target.mkdir()
                (source / 'code').write_bytes(b'intended-before-launch')
                (target / 'orphan').write_bytes(b'stale')
                spec = dict(engine='rsync', initial_seed='reviewed-overwrite', overwrite_approved=True,
                    delete=True, delete_approved=True, mappings=[dict(name='repo', kind='source',
                    local=str(source), remote=str(target), container='/workspaces/repo')])
                def report_success_without_intended_effect(*args, **kwargs):
                    if corruption != 'missing-copy':
                        (target / 'code').write_bytes(b'intended-before-launch')
                    if corruption in ('both-endpoints-changed', 'source-changed'):
                        (source / 'code').write_bytes(b'changed-after-launch')
                    if corruption == 'both-endpoints-changed':
                        (target / 'code').write_bytes(b'changed-after-launch')
                    if corruption != 'orphan-retained':
                        (target / 'orphan').unlink()
                    return subprocess.CompletedProcess(args[0], 0)
                # Fault injection at the syscall boundary, no executable PATH hook.
                with mock.patch('subprocess.run', side_effect=report_success_without_intended_effect):
                    with self.assertRaisesRegex(ValueError, 'verification'):
                        fixture.transfer(spec)

    def test_plan_never_inspects_selected_targets_even_for_ssh_preview(self):
        from unittest import mock
        module = self.module()
        endpoint = dict(host='fixture.invalid', user='fixture', identity_file=str(self.root / 'key'),
                        known_hosts_file=str(self.root / 'known-hosts'))
        for selected_endpoint in (None, endpoint):
            with self.subTest(endpoint=selected_endpoint):
                with mock.patch.object(Path, 'stat', side_effect=AssertionError('target metadata inspected')), \
                     mock.patch.object(Path, 'lstat', side_effect=AssertionError('target metadata inspected')):
                    result = module.build_plan(dict(self.spec, endpoint=selected_endpoint))
                self.assertEqual(result['target_observation'], 'none; lexical plan only')
                self.assertTrue(result['preflight_required'])

    def test_fixture_preflight_refuses_linked_mapping_ancestors(self):
        from unittest import mock
        module = self.module()
        with module.local_fixture() as fixture:
            real = fixture.root / 'real'
            real.mkdir()
            (real / 'code').write_text('synthetic')
            link = fixture.root / 'link'
            link.symlink_to(real, target_is_directory=True)
            spec = dict(engine='rsync', mappings=[dict(name='repo', kind='source', local=str(link),
                         remote=str(fixture.root / 'target'), container='/workspaces/repo')])
            with mock.patch('subprocess.run') as process:
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    fixture.transfer(spec)
                process.assert_not_called()

    def test_selected_protected_paths_exclude_arbitrary_files_and_recovery_trees(self):
        if not Path('/usr/bin/rsync').is_file():
            self.skipTest('trusted /usr/bin/rsync unavailable')
        module = self.module()
        with module.local_fixture() as fixture:
            source, target = fixture.root / 'source', fixture.root / 'target'
            source.mkdir()
            target.mkdir()
            (source / 'ordinary').write_bytes(b'copy me')
            (source / 'active-profile.toml').write_bytes(b'private source selection')
            (target / 'active-profile.toml').write_bytes(b'active target selection')
            (target / 'rescue-2026').mkdir()
            (target / 'rescue-2026/snapshot').write_bytes(b'preserve recovery')
            spec = dict(engine='rsync', delete=True, delete_approved=True,
                protected_paths=[dict(namespace='local', path=str(source / 'active-profile.toml')),
                                 dict(namespace='remote', path=str(target / 'rescue-2026'))],
                mappings=[dict(name='repo', kind='source', local=str(source), remote=str(target),
                               container='/workspaces/repo')])
            plan = module.build_plan(spec)
            self.assertIn('/active-profile.toml', plan['mappings'][0]['excludes'])
            self.assertIn('/rescue-2026', plan['mappings'][0]['excludes'])
            receipt = fixture.transfer(spec)
            self.assertEqual(receipt['status'], 'verified')
            self.assertEqual((target / 'ordinary').read_bytes(), b'copy me')
            self.assertEqual((target / 'active-profile.toml').read_bytes(), b'active target selection')
            self.assertEqual((target / 'rescue-2026/snapshot').read_bytes(), b'preserve recovery')
            # A selected protected root cannot itself become a mapping.
            for namespace, path in [('local', str(source)), ('remote', str(target.parent)),
                                    ('container', '/workspaces/repo')]:
                with self.subTest(namespace=namespace), self.assertRaisesRegex(ValueError, 'protected'):
                    module.build_plan(dict(spec, protected_paths=[dict(namespace=namespace, path=path)]))
            for protected in (None, ['bad'], [dict(namespace='other', path=str(source))],
                              [dict(namespace='local', path='../escape')]):
                with self.subTest(protected=protected), self.assertRaises(ValueError):
                    module.build_plan(dict(spec, protected_paths=protected))

    def test_lifecycle_receipts_distinguish_model_from_engine_supervision(self):
        from unittest import mock
        module = self.module()
        with mock.patch('subprocess.run', side_effect=AssertionError('engine invoked')):
            model = module.Lifecycle(dict(self.spec, engine='mutagen'))
            model.transition('seed-start')
            model.transition('seed-complete', verified=True)
            receipt = model.transition('resume', verified=True, deletion_approved=True, recovery_verified=True)
            self.assertEqual(receipt['state'], 'continuous')
            self.assertEqual(receipt['modeled_writer'], 'continuous-engine')
            self.assertEqual(receipt['process_status'], 'not-observed')
            self.assertFalse(receipt['supervisor_implemented'])
            self.assertTrue(receipt['model_only'])
            result = module.render_candidate(dict(self.spec, engine='mutagen'), self.root / 'candidate', reviewed=True)
            self.assertEqual(result['continuous']['native_validation'], 'not-performed')
            self.assertFalse(result['continuous']['supervisor_implemented'])

    def test_candidate_output_cannot_overwrite_selected_protection(self):
        module = self.module()
        spec = dict(self.spec, protected_paths=[dict(namespace='local', path=str(self.root / 'saved-recovery'))])
        for out in (self.root / 'saved-recovery', self.root / 'saved-recovery/new-candidate'):
            with self.subTest(out=out), self.assertRaisesRegex(ValueError, 'protected'):
                module.render_candidate(spec, out, reviewed=True)
        self.assertFalse((self.root / 'saved-recovery').exists())

    def test_seed_verification_detects_protected_file_damage_or_leakage(self):
        import subprocess
        from unittest import mock
        for damage in ('overwrite-protected', 'leak-excluded'):
            with self.subTest(damage=damage), self.module().local_fixture() as fixture:
                source, target = fixture.root / 'source', fixture.root / 'target'
                source.mkdir()
                target.mkdir()
                (source / 'code').write_bytes(b'intended')
                (source / '.env').write_bytes(b'excluded-source')
                (target / 'active.toml').write_bytes(b'protected-target')
                spec = dict(engine='rsync', protected_paths=[dict(namespace='remote', path=str(target / 'active.toml'))],
                    mappings=[dict(name='repo', kind='source', local=str(source), remote=str(target), container='/workspaces/repo')])
                def damaged_result(*args, **kwargs):
                    (target / 'code').write_bytes(b'intended')
                    if damage == 'overwrite-protected':
                        (target / 'active.toml').write_bytes(b'wrong')
                    else:
                        (target / '.env').write_bytes(b'excluded-source')
                    return subprocess.CompletedProcess(args[0], 0)
                with mock.patch('subprocess.run', side_effect=damaged_result):
                    with self.assertRaisesRegex(ValueError, 'verification'):
                        fixture.transfer(spec)

    def test_plan_preserves_source_and_artifact_ownership_and_directions(self):
        plan = self.module().build_plan(self.spec)
        self.assertEqual([m['direction'] for m in plan['mappings']], ['push', 'pull'])
        self.assertEqual([m['owner'] for m in plan['mappings']], ['local', 'remote-runtime'])
        self.assertEqual(plan['mappings'][0]['container'], '/workspaces/repo')
        self.assertFalse(plan['activation_allowed'])
        self.assertFalse(plan['delete'])
        self.assertEqual(plan['initial_seed'], 'empty-target')
        self.assertEqual(plan, self.module().build_plan(self.spec))
        self.assertFalse((self.root / 'remote-source').exists())

    def test_invalid_or_ambiguous_selection_is_rejected_without_mutation(self):
        import copy
        module = self.module()
        cases = [dict(engine='auto'), dict(engine=None), dict(delete=True),
                 dict(delete='false'), dict(delete_approved='yes'),
                 dict(initial_seed='reviewed-overwrite'), dict(conflict_policy='source-wins'),
                 dict(unknown='secret'), dict(mappings=[])]
        for update in cases:
            with self.subTest(update=update), self.assertRaises(ValueError):
                module.build_plan(dict(self.spec, **update))
        for field, value in [('local', '/'), ('local', 'relative'),
                             ('remote', '/host/../etc'), ('container', '/'),
                             ('remote', '/remote,x'), ('local', str(self.root / '.ssh')),
                             ('local', str(self.root / 'datasets')), ('kind', 'bidirectional')]:
            spec = copy.deepcopy(self.spec)
            spec['mappings'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                module.build_plan(spec)
        for field in ('local', 'remote', 'container'):
            spec = copy.deepcopy(self.spec)
            spec['mappings'][1][field] = spec['mappings'][0][field] + '/nested'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'overlap'):
                module.build_plan(spec)
        link = self.root / 'linked'
        link.symlink_to(self.source)
        spec = copy.deepcopy(self.spec)
        spec['mappings'][0]['local'] = str(link)
        # A lexical plan deliberately does not classify existing symlinks.
        self.assertTrue(module.build_plan(spec)['preflight_required'])


    def test_rsync_preview_reuses_existing_ssh_iap_and_transfer_policy(self):
        import shlex
        from unittest import mock
        from src.python import file_transfer
        module = self.module()
        key = self.root / 'identity'
        key.write_text('SYNTHETIC-KEY-MUST-NOT-LEAK')
        endpoint = dict(host='private-vm', user='fixture', identity_file=str(key),
                        known_hosts_file=str(self.root / 'trust'), iap=True,
                        instance='private-vm', project='fixture-project', zone='us-central1-a')
        spec = dict(self.spec, endpoint=endpoint, delete=True, delete_approved=True)
        plan = module.build_plan(spec)
        self.assertFalse((self.root / 'trust').exists())
        for mapping in plan['mappings']:
            argv = mapping['rsync_argv']
            self.assertIn('--dry-run', argv)
            self.assertIn('--delete-after', argv)
            self.assertIn('start-iap-tunnel', shlex.join(argv))
            self.assertNotIn('SYNTHETIC-KEY', shlex.join(argv))
            with mock.patch.object(file_transfer.subprocess, 'run') as network_boundary:
                file_transfer.transfer_directory(file_transfer.TransferEndpoint(**endpoint),
                    mapping['direction'], mapping['local'], mapping['remote'], dry_run=True,
                    delete=True, exclude=tuple(p for p in mapping['excludes']
                                              if p not in file_transfer.DEFAULT_EXCLUDES))
            self.assertEqual(argv, network_boundary.call_args.args[0])
        self.assertIn('datasets/', plan['mappings'][0]['excludes'])
        self.assertNotIn('datasets/', plan['mappings'][1]['excludes'])
        for mapping in plan['mappings']:
            for pattern in ('.git/', '.env', 'state/', '.venv/', '*.db', 'backups/'):
                self.assertIn(pattern, mapping['excludes'])


    def test_candidate_render_writes_only_new_reviewed_output_without_hooks(self):
        import json
        module = self.module()
        self.assertTrue(hasattr(module, 'render_candidate'), 'reviewed candidate renderer is missing')
        out = self.root / 'candidate'
        with self.assertRaisesRegex(ValueError, 'review'):
            module.render_candidate(self.spec, out)
        self.assertFalse(out.exists())
        result = module.render_candidate(self.spec, out, reviewed=True)
        candidate = json.loads((out / 'devcontainer.json').read_text())
        self.assertEqual(candidate, result['devcontainer'])
        self.assertEqual(candidate['image'], self.spec['image'])
        self.assertEqual(candidate['workspaceFolder'], '/workspaces/repo')
        self.assertIn('readonly', candidate['workspaceMount'])
        self.assertTrue(any('target=/outputs/results' in mount and 'readonly' not in mount
                            for mount in candidate['mounts']))
        self.assertFalse(any('Command' in key for key in candidate))
        self.assertNotIn('customizations', candidate)
        self.assertNotIn('runArgs', candidate)
        self.assertFalse(result['runtime_parity_verified'])
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        with self.assertRaises((ValueError, FileExistsError)):
            module.render_candidate(self.spec, out, reviewed=True)
        self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})
        for path in (self.source / 'candidate', self.root / '.devcontainer',
                     self.root / '.vscode' / 'candidate'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.render_candidate(self.spec, path, reviewed=True)
        linked = self.root / 'linked-output'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            module.render_candidate(self.spec, linked / 'new', reviewed=True)
        self.assertFalse((self.root / 'new').exists())


    def test_explicit_continuous_candidates_keep_deletion_and_activation_gated(self):
        import json
        import xml.etree.ElementTree as ET
        module = self.module()
        for engine in ('mutagen', 'syncthing'):
            spec = dict(self.spec, engine=engine)
            result = module.render_candidate(spec, self.root / engine, reviewed=True)
            self.assertIn('continuous', result)
            continuous = result['continuous']
            self.assertEqual(continuous['engine'], engine)
            self.assertFalse(continuous['activation_allowed'])
            self.assertTrue(continuous['deletion_propagates'])
            self.assertFalse(continuous['deletion_approved'])
            self.assertIn('pairing/transport', continuous['live_gates'])
            if engine == 'mutagen':
                config = json.loads((self.root / engine / 'mutagen.candidate.yml').read_text())
                for session in config['sync'].values():
                    self.assertEqual(session['mode'], 'one-way-safe')
                    self.assertEqual(session['symlink']['mode'], 'ignore')
                    self.assertIn('.env', session['ignore']['paths'])
                self.assertEqual(config['sync']['repo']['alpha'], str(self.source))
                self.assertEqual(config['sync']['results']['alpha'], self.spec['mappings'][1]['remote'])
                self.assertNotIn('afterCreate', config)
            else:
                local = ET.parse(self.root / engine / 'syncthing.local.candidate.xml').getroot()
                remote = ET.parse(self.root / engine / 'syncthing.remote.candidate.xml').getroot()
                self.assertEqual([f.get('type') for f in local.findall('folder')], ['sendonly', 'receiveonly'])
                self.assertEqual([f.get('type') for f in remote.findall('folder')], ['receiveonly', 'sendonly'])
                for root in (local, remote):
                    for folder in root.findall('folder'):
                        self.assertEqual(folder.get('paused'), 'true')
                        self.assertEqual(folder.find('versioning').get('type'), 'staggered')
                self.assertIn('.env', (self.root / engine / 'repo.stignore.candidate').read_text())


    def test_disposable_local_rsync_transfers_selected_source_and_artifacts(self):
        if not Path('/usr/bin/rsync').is_file():
            self.skipTest('rsync unavailable; no installation attempted')
        module = self.module()
        self.assertTrue(hasattr(module, 'local_fixture'), 'disposable local transfer adapter is missing')
        with module.local_fixture() as fixture:
            source = fixture.root / 'source'
            source.mkdir()
            (source / 'code.py').write_text('canonical source')
            for name in ('.env', '.git/config', '.venv/bin/python', 'state/key',
                         'databases/live.db', 'datasets/large', '.config/gcloud/token'):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('SECRET-NEVER-TRANSFER')
            artifacts = fixture.root / 'runtime-output'
            artifacts.mkdir()
            (artifacts / 'checkpoint.pt').write_bytes(b'fixture-checkpoint')
            spec = dict(engine='rsync', mappings=[
                dict(name='code', kind='source', local=str(source),
                     remote=str(fixture.root / 'remote'), container='/workspaces/code'),
                dict(name='models', kind='artifacts', local=str(fixture.root / 'retrieved'),
                     remote=str(artifacts), container='/outputs/models')])
            result = fixture.transfer(spec)
            self.assertEqual(result['returncodes'], [0, 0])
            self.assertEqual((fixture.root / 'remote/code.py').read_text(), 'canonical source')
            self.assertEqual((fixture.root / 'retrieved/checkpoint.pt').read_bytes(), b'fixture-checkpoint')
            for file in (fixture.root / 'remote').rglob('*'):
                if file.is_file():
                    self.assertNotIn(b'SECRET', file.read_bytes())
            self.assertEqual(fixture.transfer(spec)['returncodes'], [0, 0])
            (fixture.root / 'remote/code.py').write_text('unexpected remote edit')
            with self.assertRaisesRegex(ValueError, 'conflict'):
                fixture.transfer(spec)
            self.assertEqual((fixture.root / 'remote/code.py').read_text(), 'unexpected remote edit')
            (source / 'escape').symlink_to(self.root)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                fixture.transfer(spec)
            (source / 'escape').unlink()
            spec['mappings'][0]['local'] = str(self.source)
            with self.assertRaisesRegex(ValueError, 'fixture'):
                fixture.transfer(spec)
        self.assertFalse(fixture.root.exists())


    def test_lifecycle_requires_verified_seed_and_cooperative_exclusive_writer(self):
        module = self.module()
        self.assertTrue(hasattr(module, 'Lifecycle'), 'offline lifecycle orchestrator is missing')
        lifecycle = module.Lifecycle(dict(self.spec, engine='mutagen'))
        with self.assertRaisesRegex(ValueError, 'seed'):
            lifecycle.transition('resume')
        self.assertEqual(lifecycle.transition('seed-start')['state'], 'seeding')
        with self.assertRaisesRegex(ValueError, 'verified'):
            lifecycle.transition('seed-complete')
        self.assertEqual(lifecycle.transition('seed-complete', verified=True)['state'], 'paused')
        with self.assertRaisesRegex(ValueError, 'deletion'):
            lifecycle.transition('resume', verified=True)
        with self.assertRaisesRegex(ValueError, 'recovery'):
            lifecycle.transition('resume', verified=True, deletion_approved=True)
        result = lifecycle.transition('resume', verified=True, deletion_approved=True, recovery_verified=True)
        self.assertEqual(result['state'], 'continuous')
        self.assertFalse(result['executed'])
        with self.assertRaisesRegex(ValueError, 'writer'):
            lifecycle.transition('seed-start')
        self.assertEqual(lifecycle.transition('conflict')['state'], 'blocked')
        with self.assertRaises(ValueError):
            lifecycle.transition('resume', verified=True, deletion_approved=True, recovery_verified=True)
        self.assertEqual(lifecycle.transition('stop')['state'], 'stopped')
        with self.assertRaises(ValueError):
            lifecycle.transition('resume', verified=True, deletion_approved=True, recovery_verified=True)
        with module.local_fixture() as fixture:
            self.assertTrue(hasattr(fixture, 'writer'), 'exclusive fixture writer lock missing')
            with fixture.writer('mutagen'):
                with self.assertRaisesRegex(ValueError, 'writer'):
                    with fixture.writer('rsync'):
                        self.fail('two engines obtained the same writer lock')
            with fixture.writer('rsync'):
                pass


    def test_disposable_overwrite_delete_and_gitfile_exclusions_are_separate(self):
        if not Path('/usr/bin/rsync').is_file():
            self.skipTest('rsync unavailable; no installation attempted')
        module = self.module()
        with module.local_fixture() as fixture:
            source, target = fixture.root / 'source', fixture.root / 'target'
            source.mkdir()
            target.mkdir()
            (source / 'code.py').write_text('new source content')
            (target / 'code.py').write_text('old target')
            (target / 'keep').write_text('orphan')
            (source / '.git').write_text('gitdir: PRIVATE-METADATA')
            (source / '.netrc').write_text('PRIVATE-CREDENTIAL')
            (target / '.env').write_text('private retained')
            spec = dict(engine='rsync', mappings=[dict(name='source', kind='source', local=str(source),
                       remote=str(target), container='/workspaces/source')])
            with self.assertRaisesRegex(ValueError, 'conflict'):
                fixture.transfer(spec)
            spec.update(initial_seed='reviewed-overwrite', overwrite_approved=True)
            self.assertEqual(fixture.transfer(spec)['returncodes'], [0])
            self.assertEqual((target / 'code.py').read_text(), 'new source content')
            self.assertTrue((target / 'keep').exists())
            self.assertFalse((target / '.git').exists())
            self.assertFalse((target / '.netrc').exists())
            spec['delete'] = True
            with self.assertRaisesRegex(ValueError, 'Deletion'):
                fixture.transfer(spec)
            self.assertTrue((target / 'keep').exists())
            spec['delete_approved'] = True
            fixture.transfer(spec)
            self.assertFalse((target / 'keep').exists())
            self.assertEqual((target / '.env').read_text(), 'private retained')


    def test_selected_nested_secret_roots_and_nonempty_seed_are_rejected(self):
        import copy
        module = self.module()
        for suffix in ('.config/gcloud', '.agents/memory'):
            spec = copy.deepcopy(self.spec)
            spec['mappings'][0]['local'] = str(self.root / suffix)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'excluded'):
                module.build_plan(spec)
        with module.local_fixture() as fixture:
            source, target = fixture.root / 'source', fixture.root / 'target'
            source.mkdir()
            target.mkdir()
            (source / 'new').write_text('new')
            (target / 'unadopted').write_text('keep')
            spec = dict(engine='rsync', mappings=[dict(name='repo', kind='source', local=str(source),
                        remote=str(target), container='/workspaces/repo')])
            with self.assertRaisesRegex(ValueError, 'seed'):
                fixture.transfer(spec)
            self.assertFalse((target / 'new').exists())
            spec.update(initial_seed='reviewed-overwrite', overwrite_approved=True)
            (source / 'unadopted').mkdir()
            with self.assertRaisesRegex(ValueError, 'type conflict'):
                fixture.transfer(spec)
            self.assertEqual((target / 'unadopted').read_text(), 'keep')


    def test_glob_paths_and_continuous_recovery_stores_are_not_sync_inputs(self):
        import copy
        module = self.module()
        for suffix in ('selected/*', 'selected/[ab]', '.stversions', '.stfolder'):
            spec = copy.deepcopy(self.spec)
            spec['mappings'][0]['remote'] = str(self.root / suffix)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                module.build_plan(spec)
        plan = module.build_plan(self.spec)
        for mapping in plan['mappings']:
            self.assertIn('.stversions/', mapping['excludes'])
            self.assertIn('.stfolder/', mapping['excludes'])


if __name__ == '__main__':
    unittest.main()
