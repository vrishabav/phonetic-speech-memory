"""Build the generated evaluation tier.

The hand-written tier (`tier_c_application.jsonl`, 68 cases) is a
*specification*: each case encodes a judgement about what the product should do,
was written before the engine, and is worth arguing about one at a time. That is
why it is small. Writing three thousand of those by hand would not make them
three thousand judgements; it would make them three thousand copies of a
handful of judgements, and the number would mean nothing.

This tier is a *measurement*. Every case is derived mechanically from committed
inputs, and - the property that makes it worth anything - **its expected
outcome comes from the construction, never from what the engine did**. A case
that says "we took the canonical form `Vaishnavi Kulkarni`, applied the
documented `v→w` confusion to produce `waishnavi Kulkarni`, and put it in a
carrier sentence in Slack" already knows the right answer before the engine is
built. Generating inputs and recording the engine's replies as the expectation
would produce a suite that can never fail, which is the standard way a large
benchmark ends up meaning nothing.

Two consequences worth stating plainly:

**Some of these cases are supposed to be hard, and some will fail.** The
`unseen_mishearing` family in particular asks the system to fix forms that are
in no variant table anywhere. A 100% score there would mean the generator was
too easy, not that the system was perfect. The point of the tier is the
breakdown - per family, per script, per confusion rule - because that is what
says *where* it fails rather than *whether*.

**The personas are not the tuned one.** These cases run against the three
stress personas (24, 104 and 367 terms), two of which have no hand-written
guards at all, plus an Indic persona built from `indic_names.py`. Thresholds
were never tuned on any of them.

    python -m evals.gen.build      # writes evals/data/tier_d_generated.jsonl
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from gen.indic_names import CARRIERS as INDIC_CARRIERS  # noqa: E402
from gen.indic_names import every_name, perturb  # noqa: E402

DATA = ROOT / "evals" / "data"
STRESS = ROOT / "evals" / "stress"
OUT = DATA / "tier_d_generated.jsonl"
PERSONA_OUT = DATA / "personas"

SEED = 20260906

APPS = ["com.tinyspeck.slackmacgap", "com.microsoft.Outlook", "com.microsoft.VSCode"]

CARRIERS = [
    "ask {} to review the change",
    "{} is on call this week",
    "i sent the draft to {}",
    "can you loop in {} on this",
    "{} pushed a fix last night",
    "the ticket is assigned to {}",
    "we should ask {} before shipping",
    "{} said the numbers look wrong",
    "i will sync with {} tomorrow morning",
    "please add {} to the thread",
]

#: Latin confusion rules, the same set the stress generator uses, restated here
#: with their identifiers so a result can be sliced by *which* rule produced it.
#: That slice is the useful one: "the system handles aspiration but not v/w" is
#: an actionable finding; "72% overall" is not.
LATIN_RULES: tuple[tuple[str, str, str], ...] = (
    ("aa", "a", "long-a shortened"),
    ("a", "aa", "short-a lengthened"),
    ("ee", "i", "long-i romanised two ways"),
    ("i", "ee", "long-i romanised two ways (reverse)"),
    ("oo", "u", "long-u romanised two ways"),
    ("u", "oo", "long-u romanised two ways (reverse)"),
    ("th", "t", "aspirated dental flattened"),
    ("t", "th", "plain dental aspirated"),
    ("dh", "d", "aspirated d flattened"),
    ("d", "dh", "plain d aspirated"),
    ("bh", "b", "aspirated b flattened"),
    ("kh", "k", "aspirated k flattened"),
    ("gh", "g", "aspirated g flattened"),
    ("ph", "f", "aspirated p heard as f"),
    ("v", "w", "v/w merger"),
    ("w", "v", "v/w merger (reverse)"),
    ("sh", "s", "sibilant flattened"),
    ("s", "sh", "sibilant sharpened"),
    ("y", "i", "semivowel written as a vowel"),
    ("ai", "ay", "diphthong romanised two ways"),
)

#: Names that are in no persona. Used for the `unknown_name` family: the system
#: must not snap an unfamiliar name to the nearest thing it happens to know.
STRANGERS = [
    "Fiona MacGregor", "Tomas Novak", "Yusuf Demir", "Grace Okonkwo",
    "Henrik Lindqvist", "Paulo Ferreira", "Mei Ling Tan", "Omar Haddad",
    "Beatrix Kovacs", "Sipho Ndlovu", "Ingrid Halvorsen", "Diego Salazar",
]

#: Ordinary English words that also happen to be somebody's term somewhere.
#: Used in their plain sense, they must survive untouched.
ORDINARY_USES = [
    ("kiwi", "i ate a {} for breakfast"),
    ("prod", "do not {} the release before friday"),
    ("were", "the numbers {} set before the run"),
    ("npm", "run {} install and then try again"),
    ("saras", "the {} river is mentioned in the text"),
]


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def app_for(lexeme: dict, index: int) -> str:
    """An application in which this term is actually supposed to apply.

    The first version of this generator picked an app round-robin and ignored
    bindings, which produced eleven cases demanding that an app-bound term be
    corrected inside a *different* app. The engine refused, correctly, and the
    suite recorded eleven harmful interventions that were entirely the
    generator's fault. Generated expectations are only worth anything if the
    generator models the same rules the system does - so a positive case now
    always names a scope the term is bound to, and the mismatch is tested
    deliberately by `scope_mismatch_cases` instead of by accident here.
    """
    for binding in lexeme.get("bindings", [{"scope": "global"}]):
        if binding.get("scope") == "app" and binding.get("ref"):
            return binding["ref"]
    return APPS[index % len(APPS)]


def other_app(lexeme: dict) -> str | None:
    """An application this term is bound *away* from, or None if it is global."""
    bound = {
        b.get("ref")
        for b in lexeme.get("bindings", [])
        if b.get("scope") == "app" and b.get("ref")
    }
    if not bound:
        return None
    return next((app for app in APPS if app not in bound), None)


def apply_latin_rule(name: str, index: int) -> tuple[str, str, str] | None:
    """Apply confusion rule `index % len(LATIN_RULES)` to `name`.

    Deterministic, and returns the rule id so a failure can be traced to the
    phonological confusion that caused it rather than to a case number.
    """
    src, dst, why = LATIN_RULES[index % len(LATIN_RULES)]
    lower = name.lower()
    aspirating = dst == src + "h"

    hits = []
    start = 0
    while True:
        at = lower.find(src, start)
        if at == -1:
            break
        # An aspirating rule must not fire on a consonant that is already
        # aspirated: `s->sh` applied to the `s` of "Deshpande" yields
        # "Deshhpande", a doubled h that appears in no romanisation of anything
        # and that nobody would ever type. The first version of this generator
        # produced dozens of those and then recorded the engine's refusal to
        # match them as a failure, which made `s->sh` look like a hole in the
        # phonetic fold when it was a hole in the generator.
        if not (aspirating and lower[at + len(src) : at + len(src) + 1] == "h"):
            hits.append(at)
        start = at + 1
    if not hits:
        return None
    at = hits[(index // len(LATIN_RULES)) % len(hits)]
    out = name[:at] + dst + name[at + len(src) :]
    if out.lower() == name.lower() or "hh" in out.lower():
        return None
    return out, f"{src}->{dst}", why


# --------------------------------------------------------------------------- #
# The Indic persona
# --------------------------------------------------------------------------- #


def build_indic_persona() -> dict:
    """A memory of native-script names across all nine supported scripts.

    Each term gets one or two forms "the recogniser has already produced",
    generated by the same offset rules, so the `known_variant` family has
    something to hit and the `unseen` family has something left over.
    """
    lexemes = []
    for i, (script, native, latin) in enumerate(every_name()):
        # Scan rule indices until two distinct mishearings are found rather
        # than fixing on two indices: scripts differ in which rules can fire at
        # all (Tamil has no aspirates), so a fixed pair leaves half the persona
        # with no variants and silently shrinks the known-form family.
        variants: list[dict] = []
        for rule_index in range(60):
            if len(variants) >= 2:
                break
            got = perturb(native, script, rule_index)
            if got and got[0] != native and got[0] not in {v["form"] for v in variants}:
                variants.append({"form": got[0], "provenance": "observed", "count": 2})
        lexemes.append(
            {
                "id": f"lex.indic.{i}",
                "canonical": native,
                "kind": "person",
                "variants": variants,
                "state": "active",
                "confidence": {"alpha": 5.0, "beta": 1.0},
                "bindings": [{"scope": "global"}],
                "$script": script,
                "$latin": latin,
            }
        )
    return {
        "$comment": (
            "Native-script persona covering all nine supported Indic blocks. "
            "Generated by evals/gen/build.py; names and rules are committed in "
            "evals/gen/indic_names.py."
        ),
        "persona": {"name": "indic_native", "clock": "2026-01-15T09:00:00+00:00"},
        "lexemes": lexemes,
        "edges": [],
    }


# --------------------------------------------------------------------------- #
# Case families
# --------------------------------------------------------------------------- #


def _case(
    case_id: str,
    cls: str,
    generator: str,
    persona: str,
    expect: str,
    given: dict,
    then: dict,
    rationale: str,
    **extra,
) -> dict:
    return {
        "case_id": case_id,
        "kind": "application",
        "tier": "D",
        "class": cls,
        "generator": generator,
        "persona": persona,
        "expect": expect,
        "authored_before_engine": True,
        "rationale": rationale,
        "given": {"persona": persona, **given},
        "then": then,
        **extra,
    }


def known_variant_cases(persona_name: str, persona: dict, rng, limit: int) -> list[dict]:
    """A form the recogniser has demonstrably produced for this term before.

    The easy family, and it should be near-perfect: if a system cannot apply a
    correction it has already recorded, nothing else it does matters. Failures
    here are retrieval or scoring bugs, not generalisation gaps.
    """
    out = []
    for lexeme in persona["lexemes"]:
        for variant in lexeme.get("variants", []):
            if len(out) >= limit:
                return out
            form = variant["form"]
            if form.lower() == lexeme["canonical"].lower():
                continue
            carrier = CARRIERS[len(out) % len(CARRIERS)]
            app = app_for(lexeme, len(out))
            asr = carrier.format(form.lower())
            formatted = _sentence_case(carrier.format(form)) + "."
            expected = _sentence_case(carrier.format(lexeme["canonical"])) + "."
            out.append(
                _case(
                    f"D1-{persona_name}-{len(out):04d}",
                    "known_variant",
                    "known_variant",
                    persona_name,
                    "apply",
                    {"asr": asr, "formatted": formatted, "app": app},
                    {"output": expected},
                    f"{form!r} is a form already on file for {lexeme['canonical']!r}. "
                    f"Applying it needs no generalisation at all, only retrieval.",
                    lexeme_id=lexeme["id"],
                )
            )
    return out


def unseen_mishearing_cases(persona_name: str, persona: dict, rng, limit: int) -> list[dict]:
    """A form produced by a documented confusion rule and in no variant table.

    The family that decides whether this is a memory or a lookup table. It is
    *meant* to be hard, and a perfect score would mean the rules were too
    timid. Each case records the rule that produced it so the report can say
    which confusions the encoder handles and which it does not.
    """
    out = []
    known = {
        v["form"].lower()
        for lx in persona["lexemes"]
        for v in lx.get("variants", [])
    }
    index = 0
    for lexeme in persona["lexemes"]:
        canonical = lexeme["canonical"]
        for attempt in range(len(LATIN_RULES)):
            if len(out) >= limit:
                return out
            got = apply_latin_rule(canonical, index + attempt)
            index += 1
            if not got:
                continue
            wrong, rule_id, why = got
            if wrong.lower() in known or wrong.lower() == canonical.lower():
                continue
            carrier = CARRIERS[len(out) % len(CARRIERS)]
            app = app_for(lexeme, len(out))
            out.append(
                _case(
                    f"D2-{persona_name}-{len(out):04d}",
                    "unseen_mishearing",
                    "unseen_mishearing",
                    persona_name,
                    "apply",
                    {
                        "asr": carrier.format(wrong.lower()),
                        "formatted": _sentence_case(carrier.format(wrong)) + ".",
                        "app": app,
                    },
                    {"output": _sentence_case(carrier.format(canonical)) + "."},
                    f"{wrong!r} has never been produced for {canonical!r}. It is "
                    f"reachable only by generalising: {why} ({rule_id}).",
                    lexeme_id=lexeme["id"],
                    rule=rule_id,
                )
            )
            break
    return out


def indic_cases(persona: dict, *, unseen: bool, limit: int) -> list[dict]:
    """Native-script cases, one family per known/unseen, tagged by script."""
    out = []
    known_forms = {
        v["form"] for lx in persona["lexemes"] for v in lx.get("variants", [])
    }
    for lexeme in persona["lexemes"]:
        script = lexeme["$script"]
        canonical = lexeme["canonical"]
        carriers = INDIC_CARRIERS[script]

        if unseen:
            surfaces = []
            for rule_index in range(40):
                got = perturb(canonical, script, rule_index)
                if got and got[0] not in known_forms and got[0] != canonical:
                    surfaces.append(got)
                if len(surfaces) >= 3:
                    break
        else:
            surfaces = [(v["form"], "already on file") for v in lexeme.get("variants", [])]

        for surface, why in surfaces:
            if len(out) >= limit:
                return out
            carrier = carriers[len(out) % len(carriers)]
            out.append(
                _case(
                    f"{'D4' if unseen else 'D3'}-{script[:3]}-{len(out):04d}",
                    "indic_script",
                    "indic_unseen" if unseen else "indic_known_variant",
                    "indic_native",
                    "apply",
                    {
                        "asr": carrier.format(surface),
                        "formatted": carrier.format(surface),
                        "app": APPS[len(out) % len(APPS)],
                    },
                    {"output": carrier.format(canonical)},
                    f"{script.title()} script, in and out. {why}. The text is "
                    f"transliterated to a Latin phonetic form and then goes through "
                    f"the same fold, index and policy stack as an English name.",
                    lexeme_id=lexeme["id"],
                    language=script,
                    latin=lexeme["$latin"],
                )
            )
    return out


def prose_cases(persona_name: str, corpus: list[str], limit: int) -> list[dict]:
    """Real English prose containing nothing the system knows.

    The majority of real traffic, and the family where a false positive is
    unshippable rather than merely annoying. Sentences are harvested from
    Python standard-library docstrings, so they are prose this project's author
    did not write.
    """
    out = []
    for sentence in corpus:
        if len(out) >= limit:
            return out
        text = sentence.strip()
        if not (30 <= len(text) <= 140):
            continue
        formatted = _sentence_case(text)
        if not formatted.endswith((".", "?", "!")):
            formatted += "."
        out.append(
            _case(
                f"D5-{persona_name}-{len(out):04d}",
                "no_candidate",
                "ordinary_prose",
                persona_name,
                "abstain",
                {
                    "asr": text.lower(),
                    "formatted": formatted,
                    "app": APPS[len(out) % len(APPS)],
                },
                {"output": formatted, "max_llm_calls": 0},
                "Ordinary prose with nothing known in it. Any change here is a "
                "corruption, and the call must also cost nothing.",
            )
        )
    return out


def unknown_name_cases(persona_name: str, limit: int) -> list[dict]:
    """A name the user has never mentioned. Must not snap to a neighbour."""
    out = []
    for index in range(limit):
        name = STRANGERS[index % len(STRANGERS)]
        carrier = CARRIERS[index % len(CARRIERS)]
        formatted = _sentence_case(carrier.format(name)) + "."
        out.append(
            _case(
                f"D6-{persona_name}-{index:04d}",
                "unknown_term",
                "unknown_name",
                persona_name,
                "abstain",
                {
                    "asr": carrier.format(name.lower()),
                    "formatted": formatted,
                    "app": APPS[index % len(APPS)],
                },
                {"output": formatted},
                f"{name!r} is in no persona. A system that reaches for its nearest "
                f"known name here is worse than one that does nothing.",
            )
        )
    return out


def ordinary_word_cases(persona_name: str, limit: int) -> list[dict]:
    """A word that is also somebody's term, used in its plain sense."""
    out = []
    for index in range(limit):
        word, carrier = ORDINARY_USES[index % len(ORDINARY_USES)]
        formatted = _sentence_case(carrier.format(word)) + "."
        out.append(
            _case(
                f"D7-{persona_name}-{index:04d}",
                "common_word_sense",
                "ordinary_word_sense",
                persona_name,
                "abstain",
                {
                    "asr": carrier.format(word),
                    "formatted": formatted,
                    "app": APPS[index % len(APPS)],
                },
                {"output": formatted},
                f"{word!r} is an ordinary English word here. The guard must hold "
                f"even though a term with that surface exists in memory.",
            )
        )
    return out


