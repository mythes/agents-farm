"""Fuzzy search and exact filters."""

import time

from agents_farm.model import Agent, Status
from agents_farm.search import Query


def agent(title, project="backend", branch="main", model="claude-opus-5-5", prompt="", status=Status.RUNNING):
    a = Agent(id=title, transcript="", title=title, project=project, branch=branch, model=model, prompt=prompt)
    a.status = status
    return a


AGENTS = [
    agent("docs-writer", prompt="Update the README", status=Status.WAITING, model="claude-sonnet-5-5"),
    agent("api-refactor", prompt="Move auth into its own module"),
    agent("deploy-check", prompt="Check the staging deploy", status=Status.ERROR, model="claude-sonnet-5-5"),
    agent("perf-audit", prompt="Find slow queries in /reports", project="reports", branch="feat/speed"),
    agent("lint-pass", prompt="Run the linter", status=Status.DONE, model="claude-haiku-5-5"),
]


def found(text):
    q = Query(text)
    scored = [(q.score(a), a.title) for a in AGENTS]
    return [t for s, t in sorted((x for x in scored if x[0] is not None), key=lambda x: -x[0])]


def test_empty_query_matches_everything_and_does_not_rank():
    q = Query("   ")
    assert not q.active and not q.ranks
    assert all(q.score(a) == 0.0 for a in AGENTS)


def test_fuzzy_letters_find_the_agent():
    assert found("apirf") == ["api-refactor"]
    assert found("dcswr") == ["docs-writer"]


def test_better_match_ranks_first():
    names = found("dep")
    assert names[0] == "deploy-check"


def test_filter_and_fuzzy_word_work_together():
    assert found("status:error dep") == ["deploy-check"]
    assert found("status:waiting dep") == []


def test_exact_filters():
    assert found("status:waiting") == ["docs-writer"]
    assert sorted(found("model:sonnet")) == ["deploy-check", "docs-writer"]
    assert found("project:reports") == ["perf-audit"]


def test_incomplete_filter_while_typing_is_ignored():
    assert len(found("status:")) == len(AGENTS)


def test_unknown_key_is_a_normal_word():
    q = Query("foo:bar")
    assert q.terms == ["foo:bar"] and not q.filters


def test_model_and_prompt_match_as_plain_text():
    assert found("haiku") == ["lint-pass"]
    assert found("slow queries") == ["perf-audit"]
    assert found("staging") == ["deploy-check"]


def test_branch_and_project_are_searched():
    assert "perf-audit" in found("speed")
    assert "perf-audit" in found("reports")


def test_all_words_must_match():
    assert found("api module") == ["api-refactor"]
    assert found("api staging") == []


def test_name_offsets_point_at_the_matched_letters():
    q = Query("apirf")
    a = AGENTS[1]
    offsets = q.name_offsets(a)
    assert len(offsets) == 5 and offsets == sorted(offsets)
    assert "".join(a.name[i] for i in offsets) == "apirf"
    assert Query("status:error").name_offsets(a) == []


def test_search_is_fast_for_many_agents():
    many = [agent(f"agent-{i}-refactor", project=f"proj{i % 7}") for i in range(500)]
    q = Query("agrf proj3")
    start = time.perf_counter()
    for a in many:
        q.score(a)
        q.name_offsets(a)
    assert time.perf_counter() - start < 1.0
