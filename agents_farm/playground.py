#!/usr/bin/env python3
"""The demo and the playground: made-up sessions in every state, and a fake `claude`. Nothing real is touched.

`agents-farm --demo` builds this in a temporary folder, runs the dashboard on it, and removes it when you quit.
Real (fake) processes, process files and transcripts are made, and `claude_bin` points to the fake claude
(agents_farm/fake_claude.py), so `n`, `a`, `r`, `f` and `x` really work, without any real session or any token.

For development:
    python -m agents_farm.playground up      build it in a fixed folder and print how to start
    python -m agents_farm.playground env     print the environment (to use with your own shell)
    python -m agents_farm.playground down    stop the fake processes and remove the folder
"""

import json
import os
import shlex
import shutil
import signal
import subprocess  # nosec B404
import sys
import tempfile
import time
import uuid

# Every subprocess call in this file runs a fixed command (ps, or this Python): there is no user input in it.
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))      # where the package is

DEFAULT_DIR = os.path.join(tempfile.gettempdir(), "agents-farm-playground")
# A fake process waits until the folder of its sessions is gone (or six hours pass), so none is ever left behind.
SLEEPER = "import os, sys, time\nend = time.time() + 21600\nwhile time.time() < end and os.path.isdir(sys.argv[2]):\n    time.sleep(1)"
PYTHON = sys.executable
FOLDERS = ("api-refactor", "docs-writer", "deploy-check", "lint-pass", "perf-audit", "test-fixer", "migrations",
           "old-spike", "untrusted-app")
TITLES = {"docs-writer": "docs-writer", "api-refactor": "api-refactor", "test-fixer": "test-fixer", "perf-audit": "perf-audit",
          "lint-pass": "lint-pass", "deploy-check": "deploy-check", "bg-migrations": "migrations", "other-terminal": "review-pr",
          "ended-spike": "old-spike", "ended-desktop": "release-notes", "ended-gone": "rename-keys", "interrupted": "failing-ci"}
GONE = "removed-project"                      # a session whose folder no longer exists (it is not created)


def paths(base):
    return {
        "base": base, "home": os.path.join(base, "home"), "projects": os.path.join(base, "home", ".claude", "projects"),
        "sessions": os.path.join(base, "home", ".claude", "sessions"), "af": os.path.join(base, "af"),
        "pids": os.path.join(base, "pids.json"), "work": os.path.join(base, "home", "projects"),
    }


def env_for(base):
    p = paths(base)
    return {"HOME": p["home"], "AGENTS_FARM_HOME": p["af"], "CLAUDE_PROJECTS_DIR": p["projects"],
            "CLAUDE_SESSIONS_DIR": p["sessions"], "PYTHONPATH": ROOT}


def iso(age_s):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - age_s))


def lstart(pid):
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,  # nosec
                         env=dict(os.environ, TZ="UTC", LC_ALL="C")).stdout
    return out.strip()


# name, folder, prompt, age (seconds since the last event), how the transcript ends, model, where it started,
# process: None (ended) or (status, kind), and extras
SESSIONS = [
    ("docs-writer", "docs-writer", "Update the README and remove old docs", 90, "tool", "sonnet", "claude-desktop", ("waiting", "interactive")),
    ("api-refactor", "api-refactor", "Move auth into its own module, keep the public API", 12, "tool", "opus", "cli", ("busy", "interactive")),
    ("test-fixer", "test-fixer", "Fix the flaky test in payments", 40, "user", "sonnet", "cli", ("busy", "interactive")),
    ("perf-audit", "perf-audit", "Find slow queries in /reports", 900, "tool", "opus", "cli", ("busy", "interactive")),
    ("lint-pass", "lint-pass", "Run the linter and fix warnings", 240, "end", "haiku", "cli", ("idle", "interactive")),
    ("deploy-check", "deploy-check", "Check the staging deploy", 360, "error", "sonnet", "cli", ("idle", "interactive")),
    ("bg-migrations", "migrations", "Add an index on orders.created_at", 8, "tool", "haiku", "cli", ("busy", "bg")),
    ("bg-fresh", "api-refactor", None, 0, None, "haiku", "cli", ("idle", "bg")),          # no transcript yet
    ("other-terminal", "docs-writer", "Review the open pull request", 180, "end", "sonnet", "cli", ("idle", "interactive")),
    ("ended-spike", "old-spike", "Spike: SSE instead of polling", 7200, "end", "sonnet", "cli", None),
    ("ended-desktop", "docs-writer", "Draft the release notes", 600, "end", "sonnet", "claude-desktop", None),
    ("ended-gone", GONE, "Rename the config keys", 720, "end", "haiku", "cli", None),
    ("interrupted", "api-refactor", "Look at the failing CI", 3600, "user", "sonnet", "cli", None),
]


