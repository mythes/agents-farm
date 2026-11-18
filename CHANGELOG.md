# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). While the version is `0.x`, things can change between releases.

## [Unreleased]

### Changed
- The `n` dialog is now a small folder browser. The list follows the path field: delete back to a `/` to see the neighbouring folders, type letters to filter with fuzzy matching (the matched letters are highlighted), `Tab` (or `→` at the end of the text) opens a folder, and `Enter` starts `claude` there. On the `..` row, `Enter` goes up. A preview shows the content of the marked folder, its git branch and your past sessions there. With no `/` in the field, the list shows your recent projects.
- Model, permission mode and worktree are chosen with `Ctrl+A`, `Ctrl+S` and `Ctrl+D` (next to each other, for one hand). `Ctrl+A` opens a fuzzy model list: `default`, the aliases (`fable`, `opus`, `sonnet`, `haiku`), the models found in your sessions, and the new `models` list in the config. The choices are remembered for the next dialog.

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

[Unreleased]: https://github.com/mythes/agents-farm/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mythes/agents-farm/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mythes/agents-farm/releases/tag/v0.1.0
