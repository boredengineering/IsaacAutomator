"""Offline, inert GitHub Actions generation; never contacts cloud/GitHub APIs."""
from dataclasses import dataclass
import copy
import json
import re
import hashlib
import difflib
from pathlib import Path
import textwrap
import shutil
import subprocess

import yaml

from src.python.terraform_backend import validate_terraform_version, _component as _backend_component

TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "github-actions"
# Public upstream refs/tags/v4.2.2 and refs/tags/v3.1.2 verified via
# git ls-remote https://github.com/{actions/checkout,hashicorp/setup-terraform}.git
CHECKOUT = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
TERRAFORM = "hashicorp/setup-terraform@b9cd54a3c349d3f38e8881555d616ced269862dd"
APPROVED_ACTIONS = frozenset({CHECKOUT, TERRAFORM,
    "aws-actions/configure-aws-credentials@b47578312673ae6fa5b5096b330d9fbac3d116df",
    "google-github-actions/auth@ba79af03959ebeac9769e648f473a284504d9193",
    "azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5"})


def _match(value, pattern, field):
    if not isinstance(value, str) or not re.fullmatch(pattern, value) or len(value) > 512:
        raise ValueError(f"invalid {field}")


def _path(value, field):
    _match(value, r"[A-Za-z0-9][A-Za-z0-9_./-]*", field)
    if any(part in ("", ".", "..") or part.startswith(".") for part in value.split("/")):
        raise ValueError(f"invalid {field}: unsafe path")