def transcript(folder_path, prompt, age, ending, model, origin, sid, title=""):
    """JSON lines for one session. `ending`: tool (a tool call with no result yet), user (a prompt with no answer),
    end (a finished answer) or error."""
    first = age + 120
    lines = [{"type": "custom-title", "customTitle": title}] if title else []
    lines.append({"type": "user", "timestamp": iso(first), "cwd": folder_path, "entrypoint": origin, "gitBranch": "main",
                  "message": {"role": "user", "content": prompt}})

    def assistant(ts, content, stop):
        return {"type": "assistant", "timestamp": iso(ts), "message": {
            "id": uuid.uuid4().hex[:12], "model": f"claude-{model}-5-5", "stop_reason": stop,
            "usage": {"input_tokens": 60000, "output_tokens": 900, "cache_read_input_tokens": 30000}, "content": content}}

    if ending in ("tool", "end", "error"):
        lines.append(assistant(first - 30, [{"type": "text", "text": "Looking at the code first."},
                                            {"type": "tool_use", "id": "t0", "name": "Read", "input": {"file_path": "src/main.py"}}], "tool_use"))
        lines.append({"type": "user", "timestamp": iso(first - 31), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t0", "content": "ok"}]}})
    if ending == "tool":
        lines.append(assistant(age, [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "npm test"}}], "tool_use"))
    elif ending == "end":
        lines.append(assistant(age, [{"type": "text", "text": "Done. The change is in place and the tests pass."}], "end_turn"))
    elif ending == "error":
        lines.append({"type": "assistant", "timestamp": iso(age), "isApiErrorMessage": True,
                      "message": {"role": "assistant", "content": [{"type": "text", "text": "API Error: 529 overloaded"}]}})
    return lines


def down(base):
    p = paths(base)
    killed = 0
    try:
        pids = json.load(open(p["pids"]))
    except (OSError, ValueError):
        pids = []
    for pid in pids:                    # only the fake processes this script started, and only if they still look like them
        try:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout  # nosec
            if "claude-fake" in cmd:
                os.kill(int(pid), signal.SIGTERM)
                killed += 1
        except (OSError, ValueError):
            pass
    # fake background sessions that the fake claude started later (they also say "claude-fake")
    try:
        sessions = [f for f in os.listdir(p["sessions"]) if f.endswith(".json")]
    except OSError:
        sessions = []
    for name in sessions:
        try:
            pid = int(name[:-5])
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout  # nosec
            if "claude-fake" in cmd:
                os.kill(pid, signal.SIGTERM)
                killed += 1
        except (OSError, ValueError):
            pass
    if os.path.isdir(base) and os.path.exists(p["pids"]):      # only remove a folder that this script made
        shutil.rmtree(base, ignore_errors=True)
    return killed


