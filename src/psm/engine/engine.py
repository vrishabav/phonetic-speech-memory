"""The facade. Everything above is wired together here and nowhere else.

    engine = Engine.build(settings)
    result = engine.handle(utterance)

The pipeline, in order, with the cost of each stage:

    0  gate        index probe over n-grams. Nothing matches -> return the
                   input unchanged. ~1ms, 0 tokens. This is the majority of
                   real traffic and it must cost nothing.
    1  retrieve    exact-form lookup, then phonetic blocking. <5ms.
    2  adjudicate  the policy stack, per candidate. Deterministic.
    3  apply       splice the accepted replacements into the formatted text.
    4  record      one Adjudication, always - including for the calls where
                   nothing happened, because an abstention with a reason is a
                   decision and needs to be as inspectable as a change.

The model is not in that list, and that is the point: every stage above is
arithmetic, so the whole path is deterministic, reproducible and free. A
language model is used by the *formatting* stage above this one (see
`adapters/formatter/`), and a port exists for an LLM adjudicator over genuinely
ambiguous candidates - but no committed result uses either, and the evaluation
records zero model calls.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from psm.adapters.formatter.passthrough import PassthroughFormatter
from psm.adapters.index.inmemory import InMemoryIndex
from psm.adapters.phonetics.dmetaphone import PhoneticStack
from psm.config import Settings
from psm.domain.enums import LexemeState, ObservationSource, Verdict
from psm.domain.models import Adjudication, Cost, Lexeme, Observation, Resolution, Utterance
from psm.engine.adjudicator import Adjudicator
from psm.engine.applier import apply_resolutions
from psm.engine.guards import synthesise_all
from psm.engine.learner import Learner
from psm.engine.policies import build_stack
from psm.engine.projector import Projector
from psm.ports.policy import PolicyContext
from psm.registry import resolve

#: States whose terms are worth telling the formatter about. A SUPPRESSED or
#: RETIRED term must not reach the prompt at all - the deterministic stage could
#: veto a replacement afterwards, but it cannot un-say a hint.
_APPLICABLE = frozenset({LexemeState.ACTIVE, LexemeState.PROPOSED, LexemeState.DORMANT})


class Engine:
    def __init__(
        self,
        *,
        settings: Settings,
        store,
        index: InMemoryIndex,
        phonetics: PhoneticStack,
        clock,
        llm=None,
        formatter=None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.index = index
        self.phonetics = phonetics
        self.clock = clock
        self.llm = llm
        self.formatter = formatter or PassthroughFormatter()
        self.projector = Projector(settings.thresholds, settings.weights)
        self.learner = Learner(phonetics, settings.thresholds)
        self.adjudicator = Adjudicator(build_stack(settings.policies), settings.thresholds)
        self._lexemes: list[Lexeme] = []
        self._edges: list[tuple[str, str, str, float]] = []

    # -- construction ------------------------------------------------------- #

    @classmethod
    def build(cls, settings: Settings | None = None, *, lexemes=None, edges=None) -> Engine:
        settings = settings or Settings()
        phonetics = PhoneticStack(encoder=resolve(settings.phonetics)())
        store = resolve(settings.store)(settings.database_url)
        index = resolve(settings.index)(phonetics, settings.thresholds.retrieval_max_distance)
        llm = resolve(settings.llm)()
        engine = cls(
            settings=settings,
            store=store,
            index=index,
            phonetics=phonetics,
            clock=resolve(settings.clock)(),
            llm=llm,
            formatter=resolve(settings.formatter)(
                llm=llm,
                allow_prompt_injection=settings.allow_prompt_injection,
                verify_output=settings.verify_output,
            ),
        )
        engine.load(lexemes=lexemes, edges=edges)
        return engine

    def load(self, *, lexemes=None, edges=None) -> None:
        """Refresh in-memory state from the store (or from an explicit set, for
        tests and eval cases that pin their own memory)."""
        self._lexemes = list(lexemes if lexemes is not None else self.store.all_lexemes())
        self._edges = list(edges if edges is not None else self.store.edges())
        self._lexemes = self.projector.refresh(self._lexemes, self.store, self.now())
        # Guards are derived, like confidence: any term whose surface form is an
        # ordinary English word is protected automatically, so the system does
        # not depend on somebody having hand-written a guard list for it.
        self._lexemes = synthesise_all(self._lexemes)
        self.index.rebuild(self._lexemes)

    def now(self) -> datetime:
        return self.clock.now()

    @property
    def lexemes(self) -> Sequence[Lexeme]:
        return tuple(self._lexemes)

    # -- the hot path ------------------------------------------------------- #

    def handle(self, utterance: Utterance, *, record: bool = True) -> Adjudication:
        started = time.perf_counter()

        if not self.index.probe(utterance.formatted_text):
            return self._finish(utterance, utterance.formatted_text, (), False, started, record)

        binding = utterance.binding()
        candidates = self.index.search(utterance, binding=binding, limit=8)
        if not candidates:
            return self._finish(utterance, utterance.formatted_text, (), True, started, record)

        ctx = PolicyContext(
            utterance=utterance,
            binding=binding,
            snapshot=self.snapshot(),
            now=self.now(),
            siblings=tuple(candidates),
            edges=tuple(self._edges),
        )
        resolutions = tuple(self.adjudicator.resolve(c, ctx) for c in candidates)
        output = apply_resolutions(utterance.formatted_text, resolutions)
        return self._finish(utterance, output, resolutions, True, started, record)

    def dictate(self, asr_text: str, **kwargs) -> Adjudication:
        """The full pipeline, from raw ASR text, with no formatted text supplied.

        `handle` takes an already-formatted utterance because that is what the
        evaluation does - fixtures pin the formatting so that memory can be
        measured on its own. Real dictation has no such luxury, so this runs the
        formatting stage first, conditioned on the memory that is active for
        this app, and then hands the result to `handle`.

        Both stages get the same memory and they use it differently: the
        formatter is *told* about the terms (it may act on them, in context),
        and the engine then *checks* what came back. That redundancy is the
        point - the deterministic stage is what stops a helpful model from
        rewriting a sentence it was only asked to punctuate.
        """
        provisional = Utterance(asr_text=asr_text, formatted_text=asr_text, **kwargs)
        binding = provisional.binding()
        active = [
            lx
            for lx in self._lexemes
            if lx.state in _APPLICABLE and any(b.covers(binding) for b in lx.bindings)
        ]
        formatted = self.formatter.format(
            provisional,
            lexemes=active,
            instructions=[lx.instruction for lx in active if lx.instruction],
        )
        return self.handle(replace(provisional, formatted_text=formatted))

    def _finish(
        self,
        utterance: Utterance,
        output: str,
        resolutions: Sequence[Resolution],
        gate_passed: bool,
        started: float,
        record: bool,
    ) -> Adjudication:
        adjudication = Adjudication(
            utterance=utterance,
            output_text=output,
            resolutions=tuple(resolutions),
            gate_passed=gate_passed,
            cost=Cost(latency_ms=(time.perf_counter() - started) * 1000.0),
            at=self.now(),
        )
        if record:
            try:
                self.store.record(adjudication)
            except Exception:  # pragma: no cover - telemetry must never break the call
                pass
        return adjudication

    # -- learning ----------------------------------------------------------- #

    def observe(self, obs: Observation) -> Observation:
        """Ingest one piece of evidence: judge it, log it, fold it in, reindex."""
        judged = self.learner.judge(obs)
        self.learner.pending_tombstones.clear()
        lexemes, lexeme_id = self.learner.attribute(judged, self._lexemes)
        judged = judged if lexeme_id is None else _with_lexeme(judged, lexeme_id)
        self.store.append(judged)
        # A rename or a deletion emits a tombstone. The learner produces it; the
        # store owns it. Draining here keeps the learner free of I/O.
        if self.learner.pending_tombstones:
            self.store.put_tombstones(self.learner.pending_tombstones)
            self.learner.pending_tombstones = []
        self._lexemes = self.projector.refresh(lexemes, self.store, self.now())
        self.index.rebuild(self._lexemes)
        return judged

    def teach(self, term: str, *, heard: str | None = None, instruction: str | None = None,
              app: str | None = None) -> Observation:
        from psm.domain.models import Binding, BindingScope

        binding = Binding(BindingScope.APP, app) if app else None
        from psm.engine.learner import observation as make_observation

        return self.observe(
            make_observation(
                ObservationSource.DECLARED if not instruction else ObservationSource.INSTRUCTION,
                term,
                at=self.now(),
                before=heard,
                binding=binding,
                note=instruction,
            )
        )

    def snapshot(self):
        from psm.domain.models import MemorySnapshot

        return MemorySnapshot(
            at=self.now(), lexemes=tuple(self._lexemes), tombstones=(), observation_count=0
        )

    def reset(self) -> None:
        self.store.clear()
        self._lexemes, self._edges = [], []
        self.index.rebuild([])


def _with_lexeme(obs: Observation, lexeme_id: str) -> Observation:
    from dataclasses import replace

    return replace(obs, lexeme_id=lexeme_id)


def summarise(adjudication: Adjudication) -> str:
    """One line per decision, for the CLI and the report."""
    lines = []
    for r in adjudication.resolutions:
        mark = {Verdict.APPLY: "APPLY  ", Verdict.PROPOSE: "PROPOSE", Verdict.ABSTAIN: "ABSTAIN"}[
            r.verdict
        ]
        lines.append(
            f"  {mark} {r.candidate.span.text!r} -> {r.replacement or '(unchanged)'}"
            f"  [{r.reason}] score={r.score:.2f}"
        )
        for outcome in r.outcomes:
            if outcome.rationale:
                lines.append(f"           . {outcome.policy}: {outcome.rationale}")
    return "\n".join(lines)
