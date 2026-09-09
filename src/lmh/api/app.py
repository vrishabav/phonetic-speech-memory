"""The runnable demonstration.

The brief asks that a reviewer be able to do six things. Each maps to exactly
one endpoint, and the UI at `/` is a thin client over them:

  1. provide observations                  POST /observations
  2. inspect the resulting memory          GET  /memory
  3. provide new ASR + formatted text      POST /dictate
  4. see the memory-aware result           (same response)
  5. understand why it did or did not act  (same response: `resolutions`)
  6. reset and repeat                      POST /reset

and one the brief does not ask for, because eight examples in a page are an
illustration and the evaluation is the evidence:

  -. see all 1,926 evaluation cases       GET  /explorer

Recognition itself is not here, and that is a decision rather than an omission.
The system's input is text a recogniser already produced; the recogniser is
upstream, owned by the platform, and swapping in a small offline model so a
reviewer could speak into the page made that model's accuracy the thing under
evaluation instead of the memory system. Text in, text out, is also exactly the
contract the evaluation harness measures, so what a reviewer sees in the browser
and what the numbers describe are the same thing.

There is no capability behind a button that is not also on the API and in the
CLI. That is deliberate: a demo that can do things the API cannot is a demo of
the demo.

State lives in one process-wide Engine over the configured store. This is a
single-user personal-memory system, so a single instance is the honest model;
the API is not the scaling story and pretending otherwise would add locking
that nothing in the design needs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from lmh.api.schemas import adjudication_json, lexeme_json
from lmh.api.ui import PAGE
from lmh.config import Settings, from_env
from lmh.domain.enums import ObservationSource
from lmh.domain.models import Binding, BindingScope, Utterance
from lmh.engine.engine import Engine
from lmh.engine.learner import observation as make_observation
from lmh.seed import load_persona

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PERSONA = ROOT / "evals" / "data" / "persona_seed.json"
EXPLORER = ROOT / "evals" / "results" / "explorer.html"

app = FastAPI(
    title="language-memory-handler",
    version="1.0",
    description=__doc__,
)

_engine: Engine | None = None

#: Construction only. FastAPI serves sync endpoints from a threadpool, so the
#: page's first two calls - `/health` and `/memory` - arrive genuinely at once,
#: and without this both of them ran the migration and one of them lost. This is
#: not a concurrency story about memory (there isn't one, by D-012); it is the
#: ordinary requirement that initialisation happen once.
_building = threading.Lock()


def engine() -> Engine:
    """The one process-wide Engine, built and made usable on first request.

    Two kinds of emptiness are healed here rather than reported, because both
    of them used to produce the same useless demo: a page that renders, and
    every button on it returning a 500.

    *No schema.* `make serve` before `make seed` left an empty SQLite file, and
    the first query died on `no such table: lexeme`. The migration still owns
    the schema - this runs it, it does not duplicate it.

    *No memory.* An empty system abstains from everything, which looks like
    correctness and is actually silence.

    Both are done under a lock, because the page's first two calls arrive
    together and a migration run twice is a 503 on one of them.
    """
    global _engine
    if _engine is not None:
        return _engine
    with _building:
        if _engine is not None:  # another thread built it while we waited
            return _engine
        settings = from_env()
        try:
            built = Engine.build(settings)
            empty = not built.lexemes
        except OperationalError:
            _migrate(settings.database_url)
            built = Engine.build(settings)
            empty = True
        if empty and DEFAULT_PERSONA.exists():
            _reseed(built)
        _engine = built
    return _engine


def _migrate(database_url: str) -> None:
    """Bring the database up to head, in a subprocess.

    Alembic is invoked out of process on purpose: `command.upgrade` reconfigures
    the root logger from `alembic.ini`, which inside a running uvicorn means the
    server's own logging changes underneath it as a side effect of one request.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "LMH_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(
            503,
            "the database has no schema and the migration could not create one. "
            f"Run `make seed` and restart. Alembic said: {result.stderr.strip()[-400:]}",
        )


def _reseed(target: Engine) -> None:
    lexemes, edges = load_persona(DEFAULT_PERSONA, now=target.now())
    target.load(lexemes=lexemes, edges=edges)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class DictateBody(BaseModel):
    asr_text: str = Field(..., description="Raw recogniser output")
    formatted_text: str | None = Field(
        None,
        description=(
            "Output of the formatting stage. Omit it to run the formatter too - "
            "with the default passthrough formatter that simply means the ASR "
            "text is used unchanged."
        ),
    )
    app: str | None = Field(None, description="Bundle id of the target application")
    persona: str | None = None
    surrounding_text: str | None = Field(None, description="Text visible on screen")


class ObservationBody(BaseModel):
    after: str = Field(..., description="The form the user settled on")
    before: str | None = Field(None, description="The form that was there first, if any")
    source: str = Field("post_edit")
    app: str | None = None
    note: str | None = Field(None, description="A standing instruction, in the user's words")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return PAGE


@app.get("/health")
def health() -> dict[str, Any]:
    e = engine()
    settings: Settings = e.settings
    return {
        "ok": True,
        "lexemes": len(e.lexemes),
        "components": settings.describe(),
        "explorer": EXPLORER.exists(),
    }