def up(base=None):
    """Build the playground. With no folder given a new temporary one is made."""
    base = base or tempfile.mkdtemp(prefix="agents-farm-demo-")
    if os.path.exists(base) and os.listdir(base):
        down(base)
    p = paths(base)
    for key in ("projects", "sessions", "af", "work"):
        os.makedirs(p[key], exist_ok=True)
    for name in FOLDERS:
        os.makedirs(os.path.join(p["work"], name), exist_ok=True)
    os.makedirs(os.path.join(p["work"], "api-refactor", ".git"), exist_ok=True)
    with open(os.path.join(p["work"], "api-refactor", ".git", "HEAD"), "w") as fh:
        fh.write("ref: refs/heads/feature/api-v2\n")
    for sub in ("src", "tests", "docs"):
        os.makedirs(os.path.join(p["work"], "api-refactor", sub), exist_ok=True)
    wrapper = os.path.join(base, "claude")                     # a program called `claude` that runs the fake one
    with open(wrapper, "w") as fh:
        fh.write(f"#!/bin/sh\nPYTHONPATH={shlex.quote(ROOT)}${{PYTHONPATH:+:$PYTHONPATH}} exec {shlex.quote(sys.executable)} -m agents_farm.fake_claude \"$@\"\n")
    os.chmod(wrapper, 0o700)           # only you run it
    with open(os.path.join(p["af"], "config.json"), "w") as fh:
        json.dump({"claude_bin": wrapper, "notify": True, "since_hours": 12}, fh)

    pids = []
    for name, folder, prompt, age, ending, model, origin, proc in SESSIONS:
        cwd = os.path.join(p["work"], folder)
        sid = str(uuid.uuid4())
        if prompt is not None:
            directory = os.path.join(p["projects"], "-" + cwd.replace("/", "-").lstrip("-"))
            os.makedirs(directory, exist_ok=True)
            with open(os.path.join(directory, sid + ".jsonl"), "w") as fh:
                fh.write("\n".join(json.dumps(x) for x in transcript(cwd, prompt, age, ending, model, origin, sid, TITLES.get(name, ""))) + "\n")
            if name == "api-refactor":                          # one subagent under it
                sub = os.path.join(directory, sid, "subagents")
                os.makedirs(sub, exist_ok=True)
                with open(os.path.join(sub, "agent-1.jsonl"), "w") as fh:
                    fh.write("\n".join(json.dumps(x) for x in transcript(cwd, "Find every caller of getSession()", 5, "tool", "haiku", origin, sid, "explore auth usages")) + "\n")
        if proc:
            status, kind = proc
            child = subprocess.Popen([sys.executable, "-c", SLEEPER, f"claude-fake-{name}", p["sessions"]],  # nosec
                                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pids.append(child.pid)
            time.sleep(0.15)
            with open(os.path.join(p["sessions"], f"{child.pid}.json"), "w") as fh:
                json.dump({"pid": child.pid, "sessionId": sid, "cwd": cwd, "name": prompt or "new background session", "status": status,
                           "entrypoint": origin, "kind": kind, "version": "2.1.327", "startedAt": int((time.time() - age - 120) * 1000),
                           "procStart": lstart(child.pid)}, fh)
    with open(p["pids"], "w") as fh:
        json.dump(pids, fh)
    return base


def make_store(base, notify=True):
    """A Store that reads the playground, and runs the fake claude (through `claude_env` and `claude_bin`)."""
    from .config import DEFAULTS
    from .store import Store
    p = paths(base)
    cfg = dict(DEFAULTS, claude_bin=os.path.join(base, "claude"), notify=notify,
               claude_env={"CLAUDE_PROJECTS_DIR": p["projects"], "CLAUDE_SESSIONS_DIR": p["sessions"], "HOME": p["home"]})
    store = Store(root=p["projects"], since_hours=12, cfg=cfg, sessions_dir=p["sessions"])
    store.source = "playground"
    return store


def summary(base):
    snap = make_store(base).refresh()
    rows = []
    for a in snap.agents:
        rows.append((a.status.value, str(a.pid or "-"), "bg" if a.background else (a.entrypoint or a.origin or "-"), a.name[:44]))
    return rows


def shell_line(base):
    e = env_for(base)
    return " ".join(f"{k}={v}" for k, v in e.items()) + f" {PYTHON} -m agents_farm"        # the real dashboard on this folder


def main(argv):
    cmd = argv[0] if argv else "help"
    base = argv[1] if len(argv) > 1 else DEFAULT_DIR
    if cmd == "up":
        up(base)
        print(f"playground ready in {base}\n")
        print(f"{'status':<9} {'pid':<7} {'from':<15} session")
        for row in summary(base):
            print(f"{row[0]:<9} {row[1]:<7} {row[2]:<15} {row[3]}")
        print("\nthe same data, with the real dashboard:\n  " + shell_line(base))
        print("\nstop it and clean up:\n  python -m agents_farm.playground down")
        return 0
    if cmd == "env":
        for k, v in env_for(base).items():
            print(f"export {k}={v}")
        return 0
    if cmd == "down":
        print("fake processes stopped:", down(base))
        return 0
    print(__doc__)
    return 0 if cmd in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