def _mapping(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError("unknown or missing workflow configuration fields")


def _validate(data):
    required = {"schema_version", "repository", "protected_branch", "source_revision", "provider", "identity", "config_path", "deployments", "backend_identity", "namespace", "scopes", "runtime_image", "terraform_version"}
    _mapping(data, required | {"schedule", "correction_mode", "notifications", "runner_labels", "timeout_minutes", "max_parallel"}, required)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported workflow schema_version")
    _match(data["repository"], r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_-]*", "repository")
    _path(data["protected_branch"], "protected_branch")
    if ".." in data["protected_branch"] or data["protected_branch"].startswith("refs/") or data["protected_branch"].endswith((".lock", ".")):
        raise ValueError("ambiguous protected_branch")
    _match(data["source_revision"], r"[0-9a-f]{40}", "source_revision")
    _path(data["config_path"], "config_path")
    _path(data["backend_identity"], "backend_identity")
    # Reuse BackendSpec's exact namespace policy, including reserved names.
    _backend_component(data["namespace"], "namespace")
    _match(data["runtime_image"], r"[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}", "runtime_image")

    for field in ("deployments", "scopes"):
        values = data[field]
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError(f"invalid {field}")
        for value in values:
            _match(value, r"[A-Za-z0-9][A-Za-z0-9_-]*", field)
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate {field}")
    if set(data["scopes"]) - {"workstation_infrastructure", "controller_identity", "backend_infrastructure", "runtime"}:
        raise ValueError("unsupported detection scope")
    patterns = {
        "aws": {"role_arn": r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_/-]+", "region": r"[a-z]{2}(?:-[a-z]+)+-[0-9]"},
        "gcp": {"workload_identity_provider": r"projects/[0-9]+/locations/global/workloadIdentityPools/[a-z0-9-]+/providers/[a-z0-9-]+", "service_account": r"[a-z0-9-]+@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com"},
        "azure": {key: r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" for key in ("client_id", "tenant_id", "subscription_id")},
    }
    if not isinstance(data["provider"], str) or data["provider"] not in patterns:
        raise ValueError("unsupported provider")
    # Scheduled cloud detection shares the runner's stable remote-backend gate;
    # no synthetic storage descriptor, credentials, or duplicated version policy.
    validate_terraform_version(data["terraform_version"],
        {"aws": "s3", "gcp": "gcs", "azure": "azurerm"}[data["provider"]])
    fields = patterns[data["provider"]]
    _mapping(data["identity"], fields, fields)
    for key, pattern in fields.items():
        _match(data["identity"][key], pattern, key)
    data.setdefault("schedule", {})
    _mapping(data["schedule"], {"enabled", "cron_utc"})
    data["schedule"].setdefault("enabled", False)
    data["schedule"].setdefault("cron_utc", "17 */6 * * *")
    if type(data["schedule"]["enabled"]) is not bool:
        raise ValueError("schedule.enabled must be boolean")
    # Deliberately small UTC cron grammar: one minute, each N hours, every day.
    _match(data["schedule"]["cron_utc"], r"(?:[0-9]|[1-5][0-9]) (?:\*|\*/(?:[1-9]|1[0-9]|2[0-3])|[0-9]|1[0-9]|2[0-3]) \* \* \*", "cron_utc")
    data.setdefault("correction_mode", "report_only")
    if data["correction_mode"] != "report_only":
        raise ValueError("remediation generation unavailable: no protected-environment verification receipt/trust-anchor integration; use report_only")
    data.setdefault("notifications", "job_summary")
    if data["notifications"] != "job_summary":
        raise ValueError("only job_summary notifications supported; no issue/external writes")
    data.setdefault("runner_labels", ["ubuntu-24.04"])
    if data["runner_labels"] not in (["ubuntu-latest"], ["ubuntu-24.04"], ["ubuntu-22.04"]):
        raise ValueError("only ephemeral GitHub-hosted Ubuntu runners supported")
    for field, default, maximum in (("timeout_minutes", 30, 360), ("max_parallel", 1, 32)):
        data.setdefault(field, default)
        if type(data[field]) is not int or not 1 <= data[field] <= maximum:
            raise ValueError(f"invalid {field}")
    return data


@dataclass(frozen=True)
class WorkflowConfig:
    """Separate workflow schema; drift_config owns detector configuration."""
    canonical: str

    @classmethod
    def from_dict(cls, value):
        data = _validate(copy.deepcopy(value))
        return cls(json.dumps(data, sort_keys=True, separators=(",", ":")))

    def to_dict(self):
        return json.loads(self.canonical)


def _template(name, values):
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@@" + key + "@@", value)
    if "@@" in text:
        raise ValueError("unresolved template token")
    return text


def render(config):
    """Return filename->UTF-8 text, with no writes or external verification.

    Remediation intentionally unavailable: no authenticated protected-environment
    receipt verifier/trust anchor is integrated. Caller-editable flags never help.
    """
    config = WorkflowConfig.from_dict(config.to_dict())
    data = config.to_dict()
    digest = hashlib.sha256(config.canonical.encode()).hexdigest()
    provider = data["provider"]
    auth = yaml.safe_load(_template(f"drift-{provider}.yml.tmpl", {
        key.upper(): json.dumps(value) for key, value in data["identity"].items()}))
    group = hashlib.sha256((provider + ":" + data["backend_identity"] + ":" + data["namespace"]).encode()).hexdigest()[:24]
    script = '''set -euo pipefail
umask 077
private_dir=$(mktemp -d "${RUNNER_TEMP}/isaac-drift.XXXXXXXX")
trap 'rm -rf -- "$private_dir"' EXIT
status=0
for scope in $DRIFT_SCOPES; do
  set +e
  ./drift check "$DRIFT_DEPLOYMENT" --config "$DRIFT_CONFIG" --scope "$scope" --format json --report-dir "$private_dir/reports" >"$private_dir/report.json" 2>"$private_dir/error.log" </dev/null
  code=$?
  wrapper_code=$code
  set -e
  if [ "$code" -eq 0 ]; then
    if ! python3 -c 'import json,sys; report=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(report,dict) and report.get("classes")==["clean_within_coverage"] else 1)' "$private_dir/report.json" > /dev/null 2>&1; then
      code=1
    fi
  fi
  case "$code" in
    0) label=clean ;;
    2) label=drift; if [ "$status" -eq 0 ]; then status=2; fi ;;
    3) label=incomplete; if [ "$status" -ne 1 ]; then status=3; fi ;;
    *) label=error; status=1 ;;
  esac
  printf 'Drift check: %s (wrapper exit %s)\\n' "$label" "$wrapper_code" >> "$GITHUB_STEP_SUMMARY"
done
exit "$status"
'''
    job = {
        "if": "${{ github.repository == '" + data["repository"] + "' && github.ref == 'refs/heads/" + data["protected_branch"] + "' }}",
        "runs-on": data["runner_labels"], "container": {"image": data["runtime_image"]},
        "timeout-minutes": data["timeout_minutes"],
        "permissions": {"contents": "read", "id-token": "write"},
        "strategy": {"fail-fast": False, "max-parallel": data["max_parallel"], "matrix": {"deployment": data["deployments"]}},
        "concurrency": {"group": "isaac-drift-" + group + "-${{ matrix.deployment }}", "cancel-in-progress": False},
        "defaults": {"run": {"shell": "bash"}},
        "env": {"TF_IN_AUTOMATION": "true", "TF_INPUT": "false", "DRIFT_CONFIG": data["config_path"], "DRIFT_DEPLOYMENT": "${{ matrix.deployment }}", "DRIFT_SCOPES": " ".join(data["scopes"])},
        "steps": [
            {"name": "Pinned protected source", "uses": CHECKOUT, "with": {"repository": data["repository"], "ref": data["source_revision"], "persist-credentials": False}},
            {"name": "Pinned Terraform", "uses": TERRAFORM, "with": {"terraform_version": data["terraform_version"], "terraform_wrapper": False}},
            auth,
            {"name": "Report-only detection (private ephemeral reports)", "run": script},
        ],
    }
    if provider == "azure":
        job["env"].update({"ARM_USE_OIDC": "true", "ARM_USE_AZUREAD": "true",
                          **{"ARM_" + key.upper(): value for key, value in data["identity"].items()}})
    triggers: dict = {"workflow_dispatch": {}}
    if data["schedule"]["enabled"]:
        triggers["schedule"] = [{"cron": data["schedule"]["cron_utc"]}]
    text = _template("drift-check.yml.tmpl", {"DIGEST": digest,
        "TRIGGERS": json.dumps(triggers),
        "JOBS": textwrap.indent(yaml.safe_dump({"detect": job}, sort_keys=False, width=1000), "  ")})
    checklist = f'''# Drift workflow setup — UNVERIFIED

Generator/schema: 1; configuration SHA-256: {digest}
Repository: `{data['repository']}`; protected branch: `{data['protected_branch']}`.
Pinned source: `{data['source_revision']}`. Runtime image: `{data['runtime_image']}`.
Provider identity (nonsecret): `{json.dumps(data['identity'], sort_keys=True)}`.

- [ ] Verify repository identity, protected branch/default branch and CODEOWNERS/review protections for workflows, config, modules, inputs and provider lockfiles.
- [ ] Review the pinned source and image. Image must contain Python 3.10+, Automator dependencies, Bash, Git, Node-compatible glibc, provider SDK/CLI (including az for Azure), and runnable ./drift; do not use interactive login or nested workstation Docker wrappers.
- [ ] Supply the detector config at `{data['config_path']}` in the pinned source. Explicit report_only policy and the same deployment allowlist, baseline, state/input/provider-lockfile references must be enforced there; this workflow config is a separate schema.
- [ ] Verify read-only detector role scope for `{data['backend_identity']}` / `{data['namespace']}`, state lock access, and inability to assume any correction/admin identity.
- [ ] OIDC issuer https://token.actions.githubusercontent.com; exact subject `repo:{data['repository']}:ref:refs/heads/{data['protected_branch']}`. Restrict provider trust to repository/ref and workflow context, not just repository. Verify audience and claim mapping (AWS sts.amazonaws.com; GCP full workload-identity-provider audience; Azure api://AzureADTokenExchange).
- [ ] Verify private endpoint reachability without opening storage publicly. Self-hosted runners and secret-value authentication are unsupported.
- [ ] Reports/stdout/stderr are private 0700 temporary storage, deleted on exit; no state/plans/report values are uploaded or printed. This subset retains only a classified job summary, NOT durable report/history storage. Provision a separately reviewed private report/heartbeat store before relying on history.
- [ ] Backend locking remains mandatory. Concurrency only coordinates this repository and does not replace cross-controller locks; shared bootstrap stacks need a common independent owner/group.
- [ ] Schedules are disabled by default. Schedules run on the default branch, may be delayed/dropped/disabled after inactivity. Configure an independent watchdog for missed checks and last-success/coverage; a workflow cannot report that it never ran.
- [ ] Remediation is UNAVAILABLE: a real protected-environment verification receipt plus independent approval trust anchor is required, including plan/visibility support, prevent-self-review, non-bypass protections, identity separation, expiry and bound saved-plan verification. Environment names or caller JSON flags are not evidence.
- [ ] Preview explicit install destination/diff, review generated files, and separately authorize setup/activation. Generator performs no GitHub/cloud reads/writes, IAM/secrets/settings changes, commits or pushes.
'''
    return {"drift-check.yml": text, "SETUP.md": checklist}


DEFAULT_OUTPUT = Path(".generated/isaacautomator/workflows")


def _safe_directory(directory):
    directory = Path(directory).absolute()
    if ".." in directory.parts or any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("unsafe output path: traversal or symbolic link")
    if directory.exists() and not directory.is_dir():
        raise ValueError("output directory is not a directory")
    return directory


def _preflight(directory, files):
    for name, text in files.items():
        path = directory / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != text.encode())):
            raise ValueError(f"workflow conflict: {path}; choose a fresh directory and review diff")