def already_canonical_cases(persona_name: str, persona: dict, limit: int) -> list[dict]:
    """The formatter already got it right. Nothing to do, and nothing to spend."""
    out = []
    for lexeme in persona["lexemes"]:
        if len(out) >= limit:
            return out
        carrier = CARRIERS[len(out) % len(CARRIERS)]
        formatted = _sentence_case(carrier.format(lexeme["canonical"])) + "."
        out.append(
            _case(
                f"D8-{persona_name}-{len(out):04d}",
                "already_canonical",
                "already_canonical",
                persona_name,
                "abstain",
                {
                    "asr": carrier.format(lexeme["canonical"].lower()),
                    "formatted": formatted,
                    "app": APPS[len(out) % len(APPS)],
                },
                {"output": formatted, "max_llm_calls": 0},
                f"The text already reads {lexeme['canonical']!r}. A no-op that still "
                f"costs a model call is a bug even though the output is right.",
                lexeme_id=lexeme["id"],
            )
        )
    return out


def verbatim_cases(persona_name: str, persona: dict, limit: int) -> list[dict]:
    """A known wrong-form inside a quotation. Somebody else's words."""
    out = []
    for lexeme in persona["lexemes"]:
        variants = lexeme.get("variants", [])
        if not variants or len(out) >= limit:
            if len(out) >= limit:
                return out
            continue
        form = variants[0]["form"]
        formatted = f'She wrote, "{form} approved it," in the thread.'
        out.append(
            _case(
                f"D9-{persona_name}-{len(out):04d}",
                "verbatim_region",
                "verbatim_region",
                persona_name,
                "abstain",
                {
                    "asr": f"she wrote quote {form} approved it unquote in the thread",
                    "formatted": formatted,
                    "app": app_for(lexeme, len(out)),
                },
                {"output": formatted},
                "Inside a quotation. Correcting somebody else's spelling changes "
                "what they said, which is never this system's call.",
                lexeme_id=lexeme["id"],
            )
        )
    return out


