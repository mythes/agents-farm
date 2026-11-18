"""Fake, slowly-evolving data so the UI can be tried without live agents."""

from __future__ import annotations

import random
from datetime import timedelta

from .config import DEFAULTS
from .render import context_window
from .model import ActivityItem, Agent, LimitInfo, PlanItem, Snapshot, Status, utcnow

TOOLS = [
    ("Read", "src/auth/session.ts"), ("Grep", "getSession\\("), ("Edit", "src/auth/index.ts"),
    ("Bash", "npm test -- auth"), ("Read", "src/server.ts"), ("Edit", "src/server.ts"),
    ("Bash", "git diff --stat"), ("Write", "src/auth/README.md"), ("say", "Tests pass, updating the imports"),
]


class DemoStore:
    cfg = DEFAULTS

    def __init__(self):
        self.rng = random.Random(7)  # nosec B311
        self._next_pid = 40210       # fake process ids for the demo
        now = utcnow()
        self.agents = [
            self._mk("docs-writer", "Update the README and remove old docs", "claude-sonnet-5-5", Status.WAITING, 2, 0.34,
                     note="Claude needs your permission to use Bash: rm docs/old/README.md"),
            self._mk("api-refactor", "Move auth into its own module, keep the public API", "claude-opus-5-5", Status.RUNNING, 12, 0.71,
                     plan=["Find all uses of session", "Create src/auth/", "Move the code", "Update the imports", "Run the tests"], step=2),
            self._mk("test-fixer", "Fix the flaky test in payments", "claude-sonnet-5-5", Status.THINKING, 4, 0.22),
            self._mk("migrations", "Add an index on orders.created_at", "claude-haiku-5-5", Status.RUNNING, 1, 0.08),
            self._mk("deploy-check", "Check the staging deploy", "claude-sonnet-5-5", Status.ERROR, 6, 0.40,
                     note="API Error: 529 overloaded — retries exhausted"),
            self._mk("perf-audit", "Find slow queries in /reports", "claude-opus-5-5", Status.STALLED, 18, 0.55,
                     note="Bash pending for 4m — maybe waiting for permission"),
            self._mk("lint-pass", "Run the linter and fix warnings", "claude-haiku-5-5", Status.DONE, 9, 0.12),
            self._mk("old-spike", "Spike: SSE instead of polling", "claude-sonnet-5-5", Status.IDLE, 300, 0.3),
        ]
        sub = self._mk("explore auth usages", "Find every caller of getSession()", "claude-haiku-5-5", Status.RUNNING, 1, 0.1)
        sub.parent = self.agents[1].id
        sub.live, sub.pid, sub.entrypoint, sub.live_status = None, None, "", ""   # subagents have no process of their own
        sub.id = self.agents[1].id + "/agent-1"
        self.agents.insert(2, sub)
        next(x for x in self.agents if x.id == "demo-migrations").background = True   # a background session: `a` works on it
        self.used = {"opus": 2_480_000, "sonnet": 7_520_000, "haiku": 2_800_000}
        self.reset = now + timedelta(hours=1, minutes=12)

    def _mk(self, title, prompt, model, status, minutes, ctx, note="", plan=None, step=0) -> Agent:
        now = utcnow()
        a = Agent(id=f"demo-{title}", transcript=f"~/.claude/projects/-demo/{title}.jsonl",
                  project="backend", cwd="/Users/you/work/backend", branch=f"feat/{title}",
                  title=title, model=model, prompt=prompt, first_prompt=prompt)
        a.started = a.prompt_ts = now - timedelta(minutes=minutes)
        a.last_activity = now - timedelta(seconds=self.rng.randint(1, 40) if status in (Status.RUNNING, Status.THINKING) else minutes * 30)
        a.context_tokens = int(ctx * context_window(a, DEFAULTS["context_window"]))
        a.tokens_in, a.tokens_out = a.context_tokens * 3, a.context_tokens // 6
        a.status, a.status_note = status, note
        a.hooked = True
        if status in (Status.IDLE, Status.DONE):
            a.live = False                       # the session is not running any more
        else:
            self._next_pid += 7
            a.live, a.pid, a.pid_verified = True, self._next_pid, True
            a.entrypoint = "claude-desktop" if self._next_pid % 2 else "cli"
            a.live_status = "busy" if status in (Status.RUNNING, Status.THINKING) else "idle"
            a.client_version = "2.1.325"
        t = a.started
        a.activity.append(ActivityItem(t, "you", prompt))
        for i in range(self.rng.randint(4, 10)):
            t += timedelta(seconds=self.rng.randint(5, 60))
            kind, detail = self.rng.choice(TOOLS)
            a.activity.append(ActivityItem(t, kind, detail))
            if kind in ("Read", "Edit", "Write"):
                c = a.files.setdefault(detail, {"R": 0, "E": 0})
                c["R" if kind == "Read" else "E"] += 1
        if status == Status.ERROR:
            a.activity.append(ActivityItem(t, "Bash", "curl staging/health → connection refused", True))
        if plan:
            a.plan = [PlanItem(p, "completed" if i < step else "in_progress" if i == step else "pending") for i, p in enumerate(plan)]
        return a

    def refresh(self) -> Snapshot:
        now = utcnow()
        for a in self.agents:
            if a.status == Status.RUNNING and self.rng.random() < 0.6:
                kind, detail = self.rng.choice(TOOLS)
                a.activity.append(ActivityItem(now, kind, detail))
                a.last_activity = now
                a.context_tokens = min(a.context_tokens + self.rng.randint(500, 4000), int(0.95 * context_window(a, DEFAULTS["context_window"])))
            elif a.status == Status.THINKING and self.rng.random() < 0.1:
                a.status = Status.RUNNING
        for fam in self.used:
            self.used[fam] += self.rng.randint(0, 8000)
        limits = [
            LimitInfo(f, u, DEFAULTS["limits"][f], self.reset, rate_per_min={"sonnet": 30_000}.get(f, 4000))
            for f, u in sorted(self.used.items(), key=lambda kv: -kv[1])
        ]
        return Snapshot(agents=list(self.agents), limits=limits, updated=now, hooks_active=True, source="demo")
