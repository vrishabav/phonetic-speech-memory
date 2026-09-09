"""Unit tests for the engine's moving parts.

The fixture suite in `evals/` tests the *product claim* end to end. These tests
cover the mechanisms underneath it, where a bug is invisible in an aggregate
pass rate: span selection, decay arithmetic, the learner's phonetic gate, and
the invariant that the ports are actually ports.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lmh.adapters.clock.frozen import FrozenClock
from lmh.adapters.phonetics.dmetaphone import PhoneticStack, normalise
from lmh.adapters.store.memory import InMemoryStore
from lmh.config import EvidenceWeights, Settings, Thresholds
from lmh.domain.enums import (
    LexemeState,
    ObservationSource,
    Verdict,
)
from lmh.domain.models import Confidence, Utterance
from lmh.engine.engine import Engine
from lmh.engine.learner import Learner, observation
from lmh.engine.projector import Projector, decay
from lmh.engine.text import in_protected_region, ngram_spans, splice, window_tokens
from lmh.seed import load_persona

ROOT = Path(__file__).resolve().parents[1]
PERSONA = ROOT / "evals" / "data" / "persona_seed.json"
CLOCK = "2026-01-15T09:00:00+00:00"


@pytest.fixture
def engine() -> Engine:
    payload = json.loads(PERSONA.read_text(encoding="utf-8"))
    clock = FrozenClock(CLOCK)
    lexemes, edges = load_persona(payload, now=clock.now())
    settings = Settings(store="store.memory", database_url="memory://")
    eng = Engine.build(settings, lexemes=lexemes, edges=edges)
    eng.clock = clock
    eng.load(lexemes=lexemes, edges=edges)
    return eng


def run(engine: Engine, formatted: str, *, asr: str = "", app: str | None = None):
    return engine.handle(
        Utterance(asr or formatted, formatted, app=app), record=False
    )


# --------------------------------------------------------------------------- #
# Text mechanics
# --------------------------------------------------------------------------- #


def test_ngram_spans_cover_multi_token_entities():
    spans = {s.text for s in ngram_spans("Ask Adith Narayanan today")}
    assert "Adith Narayanan" in spans
    assert "Ask Adith Narayanan" in spans


def test_splice_applies_right_to_left():
    """Left-to-right splicing invalidates every offset after the first edit -
    the classic way a multi-correction utterance comes out mangled."""
    text = "aa bb cc"
    spans = ngram_spans(text, max_len=1)
    by_text = {s.text: s for s in spans}
    out = splice(text, [(by_text["aa"], "XXXX"), (by_text["cc"], "Y")])
    assert out == "XXXX bb Y"


def test_window_is_local_not_utterance_wide():
    """The property MX-001 depends on: a veto token six tokens away must not
    reach back and block an earlier occurrence."""
    text = "debugging kiwi while i finish the kiwi smoothie"
    spans = [s for s in ngram_spans(text, max_len=1) if s.text == "kiwi"]
    first, second = spans[0], spans[1]
    assert "debugging" in window_tokens(text, first)
    assert "smoothie" not in window_tokens(text, first)
    assert "smoothie" in window_tokens(text, second)


@pytest.mark.parametrize(
    "text",
    ['He said "the Bangalore office" today', "run `const kiwi = 1` now"],
)
def test_protected_regions_are_detected(text):
    inner = [s for s in ngram_spans(text, max_len=1) if s.text in {"Bangalore", "kiwi"}][0]
    assert in_protected_region(inner, text)


def test_normalise_is_stable():
    assert normalise("  Sarah's  Desk!! ") == "sarah's desk"
    assert normalise("Grad-CAM") == "grad-cam"


# --------------------------------------------------------------------------- #
# Confidence and decay
# --------------------------------------------------------------------------- #


def test_decay_halves_at_the_half_life():
    assert decay(90, 90) == pytest.approx(0.5, abs=1e-9)
    assert decay(0, 90) == 1.0


def test_confidence_distinguishes_belief_from_evidence_mass():
    """0.5 from nothing and 0.5 from a lot are different states. A bare counter
    cannot tell them apart; the posterior can, and `strength` is what the
    activation threshold reads."""
    thin = Confidence(1.0, 1.0)
    thick = Confidence(10.0, 10.0)
    assert thin.mean == thick.mean == 0.5
    assert thick.strength > thin.strength


def test_reverts_and_support_share_one_arithmetic():
    projector = Projector(Thresholds(), EvidenceWeights())
    now = datetime(2026, 1, 15, tzinfo=UTC)
    supporting = observation(ObservationSource.POST_EDIT, "Kivi", at=now, before="kiwi")
    contradicting = observation(ObservationSource.REVERT, "kiwi", at=now, before="Kivi")
    up = projector.confidence([supporting], now)
    down = projector.confidence([supporting, contradicting], now)
    assert down.mean < up.mean
    assert down.strength > up.strength  # a revert is evidence, not erasure


def test_disuse_causes_dormancy_independently_of_confidence(engine):
    """A well-evidenced name the user stopped saying must fade, or the store
    only ever grows louder."""
    lexeme = next(lx for lx in engine.lexemes if lx.id == "lex.rukmini")
    assert lexeme.state is LexemeState.DORMANT


# --------------------------------------------------------------------------- #
# The learner's phonetic gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("before", "after", "accepted"),
    [
        ("Adith Kulkarni", "Aadith Kulkarni", True),
        ("bangalore", "Bengaluru", True),
        ("Ask Aadith to review it", "Please ask Aadith when he is free to review it", False),
        ("ship it on Tuesday", "ship it on Thursday", False),
    ],
)
def test_only_respellings_become_evidence(before, after, accepted):
    """The single filter that keeps the store clean. Without it, every
    stylistic edit becomes a spurious lexeme."""
    learner = Learner(PhoneticStack(), Thresholds())
    obs = observation(
        ObservationSource.POST_EDIT, after, at=datetime(2026, 1, 15, tzinfo=UTC), before=before
    )
    assert learner.judge(obs).accepted is accepted


def test_rejected_observations_are_still_recorded(engine):
    """Declining to learn is itself a decision and has to be inspectable."""
    judged = engine.observe(
        observation(
            ObservationSource.POST_EDIT,
            "Please ask Aadith when he is free",
            at=engine.now(),
            before="Ask Aadith to review it",
        )
    )
    assert judged.accepted is False
    assert "rejected" in (judged.note or "")
    assert engine.store.all()


def test_declared_terms_are_usable_immediately(engine):
    before = {lx.id for lx in engine.lexemes}
    engine.teach("Kshetra Labs")
    created = [lx for lx in engine.lexemes if lx.id not in before]
    assert len(created) == 1
    assert created[0].canonical == "Kshetra Labs"


def test_a_single_inferred_correction_only_proposes(engine):
    engine.observe(
        observation(
            ObservationSource.POST_EDIT,
            "Aadith Kulkarni",
            at=engine.now(),
            before="Adith Kulkarni",
        )
    )
    lexeme = next(lx for lx in engine.lexemes if lx.canonical == "Aadith Kulkarni")
    assert lexeme.state is LexemeState.PROPOSED


def test_repetition_promotes_to_active(engine):
    for day in (0, 1):
        engine.observe(
            observation(
                ObservationSource.POST_EDIT,
                "Aadith Kulkarni",
                at=engine.now() + timedelta(days=day),
                before="Adith Kulkarni",
            )
        )
    lexeme = next(lx for lx in engine.lexemes if lx.canonical == "Aadith Kulkarni")
    assert lexeme.state is LexemeState.ACTIVE


# --------------------------------------------------------------------------- #
# End-to-end behaviour
# --------------------------------------------------------------------------- #


def test_ordinary_text_costs_nothing_and_is_left_alone(engine):
    """What matters is that ordinary text is untouched and free.

    Note this does NOT assert the gate stayed shut. Once memory contains a
    three-letter acronym like WER, the gate opens on plenty of ordinary
    sentences - "we" blocks against it - and that is an unavoidable cost of
    remembering short acronyms at all. The guarantee that survives is the one
    worth having: nothing changes, nothing is spent.
    """
    text = "Can we move the sync to four o'clock tomorrow?"
    result = run(engine, text)
    assert result.output_text == text
    assert result.applied == ()
    assert result.cost.llm_calls == 0


def test_a_known_variant_is_corrected(engine):
    result = run(engine, "Ask Adith Narayanan to review it.")
    assert result.output_text == "Ask Aadith Narayanan to review it."
    assert result.applied[0].reason.value == "exact_observed_variant"


def test_a_common_word_survives_without_support(engine):
    """The case the whole product is judged on."""
    result = run(engine, "I ate a kiwi for breakfast.")
    assert result.output_text == "I ate a kiwi for breakfast."
    assert result.abstained[0].reason.value == "common_word_guard"


def test_the_same_word_can_be_corrected_and_left_alone_in_one_utterance(engine):
    text = "Adith Narayanan is debugging Kiwi while I finish the kiwi smoothie."
    result = run(engine, text, app="com.tinyspeck.slackmacgap")
    assert "debugging Kivi" in result.output_text
    assert "kiwi smoothie" in result.output_text


def test_every_decision_carries_a_rationale(engine):
    result = run(engine, "The Sarvam Kiwi service is dropping requests.")
    for resolution in result.resolutions:
        assert resolution.reason is not None
        assert any(o.rationale for o in resolution.outcomes)


def test_abstentions_are_recorded_not_merely_absent(engine):
    result = run(engine, "I ate a kiwi for breakfast.")
    assert result.abstained, "an abstention must appear in the trace, not vanish"
    assert result.output_text == result.utterance.formatted_text


# --------------------------------------------------------------------------- #
# The ports are real
# --------------------------------------------------------------------------- #


def test_engine_runs_against_a_store_that_is_not_sqlite(engine):
    assert isinstance(engine.store, InMemoryStore)
    assert run(engine, "Ask Adith Narayanan to review it.").applied


def test_removing_a_policy_is_a_config_change():
    """Ablations must be declarative. If this needed a code branch, the
    evaluation's ablation table would not mean anything."""
    payload = json.loads(PERSONA.read_text(encoding="utf-8"))
    clock = FrozenClock(CLOCK)
    lexemes, edges = load_persona(payload, now=clock.now())
    settings = Settings(store="store.memory", database_url="memory://").with_(
        policies=("suppression", "scope_fit", "exact_variant")
    )
    eng = Engine.build(settings, lexemes=lexemes, edges=edges)
    eng.clock = clock
    eng.load(lexemes=lexemes, edges=edges)
    # Without the guard stack, the fruit gets corrected. That is the point of
    # the ablation: it shows what the guards are actually buying.
    result = run(eng, "I ate a kiwi for breakfast.")
    assert result.output_text != "I ate a kiwi for breakfast."


