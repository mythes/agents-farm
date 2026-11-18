# Agents Farm: terminal UI design and sketches

Goal: on one screen, see **which agent does what**, the **task context** (you can open it), and **how much of your model limits is left**. Then you can see in time that an agent is stuck, is waiting for you, or that a model is close to its limit.

We built layout **A**. The other layouts are kept here as ideas. The sketches are early: some keys in them (for example `p pause`) were never built. For the real keys, see the README.

---

## 0. Shared parts (all layouts)

### Agent status: colour + symbol (never colour alone)

| Symbol | Status | Colour | Meaning |
|---|---|---|---|
| `●` | running | green | working, fresh output |
| `◐` | thinking | blue (animated spinner `⠋⠙⠹⠸`) | waiting for the model |
| `?` | waiting | **yellow, bold** | waits for you (permission or question). The most important status |
| `!` | error | red | failed or out of retries |
| `◌` | idle | grey | no task |
| `✓` | done | soft green | finished, needs a look |
| `⏸` | stalled | orange | a live process that printed nothing for a long time (10 min by default); never used for a session whose process has ended |

### Limit bar per model

```
opus-5.5    ████████████░░░░░░░░  62%  ↻ 1h12m   tok 1.2M/2M   $4.10
sonnet-5.5  ███████████████████░  94%  ↻ 0h08m   ⚠ limit soon
haiku-5.5   ███░░░░░░░░░░░░░░░░░  14%  ↻ 3h40m
```

Thresholds: `<70%` green · `70–90%` yellow · `>90%` red + `⚠`, and the row moves up to the status bar.
We show the **time to reset** (`↻`), not only the percent, because what you do depends on it.
Optional forecast: "at this speed the limit ends in about 25 min".

> Note: later research showed that real plans use one 5-hour window and one weekly window, not a budget per model. See [backlog.md](backlog.md), task T6.

### Task highlights

- A task in `waiting` is always at the top of the list, with a yellow row.
- Filter search `/` shows matches in bold.
- Fresh changes (last 5 s) flash in reverse colours and then fade.

---

## Layout A: "Dashboard" (3 panels, like k9s / lazygit) ⭐ built

The agent list is on the left, details of the chosen agent on the right, limits at the bottom. You move with `j/k`.

```
┌ agents-farm ─────────────────────────────────── 4 running · 1 waiting · 1 err ┐
│ AGENTS                         │ ● api-refactor            opus-5.5   12m34s  │
│                                │──────────────────────────────────────────────│
│ ? docs-writer      sonnet  2m  │ TASK  Move auth into its own module          │
│ ● api-refactor     opus   12m ◀│ REPO  ~/work/backend   branch feat/auth      │
│ ◐ test-fixer       sonnet  4m  │ CTX   ███████████░░░░ 71%  142k/200k tok     │
│ ● migrations       haiku   1m  │                                              │
│ ! deploy-check     sonnet  ERR │ ▸ Context (3 files, 2 messages)        [enter]│
│ ✓ lint-pass        haiku  done │ ▾ Activity                                   │
│ ◌ spare-1          —        —  │   12:41:02  Read  src/auth/session.ts        │
│                                │   12:41:09  Edit  src/auth/index.ts  +42 −8  │
│                                │   12:41:30  Bash  npm test  ⠹ running…       │
│                                │ ▸ Plan  3/5 steps                            │
├────────────────────────────────┴──────────────────────────────────────────────┤
│ LIMITS  opus ████████░░ 62% ↻1h12m │ sonnet █████████▉ 94% ⚠ ↻8m │ haiku █░ 14%│
├───────────────────────────────────────────────────────────────────────────────┤
│ j/k move  enter expand  a attach  p pause  x kill  / filter  ? help    q quit │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Opened context** (`enter` on a section, or `z` to zoom to the full screen):

```
┌ api-refactor › Context ─────────────────────────────────────── esc back ─────┐
│ ▾ Prompt                                                                     │
│   Move the session logic from src/server.ts into src/auth/, keep the public  │
│   API. Do not touch the migrations.                                          │
│ ▾ Files in context (3)                                                       │
│   src/server.ts          412 ln   18k tok                                    │
│   src/auth/session.ts    120 ln    5k tok                                    │
│   src/auth/index.ts       64 ln    2k tok                                    │
│ ▸ Conversation (14 msgs)                                                     │
│ ▸ Last diff  +42 −8                                                          │
│ ▾ Plan                                                                       │
│   ✓ Find all uses of session                                                 │
│   ✓ Create src/auth/                                                         │
│   ● Move the code  ← now                                                     │
│   ○ Update the imports                                                       │
│   ○ Run the tests                                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ ↑↓ scroll  space toggle  E expand all  y copy  o open in $EDITOR   esc back  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Good:** everything on one screen, a familiar model (k9s, lazygit), works for about 20 agents.
**Not so good:** on a narrow terminal (<100 columns) the right panel must be hidden.

---

## Layout B: "Kanban" (columns by status)

Good when agents are a pipeline of tasks and the flow matters: what is queued, what runs, what waits for review.