def build_latin_persona() -> dict:
    """The same people, spelled in Latin.

    Exists for one family: the user writes a name in Devanagari, the memory
    holds it in Latin. Retrieval should cross the script boundary; the rewrite
    must not. Without a Latin-canonical persona there is nothing for the
    Devanagari text to *nearly* match, and the case would pass for the wrong
    reason - because nothing was found at all.
    """
    lexemes = []
    for index, (script, _native, latin) in enumerate(every_name()):
        if script != "devanagari":
            continue
        lexemes.append(
            {
                "id": f"lex.latin.{index}",
                "canonical": latin,
                "kind": "person",
                "variants": [],
                "state": "active",
                "confidence": {"alpha": 5.0, "beta": 1.0},
                "bindings": [{"scope": "global"}],
            }
        )
    return {
        "$comment": (
            "Latin spellings of the Devanagari persona, so that cross-script "
            "retrieval has something to find and cross-script rewriting has "
            "something to refuse. Generated by evals/gen/build.py."
        ),
        "persona": {"name": "latin_only", "clock": "2026-01-15T09:00:00+00:00"},
        "lexemes": lexemes,
        "edges": [],
    }


#: A binding on one of these is part of what the term *is*: a channel handle
#: and a service identifier name something that exists inside one application.
#: A binding on anything else records where the evidence happened to arrive.
#: The engine draws the same line, in `policies/context.py`.
APP_NATIVE_KINDS = frozenset({"handle", "code_symbol"})


