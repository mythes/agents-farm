---
name: sync-backlog
description: Keep docs/backlog.md and the GitHub issues and milestones in sync (create, update, close, label). Use when a task is finished, a new task appears, or the plan changes.
disable-model-invocation: true
---

# Sync the backlog with GitHub

`docs/backlog.md` has the research and the details. The GitHub issues have the short version and the status. They must say the same thing.

Requirements: `gh` is installed and logged in (`gh auth status`).

## Conventions

- IDs: `S1…` are spikes (questions to answer), `T0…` are tasks. The issue title starts with the ID: `T2 · Kill hotkey with confirmation`.
- Milestones: `M0 — Spikes`, `M1 — Registry, PID, fuzzy, kill`, `M2 — Start and resume`, `M3 — Limits and percentages`.
- Labels: `spike`, `feature`, `limits`, `safety`, `ui`.
- Language: **English, plain (B1)**. See the `docs-style` skill.
- Each issue body ends with a link to `docs/backlog.md` and has a "Done when" checklist.

## Steps

1. Read the current state:

   ```bash
   gh issue list --state all --limit 100 --json number,title,state,milestone,labels
   ```

   Read `docs/backlog.md` too.
2. Compare them. List the differences for the user: missing issues, wrong state, a changed scope, a changed milestone.
3. **Ask the user to confirm the list.** Creating, closing and editing issues is visible to others.
4. Apply the changes:
   - new task → add it to `docs/backlog.md` first, then `gh issue create --title … --body … --milestone … --label …`
   - done task → tick its checklist, `gh issue close <n> --comment "Done in <commit or PR>"`, and mark it done in `docs/backlog.md`
   - changed scope → edit both with `gh issue edit <n> --body …`
5. A spike's answer goes into the **"What the research showed"** section of `docs/backlog.md` and into the issue before you close it. Update the tasks that depended on it.
6. Run the `check` skill, then commit the backlog change.

## Rules

- Never delete an issue. Close it with a short reason.
- Do not put personal data, tokens or private paths into an issue.
