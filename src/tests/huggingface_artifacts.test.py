"""Offline Hugging Face contract and consumer tests; no real Hub access."""
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import yaml

SRC = Path(__file__).resolve().parents[1]
ROLE = SRC / "ansible/roles/huggingface-artifacts"
sys.path.insert(0, str(SRC.parent))
from src.python.registry_profile import RegistryProfileError


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repository(**overrides):
    return dict(name="demo", repo_id="example/model", revision="a" * 40, **overrides)


class ProfileTests(unittest.TestCase):
    def test_token_reference_rejects_ansible_template_characters(self):
        for path in ("/tmp/{{lookup}}", "/tmp/{%template%}", "/tmp/$HOME/token", "/tmp/a b"):
            with self.subTest(path=path), self.assertRaises(RegistryProfileError):
                self.normalize({"huggingface": {"enabled": True, "repositories": [repository()], "token_file": path}})

    def normalize(self, profile):
        path = SRC / "python/huggingface_profile.py"
        self.assertTrue(path.exists(), "HF profile normalizer is not implemented")
        return load(path, "hf_profile_test").normalize_huggingface(profile)

    def test_disabled_by_default_independent_of_registry_and_cloud(self):
        for profile in ({}, {"cloud": "aws", "container_registry": {"enabled": True}},
                        {"huggingface": {"enabled": False}}):
            self.assertEqual(self.normalize(profile), {"huggingface": {"enabled": False}})


    def test_enabled_pinned_entries_are_normalized_without_mutation(self):
        data = {"enabled": True, "repositories": [repository(), repository(repo_type="dataset")],
                "token_file": "/home/operator/.secrets/hf-token"}
        data["repositories"][1]["name"] = "training"
        original = json.loads(json.dumps(data))
        expected = json.loads(json.dumps(data))
        expected["repositories"][0]["repo_type"] = "model"
        self.assertEqual(self.normalize({"huggingface": data}), {"huggingface": expected})
        self.assertEqual(data, original)

    def test_rejects_unsafe_or_ambiguous_contract(self):
        valid = {"enabled": True, "repositories": [repository()]}
        cases = [None, [], {"enabled": "false"}, {"enabled": 1}, {"token": "never-echo-me"},
                 {"enabled": True}, {"enabled": True, "repositories": []},
                 dict(valid, repositories={}), dict(valid, repositories=[None]),
                 dict(valid, repositories=[repository(), repository()])]
        for key, values in {
            "name": ["../escape", "/root", "Upper", "a\n", "a.b", ""],
            "repo_id": ["solo", "org/../x", "../model", "org/a..b", "org/a--b", "https://host/repo", "org/a.git"],
            "revision": ["main", "a" * 39, "A" * 40, 123, "a" * 40 + "\n"],
            "repo_type": ["space", "Model", None], "token": ["never-echo-me"],
        }.items():
            for value in values:
                entry = repository()
                entry[key] = value
                cases.append(dict(valid, repositories=[entry]))
        for path in ["relative", "/", "/a/../token", "/a/./token", "/a//token", "/a/'token", '/a/"token', "/a/\ntoken", "/a/\x7ftoken", 123, ""]:
            cases.append(dict(valid, token_file=path))
        # Disabled blocks are still validated: typos and inline secrets never hide.
        cases.append({"enabled": False, "token_file": "not-a-path"})
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(RegistryProfileError) as caught:
                    self.normalize({"huggingface": value})
                self.assertNotIn("never-echo-me", str(caught.exception))


