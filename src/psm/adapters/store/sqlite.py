"""SQLite persistence.

Three stores over one database, matching the three ports. Written with
SQLAlchemy Core rather than the ORM: the schema is owned by the migration, the
domain objects are plain dataclasses, and an ORM layer between them would be a
third representation of the same thing with nothing to show for it.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from psm.domain.enums import (
    BindingScope,
    GuardKind,
    LexemeKind,
    LexemeState,
    ObservationPolarity,
    ObservationSource,
    TombstoneReason,
    VariantProvenance,
)
from psm.domain.models import (
    Adjudication,
    Binding,
    Confidence,
    Guard,
    Lexeme,
    MemorySnapshot,
    Observation,
    Tombstone,
    Variant,
)

ALL_TABLES = (
    "evidence_link", "phonetic_key", "binding", "guard", "variant",
    "edge", "tombstone", "observation", "lexeme", "adjudication",
)


def _adapt_datetime(value: datetime) -> str:
    """Store datetimes as timezone-aware ISO-8601 strings.

    Python's built-in sqlite3 datetime adapter is deprecated in 3.12 and slated
    for removal, and it drops the timezone besides - which matters here, because
    every decay calculation is a subtraction of two instants and a naive one
    would silently be read back as UTC on one machine and local time on another.
    Registering explicitly makes the format ours and the warning go away.
    """
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


sqlite3.register_adapter(datetime, _adapt_datetime)


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqliteStore:
    """Implements ObservationLog, MemoryStore and AdjudicationLog.

    One class because they share a connection and a transaction boundary; three
    ports because they have three different lifetimes and callers depend on
    only the part they need.
    """

    def __init__(self, url: str = "sqlite:///./data/psm.db") -> None:
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.url = url
        self.engine = create_engine(url, future=True)

    # -- observation log ---------------------------------------------------- #

    def append(self, observation: Observation) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "insert into observation (id, source, polarity, at, before_form,"
                    " after_form, scope, scope_ref, utterance_id, surrounding_text,"
                    " lexeme_id, phonetic_distance, accepted, note, meta_json)"
                    " values (:id, :source, :polarity, :at, :before, :after, :scope,"
                    " :scope_ref, :utterance_id, :surrounding, :lexeme_id, :distance,"
                    " :accepted, :note, :meta)"
                ),
                {
                    "id": observation.id,
                    "source": str(observation.source),
                    "polarity": str(observation.polarity),
                    "at": observation.at,
                    "before": observation.before,
                    "after": observation.after,
                    "scope": str(observation.binding.scope),
                    "scope_ref": observation.binding.ref,
                    "utterance_id": observation.utterance_id,
                    "surrounding": observation.surrounding_text,
                    "lexeme_id": observation.lexeme_id,
                    "distance": observation.phonetic_distance,
                    "accepted": observation.accepted,
                    "note": observation.note,
                    "meta": json.dumps(dict(observation.meta)) if observation.meta else None,
                },
            )

    def all(self, *, until: datetime | None = None) -> list[Observation]:
        sql = "select * from observation"
        params: dict = {}
        if until is not None:
            sql += " where at <= :until"
            params["until"] = until
        sql += " order by at, id"
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [self._observation(r) for r in rows]

    def for_lexeme(self, lexeme_id: str) -> list[Observation]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("select * from observation where lexeme_id = :id order by at"),
                {"id": lexeme_id},
            ).mappings().all()
        return [self._observation(r) for r in rows]

    def truncate(self) -> None:
        self.clear()

    @staticmethod
    def _observation(row) -> Observation:
        return Observation(
            id=row["id"],
            source=ObservationSource(row["source"]),
            polarity=ObservationPolarity(row["polarity"]),
            at=_dt(row["at"]),
            before=row["before_form"],
            after=row["after_form"],
            binding=Binding(BindingScope(row["scope"]), row["scope_ref"]),
            utterance_id=row["utterance_id"],
            surrounding_text=row["surrounding_text"],
            lexeme_id=row["lexeme_id"],
            phonetic_distance=row["phonetic_distance"],
            accepted=None if row["accepted"] is None else bool(row["accepted"]),
            note=row["note"],
            meta=json.loads(row["meta_json"]) if row["meta_json"] else {},
        )

    # -- memory store ------------------------------------------------------- #

    def put(self, lexemes: Iterable[Lexeme]) -> None:
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            for lexeme in lexemes:
                conn.execute(
                    text("delete from lexeme where id = :id"), {"id": lexeme.id}
                )
                conn.execute(
                    text(
                        "insert into lexeme (id, canonical, kind, instruction, parent_id,"
                        " conf_alpha, conf_beta, prior_alpha, prior_beta, state,"
                        " learning_enabled, first_seen, last_used, created_at, updated_at)"
                        " values (:id, :canonical, :kind, :instruction, :parent, :a, :b,"
                        " :pa, :pb, :state, :learning, :first_seen, :last_used, :now, :now)"
                    ),
                    {
                        "id": lexeme.id,
                        "canonical": lexeme.canonical,
                        "kind": str(lexeme.kind),
                        "instruction": lexeme.instruction,
                        "parent": lexeme.parent_id,
                        "a": lexeme.confidence.alpha,
                        "b": lexeme.confidence.beta,
                        "pa": lexeme.prior.alpha,
                        "pb": lexeme.prior.beta,
                        "state": str(lexeme.state),
                        "learning": lexeme.learning_enabled,
                        "first_seen": lexeme.first_seen,
                        "last_used": lexeme.last_used,
                        "now": now,
                    },
                )
                for variant in lexeme.variants:
                    conn.execute(
                        text(
                            "insert or ignore into variant (lexeme_id, form, form_norm,"
                            " provenance, count, last_seen, scope, scope_ref)"
                            " values (:id, :form, :norm, :prov, :count, :seen, :scope, :ref)"
                        ),
                        {
                            "id": lexeme.id,
                            "form": variant.form,
                            "norm": " ".join(variant.form.casefold().split()),
                            "prov": str(variant.provenance),
                            "count": variant.count,
                            "seen": variant.last_seen,
                            "scope": str(variant.binding.scope),
                            "ref": variant.binding.ref,
                        },
                    )
                for guard in lexeme.guards:
                    conn.execute(
                        text(
                            "insert into guard (lexeme_id, kind, payload_json, note,"
                            " created_by_observation_id, created_at)"
                            " values (:id, :kind, :payload, :note, :obs, :now)"
                        ),
                        {
                            "id": lexeme.id,
                            "kind": str(guard.kind),
                            "payload": json.dumps(dict(guard.payload)),
                            "note": guard.note,
                            "obs": guard.created_by_observation_id,
                            "now": now,
                        },
                    )
                for binding in lexeme.bindings:
                    conn.execute(
                        text(
                            "insert or ignore into binding (lexeme_id, scope, scope_ref)"
                            " values (:id, :scope, :ref)"
                        ),
                        {"id": lexeme.id, "scope": str(binding.scope), "ref": binding.ref},
                    )

    def get(self, lexeme_id: str) -> Lexeme | None:
        return next((lx for lx in self.all_lexemes() if lx.id == lexeme_id), None)

    def all_lexemes(self) -> list[Lexeme]:
        with self.engine.begin() as conn:
            rows = conn.execute(text("select * from lexeme")).mappings().all()
            variants = conn.execute(text("select * from variant")).mappings().all()
            guards = conn.execute(text("select * from guard")).mappings().all()
            bindings = conn.execute(text("select * from binding")).mappings().all()

        by_lexeme_variants: dict[str, list[Variant]] = {}
        for v in variants:
            by_lexeme_variants.setdefault(v["lexeme_id"], []).append(
                Variant(
                    form=v["form"],
                    provenance=VariantProvenance(v["provenance"]),
                    count=v["count"],
                    last_seen=_dt(v["last_seen"]),
                    binding=Binding(BindingScope(v["scope"]), v["scope_ref"]),
                )
            )
        by_lexeme_guards: dict[str, list[Guard]] = {}
        for g in guards:
            by_lexeme_guards.setdefault(g["lexeme_id"], []).append(
                Guard(
                    kind=GuardKind(g["kind"]),
                    payload=json.loads(g["payload_json"] or "{}"),
                    created_by_observation_id=g["created_by_observation_id"],
                    note=g["note"],
                )
            )
        by_lexeme_bindings: dict[str, list[Binding]] = {}
        for b in bindings:
            by_lexeme_bindings.setdefault(b["lexeme_id"], []).append(
                Binding(BindingScope(b["scope"]), b["scope_ref"])
            )

        return [
            Lexeme(
                id=r["id"],
                canonical=r["canonical"],
                kind=LexemeKind(r["kind"]),
                instruction=r["instruction"],
                parent_id=r["parent_id"],
                variants=tuple(by_lexeme_variants.get(r["id"], ())),
                guards=tuple(by_lexeme_guards.get(r["id"], ())),
                bindings=tuple(by_lexeme_bindings.get(r["id"], ())) or (Binding(),),
                prior=Confidence(r["prior_alpha"], r["prior_beta"]),
                confidence=Confidence(r["conf_alpha"], r["conf_beta"]),
                state=LexemeState(r["state"]),
                learning_enabled=bool(r["learning_enabled"]),
                first_seen=_dt(r["first_seen"]),
                last_used=_dt(r["last_used"]),
            )
            for r in rows
        ]

    def edges(self) -> list[tuple[str, str, str, float]]:
        with self.engine.begin() as conn:
            rows = conn.execute(text("select a_id, b_id, rel, weight from edge")).all()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def put_edges(self, edges: Iterable[tuple[str, str, str, float]]) -> None:
        with self.engine.begin() as conn:
            for a, b, rel, weight in edges:
                conn.execute(
                    text(
                        "insert or replace into edge (a_id, b_id, rel, weight, observed_count)"
                        " values (:a, :b, :rel, :w, 0)"
                    ),
                    {"a": a, "b": b, "rel": rel, "w": weight},
                )

    def tombstones(self) -> list[Tombstone]:
        with self.engine.begin() as conn:
            rows = conn.execute(text("select * from tombstone")).mappings().all()
        return [
            Tombstone(
                id=r["id"],
                reason=TombstoneReason(r["reason"]),
                canonical=r["canonical"],
                match_forms=tuple(json.loads(r["match_forms_json"] or "[]")),
                source_lexeme_id=r["source_lexeme_id"],
                replacement_lexeme_id=r["replacement_lexeme_id"],
                created_at=_dt(r["created_at"]),
            )
            for r in rows
        ]

    def put_tombstones(self, tombstones: Iterable[Tombstone]) -> None:
        with self.engine.begin() as conn:
            for t in tombstones:
                conn.execute(
                    text(
                        "insert or replace into tombstone (id, reason, canonical,"
                        " match_forms_json, source_lexeme_id, replacement_lexeme_id, created_at)"
                        " values (:id, :reason, :canonical, :forms, :source, :repl, :now)"
                    ),
                    {
                        "id": t.id,
                        "reason": str(t.reason),
                        "canonical": t.canonical,
                        "forms": json.dumps(list(t.match_forms)),
                        "source": t.source_lexeme_id,
                        "repl": t.replacement_lexeme_id,
                        "now": t.created_at or datetime.now(UTC),
                    },
                )

    def snapshot(self) -> MemorySnapshot:
        with self.engine.begin() as conn:
            count = conn.execute(text("select count(*) from observation")).scalar_one()
        return MemorySnapshot(
            at=datetime.now(UTC),
            lexemes=tuple(self.all_lexemes()),
            tombstones=tuple(self.tombstones()),
            observation_count=count,
        )

    def clear(self) -> None:
        with self.engine.begin() as conn:
            for table in ALL_TABLES:
                conn.execute(text(f"delete from {table}"))

    # -- adjudication log --------------------------------------------------- #

    def record(self, adjudication: Adjudication) -> str:
        adjudication_id = str(uuid.uuid4())
        primary = adjudication.resolutions[0].reason if adjudication.resolutions else None
        applied = adjudication.applied
        if applied:
            primary = applied[0].reason
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "insert into adjudication (id, at, utterance_id, app, persona, asr_text,"
                    " formatted_text, output_text, gate_passed, intervened, verifier_rejected,"
                    " resolutions_json, primary_reason, llm_calls, prompt_tokens,"
                    " completion_tokens, cost_paise, latency_ms, observation_watermark)"
                    " values (:id, :at, :uid, :app, :persona, :asr, :fmt, :out, :gate, :inter,"
                    " :rejected, :res, :reason, :calls, :ptok, :ctok, :cost, :lat, :wm)"
                ),
                {
                    "id": adjudication_id,
                    "at": adjudication.at or datetime.now(UTC),
                    "uid": adjudication.utterance.utterance_id,
                    "app": adjudication.utterance.app,
                    "persona": adjudication.utterance.persona,
                    "asr": adjudication.utterance.asr_text,
                    "fmt": adjudication.utterance.formatted_text,
                    "out": adjudication.output_text,
                    "gate": adjudication.gate_passed,
                    "inter": adjudication.intervened,
                    "rejected": adjudication.verifier_rejected,
                    "res": json.dumps(serialise_resolutions(adjudication)),
                    "reason": str(primary) if primary else None,
                    "calls": adjudication.cost.llm_calls,
                    "ptok": adjudication.cost.prompt_tokens,
                    "ctok": adjudication.cost.completion_tokens,
                    "cost": adjudication.cost.cost_paise,
                    "lat": adjudication.cost.latency_ms,
                    "wm": 0,
                },
            )
        return adjudication_id

    def recent(self, limit: int = 50) -> Sequence[dict]:
        with self.engine.begin() as conn:
            return conn.execute(
                text("select * from adjudication order by at desc limit :n"), {"n": limit}
            ).mappings().all()


def serialise_resolutions(adjudication: Adjudication) -> list[dict]:
    """The audit trail, as JSON. Every candidate, every policy, every rationale
    - including the ones that led nowhere, because a near-miss is the most
    useful row in the evaluation report."""
    return [
        {
            "lexeme_id": r.candidate.lexeme.id,
            "canonical": r.candidate.lexeme.canonical,
            "span": [r.candidate.span.start, r.candidate.span.end, r.candidate.span.text],
            "matched_form": r.candidate.matched_form,
            "matched_via": r.candidate.matched_via,
            "retrieval_score": round(r.candidate.retrieval_score, 4),
            "verdict": str(r.verdict),
            "score": round(r.score, 4),
            "reason": str(r.reason),
            "replacement": r.replacement,
            "policies": [
                {
                    "policy": o.policy,
                    "signal": str(o.signal),
                    "weight": round(o.weight, 4),
                    "reason": str(o.reason) if o.reason else None,
                    "rationale": o.rationale,
                }
                for o in r.outcomes
            ],
        }
        for r in adjudication.resolutions
    ]
