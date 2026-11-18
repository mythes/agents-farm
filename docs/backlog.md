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
9. **S1 result (checked on 2026-11-18): Desktop sessions do not run the statusLine command. CLI sessions do.**
   - We added a test statusLine to `~/.claude/settings.json`. A new CLI session (`entrypoint=cli`, 2.1.319) called it twice within seconds.
   - A new Desktop session (`claude-desktop` 2.1.325) was started after the change, received a prompt and answered. Its hooks from the **same** settings file fired (`SessionStart`, `UserPromptSubmit`, `Stop`), but the statusLine was never called. The four older Desktop sessions did not call it either.
   - The CLI data had `rate_limits.five_hour` and `seven_day` (`used_percentage`, `resets_at`), `context_window` (size, `used_percentage`, `current_usage`), `cost`, `version`, `workspace.repo` and more.
   - Limits are shared by the whole account, so a number from a CLI session is also true for Desktop sessions. But it is fresh only while some CLI session is active.
   - We found no other source for Desktop: the common fields of hook payloads have no limits (per-event fields were only partly read), and nothing is cached on disk (only feature flags).
10. **Context window sizes can be learned from CLI sessions.** The CLI statusLine reported `context_window_size = 1,000,000` for `claude-haiku-5-5` too, so the default of 200k for haiku-5 is probably wrong. Handle it in T7a.
11. **S2 result (2026-11-18): the pid file does write `waiting`, and it is as fast as the hooks.**
    - Values seen: `idle`, `busy`, `waiting`. A CLI session has no `status` for a moment at start, then `idle`.
    - Test: a Desktop chat asked a question with `AskUserQuestion` and waited. The pid file changed `busy` → `waiting` at 10:42:55.148 and back to `busy` at 10:43:16.349, when the user answered, then `idle` at 10:43:19.555.
    - Compared with the hooks of the same session: `PermissionRequest` came 57 ms **after** `waiting`, `Notification` (permission_prompt) came **6 s after** it, `PostToolUse` 121 ms after `busy`, `Stop` 20 ms before `idle`.
    - So the pid file gives the status `waiting` with no hooks and sooner than the `Notification` hook. Not tested: a normal tool permission prompt (for example Bash). The `PermissionRequest` hook fired in the same way, so it is probably the same.
    - The binary of Claude Code also lists the states `starting, running, resuming, adopted, crashed, working, blocked, done, stopped, failed, shell`. We never saw them in session files.
    - The pid file of a finished session is removed.
12. **S3 result (2026-11-18): suspend and resume of the terminal works** in the terminal panel of the Claude app. A probe TUI (mouse, timer, colours) was suspended with `App.suspend()`, ran `less` and a real interactive `claude`, and came back with mouse, timer, colours, cursor and keys all fine. Not tested yet: iTerm2 and Terminal.app on their own.
13. **S4 result (2026-11-18): killing the process of a Desktop session is safe when the session is idle, and Desktop restarts it by itself.**
    - We sent `SIGTERM` to the `claude` process of an idle Desktop chat. Its pid file was removed in 0.1 s, the process ended in about 1 s, and its parent wrapper `disclaimer` ended with it. The `SessionEnd` hook ran. The Desktop app and other sessions were not affected.
    - The chat showed nothing unusual. Its transcript stayed whole.
    - When the user sent the next message, Desktop started a **new process with a new pid** for the **same session id**. The same transcript file continued, and `SessionStart` ran again before the message.
    - So a pid is not stable for a Desktop session: always join by session id (T0 does).
    - Not tested: killing a session that is `busy` or `waiting`. The current turn would be lost.

