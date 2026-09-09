"""Automatic guard synthesis.

A `common_word` guard says: *this term's surface form is also an ordinary
English word, so it must earn its correction from context rather than firing on
every occurrence.* Without one, a memory for the acronym **WER** rewrites every
occurrence of the word **were**.

That is not hypothetical. It was measured: a 367-term memory run over 4,000
sentences of real English prose produced 20 corruptions, and **every single one
was `were` -> `WER`.** One unguarded three-letter acronym accounted for the
entire false-positive rate.

The obvious answer - "write a guard for it" - does not scale and is not a
product. A user does not curate guard lists; they say a word and expect the
system to be sensible. So guards are **synthesised** from the memory itself:

  * if the canonical form is a common English word, guard it;
  * if any form the recogniser has produced for it is a common English word,
    guard that form;
  * very short all-caps acronyms are guarded regardless, because three letters
    collide with something in almost any language.

A synthesised guard never overwrites a hand-written one, and it carries a note
saying it was generated, so the memory inspector can show the difference.

The word list is a data file (`src/lmh/data/common_words.txt`), which is the
point: swapping in a proper frequency list, or the recogniser's own vocabulary,
is a file change. The mechanism is what is being claimed here, not the list.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from lmh.domain.enums import GuardKind, VariantProvenance
from lmh.domain.models import Guard, Lexeme

DATA = Path(__file__).resolve().parents[1] / "data" / "common_words.txt"

#: Generic engineering words that make a guarded technical term plausible.
#: Deliberately small and generic - a per-term list would be curation again.
DEFAULT_SUPPORT = (
    "service", "services", "endpoint", "endpoints", "deploy", "deployed", "deploys",
    "build", "builds", "release", "released", "ship", "shipped", "commit", "branch",
    "pull", "request", "review", "merge", "bug", "fix", "fixed", "crash", "logs",
    "latency", "throughput", "api", "server", "cluster", "pipeline", "model",
    "training", "eval", "dataset", "repo", "ticket", "sprint", "standup", "oncall",
)


@lru_cache(maxsize=1)
def common_words() -> frozenset[str]:
    if not DATA.exists():  # pragma: no cover - packaging failure
        return frozenset()
    return frozenset(
        line.strip().casefold()
        for line in DATA.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )


def is_common(form: str) -> bool:
    """Is this stretch of text just ordinary English?

    True when the form is a common word, and also when it is several words that
    are *all* common - because a run of ordinary words is ordinary text, however
    it happens to sound.

    The multi-word half is not hypothetical either. Before it existed, a memory
    for the name **Ishaan** rewrote the phrase **"is an"** in 14 sentences out
    of 1,500: two of the commonest words in English, which together sound
    almost exactly like the name. A single-token check cannot see that, because
    neither "is" nor "an" is the span being matched.

    A name made of uncommon words - "Kaveri Sengupta" - is not going to collide
    with running text and stays unguarded, so the system is not made timid.
    """
    words = form.strip().casefold().split()
    if not words:
        return False
    vocabulary = common_words()
    return all(word in vocabulary for word in words)


def looks_like_short_acronym(form: str) -> bool:
    """WER, CTC, BPE. Two to four letters, all capitals.

    Guarded on sight. A three-letter string collides with something in almost
    any vocabulary, and the cost of being wrong about an acronym is high
    precisely because acronyms appear in the middle of ordinary sentences.
    """
    return 2 <= len(form) <= 4 and form.isalpha() and form.isupper()


def synthesise(lexeme: Lexeme) -> Lexeme:
    """Return the lexeme with any missing common-word guards added."""
    if any(g.kind is GuardKind.COMMON_WORD for g in lexeme.guards):
        return lexeme  # a hand-written guard is authoritative

    risky: list[str] = []
    if is_common(lexeme.canonical) or looks_like_short_acronym(lexeme.canonical):
        risky.append(lexeme.canonical.casefold())
    for variant in lexeme.variants:
        # Only forms a recogniser really produced, or the user declared. A form
        # we merely generated is already weak enough not to need protecting.
        if variant.provenance is VariantProvenance.GENERATED:
            continue
        if is_common(variant.form):
            risky.append(variant.form.casefold())

    if not risky:
        return lexeme

    guards = tuple(lexeme.guards) + tuple(
        Guard(
            kind=GuardKind.COMMON_WORD,
            payload={"form": form, "support_tokens": list(DEFAULT_SUPPORT), "synthesised": True},
            note=f"{form!r} is an ordinary English word; this guard was generated, not written",
        )
        for form in dict.fromkeys(risky)
    )
    return replace(lexeme, guards=guards)


def synthesise_all(lexemes):
    return [synthesise(lx) for lx in lexemes]
