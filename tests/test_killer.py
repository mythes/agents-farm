"""T2: stopping a process. Every safety rule has a test, and they all use a harmless fake process."""

import json
import os
import signal
import stat
import subprocess
import sys
import time

import pytest

from agents_farm import killer
from agents_farm.killer import KillError, Target
from agents_farm.registry import process_start_times

SID = "dddddddd-0000-0000-0000-000000000001"
needs_ps = pytest.mark.skipif(not process_start_times([os.getpid()]), reason="ps is not available")
pytestmark = needs_ps

SLEEP = "import time; time.sleep(60)"
IGNORE_TERM = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


@pytest.fixture
def procs():
    """Start fake processes. 'claude' is in their command line, so they look like the real thing."""
    started = []

    def start(code=SLEEP, marker="claude"):
        p = subprocess.Popen([sys.executable, "-c", code, marker])
        started.append(p)
        time.sleep(0.3)               # let it start, so `ps` can see it
        return p

    yield start
    for p in started:
        if p.poll() is None:
            p.kill()
        p.wait()


def lstart(epoch):
    return time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(epoch))


def pidfile(folder, pid, sid=SID, shift=0, with_start=True):
    data = {"pid": pid, "sessionId": sid, "name": "fake", "status": "idle", "entrypoint": "cli", "version": "2.1.325"}
    if with_start:
        data["procStart"] = lstart(process_start_times([pid])[pid] + shift)
    (folder / f"{pid}.json").write_text(json.dumps(data))


def target(p, sid=SID, status="idle"):
    return Target(pid=p.pid, session_id=sid, name="fake agent", entrypoint="cli", status=status)


def log_lines(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


# ------------------------------------------------------------------ the happy path

def test_sigterm_stops_a_verified_process_and_logs_it(tmp_path, procs):
    p = procs()
    pidfile(tmp_path, p.pid)
    log = str(tmp_path / "logs" / "actions.log")
    assert killer.kill(target(p), signal.SIGTERM, str(tmp_path), wait_s=5, log_path=log) is True
    assert p.wait(timeout=5) == -signal.SIGTERM
    entry = log_lines(log)[-1]
    assert (entry["signal"], entry["pid"], entry["session"], entry["name"]) == ("SIGTERM", p.pid, SID, "fake agent")
    assert entry["result"] == "sent, the process ended"
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(log)).st_mode) == 0o700


def test_sigkill_is_the_follow_up_for_a_process_that_ignores_sigterm(tmp_path, procs):
    p = procs(IGNORE_TERM)
    pidfile(tmp_path, p.pid)
    log = str(tmp_path / "actions.log")
    assert killer.kill(target(p), signal.SIGTERM, str(tmp_path), wait_s=1, log_path=log) is False
    assert p.poll() is None                                   # still running: we must offer SIGKILL
    assert killer.kill(target(p), signal.SIGKILL, str(tmp_path), wait_s=5, log_path=log) is True
    assert p.wait(timeout=5) == -signal.SIGKILL
    assert [e["signal"] for e in log_lines(log)] == ["SIGTERM", "SIGKILL"]


# ------------------------------------------------------- refusals: the process lives on

def refused(tmp_path, p, tgt, reason, sessions=None):
    log = str(tmp_path / "actions.log")
    with pytest.raises(KillError, match=reason):
        killer.kill(tgt, signal.SIGTERM, str(sessions or tmp_path), log_path=log)
    time.sleep(0.2)
    assert p.poll() is None, "the process must not receive any signal"
    assert log_lines(log)[-1]["result"].startswith("refused: ")


def test_refuses_when_the_pid_file_is_gone(tmp_path, procs):
    p = procs()
    refused(tmp_path, p, target(p), "session has ended")


def test_refuses_a_pid_file_of_another_session(tmp_path, procs):
    p = procs()
    pidfile(tmp_path, p.pid, sid="eeeeeeee-0000-0000-0000-000000000009")
    refused(tmp_path, p, target(p), "another session")


