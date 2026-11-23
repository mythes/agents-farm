"""Incremental reader for Claude Code transcripts (~/.claude/projects/**/*.jsonl).

Each reader tails one JSONL file from the last byte offset it saw, so a refresh
only parses what was appended since the previous one.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Set

from .model import ActivityItem, Agent, PlanItem, UsageRecord, parse_ts, sanitize
from .tail import Tail

READ_TOOLS = {"Read", "NotebookRead"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
HANDBACK_TOOL = "SubagentHandback"    # a subagent ends with this call: no "end_turn" follows its result
PLAN_TOOLS = {"TodoWrite", "mcp__ccd_turn__update_plan"}


def first_line(text: str, limit: int = 140) -> str:
    for line in sanitize(text).splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def short_path(path: str, cwd: str) -> str:
    path = sanitize(path)
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1 :]
    home = os.path.expanduser("~")
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


def tool_detail(name: str, inp, cwd: str) -> str:
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(inp.get(key), str):
            return short_path(inp[key], cwd)
    for key in ("command", "description", "pattern", "url", "query", "skill", "prompt", "message"):
        val = inp.get(key)
        if isinstance(val, str) and val.strip():
            return first_line(val)
    if name == "mcp__ccd_turn__update_plan":
        return "plan updated"
    return ""


def _result_text(block) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def project_from_dir(dirname: str) -> str:
    # "-Users-me-ai-projects-roblox" -> "roblox" (best effort; cwd overrides it)
    return dirname.rstrip("-").split("-")[-1] or dirname


class TranscriptReader:
    def __init__(self, path: str, agent: Agent):
        self.path = path
        self.agent = agent
        self._tail = Tail(path)
        self._seen_msgs: Set[str] = set()
        self._pending: Dict[str, str] = {}
        self.usage: List[UsageRecord] = []

    def poll(self) -> bool:
        changed = False
        for raw in self._tail.lines():
            changed = True
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if isinstance(entry, dict):
                try:
                    self._apply(entry)
                except (TypeError, AttributeError, KeyError):
                    continue  # one malformed line must not break the whole session
        self.agent.pending_tools = len(self._pending)
        return changed

    # ------------------------------------------------------------------ parsing

    def _apply(self, d: dict) -> None:
        a = self.agent
        kind = d.get("type")
        if kind == "custom-title":
            a.title = sanitize(d.get("customTitle")) or a.title
            return
        if kind == "agent-name" and not a.title:
            a.title = sanitize(d.get("agentName")) or a.title
            return
        if kind not in ("user", "assistant", "system"):
            return

        ts = parse_ts(d.get("timestamp"))
        if not a.origin and isinstance(d.get("entrypoint"), str) and d["entrypoint"]:
            a.origin = sanitize(d["entrypoint"])[:32]        # "cli", "claude-desktop", "sdk-cli": where the session was started
        if isinstance(d.get("cwd"), str) and d["cwd"]:
            a.cwd = sanitize(d["cwd"])
            a.project = os.path.basename(a.cwd.rstrip("/")) or a.project
        if isinstance(d.get("gitBranch"), str) and d["gitBranch"]:
            a.branch = sanitize(d["gitBranch"])
        if ts:
            if a.started is None:
                a.started = ts
            if a.last_activity is None or ts > a.last_activity:
                a.last_activity = ts

        if kind == "system":
            if d.get("level") == "error":
                a.last_kind = "error"
                a.error_note = first_line(str(d.get("content") or "error"), 200)
            return

        msg = d.get("message") or {}
        content = msg.get("content")

        if kind == "user":
            if d.get("isMeta"):
                return
            handed_back = False
            if isinstance(content, str):
                self._prompt(content, ts)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        name = self._pending.pop(block.get("tool_use_id"), None)
                        if block.get("is_error"):
                            a.activity.append(
                                ActivityItem(ts, name or "tool", first_line(_result_text(block)) or "error", True)
                            )
                        elif name == HANDBACK_TOOL:
                            handed_back = True
                    elif block.get("type") == "text":
                        self._prompt(block.get("text", ""), ts)
            a.last_kind = "handback" if handed_back and a.parent else "user"
            a.error_note = None
            return

        # assistant
        if d.get("isApiErrorMessage") or d.get("error"):
            a.last_kind = "error"
            text = ""
            if isinstance(content, list):
                text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            a.error_note = first_line(text or str(d.get("error")), 200)
            return

        model = msg.get("model")
        if isinstance(model, str) and model and not model.startswith("<"):
            a.model = sanitize(model)[:80]

        usage = msg.get("usage")
        if isinstance(usage, dict):
            inp = int(usage.get("input_tokens") or 0)
            out = int(usage.get("output_tokens") or 0)
            cc = int(usage.get("cache_creation_input_tokens") or 0)
            cr = int(usage.get("cache_read_input_tokens") or 0)
            if inp + cc + cr > 0:  # '<synthetic>' / error messages carry zero usage
                a.context_tokens = inp + cc + cr + out
            mid = msg.get("id")
            if mid and mid not in self._seen_msgs and ts:
                self._seen_msgs.add(mid)
                a.tokens_in += inp
                a.tokens_out += out
                a.tokens_cache_create += cc
                a.tokens_cache_read += cr
                self.usage.append(UsageRecord(ts, a.model or "unknown", inp, out, cc, cr))

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    name = block.get("name", "tool")
                    inp = block.get("input") or {}
                    if block.get("id"):
                        self._pending[block["id"]] = name
                    a.activity.append(ActivityItem(ts, name, tool_detail(name, inp, a.cwd)))
                    self._track_file(name, inp)
                    if name in PLAN_TOOLS:
                        self._plan(name, inp)
                elif btype == "text":
                    line = first_line(block.get("text", ""))
                    if line:
                        a.activity.append(ActivityItem(ts, "say", line))

        a.stop_reason = msg.get("stop_reason") or a.stop_reason
        a.last_kind = "assistant"
        a.error_note = None

    def _prompt(self, text: str, ts) -> None:
        text = sanitize(text).strip()
        if not text or text.startswith("<") or text.startswith("Caveat:"):
            return
        a = self.agent
        if text.startswith("[Request interrupted"):
            a.activity.append(ActivityItem(ts, "you", "interrupted", True))
            return
        a.prompt = text
        a.prompt_ts = ts
        if not a.first_prompt:
            a.first_prompt = text
        a.activity.append(ActivityItem(ts, "you", first_line(text)))

    def _track_file(self, name: str, inp) -> None:
        if not isinstance(inp, dict):
            return
        path = inp.get("file_path") or inp.get("notebook_path")
        if not isinstance(path, str):
            return
        op = "E" if name in EDIT_TOOLS else "R" if name in READ_TOOLS else None
        if not op:
            return
        rel = short_path(path, self.agent.cwd)
        counts = self.agent.files.setdefault(rel, {"R": 0, "E": 0})
        counts[op] += 1

    def _plan(self, name: str, inp) -> None:
        if not isinstance(inp, dict):
            return
        a = self.agent
        if name == "TodoWrite" and isinstance(inp.get("todos"), list):
            a.plan = [
                PlanItem(sanitize(t.get("content", ""))[:300], sanitize(t.get("status", "pending")))
                for t in inp["todos"]
                if isinstance(t, dict)
            ][:100]
            return
        # Claude desktop's plan tool: full list or incremental advance/done/start.
        if isinstance(inp.get("items"), list):
            a.plan = [
                PlanItem(sanitize(t.get("content", ""))[:300], sanitize(t.get("status", "pending")))
                for t in inp["items"]
                if isinstance(t, dict)
            ][:100]
            return
        plan = a.plan
        if inp.get("advance"):
            cur = next((i for i, p in enumerate(plan) if p.status == "in_progress"), None)
            if cur is not None:
                plan[cur].status = "completed"
            nxt = next((p for p in plan if p.status == "pending"), None)
            if nxt:
                nxt.status = "in_progress"
        for idx in inp.get("done") or []:
            if isinstance(idx, int) and 0 < idx <= len(plan):
                plan[idx - 1].status = "completed"
        start = inp.get("start")
        if isinstance(start, int) and 0 < start <= len(plan):
            for p in plan:
                if p.status == "in_progress":
                    p.status = "pending"
            plan[start - 1].status = "in_progress"
