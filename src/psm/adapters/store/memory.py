"""In-process store.

Satisfies the same three ports as the SQLite adapter, with no database and no
migration. Used by the evaluation harness and the unit tests, where each case
needs its own isolated memory pinned to its own clock - running 59 cases
against one file-backed database would make them order-dependent, which is the
one thing an evaluation must not be.

It is also the cheapest possible proof that the ports are real: if the engine
can run against this without changing a line, nothing above the adapter layer
knows what SQLite is.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from psm.domain.models import Adjudication, Lexeme, MemorySnapshot, Observation, Tombstone


class InMemoryStore:
    name = "memory"

    def __init__(self, url: str | None = None) -> None:
        self.url = url or "memory://"
        self._observations: list[Observation] = []
        self._lexemes: dict[str, Lexeme] = {}
        self._tombstones: list[Tombstone] = []
        self._edges: list[tuple[str, str, str, float]] = []
        self._adjudications: list[tuple[str, Adjudication]] = []

    # -- observation log ---------------------------------------------------- #

    def append(self, observation: Observation) -> None:
        self._observations.append(observation)

    def all(self, *, until: datetime | None = None) -> list[Observation]:
        rows = sorted(self._observations, key=lambda o: (o.at, o.id))
        return [o for o in rows if until is None or o.at <= until]

    def for_lexeme(self, lexeme_id: str) -> list[Observation]:
        return [o for o in self.all() if o.lexeme_id == lexeme_id]

    def truncate(self) -> None:
        self._observations.clear()

    # -- memory store ------------------------------------------------------- #

    def put(self, lexemes: Iterable[Lexeme]) -> None:
        for lexeme in lexemes:
            self._lexemes[lexeme.id] = lexeme

    def get(self, lexeme_id: str) -> Lexeme | None:
        return self._lexemes.get(lexeme_id)

    def all_lexemes(self) -> list[Lexeme]:
        return list(self._lexemes.values())

    def edges(self) -> list[tuple[str, str, str, float]]:
        return list(self._edges)

    def put_edges(self, edges: Iterable[tuple[str, str, str, float]]) -> None:
        self._edges = list(edges)

    def tombstones(self) -> list[Tombstone]:
        return list(self._tombstones)

    def put_tombstones(self, tombstones: Iterable[Tombstone]) -> None:
        self._tombstones.extend(tombstones)

    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(
            at=datetime.now(UTC),
            lexemes=tuple(self._lexemes.values()),
            tombstones=tuple(self._tombstones),
            observation_count=len(self._observations),
        )

    def clear(self) -> None:
        self._observations.clear()
        self._lexemes.clear()
        self._tombstones.clear()
        self._edges.clear()
        self._adjudications.clear()

    # -- adjudication log --------------------------------------------------- #

    def record(self, adjudication: Adjudication) -> str:
        adjudication_id = str(uuid.uuid4())
        self._adjudications.append((adjudication_id, adjudication))
        return adjudication_id

    def get_adjudication(self, adjudication_id: str) -> Adjudication | None:
        return next((a for i, a in self._adjudications if i == adjudication_id), None)

    def recent(self, limit: int = 50) -> Sequence[Adjudication]:
        return [a for _, a in self._adjudications[-limit:]][::-1]
