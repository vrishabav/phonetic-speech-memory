"""Policy helpers shared by the stack."""

from __future__ import annotations

from psm.domain.enums import PolicySignal, ReasonCode
from psm.domain.models import PolicyOutcome


def support(policy: str, weight: float, rationale: str, reason: ReasonCode | None = None):
    return PolicyOutcome(policy, PolicySignal.SUPPORT, weight, reason, rationale)


def oppose(policy: str, weight: float, rationale: str, reason: ReasonCode | None = None):
    return PolicyOutcome(policy, PolicySignal.OPPOSE, -abs(weight), reason, rationale)


def veto(policy: str, reason: ReasonCode, rationale: str):
    return PolicyOutcome(policy, PolicySignal.VETO, 0.0, reason, rationale)


def neutral(policy: str, rationale: str = ""):
    return PolicyOutcome(policy, PolicySignal.NEUTRAL, 0.0, None, rationale)
