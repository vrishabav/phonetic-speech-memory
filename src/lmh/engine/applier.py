"""Write the decisions into the text.

Deterministic splice: right-to-left so offsets stay valid, longest span first
so a multi-token entity is never half-replaced, and casing carried from the
source unless the lexeme's own standing instruction says otherwise.

This is the fast path. Anything it cannot express - an instruction that expands
or rewrites rather than substitutes - is handed to the model, and the verifier
then checks that the model changed only what it was asked to.
"""

from __future__ import annotations

from collections.abc import Sequence

from lmh.domain.enums import Verdict
from lmh.domain.models import Resolution, Span
from lmh.engine.text import match_case, overlaps, splice

#: Instruction wording that means "the canonical casing is not negotiable".
_CASE_LOCKED = ("lowercase", "capitalis", "capitaliz", "upper", "hyphenated")


def apply_resolutions(formatted: str, resolutions: Sequence[Resolution]) -> str:
    chosen: list[tuple[Span, str]] = []
    taken: list[Span] = []

    # Longest spans first: "Shreya Bhattacharya" must win over "Shreya".
    ordered = sorted(
        (r for r in resolutions if r.verdict is Verdict.APPLY and r.replacement),
        key=lambda r: (len(r.candidate.span), r.score),
        reverse=True,
    )
    for resolution in ordered:
        span = resolution.candidate.span
        if any(overlaps(span, other) for other in taken):
            continue
        instruction = resolution.candidate.lexeme.instruction or ""
        locked = any(word in instruction.casefold() for word in _CASE_LOCKED)
        chosen.append((span, match_case(span.text, resolution.replacement, force=locked)))
        taken.append(span)

    return splice(formatted, chosen)
