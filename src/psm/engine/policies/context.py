from __future__ import annotations

from psm.domain.enums import BindingScope, GuardKind, LexemeKind, ReasonCode
from psm.domain.models import Candidate, Guard
from psm.engine.guards import DEFAULT_SUPPORT, is_common
from psm.engine.text import window_tokens

from .base import neutral, support, veto

#: Kinds whose binding is part of what the term *is*, rather than a record of
#: where it was last seen. A channel handle and a service identifier name
#: something that exists inside one application; writing `#eng-asr` into an
#: email is not a spelling that needs fixing, it is a reference to a thing that
#: is not there. Every other kind names something that exists independently of
#: the window it is typed into - a person keeps the same name in Slack, in Mail
#: and on paper.
APP_NATIVE_KINDS = frozenset({LexemeKind.HANDLE, LexemeKind.CODE_SYMBOL})


class ScopeFitPolicy:
    """Where a memory was learned, and where it is allowed to apply.

    These are two different questions, and the first version of this policy
    answered both with one veto. A binding is created from the application the
    user happened to be typing in when the evidence arrived; treating that as
    "this term exists only here" is reading a licence into an accident, and it
    produced the worst class of failure this system has: a name the memory
    holds an exact observed variant for, left uncorrected because the user
    switched windows.

    So the veto is now reserved for terms whose binding is intrinsic
    (`APP_NATIVE_KINDS`). For everything else, a matching scope *adds*
    confidence and a mismatching one merely withholds it.

    Nothing is lost by this. The work an out-of-scope veto was really doing -
    keeping two people with the same-sounding name apart - belongs to the
    conflict policy, which does it better because it does it whichever
    application you are in. Scope is a tiebreaker; it was being used as a gate.
    """

    name = "scope_fit"
    order = 4

    def evaluate(self, candidate: Candidate, ctx) -> object:
        bindings = candidate.lexeme.bindings or ()
        if not bindings:
            return neutral(self.name)
        if any(b.covers(ctx.binding) for b in bindings):
            specific = [b for b in bindings if b.scope is not BindingScope.GLOBAL]
            if specific and any(b.covers(ctx.binding) for b in specific):
                # Deliberately no reason code: fitting the scope is a
                # precondition for acting, not a reason to act. Letting it claim
                # CONTEXT_SUPPORTED would mask the real cause of every decision
                # about an app-bound lexeme.
                return support(
                    self.name,
                    0.18,
                    f"{candidate.lexeme.canonical!r} is bound to this context "
                    f"({ctx.binding.key()})",
                )
            return neutral(self.name, "global memory, applies everywhere")

        where = ", ".join(b.key() for b in bindings)
        if candidate.lexeme.kind in APP_NATIVE_KINDS:
            return veto(
                self.name,
                ReasonCode.OUT_OF_SCOPE,
                f"{candidate.lexeme.canonical!r} names something that exists only in "
                f"{where}; in {ctx.binding.key()} it is not a spelling to fix",
            )
        return neutral(
            self.name,
            f"only ever seen in {where}, but a {candidate.lexeme.kind} keeps its "
            f"spelling across applications, so this is not a reason to stop - "
            f"it only forgoes the in-scope bonus",
        )


