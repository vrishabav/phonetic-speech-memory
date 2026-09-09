"""The runnable demonstration, tested as a deliverable.

One thing is covered here that nothing else covers: **the page's JavaScript.**
The client is ~200 lines of JS embedded in a Python string, which means the
compiler that would normally catch a stray bracket never sees it. A syntax error
there produces a blank page and a green test suite. This asserts that the browser
could parse it, using `node --check` when Node is present and a bracket-balance
check when it is not.

The rest is the same contract the evaluation measures - ASR text and formatted
text in, memory-aware text and reasoning out - driven through the real app, so
the buttons on the page cannot quietly stop matching their labels.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from psm.api import app as app_module

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PSM_STORE", "store.memory")
    monkeypatch.setenv("PSM_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    app_module._engine = None
    with TestClient(app_module.app) as c:
        yield c
    app_module._engine = None


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #


def _script(page: str) -> str:
    return page.split("<script>")[1].split("</script>")[0]


def test_the_page_javascript_parses(client):
    """A stray bracket in the embedded client produces a blank page and a green
    test suite, because no compiler ever sees this code. It happened once."""
    js = _script(client.get("/").text)
    node = shutil.which("node")
    if node:
        source = Path(__file__).parent / "_ui_check.js"
        source.write_text(js, encoding="utf-8")
        try:
            result = subprocess.run(
                [node, "--check", str(source)], capture_output=True, text=True
            )
            assert result.returncode == 0, result.stderr
        finally:
            source.unlink(missing_ok=True)
    else:  # pragma: no cover - depends on the machine
        for open_ch, close_ch in ("{}", "()", "[]"):
            assert js.count(open_ch) == js.count(close_ch), f"unbalanced {open_ch}{close_ch}"


def test_the_page_wires_every_endpoint_it_claims(client):
    js = _script(client.get("/").text)
    for endpoint in ("/dictate", "/observations", "/memory", "/reset", "/health"):
        assert endpoint in js, f"the page never calls {endpoint}"


def test_the_page_offers_no_capability_the_api_lacks(client):
    """The page is a thin client over the JSON API, and the value of saying so
    depends on it staying true. Every path the client fetches must exist in the
    published schema."""
    js = _script(client.get("/").text)
    spec = json.loads(client.get("/openapi.json").text)
    import re

    called = {m.split("?")[0] for m in re.findall(r"""['"](/[a-z/]*)['"]""", js)}
    for path in called - {"/"}:
        assert path in spec["paths"], f"the page calls {path}, which the API does not expose"


