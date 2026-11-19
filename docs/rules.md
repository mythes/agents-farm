# The rules

One page that says what agents-farm does, and why. The README shows each feature in a short demo, and this page is the exact rule behind it. If the program and this page ever disagree, that is a bug: please open an issue.

Words used everywhere (the same word always means the same thing):

| Word | Meaning |
|---|---|
| **session** | one Claude Code conversation, with a session id and a history (a transcript file) |
| **process** | the running `claude` program of a session. A session that is not running has no process |
| **background session** | a session that Claude Code keeps running in its own service (`claude --bg`), so it survives your terminal |
| **open** | show a session in this terminal (`claude attach`). Opening does not start or stop anything |
| **continue** | start a session that has ended again, with the **same** id and history |
| **fork** | start a **new** session (new id) with the same history. The original is not changed |

## 1. Statuses (the symbol in the list)

The status comes from the first source that knows: the process file (`~/.claude/sessions/<pid>.json`), then hooks (if installed), then a guess from the transcript.

| Symbol | Status | When |
|---|---|---|
| `?` | waiting | the process waits for you (a permission request, a question). Always on top |
| `!` | error | the last turn failed. Stays visible while the process is idle |
| `●` `◐` | running, thinking | the process is busy |
| `⏸` | stalled | the process is busy but has printed nothing for 10 minutes (`busy_stalled_s`). Never used for a session whose process is gone |
| `✓` | done | the process is idle after an answer. Shown for 30 minutes |
| `◌` | idle | older than 30 minutes, **or** the process is gone and the transcript has been quiet for a minute (the session has ended). Hidden until you press `h` |

Without process files (an older Claude Code) the status is only a guess from the transcript, and agents-farm cannot tell whether a session runs.

## 2. What you can do with a session

The footer shows a key in grey when it does not fit the selected session. If you press it anyway, a pop-up says why and which keys to use instead (and you can press one of them there).

| Key | Does | Running in the background | Running in a terminal or Desktop | Ended | Subagent | Nothing selected |
|---|---|---|---|---|---|---|
| `a` | open | ✅ opens it | ❌ it is not a background session | ❌ it is not running | ❌ | ❌ |
| `r` | continue (same session) | ❌ already running: `a` or `f` | ❌ it runs: `f` | ✅ | ❌ | ❌ |
| `f` | fork (new session) | ✅ | ✅ | ✅ | ❌ | ❌ |
| `x` | stop | ✅ `claude stop` | ✅ asks, then SIGTERM | ❌ it is not running | ❌ | ❌ |
| `p` | copy the pid | ✅ | ✅ | ❌ | ❌ | ❌ |

`r` and `f` also say no for a session with no history yet, a session whose folder is gone, and (for `r`) a session whose state we cannot tell (an older Claude Code with no process files).

Other keys (`n` new, `/` search, `z` zoom, `e` `h` `o` `?` `q`) work always. `Ctrl+R` refreshes (the list also refreshes every 2 seconds).

## 3. Starting a session (`n`)

