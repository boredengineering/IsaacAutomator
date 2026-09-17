# Targeted host collection — offline verification

## Scope and diagnosis

This follow-up addresses the first real host report's coverage gaps without
installing anything or opening host access from the devcontainer.

- Both BoredEngineer and the legacy alias were observed. The old collector
  required one selected workspace before collecting any repositories. It now
  observes each candidate under the same limits, leaving ambiguous intent unset.
- The real report hit the shared entry limit while parsing dpkg, before examining
  environments. An explicit `--scope software` skips machine/APT/dpkg reads and
  records `system-scope-not-collected`, including on early watchdog timeout.
- Fixed `.git` metadata probing precedes repository payload enumeration, avoiding
  budget exhaustion on irrelevant payload filenames in recognized checkouts.
- The repository wrapper accepts a constrained `--report-name` basename. New
  follow-up reports are private and exclusive; the original need not be moved.

No private inventory contents are copied into these verification artifacts.
Fixtures, package/version values and reviewed YAML here are synthetic, not the
user's desired profile. No host collection, installation, sync or cloud operation
was performed in this follow-up.

## Fresh execution

| Scope | Tests | Passed | Skipped | Failures/errors |
|---|---:|---:|---:|---:|
| Collector/importer | 59 | 59 | 0 | 0 |
| 19 selected existing core suites | 267 | 265 | 2 | 0 |
| Total, disjoint suites | 326 | 324 | 2 | 0 |

Raw `results.json` and logs are retained in `host/` and `core/`. Their paths refer
to original execution directories. The two skips are existing root-only tests;
the retained harness deliberately runs unprivileged with filesystem/network
confinement. Two established managed-dependent methods remain excluded. These
are scoped regression results, not a full-repository or live-install certification.

`demo/` retains the actual ten-command collector/import/review/reimport/YAML/
both-renderers/dry-run chain. All 15 synthetic input files and source-tree entries
were preserved. Dry-run deliberately returns the expected incomplete-evidence
status, never installation authorization. The late software-only timeout-marker
change does not affect this default-all demo or the existing core suites.

Reproduce from the repository root:

```sh
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step2/run_bounded_tests.py
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step1/isaac-step1-runner.py
/usr/bin/python3 -B .agents/references/isaac-installer/verification/step2/demo_host_workflow.py
```

## Regression evidence

Before each implementation slice, the confined collector suite failed for the
expected missing behavior (then passed after the implementation):

- Ambiguous workspace observations: `/tmp/isaac-step1-a4bbtkh4` RED,
  `/tmp/isaac-step1-g2p3x9ic` GREEN.
- Software-only CLI / environment budget: `/tmp/isaac-step1-87btzmkg` RED,
  `/tmp/isaac-step1-mp4qrxz7` GREEN.
- Repository payload enumeration: `/tmp/isaac-step1-2tgw7rmh` RED,
  `/tmp/isaac-step1-icpkz2t0` GREEN. The first exploratory assertion at
  `/tmp/isaac-step1-yry8uha3` was tightened from IndexError to an explicit count.
- Wrapper scoped follow-up / preserved original: `/tmp/isaac-step1-h9t_ezmx` RED,
  `/tmp/isaac-step1-zy78tqd9` GREEN.
- Omission marker on early timeout: `/tmp/isaac-step1-n4ppxfqw` RED,
  final `/tmp/isaac-step1-kmd9fs9w` GREEN.

The new real CLI import regression verifies competing source revisions remain
alternatives, workspace intent stays unknown, environment proposals survive,
all decisions remain unapproved, and the input report stays unchanged.

Python AST syntax and `git diff --check` passed. The new report destination is
Git-ignored. Independent source review PASS is retained in `review.json`; the
parent verified all five recorded hashes against the current source/test/guide
files, including the late timeout-marker fix. Review was source-only, not an
independent test rerun. The original private inventory also passed pure schema
validation without writes.

## Remaining gaps and next host interaction

Use the ordinary-user host commands documented in
`isaac-installer/docs/host-discovery.md`: plan then explicit software collection
into `host-software-02.json`, preserving the original inventory. No automatic
budget increase or retry is made; investigate remaining limits after this batch.

IsaacSim VERSION parsing remains unresolved: rejected raw text is deliberately
absent from the existing report. Do not infer the file's format or the installed
version from the configured target stack. Driver syntax, symlinked CUDA metadata,
unsupported package formats/manual flags, editable/UV metadata and live GPU
compatibility remain unknown or unsupported as reported.

Software follow-ups are separate snapshots. `--previous-report` carries review
continuity, not an automatic union with older machine/package observations.
Retain both reports, compare scope, and review desired intent separately. No
real desired YAML profile is claimed from the incomplete initial inventory.
