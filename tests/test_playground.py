"""The playground (scripts/playground.py) and its fake claude: made-up sessions in every state, nothing real touched."""

import os
import subprocess
import sys

import pytest

from agents_farm import playground, runner
from test_registry import needs_ps

pytestmark = needs_ps


@pytest.fixture
def pg(tmp_path):
    base = str(tmp_path / "pg")
    playground.up(base)
    yield base
    playground.down(base)


def test_every_state_is_there(pg):
    rows = {r[3].strip(): r for r in playground.summary(pg)}
    status = {name: row[0] for name, row in rows.items()}
    assert status["docs-writer"] == "waiting"
    assert status["api-refactor"] == "running"
    assert status["test-fixer"] == "thinking"
    assert status["perf-audit"] == "stalled"
    assert status["lint-pass"] == "done"
    assert status["deploy-check"] == "error"
    assert status["old-spike"] == "idle"                                         # an ended session
    assert status["failing-ci"] == "idle"                                        # interrupted, the process is gone: ended, not stalled
    assert status["migrations"] == "running" and rows["migrations"][2] == "bg"
    assert rows["new background session"][2] == "bg"                              # no transcript yet, listed from its pid file
    assert rows["release-notes"][2] == "claude-desktop" and rows["review-pr"][2] == "cli"


def test_down_stops_the_fake_processes_and_removes_the_folder(tmp_path):
    base = str(tmp_path / "pg")
    playground.up(base)
    pids = [int(n[:-5]) for n in os.listdir(os.path.join(base, "home", ".claude", "sessions"))]
    assert pids and playground.down(base) >= len(pids)
    assert not os.path.exists(base)


def run_fake(base, *args, cwd=None):
    env = dict(os.environ, **playground.env_for(base))
    return subprocess.run([os.path.join(base, "claude")] + list(args), capture_output=True, text=True, env=env, cwd=cwd or base, timeout=30)


def test_the_fake_claude_starts_resumes_forks_and_stops_background_sessions(pg):
    work = os.path.join(pg, "home", "projects", "lint-pass")
    started = runner.start_background(work, ["first prompt"], os.path.join(pg, "claude"), dict(os.environ, **playground.env_for(pg)))
    assert len(started) == 8
    out = run_fake(pg, "stop", started)
    assert out.returncode == 0 and "stopped" in out.stdout
    assert run_fake(pg, "stop", started).returncode != 0                           # it is gone


def test_the_fake_claude_refuses_an_untrusted_folder_and_a_missing_bg_like_the_real_one(pg, monkeypatch):
    env = dict(os.environ, **playground.env_for(pg))
    untrusted = os.path.join(pg, "home", "projects", "untrusted-app")
    with pytest.raises(runner.BackgroundRefused, match="not trusted"):
        runner.start_background(untrusted, [], os.path.join(pg, "claude"), env)
    with pytest.raises(runner.BackgroundRefused, match="unknown option"):
        runner.start_background(os.path.join(pg, "home", "projects", "lint-pass"), [], os.path.join(pg, "claude"), dict(env, FAKE_CLAUDE_NO_BG="1"))


def test_the_fake_claude_never_runs_without_the_playground_folders(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    out = subprocess.run([sys.executable, "-m", "agents_farm.fake_claude", "stop", "x"], capture_output=True, text=True, env=env,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.returncode != 0 and "refusing to run" in out.stderr


def test_the_demo_command_runs_on_the_playground_and_cleans_up(tmp_path):
    """`agents-farm status --demo` builds the playground, reads it, and removes it and its processes."""
    before = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout.count("claude-fake")
    out = subprocess.run([sys.executable, "-m", "agents_farm", "status", "--demo"], capture_output=True, text=True, timeout=60,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.returncode == 0 and "?1" in out.stdout and "●" in out.stdout, out.stderr
    after = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout.count("claude-fake")
    assert after <= before                                                         # no fake process is left behind
