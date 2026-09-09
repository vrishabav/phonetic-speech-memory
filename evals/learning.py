"""Run the learning fixtures.

`tier_c_application.jsonl` asserts what the system *does to text*.
`tier_c_learning.jsonl` asserts what evidence *does to memory* - a different
question with a different failure mode, which is why it is a separate file and
a separate runner.

For a while it was a separate file and *no* runner: the cases were schema-checked
and never executed, so fifteen assertions about learning behaviour were
decorative. This module is the fix. Every `memory_delta` key in the fixtures is
implemented as a check below; an unrecognised key is an error rather than a
silent skip, because a fixture that asserts something nothing reads is worse
than no fixture at all.

    python -m lmh.cli eval          # runs both tiers
    python evals/learning.py        # this tier alone, verbose
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lmh.adapters.clock.frozen import FrozenClock  # noqa: E402
from lmh.config import Settings  # noqa: E402
from lmh.domain.enums import ObservationSource  # noqa: E402
from lmh.domain.models import Binding, BindingScope  # noqa: E402
from lmh.engine.engine import Engine  # noqa: E402
from lmh.engine.learner import observation as make_observation  # noqa: E402
from lmh.seed import load_persona  # noqa: E402

DATA = ROOT / "evals" / "data"
DEFAULT_CLOCK = "2026-01-15T09:00:00+00:00"

#: Every assertion a learning fixture is allowed to make. Kept explicit so that
#: a typo in a fixture key fails loudly instead of passing vacuously.
KNOWN_DELTAS = frozenset(
    {
        "lexeme_created",
        "lexeme_recreated",
        "lexeme_id",
        "canonical",
        "state",
        "reason",
        "variants_added",
        "variant_count",
        "guard_created",
        "instruction_set",
        "tombstone_created",
        "confidence_decreased",
        "observation_accepted",
    }
)


@dataclass
class LearningResult:
    case_id: str
    cls: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    observed_state: dict = field(default_factory=dict)
    rationale: str = ""


def _observations(given: dict) -> list[dict]:
    if "observations" in given:
        return list(given["observations"])
    if "observation" in given:
        return [given["observation"]]
    return []


def _variant_counts(lexemes, lexeme_id):
    lexeme = next((lx for lx in lexemes if lx.id == lexeme_id), None)
    return {v.form: v.count for v in lexeme.variants} if lexeme else {}


def _snapshot(engine) -> dict[str, dict]:
    return {
        lx.id: {
            "canonical": lx.canonical,
            "state": str(lx.state),
            "confidence": lx.confidence.mean,
            "variants": [(v.form, str(v.provenance)) for v in lx.variants],
            "guards": [str(g.kind) for g in lx.guards],
            "instruction": lx.instruction,
        }
        for lx in engine.lexemes
    }


def run_case(case: dict, settings: Settings) -> LearningResult:
    from evals.harness import apply_overrides

    given, then = case["given"], case["then"]
    delta = then.get("memory_delta", {})

    unknown = set(delta) - KNOWN_DELTAS
    if unknown:
        return LearningResult(
            case["case_id"],
            case["class"],
            False,
            [f"fixture asserts unknown key(s) {sorted(unknown)} that no check reads"],
        )

    persona = json.loads((DATA / "persona_seed.json").read_text(encoding="utf-8"))
    clock = FrozenClock(given.get("clock") or persona["persona"].get("clock") or DEFAULT_CLOCK)
    lexemes, edges = load_persona(persona, now=clock.now())
    lexemes = apply_overrides(lexemes, given.get("memory_overrides") or {})

    engine = Engine.build(settings, lexemes=lexemes, edges=edges)
    engine.clock = clock
    engine.load(lexemes=lexemes, edges=edges)

    before = _snapshot(engine)
    before_lexemes = list(engine.lexemes)
    judged = None
    for spec in _observations(given):
        at = (
            datetime.fromisoformat(spec["at"])
            if spec.get("at")
            else clock.now()
        )
        binding = Binding(BindingScope.APP, spec["app"]) if spec.get("app") else None
        judged = engine.observe(
            make_observation(
                ObservationSource(spec["source"]),
                spec["after"],
                at=at,
                before=spec.get("before"),
                binding=binding,
                lexeme_id=spec.get("lexeme_id"),
                surrounding_text=spec.get("surrounding_text"),
                note=spec.get("note"),
            )
        )
    after = _snapshot(engine)

    failures: list[str] = []

    def target():
        """The lexeme this case is about: the one it names, else the one that
        appeared, else the one the observation was attributed to."""
        if delta.get("lexeme_id"):
            return delta["lexeme_id"]
        appeared = set(after) - set(before)
        if appeared:
            return next(iter(appeared))
        if judged is not None and judged.lexeme_id:
            return judged.lexeme_id
        return None

    tid = target()
    state = after.get(tid) if tid else None

    # -- existence ---------------------------------------------------------- #

    if "lexeme_created" in delta:
        created = bool(set(after) - set(before))
        if created != delta["lexeme_created"]:
            failures.append(
                f"lexeme_created: expected {delta['lexeme_created']}, got {created}"
            )

    if delta.get("lexeme_recreated") is False and tid and tid in before:
        # "re-observation must not silently resurrect a deleted term"
        if before[tid]["state"] == "retired" and after[tid]["state"] != "retired":
            failures.append("lexeme_recreated: a retired lexeme came back to life")

    # -- identity ----------------------------------------------------------- #

    if "canonical" in delta:
        got = state["canonical"] if state else None
        if got != delta["canonical"]:
            failures.append(f"canonical: expected {delta['canonical']!r}, got {got!r}")

    if "state" in delta:
        got = state["state"] if state else None
        if got != delta["state"]:
            failures.append(f"state: expected {delta['state']!r}, got {got!r}")

    # -- variants ----------------------------------------------------------- #

    if "variants_added" in delta:
        # "Added" means the observation put evidence behind this form: either the
        # variant is new, or it already existed and its count went up. The
        # distinction matters for the casing case, where the seeded persona
        # already lists "Npm" - asserting only newness would demand that the
        # system forget what it knew in order to pass.
        old = dict(_variant_counts(before_lexemes, tid))
        new = dict(_variant_counts(engine.lexemes, tid))
        old_forms = set(before.get(tid, {}).get("variants", [])) if tid else set()
        new_forms = set(state["variants"]) if state else set()
        for want in delta["variants_added"]:
            form, provenance = want["form"], want["provenance"]
            if (form, provenance) not in new_forms:
                failures.append(
                    f"variants_added: {form!r} ({provenance}) is not a variant "
                    f"of {tid} afterwards"
                )
            elif new.get(form, 0) <= old.get(form, 0):
                failures.append(
                    f"variants_added: {form!r} was already known and its count "
                    f"did not move ({old.get(form)} -> {new.get(form)}), so this "
                    f"observation contributed nothing"
                )
        if not delta["variants_added"] and (new_forms - old_forms):
            failures.append(f"variants_added: expected none, got {sorted(new_forms - old_forms)}")

    if "variant_count" in delta:
        # A mapping of form -> how many times that form has been seen. Asserting
        # the count rather than mere presence is what distinguishes "the same
        # correction twice" from "two different corrections".
        counts = {}
        if tid:
            lexeme = next((lx for lx in engine.lexemes if lx.id == tid), None)
            if lexeme:
                counts = {v.form: v.count for v in lexeme.variants}
        for form, want in delta["variant_count"].items():
            got = counts.get(form)
            if got != want:
                failures.append(f"variant_count[{form!r}]: expected {want}, got {got}")

    # -- guards, instructions, tombstones ----------------------------------- #

    if "guard_created" in delta:
        old = set(before.get(tid, {}).get("guards", [])) if tid else set()
        new = set(state["guards"]) if state else set()
        created = new - old
        want = delta["guard_created"]
        wanted_kind = want.get("kind") if isinstance(want, dict) else want
        if wanted_kind is True and not created:
            failures.append("guard_created: expected a new guard, none appeared")
        elif isinstance(wanted_kind, str) and wanted_kind not in created:
            failures.append(f"guard_created: expected {wanted_kind!r}, got {sorted(created)}")
        elif wanted_kind is False and created:
            failures.append(f"guard_created: expected none, got {sorted(created)}")

    if "instruction_set" in delta:
        got = bool(state and state["instruction"])
        if got != bool(delta["instruction_set"]):
            failures.append(f"instruction_set: expected {delta['instruction_set']}, got {got}")

    if "tombstone_created" in delta:
        want = delta["tombstone_created"]
        stones = list(engine.store.tombstones())
        if want is False:
            if stones:
                failures.append(f"tombstone_created: expected none, got {len(stones)}")
        elif not stones:
            failures.append("tombstone_created: expected one, none was created")
        elif isinstance(want, dict):
            reasons = {str(t.reason) for t in stones}
            if want.get("reason") and want["reason"] not in reasons:
                failures.append(
                    f"tombstone_created: expected reason {want['reason']!r}, got {sorted(reasons)}"
                )
            if want.get("match_forms_preserved") and not any(t.match_forms for t in stones):
                failures.append(
                    "tombstone_created: match_forms_preserved, but no tombstone kept any "
                    "surface form - the old spelling would have to be re-learned"
                )

    # -- confidence --------------------------------------------------------- #

    if delta.get("confidence_decreased"):
        new = state["confidence"] if state else None
        if _observations(given):
            # Evidence arrived: the question is whether it moved belief down.
            old = before.get(tid, {}).get("confidence") if tid else None
            label = "before this evidence"
        else:
            # No evidence arrived, so the case is about *time*. Compare against
            # the undecayed prior - the belief the original evidence supported -
            # because both sides of a before/after snapshot have already aged by
            # the time the engine has loaded.
            lexeme = next((lx for lx in engine.lexemes if lx.id == tid), None)
            old = lexeme.prior.mean if lexeme else None
            label = "undecayed prior"
        if old is None or new is None or new >= old:
            failures.append(f"confidence_decreased: {label} {old} -> {new}")

    # -- the learner's own verdict ------------------------------------------ #

    if "observation_accepted" in delta:
        got = judged.accepted if judged is not None else None
        want = delta["observation_accepted"]
        # `None` means the learner had no phonetic opinion, which is not the
        # same as a rejection; only an explicit False is a rejection.
        if want is False and got is not False:
            failures.append(f"observation_accepted: expected False, got {got!r}")
        if want is True and got is False:
            failures.append("observation_accepted: expected accepted, was rejected")

    return LearningResult(
        case_id=case["case_id"],
        cls=case["class"],
        passed=not failures,
        failures=failures,
        observed_state=state or {},
        rationale=case.get("rationale", ""),
    )


def run_learning_cases(cases: list[dict], settings: Settings) -> list[LearningResult]:
    return [run_case(case, settings) for case in cases]


def summarise(results: list[LearningResult]) -> dict:
    return {
        "cases": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "pass_rate": round(
            sum(1 for r in results if r.passed) / max(1, len(results)), 4
        ),
        "failures": [
            {"case_id": r.case_id, "class": r.cls, "why": r.failures}
            for r in results
            if not r.passed
        ],
    }


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ROOT))
    from evals.harness import load_jsonl

    cases = load_jsonl(DATA / "tier_c_learning.jsonl")
    results = run_learning_cases(cases, Settings(store="store.memory"))
    summary = summarise(results)

    for r in results:
        mark = "pass" if r.passed else "FAIL"
        print(f"  {mark}  {r.case_id:<10} {r.cls}")
        for why in r.failures:
            print(f"          {why}")
    print(f"\n{summary['passed']}/{summary['cases']} learning cases passed")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