- **Every session starts in the background** (`claude --bg`). So it keeps running whatever you do next.
- **Open now: yes** (the default): the session is opened here right away. **`Ctrl+Z` leaves it running** and brings you back to the dashboard. `/exit` ends it.
- **Open now: no** (`Ctrl+B`): the session starts and stays closed. Open it later with `a`.
- **First prompt** (optional, `Ctrl+F`): a multi-line editor. `Ctrl+E` starts from anywhere in the dialog.
- The folder must exist. The model name is checked.
- **Permission modes:** `default`, `acceptEdits`, `auto` (Claude's own classifier decides what is safe, see `claude auto-mode`; some plans or organizations do not have it, and then `claude` says so) and `plan`. Modes that skip permission checks (`bypassPermissions`, `dontAsk`) are never offered.
- **The dialog remembers** the model, mode, worktree and open-now choices of the last session you started, also after a restart (`~/.agents-farm/state.json`, readable only by you; a value that is not valid any more is ignored). The folder and the first prompt are not remembered. `new_model` in the config is the model until you have chosen one.
- A session in `default` mode that stays closed stops at its first permission request. The dialog warns you: use `acceptEdits` or `plan`, or open it and answer.

**When a background session is not possible** (the folder is not trusted yet, an administrator turned background sessions off, or this Claude Code has no `--bg`):

| Open now | What happens |
|---|---|
| yes | a plain `claude` starts in this terminal and agents-farm says why. `Ctrl+Z` leaves it **only if it is idle or has not started yet**: it is ended, and `r` continues it later (the same history), from this or any other agents-farm. If it is busy, `Ctrl+Z` does nothing. `/exit` always ends it |
| no | nothing starts, and the reason is shown |

A timeout or a missing `claude` never starts a second session. With `"use_background": false` in the config, the plain `claude` is always used.

## 4. Leaving a session

| Session | `Ctrl+Z` | `/exit` |
|---|---|---|
| opened (a background session) | back to the dashboard, **keeps running** | ends the session |
| plain `claude` (the fallback above) | back to the dashboard if idle (it ends, `r` continues it); nothing if busy | ends the session |

`Ctrl+C` always goes to `claude`. A background session has no other end than `x` (or `/exit` inside it).

## 5. Continue (`r`) and fork (`f`)

| | Continue (`r`) | Fork (`f`) |
|---|---|---|
| what it is | the **same** session: same id, history, model and mode | a **new** session (new id) with the same history. The original is not changed |
| ended, started in a terminal | ✅ Enter continues | ✅ |
| ended, a Claude Desktop chat | ✅ but the dialog suggests a fork: Enter forks, `y` continues (Desktop starts the chat again on your next message, and then two processes would write to one history) | ✅ |
| running in a terminal or Desktop | ❌ explained, with `f` as the way | ✅ the original keeps running |
| running in the background | ❌ explained, with `a` (open) and `f` | ✅ |
| we cannot tell (no process files) | ❌ explained, with `f` | ✅ |

- **Two processes never write to one history.** So a session that runs is never continued, only forked.
- Both open here and run in the background (`Ctrl+Z` leaves them running). In a folder that is not trusted, or with background sessions off, a plain `claude --resume` runs instead (see section 3).
- The session folder must still exist. A subagent can be neither continued nor forked (use its parent). The saved model and permission mode come back by themselves.
- A fork asks one short question (Enter confirms, Esc cancels).

## 6. Stopping (`x`)

- It always asks, and **the default answer is No** (only `y` confirms).
- A background session is stopped with `claude stop`. The history is kept.
- Any other process gets SIGTERM, and if it is still there after 3 seconds, a second question asks about SIGKILL. Before every signal agents-farm checks that the pid still belongs to that session, to you, and to `claude` (never the Desktop wrapper, agents-farm itself or its parents).
- Every signal attempt, also a refused one, is written to `~/.agents-farm/actions.log`. `"allow_kill": false` turns the key off.

## 7. The SRC column

| Letter | Where the session was started |
|---|---|
| `B` | in the background (`claude --bg`) |
| `T` | in a terminal (the Claude Code CLI) |
| `D` | in Claude Desktop |
| `S` | by the SDK |

A star (`B*`) means that this agents-farm started or continued the session. It is forgotten when you quit. Ended sessions keep their letter (it is read from the transcript).

## 8. What Enter does

| Where | Enter |
|---|---|
| the list | zoom (details full screen) |
| `n` dialog, path field | start in the marked folder (on the `..` row: go up). `Ctrl+E` starts from anywhere |
| `r` dialog | continue (for a Desktop chat: fork) |
| `f` dialog | fork |
| attach hint | open |
| stop dialog | **cancel** (the safe answer) |

## 9. What agents-farm never does

- It never changes your Claude Code files, and it never types into another terminal.
- It never answers a trust question for you.
- It signals a process only when you ask (`x`, or `Ctrl+Z` in a plain session it started itself). See [SECURITY.md](../SECURITY.md).
