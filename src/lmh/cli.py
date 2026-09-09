"""Command line entry point.

    python -m lmh.cli seed --from evals/data/persona_seed.json
    python -m lmh.cli inspect
    python -m lmh.cli dictate "The Sarvam Kiwi service is down." --app com.tinyspeck.slackmacgap
    python -m lmh.cli teach "Aadith Kulkarni" --before "Adith Kulkarni"
    python -m lmh.cli eval --policies suppression,exact_variant --label my-ablation
    python -m lmh.cli reset

Between them, `teach`, `inspect`, `dictate` and `reset` cover everything the
demonstration does except speaking into a microphone. The browser interface at
`make serve` is a nicer surface for the same operations, not extra capability -
there is nothing behind a button that is not also here and on the API.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from lmh.config import from_env
from lmh.domain.enums import ObservationSource
from lmh.domain.models import Observation

# --------------------------------------------------------------------------- #


def _engine(url: str):
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# seed
# --------------------------------------------------------------------------- #


def cmd_seed(args: argparse.Namespace) -> int:
    """Load a persona into the store, through the same loader the evaluation
    uses. Two loaders would eventually disagree, and the disagreement would
    surface as an unreproducible result."""
    from lmh.adapters.store.sqlite import SqliteStore
    from lmh.seed import load_persona

    settings = from_env()
    store = SqliteStore(settings.database_url)
    with store.engine.begin() as conn:
        if not conn.execute(
            text("select name from sqlite_master where type='table' and name='lexeme'")
        ).fetchone():
            print("error: the database has no schema. Run `make migrate` first.", file=sys.stderr)
            return 2

    lexemes, edges = load_persona(Path(args.source), now=_now())
    store.clear()  # seeding twice produces the same state as seeding once
    store.put(lexemes)
    store.put_edges(edges)

    for lexeme in lexemes:
        store.append(
            Observation(
                id=str(uuid.uuid4()),
                source=ObservationSource.DECLARED,
                at=lexeme.first_seen or _now(),
                after=lexeme.canonical,
                lexeme_id=lexeme.id,
                accepted=True,
                note="seed",
            )
        )

    print(f"seeded {len(lexemes)} lexemes and {len(edges)} edges into {settings.database_url}")
    return 0


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #


def cmd_inspect(args: argparse.Namespace) -> int:
    settings = from_env()
    engine = _engine(settings.database_url)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "select l.id, l.canonical, l.kind, l.state, l.conf_alpha, l.conf_beta,"
                " (select count(*) from variant v where v.lexeme_id = l.id) as variants,"
                " (select count(*) from guard g where g.lexeme_id = l.id) as guards"
                " from lexeme l order by l.canonical"
            )
        ).all()
    if not rows:
        print("memory is empty - run `make seed`")
        return 0
    width = max(len(r.canonical) for r in rows)
    print(f"{'canonical'.ljust(width)}  {'kind':<11} {'state':<10} {'conf':>5}  var  grd")
    print("-" * (width + 40))
    for r in rows:
        confidence = r.conf_alpha / (r.conf_alpha + r.conf_beta)
        print(
            f"{r.canonical.ljust(width)}  {r.kind:<11} {r.state:<10} "
            f"{confidence:>5.2f}  {r.variants:>3}  {r.guards:>3}"
        )
    print(f"\n{len(rows)} lexemes")
    return 0


# --------------------------------------------------------------------------- #
# reset
# --------------------------------------------------------------------------- #


def cmd_reset(args: argparse.Namespace) -> int:
    settings = from_env()
    engine = _engine(settings.database_url)
    with engine.begin() as conn:
        for table in (
            "evidence_link", "phonetic_key", "binding", "guard", "variant",
            "edge", "tombstone", "observation", "lexeme", "adjudication",
        ):
            conn.execute(text(f"delete from {table}"))
    print("all memory state cleared")
    return 0


def cmd_dictate(args: argparse.Namespace) -> int:
    """Run one utterance through the engine and print the decision trace.

    The CLI equivalent of the demo's Dictate + Trace panes: it shows the
    memory-aware output and, underneath it, every candidate, every policy and
    the reason each one gave - including for the calls where nothing happened.
    """
    from lmh.domain.models import Utterance
    from lmh.engine.engine import Engine, summarise

    engine = Engine.build(from_env())
    utterance = Utterance(
        asr_text=args.asr or args.formatted,
        formatted_text=args.formatted,
        app=args.app,
        persona=args.persona,
    )
    adjudication = engine.handle(utterance)
    print(f"  in  {utterance.formatted_text}")
    print(f"  out {adjudication.output_text}")
    trace = summarise(adjudication)
    print(trace if trace else "  (gate exit - nothing in memory resembles this text)")
    print(
        f"\n  gate={'opened' if adjudication.gate_passed else 'closed'} "
        f"candidates={len(adjudication.resolutions)} "
        f"model_calls={adjudication.cost.llm_calls} "
        f"latency={adjudication.cost.latency_ms:.2f}ms"
    )
    return 0


def cmd_teach(args: argparse.Namespace) -> int:
    """Feed the system one observation and report what it did with it."""
    from lmh.domain.enums import BindingScope, ObservationSource
    from lmh.domain.models import Binding
    from lmh.engine.engine import Engine
    from lmh.engine.learner import observation as make_observation

    engine = Engine.build(from_env())
    source = ObservationSource(args.source)
    obs = make_observation(
        source,
        args.after,
        at=engine.now(),
        before=args.before,
        binding=Binding(BindingScope.APP, args.app) if args.app else None,
        note=args.note,
    )
    judged = engine.observe(obs)
    if judged.accepted is False:
        print(f"  discarded: {judged.note}")
        return 0
    target = next((lx for lx in engine.lexemes if lx.id == judged.lexeme_id), None)
    if target is None:
        print("  recorded, not attributed to any lexeme")
        return 0
    print(
        f"  {target.canonical!r} [{target.state}] confidence={target.confidence.mean:.2f} "
        f"strength={target.confidence.strength:.2f}"
    )
    for variant in target.variants:
        print(f"    also heard as {variant.form!r} ({variant.provenance}, {variant.count}x)")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from evals.harness import main as run_eval

    argv = ["--out", args.out]
    if args.label:
        argv += ["--label", args.label]
    if args.policies:
        argv += ["--policies", args.policies]
    if args.phonetics:
        argv += ["--phonetics", args.phonetics]
    if args.quiet:
        argv += ["--quiet"]
    return run_eval(argv)


def cmd_eval_generated(args: argparse.Namespace) -> int:
    """Run the large derived tier and print the breakdown.

    Separate from `eval` because it answers a different question: `eval` asks
    whether the specified behaviours hold, this asks which *kinds* of input the
    system gets wrong across ~1,800 mechanically-derived situations.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from evals.generated import main as run_generated

    argv = ["--out", args.out]
    if args.policies:
        argv += ["--policies", args.policies]
    if args.phonetics:
        argv += ["--phonetics", args.phonetics]
    if args.quiet:
        argv += ["--quiet"]
    return run_generated(argv)


