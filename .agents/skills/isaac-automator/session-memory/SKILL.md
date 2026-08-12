---
name: session-memory
description: Manage, search, resume, and log session memory checkpoints in .agents/memory/ using 25-character timestamped UUID files.
---

# Session Memory Management <!-- omit in toc -->

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [1. Resuming Past Work](#1-resuming-past-work)
- [2. Creating a Session Checkpoint](#2-creating-a-session-checkpoint)
- [3. Updating the Master Catalog](#3-updating-the-master-catalog)

## Overview

This skill defines how Antigravity manages session memory within the repository. Because LLM sessions start fresh, all session history, architectural decisions, and technical gotchas are recorded as structured 25-character markdown logs under `.agents/memory/sessions/` and indexed in `.agents/memory/INDEX.md`.

## Directory Structure

```text
.agents/memory/
├── INDEX.md                                # Master catalog of past session checkpoints
└── sessions/
    └── YYYYMMDD_HHMMSS_<short_uuid>.md    # 25-character session log (e.g. 20260812_224648_0d1a2b3c.md)
```

## 1. Resuming Past Work

When the user asks to "resume previous work", "check past session notes", or asks a question about prior work:
1. Open `.agents/memory/INDEX.md` using `view_file`.
2. Locate the relevant session log file link in the table.
3. Open the specific `sessions/YYYYMMDD_HHMMSS_<short_uuid>.md` file to retrieve full details.

## 2. Creating a Session Checkpoint

When a major milestone is completed, important architectural decisions are made, or the user requests a checkpoint ("save session", "checkpoint"):

1. Generate a 25-character filename:
   Format: `YYYYMMDD_HHMMSS_<short_uuid>.md`
   Example: `20260812_224648_0d1a2b3c.md`

2. Populate the log at `.agents/memory/sessions/YYYYMMDD_HHMMSS_<short_uuid>.md` with frontmatter and structured sections:

```markdown
---
uuid: "<full-uuid>"
short_uuid: "<8-char-uuid>"
timestamp: "YYYY-MM-DDTHH:MM:SSZ"
topic: "<Topic Title>"
tags: ["tag1", "tag2"]
---

# Session Memory: <Topic Title>

## Summary
Brief summary of what was completed in this session.

## Decisions & Rationale
- Key decisions made...

## Discovered Gotchas & Caveats
- Important fixes, errors, or technical nuances...

## Completed Tasks
- [x] Task 1
- [x] Task 2

## Next Steps / Pending Items
- [ ] Task to tackle in future session
```

## 3. Updating the Master Catalog

After writing a new session log, append a row to the table in `.agents/memory/INDEX.md`:

```markdown
| Date | UUID | Topic | Summary | File |
| :--- | :--- | :--- | :--- | :--- |
| YYYY-MM-DD HH:MM | `<short_uuid>` | `<Topic Title>` | `<1-line summary>` | [`YYYYMMDD_HHMMSS_<short_uuid>.md`](./sessions/YYYYMMDD_HHMMSS_<short_uuid>.md) |
```
