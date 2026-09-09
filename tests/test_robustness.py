"""Regression tests for the failures the stress suite found.

Every test here corresponds to a real, measured defect. They are separated from
`test_engine.py` because they are not about mechanisms - they are about
behaviours that were once wrong on data nobody had thought to write a case for,
and must never be wrong again.

The measurements behind them live in `evals/stress/`; these are the cheap
guards that run on every commit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from psm.adapters.clock.frozen import FrozenClock
from psm.adapters.phonetics.dmetaphone import DoubleMetaphoneEncoder, PhoneticStack
from psm.adapters.phonetics.indic import fold
from psm.config import Settings
from psm.domain.enums import GuardKind
from psm.domain.models import Utterance
from psm.engine.engine import Engine
from psm.engine.guards import is_common, looks_like_short_acronym
from psm.seed import load_persona

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "evals" / "stress"
CLOCK = "2026-01-15T09:00:00+00:00"


def build(persona_path: Path) -> Engine:
    clock = FrozenClock(CLOCK)
    lexemes, edges = load_persona(persona_path, now=clock.now())
    settings = Settings(store="store.memory", database_url="memory://")
    engine = Engine.build(settings, lexemes=lexemes, edges=edges)
    engine.clock = clock
    engine.load(lexemes=lexemes, edges=edges)
    return engine


@pytest.fixture(scope="module")
def seeded() -> Engine:
    return build(ROOT / "evals" / "data" / "persona_seed.json")


@pytest.fixture(scope="module")
def large() -> Engine:
    return build(STRESS / "personas" / "large_unguarded.json")


# --------------------------------------------------------------------------- #
# Romanisation folding
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Vishwanathan", "Viswanathan"),   # sibilant
        ("Vishwanathan", "Vishvanathan"),  # v/w
        ("Aadith", "Adith"),               # vowel length + aspiration
        ("Tanvi", "Thanvi"),               # aspiration
        ("Tanvi", "Tanwi"),                # v/w
        ("Bhaskar", "Bhaashkar"),          # vowel length
        ("Vaidyanathan", "Vaidianathan"),  # y/i after consonant
        ("Rukmini", "Rukmeeni"),           # long i
        ("Dhruv", "Dhroov"),               # long u
    ],
)
def test_romanisations_of_one_name_converge(a, b):
    """The whole point of the fold. If these diverge, the index cannot find the
    name and nothing downstream gets a chance."""
    assert fold(a.casefold()) == fold(b.casefold())


@pytest.mark.parametrize(
    ("a", "b"),
    [("Kaveri", "Meenakshi"), ("Sengupta", "Kulkarni"), ("Bengaluru", "Mysuru")],
)
def test_the_fold_does_not_collapse_genuinely_different_names(a, b):
    assert fold(a.casefold()) != fold(b.casefold())


def test_folded_names_share_a_blocking_key():
    encoder = DoubleMetaphoneEncoder()
    assert set(encoder.encode("Vishwanathan")) & set(encoder.encode("Viswanathan"))
    assert set(encoder.encode("Aadith Narayanan")) & set(encoder.encode("Adith Narayan"))


# --------------------------------------------------------------------------- #
# Automatic common-word guarding
# --------------------------------------------------------------------------- #


def test_ordinary_words_are_recognised_as_ordinary():
    assert is_common("were") and is_common("kiwi") and is_common("start")
    assert not is_common("Sengupta") and not is_common("vaani-gateway")


def test_a_run_of_ordinary_words_is_ordinary_text():
    """'is an' sounds like 'Ishaan' and rewrote 14 sentences in 1,500 before
    this existed. Neither token alone is the span being matched, so a
    single-word check cannot see it."""
    assert is_common("is an")
    assert not is_common("Kaveri Sengupta")


def test_short_acronyms_are_guarded_on_sight():
    assert looks_like_short_acronym("WER") and looks_like_short_acronym("CTC")
    assert not looks_like_short_acronym("MLOps") and not looks_like_short_acronym("Kivi")


def test_guards_are_synthesised_without_being_written(large):
    """A user does not curate guard lists. The persona this runs against has no
    hand-written guards at all."""
    guarded = [lx for lx in large.lexemes if any(
        g.kind is GuardKind.COMMON_WORD for g in lx.guards)]
    assert guarded, "no guards were synthesised for a memory full of acronyms"
    assert all(
        g.payload.get("synthesised")
        for lx in guarded for g in lx.guards if g.kind is GuardKind.COMMON_WORD
    )


def test_a_handwritten_guard_is_never_overwritten(seeded):
    kivi = next(lx for lx in seeded.lexemes if lx.canonical == "Kivi")
    common = [g for g in kivi.guards if g.kind is GuardKind.COMMON_WORD]
    assert len(common) == 1
    assert not common[0].payload.get("synthesised")


# --------------------------------------------------------------------------- #
# The false positives that were actually measured
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "sentence",
    [
        "If none were set, return an error message.",              # were -> WER
        "number is the number of substitutions that were made.",
        "Start a socket server, call back for each client.",        # Start -> Siddharth
        "It should return an ASCII string that will be sent to the server.",  # sent -> Sandhya
        "On Windows kill() is an alias for terminate().",           # is an -> Ishaan
        "Finally, StringIO is an in-memory stream for text.",
    ],
)
def test_ordinary_english_survives_a_large_memory(large, sentence):
    """Each of these was corrupted by a real run over 4,000 sentences of prose.
    A sound-alike is not evidence."""
    assert large.handle(Utterance("", sentence), record=False).output_text == sentence


def test_a_common_word_needs_to_have_actually_been_heard(seeded):
    """'kiwi' has genuinely been produced for 'Kivi' six times, so with support
    it may fire. Nothing has ever been produced for a name that merely sounds
    like an English word, so that may not - however good the context looks."""
    with_support = seeded.handle(
        Utterance("", "The Sarvam Kiwi service is dropping requests."),
        record=False,
    )
    assert "Kivi" in with_support.output_text

    without = seeded.handle(Utterance("", "I ate a kiwi for breakfast."), record=False)
    assert without.output_text == "I ate a kiwi for breakfast."


# --------------------------------------------------------------------------- #
# Messy input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ask adith narayanan to review the pull request", "Aadith Narayanan"),
        ("ASK ADITH NARAYANAN TO REVIEW THIS", "Aadith Narayanan"),
        ("um so ask uh adith narayanan to like review it", "Aadith Narayanan"),
        ("ask ad- adith narayanan to review", "Aadith Narayanan"),
        ("ask adith narayanan to review 🙏", "Aadith Narayanan"),
        ("ask adith narayanan,then ping me", "Aadith Narayanan"),
    ],
)
def test_unpunctuated_and_disfluent_input_still_works(seeded, text, expected):
    """Real dictation is not tidy prose. If the system only works on clean
    sentences it does not work."""
    assert expected in seeded.handle(
        Utterance(text, text, app="com.tinyspeck.slackmacgap"), record=False
    ).output_text


@pytest.mark.parametrize(
    "text",
    [
        "i ate a kiwi for breakfast",
        "I ATE A KIWI FOR BREAKFAST",
        "we need kiwi, mango and papaya for the smoothie",
    ],
)
def test_negatives_survive_messy_input_too(seeded, text):
    assert seeded.handle(
        Utterance(text, text, app="com.microsoft.Outlook"), record=False
    ).output_text == text


# --------------------------------------------------------------------------- #
# Held-out mishearings - the headline capability
# --------------------------------------------------------------------------- #


def test_unseen_mishearings_are_mostly_fixed():
    """94 mishearings of known names that are in NO variant table, generated
    from documented Indic romanisation rules. This is the number that says
    whether phonetic retrieval is real or decorative.

    The bar is set below the measured value on purpose: this is a regression
    guard, not a target. Current measurement is 72.3% fixed, 2.1% corrupted.
    """
    engine = build(STRESS / "personas" / "medium_unguarded.json")
    cases = [
        json.loads(line)
        for line in (STRESS / "mishearings.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fixed = wrong = 0
    for case in cases:
        result = engine.handle(
            Utterance(case["asr"], case["formatted"], app=case["app"]), record=False
        )
        if case["canonical"] in result.output_text:
            fixed += 1
        elif result.output_text != case["formatted"]:
            wrong += 1
    assert fixed / len(cases) >= 0.65, f"only {fixed / len(cases):.1%} fixed"
    assert wrong / len(cases) <= 0.05, f"{wrong / len(cases):.1%} corrupted"


def test_the_gate_still_costs_nothing_at_scale(large):
    """Adding the fold made every key computation more expensive. The gate must
    still exit without doing real work on ordinary text."""
    sentences = (STRESS / "neutral_corpus.txt").read_text(encoding="utf-8").splitlines()[:300]
    calls = sum(
        large.handle(Utterance("", s), record=False).cost.llm_calls for s in sentences
    )
    assert calls == 0


# --------------------------------------------------------------------------- #
# Indic scripts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("native", "roman", "script"),
    [
        ("ठीक है", "theek hai", "Devanagari"),
        ("आदित्य", "Aaditya", "Devanagari"),
        ("बेंगलुरु", "Bengaluru", "Devanagari"),
        ("অনন্যা", "Ananya", "Bengali"),
        ("విశ్వనాథన్", "Vishwanathan", "Telugu"),
        ("ವಿಶ್ವನಾಥನ್", "Vishwanathan", "Kannada"),
        ("விஸ்வநாதன்", "Vishwanathan", "Tamil"),
        ("વિશ્વનાથન", "Vishwanathan", "Gujarati"),
        ("ଵିଶ୍ୱନାଥନ", "Vishwanathan", "Odia"),
        ("മീനാക്ഷി", "Meenakshi", "Malayalam"),
    ],
)
def test_a_name_is_findable_across_scripts(native, roman, script):
    """One person, one memory, whichever alphabet the recogniser reached for.

    Without this, a user who dictates Hindi some days and romanised Hindi other
    days ends up with two half-learned entries for one colleague.
    """
    encoder = DoubleMetaphoneEncoder()
    stack = PhoneticStack()
    assert set(encoder.encode(native)) & set(encoder.encode(roman)), f"{script}: no shared key"
    assert stack.distance(native, roman) <= 0.34, f"{script}: too far apart to retrieve"


@pytest.mark.parametrize(
    ("a", "b"),
    [("आदित्य", "श्रेया"), ("कीवी", "Kevin"), ("बेंगलुरु", "Mysuru"), ("मीरा", "नीरा")],
)
def test_different_names_stay_apart_across_scripts(a, b):
    assert PhoneticStack().distance(a, b) > 0.34


def test_indic_combining_marks_stay_inside_their_token():
    """`\\w` does not match matras, so "शर्मा" tokenised as ['शर', 'म'] and a
    replacement left a dangling vowel sign: मीरा शर्माा."""
    from psm.engine.text import tokenize

    assert [t.text for t in tokenize("मीरा शर्मा को")] == ["मीरा", "शर्मा", "को"]


def test_indic_text_is_corrected_within_its_own_script(seeded):
    result = seeded.handle(
        Utterance("", "मिरा शर्मा को भेज दो।", app="com.tinyspeck.slackmacgap"), record=False
    )
    assert result.output_text == "मीरा शर्मा को भेज दो।"


def test_the_alphabet_is_never_swapped(seeded):
    """Cross-script retrieval is deliberate; cross-script rewriting is not.
    Splicing a Latin name into a Hindi sentence is an alphabet change, and
    nothing in the evidence says the user wanted one."""
    hindi = "आदित्य नारायणन को पीआर भेज दो।"
    assert seeded.handle(Utterance("", hindi), record=False).output_text == hindi
    roman = "Ask Meera Sharma to review it."
    assert seeded.handle(Utterance("", roman), record=False).output_text == roman


def test_code_switched_text_is_corrected_per_span(seeded):
    """Hindi and English in one sentence, which is what Kivi actually produces.
    The English term is fixed; the Devanagari around it is untouched."""
    result = seeded.handle(
        Utterance("", "मैंने Kiwi service को restart किया।", app="com.tinyspeck.slackmacgap"),
        record=False,
    )
    assert result.output_text == "मैंने Kivi service को restart किया।"


def test_unsupported_scripts_abstain_rather_than_guess():
    """Arabic, Han, Cyrillic are outside the nine ISCII-aligned blocks. The
    right answer is no keys, not bad keys."""
    encoder = DoubleMetaphoneEncoder()
    assert encoder.encode("مرحبا") == ()
    assert encoder.encode("你好") == ()


# --------------------------------------------------------------------------- #
# Fold coverage found by the generated tier
#
# Both of these were holes the 68-case suite could not see, because every one of
# its cases matches a form somebody wrote down by hand. Running 1,842 derived
# cases and slicing the result *by confusion rule* made them obvious: `sh->s`
# passed 100% while `s->sh` passed 48%, and `ph` names failed across seven
# scripts at once. A single pass rate would have shown neither.
# --------------------------------------------------------------------------- #


def test_p_ph_and_f_are_one_bucket():
    """`फ` is /p_h/. It is written "ph", heard "f", and spelled "p" by people in
    a hurry. Collapsing ph->f without collapsing f->p left "Patil" and "Phatil"
    in different blocking buckets."""
    from psm.adapters.phonetics.indic import fold

    assert fold("patil") == fold("phatil") == fold("fatil")
    assert fold("deepak") == fold("deephak")
    assert fold("padmaja") == fold("phadmaja")


def test_y_and_i_alternate_next_to_vowels_too():
    """The rule fired only after a consonant, which is not where `y` sits in
    Iyer, Iyengar or Yashodhara - the names it most needed to handle."""
    from psm.adapters.phonetics.indic import fold

    assert fold("iyer") == fold("iier")
    assert fold("iyengar") == fold("iiengar")
    assert fold("yashodhara") == fold("iashodhara")
    assert fold("vaidyanathan") == fold("vaidianathan")


def test_the_fold_is_idempotent():
    """It is applied to both sides of every comparison, so a second application
    must be a no-op or the index and the query could disagree."""
    from psm.adapters.phonetics.indic import fold

    for word in (
        "phatil", "iyer", "vishwanathan", "aadith", "keerthana",
        "bandyopadhyay", "the", "should", "kiwi",
    ):
        once = fold(word)
        assert fold(once) == once, word


def test_a_veto_outranks_a_proposal_in_the_reported_reason():
    """Reporting the weakest reason hid a working script_fit veto behind an
    unrelated single-observation proposal on a shorter span."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from evals.harness import pick_reason

    from psm.adapters.clock.frozen import FrozenClock
    from psm.config import Settings
    from psm.domain.models import Utterance
    from psm.engine.engine import Engine
    from psm.seed import load_persona

    clock = FrozenClock("2026-01-15T09:00:00+00:00")
    lexemes, edges = load_persona(root / "evals/data/persona_seed.json", now=clock.now())
    engine = Engine.build(Settings(store="store.memory"), lexemes=lexemes, edges=edges)
    engine.clock = clock
    engine.load(lexemes=lexemes, edges=edges)

    text = "Ask Meera Sharma to review it."
    adjudication = engine.handle(
        Utterance(asr_text=text.lower(), formatted_text=text, app="com.tinyspeck.slackmacgap"),
        record=False,
    )
    assert adjudication.output_text == text, "Latin text must not become Devanagari"
    assert pick_reason(adjudication) == "script_mismatch"


