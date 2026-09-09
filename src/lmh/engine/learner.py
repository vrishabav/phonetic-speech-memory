"""Turn raw signals into evidence.

One rule does most of the work here, and it is the reason the memory stays
clean: **a post-dictation edit is only phonetic evidence if the replaced text
is phonetically close to what replaced it.**

    "Adith Kulkarni"  ->  "Aadith Kulkarni"     distance 0.09   -> evidence
    "Ask Aadith to review it"
      -> "Please ask Aadith when he has a moment to review it"  -> discarded

Without that gate every stylistic edit becomes a spurious lexeme and the store
fills with noise inside a day. With it, the learner ignores rewrites entirely
and only ever learns about words.

Everything the learner produces is an `Observation` appended to the log. It
never writes memory state - the projector derives that.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime

from lmh.adapters.phonetics.dmetaphone import PhoneticStack, normalise
from lmh.config import Thresholds
from lmh.domain.enums import (
    GuardKind,
    LexemeKind,
    LexemeState,
    ObservationPolarity,
    ObservationSource,
    TombstoneReason,
    VariantProvenance,
)
from lmh.domain.models import Guard, Lexeme, Observation, Tombstone
from lmh.engine.projector import merge_variant
from lmh.engine.text import changed_segments

#: Sources whose evidence is the user speaking directly about a term. These are
#: trusted at n=1; everything else has to repeat before it is allowed to act.
DIRECT_SOURCES = {ObservationSource.DECLARED, ObservationSource.INSTRUCTION}

#: Words that appear in instructions about terms and are never themselves the
#: term. Deliberately tiny and English-only: this is a convenience parser for
#: spoken instructions, not a claim to understand them, and it fails by leaving
#: the instruction unattached rather than by inventing a lexeme.
_INSTRUCTION_STOPWORDS = frozenset(
    """a abbreviate always an and as at be but by call called capital capitalise
    capitalised capitalize capitalized do dont don't ever expand for from he her
    hers him his i in is it its it's just keep letter letters lowercase me my
    never not of on one only or our out please refer romanise romanize s say she
    shorten spell spelled spelling spelt that the their them they this to
    translate transliterate two three uppercase use used using we with word write
    written you your""".split()
)

#: "…forget…", "…delete…" - an explicit instruction to remove a term.
_FORGET_WORDS = frozenset({"forget", "delete", "remove", "drop"})


class Learner:
    def __init__(self, phonetics: PhoneticStack, thresholds: Thresholds) -> None:
        self.phonetics = phonetics
        self.thresholds = thresholds
        #: Tombstones produced by the last `attribute` call. The learner does
        #: not own storage - the engine drains this into the store - but a
        #: rename and a deletion both have to emit one, and threading it through
        #: the return type would complicate every other caller for two cases.
        self.pending_tombstones: list[Tombstone] = []

    # -- evidence ----------------------------------------------------------- #

    def judge(self, observation: Observation) -> Observation:
        """Score an observation and decide whether it is phonetic evidence.

        Returns the observation with `phonetic_distance` and `accepted` filled
        in. A rejected observation is still appended to the log - the fact that
        we saw an edit and declined to learn from it is itself inspectable.
        """
        if observation.source in DIRECT_SOURCES:
            return replace(observation, accepted=True, phonetic_distance=0.0)
        if observation.polarity is ObservationPolarity.CONTRADICTS:
            return replace(observation, accepted=True, phonetic_distance=0.0)
        if not observation.before:
            # Nothing was replaced; this is a sighting, not a correction.
            return replace(observation, accepted=True, phonetic_distance=None)

        segments = changed_segments(observation.before, observation.after)
        if segments is None:
            return replace(
                observation,
                phonetic_distance=None,
                accepted=False,
                note=(
                    f"rejected: {observation.before!r} -> {observation.after!r} adds or removes "
                    f"words, so it is a rewrite rather than a respelling"
                ),
            )
        if not segments:
            return replace(observation, phonetic_distance=0.0, accepted=True)

        # Score only what changed. Comparing the whole strings lets a long
        # shared prefix disguise a change of meaning as a spelling fix.
        distance = max(self.phonetics.distance(old, new) for old, new in segments)
        accepted = distance <= self.thresholds.learn_max_phonetic_distance
        note = observation.note
        if not accepted:
            worst = max(segments, key=lambda s: self.phonetics.distance(*s))
            note = (
                f"rejected: {worst[0]!r} -> {worst[1]!r} is a different word, not a different "
                f"spelling of the same word (phonetic distance {distance:.2f})"
            )
        return replace(observation, phonetic_distance=distance, accepted=accepted, note=note)

    # -- instructions ------------------------------------------------------- #

    @staticmethod
    def term_from_instruction(text: str) -> str | None:
        """Pull the term out of a spoken instruction about a term.

        "always write it Aadith with two a's"  ->  "Aadith"

        The rules are small and stated rather than learned: a quoted run wins;
        otherwise the longest token that is capitalised, or contains a sigil, or
        is simply not an ordinary instruction word. If nothing survives, the
        answer is None and the caller records the observation without attaching
        it to a lexeme - which is the safe failure, because inventing a lexeme
        named after a sentence is exactly the noise the learner exists to avoid.
        """
        import re

        quoted = re.findall(r"[\"'\u2018\u2019\u201c\u201d]([^\"'\u2018\u2019\u201c\u201d]{2,})", text)
        if quoted:
            return quoted[0].strip() or None

        candidates = []
        for raw in re.findall(r"[\w'\u2019@#\-\u0900-\u0D7F]+", text):
            word = raw.strip("'\u2019")
            if len(word) < 2:
                continue
            if word.casefold() in _INSTRUCTION_STOPWORDS:
                continue
            interesting = (
                word[0].isupper()
                or word[0] in "@#"
                or "-" in word
                or not word.isascii()
            )
            candidates.append((interesting, len(word), word))
        if not candidates:
            return None
        interesting = [c for c in candidates if c[0]]
        pool = interesting or candidates
        return max(pool, key=lambda c: c[1])[2]

    # -- projection --------------------------------------------------------- #

    def attribute(
        self, observation: Observation, lexemes: list[Lexeme]
    ) -> tuple[list[Lexeme], str | None]:
        """Fold an accepted observation into the lexeme set.

        Returns the updated lexemes and the id of the lexeme it landed on, so
        the observation can be linked back to it in the log.
        """
        if observation.accepted is False:
            return lexemes, None

        at = observation.at

        if observation.source is ObservationSource.INSTRUCTION:
            return self._apply_instruction(observation, lexemes)
        if self._is_deletion(observation):
            return self._retire(observation, lexemes)

        target_id = observation.lexeme_id or self._match(observation, lexemes)

        # A declared observation that names an existing lexeme and supplies a
        # different `after` is a rename, not a new variant of the old name.
        if (
            observation.source is ObservationSource.DECLARED
            and observation.lexeme_id
            and observation.after
            and any(
                lx.id == observation.lexeme_id
                and normalise(lx.canonical) != normalise(observation.after)
                for lx in lexemes
            )
        ):
            return self._supersede(observation, lexemes)

        if target_id is None:
            lexeme = Lexeme(
                id=f"lex.{uuid.uuid4().hex[:10]}",
                canonical=observation.after,
                kind=LexemeKind.TERM,
                variants=(),
                bindings=(observation.binding,),
                state=LexemeState.PROPOSED,
                first_seen=at,
                last_used=at,
            )
            if observation.before:
                lexeme = replace(
                    lexeme,
                    variants=merge_variant(
                        (), observation.before, VariantProvenance.OBSERVED, at
                    ),
                )
            return [*lexemes, lexeme], lexeme.id

        out: list[Lexeme] = []
        for lexeme in lexemes:
            if lexeme.id != target_id:
                out.append(lexeme)
                continue
            if observation.polarity is ObservationPolarity.CONTRADICTS:
                out.append(self._penalise(lexeme, observation))
                continue
            if not lexeme.learning_enabled:
                # Application is unaffected; only recording stops. The two are
                # separately controllable, and L13-001 pins that down.
                out.append(replace(lexeme, last_used=at))
                continue
            variants = lexeme.variants
            # Compare exactly, not normalised. A casing-only edit ("Npm" ->
            # "npm") normalises to nothing at all, but it is real evidence
            # about how this user writes the term - it just must not create a
            # second lexeme for the same word, which the attribution above has
            # already prevented.
            if observation.before and observation.before != lexeme.canonical:
                provenance = (
                    VariantProvenance.DECLARED
                    if observation.source in DIRECT_SOURCES
                    else VariantProvenance.OBSERVED
                )
                variants = merge_variant(variants, observation.before, provenance, at)
            out.append(replace(lexeme, variants=variants, last_used=at))
        return out, target_id

    # -- instruction, rename, deletion --------------------------------------- #

    def _apply_instruction(
        self, observation: Observation, lexemes: list[Lexeme]
    ) -> tuple[list[Lexeme], str | None]:
        """A spoken rule about a term.

        This is the class the whole architecture is shaped around (A8 in the
        taxonomy): "always write it Aadith with two a's" is not a substitution,
        it is a rule that travels with the term into the formatting prompt. So
        the instruction text is stored verbatim on the lexeme rather than being
        compiled into a replacement.
        """
        term = self.term_from_instruction(observation.after)
        if not term:
            return lexemes, None
        at = observation.at
        for index, lexeme in enumerate(lexemes):
            if normalise(lexeme.canonical) == normalise(term) or any(
                normalise(v.form) == normalise(term) for v in lexeme.variants
            ):
                updated = replace(
                    lexeme,
                    canonical=term if normalise(lexeme.canonical) == normalise(term) else lexeme.canonical,
                    instruction=observation.after,
                    last_used=at,
                )
                return [*lexemes[:index], updated, *lexemes[index + 1 :]], updated.id
        created = Lexeme(
            id=f"lex.{uuid.uuid4().hex[:10]}",
            canonical=term,
            kind=LexemeKind.TERM,
            instruction=observation.after,
            bindings=(observation.binding,),
            state=LexemeState.PROPOSED,
            first_seen=at,
            last_used=at,
        )
        return [*lexemes, created], created.id

    @staticmethod
    def _is_deletion(observation: Observation) -> bool:
        note = (observation.note or "").casefold()
        return (
            observation.source is ObservationSource.DECLARED
            and not (observation.after or "").strip()
            and any(word in note.split() for word in _FORGET_WORDS)
        )

    def _retire(
        self, observation: Observation, lexemes: list[Lexeme]
    ) -> tuple[list[Lexeme], str | None]:
        """An explicit forget.

        The lexeme is tombstoned rather than dropped. A later sighting of the
        same form must not silently recreate what the user deleted - that reads
        as the product ignoring them - so the tombstone keeps the surface forms
        and the retired lexeme stays in the set, out of play.
        """
        target_id = observation.lexeme_id
        out, retired = [], None
        for lexeme in lexemes:
            if lexeme.id != target_id:
                out.append(lexeme)
                continue
            retired = replace(lexeme, state=LexemeState.RETIRED)
            out.append(retired)
        if retired is None:
            return lexemes, None
        self.pending_tombstones.append(
            Tombstone(
                id=f"tomb.{uuid.uuid4().hex[:10]}",
                reason=TombstoneReason.USER_DELETE,
                canonical=retired.canonical,
                match_forms=retired.all_forms(),
                source_lexeme_id=retired.id,
                created_at=observation.at,
            )
        )
        return out, retired.id

    def _supersede(
        self, observation: Observation, lexemes: list[Lexeme]
    ) -> tuple[list[Lexeme], str | None]:
        """The user renames a canonical form.

        The old spelling is kept as a variant *and* recorded on a tombstone, so
        it still resolves to the renamed lexeme instead of being re-learned from
        zero the next time the recogniser produces it.
        """
        target_id = observation.lexeme_id
        at = observation.at
        out, renamed, old_forms = [], None, ()
        for lexeme in lexemes:
            if lexeme.id != target_id:
                out.append(lexeme)
                continue
            old_forms = lexeme.all_forms()
            renamed = replace(
                lexeme,
                canonical=observation.after,
                variants=merge_variant(
                    lexeme.variants, lexeme.canonical, VariantProvenance.OBSERVED, at
                ),
                last_used=at,
            )
            out.append(renamed)
        if renamed is None:
            return lexemes, None
        self.pending_tombstones.append(
            Tombstone(
                id=f"tomb.{uuid.uuid4().hex[:10]}",
                reason=TombstoneReason.SUPERSESSION,
                canonical=observation.after,
                match_forms=old_forms,
                source_lexeme_id=target_id,
                replacement_lexeme_id=renamed.id,
                created_at=at,
            )
        )
        return out, renamed.id

    def _penalise(self, lexeme: Lexeme, observation: Observation) -> Lexeme:
        """A revert is negative evidence. Two of them in the same scope create a
        suppression guard rather than deleting the lexeme, because the term is
        still real - it is *this context* the user does not want it in."""
        reverts = 1 + sum(
            1 for g in lexeme.guards if g.kind is GuardKind.USER_SUPPRESSION
        ) + int(observation.meta.get("prior_reverts", 0) or 0)
        if reverts >= self.thresholds.reverts_to_suppress:
            guard = Guard(
                kind=GuardKind.USER_SUPPRESSION,
                payload={"reverts": reverts, "scope": observation.binding.key()},
                created_by_observation_id=observation.id,
                note=f"user reverted this correction {reverts} times",
            )
            return replace(
                lexeme,
                guards=(*lexeme.guards, guard),
                state=LexemeState.SUPPRESSED,
            )
        return lexeme

    def _match(self, observation: Observation, lexemes: list[Lexeme]) -> str | None:
        """Which lexeme does this observation belong to?

        Exact canonical or variant first, then phonetic proximity. Falling
        through to None creates a new lexeme, which is the right default:
        wrongly attaching a new name to an existing entry is far more damaging
        than carrying one extra proposed entry.
        """
        after = normalise(observation.after)
        for lexeme in lexemes:
            if normalise(lexeme.canonical) == after:
                return lexeme.id
            if any(normalise(v.form) == after for v in lexeme.variants):
                return lexeme.id
        best, best_distance = None, 1.0
        for lexeme in lexemes:
            distance = self.phonetics.distance(lexeme.canonical, observation.after)
            if distance < best_distance:
                best, best_distance = lexeme.id, distance
        return best if best_distance <= 0.20 else None


def observation(
    source: ObservationSource,
    after: str,
    *,
    at: datetime,
    before: str | None = None,
    binding=None,
    lexeme_id: str | None = None,
    surrounding_text: str | None = None,
    note: str | None = None,
    polarity: ObservationPolarity | None = None,
    meta: dict | None = None,
) -> Observation:
    """Construct an observation with a generated id. Reverts and dismissals are
    automatically negative - the caller does not have to remember."""
    from lmh.domain.models import GLOBAL

    if polarity is None:
        polarity = (
            ObservationPolarity.CONTRADICTS
            if source in {ObservationSource.REVERT, ObservationSource.DISMISSAL}
            else ObservationPolarity.SUPPORTS
        )
    return Observation(
        id=str(uuid.uuid4()),
        source=source,
        at=at,
        after=after,
        before=before,
        polarity=polarity,
        binding=binding or GLOBAL,
        lexeme_id=lexeme_id,
        surrounding_text=surrounding_text,
        note=note,
        meta=meta or {},
    )
