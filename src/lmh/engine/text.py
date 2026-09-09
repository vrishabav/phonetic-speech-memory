"""Text mechanics: tokens, spans, windows, protected regions.

Kept separate from the engine because every one of these is a place where a
plausible-looking shortcut produces a wrong answer, and each deserves its own
test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from lmh.domain.models import Span

# `\w` does NOT match Indic combining marks - matras, virama, anusvara are all
# category Mn, and `'ा'.isalnum()` is False. Without the explicit block range,
# "शर्मा" tokenises as ['शर', 'म'] with the final matra falling outside every
# span, and a replacement then leaves a dangling vowel sign behind:
#     मीरा शर्मा  ->  मीरा शर्माा
# One character in a regex; three of the Indic test cases turned on it.
_TOKEN = re.compile(r"[\w'’@#\-\u0900-\u0D7F]+", re.UNICODE)

#: Regions whose contents are somebody else's words and must never be edited:
#: quoted text, inline code, fenced code. B9-001 and B9-002 test this.
_PROTECTED = (
    re.compile(r"`[^`]*`"),
    re.compile(r"```.*?```", re.DOTALL),
    re.compile(r"\"[^\"]*\""),
    re.compile(r"“[^”]*”"),
    re.compile(r"'[^']{12,}'"),  # long single-quoted runs only; short ones are possessives
)


@dataclass(frozen=True, slots=True)
class Token:
    text: str
    start: int
    end: int


def tokenize(text: str) -> list[Token]:
    return [Token(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def ngram_spans(text: str, max_len: int = 5) -> list[Span]:
    """Every 1..max_len token window, as character spans into `text`.

    Character spans rather than token indices because the replacement has to be
    spliced back into the original string with its original punctuation intact.
    """
    tokens = tokenize(text)
    spans: list[Span] = []
    for i in range(len(tokens)):
        for n in range(1, max_len + 1):
            if i + n > len(tokens):
                break
            start, end = tokens[i].start, tokens[i + n - 1].end
            spans.append(Span(start, end, text[start:end]))
    return spans


def protected_regions(text: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for pattern in _PROTECTED:
        regions.extend((m.start(), m.end()) for m in pattern.finditer(text))
    return regions


def in_protected_region(span: Span, text: str) -> bool:
    return any(start <= span.start and span.end <= end for start, end in protected_regions(text))


def window_tokens(text: str, span: Span, radius: int = 4) -> set[str]:
    """Casefolded tokens within `radius` tokens either side of `span`.

    Windowed rather than utterance-wide, and this is load-bearing: MX-001 has
    one occurrence of a guarded term that must be corrected and another, six
    tokens later, that must not. An utterance-wide guard cannot express that.
    """
    tokens = tokenize(text)
    inside = [i for i, t in enumerate(tokens) if t.start >= span.start and t.end <= span.end]
    if not inside:
        return set()
    lo, hi = max(0, inside[0] - radius), min(len(tokens), inside[-1] + radius + 1)
    return {
        tokens[i].text.casefold()
        for i in range(lo, hi)
        if not (inside[0] <= i <= inside[-1])
    }


def splice(text: str, replacements: list[tuple[Span, str]]) -> str:
    """Apply replacements right-to-left so earlier offsets stay valid."""
    out = text
    for span, replacement in sorted(replacements, key=lambda p: p[0].start, reverse=True):
        out = out[: span.start] + replacement + out[span.end :]
    return out


def match_case(source: str, replacement: str, *, force: bool = False) -> str:
    """Carry sentence-initial capitalisation onto a replacement.

    `force=True` means the lexeme carries a standing instruction about its own
    casing ("always lowercase, even sentence-initial"), in which case the
    canonical form wins and the surrounding sentence does not get a vote.
    """
    if force or not source or not replacement:
        return replacement
    if source.isupper() and len(source) > 1:
        return replacement
    if source[0].isupper() and replacement[0].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


def overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def changed_segments(before: str, after: str) -> list[tuple[str, str]] | None:
    """The parts of an edit that actually changed, as (old, new) pairs.

    Comparing whole strings is wrong and was a real bug: "ship it on Tuesday"
    and "ship it on Thursday" are 73% identical as text, so any threshold loose
    enough to accept a respelling also accepts a change of meaning. Only the
    replaced span tells you what kind of edit this was.

    Returns None when the edit is structurally a rewrite rather than a
    respelling:

      * whole tokens inserted or deleted - "ask X" -> "please ask X when free"
        adds words, and adding words is never a spelling correction;
      * more than two separate replaced regions, which is an edit pass, not a
        fix to one term;
      * a replaced region that changes token count by more than one, which is a
        rephrasing of a clause.
    """
    old_tokens = [t.text for t in tokenize(before)]
    new_tokens = [t.text for t in tokenize(after)]
    if not old_tokens or not new_tokens:
        return None

    segments: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=old_tokens, b=new_tokens).get_opcodes():
        if tag == "equal":
            continue
        if tag in {"insert", "delete"}:
            return None
        if abs((i2 - i1) - (j2 - j1)) > 1:
            return None
        segments.append((" ".join(old_tokens[i1:i2]), " ".join(new_tokens[j1:j2])))
        if len(segments) > 2:
            return None
    return segments
