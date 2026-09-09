# Optional Hugging Face artifacts

Input: `huggingface_json`, a mapping or serialized JSON; omitted/disabled is a
no-op. See `.agents/references/docs/optional-distribution-guide.md` for profile
examples and the image-versus-model distinction.

Enabled settings require `repositories` entries with unique `name`, `repo_id`,
`repo_type` (`model` default or `dataset`) and a full lowercase 40-character
commit `revision`. Optional `token_file` is an existing absolute path on the
target, not a credential value or controller path. Only conservative ASCII path
characters (letters, digits, underscore, dot, slash, hyphen) are accepted; no
traversal or Ansible template expressions.

The role resolves the non-root SSH account through getent. It installs
`python3-venv` and `python3-packaging` with apt only when enabled. The Ansible pip
task explicitly uses `/usr/bin/python3` so its system `packaging` prerequisite
matches the module interpreter; venv support alone does not supply that import.
It then creates a per-user venv and installs `huggingface-hub==0.34.4`.
All user filesystem changes and downloads run under that
SSH account. A root SSH account is intentionally unsupported. Trusted OS/PyPI
package downloads are provisioning prerequisites; no Hub code is executed.

Snapshots live at:

`<SSH_HOME>/.cache/isaac-automator/huggingface/<name>/<models|datasets>--<namespace>--<repo>/snapshots/<commit>`

Each commit gets an immutable snapshot directory rather than overlaying an old
checkout. The runner compares file metadata to report idempotence and refuses
symlinked managed cache paths. It does not garbage-collect old commits.

The token is read on the target under the effective SSH UID and never passed in
argv or saved by `login()`. Missing token_file means anonymous access (`token=False`)
with implicit Hub authentication disabled. Download output is hidden by Ansible
`no_log`; errors never include caught SDK details. Private/gated repositories
still require appropriate permissions and accepted terms.

This role stages data only. Container bind mounts, GR00T model selection,
dataset consumers, checkpoint health and GPU execution remain separate. Enabling
this block can transfer large repositories and consume disk/egress; review size
and licensing first.

Offline tests: `python3 src/tests/huggingface_artifacts.test.py`. They exercise
normalization, direct disabled/invalid Ansible runs and the real runner against a
fake local Hub module, not real repository downloads. Live authenticated downloads
have not been validated during implementation.