def test_the_generated_tier_holds_its_negative_families():
    """The cheap half of the generated tier, run inline. The positive families
    take a few seconds and live in `make eval-generated`; the negative ones are
    the ones whose regression would be unshippable, so they run in `make test`."""
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from evals.generated import run

    from psm.config import Settings

    cases = [
        json.loads(line)
        for line in (root / "evals/data/tier_d_generated.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    negative = [c for c in cases if c["expect"] != "apply"]
    assert len(negative) > 900, "the negative half of the generated tier has shrunk"

    results = run(negative, Settings(store="store.memory", database_url="memory://"))
    harmful = [r for r in results if r.outcome == "harmful_intervention"]
    assert not harmful, (
        f"{len(harmful)} false interventions, e.g. "
        f"{[(r.case_id, r.formatted, r.actual_output) for r in harmful[:3]]}"
    )


def test_b_and_v_are_alternates_in_every_script_that_has_both():
    """Eight of the nine remaining generated-tier failures were this one letter.

    ब/व confusion was modelled as a Bengali peculiarity because Bengali merged
    the sounds outright. It is not: any recogniser choosing between the two
    makes the same mistake, and the generated tier found it failing identically
    in Devanagari, Telugu and Malayalam.
    """
    from psm.adapters.phonetics.dmetaphone import PhoneticStack
    from psm.adapters.phonetics.indic_script import readings

    stack = PhoneticStack()

    # A single ambiguous letter: the two spellings share a reading outright.
    for native, misheard in (("भावना", "भाबना"), ("प्रणव", "प्रणब")):
        assert set(readings(native)) & set(readings(misheard)), (
            f"{native} and {misheard} share no reading"
        )

    # Two ambiguous letters in one word is the harder case, and all-or-nothing
    # alternation does not cover it: swapping every occurrence turns वैष्णवी
    # into "baishnabii" while the recogniser's actual error is "baishnavii" -
    # one letter, not both. Readings are therefore emitted per combination.
    for native, misheard in (
        ("वैष्णवी", "बैष्णवी"),
        ("వెంకటేశ్వర్లు", "బెంకటేశ్వర్లు"),
    ):
        assert set(readings(native)) & set(readings(misheard)), (
            f"{native} and {misheard} share no reading"
        )
        assert stack.distance(native, misheard) < 0.34, (
            f"{native} and {misheard} are beyond retrieval distance"
        )


def test_readings_stay_bounded():
    """This is a blocking function: an unbounded bucket costs latency on every
    utterance. The combinatorial expansion is capped rather than open-ended."""
    from psm.adapters.phonetics.indic_script import readings

    # Six ambiguous letters would be 64 combinations without the cap.
    crowded = "बबबवववा"
    assert len(readings(crowded)) <= 16, len(readings(crowded))
    assert len(readings("मीरा शर्मा")) <= 4


def test_tamil_is_deliberately_excluded_from_the_b_v_alternation():
    """Tamil has one labial approximant, so an alternate reading would widen the
    blocking bucket for a confusion the script cannot express."""
    from psm.adapters.phonetics.indic_script import SCRIPT_AMBIGUITY

    assert 0x0B80 not in SCRIPT_AMBIGUITY
    assert 0x0900 in SCRIPT_AMBIGUITY


# --------------------------------------------------------------------------- #
# What a binding means
#
# The engine used to answer two different questions with one veto: "is this
# term applicable here?" and "which of two rival terms did the user mean?". A
# binding is created from whichever application the user happened to be typing
# in when the evidence arrived, so treating it as an exclusive licence lost
# corrections the memory demonstrably knew how to make. The veto now belongs
# only to terms whose binding is part of what they are.
# --------------------------------------------------------------------------- #


def test_a_persons_spelling_survives_a_change_of_application(seeded):
    """Shreya Menon's evidence arrived in Mail. Her name is spelled the same way
    in Slack, and the memory holds an exact observed form for the mishearing."""
    out = seeded.handle(
        Utterance(
            asr_text="ask shreya menan for the revised quote",
            formatted_text="Ask Shreya Menan for the revised quote.",
            app="com.tinyspeck.slackmacgap",
        )
    )
    assert out.output_text == "Ask Shreya Menon for the revised quote."


def test_an_app_native_handle_still_refuses_to_travel(seeded):
    """The other half of the same rule. `#eng-asr` names a channel that exists
    in Slack and nowhere else, so in Mail it is not a spelling to fix."""
    out = seeded.handle(
        Utterance(
            asr_text="i posted the trace in hash eng asr",
            formatted_text="I posted the trace in hash eng asr.",
            app="com.microsoft.Outlook",
        )
    )
    assert out.output_text == "I posted the trace in hash eng asr."
    reasons = {str(r.reason) for r in out.resolutions}
    assert "out_of_scope" in reasons, reasons


def test_scope_is_not_allowed_to_break_a_genuine_ambiguity(seeded):
    """Two people, one sound, and only one of them in scope. The in-scope one
    does *not* win by default: which colleague was meant is not decided by
    which window is open, and naming the wrong one is the worst thing this
    system can do."""
    out = seeded.handle(
        Utterance(
            asr_text="ask shreya to send the deck across",
            formatted_text="Ask Shreya to send the deck across.",
            app="com.tinyspeck.slackmacgap",
        )
    )
    assert out.output_text == "Ask Shreya to send the deck across."
    assert "ambiguous_conflict" in {str(r.reason) for r in out.resolutions}


def test_a_superseded_span_says_it_was_superseded(seeded):
    """An explanation bug, and the kind this project cannot afford. When the
    longer span 'Shreya Menan' has already matched, the shorter 'Shreya' did
    not fail because nothing could tell the two names apart - it failed because
    a better reading of the same words already won. Saying 'nothing here
    decides between them' while the next token decides it is untrue."""
    out = seeded.handle(
        Utterance(
            asr_text="ask shreya menan for the revised quote",
            formatted_text="Ask Shreya Menan for the revised quote.",
            app="com.tinyspeck.slackmacgap",
        )
    )
    dropped = [r for r in out.resolutions if r.candidate.span.text == "Shreya"]
    assert dropped, [r.candidate.span.text for r in out.resolutions]
    assert str(dropped[0].reason) == "superseded_by_longer_span"
