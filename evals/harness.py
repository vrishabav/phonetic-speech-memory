"""The evaluation harness.

Runs the committed fixtures against a configured Engine and writes a result
directory that someone else can audit without running anything:

    evals/results/<timestamp>/
      summary.json   aggregate + per-tier + per-class + per-reason-code
      cases.jsonl    one row per case: inputs, expected, actual, memory state,
                     decision trace - the five things the brief asks for
      report.html    self-contained, opens in a browser

Two properties it is built around.

**A case can fail for the right reason.** Every case asserts a reason code as
well as an output. A case that produces the right text via the wrong policy is
recorded as `reason_mismatch`, not as a pass. That is the usual way a green
suite hides a broken system.

**Intervention quality is reported, not accuracy.** A single accuracy number
averages together two failures with opposite costs: not correcting something
(mildly annoying) and corrupting something that was already right (unshippable).
They are counted separately, always.
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

from psm.adapters.clock.frozen import FrozenClock  # noqa: E402
from psm.adapters.store.sqlite import serialise_resolutions  # noqa: E402
from psm.config import Settings  # noqa: E402
from psm.domain.enums import LexemeState  # noqa: E402
from psm.domain.models import Utterance  # noqa: E402
from psm.engine.engine import Engine  # noqa: E402
from psm.seed import load_persona  # noqa: E402

DATA = ROOT / "evals" / "data"
DEFAULT_CLOCK = "2026-01-15T09:00:00+00:00"


# --------------------------------------------------------------------------- #
# Outcome taxonomy. The names are the report's column headings.
# --------------------------------------------------------------------------- #

USEFUL = "useful_intervention"          # fired, output correct
MISSED = "missed_intervention"          # should have fired, did not
HARMFUL = "harmful_intervention"        # fired, made it worse
UNNECESSARY = "unnecessary_intervention"  # fired when nothing needed changing
CORRECT_ABSTENTION = "correct_abstention"
REASON_MISMATCH = "reason_mismatch"     # right text, wrong stated cause


@dataclass
class CaseResult:
    case_id: str
    cls: str
    expect: str
    outcome: str
    passed: bool
    expected_output: str
    actual_output: str
    expected_reason: str | None
    actual_reason: str | None
    llm_calls: int
    max_llm_calls: int | None
    latency_ms: float
    trace: list = field(default_factory=list)
    memory_state: list = field(default_factory=list)
    note: str = ""


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def apply_overrides(lexemes, overrides: dict):
    """Patch the seeded memory for a single case.

    Cases that need an unusual state - suppressed, dormant, learning off - say
    so inline rather than depending on a second seed file, so a case is
    readable on its own.
    """
    from dataclasses import replace

    if not overrides:
        return lexemes
    out = []
    for lexeme in lexemes:
        patch = overrides.get(lexeme.id)
        if not patch:
            out.append(lexeme)
            continue
        fields = {}
        if "state" in patch:
            fields["state"] = LexemeState(patch["state"])
        if "learning_enabled" in patch:
            fields["learning_enabled"] = patch["learning_enabled"]
        if "last_used" in patch:
            fields["last_used"] = datetime.fromisoformat(patch["last_used"])
        if "guards" in patch:
            from psm.domain.enums import GuardKind
            from psm.domain.models import Guard

            fields["guards"] = tuple(
                Guard(kind=GuardKind(g["kind"]), payload=g.get("payload", {}))
                for g in patch["guards"]
            )
        out.append(replace(lexeme, **fields))
    return out


def memory_digest(lexemes) -> list[dict]:
    """The memory state as it was when the decision was made. Recorded per
    case, because "what did the system know?" is the first question anyone
    asks about a surprising result."""
    return [
        {
            "id": lx.id,
            "canonical": lx.canonical,
            "state": str(lx.state),
            "confidence": round(lx.confidence.mean, 3),
            "strength": round(lx.confidence.strength, 3),
            "variants": [f"{v.form} ({v.provenance})" for v in lx.variants],
            "guards": [str(g.kind) for g in lx.guards],
        }
        for lx in sorted(lexemes, key=lambda lx: lx.canonical)
    ]


def pick_reason(adjudication) -> str:
    """The single reason code that best describes what happened.

    For an APPLY, the highest-precedence reason among the applied resolutions -
    the same ordering the adjudicator uses, so the report and the engine tell
    the same story when several candidates fired at once.

    For an abstention, `no_candidate` means the gate exited without looking,
    and anything else means we looked and declined. Collapsing those two into
    one code would hide the difference between "cost nothing" and "cost a
    retrieval and a policy pass", which is exactly the distinction the latency
    and cost numbers turn on.
    """
    from psm.domain.enums import PolicySignal
    from psm.engine.adjudicator import APPLY_REASON_PRECEDENCE

    applied = adjudication.applied
    if applied:
        reasons = {r.reason for r in applied}
        for reason in APPLY_REASON_PRECEDENCE:
            if reason in reasons:
                return str(reason)
        return str(applied[0].reason)

    # Nothing was applied, so the reported reason should say what *stopped* it.
    # A veto outranks a proposal: "this is the wrong script" is a decision, and
    # "we have only seen this once" is the absence of one. Reporting the weaker
    # of the two hid a working `script_fit` veto behind an unrelated single-
    # observation proposal on a shorter span, and made a passing case look like
    # a regression.
    vetoed = [
        r
        for r in adjudication.abstained
        if any(o.signal is PolicySignal.VETO for o in r.outcomes)
    ]
    if vetoed:
        return str(max(vetoed, key=lambda r: len(r.candidate.span)).reason)
    if adjudication.proposed:
        return str(adjudication.proposed[0].reason)
    if adjudication.resolutions:
        return str(adjudication.resolutions[0].reason)
    return "below_threshold" if adjudication.gate_passed else "no_candidate"


def run_application_cases(cases: list[dict], settings: Settings) -> list[CaseResult]:
    persona = json.loads((DATA / "persona_seed.json").read_text(encoding="utf-8"))
    results: list[CaseResult] = []

    for case in cases:
        given, then = case["given"], case["then"]
        clock = FrozenClock(given.get("clock") or persona["persona"].get("clock") or DEFAULT_CLOCK)
        lexemes, edges = load_persona(persona, now=clock.now())
        lexemes = apply_overrides(lexemes, given.get("memory_overrides") or {})

        engine = Engine.build(settings, lexemes=lexemes, edges=edges)
        engine.clock = clock
        engine.load(lexemes=lexemes, edges=edges)

        utterance = Utterance(
            asr_text=given.get("asr", ""),
            formatted_text=given.get("formatted", ""),
            app=given.get("app"),
            persona=given.get("persona"),
            surrounding_text=given.get("surrounding_text"),
            utterance_id=case["case_id"],
        )
        started = time.perf_counter()
        adjudication = engine.handle(utterance, record=False)
        latency = (time.perf_counter() - started) * 1000.0

        actual = adjudication.output_text
        expected = then["output"]
        proposed = adjudication.proposed
        actual_reason = pick_reason(adjudication)

        expect = case["expect"]
        text_ok = actual == expected
        intervened = actual != given.get("formatted", "")

        if expect == "apply":
            if text_ok:
                outcome = USEFUL
            elif intervened:
                outcome = HARMFUL
            else:
                outcome = MISSED
        elif expect in {"abstain", "noop"}:
            outcome = CORRECT_ABSTENTION if text_ok else HARMFUL
        else:  # propose
            if not text_ok:
                outcome = HARMFUL
            elif proposed:
                outcome = CORRECT_ABSTENTION
            else:
                outcome = MISSED

        expected_reason = then.get("reason")
        passed = outcome in {USEFUL, CORRECT_ABSTENTION}
        if passed and expected_reason and actual_reason != expected_reason:
            outcome = REASON_MISMATCH
            passed = False

        budget = then.get("max_llm_calls")
        calls = adjudication.cost.llm_calls
        note = ""
        if budget is not None and calls > budget:
            passed = False
            note = f"exceeded model-call budget: {calls} > {budget}"

        results.append(
            CaseResult(
                case_id=case["case_id"],
                cls=case["class"],
                expect=expect,
                outcome=outcome,
                passed=passed,
                expected_output=expected,
                actual_output=actual,
                expected_reason=expected_reason,
                actual_reason=actual_reason,
                llm_calls=calls,
                max_llm_calls=budget,
                latency_ms=latency,
                trace=serialise_resolutions(adjudication),
                memory_state=memory_digest(engine.lexemes),
                note=note,
            )
        )
    return results


def summarise(results: list[CaseResult], settings: Settings) -> dict:
    outcomes = Counter(r.outcome for r in results)
    by_class: dict[str, Counter] = defaultdict(Counter)
    by_reason: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_class[r.cls][r.outcome] += 1
        by_reason[r.expected_reason or "-"]["pass" if r.passed else "fail"] += 1

    latencies = sorted(r.latency_ms for r in results)

    def pct(idx: float) -> float:
        if not latencies:
            return 0.0
        return round(latencies[min(len(latencies) - 1, int(len(latencies) * idx))], 3)

    positives = [r for r in results if r.expect == "apply"]
    negatives = [r for r in results if r.expect in {"abstain", "noop", "propose"}]
    fired_wrongly = sum(1 for r in negatives if r.outcome == HARMFUL)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "settings": settings.describe(),
        "totals": {
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "pass_rate": round(sum(1 for r in results if r.passed) / max(1, len(results)), 4),
        },
        "interventions": dict(outcomes),
        "positive_cases": {
            "n": len(positives),
            "useful": sum(1 for r in positives if r.outcome == USEFUL),
            "missed": sum(1 for r in positives if r.outcome == MISSED),
            "harmful": sum(1 for r in positives if r.outcome == HARMFUL),
        },
        "negative_cases": {
            "n": len(negatives),
            "correct_abstention": sum(1 for r in negatives if r.outcome == CORRECT_ABSTENTION),
            "false_intervention": fired_wrongly,
            "false_intervention_rate": round(fired_wrongly / max(1, len(negatives)), 4),
        },
        "cost": {
            "llm_calls_total": sum(r.llm_calls for r in results),
            "llm_calls_per_case": round(
                sum(r.llm_calls for r in results) / max(1, len(results)), 3
            ),
            "zero_call_cases": sum(1 for r in results if r.llm_calls == 0),
        },
        "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": round(max(latencies or [0]), 3)},
        "by_class": {k: dict(v) for k, v in sorted(by_class.items())},
        "by_expected_reason": {k: dict(v) for k, v in sorted(by_reason.items())},
        "failures": [
            {
                "case_id": r.case_id,
                "class": r.cls,
                "outcome": r.outcome,
                "expected": r.expected_output,
                "actual": r.actual_output,
                "expected_reason": r.expected_reason,
                "actual_reason": r.actual_reason,
                "note": r.note,
            }
            for r in results
            if not r.passed
        ],
    }


def write_results(results: list[CaseResult], summary: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out_dir / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.__dict__, default=str, ensure_ascii=False) + "\n")
    (out_dir / "report.html").write_text(render_report(summary, results), encoding="utf-8")
    return out_dir


def render_report(summary: dict, results: list[CaseResult]) -> str:
    from html import escape

    rows = "\n".join(
        f'<tr class="{"ok" if r.passed else "bad"}"><td>{escape(r.case_id)}</td>'
        f"<td>{escape(r.cls)}</td><td>{escape(r.expect)}</td>"
        f"<td>{escape(r.outcome)}</td>"
        f"<td>{escape(r.expected_reason or '-')}</td><td>{escape(r.actual_reason or '-')}</td>"
        f"<td class=t>{escape(r.actual_output[:90])}</td></tr>"
        for r in results
    )
    t = summary["totals"]
    return f"""<!doctype html><meta charset=utf-8><title>PSM evaluation</title>
