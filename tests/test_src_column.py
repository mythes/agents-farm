"""The SRC column: where a session was started, and a star for the sessions this agents-farm started."""

import pytest
from textual.widgets import DataTable

from agents_farm import render as R
from agents_farm.model import Agent
from demo_store import DemoStore
from test_background import run


def agent(**kw):
    a = Agent(id="aaaaaaaa-0000-0000-0000-000000000001", transcript="")
    for k, v in kw.items():
        setattr(a, k, v)
    return a


@pytest.mark.parametrize("fields, letter", [
    ({"background": True, "origin": "cli"}, "B"),                 # a background session is B whatever started the process
    ({"entrypoint": "cli"}, "T"), ({"entrypoint": "claude-desktop"}, "D"), ({"origin": "sdk-cli"}, "S"),
    ({"origin": "claude-desktop"}, "D"),                          # an ended session: the transcript knows
    ({}, "·"), ({"entrypoint": "something-new"}, "·"),
])
def test_the_letter(fields, letter):
    assert R.src_letter(agent(**fields)) == letter


def test_the_star_means_this_agents_farm_started_it():
    assert R.src_cell(agent(entrypoint="cli")).plain == "T"
    assert R.src_cell(agent(entrypoint="cli"), mine=True).plain == "T*"
    assert R.src_cell(agent(background=True), mine=True).plain == "B*"


def test_the_column_is_in_the_list_and_the_star_follows_the_session_ids():
    async def scenario(app, pilot):
        table = app.query_one(DataTable)
        col = [c.key.value for c in table.columns.values()].index("src")
        letters = {key: str(table.get_row(key)[col]) for key in app.row_keys}
        assert letters["demo-docs-writer"] == "D" and letters["demo-api-refactor"] == "T"
        app._mine.add("demo-api-ref")                                               # a prefix is enough: the id of a new session is known by its first characters
        assert app._is_mine(next(a for a in app.snap.agents if a.id == "demo-api-refactor"))
        app._render_table()
        await pilot.pause(0.3)
        assert str(table.get_row("demo-api-refactor")[col]) == "T*"
        assert str(table.get_row("demo-docs-writer")[col]) == "D"

    run(scenario, DemoStore())
