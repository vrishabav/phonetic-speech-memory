"""A deterministic stand-in for a language model.

Not a mock in the testing sense - it is the default provider, so `make eval`
runs the whole suite with no API key and no network. It answers the only two
questions the engine ever asks a model, and it answers them from the same
structured inputs the real adapter gets, so swapping providers changes cost and
quality but never the shape of the result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from lmh.ports.llm import LLMResponse


class StubModel:
    name = "stub"

    def __init__(self, **_: Any) -> None:
        self.calls = 0

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        stop: Sequence[str] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        # Abstain by default. A stub that guessed would make the offline
        # evaluation look better than the system is, which is the one thing an
        # evaluation must never do.
        payload = {"decisions": [], "note": "stub provider: no adjudication performed"}
        return LLMResponse(
            text=json.dumps(payload),
            parsed=payload,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0.0,
            cost_paise=0.0,
            model=self.name,
            from_cache=True,
        )
