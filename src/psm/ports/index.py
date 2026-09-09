"""Candidate retrieval.

Deliberately separate from the store: retrieval quality (did we find the right
lexeme at all?) is measured independently from decision quality (did we do the
right thing with it?). Recall@k against the fixtures is its own metric.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from psm.domain.models import Binding, Candidate, Lexeme, Utterance


@runtime_checkable
class CandidateIndex(Protocol):
    def rebuild(self, lexemes: Sequence[Lexeme]) -> None:
        """Drop and repopulate. The index is a cache; it is never authoritative."""
        ...

    def upsert(self, lexeme: Lexeme) -> None: ...

    def remove(self, lexeme_id: str) -> None: ...

    def probe(self, text: str) -> bool:
        """Cheapest possible question: could anything in memory match this text?

        Answering `False` here is the gate. It must be fast and it must never
        produce a false negative for an exact observed variant.
        """
        ...

    def search(
        self,
        utterance: Utterance,
        *,
        binding: Binding,
        limit: int = 8,
    ) -> Sequence[Candidate]:
        """Candidates over spans of `utterance.asr_text`, best first."""
        ...