def test_an_unknown_policy_name_is_an_error_not_a_silent_omission():
    from lmh.engine.policies import build_stack

    with pytest.raises(ValueError, match="unknown policy"):
        build_stack(["suppression", "nonsense"])


def test_verdicts_are_three_valued(engine):
    """apply / propose / abstain. A two-valued system cannot express "I think
    so but not enough to touch your text"."""
    assert {Verdict.APPLY, Verdict.PROPOSE, Verdict.ABSTAIN} == set(Verdict)


# --------------------------------------------------------------------------- #
# Priors
#
# Regression. Found by clicking "Record" in the demo UI and reading the answer:
# a *supporting* post-edit moved "Shreyaa Bhattacharya" from active to
# proposed. The projection was `log if log else stored confidence`, so the
# first observation about a seeded term replaced four sightings' worth of
# history with one. Confirming a term made the system less sure of it.
#
# The fix is `prior + log`, always, with Beta(1,1) for a term that really did
# start from nothing. These tests pin the direction of movement rather than the
# exact number, because the numbers are threshold-dependent and the direction
# is the actual promise.
# --------------------------------------------------------------------------- #


def _seeded_engine():
    from lmh.config import Settings
    from lmh.engine.engine import Engine
    from lmh.seed import load_persona

    engine = Engine.build(Settings(store="store.memory"))
    lexemes, edges = load_persona("evals/data/persona_seed.json", now=engine.now())
    engine.load(lexemes=lexemes, edges=edges)
    return engine


