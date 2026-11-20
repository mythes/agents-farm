"""Performance: no leak, no wasted wake-ups, no file that grows for ever. Found with a long run of the playground."""

import dataclasses
import gc
import json
import os
import stat
import tracemalloc

import pytest

from agents_farm import config, events, killer, registry
from agents_farm.app import FarmApp
from agents_farm.killer import Target
from agents_farm.model import Status
from demo_store import DemoStore
from test_background import run
from test_registry import MY_PID, needs_ps, write


# ------------------------------------------------------------------------------------------------ the footer leak

def test_the_footer_is_not_rebuilt_on_every_refresh(monkeypatch):
    """Every refresh_bindings() makes Textual rebuild the footer keys, and the old ones were never freed: 0.2 MB per
    refresh, so a dashboard left open for a day grew to gigabytes (v0.6.0 to v0.6.1)."""
    calls = []
    original = FarmApp.refresh_bindings
    monkeypatch.setattr(FarmApp, "refresh_bindings", lambda self, *a, **k: calls.append(1) or original(self, *a, **k))

    async def scenario(app, pilot):
        snap = app.snap
        calls.clear()
        for _ in range(60):                                  # 60 refreshes with the same data: the keys do not change
            app._apply_snapshot(snap)
        assert len(calls) == 0
        await pilot.press("j")                               # another session is selected: the keys may change
        await pilot.pause(0.2)
        assert len(calls) <= 1

    run(scenario, DemoStore())


def test_the_number_of_widgets_and_the_memory_stay_flat_over_many_refreshes():
    async def scenario(app, pilot):
        store = app.store
        for _ in range(30):                                  # warm up the caches
            app._apply_snapshot(store.refresh())
        await pilot.pause(0.2)
        widgets = len(list(app.screen.query("*"))) + len(list(app.query("Footer *")))
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(150):
            app._apply_snapshot(store.refresh())
        await pilot.pause(0.2)
        gc.collect()
        grown = tracemalloc.get_traced_memory()[0] - before
        tracemalloc.stop()
        assert len(list(app.screen.query("*"))) + len(list(app.query("Footer *"))) == widgets
        assert grown < 4_000_000, f"the heap grew by {grown / 1e6:.1f} MB in 150 refreshes (it was 31 MB before the fix)"

    run(scenario, DemoStore())


# ------------------------------------------------------------------------------------------------- idle wake-ups

def test_the_spinner_timer_runs_only_while_an_agent_is_thinking():
    async def scenario(app, pilot):
        assert app._spinning is True                         # the demo has an agent that thinks
        calm = dataclasses.replace(app.snap, agents=[a for a in app.snap.agents if a.status != Status.THINKING])
        app._apply_snapshot(calm)
        assert app._spinning is False and app._spin_timer._active.is_set() is False
        app._apply_snapshot(app.snap if any(a.status == Status.THINKING for a in app.snap.agents) else calm)

    run(scenario, DemoStore())


@needs_ps
def test_ps_is_not_spawned_on_every_refresh(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    write(sessions, MY_PID, sessionId="aaaaaaaa-0000-0000-0000-000000000001")
    calls = []
    real = registry.process_start_times
    monkeypatch.setattr(registry, "process_start_times", lambda pids: calls.append(list(pids)) or real(pids))
    monkeypatch.setattr(registry, "PS_TTL_S", 60.0)
    reg = registry.Registry(str(sessions))
    for _ in range(10):
        assert reg.scan()                                    # the session is found every time
    assert len(calls) == 1                                   # ... with one `ps`, not ten
    write(sessions, os.getppid(), sessionId="bbbbbbbb-0000-0000-0000-000000000002")
    reg.scan()
    assert len(calls) == 2                                   # a new pid file is looked at once
    monkeypatch.setattr(registry, "PS_TTL_S", 0)
    reg.scan()
    reg.scan()
    assert len(calls) == 4                                   # no cache: every scan, as the tests need it


# ------------------------------------------------------------------------------------------------- files that grow

def lines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def test_trim_log_keeps_the_newest_whole_lines_and_stays_private(tmp_path):
    path = tmp_path / "log"
    path.write_text("".join(json.dumps({"n": i, "pad": "x" * 40}) + "\n" for i in range(1000)))
    os.chmod(path, 0o600)
    size = path.stat().st_size
    assert config.trim_log(str(path), size + 1, 2000) is False                     # small enough: untouched
    assert path.stat().st_size == size
    assert config.trim_log(str(path), 5000, 2000) is True
    kept = lines(path)                                                             # every line is whole, and newest
    assert kept[-1]["n"] == 999 and 20 < len(kept) < 50 and kept == sorted(kept, key=lambda r: r["n"])
    assert path.stat().st_size <= 2000 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not [f for f in os.listdir(tmp_path) if ".trim" in f]                   # no temp file is left


def test_trim_log_never_raises(tmp_path):
    assert config.trim_log(str(tmp_path / "missing"), 10, 5) is False
    assert config.trim_log(str(tmp_path), 0, 5) is False                           # a folder, not a file


def test_the_hook_trims_events_jsonl_and_the_reader_follows(tmp_path, monkeypatch):
    path = str(tmp_path / "events.jsonl")
    monkeypatch.setattr(events, "EVENTS_PATH", path)
    monkeypatch.setattr(events, "EVENTS_MAX_BYTES", 4000)
    monkeypatch.setattr(events, "EVENTS_KEEP_BYTES", 1500)
    reader = events.EventReader(path)
    import io, sys
    for i in range(80):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "session_id": f"s{i}", "cwd": "/x" * 20})))
        with pytest.raises(SystemExit):
            events.run_hook()
        reader.poll()
    assert os.path.getsize(path) <= 4000 + 400                                     # it never grew far above the limit
    assert reader.latest["s79"].event == "Stop"                                    # the reader did not lose the newest event
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_actions_log_is_trimmed_too(tmp_path, monkeypatch):
    import signal
    path = str(tmp_path / "actions.log")
    monkeypatch.setattr(killer, "ACTIONS_LOG", path)
    monkeypatch.setattr(killer, "ACTIONS_MAX_BYTES", 3000)
    monkeypatch.setattr(killer, "ACTIONS_KEEP_BYTES", 1000)
    for i in range(60):
        killer.log_action(Target(pid=1000 + i, session_id="s", name="n" * 50), signal.SIGTERM, "sent", path)
    assert os.path.getsize(path) <= 3000 + 500
    assert lines(path)[-1]["pid"] == 1059
