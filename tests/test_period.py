"""The period of the list (the t key): what is listed, no false alerts, no parallel refreshes, the same limits."""

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from agents_farm import app as app_module
from agents_farm import config
from agents_farm.app import FarmApp
from agents_farm.model import Agent, Snapshot, Status, utcnow
from agents_farm.render import list_title, period_label
from agents_farm.store import Store
from test_registry import MY_PID, needs_ps, write

HOUR = 3600


def transcript(root, sid, hours, error=False, parent=None, tokens=10):
    path = root / "-Users-you-app" / (f"{parent}/subagents/{sid}.jsonl" if parent else f"{sid}.jsonl")
    os.makedirs(path.parent, exist_ok=True)
    when = datetime.now(timezone.utc) - timedelta(hours=hours)
    entry = {"type": "assistant", "timestamp": when.isoformat(), "message": {
        "id": f"m-{sid}", "model": "claude-opus", "stop_reason": "end_turn",
        "usage": {"input_tokens": tokens, "output_tokens": 0}, "content": [{"type": "text", "text": "hi"}]}}
    lines = [entry] + ([{"type": "assistant", "timestamp": when.isoformat(), "error": "boom"}] if error else [])
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    os.utime(path, (time.time() - hours * HOUR,) * 2)
    return str(path)


def make(tmp_path, since=24, sessions=None):
    root = tmp_path / "projects"
    os.makedirs(root, exist_ok=True)
    cfg = dict(config.DEFAULTS, state_path=str(tmp_path / "af" / "state.json"))
    return root, Store(root=str(root), since_hours=since, cfg=cfg, sessions_dir=sessions)


def ids(store):
    return sorted(a.id for a in store.refresh().agents)


# -------------------------------------------------------------------------------------------------- the store

def test_the_period_can_grow_and_shrink(tmp_path):
    root, store = make(tmp_path)
    for sid, hours in (("new", 1), ("two", 48), ("five", 120), ("old", 300)):
        transcript(root, sid, hours)
    assert ids(store) == ["new"]
    store.set_since(168)
    assert ids(store) == ["five", "new", "two"]            # at once, not after DISCOVER_EVERY_S
    readers = dict(store.readers)
    store.set_since(24)
    assert ids(store) == ["new"] and store.readers == readers        # kept: the way back reads no file again
    store.set_since(72)
    assert ids(store) == ["new", "two"]
    assert all(store.readers[p] is r for p, r in readers.items())


def test_the_limits_are_the_same_for_every_period(tmp_path):
    root, store = make(tmp_path, since=1)
    transcript(root, "now", 0.1)
    transcript(root, "before", 2, tokens=500)
    used = lambda: {x.family: x.used for x in store.refresh().limits}  # noqa: E731
    assert ids(store) == ["now"]
    short = used()
    store.set_since(168)
    assert ids(store) == ["before", "now"] and used() == short
    assert len(store.readers) == 2


def test_a_transcript_is_freed_after_a_week_and_not_read_again(tmp_path):
    root, store = make(tmp_path, since=168)
    path = transcript(root, "s", 150)
    assert ids(store) == ["s"]
    os.utime(path, (time.time() - 200 * HOUR,) * 2)
    store.rediscover()
    store.refresh()
    assert store.readers == {}


def test_the_parent_of_a_listed_subagent_is_listed(tmp_path):
    root, store = make(tmp_path, since=168)
    transcript(root, "mum", 48)
    transcript(root, "agent-1", 1, parent="mum")
    assert len(ids(store)) == 2
    store.set_since(24)
    assert ids(store) == ["mum", "mum/agent-1"]


@needs_ps
def test_a_running_session_is_listed_at_any_age(tmp_path):
    os.makedirs(tmp_path / "sessions")
    root, store = make(tmp_path, sessions=str(tmp_path / "sessions"))
    transcript(root, "alive", 400)
    transcript(root, "gone", 400)
    write(tmp_path / "sessions", MY_PID, sessionId="alive")
    for _ in range(2):
        store.rediscover()
        agents = store.refresh().agents
        assert [a.id for a in agents] == ["alive"] and agents[0].transcript      # read, not a placeholder
    store.rediscover()
    assert len(store.readers) == 1


def test_a_change_during_the_search_is_not_lost(tmp_path, monkeypatch):
    root, store = make(tmp_path)
    transcript(root, "two", 48)
    original, done = Store._discover, []

    def slow(self, live, since):
        original(self, live, since)
        if not done:
            done.append(1)
            self.set_since(72)

    monkeypatch.setattr(Store, "_discover", slow)
    first = store.refresh()
    assert first.since_hours == 24 and first.agents == []        # labelled with the period that was really read
    second = store.refresh()
    assert second.since_hours == 72 and [a.id for a in second.agents] == ["two"]


def test_labels():
    assert [period_label(h) for h in (12, 24, 72, 168, 1.5)] == ["12h", "24h", "3d", "7d", "1.5h"]
    snap = Snapshot(agents=[], limits=[], updated=utcnow(), hooks_active=False, since_hours=24)
    assert list_title(snap, 3) == "AGENTS (3) · last 24h (t)"
    assert list_title(snap, 3, 168) == "AGENTS (3) · last 7d (t) …"
    snap.since_hours = None
    assert list_title(snap, 3) == "AGENTS (3)"


