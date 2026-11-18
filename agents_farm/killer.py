"""Stop the process of an agent, with safety checks and a log of every action.

Nothing here runs without the user confirming in the UI. Before any signal, the
target is checked again, because a process id can be reused by another program
between the moment the list was drawn and the moment the user presses `y`:

  1. the pid file still exists and names the same session
  2. the process start time still matches the file (a reused pid is refused)
  3. the process belongs to the current user
  4. it is the `claude` process, not the `disclaimer` wrapper that Desktop puts around it
  5. it is not agents-farm itself or one of its parents (that would close this terminal)

Every attempt is appended to ~/.agents-farm/actions.log (owner-only), also the refused ones.
Only SIGTERM (a normal stop) and SIGKILL (the follow-up if it does not stop) are used.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple

from .config import ACTIONS_LOG
from .registry import START_TOLERANCE_S, LiveSession, load_session_file, process_start_times

TERM_WAIT_S = 3.0        # how long we wait for SIGTERM before offering SIGKILL
KILL_WAIT_S = 2.0
SIGNAL_NAMES = {signal.SIGTERM: "SIGTERM", signal.SIGKILL: "SIGKILL"}


class KillError(Exception):
    """The kill was refused. The message says why, in words for the user."""


@dataclass
class Target:
    pid: int
    session_id: str
    name: str = ""
    entrypoint: str = ""
    status: str = ""          # idle | busy | waiting, as the UI saw it


def _ps_field(field: str, pid: int) -> Optional[str]:
    """One `ps` column of one process, for example _ps_field("uid", 123). No shell is used."""
    try:
        # Fixed program and flags, a numeric pid, no shell: nothing here comes from the user.
        out = subprocess.run(  # nosec
            ["ps", "-o", f"{field}=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5, env=dict(os.environ, LC_ALL="C"),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def process_uid(pid: int) -> Optional[int]:
    out = _ps_field("uid", pid)
    return int(out) if out and out.isdigit() else None


def process_comm(pid: int) -> str:
    return _ps_field("comm", pid) or ""


def process_state(pid: int) -> str:
    """The `ps` state letters, for example 'S' (sleeping) or 'Z' (finished, but not yet collected by its parent)."""
    return _ps_field("stat", pid) or ""


def process_command(pid: int) -> str:
    return _ps_field("command", pid) or ""


def ancestor_pids() -> Set[int]:
    """This process and all its parents: killing any of them would close our own terminal."""
    seen: Set[int] = set()
    pid = os.getpid()
    for _ in range(64):
        seen.add(pid)
        out = _ps_field("ppid", pid)
        if not out or not out.isdigit():
            break
        parent = int(out)
        if parent <= 1 or parent in seen:
            break
        pid = parent
    return seen


def check(target: Target, sessions_dir: Optional[str]) -> LiveSession:
    """Raise KillError unless it is safe to signal this process. Returns the verified session."""
    if not sessions_dir:
        raise KillError("process files are not available, so the process cannot be verified")
    pid = target.pid
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise KillError("invalid process id")
    if pid in ancestor_pids():
        raise KillError("this is the process that runs agents-farm (or one of its parents)")

    session = load_session_file(os.path.join(sessions_dir, f"{pid}.json"))
    if session is None:
        raise KillError("the process file is gone: the session has ended")
    if session.session_id != target.session_id:
        raise KillError("this pid now belongs to another session")
    if session.proc_start is None:
        raise KillError("the process file has no start time, so the process cannot be verified")

    starts = process_start_times([pid])
    if starts is None:
        raise KillError("ps is not available, so the process cannot be verified")
    actual = starts.get(pid)
    if actual is None:
        raise KillError("the process is not running any more (if it shows as <defunct>, its parent has not cleaned up yet)")
    if abs(actual - session.proc_start) > START_TOLERANCE_S:
        raise KillError("this pid was reused by another program")

    if process_uid(pid) != os.getuid():
        raise KillError("the process belongs to another user")
    if os.path.basename(process_comm(pid)) == "disclaimer":
        raise KillError("this is the Desktop wrapper, not the claude process")
    if "claude" not in process_command(pid).lower():
        raise KillError("the process does not look like claude")
    session.verified = True
    return session


def wait_until_gone(session: LiveSession, seconds: float) -> bool:
    """True if this exact process has ended within `seconds`."""
    end = time.monotonic() + seconds
    while True:
        starts = process_start_times([session.pid])
        actual = None if starts is None else starts.get(session.pid)
        if actual is None or session.proc_start is None or abs(actual - session.proc_start) > START_TOLERANCE_S:
            return True
        if process_state(session.pid).startswith("Z"):    # it has ended, only the parent has not collected it yet
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


def log_action(target: Target, sig: signal.Signals, result: str, path: Optional[str] = None) -> None:
    """Append one JSON line to the actions log. Never raises: a log problem must not stop the user."""
    path = path or ACTIONS_LOG
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": "kill", "signal": SIGNAL_NAMES.get(sig, str(sig)), "pid": target.pid,
        "session": target.session_id, "name": target.name[:100], "entrypoint": target.entrypoint,
        "status": target.status, "result": result[:200],
    }
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def kill(target: Target, sig: signal.Signals, sessions_dir: Optional[str], wait_s: float = 0.0,
         log_path: Optional[str] = None) -> bool:
    """Send `sig` to the verified process. Returns True if it has ended after `wait_s` seconds.

    Raises KillError if the kill is refused. Every outcome is written to the actions log.
    """
    if sig not in SIGNAL_NAMES:
        raise KillError("only SIGTERM and SIGKILL are allowed")
    try:
        session = check(target, sessions_dir)
    except KillError as exc:
        log_action(target, sig, f"refused: {exc}", log_path)
        raise
    try:
        os.kill(target.pid, sig)
    except ProcessLookupError:
        log_action(target, sig, "the process had already ended", log_path)
        return True
    except PermissionError:
        log_action(target, sig, "refused by the system: no permission", log_path)
        raise KillError("the system did not allow the signal")
    gone = wait_until_gone(session, wait_s) if wait_s > 0 else False
    log_action(target, sig, "sent, the process ended" if gone else "sent", log_path)
    return gone


def warnings(entrypoint: str, status: str, session_id: str) -> List[Tuple[str, str]]:
    """Lines for the confirmation dialog: (style, text). Text is based on spike S4."""
    lines: List[Tuple[str, str]] = []
    if entrypoint == "claude-desktop":
        lines.append(("", "Claude Desktop will start a new process for this chat when you send the next message. The history is kept."))
    elif entrypoint == "cli":
        lines.append(("", f"This ends the claude session in its terminal. You can continue it later: claude --resume {session_id}"))
    if status == "busy":
        lines.append(("bold red", "The agent is working now: the current turn will be lost."))
    elif status == "waiting":
        lines.append(("bold red", "The agent is waiting for your answer: that question will be lost."))
    return lines
