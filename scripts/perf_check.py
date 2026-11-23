#!/usr/bin/env python3
"""Performance check: does the dashboard leak memory or get slower over time?

Runs the app on the playground (made-up sessions, nothing real is touched) and refreshes it many times.
It prints the heap size and the time per refresh, and fails (exit code 1) when a limit is broken.

    .venv/bin/python scripts/perf_check.py              # 1500 refreshes, about 1 minute
    .venv/bin/python scripts/perf_check.py --refreshes 5000 --json perf.json
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agents_farm import playground  # noqa: E402
from agents_farm.app import FarmApp  # noqa: E402

# Limits. The leak found in v0.6.1 was 0.21 MB per refresh (258 MB at 1200 refreshes).
WARMUP = 3000               # refreshes before we start to measure. The table cache of Textual (10000 entries) is full after
                            # about 2000 (when every fifth one is drawn), and the heap then stays at about 12 MB (checked up to 12000 refreshes)
MAX_GROWTH_MB = 3.0          # heap growth after the warm-up
MAX_MS_PER_REFRESH = 150.0   # one refresh (scan + apply); it was about 40 ms
MAX_SLOWDOWN = 2.0           # the last quarter may not be slower than the first quarter by more than this factor


async def measure(refreshes: int) -> dict:
    base = playground.up(tempfile.mkdtemp(prefix="af-perf-"))
    try:
        store = playground.make_store(base, notify=True)
        app = FarmApp(store, interval=3600.0, notify_enabled=True)  # the timers are driven by hand
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause(1.0)
            tracemalloc.start()                                      # trace from the start: old objects must be counted too
            for i in range(WARMUP):                                  # caches fill up first
                app._apply_snapshot(store.refresh())
                if i % 5 == 0:                                   # draw often: only drawing fills the caches
                    await pilot.pause(0.001)
            gc.collect()
            start_heap = tracemalloc.get_traced_memory()[0]
            times, heap = [], []
            for i in range(refreshes):
                t0 = time.perf_counter()
                app._apply_snapshot(store.refresh())
                times.append((time.perf_counter() - t0) * 1000)
                if i % 20 == 0:
                    await pilot.pause(0.001)
                if i % max(1, refreshes // 10) == 0:
                    gc.collect()
                    heap.append(round((tracemalloc.get_traced_memory()[0] - start_heap) / 1e6, 2))
            gc.collect()
            grown = (tracemalloc.get_traced_memory()[0] - start_heap) / 1e6
            tracemalloc.stop()
    finally:
        playground.down(base)
    q = max(1, len(times) // 4)
    first, last = sum(times[:q]) / q, sum(times[-q:]) / q
    return {
        "refreshes": refreshes,
        "heap_growth_mb": round(grown, 2),
        "heap_series_mb": heap,
        "ms_avg": round(sum(times) / len(times), 1),
        "ms_first_quarter": round(first, 1),
        "ms_last_quarter": round(last, 1),
    }


def verdict(r: dict) -> list:
    problems = []
    if r["heap_growth_mb"] > MAX_GROWTH_MB:
        problems.append(f"heap grew by {r['heap_growth_mb']} MB (limit {MAX_GROWTH_MB} MB): a leak")
    if r["ms_avg"] > MAX_MS_PER_REFRESH:
        problems.append(f"a refresh takes {r['ms_avg']} ms (limit {MAX_MS_PER_REFRESH} ms)")
    if r["ms_last_quarter"] > MAX_SLOWDOWN * max(r["ms_first_quarter"], 1.0):
        problems.append(f"refreshes get slower: {r['ms_first_quarter']} ms, then {r['ms_last_quarter']} ms")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refreshes", type=int, default=1500)
    parser.add_argument("--json", help="also write the result to this file")
    args = parser.parse_args()
    result = asyncio.run(measure(args.refreshes))
    print(json.dumps(result, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
    problems = verdict(result)
    for p in problems:
        print("FAIL:", p)
    print("performance ok" if not problems else "performance check failed")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
