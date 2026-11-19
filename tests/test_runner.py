"""T3: starting claude. No test starts a real claude: a small fake script stands in for it."""

import os
import signal
import stat
import sys
import time

import pytest

from agents_farm import runner
from agents_farm.runner import RunError


def fake_claude(folder, body="pass"):
    path = folder / "claude"
    path.write_text(f"#!{sys.executable}\nimport os, sys, json\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_build_args_is_a_list_in_a_fixed_order():
    assert runner.build_args() == []
    assert runner.build_args("opus", "plan", True, ["--verbose"]) == ["--model", "opus", "--permission-mode", "plan", "--verbose", "-w"]


def test_the_first_prompt_goes_first_and_never_looks_like_an_option():
    assert runner.build_args("opus", "plan", True, ["--verbose"], prompt="fix the tests") == \
        ["fix the tests", "--model", "opus", "--permission-mode", "plan", "--verbose", "-w"]
    assert runner.build_args(prompt="--dangerously-skip-permissions") == [" --dangerously-skip-permissions"]   # a space hides the dash
    assert runner.build_args(prompt="   ") == []
    for bad in ("x" * 4001, "a\0b"):
        with pytest.raises(RunError, match="first prompt"):
            runner.build_args(prompt=bad)


@pytest.mark.parametrize("model", ["--dangerously-skip-permissions", "-x", "a b", "a;b", "$(id)", "x" * 80])
def test_a_model_name_cannot_inject_flags_or_shell(model):
    with pytest.raises(RunError, match="model name"):
        runner.build_args(model)


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "x", ""])
def test_unsafe_permission_modes_are_not_offered(mode):
    with pytest.raises(RunError, match="permission mode"):
        runner.build_args("", mode)


def test_claude_args_must_be_strings():
    with pytest.raises(RunError, match="list of strings"):
        runner.build_args(extra=["ok", 5])


def test_check_dir(tmp_path):
    assert runner.check_dir(str(tmp_path)) == str(tmp_path)
    with pytest.raises(RunError, match="does not exist"):
        runner.check_dir(str(tmp_path / "nope"))
    with pytest.raises(RunError, match="choose a folder"):
        runner.check_dir("  ")


def test_find_claude(tmp_path, monkeypatch):
    path = fake_claude(tmp_path)
    assert runner.find_claude({"claude_bin": path}) == path
    with pytest.raises(RunError, match="claude_bin"):
        runner.find_claude({"claude_bin": str(tmp_path / "missing")})
    monkeypatch.setenv("PATH", str(tmp_path))
    assert runner.find_claude({}) == path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with pytest.raises(RunError, match="was not found"):
        runner.find_claude({})


def test_env_is_validated():
    assert runner.build_env({"MY_VAR": "1"})["MY_VAR"] == "1"
    for bad in ({"A B": "1"}, {"A": 1}, {"A": "x\0y"}):
        with pytest.raises(RunError, match="claude_env"):
            runner.build_env(bad)


def test_run_interactive_uses_the_folder_the_arguments_and_the_exit_code(tmp_path):
    out = tmp_path / "out.json"
    claude = fake_claude(tmp_path, f"open({str(out)!r}, 'w').write(json.dumps([os.getcwd(), sys.argv[1:], os.environ.get('MY_VAR')]))\nsys.exit(3)")
    work = tmp_path / "work"
    work.mkdir()
    code = runner.run_interactive(str(work), ["--model", "opus"], claude, runner.build_env({"MY_VAR": "v"}))
    assert code == 3
    import json
    assert json.loads(out.read_text()) == [os.path.realpath(work), ["--model", "opus"], "v"]


def test_claude_keeps_the_default_sigint_and_we_survive_it(tmp_path):
    before = signal.getsignal(signal.SIGINT)
    seen = tmp_path / "seen"
    claude = fake_claude(tmp_path, f"import signal\nopen({str(seen)!r}, 'w').write(str(signal.getsignal(signal.SIGINT) is not signal.SIG_IGN))")
    runner.run_interactive(str(tmp_path), [], claude)
    assert signal.getsignal(signal.SIGINT) == before
    assert seen.read_text() == "True"     # not "ignore": the child must still be stoppable with Ctrl-C


def test_ctrl_c_during_the_run_does_not_stop_us(tmp_path):
    claude = fake_claude(tmp_path, "import time\ntime.sleep(0.6)")
    import threading
    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    assert runner.run_interactive(str(tmp_path), [], claude) == 0


def test_a_program_that_cannot_start_is_an_error_not_a_crash(tmp_path):
    bad = tmp_path / "claude"
    bad.write_text("not a program")
    bad.chmod(0o755)
    with pytest.raises(RunError, match="cannot start"):
        runner.run_interactive(str(tmp_path), [], str(bad))


def _in_subprocess(code: str, timeout=30):
    """Run a snippet in its own process: a stopped or killed test process must never be pytest itself."""
    import subprocess
    return subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r)\n" % os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + code],
                          capture_output=True, text=True, timeout=timeout)


def test_ctrl_z_during_the_run_does_not_stop_us(tmp_path):
    """The terminal sends Ctrl-Z to the whole foreground group, so also to us. We must go on."""
    claude = fake_claude(tmp_path, "import time\ntime.sleep(0.8)")
    done = _in_subprocess(f"""
import os, signal, threading
from agents_farm import runner
threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTSTP)).start()
print("code", runner.run_interactive({str(tmp_path)!r}, [], {claude!r}))
""")
    assert done.returncode == 0 and "code 0" in done.stdout, done.stderr             # a stopped process would hit the timeout instead


