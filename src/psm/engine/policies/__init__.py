"""The policy stack.

Each policy inspects one candidate and returns one opinion: a bounded
contribution, a machine-readable reason code, and a sentence a human can read.
The adjudicator combines them; nothing here knows about thresholds or verdicts.

Two properties make this worth the indirection:

  * `VETO` is expressible. A guard can block a candidate no matter how strong
    the phonetic evidence is, so "deliberately do nothing" is a return value
    rather than a threshold that happened not to be crossed.
  * Removing a policy is a config edit. The ablation table in the evaluation
    falls out of the architecture instead of being bolted onto it.

Order matters: cheap, decisive policies run first so a veto short-circuits
before anything expensive.
"""

from __future__ import annotations

from .conflict import ConflictPolicy
from .context import CommonWordGuardPolicy, CooccurrencePolicy, ScopeFitPolicy
from .lexical import AlreadyCanonicalPolicy, ExactVariantPolicy, PhoneticPolicy
from .recency import RecencyPolicy
from .script import ScriptFitPolicy
from .suppression import SuppressionPolicy, VerbatimPolicy

REGISTRY = {
    "suppression": SuppressionPolicy,
    "verbatim": VerbatimPolicy,
    "already_canonical": AlreadyCanonicalPolicy,
    "script_fit": ScriptFitPolicy,
    "scope_fit": ScopeFitPolicy,
    "exact_variant": ExactVariantPolicy,
    "phonetic": PhoneticPolicy,
    "common_word_guard": CommonWordGuardPolicy,
    "cooccurrence": CooccurrencePolicy,
    "conflict": ConflictPolicy,
    "recency": RecencyPolicy,
}

__all__ = ["REGISTRY", "build_stack"]


def build_stack(names) -> list:
    """Instantiate the named policies, in the given order.

    An unknown name is an error rather than a silent omission - an ablation
    that quietly ran the full stack would be worse than no ablation at all.
    """
    stack = []
    for name in names:
        try:
            stack.append(REGISTRY[name]())
        except KeyError:
            raise ValueError(
                f"unknown policy {name!r}; known policies: {', '.join(sorted(REGISTRY))}"
            ) from None
    return stack
