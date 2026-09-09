"""The demonstration is part of the deliverable, so it is tested like one.

The brief names six things a reviewer must be able to do. There is one test per
capability, named after it, so that a failure says which promise broke rather
than which function did.

Each test drives the real FastAPI app through a real client. Nothing is mocked:
a demo that only works under mocks is not a demo.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lmh.api import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A fresh in-memory engine per test. The API keeps one process-wide engine
    # because it models one user's memory; the fixture resets that global so
    # tests cannot leak learned terms into one another.
    monkeypatch.setenv("LMH_STORE", "store.memory")
    monkeypatch.setenv("LMH_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    app_module._engine = None
    with TestClient(app_module.app) as c:
        yield c
    app_module._engine = None


# --------------------------------------------------------------------------- #
# The six capabilities
# --------------------------------------------------------------------------- #


def test_capability_2_inspect_memory(client):
    body = client.get("/memory").json()
    assert body["count"] > 0, "the demo seeds itself; an empty memory demos nothing"
    kivi = next(lx for lx in body["lexemes"] if lx["canonical"] == "Kivi")
    # Confidence and its evidence must both be visible: a number without the
    # observations behind it is not inspectable, it is just a number.
    assert kivi["state"] == "active"
    assert 0.0 < kivi["confidence"] <= 1.0
    assert kivi["variants"], "a term with no recorded forms cannot explain itself"
    assert any(g["kind"] == "common_word" for g in kivi["guards"])


def test_capability_3_and_4_memory_aware_result(client):
    r = client.post(
        "/dictate",
        json={
            "asr_text": "ask adith narayanan to review the pull request",
            "formatted_text": "Ask Adith Narayanan to review the pull request.",
            "app": "com.tinyspeck.slackmacgap",
        },
    ).json()
    assert r["output_text"] == "Ask Aadith Narayanan to review the pull request."
    assert r["intervened"] is True


def test_capability_5_explains_why_it_intervened(client):
    r = client.post(
        "/dictate",
        json={
            "asr_text": "the sarvam kiwi service is dropping requests",
            "formatted_text": "The Sarvam Kiwi service is dropping requests.",
            "app": "com.tinyspeck.slackmacgap",
        },
    ).json()
    applied = [x for x in r["resolutions"] if x["verdict"] == "apply"]
    assert applied, "expected an intervention to explain"
    decision = applied[0]
    assert decision["reason"]
    # Every policy that spoke must have said something a human can read. An
    # audit trail of bare enum values would satisfy a schema and no reviewer.
    spoke = [p for p in decision["policies"] if p["signal"] != "neutral"]
    assert spoke and all(p["rationale"] for p in spoke)


def test_capability_5_explains_why_it_did_not_intervene(client):
    """The harder half, and the one a dictionary cannot do."""
    r = client.post(
        "/dictate",
        json={
            "asr_text": "i ate a kiwi on the way in",
            "formatted_text": "I ate a kiwi on the way in.",
            "app": "com.tinyspeck.slackmacgap",
        },
    ).json()
    assert r["output_text"] == "I ate a kiwi on the way in."
    assert r["intervened"] is False
    vetoes = [
        p
        for res in r["resolutions"]
        for p in res["policies"]
        if p["signal"] == "veto"
    ]
    assert vetoes, "an abstention with no stated cause is indistinguishable from a bug"
    assert any(p["rationale"] for p in vetoes)


def test_capability_1_observation_reports_what_changed(client):
    before = {
        lx["canonical"]: lx["state"] for lx in client.get("/memory").json()["lexemes"]
    }
    assert "Nandini Rao" not in before

    r = client.post(
        "/observations",
        json={"after": "Nandini Rao", "source": "declared"},
    ).json()
    assert r["observation"]["source"] == "declared"
    assert r["memory_changes"], "the response must show the effect, not just acceptance"
    assert any("Nandini Rao" == c["canonical"] for c in r["memory_changes"])

    now = {lx["canonical"]: lx for lx in client.get("/memory").json()["lexemes"]}
    assert "Nandini Rao" in now


def test_capability_6_reset_and_repeat(client):
    client.post("/observations", json={"after": "Ephemeral Term", "source": "declared"})
    assert any(
        lx["canonical"] == "Ephemeral Term" for lx in client.get("/memory").json()["lexemes"]
    )

    client.post("/reset")
    after = client.get("/memory").json()
    assert not any(lx["canonical"] == "Ephemeral Term" for lx in after["lexemes"])
    # Reset means "back to the known starting point", not "empty" - an empty
    # system abstains from everything, which looks like correctness.
    assert after["count"] > 0


# --------------------------------------------------------------------------- #
# Properties the demo must not quietly lose
# --------------------------------------------------------------------------- #


def test_unrelated_text_costs_nothing(client):
    """The majority of real traffic. Note what is asserted and what is not:
    the *gate* may open on a chance phonetic collision, and that is allowed.
    What may never happen is a model call, a resolution, or a changed word."""
    r = client.post(
        "/dictate",
        json={
            "asr_text": (
                "i went through the whole document last night and the only thing i "
                "would change is the ordering of the last two sections"
            ),
            "formatted_text": (
                "I went through the whole document last night, and the only thing I "
                "would change is the ordering of the last two sections."
            ),
            "app": "com.microsoft.Outlook",
        },
    ).json()
    assert r["gate_passed"] is False
    assert r["cost"]["llm_calls"] == 0
    assert r["resolutions"] == []
    assert r["output_text"] == r["formatted_text"]


def test_scope_is_enforced_over_http(client):
    """The same input, two apps, two answers. If the API flattened scope this
    would pass in both places and the whole binding model would be decorative."""
    payload = {
        "asr_text": "i posted it in hash eng asr",
        "formatted_text": "I posted it in hash eng asr.",
    }
    slack = client.post("/dictate", json={**payload, "app": "com.tinyspeck.slackmacgap"}).json()
    mail = client.post("/dictate", json={**payload, "app": "com.microsoft.Outlook"}).json()
    assert "#eng-asr" in slack["output_text"]
    assert "#eng-asr" not in mail["output_text"]


def test_indic_script_survives_the_http_round_trip(client):
    """JSON, HTTP and the engine all have to agree about Unicode. They did not,
    once: the tokeniser dropped combining marks and produced a dangling matra."""
    r = client.post(
        "/dictate",
        json={
            "asr_text": "मिरा शर्मा को भेज दो",
            "formatted_text": "मिरा शर्मा को भेज दो।",
            "app": "com.tinyspeck.slackmacgap",
        },
    ).json()
    assert r["output_text"] == "मीरा शर्मा को भेज दो।"


def test_unknown_observation_source_is_a_422_not_a_500(client):
    r = client.post("/observations", json={"after": "x", "source": "telepathy"})
    assert r.status_code == 422
    assert "telepathy" in r.json()["detail"]


def test_health_reports_the_components_that_actually_ran(client):
    h = client.get("/health").json()
    assert h["ok"] is True
    assert h["components"]["policies"]
    assert h["components"]["llm"] == "llm.stub"


def test_the_page_serves_and_is_self_contained(client):
    import re

    page = client.get("/").text
    assert "language-memory-handler" in page

    # No CDN, no build step: `make serve` has to work on a fresh clone with no
    # network, and a blocked script or stylesheet would fail silently in the
    # browser rather than loudly in a test.
    #
    # The check is on what the page actually *fetches* - src/href values - not
    # on the substring "http", because an SVG data: URI legitimately contains
    # an xmlns of `http://www.w3.org/2000/svg`, which is a namespace name and
    # never resolved over the network.
    external = [
        url
        for url in re.findall(r"""(?:src|href)\s*=\s*["\']([^"\']+)""", page)
        if not url.startswith(("data:", "#", "/"))
    ]
    assert not external, f"the demo page loads external resources: {external}"
