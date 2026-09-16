#!/usr/bin/env python3
"""Execute real installer seams offline, with disposable command binaries only.

Never invoke installer dispatch, installed repositories, or any package manager.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'isaac-installer/lib/core/config.sh'
CONDA = ROOT / 'isaac-installer/lib/modules/conda.sh'
SIM = ROOT / 'isaac-installer/lib/modules/isaacsim.sh'


class RuntimeConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='isaac-runtime-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home with spaces'
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        self.env_path = self.home / "miniforge ' quote/envs/isaaclab"
        self.conda = self.home / "miniforge ' quote/bin/conda"
        self.fake(self.conda, 'conda')
        self.fake(self.env_path / 'bin/python', 'python')
        self.python_template = self.root / 'python-template'
        self.python_template.write_text((self.env_path / 'bin/python').read_text())
        # Real python3 is used ONLY for the actual no-eval parser and test binaries.
        (self.bin / 'python3').symlink_to('/usr/bin/python3')
        self.env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.home),
                    'TARGET_HOME': str(self.home), 'TARGET_USER': 'fixture',
                    'CALL_LOG': str(self.log), 'FAKE_PYTHON_VERSION': '3.12.7',
                    'PYTHONDONTWRITEBYTECODE': '1'}
        self.profile = {'profile_name': 'fixture', 'workspace': {'layout': 'flat'},
                        'runtimes': {'lab': {'environment': 'isaaclab', 'python': '3.12',
                            'torch': '2.10.0+cu128', 'torchvision': '0.25.0+cu128',
                            'cuda_runtime': '12.8', 'architecture': 'sm_120'}}}

    def fake(self, path, name):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/usr/bin/python3\n' +
            'import json, os, sys\nfrom pathlib import Path\n' +
            f'name = {name!r}\n' +
            "with open(os.environ['CALL_LOG'], 'a') as f:\n"
            " f.write(json.dumps({'name': name, 'argv': sys.argv[1:], 'cwd': os.getcwd(), "
            "'home': os.environ.get('HOME'), 'solver': os.environ.get('CONDA_SOLVER')}) + '\\n')\n"
            "if name == 'python' and sys.argv[1:2] == ['-c']:\n"
            " print(os.environ.get('FAKE_PYTHON_VERSION', '3.12.7'))\n"
            "if name == 'conda' and 'create' in sys.argv and not os.environ.get('FAIL_CONDA'):\n"
            " p=Path(sys.argv[sys.argv.index('--prefix')+1])/'bin/python'; p.parent.mkdir(parents=True,exist_ok=True)\n"
            " p.write_text(Path(os.environ['PYTHON_TEMPLATE']).read_text()); p.chmod(0o755)\n"
            "if name == 'wget':\n"
            " Path(sys.argv[sys.argv.index('-O') + 1]).write_bytes(b'fixture archive bytes')\n"
            "if name == 'unzip':\n"
            " p=Path(sys.argv[sys.argv.index('-d') + 1]); p.mkdir(parents=True, exist_ok=True)\n"
            " (p/'isaac-sim.sh').write_text('fixture launcher')\n"
            " (p/'isaac-sim.sh').chmod(0o755)\n"
            "sys.exit(int(os.environ.get('FAIL_' + name.upper(), '0')))\n")
        path.chmod(0o755)

    def run_shell(self, body, profile=None):
        config = self.root / 'profile.yaml'
        config.write_text(yaml.safe_dump(profile or self.profile))
        script = f'''set -euo pipefail
SCRIPT_DIR={shlex.quote(str(ROOT / 'isaac-installer'))}
source {shlex.quote(str(CONFIG))}
source {shlex.quote(str(CONDA))}
source {shlex.quote(str(SIM))}
detect_target_user() {{ :; }}
log_step() {{ :; }}; log_info() {{ :; }}; log_warn() {{ :; }}
log_success() {{ :; }}; log_header() {{ :; }}; log_error() {{ printf '%s\\n' "$*" >&2; }}
# Native run_as_user takes ONE shell string, not variadic argv. Execute it,
# rather than merely inspecting a mock call; printf %q must survive bash -c.
run_as_user() {{ [[ $# == 1 ]] || return 91; /bin/bash -c "$1"; }}
resolve_conda_bin() {{ printf '%s\\n' {shlex.quote(str(self.conda))}; }}
load_config_profile {shlex.quote(str(config))}
{body}
'''
        return subprocess.run(['/bin/bash', '-c', script], env=self.env,
                              cwd=self.root, capture_output=True, text=True)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_mismatched_or_unsafe_pins_refuse_before_package_mutation(self):
        cases = [('architecture', 'sm_89'), ('architecture', 'sm_999'),
                 ('cuda_runtime', '12.4'), ('python', '3.10'),
                 ('environment', 'other-lab'), ('torch', "2.1; touch injected"),
                 ('cuda_runtime', '12.8.1')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.profile['runtimes']['lab'][key], old = value, self.profile['runtimes']['lab'][key]
                self.log.unlink(missing_ok=True)
                result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime')
                self.profile['runtimes']['lab'][key] = old
                self.assertNotEqual(result.returncode, 0, (key, result.stdout))
                self.assertFalse(any(x['argv'][:3] == ['-m', 'pip', 'install'] for x in self.calls()))
                self.assertFalse((self.root / 'injected').exists())
                self.profile['runtimes']['lab'][key] = old
        self.log.unlink(missing_ok=True)
        result = self.run_shell('unset GPU_COMPUTE_CAP; install_profile_lab_runtime')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_new_environment_uses_exact_python_pin_without_official_helper_fallback(self):
        (self.env_path / 'bin/python').unlink()
        self.env['PYTHON_TEMPLATE'] = str(self.python_template)
        result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0]['name'], 'conda')
        self.assertEqual(calls[0]['argv'], ['create', '-y', '--prefix', str(self.env_path),
            'python=3.12', 'pip', '-c', 'conda-forge'])
        self.assertEqual(calls[0]['solver'], 'classic')
        self.assertTrue((self.env_path / 'bin/python').exists())
        self.assertNotIn('--conda', str(calls))
        self.log.unlink()
        (self.env_path / 'bin/python').unlink()
        self.env['FAIL_CONDA'] = '42'
        result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_installer_dispatch_uses_pinned_seam_and_preserves_named_resolver_guard(self):
        # Trap the legacy deletion path BEFORE invoking the real function. Only
        # the pinned consumer and a disposable end-of-stage hook may run.
        body = '''
GPU_COMPUTE_CAP=12.0
resolve_active_repo_dir() { printf '%s\\n' "$HOME/work space/IsaacLab"; }
rm() { printf 'legacy cleanup must not execute' >&2; exit 93; }
sed() { exit 93; }; wget() { exit 93; }; run_as_root() { exit 93; }
configure_python_env_hooks() { printf 'HOOK_PATH=%s\\n' "$1"; }
install_python_env
'''
        result = self.run_shell(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('HOOK_PATH=' + str(self.env_path), result.stdout)
        self.assertTrue(any(x['argv'][:3] == ['-m', 'pip', 'install'] for x in self.calls()))
        self.log.unlink()
        result = self.run_shell(body.replace('install_python_env', '''
WORKSPACE_LAYOUT=named
resolve_active_repo_dir() { return 72; }
install_python_env'''))
        self.assertEqual(result.returncode, 72)
        self.assertEqual(self.calls(), [])

    def test_custom_pypi_pins_use_selected_environment_without_dependency_upgrades(self):
        self.profile['runtimes']['lab']['packages'] = 'example-extra==1.2.3\nsecond_pkg==4.5.6'
        result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        installs = [x['argv'] for x in self.calls() if x['argv'][:3] == ['-m', 'pip', 'install']]
        self.assertEqual(installs[-1], ['-m', 'pip', 'install', '--no-deps', '--',
            'example-extra==1.2.3', 'second_pkg==4.5.6'])
        self.assertEqual(len(installs), 2)
        for spec in ('torch==1.2.3', 'uv==1.2.3', 'bad;touch injected==1.2.3', 'extra>=1.2', '--upgrade'):
            with self.subTest(spec=spec):
                self.log.unlink(missing_ok=True)
                self.profile['runtimes']['lab']['packages'] = spec
                result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / 'injected').exists())

    def test_same_frozen_default_maps_local_and_ansible_pins_then_executes_local(self):
        from src.python.workstation_profile import resolve_profile
        from src.python.profile_adapters import render_profile
        desired = resolve_profile('default')['profile']
        frozen = json.dumps(desired, sort_keys=True)
        local = render_profile(desired, 'local', '/home/reviewer')
        cloud = render_profile(desired, 'ansible', '/home/reviewer')
        self.assertTrue(local['render_supported'], local['blockers'])
        mapping = {'environment': 'conda_env_name', 'python': 'conda_python_version',
                   'torch': 'profile_lab_torch', 'cuda_runtime': 'profile_lab_cuda_runtime',
                   'architecture': 'profile_lab_architecture'}
        for field, variable in mapping.items():
            self.assertEqual(local['artifact']['runtimes']['lab'][field], cloud['artifact'][variable])
            self.assertEqual(local['coverage']['runtimes.lab.' + field]['status'], 'mapped')
        result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime', local['artifact'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('torch==' + desired['runtimes']['lab']['torch'], str(self.calls()))
        self.assertEqual(json.dumps(desired, sort_keys=True), frozen)
        self.assertFalse(local['apply_supported'])

    def test_custom_dependency_mapping_reaches_actual_consumer_only_when_selected(self):
        from src.python.workstation_profile import resolve_profile
        from src.python.profile_adapters import render_profile
        desired = resolve_profile('default')['profile']
        desired['custom_dependencies'] = [{'id': 'extra', 'name': 'example-extra', 'version': '1.2.3',
            'environment': 'isaaclab', 'location': None, 'purpose': 'direct pinned extra',
            'source': 'pypi', 'placement': 'environment', 'required': True, 'support': 'unsupported'}]
        report = render_profile(desired, 'local', '/home/reviewer')
        self.assertTrue(report['render_supported'], report['blockers'])
        result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime', report['artifact'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('example-extra==1.2.3', str(self.calls()))
        desired['custom_dependencies'][0]['environment'] = 'gr00t'
        self.assertFalse(render_profile(desired, 'local', '/home/reviewer')['render_supported'])

    def prepare_archive_fixture(self):
        for name in ('wget', 'unzip', 'chown'):
            self.fake(self.bin / name, name)
        # sudo is a disposable argv dispatcher, never privilege elevation.
        (self.bin / 'sudo').write_text('#!/bin/bash\n[[ "$1" == -H && "$2" == -u ]] || exit 98\nshift 3\nexec "$@"\n')
        (self.bin / 'sudo').chmod(0o755)
        (self.bin / 'python3').unlink()
        wrapper = '''#!/usr/bin/python3
import io, json, os, runpy, socket, sys
from unittest.mock import patch, MagicMock
if len(sys.argv) > 2 and sys.argv[1] == '-I' and sys.argv[2].endswith('/public_artifact.py'):
    with open(os.environ['CALL_LOG'], 'a') as f:
        f.write(json.dumps({'name':'public_artifact', 'argv':sys.argv[1:]})+'\\n')
    class Wire:
        def settimeout(self, value): pass
        def connect(self, addr): pass
        def sendall(self, value): pass
        def close(self): pass
        def makefile(self, *args):
            body=b'fixture archive bytes'
            return io.BytesIO(b'HTTP/1.1 200 OK\\r\\nContent-Length: '+str(len(body)).encode()+b'\\r\\n\\r\\n'+body)
    tls=MagicMock(); tls.wrap_socket.side_effect=lambda sock, **kwargs:sock
    with patch('socket.getaddrinfo', return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]), patch('socket.socket', side_effect=lambda *args: Wire()), patch('ssl.SSLContext', return_value=tls):
        sys.argv=sys.argv[2:]
        runpy.run_path(sys.argv[0], run_name='__main__')
else:
    os.execv('/usr/bin/python3', ['/usr/bin/python3']+sys.argv[1:])
'''
        (self.bin / 'python3').write_text(wrapper)
        (self.bin / 'python3').chmod(0o755)
        self.sim_dir = self.home / 'Sim custom directory'
        self.archive_url = 'https://artifacts.example.org/exact-sim-6.0.1.zip'
        self.archive_sha = hashlib.sha256(b'fixture archive bytes').hexdigest()
        self.profile['simulation'] = {'isaacsim': {'version': '6.0.1', 'source_type': 'standalone',
            'install_dir': str(self.sim_dir), 'url': self.archive_url, 'sha256': self.archive_sha}}

    def test_explicit_archive_uses_actual_verified_helper_before_extraction(self):
        self.prepare_archive_fixture()
        result = self.run_shell('install_isaac_sim')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0]['name'], 'public_artifact', calls)
        argv = calls[0]['argv']
        self.assertEqual(argv[:2], ['-I', str(ROOT / 'src/python/public_artifact.py')])
        self.assertEqual(argv[argv.index('--url')+1], self.archive_url)
        self.assertEqual(argv[argv.index('--sha256')+1], self.archive_sha)
        extraction = next(x for x in calls if x['name'] == 'unzip')
        self.assertEqual(extraction['argv'][-2:], ['-d', str(self.sim_dir)])
        self.assertTrue((self.sim_dir / '.eula_accepted').exists())
        self.assertFalse(any(x['name'] == 'wget' for x in calls))
        self.assertEqual(list(self.home.glob('.isaacsim-archive.*')), [])

    def test_python_resolver_and_check_do_not_skip_explicit_pins(self):
        self.profile['runtimes']['lab']['python'] = '3.11.9'
        hook = self.env_path / 'etc/conda/activate.d/00_isaaclab_env.sh'
        hook.parent.mkdir(parents=True)
        hook.write_text('fixture')
        self.fake(self.bin / 'uv', 'uv')
        self.fake(self.bin / 'isaaclab-env', 'shim')
        result = self.run_shell('resolve_target_python_version; if check_python_env; then exit 99; fi')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '3.11.9')
        self.assertEqual(self.calls(), [])

    def test_activation_hook_paths_survive_native_shell_string_boundary(self):
        body = '''
run_as_user_stdin() { [[ "$1" == "$TARGET_HOME/"* ]] || return 90; /usr/bin/tee "$1" >/dev/null; }
run_as_root() { /usr/bin/cat > "$HOME/shim.fixture"; }
mkdir() { [[ "$*" == *"$TARGET_HOME"* ]] && /usr/bin/mkdir "$@" || :; }
cp() { :; }; chmod() { :; }
configure_python_env_hooks "$(resolve_conda_env_path isaaclab)"
'''
        result = self.run_shell(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        hook = self.env_path / 'etc/conda/activate.d/00_isaaclab_env.sh'
        self.assertTrue(hook.is_file())
        self.assertIn('CARB_APP_PATH', hook.read_text())

    def test_archive_check_does_not_treat_existing_launcher_as_checksum_conformance(self):
        self.prepare_archive_fixture()
        self.sim_dir.mkdir()
        launcher = self.sim_dir / 'isaac-sim.sh'
        launcher.write_text('fixture')
        launcher.chmod(0o755)
        result = self.run_shell('if check_isaac_sim; then exit 99; fi')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.sim_dir / '.eula_accepted').exists())
        self.assertEqual(self.calls(), [])

    def test_real_run_as_user_receives_quoted_runtime_command(self):
        # Execute the real native helper, replacing only its bash binary so no
        # login startup files or ambient user configuration are read/executed.
        bash = self.bin / 'bash'
        bash.write_text('#!/bin/bash\n[[ "$1" == -l ]] && shift\nexec /bin/bash "$@"\n')
        bash.chmod(0o755)
        self.env['USER'] = 'fixture'
        result = self.run_shell(f'''source {shlex.quote(str(CONFIG.parent / 'detect.sh'))}
detect_target_user() {{ :; }}
GPU_COMPUTE_CAP=12.0
install_profile_lab_runtime''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('torch==2.10.0+cu128', str(self.calls()))

    def test_explicit_archive_refuses_unqualified_existing_target(self):
        self.prepare_archive_fixture()
        self.sim_dir.mkdir()
        marker = self.sim_dir / 'keep-user-data'
        marker.write_text('untouched')
        result = self.run_shell('install_isaac_sim')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(marker.read_text(), 'untouched')
        self.assertEqual(list(self.sim_dir.iterdir()), [marker])

    def test_checksum_failure_never_extracts_or_accepts_eula(self):
        self.prepare_archive_fixture()
        for digest in ('0' * 64, 'broken', ''):
            with self.subTest(digest=digest):
                self.log.unlink(missing_ok=True)
                self.profile['simulation']['isaacsim']['sha256'] = digest
                result = self.run_shell('install_isaac_sim')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('checksum' if digest == '0' * 64 else 'SHA256', result.stderr)
                self.assertFalse(any(x['name'] in ('unzip', 'wget') for x in self.calls()))
                self.assertFalse(self.sim_dir.exists())
                self.assertEqual(list(self.home.glob('.isaacsim-archive.*')), [])
        self.profile['simulation']['isaacsim']['sha256'] = self.archive_sha
        self.env['FAIL_UNZIP'] = '44'
        result = self.run_shell('install_isaac_sim')
        self.assertEqual(result.returncode, 44, result.stderr)
        self.assertFalse((self.sim_dir / '.eula_accepted').exists())

    def test_archive_mapping_shared_frozen_intent_reaches_actual_local_installer(self):
        from src.python.workstation_profile import resolve_profile
        from src.python.profile_adapters import render_profile
        self.prepare_archive_fixture()
        desired = resolve_profile('default')['profile']
        desired['components']['sim']['source'].update(url=self.archive_url, sha256=self.archive_sha)
        frozen = json.dumps(desired, sort_keys=True)
        local = render_profile(desired, 'local', str(self.home))
        cloud = render_profile(desired, 'ansible', str(self.home))
        self.assertTrue(local['render_supported'], local['blockers'])
        sim = local['artifact']['simulation']['isaacsim']
        self.assertEqual(sim['url'], cloud['artifact']['isaacsim_archive_url'])
        self.assertEqual(sim['sha256'], cloud['artifact']['isaacsim_archive_sha256'])
        self.assertEqual(sim['version'], cloud['artifact']['isaacsim_version'])
        result = self.run_shell('install_isaac_sim', local['artifact'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / 'IsaacSim/.eula_accepted').exists())
        self.assertEqual(json.dumps(desired, sort_keys=True), frozen)
        for field in ('url', 'sha256'):
            incomplete = json.loads(frozen)
            del incomplete['components']['sim']['source'][field]
            report = render_profile(incomplete, 'local', str(self.home))
            self.assertFalse(report['render_supported'])
            self.assertIn('components.sim.source.' + field, [x['field'] for x in report['blockers']])

    def test_lab_pins_reach_native_environment_and_pip_argv(self):
        result = self.run_shell('GPU_COMPUTE_CAP=12.0; install_profile_lab_runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0]['argv'][0], '-c')
        pip = [x for x in calls if x['argv'][:3] == ['-m', 'pip', 'install']]
        self.assertEqual(len(pip), 1, calls)
        self.assertEqual(pip[0]['argv'], ['-m', 'pip', 'install', '--index-url',
            'https://download.pytorch.org/whl/cu128', '--',
            'torch==2.10.0+cu128', 'torchvision==0.25.0+cu128'])
        self.assertEqual(pip[0]['home'], str(self.home))
        self.assertFalse(any(x['name'] == 'conda' for x in calls), calls)


if __name__ == '__main__':
    unittest.main()
