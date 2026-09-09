"""The live model path, exercised end to end against a stub endpoint.

Everything else in this repository runs offline and makes zero model calls,
which is what makes every committed number reproducible. The cost of that is
that the one path a reviewer cannot check - memory conditioning the formatting
prompt, a real HTTP request, and the verifier deciding whether the reply
overreached - was for a long time only tested for construction. "The live path
is lightly exercised" was a true sentence in the report and a gap in the work.

It is not a gap that needs a network. The adapter speaks the OpenAI
chat-completions protocol over `urllib`, so a socket on localhost serving a
canned response drives the entire chain: `SarvamModel` builds and
sends the request, `LLMFormatter` builds the memory-conditioned prompt from
real lexemes, and the verifier judges the reply. The only thing not covered is
whether a real model writes good prose, which is not this project's claim.

Each test asserts something different about that chain:

  * the request carries the memory into the prompt, and the reply comes back;
  * a reply that rewrites rather than formats is rejected, and the deterministic
    text stands;
  * an endpoint that errors degrades to the unconditioned text instead of
    taking dictation down with it;
  * the ablation switch really does remove the memory block from the prompt.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from psm.adapters.formatter.llm_formatter import LLMFormatter
from psm.adapters.llm.sarvam import SarvamModel
from psm.domain.enums import LexemeKind, LexemeState, VariantProvenance
from psm.domain.models import Confidence, Lexeme, Utterance, Variant


class _Handler(BaseHTTPRequestHandler):
    """Records the request it was given and replies with whatever is queued."""

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's interface
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append(  # type: ignore[attr-defined]
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
        )
        status, reply = self.server.reply  # type: ignore[attr-defined]
        payload = json.dumps(
            {
                "model": "stub-1",
                "choices": [{"message": {"content": reply}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):  # keep the test output readable
        return


@pytest.fixture
def endpoint():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.reply = (200, "")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def model_for(endpoint) -> SarvamModel:
    return SarvamModel(
        api_key="test-key", base_url=endpoint.base_url, model="stub-1", timeout=5.0
    )


MEMORY = (
    Lexeme(
        id="lex.kivi",
        canonical="Kivi",
        kind=LexemeKind.PRODUCT,
        state=LexemeState.ACTIVE,
        confidence=Confidence(7.0, 1.0),
        instruction='the dictation product; always capitalised, never "kiwi"',
        variants=(Variant(form="kiwi", provenance=VariantProvenance.OBSERVED, count=6),),
    ),
)
UTTERANCE = Utterance(
    asr_text="the sarvam kiwi service is dropping requests",
    formatted_text="",
    app="com.tinyspeck.slackmacgap",
)


def test_the_request_carries_memory_and_the_reply_comes_back(endpoint):
    endpoint.reply = (200, "The Sarvam Kivi service is dropping requests.")
    formatter = LLMFormatter(model_for(endpoint))

    out = formatter.format(
        UTTERANCE, lexemes=MEMORY, instructions=[m.instruction for m in MEMORY]
    )

    assert out == "The Sarvam Kivi service is dropping requests."
    assert len(endpoint.requests) == 1
    request = endpoint.requests[0]
    assert request["path"].endswith("/chat/completions")
    assert request["auth"] == "Bearer test-key"

    system = request["body"]["messages"][0]["content"]
    user = request["body"]["messages"][1]["content"]
    # The whole architectural claim of the live path: the canonical form and the
    # standing instruction reach the model *before* it writes, which is the one
    # thing a post-hoc replace stage can never do.
    assert "Kivi" in system and "heard as: kiwi" in system
    assert 'never "kiwi"' in system
    assert user == UTTERANCE.asr_text
    assert request["body"]["temperature"] == 0.0


def test_a_reply_that_rewrites_rather_than_formats_is_rejected(endpoint):
    """A model given a rewriting brief will sometimes rewrite. The verifier is
    the only place that can be caught, and on rejection the deterministic text
    has to stand."""
    endpoint.reply = (200, "Could you please take a look at the outage when you get a chance?")
    formatter = LLMFormatter(model_for(endpoint))

    out = formatter.format(UTTERANCE, lexemes=MEMORY)

    assert out == UTTERANCE.asr_text, "an overreaching reply must not reach the user"
    assert formatter.rejections == 1


def test_an_endpoint_that_errors_does_not_take_dictation_down(endpoint):
    endpoint.reply = (500, "upstream is unwell")
    formatter = LLMFormatter(model_for(endpoint))

    out = formatter.format(UTTERANCE, lexemes=MEMORY)

    assert out == UTTERANCE.asr_text
    assert formatter.calls == 1


def test_the_no_memory_ablation_really_removes_the_memory(endpoint):
    """`allow_prompt_injection=False` is the no-memory baseline, and it only means
    anything if it runs through this same code path with the block gone."""
    endpoint.reply = (200, "The Sarvam kiwi service is dropping requests.")
    formatter = LLMFormatter(model_for(endpoint), allow_prompt_injection=False)

    formatter.format(UTTERANCE, lexemes=MEMORY, instructions=["never write kiwi"])

    system = endpoint.requests[0]["body"]["messages"][0]["content"]
    assert "Kivi" not in system
    assert "never write kiwi" not in system


def test_the_key_never_appears_in_the_prompt_or_the_result(endpoint):
    endpoint.reply = (200, "The Sarvam Kivi service is dropping requests.")
    model = model_for(endpoint)
    response = model.complete(system="s", user="u")

    assert "test-key" not in json.dumps(endpoint.requests[0]["body"])
    assert "test-key" not in response.text
    assert response.prompt_tokens == 11 and response.completion_tokens == 7
    assert model.calls == 1
