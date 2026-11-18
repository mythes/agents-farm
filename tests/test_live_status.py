"""T8: the status from the pid file (idle / busy / waiting) and how it combines with the transcript and hooks."""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from agents_farm.events import HookState
from agents_farm.model import Agent, Snapshot, Status
from agents_farm.render import top_bar
from agents_farm.store import Store
from test_registry import MY_PID, needs_ps, write

NOW = datetime.now(timezone.utc)


def make_store(tmp_path):
    return Store(root=str(tmp_path / "projects"), since_hours=24)


def agent(age=5, live=None, pid=4242, last_kind="assistant", pending=0, stop="end_turn", sid="s1"):
    a = Agent(id=sid, transcript="", last_activity=NOW - timedelta(seconds=age), last_kind=last_kind,
              pending_tools=pending, stop_reason=stop)
    a.pid, a.live_status = (pid, live) if live else (None, "")
    return a


def derive(store, a):
    store._derive(a, NOW)
    return a.status, a.status_note


def test_waiting_is_shown_without_hooks(tmp_path):
    status, note = derive(make_store(tmp_path), agent(live="waiting", pending=1))
    assert status == Status.WAITING and note == "waiting for your answer"


def test_waiting_takes_the_note_from_a_hook_when_there_is_one(tmp_path):
    store = make_store(tmp_path)
    store.events.latest["s1"] = HookState(NOW, "PermissionRequest", "Bash", None, None, None)
    status, note = derive(store, agent(live="waiting", pending=1))
    assert status == Status.WAITING and note == "permission: Bash"


def test_waiting_is_not_hidden_after_many_hours(tmp_path):
    """A session that really waits for you must not turn idle only because it is old."""
    status, _ = derive(make_store(tmp_path), agent(age=9 * 3600, live="waiting", pending=1))
    assert status == Status.WAITING


def test_busy_with_a_pending_tool_is_running_not_stalled(tmp_path):
    """Without the pid file this case (tool pending for 120 s) is guessed as stalled."""
    store = make_store(tmp_path)
    status, note = derive(store, agent(age=120, live="busy", pending=1, last_kind="assistant", stop="tool_use"))
    assert (status, note) == (Status.RUNNING, "")
    guess, _ = derive(store, agent(age=120, live=None, pending=1, last_kind="assistant", stop="tool_use"))
    assert guess == Status.STALLED


def test_busy_after_a_prompt_is_thinking(tmp_path):
    status, _ = derive(make_store(tmp_path), agent(live="busy", last_kind="user", stop=None))
    assert status == Status.THINKING


def test_busy_for_a_very_long_time_is_stalled(tmp_path):
    status, note = derive(make_store(tmp_path), agent(age=700, live="busy", pending=1))
    assert status == Status.STALLED and "no new output for 11 min" in note


def test_idle_is_done_then_idle_when_old(tmp_path):
    store = make_store(tmp_path)
    assert derive(store, agent(age=60, live="idle"))[0] == Status.DONE
    assert derive(store, agent(age=3 * 3600, live="idle"))[0] == Status.IDLE


def test_failed_turn_stays_visible_when_the_process_is_idle(tmp_path):
    a = agent(live="idle", last_kind="error", stop=None)
    a.error_note = "API Error: 529"
    status, note = derive(make_store(tmp_path), a)
    assert status == Status.ERROR and note == "API Error: 529"


def test_pid_file_wins_over_a_stale_hook(tmp_path):
    store = make_store(tmp_path)
    store.events.latest["s1"] = HookState(NOW, "Notification", None, "needs permission", "permission_prompt", None)
    status, _ = derive(store, agent(live="busy", last_kind="assistant", stop="tool_use", pending=1))
    assert status == Status.RUNNING


@pytest.mark.parametrize("state", ["blocked", "crashed", "starting", "", "whatever"])
def test_unknown_states_fall_back_to_the_transcript(tmp_path, state):
    a = agent(age=5, live=state or None, pending=1, stop="tool_use")
    a.live_status = state
    assert derive(make_store(tmp_path), a)[0] == Status.RUNNING     # the guess from the transcript


