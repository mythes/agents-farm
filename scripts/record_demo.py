#!/usr/bin/env python3
"""Record scripted demos of `agents-farm --demo`, one short recording per feature, as asciicast v2 files.

The casts are plain text (tens of KB), so they are the small source of truth.
`scripts/make_demo.sh` turns each one into a GIF for the README.

Usage:
    python scripts/record_demo.py --list            list the scenarios
    python scripts/record_demo.py NAME [out.cast]   record one scenario (default: docs/demo/NAME.cast)
    python scripts/record_demo.py --all             record every scenario
"""

import codecs
import fcntl
import json
import os
import select
import struct
import subprocess
import sys
import termios
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT_DIR = os.path.join(ROOT, "docs", "demo")

ESC, ENTER, TAB = b"\x1b", b"\r", b"\t"
CTRL_A, CTRL_B, CTRL_D, CTRL_E, CTRL_F, CTRL_S, CTRL_T = b"\x01", b"\x02", b"\x04", b"\x05", b"\x06", b"\x13", b"\x14"


def typed(text, gap=0.1):
    return [(gap, ch.encode()) for ch in text]


def find(text):
    """Filter the list to one agent and move the cursor into it (search, then Enter)."""
    return [(1.0, b"/")] + typed(text, 0.09) + [(0.7, ENTER)]


def clear():
    return [(0.7, ESC)]


# name -> (columns, rows, steps). A step is (seconds to wait before sending, bytes to send).
# The data is the demo playground (agents_farm/playground.py): made-up sessions and a fake claude.
SCENARIOS = {
    # The list (with the SRC column), the details, the zoom, the idle sessions and the period (t).
    "overview": (100, 26,
                 [(2.0, b""), (1.1, b"j"), (0.9, b"j"), (0.9, b"j"), (1.6, b"z"), (1.8, ESC), (1.0, b"h"), (2.0, b""), (1.0, b"t"), (2.6, b"t"), (2.6, b"t"), (2.0, b"")]),

    # Fuzzy search and the status: filter.
    "search": (100, 26,
               [(1.8, b""), (1.0, b"/")] + typed("apir") + [(1.8, ESC), (1.0, b"/")] + typed("status:waiting") + [(2.0, ESC)]),

    # The new-session dialog: folders, model, mode, a multi-line first prompt.
    "new-session": (110, 32,
                    find("apir") + [(1.2, b"n"), (1.6, CTRL_T), (2.6, CTRL_T)] + typed("te") + [(1.6, TAB), (1.6, CTRL_A)] + typed("so") + [(1.2, ENTER), (1.0, CTRL_S), (1.2, CTRL_F)]
                    + typed("fix it", 0.06) + [(0.4, ENTER)] + typed("lint", 0.06) + [(1.4, CTRL_F), (2.0, ESC)] + clear()),

    # "Open now" or "stay here", and how to come back from a session (Ctrl+Z).
    "background": (110, 32,
                   find("mig") + [(1.2, b"n"), (2.2, b""), (1.0, CTRL_B), (2.4, b""), (1.0, ESC)]
                   + [(1.2, b"a"), (3.2, ESC)] + clear()),

    # Continue an ended session (r), a Desktop chat defaults to a fork, and fork a session that runs (f).
    "resume": (110, 30,
               find("spike") + [(1.2, b"r"), (3.0, ESC)] + clear()
               + find("release") + [(1.2, b"r"), (3.2, ESC)] + clear()
               + find("apir") + [(1.2, b"f"), (3.2, ESC)] + clear()),

    # A key that does not fit the selected session is grey, and says why.
    "greyed-keys": (110, 30,
                    find("spike") + [(2.2, b"a"), (3.6, b"r"), (2.4, ESC)] + clear()
                    + find("apir") + [(1.4, b"r"), (3.4, b"f"), (2.4, ESC)] + clear()),

    # The help screen: every key, symbol, letter and column explained.
    "help": (110, 36,
             [(2.0, b""), (1.0, b"?"), (3.2, b"\x1b[6~"), (3.2, b"\x1b[6~"), (3.0, ESC)]),

    # Stop a session: a process (asks first, default No) and a background session.
    "stop": (100, 26,
             find("apir") + [(1.2, b"x"), (3.4, b"n")] + clear()
             + find("mig") + [(1.2, b"x"), (3.4, b"n")] + clear()),
}


def record(name, out_path):
    cols, rows, steps = SCENARIOS[name]
    out_path = os.path.abspath(out_path)
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", LANG="en_US.UTF-8", PYTHONPATH=os.path.abspath(ROOT))
    env.pop("NO_COLOR", None)
    env["AGENTS_FARM_DEMO_ALERTS"] = "0"            # no pop-up alerts over the keys in the recording

    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen(
        [sys.executable, "-m", "agents_farm", "--demo", "--interval", "6"],   # the demo builds its own made-up home folder
        stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True,
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
        deadline = time.monotonic() + 15            # the demo builds its folders and processes first: wait for the screen
        while time.monotonic() < deadline and not any("AGENTS" in e[2] for e in events):
            pump(0.1)
        pump(0.5)
        for wait, keys in steps:
            pump(wait)
            if keys:
                os.write(master, keys)
        pump(1.0)
    finally:
        if proc.poll() is None:
            proc.terminate()                         # the demo removes its fake processes when it ends
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        os.close(master)

    if events:                                       # the recording starts at the first screen, not at the build
        first = events[0][0]
        for event in events:
            event[0] = round(event[0] - first + 0.1, 4)

    header = {
        "version": 2, "width": cols, "height": rows, "timestamp": int(time.time()),
        "title": f"agents-farm: {name}", "env": {"TERM": "xterm-256color", "SHELL": "/bin/zsh"},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    size = os.path.getsize(out_path)
    print(f"{name}: {out_path}: {len(events)} events, {size / 1024:.0f} KB, {events[-1][0]:.1f}s")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        print("\n".join(SCENARIOS))
        return 0
    if argv[0] == "--all":
        for name in SCENARIOS:
            record(name, os.path.join(OUT_DIR, name + ".cast"))
        return 0
    if argv[0] not in SCENARIOS:
        print(f"unknown scenario {argv[0]!r}; try --list", file=sys.stderr)
        return 2
    record(argv[0], argv[1] if len(argv) > 1 else os.path.join(OUT_DIR, argv[0] + ".cast"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
