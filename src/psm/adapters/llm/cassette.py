"""Record once against the live API, replay for ever after.

The problem this solves: an evaluation that needs an API key is an evaluation
the reviewer cannot run, and one whose numbers cannot be reproduced next month
when the model behind that key has been retrained.

A cassette is a JSON file per request, named by a SHA-256 of everything that
could change the answer - system prompt, user prompt, schema, temperature,
model. Replay is therefore exact, and a changed prompt produces a *cache miss*
rather than a stale answer, which is the property that matters: it is not
possible to edit a prompt and keep the old recording by accident.

    PSM_LLM=llm.sarvam make eval-live     # records
    make eval                             # replays, offline

`strict=True` (the default for replay) raises on a miss rather than reaching for
the network, so a committed evaluation can never silently become a live one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psm.ports.llm import LLMResponse


class CassetteMiss(KeyError):
    """No recording for this request, and no live model to fall through to."""


def fingerprint(
    *,
    system: str,
    user: str,
    schema: Mapping[str, Any] | None,
    temperature: float,
    model: str,
) -> str:
    blob = json.dumps(
        {
            "system": system,
            "user": user,
            "schema": schema,
            "temperature": temperature,
            "model": model,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class CassetteModel:
    name = "cassette"

    def __init__(
        self,
        *,
        directory: str = "evals/cassettes",
        inner: Any = None,
        strict: bool = True,
        **_: Any,
    ) -> None:
        self.directory = Path(directory)
        self.inner = inner
        self.strict = strict and inner is None
        self.calls = 0
        self.hits = 0
        self.recorded = 0

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
        model = getattr(self.inner, "model", "") or getattr(self.inner, "name", "offline")
        key = fingerprint(
            system=system, user=user, schema=schema, temperature=temperature, model=model
        )
        path = self.directory / f"{key}.json"

        if path.exists():
            self.hits += 1
            payload = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse(
                text=payload["text"],
                parsed=payload.get("parsed"),
                prompt_tokens=payload.get("prompt_tokens", 0),
                completion_tokens=payload.get("completion_tokens", 0),
                latency_ms=0.0,          # replay is free; reporting otherwise would lie
                model=payload.get("model", model),
                from_cache=True,
            )

        if self.inner is None:
            raise CassetteMiss(
                f"no recording for this request ({key}). Record it with "
                f"`make eval-live`, or run the offline evaluation with `make eval`."
            )

        response = self.inner.complete(
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        # The prompts are stored alongside the answer purely so a reviewer can
        # read a cassette and see what was asked. Nothing reads them back.
        path.write_text(
            json.dumps(
                {
                    "_system": system,
                    "_user": user,
                    "text": response.text,
                    "parsed": response.parsed,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "model": response.model,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.recorded += 1
        return response
