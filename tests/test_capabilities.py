"""Greyed-out keys with an explanation: what each key can do for the selected session, and why not."""

import pytest
from textual.widgets import Static

from agents_farm import capabilities as cap
from agents_farm.app import AttachHint, ConfirmFork, ConfirmResume, Explain
from demo_store import DemoStore
from agents_farm.model import Agent
from agents_farm.store import Store
from test_background import BG_SID, _store, calls, needs_ps, run  # noqa: F401  (calls is a fixture)
from test_resume import _dead_store


def agent(tmp_path=None, pid=None, bg=False, parent=None, from_pid=False, live=False, entry="", origin="", cwd="ok"):
    a = Agent(id=BG_SID, transcript="", cwd=str(tmp_path) if cwd == "ok" and tmp_path else (cwd if cwd != "ok" else ""))
    a.pid, a.background, a.parent, a.from_pid_file, a.live, a.entrypoint, a.origin = pid, bg, parent, from_pid, live, entry, origin
    return a


def text(app, selector):
    return " ".join(str(app.screen.query_one(selector, Static).render()).split())


# --------------------------------------------------------------- what is possible (no UI)

def test_every_key_is_explained_when_nothing_is_selected():
    for action in cap.SESSION_KEYS.values():
        why = cap.unavailable(action, None)
        assert why and "No session" in why.title and why.options


def test_attach_only_for_a_running_background_session(tmp_path):
    assert cap.unavailable("attach", agent(tmp_path, pid=5, bg=True, live=True)) is None
    cli = cap.unavailable("attach", agent(tmp_path, pid=5, live=True, entry="cli"))
    assert "not a background session" in cli.title and any(o.startswith("f  ") for o in cli.options)
    ended = cap.unavailable("attach", agent(tmp_path))
    assert "not running" in ended.title and any(o.startswith("r  ") for o in ended.options)


def test_continue_is_only_for_a_session_that_has_ended(tmp_path):
    assert cap.unavailable("resume", agent(tmp_path)) is None                              # ended: continue
    assert cap.unavailable("resume", agent(tmp_path, entry="")) is None
    running = cap.unavailable("resume", agent(tmp_path, pid=5, live=True))                 # runs in a terminal or Desktop
    assert "running now" in running.title and any(o.startswith("f  ") for o in running.options)
    bg = cap.unavailable("resume", agent(tmp_path, pid=5, bg=True, live=True))
    assert "already running" in bg.title and any(o.startswith("a  ") for o in bg.options) and any(o.startswith("f  ") for o in bg.options)
    unknown = cap.unavailable("resume", agent(tmp_path, live=None))                        # no process files: we cannot tell
    assert "cannot tell" in unknown.title and any(o.startswith("f  ") for o in unknown.options)
    assert "no history" in cap.unavailable("resume", agent(tmp_path, pid=5, bg=True, from_pid=True)).title
    assert "folder" in cap.unavailable("resume", agent(tmp_path, cwd=str(tmp_path / "gone"))).title
    assert "folder" in cap.unavailable("resume", agent(tmp_path, cwd="")).title


def test_fork_works_for_every_session_that_has_a_history(tmp_path):
    for a in (agent(tmp_path), agent(tmp_path, pid=5, live=True), agent(tmp_path, pid=5, bg=True, live=True),
              agent(tmp_path, live=None), agent(tmp_path, entry="claude-desktop")):
        assert cap.unavailable("fork", a) is None
    assert "no history" in cap.unavailable("fork", agent(tmp_path, pid=5, bg=True, from_pid=True)).title
    assert "folder" in cap.unavailable("fork", agent(tmp_path, cwd=str(tmp_path / "gone"))).title


def test_stop_and_copy_pid_reasons(tmp_path):
    assert cap.unavailable("kill", agent(tmp_path, pid=5, live=True)) is None
    assert "not running" in cap.unavailable("kill", agent(tmp_path)).title
    off = cap.unavailable("kill", agent(tmp_path, pid=5), {"allow_kill": False})
    assert "turned off" in off.title and "allow_kill" in " ".join(off.options)
    assert cap.unavailable("copy_pid", agent(tmp_path, pid=5)) is None
    assert "not running" in cap.unavailable("copy_pid", agent(tmp_path)).title


def test_one_rule_for_a_subagent_select_its_parent(tmp_path):
    for action in cap.SESSION_KEYS.values():
        assert "subagent" in cap.unavailable(action, agent(tmp_path, pid=5, parent="x")).title, action


def test_every_option_key_in_a_pop_up_leads_somewhere_that_exists(tmp_path):
    """An option line starts with a key; if it is a letter, the pop-up runs it, so it must be a known action."""
    agents = [agent(tmp_path), agent(tmp_path, pid=5, live=True), agent(tmp_path, pid=5, bg=True, live=True),
              agent(tmp_path, live=None), agent(tmp_path, parent="x", pid=5), agent(tmp_path, pid=5, bg=True, from_pid=True)]
    for a in agents:
        for action in cap.SESSION_KEYS.values():
            why = cap.unavailable(action, a, {"allow_kill": False})
            for option in (why.options if why else []):
                key = option.partition("  ")[0]
                if len(key) == 1 and key.isalpha():
                    assert key in cap.OPTION_ACTIONS, (action, option)


