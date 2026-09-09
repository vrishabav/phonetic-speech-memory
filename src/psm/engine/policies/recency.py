from __future__ import annotations

from psm.domain.enums import LexemeState, ReasonCode
from psm.domain.models import Candidate

from .base import neutral, oppose, veto


class RecencyPolicy:
    """Decay, and the conditions under which a faded memory may still act.

    A name the user has not said in eight months should not vanish - people
    come back - but it should stop volunteering itself. A dormant lexeme is
    therefore allowed to apply on an exact form we have actually observed, and
    nothing weaker.
    """

    name = "recency"
    order = 10

    def evaluate(self, candidate: Candidate, ctx) -> object:
        lexeme = candidate.lexeme
        if lexeme.state is not LexemeState.DORMANT:
            return neutral(self.name)

        if candidate.matched_via == "observed_variant":
            return oppose(
                self.name,
                0.05,
                f"{lexeme.canonical!r} is dormant, but this is a form the recogniser "
                f"has actually produced for it before",
            )
        return veto(
            self.name,
            ReasonCode.DORMANT_WITHOUT_SUPPORT,
            f"{lexeme.canonical!r} is dormant and {candidate.span.text!r} is only a "
            f"{candidate.matched_via.replace('_', ' ')} - not enough to wake it",
        )
