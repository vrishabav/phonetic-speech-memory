from __future__ import annotations

from psm.adapters.phonetics.dmetaphone import normalise
from psm.domain.enums import ReasonCode
from psm.domain.models import Candidate

from .base import neutral, oppose, support, veto

#: How much a match is worth, by where the matched form came from. An ASR
#: actually produced an `observed` form; a `declared` form is the user's word
#: for it; a `generated` form is our own guess and must be rescued by context
#: before it is allowed to do anything.
PROVENANCE_WEIGHT = {
    "observed_variant": 0.62,
    "declared_variant": 0.45,
    "generated_variant": 0.30,
    "canonical": 0.0,
    "phonetic": 0.0,
}


class AlreadyCanonicalPolicy:
    """The formatter already produced the right form.

    Vetoing here is a correctness decision and a cost decision: it keeps this
    call out of the "unnecessary intervention" column and stops it reaching the
    model. B5-001 and B5-002 assert a zero-token budget for exactly this path.
    """

    name = "already_canonical"
    order = 2

    def evaluate(self, candidate: Candidate, ctx) -> object:
        if candidate.span.text == candidate.lexeme.canonical:
            return veto(
                self.name,
                ReasonCode.ALREADY_CANONICAL,
                f"text already reads {candidate.lexeme.canonical!r}",
            )
        # A casing-only difference is NOT already-canonical: it is precisely
        # what a standing instruction about casing exists to fix.
        if normalise(candidate.span.text) == normalise(candidate.lexeme.canonical):
            if candidate.lexeme.instruction:
                return support(
                    self.name,
                    0.55,
                    f"casing differs from canonical {candidate.lexeme.canonical!r}; "
                    f"standing instruction applies",
                    ReasonCode.STANDING_INSTRUCTION,
                )
            return veto(
                self.name,
                ReasonCode.ALREADY_CANONICAL,
                f"only casing differs from {candidate.lexeme.canonical!r} and no "
                f"instruction says which casing the user wants",
            )
        return neutral(self.name)


class ExactVariantPolicy:
    """An exact match against a form we have on file.

    The deterministic fast path. An observed variant is the strongest signal in
    the system because it is the only one grounded in something that actually
    happened rather than in a similarity we computed.
    """

    name = "exact_variant"
    order = 5

    def evaluate(self, candidate: Candidate, ctx) -> object:
        weight = PROVENANCE_WEIGHT.get(candidate.matched_via, 0.0)
        if not weight:
            return neutral(self.name)
        variant = next(
            (v for v in candidate.lexeme.variants if v.form == candidate.matched_form), None
        )
        count = variant.count if variant else 0
        reason = (
            ReasonCode.EXACT_OBSERVED_VARIANT
            if candidate.matched_via == "observed_variant"
            else ReasonCode.DECLARED_BY_USER
        )
        # Repetition adds a little, but with a hard ceiling: a form seen twenty
        # times should not be able to overwhelm a guard on its own.
        bonus = min(0.10, 0.02 * count)
        return support(
            self.name,
            weight + bonus,
            f"{candidate.span.text!r} is a known {candidate.matched_via.replace('_', ' ')} "
            f"of {candidate.lexeme.canonical!r}"
            + (f", seen {count}x" if count else ""),
            reason,
        )


class PhoneticPolicy:
    """Similarity to a known form, for surfaces we have never seen before.

    Deliberately worth less than an exact variant. It exists to catch the first
    occurrence of a new mishearing, not to carry decisions on its own.
    """

    name = "phonetic"
    order = 6

    def evaluate(self, candidate: Candidate, ctx) -> object:
        if candidate.matched_via != "phonetic":
            return neutral(self.name)
        similarity = candidate.retrieval_score
        if similarity < 0.70:
            return oppose(
                self.name,
                0.20,
                f"{candidate.span.text!r} is only {similarity:.2f} similar to "
                f"{candidate.matched_form!r} - too far to act on",
                ReasonCode.BELOW_THRESHOLD,
            )
        return support(
            self.name,
            0.30 + 0.35 * (similarity - 0.70) / 0.30,
            f"{candidate.span.text!r} sounds like {candidate.matched_form!r} "
            f"(similarity {similarity:.2f})",
            ReasonCode.PHONETIC_HIGH_CONFIDENCE,
        )
