"""Persistence.

Three ports because they have three different access patterns and three
different lifetimes: the observation log is append-only and authoritative, the
memory store is a rebuildable projection, the adjudication log is write-once
telemetry.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from lmh.domain.models import (
    Adjudication,
    Lexeme,
    MemorySnapshot,
    Observation,
    Tombstone,
)


@runtime_checkable
class ObservationLog(Protocol):
    """Append-only. The single source of truth."""

    def append(self, observation: Observation) -> None: ...

    def all(self, *, until: datetime | None = None) -> Sequence[Observation]:
        """Every observation, oldest first. `until` enables time-travel replay."""
        ...

    def for_lexeme(self, lexeme_id: str) -> Sequence[Observation]: ...

    def truncate(self) -> None:
        """Full reset. This is the only state that has to be cleared."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """The projection. Always rebuildable from the observation log."""

    def put(self, lexemes: Iterable[Lexeme]) -> None: ...

    def get(self, lexeme_id: str) -> Lexeme | None: ...

    def all(self) -> Sequence[Lexeme]: ...

    def tombstones(self) -> Sequence[Tombstone]: ...

    def put_tombstones(self, tombstones: Iterable[Tombstone]) -> None: ...

    def snapshot(self) -> MemorySnapshot: ...

    def clear(self) -> None: ...


@runtime_checkable
class AdjudicationLog(Protocol):
    """One row per call, including calls where nothing happened."""

    def record(self, adjudication: Adjudication) -> str:
        """Returns the adjudication id."""
        ...

    def get(self, adjudication_id: str) -> Adjudication | None: ...

    def recent(self, limit: int = 50) -> Sequence[Adjudication]: ...

    def clear(self) -> None: ...