# ----------------------------------------------------------------------------------------------------- the UI

def play(store, scenario, notify=True):
    async def main():
        app = FarmApp(store, interval=60.0, notify_enabled=notify)
        app.said = []
        app.notify = lambda message, **kw: app.said.append(message)
        async with app.run_test(size=(130, 32)) as pilot:
            await until(pilot, lambda: app.snap)
            return await scenario(app, pilot)

    return asyncio.run(main())


async def until(pilot, ready):
    for _ in range(100):
        if ready():
            return
        await pilot.pause(0.05)
    raise AssertionError("timeout")


def test_t_cycles_remembers_and_gives_no_alerts_for_old_errors(tmp_path):
    root, store = make(tmp_path)
    transcript(root, "new", 1)
    transcript(root, "failed", 100, error=True)

    async def scenario(app, pilot):
        for hours in (72, 168):
            await pilot.press("t")
            await until(pilot, lambda: app.snap.since_hours == hours)
        assert next(a for a in app.snap.agents if a.id == "failed").status == Status.ERROR
        assert app.said == [] and app._period is None
        assert config.load_state(app._state_path())["since_hours"] == 168
        await pilot.press("t")
        await until(pilot, lambda: app.snap.since_hours == 24)

    play(store, scenario)


def test_quick_presses_load_only_the_last_period(tmp_path, monkeypatch):
    _, store = make(tmp_path)
    asked, original = [], store.set_since
    monkeypatch.setattr(store, "set_since", lambda h: asked.append(h) or original(h))
    monkeypatch.setattr(app_module, "PERIOD_DELAY_S", 1.0)

    async def scenario(app, pilot):
        await pilot.press("t", "t")
        assert app._period == 168 and asked == []
        await until(pilot, lambda: app.snap.since_hours == 168)
        assert asked == [168]

    play(store, scenario)


def test_real_news_still_alert_at_a_switch(tmp_path):
    _, store = make(tmp_path)

    def snap(hours, *agents):
        return Snapshot(agents=list(agents), limits=[], updated=utcnow(), hooks_active=False, since_hours=hours)

    def agent(sid, status, live=None):
        return Agent(id=sid, transcript="", title=sid, last_activity=utcnow(), status=status, status_note=sid, live=live)

    async def scenario(app, pilot):
        app._alert_transitions(snap(24, agent("known", Status.RUNNING)))
        app._alert_transitions(snap(168, agent("known", Status.WAITING), agent("old", Status.ERROR), agent("running", Status.WAITING, True)))
        assert app.said == ["known", "running"]
        app._alert_transitions(snap(168, agent("later", Status.ERROR)))          # not a switch any more
        assert app.said[-1] == "later"

    play(store, scenario)


def test_refreshes_never_run_at_the_same_time(tmp_path, monkeypatch):
    _, store = make(tmp_path)
    original, now, most, calls = store.refresh, [0], [0], [0]
    guard = threading.Lock()

    def slow():
        with guard:
            now[0] += 1
            calls[0] += 1
            most[0] = max(most[0], now[0])
        time.sleep(0.15)
        with guard:
            now[0] -= 1
        return original()

    async def scenario(app, pilot):
        monkeypatch.setattr(store, "refresh", slow)
        for _ in range(6):
            app.refresh_data()
            await pilot.pause(0.03)
        await pilot.pause(1.0)
        assert most[0] == 1 and 1 <= calls[0] < 6            # the ones in the middle are skipped

    play(store, scenario)


@pytest.mark.parametrize("saved, fixed, expected", [(168, None, 168), (168, 12, 12), (5, None, 24), ("x", None, 24), (True, None, 24)])
def test_the_period_of_the_last_run(tmp_path, saved, fixed, expected):
    _, store = make(tmp_path, since=fixed)
    config.save_state({"since_hours": saved}, store.cfg["state_path"])
    FarmApp(store)
    assert store.refresh().since_hours == expected


def test_the_cursor_stays_near_when_the_selected_session_leaves_the_list(tmp_path):
    root, store = make(tmp_path, since=168)
    for sid, hours in (("a", 0.1), ("b", 1), ("c", 48), ("d", 100)):
        transcript(root, sid, hours)

    async def scenario(app, pilot):
        app.show_idle = True
        app._render_table()
        assert app.row_keys == ["a", "b", "c", "d"]
        await pilot.press("j", "j")
        await until(pilot, lambda: app.selected_id == "c")
        await pilot.press("t")                                # 24 hours: c and d leave the list
        await until(pilot, lambda: app.row_keys == ["a", "b"])
        await pilot.pause(0.2)
        assert app.selected_id == "b" and app.query_one("#agents").cursor_row == 1
        for _ in range(2):                                    # back to 7 days: the cursor stays on the same session
            await pilot.press("t")
        await until(pilot, lambda: len(app.row_keys) == 4)
        await pilot.pause(0.2)
        assert app.selected_id == "b" and app.query_one("#agents").cursor_row == 1
        app.selected_id, app.row_keys = "x", ["a", "x", "b"]
        assert app._stay_near(["a", "b"]) == "b" and app._stay_near(["a"]) == "a" and app._stay_near([]) is None

    play(store, scenario)
