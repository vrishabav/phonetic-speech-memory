"""Load a persona file into domain objects.

Shared by the CLI (`make seed`) and the evaluation harness, so the memory a
reviewer sees in the UI and the memory the evaluation runs against are built by
the same code from the same file. Two loaders would eventually disagree, and
the disagreement would show up as an unreproducible result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from psm.domain.enums import (
    BindingScope,
    GuardKind,
    LexemeKind,
    LexemeState,
    VariantProvenance,
)
from psm.domain.models import Binding, Confidence, Guard, Lexeme, Variant


def _dt(value, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def load_persona(payload: dict | str | Path, *, now: datetime | None = None):
    """Return (lexemes, edges).

    The persona file is written against a fixed reference date (`persona.clock`)
    and its entries are dated *relative* to it: most were last used "today",
    while Rukmini Iyer was deliberately last used nine months earlier so that
    she is dormant. Those relationships are the point - three fixture cases
    depend on them.

    `now` anchors that timeline. When it differs from the file's reference date,
    every date shifts by the same delta, so the relative ages survive:

        persona.clock  2026-01-15   Kivi: today      Rukmini: -288 days
        now            2026-09-06   Kivi: today      Rukmini: -288 days

    The evaluation passes its frozen clock, so results are identical on any day
    the suite runs. The CLI passes real time, so a freshly seeded demo is not
    immediately eight months stale - which it was before this shift existed, and
    the symptom was every lexeme reporting itself dormant on day one.
    """
    if isinstance(payload, (str, Path)):
        payload = json.loads(Path(payload).read_text(encoding="utf-8"))

    reference = _dt(payload.get("persona", {}).get("clock"), datetime.now(UTC))
    clock = now or reference
    shift = clock - reference

    lexemes: list[Lexeme] = []

    for entry in payload["lexemes"]:
        confidence = entry.get("confidence", {})
        last_used = _dt(entry.get("last_used"), reference) + shift
        lexemes.append(
            Lexeme(
                id=entry["id"],
                canonical=entry["canonical"],
                kind=LexemeKind(entry["kind"]),
                instruction=entry.get("instruction"),
                variants=tuple(
                    Variant(
                        form=v["form"],
                        provenance=VariantProvenance(v["provenance"]),
                        count=v.get("count", 0),
                        last_seen=last_used,
                    )
                    for v in entry.get("variants", [])
                ),
                guards=tuple(
                    Guard(kind=GuardKind(g["kind"]), payload=g.get("payload", {}))
                    for g in entry.get("guards", [])
                ),
                bindings=tuple(
                    Binding(BindingScope(b["scope"]), b.get("ref"))
                    for b in entry.get("bindings", [{"scope": "global"}])
                ),
                # A persona describes a user who has been dictating for months.
                # Its confidence is evidence from before the log starts, so it
                # is loaded as the prior and the projector derives the rest.
                prior=Confidence(
                    float(confidence.get("alpha", 1.0)), float(confidence.get("beta", 1.0))
                ),
                confidence=Confidence(
                    float(confidence.get("alpha", 1.0)), float(confidence.get("beta", 1.0))
                ),
                state=LexemeState(entry.get("state", "proposed")),
                learning_enabled=entry.get("learning_enabled", True),
                first_seen=clock,
                last_used=last_used,
            )
        )

    edges = [
        (e["a"], e["b"], e["rel"], float(e.get("weight", 1.0)))
        for e in payload.get("edges", [])
    ]
    return lexemes, edges
