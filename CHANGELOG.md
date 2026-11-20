# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). While the version is `0.x`, things can change between releases.

## [Unreleased]

## [0.6.2] - 2026-11-20

A memory leak fix. Please update: in 0.6.0 and 0.6.1 a dashboard left open grew to about 1 GB of RAM and used a lot of CPU in a day.

### Fixed
- **Memory leak and high CPU.** The footer was rebuilt on every refresh (every 2 seconds) and the old parts were never freed, about 0.2 MB each time. Now it is rebuilt only when the usable keys change. The heap stays at about 13 MB, and a refresh is about 3 times faster.
- The spinner timer runs only while an agent is thinking, so an idle dashboard does not wake up 4 times a second.
- `ps` runs once every 6 seconds, not at every refresh.
- `events.jsonl` (2 MB) and `actions.log` (256 KB) are trimmed to their newest lines, so they do not grow for ever.

### Added
- `scripts/perf_check.py` and the `perf-check` skill: a long run on the playground that fails when memory grows or refreshes get slower.

## [0.6.1] - 2026-11-19

The `auto` permission mode, and the new-session dialog remembers your last choices.

### Added
- **The `auto` permission mode** in the new-session dialog (`Ctrl+S` cycles `default`, `acceptEdits`, `auto`, `plan`). In `auto` mode Claude's own classifier decides what is safe. Modes that skip permission checks are still never offered.
- **The dialog remembers the last choices** (model, mode, worktree, open now) between runs, in `~/.agents-farm/state.json` (readable only by you). Values that are not valid any more are ignored, and `new_model` in the config is used until you choose one. The demo keeps its own state, and the tests never touch the real file.

## [0.6.0] - 2026-11-19

Continue and fork, keys that explain themselves, a SRC column, a demo you can really use, and a help screen that decodes everything.

### Added
- Resume a session with `r` (continue it, the same session and history) and fork it with `f` (a new session with the same history, also for one that runs). Both start in the background and open the session like a new one (`claude --bg --resume`, then `claude attach`), so `Ctrl+Z` brings you back. A session that runs in a terminal or in Claude Desktop, or whose state is unknown, is never continued in place (two processes would write to one history): only a fork is possible. A Desktop chat that has ended defaults to a fork. A session already running in the background is opened with `a`. The origin of a session (`cli`, `claude-desktop`) is read from its transcript, so it is known also after the process has ended.
- **Keys that do not fit explain themselves.** The footer shows a key in grey when it does not fit the selected session (for example `a` on an ended session, or `x` on a subagent). If you press it anyway, a pop-up says why and which keys to use instead, and you can press one of them there.
- **The help screen (`?`) decodes everything:** the keys in groups, every status symbol, the SRC letters, every column (PID, TIME, CTX, LIMITS) and a few tips. It scrolls with the arrow keys. The text lives in `agents_farm/helptext.py`, and a test makes sure that every status is described.
- **`f` forks a session** (a new session with the same history; also for one that runs), and `r` now only continues a session that has ended. Fork was a hidden choice inside the `r` dialog before.
- **SRC column:** a letter for where each session was started (`B` background, `T` terminal, `D` Claude Desktop, `S` SDK), with a star when this agents-farm started it.
- **Without a background session.** If `claude --bg` is refused for any reason (not trusted, turned off by an administrator, an older Claude Code), a normal session starts in this terminal and agents-farm says why. `Ctrl+Z` there leaves an idle session: it is ended and `r` continues it later, from this or any other agents-farm. A busy session is not ended. New config key `use_background` (`false` always uses plain `claude`).
- **`agents-farm --demo` runs on a playground:** made-up sessions in every state (waiting, running, stalled, done, error, background, ended, interrupted, a Desktop chat, a subagent, an untrusted folder) with real fake processes and a fake `claude` (`--bg`, `attach`, `stop`, `--resume`, plain), so `n`, `a`, `r`, `f` and `x` really work in the demo. Nothing real is touched, and it cleans up when you quit.
- **docs/rules.md:** every rule on one page (statuses, which key works on which session, starting, leaving, resume, stop), and the README shows each feature in a short demo (`docs/demo/`, one recording per feature).

### Changed
- Refresh is now `Ctrl+R` (it was `r`).
- The footer starts with the keys of the selected session (`n a r f x`), and the labels are shorter, so a narrow terminal still shows them.
- One word for each thing: a **fork** is a new session with the same history (it was called a copy), and the dialog option is **open now** yes or no (it was called background). A subagent now gets the same explanation for every key: select its parent.
- The README is organised by feature, and the single demo is replaced by one short demo per feature.

### Removed
- The `y` key (copy a command). It was mostly useful over SSH; with `r`, `f` and `a` the session can be continued, forked or opened from agents-farm itself.

