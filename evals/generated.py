"""Run the generated tier, and report where it fails rather than whether.

The hand-written tier answers "does the system do the right thing in the
situations we specified?" - 68 cases, each argued for. This tier answers a
different question: "across seventeen hundred mechanically-derived situations,
*which kinds* does it get wrong?" A single pass rate over this many cases would
be the least useful number in the repository, so the runner reports:

  * per family - is the failure in retrieval, in generalisation, or in a guard?
  * per confusion rule - which phonological confusions the encoder survives
  * per script - whether the nine Indic blocks really do behave alike
  * per persona - whether behaviour degrades as memory grows from 24 to 367

and it separates the two error costs throughout, because they are not
comparable: a missed correction is an annoyance, a corrupted one is
unshippable.

One structural difference from `harness.py`: cases are grouped by persona and
one engine is built per group. Building 1,772 engines takes about a minute and
buys nothing, since a case that pins no memory override cannot affect the next.
Cases that *do* override memory get their own engine, so isolation is preserved
exactly where it matters.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from psm.adapters.clock.frozen import FrozenClock  # noqa: E402
from psm.config import Settings  # noqa: E402
from psm.domain.models import Utterance  # noqa: E402
from psm.engine.engine import Engine  # noqa: E402
from psm.seed import load_persona  # noqa: E402

DATA = ROOT / "evals" / "data"
STRESS = ROOT / "evals" / "stress"
CASES = DATA / "tier_d_generated.jsonl"
CLOCK = "2026-01-15T09:00:00+00:00"

USEFUL = "useful_intervention"
MISSED = "missed_intervention"
HARMFUL = "harmful_intervention"
CORRECT_ABSTENTION = "correct_abstention"


@dataclass
class GenResult:
    case_id: str
    cls: str
    generator: str
    persona: str
    expect: str
    outcome: str
    passed: bool
    asr: str
    formatted: str
    expected_output: str
    actual_output: str
    actual_reason: str
    llm_calls: int
    latency_ms: float
    rule: str = ""
    language: str = "latin"
    trace: list = field(default_factory=list)
    rationale: str = ""


def find_persona(name: str) -> dict:
    """Personas live in two places for a reason: the stress personas predate
    this tier and are shared with `evals/stress/run.py`, while the generated
    ones are outputs of `evals/gen/build.py`. Both are committed."""
    for candidate in (DATA / "personas" / f"{name}.json", STRESS / "personas" / f"{name}.json"):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no persona {name!r} in evals/data/personas or evals/stress/personas")


def _engine_for(persona: dict, settings: Settings) -> Engine:
    clock = FrozenClock(persona["persona"].get("clock") or CLOCK)
    lexemes, edges = load_persona(persona, now=clock.now())
    engine = Engine.build(settings, lexemes=lexemes, edges=edges)
    engine.clock = clock
    engine.load(lexemes=lexemes, edges=edges)
    return engine


def run(cases: list[dict], settings: Settings) -> list[GenResult]:
    from evals.harness import pick_reason

    by_persona: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        by_persona[case["persona"]].append(case)

    results: list[GenResult] = []
    for persona_name, group in by_persona.items():
        persona = find_persona(persona_name)
        engine = _engine_for(persona, settings)

        for case in group:
            given, then = case["given"], case["then"]
            utterance = Utterance(
                asr_text=given.get("asr", ""),
                formatted_text=given.get("formatted", ""),
                app=given.get("app"),
                utterance_id=case["case_id"],
            )
            started = time.perf_counter()
            adjudication = engine.handle(utterance, record=False)
            latency = (time.perf_counter() - started) * 1000.0

            actual = adjudication.output_text
            # Two assertion shapes. Most cases pin the exact output. A
            # `must_not_contain` case pins only that one specific term did not
            # get applied, because the sentence may legitimately contain another
            # term that should be - asserting the whole string would fail for a
            # reason unrelated to what the case is testing.
            if "must_not_contain" in then:
                forbidden = then["must_not_contain"]
                expected = f"(anything without {forbidden!r})"
                text_ok = forbidden not in actual
            else:
                expected = then["output"]
                text_ok = actual == expected
            intervened = actual != given.get("formatted", "")

            if case["expect"] == "apply":
                outcome = USEFUL if text_ok else (HARMFUL if intervened else MISSED)
            else:
                outcome = CORRECT_ABSTENTION if text_ok else HARMFUL

            passed = outcome in {USEFUL, CORRECT_ABSTENTION}
            budget = then.get("max_llm_calls")
            if budget is not None and adjudication.cost.llm_calls > budget:
                passed = False

            results.append(
                GenResult(
                    case_id=case["case_id"],
                    cls=case["class"],
                    generator=case["generator"],
                    persona=persona_name,
                    expect=case["expect"],
                    outcome=outcome,
                    passed=passed,
                    asr=given.get("asr", ""),
                    formatted=given.get("formatted", ""),
                    expected_output=expected,
                    actual_output=actual,
                    actual_reason=pick_reason(adjudication),
                    llm_calls=adjudication.cost.llm_calls,
                    latency_ms=latency,
                    rule=case.get("rule", ""),
                    language=case.get("language", "latin"),
                    rationale=case.get("rationale", ""),
                    trace=_trace(adjudication),
                )
            )
    return results


def _trace(adjudication) -> list:
    """A compact trace. The full policy tables are recorded for the hand-written
    tier; storing them for 1,772 cases would produce a file nobody opens."""
    return [
        {
            "verdict": str(r.verdict),
            "span": r.candidate.span.text,
            "canonical": r.candidate.lexeme.canonical,
            "matched_via": r.candidate.matched_via,
            "score": round(r.score, 3),
            "reason": str(r.reason),
            "replacement": r.replacement,
            "vetoed_by": [
                o.policy for o in r.outcomes if str(o.signal) == "veto"
            ],
        }
        for r in adjudication.resolutions
    ]


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _slice(results: list[GenResult], key) -> dict[str, dict]:
    grouped: dict[str, list[GenResult]] = defaultdict(list)
    for r in results:
        value = key(r)
        if value:
            grouped[value].append(r)
    out = {}
    for name, rows in sorted(grouped.items()):
        outcomes = Counter(r.outcome for r in rows)
        out[name] = {
            "n": len(rows),
            "passed": sum(1 for r in rows if r.passed),
            "pass_rate": round(sum(1 for r in rows if r.passed) / len(rows), 4),
            "useful": outcomes.get(USEFUL, 0),
            "missed": outcomes.get(MISSED, 0),
            "harmful": outcomes.get(HARMFUL, 0),
            "correct_abstention": outcomes.get(CORRECT_ABSTENTION, 0),
        }
    return out


def summarise(results: list[GenResult], settings: Settings) -> dict:
    negatives = [r for r in results if r.expect != "apply"]
    harmful = sum(1 for r in negatives if r.outcome == HARMFUL)
    latencies = sorted(r.latency_ms for r in results)

    def pct(f):
        return round(latencies[min(len(latencies) - 1, int(len(latencies) * f))], 3)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "settings": settings.describe(),
        "totals": {
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "pass_rate": round(sum(1 for r in results if r.passed) / max(1, len(results)), 4),
        },
        "interventions": dict(Counter(r.outcome for r in results)),
        "negative_cases": {
            "n": len(negatives),
            "false_intervention": harmful,
            "false_intervention_rate": round(harmful / max(1, len(negatives)), 4),
        },
        "cost": {
            "llm_calls_total": sum(r.llm_calls for r in results),
            "zero_call_cases": sum(1 for r in results if r.llm_calls == 0),
        },
        "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": round(latencies[-1], 3)},
        "by_family": _slice(results, lambda r: r.generator),
        "by_persona": _slice(results, lambda r: r.persona),
        "by_language": _slice(results, lambda r: r.language),
        "by_confusion_rule": _slice(results, lambda r: r.rule),
        "failures": [
            {
                "case_id": r.case_id,
                "family": r.generator,
                "outcome": r.outcome,
                "rule": r.rule,
                "language": r.language,
                "formatted": r.formatted,
                "expected": r.expected_output,
                "actual": r.actual_output,
                "reason": r.actual_reason,
            }
            for r in results
            if not r.passed
        ],
    }


def _table(title: str, rows: dict, note: str = "") -> None:
    print(f"\n  {title}")
    if note:
        print(f"  {note}")
    print(f"    {'':<26} {'n':>5} {'pass':>7}  {'useful':>7} {'missed':>7} {'harmful':>8}")
    for name, s in sorted(rows.items(), key=lambda kv: kv[1]["pass_rate"]):
        print(
            f"    {name:<26} {s['n']:>5} {s['pass_rate']:>6.1%}  "
            f"{s['useful']:>7} {s['missed']:>7} {s['harmful']:>8}"
        )


def report(summary: dict) -> None:
    t = summary["totals"]
    print("=" * 78)
    print(f"Generated tier: {t['passed']}/{t['cases']} ({t['pass_rate']:.1%})")
    print("=" * 78)
    print(f"  false intervention  {summary['negative_cases']['false_intervention']} of "
          f"{summary['negative_cases']['n']} negative cases "
          f"({summary['negative_cases']['false_intervention_rate']:.2%})")
    print(f"  model calls         {summary['cost']['llm_calls_total']}")
    print(f"  latency p50/p95     {summary['latency_ms']['p50']}ms / "
          f"{summary['latency_ms']['p95']}ms")

    _table("By family", summary["by_family"],
           "worst first. `unseen_mishearing` is meant to be hard.")
    _table("By memory size", summary["by_persona"],
           "does behaviour hold as memory grows?")
    _table("By script", summary["by_language"],
           "the nine Indic blocks share one code path; do they share results?")
    _table("By confusion rule", summary["by_confusion_rule"],
           "which phonological confusions the encoder survives.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="psm-eval-generated")
    parser.add_argument("--out", default="evals/results/generated")
    parser.add_argument("--policies")
    parser.add_argument("--phonetics")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings(store="store.memory", database_url="memory://")
    if args.policies:
        settings = settings.with_(policies=tuple(p.strip() for p in args.policies.split(",")))
    if args.phonetics:
        settings = settings.with_(phonetics=args.phonetics)

    cases = [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = run(cases, settings)
    summary = summarise(results, settings)

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out_dir / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.__dict__, default=str, ensure_ascii=False) + "\n")

    if not args.quiet:
        report(summary)
        print(f"\nwritten to {out_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
