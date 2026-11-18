# Security

agents-farm is a **local, read-only** observer. It reads Claude Code transcripts (`~/.claude/projects`) and hook events (`~/.agents-farm/events.jsonl`). It makes no network connections and never writes to Claude Code's data.

## Report a problem

Please do not open a public issue for a security problem. Use GitHub's private reporting: **Security → Report a vulnerability** on the repository page.

## Trust model

Everything read from transcripts and hook payloads is **untrusted**. It can contain text that came from web pages, repositories or tool output (prompt injection). The code uses it as data only.

| Risk | How we handle it |
|---|---|
| Terminal escape injection (change the title, write to the clipboard with OSC 52, clear the screen, bidi spoofing) | `sanitize()` removes control and bidi characters when data is read (`model.py`) |
| Textual or Rich markup injection (`[@click=…]`, `[link=…]`) in titles and toasts | `notify(..., markup=False)` and `escape()` for border titles. Table and detail cells are `rich.Text`, never parsed as markup |
| Shell injection through the copied `claude --resume` command | The session id and the working directory are quoted with `shlex.quote` |
| A hook event that points the reader to any file | A transcript path from a hook must resolve (symlinks too) inside `~/.claude/projects` and end with `.jsonl` |
| Event log readable by other local users | Directory `0700`, file `0600`, fields have a maximum length |
| A hook that breaks the agent | The handler swallows all errors, always exits with 0, and has a 5-second timeout |
| Running out of memory on huge logs | Files are read in 8 MB chunks. Very long lines are dropped |
| `$PAGER` for the `o` key | It runs without a shell. The temporary log file is `0600` and is removed afterwards |

## Known limits

- `~/.agents-farm/events.jsonl` only grows and is not rotated. Delete it from time to time.
- The `o` log writes prompt text to a temporary file for a short time (owner only, deleted on exit).
- Anyone who can already write to your home directory can send fake events. They can only change statuses. There is no way to run code.
- Usage limits are estimates, not data from Anthropic.

## Checks

```bash
pip install -e '.[dev]'
pytest                    # includes tests/test_security.py
bandit -r agents_farm     # static scan
```
