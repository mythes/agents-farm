"""Tests never read or write what agents-farm remembers for the real user (rule 2 in CLAUDE.md)."""

import pytest

from agents_farm import config, entities, registry


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_PATH", str(tmp_path / "state-of-the-test" / "state.json"))


@pytest.fixture(autouse=True)
def no_real_claude_folder(tmp_path, monkeypatch):
    """The Claude panel reads the user's skills and MCP servers: tests see an empty folder instead."""
    monkeypatch.setattr(entities, "roots", lambda: (str(tmp_path / "claude-of-the-test"), str(tmp_path / "claude-of-the-test.json")))


@pytest.fixture(autouse=True)
def no_ps_cache(monkeypatch):
    """The tests change processes and expect to see it at once: no cache for the `ps` result (see test_performance.py)."""
    monkeypatch.setattr(registry, "PS_TTL_S", 0)
