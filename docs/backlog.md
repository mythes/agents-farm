# Backlog

Decisions that set the scope (answers to our open questions):

| Question | Decision |
|---|---|
| Where to open a new or resumed session | **In the same terminal.** The TUI pauses (`App.suspend()`), `claude` takes the screen, and when it exits you come back to the TUI |
| Which sessions we manage | **Both Desktop and CLI.** The behaviour depends on the `entrypoint` field |
| Source of the limits | **statusLine** (the official `rate_limits` data) |
| Percent per session | **Both numbers:** how full the context is, and the share of the limits |

Size: **S** up to half a day · **M** 1–2 days · **L** 3 days or more.

Each task is also a GitHub issue. The issues have the short version. This file has the research and the risks.

---

## What the research showed

Checked on a real machine with Claude Code 2.1.319 / 2.1.325. These facts change the plan, so they come first.

1. **`~/.claude/sessions/<pid>.json` is a ready list of live processes.** Fields: `pid`, `sessionId`, `cwd`, `name`, `status` (`idle` / `busy`), `entrypoint` (`claude-desktop` or CLI), `kind`, `version`, `startedAt` (ms), `procStart`, `updatedAt`, `statusUpdatedAt`, `messagingSocketPath`. All 4 live sessions here have `entrypoint=claude-desktop`. This gives us the PID, kill, and a live status without guessing from transcripts.
2. **`procStart` is in UTC, but `ps -o lstart` shows local time** (2 hours apart here). To protect against PID reuse, compare `startedAt` (epoch in ms), not the strings.
3. **On Pro the limits are one 5-hour window plus one weekly window (all models).** There is no 5-hour budget per model. Our current bars `opus/sonnet/haiku` with budgets in the config are wrong in concept, so we replace them (see T6). For example, `get_usage` in Desktop showed 5h = 50% and weekly = 54%, while our estimate showed sonnet 12% and opus 5%.
4. **statusLine receives official `rate_limits.five_hour` and `seven_day` (`used_percentage`, `resets_at`), `context_window.context_window_size`, `context_window.used_percentage`, `session_id` and `transcript_path` in its JSON.** `rate_limits` exists only for Pro/Max, and only after the first API reply. The context `used_percentage` uses input tokens only: `input + cache_creation + cache_read`, **without** `output_tokens`. Our first calculation added the output, so it was about 1k tokens too high.
5. **The real context window is 1,000,000 tokens, with auto-compact at 97%** (from `get_usage`). This solves the "which window" question (see T7a).
6. **`textual.fuzzy.Matcher` is already in Textual 8.2.8.** Checked: `apirf` → `api-refactor` scores 9.52, `docs-writer` scores 0. We need no new dependency.
7. **CLI flags:** `--resume <id>`, `-c/--continue`, `--fork-session`, `--session-id`, `--model`, `--permission-mode`, `--add-dir`, `-w/--worktree`. The Desktop app uses its own binaries (`…/claude-code/<version>/…/claude --output-format stream-json`). Their parent is a `disclaimer` wrapper.
8. `tmux` is not required. We chose to run in the same terminal.

---

## Milestones

| M | Content | Tasks | Size |
|---|---|---|---|
| **M0** | Spikes: remove 4 unknowns before we build | S1–S4 | S |
| **M1** | Session registry, PID, fuzzy search, kill | T0, T1, T5, T2 | M+S+S+M |
| **M2** | Start and resume sessions | T3, T4 | M+M |
| **M3** | Real limits and percentages | T6, T7 | L+M |

---

## M0: Spikes (the unknowns we check first)

| ID | Question | How to check | What it decides |
|---|---|---|---|
| **S1** | Does statusLine run in Desktop sessions (`stream-json`)? | Add a temporary statusLine that writes stdin to a file. Open one Desktop session and one CLI session and see if files appear. **Needs your OK to edit `settings.json`** (with a backup) | T6, T7a. If not, for Desktop we use transcripts and mark the values with `≈` |
| **S2** | Which values can `status` in `sessions/<pid>.json` have? (We saw only `idle` and `busy`.) Is there a `waiting` for a permission request? | Log changes of `status` / `statusUpdatedAt` for some hours and during a permission request | T0: can we replace hooks with the live status? |
| **S3** | Does `App.suspend()` + `claude` return the terminal to the TUI in a clean state on macOS (iTerm2, Terminal.app)? | Run `claude` by hand, exit, and check the cursor, mouse mode and colours. The `o` key (pager) is also not tested by hand yet | T3, T4 |
| **S4** | What happens in Desktop when we kill its `claude` process? | Kill a **throwaway** Desktop session (never a working one) | The warning text in T2 |

---

## M1

### T0 · Live process registry from `~/.claude/sessions` · M

**Goal.** One source of truth for the PID and for "alive or dead". T1, T2 and T4 depend on it.

**Possible:** ✅ the format is checked.

