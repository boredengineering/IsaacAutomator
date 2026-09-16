#!/usr/bin/env python3
"""Pure workspace resolution against synthetic temporary directories only."""
import os
import importlib.util
import unittest
from unittest.mock import patch


def paths_api():
    spec = importlib.util.spec_from_file_location('contract_workspace_paths', CORE / 'workspace_paths.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PureWorkspaceContract(unittest.TestCase):
    def test_ancestor_traversal_never_requests_directory_read_access(self):
        api = paths_api()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'selected'
            target.mkdir()
            original_open = os.open
            def selected_read_only(path, flags, *args, **kwargs):
                if str(path) != '.':
                    self.assertTrue(flags & os.O_PATH, 'ancestor traversal requested read access')
                else:
                    self.assertFalse(flags & os.O_PATH)
                    self.assertEqual(os.fstat(kwargs['dir_fd']).st_ino, target.stat().st_ino)
                return original_open(path, flags, *args, **kwargs)
            with patch.object(os, 'open', side_effect=selected_read_only):
                fd = api.open_directory_nofollow(target)
                self.assertIsNotNone(fd)
                try:
                    self.assertEqual(os.fstat(fd).st_ino, target.stat().st_ino)
                    self.assertEqual(os.listdir(fd), [])
                finally:
                    os.close(fd)

    def test_explicit_home_and_typed_settings_refuse_malformed_values(self):
        api = paths_api()
        args = dict(home='/fixture/home', repo='IsaacLab', root='~/work', layout='flat')
        for key, value in (('home', '~/someone'), ('github_desktop', 'false'), ('configured_owner', None),
                           ('root', None), ('slug', None), ('path_override', [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.resolve_paths(**dict(args, **{key: value}))

    def test_supplied_entries_validate_bounds_components_and_named_collisions(self):
        api = paths_api()
        args = dict(home='/fixture/home', root='~/work', repo='IsaacLab', layout='named', name='Chosen')
        for entries in ({'/fixture/home/work': ['chosen']},
                        {'/fixture/home/work': ['Chosen', 'chosen']},
                        {'/fixture/home/work/Chosen': ['isaaclab']},
                        {'/fixture/home': [{'name': 'work', 'kind': 'symlink'}]},
                        {'/fixture/home/work': ['a'] * 4097},
                        {'/fixture/home/work': [{'name': '../escape', 'kind': 'directory'}]}):
            with self.subTest(entries=str(entries)[:90]), self.assertRaises(ValueError):
                api.resolve_paths(**args, directory_entries=entries)
        self.assertEqual(api.resolve_paths(**args, directory_entries={
            '/fixture/home/work': ['Chosen'], '/fixture/home/work/Chosen': ['IsaacLab']
        })['destination'], '/fixture/home/work/Chosen/IsaacLab')

    def test_selected_leaf_case_collisions_refuse_in_every_layout(self):
        api = paths_api()
        for layout in ('flat', 'auto', 'org', 'named'):
            for override in ('', '/fixture/override/IsaacLab'):
                for exact in (False, True):
                    with self.subTest(layout=layout, override=override, exact=exact):
                        group = ('/fixture/override' if override else '/fixture/home/work' +
                                 ('/Chosen' if layout == 'named' else '/Owner' if layout in ('auto', 'org') else ''))
                        entries = {'/fixture/home/work': ['Chosen', 'Owner']}
                        entries[group] = ['isaaclab'] + (['IsaacLab'] if exact else [])
                        with self.assertRaisesRegex(ValueError, 'case-only collision'):
                            api.resolve_paths(home='/fixture/home', root='~/work', repo='IsaacLab',
                                              layout=layout, name='Chosen' if layout == 'named' else '',
                                              configured_owner='Owner' if layout in ('auto', 'org') else '',
                                              path_override=override, directory_entries=entries)

    def test_default_root_uses_only_supplied_home_entries(self):
        api = paths_api()
        args = dict(home='/fixture/home', repo='IsaacLab', layout='flat')
        self.assertEqual(api.resolve_paths(**args)['status'], 'unknown')
        for entries, expected in (({'/fixture/home/Documents': ['GitHub']}, 'Documents/GitHub'),
                                  ({'/fixture/home/Documents': [], '/fixture/home': ['workspace']}, 'workspace'),
                                  ({'/fixture/home/Documents': [], '/fixture/home': []}, '')):
            self.assertEqual(api.resolve_paths(**args, directory_entries=entries)['destination'],
                             str(Path('/fixture/home') / expected / 'IsaacLab'))
        self.assertEqual(api.resolve_paths(**args, github_desktop=True)['root'], '/fixture/home/Documents/GitHub')

    def test_legacy_owner_priority_case_reuse_and_ambiguity(self):
        api = paths_api()
        args = dict(home='/fixture/home', root='~/work', repo='IsaacLab', layout='auto')
        entries = {'/fixture/home/work': ['ExistingOwner', 'NVIDIA']}
        cases = [('Configured', 'fork/repo', 'Configured'),
                 ('existingowner', 'fork/repo', 'ExistingOwner'),
                 ('', 'git@github.com:Fork/repo.git', 'Fork'),
                 ('<placeholder>', 'https://github.com/Fork/repo.git', 'Fork'),
                 ('', 'NVIDIA/repo', 'NVIDIA'), ('Configured', 'NVIDIA/repo', 'NVIDIA'),
                 ('', 'isaac-sim/repo', '')]
        for owner, slug, expected in cases:
            with self.subTest(owner=owner, slug=slug):
                result = api.resolve_paths(**args, configured_owner=owner, slug=slug,
                                           directory_entries=entries)
                self.assertEqual(result['destination'], str(Path('/fixture/home/work') / expected / 'IsaacLab'))
        with self.assertRaisesRegex(ValueError, 'ambigu'):
            api.resolve_paths(**args, configured_owner='Owner',
                              directory_entries={'/fixture/home/work': ['Owner', 'owner']})
        result = api.resolve_paths(**args, configured_owner='Owner')
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['destination'])
        self.assertEqual(result['candidate_destination'], '/fixture/home/work/Owner/IsaacLab')

    def test_named_and_override_are_pure_exact_paths(self):
        api = paths_api()
        self.assertTrue(callable(getattr(api, 'resolve_paths', None)), 'pure resolve_paths missing')
        with patch.object(os, 'scandir', side_effect=AssertionError('filesystem read')), \
                patch.object(Path, 'lstat', side_effect=AssertionError('filesystem read')):
            result = api.resolve_paths(home='/fixture/home', root='~/work', repo='IsaacLab',
                                       layout='named', name='Bored Engineer', slug='remote/IsaacLab')
            self.assertEqual(result['destination'], '/fixture/home/work/Bored Engineer/IsaacLab')
            result = api.resolve_paths(home='/fixture/home', root='invalid unrelated root', repo='IsaacLab',
                                       layout='named', name='Chosen', path_override='~/custom')
            self.assertEqual(result['destination'], '/fixture/home/custom')

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "isaac-installer/lib/core"


class InstallerWorkspaceContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.workspace = self.home / "Documents/GitHub"

    def resolve(self, function="resolve_repo_dest_path", repo="IsaacLab",
                slug="boredengineering/IsaacLab", explicit="", before="", **values):
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
               "HOME": str(self.home), "USER": "workspace-fixture", "SUDO_USER": ""}
        env.update(WORKSPACE_DIR=str(self.workspace))
        env.update(values)
        # Block action commands as a second guard; state snapshots prove actual writes.
        script = '''set -euo pipefail
SCRIPT_DIR="${1%/lib/core}"
source "$1/detect.sh"
source "$1/config.sh"
source "$1/git_workspace.sh"
for action in git gh sudo chown chmod curl wget; do
  eval "$action() { printf 'forbidden action: %s\\n' '$action' >&2; return 97; }"
done
''' + before + '''
"$2" "$3" "$4" "$5"
'''
        return subprocess.run(["bash", "-c", script, "workspace-contract", str(CORE),
                               function, repo, slug, explicit], env=env, cwd=self.root,
                              capture_output=True, text=True, timeout=10)

    def assert_path(self, result, path):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(path) + "\n")
        self.assertEqual(result.stderr, "")

    def test_named_destination_preserves_explicit_spelling_not_remote_owner(self):
        (self.workspace / "boredengineering").mkdir(parents=True)
        self.assert_path(self.resolve(WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Bored Engineer"),
                         self.workspace / "Bored Engineer/IsaacLab")
        self.assertFalse((self.workspace / "Bored Engineer").exists())

    def test_invalid_workspace_names_and_combinations_fail_closed(self):
        cases = [("named", name, "") for name in
                 ("", " ", ".", "..", "../escape", "a/b", "a\\b", " a", "a ",
                  "a\nb", "a\tb", "a\x7fb", "-option", "$(touch canary)", "café")]
        cases += [("flat", "Chosen", ""), ("auto", "Chosen", ""),
                  ("org", "Chosen", ""), ("unknown", "", ""),
                  ("named", "Chosen", "Different")]
        for layout, name, owner in cases:
            with self.subTest(layout=layout, name=name, owner=owner):
                result = self.resolve(WORKSPACE_LAYOUT=layout, WORKSPACE_NAME=name,
                                      WORKSPACE_DEFAULT_OWNER=owner)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("workspace", result.stderr.lower())
        self.assertFalse(self.workspace.exists())

    def test_case_only_workspace_or_repo_collisions_refuse_even_with_exact_match(self):
        for level in ("workspace", "repo"):
            for exact in (False, True):
                with self.subTest(level=level, exact=exact):
                    base = self.workspace / (level + str(exact))
                    parent = base if level == "workspace" else base / "Chosen"
                    parent.mkdir(parents=True)
                    wanted = "Chosen" if level == "workspace" else "IsaacLab"
                    (parent / wanted.lower()).mkdir()
                    if exact:
                        (parent / wanted).mkdir()
                    result = self.resolve(WORKSPACE_DIR=str(base), WORKSPACE_LAYOUT="named",
                                          WORKSPACE_NAME="Chosen")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("collision", result.stderr.lower())

    def test_roots_expand_selected_home_and_reject_unsafe_paths(self):
        self.assert_path(self.resolve("resolve_default_workspace_dir", WORKSPACE_DIR="~/Repo Space"),
                         self.home / "Repo Space")
        for value in ("relative", "~other/work", "/", str(self.home / "../escape"),
                      str(self.home / "bad\nroot"), str(self.home / "bad\\root")):
            with self.subTest(value=value):
                result = self.resolve("resolve_default_workspace_dir", WORKSPACE_DIR=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.assertFalse((self.home / "Repo Space").exists())

    def test_selected_path_components_reject_files_and_symlinks(self):
        for level in ("root", "group", "repo"):
            for kind in ("file", "link", "dangling"):
                with self.subTest(level=level, kind=kind):
                    base = self.workspace / (level + kind)
                    target = {"root": base, "group": base / "Chosen",
                              "repo": base / "Chosen/IsaacLab"}[level]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if kind == "file":
                        target.write_text("user data")
                    else:
                        target.symlink_to(self.home if kind == "link" else self.home / "absent")
                    result = self.resolve(WORKSPACE_DIR=str(base), WORKSPACE_LAYOUT="named",
                                          WORKSPACE_NAME="Chosen")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("workspace", result.stderr.lower())

    def test_repository_segment_cannot_escape_named_group(self):
        for repo in ("../escape", "/outside", "a/b", "a\\b", "", "..", "bad\nname"):
            with self.subTest(repo=repo):
                result = self.resolve(repo=repo, WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_named_active_selection_never_uses_unrelated_discovery(self):
        unrelated = self.home / "IsaacLab/.git"
        unrelated.mkdir(parents=True)
        self.assert_path(self.resolve("resolve_active_repo_dir", WORKSPACE_LAYOUT="named",
                                      WORKSPACE_NAME="Chosen"), self.workspace / "Chosen/IsaacLab")
        override = self.home / "explicit repo"
        self.assert_path(self.resolve("resolve_active_repo_dir", explicit=str(override),
                                      WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen"), override)

    def test_explicit_override_is_validated_without_requiring_default_root(self):
        invalid_root = self.home / "unrelated link"
        invalid_root.symlink_to(self.home)
        self.assert_path(self.resolve(explicit="~/override dir", WORKSPACE_DIR=str(invalid_root),
                                      WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen"),
                         self.home / "override dir")
        file = self.home / "file"
        file.write_text("preserve")
        link = self.home / "link"
        link.symlink_to(self.home / "missing")
        (self.home / "CaseRepo").mkdir()
        for explicit in ("relative", "/", str(self.home), "~/../escape", str(file),
                         str(link), str(self.home / "caserepo")):
            with self.subTest(explicit=explicit):
                result = self.resolve(explicit=explicit, WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_existing_named_destinations_refuse_before_any_setup_action(self):
        for kind in ("repository", "directory", "file", "dangling"):
            with self.subTest(kind=kind):
                dest = self.workspace / "Chosen" / kind
                dest.parent.mkdir(parents=True, exist_ok=True)
                if kind in ("repository", "directory"):
                    dest.mkdir()
                    if kind == "repository":
                        (dest / ".git").mkdir()
                        (dest / ".git/config").write_text("synthetic private metadata")
                        (dest / "uncommitted").write_text("uncommitted work")
                elif kind == "file":
                    dest.write_text("user data")
                else:
                    dest.symlink_to(self.home / "missing")
                snapshot = self.snapshot()
                result = self.resolve("setup_git_repo_with_fork", repo=str(dest),
                                      slug="example/repo", explicit="upstream/repo",
                                      WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen",
                                      before='mkdir() { touch "$HOME/setup-attempt"; return 97; }')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("adoption", result.stderr.lower())
                self.assertEqual(self.snapshot(), snapshot)

    def snapshot(self):
        return {str(p.relative_to(self.home)): (p.lstat().st_mode,
                os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                for p in self.home.rglob("*")}

    def test_exact_existing_named_selection_is_read_only_including_git_file(self):
        for marker in ("directory", "file"):
            target = self.workspace / marker / "Chosen/IsaacLab"
            target.mkdir(parents=True)
            if marker == "directory":
                (target / ".git").mkdir()
                (target / ".git/config").write_text("private metadata")
            else:
                (target / ".git").write_text("gitdir: /out-of-scope/never-read")
            (target / "untracked").write_text("local work")
            snapshot = self.snapshot()
            for function in ("resolve_repo_dest_path", "resolve_active_repo_dir"):
                self.assert_path(self.resolve(function, WORKSPACE_DIR=str(self.workspace / marker),
                                              WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen"), target)
                self.assertEqual(self.snapshot(), snapshot)

    def test_runtime_component_inspection_uses_nofollow_handles_not_path_lstat(self):
        api = paths_api()
        target = self.workspace / 'Chosen/IsaacLab'
        target.mkdir(parents=True)
        with patch.object(Path, 'lstat', side_effect=AssertionError('path-based component race')):
            self.assertEqual(api.resolve_runtime(str(self.home), 'IsaacLab', '', '',
                                                 str(self.workspace), 'named', 'Chosen', ''), str(target))
        target.rmdir()
        target.symlink_to(self.home)
        with self.assertRaises((OSError, ValueError)):
            api.resolve_runtime(str(self.home), 'IsaacLab', '', '', str(self.workspace), 'named', 'Chosen', '')

    def test_runtime_selected_leaf_case_collision_is_bounded_in_every_layout(self):
        api = paths_api()
        for layout in ('flat', 'auto', 'org', 'named'):
            for exact in (False, True):
                with self.subTest(layout=layout, exact=exact):
                    root = self.workspace / (layout + str(exact))
                    group = root / 'Chosen' if layout == 'named' else root / 'Owner' if layout in ('auto', 'org') else root
                    group.mkdir(parents=True)
                    (group / 'isaaclab').mkdir()
                    if exact:
                        (group / 'IsaacLab').mkdir()
                    snapshot = self.snapshot()
                    with patch.object(api, 'bounded_directory_entries', wraps=api.bounded_directory_entries) as listing:
                        with self.assertRaisesRegex(ValueError, 'case-only collision'):
                            api.resolve_runtime(str(self.home), 'IsaacLab', '', '', str(root), layout,
                                                'Chosen' if layout == 'named' else '',
                                                'Owner' if layout in ('auto', 'org') else '')
                    self.assertTrue(set(str(call.args[0]) for call in listing.call_args_list) <= {str(root), str(group)})
                    self.assertEqual(snapshot, self.snapshot())

    def test_legacy_discovery_ambiguity_refuses_without_destination_fallback(self):
        for target in (self.home / 'IsaacLab', self.workspace / 'isaaclab'):
            (target / '.git').mkdir(parents=True)
        # Discovery and authoritative configured selection refuse for different
        # reasons: never restore global discovery for an explicit flat target.
        for function, reason in (('find_existing_repo', 'ambigu'),
                                 ('resolve_active_repo_dir', 'case-only collision')):
            result = self.resolve(function, WORKSPACE_LAYOUT='flat')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn(reason, result.stderr)

    def test_legacy_discovery_unique_case_and_space_parent_remains_read_only(self):
        target = self.workspace / 'Team Space/isaaclab'
        (target / '.git').mkdir(parents=True)
        (target / '.git/config').write_text('private fixture')
        snapshot = self.snapshot()
        self.assert_path(self.resolve('find_existing_repo'), target)
        self.assertEqual(snapshot, self.snapshot())

    def test_legacy_owner_ambiguity_refuses_instead_of_find_first(self):
        (self.workspace / 'Owner').mkdir(parents=True)
        (self.workspace / 'owner').mkdir()
        result = self.resolve(WORKSPACE_LAYOUT='auto', WORKSPACE_DEFAULT_OWNER='Owner')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('ambigu', result.stderr)

    def test_shell_delegates_to_shared_pure_api(self):
        # Isolated copy with a sentinel pure resolver proves the actual consumer
        # calls it rather than retaining a second shell owner algorithm.
        import shutil
        copied = self.root / 'core'
        shutil.copytree(CORE, copied)
        text = (copied / 'workspace_paths.py').read_text()
        text = text.replace('if __name__ == "__main__":',
                            'def resolve_paths(**kwargs):\n    raise ValueError("SHARED-RESOLVER-SENTINEL")\n\nif __name__ == "__main__":')
        (copied / 'workspace_paths.py').write_text(text)
        with patch.dict(globals(), {'CORE': copied}):
            result = self.resolve(WORKSPACE_LAYOUT='auto', WORKSPACE_DEFAULT_OWNER='Owner')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHARED-RESOLVER-SENTINEL', result.stderr)

    def test_legacy_layout_owner_resolution_remains_compatible(self):
        (self.workspace / "ExistingOwner").mkdir(parents=True)
        cases = [("auto", "", "fork/repo", "fork/IsaacLab"),
                 ("org", "Configured", "fork/repo", "Configured/IsaacLab"),
                 ("auto", "existingowner", "fork/repo", "ExistingOwner/IsaacLab"),
                 ("auto", "", "isaac-sim/IsaacLab", "IsaacLab"),
                 ("flat", "Configured", "fork/repo", "IsaacLab")]
        for layout, owner, slug, path in cases:
            with self.subTest(layout=layout, owner=owner, slug=slug):
                self.assert_path(self.resolve(slug=slug, WORKSPACE_LAYOUT=layout,
                                              WORKSPACE_DEFAULT_OWNER=owner), self.workspace / path)

    def test_inaccessible_directory_is_not_reported_as_missing_or_usable(self):
        self.workspace.mkdir(parents=True)
        self.workspace.chmod(0)
        try:
            result = self.resolve(WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("inaccessible", result.stderr.lower())
        finally:
            self.workspace.chmod(0o700)

    def test_disabled_desktop_registration_never_invokes_desktop_or_sudo(self):
        target = self.workspace / "Chosen/IsaacLab"
        (target / ".git").mkdir(parents=True)
        for key in ("CFG_WORKSPACE_AUTO_REGISTER_GITHUB_DESKTOP", "WORKSPACE_AUTO_REGISTER_GITHUB_DESKTOP"):
            with self.subTest(key=key):
                result = self.resolve("register_github_desktop_repo", repo=str(target),
                                      WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen",
                                      before='log_info() { :; }; github-desktop() { :; }; '
                                             'sudo() { touch "$HOME/desktop-attempt"; return 97; }',
                                      **{key: "false"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.home / "desktop-attempt").exists())

    def test_collision_inspection_has_a_bounded_entry_budget(self):
        self.workspace.mkdir(parents=True)
        for index in range(4097):
            (self.workspace / f"entry-{index}").touch()
        result = self.resolve(WORKSPACE_LAYOUT="named", WORKSPACE_NAME="Chosen")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("limit", result.stderr.lower())

    def test_cleared_legacy_owner_does_not_fall_back_to_profile_owner(self):
        self.assert_path(self.resolve(slug="isaac-sim/IsaacLab", WORKSPACE_LAYOUT="auto",
                                      WORKSPACE_DEFAULT_OWNER="", CFG_WORKSPACE_DEFAULT_OWNER="ProfileOwner"),
                         self.workspace / "IsaacLab")

    def test_default_documents_resolution_never_invokes_chown(self):
        self.workspace.mkdir(parents=True)
        result = self.resolve("resolve_default_workspace_dir", WORKSPACE_DIR="",
                              before='chown() { touch "$HOME/chown-attempt"; return 97; }')
        self.assert_path(result, self.workspace)
        self.assertFalse((self.home / "chown-attempt").exists())

    def test_root_resolution_does_not_create_missing_directories(self):
        self.assert_path(self.resolve("resolve_default_workspace_dir"), self.workspace)
        self.assertFalse(self.workspace.parent.exists(), "resolution created Documents")


if __name__ == "__main__":
    unittest.main()
