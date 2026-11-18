"""The Textual UI with demo data: PID column, fuzzy search, copy PID."""

import asyncio

from textual.widgets import DataTable

from agents_farm.app import FarmApp
from agents_farm.demo import DemoStore


def run(scenario, size=(130, 32)):
    async def main():
        app = FarmApp(DemoStore(), interval=60.0, notify_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(1.0)
            return await scenario(app, pilot)

    return asyncio.run(main())


def pids(app):
    table = app.query_one(DataTable)
    col = [c.key.value for c in table.columns.values()].index("pid")
    return {key: str(table.get_row(key)[col]) for key in app.row_keys}


def test_pid_column_shows_pid_or_dash():
    async def scenario(app, pilot):
        table = app.query_one(DataTable)
        assert [str(c.label) for c in table.columns.values()] == [" ", "AGENT", "MODEL", "PID", "TIME", "CTX"]
        shown = pids(app)
        assert shown["demo-docs-writer"] == "40217"          # a running session
        assert shown["demo-api-refactor/agent-1"] == "—"     # a subagent has no process of its own
        assert shown["demo-lint-pass"] == "—"                 # finished: no process

    run(scenario)


def test_details_show_the_process_line():
    async def scenario(app, pilot):
        header = app.query_one("#d-head").render()
        assert "pid 40217" in str(header) and "Desktop" in str(header)

    run(scenario)


def test_fuzzy_search_finds_and_highlights():
    async def scenario(app, pilot):
        await pilot.press("slash")
        await pilot.press(*"apirf")
        await pilot.pause(0.3)
        assert app.row_keys == ["demo-api-refactor"]
        assert app._hl["demo-api-refactor"] == [0, 1, 2, 4, 6]
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert len(app.row_keys) > 3                              # the list is back

    run(scenario)


def test_status_filter_and_fuzzy_word_together():
    async def scenario(app, pilot):
        await pilot.press("slash")
        await pilot.press(*"status:error dep")
        await pilot.pause(0.3)
        assert app.row_keys == ["demo-deploy-check"]

    run(scenario)


def test_incomplete_filter_does_not_empty_the_list():
    async def scenario(app, pilot):
        await pilot.press("slash")
        await pilot.press(*"status:")
        await pilot.pause(0.3)
        assert len(app.row_keys) > 3

    run(scenario)


def test_p_copies_the_pid():
    async def scenario(app, pilot):
        copied = []
        app.copy_to_clipboard = copied.append
        await pilot.press("p")
        assert copied == ["40217"]                                # the first row is docs-writer
        for _ in range(len(app.row_keys)):                        # move down to the subagent row
            if app.selected_id == "demo-api-refactor/agent-1":
                break
            await pilot.press("j")
            await pilot.pause(0.1)
        assert app.selected_id == "demo-api-refactor/agent-1"
        await pilot.press("p")
        assert copied == ["40217"]                                # a subagent has no pid: nothing copied

    run(scenario)


def test_quitting_leaves_no_errors():
    """Timers and the data worker can fire once more while the app closes. That must be silent."""
    async def scenario(app, pilot):
        await pilot.press("q")
        await pilot.pause(1.0)

    run(scenario)
