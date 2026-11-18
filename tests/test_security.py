"""Security regression tests: untrusted transcript / hook content must stay inert."""

import asyncio
import json
import os
import stat
import subprocess
import sys
import tempfile
import time

from agents_farm.model import sanitize
from agents_farm.store import Store

ESC = "\x1b"
EVIL = f"hi{ESC}]52;c;ZXZpbA==\x07{ESC}[2J\u202eevil\x9b31m"
MARKUP = "[@click=app.quit]pwn[/] [link=https://evil.example]x[/link]"


def _write_session(root, sid="s1", cwd="/tmp/proj"):
    d = os.path.join(root, "-tmp-proj")
    os.makedirs(d)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    lines = [
        {"type": "custom-title", "customTitle": EVIL + MARKUP, "sessionId": sid},
        {"type": "user", "timestamp": ts, "cwd": cwd + EVIL, "gitBranch": "main" + ESC,
         "message": {"role": "user", "content": EVIL + MARKUP}},
        {"type": "assistant", "timestamp": ts, "message": {
            "id": "m1", "model": "claude-opus-5-5", "stop_reason": "tool_use",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": EVIL}}]}},
        "this line is not json",
        {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": EVIL}]}},
    ]
    with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
        for line in lines:
            fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_sanitize():
    assert ESC not in sanitize(EVIL) and "\x9b" not in sanitize(EVIL) and "\u202e" not in sanitize(EVIL)
    assert sanitize("a\tb\nc") == "a\tb\nc"


def test_transcript_text_has_no_control_chars():
    with tempfile.TemporaryDirectory() as root:
        _write_session(root)
        snap = Store(root=root, since_hours=24).refresh()
        assert len(snap.agents) == 1
        a = snap.agents[0]
        blobs = [a.title, a.prompt, a.first_prompt, a.cwd, a.branch, a.project] + [i.detail for i in a.activity]
        for text in blobs:
            assert not any(ord(c) < 32 and c not in "\n\t" or 0x7F <= ord(c) <= 0x9F for c in text), repr(text)


def test_hook_file_is_private_and_bounded():
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, AGENTS_FARM_HOME=os.path.join(home, "af"))
        payload = json.dumps({"hook_event_name": "Notification", "session_id": "x", "message": "A" * 50_000})
        r = subprocess.run([sys.executable, "-m", "agents_farm", "hook"], input=payload, text=True, env=env)
        assert r.returncode == 0
        path = os.path.join(home, "af", "events.jsonl")
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
        assert len(json.loads(open(path).read())["message"]) == 1000


def test_hook_never_fails_on_garbage():
    r = subprocess.run([sys.executable, "-m", "agents_farm", "hook"], input="{{{not json", text=True)
    assert r.returncode == 0


def test_hook_cannot_point_reader_outside_projects_dir():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
        secret = os.path.join(other, "secret.jsonl")
        with open(secret, "w") as fh:
            fh.write(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z",
                                 "message": {"role": "user", "content": "TOP SECRET"}}) + "\n")
        store = Store(root=root, since_hours=24)
        assert store._inside_root(secret) is False
        link = os.path.join(root, "x.jsonl")
        os.symlink(secret, link)  # symlink escaping the root is rejected too
        assert store._inside_root(link) is False


def test_notify_and_titles_do_not_interpret_markup():
    from agents_farm.app import FarmApp
    from agents_farm.demo import DemoStore

    async def run():
        store = DemoStore()
        store.agents[0].title = MARKUP
        store.agents[0].project = MARKUP
        app = FarmApp(store, interval=1.0)
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause(1.2)
            app.notify(MARKUP, markup=False)
            await pilot.pause(0.3)
            assert app.is_running  # the injected action did not quit the app
            titles = str(app.query_one("#detail").border_title)
            assert "\\[@click" in titles  # escaped, so it renders as literal text

    asyncio.run(run())


def test_no_hidden_unicode_in_source():
    """Trojan Source: bidi/zero-width characters must never appear literally in the repo."""
    import glob
    import re

    bad = re.compile("[\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")
    root = os.path.dirname(os.path.dirname(__file__))
    for pattern in ("agents_farm/*.py", "tests/*.py", "*.md", "docs/*.md", "pyproject.toml"):
        for path in glob.glob(os.path.join(root, pattern)):
            with open(path, encoding="utf-8") as fh:
                assert not bad.search(fh.read()), path
