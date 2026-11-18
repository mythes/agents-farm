"""T3: starting claude. No test starts a real claude: a small fake script stands in for it."""

import os
import signal
import stat
import sys

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
