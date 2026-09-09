from __future__ import annotations

from lmh.adapters.phonetics.indic_script import is_indic
from lmh.domain.enums import ReasonCode
from lmh.domain.models import Candidate

from .base import neutral, veto


class ScriptFitPolicy:
    """Never change the script the user is writing in.

    Cross-script *retrieval* is deliberate and valuable: one memory for one
    person should be findable whether the recogniser emitted `आदित्य नारायणन`
    or `Aadith Narayanan`, so the user does not end up with two half-learned
    entries for one colleague.

    Cross-script *rewriting* is the opposite of valuable. Someone dictating a
    Hindi sentence in Devanagari does not want a Latin name spliced into the
    middle of it:

        आदित्य नारायणन को PR भेज दो।
        Aadith Narayanan को PR भेज दो।     <- never do this

    The memory knows how the user spells the name. It does not know they wanted
    a different alphabet, and nothing in the evidence could tell it so.

    So the rule is narrow: a candidate may only be replaced by a form written in
    the same script it was found in. When a lexeme has no form in that script
    yet, the honest answer is to leave the text alone - and the learner will
    pick up the correct spelling the first time the user types it.
    """

    name = "script_fit"
    order = 3

    def evaluate(self, candidate: Candidate, ctx) -> object:
        span_indic = is_indic(candidate.span.text)
        canonical_indic = is_indic(candidate.lexeme.canonical)
        if span_indic == canonical_indic:
            return neutral(self.name)
        return veto(
            self.name,
            ReasonCode.SCRIPT_MISMATCH,
            f"{candidate.span.text!r} is written in a different script from "
            f"{candidate.lexeme.canonical!r}; correcting spelling is this system's "
            f"job, changing alphabet is not",
        )
