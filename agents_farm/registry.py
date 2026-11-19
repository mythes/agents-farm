"""Live Claude Code processes, from ~/.claude/sessions/<pid>.json.

Claude Code writes one small file per running session: pid, session id, working
directory, name, status (idle / busy), entry point (Desktop or CLI), version and the
start time of the process. This is an undocumented format, so every field is
validated and a missing or broken file is skipped without any error.

A file can outlive its process, and a process id can be reused by another program.
So a session counts as running only if a process with that pid exists and its start
time matches `procStart` from the file. `ps` prints the time in UTC when TZ=UTC.
"""

from __future__ import annotations

import calendar
import glob
import json
import os
import re
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .model import sanitize

MAX_FILE_BYTES = 64 * 1024
START_TOLERANCE_S = 2.0           # allowed difference between the file and `ps`
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
ENTRYPOINT_LABELS = {"claude-desktop": "Desktop", "cli": "CLI"}


@dataclass
class LiveSession:
    pid: int
    session_id: str
    cwd: str = ""
    name: str = ""
    status: str = ""                 # idle | busy (the only values seen so far)
    entrypoint: str = ""
    kind: str = ""
    version: str = ""
    started_at: Optional[datetime] = None
    proc_start: Optional[float] = None   # epoch seconds, from procStart in the file
    verified: bool = False           # process start time matched the file

    @property
    def entry_label(self) -> str:
        return ENTRYPOINT_LABELS.get(self.entrypoint, self.entrypoint or "?")


def _parse_lstart(text: str) -> Optional[float]:
    """'Tue Nov 17 15:24:40 2026' (UTC) -> epoch seconds."""
    try:
        return float(calendar.timegm(time.strptime(text.strip(), "%a %b %d %H:%M:%S %Y")))
    except (ValueError, OverflowError):
        return None


def process_start_times(pids: List[int]) -> Optional[Dict[int, float]]:
    """Start time (epoch, UTC) of each running pid. None if `ps` cannot be used."""
    if not pids:
        return {}
    env = dict(os.environ, TZ="UTC", LC_ALL="C")
    try:
        # Fixed command; the pids are integers read from validated files.
        out = subprocess.run(  # nosec B603 B607
            ["ps", "-o", "pid=,stat=,lstart=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, env=env, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    result: Dict[int, float] = {}
    for line in out.splitlines():
        head, _, rest = line.strip().partition(" ")
        state, _, rest = rest.strip().partition(" ")
        if head.isdigit() and not state.startswith("Z"):      # a zombie has ended: it only waits for its parent
            started = _parse_lstart(rest)
            if started is not None:
                result[int(head)] = started
    return result


def _text(value, limit: int) -> str:
    return sanitize(value)[:limit] if isinstance(value, str) else ""


def load_session_file(path: str) -> Optional[LiveSession]:
    """Read and validate one pid file. Returns None for anything unexpected."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return None
    if os.path.basename(path) != f"{pid}.json":      # the file name must match the pid inside
        return None
    sid = data.get("sessionId")
    if not isinstance(sid, str) or not SESSION_ID_RE.match(sid):
        return None

    started_at = None
    ms = data.get("startedAt")
    if isinstance(ms, (int, float)) and not isinstance(ms, bool) and 0 < ms < 4_102_444_800_000:
        started_at = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    proc_start = _parse_lstart(data["procStart"]) if isinstance(data.get("procStart"), str) else None

    return LiveSession(
        pid=pid, session_id=sid,
        cwd=_text(data.get("cwd"), 1024), name=_text(data.get("name"), 200),
        status=_text(data.get("status"), 32), entrypoint=_text(data.get("entrypoint"), 64),
        kind=_text(data.get("kind"), 32), version=_text(data.get("version"), 32),
        started_at=started_at, proc_start=proc_start,
    )


class Registry:
    def __init__(self, root: Optional[str]):
        self.root = root

    @property
    def available(self) -> bool:
        """True if this Claude Code version writes pid files at all."""
        return bool(self.root) and os.path.isdir(self.root)

    def scan(self) -> Dict[str, LiveSession]:
        """Running sessions by session id."""
        if not self.available:
            return {}
        sessions = [s for s in (load_session_file(p) for p in glob.glob(os.path.join(self.root, "*.json"))) if s]
        if not sessions:
            return {}
        starts = process_start_times([s.pid for s in sessions])

        running: Dict[str, LiveSession] = {}
        for s in sessions:
            if starts is None:                       # no `ps`: fall back to a plain liveness check
                if not _pid_exists(s.pid):
                    continue
            else:
                actual = starts.get(s.pid)
                if actual is None:
                    continue                         # no such process: the file is stale
                if s.proc_start is not None:
                    if abs(actual - s.proc_start) > START_TOLERANCE_S:
                        continue                     # the pid belongs to another program now
                    s.verified = True
            current = running.get(s.session_id)
            if current is None or (s.verified, s.started_at or _EPOCH) > (current.verified, current.started_at or _EPOCH):
                running[s.session_id] = s
        return running


_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _pid_exists(pid: int) -> bool:
    """Plain liveness check, used only when `ps` is missing. It cannot tell a zombie (`<defunct>`) from a live process."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
