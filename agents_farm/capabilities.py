"""What can be done with the selected session, and why not. No Textual imports.

The footer greys out a key that cannot be used on the selected session. When the user presses it anyway, the
dashboard explains the reason and what to do instead, in a pop-up. `unavailable()` returns None when the action is
possible, otherwise a `Why` with the reason and the options. The rules are written in docs/rules.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .model import Agent
from .registry import ENTRYPOINT_LABELS

# The keys that depend on the selected session: key -> action name.
SESSION_KEYS: Dict[str, str] = {"a": "attach", "r": "resume", "f": "fork", "x": "kill", "p": "copy_pid"}

# Where a key in an option line leads (the pop-up can run it for you).
OPTION_ACTIONS: Dict[str, str] = {"a": "attach", "r": "resume", "f": "fork", "x": "kill", "n": "new_session"}


@dataclass
class Why:
    title: str
    reason: List[str]
    options: List[str] = field(default_factory=list)     # "r  continue it": the first word is the key


def _who(a: Agent) -> str:
    return ENTRYPOINT_LABELS.get(a.entrypoint or a.origin, "another program")


def _subagent() -> Why:
    return Why("A subagent has no process of its own",
               ["Subagents run inside their parent session, so they cannot be stopped, resumed, forked or attached alone."],
               ["↑  select the parent session, then try again"])


def _no_session() -> Why:
    return Why("No session is selected", ["There is no session in the list, or none is selected."],
               ["n  start a new session", "h  show idle sessions"])


def _folder_gone(a: Agent) -> Why:
    return Why("The folder of this session is gone", [f"{a.cwd or '(unknown folder)'} does not exist any more."],
               ["Create the folder again, then try again", "n  start a new session"])


def _no_history(extra: Optional[List[str]] = None) -> Why:
    return Why("This session has no history yet",
               ["It was just started and nothing has been written yet, so there is nothing to continue or fork."], extra or [])


def _folder_missing(a: Agent, cfg: dict) -> bool:
    return not cfg.get("demo") and (not a.cwd or not os.path.isdir(a.cwd))       # demo sessions have made-up folders


def unavailable(action: str, a: Optional[Agent], cfg: Optional[dict] = None) -> Optional[Why]:
    """None if `action` can be done with this session, else why not and what to do instead."""
    cfg = cfg or {}
    if a is None:
        return _no_session()

    if action == "attach":
        if a.parent:
            return _subagent()
        if a.background and a.pid:
            return None
        if a.pid:
            return Why("This session is not a background session",
                       [f"It runs in {_who(a)} (pid {a.pid}). agents-farm can only open sessions that run in the background."],
                       ["f  fork it: a new background session with the same history",
                        f"Open it in {_who(a)}, where it runs",
                        "x  stop it, then r to continue it as a background session"])
        return Why("This session is not running", ["There is no process to attach to."],
                   ["r  continue it", "f  fork it", "n  start a new session"])

    if action == "resume":                        # continue the same session: it must not be running
        if a.parent:
            return _subagent()
        if a.from_pid_file:
            return _no_history(["a  open it and type a first prompt"] if a.background and a.pid else [])
        if a.pid and a.background:
            return Why("It is already running in the background", ["A session that runs is not continued a second time."],
                       ["a  open it", "f  fork it: a new session with the same history"])
        if a.pid:
            return Why("It is running now",
                       [f"It runs in {_who(a)} (pid {a.pid}). Two processes must not write to one history, so it cannot be continued."],
                       ["f  fork it: a new session with the same history", "x  stop it first, then r"])
        if a.live is None:
            return Why("agents-farm cannot tell if it is running",
                       ["This Claude Code writes no process files, so it may be running. Two processes must not write to one history."],
                       ["f  fork it: a new session with the same history"])
        if _folder_missing(a, cfg):
            return _folder_gone(a)
        return None

    if action == "fork":                          # a new session with the same history: also when the session runs
        if a.parent:
            return _subagent()
        if a.from_pid_file:
            return _no_history()
        if _folder_missing(a, cfg):
            return _folder_gone(a)
        return None

    if action == "kill":
        if not cfg.get("allow_kill", True):
            return Why("Stopping is turned off", ["The config has \"allow_kill\": false."],
                       ["Set \"allow_kill\": true in ~/.agents-farm/config.json to turn it on"])
        if a.parent:
            return _subagent()
        if not a.pid:
            return Why("This session is not running", ["There is no process to stop."],
                       ["r  continue it if you want to work on it again", "h  show or hide idle sessions"])
        return None

    if action == "copy_pid":
        if a.parent:
            return _subagent()
        if not a.pid:
            return Why("This session is not running", ["It has no process id to copy."], ["r  continue it", "f  fork it"])
        return None
    return None
