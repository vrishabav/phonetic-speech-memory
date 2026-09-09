"""Domain objects.

Plain frozen dataclasses. No ORM, no framework, no I/O. Everything in
`engine/` operates on these; adapters translate at the boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from .enums import (
    BindingScope,
    GuardKind,
    LexemeKind,
    LexemeState,
    ObservationPolarity,
    ObservationSource,
    PolicySignal,
    ReasonCode,
    TombstoneReason,
    VariantProvenance,
    Verdict,
)

# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Binding:
    """Where something applies."""

    scope: BindingScope = BindingScope.GLOBAL
    ref: str | None = None  # app bundle id, or persona slug; None for GLOBAL

    def key(self) -> str:
        return self.scope.value if self.ref is None else f"{self.scope.value}:{self.ref}"

    def covers(self, other: Binding) -> bool:
        """A GLOBAL binding covers every context; a specific one covers only itself."""
        if self.scope is BindingScope.GLOBAL:
            return True
        return self.scope is other.scope and self.ref == other.ref


GLOBAL = Binding()


@dataclass(frozen=True, slots=True)
class Utterance:
    """One dictation, as PSM receives it."""

    asr_text: str
    formatted_text: str
    app: str | None = None
    persona: str | None = None
    surrounding_text: str | None = None
    utterance_id: str | None = None

    def binding(self) -> Binding:
        if self.app:
            return Binding(BindingScope.APP, self.app)
        if self.persona:
            return Binding(BindingScope.PERSONA, self.persona)
        return GLOBAL


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Observation:
    """An immutable piece of evidence. The only input to memory.

    `before`/`after` are the two forms in play. For a POST_EDIT that is what we
    inserted and what the user left behind. For a DECLARED add, `before` is None.
    """

    id: str
    source: ObservationSource
    at: datetime
    after: str
    before: str | None = None
    polarity: ObservationPolarity = ObservationPolarity.SUPPORTS
    binding: Binding = GLOBAL
    utterance_id: str | None = None
    surrounding_text: str | None = None
    lexeme_id: str | None = None          # set once attributed by the projector
    phonetic_distance: float | None = None  # None until the learner scores it
    accepted: bool | None = None            # False = rejected as non-phonetic
    note: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Variant:
    """A form that has stood in for a lexeme."""

    form: str
    provenance: VariantProvenance
    count: int = 0
    last_seen: datetime | None = None
    binding: Binding = GLOBAL


@dataclass(frozen=True, slots=True)
class Guard:
    """A condition under which the owning lexeme must not be applied.

    `payload` is kind-specific: a token list for LEXICAL_CONTEXT, a natural
    language predicate for SEMANTIC_CONTEXT, a binding for SCOPE.
    """

    kind: GuardKind
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_by_observation_id: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Confidence:
    """Beta posterior over "this lexeme should be applied when matched"."""

    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def strength(self) -> float:
        """Total (decayed) evidence mass. Distinguishes 0.5-from-nothing from 0.5-from-a-lot."""
        return self.alpha + self.beta - 2.0

    def support(self, weight: float) -> Confidence:
        return replace(self, alpha=self.alpha + weight)

    def contradict(self, weight: float) -> Confidence:
        return replace(self, beta=self.beta + weight)


@dataclass(frozen=True, slots=True)
class Lexeme:
    """A remembered term."""

    id: str
    canonical: str
    kind: LexemeKind
    # A standing instruction in the user's own words. Travels into the formatting
    # prompt verbatim. This is what makes the system more than a replace table.
    instruction: str | None = None
    variants: Sequence[Variant] = ()
    guards: Sequence[Guard] = ()
    bindings: Sequence[Binding] = (GLOBAL,)
    #: Evidence that predates this log: an imported dictionary, a seeded
    #: persona, a migrated profile. It is a genuine Bayesian prior - the log
    #: accumulates ON it, never replaces it. Without this the first correction
    #: of an imported term would *reduce* confidence, because the projection
    #: would suddenly be computed from one observation instead of a history.
    prior: Confidence = Confidence()
    #: Derived: `prior` folded together with every observation in the log.
    #: Never set directly outside the projector.
    confidence: Confidence = Confidence()
    state: LexemeState = LexemeState.PROPOSED
    learning_enabled: bool = True
    parent_id: str | None = None
    first_seen: datetime | None = None
    last_used: datetime | None = None
    evidence_ids: Sequence[str] = ()

    def observed_forms(self) -> tuple[str, ...]:
        return tuple(
            v.form for v in self.variants if v.provenance is VariantProvenance.OBSERVED
        )

    def observed_forms_with(self, form: str) -> tuple[Variant, ...]:
        """Variants the recogniser genuinely produced, matching `form`.

        Used by the common-word guard: an ordinary English word may only be
        corrected if it is a form actually seen, never one merely computed.
        """
        wanted = " ".join(form.casefold().split())
        return tuple(
            v
            for v in self.variants
            if v.provenance is not VariantProvenance.GENERATED
            and " ".join(v.form.casefold().split()) == wanted
        )

    def all_forms(self) -> tuple[str, ...]:
        return (self.canonical,) + tuple(v.form for v in self.variants)


@dataclass(frozen=True, slots=True)
class Tombstone:
    id: str
    reason: TombstoneReason
    canonical: str
    match_forms: Sequence[str] = ()
    source_lexeme_id: str | None = None
    replacement_lexeme_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """The projection at a point in time. What an eval case records."""

    at: datetime
    lexemes: Sequence[Lexeme] = ()
    tombstones: Sequence[Tombstone] = ()
    observation_count: int = 0

    def by_id(self, lexeme_id: str) -> Lexeme | None:
        return next((lx for lx in self.lexemes if lx.id == lexeme_id), None)


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    text: str

    def __len__(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Candidate:
    """A (span, lexeme) pair proposed by retrieval, before any policy has run."""

    span: Span
    lexeme: Lexeme
    matched_form: str
    retrieval_score: float
    matched_via: str  # "exact_variant" | "phonetic_key" | "fuzzy" | "canonical"


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """One policy's opinion about one candidate. Both halves of the audit trail."""

    policy: str
    signal: PolicySignal
    weight: float = 0.0            # signed contribution; ignored when signal is VETO
    reason: ReasonCode | None = None
    rationale: str = ""            # human-readable, shown in the UI and the report
    evidence_ids: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class Resolution:
    """The decision about a single candidate."""

    candidate: Candidate
    verdict: Verdict
    score: float
    reason: ReasonCode
    outcomes: Sequence[PolicyOutcome] = ()
    replacement: str | None = None  # canonical form, when APPLY

    def explain(self) -> str:
        return "; ".join(o.rationale for o in self.outcomes if o.rationale)


@dataclass(frozen=True, slots=True)
class Cost:
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_paise: float = 0.0
    llm_calls: int = 0


@dataclass(frozen=True, slots=True)
class Adjudication:
    """The complete record of one call. Written for every utterance, including
    those where nothing happened."""

    utterance: Utterance
    output_text: str
    resolutions: Sequence[Resolution] = ()
    gate_passed: bool = False
    verifier_rejected: bool = False
    cost: Cost = Cost()
    memory_snapshot_ref: str | None = None
    at: datetime | None = None

    @property
    def applied(self) -> tuple[Resolution, ...]:
        return tuple(r for r in self.resolutions if r.verdict is Verdict.APPLY)

    @property
    def abstained(self) -> tuple[Resolution, ...]:
        return tuple(r for r in self.resolutions if r.verdict is Verdict.ABSTAIN)

    @property
    def proposed(self) -> tuple[Resolution, ...]:
        return tuple(r for r in self.resolutions if r.verdict is Verdict.PROPOSE)

    @property
    def intervened(self) -> bool:
        return bool(self.applied) and self.output_text != self.utterance.formatted_text
