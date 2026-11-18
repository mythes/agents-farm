"""User config at ~/.agents-farm/config.json (all keys optional)."""

from __future__ import annotations

import copy
import json
import os

HOME_DIR = os.path.expanduser(os.environ.get("AGENTS_FARM_HOME", "~/.agents-farm"))
CONFIG_PATH = os.path.join(HOME_DIR, "config.json")
EVENTS_PATH = os.path.join(HOME_DIR, "events.jsonl")
ACTIONS_LOG = os.path.join(HOME_DIR, "actions.log")
CLAUDE_PROJECTS = os.path.expanduser(os.environ.get("CLAUDE_PROJECTS_DIR", "~/.claude/projects"))
CLAUDE_SESSIONS = os.path.expanduser(os.environ.get("CLAUDE_SESSIONS_DIR", "~/.claude/sessions"))

DEFAULTS = {
    # Usage window that limits reset on (Claude subscriptions use 5-hour blocks).
    "window_hours": 5,
    # Token budget per model family per window. These are PLACEHOLDERS, not real
    # plan limits: Claude Code does not expose the remaining quota locally, so
    # set numbers that match what you observe on your plan. 0 = unknown (no %).
    "limits": {"opus": 4_000_000, "sonnet": 8_000_000, "haiku": 20_000_000, "fable": 4_000_000},
    # Which token kinds count toward the budget.
    "count_cache_read": False,
    "warn": 0.70,
    "crit": 0.90,
    # Context window in tokens. Transcripts do NOT record the window, so it is set
    # per model-id substring (longest match wins). Evidence: opus-5-5 sessions
    # reached 347k, and /context reports 1m for sonnet-5-5. Check `/context` in
    # Claude Code for your plan and override here. A session that exceeds its
    # window is bumped up automatically, so the bar can never pass 100%.
    "context_window": {"default": 200_000, "opus-5": 1_000_000, "sonnet-5": 1_000_000},
    # Only show sessions touched within this many hours.
    "since_hours": 12,
    "stalled_after_s": 90,
    # A session the pid file calls "busy" is normal for a long time (builds, tests).
    # Only after this many seconds without any new output is it shown as stalled.
    "busy_stalled_s": 600,
    "done_visible_min": 30,
    "notify": True,
    # The x key (stop an agent's process) always asks first. Set to false to turn it off.
    "allow_kill": True,
    # The n key starts `claude` in this terminal. "" = look for `claude` on PATH.
    "claude_bin": "",
    "claude_args": [],       # extra flags for every new session, for example ["--verbose"]
    "claude_env": {},        # extra environment variables for `claude`
    "new_model": "",         # default model in the new-session dialog ("" = Claude's default)
    "models": [],            # extra model names to offer in the dialog (ctrl+o)
}


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            user = json.load(fh)
    except (OSError, ValueError):
        return cfg
    for key, val in user.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg
