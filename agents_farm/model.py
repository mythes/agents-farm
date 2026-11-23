"""Core data types shared by the data layer and the UI."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, Dict, List, Optional


# Characters removed from untrusted text. Built from numeric ranges (not a regular
# expression): it is easy to read, and str.translate() is fast on large logs.
_STRIP = {
    code: None
    for code in (
        *range(0x00, 0x09),    # C0 controls, but keep tab (0x09) and newline (0x0A)
        *range(0x0B, 0x20),    # the rest of C0, including ESC (0x1B) and CR
        *range(0x7F, 0xA0),    # DEL and the C1 controls
        *range(0x202A, 0x202F),  # bidi embeddings and overrides
        *range(0x2066, 0x206A),  # bidi isolates
    )
}


def sanitize(value) -> str:
    """Strip terminal control characters (ESC, C1, bidi overrides) from untrusted text.

    Transcripts and hook payloads contain text that may originate from web pages,
    files or tool output. Rendered raw, an ESC sequence could retitle the terminal,
    write to the clipboard (OSC 52) or hide text. Newlines and tabs are kept.
    """
    if value is None:
        return ""
    return str(value).translate(_STRIP)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value) -> Optional[datetime]:
    """Parse Claude Code ISO timestamps ('2026-11-17T15:18:03.123Z')."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Status(str, Enum):
    WAITING = "waiting"
    ERROR = "error"
    RUNNING = "running"
    THINKING = "thinking"
    STALLED = "stalled"
    DONE = "done"
    IDLE = "idle"


# symbol, colour — status is never encoded by colour alone.
STATUS_STYLE = {
    Status.WAITING: ("?", "bold black on yellow"),
    Status.ERROR: ("!", "bold white on red"),
    Status.RUNNING: ("●", "bold green"),
    Status.THINKING: ("◐", "bold cyan"),
    Status.STALLED: ("⏸", "bold dark_orange"),
    Status.DONE: ("✓", "green"),
    Status.IDLE: ("◌", "grey50"),
}

# "Needs you" first, then problems, then live work, then the rest.
STATUS_ORDER = {
    Status.WAITING: 0,
    Status.ERROR: 1,
    Status.STALLED: 2,
    Status.RUNNING: 3,
    Status.THINKING: 3,
    Status.DONE: 4,
    Status.IDLE: 5,
}

ACTIVE = {Status.RUNNING, Status.THINKING}


@dataclass
class ActivityItem:
    ts: Optional[datetime]
    kind: str  # tool name, "say" (assistant text) or "you" (user prompt)
    detail: str
    error: bool = False


@dataclass
class PlanItem:
    content: str
    status: str  # pending | in_progress | completed


@dataclass
class UsageRecord:
    ts: datetime
    model: str
    input: int
    output: int
    cache_create: int
    cache_read: int


@dataclass
class Agent:
    id: str
    transcript: str
    project: str = ""
    cwd: str = ""
    branch: str = ""
    title: str = ""
    model: str = ""
    parent: Optional[str] = None  # session id for subagents
    prompt: str = ""
    prompt_ts: Optional[datetime] = None
    first_prompt: str = ""
    started: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    last_kind: str = ""  # user | assistant | error | handback (a subagent gave its result to the parent)
    stop_reason: Optional[str] = None
    pending_tools: int = 0
    error_note: Optional[str] = None
    context_tokens: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache_read: int = 0
    tokens_cache_create: int = 0
    activity: Deque[ActivityItem] = field(default_factory=lambda: deque(maxlen=200))
    plan: List[PlanItem] = field(default_factory=list)
    files: Dict[str, Dict[str, int]] = field(default_factory=dict)  # path -> {"R": n, "E": n}
    # derived on every refresh
    status: Status = Status.IDLE
    status_note: str = ""
    hooked: bool = False
    # from the live process registry (registry.py)
    live: Optional[bool] = None      # None = unknown (no registry), True/False = process running or not
    pid: Optional[int] = None
    parent_live: Optional[bool] = None   # the same for the parent session of a subagent
    entrypoint: str = ""
    live_status: str = ""
    from_pid_file: bool = False      # no transcript yet: built from the pid file alone
    origin: str = ""                 # entrypoint written in the transcript: known also when the process is gone
    background: bool = False         # started with `claude --bg` (kind "bg" in the pid file)
    client_version: str = ""
    pid_verified: bool = False

    @property
    def name(self) -> str:
        if self.title:
            return self.title
        if self.first_prompt:
            return self.first_prompt.splitlines()[0][:60]
        return self.project or self.id[:8]

    @property
    def session_id(self) -> str:
        return self.parent or self.id


@dataclass
class LimitInfo:
    family: str
    used: int
    limit: int  # 0 = unknown
    reset_at: Optional[datetime]
    rate_per_min: float = 0.0

    @property
    def pct(self) -> Optional[float]:
        if not self.limit:
            return None
        return self.used / self.limit

    @property
    def eta_minutes(self) -> Optional[float]:
        if not self.limit or self.rate_per_min <= 0:
            return None
        left = self.limit - self.used
        return max(left, 0) / self.rate_per_min


@dataclass
class Snapshot:
    agents: List[Agent]
    limits: List[LimitInfo]
    updated: datetime
    hooks_active: bool
    warn: float = 0.7
    crit: float = 0.9
    since_hours: Optional[float] = None   # the period that this list covers
    source: str = "claude-code"
    live_status: bool = False        # True if any agent's status comes from a pid file
