"""Aggregates transcripts + hook events into a Snapshot for the UI."""

from __future__ import annotations

import copy
import glob
import os
import time
from datetime import timedelta
from typing import Dict, List, Optional

from .config import CLAUDE_PROJECTS, load_config
from .events import EventReader, HookState
from .limits import compute_limits
from .model import Agent, Snapshot, Status, utcnow
from .transcripts import TranscriptReader, project_from_dir

DISCOVER_EVERY_S = 10


class Store:
    def __init__(self, root: str = CLAUDE_PROJECTS, since_hours: Optional[float] = None, cfg: Optional[dict] = None):
        self.root = root
        self.cfg = cfg or load_config()
        self.since = timedelta(hours=float(since_hours or self.cfg["since_hours"]))
        self.readers: Dict[str, TranscriptReader] = {}
        self.events = EventReader()
        self._last_discover: Optional[float] = None

    # ---------------------------------------------------------------- discovery

    def _discover(self) -> None:
        cutoff = time.time() - self.since.total_seconds()
        patterns = [
            os.path.join(self.root, "*", "*.jsonl"),
            os.path.join(self.root, "*", "*", "subagents", "*.jsonl"),
        ]
        for pattern in patterns:
            for path in glob.glob(pattern):
                if path in self.readers:
                    continue
                try:
                    if os.path.getmtime(path) < cutoff:
                        continue
                except OSError:
                    continue
                self._add(path)
        # Sessions that hooks report but that we haven't picked up yet.
        for st in self.events.latest.values():
            p = st.transcript_path
            if p and p not in self.readers and self._inside_root(p):
                self._add(p)

    def _inside_root(self, path: str) -> bool:
        # A hook event is untrusted input: never open files outside ~/.claude/projects.
        try:
            real, root = os.path.realpath(path), os.path.realpath(self.root)
            return real.endswith(".jsonl") and os.path.commonpath([real, root]) == root and os.path.isfile(real)
        except (ValueError, OSError):
            return False

    def _add(self, path: str) -> None:
        parts = path.split(os.sep)
        if parts[-2] == "subagents":
            parent = parts[-3]
            agent_id = f"{parent}/{os.path.splitext(parts[-1])[0]}"
            project_dir = parts[-4]
        else:
            parent = None
            agent_id = os.path.splitext(parts[-1])[0]
            project_dir = parts[-2]
        agent = Agent(id=agent_id, transcript=path, parent=parent, project=project_from_dir(project_dir))
        self.readers[path] = TranscriptReader(path, agent)

    # ------------------------------------------------------------------ refresh

    def refresh(self) -> Snapshot:
        self.events.poll()
        if self._last_discover is None or time.monotonic() - self._last_discover > DISCOVER_EVERY_S:
            self._discover()
            self._last_discover = time.monotonic()
        for reader in self.readers.values():
            reader.poll()

        now = utcnow()
        agents: List[Agent] = []
        usage = []
        for reader in self.readers.values():
            usage.extend(reader.usage)
            a = reader.agent
            if a.last_activity is None:
                continue
            self._derive(a, now)
            if a.last_activity < now - self.since:
                continue
            agents.append(self._copy(a))

        limits = compute_limits(usage, self.cfg, now)
        return Snapshot(
            agents=agents,
            limits=limits,
            updated=now,
            hooks_active=self.events.active,
            warn=self.cfg["warn"],
            crit=self.cfg["crit"],
        )

    @staticmethod
    def _copy(a: Agent) -> Agent:
        """Detached copy so the UI thread never sees a half-updated agent."""
        c = copy.copy(a)
        c.activity = copy.copy(a.activity)
        c.plan = [copy.copy(p) for p in a.plan]
        c.files = {k: dict(v) for k, v in a.files.items()}
        return c

    # ------------------------------------------------------------------- status

    def _derive(self, a: Agent, now) -> None:
        cfg = self.cfg
        age = (now - a.last_activity).total_seconds()
        stalled_after = float(cfg["stalled_after_s"])
        note = ""

        if a.last_kind == "error":
            st, note = Status.ERROR, a.error_note or "error"
        elif a.pending_tools:
            if age < stalled_after:
                st = Status.RUNNING
            else:
                st = Status.STALLED
                note = "tool pending for a while — maybe waiting for permission (install hooks to know for sure)"
        elif a.last_kind == "assistant" and a.stop_reason in ("end_turn", "stop_sequence", "max_tokens", "refusal"):
            st = Status.DONE
        elif a.last_kind == "user":
            st = Status.THINKING if age < 300 else Status.STALLED
            if st == Status.STALLED:
                note = "no response from the model for 5+ min"
        else:
            st = Status.RUNNING if age < stalled_after else Status.STALLED

        hook: Optional[HookState] = self.events.latest.get(a.session_id) if a.parent is None else None
        a.hooked = hook is not None
        if hook and hook.ts >= a.last_activity - timedelta(seconds=2):
            hst, hnote = hook.status()
            if hst is not None:
                st, note = hst, hnote or note

        if st == Status.DONE and age > float(cfg["done_visible_min"]) * 60:
            st = Status.IDLE
        if st in (Status.STALLED, Status.WAITING) and age > 6 * 3600:
            st, note = Status.IDLE, ""

        a.status, a.status_note = st, note