def _write_files(directory, files):
    validate_rendered(files)
    _preflight(directory, files)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, text in files.items():
        path = directory / name
        if not path.exists():
            # Exclusive creation never overwrites a concurrently-created file/link.
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    return [directory / name for name in sorted(files)]


def generate(config, output_dir=DEFAULT_OUTPUT):
    """Write only inert files; identical regeneration is a no-op.

    Changed files (even previously generated ones) require a fresh output directory
    and explicit diff review. There is deliberately no overwrite/force option.
    """
    directory = _safe_directory(output_dir)
    if any(part.lower() == ".github" for part in directory.parts):
        raise ValueError("generation cannot target .github; use explicit install")
    return _write_files(directory, render(config))


def install_preview(config, repository_dir):
    """Show destination and unified diff without creating .github or reading Git.

    Confirmation binds exact bytes and destination; this is installation consent,
    NOT proof of repository protection, cloud trust, or remediation approval.
    """
    root = _safe_directory(repository_dir)
    if root == TEMPLATES.parents[1] or not (root / ".git").exists():
        raise ValueError("install requires an explicit external repository, never this source checkout")
    directory = _safe_directory(root / ".github" / "workflows")
    files = {k: v for k, v in render(config).items() if k.endswith(".yml")}
    validate_rendered(files)
    _preflight(directory, files)
    diff = "".join("".join(difflib.unified_diff(
        (directory / name).read_text().splitlines(True) if (directory / name).exists() else [],
        text.splitlines(True), fromfile=str(directory / name), tofile=str(directory / name)))
        for name, text in sorted(files.items()))
    binding = json.dumps({"destination": str(directory), "files": files, "diff": diff}, sort_keys=True)
    return {"destination": str(directory), "diff": diff,
            "confirmation": hashlib.sha256(binding.encode()).hexdigest(),
            "setup_status": "UNVERIFIED", "remote_activation": "not_performed"}