def test_the_page_stays_self_contained(client):
    """`make serve` has to work on a fresh clone with no network. A blocked
    script tag fails silently in the browser rather than loudly here."""
    import re

    page = client.get("/").text
    external = [
        url
        for url in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)""", page)
        if not url.startswith(("data:", "#", "/"))
    ]
    assert not external, f"the demo page loads external resources: {external}"


def test_the_prepared_examples_all_behave_as_advertised(client):
    """Every one-click example in the page is run through the API, and the three
    labelled 'must NOT change' are asserted to change nothing. A demo whose
    buttons quietly stopped matching their labels would be worse than none."""
    js = _script(client.get("/").text)
    block = js.split("const EXAMPLES = [", 1)[1].split("];", 1)[0]
    labels = [line for line in block.splitlines() if "{t:" in line]
    assert len(labels) >= 6, "the example list shrank"

    must_not_change = [
        {
            "asr_text": "i ate a kiwi for breakfast",
            "formatted_text": "I ate a kiwi for breakfast.",
            "app": "com.microsoft.Outlook",
        },
        {
            "asr_text": "i posted the trace in hash eng asr",
            "formatted_text": "I posted the trace in hash eng asr.",
            "app": "com.microsoft.Outlook",
        },
    ]
    for payload in must_not_change:
        d = client.post("/dictate", json=payload).json()
        assert d["output_text"] == payload["formatted_text"], d["summary"]

    must_change = {
        "asr_text": "the sarvam kiwi service is dropping requests",
        "formatted_text": "The Sarvam Kiwi service is dropping requests.",
        "app": "com.tinyspeck.slackmacgap",
    }
    d = client.post("/dictate", json=must_change).json()
    assert d["output_text"] == "The Sarvam Kivi service is dropping requests."


def test_omitting_formatted_text_runs_the_formatting_stage(client):
    """The second box on the page may be left blank. That is not a shortcut for
    'skip formatting' - it means run the configured formatter, which under the
    default passthrough adapter returns the ASR text unchanged."""
    d = client.post("/dictate", json={"asr_text": "i ate a kiwi for breakfast"}).json()
    assert d["formatted_text"] == "i ate a kiwi for breakfast"
    assert "output_text" in d and "resolutions" in d


def test_the_demo_survives_a_database_with_no_schema(tmp_path, monkeypatch):
    """`make serve` before `make seed` used to produce the worst possible demo:
    the page rendered, and every button on it returned a bare 500 whose body was
    not even JSON, so the interface said "API unreachable" about a server that
    was running perfectly. The migration still owns the schema; the app now runs
    it rather than reporting its absence."""
    monkeypatch.setenv("PSM_STORE", "store.sqlite")
    monkeypatch.setenv("PSM_DATABASE_URL", f"sqlite:///{tmp_path}/fresh.db")
    app_module._engine = None
    try:
        with TestClient(app_module.app) as c:
            body = c.get("/health").json()
            assert body["ok"] is True
            assert body["lexemes"] > 0, "a migrated database should also be seeded"
            assert c.post(
                "/dictate",
                json={
                    "asr_text": "the sarvam kiwi service is dropping requests",
                    "formatted_text": "The Sarvam Kiwi service is dropping requests.",
                    "app": "com.tinyspeck.slackmacgap",
                },
            ).json()["output_text"] == "The Sarvam Kivi service is dropping requests."
    finally:
        app_module._engine = None


def test_an_unexpected_failure_arrives_as_json_with_a_reason(tmp_path, monkeypatch):
    """Starlette's default for an unhandled error is a plain-text body, which
    makes `response.json()` throw in the browser and leaves the page able to say
    only that the response was unreadable. The reason has to survive the trip."""
    monkeypatch.setenv("PSM_STORE", "store.memory")
    monkeypatch.setenv("PSM_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    app_module._engine = None
    with TestClient(app_module.app, raise_server_exceptions=False) as c:
        c.get("/health")

        def _boom(_lexeme):
            raise RuntimeError("the projector fell over")

        monkeypatch.setattr(app_module, "lexeme_json", _boom)
        r = c.get("/memory")
        assert r.status_code == 500
        assert "the projector fell over" in r.json()["detail"]
    app_module._engine = None


def test_teaching_reports_only_the_term_that_actually_moved(client):
    """The teach panel promises to report what changed. It used to report all 24
    terms - every confidence is decayed against the clock, so the projections
    either side of an observation differ in the twelfth decimal place for every
    term in memory, and the one that really moved was buried in the noise."""
    r = client.post(
        "/observations",
        json={"before": "Shreya Bhattacharya", "after": "Shreyaa Bhattacharya"},
    ).json()
    moved = [c["canonical"] for c in r["memory_changes"]]
    assert moved == ["Shreyaa Bhattacharya"], moved


def test_the_case_explorer_is_reachable_from_the_demo(client, tmp_path, monkeypatch):
    """The explorer is the strongest evidence in the repository and used to be a
    file a reviewer had to know to open. It is now a route, and the page links
    to it."""
    stand_in = tmp_path / "explorer.html"
    stand_in.write_text("<!doctype html><title>x</title>ok", encoding="utf-8")
    monkeypatch.setattr(app_module, "EXPLORER", stand_in)

    r = client.get("/explorer")
    assert r.status_code == 200
    assert "ok" in r.text

    page = client.get("/").text
    assert "/explorer" in page, "the demo never offers the explorer"
    assert client.get("/health").json()["explorer"] is True


def test_the_openapi_schema_is_generated(client):
    """The demo is not the only interface; the API has to be readable on its own
    at /docs, because that is where a reviewer checks that the page is a thin
    client rather than where the behaviour lives."""
    spec = json.loads(client.get("/openapi.json").text)
    for path in ("/dictate", "/observations", "/memory", "/reset"):
        assert path in spec["paths"], path


def test_the_first_two_requests_do_not_race_to_migrate(tmp_path, monkeypatch):
    """The page opens `/health` and `/memory` at the same moment. FastAPI serves
    sync endpoints from a threadpool, so on a database with no schema both of
    them used to run the migration and one of them lost with a 503 - the demo
    coming up half-broken on exactly the run where the healing mattered."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("PSM_STORE", "store.sqlite")
    monkeypatch.setenv("PSM_DATABASE_URL", f"sqlite:///{tmp_path}/race.db")
    app_module._engine = None
    try:
        with TestClient(app_module.app) as c:
            with ThreadPoolExecutor(max_workers=4) as pool:
                codes = [
                    f.result().status_code
                    for f in [pool.submit(c.get, p) for p in
                              ("/health", "/memory", "/health", "/memory")]
                ]
        assert codes == [200, 200, 200, 200], codes
    finally:
        app_module._engine = None
