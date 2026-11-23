"""The Claude panel of the new-session dialog: what is read, what is never shown, and the Ctrl+T key."""

import asyncio
import json
import os
import time

import pytest
from textual.widgets import DataTable, Static

from agents_farm import app as app_module
from agents_farm import config, entities
from agents_farm.app import FarmApp, NewSession
from agents_farm.entities import Entities, Entity
from demo_store import DemoStore


def put(path, text):
    os.makedirs(path.parent, exist_ok=True)
    path.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")


def skill(root, name, about="does a thing"):
    put(root / "skills" / name / "SKILL.md", f"---\nname: {name}\ndescription: {about}\n---\nbody\n")


@pytest.fixture
def home(tmp_path):
    return tmp_path / "claude-of-the-test"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    return tmp_path / "repo"


def found(items):
    return [(e.source, e.name) for e in items]


# ------------------------------------------------------------------------------------------------- skills

@pytest.mark.parametrize("text, expected", [
    ("---\nname: a\ndescription: b\n---\n", {"name": "a", "description": "b"}),
    ("---\r\nname: 'a'\r\ndescription: \"b: c\"\r\n---\r\n", {"name": "a", "description": "b: c"}),
    ("---\ndescription: >-\n  one\n  two\nname: a\n---\n", {"description": "one two", "name": "a"}),
    ("---\nname: a\n", {}), ("no front matter", {}), ("", {}), ("---\n---\n", {}),
])
def test_front_matter(text, expected):
    assert entities.front_matter(text) == expected


def test_skills_of_the_project_its_parents_and_the_user(home, repo, tmp_path):
    skill(repo / ".claude", "top")
    skill(repo / "sub" / ".claude", "deep", "line\x1b[31m one")
    skill(tmp_path / ".claude", "above")                              # above the root of the repository: not read
    skill(home, "mine")
    skill(home / "skills" / "synced" / "b1", "x")                     # wrong depth, ignored
    put(home / "skills" / "synced" / "b1" / "cloud" / "SKILL.md", "---\nname: cloud\n---\n")
    skill(home / "skills" / "synced" / ".bucket", "hidden")
    e = entities.read(str(repo / "sub"))
    assert found(e.skills) == [("P", "deep"), ("P", "top"), ("U", "mine"), ("C", "cloud")]
    assert e.skills[0].note == "line[31m one"                          # no escape character


def test_bad_skill_files_are_skipped(home, repo):
    root = repo / ".claude" / "skills"
    put(root / "ok" / "SKILL.md", "---\ndescription: d\n---\n" + "x" * 100_000)       # large: only the top is read
    (root / "folder" / "SKILL.md").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "pipe").mkdir()
    os.mkfifo(root / "pipe" / "SKILL.md")                             # opening it must not block
    put(root / "plain" / "SKILL.md", "no front matter")
    (root / "bin").mkdir()
    (root / "bin" / "SKILL.md").write_bytes(b"\xff\xfe\x00")
    start = time.monotonic()
    assert [x.name for x in entities.read(str(repo)).skills] == ["bin", "ok", "plain"]
    assert time.monotonic() - start < 2


# ---------------------------------------------------------------------------------------------------- MCP

def test_mcp_servers_never_show_secrets(home, repo, tmp_path):
    put(repo / ".mcp.json", {"mcpServers": {
        "local": {"command": "/opt/SECRET1/npx SECRET2", "args": ["SECRET3"], "env": {"K": "SECRET4"}},
        "web": {"type": "http", "url": "https://user:SECRET5@mcp.example.com/SECRET6?t=SECRET7", "headers": {"A": "SECRET8"}},
        "bad": 5, "empty": {}, "odd": {"url": "http://[broken"}}})
    put(repo / ".claude" / "settings.local.json", {"disabledMcpjsonServers": ["web", 3]})
    put(tmp_path / "claude-of-the-test.json", {
        "mcpServers": {"mine": {"command": "uvx"}},
        "projects": {str(repo): {"mcpServers": {"private": {"command": "node"}}}, "/other": {"mcpServers": {"no": {"command": "x"}}}}})
    e = entities.read(str(repo))
    assert found(e.mcp) == [("L", "private"), ("P", "local"), ("P", "web"), ("P", "odd"), ("U", "mine")]
    by = {x.name: x for x in e.mcp}
    assert by["local"].note == "stdio · npx" and by["web"].note == "http · mcp.example.com" and by["web"].off and not by["local"].off
    assert "SECRET" not in repr(e) + repr(entities.lines(e, 40))


# ------------------------------------------------------------------------------------------------ plugins

