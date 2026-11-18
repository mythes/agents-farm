# agents-farm: notes for coding agents

A Textual terminal dashboard that watches Claude Code sessions: status, context, limits. It only **reads** local files (`~/.claude/projects`, `~/.agents-farm/events.jsonl`) and never changes Claude Code data.

## Commands

```bash
.venv/bin/pip install -e '.[dev]'   # set up
.venv/bin/agents-farm --demo        # try the UI with fake data
scripts/check.sh                    # tests + bandit + whitespace (run before every commit)
scripts/install.sh --dry-run        # show what the installer would do (adds the commands agents-farm and af)
scripts/make_demo.sh                # rebuild docs/demo.cast and docs/demo.gif
```

## Code map

| File | Job |
|---|---|
| `transcripts.py` | incremental parser for JSONL transcripts (`tail.py` reads files in chunks) |
| `registry.py` | running processes from `~/.claude/sessions` (validated, PID reuse guard) |
| `search.py` | fuzzy search and `key:value` filters (`textual.fuzzy`) |
| `events.py` | hook handler (`agents-farm hook`) and reader for `events.jsonl` |
| `store.py` | builds a `Snapshot`, works out each agent status |
| `limits.py` | token usage per model in the 5-hour window (an estimate) |
| `render.py` | Rich rendering, no Textual imports |
| `app.py` | Textual UI |
| `demo.py` | fake data for `--demo` and the recording |
| `scripts/install.sh` | installer with a collision guard (tests: `tests/test_installer.py`, use `--dry-run`) |

## Rules you must follow

1. **Text from transcripts, hooks and process files is untrusted** (prompt injection). Pass it through `sanitize()` when you read it. Never turn on markup for it: use `notify(..., markup=False)`, `rich.markup.escape` for titles, and `rich.Text` for cells. See `SECURITY.md`.
2. **Never run a real `claude` or touch real sessions in tests.** Use temporary folders and the variables `CLAUDE_PROJECTS_DIR`, `AGENTS_FARM_HOME`.
3. **Dangerous actions need confirmation** (kill, start, resume, editing `settings.json`). Pass arguments to processes as lists, never through a shell. Validate PIDs against `startedAt` before you send a signal.
4. **Keep the repo small.** Rebuild the GIF only when the UI changes in a visible way. No video files. Size budgets are tested.
5. **English only, plain style (B1)** in docs, comments, UI text, demo data, commits and issues. See `.claude/skills/docs-style`.
6. **No personal data.** Use placeholders (`/Users/you`). Commits use the GitHub noreply email set in the local git config. Do not change the identity.
7. **Do not guess about Claude Code internals.** Files like `~/.claude/sessions/*.json` are not documented. Validate every field and fail softly.
8. **Escapes can turn into real characters.** If you write `\u202e` or similar in a file, check that the file does not contain the literal character (bidi and Cyrillic characters break `test_repo_hygiene.py` and are unsafe in source). Build such values with `chr()`.
9. **Pin every GitHub Action to a full commit SHA** (with the tag in a comment). Keep workflow `permissions` as small as possible. A test checks the pins.
10. **The installer must never overwrite a file or command it did not create.** Keep the collision checks and the `--dry-run` tests when you change `scripts/install.sh`. Do not add `af` as a pip entry point: the short name is only a local link, so the package does not claim it for everyone.
11. Python 3.9 compatible (CI runs 3.9 and 3.12). Use `from __future__ import annotations`.
12. Ask before you push, tag, publish, change repo visibility, or edit the user's `~/.claude/settings.json`.

## Skills in `.claude/skills/`

| Skill | Use it when |
|---|---|
| `check` | before every commit or PR |
| `update-demo` | the UI changed and the README demo is out of date |
| `docs-style` | you write or translate any text |
| `sync-backlog` | a task is done or added (keeps `docs/backlog.md` and GitHub issues in sync) |
| `release` | the user asks for a release (manual only) |

## Where to find plans

`docs/backlog.md` (research, tasks, order) and the GitHub issues. Design ideas: `docs/tui-design.md`.