# ------------------------------------------------------------------------ the footer and the pop-up

def bindings(app):
    return {k: v for k, v in app.screen.active_bindings.items() if k in cap.SESSION_KEYS}


def test_the_footer_greys_out_the_keys_an_ended_session_cannot_use(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        b = bindings(app)
        assert b["r"].enabled and b["f"].enabled                                    # continue, fork
        assert not b["a"].enabled and not b["x"].enabled and not b["p"].enabled     # nothing runs: nothing to open, stop, copy

    run(scenario, _dead_store(tmp_path))


@needs_ps
def test_the_footer_follows_a_running_background_session(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        b = bindings(app)
        assert b["a"].enabled and b["x"].enabled and b["p"].enabled and b["f"].enabled
        assert not b["r"].enabled                                                   # it already runs: open it, or fork it

    run(scenario, _store(tmp_path, kind="bg"))


def test_the_keys_of_the_session_come_first_in_the_footer(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        shown = [v.binding.key for v in app.screen.active_bindings.values() if v.binding.show]
        assert shown[:5] == ["n", "a", "r", "f", "x"], shown

    run(scenario, _dead_store(tmp_path))


def test_a_greyed_key_opens_an_explanation_and_an_option_key_runs_it(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("a")                                                      # open: this session is not running
        await pilot.pause(0.3)
        assert isinstance(app.screen, Explain)
        body = text(app, "#explain-body")
        assert "This session is not running" in body and "What you can do" in body and "continue it" in body
        await pilot.press("r")                                                      # the option key does it
        await pilot.pause(0.4)
        assert isinstance(app.screen, ConfirmResume)
        await pilot.press("escape")

    run(scenario, _dead_store(tmp_path))
    assert calls["start"] == []


def test_escape_closes_the_explanation_and_nothing_happens(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("x")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Explain)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, Explain)

    run(scenario, _dead_store(tmp_path))
    assert calls["start"] == [] and calls["interactive"] == [] and calls["kill"] == []


@needs_ps
def test_continue_on_a_running_background_session_points_to_open_or_fork(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("r")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Explain) and "already running" in text(app, "#explain-body")
        await pilot.press("a")
        await pilot.pause(0.4)
        assert isinstance(app.screen, AttachHint)
        await pilot.press("escape")

    run(scenario, _store(tmp_path, kind="bg"))


@needs_ps
def test_continue_on_a_session_that_runs_elsewhere_points_to_fork_and_the_option_key_forks(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("r")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Explain) and "running now" in text(app, "#explain-body")
        await pilot.press("f")                                                      # the option key
        await pilot.pause(0.4)
        assert isinstance(app.screen, ConfirmFork)
        await pilot.press("enter")
        await pilot.pause(1.0)

    run(scenario, _store(tmp_path, kind="interactive"))
    assert calls["start"] == [(str(tmp_path), ["--resume", BG_SID, "--fork-session"])]


@needs_ps
def test_attach_on_a_terminal_session_explains_that_it_is_not_a_background_session(tmp_path, calls):  # noqa: F811
    async def scenario(app, pilot):
        await pilot.press("a")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Explain)
        body = text(app, "#explain-body")
        assert "not a background session" in body and "pid" in body and "fork it" in body
        await pilot.press("escape")

    run(scenario, _store(tmp_path, kind="interactive"))


def test_with_nothing_selected_every_key_explains_that(calls):  # noqa: F811
    async def scenario(app, pilot):
        for key in ("a", "r", "f", "x", "p"):
            await pilot.press(key)
            await pilot.pause(0.2)
            assert isinstance(app.screen, Explain) and "No session" in text(app, "#explain-body"), key
            await pilot.press("escape")
            await pilot.pause(0.2)

    empty = Store(root="/nonexistent-projects-folder", since_hours=24, sessions_dir="/nonexistent-sessions-folder")
    run(scenario, empty)


def test_a_subagent_is_explained_not_ignored(calls):  # noqa: F811
    async def scenario(app, pilot):
        for _ in range(len(app.row_keys) * 2):
            if app.selected_id == "demo-api-refactor/agent-1":
                break
            await pilot.press("j")
            await pilot.pause(0.05)
        assert app.selected_id == "demo-api-refactor/agent-1"
        for key in ("r", "f"):
            await pilot.press(key)
            await pilot.pause(0.3)
            assert isinstance(app.screen, Explain) and "subagent" in text(app, "#explain-body")
            await pilot.press("escape")
            await pilot.pause(0.2)

    run(scenario, DemoStore())
