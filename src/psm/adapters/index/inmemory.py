"""Candidate retrieval over an in-process index.

Rebuilt from the projection on load. Three lookup paths, cheapest first:

  1. exact normalised form -> (lexeme, variant). O(1). Catches every form the
     ASR has actually produced before, which is the majority of real hits.
  2. phonetic key -> lexemes. Blocking, so scoring only ever runs against a
     handful of candidates rather than the whole store.
  3. canonical exact match -> used to detect the already-correct no-op cheaply.

The index is a cache and never authoritative; `rebuild` is always safe. It is
in-process rather than in SQLite because personal memory is small (hundreds to
low thousands of lexemes) and the port lets it be swapped for an ANN index
without the engine noticing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from psm.adapters.phonetics.dmetaphone import PhoneticStack, normalise
from psm.domain.models import Binding, Candidate, Lexeme, Span, Utterance
from psm.engine.text import ngram_spans, overlaps


class InMemoryIndex:
    name = "inmemory"

    def __init__(self, phonetics: PhoneticStack | None = None, max_distance: float = 0.34) -> None:
        self.phonetics = phonetics or PhoneticStack()
        self.max_distance = max_distance
        self._exact: dict[str, list[tuple[Lexeme, str, str]]] = defaultdict(list)
        self._keys: dict[str, set[str]] = defaultdict(set)
        self._canonical: dict[str, Lexeme] = {}
        self._by_id: dict[str, Lexeme] = {}
        self._max_tokens = 1

    # -- maintenance -------------------------------------------------------- #

    def rebuild(self, lexemes: Sequence[Lexeme]) -> None:
        self._exact.clear()
        self._keys.clear()
        self._canonical.clear()
        self._by_id.clear()
        self._max_tokens = 1
        for lexeme in lexemes:
            self.upsert(lexeme)

    def upsert(self, lexeme: Lexeme) -> None:
        self._by_id[lexeme.id] = lexeme
        self._canonical[normalise(lexeme.canonical)] = lexeme
        forms = [(lexeme.canonical, "canonical")] + [
            (v.form, v.provenance.value) for v in lexeme.variants
        ]
        for form, provenance in forms:
            norm = normalise(form)
            if not norm:
                continue
            self._exact[norm].append((lexeme, form, provenance))
            self._max_tokens = max(self._max_tokens, len(norm.split()))
            for key in self.phonetics.keys(form):
                self._keys[key].add(lexeme.id)

    def remove(self, lexeme_id: str) -> None:
        self.rebuild([lx for lx in self._by_id.values() if lx.id != lexeme_id])

    # -- lookup ------------------------------------------------------------- #

    def probe(self, text: str) -> bool:
        """The gate. Can anything in memory possibly match this text?

        Must never produce a false negative for an exact known form, and must
        be cheap enough that the common case (nothing matches) costs nothing.
        """
        if not self._exact:
            return False
        for span in ngram_spans(text, max_len=min(self._max_tokens, 5)):
            norm = normalise(span.text)
            if norm in self._exact or norm in self._canonical:
                return True
            for key in self.phonetics.keys(span.text):
                if key in self._keys:
                    return True
        return False

    def search(
        self, utterance: Utterance, *, binding: Binding, limit: int = 8
    ) -> list[Candidate]:
        text = utterance.formatted_text
        found: dict[tuple[str, int, int], Candidate] = {}

        for span in ngram_spans(text, max_len=min(self._max_tokens, 5)):
            norm = normalise(span.text)
            if not norm:
                continue

            for lexeme, form, provenance in self._exact.get(norm, []):
                self._offer(
                    found,
                    Candidate(
                        span=span,
                        lexeme=lexeme,
                        matched_form=form,
                        retrieval_score=1.0,
                        matched_via=(
                            "canonical" if provenance == "canonical" else f"{provenance}_variant"
                        ),
                    ),
                )

            # Phonetic blocking, only for spans that did not match exactly.
            if norm in self._exact:
                continue
            seen: set[str] = set()
            for key in self.phonetics.keys(span.text):
                for lexeme_id in self._keys.get(key, ()):  # noqa: SIM118
                    if lexeme_id in seen:
                        continue
                    seen.add(lexeme_id)
                    lexeme = self._by_id[lexeme_id]
                    distance, form = self._best_form(lexeme, span)
                    if distance <= self.max_distance:
                        self._offer(
                            found,
                            Candidate(
                                span=span,
                                lexeme=lexeme,
                                matched_form=form,
                                retrieval_score=1.0 - distance,
                                matched_via="phonetic",
                            ),
                        )

        ranked = sorted(
            found.values(),
            key=lambda c: (c.retrieval_score, len(c.span)),
            reverse=True,
        )
        return self._drop_dominated(ranked)[:limit]

    def _best_form(self, lexeme: Lexeme, span: Span) -> tuple[float, str]:
        best = (1.0, lexeme.canonical)
        for form in lexeme.all_forms():
            distance = self.phonetics.distance(form, span.text)
            if distance < best[0]:
                best = (distance, form)
        return best

    @staticmethod
    def _offer(found: dict, candidate: Candidate) -> None:
        key = (candidate.lexeme.id, candidate.span.start, candidate.span.end)
        existing = found.get(key)
        if existing is None or candidate.retrieval_score > existing.retrieval_score:
            found[key] = candidate

    @staticmethod
    def _drop_dominated(ranked: list[Candidate]) -> list[Candidate]:
        """Keep the best span per lexeme among overlapping ones.

        Better means higher retrieval score first, longer span as the tiebreak.
        Score has to lead: an exact two-token hit on "Adith Narayanan" must beat
        a fuzzy three-token hit on "Adith Narayanan to" that merely swallowed an
        extra word. Length only decides between equally confident matches, which
        is what stops "Shreya" being corrected inside "Shreya Bhattacharya".
        """

        def key(c: Candidate) -> tuple[float, int]:
            return (c.retrieval_score, len(c.span))

        kept: list[Candidate] = []
        for candidate in ranked:
            dominated = any(
                other is not candidate
                and other.lexeme.id == candidate.lexeme.id
                and overlaps(other.span, candidate.span)
                and key(other) > key(candidate)
                for other in ranked
            )
            if not dominated:
                kept.append(candidate)
        return kept
