# agents-farm

A terminal dashboard for your [Claude Code](https://claude.com/claude-code) agents.
See which agents are working, what they do, how full their context is, and how much of your limits you have used.

![agents-farm overview](docs/demo/overview.gif)

> Try it without any real sessions: `af --demo` (see [Install](#install))

## Features

Each feature has a short demo. The exact rules are on one page: **[docs/rules.md](docs/rules.md)**.

### 1. See every agent
![overview](docs/demo/overview.gif)

A live list with a status symbol: `?` waits for you, `!` error, `●` running, `⏸` stalled, `✓` done. The **SRC** column says where a session was started: `B` background, `T` terminal, `D` Claude Desktop, `S` SDK (a star, `B*`, means this agents-farm started it). Agents that need you are on top, subagents show under their parent. Open the details (context, activity, plan) with `z`, see usage and reset time per model at the bottom, and get an alert when an agent starts to wait for you. Idle and ended sessions are hidden until `h`. `t` changes the period: the last 24 hours, 3 days or 7 days.

### 2. Find one fast
![search](docs/demo/search.gif)

`/` and a few letters: `apir` finds `api-refactor`. Add filters: `status:waiting`, `model:opus`, `project:api`.

### 3. Start a session
![new session](docs/demo/new-session.gif)

`n` opens a folder browser: type letters to filter folders (fuzzy), `Tab` opens a folder, a preview shows its content and git branch. `Ctrl+A` picks the model, `Ctrl+S` the permission mode (`default`, `acceptEdits`, `auto`, `plan`), `Ctrl+D` a git worktree. `Ctrl+F` opens a multi-line first prompt, `Ctrl+E` starts. The dialog remembers your last choices, also after a restart.

### 4. Leave a session and come back
![background](docs/demo/background.gif)

Every session starts in the background, so it keeps running. By default it opens here at once: press **`Ctrl+Z`** to go back to the dashboard (it keeps running), `/exit` ends it. With `Ctrl+B` ("open now: no") it stays closed, and you open it later with `a`.

### 5. Continue or fork
![resume](docs/demo/resume.gif)

`r` **continues** a session that has ended (the same session and history). `f` **forks** any session: a new session with the same history, and the original is not changed. A session that is still running can only be forked, because two processes must never write to one history. A Claude Desktop chat defaults to a fork.

### 6. Keys that do not fit explain themselves
![greyed keys](docs/demo/greyed-keys.gif)

The footer shows a key in grey when it does not fit the selected session. Press it anyway and a pop-up says why and which keys to use instead (press one there to do it).

### 7. Help that decodes everything
![help](docs/demo/help.gif)

`?` explains every key, every status symbol (`?` `!` `●` `◐` `⏸` `✓` `◌`), the SRC letters, and every column (PID, TIME, CTX, LIMITS). The arrow keys scroll it.

### 8. Stop safely
![stop](docs/demo/stop.gif)

`x` always asks, and **the default answer is No**. A background session is stopped with `claude stop`, any other process with SIGTERM (a second question before SIGKILL). The process is checked again before every signal.

## Install

You need Claude Code. It works on macOS and Linux.

### With Homebrew

```bash
brew install mythes/tap/agents-farm
```

Homebrew installs it with its own Python, so you need nothing else. Then run `af --demo`. You get the commands `agents-farm` and the short name `af` (Homebrew makes `af` as a link, and it will not replace a file it did not create). Update with `brew upgrade agents-farm`, remove with `brew uninstall agents-farm`. The formula lives in [mythes/homebrew-tap](https://github.com/mythes/homebrew-tap), a tap that can hold more apps later.

### With the install script

You need Python 3.9 or newer.

```bash
git clone https://github.com/mythes/agents-farm.git
cd agents-farm
scripts/install.sh
```

The script makes a private virtual environment in `~/.local/share/agents-farm` and adds two commands to `~/.local/bin`: `agents-farm` and the short name **`af`**. Then run `af --demo`.

If `~/.local/bin` is not on your `PATH`, the script prints the line to add to your shell config.

**It never overwrites anything it did not create.** Before it makes `af`, it checks that the name is free: no other program on your `PATH`, no alias or function in your shell config. If the name is taken, it skips the short name, tells you why, and installs `agents-farm` anyway. Pick another name with `--name`:

```bash
scripts/install.sh --name farm        # use another short name
scripts/install.sh --no-alias         # only `agents-farm`
scripts/install.sh --dry-run          # show the plan and the checks, change nothing
scripts/install.sh --uninstall        # remove the commands and the virtual environment
```

The script does not edit your shell config or `~/.claude/settings.json`. `--uninstall` removes only what the script created, and keeps your data in `~/.agents-farm`.

Install without a clone (read the script first: [scripts/install.sh](scripts/install.sh)):

```bash
curl -fsSL https://raw.githubusercontent.com/mythes/agents-farm/main/scripts/install.sh | bash -s -- --ref v0.7.0
```

> **Why `af`?** It is short, and at the time of writing it is free in Homebrew, PyPI and Debian. Two old tools use the same name: an npm package (the AppFog CLI) and a Rust crate (an HTTP fetch tool). If you installed one of them, or you have `alias af=…`, the script will notice and keep your command. The short name is only a link made on your machine, so the package itself does not claim `af` for everyone.

For development, install in editable mode: `scripts/install.sh --editable`, or use a virtual environment with `pip install -e '.[dev]'`.

## Use

After the install, `af` and `agents-farm` are the same command.

```bash
agents-farm             # your real sessions from ~/.claude/projects
agents-farm --demo      # made-up sessions and a fake claude, good for a first look
agents-farm --since 72  # show sessions from the last 72 hours (default: 24)
```

Try every state without any real session:

```bash
agents-farm --demo      # made-up sessions and a fake claude; nothing real is touched, and it cleans up when you quit
```

The demo builds a temporary folder with sessions that wait, run, think, stall, finish, fail, run in the background, have ended or were interrupted, a Claude Desktop chat, a subagent, and a folder that is "not trusted". The processes are real (fake) ones, and `n`, `a`, `r`, `f` and `x` really work on them.

One-line status (for tmux or a status line) and JSON (for scripts):

```bash
agents-farm status          # ?1 ●2 │ sonnet 25% │ opus 7%
agents-farm status --json
```

## Keys

A key that does not fit the selected session is grey in the footer; see [rules, section 2](docs/rules.md#2-what-you-can-do-with-a-session).

| Key | Action |
|---|---|
| `n` | New session: folder browser, model, mode, worktree, first prompt |
| `a` | Open a background session here. **`Ctrl+Z` leaves it and keeps it running** |
| `r` | Continue a session that has ended (the same session and history) |
| `f` | Fork a session: a new session with the same history (also for one that runs) |
| `x` | Stop the session's process. Asks first, and the default answer is No |
| `p` | Copy the PID |
| `↑` `↓` / `j` `k` | Move between agents |
| `enter` / `z` | Zoom: details on the full screen. `esc` goes back |
| `1` `2` `3` / `e` | Open or close Context / Activity / Plan, or all sections |
| `/` | Search: letters (fuzzy) and filters (`status:waiting`, `model:opus`, `project:api`) |
| `h` | Show or hide idle sessions (including ended ones) and finished subagents |
| `t` | Period: the last 24 hours, 3 days or 7 days. It is remembered, and then used instead of `since_hours`; `--since` wins for one run. Running sessions are always listed |
| `o` | Open the full log in `$PAGER` |
| `Ctrl+R` | Refresh now |
| `?` / `q` | Help / quit |

## Where the data comes from

1. **Transcripts** in `~/.claude/projects/**/*.jsonl`. They are read step by step (only new lines). They give the prompt, the steps, files, plan, tokens, model and context size.
2. **Process files** in `~/.claude/sessions/<pid>.json`, written by Claude Code. They give the PID, Desktop or CLI, and the version. A PID is shown only if that process is running and its start time matches the file, so a reused PID is never shown for the wrong session. Their `status` field (`idle`, `busy`, `waiting`) is also the **live status** of the agent: the exact `? waiting` needs no setup, and it appears about 6 seconds sooner than the Claude Code notification hook.
3. **Hooks** (optional). The status no longer depends on them. When hooks are installed, they add the text of the request (for example `permission: Bash`), and they are the only source for sessions that have no process file (older Claude Code versions). Without a process file and without hooks, "waiting for permission" can only be guessed, and the agent can show as `⏸ stalled`.

When there is no process for a session any more and its transcript has been quiet for a minute, it is shown as `idle` (ended), not as `running` or `stalled`, and it is hidden until you press `h`. `stalled` (`⏸`) is only used for a live process that has printed nothing for a long time (see `busy_stalled_s`).

### Install the hooks (optional)

Print the block for your `~/.claude/settings.json`:

```bash
agents-farm hooks-snippet
```

Add the content of `"hooks"` to your settings. If you already have hooks for the same events, put the new entries next to the old ones. The hook writes one line to `~/.agents-farm/events.jsonl` (about 140 ms per call). It never fails and always exits with code 0. The top bar tells you where the status comes from: `live ✓` (process files), `hooks ✓`, or both.

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
  "since_hours": 24,
  "notify": true,
  "busy_stalled_s": 600,
  "allow_kill": true,
  "claude_bin": "",
  "claude_args": [],
  "claude_env": {},
  "use_background": true,
  "new_model": "",
  "models": [],
  "context_window": {"default": 200000, "opus-5": 1000000, "sonnet-5": 1000000}
}
```

`claude_args` are extra flags for every new session (a list of strings), `claude_env` are extra environment variables, and `new_model` is the default model in the dialog. `models` adds model names to its list. `use_background` (default `true`) starts every session in the background; set it to `false` if your account or Claude Code version does not allow background sessions, and plain `claude` sessions are used instead (see [the rules](docs/rules.md#3-starting-a-session-n)).

`busy_stalled_s` is how long a `busy` agent may print nothing before it is shown as stalled (default 10 minutes).

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
  tail.py         reads files in chunks
  registry.py     running processes from ~/.claude/sessions (PID, Desktop or CLI)
  killer.py       safe stop of a process (checks before every signal)
  runner.py       starts, opens, resumes and stops sessions with Claude Code's own commands
  capabilities.py what each key can do for the selected session, and why not
  picker.py       folders and models for the new-session dialog
  playground.py   the demo: made-up sessions, processes and a fake claude (fake_claude.py)
  search.py       fuzzy search and filters
  events.py       hook handler and reader for events.jsonl
  store.py        builds a Snapshot and works out the statuses
  limits.py       usage per model in the 5-hour window
  render.py       Rich rendering of rows, details, limits (no Textual)
  app.py          Textual UI
  config.py       settings from the config file
  cli.py          command line
docs/             rules (rules.md), design notes, backlog, and the feature demos (demo/)
scripts/          checks and demo recording
.claude/skills/   skills for coding agents that maintain this repo
```

## Roadmap

See [docs/backlog.md](docs/backlog.md) and the [issues](https://github.com/mythes/agents-farm/issues). Done: PID column, live status, fuzzy search, stop, start a new session (folder browser, models, first prompt), background sessions with `Ctrl+Z`, resume and fork, greyed keys with explanations. Next: real limits and the share of the limits per session.

## Contributing

Run `scripts/check.sh` before every commit. If you use Claude Code, the skills in `.claude/skills/` and the rules in [CLAUDE.md](CLAUDE.md) help you keep the repo in good shape.

## License

[MIT](LICENSE)
