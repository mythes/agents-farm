"""The help screen (`?`): the keys, and a decoding of every symbol, letter and column."""

import io

import pytest
from rich.console import Console
from textual.widgets import Static

from agents_farm import capabilities, helptext
from agents_farm.app import HelpScreen
from agents_farm.model import Status
from demo_store import DemoStore
from test_background import run


def test_every_status_and_every_session_key_is_described():
    assert set(helptext.STATUS_HELP) == set(Status)                                  # a new status must come with a decoding
    keys = " ".join(key for _, group in helptext.KEY_GROUPS for key, _ in group)
    for key in capabilities.SESSION_KEYS:
        assert key in keys.split() or f" {key} " in f" {keys} ", key
    assert all(desc.strip() for _, group in helptext.KEY_GROUPS for _, desc in group)


def test_the_columns_cover_the_list_and_explain_the_src_letters():
    names = [n for n, _ in helptext.COLUMNS]
    for column in ("AGENT", "SRC", "MODEL", "PID", "TIME", "CTX"):
        assert column in names
    src = dict(helptext.COLUMNS)["SRC"]
    for part in ("B background", "T terminal", "D Claude Desktop", "S SDK", "B*"):
        assert part in src


def test_the_screen_shows_the_decoding_and_closes():
    async def scenario(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause(0.4)
        assert isinstance(app.screen, HelpScreen)
        out = io.StringIO()
        console = Console(file=out, width=110, color_system=None)
        for widget in app.screen.query(Static):
            console.print(getattr(widget.visual, "_renderable", widget.visual))        # the Rich text or table that the widget shows
        text = " ".join(out.getvalue().split())
        for st in Status:
            assert st.value in text, st
        for needle in ("Symbols in the first column", "Columns and bars", "Good to know", "Ctrl+Z leaves it running", "SRC", "B background"):
            assert needle in text, needle
        await pilot.press("down", "down", "pagedown")                                # it scrolls without a problem
        await pilot.pause(0.2)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, HelpScreen)

    run(scenario, DemoStore())