14. **S5 result (2026-11-18): Claude Code 2.1.327 has its own background sessions, and they fit `af` well.** Checked with one real `claude --bg` session (haiku, `plan` mode, read-only task in a trusted folder), stopped afterwards.
    - Commands: `claude --bg "<prompt>"` (prints a short id), `claude attach <id>`, `claude logs <id>`, `claude stop <id>`, `claude rm <id>`, `claude respawn`, `claude agents` (its own screen) and `claude agents --json` (a list of active sessions). `claude --bg --resume <session-id>` continues the session in the background under the same id, or starts a copy and says so when it is already running.
    - A background session gets a normal pid file in `~/.claude/sessions` (`kind: "bg"`, `entrypoint: "cli"`, `status`, a `jobId`), and its transcript is in the usual place, named by the session id. **The current `af` showed it with no code change** (status `done`, pid, CLI). The short id from `agents --json` is the first 8 characters of the session id. `agents --json` has a `state` (`working`, `done`, `blocked`) that is not the same as the pid file `status`.
    - A background session only starts in a folder you already trusted ("Workspace not trusted" otherwise). We must not accept trust for the user: show the message.
    - `attach` shows the live screen of the session. **Ctrl+Z ends the `attach` process with exit code 0 and the session keeps running** (so `af` gets the terminal back, no `/exit` needed). The left arrow does not leave `attach`: it opens the agent view inside the same process.
    - A prompt typed in `attach` while the session is busy reaches the model in the same turn (the answer to a long task contained the line asked for in the second prompt).
    - `claude logs` prints the raw terminal stream with escape codes: it needs cleaning before it can be shown.
    - `claude stop` ended the process, removed the pid file and the entry in `agents --json`. The conversation stays in the transcript.
    - Not tested: a `blocked` session being answered from `attach`, `respawn`, `rm` with a worktree, and iTerm2 / Terminal.app.

---

## Milestones

| M | Content | Tasks | Size |
|---|---|---|---|
| **M0** | Spikes: remove 4 unknowns before we build. **Done** | S1–S4 | S |
| **M1** | Session registry, PID, fuzzy search, live status, kill. **Done in v0.2.0** | T0, T1, T5, T8, T2 | M+S+S+S+M |
| **M2** | Start and resume sessions | T3, T4 | M+M |
| **M3** | Real limits and percentages | T6, T7 | L+M |

---

## M0: Spikes (the unknowns we check first)

| ID | Question | How to check | What it decides |
|---|---|---|---|
| **S1** | Does statusLine run in Desktop sessions (`stream-json`)? | Add a temporary statusLine that writes stdin to a file. Open one Desktop session and one CLI session and see if files appear. **Needs your OK to edit `settings.json`** (with a backup) | T6, T7a. **Result: no for Desktop, yes for CLI (finding 9).** For Desktop we use the newest CLI value (with its age) or transcripts, and mark estimates with `≈` |
| **S2** | Which values can `status` in `sessions/<pid>.json` have? (We saw only `idle` and `busy`.) Is there a `waiting` for a permission request? | Log changes of `status` / `statusUpdatedAt` for some hours and during a permission request | T0: can we replace hooks with the live status? **Result: done. `waiting` exists and comes before the hooks (finding 11).** |
| **S3** | Does `App.suspend()` + `claude` return the terminal to the TUI in a clean state on macOS (iTerm2, Terminal.app)? | Run `claude` by hand, exit, and check the cursor, mouse mode and colours. The `o` key (pager) is also not tested by hand yet | T3, T4 **Result: works in the Claude app terminal (finding 12). iTerm2 and Terminal.app not tested.** |
| **S4** | What happens in Desktop when we kill its `claude` process? | Kill a **throwaway** Desktop session (never a working one) | The warning text in T2 **Result: done. Safe when idle, Desktop restarts the process on the next message (finding 13).** |
| **S5** | Can `af` use Claude Code's own background sessions (`--bg`, `attach`) to leave a session without `/exit` and to type a prompt while it works? | Start one cheap read-only `--bg` session, attach through a pty, try Ctrl+Z and the left arrow, type a second prompt while it is busy, then stop it | T9, T4 **Result: yes (finding 14).** |

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
- The `status` field is used as the live status: see T8 (S2 confirmed that it has `waiting`).

**Done when**
- `status --json` shows `pid` and `entrypoint` for each of the 4 live sessions.
- Dead PIDs are not shown as alive.
- A test with a fake folder and a fake process.

**Risks:** the format is not documented and can change. So we validate every field strictly, and a missing file never breaks the app.

### T8 · Live status from the pid files (no hooks needed) · S

**Possible:** ✅ (S2 confirmed it). Needs T0.

**Why.** The pid file has `idle`, `busy` and `waiting`, updated within about 60 ms of the hooks. `waiting` appears 6 s before the `Notification` hook. So the exact "waits for you" status works for every user, even without hooks.

**Plan**
- `waiting` → `Status.WAITING` (the note comes from the hook `Notification` text when hooks are installed, else "waiting for your answer").
- `busy` → running or thinking (keep the transcript to tell them apart). `idle` → done, or idle when the session is old.
- A live pid-file status wins over the guess from the transcript. If there is no pid file, keep today's logic.
- Hooks stay as an extra: message text and the `Stop` / `SessionEnd` events. When both agree, nothing changes.
- Ignore states we never saw (`blocked`, `crashed`…) but show them in the details as text.
- Tell the user in the top bar when the status comes from the pid file (`live ✓`) instead of hooks.

