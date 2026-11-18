"""T3 in the UI: the n key opens a dialog, bad input stays in the dialog, and demo mode starts nothing."""

import asyncio
import os
import time

import pytest
from textual.widgets import Checkbox, Input, Select, Static

from agents_farm import runner
from agents_farm.app import FarmApp, NewSession
from agents_farm.demo import DemoStore
from agents_farm.store import Store
from test_registry import _transcript
from test_runner import fake_claude


def run(scenario, store=None, size=(130, 40)):
    async def main():
        app = FarmApp(store or DemoStore(), interval=60.0, notify_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(1.0)
            return await scenario(app, pilot)

    return asyncio.run(main())


@pytest.fixture
def no_run(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run_interactive", lambda *a, **k: calls.append(a) or 0)
    return calls


def test_n_opens_the_dialog_and_escape_cancels(no_run):
    async def scenario(app, pilot):
        await pilot.press("n")
        assert isinstance(app.screen, NewSession)
        assert app.screen.query_one("#ns-mode", Select).value == "default"
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, NewSession)

    run(scenario)
    assert no_run == []


def test_the_mode_list_has_no_unsafe_mode(no_run):
    async def scenario(app, pilot):
        await pilot.press("n")
        values = [v for _, v in app.screen.query_one("#ns-mode", Select)._options if isinstance(v, str)]
        assert values == list(runner.PERMISSION_MODES)
        await pilot.press("escape")

    run(scenario)


def test_a_missing_folder_stays_in_the_dialog_with_a_message(no_run, tmp_path):
    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(tmp_path / "gone")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, NewSession)
        assert "does not exist" in str(app.screen.query_one("#ns-error", Static).render())
        app.screen.query_one("#ns-dir", Input).value = str(tmp_path)
        app.screen.query_one("#ns-model", Input).value = "--bad"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, NewSession)
        assert "model name" in str(app.screen.query_one("#ns-error", Static).render())
        await pilot.press("escape")

    run(scenario)
    assert no_run == []


def test_demo_mode_starts_nothing(no_run, tmp_path):
    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(tmp_path)
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert not isinstance(app.screen, NewSession)

    run(scenario)
    assert no_run == []


def test_enter_starts_claude_with_the_choices_and_selects_the_new_session(tmp_path, monkeypatch):
    """A fake claude stands in. The terminal hand-over (suspend) is replaced because the test has no real terminal."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    projects = tmp_path / "projects"
    old_sid, new_sid = "aaaaaaaa-0000-0000-0000-00000000000a", "bbbbbbbb-0000-0000-0000-00000000000b"
    _transcript(projects, old_sid)
    work = tmp_path / "work"
    work.mkdir()
    seen = []

    def fake_run(cwd, args, claude, env=None):
        seen.append((cwd, args, claude, env.get("MY_VAR")))
        _transcript(projects, new_sid)            # the new session writes its transcript
        return 0

    monkeypatch.setattr(runner, "run_interactive", fake_run)
    claude = fake_claude(tmp_path)
    store = Store(root=str(projects), since_hours=24, sessions_dir=str(sessions))
    store.cfg = dict(store.cfg, claude_bin=claude, claude_args=["--verbose"], claude_env={"MY_VAR": "1"})

    async def scenario(app, pilot):
        from contextlib import contextmanager

        @contextmanager
        def no_suspend():
            yield

        app.suspend = no_suspend
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(work)
        app.screen.query_one("#ns-model", Input).value = "opus"
        app.screen.query_one("#ns-mode", Select).value = "plan"
        app.screen.query_one("#ns-worktree", Checkbox).value = True
        await pilot.press("enter")
        end = time.monotonic() + 8
        while time.monotonic() < end and app.selected_id != new_sid:
            await pilot.pause(0.2)
        assert app.selected_id == new_sid

    run(scenario, store)
    assert seen == [(str(work), ["--model", "opus", "--permission-mode", "plan", "--verbose", "-w"], claude, "1")]
