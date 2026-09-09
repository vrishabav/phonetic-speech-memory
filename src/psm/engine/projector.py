"""Replay the observation log into memory state.

Memory is never mutated in place. It is *derived*, every time, from the
append-only log. That is what makes four of the brief's requirements fall out
for free instead of needing machinery: per-case memory state (replay to time
t), decision provenance (every field traces to observations), reset (truncate
the log), and a reproducible evaluation (same log + same clock = same memory,
byte for byte).

Confidence is a Beta posterior rather than a count:

    alpha = 1 + sum of decayed weights of supporting observations
    beta  = 1 + sum of decayed weights of contradicting observations
    confidence = alpha / (alpha + beta)

Three things that buys, all of which a counter does not:
  * a revert is ordinary arithmetic, not a special case;
  * decay makes an old memory *uncertain* rather than *wrong*, which is the
    behaviour you actually want for a name unused since April;
  * it is calibratable, so the report can show whether the number means
    anything.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from psm.config import EvidenceWeights, Thresholds
from psm.domain.enums import (
    GuardKind,
    LexemeState,
    ObservationPolarity,
    ObservationSource,
    VariantProvenance,
)
from psm.domain.models import Confidence, Guard, Lexeme, Observation, Variant

SOURCE_WEIGHT_FIELD = {
    ObservationSource.DECLARED: "declared",
    ObservationSource.INSTRUCTION: "instruction",
    ObservationSource.POST_EDIT: "post_edit",
    ObservationSource.REPETITION: "repetition",
    ObservationSource.AMBIENT: "ambient",
    ObservationSource.IMPORT: "imported",
    ObservationSource.REVERT: "revert",
    ObservationSource.DISMISSAL: "dismissal",
}


def decay(age_days: float, half_life_days: float) -> float:
    """Exponential, expressed as a half-life because that is the number a human
    can reason about: 'evidence is worth half as much after three months'."""
    if age_days <= 0:
        return 1.0
    return math.exp(-math.log(2) * age_days / half_life_days)


class Projector:
    def __init__(self, thresholds: Thresholds, weights: EvidenceWeights) -> None:
        self.thresholds = thresholds
        self.weights = weights

    def weight_for(self, observation: Observation) -> float:
        field = SOURCE_WEIGHT_FIELD.get(observation.source)
        return float(getattr(self.weights, field, 1.0)) if field else 1.0

    def decayed_prior(self, prior: Confidence, anchor: datetime | None, now: datetime) -> Confidence:
        """Age the pre-log evidence, the same way logged evidence ages.

        Only the *excess over Beta(1, 1)* decays. The uniform prior is not
        evidence and cannot expire; what expires is the belief built on top of
        it. So an old, well-evidenced memory regresses toward "no opinion"
        rather than toward "wrong", which is the behaviour the design claims and
        for a while did not have: a seeded lexeme's confidence was frozen,
        because its evidence had no date to grow old from.

        `anchor` is the last moment the term was in play (`last_used`, falling
        back to `first_seen`). Without one, nothing decays.
        """
        if anchor is None:
            return prior
        age = (now - anchor).total_seconds() / 86400.0
        factor = decay(age, self.thresholds.decay_half_life_days)
        return Confidence(
            alpha=1.0 + (prior.alpha - 1.0) * factor,
            beta=1.0 + (prior.beta - 1.0) * factor,
        )

    def confidence(
        self,
        observations: Sequence[Observation],
        now: datetime,
        prior: Confidence | None = None,
    ) -> Confidence:
        """Fold the log onto the prior.

        `prior` defaults to Beta(1,1) - uniform, one pseudo-observation each
        way, believing nothing. A seeded or imported lexeme supplies a real one
        instead, so its history survives the arrival of new evidence.
        """
        prior = prior or Confidence()
        alpha, beta = prior.alpha, prior.beta
        for observation in observations:
            if observation.accepted is False:
                continue
            age = (now - observation.at).total_seconds() / 86400.0
            weight = self.weight_for(observation) * decay(age, self.thresholds.decay_half_life_days)
            if observation.polarity is ObservationPolarity.CONTRADICTS:
                beta += weight
            else:
                alpha += weight
        return Confidence(alpha, beta)

    def state_for(
        self, lexeme: Lexeme, confidence: Confidence, now: datetime
    ) -> LexemeState:
        """State is derived, never stored independently.

        A lexeme is ACTIVE when it is both believed (confidence) and
        substantiated (evidence mass). The second condition is what stops a
        single ambient sighting - one observation, no contradiction, confidence
        0.8 - from behaving like something the user has confirmed twice.
        """
        if lexeme.state is LexemeState.SUPPRESSED:
            return LexemeState.SUPPRESSED
        if lexeme.state is LexemeState.RETIRED:
            return LexemeState.RETIRED
        if confidence.mean < self.thresholds.dormancy_confidence:
            return LexemeState.DORMANT
        # Disuse causes dormancy on its own, independently of confidence. A name
        # the user has not said since April is not *less believed*, it is simply
        # no longer volunteering itself - and this check has to run before the
        # activation test, or a well-evidenced but stale memory stays ACTIVE
        # forever.
        if lexeme.last_used is not None:
            idle_days = (now - lexeme.last_used).total_seconds() / 86400.0
            if decay(idle_days, self.thresholds.decay_half_life_days) < 0.25:
                return LexemeState.DORMANT
        if (
            confidence.mean >= self.thresholds.activation_confidence
            and confidence.strength >= self.thresholds.activation_strength
        ):
            return LexemeState.ACTIVE
        return LexemeState.PROPOSED

    def refresh(self, lexemes: Sequence[Lexeme], log, now: datetime) -> list[Lexeme]:
        """Recompute confidence and state for every lexeme against the log.

        Cheap enough to run on load; the projection tables are a cache, so this
        is also the repair path if they ever drift.
        """
        out: list[Lexeme] = []
        for lexeme in lexemes:
            # Always recompute, even with an empty log: the projection is a
            # pure function of (prior, observations), which is what makes it
            # replayable and what stops a lexeme's confidence depending on
            # whether it happens to have been observed since start-up.
            observations = log.for_lexeme(lexeme.id)
            prior = self.decayed_prior(
                lexeme.prior, lexeme.last_used or lexeme.first_seen, now
            )
            confidence = self.confidence(observations, now, prior)
            lexeme = self.derive_guards(lexeme, observations)
            out.append(
                replace(
                    lexeme,
                    confidence=confidence,
                    state=self.state_for(lexeme, confidence, now),
                )
            )
        return out

    def derive_guards(self, lexeme: Lexeme, observations: Sequence[Observation]) -> Lexeme:
        """Guards that follow from evidence are derived here, not written by hand.

        Today that means one: repeated reverts in the same scope create a
        suppression guard. It belongs in the projection rather than in the
        learner because counting reverts means reading the log, and the log is
        what the projector is for. Deriving it also makes it self-correcting -
        replay the log and the guard comes back; truncate the log and it does
        not.
        """
        reverts: dict[str, int] = {}
        for observation in observations:
            if observation.source is ObservationSource.REVERT:
                key = observation.binding.key()
                reverts[key] = reverts.get(key, 0) + 1

        existing = {
            g.payload.get("scope")
            for g in lexeme.guards
            if g.kind is GuardKind.USER_SUPPRESSION
        }
        new = [
            Guard(
                kind=GuardKind.USER_SUPPRESSION,
                payload={"reverts": count, "scope": scope},
                note=f"user reverted this correction {count} times",
            )
            for scope, count in sorted(reverts.items())
            if count >= self.thresholds.reverts_to_suppress and scope not in existing
        ]
        if not new:
            return lexeme
        # SUPPRESSED outranks everything the confidence arithmetic could say:
        # the user has told us twice, in words we cannot argue with.
        return replace(
            lexeme, guards=(*lexeme.guards, *new), state=LexemeState.SUPPRESSED
        )


def merge_variant(variants: Sequence[Variant], form: str, provenance: VariantProvenance,
                  at: datetime) -> tuple[Variant, ...]:
    """Add or reinforce a variant. Provenance only ever strengthens: a form we
    guessed and then actually observed becomes observed, never the reverse."""
    rank = {
        VariantProvenance.GENERATED: 0,
        VariantProvenance.DECLARED: 1,
        VariantProvenance.OBSERVED: 2,
    }
    out: list[Variant] = []
    found = False
    for variant in variants:
        if variant.form.casefold() == form.casefold():
            found = True
            best = variant.provenance if rank[variant.provenance] >= rank[provenance] else provenance
            out.append(
                Variant(
                    form=variant.form,
                    provenance=best,
                    count=variant.count + 1,
                    last_seen=at,
                    binding=variant.binding,
                )
            )
        else:
            out.append(variant)
    if not found:
        out.append(Variant(form=form, provenance=provenance, count=1, last_seen=at))
    return tuple(out)
