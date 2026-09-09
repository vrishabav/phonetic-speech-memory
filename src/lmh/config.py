"""Settings.

Every knob that changes behaviour lives here so that an experiment is fully
described by a Settings object, and so that the eval harness can serialise the
exact configuration a result was produced under.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

# Ordered. Cheap, decisive policies first so a veto short-circuits early.
_DOTENV_LOADED = False

DEFAULT_POLICIES: tuple[str, ...] = (
    "suppression",        # the user already said no. Nothing else gets a vote.
    "verbatim",           # somebody else's words: quotes, code
    "already_canonical",  # nothing to do, and no model call
    "script_fit",         # never swap the user's alphabet
    "scope_fit",          # right form, wrong place
    "exact_variant",      # a form the recogniser has actually produced
    "phonetic",           # a form it has not, but that sounds right
    "common_word_guard",  # the term is also an ordinary word
    "cooccurrence",       # terms learned together appear together
    "conflict",           # two memories, one sound
    "recency",            # decayed memories act only on strong evidence
)
# `learning_enabled` is deliberately NOT a policy. It governs whether new
# evidence is *recorded*, not whether existing memory is *applied* - the two
# are separately controllable, and conflating them would mean switching off
# learning silently switched off correction too. It is enforced in the
# learner and pinned by L13-001.


@dataclass(frozen=True, slots=True)
class Thresholds:
    #: Phonetic distance above which a candidate is not even considered.
    retrieval_max_distance: float = 0.34
    #: Combined score required to APPLY.
    apply_score: float = 0.55
    #: Combined score required to PROPOSE rather than ABSTAIN.
    propose_score: float = 0.30
    #: Confidence mean required for a lexeme to be ACTIVE.
    activation_confidence: float = 0.60
    #: Decayed evidence mass required for a lexeme to be ACTIVE.
    activation_strength: float = 1.5
    #: Below this confidence a lexeme is DORMANT.
    dormancy_confidence: float = 0.35
    #: Half-life of evidence, in days.
    decay_half_life_days: float = 90.0
    #: A post-edit is only phonetic evidence below this distance.
    learn_max_phonetic_distance: float = 0.45
    #: Reverts before a suppression guard is created.
    reverts_to_suppress: int = 2


@dataclass(frozen=True, slots=True)
class EvidenceWeights:
    """Default weight per observation source, before decay."""

    declared: float = 3.0
    instruction: float = 3.0
    post_edit: float = 1.0
    repetition: float = 0.5
    ambient: float = 0.25
    imported: float = 1.0
    revert: float = 2.0      # applied to beta
    dismissal: float = 1.0   # applied to beta


@dataclass(frozen=True, slots=True)
class Settings:
    # --- components (dotted path or registry alias) ---
    clock: str = "clock.system"
    phonetics: str = "phonetics.dmetaphone"
    store: str = "store.sqlite"
    index: str = "index.inmemory"
    llm: str = "llm.stub"
    formatter: str = "formatter.passthrough"
    policies: tuple[str, ...] = DEFAULT_POLICIES

    # --- behaviour ---
    thresholds: Thresholds = field(default_factory=Thresholds)
    weights: EvidenceWeights = field(default_factory=EvidenceWeights)
    #: When False the adjudicator is deterministic-only. This is an ablation.
    allow_llm_adjudication: bool = True
    #: When False memory is not injected into the formatting prompt. Ablation.
    allow_prompt_injection: bool = True
    #: Reject a model result that changed spans it was not asked to change.
    verify_output: bool = True

    # --- infrastructure ---
    database_url: str = "sqlite:///./data/lmh.db"
    cassette_dir: str = "evals/cassettes"
    sarvam_base_url: str = "https://api.sarvam.ai/v1"
    sarvam_model: str = "sarvam-105b"

    def with_(self, **kwargs: Any) -> Settings:
        """Return a copy with fields replaced. Used to define ablations."""
        return replace(self, **kwargs)

    def describe(self) -> Mapping[str, Any]:
        """Serialisable description, embedded in every eval result."""
        return {
            "clock": self.clock,
            "phonetics": self.phonetics,
            "store": self.store,
            "index": self.index,
            "llm": self.llm,
            "formatter": self.formatter,
            "policies": list(self.policies),
            "allow_llm_adjudication": self.allow_llm_adjudication,
            "allow_prompt_injection": self.allow_prompt_injection,
            "verify_output": self.verify_output,
            "thresholds": asdict(self.thresholds),
            "weights": asdict(self.weights),
        }


def load_dotenv_once() -> None:
    """Read `.env` into the environment if it exists.

    Values already set in the real environment win, so an explicit
    `SARVAM_API_KEY=... make eval-live` overrides the file. Missing file is not
    an error - the whole system runs without one.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    path = Path(os.environ.get("LMH_DOTENV", ".env"))
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # Tolerate `KEY = "value"` as well as `KEY=value`.
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def from_env(**overrides: Any) -> Settings:
    """Settings from `.env`, then the environment, then explicit overrides."""
    load_dotenv_once()
    env: dict[str, Any] = {}
    for field_name in (
        "clock",
        "phonetics",
        "store",
        "index",
        "llm",
        "formatter",
        "database_url",
        "cassette_dir",
        "sarvam_base_url",
        "sarvam_model",
    ):
        value = os.environ.get(f"LMH_{field_name.upper()}")
        if value:
            env[field_name] = value
    policies = os.environ.get("LMH_POLICIES")
    if policies:
        env["policies"] = tuple(p.strip() for p in policies.split(",") if p.strip())
    return Settings(**{**env, **overrides})