def _find(engine, canonical):
    return next(lx for lx in engine.lexemes if lx.canonical == canonical)


def test_supporting_evidence_never_lowers_confidence():
    from lmh.domain.enums import ObservationSource
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    before = _find(engine, "Shreyaa Bhattacharya")
    engine.observe(
        observation(
            ObservationSource.POST_EDIT,
            "Shreyaa Bhattacharya",
            at=engine.now(),
            before="Shreya Bhattacharya",
        )
    )
    after = _find(engine, "Shreyaa Bhattacharya")
    assert after.confidence.mean >= before.confidence.mean
    assert after.confidence.strength > before.confidence.strength
    assert after.state == before.state, "a confirmation must never demote a term"


def test_contradicting_evidence_still_lowers_confidence():
    """The other direction has to keep working, or the fix above is just a
    ratchet that makes memory unfalsifiable."""
    from lmh.domain.enums import ObservationSource
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    before = _find(engine, "Shreyaa Bhattacharya")
    engine.observe(
        observation(
            ObservationSource.REVERT,
            "Shreyaa Bhattacharya",
            at=engine.now(),
            before="Shreya Bhattacharya",
        )
    )
    after = _find(engine, "Shreyaa Bhattacharya")
    assert after.confidence.mean < before.confidence.mean


