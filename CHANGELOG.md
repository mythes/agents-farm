# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). While the version is `0.x`, things can change between releases.

## [Unreleased]

### Added
- `scripts/install.sh`: installs into a private virtual environment and adds the commands `agents-farm` and the short name `af`. It checks for name collisions first (other programs on `PATH`, shell aliases and functions) and never overwrites files it did not create. Options: `--name`, `--no-alias`, `--dry-run`, `--uninstall`, `--from-git`, `--ref`, `--editable`.
- `agents-farm --version`.
- PID column in the agent list, and a `PROC` line in the details (PID, Desktop or CLI, version, busy or idle). Data comes from `~/.claude/sessions`. A PID is shown only if the process runs and its start time matches the file (protection against PID reuse). `p` copies the PID. `status --json` has `pid` and `entrypoint`.
- Fuzzy search: `apirf` finds `api-refactor`. Results are sorted by match quality, and the matched letters are highlighted. Filters `status:`, `model:`, `project:` still work and can be mixed with fuzzy words.

### Changed
- The list panel is wider (68 columns) to fit the PID column, and the single-panel layout starts below 112 columns.
- An incomplete filter such as `status:` is ignored while you type, instead of hiding every agent.

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

[0.1.0]: https://github.com/mythes/agents-farm/releases/tag/v0.1.0
