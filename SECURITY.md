# Security

agents-farm is a **local, read-only** observer. It reads Claude Code transcripts (`~/.claude/projects`) and hook events (`~/.agents-farm/events.jsonl`). It makes no network connections and never writes to Claude Code's data.

## Report a problem

Please do not open a public issue for a security problem. Use GitHub's private reporting: **Security → Report a vulnerability** on the repository page. If you do not see that button, open an issue that asks for a private contact and gives no details.

## Trust model

Everything read from transcripts and hook payloads is **untrusted**. It can contain text that came from web pages, repositories or tool output (prompt injection). The code uses it as data only.

| Risk | How we handle it |
|---|---|
| Terminal escape injection (change the title, write to the clipboard with OSC 52, clear the screen, bidi spoofing) | `sanitize()` removes control and bidi characters when data is read (`model.py`) |
| Textual or Rich markup injection (`[@click=…]`, `[link=…]`) in titles and toasts | `notify(..., markup=False)` and `escape()` for border titles. Table and detail cells are `rich.Text`, never parsed as markup |
| Shell injection through the copied `claude --resume` command | The session id and the working directory are quoted with `shlex.quote` |
| A fake or broken process file in `~/.claude/sessions` | Files are validated (the file name must match the pid, the session id has a strict pattern, size is limited), text is cleaned, and a PID counts only if the process start time matches the file. A reused PID is rejected |
| Stopping the wrong process with the `x` key (a reused PID, a parent process, another user's process, the Desktop wrapper) | The key always asks first, and only `y` confirms. Before each signal the target is checked again: the pid file names the same session, the process start time matches the file, the process belongs to you, it is `claude` and not `disclaimer`, and it is not agents-farm or one of its parents. Only SIGTERM and SIGKILL are used, arguments are never passed through a shell, and every attempt is logged in `~/.agents-farm/actions.log` (`0600`) |
| A hook event that points the reader to any file | A transcript path from a hook must resolve (symlinks too) inside `~/.claude/projects` and end with `.jsonl` |
| Event log readable by other local users | Directory `0700`, file `0600`, fields have a maximum length |
| A hook that breaks the agent | The handler swallows all errors, always exits with 0, and has a 5-second timeout |
| Running out of memory on huge logs | Files are read in 8 MB chunks. Very long lines are dropped |
| `$PAGER` for the `o` key | It runs without a shell. The temporary log file is `0600` and is removed afterwards |

## Known limits

- `~/.agents-farm/events.jsonl` only grows and is not rotated. Delete it from time to time.
- The `o` log writes prompt text to a temporary file for a short time (owner only, deleted on exit).
- Anyone who can already write to your home directory can send fake events. They can only change statuses. There is no way to run code.
- The `x` key sends a signal only to a process that matches its pid file. It cannot protect you from stopping a session whose work you wanted to keep: that is what the confirmation and the red warning are for.
- The `a`, `x` and `Ctrl+B` keys for background sessions only run `claude attach`, `claude stop` and `claude --bg`, with an id of exactly 8 hex characters (taken from the session id). agents-farm never types into another terminal and sends no signal for these. `claude` may ask for folder trust: agents-farm never answers that for you.
- The `n` key starts `claude` with arguments you choose, in a folder you choose. `claude_args` and `claude_env` come from your own config file and are passed on as they are. If someone can edit that file, they can already run code as you.
- `~/.agents-farm/actions.log` only grows and is not rotated.
- Usage limits are estimates, not data from Anthropic.

## Automated checks

| Check | Where | What it finds |
|---|---|---|
| `pytest` (`tests/test_security.py`, `tests/test_repo_hygiene.py`) | CI, every push and pull request | Escape and markup injection, unsafe file access, personal data in files, unpinned actions |
| `bandit -r agents_farm` | CI | Common insecure Python patterns |
| `pip-audit .` | CI | Dependencies with known vulnerabilities |
| gitleaks | CI | Secrets (tokens, keys) in the code and in the whole git history |
| Dependabot | Weekly pull requests | Outdated Python dependencies and outdated GitHub Actions |
| CodeQL (`security-extended` queries) | CI, public repository only | Deeper code analysis. Code scanning is free for public repositories. For a private one it needs GitHub Advanced Security, so the job is skipped |

Workflows use least-privilege `permissions`, and every action is pinned to a full commit SHA (a test checks this). Dependabot keeps the SHAs up to date.

Run the local checks yourself:

```bash
pip install -e '.[dev]'
scripts/check.sh          # tests + bandit + whitespace
pip-audit .               # needs network access
```
