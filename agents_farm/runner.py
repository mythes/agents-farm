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
from typing import Dict, List, Optional

from .model import sanitize

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


def run_interactive(cwd: str, args: List[str], claude: str, env: Optional[Dict[str, str]] = None) -> int:
    """Run `claude` and wait. Ctrl-C goes to `claude` too, but must not stop us.

    We use a handler that does nothing, not SIG_IGN: "ignore" is inherited by the child
    (claude would never see Ctrl-C), while a handler is reset to the default on exec.
    """
    old = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        return subprocess.call([claude] + args, cwd=cwd, env=env)  # nosec B603
    except OSError as exc:
        raise RunError(f"cannot start claude: {exc}") from exc
    finally:
        signal.signal(signal.SIGINT, old)


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
        raise RunError(_first_line(done.stderr) or _first_line(done.stdout) or f"claude --bg failed (exit {done.returncode})")
    return match.group(1)


def attach_args(session_id: str) -> List[str]:
    return ["attach", short_id(session_id)]


def stop_background(session_id: str, claude: str, env: Optional[Dict[str, str]] = None) -> str:
    """`claude stop <id>`: the official way to end a background session. Returns what claude said."""
    done = _run_claude(claude, ["stop", short_id(session_id)], None, env)
    if done.returncode != 0:
        raise RunError(_first_line(done.stderr) or _first_line(done.stdout) or f"claude stop failed (exit {done.returncode})")
    return _first_line(done.stdout) or "stopped"
