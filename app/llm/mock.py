"""Deterministic, offline mock provider.

It does NOT understand the notes. It builds a reply from the passage with string operations, so
the real parsing, validation and grounding code runs without a key or a network connection.

Modes:
- `good`          cards whose quotes are copied verbatim from the passage
- `fake_quotes`   cards whose quotes are invented or altered, so the grounding check must reject them
- `mixed`         good and fake cards alternating
- `invalid_json`  a chatty reply that is not JSON

Test hooks (constructor arguments):
- `responses`: raw texts returned in order before the mode's own behaviour takes over
- `fail_with`: exception raised on every call, or on the first `fail_times` calls
- `calls`: every request received, for assertions
"""

import json
import time
from collections import deque
from typing import Literal

from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.text import collapse_ws, sentence_spans, strip_bullet, strip_markers

MockMode = Literal["good", "fake_quotes", "mixed", "invalid_json"]

INVENTED_QUOTE = "The mock provider invented this sentence, so it is not in the notes."
NOT_JSON_REPLY = "Sure! Here are some flashcards for you:\n1. Q: What is this? A: Not JSON."


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, mode: MockMode = "good", model: str = "mock-model",
                 responses: list[str] | None = None, fail_with: Exception | None = None,
                 fail_times: int | None = None):
        self.mode = mode
        self.model = model
        self._responses = deque(responses or [])
        self._fail_with = fail_with
        self._fail_times = fail_times
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        self.calls.append(request)
        if self._fail_with is not None and (self._fail_times is None or self._fail_times > 0):
            if self._fail_times is not None:
                self._fail_times -= 1
            raise self._fail_with
        text = self._responses.popleft() if self._responses else self._reply(request)
        return LLMResponse(text=text, model=self.model, provider=self.name,
                           latency_ms=round((time.perf_counter() - started) * 1000, 1))

    def _reply(self, request: LLMRequest) -> str:
        if self.mode == "invalid_json":
            return NOT_JSON_REPLY
        passage = str(request.metadata.get("passage", ""))
        limit = int(request.metadata.get("max_cards", 3))
        cards = []
        for start, end in sentence_spans(passage):
            raw = passage[start:end]
            clean = collapse_ws(strip_bullet(strip_markers(raw)))
            if len(clean.split()) < 6 or len(clean) > 280:
                continue
            index = len(cards)
            fake = self.mode == "fake_quotes" or (self.mode == "mixed" and index % 2 == 1)
            cards.append({
                "question": f'Mock question: what do the notes say about "{" ".join(clean.split()[:4])} ..."?',
                "answer": clean,
                "quote": self._fake_quote(raw, index) if fake else raw,
            })
            if len(cards) >= limit:
                break
        return json.dumps({"cards": cards})

    @staticmethod
    def _fake_quote(sentence: str, index: int) -> str:
        """Alternate between an invented sentence and a real one with its last word changed."""
        if index % 2 == 0:
            return INVENTED_QUOTE
        return sentence.rstrip(".").rsplit(" ", 1)[0] + " definitely."