def test_without_a_pid_file_nothing_changes(tmp_path):
    store = make_store(tmp_path)
    assert derive(store, agent(age=5, pid=None, pending=1))[0] == Status.RUNNING
    status, note = derive(store, agent(age=200, pid=None, pending=1))
    assert status == Status.STALLED and "maybe waiting for permission" in note


# ------------------------------------------------------------- with real files

def _session(tmp_path, pid_status):
    projects, sessions = tmp_path / "projects", tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    folder = projects / "-tmp-proj"
    folder.mkdir(parents=True, exist_ok=True)
    sid = "cccccccc-0000-0000-0000-000000000001"
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    lines = [
        {"type": "user", "timestamp": ts, "cwd": "/tmp/proj", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "timestamp": ts, "message": {"id": "m1", "model": "claude-opus-5-5", "stop_reason": "end_turn",
                                                          "usage": {"input_tokens": 1, "output_tokens": 1},
                                                          "content": [{"type": "text", "text": "done"}]}},
    ]
    (folder / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    write(sessions, MY_PID, sessionId=sid, status=pid_status)
    return Store(root=str(projects), since_hours=24, sessions_dir=str(sessions))


@needs_ps
def test_end_to_end_waiting_overrides_a_finished_looking_transcript(tmp_path):
    """The transcript says 'done', but the process says 'waiting': we believe the process."""
    snap = _session(tmp_path, "waiting").refresh()
    assert snap.agents[0].status == Status.WAITING and snap.live_status
    assert "live ✓" in top_bar(snap, 1, 0).plain


@needs_ps
def test_end_to_end_idle_and_busy(tmp_path):
    assert _session(tmp_path, "idle").refresh().agents[0].status == Status.DONE
    assert _session(tmp_path, "busy").refresh().agents[0].status == Status.RUNNING


def test_top_bar_names_the_source_of_the_status():
    def bar(live, hooks, source="claude-code"):
        return top_bar(Snapshot(agents=[], limits=[], updated=NOW, hooks_active=hooks, live_status=live, source=source), 0, 0).plain
    assert "live ✓ hooks ✓" in bar(True, True)
    assert "live ✓" in bar(True, False) and "hooks" not in bar(True, False)
    assert "hooks ✓" in bar(False, True) and "live" not in bar(False, True)
    assert "approximated" in bar(False, False)
    assert "DEMO" in bar(False, False, source="demo")


# ------------------------------------------------- a session whose process is gone

def gone(age, **kw):
    a = agent(age=age, live=None, pid=None, **kw)
    a.live = False                          # the registry works, and there is no process for this session
    return a


def test_a_session_with_no_process_is_ended_not_stalled(tmp_path):
    """The transcript ends with a prompt that never got an answer (interrupted): that is not 'stalled'."""
    store = make_store(tmp_path)
    status, note = derive(store, gone(age=3600, last_kind="user", stop=None))
    assert status == Status.IDLE and "ended" in note
    assert derive(store, gone(age=3600, pending=1, stop="tool_use"))[0] == Status.IDLE      # a tool that never finished
    hooked = make_store(tmp_path)
    hooked.events.latest["s1"] = HookState(NOW, "PermissionRequest", "Bash", None, None, None)
    assert derive(hooked, gone(age=3600, pending=1, stop="tool_use"))[0] == Status.IDLE     # even a stale 'waiting' hook


def test_a_recent_session_without_a_pid_file_keeps_the_guess(tmp_path):
    """It may be running without a pid file (an older Claude Code): only a quiet transcript means 'ended'."""
    assert derive(make_store(tmp_path), gone(age=5, last_kind="user", stop=None))[0] == Status.THINKING


def test_ended_does_not_hide_errors_or_finished_work_and_unknown_stays_unknown(tmp_path):
    store = make_store(tmp_path)
    err = gone(age=3600, last_kind="error", stop=None)
    err.error_note = "API Error: 529"
    assert derive(store, err)[0] == Status.ERROR
    assert derive(store, gone(age=300))[0] == Status.DONE                                    # a finished answer
    unknown = agent(age=3600, live=None, pid=None, pending=1, stop="tool_use")               # live is None: no registry
    assert derive(store, unknown)[0] == Status.STALLED
