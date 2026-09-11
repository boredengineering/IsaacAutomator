"""Private applied recipe tests: synthetic state, no credentials/cloud or commits."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('src.python.deployment_baseline'),
                             'durable baseline module is missing')
        from src.python import deployment_baseline
        return deployment_baseline

    def test_legacy_without_receipt_is_explicitly_unknown(self):
        api = self.api()
        store = api.BaselineStore(self.root / 'private')
        self.assertIsNone(store.load(None))
        self.assertEqual(store.lifecycle_status(None), 'unknown')
        self.assertEqual((self.root / 'private').stat().st_mode & 0o777, 0o700)

    def fixture(self):
        api = self.api()
        source = self.root / 'source'
        source.mkdir()
        (source / 'main.tf').write_bytes(b'output "recipe" { value = "original" }\n')
        (source / 'secret.auto.tfvars').write_text('NEVER_COPY')
        inputs = self.root / 'approved.tfvars.json'
        inputs.write_bytes(b'{"password":"PRIVATE_INPUT"}')
        lock = self.root / 'approved.lock'
        lock.write_bytes(b'# approved provider lock\n')
        expected = {'main.tf': (source / 'main.tf').read_bytes()}
        revision = hashlib.sha256(b'synthetic trusted build record').hexdigest()
        # Trust callback models an independently approved build record, not HEAD.
        verifier = lambda rev, files: rev == revision and dict(files) == expected
        store = api.BaselineStore(self.root / 'private')
        prepared = api.prepare(source_root=source, source_files=('main.tf',),
                               variables_file=inputs, provider_lockfile=lock,
                               source_revision=revision, verify_source=verifier)
        return api, store, prepared, source, inputs

    def evidence(self):
        outputs = {'recipe': {'sensitive': False, 'type': 'string', 'value': 'original'}}
        state = {'version': 4, 'serial': 1, 'lineage': '00000000-0000-0000-0000-000000000001',
                 'resources': [], 'outputs': outputs}
        return state, outputs

    def publish(self, store, prepared, **changes):
        state, outputs = self.evidence()
        options = dict(apply_exit_code=0, state=state, outputs=outputs,
                       verify_applied=lambda recipe, observed, actual: actual == outputs,
                       applied_at=100)
        options.update(changes)
        return store.publish(prepared, **options)

    def test_published_recipe_reconstructs_original_private_bytes_not_dirty_tree(self):
        from src.python.drift_config import DriftConfig
        from src.python.drift_report import Baseline
        api, store, prepared, source, inputs = self.fixture()
        self.assertFalse(any(store.root.iterdir()), 'prepare must not publish')
        (source / 'main.tf').write_text('DIRTY_HEAD')
        inputs.write_text('changed after approval')
        receipt = self.publish(store, prepared)
        self.assertEqual(DriftConfig.from_dict({'baseline_ref': receipt.baseline_ref}).baseline_ref,
                         receipt.baseline_ref)
        self.assertIsInstance(receipt.baseline, Baseline)
        restarted = api.BaselineStore(store.root)
        self.assertEqual(restarted.load(receipt.baseline_ref), receipt)
        recovered = restarted.reconstruct(receipt.baseline_ref, self.root / 'recovered')
        self.assertEqual(recovered.source_files, ('main.tf', '.terraform.lock.hcl'))
        self.assertEqual((recovered.source_root / 'main.tf').read_bytes(),
                         b'output "recipe" { value = "original" }\n')
        self.assertEqual(recovered.variables_file.read_bytes(), b'{"password":"PRIVATE_INPUT"}')
        self.assertFalse((recovered.source_root / 'secret.auto.tfvars').exists())
        self.assertEqual(recovered.baseline, receipt.baseline)
        self.assertNotIn('PRIVATE_INPUT', repr(receipt))
        self.assertNotIn('PRIVATE_INPUT', repr(prepared))
        for directory, _, filenames in os.walk(store.root):
            self.assertEqual(Path(directory).stat().st_mode & 0o777, 0o700)
            for name in filenames:
                self.assertEqual((Path(directory) / name).stat().st_mode & 0o777, 0o600)

    def test_every_published_byte_is_verified_before_reconstruction(self):
        api, store, prepared, _, _ = self.fixture()
        receipt = self.publish(store, prepared)
        for path in tuple(store.root.iterdir()):
            original = path.read_bytes()
            path.write_bytes(original + b'CORRUPTED')
            with self.subTest(object=path.name):
                with self.assertRaises(api.BaselineError):
                    store.reconstruct(receipt.baseline_ref, self.root / 'recovered')
                self.assertFalse((self.root / 'recovered').exists())
            path.write_bytes(original)
        self.assertEqual(store.load(receipt.baseline_ref), receipt)

    def test_prepare_requires_explicit_reviewed_source_and_immutable_revision(self):
        api, _, _, source, inputs = self.fixture()
        options = dict(source_root=source, source_files=('main.tf',), variables_file=inputs,
                       provider_lockfile=None, source_revision='a' * 40,
                       verify_source=lambda rev, files: True)
        for change in ({'source_revision': 'HEAD'}, {'source_revision': None},
                       {'source_files': ()}, {'source_files': ('main.tf', 'main.tf')},
                       {'source_files': ('secret.auto.tfvars',)}, {'source_files': ('*.tf',)},
                       {'source_files': ('../source/main.tf',)}, {'source_files': ('/main.tf',)},
                       {'source_files': ('override.tf',)}, {'provider_lockfile': ''},
                       {'verify_source': None},
                       {'verify_source': lambda rev, files: False},
                       {'verify_source': lambda rev, files: 'true'}):
            with self.subTest(change=repr(change)):
                with self.assertRaises(api.BaselineError):
                    api.prepare(**{**options, **change})

    def test_filesystem_boundaries_reject_links_unsafe_modes_and_nonregular_files(self):
        api, store, prepared, source, inputs = self.fixture()
        receipt = self.publish(store, prepared)
        options = dict(source_root=source, source_files=('main.tf',), variables_file=inputs,
                       provider_lockfile=None, source_revision='a' * 40,
                       verify_source=lambda rev, files: True)
        for path in (source / 'main.tf', inputs):
            original = path.read_bytes()
            real = self.root / 'outside-file'
            real.write_bytes(original)
            for kind in ('symlink', 'hardlink', 'fifo'):
                path.unlink()
                if kind == 'symlink':
                    path.symlink_to(real)
                elif kind == 'hardlink':
                    os.link(real, path)
                else:
                    os.mkfifo(path)
                with self.subTest(path=path.name, kind=kind):
                    with self.assertRaises(api.BaselineError):
                        api.prepare(**options)
                path.unlink()
                path.write_bytes(original)
            real.unlink()
        linked = self.root / 'linked'
        linked.symlink_to(store.root, target_is_directory=True)
        with self.assertRaises(api.BaselineError):
            api.BaselineStore(linked)
        with self.assertRaises(api.BaselineError):
            api.BaselineStore(linked / 'child')
        store.root.chmod(0o755)
        with self.assertRaises(api.BaselineError):
            api.BaselineStore(store.root)
        store.root.chmod(0o700)
        victim = store.root / receipt.baseline.inputs_ref
        victim.chmod(0o644)
        with self.assertRaises(api.BaselineError):
            store.load(receipt.baseline_ref)
        victim.chmod(0o600)
        outside = self.root / 'outside'
        outside.write_bytes(victim.read_bytes())
        victim.unlink()
        os.link(outside, victim)
        with self.assertRaises(api.BaselineError):
            store.load(receipt.baseline_ref)
        victim.unlink()
        victim.symlink_to(outside)
        with self.assertRaises(api.BaselineError):
            store.load(receipt.baseline_ref)

    def test_publish_never_follows_replaced_store_or_existing_object_links(self):
        api, store, prepared, _, _ = self.fixture()
        outside = self.root / 'outside-store'
        outside.mkdir(mode=0o700)
        store.root.rmdir()
        store.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(api.BaselineError):
            self.publish(store, prepared)
        self.assertEqual(list(outside.iterdir()), [])
        store.root.unlink()
        store.root.mkdir(mode=0o700)
        receipt = self.publish(store, prepared)
        path = store.root / receipt.baseline.inputs_ref
        raw = path.read_bytes()
        victim = self.root / 'victim'
        victim.write_bytes(raw)
        victim.chmod(0o600)
        path.unlink()
        path.symlink_to(victim)
        with self.assertRaises(api.BaselineError):
            self.publish(store, prepared)
        self.assertEqual(victim.read_bytes(), raw)

    def test_git_verifier_compares_only_selected_blobs_to_explicit_commit(self):
        import subprocess
        from src.python.terraform_sources import workstation_source_files
        api = self.api()
        self.assertTrue(hasattr(api, 'GitRevisionVerifier'), 'concrete git revision verifier required')
        repo = Path(__file__).resolve().parents[2]
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
        names = workstation_source_files('aws')
        selected = {name: subprocess.check_output(['git', 'show', f'{revision}:src/terraform/aws/{name}'],
                                                 cwd=repo) for name in names}
        verifier = api.GitRevisionVerifier(repo, 'src/terraform/aws')
        self.assertTrue(verifier(revision, selected))
        inputs = self.root / 'inputs.tfvars'
        inputs.write_bytes(b'')
        checkout = self.root / 'selected-git-blobs'
        for name, raw in selected.items():
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        prepared = api.prepare(source_root=checkout, source_files=names,
                               variables_file=inputs, provider_lockfile=None,
                               source_revision=revision, verify_source=verifier)
        self.assertEqual(prepared.source_revision, revision)
        selected['main.tf'] += b'\n# dirty HEAD must not become applied truth\n'
        self.assertFalse(verifier(revision, selected))
        with self.assertRaises(api.BaselineError):
            verifier('HEAD', selected)
        with self.assertRaises(api.BaselineError):
            verifier(revision, {'../credentials': b'NEVER_READ'})

    def test_publication_requires_typed_success_and_sanitized_state_output_verification(self):
        api, store, prepared, _, _ = self.fixture()
        def private_error(*args):
            raise RuntimeError('PRIVATE_INPUT')
        for changes in ({'apply_exit_code': False}, {'apply_exit_code': 1},
                        {'apply_exit_code': '0'}, {'verify_applied': None},
                        {'verify_applied': private_error}, {'state': {}},
                        {'outputs': {}}, {'applied_at': True},
                        {'verify_applied': lambda *args: False}):
            with self.subTest(changes=repr(changes)):
                with self.assertRaises(api.BaselineError) as error:
                    self.publish(store, prepared, **changes)
                self.assertNotIn('PRIVATE_INPUT', str(error.exception))
                self.assertEqual(list(store.root.iterdir()), [])

    def test_prepared_recipe_stages_exact_bytes_before_apply_without_publication(self):
        api, store, prepared, source, inputs = self.fixture()
        self.assertTrue(hasattr(prepared, 'stage'), 'prepared recipe must feed the actual apply')
        (source / 'main.tf').write_text('DIRTY')
        inputs.write_text('DIRTY_INPUT')
        staged = prepared.stage(self.root / 'apply-recipe')
        self.assertEqual((staged.source_root / 'main.tf').read_bytes(), prepared._sources[0][1])
        self.assertEqual(staged.variables_file.read_bytes(), b'{"password":"PRIVATE_INPUT"}')
        self.assertEqual(list(store.root.iterdir()), [])
        with self.assertRaises(api.BaselineError):
            prepared.stage(self.root / 'apply-recipe')
        link = self.root / 'linked-parent'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(api.BaselineError):
            prepared.stage(link / 'should-not-exist')
        self.assertFalse((self.root / 'should-not-exist').exists())
        for directory, _, filenames in os.walk(self.root / 'apply-recipe'):
            self.assertEqual(Path(directory).stat().st_mode & 0o777, 0o700)
            for name in filenames:
                self.assertEqual((Path(directory) / name).stat().st_mode & 0o777, 0o600)

    def test_reconstruction_uses_verified_bytes_and_rejects_destination_links(self):
        from unittest import mock
        api, store, prepared, _, _ = self.fixture()
        receipt = self.publish(store, prepared)
        linked = self.root / 'linked-parent'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(api.BaselineError):
            store.reconstruct(receipt.baseline_ref, linked / 'escape')
        self.assertFalse((self.root / 'escape').exists())
        original_materialize = api._materialize
        def after_verification(recipe, destination):
            blob = store.root / ('object-' + hashlib.sha256(prepared._sources[0][1]).hexdigest())
            blob.write_bytes(b'corrupt after verified read')
            return original_materialize(recipe, destination)
        with mock.patch.object(api, '_materialize', side_effect=after_verification) as materialize:
            recovered = store.reconstruct(receipt.baseline_ref, self.root / 'recovered')
            materialize.assert_called_once()
        self.assertEqual((recovered.source_root / 'main.tf').read_bytes(), prepared._sources[0][1])

    def test_receipt_schema_and_opaque_reference_are_validated_before_path_access(self):
        api, store, prepared, _, _ = self.fixture()
        receipt = self.publish(store, prepared)
        for ref in ('../approved.tfvars.json', str(self.root / 'approved.tfvars.json'),
                    'baseline-' + 'a' * 64, 'https://example.test/file', ''):
            with self.subTest(ref=ref):
                with self.assertRaises(api.BaselineError):
                    store.load(ref)
        original = json.loads((store.root / receipt.baseline_ref).read_bytes())
        for change in ({'inputs_name': '../escape'}, {'schema_version': True},
                       {'lock_present': 'yes'}, {'sources': {}}, {'state': {}},
                       {'unexpected': 'PRIVATE_INPUT'}):
            record = {**original, **change}
            raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
            ref = 'baseline-' + hashlib.sha256(raw).hexdigest()
            path = store.root / ref
            path.write_bytes(raw)
            path.chmod(0o600)
            with self.subTest(change=change):
                with self.assertRaises(api.BaselineError):
                    store.reconstruct(ref, self.root / 'recovered')
                self.assertFalse((self.root / 'recovered').exists())

    def test_unverified_recipe_cannot_be_constructed_or_relabelled_as_a_revision(self):
        from dataclasses import replace
        api, _, prepared, _, _ = self.fixture()
        with self.assertRaises(api.BaselineError):
            api.PreparedBaseline('b' * 40, prepared._sources, prepared._inputs,
                                 prepared._lock, prepared.inputs_name, prepared.lock_present)
        with self.assertRaises(api.BaselineError):
            replace(prepared, source_revision='b' * 40)

    def test_source_verifier_failures_do_not_leak_private_diagnostics(self):
        api, _, _, source, inputs = self.fixture()
        def failure(*args):
            raise RuntimeError('PRIVATE_INPUT')
        with self.assertRaises(api.BaselineError) as error:
            api.prepare(source_root=source, source_files=('main.tf',), variables_file=inputs,
                        provider_lockfile=None, source_revision='a' * 40, verify_source=failure)
        self.assertNotIn('PRIVATE_INPUT', str(error.exception))

    def test_interrupted_publication_preserves_previous_receipt_and_retries_idempotently(self):
        from unittest import mock
        api, store, prepared, _, _ = self.fixture()
        previous = self.publish(store, prepared)
        replace = os.replace
        def interrupted(src, dst, **kwargs):
            if str(dst).startswith('baseline-'):
                raise OSError('synthetic interrupted atomic publication')
            return replace(src, dst, **kwargs)
        with mock.patch.object(api.os, 'replace', side_effect=interrupted):
            with self.assertRaises(api.BaselineError):
                self.publish(store, prepared, applied_at=200)
        self.assertEqual(store.load(previous.baseline_ref), previous)
        self.assertEqual([p.name for p in store.root.iterdir() if p.name.startswith('baseline-')],
                         [previous.baseline_ref])
        self.assertFalse(any(p.name.startswith('pending-') for p in store.root.iterdir()))
        recovered = self.publish(store, prepared, applied_at=200)
        self.assertEqual(self.publish(store, prepared, applied_at=200), recovered)
        self.assertEqual(store.load(recovered.baseline_ref), recovered)

    def test_real_provider_free_terraform_applies_reconstructs_pinned_recipe_and_destroys(self):
        import shutil
        from src.python.terraform_backend import BackendSpec
        from src.python.terraform_runner import TerraformRunner
        if shutil.which('terraform') is None:
            self.skipTest('Terraform binary unavailable: integration not exercised')
        api = self.api()
        source = self.root / 'approved-build'
        (source / 'modules/recipe').mkdir(parents=True)
        approved = {
            'main.tf': b'''terraform {
  required_version = ">= 1.3.5"
  backend "local" {}
}
variable "label" { type = string }
module "recipe" { source = "./modules/recipe" }
output "answer" { value = "${module.recipe.value}-${var.label}" }
''',
            'modules/recipe/main.tf': b'output "value" { value = "original" }\n',
        }
        for name, raw in approved.items():
            (source / name).write_bytes(raw)
        inputs = self.root / 'approved.tfvars.json'
        inputs.write_bytes(b'{"label":"private-fixture"}')
        # This disposable build record explicitly binds the canonical source map
        # to its SHA-256 revision. It is NOT an invented Git commit or HEAD hash.
        build_record = json.dumps({name: hashlib.sha256(raw).hexdigest() for name, raw in approved.items()},
                                  sort_keys=True, separators=(',', ':')).encode()
        revision = hashlib.sha256(build_record).hexdigest()
        def approved_build(rev, selected):
            return rev == revision and dict(selected) == approved
        prepared = api.prepare(source_root=source, source_files=tuple(approved), variables_file=inputs,
                               provider_lockfile=None, source_revision=revision, verify_source=approved_build)
        store = api.BaselineStore(self.root / 'private')
        paths = prepared.stage(self.root / 'apply-recipe')
        options = dict(backend_spec=BackendSpec.from_dict({}, cloud='aws'), target_scope='123456789012',
                       deployment_name='offline-baseline', state_root=self.root / 'state',
                       lock_root=self.root / 'locks', command_timeout=30,
                       environment={'PATH': os.environ['PATH'], 'CHECKPOINT_DISABLE': '1'})
        def runner(recipe):
            return TerraformRunner(source_root=recipe.source_root, source_files=recipe.source_files,
                                   variables_file=recipe.variables_file, **options)
        with runner(paths) as run:
            run.init()
            plan = run.plan()
            self.assertTrue(plan.has_changes)
            run.apply(plan, acknowledge_mutation=True)
            state, outputs = run.pull_state(), run.output()
            self.assertEqual(outputs['answer']['value'], 'original-private-fixture')
            def verify_applied(recipe, observed, actual):
                return (recipe is prepared and observed['lineage'] == state['lineage']
                        and observed['serial'] == state['serial'] and observed['resources'] == []
                        and actual['answer']['value'] == 'original-private-fixture')
            receipt = store.publish(prepared, apply_exit_code=0, state=state, outputs=outputs,
                                    verify_applied=verify_applied, applied_at=100)
        (source / 'modules/recipe/main.tf').write_bytes(b'output "value" { value = "DIRTY" }\n')
        with self.assertRaises(api.BaselineError):
            api.prepare(source_root=source, source_files=tuple(approved), variables_file=inputs,
                        provider_lockfile=None, source_revision=revision, verify_source=approved_build)
        restored = api.BaselineStore(store.root).reconstruct(receipt.baseline_ref, self.root / 'restore')
        self.assertEqual(restored.baseline.source_revision, revision)
        self.assertFalse((restored.source_root / '.terraform.lock.hcl').exists())
        self.assertEqual(restored.variables_file.read_bytes(), b'{"label":"private-fixture"}')
        with runner(restored) as run:
            run.init()
            self.assertFalse(run.plan().has_changes, 'reconstruction must retain the actually applied recipe')
            self.assertEqual(run.output()['answer']['value'], 'original-private-fixture')
            destroy = run.plan(destroy=True)
            self.assertTrue(destroy.has_changes)
            run.apply(destroy, acknowledge_mutation=True)
            destroyed = run.pull_state()
            self.assertEqual(destroyed['lineage'], state['lineage'])
            self.assertGreater(destroyed['serial'], state['serial'])
            self.assertEqual(destroyed['outputs'], {})
            self.assertEqual(destroyed['resources'], [])
        # Last-applied evidence is historical; lifecycle owner retires its active
        # pointer after verified destroy, rather than rewriting this immutable CAS.
        self.assertEqual(store.load(receipt.baseline_ref), receipt)

    def test_malformed_output_envelopes_cannot_satisfy_apply_verification(self):
        api, store, prepared, _, _ = self.fixture()
        for output in ({'value': 'original'}, {'sensitive': 'false', 'type': 'string', 'value': 'original'},
                       {'sensitive': False, 'type': 'string', 'value': 'original', 'unexpected': True}):
            state, _ = self.evidence()
            state['outputs'] = {'recipe': output}
            # Match the normal missing-sensitive default to test schema, not mismatch.
            observed = {'recipe': {'sensitive': False, **output}}
            with self.subTest(output=output):
                with self.assertRaises(api.BaselineError):
                    self.publish(store, prepared, state=state, outputs=observed,
                                 verify_applied=lambda *args: True)
                self.assertEqual(list(store.root.iterdir()), [])

    def test_snapshot_size_limits_match_runner_inputs_and_bound_total_sources(self):
        from unittest import mock
        api, _, _, source, inputs = self.fixture()
        options = dict(source_root=source, source_files=('main.tf',), variables_file=inputs,
                       provider_lockfile=None, source_revision='a' * 40,
                       verify_source=lambda *args: True)
        with mock.patch.object(api, '_MAX_TOTAL', 1, create=True):
            with self.assertRaises(api.BaselineError):
                api.prepare(**options)
        inputs.write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaises(api.BaselineError):
            api.prepare(**options)

    def test_missing_state_outputs_cannot_be_treated_as_verified_empty_outputs(self):
        api, store, prepared, _, _ = self.fixture()
        state, _ = self.evidence()
        del state['outputs']
        with self.assertRaises(api.BaselineError):
            self.publish(store, prepared, state=state, outputs={}, verify_applied=lambda *args: True)
        self.assertEqual(list(store.root.iterdir()), [])

    def test_directory_swap_during_source_read_cannot_redirect_snapshot(self):
        from unittest import mock
        api, _, prepared, source, inputs = self.fixture()
        outside = self.root / 'untrusted'
        outside.mkdir()
        (outside / 'main.tf').write_bytes(b'SECRET_DO_NOT_COPY')
        original_open = os.open
        swapped = False
        def swap(name, flags, *args, **kwargs):
            nonlocal swapped
            if name == 'main.tf' and not swapped:
                swapped = True
                source.rename(self.root / 'pinned-original')
                source.symlink_to(outside, target_is_directory=True)
            return original_open(name, flags, *args, **kwargs)
        with mock.patch.object(api.os, 'open', side_effect=swap):
            result = api.prepare(source_root=source, source_files=('main.tf',), variables_file=inputs,
                                 provider_lockfile=None, source_revision=prepared.source_revision,
                                 verify_source=lambda rev, files: dict(files) == dict(prepared._sources))
        self.assertTrue(swapped)
        self.assertEqual(result._sources, prepared._sources)

    def test_receipt_input_limit_matches_prepare_on_load_and_reconstruct(self):
        api, store, prepared, _, _ = self.fixture()
        receipt = self.publish(store, prepared)
        record = json.loads((store.root / receipt.baseline_ref).read_bytes())
        for size in (1024 * 1024 + 1, 1024 * 1024):
            inputs = b'x' * size
            sha = api._sha(inputs)
            store._write('object-' + sha, inputs)
            record['baseline'].update(input_digest=sha, inputs_ref='object-' + sha)
            raw = api._json(record)
            ref = 'baseline-' + api._sha(raw)
            store._write(ref, raw)
            for operation in ('load', 'reconstruct'):
                destination = self.root / (operation + str(size))
                def read():
                    return store.load(ref) if operation == 'load' else store.reconstruct(ref, destination)
                with self.subTest(size=size, operation=operation):
                    if size > 1024 * 1024:
                        with self.assertRaises(api.BaselineError):
                            read()
                        self.assertFalse(destination.exists())
                    else:
                        self.assertIsNotNone(read())

    def test_receipt_load_and_reconstruct_bound_repeated_source_bytes(self):
        from unittest import mock
        api, store, prepared, _, _ = self.fixture()
        receipt = self.publish(store, prepared)
        record = json.loads((store.root / receipt.baseline_ref).read_bytes())
        sha = record['sources']['main.tf']
        record['sources'] = {f'copy{index}.tf': sha for index in range(4)}
        source_map = api._json(record['sources'])
        record['baseline'].update(source_digest=api.digest(record['sources']),
                                  source_ref='object-' + api._sha(source_map))
        store._write('object-' + api._sha(source_map), source_map)
        raw = api._json(record)
        ref = 'baseline-' + api._sha(raw)
        store._write(ref, raw)
        for operation in ('load', 'reconstruct'):
            with self.subTest(operation=operation), mock.patch.object(api, '_MAX_TOTAL', len(prepared._sources[0][1]) * 2):
                with self.assertRaises(api.BaselineError):
                    if operation == 'load':
                        store.load(ref)
                    else:
                        store.reconstruct(ref, self.root / 'oversized')
                self.assertFalse((self.root / 'oversized').exists())
        # Exact aggregate boundary remains reconstructible (count references,
        # not unique CAS objects); this is defensive validation, not signatures.
        with mock.patch.object(api, '_MAX_TOTAL', len(prepared._sources[0][1]) * 4):
            self.assertIsNotNone(store.load(ref))
            recovered = store.reconstruct(ref, self.root / 'bounded')
            self.assertEqual(len(recovered.source_files), 5)

    def test_nested_recipe_directories_fsync_each_created_parent(self):
        from unittest import mock
        api, store, _, source, inputs = self.fixture()
        (source / 'modules/child').mkdir(parents=True)
        (source / 'modules/child/main.tf').write_bytes(b'output "value" { value = "nested" }\n')
        prepared = api.prepare(source_root=source, source_files=('modules/child/main.tf',),
                               variables_file=inputs, provider_lockfile=None,
                               source_revision='a' * 40, verify_source=lambda *args: True)
        receipt = self.publish(store, prepared)
        real_mkdir, real_fsync = os.mkdir, os.fsync
        for operation in ('stage', 'reconstruct'):
            events = []
            def mkdir(name, *args, **kwargs):
                result = real_mkdir(name, *args, **kwargs)
                info = os.fstat(kwargs['dir_fd'])
                events.append(('mkdir', (info.st_dev, info.st_ino), name))
                return result
            def fsync(fd):
                info = os.fstat(fd)
                events.append(('fsync', (info.st_dev, info.st_ino), None))
                return real_fsync(fd)
            with mock.patch.object(api.os, 'mkdir', side_effect=mkdir), mock.patch.object(api.os, 'fsync', side_effect=fsync):
                if operation == 'stage':
                    prepared.stage(self.root / operation)
                else:
                    store.reconstruct(receipt.baseline_ref, self.root / operation)
            with self.subTest(operation=operation):
                self.assertTrue(any(event[2] == 'child' for event in events))
                for index, (event, identity, name) in enumerate(events):
                    if event == 'mkdir':
                        self.assertIn(('fsync', identity, None), events[index + 1:],
                                      f'parent of {name} was not synchronized')

    def test_canonical_store_replacement_during_publication_fails_closed(self):
        from unittest import mock
        api, _, prepared, _, _ = self.fixture()
        real_replace = os.replace
        for phase in ('object', 'receipt'):
            with self.subTest(phase=phase):
                store = api.BaselineStore(self.root / ('store-' + phase))
                detached = self.root / ('detached-' + phase)
                swapped = False
                def replace(src, dst, **kwargs):
                    nonlocal swapped
                    result = real_replace(src, dst, **kwargs)
                    if not swapped and str(dst).startswith('object-' if phase == 'object' else 'baseline-'):
                        swapped = True
                        store.root.rename(detached)
                        store.root.mkdir(mode=0o700)
                    return result
                with mock.patch.object(api.os, 'replace', side_effect=replace):
                    with self.assertRaises(api.BaselineError):
                        self.publish(store, prepared)
                self.assertTrue(swapped)
                self.assertEqual(list(store.root.iterdir()), [])
                self.assertFalse(any(p.name.startswith('pending-') for p in detached.iterdir()))

    def test_concurrent_publishers_share_complete_immutable_content_addresses(self):
        from concurrent.futures import ThreadPoolExecutor
        _, store, prepared, _, _ = self.fixture()
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.publish(store, prepared), range(8)))
        self.assertEqual(len(set(receipts)), 1)
        self.assertEqual(store.load(receipts[0].baseline_ref), receipts[0])
        self.assertFalse(any(path.name.startswith('pending-') for path in store.root.iterdir()))


if __name__ == '__main__':
    unittest.main()
