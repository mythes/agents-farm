# Security notes

agents-farm is a **local, read-only** observer. It reads Claude Code transcripts
(`~/.claude/projects`) and hook events (`~/.agents-farm/events.jsonl`); it makes no
network connections and never writes to Claude Code's data.

## Trust model

Everything read from transcripts and hook payloads is **untrusted**: it can contain
text that came from web pages, repositories or tool output (prompt injection).
The code therefore treats it as data only.

| Risk | Mitigation |
|---|---|
| Terminal escape injection (retitle, OSC 52 clipboard write, screen clearing, bidi spoofing) | `sanitize()` strips C0/C1 control and bidi characters at ingest (`model.py`) |
| Textual/Rich markup injection (`[@click=…]`, `[link=…]`) in titles and toasts | `notify(..., markup=False)`, `escape()` on border titles; table/detail cells are `rich.Text`, never parsed as markup |
| Shell injection via the copied `claude --resume` command | session id and cwd are `shlex.quote`d |
| Hook event pointing the reader at an arbitrary file | hook-reported transcript paths must resolve (symlinks included) inside `~/.claude/projects` and end in `.jsonl` |
| Event log readable by other local users | dir `0700`, file `0600`; fields length-capped |
| Hook breaking the agent | handler swallows all errors and always exits 0, 5 s timeout |
| Memory exhaustion on huge logs | files are read in 8 MB chunks; runaway lines are dropped |
| `$PAGER` for the `o` key | executed without a shell; the temp log is `0600` and removed afterwards |

## Known limitations

- `~/.agents-farm/events.jsonl` is append-only and not rotated; delete it occasionally.
- The `o` log temporarily writes prompt text to a temp file (owner-only, deleted on exit).
- Anyone who can already write to your `~` can feed fake events (statuses only; no code execution path).
- Usage limits are estimates, not data from Anthropic.

Tests: `pip install -e '.[dev]' && pytest` (see `tests/test_security.py`). Static scan: `bandit -r agents_farm`.
