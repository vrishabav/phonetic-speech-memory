from __future__ import annotations

from lmh.domain.enums import LexemeState, ReasonCode
from lmh.domain.models import Candidate
from lmh.engine.text import overlaps

from .base import neutral, veto


class ConflictPolicy:
    """Two memories, one sound, no way to tell them apart.

    The correct behaviour is to abstain and say so. Picking the
    higher-confidence one would be a silent coin-flip, and a coin-flip that
    puts the wrong colleague's name in a message is the single worst thing this
    system can do. Abstention is only lifted when something else - scope, or a
    longer exact span - has already separated them.
    """

    name = "conflict"
    order = 9

    def evaluate(self, candidate: Candidate, ctx) -> object:
        conflicting = {
            b for a, b, rel, _ in ctx.edges if rel == "conflicts" and a == candidate.lexeme.id
        } | {
            a for a, b, rel, _ in ctx.edges if rel == "conflicts" and b == candidate.lexeme.id
        }
        if not conflicting:
            return neutral(self.name)

        rivals = [
            sibling
            for sibling in ctx.siblings
            if sibling.lexeme.id in conflicting
            and sibling.lexeme.state is not LexemeState.RETIRED
            and overlaps(sibling.span, candidate.span)
        ]
        if not rivals:
            return neutral(self.name, "conflicting memory exists but does not match here")

        # A strictly longer exact match has already disambiguated: "Shreya
        # Bhattacharya" is not ambiguous just because "Shreya" would be.
        decisive = [
            r
            for r in rivals
            if len(r.span) > len(candidate.span) or r.retrieval_score > candidate.retrieval_score
        ]
        if not decisive and all(
            len(candidate.span) > len(r.span) for r in rivals
        ):
            return neutral(self.name, "longer exact span wins over the conflicting memory")

        # Both halves of that same fact deserve saying. When a longer overlapping
        # span won, this span did not fail because the system could not tell the
        # two names apart - it failed because a better reading of the same words
        # already decided, and saying "nothing here decides between them" while
        # the very next token decides it is an explanation that is simply untrue.
        longer = [r for r in decisive if len(r.span) > len(candidate.span)]
        if longer:
            best = max(longer, key=lambda r: (len(r.span), r.retrieval_score))
            return veto(
                self.name,
                ReasonCode.SUPERSEDED_BY_LONGER_SPAN,
                f"the longer span {best.span.text!r} already matched "
                f"{best.lexeme.canonical!r}; this shorter reading is dropped rather "
                f"than weighed",
            )

        names = ", ".join(sorted({r.lexeme.canonical for r in rivals}))
        return veto(
            self.name,
            ReasonCode.AMBIGUOUS_CONFLICT,
            f"{candidate.span.text!r} could be {candidate.lexeme.canonical!r} or {names}; "
            f"nothing here decides between them, so nothing is changed",
        )
