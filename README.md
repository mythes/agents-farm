# agents-farm

A terminal dashboard for your [Claude Code](https://claude.com/claude-code) agents.
See which agents are working, what they do, how full their context is, and how much of your limits you have used.

![agents-farm demo](docs/demo.gif)

> Try it without any real sessions: `agents-farm --demo`

## Features

- **Live agent list.** Every session has a status symbol and a colour. Agents that wait for you (`?`) or have an error (`!`) are always on top. Subagents show under their parent (`└`).
- **Details you can open.** Context (prompt, files, tokens), Activity (every step with time) and Plan (from TodoWrite or `update_plan`). Press `enter` for a full-screen view.
- **Limits and context bars.** Usage per model in the current window, with warning colours and a reset timer.
- **Alerts.** A notification and a bell when an agent starts to wait for you, fails, or a limit goes above 90%.
- **Search and filter.** Type text, or use `status:waiting`, `model:opus`, `project:api`.
- **Terminal friendly.** Works on narrow screens, and has a one-line mode for tmux and status lines.

## Install

You need Python 3.9 or newer and Claude Code. It works on macOS and Linux.

```bash
git clone https://github.com/mythes/agents-farm.git
cd agents-farm
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Use

```bash
.venv/bin/agents-farm             # your real sessions from ~/.claude/projects
.venv/bin/agents-farm --demo      # fake data, good for a first look
.venv/bin/agents-farm --since 24  # show sessions from the last 24 hours (default: 12)
```

One-line status (for tmux or a status line) and JSON (for scripts):

```bash
.venv/bin/agents-farm status          # ?1 ●2 │ sonnet 25% │ opus 7%
.venv/bin/agents-farm status --json
```

## Keys

| Key | Action |
|---|---|
| `↑` `↓` / `j` `k` | Move between agents |
| `enter` / `z` | Zoom: details on the full screen. `esc` goes back |
| `1` `2` `3` | Open or close Context / Activity / Plan |
| `e` | Open or close all sections |
| `/` | Filter: text, `status:waiting`, `model:opus`, `project:api` |
| `h` | Show or hide idle sessions and finished subagents |
| `y` | Copy `cd … && claude --resume <id>` (works over SSH too) |
| `o` | Open the full log in `$PAGER` |
| `?` | Help |
| `q` | Quit |

## Where the data comes from

1. **Transcripts** in `~/.claude/projects/**/*.jsonl`. They are read step by step (only new lines). They give the prompt, the steps, files, plan, tokens, model and context size.
2. **Hooks** (recommended). Without hooks, "waiting for permission" can only be guessed, and the agent shows as `⏸ stalled`. With hooks the status is exact (`? waiting`).

### Install the hooks

Print the block for your `~/.claude/settings.json`:

```bash
.venv/bin/agents-farm hooks-snippet
```

Add the content of `"hooks"` to your settings. If you already have hooks for the same events, put the new entries next to the old ones. The hook writes one line to `~/.agents-farm/events.jsonl` (about 140 ms per call). It never fails and always exits with code 0. When it works, the top bar shows `hooks ✓`.

## Limits: please read

Claude Code does not save your remaining plan quota on disk. For now the limit bars are an **estimate**: the sum of tokens (input + output + cache write) per model in the current 5-hour window, compared with a budget from the config.

The default budgets are **placeholders**. Set numbers that match your plan in `~/.agents-farm/config.json`. A value of `0` means "unknown": only tokens are shown.

Real plans use one 5-hour window and one weekly window, not a budget per model. Official numbers (from the Claude Code `statusLine` data) are planned: see [issue #11](https://github.com/mythes/agents-farm/issues/11).

## Config

All keys are optional. The file is `~/.agents-farm/config.json`:

```json
{
  "limits": {"opus": 4000000, "sonnet": 8000000, "haiku": 20000000},
  "window_hours": 5,
  "count_cache_read": false,
  "warn": 0.7,
  "crit": 0.9,
  "since_hours": 12,
  "notify": true,
  "context_window": {"default": 200000, "opus-5": 1000000, "sonnet-5": 1000000}
}
```

`context_window` sets the context size by a part of the model id (the longest match wins). Transcripts do not store this size, so check the number with `/context` in Claude Code and change it here if needed. If a session goes over its window, the window grows by itself, so the bar never shows more than 100%.

## Security and tests

Text from transcripts and hooks is treated as untrusted input (prompt injection). See [SECURITY.md](SECURITY.md).

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/bandit -r agents_farm
```

## Project layout

```
agents_farm/
  transcripts.py  incremental parser for JSONL transcripts
  events.py       hook handler and reader for events.jsonl
  store.py        builds a Snapshot and works out the statuses
  limits.py       usage per model in the 5-hour window
  render.py       Rich rendering of rows, details, limits (no Textual)
  app.py          Textual UI
  demo.py         fake data
  cli.py          command line
docs/             design notes and backlog
scripts/          checks and demo recording
.claude/skills/   skills for coding agents that maintain this repo
```

## Roadmap

See [docs/backlog.md](docs/backlog.md) and the [issues](https://github.com/mythes/agents-farm/issues): PID column, kill, start and resume sessions, fuzzy search, real limits.

## Contributing

Run `scripts/check.sh` before every commit. If you use Claude Code, the skills in `.claude/skills/` and the rules in [CLAUDE.md](CLAUDE.md) help you keep the repo in good shape.

## License

[MIT](LICENSE)
