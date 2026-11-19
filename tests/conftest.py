"""Tests never read or write what agents-farm remembers for the real user (rule 2 in CLAUDE.md)."""

import pytest

from agents_farm import config


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_PATH", str(tmp_path / "state-of-the-test" / "state.json"))
