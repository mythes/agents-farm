"""Pure rendering helpers (Rich Text) — no Textual dependency, easy to test."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List, Optional

from rich.text import Text

from .model import ACTIVE, STATUS_STYLE, Agent, LimitInfo, Snapshot, Status
from .registry import ENTRYPOINT_LABELS

SPINNER = "◐◓◑◒"
NAME_WIDTH = 20                           # width of the AGENT column in the list
TOOL_COLORS = {
    "Read": "cyan", "Grep": "cyan", "Glob": "cyan",
    "Edit": "yellow", "Write": "yellow", "MultiEdit": "yellow", "NotebookEdit": "yellow",
    "Bash": "magenta", "Agent": "blue", "Task": "blue",
    "WebFetch": "bright_blue", "WebSearch": "bright_blue",
    "you": "bold bright_white", "say": "grey70",
}


def fmt_dur(seconds: float) -> str:
    s = int(max(seconds, 0))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s" if m < 10 else f"{m}m"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h{m:02d}m"
    return f"{h // 24}d"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def short_model(model: str) -> str:
    # claude-opus-5-5 -> opus-5.5 ; claude-3-5-haiku-20241022 -> haiku-3.5
    m = (model or "").lower().replace("claude-", "")
    m = re.sub(r"-\d{8}$", "", m)
    m = re.sub(r"\[.*\]$", "", m)
    match = re.match(r"([a-z]+)-(\d+)(?:-(\d+))?$", m)
    if match:
        fam, a, b = match.groups()
        return f"{fam}-{a}.{b}" if b else f"{fam}-{a}"
    match = re.match(r"(\d+)-(\d+)-([a-z]+)$", m)
    if match:
        a, b, fam = match.groups()
        return f"{fam}-{a}.{b}"
    return m or "—"


def context_window(a: Agent, cfg_windows: Optional[dict] = None) -> int:
    windows = cfg_windows or {"default": 200_000}
    model = a.model or ""
    win = int(windows.get("default", 200_000))
    best = -1
    for key, val in windows.items():  # longest matching substring wins
        if key != "default" and key in model and len(key) > best:
            win, best = int(val), len(key)
    if "[1m]" in model:
        win = max(win, 1_000_000)
    if a.context_tokens > win:  # window is bigger than assumed: never show >100%
        for tier in (200_000, 500_000, 1_000_000, 2_000_000):
            if a.context_tokens <= tier:
                return max(win, tier)
        return a.context_tokens
    return win


def pct_style(p: float, warn: float = 0.7, crit: float = 0.9) -> str:
    if p >= crit:
        return "bold red"
    if p >= warn:
        return "yellow"
    return "green"


def bar(p: float, width: int, style: str) -> Text:
    p = min(max(p, 0.0), 1.0)
    eighths = " ▏▎▍▌▋▊▉█"
    full = int(p * width)
    rem = int((p * width - full) * 8)
    t = Text("█" * full, style=style)
    if full < width:
        t.append(eighths[rem] if rem else "", style=style)
        t.append("░" * (width - full - (1 if rem else 0)), style="grey35")
    return t


def status_cell(a: Agent, frame: int = 0) -> Text:
    sym, style = STATUS_STYLE[a.status]
    if a.status == Status.THINKING:
        sym = SPINNER[frame % len(SPINNER)]
    return Text(f" {sym} ", style=style)


def name_style(a: Agent) -> str:
    return {
        Status.WAITING: "bold yellow",
        Status.ERROR: "bold red",
        Status.STALLED: "dark_orange",
        Status.DONE: "grey70",
        Status.IDLE: "grey50",
    }.get(a.status, "bold")


def elapsed(a: Agent, now: datetime) -> str:
    if a.status in ACTIVE or a.status in (Status.WAITING, Status.STALLED):
        since = a.prompt_ts or a.started or a.last_activity
        return fmt_dur((now - since).total_seconds()) if since else "—"
    if a.last_activity:
        return fmt_dur((now - a.last_activity).total_seconds())
    return "—"


MATCH_STYLE = "bold #000000 on #ffd75f"   # letters found by the search


def entry_label(entrypoint: str) -> str:
    return ENTRYPOINT_LABELS.get(entrypoint, entrypoint or "?")


def pid_cell(a: Agent) -> Text:
    if a.pid:
        return Text(str(a.pid), "grey70" if a.pid_verified else "dark_orange")
    return Text("—", "grey50")


SRC_STYLES = {"B": "bold #5fafd7", "T": "grey70", "D": "magenta", "S": "grey58", "·": "grey42"}


def src_letter(a: Agent) -> str:
    """Where the session was started: B background, T terminal, D Claude Desktop, S SDK."""
    if a.background:
        return "B"
    return {"claude-desktop": "D", "cli": "T", "sdk-cli": "S"}.get(a.entrypoint or a.origin, "·")


def src_cell(a: Agent, mine: bool = False) -> Text:
    """The letter, and a star when this agents-farm started the session."""
    letter = src_letter(a)
    t = Text(letter, SRC_STYLES[letter])
    if mine:
        t.append("*", "bold yellow")
    return t


def row_cells(a: Agent, now: datetime, frame: int, warn: float, crit: float, windows=None, highlight=None, mine: bool = False):
    name = a.name.replace("\n", " ")
    prefix = " └ " if a.parent else ""
    max_len = NAME_WIDTH - len(prefix)
    if len(name) > max_len:
        name = name[: max_len - 1] + "…"
    name_text = Text(name, name_style(a))
    for i in highlight or ():
        if i < len(name_text.plain) - (1 if name.endswith("…") else 0):
            name_text.stylize(MATCH_STYLE, i, i + 1)
    ctx = a.context_tokens / context_window(a, windows) if a.context_tokens else 0
    ctx_cell = Text(f"{ctx:>4.0%}", style=pct_style(ctx, warn, crit)) if a.context_tokens else Text("   —", "grey50")
    return (
        status_cell(a, frame),
        Text(prefix, "grey50") + name_text,
        src_cell(a, mine),
        Text(short_model(a.model), "grey70"),
        pid_cell(a),
        Text(elapsed(a, now), "grey70"),
        ctx_cell,
    )


# --------------------------------------------------------------------- detail


def home_short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def detail_header(a: Agent, now: datetime, warn: float, crit: float, windows=None) -> Text:
    sym, style = STATUS_STYLE[a.status]
    t = Text()
    t.append(f" {sym} ", style=style)
    t.append(f" {a.status.value.upper()} ", style="bold")
    t.append(a.name.splitlines()[0][:80], style="bold")
    when = elapsed(a, now)
    if a.status not in ACTIVE and a.status not in (Status.WAITING, Status.STALLED):
        when += " ago"
    t.append(f"   {short_model(a.model)}   {when}\n", style="grey70")
    if a.status_note:
        t.append("NOTE  ", style="bold " + ("yellow" if a.status == Status.WAITING else "dark_orange"))
        t.append(a.status_note + "\n", style="yellow" if a.status == Status.WAITING else "")
    t.append("TASK  ", style="bold grey62")
    t.append((a.prompt.splitlines()[0] if a.prompt else "—")[:200] + "\n")
    t.append("REPO  ", style="bold grey62")
    t.append(home_short(a.cwd) or a.project)
    if a.branch:
        t.append("   branch ", style="grey62")
        t.append(a.branch, style="magenta")
    t.append("\n")
    if a.live is not None:
        t.append("PROC  ", style="bold grey62")
        if a.pid:
            t.append(f"pid {a.pid}", style="bold")
            t.append(f" · {entry_label(a.entrypoint)}", style="grey70")
            if a.background:
                t.append(" · background", style="bold cyan")
            if a.client_version:
                t.append(f" · v{a.client_version}", style="grey70")
            if a.live_status:
                t.append(f" · {a.live_status}", style="cyan" if a.live_status == "busy" else "grey70")
            if not a.pid_verified:
                t.append(" · not verified", style="dark_orange")
        else:
            t.append("not running", style="grey50")
        t.append("\n")
    win = context_window(a, windows)
    p = a.context_tokens / win if win else 0
    t.append("CTX   ", style="bold grey62")
    t.append_text(bar(p, 20, pct_style(p, warn, crit)))
    t.append(f" {p:>4.0%}  ", style=pct_style(p, warn, crit))
    t.append(f"{fmt_tokens(a.context_tokens)}/{fmt_tokens(win)} tok", style="grey70")
    return t


def detail_context(a: Agent) -> Text:
    t = Text()
    t.append("Latest prompt\n", style="bold underline")
    prompt = a.prompt or "—"
    t.append((prompt[:4000] + ("…" if len(prompt) > 4000 else "")) + "\n\n")
    if a.first_prompt and a.first_prompt != a.prompt:
        t.append("First prompt\n", style="bold underline")
        t.append(a.first_prompt[:1500] + "\n\n", style="grey70")
    t.append(f"Files ({len(a.files)})\n", style="bold underline")
    if not a.files:
        t.append("  —\n", style="grey50")
    for path, c in sorted(a.files.items(), key=lambda kv: -(kv[1]["E"] * 10 + kv[1]["R"]))[:30]:
        t.append(f"  R{c['R']:<2} ", style="cyan" if c["R"] else "grey35")
        t.append(f"E{c['E']:<2} ", style="yellow" if c["E"] else "grey35")
        t.append(path + "\n")
    t.append("\nTokens  ", style="bold")
    t.append(
        f"in {fmt_tokens(a.tokens_in)} · out {fmt_tokens(a.tokens_out)} · "
        f"cache write {fmt_tokens(a.tokens_cache_create)} · cache read {fmt_tokens(a.tokens_cache_read)}\n",
        style="grey70",
    )
    t.append("Session ", style="bold")
    t.append(a.session_id + "\n", style="grey70")
    t.append("Log     ", style="bold")
    t.append(home_short(a.transcript) + "\n", style="grey50")
    t.append("Hooks   ", style="bold")
    t.append("live status ✓" if a.hooked else "not seen — status is inferred from the transcript", style="green" if a.hooked else "grey50")
    return t


def detail_activity(a: Agent, limit: int = 40, wrap: bool = False) -> Text:
    # One event per line; long commands are cut with "…" so columns stay aligned.
    t = Text(no_wrap=not wrap, overflow="fold" if wrap else "ellipsis")
    items = list(a.activity)[-limit:]
    if not items:
        return Text("—", "grey50")
    for item in reversed(items):
        when = item.ts.astimezone().strftime("%H:%M:%S") if item.ts else "--:--:--"
        t.append(f"{when}  ", style="grey50")
        label = {"say": "›", "you": "you"}.get(item.kind, item.kind)
        if label.startswith("mcp__"):
            label = label.split("__")[-1]
        t.append(f"{label[:12]:<12} ", style="bold red" if item.error else TOOL_COLORS.get(item.kind, "blue"))
        t.append(item.detail + "\n", style="red" if item.error else ("grey70" if item.kind == "say" else ""))
    t.rstrip()
    return t


def detail_plan(a: Agent) -> Text:
    if not a.plan:
        return Text("no plan (TodoWrite / update_plan not used)", "grey50")
    t = Text()
    for p in a.plan:
        if p.status == "completed":
            t.append("  ✓ ", style="green")
            t.append(p.content + "\n", style="grey50 strike")
        elif p.status == "in_progress":
            t.append("  ● ", style="bold cyan")
            t.append(p.content, style="bold")
            t.append("  ← now\n", style="cyan")
        else:
            t.append("  ○ ", style="grey50")
            t.append(p.content + "\n")
    t.rstrip()
    return t


def plan_progress(a: Agent) -> str:
    if not a.plan:
        return ""
    done = sum(1 for p in a.plan if p.status == "completed")
    return f"{done}/{len(a.plan)}"


# --------------------------------------------------------------------- limits


def limits_line(limits: List[LimitInfo], now: datetime, width: int, warn: float, crit: float) -> Text:
    t = Text()
    t.append(" LIMITS ", style="bold reverse")
    if not limits:
        t.append("  no usage in the current window", style="grey50")
        return t
    # ~30 cols of text per model besides the bar; drop bars / ETA when narrow.
    per = (width - 10) // max(len(limits), 1)
    bar_w = min(16, per - 30)
    show_bar = bar_w >= 4
    show_eta = per >= 46
    for i, lim in enumerate(limits):
        t.append("  │  " if i else "  ")
        p = lim.pct
        style = pct_style(p, warn, crit) if p is not None else "grey70"
        t.append(lim.family, style="bold")
        t.append(" ")
        if p is not None:
            if show_bar:
                t.append_text(bar(p, bar_w, style))
            t.append(f" {p:>4.0%}", style=style)
            if p >= crit:
                t.append(" ⚠", style="bold red")
        else:
            t.append(fmt_tokens(lim.used) + " tok", style=style)
        if lim.reset_at:
            t.append(f" ↻{fmt_dur((lim.reset_at - now).total_seconds())}", style="grey62")
        eta = lim.eta_minutes
        if show_eta and p is not None and eta is not None and p >= warn and lim.reset_at and now.timestamp() + eta * 60 < lim.reset_at.timestamp():
            t.append(f" ≈out in {fmt_dur(eta * 60)}", style="bold red")
    return t


def top_bar(snap: Snapshot, shown: int, hidden_idle: int) -> Text:
    counts = {}
    for a in snap.agents:
        counts[a.status] = counts.get(a.status, 0) + 1
    t = Text()
    t.append(" agents-farm ", style="bold reverse")
    t.append("  ")
    parts = [
        (Status.WAITING, "waiting", "bold yellow"),
        (Status.ERROR, "error", "bold red"),
        (Status.STALLED, "stalled", "dark_orange"),
        (Status.RUNNING, "running", "green"),
        (Status.THINKING, "thinking", "cyan"),
        (Status.DONE, "done", "grey70"),
    ]
    first = True
    for st, label, style in parts:
        n = counts.get(st, 0)
        if not n:
            continue
        if not first:
            t.append(" · ", style="grey50")
        t.append(f"{STATUS_STYLE[st][0]} {n} {label}", style=style)
        first = False
    if first:
        t.append("no active agents", style="grey50")
    if hidden_idle:
        t.append(f"   +{hidden_idle} idle hidden", style="grey50")
    t.append("   │ ", style="grey35")
    if snap.source in ("demo", "playground"):
        t.append("DEMO data", style="bold magenta")
    elif snap.live_status or snap.hooks_active:
        # Where the exact status comes from: the pid files of the processes, and/or hooks.
        t.append(" ".join(label for label, on in (("live ✓", snap.live_status), ("hooks ✓", snap.hooks_active)) if on), style="green")
    else:
        t.append("status approximated (no pid files, no hooks)", style="grey50")
    t.append(f"   {snap.updated.astimezone().strftime('%H:%M:%S')}", style="grey50")
    return t