**Done when**
- [ ] an agent that waits for you shows `?` without hooks installed
- [ ] the status changes back to running right after the answer
- [ ] tests for each value and for a missing or broken file

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

**Possible:** ✅ simple in code. S4 showed that killing an **idle** Desktop session is safe: the history stays and Desktop starts a new process on the next message. A **busy** session loses its current turn.

**Plan**
- `x` on a live session opens a dialog: `Kill "<name>" (pid 96635, Desktop)? [y/N]`. The default is **N**. `esc` cancels.
- `y` sends `SIGTERM`. After 3 seconds, if the process still lives, ask: `Still running. SIGKILL? [y/N]`.
- **Safety rules** (all required, each with a test):
  1. Before the signal, read the pid file again and compare `startedAt` (protects against PID reuse).
  2. Never kill `pid ≤ 1`, other users' processes, our own process, or any parent of the TUI (so we never kill the session that started `agents-farm`).
  3. Kill only the `claude` process from the pid file, **not** its parent (`disclaimer` / Desktop).
  4. For `entrypoint=claude-desktop`, show an extra line: "Desktop will start a new process for this chat when you send the next message. The history is kept." If the status is `busy` or `waiting`, add a stronger warning: "The current turn will be lost."
  5. Write each action to `~/.agents-farm/actions.log` (time, pid, name, signal), mode 0600.
- For dead sessions and subagents the key is off, with a short reason.
- Optional: a separate key `i` to interrupt the current turn (SIGINT). S4 did not test SIGINT, so check it in its own spike before we offer it.

**Done when:** a test with a spawned `sleep` process and a fake pid file (kill works; wrong `startedAt` → refused; parent → refused), and no signal is sent without confirmation.
**Risks:** killing a working session by mistake. The default answer is "N", and the dialog shows the name and age.

---

## M2

### T3 · New session hotkey (CLI claude) · M

**Done in v0.2.0.** Still to check by hand: iTerm2 and Terminal.app.

**Possible:** ✅ the same way as `o` (pager): `App.suspend()` + `subprocess`. S3 passed in the Claude app terminal; check iTerm2 and Terminal.app by hand.

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
  - process alive (especially Desktop) → dialog (S4: a Desktop chat that is not running is restarted by Desktop on the next message, so a manual resume could race with it and create two writers; prefer the fork): "This session is already running (pid N). Open a **fork** (`--fork-session`, a new history from a copy) / cancel". We do not offer to open the same session twice: both processes would write to one transcript.
- Subagent transcripts cannot be resumed (the key is off).
- `c` runs `--continue` for the newest session in the directory.
- Check that `cwd` exists. If the folder is gone, show an error with the path.
- Keep `y` (copy the command) to resume in another terminal.

**Done when:** resume of a dead CLI session works, for a live Desktop session we offer a fork (not a copy), and tests cover the mode choice (without starting `claude`).

---

### T9 · Background sessions: start, attach, stop · M · **done (v0.5.0)**

**Possible:** ✅ (S5, finding 14). Uses the official commands only (`claude --bg`, `attach`, `stop`, `agents --json`), no keystroke injection and no tmux.

**What was built (the design changed while we tested)**
- **Every session starts with `claude --bg`.** In the `n` dialog, `Ctrl+B` (background) decides what happens next: on = stay in `af` and open it later with `a`; off (a normal session) = `claude attach <id>` right away inside `App.suspend()`. So `Ctrl+Z` brings you back to `af` in both cases and the session keeps running. We first tried to park a normal foreground `claude` that was stopped with Ctrl+Z, and dropped it: a stopped process does no work, and a normal `claude` cannot run without the terminal.
- **`Ctrl+Z` handling (`runner.run_interactive`).** The terminal sends it to every process of the foreground group, `af` included, so `af` was stopped while `claude` left. Now `af` uses a signal handler that does nothing (not `SIG_IGN`, which the child would inherit) for `SIGINT` and `SIGTSTP`, waits with `WUNTRACED`, ends a stopped attach client (`leave_on_stop`) and resumes any other stopped child.
- A folder that is not trusted: `claude --bg` says "Workspace not trusted". A normal session falls back to a plain `claude` in the foreground so the user can answer the question; with `Ctrl+B` on, the error is shown. We never answer the trust question for the user.
- `a` runs `claude attach <id>`, with a hint first. `x` on a background session runs `claude stop <id>`. `claude rm` is not offered (it can delete a worktree).
- The first prompt (optional, multi-line, `Ctrl+F`) goes first in the argument list, and a leading `-` is hidden behind a space.
- A running session with no transcript yet (a new background session) is listed from its pid file. A session with no process and a quiet transcript is shown as ended (`idle`), never as `stalled`. A zombie (`<defunct>`) is not a running process.
- A warning when a background session uses the `default` permission mode: it stops at its first permission request.

