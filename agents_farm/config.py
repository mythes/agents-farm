"""User config at ~/.agents-farm/config.json (all keys optional)."""

from __future__ import annotations

import copy
import json
import os

HOME_DIR = os.path.expanduser(os.environ.get("AGENTS_FARM_HOME", "~/.agents-farm"))
CONFIG_PATH = os.path.join(HOME_DIR, "config.json")
EVENTS_PATH = os.path.join(HOME_DIR, "events.jsonl")
CLAUDE_PROJECTS = os.path.expanduser(os.environ.get("CLAUDE_PROJECTS_DIR", "~/.claude/projects"))

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
    # Context window per model family (tokens); auto-bumps to 1M if exceeded.
    "context_window": {"default": 200_000},
    # Only show sessions touched within this many hours.
    "since_hours": 12,
    "stalled_after_s": 90,
    "done_visible_min": 30,
    "notify": True,
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