def test_a_second_ctrl_z_after_the_child_has_gone_is_still_shielded(tmp_path):
    """While the dashboard takes the terminal back, a queued Ctrl-Z must not stop agents-farm either."""
    claude = fake_claude(tmp_path, "pass")
    done = _in_subprocess(f"""
import os, signal
from agents_farm import runner
with runner.shielded_signals():
    runner.run_interactive({str(tmp_path)!r}, [], {claude!r})
    os.kill(os.getpid(), signal.SIGTSTP)                    # the child is gone, the dashboard is not back yet
    print("alive")
print("restored", signal.getsignal(signal.SIGTSTP) == signal.SIG_DFL)
""")
    assert done.returncode == 0 and "alive" in done.stdout and "restored True" in done.stdout, done.stderr


def test_a_child_that_stops_is_resumed_so_ctrl_z_does_nothing_in_a_normal_session(tmp_path):
    claude = fake_claude(tmp_path, "import signal\nos.kill(os.getpid(), signal.SIGSTOP)\nsys.exit(7)")  # stops itself, exits 7 once resumed
    assert runner.run_interactive(str(tmp_path), [], claude) == 7


def test_leave_on_stop_ends_the_viewer_and_returns_zero(tmp_path):
    pidfile = tmp_path / "pid"
    claude = fake_claude(tmp_path, f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\nimport signal, time\nos.kill(os.getpid(), signal.SIGSTOP)\ntime.sleep(60)")
    started = time.monotonic()
    assert runner.run_interactive(str(tmp_path), ["attach", "x"], claude, leave_on_stop=True) == 0
    assert time.monotonic() - started < 8
    pid = int(pidfile.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)                                                         # the stopped viewer is gone, not left behind


def test_exit_codes_and_signals_are_reported(tmp_path):
    assert runner.run_interactive(str(tmp_path), [], fake_claude(tmp_path, "sys.exit(3)")) == 3
    assert runner.run_interactive(str(tmp_path), [], fake_claude(tmp_path, "os.kill(os.getpid(), 15)")) == 128 + 15


def test_a_trust_refusal_is_recognised():
    assert runner.is_trust_error("Workspace not trusted. Run `claude` in /x once and accept the trust prompt, then retry.")
    assert not runner.is_trust_error("cannot start claude: boom") and not runner.is_trust_error("")


# ------------------------------------------------------- run_job: Ctrl-Z in a normal session ("end")

STOP_THEN_SLEEP = "import signal, time\nos.kill(os.getpid(), signal.SIGSTOP)\ntime.sleep(60)"


def test_end_on_stop_ends_an_idle_session_and_says_so(tmp_path):
    pidfile = tmp_path / "pid"
    claude = fake_claude(tmp_path, f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n" + STOP_THEN_SLEEP)
    started = time.monotonic()
    result = runner.run_job(str(tmp_path), [], claude, on_stop="end", is_busy=lambda pid: False)
    assert result.ended and result.code == 0 and time.monotonic() - started < 8
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)                                    # ended, not left stopped


@pytest.mark.parametrize("busy", [True, None, "boom"])
def test_end_on_stop_does_not_end_a_busy_or_unknown_session(tmp_path, busy):
    """Nothing is lost: a session that works, or whose state we cannot read, is simply continued."""
    claude = fake_claude(tmp_path, "import signal\nos.kill(os.getpid(), signal.SIGSTOP)\nsys.exit(7)")

    def is_busy(pid):
        if busy == "boom":
            raise OSError("cannot read the pid file")
        return busy

    result = runner.run_job(str(tmp_path), [], claude, on_stop="end", is_busy=is_busy)
    assert result.code == 7 and not result.ended


def test_a_child_that_keeps_stopping_is_ended_with_a_clear_error(tmp_path):
    """For example agents-farm runs as a background job: claude stops again as soon as it is continued."""
    claude = fake_claude(tmp_path, "import signal\nwhile True:\n    os.kill(os.getpid(), signal.SIGSTOP)")
    started = time.monotonic()
    with pytest.raises(RunError, match="keeps stopping"):
        runner.run_job(str(tmp_path), [], claude)
    assert time.monotonic() - started < 15


def test_a_refusal_is_a_background_refusal_but_a_timeout_or_a_missing_program_is_not(tmp_path, monkeypatch):
    refuse = fake_claude(tmp_path, "sys.stderr.write('error: unknown option --bg\\n'); sys.exit(1)")
    with pytest.raises(runner.BackgroundRefused, match="unknown option"):
        runner.start_background(str(tmp_path), [], refuse)
    monkeypatch.setattr(runner, "BG_TIMEOUT_S", 0.5)
    slow = fake_claude(tmp_path, "import time\ntime.sleep(5)")
    with pytest.raises(RunError, match="did not answer") as err:
        runner.start_background(str(tmp_path), [], slow)
    assert not isinstance(err.value, runner.BackgroundRefused)
    with pytest.raises(RunError, match="cannot start") as err2:
        runner.start_background(str(tmp_path), [], str(tmp_path / "missing"))
    assert not isinstance(err2.value, runner.BackgroundRefused)