```
┌ agents-farm ── board ─────────────────────────────────────────────────────────┐
│ QUEUE (3)          │ RUNNING (3)         │ NEEDS YOU (2)      │ DONE (5)       │
│────────────────────│─────────────────────│────────────────────│────────────────│
│ ○ add-metrics      │ ● api-refactor      │ ? docs-writer      │ ✓ lint-pass    │
│   sonnet           │   opus · 12m · 71%  │   "Can I delete    │ ✓ bump-deps    │
│ ○ i18n-ua          │ ◐ test-fixer        │    old/README?"    │ ✓ typo-fix     │
│   haiku            │   sonnet · 4m       │ ! deploy-check     │ ✓ ci-cache     │
│ ○ perf-audit       │ ● migrations        │   exit 1 · retry?  │ ✓ readme       │
│   opus             │   haiku · 1m        │                    │                │
├────────────────────┴─────────────────────┴────────────────────┴────────────────┤
│ opus 62% ↻1h12m   sonnet 94% ⚠ ↻8m   haiku 14%            h/l column  j/k card │
└────────────────────────────────────────────────────────────────────────────────┘
```

`enter` on a card opens the same detail screen as in layout A.

**Good:** you see the bottleneck and everything that waits for you.
**Not so good:** a card shows less detail, and it is bad for more than 30 agents.

---

## Layout C: "Top + Feed" (like htop + a live log)

A compact table on top and a shared event feed below. For people who like to watch it work.

```
 agents-farm   opus ████████░░ 62% ↻1h12m  sonnet █████████▉ 94%⚠  haiku █░ 14%
 ─────────────────────────────────────────────────────────────────────────────
  ST  AGENT          MODEL    TIME   CTX   TOKENS  COST   TASK
  ?   docs-writer    sonnet   2m     34%   48k     $0.12  Update the README
▶ ●   api-refactor   opus     12m    71%   142k    $2.30  Move auth to a module
  ◐   test-fixer     sonnet   4m     22%   31k     $0.09  Fix the flaky test
  ●   migrations     haiku    1m     8%    6k      $0.01  Add an index
  !   deploy-check   sonnet   ERR    40%   52k     $0.14  Check the deploy
 ─────────────────────────────────────────────────────────────────────────────
  FEED  [all ▾]                                                     ⏸ space
  12:41:30  api-refactor   Bash  npm test
  12:41:28  docs-writer    ?     Asks permission: delete old/README.md
  12:41:09  api-refactor   Edit  src/auth/index.ts +42 −8
  12:40:55  deploy-check   !     exit 1: connection refused :5432
 ─────────────────────────────────────────────────────────────────────────────
  F1 help  F3 search  F5 tree  F6 sort  F9 kill  tab focus feed  enter detail
```

**Good:** very dense, sortable columns, everything visible.
**Not so good:** noisy, and the feed moves fast (so there is a pause with `space`).

---

## Layout D: minimal (status line / tmux)

Not a separate app. It is one line for tmux or the Claude Code status line, and `agents-farm status` for more detail.

```
 ●3 ?1 !1 │ opus 62% │ sonnet 94%⚠ 8m │ haiku 14%
```

Useful as an extra to A, B or C, not instead of them. This is implemented as `agents-farm status`.

---

## Terminal UX practices we follow

1. **Colour + symbol + text.** Never show a state with colour only (colour blindness, mono terminals). Respect `NO_COLOR`.
2. **Most important first.** "Waits for you" and errors sort first and are repeated in the header (`1 waiting`).
3. **Vim keys and arrows.** `?` always shows help. The footer shows 5–7 key hints for the current context.
4. **Progressive disclosure.** List → details → zoom. `enter` goes deeper, `esc` goes back, `space` closes or opens, `e` toggles all.
5. **Adaptive layout.** Under 100 columns: one panel (list or details). Wider: two panels. Handle `SIGWINCH`.
6. **No flicker.** Update only what changed, at most 10 fps, spinner only on active rows. The cursor does not jump when the order changes (we track the agent id).
7. **Search and filter `/`.** Highlight matches. Filters like `status:waiting model:opus`.
8. **Ask before danger.** `x kill` asks `Kill api-refactor? y/N`. Offer undo where it is possible.
9. **Reach outside the app.** `y` copies (OSC 52, works over SSH), `o` opens a file or log in `$PAGER`, `a` attaches to the agent session.
10. **Notifications.** A bell `\a` or an OS notification when an agent changes to `waiting` or a limit goes above 90%. Can be turned off in the config.
11. **Unicode with ASCII fallback** (`[#####-----]`) for old terminals.
12. **Non-interactive mode.** `agents-farm status --json` for scripts and status lines.

---

## Stack

| Option | Good | Not so good |
|---|---|---|
| **Python + Textual** ⭐ chosen | Fastest to prototype, CSS-like styles, ready widgets (Tree, DataTable, Collapsible) | Needs a Python runtime |
| Go + Bubble Tea + Lip Gloss | One binary, fast, good components | More layout code |
| Rust + ratatui | Maximum speed | Slowest to develop |
| TypeScript + Ink | React model, easy for a JS team | Weaker with long lists |

## Data source

How we get the agent state decides the architecture. We chose to **observe Claude Code sessions**: local transcripts in `~/.claude/projects/*` plus hooks that write events to a file. A custom orchestrator (agents write events to SQLite or HTTP) is a possible later step.