**Plan**
- `registry.py` reads `sessions/*.json` (the folder can be changed with `CLAUDE_SESSIONS_DIR` for tests) and returns `LiveSession{pid, session_id, cwd, name, status, entrypoint, kind, version, started_at}`.
- Alive check: `os.kill(pid, 0)` + `startedAt` equals the process start time (`ps -o etime=`). `psutil` is not needed. If the code gets messy, we can add it.
- `Agent` gets `pid`, `entrypoint`, `live_status`. We join by `sessionId` (subagents have no PID).
- Ignore files of dead processes (do not delete them).
- After S2: use `status` as a `busy` / `idle` signal next to the hooks.

**Done when**
- `status --json` shows `pid` and `entrypoint` for each of the 4 live sessions.
- Dead PIDs are not shown as alive.
- A test with a fake folder and a fake process.

**Risks:** the format is not documented and can change. So we validate every field strictly, and a missing file never breaks the app.

### T1 · PID column · S

**Possible:** ✅ (needs T0).

**Plan:** a `PID` column in the `DataTable` (width 6) between MODEL and TIME. Show `—` for dead sessions, subagents and sessions without a file. Hide the column under 100 columns of width. Details get `PID`, `Entrypoint` (Desktop / CLI) and `Version`. PID goes into `status --json`. The `p` key copies the PID.

**Done when:** live sessions show a PID, finished ones show `—`, and the UI does not jump when a PID appears.

### T5 · Fuzzy search · S

**Possible:** ✅ the built-in `textual.fuzzy.Matcher`, no new dependency.

**Plan**
- The `/` field becomes fuzzy. Words without `:` are matched against `name`, `project`, `branch`, `prompt` (weights: name ×3, project ×2, branch ×1.5, prompt ×1). Words like `key:value` (`status:`, `model:`, `project:`) stay exact, as now.
- Results are sorted by score (then by urgency). The match is highlighted in the AGENT column (`Matcher.highlight`).
- An empty query returns the normal order.
- Speed: under 20 ms for 500 sessions (cache the `Matcher` per query).
- Mention it in the `?` help.

**Done when:** `apirf` finds `api-refactor` first, `status:waiting dep` works together, and tests cover the ranking and the mixed query.

### T2 · Kill hotkey with confirmation · M

**Possible:** ✅ simple in code. ⚠️ For Desktop sessions we do not know what happens after a kill (S4).

**Plan**
- `x` on a live session opens a dialog: `Kill "<name>" (pid 96635, Desktop)? [y/N]`. The default is **N**. `esc` cancels.
- `y` sends `SIGTERM`. After 3 seconds, if the process still lives, ask: `Still running. SIGKILL? [y/N]`.
- **Safety rules** (all required, each with a test):
  1. Before the signal, read the pid file again and compare `startedAt` (protects against PID reuse).
  2. Never kill `pid ≤ 1`, other users' processes, our own process, or any parent of the TUI (so we never kill the session that started `agents-farm`).
  3. Kill only the `claude` process from the pid file, **not** its parent (`disclaimer` / Desktop).
  4. For `entrypoint=claude-desktop`, show an extra line: "Desktop owns this process; the session may look failed in Desktop" (final text after S4).
  5. Write each action to `~/.agents-farm/actions.log` (time, pid, name, signal), mode 0600.
- For dead sessions and subagents the key is off, with a short reason.
- Optional: a separate key `i` to interrupt the current turn (SIGINT), only if S4 shows it is safe.

**Done when:** a test with a spawned `sleep` process and a fake pid file (kill works; wrong `startedAt` → refused; parent → refused), and no signal is sent without confirmation.
**Risks:** killing a working session by mistake. The default answer is "N", and the dialog shows the name and age.

---

## M2

### T3 · New session hotkey (CLI claude) · M

**Possible:** ✅ the same way as `o` (pager): `App.suspend()` + `subprocess`. ⚠️ needs S3.

**Plan**
- `n` opens a dialog: directory (default: the `cwd` of the selected session, plus recent projects from `~/.claude/projects` with fuzzy pick, T5), model (`--model`, default from the config), permission mode (`--permission-mode`), a checkbox for `-w` (worktree).
- A separate `runner.py` with `run_interactive(cwd, args)`: call `suspend()`, ignore SIGINT in the parent while the child runs (Ctrl-C goes to `claude`), and when it exits restore the TUI and select the new session (found by a new pid file or transcript, T0).
- Config: `claude_bin` (default: `claude` from PATH, else `~/.local/bin/claude`), `claude_args` (extra flags), `claude_env`.
- Errors: missing directory, `claude` not found, exit code ≠ 0 → show a message, never crash.
- Pass arguments as a list (no shell). Never put a path or user input into a shell string.

**Done when:** `n` starts `claude` in the right directory, after `/exit` the TUI is back with a clean screen, a missing directory gives a clear error, and a test checks the argument building (without a real `claude`).
**Risks:** restoring the terminal state (mouse, alt-screen) on different terminals → S3. The TUI is blocked while the session is open (accepted, because we chose "same terminal").

### T4 · Resume a session · M

**Possible:** ✅ `claude --resume <id>` in the `cwd` of the session. ⚠️ conflict if the process is alive.

