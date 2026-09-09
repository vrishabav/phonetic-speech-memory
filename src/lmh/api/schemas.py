"""Serialisation between domain objects and JSON.

Kept apart from `app.py` so that the HTTP layer stays thin and so that the CLI,
the evaluation harness and the explorer can share one definition of what a
decision looks like on the wire. The explorer's `cases.jsonl` and this API
speak the same shapes on purpose: a reviewer who has read one can read the
other.
"""

from __future__ import annotations

from typing import Any

from lmh.domain.models import Adjudication, Lexeme, Resolution


def resolution_json(resolution: Resolution) -> dict[str, Any]:
    candidate = resolution.candidate
    return {
        "verdict": str(resolution.verdict),
        "reason": str(resolution.reason),
        "score": round(resolution.score, 4),
        "span": {
            "start": candidate.span.start,
            "end": candidate.span.end,
            "text": candidate.span.text,
        },
        "lexeme_id": candidate.lexeme.id,
        "canonical": candidate.lexeme.canonical,
        "matched_form": candidate.matched_form,
        "matched_via": candidate.matched_via,
        "retrieval_score": round(candidate.retrieval_score, 4),
        "replacement": resolution.replacement,
        # Every policy that had an opinion, in the order it was consulted, with
        # the sentence it gave. This is the "why" the brief asks for, and it is
        # produced by the engine rather than reconstructed here - a rationale
        # written by the presentation layer would be a plausible story rather
        # than a record.
        "policies": [
            {
                "policy": outcome.policy,
                "signal": str(outcome.signal),
                "weight": round(outcome.weight, 4),
                "reason": str(outcome.reason) if outcome.reason else None,
                "rationale": outcome.rationale,
            }
            for outcome in resolution.outcomes
        ],
    }


def adjudication_json(adjudication: Adjudication) -> dict[str, Any]:
    return {
        "asr_text": adjudication.utterance.asr_text,
        "formatted_text": adjudication.utterance.formatted_text,
        "output_text": adjudication.output_text,
        "intervened": adjudication.intervened,
        "gate_passed": adjudication.gate_passed,
        "verifier_rejected": adjudication.verifier_rejected,
        "app": adjudication.utterance.app,
        "cost": {
            "latency_ms": round(adjudication.cost.latency_ms, 3),
            "llm_calls": adjudication.cost.llm_calls,
            "prompt_tokens": adjudication.cost.prompt_tokens,
            "completion_tokens": adjudication.cost.completion_tokens,
        },
        "at": adjudication.at.isoformat() if adjudication.at else None,
        "resolutions": [resolution_json(r) for r in adjudication.resolutions],
        # A summary for the impatient, so the UI does not have to derive it and
        # then disagree with the API about what happened.
        "summary": _summary(adjudication),
    }


def _summary(adjudication: Adjudication) -> str:
    if not adjudication.gate_passed:
        return (
            "Nothing in memory resembled this text. The gate closed before "
            "retrieval, so this call cost nothing."
        )
    if not adjudication.resolutions:
        return "The gate opened but no candidate survived retrieval."
    applied = adjudication.applied
    proposed = adjudication.proposed
    if applied:
        changes = ", ".join(f"{r.candidate.span.text!r} -> {r.replacement!r}" for r in applied)
        return f"Applied {len(applied)} change(s): {changes}."
    if proposed:
        return (
            f"Proposed {len(proposed)} change(s) without applying any - the evidence "
            f"was enough to raise the question, not enough to act."
        )
    reasons = sorted({str(r.reason) for r in adjudication.abstained})
    return f"Abstained. {', '.join(reasons)}."


def lexeme_json(lexeme: Lexeme) -> dict[str, Any]:
    return {
        "id": lexeme.id,
        "canonical": lexeme.canonical,
        "kind": str(lexeme.kind),
        "state": str(lexeme.state),
        "instruction": lexeme.instruction,
        "confidence": round(lexeme.confidence.mean, 4),
        "strength": round(lexeme.confidence.strength, 4),
        "alpha": round(lexeme.confidence.alpha, 4),
        "beta": round(lexeme.confidence.beta, 4),
        "learning_enabled": lexeme.learning_enabled,
        "first_seen": lexeme.first_seen.isoformat() if lexeme.first_seen else None,
        "last_used": lexeme.last_used.isoformat() if lexeme.last_used else None,
        "bindings": [
            {"scope": str(b.scope), "ref": b.ref} for b in lexeme.bindings
        ],
        "variants": [
            {
                "form": v.form,
                "provenance": str(v.provenance),
                "count": v.count,
            }
            for v in lexeme.variants
        ],
        "guards": [
            {"kind": str(g.kind), "payload": dict(g.payload), "note": g.note}
            for g in lexeme.guards
        ],
    }
