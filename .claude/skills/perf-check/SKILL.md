---
name: perf-check
description: Check agents-farm for memory leaks, slow refreshes and files that grow for ever. Use after you change app.py, store.py, registry.py, render.py, events.py or anything that runs on every refresh, before a release, and when the user says the dashboard is slow or uses CPU or RAM.
---

# Check performance

The dashboard may run for days, so a small cost per refresh (every 2 seconds) becomes a big one. In v0.6.0 and v0.6.1 a Footer rebuild on every refresh leaked about 0.2 MB each time: one open dashboard reached 1 GB of RAM and 90% CPU in a day.

## Steps

1. Run the fast tests (they also run in `scripts/check.sh`):

   ```bash
   .venv/bin/pytest tests/test_performance.py -q
   ```

2. Run the long check. It uses the playground (made-up sessions, nothing real) and takes about a minute:

   ```bash
   .venv/bin/python scripts/perf_check.py
   .venv/bin/python scripts/perf_check.py --refreshes 5000 --json /tmp/perf.json   # before a release
   ```

   It fails when the heap grows more than 6 MB, a refresh takes more than 150 ms, or the last quarter is more than 2 times slower than the first.
3. Compare with the last numbers: about 13 MB of heap at the plateau, about 40 ms per refresh on real data (most of it is the `ps` call).

## If it fails

| Sign | Likely cause |
|---|---|
| heap grows steadily | something is created on every refresh and never freed: widgets, bindings (`refresh_bindings`), timers, caches without a limit. Find it with `tracemalloc` and compare two snapshots (`take_snapshot().compare_to(...)`) |
| a refresh is slow | a new `subprocess`, a file read for every session, or a full table rebuild. Cache by pid or by file size and mtime |
| later refreshes are slower | a list or dict that only grows (events, history) |
| idle CPU is high | a timer that always runs. Pause it when there is nothing to animate (see `_spin_for` in `app.py`) |

## Rules

- Never call `refresh_bindings()` on every refresh. Use `_refresh_footer()`, which does it only when the usable keys change.
- Every log file that the program appends to needs a size limit (`config.trim_log`).
- Do not raise a limit to make the check pass. Find the cause first.
- To look at a running dashboard, use `ps -o pid,%cpu,rss,etime -p <pid>`. Do not stop a process you did not start without asking the user.
