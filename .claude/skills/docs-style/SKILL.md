---
name: docs-style
description: Write and review agents-farm documentation, UI text, comments and issue text in plain English (B1 level). Use when you add or change a README, docs, error message, help text or issue, or when you translate text.
---

# Plain English (B1) for this repo

All text in the repository is English: docs, code comments, UI strings, demo data, commit messages and GitHub issues. A test fails if Cyrillic text appears in the repo files.

## Rules

1. **Short sentences.** About 15 words or fewer. One idea per sentence.
2. **Common words.** Use `use`, not `utilise`; `start`, not `initiate`; `show`, not `display` when both work.
3. **Active voice.** "The hook writes one line", not "One line is written by the hook".
4. **Say what to do.** Start steps with a verb: "Run", "Add", "Check".
5. **No idioms or jokes.** Many readers are not native speakers.
6. **Name things the same way every time.** Pick one word (`session`, `agent`, `hook`) and keep it.
7. **Explain a hard word once** the first time it appears, if it is not a common developer term.
8. **Tables for facts, sentences for reasons.** Keep tables short.
9. **Tell the truth about limits.** Mark estimates as estimates (`≈`). Say what is not done or not checked.
10. **Keep code, commands and file names exact.** Put them in backticks. Do not translate them.

## Style for specific places

- **UI text and errors:** say what happened and what to do next. Example: `cannot start pager: less not found. Set $PAGER.`
- **Commit messages:** first line in the imperative, up to about 70 characters (`Fix context window calculation`). Add a short body that says why.
- **Issues:** a short goal, a plan, and a "Done when" checklist.
- **Comments in code:** explain why, not what.

## Check before you finish

- Read the text aloud. If a sentence is hard to say, split it.
- Run the `check` skill. It finds non-English text and personal data.
- When you translate, keep the meaning and the numbers. Do not add new claims.