### Fixed
- The new session was sometimes not selected after it started: the first snapshot cleared the request even when the session was not in it yet. It now waits up to 15 seconds, and picks the session by its id.
- A second `Ctrl+Z` (a double press) while the dashboard came back could still stop agents-farm. The signal handlers now stay in place until the dashboard has the terminal back, and queued keys are dropped.
- A child process that stops again as soon as it is continued (for example agents-farm started with `&`) no longer makes a busy loop: it is ended with a clear message.
- `r` could continue in place a session whose state was unknown (no process files); it now offers only a fork.

## [0.5.0] - 2026-11-18

A multi-line first prompt, clearer key hints, and every session started in the background.

### Changed
- **Every session now starts in the background** (`claude --bg`), so it keeps running whatever you do next. A normal session (the default) is opened right away with `claude attach`, and **`Ctrl+Z` brings you back** to agents-farm while the session keeps running (`/exit` ends it). With `Ctrl+B` on, the session is not opened and you open it later with `a`. If the folder is not trusted yet, a normal session falls back to a plain `claude` in this terminal, so you can answer the trust question yourself.
- The first prompt in the `n` dialog is a multi-line editor. `Ctrl+F` hides the folder list and gives the whole area to the prompt. Long lines wrap and `Enter` adds a new line; `Ctrl+E` starts the session from anywhere in the dialog (with or without a prompt); the arrow keys, `Tab` and `→` belong to the text there. The key hints at the bottom have two levels (options and start, then moving around), a colour for each group, and the option values are coloured by meaning.

### Fixed
- A session whose process is gone and whose transcript has been quiet for a minute was shown as `stalled` or `running` (a guess from the transcript, for example after you interrupted it). It is now `idle` (ended) and hidden until you press `h`. Errors, finished answers and sessions that are still writing are not affected.
- `Ctrl+Z` in an attached background session stopped agents-farm itself. The terminal sends the key to every process in the foreground group, and agents-farm was one of them, so it was stopped while `claude` left. Now agents-farm ignores the stop signal while `claude` runs, ends the attach client when you press `Ctrl+Z` and comes back to the dashboard (the session keeps running). In a normal session `Ctrl+Z` still does nothing: a stopped `claude` is resumed, so no stopped process is left behind.
- A finished process that its parent has not cleaned up yet (`<defunct>`, a zombie) was listed as running, and `x` on it said "does not look like claude". It is no longer listed as running, and the message now explains it.

## [0.4.1] - 2026-11-18

Install with Homebrew, and clearer hints for leaving a session.

### Changed
- The `n` dialog always shows how to leave a session, whatever `Ctrl+B` is set to: `Ctrl+Z` for a background session (it keeps running), `/exit` for a normal one (it ends). `Ctrl+Z` does nothing in a normal session. The README says it too.

### Added
- Install with Homebrew: `brew install mythes/tap/agents-farm` (the formula is in the separate repository `mythes/homebrew-tap`).

## [0.4.0] - 2026-11-18

Background sessions: start them, attach to them and come back, all from the dashboard.

### Added
- Background sessions, with Claude Code's own commands. In the `n` dialog `Ctrl+B` starts the session with `claude --bg`, and `af` stays on screen. `a` opens a background session in this terminal (`claude attach`): you can type to it while it works, and **`Ctrl+Z` brings you back** to agents-farm while the session keeps running. `x` on a background session runs `claude stop`. The details show `background`. Sessions that are not in the background stay view-only. A hint is shown before attach, and a warning when a background session uses the `default` permission mode (it stops at its first permission request). The `n` dialog has an optional first prompt (`Ctrl+F` switches to it), for normal and background sessions. The footer now shows `Attach` and `Stop` after `New session`, and the README demo shows the new features. A running session with no transcript yet (a new background session waits for its first prompt) is now listed too, built from its pid file.

## [0.3.0] - 2026-11-18

A better new-session dialog.

### Changed
- The `n` dialog is now a small folder browser. The list follows the path field: delete back to a `/` to see the neighbouring folders, type letters to filter with fuzzy matching (the matched letters are highlighted), `Tab` (or `→` at the end of the text) opens a folder, and `Enter` starts `claude` there. On the `..` row, `Enter` goes up. A preview shows the content of the marked folder, its git branch and your past sessions there. With no `/` in the field, the list shows your recent projects.
- Model, permission mode and worktree are chosen with `Ctrl+A`, `Ctrl+S` and `Ctrl+D` (next to each other, for one hand). `Ctrl+A` opens a fuzzy model list: `default`, the aliases (`fable`, `opus`, `sonnet`, `haiku`), the models found in your sessions, and the new `models` list in the config. The choices are remembered for the next dialog.
- The demo in the README now shows the new-session dialog.

## [0.2.0] - 2026-11-18

See every running Claude Code process and its live status, stop it safely, and start a new session from the dashboard.

