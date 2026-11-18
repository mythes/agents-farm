"""T9: background sessions (claude --bg, attach, stop). A fake `claude` script stands in; no real session is touched."""

import asyncio
import json
import os
import stat
import sys
import time
from contextlib import contextmanager
from datetime import timedelta

import pytest
from textual.widgets import DataTable, Input, Static, TextArea

from agents_farm import killer, runner
from agents_farm.app import AttachHint, ConfirmKill, FarmApp, NewSession
from agents_farm.demo import DemoStore
from agents_farm.model import utcnow
from agents_farm.render import detail_header
from agents_farm.runner import RunError
from agents_farm.store import Store
from test_registry import MY_PID, needs_ps, write

BG_SID = "bbbbbbbb-1111-2222-3333-444444444444"


def fake(folder, body):
    path = folder / "claude"
    path.write_text(f"#!{sys.executable}\nimport sys, json, os\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


# ------------------------------------------------------------------------ runner

def test_start_background_returns_the_short_id_and_passes_the_arguments(tmp_path):
    out = tmp_path / "argv.json"
    claude = fake(tmp_path, f"open({str(out)!r}, 'w').write(json.dumps([os.getcwd(), sys.argv[1:]]))\n"
                            "print('Starting background service…'); print('backgrounded · e75336f6 (idle — send a prompt to start)')")
    work = tmp_path / "w"
    work.mkdir()
    assert runner.start_background(str(work), ["--model", "haiku", "-w"], claude) == "e75336f6"
    assert json.loads(out.read_text()) == [os.path.realpath(work), ["--bg", "--model", "haiku", "-w"]]


def test_a_refusal_from_claude_is_shown_as_it_is(tmp_path):
    claude = fake(tmp_path, "sys.stderr.write('Workspace not trusted. Run `claude` in /x once.\\n'); sys.exit(1)")
    with pytest.raises(RunError, match="Workspace not trusted"):
        runner.start_background(str(tmp_path), [], claude)


def test_unexpected_output_is_an_error_and_is_sanitised(tmp_path):
    claude = fake(tmp_path, "print('weird" + "\\u202e" + " output')")
    with pytest.raises(RunError) as err:
        runner.start_background(str(tmp_path), [], claude)
    assert chr(0x202E) not in str(err.value)


@pytest.mark.parametrize("bad", ["", "xyz", "--force", "e75336f", "g75336f6", "../../etc/p", "-e75336f"])
def test_short_id_rejects_anything_that_is_not_8_hex_characters(bad):
    with pytest.raises(RunError, match="no id"):
        runner.short_id(bad)


def test_short_id_keeps_only_the_first_8_characters():
    assert runner.short_id("E75336F6-aaaa; rm -rf /") == "e75336f6"


def test_attach_and_stop_use_the_short_id_only(tmp_path):
    assert runner.attach_args(BG_SID) == ["attach", "bbbbbbbb"]
    out = tmp_path / "argv.json"
    claude = fake(tmp_path, f"open({str(out)!r}, 'w').write(json.dumps(sys.argv[1:]))\nprint('stopped bbbbbbbb')")
    assert runner.stop_background(BG_SID, claude) == "stopped bbbbbbbb"
    assert json.loads(out.read_text()) == ["stop", "bbbbbbbb"]


def test_stop_failure_is_an_error(tmp_path):
    claude = fake(tmp_path, "sys.stderr.write('no such session'); sys.exit(2)")
    with pytest.raises(RunError, match="no such session"):
        runner.stop_background(BG_SID, claude)


# ------------------------------------------------------------- registry and details

def _store(tmp_path, kind="bg", status="idle"):
    projects, sessions = tmp_path / "projects", tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    folder = projects / "-tmp-proj"
    folder.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    lines = [{"type": "user", "timestamp": ts, "cwd": str(tmp_path), "message": {"role": "user", "content": "hi"}},
             {"type": "assistant", "timestamp": ts, "message": {"id": "m1", "model": "claude-haiku-5-5", "stop_reason": "end_turn",
                                                               "usage": {"input_tokens": 1, "output_tokens": 1},
                                                               "content": [{"type": "text", "text": "done"}]}}]
    (folder / f"{BG_SID}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    write(sessions, MY_PID, sessionId=BG_SID, status=status, kind=kind, cwd=str(tmp_path))
    return Store(root=str(projects), since_hours=24, sessions_dir=str(sessions))


@needs_ps
def test_a_bg_pid_file_marks_the_agent_and_the_details(tmp_path):
    snap = _store(tmp_path).refresh()
    a = snap.agents[0]
    assert a.background is True
    assert "background" in detail_header(a, snap.updated, snap.warn, snap.crit, None).plain
    other = tmp_path / "other"
    other.mkdir()
    assert _store(other, kind="interactive").refresh().agents[0].background is False


# ------------------------------------------------- a new session with no transcript yet

def _no_transcript_store(tmp_path, kind="bg"):
    projects, sessions = tmp_path / "projects", tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    projects.mkdir(exist_ok=True)
    write(sessions, MY_PID, sessionId=BG_SID, status="idle", kind=kind, cwd=str(tmp_path), name="fresh one")
    return Store(root=str(projects), since_hours=24, sessions_dir=str(sessions))


@needs_ps
def test_a_running_session_without_a_transcript_is_still_listed(tmp_path):
    """`claude --bg` starts empty: there is no transcript until the first prompt."""
    snap = _no_transcript_store(tmp_path).refresh()
    assert [a.id for a in snap.agents] == [BG_SID]
    a = snap.agents[0]
    assert (a.background, a.transcript, a.pid) == (True, "", MY_PID)
    assert a.name == "fresh one" and a.status.value == "done" and a.status_note.startswith("no prompt yet")


@needs_ps
def test_it_stays_visible_however_long_it_waits_and_is_not_listed_twice_later(tmp_path):
    store = _no_transcript_store(tmp_path)
    assert store.refresh().agents[0].status.value == "done"
    now = utcnow()
    old = store._placeholder(store.registry.scan()[BG_SID], now)
    old.last_activity = now - timedelta(days=365)                                    # waiting for a year
    store._derive(old, now)
    assert old.status.value == "done"
    # the first prompt arrives: a transcript exists, and there is still one entry
    folder = tmp_path / "projects" / "-tmp-proj"
    folder.mkdir()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    (folder / f"{BG_SID}.jsonl").write_text(json.dumps({"type": "user", "timestamp": ts, "cwd": str(tmp_path),
                                                        "message": {"role": "user", "content": "hello"}}) + "\n")
    store.rediscover()
    assert [a.id for a in store.refresh().agents] == [BG_SID]


@needs_ps
def test_the_new_background_session_is_selected_and_can_be_attached_before_any_prompt(tmp_path, calls):
    async def scenario(app, pilot):
        assert app.selected_id == BG_SID
        await pilot.press("a")
        await pilot.pause(0.3)
        assert isinstance(app.screen, AttachHint)
        await pilot.press("enter")
        await pilot.pause(0.5)

    run(scenario, _no_transcript_store(tmp_path))
    assert calls["interactive"] == [(str(tmp_path), ["attach", "bbbbbbbb"])]


# ------------------------------------------------------------------------------ UI

def run(scenario, store, size=(130, 40)):
    async def main():
        app = FarmApp(store, interval=60.0, notify_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(1.0)

            @contextmanager
            def no_suspend():
                yield

            app.suspend = no_suspend
            return await scenario(app, pilot)

    return asyncio.run(main())


@pytest.fixture
def calls(monkeypatch):
    seen = {"interactive": [], "start": [], "stop": [], "kill": []}
    monkeypatch.setattr(runner, "run_interactive", lambda cwd, args, claude, env=None: seen["interactive"].append((cwd, args)) or 0)
    monkeypatch.setattr(runner, "start_background", lambda cwd, args, claude, env=None: seen["start"].append((cwd, args)) or "cccccccc")
    monkeypatch.setattr(runner, "stop_background", lambda sid, claude, env=None: seen["stop"].append(sid) or "stopped bbbbbbbb")
    monkeypatch.setattr(runner, "find_claude", lambda cfg=None: "/fake/claude")
    monkeypatch.setattr(killer, "kill", lambda *a, **k: seen["kill"].append(a) or (_ for _ in ()).throw(AssertionError("signal sent")))
    return seen


@needs_ps
def test_a_attaches_after_a_hint_and_runs_claude_attach(tmp_path, calls):
    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause(0.3)
        assert isinstance(app.screen, AttachHint)
        text = str(app.screen.query_one("#attach-body", Static).render())
        assert "Ctrl+Z" in text and "/exit" in text
        await pilot.press("enter")
        await pilot.pause(0.5)

    run(scenario, _store(tmp_path))
    assert calls["interactive"] == [(str(tmp_path), ["attach", "bbbbbbbb"])]


@needs_ps
def test_escape_on_the_hint_attaches_nothing(tmp_path, calls):
    async def scenario(app, pilot):
        await pilot.press("a", "escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, AttachHint)

    run(scenario, _store(tmp_path))
    assert calls["interactive"] == []


@needs_ps
def test_a_on_a_normal_session_does_nothing(tmp_path, calls):
    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, AttachHint)

    run(scenario, _store(tmp_path, kind="interactive"))
    assert calls["interactive"] == []


@needs_ps
def test_x_on_a_background_session_uses_claude_stop_and_no_signal(tmp_path, calls):
    async def scenario(app, pilot):
        await pilot.press("x")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmKill)
        assert "claude stop" in str(app.screen.query_one("#kill-body", Static).render())
        await pilot.press("y")
        await pilot.pause(1.0)

    run(scenario, _store(tmp_path))
    assert calls["stop"] == [BG_SID] and calls["kill"] == []


@needs_ps
def test_n_with_ctrl_b_starts_in_the_background_and_warns_about_default_mode(tmp_path, calls):
    work = tmp_path / "work"
    work.mkdir()

    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(work) + "/"
        await pilot.pause(0.2)
        await pilot.press("ctrl+b")
        text = str(app.screen.query_one("#ns-opts", Static).render())
        assert "background on" in text
        info = str(app.screen.query_one("#ns-info", Static).render())
        assert "Ctrl+Z" in info and "not /exit" in info                      # the way back is shown
        assert "stops at its first permission request" in str(app.screen.query_one("#ns-warn", Static).render())
        await pilot.press("ctrl+s")                                         # acceptEdits: no warning any more
        assert str(app.screen.query_one("#ns-warn", Static).render()).strip() == ""
        await pilot.press("enter")
        await pilot.pause(1.0)
        assert not isinstance(app.screen, NewSession)

    run(scenario, _store(tmp_path))
    assert calls["interactive"] == []                                         # nothing took over the terminal
    assert calls["start"] == [(str(work), ["--permission-mode", "acceptEdits"])]


def test_demo_mode_starts_attaches_and_stops_nothing(tmp_path, calls):
    async def scenario(app, pilot):
        await pilot.press("n", "ctrl+b", "enter")
        await pilot.pause(0.5)
        await pilot.press("a")
        await pilot.press("x")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, AttachHint)
        await pilot.press("escape", "n")
        await pilot.press("escape")

    run(scenario, DemoStore())
    assert calls == {"interactive": [], "start": [], "stop": [], "kill": []}


@needs_ps
def test_ctrl_f_switches_to_the_prompt_field_and_the_prompt_is_sent_first(tmp_path, calls):
    work = tmp_path / "work"
    work.mkdir()

    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(work) + "/"
        await pilot.pause(0.2)
        await pilot.press("ctrl+b", "ctrl+s")
        await pilot.press("ctrl+f")
        assert app.screen.query_one("#ns-prompt", TextArea).has_focus
        await pilot.press("tab", "right")                                    # these must not open a folder from the prompt editor
        assert app.screen.query_one("#ns-dir", Input).value.endswith("/work/")
        app.screen.query_one("#ns-prompt", TextArea).text = "--evil start"
        await pilot.press("ctrl+e")                                          # Enter would add a new line: Ctrl+E starts
        await pilot.pause(1.0)
        assert not isinstance(app.screen, NewSession)

    run(scenario, _store(tmp_path))
    assert calls["start"] == [(str(work), [" --evil start", "--permission-mode", "acceptEdits"])]


@needs_ps
def test_enter_on_dot_dot_in_the_prompt_field_does_not_start(tmp_path, calls):
    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(tmp_path) + "/"
        await pilot.pause(0.2)
        await pilot.press("down", "ctrl+f", "ctrl+e")                        # the ".." row
        await pilot.pause(0.3)
        assert isinstance(app.screen, NewSession)
        assert "marked row is .." in str(app.screen.query_one("#ns-error", Static).render())
        await pilot.press("escape")

    run(scenario, _store(tmp_path))
    assert calls["start"] == [] and calls["interactive"] == []


@needs_ps
def test_a_normal_session_also_gets_the_first_prompt(tmp_path, calls):
    work = tmp_path / "work"
    work.mkdir()

    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(work) + "/"
        await pilot.pause(0.2)
        app.screen.query_one("#ns-prompt", TextArea).text = "explain the repo"
        await pilot.press("enter")
        await pilot.pause(1.0)

    run(scenario, _store(tmp_path))
    assert calls["interactive"] == [(str(work), ["explain the repo"])] and calls["start"] == []


def test_the_dialog_always_says_how_to_leave_both_kinds_of_session(calls):
    """Whatever Ctrl+B is set to, both hints are on screen."""
    async def scenario(app, pilot):
        await pilot.press("n")
        for _ in range(2):
            info = str(app.screen.query_one("#ns-info", Static).render())
            assert "Ctrl+Z" in info and "not /exit" in info and "Ctrl+B" in info       # background: how to leave
            assert "Normal session" in info and "/exit" in info                         # normal: how to leave
            await pilot.press("ctrl+b")
        await pilot.press("escape")

    run(scenario, DemoStore())


@needs_ps
def test_ctrl_f_gives_the_whole_area_to_a_multi_line_prompt(tmp_path, calls):
    work = tmp_path / "work"
    work.mkdir()

    async def scenario(app, pilot):
        await pilot.press("n")
        app.screen.query_one("#ns-dir", Input).value = str(work) + "/"
        await pilot.pause(0.3)
        box = app.screen.query_one("#ns-prompt", TextArea)
        assert app.screen.query_one("#ns-main").display and not box.display          # folders are shown, the editor is hidden
        assert "writes it" in str(app.screen.query_one("#ns-prompt-line", Static).render())

        await pilot.press("ctrl+f")
        await pilot.pause(0.3)
        assert not app.screen.query_one("#ns-main").display and box.display and box.has_focus   # the editor took the place
        assert "Start" in str(app.screen.query_one("#ns-hints", Static).render())
        await pilot.press(*"first line", "enter", *"second line")                    # Enter is a new line here
        assert box.text == "first line\nsecond line"
        table = app.screen.query_one("#ns-list", DataTable)
        row = table.cursor_row
        await pilot.press("up", "down", "down")                                      # the arrows move in the text, not in the folder list
        assert table.cursor_row == row

        await pilot.press("ctrl+f")                                                  # back to the folders, the text is kept
        await pilot.pause(0.3)
        assert app.screen.query_one("#ns-main").display and not box.display
        line = str(app.screen.query_one("#ns-prompt-line", Static).render())
        assert "first line" in line and "+1 more line" in line
        assert "Open folder" in str(app.screen.query_one("#ns-hints", Static).render())

        await pilot.press("ctrl+f", "ctrl+e")                                        # start from the editor
        await pilot.pause(1.0)
        assert not isinstance(app.screen, NewSession)

    run(scenario, _store(tmp_path))
    assert calls["interactive"] == [(str(work), ["first line\nsecond line"])]
