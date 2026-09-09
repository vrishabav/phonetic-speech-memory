from __future__ import annotations

from psm.domain.enums import GuardKind, LexemeState, ReasonCode
from psm.domain.models import Candidate
from psm.engine.text import in_protected_region

from .base import neutral, veto


class SuppressionPolicy:
    """The user has already told us no. Nothing downstream gets a vote.

    Runs first because it is the cheapest possible decision and because a
    system that keeps re-applying a correction the user undid is worse than one
    with no memory at all.
    """

    name = "suppression"
    order = 0

    def evaluate(self, candidate: Candidate, ctx) -> object:
        lexeme = candidate.lexeme
        if lexeme.state is LexemeState.SUPPRESSED:
            return veto(
                self.name,
                ReasonCode.SUPPRESSED,
                f"{lexeme.canonical!r} is suppressed; the user reverted this correction before",
            )
        for guard in lexeme.guards:
            if guard.kind is GuardKind.USER_SUPPRESSION:
                reverts = guard.payload.get("reverts", "?")
                return veto(
                    self.name,
                    ReasonCode.SUPPRESSED,
                    f"user suppression guard on {lexeme.canonical!r} ({reverts} reverts)",
                )
        return neutral(self.name)


class VerbatimPolicy:
    """Quoted text and code are somebody else's words.

    Applying a personal spelling preference inside a quotation silently
    falsifies a citation, and renaming an identifier inside a code fence breaks
    the user's code. Both are worse than the original error.
    """

    name = "verbatim"
    order = 1

    def evaluate(self, candidate: Candidate, ctx) -> object:
        text = ctx.utterance.formatted_text
        if in_protected_region(candidate.span, text):
            return veto(
                self.name,
                ReasonCode.VERBATIM_REGION,
                f"{candidate.span.text!r} sits inside quoted or fenced text",
            )
        return neutral(self.name)
