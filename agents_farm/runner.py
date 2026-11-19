"""T3: start `claude` in the same terminal. No Textual imports here.

Rules: arguments are always a list (no shell), the folder is checked first, and the
dialog can only choose safe permission modes. The app calls `run_interactive` inside
`App.suspend()`, so the terminal belongs to `claude` until it exits.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess  # nosec B404
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .model import sanitize
from .registry import SESSION_ID_RE

# The dialog offers only these. Modes that skip permission checks are not offered.
PERMISSION_MODES = ("default", "acceptEdits", "plan")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class RunError(Exception):
    """A problem the user can read and fix. Never a crash."""


def find_claude(cfg: Optional[dict] = None) -> str:
    """The `claude` program: config `claude_bin`, else PATH, else ~/.local/bin/claude."""
    wanted = str((cfg or {}).get("claude_bin") or "").strip()
    if wanted:
        found = shutil.which(os.path.expanduser(wanted))
        if not found:
            raise RunError(f"claude_bin in the config is not a program that can run: {wanted}")
        return found
    found = shutil.which("claude")
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/claude")
    if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        return fallback
    raise RunError("`claude` was not found. Install Claude Code, or set claude_bin in ~/.agents-farm/config.json")


def check_dir(path: str) -> str:
    """The folder to start in. It must exist."""
    path = (path or "").strip()
    if not path:
        raise RunError("choose a folder")
    full = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(full):
        raise RunError(f"folder does not exist: {full}")
    return full


def check_model(model: str) -> str:
    model = (model or "").strip()
    if model and not _MODEL_RE.match(model):
        raise RunError("model name: use letters, digits and . _ : - only (for example: opus, sonnet, claude-opus-5-5)")
    return model


MAX_PROMPT = 4000


def check_prompt(prompt: str) -> str:
    """The first prompt, as one argument. It goes first, so `-w` never takes it as a worktree name,
    and a leading "-" is hidden behind a space so it can never be read as an option."""
    prompt = (prompt or "").strip()
    if "\0" in prompt or len(prompt) > MAX_PROMPT:
        raise RunError(f"the first prompt must be at most {MAX_PROMPT} characters")
    return (" " + prompt) if prompt.startswith("-") else prompt


def build_args(model: str = "", permission_mode: str = "default", worktree: bool = False,
               extra: Optional[List[str]] = None, prompt: str = "") -> List[str]:
    """The argument list for `claude`. Order: the prompt, our flags, then config flags, then -w."""
    args: List[str] = []
    first = check_prompt(prompt)
    if first:
        args.append(first)
    model = check_model(model)
    if model:
        args += ["--model", model]
    if permission_mode not in PERMISSION_MODES:
        raise RunError(f"permission mode must be one of: {', '.join(PERMISSION_MODES)}")
    if permission_mode != "default":
        args += ["--permission-mode", permission_mode]
    if extra:
        if not all(isinstance(x, str) for x in extra):
            raise RunError("claude_args in the config must be a list of strings")
        args += list(extra)
    if worktree:
        args.append("-w")
    return args


def build_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ)
    for name, value in (extra or {}).items():
        if not (isinstance(name, str) and isinstance(value, str) and _ENV_NAME_RE.match(name)) or "\0" in value:
            raise RunError(f"claude_env in the config: bad entry {str(name)[:40]!r}")
        env[name] = value
    return env


class BackgroundRefused(RunError):
    """claude ran, but would not start a background session here (folder not trusted, turned off by an
    administrator, or `--bg` is not supported by this version). A plain `claude` may still work."""


@dataclass
class RunResult:
    code: int = 0
    ended: bool = False            # the session was ended on purpose because the user pressed Ctrl+Z


def _noop(*_args) -> None:
    pass


@contextmanager
def shielded_signals():
    """No-op handlers for SIGINT and SIGTSTP until the block ends (a handler, not SIG_IGN: "ignore" would
    be inherited by `claude`, which would then never see the key).

    The terminal sends Ctrl-C and Ctrl-Z to every process of the foreground group, so also to us. Wrap the whole
    hand-over to `claude`, including the moment when the dashboard takes the terminal back: a second Ctrl-Z
    pressed in that moment must not stop agents-farm either.
    """
    old = {signal.SIGINT: signal.signal(signal.SIGINT, _noop)}
    if hasattr(signal, "SIGTSTP"):
        old[signal.SIGTSTP] = signal.signal(signal.SIGTSTP, _noop)
    try:
        yield
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


def _flush_input() -> None:
    """Drop keys typed while `claude` ran, so a queued Ctrl-Z cannot hit the dashboard when it comes back."""
    try:
        import termios
        if sys.stdin.isatty():
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:  # noqa: BLE001 - never worth a crash
        return


def _leave(proc: "subprocess.Popen") -> None:
    """End a child that was stopped by Ctrl+Z: an attach client (the session it showed lives on), or a session
    that the user chose to leave. This is only ever the process we started ourselves."""
    for sig, wait in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 3.0)):
        try:
            os.kill(proc.pid, signal.SIGCONT)     # a stopped process only sees SIGTERM after it continues
            os.kill(proc.pid, sig)
        except ProcessLookupError:
            return
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                done, _ = os.waitpid(proc.pid, os.WNOHANG)
            except ChildProcessError:
                return
            if done:
                return
            time.sleep(0.05)


MAX_RESUMES = 5                 # a child that stops more often than this in one second is not a Ctrl-Z


def run_job(cwd: str, args: List[str], claude: str, env: Optional[Dict[str, str]] = None, on_stop: str = "resume",
            is_busy: Optional[Callable[[int], Optional[bool]]] = None) -> RunResult:
    """Run `claude` in this terminal and wait. `on_stop` says what Ctrl-Z (the child stops) means:

    - "resume": nothing. The child is continued, so no stopped process is left behind.
    - "leave":  an attach client. It is ended and we return, and the session it showed keeps running.
    - "end":    leave a normal (foreground) session. If `is_busy(pid)` is False (it is idle, nothing is lost),
                the session is ended and `ended` is True: its history stays, and `r` continues it later,
                from this or any other agents-farm. If it is busy or unknown, it is continued as with "resume".
    """
    with shielded_signals():
        try:
            proc = subprocess.Popen([claude] + args, cwd=cwd, env=env)  # nosec B603
        except OSError as exc:
            raise RunError(f"cannot start claude: {exc}") from exc
        resumed: List[float] = []
        try:
            while True:
                try:
                    _, status = os.waitpid(proc.pid, os.WUNTRACED)
                except ChildProcessError:
                    return RunResult(0)
                if os.WIFSTOPPED(status):
                    if on_stop == "leave":
                        _leave(proc)
                        proc.returncode = 0
                        return RunResult(0)
                    if on_stop == "end" and is_busy is not None:
                        try:
                            busy = is_busy(proc.pid)
                        except Exception:  # noqa: BLE001 - an unknown state means "do not end it"
                            busy = None
                        if busy is False:
                            _leave(proc)
                            proc.returncode = 0
                            return RunResult(0, ended=True)
                    now = time.monotonic()
                    resumed = [t for t in resumed if now - t < 1.0] + [now]
                    if len(resumed) > MAX_RESUMES:       # it stops again at once: for example agents-farm is not the foreground job
                        _leave(proc)
                        proc.returncode = 1
                        raise RunError("claude keeps stopping itself. Is agents-farm running in the background (started with &)?")
                    os.kill(proc.pid, signal.SIGCONT)
                    continue
                proc.returncode = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 128 + os.WTERMSIG(status)
                return RunResult(proc.returncode)
        finally:
            _flush_input()


def run_interactive(cwd: str, args: List[str], claude: str, env: Optional[Dict[str, str]] = None,
                    leave_on_stop: bool = False) -> int:
    """`run_job` that returns only the exit code: "leave" for an attach client, otherwise Ctrl-Z does nothing."""
    return run_job(cwd, args, claude, env, on_stop="leave" if leave_on_stop else "resume").code


# ---------------------------------------------------------------- background sessions (T9)
# Claude Code's own `claude --bg`, `attach` and `stop` (see docs/backlog.md, finding 14).
# We only run these commands. We never type into a terminal and never send a signal here.

_BG_ID_RE = re.compile(r"backgrounded\s*\S*\s*([0-9a-f]{8})\b")
SHORT_ID_RE = re.compile(r"^[0-9a-f]{8}$")
BG_TIMEOUT_S = 60


def short_id(session_id: str) -> str:
    """The id `claude attach` and `claude stop` take: the first 8 characters of the session id."""
    sid = (session_id or "")[:8].lower()
    if not SHORT_ID_RE.match(sid):
        raise RunError("this session has no id that claude can use")
    return sid


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = sanitize(line).strip()
        if line:
            return line[:300]
    return ""


def _run_claude(claude: str, args: List[str], cwd: Optional[str], env: Optional[Dict[str, str]]):
    try:
        return subprocess.run([claude] + args, cwd=cwd, env=env, capture_output=True, text=True,  # nosec B603
                              timeout=BG_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise RunError(f"claude did not answer within {BG_TIMEOUT_S} seconds") from exc
    except OSError as exc:
        raise RunError(f"cannot start claude: {exc}") from exc


def start_background(cwd: str, args: List[str], claude: str, env: Optional[Dict[str, str]] = None) -> str:
    """`claude --bg ...`: start an idle session in the background. Returns its short id."""
    done = _run_claude(claude, ["--bg"] + args, cwd, env)
    match = _BG_ID_RE.search(done.stdout or "")
    if done.returncode != 0 or not match:
        raise BackgroundRefused(_first_line(done.stderr) or _first_line(done.stdout) or f"claude --bg failed (exit {done.returncode})")
    return match.group(1)


def is_trust_error(message: str) -> bool:
    """`claude --bg` only starts in a folder you already trusted. It says so with 'Workspace not trusted'."""
    return "not trusted" in (message or "").lower()


def attach_args(session_id: str) -> List[str]:
    return ["attach", short_id(session_id)]


def stop_background(session_id: str, claude: str, env: Optional[Dict[str, str]] = None) -> str:
    """`claude stop <id>`: the official way to end a background session. Returns what claude said."""
    done = _run_claude(claude, ["stop", short_id(session_id)], None, env)
    if done.returncode != 0:
        raise RunError(_first_line(done.stderr) or _first_line(done.stdout) or f"claude stop failed (exit {done.returncode})")
    return _first_line(done.stdout) or "stopped"


# ------------------------------------------------------------------------ resume a session (T4)
# `claude --bg --resume <id>` wakes a finished session in the background under the same id (verified: it
# also restores the saved model and permission mode). If the session already runs in the background, claude
# itself starts a fork and says so. `--fork-session` always makes a fork with a new id.

def resume_args(session_id: str, fork: bool = False) -> List[str]:
    """Arguments that resume (or fork) a session. The id is checked, so it can never look like an option."""
    if not SESSION_ID_RE.match(session_id or "") or session_id.startswith("-"):
        raise RunError("this session has no id that claude can resume")
    return ["--resume", session_id] + (["--fork-session"] if fork else [])


@dataclass
class ResumePlan:
    allowed: tuple                 # "resume" and/or "fork"
    primary: str                   # what Enter does
    lines: List[tuple]             # (style, text) lines for the dialog


def resume_plan(entrypoint: str) -> ResumePlan:
    """The dialog for `r` (continue a session that has ended). Whether it may be continued at all is decided by
    capabilities.unavailable(): a session that runs is never continued, so two processes never write to one history."""
    if entrypoint == "claude-desktop":
        return ResumePlan(("resume", "fork"), "fork", [
            ("", "  This chat belongs to Claude Desktop, which starts it again on your next message there."),
            ("yellow", "  Then both would write to one history, so a fork is the safer choice."),
        ])
    return ResumePlan(("resume",), "resume", [
        ("", "  The same session continues, with its history, model and mode."),
        ("", "  It opens here and runs in the background: Ctrl+Z leaves it running."),
    ])