def scope_mismatch_cases(persona_name: str, persona: dict, limit: int) -> list[dict]:
    """An app-bound term, used inside a different application.

    One construction, two expectations, and which one a term gets is decided by
    what the term is rather than by how it was learned:

    * a **handle or code symbol** names something that exists only inside one
      application, so outside it the memory must stay quiet. `#eng-asr` in an
      email is not a spelling to fix; it is a reference to a channel that is
      not there.
    * a **person, place or piece of jargon** keeps its spelling wherever it is
      typed. The binding says where the user last corrected it, which is a fact
      about the user's afternoon and not about the name. So the correction must
      still be applied, and the case asserts the corrected sentence exactly.

    The earlier version of this family asserted abstention for *every* kind, and
    was wrong for the same reason the engine was wrong: it read a licence into
    an accident. See the report's section on scope.

    The negative half asserts narrowly - not "the text is unchanged" but "this
    term's canonical form does not appear" - because a sentence containing an
    app-bound surname often also contains a globally-bound given name that may
    legitimately be corrected.
    """
    out = []
    for lexeme in persona["lexemes"]:
        if len(out) >= limit:
            return out
        wrong_app = other_app(lexeme)
        variants = lexeme.get("variants", [])
        if not wrong_app or not variants:
            continue
        form = variants[0]["form"]
        if form.lower() == lexeme["canonical"].lower():
            continue
        carrier = CARRIERS[len(out) % len(CARRIERS)]
        formatted = _sentence_case(carrier.format(form)) + "."
        bound_to = lexeme["bindings"][0].get("ref")
        native = lexeme.get("kind") in APP_NATIVE_KINDS
        given = {
            "asr": carrier.format(form.lower()),
            "formatted": formatted,
            "app": wrong_app,
        }
        if native:
            out.append(
                _case(
                    f"D11-{persona_name}-{len(out):04d}",
                    "scope_mismatch",
                    "scope_mismatch",
                    persona_name,
                    "abstain",
                    given,
                    {"must_not_contain": lexeme["canonical"]},
                    f"{lexeme['canonical']!r} is a {lexeme['kind']} bound to {bound_to} - "
                    f"it names something that exists there and nowhere else. In "
                    f"{wrong_app} it must be left alone.",
                    lexeme_id=lexeme["id"],
                )
            )
        else:
            out.append(
                _case(
                    f"D12-{persona_name}-{len(out):04d}",
                    "scope_carryover",
                    "scope_carryover",
                    persona_name,
                    "apply",
                    given,
                    {"output": _sentence_case(carrier.format(lexeme["canonical"])) + "."},
                    f"{lexeme['canonical']!r} is a {lexeme['kind']} whose evidence arrived "
                    f"in {bound_to}. A {lexeme['kind']} keeps its spelling in "
                    f"{wrong_app} too, so the correction must still be made - the "
                    f"binding records where the user was, not where the name is valid.",
                    lexeme_id=lexeme["id"],
                )
            )
    return out


