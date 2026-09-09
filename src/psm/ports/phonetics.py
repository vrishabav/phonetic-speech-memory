"""Phonetic encoding and comparison.

Two ports, not one, because they are upgraded independently: an encoder produces
keys for the index (a blocking function), a comparator produces a distance
(a scoring function). Today both are grapheme-based. Either can be replaced by
an IPA / articulatory-feature / learned-embedding implementation without the
engine noticing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class PhoneticEncoder(Protocol):
    name: str

    def encode(self, text: str) -> tuple[str, ...]:
        """Zero or more index keys for `text`.

        Multiple keys are allowed and expected: double metaphone returns a
        primary and an alternate, and a multi-word phrase may key on each token
        as well as the whole.
        """
        ...


@runtime_checkable
class PhoneticComparator(Protocol):
    name: str

    def distance(self, a: str, b: str) -> float:
        """Phonetic distance in [0.0, 1.0]. 0.0 = indistinguishable.

        Must be symmetric and must return 0.0 for identical input.
        """
        ...

    def similarity(self, a: str, b: str) -> float:
        """Convenience: 1.0 - distance."""
        ...


@runtime_checkable
class PhoneticStack(Protocol):
    """A weighted combination of encoders and comparators, selected by config.

    Exists so that an ablation ("no phonetics") is a config value rather than a
    branch inside the retriever.
    """

    encoders: Sequence[PhoneticEncoder]
    comparators: Sequence[PhoneticComparator]

    def keys(self, text: str) -> tuple[str, ...]: ...
    def distance(self, a: str, b: str) -> float: ...