def cmd_explore(args: argparse.Namespace) -> int:
    """Build the case explorer, running the evaluation first if it has not been run.

    The results directory is an artefact, not a source file, so a reviewer who
    clones the repo and types `make explore` should get a page rather than an
    error about a missing file.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from evals.explorer import main as build_explorer

    results = Path(args.results)
    if not (results / "cases.jsonl").exists():
        print(f"{results}/cases.jsonl not found - running the evaluation first")
        rc = cmd_eval(
            argparse.Namespace(
                out=str(results.parent),
                label=results.name,
                policies=None,
                phonetics=None,
                quiet=True,
            )
        )
        if rc != 0:
            return rc
    return build_explorer(results=str(results), out=args.out)


# --------------------------------------------------------------------------- #


def _quiet_broken_pipe() -> None:
    """`lmh inspect | head` closes the pipe early. Without this, Python prints a
    BrokenPipeError traceback over the output the reviewer actually wanted."""
    import signal

    with contextlib.suppress(AttributeError, ValueError):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def main(argv: list[str] | None = None) -> int:
    _quiet_broken_pipe()
    parser = argparse.ArgumentParser(prog="lmh")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="load a persona into memory")
    p_seed.add_argument("--from", dest="source", default="evals/data/persona_seed.json")
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("inspect", help="print the current memory state").set_defaults(
        func=cmd_inspect
    )
    sub.add_parser("reset", help="clear all memory state").set_defaults(func=cmd_reset)

    p_dictate = sub.add_parser("dictate", help="run one utterance and show the trace")
    p_dictate.add_argument("formatted", help="the formatted text Kivi would insert")
    p_dictate.add_argument("--asr", help="raw ASR text, if it differs")
    p_dictate.add_argument("--app")
    p_dictate.add_argument("--persona")
    p_dictate.set_defaults(func=cmd_dictate)

    p_teach = sub.add_parser("teach", help="feed the system one observation")
    p_teach.add_argument("after", help="the correct form")
    p_teach.add_argument("--before", help="what was inserted before the user fixed it")
    p_teach.add_argument(
        "--source",
        default="post_edit",
        choices=["declared", "post_edit", "instruction", "ambient", "revert", "dismissal"],
    )
    p_teach.add_argument("--app")
    p_teach.add_argument("--note")
    p_teach.set_defaults(func=cmd_teach)

    p_eval = sub.add_parser("eval", help="run the evaluation")
    p_eval.add_argument("--replay", action="store_true", default=True)
    p_eval.add_argument("--live", action="store_true")
    p_eval.add_argument("--out", default="evals/results")
    p_eval.add_argument("--label", default="")
    p_eval.add_argument("--policies", help="comma-separated ablation")
    p_eval.add_argument("--phonetics")
    p_eval.add_argument("--quiet", action="store_true", help="only write files, print nothing")
    p_eval.set_defaults(func=cmd_eval)

    p_gen = sub.add_parser(
        "eval-generated", help="run the ~1,800-case derived tier and report where it fails"
    )
    p_gen.add_argument("--out", default="evals/results/generated")
    p_gen.add_argument("--policies")
    p_gen.add_argument("--phonetics")
    p_gen.add_argument("--quiet", action="store_true")
    p_gen.set_defaults(func=cmd_eval_generated)

    p_explore = sub.add_parser(
        "explore", help="build a browsable page showing every case and its decision"
    )
    p_explore.add_argument("--results", default="evals/results/baseline")
    p_explore.add_argument("--out", default="evals/results/explorer.html")
    p_explore.set_defaults(func=cmd_explore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
