"""Sarvam chat completions, over the OpenAI-compatible endpoint.

Deliberately written against `urllib` rather than an SDK. The port is four
lines wide and the request is one JSON object; adding a dependency to send it
would buy nothing and would make `make install` fail on a Python version the
SDK had not caught up with yet - which is a failure mode this project has
already hit once, with rapidfuzz on 3.14.

The key is read from the environment, which `lmh.config.load_dotenv_once`
populates from `.env`. It is never logged, never written to a cassette and
never included in an eval result.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from lmh.config import load_dotenv_once
from lmh.ports.llm import LLMResponse


class SarvamCredentialsMissing(RuntimeError):
    """Raised instead of silently degrading to a stub.

    A live run that quietly fell back to the offline provider would report
    "0 model calls" and look like a triumph of efficiency.
    """


class SarvamModel:
    name = "sarvam"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.sarvam.ai/v1",
        model: str = "sarvam-105b",
        timeout: float = 30.0,
        **_: Any,
    ) -> None:
        load_dotenv_once()
        self.api_key = api_key or os.environ.get("SARVAM_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.calls = 0
        if not self.api_key:
            raise SarvamCredentialsMissing(
                "SARVAM_API_KEY is not set. Put it in .env (see .env.example), or "
                "run the offline evaluation with `make eval`, which needs no key."
            )

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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = list(stop)
        if schema is not None:
            # Structured output is a correctness control, not a convenience: the
            # adjudicator may only ever *choose among* candidates it supplied,
            # and a free-text reply could invent a replacement that no memory
            # ever justified.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "decision", "strict": True, "schema": dict(schema)},
            }

        request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as handle:  # noqa: S310
                body = json.loads(handle.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"Sarvam returned {exc.code}: {detail}") from exc
        latency = (time.perf_counter() - started) * 1000.0
        self.calls += 1

        text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        parsed = None
        if schema is not None:
            parsed = json.loads(text)
        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            parsed=parsed,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency,
            model=body.get("model") or self.model,
            from_cache=False,
        )
