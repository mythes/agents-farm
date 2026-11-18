"""Live process registry (~/.claude/sessions): validation and PID reuse guard."""

import json
import os
import subprocess
import sys
import time

import pytest

from agents_farm.registry import Registry, load_session_file, process_start_times
from agents_farm.store import Store

MY_PID = os.getpid()
_START = process_start_times([MY_PID])
needs_ps = pytest.mark.skipif(not _START or MY_PID not in _START, reason="ps is not available")


def lstart(epoch):
    """The format used in procStart: 'Tue Nov 17 15:24:40 2026' in UTC."""
    return time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(epoch))


def write(folder, pid, **over):
    data = {
        "pid": pid, "sessionId": "11111111-2222-3333-4444-555555555555", "cwd": "/tmp/proj",
        "name": "my session", "status": "busy", "entrypoint": "cli", "kind": "interactive",
        "version": "2.1.325", "startedAt": int(time.time() * 1000),
    }
    if pid in (_START or {}):
        data["procStart"] = lstart(_START[pid])
    data.update(over)
    data = {k: v for k, v in data.items() if v is not None}
    path = folder / f"{pid}.json"
    path.write_text(json.dumps(data))
    return path


@needs_ps
def test_running_session_is_found_and_verified(tmp_path):
    write(tmp_path, MY_PID)
    found = Registry(str(tmp_path)).scan()
    session = found["11111111-2222-3333-4444-555555555555"]
    assert session.pid == MY_PID and session.verified
    assert (session.entrypoint, session.entry_label, session.status, session.version) == ("cli", "CLI", "busy", "2.1.325")
    assert session.started_at is not None


@needs_ps
def test_reused_pid_is_rejected(tmp_path):
    """A live process with this pid exists, but it started at another time than the file says."""
    write(tmp_path, MY_PID, procStart=lstart(_START[MY_PID] - 3600))
    assert Registry(str(tmp_path)).scan() == {}


@needs_ps
def test_file_without_proc_start_is_running_but_not_verified(tmp_path):
    write(tmp_path, MY_PID, procStart=None)
    session = next(iter(Registry(str(tmp_path)).scan().values()))
    assert session.pid == MY_PID and not session.verified


def test_dead_process_is_ignored(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    write(tmp_path, child.pid, procStart=lstart(time.time() - 60))
    assert Registry(str(tmp_path)).scan() == {}


def test_missing_folder_and_disabled_registry(tmp_path):
    assert Registry(None).scan() == {} and not Registry(None).available
    gone = Registry(str(tmp_path / "nope"))
    assert gone.scan() == {} and not gone.available
    assert Registry(str(tmp_path)).available


@pytest.mark.parametrize("content", [
    "not json", "[1, 2]", "null", '{"pid": true, "sessionId": "x"}', '{"pid": "5", "sessionId": "x"}',
    '{"pid": 1, "sessionId": "x"}', '{"pid": 5}', '{"pid": 5, "sessionId": "../../etc/passwd"}',
    '{"pid": 5, "sessionId": "a b"}', '{"pid": 5, "sessionId": ""}',
])
def test_bad_files_are_skipped(tmp_path, content):
    path = tmp_path / "5.json"
    path.write_text(content)
    assert load_session_file(str(path)) is None


def test_file_name_must_match_the_pid_inside(tmp_path):
    path = tmp_path / "999.json"
    path.write_text(json.dumps({"pid": 5, "sessionId": "abc"}))
    assert load_session_file(str(path)) is None


def test_oversized_file_is_skipped(tmp_path):
    path = tmp_path / "5.json"
    path.write_text(json.dumps({"pid": 5, "sessionId": "abc", "name": "x" * 100_000}))
    assert load_session_file(str(path)) is None


def test_text_fields_are_cleaned_and_limited(tmp_path):
    path = write(tmp_path, 5, name="evil\x1b]52;c;x\x07" + "n" * 1000, cwd="/tmp" + chr(0x202E) + "/x", status="busy\x1b[2J")
    session = load_session_file(str(path))
    assert "\x1b" not in session.name and len(session.name) <= 200
    assert chr(0x202E) not in session.cwd and "\x1b" not in session.status


def test_key_files_and_other_files_are_ignored(tmp_path):
    (tmp_path / "5.abcdef.key").write_text("secret")
    (tmp_path / "notes.txt").write_text("hi")
    assert Registry(str(tmp_path)).scan() == {}


# ------------------------------------------------------------ store integration

def _transcript(projects, session_id):
    folder = projects / "-tmp-proj"
    folder.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    lines = [{"type": "user", "timestamp": ts, "cwd": "/tmp/proj", "message": {"role": "user", "content": "hello"}}]
    (folder / f"{session_id}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


@needs_ps
def test_store_attaches_pid_and_marks_dead_sessions(tmp_path):
    projects, sessions = tmp_path / "projects", tmp_path / "sessions"
    sessions.mkdir()
    _transcript(projects, "aaaaaaaa-0000-0000-0000-000000000001")
    write(sessions, MY_PID, sessionId="aaaaaaaa-0000-0000-0000-000000000001")
    snap = Store(root=str(projects), since_hours=24, sessions_dir=str(sessions)).refresh()
    agent = snap.agents[0]
    assert (agent.pid, agent.entrypoint, agent.live, agent.pid_verified) == (MY_PID, "cli", True, True)

    # Same transcript, but no process for it: known to be not running.
    for f in sessions.iterdir():
        f.unlink()
    snap = Store(root=str(projects), since_hours=24, sessions_dir=str(sessions)).refresh()
    assert (snap.agents[0].pid, snap.agents[0].live) == (None, False)


def test_store_with_custom_projects_folder_does_not_read_real_sessions(tmp_path):
    _transcript(tmp_path / "projects", "aaaaaaaa-0000-0000-0000-000000000002")
    store = Store(root=str(tmp_path / "projects"), since_hours=24)
    assert not store.registry.available
    agent = store.refresh().agents[0]
    assert agent.live is None and agent.pid is None


@needs_ps
def test_a_zombie_is_not_a_running_process():
    """A finished process whose parent has not cleaned up yet (<defunct>) must not count as running."""
    import subprocess
    child = subprocess.Popen(["true"])
    time.sleep(0.5)                                                   # it has ended, and we did not wait() for it: a zombie
    try:
        assert child.pid not in process_start_times([child.pid])
        assert MY_PID in process_start_times([MY_PID])                # a live process is still listed
    finally:
        child.wait()
