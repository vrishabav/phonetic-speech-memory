"""The frozen formatter. Costs nothing, changes nothing, never varies.

This is the default, and it is the one the committed evaluation results were
produced with. The fixtures already carry a `formatted` field - a plausible
output of a formatting model - so replaying them through a real model would
measure the model, not the memory.

It is not a stub in the testing sense. It is a deliberate experimental control:
holding the formatter constant is what makes "no-guards costs 16 cases" a
statement about the guard policy rather than about the weather.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psm.domain.models import Lexeme, Utterance


class PassthroughFormatter:
    name = "passthrough"

    def __init__(self, **_: Any) -> None:
        self.calls = 0

    def format(
        self,
        utterance: Utterance,
        *,
        lexemes: Sequence[Lexeme] = (),
        instructions: Sequence[str] = (),
    ) -> str:
        self.calls += 1
        # `lexemes` and `instructions` are accepted and ignored on purpose: the
        # signature is the port's, and a caller must not have to know which
        # formatter is installed.
        return utterance.formatted_text or utterance.asr_text
