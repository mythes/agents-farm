"""Claude Code hook events: a tiny writer (run by the hook) and a tailing reader.

The hook command receives the event JSON on stdin and appends one compact line
to ~/.agents-farm/events.jsonl. It must be fast and must never fail the agent,
so every error is swallowed and it always exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from .config import EVENTS_KEEP_BYTES, EVENTS_MAX_BYTES, EVENTS_PATH, trim_log
from .model import Status, parse_ts, sanitize, utcnow
from .tail import Tail

HOOK_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "PermissionRequest",
    "Stop",
    "StopFailure",
    "SubagentStop",
    "SessionEnd",
]


def _clip(value, limit: int):
    return value[:limit] if isinstance(value, str) else None


def run_hook() -> None:
    try:
        payload = json.load(sys.stdin)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": _clip(payload.get("hook_event_name"), 64),
            "session_id": _clip(payload.get("session_id"), 128),
            "transcript_path": _clip(payload.get("transcript_path"), 1024),
            "cwd": _clip(payload.get("cwd"), 1024),
            "tool": _clip(payload.get("tool_name"), 128),
            "message": _clip(payload.get("message"), 1000),
            "notification_type": _clip(payload.get("notification_type"), 64),
        }
        directory = os.path.dirname(EVENTS_PATH)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        # Events hold prompts-adjacent data (cwd, permission requests): owner-only.
        fd = os.open(EVENTS_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: v for k, v in event.items() if v is not None}) + "\n")
        trim_log(EVENTS_PATH, EVENTS_MAX_BYTES, EVENTS_KEEP_BYTES)     # the file must not grow for ever
    except Exception:  # noqa: BLE001  # nosec B110
        pass
    sys.exit(0)


@dataclass
class HookState:
    ts: datetime
    event: str
    tool: Optional[str]
    message: Optional[str]
    notification_type: Optional[str]
    transcript_path: Optional[str]

    def status(self) -> Tuple[Optional[Status], str]:
        ev = self.event
        if ev == "Notification":
            msg = self.message or ""
            idle = self.notification_type == "idle_prompt" or "waiting for your input" in msg.lower()
            if idle:
                return Status.DONE, "waiting for your next prompt"
            return Status.WAITING, msg or "needs your attention"
        if ev == "PermissionRequest":
            return Status.WAITING, f"permission: {self.tool or 'tool'}"
        if ev == "StopFailure":
            return Status.ERROR, "turn ended with an API error"
        if ev == "Stop":
            return Status.DONE, ""
        if ev == "SessionEnd":
            return Status.IDLE, "session ended"
        if ev in ("PreToolUse", "PostToolUse"):
            return Status.RUNNING, ""
        if ev == "UserPromptSubmit":
            return Status.THINKING, ""
        return None, ""


class EventReader:
    def __init__(self, path: str = EVENTS_PATH):
        self.path = path
        self._tail = Tail(path)
        self.latest: Dict[str, HookState] = {}
        self.last_event_at: Optional[datetime] = None

    def poll(self) -> None:
        for raw in self._tail.lines():
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            sid, ts = d.get("session_id"), parse_ts(d.get("ts"))
            if not isinstance(sid, str) or not sid or not ts or not isinstance(d.get("event"), str):
                continue
            if d["event"] == "SubagentStop":
                continue  # the parent keeps running
            self.latest[sid] = HookState(
                ts, sanitize(d["event"]), sanitize(d.get("tool")) or None, sanitize(d.get("message")) or None,
                sanitize(d.get("notification_type")) or None, d.get("transcript_path") if isinstance(d.get("transcript_path"), str) else None,
            )
            if self.last_event_at is None or ts > self.last_event_at:
                self.last_event_at = ts

    @property
    def active(self) -> bool:
        """Hooks are considered installed if any event arrived in the last day."""
        return bool(self.last_event_at and utcnow() - self.last_event_at < timedelta(days=1))
