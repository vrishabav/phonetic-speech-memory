"""Language model access.

One narrow port. The engine never sees a provider SDK, a base URL or a model
name. Three adapters implement it: `stub` (deterministic, no network, and the
default - which is why the whole evaluation runs offline), `sarvam` (live, over
the OpenAI-compatible endpoint) and `cassette` (replays recorded live responses
by request hash, so a live run can be made reproducible afterwards).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    parsed: Any = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_paise: float = 0.0
    model: str = ""
    from_cache: bool = False


@runtime_checkable
class LanguageModel(Protocol):
    name: str

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
        """A single completion.

        When `schema` is given the adapter must enforce structured output and
        must raise if the response does not validate. The adjudicator relies on
        this: the model may only choose among candidates it was given, never
        invent a replacement.
        """
        ...