def test_plugins(home, repo):
    cache = home / "plugins" / "cache" / "m"
    put(cache / "kit" / "1" / ".claude-plugin" / "plugin.json", {"name": "kit", "description": "Helpers"})
    skill(cache / "kit" / "1", "one")
    put(cache / "kit" / "1" / ".mcp.json", {"mcpServers": {"a": {"command": "x"}}})
    outside = repo / "evil"
    put(outside / ".claude-plugin" / "plugin.json", {"description": "must not be read"})
    put(home / "plugins" / "installed_plugins.json", {"plugins": {
        "kit@m": [{"installPath": str(cache / "kit" / "1")}], "out@m": [{"installPath": str(outside)}],
        "here@m": [{"projectPath": str(repo), "installPath": ""}], "other@m": [{"projectPath": "/somewhere"}], "bad@m": 7}})
    put(home / "settings.json", {"enabledPlugins": {"kit@m": True, "out@m": True, "missing@m": True, "odd@m": "yes"}})
    put(repo / ".claude" / "settings.json", {"enabledPlugins": {"out@m": False, "here@m": True}})
    put(home / "plugins" / "synced" / "b" / "cloud" / ".claude-plugin" / "plugin.json", {"description": "From claude.ai"})
    put(home / "plugins" / "marketplaces" / "m" / "plugins" / "shop" / ".claude-plugin" / "plugin.json", {"name": "shop"})
    got = {x.name: x for x in entities.read(str(repo)).plugins}
    assert set(got) == {"kit", "out", "here", "missing", "cloud"}          # a plugin that a marketplace only offers is not installed
    assert got["kit"].note == "Helpers · 1 skill · 1 MCP" and not got["kit"].off
    assert got["out"].off and got["out"].note == ""                        # the project says no, and its path is outside
    assert got["here"].source == "P" and not got["here"].off and got["missing"].note == "not installed here" and got["cloud"].source == "C"


@pytest.mark.parametrize("text", ["", "not json", "[1]", "null", '{"plugins": [1], "mcpServers": 3, "projects": [], "enabledPlugins": 1}', "[" * 100_000])
def test_broken_files_give_empty_lists(home, repo, tmp_path, text):
    for path in (repo / ".mcp.json", home / "settings.json", home / "plugins" / "installed_plugins.json",
                 tmp_path / "claude-of-the-test.json", repo / ".claude" / "settings.json"):
        put(path, text)
    assert entities.read(str(repo)) == Entities()
    assert entities.read(str(tmp_path / "missing")) == Entities()


def test_claude_md_agents_and_commands(home, repo):
    put(repo / "CLAUDE.md", "x")
    put(repo / ".claude" / "agents" / "a.md", "x")
    put(home / "agents" / "b.md", "x")
    put(home / "commands" / "c.md", "x")
    assert entities.read(str(repo)).also == ["CLAUDE.md", "2 agents", "1 command"]


def test_the_home_folder_is_not_a_project(monkeypatch, tmp_path):
    monkeypatch.setattr(entities, "roots", lambda: (str(tmp_path / ".claude"), str(tmp_path / ".claude.json")))
    skill(tmp_path / ".claude", "mine")
    assert found(entities.read(str(tmp_path)).skills) == [("U", "mine")]


# -------------------------------------------------------------------------------------------------- lines

@pytest.mark.parametrize("height", [0, 8, 13, 21, 22, 30, 100])
def test_the_lines_fit_and_the_counts_are_true(height):
    e = Entities([Entity(f"s{i}") for i in range(30)], [Entity("p", off=True)], [], ["CLAUDE.md"])
    rows = entities.lines(e, height)
    assert len(rows) <= max(height, 8)
    heads = [r[2] for r in rows if r[0] == "head"]
    assert heads == ["Skills (30)", "Plugins (1)", "MCP servers (0)"]
    shown = sum(r[2].startswith("s") for r in rows if r[0] == "item")
    hidden = [int(r[2][1:].split()[0]) for r in rows if r[2].startswith("+")]
    assert shown + sum(hidden) == 30
    assert [r[3] for r in rows if r[0] == "off"] == ["off · "]


# ----------------------------------------------------------------------------------------------------- UI

def play(scenario, size=(130, 40)):
    async def main():
        app = FarmApp(DemoStore(), interval=60.0, notify_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.5)
            await pilot.press("n")
            await pilot.pause(0.2)
            return await scenario(app, pilot)

    return asyncio.run(main())


def panel(app):
    return str(app.screen.query_one("#ns-preview", Static).render())


async def until(pilot, ready):
    for _ in range(80):
        if ready():
            return
        await pilot.pause(0.05)
    raise AssertionError("timeout")