def test_refuses_a_reused_pid(tmp_path, procs):
    """The file says the process started an hour ago, but this pid belongs to a younger process."""
    p = procs()
    pidfile(tmp_path, p.pid, shift=-3600)
    refused(tmp_path, p, target(p), "reused by another program")


def test_refuses_a_file_without_a_start_time(tmp_path, procs):
    p = procs()
    pidfile(tmp_path, p.pid, with_start=False)
    refused(tmp_path, p, target(p), "no start time")


def test_refuses_when_there_is_no_folder_for_process_files(tmp_path, procs):
    p = procs()
    with pytest.raises(KillError, match="not available"):
        killer.kill(target(p), signal.SIGTERM, None, log_path=str(tmp_path / "a.log"))
    assert p.poll() is None


def test_refuses_a_process_that_does_not_look_like_claude(tmp_path, procs):
    p = procs(marker="something-else")
    pidfile(tmp_path, p.pid)
    refused(tmp_path, p, target(p), "does not look like claude")


def test_refuses_another_users_process(tmp_path, procs, monkeypatch):
    p = procs()
    pidfile(tmp_path, p.pid)
    monkeypatch.setattr(killer, "process_uid", lambda pid: os.getuid() + 1)
    refused(tmp_path, p, target(p), "another user")


def test_refuses_the_desktop_wrapper(tmp_path, procs, monkeypatch):
    p = procs()
    pidfile(tmp_path, p.pid)
    monkeypatch.setattr(killer, "process_comm", lambda pid: "/Applications/Claude.app/Contents/Helpers/disclaimer")
    refused(tmp_path, p, target(p), "wrapper")


@pytest.mark.parametrize("pid", [1, 0, -5])
def test_refuses_pid_1_and_invalid_pids(tmp_path, pid):
    with pytest.raises(KillError, match="invalid process id"):
        killer.kill(Target(pid=pid, session_id=SID), signal.SIGTERM, str(tmp_path), log_path=str(tmp_path / "a.log"))


def test_refuses_our_own_process_and_its_parents(tmp_path):
    for pid in (os.getpid(), os.getppid()):
        with pytest.raises(KillError, match="runs agents-farm"):
            killer.kill(Target(pid=pid, session_id=SID), signal.SIGTERM, str(tmp_path), log_path=str(tmp_path / "a.log"))


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGHUP, signal.SIGUSR1])
def test_only_sigterm_and_sigkill_are_allowed(tmp_path, procs, sig):
    p = procs()
    pidfile(tmp_path, p.pid)
    with pytest.raises(KillError, match="only SIGTERM and SIGKILL"):
        killer.kill(target(p), sig, str(tmp_path), log_path=str(tmp_path / "a.log"))
    assert p.poll() is None


# ------------------------------------------------------------------------- small parts

def test_a_process_that_already_ended_is_not_an_error(tmp_path, procs):
    p = procs()
    pidfile(tmp_path, p.pid)
    session = killer.check(target(p), str(tmp_path))
    p.kill()
    p.wait()
    assert killer.wait_until_gone(session, 1) is True


def test_log_problems_never_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    killer.log_action(Target(pid=5, session_id=SID), signal.SIGTERM, "x", str(blocker / "sub" / "a.log"))


def test_warnings_follow_what_spike_s4_found():
    desktop_idle = [t for _, t in killer.warnings("claude-desktop", "idle", SID)]
    assert len(desktop_idle) == 1 and "next message" in desktop_idle[0] and "history is kept" in desktop_idle[0]
    busy = killer.warnings("claude-desktop", "busy", SID)
    assert any("current turn will be lost" in t for _, t in busy) and any(s == "bold red" for s, _ in busy)
    waiting = killer.warnings("claude-desktop", "waiting", SID)
    assert any("question will be lost" in t for _, t in waiting)
    cli = " ".join(t for _, t in killer.warnings("cli", "idle", SID))
    assert f"claude --resume {SID}" in cli