def install(config, repository_dir, *, confirmation=None):
    """Install local reviewed files only; never commits/pushes/enables Actions."""
    preview = install_preview(config, repository_dir)
    if not isinstance(confirmation, str) or confirmation != preview["confirmation"]:
        raise ValueError("explicit current destination-bound preview confirmation required")
    files = {k: v for k, v in render(config).items() if k.endswith(".yml")}
    return _write_files(Path(preview["destination"]), files)


def validate_rendered(files):
    """Check YAML semantics and existing actionlint, never install tools.

    This validator is defense in depth for generated output, not a sandbox for
    arbitrary third-party workflows. Only render() output should be installed.
    """
    executable = shutil.which("actionlint")
    for name, text in files.items():
        if not name.endswith(".yml"):
            continue
        try:
            document = yaml.safe_load(text)
            if (not isinstance(document, dict) or "on" not in document or True in document
                    or set(document["on"]) - {"workflow_dispatch", "schedule"}
                    or document["permissions"] != {"contents": "read"}):
                raise ValueError("invalid GitHub trigger/permission semantics")
            for job in document["jobs"].values():
                if job["permissions"] != {"contents": "read", "id-token": "write"} or job["concurrency"]["cancel-in-progress"] is not False:
                    raise ValueError("invalid detection permissions/concurrency")
                for step in job["steps"]:
                    if "uses" in step and step["uses"] not in APPROVED_ACTIONS:
                        raise ValueError("action revision is not approved")
        except (yaml.YAMLError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid generated workflow YAML") from exc
        if executable:
            try:
                result = subprocess.run([executable, "-no-color", "-"], input=text,
                    capture_output=True, text=True, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ValueError("actionlint failed to execute") from exc
            if result.returncode:
                raise ValueError("actionlint rejected generated workflow: " + result.stdout + result.stderr)
    return {"yaml": "valid", "actionlint": "valid" if executable else "unavailable (not installed)"}


def preview(config):
    """No writes/network; existing actionlint may be executed read-only."""
    files = render(config)
    return {"files": files, "validation": validate_rendered(files),
            "default_output": str(DEFAULT_OUTPUT), "setup_status": "UNVERIFIED"}


def verify_setup(config):
    """Offline checklist, not remote proof. No authorization bypass parameter.

    Authenticated GitHub/cloud read adapters and approval receipt verification
    are not implemented. A CLI should return nonzero for this unverified result.
    """
    files = render(config)
    return {"status": "UNVERIFIED", "verified": False, "remediation_available": False,
            "checks": {key: "UNVERIFIED" for key in (
                "repository_identity", "protected_source_policy", "environment_required_reviewers",
                "oidc_subject_audience", "runtime_versions", "private_network_reachability",
                "report_storage_permissions", "independent_watchdog")},
            "checklist": files["SETUP.md"], "validation": validate_rendered(files)}