def test_a_term_with_no_prior_starts_from_uniform():
    """A genuinely new term must not inherit anybody's confidence."""
    from lmh.domain.enums import ObservationSource
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    engine.observe(
        observation(ObservationSource.AMBIENT, "Padmanabhan Iyengar", at=engine.now())
    )
    fresh = _find(engine, "Padmanabhan Iyengar")
    assert fresh.prior.alpha == 1.0 and fresh.prior.beta == 1.0
    # One weak sighting: known, not trusted. Proposing rather than applying is
    # the whole point of the state machine.
    assert fresh.state.value == "proposed"


def test_the_projection_is_stable_under_repeated_refresh():
    """`refresh` runs on every load. If it folded the prior in each time rather
    than computing from it, confidence would drift on restart alone.

    The clock is frozen because the projection is a pure function of
    (prior, log, now) and `now` is genuinely one of the inputs - priors decay.
    Freezing it is what makes "stable" a testable claim rather than a
    tolerance."""
    from lmh.adapters.clock.frozen import FrozenClock

    engine = _seeded_engine()
    engine.clock = FrozenClock("2026-01-15T09:00:00+00:00")
    engine.load(lexemes=engine.lexemes, edges=[])
    first = _find(engine, "Kivi").confidence
    for _ in range(3):
        engine.load(lexemes=engine.lexemes, edges=[])
    assert _find(engine, "Kivi").confidence == first


def test_sqlite_round_trip_preserves_the_prior(tmp_path):
    """A prior that vanished on save would resurrect the original bug the next
    time the process started, which is the worst kind: invisible in tests that
    never restart."""
    from alembic import command
    from alembic.config import Config

    from lmh.adapters.store.sqlite import SqliteStore
    from lmh.domain.models import Confidence
    from lmh.seed import load_persona

    # Built by the real migrations, not by a convenience helper: this doubles as
    # the test that `make migrate` produces a schema the code can actually use.
    url = f"sqlite:///{tmp_path}/round.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    store = SqliteStore(url)
    lexemes, _ = load_persona("evals/data/persona_seed.json")
    store.put(lexemes)

    reloaded = {lx.id: lx for lx in store.all_lexemes()}
    for original in lexemes:
        assert reloaded[original.id].prior == original.prior
    assert any(lx.prior != Confidence() for lx in reloaded.values()), (
        "the persona carries real priors; a round trip of all-default priors "
        "would pass this test vacuously"
    )


# --------------------------------------------------------------------------- #
# Instructions, renames and deletions
#
# Three learner paths that are not corrections. Each was specified in the
# taxonomy from the start and none was implemented until the learning tier was
# actually run against the engine.
# --------------------------------------------------------------------------- #


def test_an_instruction_names_its_own_term():
    from lmh.engine.learner import Learner

    extract = Learner.term_from_instruction
    assert extract("always write it Aadith with two a's") == "Aadith"
    # A multi-word term yields its most distinctive token, not the phrase.
    # That is a stated limitation of a deliberately small parser: attaching the
    # instruction to the right lexeme is what matters, and "theek" reaches
    # "theek hai" through the same variant matching everything else uses.
    assert extract("never translate theek hai") == "theek"
    assert extract('spell it "vaani-gateway"') == "vaani-gateway"
    assert extract("always keep #eng-asr as a handle") == "#eng-asr"
    # Nothing term-like: better to attach nothing than to invent a lexeme named
    # after a sentence.
    assert extract("please just do it") is None


