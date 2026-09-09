"""Turn policy opinions into a verdict.

The rules are deliberately dull, because the interesting judgement already
happened inside the policies and this is where it has to become auditable:

  1. Any VETO ends it. The first veto in policy order is the reason, so the
     explanation the user reads is the cheapest true one rather than whichever
     rule happened to run last.
  2. Otherwise the contributions sum. APPLY above one threshold, PROPOSE above
     a lower one, ABSTAIN below.
  3. A lexeme that is not yet trusted can never APPLY, however strong the
     match. Evidence about *what* the form is does not substitute for evidence
     that the user wants it changed.
"""

from __future__ import annotations

from collections.abc import Sequence

from psm.config import Thresholds
from psm.domain.enums import LexemeState, PolicySignal, ReasonCode, Verdict
from psm.domain.models import Candidate, PolicyOutcome, Resolution
from psm.ports.policy import PolicyContext

#: Which reason best describes an APPLY when several policies contributed.
#: Ordered by how much machinery the decision needed, most first, so the
#: primary reason names the most interesting thing that happened rather than
#: the highest-scoring coincidence.
APPLY_REASON_PRECEDENCE = (
    ReasonCode.STANDING_INSTRUCTION,
    ReasonCode.CONTEXT_SUPPORTED,
    ReasonCode.EXACT_OBSERVED_VARIANT,
    ReasonCode.DECLARED_BY_USER,
    ReasonCode.PHONETIC_HIGH_CONFIDENCE,
)


class Adjudicator:
    def __init__(self, policies: Sequence, thresholds: Thresholds) -> None:
        self.policies = sorted(policies, key=lambda p: p.order)
        self.thresholds = thresholds

    def resolve(self, candidate: Candidate, ctx: PolicyContext) -> Resolution:
        outcomes: list[PolicyOutcome] = []
        for policy in self.policies:
            outcome = policy.evaluate(candidate, ctx)
            outcomes.append(outcome)
            if outcome.signal is PolicySignal.VETO:
                return Resolution(
                    candidate=candidate,
                    verdict=Verdict.ABSTAIN,
                    score=0.0,
                    reason=outcome.reason or ReasonCode.BELOW_THRESHOLD,
                    outcomes=tuple(outcomes),
                )

        score = sum(o.weight for o in outcomes)
        reason = self._primary_reason(outcomes)

        if score < self.thresholds.propose_score:
            return Resolution(
                candidate, Verdict.ABSTAIN, score, ReasonCode.BELOW_THRESHOLD, tuple(outcomes)
            )

        untrusted = candidate.lexeme.state is LexemeState.PROPOSED
        if score < self.thresholds.apply_score or untrusted:
            return Resolution(
                candidate,
                Verdict.PROPOSE,
                score,
                ReasonCode.BELOW_ACTIVATION_THRESHOLD
                if untrusted
                else ReasonCode.SINGLE_OBSERVATION,
                tuple(outcomes),
            )

        return Resolution(
            candidate,
            Verdict.APPLY,
            score,
            reason,
            tuple(outcomes),
            replacement=candidate.lexeme.canonical,
        )

    @staticmethod
    def _primary_reason(outcomes: Sequence[PolicyOutcome]) -> ReasonCode:
        contributed = {
            o.reason
            for o in outcomes
            if o.reason is not None and o.signal is PolicySignal.SUPPORT
        }
        for reason in APPLY_REASON_PRECEDENCE:
            if reason in contributed:
                return reason
        return ReasonCode.PHONETIC_HIGH_CONFIDENCE
