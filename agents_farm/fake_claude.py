#!/usr/bin/env python3
"""A fake `claude` for the demo and the playground (agents_farm/playground.py). It never touches your real Claude Code data.

It understands what agents-farm runs: `--bg` (with `--resume` and `--fork-session`), `attach <id>`, `stop <id>`,
and a plain interactive session. It keeps its sessions only in the folders named by CLAUDE_SESSIONS_DIR and
CLAUDE_PROJECTS_DIR, and refuses to run without them.

Try these on purpose:
  - a folder whose path contains "untrusted" answers "Workspace not trusted" (the fallback to a plain session)
  - FAKE_CLAUDE_NO_BG=1 answers "unknown option '--bg'" (an old Claude Code, or background sessions turned off)
  - in `attach` and in a plain session: Ctrl+Z leaves (a plain session stops itself, like the real one), /exit ends
"""

import json
import os
import signal
import subprocess  # nosec B404
import sys
import termios
import time
import tty
import uuid

# Every subprocess call in this file runs a fixed command (ps, or this Python): there is no user input in it.
SESSIONS = os.environ.get("CLAUDE_SESSIONS_DIR", "")
PROJECTS = os.environ.get("CLAUDE_PROJECTS_DIR", "")
VALUE_FLAGS = {"--model", "--permission-mode", "--resume"}


def die(message, code=1):
    sys.stderr.write(message + "\n")
    sys.exit(code)


def now_iso(offset=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + offset))


def lstart(pid):
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,  # nosec
                         env=dict(os.environ, TZ="UTC", LC_ALL="C")).stdout
    return out.strip()


def project_dir(cwd):
    return os.path.join(PROJECTS, "-" + cwd.replace("/", "-").lstrip("-"))


def transcript_path(sid, cwd):
    return os.path.join(project_dir(cwd), sid + ".jsonl")


def write_pidfile(pid, sid, cwd, name, status, kind):
    data = {"pid": pid, "sessionId": sid, "cwd": cwd, "name": name, "status": status, "entrypoint": "cli", "kind": kind,
            "version": "2.1.327", "startedAt": int(time.time() * 1000), "procStart": lstart(pid)}
    os.makedirs(SESSIONS, exist_ok=True)
    with open(os.path.join(SESSIONS, f"{pid}.json"), "w") as fh:
        json.dump(data, fh)


def set_status(pid, status):
    path = os.path.join(SESSIONS, f"{pid}.json")
    try:
        data = json.load(open(path))
        data["status"] = status
        json.dump(data, open(path, "w"))
    except (OSError, ValueError):
        pass


def append_turn(sid, cwd, prompt, reply="ok (this is the fake claude)"):
    path = transcript_path(sid, cwd)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": now_iso(), "cwd": cwd, "entrypoint": "cli",
                             "message": {"role": "user", "content": prompt}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "timestamp": now_iso(1), "message": {
            "id": uuid.uuid4().hex[:12], "model": "claude-haiku-5-5", "stop_reason": "end_turn",
            "usage": {"input_tokens": 1200, "output_tokens": 40},
            "content": [{"type": "text", "text": reply}]}}) + "\n")


def live_sessions():
    out = []
    for name in os.listdir(SESSIONS) if os.path.isdir(SESSIONS) else []:
        if name.endswith(".json"):
            try:
                out.append(json.load(open(os.path.join(SESSIONS, name))))
            except (OSError, ValueError):
                continue
    return out


def find_live(prefix):
    for s in live_sessions():
        if str(s.get("sessionId", "")).startswith(prefix):
            return s
    return None


def parse(args):
    opts, prompt, i = {}, "", 0
    while i < len(args):
        a = args[i]
        if a in VALUE_FLAGS and i + 1 < len(args):
            opts[a] = args[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            opts[a] = True
        elif not prompt:
            prompt = a.strip()
        i += 1
    return opts, prompt


# ------------------------------------------------------------------------------------------ claude --bg

def cmd_bg(args):
    if os.environ.get("FAKE_CLAUDE_NO_BG"):
        die("error: unknown option '--bg'")
    opts, prompt = parse(args)
    cwd = os.getcwd()
    if "untrusted" in cwd:
        die(f"Workspace not trusted. Run `claude` in {cwd} once and accept the trust prompt, then retry.")
    resume = opts.get("--resume") if isinstance(opts.get("--resume"), str) else None
    sid, note = str(uuid.uuid4()), ""
    if resume:
        running = find_live(resume)
        if not opts.get("--fork-session") and not running:
            sid = resume
        else:
            old = transcript_path(resume, cwd)
            if os.path.exists(old):
                os.makedirs(os.path.dirname(old), exist_ok=True)
                with open(old) as src, open(transcript_path(sid, cwd), "w") as dst:
                    dst.write(src.read())
            if running and not opts.get("--fork-session"):
                note = f"note: session {resume[:8]} is already running in the background, so this started a copy as {sid[:8]}. `claude attach {resume[:8]}` opens the original.\n"
        if sid == resume:
            note = f"note: woke session {sid[:8]} with its saved options (--permission-mode, --model).\n"
    if prompt:
        append_turn(sid, cwd, prompt)
    waiter = "import os, sys, time\nend = time.time() + 21600\nwhile time.time() < end and os.path.isdir(sys.argv[2]):\n    time.sleep(1)"
    proc = subprocess.Popen([sys.executable, "-c", waiter, f"claude-fake-bg-{sid[:8]}", SESSIONS],  # nosec
                            start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.2)                                          # let `ps` see it
    write_pidfile(proc.pid, sid, cwd, prompt[:40] or "new background session", "idle", "bg")
    sys.stdout.write(note)
    sys.stdout.write(f"Starting background service…\nbackgrounded · {sid[:8]} (idle — send a prompt to start)\n"
                     f"  claude attach {sid[:8]}    open in this terminal\n  claude stop {sid[:8]}      stop this session\n")
    return 0


def cmd_stop(args):
    s = find_live(args[0]) if args else None
    if not s:
        die(f"error: no background session {args[0] if args else ''}")
    try:
        os.kill(int(s["pid"]), signal.SIGTERM)
    except OSError:
        pass
    try:
        os.remove(os.path.join(SESSIONS, f"{s['pid']}.json"))
    except OSError:
        pass
    print(f"stopped {args[0]}")
    return 0


# ------------------------------------------------------------------------------- the terminal screens

def screen(lines):
    sys.stdout.write("\x1b[2J\x1b[H" + "\r\n".join(lines) + "\r\n")
    sys.stdout.flush()


def read_loop(title, hint, on_line, on_ctrl_z):
    """Raw keyboard loop. Ctrl+Z calls on_ctrl_z(). Enter calls on_line(text); returns True to end the loop."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = ""
    try:
        tty.setraw(fd)
        screen([f"[fake claude] {title}", hint, "", "> "])
        while True:
            ch = os.read(fd, 1)
            if not ch:
                return
            if ch == b"\x1a":
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                if on_ctrl_z():
                    return
                tty.setraw(fd)
                screen([f"[fake claude] {title}", hint, "", "> " + buf])
            elif ch in (b"\r", b"\n"):
                text, buf = buf, ""
                if on_line(text):
                    return
                sys.stdout.write("\r\n> ")
                sys.stdout.flush()
            elif ch == b"\x7f":
                buf = buf[:-1]
            elif ch >= b" ":
                buf += ch.decode("utf-8", "replace")
                sys.stdout.write(ch.decode("utf-8", "replace"))
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")


def cmd_attach(args):
    s = find_live(args[0]) if args else None
    if not s or s.get("kind") != "bg":
        die(f"error: no background session {args[0] if args else ''}")
    pid, sid, cwd = int(s["pid"]), s["sessionId"], s["cwd"]

    def on_line(text):
        if text.strip() == "/exit":
            try:
                os.kill(pid, signal.SIGTERM)
                os.remove(os.path.join(SESSIONS, f"{pid}.json"))
            except OSError:
                pass
            print("session ended")
            return True
        if text.strip():
            set_status(pid, "busy")
            append_turn(sid, cwd, text)
            set_status(pid, "idle")
        return False

    read_loop(f"attached to {sid[:8]}", "Ctrl+Z leaves it running · /exit ends it", on_line, lambda: True)
    return 0


def cmd_plain(args):
    opts, prompt = parse(args)
    cwd = os.getcwd()
    sid = opts.get("--resume") if isinstance(opts.get("--resume"), str) else str(uuid.uuid4())
    if opts.get("--fork-session"):
        sid = str(uuid.uuid4())
    started = {"pid": False}

    def first_turn(text):
        if not started["pid"]:
            write_pidfile(os.getpid(), sid, cwd, text[:40] or "plain session", "idle", "interactive")   # like claude: with the first prompt
            started["pid"] = True
        set_status(os.getpid(), "busy")
        append_turn(sid, cwd, text)
        set_status(os.getpid(), "idle")

    def on_line(text):
        if text.strip() == "/exit":
            try:
                os.remove(os.path.join(SESSIONS, f"{os.getpid()}.json"))
            except OSError:
                pass
            return True
        if text.strip():
            first_turn(text)
        return False

    def on_ctrl_z():
        os.kill(os.getpid(), signal.SIGSTOP)               # like the real claude: it stops itself and `fg` continues it
        return False

    if prompt:
        first_turn(prompt)
    read_loop("plain session (foreground)", "Ctrl+Z pauses it · /exit ends it", on_line, on_ctrl_z)
    return 0


def main(argv):
    if not SESSIONS or not PROJECTS:
        die("fake claude: refusing to run without CLAUDE_SESSIONS_DIR and CLAUDE_PROJECTS_DIR (it must never touch real data)")
    if argv and argv[0] == "attach":
        return cmd_attach(argv[1:])
    if argv and argv[0] == "stop":
        return cmd_stop(argv[1:])
    if "--bg" in argv:
        return cmd_bg([a for a in argv if a != "--bg"])
    return cmd_plain(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))             # python -m agents_farm.fake_claude ...
