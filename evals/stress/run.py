"""Stress tests: the experiments designed to make this system fail.

The 59-case suite in `evals/data/` measures whether the system does the right
thing on cases someone thought of. That is necessary and not sufficient. These
six experiments ask harder questions:

  S1  Does it work on a persona it was NOT tuned against?
  S2  How often does it corrupt ordinary English, at realistic memory sizes?
  S3  Are the thresholds a plateau or a knife-edge?
  S4  Does it survive messy, unpunctuated, disfluent ASR text?
  S5  How does latency scale with memory size?
  S6  Can it fix forms it has NEVER seen - i.e. is phonetic retrieval real?

S6 is the one that decides whether a language model is needed. If phonetic
retrieval handles unseen mishearings, the deterministic engine is the product.
If it does not, the gap is exactly the LLM's job.

Run:  python evals/stress/run.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lmh.adapters.clock.frozen import FrozenClock  # noqa: E402
from lmh.config import Settings, Thresholds  # noqa: E402
from lmh.domain.models import Utterance  # noqa: E402
from lmh.engine.engine import Engine  # noqa: E402
from lmh.seed import load_persona  # noqa: E402

HERE = Path(__file__).resolve().parent
CLOCK = "2026-01-15T09:00:00+00:00"
OFFLINE = Settings(store="store.memory", database_url="memory://")


def engine_for(persona_path: Path, settings: Settings = OFFLINE) -> Engine:
    clock = FrozenClock(CLOCK)
    lexemes, edges = load_persona(persona_path, now=clock.now())
    eng = Engine.build(settings, lexemes=lexemes, edges=edges)
    eng.clock = clock
    eng.load(lexemes=lexemes, edges=edges)
    return eng


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# --------------------------------------------------------------------------- #
# S1 - generalisation to unseen personas
# --------------------------------------------------------------------------- #


def s1_unseen_persona() -> dict:
    """Run the 59 committed cases' *structure* against personas the thresholds
    were never tuned on - specifically, personas with no hand-written guards.

    We cannot reuse the case texts (they name the seed persona's terms), so this
    measures the property that transfers: on sentences that contain a known
    wrong-form, does it fire; on ordinary English, does it stay silent.
    """
    rule("S1  Generalisation: personas the thresholds were never tuned on")
    neutral = (HERE / "neutral_corpus.txt").read_text(encoding="utf-8").splitlines()[:1500]
    out = {}
    for label in ("small_unseen", "medium_unguarded", "large_unguarded"):
        eng = engine_for(HERE / "personas" / f"{label}.json")

        # (a) does it fire on forms it has on file?
        hits = total = 0
        for lexeme in eng.lexemes:
            for variant in lexeme.variants:
                total += 1
                formatted = f"Ask {variant.form.title()} about the rollout."
                result = eng.handle(Utterance("", formatted), record=False)
                if lexeme.canonical in result.output_text:
                    hits += 1

        # (b) does it stay silent on ordinary English?
        fires = 0
        for sentence in neutral:
            result = eng.handle(Utterance("", sentence), record=False)
            if result.output_text != sentence:
                fires += 1

        recall = hits / max(1, total)
        fpr = fires / len(neutral)
        out[label] = {"n_lexemes": len(eng.lexemes), "known_form_recall": round(recall, 4),
                      "false_fires": fires, "neutral_sentences": len(neutral),
                      "false_fire_rate": round(fpr, 5)}
        print(f"  {label:<20} {len(eng.lexemes):>4} lexemes | "
              f"known-form recall {recall:6.1%} | "
              f"false fires {fires:>3}/{len(neutral)} ({fpr:.2%})")
    return out


# --------------------------------------------------------------------------- #
# S2 - false activation on real English
# --------------------------------------------------------------------------- #


def s2_false_activation() -> dict:
    """The safety number. 4000 sentences of real English prose, a 367-term
    memory, and nothing in the text that should ever be corrected.

    Every fire here is a sentence this product would have corrupted."""
    rule("S2  False activation on 4000 sentences of real English prose")
    corpus = (HERE / "neutral_corpus.txt").read_text(encoding="utf-8").splitlines()
    eng = engine_for(HERE / "personas" / "large_unguarded.json")
    fires, gate_opens, examples = 0, 0, []
    started = time.perf_counter()
    for sentence in corpus:
        result = eng.handle(Utterance("", sentence), record=False)
        if result.gate_passed:
            gate_opens += 1
        if result.output_text != sentence:
            fires += 1
            if len(examples) < 12:
                changed = [(r.candidate.span.text, r.replacement) for r in result.applied]
                examples.append({"sentence": sentence, "changes": changed})
    elapsed = time.perf_counter() - started
    print(f"  memory              {len(eng.lexemes)} lexemes")
    print(f"  sentences           {len(corpus)}")
    print(f"  gate opened on      {gate_opens} ({gate_opens / len(corpus):.1%})  <- did any work at all")
    print(f"  CORRUPTED           {fires} ({fires / len(corpus):.2%})  <- would have been wrong")
    print(f"  throughput          {len(corpus) / elapsed:,.0f} sentences/sec")
    if examples:
        print("\n  every false fire:")
        for e in examples:
            print(f"    {e['changes']}")
            print(f"      in: {e['sentence'][:96]}")
    return {"n_lexemes": len(eng.lexemes), "sentences": len(corpus),
            "gate_open_rate": round(gate_opens / len(corpus), 5),
            "false_fires": fires, "false_fire_rate": round(fires / len(corpus), 5),
            "examples": examples}


# --------------------------------------------------------------------------- #
# S3 - threshold sensitivity
# --------------------------------------------------------------------------- #


def s3_threshold_sensitivity() -> dict:
    """Is 98% a plateau or a knife-edge?

    If the committed score only exists at one exact threshold, the numbers are
    an artefact of tuning rather than a property of the design. Sweep the two
    thresholds that matter and see how wide the good region is.
    """
    rule("S3  Threshold sensitivity: plateau or knife-edge?")
    sys.path.insert(0, str(ROOT))
    from evals.harness import load_jsonl, run_application_cases, summarise

    cases = load_jsonl(ROOT / "evals" / "data" / "tier_c_application.jsonl")
    results = {}

    print("\n  apply_score sweep (committed value 0.55)")
    print(f"  {'value':>7} {'pass':>9} {'useful':>7} {'harmful':>8} {'missed':>7}")
    for value in [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]:
        s = OFFLINE.with_(thresholds=Thresholds(apply_score=value))
        summary = summarise(run_application_cases(cases, s), s)
        t, p = summary["totals"], summary["positive_cases"]
        marker = "  <- committed" if value == 0.55 else ""
        print(f"  {value:>7.2f} {t['passed']:>4}/{t['cases']} {p['useful']:>7} "
              f"{p['harmful']:>8} {p['missed']:>7}{marker}")
        results[f"apply_score={value}"] = t["passed"]

    print("\n  retrieval_max_distance sweep (committed value 0.34)")
    print(f"  {'value':>7} {'pass':>9} {'useful':>7} {'harmful':>8} {'false-int':>10}")
    for value in [0.20, 0.26, 0.30, 0.34, 0.38, 0.42, 0.50]:
        s = OFFLINE.with_(thresholds=Thresholds(retrieval_max_distance=value))
        summary = summarise(run_application_cases(cases, s), s)
        t, p, n = summary["totals"], summary["positive_cases"], summary["negative_cases"]
        marker = "  <- committed" if value == 0.34 else ""
        print(f"  {value:>7.2f} {t['passed']:>4}/{t['cases']} {p['useful']:>7} "
              f"{p['harmful']:>8} {n['false_intervention_rate']:>9.1%}{marker}")
        results[f"retrieval_max_distance={value}"] = t["passed"]
    return results


# --------------------------------------------------------------------------- #
# S4 - messy input
# --------------------------------------------------------------------------- #

MESSY = [
    # (description, formatted_text_as_it_would_arrive, must_contain_after)
    ("clean baseline", "Ask Adith Narayanan to review the pull request.", "Aadith Narayanan"),
    ("no punctuation", "ask adith narayanan to review the pull request", "Aadith Narayanan"),
    ("all lowercase", "the sarvam kiwi service is dropping requests", "Kivi"),
    ("ALL CAPS", "ASK ADITH NARAYANAN TO REVIEW THIS", "Aadith Narayanan"),
    ("disfluent", "um so ask uh adith narayanan to like review the pull request", "Aadith Narayanan"),
    ("run-on, two corrections",
     "ok so i spoke to adith narayanan about the vani gateway thing and he said "
     "it's fine but we should check with shreya bhattacharya first before we ship anything",
     "Aadith Narayanan"),
    ("repeated word", "ask ask adith narayanan to review", "Aadith Narayanan"),
    ("trailing filler", "ask adith narayanan to review the pull request you know", "Aadith Narayanan"),
    ("mid-word stutter", "ask ad- adith narayanan to review", "Aadith Narayanan"),
    ("no spaces after comma", "ask adith narayanan,then ping me", "Aadith Narayanan"),
    ("emoji present", "ask adith narayanan to review 🙏", "Aadith Narayanan"),
    ("numbers inline", "ask adith narayanan re ticket 4471 by 5pm", "Aadith Narayanan"),
]

MESSY_NEGATIVE = [
    ("fruit, no punctuation", "i ate a kiwi for breakfast", "kiwi"),
    ("fruit, all caps", "I ATE A KIWI FOR BREAKFAST", "KIWI"),
    ("fruit, disfluent", "um i ate a uh kiwi for breakfast today", "kiwi"),
    ("fruit in a list", "we need kiwi, mango and papaya for the smoothie", "kiwi"),
]


def s4_messy_input() -> dict:
    """Real dictation is not punctuated prose. Does the system survive it?"""
    rule("S4  Messy input: unpunctuated, disfluent, mis-cased, emoji")
    eng = engine_for(ROOT / "evals" / "data" / "persona_seed.json")
    passed = failed = 0
    print("  POSITIVE - should still correct")
    for label, text, expected in MESSY:
        result = eng.handle(Utterance("", text, app="com.tinyspeck.slackmacgap"), record=False)
        ok = expected in result.output_text
        passed += ok
        failed += not ok
        print(f"    {'PASS' if ok else 'FAIL'}  {label:<26} -> {result.output_text[:64]}")
    print("  NEGATIVE - must still leave alone")
    for label, text, must_survive in MESSY_NEGATIVE:
        result = eng.handle(Utterance("", text, app="com.microsoft.Outlook"), record=False)
        ok = must_survive in result.output_text
        passed += ok
        failed += not ok
        print(f"    {'PASS' if ok else 'FAIL'}  {label:<26} -> {result.output_text[:64]}")
    print(f"\n  {passed}/{passed + failed} passed")
    return {"passed": passed, "failed": failed}


# --------------------------------------------------------------------------- #
# S5 - scale
# --------------------------------------------------------------------------- #


def s5_scale() -> dict:
    """Latency and index-build cost as memory grows."""
    rule("S5  Scale: latency vs memory size")
    corpus = (HERE / "neutral_corpus.txt").read_text(encoding="utf-8").splitlines()[:400]
    hit = "Ask Adith Narayanan to review the pull request."
    out = {}
    print(f"  {'lexemes':>8} {'build ms':>9} {'p50 miss':>9} {'p95 miss':>9} {'p50 hit':>8}")
    for label in ("small_unseen", "medium_unguarded", "large_unguarded"):
        path = HERE / "personas" / f"{label}.json"
        clock = FrozenClock(CLOCK)
        lexemes, edges = load_persona(path, now=clock.now())
        eng = Engine.build(OFFLINE, lexemes=lexemes, edges=edges)
        eng.clock = clock
        t0 = time.perf_counter()
        eng.load(lexemes=lexemes, edges=edges)
        build_ms = (time.perf_counter() - t0) * 1000

        miss = []
        for sentence in corpus:
            t0 = time.perf_counter()
            eng.handle(Utterance("", sentence), record=False)
            miss.append((time.perf_counter() - t0) * 1000)
        hits = []
        for _ in range(200):
            t0 = time.perf_counter()
            eng.handle(Utterance("", hit), record=False)
            hits.append((time.perf_counter() - t0) * 1000)

        miss.sort()
        row = {"n": len(lexemes), "build_ms": round(build_ms, 2),
               "p50_miss_ms": round(statistics.median(miss), 3),
               "p95_miss_ms": round(miss[int(len(miss) * 0.95)], 3),
               "p50_hit_ms": round(statistics.median(hits), 3)}
        out[label] = row
        print(f"  {row['n']:>8} {row['build_ms']:>9.2f} {row['p50_miss_ms']:>9.3f} "
              f"{row['p95_miss_ms']:>9.3f} {row['p50_hit_ms']:>8.3f}")
    return out


# --------------------------------------------------------------------------- #
# S6 - unseen mishearings: does phonetic retrieval actually work?
# --------------------------------------------------------------------------- #


def s6_unseen_mishearings() -> dict:
    """THE decisive experiment.

    Every case here is a mishearing the system has never seen, of a term it
    knows, produced by a documented Indic confusion rule. The variant table
    cannot help. Only phonetics can.

    Three outcomes are counted separately, because they have very different
    costs:
      fixed       - correct canonical form produced
      missed      - left unchanged (annoying, harmless)
      wrong       - changed to a DIFFERENT term (actively damaging)
    """
    rule("S6  Held-out mishearings: can it fix forms it has never seen?")
    cases = [json.loads(line) for line in
             (HERE / "mishearings.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    eng = engine_for(HERE / "personas" / "medium_unguarded.json")

    fixed = missed = wrong = 0
    retrieved = 0
    misses, wrongs = [], []
    for case in cases:
        result = eng.handle(
            Utterance(case["asr"], case["formatted"], app=case["app"]), record=False
        )
        if any(r.candidate.lexeme.id == case["lexeme_id"] for r in result.resolutions):
            retrieved += 1
        if case["canonical"] in result.output_text:
            fixed += 1
        elif result.output_text == case["formatted"]:
            missed += 1
            if len(misses) < 10:
                misses.append((case["heard"], case["canonical"]))
        else:
            wrong += 1
            if len(wrongs) < 10:
                wrongs.append((case["heard"], case["canonical"], result.output_text))

    n = len(cases)
    print(f"  cases                 {n} unseen mishearings, memory of {len(eng.lexemes)} terms")
    print(f"  retrieved at all      {retrieved:>4} ({retrieved / n:6.1%})  <- did the index find it")
    print(f"  FIXED                 {fixed:>4} ({fixed / n:6.1%})")
    print(f"  missed (left alone)   {missed:>4} ({missed / n:6.1%})")
    print(f"  WRONG (corrupted)     {wrong:>4} ({wrong / n:6.1%})")
    if misses:
        print("\n  sample misses - retrieval or scoring did not reach them:")
        for heard, canonical in misses:
            print(f"    {heard:<30} should have become  {canonical}")
    if wrongs:
        print("\n  sample corruptions - these are the dangerous ones:")
        for heard, canonical, got in wrongs:
            print(f"    {heard:<24} wanted {canonical:<26} got: {got[:46]}")
    return {"n": n, "retrieved": retrieved, "retrieval_rate": round(retrieved / n, 4),
            "fixed": fixed, "fixed_rate": round(fixed / n, 4),
            "missed": missed, "wrong": wrong, "wrong_rate": round(wrong / n, 4),
            "sample_misses": misses, "sample_wrongs": wrongs}


def main() -> int:
    report = {
        "s1_generalisation": s1_unseen_persona(),
        "s2_false_activation": s2_false_activation(),
        "s3_threshold_sensitivity": s3_threshold_sensitivity(),
        "s4_messy_input": s4_messy_input(),
        "s5_scale": s5_scale(),
        "s6_unseen_mishearings": s6_unseen_mishearings(),
    }
    out = ROOT / "evals" / "results" / "stress" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