**Not done / ideas:** a clean "terminal output" block in zoom from `claude logs <id>` (it prints raw escape codes), and a sign for background sessions in the list (the details say `background`).
**Risks:** `Ctrl+Z` in iTerm2 and Terminal.app (S3 list); `claude` command names can change between versions (check `claude --help` and fail softly).

## M3

### T6 · Limit monitoring: real data from statusLine · L

**Possible:** ✅ for CLI sessions (S1 confirmed). ⚠️ **Desktop sessions do not run the statusLine (S1)**, so Desktop-only use gets no fresh numbers from it. Pro/Max only, and only after the first API reply.

**What changes:** instead of three bars per model and budgets in the config, we show **two bars: the 5-hour window and the week**, with percent, time to reset and pace.

**Plan**
1. **`agents-farm statusline`** (runs in CLI sessions only) reads JSON from stdin, writes `~/.agents-farm/state/<session_id>.json` atomically (mode 0600: `rate_limits`, `context_window`, `model`, `transcript_path`, write time), and prints a short line for the status line. It supports chaining: `--then "<command>"` (settings allow only one `statusLine`; you have none today).
2. **`agents-farm install-statusline`** shows a diff for `~/.claude/settings.json`, makes a backup, asks to confirm, and refuses without chaining if a `statusLine` already exists. No silent changes.
3. **Store:** account limits = the newest `rate_limits` across all state files (limits are shared by all sessions, so a CLI value is also valid for Desktop sessions). Show the age of the data ("as of 3 min ago"). Mark expired data (`resets_at` in the past) as unknown.
4. **UI:** bottom bar `5h ███████░░░ 50% ↻2h42m │ 7d ██████░░░░ 54% ↻4d8h`, a pace marker (percent used compared with the share of the window that passed) with a warning "you run out in about X at this pace", the same warn/crit colours, and one alert per window.
5. **Fallback**, if there is no statusLine data (no CLI session ran recently, which is the normal case for Desktop-only use, or the plan is not Pro/Max): the old token estimate, but without budgets per model, clearly marked `≈`, with a hint "install the statusline for exact numbers".
6. **Config:** mark `limits` (budgets per model) and `window_hours` as deprecated. No migration is needed. The keys are ignored with a warning.

**Done when:** after installing the statusLine in a CLI session, the dashboard shows the same percent as `/usage`. For Desktop sessions it shows the newest CLI value with its age, or the `≈` estimate when there is none. Tests cover command chaining, atomic write, expired data and a missing `rate_limits`.
**Open question (candidate spike S5):** is there any source of fresh limits for a Desktop-only user? Ideas to study: the usage data behind `/usage` (it needs the user's login token and is not documented, so only with explicit consent), or reading the "limit reached" messages in transcripts (only at 100%). Do not build on either before a spike.
**Risks:** (a) Desktop does not run statusLine (confirmed), so limits update only while CLI sessions are active; (b) editing `settings.json` needs a backup and clear confirmation; (c) statusLine runs often (300 ms debounce), so the handler must be fast and must not import Textual.

### T7 · Percent per session (both numbers) · M

#### T7a · How full the context is

**Possible:** ✅ the data is already here.
- Source order: **statusLine state file** (`context_window.used_percentage`, `context_window_size`; CLI sessions only, S1) → transcript with the window from the config. Desktop sessions always use the transcript.
- Learn the window per model from the state files of CLI sessions (for example haiku-5-5 reported 1,000,000) and keep it in a small file, so Desktop sessions of the same model get the right window without any config.
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

`S1–S4` → `T0` → `T1` + `T5` → `T8` → `T2` → `T3` → `T9` → `T4` → `T6` → `T7a` → `T7b`

The biggest unknown is **S1** (does statusLine run in Desktop sessions?). It decides how exact the limits will be for the main use case. So check it before T6, and best of all first.
