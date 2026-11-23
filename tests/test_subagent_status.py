"""Subagents that have ended must not look as if they still think or are stalled."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from agents_farm.model import Status
from agents_farm.store import Store
from test_registry import MY_PID, needs_ps, write

PARENT = "11111111-1111-1111-1111-111111111111"


def at(age):
    return (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat().replace("+00:00", "Z")


def use(age, name="SubagentHandback", tid="t1"):
    return {"type": "assistant", "timestamp": at(age), "message": {
        "id": f"m-{tid}", "model": "claude-opus", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]}}


def result(age, tid="t1", **extra):
    return {"type": "user", "timestamp": at(age), "message": {
        "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok", **extra}]}}


def prompt(age):
    return {"type": "user", "timestamp": at(age), "message": {"content": "continue, please"}}


def snapshot(tmp_path, lines, subagent=True, sessions=None):
    project = tmp_path / "projects" / "-Users-you-app"
    path = project / PARENT / "subagents" / "agent-a1.jsonl" if subagent else project / f"{PARENT}.jsonl"
    os.makedirs(path.parent, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    store = Store(root=str(tmp_path / "projects"), since_hours=24, sessions_dir=sessions)
    return store, path


def status(store):
    return next(a for a in store.refresh().agents if a.transcript)


@pytest.mark.parametrize("age", [5, 120, 400])
def test_a_handback_is_done(tmp_path, age):
    store, _ = snapshot(tmp_path, [use(age + 1), result(age)])
    a = status(store)
    assert (a.status, a.status_note) == (Status.DONE, "")


def test_a_failed_handback_is_not_done(tmp_path):
    store, _ = snapshot(tmp_path, [use(6), result(5, is_error=True)])
    assert status(store).status == Status.THINKING


def test_a_handback_next_to_a_pending_tool_is_not_done(tmp_path):
    store, _ = snapshot(tmp_path, [use(7, "Bash", "t0"), use(6), result(5)])
    assert status(store).status == Status.RUNNING


def test_other_tools_and_top_level_sessions_are_not_changed(tmp_path):
    store, _ = snapshot(tmp_path / "a", [use(6, "Bash"), result(5)])
    assert status(store).status == Status.THINKING
    store, _ = snapshot(tmp_path / "b", [use(6), result(5)], subagent=False)
    assert status(store).status == Status.THINKING


def test_a_subagent_that_continues_after_a_handback_works_again(tmp_path):
    store, path = snapshot(tmp_path, [use(20), result(19)])
    assert status(store).status == Status.DONE
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(prompt(3)) + "\n")
    assert status(store).status == Status.THINKING


@pytest.mark.parametrize("lines", [[prompt(400)], [use(400, "Bash")]])
def test_a_subagent_of_a_session_with_no_process_has_ended(tmp_path, lines):
    os.makedirs(tmp_path / "sessions")
    store, _ = snapshot(tmp_path, lines, sessions=str(tmp_path / "sessions"))
    a = status(store)
    assert a.status == Status.IDLE and "ended" in a.status_note
    assert a.live is None                        # a subagent still has no process of its own


def test_a_recent_subagent_keeps_the_guess_and_so_does_one_without_a_registry(tmp_path):
    os.makedirs(tmp_path / "sessions")
    store, _ = snapshot(tmp_path / "a", [prompt(5)], sessions=str(tmp_path / "sessions"))
    assert status(store).status == Status.THINKING
    store, _ = snapshot(tmp_path / "b", [prompt(400)])
    assert status(store).status == Status.STALLED


@needs_ps
def test_a_quiet_subagent_of_a_running_session_keeps_the_guess(tmp_path):
    os.makedirs(tmp_path / "sessions")
    write(tmp_path / "sessions", pid=MY_PID, sessionId=PARENT)
    store, _ = snapshot(tmp_path, [prompt(400)], sessions=str(tmp_path / "sessions"))
    assert PARENT in store.registry.scan()       # the parent really counts as running in this test
    assert status(store).status == Status.STALLED
