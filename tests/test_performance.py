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


# ------------------------------------------------------------------------------- only what changed is drawn

def _quiet_snapshot():
    """A snapshot that does not change by itself."""
    snap = DemoStore().refresh()
    for a in snap.agents:
        a.transcript = a.transcript or "x"
    return snap


def _count_updates(monkeypatch):
    from textual.widgets import DataTable, Static
    cells, texts = [], []
    cell, update = DataTable.update_cell, Static.update
    monkeypatch.setattr(DataTable, "update_cell", lambda self, row, col, value, **k: cells.append((row, getattr(col, "value", col))) or cell(self, row, col, value, **k))
    monkeypatch.setattr(Static, "update", lambda self, content="", **k: texts.append(self.id) or update(self, content, **k))
    return cells, texts


def test_a_refresh_with_the_same_data_draws_nothing(monkeypatch):
    cells, texts = _count_updates(monkeypatch)

    async def scenario(app, pilot):
        snap = _quiet_snapshot()
        app._apply_snapshot(snap)
        cells.clear(), texts.clear()
        for _ in range(20):
            app._apply_snapshot(snap)
        assert cells == [] and texts == []

    run(scenario, DemoStore())


def test_every_change_is_still_drawn(monkeypatch):
    from agents_farm.model import ActivityItem, PlanItem
    cells, texts = _count_updates(monkeypatch)

    async def scenario(app, pilot):
        snap = _quiet_snapshot()
        app._apply_snapshot(snap)
        a = app._selected()

        def after(change):
            cells.clear(), texts.clear()
            change()
            app._apply_snapshot(snap)
            return set(cells), set(texts) - {None}            # None: the title of a section (its count)

        assert after(lambda: a.activity.append(ActivityItem(snap.updated, "Bash", "new"))) == (set(), {"d-activity"})
        assert after(lambda: a.plan.append(PlanItem("x", "pending"))) == (set(), {"d-plan"})
        assert after(lambda: a.files.update({"new.py": {"R": 1, "E": 0}})) == (set(), {"d-context"})
        changed, drawn = after(lambda: setattr(a, "context_tokens", a.context_tokens + 30_000))
        assert changed == {(a.id, "ctx")} and drawn == {"d-head"}
        # only the colour of the cell changes (verified -> not verified): the text is the same
        changed, drawn = after(lambda: setattr(a, "pid_verified", False))
        assert changed == {(a.id, "pid")} and "d-head" in drawn
        changed, drawn = after(lambda: setattr(a, "status", Status.ERROR))
        assert (a.id, "st") in changed and {"topbar", "d-head"} <= drawn
        assert "limits" in after(lambda: setattr(snap.limits[0], "used", snap.limits[0].used * 2))[1]

    run(scenario, DemoStore())


def test_the_screen_is_right_after_no_selection_and_back():
    from textual.widgets import Static

    async def scenario(app, pilot):
        snap = _quiet_snapshot()
        app._apply_snapshot(snap)
        shown = {i: str(app.query_one(i, Static).render()) for i in ("#d-head", "#d-context", "#d-activity", "#d-plan")}
        selected = app.selected_id
        app.selected_id = None
        app._render_detail()
        assert "No agent selected" in str(app.query_one("#d-head", Static).render()) and str(app.query_one("#d-plan", Static).render()) == ""
        app.selected_id = selected
        app._render_detail()
        assert {i: str(app.query_one(i, Static).render()) for i in shown} == shown

    run(scenario, DemoStore())


def test_the_spinner_stops_at_the_right_symbol():
    from textual.widgets import DataTable

    async def scenario(app, pilot):
        snap = _quiet_snapshot()
        a = next(x for x in snap.agents if x.status == Status.THINKING)
        app._apply_snapshot(snap)
        app._spin()                                       # the spinner writes the cell on its own
        a.status = Status.RUNNING
        app._apply_snapshot(snap)
        assert "●" in app.query_one(DataTable).get_cell(a.id, "st").plain

    run(scenario, DemoStore())


def test_the_look_of_a_text_covers_the_style():
    from rich.text import Text
    from agents_farm.render import look
    assert Text("a", "red") == Text("a", "green")         # why Text.__eq__ is not used
    assert look(Text("a", "red")) != look(Text("a", "green")) and look(Text("a", "red")) == look(Text("a", "red"))


def test_one_line_bars_reach_the_screen_without_a_new_layout():
    from datetime import timedelta

    def row(app, selector):
        y = app.query_one(selector).region.y
        return "".join(s.text for s in app.screen._compositor.render_strips()[y])

    async def scenario(app, pilot):
        snap = _quiet_snapshot()
        app._apply_snapshot(snap)
        await pilot.pause(0.2)
        top, limits = row(app, "#topbar"), row(app, "#limits")
        snap.updated += timedelta(hours=1)
        snap.limits[0].used = 1
        app._apply_snapshot(snap)
        await pilot.pause(0.2)
        assert row(app, "#topbar") != top and row(app, "#limits") != limits

    run(scenario, DemoStore(), size=(160, 40))         # wide: the clock must fit
