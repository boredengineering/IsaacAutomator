# Git Workflow & Commit Rules

## Explicit Permission Required for Git Commits and Pushes

1. **No Autonomous Commits:**
   - The agent MUST NEVER execute `git commit` (including `git commit -m`, `git commit -a`, `git commit --amend`, or any command creating or modifying commits) on behalf of the user.
   - The agent MUST ALWAYS ask for explicit user permission and confirmation before staging (`git add`) or committing (`git commit`).
   - When code or documentation modifications are complete, the agent must present the summary of changes and ask the user whether they would like the changes committed. The agent must wait for explicit user consent before touching git commits.

2. **No Autonomous Pushes:**
   - The agent MUST NEVER execute `git push` (or `git push --force`) to remote repositories unless the user explicitly requests or commands it in their prompt.

3. **Working Tree Changes:**
   - The agent creates, edits, and tests files directly in the working tree.
   - Leaving changes uncommitted for user review is the expected default state.