def script_shift_cases(indic: dict, limit: int) -> list[dict]:
    """Native-script text against a Latin-canonical memory.

    Retrieval across scripts is wanted; rewriting across them is not. Fixing
    somebody's spelling is the job - changing the alphabet they chose to write
    in is not.
    """
    latin_equivalents = [
        ("मीरा शर्मा", "Meera Sharma"),
        ("अनिरुद्ध देशपांडे", "Anirudh Deshpande"),
        ("प्रणव जोशी", "Pranav Joshi"),
        ("भावना कुलकर्णी", "Bhavana Kulkarni"),
    ]
    out = []
    for index in range(limit):
        native, latin = latin_equivalents[index % len(latin_equivalents)]
        carrier = INDIC_CARRIERS["devanagari"][index % 3]
        formatted = carrier.format(native)
        out.append(
            _case(
                f"D10-script-{index:04d}",
                "script_shift",
                "script_shift",
                "latin_only",
                "abstain",
                {
                    "asr": formatted,
                    "formatted": formatted,
                    "app": APPS[index % len(APPS)],
                    "memory_overrides": {},
                },
                {"output": formatted},
                f"The memory holds {latin!r} in Latin; the user wrote {native!r} in "
                f"Devanagari. Retrieval may cross scripts - rewriting may not.",
                language="devanagari",
            )
        )
    return out