### Added
- `scripts/install.sh`: installs into a private virtual environment and adds the commands `agents-farm` and the short name `af`. It checks for name collisions first (other programs on `PATH`, shell aliases and functions) and never overwrites files it did not create. Options: `--name`, `--no-alias`, `--dry-run`, `--uninstall`, `--from-git`, `--ref`, `--editable`.
- `agents-farm --version`.
- PID column in the agent list, and a `PROC` line in the details (PID, Desktop or CLI, version, busy or idle). Data comes from `~/.claude/sessions`. A PID is shown only if the process runs and its start time matches the file (protection against PID reuse). `p` copies the PID. `status --json` has `pid` and `entrypoint`.
- Stop an agent's process with `x`. It asks first (the default answer is No), sends SIGTERM, and asks again before SIGKILL if the process does not stop in 3 s. Before every signal the target is checked again: same session in the pid file, matching process start time (a reused PID is refused), same user, a `claude` process (not the Desktop `disclaimer` wrapper), and not agents-farm or its parents. Desktop and CLI sessions get their own warnings, and a stronger one for `busy` and `waiting` agents. Every attempt is written to `~/.agents-farm/actions.log`. In `--demo` mode no signal is sent. `allow_kill` in the config turns the key off.
- Start a new `claude` session with `n`, in the same terminal. A dialog asks for the folder, the model, the permission mode and the worktree option, and checks them before anything starts. Arguments are passed as a list (no shell), and modes that skip permission checks are not offered. When you leave `claude`, the dashboard comes back and selects the new session. Config: `claude_bin`, `claude_args`, `claude_env`, `new_model`.
- Live status from the process files: the agent status now comes from the `status` field (`idle`, `busy`, `waiting`) of `~/.claude/sessions/<pid>.json`. The exact `? waiting` works with no hooks installed, and about 6 seconds sooner than the notification hook. A hook only adds the text of the request. A `busy` agent is no longer shown as stalled after 90 s: it is shown as stalled only after 10 minutes with no new output (`busy_stalled_s`). A waiting agent stays `waiting` however long it waits. The top bar shows `live ✓` and/or `hooks ✓`.
- Fuzzy search: `apirf` finds `api-refactor`. Results are sorted by match quality, and the matched letters are highlighted. Filters `status:`, `model:`, `project:` still work and can be mixed with fuzzy words.

### Changed
- The list panel is wider (68 columns) to fit the PID column, and the single-panel layout starts below 112 columns.
- An incomplete filter such as `status:` is ignored while you type, instead of hiding every agent.
- The installer hint no longer says that hooks are needed for the `waiting` status.
- CI uses newer versions of the GitHub Actions (checkout, setup-python, gitleaks, CodeQL), still pinned to full commit SHAs.

### Fixed
- No `NoMatches` error from the spinner or the data refresh while the app closes.

### Security
- Control characters are now removed with a translate table instead of a wide regex range (found by CodeQL). The result is the same.

### Known limits
- Usage limits are still an estimate. Real plan limits are planned: [#11](https://github.com/mythes/agents-farm/issues/11).
- You cannot resume a session from the dashboard yet ([#10](https://github.com/mythes/agents-farm/issues/10)).
- The `n` key is tested by hand only in the Claude app terminal. iTerm2 and Terminal.app are not tested yet.

## [0.1.0] - 2026-11-18

First release. A terminal dashboard for Claude Code agents.

### Added
- Textual dashboard with an agent list, a details panel and a limits bar.
- Status symbols and colours (`?` waits for you, `!` error, `●` running, `◐` thinking, `⏸` stalled, `✓` done), with the most urgent agents on top.
- Details with Context, Activity and Plan sections, and a full-screen zoom.
- Filter (`/`) with `status:`, `model:` and `project:` words.
- Notifications and a bell when an agent waits for you, fails, or a limit goes above 90%.
- Hook support (`agents-farm hook`, `agents-farm hooks-snippet`) for an exact "waiting" status.
- `agents-farm status` (one line) and `agents-farm status --json`.
- `--demo` mode with fake data, and a demo recording in the README.
- Per-model usage in the 5-hour window (an estimate) and a configurable context window.
- Keys to copy the `claude --resume` command (`y`) and to open the full log in `$PAGER` (`o`).

### Security
- Text from transcripts and hooks is cleaned of terminal control characters, and never parsed as markup.
- The hook event file is private (`0600`), and only transcripts inside `~/.claude/projects` are opened.
- CI runs tests, bandit, pip-audit and gitleaks. Dependabot and CodeQL are configured. See [SECURITY.md](SECURITY.md).

### Known limits
- Usage limits are an estimate. Real plan limits (5-hour and weekly) are planned: [#11](https://github.com/mythes/agents-farm/issues/11).
- There is no PID column, kill, start or resume yet. See the [backlog](docs/backlog.md).

[Unreleased]: https://github.com/mythes/agents-farm/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/mythes/agents-farm/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/mythes/agents-farm/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/mythes/agents-farm/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/mythes/agents-farm/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/mythes/agents-farm/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mythes/agents-farm/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mythes/agents-farm/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mythes/agents-farm/releases/tag/v0.1.0