def test_ctrl_t_switches_the_panel_and_is_remembered(home, repo):
    skill(repo / ".claude", "check", "[bold]no markup[/bold]")
    put(repo / "file.txt", "x")

    async def scenario(app, pilot):
        app.screen.query_one("#ns-dir").value = str(repo) + "/"
        await pilot.pause(0.2)
        assert "file.txt" in panel(app) and "FILES" in str(app.screen.query_one("#ns-preview").border_title)
        await pilot.press("ctrl+t")
        await until(pilot, lambda: "Skills (1)" in panel(app))
        assert "[bold]no markup[/bold]" in panel(app) and "file.txt" not in panel(app)
        assert app.screen.query_one("#ns-dir").has_focus and app.screen.query_one("#ns-dir").value == str(repo) + "/"
        assert config.load_state(app._state_path())["claude_panel"] is True
        await pilot.press("escape")
        await pilot.press("n")
        await until(pilot, lambda: isinstance(app.screen, NewSession) and "Skills (" in panel(app))      # remembered
        await pilot.press("ctrl+t")
        await pilot.pause(0.1)
        assert "Skills (" not in panel(app)

    play(scenario)


def test_moving_fast_reads_only_the_last_folder(home, tmp_path, monkeypatch):
    for n in ("a", "b", "c", "d"):
        (tmp_path / "w" / n).mkdir(parents=True)
    asked = []
    monkeypatch.setattr(entities, "read", lambda path: asked.append(os.path.basename(path)) or Entities(also=[os.path.basename(path)]))
    monkeypatch.setattr(app_module, "PANEL_DELAY_S", 0.6)

    async def scenario(app, pilot):
        await pilot.press("ctrl+t")
        app.screen.query_one("#ns-dir").value = str(tmp_path / "w") + "/"
        await pilot.pause(0.1)
        await pilot.press("down", "down", "down")
        await until(pilot, lambda: "Also: b" in panel(app))
        assert asked == ["b"]
        await pilot.press("up", "down")                               # known: shown at once, not read again
        await pilot.pause(0.1)
        assert "Also: b" in panel(app) and asked.count("b") == 1

    play(scenario)


def test_a_slow_answer_after_the_dialog_is_closed_or_moved_is_ignored(home, repo, monkeypatch):
    async def scenario(app, pilot):
        dialog = app.screen
        dialog._claude_ready("/not/the/marked/folder", Entities(also=["old"]))
        assert "old" not in panel(app)
        await pilot.press("escape")
        await pilot.pause(0.2)
        dialog._claude_ready("/x", Entities())                        # no exception

    play(scenario)


def test_an_unexpected_error_leaves_the_dialog_usable(home, monkeypatch):
    def broken(path):
        raise RuntimeError("no")

    monkeypatch.setattr(entities, "read", broken)

    async def scenario(app, pilot):
        await pilot.press("ctrl+t")
        await until(pilot, lambda: "cannot be read" in panel(app))
        await pilot.press("escape")

    play(scenario)


def test_a_narrow_terminal_shows_the_panel_in_place_of_the_list(home):
    async def scenario(app, pilot):
        table, side = app.screen.query_one("#ns-list", DataTable), app.screen.query_one("#ns-preview")
        assert table.display and not side.display
        await pilot.press("ctrl+t")
        await until(pilot, lambda: "Skills (" in panel(app))
        assert side.display and not table.display
        before = table.cursor_row
        await pilot.press("down")
        assert table.cursor_row == before + 1                         # the arrow keys still move the marker
        await pilot.press("ctrl+t")
        await pilot.pause(0.1)
        assert table.display and not side.display

    play(scenario, size=(80, 30))


@pytest.mark.parametrize("size", [(80, 24), (110, 32), (160, 50)])
def test_every_line_fits_in_the_panel(home, repo, size):
    for i in range(30):
        skill(repo / ".claude", f"a-very-long-skill-name-{i}", "word " * 60)

    async def scenario(app, pilot):
        app.screen.query_one("#ns-dir").value = str(repo) + "/"
        await pilot.press("ctrl+t")
        await until(pilot, lambda: "Skills (30)" in panel(app))
        await pilot.pause(0.2)
        side = app.screen.query_one("#ns-preview", Static)
        rows = panel(app).rstrip("\n").split("\n")
        assert max(len(r) for r in rows) <= side.content_size.width and len(rows) <= max(side.content_size.height, 8)
        assert "MCP servers (0)" in panel(app) and "C claude.ai" in panel(app)

    play(scenario, size=size)


def test_ctrl_t_does_nothing_in_the_prompt_editor(home):
    async def scenario(app, pilot):
        await pilot.press("ctrl+f", "ctrl+t")
        await pilot.pause(0.1)
        assert app.screen._claude_panel is False

    play(scenario)
