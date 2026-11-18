import json
import os
import tempfile
import time

from agents_farm.config import DEFAULTS
from agents_farm.model import Agent
from agents_farm.render import context_window
from agents_farm.store import Store

W = DEFAULTS["context_window"]


def _agent(model, tokens):
    return Agent(id="x", transcript="", model=model, context_tokens=tokens)


def test_claude5_models_use_1m_window():
    assert context_window(_agent("claude-opus-5-5", 100_000), W) == 1_000_000
    assert context_window(_agent("claude-sonnet-5-5", 196_500), W) == 1_000_000


def test_unknown_model_defaults_and_never_exceeds_100_percent():
    assert context_window(_agent("claude-haiku-5-5", 100_000), W) == 200_000
    win = context_window(_agent("claude-haiku-5-5", 250_000), W)  # exceeded the assumed window
    assert win >= 250_000


def test_longest_substring_wins_and_user_override():
    w = {"default": 200_000, "opus": 500_000, "opus-5": 1_000_000}
    assert context_window(_agent("claude-opus-5-5", 1), w) == 1_000_000
    assert context_window(_agent("claude-opus-4-1", 1), w) == 500_000


def test_synthetic_zero_usage_does_not_reset_context():
    with tempfile.TemporaryDirectory() as root:
        d = os.path.join(root, "-p")
        os.makedirs(d)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        def asst(mid, model, inp, cr):
            return {"type": "assistant", "timestamp": ts, "message": {
                "id": mid, "model": model, "stop_reason": "end_turn",
                "usage": {"input_tokens": inp, "output_tokens": 0, "cache_read_input_tokens": cr},
                "content": [{"type": "text", "text": "ok"}]}}

        with open(os.path.join(d, "s.jsonl"), "w") as fh:
            for line in (asst("a", "claude-opus-5-5", 10, 150_000), asst("b", "<synthetic>", 0, 0)):
                fh.write(json.dumps(line) + "\n")
        agent = Store(root=root, since_hours=24).refresh().agents[0]
        assert agent.context_tokens == 150_010