<style>
body{{font:14px/1.5 ui-sans-serif,system-ui,sans-serif;margin:2rem auto;max-width:1100px;color:#16161d}}
h1{{font-size:1.4rem;margin:0 0 .2rem}} .sub{{color:#666;margin:0 0 1.5rem}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th{{text-align:left;border-bottom:2px solid #ddd;padding:6px;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#666}}
td{{border-bottom:1px solid #eee;padding:6px;vertical-align:top}}
tr.bad td{{background:#fff4f2}} tr.ok td:first-child{{color:#137a5a}}
td.t{{font-family:ui-monospace,monospace;font-size:11.5px;color:#444}}
pre{{background:#f6f6f8;padding:1rem;border-radius:6px;overflow:auto;font-size:12px}}
</style>
<h1>phonetic-speech-memory - evaluation</h1>
<p class=sub>{t['passed']}/{t['cases']} passed ({t['pass_rate']:.0%}) &middot;
generated {summary['generated_at']}</p>
<pre>{escape(json.dumps({k: summary[k] for k in
  ('interventions','positive_cases','negative_cases','cost','latency_ms')}, indent=2))}</pre>
<table><tr><th>case</th><th>class</th><th>expect</th><th>outcome</th>
<th>expected reason</th><th>actual reason</th><th>output</th></tr>
{rows}</table>"""


def _preflight(settings: Settings, parser) -> None:
    """Prove the configured formatter can reach its model before writing a
    result file with that model's name on it.

    The formatter degrades to the unconditioned text when the model is
    unreachable, which is correct for dictation and ruinous for an evaluation:
    a replay run against an empty cassette directory produced exactly the
    offline numbers, under the label `replay`. One probe call up front turns
    that into an error the reviewer can act on.
    """
    try:
        engine = Engine.build(settings)
    except Exception as exc:  # missing credentials, unknown alias, bad URL
        parser.error(f"{settings.llm} could not be constructed. {exc}")
    formatter = engine.formatter
    formatter.format(
        Utterance(
            asr_text="the sarvam kiwi service is dropping requests",
            formatted_text="",
            app="com.tinyspeck.slackmacgap",
        ),
        lexemes=(),
        instructions=(),
    )
    if getattr(formatter, "failures", 0):
        parser.error(
            f"the {settings.formatter} formatter could not reach {settings.llm}: "
            f"{getattr(formatter, 'last_error', 'unknown error')}. "
            "Nothing was written. Run `make eval` for the offline evaluation."
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="psm-eval")
    parser.add_argument("--out", default="evals/results")
    parser.add_argument(
        "--live",
        action="store_true",
        help="run the memory-conditioned formatter against a real model endpoint",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="same path as --live, answered from recorded cassettes",
    )
    parser.add_argument("--policies", help="comma-separated ablation")
    parser.add_argument("--phonetics", help="e.g. phonetics.null")
    parser.add_argument("--label", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    # Every case gets its own isolated in-memory store pinned to its own clock.
    # A shared file-backed database would make the suite order-dependent.
    settings = Settings(store="store.memory", database_url="memory://")
    if args.policies:
        settings = settings.with_(policies=tuple(p.strip() for p in args.policies.split(",")))
    if args.phonetics:
        settings = settings.with_(phonetics=args.phonetics)

    # These two flags used to be declared and then ignored, which is the worst
    # possible bug in an evaluation harness: `make eval-live` ran the offline
    # stub, reported "0 model calls", and wrote a result file labelled `live`.
    # A number that names a component which never ran is a false claim in every
    # artefact it appears in, so the switch is now real and it fails loudly.
    if args.live and args.replay:
        parser.error("--live and --replay are alternatives; pass one or neither")
    if args.live:
        settings = settings.with_(llm="llm.sarvam", formatter="formatter.llm")
    elif args.replay:
        settings = settings.with_(llm="llm.cassette", formatter="formatter.llm")

    if args.live or args.replay:
        _preflight(settings, parser)

    cases = load_jsonl(DATA / "tier_c_application.jsonl")
    results = run_application_cases(cases, settings)
    summary = summarise(results, settings)

    # The learning tier runs in the same command as the application tier, on
    # purpose. It lived in its own file with no runner for a while and fifteen
    # assertions about learning quietly asserted nothing; wiring it into the
    # default path is what stops that recurring.
    sys.path.insert(0, str(ROOT))
    from evals.learning import run_learning_cases
    from evals.learning import summarise as summarise_learning

    learning_cases = load_jsonl(DATA / "tier_c_learning.jsonl")
    learning_results = run_learning_cases(learning_cases, settings)
    summary["learning"] = summarise_learning(learning_results)

    label = args.label or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = write_results(results, summary, Path(args.out) / label)
    (out_dir / "learning.jsonl").write_text(
        "".join(
            json.dumps(r.__dict__, default=str, ensure_ascii=False) + "\n"
            for r in learning_results
        ),
        encoding="utf-8",
    )

    if not args.quiet:
        t = summary["totals"]
        print(f"{t['passed']}/{t['cases']} passed ({t['pass_rate']:.0%})")
        print(f"  interventions      {summary['interventions']}")
        print(f"  false intervention {summary['negative_cases']['false_intervention_rate']:.1%} "
              f"of {summary['negative_cases']['n']} negative cases")
        print(f"  model calls        {summary['cost']['llm_calls_total']}")
        print(f"  latency p50/p95    {summary['latency_ms']['p50']}ms / "
              f"{summary['latency_ms']['p95']}ms")
        learning = summary["learning"]
        print(f"  learning tier      {learning['passed']}/{learning['cases']} "
              f"memory-state cases")
        for f in learning["failures"]:
            print(f"    {f['case_id']:<10} {f['class']}: {'; '.join(f['why'])}")
        if summary["failures"]:
            print(f"\n  {len(summary['failures'])} failing:")
            for f in summary["failures"]:
                print(f"    {f['case_id']:<10} {f['outcome']:<24} {f['class']}")
        print(f"\nwritten to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
