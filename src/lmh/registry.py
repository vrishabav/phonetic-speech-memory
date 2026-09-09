"""Component resolution by dotted path.

    resolve("lmh.adapters.clock.system:SystemClock")

A component swap is therefore a config value, not an import edit. This is the
mechanism that makes ablations declarative: the eval harness constructs an
Engine from a `Settings` object with one field changed.
"""

from __future__ import annotations

import importlib
from typing import Any, TypeVar

T = TypeVar("T")

_ALIASES: dict[str, str] = {
    # short name -> dotted path. Keeps config files readable.
    "clock.system": "lmh.adapters.clock.system:SystemClock",
    "clock.frozen": "lmh.adapters.clock.frozen:FrozenClock",
    "phonetics.dmetaphone": "lmh.adapters.phonetics.dmetaphone:DoubleMetaphoneEncoder",
    "phonetics.null": "lmh.adapters.phonetics.dmetaphone:NullEncoder",
    "llm.stub": "lmh.adapters.llm.stub:StubModel",
    "llm.sarvam": "lmh.adapters.llm.sarvam:SarvamModel",
    "llm.cassette": "lmh.adapters.llm.cassette:CassetteModel",
    "store.sqlite": "lmh.adapters.store.sqlite:SqliteStore",
    "store.memory": "lmh.adapters.store.memory:InMemoryStore",
    "index.inmemory": "lmh.adapters.index.inmemory:InMemoryIndex",
    "formatter.passthrough": "lmh.adapters.formatter.passthrough:PassthroughFormatter",
    "formatter.llm": "lmh.adapters.formatter.llm_formatter:LLMFormatter",
}


def register_alias(alias: str, dotted: str) -> None:
    _ALIASES[alias] = dotted


def resolve(spec: str) -> Any:
    """Return the object named by `spec`, which may be an alias or a dotted path."""
    dotted = _ALIASES.get(spec, spec)
    if ":" not in dotted:
        raise ValueError(
            f"component spec {spec!r} must be 'module.path:Name' or a known alias "
            f"(known: {', '.join(sorted(_ALIASES))})"
        )
    module_name, _, attr = dotted.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as exc:  # pragma: no cover - config error path
        raise ValueError(f"{module_name!r} has no attribute {attr!r}") from exc


def build(spec: str, /, **kwargs: Any) -> Any:
    """Resolve and instantiate."""
    return resolve(spec)(**kwargs)
