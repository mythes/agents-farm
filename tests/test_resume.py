"""T4: resume a session. A fake `claude` stands in, so no real session is touched."""

import json
import time

import pytest
from textual.widgets import Static

from agents_farm import runner
from agents_farm.app import ConfirmFork, ConfirmResume, Explain
from demo_store import DemoStore
from agents_farm.runner import RunError
from agents_farm.store import Store
from test_background import BG_SID, _store, calls, needs_ps, run  # noqa: F401  (calls is a fixture)


# ------------------------------------------------------------------------ runner

@pytest.mark.parametrize("bad", ["", "-x", "--fork-session", "a b", "a;b", "x" * 200, "../etc"])
def test_resume_args_reject_anything_that_could_be_an_option_or_a_shell_word(bad):
    with pytest.raises(RunError, match="no id"):
        runner.resume_args(bad)


def test_resume_args():
    assert runner.resume_args(BG_SID) == ["--resume", BG_SID]
    assert runner.resume_args(BG_SID, fork=True) == ["--resume", BG_SID, "--fork-session"]


def test_a_session_that_ended_is_continued_and_a_desktop_chat_defaults_to_a_fork():
    plan = runner.resume_plan("cli")
    assert plan.allowed == ("resume",) and plan.primary == "resume"
    desktop = runner.resume_plan("claude-desktop")
    assert desktop.primary == "fork" and desktop.allowed == ("resume", "fork") and any("Desktop" in t for _, t in desktop.lines)


# ----------------------------------------------------------------------- a session that ended

def _dead_store(tmp_path, origin="cli", cwd=None, registry=True):
    """A transcript and no process: the session has ended. With registry=False there is no folder with process
    files at all (an older Claude Code), so we cannot tell whether it runs."""
    projects, sessions = tmp_path / "projects", tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    folder = projects / "-tmp-proj"
    folder.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    lines = [{"type": "user", "timestamp": ts, "cwd": cwd or str(tmp_path), "entrypoint": origin,
              "message": {"role": "user", "content": "hello"}},
             {"type": "assistant", "timestamp": ts, "message": {"id": "m1", "model": "claude-haiku-5-5", "stop_reason": "end_turn",
                                                               "usage": {"input_tokens": 1, "output_tokens": 1},
                                                               "content": [{"type": "text", "text": "done"}]}}]
    (folder / f"{BG_SID}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    if not registry:
        sessions.rmdir()
    return Store(root=str(projects), since_hours=24, sessions_dir=str(sessions))


def test_the_transcript_tells_where_a_session_was_started(tmp_path):
    agent = _dead_store(tmp_path, origin="claude-desktop").refresh().agents[0]
    assert agent.origin == "claude-desktop" and agent.pid is None


@pytest.mark.parametrize("key", ["y", "enter"])
def test_r_continues_in_the_background_and_opens_it(tmp_path, calls, key):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("r")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmResume)
        body = str(app.screen.query_one("#resume-body", Static).render())
        assert "Continue this session" in body and "fork" not in body.lower().replace("forks", "")   # a session of a terminal: continue only
        await pilot.press(key)
        await pilot.pause(1.0)

    run(scenario, _dead_store(tmp_path))
    assert calls["start"] == [(str(tmp_path), ["--resume", BG_SID])]                 # claude --bg --resume ...
    assert calls["interactive"] == [(str(tmp_path), ["attach", "cccccccc"])]         # then claude attach
    assert calls["leave"] == [True]                                                  # Ctrl+Z leaves it running


def test_escape_and_n_continue_nothing(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("r", "escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, ConfirmResume)
        await pilot.press("r", "n")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, ConfirmResume)

    run(scenario, _dead_store(tmp_path))
    assert calls["start"] == [] and calls["interactive"] == []


@pytest.mark.parametrize("key, args", [("enter", ["--resume", BG_SID, "--fork-session"]), ("y", ["--resume", BG_SID])])
def test_a_desktop_chat_defaults_to_a_fork_and_can_still_be_continued(tmp_path, calls, key, args):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("r")
        await pilot.pause(0.3)
        assert "Claude Desktop" in str(app.screen.query_one("#resume-body", Static).render())
        await pilot.press(key)
        await pilot.pause(1.0)

    run(scenario, _dead_store(tmp_path, origin="claude-desktop"))
    assert calls["start"] == [(str(tmp_path), args)]


@pytest.mark.parametrize("key", ["enter", "y"])
def test_f_forks_a_session_that_has_ended(tmp_path, calls, key):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("f")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmFork)
        body = str(app.screen.query_one("#fork-body", Static).render())
        assert "same history" in body and "original is not changed" in body
        await pilot.press(key)
        await pilot.pause(1.0)

    run(scenario, _dead_store(tmp_path))
    assert calls["start"] == [(str(tmp_path), ["--resume", BG_SID, "--fork-session"])]
    assert calls["interactive"] == [(str(tmp_path), ["attach", "cccccccc"])]


