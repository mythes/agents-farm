"""The text of the help screen (`?`): keys, and a decoding of every symbol, letter and column. No Textual imports."""

from __future__ import annotations

from typing import List, Tuple

from .model import Status

# (key, what it does), in groups. The keys of the selected session come first, like in the footer.
KEY_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Sessions (a key in grey in the footer does not fit the selected session: press it to see why)", [
        ("n", "new session: pick a folder, then ctrl+a model, ctrl+s mode, ctrl+d worktree, ctrl+b open now / stay here, ctrl+f first prompt, ctrl+e start"),
        ("a", "open a background session here (Ctrl+Z leaves it running)"),
        ("r", "continue a session that has ended (the same session and history)"),
        ("f", "fork a session: a new session with the same history (also for one that runs)"),
        ("x", "stop the session's process (asks first; the default answer is No)"),
        ("p", "copy the PID of the session's process"),
    ]),
    ("Move and read", [
        ("↑↓ / j k", "move between sessions"),
        ("enter / z", "zoom: details on the full screen (esc goes back)"),
        ("1 2 3 / e", "open or close Context / Activity / Plan, or all of them"),
        ("/", "search: letters (apirf finds api-refactor), and filters: status:waiting model:opus project:api"),
        ("h", "show or hide idle sessions (also the ones that have ended) and finished subagents"),
        ("t", "period: sessions of the last 24 hours, 3 days or 7 days. Running sessions are always listed"),
        ("o", "open the full log of the session in $PAGER"),
    ]),
    ("Other", [
        ("ctrl+r", "refresh now (the list also refreshes by itself)"),
        ("?", "this help"),
        ("q", "quit"),
    ]),
]

# What each status symbol means (see docs/rules.md, section 1).
STATUS_HELP = {
    Status.WAITING: "waits for you: a permission request or a question. Always on top",
    Status.ERROR: "the last turn failed (for example an API error)",
    Status.RUNNING: "working: it runs a tool or writes an answer",
    Status.THINKING: "got your prompt and is thinking",
    Status.STALLED: "busy, but nothing new for 10 minutes: it may be stuck",
    Status.DONE: "finished its answer and waits for your next prompt (shown for 30 minutes)",
    Status.IDLE: "old, or its process has ended. Hidden until you press h",
}

# The columns of the list and the bars at the bottom.
COLUMNS: List[Tuple[str, str]] = [
    ("AGENT", "the title, or your first prompt. └ marks a subagent: it runs inside its parent"),
    ("SRC", "where it was started: B background · T terminal · D Claude Desktop · S SDK. A star (B*) = this agents-farm started it"),
    ("MODEL", "the model of the last answer"),
    ("PID", "process id of the session. — means there is no process: the session has ended"),
    ("TIME", "how long it has been working, or how long ago it stopped"),
    ("CTX", "how full the context window is: green below 70%, orange from 70%, red from 90%"),
    ("LIMITS", "tokens used per model in the current 5-hour window. ↻ is the time to the reset. An estimate, not a number from Anthropic"),
]

TIPS: List[str] = [
    "Every session runs in the background. Ctrl+Z leaves it running and brings you back here; /exit ends it.",
    "Two processes never write to one history: a session that runs can only be forked (f), not continued (r).",
    "The exact rules are on one page: docs/rules.md in the project.",
]
