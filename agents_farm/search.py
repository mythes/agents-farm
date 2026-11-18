"""Search over agents: fuzzy words plus exact `key:value` filters.

    apirf                  fuzzy: finds "api-refactor"
    status:waiting         exact filter on the status
    model:opus project:api exact filters (the value is a part of the text)
    status:error dep       a filter and a fuzzy word together

Every word must match (AND). Fuzzy words are matched against the agent name, project
and branch, with weights. The model and the prompt are matched as a plain part of
the text only: a fuzzy match inside a long prompt would match almost anything.
Uses the fuzzy matcher that comes with Textual, so there is no extra dependency.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from textual.fuzzy import FuzzySearch

from .model import Agent

FILTER_KEYS = ("status", "model", "project")

W_NAME, W_PROJECT, W_BRANCH = 3.0, 2.0, 1.5
W_MODEL, W_PROMPT = 2.0, 1.0          # plain "contains" matches get a fixed, lower score
FUZZY_TEXT_LIMIT = 200                # characters of a field that are matched


class Query:
    def __init__(self, text: str = ""):
        self.raw = (text or "").strip()
        self.filters: List[Tuple[str, str]] = []
        self.terms: List[str] = []
        for token in self.raw.lower().split():
            key, sep, value = token.partition(":")
            if sep and key in FILTER_KEYS:
                if value:                      # "status:" while you type is ignored
                    self.filters.append((key, value))
            else:
                self.terms.append(token)
        self._fuzzy = FuzzySearch(case_sensitive=False)

    @property
    def active(self) -> bool:
        return bool(self.filters or self.terms)

    @property
    def ranks(self) -> bool:
        """True if the result order should follow the match score."""
        return bool(self.terms)

    def score(self, agent: Agent) -> Optional[float]:
        """None if the agent does not match, else a score (bigger is better)."""
        for key, value in self.filters:
            field = {
                "status": agent.status.value,
                "model": agent.model,
                "project": f"{agent.project} {agent.cwd}",
            }[key]
            if value not in field.lower():
                return None
        total = 0.0
        for term in self.terms:
            best = self._term_score(term, agent)
            if best <= 0:
                return None
            total += best
        return total

    def _term_score(self, term: str, agent: Agent) -> float:
        best = 0.0
        for text, weight in ((agent.name, W_NAME), (agent.project, W_PROJECT), (agent.branch, W_BRANCH)):
            if text:
                score, _ = self._fuzzy.match(term, text[:FUZZY_TEXT_LIMIT])
                best = max(best, score * weight)
        if term in (agent.model or "").lower():
            best = max(best, W_MODEL)
        if term in (agent.prompt or "")[:2000].lower():
            best = max(best, W_PROMPT)
        return best

    def name_offsets(self, agent: Agent) -> List[int]:
        """Positions of the matched letters in the agent name (to highlight them)."""
        found = set()
        for term in self.terms:
            score, offsets = self._fuzzy.match(term, agent.name[:FUZZY_TEXT_LIMIT])
            if score > 0:
                found.update(offsets)
        return sorted(found)