# --------------------------------------------------------------------------- #


def main() -> int:
    rng = random.Random(SEED)
    PERSONA_OUT.mkdir(parents=True, exist_ok=True)

    indic = build_indic_persona()
    (PERSONA_OUT / "indic_native.json").write_text(
        json.dumps(indic, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (PERSONA_OUT / "latin_only.json").write_text(
        json.dumps(build_latin_persona(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    personas = {
        name: json.loads((STRESS / "personas" / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("small_unseen", "medium_unguarded", "large_unguarded")
    }
    corpus = (STRESS / "neutral_corpus.txt").read_text(encoding="utf-8").splitlines()

    cases: list[dict] = []
    for name, persona in personas.items():
        cases += known_variant_cases(name, persona, rng, limit=160)
        cases += unseen_mishearing_cases(name, persona, rng, limit=200)
        cases += already_canonical_cases(name, persona, limit=60)
        cases += verbatim_cases(name, persona, limit=40)
        cases += scope_mismatch_cases(name, persona, limit=40)

    cases += prose_cases("large_unguarded", corpus, limit=500)
    cases += unknown_name_cases("large_unguarded", limit=120)
    cases += ordinary_word_cases("small_unseen", limit=60)
    cases += indic_cases(indic, unseen=False, limit=120)
    cases += indic_cases(indic, unseen=True, limit=120)
    cases += script_shift_cases(indic, limit=40)

    OUT.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8"
    )

    families: dict[str, int] = {}
    for case in cases:
        families[case["generator"]] = families.get(case["generator"], 0) + 1
    positive = sum(1 for c in cases if c["expect"] == "apply")

    print(f"{len(cases)} generated cases -> {OUT.relative_to(ROOT)}")
    print(f"  {positive} positive, {len(cases) - positive} negative "
          f"({(len(cases) - positive) / len(cases):.0%} negative)")
    for family, count in sorted(families.items(), key=lambda kv: -kv[1]):
        print(f"    {family:<24} {count:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