class AnsibleTests(unittest.TestCase):
    def test_workstation_includes_optional_huggingface_before_workloads(self):
        meta = yaml.safe_load((SRC / "ansible/roles/isaac-workstation/meta/main.yml").read_text())
        roles = [entry["role"] for entry in meta["dependencies"]]
        self.assertIn("huggingface-artifacts", roles)
        self.assertLess(roles.index("huggingface-artifacts"), roles.index("gr00t"))

    def test_enabled_role_installs_system_venv_prerequisite(self):
        tasks = yaml.safe_load((ROLE / "tasks/download.yml").read_text())
        packages = [task["ansible.builtin.apt"] for task in tasks if "ansible.builtin.apt" in task]
        self.assertTrue(packages, "fresh workstations need python3-venv for the isolated downloader")
        self.assertIn("python3-venv", packages[0]["name"])

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which("su"),
                         "isolated enabled-role UID test requires root and su")
    def test_fresh_target_enabled_chain_bootstraps_pip_interpreter(self):
        # Run the real role and real installed Ansible pip module. Only passwd,
        # apt acquisition and pip's external commands are faked, inside tmp.
        # Ambient packaging/pkg_resources must not hide missing system deps.
        from ansible.modules import pip as ansible_pip

        account = pwd.getpwnam("nobody")
        with tempfile.TemporaryDirectory(prefix="hf-bootstrap-") as tmp:
            root = Path(tmp)
            root.chmod(0o755)
            home = root / "home"
            home.mkdir()
            os.chown(home, account.pw_uid, account.pw_gid)
            role = root / "roles/huggingface-artifacts"
            shutil.copytree(ROLE, role, ignore=shutil.ignore_patterns("__pycache__"))
            library = root / "library"
            library.mkdir()
            packages = root / "packages.json"
            library.joinpath("offline_apt.py").write_text(textwrap.dedent(f'''
                import json, os
                from pathlib import Path
                from ansible.module_utils.basic import AnsibleModule
                m = AnsibleModule(argument_spec=dict(name=dict(type='list'),
                    state=dict(), update_cache=dict(type='bool'), cache_valid_time=dict(type='int')))
                assert os.geteuid() == 0
                p = Path({str(packages)!r})
                changed = not p.exists()
                p.write_text(json.dumps(m.params['name']))
                p.chmod(0o644)
                m.exit_json(changed=changed)
            '''))
            library.joinpath("offline_getent.py").write_text(textwrap.dedent(f'''
                from ansible.module_utils.basic import AnsibleModule
                m = AnsibleModule(argument_spec=dict(database=dict(), key=dict()))
                m.exit_json(changed=False, ansible_facts={{'getent_passwd': {{m.params['key']:
                    ['x', {account.pw_uid!r}, {account.pw_gid!r}, '', {str(home)!r}, '/bin/sh']}}}})
            '''))
            # An intentionally unsuitable inventory interpreter must be overridden
            # for pip, not confused with virtualenv_command's Python selection.
            alternate = root / "alternate-python"
            alternate.write_text('#!/bin/sh\nexport HF_TEST_ALTERNATE_PYTHON=1\nexec /usr/bin/python3 "$@"\n')
            alternate.chmod(0o755)
            guard = textwrap.dedent(f'''
                import importlib.abc, json
                from pathlib import Path
                class FreshTargetImports(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        name = fullname.split('.')[0]
                        if name == 'pkg_resources' or (name == 'packaging' and (
                            'python3-packaging' not in json.loads(Path({str(packages)!r}).read_text())
                            or os.environ.get('HF_TEST_ALTERNATE_PYTHON') == '1')):
                            raise ImportError('fresh target lacks system packaging for this interpreter')
                for name in list(sys.modules):
                    if name.split('.')[0] in ('packaging', 'pkg_resources'):
                        del sys.modules[name]
                sys.meta_path.insert(0, FreshTargetImports())
            ''')
            downloader = textwrap.dedent(f'''
                #!/usr/bin/python3
                import json, os, sys
                from pathlib import Path
                assert os.geteuid() == {account.pw_uid}
                assert json.load(sys.stdin)['enabled'] is True
                marker = Path({str(home / 'downloaded')!r})
                changed = not marker.exists()
                marker.write_text(str(os.geteuid()))
                print(json.dumps({{'changed': changed}}))
            ''').lstrip()
            commands = textwrap.dedent(f'''
                def offline_command(self, cmd, **kwargs):
                    assert os.geteuid() == {account.pw_uid}
                    assert sys.executable == '/usr/bin/python3'
                    if isinstance(cmd, str):
                        cmd = shlex.split(cmd)
                    env = Path(self.params['virtualenv'])
                    installed = env / 'installed'
                    with Path({str(home / 'pip-commands')!r}).open('a') as log:
                        log.write(json.dumps(cmd) + '\\n')
                    if cmd == ['/usr/bin/python3', '--help']:
                        return 0, '', ''
                    if Path(cmd[0]).name == 'locale' and cmd[1:] == ['-a']:
                        return 0, 'C\\n', ''
                    if cmd == ['/usr/bin/python3', '-m', 'venv', str(env)]:
                        assert 'python3-venv' in json.loads(Path({str(packages)!r}).read_text())
                        (env / 'bin').mkdir(parents=True)
                        (env / 'bin/activate').touch()
                        (env / 'bin/pip').write_text('#!/bin/sh\\nexit 99\\n')
                        (env / 'bin/pip').chmod(0o700)
                        (env / 'bin/python').write_text({downloader!r})
                        (env / 'bin/python').chmod(0o700)
                        return 0, '', ''
                    if cmd[0] == str(env / 'bin/pip'):
                        if cmd[1] in ('list', 'freeze'):
                            return 0, 'huggingface-hub==0.34.4\\n' if installed.exists() else '', ''
                        if cmd[1] == 'install':
                            assert '-r' in cmd
                            assert Path(cmd[cmd.index('-r') + 1]).read_text().splitlines()[-1] == 'huggingface-hub==0.34.4'
                            installed.touch()
                            return 0, '', ''
                    raise AssertionError('external command forbidden: ' + repr(cmd))
                AnsibleModule.run_command = offline_command
            ''')
            pip_source = Path(ansible_pip.__file__).read_text()
            self.assertIn('PACKAGING_IMP_ERR = None', pip_source)
            self.assertIn("if __name__ == '__main__':", pip_source)
            pip_source = pip_source.replace('PACKAGING_IMP_ERR = None', guard + '\nPACKAGING_IMP_ERR = None', 1)
            pip_source = pip_source.replace("if __name__ == '__main__':", commands + "\nif __name__ == '__main__':", 1)
            library.joinpath("offline_pip.py").write_text(pip_source)
            task_file = role / "tasks/download.yml"
            tasks = task_file.read_text()
            for real, fake in (("apt", "offline_apt"), ("getent", "offline_getent"), ("pip", "offline_pip")):
                tasks = tasks.replace(f"ansible.builtin.{real}:", f"{fake}:")
            task_file.write_text(tasks)
            play = root / "play.yml"
            play.write_text(yaml.safe_dump([dict(hosts="localhost", gather_facts=False,
                become=True, become_user="root", vars=dict(ansible_user=account.pw_name,
                    ansible_become_method="su", ansible_become_flags="-s /bin/sh",
                    ansible_python_interpreter=str(alternate),
                    ansible_remote_tmp=str(root / "remote"),
                    huggingface_json=dict(enabled=True, repositories=[repository()])),
                roles=[str(role)])]))
            config = root / "ansible.cfg"
            config.write_text('[defaults]\nhost_key_checking = False\n')
            for expected_changed in (True, False):
                result = subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
                    cwd=root, env=dict(os.environ, ANSIBLE_CONFIG=str(config), ANSIBLE_LIBRARY=str(library)),
                    capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                download_output = result.stdout.split("Download pinned snapshots without exposing runtime credentials", 1)[1]
                self.assertIn("changed: [localhost]" if expected_changed else "ok: [localhost]", download_output)
                if not expected_changed:
                    self.assertIn("changed=0", result.stdout)
            self.assertEqual((home / "downloaded").read_text(), str(account.pw_uid))
            self.assertEqual({p.stat().st_uid for p in home.rglob('*')}, {account.pw_uid})
            calls = [json.loads(line) for line in (home / "pip-commands").read_text().splitlines()]
            self.assertEqual(sum(cmd[:3] == ['/usr/bin/python3', '-m', 'venv'] for cmd in calls), 1)

    def test_filter_accepts_mapping_and_json_and_rejects_duplicate_keys(self):
        path = ROLE / "filter_plugins/huggingface.py"
        self.assertTrue(path.exists(), "Ansible HF validation is not implemented")
        validate = load(path, "hf_filter_test").FilterModule().filters()["huggingface_settings"]
        value = {"enabled": True, "repositories": [repository()]}
        normalized = load(SRC / "python/huggingface_profile.py", "hf_normalizer").normalize_huggingface({"huggingface": value})["huggingface"]
        for data in (value, json.dumps(value)):
            self.assertEqual(validate(data), normalized)
        for data in ('{"enabled":false,"enabled":true}', '{"enabled":false,"token":"secret"}', '[]', 'broken', {"enabled": "false"}):
            with self.assertRaises(ValueError):
                validate(data)

    def play(self, value):
        with tempfile.TemporaryDirectory() as tmp:
            play = Path(tmp) / "play.yml"
            play.write_text(yaml.safe_dump([{"hosts": "localhost", "gather_facts": False,
                "vars": {"huggingface_json": value}, "roles": [str(ROLE)]}]))
            return subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
                                  capture_output=True, text=True, timeout=40)

    def test_direct_ansible_disabled_is_noop_and_invalid_fails_before_mutation(self):
        self.assertTrue((ROLE / "tasks/main.yml").exists(), "HF role is not implemented")
        for data in ({}, '{"enabled":false}'):
            result = self.play(data)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("changed=0", result.stdout)
        result = self.play({"enabled": True, "repositories": [dict(repository(), revision="main")]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed=0", result.stdout)


    def test_enabled_role_resolves_account_and_isolates_all_writes(self):
        tasks = yaml.safe_load((ROLE / "tasks/download.yml").read_text())
        self.assertTrue(any("ansible.builtin.getent" in task for task in tasks), "resolve home from passwd, not /home guess or elevated HOME")
        blocks = [task for task in tasks if "block" in task]
        self.assertEqual(len(blocks), 1, "all user filesystem and download operations must share the SSH-user block")
        block = blocks[0]
        self.assertIs(block["become"], True)
        self.assertEqual(block["become_user"], "{{ ansible_user }}")
        pip = next(task["ansible.builtin.pip"] for task in block["block"] if "ansible.builtin.pip" in task)
        self.assertIn("virtualenv", pip)
        self.assertEqual(pip["virtualenv_command"], "/usr/bin/python3 -m venv")
        command = next(task for task in block["block"] if "ansible.builtin.command" in task)
        self.assertIs(command["no_log"], True)
        self.assertIn("stdin", command["ansible.builtin.command"])
        self.assertNotIn("token", str(command["ansible.builtin.command"]["argv"]))
        self.assertIn("changed", command["changed_when"])
        self.assertEqual((ROLE / "files/requirements.txt").read_text().splitlines()[-1], "huggingface-hub==0.34.4")

    def test_enabled_direct_role_rejects_missing_ssh_account_before_writes(self):
        result = self.play({"enabled": True, "repositories": [repository()]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed=0", result.stdout)


class RunnerTests(unittest.TestCase):
    def run_fake(self, tmp, value, token: str | bool = False, fail=False):
        script = ROLE / "files/download_huggingface.py"
        self.assertTrue(script.exists(), "pinned snapshot runner is not implemented")
        home = Path(tmp) / "home"
        home.mkdir(exist_ok=True)
        fake = Path(tmp) / "huggingface_hub.py"
        fake.write_text('''import json, os
from pathlib import Path
def snapshot_download(**kwargs):
    assert kwargs['token'] == json.loads(os.environ['EXPECTED_TOKEN'])
    assert os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] == '1'
    assert 'HF_TOKEN' not in os.environ
    assert kwargs['endpoint'] == 'https://huggingface.co'
    assert 'trust_remote_code' not in kwargs and 'local_dir' not in kwargs
    assert kwargs['repo_type'] in ('model', 'dataset')
    if os.environ.get('FAKE_FAIL') == '1':
        print('dummy-secret-sensitive')
        raise RuntimeError('dummy-secret-sensitive')
    root = Path(kwargs['cache_dir']) / (kwargs['repo_type'] + 's--' + kwargs['repo_id'].replace('/', '--')) / 'snapshots' / kwargs['revision']
    root.mkdir(parents=True, exist_ok=True)
    file = root / 'weights.fake'
    if not file.exists(): file.write_text('fake bytes; not a model')
    log = Path(os.environ['FAKE_CALLS'])
    with log.open('a') as stream: stream.write(json.dumps({k:v for k,v in kwargs.items() if k != 'token'}) + '\\n')
    return str(root)
''')
        wrapper = Path(tmp) / "invoke.py"
        # Identity is mocked, not provisioned. Real runner is executed as __main__;
        # it can only reach the local fake Hub module, never the network.
        wrapper.write_text("import os,pwd,runpy,sys,types\n"
            "os.geteuid=lambda:1000\n"
            "pwd.getpwuid=lambda uid:types.SimpleNamespace(pw_dir=os.environ['TEST_HOME'])\n"
            "sys.path.insert(0, " + repr(str(ROLE / "files")) + ")\n"
            "runpy.run_path(" + repr(str(script)) + ",run_name='__main__')\n")
        env = dict(os.environ, PYTHONPATH=tmp, TEST_HOME=str(home), HF_TOKEN="ambient-secret-must-not-read",
                   EXPECTED_TOKEN=json.dumps(token), FAKE_CALLS=str(Path(tmp) / "calls"), FAKE_FAIL=str(int(fail)))
        return subprocess.run([sys.executable, str(wrapper)], input=json.dumps(value), text=True,
                              capture_output=True, env=env, timeout=20)

    def test_actual_runner_anonymous_pinned_model_dataset_and_repeat(self):
        value = {"enabled": True, "repositories": [repository(), dict(repository(repo_type="dataset"), name="training")]}
        with tempfile.TemporaryDirectory() as tmp:
            for expected in (True, False):
                result = self.run_fake(tmp, value)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["changed"], expected)
            calls = [json.loads(line) for line in (Path(tmp) / "calls").read_text().splitlines()]
            self.assertEqual(len(calls), 4)
            for call in calls:
                self.assertEqual(call["revision"], "a" * 40)
                self.assertTrue(call["cache_dir"].startswith(str(Path(tmp) / "home/.cache/isaac-automator/huggingface/")))
            # Deletion repairs from the pinned snapshot; no marker-only skip.
            next((Path(tmp) / "home").rglob("weights.fake")).unlink()
            result = self.run_fake(tmp, value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["changed"])

    def test_explicit_token_is_runtime_only_and_failures_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "operator-token"
            token.write_text("dummy-secret-sensitive\n")
            value = {"enabled": True, "repositories": [repository()], "token_file": str(token)}
            result = self.run_fake(tmp, value, token="dummy-secret-sensitive")
            self.assertEqual(result.returncode, 0, result.stderr)
            for file in (Path(tmp) / "home").rglob("*"):
                if file.is_file():
                    self.assertNotIn("dummy-secret-sensitive", file.read_text())
            result = self.run_fake(tmp, value, token="dummy-secret-sensitive", fail=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("dummy-secret-sensitive", result.stdout + result.stderr)
            token.unlink()
            result = self.run_fake(tmp, value, token="dummy-secret-sensitive")
            self.assertNotEqual(result.returncode, 0)

    def test_revision_changes_use_separate_snapshots_not_stale_overlays(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = {"enabled": True, "repositories": [repository()]}
            first = self.run_fake(tmp, value)
            self.assertEqual(first.returncode, 0, first.stderr)
            value["repositories"][0]["revision"] = "b" * 40
            second = self.run_fake(tmp, value)
            self.assertEqual(second.returncode, 0, second.stderr)
            old = json.loads(first.stdout)["snapshots"]["demo"]
            new = json.loads(second.stdout)["snapshots"]["demo"]
            self.assertNotEqual(old, new)
            self.assertTrue(Path(old).is_dir())
            self.assertTrue(Path(new).is_dir())
            self.assertTrue(json.loads(second.stdout)["changed"])

    def test_runtime_revalidates_inventory_before_import_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = {"enabled": True, "repositories": [dict(repository(), name="../escape")]}
            result = self.run_fake(tmp, value)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((Path(tmp) / "calls").exists())
            self.assertFalse((Path(tmp) / "home/.cache").exists())

    def test_disabled_never_imports_hub_or_reads_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_fake(tmp, {"enabled": False, "token_file": "/does/not/exist"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((Path(tmp) / "calls").exists())
            self.assertFalse((Path(tmp) / "home/.cache").exists())

    def test_root_runner_is_rejected_without_creating_cache(self):
        if os.geteuid() != 0:
            self.skipTest("root rejection requires a root test process")
        script = ROLE / "files/download_huggingface.py"
        result = subprocess.run([sys.executable, str(script)],
            input=json.dumps({"enabled": True, "repositories": [repository()]}),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1)

    def test_cache_symlinks_cannot_redirect_download_writes(self):
        value = {"enabled": True, "repositories": [repository()]}
        for relative in (".cache", ".cache/isaac-automator/huggingface/.xet",
                         ".cache/isaac-automator/huggingface/demo/models--example--model/blobs"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                link = home / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                outside = Path(tmp) / "outside"
                outside.mkdir()
                link.symlink_to(outside, target_is_directory=True)
                result = self.run_fake(tmp, value)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertFalse((Path(tmp) / "calls").exists())
                self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
