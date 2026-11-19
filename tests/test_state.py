"""What agents-farm remembers between runs (the last new-session choices), and the auto permission mode."""

import json
import os
import stat

import pytest
from textual.widgets import Input, Static

from agents_farm import config, playground, runner
from agents_farm.app import FarmApp
from agents_farm.store import Store
from test_background import _store, calls, needs_ps, run  # noqa: F401  (calls is a fixture)


# ------------------------------------------------------------------------------ the auto mode

def test_auto_is_a_permission_mode_and_the_modes_that_skip_checks_are_not():
    assert runner.PERMISSION_MODES == ("default", "acceptEdits", "auto", "plan")
    assert runner.build_args(permission_mode="auto") == ["--permission-mode", "auto"]
    for bad in ("bypassPermissions", "dontAsk", "manual", ""):
        with pytest.raises(runner.RunError, match="permission mode"):
            runner.build_args(permission_mode=bad)


# ------------------------------------------------------------------------- the state file

def test_the_state_file_is_merged_and_private(tmp_path):
    path = str(tmp_path / "af" / "state.json")
    config.save_state({"a": 1}, path)
    config.save_state({"b": 2}, path)
    assert config.load_state(path) == {"a": 1, "b": 2}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert not [f for f in os.listdir(os.path.dirname(path)) if f.endswith(tuple("0123456789"))]      # no temp file is left


@pytest.mark.parametrize("content", ["not json", "[1, 2]", "42", "", "null"])
def test_a_broken_state_file_is_ignored(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    assert config.load_state(str(path)) == {}
    config.save_state({"x": 1}, str(path))                                   # and it is replaced by a good one
    assert config.load_state(str(path)) == {"x": 1}


def test_saving_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    config.save_state({"x": 1}, str(blocker / "sub" / "state.json"))        # the folder cannot be made: forgetting is harmless
    assert config.load_state(str(tmp_path / "missing" / "state.json")) == {}


def test_the_tests_use_their_own_state_file_never_the_real_one():
    assert config.STATE_PATH != os.path.join(os.path.expanduser("~/.agents-farm"), "state.json")
    assert "state-of-the-test" in config.STATE_PATH


def test_the_demo_keeps_its_own_state(tmp_path):
    base = str(tmp_path / "pg")
    playground.up(base)
    try:
        assert playground.make_store(base).cfg["state_path"].startswith(base)
    finally:
        playground.down(base)


# ------------------------------------------------------------------ the dialog remembers

def opts_line(app):
    return " ".join(str(app.screen.query_one("#ns-opts", Static).render()).split())


def store_with_state(tmp_path, **cfg):
    store = _store(tmp_path)
    store.cfg = dict(store.cfg, state_path=str(tmp_path / "state.json"), **cfg)
    return store


@needs_ps
def test_the_choices_of_a_started_session_are_remembered_for_the_next_run(tmp_path, calls):  # noqa: F811
    work = tmp_path / "work"
    work.mkdir()

    async def first_run(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(work) + "/"
        await pilot.pause(0.2)
        await pilot.press("ctrl+s", "ctrl+s", "ctrl+d", "ctrl+b")                 # acceptEdits, then auto; worktree; stay here
        assert "mode auto" in opts_line(app)
        await pilot.press("enter")
        await pilot.pause(1.0)

    run(first_run, store_with_state(tmp_path))
    assert calls["start"] == [(str(work), ["--permission-mode", "auto", "-w"])]
    assert config.load_state(str(tmp_path / "state.json"))["new_session"] == {"model": "", "mode": "auto", "worktree": True, "background": True}

    async def second_run(app, pilot):                                              # a new agents-farm: nothing was chosen yet
        await pilot.press("n")
        line = opts_line(app)
        assert "mode auto" in line and "worktree on" in line and "open now no" in line
        await pilot.press("escape")

    run(second_run, store_with_state(tmp_path))


@needs_ps
def test_a_cancelled_dialog_remembers_nothing(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("n", "ctrl+s", "ctrl+d", "escape")

    run(scenario, store_with_state(tmp_path))
    assert config.load_state(str(tmp_path / "state.json")) == {}


@needs_ps
@pytest.mark.parametrize("saved", [
    {"new_session": {"mode": "bypassPermissions", "model": "--evil", "worktree": "yes", "background": 1}},   # nothing here is valid
    {"new_session": "plain text"}, {"new_session": None}, {},
])
def test_what_is_not_valid_now_is_ignored(tmp_path, calls, saved):  # noqa: F811
    (tmp_path / "state.json").write_text(json.dumps(saved))

    async def scenario(app, pilot):
        await pilot.press("n")
        line = opts_line(app)
        assert "model default" in line and "mode default" in line and "worktree off" in line and "open now yes" in line
        await pilot.press("escape")

    run(scenario, store_with_state(tmp_path))


@needs_ps
def test_new_model_in_the_config_is_the_model_until_you_choose_one(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("n")
        assert "model haiku" in opts_line(app)
        await pilot.press("escape")

    run(scenario, store_with_state(tmp_path, new_model="haiku"))
    (tmp_path / "state.json").write_text(json.dumps({"new_session": {"model": "opus", "mode": "plan", "worktree": False, "background": False}}))
    run(lambda app, pilot: _expect(app, pilot, "model opus"), store_with_state(tmp_path, new_model="haiku"))   # the saved one wins


async def _expect(app, pilot, text):
    await pilot.press("n")
    assert text in opts_line(app)
    await pilot.press("escape")
