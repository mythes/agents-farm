"""Per-model usage inside the current rate-limit window.

Claude Code doesn't write the remaining subscription quota to disk, so this is an
estimate: tokens summed over the active 5-hour block (block starts at the first
message after the previous block expired, floored to the hour), compared with
the budgets in config.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from .model import LimitInfo, UsageRecord

FAMILIES = ("opus", "sonnet", "haiku", "fable")


def family(model: str) -> str:
    m = (model or "").lower()
    for f in FAMILIES:
        if f in m:
            return f
    return "other"


def _weight(r: UsageRecord, count_cache_read: bool) -> int:
    n = r.input + r.output + r.cache_create
    if count_cache_read:
        n += r.cache_read
    return n


def current_block_start(records: List[UsageRecord], window: timedelta, now: datetime) -> Optional[datetime]:
    start: Optional[datetime] = None
    for r in records:
        if start is None or r.ts >= start + window:
            start = r.ts.replace(minute=0, second=0, microsecond=0)
    if start is None or now >= start + window:
        return None
    return start


def compute_limits(records: Iterable[UsageRecord], cfg: dict, now: datetime) -> List[LimitInfo]:
    window = timedelta(hours=float(cfg.get("window_hours", 5)))
    recs = sorted((r for r in records if r.ts >= now - 2 * window), key=lambda r: r.ts)
    start = current_block_start(recs, window, now)
    count_cr = bool(cfg.get("count_cache_read"))
    budgets: Dict[str, int] = cfg.get("limits", {})

    used: Dict[str, int] = {}
    recent: Dict[str, int] = {}
    rate_from = now - timedelta(minutes=15)
    if start is not None:
        for r in recs:
            if r.ts < start:
                continue
            fam = family(r.model)
            w = _weight(r, count_cr)
            used[fam] = used.get(fam, 0) + w
            if r.ts >= rate_from:
                recent[fam] = recent.get(fam, 0) + w

    reset_at = start + window if start else None
    out = []
    for fam in sorted(used, key=lambda f: -used[f]):
        out.append(
            LimitInfo(
                family=fam,
                used=used.get(fam, 0),
                limit=int(budgets.get(fam, 0) or 0),
                reset_at=reset_at if used.get(fam) else None,
                rate_per_min=recent.get(fam, 0) / 15.0,
            )
        )
    return out
