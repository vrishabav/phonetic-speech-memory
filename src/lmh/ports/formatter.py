"""The stage that turns raw ASR text into clean prose.

LMH sits downstream of it and conditions it. It is a port so that the memory
system can be evaluated against a frozen formatter - otherwise a change in
formatting quality is indistinguishable from a change in memory quality.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from lmh.domain.models import Lexeme, Utterance


@runtime_checkable
class Formatter(Protocol):
    name: str

    def format(
        self,
        utterance: Utterance,
        *,
        lexemes: Sequence[Lexeme] = (),
        instructions: Sequence[str] = (),
    ) -> str:
        """Produce formatted text, conditioned on the supplied lexemes.

        `lexemes` carry both canonical forms and standing instructions. Passing
        an empty sequence must produce the unconditioned baseline - that is the
        no-memory ablation.
        """
        ...