**Plan**
- `r` (and `enter` on a not-live session) runs `runner.run_interactive(cwd, ["--resume", session_id])`.
- **Alive check (T0):**
  - process dead → resume at once;
  - process alive (especially Desktop) → dialog: "This session is already running (pid N). Open a **fork** (`--fork-session`, a new history from a copy) / cancel". We do not offer to open the same session twice: both processes would write to one transcript.
- Subagent transcripts cannot be resumed (the key is off).
- `c` runs `--continue` for the newest session in the directory.
- Check that `cwd` exists. If the folder is gone, show an error with the path.
- Keep `y` (copy the command) to resume in another terminal.

**Done when:** resume of a dead CLI session works, for a live Desktop session we offer a fork (not a copy), and tests cover the mode choice (without starting `claude`).

---

## M3

### T6 · Limit monitoring: real data from statusLine · L

**Possible:** ✅ there is an official channel. ⚠️ It may not work for Desktop sessions (S1). Pro/Max only, and only after the first API reply.

**What changes:** instead of three bars per model and budgets in the config, we show **two bars: the 5-hour window and the week**, with percent, time to reset and pace.

**Plan**
1. **`agents-farm statusline`** reads JSON from stdin, writes `~/.agents-farm/state/<session_id>.json` atomically (mode 0600: `rate_limits`, `context_window`, `model`, `transcript_path`, write time), and prints a short line for the status line. It supports chaining: `--then "<command>"` (settings allow only one `statusLine`; you have none today).
2. **`agents-farm install-statusline`** shows a diff for `~/.claude/settings.json`, makes a backup, asks to confirm, and refuses without chaining if a `statusLine` already exists. No silent changes.
3. **Store:** account limits = the newest `rate_limits` across all state files (limits are shared by all sessions). Show the age of the data ("as of 3 min ago"). Mark expired data (`resets_at` in the past) as unknown.
4. **UI:** bottom bar `5h ███████░░░ 50% ↻2h42m │ 7d ██████░░░░ 54% ↻4d8h`, a pace marker (percent used compared with the share of the window that passed) with a warning "you run out in about X at this pace", the same warn/crit colours, and one alert per window.
5. **Fallback**, if there is no statusLine data (S1 is negative, or not Pro/Max): the old token estimate, but without budgets per model, clearly marked `≈`, with a hint "install the statusline for exact numbers".
6. **Config:** mark `limits` (budgets per model) and `window_hours` as deprecated. No migration is needed. The keys are ignored with a warning.

**Done when:** after installing the statusLine in a CLI session, the dashboard shows the same percent as `/usage`. Desktop works as S1 decides. Tests cover command chaining, atomic write, expired data and a missing `rate_limits`.
**Risks:** (a) Desktop may not run statusLine, so limits update only while CLI sessions are active (S1); (b) editing `settings.json` needs a backup and clear confirmation; (c) statusLine runs often (300 ms debounce), so the handler must be fast and must not import Textual.

### T7 · Percent per session (both numbers) · M

#### T7a · How full the context is

**Possible:** ✅ the data is already here.
- Source order: **statusLine state file** (`context_window.used_percentage`, `context_window_size`) → transcript with the window from the config.
- Fix the formula: `input + cache_creation + cache_read`, **without** `output`. This matches the official value.
- Show an auto-compact marker (~97%) and warn near it.
- With the statusLine we do not need `context_window` in the config for those sessions.
- Done when: the value is within 1% of `/context`, and tests cover both sources and their priority.

#### T7b · Share of the limits per session

**Possible:** ⚠️ **there is no official split per session, only an estimate.**
- Formula: `share(session) = used_5h% × (weighted tokens of the session in the window ÷ weighted tokens of all sessions in the window)`. The shares add up to the real account percent.
- Token weights (config; default follows API price ratios): input 1, output 5, cache_create 1.25, cache_read 0.1. This is an assumption and needs calibration. Subscription limits are not linear in tokens.
- A `5H%` column marked `≈`; details also show `7d%`. Sort by this column with `s`. Sessions with no activity in the window show `—`.
- Done when: the shares add up to about the account percent, a test covers the split, and the help says this is an estimate.

---

## Cross-cutting

- **Tests:** the variables `CLAUDE_SESSIONS_DIR`, `CLAUDE_PROJECTS_DIR` and `AGENTS_FARM_HOME` replace the real folders. Textual `run_test` covers the UI. Fake processes cover kill. Nothing may start a real `claude` or touch real sessions.
- **Security:** every new action (kill, start, resume, editing `settings.json`) needs an explicit confirmation. All strings from transcripts and pid files go through `sanitize()`. Process arguments never use a shell. Actions go to `actions.log`. Update `SECURITY.md`.
- **Performance:** UI updates must not block on reads (they run in a thread). The PID and limit columns must add less than 50 ms per refresh for 200 sessions.
- **Docs:** update the key table in the README and in `?`, and add the statusLine install guide.

## Order of work

`S1–S4` → `T0` → `T1` + `T5` → `T2` → `T3` → `T4` → `T6` → `T7a` → `T7b`

The biggest unknown is **S1** (does statusLine run in Desktop sessions?). It decides how exact the limits will be for the main use case. So check it before T6, and best of all first.
