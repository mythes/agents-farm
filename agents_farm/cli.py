"""Command line entry point.

  agents-farm                 dashboard (Claude Code sessions)
  agents-farm --demo          dashboard with fake data
  agents-farm status [--json] one-shot summary for scripts / statuslines
  agents-farm hook            hook handler (reads the event JSON on stdin)
  agents-farm hooks-snippet   print the settings.json block that installs the hooks
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys

from . import __version__


def _store(args):
    if getattr(args, "demo", False):
        from .demo import DemoStore

        return DemoStore()
    from .store import Store

    return Store(since_hours=args.since)


def cmd_status(args) -> None:
    from .render import fmt_tokens, short_model

    snap = _store(args).refresh()
    active = [a for a in snap.agents if a.status.value != "idle"]
    if args.json:
        out = {
            "updated": snap.updated.isoformat(),
            "hooks_active": snap.hooks_active,
            "agents": [
                {
                    "id": a.id, "parent": a.parent, "name": a.name, "status": a.status.value,
                    "pid": a.pid, "entrypoint": a.entrypoint,
                    "note": a.status_note, "model": a.model, "project": a.project, "cwd": a.cwd,
                    "context_tokens": a.context_tokens, "prompt": a.prompt[:500],
                    "last_activity": a.last_activity.isoformat() if a.last_activity else None,
                }
                for a in active
            ],
            "limits": [
                {"family": l.family, "used": l.used, "limit": l.limit, "pct": l.pct,
                 "reset_at": l.reset_at.isoformat() if l.reset_at else None}
                for l in snap.limits
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    # one line, suitable for tmux / statusline
    counts = {}
    for a in active:
        counts[a.status.value] = counts.get(a.status.value, 0) + 1
    sym = {"running": "●", "thinking": "◐", "waiting": "?", "error": "!", "stalled": "⏸", "done": "✓"}
    parts = [f"{sym[s]}{counts[s]}" for s in sym if counts.get(s)]
    lims = []
    for l in snap.limits:
        if l.pct is not None:
            lims.append(f"{l.family} {l.pct:.0%}" + ("⚠" if l.pct >= snap.crit else ""))
        else:
            lims.append(f"{l.family} {fmt_tokens(l.used)}")
    print(" ".join(parts) + (" │ " if parts and lims else "") + " │ ".join(lims))


def cmd_hooks_snippet(args) -> None:
    from .events import HOOK_EVENTS

    exe = shutil.which("agents-farm") or os.path.join(os.path.dirname(sys.executable), "agents-farm")
    command = f"{shlex.quote(exe)} hook"
    block = {
        "hooks": {
            ev: [{"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": 5}]}]
            if ev in ("PreToolUse", "PostToolUse")
            else [{"hooks": [{"type": "command", "command": command, "timeout": 5}]}]
            for ev in HOOK_EVENTS
        }
    }
    print(json.dumps(block, indent=2))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="agents-farm", description="Terminal dashboard for Claude Code agents")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--demo", action="store_true", help="use fake data")
    parser.add_argument("--since", type=float, default=None, help="show sessions active in the last N hours (default 12)")
    parser.add_argument("--interval", type=float, default=2.0, help="refresh interval, seconds")
    sub = parser.add_subparsers(dest="cmd")
    st = sub.add_parser("status", help="one-shot summary")
    st.add_argument("--json", action="store_true")
    st.add_argument("--demo", action="store_true")
    st.add_argument("--since", type=float, default=None)
    sub.add_parser("hook", help="hook handler (stdin JSON)")
    sub.add_parser("hooks-snippet", help="print settings.json hooks block")
    args = parser.parse_args(argv)

    if args.cmd == "hook":
        from .events import run_hook

        run_hook()
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "hooks-snippet":
        cmd_hooks_snippet(args)
    else:
        from .app import FarmApp
        from .config import load_config

        cfg = load_config()
        FarmApp(_store(args), interval=args.interval, notify_enabled=bool(cfg.get("notify", True))).run()


if __name__ == "__main__":
    main()
