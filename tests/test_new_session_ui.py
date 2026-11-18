"""T3 in the UI: the n key opens a folder browser, options have hot keys, and demo mode starts nothing."""

import asyncio
import os
import time
from contextlib import contextmanager

import pytest
from textual.widgets import DataTable, Input, Static

from agents_farm import runner
from agents_farm.app import FarmApp, ModelPicker, NewSession
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


def labels(app):
    return [r.label for r in app.screen._rows]


async def typed(pilot, app, text):
    app.screen.query_one("#ns-dir", Input).value = text
    await pilot.pause(0.2)


def tree(tmp_path):
    for name in ("api-refactor", "docs-writer", "lint-pass"):
        (tmp_path / name).mkdir(exist_ok=True)
    (tmp_path / "api-refactor" / "src").mkdir(exist_ok=True)
    return str(tmp_path)


def test_n_opens_the_dialog_and_escape_cancels(no_run):
    async def scenario(app, pilot):
        await pilot.press("n")
        assert isinstance(app.screen, NewSession)
        assert app.screen.query_one("#new-body").border_title == "NEW SESSION"
        assert "model default   mode default   worktree off" in str(app.screen.query_one("#ns-opts", Static).render())
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, NewSession)

    run(scenario)
    assert no_run == []


def test_the_path_field_drives_the_list(no_run, tmp_path):
    base = tree(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("n")
        await typed(pilot, app, base + "/")
        assert labels(app)[:2] == ["use this folder", ".."] and "docs-writer/" in labels(app)
        await typed(pilot, app, base + "/apirf")                      # fuzzy match in that folder
        assert labels(app) == ["api-refactor/"]
        await typed(pilot, app, base + "/api-refactor")               # delete the slash: its neighbours appear again
        await typed(pilot, app, base + "/")
        assert "lint-pass/" in labels(app)
        await pilot.press("escape")

    run(scenario)


def test_tab_opens_the_highlighted_folder_and_the_preview_shows_its_content(no_run, tmp_path):
    base = tree(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("n")
        await typed(pilot, app, base + "/api")
        assert labels(app) == ["api-refactor/"]
        assert "src/" in str(app.screen.query_one("#ns-preview", Static).render())
        await pilot.press("tab")
        await pilot.pause(0.2)
        assert app.screen.query_one("#ns-dir", Input).value.endswith("/api-refactor/")
        assert labels(app)[:3] == ["use this folder", "..", "src/"]
        await pilot.press("escape")

    run(scenario)


def test_up_and_down_move_in_the_list_while_you_type(no_run, tmp_path):
    base = tree(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("n")
        await typed(pilot, app, base + "/")
        table = app.screen.query_one("#ns-list", DataTable)
        assert table.cursor_row == 0
        await pilot.press("down", "down")
        assert table.cursor_row == 2
        await pilot.press("up")
        assert table.cursor_row == 1
        await pilot.press("escape")

    run(scenario)


def test_the_right_arrow_moves_the_text_cursor_unless_it_is_at_the_end(no_run, tmp_path):
    base = tree(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("n")
        await typed(pilot, app, base + "/api")
        field = app.screen.query_one("#ns-dir", Input)
        field.cursor_position = 3
        await pilot.press("right")
        assert field.cursor_position == 4 and field.value.endswith("/api")        # only moved
        await pilot.press("end", "right")
        await pilot.pause(0.2)
        assert field.value.endswith("/api-refactor/")                             # opened
        await pilot.press("escape")

    run(scenario)


def test_hot_keys_change_the_options_and_the_summary(no_run):
    async def scenario(app, pilot):
        await pilot.press("n")
        await pilot.press("ctrl+p")
        await pilot.press("ctrl+t")
        text = str(app.screen.query_one("#ns-opts", Static).render())
        assert "mode acceptEdits" in text and "worktree on" in text
        await pilot.press("ctrl+p", "ctrl+p")
        assert "mode default" in str(app.screen.query_one("#ns-opts", Static).render())
        await pilot.press("escape")

    run(scenario)
    assert app_palette_is_off()


def app_palette_is_off():
    return FarmApp.ENABLE_COMMAND_PALETTE is False


def test_the_model_list_filters_and_selects(no_run):
    async def scenario(app, pilot):
        await pilot.press("n")
        await pilot.press("ctrl+o")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ModelPicker)
        names = [c.value for c in app.screen._shown]
        assert names[:5] == ["", "fable", "opus", "sonnet", "haiku"]
        app.screen.query_one("#mp-filter", Input).value = "son"
        await pilot.pause(0.2)
        assert app.screen._shown[0].value == "sonnet"
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, NewSession)
        assert "model sonnet" in str(app.screen.query_one("#ns-opts", Static).render())
        await pilot.press("escape")

    run(scenario)


def test_a_model_typed_by_hand_is_checked(no_run):
    async def scenario(app, pilot):
        await pilot.press("n", "ctrl+o")
        await pilot.pause(0.3)
        field = app.screen.query_one("#mp-filter", Input)
        field.value = "--bad"
        await pilot.pause(0.2)
        await pilot.press("down", "enter") if len(app.screen._shown) > 1 else await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ModelPicker)                          # still open
        assert "model name" in str(app.screen.query_one("#mp-error", Static).render())
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert isinstance(app.screen, NewSession)
        assert "model default" in str(app.screen.query_one("#ns-opts", Static).render())
        await pilot.press("escape")

    run(scenario)


def test_demo_mode_starts_nothing(no_run, tmp_path):
    async def scenario(app, pilot):
        await pilot.press("n")
        await typed(pilot, app, str(tmp_path) + "/")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert not isinstance(app.screen, NewSession)

    run(scenario)
    assert no_run == []


def test_nothing_to_start_in_stays_in_the_dialog(no_run, tmp_path):
    async def scenario(app, pilot):
        await pilot.press("n")
        await typed(pilot, app, str(tmp_path) + "/zzzzz")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, NewSession)
        assert "no folder to start in" in str(app.screen.query_one("#ns-error", Static).render())
        await pilot.press("escape")

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
    (work / "proj").mkdir(parents=True)
    seen = []

    def fake_run(cwd, args, claude, env=None):
        seen.append((cwd, args, claude, env.get("MY_VAR")))
        _transcript(projects, new_sid)
        return 0

    monkeypatch.setattr(runner, "run_interactive", fake_run)
    claude = fake_claude(tmp_path)
    store = Store(root=str(projects), since_hours=24, sessions_dir=str(sessions))
    store.cfg = dict(store.cfg, claude_bin=claude, claude_args=["--verbose"], claude_env={"MY_VAR": "1"}, models=["my-model"])

    async def scenario(app, pilot):
        @contextmanager
        def no_suspend():
            yield

        app.suspend = no_suspend
        await pilot.press("n")
        await typed(pilot, app, str(work) + "/pro")
        await pilot.press("ctrl+o")
        await pilot.pause(0.3)
        app.screen.query_one("#mp-filter", Input).value = "my-model"
        await pilot.pause(0.2)
        await pilot.press("enter")
        await pilot.pause(0.3)
        await pilot.press("ctrl+p", "ctrl+p", "ctrl+t")                      # plan + worktree
        await pilot.press("enter")
        end = time.monotonic() + 8
        while time.monotonic() < end and app.selected_id != new_sid:
            await pilot.pause(0.2)
        assert app.selected_id == new_sid
        await pilot.press("n")                                               # the next dialog starts with the same choices
        assert "model my-model   mode plan   worktree on" in str(app.screen.query_one("#ns-opts", Static).render())
        await pilot.press("escape")

    run(scenario, store)
    assert seen == [(str(work / "proj"), ["--model", "my-model", "--permission-mode", "plan", "--verbose", "-w"], claude, "1")]