class CommonWordGuardPolicy:
    """The hardest problem in the system, in one policy.

    Some remembered terms are also ordinary words. "Kivi" is a product; "kiwi"
    is a fruit. A memory that fires on every occurrence of the surface form is
    worse than no memory, so a guarded form has to *earn* its correction:

      * a veto token nearby (fruit, smoothie, desk) blocks it outright;
      * otherwise it needs at least one positive signal - a support token, a
        co-occurring known term, or the canonical form already present
        elsewhere in the same utterance;
      * with neither, the default is to leave the text alone.

    Both lists are windowed around the span rather than scanned across the
    whole utterance. MX-001 is the case that forces this: one occurrence of
    "kiwi" must be corrected and another, six tokens later, must not.
    """

    name = "common_word_guard"
    order = 7

    def evaluate(self, candidate: Candidate, ctx) -> object:
        lexeme = candidate.lexeme
        text = ctx.utterance.formatted_text
        window = window_tokens(text, candidate.span, radius=4)
        matched_norm = candidate.span.text.casefold()

        lexical = [g for g in lexeme.guards if g.kind is GuardKind.LEXICAL_CONTEXT]
        common = [g for g in lexeme.guards if g.kind is GuardKind.COMMON_WORD]

        for guard in lexical:
            applies_to = guard.payload.get("applies_to_forms")
            if applies_to and matched_norm not in {f.casefold() for f in applies_to}:
                continue
            hits = window & {t.casefold() for t in guard.payload.get("veto_tokens", [])}
            if hits:
                return veto(
                    self.name,
                    ReasonCode.GUARD_CONDITION_MET,
                    f"{', '.join(sorted(hits))} near {candidate.span.text!r} - "
                    f"this is the ordinary sense, not {lexeme.canonical!r}",
                )

        # A term is guarded if a guard was written or synthesised for this
        # exact form, OR - and this is the part that makes it general - if the
        # matched text is simply an ordinary English word.
        #
        # The second condition is not redundant. A pre-registered guard only
        # protects forms already in the variant table, but the dangerous
        # matches arrive through *phonetics*, on forms nobody registered: a
        # memory for the acronym WER matched the word "were" 20 times across
        # 4,000 sentences of ordinary prose, and no registered form would have
        # caught it because "were" was never stored anywhere.
        registered = matched_norm in {
            str(g.payload.get("form", "")).casefold() for g in common
        }
        ordinary = is_common(matched_norm)
        if not (registered or ordinary):
            return neutral(self.name)
        if not common:
            common = [
                Guard(
                    kind=GuardKind.COMMON_WORD,
                    payload={"form": matched_norm, "support_tokens": list(DEFAULT_SUPPORT)},
                )
            ]

        # A common English word that this recogniser has NEVER actually produced
        # for this term cannot be corrected, whatever the context looks like.
        #
        # This is the rule that closes the last of the false positives. The
        # residual failures were "Start a socket server" -> Siddharth and
        # "sent by the server" -> Sandhya: real names that a generic support
        # word ("server") was rescuing. The asymmetry is the point - "kiwi" is
        # a form the recogniser has genuinely emitted for Kivi six times, so
        # there is evidence it happens; "start" has never once been emitted for
        # Siddharth, so there is no evidence at all, only a sound.
        observed = {v.form.casefold() for v in lexeme.observed_forms_with(matched_norm)}
        if matched_norm not in observed:
            return veto(
                self.name,
                ReasonCode.COMMON_WORD_GUARD,
                f"{candidate.span.text!r} is an ordinary English word and the recogniser "
                f"has never produced it for {lexeme.canonical!r} - a sound-alike is not "
                f"evidence",
            )

        signals: list[str] = []
        for guard in common:
            hits = window & {t.casefold() for t in guard.payload.get("support_tokens", [])}
            if hits:
                signals.append(f"{', '.join(sorted(hits))} nearby")
        if _canonical_present(candidate, text):
            signals.append(f"{lexeme.canonical!r} already appears in this utterance")
        if _cooccurring(candidate, ctx):
            signals.append("a term it is usually seen with is present")

        if not signals:
            return veto(
                self.name,
                ReasonCode.COMMON_WORD_GUARD,
                f"{candidate.span.text!r} is also an ordinary English word and nothing "
                f"in this sentence suggests {lexeme.canonical!r}"
                + ("" if registered else " (guard applied automatically)"),
            )
        return support(
            self.name,
            0.30,
            f"guarded term rescued by context: {'; '.join(signals)}",
            ReasonCode.CONTEXT_SUPPORTED,
        )


class CooccurrencePolicy:
    """Terms learned together tend to appear together.

    A single join over the edge table, and it resolves the hardest negative
    case in the taxonomy: "Sarvam" in the sentence makes "kiwi -> Kivi" likely,
    while "breakfast" makes it absurd. Cheap, inspectable, and the ablation row
    it produces is one of the more interesting numbers in the report.
    """

    name = "cooccurrence"
    order = 8

    def evaluate(self, candidate: Candidate, ctx) -> object:
        partners = _cooccurring(candidate, ctx)
        if not partners:
            return neutral(self.name)
        names = ", ".join(sorted(p.canonical for p in partners))
        return support(
            self.name,
            min(0.45, 0.25 * len(partners)),
            f"{candidate.lexeme.canonical!r} usually appears alongside {names}, "
            f"and {'they are' if len(partners) > 1 else 'it is'} present here",
            ReasonCode.CONTEXT_SUPPORTED,
        )


def _canonical_present(candidate: Candidate, text: str) -> bool:
    canonical = candidate.lexeme.canonical
    for start in _find_all(text, canonical):
        if not (start == candidate.span.start):
            return True
    return False


def _find_all(haystack: str, needle: str):
    start = haystack.find(needle)
    while start != -1:
        yield start
        start = haystack.find(needle, start + 1)


def _cooccurring(candidate: Candidate, ctx) -> list:
    """Sibling candidates linked to this one by a `cooccurs` edge."""
    partner_ids = {
        b for a, b, rel, _ in ctx.edges if rel == "cooccurs" and a == candidate.lexeme.id
    } | {a for a, b, rel, _ in ctx.edges if rel == "cooccurs" and b == candidate.lexeme.id}
    seen: dict[str, object] = {}
    for sibling in ctx.siblings:
        if sibling.lexeme.id in partner_ids and sibling.lexeme.id != candidate.lexeme.id:
            seen[sibling.lexeme.id] = sibling.lexeme
    return list(seen.values())