def test_escape_cancels_the_fork(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("f", "escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, ConfirmFork)

    run(scenario, _dead_store(tmp_path))
    assert calls["start"] == []


@needs_ps
@pytest.mark.parametrize("kind", ["interactive", "bg"])
def test_f_forks_a_session_that_runs_and_says_the_original_keeps_running(tmp_path, calls, kind):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("f")
        await pilot.pause(0.3)
        assert "keeps running" in str(app.screen.query_one("#fork-body", Static).render())
        await pilot.press("enter")
        await pilot.pause(1.0)

    run(scenario, _store(tmp_path, kind=kind))
    assert calls["start"] == [(str(tmp_path), ["--resume", BG_SID, "--fork-session"])]


def test_when_we_cannot_tell_whether_it_runs_continue_is_explained_and_fork_works(tmp_path, calls):  # noqa: F811
    """No folder with process files (an older Claude Code): continuing in place could make two writers."""
    async def scenario(app, pilot):
        assert app._selected().live is None
        await pilot.press("r")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Explain) and "cannot tell" in str(app.screen.query_one("#explain-body", Static).render())
        await pilot.press("f")                                                       # the option key forks
        await pilot.pause(0.4)
        assert isinstance(app.screen, ConfirmFork)
        await pilot.press("enter")
        await pilot.pause(1.0)

    run(scenario, _dead_store(tmp_path, registry=False))
    assert calls["start"] == [(str(tmp_path), ["--resume", BG_SID, "--fork-session"])]


def test_a_session_whose_folder_is_gone_is_neither_continued_nor_forked(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        for key in ("r", "f"):
            await pilot.press(key)
            await pilot.pause(0.3)
            assert isinstance(app.screen, Explain)
            await pilot.press("escape")
            await pilot.pause(0.2)

    run(scenario, _dead_store(tmp_path, cwd=str(tmp_path / "gone")))
    assert calls["start"] == []


@pytest.mark.parametrize("key, args", [("r", ["--resume", BG_SID]), ("f", ["--resume", BG_SID, "--fork-session"])])
@pytest.mark.parametrize("message", ["Workspace not trusted.", "error: unknown option '--bg'"])
def test_a_refused_background_start_falls_back_to_a_plain_run(tmp_path, calls, monkeypatch, key, args, message):  # noqa: F811
    monkeypatch.setattr(runner, "start_background", lambda *a, **k: (_ for _ in ()).throw(runner.BackgroundRefused(message)))

    async def scenario(app, pilot):
        await pilot.press(key, "enter")
        await pilot.pause(1.0)

    run(scenario, _dead_store(tmp_path))
    assert calls["job"] == [(str(tmp_path), args, "end")]      # a plain `claude --resume`; Ctrl+Z leaves an idle one


@pytest.mark.parametrize("key, args", [("r", ["--resume", BG_SID]), ("f", ["--resume", BG_SID, "--fork-session"])])
def test_use_background_false_runs_in_the_foreground(tmp_path, calls, key, args):  # noqa: F811
    store = _dead_store(tmp_path)
    store.cfg = dict(store.cfg, use_background=False)

    async def scenario(app, pilot):
        await pilot.press(key, "enter")
        await pilot.pause(1.0)

    run(scenario, store)
    assert calls["start"] == [] and calls["job"] == [(str(tmp_path), args, "end")]


def test_demo_data_resumes_nothing(calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("down", "down", "down", "down", "down", "down")
        for key in ("r", "f"):
            await pilot.press(key)
            await pilot.pause(0.4)
            await pilot.press("y")
            await pilot.pause(0.4)
            await pilot.press("escape")
            await pilot.pause(0.2)

    run(scenario, DemoStore())
    assert calls["start"] == [] and calls["interactive"] == []


def test_ctrl_r_refreshes_and_plain_r_no_longer_does(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        before = app.snap
        await pilot.press("ctrl+r")
        await pilot.pause(0.8)
        assert app.snap is not None and app.snap.updated >= before.updated

    run(scenario, _dead_store(tmp_path))
