"""The unit of ablation.

Each policy inspects one candidate and returns one opinion. The adjudicator
combines them. Adding a rule to the system means adding a Policy; removing one
from an experiment means removing a name from a config list.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from lmh.domain.models import Binding, Candidate, MemorySnapshot, PolicyOutcome, Utterance


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Everything a policy is allowed to look at. Deliberately narrow."""

    utterance: Utterance
    binding: Binding
    snapshot: MemorySnapshot
    now: datetime
    #: Every other candidate retrieved for this utterance. Candidates are
    #: allowed to support or contradict one another - that is how co-occurrence
    #: and conflict work - but never to see anything outside this utterance.
    siblings: Sequence[Candidate] = ()
    #: (a_id, b_id, rel, weight). Relations between lexemes: alias, cooccurs,
    #: conflicts.
    edges: Sequence[tuple[str, str, str, float]] = ()


@runtime_checkable
class Policy(Protocol):
    name: str
    #: Policies run in ascending order. Cheap and decisive ones go first so that
    #: a VETO short-circuits before anything expensive runs.
    order: int

    def evaluate(self, candidate: Candidate, ctx: PolicyContext) -> PolicyOutcome:
        """Return this policy's opinion. Must be pure and must not raise."""
        ...