def test_an_instruction_is_stored_verbatim_not_compiled():
    """A8 is the class the architecture is shaped around. The instruction has to
    survive as the user's words, because it is a rule about how to write rather
    than a string to substitute."""
    from lmh.domain.enums import ObservationSource
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    engine.observe(
        observation(
            ObservationSource.INSTRUCTION,
            "always write it Aadith with two a's",
            at=engine.now(),
        )
    )
    target = _find(engine, "Aadith Narayanan")
    assert target.instruction is not None


def test_a_rename_tombstones_the_old_form_and_keeps_it_resolving():
    from lmh.domain.enums import ObservationSource
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    engine.observe(
        observation(
            ObservationSource.DECLARED,
            "vaani-api",
            at=engine.now(),
            before="vaani-gateway",
            lexeme_id="lex.vaani_gateway",
        )
    )
    renamed = next(lx for lx in engine.lexemes if lx.id == "lex.vaani_gateway")
    assert renamed.canonical == "vaani-api"
    # The old spelling must still resolve, or the next time the recogniser
    # produces it the term is learned again from zero.
    assert "vaani-gateway" in [v.form for v in renamed.variants]
    stones = engine.store.tombstones()
    assert stones and str(stones[0].reason) == "supersession"
    assert "vaani-gateway" in stones[0].match_forms


def test_a_deletion_tombstones_rather_than_dropping():
    from lmh.domain.enums import ObservationSource
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    engine.observe(
        observation(
            ObservationSource.DECLARED,
            "",
            at=engine.now(),
            lexeme_id="lex.rukmini",
            note="forget",
        )
    )
    assert _find(engine, "Rukmini Iyer").state.value == "retired"
    stones = engine.store.tombstones()
    assert stones and str(stones[0].reason) == "user_delete"


def test_two_reverts_in_one_scope_create_a_suppression_guard():
    """Derived from the log by the projector, not written by the learner - so
    replaying the log reproduces the guard and truncating it removes the guard."""
    from lmh.domain.enums import ObservationSource
    from lmh.domain.models import Binding, BindingScope
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    binding = Binding(BindingScope.APP, "com.tinyspeck.slackmacgap")
    for _ in range(2):
        engine.observe(
            observation(
                ObservationSource.REVERT,
                "prawed",
                at=engine.now(),
                before="prod",
                binding=binding,
                lexeme_id="lex.prod",
            )
        )
    target = next(lx for lx in engine.lexemes if lx.id == "lex.prod")
    assert target.state.value == "suppressed"
    assert any(str(g.kind) == "user_suppression" for g in target.guards)


def test_one_revert_is_not_enough_to_suppress():
    from lmh.domain.enums import ObservationSource
    from lmh.domain.models import Binding, BindingScope
    from lmh.engine.learner import observation

    engine = _seeded_engine()
    engine.observe(
        observation(
            ObservationSource.REVERT,
            "prawed",
            at=engine.now(),
            before="prod",
            binding=Binding(BindingScope.APP, "com.tinyspeck.slackmacgap"),
            lexeme_id="lex.prod",
        )
    )
    target = next(lx for lx in engine.lexemes if lx.id == "lex.prod")
    assert target.state.value != "suppressed"


def test_an_old_prior_decays_toward_no_opinion_not_toward_wrong():
    """The docs claim decay makes a memory uncertain rather than wrong. Before
    priors existed that claim was false for any seeded term: its confidence was
    frozen, because its evidence had no date to grow old from."""
    from datetime import UTC, datetime, timedelta

    from lmh.config import Thresholds
    from lmh.domain.models import Confidence
    from lmh.engine.projector import Projector

    projector = Projector(Thresholds(), _weights())
    prior = Confidence(alpha=5.0, beta=1.0)      # mean 0.83, strength 4
    anchor = datetime(2026, 1, 1, tzinfo=UTC)

    fresh = projector.decayed_prior(prior, anchor, anchor)
    aged = projector.decayed_prior(prior, anchor, anchor + timedelta(days=365))

    assert fresh == prior
    assert aged.mean < prior.mean            # less believed
    assert aged.strength < prior.strength    # and less substantiated
    assert aged.mean > 0.5                   # but not flipped to "wrong"


def _weights():
    from lmh.config import EvidenceWeights

    return EvidenceWeights()
