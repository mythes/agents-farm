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


def build_args(model: str = "", permission_mode: str = "default", worktree: bool = False,
               extra: Optional[List[str]] = None) -> List[str]:
    """The argument list for `claude`. Order: our flags, then config flags, then -w."""
    args: List[str] = []
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
