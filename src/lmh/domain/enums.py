"""Closed vocabularies.

Every value here appears in the database, in eval fixtures and in the API.
Adding one is a schema change; renaming one is a migration.
"""

from __future__ import annotations

from enum import StrEnum

# `enum.StrEnum` (3.11+) means every member IS its own string value, so these
# enums serialise straight into JSON columns and SQL parameters with no
# `.value` at the call site and no custom __str__.


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #


class ObservationSource(StrEnum):
    """Where a piece of evidence came from. Determines its default weight."""

    DECLARED = "declared"           # user typed the term into the dictionary
    POST_EDIT = "post_edit"         # user edited inserted text in place
    INSTRUCTION = "instruction"     # spoken/typed instruction about a term
    AMBIENT = "ambient"             # term read from surrounding on-screen text
    REPETITION = "repetition"       # term recurred in the user's own writing
    REVERT = "revert"               # user undid one of our corrections
    DISMISSAL = "dismissal"         # user declined a proposal
    IMPORT = "import"               # migrated from an external dictionary


class ObservationPolarity(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #


class LexemeKind(StrEnum):
    PERSON = "person"
    ORG = "org"
    PRODUCT = "product"
    PLACE = "place"
    TERM = "term"               # jargon, acronyms, domain vocabulary
    CODE_SYMBOL = "code_symbol"  # service names, identifiers
    HANDLE = "handle"           # @mentions, #channels
    PHRASE = "phrase"           # multi-word fixed expressions, code-switched forms


class VariantProvenance(StrEnum):
    """How we came to believe this form stands in for the canonical one."""

    OBSERVED = "observed"    # an ASR actually emitted this. Strongest.
    DECLARED = "declared"    # the user told us. Strong, but unverified in the wild.
    GENERATED = "generated"  # we derived it phonetically. Weakest; needs support.


class LexemeState(StrEnum):
    """Derived from confidence and recency. Never set directly."""

    PROPOSED = "proposed"      # known, not yet trusted enough to apply
    ACTIVE = "active"
    DORMANT = "dormant"        # decayed; applies only with contextual support
    SUPPRESSED = "suppressed"  # a suppression guard is in force
    RETIRED = "retired"        # tombstoned


class GuardKind(StrEnum):
    """A condition under which a lexeme must not be applied."""

    COMMON_WORD = "common_word"        # the surface form is also ordinary English
    LEXICAL_CONTEXT = "lexical_context"  # veto when these tokens are nearby
    SEMANTIC_CONTEXT = "semantic_context"  # veto when the LLM judges the sense wrong
    SCOPE = "scope"                    # veto outside a binding
    VERBATIM = "verbatim"              # veto inside quotes / code fences
    USER_SUPPRESSION = "user_suppression"  # created by repeated reverts


class BindingScope(StrEnum):
    GLOBAL = "global"
    APP = "app"
    PERSONA = "persona"


class TombstoneReason(StrEnum):
    USER_DELETE = "user_delete"
    SUPERSESSION = "supersession"


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #


class Verdict(StrEnum):
    APPLY = "apply"
    PROPOSE = "propose"
    ABSTAIN = "abstain"


class PolicySignal(StrEnum):
    """What a single policy returns about a candidate."""

    SUPPORT = "support"    # contributes positively, weighted
    OPPOSE = "oppose"      # contributes negatively, weighted
    VETO = "veto"          # blocks regardless of every other signal
    NEUTRAL = "neutral"    # policy had nothing to say


class ReasonCode(StrEnum):
    """Why a verdict was reached. Reported per-code in the evaluation."""

    # apply
    EXACT_OBSERVED_VARIANT = "exact_observed_variant"
    PHONETIC_HIGH_CONFIDENCE = "phonetic_high_confidence"
    CONTEXT_SUPPORTED = "context_supported"
    DECLARED_BY_USER = "declared_by_user"
    STANDING_INSTRUCTION = "standing_instruction"

    # propose
    SINGLE_OBSERVATION = "single_observation"
    BELOW_ACTIVATION_THRESHOLD = "below_activation_threshold"
    SCOPE_UNPROVEN = "scope_unproven"
    CONFLICT_NEEDS_USER = "conflict_needs_user"

    # abstain
    NO_CANDIDATE = "no_candidate"
    COMMON_WORD_GUARD = "common_word_guard"
    GUARD_CONDITION_MET = "guard_condition_met"
    AMBIGUOUS_CONFLICT = "ambiguous_conflict"
    SUPERSEDED_BY_LONGER_SPAN = "superseded_by_longer_span"
    ALREADY_CANONICAL = "already_canonical"
    DORMANT_WITHOUT_SUPPORT = "dormant_without_support"
    OUT_OF_SCOPE = "out_of_scope"
    SEMANTIC_MISMATCH = "semantic_mismatch"
    VERBATIM_REGION = "verbatim_region"
    SUPPRESSED = "suppressed"
    NOT_PHONETIC_CHANGE = "not_phonetic_change"
    LEARNING_DISABLED = "learning_disabled"
    BELOW_THRESHOLD = "below_threshold"
    WRONG_REFERENT = "wrong_referent"
    SCRIPT_MISMATCH = "script_mismatch"


APPLY_REASONS = frozenset(
    {
        ReasonCode.EXACT_OBSERVED_VARIANT,
        ReasonCode.PHONETIC_HIGH_CONFIDENCE,
        ReasonCode.CONTEXT_SUPPORTED,
        ReasonCode.DECLARED_BY_USER,
        ReasonCode.STANDING_INSTRUCTION,
    }
)

PROPOSE_REASONS = frozenset(
    {
        ReasonCode.SINGLE_OBSERVATION,
        ReasonCode.BELOW_ACTIVATION_THRESHOLD,
        ReasonCode.SCOPE_UNPROVEN,
        ReasonCode.CONFLICT_NEEDS_USER,
    }
)

ABSTAIN_REASONS = frozenset(ReasonCode) - APPLY_REASONS - PROPOSE_REASONS
