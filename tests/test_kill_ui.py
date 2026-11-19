"""T2 in the UI: the x key asks first, the default answer is No, and demo data never receives a signal."""

import asyncio
import os
import signal
import time

import pytest

from agents_farm import killer
from agents_farm.app import ConfirmKill, Explain, FarmApp
from agents_farm.config import DEFAULTS
from demo_store import DemoStore
from agents_farm.store import Store
from test_killer import IGNORE_TERM, SID, log_lines, pidfile, procs  # noqa: F401  (procs is a fixture)
from test_registry import _transcript

needs_ps = pytest.mark.skipif(not killer.process_start_times([os.getpid()]), reason="ps is not available")


def run(scenario, store=None, size=(130, 32)):
    async def main():
        app = FarmApp(store or DemoStore(), interval=60.0, notify_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(1.0)
            return await scenario(app, pilot)

    return asyncio.run(main())


def asking(app):
    """True when a dialog is open and its text is already on screen."""
    return isinstance(app.screen, ConfirmKill) and len(app.screen.query("#kill-body")) > 0


def dialog_text(app):
    return str(app.screen.query_one("#kill-body").render())


async def wait_for(pilot, condition, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        await pilot.pause(0.2)
    return condition()


@pytest.fixture
def no_signal(monkeypatch):
    """Any attempt to signal a process fails the test."""
    calls = []
    monkeypatch.setattr(killer, "kill", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("signal sent")))
    return calls


# ---------------------------------------------------------------- asking first

def test_x_opens_a_dialog_with_the_warnings_and_enter_cancels(no_signal):
    async def scenario(app, pilot):
        await pilot.press("x")
        assert asking(app)
        assert asking(app)
        body = dialog_text(app)
        assert "pid 40217" in body and "Desktop" in body and "next message" in body and "history is kept" in body
        await pilot.press("enter")                                  # the default answer is No
        assert not asking(app)

    run(scenario)
    assert no_signal == []


@pytest.mark.parametrize("key", ["n", "escape"])
def test_n_and_escape_cancel(no_signal, key):
    async def scenario(app, pilot):
        await pilot.press("x")
        assert asking(app)
        await pilot.press(key)
        await pilot.pause(0.3)
        assert not asking(app)

    run(scenario)
    assert no_signal == []


def test_a_busy_agent_gets_the_stronger_warning(no_signal):
    async def scenario(app, pilot):
        for _ in range(len(app.row_keys)):                          # api-refactor is busy
            if app.selected_id == "demo-api-refactor":
                break
            await pilot.press("j")
            await pilot.pause(0.1)
        await pilot.press("x")
        assert asking(app)
        assert "current turn will be lost" in dialog_text(app)
        await pilot.press("n")

    run(scenario)


def test_demo_data_never_receives_a_signal(no_signal):
    async def scenario(app, pilot):
        await pilot.press("x")
        await pilot.press("y")                                      # even a "yes" does nothing in demo mode
        await pilot.pause(0.5)
        assert not asking(app)

    run(scenario)
    assert no_signal == []


def test_no_dialog_for_a_subagent_a_dead_session_or_when_turned_off(no_signal):
    async def scenario(app, pilot):
        async def go(row_id):
            for _ in range(len(app.row_keys) * 2):
                if app.selected_id == row_id:
                    return
                key = "j" if app.row_keys.index(row_id) > app.row_keys.index(app.selected_id) else "k"
                await pilot.press(key)
                await pilot.pause(0.05)
            raise AssertionError(f"could not select {row_id}")

        async def refused():
            """No stop dialog: a pop-up explains why (see test_capabilities_ui). Close it to go on."""
            await pilot.press("x")
            await pilot.pause(0.2)
            assert not asking(app)
            assert isinstance(app.screen, Explain)
            await pilot.press("escape")
            await pilot.pause(0.2)

        await go("demo-api-refactor/agent-1")                       # a subagent: no process of its own
        await refused()
        await go("demo-lint-pass")                                   # finished: no process
        await refused()
        await go("demo-docs-writer")
        app.store.cfg = dict(DEFAULTS, allow_kill=False)             # turned off in the config
        await refused()

    run(scenario)
    assert no_signal == []


# -------------------------------------------------------- real (fake) processes

def real(tmp_path, monkeypatch, p, shift=0):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    pidfile(sessions, p.pid, shift=shift)
    _transcript(tmp_path / "projects", SID)
    log = str(tmp_path / "actions.log")
    monkeypatch.setattr(killer, "ACTIONS_LOG", log)                  # never write to the real log
    return Store(root=str(tmp_path / "projects"), since_hours=24, sessions_dir=str(sessions)), log


@needs_ps
def test_yes_stops_the_process_and_writes_the_log(tmp_path, monkeypatch, procs):  # noqa: F811
    p = procs()
    store, log = real(tmp_path, monkeypatch, p)

    async def scenario(app, pilot):
        await pilot.press("x")
        assert asking(app) and "cli" not in "".join(app.row_keys)
        await pilot.press("y")
        assert await wait_for(pilot, lambda: p.poll() is not None)
        assert p.poll() == -signal.SIGTERM
        await pilot.pause(0.5)
        assert not asking(app)

    run(scenario, store)
    entry = log_lines(log)[-1]
    assert (entry["signal"], entry["pid"], entry["result"]) == ("SIGTERM", p.pid, "sent, the process ended")


@needs_ps
def test_cancel_leaves_the_process_alone(tmp_path, monkeypatch, procs):  # noqa: F811
    p = procs()
    store, log = real(tmp_path, monkeypatch, p)

    async def scenario(app, pilot):
        await pilot.press("x")
        await pilot.press("n")
        await pilot.pause(1.0)

    run(scenario, store)
    assert p.poll() is None and log_lines(log) == []


@needs_ps
def test_a_process_that_ignores_sigterm_gets_a_second_question_for_sigkill(tmp_path, monkeypatch, procs):  # noqa: F811
    monkeypatch.setattr(killer, "TERM_WAIT_S", 0.5)
    p = procs(IGNORE_TERM)
    store, log = real(tmp_path, monkeypatch, p)

    async def scenario(app, pilot):
        await pilot.press("x")
        await pilot.press("y")
        assert await wait_for(pilot, lambda: not asking(app))        # the first dialog is closed
        assert await wait_for(pilot, lambda: asking(app))            # the SIGKILL question
        body = dialog_text(app)
        assert "did not stop" in body and "SIGKILL" in body
        assert p.poll() is None
        await pilot.press("n")                                       # declining leaves it running
        assert await wait_for(pilot, lambda: not asking(app))
        await pilot.pause(0.5)
        assert p.poll() is None
        await pilot.press("x")
        assert await wait_for(pilot, lambda: asking(app))
        await pilot.press("y")
        assert await wait_for(pilot, lambda: not asking(app))
        assert await wait_for(pilot, lambda: asking(app))            # asked about SIGKILL again
        await pilot.press("y")
        assert await wait_for(pilot, lambda: p.poll() is not None)
        assert p.poll() == -signal.SIGKILL

    run(scenario, store)
    assert [e["signal"] for e in log_lines(log)][-1] == "SIGKILL"


@needs_ps
def test_a_session_with_a_reused_pid_is_not_even_listed_as_running(tmp_path, monkeypatch, procs):  # noqa: F811
    p = procs()
    store, log = real(tmp_path, monkeypatch, p, shift=-3600)         # the file does not match the process

    async def scenario(app, pilot):
        assert app._selected().pid is None
        await pilot.press("x")
        assert not asking(app)

    run(scenario, store)
    assert p.poll() is None and log_lines(log) == []


@needs_ps
def test_a_pid_that_changed_after_the_list_was_drawn_is_refused_even_after_yes(tmp_path, monkeypatch, procs):  # noqa: F811
    """Between the dialog and `y` the pid is reused by another program: the check is made again."""
    p = procs()
    store, log = real(tmp_path, monkeypatch, p)

    async def scenario(app, pilot):
        await pilot.press("x")
        assert asking(app)
        pidfile(tmp_path / "sessions", p.pid, shift=-3600)           # now the file says it started an hour earlier
        await pilot.press("y")
        await pilot.pause(1.5)

    run(scenario, store)
    assert p.poll() is None
    assert "reused by another program" in log_lines(log)[-1]["result"]