@app.get("/explorer", response_class=HTMLResponse)
def explorer():
    """The case explorer, served from the demo rather than found on disk.

    It is the same `evals/results/explorer.html` that `make explore` writes -
    every specification case in full detail and every derived case filterable
    by family, script, confusion rule and pass/fail. It is the strongest piece
    of evidence in the repository and it was previously a file a reviewer had
    to know to open, so the demo now links to it.

    If it has not been built, build it here. The results directory is an
    artefact, not a source file: a reviewer who clones and runs `make serve`
    should get the page, not a 404 about a missing file. It takes a second or
    two, once.
    """
    if not EXPLORER.exists():
        result = subprocess.run(
            [sys.executable, "-m", "lmh.cli", "explore"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not EXPLORER.exists():
            raise HTTPException(
                503,
                "the case explorer has not been built and could not be built now. "
                f"Run `make explore`. It said: {result.stderr.strip()[-400:]}",
            )
    return FileResponse(EXPLORER, media_type="text/html")


@app.post("/dictate")
def dictate(body: DictateBody) -> dict[str, Any]:
    """Capability 3, 4 and 5: text in, memory-aware text out, with the reasoning.

    If `formatted_text` is supplied the formatting stage is skipped and the
    memory system is measured on its own - the same contract the evaluation
    uses. If it is omitted, the configured formatter runs first.
    """
    e = engine()
    if body.formatted_text is None:
        adjudication = e.dictate(
            body.asr_text,
            app=body.app,
            persona=body.persona,
            surrounding_text=body.surrounding_text,
        )
    else:
        adjudication = e.handle(
            Utterance(
                asr_text=body.asr_text,
                formatted_text=body.formatted_text,
                app=body.app,
                persona=body.persona,
                surrounding_text=body.surrounding_text,
            )
        )
    return adjudication_json(adjudication)


@app.post("/observations")
def observe(body: ObservationBody) -> dict[str, Any]:
    """Capability 1: give the system a piece of evidence and watch memory move."""
    e = engine()
    try:
        source = ObservationSource(body.source)
    except ValueError as exc:
        raise HTTPException(
            422,
            f"unknown source {body.source!r}. Known: "
            f"{', '.join(s.value for s in ObservationSource)}",
        ) from exc

    before = {lx.id: (lx.state, lx.confidence.mean) for lx in e.lexemes}
    judged = e.observe(
        make_observation(
            source,
            body.after,
            at=e.now(),
            before=body.before,
            binding=Binding(BindingScope.APP, body.app) if body.app else None,
            note=body.note,
        )
    )
    # Report the *effect*, not just the acceptance. "Recorded" tells a reviewer
    # nothing; "this term moved from proposed to active" is the observable that
    # the whole learning design exists to produce.
    changes = []
    for lx in e.lexemes:
        was = before.get(lx.id)
        if was is None:
            changes.append({"canonical": lx.canonical, "change": "created", "state": str(lx.state)})
        elif was[0] != lx.state:
            changes.append(
                {
                    "canonical": lx.canonical,
                    "change": f"{was[0]} -> {lx.state}",
                    "confidence": round(lx.confidence.mean, 3),
                }
            )
        elif round(was[1], 3) != round(lx.confidence.mean, 3):
            # Rounded to what is actually displayed, not compared exactly. Every
            # confidence is a decayed quantity read against the clock, so the two
            # projections either side of an observation are microseconds apart
            # and *every* term differs in the twelfth decimal place. Reporting
            # those listed all 24 terms as "0.833 -> 0.833" and buried the one
            # that moved - a report that names everything names nothing.
            changes.append(
                {
                    "canonical": lx.canonical,
                    "change": f"confidence {was[1]:.3f} -> {lx.confidence.mean:.3f}",
                    "state": str(lx.state),
                }
            )
    return {
        "observation": {
            "id": judged.id,
            "source": str(judged.source),
            "before": judged.before,
            "after": judged.after,
            "polarity": str(judged.polarity),
            "attributed_to": judged.lexeme_id,
        },
        "memory_changes": changes,
    }


@app.get("/memory")
def memory(state: str | None = None, q: str | None = None) -> dict[str, Any]:
    """Capability 2: the whole of memory, with the evidence behind each entry."""
    e = engine()
    rows = [lexeme_json(lx) for lx in e.lexemes]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if q:
        needle = q.casefold()
        rows = [
            r
            for r in rows
            if needle in r["canonical"].casefold()
            or any(needle in v["form"].casefold() for v in r["variants"])
        ]
    rows.sort(key=lambda r: r["canonical"].casefold())
    return {"count": len(rows), "lexemes": rows, "at": e.now().isoformat()}


@app.get("/memory/{lexeme_id}")
def memory_one(lexeme_id: str) -> dict[str, Any]:
    e = engine()
    for lx in e.lexemes:
        if lx.id == lexeme_id:
            return lexeme_json(lx)
    raise HTTPException(404, f"no lexeme {lexeme_id!r}")


@app.post("/reset")
def reset(seed: bool = True) -> dict[str, Any]:
    """Capability 6: back to a known state, so a demonstration can be repeated.

    Resetting to the *seeded* persona rather than to empty is the useful
    default: an empty system abstains from everything, which looks like
    correctness and is actually silence.
    """
    e = engine()
    e.reset()
    if seed:
        _reseed(e)
    return {"ok": True, "lexemes": len(e.lexemes), "seeded": seed}


@app.exception_handler(ValueError)
def _value_error(_request, exc: ValueError) -> JSONResponse:  # pragma: no cover
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    """Any other failure, as JSON with the reason in it.

    Without this, an unexpected server-side error reaches the browser as
    Starlette's plain-text `Internal Server Error`, the page's `response.json()`
    throws, and the reviewer is told "unreadable response" - which describes
    the client's problem rather than the server's. The traceback still goes to
    the terminal; this only decides what the page is able to say.
    """
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )
