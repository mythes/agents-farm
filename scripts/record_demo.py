#!/usr/bin/env python3
"""Record a scripted demo of `agents-farm --demo` as an asciicast v2 file.

The cast is plain text (tens of KB), so it is the small source of truth.
`scripts/make_demo.sh` turns it into the GIF used in the README.

Usage: python scripts/record_demo.py [output.cast]
"""

import codecs
import fcntl
import json
import os
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

COLS, ROWS = 120, 30
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "docs", "demo.cast")

ESC, ENTER = b"\x1b", b"\r"


def typed(text, gap=0.11):
    return [(gap, ch.encode()) for ch in text]


# (seconds to wait before sending, bytes to send). The demo data is fake.
STEPS = (
    [(2.6, b"")]                        # first look: the agent that waits for you is on top
    + [(1.2, b"j"), (0.9, b"j"), (0.9, b"j")]   # move down to the running agent (plan + activity)
    + [(2.0, b"z")]                     # zoom: details on the full screen
    + [(1.8, ESC)]                      # back to the list
    + [(1.0, b"/")] + typed("apir") + [(1.8, ESC)]   # fuzzy search, then clear it
    + [(1.0, b"n")] + typed("apir") + [(1.8, b"\t")]   # new session: fuzzy folder, Tab opens it
    + [(1.8, b"\x01")] + typed("son") + [(1.4, ENTER)]  # Ctrl+A: pick a model
    + [(1.0, b"\x13"), (1.0, b"\x02")]                  # Ctrl+S mode, Ctrl+B background (start closed)
    + [(1.2, b"\x06")] + typed("fix tests", gap=0.06) + [(0.5, ENTER)] + typed("lint too", gap=0.06)   # Ctrl+F: the prompt editor (Enter = new line)
    + [(1.4, b"\x06")]                  # Ctrl+F again: back to the folders
    + [(1.6, ESC)]                      # cancel: the demo never starts claude
    + [(1.0, b"/")] + typed("mig") + [(0.8, ENTER)]   # find the background session
    + [(1.4, b"a")] + [(2.4, ESC)]      # attach: the hint says how to come back (Ctrl+Z)
    + [(0.8, ESC)]                      # clear the search
    + [(0.8, b"q")]
)


def make_fake_home(home):
    """A made-up home folder, so the new-session dialog shows no real paths."""
    projects = os.path.join(home, "projects")
    for name in ("api-refactor", "docs-writer", "deploy-check", "lint-pass", "perf-audit"):
        os.makedirs(os.path.join(projects, name), exist_ok=True)
    for sub in ("src", "tests", "docs"):
        os.makedirs(os.path.join(projects, "api-refactor", sub), exist_ok=True)
    os.makedirs(os.path.join(projects, "api-refactor", ".git"), exist_ok=True)
    with open(os.path.join(projects, "api-refactor", ".git", "HEAD"), "w") as fh:
        fh.write("ref: refs/heads/feature/api-v2\n")
    for name in ("README.md", "pyproject.toml"):
        with open(os.path.join(projects, "api-refactor", name), "w") as fh:
            fh.write("demo\n")
    return projects


def main():
    out_path = os.path.abspath(OUT)
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", LANG="en_US.UTF-8")
    env.pop("NO_COLOR", None)
    with tempfile.TemporaryDirectory() as home:
        home = os.path.realpath(home)   # on macOS /var is a link to /private/var: the paths must match
        env["AGENTS_FARM_HOME"] = home  # never read the real user config
        env["HOME"] = home              # ~ is the made-up home: no real path is drawn
        projects = make_fake_home(home)
        repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        env["PYTHONPATH"] = os.path.abspath(repo)

        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        proc = subprocess.Popen(
            [sys.executable, "-m", "agents_farm", "--demo", "--interval", "6"],  # rare data refresh = fewer repaints
            stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True,
            cwd=projects,               # the new-session dialog starts here: ~/projects
        )
        os.close(slave)

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        events = []
        start = time.monotonic()

        def pump(seconds):
            end = time.monotonic() + seconds
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    return
                ready, _, _ = select.select([master], [], [], min(left, 0.05))
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        return
                    if not data:
                        return
                    text = decoder.decode(data)
                    if text:
                        events.append([round(time.monotonic() - start, 4), "o", text])

        try:
            for wait, keys in STEPS:
                pump(wait)
                if keys:
                    os.write(master, keys)
            pump(1.0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            os.close(master)

    header = {
        "version": 2, "width": COLS, "height": ROWS, "timestamp": int(time.time()),
        "title": "agents-farm demo", "env": {"TERM": "xterm-256color", "SHELL": "/bin/zsh"},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    size = os.path.getsize(out_path)
    print(f"wrote {out_path}: {len(events)} events, {size / 1024:.0f} KB, {events[-1][0]:.1f}s")


if __name__ == "__main__":
    main()
